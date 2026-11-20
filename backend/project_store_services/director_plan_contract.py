# -*- coding: utf-8 -*-
"""分镜脚本的镜头、声音与文本契约，供生成、编辑和历史恢复共同使用。"""
from __future__ import annotations

import copy
from .generation_config import (
    _video_task_card_allowed_duration_label,
    _video_task_card_allowed_duration_values,
)
from .generation_input_context import (
    _work_chain_video_task_ids_for_director,
)
from .planning_contract import (
    _workflow_clean_seconds,
    _workflow_timing_number,
)
from .workflow_contract import (
    _workflow_node,
)
from typing import (
    Any,
)

import re
import math
from decimal import Decimal, InvalidOperation


def _normalize_multiline_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    rows: list[str] = []
    last_blank = False
    for raw_line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if line:
            rows.append(line)
            last_blank = False
        elif rows and not last_blank:
            rows.append("")
            last_blank = True
    return "\n".join(rows).strip()


_DIRECTOR_PLAN_SOUND_KINDS = {"voice", "ambient", "sfx", "music"}

_DIRECTOR_ENTRY_BOUNDARY_KINDS = {
    "direct_continuation", "spatial_cut", "ordinary_cut", "time_space_jump",
}
_DIRECTOR_AUDIO_BOUNDARY_KINDS = {
    "continuous_ambience", "dialogue_overlap", "hard_cut", "intentional_silence",
}


_DIRECTOR_PLAN_VOICE_TYPES = {"dialogue", "self_talk", "inner_thought", "crowd", "narration"}

_SOURCE_VOICE_LABELED = re.compile(
    r"^\s*(?:[^：:\n]+?[（(](?:对白|内心声|自言自语|旁白|画外音|群众发言)[^）)]*[）)]|旁白|画外音|群众声)\s*[：:]\s*(.+)$"
)
_SOURCE_VOICE_MARKED = re.compile(r"^\s*【([^】]+)】\s*(.+)$")
_SOURCE_PARENTHESIZED_LINE = re.compile(r"^\s*[^：:\n（）()]+[（(]([^）)]*)[）)]\s*[：:]\s*(.+)$")
_SOURCE_AUDIO_MARKERS = ("对白", "内心声", "自言自语", "旁白", "画外音", "群众发言", "设备声", "通话声", "录音声", "播报声")
_SOURCE_NONVOICE_MARKERS = ("画面文字", "屏幕文字", "字幕", "音效", "环境声", "音乐")


def director_plan_source_voice_lines(text: str) -> list[str]:
    """Extract only language explicitly marked as spoken in a shootable script."""
    lines: list[str] = []
    for line in str(text or "").splitlines():
        labeled = _SOURCE_VOICE_LABELED.match(line)
        if labeled:
            lines.append(labeled.group(1).strip())
            continue
        parenthesized = _SOURCE_PARENTHESIZED_LINE.match(line)
        if parenthesized:
            annotation = parenthesized.group(1)
            if (any(marker in annotation for marker in _SOURCE_AUDIO_MARKERS)
                    and not any(marker in annotation for marker in _SOURCE_NONVOICE_MARKERS)):
                lines.append(parenthesized.group(2).strip())
                continue
        marked = _SOURCE_VOICE_MARKED.match(line)
        if marked and any(label in marked.group(1) for label in (
            "对白", "内心声", "独白", "画外音", "群众发言", "旁白",
        )):
            spoken = marked.group(2).lstrip("：:").strip()
            if spoken:
                lines.append(spoken)
    return lines


def _voice_match_text(value: Any) -> str:
    """Ignore quotation marks enclosing a line, not its spoken punctuation."""
    text = "".join(str(value or "").split())
    if len(text) >= 2 and (text[0], text[-1]) in {
        ("“", "”"), ("‘", "’"), ('"', '"'), ("'", "'"),
    }:
        return text[1:-1]
    return text


def director_plan_source_voice_matches(source_text: str, shots: list[dict[str, Any]]) -> bool:
    """Require marked source speech in order; extra voice may quote visible screen text."""
    required = "".join(_voice_match_text(line) for line in director_plan_source_voice_lines(source_text))
    if not required:
        return True
    screen_text = {
        _voice_match_text(event.get("content"))
        for shot in shots for event in shot.get("screenTextEvents") or []
        if isinstance(event, dict)
    }
    positions = {0}
    for shot in shots:
        for event in shot.get("soundEvents") or []:
            if not isinstance(event, dict) or event.get("kind") != "voice":
                continue
            spoken = _voice_match_text(event.get("content"))
            next_positions = {
                position + len(spoken) for position in positions
                if spoken and required.startswith(spoken, position)
            }
            if spoken in screen_text:
                next_positions.update(positions)
            positions = next_positions
            if not positions:
                return False
    return len(required) in positions


def director_plan_source_voice_mismatch(source_text: str, shots: list[dict[str, Any]]) -> str:
    """Explain the first audible divergence without dumping the full script."""
    required = "".join(_voice_match_text(line) for line in director_plan_source_voice_lines(source_text))
    screen_text = {
        _voice_match_text(event.get("content"))
        for shot in shots for event in shot.get("screenTextEvents") or [] if isinstance(event, dict)
    }
    positions = {0}
    for shot_index, shot in enumerate(shots, start=1):
        for event in shot.get("soundEvents") or []:
            if not isinstance(event, dict) or event.get("kind") != "voice":
                continue
            spoken = _voice_match_text(event.get("content"))
            next_positions = {position + len(spoken) for position in positions
                              if spoken and required.startswith(spoken, position)}
            if spoken in screen_text:
                next_positions.update(positions)
            if not next_positions:
                position = max(positions)
                return (f"镜头 {shot_index} 的人声从“{spoken[:24]}”开始，"
                        f"原文此处应接“{required[position:position + 24]}”")
            positions = next_positions
    if len(required) not in positions:
        position = max(positions)
        return f"镜头结束后仍缺少原文发声：“{required[position:position + 30]}”"
    return ""


def _director_plan_inline_text(value: Any) -> str:
    return " ".join(
        line.strip()
        for line in _normalize_multiline_text(value).splitlines()
        if line.strip()
    )


def _director_plan_shot_number(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"分镜脚本镜头的 {field_name} 无效")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"分镜脚本镜头的 {field_name} 无效") from exc
    if not number.is_integer() or number <= 0:
        raise ValueError(f"分镜脚本镜头的 {field_name} 必须是正整数")
    return int(number)


