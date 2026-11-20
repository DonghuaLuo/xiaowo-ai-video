# -*- coding: utf-8 -*-
"""Canonical video model capability table used by catalog and adapters.

Read video_model_capability(model_id)[scope]["visual_inputs"], where scope is
"official_capabilities" for provider support or "adapter_capabilities" for
currently available storyboard actions. A selection must fit one complete
mode (required roles, per-role counts and shared reference limits); never union
roles from separate modes. These modes describe visual inputs, not audio/text
only generation. Prompted frames and storyboards consume reference-image slots.
"""

from __future__ import annotations

import copy
from typing import Any

from utils.autodl_comfyui import AUTODL_H3_WORKFLOWS


def _seconds(start: int, end: int) -> list[int]:
    return list(range(start, end + 1))


FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT = "seedance_official_compact"
FINAL_VIDEO_PROMPT_PROFILE_DASHSCOPE_WAN27_R2V_OFFICIAL = "dashscope_wan27_r2v_official"
FINAL_VIDEO_PROMPT_PROFILE_VIDU_Q3_REFERENCE_OFFICIAL = "vidu_q3_reference_official"
FINAL_VIDEO_PROMPT_PROFILE_HAPPYHORSE_OFFICIAL = "happyhorse_official"
FINAL_VIDEO_PROMPT_PROFILE_GROK_OFFICIAL = "grok_official"
FINAL_VIDEO_PROMPT_PROFILE_KLING_OFFICIAL = "kling_official"
FINAL_VIDEO_PROMPT_PROFILE_VEO_OFFICIAL = "veo_official"
FINAL_VIDEO_PROMPT_PROFILE_MINIMAX_H3_OFFICIAL = "minimax_h3_official"
SEEDANCE_IMAGE_MAX_BYTES = 30 * 1024 * 1024
SEEDANCE_AUDIO_MAX_BYTES = 15 * 1024 * 1024
SEEDANCE_REQUEST_BODY_MAX_BYTES = 64 * 1024 * 1024
DASHSCOPE_PROMPT_HARD_LIMIT_CHARS = 5000
VIDU_PROMPT_HARD_LIMIT_CHARS = 5000
VIDU_REFERENCE_PROMPT_HARD_LIMIT_CHARS = 2000
SEEDANCE_IMAGE_LIMITS = {
    "min_side": 300, "max_side": 6000, "min_ratio": 0.4, "max_ratio": 2.5,
    "max_bytes": SEEDANCE_IMAGE_MAX_BYTES,
}


def _reference_audio_capabilities(*, transport: str = "data_url", count: int = 3,
                                  min_seconds: int = 2, max_seconds: int = 15,
                                  total_seconds: int = 15, binding: str = "prompt",
                                  native_frames: bool = False, requires_visual: bool = True,
                                  mixed_limit: int = 0, prompt_label: str = "音频{index}") -> dict[str, Any]:
    return {
        "supports_reference_audio_input": True,
        "max_reference_audios": count,
        "reference_audio_limits": {
            "transport": transport, "binding": binding, "max_count": count,
            "min_seconds": min_seconds, "max_seconds": max_seconds,
            "total_max_seconds": total_seconds, "max_bytes": SEEDANCE_AUDIO_MAX_BYTES,
            "formats": ["wav", "mp3"], "supports_native_frames": native_frames,
            "requires_visual": requires_visual, "max_mixed_materials": mixed_limit,
            "prompt_label": prompt_label,
        },
    }


def _visual_input_mode(
    mode_id: str,
    endpoint: str,
    *,
    first_frame: int = 0,
    last_frame: int = 0,
    reference_image: int = 0,
    reference_video: int = 0,
    required_roles: tuple[str, ...] = (),
    min_reference_materials: int = 0,
    max_reference_materials: int = 0,
) -> dict[str, Any]:
    return {
        "id": mode_id,
        "endpoint": endpoint,
        "required_roles": list(required_roles),
        "max_counts": {
            "first_frame": first_frame,
            "last_frame": last_frame,
            "reference_image": reference_image,
            "reference_video": reference_video,
        },
        # Only reference_image + reference_video count toward this shared limit.
        # Storyboards and prompted frames are reference_image, not extra slots.
        "min_reference_materials": min_reference_materials,
        "max_reference_materials": max_reference_materials,
    }


def _official_visual_inputs(
    *,
    reference_endpoint: str,
    max_images: int,
    max_videos: int = 0,
    max_references: int,
    first_frame_endpoint: str = "",
    first_last_frame_endpoint: str = "",
    first_frame_with_references: bool = False,
    native_frame_controls_aspect_ratio: bool = False,
    storyboard_support: str = "image_reference_only",
    prompted_frame_support: str = "unverified",
    verified_on: str = "2026-09-24",
    source_urls: tuple[str, ...],
) -> dict[str, Any]:
    """Visual input combinations, not a promise of frame/shot fidelity.

    documented: explicitly described by the provider; image_reference_only:
    upload is supported but storyboard interpretation is not confirmed;
    unverified: a prompting strategy, not a documented frame constraint.
    """
    modes = [_visual_input_mode(
        "reference_to_video", reference_endpoint,
        first_frame=int(first_frame_with_references),
        reference_image=max_images, reference_video=max_videos,
        min_reference_materials=1, max_reference_materials=max_references,
    )] if max_images or max_videos else []
    if first_frame_endpoint:
        modes.append(_visual_input_mode(
            "first_frame_to_video", first_frame_endpoint,
            first_frame=1, required_roles=("first_frame",),
        ))
    if first_last_frame_endpoint:
        modes.append(_visual_input_mode(
            "first_last_frame_to_video", first_last_frame_endpoint,
            first_frame=1, last_frame=1,
            required_roles=("first_frame", "last_frame"),
        ))
    return {
        "supports_video_generation": True,
        "supports_reference_video": max_videos > 0,
        "max_reference_videos": max_videos,
        "visual_inputs": {
            "supports_first_frame": bool(first_frame_endpoint or first_frame_with_references),
            "native_frame_controls_aspect_ratio": native_frame_controls_aspect_ratio,
            "supports_last_frame": bool(first_last_frame_endpoint),
            "supports_last_frame_only": False,
            "supports_multi_reference_images": max_images > 1,
            "storyboard_support": storyboard_support,
            "prompted_frame_support": prompted_frame_support,
            "supports_native_pseudo_frame": False,
            "modes": modes,
            "verified_on": verified_on,
            "source_urls": list(source_urls),
        },
    }


def _model_capability(
    *,
    provider_prefix: str,
    title: str,
    resolutions: list[str],
    default_resolution: str,
    durations: list[int],
    audio: bool,
    max_reference_images: int,
    metadata: dict[str, Any],
    supports: list[str],
    usage: str,
    supports_reference_video: bool,
    official_capabilities: dict[str, Any] | None = None,
    adapter_capabilities: dict[str, Any] | None = None,
    keyframe_durations: list[int] | None = None,
) -> dict[str, Any]:
    adapter = {
        "resolutions": list(resolutions),
        "default_resolution": default_resolution,
        "durations": list(durations),
        "audio": audio,
        "max_reference_images": max_reference_images,
        "supports": list(supports),
        "supports_reference_video": supports_reference_video,
        **copy.deepcopy(adapter_capabilities or {}),
    }
    official = {
        "resolutions": list(resolutions),
        "default_resolution": default_resolution,
        "durations": list(durations),
        "audio": audio,
        "max_reference_images": max_reference_images,
        "supports": list(supports),
        "supports_reference_video": supports_reference_video,
        **copy.deepcopy(official_capabilities or {}),
    }
    # Ordinary cards use reference modes; native cards get their own mode subset.
    visual_inputs = copy.deepcopy(official["visual_inputs"])
    visual_inputs["modes"] = [mode for mode in visual_inputs["modes"] if mode["max_counts"]["reference_image"] > 0]
    visual_inputs["supports_first_frame"] = any(mode["max_counts"]["first_frame"] > 0 for mode in visual_inputs["modes"])
    visual_inputs["supports_last_frame"] = any(mode["max_counts"]["last_frame"] > 0 for mode in visual_inputs["modes"])
    for mode in visual_inputs["modes"]:
        if not supports_reference_video:
            mode["max_counts"]["reference_video"] = 0
        if mode["id"] == "reference_to_video" and not supports_reference_video:
            mode["max_reference_materials"] = max_reference_images
    visual_inputs["prompted_frame_support"] = "documented" if visual_inputs["prompted_frame_support"] == "documented" else "unverified"
    adapter.update({
        "supports_video_generation": True,
        "max_reference_videos": official.get("max_reference_videos", 0) if supports_reference_video else 0,
        "visual_inputs": visual_inputs,
    })
    keyframe_visual_inputs = copy.deepcopy(official["visual_inputs"])
    keyframe_visual_inputs["durations"] = list(keyframe_durations if keyframe_durations is not None else durations)
    keyframe_visual_inputs["modes"] = [
        mode for mode in keyframe_visual_inputs["modes"]
        if mode["max_counts"]["first_frame"] > 0
    ]
    for mode in keyframe_visual_inputs["modes"]:
        if not supports_reference_video:
            mode["max_counts"]["reference_video"] = 0
    keyframe_visual_inputs["supports_first_frame"] = bool(keyframe_visual_inputs["modes"])
    keyframe_visual_inputs["supports_last_frame"] = any(
        mode["max_counts"]["last_frame"] > 0 for mode in keyframe_visual_inputs["modes"]
    )
    adapter["keyframe_visual_inputs"] = keyframe_visual_inputs
    if supports_reference_video:
        for key in ("reference_video_limits", "durations_with_reference_video"):
            if key in official:
                adapter[key] = copy.deepcopy(official[key])
    return {
        "provider_prefix": provider_prefix,
        "title": title,
        "resolutions": adapter["resolutions"],
        "default_resolution": adapter["default_resolution"],
        "durations": adapter["durations"],
        "audio": adapter["audio"],
        "max_reference_images": adapter["max_reference_images"],
        "metadata": metadata,
        "supports": adapter["supports"],
        "usage": usage,
        "supports_reference_video": adapter["supports_reference_video"],
        "official_capabilities": official,
        "adapter_capabilities": adapter,
    }


