# -*- coding: utf-8 -*-
"""任务创建、取消状态、活动状态更新与结果提交控制。"""
from __future__ import annotations

from utils.generation_requests import GenerationCancelled
from utils.agent_execution_state import current_execution_id

import copy
import uuid
from datetime import datetime
from typing import Any, Callable, TypeVar

from .canvas_store_queries import episode_canvas_exists, read_canvas_card_record_v4
from .perf_logging import canvas_perf_elapsed_ms, canvas_perf_log, canvas_perf_start
from .store_core import _display_time
from .store_core import (
    _emit_agent_event,
    _now,
)
from .task_canvas_sync import (
    _defer_canvas_task_record_sync,
    _should_defer_canvas_task_record_sync,
    _sync_canvas_task_record,
    _task_canvas_episode_id,
    _task_canvas_node_id,
    _task_canvas_record_sync_mode,
)
from .task_storage import (
    _TASK_STORAGE_LOCK,
    _hydrate_task_runtime_fields,
    _load_task_storage_bucket,
    _normalized_task_status,
    _save_task_storage_bucket,
    _task_project_id,
    _task_storage_key_for_project,
    _task_storage_key_for_task_id,
)

_IntermediateResult = TypeVar("_IntermediateResult")


_ACTIVE_GLOBAL_TASK_STATUSES = {
    "created",
    "queued",
    "waiting",
    "waiting_upstream",
    "ready",
    "running",
    "processing",
    "paused",
}


