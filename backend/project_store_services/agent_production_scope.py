# -*- coding: utf-8 -*-
"""生产范围中的分集、工作链、路由与节点身份解析。"""
from __future__ import annotations

from .agent_asset_range_state import (
    _agent_source_coverage_safe,
)
from .agent_context_runtime import (
    _agent_episode_number,
)
from .agent_session_policy import (
    latest_project_episode_id,
)
from .agent_sessions import (
    _project_meta_path,
)
from .store_core import (
    _read_json,
)

from .agent_contracts import (
    is_work_chain_recommendation_target,
)
from .agent_pending_operations import (
    _agent_message_continues_flow,
)
from .workflow_input_resolution import (
    resolve_generation_task_node_id,
)
from .workflow_projection import (
    get_canvas_workflow_projection,
)

from typing import Any


def _agent_production_status_from_state(state: dict[str, Any]) -> dict[str, Any]:
    value = state.get("productionStatus") if isinstance(state.get("productionStatus"), dict) else {}
    return value if isinstance(value, dict) else {}


def _agent_generation_flow_step_hypothesis(task_hypothesis: dict[str, Any] | None) -> bool:
    if not isinstance(task_hypothesis, dict):
        return False
    route_source = str(task_hypothesis.get("routeSource") or "").strip()
    execution_mode = str(task_hypothesis.get("executionMode") or "").strip()
    return (
        route_source == "production_single_step_confirmation"
        or execution_mode == "flow_step"
        or bool(task_hypothesis.get("flowStepOnly"))
    )


_AGENT_ASSET_IMAGE_TYPES = {"characters", "creatures", "scenes", "props"}


def _agent_normalize_asset_image_type(value: Any) -> str:
    text = str(value or "").strip()
    aliases = {
        "character": "characters",
        "characters": "characters",
        "creature": "creatures",
        "creatures": "creatures",
        "scene": "scenes",
        "scenes": "scenes",
        "prop": "props",
        "props": "props",
    }
    return aliases.get(text, "")


def _agent_asset_image_root_identity(data: dict[str, Any], node: dict[str, Any] | None = None) -> tuple[str, str]:
    if not isinstance(data, dict):
        return "", ""
    node = node if isinstance(node, dict) else {}
    root_asset_type = _agent_normalize_asset_image_type(
        data.get("rootAssetType")
        or node.get("rootAssetType")
    )
    root_asset_id = str(
        data.get("rootAssetId")
        or node.get("rootAssetId")
        or ""
    ).strip()
    if root_asset_type in _AGENT_ASSET_IMAGE_TYPES and root_asset_id:
        return root_asset_type, root_asset_id
    return "", ""


def _agent_flow_node_data(node: dict[str, Any]) -> dict[str, Any]:
    return node.get("data") if isinstance(node.get("data"), dict) else {}


def _agent_flow_node_route_id(node: dict[str, Any]) -> str:
    data = _agent_flow_node_data(node)
    return str(node.get("routeId") or data.get("routeId") or "").strip()


def _agent_flow_node_work_chain_id(node: dict[str, Any]) -> str:
    data = _agent_flow_node_data(node)
    return str(
        node.get("workChainId")
        or data.get("workChainId")
        or ""
    ).strip()


def _agent_collect_asset_ref_keys(value: Any, keys: set[tuple[str, str]], *, asset_type_hint: str = "") -> None:
    if isinstance(value, dict):
        asset_type = _agent_normalize_asset_image_type(
            value.get("rootAssetType")
            or value.get("assetType")
            or value.get("type")
            or asset_type_hint
            or ""
        )
        asset_id = str(
            value.get("rootAssetId")
            or value.get("assetId")
            or value.get("id")
            or ""
        ).strip()
        if asset_type in _AGENT_ASSET_IMAGE_TYPES and asset_id:
            keys.add((asset_type, asset_id))
        for key, item in value.items():
            next_hint = str(key or "").strip()
            normalized_next_hint = _agent_normalize_asset_image_type(next_hint)
            _agent_collect_asset_ref_keys(
                item,
                keys,
                asset_type_hint=next_hint if normalized_next_hint in _AGENT_ASSET_IMAGE_TYPES else asset_type_hint,
            )
        return
    if isinstance(value, list):
        for item in value:
            _agent_collect_asset_ref_keys(item, keys, asset_type_hint=asset_type_hint)


