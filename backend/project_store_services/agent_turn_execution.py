# -*- coding: utf-8 -*-
"""后台及内联智能体回合的执行生命周期。"""
from __future__ import annotations
from utils.agent_execution_state import EXECUTION_CONTEXT
import uuid

import copy as copy
import json as json
import threading as threading
import time as time
import traceback as traceback
from .agent_action_contract import (
    _agent_action_prompt,
    _agent_is_background_action,
    _agent_program_action_from_message,
    _agent_validate_action,
    _agent_validate_task_type,
)
from .agent_canvas_events import _emit_agent_project_effect
from .agent_contracts import (
    _agent_steps_from_state,
    agent_target_for_scope as _agent_active_target_for_scope,
    recent_creative_task_target,
)
from .agent_task_catalog import _agent_task_label
from .agent_execution_traces import (
    cancel_agent_execution_trace,
    finish_agent_execution_trace,
    start_agent_execution_trace,
)
from .agent_conversation_context import (
    _agent_turn_context_scope,
    _agent_turn_session_episode_id,
    _agent_turn_workflow_id,
    _apply_agent_session_context,
    _save_agent_turn_conversation_context,
)
from .agent_scope_hints import (
    _agent_message_requests_episode_detail,
)
from .agent_model_runtime import (
    _agent_sdk_runtime_config,
)
from .agent_pending_operations import (
    _agent_message_is_pending_operation_confirmation_reply,
    _agent_pending_operation_context,
    _agent_pending_operation_requires_semantic_probe,
)
from .agent_production_controller import (
    _execute_agent_action,
)
from .agent_progress_recommendations import (
    _agent_control_only_quick_prompt_message,
    _agent_control_preferred_production_task_result,
    _agent_next_running_step_id,
    _agent_progress_state,
    _agent_project_effect_for_action,
    _agent_project_status_result,
    _agent_tool_result_summary,
    _agent_work_chain_plan_already_generated_result,
)
from .agent_result_presentation import (
    _agent_session_task_policy_rejection,
    _agent_result_background_started,
    _agent_result_suppresses_session_message,
)
from .agent_session_events import (
    _emit_agent_session_update,
)
from .agent_session_lifecycle import (
    _resolve_agent_turn_result,
)
from .agent_session_policy import (
    build_agent_session_policy,
    validate_agent_session_action,
)
from .agent_session_results import (
    _interrupt_agent_session_state,
    _agent_runtime_config_failure_result,
    _finish_agent_session_local_result,
    _finish_agent_session_policy_rejection,
    _finish_agent_session_result,
)
from .agent_sessions import (
    _agent_live_activity_for_turn,
    _agent_message_attachment_rows,
    _agent_message_row,
    _agent_session_detail,
    _agent_session_summaries,
    _agent_session_title_for_message,
    _apply_agent_message_retention,
    _ensure_agent_session,
    _load_agent_sessions,
    _normalize_agent_message_rows,
    _save_agent_live_snapshot,
    _save_agent_sessions,
    _try_emit_agent_live_activity,
    append_agent_execution_error,
)
from .agent_turn_routing import (
    _agent_result_used_sdk_stream,
    _agent_turn_requires_sdk_runtime,
)
from .agent_task_status import (
    _agent_task_failure_fields,
    _agent_update_task_if_active,
)
from .runtime_state import (
    AgentTurnCancelled,
    _AGENT_CANCEL_FLAGS,
    _AGENT_THREADS,
    _LOCK,
)
from .source_text_store import _compact_text
from .store_core import (
    _emit_agent_event,
    _now,
)
from .task_control import (
    create_task,
)

from typing import Any


