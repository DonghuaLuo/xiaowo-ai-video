# -*- coding: utf-8 -*-
"""资产提取证据、范围绑定、复用名称与别名归并。"""
from __future__ import annotations

from .asset_text_contract import _merge_agent_asset_source_refs
from .planning_contract import _is_user_locked_item
from .source_coverage import _asset_range_id_tokens
from .source_coverage import _asset_ranges_for_source_ref
from .source_coverage import _confirmed_asset_range
from .source_coverage import _source_ref_bounds
from .source_coverage import _source_refs_from_asset_row
from .source_text_store import _read_source_content
from .source_text_store import _select_project_sources
from .splitting_templates import _string_list
from .store_core import _asset_is_offline
from .video_task_card_references import _ASSET_REF_COLLECTIONS
from typing import Any
import copy
import json
import re
import traceback


def _asset_range_id_from_source_refs(project_id: str, row: dict[str, Any]) -> str:
    refs = _source_refs_from_asset_row(row)
    if not refs:
        return ""
    range_ids: list[str] = []
    for ref in refs:
        for range_row in _asset_ranges_for_source_ref(project_id, ref):
            range_id = str(range_row.get("rangeId") or range_row.get("range_id") or "").strip()
            if range_id and range_id not in range_ids:
                range_ids.append(range_id)
    if len(range_ids) == 1:
        return range_ids[0]
    if len(range_ids) > 1:
        raise ValueError("资产 sourceRefs 跨多个资产分组，请明确传入 assetRangeId")
    raise ValueError("无法根据资产 sourceRefs 匹配已提交的资产分组")


def _find_asset_evidence_range_in_text(source_text: str, excerpt: str) -> tuple[int, int, str] | None:
    text = str(excerpt or "").strip()
    if not source_text or not text:
        return None
    local_start = source_text.find(text)
    if local_start >= 0:
        return local_start, local_start + len(text), text

    compact_text = re.sub(r"\s+", "", text)
    if compact_text:
        compact_parts: list[str] = []
        compact_positions: list[int] = []
        for index, char in enumerate(source_text):
            if char.isspace():
                continue
            compact_parts.append(char)
            compact_positions.append(index)
        compact_source = "".join(compact_parts)
        compact_start = compact_source.find(compact_text)
        if compact_start >= 0:
            compact_end = compact_start + len(compact_text)
            local_start = compact_positions[compact_start]
            local_end = compact_positions[compact_end - 1] + 1
            return local_start, local_end, source_text[local_start:local_end]

    parts = [part for part in re.split(r"\s+", text) if part]
    if len(parts) <= 1:
        return None
    match = re.search(r"\s+".join(re.escape(part) for part in parts), source_text)
    if not match:
        return None
    return match.start(), match.end(), source_text[match.start() : match.end()]


def _source_window_for_asset_range(project_id: str, asset_range_id: str) -> tuple[str, int, int, str]:
    range_row = _confirmed_asset_range(project_id, asset_range_id)
    source_id = str(range_row.get("sourceId") or range_row.get("source_id") or "").strip()
    if not source_id:
        return "", 0, 0, ""
    try:
        start = int(range_row.get("absoluteStart") or range_row.get("startOffset") or 0)
        end = int(range_row.get("absoluteEnd") or range_row.get("endOffset") or 0)
    except (TypeError, ValueError):
        return source_id, 0, 0, ""
    source = _select_project_sources(project_id, source_id)[0]
    content = _read_source_content(project_id, source)
    return source_id, start, end, content[start:end]


