# -*- coding: utf-8 -*-
"""Read one director board and atomically commit its verified shots and allocation."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from decimal import Decimal
from typing import Any

from .canvas_store_queries import (
    read_canvas_card_record_v4, read_workflow_card_neighborhood_v4,
    read_previous_director_plan_boundary_v4, read_work_chain_shootable_context_v4,
)
from .director_plan_contract import (
    _director_plan_bound_asset_catalog,
    _director_plan_bound_speaker_asset_ids,
    _director_plan_normalized_content,
    _director_plan_reference_duration_sum,
    director_plan_source_voice_lines,
    director_plan_source_voice_matches,
    director_plan_source_voice_mismatch,
    _normalize_multiline_text,
)
from .director_rules import _director_rule_details_text, _normalize_director_rule_id, _selectable_director_rules
from .source_text_store import _read_episode_source_text
from .script_delivery_contract import current_script_delivery_contract
from .store_core import _JSON_WRITE_LOCK
from .planning_contract import _is_user_locked_item
from .storyboard_allocation import (_allocation_groups, _director_branches,
                                    apply_storyboard_allocation, director_shots_hash,
                                    require_direct_continuation_previous_group)
from .storyboard_timing import (voice_delivery_issue, effective_rhythm as resolve_effective_rhythm,
                                project_storyboard_timing, speech_seconds, formal_shot_seconds,
                                validate_shot_timing,
                                SPEECH_ESTIMATE_TOLERANCE_SECONDS)
from .storyboard_frame_readiness import (observed_frame_refusal_risks,
                                        storyboard_frame_readiness_issues, storyboard_frame_review_rules)
from .storyboard_visual_policy import project_visual_layers
from .project_management import get_effective_config
from .model_provider_config import _project_model_config
from .storyboard_prompt_content import _workflow_storyboard_asset_refs_text, _workflow_storyboard_speaker_identity_map
from .work_chain_context import script_source_text, script_narrative_mode, work_chain_stage_node
from .workflow_contract import _workflow_node, _workflow_node_type_value
from .director_plan_source_context import _director_plan_marked_episode_source, _director_plan_rhythm_multiplier
from .workflow_director_rework_records import list_director_rework_records, record_director_rework_record
from .workflow_input_resolution import _resolve_workflow_node_inputs_from_workflow


def _digest(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _failure(path: str, code: str, message: str, repair_action: str) -> dict[str, Any]:
    return {
        "success": False, "status": "validation_failed", "message": message,
        "errors": [{"path": path, "code": code, "message": message, "repairAction": repair_action}],
        "projectChanged": False,
    }


def _split_optional_voice_issue(script: str, shots: list[dict[str, Any]], clip_max_seconds: float,
                                rhythm: float = 1.0) -> str:
    """Do not cut a short thought/narration line merely to fit separate video cards."""
    optional_lines: list[tuple[int, str]] = []
    for line_no, line in enumerate(str(script or "").splitlines(), start=1):
        parenthesized = re.match(r"^\s*[^：:\n（）()]+[（(]([^）)]*)[）)]\s*[：:]\s*(.+)$", line)
        if parenthesized and "内心声" in parenthesized.group(1):
            optional_lines.append((line_no, parenthesized.group(2)))
        elif re.match(r"^\s*旁白\s*[：:]", line):
            optional_lines.append((line_no, re.split(r"[：:]", line, maxsplit=1)[1]))
    if not optional_lines:
        return ""
    shot_ranges: list[tuple[int, int]] = []
    spoken_parts: list[str] = []
    cursor = 0
    for shot in shots:
        spoken = "".join(
            "".join(str(event.get("content") or "").split())
            for event in shot.get("soundEvents") or []
            if isinstance(event, dict) and event.get("kind") == "voice"
        )
        spoken_parts.append(spoken)
        shot_ranges.append((cursor, cursor + len(spoken)))
        cursor += len(spoken)
    all_spoken = "".join(spoken_parts)
    search_from = 0
    for line_no, content in optional_lines:
        normalized = "".join(content.split())
        if not normalized:
            continue
        start = all_spoken.find(normalized, search_from)
        if start < 0:
            continue  # The source-voice validator reports missing or changed words.
        end = start + len(normalized)
        search_from = end
        duration = speech_seconds({"soundEvents": [{"kind": "voice", "content": content}]}, rhythm)
        if duration <= clip_max_seconds + SPEECH_ESTIMATE_TOLERANCE_SECONDS and not any(
            start >= shot_start and end <= shot_end for shot_start, shot_end in shot_ranges
        ):
            return (f"剧本第 {line_no} 行可选内心声／旁白按正常语速约 {duration:g} 秒，"
                    f"可在 {clip_max_seconds:g} 秒单镜中完整说完，却被拆进相邻镜头。"
                    "请将整句与同一人物的有效动作或反应放在一镜；只有两个独立观看任务时，"
                    "先在剧本明确分成两段，再重做分镜。")
    return ""


def _previous_boundary_context(project_id: str, episode_id: str, work_chain_id: str) -> tuple[dict[str, Any], dict[str, str]]:
    if not work_chain_id:
        raise ValueError("当前分镜脚本节点缺少工作链归属，请从当前画布重新发起")
    boundary = read_previous_director_plan_boundary_v4(project_id, episode_id, work_chain_id)
    if boundary.get("status") in {"ambiguous", "unavailable_order"}:
        raise ValueError("无法确定紧邻上一工作链的分镜目标或顺序，请检查当前画布后再生成")
    previous_segment = (
        read_work_chain_shootable_context_v4(project_id, episode_id, str(boundary.get("workChainId") or ""))
        if boundary.get("status") == "missing_plan" else {"kind": "none", "text": ""}
    )
    return boundary, previous_segment


def _context(project_id: str, episode_id: str, node_id: str, user_instruction: str,
             rhythm_multiplier: Any, rework_record_ids: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not str(episode_id or "").strip() or not str(node_id or "").strip():
        raise ValueError("必须明确提供 episodeId 和 nodeId")
    workflow = read_workflow_card_neighborhood_v4(project_id, episode_id, node_id, detail="full")
    director = _workflow_node(workflow, node_id)
    if not director or _workflow_node_type_value(director) != "director.board":
        raise ValueError("目标必须是当前分集中的分镜脚本节点")
    if _is_user_locked_item(director):
        raise ValueError("分镜脚本节点已由用户锁定，本次分镜未保存")
    if any(_is_user_locked_item(node) for branch in _director_branches(workflow, director) for node in branch):
        raise ValueError("分镜后继卡片已由用户锁定，本次分镜及分组未保存")
    data = director.get("data") if isinstance(director.get("data"), dict) else {}
    script = work_chain_stage_node(workflow, director, "prompt.storyboard")
    script_data = script.get("data") if isinstance((script or {}).get("data"), dict) else {}
    narrative_mode = script_narrative_mode(script_data)
    shootable = _normalize_multiline_text(script_source_text(script_data))
    if not shootable:
        raise ValueError("当前工作链尚无已提交的可拍摄剧本")
    configured_rule_id = str(data.get("directorRuleId") or "").strip()
    selection_mode = (
        "auto" if data.get("directorRuleSelectionMode") == "auto" or not configured_rule_id
        else "manual"
    )
    rule_id = (
        _normalize_director_rule_id(configured_rule_id, source_label="当前导演规则", require_non_empty=True)
        if selection_mode == "manual" else ""
    )
    selectable_rules = _selectable_director_rules() if selection_mode == "auto" else []
    rule_catalog = [
        {"id": str(rule["id"]), "title": str(rule["title"]),
         "description": str(rule["description"])}
        for rule in selectable_rules
    ]
    inputs = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, node_id)
    asset_catalog = _director_plan_bound_asset_catalog(project_id, inputs)
    speaker_map = _workflow_storyboard_speaker_identity_map(project_id, inputs)
    if not any(row.get("speakerId") == "project:narrator" for row in speaker_map):
        speaker_map.append({"name": "旁白", "speakerId": "project:narrator"})
    episode_source = next((
        str((node.get("data") or {}).get("sourceText") or "")
        for node in workflow.get("nodes") or []
        if isinstance(node, dict) and node.get("type") == "source.text"
        and isinstance(node.get("data"), dict) and node["data"].get("sourceText")
    ), "") or _read_episode_source_text(project_id, episode_id)
    source_fact = _normalize_multiline_text(script_data.get("sourceFactText"))
    marked_episode_source = _director_plan_marked_episode_source(episode_source, source_fact or shootable)
    effective_rhythm = resolve_effective_rhythm(project_id, data.get("rhythmMultiplier"))
    if rhythm_multiplier not in (None, "") and _director_plan_rhythm_multiplier(rhythm_multiplier) != effective_rhythm:
        raise ValueError("画布上的镜头节奏尚未保存，请先保存设置后再生成分镜脚本")
    if rework_record_ids is None:
        selected_ids: list[str] = []
    elif isinstance(rework_record_ids, list) and all(isinstance(item, str) and item.strip() for item in rework_record_ids):
        selected_ids = [item.strip() for item in rework_record_ids]
        if len(set(selected_ids)) != len(selected_ids):
            raise ValueError("返工记录 ID 重复")
    else:
        raise ValueError("reworkRecordIds 必须是记录 ID 数组")
    available_records = list_director_rework_records(project_id, episode_id, {"nodeId": node_id})["items"] if selected_ids else []
    by_id = {row["id"]: row for row in available_records}
    if any(record_id not in by_id for record_id in selected_ids):
        raise ValueError("所选返工记录已变化，请重新打开后再提交")
    selected_records = [copy.deepcopy(by_id[record_id]) for record_id in selected_ids]
    allocation = data.get("storyboardAllocation") if isinstance(data.get("storyboardAllocation"), dict) else {}
    work_chain_id = str(director.get("workChainId") or data.get("workChainId") or "")
    previous_boundary, previous_segment = _previous_boundary_context(project_id, episode_id, work_chain_id)
    project_config = get_effective_config(project_id)
    image_defaults = _project_model_config(project_id)[2].get("image", {})
    default_image_model_id = str(image_defaults.get("model_id") or "").strip()
    image_model_ids: list[str] = []
    for branch in _director_branches(workflow, director):
        image_node = branch[1]
        card_data = branch[0].get("data") if isinstance(branch[0].get("data"), dict) else {}
        card_config = card_data.get("generationConfig") if isinstance(card_data.get("generationConfig"), dict) else {}
        image_data = image_node.get("data") if isinstance(image_node.get("data"), dict) else {}
        image_config = image_data.get("generationConfig") if isinstance(image_data.get("generationConfig"), dict) else {}
        route = next((item for item in workflow.get("routes") or []
                      if isinstance(item, dict) and item.get("id") == image_node.get("routeId")), {})
        route_config = route.get("generationConfig") if isinstance(route.get("generationConfig"), dict) else {}
        selected = str(card_config.get("modelId") or card_config.get("model_id")
                       or image_config.get("modelId") or image_config.get("model_id")
                       or route_config.get("modelId") or route_config.get("model_id")
                       or default_image_model_id).strip()
        if selected and selected not in image_model_ids:
            image_model_ids.append(selected)
    if not image_model_ids and default_image_model_id:
        image_model_ids.append(default_image_model_id)
    context = {
        "episodeId": episode_id, "nodeId": node_id,
        "workChainId": work_chain_id,
        "nodeTitle": str(director.get("title") or data.get("title") or ""),
        "scriptNodeId": str((script or {}).get("id") or ""),
        "shootableContent": shootable,
        "scriptDeliveryContract": (
            current_script_delivery_contract(script_data)
            if _normalize_multiline_text(script_data.get("cinematicStoryText")) else None
        ),
        "narrativeMode": narrative_mode,
        "shootableSourceKind": "cinematic_script" if _normalize_multiline_text(script_data.get("cinematicStoryText")) else "source_fragment",
        "previousBoundary": previous_boundary,
        "previousSegmentContext": previous_segment,
        "sourceFactText": source_fact,
        "episodeContext": marked_episode_source,
        "directorRuleId": rule_id,
        "directorRuleSelectionMode": selection_mode,
        "directorRuleCatalog": rule_catalog,
        "directorRuleCatalogVersion": _digest([
            {"id": rule["id"], "title": rule["title"],
             "description": rule["description"], "content": rule["content"]}
            for rule in selectable_rules
        ]) if selectable_rules else "",
        "directorRule": _director_rule_details_text([rule_id]) if rule_id else "",
        "rhythmMultiplier": effective_rhythm,
        "cardRhythmMultiplier": data.get("rhythmMultiplier"),
        "projectRhythmMultiplier": project_storyboard_timing(project_id)["rhythmMultiplier"],
        "clipMaxSeconds": project_storyboard_timing(project_id)["clipMaxSeconds"],
        "assetFacts": _workflow_storyboard_asset_refs_text(project_id, inputs),
        "assetCatalog": asset_catalog,
        "excludedAssets": copy.deepcopy(inputs.get("excludedAssets") or []),
        "speakerIdentityMap": speaker_map,
        "currentDirectorPlan": _normalize_multiline_text(data.get("directorPlan")),
        # The allocator compares this value to the stored field exactly: a missing
        # field (None) is distinct from an explicitly saved empty list.
        "currentDirectorPlanShots": copy.deepcopy(data.get("directorPlanShots")),
        "currentSpeakerRoster": copy.deepcopy(data.get("speakerRoster") or []),
        "currentSpeechBudgetNote": str(data.get("speechBudgetNote") or ""),
        "currentAllocation": copy.deepcopy(allocation.get("groups") or []),
        "selectedReworkRecords": selected_records,
        "userInstruction": _normalize_multiline_text(user_instruction),
        "workflowVersion": workflow.get("version"),
        "projectVisualLayers": project_visual_layers(project_config),
        "imageModelId": " ".join(image_model_ids),
    }
    # Bind creative reads to their actual inputs. Progress, layout and derived
    # status also advance the canvas revision, but do not invalidate this bundle.
    # Submission rebuilds this context under the write lock and passes its fresh
    # workflowVersion to the allocator for optimistic concurrency protection.
    context["inputDigest"] = _digest({key: value for key, value in context.items() if key != "workflowVersion"})
    return context, workflow


def _selected_director_context(context: dict[str, Any], selected_rule_id: str) -> dict[str, Any]:
    selected = str(selected_rule_id or "").strip()
    if context["directorRuleSelectionMode"] == "auto":
        rule_id = _normalize_director_rule_id(
            selected, source_label="自动选择的导演规则", require_non_empty=True,
        )
        if rule_id not in {row["id"] for row in context["directorRuleCatalog"]}:
            raise ValueError("所选导演规则已不在当前规则列表中，请重新读取规则列表")
        return {**context, "directorRuleId": rule_id,
                "directorRule": _director_rule_details_text([rule_id])}
    if selected and selected != context["directorRuleId"]:
        raise ValueError("分镜脚本卡已手动指定导演规则，不能改用其他规则")
    return context


def get_director_plan_context(project_id: str, episode_id: str, node_id: str, *,
                              user_instruction: str = "", rhythm_multiplier: Any = None,
                              rework_record_ids: Any = None, part: str = "",
                              input_digest: str = "", selected_director_rule_id: str = "") -> dict[str, Any]:
    parts = {
        "shootable_content", "episode_continuity", "director_rule", "visual_assets",
        "speaker_identities", "planning_state", "planning_bundle", "revision_state", "rule_catalog",
        "project_visuals",
    }
    if part not in parts:
        return _failure("part", "invalid_part", "请选择明确的分镜脚本资料类型", "revise_and_resubmit")
    if part not in {"planning_state", "planning_bundle"} and not str(input_digest or "").strip():
        return _failure("inputDigest", "required", "请先读取 planning_bundle，再用其 inputDigest 补读任务资料", "reread_context")
    try:
        context, _ = _context(project_id, episode_id, node_id, user_instruction,
                              rhythm_multiplier, rework_record_ids)
    except (ValueError, FileNotFoundError, OSError) as exc:
        return _failure("nodeId", "context_unavailable", str(exc), "stop")
    if part not in {"planning_state", "planning_bundle"} and context["inputDigest"] != input_digest:
        return _failure("inputDigest", "stale_context", "分镜脚本任务资料已变化，请重新读取 planning_bundle 和所需资料", "reread_context")
    planning_state = None
    if part in {"planning_state", "planning_bundle"}:
        planning_state = {
            "narrativeMode": context.get("narrativeMode", "drama"),
            "shootableSourceKind": context.get("shootableSourceKind", "source_fragment"),
            "directorRuleId": context["directorRuleId"],
            "directorRuleSelectionMode": context["directorRuleSelectionMode"],
            "previousBoundaryStatus": (context.get("previousBoundary") or {}).get("status", "unavailable_order"),
            "inputDigest": context["inputDigest"],
        }
    if part == "planning_bundle":
        result = {
            "success": True, "inputDigest": context["inputDigest"], "planningState": planning_state,
            "shootableContent": context["shootableContent"],
            "scriptDeliveryContract": context.get("scriptDeliveryContract"),
            "narrativeMode": context.get("narrativeMode", "drama"),
            "shootableSourceKind": context.get("shootableSourceKind", "source_fragment"),
            "previousBoundary": context.get("previousBoundary") or {"status": "unavailable_order"},
            "previousSegmentContext": context.get("previousSegmentContext") or {"kind": "none", "text": ""},
            "assetFacts": context["assetFacts"], "assetCatalog": context["assetCatalog"],
            "excludedAssets": context.get("excludedAssets") or [],
            "speakerIdentityMap": context["speakerIdentityMap"],
            "projectVisualLayers": context.get("projectVisualLayers") or {},
            "frameReviewRules": storyboard_frame_review_rules(),
            "observedFrameRefusalRisks": observed_frame_refusal_risks(context.get("imageModelId") or ""),
        }
        if context["directorRuleSelectionMode"] == "auto":
            result["directorRuleCatalog"] = context["directorRuleCatalog"]
        else:
            result["directorRule"] = context["directorRule"]
        return result
    if part == "shootable_content":
        return {"success": True, "shootableContent": context["shootableContent"],
                "scriptDeliveryContract": context.get("scriptDeliveryContract"),
                "narrativeMode": context.get("narrativeMode", "drama"),
                "shootableSourceKind": context.get("shootableSourceKind", "source_fragment"),
                "previousBoundary": context.get("previousBoundary") or {"status": "unavailable_order"},
                "previousSegmentContext": context.get("previousSegmentContext") or {"kind": "none", "text": ""}}
    if part == "episode_continuity":
        return {"success": True, "episodeContext": context["episodeContext"]}
    if part == "rule_catalog":
        if context["directorRuleSelectionMode"] != "auto":
            return _failure("part", "manual_rule_selected", "分镜卡已指定导演规则，无需自动选择", "stop")
        return {"success": True, "directorRuleCatalog": context["directorRuleCatalog"]}
    if part == "director_rule":
        try:
            selected = _selected_director_context(context, selected_director_rule_id)
        except ValueError as exc:
            return _failure("selectedDirectorRuleId", "invalid_rule", str(exc), "revise_and_resubmit")
        return {"success": True, "directorRuleId": selected["directorRuleId"],
                "directorRule": selected["directorRule"]}
    if part == "visual_assets":
        return {"success": True, "assetFacts": context["assetFacts"], "assetCatalog": context["assetCatalog"],
                "excludedAssets": context.get("excludedAssets") or []}
    if part == "project_visuals":
        return {"success": True, "projectVisualLayers": context.get("projectVisualLayers") or {}}
    if part == "speaker_identities":
        return {"success": True, "speakerIdentityMap": context["speakerIdentityMap"]}
    if part == "revision_state":
        current_shots = context["currentDirectorPlanShots"]
        draft_shots = copy.deepcopy(current_shots) if isinstance(current_shots, list) else None
        if draft_shots is not None:
            for shot in draft_shots:
                if not isinstance(shot, dict):
                    draft_shots = None
                    break
                try:
                    formal_duration = float(shot["durationSec"])
                except (TypeError, ValueError, KeyError):
                    draft_shots = None
                    break
                if not math.isfinite(formal_duration) or formal_duration <= 0:
                    draft_shots = None
                    break
                normal_duration = shot.pop("normalDurationSec", None)
                if normal_duration is not None:
                    shot.pop("durationSec")
                    shot["normalDurationSec"] = normal_duration
        revision_state = {
            key: context[key] for key in (
                "currentDirectorPlanShots", "currentSpeakerRoster", "currentSpeechBudgetNote", "selectedReworkRecords",
            )
        }
        revision_state["currentDirectorPlanDraftShots"] = draft_shots
        revision_state["currentAllocation"] = copy.deepcopy(context.get("currentAllocation") or [])
        return {"success": True, "revisionState": revision_state}
    return {"success": True, "planningState": planning_state}


def director_plan_output_digest(shots: Any, speaker_roster: Any, speech_budget_note: Any,
                                director_rule_id: Any, rhythm_multiplier: Any) -> str:
    return _digest({
        "shots": shots, "speakerRoster": speaker_roster,
        "speechBudgetNote": _normalize_multiline_text(speech_budget_note),
        "directorRuleId": director_rule_id, "rhythmMultiplier": rhythm_multiplier,
    })


def director_plan_submission_digest(shots: Any, speaker_roster: Any, speech_budget_note: Any,
                                    groups: Any = None, selected_director_rule_id: str = "") -> str:
    return _digest({"shots": shots, "speakerRoster": speaker_roster,
                    "speechBudgetNote": _normalize_multiline_text(speech_budget_note), "groups": groups,
                    "selectedDirectorRuleId": str(selected_director_rule_id or "").strip()})


def _director_plan_candidate_input_failure(shots: Any, speaker_roster: Any,
                                           speech_budget_note: Any, groups: Any) -> dict[str, Any] | None:
    if not isinstance(shots, list) or not shots:
        return _failure("shots", "invalid_shots", "镜头列表必须是非空数组", "revise_and_resubmit")
    if not isinstance(speaker_roster, list):
        return _failure("speakerRoster", "invalid_roster", "临时说话者名单必须是数组", "revise_and_resubmit")
    if groups is not None and (not isinstance(groups, list) or not groups):
        return _failure("groups", "invalid_groups", "镜头分组若提供，必须是非空数组", "revise_and_resubmit")
    required = ("visualPurpose", "storyboardFrame",
                "videoExecution", "endState", "assets", "visibleAssets", "screenTextEvents", "soundEvents")
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            return _failure(f"shots[{index - 1}]", "invalid_shot", "每个镜头必须是结构化对象", "revise_and_resubmit")
        missing = [field for field in required if field not in shot]
        if missing:
            return _failure(f"shots[{index - 1}].{missing[0]}", "required",
                            f"镜头 {index} 缺少 {missing[0]}", "revise_and_resubmit")
        duration_fields = [field for field in ("normalDurationSec", "durationSec") if field in shot]
        if len(duration_fields) != 1 or "durationRangeSec" in shot:
            return _failure(f"shots[{index - 1}].normalDurationSec", "required",
                            f"镜头 {index} 只能提交 normalDurationSec 或 durationSec 其中一种时长", "revise_and_resubmit")
        if shot.get("editorialTextEvents") or shot.get("publicAssetLabels"):
            return _failure(f"shots[{index - 1}]", "editorial_text_not_supported",
                            "默认分镜不生成编辑层字卡或资产介绍卡；请仅保留真实场景载体文字", "revise_and_resubmit")
    if len(_normalize_multiline_text(speech_budget_note)) > 300:
        return _failure("speechBudgetNote", "too_long", "声音时长说明最多 300 字", "revise_and_resubmit")
    return None


def _unverified_screen_text(shots: list[dict[str, Any]], source: str) -> tuple[int, int, str] | None:
    """A legible on-screen inscription must come from the current script."""
    evidence = re.sub(r"\s+", "", source or "")
    if not evidence:
        return None
    for shot_index, shot in enumerate(shots):
        for event_index, event in enumerate(shot.get("screenTextEvents") or []):
            content = re.sub(r"\s+", "", str(event.get("content") or ""))
            if content and content not in evidence:
                return shot_index, event_index, str(event.get("content") or "")
    return None


def _timing_budget_review(shots: list[dict[str, Any]], rhythm: float) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Budget spoken lines and actions that cannot share their screen time."""
    timing: list[dict[str, Any]] = []
    issues: list[str] = []
    speech_deficits = False
    for index, shot in enumerate(shots, start=1):
        spoken = speech_seconds(shot, rhythm)
        non_overlap_exact = sum(
            (Decimal(str(beat["durationSec"])) for beat in shot.get("nonOverlappingBeats") or []),
            Decimal(0),
        )
        non_overlap = float(non_overlap_exact)
        expected = spoken + non_overlap
        actual = float(shot["durationSec"])
        timing.append({"shotNo": index, "speechSeconds": spoken,
                       "nonOverlappingSeconds": round(non_overlap, 3),
                       "plannedSeconds": actual, "accountedSeconds": round(expected, 3)})
        available_exact = Decimal(str(actual)) + Decimal(str(SPEECH_ESTIMATE_TOLERANCE_SECONDS))
        if available_exact < Decimal(str(spoken)):
            speech_deficits = True
            issues.append(f"镜头 {index}: 发声至少 {spoken:g} 秒，画面只有 {actual:g} 秒")
        elif available_exact < Decimal(str(spoken)) + non_overlap_exact:
            issues.append(f"镜头 {index}: 目标 {actual:g} 秒，发声与不能同步完成的动作约需 {expected:g} 秒")
    if not issues:
        return timing, None
    message = (
        "以下镜头的时长账不符：" + "；".join(issues)
        + "。请按正常语速重估人声与不能同步完成的动作；"
        "屏幕信息流不计逐字阅读时间，关键讨论应由同镜的人声或行动表达。"
    )
    return timing, {"path": "shots.durationSec",
                    "code": "shot_timing_invalid" if speech_deficits else "timing_budget_mismatch",
                    "message": message, "repairAction": "revise_and_resubmit"}


