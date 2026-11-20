"""Project an Agent's creative stage without writing its canvas document."""
from __future__ import annotations

import traceback
from datetime import datetime

from utils.agent_execution_state import current_execution_id
from .canvas_store_queries import read_canvas_card_record_v4
from .task_control import _emit_task_update, _get_task, _update_task_if_active
from .task_storage import _TASK_STORAGE_LOCK


_CANVAS_TOOL_STAGES = {
    "get_cinematic_script_context": ("prompt.storyboard", "workflow_cinematic_script"),
    "get_director_plan_context": ("director.board", "storyboard_plan"),
    "get_video_prompt_context": ("video.storyboard", "video_prompt"),
    "get_video_prompt_optimization_context": ("video.storyboard", "video_prompt"),
    "get_video_prompt_standalone_context": ("video.storyboard", "video_prompt"),
    "validate_director_plan_draft": ("director.board", "storyboard_plan"),
    "submit_director_plan_result": ("director.board", "storyboard_plan"),
    "submit_cinematic_script_result": ("prompt.storyboard", "workflow_cinematic_script"),
    "submit_video_prompt_result": ("video.storyboard", "video_prompt"),
    "submit_video_prompt_optimization_result": ("video.storyboard", "video_prompt"),
    "submit_video_prompt_standalone_result": ("video.storyboard", "video_prompt"),
}

_CREATIVE_CONTEXT_TASKS = {
    "get_cinematic_script_context": "workflow_cinematic_script_generation",
    "get_director_plan_context": "director_plan_generation",
    "get_video_prompt_context": "video_prompt_generation",
    "get_video_prompt_optimization_context": "video_prompt_optimization",
    "get_video_prompt_standalone_context": "video_prompt_standalone_generation",
}


def track_agent_canvas_stage(
    project_id: str, session_id: str, episode_id: str, node_id: str, tool_name: str,
    *, task_type: str = "", completed: bool = False,
) -> None:
    stage = _CANVAS_TOOL_STAGES.get(tool_name)
    if not stage or not episode_id or not node_id:
        return
    if tool_name in _CREATIVE_CONTEXT_TASKS and task_type != _CREATIVE_CONTEXT_TASKS[tool_name]:
        # A free-chat context read can be inspection, rather than generation.
        return
    execution_id = current_execution_id(session_id)
    if not execution_id:
        return
    try:
        node = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="summary")
        if node.get("type") != stage[0]:
            return
        data = node.get("data") or {}
        fields = {
            "generationTaskType": stage[1], "nodeId": node_id,
            "canvasStageStatus": "completed" if completed else "running",
            "routeId": node.get("routeId") or data.get("routeId") or "",
            "workChainId": node.get("workChainId") or data.get("workChainId") or "",
            "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id},
        }
        # Read-only tools can finish after a submission. Check the latest task
        # and update under the storage lock so readback cannot restart its stage.
        with _TASK_STORAGE_LOCK:
            task = _get_task(execution_id)
            if (not task or task.get("type") != "agent_turn"
                    or task.get("projectId") != project_id
                    or task.get("episodeId") != episode_id
                    or task.get("sessionId") != session_id):
                return
            if (not completed and not tool_name.startswith("submit_")
                    and task.get("nodeId") == node_id
                    and task.get("generationTaskType") == stage[1]
                    and task.get("canvasStageStatus") == "completed"):
                return
            if all(task.get(key) == value for key, value in fields.items()):
                return
            updated = _update_task_if_active(
                execution_id, syncCanvasTaskRecord=False,
                updatedAt=max(int(datetime.now().timestamp() * 1000), int(task.get("updatedAt") or 0) + 1),
                **fields,
            )
        if updated:
            # This event projects task metadata, not a new canvas mutation. A
            # parent's earlier commit envelope must not make it look stale.
            _emit_task_update({key: value for key, value in updated.items() if key not in {
                "workflowVersion", "revision", "baseRevision", "txId", "seq",
                "opType", "records", "changedResources",
            }})
    except Exception:
        # Progress projection cannot fail an otherwise valid creative tool call.
        print(traceback.format_exc(), flush=True)
