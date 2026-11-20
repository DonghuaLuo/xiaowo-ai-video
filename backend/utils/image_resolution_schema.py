# -*- coding: utf-8 -*-
"""Unified image output resolution schema and helpers."""

from __future__ import annotations

import copy
import math
import re
from typing import Any

from utils.aspect_size import image_size_for_resolution, parse_aspect_ratio


OPENAI_GPT_IMAGE_2_SCHEMA: dict[str, Any] = {
    "version": 1,
    "source": "official",
    "source_url": "https://developers.openai.com/api/docs/guides/image-generation",
    "parameter": "size",
    "value_format": "width_x_height",
    "size_mode": "computed_pixels",
    "separator": "x",
    "round_to": 16,
    "default_long_edge": 1024,
    "max_long_edge": 3840,
    "max_total_pixels": 8_294_400,
    "max_ratio": 3.0,
    "allow_explicit_pixels": True,
    "explicit_pixel_constraints": {
        "multiple_of": 16,
        "max_long_edge": 3840,
        "max_total_pixels": 8_294_400,
        "max_ratio": 3.0,
    },
    "notes": "OpenAI Images API uses size=WIDTHxHEIGHT or auto. Local tiers are converted to legal pixel sizes.",
}

ARK_SEEDREAM_5_LITE_SCHEMA: dict[str, Any] = {
    "version": 1,
    "source": "official",
    "source_url": "https://www.volcengine.com/docs/82379/1541523",
    "parameter": "size",
    "value_format": "tier_or_width_x_height",
    "size_mode": "native_tier",
    "separator": "x",
    "native_tiers": ["2K", "3K", "4K"],
    "allow_explicit_pixels": True,
    "explicit_pixel_constraints": {
        "min_total_pixels": 2560 * 1440,
        "max_total_pixels": 4096 * 4096,
        "max_ratio": 16.0,
    },
    "notes": "Seedream 5.0 Lite accepts provider-native K tiers; explicit pixel values use the official total-pixel and aspect-ratio guardrails.",
}

ARK_SEEDREAM_5_PRO_SCHEMA: dict[str, Any] = {
    **ARK_SEEDREAM_5_LITE_SCHEMA,
    "native_tiers": ["1K", "2K"],
    "notes": "Seedream 5.0 Pro accepts provider-native 1K/2K tiers; explicit pixel values use the official total-pixel and aspect-ratio guardrails.",
}

DASHSCOPE_QWEN_IMAGE_SCHEMA: dict[str, Any] = {
    "version": 1,
    "source": "official",
    "source_url": "https://help.aliyun.com/zh/model-studio/qwen-image-api",
    "parameter": "parameters.size",
    "value_format": "width_star_height",
    "size_mode": "explicit_pixels",
    "separator": "*",
    "allow_explicit_pixels": True,
    "explicit_pixel_constraints": {
        "multiple_of": 16,
        "max_ratio": 8.0,
    },
    "notes": "DashScope Qwen image models use parameters.size in WIDTH*HEIGHT form.",
}

DASHSCOPE_QWEN_IMAGE_EDIT_SCHEMA: dict[str, Any] = {
    **DASHSCOPE_QWEN_IMAGE_SCHEMA,
    "source_url": "https://help.aliyun.com/zh/model-studio/qwen-image-edit-api",
    "explicit_pixel_constraints": {
        "multiple_of": 16,
        "max_long_edge": 2048,
        "max_ratio": 4.0,
    },
    "notes": "DashScope Qwen image edit models use parameters.size in WIDTH*HEIGHT form; long edge is capped at 2048.",
}

DASHSCOPE_WAN27_IMAGE_SCHEMA: dict[str, Any] = {
    "version": 1,
    "source": "official",
    "source_url": "https://help.aliyun.com/en/model-studio/wan-image-generation-and-editing-api-reference",
    "parameter": "parameters.size",
    "value_format": "width_star_height",
    "size_mode": "computed_pixels",
    "separator": "*",
    "round_to": 16,
    "default_long_edge": 1440,
    "max_total_pixels": 2048 * 2048,
    "max_ratio": 8.0,
    "allow_explicit_pixels": True,
    "explicit_pixel_constraints": {
        "multiple_of": 16,
        "max_total_pixels": 2048 * 2048,
        "max_ratio": 8.0,
    },
    "notes": "Wan2.7 image models use parameters.size. Base model is limited to 1K/2K.",
}

