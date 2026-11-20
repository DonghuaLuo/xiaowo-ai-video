# -*- coding: utf-8 -*-
"""工作流领域实际实现。"""
from __future__ import annotations

from .planning_workflow_assets import _asset_ref_canvas_materials
from .store_core import _now
from .workflow_asset_resolution import _copy_non_empty_fields
from .workflow_asset_resolution import _fill_empty_asset_node_media
from .workflow_contract import _append_unique_string
from .workflow_contract import _node_route_id
from .workflow_contract import _node_segment_id
from .workflow_contract import _node_work_chain_id
from .workflow_contract import _workflow_accepts_material_input
from .workflow_contract import _workflow_chain_route_ids
from .workflow_contract import _workflow_is_video_task_type
from .workflow_contract import _workflow_node
from .workflow_contract import _workflow_node_work_chain_id
from .workflow_input_resolution import _workflow_asset_link_has_image_binding
from .workflow_input_resolution import _workflow_linkable_scope_node_ids
from .workflow_input_resolution import _workflow_route_ids_for_work_chain
from .workflow_input_resolution import _workflow_work_chain_input_owner_nodes
from typing import Any
import copy
import re


def _workflow_asset_link_key(link: dict[str, Any]) -> tuple[str, str, str, str]:
    source_node_id = str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip()
    source_type = str(link.get("sourceType") or link.get("source_type") or "").strip()
    semantic_asset_id = str(
        link.get("rootAssetId")
        or link.get("assetId")
        or ""
    ).strip()
    media_id = "" if semantic_asset_id else str(link.get("mediaId") or link.get("media_id") or "").strip()
    if source_node_id:
        return (
            "source-node",
            f"{source_type}:{source_node_id}",
            str(link.get("targetSlot") or link.get("target_slot") or link.get("slot") or "").strip(),
            "",
        )
    return (
        "asset",
        f"{str(link.get('rootAssetType') or link.get('assetType') or '').strip()}:{semantic_asset_id}",
        str(link.get("targetSlot") or link.get("target_slot") or link.get("slot") or "").strip(),
        media_id,
    )


def _workflow_prompt_asset_node_id_suffix(node: dict[str, Any], segment_id: str, route_id: str) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    for value in (node.get("id"), data.get("nodeId"), data.get("node_id")):
        match = re.search(r"_route_(\d{2})(?:_|$)", str(value or ""))
        if match and match.group(1) != "01":
            return f"_route_{match.group(1)}"
    if segment_id and route_id:
        prefix = f"route_{segment_id}_"
        if route_id.startswith(prefix):
            match = re.match(r"(\d{2})(?:_|$)", route_id[len(prefix):])
            if match and match.group(1) != "01":
                return f"_route_{match.group(1)}"
    return ""


def _merge_asset_input_link_without_rebinding_media(
    current_link: dict[str, Any],
    incoming_link: dict[str, Any],
) -> dict[str, Any]:
    merged_link = copy.deepcopy(current_link)
    current_has_media = _workflow_asset_link_has_image_binding(current_link)
    incoming_has_media = _workflow_asset_link_has_image_binding(incoming_link)
    _copy_non_empty_fields(
        merged_link,
        incoming_link,
        (
            "label",
            "displayName",
            "assetName",
            "aliases",
            "assetId",
            "assetType",
            "sourceType",
            "targetSlot",
            "slot",
            "status",
            "visibilityScope",
        ),
    )
    for field in ("sourceNodeId", "sourceNodeType", "targetNodeId", "targetNodeType"):
        if not merged_link.get(field) and incoming_link.get(field):
            merged_link[field] = copy.deepcopy(incoming_link.get(field))
    if not current_has_media and incoming_has_media:
        _copy_non_empty_fields(
            merged_link,
            incoming_link,
            (
                "mediaId",
                "mediaVersionId",
                "sourceVersionId",
                "versionId",
                "assetVersionId",
                "activeMediaVersionId",
                "mediaType",
                "path",
                "file",
                "relativePath",
                "relative_path",
                "url",
                "preview",
            ),
        )
        merged_link["mediaBindingMode"] = "pinned"
        merged_link["mediaPinnedAt"] = _now()
    return merged_link


