# -*- coding: utf-8 -*-
"""工作流节点、输入契约与保存校验领域。

本模块只依赖底层资产、画布所有权和规划契约；工作流服务层通过显式导入复用，
避免把节点契约继续堆在 workflows.py 中。
"""

from __future__ import annotations
from .canvas_ownership import VIDEO_TASK_NODE_TYPES
from utils.video_task_types import (
    CHARACTER_REPLACE_TASK, CHARACTER_REPLACE_INPUT_SLOTS,
    standalone_video_strategy,
)

from typing import Any
import re
import uuid


import copy
from utils.frame_references import (
    FRAME_IMAGE,
    FRAME_SLOT,
    frame_options,
    is_frame_image,
)
from utils.video_references import VIDEO_REFERENCE_SLOT
from .assets import _asset_name_key
from .canvas_ownership import (
    normalize_node_ownership,
    normalize_work_chain_origins,
    video_task_scope,
)
from .reference_utils import ASSET_REF_COLLECTIONS as _ASSET_REF_COLLECTIONS
from .planning_contract import _safe_workflow_id


_WORKFLOW_VIDEO_TASK_NODE_TYPES = VIDEO_TASK_NODE_TYPES

_WORKFLOW_VIDEO_TASK_SCOPE_WORK_CHAIN = "work_chain"

_WORKFLOW_VIDEO_TASK_SCOPE_STANDALONE = "standalone"

_WORKFLOW_VIDEO_MATERIAL_INPUT_SLOTS = {
    "custom_image",
    VIDEO_REFERENCE_SLOT,
    FRAME_SLOT,
    "character_reference",
    "creature_reference",
    "scene_reference",
    "prop_reference",
    "storyboard_image",
    "visual_handoff_reference",
}

_STANDALONE_VIDEO_GENERATION_CONFIG = {
    "strategy": "image_reference_video",
    "videoInputMode": "image_reference",
    "inputMode": "image_reference",
    "referenceMode": "image_reference",
}

_VISUAL_HANDOFF_SLOT = "visual_handoff_reference"

_WORKFLOW_MATERIAL_INPUT_SLOTS_BY_TARGET = {
    **{node_type: {
        "custom_image",
        FRAME_SLOT,
        "character_reference",
        "creature_reference",
        "scene_reference",
        "prop_reference",
        _VISUAL_HANDOFF_SLOT,
    } for node_type in ("director.board", "storyboard.card")},
    **dict.fromkeys(VIDEO_TASK_NODE_TYPES, _WORKFLOW_VIDEO_MATERIAL_INPUT_SLOTS),
    CHARACTER_REPLACE_TASK: CHARACTER_REPLACE_INPUT_SLOTS,
}

_CANVAS_NODE_ROLE_IMAGE_ASSET = "image_asset"

def _workflow_is_video_task_type(node_type: str) -> bool:
    return str(node_type or "").strip() in _WORKFLOW_VIDEO_TASK_NODE_TYPES

def _workflow_standalone_video_generation_config(base: Any = None) -> dict[str, Any]:
    config = copy.deepcopy(base) if isinstance(base, dict) else {}
    config.update(copy.deepcopy(_STANDALONE_VIDEO_GENERATION_CONFIG))
    return config

def _workflow_keyframe_video_generation_config(base: Any = None) -> dict[str, Any]:
    config = copy.deepcopy(base) if isinstance(base, dict) else {}
    config.update({
        "strategy": "native_keyframe_video",
        "videoInputMode": "native_keyframe",
        "inputMode": "native_keyframe",
        "referenceMode": "native_keyframe",
    })
    return config


def _workflow_character_replace_generation_config(base: Any = None) -> dict[str, Any]:
    config = copy.deepcopy(base) if isinstance(base, dict) else {}
    config.update({
        "strategy": "character_replace_video", "videoInputMode": "character_replace",
        "inputMode": "character_replace", "referenceMode": "character_replace",
    })
    config.setdefault("resolution", "768p")
    config.pop("aspectRatio", None)
    config.pop("aspect_ratio", None)
    config.setdefault("durationSeconds", 10)
    return config

def _workflow_standalone_video_payload(episode_id: str, title: str) -> dict[str, Any]:
    return {
        "episodeId": episode_id,
        "episodeTitle": str(episode_id or "").strip(),
        "title": str(title or "").strip(),
        "panelCount": 0,
        "routePanelCount": 0,
        "panels": [],
        "rawPrompts": [],
        "shotTimingPlan": {},
        "storyboardFormat": "video_task_card_direct",
        "storyboardPrompt": "",
        "storyboardImagePrompt": "",
        "prompt": {},
        "videoTaskCard": {"promptKind": "final_provider_prompt"},
        "videoInputMode": "image_reference",
        "referenceMode": "image_reference",
        "videoInputPlan": {
            "mode": "image_reference",
            "referenceMode": "image_reference",
            "requiredSlots": ["image_reference"],
        },
        "strategy": "image_reference_video",
        "source": "video_task_card",
    }

_WORKFLOW_GENERIC_OUTPUT_TITLES = {
    "生成版本",
    "分镜",
    "分镜图",
    "分镜图资产",
    "故事版分镜图",
    "当前分镜图",
    "视觉交接图",
    "视觉交接",
    "视频",
    "视频片段",
    "故事版视频",
    "最终视频",
    "当前视频",
}

_WORKFLOW_GENERIC_OUTPUT_TITLE_KEYS = {
    re.sub(r"\s+", "", item).lower()
    for item in _WORKFLOW_GENERIC_OUTPUT_TITLES
}

def _workflow_normalized_title_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()

