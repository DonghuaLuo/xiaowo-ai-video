# -*- coding: utf-8 -*-
"""Convert one model response containing plot segments and asset IDs into a source-backed proposal."""
from __future__ import annotations

import copy
from typing import Any


ASSET_TYPES = ("characters", "creatures", "scenes", "props")


def clean_plot_source_text(source_text: str, excluded_texts: Any) -> str:
    """Remove only explicitly identified, exact source excerpts in source order."""
    if not isinstance(excluded_texts, list) or any(
        not isinstance(value, str) or not value.strip() for value in excluded_texts
    ):
        raise ValueError("清理片段 excludedTexts 必须是原文字符串数组")
    cursor = 0
    kept: list[str] = []
    for value in excluded_texts:
        start = source_text.find(value, cursor)
        if start < 0:
            raise ValueError("清理片段不在对应剧情原文中，或清理顺序与原文不一致")
        kept.append(source_text[cursor:start])
        cursor = start + len(value)
    kept.append(source_text[cursor:])
    cleaned = "".join(kept).strip()
    if not cleaned:
        raise ValueError("清理后剧情片段为空")
    return cleaned


def _without_whitespace(text: str) -> str:
    return "".join(char for char in text if not char.isspace())


def resolve_plot_split_source_range_text(
    project_id: str, episode_text: str, source_ref: dict[str, Any]
) -> str:
    """Keep absolute offsets in the original text; the saved episode may be trimmed."""
    from .source_text_store import get_source_text

    source_id = str(source_ref.get("sourceId") or "").strip()
    start = int(source_ref.get("absoluteStart") or 0)
    end = int(source_ref.get("absoluteEnd") or 0)
    if not source_id or start < 0 or end <= start:
        raise ValueError("已提交 source range 无效")
    original = str(get_source_text(project_id, source_id).get("text") or "")
    if end > len(original):
        raise ValueError("已提交 source range 超出原始小说")
    source_range_text = original[start:end]
    if not _without_whitespace(source_range_text) or (
        _without_whitespace(source_range_text) != _without_whitespace(episode_text)
    ):
        raise ValueError("分集原文内容与已提交 source range 不一致，请重新提交分集原文")
    return source_range_text


