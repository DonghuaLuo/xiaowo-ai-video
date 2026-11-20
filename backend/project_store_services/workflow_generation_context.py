# -*- coding: utf-8 -*-
"""工作流领域实际实现。"""
from __future__ import annotations

from .canvas_ownership import source_work_chain_ids
from .canvas_store_queries import read_workflow_card_neighborhood_v4
from .canvas_store_records import _json_signature
from .reference_utils import asset_refs_has_value as _asset_refs_has_value
from .asset_reference_scope import _filter_asset_refs_to_active_project_assets
from .planning_contract import _segment_asset_refs
from .source_text_store import _compact_text
from .store_core import _now
from .storyboard_prompt_content import _compact_multiline_text
from .storyboard_prompt_content import _panel_value
from .storyboard_prompt_content import _storyboard_source_fact_text_from_data
from .workflow_asset_resolution import resolve_workflow_node_inputs
from .workflow_contract import _PROMPT_STORYBOARD_NODE_TYPES
from .workflow_contract import _STORYBOARD_REFERENCE_NODE_TYPES
from .workflow_contract import _VIDEO_RESULT_NODE_TYPES
from .workflow_contract import _WORKFLOW_VIDEO_TASK_NODE_TYPES
from .workflow_contract import _node_route_id
from .workflow_contract import _node_segment_id
from .workflow_contract import _node_work_chain_id
from .workflow_contract import _workflow_is_video_task_type
from .workflow_contract import _workflow_node
from .workflow_contract import _workflow_node_type
from .workflow_contract import _workflow_node_type_value
from .workflow_contract import _workflow_node_work_chain_id
from .workflow_input_resolution import _workflow_node_matches_work_chain
from .workflow_input_resolution import _workflow_nodes_by_types
from .workflow_input_resolution import resolve_generation_task_node_id
from .workflow_input_resolution import workflow_storyboard_image_director_node_id
from .workflow_input_resolution import workflow_video_task_work_chain_storyboard_node_ids
from .workflow_media_batch import _workflow_batch_edge_blockers
from .workflow_projection import _workflow_cards_mutation_write
from .workflow_visual_handoff import _workflow_prompt_storyboard_nodes_ordered
from typing import Any
import copy