ARK_SEEDANCE_2_VIDEO_CAPABILITY_METADATA = {
    "capability_source": "official",
    "capability_source_url": "https://docs.volcengine.com/docs/82379/2222480",
    "capability_note": (
        "Seedance 2.0 family supports multimodal reference-to-video generation. "
        "Prompt strategy follows the official Seedance 2.0 prompt guide: define subjects, "
        "map references clearly and use shot sequence as the primary temporal control. "
        "The local adapter exposes storyboard reference image and multi-reference image "
        "generation with reference video input."
    ),
}

ARK_SEEDANCE_25_VIDEO_CAPABILITY_METADATA = {
    "capability_source": "official",
    "capability_source_url": "https://docs.volcengine.com/docs/82379/2607689",
    "capability_note": (
        "Seedance 2.5 supports 4-30 second multimodal reference-to-video generation. "
        "The local adapter exposes storyboard reference image and multi-reference image "
        "generation with reference video input. Prompt strategy follows the "
        "official Seedance 2.5 prompt guide and uses shot sequence plus rhythm/action "
        "density instead of mechanical per-second timeline descriptions."
    ),
}

DASHSCOPE_WAN27_VIDEO_CAPABILITY_METADATA = {
    "capability_source": "official",
    "capability_source_url": "https://help.aliyun.com/zh/model-studio/wan2-7-r2v",
    "capability_note": (
        "DashScope Wan2.7 R2V supports text/image/video/audio input, up to 5 mixed "
        "image/video references, and audio timbre reference. The local adapter uses "
        "reference_image media for storyboard video generation; final prompts follow "
        "the official Wan video prompt formulas with uploaded media labels such as 图1."
    ),
    "prompt_hard_limit_chars": DASHSCOPE_PROMPT_HARD_LIMIT_CHARS,
    "official_prompt_limit_chars": DASHSCOPE_PROMPT_HARD_LIMIT_CHARS,
}

VIDU_Q3_VIDEO_CAPABILITY_METADATA = {
    "capability_source": "official",
    "capability_source_url": "https://platform.vidu.cn/docs/reference-to-video",
    "capability_note": (
        "Vidu Q3-family reference-to-video models support multi-reference image input "
        "and audio-video output. The local adapter routes storyboard video generation "
        "through the official reference2video endpoint and keeps the prompt aligned "
        "with uploaded image references. The local images-array adapter uses the "
        "stricter limits shared by the China and global APIs; subjects are not enabled."
    ),
    "prompt_hard_limit_chars": VIDU_REFERENCE_PROMPT_HARD_LIMIT_CHARS,
    "official_prompt_limit_chars": VIDU_REFERENCE_PROMPT_HARD_LIMIT_CHARS,
}

SEEDANCE_COMMON_OFFICIAL_INPUT_LIMITS: dict[str, Any] = {
    "parameter_transport": "request_body",
    "weak_prompt_parameter_transport_supported": True,
    "generation_modes": [
        "multimodal_reference_to_video",
        "first_last_frame_to_video",
        "first_frame_to_video",
        "text_to_video",
    ],
    "multimodal_reference_task_modes": [
        "generate_new_video",
        "edit_video",
        "extend_video",
    ],
    "supported_content_types": ["text", "image_url", "video_url", "audio_url"],
    "reference_image_formats": ["jpeg", "png", "webp", "bmp", "tiff", "gif", "heic", "heif"],
    "reference_image_aspect_ratio_range": [0.4, 2.5],
    "reference_image_width_height_px_range": [300, 6000],
    "reference_image_max_bytes": SEEDANCE_IMAGE_MAX_BYTES,
    "reference_audio_formats": ["wav", "mp3"],
    "reference_audio_max_bytes": SEEDANCE_AUDIO_MAX_BYTES,
    "request_body_max_bytes": SEEDANCE_REQUEST_BODY_MAX_BYTES,
    "content_role_map": {
        "reference_image": "image_url",
        "reference_video": "video_url",
        "first_frame": "image_url",
        "last_frame": "image_url",
        "reference_audio": "audio_url",
    },
    "prompt_guide_source_urls": [
        "https://docs.volcengine.com/docs/82379/2222480",
        "https://docs.volcengine.com/docs/82379/1520757",
    ],
}

SEEDANCE_2_OFFICIAL_REFERENCE_LIMITS: dict[str, Any] = {
    **SEEDANCE_COMMON_OFFICIAL_INPUT_LIMITS,
    **_official_visual_inputs(
        reference_endpoint="/api/v3/contents/generations/tasks",
        max_images=9, max_videos=3, max_references=12,
        first_frame_endpoint="/api/v3/contents/generations/tasks",
        first_last_frame_endpoint="/api/v3/contents/generations/tasks",
        prompted_frame_support="documented",
        source_urls=("https://docs.volcengine.com/docs/82379/1520757",),
    ),
    "output_fps": 24,
    "reference_video_limits": {"min_seconds": 2, "max_seconds": 15, "total_max_seconds": 15, "max_bytes": 200 * 1024 * 1024, "formats": ["mp4", "mov"], "min_width": 300, "max_width": 6000, "min_height": 300, "max_height": 6000, "min_pixels": 407696, "max_pixels": 8295044, "min_ratio": 0.4, "max_ratio": 2.5, "min_fps": 24, "max_fps": 60, "transport": "public_url"},
    "output_formats": ["mp4"],
    "max_reference_images": 9,
    "max_reference_audios": 3,
    "max_mixed_reference_materials": 15,
    "reference_audio_clip_seconds_range": [2, 15],
    "reference_audio_total_max_seconds": 15,
    "supports_audio_only_input": False,
    "requires_image_or_video_with_reference_audio": True,
}

SEEDANCE_25_OFFICIAL_REFERENCE_LIMITS: dict[str, Any] = {
    **SEEDANCE_COMMON_OFFICIAL_INPUT_LIMITS,
    **_official_visual_inputs(
        reference_endpoint="/api/v3/contents/generations/tasks",
        max_images=30, max_videos=10, max_references=40,
        first_frame_endpoint="/api/v3/contents/generations/tasks",
        first_last_frame_endpoint="/api/v3/contents/generations/tasks",
        storyboard_support="documented",
        prompted_frame_support="documented",
        source_urls=(
            "https://docs.volcengine.com/docs/82379/1520757",
            "https://docs.volcengine.com/docs/ark/seedance-2-5-prompt-guide?lang=zh",
        ),
    ),
    "output_fps": 24,
    "reference_video_limits": {"min_seconds": 2, "max_seconds": 30, "total_max_seconds": 30, "max_bytes": 200 * 1024 * 1024, "formats": ["mp4", "mov"], "min_width": 300, "max_width": 6000, "min_height": 300, "max_height": 6000, "min_pixels": 407696, "max_pixels": 8295044, "min_ratio": 0.4, "max_ratio": 2.5, "min_fps": 24, "max_fps": 60, "transport": "public_url"},
    "output_formats": ["mp4", "mov"],
    "max_reference_images": 30,
    "max_reference_audios": 10,
    "max_mixed_reference_materials": 50,
    "reference_audio_clip_seconds_range": [2, 30],
    "reference_audio_total_max_seconds": 30,
    "supports_audio_only_input": True,
    "requires_image_or_video_with_reference_audio": False,
}

