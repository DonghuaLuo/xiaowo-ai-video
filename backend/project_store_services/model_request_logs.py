# -*- coding: utf-8 -*-
"""Project-scoped model request logging for debug and prompt audits."""

from __future__ import annotations

import copy
import errno
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalogs import PROJECTS_DIR
from utils.request_media_archive import log_directory_activity, remove_empty_log_directory

MODEL_LOG_RETENTION_HOURS = 24
MODEL_LOG_RETENTION_SECONDS = MODEL_LOG_RETENTION_HOURS * 60 * 60
_STARTUP_CLEANUP_LOCK = threading.Lock()
_STARTUP_CLEANUP_RESULT: dict[str, Any] | None = None
MODEL_REQUEST_LOG_MARKDOWN_ENV = "AI_VIDEO_MODEL_REQUEST_LOG_MARKDOWN"

STAGE_FINAL_VIDEO_GENERATION_REQUEST = "final-video-generation-request"
STAGE_ASSET_IMAGE_GENERATION_REQUEST = "asset-image-generation-request"
STAGE_STORYBOARD_IMAGE_GENERATION_PROMPT = "storyboard-image-generation-prompt"
STAGE_STORYBOARD_IMAGE_READBACK_PROMPT = "storyboard-image-readback-prompt"
STAGE_DIRECTOR_RULE_ANALYSIS_PROMPT = "director-rule-analysis-prompt"
STAGE_DIRECTOR_PLAN_PROMPT = "director-plan-prompt"
STAGE_FINAL_VIDEO_PROMPT_PLAN_PROMPT = "final-video-prompt-plan-prompt"
STAGE_CHARACTER_ASSET_DESIGN_PROMPT = "character-asset-design-prompt"
STAGE_PROJECT_OVERVIEW_PROMPT = "project-overview-prompt"
STAGE_ASSET_RANGE_BOUNDARY_PROMPT = "asset-range-boundary-prompt"
STAGE_AGENT_INTENT_PROBE_PROMPT = "agent-intent-probe-prompt"
STAGE_PLOT_SPLIT_PROPOSAL_PROMPT = "plot-split-proposal-prompt"
STAGE_ASSET_BINDING_REVIEW_PROMPT = "plot-split-asset-binding-review-prompt"

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_DATA_URL_HEADER_RE = re.compile(r"^data:([^;,]+)?(?:;[^,]*)?,", re.IGNORECASE)

_MEDIA_SOURCE_FIELD_GROUPS = (
    ("mimeType", ("mimeType", "mime_type", "contentType", "content_type")),
    ("sourceUrl", ("sourceUrl", "source_url", "publicUrl", "public_url", "remoteUrl", "remote_url", "downloadUrl", "download_url")),
    ("sourcePath", ("filePath", "file_path", "path", "relativePath", "relative_path", "localPath", "local_path")),
    ("sourceId", ("assetId", "asset_id", "mediaId", "media_id", "versionId", "version_id", "requestedReferenceId", "referenceId", "reference_id", "id")),
    ("sourceName", ("name", "fileName", "file_name", "originalName", "displayName", "label")),
    ("sourceRole", ("role", "referenceRole", "reference_role", "source", "sourceType", "source_type", "purpose")),
    ("providerFileId", ("providerFileId", "provider_file_id", "providerImageId", "provider_image_id", "providerMediaId", "provider_media_id", "fileId", "file_id")),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="microseconds")


def _safe_path_part(value: Any, fallback: str = "item") -> str:
    text = _SAFE_ID_RE.sub("-", str(value or "").strip()).strip("-._")
    return text[:80] or fallback


def _validate_project_id(project_id: Any) -> tuple[str, str]:
    text = str(project_id or "").strip()
    if not text:
        return "", "缺少 projectId"
    if text in {".", ".."}:
        return "", "项目 ID 无效"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", text):
        return "", "项目 ID 无效"
    try:
        project_root = (PROJECTS_DIR / text).resolve()
        projects_root = PROJECTS_DIR.resolve()
        project_root.relative_to(projects_root)
    except Exception:
        return "", "项目 ID 无效"
    if project_root == projects_root:
        return "", "项目 ID 无效"
    return text, ""


def _project_log_root(project_id: str) -> Path:
    return PROJECTS_DIR / project_id / "debug" / "model-request-logs"


def _project_response_log_root(project_id: str) -> Path:
    return PROJECTS_DIR / project_id / "debug" / "model-response-logs"


def _project_relative_path(project_id: str, path: Path) -> str:
    try:
        project_root = PROJECTS_DIR / project_id
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except Exception:
        return ""


def _media_kind(mime_type: str = "", source_field: str = "") -> str:
    text = f"{mime_type} {source_field}".lower()
    if "image" in text:
        return "image"
    if "video" in text:
        return "video"
    if "audio" in text:
        return "audio"
    return "media"


