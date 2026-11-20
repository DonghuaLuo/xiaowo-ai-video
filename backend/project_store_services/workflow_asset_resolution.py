# -*- coding: utf-8 -*-
"""画布资产素材补齐与生成前输入解析；包含持久化写入。"""
from __future__ import annotations

from .agent_sessions import _hydrate_media_asset_for_ui
from .agent_sessions import _persistent_media_data_removed
from .assets import list_assets
from .catalogs import ASSET_TYPES
from .store_core import ASSET_LIFECYCLE_ACTIVE
from .store_core import _normalize_asset_type_key
from .workflow_contract import _workflow_image_node_type
from typing import Any

import copy
from .canvas_store_queries import get_canvas_records_v4, read_canvas_workflow_projection_v4, read_workflow_card_neighborhood_v4
from .canvas_store_mutations import write_canvas_card_records_v4
from .video_task_card_references import _ASSET_REF_COLLECTIONS
from .planning_workflow_builder import (
    _asset_ref_canvas_materials,
)
from .projects import (
    _touch_project_meta,
)
from .store_core import (
    _emit_agent_event,
    _now,
)
from .workflow_contract import (
    _node_route_id,
    _node_segment_id,
    _node_work_chain_id,
    _workflow_accepts_material_input,
    _workflow_mutation_event_fields,
    _workflow_node,
    _workflow_normalize_asset_type,
)
from .workflow_input_resolution import (
    _resolve_workflow_node_inputs_from_workflow,
    _workflow_asset_node_has_image_binding,
    _workflow_canvas_asset_node_project_asset_identity,
)


def _copy_non_empty_fields(target: dict[str, Any], source: dict[str, Any], fields: tuple[str, ...]) -> None:
    for field in fields:
        if field in source and source.get(field) not in (None, ""):
            target[field] = copy.deepcopy(source.get(field))


def _fill_empty_asset_node_media(existing_node: dict[str, Any], incoming_node: dict[str, Any]) -> bool:
    if _workflow_asset_node_has_image_binding(existing_node) or not _workflow_asset_node_has_image_binding(incoming_node):
        return False
    existing_data = existing_node.setdefault("data", {})
    if not isinstance(existing_data, dict):
        existing_data = {}
        existing_node["data"] = existing_data
    incoming_data = incoming_node.get("data") if isinstance(incoming_node.get("data"), dict) else {}
    before = copy.deepcopy(existing_data)
    _copy_non_empty_fields(
        existing_data,
        incoming_data,
        (
            "mediaId",
            "mediaVersionId",
            "sourceVersionId",
            "versionId",
            "assetVersionId",
            "activeMediaVersionId",
        ),
    )
    for field in ("media", "storage"):
        if isinstance(incoming_data.get(field), dict):
            existing_data[field] = copy.deepcopy(incoming_data.get(field))
    existing_data["status"] = "ready"
    existing_data["mediaBindingMode"] = "pinned"
    existing_data["mediaPinnedAt"] = _now()
    return existing_data != before


def _workflow_material_target_nodes_for_source(
    workflow: dict[str, Any],
    source_node_id: str,
) -> list[dict[str, Any]]:
    normalized_source_id = str(source_node_id or "").strip()
    if not normalized_source_id:
        return []
    target_nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in workflow.get("edges", []) if isinstance(workflow.get("edges"), list) else []:
        if not isinstance(edge, dict):
            continue
        edge_data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        if edge_data.get("kind") != "material":
            continue
        if str(edge.get("source") or "").strip() != normalized_source_id:
            continue
        target_id = str(edge.get("target") or "").strip()
        if not target_id or target_id in seen:
            continue
        target_node = _workflow_node(workflow, target_id)
        if not isinstance(target_node, dict) or not _workflow_accepts_material_input(target_node):
            continue
        seen.add(target_id)
        target_nodes.append(target_node)
    return target_nodes