def _workflow_video_task_nodes_inheriting_material_targets(
    workflow: dict[str, Any],
    material_target_node_ids: set[str],
) -> set[str]:
    if not material_target_node_ids:
        return set()
    video_node_ids: set[str] = set()
    for node in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        if not node_id or not _workflow_is_video_task_type(str(node.get("type") or "")):
            continue
        for owner in _workflow_work_chain_input_owner_nodes(workflow, node):
            owner_id = str(owner.get("id") or "").strip()
            if owner_id in material_target_node_ids:
                video_node_ids.add(node_id)
                break
    return video_node_ids


def _apply_asset_ref_canvas_materials_to_prompt_node(
    project_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
    asset_refs: Any,
    *,
    allow_new_links: bool = True,
    only_fill_empty: bool = False,
) -> tuple[bool, list[dict[str, str]]]:
    node_id = str(node.get("id") or "").strip()
    if not node_id:
        return False, []
    node_data = node.setdefault("data", {})
    if not isinstance(node_data, dict):
        node_data = {}
        node["data"] = node_data
    route_id = _node_route_id(node) or str(node_data.get("routeId") or node_data.get("route_id") or "")
    segment_id = _node_segment_id(node) or str(node_data.get("segmentId") or node_data.get("segment_id") or node_id)
    work_chain_id = _node_work_chain_id(node) or str(node_data.get("workChainId") or node_data.get("work_chain_id") or segment_id)
    input_links, asset_nodes, asset_edges, missing_asset_refs = _asset_ref_canvas_materials(
        project_id,
        asset_refs,
        target_node_id=node_id,
        route_id=route_id,
        segment_id=segment_id,
        work_chain_id=work_chain_id,
        node_id_suffix=_workflow_prompt_asset_node_id_suffix(node, segment_id, route_id),
    )

    changed = False
    link_id_overrides: dict[str, str] = {}
    filled_source_node_ids: set[str] = set()
    existing_links = [
        copy.deepcopy(link)
        for link in node_data.get("inputLinks", [])
        if isinstance(link, dict)
    ] if isinstance(node_data.get("inputLinks"), list) else []
    existing_link_index = {
        _workflow_asset_link_key(link): index
        for index, link in enumerate(existing_links)
    }
    for link in input_links:
        key = _workflow_asset_link_key(link)
        generated_link_id = str(link.get("id") or link.get("inputLinkId") or "").strip()
        if key in existing_link_index:
            existing_index = existing_link_index[key]
            current_link = existing_links[existing_index]
            if only_fill_empty and _workflow_asset_link_has_image_binding(current_link):
                continue
            existing_link_id = str(current_link.get("id") or current_link.get("inputLinkId") or current_link.get("input_link_id") or "").strip()
            if existing_link_id and generated_link_id and existing_link_id != generated_link_id:
                link_id_overrides[generated_link_id] = existing_link_id
            current_has_media = _workflow_asset_link_has_image_binding(current_link)
            incoming_has_media = _workflow_asset_link_has_image_binding(link)
            merged_link = _merge_asset_input_link_without_rebinding_media(current_link, link)
            if not current_has_media and incoming_has_media:
                filled_source_node_id = str(merged_link.get("sourceNodeId") or "").strip()
                if filled_source_node_id:
                    filled_source_node_ids.add(filled_source_node_id)
            if merged_link != current_link:
                existing_links[existing_index] = merged_link
                changed = True
            continue
        if not allow_new_links or only_fill_empty:
            continue
        existing_links.append(copy.deepcopy(link))
        existing_link_index[key] = len(existing_links) - 1
        changed = True
    if existing_links and node_data.get("inputLinks") != existing_links:
        node_data["inputLinks"] = existing_links
        changed = True

    nodes = workflow.setdefault("nodes", [])
    node_by_id = {
        str(item.get("id") or ""): item
        for item in nodes
        if isinstance(item, dict) and str(item.get("id") or "")
    } if isinstance(nodes, list) else {}
    for raw_asset_node in asset_nodes:
        asset_node = copy.deepcopy(raw_asset_node)
        asset_node_id = str(asset_node.get("id") or "").strip()
        if not asset_node_id:
            continue
        if only_fill_empty and asset_node_id not in filled_source_node_ids:
            continue
        existing_node = node_by_id.get(asset_node_id)
        if existing_node:
            if _fill_empty_asset_node_media(existing_node, asset_node):
                changed = True
            continue
        if not allow_new_links or only_fill_empty or not isinstance(nodes, list):
            continue
        nodes.append(asset_node)
        node_by_id[asset_node_id] = asset_node
        changed = True

    workflow_edges = workflow.setdefault("edges", [])
    if isinstance(workflow_edges, list):
        edge_ids = {str(edge.get("id") or "") for edge in workflow_edges if isinstance(edge, dict)}
        for raw_edge in asset_edges:
            edge = copy.deepcopy(raw_edge)
            source_id = str(edge.get("source") or "").strip()
            if only_fill_empty and source_id not in filled_source_node_ids:
                continue
            edge_data = edge.setdefault("data", {})
            if isinstance(edge_data, dict):
                input_link_id = str(edge_data.get("inputLinkId") or "").strip()
                if input_link_id in link_id_overrides:
                    edge_data["inputLinkId"] = link_id_overrides[input_link_id]
                target_slot = str(edge_data.get("targetSlot") or edge_data.get("role") or "").strip()
            else:
                target_slot = ""
            edge_id = str(edge.get("id") or "").strip()
            if not edge_id or edge_id in edge_ids:
                continue
            workflow_edges.append(edge)
            edge_ids.add(edge_id)
            changed = True
    return changed, missing_asset_refs


