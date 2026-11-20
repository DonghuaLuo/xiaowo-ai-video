# -*- coding: utf-8 -*-
"""待确认操作的回合路由与提交结果处理。"""
from __future__ import annotations

import traceback as traceback
from .agent_session_policy import (
    AgentSessionPolicyError,
    validate_agent_session_episode_target,
    validate_agent_session_pending_operation,
)
from .runtime_state import (
    AgentTurnCancelled,
    _AGENT_CANCEL_FLAGS,
)
from .agent_operation_catalog import (
    AGENT_DESTRUCTIVE_OPERATION_TYPES as _AGENT_DESTRUCTIVE_OPERATION_TYPES,
    CURRENT_CANVAS_CLEAR_OPERATION_TYPES as _CURRENT_CANVAS_CLEAR_OPERATION_TYPES,
    EPISODE_SOURCE_DELETE_OPERATION_TYPES as _EPISODE_SOURCE_DELETE_OPERATION_TYPES,
    LATEST_ASSET_RANGE_DELETE_OPERATION_TYPES as _LATEST_ASSET_RANGE_DELETE_OPERATION_TYPES,
    PROJECT_ASSET_CLEANUP_OPERATION_TYPES as _PROJECT_ASSET_CLEANUP_OPERATION_TYPES,
    agent_operation_label,
    agent_operation_task_type,
)
from .agent_pending_operations import (
    _agent_clear_pending_operation_state,
    _agent_message_cancels_destructive_operation,
    _agent_message_confirms,
    _agent_message_confirms_destructive_operation,
    _agent_message_is_pending_operation_confirmation_reply,
    _agent_pending_operation_kind,
    _agent_pending_operation_local_result,
    _agent_task_type_for_pending_operation,
    _combine_agent_user_instructions,
)
from .agent_result_presentation import (
    _agent_episode_session_project_delete_rejection,
    _agent_session_policy_rejection,
    _agent_session_task_policy_rejection,
    _agent_turn_result_from_worker_decision,
    _agent_controller_decision_from_result,
)
from .agent_plot_contract import (
    _agent_plot_split_revision_requirements,
)
from .agent_progress_recommendations import (
    _agent_progress_message,
    _agent_progress_state,
    _agent_project_status_result,
)
from .agent_contracts import (
    _agent_steps_from_state,
)
from .agent_plot_splitting import (
    _commit_plot_split_to_workflow_controller,
)
from .agent_plot_split_tools import (
    _plot_split_inputs,
    plot_split_candidate_digest,
)
from .agent_asset_cleanup import (
    _run_current_canvas_clear_controller,
    _run_episode_source_delete_controller,
    _run_latest_asset_range_delete_controller,
    _run_project_asset_cleanup_controller,
)
from .agent_direct_deletion import execute_agent_direct_delete
from .agent_sessions import (
    append_agent_execution_error,
)
from typing import Any