def _director_plan_optional_sound_duration(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        seconds = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not seconds.is_finite() or seconds <= 0 or seconds > 3600:
        return None
    centiseconds = seconds * 100
    if centiseconds != centiseconds.to_integral_value():
        return None
    ticks = int(centiseconds)
    return ticks // 100 if ticks % 100 == 0 else ticks / 100


_DIRECTOR_PLAN_ASSET_KINDS = ("characters", "creatures", "scenes", "props")


def _director_plan_shot_assets(
    value: Any, shot_no: int, allowed_asset_ids: dict[str, set[str]] | None,
) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ValueError(f"分镜脚本镜头 {shot_no:02d} 缺少资产列表")
    result: dict[str, list[str]] = {}
    for kind in _DIRECTOR_PLAN_ASSET_KINDS:
        ids = value.get(kind)
        if not isinstance(ids, list) or any(not isinstance(item, str) or not item.strip() for item in ids):
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 {kind} 必须是资产 ID 数组")
        if len(ids) != len(set(ids)):
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 {kind} 有重复资产")
        if allowed_asset_ids is not None and any(item not in allowed_asset_ids.get(kind, set()) for item in ids):
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 {kind} 包含未绑定资产")
        result[kind] = ids[:]
    return result


def _director_plan_visible_assets(
    value: Any, shot_no: int, assets: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Identify on-screen identities; `assets` also includes off-screen voices/use."""
    if not isinstance(value, dict):
        raise ValueError(f"分镜脚本镜头 {shot_no:02d} 缺少 visibleAssets")
    visible = _director_plan_shot_assets(value, shot_no, None)
    for kind in _DIRECTOR_PLAN_ASSET_KINDS:
        extra = set(visible[kind]) - set(assets[kind])
        if extra:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 visibleAssets.{kind} 包含未列入 assets 的资产")
    return visible


def _director_plan_public_asset_labels(
    value: Any, shot_no: int, visible_assets: dict[str, list[str]],
) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 publicAssetLabels 必须是数组")
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的公开称谓无效")
        kind = str(raw.get("assetType") or "")
        asset_id = str(raw.get("assetId") or "").strip()
        content = _director_plan_inline_text(raw.get("content"))
        source_type = str(raw.get("sourceType") or "")
        quote = _director_plan_inline_text(raw.get("sourceQuote"))
        if (kind not in _DIRECTOR_PLAN_ASSET_KINDS or asset_id not in visible_assets.get(kind, [])
                or not content or not quote or content not in quote
                or source_type not in {"shootable_content", "source_fact"}
                or (kind, asset_id) in seen):
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的公开称谓须对应可见资产和原文中的准确短引文")
        result.append({"assetType": kind, "assetId": asset_id, "content": content,
                       "sourceType": source_type, "sourceQuote": quote})
        seen.add((kind, asset_id))
    return result


def _director_plan_normalized_sound_events(
    value: Any,
    *,
    shot_no: int,
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 soundEvents 必须是数组")
    rows = value
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条声音事件不是有效对象")
        content = _director_plan_inline_text(raw.get("content"))
        expression_notes = _director_plan_inline_text(raw.get("expressionNotes"))
        source_name = _director_plan_inline_text(raw.get("sourceName"))
        timing = _director_plan_inline_text(raw.get("timing"))
        if not any((content, expression_notes, source_name, timing)):
            continue
        kind = str(raw.get("kind") or "").strip().casefold()
        if kind not in _DIRECTOR_PLAN_SOUND_KINDS:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条声音事件缺少 kind")
        if not content:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条声音事件缺少 content")
        voice_type = str(raw.get("voiceType") or "").strip().casefold()
        if kind == "voice" and voice_type not in _DIRECTOR_PLAN_VOICE_TYPES:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条人声事件缺少有效 voiceType")
        if kind == "voice" and not source_name:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条人声事件缺少声源")
        row: dict[str, Any] = {
            "kind": kind,
            "content": content,
            "expressionNotes": expression_notes,
        }
        if kind == "voice":
            row["voiceType"] = voice_type
            speaker_id = _director_plan_inline_text(raw.get("speakerId"))
            if speaker_id:
                row["speakerId"] = speaker_id
        if source_name:
            row["sourceName"] = source_name
        if timing:
            row["timing"] = timing
        if kind == "voice" and raw.get("durationSec") is not None:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条人声不能自行填写 durationSec；请使用项目镜头节奏或有来源依据的 deliveryOverride")
        if kind == "voice" and raw.get("deliveryOverride") is not None:
            override = raw["deliveryOverride"]
            if not isinstance(override, dict):
                raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条 deliveryOverride 必须是对象")
            raw_seconds = override.get("durationSec")
            seconds = (_director_plan_optional_sound_duration(raw_seconds)
                       if isinstance(raw_seconds, (int, float)) and not isinstance(raw_seconds, bool)
                       else None)
            evidence_source = str(override.get("evidenceSource") or "").strip()
            evidence_text = _director_plan_inline_text(override.get("evidenceText"))
            reason = _director_plan_inline_text(override.get("reason"))
            if (seconds is None or evidence_source not in {"source_text", "user_instruction"}
                    or not evidence_text or not reason):
                raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条 deliveryOverride 缺少有效时长、来源引文或表演理由")
            row["deliveryOverride"] = {
                "durationSec": seconds, "evidenceSource": evidence_source,
                "evidenceText": evidence_text, "reason": reason,
            }
        elif kind != "voice" and raw.get("deliveryOverride") is not None:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条非人声不能填写 deliveryOverride")
        if kind != "voice":
            duration_seconds = _director_plan_optional_sound_duration(raw.get("durationSec"))
            if raw.get("durationSec") not in (None, "") and duration_seconds is None:
                raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条非人声时长须为大于零、最多两位小数的秒数")
            if duration_seconds is not None:
                row["durationSec"] = duration_seconds
        result.append(row)
    return result


def _director_plan_normalized_screen_text_events(value: Any, *, shot_no: int) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 screenTextEvents 必须是数组")
    result: list[dict[str, str]] = []
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条画面文字不是有效对象")
        content = _director_plan_inline_text(raw.get("content"))
        medium = _director_plan_inline_text(raw.get("medium"))
        author_label = _director_plan_inline_text(raw.get("authorLabel"))
        timing = _director_plan_inline_text(raw.get("timing"))
        if not any((content, medium, author_label, timing)):
            continue
        if not content or not medium:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条画面文字缺少内容或载体")
        row = {"content": content, "medium": medium}
        if "visibleAtStart" in raw:
            if not isinstance(raw["visibleAtStart"], bool):
                raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的画面文字 visibleAtStart 必须是布尔值")
            row["visibleAtStart"] = raw["visibleAtStart"]
        if author_label:
            row["authorLabel"] = author_label
        if timing:
            row["timing"] = timing
        result.append(row)
    return result


_PRESENTATION_MODES = {
    "normal",
    "chronological_compression", "memory", "dream", "imagination",
    "reported", "mediated", "parallel", "inner", "time_jump", "perceptual_distortion",
    "process_montage", "character_account", "romantic_ambiguity",
}

_SEQUENCE_PRESENTATION_KINDS = {
    "continuous", "fast_exposition", "memory", "character_account", "subjective", "other",
}
_SEQUENCE_LOOK_VARIANTS = {
    "project_baseline", "project_treated", "ink_wash", "anime_cutout", "vignette_soft_focus",
    "graphic_montage", "other_custom",
}


def _director_plan_normalized_sequence_presentation(value: Any, *, shot_no: int) -> dict[str, Any] | None:
    if value is None or value == {}:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的跨镜表达方案必须是对象")
    kind = str(value.get("kind") or "").strip()
    if kind not in _SEQUENCE_PRESENTATION_KINDS:
        raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的跨镜表达类型无效")
    look = str(value.get("lookVariant") or "").strip()
    if look and (look not in _SEQUENCE_LOOK_VARIANTS or (kind != "continuous" and look == "project_baseline")):
        raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的特殊表达须选择区别于普通现场的 lookVariant")
    result = {"kind": kind}
    if look:
        result["lookVariant"] = look
    if "visualLayers" in value:
        layers = value["visualLayers"]
        if not isinstance(layers, dict) or set(layers) != {"visualStyle", "themeVisual", "phaseVisual"} or any(
            not isinstance(layers[key], bool) for key in layers
        ):
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 visualLayers 必须明确三个项目视觉层的布尔应用范围")
        if look == "project_treated" and not layers["visualStyle"]:
            raise ValueError(
                f"分镜脚本镜头 {shot_no:02d} 选择 project_treated 时须保留项目视觉风格；"
                "若要更换渲染媒介，请选择相应差异画法并写明兼容的主题与阶段视觉"
            )
        result["visualLayers"] = dict(layers)
    if "mediumChangeBasis" in value:
        basis = value["mediumChangeBasis"]
        if (not isinstance(basis, dict) or set(basis) != {"source", "quote", "reason"}
                or not isinstance(basis.get("source"), str)
                or basis["source"] not in {"project_visuals", "user_instruction", "shootable_content"}
                or any(not _director_plan_inline_text(basis.get(key)) for key in ("quote", "reason"))):
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 mediumChangeBasis 须有来源、准确引文和换媒介理由")
        result["mediumChangeBasis"] = {
            "source": basis["source"],
            "quote": _director_plan_inline_text(basis["quote"]),
            "reason": _director_plan_inline_text(basis["reason"]),
        }
    for field in ("sequenceId", "sourcePerspective", "certainty", "timeRelation",
                  "staticLook", "motionTreatment", "overlayTreatment"):
        content = _director_plan_inline_text(value.get(field))
        if not content:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的跨镜表达方案缺少 {field}")
        result[field] = content
    return result


def _director_plan_normalized_presentation(value: Any, *, shot_no: int) -> dict[str, Any] | None:
    if value is None or value == {}:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的画面段落必须是对象")
    modes = value.get("modes")
    if (not isinstance(modes, list) or not modes
            or any(not isinstance(mode, str) or mode not in _PRESENTATION_MODES for mode in modes)
            or len(set(modes)) != len(modes)):
        raise ValueError(
            f"分镜脚本镜头 {shot_no:02d} 的 presentation.modes 无效；"
            f"只能从 {', '.join(sorted(_PRESENTATION_MODES))} 中选择，"
            "顺时压缩用 chronological_compression，普通现场只用 normal"
        )
    if "normal" in modes:
        if modes != ["normal"]:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的普通现场不能与特殊画面段落混用")
        return None
    required = ("segmentId", "sourcePerspective", "certainty", "timeRelation")
    result: dict[str, Any] = {"modes": modes[:]}
    for field in required:
        text = _director_plan_inline_text(value.get(field))
        if not text:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的画面段落缺少 {field}")
        result[field] = text
    for field in ("entryCue", "exitCue"):
        text = _director_plan_inline_text(value.get(field))
        if text:
            result[field] = text
    event_label = value.get("eventLabel")
    if event_label is not None:
        if not isinstance(event_label, dict):
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的事件短标识必须是对象")
        content = _director_plan_inline_text(event_label.get("content"))
        source_quote = _director_plan_inline_text(event_label.get("sourceQuote"))
        visible_at_start = event_label.get("visibleAtStart")
        if not content or not source_quote or not isinstance(visible_at_start, bool):
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的事件短标识缺少内容、来源短引文或起点可见状态")
        result["eventLabel"] = {
            "content": content, "sourceQuote": source_quote,
            "visibleAtStart": visible_at_start,
        }
    return result


def _expand_shared_presentation_references(shots: list[Any]) -> list[Any]:
    """Expand one declared segment/sequence plan into later ID-only references."""
    expanded = copy.deepcopy(shots)
    sequences: dict[str, dict[str, Any]] = {}
    segments: dict[str, dict[str, Any]] = {}
    for shot in expanded:
        if not isinstance(shot, dict):
            continue
        sequence = shot.get("sequencePresentation")
        if isinstance(sequence, dict):
            sequence_id = str(sequence.get("sequenceId") or "").strip()
            if sequence_id in sequences:
                shot["sequencePresentation"] = {**sequences[sequence_id], **sequence}
            elif sequence_id:
                sequences[sequence_id] = copy.deepcopy(sequence)
        presentation = shot.get("presentation")
        if isinstance(presentation, dict) and presentation.get("modes") != ["normal"]:
            segment_id = str(presentation.get("segmentId") or "").strip()
            if segment_id in segments:
                # Entry, exit and event label belong to each shot.
                shot["presentation"] = {**segments[segment_id], **presentation}
            elif segment_id:
                segments[segment_id] = {
                    key: copy.deepcopy(value) for key, value in presentation.items()
                    if key not in {"entryCue", "exitCue", "eventLabel"}
                }
    return expanded


def _director_plan_normalized_editorial_text_events(value: Any, *, shot_no: int) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 editorialTextEvents 必须是数组")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条编辑层文字无效")
        row: dict[str, Any] = {}
        for field in ("eventId", "content", "sourceQuote", "anchor", "placement", "styleIntent"):
            text = _director_plan_inline_text(raw.get(field))
            if not text:
                raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条编辑层文字缺少 {field}")
            row[field] = text
        source_type = str(raw.get("sourceType") or "").strip()
        if source_type not in {"shootable_content", "source_fact", "asset_fact", "user_instruction"}:
            raise ValueError(
                f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条编辑层文字 sourceType 无效；"
                "仅允许 shootable_content（当前可拍剧本）、source_fact（片段原文）、"
                "asset_fact（有效资产事实）、user_instruction（本轮用户要求）。"
                "sourceQuote 必须是对应来源里的准确短引文"
            )
        delivery_path = str(raw.get("deliveryPath") or "").strip()
        if delivery_path not in {"post", "model", "pending"}:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条编辑层文字制作路径无效")
        row["sourceType"] = source_type
        row["deliveryPath"] = delivery_path
        start, end = raw.get("startFraction"), raw.get("endFraction")
        if (isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end > 1 or end <= start):
            raise ValueError(
                f"分镜脚本镜头 {shot_no:02d} 的第 {index} 条编辑层文字读字区间无效；"
                "请填写数字字段 startFraction 和 endFraction，满足 0≤startFraction<endFraction≤1；"
                "不要使用 startRatio/endRatio 或秒数"
            )
        row["startFraction"] = round(float(start), 4)
        row["endFraction"] = round(float(end), 4)
        if raw.get("eventType") == "asset_intro":
            kind = str(raw.get("assetType") or "")
            asset_id = str(raw.get("assetId") or "").strip()
            first_no = raw.get("firstShotNo")
            scope = str(raw.get("appearanceScope") or "")
            if (kind not in _DIRECTOR_PLAN_ASSET_KINDS or not asset_id
                    or not isinstance(first_no, int) or first_no < 1
                    or scope not in {"project", "provisional", "independent"}):
                raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的资产介绍卡归属无效")
            row.update({"eventType": "asset_intro", "assetType": kind, "assetId": asset_id,
                        "firstShotNo": first_no, "appearanceScope": scope})
            source_version = _director_plan_inline_text(raw.get("sourceVersion"))
            if source_version:
                row["sourceVersion"] = source_version
        result.append(row)
    return result


def _director_plan_normalized_shots(
    value: Any,
    *,
    allowed_asset_ids: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("模型未返回可用镜头计划")
    value = _expand_shared_presentation_references(value)
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"分镜脚本第 {index} 个镜头不是有效对象")
        shot_no = _director_plan_shot_number(raw.get("shotNo"), "shotNo")
        if shot_no != index:
            raise ValueError("分镜脚本镜头编号必须从 1 开始连续递增")
        if "durationRangeSec" in raw:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 不接受 durationRangeSec，请填写 durationSec")
        duration_sec = _director_plan_optional_sound_duration(raw.get("durationSec")) or 0
        if raw.get("durationSec") not in (None, "") and duration_sec <= 0:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 durationSec 须为大于零、最多两位小数的秒数")
        if duration_sec <= 0:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 缺少 durationSec")
        storyboard_frame = _director_plan_inline_text(raw.get("storyboardFrame"))
        video_execution = _director_plan_inline_text(raw.get("videoExecution"))
        if not storyboard_frame or not video_execution:
            raise ValueError(f"分镜脚本镜头 {shot_no:02d} 缺少分镜画面或视频执行")
        sound_events = _director_plan_normalized_sound_events(
            raw.get("soundEvents") if "soundEvents" in raw else [],
            shot_no=shot_no,
        )
        screen_text_events = _director_plan_normalized_screen_text_events(
            raw.get("screenTextEvents") if "screenTextEvents" in raw else [],
            shot_no=shot_no,
        )
        presentation = _director_plan_normalized_presentation(raw.get("presentation"), shot_no=shot_no)
        sequence_presentation = _director_plan_normalized_sequence_presentation(
            raw.get("sequencePresentation"), shot_no=shot_no,
        )
        editorial_text_events = _director_plan_normalized_editorial_text_events(
            raw.get("editorialTextEvents"), shot_no=shot_no,
        )
        row: dict[str, Any] = {
            "shotNo": shot_no,
            "durationSec": duration_sec,
            "storyboardFrame": storyboard_frame,
            "videoExecution": video_execution,
            "screenTextEvents": screen_text_events,
            "soundEvents": sound_events,
        }
        if raw.get("normalDurationSec") not in (None, ""):
            normal_seconds = _director_plan_optional_sound_duration(raw["normalDurationSec"])
            if normal_seconds is None:
                raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 normalDurationSec 须为大于零、最多两位小数的秒数")
            row["normalDurationSec"] = normal_seconds
        if raw.get("groupBreakBefore") is not None:
            if not isinstance(raw["groupBreakBefore"], bool):
                raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 groupBreakBefore 必须为布尔值")
            if raw["groupBreakBefore"]:
                row["groupBreakBefore"] = True
        for field, allowed in (
            ("entryBoundaryKind", _DIRECTOR_ENTRY_BOUNDARY_KINDS),
            ("audioBoundaryKind", _DIRECTOR_AUDIO_BOUNDARY_KINDS),
        ):
            if raw.get(field) not in allowed:
                raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 {field} 必须选择有效的交接类型")
            row[field] = raw[field]
        if presentation is not None:
            row["presentation"] = presentation
        if sequence_presentation is not None:
            row["sequencePresentation"] = sequence_presentation
        if editorial_text_events:
            row["editorialTextEvents"] = editorial_text_events
        if raw.get("nonOverlappingBeats") is not None:
            beats = raw["nonOverlappingBeats"]
            if not isinstance(beats, list):
                raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的 nonOverlappingBeats 必须是数组")
            normalized_beats = []
            for beat_index, beat in enumerate(beats, start=1):
                if not isinstance(beat, dict):
                    raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {beat_index} 个独立时段无效")
                description = _director_plan_inline_text(beat.get("description"))
                beat_seconds = _director_plan_optional_sound_duration(beat.get("durationSec"))
                if not description or beat_seconds is None:
                    raise ValueError(f"分镜脚本镜头 {shot_no:02d} 的第 {beat_index} 个独立时段缺少动作说明或有效秒数")
                normalized_beats.append({"description": description, "durationSec": beat_seconds})
            row["nonOverlappingBeats"] = normalized_beats
        if "assets" in raw:
            row["assets"] = _director_plan_shot_assets(raw["assets"], shot_no, allowed_asset_ids)
            if "visibleAssets" in raw:
                row["visibleAssets"] = _director_plan_visible_assets(raw["visibleAssets"], shot_no, row["assets"])
                if raw.get("startVisibleAssets") is not None:
                    row["startVisibleAssets"] = _director_plan_visible_assets(
                        raw["startVisibleAssets"], shot_no, row["visibleAssets"],
                    )
        if "publicAssetLabels" in raw:
            row["publicAssetLabels"] = _director_plan_public_asset_labels(
                raw["publicAssetLabels"], shot_no, row.get("visibleAssets") or {},
            )
        for field in ("visualPurpose", "endState"):
            if field in raw:
                text = _director_plan_inline_text(raw[field])
                if not text:
                    raise ValueError(f"分镜脚本镜头 {shot_no:02d} 缺少 {field}")
                row[field] = text
        rows.append(row)
    segments: dict[str, tuple[int, dict[str, Any]]] = {}
    sequences: dict[str, tuple[int, dict[str, str]]] = {}
    for shot in rows:
        sequence = shot.get("sequencePresentation")
        if sequence:
            sequence_id = sequence["sequenceId"]
            first = sequences.get(sequence_id)
            if first and (first[1] != sequence or shot["shotNo"] > first[0] + 1
                          and rows[shot["shotNo"] - 2].get("sequencePresentation", {}).get("sequenceId") != sequence_id):
                raise ValueError(f"分镜脚本跨镜表达方案 {sequence_id} 的内容不一致或镜头不连续")
            sequences.setdefault(sequence_id, (shot["shotNo"], sequence))
        presentation = shot.get("presentation")
        if not presentation:
            continue
        segment_id = presentation["segmentId"]
        common = {key: presentation[key] for key in (
            "modes", "sourcePerspective", "certainty", "timeRelation",
        )}
        if segment_id in segments and segments[segment_id][1] != common:
            first_shot_no, first_common = segments[segment_id]
            different_fields = [field for field in common if common[field] != first_common[field]]
            raise ValueError(
                f"画面段落 {segment_id} 的镜头 {first_shot_no} 与镜头 {shot['shotNo']} "
                f"字段 {', '.join(different_fields)} 不一致；同一段落保持相同来源与时序事实，"
                "事件短标识及入出线索按镜分别填写"
            )
        segments[segment_id] = (shot["shotNo"], common)
    return rows


def _director_plan_trim_end_punctuation(value: Any) -> str:
    return re.sub(r"[。；;，,、\s]+$", "", str(value or "").strip())


def _director_plan_shot_label(shot: dict[str, Any]) -> str:
    shot_no = _director_plan_shot_number(shot.get("shotNo"), "shotNo")
    return f"镜头 {shot_no:02d}："


def _director_plan_render_sound_event(event: dict[str, Any], *, include_kind: bool = False) -> str:
    if not isinstance(event, dict):
        return ""
    kind = str(event.get("kind") or "").strip()
    voice_type = str(event.get("voiceType") or "").strip()
    source_name = _director_plan_trim_end_punctuation(event.get("sourceName"))
    content = _director_plan_trim_end_punctuation(event.get("content"))
    expression_notes = _director_plan_trim_end_punctuation(event.get("expressionNotes"))
    timing = _director_plan_trim_end_punctuation(event.get("timing"))
    if not content:
        return ""
    if kind == "voice":
        if voice_type == "inner_thought":
            prefix = f"{source_name or '角色'}内心独白"
        elif voice_type == "self_talk":
            prefix = f"{source_name or '角色'}自言自语"
        elif voice_type == "crowd":
            prefix = source_name or "多名人群声"
        else:
            prefix = source_name or "角色对白"
        rendered = f"{prefix}：“{content}”"
    else:
        rendered = content
    details = "，".join(item for item in (expression_notes, timing) if item)
    if details:
        rendered = f"{rendered}（{details}）"
    if include_kind:
        label = " ".join(item for item in (kind, voice_type) if item)
        if label:
            return f"{label}：{rendered}"
    return rendered


def _director_plan_text_from_shots(shots: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for shot in shots:
        parts = [
            f"分镜画面：{shot['storyboardFrame']}",
            f"视频执行：{shot['videoExecution']}",
        ]
        if shot.get("visualPurpose"):
            parts.insert(0, f"镜头目的：{shot['visualPurpose']}")
        if shot.get("endState"):
            parts.append(f"结束状态：{shot['endState']}")
        if shot.get("presentation"):
            presentation = shot["presentation"]
            parts.append("画面段落：" + "；".join(filter(None, (
                "、".join(presentation["modes"]),
                presentation["sourcePerspective"], presentation["certainty"],
                presentation["timeRelation"], presentation.get("entryCue"),
                presentation.get("exitCue"),
            ))))
            event_label = presentation.get("eventLabel")
            if isinstance(event_label, dict):
                parts.append(f"事件短标识：{event_label['content']}（起点可见：{bool(event_label['visibleAtStart'])}）")
        if isinstance(shot.get("assets"), dict):
            labels = {"characters": "角色", "creatures": "生物", "scenes": "场景", "props": "道具"}
            assets = "；".join(
                f"{labels[kind]}：{'、'.join(shot['assets'].get(kind) or []) or '无'}"
                for kind in _DIRECTOR_PLAN_ASSET_KINDS
            )
            parts.append(f"涉及资产：{assets}")
        events = shot.get("soundEvents") if isinstance(shot.get("soundEvents"), list) else []
        for event in shot.get("screenTextEvents") or []:
            parts.append("画面文字：" + "；".join(filter(None, (
                event.get("medium"), event.get("authorLabel"), event.get("content"), event.get("timing"),
            ))))
        for event in shot.get("editorialTextEvents") or []:
            parts.append("编辑层文字：" + "；".join(filter(None, (
                event["content"], event["sourceType"], event["sourceQuote"],
                event["anchor"], event["placement"], event["styleIntent"],
                event["deliveryPath"],
            ))))
        for event in events:
            rendered = _director_plan_render_sound_event(event, include_kind=True)
            if rendered:
                parts.append(f"声音事件：{rendered}")
        rows.append(_director_plan_shot_label(shot) + "；".join(parts))
    return "\n".join(rows)


def _director_plan_normalized_speaker_roster(
    value: Any,
    *,
    shots: list[dict[str, Any]] | None = None,
    speaker_asset_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    raw_speakers = [] if value is None else value
    if not isinstance(raw_speakers, list):
        raise ValueError("分镜脚本的临时说话者名单必须是数组")
    speakers: list[dict[str, str]] = []
    speaker_ids: set[str] = set()
    for index, raw in enumerate(raw_speakers, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"临时说话者名单第 {index} 位说话者不是有效对象")
        for key, label in (("speakerId", "内部标识"), ("displayName", "名称")):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise ValueError(f"临时说话者名单第 {index} 位说话者缺少{label}，请补全后重新生成")
        if raw.get("identityDescription") is not None and not isinstance(raw["identityDescription"], str):
            raise ValueError(f"临时说话者名单第 {index} 位说话者的身份描述必须是文本")
        speaker_id = _director_plan_inline_text(raw.get("speakerId"))
        display_name = _director_plan_inline_text(raw.get("displayName"))
        identity_description = _director_plan_inline_text(raw.get("identityDescription"))
        if speaker_id.startswith(("asset:", "project:")):
            raise ValueError(f"临时说话者名单第 {index} 位说话者不能使用已有声音身份，请在声音事件中直接引用")
        if speaker_id in speaker_ids:
            raise ValueError(f"临时说话者名单第 {index} 位说话者的内部标识重复")
        speaker_ids.add(speaker_id)
        speakers.append({
            "speakerId": speaker_id,
            "displayName": display_name,
            "identityDescription": identity_description,
        })
    for shot_index, shot in enumerate(shots or [], start=1):
        for event_index, event in enumerate(shot.get("soundEvents") or [], start=1):
            if event.get("kind") != "voice":
                continue
            speaker_id = _director_plan_inline_text(event.get("speakerId"))
            location = f"分镜脚本镜头 {shot_index:02d} 的第 {event_index} 条人声事件"
            if not speaker_id or speaker_id == "asset:":
                raise ValueError(f"{location}缺少说话者关联，请重新选择声源")
            if speaker_id.startswith("asset:") and speaker_asset_ids is not None and speaker_id[6:] not in speaker_asset_ids:
                raise ValueError(f"{location}关联的资产不存在或未关联到当前工作链：{speaker_id}")
            if not speaker_id.startswith("asset:") and speaker_id != "project:narrator" and speaker_id not in speaker_ids:
                raise ValueError(f"{location}关联的说话者不在临时说话者名单中，请重新选择声源或补全名单")
    return speakers


def speaker_roster_for_shots(
    speaker_roster: list[dict[str, Any]], shots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only temporary speakers whose voice events occur in these shots."""
    used_ids = {
        str(event.get("speakerId") or "").strip()
        for shot in shots if isinstance(shot, dict)
        for event in (shot.get("soundEvents") or []) if isinstance(event, dict)
        and event.get("kind") == "voice"
    }
    return [
        copy.deepcopy(row) for row in speaker_roster if isinstance(row, dict)
        and str(row.get("speakerId") or "").strip() in used_ids
    ]


class DirectorPlanIdentityError(ValueError):
    """Identity boundary failed; repeated generation must not hide this failure."""


def _director_plan_identity_issues(plan: dict[str, Any], speaker_asset_ids: set[str]) -> list[str]:
    """Check internal identity tokens in prose fields; spoken content is never rewritten."""
    tokens = [r"asset:[A-Za-z0-9_-]+", re.escape("project:narrator"), *(re.escape(f"asset:{key}") for key in sorted(speaker_asset_ids))]
    pattern = re.compile(r"(?:" + "|".join(tokens) + r")(?![A-Za-z0-9_-])")
    issues: list[str] = []

    def check(value: Any, path: str) -> None:
        if isinstance(value, str) and pattern.search(value):
            issues.append(path)

    def rows(value: Any) -> list:
        return value if isinstance(value, list) else []

    for index, shot in enumerate(rows(plan.get("shots"))):
        if not isinstance(shot, dict):
            continue
        for field in ("visualPurpose", "storyboardFrame", "videoExecution", "endState"):
            check(shot.get(field), f"shots[{index}].{field}")
        for event_index, event in enumerate(rows(shot.get("screenTextEvents"))):
            if isinstance(event, dict):
                for field in ("medium", "authorLabel", "timing"):
                    check(event.get(field), f"shots[{index}].screenTextEvents[{event_index}].{field}")
        for event_index, event in enumerate(rows(shot.get("soundEvents"))):
            if not isinstance(event, dict):
                continue
            for field in ("sourceName", "expressionNotes", "timing"):
                check(event.get(field), f"shots[{index}].soundEvents[{event_index}].{field}")
            if event.get("kind") != "voice":
                check(event.get("content"), f"shots[{index}].soundEvents[{event_index}].content")
    for index, speaker in enumerate(rows(plan.get("speakerRoster"))):
        if isinstance(speaker, dict):
            for field in ("displayName", "identityDescription"):
                check(speaker.get(field), f"speakerRoster[{index}].{field}")
    return issues


def _director_plan_normalized_content(
    shots: Any,
    speaker_roster: Any,
    *,
    speaker_asset_ids: set[str] | None = None,
    speaker_source_names: dict[str, str] | None = None,
    allowed_asset_ids: dict[str, set[str]] | None = None,
    allow_empty: bool = False,
) -> dict[str, Any]:
    """Keep generated, edited and restored plans on the same persisted contract."""
    # Existing voice identities sometimes arrive redundantly in the model's
    # temporary roster. Their display names can fill a missing sound label,
    # while the stable asset/project ID remains the only persisted identity.
    prepared_roster = speaker_roster
    prepared_shots = shots
    if isinstance(speaker_roster, list):
        source_names = {
            str(row.get("speakerId") or "").strip(): str(row.get("displayName") or "").strip()
            for row in speaker_roster if isinstance(row, dict)
        }
        source_names.setdefault("project:narrator", "旁白")
        source_names.update({str(key).strip(): str(value).strip()
                             for key, value in (speaker_source_names or {}).items() if str(value).strip()})
        prepared_roster = [
            row for row in speaker_roster
            if not isinstance(row, dict) or not str(row.get("speakerId") or "").strip().startswith(("asset:", "project:"))
        ]
        if isinstance(shots, list) and source_names:
            prepared_shots = copy.deepcopy(shots)
            for shot in prepared_shots:
                if not isinstance(shot, dict) or not isinstance(shot.get("soundEvents"), list):
                    continue
                for event in shot["soundEvents"]:
                    if not isinstance(event, dict) or event.get("kind") != "voice" or event.get("sourceName"):
                        continue
                    name = source_names.get(str(event.get("speakerId") or "").strip())
                    if name:
                        event["sourceName"] = name
    normalized_shots = (
        []
        if allow_empty and isinstance(prepared_shots, list) and not prepared_shots
        else _director_plan_normalized_shots(
            prepared_shots, allowed_asset_ids=allowed_asset_ids,
        )
    )
    normalized_roster = _director_plan_normalized_speaker_roster(
        prepared_roster, shots=normalized_shots, speaker_asset_ids=speaker_asset_ids,
    )
    identities = speaker_asset_ids if speaker_asset_ids is not None else {
        event["speakerId"][6:] for shot in normalized_shots for event in shot.get("soundEvents") or []
        if str(event.get("speakerId") or "").startswith("asset:")
    }
    issues = _director_plan_identity_issues({"shots": normalized_shots, "speakerRoster": normalized_roster}, identities)
    if issues:
        raise DirectorPlanIdentityError("分镜脚本正文包含内部声音身份标识：" + "、".join(issues))
    return {
        "directorPlan": _director_plan_text_from_shots(normalized_shots),
        "directorPlanShots": normalized_shots,
        "speakerRoster": normalized_roster,
    }


def _director_plan_bound_speaker_asset_ids(project_id: str, input_snapshot: dict[str, Any]) -> set[str]:
    from .prompt_asset_context import resolve_prompt_assets

    return {
        identity for identity, asset in resolve_prompt_assets(project_id, input_snapshot).items()
        if asset["exists"] and asset["assetType"] in {"characters", "creatures"}
    }


def director_plan_bound_speaker_asset_ids_for_work_chain(
    project_id: str, workflow: dict[str, Any], episode_id: str, director_id: str,
) -> set[str]:
    """Include assets attached to storyboard units whose shots belong to this director."""
    from .workflow_input_resolution import _resolve_workflow_node_inputs_from_workflow

    nodes = [node for node in workflow.get("nodes", []) if isinstance(node, dict)]
    director = next((node for node in nodes if str(node.get("id") or "") == director_id), None)
    director_data = director.get("data") if isinstance(director, dict) else {}
    chain_id = str((director or {}).get("workChainId") or (director_data or {}).get("workChainId") or "")
    source_ids = [director_id]
    if chain_id:
        source_ids.extend(
            str(node.get("id") or "") for node in nodes
            if node.get("type") == "storyboard.card"
            and isinstance(node.get("data"), dict)
            and str(node.get("workChainId") or node["data"].get("workChainId") or "") == chain_id
        )
    identities: set[str] = set()
    for node_id in source_ids:
        snapshot = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, node_id)
        identities.update(_director_plan_bound_speaker_asset_ids(project_id, snapshot))
    return identities


def director_plan_bound_asset_ids_for_work_chain(
    project_id: str, workflow: dict[str, Any], episode_id: str, director_id: str,
) -> dict[str, set[str]]:
    """Allow shot assets only when currently attached to this work chain."""
    from .prompt_asset_context import resolve_prompt_assets
    from .workflow_input_resolution import _resolve_workflow_node_inputs_from_workflow

    nodes = [node for node in workflow.get("nodes", []) if isinstance(node, dict)]
    director = next((node for node in nodes if str(node.get("id") or "") == director_id), None)
    director_data = director.get("data") if isinstance(director, dict) else {}
    chain_id = str((director or {}).get("workChainId") or (director_data or {}).get("workChainId") or "")
    source_ids = [director_id]
    if chain_id:
        source_ids.extend(
            str(node.get("id") or "") for node in nodes
            if node.get("type") == "storyboard.card"
            and isinstance(node.get("data"), dict)
            and str(node.get("workChainId") or node["data"].get("workChainId") or "") == chain_id
        )
    allowed = {kind: set() for kind in _DIRECTOR_PLAN_ASSET_KINDS}
    for node_id in source_ids:
        snapshot = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, node_id)
        for identity, asset in resolve_prompt_assets(project_id, snapshot).items():
            kind = asset["assetType"]
            if asset["exists"] and kind in allowed:
                allowed[kind].add(identity)
    return allowed