SEEDANCE_2_ADAPTER_CAPABILITIES: dict[str, Any] = {
    "reference_image_limits": SEEDANCE_IMAGE_LIMITS,
    "max_reference_videos": 0,
    **_reference_audio_capabilities(mixed_limit=15),
    "supports_audio_only_input": False,
    "parameter_transport": "request_body",
    "request_body_max_bytes": SEEDANCE_REQUEST_BODY_MAX_BYTES,
    "final_prompt_profile": FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT,
    "prompt_timing_style": "shot_sequence",
}

SEEDANCE_25_ADAPTER_CAPABILITIES: dict[str, Any] = {
    "reference_image_limits": SEEDANCE_IMAGE_LIMITS,
    "max_reference_videos": 0,
    **_reference_audio_capabilities(count=10, max_seconds=30, total_seconds=30,
                                    requires_visual=False, mixed_limit=50, prompt_label="@音频{index}"),
    "supports_audio_only_input": True,
    "parameter_transport": "request_body",
    "request_body_max_bytes": SEEDANCE_REQUEST_BODY_MAX_BYTES,
    "final_prompt_profile": FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT,
    "prompt_timing_style": "integer_second_timeline",
}

DASHSCOPE_WAN27_ADAPTER_CAPABILITIES: dict[str, Any] = {
    "reference_image_limits": {
        "min_side": 240, "max_side": 8000, "min_ratio": 0.125, "max_ratio": 8,
        "max_bytes": 20 * 1024 * 1024, "allow_alpha": False,
    },
    "final_prompt_profile": FINAL_VIDEO_PROMPT_PROFILE_DASHSCOPE_WAN27_R2V_OFFICIAL,
    "prompt_timing_style": "integer_second_timeline",
}

VIDU_Q3_ADAPTER_CAPABILITIES: dict[str, Any] = {
    # Common supported range for both configured .cn and .com API hosts.
    "request_body_max_bytes": 20 * 1024 * 1024,
    "reference_image_limits": {
        "min_side": 128, "min_ratio": 0.25, "max_ratio": 4,
        "max_bytes": 10 * 1024 * 1024,
    },
    "keyframe_prompt_hard_limit_chars": VIDU_PROMPT_HARD_LIMIT_CHARS,
    "final_prompt_profile": FINAL_VIDEO_PROMPT_PROFILE_VIDU_Q3_REFERENCE_OFFICIAL,
    "prompt_timing_style": "shot_sequence",
    "native_frame_ratio_range": [0.8, 1.25],
}

STORYBOARD_VIDEO_SERVICE_IDS = {"ark-seedance", "dashscope", "vidu", "minimax", "metaso", "autodl-comfyui"}


def _autodl_h3_capability(model_name: str) -> dict[str, Any] | None:
    workflow = AUTODL_H3_WORKFLOWS.get(model_name)
    if not workflow:
        return None
    native = workflow["native_frames"]
    replace = workflow.get("character_replace", False)
    max_images = workflow.get("max_images", 0 if native else 9)
    endpoint = f"/comfyui_workflow/{model_name}"
    source = f"https://www.autodl.art/large-model/comfyui/{model_name}"
    official = _official_visual_inputs(
        reference_endpoint=endpoint, max_images=max_images, max_references=max_images + int(replace), max_videos=int(replace),
        first_last_frame_endpoint=endpoint if native else "", verified_on="2026-11-17",
        source_urls=(source, "https://autodl.art/docs/comfyui_api/"),
    )
    if not native and not workflow["image_required"]:
        official["visual_inputs"]["modes"][0]["min_reference_materials"] = 0
    if replace:
        official["visual_inputs"]["modes"][0]["required_roles"] = ["reference_image", "reference_video"]
        official["reference_video_limits"] = {"formats": ["mp4", "webm"], "transport": "public_url"}
    spec = _model_capability(
        provider_prefix="autodl-comfyui", title=workflow["title"], resolutions=["768p"] if replace else ["480p", "768p"],
        default_resolution="768p", durations=_seconds(5, 25) if replace else _seconds(1, 15), audio=True,
        max_reference_images=max_images, supports_reference_video=replace,
        supports=["character_replace", "single_image_to_video", "multi_reference_video"] if replace else ["native_audio"] if native else ["storyboard_reference_image", "single_image_to_video", "multi_reference_video", "native_audio"],
        usage="用角色图替换源视频中的角色，沿用源视频表演、镜头与原声" if replace else "原生首尾帧生成视频（首帧和尾帧均必填）" if native else "多参考图生成有声视频",
        metadata={"capability_source": "official", "capability_source_url": source,
                  "prompt_hard_limit_chars": 2048 if replace else 20000, "official_prompt_limit_chars": 2048 if replace else 20000,
                  "capability_note": "角色替换专用：一段源视频与角色图；替换说明可留空，原声沿用源视频。" if replace else "AutoDL 托管工作流：不支持参考视频；参考音频尚未接入。"},
        official_capabilities=official,
        adapter_capabilities={"endpoint": endpoint, "query_endpoint": "/comfyui_workflow/result/{task_id}",
                              "final_prompt_profile": "character_replace" if replace else FINAL_VIDEO_PROMPT_PROFILE_MINIMAX_H3_OFFICIAL,
                              **({"task_types": ["video.character_replace"], "audio_mode": "source_audio"} if replace else {}),
                              "prompt_timing_style": "shot_sequence", "reference_image_transport": "public_url"},
    )
    spec["aspect_ratios"] = list(workflow["aspect_ratios"])
    return spec


def _minimax_h3_capability(model_name: str, *, deployment: str = "minimax") -> dict[str, Any]:
    is_metaso = deployment == "metaso"
    source = (
        "https://github.com/meta-sota/ComfyUI-MiniMaxH3-API/blob/main/nodes.py"
        if is_metaso else "https://platform.minimax.cn/docs/api-reference/video-generation-v2-create"
    )
    query_source = (
        "https://github.com/meta-sota/ComfyUI-MiniMaxH3-API/blob/main/api_client.py"
        if is_metaso else "https://platform.minimax.cn/docs/api-reference/video-generation-v2-query"
    )
    is_max = model_name == "MiniMax-H3-Max"
    resolutions = ["480p", "768p"] if is_max else ["768p", "2k"]
    durations = _seconds(5, 15) if is_max else _seconds(4, 15)
    supports_reference_video = is_max or is_metaso
    official = _official_visual_inputs(
        reference_endpoint="/v2/video_generation",
        max_images=9,
        max_videos=3 if supports_reference_video else 0,
        max_references=12 if supports_reference_video else 9,
        first_frame_endpoint="/v2/video_generation",
        first_last_frame_endpoint="/v2/video_generation",
        native_frame_controls_aspect_ratio=True,
        storyboard_support="documented",
        prompted_frame_support="documented",
        source_urls=(source, query_source),
        verified_on="2026-10-08" if is_metaso else "2026-09-30",
    )
    official.update(_reference_audio_capabilities(transport="public_url" if is_metaso else "data_url"))
    if supports_reference_video:
        official["reference_video_limits"] = {
            "min_seconds": 2, "max_seconds": 15, "total_max_seconds": 15,
            "max_bytes": 50 * 1000 * 1000, "formats": ["mp4", "mov"],
            "video_codecs": ["h264", "hevc"], "audio_codecs": ["aac", "mp3"],
            "min_width": 256, "max_width": 5760, "min_height": 256, "max_height": 5760,
            "min_ratio": 0.4, "max_ratio": 2.5, "min_fps": 23.976, "max_fps": 60,
            "transport": "public_url",
        }
    spec = _model_capability(
        provider_prefix=deployment, title=model_name,
        resolutions=resolutions, default_resolution="768p", durations=durations,
        audio=True, max_reference_images=9, supports_reference_video=supports_reference_video,
        supports=[
            "storyboard_reference_image", "single_image_to_video", "multi_reference_video", "native_audio",
        ],
        usage="参考图/视频，或原生首帧/首尾帧生成视频" if supports_reference_video else "参考图，或原生首帧/首尾帧生成视频",
        metadata={
            "capability_source": "official", "capability_source_url": source,
            "prompt_hard_limit_chars": 7000, "official_prompt_limit_chars": 7000,
            "capability_note": (
                "秘塔 H3 部署：支持参考图/视频及参考音频，与原生首尾帧模式互斥，原生有声输出。"
                if is_metaso else "原生首尾帧与参考素材模式互斥；H3 音频由模型原生生成。"
            ),
        },
        official_capabilities=official,
        adapter_capabilities={
            "endpoint": "/v2/video_generation",
            **_reference_audio_capabilities(transport="public_url" if is_metaso else "data_url"),
            "query_endpoint": "/v2/query/video_generation/{task_id}",
            "final_prompt_profile": FINAL_VIDEO_PROMPT_PROFILE_MINIMAX_H3_OFFICIAL,
            "prompt_timing_style": "shot_sequence", "native_ratio_parameter": "adaptive",
            "request_body_max_bytes": 64 * 1024 * 1024,
            "reference_image_limits": {
                "max_bytes": 30 * 1000 * 1000, "min_side": 256, "max_side": 5760,
                "min_ratio": 0.4, "max_ratio": 2.5, "allow_alpha": False,
            },
            **({"reference_video_limits": official["reference_video_limits"]} if supports_reference_video else {}),
        },
    )
    spec["aspect_ratios"] = ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
    return spec