DASHSCOPE_WAN27_IMAGE_PRO_SCHEMA: dict[str, Any] = {
    **DASHSCOPE_WAN27_IMAGE_SCHEMA,
    "max_total_pixels_by_resolution": {"4K": 4096 * 4096},
    "explicit_pixel_constraints_by_resolution": {
        "4K": {
            "multiple_of": 16,
            "max_total_pixels": 4096 * 4096,
            "max_ratio": 8.0,
        }
    },
    "operation_constraints": [
        {
            "when": {"has_reference_images": True},
            "disallow_resolutions": ["4K"],
            "fallback_resolution": "2K",
            "message": "Wan2.7 Image Pro only supports 4K for text-to-image; reference/edit requests must use 1K or 2K.",
        }
    ],
    "notes": "Wan2.7 Image Pro supports 4K for text-to-image only. Reference/edit requests are normalized to 1K/2K.",
}

MINIMAX_IMAGE_SCHEMA: dict[str, Any] = {
    "version": 1,
    "source": "official",
    "source_url": "https://platform.minimax.cn/docs/api-reference/image-generation-t2i",
    "parameter": "width,height",
    "value_format": "width_x_height",
    "size_mode": "computed_pixels",
    "round_to": 16,
    "default_long_edge": 2048,
    "allow_explicit_pixels": True,
    "explicit_pixel_constraints": {
        "multiple_of": 8,
        "min_short_edge": 512,
        "max_long_edge": 2048,
        "max_ratio": 4.0,
    },
}

MINIMAX_IMAGE_LIVE_SCHEMA: dict[str, Any] = {
    "version": 1,
    "source": "official",
    "source_url": "https://platform.minimax.cn/docs/api-reference/image-generation-t2i",
    "parameter": "aspect_ratio",
    "size_mode": "native_tier",
    "native_tiers": ["auto"],
    "allow_explicit_pixels": False,
    "aspect_ratios": ["1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16"],
}

PROVIDER_NATIVE_TIER_SCHEMA: dict[str, Any] = {
    "version": 1,
    "source": "provider",
    "parameter": "resolution",
    "value_format": "tier",
    "size_mode": "native_tier",
    "separator": "x",
    "allow_explicit_pixels": False,
    "notes": "Provider accepts named resolution tiers; exact output pixels are provider-defined.",
}


def _normalize_provider_id(provider_id: Any) -> str:
    raw = str(provider_id or "").strip()
    if raw == "ark":
        return "ark-seedance"
    if raw == "openai-image":
        return "openai"
    return raw


def _api_model_name(model_id: Any) -> str:
    raw = str(model_id or "").strip()
    if ":" in raw:
        return raw.split(":", 1)[1]
    if "/" in raw:
        return raw.rsplit("/", 1)[1]
    return raw


def _model_provider_from_id(model_id: Any) -> str:
    raw = str(model_id or "").strip()
    if ":" in raw:
        return _normalize_provider_id(raw.split(":", 1)[0])
    if "/" in raw:
        return _normalize_provider_id(raw.split("/", 1)[0])
    return ""


def _resolution_key(value: Any) -> str:
    return str(value or "").strip().replace("×", "x").replace("*", "x").upper()