def _safe_media_source_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (int, float, bool)):
        text = str(value)
    else:
        return ""
    if not text or _DATA_URL_HEADER_RE.match(text):
        return ""
    return text[:1000]


def _media_context_from_mapping(value: dict[Any, Any]) -> dict[str, str]:
    context: dict[str, str] = {}
    for output_key, source_keys in _MEDIA_SOURCE_FIELD_GROUPS:
        if context.get(output_key):
            continue
        for source_key in source_keys:
            if source_key not in value:
                continue
            text = _safe_media_source_value(value.get(source_key))
            if text:
                context[output_key] = text
                break
    return context


def _next_media_index(media_index_state: dict[str, int]) -> int:
    media_index_state["media"] = int(media_index_state.get("media") or 0) + 1
    return media_index_state["media"]


def _media_reference_log_entry(
    *,
    media_index_state: dict[str, int],
    source_field: str,
    mime_type: str = "",
    char_length: int = 0,
    byte_length: int = 0,
    media_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    effective_mime_type = mime_type or (media_context or {}).get("mimeType", "")
    entry: dict[str, Any] = {
        "__type": "media_reference",
        "mediaIndex": _next_media_index(media_index_state),
        "mediaKind": _media_kind(effective_mime_type, source_field),
    }
    if source_field:
        entry["requestField"] = source_field
    if effective_mime_type:
        entry["mimeType"] = effective_mime_type
    if char_length:
        entry["originalCharLength"] = char_length
    if byte_length:
        entry["byteLength"] = byte_length
    for key, text in (media_context or {}).items():
        if key == "mimeType" and effective_mime_type:
            continue
        if text:
            entry[key] = text
    return entry


def _inline_media_base64_field(value: str, source_field: str, media_context: dict[str, str]) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    field_name = source_field.rsplit(".", 1)[-1].lower()
    if field_name in {"image", "input_reference", "image_tail"} and text.startswith(("/9j/", "iVBORw0KGgo", "UklGR")):
        return True
    if field_name not in {"data", "base64", "b64_json", "b64json"}:
        return False
    context_text = f"{source_field} {media_context.get('mimeType', '')}".lower()
    return any(token in context_text for token in ("inlinedata", "inline_data", "image", "video", "audio"))


def _request_log_safe(
    value: Any,
    *,
    source_field: str = "",
    media_index_state: dict[str, int] | None = None,
    media_context: dict[str, str] | None = None,
    media_writer: Any = None,
) -> Any:
    if media_index_state is None:
        media_index_state = {"media": 0}
    if media_context is None:
        media_context = {}
    if isinstance(value, bytes):
        entry = _media_reference_log_entry(
            media_index_state=media_index_state,
            source_field=source_field,
            byte_length=len(value),
            media_context=media_context,
        )
        if media_writer:
            entry.update(media_writer(value, entry))
        return entry
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        match = _DATA_URL_HEADER_RE.match(value)
        if match:
            entry = _media_reference_log_entry(
                media_index_state=media_index_state,
                source_field=source_field,
                mime_type=match.group(1) or "",
                char_length=len(value),
                media_context=media_context,
            )
            if media_writer:
                entry.update(media_writer(value, entry))
            return entry
        if _inline_media_base64_field(value, source_field, media_context):
            entry = _media_reference_log_entry(
                media_index_state=media_index_state,
                source_field=source_field,
                mime_type=media_context.get("mimeType", ""),
                char_length=len(value),
                media_context=media_context,
            )
            if media_writer:
                entry.update(media_writer(value, entry))
            return entry
        return value
    if isinstance(value, dict):
        next_context = dict(media_context)
        next_context.update(_media_context_from_mapping(value))
        safe_dict: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            next_source_field = f"{source_field}.{key_text}" if source_field else key_text
            safe_dict[key_text] = _request_log_safe(
                item,
                source_field=next_source_field,
                media_index_state=media_index_state,
                media_context=next_context,
                media_writer=media_writer,
            )
        return safe_dict
    if isinstance(value, (list, tuple, set)):
        return [
            _request_log_safe(
                item,
                source_field=f"{source_field}[{index}]" if source_field else f"[{index}]",
                media_index_state=media_index_state,
                media_context=media_context,
                media_writer=media_writer,
            )
            for index, item in enumerate(value)
        ]
    return value


def _first_dict_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data.get(key)
    return None


def _text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _extract_text_parts(value: Any) -> list[str]:
    parts: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        if text:
            parts.append(text)
        return parts
    if isinstance(value, list):
        for item in value:
            parts.extend(_extract_text_parts(item))
        return parts
    if isinstance(value, dict):
        for key in ("text", "prompt", "content"):
            text = _text_value(value.get(key)).strip()
            if text:
                parts.append(text)
        for key in ("parts", "content"):
            nested = value.get(key)
            if isinstance(nested, (list, dict)):
                parts.extend(_extract_text_parts(nested))
        return parts
    return parts


def _request_payload(request_data: Any) -> dict[str, Any]:
    if not isinstance(request_data, dict):
        return {}
    for key in ("requestBody", "request", "body", "payload"):
        value = request_data.get(key)
        if isinstance(value, dict):
            return value
    return request_data


def _messages_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("messages", "input", "contents"):
        value = payload.get(key)
        if isinstance(value, list):
            rows: list[dict[str, Any]] = []
            for item in value:
                if isinstance(item, dict):
                    rows.append(_request_log_safe(item))
                else:
                    rows.append({"content": _request_log_safe(item)})
            return rows
    return []


def _prompt_from_fields(payload: dict[str, Any]) -> str:
    fields = payload.get("fields")
    if not isinstance(fields, list):
        return ""
    for item in fields:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() == "prompt":
            return _text_value(item.get("value"))
    return ""


def _prompt_from_payload(payload: dict[str, Any]) -> str:
    prompt = _text_value(_first_dict_value(payload, "prompt", "text"))
    if prompt:
        return prompt
    input_block = payload.get("input")
    if isinstance(input_block, dict):
        prompt = _text_value(_first_dict_value(input_block, "prompt", "text"))
        if prompt:
            return prompt
    content = payload.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                prompt = _text_value(item.get("text"))
                if prompt:
                    return prompt
    field_prompt = _prompt_from_fields(payload)
    if field_prompt:
        return field_prompt
    messages = _messages_from_payload(payload)
    if messages:
        user_parts: list[str] = []
        for item in messages:
            role = str(item.get("role") or "").strip().lower()
            if role and role not in {"user", "human"}:
                continue
            user_parts.extend(_extract_text_parts(item.get("content") or item.get("parts") or item))
        if user_parts:
            return "\n".join(user_parts)
    return ""


def _system_prompt_from_payload(payload: dict[str, Any]) -> str:
    direct = _text_value(_first_dict_value(payload, "system", "systemPrompt", "system_prompt", "instructions", "instruction"))
    if direct:
        return direct
    messages = _messages_from_payload(payload)
    for item in messages:
        role = str(item.get("role") or "").strip().lower()
        if role in {"system", "developer"}:
            parts = _extract_text_parts(item.get("content") or item.get("parts") or item)
            if parts:
                return "\n".join(parts)
    options = payload.get("options")
    if isinstance(options, dict):
        system_prompt = options.get("system_prompt") or options.get("systemPrompt")
        if isinstance(system_prompt, dict):
            append = _text_value(system_prompt.get("append"))
            if append:
                return append
        return _text_value(system_prompt)
    return ""


def _count_media(value: Any, media_keys: set[str]) -> int:
    if isinstance(value, dict):
        total = 0
        skip_nested_keys: set[str] = set()
        if "files" in value and "fileMetadata" in value and {"files", "fileMetadata"} <= media_keys:
            skip_nested_keys.add("fileMetadata")
        for key, item in value.items():
            key_text = str(key or "").strip()
            if key_text in skip_nested_keys:
                continue
            if key_text in media_keys:
                if isinstance(item, list):
                    total += len(item)
                elif item:
                    total += 1
                continue
            total += _count_media(item, media_keys)
        return total
    if isinstance(value, list):
        return sum(_count_media(item, media_keys) for item in value)
    return 0


def _seedance_family(model_name: str) -> str:
    text = str(model_name or "").strip().lower()
    if "seedance" not in text and "doubao" not in text:
        return ""
    if any(token in text for token in ("2.5", "2-5", "2_5", "2 5")):
        return "seedance-2.5"
    if any(token in text for token in ("2.0", "2-0", "2_0", "2 0")):
        return "seedance-2.0"
    return "seedance"


def _build_analysis_snapshot(
    request_data: Any,
    *,
    stage: str,
    provider_id: str = "",
    model_name: str = "",
    endpoint: str = "",
    blocked: bool = False,
) -> dict[str, Any]:
    request_root = request_data if isinstance(request_data, dict) else {}
    payload = _request_payload(request_data)
    prompt = _prompt_from_payload(payload)
    if not prompt:
        prompt = _text_value(request_root.get("prompt")) if isinstance(request_root, dict) else ""
    system_prompt = _system_prompt_from_payload(payload)
    messages = _messages_from_payload(payload)
    model = (
        _text_value(payload.get("model"))
        or _text_value(request_root.get("model") if isinstance(request_root, dict) else "")
        or model_name
    )
    provider = (
        _text_value(request_root.get("provider") if isinstance(request_root, dict) else "")
        or provider_id
    )
    parameters = {}
    for key in ("parameters", "generationConfig"):
        value = payload.get(key)
        if isinstance(value, dict):
            parameters = dict(value)
            break
    for key in ("ratio", "aspect_ratio", "duration", "resolution", "watermark", "generate_audio", "audio"):
        if key in payload:
            parameters.setdefault(key, payload.get(key))
    image_keys = {"image", "images", "image_url", "image_urls", "reference_image", "referenceImages", "reference_images", "fileMetadata", "files", "media"}
    video_keys = {"video", "videos", "video_url", "video_urls", "reference_video", "referenceVideos", "reference_videos"}
    snapshot = {
        "stage": stage,
        "providerId": provider_id,
        "provider": provider,
        "modelName": model_name or model,
        "model": model,
        "modelFamily": _seedance_family(model_name or model),
        "endpoint": endpoint,
        "blocked": bool(blocked),
        "transport": _text_value(request_root.get("transport") if isinstance(request_root, dict) else ""),
        "method": _text_value(request_root.get("method") if isinstance(request_root, dict) else ""),
        "url": _text_value(request_root.get("url") if isinstance(request_root, dict) else ""),
        "finalPrompt": prompt,
        "finalPromptChars": len(prompt),
        "systemPrompt": system_prompt,
        "systemPromptChars": len(system_prompt),
        "messages": messages,
        "messageCount": len(messages),
        "parameters": _request_log_safe(parameters),
        "referenceImageCount": _count_media(payload, image_keys),
        "referenceVideoCount": _count_media(payload, video_keys),
        "hasReferenceAudio": bool(_count_media(payload, {"audio_url", "audioUrls", "referenceAudio", "reference_audio", "reference_voice"})),
        "generateAudio": bool(parameters.get("generate_audio") or parameters.get("audio")),
    }
    return snapshot


def _base_log_document(
    *,
    schema_version: int,
    stage: str,
    created_at: str,
    project_id: str,
    episode_id: str,
    node_id: str,
    task_id: str,
    worker_name: str,
    phase: str,
    provider_id: str,
    model_name: str,
    endpoint: str,
    blocked: bool,
    source: str,
    should_background: bool,
    cleanup_result: dict[str, Any],
    call_id: str = "",
) -> dict[str, Any]:
    document = {
        "schemaVersion": schema_version,
        "stage": stage,
        "createdAt": created_at,
        "storedAt": created_at,
        "retentionHours": MODEL_LOG_RETENTION_HOURS,
        "projectId": project_id,
        "episodeId": str(episode_id or ""),
        "nodeId": str(node_id or ""),
        "taskId": str(task_id or ""),
        "workerName": str(worker_name or ""),
        "phase": str(phase or ""),
        "providerId": str(provider_id or ""),
        "modelName": str(model_name or ""),
        "endpoint": str(endpoint or ""),
        "blocked": bool(blocked),
        "source": str(source or ""),
        "writeMode": "background" if should_background else "sync",
        "cleanup": cleanup_result,
    }
    if call_id:
        document["callId"] = str(call_id or "")
    return document


def _snapshot_for_log(
    request_data: Any,
    *,
    stage: str,
    provider_id: str,
    model_name: str,
    endpoint: str,
    blocked: bool,
    analysis_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(analysis_snapshot, dict):
        return dict(analysis_snapshot)
    return _build_analysis_snapshot(
        request_data,
        stage=stage,
        provider_id=provider_id,
        model_name=model_name,
        endpoint=endpoint,
        blocked=blocked,
    )


def _provider_request_log_document(
    request_data: Any,
    *,
    attachment_dir: Path,
) -> Any:
    from utils.request_media_archive import copy_transport_archive, media_archive_writer

    writer = media_archive_writer(attachment_dir)
    if isinstance(request_data, dict) and isinstance(request_data.get("transportMedia"), list):
        request_data = {**request_data, "transportMedia": [
            copy_transport_archive(entry, attachment_dir) for entry in request_data["transportMedia"]
        ]}
    return _request_log_safe(request_data, media_writer=writer)


def _debug_snapshot_summary(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    summary = _request_log_safe(snapshot)
    if not isinstance(summary, dict):
        return {}
    for key in ("finalPrompt", "systemPrompt", "messages"):
        summary.pop(key, None)
    return summary


def _assembly_context_summary(assembly_context: Any) -> dict[str, Any]:
    if not isinstance(assembly_context, dict):
        return {}
    return {
        "available": True,
        "keys": sorted(str(key) for key in assembly_context.keys()),
    }


def _debug_log_document(
    *,
    stage: str,
    created_at: str,
    project_id: str,
    episode_id: str,
    node_id: str,
    task_id: str,
    worker_name: str,
    phase: str,
    provider_id: str,
    model_name: str,
    endpoint: str,
    blocked: bool,
    source: str,
    should_background: bool,
    cleanup_result: dict[str, Any],
    request_log_path: Path,
    request_log_markdown_path: Path | None,
    request_data: Any,
    analysis_snapshot: dict[str, Any] | None,
    assembly_context: dict[str, Any] | None,
    call_id: str = "",
) -> dict[str, Any]:
    snapshot = _snapshot_for_log(
        request_data,
        stage=stage,
        provider_id=str(provider_id or ""),
        model_name=str(model_name or ""),
        endpoint=str(endpoint or ""),
        blocked=blocked,
        analysis_snapshot=analysis_snapshot,
    )
    document = {
        **_base_log_document(
            schema_version=3,
            stage=stage,
            created_at=created_at,
            project_id=project_id,
            episode_id=episode_id,
            node_id=node_id,
            task_id=task_id,
            worker_name=worker_name,
            phase=phase,
            provider_id=provider_id,
            model_name=model_name,
            endpoint=endpoint,
            blocked=blocked,
            source=source,
            should_background=should_background,
            cleanup_result=cleanup_result,
            call_id=call_id,
        ),
        "logMode": "debug-summary",
        "providerRequestLog": _project_relative_path(project_id, request_log_path),
        "requestDataInDebugLog": False,
        "captureLevel": request_data.get("captureLevel", "application_submission") if isinstance(request_data, dict) else "application_submission",
        "requestDataNote": "请求记录单独保存在 providerRequestLog；captureLevel 区分应用提交与实际 API 出站，debug 仅为本地诊断摘要。",
        "analysisSnapshot": _debug_snapshot_summary(snapshot),
        "assemblyContext": _assembly_context_summary(assembly_context),
    }
    if request_log_markdown_path is not None:
        document["providerRequestMarkdown"] = _project_relative_path(project_id, request_log_markdown_path)
    return document


def _response_snapshot_summary(response_data: Any) -> dict[str, Any]:
    if isinstance(response_data, dict):
        text_parts = _extract_text_parts(response_data)
        summary: dict[str, Any] = {
            "type": "object",
            "keys": sorted(str(key) for key in response_data.keys())[:80],
            "textChars": len("\n".join(text_parts)),
        }
        usage = response_data.get("usage")
        if isinstance(usage, dict):
            summary["usage"] = _request_log_safe(usage)
        return summary
    if isinstance(response_data, list):
        return {"type": "array", "itemCount": len(response_data)}
    if isinstance(response_data, str):
        return {"type": "string", "chars": len(response_data)}
    if response_data is None:
        return {"type": "null"}
    return {"type": type(response_data).__name__}


def _provider_response_log_document(response_data: Any) -> Any:
    return response_data


def _debug_response_log_document(
    *,
    stage: str,
    created_at: str,
    project_id: str,
    episode_id: str,
    node_id: str,
    task_id: str,
    worker_name: str,
    phase: str,
    provider_id: str,
    model_name: str,
    endpoint: str,
    blocked: bool,
    source: str,
    should_background: bool,
    cleanup_result: dict[str, Any],
    response_log_path: Path,
    response_data: Any,
    call_id: str = "",
) -> dict[str, Any]:
    return {
        **_base_log_document(
            schema_version=1,
            stage=stage,
            created_at=created_at,
            project_id=project_id,
            episode_id=episode_id,
            node_id=node_id,
            task_id=task_id,
            worker_name=worker_name,
            phase=phase,
            provider_id=provider_id,
            model_name=model_name,
            endpoint=endpoint,
            blocked=blocked,
            source=source,
            should_background=should_background,
            cleanup_result=cleanup_result,
            call_id=call_id,
        ),
        "logMode": "response-debug-summary",
        "providerResponseLog": _project_relative_path(project_id, response_log_path),
        "responseDataInDebugLog": False,
        "responseDataNote": "文本模型供应商返回的原始响应数据已单独写入 providerResponseLog；debug 文件不重复保存完整响应体。",
        "responseSnapshot": _response_snapshot_summary(response_data),
    }


def _model_request_log_markdown_enabled() -> bool:
    text = str(os.environ.get(MODEL_REQUEST_LOG_MARKDOWN_ENV) or "").strip().lower()
    return text in {"1", "true", "yes", "on", "enabled"}


def _render_model_request_markdown(document: Any) -> str:
    # Keep production auto-exports and explicit prompt-log exports on one renderer.
    from utils.model_request_markdown import render_prompt_request_log

    return render_prompt_request_log(document)


def _write_json_document(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, default=str), encoding="utf-8", newline="\n")


def _write_model_request_log_files(path: Path, file_factory: Any, *, swallow_errors: bool) -> None:
    try:
        with log_directory_activity(path.parent):
            document, debug_path, debug_document, markdown_path, markdown_text = file_factory()
            _write_json_document(path, document)
            if isinstance(debug_document, dict):
                _write_json_document(debug_path, debug_document)
            if markdown_path is not None and markdown_text:
                markdown_path.parent.mkdir(parents=True, exist_ok=True)
                markdown_path.write_text(markdown_text, encoding="utf-8", newline="\n")
            # Readers only consume bundles carrying this marker. Partial writes
            # stay inspectable but can never masquerade as a complete request.
            _write_json_document(path.parent / "complete.json", {"schemaVersion": 1, "completedAt": _now_iso()})
    except Exception as exc:  # noqa: BLE001
        if not swallow_errors:
            raise
        print(f"[model-request-log] 写入失败: {path}: {exc}", file=sys.stderr, flush=True)


def _cleanup_model_log_roots(roots: list[Path], *, retention_seconds: int, now: float | None = None) -> dict[str, Any]:
    cutoff = (time.time() if now is None else now) - max(1, int(retention_seconds or MODEL_LOG_RETENTION_SECONDS))
    removed = 0
    removed_directories = 0
    errors: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        # Only traverse the explicitly selected log tree. Never follow a symlink
        # or a Windows junction into project media or another directory.
        resolved_root = root.resolve()
        if root.is_symlink() or resolved_root != root.absolute():
            errors.append(f"跳过重定向的日志目录：{root}")
            continue
        visited_directories: list[Path] = []
        for directory, subdirectories, files in os.walk(root, topdown=True, followlinks=False):
            parent = Path(directory)
            visited_directories.append(parent)
            subdirectories[:] = [name for name in subdirectories
                                  if not (parent / name).is_symlink()
                                  and (parent / name).resolve() == (parent / name).absolute()]
            for name in files:
                path = parent / name
                try:
                    if path.is_symlink() or not path.resolve().is_relative_to(resolved_root):
                        continue
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                        removed += 1
                except FileNotFoundError:
                    continue
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{path}: {exc}")
        for path in reversed(visited_directories):
            try:
                if path.is_symlink() or path.resolve() != path.absolute():
                    continue
                if remove_empty_log_directory(path):
                    removed_directories += 1
            except FileNotFoundError:
                continue
            except OSError as exc:
                # A concurrent logger may have populated this directory since
                # the emptiness check. Keep it and continue without waiting.
                if exc.errno in {errno.ENOTEMPTY, errno.EEXIST} or getattr(exc, "winerror", None) == 145:
                    continue
                errors.append(f"{path}: {exc}")
            except Exception as exc:
                errors.append(f"{path}: {exc}")
    return {"success": not errors, "removed": removed, "removedDirectories": removed_directories,
            "cutoff": datetime.fromtimestamp(cutoff, timezone.utc).isoformat(), "errors": errors[:8]}


def _run_startup_log_cleanup(started_at: float) -> None:
    global _STARTUP_CLEANUP_RESULT
    try:
        projects_root = PROJECTS_DIR.resolve()
        projects = [project for project in projects_root.iterdir()
                    if project.is_dir() and not project.is_symlink()
                    and project.resolve().parent == projects_root] if projects_root.exists() else []
        roots = [project / "debug" / name for project in projects
                 for name in ("model-request-logs", "model-response-logs")]
        result = _cleanup_model_log_roots(roots, retention_seconds=MODEL_LOG_RETENTION_SECONDS, now=started_at)
        result = {**result, "status": "completed", "trigger": "plugin-startup",
                  "retentionHours": MODEL_LOG_RETENTION_HOURS, "projects": len(projects)}
    except Exception as exc:
        result = {"success": False, "status": "failed", "trigger": "plugin-startup", "errors": [str(exc)]}
    with _STARTUP_CLEANUP_LOCK:
        _STARTUP_CLEANUP_RESULT = result


def cleanup_model_logs_on_startup() -> dict[str, Any]:
    """Schedule one maintenance thread and return without waiting for disk I/O."""
    global _STARTUP_CLEANUP_RESULT
    with _STARTUP_CLEANUP_LOCK:
        if _STARTUP_CLEANUP_RESULT is not None:
            return {**_STARTUP_CLEANUP_RESULT, "alreadyRan": True}
        started_at = time.time()
        _STARTUP_CLEANUP_RESULT = {"success": True, "status": "running", "trigger": "plugin-startup"}
        try:
            threading.Thread(
                target=_run_startup_log_cleanup, args=(started_at,),
                name="model-log-startup-cleanup", daemon=True,
            ).start()
        except Exception as exc:
            _STARTUP_CLEANUP_RESULT = {"success": False, "status": "failed", "trigger": "plugin-startup", "errors": [str(exc)]}
        return dict(_STARTUP_CLEANUP_RESULT)


def _record_path(root: Path, stage: str, task_id: str, call_id: str, name: str) -> Path:
    # call_id is a correlation ID, not a filename; retries may reuse it.
    record_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid.uuid4().hex
    task_group = _safe_path_part(task_id or call_id or "standalone", "standalone")
    return root / _safe_path_part(stage, "stage") / task_group / record_id / name


def write_model_request_log(
    project_id: str,
    stage: str,
    request_data: Any,
    *,
    episode_id: str = "",
    node_id: str = "",
    task_id: str = "",
    worker_name: str = "",
    phase: str = "",
    provider_id: str = "",
    model_name: str = "",
    endpoint: str = "",
    blocked: bool = False,
    source: str = "",
    analysis_snapshot: dict[str, Any] | None = None,
    assembly_context: dict[str, Any] | None = None,
    background: bool | None = None,
    call_id: str = "",
) -> dict[str, Any]:
    stage = str(stage or "").strip()
    project_id, project_error = _validate_project_id(project_id)
    if project_error:
        return {"success": False, "error": project_error}
    if not stage:
        return {"success": False, "error": "缺少 stage"}
    root = _project_log_root(project_id)
    created_at = _now_iso()
    log_id = call_id or uuid.uuid4().hex
    path = _record_path(root, stage, task_id or node_id, call_id, "request.json")
    # Freeze the business request before handing work to a background thread.
    try:
        request_data = copy.deepcopy(request_data)
        analysis_snapshot = copy.deepcopy(analysis_snapshot)
        assembly_context = copy.deepcopy(assembly_context)
    except Exception as exc:
        traceback.print_exc()
        return {"success": False, "error": str(exc)}
    debug_path = path.with_name(f"{path.stem}.debug.json")
    markdown_path = path.with_suffix(".md") if _model_request_log_markdown_enabled() else None
    should_background = (not bool(blocked)) if background is None else bool(background)

    def file_factory() -> tuple[Any, Path, dict[str, Any], Path | None, str]:
        cleanup_result = {"trigger": "plugin-startup", "performedOnWrite": False}
        request_document = _provider_request_log_document(
            request_data,
            attachment_dir=path.parent / "attachments",
        )
        debug_document = _debug_log_document(
            stage=stage,
            created_at=created_at,
            project_id=project_id,
            episode_id=episode_id,
            node_id=node_id,
            task_id=task_id,
            worker_name=worker_name,
            phase=phase,
            provider_id=provider_id,
            model_name=model_name,
            endpoint=endpoint,
            blocked=blocked,
            source=source,
            should_background=should_background,
            cleanup_result=cleanup_result,
            request_log_path=path,
            request_log_markdown_path=markdown_path,
            request_data=request_data,
            analysis_snapshot=analysis_snapshot,
            assembly_context=assembly_context,
            call_id=log_id,
        )
        markdown_text = _render_model_request_markdown(request_document) if markdown_path is not None else ""
        return request_document, debug_path, debug_document, markdown_path, markdown_text

    if should_background:
        try:
            thread = threading.Thread(
                target=_write_model_request_log_files,
                args=(path, file_factory),
                kwargs={"swallow_errors": True},
                # Media archives must finish on normal backend shutdown.
                daemon=False,
            )
            thread.start()
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}
    else:
        try:
            _write_model_request_log_files(path, file_factory, swallow_errors=False)
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "path": str(path),
        "relativePath": _project_relative_path(project_id, path),
        "debugPath": str(debug_path),
        "debugRelativePath": _project_relative_path(project_id, debug_path),
        **(
            {
                "markdownPath": str(markdown_path),
                "markdownRelativePath": _project_relative_path(project_id, markdown_path),
            }
            if markdown_path is not None
            else {}
        ),
        "stage": stage,
        "createdAt": created_at,
        "storedAt": created_at,
        "callId": log_id,
        "writeMode": "background" if should_background else "sync",
        "queued": bool(should_background),
        "persisted": not bool(should_background),
    }


