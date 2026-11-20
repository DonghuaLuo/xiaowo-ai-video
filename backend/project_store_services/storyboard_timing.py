# -*- coding: utf-8 -*-
"""Shared timing policy for director shots and generated video segments."""
from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

from .agent_sessions import _project_config_path
from .store_core import _read_json

DEFAULT_RHYTHM = 1.0
DEFAULT_CLIP_MAX_SECONDS = 15
NORMAL_MANDARIN_SYLLABLES_PER_SECOND = 4.0


def valid_rhythm(value: Any) -> float:
    try:
        rhythm = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("镜头节奏必须在 1.0～2.0 倍之间") from exc
    if not math.isfinite(rhythm) or rhythm < 1 or rhythm > 2 or abs(rhythm * 10 - round(rhythm * 10)) > 0.001:
        raise ValueError("镜头节奏必须为 1.0～2.0 倍之间的 0.1 倍步长")
    return round(rhythm, 1)


def valid_clip_max(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("镜头组时长上限必须为 5～30 秒的整数")
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("镜头组时长上限必须为 5～30 秒的整数") from exc
    if str(value).strip() not in {str(seconds), f"{seconds}.0"} or seconds < 5 or seconds > 30:
        raise ValueError("镜头组时长上限必须为 5～30 秒的整数")
    return seconds


def project_storyboard_timing(project_id: str) -> dict[str, int | float]:
    config = _read_json(_project_config_path(project_id), {})
    storyboard = config.get("storyboard") if isinstance(config, dict) else {}
    storyboard = storyboard if isinstance(storyboard, dict) else {}
    return {
        "rhythmMultiplier": valid_rhythm(storyboard.get("rhythm_multiplier", DEFAULT_RHYTHM)),
        "clipMaxSeconds": valid_clip_max(storyboard.get("clip_max_seconds", DEFAULT_CLIP_MAX_SECONDS)),
    }


def effective_rhythm(project_id: str, card_rhythm: Any) -> float:
    # A saved 1.0x is an explicit card override. Only a missing value inherits.
    inherited = card_rhythm in (None, "")
    return valid_rhythm(
        card_rhythm if not inherited
        else project_storyboard_timing(project_id)["rhythmMultiplier"]
    )


def speech_seconds(shot: dict[str, Any], rhythm: float) -> float:
    """Estimate normal spoken time; visual rhythm never accelerates voices."""
    valid_rhythm(rhythm)
    total = 0.0
    for event in shot.get("soundEvents") or []:
        if not isinstance(event, dict) or event.get("kind") != "voice":
            continue
        content = str(event.get("content") or "").strip()
        if not content:
            continue
        cjk = len(re.findall(r"[\u3400-\u9fff]", content))
        words = len(re.findall(r"[A-Za-z0-9]+", content))
        pauses = len(re.findall(r"[，,；;：:。！？!?…]", content))
        normal_seconds = cjk / NORMAL_MANDARIN_SYLLABLES_PER_SECOND + words / 2.4 + pauses * 0.15
        override = event.get("deliveryOverride")
        stated = float(override.get("durationSec") or 0) if isinstance(override, dict) else 0
        total += max(normal_seconds, stated)
    return round(total, 3)


def formal_shot_seconds(normal_duration: float, shot: dict[str, Any], rhythm: float) -> float:
    """Compress visual time without shortening speech or explicitly timed actions."""
    pace = valid_rhythm(rhythm)
    spoken = speech_seconds(shot, pace)
    if (Decimal(str(normal_duration)) + Decimal(str(SPEECH_ESTIMATE_TOLERANCE_SECONDS))
            < Decimal(str(spoken))):
        raise ValueError("正常镜长短于正常发声时间")
    independent = sum(float(beat["durationSec"]) for beat in shot.get("nonOverlappingBeats") or [])
    formal = max(spoken + max(0.0, normal_duration - spoken) / pace, spoken + independent)
    return math.ceil(formal * 10 - 1e-9) / 10


# Speech timing is an estimate, not a measured waveform. Subsecond differences
# should not force another agent rewrite or an artificial extra cut.
SPEECH_ESTIMATE_TOLERANCE_SECONDS = 0.4


def voice_delivery_issue(event: dict[str, Any], rhythm: float, source_text: str,
                         user_instruction: str) -> str:
    """Require a traceable source for any deliberate departure from the project pace."""
    if event.get("kind") != "voice":
        return ""
    if event.get("durationSec") is not None:
        return "人声 durationSec 不能自行指定；按正常语速估时，确有原文或用户要求慢说时填写 deliveryOverride"
    override = event.get("deliveryOverride")
    if override is None:
        return ""
    if not isinstance(override, dict):
        return "deliveryOverride 必须是包含时长和来源依据的对象"
    stated = float(override.get("durationSec") or 0)
    baseline = speech_seconds({"soundEvents": [{**event, "deliveryOverride": None}]}, rhythm)
    if stated <= baseline + 0.05:
        return f"例外时长 {stated:g} 秒没有超过正常语速估算的 {baseline:g} 秒；请删去 deliveryOverride"
    evidence_source = override.get("evidenceSource")
    evidence = "".join(str(override.get("evidenceText") or "").split())
    corpus = "".join((source_text if evidence_source == "source_text" else user_instruction).split())
    if evidence_source not in {"source_text", "user_instruction"} or not evidence or evidence not in corpus:
        return "deliveryOverride 的依据须逐字出现在当前可拍摄内容、原文或本轮用户指令中"
    spoken = "".join(str(event.get("content") or "").split())
    if evidence in spoken:
        return "仅引用对白原句不能证明需要慢说；请引用明确的表演要求"
    if not str(override.get("reason") or "").strip():
        return "deliveryOverride 必须说明为何需要偏离正常语速"
    return ""


def validate_shot_timing(shots: list[dict[str, Any]], rhythm: float) -> None:
    """Check that picture time can carry speech and actions that cannot overlap it."""
    for index, shot in enumerate(shots, start=1):
        duration = float(shot.get("durationSec") or 0)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"镜头 {index} 缺少有效的画面时长")
        spoken = speech_seconds(shot, rhythm)
        duration_exact = Decimal(str(duration))
        spoken_exact = Decimal(str(spoken))
        tolerated_duration = duration_exact + Decimal(str(SPEECH_ESTIMATE_TOLERANCE_SECONDS))
        if spoken_exact > tolerated_duration:
            raise ValueError(f"镜头 {index} 的连续对白按正常语速约需 {spoken:g} 秒，画面只规划 {duration:g} 秒；请重估声音与动作时间")
        independent_exact = sum(
            (Decimal(str(beat["durationSec"])) for beat in shot.get("nonOverlappingBeats") or []),
            Decimal(0),
        )
        independent = float(independent_exact)
        if independent_exact > duration_exact:
            raise ValueError(f"镜头 {index} 的不能同步完成的动作约需 {independent:g} 秒，画面只规划 {duration:g} 秒；请重估动作时间")
        if spoken_exact + independent_exact > tolerated_duration:
            raise ValueError(
                f"镜头 {index} 的发声约需 {spoken:g} 秒，不能同步完成的动作约需 {independent:g} 秒，"
                f"画面只规划 {duration:g} 秒；请重估声音与动作时间"
            )