def _prepare_director_plan_candidate(project_id: str, episode_id: str, node_id: str,
                                     context: dict[str, Any], workflow: dict[str, Any],
                                     shots: list[dict[str, Any]], speaker_roster: list[Any],
                                     groups: list[Any]) -> dict[str, Any]:
    input_failure = _director_plan_candidate_input_failure(shots, speaker_roster, "", groups)
    if input_failure:
        return input_failure
    for shot_index, shot in enumerate(shots):
        for event_index, event in enumerate(shot.get("soundEvents") or []):
            if isinstance(event, dict) and str(event.get("kind") or "").casefold() == "voice" and event.get("durationSec") is not None:
                return _failure(
                    f"shots[{shot_index}].soundEvents[{event_index}].durationSec",
                    "voice_duration_read_only",
                    "人声时长由后端按正常语速估算；确有原文或用户指令要求慢说时，请使用附来源引文的 deliveryOverride",
                    "revise_and_resubmit",
                )
    inputs = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, node_id)
    asset_catalog = context["assetCatalog"]
    candidate_shots = copy.deepcopy(shots)
    normal_estimates: dict[int, float] = {}
    for index, shot in enumerate(candidate_shots):
        if "normalDurationSec" in shot:
            try:
                normal_seconds = float(shot.pop("normalDurationSec"))
            except (TypeError, ValueError) as exc:
                return _failure(f"shots[{index}].normalDurationSec", "invalid_duration",
                                "正常镜长必须是有效秒数", "revise_and_resubmit")
            if not math.isfinite(normal_seconds) or normal_seconds <= 0:
                return _failure(f"shots[{index}].normalDurationSec", "invalid_duration",
                                "正常镜长必须大于零", "revise_and_resubmit")
            shot["durationSec"] = normal_seconds
            normal_estimates[index] = normal_seconds
    normalized = _director_plan_normalized_content(
        candidate_shots, speaker_roster,
        speaker_asset_ids=_director_plan_bound_speaker_asset_ids(project_id, inputs),
        speaker_source_names={
            f"asset:{row['id']}": row['name']
            for kind in ("characters", "creatures") for row in asset_catalog.get(kind, [])
            if row.get("id") and row.get("name")
        },
        allowed_asset_ids={kind: {row["id"] for row in rows} for kind, rows in asset_catalog.items()},
    )
    normalized_shots = normalized["directorPlanShots"]
    if normalized_shots[0].get("entryBoundaryKind") == "direct_continuation":
        try:
            require_direct_continuation_previous_group(
                project_id, episode_id,
                str(context.get("workChainId") or ""),
                context.get("previousBoundary"),
            )
        except ValueError as exc:
            return _failure("shots[0].entryBoundaryKind", "direct_continuation_without_previous",
                            str(exc), "revise_and_resubmit")
    frame_issues = storyboard_frame_readiness_issues(normalized_shots, str(context.get("imageModelId") or ""))
    field_issues = list(frame_issues)
    timing, budget_issue = _timing_budget_review(normalized_shots, 1.0)
    if budget_issue:
        field_issues.append(budget_issue)
    if field_issues:
        return {
            "success": False,
            "status": "frame_review_required" if len(field_issues) == len(frame_issues) else "field_review_required",
            "message": (field_issues[0]["message"] if len(field_issues) == 1 else
                        "请按镜头和字段一次修订以下画面、首登、装饰文字与时长问题，再提交同一完整草稿"),
            "errors": field_issues, "projectChanged": False,
            **({"shotTiming": timing} if budget_issue else {}),
            **({"editableField": "storyboardFrame"} if len(field_issues) == len(frame_issues) else {}),
        }
    unverified_text = _unverified_screen_text(
        normalized_shots,
        "\n".join((str(context.get("shootableContent") or ""), str(context.get("userInstruction") or ""))),
    )
    if unverified_text:
        shot_index, event_index, content = unverified_text
        return _failure(
            f"shots[{shot_index}].screenTextEvents[{event_index}].content",
            "screen_text_not_in_script",
            f"镜头 {shot_index + 1} 的逐字画面文字“{content[:40]}”不在当前可拍摄剧本中。"
            "只将剧本或本轮用户明确要求的逐字可见文字列为画面文字；叙述事实不能自动变成画内字样。",
            "revise_and_resubmit",
        )
    event_label_sources = "\n".join((
        str(context.get("shootableContent") or ""),
        str(context.get("sourceFactText") or ""),
    ))
    for shot_index, shot in enumerate(normalized_shots):
        presentation = shot.get("presentation") if isinstance(shot.get("presentation"), dict) else {}
        event_label = presentation.get("eventLabel")
        if isinstance(event_label, dict) and event_label["sourceQuote"] not in event_label_sources:
            return _failure(
                f"shots[{shot_index}].presentation.eventLabel.sourceQuote",
                "event_label_source_unverified",
                f"镜头 {shot_index + 1} 的事件短标识没有可核对的剧本或原文依据。",
                "revise_and_resubmit",
            )
    source_voice_lines = director_plan_source_voice_lines(context.get("shootableContent") or "")
    if source_voice_lines and not director_plan_source_voice_matches(context["shootableContent"], normalized_shots):
        return _failure(
            "shots.soundEvents", "source_voice_mismatch",
            f"可拍摄内容中明确标注的 {len(source_voice_lines)} 条发声，未按原字、标点和顺序完整分配到镜头人声。"
            f"{director_plan_source_voice_mismatch(context['shootableContent'], normalized_shots)}",
            "revise_and_resubmit",
        )
    source_evidence = "\n".join(str(context.get(key) or "") for key in (
        "shootableContent", "sourceFactText", "episodeContext",
    ))
    for index, shot in enumerate(normalized_shots, start=1):
        for event_index, event in enumerate(shot.get("soundEvents") or []):
            issue = voice_delivery_issue(
                event, 1.0, source_evidence,
                str(context.get("userInstruction") or ""),
            )
            if issue:
                return _failure(
                    f"shots[{index - 1}].soundEvents[{event_index}].deliveryOverride",
                    "speech_override_unverified", f"镜头 {index} 的人声时长例外无效：{issue}",
                    "revise_and_resubmit",
                )
    validate_shot_timing(normalized_shots, 1.0)
    if normal_estimates:
        for index, shot in enumerate(normalized_shots):
            if index not in normal_estimates:
                continue
            formal_seconds = formal_shot_seconds(float(shot["durationSec"]), shot, context["rhythmMultiplier"])
            if formal_seconds <= 0:
                return _failure(f"shots[{index}].normalDurationSec", "invalid_duration",
                                "正常镜长换算后不足 0.1 秒，请重新估算", "revise_and_resubmit")
            shot["durationSec"] = formal_seconds
            shot["normalDurationSec"] = normal_estimates[index]
        validate_shot_timing(normalized_shots, context["rhythmMultiplier"])
    split_optional_issue = _split_optional_voice_issue(
        context.get("shootableContent") or "", normalized_shots, float(context["clipMaxSeconds"]),
        context["rhythmMultiplier"],
    )
    if split_optional_issue:
        return _failure("shots.soundEvents", "optional_voice_split_without_need",
                        split_optional_issue, "revise_and_resubmit")
    duration = _director_plan_reference_duration_sum(normalized_shots)
    if duration is None:
        return _failure("shots.durationSec", "invalid_duration", "镜头缺少有效的参考时长", "revise_and_resubmit")
    for index, shot in enumerate(normalized_shots):
        if float(shot["durationSec"]) > float(context["clipMaxSeconds"]) + 0.005:
            return _failure(
                f"shots[{index}].durationSec", "clip_max_exceeded",
                f"镜头 {index + 1} 的目标时长 {shot['durationSec']:g} 秒超过项目单段上限 "
                f"{context['clipMaxSeconds']:g} 秒；先核对声音与动作真实用时，确实超出时只在有新观看重点处切镜",
                "revise_and_resubmit",
            )
    if groups is None:
        return {
            "success": True, "status": "grouping_required", "normalizedShots": normalized_shots,
            "normalizedRoster": normalized["speakerRoster"], "durationSeconds": duration,
            "shotTiming": timing,
        }
    prepared_groups = [
        {"id": str(group.get("id") or f"group_{index:03d}"), "shotNos": group.get("shotNos"),
         **({"reason": group["reason"].strip()} if isinstance(group.get("reason"), str)
            and group["reason"].strip() else {})}
        if isinstance(group, dict) else group
        for index, group in enumerate(groups, start=1)
    ]
    try:
        checked_groups = _allocation_groups(prepared_groups, normalized_shots)
    except ValueError as exc:
        return _failure("groups", "invalid_groups", str(exc), "revise_and_resubmit")
    director = _workflow_node(workflow, node_id) or {"id": node_id, "data": {}}
    branches = _director_branches(workflow, director)
    if not branches:
        return _failure("groups", "storyboard_branch_missing",
                        "当前工作链缺少可用的分镜图、视频生成或视频片段节点", "stop")
    for index, group in enumerate(checked_groups):
        group_shots = [normalized_shots[number - 1] for number in group["shotNos"]]
        group_seconds = sum(float(shot["durationSec"]) for shot in group_shots)
        if group_seconds > context["clipMaxSeconds"] + 0.005:
            return _failure(f"groups[{index}].shotNos", "clip_max_exceeded",
                            f"镜头组 {index + 1} 预计 {group_seconds:g} 秒，超过项目 {context['clipMaxSeconds']} 秒上限；请拆组",
                            "revise_and_resubmit")
    # Long visual slack can make almost every shot fill its own clip even when
    # the story contains enough adjacent actions to share clips. Return the
    # draft for a timing/cut review instead of accepting a formally valid grid.
    singleton_count = sum(len(group["shotNos"]) == 1 for group in checked_groups)
    required_singletons = sum(
        len(group["shotNos"]) == 1
        and normalized_shots[group["shotNos"][0] - 1].get("entryBoundaryKind") == "direct_continuation"
        for group in checked_groups
    )
    visual_slack = sum(max(0.0, float(shot["durationSec"]) - speech_seconds(shot, 1.0))
                       for shot in normalized_shots)
    if (len(checked_groups) >= 4 and (singleton_count - required_singletons) * 4 >= len(checked_groups) * 3
            and visual_slack > len(normalized_shots) * 3):
        return _failure(
            "groups", "singleton_group_overuse",
            f"本段 {len(normalized_shots)} 镜分为 {len(checked_groups)} 组，其中 {singleton_count} 组只有一镜；"
            f"正式镜长中约 {visual_slack:g} 秒超出正常发声时间。请逐镜核对不可同步的可见动作与反应，"
            "缩短无据停留或在有新观看重点处调整切点，再按连续性和组时长上限分组。",
            "revise_and_resubmit",
        )
    segment_totals: list[float] = []
    segment_seconds = 0.0
    for shot in normalized_shots:
        if shot.get("groupBreakBefore") and segment_seconds:
            segment_totals.append(segment_seconds)
            segment_seconds = 0.0
        segment_seconds += float(shot["durationSec"])
    if segment_seconds:
        segment_totals.append(segment_seconds)
    capacity_floor = sum(math.ceil(seconds / context["clipMaxSeconds"] - 1e-9)
                         for seconds in segment_totals)
    if (len(checked_groups) >= capacity_floor + required_singletons + 3
            and (singleton_count - required_singletons) * 2 > len(checked_groups)):
        return _failure(
            "groups", "group_packing_review_required",
            f"本段 {len(checked_groups)} 组中有 {singleton_count} 个单镜组，按正式总时长和已标记硬边界"
            f"至少需要 {capacity_floor} 组。请复核相邻镜的切点、同步动作与镜长，"
            "让连续内容在组上限内自然衔接；不要为凑组硬并不连续镜头。",
            "revise_and_resubmit",
        )
    for index in range(1, len(checked_groups)):
        previous_nos = checked_groups[index - 1]["shotNos"]
        current_nos = checked_groups[index]["shotNos"]
        current_no = current_nos[0]
        combined = sum(float(normalized_shots[number - 1]["durationSec"])
                       for number in previous_nos + current_nos)
        reason = str(groups[index].get("reason") or "").strip() if isinstance(groups[index], dict) else ""
        direct_singleton_boundary = (
            (len(previous_nos) == 1
             and normalized_shots[previous_nos[0] - 1].get("entryBoundaryKind") == "direct_continuation")
            or (len(current_nos) == 1
                and normalized_shots[current_no - 1].get("entryBoundaryKind") == "direct_continuation")
        )
        if (combined <= context["clipMaxSeconds"] + 0.005
                and not direct_singleton_boundary
                and (not normalized_shots[current_no - 1].get("groupBreakBefore") or not reason)):
            return _failure(
                f"groups[{index}]", "group_boundary_unjustified",
                f"相邻镜头组 {index}、{index + 1} 合计 {combined:g} 秒且未标明必须断开的边界；"
                "请合为一组；确实不能连续执行时，在新组首镜标记 groupBreakBefore=true，"
                "并在新组 reason 说明具体原因。",
                "revise_and_resubmit",
            )
    return {"success": True, "status": "validated", "normalizedShots": normalized_shots,
            "normalizedRoster": normalized["speakerRoster"], "preparedGroups": prepared_groups,
            "durationSeconds": duration, "shotTiming": timing}


