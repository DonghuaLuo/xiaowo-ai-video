# -*- coding: utf-8 -*-
"""分镜、导演、视频提示词和交接图任务的入队及执行。"""
from __future__ import annotations

from datetime import datetime
from .perf_logging import canvas_perf_elapsed_ms
from .perf_logging import canvas_perf_log
from .perf_logging import canvas_perf_start
from .store_core import _display_time
from .store_core import _emit_agent_event
from .store_core import _now
from .task_canvas_sync import _sync_canvas_task_record
from .task_contract import _task_agent_session_fields
from utils.agent_execution_state import current_execution_id, require_task_execution
from .task_contract import _task_failure_fields
from .task_control import _begin_task_result_commit
from .task_control import _emit_task_update
from .task_control import _get_task
from .task_control import _update_task_if_active
from .task_control import create_task
from .task_events import _emit_generation_task_result
from .task_events import _emit_generation_task_result_async
from .task_events import _episode_production_status_event_effect
from .task_events import _workflow_canvas_mutation_payload
from .task_events import _workflow_with_result_nodes
from .task_lifecycle import _BACKGROUND_STORYBOARD_TASK_THREADS
from .task_lifecycle import _background_storyboard_task_allows_finish
from .task_request_identity import _active_canvas_task_for_intent_unlocked
from .task_request_identity import _canvas_task_idempotency_key
from .task_request_identity import _canvas_task_request_signature
from .task_storage import _TASK_STORAGE_LOCK
from .task_workflow_context import _assert_generation_closure_ready
from .task_workflow_context import _assert_storyboard_image_has_required_director_context
from .task_workflow_context import _canvas_task_context_workflow
from .task_workflow_context import _generation_output_running_message
from .task_workflow_context import _generation_success_notice
from .task_workflow_context import _visual_handoff_canvas_payload_from_ensure_result
from .task_workflow_context import _visual_handoff_prompt_node_id_for_request
from .task_workflow_context import _workflow_generation_output_title
from .task_workflow_context import _workflow_node_meaningful_title
from .task_workflow_context import _workflow_task_focus_target
from .task_workflow_context import _workflow_task_work_chain_fields
from .video_task_submission import start_storyboard_video_generation
from .workflow_contract import _workflow_node
from .workflow_media_generation import build_storyboard_generation_metadata
from .workflow_input_resolution import resolve_generation_task_node_id
from .workflow_storyboard_versions import add_storyboard_version
from .workflow_visual_handoff import ensure_visual_handoff_result_node
from .workflow_variant_quality import auto_review_variant_quality
from typing import Any
import copy
import threading
import traceback


