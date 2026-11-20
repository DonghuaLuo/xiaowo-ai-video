# -*- coding: utf-8 -*-
"""预检与生成共用的模型配置合并、能力约束和视频参数规则。"""
from __future__ import annotations
from .canvas_ownership import VIDEO_TASK_NODE_TYPES
from utils.video_task_types import (
    CHARACTER_REPLACE_TASK, CHARACTER_REPLACE_STRATEGY, model_supports_video_task,
    standalone_video_input_mode, standalone_video_strategy,
)

import copy
import re
from .catalogs import (
    DEFAULT_MODEL_CAPABILITIES,
    LEGACY_IMAGE_RESOLUTION_TO_TIER,
    _normalize_resolution_label,
)
from .generation_input_context import (
    _asset_refs_resolved_by_input_links,
    _workflow_generation_config_source_node,
    _workflow_node_by_id,
    _workflow_node_data_dict,
    _workflow_route_by_id,
    _workflow_video_task_scope_for_config,
)
from .generation_reference_validation import (
    WORKFLOW_NODE_SLOT_SCHEMA,
    _preflight_resolved_reference_image_count,
)
from .model_provider_config import _project_model_config
from .planning_contract import (
    _normalize_video_generation_strategy,
)
from .provider_models import (
    _find_model_by_id_or_label,
    _model_capabilities_with_provider_models,
    _model_duration_options,
    _model_options_from_capabilities,
    _resolution_matches,
    _storyboard_size_prompt_only_for_gpt_relay,
    _validated_video_resolution,
)
from .reference_utils import (
    asset_reference_ids_from_generation_sources as _asset_reference_ids_from_generation_sources,
    merge_reference_ids as _merge_reference_ids,
)
from .splitting_templates import (
    _string_list,
)
from .store_core import (
    _deep_merge,
)
from .video_input_plan import (
    normalize_video_input_mode as _shared_normalize_video_input_mode,
)
from typing import (
    Any,
)
from utils.media_backends import (
    video_prompt_char_limit,
)


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


def _media_generation_config(config: Any, media_type: str) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    media_config = config.get(media_type)
    if isinstance(media_config, dict):
        nested = copy.deepcopy(media_config)
        top_level = {
            key: copy.deepcopy(value)
            for key, value in config.items()
            if key not in {"image", "video"} and value is not None
        }
        return _deep_merge(top_level, nested)
    return copy.deepcopy(config)


def _generation_media_type_from_node(node_type: str, requested: str) -> str:
    media_type = requested.strip().lower()
    if media_type in {"image", "video"}:
        return media_type
    if node_type in {"prompt.storyboard", "storyboard.card", "storyboard.image"}:
        return "image"
    return "video"


