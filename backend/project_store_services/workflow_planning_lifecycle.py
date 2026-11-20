# -*- coding: utf-8 -*-
"""项目来源与分镜规划派生数据的生命周期管理。

本模块负责删除来源、分集规划输出及其派生画布资源。
实现依赖按职责从来源、项目、存储和画布运行时模块显式导入。
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any

from .agent_sessions import _project_dir, _project_meta_path
from .agent_session_policy import latest_project_episode_id as _policy_latest_project_episode_id
from .canvas_store_documents import delete_episode_canvas_v4
from .project_resource_revisions import _append_resource_revision, _resource_revision_value
from .source_text_store import _is_novel_source, _source_collection_title, _source_refs_for_meta, list_sources
from .source_coverage import _load_source_coverage, _reset_source_planning_state, _source_coverage_path, _write_source_coverage
from .source_index import _source_index_path, build_source_index
from .project_overview import _sync_project_theme_visual_context
from .store_core import (
    _assert_explicit_delete_all_confirmed,
    _now,
    _read_json,
    _write_json,
)



def delete_source(project_id: str, source_id: str) -> dict[str, Any]:
    current_sources = list_sources(project_id)["sources"]
    removed = next((item for item in current_sources if item.get("id") == source_id), None)
    removed_is_novel = isinstance(removed, dict) and _is_novel_source(removed)
    if isinstance(removed, dict):
        content_path = str(removed.get("contentPath") or removed.get("content_path") or "").strip()
        if content_path:
            path = _project_dir(project_id) / "sources" / content_path
            if path.exists() and path.is_file():
                path.unlink()
    sources = [item for item in current_sources if item.get("id") != source_id]
    _write_json(_project_dir(project_id) / "sources" / "sources.json", sources)
    meta = _read_json(_project_meta_path(project_id), {})
    novel_sources: list[dict[str, Any]] = []
    if removed_is_novel:
        novel_sources = [
            item
            for item in sources
            if isinstance(item, dict) and _is_novel_source(item)
        ]
        meta.pop("overview_analysis", None)
        _sync_project_theme_visual_context(project_id, meta, "")
        source_refs = _source_refs_for_meta(novel_sources)
        meta["source_count"] = len(novel_sources)
        meta["sources"] = source_refs
        if source_refs:
            current_source_id = str((meta.get("source") or {}).get("id") or "")
            meta["source"] = next(
                (ref for ref in source_refs if ref.get("id") == current_source_id),
                source_refs[0],
            )
            meta["summary"] = f"已删除小说文本，当前剩余{_source_collection_title(novel_sources)}，等待重新分析"
            meta["status"] = "小说文本已变更，等待分析概述"
            meta["status_type"] = "running"
        else:
            meta.pop("source", None)
            meta["summary"] = "尚未添加小说文本"
            meta["status"] = "等待添加小说文本"
            meta["status_type"] = "draft"
    meta["updated_at"] = _now()
    _write_json(_project_meta_path(project_id), meta)
    if removed_is_novel:
        _reset_source_planning_state(project_id)
    if removed_is_novel and novel_sources:
        build_source_index(project_id)
        _load_source_coverage(project_id)
    return {"success": True}


_ALL_PLANNING_DELETE_TARGETS = {"source_index", "source_splits", "asset_ranges", "storyboards"}
_EPISODE_PLANNING_DELETE_TARGETS = {"source_splits", "storyboards"}
_GLOBAL_PLANNING_DELETE_TARGETS = {"source_index", "asset_ranges"}
_EPISODE_STORYBOARD_DERIVED_FILENAMES = (
    "work_chain_plan.json",
    "workflow_tasks.json",
    "workflow.json",
    "versions.json",
    "workflow_media.json",
    "episode_production_status.json",
    "review_results.json",
    "variant_quality_results.json",
    "node_edit_history.json",
)
_EPISODE_STORYBOARD_DERIVED_DIRNAMES = (
    "canvas",
    "cards",
    "results",
)


def _safe_episode_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text in {".", ".."} or "/" in text or "\\" in text or ":" in text:
        raise ValueError(f"分集 ID 无效：{text}")
    return text


def _delete_planning_targets(value: Any, *, default_targets: set[str] | None = None) -> set[str]:
    default_targets = set(default_targets or _ALL_PLANNING_DELETE_TARGETS)
    if value in (None, ""):
        return set(default_targets)
    rows = value if isinstance(value, list) else [value]
    if not rows:
        return set(default_targets)
    aliases = {
        "source": "source_splits",
        "sources": "source_splits",
        "source_split": "source_splits",
        "source_splits": "source_splits",
        "episode": "source_splits",
        "episodes": "source_splits",
        "episode_boundary": "source_splits",
        "episode_boundaries": "source_splits",
        "分集": "source_splits",
        "原文": "source_splits",
        "asset_range": "asset_ranges",
        "asset_ranges": "asset_ranges",
        "资产范围": "asset_ranges",
        "资产拆分": "asset_ranges",
        "storyboard": "storyboards",
        "storyboards": "storyboards",
        "shot_plan": "storyboards",
        "shot_plans": "storyboards",
        "workflow": "storyboards",
        "workflows": "storyboards",
        "分镜": "storyboards",
        "故事版": "storyboards",
        "画布": "storyboards",
        "source_index": "source_index",
        "index": "source_index",
        "索引": "source_index",
        "all": "all",
        "*": "all",
        "全部": "all",
        "所有": "all",
    }
    selected: set[str] = set()
    unknown: list[str] = []
    for item in rows:
        key = str(item or "").strip()
        if not key:
            continue
        normalized = aliases.get(key) or aliases.get(key.casefold())
        if normalized == "all":
            return set(_ALL_PLANNING_DELETE_TARGETS)
        if normalized:
            selected.add(normalized)
        else:
            unknown.append(key)
    if unknown:
        raise ValueError(f"无法识别的规划删除目标：{', '.join(unknown)}")
    return selected or set(default_targets)


def _episode_ids_from_payload(value: Any) -> list[str]:
    rows = value if isinstance(value, list) else [value] if value else []
    result: list[str] = []
    for item in rows:
        text = _safe_episode_id(item)
        if text and text not in result:
            result.append(text)
    return result


def _project_episode_ids(project_id: str, coverage: dict[str, Any] | None = None) -> list[str]:
    result: list[str] = []
    if isinstance(coverage, dict):
        for item in coverage.get("episodeRanges") or []:
            if not isinstance(item, dict):
                continue
            episode_id = str(item.get("episodeId") or item.get("episode_id") or "").strip()
            if episode_id and episode_id not in result:
                result.append(episode_id)
    meta = _read_json(_project_meta_path(project_id), {})
    for item in meta.get("episodes") or []:
        if not isinstance(item, dict):
            continue
        episode_id = str(item.get("id") or item.get("episodeId") or "").strip()
        if episode_id and episode_id not in result:
            result.append(episode_id)
    episodes_dir = _project_dir(project_id) / "episodes"
    if episodes_dir.exists() and episodes_dir.is_dir():
        for path in sorted(episodes_dir.iterdir()):
            if path.is_dir() and path.name not in result:
                result.append(path.name)
    return result


def _latest_project_episode_id(project_id: str) -> str:
    return _policy_latest_project_episode_id(project_id)


def _assert_source_split_delete_targets_latest_episode(
    project_id: str,
    *,
    targets: set[str],
    requested_episode_ids: list[str],
) -> None:
    if "source_splits" not in targets or not requested_episode_ids:
        return
    latest_episode_id = _latest_project_episode_id(project_id)
    if not latest_episode_id:
        raise ValueError("当前没有可删除的最新分集")
    if len(requested_episode_ids) != 1 or requested_episode_ids[0] != latest_episode_id:
        raise ValueError(f"只能删除最新一集（{latest_episode_id}），请按倒序删除分集")


def _source_hierarchy_manifest(project_id: str, source_index: Any | None = None) -> dict[str, Any]:
    sources = list_sources(project_id).get("sources") or []
    index = source_index if isinstance(source_index, dict) else _read_json(_source_index_path(project_id), {})
    if not isinstance(index, dict):
        index = {}
    chapter_index = index.get("chapterIndex") if isinstance(index.get("chapterIndex"), list) else []
    units = index.get("units") if isinstance(index.get("units"), list) else []
    return {
        "level1": {
            "label": "第一层：用户导入的原始小说文件",
            "resource": "sources/sources.json + sources/*.txt",
            "sources": [
                {
                    "sourceId": str(item.get("id") or ""),
                    "title": str(item.get("title") or "小说文本"),
                    "relativePath": str(item.get("relativePath") or ""),
                    "contentPath": str(item.get("contentPath") or item.get("content_path") or ""),
                }
                for item in sources
                if isinstance(item, dict)
            ],
        },
        "level2": {
            "label": "第二层：章节索引",
            "resource": "source_index.json: chapterIndex[]",
            "count": len(chapter_index),
            "sourceIds": sorted(
                {
                    str(item.get("sourceId") or "")
                    for item in chapter_index
                    if isinstance(item, dict) and str(item.get("sourceId") or "").strip()
                }
            ),
        },
        "level3": {
            "label": "第三层：段落/句子单元索引",
            "resource": "source_index.json: units[]",
            "count": len(units),
            "sourceIds": sorted(
                {
                    str(item.get("sourceId") or "")
                    for item in units
                    if isinstance(item, dict) and str(item.get("sourceId") or "").strip()
                }
            ),
        },
        "episodeDerivedFiles": {
            "label": "分集派生原文",
            "resource": "episodes/<episodeId>/source_ref.json + source.txt",
        },
    }


def _delete_episode_directory(project_id: str, episode_id: str) -> bool:
    safe_episode_id = _safe_episode_id(episode_id)
    if not safe_episode_id:
        return False
    episodes_root = (_project_dir(project_id) / "episodes").resolve()
    episode_path = (episodes_root / safe_episode_id).resolve()
    try:
        episode_path.relative_to(episodes_root)
    except ValueError:
        return False
    if episode_path == episodes_root:
        return False
    if episode_path.exists() and episode_path.is_dir():
        shutil.rmtree(episode_path)
        return True
    return False


def _delete_episode_storyboard_files(project_id: str, episode_id: str) -> dict[str, Any]:
    safe_episode_id = _safe_episode_id(episode_id)
    if not safe_episode_id:
        return {
            "deletedCount": 0,
            "deletedFileCount": 0,
            "deletedDirectoryCount": 0,
            "deletedFiles": [],
            "deletedDirectories": [],
        }
    episodes_root = (_project_dir(project_id) / "episodes").resolve()
    episode_dir = (episodes_root / safe_episode_id).resolve()
    try:
        episode_dir.relative_to(episodes_root)
    except ValueError:
        return {
            "deletedCount": 0,
            "deletedFileCount": 0,
            "deletedDirectoryCount": 0,
            "deletedFiles": [],
            "deletedDirectories": [],
        }
    if episode_dir == episodes_root:
        return {
            "deletedCount": 0,
            "deletedFileCount": 0,
            "deletedDirectoryCount": 0,
            "deletedFiles": [],
            "deletedDirectories": [],
        }
    deleted_files: list[str] = []
    deleted_directories: list[str] = []
    for filename in _EPISODE_STORYBOARD_DERIVED_FILENAMES:
        path = episode_dir / filename
        if path.exists() and path.is_file():
            path.unlink()
            deleted_files.append(filename)
    for dirname in _EPISODE_STORYBOARD_DERIVED_DIRNAMES:
        path = episode_dir / dirname
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
            deleted_directories.append(dirname)
    return {
        "deletedCount": len(deleted_files) + len(deleted_directories),
        "deletedFileCount": len(deleted_files),
        "deletedDirectoryCount": len(deleted_directories),
        "deletedFiles": deleted_files,
        "deletedDirectories": deleted_directories,
    }


def _reset_coverage_for_planning_delete(
    project_id: str,
    *,
    targets: set[str],
    episode_ids: list[str],
    reason: str,
    user_instruction: str,
) -> dict[str, Any]:
    path = _source_coverage_path(project_id)
    if not path.exists():
        return {"changed": False, "removedEpisodeIds": [], "removedAssetRangeCount": 0}
    try:
        coverage = _load_source_coverage(project_id)
    except Exception as exc:  # noqa: BLE001 - source coverage can be absent before source import.
        return {"changed": False, "removedEpisodeIds": [], "removedAssetRangeCount": 0, "skippedReason": str(exc)}
    coverage_before = copy.deepcopy(coverage)
    removed_episode_ids: list[str] = []
    removed_asset_range_count = 0

    if "source_splits" in targets:
        ranges = [item for item in coverage.get("episodeRanges") or [] if isinstance(item, dict)]
        if episode_ids:
            selected = set(episode_ids)
            indexes = [
                index
                for index, item in enumerate(ranges)
                if str(item.get("episodeId") or item.get("episode_id") or "") in selected
            ]
            if indexes:
                cutoff = min(indexes)
                removed_ranges = ranges[cutoff:]
                coverage["episodeRanges"] = ranges[:cutoff]
            else:
                removed_ranges = []
        else:
            removed_ranges = ranges
            coverage["episodeRanges"] = []
        removed_episode_ids = [
            str(item.get("episodeId") or item.get("episode_id") or "").strip()
            for item in removed_ranges
            if str(item.get("episodeId") or item.get("episode_id") or "").strip()
        ]
        kept_ranges = coverage.get("episodeRanges") if isinstance(coverage.get("episodeRanges"), list) else []
        last_range = kept_ranges[-1] if kept_ranges and isinstance(kept_ranges[-1], dict) else {}
        coverage.setdefault("episodeCursor", {})["nextOffset"] = int(last_range.get("absoluteEnd") or 0)
        coverage["episodeCursor"]["lastEpisodeId"] = last_range.get("episodeId") or None

    if "asset_ranges" in targets:
        removed_asset_range_count = len(coverage.get("assetRanges") or []) if isinstance(coverage.get("assetRanges"), list) else 0
        coverage["assetRanges"] = []
        coverage.setdefault("assetCursor", {})["nextOffset"] = 0
        coverage["assetCursor"]["lastRangeId"] = None

    if coverage == coverage_before:
        return {"changed": False, "removedEpisodeIds": removed_episode_ids, "removedAssetRangeCount": 0}
    _append_resource_revision(
        project_id,
        resource="sourceCoverage",
        relative_path="source_coverage.json",
        document=coverage_before,
        reason=reason or "delete_project_planning_outputs",
        user_instruction=user_instruction,
    )
    coverage["revision"] = _resource_revision_value(coverage_before) + 1
    _write_source_coverage(project_id, coverage)
    return {
        "changed": True,
        "coverage": coverage,
        "removedEpisodeIds": removed_episode_ids,
        "removedAssetRangeCount": removed_asset_range_count,
    }


def delete_project_planning_outputs(project_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not str(project_id or "").strip():
        raise ValueError("缺少 projectId")
    payload = payload if isinstance(payload, dict) else {}
    requested_episode_ids = _episode_ids_from_payload(payload.get("episodeIds") or payload.get("episode_ids") or payload.get("episodeId") or payload.get("episode_id"))
    user_instruction = _assert_explicit_delete_all_confirmed(
        payload,
        target_label="项目拆分规划",
        target_terms=(
            "分集",
            "集",
            "分镜",
            "规划",
            "拆分",
            "原文",
            "故事版",
            "画布",
            "source",
            "episode",
            "episodeid",
            "storyboard",
            "workflow",
            "planning",
        ),
        require_all=not bool(requested_episode_ids),
    )
    target_value = payload.get("targets")
    if target_value is None:
        target_value = payload.get("target")
    targets = _delete_planning_targets(
        target_value,
        default_targets=_EPISODE_PLANNING_DELETE_TARGETS if requested_episode_ids else _ALL_PLANNING_DELETE_TARGETS,
    )
    _assert_source_split_delete_targets_latest_episode(
        project_id,
        targets=targets,
        requested_episode_ids=requested_episode_ids,
    )
    if requested_episode_ids:
        normalized_instruction = user_instruction.casefold()
        if "source_index" in targets and not any(
            term in normalized_instruction
            for term in ("source_index", "index", "索引", "章节索引", "单元索引")
        ):
            raise ValueError("定向删除分集时未明确要求删除全局原文索引")
        if "asset_ranges" in targets and not any(
            term in normalized_instruction
            for term in ("asset_range", "asset_ranges", "资产范围", "资产拆分", "资产游标")
        ):
            raise ValueError("定向删除分集时未明确要求清空资产拆分范围")
    reason = str(payload.get("reason") or "delete_project_planning_outputs")
    index_before = _read_json(_source_index_path(project_id), {}) if _source_index_path(project_id).exists() else {}

    coverage_reset = _reset_coverage_for_planning_delete(
        project_id,
        targets=targets,
        episode_ids=requested_episode_ids,
        reason=reason,
        user_instruction=user_instruction,
    )
    removed_episode_ids = list(coverage_reset.get("removedEpisodeIds") or [])
    if "source_splits" in targets:
        if not removed_episode_ids:
            removed_episode_ids = requested_episode_ids or _project_episode_ids(project_id)
        if requested_episode_ids and coverage_reset.get("removedEpisodeIds"):
            removed_episode_ids = list(dict.fromkeys([*removed_episode_ids, *requested_episode_ids]))

    deleted_episode_dirs = 0
    deleted_storyboard_output_count = 0
    deleted_storyboard_file_count = 0
    deleted_storyboard_directory_count = 0
    storyboard_delete_results: dict[str, dict[str, Any]] = {}
    deleted_canvas_record_count = 0
    deleted_canvas_document_count = 0
    canvas_delete_results: dict[str, dict[str, Any]] = {}
    canvas_changed_resources: list[str] = []

    def delete_canvas_runtime_for_episode(raw_episode_id: str) -> None:
        nonlocal deleted_canvas_record_count, deleted_canvas_document_count
        episode_id = str(raw_episode_id or "").strip()
        if not episode_id:
            return
        delete_result = delete_episode_canvas_v4(project_id, episode_id)
        canvas_delete_results[episode_id] = delete_result
        deleted_canvas_record_count += int(delete_result.get("deletedCount") or 0)
        deleted_records = delete_result.get("deletedRecords") if isinstance(delete_result.get("deletedRecords"), dict) else {}
        deleted_canvas_document_count += int(deleted_records.get("canvas_documents") or 0)
        for resource in delete_result.get("changedResources") or []:
            resource_name = str(resource or "").strip()
            if resource_name and resource_name not in canvas_changed_resources:
                canvas_changed_resources.append(resource_name)

    story_target_episode_ids = requested_episode_ids or _project_episode_ids(project_id)
    if "source_splits" in targets:
        for episode_id in removed_episode_ids:
            delete_canvas_runtime_for_episode(episode_id)
            if _delete_episode_directory(project_id, episode_id):
                deleted_episode_dirs += 1
    elif "storyboards" in targets:
        for episode_id in story_target_episode_ids:
            delete_canvas_runtime_for_episode(episode_id)
            delete_result = _delete_episode_storyboard_files(project_id, episode_id)
            storyboard_delete_results[episode_id] = delete_result
            deleted_storyboard_output_count += int(delete_result.get("deletedCount") or 0)
            deleted_storyboard_file_count += int(delete_result.get("deletedFileCount") or 0)
            deleted_storyboard_directory_count += int(delete_result.get("deletedDirectoryCount") or 0)

    task_cleanup: dict[str, Any] = {"deletedTaskCount": 0, "deletedJobCount": 0}
    task_cleanup_episode_ids = removed_episode_ids if "source_splits" in targets else story_target_episode_ids if "storyboards" in targets else []
    if task_cleanup_episode_ids:
        from .task_commands import delete_episode_derived_tasks

        task_cleanup = delete_episode_derived_tasks(project_id, task_cleanup_episode_ids)

    source_index_deleted = False
    if "source_index" in targets:
        source_index_path = _source_index_path(project_id)
        if source_index_path.exists() and source_index_path.is_file():
            source_index_path.unlink()
            source_index_deleted = True

    if "source_splits" in targets and removed_episode_ids:
        meta = _read_json(_project_meta_path(project_id), {})
        episodes = meta.get("episodes") if isinstance(meta.get("episodes"), list) else []
        removed = set(removed_episode_ids)
        meta["episodes"] = [
            item
            for item in episodes
            if not isinstance(item, dict) or str(item.get("id") or item.get("episodeId") or "") not in removed
        ]
        meta["episode_count"] = len(meta["episodes"])
        meta["status_type"] = "running" if list_sources(project_id).get("sources") else "draft"
        meta["status"] = "已删除分集规划，等待用户下一步指令" if meta["status_type"] == "running" else "等待添加小说文本"
        meta["updated_at"] = _now()
        _write_json(_project_meta_path(project_id), meta)
    elif deleted_storyboard_output_count or deleted_canvas_record_count or int(task_cleanup.get("deletedTaskCount") or 0):
        meta = _read_json(_project_meta_path(project_id), {})
        episodes = meta.get("episodes") if isinstance(meta.get("episodes"), list) else []
        target_ids = set(story_target_episode_ids)
        next_episodes: list[dict[str, Any]] = []
        changed = False
        for item in episodes:
            if not isinstance(item, dict):
                continue
            row = copy.deepcopy(item)
            episode_id = str(row.get("id") or row.get("episodeId") or "").strip()
            if episode_id in target_ids:
                next_status = "原文已保留，等待重新规划分镜"
                if row.get("status") != next_status:
                    row["status"] = next_status
                    changed = True
            next_episodes.append(row)
        if changed:
            meta["episodes"] = next_episodes
        meta["status_type"] = "running" if list_sources(project_id).get("sources") else "draft"
        meta["status"] = "已删除分镜/画布派生内容，等待重新规划分镜" if meta["status_type"] == "running" else "等待添加小说文本"
        meta["updated_at"] = _now()
        _write_json(_project_meta_path(project_id), meta)

    changed_resources: list[str] = []
    if source_index_deleted:
        changed_resources.append("sourceIndex")
    if coverage_reset.get("changed"):
        changed_resources.append("sourceCoverage")
    if deleted_episode_dirs:
        changed_resources.append("episodes")
    if deleted_storyboard_output_count:
        changed_resources.extend(
            [
                "storyboards",
                "workflow",
                "workflow_tasks",
                "versions",
                "results",
                "episode_production_status",
            ]
        )
    if deleted_canvas_record_count:
        changed_resources.extend(
            [
                "storyboards",
                "workflow",
                "workflow_tasks",
                "versions",
                "episode_production_status",
                *canvas_changed_resources,
            ]
        )
    if int(task_cleanup.get("deletedTaskCount") or 0):
        changed_resources.append("tasks")
    if coverage_reset.get("removedAssetRangeCount"):
        changed_resources.append("assetRanges")
    changed_resources = list(dict.fromkeys(changed_resources))

    focus_target = {"section": "sources"}
    if "storyboards" in targets and "source_splits" not in targets and story_target_episode_ids:
        focus_target = {"section": "episode", "episodeId": story_target_episode_ids[0]}

    return {
        "success": True,
        "message": "已删除项目派生规划。" if changed_resources else "当前项目没有可删除的派生规划。",
        "targets": sorted(targets),
        "episodeIds": removed_episode_ids if "source_splits" in targets else story_target_episode_ids,
        "deletedEpisodeDirectoryCount": deleted_episode_dirs,
        "deletedStoryboardFileCount": deleted_storyboard_output_count,
        "deletedStoryboardOutputCount": deleted_storyboard_output_count,
        "deletedStoryboardJsonFileCount": deleted_storyboard_file_count,
        "deletedStoryboardDirectoryCount": deleted_storyboard_directory_count,
        "deletedStoryboardOutputs": storyboard_delete_results,
        "deletedCanvasDocumentCount": deleted_canvas_document_count,
        "deletedCanvasRecordCount": deleted_canvas_record_count,
        "deletedCanvasRecords": canvas_delete_results,
        "deletedTaskCount": int(task_cleanup.get("deletedTaskCount") or 0),
        "deletedTaskJobCount": int(task_cleanup.get("deletedJobCount") or 0),
        "sourceIndexDeleted": source_index_deleted,
        "assetRangeReset": {
            "changed": bool(coverage_reset.get("changed") and coverage_reset.get("removedAssetRangeCount")),
            "removedCount": int(coverage_reset.get("removedAssetRangeCount") or 0),
        },
        "sourceHierarchy": _source_hierarchy_manifest(project_id, index_before),
        "changedResources": changed_resources,
        "focusTarget": focus_target,
        "projectChanged": bool(changed_resources),
    }


__all__ = (
    "delete_source",
    "delete_project_planning_outputs",
    "_ALL_PLANNING_DELETE_TARGETS",
    "_EPISODE_PLANNING_DELETE_TARGETS",
    "_GLOBAL_PLANNING_DELETE_TARGETS",
    "_EPISODE_STORYBOARD_DERIVED_FILENAMES",
    "_EPISODE_STORYBOARD_DERIVED_DIRNAMES",
    "_safe_episode_id",
    "_delete_planning_targets",
    "_episode_ids_from_payload",
    "_project_episode_ids",
    "_latest_project_episode_id",
    "_assert_source_split_delete_targets_latest_episode",
    "_source_hierarchy_manifest",
    "_delete_episode_directory",
    "_delete_episode_storyboard_files",
    "_reset_coverage_for_planning_delete",
)