def _run_background_storyboard_generation_task(
    task_id: str,
    normalized_task_type: str,
    project_id: str,
    episode_id: str,
    selected_node_id: str,
    requested_node_id: str,
    normalized_version_type: str,
    instruction: str,
    *,
    emit_events: bool,
    session_id: str | None = None,
    generation_config: dict[str, Any] | None = None,
    generation_config_provided: bool = False,
) -> None:
    message_by_type = {
        "storyboard_image": "分镜图已生成成功。",
        "visual_handoff_image": "视觉交接图已生成成功。",
        "storyboard_video": "视频已生成成功。",
        "workflow": "工作流节点已完成。",
    }
    failure_prefix_by_type = {
        "storyboard_image": "分镜图生成失败",
        "visual_handoff_image": "视觉交接图生成失败",
        "storyboard_video": "视频生成失败",
        "workflow": "工作流节点运行失败",
    }
    metadata = None
    task_status = "completed"
    task_progress = 100
    version = None
    generation_error = ""
    quality_review_target: dict[str, str] = {}
    task = _get_task(task_id)
    session_fields = _task_agent_session_fields(session_id)
    if not isinstance(task, dict) or not _background_storyboard_task_allows_finish(task_id):
        return
    if emit_events and isinstance(task, dict):
        _emit_agent_event("task_created", task)
        _emit_agent_event("task_progress", task)
    workflow: dict[str, Any] = {}
    creation_canvas_payload: dict[str, Any] = {}
    try:
        if normalized_task_type == "visual_handoff_image":
            visual_request_node_id = str(requested_node_id or selected_node_id or "").strip()
            visual_start_workflow = (
                _canvas_task_context_workflow(project_id, episode_id, visual_request_node_id, detail="summary")
                if project_id and episode_id and visual_request_node_id
                else {}
            )
            prompt_node_id = _visual_handoff_prompt_node_id_for_request(
                visual_start_workflow,
                visual_request_node_id,
            )
            if not prompt_node_id and selected_node_id and selected_node_id != visual_request_node_id:
                prompt_node_id = _visual_handoff_prompt_node_id_for_request(
                    visual_start_workflow,
                    selected_node_id,
                )
            if not prompt_node_id:
                raise ValueError("请选择已分配的分镜单元生成视觉交接图")
            if not _background_storyboard_task_allows_finish(task_id):
                return
            ensure_result = ensure_visual_handoff_result_node(project_id, episode_id, prompt_node_id)
            ensure_data = ensure_result if isinstance(ensure_result, dict) else {}
            ensured_node_id = str(ensure_data.get("nodeId") or ensure_data.get("node_id") or "").strip()
            if ensured_node_id:
                selected_node_id = ensured_node_id
            ensured_canvas_payload = _visual_handoff_canvas_payload_from_ensure_result(ensure_result)
            if ensured_canvas_payload:
                creation_canvas_payload = ensured_canvas_payload
                task_result = copy.deepcopy(task.get("result")) if isinstance((task or {}).get("result"), dict) else {}
                task_result.update(copy.deepcopy(creation_canvas_payload))
                updated_task = _update_task_if_active(
                    task_id,
                    progress=10,
                    resultNodeId=selected_node_id,
                    outputNodeId=selected_node_id,
                    versionNodeId=selected_node_id,
                    focusTarget=_workflow_task_focus_target(episode_id, selected_node_id),
                    changedResources=copy.deepcopy(
                        creation_canvas_payload.get("changedResources")
                        or ["canvas_node", "canvas_edge", "visual_handoff"]
                    ),
                    result=task_result,
                    updatedAt=int(datetime.now().timestamp() * 1000),
                )
                if updated_task:
                    task = updated_task
                    if emit_events:
                        _emit_task_update(updated_task, "task_progress")
            if not _background_storyboard_task_allows_finish(task_id):
                return
        if not _background_storyboard_task_allows_finish(task_id):
            return
        workflow = (
            _canvas_task_context_workflow(project_id, episode_id, selected_node_id)
            if project_id and episode_id
            else {}
        )
        _assert_generation_closure_ready(
            project_id,
            episode_id,
            normalized_task_type,
            node_id=selected_node_id,
            workflow=workflow,
        )
        if not _background_storyboard_task_allows_finish(task_id):
            return
        revision_result: dict[str, Any] = {}

        if normalized_version_type:
            metadata = build_storyboard_generation_metadata(
                project_id,
                episode_id,
                selected_node_id,
                normalized_version_type,
                normalized_task_type,
                user_instruction=instruction,
                revision_result=revision_result,
                requested_node_id=requested_node_id,
                generation_config_override=generation_config,
                generation_config_provided=generation_config_provided,
                task_id=task_id,
            )
            if metadata.get("generationError"):
                generation_error = str(metadata.get("generationError") or "").strip()
                task_status = "failed"
                task_progress = 0
            elif metadata.get("status") == "processing":
                task_status = "running"
                task_progress = 60

        if not _background_storyboard_task_allows_finish(task_id):
            return

        if normalized_version_type and metadata:
            committing_task = _begin_task_result_commit(task_id, message="正在保存生成结果。")
            if not committing_task:
                return
            task = committing_task
            version = add_storyboard_version(
                project_id,
                episode_id,
                selected_node_id,
                normalized_version_type,
                {
                    **metadata,
                    "payload": {
                        **(metadata.get("payload") or {}),
                        "taskType": normalized_task_type,
                        "taskId": task_id,
                    },
                },
            )
            if str(version.get("status") or "").strip().lower() != "processing":
                quality_review_target = {
                    "nodeId": selected_node_id,
                    "versionId": str(version.get("id") or ""),
                }

        if not _background_storyboard_task_allows_finish(task_id):
            return

        now_ms = int(datetime.now().timestamp() * 1000)
        workflow_after_task = _workflow_with_result_nodes(
            workflow,
            creation_canvas_payload,
            version,
        )
        completion_canvas_payload: dict[str, Any] = {}
        if normalized_task_type == "visual_handoff_image":
            completion_canvas_payload = (
                copy.deepcopy(creation_canvas_payload)
                if creation_canvas_payload
                else _workflow_canvas_mutation_payload(
                    workflow_after_task,
                    selected_node_id,
                    requested_node_id,
                )
            )
        work_chain_fields = _workflow_task_work_chain_fields(
            workflow_after_task,
            selected_node_id,
        )
        completion_notice = ""
        if task_status == "completed":
            completion_notice = _generation_success_notice(workflow_after_task, selected_node_id, normalized_task_type)
        update_fields: dict[str, Any] = {
            "status": task_status,
            "progress": task_progress,
            "message": completion_notice or (metadata or {}).get("summary") or message_by_type.get(normalized_task_type),
            "updatedAt": now_ms,
            **session_fields,
            **work_chain_fields,
        }
        if completion_notice:
            update_fields["notice"] = completion_notice
            update_fields["completedAt"] = now_ms
        if task_status == "failed":
            failure_summary = str(update_fields.get("message") or "").strip()
            failure_reason = generation_error or failure_summary
            update_fields["failedAt"] = now_ms
            update_fields.update(
                _task_failure_fields(
                    failure_reason,
                    prefix=failure_prefix_by_type.get(normalized_task_type, "生成任务失败"),
                    provider_response=failure_reason,
                )
            )
        if completion_canvas_payload:
            update_fields["changedResources"] = copy.deepcopy(
                completion_canvas_payload.get("changedResources", ["canvas_node", "canvas_edge", "visual_handoff"])
            )
            update_fields["result"] = copy.deepcopy(completion_canvas_payload)
        if version:
            update_fields["versionId"] = version.get("id")
            update_fields["focusTarget"] = _workflow_task_focus_target(
                episode_id,
                selected_node_id,
                version_id=str(version.get("id") or ""),
            )
        task = _update_task_if_active(task_id, **update_fields)
        if not task:
            return
        production_status_effect: dict[str, Any] = {}
        if task_status == "completed":
            production_status_effect = _episode_production_status_event_effect(
                project_id,
                episode_id,
            )
        if emit_events:
            _emit_generation_task_result(
                {"success": True, "task": task, "version": version},
                project_id=project_id,
                episode_id=episode_id,
                node_id=selected_node_id,
                emit_created=False,
                production_status_effect=production_status_effect,
            )
        if quality_review_target:
            try:
                auto_review_variant_quality(project_id, episode_id, quality_review_target)
            except Exception:
                print(traceback.format_exc(), flush=True)
    except Exception as exc:
        traceback_text = traceback.format_exc()
        print(traceback_text, flush=True)
        if _background_storyboard_task_allows_finish(task_id):
            failure_message = str(exc) or exc.__class__.__name__ or "生成任务执行失败。"
            version_id = str((version or {}).get("id") or "").strip() if isinstance(version, dict) else ""
            failed_fields = {
                "status": "failed",
                "progress": 0,
                "failedAt": _display_time(_now()),
                "updatedAt": int(datetime.now().timestamp() * 1000),
                "focusTarget": _workflow_task_focus_target(
                    episode_id,
                    selected_node_id,
                    version_id=version_id,
                ),
                **session_fields,
                **_workflow_task_work_chain_fields(workflow, selected_node_id),
                **_task_failure_fields(
                    failure_message,
                    prefix=failure_prefix_by_type.get(normalized_task_type, "生成任务失败"),
                    traceback_text=traceback_text,
                    provider_response=failure_message,
                ),
            }
            if version_id:
                failed_fields["versionId"] = version_id
            task = _update_task_if_active(task_id, **failed_fields)
            if task and emit_events:
                _emit_generation_task_result(
                    {"success": False, "task": task, "version": version},
                    project_id=project_id,
                    episode_id=episode_id,
                    node_id=selected_node_id,
                    emit_created=False,
                )
    finally:
        _BACKGROUND_STORYBOARD_TASK_THREADS.pop(task_id, None)


