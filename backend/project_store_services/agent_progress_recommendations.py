# -*- coding: utf-8 -*-
"""智能体进度状态与阶段推荐领域。

这里承载阶段进度、推荐动作和用户可见解释。
"""

from __future__ import annotations

from .agent_production_scope import (
    _agent_current_route_completed_states,
    _agent_current_route_state,
)

from .agent_action_contract import (
    _agent_action_label,
    _agent_action_order,
    _agent_allowed_actions,
    _agent_program_direct_actions,
    _agent_validate_task_type,
)
from .agent_asset_range_state import (
    _agent_asset_range_analysis_completed,
    _agent_asset_range_user_label,
    _agent_blocking_asset_analysis_ranges,
)
from .agent_contracts import (
    _AGENT_PRODUCTION_STEP_STATES,
    is_work_chain_recommendation_target,
)
from .agent_pending_operations import (
    _agent_message_continues_flow,
)

from .agent_sessions import (
    _agent_attach_action_footer_to_content_blocks,
    _agent_blocks_from_attachment_fields,
    _agent_blocks_have_body_text,
    _normalize_agent_content_blocks,
    _normalize_agent_session_step_rows,
    _project_meta_path,
)
from .catalogs import (
    DEFAULT_ASSET_EXTRACTION_TARGET_UNITS,
    DEFAULT_EPISODE_TARGET_UNITS,
)
from .production_status import (
    _workflow_has_generated_work_chain,
    get_episode_production_status,
    update_episode_production_status,
)
from .projects import (
    _first_text,
    _project_row,
)
from .source_coverage import _load_source_coverage, _source_ref_bounds
from .source_text_store import _compact_text, _episode_source_ref_path, _episode_source_text_path, get_source_text
from .store_core import (
    _read_json,
)
from .work_chain_actions import (
    WORK_CHAIN_ACTIONS,
)
from .workflow_input_resolution import (
    resolve_generation_task_node_id,
)
from .workflow_projection import (
    get_canvas_workflow_projection,
)
from .workflow_generation_context import find_workflow_nodes
from utils.text_metrics import (
    content_char_count,
)

from .agent_contracts import (
    _agent_steps_from_state,
)

import copy
import traceback
import uuid
from pathlib import Path
from typing import Any


