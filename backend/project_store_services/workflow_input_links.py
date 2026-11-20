# -*- coding: utf-8 -*-
"""画布输入关联与解除关联领域。

这里承载工作流输入 link/unlink、参考视频源准备和关联校验。
旧 workflows API 通过直接名称绑定保持兼容。
"""

from __future__ import annotations
from .canvas_ownership import VIDEO_TASK_NODE_TYPES
from .workflow_reference_usage import reference_enabled, reference_identity, reference_usage_key
from .workflow_input_resolution import _resolve_workflow_node_inputs_from_workflow

import copy
import traceback
from .canvas_store_queries import read_canvas_card_record_v4
from .canvas_store_database import retry_canvas_mutation_v4
from .store_core import (
    _JSON_WRITE_LOCK,
)
from .workflow_asset_resolution import (
    resolve_workflow_node_inputs,
)
from .workflow_contract import (
    _node_route_id,
    _node_segment_id,
    _workflow_accepts_material_input,
    _workflow_mutation_returns_workflow,
)
from .workflow_input_resolution import (
    _workflow_input_scope,
)
from typing import (
    Any,
)

import uuid

from utils.frame_references import (
    FRAME_IMAGE,
    FRAME_SLOT,
    frame_options,
    is_frame_image,
)
from utils.video_references import (
    VIDEO_REFERENCE_SLOT,
    prepare_reference_video,
    reference_video_limits,
    validate_reference_video_durations,
    validate_reference_videos,
)

from .canvas_store_queries import (
    read_workflow_card_neighborhood_v4,
)
from .canvas_store_database import validate_canvas_revision_v4
from .canvas_store_mutations import write_canvas_records_v4
from .media_files import (
    _copy_local_project_video_media_file,
    _local_video_source_from_media,
    video_media_metadata,
    original_reference_video_media,
)
from .planning_contract import _is_user_locked_item
from .generation_config import _video_task_card_target_model_context
from .projects import _touch_project_meta
from .store_core import _now
from .workflow_inline_editing import _video_task_reference_image_count_for_validation
from .workflow_contract import (
    _workflow_mutation_event_fields,
    _CANVAS_NODE_ROLE_IMAGE_ASSET,
    _VISUAL_HANDOFF_SLOT,
    _WORKFLOW_VIDEO_TASK_SCOPE_STANDALONE,
    _canonical_workflow_slot,
    _ensure_saved_workflow_edge_contract,
    _ensure_saved_workflow_node_contract,
    _node_work_chain_id,
    _workflow_asset_target_slot,
    _workflow_is_default_work_chain_storyboard_result,
    _workflow_is_default_work_chain_video_result,
    _workflow_is_material_source,
    _workflow_is_video_task_type,
    _workflow_locked_system_edge_key,
    _workflow_material_source_handle,
    _workflow_material_target_handle,
    _workflow_node,
    _workflow_node_is_visual_handoff_asset_like,
    _workflow_node_media_kind,
    _workflow_node_type_value,
    _workflow_validate_material_slot,
    _workflow_video_task_material_source_error,
    workflow_video_task_scope,
)
from .workflow_input_resolution import (
    _input_link_matches,
    _next_input_links,
    _populate_workflow_video_reference_views,
    _upsert_workflow_material_edge,
    _workflow_canvas_asset_node_project_asset_identity,
    _workflow_input_action,
    _workflow_input_affected_ids,
    _workflow_input_link_direct_ids,
    _workflow_input_link_material_signature,
    _workflow_material_edge_for_input_link,
    _workflow_material_edge_signature,
    _workflow_material_input_response_nodes,
    _workflow_remove_edges_from_memory,
    _workflow_video_task_node_ids,
    workflow_current_media_reference,
    workflow_reference_video_input_links,
    _workflow_source_node_input_link_fields,
)

