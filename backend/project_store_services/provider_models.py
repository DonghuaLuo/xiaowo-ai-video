# -*- coding: utf-8 -*-
"""供应商行规范化、模型能力目录、输出尺寸和模型配置规范化。"""

from __future__ import annotations

import re
from .catalogs import (
    DEFAULT_MODEL_CAPABILITIES,
)
from typing import (
    Any,
)

import base64
import copy
import hashlib
import json
import random
import shutil
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from utils.agent_context import (
    AGENT_CONTEXT_MESSAGE_TEXT_LIMIT,
    AGENT_CONTEXT_RECENT_WINDOW,
    AGENT_CONTEXT_SUMMARY_CHARS,
    build_agent_conversation_context,
)
from utils import agent_sdk_runtime
from utils.agent_session_service import AgentSessionService
from utils.aspect_size import (
    IMAGE_TIER_SHORT_EDGE,
    VIDEO_TIER_SHORT_EDGE,
    aspect_size,
    image_size_for_resolution,
    parse_aspect_ratio,
    resolution_to_short_edge,
)
from utils.image_pipeline import (
    convert_image_bytes_to_png,
    data_url_from_bytes,
    prepare_provider_image_bytes,
    prepare_provider_image_data_uri,
    save_project_image,
    save_provider_output_image,
)
from utils.image_resolution_schema import (
    image_output_size_from_schema,
    image_resolution_options_for_schema,
    image_resolution_schema_for_model,
    resolve_image_aspect_ratio_for_model,
    with_image_resolution_schema,
)
from utils.media_backends import (
    cancel_video_media_job,
    endpoint_supports_media_generation,
    infer_model_endpoint,
    media_endpoint_type,
    normalize_media_endpoint,
    generate_image_media,
    generate_video_media,
    poll_video_media_job,
    provider_supports_media_generation,
    submit_video_media_job,
)
from .catalogs import BUILTIN_PROVIDER_MODELS
from .catalogs import DEFAULT_IMAGE_GENERATION_PARAMETERS
from .catalogs import DEFAULT_OVERVIEW_EXCERPT_CHARS
from .catalogs import IMAGE_OUTPUT_FORMATS
from .catalogs import IMAGE_OUTPUT_FORMAT_VALUES
from .catalogs import IMAGE_RESOLUTION_ALIASES
from .catalogs import LEGACY_GENERIC_PROVIDER_MODEL_IDS
from .catalogs import LEGACY_IMAGE_RESOLUTION_TO_TIER
from .catalogs import MAX_OVERVIEW_EXCERPT_CHARS
from .catalogs import MIN_OVERVIEW_EXCERPT_CHARS
from .catalogs import MODEL_CONFIG_REQUIRED_MESSAGE
from .catalogs import OPENAI_GPT_IMAGE_2_DEFAULT_RESOLUTION
from .catalogs import OPENAI_GPT_IMAGE_2_RESOLUTIONS
from .catalogs import PROVIDER_ADAPTER_SERVICE_IDS
from .catalogs import REFERENCE_IMAGE_INPUT_DEFAULT_MAX_BYTES
from .catalogs import REFERENCE_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE
from .catalogs import RETIRED_PROVIDER_PRESET_IDS
from .catalogs import SERVICE_PROVIDER_ADAPTER_IDS
from .catalogs import STANDARD_COMPATIBLE_IMAGE_RESOLUTIONS
from .catalogs import STANDARD_COMPATIBLE_VIDEO_RESOLUTIONS
from .catalogs import _DASHSCOPE_EDIT_MAX_LONG_EDGE
from .catalogs import _DASHSCOPE_EDIT_MAX_RATIO
from .catalogs import _DASHSCOPE_FOURK_PIXEL_BUDGET
from .catalogs import _DASHSCOPE_MAX_RATIO
from .catalogs import _DASHSCOPE_STANDARD_PIXEL_BUDGET
from .catalogs import _GPT_IMAGE_MAX_LONG_EDGE
from .catalogs import _GPT_IMAGE_MAX_RATIO
from .catalogs import _GPT_IMAGE_MAX_TOTAL_PIXELS
from .catalogs import _VIDEO_SIZE_PRESETS
from .catalogs import _normalize_duration_options
from .catalogs import _normalize_provider_model_metadata
from .store_core import AGENT_MAX_TOKEN_OPTIONS
from .store_core import AGENT_TEMPERATURE_OPTIONS
from .store_core import _deep_merge
from .store_core import _mask_key
from .store_core import _merge_provider_presets
from .store_core import _now

PROVIDER_CAPABILITY_VALUES = {
    "storyboard_image",
    "asset_image",
    "storyboard_video",
    "agent",
    "text_generation",
}


