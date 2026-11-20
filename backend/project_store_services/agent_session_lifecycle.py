# -*- coding: utf-8 -*-
"""回合路由协调：范围与策略预检后，按业务阶段返回首个已处理结果。"""
from __future__ import annotations

from .agent_progress_recommendations import (
    _agent_bind_production_continuation,
    _agent_progress_state,
)
from .agent_contracts import _agent_steps_from_state
from .agent_sessions import (
    _agent_message_attachment_rows,
)
from .agent_scope_hints import (
    _agent_message_requests_episode_detail,
)
from .agent_pending_operations import (
    _agent_pending_operation_context,
    _agent_pending_operation_contexts,
    _agent_message_is_pending_operation_protocol_reply,
    _agent_pending_operation_requires_semantic_probe,
    _agent_message_is_pending_operation_confirmation_reply,
)
from .agent_result_presentation import (
    _agent_session_policy_rejection,
    _agent_session_task_policy_rejection,
)
from .agent_conversation_context import (
    _agent_turn_context_scope,
)
from .agent_action_contract import (
    _agent_validate_action,
    _agent_validate_task_type,
)
from .agent_operation_catalog import agent_operation_reply
from .agent_turn_asset_routes import (
    _resolve_asset_range_turn,
)
from .agent_native_episode import run_native_episode_turn
from .agent_native_chat import run_native_chat_turn
from .agent_episode_confirmation import cancel_episode_boundary_locally, confirm_episode_boundary_locally
from .agent_asset_range_confirmation import cancel_asset_range_locally, confirm_asset_range_locally
from .agent_turn_routing import (
    _resolve_selected_program_action,
)
from .agent_turn_tools import BUSINESS_TASK_HANDOFF_TYPES
from .agent_turn_pending import (
    _resolve_pending_turn_operation,
)
from .agent_production_controller import (
    _resolve_production_turn,
)
from .agent_session_policy import (
    build_agent_session_policy,
    validate_agent_session_action,
)
from typing import Any, Callable


_NATIVE_GENERAL_TASK_TYPES = frozenset({
    "free_chat", "work_chain_plan_discuss", "asset_query", "asset_content_update",
    "asset_update", "project_content_update", "settings_update",
    "shot_prompt_patch", "workflow_node_content_update", "workflow_node_update",
    "workflow_update", "asset_image_generation", "generation_request",
    "media_file_request", "quality_review",
})


def _agent_state_for_canvas_owner(project_id: str, scope: str, canvas_key: str | None,
                                  state: dict[str, Any]) -> dict[str, Any]:
    if scope != "episode" or not canvas_key:
        return state
    from .canvas_store_queries import get_canvas_context_v4
    if get_canvas_context_v4(project_id, canvas_key).get("canvasKind") != "custom":
        return state
    # Custom canvas storage keys own their own episode-scope sessions.
    # Project production progress may otherwise point at E01 and leak its
    # allowedEpisodeIds into this canvas's MCP tool policy.
    return {**state, "selectedEpisodeId": canvas_key,
            "projectScope": False, "productionStatus": {}}