def _prepare_linked_reference_video_source(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    source_node: dict[str, Any],
    target_node: dict[str, Any],
    model_context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a visible normalized video node when provider limits require it."""
    original_source_node_id = str(source_node.get("id") or "")
    target_model_id = str(model_context.get("modelId") or "").strip()
    source_data = source_node.get("data") if isinstance(source_node.get("data"), dict) else {}
    source_provenance = source_data.get("provenance") if isinstance(source_data.get("provenance"), dict) else {}
    if (
        str(source_provenance.get("action") or "") == "reference_video_normalized"
        and str(source_provenance.get("modelId") or "") == target_model_id
    ):
        source_media = source_data.get("media") if isinstance(source_data.get("media"), dict) else {}
        if source_media:
            source_metadata = video_media_metadata(project_id, source_media)
            validate_reference_videos([source_metadata], model_context)
            processing = source_data.get("referenceVideoProcessing") if isinstance(source_data.get("referenceVideoProcessing"), dict) else {}
            return source_node, {"status": "ready", "reused": True, **copy.deepcopy(processing), "mediaNodeId": original_source_node_id}
    for candidate in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
        if not isinstance(candidate, dict) or str(candidate.get("type") or "") != "media.external":
            continue
        candidate_data = candidate.get("data") if isinstance(candidate.get("data"), dict) else {}
        provenance = candidate_data.get("provenance") if isinstance(candidate_data.get("provenance"), dict) else {}
        if (
            str(provenance.get("action") or "") == "reference_video_normalized"
            and str(provenance.get("sourceNodeId") or "") == original_source_node_id
            and str(provenance.get("modelId") or "") == target_model_id
        ):
            candidate_media = candidate_data.get("media") if isinstance(candidate_data.get("media"), dict) else {}
            if candidate_media:
                candidate_metadata = video_media_metadata(project_id, candidate_media)
                validate_reference_videos([candidate_metadata], model_context)
                processing = candidate_data.get("referenceVideoProcessing") if isinstance(candidate_data.get("referenceVideoProcessing"), dict) else {}
                return candidate, {"status": "ready", "reused": True, **copy.deepcopy(processing), "mediaNodeId": str(candidate.get("id") or "")}
    source_media = workflow_current_media_reference(
        project_id,
        episode_id,
        workflow,
        str(source_node.get("id") or ""),
    )
    if not isinstance(source_media, dict):
        source_data = source_node.get("data") if isinstance(source_node.get("data"), dict) else {}
        source_media = source_data.get("media") if isinstance(source_data.get("media"), dict) else {}
    if not source_media:
        raise ValueError("无法读取所关联视频的本地媒体信息")
    linked_media = source_media
    source_media = original_reference_video_media(source_media)
    source_path = _local_video_source_from_media(source_media)
    if source_path is None:
        raise ValueError("关联视频缺少本地文件，无法按模型规格处理")
    source_metadata = video_media_metadata(project_id, source_media)
    limits = reference_video_limits(model_context)
    from .video_clips import _media_tool_executable

    with prepare_reference_video(
        source_path[0],
        source_metadata,
        limits,
        ffmpeg=_media_tool_executable("ffmpeg"),
    ) as (prepared_path, processing):
        if not processing.get("compressed") and source_media == linked_media:
            validate_reference_videos([source_metadata], model_context)
            return source_node, {
                "status": "ready",
                "compressed": False,
                "sourceNodeId": str(source_node.get("id") or ""),
                "mediaId": str(source_metadata.get("id") or source_media.get("id") or ""),
            }
        media_id = f"reference-video-{uuid.uuid4().hex[:12]}"
        stored_media = _copy_local_project_video_media_file(
            project_id,
            prepared_path,
            media_id=media_id,
            subdir="videos",
            original_name=str(source_metadata.get("originalName") or "参考视频.mp4"),
            source_mime="video/mp4",
            storage_scope="episode_results",
            episode_id=episode_id,
        )
    normalized_media = video_media_metadata(project_id, stored_media)
    normalized_media["referenceVideoOriginal"] = copy.deepcopy(source_media)
    validate_reference_videos([normalized_media], model_context)
    source_data = source_node.get("data") if isinstance(source_node.get("data"), dict) else {}
    source_title = str(source_data.get("title") or source_node.get("id") or "参考视频").strip()
    derived_id = f"media_external_{uuid.uuid4().hex[:10]}"
    target_data = target_node.get("data") if isinstance(target_node.get("data"), dict) else {}
    position = source_node.get("position") if isinstance(source_node.get("position"), dict) else {"x": 640, "y": 240}
    derived_position = {
        "x": float(position.get("x") or 0) + 300,
        "y": float(position.get("y") or 0) + 40,
    }
    provenance = {
        "source": "system",
        "action": "reference_video_normalized",
        "createdAt": _now(),
        "sourceNodeId": str(source_node.get("id") or ""),
        "sourceMediaId": str(source_metadata.get("id") or source_media.get("id") or ""),
        "modelId": target_model_id,
        "processing": copy.deepcopy(processing),
    }
    derived_data = {
        "title": f"{source_title}（参考视频）",
        "status": "ready",
        "summary": "已按当前视频模型的参考视频规格自动压缩，供视频生成使用。",
        "workChainId": target_node.get("workChainId") or target_data.get("workChainId") or "",
        "routeId": target_node.get("routeId") or target_data.get("routeId") or "",
        "segmentId": target_node.get("segmentId") or target_data.get("segmentId") or "",
        "visibilityScope": "workChain" if target_node.get("workChainId") or target_data.get("workChainId") else "global",
        "sourceType": "external_media",
        "canvasNodeRole": _CANVAS_NODE_ROLE_IMAGE_ASSET,
        "mediaPurpose": "video",
        "preferredTargetSlot": VIDEO_REFERENCE_SLOT,
        "assetScope": "result",
        "assetKind": "video",
        "mediaId": str(normalized_media.get("id") or media_id),
        "media": copy.deepcopy(normalized_media),
        "storage": copy.deepcopy(normalized_media),
        "sourceFileName": str(normalized_media.get("originalName") or "参考视频.mp4"),
        "referenceVideoProcessing": copy.deepcopy(processing),
        "provenance": provenance,
        "cardState": {"size": {"width": 240, "height": 260, "minWidth": 220, "minHeight": 220}},
    }
    derived_node = {
        "id": derived_id,
        "type": "media.external",
        "position": derived_position,
        "workChainId": derived_data["workChainId"],
        "routeId": derived_data["routeId"],
        "segmentId": derived_data["segmentId"],
        "data": derived_data,
    }
    _ensure_saved_workflow_node_contract(derived_node)
    _workflow_replace_node_in_memory(workflow, derived_node)
    return derived_node, {
        "status": "ready",
        "compressed": True,
        "sourceNodeId": str(source_node.get("id") or ""),
        "mediaNodeId": derived_id,
        "mediaId": str(normalized_media.get("id") or media_id),
        **copy.deepcopy(processing),
    }


def _workflow_replace_node_in_memory(workflow: dict[str, Any], node: dict[str, Any]) -> None:
    node_id = str((node or {}).get("id") or "").strip()
    if not node_id:
        return
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    replaced = False
    for index, row in enumerate(nodes):
        if isinstance(row, dict) and str(row.get("id") or "").strip() == node_id:
            nodes[index] = copy.deepcopy(node)
            replaced = True
            break
    if not replaced:
        nodes.append(copy.deepcopy(node))
    workflow["nodes"] = nodes


def _link_workflow_input_fast_v4(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    scope = _workflow_input_scope(payload)
    if scope != "node":
        return None
    target_node_id = str(
        payload.get("targetNodeId")
        or payload.get("target_node_id")
        or payload.get("nodeId")
        or payload.get("node_id")
        or ""
    ).strip()
    source_node_id = str(payload.get("sourceNodeId") or payload.get("source_node_id") or "").strip()
    if not target_node_id or not source_node_id:
        return None

    workflow = read_workflow_card_neighborhood_v4(project_id, episode_id, target_node_id, detail="full")
    validate_canvas_revision_v4(workflow["version"], payload.get("expectedRevision", payload.get("expected_revision")))
    target_node = _workflow_node(workflow, target_node_id)
    if not target_node:
        raise FileNotFoundError("目标节点不存在")
    if not _workflow_accepts_material_input(target_node):
        raise ValueError("素材输入只能链接到分镜脚本、分镜单元或视频生成")
    source_node = next(
        (
            node
            for node in workflow.get("nodes", [])
            if isinstance(node, dict) and str(node.get("id") or "").strip() == source_node_id
        ),
        None,
    )
    if source_node is None:
        source_node = read_canvas_card_record_v4(project_id, episode_id, source_node_id, detail="full")
        workflow.setdefault("nodes", []).append(copy.deepcopy(source_node))
    if not _workflow_is_material_source(source_node):
        raise ValueError("素材来源必须是 asset.image、media.external 或 storyboard.image 节点")
    target_is_video_task = _workflow_is_video_task_type(_workflow_node_type_value(target_node))
    target_video_task_scope = (
        workflow_video_task_scope(workflow, target_node) if target_is_video_task else ""
    )
    if target_is_video_task and not target_video_task_scope:
        raise ValueError("视频生成缺少作用域标识，请重新创建任务卡")
    if (
        _workflow_is_default_work_chain_storyboard_result(workflow, source_node)
        and not target_is_video_task
    ):
        raise ValueError("分镜图只能关联视频生成")
    source_error = _workflow_video_task_material_source_error(source_node, target_node)
    if source_error:
        raise ValueError(source_error)
    requested_target_handle = payload.get("targetHandle") or payload.get("target_handle")

    action = _workflow_input_action(payload)
    slot_payload = payload.get("slot") or payload.get("targetSlot") or payload.get("target_slot")
    slot = _canonical_workflow_slot(slot_payload, "storyboard_image")
    source_asset_type = ""
    source_asset_id = ""
    if str(source_node.get("type") or "").strip() == "asset.image":
        source_asset_type, source_asset_id = _workflow_canvas_asset_node_project_asset_identity(source_node)
    if str(source_node.get("type") or "").strip() == "asset.image" and str(target_node.get("type") or "").strip() in {"director.board", "storyboard.card", *VIDEO_TASK_NODE_TYPES}:
        slot = _workflow_asset_target_slot(
            source_asset_type
            or payload.get("rootAssetType")
            or payload.get("assetType")
            or payload.get("asset_type"),
            slot,
        )
    if _workflow_node_is_visual_handoff_asset_like(source_node):
        slot = _VISUAL_HANDOFF_SLOT
    if target_is_video_task and _workflow_node_media_kind(source_node) == "video":
        slot = VIDEO_REFERENCE_SLOT
    if is_frame_image(source_node.get("data")):
        slot = FRAME_SLOT
    if (source_node.get("data") or {}).get("mediaPurpose") == "custom_image":
        slot = "custom_image"
    _workflow_validate_material_slot(target_node, slot, source_node=source_node)
    proposed = {**_workflow_source_node_input_link_fields(project_id, episode_id, workflow, source_node),
                "slot": slot, "targetSlot": slot}
    current_inputs = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, target_node_id)
    if slot == FRAME_SLOT:
        proposed.update({"assetType": FRAME_IMAGE, **frame_options(payload)})
        if "frameRole" not in payload:
            existing_frame = next((row for row in current_inputs["inputLinks"] if is_frame_image(row)
                                   and source_node_id in [row.get("sourceNodeId"), *row.get("referenceSourceNodeIds", [])]), None)
            if existing_frame is not None:
                proposed["frameRole"] = frame_options(existing_frame)["frameRole"]
    updating_frame = slot == FRAME_SLOT and any(key in payload for key in ("frameRole", "useNativeFrame")) and any(
        edge.get("source") == source_node_id and edge.get("target") == target_node_id
        for edge in workflow.get("edges", []))
    updating_display_port = bool(requested_target_handle) and any(
        edge.get("source") == source_node_id and edge.get("target") == target_node_id
        and (edge.get("data") or {}).get("kind") == "material"
        and _workflow_material_edge_signature(edge)[1:] == (target_node_id, slot)
        and edge.get("targetHandle") != _workflow_material_target_handle(
            target_node, slot, requested_target_handle, workflow=workflow,
        )
        for edge in workflow.get("edges", []) if isinstance(edge, dict)
    )
    if action == "append" and not updating_frame and not updating_display_port and any(
        reference_identity(row) == reference_identity(proposed) for row in current_inputs["inputLinks"]
    ):
        raise ValueError("该资产或参考素材已关联并启用，请勿重复关联")
    if target_is_video_task and slot == VIDEO_REFERENCE_SLOT:
        video_rows: list[dict[str, Any]] = []
        proposed_video_links = [
            item
            for item in (target_node.get("data") or {}).get("inputLinks", [])
            if isinstance(item, dict)
            and str(item.get("sourceNodeId") or item.get("source_node_id") or "").strip() != source_node_id
        ]
        proposed_video_links.append({"sourceNodeId": source_node_id, "slot": VIDEO_REFERENCE_SLOT})
        for link in workflow_reference_video_input_links(project_id, episode_id, workflow, proposed_video_links):
            media = link.get("media")
            if not isinstance(media, dict) or not media:
                raise ValueError("视频生成的参考视频当前没有可用媒体，请先解除该关联")
            video_rows.append(video_media_metadata(project_id, media))
        model_context = _video_task_card_target_model_context(
            project_id,
            target_node.get("data") or {},
            {},
            include_timing=True,
        )
        target_data = target_node.get("data") if isinstance(target_node.get("data"), dict) else {}
        output_duration = target_data.get("durationSeconds") or target_data.get("duration_seconds")
        if not output_duration and isinstance(target_data.get("generationConfig"), dict):
            output_duration = (
                target_data["generationConfig"].get("durationSeconds")
                or target_data["generationConfig"].get("duration_seconds")
            )
        validate_reference_video_durations(
            video_rows,
            model_context,
            image_count=_video_task_reference_image_count_for_validation(
                project_id, episode_id, workflow, target_node, model_context, len(video_rows),
            ),
            output_duration=output_duration or model_context.get("preferredDurationSeconds"),
        )
    reference_video_processing: dict[str, Any] = {}
    reference_video_source_derived = False
    if target_is_video_task and slot == VIDEO_REFERENCE_SLOT:
        source_node, reference_video_processing = _prepare_linked_reference_video_source(
            project_id,
            episode_id,
            workflow,
            source_node,
            target_node,
            model_context,
        )
        if str(source_node.get("id") or "") != source_node_id:
            source_node_id = str(source_node.get("id") or "")
            reference_video_source_derived = True
    # Protect the association itself, independently of its display port.
    node_by_id = {str(node.get("id") or ""): node for node in workflow.get("nodes", []) if isinstance(node, dict)}
    replaces_slot = action in {"replace_slot", "relink_slot"} or slot == _VISUAL_HANDOFF_SLOT
    existing_edges = [
        edge for edge in workflow.get("edges", []) if isinstance(edge, dict)
        and (edge.get("data") or {}).get("kind") == "material"
        and _workflow_material_edge_signature(edge)[1:] == (target_node_id, slot)
        and (replaces_slot or str(edge.get("source") or "") == source_node_id)
    ]
    existing_links = [
        link for link in (target_node.get("data") or {}).get("inputLinks", []) if isinstance(link, dict)
        and _workflow_input_link_material_signature(link, target_node_id)[1:] == (target_node_id, slot)
        and (replaces_slot or str(link.get("sourceNodeId") or "") == source_node_id)
    ]
    if any(
        _workflow_locked_system_edge_key(edge, node_by_id, workflow)
        or _is_user_locked_item(edge) or _is_user_locked_item(edge.get("data"))
        for edge in existing_edges
    ) or any(_is_user_locked_item(link) for link in existing_links):
        return {
            "success": True, "episodeId": episode_id, "targetNodeId": target_node_id,
            "skippedLocked": True, "message": "该链接已锁定，未修改。",
            "changedResources": [], "projectChanged": False,
        }
    target_handle = _workflow_material_target_handle(
        target_node,
        slot,
        requested_target_handle,
        workflow=workflow,
    )

    source_type = str(payload.get("sourceType") or payload.get("source_type") or "asset").strip() or "asset"
    if reference_video_source_derived:
        source_type = "external_media"
    if source_type == "media":
        source_type = "external_media"
    media_like_source_types = {"external_media", "generated_media", "generated", "version"}
    if reference_video_source_derived:
        source_id = source_node_id
    elif source_type in media_like_source_types:
        source_id = str(
            payload.get("sourceId")
            or payload.get("source_id")
            or payload.get("mediaId")
            or payload.get("media_id")
            or source_node_id
            or ""
        ).strip()
    else:
        source_id = source_node_id
    if not source_id:
        raise ValueError("缺少要链接的输入来源")
    route_id = str(payload.get("routeId") or payload.get("route_id") or _node_route_id(target_node) or "").strip()
    work_chain_id = str(
        payload.get("workChainId")
        or payload.get("work_chain_id")
        or _node_work_chain_id(target_node)
        or ""
    ).strip()
    segment_id = str(payload.get("segmentId") or payload.get("segment_id") or _node_segment_id(target_node) or "").strip()
    if target_video_task_scope == _WORKFLOW_VIDEO_TASK_SCOPE_STANDALONE:
        route_id = ""
        work_chain_id = ""
        segment_id = ""
    now = _now()
    locked = bool(payload.get("locked") or payload.get("lockedByUser") or payload.get("locked_by_user"))
    note = str(payload.get("note") or "").strip()
    payload_provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
    provenance_source = str(
        payload.get("source")
        or payload.get("createdBy")
        or payload.get("created_by")
        or payload_provenance.get("source")
        or "user"
    ).strip() or "user"
    input_link = {
        "id": str(payload.get("linkId") or payload.get("link_id") or f"input-link-{uuid.uuid4().hex[:10]}"),
        "label": str(payload.get("label") or source_id),
        "sourceType": source_type,
        "sourceId": source_id,
        "sourceHandle": _workflow_material_source_handle(
            source_node,
            payload.get("sourceHandle") or payload.get("source_handle"),
        ),
        "targetHandle": target_handle,
        "linkAction": action,
        "targetSlot": slot,
        "slot": slot,
        "visibilityScope": scope,
        "status": "relinked" if action == "relink_slot" else "linked",
        "locked": locked,
        "lockedByUser": locked,
        "preserveOnReplan": locked,
        "versionMode": "specific" if payload.get("versionId") or payload.get("version_id") else "recommended",
        "createdBy": str(payload.get("createdBy") or payload.get("created_by") or provenance_source),
        "provenance": {
            **copy.deepcopy(payload_provenance),
            "source": provenance_source,
            "action": str(payload_provenance.get("action") or action),
            "createdAt": str(payload_provenance.get("createdAt") or payload_provenance.get("created_at") or now),
            **({"note": note} if note else {}),
        },
        "workChainId": work_chain_id,
        "routeId": route_id,
        "segmentId": segment_id,
        "targetNodeId": target_node_id,
    }
    if reference_video_processing:
        input_link["referenceVideoProcessing"] = copy.deepcopy(reference_video_processing)
    if slot == FRAME_SLOT:
        previous = existing_links[0] if existing_links else {}
        occupied = {
            frame_options(edge.get("data") or {})["frameRole"]
            for edge in workflow.get("edges", [])
            if edge.get("target") == target_node_id
            and edge.get("source") != source_node_id
            and reference_enabled(target_node, str(edge.get("source") or ""))
            and (edge.get("data") or {}).get("targetSlot") == FRAME_SLOT
        }
        requested = {**previous, **payload}
        if not previous and "frameRole" not in payload:
            requested["frameRole"] = next((role for role in ("first_frame", "last_frame") if role not in occupied), "first_frame")
        options = frame_options(requested)
        if reference_enabled(target_node, source_node_id) and options["frameRole"] in occupied:
            raise ValueError("该用途已由另一张帧画面占用，请先移除对应关联")
        input_link.update({"assetType": FRAME_IMAGE, **options})
    if source_type in media_like_source_types:
        media_id = str(payload.get("mediaId") or payload.get("media_id") or source_id)
        input_link.update(
            {
                "mediaId": media_id,
                "mediaKind": "video" if reference_video_source_derived else str(payload.get("mediaKind") or payload.get("media_kind") or "external"),
                "mediaType": "video" if reference_video_source_derived else str(payload.get("mediaType") or payload.get("media_type") or "image"),
                **({"path": payload.get("path")} if payload.get("path") else {}),
                **({"mediaVersionId": str(payload.get("versionId") or payload.get("version_id"))} if payload.get("versionId") or payload.get("version_id") else {}),
            }
        )
    else:
        asset_id = str(payload.get("rootAssetId") or payload.get("assetId") or source_asset_id or "").strip()
        asset_type = str(payload.get("rootAssetType") or payload.get("assetType") or source_asset_type or "").strip()
        input_link.update(
            {
                **({"assetId": asset_id} if asset_id else {}),
                **({"assetType": asset_type} if asset_type else {}),
                **({"rootAssetId": asset_id} if asset_id else {}),
                **({"rootAssetType": asset_type} if asset_type else {}),
                **({"assetVersionId": str(payload.get("versionId") or payload.get("version_id"))} if payload.get("versionId") or payload.get("version_id") else {}),
            }
        )

    before_edge_ids = {
        str(edge.get("id") or "").strip()
        for edge in workflow.get("edges", [])
        if isinstance(edge, dict) and str(edge.get("id") or "").strip()
    }
    _upsert_workflow_material_edge(
        workflow,
        source_node=source_node,
        target_node=target_node,
        input_link=input_link,
        slot=slot,
        action=action,
        route_id=route_id,
        segment_id=segment_id,
        work_chain_id=work_chain_id,
    )
    slot = _canonical_workflow_slot(input_link.get("targetSlot") or input_link.get("slot"), slot)
    material_edge = _workflow_material_edge_for_input_link(workflow, str(input_link.get("id") or ""))
    if not material_edge:
        raise ValueError("素材链接边创建失败")
    data = target_node.setdefault("data", {})
    if not isinstance(data, dict):
        data = {}
        target_node["data"] = data
    data["inputLinks"] = _next_input_links(
        data.get("inputLinks"),
        input_link,
        action=action,
        slot=slot,
        scope=scope,
        target_node_id=target_node_id,
        route_id=route_id,
        work_chain_id=work_chain_id,
    )
    # An explicit new association can restore a source that was disabled here
    # or upstream. A downstream usage switch alone cannot bypass inheritance.
    if not updating_frame:
        data["referenceUsage"] = {**(data.get("referenceUsage") or {}),
                                  source_node_id: True, reference_usage_key(proposed): True}
    if target_is_video_task and slot != VIDEO_REFERENCE_SLOT:
        # Validate the proposed links before either the card or its edges are persisted.
        model_context = _video_task_card_target_model_context(project_id, data, {})
        video_count = len(workflow_reference_video_input_links(
            project_id, episode_id, workflow, data["inputLinks"],
        ))
        _video_task_reference_image_count_for_validation(
            project_id, episode_id, workflow, target_node, model_context, video_count,
        )
    _ensure_saved_workflow_node_contract(target_node)
    after_edge_ids = {
        str(edge.get("id") or "").strip()
        for edge in workflow.get("edges", [])
        if isinstance(edge, dict) and str(edge.get("id") or "").strip()
    }
    removed_edge_ids = sorted(before_edge_ids - after_edge_ids)
    affected_node_ids = _workflow_input_affected_ids(
        workflow,
        scope=scope,
        target_node=target_node,
        route_id=route_id,
        work_chain_id=work_chain_id,
        payload=payload,
    )
    input_link["affectedNodeIds"] = sorted(affected_node_ids)
    if reference_video_source_derived:
        affected_node_ids.add(str(source_node.get("id") or ""))
        input_link["affectedNodeIds"] = sorted(affected_node_ids)
    _ensure_saved_workflow_edge_contract(
        material_edge,
        {
            str(source_node.get("id") or ""): source_node,
            str(target_node.get("id") or ""): target_node,
        },
        workflow,
    )
    save_result = write_canvas_records_v4(
        project_id,
        episode_id,
        nodes=[
            copy.deepcopy(target_node),
            *([copy.deepcopy(source_node)] if reference_video_source_derived else []),
        ],
        edges=[copy.deepcopy(material_edge)],
        delete_edge_ids=removed_edge_ids,
        op_type="structure_patch",
        changed_resources=["canvas_node", "canvas_edge"],
        expected_revision=workflow["version"],
    )
    _touch_project_meta(project_id)
    mutation_fields = _workflow_mutation_event_fields(save_result, ["canvas_node", "canvas_edge"])
    _workflow_remove_edges_from_memory(workflow, removed_edge_ids)
    synced_video_task_node_ids = sorted(_workflow_video_task_node_ids(workflow, affected_node_ids))
    _populate_workflow_video_reference_views(
        project_id,
        episode_id,
        workflow,
        set(synced_video_task_node_ids),
    )
    workflow_version = save_result.get("workflowVersion")
    if workflow_version:
        workflow["version"] = workflow_version
    response_node_ids = {
        target_node_id,
        *affected_node_ids,
        *synced_video_task_node_ids,
    }
    if reference_video_source_derived:
        response_node_ids.add(str(source_node.get("id") or ""))
    from .workflow_projection import _populate_workflow_material_reference_views
    _populate_workflow_material_reference_views(project_id, episode_id, workflow, response_node_ids)
    response_base_nodes = _workflow_material_input_response_nodes(
        project_id,
        episode_id,
        workflow,
        response_node_ids,
    )
    if not any(str(node.get("id") or "").strip() == target_node_id for node in response_base_nodes):
        response_base_nodes.append(copy.deepcopy(target_node))
    response_nodes = response_base_nodes
    response_node = next(
        (
            copy.deepcopy(node)
            for node in response_nodes
            if str(node.get("id") or "").strip() == target_node_id
        ),
        copy.deepcopy(target_node),
    )
    return {
        "success": True,
        "episodeId": episode_id,
        "inputLink": input_link,
        "node": response_node,
        "nodes": response_nodes,
        "edge": copy.deepcopy(material_edge),
        "removedEdgeIds": removed_edge_ids,
        "affectedNodeIds": sorted(affected_node_ids),
        "syncedVideoTaskNodeIds": synced_video_task_node_ids,
        "targetNodeId": target_node_id,
        "workflowVersion": workflow_version,
        **mutation_fields,
    }


def _unlink_workflow_input_fast_v4(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    scope = _workflow_input_scope(payload)
    if scope != "node":
        return None
    target_node_id = str(
        payload.get("targetNodeId")
        or payload.get("target_node_id")
        or payload.get("nodeId")
        or payload.get("node_id")
        or ""
    ).strip()
    if not target_node_id:
        return None
    workflow = read_workflow_card_neighborhood_v4(project_id, episode_id, target_node_id, detail="full")
    validate_canvas_revision_v4(workflow["version"], payload.get("expectedRevision", payload.get("expected_revision")))
    target_node = _workflow_node(workflow, target_node_id)
    if not target_node:
        raise FileNotFoundError("目标节点不存在")
    if _workflow_is_default_work_chain_video_result(workflow, target_node):
        raise ValueError("工作链视频生成和视频片段由默认工作链维护，不能取消链接")
    slot = _canonical_workflow_slot(payload.get("slot") or payload.get("targetSlot"), "")
    link_id = str(payload.get("linkId") or payload.get("link_id") or "").strip()
    source_id = str(payload.get("sourceId") or payload.get("source_id") or "").strip()
    payload_source_node_id = str(payload.get("sourceNodeId") or payload.get("source_node_id") or "").strip()
    route_id = str(payload.get("routeId") or payload.get("route_id") or _node_route_id(target_node) or "").strip()
    work_chain_id = str(
        payload.get("workChainId")
        or payload.get("work_chain_id")
        or _node_work_chain_id(target_node)
        or ""
    ).strip()

    def should_remove(link: Any) -> bool:
        if not isinstance(link, dict):
            return False
        if link_id and link_id not in _workflow_input_link_direct_ids(link):
            return False
        if source_id and str(link.get("sourceId") or link.get("mediaId") or "") != source_id:
            return False
        if payload_source_node_id and str(link.get("sourceNodeId") or link.get("source_node_id") or "") != payload_source_node_id:
            return False
        if slot and not _input_link_matches(
            link,
            slot=slot,
            scope=scope,
            target_node_id=target_node_id,
            route_id=route_id,
            work_chain_id=work_chain_id,
        ):
            return False
        return bool(link_id or source_id or slot)

    data = target_node.setdefault("data", {})
    if not isinstance(data, dict):
        data = {}
        target_node["data"] = data
    links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
    kept_links: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for link in links:
        if should_remove(link):
            if _is_user_locked_item(link):
                return {
                    "success": True,
                    "message": "该链接已锁定，未取消。",
                    "episodeId": episode_id,
                    "targetNodeId": target_node_id,
                    "skippedLocked": True,
                    "changedResources": [],
                    "projectChanged": False,
                }
            removed.append(copy.deepcopy(link))
        elif isinstance(link, dict):
            kept_links.append(link)
    payload_link_signature = (
        payload_source_node_id,
        target_node_id,
        slot,
    ) if payload_source_node_id and target_node_id and slot else ("", "", "")
    fallback_removed_edge_ids = {
        str(edge.get("id") or "").strip()
        for edge in workflow.get("edges", [])
        if isinstance(edge, dict)
        and isinstance(edge.get("data"), dict)
        and str(edge.get("data", {}).get("kind") or "") == "material"
        and str(edge.get("target") or "").strip() == target_node_id
        and (
            (link_id and str(edge.get("data", {}).get("inputLinkId") or "") == link_id)
            or (all(payload_link_signature) and _workflow_material_edge_signature(edge) == payload_link_signature)
        )
        and str(edge.get("id") or "").strip()
    }
    if not removed and not fallback_removed_edge_ids:
        return {
            "success": True, "episodeId": episode_id, "targetNodeId": target_node_id,
            "removedLinks": [], "removedLinkIds": [], "removedEdgeIds": [],
            "changedResources": [], "projectChanged": False,
        }
    if removed:
        data["inputLinks"] = kept_links
    affected_node_ids = _workflow_input_affected_ids(
        workflow,
        scope=scope,
        target_node=target_node,
        route_id=route_id,
        work_chain_id=work_chain_id,
        payload=payload,
    )
    removed_link_ids = {
        link_direct_id
        for link in removed
        for link_direct_id in _workflow_input_link_direct_ids(link)
    }
    if link_id:
        removed_link_ids.add(link_id)
    removed_link_signatures = {
        signature
        for signature in (
            _workflow_input_link_material_signature(link, target_node_id)
            for link in removed
            if isinstance(link, dict)
        )
        if all(signature)
    }
    if all(payload_link_signature):
        removed_link_signatures.add(payload_link_signature)
    removed_edge_ids = {
        str(edge.get("id") or "").strip()
        for edge in workflow.get("edges", [])
        if isinstance(edge, dict)
        and isinstance(edge.get("data"), dict)
        and str(edge.get("data", {}).get("kind") or "") == "material"
        and str(edge.get("target") or "").strip() == target_node_id
        and (
            str(edge.get("data", {}).get("inputLinkId") or "") in removed_link_ids
            or _workflow_material_edge_signature(edge) in removed_link_signatures
        )
        and str(edge.get("id") or "").strip()
    }
    removed_edge_ids.update(fallback_removed_edge_ids)
    _workflow_remove_edges_from_memory(workflow, removed_edge_ids)
    save_result = write_canvas_records_v4(
        project_id,
        episode_id,
        delete_edge_ids=sorted(removed_edge_ids),
        nodes=[copy.deepcopy(target_node)],
        op_type="structure_patch",
        changed_resources=["canvas_node", "canvas_edge"],
        expected_revision=workflow["version"],
    )
    _touch_project_meta(project_id)
    mutation_fields = _workflow_mutation_event_fields(save_result, ["canvas_node", "canvas_edge"])
    synced_video_task_node_ids = sorted(_workflow_video_task_node_ids(workflow, affected_node_ids))
    _populate_workflow_video_reference_views(
        project_id,
        episode_id,
        workflow,
        set(synced_video_task_node_ids),
    )
    workflow_version = save_result.get("workflowVersion")
    if workflow_version:
        workflow["version"] = workflow_version
    response_node_ids = {
        target_node_id,
        *affected_node_ids,
        *synced_video_task_node_ids,
    }
    from .workflow_projection import _populate_workflow_material_reference_views
    _populate_workflow_material_reference_views(project_id, episode_id, workflow, response_node_ids)
    response_base_nodes = _workflow_material_input_response_nodes(
        project_id,
        episode_id,
        workflow,
        response_node_ids,
    )
    if not any(str(node.get("id") or "").strip() == target_node_id for node in response_base_nodes):
        response_base_nodes.append(copy.deepcopy(target_node))
    response_nodes = response_base_nodes
    response_node = next(
        (
            copy.deepcopy(node)
            for node in response_nodes
            if str(node.get("id") or "").strip() == target_node_id
        ),
        copy.deepcopy(target_node),
    )
    return {
        "success": True,
        "episodeId": episode_id,
        "removedLinks": removed,
        "removedLinkIds": sorted(removed_link_ids),
        "removedEdgeIds": sorted(removed_edge_ids),
        "node": response_node,
        "nodes": response_nodes,
        "targetNodeId": target_node_id,
        "affectedNodeIds": sorted(affected_node_ids),
        "inputDirtyNodeIds": sorted(affected_node_ids),
        "syncedVideoTaskNodeIds": synced_video_task_node_ids,
        "workflowVersion": workflow_version,
        **mutation_fields,
    }


def _assert_workflow_input_v4_mutation(
    payload: dict[str, Any],
    *,
    require_source_node: bool = False,
    require_link_selector: bool = False,
) -> None:
    if _workflow_mutation_returns_workflow(payload):
        raise ValueError("画布输入操作不再返回完整 workflow；需要完整状态时请单独调用 get_canvas_snapshot。")
    if payload.get("baseHash") or payload.get("base_hash"):
        raise ValueError("画布输入操作不再支持 baseHash 全量写入；请使用 expectedRevision。")
    scope = _workflow_input_scope(payload)
    if scope != "node":
        raise ValueError("画布输入操作必须使用 node scope，不能创建 route/workChain/global 隐藏链接。")
    target_node_id = str(
        payload.get("targetNodeId")
        or payload.get("target_node_id")
        or payload.get("nodeId")
        or payload.get("node_id")
        or ""
    ).strip()
    if not target_node_id:
        raise ValueError("缺少目标节点 targetNodeId")
    if require_source_node:
        source_node_id = str(payload.get("sourceNodeId") or payload.get("source_node_id") or "").strip()
        if not source_node_id:
            raise ValueError("缺少来源节点 sourceNodeId")
    if require_link_selector:
        slot = str(payload.get("slot") or payload.get("targetSlot") or payload.get("target_slot") or "").strip()
        link_id = str(payload.get("linkId") or payload.get("link_id") or "").strip()
        source_id = str(payload.get("sourceId") or payload.get("source_id") or "").strip()
        if not (slot or link_id or source_id):
            raise ValueError("缺少要取消的输入链接标识")


def link_workflow_input(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _JSON_WRITE_LOCK:
        payload = payload if isinstance(payload, dict) else {}
        _assert_workflow_input_v4_mutation(payload, require_source_node=True)
        fast_result = retry_canvas_mutation_v4(
            lambda: _link_workflow_input_fast_v4(project_id, episode_id, payload),
            expected_revision=payload.get("expectedRevision", payload.get("expected_revision")),
        )
        if fast_result is not None:
            return fast_result
        raise RuntimeError("画布输入链接未进入 Canvas Runtime Store v4 写入链路")


def set_workflow_reference_usage(
    project_id: str, episode_id: str, payload: dict[str, Any],
) -> dict[str, Any]:
    """Keep material edges intact; override usage only on the consuming node."""
    _assert_workflow_input_v4_mutation(payload, require_source_node=True)
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须是布尔值")
    node_id = str(payload.get("targetNodeId") or payload.get("nodeId") or "").strip()
    source_id = str(payload.get("sourceNodeId") or "").strip()

    def mutate() -> dict[str, Any]:
        workflow = read_workflow_card_neighborhood_v4(project_id, episode_id, node_id, detail="full")
        validate_canvas_revision_v4(workflow["version"], payload.get("expectedRevision"))
        node = _workflow_node(workflow, node_id)
        if not node or not _workflow_accepts_material_input(node):
            raise ValueError("只能设置分镜脚本、分镜单元或视频生成的参考资产")
        if _is_user_locked_item(node) or _is_user_locked_item(node.get("data") or {}):
            raise ValueError("该节点已锁定，请先解锁")
        snapshot = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, node_id)
        selected = next((row for row in snapshot["referenceDisplayRows"] if source_id in
                         [row.get("sourceNodeId"), *row.get("referenceSourceNodeIds", [])]), None)
        if selected is None:
            raise ValueError("该资产已不在当前节点的关联或继承范围内")
        data = node.setdefault("data", {})
        data["referenceUsage"] = {**(data.get("referenceUsage") or {}), reference_usage_key(selected): enabled,
                                  **{source: enabled for source in [source_id, *selected.get("referenceSourceNodeIds", [])]}}
        active = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, node_id)["inputLinks"]
        roles = [frame_options(row)["frameRole"] for row in active if is_frame_image(row)]
        if len(roles) != len(set(roles)):
            raise ValueError("该首帧或尾帧用途已被占用，请先调整用途或禁用另一张帧画面")
        affected = _workflow_input_affected_ids(
            workflow, scope="node", target_node=node, route_id=_node_route_id(node),
            work_chain_id=_node_work_chain_id(node), payload=payload,
        ) | {node_id}
        saved = write_canvas_records_v4(
            project_id, episode_id, nodes=[copy.deepcopy(node)],
            op_type="structure_patch", changed_resources=["canvas_node"],
            expected_revision=workflow["version"],
        )
        _touch_project_meta(project_id)
        _populate_workflow_video_reference_views(project_id, episode_id, workflow, affected)
        from .workflow_projection import _populate_workflow_material_reference_views
        _populate_workflow_material_reference_views(project_id, episode_id, workflow, affected)
        nodes = _workflow_material_input_response_nodes(project_id, episode_id, workflow, affected)
        return {
            "success": True, "episodeId": episode_id, "targetNodeId": node_id,
            "workflowVersion": saved.get("workflowVersion"),
            "node": next(row for row in nodes if row["id"] == node_id), "nodes": nodes,
            "affectedNodeIds": sorted(affected), "inputDirtyNodeIds": sorted(affected),
            **_workflow_mutation_event_fields(saved, ["canvas_node"]),
        }

    with _JSON_WRITE_LOCK:
        return retry_canvas_mutation_v4(mutate, expected_revision=payload.get("expectedRevision"))


def _workflow_input_link_row(
    link: dict[str, Any],
    *,
    owner_scope: str,
    node: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = copy.deepcopy(link)
    row["ownerScope"] = owner_scope
    if node:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        row["nodeId"] = node.get("id")
        row["nodeType"] = node.get("type")
        row.setdefault("routeId", _node_route_id(node))
        row.setdefault("segmentId", _node_segment_id(node))
        row["nodeTitle"] = data.get("title")
    return row


def list_workflow_inputs(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    route_id = str(payload.get("routeId") or payload.get("route_id") or "").strip()
    scope = str(payload.get("scope") or payload.get("visibilityScope") or "").strip()
    if not node_id:
        raise ValueError("list_workflow_inputs 必须指定 nodeId；需要完整状态时请调用 get_canvas_snapshot。")
    node = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    source_links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
    if _workflow_accepts_material_input(node):
        source_links = resolve_workflow_node_inputs(
            project_id,
            episode_id,
            {"nodeId": node_id},
        ).get("inputLinks") or []
    rows = [
        _workflow_input_link_row(link, owner_scope="node", node=node)
        for link in source_links
        if isinstance(link, dict)
    ]
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if route_id and str(row.get("routeId") or "") != route_id:
            continue
        if scope and str(row.get("visibilityScope") or row.get("ownerScope") or "") != scope:
            continue
        filtered.append(row)
    return {"success": True, "episodeId": episode_id, "inputs": filtered}


def unlink_workflow_input(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _JSON_WRITE_LOCK:
        payload = payload if isinstance(payload, dict) else {}
        _assert_workflow_input_v4_mutation(payload, require_link_selector=True)
        fast_result = retry_canvas_mutation_v4(
            lambda: _unlink_workflow_input_fast_v4(project_id, episode_id, payload),
            expected_revision=payload.get("expectedRevision", payload.get("expected_revision")),
        )
        if fast_result is not None:
            return fast_result
        raise RuntimeError("画布输入取消未进入 Canvas Runtime Store v4 写入链路")
