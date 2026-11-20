# -*- coding: utf-8 -*-
"""Scoped reads and validated, session-owned candidates for asset range planning."""
from __future__ import annotations

import copy
import uuid
from typing import Any

from utils.text_metrics import content_offset_after_units, content_units_between

from .asset_range_planning import (
    _asset_range_existing_phase_visuals_for_prompt, _asset_range_revision_target, _asset_range_owns_visual,
)
from .catalogs import DEFAULT_ASSET_EXTRACTION_TARGET_UNITS
from .project_resource_revisions import _json_hash
from .source_boundary_contract import (
    _asset_range_boundary_text_length_issue,
    _asset_range_commit_payload,
    _asset_range_phase_visual_context_items,
    _match_source_boundary_text_end,
    _range_source_excerpt,
)
from .source_coverage import _blocking_asset_analysis_range, _load_source_coverage
from .source_text_store import _read_source_content, _select_project_sources
from .store_core import _now
from .agent_run_store import stage_asset_range_candidate


ASSET_TYPES = frozenset({"characters", "creatures", "scenes", "props"})


def _error(path: str, code: str, message: str, repair_action: str = "revise_and_resubmit") -> dict[str, str]:
    return {"path": path, "code": code, "message": message, "repairAction": repair_action}


def _failure(*errors: dict[str, str]) -> dict[str, Any]:
    return {"success": False, "status": "rejected", "message": errors[0]["message"],
            "errors": list(errors), "projectChanged": False}


def _asset_range_inputs(project_id: str, source_id: str = "", target_units: int | None = None,
                        *, include_phase_visuals: bool = True, asset_range_id: str = "") -> dict[str, Any]:
    coverage = _load_source_coverage(project_id, source_id or None)
    source_id = str(coverage.get("sourceId") or "")
    source = _select_project_sources(project_id, source_id)[0]
    content = _read_source_content(project_id, source)
    cursor = coverage.get("assetCursor") if isinstance(coverage.get("assetCursor"), dict) else {}
    revision_row = _asset_range_revision_target(coverage, asset_range_id)
    start = int(revision_row["absoluteStart"] if revision_row else cursor.get("nextOffset") or 0)
    if start >= len(content):
        raise ValueError("资产拆分游标已到达源文件末尾")
    configured_target = int(cursor.get("targetUnits") or DEFAULT_ASSET_EXTRACTION_TARGET_UNITS)
    units = int(target_units or (revision_row or {}).get("targetUnits") or configured_target)
    if units < 100 or units > 50000:
        raise ValueError("本次资产范围目标字数需在 100 至 50000 之间")
    tolerance = max(100, min(200, int(units * 0.04)))
    tolerance = max(0, min(units - 1, tolerance))
    planning_end = content_offset_after_units(content, start, units)
    # A small lookahead lets the agent judge whether the preferred end cuts a
    # continuous asset description; the candidate still has a bounded end.
    window_end = min(len(content), content_offset_after_units(content, start, units + tolerance))
    blocked = _blocking_asset_analysis_range(coverage, project_id=project_id, source_id=source_id)
    if blocked and blocked is not revision_row:
        raise ValueError(f"资产范围 {blocked.get('rangeId') or ''} 尚未完成分析，不能规划下一段")
    visuals = _asset_range_existing_phase_visuals_for_prompt(project_id)
    return {
        "coverage": coverage, "sourceId": source_id,
        "content": content, "start": start, "targetUnits": units,
        "configuredTargetUnits": configured_target,
        "boundaryToleranceUnits": tolerance,
        "preferredEnd": planning_end, "windowEnd": window_end,
        "minBoundaryEnd": min(window_end, content_offset_after_units(
            content, start, max(1, units - tolerance))),
        "currentRange": copy.deepcopy(revision_row), "allPhaseVisuals": visuals,
        "existingPhaseVisuals": [item for item in visuals if not asset_range_id
                                 or not _asset_range_owns_visual(asset_range_id, item["id"])],
    }


def asset_range_context_version(data: dict[str, Any]) -> str:
    return _json_hash({"coverage": data["coverage"], "content": data["content"],
                      "visuals": data.get("allPhaseVisuals", data["existingPhaseVisuals"]),
                      "targetUnits": data["targetUnits"], "currentRange": data.get("currentRange")})


