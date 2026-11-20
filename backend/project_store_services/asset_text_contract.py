# -*- coding: utf-8 -*-
"""资产文本字段归一化、合并、完整性和分组元数据契约。"""
from __future__ import annotations

from .catalogs import ACCENTS
from .reference_utils import next_short_asset_id as _shared_next_short_asset_id
from .source_coverage import _asset_range_id_tokens
from .store_core import _asset_is_offline
from typing import Any
import copy
import re


AGENT_TEXT_RESULT_SOURCES = {"agent", "agent-model", "agent-sdk"}


def _agent_text_row_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize_character_voice_style(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" ，,；;。.")


def _agent_text_asset_match_index(rows: list[dict[str, Any]], row: dict[str, Any]) -> int:
    asset_id = _agent_text_row_text(row, "assetId", "asset_id", "id")
    if asset_id:
        for index, item in enumerate(rows):
            if _asset_is_offline(item):
                continue
            if str(item.get("id") or "") == asset_id:
                return index
    return -1


def _agent_text_asset_summary(row: dict[str, Any], previous: dict[str, Any]) -> str:
    desc = (
        _agent_text_row_text(row, "desc", "description", "summary")
        or str(previous.get("desc") or "").strip()
    )
    return desc


def _agent_text_compact_contains(base: str, candidate: str) -> bool:
    base_compact = re.sub(r"\s+", "", str(base or ""))
    candidate_compact = re.sub(r"\s+", "", str(candidate or ""))
    return bool(base_compact and candidate_compact and base_compact in candidate_compact)


def _merge_agent_asset_text(
    existing: Any,
    incoming: Any,
    *,
    replace_existing: bool = False,
) -> str:
    existing_text = str(existing or "").strip()
    incoming_text = str(incoming or "").strip()
    if replace_existing:
        return incoming_text
    if not existing_text:
        return incoming_text
    if not incoming_text:
        return existing_text
    if _agent_text_compact_contains(existing_text, incoming_text):
        return incoming_text
    if _agent_text_compact_contains(incoming_text, existing_text):
        return existing_text
    return f"{existing_text}\n{incoming_text}"


def _payload_bool(payload: dict[str, Any], *keys: str) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
    return False


def _asset_range_ids_from_row(row: dict[str, Any]) -> list[str]:
    if not isinstance(row, dict):
        return []
    return _asset_range_id_tokens(
        row.get("assetRangeIds"),
        row.get("asset_range_ids"),
        row.get("assetRangeId"),
        row.get("asset_range_id"),
    )


def _drop_incoming_asset_grouping_metadata(row: dict[str, Any]) -> dict[str, Any]:
    cleaned = copy.deepcopy(row)
    for key in (
        "assetRangeId",
        "asset_range_id",
        "assetRangeIds",
        "asset_range_ids",
        "sourceRefs",
        "source_refs",
    ):
        cleaned.pop(key, None)
    return cleaned


def _agent_text_asset_design_prompt(asset_type: str, item: dict[str, Any]) -> str:
    from .assets import _asset_design_prompt_from_asset
    from .assets import _default_asset_design_prompt
    return _asset_design_prompt_from_asset(item) or _default_asset_design_prompt(asset_type, item)


