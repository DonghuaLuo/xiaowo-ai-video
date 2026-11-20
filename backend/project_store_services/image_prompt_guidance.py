# -*- coding: utf-8 -*-
"""Shared prompt guidance for direct image generation."""

from __future__ import annotations

from typing import Any


def uses_original_image_reference(media: Any, role: Any) -> bool:
    """Only an explicitly selected original image bypasses generation templates."""
    if not media:
        return False
    if role not in ("original", "reference"):
        raise ValueError("请选择主参考图类型：原图或参考图")
    return role == "original"


def image_request_size_label(request_plan: Any, size: Any = None, resolution: Any = None) -> str:
    if isinstance(request_plan, dict):
        for key in ("requestValue", "requestedSize", "nativeTierValue", "resolution"):
            value = str(request_plan.get(key) or "").strip()
            if value:
                return value
    for value in (size, resolution):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def image_request_prompt_instruction(size: Any, orientation: str = "landscape") -> str:
    request_size = str(size or "").strip()
    prefix = f"本次请求的实际分辨率：{request_size}。" if request_size else ""
    normalized = str(orientation or "landscape").strip().lower()
    if normalized == "portrait":
        return f"{prefix}竖向画布构图，画面高度必须大于宽度；禁止横向宽幅或正方形构图。"
    if normalized == "square":
        return f"{prefix}方形画布构图，宽高应近似相等；禁止明显横向或竖向长幅构图。"
    return f"{prefix}横向宽幅构图，画面宽度必须大于高度；禁止竖版海报/手机竖屏或正方形构图。"


def image_orientation_retry_instruction(orientation: str = "landscape") -> str:
    normalized = str(orientation or "landscape").strip().lower()
    if normalized == "portrait":
        return "必须重新生成为竖向画布，画面高度必须大于宽度；禁止横向宽幅或正方形构图。"
    if normalized == "square":
        return "必须重新生成为方形画布，宽高必须近似相等；禁止明显横向或竖向长幅构图。"
    return "必须重新生成为横向宽幅画布，画面宽度必须大于高度；禁止竖版海报、手机竖屏比例或正方形构图。"


def image_landscape_retry_instruction() -> str:
    return image_orientation_retry_instruction("landscape")


def append_image_request_prompt_instruction(
    prompt: str,
    size: Any,
    orientation: str = "landscape",
) -> str:
    base = str(prompt or "").strip()
    instruction = image_request_prompt_instruction(size, orientation)
    if not instruction or instruction in base:
        return base
    if not base:
        return instruction
    return f"{base}\n\n{instruction}"


def append_image_landscape_retry_instruction(prompt: str) -> str:
    return append_image_orientation_retry_instruction(prompt, "landscape")


def append_image_orientation_retry_instruction(prompt: str, orientation: str) -> str:
    base = str(prompt or "").strip()
    instruction = image_orientation_retry_instruction(orientation)
    if instruction in base:
        return base
    if not base:
        return instruction
    return f"{base}\n\n{instruction}"


def image_metadata_needs_landscape_retry(metadata: Any) -> bool:
    return image_metadata_needs_orientation_retry(metadata, "landscape")


def image_metadata_needs_orientation_retry(metadata: Any, orientation: str) -> bool:
    if not isinstance(metadata, dict):
        return False
    try:
        width = int(metadata.get("width") or 0)
        height = int(metadata.get("height") or 0)
    except (TypeError, ValueError):
        return False
    if width <= 0 or height <= 0:
        return False
    normalized = str(orientation or "landscape").strip().lower()
    if normalized == "portrait":
        return height <= width
    if normalized == "square":
        return abs(width - height) > max(width, height) * 0.05
    return width <= height