def _capacity_director_groups(shots: list[dict[str, Any]], max_seconds: float,
                              break_reasons: dict[int, str] | None = None) -> list[dict[str, Any]]:
    """Pack adjacent shots after formal timing, retaining authored hard breaks."""
    groups: list[dict[str, Any]] = []
    current: list[int] = []
    current_seconds = 0.0
    current_reason = ""
    for shot in shots:
        seconds = float(shot["durationSec"])
        shot_no = int(shot["shotNo"])
        hard_break = bool(shot.get("groupBreakBefore")) and bool(current)
        direct_singleton = bool(current) and (
            shots[current[0] - 1].get("entryBoundaryKind") == "direct_continuation"
        )
        if current and (hard_break or direct_singleton or current_seconds + seconds > max_seconds + 0.005):
            groups.append({"shotNos": current, **({"reason": current_reason} if current_reason else {})})
            current = []
            current_seconds = 0.0
            current_reason = str((break_reasons or {}).get(shot_no) or "") if hard_break else ""
        current.append(shot_no)
        current_seconds += seconds
    if current:
        groups.append({"shotNos": current, **({"reason": current_reason} if current_reason else {})})
    return groups


def validate_director_plan_draft(project_id: str, episode_id: str, node_id: str,
                                 shots: Any, speaker_roster: Any, speech_budget_note: Any,
                                 input_digest: str, *, user_instruction: str,
                                 rhythm_multiplier: Any, groups: Any = None,
                                 rework_record_ids: Any = None,
                                 selected_director_rule_id: str = "") -> dict[str, Any]:
    """Read-only preflight; submit rechecks the same rules under the write lock."""
    if not str(episode_id or "").strip() or not str(node_id or "").strip():
        return _failure("episodeId/nodeId", "required", "缺少明确的分集或分镜脚本节点", "stop")
    if not str(input_digest or "").strip():
        return _failure("inputDigest", "required", "缺少读取上下文返回的 inputDigest", "reread_context")
    invalid = _director_plan_candidate_input_failure(shots, speaker_roster, speech_budget_note, groups)
    if invalid:
        return invalid
    try:
        context, workflow = _context(project_id, episode_id, node_id, user_instruction,
                                     rhythm_multiplier, rework_record_ids)
        if context["inputDigest"] != input_digest:
            return _failure("inputDigest", "stale_context", "当前剧本、规则、资产、分镜画布或上一份分镜已变化，请重新读取后提交", "reread_context")
        context = _selected_director_context(context, selected_director_rule_id)
        prepared = _prepare_director_plan_candidate(project_id, episode_id, node_id, context, workflow,
                                                    shots, speaker_roster, groups)
        generated_groups = None
        hard_breaks = [int(shot["shotNo"]) for shot in prepared.get("normalizedShots", [])[1:]
                       if shot.get("groupBreakBefore")]
        break_reasons = {int(shot.get("shotNo") or 0): str(shot.get("groupBreakReason") or "").strip()
                         for shot in shots if isinstance(shot, dict)}
        if (prepared.get("success") and prepared.get("status") == "grouping_required"
                and all(break_reasons.get(number) for number in hard_breaks)):
            generated_groups = _capacity_director_groups(
                prepared["normalizedShots"], context["clipMaxSeconds"], break_reasons,
            )
            prepared = _prepare_director_plan_candidate(
                project_id, episode_id, node_id, context, workflow, shots, speaker_roster, generated_groups,
            )
    except ValueError as exc:
        return _failure("shots", "candidate_invalid", str(exc), "revise_and_resubmit")
    except (FileNotFoundError, OSError) as exc:
        return _failure("nodeId", "context_unavailable", str(exc), "stop")
    if not prepared["success"]:
        return prepared
    if prepared["status"] == "grouping_required":
        return {
            "success": True, "status": "grouping_required", "projectChanged": False,
            "inputDigest": input_digest,
            "groupMaxSeconds": context["clipMaxSeconds"],
            "durationSeconds": prepared["durationSeconds"],
            "shotTiming": prepared["shotTiming"],
            "shotsForGrouping": [
                {key: copy.deepcopy(shot[key]) for key in (
                    "shotNo", "durationSec", "visualPurpose", "storyboardFrame", "videoExecution", "endState",
                    "presentation", "soundEvents", "groupBreakBefore",
                ) if key in shot}
                for shot in prepared["normalizedShots"]
            ],
        }
    return {"success": True, "status": "validated", "projectChanged": False,
            "inputDigest": input_digest,
            "groupMaxSeconds": context["clipMaxSeconds"],
            "formalShotDurations": [
                {"shotNo": shot["shotNo"], "durationSec": shot["durationSec"]}
                for shot in prepared["normalizedShots"]
            ],
            "submissionDigest": director_plan_submission_digest(
                shots, speaker_roster, speech_budget_note,
                generated_groups if generated_groups is not None else groups, selected_director_rule_id),
            **({"generatedGroups": generated_groups} if generated_groups is not None else {}),
            "directorRuleId": context["directorRuleId"],
            "shotCount": len(prepared["normalizedShots"]), "durationSeconds": prepared["durationSeconds"],
            "groupCount": len(prepared["preparedGroups"]), "shotTiming": prepared["shotTiming"]}


