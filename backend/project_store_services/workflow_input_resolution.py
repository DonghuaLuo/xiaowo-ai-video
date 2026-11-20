# -*- coding: utf-8 -*-
"""工作流素材输入解析：关联契约、素材快照、当前媒体和工作链继承。

只依赖画布存储、资产与工作流契约，不反向依赖 workflows 服务入口。
"""
from __future__ import annotations
from .workflow_reference_usage import reference_enabled, input_reference_enabled, inherited_reference_enabled, deduplicate_reference_rows

from .storyboard_templates import storyboard_image_prompt_spec
from .reference_read_context import ReferenceReadContext

from .work_chain_context import (
    work_chain_stage_node,
)
from .workflow_contract import (
    _DIRECTOR_BOARD_NODE_TYPES,
    _PROMPT_STORYBOARD_NODE_TYPES,
    _STORYBOARD_REFERENCE_NODE_TYPES,
    _VIDEO_RESULT_NODE_TYPES,
    _VISUAL_HANDOFF_SOURCE_NODE_TYPES,
    _WORKFLOW_VIDEO_MATERIAL_INPUT_SLOTS,
    _canonical_workflow_slot,
    _node_route_id,
    _workflow_is_default_work_chain_storyboard_result,
    _workflow_is_video_task_type,
    _workflow_media_reference_kind,
    _workflow_media_reference_path,
    _workflow_node,
    _workflow_node_can_supply_image_reference,
    _workflow_node_is_visual_handoff_asset_like,
    _workflow_node_media_reference_kind,
    _workflow_node_type,
    _workflow_node_work_chain_id,
)
from typing import (
    Any,
)
from utils.video_references import (
    VIDEO_REFERENCE_SLOT,
    reference_rows_in_transport_order,
)

import copy
import uuid
from utils.frame_references import (
    FRAME_IMAGE,
    FRAME_SLOT,
    frame_options,
)
from .assets import list_assets
from .canvas_store_queries import read_card_results
from .video_task_card_references import _ASSET_REF_COLLECTIONS, video_task_card_current_reference_snapshot
from .reference_utils import asset_refs_has_value as _asset_refs_has_value, dedupe_reference_tokens as _dedupe_reference_tokens
from .store_core import ASSET_LIFECYCLE_ACTIVE
from .video_reference_metadata import video_reference_input_identity
from .workflow_contract import (
    _VISUAL_HANDOFF_SLOT,
    _WORKFLOW_VIDEO_TASK_SCOPE_STANDALONE,
    _WORKFLOW_VIDEO_TASK_SCOPE_WORK_CHAIN,
    _append_unique_string,
    _apply_workflow_input_link_contract,
    _node_segment_id,
    _node_work_chain_id,
    _workflow_accepts_material_input,
    _workflow_asset_target_slot,
    _workflow_canvas_asset_node_identity_from_data,
    _workflow_chain_route_ids,
    _workflow_data_active_version_id,
    _workflow_edge_default_source_type,
    _workflow_edge_is_material_pair,
    _workflow_generation_source_node_id,
    _workflow_is_material_source_type,
    _workflow_material_allowed_slots,
    _workflow_material_source_handle,
    _workflow_material_target_handle,
    _workflow_normalize_asset_type,
    _workflow_validate_material_slot,
    workflow_node_is_default_work_chain_video_task,
    workflow_video_task_scope,
)