def _default_generation_config(
    model_config: dict[str, Any],
    capabilities: dict[str, Any],
    media_type: str,
    strategy: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if media_type == "video":
        strategy = _normalize_video_generation_strategy(strategy)
    if media_type == "image":
        image_section = model_config.get("image") if isinstance(model_config.get("image"), dict) else {}
        model_id = str(image_section.get("model_id") or "").strip()
        model = _find_model_by_id_or_label(model_id, "image", capabilities)
        if model:
            model_id = str(model.get("id") or model_id)
        resolution = _resolution_display_label(
            image_section.get("storyboard_resolution")
            or image_section.get("asset_resolution")
            or (model or {}).get("default_resolution"),
            "image",
        )
        return {
            "mediaType": "image",
            "modelId": model_id,
            "resolution": resolution,
            "outputFormat": image_section.get("image_output_format") or "auto",
            "referenceMode": "image_reference",
        }, model

    video_section = model_config.get("video") if isinstance(model_config.get("video"), dict) else {}
    model_id = str(video_section.get("model_id") or "").strip()
    model = _find_model_by_id_or_label(model_id, "video", capabilities)
    if strategy == CHARACTER_REPLACE_STRATEGY:
        model = next((row for row in capabilities.get("video", [])
                      if isinstance(row, dict) and row.get("available", True)
                      and model_supports_video_task(row, CHARACTER_REPLACE_TASK)), None)
        model_id = str((model or {}).get("id") or "")
    if model:
        model_id = str(model.get("id") or model_id)
    if strategy == CHARACTER_REPLACE_STRATEGY:
        reference_mode = "character_replace"
    elif strategy == "text_to_video_draft":
        reference_mode = "text_to_video_draft"
    elif strategy == "native_keyframe_video":
        reference_mode = "native_keyframe"
    elif strategy == "image_reference_video":
        reference_mode = "image_reference"
    elif strategy == "storyboard_multi_shot":
        reference_mode = "storyboard_reference_image"
    else:
        reference_mode = "storyboard_reference_image"
    return {
        "mediaType": "video",
        "modelId": model_id,
        "resolution": video_section.get("resolution"),
        "durationSeconds": video_section.get("duration_seconds")
        or video_section.get("durationSeconds")
        or (model or {}).get("default_duration")
        or (model or {}).get("defaultDuration"),
        "referenceMode": reference_mode,
    }, model


def _numeric_option_list(value: Any) -> list[int | float]:
    raw_values = value if isinstance(value, list) else [value]
    options: list[int | float] = []
    for item in raw_values:
        if item is None:
            continue
        for part in str(item).replace("fps", "").replace("FPS", "").split(","):
            text = part.strip()
            if not text:
                continue
            try:
                parsed = float(text)
            except ValueError:
                continue
            if parsed <= 0:
                continue
            value_to_store: int | float = int(parsed) if parsed.is_integer() else parsed
            if value_to_store not in options:
                options.append(value_to_store)
    return options


def _workflow_resolution_is_aspect_ratio(value: Any) -> bool:
    return bool(re.fullmatch(r"\s*\d+\s*:\s*\d+\s*", str(value or "")))


def _resolution_display_label(value: Any, media_type: str) -> str:
    normalized = _normalize_resolution_label(value)
    if not normalized:
        return ""
    if media_type == "image":
        return LEGACY_IMAGE_RESOLUTION_TO_TIER.get(
            normalized.replace("*", "x").replace("×", "x"),
            normalized,
        )
    return normalized


def _workflow_resolution_options(values: list[str], media_type: str) -> list[str]:
    options: list[str] = []
    seen: set[str] = set()
    for value in values:
        display = _resolution_display_label(value, media_type)
        if not display or _workflow_resolution_is_aspect_ratio(display):
            continue
        key = display.lower()
        if key in seen:
            continue
        seen.add(key)
        options.append(display)
    return options


def _workflow_resolution_default(
    value: Any,
    options: list[str],
    media_type: str,
) -> str:
    display = _resolution_display_label(value, media_type)
    if display:
        for option in options:
            if option.lower() == display.lower():
                return option
    return options[0] if options else display


def _normalized_model_capabilities(model: dict[str, Any], supports: set[str]) -> dict[str, Any]:
    max_reference_images = int(model.get("max_reference_images") or 0)
    media_type = str(model.get("type") or model.get("media_type") or "").strip().lower()
    resolutions = _string_list(model.get("resolutions"))
    resolution_options = _workflow_resolution_options(resolutions, media_type)
    durations = model.get("durations") if isinstance(model.get("durations"), list) else []
    fps_options = _numeric_option_list(
        model.get("fps")
        or model.get("frameRates")
        or model.get("frame_rates")
        or model.get("frame_rate")
    )
    aspect_ratios = _string_list(
        model.get("aspect_ratios")
        or model.get("aspectRatios")
        or model.get("ratios")
    )
    text_to_video_markers = {"text_to_video_draft", "text_to_video", "t2v"}
    multi_reference_markers = {
        "multi_reference_video",
        "multi_reference",
        "storyboard_reference_image",
    }
    supports_storyboard_reference = bool(
        model.get("supports_storyboard_reference_image") is True
        or model.get("supportsStoryboardReferenceImage") is True
        or supports.intersection({"storyboard_reference_image", "storyboard_grid_reference"})
    )
    supports_multi_reference = bool(
        model.get("supports_multi_reference_images") is True
        or model.get("supportsMultiReferenceImages") is True
        or supports.intersection(multi_reference_markers)
    )
    supports_flags = {
        "multiReferenceVideo": bool(supports_multi_reference and max_reference_images >= 2),
        "storyboardReferenceImage": supports_storyboard_reference,
        "textToVideo": bool(supports.intersection(text_to_video_markers)),
        "singleImageToVideo": bool("single_image_to_video" in supports),
    }
    input_modes: list[str] = []
    adapter = model.get("adapter_capabilities") or {}
    reference_visual = adapter.get("visual_inputs")
    supports_reference_mode = bool(reference_visual.get("modes")) if isinstance(reference_visual, dict) else (
        supports_flags["storyboardReferenceImage"]
        or supports_flags["multiReferenceVideo"]
        or supports_flags["singleImageToVideo"]
    )
    if supports_reference_mode:
        input_modes.extend(["storyboard_reference", "storyboard_reference_image"])
    if supports_flags["textToVideo"]:
        input_modes.append("text_to_video_draft")
    return {
        "inputModes": list(dict.fromkeys(input_modes)),
        "supports": {
            **supports_flags,
        },
        "limits": {
            "maxReferenceImages": max_reference_images,
            "durations": durations,
            "resolutions": resolution_options or resolutions,
            "fps": fps_options,
            "aspectRatios": aspect_ratios,
        },
        "rawSupports": sorted(supports),
    }


def _nearest_declared_duration_seconds(value: int, durations: list[int]) -> int:
    declared = _video_task_card_allowed_duration_values(durations)
    if not declared:
        return value
    return min(declared, key=lambda item: (abs(item - value), item))


def resolve_generation_config(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
    *,
    workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .workflow_projection import get_canvas_workflow_projection
    if not episode_id:
        raise ValueError("缺少 episodeId")
    payload = payload if isinstance(payload, dict) else {}
    workflow = workflow if isinstance(workflow, dict) else get_canvas_workflow_projection(project_id, episode_id)
    route_id = str(payload.get("routeId") or payload.get("route_id") or "").strip()
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    node = _workflow_node_by_id(workflow, node_id) if node_id else {}
    node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
    if not route_id:
        route_id = str(node.get("routeId") or node_data.get("routeId") or "").strip()
    route = _workflow_route_by_id(workflow, route_id) if route_id else {}
    node_type = str(payload.get("nodeType") or payload.get("node_type") or node.get("type") or "").strip()
    media_type = _generation_media_type_from_node(
        node_type,
        str(payload.get("mediaType") or payload.get("media_type") or ""),
    )
    config_node = _workflow_generation_config_source_node(workflow, node, media_type)
    config_node_data = _workflow_node_data_dict(config_node)
    input_node = config_node if node_type == "video.result" else node
    input_node_type = str(input_node.get("type") or node_type)
    if node_type == "video.result":
        node_data = config_node_data
    video_task_scope = (
        _workflow_video_task_scope_for_config(payload, input_node)
        if media_type == "video" and input_node_type in VIDEO_TASK_NODE_TYPES
        else ""
    )
    strategy = str(
        payload.get("strategy")
        or config_node.get("strategy")
        or config_node_data.get("strategy")
        or route.get("strategy")
        or (
            "native_keyframe_video" if input_node_type == "video.keyframe" else "image_reference_video"
            if media_type == "video" and video_task_scope == "standalone"
            else "storyboard_multi_shot"
            if media_type == "video"
            else "image_reference"
        )
    ).strip()
    if media_type == "video":
        strategy = _normalize_video_generation_strategy(strategy)
        if video_task_scope == "standalone":
            strategy = standalone_video_strategy(input_node_type)

    _, capabilities, model_config = _project_model_config(project_id)
    resolved_config, model = _default_generation_config(model_config, capabilities, media_type, strategy)
    payload_generation_config = (
        payload.get("generationConfig") or payload.get("generation_config") or payload.get("config")
        if not node
        else None
    )
    for source in (route.get("generationConfig"), config_node_data.get("generationConfig"), payload_generation_config):
        resolved_config = _deep_merge(resolved_config, _media_generation_config(source, media_type))
    if media_type == "video":
        resolved_config["strategy"] = strategy
        if video_task_scope:
            resolved_config["videoTaskScope"] = video_task_scope
        raw_reference_mode = resolved_config.get("referenceMode") or resolved_config.get("inputMode")
        normalized_reference_mode = _shared_normalize_video_input_mode(raw_reference_mode)
        if strategy == "text_to_video_draft":
            resolved_config["referenceMode"] = "text_to_video_draft"
            resolved_config["inputMode"] = "text_to_video_draft"
            resolved_config["videoInputMode"] = "text_to_video_draft"
        elif video_task_scope == "standalone":
            input_mode = standalone_video_input_mode(input_node_type)
            resolved_config["referenceMode"] = input_mode
            resolved_config["inputMode"] = input_mode
            resolved_config["videoInputMode"] = input_mode
        elif normalized_reference_mode in {"", "storyboard_reference"} or strategy == "storyboard_multi_shot":
            resolved_config["referenceMode"] = "storyboard_reference_image"
            resolved_config["inputMode"] = "storyboard_reference_image"
            resolved_config["videoInputMode"] = "storyboard_reference"

    model_id = str(resolved_config.get("modelId") or resolved_config.get("model_id") or "").strip()
    if model_id:
        resolved_model = _find_model_by_id_or_label(model_id, media_type, capabilities)
        if resolved_model:
            model = resolved_model
            model_id = str(resolved_model.get("id") or model_id).strip()
        elif not model or model.get("id") != model_id:
            model = None
    if model_id:
        resolved_config["modelId"] = model_id
    if workflow and str(input_node.get("id") or "") and input_node_type in {"director.board", "storyboard.card", *VIDEO_TASK_NODE_TYPES}:
        from .workflow_input_resolution import _resolve_workflow_node_inputs_from_workflow
        current_inputs = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, str(input_node["id"]))
        from .video_task_card_references import video_task_card_current_reference_snapshot
        current_references = video_task_card_current_reference_snapshot(
            project_id, episode_id, workflow, str(input_node["id"]), input_snapshot=current_inputs,
            for_generation=input_node_type in VIDEO_TASK_NODE_TYPES,
        )
        node_data = {**node_data, "inputLinks": current_references["inputLinksSnapshot"], **{
            key: current_references[key]
            for key in ("referenceMediaIds", "assetRefs", "assetRefsResolvedByInputLinks")
        }}
        payload = {**payload, "referenceMediaIds": current_references["referenceMediaIds"], "reference_media_ids": []}
    asset_refs_resolved_by_links = _asset_refs_resolved_by_input_links(
        payload,
        node_data,
        route,
        resolved_config,
    )
    if asset_refs_resolved_by_links:
        resolved_config["assetRefsResolvedByInputLinks"] = True
        resolved_config.pop("referenceMediaIds", None)
        resolved_config.pop("reference_media_ids", None)
        resolved_config.pop("explicitReferenceMediaIds", None)
        resolved_config.pop("explicit_reference_media_ids", None)
        resolved_config.pop("assetReferenceMediaIds", None)
        resolved_config.pop("asset_reference_media_ids", None)
    if asset_refs_resolved_by_links:
        reference_ids = (
            payload.get("referenceMediaIds")
            or payload.get("reference_media_ids")
            or node_data.get("referenceMediaIds")
            or []
        )
    else:
        reference_ids = (
            resolved_config.get("referenceMediaIds")
            or payload.get("referenceMediaIds")
            or payload.get("reference_media_ids")
            or node_data.get("referenceMediaIds")
            or []
        )
    explicit_reference_media_ids = _string_list(reference_ids)
    asset_reference_media_ids = (
        []
        if asset_refs_resolved_by_links
        else _asset_reference_ids_from_generation_sources(
            payload,
            node_data,
            route,
            resolved_config,
        )
    )
    if media_type == "video" and strategy == "text_to_video_draft":
        asset_reference_media_ids = []
    reference_media_ids = _merge_reference_ids(explicit_reference_media_ids, asset_reference_media_ids)
    if explicit_reference_media_ids:
        resolved_config["explicitReferenceMediaIds"] = explicit_reference_media_ids
    if asset_reference_media_ids:
        resolved_config["assetReferenceMediaIds"] = asset_reference_media_ids
    if reference_media_ids:
        resolved_config["referenceMediaIds"] = reference_media_ids

    resolved_reference_image_count = 0

    warnings: list[str] = []
    blocking: list[str] = []
    if media_type == "video" and node_type in VIDEO_TASK_NODE_TYPES and not video_task_scope:
        blocking.append("视频生成缺少作用域标识，请重新创建任务卡")
    if not model_id:
        blocking.append(f"{media_type} 生成缺少模型配置")
    elif not model:
        blocking.append(f"未找到模型能力声明：{model_id}")

    if isinstance(model, dict):
        if media_type == "video":
            if not model_supports_video_task(model, input_node_type):
                blocking.append("当前模型不支持此任务类型，请在卡片中选择匹配的视频工作流")
            adapter = model.get("adapter_capabilities") or {}
            visual_key = "keyframe_visual_inputs" if input_node_type == "video.keyframe" else "visual_inputs"
            if visual_key in adapter and not (adapter[visual_key] or {}).get("modes"):
                blocking.append("当前模型不支持此视频生成的生成方式，请切换模型或任务卡类型")
        resolutions = _string_list(model.get("resolutions"))
        resolution = str(resolved_config.get("resolution") or "").strip()
        if media_type == "image":
            resolution_options = _workflow_resolution_options(resolutions, "image")
            requested_resolution = _resolution_display_label(
                resolution or resolved_config.get("size"),
                "image",
            )
            if _workflow_resolution_is_aspect_ratio(requested_resolution):
                requested_resolution = ""
            if requested_resolution and resolution_options:
                for option in resolution_options:
                    if option.lower() == requested_resolution.lower():
                        requested_resolution = option
                        break
            if not requested_resolution:
                requested_resolution = _workflow_resolution_default(
                    model.get("default_resolution"),
                    resolution_options,
                    "image",
                )
            if requested_resolution:
                resolved_config["resolution"] = requested_resolution
                resolved_config["size"] = requested_resolution
                resolution = requested_resolution
            if (
                node_type in {"prompt.storyboard", "storyboard.card", "storyboard.image"}
                and _storyboard_size_prompt_only_for_gpt_relay(model)
            ):
                for key in ("resolution", "size", "storyboardResolution", "storyboard_resolution"):
                    resolved_config.pop(key, None)
                resolution = ""
        if media_type == "video":
            try:
                resolution = _validated_video_resolution(model, resolution)
                resolved_config["resolution"] = resolution
            except ValueError as exc:
                blocking.append(str(exc))
        elif resolution and resolutions and not any(
            _resolution_matches(resolution, item)
            or _resolution_matches(item, resolution)
            for item in resolutions
        ):
            warnings.append(f"分辨率 {resolution} 不在模型 {model_id} 的声明范围内：{', '.join(resolutions)}")

        supports = {str(item).strip().lower() for item in model.get("supports", []) if str(item).strip()}
        raw_max_reference_images = (
            model.get("max_reference_images")
            if model.get("max_reference_images") is not None
            else model.get("maxReferenceImages")
        )
        has_reference_image_limit = raw_max_reference_images is not None
        try:
            max_reference_images = int(raw_max_reference_images) if has_reference_image_limit else 0
        except (TypeError, ValueError):
            max_reference_images = 0
            has_reference_image_limit = False
        if reference_media_ids:
            resolved_reference_image_count = _preflight_resolved_reference_image_count(
                project_id,
                episode_id,
                reference_media_ids,
                workflow=workflow,
                allow_asset_library_lookup=not asset_refs_resolved_by_links,
                input_links=node_data.get("inputLinks") if media_type == "video" else None,
            )
            resolved_config["resolvedReferenceImageCount"] = resolved_reference_image_count
        provider_key = str(
            model.get("provider_preset_id")
            or model.get("providerPresetId")
            or model.get("provider_id")
            or ""
        ).strip()
        image_model_name = str(model.get("id") or model_id or "").split(":")[-1].lower()
        if (
            media_type == "image"
            and provider_key == "dashscope"
            and image_model_name.startswith("wan")
            and str(resolution or "").strip().upper() == "4K"
        ):
            if "pro" not in image_model_name:
                blocking.append(f"DashScope 模型 {model_id} 不支持 4K 图片输出，请选择 1K/2K 或切换 Wan Pro。")
            elif resolved_reference_image_count:
                blocking.append("DashScope Wan Pro 仅支持文生图 4K；当前任务包含参考图，请选择 1K/2K 或移除参考图后再生成。")
        if media_type == "video" and "native_audio" in supports:
            audio_config = copy.deepcopy(resolved_config.get("audio")) if isinstance(resolved_config.get("audio"), dict) else {}
            audio_config["mode"] = "native_audio"
            audio_config["effectiveMode"] = "native_audio"
            resolved_config["audio"] = audio_config
        model_capabilities = _normalized_model_capabilities(model, supports)
        resolved_config["modelCapabilities"] = model_capabilities
        if media_type == "video":
            from utils.frame_references import is_frame_image, select_frame_transport
            from .workflow_input_resolution import workflow_reference_video_input_links
            frame_links = [row for row in node_data.get("inputLinks", []) if is_frame_image(row)]
            if frame_links or input_node_type == "video.keyframe":
                typed_references = frame_links + [{} for _ in range(max(0, resolved_reference_image_count - len(frame_links)))]
                reference_video_count = len(workflow_reference_video_input_links(
                    project_id, episode_id, workflow, node_data.get("inputLinks", []),
                ))
                try:
                    frame_transport = select_frame_transport(
                        typed_references, model,
                        reference_video_count=reference_video_count,
                        native_required=input_node_type == "video.keyframe",
                    )
                    max_reference_images += len(frame_transport["nativeRoles"])
                    resolved_config["frameTransportMode"] = frame_transport["mode"]
                except ValueError as error:
                    blocking.append(str(error))
        if (
            resolved_reference_image_count
            and has_reference_image_limit
            and resolved_reference_image_count > max_reference_images
        ):
            blocking.append(
                f"参考图数量 {resolved_reference_image_count} 超过模型上限 {max_reference_images}，请减少参考图或切换支持更多参考图的模型后再生成。"
            )

        if media_type == "video":
            support_flags = model_capabilities.get("supports", {})
            try:
                duration_seconds = int(resolved_config.get("durationSeconds") or 0)
            except (TypeError, ValueError):
                duration_seconds = 0
            durations = _video_task_card_allowed_duration_values(
                _model_duration_options(model, resolution, native_keyframe=True)
                if input_node_type == "video.keyframe" else _model_duration_options(model, resolution)
            )
            if strategy == "storyboard_multi_shot" and not durations:
                blocking.append(
                    f"模型 {model_id} 未声明可用视频时长；请选择声明时长档位的模型，"
                    "不能把未知能力视为支持任意时长。"
                )
            if duration_seconds:
                if durations:
                    if strategy == "storyboard_multi_shot" and duration_seconds not in durations:
                        blocking.append(
                            f"当前分镜视频卡选择 {duration_seconds} 秒，模型 {model_id} 仅支持 "
                            + "、".join(f"{value} 秒" for value in durations)
                            + "；请更换模型或由用户选择受支持的卡片时长，不自动改写已定镜头和分组。"
                        )
                    elif strategy != "storyboard_multi_shot":
                        duration_seconds = _nearest_declared_duration_seconds(duration_seconds, durations)
                resolved_config["durationSeconds"] = duration_seconds
            try:
                fps_value = float(
                    resolved_config.get("fps")
                    or resolved_config.get("frameRate")
                    or resolved_config.get("frame_rate")
                    or 0
                )
            except (TypeError, ValueError):
                fps_value = 0
            fps_options = (
                model_capabilities.get("limits", {}).get("fps")
                if isinstance(model_capabilities.get("limits"), dict)
                else []
            )
            if fps_value:
                resolved_config["fps"] = int(fps_value) if fps_value.is_integer() else fps_value
                normalized_fps_options = {
                    float(item) for item in fps_options if isinstance(item, (int, float))
                }
                if normalized_fps_options and fps_value not in normalized_fps_options:
                    allowed_fps = ", ".join(
                        f"{item:g}" for item in sorted(normalized_fps_options)
                    )
                    warnings.append(
                        f"帧率 {resolved_config['fps']}fps 不在模型 {model_id} 的声明范围内：{allowed_fps}fps"
                    )
            if strategy == "text_to_video_draft" and not support_flags.get("textToVideo"):
                blocking.append(f"模型 {model_id} 未声明文生视频草稿能力")
            assigned_shot_nos = node_data.get("shotNos") if isinstance(node_data.get("shotNos"), list) else []
            storyboard_reference_supported = (
                support_flags.get("storyboardReferenceImage")
                if len(assigned_shot_nos) > 1
                else support_flags.get("storyboardReferenceImage") or support_flags.get("singleImageToVideo")
            )
            if strategy == "storyboard_multi_shot" and resolved_reference_image_count and not storyboard_reference_supported:
                if support_flags.get("textToVideo"):
                    blocking.append(
                        f"模型 {model_id} 未声明按当前分镜图画格顺序生成视频的能力；"
                        "请切换已证实支持 storyboard_reference_image 的视频模型，或把路线改为 text_to_video_draft。"
                    )
                else:
                    blocking.append(f"模型 {model_id} 未声明按多画格分镜图镜序生成视频的能力；普通单图生视频能力不足以证明可用")
            if strategy == "storyboard_multi_shot" and assigned_shot_nos:
                chain_id = str(config_node.get("workChainId") or config_node_data.get("workChainId") or "")
                director = next((item for item in workflow.get("nodes") or []
                                 if isinstance(item, dict) and item.get("type") == "director.board"
                                 and chain_id and str(item.get("workChainId") or (item.get("data") or {}).get("workChainId") or "") == chain_id), None)
                formal_shots = (director.get("data") or {}).get("directorPlanShots") if isinstance(director, dict) else None
                if isinstance(formal_shots, list) and any(
                    isinstance(number, int) and 1 <= number <= len(formal_shots)
                    and isinstance(formal_shots[number - 1], dict)
                    and any(isinstance(event, dict) and event.get("kind") == "voice"
                            for event in (formal_shots[number - 1].get("soundEvents") or []))
                    for number in assigned_shot_nos
                ) and not (model.get("audio") is True or model.get("supports_native_audio") is True
                           or model.get("supportsNativeAudio") is True or "native_audio" in (model.get("supports") or [])):
                    warnings.append(f"模型 {model_id} 未声明原生人声生成能力；本镜头组含对白或其他人声，须另行安排配音制作")
            if (
                video_task_scope in {"work_chain", "standalone"} and input_node_type != "video.keyframe"
                and not resolved_reference_image_count
                and not workflow_reference_video_input_links(project_id, episode_id, workflow, node_data.get("inputLinks", []))
                and not support_flags.get("textToVideo")
            ):
                blocking.append(f"模型 {model_id} 未声明纯文本视频能力，请关联可用参考图或切换模型")

    return {
        "success": not blocking,
        "projectId": project_id,
        "episodeId": episode_id,
        "routeId": route_id,
        "nodeId": node_id,
        "mediaType": media_type,
        "strategy": strategy,
        "resolvedConfig": resolved_config,
        "route": copy.deepcopy(route),
        "node": copy.deepcopy(node),
        "model": copy.deepcopy(model) if isinstance(model, dict) else None,
        "warnings": warnings,
        "blockingIssues": blocking,
        "qualityGates": {
            "blockingIssueCount": len(blocking),
            "warningCount": len(warnings),
        },
    }


def _video_task_card_final_prompt_policy() -> dict[str, Any]:
    return {
        "promptMode": "explicit_final_provider_prompt_from_source_adapter",
        "promptBudgetPolicy": "visible_provider_prompt_plus_hidden_asset_references",
        "promptBudgetGuidance": (
            "视频生成保存当前视频模型最终提交使用的正文提示词；"
            "该正文由用户显式触发生成，工作链来源按分镜脚本镜头计划请求模型生成中间数据后，"
            "由本地按供应商路线组装；独立视频来源直接使用任务卡内的用户输入；"
            "提交时在正文前组装当前可用图片资产引用说明及统一画面约束；有参考图时约束辅助标记，无参考图时仅约束字幕和剧情内文字；不改写任务卡正文。"
        ),
    }


def _video_task_card_final_prompt_profile(model: dict[str, Any]) -> str:
    for key in (
        "final_prompt_profile",
        "finalPromptProfile",
        "videoPromptProfile",
        "finalVideoPromptProfile",
    ):
        value = str(model.get(key) or "").strip()
        if value:
            return value
    for nested_key in (
        "adapter_capabilities",
        "adapterCapabilities",
        "metadata",
        "official_capabilities",
        "officialCapabilities",
    ):
        nested = model.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key in (
            "final_prompt_profile",
            "finalPromptProfile",
            "videoPromptProfile",
            "finalVideoPromptProfile",
        ):
            value = str(nested.get(key) or "").strip()
            if value:
                return value
    return ""


def _video_task_card_prompt_timing_style(model: dict[str, Any]) -> str:
    for key in ("prompt_timing_style", "promptTimingStyle"):
        value = str(model.get(key) or "").strip()
        if value:
            return value
    for nested_key in (
        "adapter_capabilities",
        "adapterCapabilities",
        "metadata",
        "official_capabilities",
        "officialCapabilities",
    ):
        nested = model.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key in ("prompt_timing_style", "promptTimingStyle"):
            value = str(nested.get(key) or "").strip()
            if value:
                return value
    model_id = str(
        model.get("id")
        or model.get("model_id")
        or model.get("modelId")
        or model.get("name")
        or ""
    ).casefold()
    if "doubao-seedance-2-5" in model_id:
        return "integer_second_timeline"
    if "doubao-seedance-2-0" in model_id:
        return "shot_sequence"
    return ""


def _video_task_card_raw_video_defaults(global_config: dict[str, Any]) -> dict[str, Any]:
    raw_config = global_config.get("model_config") if isinstance(global_config.get("model_config"), dict) else {}
    return copy.deepcopy(raw_config.get("video") if isinstance(raw_config.get("video"), dict) else {})


def _video_task_card_target_model_context(
    project_id: str,
    data: dict[str, Any],
    payload: dict[str, Any],
    *,
    include_timing: bool = True,
    model_context: tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _global_config, capabilities, model_config = model_context if model_context is not None else _project_model_config(project_id)
    video_defaults = model_config.get("video") if isinstance(model_config.get("video"), dict) else {}
    raw_video_defaults = _video_task_card_raw_video_defaults(_global_config)
    stored_config = data.get("generationConfig") if isinstance(data.get("generationConfig"), dict) else {}
    request_config = payload.get("generationConfig") if isinstance(payload.get("generationConfig"), dict) else {}
    resolved_config = payload.get("resolvedConfig") if isinstance(payload.get("resolvedConfig"), dict) else {}
    if stored_config.get("strategy") == CHARACTER_REPLACE_STRATEGY:
        replacement_defaults, _ = _default_generation_config(model_config, capabilities, "video", CHARACTER_REPLACE_STRATEGY)
        video_defaults = {"model_id": replacement_defaults.get("modelId"), "resolution": "768p", "duration_seconds": 10}
        raw_video_defaults = video_defaults
    full_capabilities = (
        _global_config.get("model_capabilities")
        if isinstance(_global_config.get("model_capabilities"), dict)
        else {}
    )
    configured_provider_capabilities = full_capabilities if model_context is not None else _model_capabilities_with_provider_models(
        full_capabilities if isinstance(full_capabilities, dict) and full_capabilities else DEFAULT_MODEL_CAPABILITIES,
        _global_config.get("providers") if isinstance(_global_config.get("providers"), list) else [],
    )
    def config_model_id(config: dict[str, Any]) -> str:
        return str(
            config.get("modelId")
            or config.get("model_id")
            or config.get("model")
            or ""
        ).strip()

    def is_video_model_config(config: dict[str, Any], candidate_id: str) -> bool:
        if config is video_defaults or config is raw_video_defaults:
            return True
        purpose = str(config.get("purpose") or config.get("taskType") or config.get("task_type") or "").strip().casefold()
        if purpose and "video" not in purpose:
            return False
        if _find_model_by_id_or_label(candidate_id, "video", capabilities):
            return True
        if _find_model_by_id_or_label(candidate_id, "video", full_capabilities):
            return True
        if _find_model_by_id_or_label(candidate_id, "video", configured_provider_capabilities):
            return True
        if _find_model_by_id_or_label(candidate_id, "image", capabilities):
            return False
        if _find_model_by_id_or_label(candidate_id, "image", full_capabilities):
            return False
        if _find_model_by_id_or_label(candidate_id, "image", configured_provider_capabilities):
            return False
        return not purpose

    model_id = ""
    model: dict[str, Any] | None = None
    selected_model_config: dict[str, Any] = {}
    fallback_model_id = ""
    fallback_model_config: dict[str, Any] = {}
    for config in (resolved_config, request_config, stored_config, video_defaults, raw_video_defaults):
        if not isinstance(config, dict):
            continue
        candidate_id = config_model_id(config)
        if not candidate_id:
            continue
        if not is_video_model_config(config, candidate_id):
            continue
        if not fallback_model_id:
            fallback_model_id = candidate_id
            fallback_model_config = config
        candidate_model = _find_model_by_id_or_label(candidate_id, "video", capabilities)
        if not candidate_model:
            candidate_model = _find_model_by_id_or_label(candidate_id, "video", full_capabilities)
        if not candidate_model:
            candidate_model = _find_model_by_id_or_label(candidate_id, "video", configured_provider_capabilities)
        if not candidate_model:
            continue
        model_id = candidate_id
        model = candidate_model
        selected_model_config = config
        break
    if not model_id and fallback_model_id:
        model_id = fallback_model_id
        selected_model_config = fallback_model_config
    model = model if isinstance(model, dict) else {}
    format_context = {
        "modelId": str(model.get("id") or model_id),
        "api_model_id": str(model.get("api_model_id") or ""),
        "endpoint": str(model.get("endpoint") or ""),
        "label": str(model.get("label") or model.get("name") or model_id),
        "providerId": str(
            model.get("provider_preset_id") or model.get("providerPresetId")
            or model.get("provider_id") or model.get("providerId") or ""
        ).strip(),
        "maxReferenceImages": int(model.get("max_reference_images") or 0),
        "finalPromptProfile": _video_task_card_final_prompt_profile(model),
    }
    if not include_timing:
        return format_context

    def config_for_video(config: dict[str, Any]) -> dict[str, Any]:
        return config if selected_model_config is config or not config_model_id(config) else {}

    resolved_config_for_video = config_for_video(resolved_config)
    request_config_for_video = config_for_video(request_config)
    stored_config_for_video = config_for_video(stored_config)
    selected_resolution = str(
        resolved_config_for_video.get("resolution")
        or request_config_for_video.get("resolution")
        or stored_config_for_video.get("resolution")
        or video_defaults.get("resolution")
        or raw_video_defaults.get("resolution")
        or model.get("default_resolution")
        or ""
    ).strip()
    task_card = data.get("videoTaskCard") if isinstance(data.get("videoTaskCard"), dict) else {}
    boundary_plan = task_card.get("boundaryPlan") if isinstance(task_card.get("boundaryPlan"), dict) else {}
    durations = _video_task_card_allowed_duration_values(
        _model_duration_options(
            model, selected_resolution,
            native_keyframe=(
                data.get("eyebrow") == "video.keyframe"
                or boundary_plan.get("mode") == "native_keyframe"
                or any(
                    config.get("strategy") == "native_keyframe_video"
                    or config.get("videoInputMode") == "native_keyframe"
                    or config.get("inputMode") == "native_keyframe"
                    for config in (resolved_config_for_video, request_config_for_video, stored_config_for_video)
                )
            ),
        )
    )
    resolutions = [str(item).strip() for item in model.get("resolutions", []) if str(item).strip()]
    supports = [str(item).strip() for item in model.get("supports", []) if str(item).strip()]
    provider_id = str(
        model.get("provider_preset_id")
        or model.get("providerPresetId")
        or model.get("provider_id")
        or model.get("providerId")
        or ""
    ).strip()
    support_set = {item.casefold() for item in supports}
    preferred_duration = _video_task_card_duration(
        resolved_config_for_video.get("durationSeconds")
        or resolved_config_for_video.get("duration")
        or request_config_for_video.get("durationSeconds")
        or request_config_for_video.get("duration")
        or stored_config_for_video.get("durationSeconds")
        or stored_config_for_video.get("duration")
        or video_defaults.get("duration_seconds")
        or video_defaults.get("durationSeconds")
        or video_defaults.get("duration")
        or raw_video_defaults.get("duration_seconds")
        or raw_video_defaults.get("durationSeconds")
        or raw_video_defaults.get("duration")
        or 8,
        8,
        durations,
    )
    return {
        "modelId": str(model.get("id") or model_id),
        "api_model_id": str(model.get("api_model_id") or ""),
        "endpoint": str(model.get("endpoint") or ""),
        "label": str(model.get("label") or model.get("name") or model_id),
        "providerId": provider_id,
        "allowedDurations": durations,
        "durations": durations,
        "preferredDurationSeconds": preferred_duration,
        "allowedResolutions": resolutions,
        "defaultResolution": str(model.get("default_resolution") or ""),
        "supports": supports,
        "supportsStoryboardReferenceImage": bool(
            model.get("supports_storyboard_reference_image") is True
            or model.get("supportsStoryboardReferenceImage") is True
            or "storyboard_reference_image" in support_set
        ),
        "supportsMultiReferenceImages": bool(
            model.get("supports_multi_reference_images") is True
            or model.get("supportsMultiReferenceImages") is True
            or "multi_reference_video" in support_set
        ),
        "supportsNativeAudio": bool(
            model.get("audio")
            or model.get("supports_native_audio") is True
            or model.get("supportsNativeAudio") is True
            or "native_audio" in support_set
        ),
        "maxReferenceImages": int(model.get("max_reference_images") or 0),
        **copy.deepcopy(_video_task_card_final_prompt_policy()),
        "finalPromptProfile": _video_task_card_final_prompt_profile(model),
        "promptTimingStyle": _video_task_card_prompt_timing_style(model),
    }


def _video_task_card_duration(
    value: Any,
    fallback: int = 8,
    allowed_durations: list[int] | None = None,
) -> int:
    try:
        duration = int(value)
    except (TypeError, ValueError):
        duration = fallback
    if duration <= 0:
        duration = fallback
    allowed = sorted({int(item) for item in (allowed_durations or []) if 0 < int(item) <= 60})
    if allowed:
        return min(allowed, key=lambda item: (abs(item - duration), item))
    return duration


def _video_task_card_allowed_duration_values(values: Any) -> list[int]:
    rows = values if isinstance(values, list) else []
    allowed: list[int] = []
    for item in rows:
        if isinstance(item, bool):
            continue
        try:
            raw_duration = float(item)
        except (TypeError, ValueError):
            continue
        if abs(raw_duration - round(raw_duration)) > 0.005:
            continue
        duration = int(round(raw_duration))
        if 0 < duration <= 60 and duration not in allowed:
            allowed.append(duration)
    return sorted(allowed)


def _video_task_card_allowed_duration_label(allowed_durations: list[int]) -> str:
    return "、".join(f"{item:g} 秒" for item in allowed_durations)


def _workflow_model_capability_row(model: dict[str, Any], media_type: str) -> dict[str, Any]:
    supports = {
        str(item).strip().lower()
        for item in model.get("supports", [])
        if str(item).strip()
    } if isinstance(model.get("supports"), list) else set()
    normalized = _normalized_model_capabilities(model, supports)
    resolution_descriptions = (
        model.get("resolution_descriptions")
        if isinstance(model.get("resolution_descriptions"), dict)
        else model.get("resolutionDescriptions")
        if isinstance(model.get("resolutionDescriptions"), dict)
        else {}
    )
    provider_resolutions = _string_list(model.get("resolutions"))
    resolutions = _workflow_resolution_options(provider_resolutions, media_type)
    default_resolution = _workflow_resolution_default(
        model.get("default_resolution"),
        resolutions,
        media_type,
    )
    durations = (
        _model_duration_options(model, default_resolution)
        if media_type == "video"
        else model.get("durations") if isinstance(model.get("durations"), list) else []
    )
    provider_id = model.get("provider_id") or model.get("provider_preset_id")
    raw_model_id = str(model.get("id") or "")
    model_id = raw_model_id.split(":", 1)[1] if ":" in raw_model_id else raw_model_id
    prompt_hard_limit_chars = (
        video_prompt_char_limit(str(provider_id or ""), model_id, model=model)
        if media_type == "video"
        else 0
    )
    return {
        "id": model.get("id"),
        "label": model.get("label") or model.get("id"),
        "type": media_type,
        "providerId": provider_id,
        "providerPresetId": model.get("provider_preset_id"),
        "adapterId": model.get("adapter_id") or model.get("adapterId"),
        "endpoint": model.get("endpoint") or "",
        "available": model.get("available", True),
        "availability_note": model.get("availability_note", ""),
        "defaultResolution": default_resolution,
        "resolutions": resolutions,
        "providerResolutions": provider_resolutions,
        "resolutionLabels": {
            resolution: resolution
            for resolution in resolutions
        },
        "resolutionDescriptions": copy.deepcopy(resolution_descriptions),
        "resolution_descriptions": copy.deepcopy(resolution_descriptions),
        "durations": durations,
        "allowedDurations": durations,
        "fps": normalized.get("limits", {}).get("fps") or [],
        "inputModes": normalized.get("inputModes") or [],
        "aspectRatios": normalized.get("limits", {}).get("aspectRatios") or [],
        "maxReferenceImages": normalized.get("limits", {}).get("maxReferenceImages") or 0,
        "supportsStoryboardReferenceImage": bool(
            model.get("supports_storyboard_reference_image") is True
            or model.get("supportsStoryboardReferenceImage") is True
        ),
        "supportsMultiReferenceImages": bool(
            model.get("supports_multi_reference_images") is True
            or model.get("supportsMultiReferenceImages") is True
        ),
        "supportsNativeAudio": bool(
            model.get("supports_native_audio") is True
            or model.get("supportsNativeAudio") is True
            or model.get("audio") is True
        ),
        "promptHardLimitChars": prompt_hard_limit_chars,
        "finalPromptProfile": _video_task_card_final_prompt_profile(model),
        "promptTimingStyle": _video_task_card_prompt_timing_style(model),
        "capabilitySource": model.get("capability_source")
        or model.get("capabilitySource")
        or "",
        "capabilitySourceUrl": model.get("capability_source_url")
        or model.get("capabilitySourceUrl")
        or "",
        "capabilityNote": model.get("capability_note")
        or model.get("capabilityNote")
        or "",
        "referenceImageLimitSource": model.get("reference_image_limit_source")
        or model.get("referenceImageLimitSource")
        or "",
        "referenceImageLimitSourceUrl": model.get("reference_image_limit_source_url")
        or model.get("referenceImageLimitSourceUrl")
        or "",
        "referenceImageLimitNote": model.get("reference_image_limit_note")
        or model.get("referenceImageLimitNote")
        or "",
        "supports": normalized.get("supports") or {},
        "rawSupports": normalized.get("rawSupports") or [],
        "official_capabilities": copy.deepcopy(model.get("official_capabilities")),
        "adapter_capabilities": copy.deepcopy(model.get("adapter_capabilities")),
    }


def list_model_capabilities(
    project_id: str,
    episode_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .model_provider_config import _project_model_selection
    from .settings_loaders import filter_model_capabilities_by_status

    payload = payload if isinstance(payload, dict) else {}
    capabilities, model_config = _project_model_selection(project_id)
    media_type = str(payload.get("mediaType") or payload.get("media_type") or "").strip().lower()
    keys = [media_type] if media_type in {"image", "video"} else ["image", "video"]
    visible_capabilities = filter_model_capabilities_by_status(
        capabilities, str(payload.get("status") or "adapted")
    )
    models = {
        key: [
            _workflow_model_capability_row(model, key)
            for model in visible_capabilities.get(key, [])
            if isinstance(model, dict)
        ]
        for key in keys
    }
    return {
        "success": True,
        "projectId": project_id,
        "episodeId": episode_id,
        "modelConfig": copy.deepcopy(model_config),
        "modelOptions": _model_options_from_capabilities(visible_capabilities),
        "models": models,
        "slotSchema": copy.deepcopy(WORKFLOW_NODE_SLOT_SCHEMA),
    }