def compact_plot_asset_catalog(assets: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Match the compact catalog used by the accepted Prompt Lab request builder."""
    catalog: dict[str, list[dict[str, Any]]] = {}
    for kind in ASSET_TYPES:
        catalog[kind] = []
        for asset in assets.get(kind, []):
            row = {"id": str(asset["id"]), "name": str(asset.get("name") or asset["id"])}
            aliases = asset.get("aliases")
            if isinstance(aliases, list) and aliases:
                row["aliases"] = [str(alias) for alias in aliases if str(alias).strip()]
            description = str(
                asset.get("desc") or asset.get("description") or asset.get("identityHint") or ""
            ).strip()
            if description:
                sentences = [part.strip() for part in description.split("。") if part.strip()]
                brief = "。".join(sentences[:2])
                if len(brief) > 180 and sentences:
                    brief = sentences[0][:180]
                row["identity"] = brief.rstrip("。") + "。"
            catalog[kind].append(row)
    return catalog


def validate_plot_split_asset_ids(
    proposal: dict[str, Any], assets: dict[str, list[dict[str, Any]]]
) -> None:
    allowed = {
        kind: {str(row.get("id") or "") for row in assets.get(kind, []) if isinstance(row, dict)}
        for kind in ASSET_TYPES
    }
    items = proposal.get("items") if isinstance(proposal.get("items"), list) else []
    for index, item in enumerate(items, start=1):
        hints = item.get("assetHints") if isinstance(item, dict) else None
        if not isinstance(hints, dict):
            raise ValueError(f"剧情 {index} 缺少资产关联")
        expected_bindings: set[tuple[str, str]] = set()
        for kind in ASSET_TYPES:
            ids = hints.get(kind)
            if not isinstance(ids, list) or any(not isinstance(asset_id, str) for asset_id in ids):
                raise ValueError(f"剧情 {index} 的 {kind} 必须是资产 ID 数组")
            unknown = [asset_id for asset_id in ids if asset_id not in allowed[kind]]
            if unknown:
                raise ValueError(f"剧情 {index} 的 {kind} 包含目录外资产 ID：{', '.join(unknown[:4])}")
            expected_bindings.update((kind, asset_id) for asset_id in ids)
        bindings = item.get("assetBindings") if isinstance(item, dict) else None
        if not isinstance(bindings, list) or any(not isinstance(row, dict) for row in bindings):
            raise ValueError(f"剧情 {index} 缺少资产绑定列表")
        actual_bindings = {
            (str(row.get("assetType") or ""), str(row.get("id") or "")) for row in bindings
        }
        if actual_bindings != expected_bindings:
            raise ValueError(f"剧情 {index} 的资产绑定与资产 ID 数组不一致")


def validate_plot_split_source_coverage(
    proposal: dict[str, Any], source_range_text: str, source_ref: dict[str, Any]
) -> None:
    items = proposal.get("items") if isinstance(proposal.get("items"), list) else []
    if not items:
        raise ValueError("剧情拆分结果没有片段")
    source_start = int(source_ref.get("absoluteStart") or 0)
    source_end = int(source_ref.get("absoluteEnd") or 0)
    source_id = str(source_ref.get("sourceId") or "").strip()
    if not source_id or source_end - source_start != len(source_range_text):
        raise ValueError("原始小说切片与已提交 source range 长度不一致")
    cursor = source_start
    for index, item in enumerate(items, start=1):
        refs = item.get("sourceRefs") if isinstance(item, dict) else None
        if not isinstance(refs, list) or len(refs) != 1 or not isinstance(refs[0], dict):
            raise ValueError(f"剧情 {index} 缺少唯一原文范围")
        ref = refs[0]
        start = int(ref.get("absoluteStart") or 0)
        end = int(ref.get("absoluteEnd") or 0)
        if str(ref.get("sourceId") or "").strip() != source_id or start != cursor or end <= start or end > source_end:
            raise ValueError(f"剧情 {index} 的原文范围不连续或超出分集")
        actual = source_range_text[start - source_start:end - source_start].strip()
        if actual != str(item.get("sourceFactText") or "").strip():
            raise ValueError(f"剧情 {index} 的原文事实与来源范围不一致")
        clean_plot_source_text(actual, item.get("excludedTexts", []))
        cursor = end
    if cursor != source_end:
        raise ValueError("剧情拆分结果没有覆盖分集末尾")


def proposal_from_one_request(
    data: Any,
    *,
    episode_id: str,
    episode_title: str,
    source_text: str,
    source_range_text: str,
    source_ref: dict[str, Any],
    assets: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Verify exact source coverage and derive original offsets without asking the model for ranges."""
    segments = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(segments, list) or not segments:
        raise ValueError("模型未返回非空 segments 数组")
    positions = [index for index, char in enumerate(source_range_text) if not char.isspace()]
    normalized_source = "".join(source_range_text[index] for index in positions)
    if not normalized_source:
        raise ValueError("分集原文为空")
    if _without_whitespace(source_text) != normalized_source:
        raise ValueError("分集原文内容与已提交 source range 不一致，请重新提交分集原文")
    parts: list[str] = []
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            raise ValueError(f"剧情 {index} 缺少连续原文 text")
        part = _without_whitespace(segment["text"])
        if not part:
            raise ValueError(f"剧情 {index} 的原文 text 为空")
        parts.append(part)
    if "".join(parts) != normalized_source:
        raise ValueError("模型返回的剧情文本与分集原文不一致，存在遗漏、重复或改写")

    source_start = int(source_ref.get("absoluteStart") or 0)
    source_end = int(source_ref.get("absoluteEnd") or 0)
    source_id = str(source_ref.get("sourceId") or "").strip()
    if not source_id or source_end - source_start != len(source_range_text):
        raise ValueError("原始小说切片与已提交 source range 长度不一致")

    items: list[dict[str, Any]] = []
    cursor = 0
    for index, (segment, part) in enumerate(zip(segments, parts), start=1):
        next_cursor = cursor + len(part)
        raw_start = 0 if cursor == 0 else positions[cursor]
        raw_end = positions[next_cursor] if next_cursor < len(positions) else len(source_range_text)
        fact_text = source_range_text[raw_start:raw_end].strip()
        excluded_texts = segment.get("excludedTexts", [])
        try:
            clean_plot_source_text(fact_text, excluded_texts)
        except ValueError as exc:
            raise ValueError(f"剧情 {index}：{exc}") from exc
        hints: dict[str, list[str]] = {}
        bindings: list[dict[str, str]] = []
        for kind in ASSET_TYPES:
            ids = segment.get(kind)
            if not isinstance(ids, list) or any(not isinstance(asset_id, str) for asset_id in ids):
                raise ValueError(f"剧情 {index} 的 {kind} 必须是资产 ID 数组")
            unique_ids = list(dict.fromkeys(ids))
            hints[kind] = unique_ids
            bindings.extend({"assetType": kind, "id": asset_id} for asset_id in unique_ids)
        source_range = {
            "sourceId": source_id,
            "absoluteStart": source_start + raw_start,
            "absoluteEnd": source_start + raw_end,
        }
        items.append({
            "index": index,
            "id": f"plot_{index:03d}",
            "title": str(segment.get("title") or f"剧情 {index}").strip(),
            "sourceStartAnchor": fact_text[:80].strip(),
            "sourceEndAnchor": fact_text[-80:].strip(),
            "sourceFactText": fact_text,
            "excludedTexts": copy.deepcopy(excluded_texts),
            "sourceRefs": [copy.deepcopy(source_range)],
            "sourceRange": source_range,
            "splitReason": str(segment.get("splitReason") or "按小事件的因果推进划分").strip(),
            "assetHints": hints,
            "assetBindings": bindings,
        })
        cursor = next_cursor
    proposal = {
        "episodeId": episode_id,
        "episodeTitle": episode_title,
        "count": len(items),
        "items": items,
    }
    validate_plot_split_asset_ids(proposal, assets)
    validate_plot_split_source_coverage(proposal, source_range_text, source_ref)
    return proposal
