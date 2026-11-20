# -*- coding: utf-8 -*-
"""后台线程登记、运行状态判断和失效任务收敛。"""
from __future__ import annotations

from datetime import datetime
from .agent_sessions import _project_dir
from .canvas_store_queries import read_workflow_card_neighborhood_v4
from .store_core import _display_time
from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json
from .task_contract import _AGENT_GLOBAL_TASK_TYPES
from .task_contract import _BACKGROUND_STORYBOARD_TASK_TYPES
from .task_contract import _STALE_AGENT_TASK_MESSAGE
from .task_contract import _STALE_ASSET_IMAGE_TASK_MESSAGE
from .task_contract import _STALE_STORYBOARD_TASK_MESSAGE
from .task_contract import _STALE_WORKFLOW_TASK_MESSAGE
from .task_contract import _WORKFLOW_NODE_TASK_TYPES
from .task_contract import _is_stale_task_message
from .task_contract import _task_age_seconds
from .task_contract import _task_workflow_node_id
from .task_control import _ACTIVE_GLOBAL_TASK_STATUSES
from .task_control import _get_task
from .task_storage import _TASK_STORAGE_GLOBAL_KEY
from .task_storage import _TASK_STORAGE_LOCK
from .task_storage import _load_task_listing_snapshot
from .task_storage import _load_tasks
from .task_storage import _load_tasks_for_project
from .task_storage import _normalized_task_status
from .task_storage import _read_task_runtime_job
from .task_storage import _save_task_storage_bucket
from .task_storage import _save_tasks
from .task_storage import _task_project_id
from .runtime_state import AGENT_STALE_RUNNING_GRACE_SECONDS
from .runtime_state import _agent_thread_is_alive
from .runtime_state import _ASSET_IMAGE_TASK_THREADS
from .runtime_state import _VIDEO_GENERATION_TASK_TYPES
from .runtime_state import _VIDEO_TASK_THREADS
from typing import Any
import copy
import os
import threading
import time


_TASK_STALE_RECONCILE_INTERVAL_SECONDS = 5.0


_TASK_STALE_RECONCILE_LAST_AT: dict[str, float] = {}


_BACKGROUND_STORYBOARD_TASK_THREADS: dict[str, threading.Thread] = {}


def _is_workflow_node_task(task: dict[str, Any]) -> bool:
    task_type = str(task.get("type") or "").strip()
    return task_type in _WORKFLOW_NODE_TASK_TYPES


def _workflow_node_exists_for_task(task: dict[str, Any]) -> bool:
    project_id = str(task.get("projectId") or task.get("project_id") or "").strip()
    episode_id = str(task.get("episodeId") or task.get("episode_id") or "").strip()
    node_id = _task_workflow_node_id(task)
    if not project_id or not episode_id or not node_id or not _is_workflow_node_task(task):
        return True
    try:
        read_workflow_card_neighborhood_v4(project_id, episode_id, node_id, detail="summary")
    except FileNotFoundError:
        return False
    except Exception:
        return True
    return True


def _task_agent_thread_keys(task: dict[str, Any]) -> list[str]:
    key = str(task.get("id") or "").strip()
    return [key] if key else []


def _agent_task_has_running_thread(task: dict[str, Any]) -> bool:
    return any(_agent_thread_is_alive(key) for key in _task_agent_thread_keys(task))


def _agent_task_is_stale(task: dict[str, Any]) -> bool:
    if str(task.get("type") or "").strip() not in _AGENT_GLOBAL_TASK_TYPES:
        return False
    if _normalized_task_status(task) not in _ACTIVE_GLOBAL_TASK_STATUSES:
        return False
    if _agent_task_has_running_thread(task):
        return False
    age_seconds = _task_age_seconds(task)
    return age_seconds is None or age_seconds >= AGENT_STALE_RUNNING_GRACE_SECONDS


def _asset_image_task_has_running_thread(task: dict[str, Any]) -> bool:
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        return False
    thread = _ASSET_IMAGE_TASK_THREADS.get(task_id)
    return bool(thread and thread.is_alive())


def _asset_image_task_is_stale(task: dict[str, Any]) -> bool:
    if str(task.get("type") or "").strip() != "asset_image":
        return False
    if _normalized_task_status(task) not in _ACTIVE_GLOBAL_TASK_STATUSES:
        return False
    if _asset_image_task_has_running_thread(task):
        return False
    age_seconds = _task_age_seconds(task)
    return age_seconds is None or age_seconds >= AGENT_STALE_RUNNING_GRACE_SECONDS


def _background_storyboard_task_has_running_thread(task: dict[str, Any]) -> bool:
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        return False
    if str(task.get("type") or "").strip() in _VIDEO_GENERATION_TASK_TYPES:
        thread = _VIDEO_TASK_THREADS.get(task_id)
        return bool(thread and thread.is_alive())
    thread = _BACKGROUND_STORYBOARD_TASK_THREADS.get(task_id)
    return bool(thread and thread.is_alive())


