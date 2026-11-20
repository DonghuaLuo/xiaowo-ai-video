# -*- coding: utf-8 -*-
"""会话历史读取与回合/意图对话上下文组装。"""
from __future__ import annotations

from .agent_contracts import (
    agent_target_for_scope as _agent_active_target_for_scope,
)
from .agent_session_policy import (
    agent_session_context_scope,
)
from .agent_sessions import (
    set_agent_conversation_context,
)

from typing import Any
from utils import agent_sdk_runtime
from utils.agent_context import AGENT_CONTEXT_RECENT_WINDOW, build_agent_conversation_context, build_agent_intent_conversation_context
from .agent_sessions import (
    _agent_message_is_control_only,
    _load_agent_sessions,
    _normalize_agent_history_summary,
    _normalize_agent_message_rows,
)

def _agent_session_messages_for_prompt(
    project_id: str,
    session_id: str | None,
    *,
    current_message: str = "",
) -> list[dict[str, Any]]:
    if not session_id:
        return []
    session = next(
        (
            row
            for row in _load_agent_sessions(project_id)
            if str(row.get("id") or "") == str(session_id)
        ),
        None,
    )
    if not isinstance(session, dict):
        return []
    messages = _normalize_agent_message_rows(session.get("messages"), project_id)
    current_text = str(current_message or "").strip()
    if current_text and messages:
        last = messages[-1]
        if str(last.get("role") or "") == "user" and str(last.get("text") or "").strip() == current_text:
            messages = messages[:-1]
    messages = [
        row
        for row in messages
        if not _agent_message_is_control_only(row)
    ]
    return messages


def _agent_session_history_summary_for_prompt(project_id: str, session_id: str | None) -> str:
    if not session_id:
        return ""
    session = next(
        (
            row
            for row in _load_agent_sessions(project_id)
            if str(row.get("id") or "") == str(session_id)
        ),
        None,
    )
    if not isinstance(session, dict):
        return ""
    return _normalize_agent_history_summary(session.get("historySummary"))


def _agent_sdk_session_id_for_resume(project_id: str, session_id: str | None) -> str | None:
    if not session_id:
        return None
    session = next(
        (
            row
            for row in _load_agent_sessions(project_id)
            if str(row.get("id") or "") == str(session_id)
        ),
        None,
    )
    if not isinstance(session, dict):
        return None
    if str(session.get("sdkContextVersion") or "") != agent_sdk_runtime.SDK_CONTEXT_VERSION:
        return None
    sdk_session_id = str(session.get("sdkSessionId") or session.get("sdk_session_id") or "").strip()
    return sdk_session_id or None


def _agent_conversation_context_for_prompt(
    project_id: str,
    session_id: str | None,
    *,
    current_message: str = "",
    limit: int = AGENT_CONTEXT_RECENT_WINDOW,
) -> dict[str, Any]:
    messages = _agent_session_messages_for_prompt(
        project_id,
        session_id,
        current_message=current_message,
    )
    return build_agent_conversation_context(
        session_id=session_id,
        messages=messages,
        history_summary=_agent_session_history_summary_for_prompt(project_id, session_id),
        limit=limit,
    )


def _agent_intent_conversation_context_for_prompt(
    project_id: str,
    session_id: str | None,
    *,
    current_message: str = "",
    limit: int = 2,
) -> dict[str, Any]:
    messages = _agent_session_messages_for_prompt(
        project_id,
        session_id,
        current_message=current_message,
    )
    return build_agent_intent_conversation_context(
        messages=messages,
        limit=limit,
    )


def _agent_turn_context_scope(scope: str | None, episode_id: str | None) -> str:
    return agent_session_context_scope(scope, episode_id)


def _agent_turn_session_episode_id(scope: str, selected_episode_id: str | None) -> str:
    if scope == "project":
        return "__project__"
    return str(selected_episode_id or "").strip() or "E01"


def _agent_turn_workflow_id(
    *,
    scope: str,
    project_id: str,
    selected_episode_id: str | None,
    workflow_id: str | None,
) -> str:
    value = str(workflow_id or "").strip()
    if value:
        return value
    if scope == "project":
        return f"project:{project_id}"
    return f"episode:{str(selected_episode_id or 'E01')}:workflow"


def _apply_agent_session_context(
    session: dict[str, Any],
    *,
    scope: str,
    episode_id: str,
    workflow_id: str | None = None,
) -> None:
    existing_scope = str(session.get("scope") or session.get("contextScope") or "").strip()
    existing_episode_id = str(session.get("episodeId") or "").strip()
    if existing_scope and existing_scope != scope:
        raise ValueError("会话类型不可变，请创建对应类型的新会话")
    if existing_episode_id and existing_episode_id != episode_id:
        raise ValueError("会话所属分集不可变，请切换到对应分集会话")
    session["episodeId"] = episode_id
    session["scope"] = scope
    session["contextScope"] = scope
    workflow_id_value = str(workflow_id or "").strip()
    if workflow_id_value:
        session["workflowId"] = workflow_id_value


def _save_agent_turn_conversation_context(
    project_id: str,
    episode_id: str,
    *,
    scope: str,
    session_id: str,
    workflow_id: str,
    active_target: dict[str, Any] | None = None,
) -> None:
    try:
        scoped_active_target = _agent_active_target_for_scope(scope, active_target)
        set_agent_conversation_context(
            project_id,
            None if scope == "project" else episode_id,
            {
                "scope": scope,
                "sessionId": session_id,
                "workflowId": workflow_id,
                "activeTarget": scoped_active_target,
            },
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[agent-context] failed to save conversation context: {exc}", flush=True)
