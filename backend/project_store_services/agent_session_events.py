# -*- coding: utf-8 -*-
"""会话事件载荷与广播。"""
from __future__ import annotations

from .agent_sessions import (
    _agent_session_detail,
    _agent_session_summaries,
    _agent_snapshot_from_session,
    _normalize_agent_live_activity,
)
from .store_core import (
    _emit_agent_event,
)

from typing import Any


def _agent_session_payload(
    project_id: str,
    episode_id: str | None,
    session: dict[str, Any],
    *,
    message: str = "",
    steps: list[dict[str, Any]] | None = None,
    pending_question: dict[str, Any] | None = None,
    client_action: dict[str, Any] | None = None,
    project_effect: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "projectId": project_id,
        "episodeId": episode_id or session.get("episodeId"),
        "message": message,
        "steps": steps or session.get("steps") or [],
        "pendingQuestion": pending_question,
        "clientAction": client_action,
        "projectEffect": project_effect,
        "session": _agent_session_detail(project_id, session),
        "sessions": _agent_session_summaries(project_id, str(episode_id or session.get("episodeId") or "")),
    }


def _emit_agent_session_update(
    project_id: str,
    episode_id: str | None,
    session: dict[str, Any],
    *,
    message: str = "",
    steps: list[dict[str, Any]] | None = None,
    pending_question: dict[str, Any] | None = None,
    client_action: dict[str, Any] | None = None,
    project_effect: dict[str, Any] | None = None,
    live_activity: list[dict[str, Any]] | None = None,
) -> None:
    payload = _agent_session_payload(
        project_id,
        episode_id,
        session,
        message=message,
        steps=steps,
        pending_question=pending_question,
        client_action=client_action,
        project_effect=project_effect,
    )
    _emit_agent_event(
        "agent_session_updated",
        payload,
    )
    _emit_agent_event(
        "agent_session_snapshot",
        {
            **payload,
            "snapshot": _agent_snapshot_from_session(
                project_id,
                session,
                live_activity=_normalize_agent_live_activity(live_activity or []),
            ),
        },
    )