def _wan3_capability(title: str) -> dict[str, Any]:
    endpoint = "/api/v1/services/aigc/video-generation/video-synthesis"
    source = "https://help.aliyun.com/zh/model-studio/wan3-video-generation-api-reference"
    return _model_capability(
        provider_prefix="dashscope", title=title,
        resolutions=["480p", "720p", "1080p"], default_resolution="720p",
        durations=_seconds(2, 30), audio=True, max_reference_images=10,
        metadata={"capability_source": "official", "capability_source_url": source,
                  "prompt_hard_limit_chars": 20000, "official_prompt_limit_chars": 20000},
        supports=["storyboard_reference_image", "single_image_to_video", "multi_reference_video", "native_audio"],
        usage="多参考素材 / 原生首尾帧生成视频", supports_reference_video=True,
        official_capabilities={
            **_official_visual_inputs(
                reference_endpoint=endpoint, max_images=10, max_videos=5, max_references=15,
                first_frame_endpoint=endpoint, first_last_frame_endpoint=endpoint,
                native_frame_controls_aspect_ratio=True, source_urls=(source,), verified_on="2026-09-29",
            ),
            "output_fps": 30,
            "reference_video_limits": {
                "min_seconds": 1, "max_seconds": 15, "total_max_seconds": 15,
                "input_output_max_seconds": 30,
                "max_bytes": 100 * 1024 * 1024, "formats": ["mp4", "mov"],
                "min_width": 240, "max_width": 4096, "min_height": 240, "max_height": 4096,
                "min_ratio": 0.125, "max_ratio": 8, "min_fps": 16, "transport": "public_url",
            },
        },
        adapter_capabilities={
            **DASHSCOPE_WAN27_ADAPTER_CAPABILITIES,
            "supports_reference_audio_input": False,
            "audio_parameter": "audio", "native_ratio_parameter": "adaptive",
            "reference_image_limits": {
                "min_side": 240, "max_side": 8000, "min_ratio": 0.125, "max_ratio": 8,
                "allow_alpha": False, "max_bytes": 20 * 1024 * 1024,
            },
        },
    )


def _vidu_native_capability(title: str, *, first_only: bool = False) -> dict[str, Any]:
    source = "https://platform.vidu.cn/docs/image-to-video"
    return _model_capability(
        provider_prefix="vidu", title=title,
        resolutions=["720p", "1080p"] if first_only else ["540p", "720p", "1080p"],
        default_resolution="720p", durations=_seconds(1, 16), audio=True, max_reference_images=0,
        metadata={"capability_source": "official", "capability_source_url": source,
                  "prompt_hard_limit_chars": VIDU_PROMPT_HARD_LIMIT_CHARS,
                  "official_prompt_limit_chars": VIDU_PROMPT_HARD_LIMIT_CHARS},
        supports=["single_image_to_video", "native_audio"],
        usage="原生首帧生成视频" if first_only else "原生首帧 / 首尾帧生成视频",
        supports_reference_video=False,
        official_capabilities=_official_visual_inputs(
            reference_endpoint="", max_images=0, max_references=0,
            first_frame_endpoint="/ent/v2/img2video",
            first_last_frame_endpoint="" if first_only else "/ent/v2/start-end2video",
            native_frame_controls_aspect_ratio=True,
            source_urls=(source, "https://platform.vidu.cn/docs/start-end-to-video"),
            verified_on="2026-09-29",
        ),
        adapter_capabilities=VIDU_Q3_ADAPTER_CAPABILITIES,
    )


def _happyhorse_capability(*, first_only: bool) -> dict[str, Any]:
    endpoint = "/api/v1/services/aigc/video-generation/video-synthesis"
    source = "https://help.aliyun.com/zh/model-studio/happyhorse-" + (
        "image-to-video-api-reference" if first_only else "reference-to-video-api-reference"
    )
    return _model_capability(
        provider_prefix="dashscope",
        title="HappyHorse 1.1 首帧" if first_only else "HappyHorse 1.1 参考图",
        resolutions=["480p", "720p", "1080p"], default_resolution="720p",
        durations=_seconds(3, 15), audio=True, max_reference_images=0 if first_only else 9,
        metadata={"capability_source": "official", "capability_source_url": source,
                  # Use the stricter documented Chinese limit for mixed-language prompts.
                  "prompt_hard_limit_chars": 2500, "official_prompt_limit_chars": 2500},
        supports=(["single_image_to_video", "native_audio"] if first_only else
                  ["storyboard_reference_image", "multi_reference_video", "native_audio"]),
        usage="原生首帧生成视频" if first_only else "多参考图生成视频",
        supports_reference_video=False,
        official_capabilities=_official_visual_inputs(
            reference_endpoint="" if first_only else endpoint,
            max_images=0 if first_only else 9, max_references=0 if first_only else 9,
            first_frame_endpoint=endpoint if first_only else "",
            native_frame_controls_aspect_ratio=first_only, source_urls=(source,),
            verified_on="2026-09-29",
        ),
        adapter_capabilities={
            "final_prompt_profile": FINAL_VIDEO_PROMPT_PROFILE_HAPPYHORSE_OFFICIAL,
            "prompt_timing_style": "shot_sequence", "supports_prompt_extend": False,
            "native_ratio_parameter": "omit" if first_only else "",
            "reference_image_limits": {
                "min_side": 300 if first_only else 400,
                "max_bytes": 20 * 1024 * 1024,
                **({"min_ratio": 0.4, "max_ratio": 2.5} if first_only else {}),
            },
        },
    )


def _grok_video_capability() -> dict[str, Any]:
    source = "https://docs.x.ai/developers/model-capabilities/video/reference-to-video"
    endpoint = "/v1/videos/generations"
    official = _official_visual_inputs(
        reference_endpoint=endpoint, max_images=7, max_references=7,
        first_frame_endpoint=endpoint, first_last_frame_endpoint=endpoint,
        native_frame_controls_aspect_ratio=True, source_urls=(source,), verified_on="2026-09-30",
    )
    official["visual_inputs"]["modes"].append(_visual_input_mode(
        "first_frame_with_references", endpoint, first_frame=1, last_frame=1,
        reference_image=7, required_roles=("first_frame",),
        min_reference_materials=1, max_reference_materials=7,
    ))
    # 1080p is only documented for pure image/text-to-video, not mixed/frame-pair modes.
    official.update(resolutions=["480p", "720p", "1080p"],
                    resolution_note="1080p: text-to-video or first-frame-only; reference modes: at most 720p")
    spec = _model_capability(
        provider_prefix="grok", title="Grok Imagine Video 1.5",
        resolutions=["480p", "720p"], default_resolution="720p", durations=_seconds(1, 15),
        audio=True, max_reference_images=7, supports_reference_video=False,
        supports=["storyboard_reference_image", "single_image_to_video", "multi_reference_video", "native_audio"],
        usage="参考图 / 首帧 / 首尾帧 / 首尾帧与参考图生成视频",
        metadata={"capability_source": "official", "capability_source_url": source,
                  "capability_note": "xAI native video protocol. Local cards expose up to 720p for consistent mixed modes; local body guard: 20 MiB."},
        official_capabilities=official,
        adapter_capabilities={
            "endpoint": endpoint, "final_prompt_profile": FINAL_VIDEO_PROMPT_PROFILE_GROK_OFFICIAL,
            "prompt_timing_style": "shot_sequence", "native_ratio_parameter": "omit",
            "supports_prompt_extend": False, "request_body_max_bytes": 20 * 1024 * 1024,
            "reference_image_limits": {"max_bytes": 20 * 1024 * 1024, "allow_alpha": False},
        },
    )
    spec["aspect_ratios"] = ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"]
    return spec