def create_model_exchange_logger(project_id: str, *, source: str = "claude-agent-sdk", stage_prefix: str = "sdk"):
    """Bind SDK audit output to this project, never to a model-supplied path."""
    def record(exchange: dict[str, Any]) -> dict[str, Any]:
        request = exchange.get("requestInfo") or {}
        purpose = str(request.get("requestPurpose") or "sdk_generation")
        stage = stage_prefix + "-" + purpose.replace(":", "-")
        call_id = str(request.get("requestId") or uuid.uuid4().hex)
        body = request.get("requestBody") or {}
        model = str(body.get("model") or (request.get("options") or {}).get("model") or "")
        common = {"source": source, "call_id": call_id, "model_name": model,
                  "endpoint": str(request.get("url") or "ClaudeSDKClient.query")}
        request_log = write_model_request_log(project_id, stage, request, **common)
        logs: dict[str, Any] = {"request": request_log}
        if not exchange.get("applicationOnly"):
            # Keep one copy of the request body in the request archive.
            response = {key: value for key, value in exchange.items() if key != "requestInfo"}
            response.update({key: request[key] for key in (
                "captureLevel", "captureSource", "requestPurpose", "requestId", "parentRequestId"
            ) if key in request})
            logs["response"] = write_model_response_log(project_id, stage, response, **common)
        failures = [value.get("error") for value in logs.values() if not value.get("success")]
        if failures:
            raise RuntimeError("; ".join(str(value) for value in failures))
        return logs

    return record