def _workflow_asset_row_identity_strings(row: dict[str, Any]) -> list[str]:
    text = str(row.get("id") or "").strip()
    return [text] if text else []


def _workflow_work_chain_id_for_route(workflow: dict[str, Any], route_id: str) -> str:
    if not route_id:
        return ""
    for route in workflow.get("routes", []):
        if not isinstance(route, dict) or str(route.get("id") or "").strip() != route_id:
            continue
        route_work_chain_id = str(route.get("workChainId") or route.get("work_chain_id") or "").strip()
        if route_work_chain_id:
            return route_work_chain_id
        break
    for chain in workflow.get("workChains", []):
        if not isinstance(chain, dict):
            continue
        if any(str(item or "").strip() == route_id for item in _workflow_chain_route_ids(chain)):
            return str(chain.get("id") or "").strip()
    return ""


def _workflow_remaining_route_ids_for_work_chain(
    workflow: dict[str, Any],
    work_chain_id: str,
    delete_route_ids: set[str],
) -> set[str]:
    if not work_chain_id:
        return set()
    deleted = {str(route_id or "").strip() for route_id in delete_route_ids if str(route_id or "").strip()}
    route_row_ids = {
        str(route.get("id") or "").strip()
        for route in workflow.get("routes", [])
        if isinstance(route, dict) and str(route.get("id") or "").strip()
    }
    node_route_ids: set[str] = set()
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_route_id = _node_route_id(node)
        if node_route_id and _workflow_node_work_chain_id(workflow, node) == work_chain_id:
            node_route_ids.add(node_route_id)
    live_route_ids = route_row_ids | node_route_ids
    return {
        route_id
        for route_id in _workflow_route_ids_for_work_chain(workflow, work_chain_id)
        if route_id and route_id not in deleted and route_id in live_route_ids
    }


def _workflow_nodes_patch(
    workflow: dict[str, Any],
    node_ids: set[str] | list[Any] | tuple[Any, ...],
) -> list[dict[str, Any]]:
    wanted = {str(item or "").strip() for item in node_ids if str(item or "").strip()}
    if not wanted:
        return []
    return [
        copy.deepcopy(node)
        for node in (workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else [])
        if isinstance(node, dict) and str(node.get("id") or "").strip() in wanted
    ]


