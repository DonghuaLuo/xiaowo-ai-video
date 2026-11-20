#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Provider-specific media generation adapters for ai-video.

The public entry points in this module form the shared media-generation
factory used by project_store.  Each provider keeps its own request shape while
the caller receives the same raw-bytes + debug contract.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable

from utils.aspect_size import VIDEO_TIER_SHORT_EDGE, aspect_size, image_size_for_resolution, resolution_to_short_edge
from utils.image_resolution_schema import (
    image_output_size_from_schema,
    image_resolution_schema_for_model,
    normalize_image_resolution_for_schema,
    provider_native_tier_value,
)
from utils.image_pipeline import (
    PROVIDER_IMAGE_INPUT_DEFAULT_MAX_BYTES,
    PROVIDER_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE,
    image_bytes_metadata,
    image_has_provider_png_transparency,
    prepare_provider_image_data_uri,
)
from utils.model_timeouts import (
    MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS,
    MODEL_MEDIA_POLL_TIMEOUT_SECONDS,
    MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS,
)
from utils.video_model_capabilities import (
    QINIU_VEO_MODELS,
    STORYBOARD_VIDEO_SERVICE_IDS,
    VIDU_AUDIO_VIDEO_MODELS,
    VIDU_VIDEO_ENDPOINT_DURATION_OPTIONS,
    VIDU_VIDEO_ENDPOINT_MODELS,
    VIDU_VIDEO_RESOLUTION_OPTIONS,
    video_model_capability,
    video_model_supports_audio,
    video_model_supports_reference_images,
    video_model_supports_reference_video,
)
from utils.video_input_images import prepare_video_request_images
from utils.request_media_archive import with_transport_media
from utils.reference_audio import audio_content, validate_reference_audios

_IMAGE_ENDPOINT_PROVIDER_IDS = {"openai", "ark-seedance", "dashscope", "gemini", "vidu", "grok", "minimax"}
_VIDEO_ENDPOINT_PROVIDER_IDS = STORYBOARD_VIDEO_SERVICE_IDS

_DASHSCOPE_STANDARD_PIXEL_BUDGET = 2048 * 2048
_DASHSCOPE_FOURK_PIXEL_BUDGET = 4096 * 4096
_DASHSCOPE_MAX_RATIO = 8.0
_DASHSCOPE_EDIT_MAX_RATIO = 4.0
_DASHSCOPE_EDIT_MAX_LONG_EDGE = 2048
_DASHSCOPE_IMAGE_ENDPOINT = "/api/v1/services/aigc/multimodal-generation/generation"
_DASHSCOPE_VIDEO_ENDPOINT = "/api/v1/services/aigc/video-generation/video-synthesis"
_DASHSCOPE_PUBLIC_BASE_URL = "https://dashscope.aliyuncs.com"
_DASHSCOPE_OFFICIAL_ENDPOINT_SOURCE_URLS = [
    "https://help.aliyun.com/en/model-studio/what-is-model-studio",
    "https://help.aliyun.com/zh/model-studio/wan-video-to-video-api-reference",
]
_DASHSCOPE_POLL_INTERVAL_SECONDS = 15.0
_VIDU_GLOBAL_BASE_URL = "https://api.vidu.com/ent/v2"
_VIDU_CN_BASE_URL = "https://api.vidu.cn/ent/v2"
_VIDU_DEFAULT_BASE_URL = _VIDU_GLOBAL_BASE_URL
_VIDU_OFFICIAL_ENDPOINT_SOURCE_URLS = [
    "https://platform.vidu.com/docs/reference-to-video",
    "https://platform.vidu.cn/docs/reference-to-video",
]
_VIDU_POLL_INTERVAL_SECONDS = 5.0
_VIDU_IMAGE_POLL_INTERVAL_SECONDS = 3.0
_VIDU_MAX_REFERENCE_IMAGES = 7
_IMAGE_MAX_REFERENCE_IMAGES = 8
_VIDU_PROMPT_MAX_TEXT2VIDEO = 5000
_VIDU_PROMPT_MAX_REFERENCE2VIDEO = 2000
_VIDU_REFERENCE_VIDEO_MIME_TYPES = {"video/mp4", "video/quicktime", "video/x-msvideo"}
_VIDU_REFERENCE_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi"}
_VIDU_PROMPT_MAX_IMAGE = 2000
_VIDU_Q3_MODELS = VIDU_AUDIO_VIDEO_MODELS
_MAX_MEDIA_DOWNLOAD_BYTES = 512 * 1024 * 1024
_MEDIA_DOWNLOAD_CHUNK_BYTES = 1024 * 1024


