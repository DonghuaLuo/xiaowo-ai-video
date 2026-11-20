# -*- coding: utf-8 -*-
"""剧情拆分结果的来源范围与字段验证。"""
from __future__ import annotations

import copy
import unicodedata
from .context_resolver import (
    context_provenance,
)
from .source_boundary_contract import _normalize_episode_boundary_title
from .source_text_store import _compact_text
from .worker_asset_context import (
    _normalize_plot_asset_hints,
)
from .worker_asset_contract import (
    _STORYBOARD_PLOT_MIN_COUNT,
)
from .worker_task_context import (
    _filter_plot_scene_asset_hints,
    _filter_plot_splitting_candidate_assets,
    _source_preview_from_refs,
)
from .worker_text import (
    _compact_source_excerpt,
)
from typing import (
    Any,
)


def _plot_source_document(output: dict[str, Any]) -> dict[str, Any]:
    value = output.get("plotSplitProposal") if isinstance(output, dict) else None
    if isinstance(value, dict):
        return value
    return output if isinstance(output, dict) else {}


def _normalize_source_ref_row(row: dict[str, Any], source_ref: dict[str, Any]) -> dict[str, Any] | None:
    source_start = int(source_ref.get("absoluteStart") or 0)
    source_end = int(source_ref.get("absoluteEnd") or 0)
    source_id = str(source_ref.get("sourceId") or source_ref.get("source_id") or "").strip()
    if source_end <= source_start:
        return None
    try:
        absolute_start = int(
            row.get("absoluteStart")
            if row.get("absoluteStart") is not None
            else row.get("startOffset")
            if row.get("startOffset") is not None
            else row.get("start")
            if row.get("start") is not None
            else -1
        )
        absolute_end = int(
            row.get("absoluteEnd")
            if row.get("absoluteEnd") is not None
            else row.get("endOffset")
            if row.get("endOffset") is not None
            else row.get("end")
            if row.get("end") is not None
            else -1
        )
    except (TypeError, ValueError):
        return None
    # Some models return local offsets. Treat small ranges inside episode length as local.
    episode_length = max(0, source_end - source_start)
    if 0 <= absolute_start < absolute_end <= episode_length and absolute_end <= source_start:
        absolute_start += source_start
        absolute_end += source_start
    if absolute_start < source_start or absolute_end > source_end or absolute_end <= absolute_start:
        return None
    ref_source_id = str(row.get("sourceId") or row.get("source_id") or source_id).strip()
    if source_id and ref_source_id and ref_source_id != source_id:
        return None
    return {
        "sourceId": source_id or ref_source_id,
        "absoluteStart": absolute_start,
        "absoluteEnd": absolute_end,
    }


def _plot_refs_from_row(row: dict[str, Any], source_ref: dict[str, Any]) -> list[dict[str, Any]]:
    refs = row.get("sourceRefs") or row.get("source_refs") or []
    if isinstance(refs, dict):
        refs = [refs]
    result: list[dict[str, Any]] = []
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, dict):
            continue
        normalized = _normalize_source_ref_row(ref, source_ref)
        if normalized:
            result.append(normalized)
    source_range = row.get("sourceRange") or row.get("source_range")
    if not result and isinstance(source_range, dict):
        normalized = _normalize_source_ref_row(source_range, source_ref)
        if normalized:
            result.append(normalized)
    return result