def _agent_route_ids_for_work_chain(workflow: dict[str, Any], work_chain_id: str) -> set[str]:
    if not work_chain_id:
        return set()
    route_ids: set[str] = set()
    for route in workflow.get("routes") or []:
        if not isinstance(route, dict):
            continue
        route_work_chain_id = str(route.get("workChainId") or "").strip()
        route_id = str(route.get("id") or "").strip()
        if route_id and route_work_chain_id == work_chain_id:
            route_ids.add(route_id)
    return route_ids


def _agent_flow_node_matches_scope(
    node: dict[str, Any],
    expected_route_id: str,
    expected_work_chain_id: str,
    route_ids_for_work_chain: set[str],
) -> bool:
    node_route_id = _agent_flow_node_route_id(node)
    node_work_chain_id = _agent_flow_node_work_chain_id(node)
    if expected_route_id and node_route_id and node_route_id != expected_route_id:
        return False
    if expected_work_chain_id and node_work_chain_id and node_work_chain_id != expected_work_chain_id:
        return False
    if expected_route_id and node_route_id == expected_route_id:
        return True
    if expected_work_chain_id and node_work_chain_id == expected_work_chain_id:
        return True
    if expected_work_chain_id and node_route_id and node_route_id in route_ids_for_work_chain:
        return True
    return False


def _agent_current_flow_asset_image_keys(
    workflow: dict[str, Any],
    expected_route_id: str,
    expected_work_chain_id: str,
) -> set[tuple[str, str]]:
    route_id = str(expected_route_id or "").strip()
    work_chain_id = str(expected_work_chain_id or "").strip()
    if not route_id and not work_chain_id:
        return set()
    route_ids_for_work_chain = _agent_route_ids_for_work_chain(workflow, work_chain_id)
    keys: set[tuple[str, str]] = set()
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if not _agent_flow_node_matches_scope(node, route_id, work_chain_id, route_ids_for_work_chain):
            continue
        data = _agent_flow_node_data(node)
        if str(node.get("type") or "").strip() == "asset.image":
            asset_type, asset_id = _agent_asset_image_root_identity(data, node)
            if asset_type in _AGENT_ASSET_IMAGE_TYPES and asset_id:
                keys.add((asset_type, asset_id))
        _agent_collect_asset_ref_keys(data.get("assetRefs"), keys)
    return keys


def _agent_current_flow_prompt_storyboard_node_id(
    project_id: str,
    episode_id: str | None,
    state: dict[str, Any],
    active_target: dict[str, Any] | None = None,
) -> str:
    current_episode_id = str(episode_id or state.get("selectedEpisodeId") or "E01").strip() or "E01"
    target = active_target if isinstance(active_target, dict) else {}
    target_node_id = str(target.get("nodeId") or target.get("node_id") or "").strip()
    target_node_type = str(target.get("nodeType") or target.get("node_type") or "").strip()
    try:
        workflow = get_canvas_workflow_projection(project_id, current_episode_id)
    except Exception:
        if target.get("source") == "agent_recommendation":
            return ""
        return target_node_id if target_node_type == "prompt.storyboard" else ""
    if target.get("source") == "agent_recommendation":
        return _agent_recommendation_node_id(workflow, current_episode_id, target, "prompt.storyboard")
    if target_node_id:
        node = next(
            (
                item
                for item in workflow.get("nodes") or []
                if isinstance(item, dict) and str(item.get("id") or "").strip() == target_node_id
            ),
            {},
        )
        if str(node.get("type") or "").strip() == "prompt.storyboard":
            return target_node_id
    route_identity = _agent_current_route_identity(state)
    expected_route_id = str(route_identity.get("routeId") or "").strip()
    expected_work_chain_id = str(route_identity.get("workChainId") or "").strip()
    if not expected_route_id and not expected_work_chain_id:
        production_status = state.get("productionStatus") if isinstance(state.get("productionStatus"), dict) else {}
        expected_route_id = str(production_status.get("currentRouteId") or "").strip()
        expected_work_chain_id = str(production_status.get("currentWorkChainId") or "").strip()
    route_ids_for_work_chain = _agent_route_ids_for_work_chain(workflow, expected_work_chain_id)
    fallback_node_id = ""
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("type") or "").strip() != "prompt.storyboard":
            continue
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        if not fallback_node_id:
            fallback_node_id = node_id
        if _agent_flow_node_matches_scope(
            node,
            expected_route_id,
            expected_work_chain_id,
            route_ids_for_work_chain,
        ):
            return node_id
    return fallback_node_id