def _agent_turn_background_worker(
    project_id: str,
    episode_id: str | None,
    session_id: str,
    message: str,
    images: list[dict[str, Any]],
    task_id: str,
    preferred_action: str = "",
    assistant_notice: str = "",
    preferred_task_type: str = "",
    event_episode_id: str | None = None,
    context_scope: str = "episode",
    workflow_id: str = "",
    active_target: dict[str, Any] | None = None,
    display_message: str = "",
    quick_prompt_id: str = "",
    control_only: bool = False,
    control_intent_message: str = "",
    execution_cancel: Any | None = None,
    candidate_ref: dict[str, Any] | None = None,
    task_options: dict[str, Any] | None = None,
) -> None:
    event_episode_id = event_episode_id or episode_id
    activity_message = str(display_message or message or "").strip()
    cancel_flag = execution_cancel or _AGENT_CANCEL_FLAGS.get(task_id) or _AGENT_CANCEL_FLAGS.get(session_id)
    execution_token = EXECUTION_CONTEXT.set((session_id, task_id))
    handoff_published = threading.Event()

    def publish_pending_handoff(
        pending: dict[str, Any], reply: str, blocks: list[dict[str, Any]], suppress_message: bool,
    ) -> None:
        try:
            if handoff_published.is_set():
                return
            handoff_result = {
                "executionId": task_id,
                "success": True,
                "message": reply,
                "contentBlocks": copy.deepcopy(blocks),
                "pendingOperation": copy.deepcopy(pending),
                "steps": _agent_steps_from_state(_agent_progress_state(project_id, episode_id)),
                "sessionStatus": "idle",
                "discardSdkSession": True,
                "suppressSessionMessage": suppress_message,
            }
            final_result = _finish_agent_session_result(
                project_id, session_id, event_episode_id, handoff_result,
            )
            handoff_published.set()
            session = final_result.get("session")
            if isinstance(session, dict):
                try:
                    _emit_agent_session_update(
                        project_id, event_episode_id, session,
                        message="" if suppress_message else reply,
                        steps=final_result.get("steps") or [],
                        pending_question=None,
                    )
                except Exception:
                    print(traceback.format_exc(), flush=True)
            completed_at = int(time.time() * 1000)
            task = _agent_update_task_if_active(
                task_id, status="completed", progress=100, message=_compact_text(reply, 96),
                updatedAt=completed_at, completedAt=completed_at,
            )
            if task:
                _emit_agent_event("task_completed", task)
        except Exception:
            print(traceback.format_exc(), flush=True)

    try:
        task = _agent_update_task_if_active(
            task_id,
            status="running",
            progress=18,
            message="智能体正在处理本轮请求",
        )
        if not task:
            return
        _emit_agent_event("task_progress", task)
        thinking_state = _agent_progress_state(project_id, episode_id)
        _try_emit_agent_live_activity(
            project_id,
            event_episode_id,
            session_id,
            _agent_live_activity_for_turn(
                thinking_state,
                activity_message,
                phase="thinking",
                preferred_action=preferred_action or "",
            ),
        )
        if cancel_flag and cancel_flag.is_set():
            return
        result = _resolve_agent_turn_result(
            project_id,
            episode_id,
            message=message,
            images=images,
            session_id=session_id,
            preferred_action=preferred_action,
            preferred_task_type=preferred_task_type,
            assistant_notice=assistant_notice,
            active_target=active_target,
            context_scope=context_scope,
            control_intent_message=control_intent_message,
            control_only=control_only,
            candidate_ref=candidate_ref,
            task_options=task_options,
            on_pending_handoff=publish_pending_handoff,
        )
        if handoff_published.is_set():
            try:
                finish_agent_execution_trace(project_id, session_id, task_id, result)
            except Exception:
                print(traceback.format_exc(), flush=True)
            return
        pending_result = result.get("pendingOperation") if isinstance(result.get("pendingOperation"), dict) else {}
        submitted_candidate_pending = bool(
            (pending_result.get("type") == "commit_episode_boundary"
             and isinstance(pending_result.get("proposal"), dict)
             and pending_result["proposal"].get("proposalId"))
            or (pending_result.get("type") == "commit_plot_split"
                and pending_result.get("runId"))
            or (pending_result.get("type") == "commit_asset_range"
                and pending_result.get("runId") and pending_result.get("candidateId"))
        )
        durable_result = submitted_candidate_pending or bool(result.get("commitReceipt"))
        if cancel_flag and cancel_flag.is_set() and not durable_result:
            return
        action = str(result.get("agentAction") or "").strip()
        if action and not isinstance(result.get("projectEffect"), dict):
            result["projectEffect"] = _agent_project_effect_for_action(action, _agent_progress_state(project_id, episode_id))
        if action and not str(result.get("toolResult") or "").strip():
            result["toolResult"] = _agent_tool_result_summary(action, result.get("agentState"), result)
        if not _agent_result_used_sdk_stream(result):
            _try_emit_agent_live_activity(
                project_id,
                event_episode_id,
                session_id,
                _agent_live_activity_for_turn(
                    result.get("agentState") if isinstance(result.get("agentState"), dict) else _agent_progress_state(project_id, episode_id),
                    activity_message,
                    phase="finalizing",
                    preferred_action=action or preferred_action or "",
                ),
            )
        for child_task in result.get("tasks") or []:
            if isinstance(child_task, dict):
                _emit_agent_event("task_created", child_task)
                child_status = str(child_task.get("status") or "").strip()
                if child_status == "failed":
                    _emit_agent_event("task_failed", child_task)
                elif child_status in {"completed", "succeeded"}:
                    _emit_agent_event("task_completed", child_task)
                else:
                    _emit_agent_event("task_progress", child_task)
        project_effect = result.get("projectEffect") if isinstance(result.get("projectEffect"), dict) else None
        if cancel_flag and cancel_flag.is_set() and not durable_result:
            return
        background_started = _agent_result_background_started(result)
        suppress_session_message = _agent_result_suppresses_session_message(result)
        final_message = (
            str(result.get("message") or "后台任务已启动")
            if suppress_session_message
            else str(result.get("message") or "智能体执行完成")
        )
        final_task_finished_at = int(time.time() * 1000)
        final_task_fields = {
            "status": "completed" if result.get("success") else "failed",
            "progress": 100 if result.get("success") else 0,
            "message": _compact_text(final_message, 96),
            "updatedAt": final_task_finished_at,
            "completedAt": final_task_finished_at if result.get("success") else None,
            "failedAt": None if result.get("success") else final_task_finished_at,
            "projectEffect": project_effect,
            "focusTarget": (project_effect or {}).get("focusTarget"),
            "notice": (project_effect or {}).get("notice"),
        }
        if not result.get("success"):
            final_task_fields.update(
                _agent_task_failure_fields(
                    result.get("error") or result.get("message") or "智能体执行失败"
                )
            )
        final_task = _agent_update_task_if_active(task_id, **final_task_fields)
        if final_task:
            _emit_agent_event("task_completed" if result.get("success") else "task_failed", final_task)
        final_result = _finish_agent_session_result(project_id, session_id, event_episode_id, result)
        try:
            finish_agent_execution_trace(project_id, session_id, task_id, final_result)
        except Exception:
            print(traceback.format_exc(), flush=True)
        if cancel_flag and cancel_flag.is_set() and not durable_result:
            return
        session = final_result.get("session")
        if isinstance(session, dict):
            _emit_agent_session_update(
                project_id,
                event_episode_id,
                session,
                message="" if suppress_session_message else final_result.get("message") or "",
                steps=final_result.get("steps") or [],
                pending_question=final_result.get("pendingQuestion"),
                client_action=final_result.get("clientAction"),
                project_effect=final_result.get("projectEffect"),
            )
        _emit_agent_project_effect(
            project_id,
            event_episode_id,
            final_result.get("projectEffect"),
            session_id=session_id,
        )
        if final_result.get("projectChanged"):
            project_effect = final_result.get("projectEffect") if isinstance(final_result.get("projectEffect"), dict) else {}
            event_payload = {
                "action": "agent_split_completed",
                "projectId": project_id,
                "episodeId": event_episode_id,
            }
            for key in (
                "workflowVersion",
                "txId",
                "seq",
                "revision",
                "baseRevision",
                "opType",
                "records",
                "documentExtras",
                "productionStatus",
            ):
                if project_effect.get(key) is not None:
                    event_payload[key] = copy.deepcopy(project_effect.get(key))
            if isinstance(project_effect.get("changedResources"), list):
                event_payload["changedResources"] = copy.deepcopy(project_effect.get("changedResources") or [])
            if isinstance(project_effect.get("focusTarget"), dict):
                event_payload["focusTarget"] = copy.deepcopy(project_effect.get("focusTarget") or {})
            _emit_agent_event("project_changed", event_payload)
    except AgentTurnCancelled:
        return
    except Exception as exc:
        traceback_text = traceback.format_exc()
        append_agent_execution_error(
            project_id,
            stage="agent_background_worker",
            message="智能体后台执行失败",
            episode_id=episode_id,
            session_id=session_id,
            category="agent_execution_error",
            source="backend_worker",
            error=exc,
            details={
                "taskId": task_id,
                "preferredAction": preferred_action,
                "preferredTaskType": preferred_task_type,
                "message": message,
                "displayMessage": activity_message,
                "quickPromptId": quick_prompt_id,
                "controlOnly": control_only,
                "scope": context_scope,
                "eventEpisodeId": event_episode_id,
                "workflowId": workflow_id,
                "activeTarget": _agent_active_target_for_scope(context_scope, active_target),
            },
            include_traceback=True,
        )
        print(traceback_text, flush=True)
        raw_error_payload = {
            "stage": "agent_background_worker",
            "error": str(exc),
            "traceback": traceback_text,
            "taskId": task_id,
            "preferredAction": preferred_action,
            "preferredTaskType": preferred_task_type,
            "message": message,
            "displayMessage": activity_message,
            "quickPromptId": quick_prompt_id,
            "controlOnly": control_only,
            "scope": context_scope,
            "eventEpisodeId": event_episode_id,
            "workflowId": workflow_id,
            "activeTarget": _agent_active_target_for_scope(context_scope, active_target),
        }
        error_result = {
            "success": False,
            "message": f"智能体执行失败：{exc}",
            "contentBlocks": [
                {"type": "text", "text": f"智能体执行失败：{exc}"},
                {
                    "type": "tool_result",
                    "content": json.dumps(raw_error_payload, ensure_ascii=False, indent=2, default=str),
                    "is_error": True,
                    "contextExcluded": True,
                },
            ],
            "steps": _agent_steps_from_state(_agent_progress_state(project_id, episode_id), failed_step="storyboard"),
            "sessionStatus": "error",
        }
        failed_task = _agent_update_task_if_active(
            task_id,
            status="failed",
            progress=0,
            message=f"智能体执行失败：{str(exc) or exc.__class__.__name__}",
            **_agent_task_failure_fields(str(exc) or exc.__class__.__name__, traceback_text),
        )
        if failed_task:
            _emit_agent_event("task_failed", failed_task)
        try:
            final_result = _finish_agent_session_result(project_id, session_id, event_episode_id, error_result)
            try:
                finish_agent_execution_trace(project_id, session_id, task_id, final_result)
            except Exception:
                print(traceback.format_exc(), flush=True)
            session = final_result.get("session")
            if isinstance(session, dict):
                _emit_agent_session_update(
                    project_id,
                    event_episode_id,
                    session,
                    message=final_result.get("message") or "",
                    steps=final_result.get("steps") or [],
                    pending_question=None,
                )
        except Exception as emit_exc:
            append_agent_execution_error(
                project_id,
                stage="agent_finalize_failed",
                message="智能体失败后更新会话状态失败",
                episode_id=event_episode_id,
                session_id=session_id,
                category="agent_execution_error",
                source="backend_worker",
                error=emit_exc,
                details={
                    "taskId": task_id,
                    "originalError": str(exc),
                    "scope": context_scope,
                    "workflowId": workflow_id,
                },
                include_traceback=True,
            )
            print(f"[agent-turn-worker] failed to finalize session: {emit_exc}", flush=True)
            print(traceback.format_exc(), flush=True)
    finally:
        if cancel_flag and cancel_flag.is_set() and not handoff_published.is_set():
            try:
                cancel_agent_execution_trace(project_id, session_id, task_id)
            except Exception:
                print(traceback.format_exc(), flush=True)
        EXECUTION_CONTEXT.reset(execution_token)
        for key in (task_id, session_id):
            if _AGENT_CANCEL_FLAGS.get(key) is cancel_flag:
                _AGENT_CANCEL_FLAGS.pop(key, None)
            if _AGENT_THREADS.get(key) is threading.current_thread():
                _AGENT_THREADS.pop(key, None)


