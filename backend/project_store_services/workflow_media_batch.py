# -*- coding: utf-8 -*-
"""工作流批处理与媒体导入领域。

这里承载批量运行、图片/视频媒体导入和媒体记录写回；旧
workflows API 通过直接名称绑定保持兼容。
"""

from __future__ import annotations

from .media_files import _image_media_from_file_info
from .media_files import _stored_media_path
from .production_status import update_episode_production_status
from .store_core import _now
from .workflow_contract import _assert_canvas_mutation_does_not_return_workflow
from .workflow_contract import _workflow_mutation_returns_production_status
from .workflow_contract import _workflow_node
from .workflow_projection import get_canvas_workflow_projection
from .workflow_storyboard_versions import add_storyboard_version
from typing import Any
import traceback
import uuid

from .assets import (
    _asset_type_label,
    list_assets,
)
from .canvas_store_queries import read_canvas_task_context_v4, read_workflow_card_neighborhood_v4
from .canvas_store_mutations import write_canvas_records_v4
from .catalogs import (
    VIDEO_EXTENSIONS,
)
from .media_files import (
    _copy_local_project_video_media_file,
    _local_video_source_from_media,
    _project_media_storage_dir,
    _safe_file_stem,
    _video_media_from_file_info,
    video_media_metadata,
)
from .planning_contract import _CANVAS_NODE_ROLE_IMAGE_ASSET
from .generation_preflight import preflight_workflow_node
from .projects import (
    _touch_project_meta,
)
from .store_core import (
    ASSET_LIFECYCLE_ACTIVE,
)
from .workflow_asset_resolution import (
    resolve_workflow_node_inputs,
)
from .workflow_projection import _read_canvas_route_v4, _workflow_cards_mutation_write
from .workflow_contract import (
    _WORKFLOW_VIDEO_TASK_SCOPE_STANDALONE,
    _WORKFLOW_VIDEO_TASK_SCOPE_WORK_CHAIN,
    _canonical_workflow_slot,
    _ensure_saved_workflow_edge_contract,
    _ensure_saved_workflow_node_contract,
    _node_route_id,
    _node_work_chain_id,
    _workflow_accepts_material_input,
    _workflow_asset_type_from_media_purpose,
    _workflow_canvas_project_asset_type_from_value,
    _workflow_is_video_task_type,
    _workflow_media_purpose_label,
    _workflow_media_purpose_material_slot,
    _workflow_media_purpose_target_slot,
    _workflow_node_can_supply_image_reference,
    _workflow_project_asset_name_exists,
    _workflow_project_asset_type_from_media_purpose,
    _workflow_validate_material_slot,
    workflow_video_task_scope,
)
from .workflow_media_generation import build_storyboard_generation_metadata
from .workflow_generation_config import (
    _merge_version_payload_snapshots,
    _workflow_version_payload_snapshots,
)
from .workflow_input_resolution import (
    workflow_current_media_version_has_media,
)
from .workflow_planning_lifecycle import (
    _safe_episode_id,
)
from .workflow_projection import (
    _append_workflow_task,
    _read_workflow_media,
    _read_workflow_tasks,
    _write_workflow_media,
)
from .workflow_visual_handoff import (
    _cleanup_promoted_media_copy,
)
from pathlib import (
    Path,
)
from utils.frame_references import (
    FRAME_IMAGE,
    is_frame_image,
)
from utils.video_import import (
    prepare_import_video,
)
from utils.video_references import (
    VIDEO_REFERENCE_SLOT,
)



import copy
import json
import time

from .workflow_contract import _workflow_mutation_event_fields
from .workflow_contract import (
    _append_unique_string,
    _node_segment_id,
)
from .workflow_input_resolution import (
    _next_input_links,
    _upsert_workflow_material_edge,
    _workflow_downstream_node_ids,
    _workflow_material_edge_for_input_link,
)

