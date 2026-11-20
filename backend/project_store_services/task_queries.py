# -*- coding: utf-8 -*-
"""任务查询、用量诊断及查询触发的后台恢复扫描。"""
from __future__ import annotations

from .catalogs import GLOBAL_USAGE_PATH
from .store_core import _display_time
from .store_core import _now
from .store_core import _read_json
from .store_core import ensure_store
from .task_contract import _FAILED_NOTIFICATION_TASK_STATUSES
from .task_contract import _SUCCESS_NOTIFICATION_TASK_STATUSES
from .task_contract import _task_workflow_node_id
from .task_lifecycle import _load_reconciled_tasks
from .task_projection import _TASK_LIST_WORKSPACE_DOCK_ACTIVE_STATUSES
from .task_projection import _task_list_bool
from .task_projection import _task_list_dedupe_workspace_dock_rows
from .task_projection import _task_list_has_uncleared_notification
from .task_projection import _task_list_is_workspace_dock_visible
from .task_projection import _task_list_status
from .task_projection import _task_list_string_set
from .task_projection import _task_list_summary
from .task_storage import _load_tasks
from .task_storage import _normalized_task_status
from typing import Any

from .task_lifecycle import _background_storyboard_task_has_running_thread
from .task_storage import _TASK_STORAGE_GLOBAL_KEY
from .task_storage import _load_tasks_for_project
from .task_storage import _read_task_runtime_job
from .video_task_execution import _resume_storyboard_video_task_rows
from .runtime_state import _VIDEO_GENERATION_TASK_TYPES
import os
import threading
import time
import traceback