def _start_agent_background_turn(
    project_id: str,
    episode_id: str | None,
    *,
    message: str,
    images: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    preferred_action: str | None = None,
    preferred_task_type: str | None = None,
    display_message: str | None = None,
    quick_prompt_id: str | None = None,
    control_only: bool = False,
    assistant_notice: str = "",
    append_user_message: bool = True,
    scope: str | None = None,
    workflow_id: str | None = None,
    active_target: dict[str, Any] | None = None,
    candidate_ref: dict[str, Any] | None = None,
    task_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context_scope = _agent_turn_context_scope(scope, episode_id)
    active_target_context = _agent_active_target_for_scope(context_scope, active_target)
    progress_episode_id = None if context_scope == "project" else episode_id
    raw_message = str(message or "").strip()
    visible_message = str(display_message or raw_message or "").strip()
    selected_quick_prompt_id = str(quick_prompt_id or "").strip()
    selected_preferred_action = _agent_validate_action(preferred_action) if preferred_action else ""
    selected_preferred_task_type = (
        "" if selected_preferred_action else _agent_validate_task_type(preferred_task_type)
    )
    control_intent_message = _agent_control_only_quick_prompt_message(selected_quick_prompt_id)
    control_only_turn = bool(control_only) and bool(
        selected_preferred_action or selected_preferred_task_type or control_intent_message
    )
    message = "" if control_only_turn else raw_message
    routing_message = control_intent_message if control_only_turn else message
    images = _agent_message_attachment_rows(images or [], project_id)
    state = _agent_progress_state(
        project_id,
        progress_episode_id,
        detail_mode=context_scope == "episode" or _agent_message_requests_episode_detail(routing_message),
    )
    visible_turn_message = visible_message or message or "继续执行项目拆分流程"
    selected_episode_id = str(
        progress_episode_id if context_scope == "episode" and progress_episode_id
        else state.get("selectedEpisodeId") or "E01"
    )
    session_policy = build_agent_session_policy(
        project_id,
        scope=context_scope,
        episode_id=progress_episode_id,
        selected_episode_id=selected_episode_id,
    )
    session_episode_id = _agent_turn_session_episode_id(context_scope, selected_episode_id)
    workflow_id_value = _agent_turn_workflow_id(
        scope=context_scope,
        project_id=project_id,
        selected_episode_id=selected_episode_id,
        workflow_id=workflow_id,
    )
    effective_session_id = str(session_id or "").strip() or None
    if effective_session_id:
        owner = next((row for row in _load_agent_sessions(project_id)
                      if str(row.get("id") or "") == effective_session_id), None)
        if owner is None:
            raise FileNotFoundError("当前会话不存在，请重新选择或创建会话")
        owner_scope = str(owner.get("scope") or owner.get("contextScope") or "").strip()
        if (str(owner.get("episodeId") or "") != session_episode_id
                or (owner_scope and owner_scope != context_scope)):
            raise ValueError("当前会话不属于这个项目或分集，请切换到对应会话")
        if owner.get("canvasTask"):
            if not (owner.get("status") == "idle" and owner["canvasTask"].get("starting")):
                raise ValueError("画布任务为一次性执行，请在所属会话中发起新一轮任务")
            active_target_context = _agent_active_target_for_scope(context_scope, owner["canvasTask"]["target"])
        if (str(owner.get("status") or "") == "running"
                and str(owner.get("runningAction") or "") == "agent_turn"
                and owner.get("runningTaskType") in {"native_chat", "episode_boundary_propose", "asset_range_propose", "asset_extraction", "work_chain_plan_save", "workflow_cinematic_script_generation", "director_plan_generation", "video_prompt_generation", "video_prompt_optimization", "video_prompt_standalone_generation"}):
            if (not message or control_only_turn or selected_preferred_action
                    or selected_preferred_task_type or candidate_ref or images):
                raise ValueError("当前智能体正在执行；请在输入框补充文字要求，或先停止任务")
            interrupted = _interrupt_agent_session_state(
                project_id, effective_session_id, superseded_by_feedback=True,
                expected_execution_id=str((owner.get("execution") or {}).get("id") or ""),
                feedback_message=visible_turn_message,
            )
            if not interrupted.get("feedbackAccepted"):
                raise ValueError("当前执行状态已变化，请重试补充要求")
            if interrupted.get("partialFailure"):
                return {**interrupted, "success": False}
            append_user_message = False
    preflight_pending_operation_context = _agent_pending_operation_context(project_id, effective_session_id)
    pending_decision = (
        task_options.get("pendingDecision")
        if isinstance(task_options, dict) and isinstance(task_options.get("pendingDecision"), dict)
        else None
    )
    pending_requires_semantic_probe = _agent_pending_operation_requires_semantic_probe(
        routing_message,
        preflight_pending_operation_context,
    )
    if selected_preferred_task_type or pending_decision is not None:
        pending_requires_semantic_probe = False
    episode_title = "项目会话" if context_scope == "project" else str(state.get("selectedEpisodeTitle") or selected_episode_id)
    direct_program_action = (
        "" if selected_preferred_action or selected_preferred_task_type or pending_decision is not None
        else str(_agent_program_action_from_message(routing_message, state) or "")
    )
    if selected_preferred_task_type == "project_status" or (
        direct_program_action and not pending_requires_semantic_probe
    ):
        if direct_program_action:
            try:
                validate_agent_session_action(direct_program_action, session_policy)
            except ValueError as exc:
                return _finish_agent_session_policy_rejection(
                    project_id,
                    effective_session_id,
                    session_episode_id,
                    state=state,
                    reason=exc,
                    message=visible_turn_message,
                    images=images,
                    append_user_message=append_user_message,
                    scope=context_scope,
                    workflow_id=workflow_id_value,
                    active_target=active_target_context,
                    task_type="overview_request"
                    if direct_program_action == "analyze_overview"
                    else "project_status",
                    route_source="background_program_action_session_policy_rejected",
                    control_only=control_only_turn,
                    quick_prompt_id=selected_quick_prompt_id,
                    execution_message=message,
                )
        result = (
            _execute_agent_action(
                project_id,
                progress_episode_id,
                direct_program_action,
                message=routing_message or visible_turn_message,
                images=images,
                session_id=effective_session_id,
                state=state,
            )
            if direct_program_action
            else _agent_project_status_result(state, routing_message or visible_turn_message)
        )
        return _finish_agent_session_local_result(
            project_id,
            effective_session_id,
            session_episode_id,
            state=state,
            result=result,
            message=visible_turn_message,
            images=images,
            append_user_message=append_user_message,
            scope=context_scope,
            workflow_id=workflow_id_value,
            active_target=active_target_context,
            control_only=control_only_turn,
            quick_prompt_id=selected_quick_prompt_id,
            execution_message=message,
        )
    if selected_preferred_action:
        try:
            validate_agent_session_action(selected_preferred_action, session_policy)
        except ValueError as exc:
            return _finish_agent_session_policy_rejection(
                project_id,
                effective_session_id,
                session_episode_id,
                state=state,
                reason=exc,
                message=visible_turn_message,
                images=images,
                append_user_message=append_user_message,
                scope=context_scope,
                workflow_id=workflow_id_value,
                active_target=active_target_context,
                task_type="overview_request",
                route_source="background_action_session_policy_rejected",
                control_only=control_only_turn,
                quick_prompt_id=selected_quick_prompt_id,
                execution_message=message,
            )
    if (
        control_only_turn
        and selected_preferred_task_type == "work_chain_plan_save"
        and not pending_requires_semantic_probe
        and not preflight_pending_operation_context.get("active")
    ):
        plan_ready_result = _agent_work_chain_plan_already_generated_result(
            state,
            selected_preferred_task_type,
        )
        if plan_ready_result:
            return _finish_agent_session_local_result(
                project_id,
                effective_session_id,
                session_episode_id,
                state=state,
                result=plan_ready_result,
                message=visible_turn_message,
                images=images,
                append_user_message=append_user_message,
                scope=context_scope,
                workflow_id=workflow_id_value,
                active_target=active_target_context,
                control_only=control_only_turn,
                quick_prompt_id=selected_quick_prompt_id,
                execution_message=message,
            )
    background_task_rejection = _agent_session_task_policy_rejection(
        state,
        selected_preferred_task_type,
        session_policy,
        route_source="background_preferred_task_session_policy_rejected",
    )
    if background_task_rejection and not pending_requires_semantic_probe:
        return _finish_agent_session_policy_rejection(
            project_id,
            effective_session_id,
            session_episode_id,
            state=state,
            reason=background_task_rejection.get("message") or "当前会话没有权限执行该操作。",
            message=visible_turn_message,
            images=images,
            append_user_message=append_user_message,
            scope=context_scope,
            workflow_id=workflow_id_value,
            active_target=active_target_context,
            task_type=selected_preferred_task_type or "project_status",
            route_source="background_preferred_task_session_policy_rejected",
            control_only=control_only_turn,
            quick_prompt_id=selected_quick_prompt_id,
            execution_message=message,
        )
    if selected_preferred_task_type and (control_only_turn or (active_target_context or {}).get("source") == "agent_recommendation"):
        preferred_task_status_result = _agent_control_preferred_production_task_result(
            state,
            selected_preferred_task_type,
            active_target_context,
        )
        if preferred_task_status_result:
            return _finish_agent_session_local_result(
                project_id,
                effective_session_id,
                session_episode_id,
                state=state,
                result=preferred_task_status_result,
                message=visible_turn_message,
                images=images,
                append_user_message=append_user_message,
                scope=context_scope,
                workflow_id=workflow_id_value,
                active_target=active_target_context,
                control_only=control_only_turn,
                quick_prompt_id=selected_quick_prompt_id,
                execution_message=message,
            )
    if pending_decision is None and _agent_turn_requires_sdk_runtime(
        routing_message,
        state,
        selected_preferred_action,
        selected_preferred_task_type,
        preflight_pending_operation_context,
    ):
        runtime_config, model_meta = _agent_sdk_runtime_config(project_id)
        if runtime_config is None:
            return _agent_runtime_config_failure_result(
                project_id,
                progress_episode_id,
                state=state,
                message=visible_turn_message,
                images=images,
                session_id=effective_session_id,
                selected_episode_id=selected_episode_id,
                episode_title=episode_title,
                model_meta=model_meta,
                append_user_message=append_user_message,
                scope=context_scope,
                session_episode_id=session_episode_id,
                workflow_id=workflow_id_value,
                active_target=active_target_context,
                control_only=control_only_turn,
                quick_prompt_id=selected_quick_prompt_id,
                execution_message=message,
            )
    running_step_id = _agent_next_running_step_id(state)
    running_steps = _agent_steps_from_state(state, running_step=running_step_id)
    task_message = "智能体已接收任务，正在启动"
    live_activity = _agent_live_activity_for_turn(
        state,
        visible_turn_message,
        phase="start",
        preferred_action=selected_preferred_action,
        goal=_agent_task_label(selected_preferred_task_type) if control_only_turn else "",
    )
    with _LOCK:
        session, sessions = _ensure_agent_session(
            project_id,
            effective_session_id,
            session_episode_id,
            _agent_session_title_for_message(episode_title, visible_turn_message),
        )
        _apply_agent_session_context(
            session,
            scope=context_scope,
            episode_id=session_episode_id,
            workflow_id=workflow_id_value,
        )
        if active_target_context:
            session["activeTarget"] = active_target_context
            recent_target = recent_creative_task_target(active_target_context, session_episode_id)
            if recent_target:
                session["recentTaskTarget"] = recent_target
        else:
            session.pop("activeTarget", None)
        waiting_for_user = bool(session.get("pendingQuestion")) and not str(session.get("taskId") or "").strip()
        if str(session.get("status") or "") == "running" and not waiting_for_user:
            raise ValueError("当前会话正在执行中，可以先停止或切换到新会话继续对话")

        messages = _normalize_agent_message_rows(session.get("messages"), project_id)
        if append_user_message:
            messages.append(
                _agent_message_row(
                    "user",
                    visible_turn_message,
                    attachments=images,
                    project_id=project_id,
                    control_only=control_only_turn,
                    quick_prompt_id=selected_quick_prompt_id,
                    execution_message=message,
                )
            )
        task = create_task(
            "agent_turn",
            project_id=project_id,
            episode_id=session_episode_id,
            node_id=active_target_context.get("nodeId") if session.get("canvasTask") and active_target_context else None,
            message=task_message,
            status="running",
            progress=5,
            task_fields={
                "sessionId": session["id"],
                "agentAction": "agent_turn",
                **({key: active_target_context[key] for key in ("workChainId", "routeId")
                    if active_target_context and key in active_target_context}
                   if session.get("canvasTask") else {}),
            },
        )

        _apply_agent_message_retention(session, messages)
        session["steps"] = running_steps
        session["status"] = "running"
        session["taskId"] = task["id"]
        session["execution"] = {"id": task["id"], "parentTaskId": task["id"], "blockingTaskIds": [], "dispatchClosed": False}
        session.pop("supersededExecutionId", None)
        session["runningAction"] = "agent_turn"
        session["runningTaskType"] = (
            "episode_boundary_propose" if selected_preferred_task_type == "episode_boundary_propose"
            else "asset_range_propose" if selected_preferred_task_type == "asset_range_propose"
            else "asset_extraction" if selected_preferred_task_type == "asset_extraction"
            else "work_chain_plan_save" if selected_preferred_task_type == "work_chain_plan_save"
            else "workflow_cinematic_script_generation" if selected_preferred_task_type == "workflow_cinematic_script_generation"
            else "director_plan_generation" if selected_preferred_task_type == "director_plan_generation"
            else "video_prompt_generation" if selected_preferred_task_type == "video_prompt_generation"
            else "video_prompt_optimization" if selected_preferred_task_type == "video_prompt_optimization"
            else "video_prompt_standalone_generation" if selected_preferred_task_type == "video_prompt_standalone_generation"
            else "local_confirmation" if pending_decision is not None
            or (isinstance(candidate_ref, dict) and candidate_ref.get("candidateId")
                and not selected_preferred_action and routing_message in {"确认", "确定", "继续", "取消"})
            or preflight_pending_operation_context.get("operationType") in {
                "commit_episode_boundary", "commit_plot_split", "commit_asset_range"}
            and _agent_message_is_pending_operation_confirmation_reply(routing_message, preflight_pending_operation_context)
            else "native_chat"
        )
        session["updatedAt"] = _now()
        session.pop("pendingQuestion", None)
        for index, row in enumerate(sessions):
            if str(row.get("id") or "") == str(session.get("id") or ""):
                sessions[index] = session
                break
        _save_agent_sessions(project_id, sessions)

    try:
        start_agent_execution_trace(
            project_id, str(session["id"]), str(task["id"]), scope=context_scope,
            episode_id=session_episode_id,
            task_type=str(session.get("runningTaskType") or selected_preferred_task_type or "agent_turn"),
        )
    except Exception:
        print(traceback.format_exc(), flush=True)

    cancel_flag = threading.Event()
    session_id_value = str(session["id"])
    _AGENT_CANCEL_FLAGS[session_id_value] = cancel_flag
    _AGENT_CANCEL_FLAGS[task["id"]] = cancel_flag
    if not session.get("canvasTask"):
        _save_agent_turn_conversation_context(
            project_id,
            session_episode_id,
            scope=context_scope,
            session_id=session_id_value,
            workflow_id=workflow_id_value,
            active_target=active_target_context,
        )
    result = {
        "success": True,
        "status": "accepted",
        "backgroundStarted": True,
        "message": task_message,
        "steps": running_steps,
        "pendingQuestion": None,
        "task": task,
        "tasks": [task],
        "session": _agent_session_detail(project_id, session),
        "snapshot": _save_agent_live_snapshot(project_id, session, live_activity),
        "sessions": _agent_session_summaries(project_id, session_episode_id),
        "sessionId": session_id_value,
        "episodeId": session_episode_id,
        "scope": context_scope,
        "workflowId": workflow_id_value,
        "sessionStatus": "running",
    }
    _emit_agent_event("task_created", task)
    _emit_agent_event("task_progress", task)
    _emit_agent_session_update(
        project_id,
        session_episode_id,
        session,
        message=task_message,
        steps=running_steps,
        pending_question=None,
        live_activity=live_activity,
    )

    thread = threading.Thread(
        target=_agent_turn_background_worker,
        args=(
            project_id,
            selected_episode_id,
            session_id_value,
            message,
            copy.deepcopy(images or []),
            task["id"],
            selected_preferred_action,
            assistant_notice,
            selected_preferred_task_type,
            session_episode_id,
            context_scope,
            workflow_id_value,
            active_target_context,
            visible_turn_message,
            selected_quick_prompt_id,
            control_only_turn,
            control_intent_message if control_only_turn else "",
            cancel_flag,
            candidate_ref,
            copy.deepcopy(task_options) if isinstance(task_options, dict) else None,
        ),
        name=f"ai-video-agent-turn-{session_id_value[-8:]}",
        daemon=True,
    )
    _AGENT_THREADS[session_id_value] = thread
    _AGENT_THREADS[task["id"]] = thread
    try:
        thread.start()
    except Exception:
        for key in (task["id"], session_id_value):
            if _AGENT_THREADS.get(key) is thread:
                _AGENT_THREADS.pop(key, None)
            if _AGENT_CANCEL_FLAGS.get(key) is cancel_flag:
                _AGENT_CANCEL_FLAGS.pop(key, None)
        _agent_update_task_if_active(task["id"], status="failed", message="智能体后台线程启动失败")
        return _finish_agent_session_result(project_id, session_id_value, session_episode_id, {
            "success": False, "sessionStatus": "error", "message": "智能体后台线程启动失败",
            "executionId": task["id"],
        })
    return result


def _run_agent_inline_turn(
    project_id: str,
    episode_id: str | None,
    *,
    message: str,
    images: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    preferred_action: str,
    assistant_notice: str = "",
    append_user_message: bool = True,
) -> dict[str, Any]:
    selected_action = _agent_validate_action(preferred_action)
    if _agent_is_background_action(selected_action):
        return _start_agent_background_turn(
            project_id,
            episode_id,
            message=message,
            images=images,
            session_id=session_id,
            preferred_action=selected_action,
            assistant_notice=assistant_notice,
            append_user_message=append_user_message,
        )

    images = _agent_message_attachment_rows(images or [], project_id)
    state = _agent_progress_state(
        project_id,
        episode_id,
        detail_mode=bool(str(episode_id or "").strip()),
    )
    selected_episode_id = str(state.get("selectedEpisodeId") or episode_id or "E01")
    episode_title = str(state.get("selectedEpisodeTitle") or selected_episode_id)
    user_text = str(message or "").strip() or _agent_action_prompt(selected_action, state)
    with _LOCK:
        session, sessions = _ensure_agent_session(
            project_id,
            session_id,
            selected_episode_id,
            _agent_session_title_for_message(episode_title, user_text),
        )
        waiting_for_user = bool(session.get("pendingQuestion")) and not str(session.get("taskId") or "").strip()
        if str(session.get("status") or "") == "running" and not waiting_for_user:
            raise ValueError("当前会话正在执行中，可以先停止或切换到新会话继续对话")
        messages = _normalize_agent_message_rows(session.get("messages"), project_id)
        if append_user_message:
            messages.append(
                _agent_message_row(
                    "user",
                    user_text,
                    attachments=images,
                    project_id=project_id,
                )
            )
        _apply_agent_message_retention(session, messages)
        session["steps"] = _agent_steps_from_state(state)
        session["status"] = "idle"
        session["execution"] = {"id": f"inline-{uuid.uuid4().hex}", "blockingTaskIds": [], "dispatchClosed": False}
        session["updatedAt"] = _now()
        session.pop("pendingQuestion", None)
        session.pop("taskId", None)
        session.pop("runningAction", None)
        for index, row in enumerate(sessions):
            if str(row.get("id") or "") == str(session.get("id") or ""):
                sessions[index] = session
                break
        _save_agent_sessions(project_id, sessions)
        session_id_value = str(session["id"])

    execution_token = EXECUTION_CONTEXT.set((session_id_value, session["execution"]["id"]))
    try:
        result = _execute_agent_action(
            project_id,
            selected_episode_id,
            selected_action,
            message=user_text,
            images=images,
            session_id=session_id_value,
            state=state,
        )
        result["sessionStatus"] = str(result.get("sessionStatus") or "idle")
        if assistant_notice:
            action_message = str(result.get("message") or "").strip()
            result["message"] = (
                f"{assistant_notice}\n\n{action_message}"
                if action_message
                else assistant_notice
            )
        return _finish_agent_session_result(project_id, session_id_value, selected_episode_id, result)

    finally:
        EXECUTION_CONTEXT.reset(execution_token)