QINIU_KLING_MODELS = {
    "kling-v2-6": "https://apidocs.qnaigc.com/404263380e0.md",
    "kling-v3": "https://apidocs.qnaigc.com/421288748e0.md",
    "kling-v3-omni": "https://apidocs.qnaigc.com/420877484e0.md",
}


def _qiniu_kling_capability(model_name: str, source: str) -> dict[str, Any]:
    omni = model_name == "kling-v3-omni"
    first_only = model_name == "kling-v2-6"
    endpoint = "/v1/videos"
    official = _official_visual_inputs(
        reference_endpoint=endpoint if omni else "", max_images=7 if omni else 0, max_references=7 if omni else 0,
        first_frame_endpoint=endpoint, first_last_frame_endpoint="" if first_only else endpoint,
        native_frame_controls_aspect_ratio=True, source_urls=(source,), verified_on="2026-09-30",
    )
    if omni:
        # At most seven images total. An end frame is forbidden with >2 images.
        official["visual_inputs"]["modes"].append(_visual_input_mode(
            "first_frame_with_references", endpoint, first_frame=1, reference_image=6,
            required_roles=("first_frame",), min_reference_materials=1, max_reference_materials=6,
        ))
    spec = _model_capability(
        provider_prefix="qiniu-kling", title="可灵 3.0 Omni" if omni else "可灵 2.6" if first_only else "可灵 3.0",
        resolutions=["720p", "1080p"], default_resolution="720p", durations=[5, 10] if first_only else _seconds(3, 15),
        audio=True, max_reference_images=7 if omni else 0, supports_reference_video=False,
        supports=(["storyboard_reference_image", "multi_reference_video"] if omni else []) + ["single_image_to_video", "native_audio"],
        usage="参考图 / 原生首尾帧生成视频" if omni else "原生首帧生成视频" if first_only else "原生首尾帧生成视频",
        metadata={"capability_source": "official", "capability_source_url": source,
                  "prompt_hard_limit_chars": 2500, "official_prompt_limit_chars": 2500,
                  "capability_note": "Qiniu Kling native route; sound on. Reference video requires sound off and is not exposed."},
        official_capabilities=official,
        adapter_capabilities={"endpoint": endpoint, "final_prompt_profile": FINAL_VIDEO_PROMPT_PROFILE_KLING_OFFICIAL,
                              "prompt_timing_style": "shot_sequence", "native_ratio_parameter": "omit",
                              "request_body_max_bytes": 20 * 1024 * 1024,
                              "reference_image_limits": {"max_bytes": 10 * 1024 * 1024, "min_side": 300,
                                                         "min_ratio": 0.4, "max_ratio": 2.5, "allow_alpha": False}},
    )
    spec["aspect_ratios"] = ["16:9", "9:16", "1:1"]
    return spec


