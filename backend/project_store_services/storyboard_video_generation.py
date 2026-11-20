# -*- coding: utf-8 -*-
"""视频生成请求构建、输入约束检查、提交与成片保存。"""
from __future__ import annotations
from utils.video_task_types import CHARACTER_REPLACE_TASK, model_supports_video_task, standalone_video_strategy, standalone_video_required_slots
from .canvas_ownership import VIDEO_TASK_NODE_TYPES

from .media_files import _decode_data_url
from .media_files import _save_project_media_file
from .model_generation_contract import _model_final_prompt_profile
from .model_generation_contract import _model_prompt_timing_style
from .model_generation_contract import _normalize_video_generation_strategy
from .model_generation_contract import _normalize_video_input_mode
from .model_generation_contract import _project_ai_content_disclosure_metadata
from .model_generation_contract import _video_input_mode_for_strategy
from .model_generation_contract import _video_reference_mode_for_input_mode
from .model_generation_contract import _video_strategy_for_input_mode
from .model_provider_config import _api_model_name
from .model_provider_config import _configured_provider_for_model
from .model_provider_config import _debug_block_builtin_video_provider_and_model
from .model_provider_config import _get_effective_config
from .model_provider_config import _project_model_config
from .model_provider_config import _provider_base_url
from .model_provider_config import _video_generation_debug_block_enabled
from .model_request_logs import STAGE_FINAL_VIDEO_GENERATION_REQUEST
from .model_request_logs import model_request_log_reference
from .model_request_logs import write_model_request_log
from .perf_logging import canvas_perf_elapsed_ms
from .perf_logging import canvas_perf_log
from .perf_logging import canvas_perf_start
from .production_specs import normalize_production_aspect_ratio
from .provider_models import _align_provider_model_metadata
from .provider_models import _find_model
from .provider_models import _is_connected_provider
from .provider_models import _model_generation_endpoint
from .provider_models import _model_duration_options
from .provider_models import _provider_adapter_id
from .provider_models import _provider_service_id
from .provider_models import _provider_supports_direct_media_generation
from .provider_models import _video_output_size
from .provider_models import _validated_video_resolution
from .video_generation_prompt import _video_prompt_and_budget_from_generation_payload
from .video_generation_prompt import _current_video_task_prompt_from_payload
from .video_generation_prompt import _video_voice_style_provider_line
from .video_provider_references import _video_provider_reference_plan
from typing import Any
from utils.media_backends import generate_video_media
from utils.media_backends import video_prompt_char_limit
from utils.image_pipeline import image_display_size
import copy
import io
import uuid

def _storyboard_video_debug_block_request_log_input(request: dict[str, Any]) -> dict[str, Any]:
    provider_request = request.get("providerRequest") if isinstance(request.get("providerRequest"), dict) else {}
    reference_images = request.get("referenceImages") if isinstance(request.get("referenceImages"), list) else []
    reference_image_count = len(reference_images) if reference_images else int(bool(request.get("referenceImage")))
    request_body = {
        "model": request.get("modelName") or "",
        "prompt": str(request.get("prompt") or ""),
        "durationSeconds": request.get("durationSeconds"),
        "aspectRatio": request.get("aspectRatio"),
        "resolution": request.get("resolution"),
        "size": request.get("size"),
        "generateAudio": bool(request.get("generateAudio")),
        "strategy": provider_request.get("strategy") or "",
        "planningStrategy": provider_request.get("planningStrategy") or "",
        "videoInputMode": provider_request.get("videoInputMode") or "",
        "referenceMode": provider_request.get("referenceMode") or "",
        "referenceImageCount": reference_image_count,
        "mediaOmitted": True,
        "debugBlocked": True,
    }
    return {
        "provider": request.get("providerId") or "",
        "transport": "debug-block",
        "method": "DRY_RUN",
        "url": request.get("endpoint") or "",
        "requestBody": {
            key: value
            for key, value in request_body.items()
            if value not in (None, "", [], {})
        },
    }