def _workflow_incoming_asset_node_for_canvas_card(
    project_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
    *,
    asset_type: str,
    asset_id: str,
) -> dict[str, Any] | None:
    node_asset_type, node_asset_id = _workflow_canvas_asset_node_project_asset_identity(node)
    target_asset_type = _workflow_normalize_asset_type(asset_type)
    if target_asset_type and node_asset_type != target_asset_type:
        return None
    if node_asset_type not in _ASSET_REF_COLLECTIONS:
        return None
    if asset_id and node_asset_id != str(asset_id or "").strip():
        return None

    lookup_token = node_asset_id
    if not lookup_token:
        return None

    source_node_id = str(node.get("id") or "").strip()
    target_nodes = _workflow_material_target_nodes_for_source(workflow, source_node_id)
    target_node = target_nodes[0] if target_nodes else None
    target_node_id = str((target_node or {}).get("id") or source_node_id)
    target_node_type = str((target_node or {}).get("type") or "prompt.storyboard")
    node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
    target_data = target_node.get("data") if isinstance(target_node, dict) and isinstance(target_node.get("data"), dict) else {}
    route_id = _node_route_id(node) or (_node_route_id(target_node) if isinstance(target_node, dict) else "")
    segment_id = (
        _node_segment_id(node)
        or (_node_segment_id(target_node) if isinstance(target_node, dict) else "")
        or target_node_id
    )
    work_chain_id = (
        _node_work_chain_id(node)
        or (_node_work_chain_id(target_node) if isinstance(target_node, dict) else "")
        or str(node_data.get("workChainId") or node_data.get("work_chain_id") or target_data.get("workChainId") or target_data.get("work_chain_id") or "")
    )

    _input_links, asset_nodes, _asset_edges, _missing_asset_refs = _asset_ref_canvas_materials(
        project_id,
        {node_asset_type: [lookup_token]},
        target_node_id=target_node_id,
        route_id=route_id,
        segment_id=segment_id,
        work_chain_id=work_chain_id,
        target_node_type=target_node_type,
    )
    for asset_node in asset_nodes:
        if _workflow_asset_node_has_image_binding(asset_node):
            return asset_node
    return None


