"""Execution identity and monotonic session/worker state (no storage or IPC)."""
from __future__ import annotations

import copy
from contextvars import ContextVar
from typing import Any


EXECUTION_CONTEXT: ContextVar[tuple[str, str]] = ContextVar("agent_execution", default=("", ""))
TERMINAL_TASK_STATUSES = frozenset({"completed", "succeeded", "failed", "error", "blocked", "preflight_failed", "cancelled", "canceled"})


def execution_id(session: dict[str, Any]) -> str:
    return str((session.get("execution") or {}).get("id") or "")


def current_execution_id(session_id: str | None) -> str:
    owner, identity = EXECUTION_CONTEXT.get()
    return identity if owner == str(session_id or "") else ""


def accepts_execution(session: dict[str, Any], identity: str) -> bool:
    current = execution_id(session)
    return bool(current) and identity == current


def require_task_execution(task: dict[str, Any], session_id: str, identity: str) -> None:
    """Reusing a task never transfers ownership from its original execution."""
    if (not identity or task.get("sessionId") != session_id
            or task.get("executionId") != identity):
        raise RuntimeError("当前任务不属于本轮智能体执行，请等待任务结束或在原入口查看。")


def merge_worker_runs(previous: list[dict], incoming: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in [*previous, *incoming]:
        key = str(item.get("workerRunId") or "")
        if not key:
            continue
        old = merged.get(key)
        if old and old.get("status") in TERMINAL_TASK_STATUSES:
            continue
        merged[key] = copy.deepcopy(item)
    return list(merged.values())[-20:]


def bound_task_status(session: dict, tasks: list[dict]) -> str | None:
    """Only this execution's blocking tasks contribute to its completion."""
    execution = session.get("execution") or {}
    ids = set(execution.get("blockingTaskIds") or [])
    if not ids or not execution.get("dispatchClosed"):
        return None
    index = {str(task.get("id")): task for task in tasks}
    if any(key not in index for key in ids):
        return None
    statuses = {str(index[key].get("status") or "") for key in ids}
    if not statuses.issubset(TERMINAL_TASK_STATUSES):
        return "running"
    if execution.get("parentFailed"):
        return "error"
    if statuses & {"failed", "error", "blocked", "preflight_failed"}:
        return "error"
    if statuses & {"cancelled", "canceled"}:
        return "interrupted"
    return "completed"