def submit_director_plan_result(
    project_id: str, episode_id: str, node_id: str,
    shots: Any, speaker_roster: Any, speech_budget_note: Any, input_digest: str,
    *, user_instruction: str, rhythm_multiplier: Any,
    groups: Any = None,
    rework_record_ids: Any = None,
    selected_director_rule_id: str = "",
    session_id: str, execution_id: str,
) -> dict[str, Any]:
    if not str(episode_id or "").strip() or not str(node_id or "").strip():
        return _failure("episodeId/nodeId", "required", "缺少明确的分集或分镜脚本节点", "stop")
    if not str(input_digest or "").strip():
        return _failure("inputDigest", "required", "缺少读取上下文返回的 inputDigest", "reread_context")
    if not session_id or not execution_id:
        return _failure("executionId", "execution_unavailable", "当前智能体执行轮次已失效", "stop")
    if groups is None:
        return _failure("groups", "grouping_required", "请先用预检返回的正式镜长按连续性完成镜头分组", "revise_and_resubmit")
    invalid = _director_plan_candidate_input_failure(shots, speaker_roster, speech_budget_note, groups)
    if invalid:
        return invalid
    note = _normalize_multiline_text(speech_budget_note)
    allocation_attempted = False
    normalized_shots: list[dict[str, Any]] | None = None
    context: dict[str, Any] | None = None

    def unverified(message: str, mutation: dict[str, Any] | None = None) -> dict[str, Any]:
        failed = _failure("nodeId", "commit_unverified", message, "stop")
        mutation = mutation or {}
        failed.update({
            "status": "commit_unverified", "projectChanged": True,
            "changedResources": mutation.get("changedResources") or ["canvas_node"],
            "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id},
            **{key: copy.deepcopy(mutation.get(key)) for key in (
                "txId", "seq", "revision", "baseRevision", "opType", "records", "workflowVersion",
            ) if mutation.get(key) is not None},
        })
        return failed

    try:
        with _JSON_WRITE_LOCK:
            context, workflow = _context(project_id, episode_id, node_id, user_instruction,
                                         rhythm_multiplier, rework_record_ids)
            if context["inputDigest"] != input_digest:
                return _failure("inputDigest", "stale_context", "当前剧本、规则、资产、分镜画布或上一份分镜已变化，请重新读取后提交", "reread_context")
            context = _selected_director_context(context, selected_director_rule_id)
            prepared = _prepare_director_plan_candidate(project_id, episode_id, node_id, context, workflow,
                                                        shots, speaker_roster, groups)
            if not prepared["success"]:
                return prepared
            normalized_shots = prepared["normalizedShots"]
            normalized_roster = prepared["normalizedRoster"]
            prepared_groups = prepared["preparedGroups"]
            duration = prepared["durationSeconds"]
            allocation_attempted = True
            result = apply_storyboard_allocation(project_id, episode_id, {
                "directorNodeId": node_id,
                "expectedWorkflowVersion": context["workflowVersion"],
                "expectedShots": context["currentDirectorPlanShots"],
                "expectedSpeakerRoster": context["currentSpeakerRoster"],
                "directorPlanPatch": {
                    "directorPlanShots": normalized_shots,
                    "speakerRoster": normalized_roster,
                    "directorRuleId": context["directorRuleId"],
                    "directorRuleSelectionMode": context["directorRuleSelectionMode"],
                    "rhythmMultiplier": context["cardRhythmMultiplier"],
                    "speechBudgetNote": note,
                },
                "groups": prepared_groups,
                "invalidateGenerated": True,
            }, preserve_generated_normal_estimates=True)
    except Exception as exc:
        if allocation_attempted and context is not None and normalized_shots is not None:
            try:
                stored = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
                stored_data = stored.get("data") if isinstance(stored.get("data"), dict) else {}
                current = read_workflow_card_neighborhood_v4(project_id, episode_id, node_id, detail="full")
                if (stored_data.get("directorPlanShots") == normalized_shots
                        or current.get("version") != context["workflowVersion"]):
                    return unverified(f"分镜脚本可能已写入，但后续步骤失败：{exc}；请检查当前画布，避免重复提交")
            except Exception as read_exc:
                return unverified(f"分镜脚本提交失败且无法回读核验：{exc}；回读错误：{read_exc}")
        if isinstance(exc, ValueError):
            return _failure("shots", "commit_or_validation_failed", str(exc), "reread_context" if allocation_attempted else "revise_and_resubmit")
        if isinstance(exc, (FileNotFoundError, OSError)):
            return _failure("nodeId", "context_unavailable", str(exc), "stop")
        return _failure("nodeId", "program_error", str(exc), "stop")

    try:
        stored = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
        data = stored.get("data") if isinstance(stored.get("data"), dict) else {}
        allocation = data.get("storyboardAllocation") if isinstance(data.get("storyboardAllocation"), dict) else {}
        mismatched = [
            label for label, actual, expected in (
                ("directorPlanShots", data.get("directorPlanShots"), normalized_shots),
                ("speakerRoster", data.get("speakerRoster"), normalized_roster),
                ("directorRuleId", data.get("directorRuleId"), context["directorRuleId"]),
                ("directorRuleSelectionMode", data.get("directorRuleSelectionMode"), context["directorRuleSelectionMode"]),
                # Persistence may normalize 9.0 to 9. The stored allocation
                # hash must bind the stored shots, while the value comparison
                # above checks those shots still match this submission.
                ("directorPlanHash", allocation.get("directorPlanHash"), director_shots_hash(data.get("directorPlanShots") or [])),
                ("groups", allocation.get("groups"), result.get("groups")),
            ) if actual != expected
        ]
        if mismatched:
            raise RuntimeError("分镜脚本或镜头分配写入后回读不一致：" + "、".join(mismatched))
    except Exception as exc:
        return unverified(str(exc), result)

    rework_record_warning = ""
    if context["currentDirectorPlanShots"] and _normalize_multiline_text(user_instruction):
        history_item = result.get("editHistory")
        try:
            if isinstance(history_item, dict) and history_item.get("id"):
                record_director_rework_record(
                    project_id, episode_id, node_id,
                    _normalize_multiline_text(user_instruction), str(history_item["id"]),
                )
            else:
                rework_record_warning = "分镜脚本已提交，但返工版本记录不可用"
        except (ValueError, FileNotFoundError, OSError) as exc:
            rework_record_warning = str(exc)

    output_digest = director_plan_output_digest(normalized_shots, normalized_roster, note,
                                                context["directorRuleId"], context["rhythmMultiplier"])
    submission_digest = director_plan_submission_digest(
        shots, speaker_roster, note, groups, selected_director_rule_id)
    receipt_id = _digest({"executionId": execution_id, "nodeId": node_id,
                          "inputDigest": input_digest, "outputDigest": output_digest})
    changed_resources = result.get("changedResources") or ["canvas_node"]
    receipt = {
        "receiptId": receipt_id, "runId": execution_id,
        "projectId": project_id, "episodeId": episode_id,
        "sessionId": session_id, "executionId": execution_id,
        "taskType": "director_plan_generation", "targetIds": [node_id],
        "inputDigest": input_digest, "outputDigest": output_digest,
        "submissionDigest": submission_digest,
        "shotCount": len(normalized_shots), "durationSeconds": duration,
        "directorRuleId": context["directorRuleId"],
        "allocationGroupCount": len(result.get("groups") or []),
        "productionWarnings": copy.deepcopy(result.get("productionWarnings") or []),
        "speechBudgetNote": note,
        "reworkRecordWarning": rework_record_warning,
        "changedResources": changed_resources,
    }
    return {
        "success": True, "status": "committed",
        "episodeId": episode_id, "nodeId": node_id,
        "shotCount": len(normalized_shots), "durationSeconds": duration,
        "directorRuleId": context["directorRuleId"],
        "allocationGroupCount": len(result.get("groups") or []),
        "productionWarnings": copy.deepcopy(result.get("productionWarnings") or []),
        "receiptId": receipt_id, "commitReceipt": receipt,
        "changedResources": changed_resources, "projectChanged": True,
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id},
        **{key: copy.deepcopy(result.get(key)) for key in (
            "txId", "seq", "revision", "baseRevision", "opType", "records", "workflowVersion",
            "productionStatusRefreshFailed", "productionStatusWarning",
        ) if result.get(key) is not None},
    }
