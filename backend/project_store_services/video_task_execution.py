# -*- coding: utf-8 -*-
"""视频请求准备、供应商提交、后台轮询与最终结果提交。"""
from __future__ import annotations

from .runtime_state import _LOCK
from datetime import datetime
from .model_request_logs import STAGE_FINAL_VIDEO_GENERATION_REQUEST
from .model_request_logs import model_request_log_reference
from .model_request_logs import write_model_request_log
from .perf_logging import canvas_perf_elapsed_ms
from .perf_logging import canvas_perf_log
from .perf_logging import canvas_perf_start
from .store_core import _emit_agent_event
from .storyboard_video_generation import _build_storyboard_video_request
from .storyboard_video_generation import _storyboard_video_debug_block_request_log_input
from .task_canvas_sync import _task_canvas_changed_resources
from .task_contract import _task_failure_fields
from .task_control import _ACTIVE_GLOBAL_TASK_STATUSES
from .task_control import _begin_task_result_commit
from .task_control import _emit_task_update
from .task_control import _get_task
from .task_control import _update_task_if_active
from .task_events import _attach_production_status_event_effect
from .task_events import _emit_storyboard_video_task_project_changed
from .task_events import _episode_production_status_event_effect
from .task_events import _maybe_report_agent_bound_generation_task
from .task_events import _task_canvas_mutation_event_fields
from .task_lifecycle import _background_storyboard_task_allows_finish
from .task_lifecycle import _storyboard_video_task_allows_work
from .task_request_identity import _canvas_task_idempotency_key
from .task_storage import _hydrate_task_runtime_fields
from .task_storage import _load_tasks
from .task_storage import _load_tasks_for_project
from .task_storage import _normalized_task_status
from .task_control import _update_task_fields_and_sync_canvas as _update_task_fields
from .task_control import _update_video_task_if_active
from .task_workflow_context import _assert_generation_closure_ready
from .task_workflow_context import _canvas_task_context_workflow
from .task_workflow_context import _generation_meaningful_title
from .task_workflow_context import _generation_output_success_text
from .task_workflow_context import _task_stored_work_chain_fields
from .task_workflow_context import _video_generation_debug_block_enabled
from .task_workflow_context import _workflow_task_focus_target
from .task_workflow_context import _workflow_task_work_chain_fields
from .video_task_provider import _block_storyboard_video_version
from .video_task_provider import _cancel_storyboard_video_provider_job_async
from .video_task_provider import _fail_storyboard_video_version
from .video_task_provider import _merge_storyboard_video_debug
from .video_task_provider import _poll_storyboard_video_job
from .video_task_provider import _response_to_storyboard_video_metadata
from .video_task_provider import _storyboard_video_job_from_request
from .video_task_requests import _add_storyboard_video_blocked_version
from .video_task_requests import _storyboard_video_generation_request_context
from .video_task_requests import _storyboard_video_job_from_request_context
from .video_task_requests import _storyboard_video_processing_version_and_job
from .video_task_requests import _update_storyboard_video_processing_version
from .workflow_storyboard_edits import _update_storyboard_version_metadata
from .runtime_state import _VIDEO_GENERATION_TASK_TYPES
from .runtime_state import _VIDEO_TASK_CANCEL_FLAGS
from .runtime_state import _VIDEO_TASK_POLL_SECONDS
from .runtime_state import _VIDEO_TASK_RESTORE_MESSAGE
from .runtime_state import _VIDEO_TASK_THREADS
from .workflow_variant_quality import auto_review_variant_quality
from typing import Any
from utils.media_backends import submit_video_media_job
import copy
import threading
import time
import traceback


