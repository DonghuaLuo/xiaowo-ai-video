# -*- coding: utf-8 -*-
"""视频任务创建、并发抢占、幂等复用和后台启动。"""
from __future__ import annotations
from utils.video_task_types import standalone_video_input_mode, standalone_video_strategy, standalone_video_required_slots

from datetime import datetime
from utils.agent_execution_state import current_execution_id, require_task_execution
from .canvas_store_queries import read_episode_card_results
from .perf_logging import canvas_perf_elapsed_ms
from .perf_logging import canvas_perf_log
from .perf_logging import canvas_perf_start
from .task_canvas_sync import _defer_canvas_task_record_sync
from .task_contract import _task_agent_session_fields
from .task_control import _ACTIVE_GLOBAL_TASK_STATUSES
from .task_control import _assert_canvas_task_source_present
from .task_projection import _task_list_summary
from .task_request_identity import _assert_canvas_task_reusable_by_signature
from .task_request_identity import _canvas_task_idempotency_key
from .task_request_identity import _canvas_task_request_signature
from .task_request_identity import _storyboard_video_request_signature_payload
from .task_request_identity import _storyboard_video_request_signature_payload_overrides
from .task_storage import _TASK_STORAGE_LOCK
from .task_storage import _hydrate_task_runtime_fields
from .task_storage import _load_task_storage_bucket
from .task_storage import _load_tasks_for_project
from .task_storage import _normalized_task_status
from .task_storage import _save_task_storage_bucket
from .task_storage import _task_storage_key_for_project
from .task_workflow_context import _workflow_task_focus_target
from .video_task_execution import _ensure_storyboard_video_worker
from .video_task_requests import _apply_video_generation_request_metadata_overrides
from .video_task_requests import _storyboard_video_generation_start_context
from .video_task_requests import _video_task_card_prompt_from_node_data
from .workflow_contract import workflow_video_task_scope
from .runtime_state import _VIDEO_GENERATION_TASK_TYPES
from typing import Any
import copy
import uuid


def _storyboard_video_task_matches_target(
    task: dict[str, Any],
    project_id: str,
    episode_id: str,
    task_node_id: str,
    result_node_id: str,
    version_node_id: str,
) -> bool:
    if not isinstance(task, dict):
        return False
    if str(task.get("type") or "").strip() not in _VIDEO_GENERATION_TASK_TYPES:
        return False
    if str(task.get("projectId") or "") != str(project_id):
        return False
    if str(task.get("episodeId") or "") != str(episode_id):
        return False
    if _normalized_task_status(task) not in _ACTIVE_GLOBAL_TASK_STATUSES:
        return False
    job = task.get("videoJob") if isinstance(task.get("videoJob"), dict) else {}
    task_node_ids = {
        str(task.get("nodeId") or "").strip(),
        str(task.get("taskNodeId") or "").strip(),
        str(task.get("generationTaskNodeId") or "").strip(),
        str(job.get("taskNodeId") or "").strip(),
    } - {""}
    if str(task_node_id or "").strip() not in task_node_ids:
        return False
    target_result_ids = {
        str(result_node_id or "").strip(),
        str(version_node_id or "").strip(),
    } - {""}
    if not target_result_ids:
        return True
    task_result_ids = {
        str(task.get("resultNodeId") or "").strip(),
        str(task.get("outputNodeId") or "").strip(),
        str(task.get("versionNodeId") or "").strip(),
        str(job.get("resultNodeId") or "").strip(),
        str(job.get("versionNodeId") or "").strip(),
    } - {""}
    return not task_result_ids or bool(task_result_ids & target_result_ids)


def _active_storyboard_video_task_for_target_unlocked(
    project_id: str,
    episode_id: str,
    task_node_id: str,
    result_node_id: str,
    version_node_id: str,
) -> dict[str, Any] | None:
    for row in reversed(_load_tasks_for_project(project_id)):
        task = _hydrate_task_runtime_fields(row)
        if _storyboard_video_task_matches_target(
            task,
            project_id,
            episode_id,
            task_node_id,
            result_node_id,
            version_node_id,
        ):
            return copy.deepcopy(task)
    return None


