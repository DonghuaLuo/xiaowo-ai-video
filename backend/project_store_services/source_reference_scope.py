# -*- coding: utf-8 -*-
"""分集原文范围和稳定文本单元引用的盖章与校验。"""
from __future__ import annotations

from .source_coverage import _load_source_coverage
from .source_coverage import _source_ref_bounds
from .source_index import list_source_index
from typing import Any
import copy


def _episode_range_for_id(project_id: str, episode_id: str) -> dict[str, Any] | None:
    try:
        coverage = _load_source_coverage(project_id)
    except Exception:
        return None
    for item in coverage.get("episodeRanges", []):
        if isinstance(item, dict) and str(item.get("episodeId") or "") == episode_id:
            return item
    return None


def _source_ref_in_episode_range(ref: dict[str, Any], episode_id: str, episode_range: dict[str, Any] | None) -> bool:
    ref_episode_id = str(ref.get("episodeId") or ref.get("episode_id") or "")
    if ref_episode_id and ref_episode_id != episode_id:
        return False
    if not episode_range:
        return False
    start, end = _source_ref_bounds(ref)
    if start is None or end is None or end <= start:
        return False
    range_start = int(episode_range.get("absoluteStart") or 0)
    range_end = int(episode_range.get("absoluteEnd") or 0)
    ref_source_id = str(ref.get("sourceId") or ref.get("source_id") or "")
    range_source_id = str(episode_range.get("sourceId") or "")
    return bool(ref_source_id and range_source_id) and ref_source_id == range_source_id and range_start <= start and end <= range_end


def _source_ref_unit_ids(ref: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    if "sourceUnitId" in ref:
        values.append(ref.get("sourceUnitId"))
    if "source_unit_id" in ref:
        values.append(ref.get("source_unit_id"))
    unit_ids = ref.get("sourceUnitIds") if "sourceUnitIds" in ref else ref.get("source_unit_ids")
    if isinstance(unit_ids, list):
        values.extend(unit_ids)
    elif unit_ids is not None:
        values.append(unit_ids)
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _source_units_for_ref(
    project_id: str,
    ref: dict[str, Any],
    episode_range: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not episode_range:
        return []
    start, end = _source_ref_bounds(ref)
    if start is None or end is None or end <= start:
        return []
    range_source_id = str(episode_range.get("sourceId") or episode_range.get("source_id") or "")
    ref_source_id = str(ref.get("sourceId") or ref.get("source_id") or range_source_id)
    if not ref_source_id or ref_source_id != range_source_id:
        return []
    index = list_source_index(project_id).get("sourceIndex") or {}
    unit_rows = index.get("units") if isinstance(index, dict) else []
    candidates: list[dict[str, Any]] = []
    for unit in (unit_rows if isinstance(unit_rows, list) else []):
        if not isinstance(unit, dict) or str(unit.get("sourceId") or "") != ref_source_id:
            continue
        unit_start, unit_end = _source_ref_bounds(
            {
                "absoluteStart": unit.get("absoluteStart"),
                "absoluteEnd": unit.get("absoluteEnd"),
            }
        )
        if unit_start is None or unit_end is None or unit_end <= unit_start:
            continue
        if max(start, unit_start) < min(end, unit_end):
            candidates.append(unit)
    sentence_units = [
        unit
        for unit in candidates
        if str(unit.get("kind") or unit.get("type") or "").lower() == "sentence"
    ]
    selected = sentence_units or candidates
    return sorted(
        selected,
        key=lambda unit: (
            int(unit.get("absoluteStart") or 0),
            int(unit.get("absoluteEnd") or 0),
            str(unit.get("id") or ""),
        ),
    )


def _stamp_source_units_on_ref(
    project_id: str,
    episode_id: str,
    episode_range: dict[str, Any] | None,
    ref: dict[str, Any],
) -> None:
    if not episode_range:
        return
    ref.setdefault("episodeId", episode_id)
    ref.setdefault("sourceId", str(episode_range.get("sourceId") or episode_range.get("source_id") or ""))
    if _source_ref_unit_ids(ref):
        return
    units = _source_units_for_ref(project_id, ref, episode_range)
    unit_ids = [str(unit.get("id") or "").strip() for unit in units if str(unit.get("id") or "").strip()]
    if not unit_ids:
        return
    ref["sourceUnitIds"] = unit_ids
    ref["sourceUnitId"] = unit_ids[0]


def _source_ref_has_valid_unit_ref(
    project_id: str,
    ref: dict[str, Any],
    episode_range: dict[str, Any] | None,
) -> bool:
    provided = set(_source_ref_unit_ids(ref))
    if not provided:
        return False
    valid = {
        str(unit.get("id") or "").strip()
        for unit in _source_units_for_ref(project_id, ref, episode_range)
        if str(unit.get("id") or "").strip()
    }
    return bool(valid) and provided.issubset(valid)


def _stamp_source_units_on_source_refs(project_id: str, episode_id: str, item: dict[str, Any]) -> None:
    episode_range = _episode_range_for_id(project_id, episode_id)
    refs = _shot_source_refs(item)
    for ref in refs:
        _stamp_source_units_on_ref(project_id, episode_id, episode_range, ref)


def _stamp_source_units_on_shot_plan(project_id: str, episode_id: str, shot_plan: dict[str, Any]) -> dict[str, Any]:
    stamped = copy.deepcopy(shot_plan)
    for group_key in ("segments", "shots"):
        rows = stamped.get(group_key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                _stamp_source_units_on_source_refs(project_id, episode_id, row)
    return stamped


def _stamp_source_units_on_workflow(project_id: str, episode_id: str, workflow: dict[str, Any]) -> dict[str, Any]:
    stamped = copy.deepcopy(workflow)
    for node in (stamped.get("nodes", []) if isinstance(stamped.get("nodes"), list) else []):
        if not isinstance(node, dict):
            continue
        _stamp_source_units_on_source_refs(project_id, episode_id, node)
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if data:
            _stamp_source_units_on_source_refs(project_id, episode_id, data)
    return stamped


def _shot_source_refs(item: dict[str, Any]) -> list[dict[str, Any]]:
    refs = item.get("sourceRefs") if "sourceRefs" in item else item.get("source_refs")
    if isinstance(refs, dict):
        return [refs]
    if isinstance(refs, list):
        return [ref for ref in refs if isinstance(ref, dict)]
    return []


def _validate_shot_plan_source_refs(project_id: str, episode_id: str, shot_plan: dict[str, Any]) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    warnings: list[str] = []
    episode_range = _episode_range_for_id(project_id, episode_id)
    if not episode_range:
        blocking.append(f"{episode_id} 尚未提交分集原文范围，不能保存镜头策略")
        return blocking, warnings
    for group_key, label in (("segments", "镜头段"), ("shots", "镜头")):
        rows = shot_plan.get(group_key)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            refs = _shot_source_refs(row)
            if not refs:
                blocking.append(f"{label}第 {index} 条缺少 sourceRefs")
                continue
            for ref in refs:
                if not _source_ref_in_episode_range(ref, episode_id, episode_range):
                    blocking.append(f"{label}第 {index} 条 sourceRefs 不属于 {episode_id} 原文范围")
                    continue
                if not _source_ref_has_valid_unit_ref(project_id, ref, episode_range):
                    blocking.append(f"{label}第 {index} 条 sourceRefs 缺少有效 sourceUnitId/sourceUnitIds")
    return blocking, warnings
