# -*- coding: utf-8 -*-
"""工作流领域实际实现。"""
from __future__ import annotations

from .assets import _asset_type_label
from .assets import list_assets
from .canvas_store_mutations import write_canvas_records_v4
from .projects import _touch_project_meta
from .store_core import ASSET_LIFECYCLE_ACTIVE
from .store_core import _now
from .workflow_asset_resolution import _workflow_canvas_asset_exists
from .workflow_contract import _CANVAS_NODE_ROLE_IMAGE_ASSET
from .workflow_contract import _assert_canvas_mutation_does_not_return_workflow
from .workflow_contract import _assert_new_workflow_node_type_allowed
from .workflow_contract import _ensure_saved_workflow_edge_contract
from .workflow_contract import _ensure_saved_workflow_node_contract
from .workflow_contract import _workflow_create_task_result_type
from .workflow_contract import _workflow_default_card_size
from .workflow_contract import _workflow_layout_size
from .workflow_contract import _workflow_media_purpose_label
from .workflow_contract import _workflow_mutation_event_fields
from .workflow_contract import _workflow_new_node_id
from .workflow_contract import _workflow_normalize_asset_type
from .workflow_contract import _workflow_position_payload
from .workflow_contract import _workflow_project_asset_name_exists
from .workflow_contract import _workflow_project_asset_type_from_media_purpose
from .workflow_contract import _workflow_standalone_video_generation_config
from .workflow_contract import _workflow_keyframe_video_generation_config
from .workflow_contract import _workflow_character_replace_generation_config
from utils.video_task_types import CHARACTER_REPLACE_TASK, standalone_video_strategy
from .workflow_contract import _workflow_task_node_allowed
from .workflow_projection import _canvas_node_exists_v4
from typing import Any
import copy


def create_workflow_node(project_id: str, episode_id: str, node_type: str, node: dict[str, Any] | None = None) -> dict[str, Any]:
    _assert_new_workflow_node_type_allowed(node_type)
    node = copy.deepcopy(node or {})
    node_id = str(node.get("id") or "").strip() or _workflow_new_node_id(node_type.replace(".", "_"))
    if _canvas_node_exists_v4(project_id, episode_id, node_id):
        raise ValueError("节点 id 已存在")
    data_patch = node.get("data") if isinstance(node.get("data"), dict) else {}
    new_node = {
        **{key: copy.deepcopy(value) for key, value in node.items() if key not in {"id", "type", "position", "data"}},
        "id": node_id,
        "type": node_type,
        "position": _workflow_position_payload(node.get("position"), {"x": 120, "y": 120}),
        "data": {
            "title": node_type,
            "status": "draft",
            "summary": "",
            **copy.deepcopy(data_patch),
        },
    }
    _ensure_saved_workflow_node_contract(new_node)
    save_result = write_canvas_records_v4(
        project_id,
        episode_id,
        nodes=[new_node],
        op_type="structure_patch",
        changed_resources=["canvas_node"],
    )
    _touch_project_meta(project_id)
    mutation_fields = _workflow_mutation_event_fields(save_result)
    return {
        "success": True,
        "episodeId": episode_id,
        "node": new_node,
        "workflowVersion": save_result.get("workflowVersion"),
        **mutation_fields,
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": new_node.get("id")},
        "projectChanged": True,
    }


