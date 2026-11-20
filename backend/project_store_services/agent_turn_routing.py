# -*- coding: utf-8 -*-
"""显式动作路由与模型回答、无模型回退的阶段处理。"""
from __future__ import annotations

from .agent_action_contract import (
    _agent_action_label,
)
from .agent_progress_recommendations import (
    _agent_progress_message,
    _agent_project_effect_for_action,
    _agent_project_status_result,
    _agent_tool_result_summary,
)
from .agent_result_presentation import (
    _agent_session_policy_rejection,
)
from .agent_sessions import (
    append_agent_execution_error,
)
from .agent_session_policy import (
    validate_agent_session_action,
)

from .agent_action_contract import (
    _agent_program_action_from_message,
    _agent_program_direct_actions,
)
from .agent_contracts import (
    _agent_steps_from_state,
)
from .agent_operation_catalog import (
    agent_operation_high_risk,
)
from .agent_pending_operations import (
    _agent_message_cancels_destructive_operation,
    _agent_message_confirms,
    _agent_message_confirms_destructive_operation,
    _agent_message_is_pending_operation_confirmation_reply,
    _agent_pending_operation_can_resolve_locally,
    _agent_pending_operation_requires_semantic_probe,
)
from .agent_production_controller import (
    _execute_agent_action,
)
from .agent_progress_recommendations import (
    _agent_progress_state,
)
from .source_text_store import _compact_text

from typing import Any


def _agent_result_used_sdk_stream(result: dict[str, Any]) -> bool:
    meta = result.get("agentModelMeta") if isinstance(result.get("agentModelMeta"), dict) else {}
    return str(meta.get("source") or "") == "claude-agent-sdk" and not str(meta.get("error") or "").strip()


def _agent_turn_requires_sdk_runtime(
    message: str,
    state: dict[str, Any],
    selected_preferred_action: str,
    selected_preferred_task_type: str,
    pending_operation_context: dict[str, Any] | None = None,
) -> bool:
    pending = pending_operation_context if isinstance(pending_operation_context, dict) else {}
    pending_operation_type = str(pending.get("operationType") or "").strip()
    pending_kind = str(pending.get("kind") or "").strip()
    if pending.get("active") and agent_operation_high_risk(pending_kind):
        if (
            _agent_message_cancels_destructive_operation(message)
            or _agent_message_confirms_destructive_operation(message, pending_operation_type)
            or _agent_message_confirms(message)
        ):
            return False
    if _agent_pending_operation_can_resolve_locally(message, pending_operation_context):
        return False
    if selected_preferred_task_type == "project_status":
        return False
    if _agent_pending_operation_requires_semantic_probe(message, pending_operation_context):
        return True
    if (
        pending.get("active")
        and pending_operation_type == "commit_episode_boundary"
        and _agent_message_is_pending_operation_confirmation_reply(message, pending)
    ):
        return False
    if selected_preferred_action:
        return selected_preferred_action not in _agent_program_direct_actions()
    if selected_preferred_task_type in {"project_cleanup", "asset_range_delete_latest"}:
        return False
    if selected_preferred_task_type in {
        "asset_range_propose",
        "video_prompt_generation",
        "asset_extraction",
        "episode_boundary_propose",
        "storyboard_image_generation",
        "visual_handoff_image_generation",
        "storyboard_video_generation",
    }:
        return False
    if (
        not selected_preferred_action
        and not selected_preferred_task_type
        and _agent_program_action_from_message(message, state)
    ):
        return False
    if selected_preferred_task_type:
        return True
    return True


def _resolve_selected_program_action(
    project_id: str,
    message: str,
    images: list[dict[str, Any]] | None,
    session_id: str | None,
    assistant_notice: str,
    session_policy: dict[str, Any] | None,
    routing_message: str,
    progress_episode_id: str | None,
    state: dict[str, Any],
    selected_action: str,
    selected_preferred_task_type: str,
    pending_requires_semantic_probe: bool,
) -> dict[str, Any] | None:
    if selected_action:
        # selected_action 只能来自结构化快捷入口、智能体推荐项或上一轮追问选择；
        # 普通用户文本不会在这里被解析成任意 action。
        result = _execute_agent_action(
            project_id,
            progress_episode_id,
            selected_action,
            message=message,
            images=images,
            session_id=session_id,
            state=state,
        )
        notice = str(assistant_notice or "").strip()
        result["agentAction"] = selected_action
        result["agentThinking"] = notice or f"根据用户选择继续执行：{_agent_action_label(selected_action, state)}。"
        result["agentState"] = state
        result["projectEffect"] = _agent_project_effect_for_action(selected_action, state)
        result["toolResult"] = _agent_tool_result_summary(selected_action, result["agentState"], result)
        action_message = str(result.get("message") or "").strip()
        if notice and action_message and notice not in action_message:
            result["message"] = f"{notice}\n\n{action_message}"
        elif notice and not action_message:
            result["message"] = notice
        return result
    direct_program_action = (
        ""
        if selected_preferred_task_type
        else str(_agent_program_action_from_message(routing_message, state) or "")
    )
    if direct_program_action and not pending_requires_semantic_probe:
        try:
            validate_agent_session_action(direct_program_action, session_policy)
        except ValueError as exc:
            return _agent_session_policy_rejection(
                state,
                exc,
                task_type="overview_request" if direct_program_action == "analyze_overview" else "project_status",
                route_source="program_action_session_policy_rejected",
            )
        result = _execute_agent_action(
            project_id,
            progress_episode_id,
            direct_program_action,
            message=routing_message,
            images=images,
            session_id=session_id,
            state=state,
        )
        result["agentAction"] = direct_program_action
        result["agentThinking"] = f"根据用户选择继续执行：{_agent_action_label(direct_program_action, state)}。"
        result["agentState"] = state
        result["projectEffect"] = _agent_project_effect_for_action(direct_program_action, state)
        result["toolResult"] = _agent_tool_result_summary(direct_program_action, result["agentState"], result)
        return result