def _resolve_plot_split_confirmation(
    project_id: str,
    episode_id: str | None,
    session_id: str | None,
    session_policy: dict[str, Any] | None,
    routing_message: str,
    progress_episode_id: str | None,
    state: dict[str, Any],
    selected_episode_id: str,
    pending_operation_context: dict[str, Any],
    pending_operation_type: str,
    candidate_ref: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        commit_payload = (
            pending_operation_context.get("commitPayload")
            if isinstance(pending_operation_context.get("commitPayload"), dict)
            else {}
        )
        plot_split_proposal = (
            commit_payload.get("plotSplitProposal")
            if isinstance(commit_payload.get("plotSplitProposal"), dict)
            else pending_operation_context.get("proposal")
            if isinstance(pending_operation_context.get("proposal"), dict)
            else {}
        )
        target_episode_id = (
            str(commit_payload.get("episodeId") or selected_episode_id).strip()
            or selected_episode_id
        )
        task_rejection = _agent_session_task_policy_rejection(
            state,
            "work_chain_plan_save",
            session_policy,
            route_source="plot_split_commit_session_policy_rejected",
        )
        if task_rejection:
            return task_rejection
        try:
            validate_agent_session_pending_operation(pending_operation_type, session_policy)
        except ValueError as exc:
            return _agent_session_policy_rejection(
                state,
                exc,
                task_type="work_chain_plan_save",
                route_source="plot_split_commit_session_policy_rejected",
            )
        validate_agent_session_episode_target(target_episode_id, session_policy)
        if str(pending_operation_context.get("sessionId") or "") != str(session_id or ""):
            raise ValueError("剧情拆分候选不属于当前会话，请在原会话确认")
        candidate_id = str(pending_operation_context.get("runId") or "")
        candidate_digest = str(pending_operation_context.get("candidateDigest") or "")
        if not candidate_id or not candidate_digest:
            raise ValueError("剧情拆分候选缺少确认身份，请重新提交候选")
        if isinstance(candidate_ref, dict) and candidate_ref:
            supplied_id = str(candidate_ref.get("runId") or candidate_ref.get("candidateId") or "")
            supplied_digest = str(candidate_ref.get("candidateDigest") or "")
            supplied_version = candidate_ref.get("candidateVersion")
            if (supplied_id and supplied_id != candidate_id) or (supplied_digest and supplied_digest != candidate_digest):
                raise ValueError("确认的是较早的剧情拆分候选，请查看当前候选后重试")
            if supplied_version is not None and supplied_version != pending_operation_context.get("candidateVersion"):
                raise ValueError("剧情拆分候选版本已变化，请查看当前候选后重试")
        if candidate_digest != plot_split_candidate_digest(plot_split_proposal):
            raise ValueError("剧情拆分候选内容已变化，请重新提交候选")
        source_input_ref = (
            commit_payload.get("sourceInputRef")
            if isinstance(commit_payload.get("sourceInputRef"), dict)
            else {}
        )
        expected_source_digest = str(source_input_ref.get("sourceDigest") or "")
        try:
            current_source = _plot_split_inputs(project_id, target_episode_id, include_assets=False)
        except (ValueError, FileNotFoundError) as exc:
            raise ValueError("剧情拆分所用原文状态无法核验，请重新读取并提交候选") from exc
        if not expected_source_digest:
            raise ValueError("剧情拆分所用原文状态无法核验，请重新读取并提交候选")
        if current_source.get("sourceDigest") != expected_source_digest:
            raise ValueError("当前集原文已变化，请依据最新原文重新拆分剧情")
        submit_user_message = _combine_agent_user_instructions(
            commit_payload.get("baseUserInstruction") or commit_payload.get("userInstruction"),
            "\n".join(
                _agent_plot_split_revision_requirements(
                    commit_payload.get("effectiveRevisionRequirements")
                )
            ),
        )
        controller_result = _commit_plot_split_to_workflow_controller(
            project_id,
            target_episode_id,
            parent_session_id=session_id,
            user_message=submit_user_message,
            plot_split_proposal=plot_split_proposal,
            pending_operation=pending_operation_context,
        )
        if controller_result.get("status") == "blocked":
            blocked = _agent_session_policy_rejection(
                state, ValueError(controller_result["message"]),
                task_type="work_chain_plan_save", route_source="plot_split_confirmation_blocked",
            )
            blocked["pendingOperation"] = controller_result.get("pendingOperation")
            return blocked
        decision = _agent_controller_decision_from_result(
            controller_result,
            {
                "source": "local-controller",
                "taskHypothesis": {
                    "taskType": "work_chain_plan_save",
                    "routeSource": "pending_operation_confirmation",
                },
            },
        )
    except AgentTurnCancelled:
        raise
    except AgentSessionPolicyError as exc:
        return _agent_session_policy_rejection(
            state,
            exc,
            task_type="work_chain_plan_save",
            route_source="plot_split_commit_session_policy_rejected",
        )
    except (ValueError, FileNotFoundError) as exc:
        blocked = _agent_session_policy_rejection(
            state, ValueError(f"未写入工作链：{exc}"),
            task_type="work_chain_plan_save", route_source="plot_split_confirmation_blocked",
        )
        blocked["pendingOperation"] = pending_operation_context
        return blocked
    except Exception as exc:  # noqa: BLE001
        append_agent_execution_error(
            project_id,
            stage="plot_split_commit_controller",
            message="原文拆分确认提交 controller 失败",
            episode_id=episode_id,
            session_id=session_id,
            category="agent_controller_error",
            source="agent_controller",
            error=exc,
            details={"pendingOperation": pending_operation_context, "message": routing_message},
            include_traceback=True,
        )
        print(traceback.format_exc(), flush=True)
        decision = _agent_controller_decision_from_result(
            {
                "success": False,
                "message": f"原文拆分确认提交失败：{exc}",
                "pendingOperation": pending_operation_context,
            },
            {"source": "local-controller", "error": str(exc)},
        )
    return _agent_turn_result_from_worker_decision(
        project_id,
        progress_episode_id,
        decision,
        fallback_state=state,
        fallback_message=routing_message,
    )




def _resolve_destructive_confirmation(
    project_id: str,
    episode_id: str | None,
    session_id: str | None,
    routing_message: str,
    context_scope_value: str,
    progress_episode_id: str | None,
    state: dict[str, Any],
    pending_operation_context: dict[str, Any],
    pending_operation_type: str,
    confirmed_by_action: bool = False,
) -> dict[str, Any] | None:
    pending_operation_kind = _agent_pending_operation_kind(pending_operation_context)
    if (
        context_scope_value == "episode"
        and pending_operation_type not in (_CURRENT_CANVAS_CLEAR_OPERATION_TYPES | _EPISODE_SOURCE_DELETE_OPERATION_TYPES)
        and pending_operation_kind not in {"direct_workflow_delete", "direct_workflow_unlink"}
    ):
        task_type = (
            "project_cleanup"
            if pending_operation_type in (_PROJECT_ASSET_CLEANUP_OPERATION_TYPES | _EPISODE_SOURCE_DELETE_OPERATION_TYPES)
            else "asset_range_delete_latest"
        )
        return _agent_episode_session_project_delete_rejection(state, task_type=task_type)
    if _agent_message_cancels_destructive_operation(routing_message):
        if pending_operation_type in _PROJECT_ASSET_CLEANUP_OPERATION_TYPES:
            reply = "已取消清空全部资产操作。本轮没有删除任何资产，也没有启动重新拆分。"
            task_type = "project_cleanup"
        elif pending_operation_type in _LATEST_ASSET_RANGE_DELETE_OPERATION_TYPES:
            reply = "已取消删除最新一组资产拆分操作。本轮没有删除任何资产，也没有回滚资产游标。"
            task_type = "asset_range_delete_latest"
        elif pending_operation_type in _EPISODE_SOURCE_DELETE_OPERATION_TYPES:
            reply = "已取消删除最新分集操作。本轮没有删除任何分集原文或工作链画布数据。"
            task_type = "project_cleanup"
        elif pending_operation_kind in {"direct_asset_delete", "direct_workflow_delete", "direct_workflow_unlink"}:
            reply = "已取消本次删除或移除请求，项目数据没有改动。"
            task_type = "project_cleanup"
        else:
            reply = "已取消清空当前集画布操作。本轮没有删除任何画布或工作链派生结果。"
            task_type = "project_cleanup"
        _agent_clear_pending_operation_state(
            project_id,
            session_id,
            pending_operation_context,
            reason="agent_destructive_pending_operation_cancelled",
            user_instruction=routing_message,
        )
        return {
            "success": True,
            "message": reply,
            "contentBlocks": [{"type": "text", "text": reply}],
            "steps": _agent_steps_from_state(state),
            "pendingQuestion": None,
            "project": state["project"],
            "agentModelMeta": {
                "source": "local-controller",
                "taskHypothesis": {
                    "taskType": task_type,
                    "routeSource": "destructive_operation_cancelled",
                },
            },
            "sessionStatus": "idle",
            "pendingOperation": None,
        }
    if _agent_message_confirms_destructive_operation(routing_message, pending_operation_type) and confirmed_by_action:
        try:
            if pending_operation_type in _PROJECT_ASSET_CLEANUP_OPERATION_TYPES:
                controller_result = _run_project_asset_cleanup_controller(
                    project_id,
                    pending_operation=pending_operation_context,
                    user_message=routing_message,
                    cancel_event=_AGENT_CANCEL_FLAGS.get(str(session_id or "")),
                )
                task_type = "project_cleanup"
                stage = "project_asset_cleanup_controller"
            elif pending_operation_type in _LATEST_ASSET_RANGE_DELETE_OPERATION_TYPES:
                controller_result = _run_latest_asset_range_delete_controller(
                    project_id,
                    pending_operation=pending_operation_context,
                    user_message=routing_message,
                    cancel_event=_AGENT_CANCEL_FLAGS.get(str(session_id or "")),
                )
                task_type = "asset_range_delete_latest"
                stage = "latest_asset_range_delete_controller"
            elif pending_operation_type in _CURRENT_CANVAS_CLEAR_OPERATION_TYPES:
                controller_result = _run_current_canvas_clear_controller(
                    project_id,
                    pending_operation=pending_operation_context,
                    user_message=routing_message,
                    cancel_event=_AGENT_CANCEL_FLAGS.get(str(session_id or "")),
                )
                task_type = "project_cleanup"
                stage = "current_canvas_clear_controller"
            elif pending_operation_type in _EPISODE_SOURCE_DELETE_OPERATION_TYPES:
                controller_result = _run_episode_source_delete_controller(
                    project_id,
                    pending_operation=pending_operation_context,
                    user_message=routing_message,
                    cancel_event=_AGENT_CANCEL_FLAGS.get(str(session_id or "")),
                )
                task_type = "project_cleanup"
                stage = "episode_source_delete_controller"
            elif pending_operation_kind in {"direct_asset_delete", "direct_workflow_delete", "direct_workflow_unlink"}:
                controller_result = execute_agent_direct_delete(project_id, pending_operation_context)
                task_type = "project_cleanup"
                stage = "direct_delete_controller"
            else:
                raise ValueError("未知的破坏性待确认操作")
            decision = _agent_controller_decision_from_result(
                controller_result,
                {
                    "source": "local-controller",
                    "taskHypothesis": {
                        "taskType": task_type,
                        "routeSource": "destructive_confirmation",
                    },
                },
            )
        except AgentTurnCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            append_agent_execution_error(
                project_id,
                stage=stage if "stage" in locals() else "destructive_operation_controller",
                message="删除确认 controller 失败",
                episode_id=episode_id,
                session_id=session_id,
                category="agent_controller_error",
                source="agent_controller",
                error=exc,
                details={"pendingOperation": pending_operation_context, "message": routing_message},
                include_traceback=True,
            )
            print(traceback.format_exc(), flush=True)
            decision = _agent_controller_decision_from_result(
                {
                    "success": False,
                    "message": f"删除操作失败：{exc}",
                    "pendingOperation": pending_operation_context,
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
        if decision.get("projectChanged"):
            result["projectChanged"] = True
        if isinstance(decision.get("projectEffect"), dict):
            result["projectEffect"] = decision.get("projectEffect")
        if decision.get("toolResult"):
            result["toolResult"] = decision.get("toolResult")
        return result
    if _agent_message_confirms(routing_message) or _agent_message_confirms_destructive_operation(routing_message, pending_operation_type):
        label = agent_operation_label(pending_operation_kind)
        reply = f"这是{label}，请在当前待确认卡片上点击确认。当前操作尚未执行。"
        return {
            "success": True,
            "message": reply,
            "contentBlocks": [{"type": "text", "text": reply}],
            "steps": _agent_steps_from_state(state),
            "pendingQuestion": None,
            "project": state["project"],
            "agentModelMeta": {
                "source": "local-controller",
                "taskHypothesis": {
                    "taskType": "project_cleanup"
                    if pending_operation_type in _PROJECT_ASSET_CLEANUP_OPERATION_TYPES
                    else agent_operation_task_type(pending_operation_type),
                    "routeSource": "destructive_confirmation_required",
                },
            },
            "sessionStatus": "idle",
            "pendingOperation": pending_operation_context,
        }




def _resolve_pending_turn_operation(
    project_id: str,
    episode_id: str | None,
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
    candidate_ref: dict[str, Any] | None = None,
    confirmed_by_action: bool = False,
) -> dict[str, Any] | None:
    pending_local_result = _agent_pending_operation_local_result(
        project_id,
        state,
        routing_message,
        pending_operation_context,
        session_id=session_id,
    )
    if pending_local_result:
        return pending_local_result
    if selected_preferred_task_type == "project_status":
        return _agent_project_status_result(state, routing_message)
    if (
        _agent_message_is_pending_operation_confirmation_reply(routing_message, pending_operation_context)
        and pending_operation_context.get("active")
        and pending_operation_type == "commit_plot_split"
    ):
        return _resolve_plot_split_confirmation(
            project_id=project_id,
            episode_id=episode_id,
            session_id=session_id,
            session_policy=session_policy,
            routing_message=routing_message,
            progress_episode_id=progress_episode_id,
            state=state,
            selected_episode_id=selected_episode_id,
            pending_operation_context=pending_operation_context,
            pending_operation_type=pending_operation_type,
            candidate_ref=candidate_ref,
        )

    if (
        pending_operation_context.get("active")
        and _agent_message_is_pending_operation_confirmation_reply(routing_message, pending_operation_context)
    ):
        try:
            validate_agent_session_pending_operation(pending_operation_type, session_policy)
        except ValueError as exc:
            return _agent_session_policy_rejection(
                state,
                exc,
                task_type=_agent_task_type_for_pending_operation(pending_operation_type),
                route_source="pending_operation_session_policy_rejected",
            )
    if pending_operation_context.get("active") and pending_operation_type in _AGENT_DESTRUCTIVE_OPERATION_TYPES:
        return _resolve_destructive_confirmation(
            project_id=project_id,
            episode_id=episode_id,
            session_id=session_id,
            routing_message=routing_message,
            context_scope_value=context_scope_value,
            progress_episode_id=progress_episode_id,
            state=state,
            pending_operation_context=pending_operation_context,
            pending_operation_type=pending_operation_type,
            confirmed_by_action=confirmed_by_action,
        )