def _source_refs_from_coverage_row(
    project_id: str,
    asset_range_id: str,
    row: dict[str, Any],
) -> list[dict[str, Any]]:
    refs = _source_refs_from_asset_row(row)
    if refs:
        try:
            source_id, range_start, range_end, _source_text = _source_window_for_asset_range(
                project_id,
                asset_range_id,
            )
        except Exception:
            print(traceback.format_exc(), flush=True)
            return []
        if not source_id or range_end <= range_start:
            return []
        stamped_refs: list[dict[str, Any]] = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            ref_asset_range_id = str(ref.get("assetRangeId") or ref.get("asset_range_id") or "").strip()
            if ref_asset_range_id and ref_asset_range_id != asset_range_id:
                continue
            ref_source_id = str(ref.get("sourceId") or ref.get("source_id") or "").strip()
            if ref_source_id and ref_source_id != source_id:
                continue
            ref_start, ref_end = _source_ref_bounds(ref)
            if ref_start is None or ref_end is None:
                continue
            if ref_start < range_start or ref_end > range_end or ref_end <= ref_start:
                continue
            next_ref = copy.deepcopy(ref)
            next_ref["sourceId"] = ref_source_id or source_id
            next_ref["assetRangeId"] = asset_range_id
            stamped_refs.append(next_ref)
        return _merge_agent_asset_source_refs(stamped_refs)
    evidence_rows = row.get("sourceEvidence") or row.get("source_evidence")
    evidence_values = evidence_rows if isinstance(evidence_rows, list) else [evidence_rows] if evidence_rows not in (None, "") else []
    evidence = [str(item or "").strip() for item in evidence_values if str(item or "").strip()]
    try:
        source_id, start, _end, source_text = _source_window_for_asset_range(project_id, asset_range_id)
    except Exception:
        print(traceback.format_exc(), flush=True)
        return []
    if not source_id or not source_text:
        return []
    result: list[dict[str, Any]] = []
    for excerpt in evidence[:3]:
        located = _find_asset_evidence_range_in_text(source_text, excerpt)
        if not located:
            continue
        local_start, local_end, source_preview = located
        result.append(
            {
                "sourceId": source_id,
                "absoluteStart": start + local_start,
                "absoluteEnd": start + local_end,
                "sourcePreview": source_preview,
                "assetRangeId": asset_range_id,
            }
        )
    if not result:
        result.append({
            "sourceId": source_id,
            "absoluteStart": start,
            "absoluteEnd": _end,
            "assetRangeId": asset_range_id,
            "sourcePreview": "",
            "precision": "range",
        })
    return _merge_agent_asset_source_refs(result)


def _attach_asset_range_metadata_to_item(
    item: dict[str, Any],
    asset_range_id: str,
    *,
    source_refs: Any = None,
) -> bool:
    if not isinstance(item, dict) or not asset_range_id:
        return False
    before = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    range_ids = _asset_range_id_tokens(
        item.get("assetRangeIds"),
        item.get("asset_range_ids"),
        item.get("assetRangeId"),
        item.get("asset_range_id"),
        asset_range_id,
    )
    if range_ids:
        item["assetRangeIds"] = range_ids
        item["assetRangeId"] = asset_range_id
    stamped_refs: list[dict[str, Any]] = []
    for ref in source_refs if isinstance(source_refs, list) else []:
        if not isinstance(ref, dict):
            continue
        next_ref = copy.deepcopy(ref)
        next_ref["assetRangeId"] = str(next_ref.get("assetRangeId") or next_ref.get("asset_range_id") or asset_range_id)
        stamped_refs.append(next_ref)
    merged_refs = _merge_agent_asset_source_refs(
        item.get("sourceRefs") or item.get("source_refs"),
        stamped_refs,
    )
    if merged_refs:
        item["sourceRefs"] = merged_refs
    after = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return before != after


