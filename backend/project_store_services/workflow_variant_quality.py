# -*- coding: utf-8 -*-
"""工作流领域实际实现。"""
from __future__ import annotations

from .canvas_store_queries import read_card_results
from .canvas_store_queries import read_workflow_card_neighborhood_v4
from .canvas_store_results import commit_canvas_result_v4
from .canvas_store_database import _SQLITE_WRITE_LOCK
from .model_request_logs import STAGE_STORYBOARD_IMAGE_READBACK_PROMPT
from .model_text_client import _model_json_or_none
from .model_provider_config import _get_effective_config
from .production_status import update_episode_production_status
from .splitting_templates import _string_list
from .store_core import _now
from .store_core import _write_json
from .store_core import _JSON_WRITE_LOCK
from .store_core import _emit_agent_event
from .workflow_contract import _assert_canvas_mutation_does_not_return_workflow
from .workflow_contract import _workflow_data_active_version_id
from .workflow_contract import _workflow_is_video_task_type
from .workflow_contract import _workflow_mutation_returns_production_status
from .workflow_contract import _workflow_node
from .workflow_input_resolution import _workflow_node_data
from .workflow_storyboard_versions import _read_variant_quality_results
from .workflow_storyboard_versions import _variant_quality_results_path
from .workflow_storyboard_versions import _emit_canvas_result_commit_event
from typing import Any
import copy
import json
import math
import re
import traceback
import threading
import uuid


_STORYBOARD_READBACK_LOCK = threading.Lock()
_STORYBOARD_READBACK_RUNNING: set[tuple[str, str, str, str]] = set()
_STORYBOARD_READBACK_ERRORS: dict[tuple[str, str, str, str], str] = {}


def _notify_storyboard_consistency_check(key: tuple[str, str, str, str]) -> None:
    project_id, episode_id, node_id, version_id = key
    _emit_agent_event("project_changed", {
        "action": "storyboard_consistency_check_changed",
        "projectId": project_id, "episodeId": episode_id,
        "nodeId": node_id, "versionId": version_id,
        "changedResources": ["variant_quality_results"],
    })


