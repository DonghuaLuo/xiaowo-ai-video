# -*- coding: utf-8 -*-
"""工作链投影使用的资产解析、素材卡与素材连线。"""
from __future__ import annotations

import copy
from .assets import (
    list_assets,
)
from .planning_contract import (
    _CANVAS_NODE_ROLE_IMAGE_ASSET,
    _WORKFLOW_ASSET_INPUT_HANDLE,
    _WORKFLOW_VIDEO_INPUT_HANDLE,
    _asset_ref_tokens,
    _safe_workflow_id,
)
from .splitting_templates import (
    _string_list,
)
from .store_core import (
    ASSET_LIFECYCLE_ACTIVE,
)
from typing import (
    Any,
)


def _asset_input_links(
    asset_refs: Any,
    target_node_id: str,
    route_id: str,
    segment_id: str,
    work_chain_id: str,
    target_node_type: str = "director.board",
) -> list[dict[str, Any]]:
    refs = asset_refs if isinstance(asset_refs, dict) else {}
    slot_by_type = {
        "characters": "character_reference",
        "creatures": "creature_reference",
        "scenes": "scene_reference",
        "props": "prop_reference",
    }
    links: list[dict[str, Any]] = []
    for asset_type, slot in slot_by_type.items():
        for ref in _asset_ref_entries(refs.get(asset_type)):
            token = str(ref.get("token") or "").strip()
            if not token:
                continue
            link_id = _safe_workflow_id(f"link_{segment_id}_{target_node_id}_{asset_type}_{token}", f"link_{len(links) + 1:03d}")
            link = {
                "id": link_id,
                "sourceType": "asset",
                "assetType": asset_type,
                "sourceId": token,
                "targetNodeId": target_node_id,
                "targetNodeType": target_node_type,
                "targetSlot": slot,
                "workChainId": work_chain_id,
                "routeId": route_id,
                "segmentId": segment_id,
                "status": "linked",
                "visibilityScope": "workChain",
            }
            if ref.get("mediaVersionId"):
                link["mediaVersionId"] = str(ref.get("mediaVersionId") or "")
                link["sourceVersionId"] = str(ref.get("mediaVersionId") or "")
            if ref.get("stateTag"):
                link["stateTag"] = str(ref.get("stateTag") or "")
            links.append(link)
    return links