def _agent_progress_state(
    project_id: str,
    episode_id: str | None,
    *,
    detail_mode: bool = False,
) -> dict[str, Any]:
    meta = _read_json(_project_meta_path(project_id), {})
    project = _project_row(project_id, meta)
    episodes = project.get("episodes") if isinstance(project.get("episodes"), list) else []
    requested_episode_id = str(episode_id or "").strip()
    project_scope = requested_episode_id in {"", "__project__", "project"}

    def episode_main_flow_complete(item: dict[str, Any]) -> bool:
        item_episode_id = str(item.get("id") or "").strip()
        if not item_episode_id:
            return False
        return _agent_episode_boundary_ready(project_id, item_episode_id)

    if project_scope:
        selected_episode = next(
            (
                item
                for item in episodes
                if isinstance(item, dict) and not episode_main_flow_complete(item)
            ),
            episodes[-1] if episodes else {"id": "E01", "title": "第一集", "status": "草稿"},
        )
    else:
        selected_episode = next(
            (
                item
                for item in episodes
                if isinstance(item, dict)
                and str(item.get("id") or "") == requested_episode_id
            ),
            episodes[0] if episodes else {"id": "E01", "title": "第一集", "status": "草稿"},
        )
    selected_episode_id = str(selected_episode.get("id") or "E01")
    selected_episode_index = next(
        (
            index
            for index, item in enumerate(episodes)
            if isinstance(item, dict) and str(item.get("id") or "") == selected_episode_id
        ),
        0,
    )
    next_episode = (
        episodes[selected_episode_index + 1]
        if selected_episode_index + 1 < len(episodes)
        and isinstance(episodes[selected_episode_index + 1], dict)
        else {}
    )
    workflow = get_canvas_workflow_projection(project_id, selected_episode_id)
    try:
        production_status_result = get_episode_production_status(project_id, selected_episode_id)
        if production_status_result.get("productionStatusNeedsRefresh"):
            production_status_result = update_episode_production_status(project_id, selected_episode_id)
            workflow = get_canvas_workflow_projection(project_id, selected_episode_id)
        production_status = (
            production_status_result.get("status")
            if isinstance(production_status_result, dict)
            else {}
        )
    except Exception as exc:
        print(traceback.format_exc(), flush=True)
        raise RuntimeError("生产状态刷新失败，无法判断当前集下一步。") from exc
    if not isinstance(production_status, dict):
        raise RuntimeError("生产状态刷新失败，无法判断当前集下一步。")
    production_completed_preconditions = {
        str(state_id or "").strip()
        for state_id in production_status.get("completedPreconditions") or []
        if str(state_id or "").strip()
    }
    production_progress = _agent_episode_production_progress(production_status)
    workflow_nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    workflow_ready = (
        bool(production_status.get("workflowReady"))
        or "workflow.ready" in production_completed_preconditions
        or bool(production_progress.get("episodeComplete"))
        or _workflow_has_generated_work_chain(
            workflow,
            workflow_nodes,
        )
    )
    source_has_remaining: bool | None = None
    try:
        coverage = _load_source_coverage(project_id)
    except Exception:
        coverage = {}
    if not next_episode:
        try:
            cursor = coverage.get("episodeCursor") if isinstance(coverage.get("episodeCursor"), dict) else {}
            source_has_remaining = int(cursor.get("nextOffset") or 0) < _agent_source_total_chars(project_id, coverage)
        except Exception:
            source_has_remaining = None
    node_map = {
        str(node.get("id") or ""): node
        for node in workflow.get("nodes", [])
        if isinstance(node, dict)
    }
    source_node = node_map.get("source_text_1") or next(
        (item for item in find_workflow_nodes(workflow, type="source.text") if isinstance(item, dict)),
        {},
    )
    prompt_node_id = resolve_generation_task_node_id(workflow, "storyboard_plan")
    prompt_node = node_map.get(prompt_node_id) or {}
    source_ready = (
        str((source_node.get("data") or {}).get("status") or "").strip().lower()
        == "ready"
    )
    source_ready = source_ready or "episode.source_ready" in production_completed_preconditions
    prompt_panels = (prompt_node.get("data") or {}).get("panels")
    prompt_ready = bool(prompt_panels) or (
        str((prompt_node.get("data") or {}).get("status") or "").strip().lower()
        == "ready"
    )
    prompt_ready = prompt_ready or workflow_ready
    episode_boundary_ready = _agent_episode_boundary_ready(project_id, selected_episode_id)
    source_count = int(project.get("sourceCount") or 0)
    character_count = int(project.get("characterCount") or 0)
    creature_count = int(project.get("creatureCount") or 0)
    scene_count = int(project.get("sceneCount") or 0)
    prop_count = int(project.get("propCount") or 0)
    asset_ranges = [
        item
        for item in coverage.get("assetRanges") or []
        if isinstance(item, dict)
    ]
    asset_cursor = coverage.get("assetCursor") if isinstance(coverage.get("assetCursor"), dict) else {}
    try:
        asset_extraction_target_units = int(
            asset_cursor.get("targetUnits") or DEFAULT_ASSET_EXTRACTION_TARGET_UNITS
        )
    except (TypeError, ValueError):
        asset_extraction_target_units = DEFAULT_ASSET_EXTRACTION_TARGET_UNITS
    asset_extraction_target_units = max(1, asset_extraction_target_units)
    coverage_source_id = str(coverage.get("sourceId") or "").strip()
    blocking_asset_ranges = _agent_blocking_asset_analysis_ranges(
        coverage,
        project_id=project_id,
        source_id=coverage_source_id,
    )
    has_completed_asset_range = any(
        _agent_asset_range_analysis_completed(item)
        for item in asset_ranges
    )
    asset_counts_ready = min(character_count, scene_count, prop_count) > 0
    asset_coverage_required_end = 0
    asset_coverage_cursor_offset = 0
    asset_coverage_gap_units = 0
    next_episode_asset_coverage_required_end = 0
    next_episode_asset_coverage_cursor_offset = 0
    next_episode_asset_coverage_gap_units = 0
    next_episode_asset_coverage_ready = True
    if not episode_boundary_ready:
        try:
            episode_cursor = coverage.get("episodeCursor") if isinstance(coverage.get("episodeCursor"), dict) else {}
            asset_cursor = coverage.get("assetCursor") if isinstance(coverage.get("assetCursor"), dict) else {}
            episode_start = int(episode_cursor.get("nextOffset") or 0)
            episode_target_units = int(episode_cursor.get("targetUnits") or DEFAULT_EPISODE_TARGET_UNITS)
            asset_coverage_cursor_offset = int(asset_cursor.get("nextOffset") or 0)
            total_chars = _agent_source_total_chars(project_id, coverage)
            asset_coverage_required_end = min(total_chars, episode_start + max(1, episode_target_units))
            asset_coverage_gap_units = max(0, asset_coverage_required_end - asset_coverage_cursor_offset)
        except Exception:
            asset_coverage_required_end = 0
            asset_coverage_cursor_offset = 0
            asset_coverage_gap_units = 0
    asset_coverage_ready_for_boundary = episode_boundary_ready or asset_coverage_required_end <= 0 or asset_coverage_gap_units <= 0
    episode_main_flow_complete = bool(episode_boundary_ready)
    if project_scope and episode_main_flow_complete and not next_episode:
        try:
            episode_cursor = coverage.get("episodeCursor") if isinstance(coverage.get("episodeCursor"), dict) else {}
            asset_cursor = coverage.get("assetCursor") if isinstance(coverage.get("assetCursor"), dict) else {}
            episode_start = int(episode_cursor.get("nextOffset") or 0)
            episode_target_units = int(episode_cursor.get("targetUnits") or DEFAULT_EPISODE_TARGET_UNITS)
            next_episode_asset_coverage_cursor_offset = int(asset_cursor.get("nextOffset") or 0)
            total_chars = _agent_source_total_chars(project_id, coverage)
            if episode_start < total_chars:
                next_episode_asset_coverage_required_end = min(total_chars, episode_start + max(1, episode_target_units))
                next_episode_asset_coverage_gap_units = max(
                    0,
                    next_episode_asset_coverage_required_end - next_episode_asset_coverage_cursor_offset,
                )
                next_episode_asset_coverage_ready = next_episode_asset_coverage_gap_units <= 0
        except Exception:
            next_episode_asset_coverage_ready = True
    asset_extraction_ready = (
        not blocking_asset_ranges
        and asset_coverage_ready_for_boundary
        # A completed asset slice can legitimately produce zero reusable assets.
        and (asset_counts_ready or has_completed_asset_range or bool(asset_ranges))
    )
    overview_ready = _agent_overview_ready(meta)
    episode_workflow_ready = episode_boundary_ready and source_ready and workflow_ready
    if source_count <= 0:
        stage = "missing_source"
    elif not overview_ready:
        stage = "overview"
    elif not asset_extraction_ready:
        stage = "assets"
    elif not episode_boundary_ready:
        stage = "episode_boundary"
    elif project_scope and episode_main_flow_complete and next_episode:
        stage = "episode_complete"
    elif project_scope and episode_main_flow_complete and source_has_remaining is False:
        stage = "project_complete"
    elif project_scope and episode_main_flow_complete:
        stage = "episode_complete"
    elif not episode_workflow_ready:
        stage = "episode_workflow"
    elif (
        detail_mode
        and production_progress["episodeComplete"]
        and not project_scope
        and not production_progress.get("episodeMediaComplete")
    ):
        stage = "production"
    elif production_progress["episodeComplete"] and next_episode:
        stage = "episode_complete"
    elif production_progress["episodeComplete"] and source_has_remaining is False:
        stage = "project_complete"
    elif production_progress["episodeComplete"]:
        stage = "episode_complete"
    else:
        stage = "production"
    return {
        "meta": meta,
        "project": project,
        "projectId": project_id,
        "projectName": str(project.get("name") or meta.get("title") or project_id),
        "projectScope": project_scope,
        "episodeDetailMode": bool(detail_mode),
        "sourceReady": source_count > 0,
        "overviewReady": overview_ready,
        "characterReady": character_count > 0,
        "sceneReady": scene_count > 0,
        "propReady": prop_count > 0,
        "assetExtractionReady": asset_extraction_ready,
        "assetRangeAnalysisReady": not blocking_asset_ranges,
        "assetCoverageReadyForBoundary": asset_coverage_ready_for_boundary,
        "assetCoverageCursorOffset": asset_coverage_cursor_offset,
        "assetCoverageRequiredEnd": asset_coverage_required_end,
        "assetCoverageGapUnits": asset_coverage_gap_units,
        "assetExtractionTargetUnits": asset_extraction_target_units,
        "nextEpisodeAssetCoverageReady": next_episode_asset_coverage_ready,
        "nextEpisodeAssetCoverageCursorOffset": next_episode_asset_coverage_cursor_offset,
        "nextEpisodeAssetCoverageRequiredEnd": next_episode_asset_coverage_required_end,
        "nextEpisodeAssetCoverageGapUnits": next_episode_asset_coverage_gap_units,
        "blockingAssetRangeCount": len(blocking_asset_ranges),
        "blockingAssetRange": copy.deepcopy(blocking_asset_ranges[0]) if blocking_asset_ranges else {},
        "blockingAssetRangeLabel": _agent_asset_range_user_label(blocking_asset_ranges[0]) if blocking_asset_ranges else "",
        "episodeBoundaryReady": episode_boundary_ready,
        "episodeMainFlowComplete": episode_main_flow_complete,
        "episodeWorkflowReady": episode_workflow_ready,
        "episodeSourceSplitReady": episode_boundary_ready and workflow_ready,
        "episodeScriptReady": episode_boundary_ready and workflow_ready,
        "selectedEpisodeId": selected_episode_id,
        "selectedEpisodeTitle": str(selected_episode.get("title") or selected_episode_id),
        "selectedEpisodeStatus": str(selected_episode.get("status") or "草稿"),
        "nextEpisodeId": str(next_episode.get("id") or ""),
        "nextEpisodeTitle": str(next_episode.get("title") or ""),
        "sourceHasRemaining": source_has_remaining,
        "characterCount": character_count,
        "creatureCount": creature_count,
        "sceneCount": scene_count,
        "propCount": prop_count,
        "episodeCount": int(project.get("episodeCount") or len(episodes) or 1),
        "productionStatus": production_status,
        **production_progress,
        "stage": stage,
    }