def _finish_storyboard_video_task(task_id: str, response: Any, job: dict[str, Any]) -> None:
    task = _get_task(task_id)
    if not task:
        return
    if _normalized_task_status(task) not in _ACTIVE_GLOBAL_TASK_STATUSES:
        return
    project_id = str(task.get("projectId") or "")
    episode_id = str(task.get("episodeId") or "")
    version_id = str(task.get("versionId") or job.get("versionId") or "")
    task_node_id = str(job.get("taskNodeId") or task.get("nodeId") or "").strip()
    version_node_id = str(
        job.get("versionNodeId")
        or task.get("versionNodeId")
        or job.get("resultNodeId")
        or task.get("resultNodeId")
        or task_node_id
    ).strip()
    metadata = _response_to_storyboard_video_metadata(project_id, episode_id, response, job)
    updated_version = None
    quality_review_target: dict[str, str] = {}
    if not _background_storyboard_task_allows_finish(task_id):
        return
    committing_task = _begin_task_result_commit(task_id, message="正在保存视频生成结果。")
    if not committing_task:
        return
    task = committing_task
    if version_id:
        updated_version = _update_storyboard_version_metadata(
            project_id,
            episode_id,
            version_id,
            metadata,
        )
        quality_review_target = {
            "nodeId": version_node_id or task_node_id,
            "versionId": version_id,
        }
    if not _background_storyboard_task_allows_finish(task_id):
        return
    now_ms = int(datetime.now().timestamp() * 1000)
    work_chain_fields = _task_stored_work_chain_fields(
        task,
        payload=job,
    )
    notice = _generation_output_success_text(
        _generation_meaningful_title(
            job.get("resultTitle")
            or job.get("title")
            or metadata.get("title")
            or task.get("title")
            or task.get("nodeTitle")
            or "视频"
        ),
        "视频",
    )
    video_mutation_fields = _task_canvas_mutation_event_fields(updated_version)
    video_changed_resources = _task_canvas_changed_resources(
        updated_version,
        fallback=["canvas_task", "canvas_node", "canvas_version"],
    )
    video_result_payload = (
        {
            "nodeId": version_node_id or task_node_id,
            "taskNodeId": task_node_id,
            "resultNodeId": str(job.get("resultNodeId") or task.get("resultNodeId") or version_node_id),
            "versionId": version_id,
            "version": updated_version,
            "media": updated_version.get("media") if isinstance(updated_version, dict) else None,
            **copy.deepcopy(video_mutation_fields),
            "changedResources": copy.deepcopy(video_changed_resources),
        }
        if isinstance(updated_version, dict)
        else None
    )
    completed_debug = _merge_storyboard_video_debug(job, response)
    completed_event_payload = (
        {
            "version": updated_version,
            "result": video_result_payload,
            **copy.deepcopy(video_mutation_fields),
            "changedResources": copy.deepcopy(video_changed_resources),
        }
        if video_result_payload
        else None
    )
    completed = _update_task_if_active(
        task_id,
        status="completed",
        progress=100,
        message=notice,
        notice=notice,
        completedAt=now_ms,
        resultNodeId=str(job.get("resultNodeId") or task.get("resultNodeId") or version_node_id),
        outputNodeId=version_node_id,
        versionNodeId=version_node_id,
        **work_chain_fields,
        focusTarget=_workflow_task_focus_target(
            episode_id,
            version_node_id or task_node_id,
            version_id=version_id,
        ),
        videoJob={**job, "phase": "completed", "debug": completed_debug},
        updatedAt=now_ms,
    )
    if not completed:
        return
    production_status_effect = _episode_production_status_event_effect(project_id, episode_id)
    _emit_task_update(
        (
            {**completed, **copy.deepcopy(completed_event_payload)}
            if isinstance(completed_event_payload, dict)
            else completed
        ),
        "task_completed",
    )
    task_for_events = completed or _get_task(task_id) or task
    project_event = {
        "action": f"{str(task.get('type') or 'storyboard_video')}_generated",
        "projectId": project_id,
        "episodeId": episode_id,
        "nodeId": version_node_id or task_node_id,
        "taskNodeId": task_node_id,
        "resultNodeId": str(job.get("resultNodeId") or task.get("resultNodeId") or version_node_id),
        "versionId": version_id,
        "version": updated_version if isinstance(updated_version, dict) else None,
        **copy.deepcopy(video_mutation_fields),
        "changedResources": copy.deepcopy(video_changed_resources),
    }
    _attach_production_status_event_effect(project_event, production_status_effect)
    _emit_agent_event("project_changed", project_event)
    completed_task = _get_task(task_id) or task_for_events
    if quality_review_target:
        try:
            auto_review_variant_quality(project_id, episode_id, quality_review_target)
        except Exception:
            print(traceback.format_exc(), flush=True)
    completed_task = _get_task(task_id) or completed_task
    _maybe_report_agent_bound_generation_task(_get_task(task_id) or completed_task, success=True)