def _agent_current_flow_director_board_node_id(
    project_id: str,
    episode_id: str | None,
    state: dict[str, Any],
    active_target: dict[str, Any] | None = None,
) -> str:
    current_episode_id = str(episode_id or state.get("selectedEpisodeId") or "E01").strip() or "E01"
    target = active_target if isinstance(active_target, dict) else {}
    target_node_id = str(target.get("nodeId") or target.get("node_id") or "").strip()
    try:
        workflow = get_canvas_workflow_projection(project_id, current_episode_id)
    except Exception:
        return ""
    if target.get("source") == "agent_recommendation":
        return _agent_recommendation_node_id(workflow, current_episode_id, target, "director.board")
    if target_node_id:
        resolved_node_id = resolve_generation_task_node_id(workflow, "storyboard_plan", target_node_id)
        resolved_node = next(
            (
                item
                for item in workflow.get("nodes") or []
                if isinstance(item, dict) and str(item.get("id") or "").strip() == resolved_node_id
            ),
            {},
        )
        if str(resolved_node.get("type") or "").strip() == "director.board":
            return str(resolved_node_id or "").strip()
    route_identity = _agent_current_route_identity(state)
    expected_route_id = str(route_identity.get("routeId") or "").strip()
    expected_work_chain_id = str(route_identity.get("workChainId") or "").strip()
    if not expected_route_id and not expected_work_chain_id:
        production_status = state.get("productionStatus") if isinstance(state.get("productionStatus"), dict) else {}
        expected_route_id = str(production_status.get("currentRouteId") or "").strip()
        expected_work_chain_id = str(production_status.get("currentWorkChainId") or "").strip()
    route_ids_for_work_chain = _agent_route_ids_for_work_chain(workflow, expected_work_chain_id)
    fallback_node_id = ""
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("type") or "").strip() != "director.board":
            continue
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        if not fallback_node_id:
            fallback_node_id = node_id
        if _agent_flow_node_matches_scope(
            node,
            expected_route_id,
            expected_work_chain_id,
            route_ids_for_work_chain,
        ):
            return node_id
    return fallback_node_id


def _agent_current_flow_storyboard_card_node_id(
    project_id: str,
    episode_id: str | None,
    state: dict[str, Any],
    active_target: dict[str, Any] | None = None,
) -> str:
    current_episode_id = str(episode_id or state.get("selectedEpisodeId") or "E01").strip() or "E01"
    target = active_target if isinstance(active_target, dict) else {}
    try:
        workflow = get_canvas_workflow_projection(project_id, current_episode_id)
    except Exception:
        return ""
    cards = [node for node in workflow.get("nodes") or []
             if isinstance(node, dict) and node.get("type") == "storyboard.card"]
    if target.get("source") == "agent_recommendation":
        recommended_id = _agent_recommendation_node_id(workflow, current_episode_id, target, "storyboard.card")
        if recommended_id:
            return recommended_id
    target_id = str(target.get("nodeId") or target.get("node_id") or "").strip()
    if target_id:
        direct = next((node for node in cards if node.get("id") == target_id), None)
        if direct:
            return target_id
        target_node = next((node for node in workflow.get("nodes") or []
                            if isinstance(node, dict) and node.get("id") == target_id), None)
        target_data = target_node.get("data") if isinstance((target_node or {}).get("data"), dict) else {}
        source_id = str(target_data.get("resultOfNodeId") or target_data.get("sourceNodeId") or "").strip()
        if any(node.get("id") == source_id for node in cards):
            return source_id
    route_identity = _agent_current_route_identity(state)
    expected_route_id = str(route_identity.get("routeId") or "").strip()
    expected_chain_id = str(route_identity.get("workChainId") or "").strip()
    if not expected_route_id and not expected_chain_id:
        production_status = state.get("productionStatus") if isinstance(state.get("productionStatus"), dict) else {}
        expected_route_id = str(production_status.get("currentRouteId") or "").strip()
        expected_chain_id = str(production_status.get("currentWorkChainId") or "").strip()
    route_ids = _agent_route_ids_for_work_chain(workflow, expected_chain_id)
    matched = [node for node in cards if _agent_flow_node_matches_scope(
        node, expected_route_id, expected_chain_id, route_ids,
    )]
    recommended_handoff_id = next(
        (str(action.get("nodeId") or "").strip()
         for action in _agent_current_route_state(state).get("availableActions") or []
         if isinstance(action, dict) and action.get("taskType") == "visual_handoff_image_generation"),
        "",
    )
    if recommended_handoff_id and any(node.get("id") == recommended_handoff_id for node in matched):
        return recommended_handoff_id
    if matched:
        return str(matched[-1].get("id") or "").strip()
    if expected_route_id or expected_chain_id:
        return ""
    return str(cards[-1].get("id") or "").strip() if cards else ""


