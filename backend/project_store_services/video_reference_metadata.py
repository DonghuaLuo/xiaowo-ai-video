# -*- coding: utf-8 -*-
"""Shared reference-image metadata rules for video prompt assembly.

These helpers are allowed in model-facing video request assembly because they
only normalize whitespace and remove UI mention markers. They must not shorten,
summarize, or discard generation semantics.
"""

from __future__ import annotations

import re
from typing import Any
from utils.frame_references import frame_options, is_frame_image


def video_reference_identity(row: dict[str, Any]) -> str:
    """Identify the referenced image, never the canvas edge or its display port."""
    media = row.get("media") if isinstance(row.get("media"), dict) else {}
    storage = row.get("storage") if isinstance(row.get("storage"), dict) else {}
    version = str(row.get("mediaVersionId") or row.get("sourceVersionId") or row.get("assetVersionId") or media.get("versionId") or "")
    media_id = str(row.get("mediaId") or media.get("id") or storage.get("id") or "")
    if media_id:
        return f"media:{media_id}:{version}"
    path = str(row.get("path") or row.get("relativePath") or row.get("url") or media.get("path") or media.get("url") or storage.get("path") or "")
    if path:
        return f"path:{path}"
    asset_id = str(row.get("rootAssetId") or row.get("assetId") or "")
    if asset_id:
        return f"asset:{row.get('rootAssetProjectId') or ''}:{asset_id}:{version}"
    source_id = str(row.get("sourceNodeId") or "")
    return f"node:{source_id}:{version}" if source_id else ""


def video_reference_input_identity(row: dict[str, Any]) -> str:
    """A shared file can occupy distinct first/last-frame and reference inputs."""
    identity = video_reference_identity(row)
    if identity and is_frame_image(row):
        return f"{identity}:frame:{frame_options(row)['frameRole']}"
    return identity


def video_reference_usage(row: dict[str, Any]) -> str:
    return frame_options(row)["frameRole"] if is_frame_image(row) else "reference_image"

REFERENCE_DESCRIPTION_KEYS = (
    "desc",
    "description",
    "summary",
    "visualDescription",
    "visual_description",
)

REFERENCE_TEXT_PLACEHOLDERS = (
    "资产参考图",
)

REFERENCE_TEXT_PLACEHOLDER_KEYS = {item.casefold() for item in REFERENCE_TEXT_PLACEHOLDERS}
LOCAL_ASSET_MENTION_MARKERS = {"@", "＠"}
LOCAL_ASSET_MENTION_STOP_CHARS = set(
    " \t\r\n@＠，。；：:、,.!?！？[]()（）{}<>《》\"“”'‘’`~"
)
LOCAL_ASSET_MENTION_EMAIL_PREV_RE = re.compile(r"[A-Za-z0-9._%+\-]")


def strip_inline_asset_mention_markers(value: Any) -> str:
    """Only for reference metadata labels; never use on final prompts or story text."""
    return str(value or "").replace("@", "").replace("＠", "").strip()


def normalize_reference_text(value: Any) -> str:
    text = strip_inline_asset_mention_markers(value)
    return re.sub(r"\s+", " ", text).strip()


def is_reference_text_placeholder(value: Any) -> bool:
    text = normalize_reference_text(value)
    return bool(text) and text.casefold() in REFERENCE_TEXT_PLACEHOLDER_KEYS


def _local_asset_mention_unknown_preview(text: str, index: int) -> str:
    end = index + 1
    while end < len(text) and text[end] not in LOCAL_ASSET_MENTION_STOP_CHARS:
        end += 1
    marker = text[index:end].strip() or text[index]
    return marker[:40] + ("..." if len(marker) > 40 else "")


def replace_known_local_asset_mentions(
    text: Any,
    labels: list[str],
    *,
    context_label: str,
    error_type: type[Exception] = RuntimeError,
) -> tuple[str, dict[str, Any]]:
    """Convert known local @asset markers to plain labels; block unknown markers.

    This is a provider boundary helper. It must only be called after the caller
    has collected labels from the current bound assets/reference images. It must
    not guess labels, shorten prompt content, or remove arbitrary ``@`` text.
    """
    value = str(text or "")
    known_labels = [
        label
        for label in sorted({str(item or "").strip() for item in labels if str(item or "").strip()}, key=len, reverse=True)
        if label
    ]
    if not value:
        return "", {
            "enabled": True,
            "knownLabelCount": len(known_labels),
            "convertedCount": 0,
            "convertedLabels": [],
        }
    parts: list[str] = []
    converted_labels: list[str] = []
    unknown_markers: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char not in LOCAL_ASSET_MENTION_MARKERS:
            parts.append(char)
            index += 1
            continue
        if index > 0 and LOCAL_ASSET_MENTION_EMAIL_PREV_RE.fullmatch(value[index - 1]):
            parts.append(char)
            index += 1
            continue
        remainder = value[index + 1 :]
        matched_label = next((label for label in known_labels if remainder.startswith(label)), "")
        if matched_label:
            parts.append(matched_label)
            if matched_label not in converted_labels:
                converted_labels.append(matched_label)
            index += 1 + len(matched_label)
            continue
        preview = _local_asset_mention_unknown_preview(value, index)
        if preview not in unknown_markers:
            unknown_markers.append(preview)
        parts.append(char)
        index += 1
    if unknown_markers:
        message = (
            f"{context_label}包含未识别的本地 @ 资产标记：{', '.join(unknown_markers[:5])}；"
            "请先绑定对应参考图或改成普通文字后再生成。"
        )
        raise error_type(message)
    return "".join(parts).strip(), {
        "enabled": True,
        "knownLabelCount": len(known_labels),
        "convertedCount": len(converted_labels),
        "convertedLabels": converted_labels,
    }