def _validate_native_frame_aspect_ratio(
    references: list[dict[str, Any]], model: dict[str, Any], aspect_ratio: str,
    *, native_required: bool = False,
) -> None:
    visual = (model.get("adapter_capabilities") or {}).get(
        "keyframe_visual_inputs" if native_required else "visual_inputs"
    ) or {}
    if not visual.get("native_frame_controls_aspect_ratio"):
        return
    from PIL import Image

    ratio_width, ratio_height = (float(value) for value in aspect_ratio.split(":"))
    for reference in references:
        if reference.get("transportRole") != "first_frame":
            continue
        raw, _mime = _decode_data_url(reference.get("dataUrl") or "")
        with Image.open(io.BytesIO(raw)) as frame:
            width, height = image_display_size(frame)
        if abs((width / height) / (ratio_width / ratio_height) - 1) > 0.01:
            advice = (
                "请更换与项目同画幅的首帧图片，或调整项目画幅；首尾帧视频生成必须保留原生约束。"
                if native_required else
                "请更换同画幅的帧画面，或关闭原生首帧约束后作为普通参考图生成。"
            )
            raise ValueError(
                f"原生首帧画幅 {width}×{height} 与项目 {aspect_ratio} 不一致；"
                f"{advice}"
            )


def _video_output_aspect_ratio(
    project_config: dict[str, Any],
    resolved_config: dict[str, Any],
) -> str:
    project_video_config = (
        project_config.get("video")
        if isinstance(project_config.get("video"), dict)
        else {}
    )
    return normalize_production_aspect_ratio(
        project_config.get("aspect_ratio")
        or project_config.get("aspectRatio")
        or project_video_config.get("aspect_ratio")
        or project_video_config.get("aspectRatio")
        or resolved_config.get("aspectRatio")
        or resolved_config.get("aspect_ratio")
        or "16:9"
    )


def _video_task_scope_from_payload_or_workflow(
    payload: dict[str, Any],
    workflow: dict[str, Any] | None,
) -> str:
    from .canvas_ownership import video_task_scope

    node_id = str(payload.get("taskNodeId") or payload.get("nodeId") or "").strip()
    node = next((row for row in (workflow or {}).get("nodes", []) if row.get("id") == node_id), None)
    if not node or node.get("type") not in VIDEO_TASK_NODE_TYPES:
        raise ValueError("未找到视频生成")
    return video_task_scope(node)


def _video_input_plan_from_payload(
    payload: dict[str, Any],
    resolved_config: dict[str, Any],
    fallback_strategy: Any = None,
) -> dict[str, Any]:
    for value in (
        payload.get("videoInputPlan"),
        payload.get("video_input_plan"),
        resolved_config.get("videoInputPlan"),
        resolved_config.get("video_input_plan"),
    ):
        if isinstance(value, dict):
            plan = copy.deepcopy(value)
            raw_mode = (
                plan.get("mode")
                or plan.get("inputMode")
                or plan.get("input_mode")
                or plan.get("referenceMode")
                or plan.get("reference_mode")
            )
            mode = _normalize_video_input_mode(raw_mode)
            if mode:
                plan["mode"] = mode
                plan["referenceMode"] = _video_reference_mode_for_input_mode(mode)
                return plan
    raw_mode = (
        payload.get("videoInputMode")
        or payload.get("video_input_mode")
        or resolved_config.get("videoInputMode")
        or resolved_config.get("video_input_mode")
        or resolved_config.get("inputMode")
        or resolved_config.get("referenceMode")
    )
    mode = _normalize_video_input_mode(raw_mode) or _video_input_mode_for_strategy(fallback_strategy)
    return {"mode": mode, "referenceMode": _video_reference_mode_for_input_mode(mode)}


def _video_generate_audio_enabled(
    resolved_config: dict[str, Any],
    video_config: dict[str, Any],
    model: dict[str, Any],
) -> bool:
    # Video audio follows model capability, not a separate task or project toggle.
    return bool(
        model.get("audio") is True
        or model.get("supports_native_audio") is True
        or model.get("supportsNativeAudio") is True
        or "native_audio" in (model.get("supports") or [])
    )