def _director_plan_bound_asset_catalog(
    project_id: str, input_snapshot: dict[str, Any],
) -> dict[str, list[dict[str, str]]]:
    from .prompt_asset_context import resolve_prompt_assets
    from .reference_read_context import ReferenceReadContext

    catalog: dict[str, list[dict[str, str]]] = {kind: [] for kind in _DIRECTOR_PLAN_ASSET_KINDS}
    read_context = ReferenceReadContext(project_id)
    for identity, asset in resolve_prompt_assets(project_id, input_snapshot, read_context=read_context).items():
        kind = asset["assetType"]
        if asset["exists"] and kind in catalog:
            row = {"id": identity, "name": asset["displayName"]}
            description = str((read_context.asset_index.get((kind, identity)) or {}).get("desc") or "").strip()
            if description:
                row["description"] = description
            catalog[kind].append(row)
    return catalog


def get_director_plan_asset_catalog(project_id: str, episode_id: str, node_id: str) -> dict[str, Any]:
    """Return the assets actually bound to one editable director or storyboard card."""
    from .canvas_store_queries import read_workflow_card_neighborhood_v4
    from .workflow_input_resolution import _resolve_workflow_node_inputs_from_workflow

    workflow = read_workflow_card_neighborhood_v4(project_id, episode_id, node_id, detail="full")
    node = next((row for row in workflow.get("nodes") or []
                 if isinstance(row, dict) and str(row.get("id") or "") == node_id), None)
    if not node or str(node.get("type") or "") not in {"director.board", "storyboard.card"}:
        raise ValueError("请选择有效的分镜脚本或分镜单元")
    inputs = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, node_id)
    return {"assetCatalog": _director_plan_bound_asset_catalog(project_id, inputs)}


