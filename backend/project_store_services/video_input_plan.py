# -*- coding: utf-8 -*-
"""Shared helpers for storyboard/video input plan normalization."""

from __future__ import annotations

import re
from typing import Any


VIDEO_INPUT_MODES = (
    "storyboard_reference",
    "image_reference",
    "native_keyframe",
    "character_replace",
    "text_to_video_draft",
)


def normalize_video_input_mode(value: Any) -> str:
    text = str(value or "").strip()
    normalized = re.sub(r"[\s\-]+", "_", text).lower()
    aliases = {
        "storyboard": "storyboard_reference",
        "storyboard_image": "storyboard_reference",
        "storyboard_sheet": "storyboard_reference",
        "storyboard_multi_shot": "storyboard_reference",
        "storyboard_reference": "storyboard_reference",
        "storyboard_reference_image": "storyboard_reference",
        "storyboard_reference_if_supported": "storyboard_reference",
        "image_reference": "image_reference",
        "image_reference_video": "image_reference",
        "native_keyframe": "native_keyframe",
        "native_keyframe_video": "native_keyframe",
        "character_replace_video": "character_replace",
        "reference_image": "image_reference",
        "asset_image": "image_reference",
        "asset_reference": "image_reference",
        "asset_reference_video": "image_reference",
        "asset_image_reference": "image_reference",
        "single_image": "image_reference",
        "image_to_video": "image_reference",
        "single_image_to_video": "image_reference",
        "first_last": "image_reference",
        "first_last_frame": "image_reference",
        "first_frame_last_frame": "image_reference",
        "keyframe": "image_reference",
        "keyframes": "image_reference",
        "multi_keyframe": "image_reference",
        "multi_keyframes": "image_reference",
        "keyframe_reference": "image_reference",
        "text": "text_to_video_draft",
        "text_to_video": "text_to_video_draft",
        "text_to_video_draft": "text_to_video_draft",
    }
    return aliases.get(normalized, normalized)


def default_video_input_mode_for_strategy(strategy: Any) -> str:
    strategy_text = str(strategy or "").strip()
    normalized = normalize_video_input_mode(strategy_text)
    if normalized in VIDEO_INPUT_MODES:
        return normalized
    return "storyboard_reference"


def video_reference_mode_for_input_mode(mode: str) -> str:
    if mode in {"storyboard_reference", "storyboard_reference_if_supported"}:
        return "storyboard_image"
    if mode == "image_reference":
        return "image_reference"
    if mode == "native_keyframe":
        return "native_keyframe"
    return mode


def video_strategy_for_input_mode(strategy: str, mode: str) -> str:
    if mode == "character_replace":
        return "character_replace_video"
    if mode in {"storyboard_reference", "storyboard_reference_if_supported"}:
        return "storyboard_multi_shot"
    if mode == "image_reference":
        return "image_reference_video"
    if mode == "native_keyframe":
        return "native_keyframe_video"
    if mode == "text_to_video_draft":
        return mode
    return strategy or "storyboard_multi_shot"


def video_input_required_slots(mode: str) -> list[str]:
    if mode == "character_replace":
        return ["character_reference", "reference_video"]
    if mode == "text_to_video_draft":
        return []
    if mode == "image_reference":
        return ["image_reference"]
    if mode == "native_keyframe":
        return ["frame_reference"]
    return []


__all__ = (
    "VIDEO_INPUT_MODES",
    "normalize_video_input_mode",
    "default_video_input_mode_for_strategy",
    "video_reference_mode_for_input_mode",
    "video_strategy_for_input_mode",
    "video_input_required_slots",
)
