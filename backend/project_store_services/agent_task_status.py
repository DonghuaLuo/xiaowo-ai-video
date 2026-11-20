"""智能体会话任务的活动状态与安全错误摘要。"""

from __future__ import annotations

import re
from typing import Any


def _agent_task_error_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "").strip()
    if not text or text == "NoneType: None":
        return ""
    text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,}\]]+", r"\1<redacted>", text)
    text = re.sub(
        r"(?i)((?:api[_-]?key|apiKey|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+",
        r"\1<redacted>",
        text,
    )
    if len(text) > limit:
        return f"{text[:limit].rstrip()}...（已截断）"
    return text


def _agent_task_failure_fields(reason: Any, traceback_text: Any = "") -> dict[str, Any]:
    failure_reason = _agent_task_error_text(reason, 3000)
    debug_text = _agent_task_error_text(traceback_text, 6000)
    fields: dict[str, Any] = {
        "failureReason": failure_reason,
        "errorSummary": failure_reason,
        "error": failure_reason,
    }
    if debug_text:
        fields["errorDebug"] = debug_text
    return fields


def _agent_update_task_if_active(task_id: str | None, **fields: Any) -> dict[str, Any] | None:
    from . import task_control as task_control

    active_updater = getattr(task_control, "_update_task_if_active", None)
    if not callable(active_updater):
        raise RuntimeError("任务活动状态更新入口不可用")
    return active_updater(task_id, **fields)
