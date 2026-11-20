# -*- coding: utf-8 -*-
"""生成共用的模型能力、文本值、素材角色和视频输入模式规则。"""
from __future__ import annotations

from .video_input_plan import default_video_input_mode_for_strategy as _shared_default_video_input_mode_for_strategy
from .video_input_plan import normalize_video_input_mode as _shared_normalize_video_input_mode
from .video_input_plan import video_reference_mode_for_input_mode as _shared_video_reference_mode_for_input_mode
from .video_input_plan import video_strategy_for_input_mode as _shared_video_strategy_for_input_mode
from typing import Any, Callable
from utils.frame_references import is_frame_image
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_DASHSCOPE_WAN27_R2V_OFFICIAL
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_VIDU_Q3_REFERENCE_OFFICIAL
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_HAPPYHORSE_OFFICIAL
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_GROK_OFFICIAL
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_KLING_OFFICIAL
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_VEO_OFFICIAL
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_MINIMAX_H3_OFFICIAL
import json
import re

def _positive_int_config_value(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _model_capability_sources(model: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(model, dict):
        return []
    sources: list[dict[str, Any]] = [model]
    for key in ("adapter_capabilities", "adapterCapabilities", "metadata", "official_capabilities", "officialCapabilities"):
        value = model.get(key)
        if isinstance(value, dict):
            sources.append(value)
    return sources


def _model_final_prompt_profile(model: dict[str, Any] | None) -> str:
    for source in _model_capability_sources(model):
        for key in (
            "final_prompt_profile",
            "finalPromptProfile",
            "video_prompt_profile",
            "videoPromptProfile",
            "final_video_prompt_profile",
            "finalVideoPromptProfile",
        ):
            value = source.get(key)
            profile = str(value or "").strip()
            if profile:
                return profile
    return ""


def _model_prompt_timing_style(model: dict[str, Any] | None) -> str:
    for source in _model_capability_sources(model):
        for key in ("prompt_timing_style", "promptTimingStyle"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    model_id = str(
        (model or {}).get("id")
        or (model or {}).get("model_id")
        or (model or {}).get("modelId")
        or (model or {}).get("name")
        or ""
    ).casefold()
    if "doubao-seedance-2-5" in model_id:
        return "integer_second_timeline"
    if "doubao-seedance-2-0" in model_id:
        return "shot_sequence"
    return ""


def _visual_style_prompt_for_model(text: Any) -> str:
    prompt = str(text or "").strip()
    if not prompt:
        return ""
    prompt = re.sub(r"^\s*(?:画风|风格|视觉风格)\s*[:：]\s*", "", prompt)
    if not prompt:
        return ""
    return f"视觉风格：{prompt}"


def _generation_text_value(value: Any, *, limit: int = 0) -> str:
    """Extract generation text without stripping semantic markers.

    ``limit > 0`` is only for UI summaries, logs, diagnostics, or short labels.
    Canonical prompts, provider payloads, and generation-affecting context must
    use ``limit=0`` and block later if an official provider hard limit is exceeded.
    """
    from .source_text_store import _compact_text

    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        return text if limit <= 0 else _compact_text(text, limit)
    if isinstance(value, list):
        rows = [_generation_text_value(item, limit=limit) for item in value]
        text = "；".join(row for row in rows if row)
        return text if limit <= 0 else _compact_text(text, limit)
    if isinstance(value, dict):
        rows = []
        for key in (
            "videoPrompt",
            "video_prompt",
            "visibleAction",
            "action",
            "cameraMotion",
            "sceneMotion",
            "temporalContinuity",
            "productionNote",
            "summary",
            "prompt",
        ):
            text = _generation_text_value(value.get(key), limit=limit)
            if text and text not in rows:
                rows.append(text)
        if rows:
            text = "；".join(rows)
            return text if limit <= 0 else _compact_text(text, limit)
        text = json.dumps(value, ensure_ascii=False)
        if limit <= 0:
            return text.strip()
        return _compact_text(text, limit)
    text = str(value or "").strip()
    return text if limit <= 0 else _compact_text(text, limit)


def _project_ai_content_disclosure_metadata(project_config: dict[str, Any] | None) -> dict[str, Any]:
    config = project_config if isinstance(project_config, dict) else {}
    production = config.get("production") if isinstance(config.get("production"), dict) else {}
    disclosure = (
        production.get("aiContentDisclosure")
        if isinstance(production.get("aiContentDisclosure"), dict)
        else config.get("aiContentDisclosure")
        if isinstance(config.get("aiContentDisclosure"), dict)
        else {}
    )
    enabled = disclosure.get("enabled")
    if enabled is None:
        enabled = True
    return {
        "enabled": bool(enabled),
        "visibleLabel": str(disclosure.get("visibleLabel") or "本视频含 AI 生成内容").strip(),
        "metadataLabel": str(disclosure.get("metadataLabel") or "AI-generated").strip(),
        "scope": "generated_media_export_or_publish",
    }


def _model_supports_storyboard_reference_image(model: dict[str, Any]) -> bool:
    supports = {str(item).strip().lower() for item in model.get("supports", []) if str(item).strip()}
    if supports.intersection({"storyboard_reference_image", "storyboard_grid_reference"}):
        return True
    return bool(
        model.get("supports_storyboard_reference_image") is True
        or model.get("supportsStoryboardReferenceImage") is True
    )


def _normalize_video_generation_strategy(strategy: Any) -> str:
    text = str(strategy or "").strip()
    if not text:
        return "storyboard_multi_shot"
    normalized = _shared_normalize_video_input_mode(text)
    if normalized == "text_to_video_draft" or text == "text_to_video_draft":
        return "text_to_video_draft"
    if text == "reference_video":
        return "reference_video"
    if normalized == "native_keyframe":
        return "native_keyframe_video"
    if normalized == "image_reference" or text in _IMAGE_REFERENCE_VIDEO_STRATEGIES:
        return "image_reference_video"
    if normalized == "storyboard_reference" or text in _LEGACY_STORYBOARD_VIDEO_STRATEGIES:
        return "storyboard_multi_shot"
    return text


def _reference_is_visual_handoff(reference: dict[str, Any] | None) -> bool:
    if not isinstance(reference, dict):
        return False
    return any(
        str(reference.get(key) or "").strip() in {"visual_handoff", "visual_handoff_reference"}
        for key in (
            "slot", "targetSlot", "target_slot", "assetType", "asset_type",
            "assetKind", "asset_kind", "mediaPurpose", "media_purpose",
            "preferredTargetSlot", "preferred_target_slot",
        )
    )


def _reference_has_storyboard_asset_type(reference: dict[str, Any] | None) -> bool:
    if not isinstance(reference, dict) or _reference_is_visual_handoff(reference):
        return False
    if any(reference.get(key) == "custom_image" for key in ("assetType", "mediaPurpose", "slot")):
        return False
    for key in _STORYBOARD_REFERENCE_ASSET_TYPE_KEYS:
        value = str(reference.get(key) or "").strip()
        normalized = value.casefold().replace("-", "_").replace(".", "_")
        if value in _STORYBOARD_REFERENCE_TYPE_VALUES or normalized in _STORYBOARD_REFERENCE_TYPE_VALUES:
            return True
    return False


def _reference_is_storyboard_sheet(reference: dict[str, Any] | None) -> bool:
    if is_frame_image(reference):
        return False
    if not isinstance(reference, dict) or _reference_is_visual_handoff(reference):
        return False
    if any(reference.get(key) == "custom_image" for key in ("assetType", "mediaPurpose", "slot")):
        return False
    purpose = reference.get("mediaPurpose")
    if purpose in {"character_reference", "creature_reference", "scene_reference", "prop_reference"}:
        return False
    node_type_values = {
        str(reference.get(key) or "").strip()
        for key in ("nodeType", "node_type", "sourceNodeType", "source_node_type", "type")
    }
    if "storyboard.image" in node_type_values:
        return True
    source_values = {
        str(reference.get(key) or "").strip()
        for key in ("source",)
    }
    if source_values.intersection({"storyboard_version", "storyboard_image"}):
        return True
    spec = reference.get("storyboardPromptSpec")
    if isinstance(spec, dict) and str(spec.get("format") or "").strip() in {
        "storyboard_panel_sequence",
        "single_storyboard_panel",
        "film_storyboard_sheet",
    }:
        return True
    return _reference_has_storyboard_asset_type(reference)


def _normalize_video_input_mode(value: Any) -> str:
    return _shared_normalize_video_input_mode(value)


def _video_strategy_for_input_mode(strategy: str, mode: str) -> str:
    return _shared_video_strategy_for_input_mode(strategy, mode)


def _video_reference_mode_for_input_mode(mode: str) -> str:
    return _shared_video_reference_mode_for_input_mode(mode)


def _video_input_mode_for_strategy(strategy: Any) -> str:
    return _shared_default_video_input_mode_for_strategy(strategy)


_SUPPLIER_OFFICIAL_FINAL_VIDEO_PROMPT_PROFILES = {
    FINAL_VIDEO_PROMPT_PROFILE_MINIMAX_H3_OFFICIAL,
    FINAL_VIDEO_PROMPT_PROFILE_KLING_OFFICIAL,
    FINAL_VIDEO_PROMPT_PROFILE_VEO_OFFICIAL,
    FINAL_VIDEO_PROMPT_PROFILE_GROK_OFFICIAL,
    FINAL_VIDEO_PROMPT_PROFILE_HAPPYHORSE_OFFICIAL,
    FINAL_VIDEO_PROMPT_PROFILE_DASHSCOPE_WAN27_R2V_OFFICIAL,
    FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT,
    FINAL_VIDEO_PROMPT_PROFILE_VIDU_Q3_REFERENCE_OFFICIAL,
}


_SUPPORTED_FINAL_VIDEO_PROMPT_PROFILES = set(_SUPPLIER_OFFICIAL_FINAL_VIDEO_PROMPT_PROFILES)


_LEGACY_STORYBOARD_VIDEO_STRATEGIES = {
    "storyboard_reference",
    "storyboard_reference_image",
    "storyboard_reference_if_supported",
    "storyboard_image",
}


_IMAGE_REFERENCE_VIDEO_STRATEGIES = {
    "image_reference",
    "image_reference_video",
    "reference_image",
    "asset_image",
    "asset_reference",
    "first_last",
    "first_last_frame",
    "first_frame_last_frame",
    "keyframe",
    "keyframes",
    "multi_keyframe",
    "multi_keyframes",
    "keyframe_reference",
    "single_image",
    "image_to_video",
    "single_image_to_video",
}


_STORYBOARD_REFERENCE_TYPE_VALUES = {
    "storyboard",
    "storyboard_image",
    "storyboard_sheet",
    "storyboard.image",
    "film_storyboard_sheet",
    "分镜图",
    "故事板分镜图",
    "故事版分镜图",
}


_STORYBOARD_REFERENCE_ASSET_TYPE_KEYS = (
    "assetType",
    "asset_type",
    "assetKind",
    "asset_kind",
    "mediaPurpose",
    "media_purpose",
)