def _background_storyboard_task_is_stale(task: dict[str, Any]) -> bool:
    if not os.environ.get("XIAOWO_PLUGIN_PROTOCOL_PIPE"):
        return False
    if str(task.get("type") or "").strip() not in _BACKGROUND_STORYBOARD_TASK_TYPES:
        return False
    if _normalized_task_status(task) not in _ACTIVE_GLOBAL_TASK_STATUSES:
        return False
    if _background_storyboard_task_has_running_thread(task):
        return False
    if (
        str(task.get("type") or "").strip() in _VIDEO_GENERATION_TASK_TYPES
        and (
            isinstance(task.get("videoJob"), dict)
            or bool(_read_task_runtime_job(task))
        )
    ):
        return False
    age_seconds = _task_age_seconds(task)
    return age_seconds is None or age_seconds >= AGENT_STALE_RUNNING_GRACE_SECONDS


def _reconcile_stale_tasks(tasks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    changed = False
    now_ms = int(datetime.now().timestamp() * 1000)
    now_label = _display_time(_now())
    next_tasks: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            next_tasks.append(task)
            continue
        status = str(task.get("status") or "").strip()
        stale_message = ""
        if _agent_task_is_stale(task):
            stale_message = _STALE_AGENT_TASK_MESSAGE
        elif _asset_image_task_is_stale(task):
            stale_message = _STALE_ASSET_IMAGE_TASK_MESSAGE
        elif _background_storyboard_task_is_stale(task):
            stale_message = _STALE_STORYBOARD_TASK_MESSAGE
        elif status in _ACTIVE_GLOBAL_TASK_STATUSES and not _workflow_node_exists_for_task(task):
            stale_message = _STALE_WORKFLOW_TASK_MESSAGE
        if stale_message:
            task = {
                **task,
                "status": "failed",
                "progress": 0,
                "message": stale_message,
                "notice": stale_message,
                "failedAt": now_label,
                "updatedAt": now_ms,
                "notificationClearedAt": task.get("notificationClearedAt") or now_ms,
            }
            changed = True
        elif (
            status == "failed"
            and not task.get("notificationClearedAt")
            and (_is_stale_task_message(task.get("message")) or _is_stale_task_message(task.get("notice")))
        ):
            task = {**task, "notificationClearedAt": now_ms, "updatedAt": task.get("updatedAt") or now_ms}
            changed = True
        next_tasks.append(task)
    return next_tasks, changed


def _load_reconciled_tasks(project_id: str | None = None, *, global_only: bool = False) -> list[dict[str, Any]]:
    normalized_project_id = str(project_id or "").strip()
    reconcile_key = normalized_project_id or (_TASK_STORAGE_GLOBAL_KEY if global_only else "__all__")
    now = time.monotonic()
    last_reconcile = _TASK_STALE_RECONCILE_LAST_AT.get(reconcile_key, 0.0)
    if now - last_reconcile < _TASK_STALE_RECONCILE_INTERVAL_SECONDS:
        return _load_task_listing_snapshot(normalized_project_id, global_only=global_only)
    with _TASK_STORAGE_LOCK:
        tasks = _load_tasks_for_project(normalized_project_id) if normalized_project_id or global_only else _load_tasks()
        _TASK_STALE_RECONCILE_LAST_AT[reconcile_key] = now
        tasks, changed = _reconcile_stale_tasks(tasks)
        if changed:
            if normalized_project_id or global_only:
                _save_task_storage_bucket(normalized_project_id or _TASK_STORAGE_GLOBAL_KEY, tasks)
            else:
                _save_tasks(tasks)
        return tasks


def register_background_task_thread(task_id: str, thread: threading.Thread) -> None:
    """Register a long-running task so stale-task reconciliation can see it."""
    normalized_task_id = str(task_id or "").strip()
    if normalized_task_id:
        _BACKGROUND_STORYBOARD_TASK_THREADS[normalized_task_id] = thread


def unregister_background_task_thread(task_id: str) -> None:
    _BACKGROUND_STORYBOARD_TASK_THREADS.pop(str(task_id or "").strip(), None)


def _storyboard_video_task_allows_work(
    task_id: str,
    cancel_event: threading.Event | None = None,
    *,
    task: dict[str, Any] | None = None,
) -> bool:
    if cancel_event and cancel_event.is_set():
        return False
    current = task if isinstance(task, dict) else _get_task(task_id)
    if not isinstance(current, dict):
        return False
    return _normalized_task_status(current) in {"created", "running"}


def _background_storyboard_task_allows_finish(task_id: str) -> bool:
    task = _get_task(task_id)
    if not task:
        return False
    return _normalized_task_status(task) in _ACTIVE_GLOBAL_TASK_STATUSES