def _clear_workflow_node_generated_output(data: dict[str, Any]) -> None:
    for key in (
        "activeVersionId",
        "winnerVersionId",
        "sourceVersionId",
        "mediaId",
        "mediaVersionId",
        "assetVersionId",
        "activeMediaVersionId",
        "mediaVersionTitle",
        "sourceFileName",
        "thumbnail",
        "thumbnailUrl",
        "previewUrl",
        "jobId",
        "taskId",
        "providerTaskId",
        "completedAt",
        "selectedAt",
        "media",
        "storage",
    ):
        data.pop(key, None)


def _workflow_input_target(
    workflow: dict[str, Any],
    payload: dict[str, Any],
    *,
    scope: str,
) -> tuple[dict[str, Any] | None, str, str, str]:
    target_node_id = str(
        payload.get("targetNodeId")
        or payload.get("target_node_id")
        or payload.get("nodeId")
        or payload.get("node_id")
        or ""
    ).strip()
    route_id = str(payload.get("routeId") or payload.get("route_id") or "").strip()
    work_chain_id = str(payload.get("workChainId") or payload.get("work_chain_id") or "").strip()
    segment_id = str(payload.get("segmentId") or payload.get("segment_id") or "").strip()
    target_node = _workflow_node(workflow, target_node_id) if target_node_id else None
    if scope == "node":
        if not target_node:
            raise FileNotFoundError("目标节点不存在")
        if not _workflow_accepts_material_input(target_node):
            raise ValueError("素材输入只能链接到分镜脚本、分镜单元或视频生成")
        route_id = route_id or _node_route_id(target_node)
        work_chain_id = work_chain_id or _node_work_chain_id(target_node)
        segment_id = segment_id or _node_segment_id(target_node)
    elif scope == "route" and not route_id:
        raise ValueError("请指定要链接的 route")
    elif scope == "workChain" and not (work_chain_id or route_id):
        raise ValueError("请指定要链接的 route 或工作链")
    if not work_chain_id and route_id:
        route = next(
            (
                item
                for item in workflow.get("routes", [])
                if isinstance(item, dict) and str(item.get("id") or "") == route_id
            ),
            None,
        )
        work_chain_id = str(route.get("workChainId") or route.get("work_chain_id") or "").strip() if isinstance(route, dict) else ""
    return target_node, route_id, segment_id, work_chain_id


def _append_reference_media_to_scope(
    workflow: dict[str, Any],
    *,
    media_id: str,
    scope: str,
    target_node: dict[str, Any] | None,
    route_id: str,
    work_chain_id: str,
) -> None:
    if not media_id:
        return
    if scope == "node" and target_node:
        data = target_node.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            target_node["data"] = data
        data["referenceMediaIds"] = _append_unique_string(data.get("referenceMediaIds"), media_id)
        return
    if scope not in {"route", "workChain"}:
        return
    route_node_ids = _workflow_linkable_scope_node_ids(
        workflow,
        scope=scope,
        route_id=route_id,
        work_chain_id=work_chain_id,
    )
    node_rows = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    for node in node_rows:
        if str(node.get("id") or "") not in route_node_ids:
            continue
        data = node.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            node["data"] = data
        data["referenceMediaIds"] = _append_unique_string(data.get("referenceMediaIds"), media_id)


def _remove_reference_media_from_scope(
    workflow: dict[str, Any],
    *,
    media_ids: set[str],
    scope: str,
    target_node: dict[str, Any] | None,
    route_id: str,
    work_chain_id: str,
) -> None:
    if not media_ids:
        return
    nodes: list[dict[str, Any]]
    if scope == "node" and target_node:
        nodes = [target_node]
    elif scope in {"route", "workChain"}:
        route_node_ids = _workflow_linkable_scope_node_ids(
            workflow,
            scope=scope,
            route_id=route_id,
            work_chain_id=work_chain_id,
        )
        node_rows = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
        nodes = [
            node
            for node in node_rows
            if isinstance(node, dict) and str(node.get("id") or "") in route_node_ids
        ]
    else:
        nodes = []
    for node in nodes:
        data = node.get("data")
        if not isinstance(data, dict):
            data = {}
            node["data"] = data
        refs = [
            str(item or "").strip()
            for item in data.get("referenceMediaIds", [])
            if str(item or "").strip() and str(item or "").strip() not in media_ids
        ]
        data["referenceMediaIds"] = refs