def create_workflow_task_card(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not episode_id:
        raise ValueError("缺少 episodeId")
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "新建画布任务卡")
    node_type = str(payload.get("nodeType") or payload.get("node_type") or payload.get("type") or "").strip()
    if not _workflow_task_node_allowed(node_type):
        raise ValueError("只能新建视频生成")
    _assert_new_workflow_node_type_allowed(node_type, allow_independent_video_task=True)

    node_id = str(payload.get("nodeId") or "").strip() or _workflow_new_node_id(node_type.replace(".", "_"))
    if _canvas_node_exists_v4(project_id, episode_id, node_id):
        raise ValueError("节点 id 已存在")
    route_id = ""
    work_chain_id = ""
    segment_id = ""
    strategy = standalone_video_strategy(node_type)
    position = _workflow_position_payload(payload.get("position"), {"x": 120, "y": 120})
    data_patch = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    generation_config = (
        payload.get("generationConfig")
        if isinstance(payload.get("generationConfig"), dict)
        else data_patch.get("generationConfig")
        if isinstance(data_patch.get("generationConfig"), dict)
        else {}
    )
    generation_config = (
        _workflow_keyframe_video_generation_config(generation_config)
        if node_type == "video.keyframe"
        else _workflow_character_replace_generation_config(generation_config)
        if node_type == CHARACTER_REPLACE_TASK
        else _workflow_standalone_video_generation_config(generation_config)
    )
    node_size = _workflow_layout_size(node_type, payload.get("size")) or _workflow_default_card_size(node_type)
    created_at = _now()
    node = {
        "id": node_id,
        "type": node_type,
        "workChainId": work_chain_id,
        "routeId": route_id,
        "segmentId": segment_id,
        "strategy": strategy,
        "position": position,
        "data": {
            "title": str(payload.get("title") or data_patch.get("title") or "任务卡"),
            "status": str(payload.get("status") or data_patch.get("status") or "draft"),
            "summary": str(payload.get("summary") or data_patch.get("summary") or ""),
            "workChainId": work_chain_id,
            "routeId": route_id,
            "segmentId": segment_id,
            "strategy": strategy,
            "prompt": data_patch.get("prompt", payload.get("prompt", "")),
            "generationConfig": copy.deepcopy(generation_config),
            **({"durationSeconds": generation_config["durationSeconds"]} if node_type == CHARACTER_REPLACE_TASK else {}),
            "cardState": {"size": node_size},
            "videoTaskCard": {
                "promptKind": "final_provider_prompt",
                "videoPromptKind": "final_provider_prompt",
                "sourceAdapter": "standalone_direct_prompt",
                **copy.deepcopy(data_patch.get("videoTaskCard") if isinstance(data_patch.get("videoTaskCard"), dict) else {}),
            },
            "provenance": {
                "source": "user",
                "action": "canvas_task_node_created",
                "createdAt": created_at,
            },
        },
    }
    _ensure_saved_workflow_node_contract(node)

    result_node: dict[str, Any] | None = None
    result_edge: dict[str, Any] | None = None
    result_node_type = _workflow_create_task_result_type(node_type)
    nodes_to_write = [node]
    edges_to_write: list[dict[str, Any]] = []
    if result_node_type:
        result_node_id = str(payload.get("resultNodeId") or "").strip() or _workflow_new_node_id(result_node_type.replace(".", "_"))
        if _canvas_node_exists_v4(project_id, episode_id, result_node_id):
            raise ValueError("结果节点 id 已存在")
        result_size = _workflow_default_card_size(result_node_type)
        result_position = _workflow_position_payload(
            payload.get("resultPosition"),
            {"x": position["x"] + node_size.get("width", 340) + 120, "y": position["y"]},
        )
        result_node = {
            "id": result_node_id,
            "type": result_node_type,
            "workChainId": work_chain_id,
            "routeId": route_id,
            "segmentId": segment_id,
            "strategy": strategy,
            "position": result_position,
            "data": {
                "title": "视频片段",
                "status": "waiting_upstream",
                "summary": "等待视频节点生成并写入结果视频。",
                "workChainId": work_chain_id,
                "routeId": route_id,
                "segmentId": segment_id,
                "strategy": strategy,
                "resultOfNodeId": node_id,
                "assetScope": "result",
                "assetKind": "video",
                "mediaPurpose": "video_result",
                "visibilityScope": "workChain" if work_chain_id else "global",
                "cardState": {"size": result_size},
                "provenance": {
                    "source": "user",
                    "action": "canvas_video_result_created" if result_node_type == "video.result" else "canvas_storyboard_result_created",
                    "createdAt": created_at,
                    "resultOfNodeId": node_id,
                },
            },
        }
        _ensure_saved_workflow_node_contract(result_node)
        nodes_to_write.append(result_node)
        result_edge = {
            "id": f"dependency-{node_id}-{result_node_id}-generates",
            "source": node_id,
            "target": result_node_id,
            "sourceHandle": "video" if result_node_type == "video.result" else "prompt",
            "targetHandle": "generates",
            "deletable": False,
            "data": {
                "kind": "dependency",
                "role": "generates",
                "sourceNodeType": node_type,
                "targetNodeType": result_node_type,
                "targetSlot": "generates",
                "workChainId": work_chain_id,
                "routeId": route_id,
                "segmentId": segment_id,
                "locked": True,
                "preserveOnReplan": True,
                "lockedReason": "任务节点的系统结果链接不可删除",
            },
        }
        _ensure_saved_workflow_edge_contract(
            result_edge,
            {str(item.get("id") or ""): item for item in nodes_to_write},
            {"nodes": nodes_to_write},
        )
        edges_to_write.append(result_edge)

    save_result = write_canvas_records_v4(
        project_id,
        episode_id,
        nodes=nodes_to_write,
        edges=edges_to_write,
        op_type="structure_patch",
        changed_resources=["canvas_node", "canvas_edge"],
        expected_revision=payload.get("expectedRevision") or payload.get("expected_revision"),
    )
    _touch_project_meta(project_id)
    result = {
        "success": True,
        "episodeId": episode_id,
        "node": copy.deepcopy(node),
        "resultNode": copy.deepcopy(result_node),
        "edge": copy.deepcopy(result_edge),
        "nodes": [copy.deepcopy(item) for item in nodes_to_write],
        "edges": [copy.deepcopy(item) for item in edges_to_write],
        "workflowVersion": save_result.get("workflowVersion"),
        **_workflow_mutation_event_fields(save_result),
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id},
        "projectChanged": True,
    }
    return result


