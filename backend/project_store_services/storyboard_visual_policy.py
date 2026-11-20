# -*- coding: utf-8 -*-
"""Resolve project visual layers for each storyboard image frame."""
from __future__ import annotations

from typing import Any

from .catalogs import (
    _style_phase_visual_prompt_from_config,
    _style_theme_visual_prompt_from_config,
)


def project_visual_layers(config: dict[str, Any]) -> dict[str, str]:
    style = config.get("style") if isinstance(config.get("style"), dict) else {}
    return {
        "visualStyle": str(style.get("prompt") or "").strip(),
        "themeVisual": _style_theme_visual_prompt_from_config(config),
        "phaseVisual": _style_phase_visual_prompt_from_config(config),
    }


_PRESENTATION_EFFECT_PRESETS = {
    "memory": "四周轻柔朦胧并带过去时态的柔和光感，主体清楚。",
    "imagination": "主体周围用轻微光晕与虚实边界呈现主观想象，不把它画成已证实的现场。",
    "dream": "四周朦胧、空间与光线略带梦境感，人物和关键物清楚。",
    "inner": "画面周边呈现清楚可辨的主观空间双重曝光：同一场景的墙面、空间线条或载体边框形成半透明的第二层错位透视，中央人物与起始信息仍清楚。所有层保持项目绘制媒介和既有人物身份；不用思想气泡或新增文字代替空间效果。",
    "perceptual_distortion": "仅在画面周边加入局部失焦或轻微形变，中央现实锚点和主体清楚。",
    "chronological_compression": "周边加入可辨的弧形时间流动光痕与柔和虚化，主体和当前状态清楚。",
    "process_montage": "用局部动作残影或节奏化光痕提示过程蒙太奇；主体、工具和当前动作仍清楚，不把多个互斥动作堆成同一瞬间。",
    "character_account": "以轻柔的画面边缘和讲述视角框定被讲述事件，保留讲述来源。",
    "reported": "以轻柔的画面边缘和讲述视角框定未证实转述，不把内容画成已证实事实。",
    "romantic_ambiguity": "在画面四周加入柔和暖光与少量心形光圈，人物、目光和互动仍是焦点，不覆盖主体。",
}

_PRESENTATION_EFFECT_LABELS = {
    "memory": "回忆",
    "imagination": "想象",
    "dream": "梦境",
    "perceptual_distortion": "感知",
    "chronological_compression": "时间流逝",
    "character_account": "讲述",
    "reported": "转述",
}


def storyboard_presentation_effect_preset(presentation: Any) -> str:
    """Apply the fixed image-only effect for each declared shot type."""
    if not isinstance(presentation, dict):
        return ""
    modes = presentation.get("modes")
    if not isinstance(modes, list):
        return ""
    selected = [mode for mode in dict.fromkeys(mode for mode in modes if isinstance(mode, str))
                if mode in _PRESENTATION_EFFECT_PRESETS]
    if not selected:
        return ""
    parts = ["本画格保留项目绘制媒介。", *(_PRESENTATION_EFFECT_PRESETS[mode] for mode in selected)]
    if len(selected) > 1:
        parts.append("叠加的氛围效果保持克制，重复的周边柔化只做一次，主体清楚。")
    labels = list(dict.fromkeys(_PRESENTATION_EFFECT_LABELS[mode] for mode in selected
                                if mode in _PRESENTATION_EFFECT_LABELS))
    if labels:
        parts.append(f"左上角绘一枚简短的“{'·'.join(labels)}”提示，不分开叠放多个提示。")
    return " ".join(parts)


def storyboard_visual_application(panels: list[dict[str, Any]]) -> dict[str, Any]:
    """Storyboard images use the project's visual layers across every frame."""
    layers = {"visualStyle": True, "themeVisual": True, "phaseVisual": True}
    return {
        "scope": "group",
        "shots": [{
            "shotNo": int(panel.get("shotNo") or index),
            "scope": "project", "lookVariant": "project_baseline",
            "layers": dict(layers),
        } for index, panel in enumerate(panels, start=1)],
    }


def storyboard_panel_visual_supplement(
    application: dict[str, Any], theme_visual: str, phase_visual: str,
) -> str:
    layers = application.get("layers") if isinstance(application.get("layers"), dict) else {}
    parts: list[str] = []
    if layers.get("themeVisual") and theme_visual:
        parts.append(f"【项目视觉补充】\n{theme_visual}")
    if layers.get("phaseVisual") and phase_visual:
        parts.append(f"【阶段视觉补充】\n{phase_visual}")
    return "\n\n".join(parts)
