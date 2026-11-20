# -*- coding: utf-8 -*-
"""Project-owned production frame contracts shared by storyboard and video stages."""

from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Any

from utils.aspect_size import aspect_size


_ASPECT_RATIO_RE = re.compile(r"^\s*(\d+)\s*[:xX/]\s*(\d+)\s*$")

_PROJECT_LANGUAGE_SPECS: dict[str, dict[str, str]] = {
    "zh-CN": {
        "label": "简体中文",
        "instruction": "所有模型生成的标题、剧情内容、说明、提示词和画面短标签使用简体中文。原文对白、专名和用户明确要求原样保留；禁止无原文依据的中英混写。",
    },
    "zh-TW": {
        "label": "繁體中文",
        "instruction": "所有模型生成的標題、劇情內容、說明、提示詞和畫面短標籤使用繁體中文。原文對白、專名和使用者明確要求原樣保留；禁止無原文依據的中英混寫。",
    },
    "en-US": {
        "label": "English",
        "instruction": "Write all model-generated titles, story content, notes, prompts, and visible short labels in English. Preserve source dialogue, proper nouns, and explicit user wording; do not mix languages without source support.",
    },
    "vi-VN": {
        "label": "Tiếng Việt",
        "instruction": "Viết toàn bộ tiêu đề, nội dung câu chuyện, ghi chú, lời nhắc và nhãn ngắn do mô hình tạo bằng tiếng Việt. Giữ nguyên lời thoại gốc, tên riêng và yêu cầu rõ ràng của người dùng; không trộn ngôn ngữ nếu nguyên tác không có.",
    },
}

_PROJECT_LANGUAGE_ALIASES = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh_cn": "zh-CN",
    "cn": "zh-CN",
    "chinese": "zh-CN",
    "中文": "zh-CN",
    "简体中文": "zh-CN",
    "zh-tw": "zh-TW",
    "zh_tw": "zh-TW",
    "繁體中文": "zh-TW",
    "繁体中文": "zh-TW",
    "en": "en-US",
    "en-us": "en-US",
    "en_us": "en-US",
    "english": "en-US",
    "英文": "en-US",
    "vi": "vi-VN",
    "vi-vn": "vi-VN",
    "vi_vn": "vi-VN",
    "vietnamese": "vi-VN",
    "越南语": "vi-VN",
    "越南語": "vi-VN",
}


def normalize_production_aspect_ratio(value: Any, fallback: str = "16:9") -> str:
    """Return a reduced positive ratio without relying on the image helper's portrait fallback."""

    def parse(candidate: Any) -> tuple[int, int] | None:
        match = _ASPECT_RATIO_RE.match(str(candidate or ""))
        if not match:
            return None
        width, height = int(match.group(1)), int(match.group(2))
        if width <= 0 or height <= 0:
            return None
        divisor = math.gcd(width, height)
        return width // divisor, height // divisor

    parts = parse(value) or parse(fallback) or (16, 9)
    return f"{parts[0]}:{parts[1]}"


def production_orientation(aspect_ratio: Any) -> tuple[str, str]:
    ratio = normalize_production_aspect_ratio(aspect_ratio)
    width, height = (int(item) for item in ratio.split(":"))
    if width > height:
        return "landscape", "横屏"
    if width < height:
        return "portrait", "竖屏"
    return "square", "方形"


def normalize_project_language(value: Any, fallback: str = "zh-CN") -> str:
    text = str(value or "").strip()
    if text in _PROJECT_LANGUAGE_SPECS:
        return text
    normalized = text.casefold()
    if normalized in _PROJECT_LANGUAGE_ALIASES:
        return _PROJECT_LANGUAGE_ALIASES[normalized]
    fallback_text = str(fallback or "zh-CN").strip()
    if fallback_text in _PROJECT_LANGUAGE_SPECS:
        return fallback_text
    return _PROJECT_LANGUAGE_ALIASES.get(fallback_text.casefold(), "zh-CN")


def project_language_spec(value: Any) -> dict[str, str]:
    code = normalize_project_language(value)
    spec = _PROJECT_LANGUAGE_SPECS[code]
    return {
        "code": code,
        "label": spec["label"],
        "instruction": spec["instruction"],
        "source": "project_config",
    }


def build_project_production_spec(
    project_config: dict[str, Any] | None,
    *,
    resolution: Any = None,
) -> dict[str, Any]:
    config = project_config if isinstance(project_config, dict) else {}
    video_config = config.get("video") if isinstance(config.get("video"), dict) else {}
    aspect_ratio = normalize_production_aspect_ratio(
        config.get("aspect_ratio")
        or config.get("aspectRatio")
        or video_config.get("aspect_ratio")
        or video_config.get("aspectRatio")
        or "16:9"
    )
    orientation, orientation_label = production_orientation(aspect_ratio)
    language = project_language_spec(
        config.get("source_language")
        or config.get("sourceLanguage")
        or "zh-CN"
    )
    return {
        "schemaVersion": 1,
        "aspectRatio": aspect_ratio,
        "orientation": orientation,
        "orientationLabel": orientation_label,
        "resolution": str(resolution or video_config.get("resolution") or "").strip(),
        "source": "project_config",
        "language": language,
    }