def add_workflow_asset_nodes(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not episode_id:
        raise ValueError("缺少 episodeId")
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "添加画布资产节点")
    incoming_nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    if not incoming_nodes:
        raise ValueError("缺少要添加的资产节点")
    project_assets_by_type: dict[str, dict[str, Any]] = {}

    def project_assets_for_type(asset_type: str) -> dict[str, Any]:
        asset_type = str(asset_type or "").strip()
        if not asset_type:
            return {}
        if asset_type not in project_assets_by_type:
            project_assets_by_type[asset_type] = list_assets(
                "project",
                project_id,
                hydrate=False,
                include_source_metadata=False,
                asset_type=asset_type,
                lifecycle_status=ASSET_LIFECYCLE_ACTIVE,
            )
        return project_assets_by_type[asset_type]

    added_nodes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in incoming_nodes:
        if not isinstance(row, dict):
            continue
        node = copy.deepcopy(row)
        node_type = str(node.get("type") or (node.get("data") if isinstance(node.get("data"), dict) else {}).get("eyebrow") or "asset.image").strip()
        if not (
            node_type == "asset.image"
            or node_type == "media.external"
            or node_type == "video.result"
            or node_type == "storyboard.image"
        ):
            raise ValueError("资产节点接口只支持画布素材节点")
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        has_work_chain_identity = bool(
            str(node.get("workChainId") or node.get("work_chain_id") or "").strip()
            or str(node.get("routeId") or node.get("route_id") or "").strip()
            or str(node.get("segmentId") or node.get("segment_id") or "").strip()
            or str(data.get("workChainId") or data.get("work_chain_id") or "").strip()
            or str(data.get("routeId") or data.get("route_id") or "").strip()
            or str(data.get("segmentId") or data.get("segment_id") or "").strip()
        )
        source_type = str(data.get("sourceType") or data.get("source_type") or "").strip()
        independent_storyboard_copy = (
            node_type == "storyboard.image"
            and not has_work_chain_identity
            and (
                str(data.get("canvasNodeRole") or data.get("canvas_node_role") or "").strip()
                == _CANVAS_NODE_ROLE_IMAGE_ASSET
                or source_type in {"version", "generated_media"}
                or data.get("copiedFromNodeId")
                or data.get("copied_from_node_id")
            )
        )
        independent_video_copy = (
            node_type == "video.result"
            and not has_work_chain_identity
            and (
                source_type in {"version", "generated_video"}
                or data.get("copiedFromNodeId")
                or data.get("copied_from_node_id")
            )
        )
        if not independent_storyboard_copy and not independent_video_copy:
            _assert_new_workflow_node_type_allowed(node_type)
        node_id = str(node.get("id") or "").strip() or _workflow_new_node_id("asset_image")
        if node_id in seen_ids or _canvas_node_exists_v4(project_id, episode_id, node_id):
            raise ValueError("节点 id 已存在")
        seen_ids.add(node_id)
        node["id"] = node_id
        node["type"] = node_type
        node["position"] = _workflow_position_payload(node.get("position"), {"x": 120, "y": 120})
        node["data"] = data
        asset_type = str(data.get("assetType") or data.get("assetKind") or "").strip()
        asset_id = str(data.get("assetId") or "").strip()
        asset_name = str(data.get("assetName") or data.get("title") or "").strip()
        if node_type == "asset.image":
            if not asset_type or not asset_id:
                raise ValueError("资产节点缺少 assetType 或 assetId")
            if not _workflow_canvas_asset_exists(
                project_assets_for_type(asset_type),
                asset_type,
                asset_id,
            ):
                raise ValueError(f"资产不存在或已被删除：{asset_name or asset_id}")
            data.setdefault("rootAssetType", _workflow_normalize_asset_type(asset_type))
            data.setdefault("rootAssetId", asset_id)
            data.setdefault("rootAssetProjectId", project_id)
        if node_type == "media.external":
            media_purpose = str(data.get("mediaPurpose") or data.get("media_purpose") or "").strip()
            media = data.get("media") if isinstance(data.get("media"), dict) else data.get("storage")
            media = media if isinstance(media, dict) else {}
            media_kind = str(
                data.get("mediaKind")
                or data.get("mediaType")
                or media.get("kind")
                or media.get("mediaType")
                or media.get("media_type")
                or ""
            ).strip().lower()
            if media_purpose not in {
                "custom_image",
                "character_reference",
                "creature_reference",
                "scene_reference",
                "prop_reference",
                "storyboard_image",
                "visual_handoff",
                "visual_reference",
            }:
                raise ValueError("外部媒体素材类型只支持媒体参考或视觉交接")
            if not asset_name:
                raise ValueError(f"{_workflow_media_purpose_label(media_purpose)}名称不能为空")
            if media_purpose == "custom_image" and media_kind == "video":
                raise ValueError("自定义图片不能使用视频媒体")
            title_asset_type = _workflow_project_asset_type_from_media_purpose(media_purpose)
            if title_asset_type and _workflow_project_asset_name_exists(
                project_assets_for_type(title_asset_type),
                title_asset_type,
                asset_name,
            ):
                raise FileExistsError(f"{_asset_type_label(title_asset_type)}名称已存在")
        data.setdefault("title", asset_name or asset_id)
        data.setdefault("status", "ready")
        data.setdefault("summary", "")
        data.setdefault(
            "sourceType",
            "asset"
            if node_type == "asset.image"
            else "external_media"
            if node_type == "media.external"
            else "generated_video"
            if node_type == "video.result"
            else "generated_media",
        )
        if node_type in {"asset.image", "media.external", "storyboard.image"}:
            data["canvasNodeRole"] = _CANVAS_NODE_ROLE_IMAGE_ASSET
            data.pop("canvas_node_role", None)
        data.setdefault("assetScope", "reusable")
        if asset_type:
            data.setdefault("assetKind", asset_type)
            data.setdefault("assetType", asset_type)
        if asset_id:
            data.setdefault("assetId", asset_id)
        if asset_name or asset_id:
            data.setdefault("assetName", asset_name or data.get("title") or asset_id)
        data.setdefault("visibilityScope", "workChain" if data.get("workChainId") or node.get("workChainId") else "global")
        data.setdefault(
            "provenance",
            {
                "source": "user",
                "action": "canvas_asset_node_created",
                "createdAt": _now(),
            },
        )
        card_state = data.get("cardState") if isinstance(data.get("cardState"), dict) else {}
        card_state.setdefault("size", _workflow_default_card_size(node_type))
        data["cardState"] = card_state
        _ensure_saved_workflow_node_contract(node)
        added_nodes.append(node)
    if not added_nodes:
        raise ValueError("没有可添加的资产节点")
    save_result = write_canvas_records_v4(
        project_id,
        episode_id,
        nodes=added_nodes,
        op_type="structure_patch",
        changed_resources=["canvas_node"],
        expected_revision=payload.get("expectedRevision") or payload.get("expected_revision"),
    )
    _touch_project_meta(project_id)

    mutation_fields = _workflow_mutation_event_fields(save_result)
    result = {
        "success": True,
        "episodeId": episode_id,
        "nodes": copy.deepcopy(added_nodes),
        "workflowVersion": save_result.get("workflowVersion"),
        **mutation_fields,
        "focusTarget": {
            "section": "episode",
            "episodeId": episode_id,
            "nodeId": str(added_nodes[-1].get("id") or ""),
        },
        "projectChanged": True,
    }
    return result