def _normalize_provider_capabilities(value: Any, *, supported: list[str] | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    for item in value:
        capability = str(item or "").strip()
        if (
            capability in PROVIDER_CAPABILITY_VALUES
            and capability not in rows
            and (supported is None or capability in supported)
        ):
            rows.append(capability)
    return rows


def _normalize_provider_id(provider_id: str | None) -> str:
    legacy = {
        "openai-image": "openai",
        "ark": "ark-seedance",
    }
    raw = str(provider_id or "").strip()
    return legacy.get(raw, raw)


def _provider_preset_id(provider: dict[str, Any] | None) -> str:
    if not isinstance(provider, dict):
        return ""
    return _normalize_provider_id(
        provider.get("preset_id")
        or provider.get("presetId")
        or provider.get("provider_preset_id")
        or provider.get("providerPresetId")
        or ""
    )


def _provider_service_id(provider: dict[str, Any] | None) -> str:
    if not isinstance(provider, dict):
        return ""
    return _provider_preset_id(provider) or _normalize_provider_id(provider.get("id"))


def _normalize_provider_adapter_id(value: Any) -> str:
    raw = str(value or "").strip()
    if raw in PROVIDER_ADAPTER_SERVICE_IDS:
        return raw
    service_id = _normalize_provider_id(raw)
    return SERVICE_PROVIDER_ADAPTER_IDS.get(service_id, service_id)


def _provider_adapter_id(provider: dict[str, Any] | None) -> str:
    if not isinstance(provider, dict):
        return ""
    explicit = (
        provider.get("adapter_id")
        or provider.get("adapterId")
        or provider.get("provider_adapter_id")
        or provider.get("providerAdapterId")
    )
    if explicit:
        return _normalize_provider_adapter_id(explicit)
    return _normalize_provider_adapter_id(_provider_service_id(provider))


def _storyboard_size_prompt_only_for_gpt_relay(
    model: dict[str, Any] | None,
    *,
    provider_id: str | None = None,
    adapter_id: str | None = None,
) -> bool:
    model = model if isinstance(model, dict) else {}
    model_id = str(model.get("id") or "").strip()
    model_name = model_id.split(":", 1)[-1].lower()
    resolved_provider_id = str(
        provider_id or model.get("provider_id") or model_id.split(":", 1)[0]
    ).strip()
    resolved_adapter_id = str(
        adapter_id or model.get("adapter_id") or model.get("adapterId") or ""
    ).strip()
    return (
        model_name.startswith("gpt-image-2")
        and resolved_adapter_id == "openai-compatible"
        and resolved_provider_id != "openai"
    )


def _provider_protocol_service_id(provider: dict[str, Any] | None) -> str:
    adapter_id = _provider_adapter_id(provider)
    return PROVIDER_ADAPTER_SERVICE_IDS.get(adapter_id, _provider_service_id(provider))


def _adapter_endpoint_format(provider: dict[str, Any] | None) -> str:
    return "google" if _provider_adapter_id(provider) == "gemini-compatible" else "openai"


def _unique_provider_instance_id(
    providers: list[dict[str, Any]],
    preferred_id: str,
    *,
    exclude_provider_id: str | None = None,
) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", preferred_id).strip("-") or "provider"
    excluded = _normalize_provider_id(exclude_provider_id)
    used = {
        _normalize_provider_id(row.get("id"))
        for row in providers
        if isinstance(row, dict)
        and _normalize_provider_id(row.get("id"))
        and _normalize_provider_id(row.get("id")) != excluded
    }
    if base not in used:
        return base
    index = 2
    while f"{base}-{index}" in used:
        index += 1
    return f"{base}-{index}"


def _unique_provider_title(
    providers: list[dict[str, Any]],
    preferred_title: str,
    *,
    exclude_provider_id: str | None = None,
) -> str:
    base = str(preferred_title or "供应商实例").strip() or "供应商实例"
    excluded = _normalize_provider_id(exclude_provider_id)
    used = {
        str(row.get("title") or row.get("name") or "").strip()
        for row in providers
        if isinstance(row, dict)
        and _normalize_provider_id(row.get("id")) != excluded
        and str(row.get("title") or row.get("name") or "").strip()
    }
    if base not in used:
        return base
    index = 1
    while f"{base} {index}" in used:
        index += 1
    return f"{base} {index}"


def _storage_provider_row(provider: dict[str, Any], presets: list[dict[str, Any]]) -> dict[str, Any]:
    provider_id = _normalize_provider_id(provider.get("id"))
    service_id = _provider_service_id(provider)
    storage_keys = (
        "id",
        "adapter_id",
        "preset_id",
        "title",
        "name",
        "logo",
        "icon_key",
        "description",
        "base_url",
        "default_base_url",
        "base_url_options",
        "base_url_note",
        "docs_url",
        "key_label",
        "capabilities",
        "models",
        "api_key",
        "api_key_masked",
        "configured",
        "connection_status",
        "last_test",
        "probe_summary",
        "native_structured_output",
        "native_structured_models",
        "user_added",
        "added_at",
    )
    row = {
        key: copy.deepcopy(provider[key])
        for key in storage_keys
        if key in provider and provider[key] not in (None, "")
    }
    if "capabilities" in row:
        row["capabilities"] = _normalize_provider_capabilities(row.get("capabilities"))
    row["id"] = provider_id
    row["adapter_id"] = _provider_adapter_id(provider)
    if service_id and service_id != provider_id:
        row["preset_id"] = service_id
    return row


def _storage_global_config(config: dict[str, Any]) -> dict[str, Any]:
    presets = _merge_provider_presets(None)
    result = copy.deepcopy(config)
    result.pop("provider_presets", None)
    result.pop("model_capabilities", None)
    result["providers"] = [
        _storage_provider_row(provider, presets)
        for provider in config.get("providers", [])
        if isinstance(provider, dict)
    ]
    return result


def _is_user_added_provider_row(
    item: dict[str, Any],
    provider_id: str,
    preset_by_id: dict[str, dict[str, Any]],
) -> bool:
    if item.get("user_added") or item.get("userAdded"):
        return True
    if item.get("added_at") or item.get("addedAt"):
        return True
    if provider_id not in preset_by_id:
        return True
    if item.get("api_key") or item.get("api_key_masked") or item.get("apiKeyMasked"):
        return True
    return bool(item.get("configured"))


def _provider_model_merge_key(model: Any) -> str:
    if not isinstance(model, dict):
        return ""
    raw = str(
        model.get("id")
        or model.get("model_id")
        or model.get("modelId")
        or model.get("name")
        or ""
    ).strip()
    if raw.startswith("models/"):
        raw = raw.split("/", 1)[1]
    if ":" in raw:
        raw = raw.split(":", 1)[1]
    return raw.strip().lower()


def _merge_provider_model_rows(base_models: Any, override_models: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for source in (base_models, override_models):
        if not isinstance(source, list):
            continue
        for model in source:
            if not isinstance(model, dict):
                continue
            row = copy.deepcopy(model)
            key = _provider_model_merge_key(row)
            if key and key in index_by_key:
                rows[index_by_key[key]] = _deep_merge(rows[index_by_key[key]], row)
                continue
            if key:
                index_by_key[key] = len(rows)
            rows.append(row)
    return rows


def _normalize_provider_rows(value: Any, presets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    incoming = value if isinstance(value, list) else []
    preset_by_id = {str(preset["id"]): preset for preset in presets}
    rows_by_id: dict[str, dict[str, Any]] = {}

    for item in incoming:
        if not isinstance(item, dict):
            continue
        provider_id = _normalize_provider_id(item.get("id"))
        if not provider_id:
            continue
        if provider_id in RETIRED_PROVIDER_PRESET_IDS:
            continue
        preset_id = _normalize_provider_id(
            item.get("preset_id")
            or item.get("presetId")
            or (provider_id if provider_id in preset_by_id else "")
        )
        service_id = preset_id or provider_id
        if service_id in RETIRED_PROVIDER_PRESET_IDS:
            continue
        if not _is_user_added_provider_row(item, service_id, preset_by_id):
            continue
        base = copy.deepcopy(preset_by_id.get(service_id, {"id": provider_id}))
        normalized = _deep_merge(base, item)
        last_test = item.get("last_test") if isinstance(item.get("last_test"), dict) else {}
        has_capability_results = isinstance(last_test.get("capabilityResults"), dict)
        if (
            service_id in preset_by_id
            and isinstance(base.get("models"), list)
            and isinstance(item.get("models"), list)
            and not has_capability_results
        ):
            normalized["models"] = _merge_provider_model_rows(
                base.get("models"),
                item.get("models"),
            )
        normalized["id"] = provider_id
        normalized["adapter_id"] = _provider_adapter_id(normalized)
        if service_id in preset_by_id:
            normalized["preset_id"] = service_id
            normalized["official_title"] = base.get("title") or service_id
        normalized["user_added"] = True
        normalized.setdefault("added_at", normalized.pop("addedAt", None) or _now())
        if not str(normalized.get("title") or "").strip():
            normalized["title"] = (
                str(normalized.get("name") or "").strip()
                or str(base.get("title") or "").strip()
                or provider_id
            )
        normalized.setdefault("logo", str(normalized.get("title", "?"))[:2].upper())
        normalized.setdefault("icon_key", normalized.get("logo") or "")
        normalized.setdefault("description", "")
        normalized.setdefault("base_url", "")
        normalized.setdefault("default_base_url", base.get("base_url") or "")
        normalized.setdefault("base_url_options", copy.deepcopy(base.get("base_url_options") or []))
        normalized.setdefault("base_url_note", base.get("base_url_note") or "")
        normalized.setdefault("docs_url", "")
        normalized.setdefault("key_label", "API_KEY")
        normalized["capabilities"] = _normalize_provider_capabilities(
            normalized.get("capabilities"), supported=base.get("capabilities"),
        )
        normalized.setdefault("models", [])
        normalized.setdefault("probe_summary", {})
        normalized.setdefault("native_structured_output", "unknown")
        if "native_structured_models" not in normalized:
            native_structured_models = normalized.pop("nativeStructuredModels", {})
            normalized["native_structured_models"] = (
                copy.deepcopy(native_structured_models)
                if isinstance(native_structured_models, dict)
                else {}
            )
        elif not isinstance(normalized.get("native_structured_models"), dict):
            normalized["native_structured_models"] = {}
        normalized.pop("nativeStructuredModels", None)
        normalized.pop("agent_runtime", None)
        normalized.pop("agentRuntime", None)
        api_key = str(normalized.get("api_key") or "")
        configured = bool(normalized.get("configured") or api_key or normalized.get("api_key_masked"))
        if str(normalized.get("status") or "") == "ready":
            configured = True
            normalized["connection_status"] = "connected"
        normalized["configured"] = configured
        normalized["api_key_masked"] = normalized.get("api_key_masked") or _mask_key(api_key)
        normalized.setdefault("connection_status", "untested" if configured else "unconfigured")
        normalized.setdefault("last_test", None)
        rows_by_id[provider_id] = _deep_merge(rows_by_id.get(provider_id, {}), normalized)

    rows: list[dict[str, Any]] = []
    for row in rows_by_id.values():
        row["title"] = _unique_provider_title(rows, str(row.get("title") or "供应商实例"), exclude_provider_id=row.get("id"))
        rows.append(row)
    return rows


def _provider_model_matches_capabilities(model: dict[str, Any], capabilities: list[str]) -> bool:
    from utils.model_exclusions import model_is_excluded

    if model_is_excluded(model):
        return False
    model_type = str(model.get("type") or "")
    capability_set = set(capabilities)
    if model_type == "image":
        return bool({"storyboard_image", "asset_image"} & capability_set)
    if model_type == "video":
        return "storyboard_video" in capability_set
    if model_type == "text":
        return bool({"agent", "text_generation"} & capability_set)
    return True


def _model_generation_endpoint(provider: dict[str, Any], model: dict[str, Any] | None) -> str:
    from .model_provider_config import _api_model_name
    if not isinstance(model, dict):
        return ""
    if model.get("routing_status") == "pending":
        return ""
    adapter_id = _provider_adapter_id(provider)
    explicit = (
        model.get("endpoint")
        or model.get("endpoint_key")
        or model.get("endpointKey")
        or model.get("generation_endpoint")
        or model.get("generationEndpoint")
        or ""
    )
    if str(explicit or "").strip():
        return str(explicit).strip()
    if adapter_id == "anthropic-compatible":
        return ""
    if str(model.get("type") or "").strip().lower() == "video":
        if adapter_id == "dashscope":
            return "dashscope-async-video"
        if adapter_id == "vidu":
            return "vidu-video"
    if adapter_id in {"ark-seedance", "dashscope", "vidu", "grok"}:
        return ""
    return infer_model_endpoint(
        _api_model_name(model.get("id")),
        _adapter_endpoint_format(provider),
        provider=provider,
    )


def _text_model_generation_endpoint(provider: dict[str, Any], model: dict[str, Any] | None) -> str:
    """Use the model protocol first; provider defaults only fill missing routes."""
    from utils.text_model_contracts import general_text_pending_reason

    if reason := general_text_pending_reason(model or {}):
        raise RuntimeError(reason)
    if isinstance(model, dict) and model.get("routing_status") == "pending":
        raise RuntimeError("当前文本模型接口待适配")
    endpoint = _model_generation_endpoint(provider, model)
    endpoint_type = media_endpoint_type(endpoint)
    if endpoint_type == "text":
        return normalize_media_endpoint(endpoint)
    if endpoint_type:
        raise RuntimeError(f"当前文本模型 endpoint 与文本调用不匹配：{endpoint}")
    adapter_id = _provider_adapter_id(provider)
    if adapter_id == "anthropic-compatible" or _provider_service_id(provider) in {
        "anthropic", "ark-agent-plan", "deepseek", "minimax",
    }:
        return "anthropic-messages"
    if adapter_id == "gemini-compatible":
        return "gemini-generate"
    return "openai-chat"


def _with_model_generation_endpoint(provider: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(model)
    endpoint = _model_generation_endpoint(provider, normalized)
    if endpoint:
        normalized["endpoint"] = endpoint
    return normalized


def _provider_supports_direct_media_generation(
    provider: dict[str, Any],
    media_type: str,
    model: dict[str, Any] | None = None,
) -> bool:
    endpoint = _model_generation_endpoint(provider, model)
    if endpoint:
        return endpoint_supports_media_generation(endpoint, media_type)
    return provider_supports_media_generation(provider, media_type)


_NON_MEDIA_GENERATION_MODEL_RE = re.compile(
    r"(^|[\s:/_.-])(speech|tts|audio|voice|embedding|embed|rerank|whisper)($|[\s:/_.-])|"
    r"minimax[\s:/_.-]*m\d",
    re.IGNORECASE,
)

def _media_generation_model_identity(model: dict[str, Any]) -> str:
    return " ".join(
        str(model.get(key) or "")
        for key in (
            "id",
            "label",
            "name",
            "model",
            "endpoint",
            "usage",
        )
    )


def _model_declares_no_image_edit(model: dict[str, Any] | None) -> bool:
    if not isinstance(model, dict):
        return False
    supports = {
        str(item).strip().lower()
        for item in model.get("supports", [])
        if str(item).strip()
    } if isinstance(model.get("supports"), list) else set()
    return bool(supports) and "image_edit" not in supports


def validate_image_model_inputs(
    model: dict[str, Any],
    *,
    image_edit: bool = False,
    reference_count: int = 0,
) -> int | None:
    if image_edit and _model_declares_no_image_edit(model):
        raise RuntimeError(f"当前图片模型 {model.get('id') or 'unknown'} 未声明支持图片编辑")
    try:
        limit = int(model["max_reference_images"]) if model.get("max_reference_images") is not None else None
    except (TypeError, ValueError):
        limit = None
    if limit is not None and reference_count > limit:
        raise RuntimeError(
            f"参考图超过模型数量上限：当前 {reference_count} 张，模型最多支持 {limit} 张；"
            "已阻断生成，不能裁掉多余参考图后提交不完整资料。"
        )
    return limit


def _storyboard_video_reference_limit(model: dict[str, Any]) -> int | None:
    try:
        value = int(model.get("max_reference_images") or model.get("maxReferenceImages") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _model_supports_storyboard_video_generation(model: dict[str, Any]) -> bool:
    supports = {
        str(item).strip().lower()
        for item in model.get("supports", [])
        if str(item).strip()
    } if isinstance(model.get("supports"), list) else set()
    durations = _normalize_duration_options(
        model.get("durations")
        or model.get("allowedDurations")
        or model.get("allowed_durations")
    )
    if not durations:
        return False
    reference_limit = _storyboard_video_reference_limit(model)
    has_storyboard_reference = bool(
        model.get("supports_storyboard_reference_image") is True
        or model.get("supportsStoryboardReferenceImage") is True
        or "storyboard_reference_image" in supports
    )
    has_multi_reference = bool(
        (
            model.get("supports_multi_reference_images") is True
            or model.get("supportsMultiReferenceImages") is True
            or "multi_reference_video" in supports
        )
        and (reference_limit or 0) >= 2
    )
    has_native_audio = bool(
        model.get("audio") is True
        or model.get("supports_native_audio") is True
        or model.get("supportsNativeAudio") is True
        or "native_audio" in supports
    )
    return has_storyboard_reference and has_multi_reference and has_native_audio


def _model_visible_for_media_generation(model: dict[str, Any], media_type: str) -> bool:
    from utils.video_model_capabilities import video_model_capability

    if media_type not in {"image", "video"}:
        return True
    model_type = str(model.get("type") or "").strip().lower()
    if model_type and model_type != media_type:
        return False
    endpoint_type = media_endpoint_type(model.get("endpoint") or "")
    if endpoint_type and endpoint_type != media_type:
        return False
    # Explicit, locally adapted video contracts can legitimately contain
    # "audio" in a workflow ID. Keep the name fallback for unknown models.
    adapted_video = media_type == "video" and endpoint_type == "video" and video_model_capability(model) is not None
    if _NON_MEDIA_GENERATION_MODEL_RE.search(_media_generation_model_identity(model)) and not adapted_video:
        return False
    if media_type == "video" and not _model_supports_storyboard_video_generation(model):
        canonical = video_model_capability(model) or {}
        replacement_modes = (canonical.get("adapter_capabilities") or {}).get("task_types") or []
        if "video.character_replace" in replacement_modes:
            return bool(_normalize_duration_options(model.get("durations")))
        native_modes = ((model.get("adapter_capabilities") or {}).get("keyframe_visual_inputs") or {}).get("modes")
        if not native_modes or not _normalize_duration_options(model.get("durations")):
            return False
    return True


def _provider_specific_model_id(
    provider_id: str,
    model_id: Any,
    provider_preset_id: str | None = None,
) -> str:
    raw = str(model_id or "").strip() or "model"
    if raw.startswith(f"{provider_id}:"):
        return raw
    preset_id = _normalize_provider_id(provider_preset_id)
    if preset_id and provider_id != preset_id and ":" in raw:
        return f"{provider_id}:{raw.split(':', 1)[1]}"
    if provider_id and ":" not in raw and "/" not in raw:
        return f"{provider_id}:{raw}"
    return raw


def _provider_text_model_supports_vision(provider_id: str, model_id: str) -> bool:
    normalized_provider_id = _normalize_provider_id(provider_id)
    normalized_model_id = str(model_id or "").strip().lower()
    adapter_id = _normalize_provider_adapter_id(normalized_provider_id)
    if adapter_id == "openai-compatible":
        if normalized_model_id.startswith(("gpt-", "chatgpt-")):
            return True
        return False
    if adapter_id == "anthropic-compatible":
        if normalized_model_id.startswith("claude"):
            return True
        if normalized_model_id.startswith("deepseek"):
            return True
        return normalized_provider_id == "minimax" and normalized_model_id.startswith(("minimax-m3", "minimax-m3.1"))
    if adapter_id == "gemini-compatible":
        return normalized_model_id.startswith("gemini-") and "flash-lite" not in normalized_model_id
    if adapter_id == "ark-seedance":
        if normalized_model_id.startswith("doubao-seed-"):
            return True
    if normalized_provider_id == "openai":
        return normalized_model_id.startswith("gpt-")
    if normalized_provider_id == "anthropic":
        return normalized_model_id.startswith("claude")
    if normalized_provider_id == "ark-seedance":
        return normalized_model_id.startswith("doubao-seed-")
    if normalized_provider_id == "gemini":
        return normalized_model_id.startswith("gemini-") and "flash-lite" not in normalized_model_id
    return False


_REMOTE_MODEL_METADATA_KEYS = (
    "api_model_id",
    "model_exclusion_status",
    "model_exclusion_reason",
    "model_exclusion_replacement",
    "model_exclusion_source",
    "capability_routes",
    "discovery_source",
    "agent_support_source",
    "agent_route",
    "agent_note",
    "agent_protocol_support",
    "agent_only",
    "catalog_source_url",
    "catalog_only",
    "catalog_scope",
    "auth_checked",
    "entitlement_checked",
    "generation_verified",
    "classification_source",
    "classification_rule",
    "model_vendor",
    "vendor_source",
    "catalog_model_id",
    "catalog_match",
    "input_modalities",
    "output_modalities",
    "modalities",
    "architecture",
    "features",
    "inference_metadata",
    "api_capabilities",
    "support_api_protocols",
    "endpoint_constraints",
    "aspect_ratios",
    "routing_source",
    "routing_status",
    "routing_note",
    "supported_endpoint_types",
    "resolutions",
    "default_resolution",
    "image_resolution_schema",
    "imageResolutionSchema",
    "duration_resolution_constraints",
    "durationResolutionConstraints",
    "durations",
    "allowedDurations",
    "image_output_formats",
    "audio",
    "max_reference_images",
    "supports_storyboard_reference_image",
    "supports_multi_reference_images",
    "supports_native_audio",
    "prompt_hard_limit_chars",
    "official_prompt_limit_chars",
    "final_prompt_profile",
    "prompt_timing_style",
    "capability_source",
    "capability_source_url",
    "capability_note",
    "official_capabilities",
    "adapter_capabilities",
    "reference_image_limit_source",
    "reference_image_limit_source_url",
    "reference_image_limit_note",
    "reference_image_input_max_long_edge",
    "reference_image_input_max_bytes",
    "reference_image_input_source",
    "reference_image_input_source_url",
    "reference_image_input_note",
    "reference_image_transport_verified",
    "reference_image_transport_unverified",
    "referenceImageLimitSource",
    "referenceImageLimitSourceUrl",
    "referenceImageLimitNote",
    "referenceImageInputMaxLongEdge",
    "referenceImageInputMaxBytes",
    "referenceImageInputSource",
    "referenceImageInputSourceUrl",
    "referenceImageInputNote",
    "referenceImageTransportVerified",
    "referenceImageTransportUnverified",
    "supportsStoryboardReferenceImage",
    "supportsMultiReferenceImages",
    "supportsNativeAudio",
    "promptHardLimitChars",
    "officialPromptLimitChars",
    "finalPromptProfile",
    "promptTimingStyle",
    "capabilitySource",
    "capabilitySourceUrl",
    "capabilityNote",
    "officialCapabilities",
    "adapterCapabilities",
    "supports",
    "usage",
)


def _remote_model_entry_id(entry: Any) -> str:
    if isinstance(entry, dict):
        raw = (
            entry.get("model_id")
            or entry.get("modelId")
            or entry.get("id")
            or entry.get("name")
            or ""
        )
    else:
        raw = entry
    model_id = str(raw or "").strip()
    if model_id.startswith("models/"):
        model_id = model_id.split("/", 1)[1]
    return model_id


def _normalize_remote_model_entries(entries: list[Any] | None) -> list[Any]:
    rows: list[Any] = []
    seen: set[str] = set()
    for entry in entries or []:
        model_id = _remote_model_entry_id(entry)
        if not model_id or model_id in seen:
            continue
        rows.append(copy.deepcopy(entry) if isinstance(entry, dict) else model_id)
        seen.add(model_id)
    return rows


def _remote_model_row(provider: dict[str, Any], remote_model: Any) -> dict[str, Any]:
    entry = remote_model if isinstance(remote_model, dict) else {}
    from utils.model_classification import classify_model

    raw_id = _remote_model_entry_id(remote_model)
    if raw_id.startswith("models/"):
        raw_id = raw_id.split("/", 1)[1]
    provider_id = _normalize_provider_id(provider.get("id")) or _provider_service_id(provider)
    provider_preset_id = _provider_service_id(provider)
    adapter_id = _provider_adapter_id(provider)
    endpoint_format = _adapter_endpoint_format(provider)
    endpoint = str(
        entry.get("endpoint")
        or entry.get("endpoint_key")
        or entry.get("endpointKey")
        or entry.get("generation_endpoint")
        or entry.get("generationEndpoint")
        or ""
    ).strip()
    if not endpoint and adapter_id != "anthropic-compatible" and entry.get("routing_source") != "relay-discovery":
        endpoint = infer_model_endpoint(raw_id, endpoint_format, provider=provider)
    endpoint_type = media_endpoint_type(endpoint)
    explicit_type = str(entry.get("media_type") or entry.get("mediaType") or entry.get("type") or "").strip().lower()
    classification = classify_model(entry)
    classified_type = next(
        (kind for kind in classification["kinds"] if kind in {"image", "video", "text"}),
        "",
    )
    if endpoint_type in {"image", "video", "text"}:
        model_type = endpoint_type
    elif explicit_type in {"image", "video", "text"}:
        model_type = explicit_type
    elif classified_type:
        model_type = classified_type
    else:
        # A model that cannot be classified is diagnostic-only. The provider's
        # selected capability must never promote it to a text model.
        model_type = "unknown"
    row: dict[str, Any] = {
        "id": _provider_specific_model_id(provider_id, raw_id, provider_preset_id),
        "provider_preset_id": provider_preset_id,
        "adapter_id": adapter_id,
        "adapterId": adapter_id,
        "label": str(entry.get("display_name") or entry.get("displayName") or entry.get("label") or raw_id),
        "type": model_type,
        "model_vendor": classification["vendor"],
        "vendor_source": classification["vendor_source"],
        "classification_source": classification["source"],
        "classification_rule": classification["rule"],
        "resolutions": [],
        "usage": "远程发现模型",
    }
    if entry.get("routing_source") == "relay-discovery":
        row["id"] = f"{provider_id}:{entry.get('api_model_id') or raw_id}"
    if endpoint:
        row["endpoint"] = endpoint
    for key in _REMOTE_MODEL_METADATA_KEYS:
        if key in entry:
            row[key] = copy.deepcopy(entry[key])
    if "defaultResolution" in entry and "default_resolution" not in row:
        row["default_resolution"] = entry["defaultResolution"]
    if "imageOutputFormats" in entry and "image_output_formats" not in row:
        row["image_output_formats"] = entry["imageOutputFormats"]
    if "maxReferenceImages" in entry and "max_reference_images" not in row:
        row["max_reference_images"] = entry["maxReferenceImages"]
    if "referenceImageLimitSource" in entry and "reference_image_limit_source" not in row:
        row["reference_image_limit_source"] = entry["referenceImageLimitSource"]
    if "referenceImageLimitSourceUrl" in entry and "reference_image_limit_source_url" not in row:
        row["reference_image_limit_source_url"] = entry["referenceImageLimitSourceUrl"]
    if "referenceImageLimitNote" in entry and "reference_image_limit_note" not in row:
        row["reference_image_limit_note"] = entry["referenceImageLimitNote"]
    if "referenceImageInputMaxLongEdge" in entry and "reference_image_input_max_long_edge" not in row:
        row["reference_image_input_max_long_edge"] = entry["referenceImageInputMaxLongEdge"]
    if "referenceImageInputMaxBytes" in entry and "reference_image_input_max_bytes" not in row:
        row["reference_image_input_max_bytes"] = entry["referenceImageInputMaxBytes"]
    if "referenceImageInputSource" in entry and "reference_image_input_source" not in row:
        row["reference_image_input_source"] = entry["referenceImageInputSource"]
    if "referenceImageInputSourceUrl" in entry and "reference_image_input_source_url" not in row:
        row["reference_image_input_source_url"] = entry["referenceImageInputSourceUrl"]
    if "referenceImageInputNote" in entry and "reference_image_input_note" not in row:
        row["reference_image_input_note"] = entry["referenceImageInputNote"]
    if "durationResolutionConstraints" in entry and "duration_resolution_constraints" not in row:
        row["duration_resolution_constraints"] = entry["durationResolutionConstraints"]
    if model_type == "image":
        if raw_id.lower() == "gpt-image-2":
            row.setdefault("image_output_formats", list(IMAGE_OUTPUT_FORMATS))
            row.setdefault("max_reference_images", 16)
            row.setdefault("reference_image_limit_source", "official")
            row.setdefault(
                "reference_image_limit_source_url",
                "https://developers.openai.com/api/reference/resources/images/methods/edit/",
            )
            row.setdefault(
                "reference_image_limit_note",
                "OpenAI Images edit API: GPT image models accept up to 16 input images.",
            )
            row.setdefault("reference_image_input_max_long_edge", _GPT_IMAGE_MAX_LONG_EDGE)
            row.setdefault("reference_image_input_max_bytes", REFERENCE_IMAGE_INPUT_DEFAULT_MAX_BYTES)
            row.setdefault("reference_image_input_source", "application")
            row.setdefault(
                "reference_image_input_note",
                "Reference images are prepared at the provider-input valve only; model outputs are saved unchanged.",
            )
            row["reference_image_transport_verified"] = True
            row.pop("reference_image_transport_unverified", None)
            row.pop("referenceImageTransportUnverified", None)
            supports = [
                str(item).strip()
                for item in row.get("supports", [])
                if str(item).strip()
            ] if isinstance(row.get("supports"), list) else []
            lowered_supports = {item.lower() for item in supports}
            for marker in (
                "storyboard_image",
                "storyboard_panel",
                "storyboard_sheet",
                "asset_image",
                "reference_image",
                "image_edit",
                "multi_reference_image",
            ):
                if marker not in lowered_supports:
                    supports.append(marker)
            row["supports"] = supports
            row["resolutions"] = row.get("resolutions") or OPENAI_GPT_IMAGE_2_RESOLUTIONS
            row["default_resolution"] = row.get("default_resolution") or OPENAI_GPT_IMAGE_2_DEFAULT_RESOLUTION
            row["usage"] = row.get("usage") or "远程发现 GPT Image 2 图片模型"
            return row
        row["resolutions"] = row.get("resolutions") or STANDARD_COMPATIBLE_IMAGE_RESOLUTIONS
        row["default_resolution"] = row.get("default_resolution") or "2K"
        row["usage"] = row.get("usage") or "远程发现图片模型"
    elif model_type == "video":
        row["resolutions"] = row.get("resolutions") or STANDARD_COMPATIBLE_VIDEO_RESOLUTIONS
        row["default_resolution"] = row.get("default_resolution") or "720p"
        durations = _normalize_duration_options(
            row.get("durations")
            or row.get("allowedDurations")
        )
        if durations:
            row["durations"] = durations
            row["allowedDurations"] = durations
        else:
            row.pop("durations", None)
            row.pop("allowedDurations", None)
            row["durationMetadataMissing"] = True
        row["usage"] = row.get("usage") or "远程发现视频模型"
    else:
        row["usage"] = "远程发现文本 / 智能体模型"
        if endpoint and media_endpoint_type(endpoint) == "text":
            row["endpoint"] = endpoint
        if _model_supports_vision_input(row):
            row["supports"] = ["vision"]
    return row


def _last_test_remote_model_ids(provider: dict[str, Any]) -> list[str]:
    last_test = provider.get("last_test") if isinstance(provider.get("last_test"), dict) else {}
    raw_ids = last_test.get("remoteModelIds") or last_test.get("remote_model_ids") or []
    if not isinstance(raw_ids, list):
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for item in raw_ids:
        model_id = str(item or "").strip()
        if model_id.startswith("models/"):
            model_id = model_id.split("/", 1)[1]
        if model_id and model_id not in seen:
            ids.append(model_id)
            seen.add(model_id)
    return ids


def _last_test_remote_model_entries(provider: dict[str, Any]) -> list[Any]:
    last_test = provider.get("last_test") if isinstance(provider.get("last_test"), dict) else {}
    raw_models = last_test.get("remoteModels") or last_test.get("remote_models")
    if isinstance(raw_models, list) and raw_models:
        return _normalize_remote_model_entries(raw_models)
    available_models = last_test.get("availableModels") or last_test.get("available_models")
    if isinstance(available_models, list) and available_models:
        entries: list[Any] = []
        provider_id = _normalize_provider_id(provider.get("id"))
        for model in available_models:
            if not isinstance(model, dict):
                continue
            entry = copy.deepcopy(model)
            raw_id = str(entry.get("id") or "").strip()
            if provider_id and raw_id.startswith(f"{provider_id}:"):
                entry["id"] = raw_id.split(":", 1)[1]
            entries.append(entry)
        has_real_model_or_endpoint = any(
            not _is_legacy_generic_model_id(entry.get("id") if isinstance(entry, dict) else entry)
            or bool(
                isinstance(entry, dict)
                and (
                    entry.get("endpoint")
                    or entry.get("endpointKey")
                    or entry.get("generation_endpoint")
                    or entry.get("generationEndpoint")
                )
            )
            for entry in entries
        )
        if entries and has_real_model_or_endpoint:
            return _normalize_remote_model_entries(entries)
    return _last_test_remote_model_ids(provider)


def _is_legacy_generic_model_id(model_id: Any) -> bool:
    raw = str(model_id or "").strip()
    if raw in LEGACY_GENERIC_PROVIDER_MODEL_IDS:
        return True
    suffix = raw.split(":", 1)[1] if ":" in raw else raw
    return suffix in {"image-model", "video-model", "text-model"}


_ALIGNED_MODEL_METADATA_KEYS = (
    "type",
    "resolutions",
    "default_resolution",
    "image_resolution_schema",
    "imageResolutionSchema",
    "durations",
    "duration_resolution_constraints",
    "image_output_formats",
    "audio",
    "max_reference_images",
    "supports_storyboard_reference_image",
    "supports_multi_reference_images",
    "supports_native_audio",
    "prompt_hard_limit_chars",
    "official_prompt_limit_chars",
    "final_prompt_profile",
    "prompt_timing_style",
    "capability_source",
    "capability_source_url",
    "capability_note",
    "official_capabilities",
    "adapter_capabilities",
    "reference_image_limit_source",
    "reference_image_limit_source_url",
    "reference_image_limit_note",
    "reference_image_input_max_long_edge",
    "reference_image_input_max_bytes",
    "reference_image_input_source",
    "reference_image_input_source_url",
    "reference_image_input_note",
    "reference_image_transport_verified",
    "reference_image_transport_unverified",
    "referenceImageLimitSource",
    "referenceImageLimitSourceUrl",
    "referenceImageLimitNote",
    "referenceImageInputMaxLongEdge",
    "referenceImageInputMaxBytes",
    "referenceImageInputSource",
    "referenceImageInputSourceUrl",
    "referenceImageInputNote",
    "referenceImageTransportVerified",
    "referenceImageTransportUnverified",
    "supportsStoryboardReferenceImage",
    "supportsMultiReferenceImages",
    "supportsNativeAudio",
    "promptHardLimitChars",
    "officialPromptLimitChars",
    "finalPromptProfile",
    "promptTimingStyle",
    "capabilitySource",
    "capabilitySourceUrl",
    "capabilityNote",
    "officialCapabilities",
    "adapterCapabilities",
    "supports",
    "usage",
    "endpoint",
)


def _aligned_model_catalog_key(provider: dict[str, Any]) -> str:
    adapter_id = _provider_adapter_id(provider)
    if adapter_id == "gemini-compatible":
        return "gemini"
    provider_id = _provider_service_id(provider) or _normalize_provider_id(provider.get("id"))
    return provider_id if provider_id in BUILTIN_PROVIDER_MODELS else ""


def _align_provider_model_metadata(provider: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    from .model_provider_config import _api_model_name
    if model.get("routing_source") == "relay-discovery":
        return _normalize_provider_model_metadata(copy.deepcopy(model))
    catalog_key = _aligned_model_catalog_key(provider)
    model_name = _api_model_name(model.get("id")).lower()
    if not catalog_key or not model_name:
        return _normalize_provider_model_metadata(_with_model_generation_endpoint(provider, model))
    for catalog_model in BUILTIN_PROVIDER_MODELS.get(catalog_key, []):
        if _api_model_name(catalog_model.get("id")).lower() != model_name:
            continue
        normalized = copy.deepcopy(model)
        for key in _ALIGNED_MODEL_METADATA_KEYS:
            if key in catalog_model:
                normalized[key] = copy.deepcopy(catalog_model[key])
        if catalog_key == "ark-seedance" and not str(normalized.get("endpoint") or "").strip():
            if str(normalized.get("type") or catalog_model.get("type") or "").strip() == "image":
                normalized["endpoint"] = "ark-seedream"
            elif model_name.startswith("doubao-seedance-"):
                normalized["endpoint"] = "ark-seedance"
        if catalog_model.get("reference_image_transport_verified") or catalog_model.get("referenceImageTransportVerified"):
            normalized.pop("reference_image_transport_unverified", None)
            normalized.pop("referenceImageTransportUnverified", None)
        if not str(normalized.get("label") or "").strip():
            normalized["label"] = catalog_model.get("label") or model.get("id")
        return _normalize_provider_model_metadata(_with_model_generation_endpoint(provider, normalized))
    normalized = _normalize_provider_model_metadata(model)
    normalized = _with_model_generation_endpoint(provider, normalized)
    if (
        normalized.get("type") == "text"
        and _model_supports_vision_input(normalized)
    ):
        supports = [
            str(item).strip()
            for item in normalized.get("supports", [])
            if str(item).strip()
        ] if isinstance(normalized.get("supports"), list) else []
        if "vision" not in {item.lower() for item in supports}:
            normalized["supports"] = [*supports, "vision"]
    return normalized


def _provider_model_available_for_group(provider: dict[str, Any], model: dict[str, Any], group: str) -> bool:
    """Execution readiness, not membership in the discovered model directory."""
    from utils.text_model_contracts import general_text_pending_reason
    from utils.model_exclusions import adapted_model_is_excluded

    if group == "video":
        from utils.video_model_capabilities import RETIRED_NEWAPI_VEO_MODELS

        model_name = str(model.get("api_model_id") or model.get("id") or "").split(":", 1)[-1]
        if model_name in RETIRED_NEWAPI_VEO_MODELS:
            return False

    if group in {"text", "agent"} and general_text_pending_reason(model):
        return False
    if group in {"text", "agent"} and adapted_model_is_excluded(
        {**model, "provider_preset_id": _provider_service_id(provider)}, output_kind=group,
    ):
        return False
    if model.get("routing_status") == "pending" and group != "agent":
        return False
    if group in {"image", "video"}:
        return _model_visible_for_media_generation(model, group) and _provider_supports_direct_media_generation(provider, group, model)
    if group != "agent":
        return True
    from utils.agent_model_contracts import agent_pending_reason, tool_calling_support

    if tool_calling_support(model) is False:
        return False
    route = model.get("agent_route") or {}
    return bool(route.get("baseUrl")) and not agent_pending_reason(model, route)


def _provider_declared_and_discovered_models(
    provider: dict[str, Any],
    remote_model_ids: list[Any] | None = None,
) -> list[dict[str, Any]]:
    models = [
        copy.deepcopy(model)
        for model in provider.get("models", [])
        if isinstance(model, dict)
    ]
    discovered_entries = _normalize_remote_model_entries(
        remote_model_ids if remote_model_ids is not None else _last_test_remote_model_entries(provider)
    )
    discovered_ids = [_remote_model_entry_id(entry) for entry in discovered_entries]
    real_models = [
        model for model in models if not _is_legacy_generic_model_id(model.get("id"))
    ]
    if len(real_models) != len(models):
        models = real_models
    if not discovered_ids:
        return [
            _align_provider_model_metadata(provider, model)
            for model in models
            if isinstance(model, dict)
        ]

    existing = {
        _provider_specific_model_id(
            _normalize_provider_id(provider.get("id")),
            model.get("id"),
            _provider_service_id(provider),
        )
        for model in models
        if model.get("id")
    }
    for remote_entry in discovered_entries:
        row = _remote_model_row(provider, remote_entry)
        if row["id"] in existing:
            continue
        models.append(row)
        existing.add(row["id"])
    return [
        _align_provider_model_metadata(provider, model)
        for model in models
        if isinstance(model, dict)
    ]


def _provider_available_models_for_test(
    provider: dict[str, Any],
    remote_model_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    return _provider_declared_and_discovered_models(provider, remote_model_ids)


def _provider_model_capability_views(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from utils.relay_provider_probes import relay_model_for_capability

    views = []
    for model in models:
        routes = model.get("capability_routes")
        if not isinstance(routes, dict):
            views.append(model)
            continue
        for kind in ("image", "video", "text"):
            view = relay_model_for_capability(model, kind)
            if view is not None:
                views.append(view)
    return views


def _model_capabilities_with_provider_models(
    capabilities: dict[str, Any],
    providers: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    source_capabilities = capabilities if isinstance(capabilities, dict) else DEFAULT_MODEL_CAPABILITIES
    merged = {
        key: copy.deepcopy(source_capabilities.get(key, []))
        if isinstance(source_capabilities.get(key), list)
        else []
        for key in ("image", "video", "agent", "text")
    }
    for key in ("image", "video", "agent", "text"):
        if not isinstance(merged.get(key), list):
            merged[key] = []
    for key in ("image", "video"):
        merged[key] = [
            _with_model_resolution_metadata(item, key)
            for item in merged.get(key, [])
            if isinstance(item, dict) and _model_visible_for_media_generation(item, key)
        ]
    direct_provider_ids = {
        provider_id
        for provider in providers
        if isinstance(provider, dict)
        for provider_id in [_normalize_provider_id(provider.get("id"))]
        if provider_id and provider_id == _provider_service_id(provider)
    }
    if direct_provider_ids:
        for key in ("image", "video", "agent", "text"):
            merged[key] = [
                item
                for item in merged.get(key, [])
                if not (
                    isinstance(item, dict)
                    and _normalize_provider_id(item.get("provider_id")) in direct_provider_ids
                )
            ]

    existing_ids: dict[str, set[str]] = {
        key: {
            str(item.get("id"))
            for item in merged.get(key, [])
            if isinstance(item, dict) and item.get("id")
        }
        for key in ("image", "video", "agent", "text")
    }

    for provider in providers:
        if not isinstance(provider, dict):
            continue
        for target, model in _provider_models_as_capabilities(provider):
            if model["id"] not in existing_ids[target]:
                merged[target].append(model)
                existing_ids[target].add(model["id"])
    return merged


def _empty_model_capabilities() -> dict[str, list[dict[str, Any]]]:
    return {"image": [], "video": [], "agent": [], "text": []}


def _is_connected_provider(provider: dict[str, Any]) -> bool:
    return bool(
        provider.get("configured")
        and provider.get("api_key")
        and str(provider.get("connection_status") or "") == "connected"
    )


def _provider_models_as_capabilities(
    provider: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    from utils.model_exclusions import annotate_model_replacements

    provider_id = _normalize_provider_id(provider.get("id"))
    if not provider_id:
        return []
    provider_preset_id = _provider_service_id(provider)
    adapter_id = _provider_adapter_id(provider)
    raw_capabilities = provider.get("capabilities", [])
    capabilities = _normalize_provider_capabilities(raw_capabilities)
    capability_set = set(capabilities)
    provider_title = str(provider.get("title") or provider.get("name") or provider_id)
    rows: list[tuple[str, dict[str, Any]]] = []
    for raw_model in _provider_model_capability_views(_provider_declared_and_discovered_models(provider)):
        if not isinstance(raw_model, dict):
            continue
        if not _provider_model_matches_capabilities(
            {**raw_model, "provider_preset_id": provider_preset_id}, capabilities,
        ):
            continue
        model_type = str(raw_model.get("type") or "")
        targets: list[str] = []
        if model_type == "image":
            targets = ["image"]
        elif model_type == "video":
            targets = ["video"]
        elif model_type == "text":
            if "agent" in capability_set:
                targets.append("agent")
            if "text_generation" in capability_set and not raw_model.get("agent_only"):
                targets.append("text")
        if not targets:
            continue

        model = copy.deepcopy(raw_model)
        model["id"] = _provider_specific_model_id(
            provider_id,
            model.get("id"),
            provider_preset_id,
        )
        model["provider_id"] = provider_id
        model["provider_preset_id"] = provider_preset_id
        model["adapter_id"] = adapter_id
        model["adapterId"] = adapter_id
        model = _with_model_generation_endpoint(provider, model)
        label = str(model.get("label") or model["id"])
        if " / " not in label:
            model["label"] = f"{provider_title} / {label}"
        for target in targets:
            view = _with_model_resolution_metadata(model, target)
            view["available"] = _provider_model_available_for_group(provider, model, target)
            view["availability_note"] = "" if view["available"] else "待适配"
            if target in {"text", "agent"}:
                from utils.model_exclusions import adapted_model_exclusion
                for field in (
                    "model_exclusion_status",
                    "model_exclusion_reason",
                    "model_exclusion_replacement",
                    "model_exclusion_source",
                ):
                    view.pop(field, None)
                exclusion = adapted_model_exclusion(
                    {**model, "provider_preset_id": provider_preset_id}, output_kind=target,
                )
                if exclusion["excluded"]:
                    view.update({
                        "model_exclusion_status": exclusion["status"],
                        "model_exclusion_reason": exclusion["reason"],
                        "model_exclusion_replacement": exclusion["replacement"],
                        "model_exclusion_source": exclusion["source"],
                    })
            rows.append((target, view))
    return [
        (target, model)
        for target in ("image", "video", "agent", "text")
        for model in annotate_model_replacements(
            [model for kind, model in rows if kind == target], output_kind=target,
        )
    ]


_AVAILABLE_CAPABILITIES_LOCK = threading.RLock()
_AVAILABLE_CAPABILITIES_KEY: bytes | None = None
_AVAILABLE_CAPABILITIES: dict[str, list[dict[str, Any]]] | None = None


def _available_model_capabilities(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    global _AVAILABLE_CAPABILITIES_KEY, _AVAILABLE_CAPABILITIES
    providers = config.get("providers", [])
    # Content-based invalidation also covers callers editing an unsaved config copy.
    key = hashlib.sha256(json.dumps(providers, sort_keys=True, ensure_ascii=False).encode("utf-8")).digest()
    with _AVAILABLE_CAPABILITIES_LOCK:
        if _AVAILABLE_CAPABILITIES is None or key != _AVAILABLE_CAPABILITIES_KEY:
            _AVAILABLE_CAPABILITIES = _build_available_model_capabilities(config)
            _AVAILABLE_CAPABILITIES_KEY = key
        return copy.deepcopy(_AVAILABLE_CAPABILITIES)


def _build_available_model_capabilities(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    capabilities = _empty_model_capabilities()
    seen: dict[str, set[str]] = {key: set() for key in capabilities}
    providers = config.get("providers", [])
    if not isinstance(providers, list):
        return capabilities
    for provider in providers:
        if not isinstance(provider, dict) or not _is_connected_provider(provider):
            continue
        for target, model in _provider_models_as_capabilities(provider):
            model_id = str(model.get("id") or "")
            if not model_id or model_id in seen[target]:
                continue
            capabilities[target].append(_with_model_resolution_metadata(model, target))
            seen[target].add(model_id)
    return capabilities


def _model_options_from_capabilities(capabilities: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    def visible_rows(key: str) -> list[dict[str, Any]]:
        rows = capabilities.get(key, [])
        if not isinstance(rows, list):
            return []
        return [
            item
            for item in rows
            if isinstance(item, dict) and not item.get("model_exclusion_status")
        ]

    def labels(key: str) -> list[str]:
        return [
            str(item.get("label") or item.get("id"))
            for item in visible_rows(key)
            if item.get("label") or item.get("id")
        ]

    video_durations = sorted(
        {
            int(duration)
            for item in visible_rows("video")
            for duration in (item.get("durations") or [])
            if isinstance(duration, int)
        }
    )
    video_resolutions = sorted(
        {
            str(resolution)
            for item in visible_rows("video")
            for resolution in (item.get("resolutions") or [])
        }
    )
    image_resolutions = sorted(
        {
            str(resolution)
            for item in visible_rows("image")
            for resolution in (item.get("resolutions") or [])
        }
    )
    return {
        "text": labels("text"),
        "agent": labels("agent"),
        "image": labels("image"),
        "video": labels("video"),
        "duration_seconds": video_durations,
        "video_resolution": video_resolutions,
        "storyboard_image_size": image_resolutions,
    }


def _find_model(model_id: str | None, model_type: str, capabilities: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not model_id:
        return None
    capability_map = capabilities if isinstance(capabilities, dict) else DEFAULT_MODEL_CAPABILITIES
    needle = re.sub(r"\s+", " ", str(model_id or "").strip()).lower()
    for item in capability_map.get(model_type, []):
        if isinstance(item, dict) and item.get("id") == model_id:
            return item
    for item in capability_map.get(model_type, []):
        if not isinstance(item, dict):
            continue
        aliases = [
            item.get("id"),
            item.get("label"),
            item.get("display_name"),
            item.get("displayName"),
            item.get("name"),
        ]
        provider_label = item.get("providerLabel") or item.get("provider_label") or item.get("provider")
        label = item.get("label") or item.get("display_name") or item.get("displayName")
        if provider_label and label:
            aliases.append(f"{provider_label} / {label}")
        if needle in {re.sub(r"\s+", " ", str(alias or "").strip()).lower() for alias in aliases if alias}:
            return item
    return None


def _model_supports_vision_input(model: dict[str, Any] | None) -> bool:
    from .model_provider_config import _api_model_name
    if not isinstance(model, dict):
        return False
    for container in (model, model.get("modalities"), model.get("architecture"), model.get("inference_metadata")):
        if isinstance(container, dict):
            inputs = container.get("input_modalities") or container.get("input_modality")
            if isinstance(inputs, list) and inputs:
                return "image" in {str(item).lower() for item in inputs}
    supports = {
        str(item).strip().lower()
        for item in model.get("supports", [])
        if str(item).strip()
    } if isinstance(model.get("supports"), list) else set()
    if {"vision", "image_input", "multimodal"} & supports:
        return True
    provider_id = _normalize_provider_id(
        model.get("provider_preset_id")
        or model.get("providerPresetId")
        or model.get("provider_id")
    )
    model_name = _api_model_name(model.get("id"))
    return _provider_text_model_supports_vision(provider_id, model_name)


def _resolution_text_key(value: Any) -> str:
    return str(value or "").strip().replace("×", "x").replace("*", "x").lower()


def _normalize_aspect_ratio_key(value: Any) -> str:
    aw, ah = parse_aspect_ratio(str(value or ""))
    return f"{aw}:{ah}"


def _generic_image_size(
    resolution: Any,
    aspect_ratio: Any,
    *,
    default_short: int = 1024,
    max_long_edge: int | None = None,
    max_total_pixels: int | None = None,
    max_ratio: float | None = None,
) -> str:
    width, height = image_size_for_resolution(
        str(resolution or "") or None,
        str(aspect_ratio or ""),
        default_long_edge=default_short,
        round_to=16,
        max_long_edge=max_long_edge,
        max_total_pixels=max_total_pixels,
        max_ratio=max_ratio,
    )
    return f"{width}x{height}"


def _explicit_image_dimensions(value: Any) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\s*[xX×*]\s*(\d+)\s*", str(value or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _explicit_image_size(value: Any) -> str:
    dimensions = _explicit_image_dimensions(value)
    if not dimensions:
        return ""
    return f"{dimensions[0]}x{dimensions[1]}"


def _image_resolution_options_for_aspect(
    options: list[str],
    aspect_ratio: str,
    model: dict[str, Any] | None = None,
    *,
    has_reference_images: bool | None = None,
) -> list[str]:
    normalized_options = [str(option) for option in options if str(option)]
    if not normalized_options:
        return []
    schema = image_resolution_schema_for_model(model) if isinstance(model, dict) else {}
    if schema:
        return image_resolution_options_for_schema(
            normalized_options,
            aspect_ratio,
            schema,
            has_reference_images=has_reference_images,
        )
    aw, ah = parse_aspect_ratio(aspect_ratio)
    filtered: list[str] = []
    for option in normalized_options:
        dimensions = _explicit_image_dimensions(option)
        if not dimensions:
            filtered.append(option)
            continue
        width, height = dimensions
        if aw == ah and width == height:
            filtered.append(option)
        elif aw > ah and width >= height:
            filtered.append(option)
        elif ah > aw and height >= width:
            filtered.append(option)
    return filtered or normalized_options


def _dashscope_exceeds_standard_budget(size: Any) -> bool:
    normalized = _resolution_text_key(size).upper()
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


def _dashscope_image_size(model: dict[str, Any], resolution: Any, aspect_ratio: Any) -> str:
    from .model_provider_config import _api_model_name
    model_name = _api_model_name(model.get("id")).lower()
    explicit = str(resolution or "").strip()
    explicit_size = _explicit_image_size(explicit)
    if explicit_size:
        return explicit_size
    if model_name.startswith("wan"):
        max_total = (
            _DASHSCOPE_FOURK_PIXEL_BUDGET
            if _dashscope_exceeds_standard_budget(explicit or "2K")
            else _DASHSCOPE_STANDARD_PIXEL_BUDGET
        )
        return _generic_image_size(
            explicit or "2K",
            aspect_ratio,
            default_short=1440,
            max_total_pixels=max_total,
            max_ratio=_DASHSCOPE_MAX_RATIO,
        )
    if "qwen-image-edit" in model_name:
        return _generic_image_size(
            explicit or "2K",
            aspect_ratio,
            default_short=2048,
            max_long_edge=_DASHSCOPE_EDIT_MAX_LONG_EDGE,
            max_ratio=_DASHSCOPE_EDIT_MAX_RATIO,
        )
    return _generic_image_size(
        explicit or "2K",
        aspect_ratio,
        default_short=2048,
        max_total_pixels=_DASHSCOPE_STANDARD_PIXEL_BUDGET,
        max_ratio=_DASHSCOPE_MAX_RATIO,
    )


def _standard_video_size(resolution: Any, aspect_ratio: Any) -> str:
    aspect_key = _normalize_aspect_ratio_key(aspect_ratio)
    resolution_key = _resolution_text_key(resolution)
    presets = _VIDEO_SIZE_PRESETS.get(aspect_key, {})
    for key, size in presets.items():
        if key.lower() == resolution_key:
            return size

    if re.fullmatch(r"\d+\s*[xX×*]\s*\d+", str(resolution or "").strip()):
        raw = _resolution_text_key(resolution)
        left, right = raw.split("x", 1)
        width, height = int(left), int(right)
        target_aspect = _normalize_aspect_ratio_key(aspect_ratio)
        if target_aspect == "16:9":
            if width >= height:
                return f"{width}x{height}"
            return f"{height}x{width}"
        if target_aspect == "9:16":
            if height >= width:
                return f"{width}x{height}"
            return f"{height}x{width}"
        return f"{width}x{height}"

    short = resolution_to_short_edge(
        str(resolution or "") or None,
        tier_map=VIDEO_TIER_SHORT_EDGE,
        default_short=720,
    )
    width, height = aspect_size(str(aspect_ratio or ""), short, round_to=8)
    return f"{width}x{height}"


def _image_output_size(
    model: dict[str, Any] | None,
    resolution: Any,
    aspect_ratio: Any,
    *,
    has_reference_images: bool | None = None,
) -> str:
    from .model_provider_config import _api_model_name
    if not isinstance(model, dict):
        return _generic_image_size(resolution, aspect_ratio)
    schema_size = image_output_size_from_schema(
        image_resolution_schema_for_model(model),
        resolution,
        aspect_ratio,
        has_reference_images=has_reference_images,
    )
    if schema_size is not None:
        return schema_size
    provider_id = _normalize_provider_id(
        model.get("provider_preset_id")
        or model.get("providerPresetId")
        or model.get("provider_id")
    )
    model_name = _api_model_name(model.get("id")).lower()
    if provider_id == "dashscope":
        return _dashscope_image_size(model, resolution, aspect_ratio)
    if model_name == "gpt-image-2":
        return _generic_image_size(
            resolution,
            aspect_ratio,
            default_short=1024,
            max_long_edge=_GPT_IMAGE_MAX_LONG_EDGE,
            max_total_pixels=_GPT_IMAGE_MAX_TOTAL_PIXELS,
            max_ratio=_GPT_IMAGE_MAX_RATIO,
        )
    return _generic_image_size(resolution, aspect_ratio)


_IMAGE_RESOLUTION_DESCRIPTION_ASPECTS: tuple[tuple[str, str], ...] = (
    ("character", "16:9"),
    ("scene", "3:2"),
    ("prop", "2:1"),
    ("asset", "16:9"),
    ("storyboard", "16:9"),
)


def _model_resolution_description_options(model: dict[str, Any]) -> list[str]:
    rows = model.get("resolutions") if isinstance(model.get("resolutions"), list) else []
    options: list[str] = []
    seen: set[str] = set()
    for row in rows:
        option = str(row or "").strip()
        if not option or option in seen:
            continue
        options.append(option)
        seen.add(option)
    return options


def _image_resolution_descriptions(model: dict[str, Any]) -> dict[str, dict[str, str]]:
    options = _model_resolution_description_options(model)
    if not options:
        return {}
    descriptions: dict[str, dict[str, str]] = {}
    aspect_maps: dict[str, dict[str, str]] = {}
    for role, aspect_ratio in _IMAGE_RESOLUTION_DESCRIPTION_ASPECTS:
        role_map = {
            option: "自动尺寸" if option.lower() == "auto" else _image_output_size(model, option, aspect_ratio)
            for option in options
        }
        descriptions[role] = role_map
        aspect_maps.setdefault(aspect_ratio, role_map)
    descriptions.update(aspect_maps)
    return descriptions


def _with_model_resolution_metadata(model: dict[str, Any], media_type: str | None = None) -> dict[str, Any]:
    normalized = with_image_resolution_schema(model, media_type)
    resolved_media_type = str(media_type or normalized.get("type") or "").strip().lower()
    if resolved_media_type == "image":
        descriptions = _image_resolution_descriptions(normalized)
        if descriptions:
            normalized["resolution_descriptions"] = descriptions
            normalized["resolutionDescriptions"] = descriptions
    return normalized


def _video_output_size(_model: dict[str, Any] | None, resolution: Any, aspect_ratio: Any) -> str:
    return _standard_video_size(resolution, aspect_ratio)


def _normalize_resolution(value: Any, options: list[str], fallback: str) -> str:
    normalized_options = [str(option) for option in options if str(option)]
    for candidate in (value, fallback):
        candidate_text = str(candidate or "")
        if not candidate_text:
            continue
        if candidate_text in normalized_options:
            return candidate_text
        lowered = candidate_text.lower()
        for option in normalized_options:
            if option.lower() == lowered:
                return option
        alias = IMAGE_RESOLUTION_ALIASES.get(lowered)
        if alias:
            for option in normalized_options:
                if option == alias or option.lower() == alias.lower():
                    return option
        legacy_tier = LEGACY_IMAGE_RESOLUTION_TO_TIER.get(_resolution_text_key(candidate_text))
        if legacy_tier:
            for option in normalized_options:
                if option.lower() == legacy_tier.lower():
                    return option
    return normalized_options[0] if normalized_options else str(value or fallback)


def _normalize_image_output_format(value: Any) -> str:
    raw = str(value or "").strip().lower()
    normalized = "jpg" if raw == "jpeg" else raw
    return normalized if normalized in IMAGE_OUTPUT_FORMAT_VALUES else "auto"


def _model_image_output_formats(model: dict[str, Any] | None) -> list[str]:
    raw_formats = (model or {}).get("image_output_formats")
    if not isinstance(raw_formats, list):
        return []
    normalized = {
        fmt
        for value in raw_formats
        for fmt in [_normalize_image_output_format(value)]
        if fmt != "auto"
    }
    return [fmt for fmt in IMAGE_OUTPUT_FORMATS if fmt in normalized]


def _resolve_image_output_format(
    image_config: dict[str, Any],
    model: dict[str, Any] | None,
) -> str | None:
    output_format = _normalize_image_output_format(image_config.get("image_output_format"))
    if output_format == "auto":
        return None
    return output_format if output_format in _model_image_output_formats(model) else None


def _image_output_source_mime(output_format: str | None) -> str:
    if output_format == "jpg":
        return "image/jpeg"
    if output_format == "webp":
        return "image/webp"
    return "image/png"


def _model_reference_image_input_limits(model: dict[str, Any] | None) -> dict[str, Any]:
    def positive_int(*keys: str, default: int | None = None) -> int | None:
        if not isinstance(model, dict):
            return default
        for key in keys:
            try:
                parsed = int(model.get(key))
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return default

    return {
        "max_long_edge": positive_int(
            "reference_image_input_max_long_edge",
            "referenceImageInputMaxLongEdge",
            default=REFERENCE_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE,
        ),
        "max_bytes": positive_int(
            "reference_image_input_max_bytes",
            "referenceImageInputMaxBytes",
            default=REFERENCE_IMAGE_INPUT_DEFAULT_MAX_BYTES,
        ),
        "source": (
            (model or {}).get("reference_image_input_source")
            or (model or {}).get("referenceImageInputSource")
            or ""
        ) if isinstance(model, dict) else "",
        "source_url": (
            (model or {}).get("reference_image_input_source_url")
            or (model or {}).get("referenceImageInputSourceUrl")
            or ""
        ) if isinstance(model, dict) else "",
        "note": (
            (model or {}).get("reference_image_input_note")
            or (model or {}).get("referenceImageInputNote")
            or ""
        ) if isinstance(model, dict) else "",
    }


def _resolution_matches(value: Any, target: str) -> bool:
    value_text = _resolution_text_key(value)
    if not value_text:
        return False
    if value_text == _resolution_text_key(target):
        return True
    alias = IMAGE_RESOLUTION_ALIASES.get(value_text)
    if alias and _resolution_text_key(alias) == _resolution_text_key(target):
        return True
    legacy = LEGACY_IMAGE_RESOLUTION_TO_TIER.get(value_text)
    return bool(legacy and legacy.lower() == str(target or "").strip().lower())


def _validated_video_resolution(model: dict[str, Any], value: Any) -> str:
    # Apply a default only after resolving the task's actual model.
    resolution = str(value or model.get("default_resolution") or "720p").strip()
    raw_options = model.get("resolutions")
    options = [str(item).strip() for item in raw_options if str(item).strip()] if isinstance(raw_options, list) else []
    if resolution and options:
        for option in options:
            if resolution.casefold() == option.casefold():
                return option
        raise ValueError(f"分辨率 {resolution} 不在模型 {model.get('id') or ''} 的声明范围内：{', '.join(options)}")
    return resolution


def _model_duration_options(model: dict[str, Any], resolution: Any = None, *, native_keyframe: bool = False) -> list[int]:
    def parse_duration(value: Any) -> int | None:
        try:
            duration = int(float(value))
        except (TypeError, ValueError):
            return None
        return duration if duration > 0 else None

    keyframe = (model.get("adapter_capabilities") or {}).get("keyframe_visual_inputs") or {}
    raw_durations = (keyframe.get("durations") if native_keyframe else None) or (
        model.get("durations")
        or model.get("allowedDurations")
        or model.get("allowed_durations")
        or []
    )
    durations = sorted(
        {
            parsed
            for duration in raw_durations
            for parsed in [parse_duration(duration)]
            if parsed is not None
        }
    )
    constraints = model.get("duration_resolution_constraints") or model.get("durationResolutionConstraints")
    resolution_text = str(resolution or "").strip()
    if isinstance(constraints, dict) and resolution_text:
        constrained: Any = None
        if resolution_text in constraints:
            constrained = constraints[resolution_text]
        else:
            lowered = resolution_text.lower()
            for key, value in constraints.items():
                if str(key).lower() == lowered:
                    constrained = value
                    break
        if isinstance(constrained, list):
            constrained_durations = sorted(
                {
                    parsed
                    for duration in constrained
                    for parsed in [parse_duration(duration)]
                    if parsed is not None
                }
            )
            if constrained_durations:
                return constrained_durations
    return durations


def _empty_model_config() -> dict[str, Any]:
    return {
        "image": {
            "model_id": "",
            "character_resolution": "",
            "scene_resolution": "",
            "prop_resolution": "",
            "asset_resolution": "",
            "storyboard_resolution": "",
            "image_output_format": "auto",
        },
        "video": {
            "model_id": "",
            "resolution": "",
            "duration_seconds": 8,
            "generate_audio": True,
        },
        "agent": {
            "model_id": "",
            "temperature": 0.4,
            "max_tokens": 8192,
        },
        "text": {
            "model_id": "",
            "overview_excerpt_chars": DEFAULT_OVERVIEW_EXCERPT_CHARS,
        },
    }


def _normalize_overview_excerpt_chars(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_OVERVIEW_EXCERPT_CHARS
    return max(MIN_OVERVIEW_EXCERPT_CHARS, min(MAX_OVERVIEW_EXCERPT_CHARS, parsed))


def _normalize_model_config(value: dict[str, Any], capabilities: dict[str, Any]) -> dict[str, Any]:
    empty_config = _empty_model_config()
    raw_config = _deep_merge(empty_config, value if isinstance(value, dict) else {})
    config = {
        section: {
            key: copy.deepcopy(
                raw_config.get(section, {}).get(key, fallback)
                if isinstance(raw_config.get(section), dict)
                else fallback
            )
            for key, fallback in defaults.items()
        }
        for section, defaults in empty_config.items()
    }

    image_model = _find_model(config["image"].get("model_id"), "image", capabilities)
    if image_model and image_model.get("available") is not False:
        config["image"]["model_id"] = image_model.get("id")
        image_resolutions = image_model.get("resolutions") or []
        for key, fallback, aspect_ratio in (
            (
                "character_resolution",
                DEFAULT_IMAGE_GENERATION_PARAMETERS["character"]["default_resolution"],
                DEFAULT_IMAGE_GENERATION_PARAMETERS["character"]["aspect_ratio"],
            ),
            (
                "scene_resolution",
                DEFAULT_IMAGE_GENERATION_PARAMETERS["scene"]["default_resolution"],
                DEFAULT_IMAGE_GENERATION_PARAMETERS["scene"]["aspect_ratio"],
            ),
            (
                "prop_resolution",
                "1K",
                DEFAULT_IMAGE_GENERATION_PARAMETERS["prop"]["aspect_ratio"],
            ),
            (
                "asset_resolution",
                DEFAULT_IMAGE_GENERATION_PARAMETERS["asset"]["default_resolution"],
                DEFAULT_IMAGE_GENERATION_PARAMETERS["asset"]["aspect_ratio"],
            ),
            (
                "storyboard_resolution",
                DEFAULT_IMAGE_GENERATION_PARAMETERS["storyboard"]["default_resolution"],
                DEFAULT_IMAGE_GENERATION_PARAMETERS["storyboard"]["aspect_ratio"],
            ),
        ):
            request_aspect_ratio = resolve_image_aspect_ratio_for_model(
                image_model,
                aspect_ratio,
                options=[str(option) for option in image_resolutions if str(option)],
            )
            resolution_options = _image_resolution_options_for_aspect(
                image_resolutions,
                request_aspect_ratio,
                image_model,
            )
            config["image"][key] = _normalize_resolution(
                config["image"].get(key),
                resolution_options,
                str(fallback),
            )
        image_output_format = _normalize_image_output_format(config["image"].get("image_output_format"))
        if image_output_format != "auto" and image_output_format not in _model_image_output_formats(image_model):
            image_output_format = "auto"
        config["image"]["image_output_format"] = image_output_format
    elif not image_model:
        config["image"] = _empty_model_config()["image"]

    video_model = _find_model(config["video"].get("model_id"), "video", capabilities)
    if video_model and video_model.get("available") is not False:
        config["video"]["model_id"] = video_model.get("id")
        video_resolutions = video_model.get("resolutions") or []
        config["video"]["resolution"] = _normalize_resolution(
            config["video"].get("resolution"),
            video_resolutions,
            str(video_model.get("default_resolution") or "720p"),
        )
        durations = _model_duration_options(video_model, config["video"].get("resolution"))
        if durations and config["video"].get("duration_seconds") not in durations:
            config["video"]["duration_seconds"] = 8 if 8 in durations else durations[0]
        elif not durations:
            config["video"].pop("duration_seconds", None)
        config["video"]["generate_audio"] = bool(video_model.get("audio", False))
    elif not video_model:
        config["video"] = _empty_model_config()["video"]

    agent_model_id = str(config["agent"].get("model_id") or "").strip()
    agent_model = _find_model(agent_model_id, "agent", capabilities)
    if agent_model:
        config["agent"]["model_id"] = agent_model.get("id") or agent_model_id
    else:
        config["agent"]["model_id"] = ""
    config["agent"].pop("agent_runtime", None)
    config["agent"].pop("agentRuntime", None)
    try:
        temperature = float(config["agent"].get("temperature"))
    except (TypeError, ValueError):
        temperature = 0.4
    if temperature not in AGENT_TEMPERATURE_OPTIONS:
        temperature = 0.4
    config["agent"]["temperature"] = temperature
    try:
        max_tokens = int(config["agent"].get("max_tokens"))
    except (TypeError, ValueError):
        max_tokens = 8192
    if max_tokens not in AGENT_MAX_TOKEN_OPTIONS:
        max_tokens = 8192
    config["agent"]["max_tokens"] = max_tokens

    text_model_id = str(config["text"].get("model_id") or "").strip()
    text_model = _find_model(text_model_id, "text", capabilities)
    if text_model:
        config["text"]["model_id"] = text_model.get("id") or text_model_id
    else:
        config["text"]["model_id"] = ""
    config["text"]["overview_excerpt_chars"] = _normalize_overview_excerpt_chars(
        config["text"].get("overview_excerpt_chars")
    )
    return config


def _sync_defaults_with_model_config(
    config: dict[str, Any],
    capabilities: dict[str, list[dict[str, Any]]],
) -> None:
    model_config = _normalize_model_config(config.get("model_config", {}), capabilities)
    config["model_config"] = model_config
    defaults = config.setdefault("defaults", {})
    defaults.setdefault("models", {})
    defaults.setdefault("storyboard", {})
    defaults.setdefault("video", {})
    image_model = _find_model(model_config["image"]["model_id"], "image", capabilities) or {}
    video_model = _find_model(model_config["video"]["model_id"], "video", capabilities) or {}
    if video_model.get("available") is not False:
        model_config["video"]["generate_audio"] = bool(video_model.get("audio", False))
    defaults["models"]["image"] = image_model.get("label") or ""
    defaults["models"]["video"] = video_model.get("label") or ""
    defaults["models"]["agent"] = model_config["agent"].get("model_id") or ""
    defaults["models"]["text"] = model_config["text"].get("model_id") or ""
    defaults["storyboard"]["image_model"] = image_model.get("label") or ""
    defaults["storyboard"]["image_size"] = model_config["image"].get("storyboard_resolution") or ""
    defaults["storyboard"]["image_output_format"] = model_config["image"].get("image_output_format") or "auto"
    defaults["video"]["model"] = video_model.get("label") or ""
    defaults["video"]["provider"] = video_model.get("provider_id") or ""
    defaults["video"]["resolution"] = model_config["video"].get("resolution") or ""
    defaults["video"]["duration_seconds"] = model_config["video"].get("duration_seconds") or 8
    defaults["video"]["generate_audio"] = bool(model_config["video"].get("generate_audio"))


def _creation_model_config_status(
    config: dict[str, Any],
    capabilities: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    capabilities = capabilities or _available_model_capabilities(config)
    model_config = _normalize_model_config(config.get("model_config", {}), capabilities)
    providers = config.get("providers", [])
    provider_count = sum(
        1
        for provider in providers
        if isinstance(provider, dict) and _is_connected_provider(provider)
    ) if isinstance(providers, list) else 0
    checks = [
        ("image", "图片模型", "image", model_config.get("image", {}).get("model_id")),
        ("agent", "智能体模型", "agent", model_config.get("agent", {}).get("model_id")),
        ("text", "文本模型", "text", model_config.get("text", {}).get("model_id")),
        ("video", "视频模型", "video", model_config.get("video", {}).get("model_id")),
    ]
    required = []
    missing = []
    for key, label, model_type, model_id in checks:
        model = _find_model(str(model_id), model_type, capabilities) if model_id else None
        configured = bool(model and model.get("available") is not False)
        required.append(
            {
                "key": key,
                "label": label,
                "modelId": model_id or "",
                "configured": configured,
            }
        )
        if not configured:
            missing.append(label)
    message = "" if not missing else MODEL_CONFIG_REQUIRED_MESSAGE
    return {
        "ready": not missing,
        "missing": missing,
        "providerCount": provider_count,
        "required": required,
        "message": message,
    }

__all__ = (
    '_normalize_provider_id', '_normalize_provider_capabilities', '_provider_preset_id', '_provider_service_id', '_normalize_provider_adapter_id',
    '_provider_adapter_id', '_provider_protocol_service_id', '_adapter_endpoint_format',
    '_unique_provider_instance_id', '_unique_provider_title', '_storage_provider_row', '_storage_global_config',
    '_is_user_added_provider_row', '_normalize_provider_rows', '_provider_model_matches_capabilities',
    '_model_generation_endpoint', '_text_model_generation_endpoint', '_with_model_generation_endpoint',
    '_provider_supports_direct_media_generation', '_provider_specific_model_id',
    '_provider_text_model_supports_vision', '_REMOTE_MODEL_METADATA_KEYS', '_remote_model_entry_id',
    '_normalize_remote_model_entries', '_remote_model_row', '_last_test_remote_model_ids',
    '_last_test_remote_model_entries', '_is_legacy_generic_model_id',
    '_ALIGNED_MODEL_METADATA_KEYS', '_aligned_model_catalog_key', '_align_provider_model_metadata',
    '_provider_declared_and_discovered_models', '_provider_available_models_for_test',
    '_model_capabilities_with_provider_models',
    '_empty_model_capabilities', '_is_connected_provider', '_provider_models_as_capabilities',
    '_available_model_capabilities', '_model_options_from_capabilities', '_find_model',
    '_model_supports_vision_input', '_resolution_text_key', '_normalize_aspect_ratio_key',
    '_generic_image_size', '_image_resolution_options_for_aspect', '_dashscope_exceeds_standard_budget',
    '_dashscope_image_size', '_standard_video_size', '_image_output_size',
    '_with_model_resolution_metadata',
    '_video_output_size', '_normalize_resolution', '_normalize_image_output_format',
    '_model_image_output_formats', '_resolve_image_output_format', '_image_output_source_mime',
    '_model_reference_image_input_limits', '_resolution_matches', '_model_duration_options', '_empty_model_config',
    '_normalize_overview_excerpt_chars', '_normalize_model_config', '_sync_defaults_with_model_config',
    '_creation_model_config_status'
)


def _model_lookup_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _find_model_by_id_or_label(
    model_ref: str | None,
    model_type: str,
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    model = _find_model(model_ref, model_type, capabilities)
    if model:
        return model
    needle = _model_lookup_key(model_ref)
    if not needle:
        return None
    capability_map = capabilities if isinstance(capabilities, dict) else DEFAULT_MODEL_CAPABILITIES
    for item in capability_map.get(model_type, []):
        if not isinstance(item, dict):
            continue
        aliases = [
            item.get("id"),
            item.get("label"),
            item.get("display_name"),
            item.get("displayName"),
            item.get("name"),
        ]
        provider_label = item.get("providerLabel") or item.get("provider_label") or item.get("provider")
        label = item.get("label") or item.get("display_name") or item.get("displayName")
        if provider_label and label:
            aliases.append(f"{provider_label} / {label}")
        if needle in {_model_lookup_key(alias) for alias in aliases if alias}:
            return item
    return None