def _coverage_row_reuses_existing_asset(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").strip()
    decision = str(row.get("decision") or "").strip()
    return bool(str(row.get("assetId") or row.get("asset_id") or "").strip()) and (
        status == "reused" or decision == "reuse_existing"
    )


def _attach_reused_asset_ranges_from_coverage(
    project_id: str,
    assets: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, int]:
    from .assets import _normalize_asset_item_for_storage
    asset_range_id = str(payload.get("assetRangeId") or payload.get("asset_range_id") or "").strip()
    if not asset_range_id:
        return {}
    _confirmed_asset_range(project_id, asset_range_id)
    counts: dict[str, int] = {}
    for asset_type in _ASSET_REF_COLLECTIONS:
        rows = _asset_coverage_rows_for_type(payload, asset_type)
        if not rows:
            continue
        existing_rows = assets.get(asset_type)
        if not isinstance(existing_rows, list):
            continue
        existing_by_id = {
            str(item.get("id") or "").strip(): item
            for item in existing_rows
            if isinstance(item, dict)
            and not _asset_is_offline(item)
            and str(item.get("id") or "").strip()
        }
        updated = 0
        for row in rows:
            if not isinstance(row, dict) or not _coverage_row_reuses_existing_asset(row):
                continue
            asset_id = str(row.get("assetId") or row.get("asset_id") or "").strip()
            existing = existing_by_id.get(asset_id)
            if not isinstance(existing, dict):
                continue
            source_refs = _source_refs_from_coverage_row(project_id, asset_range_id, row)
            if _attach_asset_range_metadata_to_item(
                existing,
                asset_range_id,
                source_refs=source_refs,
            ):
                _normalize_asset_item_for_storage(project_id, existing)
                updated += 1
        if updated:
            counts[asset_type] = updated
    return counts


def _asset_coverage_rows_for_type(payload: dict[str, Any], asset_type: str) -> list[dict[str, Any]]:
    table = payload.get("assetCoverageTable") or payload.get("asset_coverage_table")
    if not isinstance(table, dict):
        return []
    table_types = table.get("assetTypes") or table.get("asset_types")
    if not isinstance(table_types, dict):
        return []
    rows = table_types.get(asset_type)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _coverage_alias_kind_allows_canonical(value: Any) -> bool:
    normalized = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    return normalized in {
        "proper_name",
        "formal_name",
        "true_name",
        "canonical_name",
    }


def _coverage_canonical_name_from_row(row: dict[str, Any]) -> str:
    if not isinstance(row, dict):
        return ""
    canonical_kind = (
        row.get("canonicalKind")
        or row.get("canonical_kind")
        or row.get("aliasKind")
        or row.get("alias_kind")
        or ""
    )
    if not _coverage_alias_kind_allows_canonical(canonical_kind):
        return ""
    for key in ("canonicalName", "canonical_name", "promoteName", "promote_name"):
        value = str(row.get(key) or "").strip()
        if value and len(value) <= 80:
            return value
    return ""


def _promote_reused_asset_canonical_names_from_coverage(assets: dict[str, Any], payload: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for asset_type in _ASSET_REF_COLLECTIONS:
        rows = _asset_coverage_rows_for_type(payload, asset_type)
        if not rows:
            continue
        existing_rows = assets.get(asset_type)
        if not isinstance(existing_rows, list):
            continue
        existing_by_id = {
            str(item.get("id") or "").strip(): item
            for item in existing_rows
            if isinstance(item, dict) and not _asset_is_offline(item) and str(item.get("id") or "").strip()
        }
        name_owner = {
            str(item.get("name") or item.get("title") or "").strip().casefold(): str(item.get("id") or "").strip()
            for item in existing_rows
            if isinstance(item, dict)
            and not _asset_is_offline(item)
            and str(item.get("id") or "").strip()
            and str(item.get("name") or item.get("title") or "").strip()
        }
        updated = 0
        for row in rows:
            status = str(row.get("status") or "").strip()
            decision = str(row.get("decision") or "").strip()
            if status != "reused" and decision != "reuse_existing":
                continue
            asset_id = str(row.get("assetId") or row.get("asset_id") or "").strip()
            existing = existing_by_id.get(asset_id)
            if not existing or _is_user_locked_item(existing):
                continue
            canonical_name = _coverage_canonical_name_from_row(row)
            canonical_key = canonical_name.casefold()
            existing_name = str(existing.get("name") or existing.get("title") or "").strip()
            existing_key = existing_name.casefold()
            if not canonical_name or canonical_key == existing_key:
                continue
            owner_id = name_owner.get(canonical_key)
            if owner_id and owner_id != asset_id:
                continue
            existing_aliases = _string_list(existing.get("aliases"))
            next_aliases: list[str] = []
            alias_keys: set[str] = set()
            for existing_alias in existing_aliases:
                alias_key = existing_alias.casefold()
                if not alias_key or alias_key == canonical_key or alias_key in alias_keys:
                    continue
                next_aliases.append(existing_alias)
                alias_keys.add(alias_key)
            if existing_name and existing_key not in alias_keys and existing_key != canonical_key:
                next_aliases.append(existing_name)
                alias_keys.add(existing_key)
            for alias_value in (
                row.get("aliasName"),
                row.get("alias_name"),
                row.get("originalName"),
                row.get("original_name"),
            ):
                alias = str(alias_value or "").strip()
                alias_key = alias.casefold()
                if not alias or len(alias) > 80 or alias_key == canonical_key or alias_key in alias_keys:
                    continue
                next_aliases.append(alias)
                alias_keys.add(alias_key)
            existing["name"] = canonical_name
            if next_aliases != existing_aliases:
                existing["aliases"] = next_aliases
            if existing_key in name_owner:
                name_owner.pop(existing_key, None)
            name_owner[canonical_key] = asset_id
            updated += 1
        if updated:
            counts[asset_type] = updated
    return counts


def _merge_reused_asset_aliases_from_coverage(assets: dict[str, Any], payload: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for asset_type in _ASSET_REF_COLLECTIONS:
        rows = _asset_coverage_rows_for_type(payload, asset_type)
        if not rows:
            continue
        existing_rows = assets.get(asset_type)
        if not isinstance(existing_rows, list):
            continue
        existing_by_id = {
            str(item.get("id") or "").strip(): item
            for item in existing_rows
            if isinstance(item, dict) and not _asset_is_offline(item) and str(item.get("id") or "").strip()
        }
        updated = 0
        for row in rows:
            status = str(row.get("status") or "").strip()
            decision = str(row.get("decision") or "").strip()
            if status != "reused" and decision != "reuse_existing":
                continue
            asset_id = str(row.get("assetId") or row.get("asset_id") or "").strip()
            existing = existing_by_id.get(asset_id)
            if not existing or _is_user_locked_item(existing):
                continue
            alias_kind = str(
                row.get("aliasKind")
                or row.get("alias_kind")
                or row.get("aliasType")
                or row.get("alias_type")
                or ""
            ).strip().casefold().replace("-", "_").replace(" ", "_")
            alias_is_stable = bool(row.get("aliasIsStable") or row.get("alias_is_stable"))
            allowed_alias_kinds = {
                "proper_name",
                "formal_name",
                "stable_alias",
                "true_name",
                "canonical_alias",
                "专名",
                "真实姓名",
                "正式名称",
                "稳定别名",
            }
            if not alias_is_stable and alias_kind not in allowed_alias_kinds:
                continue
            existing_name = str(existing.get("name") or existing.get("title") or "").strip()
            existing_aliases = _string_list(existing.get("aliases"))
            existing_keys = {
                value.casefold()
                for value in [existing_name, *existing_aliases]
                if value
            }
            alias_values = [
                row.get("aliasName"),
                row.get("alias_name"),
            ]
            next_aliases = list(existing_aliases)
            for alias_value in alias_values:
                alias = str(alias_value or "").strip()
                alias_key = alias.casefold()
                if not alias or len(alias) > 80 or alias_key in existing_keys:
                    continue
                next_aliases.append(alias)
                existing_keys.add(alias_key)
            if next_aliases != existing_aliases:
                existing["aliases"] = next_aliases
                updated += 1
        if updated:
            counts[asset_type] = updated
    return counts
