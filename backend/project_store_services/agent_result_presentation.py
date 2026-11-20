# -*- coding: utf-8 -*-
"""智能体结果、追问、摘要和策略拒绝的用户可见内容。"""
from __future__ import annotations

from .agent_session_policy import (
    validate_agent_session_task_type,
)

import copy as copy
import re as re
import traceback as traceback
import uuid as uuid
from .agent_action_contract import (
    _agent_action_label,
    _agent_allowed_actions,
)
from .agent_contracts import (
    _agent_action_footer_instruction,
    _agent_steps_from_state,
)
from .agent_progress_recommendations import (
    _agent_production_actions,
    _agent_progress_message,
    _agent_progress_state,
    _agent_recommended_next_step,
    _agent_next_step_recommendations_block,
    _agent_stage_next_step_label,
)
from .agent_session_policy import (
    agent_session_context_scope,
)
from .agent_sessions import (
    _agent_action_footer_text,
    _agent_attach_action_footer_to_content_blocks,
    _agent_blocks_from_attachment_fields,
    _agent_blocks_have_body_text,
    _normalize_agent_action_footer,
    _normalize_agent_content_blocks,
    _normalize_agent_pending_operation,
    _normalize_agent_pending_question,
)

from typing import Any


def _agent_next_step_action_footer(state: dict[str, Any]) -> dict[str, str]:
    if state.get("stage") == "production" and len(_agent_production_actions(state)) > 1:
        return _agent_action_footer_instruction(
            "选择下一步", "生成片段剧本（可选）或直接生成分镜脚本",
            description="请选择一个操作；仅回复“继续”不会替你选择。",
        )
    step = _agent_recommended_next_step(state)
    if not step:
        return {}
    stage = str(state.get("stage") or "").strip()
    label = str(step.get("label") or "").strip()
    description = str(step.get("description") or "").strip()
    task_type = str(step.get("taskType") or "").strip()
    if stage == "project_complete" and bool(state.get("projectScope", True)):
        return _agent_action_footer_instruction(
            "下一步",
            description or "当前项目流程已完成。",
        )
    if not label:
        label = _agent_stage_next_step_label(state)
    if stage == "episode_workflow":
        label = "拆分当前集原文并生成工作链"
        description = (
            "我会先报告每段剧情及关联资产；你确认后，再按拆分结果创建画布工作链。"
        )
    return _agent_action_footer_instruction(
        "下一步",
        label,
        description=description,
        reply="继续" if task_type and task_type not in {"free_chat", "project_status", "quality_review"} else "",
    )


def _agent_attach_action_footer_instruction(result: dict[str, Any], instruction: Any) -> None:
    footer = _normalize_agent_action_footer(instruction)
    if not footer:
        return
    message = str(result.get("message") or "").strip()
    blocks = copy.deepcopy(
        result.get("contentBlocks") if isinstance(result.get("contentBlocks"), list) else []
    )
    if message and not _agent_blocks_have_body_text(blocks):
        blocks.insert(0, {"type": "text", "text": message})
    result["contentBlocks"] = _agent_attach_action_footer_to_content_blocks(
        blocks,
        footer,
        base_text=message,
    )


def _agent_append_action_reply_instruction(result: dict[str, Any], text: Any) -> None:
    if not _normalize_agent_action_footer(text):
        return
    _agent_attach_action_footer_instruction(result, text)


