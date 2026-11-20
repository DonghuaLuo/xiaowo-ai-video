# -*- coding: utf-8 -*-
"""资产拆分批次的材料列表、统计和原文读取。"""
from __future__ import annotations

from .source_coverage import _asset_range_analysis_state
from .source_coverage import _asset_range_bounds
from .source_coverage import _asset_range_created_ids
from .source_coverage import _asset_range_id_tokens
from .source_coverage import _load_source_coverage
from .source_coverage import _source_refs_from_asset_row
from .source_text_store import _compact_text
from .source_text_store import _read_source_content
from .source_text_store import list_sources
from .store_core import ASSET_LIFECYCLE_ALL
from .store_core import ASSET_LIFECYCLE_OFFLINE
from .store_core import _asset_lifecycle_status
from typing import Any
from utils.text_metrics import content_char_count
import copy


_ASSET_SPLIT_RECORD_TYPES = ("characters", "creatures", "scenes", "props")


_ASSET_SPLIT_RECORD_SOURCE_TEXT_LIMIT = 720


_ASSET_SPLIT_RECORD_SOURCE_TEXT_MAX_LIMIT = 50000


def _asset_split_source_text_limit(value: int | str | None) -> int:
    if value is None:
        return _ASSET_SPLIT_RECORD_SOURCE_TEXT_LIMIT
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return _ASSET_SPLIT_RECORD_SOURCE_TEXT_LIMIT
    return max(0, min(limit, _ASSET_SPLIT_RECORD_SOURCE_TEXT_MAX_LIMIT))


def _asset_split_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _asset_split_source_rows_by_id(project_id: str) -> dict[str, dict[str, Any]]:
    rows = list_sources(project_id).get("sources")
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_row_id = str(
            row.get("id")
            or row.get("sourceId")
            or ""
        ).strip()
        if source_row_id and source_row_id not in result:
            result[source_row_id] = row
    return result


def _asset_split_source_text(
    project_id: str,
    source_rows: dict[str, dict[str, Any]],
    source_id: str,
    cache: dict[str, str],
    *,
    strict: bool = False,
) -> str:
    if source_id in cache:
        return cache[source_id]
    source = source_rows.get(source_id)
    if not source:
        if strict:
            raise ValueError("未找到资产拆分原文文件")
        cache[source_id] = ""
        return ""
    try:
        cache[source_id] = _read_source_content(project_id, source)
    except Exception as exc:
        if strict:
            raise ValueError(f"读取资产拆分原文失败：{exc}") from exc
        cache[source_id] = ""
    return cache[source_id]


def _asset_split_range_ids_for_asset(row: dict[str, Any]) -> list[str]:
    ref_range_ids: list[str] = []
    for ref in _source_refs_from_asset_row(row):
        ref_range_id = str(
            ref.get("assetRangeId")
            or ""
        ).strip()
        if ref_range_id:
            ref_range_ids.append(ref_range_id)
    return _asset_range_id_tokens(
        row.get("assetRangeIds"),
        row.get("assetRangeId"),
        ref_range_ids,
    )