# New-output schema. The normalizer above still reads older stored shot fields.
DIRECTOR_PLAN_STRUCTURED_SCHEMA: dict[str, Any] = {'name': 'workflow_director_plan',
 'description': '分镜脚本生成结果。',
 'fields': [{'name': 'speakerRoster',
             'type': 'array',
             'required': True,
             'allow_empty': True,
             'description': '只登记本段需要发声且没有已有声音身份的临时说话者；asset:<id> 和 project:narrator '
                            '不进入名单。身份描述只写原文已知事实；匿名媒介讨论中每个实际发声的不同观众各建一个临时说话者，跨镜复用同一人的 '
                            'speakerId；不得按男／女声把不同观众合并。男／女声配音安排写在 '
                            'soundEvents.expressionNotes，不冒充身份事实；没有临时说话者时返回空数组。',
             'items': {'type': 'object',
                       'fields': [{'name': 'speakerId',
                                   'type': 'string',
                                   'required': True,
                                   'description': '稳定的临时说话者 ID，跨镜头复用；不得以 asset: 或 project: 开头。'},
                                  {'name': 'displayName',
                                   'type': 'string',
                                   'required': True,
                                   'description': '可区分的说话者名称、称谓或身份名称；在本段保持一致。'},
                                  {'name': 'identityDescription',
                                   'type': 'string',
                                   'required': False,
                                   'description': '仅填写原文明确的身份事实，如身份、关系、已知年龄或性别；没有补充事实时留空。禁止推测身份或设计音色、语气、语速。'}]}},
            {'name': 'speechBudgetNote',
             'type': 'string',
             'required': False,
             'description': '仅记录已如实拆镜和计时后仍需制作注意的声画风险；不可把说不完的台词留给后续压缩。'},
            {'name': 'shots',
             'type': 'array',
             'required': True,
             'description': '按剧情顺序排列的镜头。',
             'items': {'type': 'object',
                       'fields': [{'name': 'shotNo',
                                   'type': 'number',
                                   'required': True,
                                   'description': '镜头编号，从 1 开始按时间顺序连续递增。'},
                                  {'name': 'visualPurpose',
                                   'type': 'string',
                                   'required': True,
                                   'description': '本镜头独立的视觉目的或关键状态变化；不能只写台词主题。'},
                                  {'name': 'durationSec',
                                   'type': 'number',
                                   'required': True,
                                   'description': '正式镜长：由正常镜长在保存前按项目镜头节奏换算；不按视频模型档位填空。'},
                                  {'name': 'normalDurationSec',
                                   'type': 'number',
                                   'required': False,
                                   'description': '智能体生成时的原始正常估时；手工定时后省略，不从正式镜长反推。'},
                                  {'name': 'nonOverlappingBeats',
                                   'type': 'array',
                                   'required': False,
                                   'description': '本镜不能与发声或其他独立动作同步、且有最低实际用时的动作；各项秒数在正式镜长内保留。',
                                   'items': {'type': 'object',
                                             'fields': [{'name': 'description', 'type': 'string', 'required': True},
                                                        {'name': 'durationSec', 'type': 'number', 'required': True}]}},
                                  {'name': 'groupBreakBefore',
                                   'type': 'boolean',
                                   'required': False,
                                   'description': '只有本镜与前镜无法在同一段视频中连贯执行时填 true；普通切镜或特殊叙事入出本身不要求另起组。'},
                                  {'name': 'entryBoundaryKind',
                                   'type': 'string',
                                   'required': True,
                                   'enum': ['direct_continuation', 'spatial_cut', 'ordinary_cut', 'time_space_jump'],
                                   'description': '本镜相对前一镜的画面关系：direct_continuation 无切镜直续；spatial_cut 同空间换机位；ordinary_cut 普通切镜；time_space_jump 明确时空跳转。首镜也应依据上一工作链正式末镜判断；与分组硬边界无关。'},
                                  {'name': 'audioBoundaryKind',
                                   'type': 'string',
                                   'required': True,
                                   'enum': ['continuous_ambience', 'dialogue_overlap', 'hard_cut', 'intentional_silence'],
                                   'description': '本镜入口的声音交接：continuous_ambience 环境声延续；dialogue_overlap 有意跨画切口的对白；hard_cut 声画同时切换；intentional_silence 有意静默。不得凭此新增对白。'},
                                  {'name': 'storyboardFrame',
                                   'type': 'string',
                                   'required': True,
                                   'description': '执行前起始状态的静态单帧：景别、机位、构图、主体和空间关系、姿态表情、输入中已有的关键道具及信息落点。不要补写输入没有的物件、数量或动作结果，也不要写渐变、扩散、扫光等动作的最终结果；不写声音、运镜或过程。'},
                                  {'name': 'videoExecution',
                                   'type': 'string',
                                   'required': True,
                                   'description': '从静态起点开始的镜头运动和变化：主要运镜或固定镜头、输入事实允许的人物/道具动作、页面或光影变化及节奏；不得补写新物件或违背明确台词/命令，不要重复静态画面。'},
                                  {'name': 'endState',
                                   'type': 'string',
                                   'required': True,
                                   'description': '本镜结束时可观察的人物、道具、场景状态，供后续镜头衔接。'},
                                  {'name': 'assets',
                                   'type': 'object',
                                   'required': True,
                                   'description': '本镜实际出现、发声或使用的已绑定资产 ID；临时群众发声只进入 speakerRoster。',
                                   'fields': [{'name': 'characters',
                                               'type': 'array',
                                               'required': True,
                                               'allow_empty': True,
                                               'items': {'type': 'string'}},
                                              {'name': 'creatures',
                                               'type': 'array',
                                               'required': True,
                                               'allow_empty': True,
                                               'items': {'type': 'string'}},
                                              {'name': 'scenes',
                                               'type': 'array',
                                               'required': True,
                                               'allow_empty': True,
                                               'items': {'type': 'string'}},
                                              {'name': 'props',
                                               'type': 'array',
                                               'required': True,
                                               'allow_empty': True,
                                               'items': {'type': 'string'}}]},
                                  {'name': 'visibleAssets',
                                   'type': 'object',
                                   'required': True,
                                   'description': '本镜起始或镜内实际能被观众看见并辨认的资产 ID。必须是 assets '
                                                  '的子集；只发声、画外使用或仅在原文提及的资产不填。首次可见登场由程序按正式镜序计算，模型不得猜测首次状态。',
                                   'fields': [{'name': 'characters',
                                               'type': 'array',
                                               'required': True,
                                               'allow_empty': True,
                                               'items': {'type': 'string'}},
                                              {'name': 'creatures',
                                               'type': 'array',
                                               'required': True,
                                               'allow_empty': True,
                                               'items': {'type': 'string'}},
                                              {'name': 'scenes',
                                               'type': 'array',
                                               'required': True,
                                               'allow_empty': True,
                                               'items': {'type': 'string'}},
                                              {'name': 'props',
                                               'type': 'array',
                                               'required': True,
                                               'allow_empty': True,
                                               'items': {'type': 'string'}}]},
                                  {'name': 'startVisibleAssets',
                                   'type': 'object',
                                   'required': False,
                                   'description': '起始画格已经可见的资产 ID，必须是 visibleAssets 子集；镜内稍后入画的资产只写 '
                                                  'visibleAssets。',
                                   'fields': [{'name': 'characters',
                                               'type': 'array',
                                               'required': True,
                                               'allow_empty': True,
                                               'items': {'type': 'string'}},
                                              {'name': 'creatures',
                                               'type': 'array',
                                               'required': True,
                                               'allow_empty': True,
                                               'items': {'type': 'string'}},
                                              {'name': 'scenes',
                                               'type': 'array',
                                               'required': True,
                                               'allow_empty': True,
                                               'items': {'type': 'string'}},
                                              {'name': 'props',
                                               'type': 'array',
                                               'required': True,
                                               'allow_empty': True,
                                               'items': {'type': 'string'}}]},
                                  {'name': 'screenTextEvents',
                                   'type': 'array',
                                   'required': True,
                                   'allow_empty': True,
                                   'description': '仅登记正式剧本明确以字面为剧情线索的场景载体文字及其来源，供结构化追溯；一般群聊、弹幕、系统界面的文字信息流写在起始画面和执行中，不逐条列此处，不按读屏时长切镜，也不要求图片或视频把字逐字绘对。推动剧情的媒介讨论若已在剧本指定人声，按原说话者和顺序进入 '
                                                  'soundEvents，并与画面信息变化同镜同步；没有字面线索时返回空数组。',
                                   'items': {'type': 'object',
                                             'fields': [{'name': 'content',
                                                         'type': 'string',
                                                         'required': True,
                                                         'description': '观众应看到的原文文字。'},
                                                        {'name': 'medium',
                                                         'type': 'string',
                                                         'required': True,
                                                         'description': '文字出现的载体，如弹幕、论坛帖子、手机消息或标牌。'},
                                                        {'name': 'authorLabel',
                                                         'type': 'string',
                                                         'required': False,
                                                         'description': '原文已知且需要展示的发帖人、昵称或署名；未知则留空。署名不代表有人发声，也不能据昵称推测人物性别。'},
                                                        {'name': 'timing',
                                                         'type': 'string',
                                                         'required': False,
                                                         'description': '文字在本镜出现的相对位置和阅读顺序；关键内容应有可读停留。'},
                                                        {'name': 'visibleAtStart',
                                                         'type': 'boolean',
                                                         'required': False,
                                                         'description': '当前默认分镜图必须一次绘制需逐字读清的场景文字，因此新草稿填 '
                                                                        'true，并在 storyboardFrame '
                                                                        '起始状态显示；动态掠过且无需读清的消息只写 '
                                                                        'videoExecution。'}]}},
                                  {'name': 'presentation',
                                   'type': 'object',
                                   'required': False,
                                   'description': '仅特殊段落填写来源、时间、主客观与确定程度；普通现场省略。特殊段落首次填完整字段，后续连续镜头可只填相同 '
                                                  'modes 与 segmentId。',
                                   'fields': [{'name': 'segmentId',
                                               'type': 'string',
                                               'required': False,
                                               'description': '特殊段落必填；普通现场省略。'},
                                              {'name': 'modes',
                                               'type': 'array',
                                               'required': True,
                                               'items': {'type': 'string',
                                                         'enum': ['character_account',
                                                                  'chronological_compression',
                                                                  'dream',
                                                                  'imagination',
                                                                  'inner',
                                                                  'mediated',
                                                                  'memory',
                                                                  'normal',
                                                                  'parallel',
                                                                  'perceptual_distortion',
                                                                  'process_montage',
                                                                  'reported',
                                                                  'romantic_ambiguity',
                                                                  'time_jump']}},
                                              {'name': 'sourcePerspective',
                                               'type': 'string',
                                               'required': False,
                                               'description': '现实或主观来源及其知识归属。'},
                                              {'name': 'certainty',
                                               'type': 'string',
                                               'required': False,
                                               'description': '已证实、角色记忆、想象、未证实转述等事实确定程度。'},
                                              {'name': 'timeRelation',
                                               'type': 'string',
                                               'required': False,
                                               'description': '相对当前现场的时间方向或并行关系。'},
                                              {'name': 'entryCue', 'type': 'string', 'required': False},
                                              {'name': 'exitCue', 'type': 'string', 'required': False},
                                              {'name': 'eventLabel',
                                               'type': 'object',
                                               'required': False,
                                               'description': '仅特殊段落确需有据的画内事件短标识时填写；不是通用编辑层字卡。',
                                               'fields': [{'name': 'content',
                                                           'type': 'string',
                                                           'required': True},
                                                          {'name': 'sourceQuote',
                                                           'type': 'string',
                                                           'required': True,
                                                           'description': '可从原文或正式剧本核对的短引文，仅用于预检，不发送图片模型。'},
                                                          {'name': 'visibleAtStart',
                                                           'type': 'boolean',
                                                           'required': True}]}]},
                                  {'name': 'soundEvents',
                                   'type': 'array',
                                   'required': True,
                                   'description': '本镜实际需要发出的语言与声音，供后续组合和配音；每个人声事件对应实际发声者，无声音返回空数组。群聊、直播弹幕等媒介讨论由剧本选定多声部发言后进入人声，与同镜屏幕信息流和人物反应同步；画面文字不要求逐字读清。系统消息只有剧本指定播报或角色转述时才发声。',
                                   'items': {'type': 'object',
                                             'fields': [{'name': 'kind',
                                                         'type': 'string',
                                                         'required': True,
                                                         'enum': ['voice', 'ambient', 'sfx', 'music'],
                                                         'description': 'voice 为明确语言，ambient 为持续氛围，sfx '
                                                                        '为具体响动或无明确文字的人声反应，music 为配乐。'},
                                                        {'name': 'voiceType',
                                                         'type': 'string',
                                                         'required': False,
                                                         'enum': ['dialogue',
                                                                  'self_talk',
                                                                  'inner_thought',
                                                                  'crowd',
                                                                  'narration'],
                                                         'description': '具体人声的发声方式：对白、自言自语、内心、群众发言或画外叙述；非人声留空。'},
                                                        {'name': 'speakerId',
                                                         'type': 'string',
                                                         'required': False,
                                                         'description': '具体人声的稳定身份：已有角色、生物用输入的 '
                                                                        'asset:<id>，项目旁白用 '
                                                                        'project:narrator，临时角色用 '
                                                                        'speakerRoster 的 '
                                                                        'speakerId；仅有名称不自行拼造资产标识。叙述方式不改变声源身份，角色承担画外叙述仍用其原身份。非人声可省略。'},
                                                        {'name': 'sourceName',
                                                         'type': 'string',
                                                         'required': False,
                                                         'description': 'kind=voice 时必填可区分的具体发言者名称，与 '
                                                                        'speakerId '
                                                                        '同时提供；原文明确齐声合说时保留群体声源。非人声可省略。'},
                                                        {'name': 'content',
                                                         'type': 'string',
                                                         'required': True,
                                                         'description': '本镜关联的台词、发言、环境声、音效或音乐短句。人声保留原文，可按顺序切成连续短段；非语言写可听状态，不写绝对时间码。'},
                                                        {'name': 'expressionNotes',
                                                         'type': 'string',
                                                         'required': False,
                                                         'description': '人声按项目镜头节奏倍速表达，并保留原文已明确的音色、语气、相对快慢与停顿、情绪、声场及传播媒介；已有声音身份不得重设。剧本明确发声的匿名媒介人物可按制作要求标注可辨语气，不将配音选择当作原文身份事实。非人声无表达要求时可留空。'},
                                                        {'name': 'timing',
                                                         'type': 'string',
                                                         'required': False,
                                                         'description': '声音与本镜可见动作同步的触发点、相对位置和接续方式；对白开始不得先留无意义空画面。'},
                                                        {'name': 'durationSec',
                                                         'type': 'number',
                                                         'required': False,
                                                         'description': '仅供非人声事件；人声由后端按镜头节奏倍率估时。'},
                                                        {'name': 'deliveryOverride',
                                                         'type': 'object',
                                                         'required': False,
                                                         'description': '仅当原文或本轮用户指令明确要求拖长发声时用于人声；普通对白不填。',
                                                         'fields': [{'name': 'durationSec',
                                                                     'type': 'number',
                                                                     'required': True,
                                                                     'description': '有来源依据的实际发声秒数，须长于当前镜头节奏的后端基准。'},
                                                                    {'name': 'evidenceSource',
                                                                     'type': 'string',
                                                                     'required': True,
                                                                     'description': 'source_text 或 '
                                                                                    'user_instruction。'},
                                                                    {'name': 'evidenceText',
                                                                     'type': 'string',
                                                                     'required': True,
                                                                     'description': '逐字摘录慢说要求；只引用对白原句不算依据。'},
                                                                    {'name': 'reason',
                                                                     'type': 'string',
                                                                     'required': True,
                                                                     'description': '本句为何需要偏离当前节奏。'}]}]}}]}}]}


