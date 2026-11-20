# -*- coding: utf-8 -*-
"""资产范围分析状态及资产引用投影。"""
from __future__ import annotations

import copy as copy
from .assets import (
    _asset_store_path,
    _project_asset_is_referenced,
)
from .catalogs import (
    DEFAULT_ASSETS,
)
from .source_coverage import get_source_coverage
from .store_core import (
    _read_json,
)

from typing import Any


_ASSET_RANGE_ANALYSIS_COMPLETED_STATUSES = {"completed"}


def _agent_asset_range_analysis_status(row: dict[str, Any]) -> str:
    return str(row.get("analysisStatus") or "").strip().lower()


def _agent_asset_range_analysis_completed(row: dict[str, Any]) -> bool:
    return _agent_asset_range_analysis_status(row) in _ASSET_RANGE_ANALYSIS_COMPLETED_STATUSES


def _agent_asset_range_bounds(row: dict[str, Any]) -> tuple[int, int]:
    try:
        start = int(row.get("absoluteStart") or 0)
        end = int(row.get("absoluteEnd") or 0)
    except (TypeError, ValueError):
        return 0, 0
    return start, end


def _agent_blocking_asset_analysis_ranges(
    coverage: dict[str, Any],
    *,
    project_id: str = "",
    source_id: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    asset_ranges = coverage.get("assetRanges") if isinstance(coverage.get("assetRanges"), list) else []
    for item in asset_ranges:
        if not isinstance(item, dict):
            continue
        if source_id:
            range_source_id = str(item.get("sourceId") or "").strip()
            if range_source_id != source_id:
                continue
        start, end = _agent_asset_range_bounds(item)
        if end <= start:
            continue
        if not _agent_asset_range_analysis_completed(item):
            rows.append(item)
    return sorted(
        rows,
        key=lambda item: (
            *_agent_asset_range_bounds(item),
            str(item.get("rangeId") or ""),
        ),
    )


def _agent_asset_range_id_tokens(*values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        rows = value if isinstance(value, (list, tuple, set)) else (value,)
        for item in rows:
            token = str(item or "").strip()
            if token and token not in result:
                result.append(token)
    return result


def _agent_remove_asset_range_refs_from_asset(row: dict[str, Any], asset_range_id: str) -> tuple[dict[str, Any], bool]:
    item = copy.deepcopy(row)
    changed = False
    range_ids = _agent_asset_range_id_tokens(
        item.get("assetRangeIds"),
        item.get("assetRangeId"),
    )
    remaining = [range_id for range_id in range_ids if range_id != asset_range_id]
    if range_ids != remaining:
        changed = True
    if remaining:
        item["assetRangeIds"] = remaining
        if str(item.get("assetRangeId") or "").strip() == asset_range_id:
            item["assetRangeId"] = remaining[-1]
    else:
        item.pop("assetRangeIds", None)
        if str(item.get("assetRangeId") or "").strip() == asset_range_id:
            item.pop("assetRangeId", None)
    refs = item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else []
    if refs:
        kept_refs = [
            ref
            for ref in refs
            if not (
                isinstance(ref, dict)
                and str(ref.get("assetRangeId") or "").strip() == asset_range_id
            )
        ]
        if len(kept_refs) != len(refs):
            changed = True
            if kept_refs:
                item["sourceRefs"] = kept_refs
            else:
                item.pop("sourceRefs", None)
    return item, changed


def _agent_range_int(row: dict[str, Any] | None, *keys: str, default: int = 0) -> int:
    if not isinstance(row, dict):
        return default
    for key in keys:
        try:
            value = row.get(key)
            if value is not None and str(value).strip() != "":
                return int(value)
        except (TypeError, ValueError):
            continue
    return default


def _agent_current_source_asset_ranges(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    rows = coverage.get("assetRanges") if isinstance(coverage.get("assetRanges"), list) else []
    source_id = str(coverage.get("sourceId") or "").strip()
    result = [
        item
        for item in rows
        if isinstance(item, dict)
        and (not source_id or str(item.get("sourceId") or "").strip() == source_id)
    ]
    result.sort(
        key=lambda item: (
            _agent_range_int(item, "absoluteEnd"),
            _agent_range_int(item, "absoluteStart"),
            str(item.get("rangeId") or ""),
        )
    )
    return result


def _agent_latest_asset_range_row(coverage: dict[str, Any]) -> dict[str, Any] | None:
    rows = _agent_current_source_asset_ranges(coverage)
    return copy.deepcopy(rows[-1]) if rows else None


def _agent_asset_range_label(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return "未知资产范围"
    range_id = str(row.get("rangeId") or "").strip() or "未知范围"
    start = _agent_range_int(row, "absoluteStart")
    end = _agent_range_int(row, "absoluteEnd")
    units = _agent_range_int(row, "unitCount")
    detail = f"{start}-{end}"
    if units > 0:
        detail = f"{detail}，约 {units} 字"
    return f"{range_id}（{detail}）"


def _agent_asset_range_user_label(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return "上一段资产范围"
    start = _agent_range_int(row, "absoluteStart")
    end = _agent_range_int(row, "absoluteEnd")
    units = _agent_range_int(row, "unitCount")
    if end > start:
        suffix = f"，约 {units} 字" if units > 0 else ""
        return f"原文 {start}-{end} 的资产范围{suffix}"
    return "上一段资产范围"


def _agent_asset_range_output_preview(project_id: str, asset_range_id: str) -> dict[str, dict[str, int]]:
    assets = _read_json(_asset_store_path("project", project_id), DEFAULT_ASSETS)
    preview: dict[str, dict[str, int]] = {
        "delete": {},
        "detach": {},
        "keepReferenced": {},
    }
    for asset_type, _label in _AGENT_ASSET_REPORT_TYPES:
        rows = assets.get(asset_type)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            range_ids = _agent_asset_range_id_tokens(
                row.get("assetRangeIds"),
                row.get("assetRangeId"),
            )
            if asset_range_id not in range_ids:
                continue
            remaining = [range_id for range_id in range_ids if range_id != asset_range_id]
            if not remaining and not _project_asset_is_referenced(project_id, asset_type, row):
                preview["delete"][asset_type] = preview["delete"].get(asset_type, 0) + 1
            elif not remaining:
                preview["keepReferenced"][asset_type] = preview["keepReferenced"].get(asset_type, 0) + 1
            else:
                preview["detach"][asset_type] = preview["detach"].get(asset_type, 0) + 1
    return preview


def _agent_source_coverage_safe(project_id: str) -> dict[str, Any]:
    try:
        result = get_source_coverage(project_id)
    except Exception:
        return {}
    coverage = result.get("coverage") if isinstance(result, dict) else {}
    return coverage if isinstance(coverage, dict) else {}


_AGENT_ASSET_REPORT_TYPES = (
    ("characters", "角色"),
    ("creatures", "生物"),
    ("scenes", "场景"),
    ("props", "道具"),
)