def run_workflow_batch(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "运行画布批量生成")
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    if not node_id:
        raise ValueError("缺少 nodeId")
    workflow = read_canvas_task_context_v4(project_id, episode_id, node_id, detail="full")
    node = _workflow_node(workflow, node_id)
    if not node:
        raise FileNotFoundError("节点不存在")
    node_type = str(node.get("type") or "")
    version_type, task_type = _workflow_batch_generation_kind(node_type)
    try:
        variant_count = int(payload.get("variantCount") or payload.get("variant_count") or 3)
    except (TypeError, ValueError):
        raise ValueError("variantCount 必须是数字")
    if variant_count < 1:
        raise ValueError("variantCount 必须大于 0")
    batch_id = str(payload.get("batchId") or payload.get("batch_id") or f"batch-{uuid.uuid4().hex[:10]}")
    started_at = _now()
    started_monotonic = time.monotonic()
    budget_snapshot = _workflow_batch_budget_guard(
        project_id,
        episode_id,
        payload,
        node,
        variant_count=variant_count,
    )
    preflight_result = preflight_workflow_node(
        project_id,
        episode_id,
        {
            "nodeId": node_id,
            "nodeType": node_type,
            "routeId": _node_route_id(node),
            "strategy": (node.get("data") if isinstance(node.get("data"), dict) else {}).get("strategy")
            or node.get("strategy"),
            "generationConfig": payload.get("generationConfig") or payload.get("generation_config") or {},
            "reason": "run_workflow_batch_preflight",
            "writeBack": False,
        },
        workflow=workflow,
    )
    blocking_issues = [
        str(item).strip()
        for item in preflight_result.get("blockingIssues", [])
        if str(item).strip()
    ] if isinstance(preflight_result, dict) else []
    if blocking_issues:
        raise ValueError("节点预检未通过：" + "；".join(blocking_issues[:5]))

    node = _workflow_node(workflow, node_id)
    if not node:
        raise FileNotFoundError("节点不存在")
    input_snapshot = resolve_workflow_node_inputs(
        project_id,
        episode_id,
        {"nodeId": node_id},
        workflow=workflow,
    )
    edge_blockers = _workflow_batch_edge_blockers(project_id, episode_id, workflow, node, input_snapshot)
    if edge_blockers:
        data = node.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            node["data"] = data
        data["status"] = "blocked"
        quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
        quality["batchPreflight"] = {
            "checkedAt": _now(),
            "blockingIssues": edge_blockers,
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
        raise ValueError("节点运行前检查未通过：" + "；".join(edge_blockers[:5]))
    preflight_snapshot = preflight_result.get("preflight") if isinstance(preflight_result.get("preflight"), dict) else preflight_result
    resolved_config = (
        preflight_snapshot.get("resolvedConfig")
        if isinstance(preflight_snapshot, dict) and isinstance(preflight_snapshot.get("resolvedConfig"), dict)
        else preflight_result.get("resolvedConfig")
        if isinstance(preflight_result.get("resolvedConfig"), dict)
        else {}
    )
    model_info = preflight_result.get("model") if isinstance(preflight_result.get("model"), dict) else {}
    model_id = str(resolved_config.get("modelId") or resolved_config.get("model_id") or model_info.get("id") or "").strip()
    provider_id = str(
        model_info.get("providerId")
        or model_info.get("provider_id")
        or model_info.get("providerPresetId")
        or model_info.get("provider_preset_id")
        or resolved_config.get("providerId")
        or resolved_config.get("provider_id")
        or ""
    ).strip()
    runtime_generation_config = (
        payload.get("generationConfig")
        if isinstance(payload.get("generationConfig"), dict)
        else payload.get("generation_config")
        if isinstance(payload.get("generation_config"), dict)
        else {}
    )
    versions: list[dict[str, Any]] = []
    now = _now()
    for index in range(variant_count):
        metadata = build_storyboard_generation_metadata(
            project_id,
            episode_id,
            node_id,
            version_type,
            task_type,
            user_instruction=str(payload.get("userInstruction") or payload.get("user_instruction") or ""),
        )
        payload_row = metadata.get("payload") if isinstance(metadata.get("payload"), dict) else {}
        payload_row = _merge_version_payload_snapshots(
            payload_row,
            _workflow_version_payload_snapshots(
                project_id,
                episode_id,
                workflow,
                node_id,
                version_type=version_type,
                task_type=task_type,
                prompt_payload=payload_row,
                input_snapshot=input_snapshot,
                preflight_snapshot=preflight_snapshot,
                generation_config_override=runtime_generation_config,
            ),
            prefer_existing=False,
        )
        metadata["payload"] = {
            **payload_row,
            "batchId": batch_id,
            "variantIndex": index + 1,
            "variantCount": variant_count,
            "inputLinksSnapshot": copy.deepcopy(input_snapshot.get("inputLinks") or []),
            "referenceMediaIdsSnapshot": copy.deepcopy(input_snapshot.get("referenceMediaIds") or []),
            "assetRefsSnapshot": copy.deepcopy(input_snapshot.get("assetRefs") or []),
            "preflightSnapshot": copy.deepcopy(preflight_snapshot),
            "budgetSnapshot": copy.deepcopy(budget_snapshot),
            "estimatedCost": budget_snapshot.get("estimatedUnitCost"),
            "estimatedUnitCost": budget_snapshot.get("estimatedUnitCost"),
            "estimatedBatchCost": budget_snapshot.get("estimatedCost"),
            "modelId": model_id,
            "providerId": provider_id,
            "routeId": _node_route_id(node),
            "segmentId": _node_segment_id(node),
            "nodeType": node_type,
            "generatedAt": now,
        }
        metadata["source"] = str(metadata.get("source") or "workflow-batch")
        metadata["summary"] = f"批量候选 {index + 1}/{variant_count}：{metadata.get('summary') or '候选版本已生成。'}"
        versions.append(add_storyboard_version(project_id, episode_id, node_id, version_type, metadata))
    completed_at = _now()
    elapsed_ms = max(0, int((time.monotonic() - started_monotonic) * 1000))
    task = {
        "id": f"workflow-batch-{uuid.uuid4().hex[:10]}",
        "type": "workflow_batch",
        "projectId": project_id,
        "episodeId": episode_id,
        "nodeId": node_id,
        "status": "completed",
        "progress": 100,
        "message": f"已生成 {len(versions)} 个批量候选版本。",
        "batchId": batch_id,
        "nodeType": node_type,
        "routeId": _node_route_id(node),
        "segmentId": _node_segment_id(node),
        "modelId": model_id,
        "providerId": provider_id,
        "estimatedCost": budget_snapshot.get("estimatedCost"),
        "budget": copy.deepcopy(budget_snapshot),
        "inputSnapshot": {
            "inputLinks": copy.deepcopy(input_snapshot.get("inputLinks") or []),
            "referenceMediaIds": copy.deepcopy(input_snapshot.get("referenceMediaIds") or []),
            "assetRefs": copy.deepcopy(input_snapshot.get("assetRefs") or []),
        },
        "preflight": copy.deepcopy(preflight_snapshot),
        "startedAt": started_at,
        "completedAt": completed_at,
        "createdAt": started_at,
        "updatedAt": completed_at,
        "elapsedMs": elapsed_ms,
        "durationMs": elapsed_ms,
    }
    task_save_result = _append_workflow_task(project_id, episode_id, task)
    return_production_status = _workflow_mutation_returns_production_status(payload)
    workflow_version = next(
        (
            version.get("workflowVersion")
            for version in reversed(versions)
            if isinstance(version, dict) and version.get("workflowVersion")
        ),
        workflow.get("version"),
    )
    production_status = None
    if return_production_status:
        try:
            status_result = update_episode_production_status(project_id, episode_id)
            production_status = status_result.get("status") if isinstance(status_result, dict) else None
        except Exception:
            print(traceback.format_exc(), flush=True)
    mutation_fields = _workflow_mutation_event_fields(
        task_save_result,
        [
            "canvas_version",
            "version",
            *(["episode_production_status"] if production_status else []),
        ],
    )
    result = {
        "success": True,
        "episodeId": episode_id,
        "nodeId": node_id,
        "batchId": batch_id,
        "task": task,
        "versions": versions,
        "workflowVersion": task_save_result.get("workflowVersion") or workflow_version,
        **mutation_fields,
    }
    if return_production_status:
        result["productionStatus"] = production_status
    return result


def import_workflow_media(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "导入画布媒体")
    episode_id = _safe_episode_id(episode_id)
    workflow: dict[str, Any] | None = None

    file_info = payload.get("file") if isinstance(payload.get("file"), dict) else None
    if not file_info:
        media_payload = payload.get("media") if isinstance(payload.get("media"), dict) else {}
        source_id = str(payload.get("sourceId") or payload.get("source_id") or "").strip()
        if media_payload:
            file_info = media_payload
        elif source_id:
            file_info = {"path": source_id, "filePath": source_id, "name": Path(source_id).name}
    if not file_info:
        raise ValueError("请选择要导入的媒体")
    frame_origin = None
    if is_frame_image(file_info) or is_frame_image(payload):
        from .video_clips import validated_frame_origin
        frame_origin = validated_frame_origin(file_info)
        payload = {**payload, "mediaPurpose": FRAME_IMAGE, "assetKind": FRAME_IMAGE, "assetType": FRAME_IMAGE}

    scope = str(payload.get("scope") or payload.get("visibilityScope") or "global").strip() or "global"
    if scope not in {"node", "route", "workChain", "global"}:
        scope = "global"
    slot_payload = payload.get("slot") or payload.get("targetSlot") or payload.get("target_slot")
    slot = _canonical_workflow_slot(slot_payload, "storyboard_image")
    action = str(payload.get("action") or payload.get("linkAction") or "append").strip() or "append"
    if action not in {"append", "replace_slot", "relink_slot"}:
        action = "append"
    target_node_id = str(payload.get("targetNodeId") or payload.get("target_node_id") or payload.get("nodeId") or payload.get("node_id") or "").strip()
    if target_node_id and not (payload.get("scope") or payload.get("visibilityScope")):
        scope = "node"
    route_id = str(payload.get("routeId") or payload.get("route_id") or "").strip()
    work_chain_id = str(payload.get("workChainId") or payload.get("work_chain_id") or "").strip()
    segment_id = str(payload.get("segmentId") or payload.get("segment_id") or "").strip()
    note = str(payload.get("note") or "").strip()
    voice_style = str(payload.get("voiceStyle") or payload.get("voice_style") or "").strip()
    title = str(
        payload.get("title")
        or payload.get("name")
        or payload.get("assetName")
        or payload.get("asset_name")
        or ""
    ).strip()
    media_purpose = str(payload.get("mediaPurpose") or payload.get("media_purpose") or "auto").strip() or "auto"
    if media_purpose == "visual_reference":
        media_purpose = "storyboard_image"
    if media_purpose not in {
        "custom_image",
        FRAME_IMAGE,
        "video",
        "auto",
        "asset_reference",
        "character_reference",
        "creature_reference",
        "scene_reference",
        "prop_reference",
        "storyboard_image",
        "visual_handoff",
    }:
        media_purpose = "auto"
    if media_purpose in {"custom_image", "character_reference", "creature_reference", "scene_reference", "prop_reference", "storyboard_image", "visual_handoff", "video"} and not title:
        raise ValueError(f"{_workflow_media_purpose_label(media_purpose)}名称不能为空")
    title_asset_type = _workflow_project_asset_type_from_media_purpose(media_purpose)
    if title_asset_type:
        project_assets = list_assets(
            "project",
            project_id,
            hydrate=False,
            asset_type=title_asset_type,
            lifecycle_status=ASSET_LIFECYCLE_ACTIVE,
        )
        if _workflow_project_asset_name_exists(project_assets, title_asset_type, title):
            raise FileExistsError(f"{_asset_type_label(title_asset_type)}名称已存在")
    media_kind = _workflow_import_media_kind(file_info, payload, media_purpose)
    if media_purpose == "custom_image" and media_kind != "image":
        raise ValueError("自定义图片必须上传图片文件")
    if media_purpose == "video" and media_kind != "video":
        raise ValueError("视频分类必须上传视频文件")
    if frame_origin and media_kind != "image":
        raise ValueError("帧画面必须是视频截图图片")
    if media_purpose == "visual_handoff" and media_kind == "video":
        raise ValueError("视觉交接必须上传图片文件")
    preferred_target_slot = _workflow_media_purpose_target_slot(
        payload.get("preferredTargetSlot")
        or payload.get("preferred_target_slot")
        or media_purpose
    ) or _workflow_media_purpose_material_slot(
        payload.get("preferredTargetSlot")
        or payload.get("preferred_target_slot")
        or media_purpose
    )
    if not slot_payload and preferred_target_slot:
        slot = preferred_target_slot
    payload_asset_type = _workflow_canvas_project_asset_type_from_value(
        payload.get("assetType")
        or payload.get("asset_type")
        or payload.get("assetKind")
        or payload.get("asset_kind")
    )
    inferred_asset_type = payload_asset_type or _workflow_asset_type_from_media_purpose(media_purpose)
    asset_scope = str(payload.get("assetScope") or payload.get("asset_scope") or _workflow_media_asset_scope(media_purpose)).strip()
    if asset_scope not in {"reusable", "result"}:
        asset_scope = _workflow_media_asset_scope(media_purpose)
    canvas_node_role = _CANVAS_NODE_ROLE_IMAGE_ASSET
    locked = bool(payload.get("locked") or payload.get("lockedByUser") or payload.get("locked_by_user"))

    target_node = None
    if target_node_id:
        workflow = read_workflow_card_neighborhood_v4(project_id, episode_id, target_node_id, detail="full")
        target_node = _workflow_node(workflow, target_node_id)
    if scope == "node":
        if not target_node:
            raise FileNotFoundError("目标节点不存在")
        if not _workflow_accepts_material_input(target_node):
            raise ValueError("导入图片可链接到分镜脚本、分镜单元或视频生成；导入视频仅可链接到视频生成")
        route_id = route_id or _node_route_id(target_node)
        work_chain_id = work_chain_id or _node_work_chain_id(target_node)
        segment_id = segment_id or _node_segment_id(target_node)
    elif scope == "route" and not route_id:
        raise ValueError("请指定要链接的 route")
    elif scope == "workChain" and not (work_chain_id or route_id):
        raise ValueError("请指定要链接的 route 或工作链")
    if not work_chain_id and route_id:
        route = _read_canvas_route_v4(project_id, episode_id, route_id)
        work_chain_id = str(route.get("workChainId") or route.get("work_chain_id") or "").strip() if isinstance(route, dict) else ""

    # Validate the target slot before copying any media.  Slot validation is
    # purely structural, so doing it up front prevents a failed link from
    # leaving an unreferenced media file behind.
    if target_node_id:
        if scope != "node" or not target_node or workflow is None:
            raise ValueError("导入媒体链接目标时必须使用明确 node scope")
        _workflow_validate_material_slot(
            target_node,
            slot,
            source_node={
                "type": "media.external",
                "data": {
                    "mediaKind": media_kind,
                    "mediaType": media_kind,
                    "mediaPurpose": media_purpose,
                    "preferredTargetSlot": preferred_target_slot,
                },
            },
        )

    now = _now()
    media_id = str(payload.get("mediaId") or payload.get("media_id") or f"workflow-media-{uuid.uuid4().hex[:10]}")
    media_subdir = (
        "videos"
        if media_kind == "video"
        else "visual_handoffs"
        if media_purpose == "visual_handoff"
        else ("storyboard_images" if asset_scope == "result" else "canvas_media")
    )
    storage_scope = "episode_results"
    workflow_media_before = copy.deepcopy(_read_workflow_media(project_id, episode_id))
    media_storage_dir = _project_media_storage_dir(
        project_id,
        media_subdir,
        storage_scope=storage_scope,
        episode_id=episode_id,
    )
    media_file_stem = _safe_file_stem(media_id, media_id)
    media_paths_before = set(media_storage_dir.glob(f"{media_file_stem}.*")) if media_storage_dir.exists() else set()
    created_media_paths: set[Path] = set()
    created_frame_origin_path = ""
    if media_purpose == "video":
        from .video_clips import _media_tool_executable

        source = _local_video_source_from_media(file_info)
        if source is None:
            raise ValueError("请选择本地视频文件")
        source_path, _ = source
        with prepare_import_video(
            source_path,
            ffmpeg=_media_tool_executable("ffmpeg"),
            ffprobe=_media_tool_executable("ffprobe"),
        ) as (prepared_path, video_info):
            media = _copy_local_project_video_media_file(
                project_id, prepared_path, media_id=media_id,
                subdir=media_subdir,
                original_name=str(file_info.get("name") or source_path.name),
                source_mime="video/mp4", storage_scope=storage_scope,
                episode_id=episode_id,
            )
            media.update(video_info)
    elif media_kind == "video":
        media = _video_media_from_file_info(
            project_id,
            file_info,
            media_id=media_id,
            subdir=media_subdir,
            storage_scope=storage_scope,
            episode_id=episode_id,
        )
    else:
        media = _image_media_from_file_info(
            project_id,
            file_info,
            media_id=media_id,
            subdir=media_subdir,
            storage_scope=storage_scope,
            episode_id=episode_id,
        )
    if media_kind == "video":
        media = video_media_metadata(project_id, media)
    media_path = _stored_media_path(project_id, media)
    if media_path and media_path.is_file() and media_path not in media_paths_before:
        created_media_paths.add(media_path.resolve())
    dimensions = _image_dimensions_from_file(media_path) if media_kind == "image" else {}
    media = {**media, **dimensions} if dimensions else media
    if frame_origin:
        # Each canvas frame asset has its own binding identity, even when the
        # same capture is dropped/pasted twice and the stored pixels are shared.
        frame_media_id = f"frame-asset-{uuid.uuid4().hex[:12]}"
        target_frame_origin = {
            **copy.deepcopy(frame_origin),
            "projectId": project_id,
            "episodeId": episode_id,
            "resultId": frame_media_id,
            "copiedFrom": copy.deepcopy(frame_origin),
        }
        media.update({"id": frame_media_id, "assetType": FRAME_IMAGE, "frameOrigin": target_frame_origin})
        from .video_clips import _frame_origin_path

        origin_path = _frame_origin_path(target_frame_origin)
        try:
            origin_path.parent.mkdir(parents=True, exist_ok=True)
            origin_path.write_text(
                json.dumps(target_frame_origin, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            for created_path in created_media_paths:
                _cleanup_promoted_media_copy(project_id, created_path)
            raise
        created_frame_origin_path = str(origin_path)
    media_record = {
        "id": media.get("id") or media_id,
        "type": "media.external",
        "kind": media_kind,
        "mediaType": media_kind,
        "mediaPurpose": media_purpose,
        "preferredTargetSlot": preferred_target_slot,
        "assetScope": asset_scope,
        "assetKind": inferred_asset_type or ("video" if media_kind == "video" else ""),
        **({"assetType": inferred_asset_type} if inferred_asset_type else {}),
        "slot": slot,
        "visibilityScope": scope,
        "canvasNodeRole": canvas_node_role,
        "workChainId": work_chain_id,
        "routeId": route_id,
        "segmentId": segment_id,
        "targetNodeId": target_node_id,
        "sourceFileName": str(file_info.get("name") or file_info.get("originalName") or Path(str(file_info.get("path") or "")).name or ""),
        "title": title,
        **({"assetName": title} if title else {}),
        "size": media.get("size") or file_info.get("size"),
        **dimensions,
        "media": copy.deepcopy(media),
        "storage": copy.deepcopy(media),
        "provenance": {
            "source": "user",
            "action": "external_media_imported",
            "createdAt": now,
            "originalName": str(file_info.get("name") or file_info.get("originalName") or ""),
            **({"title": title} if title else {}),
            **({"note": note} if note else {}),
            **({"voiceStyle": voice_style} if voice_style else {}),
        },
        "createdAt": now,
        "updatedAt": now,
    }
    media_node_id = str(
        payload.get("mediaNodeId")
        or payload.get("media_node_id")
        or payload.get("canvasNodeId")
        or payload.get("canvas_node_id")
        or f"media_external_{uuid.uuid4().hex[:8]}"
    )
    media_record["nodeId"] = media_node_id
    position = payload.get("position") if isinstance(payload.get("position"), dict) else {"x": 640, "y": 240}
    node_visibility_scope = scope if scope in {"route", "workChain", "global"} else ("workChain" if work_chain_id else "global")
    media_title = title or media_record["sourceFileName"] or ("导入视频" if media_kind == "video" else "导入图片")
    media_summary = note if title else note or (
        "外部导入视觉交接图，可作为上一工作链空间连续性参考接入分镜脚本。"
        if media_purpose == "visual_handoff"
        else "外部导入视频，可作为画布视频素材使用。"
        if media_kind == "video"
        else "外部导入图片，可作为资产参考接入分镜脚本、分镜单元或视频生成。"
    )
    media_node = {
        "id": media_node_id,
        "type": "media.external",
        "position": copy.deepcopy(position),
        "workChainId": work_chain_id,
        "routeId": route_id,
        "segmentId": segment_id,
        "data": {
            "title": media_title,
            "status": "ready",
            "summary": media_summary,
            "workChainId": work_chain_id,
            "routeId": route_id,
            "segmentId": segment_id,
            "visibilityScope": node_visibility_scope,
            "sourceType": "external_media",
            "canvasNodeRole": canvas_node_role,
            "mediaPurpose": media_purpose,
            "preferredTargetSlot": preferred_target_slot,
            "assetScope": asset_scope,
            "assetKind": inferred_asset_type or ("video" if media_kind == "video" else ""),
            **({"assetType": inferred_asset_type} if inferred_asset_type else {}),
            **({"assetName": title} if title else {}),
            **({"voiceStyle": voice_style} if voice_style else {}),
            "mediaId": str(media_record["id"]),
            "media": copy.deepcopy(media),
            "storage": copy.deepcopy(media),
            "sourceFileName": media_record["sourceFileName"],
            **dimensions,
            "cardState": {"size": {"width": 240, "height": 260, "minWidth": 220, "minHeight": 220}},
            "provenance": copy.deepcopy(media_record["provenance"]),
        },
    }
    if workflow is not None:
        node_rows = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
        if not isinstance(workflow.get("nodes"), list):
            workflow["nodes"] = node_rows
        match_index = next(
            (index for index, node in enumerate(node_rows) if isinstance(node, dict) and str(node.get("id") or "") == media_node_id),
            -1,
        )
        if match_index >= 0:
            node_rows[match_index] = media_node
        else:
            node_rows.append(media_node)

    input_link: dict[str, Any] | None = None
    affected_node_ids: set[str] = set()
    removed_edge_ids: set[str] = set()
    if target_node_id:
        input_link = {
            "id": f"input-media-{uuid.uuid4().hex[:10]}",
            "label": media_title or media_record["sourceFileName"] or str(media_record["id"]),
            "sourceType": "external_media",
            "sourceId": str(media_record["id"]),
            "sourceNodeId": media_node_id,
            "sourceNodeType": "media.external",
            "targetNodeId": target_node_id,
            "targetNodeType": str(target_node.get("type") or ""),
            "mediaId": str(media_record["id"]),
            "mediaKind": "external",
            "mediaType": media_kind,
            "mediaPurpose": media_purpose,
            "preferredTargetSlot": preferred_target_slot,
            "assetScope": asset_scope,
            "assetKind": inferred_asset_type or ("video" if media_kind == "video" else ""),
            **({"assetType": inferred_asset_type} if inferred_asset_type else {}),
            "path": media.get("relativePath") or media.get("relative_path") or media.get("file") or media.get("path"),
            "linkAction": action,
            "targetSlot": slot,
            "slot": slot,
            "visibilityScope": scope,
            "status": "relinked" if action == "relink_slot" else "linked",
            "locked": locked,
            "lockedByUser": locked,
            "preserveOnReplan": locked,
            "versionMode": "specific" if payload.get("versionId") or payload.get("version_id") else "recommended",
            "provenance": {
                "source": "user",
                "action": action,
                "createdAt": now,
                **({"note": note} if note else {}),
            },
            **({"workChainId": work_chain_id} if work_chain_id else {}),
            **({"routeId": route_id} if route_id else {}),
            **({"segmentId": segment_id} if segment_id else {}),
            **({"mediaVersionId": str(payload.get("versionId") or payload.get("version_id"))} if payload.get("versionId") or payload.get("version_id") else {}),
        }
        before_edge_ids = {
            str(edge.get("id") or "").strip()
            for edge in workflow.get("edges", [])
            if isinstance(edge, dict) and str(edge.get("id") or "").strip()
        }
        _upsert_workflow_material_edge(
            workflow,
            source_node=media_node,
            target_node=target_node,
            input_link=input_link,
            slot=slot,
            action=action,
            route_id=route_id,
            segment_id=segment_id,
            work_chain_id=work_chain_id,
        )
        after_edge_ids = {
            str(edge.get("id") or "").strip()
            for edge in workflow.get("edges", [])
            if isinstance(edge, dict) and str(edge.get("id") or "").strip()
        }
        removed_edge_ids.update(before_edge_ids - after_edge_ids)
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
        data["referenceMediaIds"] = _append_unique_string(data.get("referenceMediaIds"), str(media_record["id"]))
        affected_node_ids = _workflow_downstream_node_ids(workflow, target_node_id)
        affected_node_ids.add(target_node_id)

    explicit_affected_ids = {
        str(item).strip()
        for item in (
            payload.get("affectedNodeIds")
            or payload.get("affected_node_ids")
            or []
        )
        if str(item).strip()
    }
    affected_node_ids.update(explicit_affected_ids)
    if input_link:
        input_link["affectedNodeIds"] = sorted(affected_node_ids)
        media_record["links"] = [input_link["id"]]
        media_record["inputLink"] = copy.deepcopy(input_link)
    else:
        media_record["links"] = []

    workflow_media = copy.deepcopy(workflow_media_before)
    workflow_media["items"] = [
        item
        for item in workflow_media.get("items") or []
        if not isinstance(item, dict) or str(item.get("id") or "") != str(media_record["id"])
    ] + [media_record]
    return_production_status = _workflow_mutation_returns_production_status(payload)
    try:
        _write_workflow_media(project_id, episode_id, workflow_media)
        if workflow is None:
            _ensure_saved_workflow_node_contract(media_node)
            save_result = write_canvas_records_v4(
                project_id,
                episode_id,
                nodes=[copy.deepcopy(media_node)],
                op_type="structure_patch",
                changed_resources=["canvas_node"],
                expected_revision=payload.get("expectedRevision") or payload.get("expected_revision"),
            )
            _touch_project_meta(project_id)
        else:
            material_edge = (
                _workflow_material_edge_for_input_link(workflow, str(input_link.get("id") or ""))
                if isinstance(input_link, dict)
                else None
            )
            nodes_to_write = [copy.deepcopy(media_node)]
            if isinstance(target_node, dict):
                _ensure_saved_workflow_node_contract(target_node)
                nodes_to_write.append(copy.deepcopy(target_node))
            edges_to_write: list[dict[str, Any]] = []
            if isinstance(material_edge, dict):
                _ensure_saved_workflow_edge_contract(
                    material_edge,
                    {
                        str(media_node.get("id") or ""): media_node,
                        str((target_node or {}).get("id") or ""): target_node or {},
                    },
                    workflow,
                )
                edges_to_write.append(copy.deepcopy(material_edge))
            _ensure_saved_workflow_node_contract(media_node)
            save_result = write_canvas_records_v4(
                project_id,
                episode_id,
                nodes=nodes_to_write,
                edges=edges_to_write,
                delete_edge_ids=sorted(removed_edge_ids),
                op_type="structure_patch",
                changed_resources=["canvas_node", "canvas_edge"],
                expected_revision=payload.get("expectedRevision") or payload.get("expected_revision"),
            )
            _touch_project_meta(project_id)
    except Exception:
        try:
            _write_workflow_media(project_id, episode_id, workflow_media_before)
        except Exception:
            print(traceback.format_exc(), flush=True)
        for created_path in created_media_paths:
            _cleanup_promoted_media_copy(project_id, created_path)
        _cleanup_promoted_media_copy(project_id, created_frame_origin_path)
        raise
    production_status = None
    if return_production_status:
        try:
            status_result = update_episode_production_status(project_id, episode_id)
            production_status = status_result.get("status") if isinstance(status_result, dict) else None
        except Exception:
            print(traceback.format_exc(), flush=True)

    patched_nodes = [copy.deepcopy(media_node)]
    patched_node_ids = {media_node_id}
    if workflow is not None:
        for node in workflow.get("nodes", []):
            if not isinstance(node, dict):
                continue
            current_node_id = str(node.get("id") or "").strip()
            if current_node_id and current_node_id in affected_node_ids and current_node_id not in patched_node_ids:
                patched_nodes.append(copy.deepcopy(node))
                patched_node_ids.add(current_node_id)
    material_edge = (
        _workflow_material_edge_for_input_link(workflow, str(input_link.get("id") or ""))
        if isinstance(input_link, dict) and workflow is not None
        else None
    )
    mutation_fields = _workflow_mutation_event_fields(
        save_result,
        [
            "canvas_node",
            "canvas_edge",
            *(["episode_production_status"] if production_status else []),
        ],
    )
    result = {
        "success": True,
        "episodeId": episode_id,
        "media": media,
        "mediaRecord": media_record,
        "mediaNode": media_node,
        "node": copy.deepcopy(media_node),
        "nodes": patched_nodes,
        "inputLink": input_link,
        "edge": copy.deepcopy(material_edge) if material_edge else None,
        "removedEdgeIds": sorted(removed_edge_ids),
        "workflowMedia": _read_workflow_media(project_id, episode_id),
        "workflowVersion": save_result.get("workflowVersion"),
        "productionStatus": production_status,
        **mutation_fields,
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": media_node_id},
    }
    if not production_status:
        result.pop("productionStatus", None)
    return result


def _image_dimensions_from_file(path: Path | None) -> dict[str, Any]:
    if not path or not path.is_file():
        return {}
    try:
        raw = path.read_bytes()
    except Exception:
        return {}
    width = 0
    height = 0
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        width = int.from_bytes(raw[16:20], "big")
        height = int.from_bytes(raw[20:24], "big")
    elif raw.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(raw):
            if raw[index] != 0xFF:
                index += 1
                continue
            marker = raw[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(raw):
                break
            length = int.from_bytes(raw[index:index + 2], "big")
            if length < 2 or index + length > len(raw):
                break
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                height = int.from_bytes(raw[index + 3:index + 5], "big")
                width = int.from_bytes(raw[index + 5:index + 7], "big")
                break
            index += length
    if width > 0 and height > 0:
        return {"width": width, "height": height, "aspectRatio": f"{width}:{height}"}
    return {}


def _workflow_import_media_kind(file_info: dict[str, Any], payload: dict[str, Any], media_purpose: str) -> str:
    explicit_kind = str(payload.get("mediaKind") or payload.get("media_kind") or file_info.get("kind") or "").strip().lower()
    mime_type = str(file_info.get("mimeType") or file_info.get("mime_type") or "").strip().lower()
    name = str(file_info.get("name") or file_info.get("originalName") or file_info.get("path") or file_info.get("filePath") or "").strip()
    suffix = Path(name).suffix.lower()
    if explicit_kind == "video" or mime_type.startswith("video/") or suffix in VIDEO_EXTENSIONS:
        return "video"
    return "image"


def _workflow_media_asset_scope(media_purpose: str) -> str:
    if media_purpose in {"storyboard_image", "visual_handoff", FRAME_IMAGE, "video"}:
        return "result"
    return "reusable"


def _workflow_batch_generation_kind(node_type: str) -> tuple[str, str]:
    if node_type == "prompt.storyboard":
        return "prompt", "storyboard_plan"
    if node_type == "video.result":
        raise ValueError("视频片段节点不能直接运行，请运行上游视频生成")
    if _workflow_is_video_task_type(node_type):
        return "video", "storyboard_video"
    if node_type == "storyboard.image":
        return "image", "storyboard_image"
    return "prompt", "workflow"


def _workflow_batch_budget_number(
    payload: dict[str, Any],
    node: dict[str, Any],
    *keys: str,
) -> float | None:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    budget = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
    cost_estimate = data.get("costEstimate") if isinstance(data.get("costEstimate"), dict) else {}
    generation_config = data.get("generationConfig") if isinstance(data.get("generationConfig"), dict) else {}
    sources = (payload, budget, cost_estimate, generation_config)
    for source in sources:
        for key in keys:
            if key not in source:
                continue
            value = source.get(key)
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _workflow_batch_payload_confirmed(payload: dict[str, Any]) -> bool:
    budget = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
    for source in (payload, budget):
        for key in ("confirmedHighCost", "confirmed_high_cost", "highCostConfirmed", "high_cost_confirmed"):
            value = source.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value != 0
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _workflow_task_estimated_cost(task: dict[str, Any]) -> float:
    for key in ("estimatedCost", "estimated_cost", "cost", "consumedCost", "consumed_cost"):
        try:
            return max(0.0, float(task.get(key)))
        except (TypeError, ValueError):
            continue
    budget = task.get("budget") if isinstance(task.get("budget"), dict) else {}
    for key in ("estimatedCost", "estimated_cost", "nodeEstimatedCost", "node_estimated_cost"):
        try:
            return max(0.0, float(budget.get(key)))
        except (TypeError, ValueError):
            continue
    return 0.0


def _workflow_batch_budget_guard(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
    node: dict[str, Any],
    *,
    variant_count: int,
) -> dict[str, Any]:
    unit_cost = _workflow_batch_budget_number(
        payload,
        node,
        "estimatedUnitCost",
        "estimated_unit_cost",
        "unitCost",
        "unit_cost",
    )
    unit_cost = max(0.0, unit_cost if unit_cost is not None else 1.0)
    raw_max_variants = _workflow_batch_budget_number(
        payload,
        node,
        "maxNodeVariants",
        "max_node_variants",
        "maxVariantCount",
        "max_variant_count",
    )
    max_node_variants = int(raw_max_variants) if raw_max_variants is not None else 6
    max_node_variants = max(1, max_node_variants)
    if variant_count > max_node_variants:
        raise ValueError(f"批量候选数 {variant_count} 超过单节点最大变体数 {max_node_variants}")

    estimated_cost = round(variant_count * unit_cost, 4)
    raw_max_node_cost = _workflow_batch_budget_number(
        payload,
        node,
        "maxNodeCost",
        "max_node_cost",
    )
    max_node_cost = raw_max_node_cost if raw_max_node_cost is not None else unit_cost * max_node_variants
    if max_node_cost > 0 and estimated_cost > max_node_cost:
        raise ValueError(f"当前节点预计成本 {estimated_cost:g} 超过单节点预算 {max_node_cost:g}")

    raw_max_route_cost = _workflow_batch_budget_number(payload, node, "maxRouteCost", "max_route_cost")
    raw_max_episode_cost = _workflow_batch_budget_number(payload, node, "maxEpisodeCost", "max_episode_cost")
    max_route_cost = raw_max_route_cost if raw_max_route_cost is not None else 60.0
    max_episode_cost = raw_max_episode_cost if raw_max_episode_cost is not None else 120.0
    raw_high_cost_threshold = _workflow_batch_budget_number(
        payload,
        node,
        "highCostThreshold",
        "high_cost_threshold",
    )
    high_cost_threshold = raw_high_cost_threshold if raw_high_cost_threshold is not None else unit_cost * max_node_variants

    route_id = _node_route_id(node)
    tasks = _read_workflow_tasks(project_id, episode_id)
    counted_statuses = {"queued", "running", "completed", "succeeded"}
    route_used = 0.0
    episode_used = 0.0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "").strip()
        if status and status not in counted_statuses:
            continue
        task_cost = _workflow_task_estimated_cost(task)
        episode_used += task_cost
        if route_id and str(task.get("routeId") or "") == route_id:
            route_used += task_cost
    route_after = round(route_used + estimated_cost, 4)
    episode_after = round(episode_used + estimated_cost, 4)
    if route_id and max_route_cost > 0 and route_after > max_route_cost:
        raise ValueError(f"当前路线预计累计成本 {route_after:g} 超过路线预算 {max_route_cost:g}")
    if max_episode_cost > 0 and episode_after > max_episode_cost:
        raise ValueError(f"当前集预计累计成本 {episode_after:g} 超过本集预算 {max_episode_cost:g}")
    if high_cost_threshold > 0 and estimated_cost > high_cost_threshold and not _workflow_batch_payload_confirmed(payload):
        raise ValueError(f"当前批量任务预计成本 {estimated_cost:g}，请确认高成本任务后再运行")

    return {
        "variantCount": variant_count,
        "estimatedUnitCost": unit_cost,
        "estimatedCost": estimated_cost,
        "maxNodeVariants": max_node_variants,
        "maxNodeCost": max_node_cost,
        "maxRouteCost": max_route_cost,
        "maxEpisodeCost": max_episode_cost,
        "highCostThreshold": high_cost_threshold,
        "confirmedHighCost": _workflow_batch_payload_confirmed(payload),
        "routeCostBefore": round(route_used, 4),
        "routeCostAfter": route_after,
        "episodeCostBefore": round(episode_used, 4),
        "episodeCostAfter": episode_after,
    }


def _workflow_batch_edge_blockers(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
    input_snapshot: dict[str, Any],
) -> list[str]:
    node_id = str(node.get("id") or "").strip()
    if not node_id:
        return ["缺少目标节点 id"]
    blockers: list[str] = []
    if _workflow_is_video_task_type(str(node.get("type") or "")):
        video_task_scope = workflow_video_task_scope(workflow, node)
        if video_task_scope not in {_WORKFLOW_VIDEO_TASK_SCOPE_STANDALONE, _WORKFLOW_VIDEO_TASK_SCOPE_WORK_CHAIN}:
            blockers.append("视频生成缺少作用域标识，请重新创建任务卡")
        from .video_task_card_references import video_task_card_current_reference_snapshot
        try:
            video_task_card_current_reference_snapshot(
                project_id, episode_id, workflow, node_id, input_snapshot, for_generation=True,
            )
        except ValueError as exc:
            blockers.append(str(exc))
        return blockers
    # The material edge may end at an upstream card. Inspect the resolved
    # inputs so director board → storyboard card → image inheritance is respected.
    for link in input_snapshot.get("inputLinks") or []:
        if not isinstance(link, dict):
            continue
        source_id = str(link.get("sourceNodeId") or "").strip()
        if not source_id:
            continue
        source_node = _workflow_node(workflow, source_id)
        source_data = source_node.get("data") if isinstance(source_node, dict) and isinstance(source_node.get("data"), dict) else {}
        source_status = str(source_data.get("status") or "").strip()
        target_slot = _canonical_workflow_slot(link.get("targetSlot") or link.get("slot") or link.get("role"), "")
        source_requires_current_media = target_slot == "storyboard_image"
        source_has_current_media = bool(
            source_requires_current_media
            and _workflow_node_can_supply_image_reference(source_node)
            and workflow_current_media_version_has_media(project_id, episode_id, workflow, source_id)
        )
        if source_status in {
            "queued", "running", "processing", "waiting", "waiting_upstream", "pending_generation",
        } and not source_has_current_media:
            blockers.append(f"素材来源节点 {source_id} 当前状态为 {source_status}，尚不能作为输入")
        if source_requires_current_media and not source_has_current_media:
            blockers.append(f"素材来源节点 {source_id} 当前版本没有可用媒体，不能作为视频输入")
    return blockers


def upload_storyboard_image(
    project_id: str,
    episode_id: str,
    node_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "上传分镜替代图")
    workflow = get_canvas_workflow_projection(project_id, episode_id)
    node = _workflow_node(workflow, node_id)
    if not node:
        raise FileNotFoundError("节点不存在")
    node_type = str(node.get("type") or "")
    if not (node_type == "storyboard.image"):
        raise ValueError("只有分镜图节点可以上传替代图")
    file_info = payload.get("file") if isinstance(payload.get("file"), dict) else None
    if not file_info:
        media_payload = payload.get("media") if isinstance(payload.get("media"), dict) else {}
        file_info = media_payload or None
    if not file_info:
        raise ValueError("请选择要上传的替代图片")
    media_id = str(payload.get("mediaId") or payload.get("media_id") or f"storyboard-upload-{uuid.uuid4().hex[:10]}")
    media = _image_media_from_file_info(
        project_id,
        file_info,
        media_id=media_id,
        subdir="storyboard_images",
        storage_scope="episode_results",
        episode_id=episode_id,
    )
    dimensions = _image_dimensions_from_file(_stored_media_path(project_id, media))
    if dimensions:
        media = {**media, **dimensions}
    node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
    uploaded_name = str(file_info.get("name") or file_info.get("originalName") or media.get("originalName") or "替代图")
    metadata = {
        "title": str(payload.get("title") or node_data.get("title") or "上传替代图"),
        "summary": f"已上传替代图：{uploaded_name}",
        "source": "user-upload",
        "media": media,
        "payload": {
            "generationStage": "storyboard_image_upload",
            "storyboardPromptSpec": {"layoutKind": "custom"},
            "uploadedFile": {
                "name": uploaded_name,
                "mimeType": file_info.get("mimeType") or file_info.get("mime_type") or media.get("mimeType"),
                "size": file_info.get("size"),
            },
            "mediaId": media.get("id") or media_id,
            "nodeType": node_type,
            "uploadedAt": _now(),
        },
    }
    version = add_storyboard_version(project_id, episode_id, node_id, "image", metadata)
    return_production_status = _workflow_mutation_returns_production_status(payload)
    workflow_version = version.get("workflowVersion") or workflow.get("version")
    production_status = None
    if return_production_status:
        try:
            status_result = update_episode_production_status(project_id, episode_id)
            production_status = status_result.get("status") if isinstance(status_result, dict) else None
        except Exception:
            print(traceback.format_exc(), flush=True)
    result = {
        "success": True,
        "episodeId": episode_id,
        "nodeId": node_id,
        "version": version,
        "workflowVersion": workflow_version,
        "txId": version.get("txId") if isinstance(version, dict) else None,
        "seq": version.get("seq") if isinstance(version, dict) else None,
        "revision": version.get("revision") if isinstance(version, dict) else None,
        "opType": version.get("opType") if isinstance(version, dict) else None,
        "records": version.get("records") if isinstance(version, dict) else None,
        "changedResources": ["canvas_version", "canvas_node"] + (["episode_production_status"] if production_status else []),
    }
    if return_production_status:
        result["productionStatus"] = production_status
    return result
