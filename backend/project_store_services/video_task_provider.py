# -*- coding: utf-8 -*-
"""供应商视频 job、结果元数据、取消和版本状态更新。"""
from __future__ import annotations

from datetime import datetime
from .agent_sessions import _persistent_media_data_removed
from .media_files import _save_project_media_file
from .model_provider_config import _provider_base_url
from .store_core import _display_time
from .provider_models import _normalize_provider_id
from .provider_models import _provider_service_id
from .settings_loaders import load_global_config
from .store_core import _now
from .task_control import _emit_task_update
from .task_events import _emit_storyboard_video_task_project_changed
from .task_storage import _TASK_STORAGE_LOCK
from .task_storage import _hydrate_task_runtime_fields
from .task_storage import _load_task_storage_bucket
from .task_storage import _load_tasks
from .task_storage import _save_task_storage_bucket
from .task_storage import _save_tasks
from .task_storage import _task_storage_key_for_task_id
from .workflow_storyboard_edits import _update_storyboard_version_metadata
from .runtime_state import _VIDEO_GENERATION_TASK_TYPES
from typing import Any
from utils.media_backends import cancel_video_media_job
from utils.media_backends import poll_video_media_job
import copy
import threading
import traceback
import uuid


def _provider_for_video_job(job: dict[str, Any]) -> dict[str, Any]:
    provider_instance_id = _normalize_provider_id(job.get("providerInstanceId"))
    provider_id = _normalize_provider_id(job.get("providerId"))
    providers = load_global_config().get("providers", [])
    if not isinstance(providers, list):
        providers = []
    provider = next(
        (
            row
            for row in providers
            if provider_instance_id and _normalize_provider_id(row.get("id")) == provider_instance_id
        ),
        None,
    )
    if provider is None:
        provider = next(
            (
                row
                for row in providers
                if provider_id and _provider_service_id(row) == provider_id
            ),
            None,
        )
    if not provider:
        raise RuntimeError(f"视频任务恢复失败：供应商 {provider_instance_id or provider_id or 'unknown'} 不存在")
    if not provider.get("api_key"):
        raise RuntimeError(f"视频任务恢复失败：供应商 {provider_instance_id or provider_id} 缺少 API Key")
    return provider


def _storyboard_video_response_debug(response: Any | None) -> dict[str, Any]:
    if response is None:
        return {}
    debug = getattr(response, "debug", {})
    return copy.deepcopy(debug) if isinstance(debug, dict) else {}


def _merge_storyboard_video_debug(job: dict[str, Any], response: Any | None = None) -> dict[str, Any]:
    existing_debug = job.get("debug") if isinstance(job.get("debug"), dict) else {}
    return {
        **copy.deepcopy(existing_debug),
        **_storyboard_video_response_debug(response),
    }


def _validate_downloaded_video_payload(raw: Any) -> bytes:
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise RuntimeError("视频任务尚未返回可保存的视频内容")
    payload = bytes(raw)
    head = payload[:4096].lstrip().lower()
    if head.startswith((b"<html", b"<!doctype", b"{", b"[")):
        raise RuntimeError("供应商返回了错误页而不是视频文件")
    # All currently enabled video adapters promise MP4 output. Checking the
    # ISO-BMFF signature prevents HTML/JSON bodies from being saved as .mp4.
    if b"ftyp" not in payload[:64]:
        raise RuntimeError("供应商返回的内容不是有效的 MP4 视频文件")
    return payload


def _response_to_storyboard_video_metadata(
    project_id: str,
    episode_id: str,
    response: Any,
    job: dict[str, Any],
) -> dict[str, Any]:
    raw = _validate_downloaded_video_payload(getattr(response, "raw", None))
    media_id = f"video-{episode_id}-{uuid.uuid4().hex[:8]}"
    file_meta = _save_project_media_file(
        project_id,
        raw,
        media_id=media_id,
        suffix=".mp4",
        subdir="videos",
        storage_scope="episode_results",
        episode_id=episode_id,
    )
    media = {
        **file_meta,
        "kind": "video",
        "mimeType": "video/mp4",
    }
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    title = str(payload.get("versionTitle") or payload.get("version_title") or job.get("title") or "故事版视频")
    generation_debug = _merge_storyboard_video_debug(job, response)
    return {
        "title": title,
        "summary": f"{title}已生成成功。",
        "source": "model-video-generation",
        "payload": _storyboard_video_version_payload_for_storage(payload),
        "media": media,
        "model": job.get("modelId") or job.get("modelName"),
        "provider": job.get("providerId"),
        "generationDebug": _persistent_media_data_removed(
            {
                **generation_debug,
                "providerRequest": job.get("providerRequest") or {},
            }
        ),
        "status": "ready",
        "completedAt": _display_time(_now()),
    }


