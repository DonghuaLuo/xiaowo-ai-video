# -*- coding: utf-8 -*-
"""任务结果、画布变更与生产状态事件的构建和发送。"""
from __future__ import annotations

from .agent_session_results import append_agent_generation_task_session_report
from .agent_sessions import append_agent_execution_error
from .production_status import update_episode_production_status
from .store_core import _emit_agent_event
from .task_canvas_sync import _CANVAS_MUTATION_EVENT_FIELD_ALIASES
from .task_canvas_sync import _task_canvas_changed_resources
from .task_canvas_sync import _task_canvas_mutation_sources
from .task_contract import _FAILED_NOTIFICATION_TASK_STATUSES
from .task_contract import _SUCCESS_NOTIFICATION_TASK_STATUSES
from .task_contract import _task_agent_session_id
from .task_control import _get_task
from typing import Any
import copy
import threading
import time
import traceback


def _maybe_report_agent_bound_generation_task(
    task: dict[str, Any] | None,
    *,
    success: bool | None = None,
) -> None:
    if not isinstance(task, dict):
        return
    if not _task_agent_session_id(task):
        return
    status = str(task.get("status") or "").strip()
    if success is None:
        if status in _SUCCESS_NOTIFICATION_TASK_STATUSES:
            success = True
        elif status in _FAILED_NOTIFICATION_TASK_STATUSES or status in {"cancelled", "canceled"}:
            success = False
        else:
            return
    try:
        append_agent_generation_task_session_report(
            str(task.get("projectId") or task.get("project_id") or ""),
            str(task.get("episodeId") or task.get("episode_id") or "") or None,
            task,
            success=bool(success),
        )
    except Exception as exc:  # noqa: BLE001
        try:
            append_agent_execution_error(
                str(task.get("projectId") or task.get("project_id") or ""),
                stage="agent_generation_task_session_report",
                message="生成任务完成后回写智能体会话失败",
                episode_id=str(task.get("episodeId") or task.get("episode_id") or "") or None,
                session_id=_task_agent_session_id(task),
                category="agent_session_report_error",
                source="background_generation_task",
                error=exc,
                details={"taskId": task.get("id"), "taskType": task.get("type")},
                include_traceback=True,
            )
        except Exception:
            print(traceback.format_exc(), flush=True)
        print(traceback.format_exc(), flush=True)


def _emit_storyboard_video_task_project_changed(task: dict[str, Any], action: str) -> None:
    if not isinstance(task, dict):
        return
    project_id = str(task.get("projectId") or "")
    episode_id = str(task.get("episodeId") or "")
    if not project_id or not episode_id:
        return
    job = task.get("videoJob") if isinstance(task.get("videoJob"), dict) else {}
    task_node_id = str(task.get("nodeId") or job.get("taskNodeId") or "").strip()
    result_node_id = str(task.get("resultNodeId") or job.get("resultNodeId") or "").strip()
    version_node_id = str(task.get("versionNodeId") or job.get("versionNodeId") or result_node_id or task_node_id).strip()
    _emit_agent_event(
        "project_changed",
        {
            "action": action,
            "projectId": project_id,
            "episodeId": episode_id,
            "nodeId": version_node_id,
            "taskNodeId": task_node_id,
            "resultNodeId": result_node_id or version_node_id,
            "versionId": task.get("versionId") or job.get("versionId") or "",
            **_task_canvas_mutation_event_fields(task),
            "changedResources": _task_canvas_changed_resources(
                task,
                fallback=["canvas_task", "canvas_version"],
            ),
        },
    )