def create_task(
    task_type: str,
    project_id: str | None = None,
    episode_id: str | None = None,
    node_id: str | None = None,
    message: str | None = None,
    status: str = "completed",
    progress: int | None = None,
    focus_target: dict[str, Any] | None = None,
    client_request_id: str | None = None,
    idempotency_key: str | None = None,
    request_signature: str | None = None,
    *,
    sync_canvas_task_record: bool = True,
    task_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Storage only: agent launchers bind the saved task after releasing their
    # outer task-storage locks and before starting execution.
    normalized_status = status if status in {"created", "running", "completed", "failed"} else "completed"
    task = {
        "id": f"task-{uuid.uuid4().hex[:10]}",
        "type": task_type,
        "projectId": project_id or "",
        "episodeId": episode_id,
        "nodeId": node_id,
        "status": normalized_status,
        "progress": int(progress if progress is not None else (100 if normalized_status == "completed" else 0)),
        "message": message or "任务已创建。",
        "createdAt": int(datetime.now().timestamp() * 1000),
    }
    normalized_client_request_id = str(client_request_id or "").strip()
    normalized_idempotency_key = str(idempotency_key or "").strip()
    normalized_request_signature = str(request_signature or "").strip()
    if normalized_client_request_id:
        task["clientRequestId"] = normalized_client_request_id
    if normalized_idempotency_key:
        task["idempotencyKey"] = normalized_idempotency_key
    if normalized_request_signature:
        task["requestSignature"] = normalized_request_signature
    if normalized_status == "running":
        task["startedAt"] = task["createdAt"]
    if isinstance(focus_target, dict):
        task["focusTarget"] = copy.deepcopy(focus_target)
    if isinstance(task_fields, dict):
        protected_fields = {
            "id",
            "type",
            "projectId",
            "episodeId",
            "nodeId",
            "status",
            "progress",
            "message",
            "createdAt",
            "startedAt",
        }
        initial_fields = copy.deepcopy(task_fields)
        for key, value in initial_fields.items():
            normalized_key = str(key or "").strip()
            if not normalized_key or normalized_key in protected_fields:
                continue
            task[normalized_key] = value
    identity = current_execution_id(task.get("sessionId"))
    if identity and task_type != "agent_turn":
        task["executionId"] = identity
    storage_key = _task_storage_key_for_project(project_id)
    with _TASK_STORAGE_LOCK:
        if normalized_status in {"created", "running"}:
            _assert_canvas_task_source_present(project_id, episode_id, node_id)
        tasks = _load_task_storage_bucket(storage_key)
        tasks.append(task)
        _save_task_storage_bucket(storage_key, tasks)
    if not sync_canvas_task_record:
        return task
    return _sync_canvas_task_record(task) or task


def _assert_canvas_task_source_present(project_id: str | None, episode_id: str | None, node_id: str | None) -> None:
    # Share the task lock with whole-chain deletion to close the launch/delete race.
    if project_id and episode_id and node_id and episode_canvas_exists(project_id, episode_id):
        try:
            read_canvas_card_record_v4(project_id, episode_id, node_id, detail="summary")
        except FileNotFoundError:
            raise ValueError("任务卡已删除，不能启动生成任务") from None


def is_task_cancelled(task_id: str | None) -> bool:
    task = _get_task(task_id)
    return _normalized_task_status(task or {}) in {"cancelled", "canceled"}


def _update_task_if_active(task_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update a task only while it is still active.

    Cancellation and worker completion can race.  Keeping the status check and
    update under the task lock prevents a cancelled task from being revived or
    overwritten by a late completion/failure.
    """
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return None
    sync_canvas_task_record_mode = _task_canvas_record_sync_mode(fields.pop("syncCanvasTaskRecord", True))
    storage_key = _task_storage_key_for_task_id(normalized_task_id)
    if not storage_key:
        return None
    updated: dict[str, Any] | None = None
    with _TASK_STORAGE_LOCK:
        tasks = _load_task_storage_bucket(storage_key)
        for index, task in enumerate(tasks):
            if str(task.get("id") or "") != normalized_task_id:
                continue
            if _normalized_task_status(task) not in _ACTIVE_GLOBAL_TASK_STATUSES:
                return None
            updated = {**task, **fields}
            tasks[index] = updated
            break
        if updated:
            _save_task_storage_bucket(storage_key, tasks)
    if not updated:
        return None
    if sync_canvas_task_record_mode == "none":
        return _hydrate_task_runtime_fields(updated)
    changed_resources = fields.get("changedResources") if isinstance(fields.get("changedResources"), list) else None
    if sync_canvas_task_record_mode == "deferred" or _should_defer_canvas_task_record_sync(updated, fields):
        return _defer_canvas_task_record_sync(updated, changed_resources=changed_resources)
    return _sync_canvas_task_record(updated, changed_resources=changed_resources)


def _begin_task_result_commit(
    task_id: str | None,
    *,
    message: str | None = None,
    sync_canvas_task_record: str | bool = True,
) -> dict[str, Any] | None:
    now_ms = int(datetime.now().timestamp() * 1000)
    fields: dict[str, Any] = {
        "resultCommitStartedAt": _display_time(_now()),
        "resultCommitStartedAtMs": now_ms,
        "updatedAt": now_ms,
    }
    if message:
        fields["message"] = message
    fields["syncCanvasTaskRecord"] = sync_canvas_task_record
    return _update_task_if_active(task_id, **fields)


def _get_task(task_id: str | None) -> dict[str, Any] | None:
    if not task_id:
        return None
    storage_key = _task_storage_key_for_task_id(str(task_id))
    if not storage_key:
        return None
    for task in _load_task_storage_bucket(storage_key):
        if str(task.get("id") or "") == str(task_id):
            return _hydrate_task_runtime_fields(task)
    return None


def _emit_task_update(task: dict[str, Any] | None, preferred_event: str = "task_progress") -> None:
    if not task:
        return
    status = str(task.get("status") or "")
    event_name = preferred_event
    if status == "completed":
        event_name = "task_completed"
    elif status in {"failed", "blocked", "preflight_failed"}:
        event_name = "task_failed"
    elif status == "cancelled":
        event_name = "task_cancelled"
    _emit_agent_event(event_name, task)


def _workflow_generation_task_id(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("taskId") or payload.get("task_id") or "").strip()


def _workflow_generation_task_session_fields(payload: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    session_id = str(payload.get("sessionId") or payload.get("session_id") or "").strip()
    return {"sessionId": session_id} if session_id else {}


_workflow_update_task_if_active = _update_task_if_active


def _workflow_generation_task_cancelled(payload: dict[str, Any] | None) -> bool:
    task_id = _workflow_generation_task_id(payload)
    if not task_id:
        return False

    checker = is_task_cancelled
    if not callable(checker):
        raise RuntimeError("任务取消状态检查入口不可用")
    return bool(checker(task_id))


def _raise_if_workflow_generation_task_cancelled(payload: dict[str, Any] | None) -> None:
    if _workflow_generation_task_cancelled(payload):
        raise RuntimeError("任务已取消")


def _workflow_begin_generation_result_commit(
    payload: dict[str, Any] | None,
    *,
    message: str = "正在保存生成结果。",
    task_types: set[str] | None = None,
) -> dict[str, Any] | None:
    task_id = _workflow_generation_task_id(payload)
    if not task_id:
        return None

    current_task_getter = _get_task
    if not callable(current_task_getter):
        raise RuntimeError("任务状态读取入口不可用")
    current_task = current_task_getter(task_id)
    if task_types:
        current_task_type = str((current_task or {}).get("type") or "").strip()
        if not current_task_type:
            raise RuntimeError("任务不存在或已取消")
        if current_task_type not in task_types:
            raise RuntimeError("任务类型不匹配，无法进入结果保存阶段")
    begin_commit = _begin_task_result_commit
    if not callable(begin_commit):
        raise RuntimeError("任务结果保存入口不可用")
    task = begin_commit(task_id, message=message)
    if not task:
        raise RuntimeError("任务已取消")
    return task


def run_task_intermediate_update(
    task_id: str, update: Callable[[], _IntermediateResult], *, task_types: set[str],
) -> _IntermediateResult:
    # A short intermediate write is atomic with cancellation, but does not seal the parent task.
    with _TASK_STORAGE_LOCK:
        task = _get_task(task_id)
        if not task or _normalized_task_status(task) not in _ACTIVE_GLOBAL_TASK_STATUSES:
            raise RuntimeError("任务已取消，中间结果未保存")
        if task.get("type") not in task_types:
            raise RuntimeError("任务类型不匹配，无法保存中间结果")
        return update()


def _task_cancelled(task_id: str) -> bool:
    task = _get_task(task_id)
    return not task or str(task.get("status") or "") == "cancelled"


def _update_task_fields(task_id: str | None, **fields: Any) -> dict[str, Any] | None:
    if not task_id:
        return None

    storage_key = _task_storage_key_for_task_id(str(task_id))
    if not storage_key:
        return None
    with _TASK_STORAGE_LOCK:
        tasks = _load_task_storage_bucket(storage_key)
        updated: dict[str, Any] | None = None
        for index, task in enumerate(tasks):
            if str(task.get("id") or "") != str(task_id):
                continue
            next_task = {**task, **fields}
            tasks[index] = next_task
            updated = next_task
            break
        if updated:
            _save_task_storage_bucket(storage_key, tasks)
        return updated


def _check_generation_task_cancelled(task_id: str | None) -> None:
    if not task_id:
        return
    if _task_cancelled(task_id):
        raise GenerationCancelled("生成任务已取消，结果未保存")


def _update_task_fields_and_sync_canvas(task_id: str | None, **fields: Any) -> dict[str, Any] | None:
    perf_started_at = canvas_perf_start()
    status = "ok"
    task: dict[str, Any] | None = None
    sync_canvas_task_record_mode = _task_canvas_record_sync_mode(fields.pop("syncCanvasTaskRecord", True))
    try:
        task = _update_task_fields(task_id, **fields)
        if sync_canvas_task_record_mode == "none":
            return task
        changed_resources = fields.get("changedResources") if isinstance(fields.get("changedResources"), list) else None
        if sync_canvas_task_record_mode == "deferred" or _should_defer_canvas_task_record_sync(task, fields):
            return _defer_canvas_task_record_sync(task, changed_resources=changed_resources)
        return _sync_canvas_task_record(
            task,
            changed_resources=changed_resources,
        )
    except Exception:
        status = "error"
        raise
    finally:
        canvas_perf_log(
            "update_task_fields",
            taskId=str(task_id or ""),
            projectId=_task_project_id(task),
            episodeId=_task_canvas_episode_id(task),
            nodeId=_task_canvas_node_id(task),
            taskType=str((task or {}).get("type") or ""),
            taskStatus=str((task or {}).get("status") or fields.get("status") or ""),
            status=status,
            durationMs=canvas_perf_elapsed_ms(perf_started_at),
            fieldCount=len(fields),
            changedResourceCount=len(fields.get("changedResources")) if isinstance(fields.get("changedResources"), list) else 0,
            syncCanvasTaskRecord=sync_canvas_task_record_mode,
        )


def _update_asset_image_task(task_id: str, preferred_event: str = "task_progress", **fields: Any) -> dict[str, Any] | None:
    fields["updatedAt"] = int(datetime.now().timestamp() * 1000)
    task = _update_task_if_active(task_id, **fields)
    _emit_task_update(task, preferred_event)
    return task


def _update_video_task(
    task_id: str,
    preferred_event: str = "task_progress",
    *,
    event_payload: dict[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any] | None:
    fields["updatedAt"] = int(datetime.now().timestamp() * 1000)
    task = _update_task_fields_and_sync_canvas(task_id, **fields)
    event_task = (
        {**task, **copy.deepcopy(event_payload)}
        if task and isinstance(event_payload, dict) and event_payload
        else task
    )
    _emit_task_update(event_task, preferred_event)
    return task


def _update_video_task_if_active(
    task_id: str,
    preferred_event: str = "task_progress",
    *,
    event_payload: dict[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any] | None:
    fields["updatedAt"] = int(datetime.now().timestamp() * 1000)
    task = _update_task_if_active(task_id, **fields)
    event_task = (
        {**task, **copy.deepcopy(event_payload)}
        if task and isinstance(event_payload, dict) and event_payload
        else task
    )
    _emit_task_update(event_task, preferred_event)
    return task