STORYBOARD_VIDEO_MODEL_CAPABILITIES: dict[str, dict[str, Any]] = {
    **{name: _qiniu_kling_capability(name, source) for name, source in QINIU_KLING_MODELS.items()},
    "grok-imagine-video-1.5": _grok_video_capability(),
    "MiniMax-H3": _minimax_h3_capability("MiniMax-H3"),
    "MiniMax-H3-Max": _minimax_h3_capability("MiniMax-H3-Max"),
    "doubao-seedance-2-0-260128": _model_capability(
        provider_prefix="ark",
        title="Seedance 2.0",
        resolutions=["480p", "720p", "1080p", "4K"],
        default_resolution="720p",
        durations=_seconds(4, 15),
        audio=True,
        max_reference_images=9,
        metadata=ARK_SEEDANCE_2_VIDEO_CAPABILITY_METADATA,
        supports=[
            "text_to_video",
            "storyboard_reference_image",
            "single_image_to_video",
            "multi_reference_video",
            "native_audio",
        ],
        usage="故事版视频生成 / 图片参考生成视频",
        supports_reference_video=True,
        official_capabilities={
            **SEEDANCE_2_OFFICIAL_REFERENCE_LIMITS,
        },
        adapter_capabilities=SEEDANCE_2_ADAPTER_CAPABILITIES,
    ),
    "doubao-seedance-2-0-fast-260128": _model_capability(
        provider_prefix="ark",
        title="Seedance 2.0 Fast",
        resolutions=["480p", "720p"],
        default_resolution="720p",
        durations=_seconds(4, 15),
        audio=True,
        max_reference_images=9,
        metadata=ARK_SEEDANCE_2_VIDEO_CAPABILITY_METADATA,
        supports=[
            "text_to_video",
            "storyboard_reference_image",
            "single_image_to_video",
            "multi_reference_video",
            "native_audio",
        ],
        usage="故事版视频快速预览 / 图片参考生成视频",
        supports_reference_video=True,
        official_capabilities={
            **SEEDANCE_2_OFFICIAL_REFERENCE_LIMITS,
        },
        adapter_capabilities=SEEDANCE_2_ADAPTER_CAPABILITIES,
    ),
    "doubao-seedance-2-0-mini-260615": _model_capability(
        provider_prefix="ark",
        title="Seedance 2.0 Mini",
        resolutions=["480p", "720p"],
        default_resolution="720p",
        durations=_seconds(4, 15),
        audio=True,
        max_reference_images=9,
        metadata=ARK_SEEDANCE_2_VIDEO_CAPABILITY_METADATA,
        supports=[
            "text_to_video",
            "storyboard_reference_image",
            "single_image_to_video",
            "multi_reference_video",
            "native_audio",
        ],
        usage="故事版视频轻量快速生成 / 图片参考生成视频",
        supports_reference_video=True,
        official_capabilities={
            **SEEDANCE_2_OFFICIAL_REFERENCE_LIMITS,
        },
        adapter_capabilities=SEEDANCE_2_ADAPTER_CAPABILITIES,
    ),
    "doubao-seedance-2-5-260628": _model_capability(
        provider_prefix="ark",
        title="Seedance 2.5",
        resolutions=["480p", "720p", "1080p"],
        default_resolution="720p",
        durations=_seconds(4, 30),
        audio=True,
        max_reference_images=30,
        metadata=ARK_SEEDANCE_25_VIDEO_CAPABILITY_METADATA,
        supports=[
            "text_to_video",
            "storyboard_reference_image",
            "single_image_to_video",
            "multi_reference_video",
            "native_audio",
        ],
        usage="长时长故事版多参考图生成视频",
        supports_reference_video=True,
        official_capabilities={
            **SEEDANCE_25_OFFICIAL_REFERENCE_LIMITS,
        },
        adapter_capabilities=SEEDANCE_25_ADAPTER_CAPABILITIES,
    ),
    "wan2.7-r2v-2026-06-12": _model_capability(
        provider_prefix="dashscope",
        title="Wan2.7 R2V",
        resolutions=["720p", "1080p"],
        default_resolution="720p",
        durations=_seconds(2, 15),
        audio=True,
        max_reference_images=5,
        metadata=DASHSCOPE_WAN27_VIDEO_CAPABILITY_METADATA,
        supports=[
            "storyboard_reference_image",
            "multi_reference_video",
            "native_audio",
        ],
        usage="故事版参考图生成视频",
        supports_reference_video=True,
        official_capabilities={
            **_official_visual_inputs(
                reference_endpoint="/api/v1/services/aigc/video-generation/video-synthesis",
                max_images=5, max_videos=5, max_references=5,
                first_frame_with_references=True,
                native_frame_controls_aspect_ratio=True,
                storyboard_support="documented",
                source_urls=("https://help.aliyun.com/zh/model-studio/wan-video-to-video-api-reference",),
            ),
            "default_resolution": "1080p",
            "durations_without_reference_video": _seconds(2, 15),
            "durations_with_reference_video": _seconds(2, 10),
            # The local adapter uploads to the configured temporary public URL
            # store before submitting the DashScope request.
            "reference_video_limits": {"min_seconds": 1, "max_seconds": 30, "max_bytes": 100 * 1024 * 1024, "formats": ["mp4", "mov"], "min_width": 240, "max_width": 4096, "min_height": 240, "max_height": 4096, "min_ratio": 0.125, "max_ratio": 8, "transport": "public_url"},
            "max_mixed_reference_materials": 5,
            "prompt_hard_limit_chars": DASHSCOPE_PROMPT_HARD_LIMIT_CHARS,
            "official_prompt_limit_chars": DASHSCOPE_PROMPT_HARD_LIMIT_CHARS,
            "media_prompt_reference_label_style": "图N/视频N",
            "multi_shot_prompt_style": "第N个镜头[时间]",
            "supports_reference_video": True,
            "supports_reference_video_input": True,
            "supports_reference_voice": True,
            **_reference_audio_capabilities(transport="public_url", count=5,
                min_seconds=1, max_seconds=10, total_seconds=50,
                binding="visual_subject", native_frames=True),
            "prompt_guide_source_urls": [
                "https://help.aliyun.com/zh/model-studio/wan-video-to-video-api-reference",
                "https://help.aliyun.com/zh/model-studio/text-to-video-prompt",
            ],
        },
        adapter_capabilities={
            "durations": _seconds(2, 15),
            "supports_reference_video_input": True,
            "supports_reference_voice": True,
            **_reference_audio_capabilities(transport="public_url", count=5,
                min_seconds=1, max_seconds=10, total_seconds=50,
                binding="visual_subject", native_frames=True),
            **DASHSCOPE_WAN27_ADAPTER_CAPABILITIES,
        },
    ),
    "wan3.0-video": _wan3_capability("万相 3.0"),
    "wan3.0-video-prime": _wan3_capability("万相 3.0 高速版"),
    "happyhorse-1.1-r2v": _happyhorse_capability(first_only=False),
    "happyhorse-1.1-i2v": _happyhorse_capability(first_only=True),
    "viduq3-pro": _vidu_native_capability("Vidu Q3 Pro"),
    "viduq3-pro-fast": _vidu_native_capability("Vidu Q3 Pro Fast", first_only=True),
    "viduq3-turbo": _model_capability(
        provider_prefix="vidu",
        title="Vidu Q3 Turbo",
        resolutions=["540p", "720p", "1080p"],
        default_resolution="720p",
        durations=_seconds(3, 16),
        keyframe_durations=_seconds(1, 16),
        audio=True,
        max_reference_images=7,
        metadata=VIDU_Q3_VIDEO_CAPABILITY_METADATA,
        supports=[
            "storyboard_reference_image",
            "single_image_to_video",
            "multi_reference_video",
            "native_audio",
        ],
        usage="故事板分镜图生成视频",
        supports_reference_video=False,
        official_capabilities={
            **_official_visual_inputs(
                reference_endpoint="/ent/v2/reference2video",
                max_images=7, max_references=7,
                first_frame_endpoint="/ent/v2/img2video",
                first_last_frame_endpoint="/ent/v2/start-end2video",
                source_urls=(
                    "https://platform.vidu.cn/docs/reference-to-video",
                    "https://platform.vidu.cn/docs/image-to-video",
                    "https://platform.vidu.cn/docs/start-end-to-video",
                ),
            ),
            "reference2video_durations": _seconds(3, 16),
            "reference2video_max_reference_images": 7,
            "reference2video_image_transport": "images",
            "prompt_hard_limit_chars": VIDU_REFERENCE_PROMPT_HARD_LIMIT_CHARS,
            "official_prompt_limit_chars": VIDU_REFERENCE_PROMPT_HARD_LIMIT_CHARS,
            "subjects_supported_by_api": True,
            "subjects_local_adapter_enabled": False,
            "subjects_max_images_per_subject": 3,
            "subjects_total_input_max": 7,
            "prompt_guide_source_urls": [
                "https://platform.vidu.com/docs/reference-to-video",
                "https://platform.vidu.com/docs/model-map",
                "https://platform.vidu.com/docs/prompt-rec",
                "https://help.aliyun.com/zh/model-studio/vidu-video-generation-prompt-guide",
            ],
        },
        adapter_capabilities={"endpoint": "/reference2video", **VIDU_Q3_ADAPTER_CAPABILITIES},
    ),
    "viduq3": _model_capability(
        provider_prefix="vidu",
        title="Vidu Q3",
        resolutions=["540p", "720p", "1080p"],
        default_resolution="720p",
        durations=_seconds(3, 16),
        audio=True,
        max_reference_images=7,
        metadata=VIDU_Q3_VIDEO_CAPABILITY_METADATA,
        supports=[
            "storyboard_reference_image",
            "multi_reference_video",
            "native_audio",
        ],
        usage="故事板分镜图生成视频",
        supports_reference_video=False,
        official_capabilities={
            **_official_visual_inputs(
                reference_endpoint="/ent/v2/reference2video",
                max_images=7, max_references=7,
                source_urls=("https://platform.vidu.cn/docs/reference-to-video",),
            ),
            "reference2video_durations": _seconds(3, 16),
            "reference2video_max_reference_images": 7,
            "reference2video_image_transport": "images",
            "prompt_hard_limit_chars": VIDU_REFERENCE_PROMPT_HARD_LIMIT_CHARS,
            "official_prompt_limit_chars": VIDU_REFERENCE_PROMPT_HARD_LIMIT_CHARS,
            "subjects_supported_by_api": True,
            "subjects_local_adapter_enabled": False,
            "subjects_max_images_per_subject": 3,
            "subjects_total_input_max": 7,
            "prompt_guide_source_urls": [
                "https://platform.vidu.com/docs/reference-to-video",
                "https://platform.vidu.com/docs/model-map",
                "https://platform.vidu.com/docs/prompt-rec",
                "https://help.aliyun.com/zh/model-studio/vidu-video-generation-prompt-guide",
            ],
        },
        adapter_capabilities={"endpoint": "/reference2video", **VIDU_Q3_ADAPTER_CAPABILITIES},
    ),
    "viduq3-mix": _model_capability(
        provider_prefix="vidu",
        title="Vidu Q3 Mix",
        resolutions=["720p", "1080p"],
        default_resolution="720p",
        durations=_seconds(3, 16),
        audio=True,
        max_reference_images=7,
        metadata=VIDU_Q3_VIDEO_CAPABILITY_METADATA,
        supports=[
            "storyboard_reference_image",
            "multi_reference_video",
            "native_audio",
        ],
        usage="故事板分镜图生成视频",
        supports_reference_video=False,
        official_capabilities={
            **_official_visual_inputs(
                reference_endpoint="/ent/v2/reference2video",
                max_images=7, max_references=7,
                source_urls=("https://platform.vidu.cn/docs/reference-to-video",),
            ),
            "reference2video_durations": _seconds(3, 16),
            "reference2video_max_reference_images": 7,
            "reference2video_image_transport": "images",
            "prompt_hard_limit_chars": VIDU_REFERENCE_PROMPT_HARD_LIMIT_CHARS,
            "official_prompt_limit_chars": VIDU_REFERENCE_PROMPT_HARD_LIMIT_CHARS,
            "subjects_supported_by_api": False,
            "subjects_local_adapter_enabled": False,
            "prompt_guide_source_urls": [
                "https://platform.vidu.com/docs/reference-to-video",
                "https://platform.vidu.com/docs/model-map",
                "https://platform.vidu.com/docs/prompt-rec",
                "https://help.aliyun.com/zh/model-studio/vidu-video-generation-prompt-guide",
            ],
        },
        adapter_capabilities={"endpoint": "/reference2video", **VIDU_Q3_ADAPTER_CAPABILITIES},
    ),
}

QINIU_SEEDANCE_MODELS = {
    "bytedance/doubao-seedance-2-0-260128": "https://apidocs.qnaigc.com/439818050e0.md",
    "bytedance/doubao-seedance-2-0-fast-260128": "https://apidocs.qnaigc.com/470183874e0.md",
    "bytedance/doubao-seedance-2-0-mini-260615": "https://apidocs.qnaigc.com/478283352e0.md",
}