def _compact_text_with_index_map(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    index_map: list[int] = []
    for index, char in enumerate(str(text or "")):
        for normalized_char in unicodedata.normalize("NFKC", char).casefold():
            category = unicodedata.category(normalized_char)
            if normalized_char.isspace() or category.startswith("P") or category.startswith("Z"):
                continue
            chars.append(normalized_char)
            index_map.append(index)
    return "".join(chars), index_map


def _text_with_newline_index_map(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    index_map: list[int] = []
    source = str(text or "")
    index = 0
    while index < len(source):
        char = source[index]
        if char == "\r":
            chars.append("\n")
            index_map.append(index)
            index += 2 if index + 1 < len(source) and source[index + 1] == "\n" else 1
            continue
        chars.append(char)
        index_map.append(index)
        index += 1
    return "".join(chars), index_map


def _whitespace_fold_text_with_index_map(text: str) -> tuple[str, list[int]]:
    normalized, normalized_index_map = _text_with_newline_index_map(text)
    chars: list[str] = []
    index_map: list[int] = []
    for normalized_index, char in enumerate(normalized):
        if char.isspace():
            continue
        chars.append(char)
        index_map.append(normalized_index_map[normalized_index])
    return "".join(chars), index_map


def _find_source_fact_range_in_episode(
    row: dict[str, Any],
    *,
    episode_text: str,
    source_ref: dict[str, Any],
) -> dict[str, Any] | None:
    source_fact_text = str(row.get("sourceFactText") or row.get("source_fact_text") or "").strip()
    if not source_fact_text:
        return None
    source_start = int(source_ref.get("absoluteStart") or 0)
    source_id = str(source_ref.get("sourceId") or source_ref.get("source_id") or "").strip()
    normalized_episode, episode_index_map = _text_with_newline_index_map(episode_text)
    normalized_fact, _fact_index_map = _text_with_newline_index_map(source_fact_text)
    if not normalized_fact:
        return None
    index = normalized_episode.find(normalized_fact)
    if index < 0 or normalized_episode.find(normalized_fact, index + 1) >= 0:
        return None
    end_index = index + len(normalized_fact) - 1
    if end_index < 0 or end_index >= len(episode_index_map):
        return None
    return {
        "sourceId": source_id,
        "absoluteStart": source_start + episode_index_map[index],
        "absoluteEnd": source_start + episode_index_map[end_index] + 1,
    }


def _all_text_matches(text: str, fragment: str) -> list[int]:
    if not fragment:
        return []
    result: list[int] = []
    start = 0
    while True:
        index = text.find(fragment, start)
        if index < 0:
            break
        result.append(index)
        start = index + 1
    return result


def _find_anchor_range_in_episode(
    row: dict[str, Any],
    *,
    episode_text: str,
    source_ref: dict[str, Any],
) -> dict[str, Any] | None:
    start_anchor = str(
        row.get("sourceStartAnchor")
        or row.get("source_start_anchor")
        or row.get("startAnchor")
        or row.get("start_anchor")
        or ""
    ).strip()
    end_anchor = str(
        row.get("sourceEndAnchor")
        or row.get("source_end_anchor")
        or row.get("endAnchor")
        or row.get("end_anchor")
        or ""
    ).strip()
    if not start_anchor or not end_anchor:
        return None
    source_start = int(source_ref.get("absoluteStart") or 0)
    source_id = str(source_ref.get("sourceId") or source_ref.get("source_id") or "").strip()
    normalized_episode, episode_index_map = _text_with_newline_index_map(episode_text)
    normalized_start, _start_index_map = _text_with_newline_index_map(start_anchor)
    normalized_end, _end_index_map = _text_with_newline_index_map(end_anchor)
    if not normalized_episode or not normalized_start or not normalized_end:
        return None
    start_matches = _all_text_matches(normalized_episode, normalized_start)
    end_matches = _all_text_matches(normalized_episode, normalized_end)
    use_folded_whitespace = False
    folded_episode = ""
    folded_start = ""
    folded_end = ""
    folded_episode_index_map: list[int] = []
    if not start_matches or not end_matches:
        folded_episode, folded_episode_index_map = _whitespace_fold_text_with_index_map(episode_text)
        folded_start, _ = _whitespace_fold_text_with_index_map(start_anchor)
        folded_end, _ = _whitespace_fold_text_with_index_map(end_anchor)
        if not folded_episode or not folded_start or not folded_end:
            return None
        start_matches = _all_text_matches(folded_episode, folded_start)
        end_matches = _all_text_matches(folded_episode, folded_end)
        use_folded_whitespace = True
    if not start_matches or not end_matches:
        return None
    candidates: list[tuple[int, int]] = []
    for start_index in start_matches:
        for end_index in end_matches:
            end_last_index = end_index + len(folded_end if use_folded_whitespace else normalized_end) - 1
            if end_last_index < start_index:
                continue
            candidates.append((start_index, end_last_index))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: (pair[1] - pair[0], pair[0]))
    best_start, best_end = candidates[0]
    if len(candidates) > 1:
        return None
    if use_folded_whitespace:
        if best_end < 0 or best_end >= len(folded_episode_index_map):
            return None
        return {
            "sourceId": source_id,
            "absoluteStart": source_start + folded_episode_index_map[best_start],
            "absoluteEnd": source_start + folded_episode_index_map[best_end] + 1,
        }
    if best_end < 0 or best_end >= len(episode_index_map):
        return None
    return {
        "sourceId": source_id,
        "absoluteStart": source_start + episode_index_map[best_start],
        "absoluteEnd": source_start + episode_index_map[best_end] + 1,
    }


def _source_ref_contains_range(ref: dict[str, Any], candidate: dict[str, Any]) -> bool:
    if not isinstance(ref, dict) or not isinstance(candidate, dict):
        return False
    ref_source_id = str(ref.get("sourceId") or ref.get("source_id") or "").strip()
    candidate_source_id = str(candidate.get("sourceId") or candidate.get("source_id") or "").strip()
    if ref_source_id and candidate_source_id and ref_source_id != candidate_source_id:
        return False
    try:
        ref_start = int(ref.get("absoluteStart"))
        ref_end = int(ref.get("absoluteEnd"))
        candidate_start = int(candidate.get("absoluteStart"))
        candidate_end = int(candidate.get("absoluteEnd"))
    except (TypeError, ValueError):
        return False
    return ref_start <= candidate_start < candidate_end <= ref_end


def _source_ref_same_range(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _source_ref_contains_range(left, right) and _source_ref_contains_range(right, left)


def _fallback_plot_range(
    *,
    source_ref: dict[str, Any],
    index: int,
    count: int,
) -> dict[str, Any]:
    source_start = int(source_ref.get("absoluteStart") or 0)
    source_end = int(source_ref.get("absoluteEnd") or source_start)
    source_id = str(source_ref.get("sourceId") or source_ref.get("source_id") or "").strip()
    count = max(1, int(count or 1))
    zero_index = max(0, index - 1)
    start = source_start + ((source_end - source_start) * zero_index) // count
    end = source_start + ((source_end - source_start) * (zero_index + 1)) // count
    if end <= start:
        end = min(source_end, start + 1)
    return {"sourceId": source_id, "absoluteStart": start, "absoluteEnd": end}


def validate_plot_splitting_worker_output(
    output: dict[str, Any],
    *,
    episode_id: str,
    source_ref: dict[str, Any],
    episode_text: str,
    assets: dict[str, list[dict[str, Any]]] | None = None,
    context_envelope: dict[str, Any] | None = None,
    target_model: dict[str, Any] | None = None,
    allow_asset_hints: bool = True,
) -> dict[str, Any]:
    raw_output = output if isinstance(output, dict) else {}
    assets = _filter_plot_splitting_candidate_assets(assets)
    blocking: list[str] = []
    warnings: list[str] = []
    document = copy.deepcopy(_plot_source_document(raw_output))
    if not isinstance(document, dict) or not document:
        blocking.append("plot-splitting 输出必须是 plotSplitProposal 对象")
        document = {}
    top_level_disallowed = {
        "shotPlan",
        "shot_plan",
        "shots",
        "workflow",
        "generationConfig",
        "generation",
        "storyText",
        "cinematicStoryText",
        "scriptTemplateRecommendation",
        "templateRecommendation",
        "adaptationStyle",
        "notes",
    }
    for key in top_level_disallowed:
        if key in raw_output or key in document:
            blocking.append(f"plot-splitting 不允许输出 {key}")
    document_episode_id = str(document.get("episodeId") or document.get("episode_id") or "").strip()
    if document_episode_id and document_episode_id != episode_id:
        blocking.append(f"plotSplitProposal episodeId 不匹配：{document_episode_id}")
    rows = document.get("items")
    if not isinstance(rows, list) or not rows:
        blocking.append(f"plotSplitProposal 必须包含至少 {_STORYBOARD_PLOT_MIN_COUNT} 个 items[]")
        rows = []
    normalized_items: list[dict[str, Any]] = []
    count = max(_STORYBOARD_PLOT_MIN_COUNT, len(rows))
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            blocking.append(f"原文拆分内容第 {index} 条必须是对象")
            continue
        row_disallowed = {
            "shots",
            "shotIntents",
            "shot_intents",
            "shotTimingPlan",
            "shot_timing_plan",
            "storyText",
            "story_text",
            "cinematicStoryText",
            "cinematic_story_text",
            "scriptTemplateRecommendation",
            "script_template_recommendation",
            "adaptationTemplateRecommendation",
            "adaptation_template_recommendation",
            "adaptationStyle",
            "adaptation_style",
            "templateRecommendation",
            "template_recommendation",
            "storyboardTemplate",
            "storyboard_template",
            "estimatedPanelCount",
            "estimated_panel_count",
            "panelCount",
            "panel_count",
            "storyboardImagePrompt",
            "storyboard_image_prompt",
            "videoPrompt",
            "video_prompt",
            "generationConfig",
            "generation_config",
            "description",
            "summary",
            "content",
            "excerpt",
        }
        unexpected_row_keys = sorted(key for key in row_disallowed if key in row)
        if unexpected_row_keys:
            blocking.append(
                f"原文拆分内容第 {index} 条包含拆分阶段不允许输出的字段：{', '.join(unexpected_row_keys)}"
            )
        if not allow_asset_hints and any(
            key in row
            for key in (
                "assetHints",
                "asset_hints",
                "assetRefs",
                "asset_refs",
                "assetDecisions",
                "asset_decisions",
                "assetBindings",
                "asset_bindings",
            )
        ):
            blocking.append(f"原文拆分内容第 {index} 条不能在剧情拆分阶段输出资产关联字段")
        title = _compact_text(row.get("title") or row.get("name"), 40)
        source_start_anchor = _compact_source_excerpt(
            row.get("sourceStartAnchor")
            or row.get("source_start_anchor")
            or row.get("startAnchor")
            or row.get("start_anchor"),
            180,
        )
        source_end_anchor = _compact_source_excerpt(
            row.get("sourceEndAnchor")
            or row.get("source_end_anchor")
            or row.get("endAnchor")
            or row.get("end_anchor"),
            180,
            keep_tail=True,
        )
        source_fact_text = ""
        source_preview = ""
        split_reason = _compact_text(row.get("splitReason"), 220)
        reason = split_reason
        if not title:
            blocking.append(f"原文拆分内容第 {index} 条缺少 title")
        if not source_start_anchor:
            blocking.append(f"原文拆分内容第 {index} 条缺少 sourceStartAnchor")
        if not source_end_anchor:
            blocking.append(f"原文拆分内容第 {index} 条缺少 sourceEndAnchor")
        if not split_reason:
            blocking.append(f"原文拆分内容第 {index} 条缺少 splitReason，无法确认剧情边界")
        refs = _plot_refs_from_row(row, source_ref)
        provided_fact = str(row.get("sourceFactText") or row.get("source_fact_text") or "").strip()
        exact_ref_text = (
            _source_preview_from_refs(
                refs,
                episode_text=episode_text,
                episode_source_ref=source_ref,
                limit=0,
            )
            if len(refs) == 1 and provided_fact
            else ""
        )
        # The one-request adapter derives ranges from exact source coverage. Its
        # source text is a stronger locator than short anchors in repeated prose.
        anchor_inferred = (
            refs[0]
            if exact_ref_text and exact_ref_text == provided_fact
            else _find_anchor_range_in_episode(row, episode_text=episode_text, source_ref=source_ref)
        )
        if anchor_inferred:
            if len(refs) != 1 or not _source_ref_same_range(refs[0], anchor_inferred):
                if refs:
                    warnings.append(f"原文拆分内容第 {index} 条 sourceRefs 与起止锚点范围不一致，已按锚点重新定位")
                refs = [anchor_inferred]
            source_fact_text = _source_preview_from_refs(
                refs,
                episode_text=episode_text,
                episode_source_ref=source_ref,
                limit=0,
            )
        elif source_start_anchor or source_end_anchor:
            blocking.append(f"原文拆分内容第 {index} 条 sourceStartAnchor/sourceEndAnchor 无法在当前分集原文中定位为一个连续范围")
        else:
            blocking.append(f"原文拆分内容第 {index} 条缺少可定位的原文起止锚点")
        if not refs:
            refs = [_fallback_plot_range(source_ref=source_ref, index=index, count=count)]
            blocking.append(f"原文拆分内容第 {index} 条无法定位原文事实范围，不能按平均范围猜测剧情边界")
        if not source_fact_text:
            source_fact_text = _source_preview_from_refs(
                refs,
                episode_text=episode_text,
                episode_source_ref=source_ref,
                limit=0,
            )
        if not source_fact_text:
            blocking.append(f"原文拆分内容第 {index} 条无法从当前分集原文截取原文事实内容")
        source_preview = source_fact_text[:260].rstrip()
        if source_fact_text and not source_start_anchor:
            source_start_anchor = _compact_source_excerpt(source_fact_text, 80)
        if source_fact_text and not source_end_anchor:
            source_end_anchor = _compact_source_excerpt(source_fact_text, 80, keep_tail=True)
        asset_hints = _normalize_plot_asset_hints(row.get("assetHints"), assets)
        asset_hints = _filter_plot_scene_asset_hints(
            asset_hints,
            assets,
            item_label=f"原文拆分内容第 {index} 条",
            warnings=warnings,
        )
        normalized_item = {
            "index": index,
            "id": str(row.get("id") or row.get("plotId") or f"plot_{index:03d}").strip() or f"plot_{index:03d}",
            "title": title or f"原文拆分内容 {index}",
            "sourceStartAnchor": source_start_anchor,
            "sourceEndAnchor": source_end_anchor,
            "sourceFactText": source_fact_text,
            "sourcePreview": source_preview,
            "sourceRefs": refs,
            "sourceRange": copy.deepcopy(refs[0]),
            "reason": reason,
            "splitReason": split_reason or reason,
        }
        if "excludedTexts" in row:
            normalized_item["excludedTexts"] = copy.deepcopy(row["excludedTexts"])
        if allow_asset_hints:
            normalized_item["assetHints"] = asset_hints
            asset_bindings = row.get("assetBindings") or row.get("asset_bindings")
            if isinstance(asset_bindings, list):
                normalized_item["assetBindings"] = copy.deepcopy(asset_bindings)
        normalized_items.append(normalized_item)
    locked_episode_title = _normalize_episode_boundary_title(
        source_ref.get("title")
        or source_ref.get("episodeTitle")
        or source_ref.get("episode_title"),
        episode_id,
    )
    worker_episode_title = _normalize_episode_boundary_title(
        document.get("episodeTitle") or document.get("episode_title") or document.get("title"),
        episode_id,
    )
    if bool(source_ref.get("titleLocked") or source_ref.get("title_locked")) and locked_episode_title:
        episode_title = locked_episode_title
    else:
        episode_title = worker_episode_title
    if not episode_title:
        blocking.append("plotSplitProposal 缺少有效 episodeTitle")
    proposal = {
        "episodeId": episode_id,
        "episodeTitle": episode_title,
        "count": len(normalized_items),
        "items": normalized_items,
    }
    provenance = context_provenance(context_envelope)
    if provenance:
        proposal["contextProvenance"] = provenance
    return {
        "success": not blocking,
        "blockingIssues": blocking,
        "warnings": warnings,
        "plotSplitProposal": proposal,
    }