def _run_storyboard_video_task(task_id: str, cancel_event: threading.Event) -> None:
    VideoTaskExecution(task_id, cancel_event).run()


class VideoTaskExecution:
    """视频请求准备、供应商提交和轮询共享本次任务的执行状态。"""

    def __init__(self, task_id: str, cancel_event: threading.Event) -> None:
        self.task_id = task_id
        self.cancel_event = cancel_event
        self.worker_started_at = canvas_perf_start()
        self.project_id = ""
        self.episode_id = ""
        self.node_id = ""
        self.worker_status = "ok"

    def run(self) -> None:
        try:
            if self._load_active_task() is False:
                return
            if not self.provider_job_id:
                if self._prepare_submission() is False:
                    return
                if self._resolve_request_context() is False:
                    return
                self._build_request()
                if self._submit_to_provider() is False:
                    return
                if self._accept_submitted_job() is False:
                    return
            self._poll_and_finish()
        except Exception as exc:
            self._handle_failure(exc)
        finally:
            self._release_worker()

    def _load_active_task(self) -> bool | None:
        self.task = _get_task(self.task_id)
        if not self.task:
            self.worker_status = "missing_task"
            return False
        if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event, task=self.task):
            self.worker_status = "cancelled" if self.cancel_event.is_set() else "inactive"
            return False
        self.job = self.task.get("videoJob") if isinstance(self.task.get("videoJob"), dict) else {}
        self.project_id = str(self.task.get("projectId") or "")
        self.episode_id = str(self.task.get("episodeId") or "")
        self.node_id = str(self.task.get("nodeId") or "")
        if not self.project_id or not self.episode_id or not self.node_id:
            raise RuntimeError("视频任务缺少 projectId、episodeId 或 nodeId")

        self.provider_job_id = str(self.job.get("providerJobId") or "")

    def _prepare_submission(self) -> bool | None:
        if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event):
            self.worker_status = "cancelled" if self.cancel_event.is_set() else "inactive"
            return False
        if str(self.job.get("phase") or "") == "generating" and self.job.get("resumable") is False:
            raise RuntimeError("视频任务来自不可恢复供应商，后端重启后无法接续，请重新生成。")
        self.debug_block_enabled = _video_generation_debug_block_enabled(self.project_id)
        if self.debug_block_enabled:
            if not _update_video_task_if_active(
                self.task_id,
                status="running",
                progress=10,
                message="视频阻断模式：正在组装最终提示词。",
            ):
                self.worker_status = "inactive"
                return False
        else:
            if not _update_video_task_if_active(
                self.task_id,
                status="running",
                progress=10,
                message="正在提交视频任务到供应商。",
            ):
                self.worker_status = "inactive"
                return False

    def _resolve_request_context(self) -> bool | None:
        self.workflow: dict[str, Any] | None = None
        if self.job.get("requestContextDeferred"):
            prepare_context_started_at = canvas_perf_start()
            if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event):
                self.worker_status = "cancelled" if self.cancel_event.is_set() else "inactive"
                return False
            request_context = _storyboard_video_generation_request_context(
                self.project_id,
                self.episode_id,
                str(self.job.get("requestedNodeId") or self.node_id),
                user_instruction=str(self.job.get("userInstruction") or ""),
                requested_node_id=str(self.job.get("requestedNodeId") or self.node_id),
                generation_config=self.job.get("generationConfig") if isinstance(self.job.get("generationConfig"), dict) else None,
                generation_config_provided=bool(self.job.get("generationConfigProvided")),
                payload_overrides=self.job.get("payloadOverrides") if isinstance(self.job.get("payloadOverrides"), dict) else None,
            )
            selected_node_id = str(request_context.get("selectedNodeId") or self.node_id)
            video_result_node_id = str(request_context.get("resultNodeId") or self.job.get("resultNodeId") or "")
            version_node_id = str(request_context.get("versionNodeId") or self.job.get("versionNodeId") or selected_node_id)
            idempotency_key = str(self.task.get("idempotencyKey") or self.job.get("idempotencyKey") or "").strip()
            if not idempotency_key:
                idempotency_key = _canvas_task_idempotency_key(
                    "storyboard_video",
                    self.project_id,
                    self.episode_id,
                    selected_node_id,
                    result_node_id=video_result_node_id,
                    version_node_id=version_node_id,
                )
            self.workflow = request_context["workflow"]
            _assert_generation_closure_ready(
                self.project_id,
                self.episode_id,
                "storyboard_video",
                node_id=selected_node_id,
                workflow=self.workflow,
                video_task_scope=str(request_context.get("videoTaskScope") or ""),
            )
            if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event):
                self.worker_status = "cancelled" if self.cancel_event.is_set() else "inactive"
                return False
            if self.debug_block_enabled:
                self.job, _prepared_payload = _storyboard_video_job_from_request_context(
                    self.task_id,
                    request_context,
                    client_request_id=str(self.task.get("clientRequestId") or self.job.get("clientRequestId") or ""),
                    idempotency_key=idempotency_key,
                )
            else:
                version, prepared_job, _prepared_payload = _storyboard_video_processing_version_and_job(
                    self.project_id,
                    self.episode_id,
                    self.task_id,
                    request_context,
                    client_request_id=str(self.task.get("clientRequestId") or self.job.get("clientRequestId") or ""),
                    idempotency_key=idempotency_key,
                )
                self.job = prepared_job
                self.task = _update_video_task_if_active(
                    self.task_id,
                    status="running",
                    progress=12,
                    message="视频任务已入队，正在组装最终提示词。",
                    versionId=version["id"],
                    resultNodeId=video_result_node_id,
                    outputNodeId=version_node_id,
                    versionNodeId=version_node_id,
                    nodeTitle=str(request_context.get("resultTitle") or request_context.get("taskTitle") or request_context.get("title") or ""),
                    title=str(request_context.get("resultTitle") or request_context.get("taskTitle") or request_context.get("title") or ""),
                    videoJob=self.job,
                    **_workflow_task_work_chain_fields(self.workflow, selected_node_id, payload=self.job.get("payload") if isinstance(self.job.get("payload"), dict) else None),
                    focusTarget=_workflow_task_focus_target(
                        self.episode_id,
                        version_node_id,
                        version_id=str(version.get("id") or ""),
                    ),
                )
                if not self.task:
                    self.worker_status = "inactive"
                    return False
            canvas_perf_log(
                "storyboard_video_task.prepare_deferred_context",
                taskId=self.task_id,
                projectId=self.project_id,
                episodeId=self.episode_id,
                nodeId=selected_node_id,
                resultNodeId=video_result_node_id,
                versionNodeId=version_node_id,
                versionId=str(self.job.get("versionId") or ""),
                debugBlockEnabled=bool(self.debug_block_enabled),
                durationMs=canvas_perf_elapsed_ms(prepare_context_started_at),
                nodeCount=len(self.workflow.get("nodes")) if isinstance(self.workflow.get("nodes"), list) else 0,
            )
        if self.workflow is None:
            if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event):
                self.worker_status = "cancelled" if self.cancel_event.is_set() else "inactive"
                return False
            load_context_started_at = canvas_perf_start()
            self.workflow = _canvas_task_context_workflow(self.project_id, self.episode_id, self.node_id)
            canvas_perf_log(
                "storyboard_video_task.load_context",
                taskId=self.task_id,
                projectId=self.project_id,
                episodeId=self.episode_id,
                nodeId=self.node_id,
                durationMs=canvas_perf_elapsed_ms(load_context_started_at),
                nodeCount=len(self.workflow.get("nodes")) if isinstance(self.workflow.get("nodes"), list) else 0,
            )
        if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event):
            self.worker_status = "cancelled" if self.cancel_event.is_set() else "inactive"
            return False

    def _build_request(self) -> None:
        build_request_started_at = canvas_perf_start()
        self.request = _build_storyboard_video_request(
            self.project_id,
            self.episode_id,
            str(self.job.get("title") or "故事版视频"),
            self.job.get("payload") if isinstance(self.job.get("payload"), dict) else {},
            self.workflow,
            prepare_transport_media=not self.debug_block_enabled,
        )
        canvas_perf_log(
            "storyboard_video_task.build_request",
            taskId=self.task_id,
            projectId=self.project_id,
            episodeId=self.episode_id,
            nodeId=self.node_id,
            durationMs=canvas_perf_elapsed_ms(build_request_started_at),
            debugBlockEnabled=bool(self.debug_block_enabled),
            promptChars=len(str(self.request.get("prompt") or "")),
            referenceImageCount=len(self.request.get("referenceImages")) if isinstance(self.request.get("referenceImages"), list) else int(bool(self.request.get("referenceImage"))),
        )
        self.submitted_job: dict[str, Any] = {}
        self.final_video_request_log: dict[str, Any] = {}
        self.final_video_request_log_errors: list[dict[str, Any]] = []

    def _persist_submitted_job(self, response: Any) -> None:
        self.submitted_job = _storyboard_video_job_from_request(self.job, self.request, response, phase="polling", resumable=True)
        if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event):
            latest_task = _get_task(self.task_id) or self.task
            provider_task = {
                **(latest_task if isinstance(latest_task, dict) else {}),
                "id": self.task_id,
                "type": "storyboard_video",
                "videoJob": self.submitted_job,
            }
            _update_task_fields(
                self.task_id,
                videoJob=self.submitted_job,
                syncCanvasTaskRecord=False,
            )
            _cancel_storyboard_video_provider_job_async(provider_task)
            return
        updated_task = _update_video_task_if_active(
            self.task_id,
            status="running",
            progress=20,
            message=f"视频任务已提交，正在等待供应商处理：{self.submitted_job.get('providerJobId')}",
            videoJob=self.submitted_job,
        )
        if updated_task:
            _update_storyboard_video_processing_version(
                self.project_id,
                self.episode_id,
                self.submitted_job,
                "视频任务已提交供应商，正在后台等待生成完成。",
            )

    def _log_final_video_request(self, request_info: dict[str, Any]) -> None:
        if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event):
            return
        log_result = write_model_request_log(
            self.project_id,
            STAGE_FINAL_VIDEO_GENERATION_REQUEST,
            request_info,
            episode_id=self.episode_id,
            node_id=self.node_id,
            task_id=self.task_id,
            phase="storyboard-video-submit",
            provider_id=str(self.request.get("providerId") or ""),
            model_name=str(self.request.get("modelName") or ""),
            endpoint=str(self.request.get("endpoint") or ""),
            blocked=self.debug_block_enabled,
            source=(
                "_run_storyboard_video_task.dry_run"
                if self.debug_block_enabled
                else "_run_storyboard_video_task.submit_video_media_job"
            ),
            analysis_snapshot={**copy.deepcopy(self.request.get("analysisSnapshot") or {}), "blocked": self.debug_block_enabled},
            assembly_context=self.request.get("assemblyContext") if isinstance(self.request.get("assemblyContext"), dict) else {},
            background=not self.debug_block_enabled,
        )
        self.final_video_request_log = copy.deepcopy(log_result)
        if not log_result.get("success"):
            self.final_video_request_log_errors.append(
                {
                    "stage": STAGE_FINAL_VIDEO_GENERATION_REQUEST,
                    "phase": "storyboard-video-submit",
                    "error": str(log_result.get("error") or "日志写入失败"),
                }
            )

    def _submit_to_provider(self) -> bool | None:
        submit_started_at = canvas_perf_start()
        if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event):
            self.worker_status = "cancelled" if self.cancel_event.is_set() else "inactive"
            return False
        if self.debug_block_enabled:
            self._log_final_video_request(_storyboard_video_debug_block_request_log_input(self.request))
            log_success = bool(self.final_video_request_log.get("success"))
            log_error = str(self.final_video_request_log.get("error") or "").strip()
            canvas_perf_log(
                "storyboard_video_task.submit_or_dry_run",
                taskId=self.task_id,
                projectId=self.project_id,
                episodeId=self.episode_id,
                nodeId=self.node_id,
                status="debug_blocked" if log_success else "debug_log_failed",
                durationMs=canvas_perf_elapsed_ms(submit_started_at),
                logSuccess=log_success,
            )
            if not log_success:
                raise RuntimeError(f"视频阻断提示词日志写入失败：{log_error or '未知错误'}")
            blocked_job = _storyboard_video_job_from_request(
                self.job,
                self.request,
                None,
                phase="debug_blocked",
                resumable=False,
            )
            blocked_job["providerRequest"] = {
                "providerId": self.request["providerId"],
                "modelName": self.request["modelName"],
                "endpoint": self.request["endpoint"],
                "durationSeconds": self.request["durationSeconds"],
                "finalPromptChars": len(str(self.request.get("prompt") or "")),
            }
            blocked_debug = blocked_job.get("debug") if isinstance(blocked_job.get("debug"), dict) else {}
            blocked_debug.pop("providerRequest", None)
            blocked_job["debug"] = blocked_debug
            blocked_job["debugBlockLog"] = copy.deepcopy(self.final_video_request_log)
            self.message = "视频阻断已开启：已写入最终提示词，未请求供应商 API。"
            blocked_version_node_id = str(
                blocked_job.get("versionNodeId")
                or self.job.get("versionNodeId")
                or blocked_job.get("resultNodeId")
                or self.job.get("resultNodeId")
                or self.node_id
            ).strip()
            blocked_result_node_id = str(blocked_job.get("resultNodeId") or self.job.get("resultNodeId") or "").strip()
            blocked_version_id = str(blocked_job.get("versionId") or self.job.get("versionId") or "").strip()
            created_blocked_version: dict[str, Any] | None = None
            committing_task = _begin_task_result_commit(self.task_id, message="正在保存视频生成结果。")
            if not committing_task:
                return False
            if not blocked_version_id:
                created_blocked_version = _add_storyboard_video_blocked_version(
                    self.project_id,
                    self.episode_id,
                    blocked_version_node_id,
                    blocked_job,
                    self.message,
                )
                blocked_version_id = str(created_blocked_version.get("id") or "").strip()
                if blocked_version_id:
                    blocked_job["versionId"] = blocked_version_id
            else:
                _block_storyboard_video_version(
                    {**committing_task, "videoJob": blocked_job, "versionId": blocked_version_id},
                    self.message,
                    workflow=self.workflow,
                )
            blocked = _update_video_task_if_active(
                self.task_id,
                preferred_event="task_failed",
                status="blocked",
                progress=0,
                message=self.message,
                notice=self.message,
                blockedAt=int(datetime.now().timestamp() * 1000),
                versionId=blocked_version_id,
                resultNodeId=blocked_result_node_id,
                outputNodeId=blocked_version_node_id,
                versionNodeId=blocked_version_node_id,
                focusTarget=_workflow_task_focus_target(
                    self.episode_id,
                    blocked_version_node_id,
                    version_id=blocked_version_id,
                ),
                videoJob=blocked_job,
            )
            if blocked:
                _emit_storyboard_video_task_project_changed(blocked, "storyboard_video_debug_blocked")
                _maybe_report_agent_bound_generation_task(blocked, success=False)
            return False
        try:
            if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event):
                self.worker_status = "cancelled" if self.cancel_event.is_set() else "inactive"
                return False
            self.submitted = submit_video_media_job(
                self.request["provider"],
                self.request["providerId"],
                self.request["baseUrl"],
                self.request["modelName"],
                self.request["prompt"],
                self.request["referenceImage"],
                reference_images=self.request.get("referenceImages") if isinstance(self.request.get("referenceImages"), list) else None,
                reference_videos=self.request.get("referenceVideos") if isinstance(self.request.get("referenceVideos"), list) else None,
                **({"reference_audios": self.request["referenceAudios"]} if self.request.get("referenceAudios") else {}),
                **({"replacement_subject": self.request.get("replacementSubject", "person")} if self.request.get("replacementSubject") else {}),
                strategy=str(self.request.get("providerRequest", {}).get("strategy") or ""),
                size=self.request["size"],
                aspect_ratio=self.request["aspectRatio"],
                resolution=self.request["resolution"],
                duration_seconds=self.request["durationSeconds"],
                generate_audio=self.request["generateAudio"],
                endpoint=self.request["endpoint"],
                on_job_submitted=self._persist_submitted_job,
                image_input_limits=self.request.get("imageInputLimits") if isinstance(self.request.get("imageInputLimits"), dict) else None,
                on_request_prepared=self._log_final_video_request,
            )
        except Exception:
            canvas_perf_log(
                "storyboard_video_task.submit_or_dry_run",
                taskId=self.task_id,
                projectId=self.project_id,
                episodeId=self.episode_id,
                nodeId=self.node_id,
                status="error",
                durationMs=canvas_perf_elapsed_ms(submit_started_at),
            )
            raise
        canvas_perf_log(
            "storyboard_video_task.submit_or_dry_run",
            taskId=self.task_id,
            projectId=self.project_id,
            episodeId=self.episode_id,
            nodeId=self.node_id,
            status="submitted",
            durationMs=canvas_perf_elapsed_ms(submit_started_at),
        )

    def _accept_submitted_job(self) -> bool | None:
        self.job = self.submitted_job or _storyboard_video_job_from_request(self.job, self.request, self.submitted)
        if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event):
            if not self.submitted.raw:
                latest_task = _get_task(self.task_id) or self.task
                provider_task = {
                    **(latest_task if isinstance(latest_task, dict) else {}),
                    "id": self.task_id,
                    "type": "storyboard_video",
                    "videoJob": self.job,
                }
                _update_task_fields(
                    self.task_id,
                    videoJob=self.job,
                    syncCanvasTaskRecord=False,
                )
                _cancel_storyboard_video_provider_job_async(provider_task)
            self.worker_status = "cancelled" if self.cancel_event.is_set() else "inactive"
            return False
        if self.final_video_request_log or self.final_video_request_log_errors:
            debug_payload = copy.deepcopy(self.job.get("debug") if isinstance(self.job.get("debug"), dict) else {})
            if self.final_video_request_log.get("success"):
                debug_payload["modelRequestLog"] = model_request_log_reference(
                    self.final_video_request_log,
                    phase="storyboard-video-submit",
                )
            if self.final_video_request_log_errors:
                existing_errors = (
                    debug_payload.get("modelRequestLogErrors")
                    if isinstance(debug_payload.get("modelRequestLogErrors"), list)
                    else []
                )
                debug_payload["modelRequestLogErrors"] = [
                    *copy.deepcopy(existing_errors),
                    *copy.deepcopy(self.final_video_request_log_errors),
                ]
            self.job["debug"] = debug_payload
        if self.submitted.raw:
            _finish_storyboard_video_task(self.task_id, self.submitted, self.job)
            return False
        if not self.submitted.job_id:
            raise RuntimeError("供应商已受理视频任务，但未返回可恢复的任务 ID")
        if self.final_video_request_log or self.final_video_request_log_errors:
            _update_storyboard_video_processing_version(
                self.project_id,
                self.episode_id,
                self.job,
                "视频任务已提交供应商，正在后台等待生成完成。",
            )
        if not _update_video_task_if_active(
            self.task_id,
            status="running",
            progress=25,
            message=f"视频任务已提交，正在等待供应商处理：{self.submitted.job_id}",
            videoJob=self.job,
        ):
            self.worker_status = "inactive"
            return False

    def _poll_and_finish(self) -> bool | None:
        while not self.cancel_event.is_set():
            latest = _get_task(self.task_id)
            if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event, task=latest):
                return False
            response = _poll_storyboard_video_job(self.job)
            latest = _get_task(self.task_id)
            if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event, task=latest):
                return False
            if getattr(response, "raw", None):
                _finish_storyboard_video_task(self.task_id, response, self.job)
                return False
            current_progress = int((latest or {}).get("progress") or 25)
            self.job = {**self.job, "phase": "polling", "debug": _merge_storyboard_video_debug(self.job, response)}
            _update_video_task_if_active(
                self.task_id,
                status="running",
                progress=min(95, max(30, current_progress + 3)),
                message="供应商正在生成视频，任务状态已保持。",
                videoJob=self.job,
                syncCanvasTaskRecord=False,
            )
            time.sleep(_VIDEO_TASK_POLL_SECONDS)

        latest = _get_task(self.task_id)
        if not _storyboard_video_task_allows_work(self.task_id, self.cancel_event, task=latest):
            return False
        cancelled = _update_video_task_if_active(
            self.task_id,
            status="failed",
            progress=0,
            message=str((latest or {}).get("message") or "已取消"),
            notice=str((latest or {}).get("message") or "已取消"),
            failedAt=int(datetime.now().timestamp() * 1000),
        )
        if cancelled:
            _fail_storyboard_video_version(cancelled, "已取消")
            _emit_storyboard_video_task_project_changed(cancelled, "storyboard_video_cancelled")
            _maybe_report_agent_bound_generation_task(cancelled, success=False)

    def _handle_failure(self, exc: Exception) -> None:
        self.worker_status = "error"
        traceback_text = traceback.format_exc()
        print(traceback_text, flush=True)
        self.message = str(exc) or exc.__class__.__name__
        self.task = _update_video_task_if_active(
            self.task_id,
            status="failed",
            progress=0,
            failedAt=int(datetime.now().timestamp() * 1000),
            **_task_failure_fields(
                self.message,
                prefix="视频生成失败",
                traceback_text=traceback_text,
                provider_response=self.message,
            ),
        )
        if self.task:
            _fail_storyboard_video_version(self.task, self.message)
            _emit_storyboard_video_task_project_changed(self.task, "storyboard_video_failed")
            _maybe_report_agent_bound_generation_task(self.task, success=False)

    def _release_worker(self) -> None:
        canvas_perf_log(
            "storyboard_video_task.worker",
            taskId=self.task_id,
            projectId=self.project_id,
            episodeId=self.episode_id,
            nodeId=self.node_id,
            status=self.worker_status,
            durationMs=canvas_perf_elapsed_ms(self.worker_started_at),
        )
        with _LOCK:
            _VIDEO_TASK_THREADS.pop(self.task_id, None)
            _VIDEO_TASK_CANCEL_FLAGS.pop(self.task_id, None)


