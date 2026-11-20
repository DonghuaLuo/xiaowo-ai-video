"""Prepare and submit report-driven storyboard edits through the existing image editor."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import traceback
import uuid
from typing import Any

from project_store_services.canvas_store_queries import read_card_results
from project_store_services.model_provider_config import _project_model_config
from project_store_services.provider_models import _find_model
from project_store_services.provider_models import _model_declares_no_image_edit
from project_store_services.store_core import _emit_agent_event
from project_store_services.workflow_contract import _workflow_node, _workflow_node_can_supply_image_reference
from project_store_services.workflow_input_resolution import _workflow_material_input_owner_node, workflow_current_media_reference
from project_store_services.workflow_projection import get_canvas_workflow_projection
from project_store_services.workflow_storyboard_edits import _storyboard_image_edit_generation_config, edit_storyboard_image

_LOCK = threading.Lock()
_JOBS: dict[tuple[str, str, str], dict[str, Any]] = {}


def _issue_shot_numbers(value: Any) -> set[int]:
    text = str(value or "")
    return {
        int(match.group(1))
        for match in re.finditer(r"(?:镜头|第)\s*0*(\d+)\s*(?:镜)?", text)
    }


def correction_state(project_id: str, episode_id: str, node_id: str) -> dict[str, Any] | None:
    with _LOCK:
        return copy.deepcopy(_JOBS.get((project_id, episode_id, node_id)))


def _issues(report: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    inspection = report.get("visualInspection") or {}
    shots = contract.get("shotOrder") or []
    issues: list[dict[str, Any]] = []
    represented: set[str] = set()
    for check in inspection.get("shotChecks") or []:
        number = check.get("shotNo")
        if not isinstance(number, (int, float)) or int(number) != number or not 1 <= number <= len(shots):
            continue
        number = int(number)
        if check.get("reviewStatus") == "inconclusive":
            continue
        if check.get("present") is not False and not (check.get("present") is True and check.get("matchesDirectorPlan") is False):
            continue
        note = str(check.get("note") or "").strip()
        title = f"镜头 {number} · " + ("缺少画格" if check.get("present") is False else "不一致")
        target = str(shots[number - 1].get("storyboardFrame") or "").strip()
        issue_id = f"shot:{number}"
        if any(item["id"] == issue_id for item in issues):
            continue
        issues.append({"id": issue_id, "title": title, "note": note, "target": target, "shotNo": number, "planScope": "sequence" if check.get("present") is False else "shot"})
        represented.update({note, f"镜头 {number:02d}：{note}", f"实际分镜图缺少镜头 {number:02d}"})
    expected = inspection.get("expectedPanelCount")
    observed = inspection.get("observedPanelCount")
    if expected != observed:
        issues.append({"id": "panel-count", "title": "画格数量不一致", "note": f"计划 {expected} 格，识别 {observed} 格", "target": f"按分镜脚本恢复 {expected} 个画格及其顺序。", "planScope": "sequence"})
        represented.add(f"实际观察到 {observed} 个镜头画格，分镜脚本要求 {expected} 个")
    sequence_detail_shot_sets: list[set[int]] = []
    for index, detail in enumerate(inspection.get("blockingIssueDetails") or []):
        if not isinstance(detail, dict) or detail.get("scope") not in {"shot", "sequence"}:
            continue
        shot_numbers = {
            int(value)
            for value in detail.get("shotNos") or []
            if isinstance(value, (int, float)) and int(value) == value
        }
        if not shot_numbers:
            continue
        note = str(detail.get("correction") or detail.get("observed") or detail.get("required") or "").strip()
        if not note:
            continue
        if detail["scope"] == "shot":
            for shot_number in sorted(shot_numbers):
                if not 1 <= shot_number <= len(shots):
                    continue
                issue_id = f"shot:{shot_number}"
                if any(item["id"] == issue_id for item in issues):
                    continue
                target = str(shots[shot_number - 1].get("storyboardFrame") or "").strip()
                issues.append({
                    "id": issue_id,
                    "title": f"镜头 {shot_number} · 不一致",
                    "note": note,
                    "target": target,
                    "shotNo": shot_number,
                    "planScope": "shot",
                })
                represented.update({note, f"镜头 {shot_number:02d}：{note}"})
            continue
        sequence_detail_shot_sets.append(shot_numbers)
        issues.append({
            "id": f"sequence:{index}",
            "title": "镜头连续性问题",
            "note": note,
            "target": "按所列镜头的分镜脚本保持画格顺序、静态空间关系和动作阶段一致。",
            "shotNos": sorted(shot_numbers),
            "planScope": "sequence",
        })
        represented.add(note)
    failed_shots = {int(item["shotNo"]) for item in issues if "shotNo" in item}
    for index, note in enumerate(dict.fromkeys(report.get("blockers") or [])):
        note = str(note or "").strip()
        # The quality gate already has one canonical issue per failed shot.
        # A single failed-shot reference is a duplicate of the canonical
        # shotChecks issue. Keep multi-shot references because they describe
        # continuity or ordering and require the full director plan.
        issue_shot_numbers = _issue_shot_numbers(note)
        if issue_shot_numbers and any(issue_shot_numbers == detail_shots for detail_shots in sequence_detail_shot_sets):
            continue
        if len(issue_shot_numbers) == 1 and issue_shot_numbers.issubset(failed_shots):
            continue
        if note and note not in represented:
            issues.append({"id": f"overall:{index}", "title": "整体结论", "note": note, "target": "", "planScope": "sequence"})
    return issues


def get_correction_context(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    node_id = str(payload.get("nodeId") or "").strip()
    version_id = str(payload.get("versionId") or "").strip()
    if not node_id or not version_id:
        raise ValueError("缺少分镜图或版本")
    workflow = get_canvas_workflow_projection(project_id, episode_id)
    node = _workflow_node(workflow, node_id)
    if not node or node.get("type") != "storyboard.image":
        raise ValueError("只能修正分镜图")
    version = next((row for row in read_card_results(project_id, episode_id, node_id) if row.get("id") == version_id), None)
    if not version or not version.get("media"):
        raise ValueError("分镜图版本不存在或缺少原图")
    report = version.get("qualityResult") or {}
    contract = (version.get("payload") or {}).get("storyboardInterpretationContract") or {}
    if report.get("versionId") != version_id or report.get("status") != "failed" or not report.get("visualInspection"):
        raise ValueError("此版本没有可用于修正的不一致报告，请先完成检查")
    if not contract.get("shotOrder"):
        raise ValueError("此版本缺少分镜脚本快照，无法按报告修正")
    checks = {row.get("shotNo"): row for row in report["visualInspection"].get("shotChecks") or []}
    if any(checks.get(index, {}).get("present") not in (True, False) or checks.get(index, {}).get("matchesDirectorPlan") not in (True, False) for index in range(1, len(contract["shotOrder"]) + 1)):
        raise ValueError("逐镜头检查尚未完成，请先重新检查")
    config = _storyboard_image_edit_generation_config(workflow, node_id, {}, version)
    _, capabilities, model_config = _project_model_config(project_id)
    model_id = str(config.get("modelId") or config.get("model_id") or (model_config.get("image") or {}).get("model_id") or "")
    model = _find_model(model_id, "image", capabilities)
    model_error = "" if model and not _model_declares_no_image_edit(model) else "此版本的图片模型不可用或不支持图片编辑，请在图片编辑面板选择支持编辑的模型。"
    limit = (model or {}).get("max_reference_images")
    max_references = int(limit) if limit is not None else None
    owner = _workflow_material_input_owner_node(workflow, node)
    assets = []
    seen = set()
    seen_media = set()
    for edge in workflow.get("edges") or []:
        if edge.get("target") not in {node_id, owner.get("id")}:
            continue
        source_id = str(edge.get("source") or "")
        source = _workflow_node(workflow, source_id)
        if source_id in seen or not _workflow_node_can_supply_image_reference(source) or (source or {}).get("type") == "storyboard.image":
            continue
        if (edge.get("data") or {}).get("kind") not in (None, "", "material"):
            continue
        seen.add(source_id)
        data = source.get("data") or {}
        media = workflow_current_media_reference(project_id, episode_id, workflow, source_id)
        media_key = str((media or {}).get("id") or (media or {}).get("path") or (media or {}).get("url") or "")
        if media_key and media_key in seen_media:
            continue
        if media_key:
            seen_media.add(media_key)
        identity = json.dumps([source_id, media], ensure_ascii=False, sort_keys=True)
        assets.append({
            "id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
            "nodeId": source_id,
            "name": str(data.get("assetName") or data.get("title") or "关联资产"),
            "media": media,
            "available": bool(media),
        })
    return {
        "success": True, "versionId": version_id, "reportId": report.get("id"),
        "issues": _issues(report, contract), "assets": assets,
        "baseMedia": version["media"], "modelName": (model or {}).get("label") or model_id,
        "maxReferenceImages": max_references, "modelError": model_error,
        "directorPlan": contract["shotOrder"],
    }


def start_correction(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    context = get_correction_context(project_id, episode_id, payload)
    if payload.get("reportId") != context["reportId"]:
        raise ValueError("检查报告已更新，请重新打开修正弹窗")
    if context["modelError"]:
        raise ValueError(context["modelError"])
    issue_ids = payload.get("issueIds")
    asset_ids = payload.get("assetIds")
    if not isinstance(issue_ids, list) or not issue_ids or not all(isinstance(item, str) for item in issue_ids):
        raise ValueError("请至少选择一个需要修正的问题")
    if not isinstance(asset_ids, list) or not all(isinstance(item, str) for item in asset_ids):
        raise ValueError("参考资产选择无效")
    issue_map = {item["id"]: item for item in context["issues"]}
    asset_map = {item["id"]: item for item in context["assets"] if item["available"]}
    if not set(issue_ids).issubset(issue_map) or not set(asset_ids).issubset(asset_map):
        raise ValueError("问题或参考资产已变化，请重新打开修正弹窗")
    selected = [issue_map[item] for item in dict.fromkeys(issue_ids)]
    assets = [asset_map[item] for item in dict.fromkeys(asset_ids)]
    limit = context["maxReferenceImages"]
    if limit is not None and 1 + len(assets) > limit:
        raise ValueError(f"包含原图共 {1 + len(assets)} 张，当前模型最多支持 {limit} 张参考图")
    supplement = str(payload.get("supplement") or "").strip()
    if len(supplement) > 10000:
        raise ValueError("补充要求不能超过 10000 字")
    needs_sequence = any(item["planScope"] == "sequence" for item in selected)
    selected_shots = {item["shotNo"] for item in selected if "shotNo" in item}
    plan_requirements = [
        {"镜头": index, "画面要求": str(shot.get("storyboardFrame") or "")}
        for index, shot in enumerate(context["directorPlan"], start=1)
        if needs_sequence or index in selected_shots
    ]
    problems = []
    for item in selected:
        problem = {
            "问题": item["title"],
        }
        if item.get("shotNo"):
            problem["范围"] = f"镜头 {int(item['shotNo'])}"
        elif item.get("shotNos"):
            problem["范围"] = "、".join(f"镜头 {int(number)}" for number in item["shotNos"])
        if item.get("target"):
            problem["必须达到"] = item["target"]
        problems.append(problem)
    sections = [
        "【任务与输入】\n依据生成此版本时的分镜脚本修正分镜图。第一张图片是唯一待修改原图。"
        "回读报告只用于选择修正范围，不是内容来源；不要复述、扩写或重现报告中的观察、摘要和不确定描述。"
        "以必须达到和分镜脚本为唯一内容依据。",
        "【必须修正】\n" + json.dumps(problems, ensure_ascii=False, indent=2),
        ("【必须达到：完整分镜脚本与画格顺序】\n" if needs_sequence else "【必须达到：所选镜头画面要求】\n")
        + json.dumps(plan_requirements, ensure_ascii=False, indent=2),
    ]
    if supplement:
        sections.append("【用户补充要求】\n" + supplement)
    if assets:
        sections.append("【附加参考图】\n" + "\n".join(f"图片 {index + 2}：{item['name']}；仅用于对应主体的外观、场景或道具参考。" for index, item in enumerate(assets)))
    sections.append("【必须保持】\n只修改选中的问题及用户明确要求的细节。保留其他画格的内容、角色身份、风格和画幅；只有选中的问题明确涉及数量、布局或顺序时才调整分镜结构。补充要求用于细化修正，不改写分镜脚本的剧情和镜头目标。")
    node_id = str(payload["nodeId"])
    version_id = str(payload["versionId"])
    key = (project_id, episode_id, node_id)
    operation = {"id": f"correction-{uuid.uuid4().hex[:12]}", "status": "running", "baseVersionId": version_id}
    with _LOCK:
        if (_JOBS.get(key) or {}).get("status") == "running":
            raise ValueError("此分镜图正在修正，请等待当前任务完成")
        _JOBS[key] = operation

    def notify() -> None:
        _emit_agent_event("project_changed", {"action": "storyboard_correction_changed", "projectId": project_id, "episodeId": episode_id, "nodeId": node_id, "versionId": version_id})

    def worker() -> None:
        try:
            result = edit_storyboard_image(project_id, episode_id, node_id, {
                "baseVersionId": version_id, "prompt": "\n\n".join(sections),
                "referenceFiles": [{**copy.deepcopy(item["media"]), "name": item["name"]} for item in assets],
                "consistencyCorrection": {"reportId": context["reportId"], "issues": selected, "supplement": supplement, "assets": [{"nodeId": item["nodeId"], "mediaId": item["media"].get("id"), "name": item["name"]} for item in assets]},
                "returnProductionStatus": False,
            })
            if result.get("cancelled") or result.get("success") is False:
                raise RuntimeError("correction did not complete")
            with _LOCK:
                operation.update(status="completed", versionId=(result.get("version") or {}).get("id"))
        except Exception:
            print(traceback.format_exc(), flush=True)
            with _LOCK:
                operation.update(status="failed", message="修正失败，原图已保留。请检查生成任务中的失败原因后重试。")
        finally:
            notify()

    try:
        notify()
        threading.Thread(target=worker, name="storyboard-consistency-correction", daemon=True).start()
    except Exception:
        with _LOCK:
            operation.update(status="failed", message="未能启动修正任务，请重试。")
        notify()
        raise
    with _LOCK:
        return {"success": True, "operation": copy.deepcopy(operation)}