def write_model_response_log(
    project_id: str,
    stage: str,
    response_data: Any,
    *,
    episode_id: str = "",
    node_id: str = "",
    task_id: str = "",
    worker_name: str = "",
    phase: str = "",
    provider_id: str = "",
    model_name: str = "",
    endpoint: str = "",
    blocked: bool = False,
    source: str = "",
    background: bool | None = None,
    call_id: str = "",
) -> dict[str, Any]:
    stage = str(stage or "").strip()
    project_id, project_error = _validate_project_id(project_id)
    if project_error:
        return {"success": False, "error": project_error}
    if not stage:
        return {"success": False, "error": "缺少 stage"}
    root = _project_response_log_root(project_id)
    created_at = _now_iso()
    log_id = call_id or uuid.uuid4().hex
    path = _record_path(root, stage, task_id or node_id, call_id, "response.json")
    try:
        response_data = copy.deepcopy(response_data)
    except Exception as exc:
        traceback.print_exc()
        return {"success": False, "error": str(exc)}
    debug_path = path.with_name(f"{path.stem}.debug.json")
    should_background = (not bool(blocked)) if background is None else bool(background)

    def file_factory() -> tuple[Any, Path, dict[str, Any], None, str]:
        cleanup_result = {"trigger": "plugin-startup", "performedOnWrite": False}
        response_document = _provider_response_log_document(response_data)
        debug_document = _debug_response_log_document(
            stage=stage,
            created_at=created_at,
            project_id=project_id,
            episode_id=episode_id,
            node_id=node_id,
            task_id=task_id,
            worker_name=worker_name,
            phase=phase,
            provider_id=provider_id,
            model_name=model_name,
            endpoint=endpoint,
            blocked=blocked,
            source=source,
            should_background=should_background,
            cleanup_result=cleanup_result,
            response_log_path=path,
            response_data=response_data,
            call_id=log_id,
        )
        return response_document, debug_path, debug_document, None, ""

    if should_background:
        try:
            thread = threading.Thread(
                target=_write_model_request_log_files,
                args=(path, file_factory),
                kwargs={"swallow_errors": True},
                daemon=False,
            )
            thread.start()
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}
    else:
        try:
            _write_model_request_log_files(path, file_factory, swallow_errors=False)
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "path": str(path),
        "relativePath": _project_relative_path(project_id, path),
        "debugPath": str(debug_path),
        "debugRelativePath": _project_relative_path(project_id, debug_path),
        "stage": stage,
        "createdAt": created_at,
        "storedAt": created_at,
        "callId": log_id,
        "writeMode": "background" if should_background else "sync",
        "queued": bool(should_background),
        "persisted": not bool(should_background),
    }


