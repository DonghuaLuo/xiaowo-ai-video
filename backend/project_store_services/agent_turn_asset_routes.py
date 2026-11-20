# -*- coding: utf-8 -*-
"""资产范围与分集边界的回合选择、策略预检和控制器结果处理。"""
from __future__ import annotations

import traceback
from typing import (
    Any,
)
from .agent_asset_cleanup import (
    _agent_current_canvas_clear_pending_operation,
    _agent_latest_asset_range_delete_pending_operation,
    _agent_project_asset_cleanup_pending_operation,
)
from .agent_result_presentation import (
    _agent_episode_session_project_delete_rejection,
    _agent_controller_decision_from_result,
)
from .agent_progress_recommendations import (
    _agent_progress_message,
    _agent_progress_state,
)
from .agent_contracts import (
    _agent_steps_from_state,
)
from .agent_sessions import (
    append_agent_execution_error,
)


def _resolve_latest_asset_range_delete_turn(
    project_id: str,
    message: str,
    session_id: str | None,
    context_scope_value: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    if context_scope_value == "episode":
        return _agent_episode_session_project_delete_rejection(state, task_type="asset_range_delete_latest")
    controller_result = _agent_latest_asset_range_delete_pending_operation(project_id, session_id, message)
    decision = _agent_controller_decision_from_result(
        controller_result,
        {
            "source": "local-controller",
            "taskHypothesis": {
                "taskType": "asset_range_delete_latest",
                "routeSource": "explicit_delete_latest_asset_range",
            },
        },
    )
    return {
        "success": True,
        "message": str(decision.get("reply") or "").strip(),
        "contentBlocks": decision.get("contentBlocks") or [],
        "steps": _agent_steps_from_state(state),
        "pendingQuestion": None,
        "project": state["project"],
        "agentModelMeta": decision.get("modelMeta") or {},
        "sessionStatus": "idle",
        "pendingOperation": decision.get("pendingOperation"),
    }


def _resolve_project_cleanup_turn(
    project_id: str,
    episode_id: str | None,
    message: str,
    session_id: str | None,
    routing_message: str,
    context_scope_value: str,
    progress_episode_id: str | None,
    state: dict[str, Any],
    selected_episode_id: str,
) -> dict[str, Any] | None:
    try:
        if context_scope_value == "episode":
            controller_result = _agent_current_canvas_clear_pending_operation(
                project_id,
                selected_episode_id,
                session_id,
                message,
                episode_title=str(state.get("selectedEpisodeTitle") or selected_episode_id),
            )
        else:
            controller_result = _agent_project_asset_cleanup_pending_operation(project_id, session_id, message)
        decision = _agent_controller_decision_from_result(
            controller_result,
            {
                "source": "local-controller",
                "taskHypothesis": {
                    "taskType": "project_cleanup",
                    "routeSource": "explicit_cleanup_requires_confirmation",
                },
            },
        )
    except Exception as exc:  # noqa: BLE001
        append_agent_execution_error(
            project_id,
            stage="project_asset_cleanup_confirm_prepare",
            message="项目资产清空确认准备失败",
            episode_id=episode_id,
            session_id=session_id,
            category="agent_controller_error",
            source="agent_controller",
            error=exc,
            details={"message": routing_message},
            include_traceback=True,
        )
        print(traceback.format_exc(), flush=True)
        decision = _agent_controller_decision_from_result(
            {
                "success": False,
                "message": f"项目资产清空确认准备失败：{exc}",
                "pendingOperation": None,
            },
            {"source": "local-controller", "error": str(exc)},
        )
    success = bool(decision.get("success", True))
    result = {
        "success": success,
        "message": str(decision.get("reply") or "").strip() or _agent_progress_message(state, routing_message),
        "contentBlocks": decision.get("contentBlocks") or [],
        "steps": _agent_steps_from_state(_agent_progress_state(project_id, progress_episode_id)),
        "pendingQuestion": decision.get("pendingQuestion"),
        "project": _agent_progress_state(project_id, progress_episode_id)["project"],
        "agentModelMeta": decision.get("modelMeta") or {},
        "sessionStatus": "idle" if success else "error",
    }
    if "pendingOperation" in decision:
        result["pendingOperation"] = decision.get("pendingOperation")
    return result


def _resolve_asset_range_turn(
    project_id: str,
    episode_id: str | None,
    message: str,
    session_id: str | None,
    session_policy: dict[str, Any] | None,
    routing_message: str,
    context_scope_value: str,
    progress_episode_id: str | None,
    state: dict[str, Any],
    selected_episode_id: str,
    selected_preferred_task_type: str,
    pending_operation_context: dict[str, Any],
    pending_operation_type: str,
    pending_requires_semantic_probe: bool,
) -> dict[str, Any] | None:
    if selected_preferred_task_type == "asset_range_delete_latest" and not pending_requires_semantic_probe:
        return _resolve_latest_asset_range_delete_turn(
            project_id=project_id,
            message=message,
            session_id=session_id,
            context_scope_value=context_scope_value,
            state=state,
        )

    if selected_preferred_task_type == "project_cleanup" and not pending_requires_semantic_probe:
        return _resolve_project_cleanup_turn(
            project_id=project_id,
            episode_id=episode_id,
            message=message,
            session_id=session_id,
            routing_message=routing_message,
            context_scope_value=context_scope_value,
            progress_episode_id=progress_episode_id,
            state=state,
            selected_episode_id=selected_episode_id,
        )

    return None