QINIU_VIDU_MODELS = {
    "viduq3-pro": ("pro", "https://apidocs.qnaigc.com/426890494e0.md"),
    "viduq3-turbo": ("turbo", "https://apidocs.qnaigc.com/463733856e0.md"),
    "vidu/viduq3": ("", "https://apidocs.qnaigc.com/463733855e0.md"),
}

QINIU_VEO_MODELS = {
    "veo-3.1-generate-001": "https://apidocs.qnaigc.com/465633343e0.md",
    "veo-3.1-fast-generate-001": "https://apidocs.qnaigc.com/429622273e0.md",
}
# Gemini API retired these preview IDs on 2026-10-22. Keep the exact names
# only to diagnose old configurations; Qiniu's distinct -001 routes remain.
RETIRED_NEWAPI_VEO_MODELS = {"veo-3.1-generate-preview", "veo-3.1-fast-generate-preview"}


def veo_video_capability(model_name: str, *, qiniu: bool) -> dict[str, Any] | None:
    if not qiniu or model_name not in QINIU_VEO_MODELS:
        return None
    source = QINIU_VEO_MODELS[model_name]
    base = "/queue/fal-ai/veo3.1" + ("/fast" if "fast" in model_name else "")
    spec = _model_capability(
        provider_prefix="qiniu-veo", title="Veo 3.1 Fast" if "fast" in model_name else "Veo 3.1",
        resolutions=["720p", "1080p", "4k"], default_resolution="720p", durations=[4, 6, 8],
        audio=True, max_reference_images=0, supports_reference_video=False,
        supports=["single_image_to_video", "native_audio"],
        usage="原生首帧 / 首尾帧生成视频",
        metadata={"capability_source": "official", "capability_source_url": source,
                  "capability_note": "Veo audio always on; 1080p/4k require 8 seconds. Local body guard: 20 MiB.",
                  "prompt_hard_limit_chars": 20000, "official_prompt_limit_chars": 20000},
        official_capabilities=_official_visual_inputs(
            reference_endpoint="", max_images=0, max_references=0,
            first_frame_endpoint=base + "/image-to-video",
            first_last_frame_endpoint=base + "/first-last-frame-to-video",
            native_frame_controls_aspect_ratio=True, source_urls=(source,), verified_on="2026-09-30",
        ),
        adapter_capabilities={"final_prompt_profile": FINAL_VIDEO_PROMPT_PROFILE_VEO_OFFICIAL,
                              "prompt_timing_style": "shot_sequence", "native_ratio_parameter": "omit",
                              "request_body_max_bytes": 20 * 1024 * 1024,
                              "reference_image_limits": {"max_bytes": 20 * 1024 * 1024, "min_side": 720, "allow_alpha": False}},
    )
    spec["aspect_ratios"] = ["16:9", "9:16"]
    spec["duration_resolution_constraints"] = {"720p": [4, 6, 8], "1080p": [8], "4k": [8]}
    spec["metadata"]["duration_resolution_constraints"] = copy.deepcopy(spec["duration_resolution_constraints"])
    return spec


def qiniu_vidu_capability(model_name: str) -> dict[str, Any] | None:
    route = QINIU_VIDU_MODELS.get(model_name)
    if route is None:
        return None
    tier, source = route
    root = "/queue/fal-ai/vidu/q3"
    suffix = f"/{tier}" if tier else ""
    native = bool(tier)
    references = tier != "pro"
    return _model_capability(
        provider_prefix="qiniu-vidu", title=f"Vidu Q3 {tier.title()}".strip(),
        resolutions=["540p", "720p", "1080p"], default_resolution="720p",
        durations=_seconds(3 if references else 1, 16), keyframe_durations=_seconds(1, 16),
        audio=True, max_reference_images=7 if references else 0, supports_reference_video=False,
        supports=(["storyboard_reference_image", "multi_reference_video"] if references else []) + ["single_image_to_video", "native_audio"],
        usage="原生首帧 / 参考图生成视频" if native and references else "原生首帧生成视频" if native else "参考图生成视频",
        metadata={"capability_source": "official", "capability_source_url": source,
                  "prompt_hard_limit_chars": 2000, "official_prompt_limit_chars": 2000,
                  "capability_note": "Qiniu Fal Vidu Q3; audio=true. Frame-pair audio contract unconfirmed, so tail frames are not exposed."},
        official_capabilities=_official_visual_inputs(
            reference_endpoint=f"{root}/reference-to-video{suffix}" if references else "",
            max_images=7 if references else 0, max_references=7 if references else 0,
            first_frame_endpoint=f"{root}/image-to-video{suffix}" if native else "",
            native_frame_controls_aspect_ratio=native, source_urls=(source,), verified_on="2026-09-30",
        ),
        adapter_capabilities={"final_prompt_profile": FINAL_VIDEO_PROMPT_PROFILE_VIDU_Q3_REFERENCE_OFFICIAL,
                              "prompt_timing_style": "shot_sequence", "native_ratio_parameter": "omit",
                              "request_body_max_bytes": 20 * 1024 * 1024,
                              "reference_image_limits": {"max_bytes": 50 * 1024 * 1024, "min_ratio": 0.25, "max_ratio": 4,
                                                         "allow_alpha": False}},
    )

# Reviewed new-api task plugins: doubao 1.2.0 and alibaba 1.4.1.
# A matching model name is insufficient; discovery must declare openai-video,
# or the provider must explicitly use the official newapi-video adapter.
NEWAPI_VIDEO_MODELS = {
    "doubao-seedance-2-0-260128": "doubao",
    "doubao-seedance-2-0-fast-260128": "doubao",
    "doubao-seedance-2-0-mini-260615": "doubao",
    "doubao-seedance-2-5-260628": "doubao",
    "wan3.0-video": "alibaba",
    "wan3.0-video-prime": "alibaba",
}


def _newapi_h3_capability() -> dict[str, Any]:
    source = "https://github.com/QuantumNous/new-api-plugins/blob/main/plugins/tasks/hailuo/1.2.0/plugin.js"
    official = _official_visual_inputs(
        reference_endpoint="/v1/videos", max_images=9, max_videos=3, max_references=12,
        first_frame_endpoint="/v1/videos", first_last_frame_endpoint="/v1/videos",
        native_frame_controls_aspect_ratio=True,
        source_urls=(source, "https://platform.minimax.io/docs/api-reference/video-generation-v2-create"),
        verified_on="2026-09-30",
    )
    official["reference_video_limits"] = {
        "min_seconds": 2, "max_seconds": 15, "total_max_seconds": 15,
        "max_bytes": 50 * 1000 * 1000, "formats": ["mp4", "mov"],
        "video_codecs": ["h264", "hevc"], "audio_codecs": ["aac", "mp3"],
        "min_width": 256, "max_width": 5760, "min_height": 256, "max_height": 5760,
        "min_ratio": 0.4, "max_ratio": 2.5, "min_fps": 23.976, "max_fps": 60,
        "transport": "public_url",
    }
    spec = _model_capability(
        provider_prefix="newapi", title="MiniMax H3", resolutions=["768p", "2k"], default_resolution="768p",
        durations=_seconds(4, 15), audio=True, max_reference_images=9, supports_reference_video=True,
        supports=["storyboard_reference_image", "multi_reference_video", "single_image_to_video", "native_audio"],
        usage="参考图/视频，或原生首帧/首尾帧生成视频",
        metadata={"capability_source": "official", "capability_source_url": source,
                  "prompt_hard_limit_chars": 7000, "official_prompt_limit_chars": 7000,
                  "capability_note": "Native audio; frame and reference modes are exclusive. Local body guard: 20 MiB."},
        official_capabilities=official,
        adapter_capabilities={"final_prompt_profile": FINAL_VIDEO_PROMPT_PROFILE_MINIMAX_H3_OFFICIAL,
                              **_reference_audio_capabilities(transport="public_url"),
                              "prompt_timing_style": "shot_sequence", "native_ratio_parameter": "omit",
                              "request_body_max_bytes": 20 * 1024 * 1024,
                              "reference_image_limits": {"max_bytes": 30 * 1000 * 1000, "min_side": 256,
                                                         "max_side": 5760, "min_ratio": 0.4, "max_ratio": 2.5,
                                                         "allow_alpha": False}},
    )
    spec["aspect_ratios"] = ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
    return spec


