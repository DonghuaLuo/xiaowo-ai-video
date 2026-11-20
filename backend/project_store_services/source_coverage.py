# -*- coding: utf-8 -*-
"""原文覆盖账本、范围状态、资产提取完成度与资产来源约束。"""
from __future__ import annotations

from .catalogs import DEFAULT_ASSETS
from .catalogs import DEFAULT_ASSET_EXTRACTION_TARGET_UNITS
from .catalogs import DEFAULT_EPISODE_TARGET_UNITS
from .source_index import _source_index_path
from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json
from pathlib import Path
from typing import Any
import copy


_ASSET_RANGE_ANALYSIS_COMPLETED_STATUSES = {"completed"}


def _source_coverage_path(project_id: str) -> Path:
    from .agent_sessions import _project_dir
    return _project_dir(project_id) / "source_coverage.json"


def _coverage_target_units(config: dict[str, Any], key: str, default_value: int) -> int:
    try:
        value = int(config.get(key) or default_value)
    except (TypeError, ValueError):
        value = default_value
    return max(1, value)


def _default_source_coverage(project_id: str, source_id: str | None = None) -> dict[str, Any]:
    from .source_text_store import _select_project_sources
    sources = _select_project_sources(project_id, source_id)
    return _new_source_coverage(project_id, str(sources[0].get("id") or ""))


def _new_source_coverage(project_id: str, source_id: str) -> dict[str, Any]:
    from .project_management import get_project_business_config

    config = get_project_business_config(project_id)
    return {
        "schemaVersion": 1,
        "revision": 0,
        "sourceId": source_id,
        "episodeCursor": {
            "nextOffset": 0,
            "targetUnits": _coverage_target_units(config, "episode_target_units", DEFAULT_EPISODE_TARGET_UNITS),
            "lastEpisodeId": None,
        },
        "assetCursor": {
            "nextOffset": 0,
            "targetUnits": _coverage_target_units(
                config,
                "asset_extraction_target_units",
                DEFAULT_ASSET_EXTRACTION_TARGET_UNITS,
            ),
            "lastRangeId": None,
        },
        "episodeRanges": [],
        "assetRanges": [],
        "updatedAt": _now(),
    }


def _normalize_coverage_cursor(cursor: Any, *, target_units: int) -> dict[str, Any]:
    data = cursor if isinstance(cursor, dict) else {}
    try:
        next_offset = int(data.get("nextOffset") or 0)
    except (TypeError, ValueError):
        next_offset = 0
    return {
        "nextOffset": max(0, next_offset),
        "targetUnits": target_units,
        "lastEpisodeId": data.get("lastEpisodeId"),
        "lastRangeId": data.get("lastRangeId"),
    }


def _range_cursor_from_rows(rows: list[Any]) -> dict[str, Any]:
    next_offset = 0
    last_range_id: str | None = None
    for item in rows:
        if not isinstance(item, dict):
            continue
        try:
            end = int(item.get("absoluteEnd") or 0)
        except (TypeError, ValueError):
            end = 0
        if end > next_offset:
            next_offset = end
            last_range_id = str(item.get("rangeId") or "") or None
    return {"nextOffset": next_offset, "lastRangeId": last_range_id}


def _normalize_source_coverage(project_id: str, data: Any, source_id: str | None = None) -> dict[str, Any]:
    default = _default_source_coverage(project_id, source_id)
    if not isinstance(data, dict):
        return default
    selected_source_id = str(source_id or data.get("sourceId") or default["sourceId"])
    if selected_source_id != default["sourceId"]:
        return _default_source_coverage(project_id, selected_source_id)
    episode_target = default["episodeCursor"]["targetUnits"]
    asset_target = default["assetCursor"]["targetUnits"]
    episode_cursor = _normalize_coverage_cursor(data.get("episodeCursor"), target_units=episode_target)
    asset_cursor = _normalize_coverage_cursor(data.get("assetCursor"), target_units=asset_target)
    episode_ranges = [item for item in data.get("episodeRanges", []) if isinstance(item, dict)]
    asset_ranges = [copy.deepcopy(item) for item in data.get("assetRanges", []) if isinstance(item, dict)]
    asset_range_cursor = _range_cursor_from_rows(asset_ranges)
    if int(asset_range_cursor["nextOffset"] or 0) != int(asset_cursor["nextOffset"] or 0):
        asset_cursor["nextOffset"] = asset_range_cursor["nextOffset"]
        asset_cursor["lastRangeId"] = asset_range_cursor["lastRangeId"]
    return {
        "schemaVersion": 1,
        "revision": int(data.get("revision") or default.get("revision") or 0),
        "sourceId": selected_source_id,
        "episodeCursor": {
            "nextOffset": episode_cursor["nextOffset"],
            "targetUnits": episode_cursor["targetUnits"],
            "lastEpisodeId": episode_cursor.get("lastEpisodeId"),
        },
        "assetCursor": {
            "nextOffset": asset_cursor["nextOffset"],
            "targetUnits": asset_cursor["targetUnits"],
            "lastRangeId": asset_cursor.get("lastRangeId"),
        },
        "episodeRanges": episode_ranges,
        "assetRanges": asset_ranges,
        "updatedAt": str(data.get("updatedAt") or _now()),
    }


