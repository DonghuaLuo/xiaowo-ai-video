# -*- coding: utf-8 -*-
"""任务取消、通知清除和派生任务删除。"""
from __future__ import annotations

from .runtime_state import _LOCK
from datetime import datetime
from .agent_session_results import _interrupt_agent_session_state
from .store_core import _display_time
from .store_core import _now
from .task_canvas_sync import _sync_canvas_task_record
from .task_contract import _AGENT_GLOBAL_TASK_TYPES
from .task_contract import _AGENT_SESSION_BOUND_CANCEL_TASK_TYPES
from .task_contract import _EPISODE_DERIVED_TASK_TYPES
from .task_contract import _FAILED_NOTIFICATION_TASK_STATUSES
from .task_contract import _SUCCESS_NOTIFICATION_TASK_STATUSES
from .task_contract import _task_agent_session_id
from .task_contract import _task_result_commit_started
from .task_control import _ACTIVE_GLOBAL_TASK_STATUSES
from .task_control import _emit_task_update
from .task_control import _get_task
from .task_events import _emit_storyboard_video_task_project_changed
from .task_events import _maybe_report_agent_bound_generation_task
from .task_lifecycle import _BACKGROUND_STORYBOARD_TASK_THREADS
from .task_lifecycle import _reconcile_stale_tasks
from .task_lifecycle import _task_agent_thread_keys
from .task_projection import _task_list_has_uncleared_notification
from .task_projection import _task_list_summary
from .task_storage import _TASK_PROJECT_INDEX
from .task_storage import _TASK_STORAGE_LOCK
from .task_storage import _delete_task_runtime_job
from .task_storage import _hydrate_task_runtime_fields
from .task_storage import _load_task_storage_bucket
from .task_storage import _load_tasks
from .task_storage import _load_tasks_for_project
from .task_storage import _normalized_task_status
from .task_storage import _save_task_storage_bucket
from .task_storage import _save_tasks
from .task_storage import _task_storage_key_for_task_id
from .video_task_provider import _cancel_storyboard_video_provider_job_async
from .video_task_provider import _cancel_storyboard_video_version
from .runtime_state import _AGENT_CANCEL_FLAGS
from .runtime_state import _ASSET_IMAGE_TASK_CANCEL_FLAGS
from .runtime_state import _VIDEO_GENERATION_TASK_TYPES
from .runtime_state import _VIDEO_TASK_CANCEL_FLAGS
from typing import Any
import traceback


