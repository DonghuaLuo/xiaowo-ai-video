# -*- coding: utf-8 -*-
"""视频请求预检、关联输入、参数快照与初始版本准备。"""
from __future__ import annotations
from utils.video_task_types import CHARACTER_REPLACE_TASK, standalone_video_input_mode, standalone_video_strategy, standalone_video_required_slots

from .agent_sessions import _persistent_media_data_removed
from .canvas_store_queries import read_workflow_card_neighborhood_v4
from .generation_config import _video_task_card_allowed_duration_values, _video_task_card_target_model_context
from .model_provider_config import _project_model_config
from .perf_logging import canvas_perf_elapsed_ms
from .perf_logging import canvas_perf_log
from .perf_logging import canvas_perf_start
from .production_status import _video_task_card_preparation_issues
from .production_status import _video_task_has_ready_manual_image_reference
from .storyboard_prompt_content import _workflow_video_task_card_duration_seconds
from .task_contract import _storyboard_video_task_node_type
from .task_workflow_context import _canvas_task_context_workflow
from .task_workflow_context import _generation_meaningful_title
from .task_workflow_context import _resolve_storyboard_video_task_and_result_nodes
from .task_workflow_context import _workflow_node_title
from .task_workflow_context import _workflow_task_work_chain_fields
from .video_task_card_context import _video_task_card_storyboard_interpretation_contract
from .video_task_card_references import video_task_card_current_reference_snapshot
from .video_task_provider import _storyboard_video_version_payload_for_storage
from .workflow_asset_resolution import resolve_workflow_node_inputs
from .workflow_contract import _workflow_node
from .workflow_contract import workflow_video_task_scope
from .workflow_storyboard_prompts import _generated_version_preview
from .workflow_generation_config import _runtime_generation_config_for_execution
from .workflow_input_resolution import _workflow_node_data
from .workflow_input_resolution import workflow_current_media_version_has_media
from .workflow_input_resolution import workflow_storyboard_reference_node_ids
from .workflow_storyboard_edits import _update_storyboard_version_metadata
from .workflow_storyboard_versions import add_storyboard_version
from .workflow_generation_context import validate_workflow_node_inputs_ready
from typing import Any
import copy
import math


def _work_chain_video_duration_for_submission(
    project_id: str,
    node_data: dict[str, Any],
    runtime_config: dict[str, Any],
    request: dict[str, Any] | None,
) -> int | float:
    """Resolve the video card's displayed default only when the video is submitted."""
    stored = _workflow_video_task_card_duration_seconds(node_data)
    if stored:
        return stored
    request = request if isinstance(request, dict) else {}
    configured = next(
        (value for value in (request.get("durationSeconds"), runtime_config.get("durationSeconds")) if value is not None),
        None,
    )
    if configured is not None:
        try:
            duration = float(configured)
        except (TypeError, ValueError) as exc:
            raise ValueError("视频生成时长无效，请重新选择时长") from exc
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("视频生成时长无效，请重新选择时长")
        return int(duration) if duration.is_integer() else duration
    model = _video_task_card_target_model_context(
        project_id, node_data, {"resolvedConfig": runtime_config},
    )
    allowed = _video_task_card_allowed_duration_values(
        model.get("allowedDurations") or model.get("durations")
    )
    return next((value for value in allowed if abs(float(value) - 15) <= 0.005), max(allowed)) if allowed else 15


def _update_storyboard_video_processing_version(
    project_id: str,
    episode_id: str,
    job: dict[str, Any],
    summary: str,
) -> None:
    version_id = str(job.get("versionId") or "")
    if not version_id:
        return
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    _update_storyboard_version_metadata(
        project_id,
        episode_id,
        version_id,
        {
            "summary": summary,
            "source": "model-video-job",
            "payload": {
                **payload,
                "providerJobId": job.get("providerJobId") or "",
                "resumable": bool(job.get("resumable", True)),
                "providerRequest": job.get("providerRequest") or {},
            },
            "model": job.get("modelId") or job.get("modelName"),
            "provider": job.get("providerId"),
            "generationDebug": _persistent_media_data_removed(
                {**(job.get("debug") or {}), "providerRequest": job.get("providerRequest") or {}}
            ),
            "status": "processing",
        },
    )