def _load_source_coverage(project_id: str, source_id: str | None = None) -> dict[str, Any]:
    from .episode_boundary_transaction import recover_episode_boundary_commit
    recover_episode_boundary_commit(project_id)
    path = _source_coverage_path(project_id)
    raw = _read_json(path, {})
    coverage = _normalize_source_coverage(project_id, raw, source_id)
    if not path.exists() or raw != coverage:
        _write_json(path, coverage)
    return coverage


def _write_source_coverage(project_id: str, coverage: dict[str, Any]) -> None:
    from .projects import _touch_project_meta
    coverage["updatedAt"] = _now()
    _write_json(_source_coverage_path(project_id), coverage)
    _touch_project_meta(project_id)


def _sync_source_coverage_targets(project_id: str, config: dict[str, Any] | None = None) -> None:
    from .project_management import get_project_business_config
    path = _source_coverage_path(project_id)
    if not path.exists():
        return
    try:
        coverage = _load_source_coverage(project_id)
    except ValueError:
        return
    config = config if isinstance(config, dict) else get_project_business_config(project_id)
    coverage.setdefault("episodeCursor", {})["targetUnits"] = _coverage_target_units(
        config,
        "episode_target_units",
        DEFAULT_EPISODE_TARGET_UNITS,
    )
    coverage.setdefault("assetCursor", {})["targetUnits"] = _coverage_target_units(
        config,
        "asset_extraction_target_units",
        DEFAULT_ASSET_EXTRACTION_TARGET_UNITS,
    )
    _write_source_coverage(project_id, coverage)


def _reset_source_planning_state(project_id: str) -> None:
    for path in (_source_index_path(project_id), _source_coverage_path(project_id)):
        if path.exists() and path.is_file():
            path.unlink()


def get_source_coverage(project_id: str, source_id: str | None = None) -> dict[str, Any]:
    from .source_text_store import _episode_source_rows, _is_novel_source, list_sources
    if not any(
        _is_novel_source(source)
        for source in (list_sources(project_id).get("sources") or [])
        if isinstance(source, dict)
    ):
        return {
            "success": True,
            "coverage": _new_source_coverage(project_id, ""),
            "episodeSources": [],
        }
    coverage = _load_source_coverage(project_id, source_id)
    return {
        "success": True,
        "coverage": coverage,
        "episodeSources": _episode_source_rows(project_id, coverage),
    }


def _asset_range_analysis_state(row: dict[str, Any]) -> str:
    return str(row.get("analysisStatus") or "").strip().lower()


def _asset_range_created_ids(row: dict[str, Any]) -> list[str]:
    values = row.get("createdAssetIds")
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _asset_range_bounds(row: dict[str, Any]) -> tuple[int, int]:
    try:
        start = int(row.get("absoluteStart") or 0)
        end = int(row.get("absoluteEnd") or 0)
    except (TypeError, ValueError):
        return 0, 0
    return start, end


def _asset_range_analysis_completed(row: dict[str, Any]) -> bool:
    return _asset_range_analysis_state(row) in _ASSET_RANGE_ANALYSIS_COMPLETED_STATUSES


def _blocking_asset_analysis_range(
    coverage: dict[str, Any],
    *,
    project_id: str = "",
    source_id: str,
    before_end: int | None = None,
) -> dict[str, Any] | None:
    rows: list[dict[str, Any]] = []
    for item in coverage.get("assetRanges", []):
        if not isinstance(item, dict):
            continue
        range_source_id = str(item.get("sourceId") or "").strip()
        if range_source_id != source_id:
            continue
        start, end = _asset_range_bounds(item)
        if end <= start:
            continue
        if before_end is not None and start >= before_end:
            continue
        if not _asset_range_analysis_completed(item):
            rows.append(item)
    if not rows:
        return None
    rows.sort(key=lambda item: (*_asset_range_bounds(item), str(item.get("rangeId") or "")))
    return rows[0]


