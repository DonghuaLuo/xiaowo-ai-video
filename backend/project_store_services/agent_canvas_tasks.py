"""Isolated canvas tasks sharing one visible canvas assistant panel."""
from __future__ import annotations

import copy
import traceback
import threading
from typing import Any

from .agent_runtime import run_agent_message
from .agent_sessions import (
    _agent_session_detail, _agent_session_summaries, _agent_snapshot_from_session,
    _ensure_agent_session, _load_agent_sessions, _save_agent_sessions,
)
from .canvas_store_queries import get_canvas_context_v4, read_canvas_card_locator_v4, read_workflow_card_neighborhood_v4
from .runtime_state import _AGENT_BACKEND_INSTANCE_ID, _LOCK


CANVAS_TASKS = {
    "workflow_cinematic_script_generation": ("生成剧本", "canvas_generate_cinematic_script", {"prompt.storyboard"}),
    "director_plan_generation": ("生成分镜脚本", "canvas_generate_director_plan", {"director.board"}),
    "video_prompt_generation": ("生成视频提示词", "canvas_generate_video_prompt", {"video.storyboard"}),
    "video_prompt_standalone_generation": ("生成视频提示词", "canvas_generate_video_prompt", {"video.storyboard", "video.keyframe"}),
    "video_prompt_optimization": ("优化视频提示词", "canvas_optimize_video_prompt", {"video.storyboard", "video.keyframe"}),
}
_START_LOCK = threading.Lock()


def _open(session: dict[str, Any]) -> bool:
    if session.get("status") in {"error", "interrupted"}:
        return False
    return (session.get("status") == "running"
            or bool((session.get("canvasTask") or {}).get("starting") and session.get("status") == "idle")
            or (not session.get("canvasTask") and bool(session.get("pendingQuestion") or session.get("pendingOperation"))))


def _existing_result(project_id: str, episode_id: str, session: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "reused": True, "sessionId": session["id"],
            "session": _agent_session_detail(project_id, session),
            "snapshot": _agent_snapshot_from_session(project_id, session),
            "sessions": _agent_session_summaries(project_id, episode_id)}


