# -*- coding: utf-8 -*-
"""生产动作控制器与回合中的剧本、导演稿和媒体生成路由。"""
from __future__ import annotations

import traceback as traceback
from .runtime_state import (
    AgentTurnCancelled,
)
from .agent_progress_recommendations import (
    _agent_control_preferred_production_task_result,
)
from .agent_result_presentation import (
    _agent_session_task_policy_rejection,
    _agent_turn_result_from_worker_decision,
    _agent_controller_decision_from_result,
)
from .agent_sessions import (
    append_agent_execution_error,
)

from .agent_action_contract import (
    _agent_validate_action,
)
from .agent_contracts import (
    _agent_steps_from_state,
)
from .agent_scope_hints import (
    _agent_message_requests_episode_detail,
)
from .agent_pending_operations import (
    _agent_message_continues_flow,
)
from .agent_production_scope import (
    _agent_current_flow_storyboard_card_node_id,
    _agent_current_flow_prompt_storyboard_node_id,
    _agent_current_flow_workflow_node_id,
    _agent_flow_step_instruction,
)
from .agent_progress_recommendations import (
    _agent_production_actions,
    _agent_progress_content_blocks,
    _agent_progress_message,
    _agent_progress_state,
    _agent_progress_status_block_steps,
    _agent_workflow_explainer,
)
from .runtime_state import (
    _raise_if_agent_cancelled,
)
from .project_overview import analyze_project_overview

from typing import Any