def _asset_range_target_payload(row: dict[str, Any], source_id: str) -> dict[str, Any]:
    return {
        "sourceId": source_id,
        "rangeId": str(row.get("rangeId") or ""),
    }


def _asset_range_blocked_response(
    coverage: dict[str, Any],
    row: dict[str, Any],
    source_id: str,
) -> dict[str, Any]:
    start, end = _asset_range_bounds(row)
    state = _asset_range_analysis_state(row) or "committed"
    target_payload = _asset_range_target_payload(row, source_id)
    return {
        "success": False,
        "error": "asset_range_analysis_incomplete",
        "message": f"资产范围 {target_payload.get('rangeId') or ''} 已提交但拆分尚未完成，当前状态：{state}。请先完成该范围的资产拆分，再继续规划后续范围。",
        "requiresAssetExtraction": True,
        "assetRange": copy.deepcopy(row),
        "recommendedAction": "asset_extraction",
        "recommendedPayload": target_payload,
        "nextAllowedTools": ["get_source_coverage", "get_asset_extraction_context", "submit_asset_extraction_result"],
        "nextStep": {
            "requiresUserConfirmation": False,
            "message": "这段资产尚未拆分完成；读取已确认范围并继续拆分。",
            "nextAllowedTools": ["get_asset_extraction_context", "submit_asset_extraction_result"],
        },
        "coverage": coverage,
        "reason": f"资产范围 {start}-{end} 的语义拆分与审查尚未完成。",
    }


def _episode_asset_coverage_gap(
    coverage: dict[str, Any],
    *,
    project_id: str = "",
    source_id: str,
    start: int,
    required_end: int,
    total_chars: int,
) -> dict[str, Any] | None:
    asset_cursor = coverage.get("assetCursor") if isinstance(coverage.get("assetCursor"), dict) else {}
    try:
        asset_cursor_offset = int(asset_cursor.get("nextOffset") or 0)
    except (TypeError, ValueError):
        asset_cursor_offset = 0
    try:
        asset_target_units = int(asset_cursor.get("targetUnits") or DEFAULT_ASSET_EXTRACTION_TARGET_UNITS)
    except (TypeError, ValueError):
        asset_target_units = DEFAULT_ASSET_EXTRACTION_TARGET_UNITS
    asset_cursor_offset = max(0, min(total_chars, asset_cursor_offset))
    required_end = max(0, min(total_chars, int(required_end)))
    start = max(0, min(total_chars, int(start)))
    blocking_range = _blocking_asset_analysis_range(
        coverage,
        project_id=project_id,
        source_id=source_id,
        before_end=required_end,
    )
    if blocking_range:
        range_start, range_end = _asset_range_bounds(blocking_range)
        target_payload = _asset_range_target_payload(blocking_range, source_id)
        state = _asset_range_analysis_state(blocking_range) or "committed"
        return {
            "sourceId": source_id,
            "episodeStartOffset": start,
            "episodeRequiredEndOffset": required_end,
            "assetCursorOffset": asset_cursor_offset,
            "assetTargetUnits": asset_target_units,
            "missingUnits": max(0, required_end - min(asset_cursor_offset, range_end)),
            "blockingAssetRange": copy.deepcopy(blocking_range),
            "recommendedAction": "asset_extraction",
            "recommendedPayload": target_payload,
            "nextAllowedTools": ["get_source_coverage", "get_asset_extraction_context", "submit_asset_extraction_result"],
            "reason": (
                f"资产范围 {target_payload.get('rangeId') or ''} 覆盖 {range_start}-{range_end}，"
                f"但分析尚未完成，当前状态：{state}。"
            ),
        }
    if asset_cursor_offset >= required_end:
        return None
    missing_units = max(0, required_end - asset_cursor_offset)
    return {
        "sourceId": source_id,
        "episodeStartOffset": start,
        "episodeRequiredEndOffset": required_end,
        "assetCursorOffset": asset_cursor_offset,
        "assetTargetUnits": asset_target_units,
        "missingUnits": missing_units,
        "recommendedAssetRange": {
            "sourceId": source_id,
            "startOffset": asset_cursor_offset,
            "targetUnits": max(1, asset_target_units),
            "assetTypes": ["characters", "creatures", "scenes", "props"],
        },
        "reason": (
            f"当前资产拆分游标只覆盖到 {asset_cursor_offset}，"
            f"本次分集需要覆盖到 {required_end}。"
        ),
    }


