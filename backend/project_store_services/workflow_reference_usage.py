"""Per-consumer reference usage, independent of material associations."""
from __future__ import annotations

from typing import Any
import copy
import json

from .video_reference_metadata import video_reference_input_identity


def reference_identity(row: dict[str, Any]) -> str:
    """Consumer identity: distinguish assets, media versions and frame duties."""
    asset_id = str(row.get("rootAssetId") or row.get("assetId") or "")
    asset_type = str(row.get("rootAssetType") or row.get("assetType") or "")
    asset_type = {"character": "characters", "creature": "creatures", "scene": "scenes", "prop": "props"}.get(asset_type, asset_type)
    owner = [str(row.get("rootAssetProjectId") or ""), asset_type, asset_id] if asset_id else []
    return json.dumps([owner, video_reference_input_identity(row)], ensure_ascii=False, separators=(",", ":"))


def reference_usage_key(row: dict[str, Any]) -> str:
    return "identity:" + reference_identity(row)


def deduplicate_reference_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one effective row; retain source IDs to edit duplicate associations."""
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = reference_identity(row)
        previous = result.get(key)
        sources = list(dict.fromkeys([*(previous or {}).get("referenceSourceNodeIds", []),
                                     *row.get("referenceSourceNodeIds", []), str(row.get("sourceNodeId") or "")]))
        if previous is None or (previous.get("enabled") is False and row.get("enabled") is not False):
            result[key] = copy.deepcopy(row)
        result[key]["referenceIdentity"] = key
        result[key]["referenceSourceNodeIds"] = [source for source in sources if source]
    return list(result.values())


def reference_enabled(node: dict[str, Any], source_node_id: str, *, inherited: bool = True, row: dict[str, Any] | None = None) -> bool:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    usage = data.get("referenceUsage") if isinstance(data.get("referenceUsage"), dict) else {}
    value = usage.get(reference_usage_key(row), usage.get(source_node_id)) if row is not None else usage.get(source_node_id)
    return value if isinstance(value, bool) else inherited


def inherited_reference_enabled(workflow: dict[str, Any], link: dict[str, Any]) -> bool:
    nodes = {str(node.get("id") or ""): node for node in workflow.get("nodes", [])}
    source_id = str(link.get("sourceNodeId") or "")
    owner = nodes.get(str(link.get("inheritedFromNodeId") or ""), {})
    target = nodes.get(str(link.get("targetNodeId") or ""), {})
    enabled = reference_enabled(owner, source_id, row=link)
    if owner.get("type") == "director.board" and target.get("type") in {"video.storyboard", "video.keyframe"}:
        target_id = str(target.get("id") or "")
        image_ids = {
            str(edge.get("source") or "")
            for edge in workflow.get("edges", [])
            if isinstance(edge, dict) and str(edge.get("target") or "") == target_id
            and nodes.get(str(edge.get("source") or ""), {}).get("type") == "storyboard.image"
        }
        for image_id in image_ids:
            image = nodes[image_id]
            image_data = image.get("data") if isinstance(image.get("data"), dict) else {}
            card = nodes.get(str(image_data.get("sourceNodeId") or ""))
            if card and card.get("type") == "storyboard.card":
                enabled = enabled and reference_enabled(card, source_id, row=link)
                break
    return enabled


def input_reference_enabled(workflow: dict[str, Any], link: dict[str, Any]) -> bool:
    target = next((node for node in workflow.get("nodes", []) if node.get("id") == link.get("targetNodeId")), {})
    return inherited_reference_enabled(workflow, link) and reference_enabled(
        target, str(link.get("sourceNodeId") or ""), row=link)