def model_request_log_reference(
    log_result: dict[str, Any] | None,
    *,
    phase: str = "",
) -> dict[str, Any]:
    if not isinstance(log_result, dict) or not log_result.get("success"):
        return {}
    reference = {
        "stage": log_result.get("stage"),
        "relativePath": log_result.get("relativePath"),
        "phase": phase,
        "writeMode": log_result.get("writeMode"),
        "queued": bool(log_result.get("queued")),
        "persisted": bool(log_result.get("persisted")),
    }
    if log_result.get("debugRelativePath"):
        reference["debugRelativePath"] = log_result.get("debugRelativePath")
    if log_result.get("markdownRelativePath"):
        reference["markdownRelativePath"] = log_result.get("markdownRelativePath")
    if log_result.get("callId"):
        reference["callId"] = log_result.get("callId")
    return reference


def model_response_log_reference(
    log_result: dict[str, Any] | None,
    *,
    phase: str = "",
) -> dict[str, Any]:
    if not isinstance(log_result, dict) or not log_result.get("success"):
        return {}
    reference = {
        "stage": log_result.get("stage"),
        "relativePath": log_result.get("relativePath"),
        "phase": phase,
        "writeMode": log_result.get("writeMode"),
        "queued": bool(log_result.get("queued")),
        "persisted": bool(log_result.get("persisted")),
    }
    if log_result.get("debugRelativePath"):
        reference["debugRelativePath"] = log_result.get("debugRelativePath")
    if log_result.get("callId"):
        reference["callId"] = log_result.get("callId")
    return reference
