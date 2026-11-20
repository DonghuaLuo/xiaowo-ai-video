# -*- coding: utf-8 -*-
"""任务类型、状态、错误信息和会话绑定协议。"""
from __future__ import annotations
from .canvas_ownership import VIDEO_TASK_NODE_TYPES

from .agent_contracts import AGENT_GENERATION_TASKS
from typing import Any
from typing import TypeVar
import re
import time


_SUCCESS_NOTIFICATION_TASK_STATUSES = {"completed", "succeeded"}


_FAILED_NOTIFICATION_TASK_STATUSES = {"failed", "blocked", "preflight_failed"}


_CLEARABLE_NOTIFICATION_TASK_STATUSES = (
    _SUCCESS_NOTIFICATION_TASK_STATUSES | _FAILED_NOTIFICATION_TASK_STATUSES
)


_WORKFLOW_NODE_TASK_TYPES = {
    "storyboard_image",
    "storyboard_image_edit",
    "visual_handoff_image",
    "storyboard_video",
    "workflow",
    "workflow_node",
    "route_video",
}


_EPISODE_DERIVED_TASK_TYPES = _WORKFLOW_NODE_TASK_TYPES


_AGENT_GLOBAL_TASK_TYPES = {
    "agent_turn",
}


_BACKGROUND_STORYBOARD_TASK_TYPES = {
    "storyboard_image",
    "visual_handoff_image",
    "storyboard_video",
    "workflow",
    "home_archive_export",
    "home_archive_import",
    "jianying_draft_export",
    "video_files_export",
}


_STORYBOARD_VIDEO_TASK_NODE_TYPES = VIDEO_TASK_NODE_TYPES


_STALE_WORKFLOW_TASK_MESSAGE = "任务绑定的画布节点已不存在，已停止显示为执行中。"


_STALE_AGENT_TASK_MESSAGE = "智能体后台任务已无对应运行线程，已停止显示为执行中。"


_STALE_STORYBOARD_TASK_MESSAGE = "生成后台任务已无对应运行线程，已停止显示为执行中。"


_STALE_ASSET_IMAGE_TASK_MESSAGE = "资产图后台任务已无对应运行线程，已停止显示为执行中。"


_STALE_TASK_MESSAGES = {
    _STALE_WORKFLOW_TASK_MESSAGE,
    _STALE_AGENT_TASK_MESSAGE,
    _STALE_STORYBOARD_TASK_MESSAGE,
    _STALE_ASSET_IMAGE_TASK_MESSAGE,
}


def _storyboard_video_task_node_type(node_type: Any) -> bool:
    return str(node_type or "").strip() in _STORYBOARD_VIDEO_TASK_NODE_TYPES


def _clean_task_error_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "").strip()
    if not text or text == "NoneType: None":
        return ""
    text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,}\]]+", r"\1<redacted>", text)
    text = re.sub(
        r"(?i)((?:api[_-]?key|apiKey|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+",
        r"\1<redacted>",
        text,
    )
    text = re.sub(r"\s+\n", "\n", text).strip()
    if len(text) > limit:
        return f"{text[:limit].rstrip()}...（已截断）"
    return text


def _is_stale_task_message(value: Any) -> bool:
    return str(value or "").strip() in _STALE_TASK_MESSAGES


def _task_failure_fields(
    reason: Any,
    *,
    prefix: str = "任务执行失败",
    traceback_text: str = "",
    provider_response: Any = None,
) -> dict[str, Any]:
    failure_reason = _clean_task_error_text(reason, 3000)
    provider_summary = _clean_task_error_text(provider_response, 3000)
    debug_text = _clean_task_error_text(traceback_text, 6000)
    summary = failure_reason
    if prefix and failure_reason and not failure_reason.startswith(prefix):
        summary = f"{prefix}：{failure_reason}"
    elif prefix and not failure_reason:
        summary = prefix
    fields: dict[str, Any] = {
        "message": summary or "任务执行失败。",
        "notice": summary or "任务执行失败。",
        "failureReason": failure_reason,
        "errorSummary": summary or failure_reason,
        "error": failure_reason,
    }
    if provider_summary:
        fields["providerResponseSummary"] = provider_summary
    if debug_text:
        fields["errorDebug"] = debug_text
    return fields


def _task_focus_target(task: dict[str, Any]) -> dict[str, Any]:
    focus_target = task.get("focusTarget")
    if isinstance(focus_target, dict):
        return focus_target
    project_effect = task.get("projectEffect")
    if isinstance(project_effect, dict) and isinstance(project_effect.get("focusTarget"), dict):
        return project_effect["focusTarget"]
    return {}


def _task_workflow_node_id(task: dict[str, Any]) -> str:
    node_id = str(task.get("nodeId") or task.get("node_id") or "").strip()
    if node_id:
        return node_id
    focus_target = _task_focus_target(task)
    return str(focus_target.get("nodeId") or focus_target.get("node_id") or "").strip()


def _task_client_request_id_from_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("clientRequestId", "client_request_id", "requestId", "request_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value[:160]
    return ""


def _task_idempotency_part(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text.replace("|", "%7C")


def _task_timestamp_seconds(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed > 10_000_000_000:
        return parsed / 1000
    return parsed


def _task_age_seconds(task: dict[str, Any]) -> float | None:
    timestamp = _task_timestamp_seconds(task.get("updatedAt") or task.get("createdAt"))
    if timestamp is None:
        return None
    return max(0.0, time.time() - timestamp)


def _task_agent_session_id(task: dict[str, Any]) -> str:
    return str(task.get("sessionId") or "").strip()


_AGENT_SESSION_BOUND_CANCEL_TASK_TYPES = AGENT_GENERATION_TASKS.keys()


def _task_session_id_from_payload(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("sessionId") or "").strip()


def _task_agent_session_fields(session_id: str | None) -> dict[str, str]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return {}
    return {"sessionId": normalized_session_id}


def _task_result_commit_started(task: dict[str, Any] | None) -> bool:
    if not isinstance(task, dict):
        return False
    return bool(str(task.get("resultCommitStartedAt") or "").strip())


_IntermediateResult = TypeVar("_IntermediateResult")