def _fail_storyboard_video_version(task: dict[str, Any], message: str) -> None:
    job = task.get("videoJob") if isinstance(task.get("videoJob"), dict) else {}
    version_id = str(task.get("versionId") or job.get("versionId") or "")
    if not version_id:
        return
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    _update_storyboard_version_metadata(
        str(task.get("projectId") or ""),
        str(task.get("episodeId") or ""),
        version_id,
        {
            "title": str(job.get("title") or "故事版视频"),
            "summary": f"视频模型生成失败：{message}",
            "source": "model-video-job",
            "payload": payload,
            "generationError": message,
            "status": "failed",
        },
    )


def _block_storyboard_video_version(
    task: dict[str, Any],
    message: str,
    *,
    workflow: dict[str, Any] | None = None,
) -> None:
    job = task.get("videoJob") if isinstance(task.get("videoJob"), dict) else {}
    version_id = str(task.get("versionId") or job.get("versionId") or "")
    if not version_id:
        return
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    debug_payload = copy.deepcopy(job.get("debug") if isinstance(job.get("debug"), dict) else {})
    for key in ("debugBlockLog", "debugBlockLogError"):
        if key in job:
            debug_payload[key] = copy.deepcopy(job.get(key))
    _update_storyboard_version_metadata(
        str(task.get("projectId") or ""),
        str(task.get("episodeId") or ""),
        version_id,
        {
            "title": str(job.get("title") or "故事版视频"),
            "summary": message,
            "source": "model-video-job",
            "payload": payload,
            "generationError": message,
            **(
                {"generationDebug": _persistent_media_data_removed(debug_payload)}
                if debug_payload
                else {}
            ),
            "status": "blocked",
        },
        workflow=workflow,
    )


def _cancel_storyboard_video_version(task: dict[str, Any], message: str) -> None:
    job = task.get("videoJob") if isinstance(task.get("videoJob"), dict) else {}
    version_id = str(task.get("versionId") or job.get("versionId") or "")
    if not version_id:
        return
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    _update_storyboard_version_metadata(
        str(task.get("projectId") or ""),
        str(task.get("episodeId") or ""),
        version_id,
        {
            "title": str(job.get("title") or "故事版视频"),
            "summary": message,
            "source": "model-video-job",
            "payload": payload,
            "generationError": message,
            "providerCancel": job.get("providerCancel") or {},
            "status": "failed",
            "cancelledAt": task.get("cancelledAt") or _display_time(_now()),
        },
    )


def _poll_storyboard_video_job(job: dict[str, Any]) -> Any:
    provider = _provider_for_video_job(job)
    return poll_video_media_job(
        provider,
        str(job.get("providerId") or _provider_service_id(provider)),
        str(job.get("baseUrl") or _provider_base_url(provider)),
        str(job.get("modelName") or ""),
        str(job.get("providerJobId") or ""),
        size=str(job.get("size") or "720x1280"),
        aspect_ratio=str(job.get("aspectRatio") or ""),
        resolution=str(job.get("resolution") or "720p"),
        duration_seconds=int(job.get("durationSeconds") or 8),
        endpoint=job.get("endpoint"),
    )


def _cancel_storyboard_video_provider_job(task: dict[str, Any]) -> dict[str, Any]:
    if task.get("type") not in _VIDEO_GENERATION_TASK_TYPES:
        return {"supported": False, "cancelled": False, "reason": "not_video_generation"}
    job = task.get("videoJob") if isinstance(task.get("videoJob"), dict) else {}
    provider_job_id = str(job.get("providerJobId") or "").strip()
    if not provider_job_id:
        return {
            "supported": False,
            "cancelled": False,
            "reason": "missing_provider_job_id",
            "resumable": bool(job.get("resumable", True)),
        }
    try:
        provider = _provider_for_video_job(job)
        return cancel_video_media_job(
            provider,
            str(job.get("providerId") or _provider_service_id(provider)),
            str(job.get("baseUrl") or _provider_base_url(provider)),
            provider_job_id,
            endpoint=job.get("endpoint"),
        )
    except Exception as exc:
        return {
            "supported": True,
            "cancelled": False,
            "jobId": provider_job_id,
            "error": str(exc),
        }


