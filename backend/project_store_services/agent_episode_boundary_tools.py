# -*- coding: utf-8 -*-
"""Minimal scoped source window for planning the next episode boundary."""
from __future__ import annotations

from typing import Any
import copy

from utils.text_metrics import content_offset_after_units

from .catalogs import DEFAULT_EPISODE_TARGET_UNITS
from .source_boundary_contract import (
    _episode_boundary_asset_cursor_end,
    _episode_boundary_planning_window_end,
    _episode_boundary_tolerance_units,
    _next_episode_id,
)
from .source_coverage import _episode_asset_coverage_gap, _load_source_coverage
from .source_text_store import _read_source_content, _select_project_sources
from .project_resource_revisions import _json_hash


def episode_boundary_inputs(project_id: str, episode_id: str = "") -> dict[str, Any]:
    coverage = _load_source_coverage(project_id)
    source_id = str(coverage.get("sourceId") or "")
    source = _select_project_sources(project_id, source_id)[0]
    content = _read_source_content(project_id, source)
    cursor = coverage.get("episodeCursor") if isinstance(coverage.get("episodeCursor"), dict) else {}
    current = None
    if episode_id:
        current = next((row for row in coverage.get("episodeRanges", [])
                        if isinstance(row, dict) and row.get("episodeId") == episode_id), None)
        if current is None:
            raise ValueError(f"未找到已保存的分集 {episode_id}；请核对目标，不改为规划下一集")
    start = int(current.get("absoluteStart") or 0) if current else int(cursor.get("nextOffset") or 0)
    start = max(0, min(len(content), start))
    target = max(1, int(cursor.get("targetUnits") or DEFAULT_EPISODE_TARGET_UNITS))
    if start >= len(content):
        raise ValueError("分集游标已到达源文件末尾")
    tolerance = _episode_boundary_tolerance_units({}, target)
    preferred = content_offset_after_units(content, start, target)
    asset_end = _episode_boundary_asset_cursor_end(coverage, len(content))
    upper = content_offset_after_units(content, start, target + tolerance)
    if asset_end > start:
        upper = min(upper, asset_end)
    end = _episode_boundary_planning_window_end(content, start, target, tolerance, upper)
    read_end = max(end, content_offset_after_units(content, start, target + tolerance),
                   int((current or {}).get("absoluteEnd") or 0))
    return {"coverage": coverage, "sourceId": source_id, "content": content, "start": start,
            "targetUnits": target, "boundaryToleranceUnits": tolerance, "preferredEnd": preferred,
            "planningWindowEnd": end, "assetCoverageEnd": asset_end,
            "minBoundaryEnd": min(end, content_offset_after_units(content, start, max(1, target - tolerance))),
            "episodeId": episode_id or _next_episode_id(coverage), "currentEpisode": copy.deepcopy(current),
            "sourceWindowEnd": min(len(content), read_end)}


def episode_boundary_context_version(data: dict[str, Any]) -> str:
    return _json_hash({"coverage": data["coverage"], "content": data["content"],
                      "targetUnits": data["targetUnits"], "episodeId": data["episodeId"],
                      "currentEpisode": data["currentEpisode"]})


def assert_episode_revision_safe(project_id: str, coverage: dict[str, Any], episode_id: str,
                                 end: int) -> None:
    """Metadata-only edits preserve dependencies; boundary edits never delete them."""
    rows = [row for row in coverage.get("episodeRanges", []) if isinstance(row, dict)]
    current = next((row for row in rows if row.get("episodeId") == episode_id), None)
    if current is None or int(current.get("absoluteEnd") or 0) == end:
        return
    if not rows or rows[-1].get("episodeId") != episode_id:
        raise ValueError("该集已有后续分集，调整断点会影响连续原文；请先明确处理后续依赖，本轮不覆盖")
    from .agent_sessions import _project_dir
    from .canvas_store_queries import read_canvas_workflow_projection_v4
    root = _project_dir(project_id)
    episode_dir = root / "episodes" / episode_id
    if episode_dir.is_dir() and any(path.name not in {"source.txt", "source_ref.json"}
                                   for path in episode_dir.iterdir()):
        raise ValueError("该集已有下游资料，不能直接改动断点；原集稿和下游保持不变")
    if (root / "canvas_v4.sqlite3").is_file():
        workflow = read_canvas_workflow_projection_v4(project_id, episode_id)
        if workflow.get("nodes") or workflow.get("workChains"):
            raise ValueError("该集已有画布工作链，不能直接改动断点；原集稿和下游保持不变")


def get_episode_boundary_context(project_id: str, *, part: str, episode_id: str = "") -> dict[str, Any]:
    """Return either the allowed prose or its planning state, never both."""
    if part not in {"source_text", "planning_state", "continuation_text"}:
        return {"success": False, "status": "blocked", "code": "invalid_part",
                "reason": "请选择下一集原文或断点规划状态"}
    try:
        data = episode_boundary_inputs(project_id, episode_id)
        coverage, content, source_id = data["coverage"], data["content"], data["sourceId"]
        start, preferred_end = data["start"], data["preferredEnd"]
        gap = _episode_asset_coverage_gap(
            coverage, project_id=project_id, source_id=source_id,
            start=start, required_end=preferred_end, total_chars=len(content),
        )
        if gap:
            return {"success": False, "status": "blocked", "code": "asset_coverage_gap",
                    "reason": str(gap.get("reason") or "资产分析尚未覆盖本集目标范围"),
                    "episodeStart": start, "requiredEnd": preferred_end,
                    "assetCoverageEnd": gap.get("assetCursorOffset")}
        end, asset_end = data["planningWindowEnd"], data["assetCoverageEnd"]
        if end <= start:
            return {"success": False, "status": "blocked", "code": "asset_coverage_gap",
                    "reason": "资产分析覆盖不足，无法规划下一集断点",
                    "episodeStart": start, "requiredEnd": preferred_end,
                    "assetCoverageEnd": asset_end}
        version = episode_boundary_context_version(data)
        target = {"episodeId": data["episodeId"], "absoluteStart": start}
        if part == "source_text":
            # A saved episode can extend beyond a newly reduced target. Expose
            # its source too, so metadata-only feedback does not truncate it.
            read_end = data["sourceWindowEnd"]
            return {"success": True, "contextVersion": version, "target": target, "sourceText": content[start:read_end]}
        if part == "continuation_text":
            continuation_start = data["sourceWindowEnd"]
            continuation_end = content_offset_after_units(content, continuation_start, 750)
            return {"success": True, "contextVersion": version, "target": target, "continuationText": content[continuation_start:continuation_end]}
        return {"success": True, "contextVersion": version, "target": target, "planningState": {
            "sourceId": source_id, "episodeId": data["episodeId"],
            "absoluteStart": start, "preferredEnd": preferred_end,
            "minBoundaryEnd": data["minBoundaryEnd"],
            "planningWindowEnd": end, "targetUnits": data["targetUnits"],
            "sourceWindowEnd": data["sourceWindowEnd"],
            "boundaryToleranceUnits": data["boundaryToleranceUnits"],
            "currentEpisode": data["currentEpisode"],
        }}
    except (ValueError, FileNotFoundError, IndexError, TypeError) as exc:
        return {"success": False, "status": "blocked", "code": "source_unavailable",
                "reason": str(exc)}