def _build_storyboard_video_request(
    project_id: str,
    episode_id: str,
    title: str,
    payload: dict[str, Any],
    workflow: dict[str, Any],
    *,
    prepare_transport_media: bool = True,
    include_asset_reference_prompt: bool = True,
) -> dict[str, Any]:
    from .storyboard_prompt_content import _storyboard_payload_duration_seconds

    perf_started_at = canvas_perf_start()
    resolved_config = payload.get("resolvedConfig") if isinstance(payload.get("resolvedConfig"), dict) else {}
    global_config, capabilities, model_config = _project_model_config(project_id)
    video_config = model_config.get("video", {}) if isinstance(model_config.get("video"), dict) else {}
    model_id = str(
        resolved_config.get("modelId")
        or resolved_config.get("model_id")
        or video_config.get("model_id")
        or ""
    ).strip()
    debug_block_enabled = _video_generation_debug_block_enabled(project_id)
    model = _find_model(model_id, "video", capabilities) if model_id else None
    provider = _configured_provider_for_model(model, global_config.get("providers", []))
    debug_block_catalog_model_used = False
    debug_block_provider_connection_bypassed = False
    if debug_block_enabled and model_id and (not model or not provider or not _is_connected_provider(provider)):
        catalog_provider, catalog_model = _debug_block_builtin_video_provider_and_model(model_id)
        if catalog_model and not model:
            model = catalog_model
            debug_block_catalog_model_used = True
        if catalog_provider:
            if not provider:
                provider = catalog_provider
                debug_block_provider_connection_bypassed = True
            elif not _is_connected_provider(provider):
                fallback_base_url = _provider_base_url(catalog_provider)
                provider = copy.deepcopy(provider)
                if fallback_base_url and not _provider_base_url(provider):
                    provider["base_url"] = fallback_base_url
                if not _provider_adapter_id(provider):
                    provider["adapter_id"] = catalog_provider.get("adapter_id") or catalog_provider.get("adapterId")
                debug_block_provider_connection_bypassed = True
        if provider and model:
            model = _align_provider_model_metadata(provider, model)
    if not provider or not model or (not debug_block_enabled and not _is_connected_provider(provider)):
        raise RuntimeError("视频模型供应商未连接")
    if debug_block_enabled and not _is_connected_provider(provider):
        debug_block_provider_connection_bypassed = True
    base_url = _provider_base_url(provider)
    if not base_url:
        raise RuntimeError("视频供应商 Base URL 为空")
    provider_id = _provider_service_id(provider)
    endpoint = _model_generation_endpoint(provider, model)
    if not _provider_supports_direct_media_generation(provider, "video", model):
        raise RuntimeError(f"当前视频供应商 {provider_id or 'unknown'} 暂未接入 ai-video 直接出视频适配")
    project_config = _get_effective_config(project_id)
    video_task_scope = _video_task_scope_from_payload_or_workflow(payload, workflow)
    payload = {**payload, "videoTaskScope": video_task_scope}
    keyframe_task = str(payload.get("nodeType") or "") == "video.keyframe"
    replacement_task = payload.get("nodeType") == CHARACTER_REPLACE_TASK
    if not model_supports_video_task(model, str(payload.get("nodeType") or "video.storyboard")):
        raise ValueError("所选模型与视频任务类型不匹配，请选择匹配的工作流")
    planning_strategy = str(
        payload.get("strategy")
        or resolved_config.get("strategy")
        or ("image_reference_video" if video_task_scope == "standalone" else "storyboard_multi_shot")
    ).strip()
    if video_task_scope == "standalone":
        planning_strategy = standalone_video_strategy(str(payload.get("nodeType") or ""))
    planning_strategy = _normalize_video_generation_strategy(planning_strategy)
    video_input_plan = _video_input_plan_from_payload(payload, resolved_config, planning_strategy)
    if video_task_scope == "work_chain":
        from .workflow_contract import _workflow_node
        from .video_boundary_plan import work_chain_video_boundary_plan
        task_node = _workflow_node(workflow, str(payload.get("taskNodeId") or payload.get("nodeId") or ""))
        boundary_plan = work_chain_video_boundary_plan(
            workflow, task_node, project_id=project_id, episode_id=episode_id,
        )
        saved_boundary_plan = ((task_node.get("data") or {}).get("videoTaskCard") or {}).get("boundaryPlan")
        if not isinstance(saved_boundary_plan, dict):
            raise ValueError("视频任务缺少已冻结的边界计划，请先保存视频生成提示词")
        if any(
            saved_boundary_plan.get(key) != boundary_plan.get(key)
            for key in ("sourceDirectorNodeId", "sourceGroupDependencyHash", "previousBoundaryHash",
                        "previousWorkChainId", "previousShotGroupId", "previousVideoVersionId",
                        "previousVideoFileSignature", "shotGroupId",
                        "shotNos", "boundaryKind", "audioBoundaryKind", "mode")
        ):
            raise ValueError("正式分镜或上一工作链边界已变化，请重新生成视频提示词")
        if video_input_plan.get("sourceGroupDependencyHash") and any(
            video_input_plan.get(key) != boundary_plan.get(key)
            for key in ("sourceDirectorNodeId", "sourceGroupDependencyHash", "previousBoundaryHash",
                        "previousWorkChainId", "previousShotGroupId", "previousVideoVersionId",
                        "previousVideoFileSignature",
                        "shotGroupId", "shotNos", "boundaryKind", "audioBoundaryKind", "mode")
        ):
            raise ValueError("视频边界计划已变化，请重新生成视频提示词后提交")
        video_input_plan = boundary_plan
        payload["videoInputPlan"] = copy.deepcopy(boundary_plan)
        if boundary_plan["mode"] == "native_keyframe":
            from .video_boundary_plan import validate_direct_continuation_first_frame
            validate_direct_continuation_first_frame(
                project_id, episode_id, workflow, task_node, boundary_plan,
                payload.get("inputLinksSnapshot") or payload.get("inputLinks") or [],
            )
    if replacement_task:
        video_input_plan = {"mode": "character_replace", "referenceMode": "character_replace",
                            "requiredSlots": standalone_video_required_slots(CHARACTER_REPLACE_TASK)}
    elif video_task_scope == "standalone" and not keyframe_task:
        video_input_plan = {
            **video_input_plan,
            "mode": "image_reference",
            "referenceMode": "image_reference",
            "requiredSlots": ["image_reference"],
        }
    elif keyframe_task:
        video_input_plan = {**video_input_plan, "mode": "native_keyframe", "referenceMode": "native_keyframe", "requiredSlots": ["frame_reference"]}
    video_input_mode = str(video_input_plan.get("mode") or "").strip() or "storyboard_reference"
    strategy = _video_strategy_for_input_mode(planning_strategy, video_input_mode)
    strategy = _normalize_video_generation_strategy(strategy)
    generate_audio = _video_generate_audio_enabled(resolved_config, video_config, model)
    resolution = _validated_video_resolution(
        model, resolved_config.get("resolution") or video_config.get("resolution"),
    )
    try:
        duration = int(
            payload.get("durationSeconds")
            or payload.get("duration_seconds")
            or resolved_config.get("durationSeconds")
            or resolved_config.get("duration_seconds")
            or 0
        )
    except (TypeError, ValueError):
        duration = 0
    raw_allowed_durations = model.get("durations") if isinstance(model.get("durations"), list) else []
    if keyframe_task or video_input_plan.get("mode") == "native_keyframe":
        raw_allowed_durations = _model_duration_options(
            model, resolution, native_keyframe=True,
        )
    if not raw_allowed_durations:
        raw_allowed_durations = (
            model.get("allowedDurations") if isinstance(model.get("allowedDurations"), list) else []
        )
    allowed_durations: list[int] = []
    for item in raw_allowed_durations:
        if isinstance(item, bool):
            continue
        try:
            raw_allowed_duration = float(item)
        except (TypeError, ValueError):
            continue
        if abs(raw_allowed_duration - round(raw_allowed_duration)) > 0.005:
            continue
        allowed_duration = int(round(raw_allowed_duration))
        if allowed_duration > 0 and allowed_duration not in allowed_durations:
            allowed_durations.append(allowed_duration)
    if duration <= 0:
        duration = _storyboard_payload_duration_seconds(payload, workflow) or 0
    if duration <= 0:
        raise RuntimeError("当前视频任务缺少可用视频时长，无法实时生成视频片段。")
    requested_duration = duration
    if allowed_durations and duration not in allowed_durations:
        raise RuntimeError(
            f"当前视频任务时长 {duration} 秒不在所选视频模型支持范围内："
            f"{', '.join(str(item) for item in allowed_durations)} 秒；"
            "请修改时长或切换视频模型。"
        )
    aspect_ratio = _video_output_aspect_ratio(project_config, resolved_config)
    size = _video_output_size(model, resolution, aspect_ratio)
    reference_image, reference_images, reference_plan = _video_provider_reference_plan(
        project_id,
        episode_id,
        payload,
        workflow,
        resolved_config,
        strategy,
        model,
        prepare_transport_media=prepare_transport_media,
        output_duration=duration,
    )
    if video_task_scope == "work_chain":
        boundary_kind = video_input_plan.get("boundaryKind")
        references = reference_plan.get("references") or []
        if boundary_kind == "time_space_jump" and any(
            row.get("slot") == "visual_handoff_reference" for row in references
        ):
            raise ValueError("时空跳转不能绑定上一段视觉交接图，请移除该输入后再生成")
        if boundary_kind == "spatial_cut" and any(
            row.get("slot") == "visual_handoff_reference"
            and row.get("transportRole") != "reference_image" for row in references
        ):
            raise ValueError("视觉交接图只能作为参考图，不能作为原生首帧")
    if prepare_transport_media:
        _validate_native_frame_aspect_ratio(reference_images, model, aspect_ratio,
                                            native_required=video_input_mode == "native_keyframe")
    if (
        prepare_transport_media
        and video_task_scope == "standalone"
        and not keyframe_task
        and strategy != "text_to_video_draft"
        and int(reference_plan.get("resolvedReferenceCount") or 0) <= 0
    ):
        raise RuntimeError("独立视频生成缺少当前可用的图片参考，请先关联至少一张当前版本有媒体的图片资产。")
    transport_block_reason = str(reference_plan.get("transportBlockReason") or "").strip()
    if prepare_transport_media and strategy != "text_to_video_draft" and transport_block_reason:
        raise RuntimeError(transport_block_reason)
    if (
        prepare_transport_media
        and strategy != "text_to_video_draft"
        and int(reference_plan.get("resolvedReferenceCount") or 0) > 0
        and int(reference_plan.get("transportReferenceCount") or 0) <= 0
    ):
        raise RuntimeError(
            "视频任务已绑定参考图，但当前模型/策略不会把任何参考图发送给供应商。"
            "请切换支持故事版参考图的模型后再生成。"
        )
    resolved_reference_count = int(reference_plan.get("resolvedReferenceCount") or 0)
    transport_reference_count = int(reference_plan.get("transportReferenceCount") or 0)
    if prepare_transport_media and transport_reference_count < resolved_reference_count:
        provider_reference_limit = int(reference_plan.get("providerReferenceLimit") or transport_reference_count or 0)
        raise RuntimeError(
            f"当前任务包含 {resolved_reference_count} 张参考图，超过所选模型参考图上限 "
            f"{provider_reference_limit} 张；已阻断生成，不能裁掉多余参考图后提交不完整资料。"
            "请减少参考图或切换支持更多参考图的模型。"
        )
    prompt_limit = video_prompt_char_limit(
        provider_id,
        _api_model_name(model.get("id")),
        model=model,
        strategy=strategy,
    )
    final_prompt_profile = _model_final_prompt_profile(model)
    prompt_timing_style = _model_prompt_timing_style(model)
    current_model_id = str(model.get("id") or model_id or "").strip()
    from .video_reference_audio import resolve_video_task_voices

    source_voice_prompt = _current_video_task_prompt_from_payload(payload) if not replacement_task else ""
    voices = resolve_video_task_voices(
        project_id, payload, {**model, "provider_preset_id": provider_id, "endpoint": endpoint},
        prompt=source_voice_prompt,
        manifest=reference_plan.get("referenceManifest") or [],
        native=video_input_mode == "native_keyframe", enabled=generate_audio and not replacement_task,
        prepare_transport=prepare_transport_media, validate_files=prepare_transport_media,
    ) if source_voice_prompt else {"speakers": [], "referenceAudios": [], "prompt": ""}
    voice_payload = copy.deepcopy(payload)
    if voices["speakers"]:
        voice_payload["videoTaskCard"] = {**(payload.get("videoTaskCard") or {}), "soundPrompt": voices["soundPrompt"]}
    if replacement_task:
        from .character_replacement import character_replacement_prompt
        prompt, prompt_budget = character_replacement_prompt(payload, reference_plan["referenceManifest"])
        if prepare_transport_media and len(reference_plan.get("referenceVideos") or []) != 1:
            raise ValueError("角色替换必须关联且只能关联一段可用源视频")
    else:
        prompt, prompt_budget = _video_prompt_and_budget_from_generation_payload(
            title,
            voice_payload,
            {
                **resolved_config,
                "aspectRatio": aspect_ratio,
                "modelId": current_model_id,
            },
            project_id=project_id,
            generate_audio=generate_audio,
            reference_images=reference_images,
            prompt_char_limit=prompt_limit,
            final_prompt_profile=final_prompt_profile,
            prompt_timing_style=prompt_timing_style,
            include_asset_reference_prompt=include_asset_reference_prompt,
            reference_manifest=reference_plan["referenceManifest"],
        )
    audio_config = copy.deepcopy(resolved_config.get("audio")) if isinstance(resolved_config.get("audio"), dict) else {}
    if generate_audio:
        audio_config["mode"] = "native_audio"
        audio_config["effectiveMode"] = "native_audio"
    audio_plan = payload.get("audioPlan") if isinstance(payload.get("audioPlan"), dict) else {}
    if audio_plan:
        audio_config["postAudioPlan"] = copy.deepcopy(audio_plan)
    if replacement_task:
        audio_config = {"mode": "source_audio", "effectiveMode": "source_audio"}
    if voices["speakers"]:
        audio_config["voiceSources"] = copy.deepcopy(voices["speakers"])
        audio_config["referenceAudios"] = [
            {key: row[key] for key in ("speakerId", "displayName", "binding", "duration", "size", "format", "sha256", "transport") if key in row}
            for row in voices["referenceAudios"]
        ]
    voice_style_available = not replacement_task and bool(_video_voice_style_provider_line(
        project_id,
        payload,
        limit=0,
        existing_prompt="",
    ))
    reference_audio_count = len(voices["referenceAudios"])
    provider_request = {
        "strategy": strategy,
        "planningStrategy": planning_strategy,
        "videoInputMode": video_input_mode,
        "videoTaskScope": video_task_scope,
        "transportMediaPrepared": bool(prepare_transport_media),
        "modelId": model.get("id"),
        "providerId": provider_id,
        "endpoint": endpoint,
        "size": size,
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
        "durationSeconds": duration,
        "requestedDurationSeconds": requested_duration,
        "generateAudio": generate_audio,
        "productionTrace": {
            "aiContentDisclosure": _project_ai_content_disclosure_metadata(project_config),
        },
        "referenceMode": video_input_plan.get("referenceMode") or "storyboard_image",
        "videoInputPlan": video_input_plan,
        "referencePlan": reference_plan,
        "promptBudget": prompt_budget,
        "debugBlockProviderConnectionBypassed": debug_block_provider_connection_bypassed,
        "debugBlockCatalogModelUsed": debug_block_catalog_model_used,
    }
    if audio_config:
        provider_request["audio"] = audio_config
    analysis_snapshot = {
        "stage": STAGE_FINAL_VIDEO_GENERATION_REQUEST,
        "providerId": provider_id,
        "provider": provider_id,
        "modelName": _api_model_name(model.get("id")),
        "model": model.get("id"),
        "modelFamily": (
            "seedance-2.5"
            if any(token in str(model.get("id") or "").lower() for token in ("2.5", "2-5", "2_5"))
            else "seedance-2.0"
            if any(token in str(model.get("id") or "").lower() for token in ("2.0", "2-0", "2_0"))
            else "seedance"
            if "seedance" in str(model.get("id") or "").lower()
            else ""
        ),
        "endpoint": endpoint,
        "finalPrompt": prompt,
        "finalPromptChars": len(prompt),
        "durationSeconds": duration,
        "requestedDurationSeconds": requested_duration,
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
        "size": size,
        "generateAudio": generate_audio,
        "hasVoiceDescription": voice_style_available,
        "voiceStyleAvailable": voice_style_available,
        "voiceStyleSupplementIncluded": bool(prompt_budget.get("voiceStyleSupplementIncluded")),
        "hasReferenceAudio": reference_audio_count > 0,
        "referenceAudioCount": reference_audio_count,
        "audioConfigIncluded": bool(audio_config),
        "referenceImageCount": len(reference_images) if isinstance(reference_images, list) else int(bool(reference_image)),
        "videoInputMode": video_input_mode,
        "strategy": strategy,
        "planningStrategy": planning_strategy,
        "referenceMode": video_input_plan.get("referenceMode") or "storyboard_image",
        "promptBudget": prompt_budget,
        "containsOnImageShotLabels": bool(reference_plan.get("storyboardSheetReferenceCount")),
        "debugBlockProviderConnectionBypassed": debug_block_provider_connection_bypassed,
        "debugBlockCatalogModelUsed": debug_block_catalog_model_used,
    }
    assembly_context = {
        "purpose": "最终生成视频模型输入日志，由本地程序确定性记录，不调用模型总结。",
        "primaryUse": "用于后续判断视频提示词是否符合目标供应商官方推荐写法，以及分镜图、声音、镜头表达是否与提示词一致。",
        "promptSource": {
            "title": title,
            "payloadKeys": sorted(str(key) for key in payload.keys()),
            "resolvedConfigKeys": sorted(str(key) for key in resolved_config.keys()),
            "promptBudget": prompt_budget,
            "finalPromptProfile": final_prompt_profile,
            "promptTimingStyle": prompt_timing_style,
        },
        "referencePlan": copy.deepcopy(reference_plan),
        "videoInputPlan": copy.deepcopy(video_input_plan),
        "audioConfig": copy.deepcopy(audio_config),
        "providerRequest": copy.deepcopy(provider_request),
    }
    request_result = {
        "provider": provider,
        "providerId": provider_id,
        "baseUrl": base_url,
        "model": model,
        "modelName": _api_model_name(model.get("id")),
        "prompt": prompt,
        "referenceImage": reference_image,
        "referenceImages": reference_images,
        "referenceVideos": copy.deepcopy(reference_plan.get("referenceVideos") or []),
        "referenceAudios": voices["referenceAudios"],
        **({"replacementSubject": str(resolved_config.get("replacementSubject") or "person")} if replacement_task else {}),
        "imageInputLimits": reference_plan.get("referenceInputLimits") if isinstance(reference_plan, dict) else {},
        "providerRequest": provider_request,
        "size": size,
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
        "durationSeconds": duration,
        "generateAudio": generate_audio,
        "endpoint": endpoint,
        "analysisSnapshot": analysis_snapshot,
        "assemblyContext": assembly_context,
    }
    canvas_perf_log(
        "build_storyboard_video_request",
        projectId=project_id,
        episodeId=episode_id,
        nodeId=str(payload.get("nodeId") or payload.get("node_id") or ""),
        status="ok",
        durationMs=canvas_perf_elapsed_ms(perf_started_at),
        debugBlockEnabled=bool(debug_block_enabled),
        prepareTransportMedia=bool(prepare_transport_media),
        strategy=strategy,
        videoInputMode=video_input_mode,
        promptChars=len(prompt),
        referenceImageCount=len(reference_images) if isinstance(reference_images, list) else int(bool(reference_image)),
        resolvedReferenceCount=int(reference_plan.get("resolvedReferenceCount") or 0),
        transportReferenceCount=int(reference_plan.get("transportReferenceCount") or 0),
    )
    return request_result