def get_storyboard_consistency_report(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    node_id = str(payload.get("nodeId") or "").strip()
    version_id = str(payload.get("versionId") or "").strip()
    if not node_id or not version_id:
        raise ValueError("缺少 nodeId 或 versionId")
    config = _get_effective_config(project_id)
    versions = read_card_results(project_id, episode_id, node_id)
    version = next((item for item in versions if item.get("id") == version_id), None)
    if not version:
        raise FileNotFoundError("图片版本不存在")
    report = version.get("qualityResult")
    if not isinstance(report, dict) or report.get("versionId") != version_id:
        report = None
    with _STORYBOARD_READBACK_LOCK:
        checking = (project_id, episode_id, node_id, version_id) in _STORYBOARD_READBACK_RUNNING
        error = _STORYBOARD_READBACK_ERRORS.get((project_id, episode_id, node_id, version_id))
    from utils.storyboard_consistency_correction import correction_state
    return {
        "success": True,
        "enabled": (config.get("storyboard") or {}).get("consistency_report_enabled", True) is True,
        "checking": checking,
        "report": copy.deepcopy(report),
        "error": error,
        "correction": correction_state(project_id, episode_id, node_id),
    }


def start_storyboard_consistency_check(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    node_id = str(payload.get("nodeId") or "").strip()
    version_id = str(payload.get("versionId") or "").strip()
    workflow = read_workflow_card_neighborhood_v4(project_id, episode_id, node_id, detail="full")
    if (_workflow_node(workflow, node_id) or {}).get("type") != "storyboard.image":
        raise ValueError("只能检查分镜图")
    if not version_id or not any(item.get("id") == version_id for item in read_card_results(project_id, episode_id, node_id)):
        raise ValueError("分镜图版本不存在")
    key = (project_id, episode_id, node_id, version_id)
    with _STORYBOARD_READBACK_LOCK:
        if key in _STORYBOARD_READBACK_RUNNING:
            return {"success": True, "checking": True}
        _STORYBOARD_READBACK_RUNNING.add(key)
        _STORYBOARD_READBACK_ERRORS.pop(key, None)

    def worker() -> None:
        try:
            _run_storyboard_readback(project_id, episode_id, {"nodeId": node_id, "versionId": version_id}, key)
        except Exception:
            # The shared runner records the failure and emits the terminal event.
            pass

    try:
        threading.Thread(target=worker, name="storyboard-consistency-check", daemon=True).start()
    except Exception as exc:
        print(traceback.format_exc(), flush=True)
        with _STORYBOARD_READBACK_LOCK:
            _STORYBOARD_READBACK_RUNNING.discard(key)
            _STORYBOARD_READBACK_ERRORS[key] = "未能启动检查，请重新检查。"
        _notify_storyboard_consistency_check(key)
        raise RuntimeError("未能启动检查，请重新检查。") from exc
    return {"success": True, "checking": True}


def _write_variant_quality_results(project_id: str, episode_id: str, node_id: str, results: list[dict[str, Any]]) -> None:
    _write_json(
        _variant_quality_results_path(project_id, episode_id, node_id),
        {
            "schemaVersion": 1,
            "episodeId": episode_id,
            "nodeId": str(node_id or "").strip(),
            "updatedAt": _now(),
            "results": results[-500:],
        },
    )


def save_variant_quality_result(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Keep report reads and writes atomic with generation and canvas updates.
    with _JSON_WRITE_LOCK, _SQLITE_WRITE_LOCK:
        return _save_variant_quality_result(project_id, episode_id, payload)


def _save_variant_quality_result(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "保存候选质检结果")
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    version_id = str(payload.get("versionId") or payload.get("version_id") or "").strip()
    if not node_id or not version_id:
        raise ValueError("缺少 nodeId 或 versionId")
    status = str(payload.get("status") or payload.get("result") or "passed").strip().lower() or "passed"
    waived = bool(payload.get("waived") or payload.get("exempted"))
    waiver_reason = str(payload.get("waiverReason") or payload.get("waiver_reason") or "").strip()
    if status in {"failed", "blocked"} and waived and not waiver_reason:
        raise ValueError("质检 blocker 豁免需要填写原因")
    now = _now()
    result = {
        "id": str(payload.get("id") or f"quality-{uuid.uuid4().hex[:10]}"),
        "episodeId": episode_id,
        "nodeId": node_id,
        "versionId": version_id,
        "status": status,
        "score": payload.get("score"),
        "blockers": payload.get("blockers") if isinstance(payload.get("blockers"), list) else [],
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
        "waived": waived,
        "waiverReason": waiver_reason,
        "note": str(payload.get("note") or ""),
        "source": str(payload.get("source") or "user"),
        "createdAt": now,
        "updatedAt": now,
    }
    for optional_key in (
        "inspectionLevel",
        "visualInspection",
        "reviewScope",
        "sourceTrace",
        "transportChecks",
        "modelReview",
        "metadata",
        "reportOnly",
    ):
        if optional_key in payload:
            result[optional_key] = copy.deepcopy(payload.get(optional_key))
    results = [
        item
        for item in _read_variant_quality_results(project_id, episode_id, node_id)
        if not (
            str(item.get("nodeId") or "") == node_id
            and str(item.get("versionId") or "") == version_id
        )
    ] + [result]

    workflow = read_workflow_card_neighborhood_v4(project_id, episode_id, node_id, detail="full")
    versions = read_card_results(project_id, episode_id, node_id)
    if not isinstance(versions, list):
        versions = []
    updated_version = None
    for version in versions:
        if (
            isinstance(version, dict)
            and str(version.get("id") or "") == version_id
            and str(version.get("nodeId") or "") == node_id
        ):
            version["qualityResult"] = copy.deepcopy(result)
            updated_version = version
            break
    if not updated_version:
        raise FileNotFoundError("版本不存在")
    _write_variant_quality_results(project_id, episode_id, node_id, results)

    node = _workflow_node(workflow, node_id)
    return_production_status = _workflow_mutation_returns_production_status(payload)
    production_status = None
    active_version_id = _workflow_data_active_version_id(_workflow_node_data(workflow, node_id))
    if not active_version_id:
        active_version_id = next(
            (
                str(item.get("id") or "")
                for item in versions
                if isinstance(item, dict) and bool(item.get("active"))
            ),
            "",
        )
    if node and version_id == active_version_id:
        data = node.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            node["data"] = data
        quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
        quality["lastVariantQualityResult"] = copy.deepcopy(result)
        if status in {"failed", "blocked"} and not result["waived"] and not result.get("reportOnly"):
            quality["variantQualityBlocked"] = True
        else:
            quality["variantQualityBlocked"] = False
        data["quality"] = quality
    patched_nodes = [copy.deepcopy(node)] if isinstance(node, dict) and version_id == active_version_id else []
    save_result = commit_canvas_result_v4(
        project_id,
        episode_id,
        node_id=node_id,
        versions=versions,
        active_version_id=active_version_id,
        nodes=patched_nodes,
        changed_resources=["variant_quality_results", "canvas_node", "canvas_version"],
    )
    workflow["version"] = save_result.get("workflowVersion") or workflow.get("version")
    _emit_canvas_result_commit_event(
        project_id, episode_id, node_id, updated_version, patched_nodes, [], save_result,
    )
    if return_production_status:
        try:
            status_result = update_episode_production_status(project_id, episode_id)
            production_status = status_result.get("status") if isinstance(status_result, dict) else None
        except Exception:
            print(traceback.format_exc(), flush=True)
            production_status = None
    workflow_resource = "canvas_node" if patched_nodes else ""
    result = {
        "success": True,
        "episodeId": episode_id,
        "qualityResult": result,
        "version": updated_version,
        "node": copy.deepcopy(node) if isinstance(node, dict) else None,
        "workflowVersion": save_result.get("workflowVersion"),
        "changedResources": [
            "variant_quality_results",
            "canvas_version",
            *([workflow_resource] if workflow_resource else []),
            *(["episode_production_status"] if production_status else []),
        ],
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id},
    }
    for key in ("txId", "seq", "revision", "baseRevision", "opType", "records"):
        if save_result.get(key) is not None:
            result[key] = copy.deepcopy(save_result.get(key))
    if return_production_status:
        result["productionStatus"] = production_status
    return result


def _version_has_media(version: dict[str, Any]) -> bool:
    media = version.get("media")
    if not isinstance(media, dict):
        return False
    return any(
        bool(media.get(key))
        for key in ("path", "url", "filePath", "file_path", "relativePath", "relative_path", "dataUrl", "data_url")
    )


def _version_provider_request(version: dict[str, Any]) -> dict[str, Any]:
    debug = version.get("generationDebug") if isinstance(version.get("generationDebug"), dict) else {}
    payload = version.get("payload") if isinstance(version.get("payload"), dict) else {}
    for source in (debug, payload):
        provider_request = source.get("providerRequest") if isinstance(source.get("providerRequest"), dict) else {}
        if provider_request:
            return copy.deepcopy(provider_request)
    return {}


def auto_review_variant_quality(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    version_id = str(payload.get("versionId") or payload.get("version_id") or "").strip()
    if not node_id or not version_id:
        raise ValueError("缺少 nodeId 或 versionId")
    workflow = read_workflow_card_neighborhood_v4(project_id, episode_id, node_id, detail="full")
    node = _workflow_node(workflow, node_id) or {}
    if node.get("type") != "storyboard.image":
        return _review_variant_quality(project_id, episode_id, payload)
    config = _get_effective_config(project_id)
    if (config.get("storyboard") or {}).get("consistency_report_enabled", True) is not True:
        return {"success": True, "skipped": True, "reason": "consistency_report_disabled"}
    key = (project_id, episode_id, node_id, version_id)
    with _STORYBOARD_READBACK_LOCK:
        if key in _STORYBOARD_READBACK_RUNNING:
            return {"success": True, "skipped": True, "reason": "consistency_report_running"}
        _STORYBOARD_READBACK_RUNNING.add(key)
        _STORYBOARD_READBACK_ERRORS.pop(key, None)

    return _run_storyboard_readback(project_id, episode_id, payload, key)


def _run_storyboard_readback(project_id: str, episode_id: str, payload: dict[str, Any], key: tuple[str, str, str, str]) -> dict[str, Any]:
    try:
        _notify_storyboard_consistency_check(key)
        return _review_variant_quality(project_id, episode_id, payload)
    except Exception:
        print(traceback.format_exc(), flush=True)
        with _STORYBOARD_READBACK_LOCK:
            _STORYBOARD_READBACK_ERRORS[key] = "检查未完成，请重新检查。"
        raise
    finally:
        with _STORYBOARD_READBACK_LOCK:
            _STORYBOARD_READBACK_RUNNING.discard(key)
        _notify_storyboard_consistency_check(key)


def _review_variant_quality(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    version_id = str(payload.get("versionId") or payload.get("version_id") or "").strip()
    if not node_id or not version_id:
        raise ValueError("缺少 nodeId 或 versionId")
    workflow = read_workflow_card_neighborhood_v4(project_id, episode_id, node_id, detail="full")
    node = _workflow_node(workflow, node_id)
    if not node:
        raise FileNotFoundError("节点不存在")
    node_type = str(node.get("type") or "").strip()
    node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
    versions = read_card_results(project_id, episode_id, node_id)
    if not isinstance(versions, list):
        versions = []
    version = next(
        (
            item
            for item in versions
            if isinstance(item, dict)
            and str(item.get("nodeId") or "") == node_id
            and str(item.get("id") or "") == version_id
        ),
        None,
    )
    if not version:
        raise FileNotFoundError("版本不存在")

    blockers: list[str] = []
    warnings: list[str] = []
    status = str(version.get("status") or "").strip().lower()
    if status in {"failed", "blocked", "cancelled", "canceled"}:
        blockers.append("候选版本生成失败或已取消")
    elif status == "processing":
        blockers.append("候选版本仍在生成中，暂不能设为 winner")

    requires_media = (
        node_type in {"storyboard.image", "video.result"}
        or _workflow_is_video_task_type(node_type)
    )
    if requires_media and not _version_has_media(version):
        blockers.append("候选版本缺少可用媒体文件")
    version_payload = version.get("payload") if isinstance(version.get("payload"), dict) else {}
    inspection_level = "metadata_transport"
    visual_inspection: dict[str, Any] | None = None
    model_review: dict[str, Any] | None = None
    visual_review_inconclusive = False
    if node_type == "storyboard.image":
        storyboard_contract = (
            version_payload.get("storyboardInterpretationContract")
            if isinstance(version_payload.get("storyboardInterpretationContract"), dict)
            else {}
        )
        contract_shots = (
            storyboard_contract.get("shotOrder")
            if isinstance(storyboard_contract.get("shotOrder"), list)
            else []
        )
        expected_shot_count = len([shot for shot in contract_shots if isinstance(shot, dict)])
        panel_count = version_payload.get("panelCount") or version_payload.get("panel_count")
        try:
            panel_count_value = int(panel_count)
        except (TypeError, ValueError):
            panel_count_value = 0
        if expected_shot_count <= 0:
            blockers.append("分镜图版本缺少结构化导演镜头合同快照")
        elif panel_count_value and panel_count_value != expected_shot_count:
            warnings.append(f"分镜图镜头数可能不一致：计划 {expected_shot_count} 个，生成载荷 {panel_count_value} 个")
        if expected_shot_count > 3:
            warnings.append("单张故事版分镜图镜头数量较多，请重点核对画面清晰度和编号对应关系")
        if _version_has_media(version) and expected_shot_count > 0:
            try:
                visual_inspection = _storyboard_visual_readback(
                    project_id,
                    episode_id,
                    node_id,
                    version,
                )
                inspection_level = "visual_readback"
                visual_review_inconclusive = bool(visual_inspection.get("inconclusive"))
                blockers.extend(_string_list(visual_inspection.get("blockingIssues")))
                warnings.extend(_string_list(visual_inspection.get("warnings")))
                model_review = (
                    copy.deepcopy(visual_inspection.get("modelMeta"))
                    if isinstance(visual_inspection.get("modelMeta"), dict)
                    else None
                )
            except Exception:
                print(traceback.format_exc(), flush=True)
                visual_review_inconclusive = True
                warnings.append("分镜图视觉回读未完成，请重新检查；详细原因已记录到后台日志。")

    if _workflow_is_video_task_type(node_type):
        provider_request = _version_provider_request(version)
        reference_plan = provider_request.get("referencePlan") if isinstance(provider_request.get("referencePlan"), dict) else {}
        strategy = str(provider_request.get("strategy") or node_data.get("strategy") or "").strip()
        video_input_plan = (
            provider_request.get("videoInputPlan")
            if isinstance(provider_request.get("videoInputPlan"), dict)
            else node_data.get("videoInputPlan")
            if isinstance(node_data.get("videoInputPlan"), dict)
            else {}
        )
        video_input_mode = str(video_input_plan.get("mode") or provider_request.get("videoInputMode") or "").strip()
        resolved_reference_count = int(reference_plan.get("resolvedReferenceCount") or 0)
        transport_reference_count = int(reference_plan.get("transportReferenceCount") or 0)
        adapter_transport = str(reference_plan.get("adapterTransport") or "").strip()
        if strategy != "text_to_video_draft" and resolved_reference_count > 0 and transport_reference_count <= 0:
            warnings.append("视频候选绑定了参考图，但供应商请求记录未显示实际传输参考图")
        if video_input_mode in {"image_reference", "native_keyframe"} and resolved_reference_count <= 0:
            warnings.append("视频候选缺少图片参考输入记录")
        if adapter_transport == "text_prompt_only" and video_input_mode in {"image_reference", "native_keyframe"}:
            warnings.append("视频模型本次记录为纯文本输入，请人工检查角色和镜头连续性")
        adapter_note = str(reference_plan.get("adapterNote") or "").strip()
        if adapter_note:
            warnings.append(adapter_note)

    blockers = list(dict.fromkeys(item for item in blockers if item))
    warnings = list(dict.fromkeys(item for item in warnings if item))
    blocker_count = len(blockers)
    warning_count = len(warnings)
    score = max(0, min(100, 100 - blocker_count * 35 - warning_count * 8))
    if visual_review_inconclusive and not blockers:
        score = min(score, 70)
    quality_status = "failed" if blockers else "inconclusive" if visual_review_inconclusive else "passed"
    quality_payload = {
        "nodeId": node_id,
        "versionId": version_id,
        "status": quality_status,
        "score": score,
        "blockers": blockers,
        "warnings": warnings,
        "note": (
            "分镜图自动质检会读取实际图片并逐镜头核对导演镜头合同；其他生成结果仍由用户判断视觉质量。"
            if node_type == "storyboard.image"
            else "自动质检只检查媒体、输入闭环和参考图传输；生成结果的视觉质量由用户直接判断。"
        ),
        "inspectionLevel": inspection_level,
        "source": "auto_production_quality_gate",
        "reportOnly": (
            node_type == "storyboard.image"
            and not bool(visual_inspection and visual_inspection.get("blockingIssueDetails"))
        ),
    }
    if visual_inspection is not None:
        quality_payload["visualInspection"] = {
            key: copy.deepcopy(value)
            for key, value in visual_inspection.items()
            if key != "modelMeta"
        }
    if model_review is not None:
        quality_payload["modelReview"] = model_review
    result = save_variant_quality_result(project_id, episode_id, quality_payload)
    result["autoReview"] = {
        "blockerCount": blocker_count,
        "warningCount": warning_count,
        "score": score,
    }
    return result


STORYBOARD_VISUAL_READBACK_SCHEMA: dict[str, Any] = {
    "name": "storyboard_visual_readback",
    "description": "分镜图与分镜脚本的一对一视觉回读结果。",
    "fields": [
        {
            "name": "passed",
            "type": "boolean",
            "required": True,
            "description": "只有实际图片中的镜头数量、顺序、关键画面、适用类型效果和项目绘制媒介均符合合同才为 true。",
        },
        {
            "name": "observedPanelCount",
            "type": "number",
            "required": True,
            "description": "从实际图片中观察到的主要镜头画格数量。",
        },
        {
            "name": "shotChecks",
            "type": "array",
            "required": True,
            "description": "按分镜脚本顺序逐镜头核验。",
            "items": {
                "type": "object",
                "fields": [
                    {"name": "shotNo", "type": "number", "required": True, "description": "分镜脚本中的镜头编号。"},
                    {"name": "present", "type": "boolean", "required": True, "description": "该编号的主要画格是否在实际图片中存在；不存在时为 false。"},
                    {"name": "reviewStatus", "type": "string", "required": True, "enum": ["confirmed", "inconclusive"], "description": "confirmed 表示关键区域清晰可见并完成核验；inconclusive 表示看不清、被遮挡或无法确认。"},
                    {"name": "matchesDirectorPlan", "type": "boolean", "required": True, "description": "仅在 reviewStatus=confirmed 时使用；确认违反起始画面、适用类型效果或项目绘制媒介才为 false。reviewStatus=inconclusive 时保持 true。"},
                    {"name": "note", "type": "string", "required": True, "description": "只记录该画格的可见证据或明确冲突；不要重复整体问题。"},
                ],
            },
        },
        {
            "name": "blockingIssueDetails",
            "type": "array",
            "required": False,
            "description": "机器可读的问题范围。scope=shot 表示单镜头问题，scope=sequence 表示镜头之间的静态连续性、数量、顺序或版式问题；每项必须填写涉及的镜头编号、实际观察、计划要求和修正动作。",
            "items": {
                "type": "object",
                "fields": [
                    {"name": "scope", "type": "string", "required": True, "enum": ["shot", "sequence"]},
                    {"name": "shotNos", "type": "array", "required": True, "items": {"type": "number"}},
                    {"name": "observed", "type": "string", "required": True},
                    {"name": "required", "type": "string", "required": True},
                    {"name": "correction", "type": "string", "required": True},
                ],
            },
        },
        {
            "name": "blockingIssues",
            "type": "array",
            "required": False,
            "description": "给人看的阻断问题摘要。只列出实际图片中清晰可见、且直接违反镜头合同或相邻画格静态连续性的阻断问题；单镜头问题每个最多一条，跨镜头问题必须与 blockingIssueDetails 对应。没有阻断问题时返回空数组，也允许省略。",
            "items": {"type": "string"},
        },
        {
            "name": "warnings",
            "type": "array",
            "required": False,
            "description": "非阻断警告列表。只列出不影响镜头合同的清晰度或可读性提醒；没有警告时返回空数组，也允许省略。",
            "items": {"type": "string"},
        },
    ],
}


def _readback_issue_shot_numbers(value: Any) -> set[int]:
    """Return all shot numbers named by a readback issue."""
    text = str(value or "")
    return {
        int(match.group(1))
        for match in re.finditer(r"(?:镜头|第)\s*0*(\d+)\s*(?:镜)?", text)
    }


def _storyboard_visual_readback(
    project_id: str,
    episode_id: str,
    node_id: str,
    version: dict[str, Any],
) -> dict[str, Any]:
    version_payload = version.get("payload") if isinstance(version.get("payload"), dict) else {}
    contract = (
        version_payload.get("storyboardInterpretationContract")
        if isinstance(version_payload.get("storyboardInterpretationContract"), dict)
        else {}
    )
    shot_order = contract.get("shotOrder") if isinstance(contract.get("shotOrder"), list) else []
    if not shot_order:
        raise RuntimeError("分镜图缺少导演镜头合同快照，无法执行视觉回读")
    media = version.get("media") if isinstance(version.get("media"), dict) else {}
    if not media:
        raise RuntimeError("分镜图缺少可读取的图片媒体")
    expected_panel_count = int(contract.get("panelCount") or len(shot_order))
    review_shots = [
        {
            "shotNo": index,
            "timeRange": str(row.get("timeRange") or "").strip(),
            "storyboardFrame": str(row.get("storyboardFrame") or "").strip(),
            "typeEffectPreset": str(row.get("typeEffectPreset") or "").strip(),
        }
        for index, row in enumerate(shot_order, start=1)
        if isinstance(row, dict)
    ]
    project_style = _get_effective_config(project_id).get("style") or {}
    visual_medium = str(project_style.get("prompt") or "").strip() if isinstance(project_style, dict) else ""
    prompt = (
        "【任务】\n检查随附的实际分镜图是否逐镜头遵守分镜脚本。只做可见事实核验，不重新设计镜头，"
        "不评价与镜头合同无关的审美或内容安全。\n\n"
        + (f"【项目统一视觉】\n{visual_medium}\n只核对可见的绘制媒介是否保持一致，不评价主观审美。\n\n" if visual_medium else "")
        + f"【画格识别】\n应有且只能有 {expected_panel_count} 个主要镜头画格；先根据清晰的分隔线、版式和画格边界识别画格，"
        "忽略标题、辅助栏、装饰和画格之间的溢出内容。核对主要画格的数量和从左到右（或从上到下）的顺序。\n\n"
        "【核验口径】\n"
        "1. 每个画格只与同编号的 storyboardFrame、typeEffectPreset 及统一项目视觉比较。必须核对起始画面中明确要求的主体/对象、场景、景别与机位、"
        "构图和空间关系、关键姿态或表情、关键道具以及静态画面落点。"
        "\n"
        "2. 人声、音效、音乐、连续运镜、动作发生前后、时间经过和画面外信息不是静态分镜图的必见内容。"
        "不要因为这些内容没有被画出而判错。\n"
        "3. 只有实际图片中清晰可见、能够指出具体位置并直接违反镜头要求的冲突，才将 matchesDirectorPlan 设为 false。"
        "看不清、被遮挡或无法从图片确认时，reviewStatus 必须设为 inconclusive，matchesDirectorPlan 保持 true，并在 note 中说明无法确认的区域；这不是通过结论。\n"
        "4. 完成单镜头核验后，额外检查分镜脚本明确要求的相邻画格静态连续性，例如前景是否提前出现、人物与镜头的空间关系、动作阶段或画面落点是否跨格矛盾。"
        "只依据实际可见画格和分镜脚本，不推断连续运镜、时间经过或画面外信息。\n"
        "5. 不要把相邻画格的内容误串到单镜头判断；不要把前景轻微重叠、服装纹理或姿态细节误判为改变了构图或动作，"
        "除非它确实占据画面并清楚改变了合同要求。\n"
        "画内文字只核对载体、可见时机及影响剧情的关键意思；图片模型的字形、标点和逐字精度不作阻断。"
        "若关键意思可辨且与镜头要求一致，不能只因缺少标点或个别字形差异判失败。\n"
        "6. blockingIssueDetails 是问题范围的机器可读来源：单镜头问题填 scope=shot 和一个 shotNo；跨镜头连续性、数量、顺序或整体版式问题填 scope=sequence 和所有涉及的 shotNos。"
        "每项都要填写 observed、required、correction。blockingIssues 只作为给人看的简短摘要，单镜头摘要不要重复成整体问题；warnings 只放非阻断提醒。\n\n"
        "7. typeEffectPreset 非空时，只检查本画格是否有可辨的对应类型氛围，不要求逐字或逐像素复制预设；仅有类型角标、普通照明或一般光晕不算完成预设中的空间、时间等具体效果。明显没有对应效果或把真人画成卡通等改变项目绘制媒介时，属于本镜阻断。"
        "typeEffectPreset 为空的普通画格不应获得相邻类型画格的专属效果；仅凭自然景深、普通照明或画面文字不能臆断串染。看不清时按 inconclusive 处理。\n\n"
        "【分镜脚本】\n"
        + json.dumps(review_shots, ensure_ascii=False, indent=2)
        + "\n\n【输出要求】\n按结构化契约返回观察到的画格数量、逐镜头核验、问题范围详情、阻断问题和非阻断警告。"
    )
    model_data, model_meta = _model_json_or_none(
        project_id,
        "agent",
        "model_id",
        prompt,
        system_prompt=(
            "你是分镜图回读审核员。分镜脚本是唯一核验合同；必须先观察实际图片，再逐镜头核验。"
            "不得根据提示词臆测图片中本应出现的内容，不得把不确定或不可见的细节当成失败。"
            "输出必须保守、去重，并只描述可见的合同冲突。"
        ),
        temperature=0.1,
        max_tokens=8192,
        images=[media],
        structured_schema=STORYBOARD_VISUAL_READBACK_SCHEMA,
        model_request_log_stage=STAGE_STORYBOARD_IMAGE_READBACK_PROMPT,
        model_request_log_context={
            "episodeId": episode_id,
            "nodeId": node_id,
            "phase": "storyboard-visual-readback",
            "source": "auto_review_variant_quality",
        },
    )
    if not isinstance(model_data, dict) or not model_data:
        raise RuntimeError(model_meta.get("error") or "分镜图视觉回读失败")
    model_blocking_issues = _string_list(model_data.get("blockingIssues"))
    warnings = _string_list(model_data.get("warnings"))
    observed_panel_count_value = model_data.get("observedPanelCount")
    if type(observed_panel_count_value) not in (int, float) or not math.isfinite(observed_panel_count_value) or not float(observed_panel_count_value).is_integer() or observed_panel_count_value < 0:
        raise RuntimeError("视觉回读返回了无效的画格数量")
    if type(model_data.get("passed")) is not bool:
        raise RuntimeError("视觉回读缺少有效的整体判断")
    observed_panel_count = int(observed_panel_count_value)
    failed_shots: set[int] = set()
    shot_checks = model_data.get("shotChecks") if isinstance(model_data.get("shotChecks"), list) else []
    checks_by_shot_no: dict[int, dict[str, Any]] = {}
    for item in shot_checks:
        if not isinstance(item, dict):
            raise RuntimeError("视觉回读镜头结果格式不完整")
        shot_no_value = item.get("shotNo")
        if type(shot_no_value) not in (int, float) or not math.isfinite(shot_no_value) or not float(shot_no_value).is_integer() or not 1 <= shot_no_value <= expected_panel_count or int(shot_no_value) in checks_by_shot_no:
            raise RuntimeError("视觉回读返回了无效或重复的镜头编号")
        # Old persisted/test payloads predate the tri-state field; only a
        # genuinely absent field gets the legacy confirmed default. An
        # explicit null or empty value is malformed and must not pass.
        review_status = item["reviewStatus"] if "reviewStatus" in item else "confirmed"
        if type(item.get("present")) is not bool or review_status not in {"confirmed", "inconclusive"} or type(item.get("matchesDirectorPlan")) is not bool or not isinstance(item.get("note"), str):
            raise RuntimeError("视觉回读缺少有效的逐镜头判断")
        checks_by_shot_no[int(shot_no_value)] = {**item, "reviewStatus": review_status}
    for shot_no in range(1, expected_panel_count + 1):
        check = checks_by_shot_no.get(shot_no)
        if not check:
            raise RuntimeError(f"视觉回读缺少镜头 {shot_no:02d} 的核验结果")
        if check["present"] is False:
            failed_shots.add(shot_no)
        elif check["reviewStatus"] == "confirmed" and check["matchesDirectorPlan"] is False:
            failed_shots.add(shot_no)
    inconclusive_shots = {
        shot_no
        for shot_no, check in checks_by_shot_no.items()
        if check["present"] is True and check["reviewStatus"] == "inconclusive"
    }
    blocking_issues: list[str] = []
    blocking_issue_details: list[dict[str, Any]] = []
    detail_shot_numbers: set[int] = set()
    if observed_panel_count != expected_panel_count:
        blocking_issues.append(
            f"实际观察到 {observed_panel_count} 个镜头画格，分镜脚本要求 {expected_panel_count} 个"
        )
    raw_issue_details = model_data.get("blockingIssueDetails")
    if isinstance(raw_issue_details, list):
        for detail in raw_issue_details:
            if not isinstance(detail, dict) or detail.get("scope") not in {"shot", "sequence"}:
                raise RuntimeError("视觉回读返回了无效的问题范围")
            shot_numbers = detail.get("shotNos")
            if not isinstance(shot_numbers, list) or not shot_numbers:
                raise RuntimeError("视觉回读问题范围缺少镜头编号")
            normalized_shots: list[int] = []
            for value in shot_numbers:
                if type(value) not in (int, float) or not math.isfinite(value) or not float(value).is_integer() or not 1 <= value <= expected_panel_count:
                    raise RuntimeError("视觉回读问题范围包含无效镜头编号")
                normalized_shots.append(int(value))
            if not isinstance(detail.get("observed"), str) or not isinstance(detail.get("required"), str) or not isinstance(detail.get("correction"), str):
                raise RuntimeError("视觉回读问题范围缺少实际观察、计划要求或修正动作")
            if not all(detail[key].strip() for key in ("observed", "required", "correction")):
                raise RuntimeError("视觉回读问题范围包含空的问题描述")
            normalized_detail = {
                "scope": detail["scope"],
                "shotNos": list(dict.fromkeys(normalized_shots)),
                "observed": detail["observed"].strip(),
                "required": detail["required"].strip(),
                "correction": detail["correction"].strip(),
            }
            blocking_issue_details.append(normalized_detail)
            summary = normalized_detail["correction"] or normalized_detail["observed"] or normalized_detail["required"]
            if normalized_detail["scope"] == "sequence":
                if summary:
                    blocking_issues.append(summary)
            else:
                detail_shot_numbers.update(normalized_detail["shotNos"])
                if summary:
                    for shot_no in normalized_detail["shotNos"]:
                        blocking_issues.append(f"镜头 {shot_no:02d}：{summary}")
    for issue in model_blocking_issues:
        # Per-shot issues are reconstructed from the canonical shotChecks below.
        # Keeping the model's duplicate wording here used to create two correction
        # rows for every failed shot and incorrectly widened the edit to the full plan.
        issue_shot_numbers = _readback_issue_shot_numbers(issue)
        if len(issue_shot_numbers) == 1 and issue_shot_numbers.issubset(failed_shots | detail_shot_numbers | inconclusive_shots):
            continue
        blocking_issues.append(issue)
    for shot_no in sorted(failed_shots):
        check = checks_by_shot_no[shot_no]
        if check["present"] is False:
            blocking_issues.append(f"实际分镜图缺少镜头 {shot_no:02d}")
        elif shot_no in detail_shot_numbers:
            continue
        else:
            note = str(check.get("note") or "镜头内容与分镜脚本不一致").strip()
            blocking_issues.append(f"镜头 {shot_no:02d}：{note}")
    for shot_no in sorted(inconclusive_shots):
        warnings.append(f"镜头 {shot_no:02d} 的关键区域无法确认，已标记为待复核。")
    inconclusive = bool(inconclusive_shots)
    if model_data["passed"] is False and not blocking_issues and not inconclusive:
        raise RuntimeError("视觉回读整体判断与逐镜头结果矛盾，且未返回具体不一致原因")
    blocking_issues = list(dict.fromkeys(item for item in blocking_issues if item))
    passed = model_data["passed"] and not blocking_issues and not inconclusive
    return {
        "performed": True,
        "passed": passed,
        "expectedPanelCount": expected_panel_count,
        "observedPanelCount": observed_panel_count,
        "shotChecks": [copy.deepcopy(checks_by_shot_no[shot_no]) for shot_no in sorted(checks_by_shot_no)],
        "inconclusive": inconclusive,
        "inconclusiveShots": sorted(inconclusive_shots),
        "blockingIssueDetails": blocking_issue_details,
        "blockingIssues": blocking_issues,
        "warnings": warnings,
        "modelMeta": copy.deepcopy(model_meta),
    }