def _task_canvas_mutation_event_fields(*sources: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for row in _task_canvas_mutation_sources(*sources):
        for output_key, aliases in _CANVAS_MUTATION_EVENT_FIELD_ALIASES:
            value = next((row.get(key) for key in aliases if row.get(key) is not None), None)
            if value is not None:
                fields[output_key] = copy.deepcopy(value)
    return fields


def _episode_production_status_event_effect(
    project_id: str | None,
    episode_id: str | None,
) -> dict[str, Any]:
    normalized_project_id = str(project_id or "").strip()
    normalized_episode_id = str(episode_id or "").strip()
    if not normalized_project_id or not normalized_episode_id:
        return {}
    try:
        status_result = update_episode_production_status(
            normalized_project_id,
            normalized_episode_id,
        )
    except Exception:
        print(traceback.format_exc(), flush=True)
        return {
            "projectChanged": True,
            "action": "episode_production_status_refresh_failed",
            "changedResources": [],
            "productionStatusRefreshFailed": True,
            "message": "生产状态刷新失败，请重新检查画布状态。",
        }
    if not isinstance(status_result, dict):
        return {}
    production_status = (
        status_result.get("status")
        if isinstance(status_result.get("status"), dict)
        else None
    )
    effect: dict[str, Any] = {
        "projectChanged": True,
        "action": "episode_production_status_updated",
        "changedResources": _task_canvas_changed_resources(
            status_result,
            fallback=["episode_production_status"],
        ),
    }
    if production_status:
        effect["productionStatus"] = copy.deepcopy(production_status)
    for key in (
        "workflowVersion",
        "txId",
        "seq",
        "revision",
        "baseRevision",
        "opType",
        "records",
        "documentExtras",
        "state",
    ):
        if status_result.get(key) is not None:
            effect[key] = copy.deepcopy(status_result.get(key))
    if production_status and "documentExtras" not in effect:
        effect["documentExtras"] = {"productionStatus": copy.deepcopy(production_status)}
    return effect


def _attach_production_status_event_effect(
    payload: dict[str, Any],
    production_status_effect: dict[str, Any] | None,
) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or not isinstance(production_status_effect, dict)
        or not production_status_effect
    ):
        return payload
    production_status = production_status_effect.get("productionStatus")
    if isinstance(production_status, dict):
        payload["productionStatus"] = copy.deepcopy(production_status)
    payload["projectEffect"] = copy.deepcopy(production_status_effect)
    payload["changedResources"] = _task_canvas_changed_resources(
        payload,
        production_status_effect,
        fallback=[],
    )
    return payload


def _workflow_with_result_nodes(workflow: dict[str, Any], *sources: Any) -> dict[str, Any]:
    if not isinstance(workflow, dict):
        return {}
    replacement_nodes: dict[str, dict[str, Any]] = {}
    workflow_version: Any = None
    seen_sources: set[int] = set()

    def collect_node(value: Any) -> None:
        if not isinstance(value, dict):
            return
        node_id = str(value.get("id") or value.get("nodeId") or value.get("node_id") or "").strip()
        if not node_id:
            return
        if "type" not in value and "position" not in value and not isinstance(value.get("data"), dict):
            return
        replacement_nodes[node_id] = value

    def collect_source(source: Any) -> None:
        nonlocal workflow_version
        if not isinstance(source, dict):
            return
        identity = id(source)
        if identity in seen_sources:
            return
        seen_sources.add(identity)
        if source.get("workflowVersion") is not None:
            workflow_version = source.get("workflowVersion")
        collect_node(source)
        collect_node(source.get("node"))
        nodes = source.get("nodes")
        if isinstance(nodes, list):
            for node in nodes:
                collect_node(node)
        for nested_key in ("result", "projectEffect", "version"):
            collect_source(source.get(nested_key))

    for source in sources:
        collect_source(source)
    if not replacement_nodes and workflow_version is None:
        return workflow

    next_workflow = copy.deepcopy(workflow)
    if workflow_version is not None:
        next_workflow["version"] = copy.deepcopy(workflow_version)
    nodes = next_workflow.get("nodes")
    if not isinstance(nodes, list):
        nodes = []
        next_workflow["nodes"] = nodes
    node_indexes = {
        str(node.get("id") or "").strip(): index
        for index, node in enumerate(nodes)
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }
    for node_id, node in replacement_nodes.items():
        node_copy = copy.deepcopy(node)
        node_copy["id"] = node_id
        if node_id in node_indexes:
            index = node_indexes[node_id]
            current_node = nodes[index] if isinstance(nodes[index], dict) else {}
            merged_node = copy.deepcopy(current_node)
            for key, value in node_copy.items():
                if (
                    key == "data"
                    and isinstance(value, dict)
                    and isinstance(merged_node.get("data"), dict)
                ):
                    merged_node["data"] = {
                        **copy.deepcopy(merged_node.get("data") or {}),
                        **copy.deepcopy(value),
                    }
                else:
                    merged_node[key] = copy.deepcopy(value)
            merged_node["id"] = node_id
            nodes[index] = merged_node
        else:
            node_indexes[node_id] = len(nodes)
            nodes.append(node_copy)
    return next_workflow