def _asset_split_source_range_keys_for_asset(row: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []

    def add_key(source_id: Any, range_id: Any) -> None:
        source_token = str(source_id or "").strip()
        range_token = str(range_id or "").strip()
        if not source_token or not range_token:
            return
        key = (source_token, range_token)
        if key not in result:
            result.append(key)

    for ref in _source_refs_from_asset_row(row):
        add_key(
            ref.get("sourceId"),
            ref.get("assetRangeId"),
        )
    if result:
        return result

    source_range = row.get("sourceRange") if isinstance(row.get("sourceRange"), dict) else {}
    source_token = (
        row.get("sourceId")
        or source_range.get("sourceId")
    )
    for range_id in _asset_split_range_ids_for_asset(row):
        add_key(source_token, range_id)
    return result


def _asset_split_asset_id_tokens(row: dict[str, Any]) -> list[str]:
    return [
        token.casefold()
        for token in _asset_range_id_tokens(
            row.get("id"),
            row.get("assetId"),
            row.get("asset_id"),
        )
    ]


def _asset_split_stable_id_tokens(row: dict[str, Any]) -> set[str]:
    """Return only persisted identity fields used to determine range creation."""
    return {
        str(value).strip().casefold()
        for value in (row.get("id"), row.get("assetId"), row.get("asset_id"))
        if str(value or "").strip()
    }


def _asset_split_record_asset(asset_type: str, row: dict[str, Any]) -> dict[str, Any]:
    asset = copy.deepcopy(row)
    asset["assetType"] = asset_type
    asset["lifecycleStatus"] = _asset_lifecycle_status(asset)
    return asset


def _asset_split_empty_groups() -> dict[str, list[dict[str, Any]]]:
    return {asset_type: [] for asset_type in _ASSET_SPLIT_RECORD_TYPES}


def _asset_split_counts(assets: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {
        asset_type: len(assets.get(asset_type) if isinstance(assets.get(asset_type), list) else [])
        for asset_type in _ASSET_SPLIT_RECORD_TYPES
    }


def _asset_split_append_asset(
    grouped_assets: dict[str, list[dict[str, Any]]],
    asset_type: str,
    asset: dict[str, Any],
    existing_ids: set[str],
) -> None:
    asset_ids = _asset_split_asset_id_tokens(asset)
    if asset_ids and any(asset_id in existing_ids for asset_id in asset_ids):
        return
    grouped_assets.setdefault(asset_type, []).append(copy.deepcopy(asset))
    existing_ids.update(asset_ids)


def _asset_split_merge_asset_groups(
    grouped_assets: dict[str, list[dict[str, Any]]],
    incoming_groups: dict[str, list[dict[str, Any]]] | None,
    existing_ids: set[str],
) -> None:
    if not isinstance(incoming_groups, dict):
        return
    for asset_type in _ASSET_SPLIT_RECORD_TYPES:
        rows = incoming_groups.get(asset_type)
        if not isinstance(rows, list):
            continue
        for asset in rows:
            if isinstance(asset, dict):
                _asset_split_append_asset(grouped_assets, asset_type, asset, existing_ids)


def list_asset_split_batches(
    project_id: str,
    source_id: str | None = None,
    *,
    source_text_limit: int | str | None = _ASSET_SPLIT_RECORD_SOURCE_TEXT_LIMIT,
) -> dict[str, Any]:
    from .assets import list_assets
    requested_source_id = str(source_id or "").strip()
    coverage = _load_source_coverage(project_id, requested_source_id or None)
    source_rows = _asset_split_source_rows_by_id(project_id)
    source_text_cache: dict[str, str] = {}
    text_limit = _asset_split_source_text_limit(source_text_limit)
    asset_store = list_assets(
        "project",
        project_id,
        hydrate=True,
        include_source_metadata=True,
        lifecycle_status=ASSET_LIFECYCLE_ALL,
        source_coverage=coverage,
    )
    assets_by_range_id: dict[str, dict[str, list[dict[str, Any]]]] = {}
    assets_by_source_range_id: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = {}
    for asset_type in _ASSET_SPLIT_RECORD_TYPES:
        rows = asset_store.get(asset_type) if isinstance(asset_store, dict) else []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            asset = _asset_split_record_asset(asset_type, row)
            source_range_keys = _asset_split_source_range_keys_for_asset(row)
            if source_range_keys:
                for source_range_key in source_range_keys:
                    groups = assets_by_source_range_id.setdefault(source_range_key, _asset_split_empty_groups())
                    groups[asset_type].append(copy.deepcopy(asset))
                continue
            for range_id in _asset_split_range_ids_for_asset(row):
                groups = assets_by_range_id.setdefault(range_id, _asset_split_empty_groups())
                groups[asset_type].append(copy.deepcopy(asset))

    batches: list[dict[str, Any]] = []
    raw_ranges = coverage.get("assetRanges")
    asset_ranges = raw_ranges if isinstance(raw_ranges, list) else []
    for range_row in asset_ranges:
        if not isinstance(range_row, dict):
            continue
        range_id = str(range_row.get("rangeId") or "").strip()
        if not range_id:
            continue
        current_source_id = str(
            range_row.get("sourceId")
            or coverage.get("sourceId")
            or requested_source_id
            or ""
        ).strip()
        if requested_source_id and current_source_id != requested_source_id:
            continue
        start, end = _asset_range_bounds(range_row)
        if end < start:
            end = start
        actual_units = _asset_split_int(range_row.get("actualUnits"), max(0, end - start))
        source_text = _asset_split_source_text(
            project_id,
            source_rows,
            current_source_id,
            source_text_cache,
        )
        range_text = ""
        if source_text:
            safe_start = max(0, min(start, len(source_text)))
            safe_end = max(safe_start, min(end, len(source_text)))
            range_text = source_text[safe_start:safe_end].strip()
            range_units = content_char_count(range_text)
            if range_units > 0:
                actual_units = range_units
        source_text_char_count = actual_units if actual_units > 0 else max(0, end - start)
        display_text = range_text[:text_limit] if text_limit else ""
        created_ids = _asset_range_created_ids(range_row)
        grouped_assets = _asset_split_empty_groups()
        existing_ids: set[str] = set()
        _asset_split_merge_asset_groups(
            grouped_assets,
            assets_by_source_range_id.get((current_source_id, range_id)),
            existing_ids,
        )
        _asset_split_merge_asset_groups(
            grouped_assets,
            assets_by_range_id.get(range_id),
            existing_ids,
        )
        matched_created_tokens = {
            token
            for token in (created_id.casefold() for created_id in created_ids)
            if token in existing_ids
        }
        created_token_set = {created_id.casefold() for created_id in created_ids}
        new_asset_count = 0
        for rows in grouped_assets.values():
            for asset in rows:
                if not isinstance(asset, dict):
                    continue
                created_in_range = bool(
                    _asset_split_stable_id_tokens(asset).intersection(created_token_set)
                )
                asset["createdInRange"] = created_in_range
                if created_in_range:
                    new_asset_count += 1

        counts = _asset_split_counts(grouped_assets)
        total_assets = sum(counts.values())
        active_assets = 0
        offline_assets = 0
        for rows in grouped_assets.values():
            for asset in rows:
                if not isinstance(asset, dict):
                    continue
                if _asset_lifecycle_status(asset) == ASSET_LIFECYCLE_OFFLINE:
                    offline_assets += 1
                else:
                    active_assets += 1
        source_row = source_rows.get(current_source_id) or {}
        excerpt = str(range_row.get("excerpt") or "").strip()
        if not excerpt and range_text:
            excerpt = _compact_text(range_text, 180)
        batch_index = len(batches) + 1
        batches.append(
            {
                "index": batch_index,
                "batchLabel": f"第 {batch_index} 次拆分",
                "rangeId": range_id,
                "sourceId": current_source_id,
                "sourceTitle": str(source_row.get("title") or range_row.get("sourceTitle") or "小说文本"),
                "absoluteStart": start,
                "absoluteEnd": end,
                "rangeLabel": f"{start} - {end}",
                "targetUnits": range_row.get("targetUnits"),
                "actualUnits": actual_units,
                "analysisStatus": _asset_range_analysis_state(range_row),
                "summary": str(range_row.get("summary") or ""),
                "storyUnitSummary": str(range_row.get("storyUnitSummary") or ""),
                "excerpt": excerpt,
                "sourceText": display_text,
                "sourceTextCharCount": source_text_char_count,
                "sourceTextTruncated": bool(range_text and len(range_text) > len(display_text)),
                "createdAt": str(range_row.get("createdAt") or ""),
                "assetCounts": counts,
                "totalAssetCount": total_assets,
                "newAssetCount": new_asset_count,
                "activeAssetCount": active_assets,
                "offlineAssetCount": offline_assets,
                "orphanAssetIds": [
                    created_id
                    for created_id in created_ids
                    if created_id.casefold() not in matched_created_tokens
                ],
                "assets": grouped_assets,
            }
        )
    batches.sort(
        key=lambda item: (
            _asset_split_int(item.get("absoluteStart"), 0),
            _asset_split_int(item.get("index"), 0),
        )
    )
    return {
        "success": True,
        "projectId": project_id,
        "sourceId": requested_source_id or str(coverage.get("sourceId") or ""),
        "sourceTextLimit": text_limit,
        "batches": batches,
        "totalBatches": len(batches),
    }


def get_asset_split_batch_source_text(
    project_id: str,
    range_id: str,
    source_id: str | None = None,
) -> dict[str, Any]:
    requested_range_id = str(range_id or "").strip()
    if not requested_range_id:
        raise ValueError("缺少资产拆分范围 ID")
    requested_source_id = str(source_id or "").strip()
    coverage = _load_source_coverage(project_id, requested_source_id or None)
    source_rows = _asset_split_source_rows_by_id(project_id)
    source_text_cache: dict[str, str] = {}
    raw_ranges = coverage.get("assetRanges")
    asset_ranges = raw_ranges if isinstance(raw_ranges, list) else []
    for range_row in asset_ranges:
        if not isinstance(range_row, dict):
            continue
        current_range_id = str(range_row.get("rangeId") or "").strip()
        if not current_range_id:
            continue
        if current_range_id != requested_range_id:
            continue
        current_source_id = str(
            range_row.get("sourceId")
            or coverage.get("sourceId")
            or requested_source_id
            or ""
        ).strip()
        if requested_source_id and current_source_id != requested_source_id:
            continue
        start, end = _asset_range_bounds(range_row)
        if end < start:
            end = start
        source_text = _asset_split_source_text(
            project_id,
            source_rows,
            current_source_id,
            source_text_cache,
            strict=True,
        )
        range_text = ""
        if source_text:
            safe_start = max(0, min(start, len(source_text)))
            safe_end = max(safe_start, min(end, len(source_text)))
            range_text = source_text[safe_start:safe_end].strip()
        range_units = content_char_count(range_text)
        actual_units = _asset_split_int(
            range_row.get("actualUnits"),
            range_units if range_units > 0 else max(0, end - start),
        )
        if range_units > 0:
            actual_units = range_units
        source_row = source_rows.get(current_source_id) or {}
        return {
            "success": True,
            "projectId": project_id,
            "sourceId": current_source_id,
            "sourceTitle": str(
                source_row.get("title")
                or range_row.get("sourceTitle")
                or "小说文本"
            ),
            "rangeId": current_range_id,
            "rangeLabel": f"{start} - {end}",
            "absoluteStart": start,
            "absoluteEnd": end,
            "actualUnits": actual_units,
            "sourceText": range_text,
            "sourceTextCharCount": range_units if range_units > 0 else actual_units,
            "sourceTextTruncated": False,
        }
    raise ValueError("未找到资产拆分原文范围")