def storyboard_panel_rows(orientation: str, count: int) -> tuple[int, ...]:
    """Preferred full-sheet rows; the last row may leave unframed paper."""
    if orientation == "landscape":
        return {1: (1,), 2: (1, 1), 3: (2, 1), 4: (2, 2),
                5: (2, 2, 1), 6: (2, 2, 2)}.get(count, ())
    if orientation == "portrait":
        return {1: (1,), 2: (2,), 3: (3,), 4: (2, 2),
                5: (3, 2), 6: (3, 3)}.get(count, ())
    return ()


def _model_friendly_sheet_aspect_ratio(target: float) -> str:
    """Keep the sheet geometry close while avoiding large exact-ratio pixel units."""
    exact_simple = Fraction(target).limit_denominator(16)
    if max(exact_simple.numerator, exact_simple.denominator) <= 16 and abs(float(exact_simple) / target - 1) < 1e-9:
        return f"{exact_simple.numerator}:{exact_simple.denominator}"
    candidates: list[tuple[int, int, float, Fraction]] = []
    for denominator in range(1, 65):
        approximate = target * denominator
        for numerator in {math.floor(approximate), math.ceil(approximate)}:
            if numerator <= 0:
                continue
            fraction = Fraction(numerator, denominator)
            error = abs(float(fraction) / target - 1)
            if error <= 0.02:
                candidates.append((max(fraction.numerator, fraction.denominator),
                                   fraction.numerator + fraction.denominator, error, fraction))
    selected = min(candidates)[3] if candidates else Fraction(target).limit_denominator(64)
    return f"{selected.numerator}:{selected.denominator}"


def build_storyboard_render_spec(
    project_config: dict[str, Any] | None,
    template_layout_spec: dict[str, Any] | None,
    *,
    main_panel_count: int = 0,
    builtin_template: bool = False,
    template_id: str = "",
) -> dict[str, Any]:
    layout = template_layout_spec if isinstance(template_layout_spec, dict) else {}
    production = build_project_production_spec(project_config)
    sheet_aspect_ratio = normalize_production_aspect_ratio(
        layout.get("sheetAspectRatio") or layout.get("aspectRatio") or "16:9"
    )
    rows = storyboard_panel_rows(production["orientation"], main_panel_count) if builtin_template else ()
    main_area_fraction = (
        0.86 if template_id == "narrative_storyboard" else
        0.76 if template_id == "blocking_storyboard" else 1.0
    )
    if rows:
        frame_width, frame_height = (int(part) for part in production["aspectRatio"].split(":"))
        sheet_ratio = (frame_width / frame_height) * max(rows) / len(rows)
        if template_id == "narrative_storyboard":
            sheet_ratio /= main_area_fraction
        elif template_id == "blocking_storyboard":
            sheet_ratio *= main_area_fraction
        sheet_aspect_ratio = _model_friendly_sheet_aspect_ratio(sheet_ratio)
    sheet_orientation, sheet_orientation_label = production_orientation(sheet_aspect_ratio)
    try:
        requested_width = max(1, int(layout.get("targetWidth") or 2048))
        requested_height = max(1, int(layout.get("targetHeight") or 1152))
    except (TypeError, ValueError):
        requested_width, requested_height = 2048, 1152
    if rows:
        sheet_width = max(16, round(2048 * min(sheet_ratio, 1) / 16) * 16)
        sheet_height = max(16, round(2048 / max(sheet_ratio, 1) / 16) * 16)
    else:
        sheet_width, sheet_height = aspect_size(
            sheet_aspect_ratio,
            min(requested_width, requested_height),
            round_to=16,
        )
    return {
        "schemaVersion": 1,
        "sheet": {
            "aspectRatio": sheet_aspect_ratio,
            "orientation": sheet_orientation,
            "orientationLabel": sheet_orientation_label,
            "targetWidth": sheet_width,
            "targetHeight": sheet_height,
            "idealAspectRatio": round(sheet_ratio, 6) if rows else None,
            "resolution": str(layout.get("defaultResolution") or "2K"),
            "panelRows": list(rows),
            "mainAreaFraction": main_area_fraction,
        },
        "targetVideo": production,
        "shotFrame": {
            "aspectRatio": production["aspectRatio"],
            "orientation": production["orientation"],
            "orientationLabel": production["orientationLabel"],
            "safeAreaPercent": 90,
            "source": "project_config",
        },
        "auxiliaryPanelsMayUseIndependentAspectRatio": True,
    }


__all__ = (
    "normalize_production_aspect_ratio",
    "production_orientation",
    "normalize_project_language",
    "project_language_spec",
    "build_project_production_spec",
    "build_storyboard_render_spec",
    "storyboard_panel_rows",
)
