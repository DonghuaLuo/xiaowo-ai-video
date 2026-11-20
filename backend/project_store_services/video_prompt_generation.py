"""视频提示词声音身份的领域校验。"""
from __future__ import annotations
from typing import Any


def unique_video_speaker_ids(speaker_ids: list[str], names: dict[str, str], *,
                             preferred_ids: set[str] | None = None) -> list[str]:
    """Keep one identity per explicit display name, preferring task-owned settings."""
    preferred_ids = preferred_ids or set()
    ordered = list(dict.fromkeys(key.strip() for key in speaker_ids))
    chosen: dict[str, str] = {}
    for key in ordered:
        name = str(names.get(key) or key).strip()
        previous = chosen.get(name)
        if previous is None or (key in preferred_ids and previous not in preferred_ids):
            chosen[name] = key
    return [key for key in ordered if chosen[str(names.get(key) or key).strip()] == key]


def deduplicate_video_prompt_voices(speaker_ids: list[str], design: dict[str, Any], names: dict[str, str], *,
                                    preferred_ids: set[str] | None = None) -> tuple[set[str], dict[str, Any]]:
    labels = {**names, **{row["speakerId"]: row["displayName"] for row in design["speakers"]}}
    used = set(unique_video_speaker_ids(speaker_ids, labels, preferred_ids=preferred_ids))
    return used, {"speakers": [row for row in design["speakers"] if row["speakerId"] in used]}


def deduplicate_video_voice_prompt(sound_prompt: str, names: list[str]) -> str:
    prefixes = sorted({f"- {name.strip()}：" for name in names}, key=len, reverse=True)
    seen: set[str] = set()
    lines = []
    for line in sound_prompt.split("\n"):
        prefix = next((value for value in prefixes if line.strip().startswith(value)), None)
        if prefix is not None:
            if prefix in seen:
                continue
            seen.add(prefix)
        lines.append(line)
    return "\n".join(lines)


def normalize_video_prompt_voices(
    result: dict[str, Any], known_speakers: dict[str, str], *,
    expected_speaker_ids: set[str] | None = None,
    fallback_asset_speakers: dict[str, str] | None = None,
) -> tuple[set[str], dict[str, Any]]:
    fallback_asset_speakers = fallback_asset_speakers or {}
    used = result.get("usedSpeakerIds")
    if not isinstance(used, list) or any(not isinstance(value, str) or not value.strip() for value in used):
        raise ValueError("视频提示词缺少有效的声音身份列表")
    used_ids = {value.strip() for value in used}
    if expected_speaker_ids is not None and used_ids != expected_speaker_ids:
        raise ValueError("视频提示词的说话者身份与输入声音事件不一致")
    design = result.get("voiceDesign") or {"speakers": []}
    if not isinstance(design, dict):
        raise ValueError("视频提示词缺少有效的声音设计")
    if set(design) - {"speakers"}:
        raise ValueError("视频提示词的声音设计只能包含 speakers")
    if design.get("speakers") in (None, ""):
        design = {"speakers": []}
    if not isinstance(design.get("speakers"), list):
        raise ValueError("视频提示词缺少有效的声音设计")
    speakers: list[dict[str, str]] = []
    speaker_ids: set[str] = set()
    for row in design["speakers"]:
        if not isinstance(row, dict) or not isinstance(row.get("speakerId"), str) or not row["speakerId"].strip():
            # A malformed optional voice row cannot replace a bound identity.
            # Unbound speakers are still caught by unknown_ids below.
            continue
        speaker_id = row["speakerId"].strip()
        # A local voice remains authoritative. Only a bound asset without one
        # may receive a temporary voice for this generated prompt.
        if speaker_id in known_speakers:
            continue
        if speaker_id in fallback_asset_speakers:
            voice_style = row.get("voiceStyle")
            if speaker_id not in used_ids or not isinstance(voice_style, str) or not voice_style.strip():
                continue
            if speaker_id in speaker_ids:
                raise ValueError("视频提示词的声音身份重复")
            speaker_ids.add(speaker_id)
            speakers.append({
                "speakerId": speaker_id,
                "displayName": fallback_asset_speakers[speaker_id],
                "voiceStyle": voice_style.strip(),
            })
            continue
        if any(
            not isinstance(row.get(key), str) or not row[key].strip()
            for key in ("displayName", "voiceStyle")
        ):
            raise ValueError("视频提示词的说话者缺少身份、名称或声线")
        if speaker_id in speaker_ids:
            raise ValueError("视频提示词的声音身份重复")
        if speaker_id not in used_ids:
            raise ValueError("视频提示词为未发声的说话者设计了声线")
        if speaker_id.startswith("asset:") or (speaker_id.startswith("project:") and speaker_id != "project:narrator"):
            raise ValueError("视频提示词引用了未关联的已有声音：" + speaker_id)
        speaker_ids.add(speaker_id)
        speakers.append({
            "speakerId": speaker_id,
            "displayName": "旁白" if speaker_id == "project:narrator" else row["displayName"].strip(),
            "voiceStyle": row["voiceStyle"].strip(),
        })
    unknown_ids = used_ids - known_speakers.keys() - fallback_asset_speakers.keys() - speaker_ids
    if unknown_ids:
        raise ValueError("视频提示词引用的说话者缺少声音设计：" + "、".join(sorted(unknown_ids)))
    return used_ids, {"speakers": speakers}