def get_asset_range_context(project_id: str, *, source_id: str = "", target_units: int | None = None,
                            part: str, asset_range_id: str = "") -> dict[str, Any]:
    if part not in {"source_text", "planning_state", "phase_visuals"}:
        return _failure(_error("part", "invalid_part", "请选择资产范围正文、规划状态或已有阶段视觉", "stop"))
    try:
        data = _asset_range_inputs(project_id, source_id, target_units,
                                   include_phase_visuals=part == "phase_visuals", asset_range_id=asset_range_id)
    except (ValueError, FileNotFoundError, IndexError) as exc:
        return _failure(_error("sourceId", "source_unavailable", str(exc), "stop"))
    version = asset_range_context_version(data)
    if part == "source_text":
        return {"success": True, "contextVersion": version, "sourceText": data["content"][data["start"]:data["windowEnd"]]}
    if part == "phase_visuals":
        return {"success": True, "contextVersion": version, "existingPhaseVisuals": data["existingPhaseVisuals"]}
    return {"success": True, "contextVersion": version, "planningState": {
        "sourceId": data["sourceId"], "absoluteStart": data["start"],
        "preferredEnd": data["preferredEnd"], "minBoundaryEnd": data["minBoundaryEnd"],
        "planningWindowEnd": data["windowEnd"],
        "coverageHash": _json_hash(data["coverage"]), "targetUnits": data["targetUnits"],
        "boundaryToleranceUnits": data["boundaryToleranceUnits"],
        "currentRange": data.get("currentRange"),
    }}