def _ensure_storyboard_video_worker(task_id: str, *, restored: bool = False) -> None:
    task = _get_task(task_id)
    if not task or task.get("type") not in _VIDEO_GENERATION_TASK_TYPES:
        return
    if not _storyboard_video_task_allows_work(task_id, task=task):
        return
    if not isinstance(task.get("videoJob"), dict):
        return
    with _LOCK:
        current = _VIDEO_TASK_THREADS.get(task_id)
        if current and current.is_alive():
            return
        cancel_event = threading.Event()
        thread = threading.Thread(
            target=_run_storyboard_video_task,
            args=(task_id, cancel_event),
            name=f"ai-video-storyboard-video-{task_id}",
            daemon=True,
        )
        _VIDEO_TASK_CANCEL_FLAGS[task_id] = cancel_event
        _VIDEO_TASK_THREADS[task_id] = thread
    if restored:
        if not _update_video_task_if_active(task_id, status="running", message=_VIDEO_TASK_RESTORE_MESSAGE):
            with _LOCK:
                _VIDEO_TASK_THREADS.pop(task_id, None)
                _VIDEO_TASK_CANCEL_FLAGS.pop(task_id, None)
            return
    thread.start()


def _resume_storyboard_video_tasks(project_id: str | None = None) -> None:
    normalized_project_id = str(project_id or "").strip()
    rows = _load_tasks_for_project(normalized_project_id) if normalized_project_id else _load_tasks()
    _resume_storyboard_video_task_rows(rows)


def _resume_storyboard_video_task_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        task = _hydrate_task_runtime_fields(row)
        if task.get("type") not in _VIDEO_GENERATION_TASK_TYPES:
            continue
        if not _storyboard_video_task_allows_work(str(task.get("id") or ""), task=task):
            continue
        if not isinstance(task.get("videoJob"), dict):
            continue
        _ensure_storyboard_video_worker(str(task.get("id") or ""), restored=True)