def _asset_ranges_for_source_ref(project_id: str, source_ref: dict[str, Any] | None) -> list[dict[str, Any]]:
    ref = source_ref if isinstance(source_ref, dict) else {}
    source_id = str(ref.get("sourceId") or "").strip()
    start, end = _source_ref_bounds(ref)
    if not source_id or start is None or end is None or end <= start:
        return []
    coverage = _load_source_coverage(project_id, source_id)
    ranges: list[dict[str, Any]] = []
    for item in coverage.get("assetRanges", []):
        if not isinstance(item, dict):
            continue
        range_source_id = str(item.get("sourceId") or "").strip()
        if range_source_id != source_id:
            continue
        try:
            range_start = int(item.get("absoluteStart") or 0)
            range_end = int(item.get("absoluteEnd") or 0)
        except (TypeError, ValueError):
            continue
        if range_end <= range_start:
            continue
        if max(start, range_start) < min(end, range_end):
            ranges.append(copy.deepcopy(item))
    return sorted(
        ranges,
        key=lambda item: (
            int(item.get("absoluteStart") or 0),
            int(item.get("absoluteEnd") or 0),
            str(item.get("rangeId") or ""),
        ),
    )


def _episode_requires_asset_extraction_response(
    coverage: dict[str, Any],
    gap: dict[str, Any],
    *,
    genre_context: str = "",
    genre_context_policy: str = "",
) -> dict[str, Any]:
    recommended_action = str(gap.get("recommendedAction") or "asset_range_propose").strip() or "asset_range_propose"
    recommended_payload = gap.get("recommendedPayload")
    if not isinstance(recommended_payload, dict):
        recommended_payload = gap.get("recommendedAssetRange") if isinstance(gap.get("recommendedAssetRange"), dict) else {}
    next_allowed_tools = gap.get("nextAllowedTools")
    if not isinstance(next_allowed_tools, list) or not next_allowed_tools:
        next_allowed_tools = ["get_source_coverage", "get_asset_range_context", "submit_asset_range_candidate"]
    if recommended_action == "asset_extraction":
        next_step_message = "已确认的资产范围尚未拆分完成；读取该范围并继续拆分资产。"
        next_step_tools = ["get_asset_extraction_context", "submit_asset_extraction_result"]
        recovery_hint = "完成该范围的资产拆分后，再继续规划分集断点。"
    else:
        next_step_message = "先规划缺口资产范围；用户确认后提交该范围并完成角色、生物、场景和道具分析。"
        next_step_tools = ["get_asset_range_context", "submit_asset_range_candidate"]
        recovery_hint = "资产范围提交并保存资产后，再继续规划分集断点。"
    if recommended_action == "asset_extraction":
        message = f"{gap.get('reason')}请先完成该范围的资产拆分，再继续规划分集断点。"
    else:
        message = f"{gap.get('reason')}请先提交并拆分下一段资产范围，再继续规划分集断点。"
    response = {
        "success": False,
        "error": "asset_coverage_required",
        "message": message,
        "requiresAssetExtraction": True,
        "assetCoverage": gap,
        "recommendedAction": recommended_action,
        "recommendedPayload": recommended_payload,
        "nextAllowedTools": next_allowed_tools,
        "nextStep": {
            "requiresUserConfirmation": False,
            "message": next_step_message,
            "nextAllowedTools": next_step_tools,
        },
        "recoveryAdvice": {
            "reason": "分集规划不能越过已提交资产拆分游标，否则后续分镜会缺少该原文范围内的角色、生物、场景和道具基础资产。",
            "nextAllowedTools": next_allowed_tools,
            "hint": recovery_hint,
        },
        "coverage": coverage,
    }
    if genre_context:
        response["genreContext"] = genre_context
        response["genreContextPolicy"] = genre_context_policy
    return response


def _confirmed_asset_range(project_id: str, asset_range_id: str) -> dict[str, Any]:
    if not asset_range_id:
        raise ValueError("缺少 assetRangeId")
    coverage = _load_source_coverage(project_id)
    for item in coverage.get("assetRanges", []):
        if isinstance(item, dict) and str(item.get("rangeId") or "") == asset_range_id:
            return item
    raise ValueError("资产范围尚未提交")


def _source_refs_from_asset_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    refs = row.get("sourceRefs")
    if isinstance(refs, dict):
        return [refs]
    if isinstance(refs, list):
        return [item for item in refs if isinstance(item, dict)]
    return []


def _source_ref_bounds(ref: dict[str, Any]) -> tuple[int | None, int | None]:
    start_value = ref.get("absoluteStart")
    end_value = ref.get("absoluteEnd")
    try:
        start = int(start_value) if start_value is not None else None
        end = int(end_value) if end_value is not None else None
    except (TypeError, ValueError):
        return None, None
    return start, end