def _resolve_agent_turn_result(
    project_id: str,
    episode_id: str | None,
    message: str = "",
    images: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    preferred_action: str | None = None,
    preferred_task_type: str | None = None,
    assistant_notice: str = "",
    active_target: dict[str, Any] | None = None,
    context_scope: str | None = None,
    session_policy: dict[str, Any] | None = None,
    control_intent_message: str = "",
    control_only: bool = False,
    candidate_ref: dict[str, Any] | None = None,
    task_options: dict[str, Any] | None = None,
    on_pending_handoff: Callable[[dict[str, Any], str, list[dict[str, Any]], bool], None] | None = None,
) -> dict[str, Any]:
    images = _agent_message_attachment_rows(images or [], project_id)
    routing_message = str(control_intent_message or message or "").strip()
    context_scope_value = _agent_turn_context_scope(context_scope, episode_id)
    progress_episode_id = None if context_scope_value == "project" else episode_id
    state = _agent_progress_state(
        project_id,
        progress_episode_id,
        detail_mode=context_scope_value == "episode" or _agent_message_requests_episode_detail(routing_message),
    )
    state = _agent_state_for_canvas_owner(project_id, context_scope_value, progress_episode_id, state)
    selected_episode_id = str(state.get("selectedEpisodeId") or progress_episode_id or episode_id or "E01")
    session_policy = session_policy if isinstance(session_policy, dict) else build_agent_session_policy(
        project_id,
        scope=context_scope_value,
        episode_id=progress_episode_id,
        selected_episode_id=selected_episode_id,
    )
    selected_action = _agent_validate_action(preferred_action) if preferred_action else ""
    selected_preferred_task_type = (
        "" if selected_action else _agent_validate_task_type(preferred_task_type)
    )
    pending_contexts = _agent_pending_operation_contexts(project_id, session_id)
    active_pending_contexts = [item for item in pending_contexts if item.get("active")]
    pending_operation_context = _agent_pending_operation_context(project_id, session_id)
    pending_decision = (
        task_options.get("pendingDecision")
        if isinstance(task_options, dict) and isinstance(task_options.get("pendingDecision"), dict)
        else None
    )
    confirmed_by_action = False
    if pending_decision is not None:
        if selected_action or selected_preferred_task_type:
            return _agent_session_policy_rejection(
                state, ValueError("待确认操作不能同时启动其他任务"),
                task_type="project_status", route_source="pending_decision_conflict",
            )
        pending_operation_context = next((item for item in active_pending_contexts if (
            str(pending_decision.get("sessionId") or "") == str(item.get("sessionId") or session_id or "")
            and str(pending_decision.get("pendingOperationId") or "") == str(item.get("pendingOperationId") or "")
            and str(pending_decision.get("operationType") or "") == str(item.get("operationType") or "")
            and str(pending_decision.get("createdAt") or "") == str(item.get("createdAt") or "")
            and str(pending_decision.get("candidateId") or "") == str(item.get("candidateId") or "")
        )), {})
        matches = (
            pending_operation_context.get("active")
            and str(pending_decision.get("sessionId") or "") == str(session_id or "")
            and str(pending_decision.get("operationType") or "") == str(pending_operation_context.get("operationType") or "")
            and str(pending_decision.get("createdAt") or "") == str(pending_operation_context.get("createdAt") or "")
            and str(pending_decision.get("candidateId") or "") == str(pending_operation_context.get("candidateId") or "")
            and str(pending_decision.get("pendingOperationId") or "") == str(pending_operation_context.get("pendingOperationId") or "")
            and (not pending_operation_context.get("candidateId") or (
                str(pending_decision.get("runId") or "") == str(pending_operation_context.get("runId") or "")
                and str(pending_decision.get("candidateDigest") or "") == str(pending_operation_context.get("candidateDigest") or "")
                and pending_decision.get("candidateVersion") == pending_operation_context.get("candidateVersion")
            ))
        )
        choice = str(pending_decision.get("decision") or "").strip()
        if not matches or choice not in {"confirm", "cancel"}:
            return _agent_session_policy_rejection(
                state, ValueError("待确认操作已变化，请重新查看当前候选"),
                task_type="project_status", route_source="pending_decision_stale",
            )
        confirmed_by_action = choice == "confirm"
        routing_message = (
            agent_operation_reply(str(pending_operation_context.get("operationType") or "")) or "确认"
            if confirmed_by_action else "取消"
        )
    elif isinstance(candidate_ref, dict) and candidate_ref.get("candidateId"):
        pending_operation_context = next((item for item in active_pending_contexts if (
            str(candidate_ref.get("candidateId")) == str(item.get("candidateId") or "")
            and str(candidate_ref.get("runId") or "") == str(item.get("runId") or "")
            and str(candidate_ref.get("candidateDigest") or "") == str(item.get("candidateDigest") or "")
            and candidate_ref.get("candidateVersion") == item.get("candidateVersion")
        )), {})
        if not pending_operation_context:
            # Automatic commits have no pending card. Reconcile an explicit asset
            # reference against its session, version and saved data before replying.
            if (context_scope_value == "project" and not selected_action and not selected_preferred_task_type
                    and candidate_ref.get("candidateType") == "asset_range_candidate"
                    and routing_message in {"确认", "确定", "继续"}):
                return confirm_asset_range_locally(project_id, session_id, session_policy,
                                                   candidate_ref=candidate_ref)
            return _agent_session_policy_rejection(
                state, ValueError("候选已变化，请重新查看当前候选"),
                task_type="project_status", route_source="candidate_ref_stale",
            )
    if pending_decision is not None or (isinstance(candidate_ref, dict) and candidate_ref.get("candidateId")):
        candidate_id = str(pending_operation_context.get("candidateId") or "")
        if candidate_id:
            trusted_ref = {
                "runId": str(pending_operation_context.get("runId") or ""),
                "candidateId": candidate_id,
                "candidateDigest": str(pending_operation_context.get("candidateDigest") or ""),
                "candidateVersion": pending_operation_context.get("candidateVersion"),
            }
            expected_type = (
                "asset_range_candidate" if pending_operation_context.get("kind") == "asset_range"
                else "episode_boundary_candidate"
            )
            if isinstance(candidate_ref, dict) and (
                any(candidate_ref.get(key) != value for key, value in trusted_ref.items())
                or (candidate_ref.get("candidateType") and candidate_ref["candidateType"] != expected_type)
            ):
                return _agent_session_policy_rejection(
                    state, ValueError("确认的候选与待确认操作不一致，请重新查看候选卡片"),
                    task_type="project_status", route_source="pending_decision_candidate_mismatch",
                )
            candidate_ref = {
                **trusted_ref,
                **({"candidateType": expected_type} if expected_type == "asset_range_candidate" else {}),
            }
        elif candidate_ref:
            return _agent_session_policy_rejection(
                state, ValueError("当前待确认操作不包含候选，请重新查看确认卡片"),
                task_type="project_status", route_source="pending_decision_candidate_mismatch",
            )
    elif not selected_action and not selected_preferred_task_type:
        matching_pending = [item for item in active_pending_contexts
                            if _agent_message_is_pending_operation_protocol_reply(routing_message, item)]
        if len(matching_pending) > 1:
            return _agent_session_policy_rejection(
                state, ValueError("当前会话有多个待确认操作，请点击对应候选卡片"),
                task_type="project_status", route_source="pending_decision_ambiguous",
            )
        if matching_pending:
            pending_operation_context = matching_pending[0]
    if not selected_action and (selected_preferred_task_type or pending_operation_context.get("active")):
        selected_preferred_task_type, active_target = _agent_bind_production_continuation(
            state, routing_message, selected_preferred_task_type, active_target, pending_operation_context,
        )
    pending_operation_type = str(pending_operation_context.get("operationType") or "").strip()
    pending_requires_semantic_probe = _agent_pending_operation_requires_semantic_probe(
        routing_message,
        pending_operation_context,
    )
    if selected_preferred_task_type:
        pending_requires_semantic_probe = False
    if selected_action:
        try:
            validate_agent_session_action(selected_action, session_policy)
        except ValueError as exc:
            return _agent_session_policy_rejection(
                state,
                exc,
                task_type=selected_preferred_task_type or "overview_request",
                route_source="session_action_policy_rejected",
            )
    preferred_task_rejection = _agent_session_task_policy_rejection(
        state,
        selected_preferred_task_type,
        session_policy,
        route_source="preferred_task_session_policy_rejected",
    )
    if preferred_task_rejection and not pending_requires_semantic_probe:
        return preferred_task_rejection
    asset_range_candidate_selected = (
        isinstance(candidate_ref, dict)
        and candidate_ref.get("candidateType") == "asset_range_candidate"
    )
    if (
        context_scope_value == "project" and not selected_action
        and (pending_operation_type == "commit_asset_range"
             or asset_range_candidate_selected)
        and routing_message == "取消"
    ):
        return cancel_asset_range_locally(project_id, session_id, candidate_ref=candidate_ref)
    if (
        context_scope_value == "project" and not selected_action
        and (pending_operation_type == "commit_asset_range"
             or asset_range_candidate_selected)
        and routing_message in {"确认", "确定", "继续"}
    ):
        return confirm_asset_range_locally(project_id, session_id, session_policy,
                                           candidate_ref=candidate_ref)
    if (
        context_scope_value == "project" and not selected_action and routing_message == "取消"
        and (pending_operation_type == "commit_episode_boundary"
             or isinstance(candidate_ref, dict) and candidate_ref.get("candidateId")
             and not asset_range_candidate_selected)
    ):
        return cancel_episode_boundary_locally(project_id, session_id, candidate_ref=candidate_ref)
    if (
        context_scope_value == "project"
        and not selected_action
        and (
            (pending_operation_type == "commit_episode_boundary"
             and _agent_message_is_pending_operation_confirmation_reply(routing_message, pending_operation_context))
            or (isinstance(candidate_ref, dict) and candidate_ref.get("candidateId")
                and not asset_range_candidate_selected
                and routing_message in {"确认", "确定", "继续"})
        )
    ):
        return confirm_episode_boundary_locally(project_id, session_id, session_policy,
                                                candidate_ref=candidate_ref)
    if (
        context_scope_value == "project"
        and not selected_action
        and selected_preferred_task_type == "episode_boundary_propose"
    ):
        return run_native_episode_turn(
            project_id, progress_episode_id, session_id=session_id,
            message=routing_message,
            structured_task=selected_preferred_task_type == "episode_boundary_propose",
            on_pending_handoff=on_pending_handoff,
        )
    result = _resolve_selected_program_action(
        project_id=project_id,
        message=message,
        images=images,
        session_id=session_id,
        assistant_notice=assistant_notice,
        session_policy=session_policy,
        routing_message=routing_message,
        progress_episode_id=progress_episode_id,
        state=state,
        selected_action=selected_action,
        selected_preferred_task_type=selected_preferred_task_type,
        pending_requires_semantic_probe=pending_requires_semantic_probe,
    )
    if result is not None:
        return result
    result = _resolve_pending_turn_operation(
        project_id=project_id,
        episode_id=episode_id,
        session_id=session_id,
        session_policy=session_policy,
        routing_message=routing_message,
        context_scope_value=context_scope_value,
        progress_episode_id=progress_episode_id,
        state=state,
        selected_episode_id=selected_episode_id,
        selected_preferred_task_type=selected_preferred_task_type,
        pending_operation_context=pending_operation_context,
        pending_operation_type=pending_operation_type,
        candidate_ref=candidate_ref,
        confirmed_by_action=confirmed_by_action,
    )
    if result is not None:
        return result
    if selected_preferred_task_type in BUSINESS_TASK_HANDOFF_TYPES:
        if selected_preferred_task_type == "overview_request":
            validate_agent_session_action("analyze_overview", session_policy)
            return _resolve_selected_program_action(
                project_id=project_id, message=message, images=images,
                session_id=session_id, assistant_notice=assistant_notice,
                session_policy=session_policy, routing_message=routing_message,
                progress_episode_id=progress_episode_id, state=state,
                selected_action="analyze_overview",
                selected_preferred_task_type="", pending_requires_semantic_probe=False,
            )
        result = _resolve_asset_range_turn(
            project_id=project_id, episode_id=episode_id, message=message,
            session_id=session_id, session_policy=session_policy,
            routing_message=routing_message, context_scope_value=context_scope_value,
            progress_episode_id=progress_episode_id, state=state,
            selected_episode_id=selected_episode_id,
            selected_preferred_task_type=selected_preferred_task_type,
            pending_operation_context=pending_operation_context,
            pending_operation_type=pending_operation_type,
            pending_requires_semantic_probe=False,
        )
        if result is None:
            result = _resolve_production_turn(
                project_id=project_id, episode_id=episode_id, message=message,
                session_id=session_id, active_target=active_target,
                session_policy=session_policy, control_only=control_only,
                routing_message=routing_message, progress_episode_id=progress_episode_id,
                state=state, selected_preferred_task_type=selected_preferred_task_type,
                pending_requires_semantic_probe=False,
            )
        if result is not None:
            return result
        return {"success": False, "message": "该任务没有可执行的本地业务入口。",
                "steps": _agent_steps_from_state(state), "project": state.get("project"),
                "sessionStatus": "error"}
    native_task_type = selected_preferred_task_type
    native_structured_task = (
        native_task_type
        if (context_scope_value == "project" and native_task_type in {"asset_range_propose", "asset_extraction"})
        or context_scope_value == "episode" and native_task_type in {
            "work_chain_plan_save", "workflow_cinematic_script_generation",
            "director_plan_generation", "video_prompt_generation", "video_prompt_optimization", "video_prompt_standalone_generation",
        }
        else ""
    )
    if selected_preferred_task_type and not native_structured_task and selected_preferred_task_type not in _NATIVE_GENERAL_TASK_TYPES:
        return {"success": False,
                "message": f"当前快捷任务尚无可执行入口：{selected_preferred_task_type}。",
                "steps": _agent_steps_from_state(state), "project": state.get("project"),
                "sessionStatus": "error"}
    native_result = run_native_chat_turn(
        project_id, progress_episode_id, session_id=session_id,
        message=routing_message, state=state,
        active_target=active_target, session_policy=session_policy,
        structured_task_type=native_structured_task,
        task_options=task_options,
        images=images,
        on_pending_handoff=on_pending_handoff,
    )
    handoff = native_result.pop("businessTaskHandoff", None)
    if isinstance(handoff, dict) and handoff.get("taskType"):
        from utils.agent_execution_state import current_execution_id
        from .runtime_state import AgentTurnCancelled, _LOCK, _raise_if_agent_cancelled
        from .agent_sessions import _load_agent_sessions, _save_agent_sessions
        with _LOCK:
            _raise_if_agent_cancelled(session_id)
            sessions = _load_agent_sessions(project_id)
            owner = next((row for row in sessions if row.get("id") == session_id), None)
            if (not owner or owner.get("status") != "running"
                    or str((owner.get("execution") or {}).get("id") or "") != current_execution_id(session_id)):
                raise AgentTurnCancelled()
            owner["runningTaskType"] = "business_task"
            _save_agent_sessions(project_id, sessions)
        requirement = str(handoff.get("userRequirement") or "").strip()
        task_message = message or routing_message
        if requirement and requirement != str(message or "").strip():
            task_message = (f"{task_message}\n\n本轮会话提炼的执行约束（请结合原话核对）：{requirement}")
        return _resolve_agent_turn_result(
            project_id, episode_id, message=task_message, images=images,
            session_id=session_id, preferred_task_type=str(handoff["taskType"]),
            active_target=active_target, context_scope=context_scope,
            session_policy=session_policy,
            on_pending_handoff=on_pending_handoff,
        )
    success = bool(native_result.get("success", True))
    result = {
        "success": success,
        "message": str(native_result.get("reply") or "").strip() or ("智能体执行完成" if success else "智能体执行失败"),
        "contentBlocks": native_result.get("contentBlocks") or [],
        "steps": _agent_steps_from_state(state),
        "pendingQuestion": native_result.get("pendingQuestion"),
        "project": state.get("project"),
        "agentModelMeta": native_result.get("modelMeta") or {},
        "sessionStatus": str(native_result.get("sessionStatus") or ("idle" if success else "error")),
    }
    for key in ("pendingOperation", "projectChanged", "projectEffect", "toolResult", "completedTaskType", "commitReceipt", "discardSdkSession", "suppressSessionMessage"):
        if key in native_result:
            result[key] = native_result[key]
    return result