def _positive_int_value(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _official_capability_source(value: dict[str, Any] | None) -> bool:
    if not isinstance(value, dict):
        return False
    source = str(
        value.get("capability_source")
        or value.get("capabilitySource")
        or value.get("prompt_limit_source")
        or value.get("promptLimitSource")
        or ""
    ).strip().lower()
    return source in {"official", "official_api", "official_doc", "official_docs"}


def _official_prompt_limit_from_source(
    source: dict[str, Any] | None,
    *,
    allow_hard_alias: bool = False,
) -> int | None:
    if not isinstance(source, dict):
        return None
    for key in ("official_prompt_limit_chars", "officialPromptLimitChars"):
        parsed = _positive_int_value(source.get(key))
        if parsed is not None:
            return parsed
    if allow_hard_alias:
        for key in ("prompt_hard_limit_chars", "promptHardLimitChars"):
            parsed = _positive_int_value(source.get(key))
            if parsed is not None:
                return parsed
    return None


def _video_prompt_hard_limit_from_model_like(model: dict[str, Any] | None) -> int | None:
    if not isinstance(model, dict):
        return None
    official = model.get("official_capabilities")
    metadata = model.get("metadata") if isinstance(model.get("metadata"), dict) else {}
    official_limit = _official_prompt_limit_from_source(
        official if isinstance(official, dict) else None,
        allow_hard_alias=True,
    )
    if official_limit is not None:
        return official_limit
    for source in (model, metadata):
        if not _official_capability_source(source):
            continue
        source_limit = _official_prompt_limit_from_source(source, allow_hard_alias=True)
        if source_limit is not None:
            return source_limit
    return None


def video_prompt_char_limit(
    provider_id: str,
    model_name: str,
    *,
    model: dict[str, Any] | None = None,
    strategy: str = "",
) -> int:
    model_candidates = [
        model_name,
        (model or {}).get("id") if isinstance(model, dict) else None,
        (model or {}).get("model_id") if isinstance(model, dict) else None,
        (model or {}).get("modelId") if isinstance(model, dict) else None,
        (model or {}).get("label") if isinstance(model, dict) else None,
    ]
    has_canonical_spec = False
    for candidate in model_candidates:
        spec = video_model_capability(candidate)
        if isinstance(spec, dict):
            has_canonical_spec = True
            if strategy == "native_keyframe_video":
                native_limit = (spec.get("adapter_capabilities") or {}).get("keyframe_prompt_hard_limit_chars")
                if native_limit:
                    return int(native_limit)
        spec_limit = _video_prompt_hard_limit_from_model_like(spec)
        if spec_limit is not None:
            return spec_limit
    if has_canonical_spec:
        return 0
    model_limit = _video_prompt_hard_limit_from_model_like(model)
    if model_limit is not None:
        return model_limit
    return 0


def image_prompt_char_limit(provider_id: str, model_name: str) -> int:
    provider_key = str(provider_id or "").strip().casefold()
    model_key = str(model_name or "").strip().casefold()
    if provider_key == "vidu" or model_key.startswith("vidu"):
        return _VIDU_PROMPT_MAX_IMAGE
    return 0
_VIDU_IMAGE_ASPECT_RATIOS = {
    "viduq2": {"16:9", "9:16", "1:1", "3:4", "4:3", "21:9", "2:3", "3:2", "auto"},
}
_VIDU_IMAGE_RESOLUTIONS = {
    "viduq2": {"1K", "2K", "4K"},
}
_VIDU_DURATION_RULES: dict[tuple[str, str], list[int]] = VIDU_VIDEO_ENDPOINT_DURATION_OPTIONS
_VIDU_ENDPOINT_MODELS: dict[str, set[str]] = VIDU_VIDEO_ENDPOINT_MODELS
_VIDU_ENDPOINTS_WITH_ASPECT_RATIO = {"/text2video", "/reference2video"}
_VIDU_RESOLUTIONS = VIDU_VIDEO_RESOLUTION_OPTIONS
_VIDU_RESOLUTION_RULES: dict[tuple[str, str, int], list[str]] = {}

_GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"

_IMAGE_ENDPOINT_BACKENDS = {
    "openai-images": "openai-compatible",
    "openai-images-generations": "openai-compatible",
    "openai-images-async": "openai-compatible",
    "qiniu-chat-image": "qiniu",
    "qiniu-images": "qiniu-images",
    "qiniu-kling-image": "qiniu-kling-image",
    "ark-seedream": "ark",
    "dashscope-image": "dashscope",
    "gemini-image": "gemini",
    "vidu-image": "vidu",
    "grok-image": "grok",
    "minimax-image": "minimax",
}
_VIDEO_ENDPOINT_BACKENDS = {
    "qiniu-vidu-video": "qiniu-vidu",
    "qiniu-veo-video": "qiniu-veo",
    "qiniu-kling-video": "qiniu-kling",
    "newapi-video": "newapi",
    "grok-video": "grok",
    "ark-seedance": "ark",
    "qiniu-seedance": "qiniu",
    "dashscope-async-video": "dashscope",
    "vidu-video": "vidu",
    "minimax-video": "minimax",
    "metaso-video": "minimax",
    "autodl-comfyui-video": "autodl-comfyui",
}
_TEXT_ENDPOINTS = {"openai-chat", "openai-responses", "gemini-generate", "anthropic-messages"}
_IMAGE_PATTERN = re.compile(
    r"image|dall|img|imagen|flux|seedream|jimeng|qwen-image|wanx-image|wan2\.\d+-image|"
    r"viduq[12](?:[-_].*)?|grok[-_.]?imagine[-_.]?image",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MediaGenerationResponse:
    raw: bytes | None
    debug: dict[str, Any]
    status: str = "completed"
    job_id: str = ""


RequestPreparedCallback = Callable[[dict[str, Any]], None]


def _notify_request_prepared(
    callback: RequestPreparedCallback | None,
    request_info: dict[str, Any],
) -> None:
    if callback is not None:
        try:
            callback(request_info)
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, "allow_request_prepared_abort", False):
                raise
            print(
                f"[model-request-log] 请求日志回调失败，已继续主流程: {exc}",
                file=sys.stderr,
                flush=True,
            )


def _file_request_metadata(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in files:
        data = item.get("data")
        rows.append(
            {
                "field": item.get("field"),
                "filename": item.get("filename"),
                "contentType": item.get("content_type"),
                "byteLength": len(data) if isinstance(data, bytes) else 0,
            }
        )
    return rows


def _file_request_payload(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in files:
        data = item.get("data")
        rows.append(
            {
                "field": item.get("field"),
                "filename": item.get("filename"),
                "contentType": item.get("content_type"),
                "byteLength": len(data) if isinstance(data, bytes) else 0,
                "data": data if isinstance(data, bytes) else None,
            }
        )
    return rows


def _reference_image_limit(max_reference_images: int | None, fallback: int) -> int:
    if max_reference_images is None:
        return fallback
    try:
        value = int(max_reference_images)
    except (TypeError, ValueError):
        return fallback
    return max(0, value)


def _vidu_video_reference_image_limit(model_name: str, endpoint: str) -> int | None:
    normalized_endpoint = str(endpoint or "").strip()
    if normalized_endpoint == "/img2video":
        return 1
    if normalized_endpoint == "/start-end2video":
        return 2
    if normalized_endpoint != "/reference2video":
        return None
    capability = video_model_capability(model_name)
    if not isinstance(capability, dict):
        return None
    endpoint_sources = [
        capability.get("official_capabilities"),
        capability.get("officialCapabilities"),
        capability.get("adapter_capabilities"),
        capability.get("adapterCapabilities"),
        capability,
    ]
    for source in endpoint_sources:
        if not isinstance(source, dict):
            continue
        for key in ("reference2video_max_reference_images", "reference2videoMaxReferenceImages"):
            limit = _positive_int_value(source.get(key))
            if limit is not None:
                return limit
    generic_sources = [
        capability.get("adapter_capabilities"),
        capability.get("adapterCapabilities"),
        capability.get("official_capabilities"),
        capability.get("officialCapabilities"),
        capability,
    ]
    for source in generic_sources:
        if not isinstance(source, dict):
            continue
        for key in ("max_reference_images", "maxReferenceImages"):
            limit = _positive_int_value(source.get(key))
            if limit is not None:
                return limit
    return None


def normalize_media_endpoint(endpoint: Any) -> str:
    return str(endpoint or "").strip().lower().replace("_", "-")


def media_endpoint_type(endpoint: Any) -> str:
    normalized = normalize_media_endpoint(endpoint)
    if normalized in _IMAGE_ENDPOINT_BACKENDS:
        return "image"
    if normalized in _VIDEO_ENDPOINT_BACKENDS:
        return "video"
    if normalized in _TEXT_ENDPOINTS:
        return "text"
    return ""


def endpoint_supports_media_generation(endpoint: Any, media_type: str) -> bool:
    normalized = normalize_media_endpoint(endpoint)
    if media_type == "image":
        return normalized in _IMAGE_ENDPOINT_BACKENDS
    if media_type == "video":
        return normalized in _VIDEO_ENDPOINT_BACKENDS
    return False


def _with_endpoint_debug(response: MediaGenerationResponse, endpoint: str | None) -> MediaGenerationResponse:
    normalized = normalize_media_endpoint(endpoint)
    if not normalized:
        return response
    return MediaGenerationResponse(
        raw=response.raw,
        debug={**response.debug, "endpoint": normalized},
        status=response.status,
        job_id=response.job_id,
    )


def _with_endpoint_debug_and_job_callback(
    response: MediaGenerationResponse,
    endpoint: str | None,
    on_job_submitted: Callable[[MediaGenerationResponse], None] | None,
) -> MediaGenerationResponse:
    response = _with_endpoint_debug(response, endpoint)
    if on_job_submitted and response.job_id:
        on_job_submitted(response)
    return response


def _is_qiniu_provider_context(provider: dict[str, Any] | None) -> bool:
    if not isinstance(provider, dict):
        return False
    try:
        host = urllib.parse.urlsplit(str(provider.get("base_url") or "")).hostname or ""
    except ValueError:
        host = ""
    return host.lower() == "api.qnaigc.com"


def infer_model_endpoint(
    model_id: Any,
    endpoint_format: str = "openai",
    *,
    provider: dict[str, Any] | None = None,
) -> str:
    """Infer an endpoint only when the model/protocol context is unambiguous."""
    model = str(model_id or "").strip()
    lowered = model.lower()
    normalized_format = str(endpoint_format or "openai").strip().lower()
    normalized_format = normalized_format if normalized_format in {"openai", "google"} else "openai"
    # These names are only Qiniu contracts in this codebase.  A private relay
    # may expose the same upstream model name through another protocol.
    if model in QINIU_VEO_MODELS:
        return "qiniu-veo-video" if _is_qiniu_provider_context(provider) else ""
    video_spec = video_model_capability({
        "api_model_id": model,
        "provider_preset_id": _provider_service_id(provider or {}),
    })
    if video_spec:
        provider_prefix = str(video_spec.get("provider_prefix") or "").strip()
        return {
            "ark": "ark-seedance",
            "dashscope": "dashscope-async-video",
            "vidu": "vidu-video",
            "qiniu": "qiniu-seedance",
            "grok": "grok-video",
            "qiniu-kling": "qiniu-kling-video",
            "minimax": "minimax-video",
            "metaso": "metaso-video",
            "autodl-comfyui": "autodl-comfyui-video",
        }.get(provider_prefix, "")
    is_image = bool(_IMAGE_PATTERN.search(model))

    if is_image:
        if "qwen-image" in lowered or "wanx-image" in lowered or ("wan2." in lowered and "image" in lowered):
            return "dashscope-image"
        if "seedream" in lowered:
            return "ark-seedream"
        if "viduq1" in lowered or "viduq2" in lowered:
            return "vidu-image"
        if lowered.startswith(("minimax:image-", "minimax/image-", "image-01", "image-01-live")):
            return "minimax-image"
        if "imagen" in lowered or normalized_format == "google" or "gemini" in lowered:
            return "gemini-image"
        return "openai-images"

    if normalized_format == "google":
        return "gemini-generate"
    return "openai-chat"


def provider_supports_media_generation(
    provider: dict[str, Any],
    media_type: str,
    endpoint: str | None = None,
) -> bool:
    if endpoint:
        return endpoint_supports_media_generation(endpoint, media_type)
    provider_id = _provider_service_id(provider)
    adapter_id = _provider_adapter_id(provider)
    if adapter_id in {"openai-compatible", "gemini-compatible"}:
        return media_type == "image"
    if media_type == "image":
        return provider_id in _IMAGE_ENDPOINT_PROVIDER_IDS
    if media_type == "video":
        return provider_id in _VIDEO_ENDPOINT_PROVIDER_IDS
    return False


def _provider_image_prepare_kwargs(image_input_limits: dict[str, Any] | None) -> dict[str, int]:
    kwargs: dict[str, int] = {
        "max_long_edge": PROVIDER_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE,
        "max_bytes": PROVIDER_IMAGE_INPUT_DEFAULT_MAX_BYTES,
    }
    if not isinstance(image_input_limits, dict):
        return kwargs
    for source_key, target_key in (
        ("max_long_edge", "max_long_edge"),
        ("max_bytes", "max_bytes"),
    ):
        try:
            value = int(image_input_limits.get(source_key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            kwargs[target_key] = value
    return kwargs


def _provider_reference_has_prepared_flag(reference_image: dict[str, Any]) -> bool:
    return bool(
        reference_image.get("providerPrepared")
        or reference_image.get("providerInputPrepared")
        or reference_image.get("transportPrepared")
    )


def _provider_reference_matches_limits(
    reference_image: dict[str, Any],
    *,
    raw: bytes,
    mime: str,
    image_input_limits: dict[str, Any] | None = None,
) -> bool:
    if not _provider_reference_has_prepared_flag(reference_image):
        return False
    if mime not in {"image/jpeg", "image/png"}:
        return False
    if mime == "image/png" and not image_has_provider_png_transparency(raw):
        return False
    prepare_kwargs = _provider_image_prepare_kwargs(image_input_limits)
    max_bytes = int(prepare_kwargs.get("max_bytes") or 0)
    if max_bytes > 0 and len(raw) > max_bytes:
        return False
    max_long_edge = int(prepare_kwargs.get("max_long_edge") or 0)
    if max_long_edge > 0:
        meta = image_bytes_metadata(raw)
        width = int(meta.get("width") or 0)
        height = int(meta.get("height") or 0)
        if width <= 0 or height <= 0 or max(width, height) > max_long_edge:
            return False
    return True


def _normalize_provider_reference_image(
    reference_image: dict[str, Any] | None,
    *,
    image_input_limits: dict[str, Any] | None = None,
    purpose: str = "provider-reference",
) -> dict[str, Any] | None:
    if not isinstance(reference_image, dict):
        return reference_image
    data_url = str(reference_image.get("dataUrl") or "").strip()
    if not data_url:
        return reference_image
    if not data_url.startswith("data:image/"):
        raise RuntimeError("参考图必须是 image dataUrl，不能把非图片数据发送给供应商")
    try:
        raw, mime = _decode_data_url(data_url)
    except Exception as exc:
        raise RuntimeError("参考图 dataUrl 无法解析，不能发送给供应商") from exc
    normalized_mime = str(mime or "").strip().lower()
    if (image_input_limits or {}).get("defer_video_preparation"):
        return {**reference_image, "mimeType": normalized_mime}
    if _provider_reference_matches_limits(
        reference_image,
        raw=raw,
        mime=normalized_mime,
        image_input_limits=image_input_limits,
    ):
        if str(reference_image.get("mimeType") or "").strip().lower() == normalized_mime:
            return reference_image
        return {**reference_image, "mimeType": normalized_mime}
    try:
        prepared_data_url = prepare_provider_image_data_uri(
            raw,
            purpose=purpose,
            preserve_alpha=True,
            **_provider_image_prepare_kwargs(image_input_limits),
        )
        _prepared_raw, prepared_mime = _decode_data_url(prepared_data_url)
    except Exception as exc:
        raise RuntimeError("参考图无法按供应商传输规则转码") from exc
    return {
        **reference_image,
        "dataUrl": prepared_data_url,
        "mimeType": prepared_mime or "image/jpeg",
        "providerPrepared": True,
    }


def _normalize_provider_reference_inputs(
    reference_image: dict[str, Any] | None,
    reference_images: list[dict[str, Any]] | None = None,
    *,
    image_input_limits: dict[str, Any] | None = None,
    purpose: str = "provider-reference",
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
    normalized_reference = _normalize_provider_reference_image(
        reference_image,
        image_input_limits=image_input_limits,
        purpose=purpose,
    )
    if not isinstance(reference_images, list):
        return normalized_reference, reference_images
    normalized_images = [
        _normalize_provider_reference_image(
            row,
            image_input_limits=image_input_limits,
            purpose=f"{purpose}-{index + 1}",
        )
        for index, row in enumerate(reference_images)
        if isinstance(row, dict)
    ]
    return normalized_reference, normalized_images


def _minimax_api_origin(base_url: str) -> str:
    """Resolve official media roots while retaining compatible deployment prefixes."""
    base = _http_url_base(base_url)
    parsed = urllib.parse.urlsplit(base)
    if parsed.hostname in {"api.minimax.cn", "api.minimax.io", "api.minimaxi.com"}:
        # Existing official presets store the Anthropic text base URL.
        return f"{parsed.scheme}://{parsed.netloc}"
    return base.rstrip("/")


def _minimax_api_model_name(model_name: str) -> str:
    raw = str(model_name or "").strip()
    if ":" in raw:
        return raw.split(":", 1)[1].strip()
    if raw.lower().startswith("minimax/"):
        return raw.split("/", 1)[1].strip()
    return raw


def _minimax_reference_image_url(row: dict[str, Any]) -> str:
    for key in ("url", "imageUrl", "image_url", "dataUrl", "data_url"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    media = row.get("media") if isinstance(row.get("media"), dict) else {}
    for key in ("url", "imageUrl", "image_url", "dataUrl", "data_url"):
        value = str(media.get(key) or "").strip()
        if value:
            return value
    return ""


def _minimax_image_generation(
    provider: dict[str, Any], base_url: str, model_name: str, prompt: str,
    *, size: str, resolution: str | None, aspect_ratio: str, reference_image: dict[str, Any] | None,
    reference_images: list[dict[str, Any]] | None,
    max_reference_images: int | None,
    on_request_prepared: RequestPreparedCallback | None,
) -> MediaGenerationResponse:
    model = _minimax_api_model_name(model_name) or "image-01"
    if model not in {"image-01", "image-01-live"}:
        raise RuntimeError("当前 MiniMax 图片模型尚未适配")
    if not prompt.strip() or len(prompt) > 1500:
        raise RuntimeError("MiniMax 图片提示词不能为空且不能超过 1500 字符")
    ratio = str(aspect_ratio or "1:1").strip()
    if model == "image-01-live":
        if ratio not in {"1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16"}:
            raise RuntimeError("MiniMax Image 01 Live 不支持所选画幅")
        if str(resolution or "auto").lower() != "auto":
            raise RuntimeError("MiniMax Image 01 Live 仅支持按画幅自动确定尺寸")
        dimensions = {"aspect_ratio": ratio}
    else:
        match = re.fullmatch(r"(\d+)[xX](\d+)", str(size or "").strip())
        if not match or any(not 512 <= int(value) <= 2048 or int(value) % 8 for value in match.groups()):
            raise RuntimeError("MiniMax Image 01 宽高须为 512 至 2048 之间的 8 的倍数")
        dimensions = {"width": int(match[1]), "height": int(match[2])}
    rows = reference_images if isinstance(reference_images, list) and reference_images else []
    if not rows and reference_image:
        rows = [reference_image]
    limit = _reference_image_limit(max_reference_images, 1)
    if len(rows) > limit:
        raise RuntimeError(f"MiniMax 图片参考图最多支持 {limit} 张")
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        **dimensions,
        "n": 1,
        "response_format": "url",
        "prompt_optimizer": True,
        "aigc_watermark": False,
    }
    if rows:
        subject_reference = []
        for row in rows:
            url = _minimax_reference_image_url(row)
            if not url:
                raise RuntimeError("MiniMax 图片参考图缺少可传输地址")
            subject_type = str(row.get("subjectType") or row.get("subject_type") or "character").strip()
            subject_reference.append({"type": subject_type or "character", "image_file": url})
        payload["subject_reference"] = subject_reference
    url = f"{_minimax_api_origin(base_url)}/v1/image_generation"
    _notify_request_prepared(on_request_prepared, {
        "provider": "minimax", "transport": "http", "method": "POST", "url": url,
        "requestBody": payload,
        "mediaReferences": _reference_media_log_rows(reference_image, reference_images, media_type="image", limit=limit),
    })
    response = _post_json(url, payload, _api_key(provider), timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    image_urls = ((response.get("data") or {}).get("image_urls") if isinstance(response, dict) else None)
    image_url = next((str(value).strip() for value in image_urls or [] if str(value).strip()), "")
    if not image_url:
        raise RuntimeError("MiniMax 图片接口未返回可用图片")
    raw = _decode_data_url(image_url)[0] if image_url.startswith("data:image/") else _download_url(image_url)
    if not raw:
        raise RuntimeError("MiniMax 图片下载结果为空")
    return MediaGenerationResponse(raw=raw, debug={
        "backend": "minimax", "response": response, "request": _redact_payload(payload),
    })


def generate_image_media(
    provider: dict[str, Any],
    provider_id: str,
    base_url: str,
    model_name: str,
    prompt: str,
    *,
    size: str,
    aspect_ratio: str,
    resolution: str | None = None,
    reference_image: dict[str, Any] | None = None,
    reference_images: list[dict[str, Any]] | None = None,
    output_format: str | None = None,
    endpoint: str | None = None,
    max_reference_images: int | None = None,
    image_input_limits: dict[str, Any] | None = None,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    backend = _media_backend_name(provider, provider_id, "image", endpoint=endpoint)
    reference_image, reference_images = _normalize_provider_reference_inputs(
        reference_image,
        reference_images,
        image_input_limits=image_input_limits,
        purpose="image-generation-reference",
    )
    if backend != "openai-compatible":
        rows = reference_images if isinstance(reference_images, list) and reference_images else []
        if not rows and reference_image:
            rows = [reference_image]
        if any(
            isinstance(row, dict)
            and _reference_provider_file_id(row)
            and not _reference_data_url(row)
            for row in rows
        ):
            raise RuntimeError("当前图片供应商不支持仅使用云端图片标识作为参考图，请提供可读取的图片文件内容。")
    if backend == "openai-compatible":
        raw, debug = _openai_compatible_image_generation(
            provider,
            provider_id,
            base_url,
            model_name,
            prompt,
            size=size,
            reference_image=reference_image,
            reference_images=reference_images,
            output_format=output_format,
            max_reference_images=max_reference_images,
            on_request_prepared=on_request_prepared,
            async_mode=normalize_media_endpoint(endpoint) == "openai-images-async",
        )
        return MediaGenerationResponse(raw=raw, debug={**debug, "backend": backend, "endpoint": normalize_media_endpoint(endpoint)})
    if backend == "minimax":
        return _with_endpoint_debug(_minimax_image_generation(
            provider, base_url, model_name, prompt, size=size, resolution=resolution, aspect_ratio=aspect_ratio,
            reference_image=reference_image, reference_images=reference_images,
            max_reference_images=max_reference_images, on_request_prepared=on_request_prepared,
        ), endpoint)
    if backend == "qiniu-kling-image":
        return _with_endpoint_debug(_qiniu_kling_image_generation(
            provider, base_url, model_name, prompt, aspect_ratio=aspect_ratio, resolution=resolution,
            reference_image=reference_image, reference_images=reference_images, on_request_prepared=on_request_prepared,
        ), endpoint)
    if backend == "qiniu-images":
        return _with_endpoint_debug(
            _qiniu_images_generation(
                provider, provider_id, base_url, model_name, prompt, size=size,
                reference_image=reference_image, reference_images=reference_images,
                max_reference_images=max_reference_images, on_request_prepared=on_request_prepared,
            ), endpoint,
        )
    if backend == "qiniu":
        return _with_endpoint_debug(
            _qiniu_image_generation(
                provider, provider_id, base_url, model_name, prompt,
                aspect_ratio=aspect_ratio, reference_image=reference_image,
                reference_images=reference_images, max_reference_images=max_reference_images,
                on_request_prepared=on_request_prepared,
            ), endpoint,
        )
    if backend == "ark":
        return _with_endpoint_debug(
            _ark_image_generation(
                provider,
                base_url,
                model_name,
                prompt,
                size=size,
                resolution=resolution,
                reference_image=reference_image,
                reference_images=reference_images,
                max_reference_images=max_reference_images,
                on_request_prepared=on_request_prepared,
            ),
            endpoint,
        )
    if backend == "dashscope":
        return _with_endpoint_debug(
            _dashscope_image_generation(
                provider,
                base_url,
                model_name,
                prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution or size,
                reference_image=reference_image,
                reference_images=reference_images,
                max_reference_images=max_reference_images,
                on_request_prepared=on_request_prepared,
            ),
            endpoint,
        )
    if backend == "gemini":
        return _with_endpoint_debug(
            _gemini_image_generation(
                provider,
                base_url,
                model_name,
                prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                reference_image=reference_image,
                reference_images=reference_images,
                max_reference_images=max_reference_images,
                on_request_prepared=on_request_prepared,
            ),
            endpoint,
        )
    if backend == "vidu":
        return _with_endpoint_debug(
            _vidu_image_generation(
                provider,
                base_url,
                model_name,
                prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                reference_image=reference_image,
                reference_images=reference_images,
                max_reference_images=max_reference_images,
                on_request_prepared=on_request_prepared,
            ),
            endpoint,
        )
    if backend == "grok":
        return _with_endpoint_debug(
            _grok_image_generation(
                provider,
                model_name,
                prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution or size,
                reference_image=reference_image,
                reference_images=reference_images,
                max_reference_images=max_reference_images,
                on_request_prepared=on_request_prepared,
            ),
            endpoint,
        )
    raise RuntimeError(f"当前图片供应商 {provider_id or 'unknown'} 暂未接入 ai-video 直接出图适配")


def generate_video_media(
    provider: dict[str, Any],
    provider_id: str,
    base_url: str,
    model_name: str,
    prompt: str,
    reference_image: dict[str, Any] | None,
    *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    reference_audios: list[dict[str, Any]] | None = None,
    strategy: str = "",
    replacement_subject: str = "person",
    size: str,
    aspect_ratio: str,
    resolution: str,
    duration_seconds: int,
    generate_audio: bool = True,
    endpoint: str | None = None,
    image_input_limits: dict[str, Any] | None = None,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    # Native sound is mandatory when the selected model supports it.
    generate_audio = video_model_supports_audio(model_name)
    backend = _media_backend_name(provider, provider_id, "video", endpoint=endpoint)
    on_request_prepared = with_transport_media(on_request_prepared, [*(reference_videos or []), *(reference_audios or [])])
    validate_reference_audios(reference_audios or [], {
        "api_model_id": model_name, "endpoint": endpoint, "provider_preset_id": _provider_service_id(provider),
    }, native=strategy == "native_keyframe_video",
        image_count=len(reference_images or ([reference_image] if reference_image else [])),
        video_count=len(reference_videos or []))
    reference_image, reference_images = _normalize_provider_reference_inputs(
        reference_image,
        reference_images,
        image_input_limits={**(image_input_limits or {}), "defer_video_preparation": True},
        purpose="video-generation-reference",
    )
    supports_reference_video = bool(backend in {"ark", "dashscope", "vidu", "qiniu", "newapi", "minimax", "autodl-comfyui"} and video_model_supports_reference_video({
        "api_model_id": model_name, "endpoint": endpoint, "provider_preset_id": _provider_service_id(provider),
    }))
    if reference_videos and not supports_reference_video:
        raise RuntimeError(
            f"当前视频供应商 {provider_id or backend or 'unknown'} 尚未接入参考视频上传，不能执行视频参考编辑。"
        )
    if backend == "autodl-comfyui":
        submitted = submit_video_media_job(
            provider, provider_id, base_url, model_name, prompt, reference_image,
            reference_images=reference_images, **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos, strategy=strategy,
            replacement_subject=replacement_subject,
            size=size, aspect_ratio=aspect_ratio, resolution=resolution, duration_seconds=duration_seconds,
            generate_audio=generate_audio, endpoint=endpoint, on_request_prepared=on_request_prepared,
        )
        return _with_endpoint_debug(_await_video_job(submitted, lambda: poll_video_media_job(
            provider, provider_id, base_url, model_name, submitted.job_id,
            size=size, aspect_ratio=aspect_ratio, resolution=resolution, duration_seconds=duration_seconds,
            endpoint=endpoint,
        )), endpoint)
    if backend in {"qiniu", "grok", "newapi", "qiniu-kling", "qiniu-vidu", "qiniu-veo"}:
        submit, poll = {"qiniu": (_qiniu_video_submit, _qiniu_video_poll), "grok": (_grok_video_submit, _grok_video_poll),
                        "newapi": (_newapi_video_submit, _newapi_video_poll), "qiniu-kling": (_qiniu_kling_video_submit, _qiniu_kling_video_poll),
                        "qiniu-vidu": (_qiniu_vidu_video_submit, _qiniu_vidu_video_poll),
                        "qiniu-veo": (_qiniu_veo_video_submit, _qiniu_veo_video_poll)}[backend]
        submitted = submit(
            provider, base_url, model_name, prompt, reference_image,
            reference_images=reference_images, **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos,
            strategy=strategy, aspect_ratio=aspect_ratio, resolution=resolution,
            duration_seconds=duration_seconds, generate_audio=generate_audio,
            on_request_prepared=on_request_prepared,
        )
        return _with_endpoint_debug(_await_video_job(submitted, lambda: poll(provider, base_url, submitted.job_id)), endpoint)
    if backend == "minimax":
        submitted = _minimax_video_submit(
            provider, base_url, model_name, prompt, reference_image,
            reference_images=reference_images, **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos,
            strategy=strategy, aspect_ratio=aspect_ratio, resolution=resolution,
            duration_seconds=duration_seconds, generate_audio=True,
            on_request_prepared=on_request_prepared,
        )
        return _with_endpoint_debug(_await_video_job(
            submitted, lambda: _minimax_video_poll(provider, base_url, submitted.job_id)
        ), endpoint)
    if backend == "ark":
        return _with_endpoint_debug(
            _ark_video_generation(
                provider,
                base_url,
                model_name,
                prompt,
                reference_image,
                reference_images=reference_images,
                **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos,
                strategy=strategy,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration_seconds=duration_seconds,
                generate_audio=generate_audio,
                on_request_prepared=on_request_prepared,
            ),
            endpoint,
        )
    if backend == "dashscope":
        return _with_endpoint_debug(
            _dashscope_video_generation(
                provider,
                base_url,
                model_name,
                prompt,
                reference_image,
                reference_images=reference_images,
                **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos,
                strategy=strategy,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration_seconds=duration_seconds,
                generate_audio=generate_audio,
                on_request_prepared=on_request_prepared,
            ),
            endpoint,
        )
    if backend == "vidu":
        return _with_endpoint_debug(
            _vidu_video_generation(
                provider,
                base_url,
                model_name,
                prompt,
                reference_image,
                reference_images=reference_images,
                **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos,
                strategy=strategy,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration_seconds=duration_seconds,
                generate_audio=generate_audio,
                on_request_prepared=on_request_prepared,
            ),
            endpoint,
        )
    raise RuntimeError(f"当前视频供应商 {provider_id or 'unknown'} 暂未接入 ai-video 直接出视频适配")


def submit_video_media_job(
    provider: dict[str, Any],
    provider_id: str,
    base_url: str,
    model_name: str,
    prompt: str,
    reference_image: dict[str, Any] | None,
    *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    reference_audios: list[dict[str, Any]] | None = None,
    strategy: str = "",
    replacement_subject: str = "person",
    size: str,
    aspect_ratio: str,
    resolution: str,
    duration_seconds: int,
    generate_audio: bool = True,
    endpoint: str | None = None,
    on_job_submitted: Callable[[MediaGenerationResponse], None] | None = None,
    image_input_limits: dict[str, Any] | None = None,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    """Submit a video job without waiting for provider completion.

    The returned ``job_id`` is the durable resume handle.  Providers that return
    the video synchronously still return ``status='completed'`` with ``raw`` set.
    """

    generate_audio = video_model_supports_audio(model_name)
    backend = _media_backend_name(provider, provider_id, "video", endpoint=endpoint)
    on_request_prepared = with_transport_media(on_request_prepared, [*(reference_videos or []), *(reference_audios or [])])
    validate_reference_audios(reference_audios or [], {
        "api_model_id": model_name, "endpoint": endpoint, "provider_preset_id": _provider_service_id(provider),
    }, native=strategy == "native_keyframe_video",
        image_count=len(reference_images or ([reference_image] if reference_image else [])),
        video_count=len(reference_videos or []))
    reference_image, reference_images = _normalize_provider_reference_inputs(
        reference_image,
        reference_images,
        image_input_limits={**(image_input_limits or {}), "defer_video_preparation": True},
        purpose="video-job-reference",
    )
    supports_reference_video = bool(backend in {"ark", "dashscope", "vidu", "qiniu", "newapi", "minimax", "autodl-comfyui"} and video_model_supports_reference_video({
        "api_model_id": model_name, "endpoint": endpoint, "provider_preset_id": _provider_service_id(provider),
    }))
    if reference_videos and not supports_reference_video:
        raise RuntimeError(
            f"当前视频供应商 {provider_id or backend or 'unknown'} 尚未接入参考视频上传，不能执行视频参考编辑。"
        )
    if backend in {"qiniu", "grok", "newapi", "qiniu-kling", "qiniu-vidu", "qiniu-veo"}:
        submit = {"qiniu": _qiniu_video_submit, "grok": _grok_video_submit, "newapi": _newapi_video_submit,
                  "qiniu-kling": _qiniu_kling_video_submit, "qiniu-vidu": _qiniu_vidu_video_submit,
                  "qiniu-veo": _qiniu_veo_video_submit}[backend]
        return _with_endpoint_debug_and_job_callback(
            submit(
                provider, base_url, model_name, prompt, reference_image,
                reference_images=reference_images, **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos,
                strategy=strategy, aspect_ratio=aspect_ratio, resolution=resolution,
                duration_seconds=duration_seconds, generate_audio=generate_audio,
                on_request_prepared=on_request_prepared,
            ), endpoint, on_job_submitted,
        )
    if backend == "autodl-comfyui":
        from utils.autodl_comfyui import submit_autodl_video

        return _with_endpoint_debug_and_job_callback(submit_autodl_video(
            provider, base_url, model_name, prompt, reference_image,
            reference_images=reference_images, **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos, strategy=strategy,
            aspect_ratio=aspect_ratio, resolution=resolution, duration_seconds=duration_seconds,
            generate_audio=generate_audio, on_request_prepared=on_request_prepared,
            replacement_subject=replacement_subject,
        ), endpoint, on_job_submitted)
    if backend == "minimax":
        return _with_endpoint_debug_and_job_callback(
            _minimax_video_submit(
                provider, base_url, model_name, prompt, reference_image,
                reference_images=reference_images, **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos,
                strategy=strategy, aspect_ratio=aspect_ratio, resolution=resolution,
                duration_seconds=duration_seconds, generate_audio=True,
                on_request_prepared=on_request_prepared,
            ), endpoint, on_job_submitted,
        )
    if backend == "ark":
        return _with_endpoint_debug_and_job_callback(
            _ark_video_submit(
                provider,
                base_url,
                model_name,
                prompt,
                reference_image,
                reference_images=reference_images,
                **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos,
                strategy=strategy,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration_seconds=duration_seconds,
                generate_audio=generate_audio,
                on_request_prepared=on_request_prepared,
            ),
            endpoint,
            on_job_submitted,
        )
    if backend == "dashscope":
        return _with_endpoint_debug_and_job_callback(
            _dashscope_video_submit(
                provider,
                base_url,
                model_name,
                prompt,
                reference_image,
                reference_images=reference_images,
                **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos,
                strategy=strategy,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration_seconds=duration_seconds,
                generate_audio=generate_audio,
                on_request_prepared=on_request_prepared,
            ),
            endpoint,
            on_job_submitted,
        )
    if backend == "vidu":
        return _with_endpoint_debug_and_job_callback(
            _vidu_video_submit(
                provider,
                base_url,
                model_name,
                prompt,
                reference_image,
                reference_images=reference_images,
                **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos,
                strategy=strategy,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration_seconds=duration_seconds,
                generate_audio=generate_audio,
                on_request_prepared=on_request_prepared,
            ),
            endpoint,
            on_job_submitted,
        )
    raise RuntimeError(f"当前视频供应商 {provider_id or 'unknown'} 暂未接入 ai-video 后台视频任务")


def poll_video_media_job(
    provider: dict[str, Any],
    provider_id: str,
    base_url: str,
    model_name: str,
    job_id: str,
    *,
    size: str,
    aspect_ratio: str,
    resolution: str,
    duration_seconds: int,
    endpoint: str | None = None,
) -> MediaGenerationResponse:
    """Poll an existing provider video job once.

    Callers own the retry interval so UI/status calls never block on provider
    polling loops.
    """

    backend = _media_backend_name(provider, provider_id, "video", endpoint=endpoint)
    if not job_id:
        raise RuntimeError("视频任务缺少 provider job id，无法接续轮询")
    if backend == "qiniu":
        return _with_endpoint_debug(_qiniu_video_poll(provider, base_url, job_id), endpoint)
    if backend == "newapi":
        return _with_endpoint_debug(_newapi_video_poll(provider, base_url, job_id), endpoint)
    if backend == "autodl-comfyui":
        from utils.autodl_comfyui import poll_autodl_video

        return _with_endpoint_debug(poll_autodl_video(provider, base_url, job_id), endpoint)
    if backend == "minimax":
        return _with_endpoint_debug(_minimax_video_poll(provider, base_url, job_id), endpoint)
    if backend == "qiniu-kling":
        return _with_endpoint_debug(_qiniu_kling_video_poll(provider, base_url, job_id), endpoint)
    if backend == "qiniu-vidu":
        return _with_endpoint_debug(_qiniu_vidu_video_poll(provider, base_url, job_id), endpoint)
    if backend == "qiniu-veo":
        return _with_endpoint_debug(_qiniu_veo_video_poll(provider, base_url, job_id), endpoint)
    if backend == "grok":
        return _with_endpoint_debug(_grok_video_poll(provider, base_url, job_id), endpoint)
    if backend == "ark":
        return _with_endpoint_debug(_ark_video_poll(provider, base_url, job_id), endpoint)
    if backend == "dashscope":
        return _with_endpoint_debug(_dashscope_video_poll(provider, base_url, job_id, duration_seconds=duration_seconds), endpoint)
    if backend == "vidu":
        return _with_endpoint_debug(_vidu_video_poll(provider, base_url, job_id), endpoint)
    raise RuntimeError(f"当前视频供应商 {provider_id or 'unknown'} 暂不支持视频任务接续")


def cancel_video_media_job(
    provider: dict[str, Any],
    provider_id: str,
    base_url: str,
    job_id: str,
    *,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """Best-effort provider-side video cancellation.

    Local task cancellation must not depend on the provider accepting the remote
    cancel request.  The returned dict is intended for task debug metadata.
    """

    backend = _media_backend_name(provider, provider_id, "video", endpoint=endpoint)
    normalized_endpoint = normalize_media_endpoint(endpoint)
    task_id = str(job_id or "").strip()
    result: dict[str, Any] = {
        "provider": backend or _normalize_provider_id(provider_id) or "unknown",
        "endpoint": normalized_endpoint,
        "jobId": task_id,
        "supported": False,
        "requested": False,
        "cancelled": False,
    }
    if not task_id:
        return {**result, "reason": "missing_provider_job_id"}
    try:
        if backend == "ark":
            ark_result = _ark_video_cancel(provider, base_url, task_id)
            return {**result, **ark_result}
        if backend == "dashscope":
            return {**result, **_dashscope_video_cancel(provider, base_url, task_id)}
        if backend == "vidu":
            return {**result, **_vidu_video_cancel(provider, base_url, task_id)}
        return {**result, "reason": "provider_cancel_not_implemented"}
    except Exception as exc:
        return {**result, "supported": True, "requested": False, "cancelled": False, "error": str(exc)}


def _provider_service_id(provider: dict[str, Any]) -> str:
    if not isinstance(provider, dict):
        return ""
    raw = (
        provider.get("preset_id")
        or provider.get("presetId")
        or provider.get("provider_preset_id")
        or provider.get("providerPresetId")
        or provider.get("id")
        or ""
    )
    return _normalize_provider_id(raw)


def _provider_adapter_id(provider: dict[str, Any]) -> str:
    raw = str(provider.get("adapter_id") or provider.get("adapterId") or "").strip()
    if raw:
        return raw
    service_id = _provider_service_id(provider)
    if service_id == "openai":
        return "openai-compatible"
    if service_id in {"anthropic", "deepseek", "ark-agent-plan"}:
        return "anthropic-compatible"
    if service_id == "gemini":
        return "gemini-compatible"
    return service_id


def _normalize_provider_id(value: Any) -> str:
    legacy = {"openai-image": "openai", "ark": "ark-seedance"}
    raw = str(value or "").strip()
    return legacy.get(raw, raw)


def _media_backend_name(
    provider: dict[str, Any],
    provider_id: str,
    media_type: str,
    *,
    endpoint: str | None = None,
) -> str:
    endpoint_key = normalize_media_endpoint(endpoint)
    if media_type == "image" and endpoint_key:
        return _IMAGE_ENDPOINT_BACKENDS.get(endpoint_key, "")
    if media_type == "video" and endpoint_key:
        return _VIDEO_ENDPOINT_BACKENDS.get(endpoint_key, "")
    service_id = _provider_service_id(provider) or _normalize_provider_id(provider_id)
    adapter_id = _provider_adapter_id(provider)
    if adapter_id == "openai-compatible":
        return "openai-compatible" if media_type == "image" else ""
    if adapter_id == "gemini-compatible":
        return "gemini" if media_type == "image" else ""
    if service_id == "openai":
        return "openai-compatible" if media_type == "image" else ""
    if service_id == "ark-seedance":
        return "ark"
    if service_id in {"dashscope", "vidu"}:
        return service_id
    if service_id in {"minimax", "metaso"}:
        return "minimax"
    if media_type == "video" and service_id == "autodl-comfyui":
        return service_id
    if media_type == "image" and service_id in {"gemini", "grok"}:
        return service_id
    return ""


def _api_key(provider: dict[str, Any]) -> str:
    return str(provider.get("api_key") or provider.get("apiKey") or "").strip()


def _http_url_base(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if base and not re.match(r"^[a-z][a-z0-9+.-]*://", base, flags=re.IGNORECASE):
        base = f"https://{base}"
    return base


def _strip_known_url_suffix(base_url: str, suffixes: tuple[str, ...]) -> tuple[str, str]:
    base = str(base_url or "").strip().rstrip("/")
    lowered = base.casefold()
    for suffix in sorted({item for item in suffixes if item}, key=len, reverse=True):
        normalized = "/" + suffix.strip("/")
        if lowered.endswith(normalized.casefold()):
            return base[: -len(normalized)].rstrip("/"), normalized
    return base, ""


def _openai_compatible_base_url(provider: dict[str, Any], provider_id: str, base_url: str) -> str:
    base = _http_url_base(base_url)
    if _provider_adapter_id(provider) == "openai-compatible":
        if base.endswith("/models"):
            base = base[: -len("/models")].rstrip("/")
        if re.search(r"/v\d+$", base):
            return base
        return f"{base}/v1"
    if provider_id == "openai" and not re.search(r"/v\d+$", base):
        return f"{base}/v1"
    return base


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
    timeout: int = MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:2000] or exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"请求超时（{timeout} 秒）") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason or exc)) from exc
    return json.loads(raw) if raw else {}


def _post_json(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    *,
    timeout: int = MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        data=payload,
        timeout=timeout,
    )


def _multipart_header_value(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")


def _multipart_form_body(
    fields: list[tuple[str, str]],
    files: list[dict[str, Any]],
) -> tuple[bytes, str]:
    boundary = f"----xiaowo-ai-video-{uuid.uuid4().hex}"
    body = bytearray()

    def append(value: str | bytes) -> None:
        body.extend(value if isinstance(value, bytes) else value.encode("utf-8"))

    for name, value in fields:
        append(f"--{boundary}\r\n")
        append(f'Content-Disposition: form-data; name="{_multipart_header_value(name)}"\r\n\r\n')
        append(str(value))
        append("\r\n")

    for item in files:
        data = item.get("data")
        if not isinstance(data, bytes):
            continue
        field_name = str(item.get("field") or "file")
        filename = str(item.get("filename") or "file.bin")
        content_type = str(item.get("content_type") or "application/octet-stream")
        append(f"--{boundary}\r\n")
        append(
            "Content-Disposition: form-data; "
            f'name="{_multipart_header_value(field_name)}"; '
            f'filename="{_multipart_header_value(filename)}"\r\n'
        )
        append(f"Content-Type: {content_type}\r\n\r\n")
        append(data)
        append("\r\n")

    append(f"--{boundary}--\r\n")
    return bytes(body), boundary


def _post_multipart_json(
    url: str,
    fields: list[tuple[str, str]],
    files: list[dict[str, Any]],
    api_key: str,
    *,
    timeout: int = MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    body, boundary = _multipart_form_body(fields, files)
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:2000] or exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"请求超时（{timeout} 秒）") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason or exc)) from exc
    return json.loads(raw) if raw else {}


class _MediaDownloadRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and not _same_http_origin(req.full_url, newurl):
            for key, _ in redirected.header_items():
                if key.lower() in {"authorization", "proxy-authorization", "x-api-key", "cookie"}:
                    redirected.remove_header(key)
        return redirected


def _same_http_origin(left: str, right: str) -> bool:
    def origin(value):
        parsed = urllib.parse.urlsplit(value)
        return parsed.scheme.lower(), parsed.hostname, parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    return origin(left) == origin(right)


def _download_url(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS,
) -> bytes:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    # Authenticated relay content can redirect to a CDN; never forward its Key there.
    open_url = urllib.request.build_opener(_MediaDownloadRedirectHandler()).open if headers else urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as response:
            headers = getattr(response, "headers", {})
            declared_length = headers.get("Content-Length") if hasattr(headers, "get") else None
            # Chunked framing takes precedence over Content-Length.
            if hasattr(headers, "get") and str(headers.get("Transfer-Encoding") or "").lower() == "chunked":
                declared_length = None
            try:
                declared_length = int(declared_length) if declared_length is not None else None
            except (TypeError, ValueError):
                declared_length = None
            if declared_length is not None and declared_length < 0:
                declared_length = None
            if declared_length is not None and declared_length > _MAX_MEDIA_DOWNLOAD_BYTES:
                raise RuntimeError("供应商返回的视频文件超过本地下载大小上限")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(_MEDIA_DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_MEDIA_DOWNLOAD_BYTES:
                    raise RuntimeError("供应商返回的视频文件超过本地下载大小上限")
                chunks.append(chunk)
            if declared_length is not None and total != declared_length:
                raise RuntimeError(f"供应商媒体下载不完整：应接收 {declared_length} 字节，实际接收 {total} 字节")
            return b"".join(chunks)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:2000] or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason or exc)) from exc


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    header, payload = data_url.split(",", 1)
    mime = "application/octet-stream"
    if header.startswith("data:") and ";" in header:
        mime = header[5:].split(";", 1)[0]
    return base64.b64decode(payload), mime


def _reference_data_url(reference_image: dict[str, Any] | None) -> str:
    return str((reference_image or {}).get("dataUrl") or "").strip()


def _reference_provider_file_id(reference_image: dict[str, Any] | None) -> str:
    if not isinstance(reference_image, dict):
        return ""
    for key in (
        "providerFileId",
        "provider_file_id",
        "providerImageId",
        "provider_image_id",
        "providerMediaId",
        "provider_media_id",
        "openaiFileId",
        "openai_file_id",
        "imageFileId",
        "image_file_id",
    ):
        text = str(reference_image.get(key) or "").strip()
        if text:
            return text
    for key in ("fileId", "file_id"):
        text = str(reference_image.get(key) or "").strip()
        if text.startswith("file-"):
            return text
    return ""


def _reference_data_url_mime_type(data_url: str) -> str:
    header = str(data_url or "").split(",", 1)[0]
    if not header.lower().startswith("data:"):
        return ""
    return header[5:].split(";", 1)[0].strip()


def _reference_log_value(reference: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = reference.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
        elif isinstance(value, (int, float, bool)):
            text = str(value)
        else:
            continue
        if not text or text.lower().startswith("data:"):
            continue
        return text[:1000]
    return ""


def _reference_media_log_rows(
    reference_image: dict[str, Any] | None,
    reference_images: list[dict[str, Any]] | None = None,
    *,
    media_type: str = "image",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if limit is not None and limit <= 0:
        return []
    rows = reference_images if isinstance(reference_images, list) and reference_images else []
    if not rows and reference_image:
        rows = [reference_image]
    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        data_url = _reference_data_url(row)
        provider_file_id = _reference_provider_file_id(row)
        source_url = _reference_log_value(
            row,
            "sourceUrl",
            "source_url",
            "publicUrl",
            "public_url",
            "remoteUrl",
            "remote_url",
            "downloadUrl",
            "download_url",
            "url",
        )
        source_path = _reference_log_value(row, "filePath", "file_path", "path", "relativePath", "relative_path", "localPath", "local_path")
        source_id = _reference_log_value(
            row,
            "assetId",
            "asset_id",
            "mediaId",
            "media_id",
            "versionId",
            "version_id",
            "requestedReferenceId",
            "referenceId",
            "reference_id",
            "id",
        )
        key = data_url or provider_file_id or source_url or source_path or source_id
        if not key:
            continue
        if key in seen:
            continue
        item: dict[str, Any] = {
            "mediaIndex": len(values) + 1,
            "mediaKind": media_type,
            "sourceIndex": source_index,
        }
        mime_type = _reference_data_url_mime_type(data_url) or _reference_log_value(row, "mimeType", "mime_type")
        if mime_type:
            item["mimeType"] = mime_type
        if data_url:
            item["originalDataUrlChars"] = len(data_url)
        if provider_file_id:
            item["providerFileId"] = provider_file_id
        if source_url:
            item["sourceUrl"] = source_url
        if source_path:
            item["sourcePath"] = source_path
        if source_id:
            item["sourceId"] = source_id
        source_name = _reference_log_value(row, "name", "fileName", "file_name", "originalName", "displayName", "label")
        if source_name:
            item["sourceName"] = source_name
        source_role = _reference_log_value(row, "role", "referenceRole", "reference_role", "source", "sourceType", "source_type", "purpose")
        if source_role:
            item["sourceRole"] = source_role
        values.append(item)
        seen.add(key)
    if limit is not None and len(values) > limit:
        raise RuntimeError(
            f"参考图超过当前供应商可传输上限：当前 {len(values)} 张，最多 {limit} 张。"
            "已阻断生成，不能裁掉多余参考图后提交不完整资料；请减少参考图，或切换支持更多参考图的模型。"
        )
    return values


def _reference_image_inputs(
    reference_image: dict[str, Any] | None,
    reference_images: list[dict[str, Any]] | None = None,
    *,
    limit: int | None = None,
) -> list[dict[str, str]]:
    if limit is not None and limit <= 0:
        return []
    rows = reference_images if isinstance(reference_images, list) and reference_images else []
    if not rows and reference_image:
        rows = [reference_image]
    values: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        data_url = _reference_data_url(row)
        provider_file_id = _reference_provider_file_id(row)
        if data_url:
            key = f"image_url:{data_url}"
            item = {"image_url": data_url}
        elif provider_file_id:
            key = f"file_id:{provider_file_id}"
            item = {"file_id": provider_file_id}
        else:
            continue
        if key in seen:
            continue
        values.append(item)
        seen.add(key)
    if limit is not None and len(values) > limit:
        raise RuntimeError(
            f"参考图超过当前供应商可传输上限：当前 {len(values)} 张，最多 {limit} 张。"
            "已阻断生成，不能裁掉多余参考图后提交不完整资料；请减少参考图，或切换支持更多参考图的模型。"
        )
    return values


def _reference_data_urls(
    reference_image: dict[str, Any] | None,
    reference_images: list[dict[str, Any]] | None = None,
    *,
    limit: int | None = None,
) -> list[str]:
    if limit is not None and limit <= 0:
        return []
    rows = reference_images if isinstance(reference_images, list) and reference_images else []
    if not rows and reference_image:
        rows = [reference_image]
    values: list[str] = []
    seen: set[str] = set()
    for row in rows:
        data_url = _reference_data_url(row if isinstance(row, dict) else None)
        if not data_url or data_url in seen:
            continue
        values.append(data_url)
        seen.add(data_url)
    if limit is not None and len(values) > limit:
        raise RuntimeError(
            f"参考图超过当前供应商可传输上限：当前 {len(values)} 张，最多 {limit} 张。"
            "已阻断生成，不能裁掉多余参考图后提交不完整资料；请减少参考图，或切换支持更多参考图的模型。"
        )
    return values


def _video_image_role_urls(
    reference_image: dict[str, Any] | None, reference_images: list[dict[str, Any]] | None,
    model_name: str, *, native_required: bool = False, reference_video_count: int = 0,
    capability: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    from utils.frame_references import select_frame_transport
    rows = reference_images or ([reference_image] if reference_image else [])
    result = []
    for row in rows:
        url = _reference_data_url(row)
        if not url:
            raise RuntimeError("视频输入图片缺少可传输地址")
        role = str(row.get("transportRole") or "reference_image")
        if role not in {"reference_image", "first_frame", "last_frame"}:
            raise RuntimeError("视频输入图片用途无效")
        result.append((role, url))
    # Revalidate the exact submitted roles against the same capability table.
    if native_required or any(role != "reference_image" for role, _ in result):
        typed = [{**row, "useNativeFrame": role != "reference_image"} for row, (role, _) in zip(rows, result)]
        selection = select_frame_transport(
            typed, capability if capability is not None else video_model_capability(model_name) or {},
            native_required=native_required, reference_video_count=reference_video_count,
        )
        if any(selection["nativeRoles"].get(i, "reference_image") != role for i, (role, _) in enumerate(result)):
            raise RuntimeError("当前原生帧与参考图组合不受模型支持")
    return result


def _reference_video_urls(
    reference_videos: list[dict[str, Any]] | None = None,
    *,
    limit: int | None = None,
) -> list[str]:
    if limit is not None and limit <= 0:
        return []
    rows = reference_videos if isinstance(reference_videos, list) else []
    values: list[str] = []
    durations: list[float | None] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = str(
            row.get("dataUrl")
            or row.get("data_url")
            or row.get("videoUrl")
            or row.get("video_url")
            or row.get("url")
            or ""
        ).strip()
        if not value or value in seen:
            continue
        parsed = urllib.parse.urlparse(value)
        if not (value.startswith("data:video/") or parsed.scheme in {"http", "https"}):
            raise RuntimeError("参考视频必须是 data:video URL 或可由供应商访问的 http(s) URL。")
        if value.startswith("data:"):
            _raw, mime_type = _decode_data_url(value)
            if str(mime_type or "").strip().lower() not in _VIDU_REFERENCE_VIDEO_MIME_TYPES:
                raise RuntimeError("Vidu 参考视频只支持 mp4、avi、mov 格式。")
        else:
            media = row.get("media") if isinstance(row.get("media"), dict) else {}
            mime_type = str(
                row.get("mimeType")
                or row.get("mime_type")
                or media.get("mimeType")
                or media.get("mime_type")
                or ""
            ).strip().lower()
            if (
                Path(parsed.path).suffix.lower() not in _VIDU_REFERENCE_VIDEO_SUFFIXES
                and mime_type not in _VIDU_REFERENCE_VIDEO_MIME_TYPES
            ):
                raise RuntimeError("Vidu 参考视频 URL 只支持 mp4、avi、mov 格式。")
        media = row.get("media") if isinstance(row.get("media"), dict) else {}
        duration_value = (
            row.get("durationSeconds")
            or row.get("duration_seconds")
            or row.get("duration")
            or media.get("durationSeconds")
            or media.get("duration_seconds")
            or media.get("duration")
        )
        try:
            duration = float(duration_value) if duration_value not in (None, "") else None
        except (TypeError, ValueError):
            duration = None
        values.append(value)
        durations.append(duration)
        seen.add(value)
    if limit is not None and len(values) > limit:
        raise RuntimeError(
            f"参考视频超过当前供应商可传输上限：当前 {len(values)} 个，最多 {limit} 个。"
        )
    max_duration = 8 if len(values) == 1 else 5 if len(values) == 2 else None
    if max_duration is not None and any(
        duration is not None and duration > max_duration
        for duration in durations
    ):
        raise RuntimeError(
            f"Vidu 参考视频时长超出限制：{len(values)} 个参考视频时，每个最多 {max_duration} 秒。"
        )
    return values


def _public_reference_video_urls(reference_videos: list[dict[str, Any]] | None) -> list[str]:
    """Public-URL transports must never receive local file paths."""
    values: list[str] = []
    for row in reference_videos if isinstance(reference_videos, list) else []:
        if not isinstance(row, dict):
            continue
        value = str(row.get("url") or row.get("videoUrl") or row.get("video_url") or "").strip()
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise RuntimeError("参考视频必须是公网 http(s) URL")
        # Two video cards can share a cached URL but have different prompt bindings.
        # Keep each entry so provider numbering stays aligned with the prompt.
        values.append(value)
    return values


def _openai_image_edit_extension(mime: str) -> str:
    normalized = str(mime or "").strip().lower()
    if normalized in {"image/jpeg", "image/jpg"}:
        return "jpg"
    if normalized == "image/webp":
        return "webp"
    return "png"


def _openai_image_edit_content_type(mime: str) -> str:
    normalized = str(mime or "").strip().lower()
    if normalized in {"image/jpeg", "image/jpg"}:
        return "image/jpeg"
    if normalized == "image/webp":
        return "image/webp"
    if normalized == "image/png":
        return "image/png"
    raise RuntimeError(f"OpenAI 图片编辑接口仅支持 png、jpg、webp 参考图，当前图片类型为 {mime or 'unknown'}")


def _openai_image_edit_files(
    reference_image: dict[str, Any] | None,
    reference_images: list[dict[str, Any]] | None = None,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for index, data_url in enumerate(
        _reference_data_urls(reference_image, reference_images, limit=limit),
        start=1,
    ):
        raw, mime = _decode_data_url(data_url)
        content_type = _openai_image_edit_content_type(mime)
        files.append(
            {
                "field": "image[]",
                "filename": f"reference-{index}.{_openai_image_edit_extension(content_type)}",
                "content_type": content_type,
                "data": raw,
            }
        )
    return files


def _openai_compatible_is_official_image_api(provider: dict[str, Any], generation_base_url: str) -> bool:
    if _provider_service_id(provider) == "openai":
        return True
    try:
        host = urllib.parse.urlparse(generation_base_url).netloc.lower()
    except Exception:
        host = ""
    return host == "api.openai.com"


def _reference_image_part_from_data_url(data_url: str) -> dict[str, Any] | None:
    if not data_url:
        return None
    raw, mime = _decode_data_url(data_url)
    return {"inlineData": {"mimeType": mime or "image/jpeg", "data": base64.b64encode(raw).decode("ascii")}}



def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, str) and value.startswith("data:"):
        return "data:*/*;base64,<redacted>"
    return value


def _extract_first_media_url(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("url", "uri", "video_url", "image_url", "output_url", "download_url"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("data", "output", "images", "videos", "generated_videos", "generatedVideos", "creations"):
        value = data.get(key)
        rows = value if isinstance(value, list) else [value]
        for item in rows:
            url = _extract_first_media_url(item) if isinstance(item, dict) else ""
            if url:
                return url
    return ""


def _extract_first_image_bytes(data: Any) -> bytes | None:
    if not isinstance(data, dict):
        return None
    data_url = _extract_first_media_url(data)
    if data_url.startswith("data:image/"):
        raw, _mime = _decode_data_url(data_url)
        return raw
    rows = data.get("data")
    if isinstance(rows, list):
        for item in rows:
            if not isinstance(item, dict):
                continue
            b64 = item.get("b64_json") or item.get("b64Json")
            if isinstance(b64, str) and b64.strip():
                return base64.b64decode(b64)
            url = item.get("url")
            if isinstance(url, str) and url:
                return _download_url(url)
    return _extract_inline_image_bytes(data)


def _extract_inline_image_bytes(data: Any) -> bytes | None:
    if isinstance(data, dict):
        if data.get("thought") is True:
            return None
        inline = data.get("inlineData") or data.get("inline_data")
        if isinstance(inline, dict):
            b64 = inline.get("data")
            if isinstance(b64, str) and b64.strip():
                return base64.b64decode(b64)
        for value in data.values():
            found = _extract_inline_image_bytes(value)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_inline_image_bytes(item)
            if found:
                return found
    return None


def _qiniu_images_generation(
    provider: dict[str, Any], provider_id: str, base_url: str, model_name: str, prompt: str,
    *, size: str, reference_image: dict[str, Any] | None,
    reference_images: list[dict[str, Any]] | None, max_reference_images: int | None,
    on_request_prepared: RequestPreparedCallback | None,
) -> MediaGenerationResponse:
    refs = _reference_image_inputs(reference_image, reference_images, limit=max_reference_images)
    if any("file_id" in item for item in refs):
        raise RuntimeError("七牛云图片接口需要图片内容或可访问的图片地址")
    payload: dict[str, Any] = {"model": model_name, "prompt": prompt, "quality": "high"}
    if refs:
        payload["image"] = [item["image_url"] for item in refs]
    else:
        payload["size"] = size or "auto"
    action = "edits" if refs else "generations"
    url = f"{_openai_compatible_base_url(provider, provider_id, base_url)}/images/{action}"
    _notify_request_prepared(on_request_prepared, {
        "provider": "qiniu", "transport": "http", "method": "POST", "url": url,
        "requestBody": payload,
        "mediaReferences": _reference_media_log_rows(reference_image, reference_images, media_type="image", limit=max_reference_images),
    })
    response = _post_json(url, payload, _api_key(provider), timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    raw = _extract_first_image_bytes(response)
    if not raw:
        raise RuntimeError("七牛云图片接口未返回可用图片")
    return MediaGenerationResponse(raw=raw, debug={"backend": "qiniu-images", "response": response, "request": _redact_payload(payload)})


def _qiniu_image_generation(
    provider: dict[str, Any], provider_id: str, base_url: str, model_name: str, prompt: str,
    *, aspect_ratio: str, reference_image: dict[str, Any] | None,
    reference_images: list[dict[str, Any]] | None, max_reference_images: int | None,
    on_request_prepared: RequestPreparedCallback | None,
) -> MediaGenerationResponse:
    # https://developer.qiniu.com/aitokenapi/13379/real-time-ai-interface-api
    refs = _reference_image_inputs(reference_image, reference_images, limit=max_reference_images)
    if any("file_id" in item for item in refs):
        raise RuntimeError("七牛云图片接口需要可读取的参考图，不能使用其他供应商的文件标识")
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    content.extend({"type": "image_url", "image_url": {"url": item["image_url"]}} for item in refs)
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": aspect_ratio},
        "stream": False,
    }
    url = f"{_openai_compatible_base_url(provider, provider_id, base_url)}/chat/completions"
    _notify_request_prepared(on_request_prepared, {
        "provider": "qiniu", "transport": "http", "method": "POST", "url": url,
        "requestBody": payload,
        "mediaReferences": _reference_media_log_rows(reference_image, reference_images, media_type="image", limit=max_reference_images),
    })
    response = _post_json(url, payload, _api_key(provider), timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    for choice in response.get("choices") or []:
        message = choice.get("message") or {}
        for item in message.get("images") or []:
            value = item.get("image_url")
            image_url = value.get("url") if isinstance(value, dict) else value
            if not isinstance(image_url, str) or not image_url:
                continue
            raw = _decode_data_url(image_url)[0] if image_url.startswith("data:image/") else _download_url(image_url)
            return MediaGenerationResponse(raw=raw, debug={"backend": "qiniu", "response": response, "request": _redact_payload(payload)})
    raise RuntimeError("七牛云图片接口未返回可用图片")


def _openai_compatible_image_generation(
    provider: dict[str, Any],
    provider_id: str,
    base_url: str,
    model_name: str,
    prompt: str,
    *,
    size: str,
    reference_image: dict[str, Any] | None = None,
    reference_images: list[dict[str, Any]] | None = None,
    output_format: str | None = None,
    max_reference_images: int | None = None,
    on_request_prepared: RequestPreparedCallback | None = None,
    async_mode: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    api_key = _api_key(provider)
    generation_base_url = _openai_compatible_base_url(provider, provider_id, base_url)
    edit_endpoint = f"{generation_base_url}/images/edits" + ("/async" if async_mode else "")
    fallback_reference_limit = 16 if str(model_name or "").strip().lower() == "gpt-image-2" else _IMAGE_MAX_REFERENCE_IMAGES
    reference_limit = _reference_image_limit(max_reference_images, fallback_reference_limit)
    image_inputs = _reference_image_inputs(
        reference_image,
        reference_images,
        limit=reference_limit,
    )
    media_references = _reference_media_log_rows(reference_image, reference_images, media_type="image", limit=reference_limit)
    normalized_output_format = "jpeg" if output_format == "jpg" else output_format
    if image_inputs:
        if async_mode or _openai_compatible_is_official_image_api(provider, generation_base_url):
            image_files = _openai_image_edit_files(
                reference_image,
                reference_images,
                limit=reference_limit,
            )
            if len(image_files) < len(image_inputs):
                raise RuntimeError(
                    "OpenAI 图片编辑接口需要上传图片文件内容；当前参考图只有供应商文件 ID，"
                    "不能通过 /images/edits 的 JSON 参数真实消费。请改走 Responses API File ID 链路或提供可读取的图片字节。"
                )
            fields: list[tuple[str, str]] = [
                ("model", model_name),
                ("prompt", prompt),
                ("n", "1"),
                ("size", size),
            ]
            if normalized_output_format:
                fields.append(("output_format", normalized_output_format))
            _notify_request_prepared(
                on_request_prepared,
                {
                    "provider": "openai-compatible",
                    "transport": "http",
                    "method": "POST",
                    "url": edit_endpoint,
                    "contentType": "multipart/form-data",
                    "fields": [{"name": name, "value": value} for name, value in fields],
                    "fileMetadata": _file_request_metadata(image_files),
                    "mediaReferences": media_references,
                    "files": _file_request_payload(image_files),
                },
            )
            try:
                response = _post_multipart_json(
                    edit_endpoint, fields, image_files, api_key,
                    timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                if not async_mode:
                    raise
                raise RuntimeError(f"异步图片提交未确认，请核对供应商记录，勿直接重试：{exc}") from exc
            if async_mode:
                response = _await_async_image(provider, generation_base_url, response, on_request_prepared)
            raw = _extract_first_image_bytes(response)
            if raw:
                request_debug = {
                    "model": model_name,
                    "prompt": prompt[:1200],
                    "n": 1,
                    "size": size,
                    "imageField": "image[]",
                    "referenceImageCount": len(image_files),
                    "reference_transport": "multipart_form_data",
                }
                if normalized_output_format:
                    request_debug["output_format"] = normalized_output_format
                return raw, {"response": response, "request": request_debug}
        else:
            payload: dict[str, Any] = {
                "model": model_name,
                "prompt": prompt,
                "n": 1,
                "size": size,
                "images": image_inputs,
            }
            if normalized_output_format:
                payload["output_format"] = normalized_output_format
            _notify_request_prepared(
                on_request_prepared,
                {
                    "provider": "openai-compatible",
                    "transport": "http",
                    "method": "POST",
                    "url": f"{generation_base_url}/images/edits",
                    "mediaReferences": media_references,
                    "requestBody": payload,
                },
            )
            response = _post_json(
                f"{generation_base_url}/images/edits",
                payload,
                api_key,
                timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS,
            )
            raw = _extract_first_image_bytes(response)
            if raw:
                request_debug = {
                    "model": model_name,
                    "prompt": prompt[:1200],
                    "n": 1,
                    "size": size,
                    "images": _redact_payload(payload["images"]),
                    "reference_transport": (
                        "provider_file_id"
                        if any("file_id" in item for item in image_inputs)
                        else "image_url"
                    ),
                }
                if normalized_output_format:
                    request_debug["output_format"] = normalized_output_format
                return raw, {"response": response, "request": request_debug}
        raise RuntimeError("图片模型未返回可用图片数据")

    endpoint = f"{generation_base_url}/images/generations" + ("/async" if async_mode else "")
    payload: dict[str, Any] = {"model": model_name, "prompt": prompt, "n": 1, "size": size}
    if normalized_output_format:
        payload["output_format"] = normalized_output_format

    _notify_request_prepared(on_request_prepared, {
        "provider": "openai-compatible", "transport": "http", "method": "POST",
        "url": endpoint, "requestBody": payload,
    })
    try:
        response = _post_json(endpoint, payload, api_key, timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    except Exception as exc:
        raise RuntimeError(f"图片提交失败，请核对供应商记录后再重试：{exc}") from exc
    if async_mode:
        response = _await_async_image(provider, generation_base_url, response, on_request_prepared)
    raw = _extract_first_image_bytes(response)
    if not raw:
        raise RuntimeError("图片模型未返回可用图片数据；未自动重复提交生成")
    return raw, {"response": response, "request": _redact_payload({**payload, "prompt": prompt[:1200]})}


def _fal_media_result(provider: dict[str, Any], task_url: str, *, timeout: int) -> dict[str, Any] | None:
    headers = {"Authorization": f"Bearer {_api_key(provider)}"}
    state = _request_json("GET", task_url + "/status", headers=headers, timeout=timeout)
    if not isinstance(state, dict):
        raise RuntimeError("供应商队列返回格式无效")
    if state.get("detail"):
        raise RuntimeError(f"供应商队列任务失败：{state['detail']}")
    status = str(state.get("status") or "").upper()
    if status in {"IN_QUEUE", "IN_PROGRESS"}:
        return None
    if status != "COMPLETED":
        raise RuntimeError(f"供应商队列任务状态无效：{status}")
    result = state.get("result")
    if not isinstance(result, dict):
        result = _request_json("GET", task_url, headers=headers, timeout=timeout)
    if not isinstance(result, dict) or result.get("detail"):
        raise RuntimeError(f"供应商队列任务结果无效：{result}")
    return result


def _await_async_image(
    provider: dict[str, Any], base_url: str, created: dict[str, Any],
    on_request_prepared: RequestPreparedCallback | None,
    *, protocol: str = "openai",
) -> dict[str, Any]:
    task_id = str(created.get("task_id") or created.get("id") or created.get("request_id") or "").strip() if isinstance(created, dict) else ""
    if not task_id:
        raise RuntimeError("异步图片提交未返回任务 ID，请核对供应商记录，勿重复提交")
    url = (f"{base_url}/requests/{urllib.parse.quote(task_id, safe='')}/status" if protocol == "fal"
           else f"{base_url}/images/tasks/{urllib.parse.quote(task_id, safe='')}")
    _notify_request_prepared(on_request_prepared, {"provider": "openai-compatible", "transport": "http",
                                               "method": "GET", "url": url, "taskId": task_id})
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        try:
            timeout = max(1, min(60, int(deadline - time.monotonic())))
            if protocol == "fal":
                payload = _fal_media_result(provider, url.removesuffix("/status"), timeout=timeout)
                result = {"status": "processing"} if payload is None else {"status": "completed", "result": {"data": payload.get("images")}}
            else:
                result = _request_json("GET", url, headers={"Authorization": f"Bearer {_api_key(provider)}"}, timeout=timeout)
        except Exception as exc:
            raise RuntimeError(f"异步图片任务 {task_id} 查询失败，任务可能仍在执行，请核对供应商记录，勿重复提交：{exc}") from exc
        if not isinstance(result, dict):
            raise RuntimeError(f"异步图片任务 {task_id} 返回格式无效，勿重复提交")
        status = str(result.get("status") or "").lower()
        if status == ("succeed" if protocol == "kling" else "completed"):
            payload = result if protocol == "kling" else result.get("result")
            if not isinstance(payload, dict) or not payload.get("data"):
                raise RuntimeError(f"异步图片任务 {task_id} 已完成但未返回图片")
            return {**payload, "task_id": task_id}
        if status == "failed":
            error = result.get("error") or {}
            message = (error.get("message") if isinstance(error, dict) else str(error)) or result.get("status_message")
            raise RuntimeError(f"异步图片任务 {task_id} 失败：{message or '供应商任务失败'}")
        pending = {"submitted", "processing"} if protocol == "kling" else {"processing"}
        if status not in pending:
            raise RuntimeError(f"异步图片任务 {task_id} 返回未知状态，勿重复提交")
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise RuntimeError(f"异步图片任务 {task_id} 查询超时，请核对供应商记录，勿重复提交")


def _qiniu_kling_image_generation(
    provider: dict[str, Any], base_url: str, model_name: str, prompt: str, *,
    aspect_ratio: str, resolution: str | None,
    reference_image: dict[str, Any] | None, reference_images: list[dict[str, Any]] | None,
    on_request_prepared: RequestPreparedCallback | None,
) -> MediaGenerationResponse:
    if model_name not in {"kling-v2-1", "kling-image-o1"}:
        raise RuntimeError("当前七牛可灵图片型号尚未适配")
    if len(prompt) > 2500:
        raise RuntimeError("可灵图片提示词超过 2500 字符，请缩短后重试")
    if aspect_ratio not in {"16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9", "auto"}:
        raise RuntimeError("可灵图片不支持所选画幅")
    omni = model_name == "kling-image-o1"
    images = _reference_image_inputs(reference_image, reference_images, limit=10 if omni else 1)
    urls = []
    for item in images:
        url = item.get("image_url") or ""
        raw, _ = _decode_data_url(url)
        meta = image_bytes_metadata(raw)
        width, height = int(meta.get("width") or 0), int(meta.get("height") or 0)
        if len(raw) > 10 * 1024 * 1024 or min(width, height) < 300 or not 0.4 <= width / height <= 2.5:
            raise RuntimeError("可灵参考图需小于 10MB、宽高至少 300 像素，宽高比介于 1:2.5 与 2.5:1")
        urls.append(url)
    base = _openai_video_base(base_url)
    if omni:
        tier = str(resolution or "1K").upper()
        if tier not in {"1K", "2K"}:
            raise RuntimeError("可灵 O1 图片仅支持 1K / 2K")
        queue_base = base.removesuffix("/v1") + "/queue/fal-ai/kling-image"
        endpoint = queue_base + "/o1"
        body = {"prompt": prompt, "image_urls": urls, "num_images": 1, "resolution": tier, "aspect_ratio": aspect_ratio}
    else:
        endpoint = base + "/images/generations"
        body = {"model": model_name, "prompt": prompt, "n": 1, "aspect_ratio": aspect_ratio}
        if urls:
            body["image"] = urls[0]
    # Persisted job/debug data stays small; only the request archive sees bytes.
    log_body = _redact_payload(body)
    if not omni and urls:
        body["image"] = body["image"].split(",", 1)[1]
    _notify_request_prepared(on_request_prepared, {"provider": "qiniu-kling-image", "transport": "http", "method": "POST", "url": endpoint, "requestBody": body})
    try:
        created = _post_json(endpoint, body, _api_key(provider), timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    except Exception as exc:
        if re.match(r"HTTP 4\d\d:", str(exc)):
            raise
        raise RuntimeError("七牛可灵图片提交结果未确认，请核对供应商记录，勿直接重试") from exc
    result = _await_async_image(provider, queue_base if omni else base, created, on_request_prepared, protocol="fal" if omni else "kling")
    raw = _extract_first_image_bytes(result)
    if not raw:
        raise RuntimeError("七牛可灵图片任务未返回可读取图片")
    return MediaGenerationResponse(raw=raw, debug={"backend": "qiniu-kling-image", "response": result, "request": log_body})


def _video_size(resolution: str | None, aspect_ratio: str) -> tuple[int, int]:
    short = resolution_to_short_edge(resolution, tier_map=VIDEO_TIER_SHORT_EDGE, default_short=720)
    return aspect_size(aspect_ratio, short, round_to=8)


def _is_cancelled_status(raw: Any) -> bool:
    return str(raw or "").strip().lower() in {"cancel", "cancelled", "canceled", "cancelling", "canceling"}


def _dig(payload: Any, path: tuple[str | int, ...]) -> Any:
    current = payload
    for segment in path:
        if isinstance(segment, int):
            if not isinstance(current, list) or segment >= len(current):
                return None
            current = current[segment]
        else:
            if not isinstance(current, dict) or segment not in current:
                return None
            current = current[segment]
    return current


def _grok_image_generation(
    provider: dict[str, Any],
    model_name: str,
    prompt: str,
    *,
    aspect_ratio: str,
    resolution: str | None,
    reference_image: dict[str, Any] | None,
    reference_images: list[dict[str, Any]] | None = None,
    max_reference_images: int | None = None,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    try:
        import xai_sdk
    except Exception as exc:  # pragma: no cover - depends on plugin runtime.
        raise RuntimeError("当前运行时未安装 xai-sdk，无法调用 xAI Grok 图片生成") from exc

    client = xai_sdk.Client(api_key=_api_key(provider))
    kwargs: dict[str, Any] = {"model": model_name, "prompt": prompt, "aspect_ratio": aspect_ratio}
    if resolution:
        kwargs["resolution"] = resolution.lower()
    reference_limit = _reference_image_limit(max_reference_images, _IMAGE_MAX_REFERENCE_IMAGES)
    data_urls = _reference_data_urls(
        reference_image,
        reference_images,
        limit=reference_limit,
    )
    media_references = _reference_media_log_rows(reference_image, reference_images, media_type="image", limit=reference_limit)
    if data_urls:
        kwargs["image_urls"] = data_urls
    _notify_request_prepared(
        on_request_prepared,
        {
            "provider": "grok",
            "transport": "sdk",
            "method": "client.image.sample",
            "mediaReferences": media_references,
            "request": kwargs,
        },
    )
    response = client.image.sample(**kwargs)
    if getattr(response, "respect_moderation", True) is False:
        raise RuntimeError("Grok 图片生成被内容审核拒绝")
    url = str(getattr(response, "url", "") or "")
    if not url:
        raise RuntimeError(f"Grok 图片生成响应缺少 url: {response}")
    return MediaGenerationResponse(
        raw=_download_url(url, timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS),
        debug={"backend": "grok", "request": _redact_payload({**kwargs, "prompt": prompt[:1200]}), "imageUrl": url},
    )


def _ark_image_generation(
    provider: dict[str, Any],
    base_url: str,
    model_name: str,
    prompt: str,
    *,
    size: str,
    resolution: str | None = None,
    reference_image: dict[str, Any] | None = None,
    reference_images: list[dict[str, Any]] | None = None,
    max_reference_images: int | None = None,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    try:
        from volcenginesdkarkruntime import Ark
    except Exception as exc:  # pragma: no cover - depends on plugin runtime.
        raise RuntimeError("当前运行时未安装 volcenginesdkarkruntime，无法调用火山方舟图片生成") from exc

    client = Ark(base_url=base_url, api_key=_api_key(provider))
    requested_size = size if _explicit_image_size(size) else (resolution or size)
    kwargs: dict[str, Any] = {
        "model": model_name,
        "prompt": prompt,
        "size": _ark_seedream_size(model_name, requested_size),
    }
    reference_limit = _reference_image_limit(max_reference_images, _IMAGE_MAX_REFERENCE_IMAGES)
    data_urls = _reference_data_urls(
        reference_image,
        reference_images,
        limit=reference_limit,
    )
    media_references = _reference_media_log_rows(reference_image, reference_images, media_type="image", limit=reference_limit)
    if data_urls:
        kwargs["image"] = data_urls if len(data_urls) > 1 else data_urls[0]
    _notify_request_prepared(
        on_request_prepared,
        {
            "provider": "ark",
            "transport": "sdk",
            "method": "client.images.generate",
            "mediaReferences": media_references,
            "request": kwargs,
        },
    )
    response = client.images.generate(**kwargs)
    data = getattr(response, "data", None) or []
    if not data:
        raise RuntimeError(f"Ark 图片生成响应 data 为空 (model={model_name})")
    raw = _image_bytes_from_sdk_item(data[0])
    return MediaGenerationResponse(
        raw=raw,
        debug={"backend": "ark", "request": _redact_payload({**kwargs, "prompt": prompt[:1200]})},
    )


def _image_bytes_from_sdk_item(item: Any) -> bytes:
    b64 = getattr(item, "b64_json", None)
    if b64:
        return base64.b64decode(b64)
    url = getattr(item, "url", None)
    if url:
        return _download_url(str(url))
    if isinstance(item, dict):
        b64 = item.get("b64_json") or item.get("b64Json")
        if b64:
            return base64.b64decode(str(b64))
        url = item.get("url")
        if url:
            return _download_url(str(url))
    raise RuntimeError("图片生成响应既无 b64_json 也无 url")


def _ark_seedream_size(model_name: str, requested: str) -> str:
    raw = str(requested or "").strip()
    schema = image_resolution_schema_for_model(model_name, provider_id="ark-seedance")
    explicit_size = image_output_size_from_schema(schema, raw, "1:1")
    if explicit_size:
        return explicit_size.replace("*", "x").replace("×", "x")
    normalized = raw.lower()
    supported = tuple(provider_native_tier_value(schema, item) for item in schema.get("native_tiers", []))
    supported = tuple(item for item in supported if item) or _ark_seedream_size_presets(model_name)
    if normalized in supported:
        return normalized
    if normalized == "512px":
        return "1k" if "1k" in supported else supported[0]
    return supported[0] if supported else "2k"


def _ark_seedream_size_presets(model_name: str) -> tuple[str, ...]:
    mid = str(model_name or "").lower()
    if "seedream-3" in mid:
        return ("1k",)
    if "seedream-4-0" in mid or "seedream-4.0" in mid:
        return ("1k", "2k", "4k")
    if "seedream-4-5" in mid or "seedream-4.5" in mid:
        return ("2k", "4k")
    if "seedream-5" in mid or "seedream-5.0" in mid:
        if "pro" in mid:
            return ("1k", "2k")
        return ("2k", "3k", "4k")
    return ("2k", "4k")


def _ark_video_generation(
    provider: dict[str, Any],
    base_url: str,
    model_name: str,
    prompt: str,
    reference_image: dict[str, Any] | None,
    *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    reference_audios: list[dict[str, Any]] | None = None,
    strategy: str = "",
    aspect_ratio: str,
    resolution: str,
    duration_seconds: int,
    generate_audio: bool,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    submitted = _ark_video_submit(
        provider,
        base_url,
        model_name,
        prompt,
        reference_image,
        reference_images=reference_images,
        **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos,
        strategy=strategy,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration_seconds=duration_seconds,
        generate_audio=generate_audio,
        on_request_prepared=on_request_prepared,
    )
    return _await_video_job(submitted, lambda: _ark_video_poll(provider, base_url, submitted.job_id))


def _await_video_job(submitted: MediaGenerationResponse, poll: Callable[[], MediaGenerationResponse]) -> MediaGenerationResponse:
    last = submitted
    for _ in range(90):
        time.sleep(10)
        last = poll()
        if last.raw or last.status == "completed":
            return MediaGenerationResponse(
                raw=last.raw,
                status="completed",
                job_id=submitted.job_id,
                debug={**submitted.debug, **last.debug},
            )
    return MediaGenerationResponse(
        raw=None,
        status="processing",
        job_id=submitted.job_id,
        debug={**submitted.debug, **last.debug, "status": "processing"},
    )


def _seedance_video_request(
    model_name: str,
    prompt: str,
    reference_image: dict[str, Any] | None,
    *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    reference_audios: list[dict[str, Any]] | None = None,
    strategy: str = "",
    aspect_ratio: str,
    resolution: str,
    duration_seconds: int,
    generate_audio: bool,
    prepare_images: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    native_required = strategy == "native_keyframe_video"
    role_urls = _video_image_role_urls(
        reference_image, reference_images, model_name,
        native_required=native_required, reference_video_count=len(reference_videos or []),
    )
    if role_urls:
        supports_references = _ark_model_supports_reference_images(model_name)
        if not supports_references:
            raise RuntimeError("当前 Seedance 视频模型未声明故事版参考图能力，请切换模型。")
        for role, data_url in role_urls:
            content.append({"type": "image_url", "image_url": {"url": data_url}, "role": role})
    video_urls = _ark_reference_video_urls(reference_videos)
    if video_urls and not video_model_supports_reference_video(model_name):
        raise RuntimeError("当前 Seedance 视频模型不支持参考视频输入，请切换模型。")
    for video_url in video_urls:
        content.append(
            {
                "type": "video_url",
                "video_url": {"url": video_url},
                "role": "reference_video",
            }
        )
    content.extend(audio_content(reference_audios or [], model_name, native=native_required,
        image_count=sum(role == "reference_image" for role, _ in role_urls), video_count=len(video_urls)))
    params: dict[str, Any] = {
        "model": model_name,
        "content": content,
        "ratio": "adaptive" if native_required else aspect_ratio,
        "duration": duration_seconds,
        "watermark": False,
    }
    if resolution:
        params["resolution"] = "4k" if str(resolution).lower() == "4k" else resolution
    if _ark_model_supports_audio(model_name):
        params["generate_audio"] = bool(generate_audio)
    if not _ark_is_seedance_2(model_name) and (video_model_capability(model_name) or {}).get("provider_prefix") != "qiniu":
        params["service_tier"] = "default"
    image_preparation = prepare_video_request_images(params, model_name) if prepare_images else {}
    return params, image_preparation


def _ark_video_submit(
    provider: dict[str, Any], base_url: str, model_name: str, prompt: str,
    reference_image: dict[str, Any] | None, *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    reference_audios: list[dict[str, Any]] | None = None, strategy: str = "",
    aspect_ratio: str, resolution: str, duration_seconds: int, generate_audio: bool,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    params, image_preparation = _seedance_video_request(
        model_name, prompt, reference_image, reference_images=reference_images,
        **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos, strategy=strategy, aspect_ratio=aspect_ratio,
        resolution=resolution, duration_seconds=duration_seconds, generate_audio=generate_audio,
    )
    _notify_request_prepared(
        on_request_prepared,
        {
            "provider": "ark",
            "transport": "sdk",
            "method": "client.content_generation.tasks.create",
            "imagePreparation": image_preparation,
            "request": params,
        },
    )
    try:
        from volcenginesdkarkruntime import Ark
    except Exception as exc:  # pragma: no cover - depends on plugin runtime.
        raise RuntimeError("当前运行时未安装 volcenginesdkarkruntime，无法调用火山方舟视频生成") from exc

    client = Ark(base_url=base_url, api_key=_api_key(provider))
    created = client.content_generation.tasks.create(**params)
    task_id = getattr(created, "id", "")
    if not task_id:
        raise RuntimeError(f"Ark 视频任务创建响应缺少 id: {created}")
    return MediaGenerationResponse(
        raw=None,
        status="processing",
        job_id=task_id,
        debug={"backend": "ark", "request": _redact_payload({**params, "prompt": prompt[:1200]}),
               "taskId": task_id, "imagePreparation": image_preparation},
    )


def _openai_video_base(base_url: str) -> str:
    base, _ = _strip_known_url_suffix(_http_url_base(base_url), ("/v1/videos/generations", "/v1/videos", "/v1"))
    return f"{base}/v1"


def _grok_video_submit(
    provider: dict[str, Any], base_url: str, model_name: str, prompt: str,
    reference_image: dict[str, Any] | None, *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None, strategy: str = "",
    aspect_ratio: str, resolution: str, duration_seconds: int, generate_audio: bool,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    from utils.frame_references import select_frame_transport

    spec = video_model_capability(model_name) or {}
    if model_name != "grok-imagine-video-1.5":
        raise RuntimeError("当前 Grok 视频型号尚未适配，已阻止提交")
    if resolution not in spec["resolutions"] or duration_seconds not in spec["durations"]:
        raise RuntimeError("当前 Grok 视频模式不支持所选分辨率或时长")
    rows = reference_images or ([reference_image] if reference_image else [])
    select_frame_transport(rows, spec, native_required=strategy == "native_keyframe_video", reference_video_count=len(reference_videos or []))
    roles = _video_image_role_urls(reference_image, reference_images, model_name, native_required=strategy == "native_keyframe_video")
    body: dict[str, Any] = {"model": model_name, "prompt": prompt, "duration": duration_seconds,
                            "resolution": resolution, "generate_audio": True}
    references = []
    for role, url in roles:
        if role == "reference_image":
            references.append({"url": url})
        else:
            body["image" if role == "first_frame" else "last_frame"] = {"url": url}
    if references:
        body["reference_images"] = references
    if "image" not in body:
        if aspect_ratio not in spec["aspect_ratios"]:
            raise RuntimeError("当前 Grok 视频模型不支持所选画幅")
        body["aspect_ratio"] = aspect_ratio
    preparation = prepare_video_request_images(body, model_name)
    url = f"{_openai_video_base(base_url)}/videos/generations"
    _notify_request_prepared(on_request_prepared, {
        "provider": "grok", "transport": "http", "method": "POST", "url": url,
        "requestBody": body, "imagePreparation": preparation,
    })
    try:
        created = _post_json(url, body, _api_key(provider), timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    except Exception as exc:
        if re.match(r"HTTP 4\d\d:", str(exc)):
            raise
        raise RuntimeError("Grok 视频提交结果未确认，请先核对供应商任务记录，勿直接重试") from exc
    task_id = str(created.get("request_id") or "").strip() if isinstance(created, dict) else ""
    if not task_id:
        raise RuntimeError("Grok 视频提交未返回任务 ID，请检查供应商任务记录，勿重复提交")
    return MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug={
        "backend": "grok", "taskId": task_id, "request": _redact_payload(body), "imagePreparation": preparation,
    })


def _grok_video_poll(provider: dict[str, Any], base_url: str, task_id: str) -> MediaGenerationResponse:
    task_url = f"{_openai_video_base(base_url)}/videos/{urllib.parse.quote(task_id, safe='')}"
    headers = {"Authorization": f"Bearer {_api_key(provider)}"}
    result = _request_json("GET", task_url, headers=headers, timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    if not isinstance(result, dict):
        raise RuntimeError("Grok 视频查询返回格式无效")
    status = str(result.get("status") or "").lower()
    debug = {"backend": "grok", "taskId": task_id, "response": result}
    if status == "pending":
        return MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug=debug)
    if status in {"failed", "expired"}:
        error = result.get("error") or {}
        message = error.get("message") or error.get("code") if isinstance(error, dict) else str(error)
        raise RuntimeError(f"Grok 视频生成失败（{status}）：{message or '供应商任务已终止'}")
    if status != "done":
        raise RuntimeError("Grok 视频查询返回了无法识别的任务状态")
    video = result.get("video")
    if not isinstance(video, dict) or not isinstance(video.get("url"), str) or not video["url"].strip():
        raise RuntimeError("Grok 视频任务已完成，但未返回有效的视频地址")
    if result.get("generate_audio") is False or video.get("generate_audio") is False:
        raise RuntimeError("Grok 返回的视频未生成声音，不符合本任务要求")
    if video.get("respect_moderation") is False:
        raise RuntimeError("Grok 视频未通过供应商内容检查")
    returned = urllib.parse.urlsplit(video["url"])
    content_url = f"{task_url}/content"
    # sub2api can return /v1/... without a reverse proxy's configured path prefix.
    content_paths = {urllib.parse.urlsplit(content_url).path, f"/v1/videos/{urllib.parse.quote(task_id, safe='')}/content"}
    relative = not returned.scheme and not returned.netloc
    protected = returned.path in content_paths and not returned.query and not returned.fragment and (
        relative or _same_http_origin(task_url, video["url"])
    )
    if protected:
        raw = _download_url(content_url, headers=headers, timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS)
    elif returned.scheme in {"https", "http"} and returned.hostname and returned.username is None:
        raw = _download_url(video["url"], timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS)
    else:
        raise RuntimeError("Grok 视频返回了无效或非预期的下载地址")
    if not raw:
        raise RuntimeError("Grok 视频下载结果为空")
    return MediaGenerationResponse(raw=raw, status="completed", job_id=task_id, debug=debug)


def _minimax_video_request(
    model_name: str, prompt: str, reference_image: dict[str, Any] | None, *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    reference_audios: list[dict[str, Any]] | None = None,
    strategy: str = "", aspect_ratio: str, resolution: str,
    duration_seconds: int, provider: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from utils.frame_references import select_frame_transport
    from utils.video_references import validate_reference_videos

    model_context = {"api_model_id": model_name, "provider_preset_id": _provider_service_id(provider or {})}
    spec = video_model_capability(model_context)
    if not spec or spec.get("provider_prefix") not in {"minimax", "metaso"}:
        raise RuntimeError("当前 MiniMax 视频模型尚未适配")
    normalized_resolution = str(resolution or spec.get("default_resolution") or "768p").strip().lower()
    resolution_key = next((item for item in spec["resolutions"] if str(item).lower() == normalized_resolution), "")
    if not resolution_key:
        raise RuntimeError("MiniMax 视频模型不支持所选分辨率")
    if duration_seconds not in spec["durations"]:
        raise RuntimeError("MiniMax 视频模型不支持所选时长")
    if not prompt.strip() or len(prompt) > 7000:
        raise RuntimeError("MiniMax 视频提示词不能为空且不能超过 7000 字符")
    native = strategy == "native_keyframe_video"
    rows = reference_images or ([reference_image] if reference_image else [])
    if rows or reference_videos or native:
        select_frame_transport(
            rows, spec, native_required=native,
            reference_video_count=len(reference_videos or []),
        )
    roles = _video_image_role_urls(
        reference_image, reference_images, model_name,
        native_required=native, reference_video_count=len(reference_videos or []),
        capability=spec,
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    content.extend({"type": "image_url", "image_url": {"url": url}, "role": role} for role, url in roles)
    video_urls = _public_reference_video_urls(reference_videos)
    validate_reference_videos(
        reference_videos or [], model_context,
        image_count=sum(role == "reference_image" for role, _ in roles),
        output_duration=duration_seconds,
    )
    content.extend({"type": "video_url", "video_url": {"url": url}, "role": "reference_video"} for url in video_urls)
    content.extend(audio_content(reference_audios or [], model_context, native=native,
        image_count=sum(role == "reference_image" for role, _ in roles), video_count=len(video_urls)))
    api_model = _minimax_api_model_name(model_name)
    body: dict[str, Any] = {
        "model": api_model,
        "content": content,
        "resolution": str(resolution_key).upper(),
        "duration": duration_seconds,
        "ratio": "adaptive" if native else aspect_ratio,
    }
    if not native and aspect_ratio not in spec.get("aspect_ratios", []):
        raise RuntimeError("MiniMax 视频模型不支持所选画幅")
    preparation = prepare_video_request_images(body, model_name, capability=spec)
    return body, preparation


def _minimax_video_submit(
    provider: dict[str, Any], base_url: str, model_name: str, prompt: str,
    reference_image: dict[str, Any] | None, *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    reference_audios: list[dict[str, Any]] | None = None, strategy: str = "",
    aspect_ratio: str, resolution: str, duration_seconds: int,
    generate_audio: bool = True,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    body, preparation = _minimax_video_request(
        model_name, prompt, reference_image, reference_images=reference_images,
        **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos, strategy=strategy,
        aspect_ratio=aspect_ratio, resolution=resolution,
        duration_seconds=duration_seconds, provider=provider,
    )
    url = f"{_minimax_api_origin(base_url)}/v2/video_generation"
    _notify_request_prepared(on_request_prepared, {
        "provider": _provider_service_id(provider) or "minimax", "transport": "http", "method": "POST", "url": url,
        "requestBody": body, "imagePreparation": preparation,
    })
    try:
        created = _post_json(url, body, _api_key(provider), timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    except Exception as exc:
        if re.match(r"HTTP 4\d\d:", str(exc)):
            raise
        raise RuntimeError("MiniMax 视频提交结果未确认，请核对供应商任务记录，勿直接重试") from exc
    task_id = str(created.get("task_id") or created.get("taskId") or "").strip() if isinstance(created, dict) else ""
    if not task_id:
        raise RuntimeError("MiniMax 视频提交未返回任务 ID，请核对供应商任务记录，勿重复提交")
    return MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug={
        "backend": "minimax", "taskId": task_id,
        "request": _redact_payload(body), "imagePreparation": preparation,
    })


def _minimax_video_poll(provider: dict[str, Any], base_url: str, task_id: str) -> MediaGenerationResponse:
    url = f"{_minimax_api_origin(base_url)}/v2/query/video_generation/{urllib.parse.quote(task_id, safe='')}"
    result = _request_json("GET", url, headers={"Authorization": f"Bearer {_api_key(provider)}"}, timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    task = result.get("task") if isinstance(result, dict) else None
    if not isinstance(task, dict):
        raise RuntimeError("MiniMax 视频查询返回格式无效")
    status = str(task.get("status") or "").lower()
    debug = {"backend": "minimax", "taskId": task_id, "response": result}
    if status in {"queued", "running", "processing", "pending"}:
        return MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug=debug)
    if status in {"failed", "cancelled", "canceled", "expired"}:
        error = task.get("error") or task.get("base_resp") or {}
        message = error.get("status_msg") or error.get("message") or error.get("code") if isinstance(error, dict) else str(error)
        raise RuntimeError(f"MiniMax 视频生成失败（{status}）：{message or '供应商任务已终止'}")
    if status != "succeeded":
        raise RuntimeError("MiniMax 视频查询返回了无法识别的任务状态")
    content = task.get("content") if isinstance(task.get("content"), dict) else {}
    video_url = str(content.get("url") or "").strip()
    if not video_url or urllib.parse.urlsplit(video_url).scheme not in {"http", "https"}:
        raise RuntimeError("MiniMax 视频任务已完成，但未返回有效的视频地址")
    raw = _download_url(video_url, timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS)
    if not raw:
        raise RuntimeError("MiniMax 视频下载结果为空")
    return MediaGenerationResponse(raw=raw, status="completed", job_id=task_id, debug=debug)


def _newapi_video_submit(
    provider: dict[str, Any], base_url: str, model_name: str, prompt: str,
    reference_image: dict[str, Any] | None, *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    reference_audios: list[dict[str, Any]] | None = None, strategy: str = "",
    aspect_ratio: str, resolution: str, duration_seconds: int, generate_audio: bool,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    from utils.frame_references import select_frame_transport
    from utils.video_model_capabilities import NEWAPI_VIDEO_MODELS, RETIRED_NEWAPI_VEO_MODELS, newapi_video_capability

    if model_name in RETIRED_NEWAPI_VEO_MODELS:
        raise RuntimeError("Gemini API 的 Veo 3.1 Preview 已于 2026-10-22 停用，请重新选择可用视频模型")

    spec = newapi_video_capability(model_name)
    if not spec:
        raise RuntimeError("当前中转视频型号的参数协议尚未适配，已阻止提交")
    resolution_key = next((item for item in spec["resolutions"] if str(item).lower() == str(resolution).lower()), resolution)
    durations = spec.get("duration_resolution_constraints", {}).get(resolution_key, spec["durations"])
    if resolution_key not in spec["resolutions"] or duration_seconds not in durations:
        raise RuntimeError("当前中转视频模型不支持所选分辨率或时长")
    rows = reference_images or ([reference_image] if reference_image else [])
    select_frame_transport(rows, spec, native_required=strategy == "native_keyframe_video", reference_video_count=len(reference_videos or []))
    options = dict(reference_images=reference_images, **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos, strategy=strategy,
                   aspect_ratio=aspect_ratio, resolution=resolution, duration_seconds=duration_seconds, generate_audio=True)
    if model_name == "MiniMax-H3":
        from utils.video_references import validate_reference_videos

        if not prompt.strip() or len(prompt) > 7000:
            raise RuntimeError("MiniMax H3 提示词不能为空且不能超过 7000 字符")
        normalized_resolution = str(resolution or "").strip().lower()
        if normalized_resolution not in {str(item).lower() for item in spec["resolutions"]}:
            raise RuntimeError("MiniMax H3 不支持所选分辨率")
        if aspect_ratio not in spec["aspect_ratios"]:
            raise RuntimeError("MiniMax H3 不支持所选画幅")
        native = strategy == "native_keyframe_video"
        roles = _video_image_role_urls(reference_image, reference_images, model_name,
                                      native_required=native, reference_video_count=len(reference_videos or []), capability=spec)
        validate_reference_videos(reference_videos or [], {"api_model_id": model_name, "endpoint": "newapi-video"},
                                  image_count=len(rows), output_duration=duration_seconds)
        content = [{"type": "text", "text": prompt}]
        content.extend({"type": "image_url", "image_url": {"url": url}, "role": role} for role, url in roles)
        content.extend({"type": "video_url", "video_url": {"url": url}, "role": "reference_video"}
                       for url in _public_reference_video_urls(reference_videos))
        content.extend(audio_content(reference_audios or [], {"api_model_id": model_name, "endpoint": "newapi-video"},
            native=native, image_count=sum(role == "reference_image" for role, _ in roles), video_count=len(reference_videos or [])))
        # H3 generates native audio without an audio switch; native frames determine the ratio.
        body = {"model": model_name, "prompt": prompt, "seconds": duration_seconds,
                "metadata": {"content": content, "resolution": normalized_resolution.upper(), "ratio": "adaptive" if native else aspect_ratio}}
    else:
        if NEWAPI_VIDEO_MODELS[model_name] == "doubao":
            native, _ = _seedance_video_request(model_name, prompt, reference_image, **options, prepare_images=False)
        else:
            native = _dashscope_video_request(model_name, prompt, reference_image, **options)
        native.pop("model")
        body = {"model": model_name, "prompt": prompt, "seconds": duration_seconds, "metadata": native}
    preparation = prepare_video_request_images(body, model_name, capability=spec)
    url = f"{_openai_video_base(base_url)}/videos"
    _notify_request_prepared(on_request_prepared, {
        "provider": "newapi", "transport": "http", "method": "POST", "url": url,
        "requestBody": body, "imagePreparation": preparation,
    })
    try:
        created = _post_json(url, body, _api_key(provider), timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    except Exception as exc:
        if re.match(r"HTTP 4\d\d:", str(exc)):
            raise
        raise RuntimeError("中转视频提交结果未确认，请核对供应商任务记录，勿直接重试") from exc
    task_id = str(created.get("id") or "").strip() if isinstance(created, dict) else ""
    if not task_id:
        raise RuntimeError("中转视频提交未返回任务 ID，请核对供应商记录，勿重复提交")
    return MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug={
        "backend": "newapi", "taskId": task_id, "request": _redact_payload(body), "imagePreparation": preparation,
    })


def _newapi_video_poll(provider: dict[str, Any], base_url: str, task_id: str) -> MediaGenerationResponse:
    url = f"{_openai_video_base(base_url)}/videos/{urllib.parse.quote(task_id, safe='')}"
    headers = {"Authorization": f"Bearer {_api_key(provider)}"}
    result = _request_json("GET", url, headers=headers, timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    if not isinstance(result, dict):
        raise RuntimeError("中转视频查询返回格式无效")
    status = str(result.get("status") or "").lower()
    debug = {"backend": "newapi", "taskId": task_id, "response": result}
    if status in {"queued", "pending", "in_progress", "processing", "running", "generating"}:
        return MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug=debug)
    if status in {"failed", "cancelled", "expired"}:
        error = result.get("error") or {}
        message = error.get("message") or error.get("code") if isinstance(error, dict) else str(error)
        raise RuntimeError(f"中转视频生成失败（{status}）：{message or '供应商任务已终止'}")
    if status not in {"completed", "succeeded"}:
        raise RuntimeError("中转视频查询返回了无法识别的任务状态")
    if result.get("generate_audio") is False:
        raise RuntimeError("供应商返回了无声视频，不符合本任务要求")
    # The gateway's content route owns upstream result URLs and authentication.
    raw = _download_url(f"{url}/content", headers=headers, timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS)
    if not raw:
        raise RuntimeError("中转视频下载结果为空")
    return MediaGenerationResponse(raw=raw, status="completed", job_id=task_id, debug=debug)


def _qiniu_kling_video_submit(
    provider: dict[str, Any], base_url: str, model_name: str, prompt: str,
    reference_image: dict[str, Any] | None, *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None, strategy: str = "",
    aspect_ratio: str, resolution: str, duration_seconds: int, generate_audio: bool,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    from utils.frame_references import select_frame_transport
    from utils.video_model_capabilities import QINIU_KLING_MODELS

    spec = video_model_capability(model_name)
    if model_name not in QINIU_KLING_MODELS or not spec:
        raise RuntimeError("当前七牛可灵型号尚未适配")
    if resolution not in spec["resolutions"] or duration_seconds not in spec["durations"]:
        raise RuntimeError("当前七牛可灵模型不支持所选分辨率或时长")
    if len(prompt) > 2500:
        raise RuntimeError("可灵视频提示词超过 2500 字符，请缩短后重试")
    rows = reference_images or ([reference_image] if reference_image else [])
    native = strategy == "native_keyframe_video"
    select_frame_transport(rows, spec, native_required=native, reference_video_count=len(reference_videos or []))
    roles = _video_image_role_urls(reference_image, reference_images, model_name, native_required=native)
    body: dict[str, Any] = {"model": model_name, "prompt": prompt, "seconds": str(duration_seconds),
                            "sound": "on", "mode": "pro" if resolution == "1080p" else "std"}
    if model_name == "kling-v3-omni":
        # Native first frame occupies image_1; references follow in prompt numbering order.
        roles = sorted(roles, key=lambda item: {"first_frame": 0, "last_frame": 1, "reference_image": 2}[item[0]])
        body["image_list"] = [{"image": url, **({"type": "end_frame" if role == "last_frame" else role}
                                             if role != "reference_image" else {})} for role, url in roles]
    else:
        for role, url in roles:
            body["input_reference" if role == "first_frame" else "image_tail"] = url
    if not any(role == "first_frame" for role, _ in roles):
        if aspect_ratio not in spec["aspect_ratios"]:
            raise RuntimeError("当前七牛可灵模型不支持所选画幅")
        width, height = _video_size(resolution, aspect_ratio)
        body["size"] = f"{width}x{height}"
    preparation = prepare_video_request_images(body, model_name)
    log_body = _redact_payload(body)
    # Kling requires bare Base64, not a data-URL prefix.
    for container, key in ([(row, "image") for row in body.get("image_list", [])]
                           + [(body, key) for key in ("input_reference", "image_tail") if key in body]):
        container[key] = container[key].split(",", 1)[1]
    url = f"{_openai_video_base(base_url)}/videos"
    _notify_request_prepared(on_request_prepared, {"provider": "qiniu-kling", "transport": "http", "method": "POST",
                                                "url": url, "requestBody": body, "imagePreparation": preparation})
    try:
        created = _post_json(url, body, _api_key(provider), timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    except Exception as exc:
        if re.match(r"HTTP 4\d\d:", str(exc)):
            raise
        raise RuntimeError("七牛可灵提交结果未确认，请核对供应商任务记录，勿直接重试") from exc
    task_id = str(created.get("id") or "").strip() if isinstance(created, dict) else ""
    if not task_id:
        raise RuntimeError("七牛可灵提交未返回任务 ID，请核对供应商记录，勿重复提交")
    return MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug={
        "backend": "qiniu-kling", "taskId": task_id, "imagePreparation": preparation,
        "request": log_body,
    })


def _qiniu_kling_video_poll(provider: dict[str, Any], base_url: str, task_id: str) -> MediaGenerationResponse:
    url = f"{_openai_video_base(base_url)}/videos/{urllib.parse.quote(task_id, safe='')}"
    result = _request_json("GET", url, headers={"Authorization": f"Bearer {_api_key(provider)}"}, timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    if not isinstance(result, dict):
        raise RuntimeError("七牛可灵视频查询返回格式无效")
    status = str(result.get("status") or "").lower()
    debug = {"backend": "qiniu-kling", "taskId": task_id, "response": result}
    if status in {"initializing", "queued", "in_progress", "downloading", "uploading"}:
        return MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug=debug)
    if status != "completed":
        error = result.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise RuntimeError(f"七牛可灵视频任务未成功（{status}）：{message or '请核对供应商任务记录'}")
    if result.get("sound") == "off":
        raise RuntimeError("七牛可灵返回了无声视频，不符合本任务要求")
    videos = (result.get("task_result") or {}).get("videos") or []
    download_url = videos[0].get("url") if videos and isinstance(videos[0], dict) else ""
    parsed = urllib.parse.urlsplit(download_url or "")
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username is not None:
        raise RuntimeError("七牛可灵未返回有效的视频下载地址")
    raw = _download_url(download_url, timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS)
    if not raw:
        raise RuntimeError("七牛可灵视频下载结果为空")
    return MediaGenerationResponse(raw=raw, status="completed", job_id=task_id, debug=debug)


def _qiniu_vidu_video_submit(
    provider: dict[str, Any], base_url: str, model_name: str, prompt: str,
    reference_image: dict[str, Any] | None, *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None, strategy: str = "",
    aspect_ratio: str, resolution: str, duration_seconds: int, generate_audio: bool,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    from utils.frame_references import select_frame_transport
    from utils.video_model_capabilities import QINIU_VIDU_MODELS, qiniu_vidu_capability

    spec = qiniu_vidu_capability(model_name)
    if not spec:
        raise RuntimeError("当前七牛 Vidu 视频型号尚未适配")
    native = strategy == "native_keyframe_video"
    durations = spec["adapter_capabilities"]["keyframe_visual_inputs"]["durations"] if native else spec["durations"]
    if resolution not in spec["resolutions"] or duration_seconds not in durations:
        raise RuntimeError("当前七牛 Vidu 模式不支持所选分辨率或时长")
    if len(prompt) > 2000:
        raise RuntimeError("七牛 Vidu 视频提示词超过 2000 字符，请缩短后重试")
    rows = reference_images or ([reference_image] if reference_image else [])
    select_frame_transport(rows, spec, native_required=native, reference_video_count=len(reference_videos or []))
    roles = _video_image_role_urls(reference_image, reference_images, model_name, native_required=native, capability=spec)
    tier = QINIU_VIDU_MODELS[model_name][0]
    suffix = f"/{tier}" if tier else ""
    route = f"/queue/fal-ai/vidu/q3/{'image-to-video' if native else 'reference-to-video'}{suffix}"
    body: dict[str, Any] = {"prompt": prompt, "resolution": resolution, "duration": duration_seconds, "audio": True}
    if native:
        body.update(image_url=roles[0][1], is_rec=False)
    else:
        if aspect_ratio not in {"16:9", "9:16", "1:1", "4:3", "3:4"}:
            raise RuntimeError("当前七牛 Vidu 模型不支持所选画幅")
        body.update(reference_image_urls=[url for _, url in roles], aspect_ratio=aspect_ratio)
    preparation = prepare_video_request_images(body, model_name, capability=spec)
    url = _openai_video_base(base_url).removesuffix("/v1") + route
    _notify_request_prepared(on_request_prepared, {"provider": "qiniu-vidu", "transport": "http", "method": "POST",
                                                "url": url, "requestBody": body, "imagePreparation": preparation})
    try:
        created = _post_json(url, body, _api_key(provider), timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    except Exception as exc:
        if re.match(r"HTTP 4\d\d:", str(exc)):
            raise
        raise RuntimeError("七牛 Vidu 提交结果未确认，请核对供应商记录，勿直接重试") from exc
    task_id = str(created.get("request_id") or "").strip() if isinstance(created, dict) else ""
    if not task_id:
        raise RuntimeError("七牛 Vidu 提交未返回任务 ID，请核对供应商记录，勿重复提交")
    return MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug={
        "backend": "qiniu-vidu", "taskId": task_id, "imagePreparation": preparation, "request": _redact_payload(body),
    })


def _qiniu_vidu_video_poll(provider: dict[str, Any], base_url: str, task_id: str) -> MediaGenerationResponse:
    return _qiniu_fal_video_poll(provider, base_url, task_id, family="vidu")


def _qiniu_veo_video_poll(provider: dict[str, Any], base_url: str, task_id: str) -> MediaGenerationResponse:
    return _qiniu_fal_video_poll(provider, base_url, task_id, family="veo3.1")


def _qiniu_fal_video_poll(provider: dict[str, Any], base_url: str, task_id: str, *, family: str) -> MediaGenerationResponse:
    url = _openai_video_base(base_url).removesuffix("/v1") + f"/queue/fal-ai/{family}/requests/{urllib.parse.quote(task_id, safe='')}"
    result = _fal_media_result(provider, url, timeout=MODEL_MEDIA_POLL_TIMEOUT_SECONDS)
    debug = {"backend": "qiniu-vidu" if family == "vidu" else "qiniu-veo", "taskId": task_id}
    if result is None:
        return MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug=debug)
    video = result.get("video") or {}
    if not isinstance(video, dict):
        raise RuntimeError("七牛视频任务返回的结果格式无效")
    if any(row.get(key) is False for row in (result, video) for key in ("audio", "generate_audio")):
        raise RuntimeError("七牛返回无声视频，不符合本任务要求")
    download_url = video.get("url") or ""
    parsed = urllib.parse.urlsplit(download_url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username is not None:
        raise RuntimeError("七牛未返回有效的视频下载地址")
    raw = _download_url(download_url, timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS)
    if not raw:
        raise RuntimeError("七牛视频下载结果为空")
    return MediaGenerationResponse(raw=raw, status="completed", job_id=task_id, debug={**debug, "response": result})


def _qiniu_veo_video_submit(
    provider: dict[str, Any], base_url: str, model_name: str, prompt: str,
    reference_image: dict[str, Any] | None, *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None, strategy: str = "",
    aspect_ratio: str, resolution: str, duration_seconds: int, generate_audio: bool,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    from utils.frame_references import select_frame_transport
    from utils.video_model_capabilities import veo_video_capability

    spec = veo_video_capability(model_name, qiniu=True)
    if not spec:
        raise RuntimeError("当前七牛 Veo 型号尚未适配")
    resolution = str(resolution).strip().lower()
    durations = spec["duration_resolution_constraints"].get(resolution, [])
    if duration_seconds not in durations:
        raise RuntimeError("Veo 的 720p 支持 4/6/8 秒，1080p 和 4K 仅支持 8 秒")
    if len(prompt) > 20000:
        raise RuntimeError("Veo 视频提示词超过 20000 字符，请缩短后重试")
    rows = reference_images or ([reference_image] if reference_image else [])
    select_frame_transport(rows, spec, native_required=strategy == "native_keyframe_video", reference_video_count=len(reference_videos or []))
    roles = dict(_video_image_role_urls(reference_image, reference_images, model_name, native_required=True, capability=spec))
    pair = "last_frame" in roles
    body: dict[str, Any] = {"prompt": prompt, "duration": f"{duration_seconds}s", "resolution": resolution,
                            "generate_audio": True, "auto_fix": False, "aspect_ratio": "auto"}
    if pair:
        body.update(first_frame_url=roles["first_frame"], last_frame_url=roles["last_frame"])
    else:
        body["image_url"] = roles["first_frame"]
    preparation = prepare_video_request_images(body, model_name, capability=spec)
    route = "/queue/fal-ai/veo3.1" + ("/fast" if "fast" in model_name else "")
    route += "/first-last-frame-to-video" if pair else "/image-to-video"
    url = _openai_video_base(base_url).removesuffix("/v1") + route
    _notify_request_prepared(on_request_prepared, {"provider": "qiniu-veo", "transport": "http", "method": "POST",
                                                "url": url, "requestBody": body, "imagePreparation": preparation})
    try:
        created = _post_json(url, body, _api_key(provider), timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    except Exception as exc:
        if re.match(r"HTTP 4\d\d:", str(exc)):
            raise
        raise RuntimeError("七牛 Veo 提交结果未确认，请核对供应商记录，勿直接重试") from exc
    task_id = str(created.get("request_id") or "").strip() if isinstance(created, dict) else ""
    if not task_id:
        raise RuntimeError("七牛 Veo 提交未返回任务 ID，请核对供应商记录，勿重复提交")
    return MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug={
        "backend": "qiniu-veo", "taskId": task_id, "request": _redact_payload(body), "imagePreparation": preparation,
    })


def _qiniu_video_task_url(base_url: str, task_id: str = "") -> str:
    base, _ = _strip_known_url_suffix(_http_url_base(base_url), ("/v1", "/v3", "/v3/contents/generations/tasks"))
    url = f"{base}/v3/contents/generations/tasks"
    return f"{url}/{urllib.parse.quote(task_id, safe='')}" if task_id else url


def _qiniu_video_submit(
    provider: dict[str, Any], base_url: str, model_name: str, prompt: str,
    reference_image: dict[str, Any] | None, *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    reference_audios: list[dict[str, Any]] | None = None, strategy: str = "",
    aspect_ratio: str, resolution: str, duration_seconds: int, generate_audio: bool,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    from utils.frame_references import select_frame_transport
    from utils.video_model_capabilities import QINIU_SEEDANCE_MODELS

    if model_name not in QINIU_SEEDANCE_MODELS:
        raise RuntimeError("当前七牛云视频模型尚未适配，已阻止提交")
    spec = video_model_capability(model_name) or {}
    if str(resolution).lower() not in {item.lower() for item in spec["resolutions"]}:
        raise RuntimeError("当前七牛云视频模型不支持所选分辨率")
    if duration_seconds not in spec["durations"]:
        raise RuntimeError("当前七牛云视频模型不支持所选时长")
    rows = reference_images or ([reference_image] if reference_image else [])
    select_frame_transport(rows, spec, native_required=strategy == "native_keyframe_video", reference_video_count=len(reference_videos or []))
    params, preparation = _seedance_video_request(
        model_name, prompt, reference_image, reference_images=reference_images,
        **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos, strategy=strategy, aspect_ratio=aspect_ratio,
        resolution=resolution, duration_seconds=duration_seconds, generate_audio=True,
    )
    url = _qiniu_video_task_url(base_url)
    _notify_request_prepared(on_request_prepared, {
        "provider": "qiniu", "transport": "http", "method": "POST", "url": url,
        "requestBody": params, "imagePreparation": preparation,
    })
    try:
        created = _request_json("POST", url, headers={
            "Authorization": f"Bearer {_api_key(provider)}", "X-Qiniu-Video-API-Format": "origin",
        }, data=params, timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    except Exception as exc:
        if re.match(r"HTTP 4\d\d:", str(exc)):
            raise
        raise RuntimeError("七牛云视频提交结果未确认，请先核对供应商任务记录，勿直接重试") from exc
    task_id = str(created.get("id") or "").strip()
    if not task_id:
        raise RuntimeError("七牛云视频提交未返回任务 ID，请检查供应商任务记录，勿重复提交")
    return MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug={
        "backend": "qiniu", "taskId": task_id, "request": _redact_payload(params), "imagePreparation": preparation,
    })


def _qiniu_video_poll(provider: dict[str, Any], base_url: str, task_id: str) -> MediaGenerationResponse:
    result = _request_json("GET", _qiniu_video_task_url(base_url, task_id), headers={
        "Authorization": f"Bearer {_api_key(provider)}", "X-Qiniu-Video-API-Format": "origin",
    }, timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    status = str(result.get("status") or "").lower()
    debug = {"backend": "qiniu", "taskId": task_id, "response": result}
    if status == "succeeded":
        url = str((result.get("content") or {}).get("video_url") or "")
        if urllib.parse.urlsplit(url).scheme not in {"http", "https"}:
            raise RuntimeError("七牛云视频任务已完成，但未返回有效的视频地址")
        if result.get("generate_audio") is False:
            raise RuntimeError("七牛云返回的视频未生成声音，不符合本任务要求")
        raw = _download_url(url, timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS)
        if not raw:
            raise RuntimeError("七牛云视频下载结果为空")
        return MediaGenerationResponse(raw=raw, status="completed", job_id=task_id, debug=debug)
    if status in {"failed", "expired", "cancelled", "canceled"}:
        error = result.get("error") or {}
        message = error.get("message") or error.get("code") if isinstance(error, dict) else str(error)
        raise RuntimeError(f"七牛云视频生成失败（{status}）：{message or '供应商任务已终止'}")
    if status not in {"queued", "running", "pending", "processing"}:
        raise RuntimeError("七牛云视频查询返回了无法识别的任务状态")
    return MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug=debug)


def _ark_video_poll(provider: dict[str, Any], base_url: str, task_id: str) -> MediaGenerationResponse:
    try:
        from volcenginesdkarkruntime import Ark
    except Exception as exc:  # pragma: no cover - depends on plugin runtime.
        raise RuntimeError("当前运行时未安装 volcenginesdkarkruntime，无法调用火山方舟视频生成") from exc

    client = Ark(base_url=base_url, api_key=_api_key(provider))
    last = client.content_generation.tasks.get(task_id=task_id)
    status = str(getattr(last, "status", "") or "").lower()
    if status == "succeeded":
        url = getattr(getattr(last, "content", None), "video_url", None)
        if not url:
            raise RuntimeError(f"Ark 视频任务完成但缺少 video_url: {last}")
        raw = _download_url(str(url), timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS)
        return MediaGenerationResponse(
            raw=raw,
            status="completed",
            job_id=task_id,
            debug={"backend": "ark", "response": str(last), "taskId": task_id, "videoUrl": url},
        )
    if status in {"failed", "expired", "cancelled", "canceled"}:
        raise RuntimeError(f"Ark 视频生成失败(status={status}): {getattr(last, 'error', None) or last}")
    return MediaGenerationResponse(
        raw=None,
        status="processing",
        job_id=task_id,
        debug={"backend": "ark", "response": str(last), "taskId": task_id, "status": status or "processing"},
    )


def _ark_video_cancel(provider: dict[str, Any], base_url: str, task_id: str) -> dict[str, Any]:
    try:
        from volcenginesdkarkruntime import Ark
    except Exception as exc:  # pragma: no cover - depends on plugin runtime.
        raise RuntimeError("当前运行时未安装 volcenginesdkarkruntime，无法取消火山方舟视频任务") from exc

    client = Ark(base_url=base_url, api_key=_api_key(provider))
    tasks = getattr(getattr(client, "content_generation", None), "tasks", None)
    if tasks is None:
        return {"supported": False, "cancelled": False, "reason": "ark_tasks_client_missing"}
    for method_name in ("cancel", "delete"):
        method = getattr(tasks, method_name, None)
        if not callable(method):
            continue
        try:
            response = method(task_id=task_id)
        except TypeError:
            response = method(task_id)
        return {
            "supported": True,
            "requested": True,
            "cancelled": False,
            "action": f"ark_{method_name}",
            "response": str(response),
        }
    return {"supported": False, "cancelled": False, "reason": "ark_cancel_method_missing"}


def _ark_is_seedance_2(model_name: str) -> bool:
    spec = video_model_capability(model_name)
    return bool(spec and spec.get("provider_prefix") == "ark")


def _ark_reference_video_urls(
    reference_videos: list[dict[str, Any]] | None,
) -> list[str]:
    rows = reference_videos if isinstance(reference_videos, list) else []
    values: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        media = row.get("media") if isinstance(row.get("media"), dict) else {}
        value = str(
            row.get("dataUrl")
            or row.get("data_url")
            or row.get("url")
            or row.get("videoUrl")
            or row.get("video_url")
            or media.get("dataUrl")
            or media.get("data_url")
            or media.get("url")
            or ""
        ).strip()
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise RuntimeError("Seedance 2.x 参考视频必须是公网 http(s) URL。")
        values.append(value)
    return values


def _ark_model_supports_audio(model_name: str) -> bool:
    return video_model_supports_audio(model_name)


def _ark_model_supports_reference_images(model_name: str) -> bool:
    return video_model_supports_reference_images(model_name)


def _dashscope_endpoint_policy(base_url: str) -> dict[str, Any]:
    configured = _http_url_base(base_url or _DASHSCOPE_PUBLIC_BASE_URL)
    resolved, stripped_suffix = _strip_known_url_suffix(
        configured,
        (
            _DASHSCOPE_IMAGE_ENDPOINT,
            _DASHSCOPE_VIDEO_ENDPOINT,
            "/compatible-mode/v1",
            "/api/v1",
            "/v1",
        ),
    )
    parsed = urllib.parse.urlparse(resolved)
    host = parsed.netloc.casefold()
    if host == "dashscope.aliyuncs.com":
        profile = "legacy_public_native"
        note = "旧公共 DashScope 原生 API 域名仍保持兼容；新文本兼容接口优先按官方 workspace 域名配置。"
    elif host.endswith(".maas.aliyuncs.com"):
        profile = "workspace_maas"
        note = "检测到阿里云 Model Studio workspace 专属域名；提交原生媒体接口前会移除 compatible-mode/v1 等路径后缀。"
    else:
        profile = "custom"
        note = "自定义 DashScope 兼容域名；仅做路径规范化，不猜测区域或 workspace。"
    return {
        "provider": "dashscope",
        "configuredBaseUrl": configured,
        "resolvedBaseUrl": resolved.rstrip("/"),
        "profile": profile,
        "pathSuffixStripped": bool(stripped_suffix),
        "pathSuffix": stripped_suffix,
        "sourceUrls": list(_DASHSCOPE_OFFICIAL_ENDPOINT_SOURCE_URLS),
        "note": note,
    }


def _dashscope_host(base_url: str) -> str:
    return str(_dashscope_endpoint_policy(base_url)["resolvedBaseUrl"])


def _dashscope_headers(api_key: str, *, async_mode: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if async_mode:
        headers["X-DashScope-Async"] = "enable"
    return headers


def _dashscope_image_generation(
    provider: dict[str, Any],
    base_url: str,
    model_name: str,
    prompt: str,
    *,
    aspect_ratio: str,
    resolution: str | None,
    reference_image: dict[str, Any] | None,
    reference_images: list[dict[str, Any]] | None = None,
    max_reference_images: int | None = None,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    reference_limit = _reference_image_limit(max_reference_images, _IMAGE_MAX_REFERENCE_IMAGES)
    data_urls = _reference_data_urls(
        reference_image,
        reference_images,
        limit=reference_limit,
    )
    media_references = _reference_media_log_rows(reference_image, reference_images, media_type="image", limit=reference_limit)
    size = _dashscope_image_size(model_name, resolution, aspect_ratio, bool(data_urls))
    content: list[dict[str, str]] = []
    for data_url in data_urls:
        content.append({"image": data_url})
    content.append({"text": prompt})
    payload = {
        "model": model_name,
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": {"n": 1, "watermark": False, "prompt_extend": False, "size": size},
    }
    endpoint_policy = _dashscope_endpoint_policy(base_url)
    endpoint = f"{endpoint_policy['resolvedBaseUrl']}/{_DASHSCOPE_IMAGE_ENDPOINT.lstrip('/')}"
    _notify_request_prepared(
        on_request_prepared,
        {
            "provider": "dashscope",
            "transport": "http",
            "method": "POST",
            "url": endpoint,
            "endpointPolicy": endpoint_policy,
            "mediaReferences": media_references,
            "requestBody": payload,
        },
    )
    data = _request_json(
        "POST",
        endpoint,
        headers=_dashscope_headers(_api_key(provider)),
        data=payload,
        timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS,
    )
    url = _dashscope_extract_image_url(data)
    raw = _download_url(url, timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS)
    return MediaGenerationResponse(
        raw=raw,
        debug={
            "backend": "dashscope",
            "request": _redact_payload({**payload, "prompt": prompt[:1200]}),
            "endpointPolicy": endpoint_policy,
            "response": data,
        },
    )


def _dashscope_image_size(model_name: str, resolution: str | None, aspect_ratio: str, has_refs: bool) -> str:
    explicit = str(resolution or "").strip()
    model = model_name.lower()
    schema = image_resolution_schema_for_model(model_name, provider_id="dashscope")
    if schema:
        if model.startswith("wan"):
            model_options = ["1K", "2K", "4K"] if "pro" in model else ["1K", "2K"]
        elif "qwen-image-edit" in model:
            model_options = [
                "2048*2048",
                "2048*1152",
                "1152*2048",
                "2048*1536",
                "1536*2048",
            ]
        elif model.startswith("qwen-image"):
            model_options = [
                "2048*2048",
                "2688*1536",
                "1536*2688",
                "2368*1728",
                "1728*2368",
            ]
        else:
            model_options = []
        normalized_resolution = normalize_image_resolution_for_schema(
            explicit,
            model_options,
            "2K",
            schema,
            aspect_ratio,
            has_reference_images=has_refs,
        )
        schema_size = image_output_size_from_schema(
            schema,
            normalized_resolution,
            aspect_ratio,
            has_reference_images=has_refs,
        )
        if schema_size:
            return schema_size.replace("x", "*")
    explicit_size = _explicit_image_size(explicit, separator="*")
    if model.startswith("wan"):
        max_total = _DASHSCOPE_FOURK_PIXEL_BUDGET if _dashscope_exceeds_standard_budget(explicit or "2K") else _DASHSCOPE_STANDARD_PIXEL_BUDGET
        if max_total == _DASHSCOPE_FOURK_PIXEL_BUDGET and ("pro" not in model or has_refs):
            max_total = _DASHSCOPE_STANDARD_PIXEL_BUDGET
            explicit = "2K"
        if explicit_size:
            return explicit_size
        return _generic_image_size(explicit or "2K", aspect_ratio, default_short=1440, max_total_pixels=max_total, max_ratio=_DASHSCOPE_MAX_RATIO).replace("x", "*")
    if explicit_size:
        return explicit_size
    if "qwen-image-edit" in model:
        return _generic_image_size(explicit or "2K", aspect_ratio, default_short=2048, max_long_edge=_DASHSCOPE_EDIT_MAX_LONG_EDGE, max_ratio=_DASHSCOPE_EDIT_MAX_RATIO).replace("x", "*")
    return _generic_image_size(explicit or "2K", aspect_ratio, default_short=2048, max_total_pixels=_DASHSCOPE_STANDARD_PIXEL_BUDGET, max_ratio=_DASHSCOPE_MAX_RATIO).replace("x", "*")


def _dashscope_exceeds_standard_budget(value: str) -> bool:
    normalized = value.strip().upper().replace("×", "X").replace("*", "X")
    if normalized in {"1K", "2K"}:
        return False
    if normalized == "4K":
        return True
    if "X" in normalized:
        left, right = normalized.split("X", 1)
        try:
            return int(left) * int(right) > _DASHSCOPE_STANDARD_PIXEL_BUDGET
        except ValueError:
            return False
    return False


def _explicit_image_size(value: str | None, *, separator: str = "x") -> str:
    match = re.fullmatch(r"\s*(\d+)\s*[xX×*]\s*(\d+)\s*", str(value or ""))
    if not match:
        return ""
    return f"{int(match.group(1))}{separator}{int(match.group(2))}"


def _generic_image_size(
    resolution: str,
    aspect_ratio: str,
    *,
    default_short: int,
    max_long_edge: int | None = None,
    max_total_pixels: int | None = None,
    max_ratio: float | None = None,
) -> str:
    width, height = image_size_for_resolution(
        resolution,
        aspect_ratio,
        default_long_edge=default_short,
        round_to=16,
        max_long_edge=max_long_edge,
        max_total_pixels=max_total_pixels,
        max_ratio=max_ratio,
    )
    return f"{width}x{height}"


def _dashscope_extract_image_url(data: dict[str, Any]) -> str:
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    choices = output.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            message = choice.get("message") if isinstance(choice, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("image"):
                        return str(item["image"])
    reason = data.get("message") or output.get("message")
    raise RuntimeError(f"DashScope 图像响应缺少图片 URL: {reason or data}")


def _dashscope_video_generation(
    provider: dict[str, Any],
    base_url: str,
    model_name: str,
    prompt: str,
    reference_image: dict[str, Any] | None,
    *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    reference_audios: list[dict[str, Any]] | None = None,
    strategy: str = "",
    aspect_ratio: str,
    resolution: str,
    duration_seconds: int,
    generate_audio: bool = True,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    submitted = _dashscope_video_submit(
        provider,
        base_url,
        model_name,
        prompt,
        reference_image,
        reference_images=reference_images,
        **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos,
        strategy=strategy,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration_seconds=duration_seconds,
        generate_audio=generate_audio,
        on_request_prepared=on_request_prepared,
    )
    final = _poll_dashscope_task(provider, base_url, submitted.job_id, max_wait=max(900.0, float(duration_seconds) * 60.0))
    return _dashscope_video_response_from_task(provider, base_url, submitted.job_id, final, submitted.debug, duration_seconds)


def _dashscope_video_request(
    model_name: str,
    prompt: str,
    reference_image: dict[str, Any] | None,
    *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    reference_audios: list[dict[str, Any]] | None = None,
    strategy: str = "",
    aspect_ratio: str,
    resolution: str,
    duration_seconds: int,
    generate_audio: bool = True,
) -> dict[str, Any]:
    media: list[dict[str, str]] = []
    capability = video_model_capability(model_name)
    reference_limit = _positive_int_value((capability or {}).get("max_reference_images"))
    native_required = strategy == "native_keyframe_video"
    role_urls = _video_image_role_urls(
        reference_image, reference_images, model_name,
        native_required=native_required, reference_video_count=len(reference_videos or []),
    )
    if role_urls and reference_limit is None and not native_required:
        raise RuntimeError("当前模型未声明参考图上限")
    if sum(role == "reference_image" for role, _ in role_urls) > (reference_limit or 0):
        raise RuntimeError("参考图超过当前模型上限")
    if role_urls:
        uses_reference_images = _dashscope_model_uses_reference_images(model_name)
        if not uses_reference_images and not native_required:
            raise RuntimeError("当前 DashScope 视频模型未声明故事版参考图能力，请切换支持 reference_image 的视频模型。")
        media.extend({"type": role, "url": data_url} for role, data_url in role_urls)
    video_urls = _public_reference_video_urls(reference_videos)
    if video_urls:
        media.extend({"type": "reference_video", "url": url} for url in video_urls)
    audio_urls = validate_reference_audios(reference_audios or [], model_name, native=native_required,
        image_count=sum(role == "reference_image" for role, _ in role_urls), video_count=len(video_urls))
    for reference, audio_url in zip(reference_audios or [], audio_urls):
        binding = reference.get("binding") or {}
        media_type = {"image": "reference_image", "video": "reference_video"}.get(binding.get("kind"))
        targets = [item for item in media if item["type"] == media_type]
        index = binding.get("index")
        if not isinstance(index, int) or not 1 <= index <= len(targets):
            raise ValueError("参考音频缺少有效的角色参考素材绑定")
        if "reference_voice" in targets[index - 1]:
            raise ValueError("同一参考素材不能绑定多个说话人的音色")
        targets[index - 1]["reference_voice"] = audio_url
    input_block: dict[str, Any] = {"prompt": prompt}
    if media:
        input_block["media"] = media
    parameters: dict[str, Any] = {
        "resolution": (resolution or "720p").upper(),
        "duration": duration_seconds,
        "prompt_extend": False,
        "watermark": False,
    }
    parameters["ratio"] = aspect_ratio
    adapter = (capability or {}).get("adapter_capabilities") or {}
    if adapter.get("supports_prompt_extend") is False:
        parameters.pop("prompt_extend", None)
    if native_required:
        native_ratio = adapter.get("native_ratio_parameter")
        if native_ratio == "omit":
            parameters.pop("ratio", None)
        elif native_ratio:
            parameters["ratio"] = native_ratio
    if adapter.get("audio_parameter") == "audio":
        parameters["audio"] = bool(generate_audio)
    return {"model": model_name, "input": input_block, "parameters": parameters}


def _dashscope_video_submit(
    provider: dict[str, Any], base_url: str, model_name: str, prompt: str,
    reference_image: dict[str, Any] | None, *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    reference_audios: list[dict[str, Any]] | None = None, strategy: str = "",
    aspect_ratio: str, resolution: str, duration_seconds: int, generate_audio: bool = True,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    payload = _dashscope_video_request(
        model_name, prompt, reference_image, reference_images=reference_images,
        **({"reference_audios": reference_audios} if reference_audios else {}), reference_videos=reference_videos, strategy=strategy, aspect_ratio=aspect_ratio,
        resolution=resolution, duration_seconds=duration_seconds, generate_audio=generate_audio,
    )
    image_preparation = prepare_video_request_images(payload, model_name)
    endpoint_policy = _dashscope_endpoint_policy(base_url)
    endpoint = f"{endpoint_policy['resolvedBaseUrl']}/{_DASHSCOPE_VIDEO_ENDPOINT.lstrip('/')}"
    _notify_request_prepared(
        on_request_prepared,
        {
            "provider": "dashscope",
            "transport": "http",
            "method": "POST",
            "url": endpoint,
            "endpointPolicy": endpoint_policy,
            "imagePreparation": image_preparation,
            "requestBody": payload,
        },
    )
    submit = _request_json(
        "POST",
        endpoint,
        headers=_dashscope_headers(_api_key(provider), async_mode=True),
        data=payload,
        timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS,
    )
    task_id = _dashscope_extract_task_id(submit)
    return MediaGenerationResponse(
        raw=None,
        status="processing",
        job_id=task_id,
        debug={
            "backend": "dashscope",
            "request": _redact_payload({**payload, "prompt": prompt[:1200]}),
            "imagePreparation": image_preparation,
            "endpointPolicy": endpoint_policy,
            "created": submit,
            "taskId": task_id,
        },
    )


def _dashscope_video_response_from_task(
    provider: dict[str, Any],
    base_url: str,
    task_id: str,
    final: dict[str, Any],
    submit_debug: dict[str, Any] | None,
    duration_seconds: int,
) -> MediaGenerationResponse:
    video_url = _dashscope_extract_video_url(final)
    raw = _download_url(video_url, timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS)
    billing_duration = _dashscope_billing_duration(final)
    return MediaGenerationResponse(
        raw=raw,
        status="completed",
        job_id=task_id,
        debug={
            **(submit_debug or {"backend": "dashscope"}),
            "response": final,
            "taskId": task_id,
            "videoUrl": video_url,
            "durationSeconds": billing_duration or duration_seconds,
        },
    )


def _dashscope_video_poll(provider: dict[str, Any], base_url: str, task_id: str, *, duration_seconds: int) -> MediaGenerationResponse:
    data = _request_json(
        "GET",
        f"{_dashscope_host(base_url)}/api/v1/tasks/{urllib.parse.quote(task_id)}",
        headers={"Authorization": f"Bearer {_api_key(provider)}"},
        timeout=MODEL_MEDIA_POLL_TIMEOUT_SECONDS,
    )
    status = _dashscope_task_status(data)
    if status == "SUCCEEDED":
        return _dashscope_video_response_from_task(provider, base_url, task_id, data, None, duration_seconds)
    if status in {"FAILED", "CANCELED", "UNKNOWN"}:
        raise RuntimeError(f"DashScope 视频任务失败 status={status}: {data}")
    return MediaGenerationResponse(
        raw=None,
        status="processing",
        job_id=task_id,
        debug={"backend": "dashscope", "response": data, "taskId": task_id, "status": status or "RUNNING"},
    )


def _dashscope_video_cancel(provider: dict[str, Any], base_url: str, task_id: str) -> dict[str, Any]:
    response = _request_json(
        "POST",
        f"{_dashscope_host(base_url)}/api/v1/tasks/{urllib.parse.quote(task_id)}/cancel",
        headers={"Authorization": f"Bearer {_api_key(provider)}", "Content-Type": "application/json"},
        data={},
        timeout=MODEL_MEDIA_POLL_TIMEOUT_SECONDS,
    )
    status = _dig(response, ("output", "task_status")) or response.get("status") or response.get("state")
    return {
        "supported": True,
        "requested": True,
        "cancelled": _is_cancelled_status(status),
        "action": "dashscope_cancel_task",
        "response": response,
        "note": "DashScope only cancels tasks that are still PENDING.",
    }


def _dashscope_model_uses_reference_images(model_name: str) -> bool:
    return video_model_supports_reference_images(model_name)


def _dashscope_extract_task_id(data: dict[str, Any]) -> str:
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    task_id = output.get("task_id") or data.get("task_id")
    if not task_id:
        raise RuntimeError(f"DashScope 提交响应缺少 task_id: {data}")
    return str(task_id)


def _dashscope_task_status(data: dict[str, Any]) -> str:
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    return str(output.get("task_status") or "").upper()


def _poll_dashscope_task(provider: dict[str, Any], base_url: str, task_id: str, *, max_wait: float) -> dict[str, Any]:
    started = time.monotonic()
    last: dict[str, Any] = {}
    while time.monotonic() - started < max_wait:
        time.sleep(_DASHSCOPE_POLL_INTERVAL_SECONDS)
        last = _request_json(
            "GET",
            f"{_dashscope_host(base_url)}/api/v1/tasks/{urllib.parse.quote(task_id)}",
            headers={"Authorization": f"Bearer {_api_key(provider)}"},
            timeout=MODEL_MEDIA_POLL_TIMEOUT_SECONDS,
        )
        status = _dashscope_task_status(last)
        if status == "SUCCEEDED":
            return last
        if status in {"FAILED", "CANCELED", "UNKNOWN"}:
            raise RuntimeError(f"DashScope 视频任务失败 status={status}: {last}")
    return last


def _dashscope_extract_video_url(data: dict[str, Any]) -> str:
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    url = output.get("video_url")
    if not url:
        raise RuntimeError(f"DashScope 任务完成但缺少 video_url: {data}")
    return str(url)


def _dashscope_billing_duration(data: dict[str, Any]) -> int | None:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    raw = usage.get("duration")
    if raw is None:
        return None
    try:
        value = int(Decimal(str(raw)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value if value > 0 else None


def _gemini_base_url(base_url: str) -> str:
    base = _http_url_base(base_url or _GEMINI_DEFAULT_BASE_URL)
    return re.sub(r"/v\d+\w*$", "", base).rstrip("/")


def _gemini_api_base(base_url: str) -> str:
    return f"{_gemini_base_url(base_url)}/v1beta"


def _gemini_image_generation(
    provider: dict[str, Any],
    base_url: str,
    model_name: str,
    prompt: str,
    *,
    aspect_ratio: str,
    resolution: str | None,
    reference_image: dict[str, Any] | None,
    reference_images: list[dict[str, Any]] | None = None,
    max_reference_images: int | None = None,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    parts: list[dict[str, Any]] = []
    reference_limit = _reference_image_limit(max_reference_images, _IMAGE_MAX_REFERENCE_IMAGES)
    media_references = _reference_media_log_rows(reference_image, reference_images, media_type="image", limit=reference_limit)
    for data_url in _reference_data_urls(
        reference_image,
        reference_images,
        limit=reference_limit,
    ):
        image_part = _reference_image_part_from_data_url(data_url)
        if image_part:
            parts.append(image_part)
    parts.append({"text": prompt})
    image_config = {"aspectRatio": aspect_ratio}
    if resolution and str(resolution).lower() != "auto" and "gemini-2.5-flash-image" not in model_name.lower():
        image_config["imageSize"] = _normalize_gemini_image_resolution(resolution)
    endpoint = f"{_gemini_api_base(base_url)}/models/{urllib.parse.quote(model_name, safe='')}:generateContent"
    payload = {"contents": [{"parts": parts}], "generationConfig": {
        "responseModalities": ["TEXT", "IMAGE"], "imageConfig": image_config,
    }}
    _notify_request_prepared(on_request_prepared, {
        "provider": "gemini", "transport": "http", "method": "POST", "url": endpoint,
        "mediaReferences": media_references, "requestBody": payload,
    })
    try:
        data = _request_json(
            "POST", endpoint,
            headers={"x-goog-api-key": _api_key(provider), "Content-Type": "application/json"},
            data=payload, timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        raise RuntimeError(f"Gemini 图片请求失败，提交结果可能不明确，请核对供应商记录后再重试：{exc}") from exc
    raw = _extract_inline_image_bytes(data)
    if not raw:
        raise RuntimeError("Gemini 未返回图片 inlineData；未自动重复提交生成")
    return MediaGenerationResponse(
        raw=raw,
        debug={"backend": "gemini", "response": data, "request": _redact_payload(payload), "mimeType": "image/png"},
    )


def _normalize_gemini_image_resolution(resolution: str | None) -> str:
    raw = str(resolution or "").strip()
    if raw.lower() in {"1k", "2k", "4k"}:
        return raw.upper()
    if raw.lower() in {"512", "512px"}:
        return "512"
    return raw or "1K"


def _vidu_endpoint_policy(base_url: str) -> dict[str, Any]:
    configured = _http_url_base(base_url or _VIDU_DEFAULT_BASE_URL)
    resolved, stripped_suffix = _strip_known_url_suffix(
        configured,
        (
            "/reference2video",
            "/img2video",
            "/text2video",
            "/reference2image",
        ),
    )
    parsed = urllib.parse.urlparse(resolved)
    host = parsed.netloc.casefold()
    path = parsed.path.rstrip("/")
    if host in {"api.vidu.com", "api.vidu.cn"} and path in {"", "/ent"}:
        scheme = parsed.scheme or "https"
        resolved = f"{scheme}://{host}/ent/v2"
        parsed = urllib.parse.urlparse(resolved)
        path = parsed.path.rstrip("/")
    normalized_resolved = resolved.rstrip("/")
    if normalized_resolved.casefold() == _VIDU_GLOBAL_BASE_URL.casefold():
        profile = "official_global"
        note = "Vidu 英文官方 Reference-to-Video 文档示例域名。"
    elif normalized_resolved.casefold() == _VIDU_CN_BASE_URL.casefold():
        profile = "official_cn"
        note = "Vidu 中文/区域接口域名；保留给已按该区域配置的账号。"
    else:
        profile = "custom"
        note = "自定义 Vidu 域名；仅做 /ent/v2 与具体任务端点的路径规范化。"
    return {
        "provider": "vidu",
        "configuredBaseUrl": configured,
        "resolvedBaseUrl": normalized_resolved,
        "profile": profile,
        "pathSuffixStripped": bool(stripped_suffix),
        "pathSuffix": stripped_suffix,
        "defaultBaseUrl": _VIDU_DEFAULT_BASE_URL,
        "acceptedBaseUrls": [_VIDU_GLOBAL_BASE_URL, _VIDU_CN_BASE_URL],
        "sourceUrls": list(_VIDU_OFFICIAL_ENDPOINT_SOURCE_URLS),
        "note": note,
    }


def _vidu_base_url(base_url: str) -> str:
    return str(_vidu_endpoint_policy(base_url)["resolvedBaseUrl"])


def _vidu_headers(provider: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Token {_api_key(provider)}", "Content-Type": "application/json"}


def _vidu_image_resolution(model_name: str, resolution: str | None) -> str:
    allowed = _VIDU_IMAGE_RESOLUTIONS.get(model_name)
    if not allowed:
        return ""
    normalized = str(resolution or "").strip().upper()
    if normalized == "1080P":
        normalized = "1K"
    if normalized not in allowed:
        normalized = "2K" if "2K" in allowed else next(iter(allowed))
    return "1080p" if normalized == "1K" else normalized


def _vidu_image_generation(
    provider: dict[str, Any],
    base_url: str,
    model_name: str,
    prompt: str,
    *,
    aspect_ratio: str,
    resolution: str | None,
    reference_image: dict[str, Any] | None,
    reference_images: list[dict[str, Any]] | None = None,
    max_reference_images: int | None = None,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    prompt_text = str(prompt or "")
    if len(prompt_text) > _VIDU_PROMPT_MAX_IMAGE:
        raise RuntimeError(
            f"Vidu 图片提示词超过 {_VIDU_PROMPT_MAX_IMAGE} 字符上限；"
            "请重新生成更短且完整的图片提示词，后端不会按字符剪切、压缩或提交不完整资料。"
        )
    body: dict[str, Any] = {"model": model_name, "prompt": prompt_text}
    reference_limit = min(_reference_image_limit(max_reference_images, _VIDU_MAX_REFERENCE_IMAGES), _VIDU_MAX_REFERENCE_IMAGES)
    data_urls = _reference_data_urls(
        reference_image,
        reference_images,
        limit=reference_limit,
    )
    media_references = _reference_media_log_rows(reference_image, reference_images, media_type="image", limit=reference_limit)
    if data_urls:
        body["images"] = data_urls
    allowed_aspects = _VIDU_IMAGE_ASPECT_RATIOS.get(model_name)
    if allowed_aspects and aspect_ratio in allowed_aspects:
        body["aspect_ratio"] = aspect_ratio
    provider_resolution = _vidu_image_resolution(model_name, resolution)
    if provider_resolution:
        body["resolution"] = provider_resolution
    endpoint_policy = _vidu_endpoint_policy(base_url)
    endpoint_url = f"{endpoint_policy['resolvedBaseUrl']}/reference2image"
    _notify_request_prepared(
        on_request_prepared,
        {
            "provider": "vidu",
            "transport": "http",
            "method": "POST",
            "url": endpoint_url,
            "endpointPolicy": endpoint_policy,
            "mediaReferences": media_references,
            "requestBody": body,
        },
    )
    created = _request_json(
        "POST",
        endpoint_url,
        headers=_vidu_headers(provider),
        data=body,
        timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS,
    )
    task_id = _vidu_task_id(created)
    final = _poll_vidu_task(provider, base_url, task_id, max_wait=600.0, interval=_VIDU_IMAGE_POLL_INTERVAL_SECONDS)
    url = _vidu_extract_url(final)
    raw = _download_url(url, timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS)
    return MediaGenerationResponse(
        raw=raw,
        debug={
            "backend": "vidu",
            "request": _redact_payload(body),
            "endpointPolicy": endpoint_policy,
            "created": created,
            "response": final,
            "taskId": task_id,
            "imageUrl": url,
        },
    )


def _vidu_video_generation(
    provider: dict[str, Any],
    base_url: str,
    model_name: str,
    prompt: str,
    reference_image: dict[str, Any] | None,
    *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    strategy: str = "",
    aspect_ratio: str,
    resolution: str,
    duration_seconds: int,
    generate_audio: bool,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    submitted = _vidu_video_submit(
        provider,
        base_url,
        model_name,
        prompt,
        reference_image,
        reference_images=reference_images,
        reference_videos=reference_videos,
        strategy=strategy,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration_seconds=duration_seconds,
        generate_audio=generate_audio,
        on_request_prepared=on_request_prepared,
    )
    duration = int((submitted.debug.get("durationSeconds") if isinstance(submitted.debug, dict) else None) or duration_seconds or 5)
    final = _poll_vidu_task(provider, base_url, submitted.job_id, max_wait=max(900.0, float(duration) * 90.0), interval=_VIDU_POLL_INTERVAL_SECONDS)
    return _vidu_video_response_from_task(provider, base_url, submitted.job_id, final, submitted.debug)


def _vidu_video_submit(
    provider: dict[str, Any],
    base_url: str,
    model_name: str,
    prompt: str,
    reference_image: dict[str, Any] | None,
    *,
    reference_images: list[dict[str, Any]] | None = None,
    reference_videos: list[dict[str, Any]] | None = None,
    strategy: str = "",
    aspect_ratio: str,
    resolution: str,
    duration_seconds: int,
    generate_audio: bool,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> MediaGenerationResponse:
    role_urls = _video_image_role_urls(
        reference_image, reference_images, model_name,
        native_required=strategy == "native_keyframe_video",
        reference_video_count=len(reference_videos or []),
    )
    native = any(role != "reference_image" for role, _ in role_urls)
    if native:
        role_urls.sort(key=lambda item: 0 if item[0] == "first_frame" else 1)
    data_urls = [url for _, url in role_urls]
    video_urls = _reference_video_urls(reference_videos, limit=2)
    if video_urls:
        raise RuntimeError("当前 Vidu 正式视频模型不支持参考视频输入，请移除参考视频或切换其他支持模型。")
    endpoint = _vidu_video_endpoint(
        model_name,
        bool(data_urls or video_urls),
        reference_count=len(data_urls) + len(video_urls),
        strategy=strategy,
    )
    if native:
        endpoint = "/start-end2video" if any(role == "last_frame" for role, _ in role_urls) else "/img2video"
    if endpoint not in _VIDU_ENDPOINT_MODELS:
        raise RuntimeError(f"Vidu 视频端点 {endpoint} 未在本地能力表中声明，已阻断生成。")
    model_set = _VIDU_ENDPOINT_MODELS[endpoint]
    if model_name not in model_set:
        raise RuntimeError(
            f"Vidu 模型 {model_name} 不支持 {endpoint} 端点，已阻断生成；"
            "不能降级到其他端点导致参考图、时长或提示词语义变化。"
        )
    reference_limit = _vidu_video_reference_image_limit(model_name, endpoint)
    if data_urls and reference_limit is None:
        raise RuntimeError(
            f"Vidu 模型 {model_name} 的 {endpoint} 端点未声明参考图数量上限，已阻断生成；"
            "不能猜测可传参考图数量或提交不完整资料。"
        )
    if data_urls and reference_limit is not None and len(data_urls) > reference_limit:
        raise RuntimeError(
            f"Vidu {endpoint} 参考图超过当前模型可传输上限：当前 {len(data_urls)} 张，最多 {reference_limit} 张。"
            "已阻断生成，不能裁掉多余参考图后提交不完整资料；请减少参考图，或切换支持更多参考图的模型。"
        )
    duration = _coerce_vidu_duration(model_name, endpoint, duration_seconds)
    prompt_limit = (
        _VIDU_PROMPT_MAX_REFERENCE2VIDEO
        if endpoint == "/reference2video"
        else _VIDU_PROMPT_MAX_TEXT2VIDEO
    )
    prompt_text = str(prompt or "")
    prompt_chars = len(prompt_text)
    if prompt_chars > prompt_limit:
        raise RuntimeError(
            f"Vidu 视频生成总提示词当前 {prompt_chars} 字符（不是任务卡单独提示词），"
            f"超过模型上限 {prompt_limit} 字符，已阻断。"
        )
    body: dict[str, Any] = {
        "model": model_name,
        "prompt": prompt_text,
        "duration": duration,
    }
    coerced_resolution = _coerce_vidu_resolution(model_name, resolution, endpoint=endpoint, duration=duration)
    if coerced_resolution:
        body["resolution"] = coerced_resolution
    if model_name in _VIDU_Q3_MODELS:
        body["audio"] = bool(generate_audio)
    if endpoint in _VIDU_ENDPOINTS_WITH_ASPECT_RATIO:
        body["aspect_ratio"] = aspect_ratio
    if data_urls:
        if endpoint == "/img2video":
            if len(data_urls) > 1:
                raise RuntimeError(
                    f"Vidu 模型 {model_name} 当前只能通过 img2video 传输 1 张参考图，"
                    f"但任务提供了 {len(data_urls)} 张。请减少参考图，或切换支持 reference2video 的 Vidu 模型。"
                )
            body["images"] = data_urls
        else:
            body["images"] = data_urls
    if video_urls:
        if endpoint != "/reference2video":
            raise RuntimeError("Vidu 参考视频只能通过 reference2video 端点提交。")
        body["videos"] = video_urls
    image_preparation = prepare_video_request_images(body, model_name, image_roles=[role for role, _ in role_urls])
    endpoint_policy = _vidu_endpoint_policy(base_url)
    endpoint_url = f"{endpoint_policy['resolvedBaseUrl']}{endpoint}"
    _notify_request_prepared(
        on_request_prepared,
        {
            "provider": "vidu",
            "transport": "http",
            "method": "POST",
            "url": endpoint_url,
            "endpointPolicy": endpoint_policy,
            "imagePreparation": image_preparation,
            "requestBody": body,
        },
    )
    created = _request_json(
        "POST",
        endpoint_url,
        headers=_vidu_headers(provider),
        data=body,
        timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS,
    )
    task_id = _vidu_task_id(created)
    return MediaGenerationResponse(
        raw=None,
        status="processing",
        job_id=task_id,
        debug={
            "backend": "vidu",
            "request": _redact_payload(body),
            "imagePreparation": image_preparation,
            "endpointPolicy": endpoint_policy,
            "created": created,
            "taskId": task_id,
            "durationSeconds": duration,
        },
    )


def _vidu_video_response_from_task(
    provider: dict[str, Any],
    base_url: str,
    task_id: str,
    final: dict[str, Any],
    submit_debug: dict[str, Any] | None = None,
) -> MediaGenerationResponse:
    url = _vidu_extract_url(final)
    raw = _download_url(url, timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS)
    duration = (submit_debug or {}).get("durationSeconds")
    return MediaGenerationResponse(
        raw=raw,
        status="completed",
        job_id=task_id,
        debug={
            **(submit_debug or {"backend": "vidu"}),
            "response": final,
            "taskId": task_id,
            "videoUrl": url,
            "durationSeconds": duration,
        },
    )


def _vidu_video_poll(provider: dict[str, Any], base_url: str, task_id: str) -> MediaGenerationResponse:
    data = _request_json(
        "GET",
        f"{_vidu_base_url(base_url)}/tasks/{urllib.parse.quote(task_id)}/creations",
        headers=_vidu_headers(provider),
        timeout=MODEL_MEDIA_POLL_TIMEOUT_SECONDS,
    )
    state = str(data.get("state") or "").lower()
    if state == "success":
        return _vidu_video_response_from_task(provider, base_url, task_id, data)
    if state == "failed":
        raise RuntimeError(f"Vidu 任务失败: err_code={data.get('err_code') or 'unknown'}")
    return MediaGenerationResponse(
        raw=None,
        status="processing",
        job_id=task_id,
        debug={"backend": "vidu", "response": data, "taskId": task_id, "status": state or "processing"},
    )


def _vidu_video_cancel(provider: dict[str, Any], base_url: str, task_id: str) -> dict[str, Any]:
    response = _request_json(
        "POST",
        f"{_vidu_base_url(base_url)}/tasks/{urllib.parse.quote(task_id)}/cancel",
        headers=_vidu_headers(provider),
        data={"id": task_id},
        timeout=MODEL_MEDIA_POLL_TIMEOUT_SECONDS,
    )
    status = response.get("state") or response.get("status")
    return {
        "supported": True,
        "requested": True,
        "cancelled": _is_cancelled_status(status),
        "action": "vidu_cancel_task",
        "response": response,
    }


def _vidu_video_endpoint(
    model_name: str,
    has_reference: bool,
    *,
    reference_count: int = 0,
    strategy: str = "",
) -> str:
    normalized_strategy = str(strategy or "").strip().casefold()
    requires_reference2video = normalized_strategy in {
        "storyboard_multi_shot",
        "storyboard_reference",
        "multi_reference_video",
        "reference_video",
    }
    if has_reference:
        if model_name in _VIDU_ENDPOINT_MODELS["/reference2video"]:
            return "/reference2video"
        if requires_reference2video or reference_count > 1:
            return "/reference2video"
        return "/img2video"
    return "/text2video"


def _coerce_vidu_duration(model_name: str, endpoint: str, requested: int | None) -> int:
    allowed = _VIDU_DURATION_RULES.get((model_name, endpoint))
    if not allowed:
        return int(requested or 5)
    if requested is None:
        return 5 if 5 in allowed else allowed[0]
    requested_int = int(requested)
    if requested_int in allowed:
        return requested_int
    raise RuntimeError(
        f"Vidu 模型 {model_name} 的 {endpoint} 生成时长需为 {min(allowed)}～{max(allowed)} 秒，"
        f"当前设置为 {requested_int} 秒，已中断生成，请调整任务卡时长。"
    )


def _coerce_vidu_resolution(model_name: str, requested: str | None, *, endpoint: str, duration: int) -> str | None:
    whitelist = _VIDU_RESOLUTION_RULES.get((model_name, endpoint, duration)) or _VIDU_RESOLUTIONS.get(model_name)
    if not whitelist:
        return requested
    if requested and requested in whitelist:
        return requested
    return "720p" if "720p" in whitelist else whitelist[0]


def _vidu_task_id(data: dict[str, Any]) -> str:
    task_id = data.get("task_id") or data.get("taskId")
    if not task_id:
        raise RuntimeError(f"Vidu 任务创建响应缺少 task_id: {data}")
    return str(task_id)


def _poll_vidu_task(provider: dict[str, Any], base_url: str, task_id: str, *, max_wait: float, interval: float) -> dict[str, Any]:
    started = time.monotonic()
    last: dict[str, Any] = {}
    while time.monotonic() - started < max_wait:
        time.sleep(interval)
        last = _request_json(
            "GET",
            f"{_vidu_base_url(base_url)}/tasks/{urllib.parse.quote(task_id)}/creations",
            headers=_vidu_headers(provider),
            timeout=MODEL_MEDIA_POLL_TIMEOUT_SECONDS,
        )
        state = str(last.get("state") or "").lower()
        if state == "success":
            return last
        if state == "failed":
            raise RuntimeError(f"Vidu 任务失败: err_code={last.get('err_code') or 'unknown'}")
    return last


def _vidu_extract_url(data: dict[str, Any]) -> str:
    creations = data.get("creations")
    if isinstance(creations, list) and creations:
        url = creations[0].get("url") if isinstance(creations[0], dict) else None
        if url:
            return str(url)
    raise RuntimeError(f"Vidu 任务无 creations.url: {data}")