def _agent_task_progress_content_block(
    steps: list[dict[str, Any]] | None,
    *,
    title: str = "创建项目拆分流程",
) -> dict[str, Any] | None:
    normalized_steps = _normalize_agent_session_step_rows(steps)
    if not normalized_steps:
        return None
    statuses = {str(step.get("status") or "idle") for step in normalized_steps}
    if "failed" in statuses:
        status = "failed"
    elif "running" in statuses:
        status = "running"
    elif normalized_steps and all(step.get("status") == "done" for step in normalized_steps):
        status = "completed"
    else:
        status = "idle"
    return {
        "type": "task_progress",
        "title": title,
        "status": status,
        "steps": normalized_steps,
    }










def _agent_production_route(state: dict[str, Any], target: dict[str, Any] | None = None) -> dict[str, Any]:
    route = _agent_current_route_state(state)
    if target and (target.get("workChainId") or target.get("routeId")):
        status = state.get("productionStatus") or {}
        candidates = list(status.get("routeStates") or [])
        for chain_status in (status.get("independentWorkChains") or {}).values():
            candidates.extend(chain_status.get("routeStates") or [])
        route = next((row for row in candidates
            if (not target.get("workChainId") or row.get("workChainId") == target["workChainId"])
            and (not target.get("routeId") or row.get("routeId") == target["routeId"])), {})
    return route