def _workflow_canvas_mutation_payload(
    workflow: dict[str, Any],
    *node_ids: str | None,
) -> dict[str, Any]:
    if not isinstance(workflow, dict):
        return {}
    related_node_ids = {
        str(node_id or "").strip()
        for node_id in node_ids
        if str(node_id or "").strip()
    }
    if not related_node_ids:
        return {}
    workflow_edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    related_edges: list[dict[str, Any]] = []
    for edge in workflow_edges:
        if not isinstance(edge, dict):
            continue
        source_id = str(edge.get("source") or "").strip()
        target_id = str(edge.get("target") or "").strip()
        if source_id in related_node_ids or target_id in related_node_ids:
            related_edges.append(copy.deepcopy(edge))
            if source_id:
                related_node_ids.add(source_id)
            if target_id:
                related_node_ids.add(target_id)
    workflow_nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    related_nodes = [
        copy.deepcopy(node)
        for node in workflow_nodes
        if isinstance(node, dict)
        and str(node.get("id") or "").strip() in related_node_ids
    ]
    payload: dict[str, Any] = {
        "workflowVersion": workflow.get("version"),
        "changedResources": ["canvas_node", "canvas_edge", "visual_handoff"],
    }
    if related_nodes:
        payload["nodes"] = related_nodes
    if related_edges:
        payload["edges"] = related_edges
    return payload


