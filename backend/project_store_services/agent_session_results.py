# -*- coding: utf-8 -*-
"""会话回合完成、取消、结果报告与状态持久化。"""
from __future__ import annotations
import uuid
from utils.agent_execution_state import (
    accepts_execution, bound_task_status, current_execution_id, require_task_execution,
)

import copy as copy
import traceback as traceback
from .agent_canvas_events import (
    _emit_agent_project_effect,
)
from .agent_contracts import (
    AGENT_GENERATION_TASKS,
    _agent_steps_from_state,
    agent_target_for_scope as _agent_active_target_for_scope,
    recent_creative_task_target,
)
from .agent_conversation_context import (
    _apply_agent_session_context,
    _save_agent_turn_conversation_context,
)
from .agent_model_runtime import (
    _agent_runtime_config_failure_message,
)
from .agent_progress_recommendations import (
    _agent_progress_state,
    _agent_result_content_blocks,
)
from .agent_result_presentation import (
    _agent_maybe_append_completion_next_step,
    _agent_normalize_result_action_footer_blocks,
    _agent_result_suppresses_session_message,
    _agent_result_waits_for_background_session_report,
    _agent_sanitize_user_facing_content_blocks,
    _agent_sanitize_user_facing_text,
    _agent_session_policy_rejection,
)
from .agent_session_events import (
    _emit_agent_session_update,
)
from .agent_sessions import (
    _agent_message_row,
    _agent_session_detail,
    _agent_session_summaries,
    _agent_session_title_for_message,
    _agent_snapshot_from_session,
    _apply_agent_message_retention,
    _ensure_agent_session,
    _load_agent_sessions,
    _normalize_agent_message_rows,
    _normalize_agent_pending_operation,
    _normalize_agent_pending_question,
    _normalize_agent_session_step_rows,
    _save_agent_sessions,
    append_agent_execution_error,
)
from .agent_task_status import (
    _agent_update_task_if_active,
)
from .runtime_state import (
    _AGENT_CANCEL_FLAGS,
    _LOCK,
)
from .store_core import (
    _emit_agent_event,
    _now,
)

from typing import Any


def _update_plot_split_preview_statuses(
    messages: list[dict[str, Any]],
    previous_pending: dict[str, Any],
    result: dict[str, Any],
) -> None:
    next_pending = result.get("pendingOperation") if isinstance(result.get("pendingOperation"), dict) else {}
    next_id = (
        str(next_pending.get("candidateId") or next_pending.get("runId") or "").strip()
        if next_pending.get("operationType") == "commit_plot_split" else ""
    )
    cancelled_id = str(result.get("cancelledCandidateId") or "").strip()
    previous_id = (
        str(previous_pending.get("candidateId") or previous_pending.get("runId") or "").strip()
        if previous_pending.get("operationType") == "commit_plot_split" else ""
    )
    model_meta = result.get("agentModelMeta") if isinstance(result.get("agentModelMeta"), dict) else {}
    hypothesis = model_meta.get("taskHypothesis") if isinstance(model_meta.get("taskHypothesis"), dict) else {}
    committed_id = previous_id if (
        previous_id and result.get("success") and result.get("projectChanged")
        and "pendingOperation" in result and result["pendingOperation"] is None
        and hypothesis.get("routeSource") == "pending_operation_confirmation"
    ) else ""
    if not (next_id or cancelled_id or committed_id):
        return
    status_text = {
        "cancelled": "剧情拆分候选已取消。",
        "committed": "剧情拆分候选已确认并写入。",
        "superseded": "上一版剧情拆分候选已被新版替换。",
    }
    for message in messages:
        if message.get("role") != "assistant":
            continue
        updated_status = ""
        for block in message.get("content") or []:
            if not (
                isinstance(block, dict)
                and block.get("type") == "plot_split_preview"
                and block.get("status") == "pending_confirmation"
            ):
                continue
            candidate_id = str(block.get("candidateId") or "").strip()
            block_status = ""
            if candidate_id == cancelled_id:
                block_status = "cancelled"
            elif candidate_id == committed_id:
                block_status = "committed"
            elif next_id and candidate_id != next_id:
                block_status = "superseded"
            if block_status:
                block["status"] = block_status
                updated_status = block_status
        if updated_status and all(
            isinstance(block, dict) and block.get("type") == "plot_split_preview"
            for block in message.get("content") or []
        ):
            message["text"] = status_text[updated_status]


def _recent_task_target_from_commit_receipt(
    project_id: str, session_id: str, episode_id: str | None, receipt: Any,
) -> dict[str, str]:
    """Remember the actual node written by a creative task for later feedback."""
    if not isinstance(receipt, dict) or not episode_id:
        return {}
    expected_type = {
        "workflow_cinematic_script_generation": "prompt.storyboard",
        "director_plan_generation": "director.board",
    }.get(str(receipt.get("taskType") or ""))
    target_ids = receipt.get("targetIds")
    if (
        not expected_type or not isinstance(target_ids, list) or len(target_ids) != 1
        or str(receipt.get("projectId") or "") != project_id
        or str(receipt.get("sessionId") or "") != session_id
        or str(receipt.get("episodeId") or "") != episode_id
    ):
        return {}
    node_id = str(target_ids[0] or "").strip()
    if not node_id:
        return {}
    from .canvas_store_queries import read_canvas_card_record_v4
    try:
        node = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="summary")
    except (FileNotFoundError, ValueError, OSError):
        # Follow-up context must never turn a committed write into a failure.
        return {}
    if str(node.get("type") or "") != expected_type:
        return {}
    return recent_creative_task_target({
        "source": "storyboard_canvas", "intent": "generate", "section": "episode",
        "episodeId": episode_id, "canvasKind": "work_chain", "nodeId": node_id,
        "nodeType": expected_type, "routeId": node.get("routeId"),
        "workChainId": node.get("workChainId"),
    }, episode_id)