def start_canvas_agent_task(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _START_LOCK:
        return _start_canvas_agent_task(project_id, episode_id, payload)


def _start_canvas_agent_task(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    task_type = str(payload.get("taskType") or "")
    if task_type not in CANVAS_TASKS:
        raise ValueError("不支持的画布智能体任务")
    label, quick_prompt, node_types = CANVAS_TASKS[task_type]
    node_id = str(payload.get("nodeId") or "").strip()
    request_key = str(payload.get("requestKey") or "").strip()
    if not project_id or not episode_id or not node_id or not request_key:
        raise ValueError("缺少画布任务定位信息")
    canvas = get_canvas_context_v4(project_id, episode_id)
    canvas_kind = canvas.get("canvasKind")
    if canvas_kind != payload.get("canvasKind") or canvas_kind not in {"work_chain", "custom"}:
        raise ValueError("画布已变化，请重新发起任务")
    if canvas_kind == "custom" and task_type not in {"video_prompt_standalone_generation", "video_prompt_optimization"}:
        raise ValueError("当前自定义画布不支持此任务")

    # Scheduling is atomic. The start lock covers acceptance, never the model loop.
    # Other starts see the persisted running child before they check conflicts.
    with _LOCK:
        sessions = _load_agent_sessions(project_id)
        parent_id = str(payload.get("parentSessionId") or "")
        parent = next((row for row in sessions if row["id"] == parent_id), None)
        if parent and parent.get("canvasTask"):
            parent_id = parent["canvasTask"]["parentSessionId"]
            parent = next((row for row in sessions if row["id"] == parent_id), None)
        if not parent or parent.get("episodeId") != episode_id or parent.get("canvasTask"):
            raise ValueError("画布会话已变化，请重新打开智能体面板")

        workflow = read_workflow_card_neighborhood_v4(project_id, episode_id, node_id, detail="full")
        node = next((row for row in workflow.get("nodes", []) if row.get("id") == node_id), None)
        if not node or node.get("type") not in node_types:
            raise ValueError("目标卡片已变化，请重新选择")
        chain_id = str(node.get("workChainId") or "")
        route_id = str(node.get("routeId") or "")
        if any(payload.get(key) and str(payload[key]) != value
               for key, value in (("workChainId", chain_id), ("routeId", route_id))):
            raise ValueError("目标卡片所属工作链已变化，请重新发起任务")
        target = {"source": "storyboard_canvas", "intent": "generate", "section": "episode",
                  "episodeId": episode_id, "canvasKind": canvas_kind,
                  "nodeId": node_id, "nodeType": node["type"],
                  "workChainId": chain_id, "routeId": route_id}
        if canvas_kind == "custom":
            target.update({"canvasId": payload.get("canvasId"), "canvasTitle": payload.get("canvasTitle")})

        for other in sessions:
            if other.get("episodeId") != episode_id:
                continue
            metadata = other.get("canvasTask") or {}
            if metadata.get("requestKey") == request_key:
                if (metadata.get("parentSessionId") != parent_id or metadata.get("taskType") != task_type
                        or (metadata.get("target") or {}).get("nodeId") != node_id):
                    raise ValueError("此请求已用于其他画布任务，请重新发起")
                return _existing_result(project_id, episode_id, other)
            if not _open(other):
                continue
            other_target = metadata.get("target") or other.get("recentTaskTarget") or {}
            if other_target.get("nodeId") == node_id:
                if metadata.get("taskType") == task_type and metadata.get("parentSessionId") == parent_id:
                    return _existing_result(project_id, episode_id, other)
                return {"success": False, "blockingSessionId": other["id"],
                        "message": "此卡片已有任务正在执行，请先完成或停止该任务"}
            # Script/director writes invalidate downstream inputs/allocation.
            # Separate video cards on a stable chain remain independent.
            if (chain_id and other_target.get("workChainId") == chain_id
                    and {task_type, metadata.get("taskType") or other.get("runningTaskType")} & {
                        "workflow_cinematic_script_generation", "director_plan_generation"}):
                return {"success": False, "blockingSessionId": other["id"],
                        "message": "此工作链的剧本或分镜正在更新，请完成后再生成相关内容"}

        locator = read_canvas_card_locator_v4(project_id, episode_id, node)
        title = f"{locator}{'' if '/镜头' in locator else '.'}{label}" if locator else label
        child, sessions = _ensure_agent_session(project_id, None, episode_id, title)
        child.update({"scope": "episode", "contextScope": "episode",
                      "workflowId": f"episode:{episode_id}:workflow",
                      "canvasTask": {"parentSessionId": parent_id, "taskType": task_type,
                                     "requestKey": request_key, "target": target, "starting": True,
                                     "startingInstanceId": _AGENT_BACKEND_INSTANCE_ID}})
        _save_agent_sessions(project_id, sessions)
    try:
        result = run_agent_message(
            project_id, episode_id, message=label, display_message=label,
            session_id=child["id"], preferred_task_type=task_type,
            quick_prompt_id=quick_prompt, control_only=True, scope="episode",
            workflow_id=child["workflowId"], active_target=copy.deepcopy(target),
            task_options=payload.get("taskOptions"),
        )
        with _LOCK:
            current = _load_agent_sessions(project_id)
            accepted = next((row for row in current if row["id"] == child["id"]), None)
            if accepted:
                accepted["canvasTask"]["starting"] = False
                accepted["canvasTask"].pop("startingInstanceId", None)
                _save_agent_sessions(project_id, current)
                result.update(session=_agent_session_detail(project_id, accepted),
                              sessions=_agent_session_summaries(project_id, episode_id),
                              snapshot=_agent_snapshot_from_session(project_id, accepted))
        return result
    except Exception as exc:
        print(traceback.format_exc(), flush=True)
        # Keep the failed launch reviewable, without leaving an idle ghost.
        with _LOCK:
            current = _load_agent_sessions(project_id)
            failed = next((row for row in current if row["id"] == child["id"]), None)
            if failed:
                if failed.get("status") != "running":
                    failed["status"] = "error"
                failed["canvasTask"]["starting"] = False
                failed["canvasTask"].pop("startingInstanceId", None)
                from .agent_sessions import _agent_message_row, _apply_agent_message_retention
                messages = failed.get("messages") or []
                if not any(row.get("role") == "assistant" for row in messages):
                    reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "任务启动失败"
                    _apply_agent_message_retention(failed, [*messages, _agent_message_row(
                        "assistant", f"{title}失败：{reason}", project_id=project_id,
                    )])
                _save_agent_sessions(project_id, current)
        raise