def _agent_recommendation_node_id(
    workflow: dict[str, Any], episode_id: str, target: dict[str, Any], node_type: str,
) -> str:
    if not is_work_chain_recommendation_target(target) or target["episodeId"] != episode_id or target["nodeType"] != node_type:
        return ""
    for node in workflow.get("nodes") or []:
        if (
            node.get("id") == target["nodeId"] and node.get("type") == node_type
            and node.get("workChainId") == target["workChainId"]
            and (not target.get("routeId") or node.get("routeId") == target["routeId"])
        ):
            return node["id"]
    return ""


def _agent_current_flow_workflow_node_id(
    project_id: str,
    episode_id: str | None,
    state: dict[str, Any],
    node_type: str,
    *,
    active_target: dict[str, Any] | None = None,
    task_type: str = "",
) -> str:
    current_episode_id = str(episode_id or state.get("selectedEpisodeId") or "E01").strip() or "E01"
    target = active_target if isinstance(active_target, dict) else {}
    target_node_id = str(target.get("nodeId") or target.get("node_id") or "").strip()
    target_node_type = str(target.get("nodeType") or target.get("node_type") or "").strip()
    try:
        workflow = get_canvas_workflow_projection(project_id, current_episode_id)
    except Exception:
        if target.get("source") == "agent_recommendation":
            return ""
        return target_node_id if target_node_type == node_type else ""
    if target.get("source") == "agent_recommendation":
        return _agent_recommendation_node_id(workflow, current_episode_id, target, node_type)

    if target_node_id:
        candidate_ids = [target_node_id]
        if task_type:
            resolved_node_id = str(resolve_generation_task_node_id(workflow, task_type, target_node_id) or "").strip()
            if resolved_node_id and resolved_node_id not in candidate_ids:
                candidate_ids.insert(0, resolved_node_id)
        for candidate_id in candidate_ids:
            node = next(
                (
                    item
                    for item in workflow.get("nodes") or []
                    if isinstance(item, dict) and str(item.get("id") or "").strip() == candidate_id
                ),
                {},
            )
            if str(node.get("type") or "").strip() == node_type:
                return candidate_id

    route_identity = _agent_current_route_identity(state)
    expected_route_id = str(route_identity.get("routeId") or "").strip()
    expected_work_chain_id = str(route_identity.get("workChainId") or "").strip()
    if not expected_route_id and not expected_work_chain_id:
        production_status = state.get("productionStatus") if isinstance(state.get("productionStatus"), dict) else {}
        expected_route_id = str(production_status.get("currentRouteId") or "").strip()
        expected_work_chain_id = str(production_status.get("currentWorkChainId") or "").strip()
    route_ids_for_work_chain = _agent_route_ids_for_work_chain(workflow, expected_work_chain_id)
    fallback_node_id = ""
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("type") or "").strip() != node_type:
            continue
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        if not fallback_node_id:
            fallback_node_id = node_id
        if _agent_flow_node_matches_scope(
            node,
            expected_route_id,
            expected_work_chain_id,
            route_ids_for_work_chain,
        ):
            return node_id
    return fallback_node_id


def _agent_flow_step_instruction(message: str, fallback: str) -> str:
    if _agent_message_continues_flow(message):
        return fallback
    return str(message or "").strip() or fallback