def newapi_video_capability(model_name: str) -> dict[str, Any] | None:
    if model_name == "MiniMax-H3":
        return _newapi_h3_capability()
    family = NEWAPI_VIDEO_MODELS.get(model_name)
    if not family:
        return None
    spec = copy.deepcopy(STORYBOARD_VIDEO_MODEL_CAPABILITIES[model_name])
    version = "1.2.0" if family == "doubao" else "1.4.1"
    source = f"https://github.com/QuantumNous/new-api-plugins/blob/main/plugins/tasks/{family}/{version}/plugin.js"
    spec["metadata"]["capability_source_url"] = source
    spec["metadata"]["capability_note"] = "new-api task plugin contract; audio enabled; local body guard: 20 MiB."
    spec["official_capabilities"].pop("request_body_max_bytes", None)
    spec["adapter_capabilities"]["request_body_max_bytes"] = 20 * 1024 * 1024
    spec["adapter_capabilities"]["endpoint"] = "/v1/videos"
    for scope in ("official_capabilities", "adapter_capabilities"):
        for key in ("visual_inputs", "keyframe_visual_inputs"):
            visual = spec[scope].get(key)
            if isinstance(visual, dict):
                visual["source_urls"] = [source]
                for mode in visual["modes"]:
                    mode["endpoint"] = "/v1/videos"
    return spec


def _qiniu_seedance_capability(model_id: str, source_url: str) -> dict[str, Any]:
    # Same Seedance input semantics, but a distinct gateway route and local body guard.
    spec = copy.deepcopy(STORYBOARD_VIDEO_MODEL_CAPABILITIES[model_id.split("/", 1)[1]])
    spec["provider_prefix"] = "qiniu"
    spec["metadata"].update({
        "capability_source_url": source_url,
        "capability_note": "Qiniu native Seedance contract; audio enabled. Local request body guard: 20 MiB.",
    })
    spec["official_capabilities"].pop("request_body_max_bytes", None)
    spec["adapter_capabilities"]["request_body_max_bytes"] = 20 * 1024 * 1024
    spec["adapter_capabilities"]["endpoint"] = "/v3/contents/generations/tasks"
    for scope in ("official_capabilities", "adapter_capabilities"):
        for key in ("visual_inputs", "keyframe_visual_inputs"):
            visual = spec[scope].get(key)
            if not isinstance(visual, dict):
                continue
            visual["source_urls"] = [source_url]
            for mode in visual["modes"]:
                mode["endpoint"] = "/v3/contents/generations/tasks"
    return spec


STORYBOARD_VIDEO_MODEL_CAPABILITIES.update({
    name: _qiniu_seedance_capability(name, source) for name, source in QINIU_SEEDANCE_MODELS.items()
})
_MODEL_KEY_INDEX = {key.casefold(): key for key in STORYBOARD_VIDEO_MODEL_CAPABILITIES}

VIDU_VIDEO_ENDPOINT_MODELS: dict[str, set[str]] = {
    "/text2video": {"viduq3-turbo", "viduq3-pro"},
    "/img2video": {"viduq3-turbo", "viduq3-pro", "viduq3-pro-fast"},
    "/start-end2video": {"viduq3-turbo", "viduq3-pro"},
    "/reference2video": {"viduq3-turbo", "viduq3", "viduq3-mix"},
}
VIDU_VIDEO_ENDPOINT_DURATION_OPTIONS: dict[tuple[str, str], list[int]] = {
    ("viduq3-pro", "/text2video"): _seconds(1, 16),
    ("viduq3-pro", "/img2video"): _seconds(1, 16),
    ("viduq3-pro", "/start-end2video"): _seconds(1, 16),
    ("viduq3-pro-fast", "/img2video"): _seconds(1, 16),
    ("viduq3-turbo", "/text2video"): _seconds(1, 16),
    ("viduq3-turbo", "/img2video"): _seconds(1, 16),
    ("viduq3-turbo", "/start-end2video"): _seconds(1, 16),
    ("viduq3-turbo", "/reference2video"): _seconds(3, 16),
    ("viduq3", "/reference2video"): _seconds(3, 16),
    ("viduq3-mix", "/reference2video"): _seconds(3, 16),
}
VIDU_VIDEO_RESOLUTION_OPTIONS: dict[str, list[str]] = {
    "viduq3-pro": ["540p", "720p", "1080p"],
    "viduq3-pro-fast": ["720p", "1080p"],
    "viduq3-turbo": ["540p", "720p", "1080p"],
    "viduq3": ["540p", "720p", "1080p"],
    "viduq3-mix": ["720p", "1080p"],
}
VIDU_AUDIO_VIDEO_MODELS = {"viduq3-turbo", "viduq3", "viduq3-mix", "viduq3-pro", "viduq3-pro-fast"}


def video_model_capability(model_name: Any) -> dict[str, Any] | None:
    if isinstance(model_name, dict):
        endpoint = model_name.get("endpoint") or model_name.get("generation_endpoint")
        name = str(model_name.get("api_model_id") or model_name.get("id") or model_name.get("modelId") or "").split(":", 1)[-1]
        service = model_name.get("provider_preset_id") or model_name.get("providerPresetId") or model_name.get("preset_id") or model_name.get("presetId")
        if endpoint == "metaso-video" or service == "metaso" or (
            not endpoint and not service and str(model_name.get("id") or model_name.get("modelId") or "") == "metaso:MiniMax-H3"
        ):
            return _minimax_h3_capability(name, deployment="metaso") if name == "MiniMax-H3" else None
        if endpoint == "qiniu-vidu-video":
            return qiniu_vidu_capability(name)
        if endpoint == "qiniu-veo-video":
            return veo_video_capability(name, qiniu=True)
        if endpoint == "newapi-video":
            return newapi_video_capability(name)
        model_name = name
    raw = str(model_name or "").strip()
    autodl = _autodl_h3_capability(raw.split(":", 1)[-1])
    if autodl:
        return autodl
    if raw == "metaso:MiniMax-H3":
        return _minimax_h3_capability("MiniMax-H3", deployment="metaso")
    candidates = [raw]
    if ":" in raw:
        candidates.append(raw.split(":", 1)[1].strip())
    if "/" in raw:
        candidates.append(raw.rsplit("/", 1)[1].strip())
    key = ""
    for candidate in candidates:
        key = _MODEL_KEY_INDEX.get(candidate.casefold()) or ""
        if key:
            break
    if not key:
        return None
    return copy.deepcopy(STORYBOARD_VIDEO_MODEL_CAPABILITIES[key])


def video_model_supports_audio(model_name: Any) -> bool:
    spec = video_model_capability(model_name)
    return bool(spec and spec.get("audio") is True)


def video_model_supports_reference_images(model_name: Any) -> bool:
    spec = video_model_capability(model_name)
    supports = set(spec.get("supports") or []) if spec else set()
    return bool("storyboard_reference_image" in supports or "multi_reference_video" in supports)


def video_model_supports_reference_video(model_name: Any) -> bool:
    spec = video_model_capability(model_name)
    return bool(spec and spec.get("supports_reference_video") is True)


__all__ = (
    "ARK_SEEDANCE_2_VIDEO_CAPABILITY_METADATA",
    "ARK_SEEDANCE_25_VIDEO_CAPABILITY_METADATA",
    "DASHSCOPE_WAN27_VIDEO_CAPABILITY_METADATA",
    "FINAL_VIDEO_PROMPT_PROFILE_DASHSCOPE_WAN27_R2V_OFFICIAL",
    "FINAL_VIDEO_PROMPT_PROFILE_HAPPYHORSE_OFFICIAL",
    "FINAL_VIDEO_PROMPT_PROFILE_MINIMAX_H3_OFFICIAL",
    "FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT",
    "FINAL_VIDEO_PROMPT_PROFILE_VIDU_Q3_REFERENCE_OFFICIAL",
    "VIDU_Q3_VIDEO_CAPABILITY_METADATA",
    "STORYBOARD_VIDEO_SERVICE_IDS",
    "STORYBOARD_VIDEO_MODEL_CAPABILITIES",
    "VIDU_VIDEO_ENDPOINT_MODELS",
    "VIDU_VIDEO_ENDPOINT_DURATION_OPTIONS",
    "VIDU_VIDEO_RESOLUTION_OPTIONS",
    "VIDU_AUDIO_VIDEO_MODELS",
    "video_model_capability",
    "video_model_supports_audio",
    "video_model_supports_reference_images",
    "video_model_supports_reference_video",
)