def _validate_asset_batch_refs_in_range(project_id: str, payload: dict[str, Any], asset_range_id: str) -> None:
    asset_range = _confirmed_asset_range(project_id, asset_range_id)
    range_source_id = str(asset_range.get("sourceId") or "")
    range_start = int(asset_range.get("absoluteStart") or 0)
    range_end = int(asset_range.get("absoluteEnd") or 0)
    for asset_type, label in (("characters", "角色"), ("creatures", "生物"), ("scenes", "场景"), ("props", "道具")):
        rows = payload.get(asset_type)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            refs = _source_refs_from_asset_row(row)
            if not refs:
                continue
            for ref in refs:
                ref_asset_range_id = str(ref.get("assetRangeId") or "")
                if ref_asset_range_id and ref_asset_range_id != asset_range_id:
                    raise ValueError(f"{label}资产第 {index} 条 sourceRefs 不属于当前资产范围")
                ref_source_id = str(ref.get("sourceId") or "")
                if not ref_source_id or ref_source_id != range_source_id:
                    raise ValueError(f"{label}资产第 {index} 条 sourceRefs 不属于当前资产范围源文件")
                start, end = _source_ref_bounds(ref)
                if start is None or end is None:
                    raise ValueError(f"{label}资产第 {index} 条 sourceRefs 缺少 absoluteStart/absoluteEnd")
                if start < range_start or end > range_end or end <= start:
                    raise ValueError(f"{label}资产第 {index} 条 sourceRefs 超出已提交资产范围")


def _asset_range_id_tokens(*values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        candidates = value if isinstance(value, (list, tuple, set)) else (value,)
        for candidate in candidates:
            token = str(candidate or "").strip()
            if token and token not in result:
                result.append(token)
    return result


def _stamp_asset_range_id(payload: dict[str, Any], asset_range_id: str) -> dict[str, Any]:
    stamped = copy.deepcopy(payload)
    for asset_type in ("characters", "creatures", "scenes", "props"):
        rows = stamped.get(asset_type)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            row["assetRangeIds"] = _asset_range_id_tokens(
                row.get("assetRangeIds"),
                row.get("assetRangeId"),
                asset_range_id,
            )
            row["assetRangeId"] = asset_range_id
            refs = _source_refs_from_asset_row(row)
            for ref in refs:
                ref.setdefault("assetRangeId", asset_range_id)
    return stamped


def _asset_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for asset_type in ("characters", "creatures", "scenes", "props"):
        rows = payload.get(asset_type)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            asset_id = str(row.get("assetId") or row.get("id") or row.get("name") or "").strip()
            if asset_id:
                ids.append(asset_id)
    return list(dict.fromkeys(ids))


def _append_created_asset_ids_to_range(project_id: str, asset_range_id: str, asset_ids: list[str]) -> None:
    if not asset_range_id or not asset_ids:
        return
    coverage = _load_source_coverage(project_id)
    changed = False
    for item in coverage.get("assetRanges", []):
        if not isinstance(item, dict) or str(item.get("rangeId") or "") != asset_range_id:
            continue
        existing = [str(value) for value in item.get("createdAssetIds", []) if str(value).strip()] if isinstance(item.get("createdAssetIds"), list) else []
        item["createdAssetIds"] = list(dict.fromkeys(existing + asset_ids))
        changed = True
        break
    if changed:
        _write_source_coverage(project_id, coverage)


def _refresh_created_asset_ids_for_range(project_id: str, asset_range_id: str) -> None:
    from .assets import _asset_store_path
    if not asset_range_id:
        return
    assets = _read_json(_asset_store_path("project", project_id), DEFAULT_ASSETS)
    created_ids: list[str] = []
    if isinstance(assets, dict):
        for asset_type in ("characters", "creatures", "scenes", "props"):
            rows = assets.get(asset_type)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                range_ids = _asset_range_id_tokens(
                    row.get("assetRangeIds"),
                    row.get("assetRangeId"),
                )
                if asset_range_id not in range_ids:
                    continue
                created_id = str(row.get("id") or row.get("assetId") or row.get("name") or "").strip()
                if created_id:
                    created_ids.append(created_id)
    created_ids = list(dict.fromkeys(created_ids))
    coverage = _load_source_coverage(project_id)
    changed = False
    for item in coverage.get("assetRanges", []):
        if not isinstance(item, dict) or str(item.get("rangeId") or "") != asset_range_id:
            continue
        if item.get("createdAssetIds") != created_ids:
            item["createdAssetIds"] = created_ids
            changed = True
        break
    if changed:
        _write_source_coverage(project_id, coverage)
