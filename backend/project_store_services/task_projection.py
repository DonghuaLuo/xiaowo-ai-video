# -*- coding: utf-8 -*-
"""任务列表摘要、通知筛选和工作区展示去重。"""
from __future__ import annotations

from .agent_sessions import _persistent_media_data_removed
from .task_contract import _AGENT_GLOBAL_TASK_TYPES
from .task_contract import _task_focus_target
from .task_contract import _task_timestamp_seconds
from .task_control import _ACTIVE_GLOBAL_TASK_STATUSES
from .task_request_identity import _canvas_task_idempotency_key
from .task_storage import _TASK_LIST_SUMMARY_TEXT_LIMIT
from .task_storage import _task_list_summary_text
from .task_storage import _task_list_worker_run_summary
from typing import Any
import copy
import re


_TASK_LIST_SUMMARY_KEYS = {
    "promptOperation",
    "id",
    "type",
    "projectId",
    "episodeId",
    "nodeId",
    "nodeType",
    "clientRequestId",
    "idempotencyKey",
    "generationTaskType",
    "generationTaskNodeId",
    "resultNodeId",
    "outputNodeId",
    "versionNodeId",
    "versionId",
    "routeId",
    "routeLabel",
    "workChainId",
    "workChainLabel",
    "workChainTitle",
    "workChainName",
    "segmentId",
    "strategy",
    "modelId",
    "providerId",
    "estimatedCost",
    "consumedCost",
    "elapsedMs",
    "durationMs",
    "startedAt",
    "updatedAt",
    "completedAt",
    "failedAt",
    "cancelledAt",
    "failureReason",
    "errorSummary",
    "providerResponseSummary",
    "errorDebug",
    "traceback",
    "stackTrace",
    "assetType",
    "assetId",
    "assetName",
    "status",
    "progress",
    "message",
    "error",
    "agentAction",
    "workerName",
    "workerRunId",
    "sessionId",
    "executionId",
    "assetRangeId",
    "notice",
    "notificationClearedAt",
    "focusTarget",
    "projectEffect",
    "createdAt",
}


_TASK_LIST_TEXT_KEYS = {
    "message",
    "notice",
    "error",
    "failureReason",
    "errorSummary",
    "providerResponseSummary",
    "errorDebug",
    "traceback",
    "stackTrace",
}


_TASK_LIST_DEBUG_TEXT_LIMIT = 6000


_TASK_LIST_DEBUG_TEXT_KEYS = {"errorDebug", "traceback", "stackTrace"}


_TASK_LIST_COMPACT_DEBUG_KEYS = _TASK_LIST_DEBUG_TEXT_KEYS | {"providerResponseSummary"}


_TASK_LIST_WORKSPACE_DOCK_ACTIVE_STATUSES = {
    "created",
    "queued",
    "waiting",
    "waiting_upstream",
    "running",
    "processing",
    "paused",
}


_TASK_LIST_WORKSPACE_DOCK_NOTIFICATION_STATUSES = {
    "completed",
    "succeeded",
    "failed",
    "blocked",
    "preflight_failed",
}


_TASK_LIST_WORKSPACE_DOCK_CANVAS_TASK_TYPES = {
    "storyboard_image",
    "storyboard_image_edit",
    "visual_handoff_image",
    "storyboard_video",
    "route_video",
}


_TASK_LIST_PROJECT_EFFECT_SUMMARY_KEYS = {
    "action",
    "changedResources",
    "focusTarget",
    "nodeId",
    "notice",
    "opType",
    "projectChanged",
    "revision",
    "seq",
    "txId",
    "workflowVersion",
}


def _task_list_bool(payload: dict[str, Any], *keys: str, default: bool = False) -> bool:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off"}:
                return False
    return default


def _task_list_string_set(*values: Any) -> set[str]:
    result: set[str] = set()
    for value in values:
        if isinstance(value, (list, tuple, set)):
            rows = value
        elif isinstance(value, str):
            rows = re.split(r"[,，\s]+", value)
        elif value:
            rows = [value]
        else:
            rows = []
        for item in rows:
            text = str(item or "").strip()
            if text:
                result.add(text)
    return result


def _task_list_status(task: dict[str, Any]) -> str:
    return str(task.get("status") or "").strip()


def _task_list_has_uncleared_notification(task: dict[str, Any]) -> bool:
    return (
        str(task.get("type") or "").strip() not in _AGENT_GLOBAL_TASK_TYPES
        and _task_list_status(task) in _TASK_LIST_WORKSPACE_DOCK_NOTIFICATION_STATUSES
        and not task.get("notificationClearedAt")
    )


def _task_list_is_workspace_dock_visible(task: dict[str, Any]) -> bool:
    status = _task_list_status(task)
    return (
        status in _TASK_LIST_WORKSPACE_DOCK_ACTIVE_STATUSES
        or _task_list_has_uncleared_notification(task)
    )