def _video_task_initial_asset_thumbnails(input_links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [copy.deepcopy(link) for link in input_links if isinstance(link, dict)]


def _asset_row_display_name(row: dict[str, Any]) -> str:
    for key in ("displayName", "display_name", "name", "title", "assetName", "asset_name", "id"):
        text = str(row.get(key) or "").strip()
        if text:
            return text
    return ""


def _asset_row_aliases(row: dict[str, Any]) -> list[str]:
    aliases = _string_list(row.get("aliases") or row.get("alias") or row.get("alsoKnownAs") or row.get("also_known_as"))
    display_name = _asset_row_display_name(row)
    return [item for item in aliases if item and item != display_name]


def _asset_row_identity_strings(row: dict[str, Any], *, include_ids: bool = True, include_aliases: bool = True) -> list[str]:
    keys = ["name", "title", "displayName", "display_name", "assetName", "asset_name"]
    if include_ids:
        keys.append("id")
    tokens: list[str] = []
    for key in keys:
        text = str(row.get(key) or "").strip()
        if text and text not in tokens:
            tokens.append(text)
    if include_aliases:
        for alias in _asset_row_aliases(row):
            if alias and alias not in tokens:
                tokens.append(alias)
    return tokens


def _asset_row_canonical_identity_strings(row: dict[str, Any]) -> list[str]:
    text = str(row.get("id") or "").strip()
    return [text] if text else []


def _asset_media_version_state_tags(version: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    state_tag = str(version.get("stateTag") or version.get("state_tag") or "").strip()
    if state_tag:
        tags.append(state_tag)
    for tag in _string_list(version.get("stateTags") or version.get("state_tags")):
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _asset_ref_preferred_media_version_id(ref: Any) -> str:
    if not isinstance(ref, dict):
        return ""
    for key in (
        "mediaVersionId",
        "media_version_id",
        "sourceVersionId",
        "source_version_id",
        "versionId",
        "version_id",
        "stateTagId",
        "state_tag_id",
    ):
        text = str(ref.get(key) or "").strip()
        if text:
            return text
    return ""


def _asset_ref_preferred_state_tag(ref: Any) -> str:
    if not isinstance(ref, dict):
        return ""
    for key in ("stateTag", "state_tag", "stateLabel", "state_label"):
        text = str(ref.get(key) or "").strip()
        if text:
            return text
    return ""


def _asset_ref_entries(value: Any) -> list[dict[str, str]]:
    if isinstance(value, (list, tuple, set)):
        entries: list[dict[str, str]] = []
        for item in value:
            entries.extend(_asset_ref_entries(item))
        deduped: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for entry in entries:
            key = (
                str(entry.get("token") or "").casefold(),
                str(entry.get("mediaVersionId") or ""),
                str(entry.get("stateTag") or "").casefold(),
            )
            if not key[0] or key in seen:
                continue
            seen.add(key)
            deduped.append(entry)
        return deduped
    if isinstance(value, dict):
        version_id = _asset_ref_preferred_media_version_id(value)
        state_tag = _asset_ref_preferred_state_tag(value)
        entries = []
        for token in _asset_ref_tokens(value):
            entry = {"token": token}
            if version_id:
                entry["mediaVersionId"] = version_id
            if state_tag:
                entry["stateTag"] = state_tag
            for key in ("position", "role", "note", "label"):
                text = str(value.get(key) or "").strip()
                if text:
                    entry[key] = text
            entries.append(entry)
        return entries
    return [{"token": token} for token in _asset_ref_tokens(value)]


def _asset_ref_canvas_index(project_id: str | None) -> dict[str, dict[str, dict[str, Any]]]:
    if not project_id:
        return {}
    assets = list_assets("project", project_id, hydrate=False, lifecycle_status=ASSET_LIFECYCLE_ACTIVE, persist_normalization=False)
    index: dict[str, dict[str, dict[str, Any]]] = {}
    for asset_type in ("characters", "creatures", "scenes", "props"):
        rows = assets.get(asset_type) if isinstance(assets, dict) else []
        index[asset_type] = {}
        asset_rows = rows if isinstance(rows, list) else []
        for row in asset_rows:
            if not isinstance(row, dict):
                continue
            for text in _asset_row_canonical_identity_strings(row):
                if text:
                    index[asset_type][text.casefold()] = row
    return index


def _asset_canvas_media(
    asset: dict[str, Any],
    *,
    preferred_media_version_id: str = "",
    preferred_state_tag: str = "",
) -> tuple[dict[str, Any] | None, str]:
    versions = [item for item in asset.get("mediaVersions") or [] if isinstance(item, dict)]
    active_id = str(asset.get("activeMediaVersionId") or "").strip()
    preferred_media_version_id = str(preferred_media_version_id or "").strip()
    if preferred_media_version_id:
        for version in versions:
            if str(version.get("id") or "") != preferred_media_version_id:
                continue
            media = version.get("media")
            if isinstance(media, dict):
                return copy.deepcopy(media), str(version.get("id") or "")
        return None, ""
    preferred_state_key = str(preferred_state_tag or "").strip().casefold()
    if preferred_state_key:
        for version in versions:
            state_keys = [tag.casefold() for tag in _asset_media_version_state_tags(version)]
            if preferred_state_key not in state_keys:
                continue
            media = version.get("media")
            if isinstance(media, dict):
                return copy.deepcopy(media), str(version.get("id") or "")
        return None, ""
    if active_id:
        for version in versions:
            if str(version.get("id") or "") != active_id:
                continue
            media = version.get("media")
            if isinstance(media, dict):
                return copy.deepcopy(media), str(version.get("id") or "")
    return None, ""


def _asset_ref_canvas_materials(
    project_id: str | None,
    asset_refs: Any,
    *,
    target_node_id: str,
    route_id: str,
    segment_id: str,
    work_chain_id: str,
    target_node_type: str = "director.board",
    node_id_suffix: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    if not project_id:
        return _asset_input_links(
            asset_refs,
            target_node_id,
            route_id,
            segment_id,
            work_chain_id,
            target_node_type,
        ), [], [], []
    refs = asset_refs if isinstance(asset_refs, dict) else {}
    index = _asset_ref_canvas_index(project_id)
    slot_by_type = {
        "characters": "character_reference",
        "creatures": "creature_reference",
        "scenes": "scene_reference",
        "props": "prop_reference",
    }
    input_links: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    node_ids: set[str] = set()
    lane_index = 0
    for asset_type, target_slot in slot_by_type.items():
        for ref in _asset_ref_entries(refs.get(asset_type)):
            token = str(ref.get("token") or "").strip()
            if not token:
                continue
            asset = index.get(asset_type, {}).get(str(token).casefold())
            if not asset:
                missing.append({"assetType": asset_type, "token": str(token), "reason": "asset_not_found"})
                continue
            preferred_media_version_id = str(ref.get("mediaVersionId") or "").strip()
            preferred_state_tag = str(ref.get("stateTag") or "").strip()
            media, media_version_id = _asset_canvas_media(
                asset,
                preferred_media_version_id=preferred_media_version_id,
                preferred_state_tag=preferred_state_tag,
            )
            asset_id = str(asset.get("id") or "").strip()
            if not asset_id:
                missing.append({"assetType": asset_type, "token": str(token), "reason": "asset_missing_id"})
                continue
            display_name = _asset_row_display_name(asset) or asset_id
            aliases = _asset_row_aliases(asset)
            media_row = media if isinstance(media, dict) else {}
            media_id = str(media_row.get("id") or media_version_id or "")
            media_path = (
                media_row.get("relativePath")
                or media_row.get("relative_path")
                or media_row.get("file")
                or media_row.get("path")
                or ""
            )
            node_identity = asset_id
            if preferred_media_version_id or preferred_state_tag:
                node_identity = f"{asset_id}_{preferred_media_version_id or preferred_state_tag}"
            node_id = _safe_workflow_id(
                f"asset_image_{segment_id}_{asset_type}_{node_identity}{node_id_suffix}",
                f"asset_image_{lane_index + 1:03d}",
            )
            if node_id not in node_ids:
                node_data = {
                    "title": display_name,
                    "status": "ready" if media_row else "waiting",
                    "summary": str(asset.get("desc") or asset.get("description") or "资产参考图"),
                    "workChainId": work_chain_id,
                    "routeId": route_id,
                    "segmentId": segment_id,
                    "strategy": "asset_reference",
                    "visibilityScope": "workChain",
                    "sourceType": "asset",
                    "canvasNodeRole": _CANVAS_NODE_ROLE_IMAGE_ASSET,
                    "assetId": asset_id,
                    "assetType": asset_type,
                    "rootAssetId": asset_id,
                    "rootAssetType": asset_type,
                    "rootAssetProjectId": project_id,
                    "assetName": display_name,
                    "displayName": display_name,
                    "aliases": copy.deepcopy(aliases),
                    "mediaId": media_id,
                    "mediaVersionId": media_version_id,
                    "media": copy.deepcopy(media_row) if media_row else None,
                    "storage": copy.deepcopy(media_row) if media_row else None,
                    "assetLaneIndex": lane_index,
                    "cardState": {"size": {"width": 240, "height": 220}},
                    "provenance": {
                        "source": "agent",
                        "action": "shot_plan_asset_ref_resolved",
                    },
                }
                if preferred_state_tag:
                    node_data["stateTag"] = preferred_state_tag
                node_ids.add(node_id)
                nodes.append(
                    {
                        "id": node_id,
                        "type": "asset.image",
                        "position": {"x": 600 + (lane_index % 3) * 230, "y": 0},
                        "workChainId": work_chain_id,
                        "routeId": route_id,
                        "segmentId": segment_id,
                        "strategy": "asset_reference",
                        "data": node_data,
                    }
                )
                lane_index += 1
            link_id = _safe_workflow_id(f"link_{segment_id}_{node_id}_to_{target_node_id}_{target_slot}", f"link_asset_{len(input_links) + 1:03d}")
            input_links.append(
                {
                    "id": link_id,
                    "label": display_name,
                    "displayName": display_name,
                    "aliases": copy.deepcopy(aliases),
                    "sourceType": "asset",
                    "sourceId": node_id,
                    "sourceNodeId": node_id,
                    "sourceNodeType": "asset.image",
                    "sourceHandle": "asset_bottom",
                    "targetNodeId": target_node_id,
                    "targetNodeType": target_node_type,
                    "targetHandle": _WORKFLOW_ASSET_INPUT_HANDLE,
                    "targetSlot": target_slot,
                    "slot": target_slot,
                    "assetId": asset_id,
                    "assetType": asset_type,
                    "rootAssetId": asset_id,
                    "rootAssetType": asset_type,
                    "rootAssetProjectId": project_id,
                    "assetName": display_name,
                    "mediaId": media_id,
                    "mediaVersionId": media_version_id,
                    "mediaType": "image",
                    "path": media_path,
                    "workChainId": work_chain_id,
                    "routeId": route_id,
                    "segmentId": segment_id,
                    "status": "linked",
                    "visibilityScope": "workChain",
                }
            )
            if preferred_state_tag:
                input_links[-1]["stateTag"] = preferred_state_tag
            edges.append(
                {
                    "id": _safe_workflow_id(f"{node_id}_to_{target_node_id}_{target_slot}", f"edge_asset_{len(edges) + 1:03d}"),
                    "source": node_id,
                    "sourceHandle": "asset_bottom",
                    "target": target_node_id,
                    "targetHandle": _WORKFLOW_ASSET_INPUT_HANDLE,
                    "data": {
                        "kind": "material",
                        "role": target_slot,
                        "inputLinkId": link_id,
                        "sourceType": "asset",
                        "targetHandle": _WORKFLOW_ASSET_INPUT_HANDLE,
                        "sourceNodeType": "asset.image",
                        "targetNodeType": target_node_type,
                        "targetSlot": target_slot,
                        "workChainId": work_chain_id,
                        "routeId": route_id,
                        "segmentId": segment_id,
                    },
                }
            )
    return input_links, nodes, edges, missing


def _asset_ref_target_slot(asset_type: Any, fallback: str = "storyboard_image") -> str:
    normalized = str(asset_type or "").strip().lower()
    def slot_for(value: str) -> str:
        if value in {"character", "characters", "role", "roles", "person", "people", "角色", "人物"}:
            return "character_reference"
        if value in {"creature", "creatures", "monster", "monsters", "beast", "beasts", "生物", "怪物", "妖兽", "魔兽", "异兽"}:
            return "creature_reference"
        if value in {"scene", "scenes", "location", "locations", "setting", "场景", "地点"}:
            return "scene_reference"
        if value in {"prop", "props", "item", "items", "object", "objects", "道具", "物件"}:
            return "prop_reference"
        if value in {
            "storyboard",
            "storyboard_image",
            "image",
            _WORKFLOW_ASSET_INPUT_HANDLE,
            _WORKFLOW_VIDEO_INPUT_HANDLE,
            "分镜",
            "分镜图",
            "visual_reference",
        }:
            return "storyboard_image"
        if value in {"visual_handoff", "visual_handoff_reference", "handoff", "continuity", "视觉交接"}:
            return "visual_handoff_reference"
        return ""

    slot = slot_for(normalized)
    if slot:
        return slot
    fallback_text = str(fallback or "").strip()
    fallback_slot = slot_for(fallback_text.lower())
    if fallback_slot:
        return fallback_slot
    return fallback_text or "storyboard_image"


def _normalize_generated_workflow_material_edges(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    node_by_id = {str(node.get("id") or ""): node for node in nodes if isinstance(node, dict)}
    def source_handle_for_edge(
        edge: dict[str, Any],
        data: dict[str, Any],
        default_handle: str,
    ) -> str:
        requested = str(edge.get("sourceHandle") or data.get("sourceHandle") or "").strip()
        if requested in {default_handle, f"{default_handle}_bottom"}:
            return requested
        return default_handle

    def target_handle_for_edge(
        edge: dict[str, Any],
        data: dict[str, Any],
        target_type: str,
        target_slot: str,
        *,
        locked_storyboard_input: bool = False,
    ) -> str:
        requested = str(edge.get("targetHandle") or data.get("targetHandle") or "").strip()
        if requested in {_WORKFLOW_ASSET_INPUT_HANDLE, _WORKFLOW_VIDEO_INPUT_HANDLE}:
            return requested
        if target_type in {"director.board", "storyboard.card"}:
            return _WORKFLOW_ASSET_INPUT_HANDLE
        if target_type == "video.storyboard":
            if locked_storyboard_input and target_slot == "storyboard_image":
                return _WORKFLOW_VIDEO_INPUT_HANDLE
            return _WORKFLOW_ASSET_INPUT_HANDLE
        return requested or target_slot

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        edge["data"] = data
        source_node = node_by_id.get(str(edge.get("source") or ""))
        target_node = node_by_id.get(str(edge.get("target") or ""))
        source_type = str((source_node or {}).get("type") or data.get("sourceNodeType") or "").strip()
        target_type = str((target_node or {}).get("type") or data.get("targetNodeType") or "").strip()
        data["sourceNodeType"] = source_type
        data["targetNodeType"] = target_type
        is_material = str(data.get("kind") or "").strip() == "material"
        if not is_material:
            continue
        if source_type == "asset.image" and target_type in {"director.board", "storyboard.card"}:
            source_data = source_node.get("data") if isinstance((source_node or {}).get("data"), dict) else {}
            target_slot = _asset_ref_target_slot(
                source_data.get("assetType") or source_data.get("asset_type") or data.get("assetType"),
                data.get("targetSlot") or data.get("slot") or data.get("role"),
            )
            edge["sourceHandle"] = source_handle_for_edge(edge, data, "asset")
            edge["targetHandle"] = target_handle_for_edge(edge, data, target_type, target_slot)
            data["sourceType"] = "asset"
            data["role"] = target_slot
            data["targetHandle"] = edge["targetHandle"]
            data["targetSlot"] = target_slot
            data["slot"] = target_slot
            data["assetType"] = source_data.get("assetType") or source_data.get("asset_type") or data.get("assetType")
        elif source_type == "asset.image" and target_type == "video.storyboard":
            source_data = source_node.get("data") if isinstance((source_node or {}).get("data"), dict) else {}
            target_slot = _asset_ref_target_slot(
                source_data.get("assetType") or source_data.get("asset_type") or data.get("assetType"),
                data.get("targetSlot") or data.get("slot") or data.get("role"),
            )
            edge["sourceHandle"] = source_handle_for_edge(edge, data, "asset")
            edge["targetHandle"] = target_handle_for_edge(edge, data, target_type, target_slot)
            data["sourceType"] = "asset"
            data["role"] = target_slot
            data["targetHandle"] = edge["targetHandle"]
            data["targetSlot"] = target_slot
            data["slot"] = target_slot
            data["assetType"] = source_data.get("assetType") or source_data.get("asset_type") or data.get("assetType")
        elif source_type == "media.external":
            source_data = source_node.get("data") if isinstance((source_node or {}).get("data"), dict) else {}
            media = source_data.get("media") if isinstance(source_data.get("media"), dict) else source_data.get("storage")
            media = media if isinstance(media, dict) else {}
            media_kind = str(media.get("kind") or media.get("mediaType") or "").strip().lower()
            default_source_handle = "video" if media_kind == "video" or media_kind.startswith("video/") else "media"
            edge["sourceHandle"] = source_handle_for_edge(edge, data, default_source_handle)
            if target_type in {"director.board", "storyboard.card", "video.storyboard"}:
                target_slot = _asset_ref_target_slot(
                    data.get("assetType") or data.get("mediaPurpose") or data.get("preferredTargetSlot"),
                    data.get("targetSlot") or data.get("slot") or data.get("role"),
                )
                edge["targetHandle"] = target_handle_for_edge(edge, data, target_type, target_slot)
                data["targetHandle"] = edge["targetHandle"]
                data["targetSlot"] = target_slot
                data["slot"] = target_slot
        elif source_type == "storyboard.image":
            source_data = source_node.get("data") if isinstance((source_node or {}).get("data"), dict) else {}
            if str(source_data.get("canvasNodeRole") or source_data.get("canvas_node_role") or "").strip() == _CANVAS_NODE_ROLE_IMAGE_ASSET:
                edge["sourceHandle"] = source_handle_for_edge(edge, data, "image")
            else:
                edge["sourceHandle"] = "image"
            if target_type in {"director.board", "storyboard.card", "video.storyboard"}:
                target_slot = _asset_ref_target_slot(
                    data.get("assetType") or data.get("mediaPurpose") or data.get("preferredTargetSlot"),
                    data.get("targetSlot") or data.get("slot") or data.get("role"),
                )
                locked_reason = str(data.get("lockedReason") or edge.get("lockedReason") or "").strip()
                locked_storyboard_input = bool(data.get("locked") or edge.get("locked")) or locked_reason == "workflow_chain_storyboard_video_input"
                edge["targetHandle"] = target_handle_for_edge(
                    edge,
                    data,
                    target_type,
                    target_slot,
                    locked_storyboard_input=locked_storyboard_input,
                )
                data["targetHandle"] = edge["targetHandle"]
                data["targetSlot"] = target_slot
                data["slot"] = target_slot
        if edge.get("sourceHandle"):
            data["sourceHandle"] = edge["sourceHandle"]