def _storyboard_video_version_for_task(
    project_id: str,
    episode_id: str,
    task: dict[str, Any],
) -> dict[str, Any] | None:
    job = task.get("videoJob") if isinstance(task.get("videoJob"), dict) else {}
    version_id = str(task.get("versionId") or job.get("versionId") or "").strip()
    if not version_id:
        return None
    version_node_id = str(
        task.get("versionNodeId")
        or task.get("outputNodeId")
        or task.get("resultNodeId")
        or job.get("versionNodeId")
        or job.get("resultNodeId")
        or ""
    ).strip()
    for item in read_episode_card_results(project_id, episode_id):
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") != version_id:
            continue
        if version_node_id and str(item.get("nodeId") or "") != version_node_id:
            continue
        return copy.deepcopy(item)
    return None


def _storyboard_video_reused_generation_result(
    project_id: str,
    episode_id: str,
    task: dict[str, Any],
) -> dict[str, Any]:
    result = {
        "success": True,
        "task": _task_list_summary(task),
        "version": None,
        "backgroundStarted": True,
        "reused": True,
    }
    version = _storyboard_video_version_for_task(project_id, episode_id, task)
    if version:
        result["version"] = version
    return result


def _claim_storyboard_video_generation_task(
    project_id: str,
    episode_id: str,
    task_node_id: str,
    result_node_id: str,
    version_node_id: str,
    *,
    message: str,
    title: str,
    work_chain_fields: dict[str, Any],
    client_request_id: str | None = None,
    idempotency_key: str | None = None,
    request_signature: str | None = None,
    task_id: str | None = None,
    video_job: dict[str, Any] | None = None,
    focus_target: dict[str, Any] | None = None,
    session_fields: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    storage_key = _task_storage_key_for_project(project_id)
    normalized_session_fields = (
        copy.deepcopy(session_fields) if isinstance(session_fields, dict) else {}
    )
    requested_session_id = str(normalized_session_fields.get("sessionId") or "").strip()
    identity = current_execution_id(requested_session_id)
    with _TASK_STORAGE_LOCK:
        _assert_canvas_task_source_present(project_id, episode_id, task_node_id)
        tasks = _load_task_storage_bucket(storage_key)
        for index in range(len(tasks) - 1, -1, -1):
            row = tasks[index]
            candidate = _hydrate_task_runtime_fields(row)
            if _storyboard_video_task_matches_target(
                candidate,
                project_id,
                episode_id,
                task_node_id,
                result_node_id,
                version_node_id,
            ):
                _assert_canvas_task_reusable_by_signature(candidate, request_signature)
                if requested_session_id:
                    require_task_execution(candidate, requested_session_id, identity)
                task = copy.deepcopy(candidate)
                reused = True
                break
        else:
            reused = False
            now_ms = int(datetime.now().timestamp() * 1000)
            normalized_task_id = str(task_id or "").strip() or f"task-{uuid.uuid4().hex[:10]}"
            task: dict[str, Any] = {
                "id": normalized_task_id,
                "type": "storyboard_video",
                "projectId": project_id or "",
                "episodeId": episode_id,
                "nodeId": task_node_id,
                "status": "running",
                "progress": 5,
                "message": message or "视频正在生成。",
                "createdAt": now_ms,
                "startedAt": now_ms,
                "focusTarget": copy.deepcopy(focus_target)
                if isinstance(focus_target, dict)
                else _workflow_task_focus_target(episode_id, version_node_id or task_node_id),
            }
            normalized_client_request_id = str(client_request_id or "").strip()
            normalized_idempotency_key = str(idempotency_key or "").strip()
            normalized_request_signature = str(request_signature or "").strip()
            if normalized_client_request_id:
                task["clientRequestId"] = normalized_client_request_id
            if normalized_idempotency_key:
                task["idempotencyKey"] = normalized_idempotency_key
            if normalized_request_signature:
                task["requestSignature"] = normalized_request_signature
            update_fields: dict[str, Any] = {
                "generationTaskNodeId": task_node_id,
                "taskNodeId": task_node_id,
                "resultNodeId": result_node_id,
                "outputNodeId": version_node_id,
                "versionNodeId": version_node_id,
                "nodeTitle": title,
                "title": title,
                **work_chain_fields,
            }
            task.update(update_fields)
            if normalized_session_fields:
                task.update(normalized_session_fields)
            if identity:
                task["executionId"] = identity
            if isinstance(video_job, dict):
                stored_job = copy.deepcopy(video_job)
                if normalized_request_signature:
                    stored_job["requestSignature"] = normalized_request_signature
                    job_payload = stored_job.get("payload") if isinstance(stored_job.get("payload"), dict) else {}
                    if isinstance(job_payload, dict):
                        job_payload["requestSignature"] = normalized_request_signature
                task["videoJob"] = stored_job
            tasks.append(task)
            _save_task_storage_bucket(storage_key, tasks)
    from .agent_sessions import _bind_agent_execution_task
    if not reused or requested_session_id:
        _bind_agent_execution_task(project_id, task)
    if reused:
        return task, True
    task = _defer_canvas_task_record_sync(task, changed_resources=["canvas_task"]) or task
    return task, False


def start_storyboard_video_generation(
    project_id: str,
    episode_id: str,
    node_id: str,
    *,
    user_instruction: str = "",
    requested_node_id: str | None = None,
    generation_config: dict[str, Any] | None = None,
    generation_config_provided: bool = False,
    payload_overrides: dict[str, Any] | None = None,
    client_request_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    perf_started_at = canvas_perf_start()
    start_context = _storyboard_video_generation_start_context(
        project_id,
        episode_id,
        node_id,
        payload_overrides=payload_overrides,
        generation_config=generation_config,
        generation_config_provided=generation_config_provided,
    )
    selected_node_id = str(start_context.get("selectedNodeId") or "")
    video_result_node_id = str(start_context.get("resultNodeId") or "")
    version_node_id = str(start_context.get("versionNodeId") or selected_node_id)
    title = str(start_context.get("title") or "故事版视频")
    task_title = str(start_context.get("taskTitle") or title)
    result_title = str(start_context.get("resultTitle") or "")
    version_title = str(start_context.get("versionTitle") or result_title or task_title or title)
    work_chain_fields = (
        copy.deepcopy(start_context.get("workChainFields"))
        if isinstance(start_context.get("workChainFields"), dict)
        else {}
    )
    payload: dict[str, Any] = {
        "generationStage": "storyboard_video",
        "nodeId": selected_node_id,
        "taskNodeId": selected_node_id,
        "nodeType": str((start_context.get("node") or {}).get("type") or "video.storyboard"),
    }
    session_fields = _task_agent_session_fields(session_id)
    if video_result_node_id:
        payload["resultNodeId"] = video_result_node_id
        payload["versionNodeId"] = version_node_id
    for key in ("routeId", "routeLabel", "workChainId", "workChainLabel", "workChainTitle", "workChainName", "segmentId", "strategy"):
        if work_chain_fields.get(key):
            payload[key] = copy.deepcopy(work_chain_fields.get(key))
    if isinstance(payload_overrides, dict) and payload_overrides:
        _apply_video_generation_request_metadata_overrides(payload, payload_overrides)
    start_node_data = start_context.get("nodeData") if isinstance(start_context.get("nodeData"), dict) else {}
    start_workflow = start_context.get("workflow") if isinstance(start_context.get("workflow"), dict) else {}
    start_node = start_context.get("node") if isinstance(start_context.get("node"), dict) else {}
    video_task_scope = str(start_context.get("videoTaskScope") or "").strip() or (
        workflow_video_task_scope(start_workflow, start_node)
        if start_workflow and start_node
        else ""
    )
    if video_task_scope:
        payload["videoTaskScope"] = video_task_scope
    is_work_chain_video_task = (
        video_task_scope == "work_chain"
    )
    if video_task_scope == "standalone":
        payload["strategy"] = standalone_video_strategy(payload["nodeType"])
        payload["videoInputMode"] = standalone_video_input_mode(payload["nodeType"])
        payload["referenceMode"] = payload["videoInputMode"]
        payload["videoInputPlan"] = {
            "mode": payload["videoInputMode"],
            "referenceMode": payload["referenceMode"],
            "requiredSlots": standalone_video_required_slots(payload["nodeType"]),
        }
    if is_work_chain_video_task:
        if not _video_task_card_prompt_from_node_data(start_node_data):
            raise ValueError("工作链视频生成缺少视频提示词，请先点击“生成视频提示词”。")
    effective_user_instruction = "" if is_work_chain_video_task else str(user_instruction or "").strip()
    normalized_client_request_id = str(client_request_id or "").strip()
    idempotency_key = _canvas_task_idempotency_key(
        "storyboard_video",
        project_id,
        episode_id,
        selected_node_id,
        result_node_id=video_result_node_id,
        version_node_id=version_node_id,
    )
    if normalized_client_request_id:
        payload["clientRequestId"] = normalized_client_request_id
    payload["idempotencyKey"] = idempotency_key

    task_message = str(
        payload.get("taskMessage")
        or payload.get("task_message")
        or (
            f"{(result_title or task_title)}视频正在生成。"
            if (result_title or task_title) and "视频" not in (result_title or task_title)
            else f"{(result_title or task_title)}正在生成。"
            if (result_title or task_title)
            else "视频正在生成。"
        )
    ).strip()
    new_task_id = f"task-{uuid.uuid4().hex[:10]}"
    payload["taskId"] = new_task_id
    job = {
        "phase": "created",
        "title": version_title,
        "taskTitle": title,
        "resultTitle": result_title or version_title,
        "payload": payload,
        "taskNodeId": selected_node_id,
        "resultNodeId": video_result_node_id,
        "versionNodeId": version_node_id,
        "requestContextDeferred": True,
        "requestedNodeId": str(requested_node_id or node_id or "").strip(),
        "userInstruction": effective_user_instruction,
        "generationConfig": copy.deepcopy(generation_config) if isinstance(generation_config, dict) else {},
        "generationConfigProvided": bool(generation_config_provided),
        "payloadOverrides": copy.deepcopy(payload_overrides) if isinstance(payload_overrides, dict) else {},
    }
    signature_payload = _storyboard_video_request_signature_payload(
        payload,
        is_work_chain_video_task=is_work_chain_video_task,
    )
    signature_payload_overrides = _storyboard_video_request_signature_payload_overrides(
        payload_overrides,
        is_work_chain_video_task=is_work_chain_video_task,
    )
    request_signature = _canvas_task_request_signature(
        "storyboard_video",
        project_id,
        episode_id,
        selected_node_id,
        result_node_id=video_result_node_id,
        version_node_id=version_node_id,
        payload=signature_payload,
        workflow=start_context.get("workflow") if isinstance(start_context.get("workflow"), dict) else {},
        extra={
            "requestedNodeId": str(requested_node_id or node_id or "").strip(),
            "userInstruction": effective_user_instruction,
            "generationConfig": copy.deepcopy(generation_config) if isinstance(generation_config, dict) else {},
            "generationConfigProvided": bool(generation_config_provided),
            "payloadOverrides": signature_payload_overrides,
        },
    )
    payload["requestSignature"] = request_signature
    if session_fields:
        payload.update(copy.deepcopy(session_fields))
    job["requestSignature"] = request_signature
    if session_fields:
        job.update(copy.deepcopy(session_fields))
    task, reused = _claim_storyboard_video_generation_task(
        project_id,
        episode_id,
        selected_node_id,
        video_result_node_id,
        version_node_id,
        message=task_message,
        title=result_title or task_title,
        work_chain_fields=work_chain_fields,
        client_request_id=normalized_client_request_id,
        idempotency_key=idempotency_key,
        request_signature=request_signature,
        task_id=new_task_id,
        video_job=job,
        focus_target=_workflow_task_focus_target(episode_id, version_node_id),
        session_fields=session_fields,
    )
    if reused:
        canvas_perf_log(
            "start_storyboard_video_generation",
            taskId=str(task.get("id") or ""),
            projectId=project_id,
            episodeId=episode_id,
            requestedNodeId=node_id,
            selectedNodeId=selected_node_id,
            resultNodeId=video_result_node_id,
            versionNodeId=version_node_id,
            reused=True,
            durationMs=canvas_perf_elapsed_ms(perf_started_at),
            versionId=str(task.get("versionId") or ""),
        )
        return _storyboard_video_reused_generation_result(project_id, episode_id, task)
    _ensure_storyboard_video_worker(task["id"])
    canvas_perf_log(
        "start_storyboard_video_generation",
        taskId=str(task.get("id") or ""),
        projectId=project_id,
        episodeId=episode_id,
        requestedNodeId=node_id,
        selectedNodeId=selected_node_id,
        resultNodeId=video_result_node_id,
        versionNodeId=version_node_id,
        reused=False,
        durationMs=canvas_perf_elapsed_ms(perf_started_at),
        versionDeferred=True,
    )
    return {"success": True, "task": _task_list_summary(task), "version": None, "backgroundStarted": True}