def _agent_result_background_started(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("backgroundStarted") is True:
        return True
    worker_result = result.get("workerResult") if isinstance(result.get("workerResult"), dict) else {}
    if worker_result.get("backgroundStarted") is True:
        return True
    return False


def _agent_result_suppresses_session_message(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    return bool(result.get("suppressSessionMessage") or result.get("suppress_session_message"))


def _agent_result_waits_for_background_session_report(result: dict[str, Any]) -> bool:
    return _agent_result_background_started(result) and _agent_result_suppresses_session_message(result)


def _agent_blocks_have_action_footer(blocks: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(block, dict)
        and str(block.get("type") or "") == "text"
        and bool(block.get("actionFooter") or block.get("action_footer"))
        for block in blocks
    )


def _agent_normalize_result_action_footer_blocks(project_id: str, result: dict[str, Any]) -> None:
    message = str(result.get("message") or "").strip()
    raw_blocks = copy.deepcopy(
        result.get("contentBlocks") if isinstance(result.get("contentBlocks"), list) else []
    )
    if message and not _agent_blocks_have_body_text(raw_blocks):
        raw_blocks.insert(0, {"type": "text", "text": message})
    if not raw_blocks:
        return
    normalized_blocks = _normalize_agent_content_blocks(
        raw_blocks,
        project_id,
        hydrate=False,
    )
    if normalized_blocks:
        result["contentBlocks"] = normalized_blocks


def _agent_append_text_content_block(
    result: dict[str, Any],
    text: str,
    *,
    base_text: str = "",
    placement: str = "",
) -> None:
    if not text:
        return
    blocks = copy.deepcopy(
        result.get("contentBlocks") if isinstance(result.get("contentBlocks"), list) else []
    )
    normalized_placement = str(placement or "").strip()
    if base_text and not _agent_blocks_have_body_text(blocks):
        blocks.append({"type": "text", "text": base_text})
    block: dict[str, Any] = {"type": "text", "text": text}
    if normalized_placement:
        block["placement"] = normalized_placement
    blocks.append(block)
    result["contentBlocks"] = blocks


def _agent_followup_progress_state(
    project_id: str,
    episode_id: str | None,
    session: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    followup_episode_id = _agent_result_episode_id_for_followup(result, episode_id, session)
    context_scope = agent_session_context_scope(
        str(session.get("contextScope") or session.get("scope") or ""),
        str(session.get("episodeId") or episode_id or ""),
    )
    return _agent_progress_state(
        project_id,
        followup_episode_id,
        detail_mode=context_scope == "episode",
    )


def _agent_result_episode_id_for_followup(
    result: dict[str, Any],
    episode_id: str | None,
    session: dict[str, Any],
) -> str | None:
    context_scope = agent_session_context_scope(
        str(session.get("contextScope") or session.get("scope") or ""),
        str(session.get("episodeId") or episode_id or ""),
    )
    if context_scope == "project":
        return None
    for value in (
        result.get("episodeId"),
        (result.get("saveResult") if isinstance(result.get("saveResult"), dict) else {}).get("episodeId"),
        (result.get("projectEffect") if isinstance(result.get("projectEffect"), dict) else {}).get("episodeId"),
        episode_id,
        session.get("episodeId"),
    ):
        text = str(value or "").strip()
        if text and text not in {"__project__", "project"}:
            return text
    return None


def _agent_maybe_append_completion_next_step(
    project_id: str,
    episode_id: str | None,
    session: dict[str, Any],
    result: dict[str, Any],
) -> None:
    if not bool(result.get("success", True)):
        return
    if not bool(result.get("projectChanged")):
        return
    model_meta = result.get("agentModelMeta") if isinstance(result.get("agentModelMeta"), dict) else {}
    hypothesis = model_meta.get("taskHypothesis") if isinstance(model_meta.get("taskHypothesis"), dict) else {}
    # Direct program routes can finish a verified task without a model hypothesis.
    task_type = str(result.get("completedTaskType") or hypothesis.get("taskType") or "").strip()
    if task_type in {
        "", "free_chat", "project_status", "quality_review", "work_chain_plan_discuss",
        "asset_query", "media_file_request", "overview_request", "asset_image_generation",
        "storyboard_image_generation", "visual_handoff_image_generation",
        "storyboard_video_generation", "generation_request",
    }:
        return
    if _agent_result_background_started(result):
        return
    if result.get("cancelled") or str(result.get("sessionStatus") or "").strip() in {"error", "interrupted"}:
        return
    if _normalize_agent_pending_question(result.get("pendingQuestion")):
        return
    if "pendingOperation" in result and _normalize_agent_pending_operation(result.get("pendingOperation")):
        return
    message = str(result.get("message") or "").strip()
    if not message:
        return
    try:
        next_state = _agent_followup_progress_state(project_id, episode_id, session, result)
        recommendation_block = _agent_next_step_recommendations_block(
            next_state, origin="task_completion",
        )
        recommendation_footer = _agent_next_step_action_footer(next_state)
    except Exception:
        print(traceback.format_exc(), flush=True)
        return
    if not recommendation_block:
        return
    result["nextStepRecommendation"] = {
        "episodeId": next_state.get("selectedEpisodeId"),
        "stage": next_state.get("stage"),
        "text": _agent_action_footer_text(recommendation_footer).strip(),
        "actionFooter": recommendation_footer,
        "step": _agent_recommended_next_step(next_state),
        "items": copy.deepcopy(recommendation_block["items"]),
    }
    blocks = copy.deepcopy(result.get("contentBlocks") if isinstance(result.get("contentBlocks"), list) else [])
    blocks = [block for block in blocks if not (isinstance(block, dict) and block.get("type") == "recommendations")]
    blocks.append(recommendation_block)
    result["contentBlocks"] = blocks


def _agent_decision_requires_answer(data: dict[str, Any]) -> bool:
    keys = (
        "requiresAnswer",
        "requires_answer",
        "needsUserAnswer",
        "needs_user_answer",
        "mustAskUser",
        "must_ask_user",
    )
    for key in keys:
        if key not in data:
            continue
        raw = data.get(key)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "y"}
    pending = data.get("pendingQuestion") or data.get("pending_question")
    if isinstance(pending, dict):
        for key in keys:
            if key not in pending:
                continue
            raw = pending.get(key)
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                return raw.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _agent_sanitize_pending_question(value: Any) -> dict[str, Any] | None:
    normalized = _normalize_agent_pending_question(value)
    if not normalized:
        return None
    questions: list[dict[str, Any]] = []
    for question in normalized.get("questions") or []:
        if not isinstance(question, dict):
            continue
        options: list[dict[str, Any]] = []
        for option in question.get("options") or []:
            if not isinstance(option, dict):
                continue
            value_text = str(option.get("value") or option.get("label") or "").strip()
            label_text = str(option.get("label") or value_text).strip()
            if not label_text:
                continue
            row = {
                "value": value_text or label_text,
                "label": label_text,
                "description": str(option.get("description") or "").strip(),
            }
            options.append(row)
        if not options:
            continue
        questions.append(
            {
                "header": question.get("header"),
                "question": str(question.get("question") or "").strip(),
                "multiSelect": bool(question.get("multiSelect")),
                "options": options[:5],
            }
        )
    if not questions:
        return None
    question_id = str(
        normalized.get("question_id")
        or normalized.get("questionId")
        or f"aq_{uuid.uuid4().hex[:10]}"
    )
    return {"question_id": question_id, "questionId": question_id, "questions": questions}


def _agent_pending_question_from_decision(data: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    if not _agent_decision_requires_answer(data):
        return None
    raw_pending = _agent_sanitize_pending_question(data.get("pendingQuestion") or data.get("pending_question"))
    if raw_pending:
        return raw_pending
    return None


def _agent_decision_content_blocks(project_id: str, data: dict[str, Any], reply: str) -> list[dict[str, Any]]:
    raw_blocks = (
        data.get("contentBlocks")
        or data.get("content_blocks")
        or data.get("content")
        or data.get("messageBlocks")
        or data.get("message_blocks")
    )
    blocks = _normalize_agent_content_blocks(raw_blocks, project_id, hydrate=False)
    attachment_blocks = _agent_blocks_from_attachment_fields(project_id, data)
    if blocks:
        if reply and not _agent_blocks_have_body_text(blocks):
            blocks = [{"type": "text", "text": reply}, *blocks]
        blocks.extend(attachment_blocks)
        return blocks
    if attachment_blocks:
        if reply:
            return [{"type": "text", "text": reply}, *attachment_blocks]
        return attachment_blocks
    if reply:
        return [{"type": "text", "text": reply}]
    return []


_AGENT_USER_FACING_TOOL_LABELS = {
    "get_asset_range_context": "读取资产范围规划资料",
    "submit_asset_range_candidate": "校验并暂存资产范围候选",
    "get_asset_extraction_context": "读取资产拆分资料",
    "submit_asset_extraction_result": "校验并提交资产拆分结果",
    "submit_episode_boundary_candidate": "校验并暂存分集候选",
    "save_episode_work_chain_plan": "生成片段剧本和工作链",
    "get_source_coverage": "读取拆分进度",
    "get_episode_boundary_context": "读取下一集规划资料",
    "read_source_window": "读取原文片段",
}


def _agent_sanitize_user_facing_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    replacements: list[tuple[str, str]] = []
    for tool_name, label in _AGENT_USER_FACING_TOOL_LABELS.items():
        escaped = tool_name.replace("_", r"\_")
        mcp_name = f"mcp__ai_video__{tool_name}"
        mcp_escaped = mcp_name.replace("_", r"\_")
        for variant in (mcp_escaped, mcp_name, escaped, tool_name):
            replacements.append((f"`{variant}`", label))
            replacements.append((variant, label))
    for needle, label in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(needle, label)
    text = re.sub(r"\brecommendedAction\b", "建议动作", text)
    text = re.sub(r"\brecommendedPayload\b", "建议参数", text)
    text = re.sub(r"\bnextAllowedTools\b", "下一步可执行事项", text)
    return text


def _agent_sanitize_user_facing_content_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        item = copy.deepcopy(block)
        if str(item.get("type") or "text") == "text" and "text" in item:
            item["text"] = _agent_sanitize_user_facing_text(item.get("text"))
        sanitized.append(item)
    return sanitized


def _agent_normalize_turn_decision(
    project_id: str,
    data: dict[str, Any],
    state: dict[str, Any],
    model_meta: dict[str, Any],
) -> dict[str, Any]:
    reply = str(data.get("reply") or data.get("message") or data.get("assistant") or "").strip()
    raw_action = str(data.get("action") or data.get("tool") or "none").strip()
    if raw_action in {"", "none", "null", "chat", "answer", "respond"}:
        action = "none"
    elif raw_action in _agent_allowed_actions():
        action = raw_action
    else:
        action = "none"
    should_execute_raw = (
        data.get("shouldExecute")
        if "shouldExecute" in data
        else data.get("should_execute")
        if "should_execute" in data
        else data.get("execute")
    )
    should_execute = bool(should_execute_raw) if should_execute_raw is not None else action != "none"
    if action == "none":
        should_execute = False
    if not reply:
        if should_execute:
            reply = f"我理解你的指令，准备执行：{_agent_action_label(action, state)}。"
        else:
            reply = _agent_progress_message(state)
    pending_question = _agent_pending_question_from_decision(data, state)
    reply = _agent_sanitize_user_facing_text(reply)
    content_blocks = _agent_sanitize_user_facing_content_blocks(
        _agent_decision_content_blocks(project_id, data, reply)
    )
    return {
        "source": "model",
        "reply": reply,
        "contentBlocks": content_blocks,
        "action": action,
        "shouldExecute": should_execute,
        "pendingQuestion": pending_question,
        "modelMeta": model_meta,
    }


def _agent_controller_decision_from_result(
    result: dict[str, Any],
    model_meta: dict[str, Any],
) -> dict[str, Any]:
    worker_run = result.get("workerRun") if isinstance(result.get("workerRun"), dict) else {}
    if worker_run:
        model_meta["workerRun"] = worker_run
    content_blocks = (
        result.get("contentBlocks")
        if isinstance(result.get("contentBlocks"), list)
        else [{"type": "text", "text": str(result.get("message") or "")}]
    )
    reply = _agent_sanitize_user_facing_text(result.get("message"))
    return {
        "source": "local_system",
        "success": bool(result.get("success", True)),
        "reply": reply,
        "contentBlocks": _agent_sanitize_user_facing_content_blocks(content_blocks),
        "action": "none",
        "shouldExecute": False,
        "pendingQuestion": None,
        "modelMeta": model_meta,
        "projectChanged": bool(result.get("projectChanged")),
        "projectEffect": result.get("projectEffect") if isinstance(result.get("projectEffect"), dict) else None,
        "toolResult": str(result.get("toolResult") or result.get("message") or ""),
        "workerRun": worker_run,
        "tasks": result.get("tasks") if isinstance(result.get("tasks"), list) else ([result.get("task")] if isinstance(result.get("task"), dict) else []),
        "pendingOperation": result.get("pendingOperation") if "pendingOperation" in result else None,
        "backgroundStarted": bool(result.get("backgroundStarted")),
        "suppressSessionMessage": bool(result.get("suppressSessionMessage") or result.get("suppress_session_message")),
    }


def _agent_turn_result_from_worker_decision(
    project_id: str,
    progress_episode_id: str | None,
    decision: dict[str, Any],
    *,
    fallback_state: dict[str, Any],
    fallback_message: str,
) -> dict[str, Any]:
    success = bool(decision.get("success", True))
    next_state = _agent_progress_state(project_id, progress_episode_id)
    result = {
        "success": success,
        "message": str(decision.get("reply") or "").strip() or _agent_progress_message(next_state, fallback_message),
        "contentBlocks": decision.get("contentBlocks") or [],
        "steps": _agent_steps_from_state(next_state),
        "pendingQuestion": decision.get("pendingQuestion"),
        "project": next_state.get("project") or fallback_state.get("project"),
        "agentModelMeta": decision.get("modelMeta") or {},
        "sessionStatus": "idle" if success else "error",
    }
    if "pendingOperation" in decision:
        result["pendingOperation"] = decision.get("pendingOperation")
    if decision.get("projectChanged"):
        result["projectChanged"] = True
    if decision.get("completedTaskType"):
        result["completedTaskType"] = str(decision["completedTaskType"])
    if isinstance(decision.get("projectEffect"), dict):
        result["projectEffect"] = decision.get("projectEffect")
    if decision.get("toolResult"):
        result["toolResult"] = decision.get("toolResult")
    if isinstance(decision.get("workerRun"), dict):
        result["workerRun"] = decision.get("workerRun")
    if isinstance(decision.get("tasks"), list):
        result["tasks"] = [item for item in decision.get("tasks") if isinstance(item, dict)]
    if decision.get("backgroundStarted"):
        result["backgroundStarted"] = True
    if decision.get("suppressSessionMessage"):
        result["suppressSessionMessage"] = True
    return result


def _agent_session_policy_rejection(
    state: dict[str, Any],
    reason: str | Exception,
    *,
    task_type: str = "project_status",
    route_source: str = "session_policy_rejected",
) -> dict[str, Any]:
    reply = str(reason or "").strip() or "当前会话没有权限执行该操作。"
    return {
        "success": True,
        "status": "rejected",
        "backgroundStarted": False,
        "message": reply,
        "contentBlocks": [{"type": "text", "text": reply}],
        "steps": _agent_steps_from_state(state),
        "pendingQuestion": None,
        "project": state["project"],
        "agentModelMeta": {
            "source": "local-controller",
            "taskHypothesis": {
                "taskType": task_type,
                "routeSource": route_source,
            },
        },
        "sessionStatus": "idle",
    }




def _agent_session_task_policy_rejection(
    state: dict[str, Any],
    task_type: str | None,
    session_policy: dict[str, Any] | None,
    *,
    route_source: str = "session_task_policy_rejected",
) -> dict[str, Any] | None:
    normalized_task_type = str(task_type or "").strip()
    if not normalized_task_type:
        return None
    try:
        validate_agent_session_task_type(normalized_task_type, session_policy)
    except ValueError as exc:
        return _agent_session_policy_rejection(
            state,
            exc,
            task_type=normalized_task_type,
            route_source=route_source,
        )
    return None


def _agent_episode_session_project_delete_rejection(
    state: dict[str, Any],
    *,
    task_type: str = "project_cleanup",
) -> dict[str, Any]:
    reply = "当前集会话只能操作当前集画布，不能执行项目级删除或清空资产拆分。请切换到项目会话处理项目级删除。"
    return _agent_session_policy_rejection(
        state,
        reply,
        task_type=task_type,
        route_source="episode_scope_project_delete_rejected",
    )
