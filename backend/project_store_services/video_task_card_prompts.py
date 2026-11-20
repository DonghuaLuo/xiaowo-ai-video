# -*- coding: utf-8 -*-
"""视频生成逐镜提示词生成、声音排版、契约与内容哈希。"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from .model_generation_contract import _generation_text_value
from .director_plan_contract import (
    _director_plan_normalized_screen_text_events, _director_plan_normalized_sound_events,
    _director_plan_render_sound_event,
)
from .planning_contract import (
    _workflow_timing_number,
)
from .planning_workflow_inputs import (
    _normalize_multiline_prompt_text,
)
from typing import (
    Any,
)


VIDEO_TASK_CARD_PROMPT_TEMPLATE_VERSION = 39


VIDEO_TASK_CARD_PROMPT_HASH_BASIS_VERSION = 15


VIDEO_TASK_CARD_INTERMEDIATE_CONTRACT = "video_prompt_timed_shots_and_voices"


def _video_task_card_hash_text(value: Any) -> str:
    return _normalize_multiline_prompt_text(value)


def _video_task_card_hash_sound_event(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("kind", "voiceType", "speakerId", "sourceName", "sourceNameOriginal", "content", "expressionNotes", "timing"):
        text = _video_task_card_hash_text(event.get(key))
        if text:
            result[key] = text
    return result


def _video_task_card_hash_director_shot(shot: Any, index: int) -> dict[str, Any]:
    if not isinstance(shot, dict):
        return {}
    result: dict[str, Any] = {
        "shotNo": index,
        "storyboardFrame": _video_task_card_hash_text(shot.get("storyboardFrame")),
        "videoExecution": _video_task_card_hash_text(shot.get("videoExecution")),
    }
    sound_events = [
        item
        for item in (
            _video_task_card_hash_sound_event(event)
            for event in (shot.get("soundEvents") if isinstance(shot.get("soundEvents"), list) else [])
        )
        if item
    ]
    if sound_events:
        result["soundEvents"] = sound_events
    screen_text_events = [
        {key: _video_task_card_hash_text(event.get(key)) for key in ("content", "medium", "authorLabel", "timing")}
        for event in (shot.get("screenTextEvents") if isinstance(shot.get("screenTextEvents"), list) else [])
        if isinstance(event, dict)
    ]
    if screen_text_events:
        result["screenTextEvents"] = screen_text_events
    for key in ("presentation",):
        if shot.get(key):
            result[key] = copy.deepcopy(shot[key])
    return result


def _video_task_card_content_hash(context: dict[str, Any], reference_ids: list[str]) -> str:
    basis = {
        "sourceMode": _video_task_card_hash_text(context.get("sourceMode")),
        "directorPlanShots": [
            item
            for item in (
                _video_task_card_hash_director_shot(shot, index)
                for index, shot in enumerate(
                    context.get("directorPlanShots") if isinstance(context.get("directorPlanShots"), list) else [],
                    start=1,
                )
            )
            if item
        ],
        "userInstruction": _video_task_card_hash_text(context.get("userInstruction")),
        "continuityInstruction": _video_task_card_hash_text(context.get("continuityInstruction")),
        "speakerRoster": copy.deepcopy(context.get("speakerRoster") if isinstance(context.get("speakerRoster"), list) else []),
        "assetVoiceDesign": copy.deepcopy(context.get("assetVoiceDesign") if isinstance(context.get("assetVoiceDesign"), dict) else {}),
        "assetNameMap": copy.deepcopy(
            context.get("assetNameMap") if isinstance(context.get("assetNameMap"), dict) else {}
        ),
        "voiceAssetNameMap": copy.deepcopy(
            context.get("voiceAssetNameMap") if isinstance(context.get("voiceAssetNameMap"), dict) else {}
        ),
        "referenceIds": reference_ids,
        "referenceMentions": [[row["mentionKey"], row["mentionLabel"]] for row in context.get("referenceManifest") or []],
        "version": VIDEO_TASK_CARD_PROMPT_TEMPLATE_VERSION,
        "hashBasisVersion": VIDEO_TASK_CARD_PROMPT_HASH_BASIS_VERSION,
    }
    raw = json.dumps(basis, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _video_task_card_intermediate_plan_hash(context: dict[str, Any]) -> str:
    basis = {
        "hasStoryboardReference": bool(context.get("hasStoryboardReference")),
        "referenceMentions": [[row["mentionKey"], row["mentionLabel"]] for row in context.get("referenceManifest") or []],
        "sourceMode": _video_task_card_hash_text(context.get("sourceMode")),
        "directorPlanShots": [
            item
            for item in (
                _video_task_card_hash_director_shot(shot, index)
                for index, shot in enumerate(
                    context.get("directorPlanShots")
                    if isinstance(context.get("directorPlanShots"), list)
                    else [],
                    start=1,
                )
            )
            if item
        ],
        "userInstruction": _video_task_card_hash_text(context.get("userInstruction")),
        "continuityInstruction": _video_task_card_hash_text(context.get("continuityInstruction")),
        "speakerRoster": copy.deepcopy(context.get("speakerRoster") if isinstance(context.get("speakerRoster"), list) else []),
        "assetVoiceDesign": copy.deepcopy(context.get("assetVoiceDesign") if isinstance(context.get("assetVoiceDesign"), dict) else {}),
        "assetNameMap": copy.deepcopy(
            context.get("assetNameMap") if isinstance(context.get("assetNameMap"), dict) else {}
        ),
        "voiceAssetNameMap": copy.deepcopy(
            context.get("voiceAssetNameMap") if isinstance(context.get("voiceAssetNameMap"), dict) else {}
        ),
        "version": VIDEO_TASK_CARD_PROMPT_TEMPLATE_VERSION,
        "hashBasisVersion": VIDEO_TASK_CARD_PROMPT_HASH_BASIS_VERSION,
    }
    raw = json.dumps(basis, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _video_task_card_field_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _video_task_card_format_voice_design_for_prompt(
    voice_design: dict[str, Any] | None,
    asset_voice_design: dict[str, dict[str, str]] | None = None,
    *,
    fallback_asset_ids: set[str] | None = None,
) -> str:
    design = voice_design if isinstance(voice_design, dict) else {}
    speakers = design.get("speakers") if isinstance(design.get("speakers"), list) else []
    asset_rows = copy.deepcopy(asset_voice_design) if isinstance(asset_voice_design, dict) else {}
    fallback_asset_ids = fallback_asset_ids or set()
    # Local voices are authoritative. The project narrator can use a generated
    # voice only when no local narrator voice exists.
    prompt_speakers = [
        speaker for speaker in speakers
        if isinstance(speaker, dict)
        and _video_task_card_field_text(speaker.get("speakerId")) not in asset_rows
        and (
            _video_task_card_field_text(speaker.get("speakerId")) == "project:narrator"
            or _video_task_card_field_text(speaker.get("speakerId")) in fallback_asset_ids
            or not _video_task_card_field_text(speaker.get("speakerId")).startswith(("asset:", "project:"))
        )
    ]
    if not prompt_speakers and not asset_rows:
        return ""
    lines: list[str] = []
    for speaker_id, row in sorted(asset_rows.items()):
        if not isinstance(row, dict):
            continue
        name = _video_task_card_field_text(row.get("displayName")) or speaker_id
        style = _video_task_card_field_text(row.get("voiceStyle"))
        if style:
            lines.append(f"- {name}：{style}")
    for speaker in prompt_speakers:
        if not isinstance(speaker, dict):
            continue
        speaker_id = _video_task_card_field_text(speaker.get("speakerId"))
        display_name = _video_task_card_field_text(speaker.get("displayName")) or speaker_id or "说话者"
        style = _video_task_card_field_text(speaker.get("voiceStyle"))
        lines.append(f"- {display_name}：{style or '沿用本段统一声线'}")
    return "\n".join(lines)


def _video_task_card_trim_terminal_punctuation(text: str) -> str:
    return text.rstrip("。！？；;，, ")


def _video_task_card_format_sound_event_for_prompt(event: dict[str, Any]) -> str:
    kind = _video_task_card_field_text(event.get("kind"))
    voice_type = _video_task_card_field_text(event.get("voiceType"))
    source = _video_task_card_field_text(event.get("sourceName"))
    timing = _video_task_card_field_text(event.get("timing"))
    content = _video_task_card_field_text(event.get("content"))
    expression_notes = _video_task_card_field_text(event.get("expressionNotes"))
    if kind == "voice":
        voice_label = {
            "inner_thought": "内心声",
            "self_talk": "自言自语",
            "voiceover": "画外声",
            "narration": "旁白或播报",
            "crowd": "群体发言",
            "dialogue": "开口声",
        }.get(voice_type, voice_type or "人声")
        fragments = ["人声"]
        if timing:
            fragments.append(f"{timing}发生")
        fragments.append(f"声源={source or '人声'}")
        fragments.append(f"模式={voice_label}")
        if content:
            fragments.append(f"原文=“{content}”")
        if expression_notes:
            fragments.append(f"表现={_video_task_card_trim_terminal_punctuation(expression_notes)}")
        return "；".join(fragments)
    fragments = ["非人声"]
    if timing:
        fragments.append(f"{timing}发生")
    if source:
        fragments.append(f"声源={source}")
    if content:
        fragments.append(f"声音={_video_task_card_trim_terminal_punctuation(content) if expression_notes else content}")
    if expression_notes:
        fragments.append(f"表现={expression_notes}")
    return "；".join(fragment for fragment in fragments if fragment)


def _video_task_card_format_director_plan_for_prompt(shots: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, row in enumerate(shots, start=1):
        shot_no = row.get("shotNo") or index
        block = [
            f"镜头 {shot_no}",
            f"画面与构图：{_video_task_card_field_text(row.get('storyboardFrame'))}",
            f"动态执行：{_video_task_card_field_text(row.get('videoExecution'))}",
            "画面文字：",
        ]
        presentation = row.get("presentation")
        if isinstance(presentation, dict):
            block.append("画面层次：" + "；".join(filter(None, (
                "、".join(presentation.get("modes") or []),
                *(_video_task_card_field_text(presentation.get(key)) for key in (
                    "sourcePerspective", "certainty", "timeRelation", "entryCue", "exitCue", "visualTreatment",
                )),
            ))))
            event_label = presentation.get("eventLabel")
            if isinstance(event_label, dict):
                content = _video_task_card_field_text(event_label.get("content"))
                if content:
                    visibility = "起点可见" if event_label.get("visibleAtStart") is True else "镜内出现"
                    block.append(f"事件短标识：{content}（{visibility}）")
        screen_text_events = row.get("screenTextEvents") or []
        if screen_text_events:
            for event in screen_text_events:
                if not isinstance(event, dict):
                    continue
                details = [
                    _video_task_card_field_text(event.get(key))
                    for key in ("medium", "authorLabel", "content", "timing")
                ]
                block.append("- " + "；".join(value for value in details if value))
        else:
            block.append("- 无")
        block.append("声音事件：")
        events = row.get("soundEvents") or []
        if events:
            for event in events:
                if not isinstance(event, dict):
                    continue
                text = _video_task_card_format_sound_event_for_prompt(event)
                if text:
                    block.append(f"- {text}")
        else:
            block.append("- 无")
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def _video_task_card_intermediate_rows(
    source_rows: list[dict[str, Any]],
    candidate_shots: Any,
) -> list[dict[str, Any]]:
    if not isinstance(candidate_shots, list) or len(candidate_shots) != len(source_rows):
        raise ValueError("视频提示词中间数据生成失败：镜头数量与分镜脚本不一致")
    rows: list[dict[str, Any]] = []
    for index, (source_row, item) in enumerate(zip(source_rows, candidate_shots), start=1):
        if not isinstance(item, dict) or set(item) != {"shotNo", "prompt"}:
            raise ValueError(f"视频提示词中间数据生成失败：第 {index} 个镜头必须只包含 shotNo 和 prompt")
        shot_no = item.get("shotNo")
        if (
            isinstance(shot_no, bool)
            or not isinstance(shot_no, (int, float))
            or shot_no != index
        ):
            raise ValueError(f"视频提示词中间数据生成失败：第 {index} 个镜头编号不一致")
        prompt_value = item.get("prompt")
        if not isinstance(prompt_value, str) or not prompt_value.strip():
            raise ValueError(f"视频提示词中间数据生成失败：第 {index} 个镜头缺少融合正文")
        prompt = _normalize_multiline_prompt_text(prompt_value)
        quoted = [
            next(part for part in match if part)
            for match in re.findall(r'“([^”]*)”|「([^」]*)」|"([^"]*)"', prompt)
            if any(match)
        ]
        for event in source_row.get("soundEvents") or []:
            if not isinstance(event, dict) or event.get("kind") != "voice":
                continue
            content = _video_task_card_field_text(event.get("content"))
            if content and content not in prompt:
                raise ValueError(f"视频提示词中间数据生成失败：第 {index} 个镜头台词未逐字保留：{content}")
            source_name = _video_task_card_field_text(event.get("sourceName"))
            source_aliases = [
                value for value in (
                    source_name,
                    _video_task_card_field_text(event.get("sourceNameOriginal")),
                )
                if value
            ]
            if source_aliases and any(
                text != content
                and any(text.startswith((alias + "：", alias + ":")) for alias in source_aliases)
                for text in quoted
            ):
                raise ValueError(
                    f"视频提示词中间数据生成失败：第 {index} 个镜头声源名称混入台词正文：{source_name}"
                )
        # Text already visible in the storyboard image stays there. Exact plot text
        # introduced during the shot must survive the generated video prompt.
        for event in source_row.get("screenTextEvents") or []:
            if not isinstance(event, dict) or event.get("visibleAtStart") is True:
                continue
            content = _video_task_card_field_text(event.get("content"))
            if content and content not in prompt:
                raise ValueError(f"视频提示词中间数据生成失败：第 {index} 个镜头镜内画面文字未逐字保留：{content}")
        rows.append({"shotNo": index, "prompt": prompt})
    return rows


def _video_task_card_timed_rows(
    source_rows: list[dict[str, Any]],
    candidate_shots: Any,
    clip_duration_seconds: Any,
) -> list[dict[str, Any]]:
    """Validate one continuous timeline against the current video card, then validate content."""
    try:
        clip_duration = Decimal(str(clip_duration_seconds))
    except (InvalidOperation, TypeError, ValueError):
        clip_duration = Decimal(0)
    if not clip_duration.is_finite() or clip_duration <= 0:
        raise ValueError("视频提示词时间账校验失败：视频卡缺少有效的整片时长")
    if not isinstance(candidate_shots, list) or len(candidate_shots) != len(source_rows):
        raise ValueError("视频提示词时间账校验失败：镜头数量与分镜脚本不一致")
    plain_rows: list[dict[str, Any]] = []
    durations: list[Decimal] = []
    for index, item in enumerate(candidate_shots, start=1):
        if not isinstance(item, dict) or set(item) != {"shotNo", "durationSec", "prompt"}:
            raise ValueError(f"视频提示词时间账校验失败：第 {index} 镜必须包含 shotNo、durationSec 和 prompt")
        value = item["durationSec"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"视频提示词时间账校验失败：第 {index} 镜时长必须为数字")
        try:
            duration = Decimal(str(value))
        except (InvalidOperation, ValueError):
            duration = Decimal(0)
        if not duration.is_finite() or duration <= 0 or duration.as_tuple().exponent < -1:
            raise ValueError(f"视频提示词时间账校验失败：第 {index} 镜时长必须大于 0，最多保留一位小数")
        durations.append(duration)
        plain_rows.append({"shotNo": item["shotNo"], "prompt": item["prompt"]})
    total = sum(durations, Decimal(0))
    if total != clip_duration:
        raise ValueError(
            f"视频提示词时间账校验失败：逐镜时长合计 {_video_task_card_seconds_text(total)} 秒，"
            f"视频卡为 {_video_task_card_seconds_text(clip_duration)} 秒；请调整逐镜分配"
        )
    rows = _video_task_card_intermediate_rows(source_rows, plain_rows)
    for row, duration in zip(rows, durations):
        row["durationSec"] = float(duration)
    return rows


def _video_task_card_seconds_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _video_task_card_compact_intermediate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        result.append(
            {
                "shotNo": int(_workflow_timing_number(row.get("shotNo")) or index),
                "prompt": _normalize_multiline_prompt_text(row.get("prompt")),
                **({"durationSec": row["durationSec"]} if "durationSec" in row else {}),
            }
        )
    return result




def _video_task_card_source_prompt_from_context(
    context: dict[str, Any],
    structured_shots: list[dict[str, Any]],
) -> str:
    shot_prompt = _video_task_card_prompt_from_structured_shots(
        structured_shots,
    )
    if not shot_prompt:
        raise RuntimeError("当前分镜脚本缺少可用视频执行镜头，请重新生成分镜脚本")
    parts = [shot_prompt]
    user_instruction = _generation_text_value(context.get("userInstruction"), limit=0)
    if user_instruction:
        parts.append(f"【本轮生成要求】\n{user_instruction}")
    continuity_instruction = _generation_text_value(context.get("continuityInstruction"), limit=0)
    if continuity_instruction:
        parts.append(f"【相邻片段衔接】\n{continuity_instruction}")
    return "\n\n".join(part for part in parts if part).strip()


def _video_task_card_shot_prompt_parts_from_row(row: dict[str, Any]) -> list[str]:
    if not isinstance(row, dict):
        return []
    prompt_parts: list[str] = []
    video_execution = _normalize_multiline_prompt_text(row.get("videoExecution"))
    if video_execution:
        prompt_parts.append(f"执行：{video_execution}")
    presentation = row.get("presentation")
    if isinstance(presentation, dict):
        details = [
            *(_video_task_card_field_text(presentation.get(key)) for key in (
                "sourcePerspective", "certainty", "timeRelation", "entryCue", "exitCue",
            )),
        ]
        if any(details):
            prompt_parts.append("来源与时序：" + "；".join(value for value in details if value))
        event_label = presentation.get("eventLabel")
        if isinstance(event_label, dict):
            content = _video_task_card_field_text(event_label.get("content"))
            if content:
                visibility = "起点可见" if event_label.get("visibleAtStart") is True else "按镜内执行出现"
                prompt_parts.append(f"事件短标识：{content}（{visibility}）")
    try:
        sound_events = _director_plan_normalized_sound_events(
            row.get("soundEvents") if "soundEvents" in row else [], shot_no=int(row.get("shotNo") or 1),
        )
    except ValueError:
        sound_events = []
    for event in sound_events:
        rendered = _director_plan_render_sound_event(event)
        if rendered:
            prompt_parts.append(rendered)
    for event in row.get("screenTextEvents") or []:
        if isinstance(event, dict):
            details = "；".join(filter(None, (
                _video_task_card_field_text(event.get("medium")),
                _video_task_card_field_text(event.get("authorLabel")),
                _video_task_card_field_text(event.get("content")),
                _video_task_card_field_text(event.get("timing")),
            )))
            if details:
                prompt_parts.append(f"画面文字：{details}")
    return prompt_parts


def _director_plan_shot_rows_from_structured(
    value: Any,
) -> list[dict[str, Any]]:
    shots = value if isinstance(value, list) else []
    rows: list[dict[str, Any]] = []
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            return []
        shot_no = _workflow_timing_number(shot.get("shotNo"))
        storyboard_frame = _normalize_multiline_prompt_text(shot.get("storyboardFrame"))
        video_execution = _normalize_multiline_prompt_text(shot.get("videoExecution"))
        try:
            sound_events = _director_plan_normalized_sound_events(
                shot.get("soundEvents") if "soundEvents" in shot else [], shot_no=index,
            )
            screen_text_events = _director_plan_normalized_screen_text_events(
                shot.get("screenTextEvents") if "screenTextEvents" in shot else [], shot_no=index,
            )
        except ValueError:
            return []
        if (
            shot_no is None
            or not float(shot_no).is_integer()
            or int(shot_no) != index
            or not storyboard_frame
            or not video_execution
        ):
            return []
        label = f"Shot {index:02d}"
        video_prompt = "；".join(
            _video_task_card_shot_prompt_parts_from_row(
                {
                    "storyboardFrame": storyboard_frame,
                    "videoExecution": video_execution,
                    "soundEvents": sound_events,
                    "screenTextEvents": screen_text_events,
                    "presentation": shot.get("presentation"),
                }
            )
        )
        row = {
            "shotId": f"shot_{index:02d}",
            "shotLabel": label,
            "title": label,
            "visibleAction": storyboard_frame,
            "storyboardFrame": storyboard_frame,
            "videoExecution": video_execution,
            "soundEvents": copy.deepcopy(sound_events),
            "screenTextEvents": copy.deepcopy(screen_text_events),
            "presentation": copy.deepcopy(shot.get("presentation")),
            "visibleAssets": copy.deepcopy(shot.get("visibleAssets")),
            "startVisibleAssets": copy.deepcopy(shot.get("startVisibleAssets")),
            "prompt": video_prompt,
            "source": "director_plan",
        }
        rows.append(row)
    return rows


def _video_task_card_prompt_from_structured_shots(
    shots: list[dict[str, Any]],
) -> str:
    """Render provider-neutral editor text; adapt labels only at submission."""
    lines: list[str] = []
    elapsed = Decimal(0)
    timed = bool(shots) and all("durationSec" in row for row in shots)
    for row in shots:
        label = str(row.get("shotLabel") or "").strip()
        prompt = _normalize_multiline_prompt_text(row.get("prompt"))
        if not label or not prompt:
            continue
        if timed:
            duration = Decimal(str(row["durationSec"]))
            end = elapsed + duration
            lines.append(
                f"镜头{len(lines) + 1}｜{_video_task_card_seconds_text(elapsed)}–"
                f"{_video_task_card_seconds_text(end)}秒（{_video_task_card_seconds_text(duration)}秒）：{prompt}"
            )
            elapsed = end
        else:
            lines.append(f"镜头{len(lines) + 1}：{prompt}")
    if timed and lines:
        lines.insert(0, f"整片时长：{_video_task_card_seconds_text(elapsed)}秒。")
    return "\n".join(lines).strip()