def cancel_agent_session_bound_tasks(
    project_id: str,
    session_id: str,
    *,
    exclude_task_ids: set[str] | None = None,
    included_task_ids: set[str] | None = None,
) -> dict[str, Any]:
    normalized_project_id = str(project_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    excluded = {
        str(item or "").strip()
        for item in (exclude_task_ids or set())
        if str(item or "").strip()
    }
    if not normalized_project_id or not normalized_session_id:
        return {
            "success": True,
            "attemptedTaskIds": [],
            "cancelledTaskIds": [],
            "uncancelledTaskIds": [],
            "tasks": [],
            "cancelledTasks": [],
            "uncancelledTasks": [],
            "uncancelledTaskReasons": [],
            "errors": [],
        }

    task_ids: list[str] = []
    with _TASK_STORAGE_LOCK:
        for task in _load_tasks_for_project(normalized_project_id):
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id") or "").strip()
            if not task_id or task_id in excluded:
                continue
            if included_task_ids is not None and task_id not in included_task_ids:
                continue
            if _task_agent_session_id(task) != normalized_session_id:
                continue
            if str(task.get("type") or "").strip() not in _AGENT_SESSION_BOUND_CANCEL_TASK_TYPES:
                continue
            if _normalized_task_status(task) not in _ACTIVE_GLOBAL_TASK_STATUSES:
                continue
            task_ids.append(task_id)

    cancelled_task_ids: list[str] = []
    attempted_tasks: list[dict[str, Any]] = []
    cancelled_tasks: list[dict[str, Any]] = []
    uncancelled_task_ids: list[str] = []
    uncancelled_tasks: list[dict[str, Any]] = []
    uncancelled_task_reasons: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for task_id in task_ids:
        try:
            result = cancel_task(task_id)
            task = result.get("task") if isinstance(result, dict) else None
            if isinstance(task, dict):
                if _normalized_task_status(task) in {"cancelled", "canceled"}:
                    attempted_tasks.append(task)
                    cancelled_task_ids.append(task_id)
                    cancelled_tasks.append(task)
                else:
                    reason = str(result.get("cancelSkippedReason") or "task_not_cancelled").strip()
                    message = str(result.get("message") or result.get("cancelSkippedMessage") or "任务当前无法取消").strip()
                    task = {
                        **task,
                        "cancelSkippedReason": reason,
                        "cancelSkippedMessage": message,
                    }
                    attempted_tasks.append(task)
                    uncancelled_task_ids.append(task_id)
                    uncancelled_tasks.append(task)
                    uncancelled_task_reasons.append(
                        {"taskId": task_id, "reason": reason, "message": message}
                    )
        except Exception as exc:  # noqa: BLE001
            errors.append({"taskId": task_id, "message": str(exc) or exc.__class__.__name__})
            print(traceback.format_exc(), flush=True)

    return {
        "success": not errors,
        "attemptedTaskIds": task_ids,
        "cancelledTaskIds": cancelled_task_ids,
        "uncancelledTaskIds": uncancelled_task_ids,
        "tasks": attempted_tasks,
        "cancelledTasks": cancelled_tasks,
        "uncancelledTasks": uncancelled_tasks,
        "uncancelledTaskReasons": uncancelled_task_reasons,
        "errors": errors,
    }


def delete_episode_derived_tasks(project_id: str, episode_ids: list[str] | tuple[str, ...] | set[str]) -> dict[str, Any]:
    normalized_project_id = str(project_id or "").strip()
    selected_episode_ids = {
        str(item or "").strip()
        for item in episode_ids
        if str(item or "").strip()
    }
    if not normalized_project_id or not selected_episode_ids:
        return {"success": True, "deletedTaskCount": 0, "deletedJobCount": 0}
    deleted_tasks: list[str] = []
    deleted_jobs = 0
    with _TASK_STORAGE_LOCK:
        rows = _load_tasks_for_project(normalized_project_id)
        next_rows: list[dict[str, Any]] = []
        for task in rows:
            if not isinstance(task, dict):
                next_rows.append(task)
                continue
            task_project_id = str(task.get("projectId") or "").strip()
            task_episode_id = str(task.get("episodeId") or task.get("episode_id") or "").strip()
            task_type = str(task.get("type") or "").strip()
            should_delete = (
                task_project_id == normalized_project_id
                and task_episode_id in selected_episode_ids
                and task_type in _EPISODE_DERIVED_TASK_TYPES
            )
            if not should_delete:
                next_rows.append(task)
                continue
            task_id = str(task.get("id") or "").strip()
            if task_id:
                deleted_tasks.append(task_id)
                if _delete_task_runtime_job(normalized_project_id, task_id):
                    deleted_jobs += 1
                _TASK_PROJECT_INDEX.pop(task_id, None)
                _BACKGROUND_STORYBOARD_TASK_THREADS.pop(task_id, None)
                _VIDEO_TASK_CANCEL_FLAGS.pop(task_id, None)
        if len(next_rows) != len(rows):
            _save_task_storage_bucket(normalized_project_id, next_rows)
    return {
        "success": True,
        "deletedTaskCount": len(deleted_tasks),
        "deletedJobCount": deleted_jobs,
        "deletedTaskIds": deleted_tasks,
    }


def clear_task_notifications(project_id: str | None = None) -> dict[str, Any]:
    normalized_project_id = str(project_id or "").strip()
    now_ms = int(datetime.now().timestamp() * 1000)
    cleared = 0
    with _TASK_STORAGE_LOCK:
        tasks = _load_tasks_for_project(normalized_project_id) if normalized_project_id else _load_tasks()
        tasks, stale_changed = _reconcile_stale_tasks(tasks)
        for task in tasks:
            if not isinstance(task, dict):
                continue
            if normalized_project_id and str(task.get("projectId") or "") != normalized_project_id:
                continue
            if not _task_list_has_uncleared_notification(task):
                continue
            task["notificationClearedAt"] = now_ms
            cleared += 1
        if stale_changed or cleared:
            if normalized_project_id:
                _save_task_storage_bucket(normalized_project_id, tasks)
            else:
                _save_tasks(tasks)
    return {"success": True, "cleared": cleared}


def cancel_task(task_id: str) -> dict[str, Any]:
    normalized_task_id = str(task_id or "").strip()
    matched = _get_task(normalized_task_id)
    if (
        matched
        and matched.get("sessionId")
        and matched.get("projectId")
        and matched.get("type") == "agent_turn"
    ):
        result = _interrupt_agent_session_state(
            str(matched.get("projectId") or ""),
            str(matched.get("sessionId") or ""),
            emit_events=True,
            expected_execution_id=str(matched.get("executionId") or matched.get("id") or ""),
        )
        return {"success": True, "task": result.get("task") or matched}
    did_cancel = False
    result_commit_in_progress = False
    cancel_skipped_reason = ""
    cancel_skipped_message = ""
    storage_key = _task_storage_key_for_task_id(normalized_task_id)
    with _TASK_STORAGE_LOCK:
        tasks = _load_task_storage_bucket(storage_key) if storage_key else _load_tasks()
        for task in tasks:
            if task.get("id") == normalized_task_id and _normalized_task_status(task) in _ACTIVE_GLOBAL_TASK_STATUSES:
                if _task_result_commit_started(task):
                    result_commit_in_progress = True
                    cancel_skipped_reason = "result_commit_started"
                    cancel_skipped_message = "任务已进入结果保存阶段，取消请求不再中断保存。"
                    break
                if task.get("type") == "asset_image":
                    asset_cancel_event = _ASSET_IMAGE_TASK_CANCEL_FLAGS.get(normalized_task_id)
                    if asset_cancel_event:
                        asset_cancel_event.set()
                if task.get("type") in _VIDEO_GENERATION_TASK_TYPES:
                    cancel_event = _VIDEO_TASK_CANCEL_FLAGS.get(normalized_task_id)
                    if cancel_event:
                        cancel_event.set()
                if task.get("type") in _AGENT_GLOBAL_TASK_TYPES:
                    for key in _task_agent_thread_keys(task):
                        agent_cancel = _AGENT_CANCEL_FLAGS.get(key)
                        if agent_cancel:
                            agent_cancel.set()
                task["status"] = "cancelled"
                task["progress"] = 0
                task["message"] = "已取消"
                task["cancelledAt"] = _display_time(_now())
                task["updatedAt"] = int(datetime.now().timestamp() * 1000)
                if task.get("type") == "asset_image":
                    task["notice"] = task["message"]
                did_cancel = True
                break
        if storage_key:
            _save_task_storage_bucket(storage_key, tasks)
        else:
            _save_tasks(tasks)
        task = next((item for item in tasks if item.get("id") == normalized_task_id), None)
    if not task:
        raise FileNotFoundError("任务不存在")
    if result_commit_in_progress:
        with _LOCK:
            task = _get_task(normalized_task_id) or task
        summary = _task_list_summary(task)
        if cancel_skipped_reason:
            summary["cancelSkippedReason"] = cancel_skipped_reason
        if cancel_skipped_message:
            summary["cancelSkippedMessage"] = cancel_skipped_message
        return {
            "success": True,
            "task": summary,
            "cancelled": False,
            "cancelSkipped": True,
            "cancelSkippedReason": cancel_skipped_reason,
            "cancelSkippedMessage": cancel_skipped_message,
            "message": cancel_skipped_message or "任务当前无法取消",
        }
    task = _hydrate_task_runtime_fields(task)
    if not did_cancel:
        status = _normalized_task_status(task)
        if status in _SUCCESS_NOTIFICATION_TASK_STATUSES:
            cancel_skipped_reason = "task_already_completed"
            cancel_skipped_message = "任务已完成，无法取消。"
        elif status in {"cancelled", "canceled"}:
            cancel_skipped_reason = "task_already_cancelled"
            cancel_skipped_message = "任务已取消。"
        elif status in _FAILED_NOTIFICATION_TASK_STATUSES:
            cancel_skipped_reason = "task_already_failed"
            cancel_skipped_message = "任务已结束，无法取消。"
        else:
            cancel_skipped_reason = "task_not_active"
            cancel_skipped_message = "任务当前不在可取消状态。"
        summary = _task_list_summary(task)
        summary["cancelSkippedReason"] = cancel_skipped_reason
        summary["cancelSkippedMessage"] = cancel_skipped_message
        return {
            "success": True,
            "task": summary,
            "cancelled": False,
            "cancelSkipped": True,
            "cancelSkippedReason": cancel_skipped_reason,
            "cancelSkippedMessage": cancel_skipped_message,
            "message": cancel_skipped_message,
        }
    if did_cancel and task.get("type") in _VIDEO_GENERATION_TASK_TYPES and task.get("status") == "cancelled":
        _cancel_storyboard_video_version(task, str(task.get("message") or "已取消"))
        _emit_storyboard_video_task_project_changed(task, "storyboard_video_cancelled")
        _cancel_storyboard_video_provider_job_async(task)
    if did_cancel:
        task = _sync_canvas_task_record(task, changed_resources=["canvas_task"]) or task
        _emit_task_update(task, "task_cancelled")
        _maybe_report_agent_bound_generation_task(task, success=False)
    return {"success": True, "task": _task_list_summary(task)}