def _merge_agent_asset_source_refs(*values: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for value in values:
        rows = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            start_value = row.get("absoluteStart")
            if start_value is None:
                start_value = row.get("startOffset")
            end_value = row.get("absoluteEnd")
            if end_value is None:
                end_value = row.get("endOffset")
            key = (
                str(row.get("sourceId") or row.get("source_id") or "").strip(),
                str(start_value if start_value is not None else "").strip(),
                str(end_value if end_value is not None else "").strip(),
            )
            if not key[0] or key in seen:
                continue
            seen.add(key)
            result.append(copy.deepcopy(row))
    return result


def _normalize_agent_text_asset_row(
    asset_type: str,
    row: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
    index: int = 0,
    merge_existing_text: bool = False,
    replace_existing: bool = False,
    used_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    from .assets import _asset_design_prompt_from_asset
    if not isinstance(row, dict):
        return None
    previous = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    incoming_design_prompt = _asset_design_prompt_from_asset(row)
    previous_design_prompt = _asset_design_prompt_from_asset(previous)
    name = _agent_text_row_text(row, "name", "title") or str(previous.get("name") or "").strip()
    if not name:
        return None
    incoming_desc = _agent_text_row_text(row, "desc", "description", "summary")
    desc = (
        _merge_agent_asset_text(
            previous.get("desc"),
            incoming_desc,
            replace_existing=replace_existing,
        )
        if merge_existing_text and incoming_desc
        else _agent_text_asset_summary(row, previous)
    )
    tag = _agent_text_row_text(row, "tag", "category") or str(previous.get("tag") or "").strip()
    previous_id = str(previous.get("id") or "").strip()
    if previous_id:
        asset_id = previous_id
    else:
        asset_id = _shared_next_short_asset_id(asset_type, used_ids or [])
    if used_ids is not None:
        used_ids.add(asset_id)
    item = {
        **previous,
        "id": asset_id,
        "name": name,
        "desc": desc,
        "accent": row.get("accent") or previous.get("accent") or ACCENTS[index % len(ACCENTS)],
        "source": "agent-sdk",
    }
    if tag:
        item["tag"] = tag
    for legacy_key in (
        "prompts",
        "prompt",
        "assetImagePrompt",
        "asset_image_prompt",
        "assetVisualPrompt",
        "asset_visual_prompt",
        "designPrompt",
        "design_prompt",
        "imagePrompt",
        "image_prompt",
        "visualPrompt",
        "visual_prompt",
        "visualDescription",
        "visual_description",
        "generationPrompt",
        "generation_prompt",
        "visualSpec",
        "continuity",
        "continuityRules",
        "generation",
        "generationConfig",
        "locationType",
        "timeOfDay",
        "lighting",
        "layout",
        "mood",
        "anchorProps",
        "cameraNotes",
        "storyFunction",
        "owner",
        "stateChanges",
        "closeupPrompt",
        "stateTag",
        "state_tag",
        "stateTags",
        "state_tags",
    ):
        item.pop(legacy_key, None)
    structured_keys = (
        "aliases",
        "importance",
        "assetRangeId",
        "assetRangeIds",
        "relations",
        "referenceMediaIds",
        "designRationale",
        "canSpeak",
        "sceneReferenceRole",
    )
    snake_aliases = {
        "asset_range_id": "assetRangeId",
        "asset_range_ids": "assetRangeIds",
        "reference_media_ids": "referenceMediaIds",
        "design_rationale": "designRationale",
        "can_speak": "canSpeak",
        "scene_reference_role": "sceneReferenceRole",
    }
    for key in structured_keys:
        if key in row:
            item[key] = copy.deepcopy(row[key])
    for source_key, target_key in snake_aliases.items():
        if source_key in row and target_key not in row:
            item[target_key] = copy.deepcopy(row[source_key])
    previous_range_id = str(
        previous.get("assetRangeId") or previous.get("asset_range_id") or ""
    ).strip()
    incoming_range_id = str(
        row.get("assetRangeId") or row.get("asset_range_id") or ""
    ).strip()
    incoming_range_ids = _asset_range_id_tokens(
        row.get("assetRangeIds"),
        row.get("asset_range_ids"),
        incoming_range_id,
    )
    range_ids = _asset_range_id_tokens(
        previous.get("assetRangeIds"),
        previous.get("asset_range_ids"),
        previous_range_id,
        row.get("assetRangeIds"),
        row.get("asset_range_ids"),
        incoming_range_id,
    )
    if range_ids:
        item["assetRangeIds"] = range_ids
        item["assetRangeId"] = incoming_range_id or (
            incoming_range_ids[-1] if incoming_range_ids else previous_range_id or range_ids[-1]
        )
    source_refs = _merge_agent_asset_source_refs(
        previous.get("sourceRefs") or previous.get("source_refs"),
        row.get("sourceRefs") or row.get("source_refs"),
    )
    if source_refs:
        item["sourceRefs"] = source_refs
    incoming_voice_style = _normalize_character_voice_style(
        _agent_text_row_text(row, "voiceStyle", "voice_style")
    )
    previous_voice_style = str(previous.get("voiceStyle") or "").strip()
    voice_style = (
        _merge_agent_asset_text(
            previous_voice_style,
            incoming_voice_style,
            replace_existing=replace_existing,
        )
        if merge_existing_text and incoming_voice_style
        else incoming_voice_style
    )
    if asset_type == "characters":
        item["voiceStyle"] = voice_style or previous_voice_style
    elif asset_type == "creatures":
        can_speak = bool(voice_style or previous_voice_style)
        item["canSpeak"] = can_speak
        if can_speak and (voice_style or "voiceStyle" in previous):
            item["voiceStyle"] = voice_style or previous_voice_style
        else:
            item.pop("voiceStyle", None)
    else:
        item.pop("voiceStyle", None)
        item.pop("canSpeak", None)
    if merge_existing_text and incoming_design_prompt:
        design_prompt = _merge_agent_asset_text(
            previous_design_prompt,
            incoming_design_prompt,
            replace_existing=replace_existing,
        )
    else:
        design_prompt = incoming_design_prompt or previous_design_prompt or _agent_text_asset_design_prompt(asset_type, item)
    if design_prompt:
        item["prompts"] = {"assetImagePrompt": design_prompt}
    else:
        item.pop("prompts", None)
    return item


def _design_asset_completion_issue(asset_type: str, item: dict[str, Any]) -> str:
    label = {"characters": "角色", "creatures": "生物", "scenes": "场景", "props": "道具"}.get(asset_type, asset_type)
    name = str(item.get("name") or "未命名资产").strip() or "未命名资产"
    if asset_type in {"characters", "creatures", "scenes", "props"} and not str(item.get("desc") or "").strip():
        return f"{label}资产「{name}」缺少资产描述 desc"
    return ""


def _assert_design_asset_complete(asset_type: str, item: dict[str, Any]) -> None:
    issue = _design_asset_completion_issue(asset_type, item)
    if issue:
        raise ValueError(issue)


_AGENT_TEXT_SCENE_REFERENCE_ROLE_WORK_CHAIN = "work_chain_reference"


_AGENT_TEXT_SCENE_REFERENCE_ROLE_CONTEXT_ONLY = "context_only"


def _agent_text_scene_reference_role(row: dict[str, Any]) -> str:
    if not isinstance(row, dict):
        return ""
    role = str(row.get("sceneReferenceRole") or row.get("scene_reference_role") or "").strip().lower()
    if role in {
        _AGENT_TEXT_SCENE_REFERENCE_ROLE_WORK_CHAIN,
        _AGENT_TEXT_SCENE_REFERENCE_ROLE_CONTEXT_ONLY,
    }:
        return role
    return ""


def _agent_text_scene_row_is_context_only(row: dict[str, Any]) -> bool:
    return _agent_text_scene_reference_role(row) == _AGENT_TEXT_SCENE_REFERENCE_ROLE_CONTEXT_ONLY