def _cancel_message_with_provider_result(cancel_result: dict[str, Any]) -> str:
    if not cancel_result:
        return "已取消"
    if cancel_result.get("cancelled"):
        return "已取消，供应商已确认取消视频任务。"
    if cancel_result.get("requested"):
        return "已取消，已向供应商发送远端取消或清理请求。"
    if cancel_result.get("supported") and cancel_result.get("error"):
        return f"已取消，供应商取消请求失败：{cancel_result.get('error')}"
    if cancel_result.get("supported") is False and cancel_result.get("reason") == "missing_provider_job_id":
        return "已取消，供应商任务尚未提交或没有可取消的远端任务 ID。"
    if cancel_result.get("supported") is False:
        return "已取消，当前供应商暂不支持远端取消。"
    return "已取消"


def _apply_video_provider_cancel_result(
    task_id: str,
    provider_cancel: dict[str, Any],
) -> dict[str, Any] | None:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id or not provider_cancel:
        return None
    storage_key = _task_storage_key_for_task_id(normalized_task_id)
    with _TASK_STORAGE_LOCK:
        tasks = _load_task_storage_bucket(storage_key) if storage_key else _load_tasks()
        updated: dict[str, Any] | None = None
        for index, task in enumerate(tasks):
            if str(task.get("id") or "") != normalized_task_id:
                continue
            if str(task.get("status") or "") != "cancelled":
                return None
            next_task = _hydrate_task_runtime_fields(task)
            next_task["message"] = _cancel_message_with_provider_result(provider_cancel)
            next_task["updatedAt"] = int(datetime.now().timestamp() * 1000)
            if next_task.get("type") in _VIDEO_GENERATION_TASK_TYPES:
                job = next_task.get("videoJob") if isinstance(next_task.get("videoJob"), dict) else {}
                next_task["videoJob"] = {**job, "providerCancel": provider_cancel}
            tasks[index] = next_task
            updated = next_task
            break
        if updated:
            if storage_key:
                _save_task_storage_bucket(storage_key, tasks)
            else:
                _save_tasks(tasks)
        return updated


def _cancel_storyboard_video_provider_job_async(task: dict[str, Any]) -> None:
    if not isinstance(task, dict) or task.get("type") not in _VIDEO_GENERATION_TASK_TYPES:
        return
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        return
    snapshot = copy.deepcopy(task)

    def _worker() -> None:
        try:
            provider_cancel = _cancel_storyboard_video_provider_job(snapshot)
            updated = _apply_video_provider_cancel_result(task_id, provider_cancel)
            if not updated:
                return
            _cancel_storyboard_video_version(updated, str(updated.get("message") or "已取消"))
            _emit_storyboard_video_task_project_changed(updated, "storyboard_video_cancelled")
            _emit_task_update(updated, "task_cancelled")
        except Exception:
            print(traceback.format_exc(), flush=True)

    threading.Thread(
        target=_worker,
        name=f"ai-video-provider-cancel-{task_id}",
        daemon=True,
    ).start()


def _storyboard_video_job_from_request(
    job: dict[str, Any],
    request: dict[str, Any],
    response: Any | None = None,
    *,
    phase: str | None = None,
    resumable: bool = True,
) -> dict[str, Any]:
    provider = request.get("provider") if isinstance(request.get("provider"), dict) else {}
    provider_job_id = str(getattr(response, "job_id", "") or "")
    return {
        **job,
        "phase": phase or ("polling" if provider_job_id else "completed"),
        "providerJobId": provider_job_id,
        "providerInstanceId": _normalize_provider_id(provider.get("id")),
        "providerId": request["providerId"],
        "baseUrl": request["baseUrl"],
        "modelId": request["model"].get("id"),
        "modelName": request["modelName"],
        "size": request["size"],
        "aspectRatio": request["aspectRatio"],
        "resolution": request["resolution"],
        "durationSeconds": request["durationSeconds"],
        "endpoint": request["endpoint"],
        "resumable": bool(resumable),
        "providerRequest": request.get("providerRequest") or {},
        "debug": _merge_storyboard_video_debug(job, response),
    }


def _storyboard_video_reference_file_meta(file_info: dict[str, Any]) -> dict[str, Any]:
    return {
        key: file_info.get(key)
        for key in ("name", "mimeType", "mime_type", "size", "kind", "path", "filePath", "file_path", "relativePath", "relative_path")
        if file_info.get(key) not in (None, "")
    }


def _storyboard_video_version_payload_for_storage(payload: dict[str, Any]) -> dict[str, Any]:
    stored = copy.deepcopy(payload)
    for key in (
        "referenceFiles",
        "reference_files",
        "inlineReferenceFiles",
        "inline_reference_files",
        "editReferenceFiles",
        "edit_reference_files",
    ):
        value = stored.get(key)
        if isinstance(value, list):
            stored[key] = [
                _storyboard_video_reference_file_meta(item)
                for item in value
                if isinstance(item, dict)
            ]
    return _persistent_media_data_removed(stored)