def _video_task_card_prompt_from_node_data(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    video_task_card = data.get("videoTaskCard") if isinstance(data.get("videoTaskCard"), dict) else {}
    for source_name, value in (
        ("videoTaskCard.finalVideoPrompt", video_task_card.get("finalVideoPrompt")),
    ):
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise RuntimeError(
                f"当前视频生成 {source_name} 类型异常，必须是字符串；"
                "已阻断生成，不能把结构化对象兜底拼接成视频提示词。"
            )
        text = value.strip()
        if text:
            return text
    return ""


def _apply_video_task_card_payload_overrides(
    payload: dict[str, Any],
    node_data: dict[str, Any],
) -> None:
    prompt = _video_task_card_prompt_from_node_data(node_data)
    if prompt:
        payload["videoPrompt"] = prompt
        payload["videoPromptRaw"] = prompt
        prompt_payload = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else {}
        payload["prompt"] = {**prompt_payload, "videoPrompt": prompt}
        payload["videoPromptSource"] = "final_provider_prompt"
    video_task_card = node_data.get("videoTaskCard")
    if isinstance(video_task_card, dict):
        payload["videoTaskCard"] = copy.deepcopy(video_task_card)
    task_card = payload.get("videoTaskCard") if isinstance(payload.get("videoTaskCard"), dict) else {}
    if prompt:
        task_card.update(
            {
                "promptKind": "final_provider_prompt",
                "videoPromptKind": "final_provider_prompt",
                "finalVideoPrompt": prompt,
            }
        )
        payload["videoTaskCard"] = task_card
    for key in ("referenceThumbnails", "assetThumbnails"):
        if isinstance(node_data.get(key), list):
            payload[key] = copy.deepcopy(node_data.get(key))


def _ensure_work_chain_video_task_prompt_for_generation(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_id: str,
    node: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
    existing_prompt = _video_task_card_prompt_from_node_data(node_data)
    if node.get("type") == CHARACTER_REPLACE_TASK:
        return workflow, node, node_data, {"success": True, "skipped": True}
    video_task_scope = workflow_video_task_scope(workflow, node)
    if video_task_scope not in {"work_chain", "standalone"}:
        return workflow, node, node_data, {"success": True, "skipped": True}
    if existing_prompt:
        return workflow, node, node_data, {"success": True, "skipped": True}
    if video_task_scope == "standalone":
        raise ValueError("独立视频生成缺少视频提示词，请先填写并保存。")
    raise ValueError("工作链视频生成缺少视频提示词，请先点击“生成视频提示词”。")


def _video_prompt_task_is_work_chain(
    workflow: dict[str, Any],
    node: dict[str, Any],
) -> bool:
    return workflow_video_task_scope(workflow, node) == "work_chain"


def _apply_video_generation_request_metadata_overrides(
    payload: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> None:
    if not isinstance(overrides, dict):
        return
    for key in (
        "clientRequestId",
        "client_request_id",
        "submitRealProvider",
        "submit_real_provider",
        "taskMessage",
        "task_message",
        "title",
        "resultTitle",
        "result_title",
        "versionTitle",
        "version_title",
    ):
        if key in overrides:
            payload[key] = copy.deepcopy(overrides.get(key))


def _video_task_reference_ids_from_thumbnails(rows: Any) -> list[str]:
    reference_ids: list[str] = []

    def add(value: Any) -> bool:
        text = str(value or "").strip()
        if text and text not in reference_ids:
            reference_ids.append(text)
            return True
        return bool(text)

    if not isinstance(rows, list):
        return reference_ids
    for row in rows:
        if not isinstance(row, dict):
            continue
        found_precise_id = False
        for key in (
            "mediaVersionId",
            "media_version_id",
            "sourceVersionId",
            "source_version_id",
            "versionId",
            "version_id",
            "mediaId",
            "media_id",
        ):
            if add(row.get(key)):
                found_precise_id = True
                break
        media = row.get("media") if isinstance(row.get("media"), dict) else {}
        for key in ("id", "mediaId", "media_id", "versionId", "version_id"):
            if found_precise_id:
                break
            if add(media.get(key)):
                found_precise_id = True
                break
        if found_precise_id:
            continue
        source_type = str(row.get("sourceType") or row.get("source_type") or "").strip()
        if source_type in {"media", "external_media", "generated_media", "generated", "version", "storyboard_image"}:
            for key in ("sourceId", "source_id"):
                if add(row.get(key)):
                    break
    return reference_ids


def _storyboard_video_generation_request_context(
    project_id: str,
    episode_id: str,
    node_id: str,
    *,
    user_instruction: str = "",
    requested_node_id: str | None = None,
    generation_config: dict[str, Any] | None = None,
    generation_config_provided: bool = False,
    payload_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    perf_started_at = canvas_perf_start()
    workflow = _canvas_task_context_workflow(project_id, episode_id, node_id)
    selected_node_id, video_result_node_id = _resolve_storyboard_video_task_and_result_nodes(workflow, node_id)
    if not selected_node_id:
        raise ValueError("请先在画布上选择视频生成")
    resolve_workflow_node_inputs(project_id, episode_id, {"nodeId": selected_node_id}, workflow=workflow)
    node = _workflow_node(workflow, selected_node_id) or {}
    if not _storyboard_video_task_node_type(str(node.get("type") or "")):
        raise ValueError("请先选择或连接上游视频生成")
    node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
    video_task_scope = workflow_video_task_scope(workflow, node)
    is_work_chain_video_task = video_task_scope == "work_chain"
    is_standalone_video_task = video_task_scope == "standalone"
    is_keyframe_video_task = str(node.get("type") or "") == "video.keyframe"
    if video_task_scope in {"work_chain", "standalone"}:
        workflow, node, node_data, _prompt_sync_result = (
            _ensure_work_chain_video_task_prompt_for_generation(
                project_id,
                episode_id,
                workflow,
                selected_node_id,
                node,
                payload_overrides,
            )
        )
        video_task_scope = workflow_video_task_scope(workflow, node)
        is_work_chain_video_task = video_task_scope == "work_chain"
        is_standalone_video_task = video_task_scope == "standalone"
    runtime_generation_config = _runtime_generation_config_for_execution(
        workflow,
        selected_node_id,
        requested_node_id,
        request_generation_config=generation_config,
        request_generation_config_provided=generation_config_provided,
    )
    if node.get("type") == CHARACTER_REPLACE_TASK and not (runtime_generation_config.get("modelId") or runtime_generation_config.get("model_id")):
        model_context = _video_task_card_target_model_context(project_id, node_data, {}, include_timing=False)
        runtime_generation_config["modelId"] = model_context.get("modelId") or ""
        if not runtime_generation_config["modelId"]:
            raise ValueError("请先在供应商设置获取角色替换工作流，再选择替换模式")
    title = str(node_data.get("title") or "故事版视频").strip()
    task_title = _generation_meaningful_title(title)
    route_id = str(
        node.get("routeId")
        or node.get("route_id")
        or node_data.get("routeId")
        or node_data.get("route_id")
        or ""
    ).strip()
    segment_id = str(
        node.get("segmentId")
        or node.get("segment_id")
        or node_data.get("segmentId")
        or node_data.get("segment_id")
        or ""
    ).strip()
    work_chain_id = str(
        node.get("workChainId")
        or node.get("work_chain_id")
        or node_data.get("workChainId")
        or node_data.get("work_chain_id")
        or ""
    ).strip()
    version_node_id = video_result_node_id or selected_node_id
    raw_result_title = _workflow_node_title(workflow, video_result_node_id, "") if video_result_node_id else ""
    result_title = _generation_meaningful_title(raw_result_title)
    if is_work_chain_video_task:
        image_node_ids = workflow_storyboard_reference_node_ids(
            workflow,
            node_id=selected_node_id,
        )
        ready_storyboard_image_node_ids = [
            item
            for item in image_node_ids
            if workflow_current_media_version_has_media(
                project_id,
                episode_id,
                workflow,
                item,
            )
        ]
    else:
        ready_storyboard_image_node_ids = []
    preparation_issues = _video_task_card_preparation_issues(
        node,
        has_manual_image_reference=(
            None
            if not is_standalone_video_task
            else _video_task_has_ready_manual_image_reference(project_id, episode_id, workflow, node)
        ),
        is_work_chain_node=is_work_chain_video_task,
        video_task_scope=video_task_scope,
    )
    if preparation_issues:
        raise ValueError(preparation_issues[0])
    payload = {"episodeId": episode_id, "title": task_title or title, "prompt": {}}
    _apply_video_task_card_payload_overrides(payload, node_data)
    image_node_id = ready_storyboard_image_node_ids[0] if ready_storyboard_image_node_ids else ""
    image_data = _workflow_node_data(workflow, image_node_id) if image_node_id else {}
    if image_node_id:
        payload["storyboardInterpretationContract"] = _video_task_card_storyboard_interpretation_contract(
            project_id, episode_id, _workflow_node(workflow, image_node_id),
        )
    model_config = _project_model_config(project_id)[2]
    video_section = model_config.get("video", {}) if isinstance(model_config.get("video"), dict) else {}
    work_chain_duration = None
    if is_work_chain_video_task:
        from .storyboard_allocation import assert_video_shot_allocation_current
        from .video_boundary_plan import work_chain_video_boundary_plan

        boundary_plan = work_chain_video_boundary_plan(
            workflow, node, project_id=project_id, episode_id=episode_id,
        )
        if boundary_plan["mode"] == "native_keyframe":
            runtime_generation_config["strategy"] = "native_keyframe_video"
            runtime_generation_config["inputMode"] = "native_keyframe"
            runtime_generation_config["referenceMode"] = "native_keyframe"
            runtime_generation_config["videoInputMode"] = "native_keyframe"

        work_chain_duration = _work_chain_video_duration_for_submission(
            project_id, node_data, runtime_generation_config, payload_overrides,
        )
        assert_video_shot_allocation_current(
            project_id, workflow, node,
            duration_seconds=work_chain_duration,
            generation_config=runtime_generation_config,
        )
        saved_boundary_plan = (
            (node_data.get("videoTaskCard") or {}).get("boundaryPlan")
            if isinstance(node_data.get("videoTaskCard"), dict) else None
        )
        if not isinstance(saved_boundary_plan, dict):
            raise ValueError("视频任务缺少已冻结的边界计划，请先保存视频生成提示词")
        if any(
            saved_boundary_plan.get(key) != boundary_plan.get(key)
            for key in ("sourceDirectorNodeId", "sourceGroupDependencyHash", "previousBoundaryHash",
                        "previousWorkChainId", "previousShotGroupId", "previousVideoVersionId",
                        "previousVideoFileSignature", "shotGroupId",
                        "shotNos", "boundaryKind", "audioBoundaryKind", "mode")
        ):
            raise ValueError("相邻视频边界或上一工作链分镜已变化，请重新生成视频提示词")
        payload["videoInputPlan"] = copy.deepcopy(boundary_plan)
        payload["videoInputMode"] = boundary_plan["mode"]
        if boundary_plan["mode"] == "native_keyframe":
            payload["strategy"] = "native_keyframe_video"
    if is_standalone_video_task:
        input_mode = standalone_video_input_mode(str(node.get("type") or ""))
        strategy_value = standalone_video_strategy(str(node.get("type") or ""))
        payload["videoInputMode"] = input_mode
        payload["video_input_mode"] = input_mode
        payload["referenceMode"] = input_mode
        payload["reference_mode"] = input_mode
        payload["videoInputPlan"] = {
            "mode": input_mode,
            "referenceMode": input_mode,
            "requiredSlots": standalone_video_required_slots(str(node.get("type") or "")),
        }
        payload["video_input_plan"] = copy.deepcopy(payload["videoInputPlan"])
        payload["strategy"] = strategy_value
        if runtime_generation_config:
            runtime_generation_config["videoInputMode"] = input_mode
            runtime_generation_config["inputMode"] = input_mode
            runtime_generation_config["referenceMode"] = input_mode
            runtime_generation_config["strategy"] = strategy_value
    strategy = (
        standalone_video_strategy(str(node.get("type") or ""))
        if is_standalone_video_task
        else str(
            node.get("strategy")
            or node_data.get("strategy")
            or runtime_generation_config.get("strategy")
            or ""
        ).strip()
    )
    if not strategy and route_id:
        for route in workflow.get("routes", []):
            if not isinstance(route, dict):
                continue
            if str(route.get("id") or route.get("routeId") or "").strip() == route_id:
                strategy = str(route.get("strategy") or "").strip()
                break
    if is_work_chain_video_task and payload["videoInputPlan"]["mode"] == "native_keyframe":
        strategy = "native_keyframe_video"
    payload["generationStage"] = "storyboard_video"
    payload["nodeId"] = selected_node_id
    payload["taskNodeId"] = selected_node_id
    if video_result_node_id:
        payload["resultNodeId"] = video_result_node_id
        payload["versionNodeId"] = version_node_id
    payload["nodeType"] = str(node.get("type") or "")
    if strategy:
        payload["strategy"] = strategy
    if route_id:
        payload["routeId"] = route_id
    if segment_id:
        payload["segmentId"] = segment_id
    if image_node_id:
        payload["imageNodeId"] = image_node_id
    image_version_id = str(
        image_data.get("activeVersionId")
        or image_data.get("activeMediaVersionId")
        or image_data.get("mediaVersionId")
        or ""
    ).strip()
    payload["imageVersionId"] = image_version_id
    image_version_ids: list[str] = []
    for item in ready_storyboard_image_node_ids:
        item_data = _workflow_node_data(workflow, item)
        item_version_id = str(
            item_data.get("activeVersionId")
            or item_data.get("activeMediaVersionId")
            or item_data.get("mediaVersionId")
            or ""
        ).strip()
        if item_version_id:
            image_version_ids.append(item_version_id)
    payload["imageVersionIds"] = image_version_ids
    input_validation = validate_workflow_node_inputs_ready(
        project_id,
        episode_id,
        {"nodeId": selected_node_id},
        workflow=workflow,
    )
    input_snapshot = input_validation.get("inputSnapshot") if isinstance(input_validation, dict) else {}
    if isinstance(input_snapshot, dict):
        current_references = video_task_card_current_reference_snapshot(
            project_id,
            episode_id,
            workflow,
            selected_node_id,
            input_snapshot=input_snapshot,
            for_generation=True,
        )
        reference_thumbnails = copy.deepcopy(current_references.get("referenceThumbnails") or [])
        asset_thumbnails = copy.deepcopy(current_references.get("assetThumbnails") or [])
        payload["referenceThumbnails"] = reference_thumbnails
        payload["assetThumbnails"] = asset_thumbnails
        payload["referenceVideoThumbnails"] = copy.deepcopy(
            current_references.get("referenceVideoThumbnails") or []
        )
        payload["referenceManifest"] = copy.deepcopy(
            current_references.get("referenceManifest") or []
        )
        payload["referenceManifestSnapshot"] = copy.deepcopy(
            current_references.get("referenceManifest") or []
        )
        snapshot_reference_ids = copy.deepcopy(
            current_references.get("referenceMediaIdsSnapshot")
            if isinstance(current_references.get("referenceMediaIdsSnapshot"), list)
            else input_snapshot.get("referenceMediaIds") or []
        )
        reference_media_ids = copy.deepcopy(
            current_references.get("referenceMediaIds")
            if isinstance(current_references.get("referenceMediaIds"), list)
            else []
        )
        if not reference_media_ids:
            thumbnail_reference_ids = (
                _video_task_reference_ids_from_thumbnails(reference_thumbnails)
                + _video_task_reference_ids_from_thumbnails(asset_thumbnails)
            )
            for item in snapshot_reference_ids + thumbnail_reference_ids:
                text = str(item or "").strip()
                if text and text not in reference_media_ids:
                    reference_media_ids.append(text)
        asset_reference_media_ids = copy.deepcopy(
            current_references.get("assetReferenceMediaIds")
            if isinstance(current_references.get("assetReferenceMediaIds"), list)
            else []
        )
        asset_refs_resolved_by_links = bool(current_references.get("assetRefsResolvedByInputLinks"))
        payload["inputLinksSnapshot"] = copy.deepcopy(
            current_references.get("inputLinksSnapshot")
            if isinstance(current_references.get("inputLinksSnapshot"), list)
            else input_snapshot.get("inputLinks") or []
        )
        payload["inputLinks"] = copy.deepcopy(payload["inputLinksSnapshot"])
        payload["referenceMediaIds"] = reference_media_ids
        payload["referenceMediaIdsSnapshot"] = copy.deepcopy(snapshot_reference_ids)
        if reference_thumbnails or asset_thumbnails:
            payload["referenceThumbnailsSnapshot"] = copy.deepcopy(reference_thumbnails)
            payload["assetThumbnailsSnapshot"] = copy.deepcopy(asset_thumbnails)
        else:
            payload.pop("referenceThumbnailsSnapshot", None)
            payload.pop("assetThumbnailsSnapshot", None)
        if asset_reference_media_ids and not asset_refs_resolved_by_links:
            payload["assetReferenceMediaIds"] = copy.deepcopy(asset_reference_media_ids)
        else:
            payload.pop("assetReferenceMediaIds", None)
        if asset_refs_resolved_by_links:
            payload["assetRefsResolvedByInputLinks"] = True
        else:
            payload.pop("assetRefsResolvedByInputLinks", None)
        visible_asset_refs = copy.deepcopy(current_references.get("assetRefs") or {})
        payload["assetRefsSnapshot"] = visible_asset_refs
        if visible_asset_refs:
            payload["assetRefs"] = copy.deepcopy(visible_asset_refs)
        else:
            payload.pop("assetRefs", None)
        if runtime_generation_config:
            runtime_generation_config["referenceMediaIds"] = copy.deepcopy(reference_media_ids)
            runtime_generation_config["explicitReferenceMediaIds"] = copy.deepcopy(reference_media_ids)
            if asset_reference_media_ids and not asset_refs_resolved_by_links:
                runtime_generation_config["assetReferenceMediaIds"] = copy.deepcopy(asset_reference_media_ids)
            else:
                runtime_generation_config.pop("assetReferenceMediaIds", None)
            if asset_refs_resolved_by_links:
                runtime_generation_config["assetRefsResolvedByInputLinks"] = True
            else:
                runtime_generation_config.pop("assetRefsResolvedByInputLinks", None)
    if runtime_generation_config:
        payload["resolvedConfig"] = copy.deepcopy(runtime_generation_config)
    if is_work_chain_video_task and payload["videoInputPlan"]["mode"] == "native_keyframe":
        from .video_boundary_plan import validate_direct_continuation_first_frame
        validate_direct_continuation_first_frame(
            project_id, episode_id, workflow, node, payload["videoInputPlan"],
            payload.get("inputLinksSnapshot") or [],
        )
    payload["videoModel"] = (
        runtime_generation_config.get("modelId")
        or runtime_generation_config.get("model_id")
        or video_section.get("model_id")
    )
    final_card_prompt = _video_task_card_prompt_from_node_data(node_data)
    if not final_card_prompt and node.get("type") != CHARACTER_REPLACE_TASK:
        raise ValueError("视频生成缺少视频提示词，请先填写或更新视频生成提示词")
    task_card = payload.get("videoTaskCard") if isinstance(payload.get("videoTaskCard"), dict) else {}
    task_card.update(
        {
            "promptKind": "final_provider_prompt",
            "videoPromptKind": "final_provider_prompt",
            "finalVideoPrompt": final_card_prompt,
            "dynamicPrompt": bool(is_work_chain_video_task),
        }
    )
    payload["videoTaskCard"] = task_card
    payload["videoPrompt"] = final_card_prompt
    payload["videoPromptRaw"] = final_card_prompt
    payload["videoPromptSource"] = "final_provider_prompt"
    prompt_payload = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else {}
    prompt_payload.update(
        {
            "videoPrompt": final_card_prompt,
            "videoPromptRaw": final_card_prompt,
            "videoPromptSource": "final_provider_prompt",
        }
    )
    payload["prompt"] = prompt_payload
    duration_seconds = work_chain_duration if is_work_chain_video_task else _workflow_video_task_card_duration_seconds(node_data)
    if not duration_seconds:
        raise ValueError("请先在视频生成中选择时长")
    if duration_seconds:
        payload["durationSeconds"] = duration_seconds
        task_card = payload.get("videoTaskCard") if isinstance(payload.get("videoTaskCard"), dict) else {}
        payload["videoTaskCard"] = {
            **task_card,
            "durationSeconds": duration_seconds,
        }
        resolved_payload_config = payload.get("resolvedConfig")
        if isinstance(resolved_payload_config, dict):
            resolved_payload_config.pop("duration_seconds", None)
            resolved_payload_config.pop("duration", None)
            resolved_payload_config["durationSeconds"] = duration_seconds
    payload["resolution"] = (
        runtime_generation_config.get("resolution")
        or video_section.get("resolution")
    )
    instruction = str(user_instruction or "").strip()
    if instruction:
        if is_standalone_video_task:
            payload["userInstruction"] = instruction
    if isinstance(payload_overrides, dict) and payload_overrides:
        _apply_video_generation_request_metadata_overrides(payload, payload_overrides)
    payload["taskNodeId"] = selected_node_id
    if video_result_node_id:
        payload["resultNodeId"] = video_result_node_id
        payload["versionNodeId"] = version_node_id
    version_title = str(payload.get("versionTitle") or payload.get("version_title") or result_title or task_title or title)
    canvas_perf_log(
        "storyboard_video_generation_request_context",
        projectId=project_id,
        episodeId=episode_id,
        requestedNodeId=node_id,
        selectedNodeId=selected_node_id,
        resultNodeId=video_result_node_id,
        versionNodeId=version_node_id,
        durationMs=canvas_perf_elapsed_ms(perf_started_at),
        workflowNodeCount=len(workflow.get("nodes")) if isinstance(workflow.get("nodes"), list) else 0,
        referenceMediaIdCount=len(payload.get("referenceMediaIds")) if isinstance(payload.get("referenceMediaIds"), list) else 0,
        imageVersionIdCount=len(image_version_ids),
    )
    return {
        "workflow": workflow,
        "node": node,
        "nodeData": node_data,
        "videoTaskScope": video_task_scope,
        "selectedNodeId": selected_node_id,
        "resultNodeId": video_result_node_id,
        "versionNodeId": version_node_id,
        "title": title,
        "taskTitle": task_title,
        "resultTitle": result_title,
        "versionTitle": version_title,
        "payload": payload,
    }


def _storyboard_video_generation_start_context(
    project_id: str,
    episode_id: str,
    node_id: str,
    *,
    payload_overrides: dict[str, Any] | None = None,
    generation_config: dict[str, Any] | None = None,
    generation_config_provided: bool = False,
) -> dict[str, Any]:
    perf_started_at = canvas_perf_start()
    requested_node_id = str(node_id or "").strip()
    if not project_id or not episode_id or not requested_node_id:
        raise ValueError("视频生成缺少 projectId、episodeId 或 nodeId")
    payload = copy.deepcopy(payload_overrides) if isinstance(payload_overrides, dict) else {}
    workflow = read_workflow_card_neighborhood_v4(project_id, episode_id, requested_node_id, detail="full")
    selected_node_id, video_result_node_id = _resolve_storyboard_video_task_and_result_nodes(workflow, requested_node_id)
    if not selected_node_id:
        raise ValueError("请先在画布上选择视频生成")
    node = _workflow_node(workflow, selected_node_id) or {}
    if not _storyboard_video_task_node_type(str(node.get("type") or "")):
        raise ValueError("请先选择或连接上游视频生成")
    node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
    video_task_scope = workflow_video_task_scope(workflow, node)
    if video_task_scope == "work_chain":
        from .storyboard_allocation import assert_video_shot_allocation_current

        runtime_config = _runtime_generation_config_for_execution(
            workflow,
            selected_node_id,
            requested_node_id,
            request_generation_config=generation_config,
            request_generation_config_provided=generation_config_provided,
        )
        duration = _work_chain_video_duration_for_submission(
            project_id, node_data, runtime_config, payload_overrides,
        )
        assert_video_shot_allocation_current(
            project_id, workflow, node,
            duration_seconds=duration,
            generation_config=runtime_config,
        )
    if video_task_scope in {"work_chain", "standalone"}:
        workflow, node, node_data, _prompt_sync_result = (
            _ensure_work_chain_video_task_prompt_for_generation(
                project_id,
                episode_id,
                workflow,
                selected_node_id,
                node,
                payload,
            )
        )
        video_task_scope = workflow_video_task_scope(workflow, node)
    version_node_id = video_result_node_id or selected_node_id
    raw_result_title = _workflow_node_title(workflow, video_result_node_id, "") if video_result_node_id else ""
    result_title = _generation_meaningful_title(str(payload.get("resultTitle") or payload.get("result_title") or raw_result_title))
    title = str(payload.get("title") or node_data.get("title") or result_title or "故事版视频").strip()
    task_title = _generation_meaningful_title(title) or title
    version_title = str(
        payload.get("versionTitle")
        or payload.get("version_title")
        or result_title
        or task_title
        or title
    ).strip()
    work_chain_fields = _workflow_task_work_chain_fields(workflow, selected_node_id, payload=payload)
    canvas_perf_log(
        "storyboard_video_generation_start_context",
        projectId=project_id,
        episodeId=episode_id,
        requestedNodeId=requested_node_id,
        selectedNodeId=selected_node_id,
        resultNodeId=video_result_node_id,
        versionNodeId=version_node_id,
        durationMs=canvas_perf_elapsed_ms(perf_started_at),
        workflowNodeCount=len(workflow.get("nodes")) if isinstance(workflow.get("nodes"), list) else 0,
    )
    return {
        "workflow": workflow,
        "node": node,
        "nodeData": node_data,
        "selectedNodeId": selected_node_id,
        "resultNodeId": video_result_node_id,
        "versionNodeId": version_node_id,
        "title": title,
        "taskTitle": task_title,
        "resultTitle": result_title,
        "versionTitle": version_title or result_title or task_title or title,
        "workChainFields": work_chain_fields,
        "videoTaskScope": video_task_scope,
    }


def _storyboard_video_job_from_request_context(
    task_id: str,
    request_context: dict[str, Any],
    *,
    client_request_id: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected_node_id = str(request_context.get("selectedNodeId") or "")
    video_result_node_id = str(request_context.get("resultNodeId") or "")
    version_node_id = str(request_context.get("versionNodeId") or selected_node_id)
    title = str(request_context.get("title") or "故事版视频")
    task_title = str(request_context.get("taskTitle") or title)
    result_title = str(request_context.get("resultTitle") or "")
    version_title = str(request_context.get("versionTitle") or result_title or task_title or title)
    payload = copy.deepcopy(request_context.get("payload") if isinstance(request_context.get("payload"), dict) else {})
    if client_request_id:
        payload["clientRequestId"] = str(client_request_id)
    if idempotency_key:
        payload["idempotencyKey"] = str(idempotency_key)
    payload["taskId"] = task_id
    job = {
        "phase": "created",
        "title": version_title,
        "taskTitle": title,
        "resultTitle": result_title or version_title,
        "payload": payload,
        "taskNodeId": selected_node_id,
        "resultNodeId": video_result_node_id,
        "versionNodeId": version_node_id,
    }
    return job, payload


def _add_storyboard_video_blocked_version(
    project_id: str,
    episode_id: str,
    version_node_id: str,
    job: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    debug_payload = copy.deepcopy(job.get("debug") if isinstance(job.get("debug"), dict) else {})
    for key in ("debugBlockLog", "debugBlockLogError"):
        if key in job:
            debug_payload[key] = copy.deepcopy(job.get(key))
    metadata = {
        "title": str(job.get("title") or "故事版视频"),
        "summary": message,
        "source": "model-video-job",
        "payload": payload,
        "generationError": message,
        **(
            {"generationDebug": _persistent_media_data_removed(debug_payload)}
            if debug_payload
            else {}
        ),
        "status": "blocked",
        "preview": _generated_version_preview("video", str(job.get("title") or "故事版视频"), payload),
    }
    return add_storyboard_version(
        project_id,
        episode_id,
        version_node_id,
        "video",
        metadata,
    )


def _storyboard_video_processing_version_and_job(
    project_id: str,
    episode_id: str,
    task_id: str,
    request_context: dict[str, Any],
    *,
    client_request_id: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    selected_node_id = str(request_context.get("selectedNodeId") or "")
    version_node_id = str(request_context.get("versionNodeId") or selected_node_id)
    version_title = str(request_context.get("versionTitle") or request_context.get("resultTitle") or request_context.get("taskTitle") or request_context.get("title") or "故事版视频")
    job, payload = _storyboard_video_job_from_request_context(
        task_id,
        request_context,
        client_request_id=client_request_id,
        idempotency_key=idempotency_key,
    )
    version_payload = _storyboard_video_version_payload_for_storage(payload)
    metadata = {
        "title": version_title,
        "summary": str(
            payload.get("processingSummary")
            or payload.get("processing_summary")
            or "视频任务已进入后台队列，正在等待供应商提交。"
        ),
        "source": "model-video-job",
        "payload": version_payload,
        "status": "processing",
        "preview": _generated_version_preview("video", version_title, payload),
    }
    version = add_storyboard_version(
        project_id,
        episode_id,
        version_node_id,
        "video",
        metadata,
    )
    job["versionId"] = version["id"]
    return version, job, payload