def run_storyboard_generation_task(
    task_type: str,
    project_id: str,
    episode_id: str,
    node_id: str | None = None,
    version_type: str | None = None,
    *,
    user_instruction: str = "",
    emit_events: bool = True,
    session_id: str | None = None,
    generation_config: dict[str, Any] | None = None,
    generation_config_provided: bool = False,
    payload_overrides: dict[str, Any] | None = None,
    client_request_id: str | None = None,
) -> dict[str, Any]:
    perf_started_at = canvas_perf_start()
    normalized_task_type = str(task_type or "").strip()
    if normalized_task_type not in {"storyboard_image", "visual_handoff_image", "storyboard_video", "storyboard_image_edit"}:
        raise ValueError("此任务应通过智能体会话执行")
    normalized_version_type = str(version_type or "").strip()
    requested_node_id = str(node_id or "").strip()
    instruction = str(user_instruction or "").strip()
    session_fields = _task_agent_session_fields(session_id)
    normalized_session_id = session_fields.get("sessionId", "")
    if not project_id or not episode_id or not requested_node_id:
        raise ValueError("生成任务缺少 projectId、episodeId 或 nodeId")
    if normalized_task_type == "storyboard_video" and normalized_version_type == "video":
        result = start_storyboard_video_generation(
            project_id,
            episode_id,
            requested_node_id,
            user_instruction=instruction,
            requested_node_id=requested_node_id,
            generation_config=generation_config,
            generation_config_provided=generation_config_provided,
            payload_overrides=payload_overrides,
            client_request_id=client_request_id,
            session_id=normalized_session_id or None,
        )
        result_task = result.get("task") if isinstance(result.get("task"), dict) else {}
        video_task_node_id = str(result_task.get("nodeId") or result_task.get("taskNodeId") or requested_node_id)
        if emit_events:
            _emit_generation_task_result_async(
                result,
                project_id=project_id,
                episode_id=episode_id,
                node_id=video_task_node_id,
                emit_created=not bool(result.get("reused")),
            )
        canvas_perf_log(
            "run_storyboard_generation_task",
            taskId=str(result_task.get("id") or ""),
            projectId=project_id,
            episodeId=episode_id,
            requestedNodeId=requested_node_id,
            selectedNodeId=video_task_node_id,
            taskType=normalized_task_type,
            versionType=normalized_version_type,
            routedTo="storyboard_video",
            reused=bool(result.get("reused")),
            durationMs=canvas_perf_elapsed_ms(perf_started_at),
        )
        return result

    workflow = (
        _canvas_task_context_workflow(project_id, episode_id, requested_node_id, detail="summary")
        if project_id and episode_id
        else {}
    )
    if normalized_task_type == "visual_handoff_image":
        if not project_id or not episode_id or not requested_node_id:
            raise ValueError("生成视觉交接图缺少 projectId、episodeId 或 nodeId")
        prompt_node_id = _visual_handoff_prompt_node_id_for_request(workflow, requested_node_id)
        if not prompt_node_id:
            raise ValueError("请选择已分配的分镜单元生成视觉交接图")
    selected_node_id = resolve_generation_task_node_id(workflow, normalized_task_type, node_id)
    if not project_id or not episode_id or not selected_node_id:
        raise ValueError("生成节点缺少 projectId、episodeId 或 nodeId，请先根据原文事实拆分结果生成片段剧本和分集画布工作流")
    selected_node = _workflow_node(workflow, selected_node_id)
    if not selected_node:
        raise FileNotFoundError(f"生成节点不存在：{selected_node_id}，请先重建或刷新分集画布工作流")
    if normalized_task_type == "storyboard_image":
        if str(selected_node.get("type") or "").strip() != "storyboard.image":
            raise ValueError("当前工作链缺少分镜图卡，无法生成分镜图")
        _assert_storyboard_image_has_required_director_context(
            workflow,
            selected_node_id,
            requested_node_id or selected_node_id,
        )
    running_message_by_type = {
        "storyboard_image": "正在生成故事版分镜图。",
        "visual_handoff_image": "正在生成视觉交接图。",
        "storyboard_video": "正在生成故事版视频。",
        "workflow": "正在运行工作流节点。",
    }
    execution_node_id = selected_node_id
    result_node_id = selected_node_id
    requested_node = _workflow_node(workflow, requested_node_id) if requested_node_id else None
    requested_type = str((requested_node or {}).get("type") or "").strip()
    if normalized_task_type in {"storyboard_image", "storyboard_image_edit", "visual_handoff_image"}:
        if requested_node and requested_type == "prompt.storyboard":
            execution_node_id = requested_node_id
            result_node_id = selected_node_id
    display_title = (
        _workflow_generation_output_title(
            workflow,
            result_node_id,
            normalized_task_type,
        )
        or _workflow_node_meaningful_title(workflow, execution_node_id)
    )
    running_message = running_message_by_type.get(normalized_task_type, "正在运行生成任务。")
    if normalized_task_type == "storyboard_image" and display_title:
        running_message = _generation_output_running_message(display_title, "分镜图")
    elif normalized_task_type == "visual_handoff_image" and display_title:
        running_message = _generation_output_running_message(display_title, "视觉交接图")
    elif normalized_task_type == "storyboard_image_edit" and display_title:
        running_message = f"{display_title}修改版正在生成。"
    elif normalized_task_type in {"storyboard_video", "route_video"} and display_title:
        running_message = _generation_output_running_message(display_title, "视频")
    work_chain_fields = _workflow_task_work_chain_fields(
        workflow,
        execution_node_id or result_node_id,
    )
    task_initial_fields = {
        "generationTaskNodeId": execution_node_id,
        "taskNodeId": execution_node_id,
        "resultNodeId": result_node_id,
        "outputNodeId": selected_node_id,
        "versionNodeId": selected_node_id,
        "nodeTitle": display_title,
        "title": display_title,
        **session_fields,
        **work_chain_fields,
        "focusTarget": _workflow_task_focus_target(episode_id, execution_node_id),
    }
    normalized_client_request_id = str(client_request_id or "").strip()
    idempotency_key = _canvas_task_idempotency_key(
        normalized_task_type,
        project_id,
        episode_id,
        execution_node_id,
        result_node_id=result_node_id,
        version_node_id=selected_node_id,
    )
    request_signature_extra = {
        "versionType": normalized_version_type,
        "requestedNodeId": requested_node_id,
        "selectedNodeId": selected_node_id,
        "userInstruction": instruction,
        "generationConfig": copy.deepcopy(generation_config) if isinstance(generation_config, dict) else {},
        "generationConfigProvided": bool(generation_config_provided),
    }
    request_signature = _canvas_task_request_signature(
        normalized_task_type,
        project_id,
        episode_id,
        execution_node_id,
        result_node_id=result_node_id,
        version_node_id=selected_node_id,
        workflow=workflow,
        extra=request_signature_extra,
    )
    with _TASK_STORAGE_LOCK:
        existing = _active_canvas_task_for_intent_unlocked(
            project_id,
            episode_id,
            normalized_task_type,
            execution_node_id,
            result_node_id=result_node_id,
            version_node_id=selected_node_id,
            idempotency_key=idempotency_key,
            request_signature=request_signature,
        )
        if existing:
            if normalized_session_id:
                require_task_execution(existing, normalized_session_id, current_execution_id(normalized_session_id))
            task = existing
        else:
            task = create_task(
                normalized_task_type,
                project_id=project_id,
                episode_id=episode_id,
                node_id=execution_node_id,
                message=running_message,
                status="running",
                progress=5,
                focus_target=_workflow_task_focus_target(episode_id, execution_node_id),
                client_request_id=normalized_client_request_id,
                idempotency_key=idempotency_key,
                request_signature=request_signature,
                sync_canvas_task_record=False,
                task_fields=task_initial_fields,
            )
    from .agent_sessions import _bind_agent_execution_task
    if not existing or normalized_session_id:
        _bind_agent_execution_task(project_id, task)
    if existing:
        canvas_perf_log(
            "run_storyboard_generation_task",
            taskId=str(existing.get("id") or ""),
            projectId=project_id,
            episodeId=episode_id,
            requestedNodeId=requested_node_id,
            selectedNodeId=selected_node_id,
            taskType=normalized_task_type,
            versionType=normalized_version_type,
            routedTo="background_storyboard",
            reused=True,
            durationMs=canvas_perf_elapsed_ms(perf_started_at),
        )
        return {"success": True, "task": existing, "version": None, "backgroundStarted": True, "reused": True}
    task = _sync_canvas_task_record(
        task,
        changed_resources=task.get("changedResources") if isinstance(task.get("changedResources"), list) else None,
    ) or task
    thread = threading.Thread(
        target=_run_background_storyboard_generation_task,
        args=(
            str(task.get("id") or ""),
            normalized_task_type,
            project_id,
            episode_id,
            selected_node_id,
            requested_node_id or selected_node_id,
            normalized_version_type,
            instruction,
        ),
        kwargs={
            "emit_events": emit_events,
            "session_id": normalized_session_id or None,
            "generation_config": copy.deepcopy(generation_config),
            "generation_config_provided": generation_config_provided,
        },
        daemon=True,
        name=f"ai-video-storyboard-generation-{task.get('id')}",
    )
    _BACKGROUND_STORYBOARD_TASK_THREADS[str(task.get("id") or "")] = thread
    thread.start()
    canvas_perf_log(
        "run_storyboard_generation_task",
        taskId=str(task.get("id") or ""),
        projectId=project_id,
        episodeId=episode_id,
        requestedNodeId=requested_node_id,
        selectedNodeId=selected_node_id,
        taskType=normalized_task_type,
        versionType=normalized_version_type,
        routedTo="background_storyboard",
        reused=False,
        durationMs=canvas_perf_elapsed_ms(perf_started_at),
    )
    return {"success": True, "task": task, "version": None, "backgroundStarted": True}