def _generation_task_event_payload(
    task: dict[str, Any],
    version: dict[str, Any] | None,
    *,
    node_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(version, dict):
        return task
    event_task = copy.deepcopy(task)
    event_task.setdefault("version", copy.deepcopy(version))
    version_id = str(version.get("id") or event_task.get("versionId") or "").strip()
    if version_id:
        event_task.setdefault("versionId", version_id)
    task_node_id = str(
        event_task.get("taskNodeId")
        or event_task.get("generationTaskNodeId")
        or event_task.get("nodeId")
        or ""
    ).strip()
    version_node_id = str(
        event_task.get("versionNodeId")
        or event_task.get("outputNodeId")
        or version.get("nodeId")
        or node_id
        or task_node_id
        or ""
    ).strip()
    result_node_id = str(
        event_task.get("resultNodeId")
        or version_node_id
        or node_id
        or task_node_id
        or ""
    ).strip()
    result = copy.deepcopy(event_task.get("result")) if isinstance(event_task.get("result"), dict) else {}
    if version_node_id:
        result.setdefault("nodeId", version_node_id)
    if task_node_id:
        result.setdefault("taskNodeId", task_node_id)
    if result_node_id:
        result.setdefault("resultNodeId", result_node_id)
    if version_id:
        result.setdefault("versionId", version_id)
    result.setdefault("version", copy.deepcopy(version))
    if isinstance(version.get("media"), dict):
        result.setdefault("media", copy.deepcopy(version.get("media")))
    mutation_fields = _task_canvas_mutation_event_fields(event_task, result, version)
    if mutation_fields:
        result.update(copy.deepcopy(mutation_fields))
        event_task.update(copy.deepcopy(mutation_fields))
    changed_resources = _task_canvas_changed_resources(event_task, result, version)
    if changed_resources:
        result["changedResources"] = copy.deepcopy(changed_resources)
        event_task["changedResources"] = copy.deepcopy(changed_resources)
    event_task["result"] = result
    return event_task


def _emit_visual_handoff_cross_episode_project_changed(
    version: dict[str, Any] | None,
    *,
    project_id: str | None,
    episode_id: str | None,
    node_id: str | None,
) -> None:
    if not isinstance(version, dict):
        return
    cross_link = version.get("crossEpisodeLink") if isinstance(version.get("crossEpisodeLink"), dict) else {}
    if not cross_link or not (cross_link.get("linked") or cross_link.get("updated")):
        return
    target_episode_id = str(cross_link.get("episodeId") or "").strip()
    source_episode_id = str(episode_id or "").strip()
    if not target_episode_id or target_episode_id == source_episode_id:
        return
    linked = bool(cross_link.get("linked"))
    _emit_agent_event(
        "project_changed",
        {
            "action": "visual_handoff_cross_episode_linked"
            if linked
            else "visual_handoff_cross_episode_imported",
            "projectId": project_id or "",
            "episodeId": target_episode_id,
            "sourceEpisodeId": source_episode_id,
            "sourceNodeId": cross_link.get("sourceNodeId") or node_id or "",
            "nodeId": cross_link.get("targetNodeId") or cross_link.get("mediaNodeId") or "",
            "mediaNodeId": cross_link.get("mediaNodeId") or "",
            "versionId": str(version.get("id") or ""),
            "workflowVersion": cross_link.get("workflowVersion"),
            **_task_canvas_mutation_event_fields(cross_link),
            "changedResources": _task_canvas_changed_resources(
                cross_link,
                fallback=(
                    ["canvas_node", "canvas_edge", "visual_handoff"]
                    if linked
                    else ["canvas_node", "visual_handoff"]
                ),
            ),
        },
    )


def _emit_generation_task_result(
    result: dict[str, Any],
    *,
    project_id: str | None = None,
    episode_id: str | None = None,
    node_id: str | None = None,
    project_action: str = "workflow_node_generated",
    emit_created: bool = True,
    production_status_effect: dict[str, Any] | None = None,
) -> None:
    task = result.get("task") if isinstance(result, dict) else None
    version = result.get("version") if isinstance(result.get("version"), dict) else None
    if isinstance(task, dict):
        task = _generation_task_event_payload(task, version, node_id=node_id)
        if emit_created:
            _emit_agent_event("task_created", task)
            _emit_agent_event("task_progress", task)
        status = str(task.get("status") or "")
        if status in _FAILED_NOTIFICATION_TASK_STATUSES:
            _emit_agent_event("task_failed", task)
        elif status in {"cancelled", "canceled"}:
            _emit_agent_event("task_cancelled", task)
        elif status in _SUCCESS_NOTIFICATION_TASK_STATUSES:
            _emit_agent_event("task_completed", task)
        else:
            _emit_agent_event("task_progress", task)
    task_payload = task if isinstance(task, dict) else {}
    task_result = task_payload.get("result") if isinstance(task_payload.get("result"), dict) else {}
    mutation_fields = _task_canvas_mutation_event_fields(task_payload, task_result, version, result)
    changed_resources = _task_canvas_changed_resources(
        task_payload,
        task_result,
        version,
        result,
        production_status_effect,
        fallback=[
            "canvas_task",
            *(["canvas_node", "canvas_version"] if isinstance(version, dict) else []),
        ],
    )
    project_event: dict[str, Any] = {
        "action": project_action,
        "projectId": project_id or "",
        "episodeId": episode_id or "",
        "nodeId": node_id or "",
        **mutation_fields,
        "changedResources": changed_resources,
    }
    for key in (
        "node",
        "nodes",
        "edge",
        "edges",
        "route",
        "routes",
        "workChains",
        "work_chains",
        "tasks",
        "version",
        "versions",
        "editHistory",
        "edit_history",
        "editHistoryItems",
        "edit_history_items",
        "editHistoryWarning",
        "edit_history_warning",
    ):
        if task_result.get(key) is not None:
            project_event[key] = copy.deepcopy(task_result.get(key))
    if task_payload.get("id") is not None:
        project_event["taskId"] = task_payload.get("id")
    for key in ("taskNodeId", "resultNodeId", "versionNodeId", "versionId", "focusTarget"):
        if task_payload.get(key) is not None:
            project_event[key] = copy.deepcopy(task_payload.get(key))
    _attach_production_status_event_effect(project_event, production_status_effect)
    _emit_agent_event(
        "project_changed",
        project_event,
    )
    _emit_visual_handoff_cross_episode_project_changed(
        version,
        project_id=project_id,
        episode_id=episode_id,
        node_id=node_id,
    )
    if task_payload:
        status = str(task_payload.get("status") or "").strip()
        if status in _SUCCESS_NOTIFICATION_TASK_STATUSES:
            _maybe_report_agent_bound_generation_task(task_payload, success=True)
        elif status in _FAILED_NOTIFICATION_TASK_STATUSES or status in {"cancelled", "canceled"}:
            _maybe_report_agent_bound_generation_task(task_payload, success=False)


def _emit_generation_task_result_async(
    result: dict[str, Any],
    *,
    project_id: str | None = None,
    episode_id: str | None = None,
    node_id: str | None = None,
    project_action: str = "workflow_node_generated",
    emit_created: bool = True,
    production_status_effect: dict[str, Any] | None = None,
    delay_seconds: float = 2.0,
) -> None:
    def emit_later() -> None:
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        current_result = result
        task = result.get("task") if isinstance(result, dict) else None
        task_id = str(task.get("id") or "").strip() if isinstance(task, dict) else ""
        if task_id:
            current_task = _get_task(task_id)
            if current_task:
                current_result = {**result, "task": current_task}
        _emit_generation_task_result(
            current_result,
            project_id=project_id,
            episode_id=episode_id,
            node_id=node_id,
            project_action=project_action,
            emit_created=emit_created,
            production_status_effect=production_status_effect,
        )

    thread = threading.Thread(
        target=emit_later,
        daemon=True,
        name="ai-video-generation-task-event",
    )
    thread.start()