def list_tasks(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    project_id = str(payload.get("projectId") or payload.get("project_id") or "").strip()
    episode_id = str(payload.get("episodeId") or payload.get("episode_id") or "").strip()
    session_id = str(payload.get("sessionId") or "").strip()
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    task_type = str(payload.get("type") or payload.get("taskType") or payload.get("task_type") or "").strip()
    task_types = _task_list_string_set(
        task_type,
        payload.get("types"),
        payload.get("taskTypes"),
        payload.get("task_types"),
    )
    status_set = _task_list_string_set(
        payload.get("status"),
        payload.get("statuses"),
        payload.get("taskStatus"),
        payload.get("taskStatuses"),
        payload.get("task_status"),
        payload.get("task_statuses"),
    )
    asset_type = str(payload.get("assetType") or payload.get("asset_type") or "").strip()
    compact = _task_list_bool(payload, "compact", "summary", "lightweight", default=False)
    include_debug = _task_list_bool(payload, "includeDebug", "include_debug", "debug", default=False)
    global_only = _task_list_bool(payload, "globalOnly", "global_only", default=False)
    workspace_dock_only = _task_list_bool(
        payload,
        "workspaceDockOnly",
        "workspace_dock_only",
        "dockOnly",
        "dock_only",
        default=False,
    )
    notification_only = _task_list_bool(
        payload,
        "notificationOnly",
        "notification_only",
        "unreadNotificationsOnly",
        "unread_notifications_only",
        default=False,
    )
    raw_limit = payload.get("limit")
    try:
        limit = int(raw_limit) if raw_limit not in (None, "") else 0
    except (TypeError, ValueError):
        limit = 0
    if project_id:
        tasks = _load_reconciled_tasks(project_id)
    elif global_only:
        tasks = _load_reconciled_tasks(global_only=True)
    else:
        tasks = _load_reconciled_tasks()
    _schedule_task_recovery_scan(tasks, project_id=project_id, global_only=global_only)
    rows = list(reversed(tasks))
    if project_id:
        rows = [item for item in rows if str(item.get("projectId") or "") == project_id]
    if episode_id:
        rows = [item for item in rows if str(item.get("episodeId") or "") == episode_id]
    if session_id:
        rows = [
            item
            for item in rows
            if str(item.get("sessionId") or "") == session_id
        ]
    if node_id:
        rows = [item for item in rows if _task_workflow_node_id(item) == node_id]
    if task_types:
        rows = [item for item in rows if str(item.get("type") or "") in task_types]
    if status_set:
        rows = [item for item in rows if _task_list_status(item) in status_set]
    if workspace_dock_only:
        rows = [item for item in rows if _task_list_is_workspace_dock_visible(item)]
    elif notification_only:
        rows = [item for item in rows if _task_list_has_uncleared_notification(item)]
    if asset_type:
        rows = [item for item in rows if str(item.get("assetType") or item.get("asset_type") or "") == asset_type]
    if workspace_dock_only:
        rows = _task_list_dedupe_workspace_dock_rows([item for item in rows if isinstance(item, dict)])
    if limit > 0:
        if workspace_dock_only:
            active_rows = [
                item
                for item in rows
                if isinstance(item, dict)
                and _task_list_status(item) in _TASK_LIST_WORKSPACE_DOCK_ACTIVE_STATUSES
            ]
            notification_rows = [
                item
                for item in rows
                if not (
                    isinstance(item, dict)
                    and _task_list_status(item) in _TASK_LIST_WORKSPACE_DOCK_ACTIVE_STATUSES
                )
            ]
            rows = [*active_rows, *notification_rows[: max(0, limit - len(active_rows))]]
        else:
            rows = rows[:limit]
    if compact:
        rows = [
            _task_list_summary(
                item,
                include_debug=include_debug,
                include_worker_run=not workspace_dock_only,
            )
            if isinstance(item, dict)
            else item
            for item in rows
        ]
    return {"tasks": rows}


def diagnose_task(task_id: str) -> dict[str, Any]:
    return {
        "success": True,
        "diagnosis": {
            "level": "info",
            "message": f"任务 {task_id} 当前为本地占位生成链路，未触发远程供应商错误。",
            "createdAt": _display_time(_now()),
        },
    }


def get_usage_summary() -> dict[str, Any]:
    ensure_store()
    stored = _read_json(GLOBAL_USAGE_PATH, {})
    if not isinstance(stored, dict):
        stored = {}
    tasks = _load_tasks()
    return {
        "monthCost": float(stored.get("monthCost") or 0),
        "storyboardImages": sum(
            1
            for task in tasks
            if task.get("type") in {"storyboard_image", "storyboard_image_edit"}
            and _normalized_task_status(task) in _SUCCESS_NOTIFICATION_TASK_STATUSES
        ),
        "storyboardVideos": sum(
            1
            for task in tasks
            if task.get("type") == "storyboard_video"
            and _normalized_task_status(task) in _SUCCESS_NOTIFICATION_TASK_STATUSES
        ),
        "assetImages": sum(
            1
            for task in tasks
            if task.get("type") == "asset_image"
            and _normalized_task_status(task) in _SUCCESS_NOTIFICATION_TASK_STATUSES
        ),
        "failedTasks": sum(
            1
            for task in tasks
            if _normalized_task_status(task) in _FAILED_NOTIFICATION_TASK_STATUSES
        ),
    }


_TASK_RECOVERY_SCAN_INTERVAL_SECONDS = 8.0


_TASK_RECOVERY_SCAN_LOCK = threading.Lock()


_TASK_RECOVERY_SCAN_LAST_AT: dict[str, float] = {}


_TASK_RECOVERY_SCAN_RUNNING: set[str] = set()


def _task_recovery_scan_enabled() -> bool:
    return bool(os.environ.get("XIAOWO_PLUGIN_PROTOCOL_PIPE"))


def _video_task_row_needs_worker_recovery(task: dict[str, Any]) -> bool:
    if str(task.get("type") or "").strip() not in _VIDEO_GENERATION_TASK_TYPES:
        return False
    if str(task.get("status") or "").strip() not in {"created", "running"}:
        return False
    if _background_storyboard_task_has_running_thread(task):
        return False
    return (
        isinstance(task.get("videoJob"), dict)
        or bool(task.get("videoJobRef"))
        or bool(_read_task_runtime_job(task))
    )


def _task_row_needs_recovery_scan(task: dict[str, Any]) -> bool:
    return _video_task_row_needs_worker_recovery(task)


def _task_rows_need_recovery_scan(tasks: list[dict[str, Any]]) -> bool:
    return any(_task_row_needs_recovery_scan(task) for task in tasks if isinstance(task, dict))


def _recovery_scan_rows_for_scope(project_id: str, global_only: bool) -> list[dict[str, Any]]:
    if project_id:
        return _load_tasks_for_project(project_id)
    if global_only:
        return _load_tasks_for_project(None)
    return _load_tasks()


def _run_task_recovery_scan(scan_key: str, project_id: str, global_only: bool) -> None:
    try:
        rows = _recovery_scan_rows_for_scope(project_id, global_only)
        _resume_storyboard_video_task_rows(rows)
    except Exception:
        print(traceback.format_exc(), flush=True)
    finally:
        with _TASK_RECOVERY_SCAN_LOCK:
            _TASK_RECOVERY_SCAN_RUNNING.discard(scan_key)


def _schedule_task_recovery_scan(
    tasks: list[dict[str, Any]],
    *,
    project_id: str | None = None,
    global_only: bool = False,
) -> None:
    if not _task_recovery_scan_enabled():
        return
    if not _task_rows_need_recovery_scan(tasks):
        return
    normalized_project_id = str(project_id or "").strip()
    scan_key = normalized_project_id or (_TASK_STORAGE_GLOBAL_KEY if global_only else "__all__")
    now = time.monotonic()
    with _TASK_RECOVERY_SCAN_LOCK:
        if scan_key in _TASK_RECOVERY_SCAN_RUNNING:
            return
        last_scan = _TASK_RECOVERY_SCAN_LAST_AT.get(scan_key, 0.0)
        if now - last_scan < _TASK_RECOVERY_SCAN_INTERVAL_SECONDS:
            return
        _TASK_RECOVERY_SCAN_LAST_AT[scan_key] = now
        _TASK_RECOVERY_SCAN_RUNNING.add(scan_key)
    thread = threading.Thread(
        target=_run_task_recovery_scan,
        args=(scan_key, normalized_project_id, bool(global_only)),
        daemon=True,
        name=f"ai-video-task-recovery-{scan_key.replace(chr(10), '-')}",
    )
    try:
        thread.start()
    except Exception:
        with _TASK_RECOVERY_SCAN_LOCK:
            _TASK_RECOVERY_SCAN_RUNNING.discard(scan_key)
        print(traceback.format_exc(), flush=True)