def _director_plan_first_duration_seconds(*sources: Any) -> float | None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in (
            "durationSeconds",
            "targetDurationSeconds",
            "target_duration_seconds",
        ):
            number = _workflow_timing_number(source.get(key))
            if number and number > 0:
                return number
    return None


def _director_plan_target_video_task_data(
    workflow: dict[str, Any],
    director_node_id: str,
) -> dict[str, Any]:
    for video_node_id in _work_chain_video_task_ids_for_director(workflow, director_node_id):
        candidate = _workflow_node(workflow, video_node_id)
        if not candidate:
            continue
        data = candidate.get("data") if isinstance(candidate.get("data"), dict) else {}
        return copy.deepcopy(data)
    return {}


def _director_plan_video_model_prompt_text(
    target_model: dict[str, Any],
    _current_duration_seconds: float | None,
) -> str:
    allowed_durations = _video_task_card_allowed_duration_values(
        target_model.get("allowedDurations") or target_model.get("durations")
    )
    rows: list[str] = []
    if allowed_durations:
        rows.append("单个视频任务可用时长：" + _video_task_card_allowed_duration_label(allowed_durations))
    else:
        rows.append("当前模型未提供固定单段时长；请根据剧情节奏估算各镜自然时长。")
    return "\n".join(rows)