def _finish_agent_session_result(
    project_id: str,
    session_id: str,
    episode_id: str | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    cancel_child_ids: set[str] = set()
    with _LOCK:
        sessions = _load_agent_sessions(project_id)
        session = next((row for row in sessions if str(row.get("id") or "") == str(session_id)), None)
        if session is None:
            raise FileNotFoundError("智能体会话不存在")
        identity = str(result.get("executionId") or current_execution_id(session_id) or "")
        execution = session.get("execution") or {}
        same_execution_finished = (
            identity and identity == execution.get("id") and execution.get("parentReported")
            and not result.get("reportedGenerationTaskId")
        )
        if (not accepts_execution(session, identity) or same_execution_finished
                or (identity and session.get("supersededExecutionId") == identity)):
            result.update(contentBlocks=[], suppressSessionMessage=True, sessionStatus=session.get("status"),
                          session=_agent_session_detail(project_id, session),
                          snapshot=_agent_snapshot_from_session(project_id, session),
                          sessions=_agent_session_summaries(project_id, episode_id or session.get("episodeId")),
                          sessionId=session_id)
            return result
        pending_candidate = result.get("pendingOperation") if isinstance(result.get("pendingOperation"), dict) else {}
        submitted_candidate = bool(
            (pending_candidate.get("type") == "commit_episode_boundary"
             and isinstance(pending_candidate.get("proposal"), dict)
             and pending_candidate["proposal"].get("proposalId"))
            or (pending_candidate.get("type") == "commit_plot_split"
                and pending_candidate.get("runId"))
            or (pending_candidate.get("type") == "commit_asset_range"
                and pending_candidate.get("runId") and pending_candidate.get("candidateId"))
        )
        if str(session.get("status") or "") == "interrupted" and submitted_candidate:
            # The candidate was durably saved while cancellation raced with its tool reply.
            # Show the real pending result instead of leaving an invisible saved proposal.
            result["sessionStatus"] = "idle"
        elif str(session.get("status") or "") == "interrupted" and str(result.get("sessionStatus") or "") != "interrupted":
            result["sessionStatus"] = "interrupted"
            result["message"] = "智能体执行已停止，后台晚到结果已忽略。"
            result["session"] = _agent_session_detail(project_id, session)
            result["snapshot"] = _agent_snapshot_from_session(project_id, session)
            result["sessions"] = _agent_session_summaries(project_id, episode_id or session.get("episodeId"))
            result["sessionId"] = session_id
            return result
        if result.get("message"):
            result["message"] = _agent_sanitize_user_facing_text(result.get("message"))
        reported_generation_task_id = str(
            result.get("reportedGenerationTaskId")
            or result.get("reported_generation_task_id")
            or ""
        ).strip()
        reported_generation_task_source = (
            session.get("reportedGenerationTaskIds")
            if isinstance(session.get("reportedGenerationTaskIds"), list)
            else []
        )
        reported_generation_task_ids = [
            str(item).strip()
            for item in reported_generation_task_source
            if str(item).strip()
        ]
        already_reported_generation_task = bool(
            reported_generation_task_id
            and reported_generation_task_id in reported_generation_task_ids
        )
        child_tasks = result.get("tasks") or [result.get("task")]
        child_task_ids = {str(task.get("id")) for task in child_tasks if isinstance(task, dict) and task.get("id")}
        waiting_background = _agent_result_waits_for_background_session_report(result)
        from .agent_sessions import _agent_session_recovery_task_rows
        task_rows = _agent_session_recovery_task_rows(project_id)
        if not reported_generation_task_id:
            if waiting_background:
                stored_tasks = {str(task.get("id")): task for task in task_rows}
                for child_id in child_task_ids:
                    require_task_execution(stored_tasks.get(child_id, {}), session_id, identity)
                    if child_id not in execution.get("blockingTaskIds", []):
                        raise RuntimeError("后台任务尚未绑定本轮执行，无法等待任务结果。")
            execution["dispatchClosed"] = True
            execution["parentReported"] = True
            if result.get("success") is False:
                execution["parentFailed"] = True
                cancel_child_ids = set(execution.get("blockingTaskIds") or [])
        terminal_status = bound_task_status(session, task_rows)
        if already_reported_generation_task:
            result["contentBlocks"] = []
            result["sessionStatus"] = session.get("status")
            result["suppressSessionMessage"] = True
            result["session"] = _agent_session_detail(project_id, session)
            result["snapshot"] = _agent_snapshot_from_session(project_id, session)
            result["sessions"] = _agent_session_summaries(project_id, episode_id or session.get("episodeId"))
            result["sessionId"] = session_id
            result["conversationId"] = session_id
            return result
        _agent_maybe_append_completion_next_step(project_id, episode_id, session, result)
        _agent_normalize_result_action_footer_blocks(project_id, result)
        if isinstance(result.get("contentBlocks"), list):
            result["contentBlocks"] = _agent_sanitize_user_facing_content_blocks(result["contentBlocks"])
        messages = _normalize_agent_message_rows(session.get("messages"), project_id)
        _update_plot_split_preview_statuses(
            messages,
            session.get("pendingOperation") if isinstance(session.get("pendingOperation"), dict) else {},
            result,
        )
        if submitted_candidate:
            for previous in reversed(messages):
                if previous.get("role") != "assistant":
                    continue
                content = previous.get("content") if isinstance(previous.get("content"), list) else []
                if any(isinstance(block, dict) and block.get("type") == "interrupt_notice" for block in content):
                    previous["text"] = "停止请求时，候选已暂存，请审阅或取消。"
                    previous["content"] = [{"type": "text", "text": previous["text"]}]
                break
        next_pending = result.get("pendingOperation") if isinstance(result.get("pendingOperation"), dict) else {}
        next_proposal = next_pending.get("proposal") if isinstance(next_pending.get("proposal"), dict) else {}
        next_candidate_id = str(next_proposal.get("proposalId") or "").strip()
        if next_candidate_id and _agent_result_suppresses_session_message(result):
            candidate_blocks = [
                block for block in (result.get("contentBlocks") or [])
                if isinstance(block, dict) and block.get("type") == "episode_boundary_candidate"
                and str(block.get("candidateId") or "") == next_candidate_id
            ]
            if candidate_blocks and not any(
                isinstance(block, dict) and block.get("type") == "episode_boundary_candidate"
                and str(block.get("candidateId") or "") == next_candidate_id
                for previous in messages for block in (previous.get("content") or [])
            ):
                messages.append(_agent_message_row(
                    "assistant", "", content=candidate_blocks, project_id=project_id,
                ))
        cancelled_candidate_id = str(result.get("cancelledCandidateId") or "").strip()
        model_meta = result.get("agentModelMeta") if isinstance(result.get("agentModelMeta"), dict) else {}
        hypothesis = model_meta.get("taskHypothesis") if isinstance(model_meta.get("taskHypothesis"), dict) else {}
        cancel_candidate_without_id = (
            hypothesis.get("routeSource") == "pending_operation_cancelled" and not cancelled_candidate_id
        )
        if next_candidate_id or cancelled_candidate_id or cancel_candidate_without_id:
            for previous in messages:
                if previous.get("role") != "assistant":
                    continue
                candidate_changed = False
                candidate_cancelled = False
                for block in previous.get("content") or []:
                    if not (isinstance(block, dict) and block.get("type") == "episode_boundary_candidate"
                            and block.get("status") == "pending_confirmation"):
                        continue
                    block_id = str(block.get("candidateId") or "").strip()
                    if block_id == cancelled_candidate_id or cancel_candidate_without_id:
                        block["status"] = "cancelled"
                        candidate_changed = True
                        candidate_cancelled = True
                    elif next_candidate_id and block_id != next_candidate_id:
                        block["status"] = "superseded"
                        candidate_changed = True
                if candidate_changed:
                    previous["text"] = "分集候选已取消。" if candidate_cancelled else "上一版分集候选已替换。"
                    previous["content"] = [
                        {"type": "text", "text": previous["text"]},
                        *(block for block in previous.get("content") or []
                          if isinstance(block, dict) and block.get("type") == "episode_boundary_candidate"),
                    ]
        confirmed_candidate_id = str(result.get("confirmedCandidateId") or "").strip()
        if confirmed_candidate_id:
            for previous in reversed(messages):
                if previous.get("role") != "assistant":
                    continue
                content = previous.get("content") if isinstance(previous.get("content"), list) else []
                candidate = next((block for block in content if isinstance(block, dict)
                                  and block.get("type") == "episode_boundary_candidate"
                                  and block.get("candidateId") == confirmed_candidate_id), None)
                if candidate is None:
                    continue
                candidate["status"] = "committed"
                break
        suppress_session_message = _agent_result_suppresses_session_message(result)
        assistant_message = (
            ""
            if suppress_session_message or already_reported_generation_task
            else str(result.get("message") or "").strip()
        )
        if assistant_message:
            messages.append(
                _agent_message_row(
                    "assistant",
                    assistant_message,
                    content=_agent_result_content_blocks(project_id, result),
                    project_id=project_id,
                )
            )
        elif confirmed_candidate_id:
            recommendations = [block for block in (result.get("contentBlocks") or [])
                               if isinstance(block, dict) and block.get("type") == "recommendations"]
            if recommendations:
                messages.append(_agent_message_row("assistant", "", content=recommendations, project_id=project_id))
        _apply_agent_message_retention(session, messages)
        session["steps"] = _normalize_agent_session_step_rows(result.get("steps"))
        pending_question = _normalize_agent_pending_question(
            session.get("pendingQuestion")
            if reported_generation_task_id or (
                result.get("status") == "rejected" and result.get("pendingQuestion") is None
            )
            else result.get("pendingQuestion")
        )
        session_status = str(result.get("sessionStatus") or "").strip()
        if pending_question:
            session["pendingQuestion"] = pending_question
            session["status"] = "running"
        else:
            session.pop("pendingQuestion", None)
            if terminal_status:
                session["status"] = terminal_status
            elif reported_generation_task_id and not execution.get("dispatchClosed"):
                session["status"] = "running"
            elif session_status == "running" or waiting_background:
                session["status"] = "running"
            elif session_status in {"idle", "completed", "error", "interrupted"}:
                session["status"] = session_status
            else:
                session["status"] = "completed" if result.get("success") else "error"
        if "pendingOperation" in result:
            pending_operation = _normalize_agent_pending_operation(result.get("pendingOperation"))
            if pending_operation:
                session["pendingOperation"] = pending_operation
            else:
                session.pop("pendingOperation", None)
        if not reported_generation_task_id or execution.get("dispatchClosed"):
            session.pop("taskId", None)
            session.pop("runningAction", None)
            session.pop("runningTaskType", None)
        model_meta = result.get("agentModelMeta") if isinstance(result.get("agentModelMeta"), dict) else {}
        sdk_session_id = str(result.get("sdkSessionId") or model_meta.get("sdkSessionId") or "").strip()
        if (confirmed_candidate_id or cancelled_candidate_id or result.get("discardSdkSession")
                or execution.get("conversationHistoryChanged")):
            # Local decisions and concurrent task reports are absent from the
            # remote transcript. Rebuild from saved conversation history.
            session.pop("sdkSessionId", None)
            session.pop("sdkContextVersion", None)
        elif sdk_session_id:
            session["sdkSessionId"] = sdk_session_id
            # A new ID without its context version must never inherit a prior version.
            session["sdkContextVersion"] = str(result.get("sdkContextVersion") or model_meta.get("sdkContextVersion") or "")
        elif assistant_message:
            # Local controllers/background reports are not part of the remote
            # SDK transcript. Start fresh with bounded local history next turn.
            session.pop("sdkContextVersion", None)
        provider_instance_id = str(model_meta.get("providerInstanceId") or "").strip()
        if provider_instance_id:
            session["providerInstanceId"] = provider_instance_id
        adapter_id = str(model_meta.get("adapterId") or "").strip()
        if adapter_id:
            session["adapterId"] = adapter_id
        sdk_events = model_meta.get("sdkEvents") if isinstance(model_meta.get("sdkEvents"), dict) else {}
        tool_uses = sdk_events.get("toolUses") if isinstance(sdk_events.get("toolUses"), list) else []
        used_names = [
            str(item.get("name") or "").strip()
            for item in tool_uses
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        sdk_tool_results = (
            model_meta.get("sdkToolResults") if isinstance(model_meta.get("sdkToolResults"), list) else []
        )
        used_names.extend(
            str(item.get("tool") or "").strip()
            for item in sdk_tool_results
            if isinstance(item, dict) and str(item.get("tool") or "").strip()
        )
        if used_names:
            previous = [str(item) for item in session.get("toolsUsed", []) if str(item).strip()]
            session["toolsUsed"] = list(dict.fromkeys([*previous, *used_names]))
        if reported_generation_task_id and not already_reported_generation_task:
            session["reportedGenerationTaskIds"] = [
                *reported_generation_task_ids,
                reported_generation_task_id,
            ][-50:]
        committed_target = _recent_task_target_from_commit_receipt(
            project_id, session_id, episode_id, result.get("commitReceipt"),
        )
        if committed_target:
            session["recentTaskTarget"] = committed_target
        session["updatedAt"] = _now()
        for index, row in enumerate(sessions):
            if str(row.get("id") or "") == session_id:
                sessions[index] = session
                break
        _save_agent_sessions(project_id, sessions)
        detail = _agent_session_detail(project_id, session)
        result["session"] = detail
        result["snapshot"] = _agent_snapshot_from_session(project_id, session)
        result["sessions"] = _agent_session_summaries(project_id, episode_id or session.get("episodeId"))
        result["sessionId"] = session_id
        result["conversationId"] = session_id
    if cancel_child_ids:
        from .task_commands import cancel_agent_session_bound_tasks
        cancel_agent_session_bound_tasks(project_id, session_id, included_task_ids=cancel_child_ids)
    return result


def _agent_generation_task_session_id(task: dict[str, Any]) -> str:
    if not isinstance(task, dict):
        return ""
    return str(task.get("sessionId") or "").strip()


def _agent_generation_task_report_message(task: dict[str, Any], *, success: bool) -> str:
    task_type = str(task.get("type") or "").strip()
    label = AGENT_GENERATION_TASKS.get(task_type, {}).get("label", "生成任务")
    message = str(task.get("notice") or task.get("message") or "").strip()
    if message:
        return message
    if success:
        return f"{label}已生成成功。"
    error_text = str(task.get("error") or task.get("failureReason") or task.get("failure_reason") or "").strip()
    return f"{label}生成失败：{error_text}" if error_text else f"{label}生成失败。"


def _agent_generation_task_project_effect(task: dict[str, Any], message: str) -> dict[str, Any]:
    task_result = task.get("result") if isinstance(task.get("result"), dict) else {}
    project_effect = (
        copy.deepcopy(task.get("projectEffect"))
        if isinstance(task.get("projectEffect"), dict)
        else copy.deepcopy(task_result.get("projectEffect"))
        if isinstance(task_result.get("projectEffect"), dict)
        else {}
    )
    task_type = str(task.get("type") or "").strip()
    project_effect["projectChanged"] = True
    if not isinstance(project_effect.get("changedResources"), list):
        if task_type == "asset_image":
            fallback_resources = [
                "assets",
                str(task.get("assetType") or "").strip(),
                "canvas_task",
            ]
        else:
            fallback_resources = [
                "canvas_task",
                "canvas_node",
                *(
                    ["canvas_version"]
                    if task_type in {"storyboard_image", "visual_handoff_image", "storyboard_video", "route_video"}
                    else []
                ),
            ]
        fallback_resources = [item for item in fallback_resources if item]
        changed_resources = (
            task.get("changedResources")
            if isinstance(task.get("changedResources"), list)
            else task_result.get("changedResources")
            if isinstance(task_result.get("changedResources"), list)
            else fallback_resources
        )
        project_effect["changedResources"] = copy.deepcopy(changed_resources)
    if not isinstance(project_effect.get("focusTarget"), dict):
        focus_target = (
            copy.deepcopy(task.get("focusTarget"))
            if isinstance(task.get("focusTarget"), dict)
            else {
                "section": "episode",
                "episodeId": str(task.get("episodeId") or task.get("episode_id") or ""),
                "nodeId": str(task.get("nodeId") or task.get("node_id") or ""),
            }
        )
        project_effect["focusTarget"] = focus_target
    project_effect.setdefault(
        "action",
        AGENT_GENERATION_TASKS.get(task_type, {}).get("action", "workflow_node_generated"),
    )
    project_effect.setdefault("notice", message)
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
        "node",
        "nodes",
        "version",
        "versions",
        "editHistory",
        "editHistoryItems",
        "editHistoryWarning",
    ):
        if key not in project_effect and task_result.get(key) is not None:
            project_effect[key] = copy.deepcopy(task_result.get(key))
    for key in ("id", "nodeId", "taskNodeId", "resultNodeId", "versionNodeId", "versionId"):
        output_key = "taskId" if key == "id" else key
        if output_key not in project_effect and task.get(key) is not None:
            project_effect[output_key] = copy.deepcopy(task.get(key))
    return project_effect


def append_agent_generation_task_session_report(
    project_id: str,
    episode_id: str | None,
    task: dict[str, Any],
    *,
    success: bool,
) -> dict[str, Any] | None:
    if not isinstance(task, dict):
        return None
    task_type = str(task.get("type") or "").strip()
    if task_type not in AGENT_GENERATION_TASKS:
        return None
    task_project_id = str(task.get("projectId") or task.get("project_id") or "").strip()
    normalized_project_id = str(project_id or task_project_id or "").strip()
    if not normalized_project_id or (task_project_id and task_project_id != normalized_project_id):
        return None
    session_id = _agent_generation_task_session_id(task)
    task_id = str(task.get("id") or task.get("taskId") or "").strip()
    if not session_id or not task_id:
        return None
    task_episode_id = str(task.get("episodeId") or task.get("episode_id") or episode_id or "").strip() or None
    with _LOCK:
        sessions = _load_agent_sessions(normalized_project_id)
        session = next((row for row in sessions if str(row.get("id") or "") == session_id), None)
        if not isinstance(session, dict):
            return None
        if str(session.get("status") or "").strip() == "interrupted":
            return None
        if not accepts_execution(session, str(task.get("executionId") or "")):
            return None
        reported_source = (
            session.get("reportedGenerationTaskIds")
            if isinstance(session.get("reportedGenerationTaskIds"), list)
            else []
        )
        reported_ids = {
            str(item).strip()
            for item in reported_source
            if str(item).strip()
        }
        if task_id in reported_ids:
            return None
        resolved_episode_id = (
            task_episode_id
            or str(session.get("episodeId") or "").strip()
            or str(episode_id or "").strip()
            or None
        )
    message = _agent_generation_task_report_message(task, success=success)
    state = _agent_progress_state(
        normalized_project_id,
        resolved_episode_id,
        detail_mode=bool(resolved_episode_id),
    )
    project_effect = _agent_generation_task_project_effect(task, message) if success else None
    result: dict[str, Any] = {
        "success": bool(success),
        "message": message,
        "contentBlocks": [{"type": "text", "text": message}],
        "steps": _agent_steps_from_state(state),
        "pendingQuestion": None,
        "project": state.get("project"),
        "projectChanged": bool(success),
        "sessionStatus": "completed" if success else "error",
        "pendingOperation": None,
        "reportedGenerationTaskId": task_id,
        "executionId": str(task.get("executionId") or ""),
    }
    if project_effect:
        result["projectEffect"] = project_effect
    final_result = _finish_agent_session_result(
        normalized_project_id,
        session_id,
        resolved_episode_id,
        result,
    )
    if _agent_result_suppresses_session_message(final_result):
        return None
    session = final_result.get("session")
    if isinstance(session, dict):
        _emit_agent_session_update(
            normalized_project_id,
            resolved_episode_id,
            session,
            message=final_result.get("message") or "",
            steps=final_result.get("steps") or [],
            pending_question=final_result.get("pendingQuestion"),
            client_action=final_result.get("clientAction"),
            project_effect=final_result.get("projectEffect"),
        )
    _emit_agent_project_effect(
        normalized_project_id,
        resolved_episode_id,
        final_result.get("projectEffect") if isinstance(final_result.get("projectEffect"), dict) else None,
        session_id=session_id,
    )
    return final_result.get("session") if isinstance(final_result.get("session"), dict) else final_result


def _interrupt_agent_session_state(
    project_id: str,
    session_id: str | None,
    *,
    emit_events: bool = False,
    expected_execution_id: str = "",
    superseded_by_feedback: bool = False,
    feedback_message: str = "",
) -> dict[str, Any]:
    if not session_id:
        raise ValueError("缺少智能体会话 ID")
    task = None
    task_id = ""
    with _LOCK:
        sessions = _load_agent_sessions(project_id)
        session = next((row for row in sessions if str(row.get("id") or "") == str(session_id)), None)
        if session is None:
            raise FileNotFoundError("智能体会话不存在")
        identity = str((session.get("execution") or {}).get("id") or "")
        if expected_execution_id and identity and expected_execution_id != identity:
            return {"success": True, "session": _agent_session_detail(project_id, session), "message": "该执行已结束"}
        if superseded_by_feedback and (
            session.get("status") != "running" or session.get("runningTaskType") not in {"native_chat", "episode_boundary_propose", "asset_range_propose", "asset_extraction", "work_chain_plan_save", "workflow_cinematic_script_generation", "director_plan_generation", "video_prompt_generation", "video_prompt_optimization", "video_prompt_standalone_generation"}
        ):
            return {"success": False, "feedbackAccepted": False, "message": "当前执行已进入下一阶段"}
        cancel_flag = _AGENT_CANCEL_FLAGS.get(identity or str(session_id))
        if cancel_flag:
            cancel_flag.set()
        if superseded_by_feedback:
            session["supersededExecutionId"] = identity
            session["requirementRevision"] = int(session.get("requirementRevision") or 0) + 1
            session.pop("sdkSessionId", None)
            session.pop("sdkContextVersion", None)
        from .agent_sessions import _agent_session_recovery_task_rows
        stop_task_ids = {
            str(item.get("id")) for item in _agent_session_recovery_task_rows(project_id)
            if str(item.get("sessionId") or "") == str(session_id)
            and (not identity or str(item.get("executionId") or item.get("id")) == identity)
        }
        task_id = str(session.get("taskId") or "").strip()
        steps = []
        for step in _normalize_agent_session_step_rows(session.get("steps")):
            if step.get("status") == "running":
                step["status"] = "failed"
            steps.append(step)
        messages = _normalize_agent_message_rows(session.get("messages"), project_id)
        interrupted_text = "已停止当前智能体执行。你可以继续输入新的指令，或切换到其他会话查看状态。"
        last_message = messages[-1] if messages else {}
        last_blocks = last_message.get("content") if isinstance(last_message, dict) else []
        already_interrupted = any(
            isinstance(block, dict) and block.get("type") == "interrupt_notice"
            for block in (last_blocks if isinstance(last_blocks, list) else [])
        )
        if not already_interrupted:
            messages.append(
                _agent_message_row(
                    "assistant",
                    interrupted_text,
                    content=[{"type": "interrupt_notice", "text": interrupted_text}],
                    project_id=project_id,
                )
            )
        if superseded_by_feedback and feedback_message.strip():
            messages.append(_agent_message_row(
                "user", feedback_message.strip(), project_id=project_id,
            ))
        _apply_agent_message_retention(session, messages)
        session["steps"] = steps
        session["status"] = "interrupted"
        session["updatedAt"] = _now()
        session.pop("pendingQuestion", None)
        session.pop("taskId", None)
        session.pop("runningAction", None)
        session.pop("runningTaskType", None)
        if superseded_by_feedback:
            from .agent_run_store import change_episode_candidate_status, list_open_episode_candidates
            pending = session.get("pendingOperation") if isinstance(session.get("pendingOperation"), dict) else {}
            proposal = pending.get("proposal") if isinstance(pending.get("proposal"), dict) else {}
            target_candidate_ids = {
                str((session.get("execution") or {}).get("candidateId") or ""),
                str(proposal.get("proposalId") or ""),
            } - {""}
            for candidate in list_open_episode_candidates(project_id, str(session_id)):
                if (candidate.get("status") != "awaiting_confirmation"
                        or candidate.get("candidateId") not in target_candidate_ids):
                    continue
                change_episode_candidate_status(
                    project_id, str(session_id), candidate["candidateId"], "superseded",
                    expected_digest=candidate["digest"],
                )
        for index, row in enumerate(sessions):
            if str(row.get("id") or "") == str(session_id):
                sessions[index] = session
                break
        _save_agent_sessions(project_id, sessions)
    if task_id:
        task = _agent_update_task_if_active(
            task_id,
            status="cancelled",
            progress=0,
            message="智能体执行已停止",
            cancelledAt=_now(),
        )
    cancelled_tasks_result: dict[str, Any] = {
        "success": True,
        "attemptedTaskIds": [],
        "cancelledTaskIds": [],
        "uncancelledTaskIds": [],
        "tasks": [],
        "cancelledTasks": [],
        "uncancelledTasks": [],
        "uncancelledTaskReasons": [],
        "errors": [],
    }
    try:
        from . import task_commands as _task_commands_services

        canceller = getattr(_task_commands_services, "cancel_agent_session_bound_tasks", None)
        if callable(canceller):
            cancelled_tasks_result = canceller(
                project_id,
                str(session_id),
                exclude_task_ids={task_id} if task_id else set(),
                included_task_ids=stop_task_ids,
            )
        else:
            cancelled_tasks_result = {
                "success": False,
                "attemptedTaskIds": [],
                "cancelledTaskIds": [],
                "uncancelledTaskIds": [],
                "tasks": [],
                "cancelledTasks": [],
                "uncancelledTasks": [],
                "uncancelledTaskReasons": [],
                "errors": [{"message": "后台任务取消入口不可用"}],
            }
    except Exception as exc:  # noqa: BLE001
        cancelled_tasks_result = {
            "success": False,
            "attemptedTaskIds": [],
            "cancelledTaskIds": [],
            "uncancelledTaskIds": [],
            "tasks": [],
            "cancelledTasks": [],
            "uncancelledTasks": [],
            "uncancelledTaskReasons": [],
            "errors": [{"message": str(exc) or exc.__class__.__name__}],
        }
        try:
            append_agent_execution_error(
                project_id,
                stage="interrupt_agent_session",
                message="停止智能体会话时取消后台任务失败",
                episode_id=str(session.get("episodeId") or "") or None,
                session_id=str(session_id),
                category="agent_session_cancel_bound_tasks_error",
                source="_interrupt_agent_session_state",
                error=exc,
                details={"taskId": task_id},
                include_traceback=True,
            )
        except Exception:
            print(traceback.format_exc(), flush=True)
    cancel_errors = [
        error
        for error in (cancelled_tasks_result.get("errors") or [])
        if isinstance(error, dict)
    ]
    uncancelled_tasks = [
        item
        for item in (cancelled_tasks_result.get("uncancelledTasks") or [])
        if isinstance(item, dict)
    ]
    uncancelled_task_ids = [
        str(item or "").strip()
        for item in (cancelled_tasks_result.get("uncancelledTaskIds") or [])
        if str(item or "").strip()
    ]
    uncancelled_task_reasons = [
        item
        for item in (cancelled_tasks_result.get("uncancelledTaskReasons") or [])
        if isinstance(item, dict)
    ]
    partial_failure = (
        bool(cancel_errors)
        or cancelled_tasks_result.get("success") is False
    )
    if cancel_errors:
        result_message = "已停止当前智能体执行，但部分后台生成任务取消失败，请在任务面板查看状态。"
    elif uncancelled_task_ids:
        result_message = "已停止当前智能体执行；部分后台生成任务已进入保存或结束阶段，无法继续中断，已产生的结果会保留。"
    else:
        result_message = "已停止当前智能体执行"
    result = {
        "success": True,
        "feedbackAccepted": bool(superseded_by_feedback and feedback_message.strip()),
        "partialFailure": partial_failure,
        "message": result_message,
        "steps": steps,
        "pendingQuestion": None,
        "task": task,
        "tasks": cancelled_tasks_result.get("tasks") or [],
        "cancelledTaskIds": cancelled_tasks_result.get("cancelledTaskIds") or [],
        "cancelledTasks": cancelled_tasks_result.get("cancelledTasks") or [],
        "uncancelledTaskIds": uncancelled_task_ids,
        "uncancelledTasks": uncancelled_tasks,
        "uncancelledTaskReasons": uncancelled_task_reasons,
        "cancelErrors": cancel_errors,
        "session": _agent_session_detail(project_id, session),
        "snapshot": _agent_snapshot_from_session(project_id, session),
        "sessions": _agent_session_summaries(project_id, session.get("episodeId")),
    }
    if emit_events:
        if task:
            _emit_agent_event("task_cancelled", task)
        _emit_agent_session_update(
            project_id,
            str(session.get("episodeId") or ""),
            session,
            message=result["message"],
            steps=steps,
            pending_question=None,
        )
    return result


def interrupt_agent_session(project_id: str, session_id: str | None) -> dict[str, Any]:
    return _interrupt_agent_session_state(project_id, session_id)


def _agent_runtime_config_failure_result(
    project_id: str,
    episode_id: str | None,
    *,
    state: dict[str, Any],
    message: str,
    images: list[dict[str, Any]],
    session_id: str | None,
    selected_episode_id: str,
    episode_title: str,
    model_meta: dict[str, Any] | None,
    append_user_message: bool,
    scope: str = "episode",
    session_episode_id: str | None = None,
    workflow_id: str | None = None,
    active_target: dict[str, Any] | None = None,
    control_only: bool = False,
    quick_prompt_id: str = "",
    execution_message: str = "",
) -> dict[str, Any]:
    reply = _agent_runtime_config_failure_message(model_meta)
    steps = _agent_steps_from_state(state)
    context_episode_id = session_episode_id or selected_episode_id
    effective_session_id = str(session_id or "").strip() or None
    with _LOCK:
        session, sessions = _ensure_agent_session(
            project_id,
            effective_session_id,
            context_episode_id,
            _agent_session_title_for_message(episode_title, message),
        )
        _apply_agent_session_context(
            session,
            scope=scope,
            episode_id=context_episode_id,
            workflow_id=workflow_id,
        )
        active_target_context = _agent_active_target_for_scope(scope, active_target)
        if active_target_context:
            session["activeTarget"] = active_target_context
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
                    message or "继续执行项目拆分流程",
                    attachments=images,
                    project_id=project_id,
                    control_only=control_only,
                    quick_prompt_id=quick_prompt_id,
                    execution_message=execution_message,
                )
            )
        messages.append(
            _agent_message_row(
                "assistant",
                reply,
                content=[{"type": "text", "text": reply}],
                project_id=project_id,
            )
        )
        _apply_agent_message_retention(session, messages)
        session["steps"] = steps
        session["status"] = "error"
        session["execution"] = {"id": f"local-{uuid.uuid4().hex}", "blockingTaskIds": [], "dispatchClosed": True}
        session["updatedAt"] = _now()
        session.pop("pendingQuestion", None)
        session.pop("taskId", None)
        session.pop("runningAction", None)
        for index, row in enumerate(sessions):
            if str(row.get("id") or "") == str(session.get("id") or ""):
                sessions[index] = session
                break
        _save_agent_sessions(project_id, sessions)
        session_detail = _agent_session_detail(project_id, session)
        snapshot = _agent_snapshot_from_session(
            project_id,
            session,
            live_activity=["智能体供应商配置不可用，已停止启动后台任务"],
        )
        session_summaries = _agent_session_summaries(project_id, context_episode_id)

    error_text = str((model_meta or {}).get("error") or "").strip()
    append_agent_execution_error(
        project_id,
        stage="agent_runtime_config",
        message="智能体供应商配置不可用",
        episode_id=context_episode_id,
        session_id=str(session.get("id") or ""),
        category="provider_runtime_error",
        source="agent_model",
        error=error_text,
        details={
            "modelMeta": model_meta or {},
            "message": message,
            "scope": scope,
            "workflowId": workflow_id or "",
            "activeTarget": active_target_context,
        },
    )
    _save_agent_turn_conversation_context(
        project_id,
        context_episode_id,
        scope=scope,
        session_id=str(session.get("id") or ""),
        workflow_id=str(workflow_id or ""),
        active_target=active_target_context,
    )
    _emit_agent_session_update(
        project_id,
        context_episode_id,
        session,
        message=reply,
        steps=steps,
        pending_question=None,
        live_activity=["智能体供应商配置不可用，已停止启动后台任务"],
    )
    return {
        "success": False,
        "code": "agent_runtime_config_unavailable",
        "status": "rejected",
        "backgroundStarted": False,
        "message": reply,
        "steps": steps,
        "pendingQuestion": None,
        "task": None,
        "tasks": [],
        "session": session_detail,
        "snapshot": snapshot,
        "sessions": session_summaries,
        "sessionId": str(session.get("id") or ""),
        "episodeId": context_episode_id,
        "scope": scope,
        "workflowId": workflow_id or "",
        "sessionStatus": "error",
        "agentModelMeta": model_meta or {},
    }