def _workflow_asset_collection_from_slot(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized == "character_reference":
        return "characters"
    if normalized == "creature_reference":
        return "creatures"
    if normalized == "scene_reference":
        return "scenes"
    if normalized == "prop_reference":
        return "props"
    return ""

def _workflow_canvas_asset_node_project_asset_identity(
    node: dict[str, Any],
) -> tuple[str, str]:
    node_type = str((node or {}).get("type") or "").strip()
    if node_type != "asset.image":
        return "", ""
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return _workflow_canvas_asset_node_identity_from_data(data)

def _workflow_route_ids_for_work_chain(workflow: dict[str, Any], work_chain_id: str) -> set[str]:
    if not work_chain_id:
        return set()
    result: set[str] = set()
    for route in workflow.get("routes", []):
        if not isinstance(route, dict):
            continue
        if str(route.get("workChainId") or route.get("work_chain_id") or "").strip() == work_chain_id:
            route_id = str(route.get("id") or "").strip()
            if route_id:
                result.add(route_id)
    for chain in workflow.get("workChains", []):
        if not isinstance(chain, dict) or str(chain.get("id") or "").strip() != work_chain_id:
            continue
        for route_id in _workflow_chain_route_ids(chain):
            route_text = str(route_id or "").strip()
            if route_text:
                result.add(route_text)
    return result

def _workflow_linkable_scope_node_ids(
    workflow: dict[str, Any],
    *,
    scope: str,
    route_id: str,
    work_chain_id: str,
) -> set[str]:
    if scope == "workChain":
        route_ids = _workflow_route_ids_for_work_chain(workflow, work_chain_id)
        if route_id:
            route_ids.add(route_id)
        result: set[str] = set()
        for item_route_id in route_ids:
            result.update(_workflow_linkable_route_node_ids(workflow, item_route_id))
        return result
    if scope == "route":
        return _workflow_linkable_route_node_ids(workflow, route_id)
    return set()

_WORKFLOW_MATERIAL_INPUT_SLOT_LABELS = {
    "custom_image": "自定义图片",
    FRAME_SLOT: "帧画面",
    "character_reference": "角色资产",
    "creature_reference": "生物资产",
    "scene_reference": "场景资产",
    "prop_reference": "道具资产",
    "style_reference": "风格参考",
    _VISUAL_HANDOFF_SLOT: "视觉交接",
    "visual_reference": "分镜图资产",
    "storyboard_image": "分镜图资产",
}

_WORKFLOW_MATERIAL_INPUT_SLOT_ORDER = [
    "custom_image",
    FRAME_SLOT,
    "character_reference",
    "creature_reference",
    "scene_reference",
    "prop_reference",
    _VISUAL_HANDOFF_SLOT,
    "storyboard_image",
]

def _workflow_node_input_contract(
    node: dict[str, Any] | None,
    grouped_by_slot: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    node_type = str((node or {}).get("type") or "").strip()
    node_data = node.get("data") if isinstance((node or {}).get("data"), dict) else {}
    video_task_scope = (
        workflow_video_task_scope({"nodes": [node] if node else []}, node)
        if _workflow_is_video_task_type(node_type)
        else ""
    )
    generation_config = (
        node_data.get("generationConfig")
        if isinstance(node_data.get("generationConfig"), dict)
        else {}
    )
    strategy = str(
        (node or {}).get("strategy")
        or node_data.get("strategy")
        or generation_config.get("strategy")
        or ""
    ).strip()
    allowed_slots = _workflow_material_allowed_slots(node)
    if _workflow_is_video_task_type(node_type) and not video_task_scope:
        allowed_slots = set()
    ordered_slots = [
        slot for slot in _WORKFLOW_MATERIAL_INPUT_SLOT_ORDER if slot in allowed_slots
    ] + sorted(slot for slot in allowed_slots if slot not in _WORKFLOW_MATERIAL_INPUT_SLOT_ORDER)
    grouped_by_slot = grouped_by_slot if isinstance(grouped_by_slot, dict) else {}
    accepted_slots = [
        {
            "id": slot,
            "label": _WORKFLOW_MATERIAL_INPUT_SLOT_LABELS.get(slot, slot),
            "count": len(grouped_by_slot.get(slot) or []),
        }
        for slot in ordered_slots
    ]
    if node_type == "prompt.storyboard":
        behavior = "script_creation"
        required_params = ["cinematicStoryText"]
        preferred_slots = []
        material_required = False
    elif node_type == "storyboard.card":
        behavior = "storyboard_card"
        required_params = ["directorPlanShots"]
        preferred_slots = ["character_reference", "creature_reference", "scene_reference", "prop_reference", _VISUAL_HANDOFF_SLOT, FRAME_SLOT, "custom_image"]
        material_required = False
    elif node_type == "director.board":
        behavior = "director_board"
        required_params = ["directorPlan"]
        preferred_slots = ["character_reference", "creature_reference", "scene_reference", "prop_reference", _VISUAL_HANDOFF_SLOT, FRAME_SLOT, "custom_image"]
        material_required = False
    elif _workflow_is_video_task_type(node_type):
        behavior = "video_generation"
        required_params = ["video_script"]
        if video_task_scope == _WORKFLOW_VIDEO_TASK_SCOPE_WORK_CHAIN:
            preferred_slots = ["storyboard_image"]
        elif video_task_scope == _WORKFLOW_VIDEO_TASK_SCOPE_STANDALONE:
            preferred_slots = [
                "custom_image",
                "character_reference",
                "creature_reference",
                "scene_reference",
                "prop_reference",
                "storyboard_image",
                _VISUAL_HANDOFF_SLOT,
            ]
        else:
            preferred_slots = []
        material_required = video_task_scope == _WORKFLOW_VIDEO_TASK_SCOPE_STANDALONE and strategy != "text_to_video_draft"
    else:
        behavior = "standalone"
        required_params = []
        preferred_slots = []
        material_required = False
    return {
        "behavior": behavior,
        "independent": True,
        "requiredParams": required_params,
        "acceptedSlots": accepted_slots,
        "presentSlots": [
            slot for slot in ordered_slots if grouped_by_slot.get(slot)
        ],
        "emptySlots": [
            slot for slot in ordered_slots if not grouped_by_slot.get(slot)
        ],
        "preferredSlots": preferred_slots,
        "materialRequired": material_required,
    }

def _upsert_workflow_material_edge(
    workflow: dict[str, Any],
    *,
    source_node: dict[str, Any],
    target_node: dict[str, Any],
    input_link: dict[str, Any],
    slot: str,
    action: str,
    route_id: str,
    segment_id: str,
    work_chain_id: str,
) -> None:
    source_node_id = str(source_node.get("id") or "").strip()
    target_node_id = str(target_node.get("id") or "").strip()
    input_link_id = str(input_link.get("id") or "").strip()
    source_node_type = str(source_node.get("type") or "").strip()
    target_node_type = str(target_node.get("type") or "").strip()
    _apply_workflow_input_link_contract(input_link, source_node)
    slot = _canonical_workflow_slot(input_link.get("targetSlot") or input_link.get("slot"), slot)
    _workflow_validate_material_slot(target_node, slot, source_node=source_node)
    locked_storyboard_video_input = (
        bool(input_link.get("locked"))
        or str(input_link.get("lockedReason") or "").strip() == "workflow_chain_storyboard_video_input"
    )
    target_handle = _workflow_material_target_handle(
        target_node,
        slot,
        input_link.get("targetHandle") or input_link.get("target_handle"),
        workflow=workflow,
        locked_storyboard_video_input=locked_storyboard_video_input,
    )
    source_handle = _workflow_material_source_handle(
        source_node,
        input_link.get("sourceHandle") or input_link.get("source_handle"),
    )
    if source_handle:
        input_link["sourceHandle"] = source_handle
    input_link["sourceNodeId"] = source_node_id
    input_link["sourceNodeType"] = source_node_type
    input_link["targetNodeId"] = target_node_id
    input_link["targetNodeType"] = target_node_type
    input_link["targetHandle"] = target_handle
    edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    existing_edge = next((edge for edge in edges if isinstance(edge, dict)
        and _workflow_material_edge_signature(edge) == (source_node_id, target_node_id, slot)
        and (edge.get("data") or {}).get("kind") == "material"), None)
    if existing_edge:
        input_link_id = str(existing_edge["data"].get("inputLinkId") or input_link_id)
        input_link["id"] = input_link_id
    kept_edges: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        is_material = str(data.get("kind") or "") == "material"
        same_link = input_link_id and str(data.get("inputLinkId") or "") == input_link_id
        replace_current_slot = action in {"replace_slot", "relink_slot"} or slot == _VISUAL_HANDOFF_SLOT
        same_slot = (
            replace_current_slot
            and str(edge.get("target") or "") == target_node_id
            and str(data.get("targetSlot") or data.get("slot") or "") == slot
        )
        if is_material and (same_link or same_slot):
            continue
        kept_edges.append(edge)
    kept_edges.append(
        {
            "id": f"material-{source_node_id}-{target_node_id}-{slot}-{input_link_id}",
            "source": source_node_id,
            "target": target_node_id,
            "sourceHandle": source_handle,
            "targetHandle": target_handle,
            "data": {
                "kind": "material",
                "role": slot,
                "inputLinkId": input_link_id,
                **(frame_options(input_link) if slot == FRAME_SLOT else {}),
                "sourceType": input_link.get("sourceType"),
                "targetHandle": target_handle,
                "sourceNodeType": source_node_type,
                "targetNodeType": target_node_type,
                "targetSlot": slot,
                **({"workChainId": work_chain_id} if work_chain_id else {}),
                **({"routeId": route_id} if route_id else {}),
                **({"segmentId": segment_id} if segment_id else {}),
            },
        }
    )
    workflow["edges"] = kept_edges

def _workflow_material_edge_for_input_link(
    workflow: dict[str, Any],
    input_link_id: str,
) -> dict[str, Any] | None:
    input_link_id = str(input_link_id or "").strip()
    if not input_link_id:
        return None
    edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        if (
            str(data.get("kind") or "") == "material"
            and str(data.get("inputLinkId") or "") == input_link_id
        ):
            return edge
    return None

def _input_link_matches(
    value: Any,
    *,
    slot: str,
    scope: str,
    target_node_id: str,
    route_id: str,
    work_chain_id: str = "",
) -> bool:
    if not isinstance(value, dict):
        return False
    link_slot = str(value.get("slot") or value.get("targetSlot") or value.get("target_slot") or "")
    if link_slot != slot:
        return False
    visibility_scope = str(value.get("visibilityScope") or value.get("visibility_scope") or "")
    if scope == "node":
        return bool(target_node_id) and str(value.get("targetNodeId") or value.get("target_node_id") or "") == target_node_id
    if scope == "route":
        return (
            bool(route_id)
            and str(value.get("routeId") or value.get("route_id") or "") == route_id
            and visibility_scope == scope
            and not value.get("targetNodeId")
            and not value.get("target_node_id")
        )
    if scope == "workChain":
        link_work_chain_id = str(value.get("workChainId") or value.get("work_chain_id") or "")
        link_route_id = str(value.get("routeId") or value.get("route_id") or "")
        return (
            visibility_scope == scope
            and not value.get("targetNodeId")
            and not value.get("target_node_id")
            and (
                (bool(work_chain_id) and link_work_chain_id == work_chain_id)
                or (not work_chain_id and bool(route_id) and link_route_id == route_id)
            )
        )
    return (
        visibility_scope == "global"
        and not value.get("targetNodeId")
        and not value.get("target_node_id")
        and not value.get("routeId")
        and not value.get("route_id")
    )

def _next_input_links(
    current_links: Any,
    input_link: dict[str, Any],
    *,
    action: str,
    slot: str,
    scope: str,
    target_node_id: str,
    route_id: str,
    work_chain_id: str = "",
) -> list[dict[str, Any]]:
    current_rows = current_links if isinstance(current_links, list) else []
    links = [copy.deepcopy(item) for item in current_rows if isinstance(item, dict)]
    if action == "append" and slot != _VISUAL_HANDOFF_SLOT:
        signature = _workflow_input_link_material_signature(input_link, target_node_id)
        if signature[0]:
            existing = next((item for item in links if _workflow_input_link_material_signature(item, target_node_id) == signature), None)
            if existing:
                # Moving between display ports updates one binding, not its identity.
                input_link["id"] = existing.get("id") or input_link.get("id")
                return [item for item in links if _workflow_input_link_material_signature(item, target_node_id) != signature] + [copy.deepcopy(input_link)]
        return [*links, copy.deepcopy(input_link)]
    return [
        item
        for item in links
        if not _input_link_matches(
            item,
            slot=slot,
            scope=scope,
            target_node_id=target_node_id,
            route_id=route_id,
            work_chain_id=work_chain_id,
        )
    ] + [copy.deepcopy(input_link)]

def _workflow_downstream_node_ids(workflow: dict[str, Any], node_id: str) -> set[str]:
    edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    visited = {node_id}
    result: set[str] = set()
    queue = [node_id]
    while queue:
        current = queue.pop(0)
        for edge in edges:
            if not isinstance(edge, dict) or str(edge.get("source") or "") != current:
                continue
            target = str(edge.get("target") or "").strip()
            if not target or target in visited:
                continue
            visited.add(target)
            result.add(target)
            queue.append(target)
    return result

def _workflow_linkable_route_node_ids(workflow: dict[str, Any], route_id: str) -> set[str]:
    if not route_id:
        return set()
    result: set[str] = set()
    node_rows = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    for node in node_rows:
        if not isinstance(node, dict) or _node_route_id(node) != route_id:
            continue
        if _workflow_accepts_material_input(node):
            node_id = str(node.get("id") or "").strip()
            if node_id:
                result.add(node_id)
    return result

def _workflow_input_scope(payload: dict[str, Any]) -> str:
    raw_scope = str(payload.get("scope") or payload.get("visibilityScope") or "").strip()
    if not raw_scope and (
        payload.get("targetNodeId")
        or payload.get("target_node_id")
        or payload.get("nodeId")
        or payload.get("node_id")
    ):
        return "node"
    scope = raw_scope or "global"
    return scope if scope in {"node", "route", "workChain", "global"} else "global"

def _workflow_input_action(payload: dict[str, Any]) -> str:
    action = str(payload.get("action") or payload.get("linkAction") or "append").strip() or "append"
    return action if action in {"append", "replace_slot", "relink_slot"} else "append"

def _workflow_input_affected_ids(
    workflow: dict[str, Any],
    *,
    scope: str,
    target_node: dict[str, Any] | None,
    route_id: str,
    work_chain_id: str,
    payload: dict[str, Any],
) -> set[str]:
    if scope == "node" and target_node:
        affected = _workflow_downstream_node_ids(workflow, str(target_node.get("id") or ""))
        target_node_id = str(target_node.get("id") or "").strip()
        if target_node_id:
            affected.add(target_node_id)
    elif scope in {"route", "workChain"}:
        target_work_chain_id = work_chain_id or str(payload.get("workChainId") or payload.get("work_chain_id") or "").strip()
        affected = _workflow_linkable_scope_node_ids(
            workflow,
            scope=scope,
            route_id=route_id,
            work_chain_id=target_work_chain_id,
        )
    else:
        affected = set()
    affected.update(
        str(item).strip()
        for item in (
            payload.get("affectedNodeIds")
            or payload.get("affected_node_ids")
            or []
        )
        if str(item).strip()
    )
    return affected

def _workflow_video_task_node_ids(
    workflow: dict[str, Any],
    node_ids: set[str] | list[str] | tuple[str, ...],
) -> set[str]:
    targets = {
        str(node_id or "").strip()
        for node_id in (node_ids if isinstance(node_ids, (set, list, tuple)) else [])
        if str(node_id or "").strip()
    }
    if not targets:
        return set()
    result: set[str] = set()
    for node in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        if node_id in targets and _workflow_is_video_task_type(str(node.get("type") or "")):
            result.add(node_id)
    return result

def _workflow_material_input_response_nodes(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_ids: set[str] | list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    normalized_node_ids = {
        str(node_id or "").strip()
        for node_id in node_ids
        if str(node_id or "").strip()
    }
    if not normalized_node_ids:
        return []
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    if not nodes:
        return []
    result: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        if node_id in normalized_node_ids:
            result.append(copy.deepcopy(node))
    return result

def _workflow_remove_edges_from_memory(workflow: dict[str, Any], edge_ids: set[str] | list[str] | tuple[str, ...]) -> None:
    normalized_edge_ids = {
        str(edge_id or "").strip()
        for edge_id in edge_ids
        if str(edge_id or "").strip()
    }
    if not normalized_edge_ids:
        return
    edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    workflow["edges"] = [
        copy.deepcopy(edge)
        for edge in edges
        if isinstance(edge, dict)
        and str(edge.get("id") or "").strip() not in normalized_edge_ids
    ]

def _link_slot(link: dict[str, Any]) -> str:
    return _canonical_workflow_slot(link.get("slot") or link.get("targetSlot") or link.get("target_slot"), "")

_WORKFLOW_INACTIVE_INPUT_LINK_STATUSES = {
    "deleted",
    "input_link_removed",
    "input_link_unlinked",
    "linked_item_deleted",
    "material_edge_removed",
    "removed",
    "unlinked",
}

def _workflow_input_link_is_active(link: dict[str, Any]) -> bool:
    status = str(link.get("status") or "").strip().lower()
    return status not in _WORKFLOW_INACTIVE_INPUT_LINK_STATUSES

def _workflow_input_link_direct_ids(link: dict[str, Any]) -> set[str]:
    if not isinstance(link, dict):
        return set()
    return {
        text
        for text in (
            str(link.get("id") or "").strip(),
            str(link.get("linkId") or link.get("link_id") or "").strip(),
            str(link.get("inputLinkId") or link.get("input_link_id") or "").strip(),
        )
        if text
    }

def _workflow_input_link_material_signature(
    link: dict[str, Any],
    default_target_node_id: str,
) -> tuple[str, str, str]:
    if not isinstance(link, dict):
        return ("", "", "")
    return (
        str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip(),
        str(link.get("targetNodeId") or link.get("target_node_id") or default_target_node_id or "").strip(),
        _link_slot(link),
    )

def _workflow_material_edge_signature(edge: dict[str, Any]) -> tuple[str, str, str]:
    if not isinstance(edge, dict):
        return ("", "", "")
    edge_data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    return (
        str(edge.get("source") or "").strip(),
        str(edge.get("target") or "").strip(),
        _canonical_workflow_slot(
            edge_data.get("targetSlot")
            or edge_data.get("target_slot")
            or edge_data.get("role"),
            "",
        ),
    )

def _workflow_material_edges_for_target(
    workflow: dict[str, Any],
    target_node_id: str,
) -> list[dict[str, Any]]:
    normalized_target_id = str(target_node_id or "").strip()
    if not normalized_target_id:
        return []
    rows: list[dict[str, Any]] = []
    for edge in workflow.get("edges", []) if isinstance(workflow.get("edges"), list) else []:
        if not isinstance(edge, dict):
            continue
        edge_data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        if str(edge_data.get("kind") or "").strip() != "material":
            continue
        if str(edge.get("target") or "").strip() != normalized_target_id:
            continue
        rows.append(edge)
    return rows

_WORKFLOW_INPUT_LINK_SOURCE_SNAPSHOT_KEYS = {
    "voiceStyle",
    "sourceNodeId",
    "source_node_id",
    "sourceNodeType",
    "source_node_type",
    "label",
    "displayName",
    "display_name",
    "assetId",
    "asset_id",
    "assetType",
    "asset_type",
    "assetName",
    "asset_name",
    "mediaId",
    "media_id",
    "mediaVersionId",
    "media_version_id",
    "sourceVersionId",
    "source_version_id",
    "activeMediaVersionId",
    "active_media_version_id",
    "activeVersionId",
    "active_version_id",
    "versionId",
    "version_id",
    "mediaType",
    "media_type",
    "mediaKind",
    "media_kind",
    "kind",
    "mimeType",
    "mime_type",
    "mediaPurpose",
    "media_purpose",
    "path",
    "file",
    "filePath",
    "file_path",
    "relativePath",
    "relative_path",
    "url",
    "preview",
    "previewUrl",
    "preview_url",
    "previewSrc",
    "preview_src",
    "thumbnail",
    "thumbnailUrl",
    "thumbnail_url",
    "dataUrl",
    "data_url",
    "media",
    "storage",
}

def _workflow_clear_input_link_source_snapshot(row: dict[str, Any]) -> None:
    for key in _WORKFLOW_INPUT_LINK_SOURCE_SNAPSHOT_KEYS:
        row.pop(key, None)

def _workflow_source_node_input_link_fields(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    source_node: dict[str, Any] | None,
    *,
    read_context: ReferenceReadContext | None = None,
) -> dict[str, Any]:
    if not isinstance(source_node, dict):
        return {}
    source_node_id = str(source_node.get("id") or "").strip()
    source_node_type = str(source_node.get("type") or "").strip()
    data = source_node.get("data") if isinstance(source_node.get("data"), dict) else {}
    active_version_id = _workflow_data_active_version_id(data)
    current_media = (
        workflow_current_media_reference(project_id, episode_id, workflow, source_node_id, read_context=read_context)
        if source_node_id
        else None
    )
    top_level_path = "" if active_version_id else _workflow_media_reference_path(data)
    media = (
        current_media
        if isinstance(current_media, dict)
        else {"path": top_level_path}
        if top_level_path
        else {}
    )
    storage = data.get("storage") if isinstance(data.get("storage"), dict) and media else {}
    if source_node_type == "asset.image":
        asset_type, asset_id = _workflow_canvas_asset_node_project_asset_identity(source_node)
        root_asset_project_id = str(data.get("rootAssetProjectId") or "").strip()
    else:
        asset_id = str(data.get("assetId") or data.get("asset_id") or "").strip()
        asset_type = str(data.get("assetType") or data.get("asset_type") or "").strip()
        root_asset_project_id = ""
    data_media_id = (
        data.get("mediaId")
        or data.get("media_id")
        or storage.get("mediaId")
        or storage.get("media_id")
        or ""
        if media
        else ""
    )
    media_id = str(
        (media or {}).get("id")
        or (media or {}).get("mediaId")
        or (media or {}).get("media_id")
        or data_media_id
    ).strip()
    data_media_version_id = (
        data.get("activeMediaVersionId")
        or data.get("active_media_version_id")
        or data.get("activeVersionId")
        or data.get("active_version_id")
        or data.get("mediaVersionId")
        or data.get("media_version_id")
        or data.get("sourceVersionId")
        or data.get("source_version_id")
        or ""
        if media
        else ""
    )
    media_version_id = str(
        (media or {}).get("versionId")
        or (media or {}).get("version_id")
        or (media or {}).get("mediaVersionId")
        or (media or {}).get("media_version_id")
        or data_media_version_id
    ).strip()
    path = (
        _workflow_media_reference_path(media)
        or (top_level_path if not active_version_id else "")
    )
    media_kind = _workflow_media_reference_kind(media, data if media else {}, storage) or _workflow_node_media_reference_kind(source_node)
    result = {
        "sourceNodeId": source_node_id,
        "sourceNodeType": source_node_type,
        "label": str(data.get("assetName") or data.get("title") or data.get("name") or source_node_id).strip(),
        "voiceStyle": str(data.get("voiceStyle") or "").strip(),
        **({"assetId": asset_id} if asset_id else {}),
        **({"assetType": asset_type} if asset_type else {}),
        **({"rootAssetId": asset_id} if source_node_type == "asset.image" and asset_id else {}),
        **({"rootAssetType": asset_type} if source_node_type == "asset.image" and asset_type else {}),
        **({"rootAssetProjectId": root_asset_project_id} if root_asset_project_id else {}),
        **({"assetName": str(data.get("assetName") or data.get("title") or "").strip()} if data.get("assetName") or data.get("title") else {}),
        **({"mediaId": media_id} if media_id else {}),
        **({"mediaVersionId": media_version_id} if media_version_id else {}),
        **({"sourceVersionId": media_version_id} if media_version_id else {}),
        **({"activeMediaVersionId": media_version_id} if media_version_id else {}),
        **({"activeVersionId": media_version_id} if media_version_id else {}),
        **({"mediaType": media_kind} if media_kind and (media_id or media or storage) else {}),
        **({"mediaPurpose": data.get("mediaPurpose") or data.get("media_purpose")} if data.get("mediaPurpose") or data.get("media_purpose") else {}),
        **({"path": path} if path else {}),
    }
    if isinstance(media, dict) and media:
        result["media"] = copy.deepcopy(media)
    return result

def workflow_reference_video_input_links(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    links: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Count current video media just as submission does, without changing associations."""
    nodes = {str(node.get("id") or ""): node for node in workflow.get("nodes", []) if isinstance(node, dict)}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in links if isinstance(links, list) else []:
        if not isinstance(link, dict) or not _workflow_input_link_is_active(link):
            continue
        if _canonical_workflow_slot(link.get("targetSlot") or link.get("slot"), "") != "reference_video":
            continue
        if not input_reference_enabled(workflow, link):
            continue
        source_id = str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip()
        row = copy.deepcopy(link)
        _workflow_clear_input_link_source_snapshot(row)
        row.update(_workflow_source_node_input_link_fields(project_id, episode_id, workflow, nodes.get(source_id)))
        row["sourceNodeId"] = source_id
        identity = video_reference_input_identity(row)
        # Invalid sources must remain visible to validation, even with stale cached media.
        if row.get("media") and identity:
            if identity in seen:
                continue
            seen.add(identity)
        rows.append(row)
    return rows


def _workflow_input_link_from_material_edge(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    target_node: dict[str, Any],
    edge: dict[str, Any],
    cached_link: dict[str, Any] | None,
    *,
    read_context: ReferenceReadContext | None = None,
) -> dict[str, Any]:
    edge_data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    source_node_id = str(edge.get("source") or "").strip()
    target_node_id = str(edge.get("target") or (target_node or {}).get("id") or "").strip()
    source_node = _workflow_node(workflow, source_node_id) if source_node_id else None
    source_node_type = str((source_node or {}).get("type") or edge_data.get("sourceNodeType") or "").strip()
    target_node_type = str((target_node or {}).get("type") or edge_data.get("targetNodeType") or "").strip()
    target_slot = _canonical_workflow_slot(
        edge_data.get("targetSlot")
        or edge_data.get("target_slot")
        or edge_data.get("role")
        or (cached_link or {}).get("targetSlot")
        or (cached_link or {}).get("slot"),
        "storyboard_image",
    )
    input_link_id = str(
        edge_data.get("inputLinkId")
        or edge_data.get("input_link_id")
        or (cached_link or {}).get("id")
        or (cached_link or {}).get("inputLinkId")
        or edge.get("id")
        or f"input-link-{uuid.uuid4().hex[:10]}"
    ).strip()
    row = copy.deepcopy(cached_link) if isinstance(cached_link, dict) else {}
    row.pop("inheritedFromNodeId", None)
    row.pop("inputOwnerNodeId", None)
    if target_slot == FRAME_SLOT:
        row.update({"assetType": FRAME_IMAGE, **frame_options(edge_data)})
    source_fields = _workflow_source_node_input_link_fields(
        project_id,
        episode_id,
        workflow,
        source_node,
        read_context=read_context,
    )
    if source_node:
        _workflow_clear_input_link_source_snapshot(row)
    for key, value in source_fields.items():
        if value not in (None, ""):
            row[key] = value
    if not source_node:
        _workflow_clear_input_link_source_snapshot(row)
    row.update(
        {
            "id": input_link_id,
            "inputLinkId": input_link_id,
            "sourceNodeId": source_node_id,
            "sourceNodeType": source_node_type,
            "sourceHandle": str(edge.get("sourceHandle") or row.get("sourceHandle") or row.get("source_handle") or "").strip(),
            "targetNodeId": target_node_id,
            "targetNodeType": target_node_type,
            "targetHandle": str(edge.get("targetHandle") or row.get("targetHandle") or row.get("target_handle") or "").strip(),
            "targetSlot": target_slot,
            "slot": target_slot,
            "role": target_slot,
            "visibilityScope": str(row.get("visibilityScope") or row.get("ownerScope") or "node"),
            "status": "linked" if source_node else "needs_relink",
            "sourceType": str(
                edge_data.get("sourceType")
                or row.get("sourceType")
                or row.get("source_type")
                or _workflow_edge_default_source_type(source_node_type)
            ).strip(),
            "workChainId": str(row.get("workChainId") or edge_data.get("workChainId") or _node_work_chain_id(target_node) or ""),
            "routeId": str(row.get("routeId") or edge_data.get("routeId") or _node_route_id(target_node) or ""),
            "segmentId": str(row.get("segmentId") or edge_data.get("segmentId") or _node_segment_id(target_node) or ""),
        }
    )
    return row

def _workflow_edge_backed_input_links_for_node(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
    links: list[dict[str, Any]],
    *,
    read_context: ReferenceReadContext | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(links, list):
        links = []
    if not _workflow_accepts_material_input(node):
        return [copy.deepcopy(link) for link in links if isinstance(link, dict) and _workflow_input_link_is_active(link)]
    target_node_id = str((node or {}).get("id") or "").strip()
    material_edges = _workflow_material_edges_for_target(workflow, target_node_id)
    if not material_edges:
        return []
    cached_by_direct_id: dict[str, dict[str, Any]] = {}
    cached_by_signature: dict[tuple[str, str, str], dict[str, Any]] = {}
    for link in links:
        if not isinstance(link, dict) or not _workflow_input_link_is_active(link):
            continue
        for direct_id in _workflow_input_link_direct_ids(link):
            cached_by_direct_id.setdefault(direct_id, link)
        signature = _workflow_input_link_material_signature(link, target_node_id)
        if all(signature):
            cached_by_signature.setdefault(signature, link)
    result: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str] | str] = set()
    for edge in material_edges:
        edge_data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        edge_link_id = str(edge_data.get("inputLinkId") or edge_data.get("input_link_id") or "").strip()
        signature = _workflow_material_edge_signature(edge)
        cache_link = (
            cached_by_direct_id.get(edge_link_id)
            if edge_link_id
            else None
        ) or cached_by_signature.get(signature)
        row = _workflow_input_link_from_material_edge(project_id, episode_id, workflow, node, edge, cache_link, read_context=read_context)
        row_key: tuple[str, str, str] | str = str(row.get("id") or "").strip() or signature
        if row_key in seen_keys:
            continue
        seen_keys.add(row_key)
        result.append(row)
    return result

def _link_priority(link: dict[str, Any]) -> int:
    if link.get("locked") or link.get("lockedByUser") or link.get("locked_by_user"):
        return 10
    provenance = link.get("provenance") if isinstance(link.get("provenance"), dict) else {}
    if str(provenance.get("source") or "") == "user":
        return 20
    if str(link.get("sourceType") or "") == "version":
        return 30
    return 40

def _link_reference_media_id(link: dict[str, Any]) -> str:
    source_type = str(link.get("sourceType") or link.get("source_type") or "").strip()
    for key in ("mediaId", "media_id", "mediaVersionId", "media_version_id"):
        text = str(link.get(key) or "").strip()
        if text:
            return text
    if source_type in {"media", "version"}:
        return str(link.get("sourceId") or link.get("source_id") or "").strip()
    return ""

def _workflow_link_asset_type(link: dict[str, Any]) -> str:
    asset_type = _workflow_normalize_asset_type(
        link.get("rootAssetType")
        or link.get("assetType")
    )
    if asset_type:
        return asset_type
    return _workflow_asset_collection_from_slot(_link_slot(link))

def _workflow_link_asset_identity_tokens(link: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for key in ("rootAssetId", "assetId"):
        text = str(link.get(key) or "").strip()
        if text:
            tokens.add(text.casefold())
    return tokens

def _workflow_link_targets_project_asset(link: dict[str, Any]) -> bool:
    source_type = str(link.get("sourceType") or link.get("source_type") or "").strip().casefold()
    if source_type in {"asset", "asset.image", "asset_reference", "asset-reference"}:
        return True
    source_node_type = str(link.get("sourceNodeType") or link.get("source_node_type") or "").strip().casefold()
    if source_node_type == "asset.image":
        return True
    return bool(_workflow_link_asset_type(link) in set(_ASSET_REF_COLLECTIONS) and _workflow_link_asset_identity_tokens(link))

def _workflow_active_asset_token_index(project_id: str, *, read_context: ReferenceReadContext | None = None) -> dict[str, set[str]]:
    tokens_by_type: dict[str, set[str]] = {asset_type: set() for asset_type in _ASSET_REF_COLLECTIONS}
    if not project_id:
        return tokens_by_type
    try:
        assets = (read_context or ReferenceReadContext(project_id)).assets
    except Exception:
        return tokens_by_type
    for asset_type in _ASSET_REF_COLLECTIONS:
        rows = assets.get(asset_type) if isinstance(assets, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            asset_id = str(row.get("id") or "").strip()
            if asset_id:
                tokens_by_type[asset_type].add(asset_id.casefold())
    return tokens_by_type

def _workflow_canvas_asset_token_index(workflow: dict[str, Any]) -> dict[str, set[str]]:
    tokens_by_type: dict[str, set[str]] = {asset_type: set() for asset_type in _ASSET_REF_COLLECTIONS}
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict) or str(node.get("type") or "").strip() != "asset.image":
            continue
        asset_type, asset_id = _workflow_canvas_asset_node_project_asset_identity(node)
        if asset_type not in tokens_by_type:
            continue
        if asset_id:
            tokens_by_type[asset_type].add(asset_id.casefold())
    return tokens_by_type

def _workflow_link_targets_active_project_asset(
    link: dict[str, Any],
    active_asset_tokens: dict[str, set[str]],
) -> bool:
    if not _workflow_link_targets_project_asset(link):
        return True
    asset_type = _workflow_link_asset_type(link)
    if asset_type not in set(_ASSET_REF_COLLECTIONS):
        return True
    link_tokens = _workflow_link_asset_identity_tokens(link)
    if not link_tokens:
        return False
    return bool(link_tokens & set(active_asset_tokens.get(asset_type) or set()))

def _link_asset_ref(link: dict[str, Any]) -> dict[str, Any] | None:
    asset_id = str(
        link.get("rootAssetId")
        or link.get("assetId")
        or ""
    ).strip()
    if not asset_id:
        return None
    return {
        "assetId": asset_id,
        "assetType": str(
            link.get("rootAssetType")
            or link.get("assetType")
            or ""
        ).strip(),
        "slot": _link_slot(link),
        "source": "inputLink",
        **({"assetVersionId": str(link.get("assetVersionId") or link.get("asset_version_id"))} if link.get("assetVersionId") or link.get("asset_version_id") else {}),
    }

def _workflow_media_dict_has_reference(media: Any) -> bool:
    if not isinstance(media, dict) or not media:
        return False
    for key in (
        "id",
        "mediaId",
        "path",
        "filePath",
        "file_path",
        "url",
        "preview",
        "previewUrl",
        "thumbnail",
        "thumbnailUrl",
        "dataUrl",
    ):
        if str(media.get(key) or "").strip():
            return True
    return False

def _workflow_node_data_current_media(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    for key in ("media", "storage"):
        media = data.get(key)
        if _workflow_media_dict_has_reference(media):
            return copy.deepcopy(media)
    return None

def _workflow_media_reference_version_id(media: Any) -> str:
    if not isinstance(media, dict):
        return ""
    return str(
        media.get("versionId")
        or media.get("version_id")
        or media.get("mediaVersionId")
        or media.get("media_version_id")
        or ""
    ).strip()

def _workflow_data_media_version_id(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    return str(
        data.get("mediaVersionId")
        or data.get("media_version_id")
        or data.get("activeMediaVersionId")
        or data.get("active_media_version_id")
        or data.get("sourceVersionId")
        or data.get("source_version_id")
        or ""
    ).strip()

def _workflow_node_data_current_media_for_version(
    data: dict[str, Any] | None,
    active_version_id: str,
) -> dict[str, Any] | None:
    if not isinstance(data, dict) or not active_version_id:
        return None
    data_media_version_id = _workflow_data_media_version_id(data)
    for key in ("media", "storage"):
        media = data.get(key)
        if not _workflow_media_dict_has_reference(media):
            continue
        media_version_id = _workflow_media_reference_version_id(media) or data_media_version_id
        if media_version_id != active_version_id:
            continue
        result = copy.deepcopy(media)
        result.setdefault("versionId", active_version_id)
        return result
    return None

def workflow_current_media_reference(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_id: str,
    *,
    read_context: ReferenceReadContext | None = None,
) -> dict[str, Any] | None:
    node_id = str(node_id or "").strip()
    if not node_id:
        return None
    source_node = _workflow_node(workflow, node_id)
    source_node_type = str((source_node or {}).get("type") or "").strip()
    source_data = source_node.get("data") if isinstance((source_node or {}).get("data"), dict) else {}
    source_plan_state = str(
        source_data.get("storyboardPlanState")
        or source_data.get("storyboard_plan_state")
        or ""
    ).strip()
    if source_plan_state == "pending_script":
        return None
    active_version_id = _workflow_data_active_version_id(source_data)
    if active_version_id:
        versions = read_context.card_results(episode_id, node_id) if read_context is not None else read_card_results(project_id, episode_id, node_id)
        selected = next(
            (
                item
                for item in versions
                if isinstance(item, dict) and str(item.get("id") or "") == active_version_id
            ),
            None,
        )
        if isinstance(selected, dict):
            selected_status = str(selected.get("status") or "").strip().lower()
            if selected_status in {"failed", "blocked", "cancelled", "canceled", "processing", "queued", "running", "waiting", "waiting_upstream"}:
                return None
            selected_media = selected.get("media")
            if _workflow_media_dict_has_reference(selected_media):
                media = copy.deepcopy(selected_media)
                media.setdefault("versionId", active_version_id)
                spec = storyboard_image_prompt_spec(_workflow_node_data_current_media(source_data), selected)
                if spec:
                    media["storyboardPromptSpec"] = spec
                return media
            current_media = _workflow_node_data_current_media_for_version(source_data, active_version_id)
            if current_media:
                return current_media
            return None
        current_media = _workflow_node_data_current_media_for_version(source_data, active_version_id)
        if current_media:
            return current_media
        return None
    if _workflow_is_material_source_type(source_node_type):
        return _workflow_node_data_current_media(source_data)
    return None

def _workflow_material_input_owner_node(
    workflow: dict[str, Any],
    node: dict[str, Any],
) -> dict[str, Any]:
    node_type = str((node or {}).get("type") or "").strip()
    if node_type != "storyboard.image":
        return node
    node_id = str((node or {}).get("id") or "").strip()
    if not node_id:
        return node

    card_id = _workflow_generation_source_node_id(workflow, node_id, "storyboard_image")
    card_node = _workflow_node(workflow, card_id) if card_id else None
    if isinstance(card_node, dict) and str(card_node.get("type") or "").strip() == "storyboard.card":
        return card_node
    return node

def _workflow_work_chain_input_owner_nodes(
    workflow: dict[str, Any],
    node: dict[str, Any],
) -> list[dict[str, Any]]:
    node_type = str((node or {}).get("type") or "").strip()
    if node_type not in {"director.board", "storyboard.card"} and not _workflow_is_video_task_type(node_type):
        return []
    if _workflow_is_video_task_type(node_type) and workflow_video_task_scope(workflow, node) != _WORKFLOW_VIDEO_TASK_SCOPE_WORK_CHAIN:
        return []

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(candidate: dict[str, Any] | None) -> None:
        if not isinstance(candidate, dict):
            return
        if str(candidate.get("type") or "").strip() not in {"director.board", "storyboard.card"}:
            return
        candidate_id = str(candidate.get("id") or "").strip()
        if not candidate_id or candidate_id in seen:
            return
        rows.append(candidate)
        seen.add(candidate_id)

    if _workflow_is_video_task_type(node_type):
        for storyboard_node_id in workflow_video_task_work_chain_storyboard_node_ids(workflow, node):
            card_id = workflow_storyboard_image_director_node_id(workflow, storyboard_node_id)
            add(_workflow_node(workflow, card_id) if card_id else None)
    if node_type != "director.board":
        add(work_chain_stage_node(workflow, node, "director.board"))
    return rows

def _workflow_branch_shot_asset_ids(
    node: dict[str, Any], owners: list[dict[str, Any]],
) -> dict[str, set[str]] | None:
    card = node if str(node.get("type") or "") == "storyboard.card" else next(
        (owner for owner in owners if str(owner.get("type") or "") == "storyboard.card"), None,
    )
    if not isinstance(card, dict):
        return None
    data = card.get("data") if isinstance(card.get("data"), dict) else {}
    shots = data.get("directorPlanShots")
    if not isinstance(shots, list) or not shots:
        return None
    result = {kind: set() for kind in ("characters", "creatures", "scenes", "props")}
    for shot in shots:
        assets = shot.get("assets") if isinstance(shot, dict) else None
        if not isinstance(assets, dict):
            return None
        for kind in result:
            ids = assets.get(kind)
            if not isinstance(ids, list):
                return None
            result[kind].update(str(asset_id).strip() for asset_id in ids if str(asset_id).strip())
    return result

def _workflow_inherited_work_chain_input_links(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
    *,
    read_context: ReferenceReadContext | None = None,
    blocked_links: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    node_id = str((node or {}).get("id") or "").strip()
    links: list[dict[str, Any]] = []
    owner_ids: list[str] = []
    owners = _workflow_work_chain_input_owner_nodes(workflow, node)
    shot_asset_ids = _workflow_branch_shot_asset_ids(node, owners)
    asset_kind_by_slot = {
        "character_reference": "characters",
        "creature_reference": "creatures",
        "scene_reference": "scenes",
        "prop_reference": "props",
    }
    for owner in owners:
        owner_id = str(owner.get("id") or "").strip()
        owner_data = owner.get("data") if isinstance(owner.get("data"), dict) else {}
        owner_links = owner_data.get("inputLinks") if isinstance(owner_data.get("inputLinks"), list) else []
        owner_links = _workflow_edge_backed_input_links_for_node(
            project_id,
            episode_id,
            workflow,
            owner,
            owner_links,
            read_context=read_context,
        )
        if owner_id and owner_id not in owner_ids:
            owner_ids.append(owner_id)
        for link in owner_links:
            if not isinstance(link, dict):
                continue
            slot = _link_slot(link)
            if slot not in {"character_reference", "creature_reference", "scene_reference", "prop_reference", "custom_image", _VISUAL_HANDOFF_SLOT, FRAME_SLOT}:
                continue
            if slot == _VISUAL_HANDOFF_SLOT:
                # A handoff board is a spatial reference for the next video,
                # never a native frame or a default reference for every cut.
                if not _workflow_is_video_task_type(str(node.get("type") or "")) or owner.get("type") != "storyboard.card":
                    continue
                from .video_boundary_plan import work_chain_video_boundary_plan
                try:
                    boundary_kind = work_chain_video_boundary_plan(workflow, node)["boundaryKind"]
                except ValueError:
                    boundary_kind = ""
                if boundary_kind != "spatial_cut":
                    continue
            if shot_asset_ids is not None and owner.get("type") == "director.board" and slot in asset_kind_by_slot:
                asset_id = str(link.get("rootAssetId") or link.get("assetId") or "").strip()
                if asset_id and asset_id not in shot_asset_ids[asset_kind_by_slot[slot]]:
                    continue
            source_node = _workflow_node(workflow, str(link.get("sourceNodeId") or ""))
            if _workflow_node_is_visual_handoff_asset_like(source_node) and slot != _VISUAL_HANDOFF_SLOT:
                continue
            row = copy.deepcopy(link)
            row["inheritedFromNodeId"] = owner_id
            row["inputOwnerNodeId"] = owner_id
            row["targetNodeId"] = node_id
            row["targetNodeType"] = str(node.get("type") or "")
            row.setdefault("visibilityScope", "node")
            if not inherited_reference_enabled(workflow, row):
                if blocked_links is not None:
                    blocked_links.append(row)
                continue
            links.append(row)
    return links, owner_ids

def _resolve_workflow_node_inputs_from_workflow(
    project_id: str,
    workflow: dict[str, Any],
    episode_id: str,
    node_id: str,
    *,
    read_context: ReferenceReadContext | None = None,
) -> dict[str, Any]:
    node = _workflow_node(workflow, node_id)
    if not node:
        raise FileNotFoundError("节点不存在")
    inherited_links: list[dict[str, Any]] = []
    blocked_links: list[dict[str, Any]] = []
    inherited_owner_ids: list[str] = []
    if str(node.get("type") or "") in {"director.board", "storyboard.card"} or _workflow_is_video_task_type(str(node.get("type") or "")):
        inherited_links, inherited_owner_ids = _workflow_inherited_work_chain_input_links(
            project_id,
            episode_id,
            workflow,
            node,
            read_context=read_context,
            blocked_links=blocked_links,
        )

    input_owner_node = _workflow_material_input_owner_node(workflow, node)
    input_owner_node_id = str(input_owner_node.get("id") or "").strip() if isinstance(input_owner_node, dict) else ""
    if input_owner_node_id and input_owner_node_id != node_id:
        owner_result = _resolve_workflow_node_inputs_from_workflow(
            project_id,
            workflow,
            episode_id,
            input_owner_node_id,
            read_context=read_context,
        )
        owner_result["nodeId"] = node_id
        owner_result["routeId"] = _node_route_id(node) or owner_result.get("routeId")
        owner_result["segmentId"] = _node_segment_id(node) or owner_result.get("segmentId")
        owner_result["inputOwnerNodeId"] = input_owner_node_id
        owner_result["inputOwnerNodeType"] = str(input_owner_node.get("type") or "")
        owner_result["inheritedFromNodeId"] = input_owner_node_id
        return owner_result
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    node_links = [
        copy.deepcopy(link)
        for link in data.get("inputLinks", [])
        if isinstance(link, dict)
    ] if isinstance(data.get("inputLinks"), list) else []
    node_links = _workflow_edge_backed_input_links_for_node(
        project_id,
        episode_id,
        workflow,
        node,
        node_links,
        read_context=read_context,
    )
    links = []
    seen_link_keys: set[Any] = set()
    for link in node_links + inherited_links:
        link_id = str(link.get("id") or link.get("linkId") or "").strip()
        link_key = (
            link_id,
            str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip(),
            str(link.get("sourceId") or link.get("source_id") or link.get("mediaId") or "").strip(),
            str(link.get("targetNodeId") or link.get("target_node_id") or node_id).strip(),
            _link_slot(link),
        )
        if _workflow_is_video_task_type(str(node.get("type") or "")):
            # Usage and validation belong to source cards. Only the transport
            # projection may deduplicate their shared media.
            link_key = str(link.get("sourceNodeId") or "").strip() or link_key
        if link_key in seen_link_keys:
            continue
        seen_link_keys.add(link_key)
        links.append(link)
    active_asset_tokens = _workflow_active_asset_token_index(project_id, read_context=read_context)
    canvas_asset_tokens = _workflow_canvas_asset_token_index(workflow)
    for asset_type, tokens in canvas_asset_tokens.items():
        active_asset_tokens.setdefault(asset_type, set()).update(tokens)
    resolved_links = []
    ignored_offline_asset_links = []
    needs_relink = []
    for link in links:
        if not _workflow_link_targets_active_project_asset(link, active_asset_tokens):
            ignored_offline_asset_links.append(copy.deepcopy(link))
            continue
        slot = _link_slot(link)
        if slot:
            link["slot"] = slot
            link["targetSlot"] = slot
        if not slot:
            link["status"] = "needs_relink"
            needs_relink.append(link)
        resolved_links.append(link)
    resolved_links.sort(key=_link_priority)
    display_links = resolved_links
    for link in display_links:
        link["enabled"] = input_reference_enabled(workflow, link)
    display_links = deduplicate_reference_rows(display_links)
    resolved_links = [link for link in display_links if link["enabled"]]
    enabled_assets = {(_workflow_link_asset_type(row), str(row.get("rootAssetId") or row.get("assetId") or ""))
                      for row in resolved_links}
    excluded_assets: dict[tuple[str, str], dict[str, str]] = {}
    for row in blocked_links + [row for row in display_links if not row["enabled"]]:
        kind = _workflow_link_asset_type(row)
        asset_id = str(row.get("rootAssetId") or row.get("assetId") or "")
        if asset_id and (kind, asset_id) not in enabled_assets and kind in {"characters", "creatures", "scenes", "props"}:
            excluded_assets[(kind, asset_id)] = {"assetType": kind, "assetId": asset_id,
                                                "name": str(row.get("assetName") or row.get("label") or asset_id)}
    needs_relink = [link for link in needs_relink if link["enabled"]]
    cached_reference_media_ids = _append_unique_string(data.get("referenceMediaIds"), "")
    reference_media_ids: list[str] = []
    cached_asset_refs = [
        copy.deepcopy(item)
        for item in data.get("assetRefs", [])
        if isinstance(item, dict)
    ] if isinstance(data.get("assetRefs"), list) else []
    asset_refs: list[dict[str, Any]] = []
    grouped_by_slot: dict[str, list[dict[str, Any]]] = {}
    reference_links: list[dict[str, Any]] = []
    for link in resolved_links:
        slot = _link_slot(link) or "unspecified"
        grouped_by_slot.setdefault(slot, []).append(link)
        if _link_reference_media_id(link):
            reference_links.append(link)
        asset_ref = _link_asset_ref(link)
        if asset_ref and not any(
            str(item.get("assetId") or "") == asset_ref["assetId"]
            and str(item.get("assetType") or "") == asset_ref["assetType"]
            and str(item.get("slot") or "") == asset_ref["slot"]
            for item in asset_refs
            if isinstance(item, dict)
        ):
            asset_refs.append(asset_ref)
    for link in reference_rows_in_transport_order(reference_links):
        reference_media_ids = _append_unique_string(
            reference_media_ids,
            _link_reference_media_id(link),
        )
    input_contract = _workflow_node_input_contract(node, grouped_by_slot)
    result = {
        "success": True,
        "episodeId": episode_id,
        "nodeId": node_id,
        "routeId": _node_route_id(node),
        "segmentId": _node_segment_id(node),
        "referenceDisplayRows": copy.deepcopy(display_links),
        "inputs": resolved_links,
        "inputLinks": resolved_links,
        "groupedBySlot": grouped_by_slot,
        "referenceMediaIds": reference_media_ids,
        "assetRefs": copy.deepcopy(asset_refs),
        "excludedAssets": list(excluded_assets.values()),
        "assetRefsResolvedByInputLinks": bool(links) or bool(inherited_owner_ids) or bool(data.get("referenceUsage")),
        "inputContract": input_contract,
        "priority": [
            "locked_input_links",
            "manual_input_links",
            "generated_input_links",
            "material_edge_input_links",
            "workflow_inherited_input_links",
            "defaults",
        ],
        "needsRelink": needs_relink,
    }
    if inherited_owner_ids:
        result["inputOwnerNodeIds"] = inherited_owner_ids
        result["inheritedFromNodeIds"] = inherited_owner_ids
    if ignored_offline_asset_links:
        result["ignoredOfflineAssetLinks"] = ignored_offline_asset_links
    ignored_reference_media_ids = [
        media_id
        for media_id in cached_reference_media_ids
        if media_id not in reference_media_ids
    ]
    if ignored_reference_media_ids:
        result["ignoredReferenceMediaIds"] = ignored_reference_media_ids
    if cached_asset_refs:
        def _asset_ref_key(item: dict[str, Any]) -> tuple[str, str, str]:
            return (
                str(item.get("assetId") or item.get("asset_id") or item.get("id") or "").strip(),
                str(item.get("assetType") or item.get("asset_type") or "").strip(),
                str(item.get("slot") or item.get("targetSlot") or "").strip(),
            )

        visible_asset_ref_keys = {
            _asset_ref_key(item)
            for item in asset_refs
            if isinstance(item, dict)
        }
        ignored_asset_refs = [
            item
            for item in cached_asset_refs
            if _asset_ref_key(item) not in visible_asset_ref_keys
        ]
        if ignored_asset_refs:
            result["ignoredAssetRefs"] = ignored_asset_refs
    return result

def _populate_workflow_video_reference_views(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_ids: set[str],
    *,
    read_context: ReferenceReadContext | None = None,
) -> set[str]:
    if not node_ids:
        return set()
    synced: set[str] = set()
    for node in (workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        if not node_id or node_id not in node_ids:
            continue
        if not _workflow_is_video_task_type(str(node.get("type") or "")):
            continue
        data = node.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            node["data"] = data
        input_snapshot = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, node_id, read_context=read_context)
        snapshot = video_task_card_current_reference_snapshot(
            project_id,
            episode_id,
            workflow,
            node_id,
            input_snapshot=input_snapshot,
            read_context=read_context,
        )
        if not isinstance(snapshot, dict):
            continue
        next_fields = {
            "inputLinks": copy.deepcopy(input_snapshot["inputLinks"]),
            "referenceDisplayRows": copy.deepcopy(snapshot["referenceDisplayRows"]),
            "referenceThumbnails": copy.deepcopy(snapshot.get("referenceThumbnails") or []),
            "assetThumbnails": copy.deepcopy(snapshot.get("assetThumbnails") or []),
            "referenceVideoThumbnails": copy.deepcopy(snapshot.get("referenceVideoThumbnails") or []),
            "referenceManifest": copy.deepcopy(snapshot.get("referenceManifest") or []),
            "referenceMediaIds": copy.deepcopy(snapshot.get("referenceMediaIds") or []),
            "assetReferenceMediaIds": copy.deepcopy(snapshot.get("assetReferenceMediaIds") or []),
            "assetRefs": copy.deepcopy(snapshot.get("assetRefs") or {}),
            "assetRefsResolvedByInputLinks": bool(snapshot.get("assetRefsResolvedByInputLinks")),
        }
        changed = False
        for key, value in next_fields.items():
            if data.get(key) != value:
                data[key] = value
                changed = True
        if changed:
            synced.add(node_id)
    return synced

def workflow_storyboard_image_director_node_id(
    workflow: dict[str, Any],
    storyboard_node_id: str | None,
) -> str:
    node_id = str(storyboard_node_id or "").strip()
    if not node_id:
        return ""
    node = _workflow_node(workflow, node_id)
    if _workflow_node_type(node or {}) != "storyboard.image":
        return ""
    return _workflow_generation_source_node_id(workflow, node_id, "storyboard_image")

def workflow_video_task_work_chain_storyboard_node_ids(
    workflow: dict[str, Any],
    node_or_id: dict[str, Any] | str | None,
) -> list[str]:
    if isinstance(node_or_id, dict):
        node = node_or_id
    else:
        node_id = str(node_or_id or "").strip()
        node = _workflow_node(workflow, node_id) if node_id else None
    if not workflow_node_is_default_work_chain_video_task(workflow, node):
        return []
    work_chain_id = _workflow_node_work_chain_id(workflow, node)
    route_id = _node_route_id(node)
    node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
    shot_group_id = str(node_data.get("shotGroupId") or "").strip()
    result: list[str] = []
    for candidate in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
        if not _workflow_is_default_work_chain_storyboard_result(workflow, candidate):
            continue
        if _workflow_node_work_chain_id(workflow, candidate) != work_chain_id:
            continue
        candidate_route_id = _node_route_id(candidate)
        if route_id and candidate_route_id and candidate_route_id != route_id:
            continue
        if shot_group_id:
            candidate_data = candidate.get("data") if isinstance(candidate.get("data"), dict) else {}
            if str(candidate_data.get("shotGroupId") or "").strip() != shot_group_id:
                continue
        candidate_id = str(candidate.get("id") or "").strip()
        if candidate_id and candidate_id not in result:
            result.append(candidate_id)
    return result


_WORKFLOW_ASSET_REF_COLLECTION_KEYS = {
    "characters": ("characters", "characterRefs", "character_refs", "roles"),
    "creatures": ("creatures", "creatureRefs", "creature_refs", "monsters", "beasts"),
    "scenes": ("scenes", "sceneRefs", "scene_refs", "locations"),
    "props": ("props", "propRefs", "prop_refs"),
}


def _workflow_asset_collection_from_type(value: Any) -> str:
    return _workflow_asset_collection_from_slot(_workflow_asset_target_slot(value, ""))


def _workflow_asset_ref_tokens_local(value: Any) -> list[str]:
    tokens: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        for item in value:
            tokens.extend(_workflow_asset_ref_tokens_local(item))
        return _dedupe_reference_tokens(tokens)
    if isinstance(value, dict):
        link_like = any(
            key in value
            for key in (
                "inputLinkId",
                "input_link_id",
                "sourceNodeId",
                "source_node_id",
                "targetNodeId",
                "target_node_id",
                "targetSlot",
                "target_slot",
                "slot",
                "sourceType",
                "source_type",
            )
        )
        token_keys = ["rootAssetId", "assetId"]
        if not link_like:
            token_keys.append("id")
        for key in token_keys:
            text = str(value.get(key) or "").strip()
            if text:
                tokens.append(text)
        return _dedupe_reference_tokens(tokens)
    return []


def _workflow_asset_ref_collection_from_row(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return (
        _workflow_asset_collection_from_type(
            row.get("rootAssetType")
            or row.get("assetType")
        )
        or _workflow_asset_collection_from_slot(
            row.get("targetSlot")
            or row.get("target_slot")
            or row.get("slot")
            or row.get("sourceSlot")
            or row.get("source_slot")
        )
    )


def _workflow_asset_ref_removal_targets(links: list[dict[str, Any]]) -> dict[str, set[str]]:
    targets: dict[str, set[str]] = {key: set() for key in ("characters", "creatures", "scenes", "props")}
    for link in links:
        if not isinstance(link, dict):
            continue
        source_type = str(link.get("sourceType") or link.get("source_type") or "asset").strip().casefold()
        if source_type and source_type not in {"asset", "asset.image", "asset_reference", "asset-reference"}:
            continue
        asset_type = _workflow_asset_ref_collection_from_row(link)
        if asset_type not in targets:
            continue
        for token in _workflow_asset_ref_tokens_local(link):
            token_key = token.casefold()
            if not token_key:
                continue
            targets[asset_type].add(token_key)
    return {key: value for key, value in targets.items() if value}


def _workflow_asset_ref_value_matches(value: Any, tokens: set[str]) -> bool:
    return any(token.casefold() in tokens for token in _workflow_asset_ref_tokens_local(value))


def _workflow_remove_asset_ref_value(value: Any, tokens: set[str]) -> tuple[Any, bool]:
    if isinstance(value, list):
        kept: list[Any] = []
        changed = False
        for item in value:
            if _workflow_asset_ref_value_matches(item, tokens):
                changed = True
                continue
            kept.append(item)
        return kept, changed
    if _workflow_asset_ref_value_matches(value, tokens):
        return [], True
    return value, False


def _workflow_remove_asset_refs_from_value(value: Any, targets: dict[str, set[str]]) -> tuple[Any, bool]:
    if not targets:
        return value, False
    if isinstance(value, dict):
        updated = copy.deepcopy(value)
        changed = False
        for asset_type, keys in _WORKFLOW_ASSET_REF_COLLECTION_KEYS.items():
            tokens = targets.get(asset_type)
            if not tokens:
                continue
            for key in keys:
                if key not in updated:
                    continue
                next_value, removed = _workflow_remove_asset_ref_value(updated.get(key), tokens)
                if not removed:
                    continue
                changed = True
                if _asset_refs_has_value(next_value):
                    updated[key] = next_value
                else:
                    updated.pop(key, None)
        return (updated if _asset_refs_has_value(updated) else {}, changed)
    if isinstance(value, list):
        kept: list[Any] = []
        changed = False
        for item in value:
            collection = _workflow_asset_ref_collection_from_row(item)
            tokens = targets.get(collection)
            if tokens and _workflow_asset_ref_value_matches(item, tokens):
                changed = True
                continue
            kept.append(item)
        return kept, changed
    return value, False


def _workflow_remove_asset_ref_rows(rows: Any, targets: dict[str, set[str]]) -> tuple[list[Any], bool]:
    if not isinstance(rows, list) or not targets:
        return (rows if isinstance(rows, list) else [], False)
    kept: list[Any] = []
    changed = False
    for row in rows:
        collection = _workflow_asset_ref_collection_from_row(row)
        tokens = targets.get(collection)
        if tokens and _workflow_asset_ref_value_matches(row, tokens):
            changed = True
            continue
        kept.append(row)
    return kept, changed


def _workflow_remove_unlinked_asset_refs_from_node_data(project_id: str, data: dict[str, Any], removed_links: list[dict[str, Any]]) -> bool:
    if not isinstance(data, dict):
        return False
    targets = _workflow_asset_ref_removal_targets(removed_links)
    if not targets:
        return False
    changed = False
    for key in ("assetRefs", "asset_refs"):
        if key not in data:
            continue
        next_refs, removed = _workflow_remove_asset_refs_from_value(data.get(key), targets)
        if removed:
            data[key] = next_refs if _asset_refs_has_value(next_refs) else {}
            changed = True
    for key in ("assetThumbnails", "asset_thumbnails"):
        if key not in data:
            continue
        next_rows, removed = _workflow_remove_asset_ref_rows(data.get(key), targets)
        if removed:
            data[key] = next_rows
            changed = True
    for card_key in (
        "directorTaskCard",
        "director_task_card",
        "storyboardTaskCard",
        "storyboard_task_card",
        "videoTaskCard",
        "video_task_card",
    ):
        card = data.get(card_key)
        if not isinstance(card, dict):
            continue
        if _workflow_remove_unlinked_asset_refs_from_node_data(project_id, card, removed_links):
            changed = True
    current_refs = data.get("assetRefs") if "assetRefs" in data else data.get("asset_refs")
    if changed and not _asset_refs_has_value(current_refs):
        data["assetRefsResolvedByInputLinks"] = False
    return changed


def _workflow_shot_plan_row_matches_segment(row: dict[str, Any], segment_id: str) -> bool:
    if not segment_id:
        return False
    return segment_id in {
        str(row.get("id") or "").strip(),
        str(row.get("segmentId") or row.get("segment_id") or "").strip(),
    }


def _workflow_remove_unlinked_asset_refs_from_plan_rows(
    project_id: str,
    container: dict[str, Any],
    *,
    segment_id: str,
    removed_links: list[dict[str, Any]],
) -> bool:
    if not isinstance(container, dict) or not segment_id:
        return False
    targets = _workflow_asset_ref_removal_targets(removed_links)
    if not targets:
        return False
    changed = False
    for collection_name in ("segments", "shots", "panels"):
        rows = container.get(collection_name)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not _workflow_shot_plan_row_matches_segment(row, segment_id):
                continue
            for key in ("assetRefs", "asset_refs"):
                if key not in row:
                    continue
                next_refs, removed = _workflow_remove_asset_refs_from_value(row.get(key), targets)
                if removed:
                    row[key] = next_refs if _asset_refs_has_value(next_refs) else {}
                    changed = True
            for card_key in ("directorTaskCard", "director_task_card", "storyboardTaskCard", "storyboard_task_card"):
                task_card = row.get(card_key) if isinstance(row.get(card_key), dict) else {}
                if task_card and _workflow_remove_unlinked_asset_refs_from_node_data(project_id, task_card, removed_links):
                    changed = True
    return changed


def _workflow_remove_unlinked_asset_refs_from_workflow(
    project_id: str,
    workflow: dict[str, Any],
    *,
    segment_id: str,
    removed_links: list[dict[str, Any]],
) -> bool:
    if not isinstance(workflow, dict) or not segment_id:
        return False
    changed = _workflow_remove_unlinked_asset_refs_from_plan_rows(
        project_id,
        workflow,
        segment_id=segment_id,
        removed_links=removed_links,
    )
    for node in (workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []):
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if not isinstance(data, dict):
            continue
        if _node_segment_id(node) == segment_id and _workflow_remove_unlinked_asset_refs_from_node_data(project_id, data, removed_links):
            changed = True
        if _workflow_remove_unlinked_asset_refs_from_plan_rows(
            project_id,
            data,
            segment_id=segment_id,
            removed_links=removed_links,
        ):
            changed = True
    return changed


def _workflow_active_card_version(
    project_id: str,
    episode_id: str,
    node_id: str,
    node: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node_data = node.get("data") if isinstance((node or {}).get("data"), dict) else {}
    active_id = _workflow_data_active_version_id(node_data)
    versions = read_card_results(project_id, episode_id, node_id)
    if active_id:
        for item in versions:
            if isinstance(item, dict) and str(item.get("id") or "").strip() == active_id:
                return copy.deepcopy(item)
    for item in reversed(versions):
        if not isinstance(item, dict):
            continue
        if item.get("media") and str(item.get("status") or "").strip() not in {"failed", "blocked", "cancelled", "canceled", "processing"}:
            return copy.deepcopy(item)
    return {}


def _workflow_storyboard_reference_ids_from_material_edges(
    workflow: dict[str, Any],
    node: dict[str, Any],
) -> list[str]:
    target_id = str(node.get("id") or "").strip()
    if not target_id:
        return []
    result: list[str] = []
    edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    for edge in edges:
        if not isinstance(edge, dict) or str(edge.get("target") or "").strip() != target_id:
            continue
        source_id = str(edge.get("source") or "").strip()
        if not source_id or source_id in result:
            continue
        source_node = _workflow_node(workflow, source_id)
        if not _workflow_node_can_supply_image_reference(source_node):
            continue
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        source_type = str(data.get("sourceNodeType") or _workflow_node_type(source_node) or "").strip()
        target_type = str(data.get("targetNodeType") or _workflow_node_type(node) or "").strip()
        edge_kind = str(data.get("kind") or "").strip()
        if edge_kind and edge_kind != "material":
            continue
        if not _workflow_edge_is_material_pair(source_type, target_type):
            continue
        slot = _canonical_workflow_slot(
            data.get("targetSlot") or data.get("slot") or data.get("role"),
            "storyboard_image",
        )
        if slot == "storyboard_image":
            result.append(source_id)
    return result


def _workflow_explicit_storyboard_reference_node_ids(
    workflow: dict[str, Any],
    node: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(node, dict):
        return []
    result: list[str] = []

    def extend(values: list[str]) -> None:
        for value in values:
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)

    if _workflow_node_type(node) == "storyboard.image":
        node_id = str(node.get("id") or "").strip()
        if node_id:
            result.append(node_id)
    extend(_workflow_storyboard_reference_ids_from_material_edges(workflow, node))
    return result


def workflow_current_media_version_has_media(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_id: str,
) -> bool:
    return workflow_current_media_reference(project_id, episode_id, workflow, node_id) is not None


def workflow_storyboard_reference_node_ids(
    workflow: dict[str, Any],
    *,
    node_id: str | None = None,
    route_id: str | None = None,
    work_chain_id: str | None = None,
) -> list[str]:
    requested_id = str(node_id or "").strip()
    requested_node = _workflow_node(workflow, requested_id) if requested_id else None
    requested_type = _workflow_node_type(requested_node) if requested_node else ""
    if not requested_node:
        return []
    result: list[str] = []
    seen: set[str] = set()

    def append_node_id(value: Any) -> None:
        current_id = str(value or "").strip()
        if current_id and current_id not in seen and reference_enabled(requested_node, current_id):
            seen.add(current_id)
            result.append(current_id)

    for reference_id in _workflow_explicit_storyboard_reference_node_ids(
        workflow,
        requested_node,
    ):
        append_node_id(reference_id)

    return result


_ASSET_MEDIA_BINDING_FIELDS = (
    "path", "file", "filePath", "file_path", "relativePath", "relative_path", "url", "preview",
)


def _workflow_media_record_has_image(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(str(value.get(key) or "").strip() for key in _ASSET_MEDIA_BINDING_FIELDS)


def _workflow_asset_link_has_image_binding(link: dict[str, Any]) -> bool:
    if not isinstance(link, dict):
        return False
    if any(str(link.get(key) or "").strip() for key in _ASSET_MEDIA_BINDING_FIELDS):
        return True
    return _workflow_media_record_has_image(link.get("media")) or _workflow_media_record_has_image(link.get("storage"))


def _workflow_asset_node_has_image_binding(node: dict[str, Any]) -> bool:
    if not isinstance(node, dict):
        return False
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    if _workflow_asset_link_has_image_binding(data):
        return True
    return _workflow_media_record_has_image(data.get("media")) or _workflow_media_record_has_image(data.get("storage"))


def _workflow_input_link_has_media_reference(link: dict[str, Any]) -> bool:
    if not isinstance(link, dict):
        return False
    if any(
        str(link.get(key) or "").strip()
        for key in (
            "mediaId",
            "media_id",
            "mediaVersionId",
            "media_version_id",
            "sourceVersionId",
            "source_version_id",
            "activeMediaVersionId",
            "active_media_version_id",
            "activeVersionId",
            "active_version_id",
            "versionId",
            "version_id",
            "path",
            "file",
            "filePath",
            "file_path",
            "relativePath",
            "relative_path",
            "url",
            "preview",
            "previewUrl",
            "preview_url",
            "previewSrc",
            "preview_src",
            "thumbnail",
            "thumbnailUrl",
            "thumbnail_url",
            "dataUrl",
            "data_url",
        )
    ):
        return True
    media = link.get("media") if isinstance(link.get("media"), dict) else {}
    storage = link.get("storage") if isinstance(link.get("storage"), dict) else {}
    for record in (media, storage):
        if any(
            str(record.get(key) or "").strip()
            for key in (
                "id",
                "mediaId",
                "media_id",
                "mediaVersionId",
                "media_version_id",
                "sourceVersionId",
                "source_version_id",
            )
        ):
            return True
    return bool(_workflow_media_reference_path(media, storage))


def _workflow_input_link_is_image_reference(link: dict[str, Any]) -> bool:
    if not isinstance(link, dict):
        return False
    slot = _canonical_workflow_slot(link.get("targetSlot") or link.get("slot"))
    if slot and slot not in _WORKFLOW_VIDEO_MATERIAL_INPUT_SLOTS:
        return False
    source_node_type = str(link.get("sourceNodeType") or link.get("source_node_type") or "").strip()
    if source_node_type == "video.result" or _workflow_is_video_task_type(source_node_type):
        return False
    media = link.get("media") if isinstance(link.get("media"), dict) else {}
    storage = link.get("storage") if isinstance(link.get("storage"), dict) else {}
    media_kind = _workflow_media_reference_kind(link, media, storage)
    if source_node_type in {"asset.image", "storyboard.image"}:
        if media_kind == "video":
            return False
        if media_kind == "image":
            return True
        return _workflow_input_link_has_media_reference(link)
    return media_kind == "image"


def _workflow_video_reference_link_ready(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    link: dict[str, Any],
    *,
    allowed_slots: set[str] | None = None,
) -> bool:
    slot = _canonical_workflow_slot(link.get("targetSlot") or link.get("slot"))
    if allowed_slots is not None and slot not in allowed_slots:
        return False
    if allowed_slots is None and slot not in _WORKFLOW_VIDEO_MATERIAL_INPUT_SLOTS:
        return False
    source_node_id = str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip()
    source_node = _workflow_node(workflow, source_node_id) if source_node_id else None
    if slot == VIDEO_REFERENCE_SLOT:
        if source_node:
            source_type = str(source_node.get("type") or "").strip()
            if source_type == "media.external" and _workflow_node_media_reference_kind(source_node) != "video":
                return False
            if source_type not in {"video.result", "media.external"}:
                return False
            current_media = workflow_current_media_reference(
                project_id,
                episode_id,
                workflow,
                source_node_id,
            )
            return bool(
                current_media
                and _workflow_media_reference_kind(current_media) == "video"
            )
        if not _workflow_input_link_has_media_reference(link):
            return False
        return _workflow_media_reference_kind(
            link,
            link.get("media") if isinstance(link.get("media"), dict) else {},
            link.get("storage") if isinstance(link.get("storage"), dict) else {},
        ) == "video"
    if source_node:
        if not _workflow_node_can_supply_image_reference(
            source_node,
        ):
            return False
        return workflow_current_media_version_has_media(
            project_id,
            episode_id,
            workflow,
            source_node_id,
        )
    if not _workflow_input_link_is_image_reference(link):
        return False
    status = str(link.get("status") or "").strip().lower()
    if status in {"pending", "pending_generation", "waiting", "missing", "unlinked", "needs_relink"}:
        return False
    return _workflow_input_link_has_media_reference(link)


def _workflow_node_data(workflow: dict[str, Any], node_id: str) -> dict[str, Any]:
    node = _workflow_node(workflow, node_id) or {}
    data = node.get("data")
    return data if isinstance(data, dict) else {}


def _workflow_node_matches_work_chain(workflow: dict[str, Any], node: dict[str, Any], work_chain_id: str | None) -> bool:
    resolved_work_chain_id = str(work_chain_id or "").strip()
    if not resolved_work_chain_id:
        return True
    node_work_chain_id = _workflow_node_work_chain_id(workflow, node)
    if node_work_chain_id:
        return node_work_chain_id == resolved_work_chain_id
    route_id = _node_route_id(node)
    return bool(route_id and route_id in _workflow_route_ids_for_work_chain(workflow, resolved_work_chain_id))


def _workflow_nodes_by_types(
    workflow: dict[str, Any],
    node_types: set[str],
    *,
    route_id: str | None = None,
    work_chain_id: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict):
            continue
        if _workflow_node_type(node) not in node_types:
            continue
        if route_id and _node_route_id(node) != route_id:
            continue
        if work_chain_id and not _workflow_node_matches_work_chain(workflow, node, work_chain_id):
            continue
        rows.append(node)
    return rows


def _workflow_adjacent_nodes(
    workflow: dict[str, Any],
    node_id: str,
    node_types: set[str],
    *,
    direction: str,
) -> list[dict[str, Any]]:
    edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    node_ids: list[str] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source_id = str(edge.get("source") or "")
        target_id = str(edge.get("target") or "")
        if direction == "downstream" and source_id == node_id and target_id:
            node_ids.append(target_id)
        elif direction == "upstream" and target_id == node_id and source_id:
            node_ids.append(source_id)
    nodes: list[dict[str, Any]] = []
    for adjacent_id in node_ids:
        adjacent = _workflow_node(workflow, adjacent_id)
        if adjacent and _workflow_node_type(adjacent) in node_types:
            nodes.append(adjacent)
    return nodes


def _workflow_director_board_for_context(
    workflow: dict[str, Any],
    node: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return work_chain_stage_node(workflow, node, "director.board")


def _workflow_first_node_id(nodes: list[dict[str, Any]]) -> str:
    if not nodes:
        return ""
    return str(nodes[0].get("id") or "").strip()


def _workflow_visual_handoff_node_is_generated(node: dict[str, Any] | None) -> bool:
    if not isinstance(node, dict) or str(node.get("type") or "") != "asset.image":
        return False
    return _workflow_node_is_visual_handoff_asset_like(node)


def resolve_generation_task_node_id(
    workflow: dict[str, Any],
    task_type: str | None,
    node_id: str | None = None,
) -> str:
    normalized = str(task_type or "").strip()
    requested_id = str(node_id or "").strip()
    requested_node = _workflow_node(workflow, requested_id) if requested_id else None
    requested_type = _workflow_node_type(requested_node) if requested_node else ""
    if normalized == "storyboard_plan":
        if requested_node and requested_type in _DIRECTOR_BOARD_NODE_TYPES:
            return requested_id
        if requested_node:
            director_node = _workflow_director_board_for_context(workflow, requested_node)
            director_node_id = str((director_node or {}).get("id") or "").strip()
            if director_node_id:
                return director_node_id
        return requested_id if requested_node else ""

    if normalized == "workflow":
        if requested_node and requested_type in _PROMPT_STORYBOARD_NODE_TYPES:
            return requested_id
        if requested_node:
            downstream = _workflow_adjacent_nodes(
                workflow,
                requested_id,
                _PROMPT_STORYBOARD_NODE_TYPES,
                direction="downstream",
            )
            if downstream:
                return _workflow_first_node_id(downstream)
        return requested_id if requested_node else ""

    if normalized in {"storyboard_image", "storyboard_image_edit"}:
        if requested_node and requested_type in _STORYBOARD_REFERENCE_NODE_TYPES:
            return requested_id
        if requested_node:
            downstream = _workflow_adjacent_nodes(
                workflow,
                requested_id,
                _STORYBOARD_REFERENCE_NODE_TYPES,
                direction="downstream",
            )
            if downstream:
                return _workflow_first_node_id(downstream)
            route_id = _node_route_id(requested_node)
            work_chain_id = _workflow_node_work_chain_id(workflow, requested_node)
            candidates: list[dict[str, Any]] = []
            if route_id:
                candidates.extend(
                    _workflow_nodes_by_types(
                        workflow,
                        _STORYBOARD_REFERENCE_NODE_TYPES,
                        route_id=route_id,
                    )
                )
            if work_chain_id:
                candidates.extend(
                    _workflow_nodes_by_types(
                        workflow,
                        _STORYBOARD_REFERENCE_NODE_TYPES,
                        work_chain_id=work_chain_id,
                    )
                )
            for candidate in candidates:
                if _workflow_is_default_work_chain_storyboard_result(workflow, candidate):
                    candidate_id = str(candidate.get("id") or "").strip()
                    if candidate_id:
                        return candidate_id
            for candidate in candidates:
                candidate_id = str(candidate.get("id") or "").strip()
                if candidate_id:
                    return candidate_id
        return requested_id if requested_node else ""

    if normalized == "visual_handoff_image":
        if requested_node and _workflow_visual_handoff_node_is_generated(requested_node):
            return requested_id
        if requested_node and requested_type in _VISUAL_HANDOFF_SOURCE_NODE_TYPES:
            existing = _workflow_visual_handoff_node_for_prompt(workflow, requested_id)
            if existing:
                return str(existing.get("id") or "").strip()
        if requested_node:
            downstream = _workflow_adjacent_nodes(
                workflow,
                requested_id,
                {"asset.image"},
                direction="downstream",
            )
            for item in downstream:
                if _workflow_visual_handoff_node_is_generated(item):
                    return str(item.get("id") or "").strip()
        return requested_id if requested_node else ""

    if normalized == "storyboard_video":
        if requested_node and requested_type in _VIDEO_RESULT_NODE_TYPES:
            return requested_id
        if requested_node:
            downstream = _workflow_adjacent_nodes(
                workflow,
                requested_id,
                _VIDEO_RESULT_NODE_TYPES,
                direction="downstream",
            )
            if downstream:
                return _workflow_first_node_id(downstream)
        return requested_id if requested_node else ""

    return requested_id


def _workflow_visual_handoff_node_for_prompt(
    workflow: dict[str, Any],
    prompt_node_id: str,
) -> dict[str, Any] | None:
    prompt_node_id = str(prompt_node_id or "").strip()
    if not prompt_node_id:
        return None
    for node in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
        if not isinstance(node, dict) or str(node.get("type") or "") != "asset.image":
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        is_visual_handoff = str(
            data.get("mediaPurpose")
            or data.get("media_purpose")
            or data.get("assetKind")
            or data.get("asset_kind")
            or data.get("assetType")
            or data.get("asset_type")
            or ""
        ).strip() == "visual_handoff"
        if not is_visual_handoff:
            continue
        if str(data.get("resultOfNodeId") or data.get("sourceNodeId") or "").strip() == prompt_node_id:
            return node
    return None
