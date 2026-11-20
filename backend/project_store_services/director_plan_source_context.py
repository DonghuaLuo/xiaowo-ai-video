# -*- coding: utf-8 -*-
"""分镜任务的原文范围标记与镜头节奏输入校验。"""
from __future__ import annotations

import math
from typing import Any


def _director_plan_rhythm_multiplier(value: Any) -> float:
    if value is None or value == "":
        return 1.0
    if isinstance(value, bool):
        raise ValueError("镜头节奏倍率必须是正数")
    try:
        multiplier = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("镜头节奏倍率必须是正数") from exc
    if not math.isfinite(multiplier) or multiplier <= 0:
        raise ValueError("镜头节奏倍率必须是正数")
    return multiplier


_DIRECTOR_PLAN_TARGET_START = "<<<待规划内容开始>>>"
_DIRECTOR_PLAN_TARGET_END = "<<<待规划内容结束>>>"


def _director_plan_marked_episode_source(episode_source: str, target_source: str) -> str:
    """仅标记能在整集原文中唯一定位的当前片段。"""
    source = str(episode_source or "")
    target = str(target_source or "")
    if not source:
        return ""
    if _DIRECTOR_PLAN_TARGET_START in source or _DIRECTOR_PLAN_TARGET_END in source:
        raise ValueError("分集原文包含分镜脚本保留的范围标记")
    if target and source.count(target) == 1:
        start = source.index(target)
        return (
            source[:start] + _DIRECTOR_PLAN_TARGET_START + target
            + _DIRECTOR_PLAN_TARGET_END + source[start + len(target):]
        )
    return (
        "当前工作链对应段无法在整集原文中唯一定位；以下全文仅供理解前因后果，"
        "本轮拍摄范围只以【可拍摄内容】为准。\n" + source
    )