def submit_asset_range_candidate(
    project_id: str, args: dict[str, Any], *, session_id: str,
    user_instruction: str = "", previous_pending: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not session_id:
        return _failure(_error("sessionId", "missing_session", "资产范围候选必须属于当前项目会话", "stop"))
    previous = previous_pending if isinstance(previous_pending, dict) else {}
    if previous.get("active") and str(previous.get("sessionId") or "") not in {"", session_id}:
        return _failure(_error("sessionId", "candidate_owned_by_other_session", "待确认候选属于其他会话", "stop"))
    if previous.get("active") and str(previous.get("operationType") or "") != "commit_asset_range":
        return _failure(_error("pendingOperation", "pending_operation_exists", "当前会话已有其他待确认任务", "stop"))
    source_id = str(args.get("sourceId") or "").strip()
    try:
        target_units = int(args["targetUnits"]) if args.get("targetUnits") is not None else None
        data = _asset_range_inputs(project_id, source_id, target_units,
                                   asset_range_id=str(args.get("assetRangeId") or ""))
    except (ValueError, TypeError, FileNotFoundError, IndexError) as exc:
        return _failure(_error("sourceId", "source_unavailable", str(exc), "stop"))
    if args.get("coverageHash") != _json_hash(data["coverage"]):
        return _failure(_error("coverageHash", "source_changed", "资产范围游标或项目资料已变化，请重新读取上下文", "reread_context"))
    if args.get("contextVersion") != asset_range_context_version(data):
        return _failure(_error("contextVersion", "source_changed", "原文、规划参数或阶段视觉已变化，请重新读取三项专用资料", "reread_context"))
    start = data["start"]
    if args.get("absoluteStart") != start:
        return _failure(_error("absoluteStart", "cursor_mismatch", f"当前资产游标为 {start}，请重新读取上下文", "reread_context"))
    boundary_text = str(args.get("boundaryEndText") or "").strip()
    match = _match_source_boundary_text_end(
        data["content"], start, data["windowEnd"], boundary_text,
        min_boundary_end=data["minBoundaryEnd"],
    )
    if match.get("status") != "unique":
        outside_match = _match_source_boundary_text_end(
            data["content"], start, len(data["content"]), boundary_text,
        )
        if outside_match.get("status") == "unique":
            actual_end = int(outside_match["endOffset"])
            if actual_end < data["minBoundaryEnd"]:
                return _failure(_error(
                    "boundaryEndText", "boundary_too_early",
                    f"尾句在原文 {actual_end} 处，但允许断点为 {data['minBoundaryEnd']}–{data['windowEnd']}；"
                    "请从已读取的原文窗口选择此区间内的完整落点。",
                ))
            if actual_end > data["windowEnd"]:
                return _failure(_error(
                    "boundaryEndText", "boundary_too_late",
                    f"尾句在原文 {actual_end} 处，已超出允许断点上限 {data['windowEnd']}；"
                    "请从已读取的原文窗口选择此区间内的完整落点。",
                ))
        return _failure(_error("boundaryEndText", "boundary_not_unique", str(match.get("reason") or "断点尾句未唯一匹配原文")))
    end = int(match["endOffset"])
    length_issue = _asset_range_boundary_text_length_issue(boundary_text, available_text=data["content"][start:end])
    if length_issue:
        return _failure(_error("boundaryEndText", "invalid_boundary_length", length_issue))
    if end <= start or end > data["windowEnd"]:
        return _failure(_error("boundaryEndText", "boundary_out_of_range", "断点必须在当前来源窗口中"))
    if not isinstance(args.get("phaseVisualContexts"), list):
        return _failure(_error("phaseVisualContexts", "invalid_type", "阶段视觉候选必须是数组，可为空数组"))
    if len(args["phaseVisualContexts"]) > 4 or any(
        not isinstance(item, dict) or not all(str(item.get(key) or "").strip()
                                              for key in ("name", "visualPrompt", "sourceSpan", "visualChangeReason", "transitionType"))
        for item in args["phaseVisualContexts"]
    ):
        return _failure(_error("phaseVisualContexts", "invalid_items", "阶段视觉最多四项，每项须有名称、整体视觉、来源区间、变化依据和变化类型"))
    phase_visuals = _asset_range_phase_visual_context_items(args)
    for index, item in enumerate(phase_visuals):
        if not 6 <= len(item["name"]) <= 16:
            return _failure(_error(f"phaseVisualContexts[{index}].name", "invalid_visual_name",
                                   "阶段视觉名称须用 6–16 字概括整体视觉状态"))
        if not 12 <= len(item["visualPrompt"]) <= 40:
            return _failure(_error(f"phaseVisualContexts[{index}].visualPrompt", "invalid_visual_length",
                                   "阶段视觉描述须为 12–40 字的整体视觉约束"))
        if not 20 <= len(item["visualChangeReason"]) <= 80:
            return _failure(_error(f"phaseVisualContexts[{index}].visualChangeReason", "invalid_visual_reason",
                                   "请用 20–80 字说明跨场景持续的视觉状态变化"))
        expected_initial = not data["existingPhaseVisuals"] and index == 0
        valid_transitions = {"world_state_shift", "resource_class_shift",
                             "power_system_shift", "combat_or_training_shift"}
        invalid_transition = (
            item["transitionType"] != "initial_or_single_stage" if expected_initial
            else item["transitionType"] not in valid_transitions
        )
        if invalid_transition:
            return _failure(_error(f"phaseVisualContexts[{index}].transitionType", "invalid_transition_type",
                                   "首个阶段使用 initial_or_single_stage；已有阶段后的新增视觉须说明实际变化类型"))
    if any(not item["visualPrompt"].startswith("整体视觉以")
           or not item["visualPrompt"].endswith("为主") for item in phase_visuals):
        return _failure(_error("phaseVisualContexts.visualPrompt", "invalid_visual_form",
                               "阶段视觉需用“整体视觉以……为主。”描述主导画面环境"))
    if bool(args.get("stageVisualChanged")) != bool(phase_visuals):
        return _failure(_error("stageVisualChanged", "phase_visual_mismatch", "阶段视觉变化标记与新增阶段视觉列表不一致"))
    if not data["existingPhaseVisuals"] and not phase_visuals:
        return _failure(_error("phaseVisualContexts", "initial_phase_required", "项目尚无阶段视觉，当前范围须提交起始阶段视觉"))
    supplied_types = args.get("assetTypes")
    asset_types = supplied_types if isinstance(supplied_types, list) else sorted(ASSET_TYPES)
    if (not asset_types or any(not isinstance(t, str) or t not in ASSET_TYPES for t in asset_types)
            or len(asset_types) != len(set(asset_types))):
        return _failure(_error("assetTypes", "invalid_asset_types", "资产类型仅允许角色、生物、场景、道具对应的四类枚举"))
    reason = str(args.get("reason") or "").strip()
    if not reason:
        return _failure(_error("reason", "required", "请说明资产上下文断点的依据"))
    if args.get("riskNotes") is not None and not isinstance(args.get("riskNotes"), list):
        return _failure(_error("riskNotes", "invalid_type", "风险说明必须是数组"))
    risk_notes = [str(x).strip()[:160] for x in (args.get("riskNotes") or []) if str(x).strip()][:8]
    coverage = data["coverage"]
    range_id = str(args.get("assetRangeId") or f"asset-range-{len(coverage.get('assetRanges') or []) + 1:03d}")
    actual_units = content_units_between(data["content"], start, end)
    proposal = {
        "rangeId": range_id, "sourceId": data["sourceId"],
        "absoluteStart": start, "absoluteEnd": end,
        "targetUnits": data["targetUnits"], "actualUnits": actual_units,
        "boundaryToleranceUnits": data["boundaryToleranceUnits"],
        "planningLookaheadUnits": content_units_between(data["content"], data["preferredEnd"], data["windowEnd"]),
        "planningWindowEnd": data["windowEnd"], "planningMethod": "agent_asset_boundary",
        "boundaryEndText": boundary_text, "boundaryReason": reason,
        "phaseVisualContext": phase_visuals[0]["visualPrompt"] if phase_visuals else "",
        "stageVisualChanged": bool(phase_visuals), "phaseVisualContexts": phase_visuals,
        "assetTypes": asset_types, "summary": str(args.get("summary") or f"覆盖原文 {start}-{end}，用于资产提取。")[:500],
        "reason": reason[:1200], "riskNotes": risk_notes,
        "excerpt": _range_source_excerpt(data["content"], start, end), "createdAt": _now(),
    }
    commit_payload = _asset_range_commit_payload(proposal, coverage)
    commit_payload["assetRangeId"] = str(args.get("assetRangeId") or "")
    commit_payload["contextVersion"] = args["contextVersion"]
    commit_payload["userInstruction"] = user_instruction
    try:
        staged = stage_asset_range_candidate(
            project_id, session_id, proposal, commit_payload,
            requirement_text=user_instruction,
        )
    except ValueError as exc:
        return _failure(_error("sessionId", "candidate_not_saved", str(exc), "stop"))
    pending = {
        "type": "commit_asset_range", "operationType": "commit_asset_range",
        "source": "agent_run.candidate", "sessionId": session_id,
        "runId": staged["runId"], "candidateId": staged["candidateId"],
        "candidateDigest": staged["candidateDigest"], "candidateVersion": staged["candidateVersion"],
        "status": "awaiting_confirmation", "createdAt": proposal["createdAt"],
        "requiresUserConfirmation": True, "expectedNextTool": "commit_asset_range",
        "nextAllowedTools": ["commit_asset_range"],
        "proposal": proposal, "commitPayload": commit_payload,
        "originalUserMessage": str(previous.get("originalUserMessage") or user_instruction),
        "revisionFeedback": [*previous.get("revisionFeedback", []), user_instruction][-12:]
        if previous.get("active") and user_instruction else previous.get("revisionFeedback", []),
        "message": "资产范围候选已暂存，等待当前会话确认。",
    }
    visual_preview = (
        "\n".join(f"- {item['name']}：{item['visualPrompt']}。" for item in phase_visuals)
        if phase_visuals else "无"
    )
    preview = (
        f"{range_id}：原文 {start}–{end}，约 {actual_units} 字。\n"
        f"断点依据：{reason[:300]}\n"
        f"新增阶段视觉：\n{visual_preview}"
    )
    card = {
        "type": "asset_range_candidate", "status": "pending_confirmation",
        "runId": staged["runId"], "candidateId": staged["candidateId"],
        "candidateDigest": staged["candidateDigest"], "candidateVersion": staged["candidateVersion"],
        **copy.deepcopy(proposal),
    }
    return {
        "success": True, "status": "pending_confirmation", "requiresUserConfirmation": True,
        "candidateId": staged["candidateId"], "runId": staged["runId"],
        "candidateDigest": staged["candidateDigest"], "candidateVersion": staged["candidateVersion"],
        "proposal": proposal, "pendingOperation": pending, "previewText": preview,
        "contentBlocks": [card], "message": preview, "projectChanged": False,
    }