def _director_plan_target_duration_choices_text(text: str) -> str:
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "单个视频任务可用时长" in line or "当前可用时长" in line:
            value = line.partition("：")[2] or line.partition(":")[2]
            return value.strip().rstrip("。；;")
        if "可选总参考时长为" in line:
            value = line.partition("可选总参考时长为")[2].lstrip("：:").strip()
            return value.strip().rstrip("。；;")
    return ""


def _director_plan_target_timing_prompt_text(text: str) -> str:
    choices_text = _director_plan_target_duration_choices_text(text)
    if choices_text:
        return (
            f"单个生成视频的可用时长为：{choices_text}。这不是整个剧情片段或分镜脚本的时长上限。\n"
            "先按完整行动和台词划分必要镜头：连续机位中的动作与台词保持同镜，只有视角变化承担新的叙事信息时才切镜，不按句子或动作数量机械拆镜。"
            "逐镜估算正常语速的完整台词、不可与台词同时完成的动作及表演停顿所需时长；总参考时长按各镜自然时长合计。"
            "单镜超出单次生成容量时，在自然的行动或对白节点安排可衔接的镜头，不压缩台词、不用无意义空镜占时长。"
        )
    return (
        "镜头数量由叙事需要决定。连续机位中的动作与台词保持同镜，只有视角变化承担新的叙事信息时才切镜。"
        "逐镜估算正常语速的完整台词、不可同时完成的动作及表演停顿所需时长，总参考时长按各镜自然时长合计。"
    )


def _director_plan_normalized_duration_seconds(
    value: Any,
) -> int | float:
    candidate = _workflow_timing_number(value)
    if not candidate or candidate <= 0:
        raise ValueError("模型返回的剧情片段参考总时长不可用")
    # This is the duration of the whole story segment, not one model invocation.
    return _workflow_clean_seconds(float(candidate))


def _director_plan_reference_duration_sum(shots: list[dict[str, Any]]) -> int | float | None:
    total_centiseconds = 0
    for shot in shots:
        if not isinstance(shot, dict):
            return None
        duration = _director_plan_optional_sound_duration(shot.get("durationSec"))
        if duration is None:
            return None
        total_centiseconds += int(Decimal(str(duration)) * 100)
    if total_centiseconds <= 0:
        return None
    return (total_centiseconds // 100 if total_centiseconds % 100 == 0
            else total_centiseconds / 100)