def validate_workflow_node_inputs_ready(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
    *,
    workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    if not node_id:
        raise ValueError("缺少 nodeId")
    source_workflow = (
        workflow
        if isinstance(workflow, dict)
        else read_workflow_card_neighborhood_v4(project_id, episode_id, node_id, detail="full")
    )
    node = _workflow_node(source_workflow, node_id)
    if not node:
        raise FileNotFoundError("节点不存在")
    input_snapshot = resolve_workflow_node_inputs(
        project_id,
        episode_id,
        {"nodeId": node_id},
        workflow=source_workflow,
    )
    blockers = _workflow_batch_edge_blockers(project_id, episode_id, source_workflow, node, input_snapshot)
    if blockers:
        data = node.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            node["data"] = data
        data["status"] = "blocked"
        quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
        quality["inputPreflight"] = {
            "checkedAt": _now(),
            "blockingIssues": blockers,
            "inputSnapshot": {
                "inputLinks": copy.deepcopy(input_snapshot.get("inputLinks") or []),
                "referenceMediaIds": copy.deepcopy(input_snapshot.get("referenceMediaIds") or []),
                "needsRelink": copy.deepcopy(input_snapshot.get("needsRelink") or []),
            },
        }
        data["quality"] = quality
        _workflow_cards_mutation_write(
            project_id,
            episode_id,
            [copy.deepcopy(node)],
            op_type="card_patch",
            changed_resources=["canvas_node"],
        )
        raise ValueError("节点运行前检查未通过：" + "；".join(blockers[:5]))
    return {
        "success": True,
        "episodeId": episode_id,
        "nodeId": node_id,
        "inputSnapshot": input_snapshot,
        "blockers": [],
    }


def _merge_canvas_neighborhoods(*workflows: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "nodes": [],
        "edges": [],
        "routes": [],
        "workChains": [],
    }
    for key in ("nodes", "edges", "routes", "workChains"):
        seen: set[str] = set()
        rows: list[Any] = []
        for workflow in workflows:
            source_rows = workflow.get(key) if isinstance(workflow, dict) and isinstance(workflow.get(key), list) else []
            for row in source_rows:
                if not isinstance(row, dict):
                    continue
                row_id = str(row.get("id") or "").strip()
                dedupe_key = row_id or _json_signature(row)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                rows.append(copy.deepcopy(row))
        merged[key] = rows
    return merged


def _workflow_route_by_id_local(workflow: dict[str, Any], route_id: str) -> dict[str, Any] | None:
    route_text = str(route_id or "").strip()
    if not route_text:
        return None
    route_rows = workflow.get("routes") if isinstance(workflow.get("routes"), list) else []
    return next(
        (
            route
            for route in route_rows
            if isinstance(route, dict) and str(route.get("id") or "") == route_text
        ),
        None,
    )


def find_workflow_nodes(
    workflow: dict[str, Any],
    *,
    type: str | None = None,
    segment_id: str | None = None,
    route_id: str | None = None,
    work_chain_id: str | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    node_rows = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    for node in node_rows:
        if not isinstance(node, dict):
            continue
        if type and str(node.get("type") or "") != type:
            continue
        if segment_id and _node_segment_id(node) != segment_id:
            continue
        if route_id and _node_route_id(node) != route_id:
            continue
        if work_chain_id and not _workflow_node_matches_work_chain(workflow, node, work_chain_id):
            continue
        result.append(node)
    return result


_DIRECTOR_BOARD_NODE_TYPES = {"director.board"}


_VISUAL_HANDOFF_SOURCE_NODE_TYPES = {"storyboard.card"}


def _workflow_first_prompt_storyboard_node(workflow: dict[str, Any]) -> dict[str, Any] | None:
    rows = _workflow_prompt_storyboard_nodes_ordered(workflow)
    return rows[0] if rows else None


def _workflow_last_prompt_storyboard_node(workflow: dict[str, Any]) -> dict[str, Any] | None:
    rows = _workflow_prompt_storyboard_nodes_ordered(workflow)
    return rows[-1] if rows else None


def _workflow_next_prompt_storyboard_node(
    workflow: dict[str, Any],
    prompt_node: dict[str, Any],
) -> dict[str, Any] | None:
    prompt_node_id = str((prompt_node or {}).get("id") or "").strip()
    if not prompt_node_id:
        return None
    seen_current = False
    for node in _workflow_prompt_storyboard_nodes_ordered(workflow):
        node_id = str(node.get("id") or "").strip()
        if seen_current and node_id:
            return node
        if node_id == prompt_node_id:
            seen_current = True
    return None


def _workflow_node_is_visual_handoff_reference(node: dict[str, Any] | None) -> bool:
    if not isinstance(node, dict):
        return False
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(
        data.get("mediaPurpose")
        or data.get("media_purpose")
        or data.get("preferredTargetSlot")
        or data.get("preferred_target_slot")
        or data.get("assetKind")
        or data.get("asset_kind")
        or data.get("assetType")
        or data.get("asset_type")
        or ""
    ).strip() in {"visual_handoff", "visual_handoff_reference"}


def workflow_generation_related_node_ids(
    workflow: dict[str, Any],
    task_type: str | None,
    node_id: str | None = None,
) -> set[str]:
    normalized = str(task_type or "").strip()
    resolved_node_id = resolve_generation_task_node_id(workflow, normalized, node_id)
    resolved_node = _workflow_node(workflow, resolved_node_id) if resolved_node_id else None
    route_id = _node_route_id(resolved_node) if resolved_node else ""
    work_chain_id = _workflow_node_work_chain_id(workflow, resolved_node) if resolved_node else ""
    result: set[str] = {resolved_node_id} if resolved_node_id else set()

    if normalized == "storyboard_video" and resolved_node and _workflow_is_video_task_type(_workflow_node_type(resolved_node)):
        for storyboard_node_id in workflow_video_task_work_chain_storyboard_node_ids(workflow, resolved_node):
            result.add(storyboard_node_id)
            director_node_id = workflow_storyboard_image_director_node_id(workflow, storyboard_node_id)
            if director_node_id:
                result.add(director_node_id)
        for edge in workflow.get("edges", []) if isinstance(workflow.get("edges"), list) else []:
            if not isinstance(edge, dict) or str(edge.get("source") or "").strip() != resolved_node_id:
                continue
            target_id = str(edge.get("target") or "").strip()
            target_node = _workflow_node(workflow, target_id) if target_id else None
            if target_node and _workflow_node_type(target_node) in _VIDEO_RESULT_NODE_TYPES:
                result.add(target_id)
        return result

    if normalized in {"storyboard_plan", "workflow"}:
        node_types = _PROMPT_STORYBOARD_NODE_TYPES | _DIRECTOR_BOARD_NODE_TYPES
    elif normalized in {"storyboard_image", "storyboard_image_edit"}:
        node_types = _DIRECTOR_BOARD_NODE_TYPES | {"storyboard.card"} | _STORYBOARD_REFERENCE_NODE_TYPES
    elif normalized == "visual_handoff_image":
        node_types = _VISUAL_HANDOFF_SOURCE_NODE_TYPES | {"storyboard.image", "asset.image"}
    elif normalized == "storyboard_video":
        node_types = _WORKFLOW_VIDEO_TASK_NODE_TYPES | _VIDEO_RESULT_NODE_TYPES
    else:
        node_types = set()

    if route_id and node_types:
        for node in _workflow_nodes_by_types(workflow, node_types, route_id=route_id):
            current_id = str(node.get("id") or "").strip()
            if current_id:
                result.add(current_id)
    if work_chain_id and node_types:
        for node in _workflow_nodes_by_types(workflow, node_types, work_chain_id=work_chain_id):
            current_id = str(node.get("id") or "").strip()
            if current_id:
                result.add(current_id)
    return result


def _workflow_node_list_data(nodes: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in nodes:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node_rows: list[dict[str, Any]] = []
        nested_sources = [
            data,
            data.get("storyboardAnalysis") if isinstance(data.get("storyboardAnalysis"), dict) else {},
            data.get("directorTaskCard") if isinstance(data.get("directorTaskCard"), dict) else {},
        ]
        for source in nested_sources:
            if not isinstance(source, dict):
                continue
            for key in keys:
                value = source.get(key)
                if isinstance(value, list):
                    node_rows.extend(copy.deepcopy(item) for item in value if isinstance(item, dict))
                    break
            if node_rows:
                break
        if node_rows:
            rows.extend(node_rows)
            continue
        for source in nested_sources:
            if not isinstance(source, dict):
                continue
            nested = source.get("storyboardAnalysis") if isinstance(source.get("storyboardAnalysis"), dict) else {}
            for key in keys:
                value = nested.get(key) if isinstance(nested, dict) else None
                if isinstance(value, list):
                    node_rows.extend(copy.deepcopy(item) for item in value if isinstance(item, dict))
                    break
            if node_rows:
                break
        rows.extend(node_rows)
    return rows


def _workflow_panels(
    workflow: dict[str, Any],
    route_id: str | None = None,
    work_chain_id: str | None = None,
) -> list[dict[str, Any]]:
    prompt_nodes = find_workflow_nodes(
        workflow,
        type="prompt.storyboard",
        route_id=route_id,
        work_chain_id=work_chain_id,
    ) if route_id or work_chain_id else []
    if not prompt_nodes and not route_id and not work_chain_id:
        prompt_nodes = find_workflow_nodes(workflow, type="prompt.storyboard")
    rows = _workflow_node_list_data(prompt_nodes, "panels", "shots")
    if rows:
        return rows
    director_nodes = _workflow_nodes_by_types(
        workflow,
        _DIRECTOR_BOARD_NODE_TYPES,
        route_id=route_id,
        work_chain_id=work_chain_id,
    ) if route_id or work_chain_id else []
    if not director_nodes and not route_id and not work_chain_id:
        director_nodes = _workflow_nodes_by_types(workflow, _DIRECTOR_BOARD_NODE_TYPES)
    rows = _workflow_node_list_data(director_nodes, "panels", "shots")
    if rows:
        return rows
    return []


def _panel_with_active_asset_refs(
    project_id: str,
    panel: dict[str, Any],
    *,
    episode_id: str | None = None,
    context_provenance: dict[str, Any] | None = None,
    token_to_id: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    if not isinstance(panel, dict):
        return {}
    row = copy.deepcopy(panel)
    refs = _segment_asset_refs(row)
    if not _asset_refs_has_value(refs):
        return row
    active_refs = _filter_asset_refs_to_active_project_assets(
        project_id,
        refs,
        episode_id=episode_id,
        context_provenance=context_provenance,
        token_to_id=token_to_id,
    )
    row.pop("assetRefs", None)
    row.pop("asset_refs", None)
    if active_refs:
        row["assetRefs"] = active_refs
    return row


def _panel_camera_text(panel: dict[str, Any]) -> str:
    camera_value = panel.get("camera")
    if isinstance(camera_value, dict):
        return "，".join(
            str(camera_value.get(key) or "").strip()
            for key in ("shotType", "angle", "composition", "lighting", "cameraMotion")
            if str(camera_value.get(key) or "").strip()
        )
    return _panel_value(panel, "camera", "shot_type", "shotType")


def _storyboard_prompt_part_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        rows = []
        for item in value:
            text = _storyboard_prompt_part_text(item)
            if text and text not in rows:
                rows.append(text)
        return "；".join(rows)
    if isinstance(value, dict):
        ordered_keys = (
            "cinematicStoryText",
            "cinematic_story_text",
            "sourceFactText",
            "source_fact_text",
            "content",
            "text",
            "description",
            "summary",
            "dialogueText",
            "dialogue_text",
            "narrationText",
            "narration_text",
            "userNotes",
            "user_notes",
            "sceneBrief",
            "scene_brief",
            "visibleAction",
            "action",
            "prompt",
        )
        rows = []
        visited: set[str] = set()
        for key in ordered_keys:
            if key not in value:
                continue
            visited.add(key)
            text = _storyboard_prompt_part_text(value.get(key))
            if text and text not in rows:
                rows.append(text)
        for key, item in value.items():
            if key in visited or key in {"avoid", "negative", "negativePrompt", "negative_prompt"}:
                continue
            text = _storyboard_prompt_part_text(item)
            if text and text not in rows:
                rows.append(text)
        return "；".join(rows)
    return ""


def _storyboard_source_preview_text_from_data(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    task_card = data.get("storyboardTaskCard") if isinstance(data.get("storyboardTaskCard"), dict) else {}
    prompt = data.get("prompt") if isinstance(data.get("prompt"), dict) else {}
    value = (
        data.get("sourcePreview")
        or data.get("source_preview")
        or data.get("sourceExcerpt")
        or data.get("source_excerpt")
        or task_card.get("sourcePreview")
        or task_card.get("source_preview")
        or task_card.get("sourceExcerpt")
        or task_card.get("source_excerpt")
        or prompt.get("sourcePreview")
        or prompt.get("source_preview")
        or prompt.get("sourceExcerpt")
        or prompt.get("source_excerpt")
    )
    text = _storyboard_prompt_part_text(value).strip()
    return _compact_multiline_text(text, 1200) if text else ""


def _storyboard_node_context_title(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    task_card = data.get("storyboardTaskCard") if isinstance(data.get("storyboardTaskCard"), dict) else {}
    return _compact_text(
        data.get("title")
        or task_card.get("title")
        or data.get("label")
        or node.get("label")
        or node.get("id")
        or "片段剧本",
        80,
    )


def _workflow_adjacent_storyboard_context_text(workflow: dict[str, Any], current_node: dict[str, Any]) -> str:
    chain_ids = source_work_chain_ids(workflow)
    if _node_work_chain_id(current_node) not in chain_ids:
        return ""
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    storyboard_nodes = [
        node
        for node in nodes
        if isinstance(node, dict) and _workflow_node_type_value(node) == "prompt.storyboard" and _node_work_chain_id(node) in chain_ids
    ]
    current_id = str(current_node.get("id") or "").strip()
    current_index = next(
        (
            index
            for index, node in enumerate(storyboard_nodes)
            if str(node.get("id") or "").strip() == current_id
        ),
        -1,
    )
    if current_index < 0:
        return ""
    rows: list[str] = []
    for label, index in (("上一条工作链", current_index - 1), ("下一条工作链", current_index + 1)):
        if index < 0 or index >= len(storyboard_nodes):
            continue
        node = storyboard_nodes[index]
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        fact_text = (
            _storyboard_source_fact_text_from_data(data)
            or _storyboard_source_preview_text_from_data(data)
            or _compact_text(data.get("summary") or data.get("description") or "", 500)
        )
        if not fact_text:
            continue
        rows.append(f"{label}《{_storyboard_node_context_title(node)}》：{_compact_text(fact_text, 500)}")
    return _compact_text("\n".join(rows), 1200)