def _finish_agent_session_policy_rejection(
    project_id: str,
    session_id: str | None,
    episode_id: str | None,
    *,
    state: dict[str, Any],
    reason: str | Exception,
    message: str = "",
    images: list[dict[str, Any]] | None = None,
    append_user_message: bool = True,
    scope: str = "episode",
    workflow_id: str | None = None,
    active_target: dict[str, Any] | None = None,
    task_type: str = "project_status",
    route_source: str = "session_policy_rejected",
    control_only: bool = False,
    quick_prompt_id: str = "",
    execution_message: str = "",
) -> dict[str, Any]:
    user_text = str(message or "").strip() or ("继续项目流程" if scope == "project" else "继续当前集流程")
    result = _agent_session_policy_rejection(
        state,
        reason,
        task_type=task_type,
        route_source=route_source,
    )
    episode_title = "项目会话" if scope == "project" else str(state.get("selectedEpisodeTitle") or episode_id or "E01")
    with _LOCK:
        session, sessions = _ensure_agent_session(
            project_id,
            session_id,
            episode_id,
            _agent_session_title_for_message(episode_title, user_text),
        )
        _apply_agent_session_context(
            session,
            scope=scope,
            episode_id=episode_id,
            workflow_id=workflow_id,
        )
        if active_target:
            session["activeTarget"] = copy.deepcopy(active_target)
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
                    user_text,
                    attachments=images or [],
                    project_id=project_id,
                    control_only=control_only,
                    quick_prompt_id=quick_prompt_id,
                    execution_message=execution_message,
                )
            )
        _apply_agent_message_retention(session, messages)
        session["steps"] = _normalize_agent_session_step_rows(result.get("steps"))
        pending_question = session.get("pendingQuestion")
        session["status"] = "running" if pending_question else "idle"
        session["execution"] = {"id": f"local-{uuid.uuid4().hex}", "blockingTaskIds": [], "dispatchClosed": False}
        result["executionId"] = session["execution"]["id"]
        session["updatedAt"] = _now()
        if pending_question:
            result["pendingQuestion"] = copy.deepcopy(pending_question)
        session.pop("taskId", None)
        session.pop("runningAction", None)
        for index, row in enumerate(sessions):
            if str(row.get("id") or "") == str(session.get("id") or ""):
                sessions[index] = session
                break
        _save_agent_sessions(project_id, sessions)
        session_id_value = str(session["id"])

    _save_agent_turn_conversation_context(
        project_id,
        episode_id,
        scope=scope,
        session_id=session_id_value,
        workflow_id=workflow_id or "",
        active_target=active_target,
    )
    result = _finish_agent_session_result(project_id, session_id_value, episode_id, result)
    result["backgroundStarted"] = False
    result["status"] = "rejected"
    result["episodeId"] = episode_id
    result["scope"] = scope
    result["workflowId"] = workflow_id or ""
    return result