def resolve_canvas_asset_images(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
    *,
    workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    requested_ids = payload.get("nodeIds")
    if not isinstance(requested_ids, list) or any(not isinstance(item, str) for item in requested_ids):
        raise ValueError("nodeIds 必须是当前画布节点 ID 列表")
    requested = set(requested_ids)
    if not requested:
        return {"success": True, "episodeId": episode_id, "nodes": [], "boundNodeIds": []}
    current = workflow if workflow is not None else read_canvas_workflow_projection_v4(project_id, episode_id, detail="full")
    selected = [
        node for node in current.get("nodes", [])
        if node.get("id") in requested and node.get("type") == "asset.image"
        and (node.get("data") or {}).get("rootAssetProjectId") == project_id
    ]
    candidates: dict[str, tuple[tuple[str, str], dict[str, Any]]] = {}
    for node in selected:
        if _workflow_asset_node_has_image_binding(node):
            continue
        identity = _workflow_canvas_asset_node_project_asset_identity(node)
        if not all(identity):
            continue
        incoming = _workflow_incoming_asset_node_for_canvas_card(
            project_id, current, node, asset_type=identity[0], asset_id=identity[1],
        )
        if incoming and _workflow_asset_node_has_image_binding(incoming):
            candidates[node["id"]] = (identity, incoming)

    def bind_current_card(node: dict[str, Any]) -> dict[str, Any] | None:
        identity, incoming = candidates[node["id"]]
        if (node.get("data") or {}).get("rootAssetProjectId") != project_id:
            return None
        if _workflow_canvas_asset_node_project_asset_identity(node) != identity:
            return None
        if not _fill_empty_asset_node_media(node, incoming):
            return None
        return node["data"]

    bound_nodes: list[dict[str, Any]] = []
    if candidates:
        saved = write_canvas_card_records_v4(
            project_id, episode_id, [{"id": node_id} for node_id in candidates],
            data_transform=bind_current_card, skip_missing=True, changed_resources=["canvas_node"],
        )
        bound_nodes = saved.get("nodes") or []
        if bound_nodes:
            _touch_project_meta(project_id)
            _emit_agent_event("project_changed", {
                "action": "canvas_asset_images_resolved", "projectId": project_id, "episodeId": episode_id,
                "nodes": bound_nodes, "workflowVersion": saved["workflowVersion"],
                **_workflow_mutation_event_fields(saved, ["canvas_node"]),
            })
    if not selected:
        return {"success": True, "episodeId": episode_id, "nodes": [], "boundNodeIds": []}
    latest = get_canvas_records_v4(project_id, episode_id, {"ids": {"nodeIds": [node["id"] for node in selected]}, "detail": "full"})
    return {
        "success": True, "episodeId": episode_id,
        "nodes": [node for node in latest["records"]["nodes"] if _workflow_asset_node_has_image_binding(node)],
        "workflowVersion": latest["currentRevision"], "boundNodeIds": [node["id"] for node in bound_nodes],
    }


def resolve_workflow_node_inputs(
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
    inputs = _resolve_workflow_node_inputs_from_workflow(project_id, source_workflow, episode_id, node_id)
    source_ids = {str(link.get("sourceNodeId") or "") for link in inputs.get("inputLinks") or []}
    asset_ids = [
        node["id"] for node in source_workflow.get("nodes", [])
        if node.get("id") in source_ids and node.get("type") == "asset.image"
        and (node.get("data") or {}).get("rootAssetProjectId") == project_id
        and not _workflow_asset_node_has_image_binding(node)
    ]
    if asset_ids:
        resolve_canvas_asset_images(project_id, episode_id, {"nodeIds": asset_ids}, workflow=source_workflow)
        # Use a fresh task context after the same first-binding path used by the canvas.
        latest = read_workflow_card_neighborhood_v4(project_id, episode_id, node_id, detail="full")
        source_workflow.clear()
        source_workflow.update(latest)
        inputs = _resolve_workflow_node_inputs_from_workflow(project_id, source_workflow, episode_id, node_id)
    return inputs


def _workflow_canvas_asset_exists(
    assets: dict[str, Any],
    asset_type: str,
    asset_id: str,
) -> bool:
    rows = assets.get(asset_type) if isinstance(assets, dict) else []
    if not isinstance(rows, list):
        return False
    target_id = asset_id.strip().casefold()
    if not target_id:
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or "").strip().casefold()
        if target_id == row_id:
            return True
    return False


def _workflow_canvas_project_asset_info(node: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(node, dict):
        return None
    node_type = _workflow_image_node_type(node)
    if node_type not in {"asset.image", "media.external"}:
        return None
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    source_type = str(data.get("sourceType") or data.get("source_type") or "").strip().lower()
    if source_type != "asset":
        return None
    asset_type = _normalize_asset_type_key(
        data.get("assetType") or data.get("asset_type") or data.get("assetKind") or ""
    )
    asset_id = str(data.get("assetId") or data.get("asset_id") or "").strip()
    if not asset_type or asset_type not in ASSET_TYPES or not asset_id:
        return None
    return {
        "assetType": asset_type,
        "assetId": asset_id,
        "assetName": str(
            data.get("assetName") or data.get("asset_name") or data.get("title") or ""
        ).strip(),
    }


def _asset_media_version_as_storyboard_version(
    project_id: str,
    episode_id: str,
    node_id: str,
    asset_info: dict[str, str],
    version: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(version, dict):
        return None
    version_id = str(version.get("id") or "").strip()
    if not version_id:
        return None
    asset_type = asset_info.get("assetType") or ""
    asset_id = asset_info.get("assetId") or ""
    asset_name = asset_info.get("assetName") or ""
    media = _hydrate_media_asset_for_ui(project_id, version.get("media"))
    row: dict[str, Any] = {
        "id": version_id,
        "nodeId": node_id,
        "title": str(version.get("title") or asset_name or "设计图版本"),
        "status": str(version.get("status") or "ready"),
        "createdAt": str(version.get("createdAt") or ""),
        "summary": str(version.get("summary") or version.get("desc") or ""),
        "source": str(version.get("source") or "project-asset-version"),
        "payload": {
            "versionSource": "project_asset",
            "episodeId": episode_id,
            "assetType": asset_type,
            "assetId": asset_id,
            "assetName": asset_name,
            "assetVersionId": version_id,
        },
    }
    if media:
        row["media"] = media
    if version.get("preview"):
        row["preview"] = version.get("preview")
    for key in ("model", "provider", "generationError", "generationDebug"):
        if version.get(key) is not None:
            row[key] = _persistent_media_data_removed(version.get(key))
    return row


def _workflow_canvas_project_asset_versions(
    project_id: str,
    episode_id: str,
    node_id: str,
    node: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    asset_info = _workflow_canvas_project_asset_info(node)
    if not asset_info:
        return []
    assets = list_assets(
        "project",
        project_id,
        hydrate=True,
        include_source_metadata=False,
        asset_type=asset_info["assetType"],
        lifecycle_status=ASSET_LIFECYCLE_ACTIVE,
    )
    rows = assets.get(asset_info["assetType"]) if isinstance(assets, dict) else []
    if not isinstance(rows, list):
        return []
    asset = next(
        (
            item
            for item in rows
            if isinstance(item, dict)
            and str(item.get("id") or "") == asset_info["assetId"]
        ),
        None,
    )
    versions = (
        asset.get("mediaVersions")
        if isinstance(asset, dict) and isinstance(asset.get("mediaVersions"), list)
        else []
    )
    result: list[dict[str, Any]] = []
    for version in versions:
        row = _asset_media_version_as_storyboard_version(
            project_id,
            episode_id,
            node_id,
            asset_info,
            version,
        )
        if row:
            result.append(row)
    return result