def _task_list_node_value(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _task_list_workspace_dock_display_key(task: dict[str, Any]) -> str:
    task_type = str(task.get("generationTaskType") or task.get("type") or "").strip()
    if task_type in _TASK_LIST_WORKSPACE_DOCK_CANVAS_TASK_TYPES:
        focus_target = _task_focus_target(task)
        project_effect = task.get("projectEffect") if isinstance(task.get("projectEffect"), dict) else {}
        effect_focus = (
            project_effect.get("focusTarget")
            if isinstance(project_effect.get("focusTarget"), dict)
            else {}
        )
        project_id = str(task.get("projectId") or "").strip()
        episode_id = str(task.get("episodeId") or focus_target.get("episodeId") or "").strip()
        node_id = _task_list_node_value(
            task.get("generationTaskNodeId"),
            task.get("taskNodeId"),
            task.get("nodeId"),
            focus_target.get("nodeId"),
            effect_focus.get("nodeId"),
        )
        if project_id and episode_id and node_id:
            result_node_id = _task_list_node_value(
                task.get("resultNodeId"),
                task.get("outputNodeId"),
                task.get("versionNodeId"),
            )
            return _canvas_task_idempotency_key(
                task_type,
                project_id,
                episode_id,
                node_id,
                result_node_id=result_node_id,
                version_node_id=result_node_id,
            )
    idempotency_key = str(task.get("idempotencyKey") or task.get("idempotency_key") or "").strip()
    if idempotency_key:
        return f"intent:{idempotency_key}"
    task_id = str(task.get("id") or "").strip()
    return f"id:{task_id}" if task_id else ""


def _task_list_sort_timestamp(task: dict[str, Any]) -> float:
    value = (
        task.get("updatedAt")
        or task.get("completedAt")
        or task.get("failedAt")
        or task.get("startedAt")
        or task.get("createdAt")
    )
    return _task_timestamp_seconds(value) or 0.0


def _task_list_select_workspace_dock_row(
    current: dict[str, Any] | None,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    if current is None:
        return candidate
    current_active = _task_list_status(current) in _TASK_LIST_WORKSPACE_DOCK_ACTIVE_STATUSES
    candidate_active = _task_list_status(candidate) in _TASK_LIST_WORKSPACE_DOCK_ACTIVE_STATUSES
    if current_active != candidate_active:
        return candidate if candidate_active else current
    return candidate if _task_list_sort_timestamp(candidate) >= _task_list_sort_timestamp(current) else current


def _task_list_dedupe_workspace_dock_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for row in rows:
        key = _task_list_workspace_dock_display_key(row)
        if not key:
            unkeyed.append(row)
            continue
        by_key[key] = _task_list_select_workspace_dock_row(by_key.get(key), row)
    return sorted(
        [*by_key.values(), *unkeyed],
        key=_task_list_sort_timestamp,
        reverse=True,
    )


def _task_list_project_effect_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    summary = {
        key: _persistent_media_data_removed(copy.deepcopy(value.get(key)), key=key)
        for key in _TASK_LIST_PROJECT_EFFECT_SUMMARY_KEYS
        if value.get(key) is not None
    }
    records = value.get("records") if isinstance(value.get("records"), dict) else {}
    if records:
        summary["recordSummary"] = {
            bucket: len(rows)
            for bucket, rows in records.items()
            if isinstance(rows, list)
        }
    return summary or None


def _task_list_summary(
    task: dict[str, Any],
    *,
    include_debug: bool = False,
    include_worker_run: bool = True,
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key in _TASK_LIST_SUMMARY_KEYS:
        if key not in task:
            continue
        if not include_debug and key in _TASK_LIST_COMPACT_DEBUG_KEYS:
            continue
        if key == "projectEffect":
            value = _task_list_project_effect_summary(task.get(key))
            if value is None:
                continue
        else:
            value = _persistent_media_data_removed(task.get(key))
        if key in _TASK_LIST_TEXT_KEYS:
            limit = (
                _TASK_LIST_DEBUG_TEXT_LIMIT
                if key in _TASK_LIST_DEBUG_TEXT_KEYS
                else _TASK_LIST_SUMMARY_TEXT_LIMIT
            )
            value = _task_list_summary_text(value, limit)
        row[key] = value
    worker_run = _task_list_worker_run_summary(task.get("workerRun")) if include_worker_run else None
    if worker_run:
        task_status = str(task.get("status") or "").strip()
        worker_status = str(worker_run.get("status") or "").strip()
        if task_status not in _ACTIVE_GLOBAL_TASK_STATUSES and worker_status in _ACTIVE_GLOBAL_TASK_STATUSES:
            worker_run["status"] = task_status or "failed"
            if task.get("message") and not worker_run.get("message"):
                worker_run["message"] = _task_list_summary_text(task.get("message"))
            if task.get("notice") and not worker_run.get("notice"):
                worker_run["notice"] = _task_list_summary_text(task.get("notice"))
        row["workerRun"] = worker_run
        if not row.get("workerName"):
            row["workerName"] = worker_run.get("workerName") or worker_run.get("worker_name")
        if not row.get("workerRunId"):
            row["workerRunId"] = worker_run.get("workerRunId") or worker_run.get("worker_run_id")
    return row