def _finish_agent_session_local_result(
    project_id: str,
    session_id: str | None,
    episode_id: str | None,
    *,
    state: dict[str, Any],
    result: dict[str, Any],
    message: str = "",
    images: list[dict[str, Any]] | None = None,
    append_user_message: bool = True,
    scope: str = "episode",
    workflow_id: str | None = None,
    active_target: dict[str, Any] | None = None,
    control_only: bool = False,
    quick_prompt_id: str = "",
    execution_message: str = "",
) -> dict[str, Any]:
    user_text = str(message or "").strip() or ("继续项目流程" if scope == "project" else "继续当前集流程")
    episode_title = "项目会话" if scope == "project" else str(state.get("selectedEpisodeTitle") or episode_id or "E01")
    with _LOCK:
        session, sessions = _ensure_agent_session(
            project_id,
            session_id,
            episode_id,
            _agent_session_title_for_message(episode_title, user_text),
        )
        _apply_agent_session_context(
            session,
            scope=scope,
            episode_id=episode_id,
            workflow_id=workflow_id,
        )
        if active_target:
            session["activeTarget"] = copy.deepcopy(active_target)
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
                    user_text,
                    attachments=images or [],
                    project_id=project_id,
                    control_only=control_only,
                    quick_prompt_id=quick_prompt_id,
                    execution_message=execution_message,
                )
            )
        _apply_agent_message_retention(session, messages)
        session["steps"] = _normalize_agent_session_step_rows(result.get("steps"))
        session["status"] = str(result.get("sessionStatus") or "idle")
        session["execution"] = {"id": f"local-{uuid.uuid4().hex}", "blockingTaskIds": [], "dispatchClosed": False}
        result["executionId"] = session["execution"]["id"]
        session["updatedAt"] = _now()
        session.pop("pendingQuestion", None)
        if "pendingOperation" in result:
            pending_operation = _normalize_agent_pending_operation(result.get("pendingOperation"))
            if pending_operation:
                session["pendingOperation"] = pending_operation
            else:
                session.pop("pendingOperation", None)
        session.pop("taskId", None)
        session.pop("runningAction", None)
        for index, row in enumerate(sessions):
            if str(row.get("id") or "") == str(session.get("id") or ""):
                sessions[index] = session
                break
        _save_agent_sessions(project_id, sessions)
        session_id_value = str(session["id"])

    _save_agent_turn_conversation_context(
        project_id,
        episode_id,
        scope=scope,
        session_id=session_id_value,
        workflow_id=workflow_id or "",
        active_target=active_target,
    )
    final = _finish_agent_session_result(project_id, session_id_value, episode_id, result)
    final["backgroundStarted"] = False
    final["status"] = str(result.get("status") or "idle")
    final["episodeId"] = episode_id
    final["scope"] = scope
    final["workflowId"] = workflow_id or ""
    return final