def _agent_production_actions(state: dict[str, Any], target: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    route = _agent_production_route(state, target)
    return [dict(action) for action in route.get("availableActions") or [] if isinstance(action, dict)]


_AGENT_OPTIONAL_PRODUCTION_TASK_TYPES = {
    "workflow_cinematic_script_generation",
    "storyboard_image_generation",
    "visual_handoff_image_generation",
}


def _agent_default_production_flow_step(state: dict[str, Any]) -> dict[str, Any]:
    actions = _agent_production_actions(state)
    if len(actions) != 1:
        return {}
    return actions[0] if actions[0].get("taskType") not in _AGENT_OPTIONAL_PRODUCTION_TASK_TYPES else {}


def _agent_production_action_target(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "agent_recommendation", "intent": "generate", "section": "episode",
        "episodeId": state.get("selectedEpisodeId"), "nodeId": action["nodeId"],
        "nodeType": action["nodeType"], "workChainId": action["workChainId"], "routeId": action["routeId"],
    }


def _agent_bind_production_continuation(
    state: dict[str, Any], message: str, selected_task: str,
    target: dict[str, Any] | None, pending: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    if state.get("stage") != "production" or pending.get("active") or not _agent_message_continues_flow(message):
        return selected_task, target
    if (target or {}).get("source") == "agent_recommendation":
        return selected_task, target
    action = _agent_default_production_flow_step(state)
    if not action or (selected_task and selected_task != action["taskType"]):
        return selected_task, target
    return action["taskType"], _agent_production_action_target(state, action)


def _agent_preferred_production_task_status_result(
    state: dict[str, Any],
    notice: str,
    *,
    task_type: str,
    route_source: str,
) -> dict[str, Any]:
    result = _agent_project_status_result(state, "")
    progress_message = str(result.get("message") or "").strip()
    reply = f"{notice}\n\n{progress_message}" if progress_message else notice
    result["message"] = reply
    content_blocks = copy.deepcopy(
        result.get("contentBlocks") if isinstance(result.get("contentBlocks"), list) else []
    )
    if content_blocks and isinstance(content_blocks[0], dict) and content_blocks[0].get("type") == "text":
        base_text = str(content_blocks[0].get("text") or "").strip()
        content_blocks[0]["text"] = f"{notice}\n\n{base_text}" if base_text else notice
    else:
        content_blocks.insert(0, {"type": "text", "text": notice})
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "recommendations" and block.get("origin") == "progress_query":
            block["summary"] = reply
    result["contentBlocks"] = content_blocks
    result["agentModelMeta"] = {
        "source": "local-controller",
        "taskHypothesis": {
            "taskType": task_type,
            "routeSource": route_source,
        },
    }
    return result


def _agent_control_preferred_production_task_result(
    state: dict[str, Any],
    selected_preferred_task_type: str,
    active_target: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    task_type = str(selected_preferred_task_type or "").strip()
    if task_type not in _AGENT_DEFAULT_PRODUCTION_TASK_TYPES:
        return None
    target_state_id = _AGENT_PRODUCTION_STEP_STATES.get(task_type, "")
    if not target_state_id:
        return None
    canvas_node_type = {
        "workflow_cinematic_script_generation": "prompt.storyboard",
        "director_plan_generation": "director.board",
        "video_prompt_generation": "video.storyboard",
    }.get(task_type)
    canvas_native_target = (
        bool(canvas_node_type)
        and isinstance(active_target, dict)
        and active_target.get("source") == "storyboard_canvas"
        and active_target.get("intent") == "generate"
        and active_target.get("section") == "episode"
        and active_target.get("canvasKind") == "work_chain"
        and active_target.get("nodeType") == canvas_node_type
        and all(active_target.get(key) for key in ("episodeId", "routeId", "workChainId", "nodeId"))
    )
    if not (is_work_chain_recommendation_target(active_target) or canvas_native_target):
        return _agent_preferred_production_task_status_result(
            state, "推荐缺少完整的工作链目标，请重新检查进度后选择；本次未启动生成任务。",
            task_type=task_type, route_source="control_preferred_task_missing_target",
        )
    if (active_target or {}).get("episodeId") and active_target["episodeId"] != state.get("selectedEpisodeId"):
        return _agent_preferred_production_task_status_result(
            state, _AGENT_STALE_PRODUCTION_RECOMMENDATION_MESSAGE,
            task_type=task_type, route_source="control_preferred_task_stale",
        )
    # A canvas generation command may intentionally regenerate a completed result.
    # Verify the node binding here so a stale selection does not start an SDK turn.
    if canvas_native_target:
        try:
            from .canvas_store_queries import read_canvas_card_record_v4
            node = read_canvas_card_record_v4(
                str(state.get("projectId") or ""), str(state.get("selectedEpisodeId") or ""),
                str(active_target["nodeId"]), detail="summary",
            )
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            if (node.get("type") != canvas_node_type
                    or str(node.get("routeId") or data.get("routeId") or "") != str(active_target["routeId"])
                    or str(node.get("workChainId") or data.get("workChainId") or "") != str(active_target["workChainId"])):
                raise ValueError("目标节点已变化")
        except (ValueError, FileNotFoundError, OSError):
            return _agent_preferred_production_task_status_result(
                state, _AGENT_STALE_PRODUCTION_RECOMMENDATION_MESSAGE,
                task_type=task_type, route_source="control_preferred_task_stale",
            )
        return None
    choices = _agent_production_actions(state, active_target)
    if any(
        action.get("taskType") == task_type
        and action.get("nodeId") == active_target["nodeId"]
        and action.get("nodeType") == active_target["nodeType"]
        for action in choices
    ):
        return None
    completed_states = set(_agent_production_route(state, active_target).get("completedStates") or [])
    if target_state_id in completed_states:
        return _agent_preferred_production_task_status_result(
            state,
            _AGENT_PRODUCTION_TASK_COMPLETED_MESSAGES.get(
                task_type,
                "当前环节已生成，不需要再生成。",
            ),
            task_type=task_type,
            route_source="control_preferred_task_already_completed",
        )
    return _agent_preferred_production_task_status_result(
        state, _AGENT_STALE_PRODUCTION_RECOMMENDATION_MESSAGE,
        task_type=task_type, route_source="control_preferred_task_stale",
    )


def _agent_work_chain_plan_already_generated_result(
    state: dict[str, Any],
    selected_preferred_task_type: str,
) -> dict[str, Any] | None:
    task_type = str(selected_preferred_task_type or "").strip()
    if task_type != "work_chain_plan_save":
        return None
    production_status = (
        state.get("productionStatus")
        if isinstance(state.get("productionStatus"), dict)
        else {}
    )
    if not bool(state.get("episodeWorkflowReady")) and not bool(production_status.get("workflowReady")):
        return None
    return _agent_preferred_production_task_status_result(
        state,
        "当前集工作链画布已生成，不需要再生成。",
        task_type="work_chain_plan_save",
        route_source="work_chain_plan_already_generated",
    )


def _agent_progress_status_block_steps(state: dict[str, Any]) -> list[dict[str, Any]]:
    if bool(state.get("projectScope", True)):
        rows = [
            ("source", "源文本", bool(state.get("sourceReady"))),
            ("overview", "项目概述", bool(state.get("overviewReady"))),
            ("assets", "资产拆分", bool(state.get("assetExtractionReady"))),
            ("episodes", "分集原文", bool(state.get("episodeBoundaryReady"))),
        ]
        return [
            {"id": step_id, "label": label, "status": "done" if done else "idle"}
            for step_id, label, done in rows
        ]

    completed_states = _agent_current_route_completed_states(state)
    current_route_id = str(_agent_current_route_state(state).get("routeId") or "").strip()
    handoff_label = next(
        action["label"] for action in WORK_CHAIN_ACTIONS
        if action["stateId"] == "visual_handoff.generated"
    )
    production_status = state.get("productionStatus") if isinstance(state.get("productionStatus"), dict) else {}
    handoff_step = next(
        (step for step in production_status.get("steps") or []
         if isinstance(step, dict) and step.get("id") == "visual_handoff.generated"),
        {},
    )
    handoff_route = next(
        (row for row in handoff_step.get("routeStatuses") or []
         if isinstance(row, dict) and str(row.get("routeId") or "").strip() == current_route_id),
        {},
    )
    if handoff_route.get("status") == "partial":
        handoff_label = f"{handoff_label} · {handoff_route['generatedUnitCount']}/{handoff_route['unitCount']} 已完成"

    workflow_ready = bool(state.get("episodeWorkflowReady"))
    rows = [
        ("workflow", "拆分剧情生成工作链", workflow_ready),
        *((action["stateId"], handoff_label if action["stateId"] == "visual_handoff.generated" else action["label"],
           action["stateId"] in completed_states) for action in WORK_CHAIN_ACTIONS),
    ]
    result: list[dict[str, Any]] = []
    for step_id, label, done in rows:
        if step_id == "cinematic_script.generated" and not done and completed_states.intersection({"director_plan.generated", "storyboard.generated", "video.generated"}):
            continue
        status = "done" if done else "idle"
        result.append({"id": step_id, "label": label, "status": status})
    return result


def _agent_progress_content_blocks(state: dict[str, Any], message: str = "") -> list[dict[str, Any]]:
    reply = _agent_progress_message(state, message, include_next_step=False)
    blocks: list[dict[str, Any]] = [{"type": "text", "text": reply}]
    progress_block = _agent_task_progress_content_block(
        _agent_progress_status_block_steps(state),
        title="项目主流程" if bool(state.get("projectScope", True)) else "工作链画布流程",
    )
    if progress_block:
        blocks.append(progress_block)
    recommendation_block = _agent_next_step_recommendations_block(
        state, origin="progress_query", summary=reply,
    )
    if recommendation_block:
        blocks.append(recommendation_block)
    return blocks


def _agent_result_content_blocks(project_id: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    thinking = str(result.get("agentThinking") or "").strip()
    if thinking:
        blocks.append({"type": "thinking", "title": "智能体判断", "text": thinking})
    action = str(result.get("agentAction") or "").strip()
    if action:
        state = result.get("agentState") if isinstance(result.get("agentState"), dict) else {}
        tool_block: dict[str, Any] = {
            "type": "tool_use",
            "id": str(result.get("toolUseId") or f"tool-{uuid.uuid4().hex[:8]}"),
            "name": "ai_video_storyboard_action",
            "input": {
                "action": action,
                "label": _agent_action_label(action, state) if state else action,
            },
        }
        tool_result = str(result.get("toolResult") or "").strip()
        if tool_result:
            tool_block["result"] = _compact_text(tool_result, 1200)
        blocks.append(tool_block)
    structured_blocks = _normalize_agent_content_blocks(
        result.get("contentBlocks") or result.get("content_blocks"),
        project_id,
        hydrate=False,
    )
    attachment_blocks = _agent_blocks_from_attachment_fields(project_id, result)
    message = str(result.get("message") or "").strip()
    if structured_blocks:
        if message and not _agent_blocks_have_body_text(structured_blocks):
            blocks.extend(
                _normalize_agent_content_blocks(
                    [{"type": "text", "text": message}],
                    project_id,
                    hydrate=False,
                )
            )
        blocks.extend(structured_blocks)
    elif message:
        blocks.extend(
            _normalize_agent_content_blocks(
                [{"type": "text", "text": message}],
                project_id,
                hydrate=False,
            )
        )
    if attachment_blocks:
        blocks.extend(attachment_blocks)
    if result.get("showTaskProgressBlock"):
        progress_block = _agent_task_progress_content_block(result.get("steps"))
        if progress_block:
            blocks.append(progress_block)
    return _agent_move_tail_content_blocks(blocks)


def _agent_move_tail_content_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tail_blocks: list[dict[str, Any]] = []
    normal_blocks: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        clean_block = copy.deepcopy(block)
        placement = str(clean_block.pop("placement", "") or "").strip()
        if clean_block.get("type") == "text" and placement == "message_tail":
            tail_blocks.append(clean_block)
        else:
            normal_blocks.append(clean_block)
    for block in tail_blocks:
        normal_blocks = _agent_attach_action_footer_to_content_blocks(
            normal_blocks,
            str(block.get("text") or ""),
        )
    return normal_blocks


def _agent_tool_result_summary(
    action: str,
    state: dict[str, Any] | None,
    result: dict[str, Any],
) -> str:
    effect = result.get("projectEffect") if isinstance(result.get("projectEffect"), dict) else {}
    notice = str(effect.get("notice") or "").strip()
    if notice:
        return notice
    label = _agent_action_label(action, state or {})
    if result.get("success") is False:
        return f"执行失败：{label}"
    return f"已执行：{label}"


def _agent_project_effect_for_action(
    action: str | None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    normalized = str(action or "").strip()
    if not normalized:
        return None
    state = state if isinstance(state, dict) else {}
    mapping: dict[str, dict[str, Any]] = {
        "analyze_overview": {
            "changedResources": ["overview"],
            "focusTarget": {"section": "overview"},
            "notice": "智能体已更新项目概述",
        },
    }
    effect = copy.deepcopy(mapping.get(normalized))
    if not effect:
        return None
    effect["action"] = normalized
    return effect




def _agent_recommended_action(state: dict[str, Any]) -> str:
    stage = str(state.get("stage") or "assets")
    if stage == "overview":
        action = "analyze_overview"
    else:
        action = "show_progress"
    if action in _agent_allowed_actions():
        return action
    ordered = _agent_action_order()
    return ordered[0] if ordered else "show_progress"


def _agent_recommendation_item(
    item_id: str,
    label: str,
    description: str,
    prompt: str,
    *,
    mode: str = "prompt",
    action: str = "",
    task_type: str = "",
    recommended: bool = False,
) -> dict[str, Any] | None:
    normalized_mode = "action" if mode == "action" else "prompt"
    normalized_action = str(action or "").strip()
    normalized_task_type = _agent_validate_task_type(task_type)
    # 推荐项默认只是下一轮提示词。只有客观信息或明确生成类固定操作才保留 action 语义。
    # 页面导航、上传文本等项目界面操作不在对话推荐中做程序直达。
    if normalized_mode == "action" and normalized_action not in _agent_program_direct_actions():
        normalized_mode = "prompt"
        normalized_action = ""
    if normalized_mode == "action":
        normalized_task_type = ""
    control_only = bool(
        normalized_task_type in _AGENT_CONTROL_ONLY_TASK_TYPES
        or (normalized_mode == "action" and normalized_action)
    )
    return {
        "id": item_id,
        "label": label,
        "description": description,
        "mode": normalized_mode,
        "prompt": prompt,
        "recommended": recommended,
        **({"action": normalized_action} if normalized_mode == "action" else {}),
        **({"taskType": normalized_task_type} if normalized_task_type else {}),
        **({"controlOnly": True} if control_only else {}),
    }


def _agent_control_only_quick_prompt_message(quick_prompt_id: str | None) -> str:
    return _AGENT_CONTROL_ONLY_QUICK_PROMPT_MESSAGES.get(
        str(quick_prompt_id or "").strip(),
        "",
    )




def _agent_stage_recommendations(state: dict[str, Any]) -> list[dict[str, Any]]:
    selected_title = str(state.get("selectedEpisodeTitle") or state.get("selectedEpisodeId") or "当前集")
    stage = str(state.get("stage") or "assets")
    project_scope = bool(state.get("projectScope", True))
    production_status = state.get("productionStatus") if isinstance(state.get("productionStatus"), dict) else {}
    work_chain_number = int(state.get("currentWorkChainNumber") or 0)
    work_chain_count = int(state.get("workChainCount") or 0)
    work_chain_label = (
        f"第 {work_chain_number} 条工作链"
        if work_chain_number
        else str(production_status.get("currentWorkChainId") or "当前工作链")
    )
    if work_chain_count:
        work_chain_label = f"{work_chain_label}（共 {work_chain_count} 条）"
    rows: list[dict[str, Any] | None]
    if not project_scope and stage in {"missing_source", "overview", "assets", "episode_boundary"}:
        prerequisite = {
            "missing_source": "当前项目尚未上传小说原文，请先在项目会话准备原文。",
            "overview": "当前项目尚未完成概述，请先在项目会话生成项目概述。",
            "assets": "当前项目的资产分析或原文覆盖尚未完成，请先在项目会话完成资产拆分。",
            "episode_boundary": "当前集尚未提交分集原文，请先在项目会话规划并确认分集。",
        }[stage]
        rows = [
            {
                "id": "open_project_conversation",
                "label": "前往项目会话",
                "description": prerequisite,
                "mode": "navigation",
                "destination": "project_session",
                "prompt": "",
                "recommended": True,
            }
        ]
    elif stage == "missing_source":
        rows = [
            _agent_recommendation_item(
                "prepare_source",
                "说明准备要求",
                "了解开始拆分前需要准备的文本和参考素材。",
                "我还没上传小说文本，请告诉我开始 ai-video 拆分前需要准备哪些素材。",
                task_type="free_chat",
                recommended=True,
            ),
        ]
    elif stage == "overview":
        rows = [
            _agent_recommendation_item(
                "analyze_overview",
                "生成项目概述",
                "分析小说文本，生成项目概述、题材语境和主题视觉。",
                "请先生成项目概述。",
                mode="action",
                action="analyze_overview",
                recommended=True,
            ),
            _agent_recommendation_item(
                "discuss_overview",
                "先看概述判断",
                "讨论项目概述、题材语境和主题视觉的判断依据。",
                "请根据当前项目说明项目概述、题材语境和主题视觉分别应如何判断。",
                task_type="free_chat",
            ),
        ]
    elif stage == "assets" and int(state.get("blockingAssetRangeCount") or 0) > 0:
        blocking_label = str(state.get("blockingAssetRangeLabel") or "上一段资产范围").strip()
        blocking_range = state.get("blockingAssetRange") if isinstance(state.get("blockingAssetRange"), dict) else {}
        analysis_status = str(blocking_range.get("analysisStatus") or "").strip().lower()
        if analysis_status in {"committed", "failed", "cancelled", "canceled"}:
            rows = [
                _agent_recommendation_item(
                    "asset_extraction",
                    "拆分当前资产",
                    f"{blocking_label}已确认；读取本段原文和已有资产，拆出角色、生物、场景、道具并校验保存。",
                    f"请拆分已确认的{blocking_label}中的角色、生物、场景和道具。核对原文和已有资产后提交本段结果，完成后简要报告。",
                    task_type="asset_extraction",
                    recommended=True,
                ),
                _agent_recommendation_item(
                    "check_asset_status",
                    "查看资产拆分状态",
                    "查看已确认范围和当前资产拆分状态。",
                    "请检查当前资产范围和资产拆分状态，告诉我下一步需要处理什么。",
                    task_type="project_status",
                ),
            ]
        else:
            rows = [
                _agent_recommendation_item(
                    "check_asset_status",
                    "查看资产拆分状态",
                    "当前资产任务正在执行或状态待核对；先确认状态，避免重复提交。",
                    "请检查当前资产拆分状态，告诉我它是否仍在执行以及需要处理什么；不要重复发起拆分。",
                    task_type="project_status",
                    recommended=True,
                ),
            ]
    elif stage == "assets":
        rows = [
            _agent_recommendation_item(
                "plan_asset_range",
                "规划资产范围",
                "按目标字数附近规划下一段原文范围，选择不切断资产连续描述的自然断点。",
                "请规划下一段资产提取范围，确定原文断点，并判断是否需要新增整体阶段视觉。通过校验后写入项目。",
                task_type="asset_range_propose",
                recommended=True,
            ),
            _agent_recommendation_item(
                "plan_episode_boundary",
                "改为规划下一集断点",
                "如果想先做分集，先确定下一集的原文结束位置、字数和理由。",
                "请规划下一集的自然断点，从本集原文提炼一个有辨识度的短标题，并说明断点依据与必要风险。通过校验后写入项目。",
                task_type="episode_boundary_propose",
            ),
            _agent_recommendation_item(
                "compare_asset_order",
                "先判断资产顺序",
                "讨论当前项目的资产拆分顺序和依据。",
                "请根据当前项目比较角色、生物、场景和道具的拆分顺序，并说明依据。",
                task_type="free_chat",
            ),
        ]
    elif stage == "episode_boundary":
        rows = [
            _agent_recommendation_item(
                "plan_episode_boundary",
                "规划下一集断点",
                "确定下一集的原文范围、字数和断点理由，通过校验后保存。",
                "请规划下一集的自然断点，从本集原文提炼一个有辨识度的短标题，并说明断点依据与必要风险。通过校验后写入项目。",
                task_type="episode_boundary_propose",
                recommended=True,
            ),
            _agent_recommendation_item(
                "discuss_episode_boundary",
                "先讨论断点标准",
                "讨论下一集断点的判断标准。",
                "请根据当前项目说明下一集断点应如何判断，重点看钩子、冲突推进和自然段落。",
                task_type="free_chat",
            ),
        ]
    elif stage == "episode_workflow":
        rows = [
            _agent_recommendation_item(
                "plan_episode_work_chains",
                "生成当前集工作链",
                "读取本集原文，按完整事件拆分剧情并关联每段所需资产；确认后创建画布工作链。",
                f"请拆分{selected_title}的剧情，并为每段关联已有资产。先展示待确认的结果，我确认后再保存工作链画布。",
                task_type="work_chain_plan_save",
                recommended=True,
            ),
            _agent_recommendation_item(
                "discuss_workflow",
                "先讨论分镜节奏",
                "讨论这一集适合的剧本节奏和镜头安排。",
                f"请只讨论{selected_title}适合怎样的剧本节奏和分镜安排。",
                task_type="work_chain_plan_discuss",
            ),
        ]
    elif stage == "production":
        choices = _agent_production_actions(state)
        continuity_tasks = {"visual_handoff_image_generation", "storyboard_image_generation"}
        primary_choice = (
            next((choice for choice in choices if choice.get("taskType") in continuity_tasks), None)
            or next((choice for choice in choices if choice.get("taskType") not in _AGENT_OPTIONAL_PRODUCTION_TASK_TYPES), None)
            or (choices[0] if choices else None)
        )
        rows = []
        for choice in choices:
            choice_label = str(choice["label"]).removesuffix("（可选）")
            row = _agent_recommendation_item(
                choice["id"], choice_label,
                f"只为{work_chain_label}执行此操作，完成后停止。",
                f"请为{selected_title}的{work_chain_label}{choice_label}。只执行这一个操作，完成后停止。",
                task_type=choice["taskType"],
                recommended=choice is primary_choice,
            )
            if row:
                row["targetContext"] = _agent_production_action_target(state, choice)
                rows.append(row)
        if not choices:
            completed_video_count = int(state.get("completedVideoWorkChainCount") or 0)
            episode_media_complete = bool(state.get("episodeMediaComplete")) or (
                work_chain_count > 0 and completed_video_count >= work_chain_count
            )
            if episode_media_complete:
                rows = [
                    _agent_recommendation_item(
                        "current_episode_complete",
                        "当前集已完成",
                        "当前集所有工作链视频已生成完成。",
                        f"请只汇总{selected_title}当前集工作链画布和视频完成状态；不要重复生成当前视频。",
                        task_type="project_status",
                        recommended=True,
                    )
                ]
            else:
                rows = [
                    _agent_recommendation_item(
                        "check_current_work_chain",
                        "检查当前工作链",
                        "当前集仍有未完成内容，但没有定位到可直接继续的主线环节，需要先检查工作链状态。",
                        f"请检查{selected_title}的{work_chain_label}当前状态，只告诉我需要处理什么，不要自动生成资产图、片段剧本、分镜脚本、分镜图、视觉交接图或视频片段。",
                        task_type="project_status",
                        recommended=True,
                    )
                ]
    elif stage == "episode_complete":
        next_episode_id = str(state.get("nextEpisodeId") or "").strip()
        next_episode_title = str(state.get("nextEpisodeTitle") or next_episode_id or "下一集").strip()
        if not project_scope:
            rows = [
                _agent_recommendation_item(
                    "current_episode_complete",
                    "当前集已完成",
                    "当前集所有工作链视频已完成；当前集会话不会继续规划下一集。",
                    f"请只汇总{selected_title}当前集所有工作链视频完成状态；不要建议拆分资产、规划下一集或切换到其他集。",
                    task_type="project_status",
                    recommended=True,
                )
            ]
        elif next_episode_id:
            rows = [
                _agent_recommendation_item(
                    "continue_next_episode",
                    f"进入{next_episode_title}",
                    "当前集分集原文已完成，下一步切换到下一集继续拆分分集原文。",
                    f"{selected_title}的分集原文已完成。请检查{next_episode_title}（{next_episode_id}）的主流程状态并告诉我下一步。",
                    task_type="project_status",
                    recommended=True,
                )
            ]
        elif not bool(state.get("nextEpisodeAssetCoverageReady", True)):
            cursor_offset = int(state.get("nextEpisodeAssetCoverageCursorOffset") or 0)
            required_end = int(state.get("nextEpisodeAssetCoverageRequiredEnd") or 0)
            gap_units = int(state.get("nextEpisodeAssetCoverageGapUnits") or 0)
            asset_target_units = int(state.get("assetExtractionTargetUnits") or DEFAULT_ASSET_EXTRACTION_TARGET_UNITS)
            rows = [
                _agent_recommendation_item(
                    "propose_next_asset_range",
                    "先拆下一段资产",
                    f"下一集断点预计需要覆盖到 {required_end}，当前资产只覆盖到 {cursor_offset}，还差约 {gap_units} 字。",
                    f"当前集分集原文已完成。下一集需要先补足资产范围，请按当前约 {asset_target_units} 字的资产范围目标规划下一段原文断点，并判断是否需要新增整体阶段视觉。通过校验后写入项目。",
                    task_type="asset_range_propose",
                    recommended=True,
                )
            ]
        else:
            rows = [
                _agent_recommendation_item(
                    "propose_next_episode_boundary",
                    "规划下一集",
                    "当前集分集原文已完成，继续从小说剩余内容规划下一集。",
                    "当前集分集原文已完成。请规划下一集的自然断点和短标题，说明依据与必要风险。通过校验后写入项目。",
                    task_type="episode_boundary_propose",
                    recommended=True,
                )
            ]
    elif stage == "project_complete":
        if project_scope:
            rows = [
                _agent_recommendation_item(
                    "production_complete",
                    "本项目流程已完成",
                    "所有可拆分剧集的分集原文都已完成，插件内主流程到此结束。",
                    "请只汇总当前项目各集的分集原文完成状态，并说明插件内主流程已完成；不要主动展开工作链或某集内部生产细节，也不要建议剪辑、合并或成片导出。",
                    task_type="project_status",
                    recommended=True,
                )
            ]
        else:
            rows = [
                _agent_recommendation_item(
                    "current_episode_complete",
                    "当前集已完成",
                    "当前集所有工作链视频已完成；当前集会话只汇报本集状态。",
                    f"请只汇总{selected_title}当前集所有工作链视频完成状态；不要建议拆分资产、规划下一集或切换到其他集。",
                    task_type="project_status",
                    recommended=True,
                )
            ]
    else:
        rows = [
            _agent_recommendation_item(
                "check_current_episode",
                "检查当前集状态",
                "让智能体分析当前集的剧情、剧本和分镜状态。",
                f"请检查{selected_title}当前剧情、剧本和分镜状态，并说明需要我确认的问题。",
                task_type="quality_review",
                recommended=True,
            ),
            _agent_recommendation_item(
                "review_next_improvement",
                "检查可优化点",
                "查看当前集还有哪些剧情、剧本或分镜问题。",
                f"请检查{selected_title}当前还有哪些可以优化的剧情、剧本或分镜问题。",
                task_type="quality_review",
            ),
        ]
    return [row for row in rows if row]


def _agent_next_step_recommendations_block(
    state: dict[str, Any],
    *,
    origin: str,
    summary: str = "",
) -> dict[str, Any] | None:
    items = _agent_stage_recommendations(state)
    if not items:
        return None
    return {
        "type": "recommendations",
        "title": "下一步操作",
        "origin": origin,
        **({"summary": summary} if summary else {}),
        "items": copy.deepcopy(items),
    }


_AGENT_CONTROL_ONLY_TASK_TYPES = {
    "video_prompt_generation",
    "project_status",
    "asset_range_propose",
    "asset_extraction",
    "episode_boundary_propose",
    "work_chain_plan_save",
    "workflow_cinematic_script_generation",
    "director_plan_generation",
    "storyboard_image_generation",
    "visual_handoff_image_generation",
    "storyboard_video_generation",
}


_AGENT_CONTROL_ONLY_QUICK_PROMPT_MESSAGES = {
    "confirm": "确认",
    "continue": "继续",
}


_AGENT_DEFAULT_PRODUCTION_TASK_TYPES = {
    action["taskType"] for action in WORK_CHAIN_ACTIONS
}


_AGENT_PRODUCTION_TASK_COMPLETED_MESSAGES = {
    "video_prompt_generation": "当前视频生成已有可用提示词，不需要默认重新生成。",
    "workflow_cinematic_script_generation": "当前环节的影视化剧本已生成，不需要再生成。",
    "director_plan_generation": "当前环节的分镜脚本已生成，不需要再生成。",
    "storyboard_image_generation": "当前环节的分镜图已生成，不需要再生成。",
    "storyboard_video_generation": "当前环节的视频已生成，不需要再生成。",
}


_AGENT_STALE_PRODUCTION_RECOMMENDATION_MESSAGE = "这条推荐已不是当前最新环节，我已重新检查画布状态；请按新的默认下一步继续。"


def _agent_overview_ready(meta: dict[str, Any]) -> bool:
    overview_analysis = (
        meta.get("overview_analysis")
        if isinstance(meta.get("overview_analysis"), dict)
        else {}
    )
    result = overview_analysis.get("result")
    if not isinstance(result, dict):
        return False
    excerpt_summary = _first_text(
        result.get("excerpt_summary") or result.get("excerptSummary")
    )
    genre_context = _first_text(
        result.get("genre_context") or result.get("genreContext")
    )
    theme_visual_context = _first_text(
        result.get("theme_visual_context") or result.get("themeVisualContext")
    )
    # Match the overview page's completion criteria. Legacy projects and users
    # clearing the optional voice field still use the local narrator fallback.
    return bool(excerpt_summary and genre_context and theme_visual_context)


def _agent_episode_boundary_ready(project_id: str, episode_id: str | None) -> bool:
    episode_id = str(episode_id or "").strip()
    if not episode_id:
        return False
    source_path = _episode_source_text_path(project_id, episode_id)
    if not source_path.exists() or not source_path.is_file():
        return False
    try:
        if source_path.stat().st_size <= 0:
            return False
    except OSError:
        return False
    source_ref_path = _episode_source_ref_path(project_id, episode_id)
    source_ref = _read_json(source_ref_path, {}) if source_ref_path.exists() else {}
    if not isinstance(source_ref, dict) or not source_ref:
        return False
    ref_episode_id = str(source_ref.get("episodeId") or source_ref.get("episode_id") or "").strip()
    if ref_episode_id and ref_episode_id != episode_id:
        return False
    try:
        coverage = _load_source_coverage(project_id)
    except Exception:
        coverage = {}
    episode_range = next(
        (
            item
            for item in coverage.get("episodeRanges", [])
            if isinstance(item, dict)
            and str(item.get("episodeId") or item.get("episode_id") or "").strip()
            == episode_id
        ),
        {},
    )
    if not isinstance(episode_range, dict) or not episode_range:
        return False
    ref_start, ref_end = _source_ref_bounds(source_ref)
    range_start, range_end = _source_ref_bounds(episode_range)
    if None in (ref_start, ref_end, range_start, range_end):
        return False
    return ref_start == range_start and ref_end == range_end


def _agent_source_total_chars(project_id: str, coverage: dict[str, Any] | None = None) -> int:
    source_id = str((coverage or {}).get("sourceId") or "").strip()
    result = get_source_text(project_id, source_id or None)
    text = str(result.get("text") or "")
    try:
        return max(0, int(result.get("charCount") or content_char_count(text)))
    except (TypeError, ValueError):
        return content_char_count(text)


def _agent_episode_production_progress(production_status: dict[str, Any]) -> dict[str, Any]:
    route_states = [
        item
        for item in production_status.get("routeStates") or []
        if isinstance(item, dict)
    ]
    completed_video_work_chains = [
        item
        for item in route_states
        if "video.generated" in {
            str(state_id or "").strip()
            for state_id in item.get("completedStates") or []
        }
    ]
    def route_has_open_default_state(item: dict[str, Any]) -> bool:
        route_completed = {
            str(state_id or "").strip()
            for state_id in item.get("completedStates") or []
            if str(state_id or "").strip()
        }
        if "video.generated" in route_completed:
            return False
        return True

    current_route_id = str(production_status.get("currentRouteId") or "").strip()
    current_work_chain_id = str(production_status.get("currentWorkChainId") or "").strip()
    current_work_chain_number = 0
    for index, item in enumerate(route_states, start=1):
        route_id = str(item.get("routeId") or "").strip()
        work_chain_id = str(item.get("workChainId") or "").strip()
        if (current_route_id and route_id == current_route_id) or (
            current_work_chain_id and work_chain_id == current_work_chain_id
        ):
            if route_has_open_default_state(item):
                current_work_chain_number = index
            break
    if not current_work_chain_number and route_states:
        for index, item in enumerate(route_states, start=1):
            if route_has_open_default_state(item):
                current_work_chain_number = index
                break
    if not current_work_chain_number and route_states and len(completed_video_work_chains) < len(route_states):
        current_work_chain_number = len(completed_video_work_chains) + 1
    episode_media_complete = bool(route_states) and len(completed_video_work_chains) == len(route_states)
    episode_workflow_complete = episode_media_complete
    generated_work_chain_count = len(route_states)
    return {
        "workChainCount": len(route_states),
        "generatedWorkChainCount": generated_work_chain_count,
        "completedVideoWorkChainCount": len(completed_video_work_chains),
        "currentWorkChainNumber": current_work_chain_number,
        "episodeComplete": episode_workflow_complete,
        "episodeWorkflowComplete": episode_workflow_complete,
        "episodeMediaComplete": episode_media_complete,
    }


def _agent_progress_message(
    state: dict[str, Any],
    user_message: str = "",
    *,
    include_next_step: bool = True,
) -> str:
    project_scope = bool(state.get("projectScope", True))
    detail_mode = bool(state.get("episodeDetailMode") or not project_scope)
    stage = str(state.get("stage") or "").strip()
    episode_main_flow_complete = bool(
        state.get("episodeMainFlowComplete", state.get("episodeBoundaryReady"))
    )
    lines = [
        f"我先检查了《{state.get('projectName') or '当前项目'}》现在的拆分进度。",
        f"- 当前集：{state.get('selectedEpisodeTitle')}（{state.get('selectedEpisodeStatus')}）",
        f"- 小说文本：{'已就绪' if state.get('sourceReady') else '还未上传'}",
        f"- 项目概述：{'已完成' if state.get('overviewReady') else '待生成'}",
        f"- 角色 / 生物 / 场景 / 道具：{int(state.get('characterCount') or 0)} / {int(state.get('creatureCount') or 0)} / {int(state.get('sceneCount') or 0)} / {int(state.get('propCount') or 0)}",
        f"- 分集断点：{'已提交当前集原文' if state.get('episodeBoundaryReady') else '待规划/提交'}",
    ]
    if project_scope:
        lines.append(
            f"- 分集原文：{'已完成当前集拆分' if episode_main_flow_complete else '待拆分'}"
        )
    else:
        lines.append(
            f"- 原文事实 / 工作链画布：{'已同步当前集' if state.get('episodeWorkflowReady') and (state.get('episodeSourceSplitReady') or state.get('episodeScriptReady')) else '待生成/完善'}"
        )
    blocking_asset_range_count = int(state.get("blockingAssetRangeCount") or 0)
    if blocking_asset_range_count:
        blocking_label = str(state.get("blockingAssetRangeLabel") or "上一段资产范围").strip()
        blocking_range = state.get("blockingAssetRange") if isinstance(state.get("blockingAssetRange"), dict) else {}
        analysis_status = str(blocking_range.get("analysisStatus") or "").strip().lower()
        if analysis_status in {"committed", "failed", "cancelled", "canceled"}:
            lines.append(f"- 资产拆分：{blocking_label}已确认，等待拆分并保存资产")
        else:
            lines.append(f"- 资产拆分：{blocking_label}正在处理或状态待核对")
    elif not state.get("assetCoverageReadyForBoundary") and int(state.get("assetCoverageGapUnits") or 0) > 0:
        cursor_offset = int(state.get("assetCoverageCursorOffset") or 0)
        required_end = int(state.get("assetCoverageRequiredEnd") or 0)
        gap_units = int(state.get("assetCoverageGapUnits") or 0)
        lines.append(f"- 资产覆盖：已覆盖到 {cursor_offset}，下一集断点规划至少需要覆盖到 {required_end}，还差约 {gap_units} 字")
    if project_scope and episode_main_flow_complete:
        if stage == "project_complete" or state.get("sourceHasRemaining") is False:
            lines.append("- 当前集主流程：分集原文已完成，小说剩余内容已拆完")
        else:
            lines.append("- 当前集主流程：分集原文已完成，可继续规划下一集")
        if not bool(state.get("nextEpisodeAssetCoverageReady", True)):
            cursor_offset = int(state.get("nextEpisodeAssetCoverageCursorOffset") or 0)
            required_end = int(state.get("nextEpisodeAssetCoverageRequiredEnd") or 0)
            gap_units = int(state.get("nextEpisodeAssetCoverageGapUnits") or 0)
            lines.append(
                f"- 下一集资产覆盖：已覆盖到 {cursor_offset}，规划下一集预计需要覆盖到 {required_end}，还差约 {gap_units} 字"
            )
    work_chain_count = int(state.get("workChainCount") or 0)
    if work_chain_count:
        generated_count = int(state.get("generatedWorkChainCount") or 0)
        completed_video_count = int(state.get("completedVideoWorkChainCount") or 0)
        lines.append(f"- 工作链画布：已生成 {generated_count} / {work_chain_count}")
        if state.get("episodeComplete"):
            if not project_scope:
                lines.append("- 当前集主流程：所有工作链视频已完成")
        if detail_mode and not project_scope:
            lines.append(f"- 视频细节：已生成视频 {completed_video_count} / {work_chain_count}")
        if detail_mode and not project_scope and not state.get("episodeMediaComplete"):
            current_number = int(state.get("currentWorkChainNumber") or 0)
            default_flow_step = _agent_default_production_flow_step(state)
            current_action = str(default_flow_step.get("label") or _agent_stage_next_step_label(state)).strip()
            lines.append(
                f"- 当前环节：第 {current_number or completed_video_count + 1} 条工作链，{current_action}"
            )
    if not include_next_step:
        return "\n".join(lines)
    step = _agent_recommended_next_step(state)
    task_type = str(step.get("taskType") or "").strip() if isinstance(step, dict) else ""
    step_label = str(step.get("label") or "").strip() if isinstance(step, dict) else ""
    if step.get("mode") == "navigation":
        lines.extend(["", str(step.get("description") or ""), f"下一步：{step_label}。"])
    elif task_type and task_type not in {"free_chat", "project_status", "quality_review"}:
        lines.extend(["", f"默认下一步：{step_label or '继续当前流程'}。"])
    elif step_label:
        lines.extend(["", f"默认建议：{step_label}。"])
    elif state.get("stage") == "production" and len(_agent_production_actions(state)) > 1:
        lines.extend(["", f"请选择下一步：{_agent_stage_next_step_label(state)}。"])
    else:
        lines.extend(["", "这里只展示客观状态；当前没有可直接继续执行的下一步。"])
    return "\n".join(lines)


def _agent_project_status_result(state: dict[str, Any], message: str = "") -> dict[str, Any]:
    reply = _agent_progress_message(state, message, include_next_step=False)
    return {
        "success": True,
        "status": "idle",
        "backgroundStarted": False,
        "message": reply,
        "contentBlocks": _agent_progress_content_blocks(state, message),
        "steps": _agent_progress_status_block_steps(state),
        "pendingQuestion": None,
        "project": state["project"],
        "agentModelMeta": {
            "source": "local-controller",
            "taskHypothesis": {
                "taskType": "project_status",
                "routeSource": "preferred_task_project_status",
            },
        },
        "sessionStatus": "idle",
        "pendingOperation": None,
    }


def _agent_recommended_next_step(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("stage") == "production" and len(_agent_production_actions(state)) > 1:
        return {}
    rows = _agent_stage_recommendations(state)
    recommended = next((item for item in rows if item.get("recommended")), None)
    if state.get("stage") == "production":
        return recommended or {}
    return recommended or (rows[0] if rows else {})


def _agent_stage_next_step_label(state: dict[str, Any]) -> str:
    rows = _agent_stage_recommendations(state)
    if state.get("stage") == "production" and len(_agent_production_actions(state)) > 1:
        labels = [str(item.get("label") or "").strip() for item in rows]
        return "选择" + "、".join(label for label in labels if label)
    for item in rows:
        if item.get("recommended") and str(item.get("label") or "").strip():
            return str(item.get("label") or "").strip()
    if rows and str(rows[0].get("label") or "").strip():
        return str(rows[0].get("label") or "").strip()
    return _agent_action_label(_agent_recommended_action(state), state)


def _agent_workflow_explainer(state: dict[str, Any]) -> str:
    return "\n".join(
        [
            "ai-video 工作流拆分节奏会按阶段推进：",
            "1. 检查源文本与项目概述",
            "2. 拆出角色、生物、场景、道具",
            f"3. 从 {state.get('selectedEpisodeTitle') or state.get('selectedEpisodeId')} 对应的小说内容中拆出当前集分集原文，并提交 source.txt/source_ref.json",
            "4. 当前集分集原文完成后，项目主流程即可继续规划下一集，不等待工作链画布或视频片段生成",
            "5. 用户询问某一集下一步时，按当前工作链结果推荐：生成片段剧本（可选）与直接生成分镜脚本平级；分镜脚本之后生成分镜图、视频提示词和视频。资产图和视觉交接图只在用户明确指定时处理",
            "6. 剧情拆分的待确认结果、各任务的完成报告及下一步建议会显示在会话消息中。智能体每轮只协助执行当前一个环节",
            "7. 全部可拆分原文都完成分集原文后，插件内主流程结束；工作链和视频片段生成属于各集细节制作",
            "",
            "剪辑、视频合并和成片导出由外部完成，不属于这里的工作流。",
        ]
    )


def _agent_next_running_step_id(state: dict[str, Any]) -> str | None:
    for step in _agent_steps_from_state(state):
        if step.get("status") == "idle":
            return str(step.get("id") or "")
    return None