def _workflow_meaningful_output_title(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if _workflow_normalized_title_key(text) in _WORKFLOW_GENERIC_OUTPUT_TITLE_KEYS:
        return ""
    return text

def _workflow_node_meaningful_title(
    workflow: dict[str, Any],
    node_id: str | None,
    *fallbacks: Any,
) -> str:
    node = _workflow_node(workflow, str(node_id or "").strip()) if node_id else None
    data = node.get("data") if isinstance((node or {}).get("data"), dict) else {}
    for value in (
        data.get("assetName"),
        data.get("title"),
        data.get("name"),
        (node or {}).get("title"),
        (node or {}).get("label"),
        *fallbacks,
    ):
        title = _workflow_meaningful_output_title(value)
        if title:
            return title
    return ""

def _workflow_generation_source_matches_task_type(node_type: str, task_type: str) -> bool:
    normalized_task_type = str(task_type or "").strip()
    normalized_node_type = str(node_type or "").strip()
    if normalized_task_type in {"storyboard_image", "storyboard_image_edit"}:
        return normalized_node_type == "storyboard.card"
    if normalized_task_type == "visual_handoff_image":
        return normalized_node_type in _VISUAL_HANDOFF_SOURCE_NODE_TYPES
    if normalized_task_type in {"storyboard_video", "route_video"}:
        return _workflow_is_video_task_type(node_type)
    return False

def _workflow_generation_source_node_id(
    workflow: dict[str, Any],
    result_node_id: str | None,
    task_type: str,
) -> str:
    target_id = str(result_node_id or "").strip()
    if not target_id:
        return ""
    result_node = _workflow_node(workflow, target_id) or {}
    data = result_node.get("data") if isinstance(result_node.get("data"), dict) else {}
    for value in (data.get("resultOfNodeId"), data.get("sourceNodeId")):
        source_id = str(value or "").strip()
        source_node = _workflow_node(workflow, source_id) if source_id else None
        source_type = str((source_node or {}).get("type") or "")
        if source_node and _workflow_generation_source_matches_task_type(source_type, task_type):
            return source_id
    for edge in workflow.get("edges", []):
        if not isinstance(edge, dict) or str(edge.get("target") or "").strip() != target_id:
            continue
        source_id = str(edge.get("source") or "").strip()
        source_node = _workflow_node(workflow, source_id) if source_id else None
        source_type = str((source_node or {}).get("type") or "")
        if source_node and _workflow_generation_source_matches_task_type(source_type, task_type):
            return source_id
    return ""

def _workflow_generated_output_title(
    workflow: dict[str, Any],
    node_id: str | None,
    task_type: str,
    *,
    fallback: Any = "",
) -> str:
    direct_title = _workflow_node_meaningful_title(workflow, node_id)
    if direct_title:
        return direct_title
    source_node_id = _workflow_generation_source_node_id(workflow, node_id, task_type)
    source_title = _workflow_node_meaningful_title(workflow, source_node_id)
    if source_title:
        return source_title
    return _workflow_meaningful_output_title(fallback)

def _workflow_is_blocked_canvas_node_type(node_type: str) -> bool:
    normalized = str(node_type or "").strip()
    blocked_exact = {
        "prompt.video",
        "video.edit",
        "video.extend",
        "video.merge",
        "clip.sequence",
        "timeline",
        "audio",
        "subtitle",
        "export",
        "delivery.package",
        "review.delivery",
    }
    blocked_prefixes = ("clip.", "timeline.", "audio.", "subtitle.", "export.", "delivery.", "review.")
    return normalized in blocked_exact or normalized.startswith(blocked_prefixes)

def _workflow_default_card_size(node_type: str) -> dict[str, int]:
    if node_type in {"asset.image", "media.external"}:
        return {"width": 240, "height": 300, "minWidth": 220, "minHeight": 220}
    if node_type == "storyboard.image":
        return {"width": 320, "height": 300, "minWidth": 280, "minHeight": 240}
    if node_type == "video.result":
        return {"width": 360, "height": 260, "minWidth": 320, "minHeight": 220}
    if _workflow_is_video_task_type(node_type):
        return {"width": 360, "height": 300, "minWidth": 320, "minHeight": 240}
    if node_type == "prompt.storyboard":
        return {"width": 340, "height": 280, "minWidth": 300, "minHeight": 240}
    if node_type == "director.board":
        return {"width": 380, "height": 360, "minWidth": 340, "minHeight": 300}
    if node_type == "source.text":
        return {"width": 460, "height": 560, "minWidth": 380, "minHeight": 420}
    return {"width": 320, "height": 360, "minWidth": 280, "minHeight": 260}

def _workflow_node_payload_data(node: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(node, dict):
        return {}
    data = node.get("data")
    return data if isinstance(data, dict) else {}

def _workflow_node_type_value(node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return ""
    return str(node.get("type") or _workflow_node_payload_data(node).get("eyebrow") or "").strip()

def _workflow_canvas_node_role(node: dict[str, Any] | None) -> str:
    data = _workflow_node_payload_data(node)
    return str(data.get("canvasNodeRole") or data.get("canvas_node_role") or "").strip()

def _workflow_node_is_visual_handoff_asset_like(node: dict[str, Any] | None) -> bool:
    node_type = _workflow_node_type_value(node)
    if node_type not in {"asset.image", "media.external"}:
        return False
    data = _workflow_node_payload_data(node)
    if any(
        str(data.get(key) or "").strip() in {"visual_handoff", _VISUAL_HANDOFF_SLOT}
        for key in ("mediaPurpose", "media_purpose", "preferredTargetSlot", "preferred_target_slot", "assetKind", "asset_kind", "assetType", "asset_type")
    ):
        return True
    return str(data.get("sourceType") or data.get("source_type") or "").strip() in {
        "visual_handoff_generation",
        "cross_episode_visual_handoff",
    }

def _workflow_node_is_independent_image_asset(node: dict[str, Any] | None) -> bool:
    return (
        _workflow_canvas_node_role(node) == _CANVAS_NODE_ROLE_IMAGE_ASSET
        and not _workflow_node_is_visual_handoff_asset_like(node)
    )

def _workflow_node_is_copied_asset(node: dict[str, Any] | None) -> bool:
    data = _workflow_node_payload_data(node)
    provenance = data.get("provenance") if isinstance(data.get("provenance"), dict) else {}
    return bool(
        data.get("copiedFromNodeId")
        or data.get("copied_from_node_id")
        or provenance.get("copiedFromNodeId")
        or provenance.get("copied_from_node_id")
        or provenance.get("action") == "canvas_asset_node_pasted"
    )

def _workflow_node_provenance(node: dict[str, Any] | None) -> dict[str, Any]:
    data = _workflow_node_payload_data(node)
    provenance = data.get("provenance")
    return provenance if isinstance(provenance, dict) else {}

def _workflow_is_standalone_task_node(node: dict[str, Any] | None) -> bool:
    return bool(node and video_task_scope(node) == "standalone")

def workflow_video_task_scope(
    workflow: dict[str, Any],
    node_or_id: dict[str, Any] | str | None,
) -> str:
    node = node_or_id if isinstance(node_or_id, dict) else _workflow_node(workflow, str(node_or_id or ""))
    return video_task_scope(node) if isinstance(node, dict) else ""

def workflow_node_is_default_work_chain_video_task(
    workflow: dict[str, Any],
    node_or_id: dict[str, Any] | str | None,
) -> bool:
    return workflow_video_task_scope(workflow, node_or_id) == _WORKFLOW_VIDEO_TASK_SCOPE_WORK_CHAIN

def _workflow_is_default_work_chain_storyboard_result(
    workflow: dict[str, Any],
    node: dict[str, Any] | None,
) -> bool:
    return bool(
        isinstance(node, dict)
        and _workflow_node_type_value(node) == "storyboard.image"
        and not _workflow_node_is_independent_image_asset(node)
        and _workflow_node_work_chain_id(workflow, node)
    )

def _workflow_is_default_work_chain_video_result(
    workflow: dict[str, Any],
    node: dict[str, Any] | None,
) -> bool:
    if not isinstance(node, dict) or _workflow_node_type_value(node) != "video.result":
        return False
    owner_node_id = _workflow_node_result_of_id(node)
    owner_node = _workflow_node(workflow, owner_node_id) if owner_node_id else None
    return bool(
        owner_node
        and workflow_node_is_default_work_chain_video_task(workflow, owner_node)
    )

def _workflow_node_result_of_id(node: dict[str, Any] | None) -> str:
    data = _workflow_node_payload_data(node)
    provenance = _workflow_node_provenance(node)
    return str(
        data.get("resultOfNodeId")
        or data.get("result_of_node_id")
        or provenance.get("resultOfNodeId")
        or provenance.get("result_of_node_id")
        or ""
    ).strip()

def _workflow_edge_is_director_storyboard_result(
    edge: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
) -> bool:
    if not isinstance(edge, dict):
        return False
    source_id = str(edge.get("source") or "").strip()
    target_id = str(edge.get("target") or "").strip()
    source_node = node_by_id.get(source_id)
    target_node = node_by_id.get(target_id)
    if (
        _workflow_node_type_value(source_node) != "storyboard.card"
        or _workflow_node_type_value(target_node) != "storyboard.image"
        or _workflow_node_is_independent_image_asset(target_node)
    ):
        return False
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    role = str(data.get("role") or "").strip()
    target_slot = str(data.get("targetSlot") or data.get("slot") or data.get("role") or "").strip()
    if role not in {"", "generates"} and target_slot not in {"", "generates"}:
        return False
    source_data = _workflow_node_payload_data(source_node)
    target_data = _workflow_node_payload_data(target_node)
    source_work_chain_id = str(source_node.get("workChainId") or source_data.get("workChainId") or "").strip() if isinstance(source_node, dict) else ""
    target_work_chain_id = str(target_node.get("workChainId") or target_data.get("workChainId") or "").strip() if isinstance(target_node, dict) else ""
    if not source_work_chain_id or source_work_chain_id != target_work_chain_id:
        return False
    source_route_id = str(source_node.get("routeId") or source_data.get("routeId") or "").strip() if isinstance(source_node, dict) else ""
    target_route_id = str(target_node.get("routeId") or target_data.get("routeId") or "").strip() if isinstance(target_node, dict) else ""
    return not source_route_id or not target_route_id or source_route_id == target_route_id

def _workflow_ensure_work_chain_storyboard_result_edges(
    workflow: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
) -> None:
    edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    workflow["edges"] = edges
    existing_pairs = {
        (str(edge.get("source") or "").strip(), str(edge.get("target") or "").strip())
        for edge in edges
        if isinstance(edge, dict)
    }

    def node_text(node: dict[str, Any] | None, key: str) -> str:
        if not isinstance(node, dict):
            return ""
        data = _workflow_node_payload_data(node)
        return str(node.get(key) or data.get(key) or "").strip()

    director_nodes = [
        node
        for node in node_by_id.values()
        if _workflow_node_type_value(node) == "storyboard.card"
    ]
    for target_node in node_by_id.values():
        target_id = str(target_node.get("id") or "").strip()
        if (
            not target_id
            or _workflow_node_type_value(target_node) != "storyboard.image"
            or _workflow_node_is_independent_image_asset(target_node)
        ):
            continue
        target_work_chain_id = node_text(target_node, "workChainId")
        target_route_id = node_text(target_node, "routeId")
        if not target_work_chain_id:
            continue
        if any(
            target == target_id and _workflow_node_type_value(node_by_id.get(source)) == "storyboard.card"
            for source, target in existing_pairs
        ):
            continue
        director_node = next(
            (
                node
                for node in director_nodes
                if node_text(node, "workChainId") == target_work_chain_id
                and (
                    not target_route_id
                    or not node_text(node, "routeId")
                    or node_text(node, "routeId") == target_route_id
                )
            ),
            None,
        )
        if not director_node:
            continue
        source_id = str(director_node.get("id") or "").strip()
        if not source_id or (source_id, target_id) in existing_pairs:
            continue
        route_id = target_route_id or node_text(director_node, "routeId")
        segment_id = node_text(target_node, "segmentId") or node_text(director_node, "segmentId")
        edge = {
            "id": f"dependency-{source_id}-{target_id}-generates",
            "source": source_id,
            "target": target_id,
            "sourceHandle": "storyboard",
            "targetHandle": "generates",
            "deletable": False,
            "data": {
                "kind": "dependency",
                "role": "generates",
                "sourceNodeType": "storyboard.card",
                "targetNodeType": "storyboard.image",
                "targetSlot": "generates",
                "slot": "generates",
                "workChainId": target_work_chain_id,
                "routeId": route_id,
                "segmentId": segment_id,
                "locked": True,
                "preserveOnReplan": True,
                "lockedReason": "task_result_edge",
            },
        }
        edges.append(edge)
        existing_pairs.add((source_id, target_id))

def _workflow_is_result_node_type(node_type: str) -> bool:
    return node_type == "storyboard.image" or node_type == "video.result"

def _workflow_node_owns_generation_config(node_type: str) -> bool:
    normalized = str(node_type or "").strip()
    return normalized in {"director.board", "storyboard.card"} or _workflow_is_video_task_type(normalized)

def _workflow_protected_node_delete_reason(node: dict[str, Any] | None) -> str:
    node_type = _workflow_node_type_value(node)
    if node_type == "source.text":
        if ((node or {}).get("data") or {}).get("sourceMode") == "independent":
            return ""
        return "分集原文是画布来源，不能单独删除"
    if _workflow_is_standalone_task_node(node):
        return ""
    if node_type == "prompt.storyboard":
        return "片段剧本不能直接删除"
    if node_type == "director.board":
        return "分镜脚本不能直接删除"
    if node_type == "storyboard.card":
        return "分镜单元不能直接删除"
    if _workflow_is_video_task_type(node_type):
        return "视频生成不能直接删除"
    if node_type == "video.result" and not _workflow_node_is_copied_asset(node):
        return "视频片段不能直接删除"
    if (
        node_type == "storyboard.image"
        and not _workflow_node_is_independent_image_asset(node)
        and _node_work_chain_id(node or {})
    ):
        return "分镜图不能直接删除"
    return ""

def _workflow_task_result_edge_key(edge: dict[str, Any], node_by_id: dict[str, dict[str, Any]]) -> tuple[str, str, str] | None:
    if not isinstance(edge, dict):
        return None
    source_id = str(edge.get("source") or "").strip()
    target_id = str(edge.get("target") or "").strip()
    source_type = str((edge.get("data") if isinstance(edge.get("data"), dict) else {}).get("sourceNodeType") or "").strip()
    target_type = str((edge.get("data") if isinstance(edge.get("data"), dict) else {}).get("targetNodeType") or "").strip()
    source_type = source_type or _workflow_node_type_value(node_by_id.get(source_id))
    target_type = target_type or _workflow_node_type_value(node_by_id.get(target_id))
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    role = str(data.get("role") or "").strip()
    target_slot = str(data.get("targetSlot") or data.get("slot") or data.get("role") or "").strip()
    if source_type == "storyboard.card" and target_type == "storyboard.image":
        target_node = node_by_id.get(target_id)
        if not _workflow_edge_is_director_storyboard_result(edge, node_by_id):
            return None
        if role in {"", "generates"} or target_slot in {"", "generates"}:
            return (source_id, target_id, "generates")
    if _workflow_is_video_task_type(source_type) and target_type == "video.result":
        if role in {"", "generates"} or target_slot in {"", "generates", "video_result"}:
            return (source_id, target_id, "generates")
    return None

def _workflow_source_storyboard_edge_key(edge: dict[str, Any], node_by_id: dict[str, dict[str, Any]]) -> tuple[str, str, str] | None:
    if not isinstance(edge, dict):
        return None
    source_id = str(edge.get("source") or "").strip()
    target_id = str(edge.get("target") or "").strip()
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    source_type = str(data.get("sourceNodeType") or "").strip()
    target_type = str(data.get("targetNodeType") or "").strip()
    source_type = source_type or _workflow_node_type_value(node_by_id.get(source_id))
    target_type = target_type or _workflow_node_type_value(node_by_id.get(target_id))
    role = str(data.get("role") or "").strip()
    target_slot = str(data.get("targetSlot") or data.get("slot") or data.get("role") or "").strip()
    if source_type == "source.text" and target_type == "prompt.storyboard":
        if role in {"", "context"} or target_slot in {"", "story"}:
            return (source_id, target_id, "source_storyboard")
    return None

def _workflow_storyboard_director_edge_key(edge: dict[str, Any], node_by_id: dict[str, dict[str, Any]]) -> tuple[str, str, str] | None:
    if not isinstance(edge, dict):
        return None
    source_id = str(edge.get("source") or "").strip()
    target_id = str(edge.get("target") or "").strip()
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    source_type = str(data.get("sourceNodeType") or "").strip()
    target_type = str(data.get("targetNodeType") or "").strip()
    source_type = source_type or _workflow_node_type_value(node_by_id.get(source_id))
    target_type = target_type or _workflow_node_type_value(node_by_id.get(target_id))
    role = str(data.get("role") or "").strip()
    target_slot = str(data.get("targetSlot") or data.get("slot") or data.get("role") or "").strip()
    if source_type == "prompt.storyboard" and target_type == "director.board":
        if role in {"", "context", "generates"} or target_slot in {"", "story", "script"}:
            return (source_id, target_id, "storyboard_director")
    if source_type == "director.board" and target_type == "storyboard.card":
        if role in {"", "context"} or target_slot in {"", "story"}:
            return (source_id, target_id, "director_storyboard_card")
    return None

def _workflow_visual_handoff_edge_key(edge: dict[str, Any], node_by_id: dict[str, dict[str, Any]]) -> tuple[str, str, str] | None:
    if not isinstance(edge, dict):
        return None
    source_id = str(edge.get("source") or "").strip()
    target_id = str(edge.get("target") or "").strip()
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    source_type = str(data.get("sourceNodeType") or "").strip()
    target_type = str(data.get("targetNodeType") or "").strip()
    source_type = source_type or _workflow_node_type_value(node_by_id.get(source_id))
    target_type = target_type or _workflow_node_type_value(node_by_id.get(target_id))
    role = str(data.get("role") or "").strip()
    target_slot = str(data.get("targetSlot") or data.get("slot") or data.get("role") or "").strip()
    target_node = node_by_id.get(target_id)
    target_data = _workflow_node_payload_data(target_node)
    media_purpose = str(
        target_data.get("mediaPurpose")
        or target_data.get("preferredTargetSlot")
        or target_data.get("assetKind")
        or ""
    ).strip()
    if source_type == "storyboard.card" and target_type == "asset.image" and media_purpose == "visual_handoff":
        if role in {"", "generates", "dependency"} or target_slot in {"", "asset_context", "visual_handoff"}:
            return (source_id, target_id, "visual_handoff")
    return None

def _workflow_storyboard_video_edge_key(
    edge: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    workflow: dict[str, Any] | None = None,
) -> tuple[str, str, str] | None:
    if not isinstance(edge, dict):
        return None
    source_id = str(edge.get("source") or "").strip()
    target_id = str(edge.get("target") or "").strip()
    source_node = node_by_id.get(source_id)
    target_node = node_by_id.get(target_id)
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    source_type = str(data.get("sourceNodeType") or "").strip() or _workflow_node_type_value(source_node)
    target_type = str(data.get("targetNodeType") or "").strip() or _workflow_node_type_value(target_node)
    if source_type != "storyboard.image" or not _workflow_is_video_task_type(target_type):
        return None
    if _workflow_node_is_independent_image_asset(source_node):
        return None
    source_work_chain_id = _node_work_chain_id(source_node or {})
    target_work_chain_id = _node_work_chain_id(target_node or {})
    if (
        not source_work_chain_id
        or source_work_chain_id != target_work_chain_id
        or workflow_video_task_scope(workflow or {"nodes": list(node_by_id.values())}, target_node)
        != _WORKFLOW_VIDEO_TASK_SCOPE_WORK_CHAIN
    ):
        return None
    source_route_id = _node_route_id(source_node or {})
    target_route_id = _node_route_id(target_node or {})
    if source_route_id and target_route_id and source_route_id != target_route_id:
        return None
    edge_kind = str(data.get("kind") or "").strip()
    if edge_kind and edge_kind != "material":
        return None
    if _canonical_workflow_slot(data.get("targetSlot") or data.get("role"), "") != "storyboard_image":
        return None
    return (source_id, target_id, "storyboard_video")

def _workflow_locked_system_edge_key(
    edge: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    workflow: dict[str, Any] | None = None,
) -> tuple[str, str, str] | None:
    return (
        _workflow_source_storyboard_edge_key(edge, node_by_id)
        or _workflow_storyboard_director_edge_key(edge, node_by_id)
        or _workflow_task_result_edge_key(edge, node_by_id)
        or _workflow_storyboard_video_edge_key(edge, node_by_id, workflow)
        or _workflow_visual_handoff_edge_key(edge, node_by_id)
    )

def _workflow_protected_edge_delete_reason(
    edge: dict[str, Any] | None,
    node_by_id: dict[str, dict[str, Any]],
    workflow: dict[str, Any] | None = None,
) -> str:
    if isinstance(edge, dict) and _workflow_locked_system_edge_key(edge, node_by_id, workflow):
        return "锁定链接不能删除"
    return ""

def _assert_user_workflow_save_keeps_protected_items(
    previous_workflow: dict[str, Any],
    next_workflow: dict[str, Any],
) -> None:
    if not isinstance(previous_workflow, dict) or not previous_workflow:
        return
    previous_nodes = previous_workflow.get("nodes") if isinstance(previous_workflow.get("nodes"), list) else []
    next_nodes = next_workflow.get("nodes") if isinstance(next_workflow.get("nodes"), list) else []
    next_node_ids = {
        str(node.get("id") or "").strip()
        for node in next_nodes
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }
    previous_node_by_id = {
        str(node.get("id") or "").strip(): node
        for node in previous_nodes
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }
    removed_node_ids = set(previous_node_by_id) - next_node_ids
    allowed_removed_node_ids = {
        node_id
        for node_id in removed_node_ids
        if _workflow_is_standalone_task_node(previous_node_by_id.get(node_id))
    }
    for node in previous_nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        reason = _workflow_protected_node_delete_reason(node)
        if reason and node_id and node_id not in next_node_ids:
            result_of_node_id = _workflow_node_result_of_id(node)
            if (
                _workflow_is_result_node_type(_workflow_node_type_value(node))
                and result_of_node_id in allowed_removed_node_ids
            ):
                allowed_removed_node_ids.add(node_id)
                continue
            raise ValueError(reason)

    next_node_by_id = {
        str(node.get("id") or "").strip(): node
        for node in next_nodes
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }
    next_edge_keys = {
        key
        for edge in (next_workflow.get("edges") if isinstance(next_workflow.get("edges"), list) else [])
        if isinstance(edge, dict)
        for key in [_workflow_locked_system_edge_key(edge, next_node_by_id, next_workflow)]
        if key
    }
    previous_edges = previous_workflow.get("edges") if isinstance(previous_workflow.get("edges"), list) else []
    for edge in previous_edges:
        if not isinstance(edge, dict):
            continue
        key = _workflow_locked_system_edge_key(edge, previous_node_by_id, previous_workflow)
        if key and key not in next_edge_keys:
            source_id, target_id, _role = key
            if source_id in allowed_removed_node_ids and target_id in allowed_removed_node_ids:
                continue
            if key[2] == "source_storyboard" and target_id in allowed_removed_node_ids:
                continue
            raise ValueError("锁定链接不能删除")

def _ensure_saved_workflow_node_contract(node: dict[str, Any]) -> None:
    node_id = str(node.get("id") or "").strip()
    node_type = str(node.get("type") or "")
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    node["data"] = data
    if node_id:
        data["nodeId"] = node_id
    if node_type:
        data["eyebrow"] = node_type
    for key in ("workChainId", "routeId", "segmentId", "strategy"):
        if key == "workChainId":
            normalize_node_ownership(node)
            continue
        if node.get(key) is None and data.get(key) is not None:
            node[key] = data.get(key)
        elif key not in node:
            node[key] = data.get(key) or ""
        if data.get(key) is None:
            data[key] = node.get(key) or ""
        else:
            data.setdefault(key, node.get(key) or "")
    data.setdefault("title", node.get("id") or node_type or "工作流节点")
    data.setdefault("status", "idle")
    data.setdefault("summary", "")
    for key, fallback in (
        ("assetRefs", {}),
        ("prompt", {}),
        ("referenceMediaIds", []),
        ("inputLinks", []),
        ("resultOfNodeId", ""),
    ):
        if data.get(key) is None:
            data[key] = copy.deepcopy(fallback)
        else:
            data.setdefault(key, copy.deepcopy(fallback))
    if _workflow_node_owns_generation_config(node_type):
        for key, fallback in (
            ("generationConfig", {}),
            ("modelSelection", {}),
            ("capabilityRequirements", {}),
            ("capabilityCheck", {}),
        ):
            if data.get(key) is None:
                data[key] = copy.deepcopy(fallback)
            else:
                data.setdefault(key, copy.deepcopy(fallback))
    else:
        for key in ("generationConfig", "modelSelection", "capabilityRequirements", "capabilityCheck"):
            data.pop(key, None)
    if _workflow_is_video_task_type(node_type):
        if video_task_scope(node) == _WORKFLOW_VIDEO_TASK_SCOPE_STANDALONE:
            keyframe_task = node_type == "video.keyframe"
            strategy = standalone_video_strategy(node_type)
            node["strategy"] = strategy
            data["strategy"] = strategy
            data["generationConfig"] = (
                _workflow_keyframe_video_generation_config(data.get("generationConfig"))
                if keyframe_task else _workflow_character_replace_generation_config(data.get("generationConfig"))
                if node_type == CHARACTER_REPLACE_TASK else _workflow_standalone_video_generation_config(data.get("generationConfig"))
            )
    card_state = data.get("cardState") if isinstance(data.get("cardState"), dict) else {}
    size = card_state.get("size") if isinstance(card_state.get("size"), dict) else {}
    for key, value in _workflow_default_card_size(node_type).items():
        size.setdefault(key, value)
    card_state["size"] = size
    data["cardState"] = card_state
    delete_reason = _workflow_protected_node_delete_reason(node)
    if node_type == "source.text" and data.get("sourceMode") == "independent":
        node["deletable"] = data["deletable"] = True
    if delete_reason:
        node["deletable"] = False
        data["deletable"] = False
        data.setdefault("lockedReason", delete_reason)
    if _workflow_is_result_node_type(node_type):
        data.setdefault("assetScope", "result")
        if node_type == "video.result":
            data.setdefault("assetKind", "video")
        else:
            data.setdefault("assetKind", "storyboard_image")
    elif node_type in {"asset.image", "media.external"}:
        if _workflow_node_is_visual_handoff_asset_like(node):
            data["assetScope"] = "result"
            data.setdefault("mediaPurpose", "visual_handoff")
            data.setdefault("preferredTargetSlot", _VISUAL_HANDOFF_SLOT)
            data.setdefault("assetKind", "visual_handoff")
            data.setdefault("assetType", "visual_handoff")
            data.pop("canvasNodeRole", None)
            data.pop("canvas_node_role", None)
        else:
            data.setdefault("assetScope", "reusable")
            data["canvasNodeRole"] = _CANVAS_NODE_ROLE_IMAGE_ASSET
            data.pop("canvas_node_role", None)

def _workflow_continuity_value(value: Any, shot_ids: list[str] | None = None) -> str:
    text = str(value or "").strip().lower()
    if text in {"continuous", "single_shot", "manual"}:
        return text
    if text in {"single", "single-shot", "single_shot", "shot"}:
        return "single_shot"
    if text in {"manual", "custom"}:
        return "manual"
    if shot_ids is not None and len(shot_ids) <= 1:
        return "single_shot"
    return "continuous"

def _workflow_chain_route_ids(chain: dict[str, Any] | None) -> list[str]:
    if not isinstance(chain, dict):
        return []
    route_ids: list[str] = []
    seen: set[str] = set()
    for key in ("routeIds", "route_ids"):
        values = chain.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            text = str(item or "").strip()
            if text and text not in seen:
                seen.add(text)
                route_ids.append(text)
    return route_ids

def _normalize_workflow_work_chain_route_fields(workflow: dict[str, Any]) -> None:
    for node in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
        if not isinstance(node, dict):
            continue
        data = node.get("data")
        if isinstance(data, dict) and data.get("nodeId") and data["nodeId"] != node.get("id"):
            data["nodeId"] = node.get("id")
    work_chains = workflow.get("workChains") if isinstance(workflow.get("workChains"), list) else []
    for chain in work_chains:
        if not isinstance(chain, dict):
            continue
        chain["routeIds"] = _workflow_chain_route_ids(chain)
        chain.pop("route_ids", None)

def _ensure_saved_workflow_chain_contract(chain: dict[str, Any], index: int) -> None:
    chain_id = str(chain.get("id") or f"chain_{index + 1:03d}")
    chain["id"] = chain_id
    chain.setdefault("label", chain.get("title") or f"第 {index + 1} 条工作链")
    chain.setdefault("title", chain.get("label") or f"工作链 {index + 1}")
    shot_ids = [str(item) for item in chain.get("shotIds") or [] if str(item)]
    segment_ids = [str(item) for item in chain.get("segmentIds") or [] if str(item)]
    route_ids = _workflow_chain_route_ids(chain)
    chain["continuity"] = _workflow_continuity_value(chain.get("continuity"), shot_ids)
    chain["segmentIds"] = segment_ids
    chain["shotIds"] = shot_ids
    chain["routeIds"] = route_ids
    chain.pop("route_ids", None)
    chain["order"] = int(chain.get("order") or index + 1)
    layout = chain.get("layout") if isinstance(chain.get("layout"), dict) else {}
    layout.setdefault("y", 120 + index * 200)
    layout.setdefault("height", max(280, max(1, len(route_ids)) * 200))
    chain["layout"] = layout
    chain.setdefault("status", "draft")

def _workflow_string_list(value: Any) -> list[str]:
    result: list[str] = []
    for item in value if isinstance(value, list) else []:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result

def _workflow_add_unique(values: list[str], value: str) -> list[str]:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)
    return values

def _workflow_node_text(node: dict[str, Any] | None, key: str) -> str:
    if not isinstance(node, dict):
        return ""
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(node.get(key) or data.get(key) or "").strip()

def _workflow_default_handle(node_type: str, *, direction: str, edge_kind: str, role: str) -> str:
    node_type = str(node_type or "").strip()
    role = str(role or "").strip()
    if direction == "source":
        if node_type == "source.text":
            return "output"
        if node_type == "director.board":
            return "plan"
        if node_type == "storyboard.card":
            return "storyboard"
        if node_type == "prompt.storyboard":
            return "prompt"
        if _workflow_is_video_task_type(node_type):
            return "video"
        if node_type == "asset.image":
            return "asset"
        if node_type == "media.external":
            return "media"
        if node_type == "storyboard.image":
            return "image"
        if node_type == "video.result":
            return "video"
        return "output"
    if edge_kind == "material":
        return role or "input"
    if role == "generates":
        return "generates"
    if node_type == "prompt.storyboard":
        return "prompt"
    if _workflow_is_video_task_type(node_type):
        return "prompt"
    if node_type in {"storyboard.image", "director.board", "storyboard.card"}:
        return "story"
    return "input"

def _workflow_material_source_default_handle(source_node: dict[str, Any] | None) -> str:
    node_type = _workflow_node_type_value(source_node)
    if node_type == "asset.image":
        return "asset"
    if node_type == "media.external":
        return "video" if _workflow_node_media_kind(source_node) == "video" else "media"
    if node_type == "storyboard.image":
        return "image"
    if node_type == "video.result":
        return "video"
    return ""

def _workflow_material_source_handle(
    source_node: dict[str, Any] | None,
    requested_handle: Any = "",
) -> str:
    default_handle = _workflow_material_source_default_handle(source_node)
    if not default_handle:
        return ""
    requested = str(requested_handle or "").strip()
    if not requested:
        return default_handle
    allowed_handles = {default_handle, f"{default_handle}_bottom"}
    if (
        _workflow_node_type_value(source_node) == "storyboard.image"
        and not _workflow_node_is_independent_image_asset(source_node)
    ):
        allowed_handles = {default_handle}
    if requested in allowed_handles:
        return requested
    return default_handle

def _workflow_input_handle_kind(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    normalized = re.sub(r"[\s:-]+", "_", normalized).strip("_").lower()
    if not normalized:
        return ""

    def matches(handle: str) -> bool:
        return (
            normalized == handle
            or normalized.startswith(f"{handle}_")
            or normalized.endswith(f"_{handle}")
            or f"_{handle}_" in normalized
        )

    if matches(_WORKFLOW_ASSET_INPUT_HANDLE):
        return _WORKFLOW_ASSET_INPUT_HANDLE
    if matches(_WORKFLOW_VIDEO_INPUT_HANDLE):
        return _WORKFLOW_VIDEO_INPUT_HANDLE
    return ""

def _workflow_material_target_handle(
    target_node: dict[str, Any] | None,
    slot: str,
    requested_handle: Any = "",
    *,
    workflow: dict[str, Any] | None = None,
    locked_storyboard_video_input: bool = False,
) -> str:
    requested = str(requested_handle or "").strip()
    if requested:
        return requested
    if locked_storyboard_video_input and slot == "storyboard_image":
        return _WORKFLOW_VIDEO_INPUT_HANDLE
    return _WORKFLOW_ASSET_INPUT_HANDLE

def _workflow_edge_default_source_type(source_node_type: str) -> str:
    source_node_type = str(source_node_type or "").strip()
    if source_node_type == "asset.image":
        return "asset"
    if source_node_type == "media.external":
        return "external_media"
    if source_node_type == "storyboard.image":
        return "generated_media"
    if source_node_type == "video.result":
        return "generated_video"
    return "asset"

def _workflow_is_material_source_type(node_type: str) -> bool:
    node_type = str(node_type or "").strip()
    return (
        node_type == "video.result"
        or _workflow_is_asset_reference_type(node_type)
        or _workflow_is_external_media_type(node_type)
        or _workflow_is_generated_reference_type(node_type)
    )

def _workflow_is_asset_reference_type(node_type: str) -> bool:
    return str(node_type or "").strip() == "asset.image"

def _workflow_is_external_media_type(node_type: str) -> bool:
    return str(node_type or "").strip() == "media.external"

def _workflow_is_generated_reference_type(node_type: str) -> bool:
    node_type = str(node_type or "").strip()
    return node_type == "storyboard.image"

def _workflow_generated_reference_target_slot(node_type: str) -> str:
    node_type = str(node_type or "").strip()
    if node_type == "storyboard.image":
        return "storyboard_image"
    return ""

def _workflow_generated_reference_target_slot_for_target(node_type: str, target_node_type: str) -> str:
    normalized_node_type = str(node_type or "").strip()
    if str(target_node_type or "").strip() == "prompt.storyboard" and normalized_node_type == "storyboard.image":
        return "storyboard_image"
    return _workflow_generated_reference_target_slot(normalized_node_type)

_WORKFLOW_IMAGE_REFERENCE_FILE_RE = re.compile(r"\.(png|jpe?g|webp|gif|bmp|tiff?|avif)(?:[?#].*)?$", re.I)

_WORKFLOW_VIDEO_REFERENCE_FILE_RE = re.compile(r"\.(mp4|m4v|mov|webm|avi|mkv)(?:[?#].*)?$", re.I)

def _workflow_media_reference_path(*records: Any) -> str:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in (
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
        ):
            text = str(record.get(key) or "").strip()
            if text:
                return text
    return ""

def _workflow_media_reference_kind(*records: Any) -> str:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in (
            "mediaKind",
            "media_kind",
            "mediaType",
            "media_type",
            "kind",
            "mimeType",
            "mime_type",
        ):
            text = str(record.get(key) or "").strip().lower()
            if text == "video" or text.startswith("video/"):
                return "video"
            if text == "image" or text.startswith("image/"):
                return "image"
    path = _workflow_media_reference_path(*records)
    if _WORKFLOW_VIDEO_REFERENCE_FILE_RE.search(path):
        return "video"
    if _WORKFLOW_IMAGE_REFERENCE_FILE_RE.search(path):
        return "image"
    return ""

def _workflow_node_media_reference_kind(node: dict[str, Any] | None) -> str:
    data = node.get("data") if isinstance((node or {}).get("data"), dict) else {}
    media = data.get("media") if isinstance(data.get("media"), dict) else {}
    storage = data.get("storage") if isinstance(data.get("storage"), dict) else {}
    return _workflow_media_reference_kind(data, media, storage)

def _workflow_node_media_kind(node: dict[str, Any] | None) -> str:
    value = _workflow_node_media_reference_kind(node)
    if value in {"video", "image"}:
        return value
    return "image"

def _workflow_media_purpose_target_slot(purpose: Any) -> str:
    value = str(purpose or "").strip()
    if value == "custom_image":
        return value
    if value == FRAME_IMAGE:
        return FRAME_SLOT
    if value == "visual_handoff":
        return _VISUAL_HANDOFF_SLOT
    if value == "storyboard_image":
        return value
    return ""

def _workflow_media_purpose_material_slot(purpose: Any) -> str:
    value = str(purpose or "").strip()
    if value == "custom_image":
        return value
    if value == FRAME_IMAGE:
        return FRAME_SLOT
    if value == "visual_handoff":
        return _VISUAL_HANDOFF_SLOT
    if value == "visual_reference":
        return "storyboard_image"
    if value in {"character_reference", "creature_reference", "scene_reference", "prop_reference", "storyboard_image"}:
        return value
    return ""

def _workflow_asset_type_from_media_purpose(purpose: Any) -> str:
    value = str(purpose or "").strip()
    if value == "custom_image":
        return value
    if value == "video":
        return "video"
    if value == FRAME_IMAGE:
        return FRAME_IMAGE
    if value == "character_reference":
        return "characters"
    if value == "creature_reference":
        return "creatures"
    if value == "scene_reference":
        return "scenes"
    if value == "prop_reference":
        return "props"
    if value in {"storyboard_image", "visual_reference"}:
        return "storyboard_image"
    if value == "visual_handoff":
        return "visual_handoff"
    return ""

def _workflow_project_asset_type_from_media_purpose(purpose: Any) -> str:
    asset_type = _workflow_asset_type_from_media_purpose(purpose)
    return asset_type if asset_type in {"characters", "creatures", "scenes", "props"} else ""

def _workflow_media_purpose_label(purpose: Any) -> str:
    value = str(purpose or "").strip()
    if value == "custom_image":
        return "自定义图片"
    if value == "video":
        return "视频"
    if value == FRAME_IMAGE:
        return "帧画面"
    if value == "character_reference":
        return "角色"
    if value == "creature_reference":
        return "生物"
    if value == "scene_reference":
        return "场景"
    if value == "prop_reference":
        return "道具"
    if value in {"storyboard_image", "visual_reference"}:
        return "分镜图"
    if value == "visual_handoff":
        return "视觉交接"
    return "资产"

def _workflow_project_asset_name_exists(
    project_assets: Any,
    asset_type: str,
    name: Any,
) -> bool:
    rows = project_assets.get(asset_type) if isinstance(project_assets, dict) else []
    target = _asset_name_key(name)
    if not target or not isinstance(rows, list):
        return False
    return any(
        isinstance(row, dict) and _asset_name_key(row.get("name") or row.get("title")) == target
        for row in rows
    )

def _workflow_is_material_target_type(node_type: str) -> bool:
    node_type = str(node_type or "").strip()
    return node_type in {"director.board", "storyboard.card"} or _workflow_is_video_task_type(node_type)

def _workflow_edge_is_material_pair(source_node_type: str, target_node_type: str) -> bool:
    source_node_type = str(source_node_type or "").strip()
    target_node_type = str(target_node_type or "").strip()
    if source_node_type == "video.result":
        return _workflow_is_video_task_type(target_node_type)
    if _workflow_is_asset_reference_type(source_node_type):
        return _workflow_is_material_target_type(target_node_type)
    if _workflow_is_external_media_type(source_node_type):
        return _workflow_is_material_target_type(target_node_type)
    if _workflow_is_generated_reference_type(source_node_type):
        return _workflow_is_material_target_type(target_node_type)
    return False

def _workflow_edge_is_forbidden_image_link(source_node_type: str, target_node_type: str) -> bool:
    return _workflow_is_material_source_type(source_node_type) and not _workflow_edge_is_material_pair(source_node_type, target_node_type)

def _workflow_edge_looks_material(source_node_type: str, target_node_type: str, data: dict[str, Any]) -> bool:
    if not _workflow_edge_is_material_pair(source_node_type, target_node_type):
        return False
    if data.get("inputLinkId") or data.get("targetSlot") or data.get("sourceType"):
        return True
    return True

def _ensure_saved_workflow_route_contract(
    workflow: dict[str, Any],
    route: dict[str, Any],
    index: int,
    route_to_chain_id: dict[str, str],
) -> None:
    route_id = str(route.get("id") or f"route_{index + 1:03d}").strip()
    route["id"] = route_id
    route_nodes = [
        node
        for node in workflow.get("nodes") or []
        if isinstance(node, dict) and _workflow_node_text(node, "routeId") == route_id
    ]
    work_chain_id = str(route.get("workChainId") or route.get("work_chain_id") or route_to_chain_id.get(route_id) or "").strip()
    segment_id = str(route.get("segmentId") or route.get("segment_id") or "").strip()
    strategy = str(route.get("strategy") or route.get("generationStrategy") or "").strip()
    for node in route_nodes:
        work_chain_id = work_chain_id or _workflow_node_text(node, "workChainId")
        segment_id = segment_id or _workflow_node_text(node, "segmentId")
        strategy = strategy or _workflow_node_text(node, "strategy")
    route["workChainId"] = work_chain_id
    route["segmentId"] = segment_id
    route["strategy"] = strategy or "storyboard_multi_shot"
    route.setdefault("label", route.get("title") or f"路线 {index + 1}")
    route.setdefault("title", route.get("label") or f"路线 {index + 1}")
    route.setdefault("status", "draft")
    route.setdefault("locked", False)
    route.setdefault("preserveOnReplan", False)
    route["shotIds"] = _workflow_string_list(route.get("shotIds") or route.get("shot_ids"))
    if not route["shotIds"]:
        for node in route_nodes:
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            route["shotIds"] = _workflow_add_unique(route["shotIds"], str(data.get("shotId") or node.get("shotId") or ""))
    try:
        route["shotCount"] = int(route.get("shotCount") or route.get("shot_count") or len(route["shotIds"]) or max(1, len(route_nodes)))
    except (TypeError, ValueError):
        route["shotCount"] = len(route["shotIds"]) or max(1, len(route_nodes))

def _ensure_saved_workflow_edge_contract(
    edge: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    workflow: dict[str, Any] | None = None,
) -> None:
    source_id = str(edge.get("source") or "").strip()
    target_id = str(edge.get("target") or "").strip()
    source_node = node_by_id.get(source_id)
    target_node = node_by_id.get(target_id)
    source_type = str((source_node or {}).get("type") or "").strip()
    target_type = str((target_node or {}).get("type") or "").strip()
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    edge["data"] = data
    edge_kind = str(data.get("kind") or "").strip()
    if edge_kind not in {"material", "dependency"}:
        edge_kind = "material" if _workflow_edge_looks_material(source_type, target_type, data) else "dependency"
    elif edge_kind == "material" and not _workflow_edge_is_material_pair(source_type, target_type):
        edge_kind = "dependency"
    data["kind"] = edge_kind
    role = str(data.get("role") or data.get("targetSlot") or data.get("slot") or "").strip()
    if not role:
        role = "material" if edge_kind == "material" else "context"
    if edge_kind == "dependency" and _workflow_edge_is_director_storyboard_result(edge, node_by_id):
        role = "generates"
        if isinstance(target_node, dict) and source_id:
            target_data = (
                target_node.get("data")
                if isinstance(target_node.get("data"), dict)
                else {}
            )
            target_node["data"] = target_data
            target_data["resultOfNodeId"] = source_id
    if (
        edge_kind == "dependency"
        and _workflow_is_video_task_type(source_type)
        and target_type == "video.result"
    ):
        role = "generates"
        if isinstance(target_node, dict) and source_id:
            target_data = (
                target_node.get("data")
                if isinstance(target_node.get("data"), dict)
                else {}
            )
            target_node["data"] = target_data
            target_data["resultOfNodeId"] = source_id
    data["role"] = role
    edge_workflow = workflow or {"nodes": list(node_by_id.values())}
    locked_system_edge = _workflow_locked_system_edge_key(edge, node_by_id, edge_workflow)
    if locked_system_edge:
        edge["deletable"] = False
        data["locked"] = True
        data["preserveOnReplan"] = True
        data.setdefault(
            "lockedReason",
            {
                "source_storyboard": "source_storyboard_edge",
                "storyboard_director": "storyboard_director_edge",
                "storyboard_video": "storyboard_video_edge",
                "visual_handoff": "visual_handoff_edge",
            }.get(locked_system_edge[2], "task_result_edge"),
        )
    data["workChainId"] = str(
        data.get("workChainId")
        or _workflow_node_text(target_node, "workChainId")
        or _workflow_node_text(source_node, "workChainId")
        or ""
    ).strip()
    data["routeId"] = str(
        data.get("routeId")
        or _workflow_node_text(target_node, "routeId")
        or _workflow_node_text(source_node, "routeId")
        or ""
    ).strip()
    data["segmentId"] = str(
        data.get("segmentId")
        or _workflow_node_text(target_node, "segmentId")
        or _workflow_node_text(source_node, "segmentId")
        or ""
    ).strip()
    data.setdefault("sourceNodeType", source_type)
    data.setdefault("targetNodeType", target_type)
    if edge_kind == "material":
        requested_source_handle = edge.get("sourceHandle") or data.get("sourceHandle")
        edge["sourceHandle"] = _workflow_material_source_handle(source_node, requested_source_handle) or _workflow_default_handle(
            source_type,
            direction="source",
            edge_kind=edge_kind,
            role=role,
        )
        target_slot = _canonical_workflow_slot(
            data.get("targetSlot") or data.get("slot") or data.get("role") or role,
            "",
        )
        if source_type == "asset.image":
            source_data = source_node.get("data") if isinstance((source_node or {}).get("data"), dict) else {}
            target_slot = _workflow_asset_target_slot(
                source_data.get("rootAssetType")
                or source_data.get("assetType")
                or source_data.get("asset_type"),
                target_slot,
            )
        _workflow_validate_material_slot(target_node, target_slot, source_node=source_node)
        locked_reason = str(data.get("lockedReason") or edge.get("lockedReason") or "").strip()
        locked_storyboard_video_input = bool(data.get("locked") or edge.get("locked")) or locked_reason == "workflow_chain_storyboard_video_input"
        requested_target_handle = str(edge.get("targetHandle") or data.get("targetHandle") or "").strip()
        edge["targetHandle"] = _workflow_material_target_handle(
            target_node,
            target_slot,
            requested_target_handle,
            workflow=edge_workflow,
            locked_storyboard_video_input=locked_storyboard_video_input,
        )
        data["sourceHandle"] = edge["sourceHandle"]
        data["targetHandle"] = edge["targetHandle"]
        data["role"] = target_slot
        data["targetSlot"] = target_slot
        data["slot"] = target_slot
        if not data.get("sourceType"):
            data["sourceType"] = _workflow_edge_default_source_type(source_type)
        if data.get("inputLinkId") is None:
            data["inputLinkId"] = ""
    else:
        edge["sourceHandle"] = str(edge.get("sourceHandle") or data.get("sourceHandle") or "").strip() or _workflow_default_handle(
            source_type,
            direction="source",
            edge_kind=edge_kind,
            role=role,
        )
        target_slot = str(data.get("targetSlot") or data.get("slot") or data.get("role") or "").strip()
        if _workflow_edge_is_director_storyboard_result(edge, node_by_id):
            edge["targetHandle"] = "generates"
            data["targetSlot"] = "generates"
            data["slot"] = "generates"
            data["sourceHandle"] = edge["sourceHandle"]
        elif _workflow_is_video_task_type(source_type) and target_type == "video.result":
            edge["targetHandle"] = "generates"
            data["targetSlot"] = "generates"
            data["slot"] = "generates"
            data["sourceHandle"] = edge["sourceHandle"]
        elif (source_type, target_type) in {
            ("source.text", "prompt.storyboard"),
            ("prompt.storyboard", "director.board"),
            ("director.board", "storyboard.card"),
        }:
            edge["targetHandle"] = "story"
            data["targetSlot"] = "story"
            data["slot"] = "story"
            data["sourceHandle"] = edge["sourceHandle"]
        else:
            edge["targetHandle"] = target_slot or _workflow_default_handle(target_type, direction="target", edge_kind=edge_kind, role=role)
    if not edge.get("id"):
        edge["id"] = f"{edge_kind}-{source_id}-{target_id}-{edge['targetHandle']}"

def _ensure_saved_workflow_input_link_edges(
    workflow: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
) -> None:
    edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    workflow["edges"] = edges
    material_link_ids = {
        str((edge.get("data") if isinstance(edge.get("data"), dict) else {}).get("inputLinkId") or "").strip()
        for edge in edges
        if isinstance(edge, dict)
        and str((edge.get("data") if isinstance(edge.get("data"), dict) else {}).get("kind") or "") == "material"
    }
    material_pairs = {
        (
            str(edge.get("source") or "").strip(),
            str(edge.get("target") or "").strip(),
            _canonical_workflow_slot(
                (edge.get("data") if isinstance(edge.get("data"), dict) else {}).get("targetSlot")
                or (edge.get("data") or {}).get("role"),
                "",
            ),
        )
        for edge in edges
        if isinstance(edge, dict)
        and str((edge.get("data") if isinstance(edge.get("data"), dict) else {}).get("kind") or "") == "material"
    }
    dependency_link_ids = {
        str((edge.get("data") if isinstance(edge.get("data"), dict) else {}).get("inputLinkId") or "").strip()
        for edge in edges
        if isinstance(edge, dict)
        and str((edge.get("data") if isinstance(edge.get("data"), dict) else {}).get("kind") or "") == "dependency"
    }
    dependency_pairs = {
        (
            str(edge.get("source") or "").strip(),
            str(edge.get("target") or "").strip(),
            _canonical_workflow_slot(
                (edge.get("data") if isinstance(edge.get("data"), dict) else {}).get("targetSlot")
                or (edge.get("data") or {}).get("role"),
                "",
            ),
        )
        for edge in edges
        if isinstance(edge, dict)
        and str((edge.get("data") if isinstance(edge.get("data"), dict) else {}).get("kind") or "") == "dependency"
    }
    for target_node in workflow.get("nodes") or []:
        if not isinstance(target_node, dict):
            continue
        target_node_id = str(target_node.get("id") or "").strip()
        data = target_node.get("data") if isinstance(target_node.get("data"), dict) else {}
        input_links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
        blockers: list[dict[str, Any]] = []
        for index, link in enumerate(input_links, start=1):
            if not isinstance(link, dict):
                continue
            link_id = str(link.get("id") or link.get("inputLinkId") or link.get("input_link_id") or "").strip()
            source_node_id = str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip()
            linked_target_id = str(link.get("targetNodeId") or link.get("target_node_id") or target_node_id).strip()
            source_node = node_by_id.get(source_node_id)
            _apply_workflow_input_link_contract(link, source_node)
            target_slot = _canonical_workflow_slot(link.get("targetSlot") or link.get("slot"), "storyboard_image")
            source_node_type = str((source_node or {}).get("type") or "")
            target_node_type = str(target_node.get("type") or "")
            is_video_result_dependency = (
                bool(source_node_id)
                and linked_target_id == target_node_id
                and _workflow_is_video_task_type(source_node_type)
                and target_node_type == "video.result"
                and (
                    target_slot in {"video_result", "generates", ""}
                    or (link_id and link_id in dependency_link_ids)
                    or (source_node_id, target_node_id, target_slot) in dependency_pairs
                )
            )
            if is_video_result_dependency:
                source_data = source_node.get("data") if isinstance((source_node or {}).get("data"), dict) else {}
                active_version_id = _workflow_data_active_version_id(source_data)
                source_status = str(source_data.get("status") or "").strip()
                link["sourceNodeId"] = source_node_id
                link["sourceNodeType"] = source_node_type
                link["targetNodeId"] = target_node_id
                link["targetNodeType"] = target_node_type
                link["targetSlot"] = "video_result"
                link["slot"] = "video_result"
                link["sourceType"] = "generated_video"
                link["status"] = (
                    "linked"
                    if active_version_id and source_status not in {"running", "waiting", "processing", "failed"}
                    else "pending_generation"
                )
                if active_version_id and _workflow_input_link_version_binding(link) != "pinned":
                    link["sourceVersionId"] = active_version_id
                    link["mediaVersionId"] = active_version_id
                continue
            if (link_id and link_id in material_link_ids) or (source_node_id, target_node_id, target_slot) in material_pairs:
                continue
            slot_error = ""
            try:
                _workflow_validate_material_slot(target_node, target_slot, source_node=source_node)
            except ValueError as exc:
                slot_error = str(exc)
            can_create_edge = (
                bool(source_node_id)
                and linked_target_id == target_node_id
                and _workflow_is_material_source(source_node)
                and _workflow_accepts_material_input(target_node)
                and _workflow_edge_is_material_pair(
                    str((source_node or {}).get("type") or ""),
                    str((target_node or {}).get("type") or ""),
                )
                and not slot_error
            )
            if not can_create_edge:
                link["status"] = "needs_relink"
                blockers.append(
                    {
                        "id": f"hidden_input_link:{target_node_id}:{link_id or index}",
                        "severity": "blocker",
                        "category": "input_link",
                        "message": slot_error or "inputLink 缺少对应可视化 material edge，或来源/目标节点不符合画布链接规则",
                        "nodeId": target_node_id,
                        "nodeType": target_node.get("type"),
                        "inputLinkId": link_id,
                        "sourceNodeId": source_node_id,
                        "targetSlot": target_slot,
                    }
                )
                continue
            link["sourceNodeId"] = source_node_id
            link["sourceNodeType"] = str(source_node.get("type") or "")
            link["targetNodeId"] = target_node_id
            link["targetNodeType"] = str(target_node.get("type") or "")
            link["targetSlot"] = target_slot
            source_handle = _workflow_material_source_handle(
                source_node,
                link.get("sourceHandle") or link.get("source_handle"),
            )
            if source_handle:
                link["sourceHandle"] = source_handle
            locked_reason = str(link.get("lockedReason") or link.get("locked_reason") or "").strip()
            target_handle = _workflow_material_target_handle(
                target_node,
                target_slot,
                link.get("targetHandle") or link.get("target_handle"),
                workflow=workflow,
                locked_storyboard_video_input=bool(link.get("locked")) or locked_reason == "workflow_chain_storyboard_video_input",
            )
            link["targetHandle"] = target_handle
            if not link.get("sourceType"):
                link["sourceType"] = _workflow_edge_default_source_type(str(source_node.get("type") or ""))
            edge = {
                "id": f"material-{source_node_id}-{target_node_id}-{target_slot}-{link_id or index}",
                "source": source_node_id,
                "target": target_node_id,
                "sourceHandle": source_handle or _workflow_default_handle(str(source_node.get("type") or ""), direction="source", edge_kind="material", role=target_slot),
                "targetHandle": target_handle,
                "data": {
                    "kind": "material",
                    "role": target_slot,
                    "inputLinkId": link_id,
                    "sourceType": link.get("sourceType"),
                    "targetHandle": target_handle,
                    "sourceNodeType": link.get("sourceNodeType"),
                    "targetNodeType": link.get("targetNodeType"),
                    "targetSlot": target_slot,
                    "workChainId": str(link.get("workChainId") or _workflow_node_text(target_node, "workChainId") or ""),
                    "routeId": str(link.get("routeId") or _workflow_node_text(target_node, "routeId") or ""),
                    "segmentId": str(link.get("segmentId") or _workflow_node_text(target_node, "segmentId") or ""),
                },
            }
            edges.append(edge)
            if link_id:
                material_link_ids.add(link_id)
            material_pairs.add((source_node_id, target_node_id, target_slot))
        if blockers:
            quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
            quality["inputLinkBlockers"] = blockers
            quality["inputLinkStatus"] = "blocked"
            data["quality"] = quality
        else:
            quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
            if quality.get("inputLinkBlockers") or quality.get("inputLinkStatus") == "blocked":
                quality.pop("inputLinkBlockers", None)
                if quality.get("inputLinkStatus") == "blocked":
                    quality.pop("inputLinkStatus", None)
                data["quality"] = quality

def _ensure_saved_workflow_contract(workflow: dict[str, Any]) -> None:
    normalize_work_chain_origins(workflow)
    workflow.pop("inputLinks", None)
    if not isinstance(workflow.get("nodes"), list):
        workflow["nodes"] = []
    if not isinstance(workflow.get("routes"), list):
        workflow["routes"] = []
    if not isinstance(workflow.get("workChains"), list):
        workflow["workChains"] = []
    if not isinstance(workflow.get("edges"), list):
        workflow["edges"] = []
    for node in workflow.get("nodes") or []:
        if isinstance(node, dict):
            node_type = str(node.get("type") or "").strip()
            if _workflow_is_blocked_canvas_node_type(node_type):
                raise ValueError(f"当前分集画布范围不支持保存该类型节点：{node_type}")
            _ensure_saved_workflow_node_contract(node)
    for index, chain in enumerate(workflow.get("workChains") or []):
        if isinstance(chain, dict):
            _ensure_saved_workflow_chain_contract(chain, index)
    route_to_chain_id: dict[str, str] = {}
    chains_by_id = {
        str(chain.get("id") or "").strip(): chain
        for chain in workflow.get("workChains") or []
        if isinstance(chain, dict) and str(chain.get("id") or "").strip()
    }
    for chain_id, chain in chains_by_id.items():
        for route_id in _workflow_chain_route_ids(chain):
            route_text = str(route_id or "").strip()
            if route_text:
                route_to_chain_id[route_text] = chain_id
    for index, route in enumerate(workflow.get("routes") or []):
        if not isinstance(route, dict):
            continue
        _ensure_saved_workflow_route_contract(workflow, route, index, route_to_chain_id)
        chain = chains_by_id.get(str(route.get("workChainId") or "").strip())
        if chain:
            chain["routeIds"] = _workflow_add_unique(_workflow_chain_route_ids(chain), str(route.get("id") or ""))
            chain.pop("route_ids", None)
            chain["segmentIds"] = _workflow_add_unique(chain.get("segmentIds") if isinstance(chain.get("segmentIds"), list) else [], str(route.get("segmentId") or ""))
            for shot_id in route.get("shotIds") or []:
                chain["shotIds"] = _workflow_add_unique(chain.get("shotIds") if isinstance(chain.get("shotIds"), list) else [], str(shot_id or ""))
    node_by_id = {
        str(node.get("id") or "").strip(): node
        for node in workflow.get("nodes") or []
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }
    _workflow_ensure_work_chain_storyboard_result_edges(workflow, node_by_id)
    _ensure_saved_workflow_input_link_edges(workflow, node_by_id)
    kept_edges: list[dict[str, Any]] = []
    seen_edge_ids: set[str] = set()
    seen_edge_signatures: set[tuple[str, str, str, str, str]] = set()
    for edge in workflow.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source_node = node_by_id.get(str(edge.get("source") or "").strip())
        target_node = node_by_id.get(str(edge.get("target") or "").strip())
        source_type = str((source_node or {}).get("type") or "").strip()
        target_type = str((target_node or {}).get("type") or "").strip()
        if _workflow_edge_is_forbidden_image_link(source_type, target_type):
            continue
        _ensure_saved_workflow_edge_contract(edge, node_by_id, workflow)
        edge_id = str(edge.get("id") or "").strip()
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        signature = (
            str(data.get("kind") or "").strip(),
            str(edge.get("source") or "").strip(),
            str(edge.get("target") or "").strip(),
            str(data.get("targetSlot") or data.get("role") or "").strip(),
            str(data.get("inputLinkId") or "").strip(),
        )
        if edge_id:
            if edge_id in seen_edge_ids:
                continue
            seen_edge_ids.add(edge_id)
        if signature in seen_edge_signatures:
            continue
        seen_edge_signatures.add(signature)
        kept_edges.append(edge)
    workflow["edges"] = kept_edges

def _node_route_id(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(node.get("routeId") or node.get("route_id") or data.get("routeId") or data.get("route_id") or "").strip()

def _node_work_chain_id(node: dict[str, Any] | None) -> str:
    return str((node or {}).get("workChainId") or "").strip()

def _workflow_canvas_asset_node_identity_from_data(data: dict[str, Any] | None) -> tuple[str, str]:
    if not isinstance(data, dict):
        return "", ""
    asset_type = _workflow_normalize_asset_type(data.get("rootAssetType"))
    asset_id = str(data.get("rootAssetId") or "").strip()
    if asset_type in _ASSET_REF_COLLECTIONS and asset_id:
        return asset_type, asset_id
    return "", ""

def _workflow_node_work_chain_id(workflow: dict[str, Any], node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return ""
    return str(node.get("workChainId") or "").strip()

def _workflow_accepts_material_input(node: dict[str, Any] | None) -> bool:
    node_type = str((node or {}).get("type") or "")
    return _workflow_is_material_target_type(node_type)

def _workflow_material_allowed_slots(node: dict[str, Any] | None) -> set[str]:
    node_type = str((node or {}).get("type") or "").strip()
    return set(_WORKFLOW_MATERIAL_INPUT_SLOTS_BY_TARGET.get(node_type) or set())

_WORKFLOW_ASSET_INPUT_HANDLE = "asset_input"

_WORKFLOW_VIDEO_INPUT_HANDLE = "video_input"

def _workflow_validate_material_slot(
    target_node: dict[str, Any] | None,
    slot: str,
    *,
    source_node: dict[str, Any] | None = None,
    source_node_type: str = "",
) -> None:
    node_type = str((target_node or {}).get("type") or "").strip()
    source_is_video = _workflow_node_media_kind(source_node) == "video" or (source_node or {}).get("type") == "video.result"
    if source_node and (slot == VIDEO_REFERENCE_SLOT) != source_is_video:
        raise ValueError("视频资产必须使用参考视频关联，图片资产不能使用参考视频关联")
    if slot == FRAME_SLOT and source_node and not is_frame_image(source_node.get("data")):
        raise ValueError("只有视频剪辑截图生成的帧画面才能使用帧画面关联")
    if source_node and (source_node.get("data") or {}).get("mediaPurpose") == "custom_image" and slot != "custom_image":
        raise ValueError("自定义图片必须使用普通图片参考关联")
    resolved_source_type = str(source_node_type or (source_node or {}).get("type") or "").strip()
    if resolved_source_type and not _workflow_edge_is_material_pair(resolved_source_type, node_type):
        if _workflow_is_asset_reference_type(resolved_source_type):
            raise ValueError("资产图只能链接到分镜脚本、分镜单元或视频生成")
        if _workflow_is_external_media_type(resolved_source_type):
            raise ValueError("导入图片可关联分镜脚本、分镜单元或视频生成；导入视频仅可关联视频生成")
        if _workflow_is_generated_reference_type(resolved_source_type):
            raise ValueError("分镜图只能作为故事版参考链接到视频生成")
        raise ValueError("素材来源必须是 asset.image、media.external 或 storyboard.image 节点")
    if _workflow_is_video_task_type(node_type):
        target_scope = workflow_video_task_scope(
            {"nodes": [target_node] if target_node else []},
            target_node,
        )
        if not target_scope:
            raise ValueError("视频生成缺少作用域标识，请重新创建任务卡")
    source_error = _workflow_video_task_material_source_error(
        source_node,
        target_node,
        source_node_type=resolved_source_type,
    )
    if source_error:
        raise ValueError(source_error)
    if node_type in {"director.board", "storyboard.card"} and _workflow_node_media_kind(source_node) == "video":
        raise ValueError("分镜脚本和分镜单元只能关联图片资产")
    if node_type in {"director.board", "storyboard.card"} and source_node and not _workflow_node_is_visual_handoff_asset_like(source_node):
        source_data = _workflow_node_payload_data(source_node)
        source_slot = _workflow_asset_target_slot(
            source_data.get("rootAssetType") or source_data.get("assetType")
            or source_data.get("assetKind") or source_data.get("mediaPurpose")
            or source_data.get("preferredTargetSlot"),
            "storyboard_image" if resolved_source_type == "storyboard.image" else "",
        )
        if source_slot == "storyboard_image":
            raise ValueError("分镜脚本和分镜单元支持角色、场景、道具、生物等图片资产，分镜图请关联视频生成")
    if _workflow_node_is_visual_handoff_asset_like(source_node) and slot != _VISUAL_HANDOFF_SLOT:
        raise ValueError("视觉交接图必须使用视觉交接输入类型")
    if slot == _VISUAL_HANDOFF_SLOT and _workflow_node_media_kind(source_node) == "video":
        raise ValueError("视觉交接必须使用图片，不能链接视频资产")
    allowed_slots = _workflow_material_allowed_slots(target_node)
    if not allowed_slots:
        raise ValueError("素材输入只能链接到分镜脚本、分镜单元或视频生成")
    if slot not in allowed_slots:
        raise ValueError(f"{node_type or '目标节点'} 不支持 {slot or '未指定'} 素材输入 slot")
    if _workflow_is_external_media_type(resolved_source_type) and source_node:
        return

def _workflow_is_material_source(node: dict[str, Any] | None) -> bool:
    node_type = str((node or {}).get("type") or "")
    return _workflow_is_material_source_type(node_type)

def _canonical_workflow_slot(value: Any, fallback: str = "storyboard_image") -> str:
    text = str(value or "").strip()
    if _workflow_input_handle_kind(text):
        return "storyboard_image"
    aliases = {
        FRAME_IMAGE: FRAME_SLOT,
        "character": "character_reference",
        "characters": "character_reference",
        "creature": "creature_reference",
        "creatures": "creature_reference",
        "monster": "creature_reference",
        "monsters": "creature_reference",
        "beast": "creature_reference",
        "beasts": "creature_reference",
        "scene": "scene_reference",
        "scenes": "scene_reference",
        "prop": "prop_reference",
        "props": "prop_reference",
        "style": "style_reference",
        "styles": "style_reference",
        "asset": "storyboard_image",
        "reference": "storyboard_image",
        "visual": "storyboard_image",
        "visual_reference": "storyboard_image",
        "visual_handoff": _VISUAL_HANDOFF_SLOT,
        "visual_handoff_reference": _VISUAL_HANDOFF_SLOT,
        "handoff": _VISUAL_HANDOFF_SLOT,
        "continuity": _VISUAL_HANDOFF_SLOT,
        "视觉交接": _VISUAL_HANDOFF_SLOT,
        "交接图": _VISUAL_HANDOFF_SLOT,
        "storyboard": "storyboard_image",
        "storyboard_image": "storyboard_image",
        "image": "storyboard_image",
        "first": "storyboard_image",
        "last": "storyboard_image",
        "middle": "storyboard_image",
    }
    if not text:
        return fallback
    return aliases.get(text, text)

def _workflow_asset_target_slot(asset_type: Any, fallback: str = "storyboard_image") -> str:
    normalized = str(asset_type or "").strip().lower()
    if normalized == FRAME_IMAGE:
        return FRAME_SLOT
    if not normalized:
        return fallback
    if normalized in {
        "character",
        "characters",
        "role",
        "roles",
        "person",
        "people",
        "角色",
        "人物",
    }:
        return "character_reference"
    if normalized in {
        "creature",
        "creatures",
        "monster",
        "monsters",
        "beast",
        "beasts",
        "生物",
        "怪物",
        "活体",
        "妖兽",
        "魔兽",
        "灵兽",
    }:
        return "creature_reference"
    if normalized in {"scene", "scenes", "location", "locations", "setting", "场景", "地点"}:
        return "scene_reference"
    if normalized in {"prop", "props", "item", "items", "object", "objects", "道具", "物件"}:
        return "prop_reference"
    if normalized in {"style", "styles", "look", "风格"}:
        return "style_reference"
    if normalized in {"storyboard", "storyboard_image", "image", "分镜", "分镜图"}:
        return "storyboard_image"
    if normalized in {"visual_handoff", "visual_handoff_reference", "handoff", "continuity", "视觉交接", "交接图"}:
        return _VISUAL_HANDOFF_SLOT
    return _canonical_workflow_slot(normalized, fallback)

def _workflow_input_link_version_binding(link: dict[str, Any]) -> str:
    value = str(link.get("versionBinding") or link.get("version_binding") or "").strip().lower()
    if value in {"pinned", "specific", "fixed"}:
        return "pinned"
    if value in {"active", "latest", "recommended"}:
        return "active"
    version_mode = str(link.get("versionMode") or link.get("version_mode") or "").strip().lower()
    if version_mode in {"specific", "pinned", "fixed"}:
        return "pinned"
    if bool(link.get("pinned") or link.get("versionPinned") or link.get("version_pinned")):
        return "pinned"
    return "active"

def _workflow_source_active_version_id(source_node: dict[str, Any] | None) -> str:
    data = source_node.get("data") if isinstance((source_node or {}).get("data"), dict) else {}
    return _workflow_data_active_version_id(data)

def _workflow_data_active_version_id(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    for key in (
        "activeVersionId",
        "active_version_id",
        "activeMediaVersionId",
        "active_media_version_id",
        "mediaVersionId",
        "media_version_id",
    ):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return ""

def _apply_workflow_input_link_contract(input_link: dict[str, Any], source_node: dict[str, Any] | None = None) -> None:
    slot = _canonical_workflow_slot(input_link.get("targetSlot") or input_link.get("slot"), "storyboard_image")
    source_data = source_node.get("data") if isinstance((source_node or {}).get("data"), dict) else {}
    source_type = str((source_node or {}).get("type") or input_link.get("sourceNodeType") or "").strip()
    if is_frame_image(source_data):
        slot = FRAME_SLOT
        input_link.update({"assetType": FRAME_IMAGE, **frame_options(input_link)})
    if source_type == "asset.image":
        slot = _workflow_asset_target_slot(
            source_data.get("rootAssetType")
            or source_data.get("assetType")
            or input_link.get("assetType"),
            slot,
        )
        asset_type, asset_id = _workflow_canvas_asset_node_identity_from_data(source_data)
        if asset_type and asset_id:
            input_link["assetType"] = asset_type
            input_link["assetId"] = asset_id
            input_link["rootAssetType"] = asset_type
            input_link["rootAssetId"] = asset_id
            root_project_id = str(
                source_data.get("rootAssetProjectId")
                or ""
            ).strip()
            if root_project_id:
                input_link["rootAssetProjectId"] = root_project_id
    source_handle = _workflow_material_source_handle(
        source_node,
        input_link.get("sourceHandle") or input_link.get("source_handle"),
    )
    if source_handle:
        input_link["sourceHandle"] = source_handle
    input_link["targetSlot"] = slot
    input_link["slot"] = slot
    input_link["role"] = slot
    input_link.setdefault("required", False)
    provenance = input_link.get("provenance") if isinstance(input_link.get("provenance"), dict) else {}
    input_link.setdefault("createdBy", str(provenance.get("source") or "user"))
    binding = _workflow_input_link_version_binding(input_link)
    input_link["versionBinding"] = binding
    input_link["versionMode"] = "specific" if binding == "pinned" else "active"
    source_media = {}
    for key in ("media", "storage"):
        value = source_data.get(key)
        if isinstance(value, dict):
            source_media = value
            break
    if source_media:
        media_id = str(
            source_data.get("mediaId")
            or source_data.get("media_id")
            or source_media.get("id")
            or source_media.get("mediaId")
            or source_media.get("media_id")
            or ""
        ).strip()
        if media_id:
            input_link["mediaId"] = media_id
        media_type = str(
            source_media.get("mediaType")
            or source_media.get("media_type")
            or source_media.get("kind")
            or input_link.get("mediaType")
            or input_link.get("media_type")
            or ""
        ).strip()
        if media_type:
            input_link["mediaType"] = media_type
            input_link["mediaKind"] = media_type
        path = str(
            source_media.get("relativePath")
            or source_media.get("relative_path")
            or source_media.get("file")
            or source_media.get("path")
            or source_media.get("filePath")
            or source_media.get("file_path")
            or ""
        ).strip()
        if path:
            input_link["path"] = path
    explicit_version = str(
        input_link.get("sourceVersionId")
        or input_link.get("source_version_id")
        or input_link.get("mediaVersionId")
        or input_link.get("media_version_id")
        or input_link.get("assetVersionId")
        or input_link.get("asset_version_id")
        or input_link.get("versionId")
        or input_link.get("version_id")
        or ""
    ).strip()
    active_version = _workflow_source_active_version_id(source_node)
    version_id = (
        explicit_version
        if binding == "pinned" and explicit_version == active_version
        else active_version
    )
    if version_id:
        input_link["sourceVersionId"] = version_id
        if source_type in {"storyboard.image", "media.external", "asset.image"}:
            input_link["mediaVersionId"] = version_id
    else:
        input_link.pop("sourceVersionId", None)
        input_link.pop("source_version_id", None)
        input_link.pop("mediaVersionId", None)
        input_link.pop("media_version_id", None)

_WORKFLOW_ASSET_TYPE_ALIASES = {
    "character": "characters",
    "characters": "characters",
    "creature": "creatures",
    "creatures": "creatures",
    "scene": "scenes",
    "scenes": "scenes",
    "prop": "props",
    "props": "props",
    "style": "styles",
    "styles": "styles",
}

def _workflow_normalize_asset_type(value: Any) -> str:
    asset_type = str(value or "").strip()
    if not asset_type:
        return ""
    return _WORKFLOW_ASSET_TYPE_ALIASES.get(asset_type.casefold(), asset_type)

def _workflow_node_can_supply_image_reference(
    node: dict[str, Any] | None,
) -> bool:
    if not isinstance(node, dict):
        return False
    node_type = _workflow_node_type(node)
    if node_type == "video.result":
        return False
    if not _workflow_is_material_source_type(node_type):
        return False
    if node_type == "media.external":
        media_kind = _workflow_node_media_reference_kind(node)
        return media_kind == "image"
    return True

def _workflow_video_task_material_source_error(
    source_node: dict[str, Any] | None,
    target_node: dict[str, Any] | None,
    *,
    source_node_type: str = "",
) -> str:
    if not _workflow_is_video_task_type(_workflow_node_type_value(target_node)):
        return ""
    if _workflow_node_can_supply_image_reference(
        source_node,
    ):
        return ""
    source_type = _workflow_node_type_value(source_node) or str(source_node_type or "").strip()
    if source_type == "video.result" or (source_type == "media.external" and _workflow_node_media_kind(source_node) == "video"):
        return ""
    if not isinstance(source_node, dict) and not source_type:
        return ""
    if not isinstance(source_node, dict):
        if source_type in {"asset.image", "storyboard.image", "media.external"}:
            return ""
    return "视频生成只能关联图片或视频资产作为参考"

def _workflow_node(workflow: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    return next(
        (
            node
            for node in workflow.get("nodes", [])
            if isinstance(node, dict) and node.get("id") == node_id
        ),
        None,
    )

_DIRECTOR_BOARD_NODE_TYPES = {"director.board"}

_VISUAL_HANDOFF_SOURCE_NODE_TYPES = {"storyboard.card"}

def _workflow_node_type(node: dict[str, Any]) -> str:
    return str(node.get("type") or "").strip()


def _node_segment_id(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(node.get("segmentId") or data.get("segmentId") or "").strip()

def _append_unique_string(values: Any, value: str) -> list[str]:
    result: list[str] = []
    current_values = values if isinstance(values, list) else []
    for item in current_values:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    if value and value not in result:
        result.append(value)
    return result


_PROMPT_STORYBOARD_NODE_TYPES = {"prompt.storyboard"}

def _workflow_unique_id(base: str, used: set[str], fallback: str) -> str:
    candidate = _safe_workflow_id(str(base or ""), fallback)
    if candidate not in used:
        used.add(candidate)
        return candidate
    index = 2
    while True:
        next_candidate = _safe_workflow_id(
            f"{candidate}_{index:02d}",
            f"{fallback}_{index:02d}",
        )
        if next_candidate not in used:
            used.add(next_candidate)
            return next_candidate
        index += 1


def _translate_workflow_layout(workflow: dict[str, Any], x: float, y: float) -> None:
    for node in workflow.get("nodes", []):
        position = node.setdefault("position", {})
        position["x"] = round(float(position.get("x") or 0) + x, 3)
        position["y"] = round(float(position.get("y") or 0) + y, 3)
    for item in [*workflow.get("workChains", []), *workflow.get("routes", [])]:
        layout = item.get("layout")
        if isinstance(layout, dict):
            layout["x"] = round(float(layout.get("x") or 0) + x, 3)
            layout["y"] = round(float(layout.get("y") or 0) + y, 3)


def _workflow_mutation_returns_workflow(payload: dict[str, Any]) -> bool:
    # Local canvas mutations return ACK/version by default; full workflow payloads must be explicit.
    for key in ("returnWorkflow", "return_workflow", "includeWorkflow", "include_workflow"):
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() not in {"0", "false", "no", "off"}
    return False

def _assert_canvas_mutation_does_not_return_workflow(
    payload: dict[str, Any],
    operation_label: str = "画布操作",
) -> None:
    if _workflow_mutation_returns_workflow(payload):
        raise ValueError(f"{operation_label}不再返回完整 workflow；需要完整状态时请单独调用 get_canvas_snapshot。")
    if payload.get("baseHash") or payload.get("base_hash"):
        raise ValueError(f"{operation_label}不再支持 baseHash 全量写入；请使用 expectedRevision。")

def _workflow_mutation_returns_production_status(payload: dict[str, Any]) -> bool:
    for key in (
        "returnProductionStatus",
        "return_production_status",
        "includeProductionStatus",
        "include_production_status",
    ):
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() not in {"0", "false", "no", "off"}
    return _workflow_mutation_returns_workflow(payload)


_WORKFLOW_CHAIN_MANAGED_NODE_TYPES = {
    "source.text",
    "prompt.storyboard",
    "director.board",
    "storyboard.card",
    "storyboard.image",
    *VIDEO_TASK_NODE_TYPES,
    "video.result",
}


def _assert_new_workflow_node_type_allowed(
    node_type: str,
    *,
    allow_independent_video_task: bool = False,
    allow_work_chain_managed: bool = False,
) -> None:
    normalized = str(node_type or "").strip()
    if _workflow_is_blocked_canvas_node_type(normalized):
        raise ValueError("当前分集画布范围不支持新建该类型节点")
    if not allow_work_chain_managed and normalized in _WORKFLOW_CHAIN_MANAGED_NODE_TYPES:
        if allow_independent_video_task and _workflow_is_video_task_type(normalized):
            return
        raise ValueError("分集原文、片段剧本、分镜脚本、分镜单元、分镜图、工作链视频生成和视频片段只能由生成工作链流程创建")


def _assert_workflow_node_type_update_allowed(existing_node: dict[str, Any], incoming_node: dict[str, Any]) -> None:
    incoming_type = str(incoming_node.get("type") or "").strip()
    if not incoming_type:
        return
    existing_type = str(existing_node.get("type") or "").strip()
    if incoming_type == existing_type:
        return
    if existing_type in _WORKFLOW_CHAIN_MANAGED_NODE_TYPES or incoming_type in _WORKFLOW_CHAIN_MANAGED_NODE_TYPES:
        raise ValueError("工作链专属节点类型不能通过通用节点更新变更")


def _workflow_create_task_result_type(node_type: str) -> str:
    if _workflow_is_video_task_type(node_type):
        return "video.result"
    return ""


def _workflow_task_node_allowed(node_type: str) -> bool:
    return _workflow_is_video_task_type(node_type)


def _merge_generation_config_patch(current: Any, patch: Any) -> dict[str, Any]:
    base = copy.deepcopy(current) if isinstance(current, dict) else {}
    if not isinstance(patch, dict):
        return base
    for key, value in patch.items():
        if value is None:
            base.pop(key, None)
            continue
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge_generation_config_patch(base.get(key), value)
            continue
        base[key] = copy.deepcopy(value)
    return base


def _workflow_image_node_type(node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return ""
    node_type = str(node.get("type") or "").strip()
    if node_type:
        return node_type
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(data.get("eyebrow") or "").strip()


def _workflow_merge_response_nodes(
    nodes: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    sync_nodes: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> list[dict[str, Any]]:
    def merge_node(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged_node = {**copy.deepcopy(current), **copy.deepcopy(incoming)}
        current_data = current.get("data") if isinstance(current.get("data"), dict) else {}
        incoming_data = incoming.get("data") if isinstance(incoming.get("data"), dict) else {}
        if current_data or incoming_data:
            merged_data = {**copy.deepcopy(current_data), **copy.deepcopy(incoming_data)}
            current_card = current_data.get("videoTaskCard") if isinstance(current_data.get("videoTaskCard"), dict) else {}
            incoming_card = incoming_data.get("videoTaskCard") if isinstance(incoming_data.get("videoTaskCard"), dict) else {}
            if current_card or incoming_card:
                merged_card = {**copy.deepcopy(current_card), **copy.deepcopy(incoming_card)}
                merged_data["videoTaskCard"] = merged_card
            merged_node["data"] = merged_data
        return merged_node

    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in [*(nodes or []), *(sync_nodes or [])]:
        if not isinstance(row, dict):
            continue
        node_id = str(row.get("id") or "").strip()
        if not node_id:
            continue
        if node_id not in merged:
            order.append(node_id)
            merged[node_id] = copy.deepcopy(row)
        else:
            merged[node_id] = merge_node(merged[node_id], row)
    return [merged[node_id] for node_id in order if node_id in merged]


def _workflow_mutation_event_fields(
    save_result: dict[str, Any],
    extra_changed_resources: list[str] | None = None,
) -> dict[str, Any]:
    result = save_result if isinstance(save_result, dict) else {}
    fields = {
        key: copy.deepcopy(result.get(key))
        for key in ("txId", "seq", "revision", "baseRevision", "opType", "records")
        if result.get(key) is not None
    }
    changed_resources: list[str] = []
    resource_names = {
        "workflow": "",
        "workflow_card": "canvas_node",
        "workflow_cards": "canvas_node",
        "workflow_node": "canvas_node",
        "workflow_nodes": "canvas_node",
        "workflow_node_inline": "canvas_node",
        "workflow_node_layout": "canvas_node",
        "workflow_media": "canvas_node",
        "canvas_card": "canvas_node",
        "canvas_cards": "canvas_node",
        "workflow_edge": "canvas_edge",
        "workflow_edges": "canvas_edge",
        "workflow_route": "canvas_route",
        "workflow_routes": "canvas_route",
        "workflow_work_chain": "canvas_work_chain",
        "workflow_work_chains": "canvas_work_chain",
        "workflow_task": "canvas_task",
        "workflow_tasks": "canvas_task",
        "workflow_version": "canvas_version",
        "workflow_versions": "canvas_version",
        "task": "canvas_task",
        "tasks": "canvas_task",
        "version": "canvas_version",
        "versions": "canvas_version",
        "workflow_asset_refs": "canvas_projection",
    }
    for source in (
        result.get("changedResources") if isinstance(result.get("changedResources"), list) else [],
        extra_changed_resources if isinstance(extra_changed_resources, list) else [],
    ):
        for item in source:
            resource = resource_names.get(str(item or "").strip(), str(item or "").strip())
            if resource and resource not in changed_resources:
                changed_resources.append(resource)
    fields["changedResources"] = changed_resources
    return fields


def _workflow_node_status_after_input_availability_change(status: Any, *, input_ready: bool) -> str:
    current = str(status or "").strip()
    if current in {"", "draft", "waiting", "waiting_upstream"}:
        return "ready" if input_ready else "waiting"
    return current


_WORKFLOW_UNUSABLE_MEDIA_VERSION_STATUSES = {
    "blocked",
    "cancelled",
    "canceled",
    "draft",
    "failed",
    "idle",
    "pending_generation",
    "preflight_failed",
    "processing",
    "queued",
    "running",
    "waiting",
    "waiting_upstream",
}


def _workflow_version_has_usable_media(version: dict[str, Any] | None) -> bool:
    if not isinstance(version, dict):
        return False
    status = str(version.get("status") or "").strip().lower()
    return bool(version.get("media")) and status not in _WORKFLOW_UNUSABLE_MEDIA_VERSION_STATUSES


def _workflow_active_version_has_usable_media(
    versions: list[dict[str, Any]],
    data: dict[str, Any] | None,
) -> bool:
    if not isinstance(versions, list):
        return False
    active_version_id = _workflow_data_active_version_id(data)
    if not active_version_id:
        return False
    return any(
        _workflow_version_has_usable_media(item)
        and str(item.get("id") or "").strip() == active_version_id
        for item in versions
        if isinstance(item, dict)
    )


def _workflow_status_with_usable_active_media(status: Any) -> str:
    current = str(status or "").strip()
    if current and current not in _WORKFLOW_UNUSABLE_MEDIA_VERSION_STATUSES:
        return current
    return "ready"


_STORYBOARD_REFERENCE_NODE_TYPES = {"storyboard.image"}


_VIDEO_RESULT_NODE_TYPES = {"video.result"}


def _workflow_canvas_project_asset_type_from_value(value: Any) -> str:
    text = re.sub(
        r"[\s-]+",
        "_",
        re.sub(
            r"([a-z0-9])([A-Z])",
            r"\1_\2",
            str(value or "").strip(),
        ),
    ).lower()
    if text in {"characters", "character", "character_reference"}:
        return "characters"
    if text in {
        "creatures",
        "creature",
        "creature_reference",
        "monsters",
        "monster",
        "beasts",
        "beast",
    }:
        return "creatures"
    if text in {"scenes", "scene", "scene_reference"}:
        return "scenes"
    if text in {"props", "prop", "prop_reference"}:
        return "props"
    return ""


_VISUAL_HANDOFF_TARGET_NODE_TYPES = {"storyboard.card"}


def _workflow_layout_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _workflow_layout_position(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    x = _workflow_layout_number(value.get("x"))
    y = _workflow_layout_number(value.get("y"))
    if x is None or y is None:
        return None
    return {"x": x, "y": y}


def _mark_visual_handoff_user_position(node: dict[str, Any]) -> None:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    if node.get("type") == "asset.image" and data.get("sourceType") == "visual_handoff_generation":
        data["positionEditedByUser"] = True


def _workflow_layout_size(node_type: str, value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    size: dict[str, Any] = {}
    for key in ("width", "height", "minWidth", "minHeight"):
        number = _workflow_layout_number(value.get(key))
        if number is not None:
            size[key] = int(number) if number.is_integer() else number
    if "width" not in size or "height" not in size:
        return None
    return size


def _workflow_new_node_id(prefix: str) -> str:
    return f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', prefix).strip('_')}_{uuid.uuid4().hex[:8]}"


def _workflow_number_payload(value: Any, default: float = 0) -> float:
    number = _workflow_layout_number(value)
    return number if number is not None else default


def _workflow_position_payload(value: Any, default: dict[str, float] | None = None) -> dict[str, float]:
    parsed = _workflow_layout_position(value)
    if parsed is not None:
        return parsed
    fallback = default or {"x": 120, "y": 120}
    return {
        "x": _workflow_number_payload(fallback.get("x"), 120),
        "y": _workflow_number_payload(fallback.get("y"), 120),
    }