def _canonical_resolution(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered in {"512", "512px"}:
        return "512px"
    if lowered in {"1k", "2k", "3k", "4k"}:
        return lowered.upper()
    match = re.fullmatch(r"\s*(\d+)\s*[xX×*]\s*(\d+)\s*", raw)
    if match:
        return f"{int(match.group(1))}x{int(match.group(2))}"
    return raw


def _explicit_dimensions(value: Any) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\s*[xX×*]\s*(\d+)\s*", str(value or ""))
    if not match:
        return None
    width = int(match.group(1))
    height = int(match.group(2))
    return (width, height) if width > 0 and height > 0 else None


def _computed_dimensions_for_schema(
    schema: dict[str, Any],
    resolution: Any,
    aspect_ratio: Any,
) -> tuple[int, int] | None:
    canonical_resolution = _canonical_resolution(resolution)
    constraints = _explicit_constraints(schema, canonical_resolution)
    round_to = int(constraints.get("multiple_of") or schema.get("round_to") or 16)
    max_total_pixels = constraints.get(
        "max_total_pixels",
        _constraint_value(schema, "max_total_pixels", canonical_resolution, None),
    )
    width, height = image_size_for_resolution(
        canonical_resolution or None,
        str(aspect_ratio or ""),
        default_long_edge=int(schema.get("default_long_edge") or 1024),
        round_to=round_to,
        max_long_edge=constraints.get("max_long_edge", schema.get("max_long_edge")),
        max_total_pixels=max_total_pixels,
        max_ratio=constraints.get("max_ratio", schema.get("max_ratio")),
    )

    aw, ah = parse_aspect_ratio(str(aspect_ratio or ""))
    t = max(width // (aw * round_to), height // (ah * round_to), 1)
    min_long_edge = constraints.get("min_long_edge")
    if min_long_edge is not None:
        t = max(t, math.ceil(int(min_long_edge) / (round_to * max(aw, ah))))
    min_short_edge = constraints.get("min_short_edge")
    if min_short_edge is not None:
        t = max(t, math.ceil(int(min_short_edge) / (round_to * min(aw, ah))))
    min_total_pixels = constraints.get("min_total_pixels")
    if min_total_pixels is not None:
        denom = aw * ah * round_to * round_to
        t = max(t, math.ceil(math.sqrt(int(min_total_pixels) / denom)))

    dimensions = (aw * round_to * t, ah * round_to * t)
    return dimensions if explicit_dimensions_are_valid(dimensions, schema, canonical_resolution) else None


def _format_dimensions(width: int, height: int, separator: str = "x") -> str:
    sep = "*" if separator == "*" else "x"
    return f"{int(width)}{sep}{int(height)}"


def _schema_from_model_fields(model: dict[str, Any]) -> dict[str, Any]:
    schema = model.get("image_resolution_schema")
    if not isinstance(schema, dict):
        schema = model.get("imageResolutionSchema")
    return copy.deepcopy(schema) if isinstance(schema, dict) else {}


def image_resolution_schema_for_model(
    model_or_id: dict[str, Any] | str | None,
    provider_id: str | None = None,
    adapter_id: str | None = None,
) -> dict[str, Any]:
    if isinstance(model_or_id, dict):
        existing = _schema_from_model_fields(model_or_id)
        if existing:
            return existing
        model_id = model_or_id.get("id")
        provider = (
            model_or_id.get("provider_preset_id")
            or model_or_id.get("providerPresetId")
            or model_or_id.get("provider_id")
            or model_or_id.get("providerId")
            or provider_id
            or _model_provider_from_id(model_id)
        )
        adapter = model_or_id.get("adapter_id") or model_or_id.get("adapterId") or adapter_id or ""
    else:
        model_id = model_or_id
        provider = provider_id or _model_provider_from_id(model_id)
        adapter = adapter_id or ""

    provider = _normalize_provider_id(provider)
    model_name = _api_model_name(model_id).lower()
    adapter = str(adapter or "").strip()

    if model_name in {"image-01", "image-01-live"}:
        return copy.deepcopy(MINIMAX_IMAGE_LIVE_SCHEMA if model_name.endswith("-live") else MINIMAX_IMAGE_SCHEMA)
    if model_name == "gpt-image-2":
        return copy.deepcopy(OPENAI_GPT_IMAGE_2_SCHEMA)
    if provider == "ark-seedance" and "seedream" in model_name:
        return copy.deepcopy(ARK_SEEDREAM_5_PRO_SCHEMA if "pro" in model_name else ARK_SEEDREAM_5_LITE_SCHEMA)
    if provider == "dashscope":
        if model_name.startswith("wan2.7-image-pro"):
            return copy.deepcopy(DASHSCOPE_WAN27_IMAGE_PRO_SCHEMA)
        if model_name.startswith("wan"):
            return copy.deepcopy(DASHSCOPE_WAN27_IMAGE_SCHEMA)
        if "qwen-image-edit" in model_name:
            return copy.deepcopy(DASHSCOPE_QWEN_IMAGE_EDIT_SCHEMA)
        if model_name.startswith("qwen-image"):
            return copy.deepcopy(DASHSCOPE_QWEN_IMAGE_SCHEMA)
    if provider == "gemini":
        schema = copy.deepcopy(PROVIDER_NATIVE_TIER_SCHEMA)
        schema["parameter"] = "generationConfig.imageConfig.imageSize"
        return schema
    if provider in {"vidu", "grok"}:
        return copy.deepcopy(PROVIDER_NATIVE_TIER_SCHEMA)
    if adapter == "openai-compatible" and model_name == "gpt-image-2":
        return copy.deepcopy(OPENAI_GPT_IMAGE_2_SCHEMA)
    return {}


def with_image_resolution_schema(model: dict[str, Any], media_type: str | None = None) -> dict[str, Any]:
    normalized = copy.deepcopy(model)
    resolved_media_type = str(media_type or normalized.get("type") or "").strip().lower()
    if resolved_media_type != "image":
        return normalized
    schema = image_resolution_schema_for_model(normalized)
    if schema:
        normalized["image_resolution_schema"] = schema
        normalized["imageResolutionSchema"] = copy.deepcopy(schema)
    return normalized


def _constraint_value(
    schema: dict[str, Any],
    key: str,
    resolution: Any,
    default: Any = None,
) -> Any:
    resolution_key = _canonical_resolution(resolution)
    by_resolution = schema.get(f"{key}_by_resolution")
    if isinstance(by_resolution, dict) and resolution_key in by_resolution:
        return by_resolution[resolution_key]
    value = schema.get(key)
    return default if value is None else value


def _explicit_constraints(schema: dict[str, Any], resolution: Any) -> dict[str, Any]:
    constraints = copy.deepcopy(schema.get("explicit_pixel_constraints") or {})
    resolution_key = _canonical_resolution(resolution)
    by_resolution = schema.get("explicit_pixel_constraints_by_resolution")
    if isinstance(by_resolution, dict) and isinstance(by_resolution.get(resolution_key), dict):
        constraints.update(copy.deepcopy(by_resolution[resolution_key]))
    return constraints


def explicit_dimensions_are_valid(
    dimensions: tuple[int, int],
    schema: dict[str, Any],
    resolution: Any = None,
) -> bool:
    width, height = dimensions
    constraints = _explicit_constraints(schema, resolution)
    multiple_of = int(constraints.get("multiple_of") or schema.get("round_to") or 1)
    if multiple_of > 1 and (width % multiple_of != 0 or height % multiple_of != 0):
        return False
    min_long_edge = constraints.get("min_long_edge")
    if min_long_edge is not None and max(width, height) < int(min_long_edge):
        return False
    min_short_edge = constraints.get("min_short_edge")
    if min_short_edge is not None and min(width, height) < int(min_short_edge):
        return False
    max_long_edge = constraints.get("max_long_edge")
    if max_long_edge is not None and max(width, height) > int(max_long_edge):
        return False
    min_total_pixels = constraints.get("min_total_pixels")
    if min_total_pixels is not None and width * height < int(min_total_pixels):
        return False
    max_total_pixels = constraints.get("max_total_pixels")
    if max_total_pixels is not None and width * height > int(max_total_pixels):
        return False
    max_ratio = constraints.get("max_ratio")
    if max_ratio is not None and max(width / height, height / width) > float(max_ratio) + 1e-9:
        return False
    return True


def _resolution_is_disallowed(
    schema: dict[str, Any],
    resolution: Any,
    *,
    has_reference_images: bool | None = None,
) -> bool:
    if has_reference_images is None:
        return False
    resolution_key = _resolution_key(resolution)
    constraints = schema.get("operation_constraints")
    if not isinstance(constraints, list):
        return False
    for constraint in constraints:
        if not isinstance(constraint, dict):
            continue
        when = constraint.get("when") if isinstance(constraint.get("when"), dict) else {}
        expects_refs = when.get("has_reference_images")
        if expects_refs is not None and bool(expects_refs) != bool(has_reference_images):
            continue
        disallowed = {
            _resolution_key(item)
            for item in constraint.get("disallow_resolutions", [])
            if str(item).strip()
        }
        if resolution_key in disallowed:
            return True
    return False


def _schema_fallback_resolution(schema: dict[str, Any]) -> str:
    constraints = schema.get("operation_constraints")
    if isinstance(constraints, list):
        for constraint in constraints:
            if isinstance(constraint, dict) and constraint.get("fallback_resolution"):
                return _canonical_resolution(constraint.get("fallback_resolution"))
    return _canonical_resolution(schema.get("default_resolution") or "2K")


def image_resolution_options_for_schema(
    options: list[str],
    aspect_ratio: str,
    schema: dict[str, Any] | None = None,
    *,
    has_reference_images: bool | None = None,
) -> list[str]:
    normalized_options = [str(option) for option in options if str(option)]
    if not normalized_options:
        return []
    schema = schema or {}
    aw, ah = parse_aspect_ratio(aspect_ratio)
    target_ratio = aw / ah
    tier_options: list[str] = []
    explicit_options: list[tuple[str, float]] = []
    for option in normalized_options:
        if _resolution_is_disallowed(schema, option, has_reference_images=has_reference_images):
            continue
        dimensions = _explicit_dimensions(option)
        if not dimensions:
            tier_options.append(option)
            continue
        if schema:
            if not schema.get("allow_explicit_pixels", False):
                continue
            if not explicit_dimensions_are_valid(dimensions, schema, option):
                continue
        width, height = dimensions
        explicit_options.append((option, abs((width / height) - target_ratio)))
    if explicit_options:
        best_delta = min(delta for _, delta in explicit_options)
        tier_options.extend(
            option
            for option, delta in explicit_options
            if abs(delta - best_delta) < 1e-9
        )
    if tier_options:
        return tier_options
    return [] if schema else normalized_options


def _aspect_ratio_float(aspect_ratio: Any) -> float:
    aw, ah = parse_aspect_ratio(str(aspect_ratio or ""))
    return aw / ah if ah else 0.0


def _aspect_ratio_within_schema(schema: dict[str, Any], aspect_ratio: Any) -> bool:
    aw, ah = parse_aspect_ratio(str(aspect_ratio or ""))
    allowed = schema.get("aspect_ratios")
    if isinstance(allowed, list) and not any(parse_aspect_ratio(str(value)) == (aw, ah) for value in allowed):
        return False
    ratio = max(aw / ah, ah / aw)
    constraints = _explicit_constraints(schema, None)
    max_ratio = constraints.get("max_ratio", schema.get("max_ratio"))
    return max_ratio is None or ratio <= float(max_ratio) + 1e-9


def _dimensions_match_aspect(
    dimensions: tuple[int, int],
    aspect_ratio: Any,
    *,
    tolerance: float = 0.03,
) -> bool:
    target = _aspect_ratio_float(aspect_ratio)
    if target <= 0:
        return False
    width, height = dimensions
    actual = width / height
    return abs(actual - target) / target <= tolerance


def _canonical_aspect_ratio(value: Any) -> str:
    aw, ah = parse_aspect_ratio(str(value or ""))
    return f"{aw}:{ah}"


def image_aspect_ratio_supported_by_schema(
    options: list[str],
    aspect_ratio: str,
    schema: dict[str, Any] | None = None,
    *,
    has_reference_images: bool | None = None,
) -> bool:
    """判断模型当前分辨率选项是否能在请求前表达目标比例。"""
    schema = schema or {}
    normalized_options = [str(option) for option in options if str(option)]
    explicit_options = [
        (option, dimensions)
        for option in normalized_options
        if (dimensions := _explicit_dimensions(option)) is not None
    ]
    if explicit_options:
        for option, dimensions in explicit_options:
            if _resolution_is_disallowed(schema, option, has_reference_images=has_reference_images):
                continue
            if schema:
                if not schema.get("allow_explicit_pixels", False):
                    continue
                if not explicit_dimensions_are_valid(dimensions, schema, option):
                    continue
            if _dimensions_match_aspect(dimensions, aspect_ratio):
                return True
        return False

    if not schema:
        return True
    if not _aspect_ratio_within_schema(schema, aspect_ratio):
        return False

    size_mode = str(schema.get("size_mode") or "").strip()
    if size_mode == "computed_pixels":
        candidate = normalized_options[0] if normalized_options else _schema_fallback_resolution(schema)
        return bool(image_output_size_from_schema(schema, candidate, aspect_ratio, has_reference_images=has_reference_images))
    if size_mode == "native_tier":
        return bool(schema.get("allow_explicit_pixels", False) or schema.get("native_tiers"))
    if size_mode == "explicit_pixels":
        return bool(schema.get("allow_explicit_pixels", False))
    return True


def resolve_image_aspect_ratio_for_model(
    model: dict[str, Any] | str | None,
    aspect_ratio: Any,
    *,
    fallback_aspect_ratio: str = "16:9",
    options: list[str] | None = None,
    has_reference_images: bool | None = None,
) -> str:
    """请求前按模型能力选择可发送比例；不做失败后的二次生成。"""
    desired = _canonical_aspect_ratio(aspect_ratio)
    fallback = _canonical_aspect_ratio(fallback_aspect_ratio)
    schema = image_resolution_schema_for_model(model)
    if options is None and isinstance(model, dict) and isinstance(model.get("resolutions"), list):
        options = [str(option) for option in model.get("resolutions", []) if str(option)]
    normalized_options = options or []
    if image_aspect_ratio_supported_by_schema(
        normalized_options,
        desired,
        schema,
        has_reference_images=has_reference_images,
    ):
        return desired
    if fallback != desired and image_aspect_ratio_supported_by_schema(
        normalized_options,
        fallback,
        schema,
        has_reference_images=has_reference_images,
    ):
        return fallback
    return desired


def normalize_image_resolution_for_schema(
    value: Any,
    options: list[str],
    fallback: Any,
    schema: dict[str, Any] | None,
    aspect_ratio: str,
    *,
    has_reference_images: bool | None = None,
) -> str:
    allowed_options = image_resolution_options_for_schema(
        options,
        aspect_ratio,
        schema,
        has_reference_images=has_reference_images,
    )
    candidates = [value, fallback, _schema_fallback_resolution(schema or {})]
    for candidate in candidates:
        text = _canonical_resolution(candidate)
        if not text or _resolution_is_disallowed(schema or {}, text, has_reference_images=has_reference_images):
            continue
        for option in allowed_options:
            if _resolution_key(option) == _resolution_key(text):
                return option
    return allowed_options[0] if allowed_options else _canonical_resolution(value or fallback)


def image_output_size_from_schema(
    schema: dict[str, Any] | None,
    resolution: Any,
    aspect_ratio: Any,
    *,
    has_reference_images: bool | None = None,
) -> str | None:
    schema = schema or {}
    if not schema:
        return None
    separator = str(schema.get("separator") or "x")
    canonical_resolution = _canonical_resolution(resolution)
    if _resolution_is_disallowed(schema, canonical_resolution, has_reference_images=has_reference_images):
        canonical_resolution = _schema_fallback_resolution(schema)

    explicit = _explicit_dimensions(canonical_resolution)
    if explicit and schema.get("allow_explicit_pixels", False):
        if explicit_dimensions_are_valid(explicit, schema, canonical_resolution):
            return _format_dimensions(*explicit, separator=separator)
        return ""

    size_mode = str(schema.get("size_mode") or "").strip()
    if size_mode == "native_tier":
        if schema.get("allow_explicit_pixels", False):
            dimensions = _computed_dimensions_for_schema(schema, canonical_resolution, aspect_ratio)
            if dimensions:
                return _format_dimensions(*dimensions, separator=separator)
        native_tiers = {
            _resolution_key(item): str(item).lower()
            for item in schema.get("native_tiers", [])
            if str(item).strip()
        }
        return "" if _resolution_key(canonical_resolution) in native_tiers else ""

    if size_mode == "explicit_pixels":
        return ""

    if size_mode == "computed_pixels":
        dimensions = _computed_dimensions_for_schema(schema, canonical_resolution, aspect_ratio)
        if not dimensions:
            return ""
        width, height = dimensions
        return _format_dimensions(width, height, separator=separator)

    return None


def provider_native_tier_value(schema: dict[str, Any] | None, resolution: Any) -> str:
    schema = schema or {}
    native_tiers = {
        _resolution_key(item): str(item).lower()
        for item in schema.get("native_tiers", [])
        if str(item).strip()
    }
    key = _resolution_key(resolution)
    if key in native_tiers:
        return native_tiers[key]
    if key == "512PX" and "1K" in native_tiers:
        return native_tiers["1K"]
    return next(iter(native_tiers.values()), "")


def image_resolution_request_plan(
    model: dict[str, Any] | str | None,
    resolution: Any,
    aspect_ratio: Any,
    *,
    size: Any = None,
    has_reference_images: bool | None = None,
) -> dict[str, Any]:
    schema = image_resolution_schema_for_model(model)
    schema_size = image_output_size_from_schema(
        schema,
        resolution,
        aspect_ratio,
        has_reference_images=has_reference_images,
    )
    requested_value = str(size or schema_size or "").strip()
    native_value = ""
    if not requested_value and schema:
        native_value = provider_native_tier_value(schema, resolution)
        requested_value = native_value or str(resolution or "").strip()
    parameter = str(schema.get("parameter") or ("size" if requested_value else "resolution"))
    requested_dimensions = _explicit_dimensions(requested_value)
    return {
        "schemaVersion": schema.get("version") if schema else None,
        "schemaSource": schema.get("source") if schema else "",
        "schemaSourceUrl": schema.get("source_url") if schema else "",
        "parameter": parameter,
        "valueFormat": schema.get("value_format") if schema else "",
        "sizeMode": schema.get("size_mode") if schema else "",
        "resolution": str(resolution or ""),
        "aspectRatio": str(aspect_ratio or ""),
        "hasReferenceImages": bool(has_reference_images),
        "requestValue": requested_value,
        "requestedSize": str(size or schema_size or ""),
        "nativeTierValue": native_value,
        "requestedWidth": requested_dimensions[0] if requested_dimensions else None,
        "requestedHeight": requested_dimensions[1] if requested_dimensions else None,
        "exactPixelRequest": bool(requested_dimensions),
        "outputPreservation": "provider_pixels_png_only",
    }


def image_resolution_actual_report(
    media: dict[str, Any] | None,
    request_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    media = media if isinstance(media, dict) else {}
    request_plan = request_plan if isinstance(request_plan, dict) else {}
    try:
        width = int(media.get("width") or 0)
        height = int(media.get("height") or 0)
    except (TypeError, ValueError):
        width, height = 0, 0
    requested_width = request_plan.get("requestedWidth")
    requested_height = request_plan.get("requestedHeight")
    requested_dimensions = None
    try:
        if requested_width and requested_height:
            requested_dimensions = (int(requested_width), int(requested_height))
    except (TypeError, ValueError):
        requested_dimensions = None
    mismatch = (
        width > 0
        and height > 0
        and requested_dimensions is not None
        and (width, height) != requested_dimensions
    )
    return {
        "width": width or None,
        "height": height or None,
        "size": f"{width}x{height}" if width and height else "",
        "aspectRatio": media.get("aspectRatio") or media.get("aspect_ratio") or "",
        "requestedWidth": requested_dimensions[0] if requested_dimensions else None,
        "requestedHeight": requested_dimensions[1] if requested_dimensions else None,
        "requestedSize": (
            f"{requested_dimensions[0]}x{requested_dimensions[1]}"
            if requested_dimensions
            else str(request_plan.get("requestValue") or request_plan.get("requestedSize") or "")
        ),
        "sizeMismatch": bool(mismatch),
        "comparison": (
            "matched"
            if requested_dimensions and not mismatch and width and height
            else "mismatch"
            if mismatch
            else "not_applicable_provider_native_or_unknown"
        ),
        "preservedProviderOutput": True,
        "savedFormat": "png",
    }