def _execute_agent_action(
    project_id: str,
    episode_id: str | None,
    action: str,
    *,
    message: str = "",
    images: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action = _agent_validate_action(action)
    if not isinstance(state, dict):
        state = _agent_progress_state(
            project_id,
            episode_id,
            detail_mode=bool(str(episode_id or "").strip()) or _agent_message_requests_episode_detail(message),
        )
    selected_episode_id = str(state.get("selectedEpisodeId") or episode_id or "E01")
    _raise_if_agent_cancelled(session_id)
    if action == "show_progress":
        message_text = _agent_progress_message(state, message)
        return {
            "success": True,
            "message": message_text,
            "contentBlocks": _agent_progress_content_blocks(state, message),
            "steps": _agent_progress_status_block_steps(state),
            "pendingQuestion": None,
            "project": state["project"],
        }
    if action == "explain_workflow":
        return {
            "success": True,
            "message": _agent_workflow_explainer(state),
            "steps": _agent_steps_from_state(state),
            "pendingQuestion": None,
            "project": state["project"],
        }
    if action == "analyze_overview":
        _raise_if_agent_cancelled(session_id)
        result = analyze_project_overview(project_id, session_id=session_id)
        _raise_if_agent_cancelled(session_id)
        next_state = _agent_progress_state(project_id, selected_episode_id)
        return {
            "success": True,
            "message": (
                f"{result.get('overview') or '项目概述已生成。'}\n\n"
                "下一步可以继续拆分资产；完成资产覆盖后再规划并提交分集原文。当前集分集原文完成后，项目主流程继续规划下一集。"
            ),
            "steps": _agent_steps_from_state(next_state),
            "pendingQuestion": None,
            "tasks": [result.get("task")] if isinstance(result.get("task"), dict) else [],
            "project": next_state["project"],
            "projectChanged": True,
        }
    return {
        "success": True,
        "message": _agent_progress_message(state, message),
        "steps": _agent_steps_from_state(state),
        "pendingQuestion": None,
        "project": state["project"],
    }


def _agent_direct_production_task_hypothesis(
    task_type: str,
    state: dict[str, Any],
    routing_message: str,
) -> dict[str, Any]:
    is_flow_step = bool(
        str(state.get("stage") or "").strip() == "production"
        and task_type
        and any(action.get("taskType") == task_type for action in _agent_production_actions(state))
    ) or bool(_agent_message_continues_flow(routing_message))
    hypothesis: dict[str, Any] = {
        "taskType": task_type,
        "routeSource": "production_single_step_confirmation" if is_flow_step else "preferred_task",
        "flowStepOnly": is_flow_step,
    }
    if is_flow_step:
        hypothesis.update(
            {
                "singleStepOnly": True,
                "executionMode": "flow_step",
                "hardPrerequisitePolicy": "current_production_step",
            }
        )
    return hypothesis


def _agent_generation_controller_started_result(
    result: dict[str, Any],
    *,
    selected_episode_id: str,
    node_id: str,
    default_message: str,
    action: str,
) -> dict[str, Any]:
    task = result.get("task") if isinstance(result.get("task"), dict) else {}
    task_message = str(task.get("message") or result.get("message") or "").strip()
    message = task_message or default_message
    return {
        "success": bool(result.get("success", True)),
        "message": message,
        "contentBlocks": [{"type": "text", "text": message}],
        "projectChanged": False,
        "projectEffect": {
            "projectChanged": False,
            "changedResources": [],
            "focusTarget": {"section": "episode", "episodeId": selected_episode_id, "nodeId": node_id},
            "notice": message,
            "action": action,
            "nodeId": node_id,
        },
        "toolResult": message,
        "task": task,
        "tasks": [task] if task else [],
        "pendingOperation": None,
        "backgroundStarted": bool(result.get("backgroundStarted")),
        "suppressSessionMessage": bool(result.get("backgroundStarted")),
    }






def _run_workflow_storyboard_image_generation_controller(
    project_id: str,
    episode_id: str | None,
    *,
    state: dict[str, Any],
    parent_session_id: str | None,
    user_message: str,
    active_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_episode_id = str(episode_id or state.get("selectedEpisodeId") or "E01").strip() or "E01"
    node_id = _agent_current_flow_workflow_node_id(
        project_id,
        selected_episode_id,
        state,
        "storyboard.image",
        active_target=active_target,
        task_type="storyboard_image",
    )
    if not node_id:
        raise ValueError("当前工作链没有找到可生成分镜图的分镜图卡。")
    storyboard_instruction = _agent_flow_step_instruction(
        user_message,
        "根据当前工作链的分镜脚本生成分镜图，完成后停止。",
    )
    from .storyboard_task_execution import run_storyboard_generation_task

    result = run_storyboard_generation_task(
        "storyboard_image",
        project_id,
        selected_episode_id,
        node_id,
        "image",
        user_instruction=storyboard_instruction,
        session_id=parent_session_id,
    )
    return _agent_generation_controller_started_result(
        result,
        selected_episode_id=selected_episode_id,
        node_id=node_id,
        default_message="已开始生成当前工作链的分镜图。",
        action="storyboard_image_generation_started",
    )


def _run_workflow_visual_handoff_image_generation_controller(
    project_id: str,
    episode_id: str | None,
    *,
    state: dict[str, Any],
    parent_session_id: str | None,
    user_message: str,
    active_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_episode_id = str(episode_id or state.get("selectedEpisodeId") or "E01").strip() or "E01"
    node_id = _agent_current_flow_storyboard_card_node_id(
        project_id,
        selected_episode_id,
        state,
        active_target=active_target,
    )
    if not node_id:
        raise ValueError("当前工作链没有找到可生成视觉交接图的分镜单元。")
    handoff_instruction = _agent_flow_step_instruction(
        user_message,
        "根据当前工作链的分镜脚本和分镜图生成视觉交接图，完成后停止。",
    )
    from .storyboard_task_execution import run_storyboard_generation_task

    result = run_storyboard_generation_task(
        "visual_handoff_image",
        project_id,
        selected_episode_id,
        node_id,
        "image",
        user_instruction=handoff_instruction,
        session_id=parent_session_id,
    )
    return _agent_generation_controller_started_result(
        result,
        selected_episode_id=selected_episode_id,
        node_id=node_id,
        default_message="已开始生成当前工作链的视觉交接图。",
        action="visual_handoff_image_generation_started",
    )




def _run_workflow_storyboard_video_generation_controller(
    project_id: str,
    episode_id: str | None,
    *,
    state: dict[str, Any],
    parent_session_id: str | None,
    user_message: str,
    active_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_episode_id = str(episode_id or state.get("selectedEpisodeId") or "E01").strip() or "E01"
    node_id = _agent_current_flow_workflow_node_id(
        project_id,
        selected_episode_id,
        state,
        "video.storyboard",
        active_target=active_target,
        task_type="storyboard_video",
    )
    if not node_id:
        raise ValueError("当前工作链没有找到可生成视频的视频生成。")
    video_instruction = _agent_flow_step_instruction(
        user_message,
        "根据当前工作链的分镜图生成视频，完成后停止。",
    )
    from .storyboard_task_execution import run_storyboard_generation_task

    result = run_storyboard_generation_task(
        "storyboard_video",
        project_id,
        selected_episode_id,
        node_id,
        "video",
        user_instruction=video_instruction,
        session_id=parent_session_id,
    )
    return _agent_generation_controller_started_result(
        result,
        selected_episode_id=selected_episode_id,
        node_id=node_id,
        default_message="已开始生成当前工作链的视频。",
        action="storyboard_video_generation_started",
    )












def _resolve_direct_media_generation_turn(
    project_id: str,
    episode_id: str | None,
    message: str,
    session_id: str | None,
    active_target: dict[str, Any] | None,
    session_policy: dict[str, Any] | None,
    routing_message: str,
    progress_episode_id: str | None,
    state: dict[str, Any],
    selected_preferred_task_type: str,
    direct_generation_task_type: str,
) -> dict[str, Any] | None:
    task_rejection = _agent_session_task_policy_rejection(
        state,
        direct_generation_task_type,
        session_policy,
        route_source=f"{direct_generation_task_type}_session_policy_rejected",
    )
    if task_rejection:
        return task_rejection
    try:
        if direct_generation_task_type == "storyboard_image_generation":
            controller_result = _run_workflow_storyboard_image_generation_controller(
                project_id,
                progress_episode_id,
                state=state,
                parent_session_id=session_id,
                user_message=message,
                active_target=active_target,
            )
        elif direct_generation_task_type == "visual_handoff_image_generation":
            controller_result = _run_workflow_visual_handoff_image_generation_controller(
                project_id,
                progress_episode_id,
                state=state,
                parent_session_id=session_id,
                user_message=message,
                active_target=active_target,
            )
        else:
            controller_result = _run_workflow_storyboard_video_generation_controller(
                project_id,
                progress_episode_id,
                state=state,
                parent_session_id=session_id,
                user_message=message,
                active_target=active_target,
            )
        decision = _agent_controller_decision_from_result(
            controller_result,
            {
                "source": "local-controller",
                "taskHypothesis": _agent_direct_production_task_hypothesis(
                    direct_generation_task_type,
                    state,
                    routing_message,
                ),
            },
        )
    except AgentTurnCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        append_agent_execution_error(
            project_id,
            stage=f"{direct_generation_task_type}_controller",
            message="工作链生成任务 controller 失败",
            episode_id=episode_id,
            session_id=session_id,
            category="agent_controller_error",
            source="agent_controller",
            error=exc,
            details={"message": message, "preferredTaskType": selected_preferred_task_type},
            include_traceback=True,
        )
        print(traceback.format_exc(), flush=True)
        failure_label = {
            "storyboard_image_generation": "分镜图生成",
            "visual_handoff_image_generation": "视觉交接图生成",
            "storyboard_video_generation": "视频生成",
        }.get(direct_generation_task_type, "生成任务")
        decision = _agent_controller_decision_from_result(
            {
                "success": False,
                "message": f"{failure_label}没有启动成功：{exc}",
                "pendingOperation": None,
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




def _resolve_production_turn(
    project_id: str,
    episode_id: str | None,
    message: str,
    session_id: str | None,
    active_target: dict[str, Any] | None,
    session_policy: dict[str, Any] | None,
    control_only: bool,
    routing_message: str,
    progress_episode_id: str | None,
    state: dict[str, Any],
    selected_preferred_task_type: str,
    pending_requires_semantic_probe: bool,
) -> dict[str, Any] | None:
    if selected_preferred_task_type and (control_only or (active_target or {}).get("source") == "agent_recommendation"):
        preferred_task_status_result = _agent_control_preferred_production_task_result(
            state,
            selected_preferred_task_type,
            active_target,
        )
        if preferred_task_status_result:
            return preferred_task_status_result
    direct_generation_task_type = ""
    if not pending_requires_semantic_probe:
        if selected_preferred_task_type in {
            "storyboard_image_generation",
            "visual_handoff_image_generation",
            "storyboard_video_generation",
        }:
            direct_generation_task_type = selected_preferred_task_type
    if direct_generation_task_type:
        return _resolve_direct_media_generation_turn(
            project_id=project_id,
            episode_id=episode_id,
            message=message,
            session_id=session_id,
            active_target=active_target,
            session_policy=session_policy,
            routing_message=routing_message,
            progress_episode_id=progress_episode_id,
            state=state,
            selected_preferred_task_type=selected_preferred_task_type,
            direct_generation_task_type=direct_generation_task_type,
        )