def _agent_project_episode_rows_for_agent(
    project_id: str,
    state: dict[str, Any] | None = None,
    *,
    coverage: dict[str, Any] | None = None,
    limit: int | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_episode(value: Any) -> None:
        if not isinstance(value, dict):
            return
        episode_id = str(
            value.get("id")
            or value.get("episodeId")
            or value.get("episode_id")
            or ""
        ).strip()
        if not episode_id or episode_id in seen:
            return
        row = {"id": episode_id}
        title = str(
            value.get("title")
            or value.get("episodeTitle")
            or value.get("episode_title")
            or value.get("name")
            or ""
        ).strip()
        status = str(value.get("status") or "").strip()
        if title:
            row["title"] = title
        if status:
            row["status"] = status
        rows.append(row)
        seen.add(episode_id)

    state = state if isinstance(state, dict) else {}
    project = state.get("project") if isinstance(state.get("project"), dict) else {}
    for item in project.get("episodes") if isinstance(project.get("episodes"), list) else []:
        add_episode(item)
    meta = state.get("meta") if isinstance(state.get("meta"), dict) else {}
    for item in meta.get("episodes") if isinstance(meta.get("episodes"), list) else []:
        add_episode(item)
    coverage_data = coverage if isinstance(coverage, dict) else _agent_source_coverage_safe(project_id)
    for item in coverage_data.get("episodeRanges") if isinstance(coverage_data.get("episodeRanges"), list) else []:
        add_episode(item)
    if not rows:
        meta = _read_json(_project_meta_path(project_id), {})
        for item in meta.get("episodes") if isinstance(meta.get("episodes"), list) else []:
            add_episode(item)
    if isinstance(limit, int) and limit > 0 and len(rows) > limit:
        return rows[-limit:]
    return rows


def _agent_episode_sort_key_for_id(episode_id: str) -> tuple[int, int, str]:
    number = _agent_episode_number(episode_id)
    if number > 0:
        return (1, number, str(episode_id or ""))
    return (0, 0, str(episode_id or ""))


def _agent_latest_episode_id_for_agent(
    project_id: str,
    state: dict[str, Any] | None = None,
    *,
    session_policy: dict[str, Any] | None = None,
    episodes: list[dict[str, str]] | None = None,
) -> str:
    rows = episodes if isinstance(episodes, list) else _agent_project_episode_rows_for_agent(project_id, state)
    episode_ids = [
        str(item.get("id") or "").strip()
        for item in rows
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    policy = session_policy if isinstance(session_policy, dict) else {}
    policy_latest = str(policy.get("latestEpisodeId") or "").strip()
    if policy_latest and (not episode_ids or policy_latest in episode_ids):
        return policy_latest
    if episode_ids:
        return sorted(episode_ids, key=_agent_episode_sort_key_for_id)[-1]
    try:
        return latest_project_episode_id(project_id)
    except Exception:
        return ""


def _agent_episode_title_for_agent(
    project_id: str,
    state: dict[str, Any] | None,
    episode_id: str,
    *,
    coverage: dict[str, Any] | None = None,
) -> str:
    target_episode_id = str(episode_id or "").strip()
    if not target_episode_id:
        return ""
    for item in _agent_project_episode_rows_for_agent(project_id, state, coverage=coverage):
        if not isinstance(item, dict) or str(item.get("id") or "").strip() != target_episode_id:
            continue
        return str(item.get("title") or "").strip()
    return ""


def _agent_progress_string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item or "").strip() for item in value if str(item or "").strip()}


def _agent_current_route_state(state: dict[str, Any]) -> dict[str, Any]:
    production_status = (
        state.get("productionStatus")
        if isinstance(state.get("productionStatus"), dict)
        else {}
    )
    route_states = [
        item
        for item in production_status.get("routeStates") or []
        if isinstance(item, dict)
    ]
    def has_open_default_state(item: dict[str, Any]) -> bool:
        completed = _agent_progress_string_set(item.get("completedStates"))
        if "video.generated" in completed:
            return False
        return True

    current_route_id = str(production_status.get("currentRouteId") or "").strip()
    current_work_chain_id = str(production_status.get("currentWorkChainId") or "").strip()
    current_route_state: dict[str, Any] = {}
    for item in route_states:
        route_id = str(item.get("routeId") or "").strip()
        work_chain_id = str(item.get("workChainId") or "").strip()
        if (current_route_id and route_id == current_route_id) or (
            current_work_chain_id and work_chain_id == current_work_chain_id
        ):
            current_route_state = item
            break
    if current_route_state and has_open_default_state(current_route_state):
        return current_route_state
    for item in route_states:
        if has_open_default_state(item):
            return item
    return current_route_state


def _agent_current_route_identity(state: dict[str, Any]) -> dict[str, str]:
    route_state = _agent_current_route_state(state)
    return {
        "routeId": str(route_state.get("routeId") or "").strip(),
        "workChainId": str(route_state.get("workChainId") or "").strip(),
        "segmentId": str(route_state.get("segmentId") or "").strip(),
    }


def _agent_current_route_completed_states(state: dict[str, Any]) -> set[str]:
    production_status = (
        state.get("productionStatus")
        if isinstance(state.get("productionStatus"), dict)
        else {}
    )
    completed_states: set[str] = set()
    route_state = _agent_current_route_state(state)
    if route_state:
        completed_states = _agent_progress_string_set(route_state.get("completedStates"))
    return completed_states