def _generate_storyboard_video_media(
    project_id: str,
    episode_id: str,
    title: str,
    payload: dict[str, Any],
    workflow: dict[str, Any],
) -> dict[str, Any]:
    debug_block_enabled = _video_generation_debug_block_enabled(project_id)
    request = _build_storyboard_video_request(
        project_id,
        episode_id,
        title,
        payload,
        workflow,
        prepare_transport_media=not debug_block_enabled,
    )
    final_video_request_log: dict[str, Any] = {}
    final_video_request_log_errors: list[dict[str, Any]] = []

    def log_video_request(request_info: dict[str, Any]) -> None:
        nonlocal final_video_request_log
        log_result = write_model_request_log(
            project_id,
            STAGE_FINAL_VIDEO_GENERATION_REQUEST,
            request_info,
            episode_id=episode_id,
            node_id=str(payload.get("nodeId") or payload.get("node_id") or ""),
            phase="direct-video-generation",
            provider_id=str(request.get("providerId") or ""),
            model_name=str(request.get("modelName") or ""),
            endpoint=str(request.get("endpoint") or ""),
            blocked=debug_block_enabled,
            source=(
                "_generate_storyboard_video_media.dry_run"
                if debug_block_enabled
                else "_generate_storyboard_video_media"
            ),
            analysis_snapshot={**copy.deepcopy(request.get("analysisSnapshot") or {}), "blocked": debug_block_enabled},
            assembly_context=request.get("assemblyContext") if isinstance(request.get("assemblyContext"), dict) else {},
            background=not debug_block_enabled,
        )
        final_video_request_log = copy.deepcopy(log_result)
        if not log_result.get("success"):
            final_video_request_log_errors.append(
                {
                    "stage": STAGE_FINAL_VIDEO_GENERATION_REQUEST,
                    "phase": "direct-video-generation",
                    "error": str(log_result.get("error") or "日志写入失败"),
                }
            )

    if debug_block_enabled:
        log_video_request(_storyboard_video_debug_block_request_log_input(request))
        log_success = bool(final_video_request_log.get("success"))
        log_error = str(final_video_request_log.get("error") or "").strip()
        if not log_success:
            raise RuntimeError(f"视频阻断提示词日志写入失败：{log_error or '未知错误'}")
        return {
            "media": None,
            "preview": None,
            "status": "blocked",
            "source": "model-video-debug-blocked",
            "model": request["model"].get("id"),
            "provider": request["providerId"],
            "summary": "视频阻断已开启：已写入最终提示词，未请求供应商 API。",
            "debug": {
                "providerId": request["providerId"],
                "modelName": request["modelName"],
                "endpoint": request["endpoint"],
                "durationSeconds": request["durationSeconds"],
                "finalPromptChars": len(str(request.get("prompt") or "")),
                "debugBlockLog": copy.deepcopy(final_video_request_log),
            },
        }

    response = generate_video_media(
        request["provider"],
        request["providerId"],
        request["baseUrl"],
        request["modelName"],
        request["prompt"],
        request["referenceImage"],
        reference_images=request.get("referenceImages") if isinstance(request.get("referenceImages"), list) else None,
        reference_videos=request.get("referenceVideos") if isinstance(request.get("referenceVideos"), list) else None,
        **({"reference_audios": request["referenceAudios"]} if request.get("referenceAudios") else {}),
        **({"replacement_subject": request["replacementSubject"]} if request.get("replacementSubject") else {}),
        strategy=str(request.get("providerRequest", {}).get("strategy") or ""),
        size=request["size"],
        aspect_ratio=request["aspectRatio"],
        resolution=request["resolution"],
        duration_seconds=request["durationSeconds"],
        generate_audio=request["generateAudio"],
        endpoint=request["endpoint"],
        image_input_limits=request.get("imageInputLimits") if isinstance(request.get("imageInputLimits"), dict) else None,
        on_request_prepared=log_video_request,
    )
    raw = response.raw
    debug = {**(response.debug or {}), "providerRequest": request.get("providerRequest") or {}}
    if final_video_request_log.get("success"):
        debug["modelRequestLog"] = model_request_log_reference(
            final_video_request_log,
            phase="direct-video-generation",
        )
    if final_video_request_log_errors:
        existing_errors = debug.get("modelRequestLogErrors") if isinstance(debug.get("modelRequestLogErrors"), list) else []
        debug["modelRequestLogErrors"] = [
            *copy.deepcopy(existing_errors),
            *copy.deepcopy(final_video_request_log_errors),
        ]
    if raw:
        media_id = f"video-{episode_id}-{uuid.uuid4().hex[:8]}"
        file_meta = _save_project_media_file(
            project_id,
            raw,
            media_id=media_id,
            suffix=".mp4",
            subdir="videos",
            storage_scope="episode_results",
            episode_id=episode_id,
        )
        media = {
            **file_meta,
            "kind": "video",
            "mimeType": "video/mp4",
        }
        return {
            "media": media,
            "source": "model-video-generation",
            "model": request["model"].get("id"),
            "provider": request["providerId"],
            "debug": debug,
        }
    return {
        "media": None,
        "preview": None,
        "status": response.status or "processing",
        "source": "model-video-job",
        "model": request["model"].get("id"),
        "provider": request["providerId"],
        "debug": debug,
    }
