# -*- coding: utf-8 -*-
"""基础 JSON 存储、事件派发、目录初始化和通用合并工具。"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import random
import re
import shutil
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any

from utils.agent_context import (
    AGENT_CONTEXT_MESSAGE_TEXT_LIMIT,
    AGENT_CONTEXT_RECENT_WINDOW,
    AGENT_CONTEXT_SUMMARY_CHARS,
    build_agent_conversation_context,
)
from utils import agent_sdk_runtime
from utils.agent_session_service import AgentSessionService
from utils.aspect_size import (
    IMAGE_TIER_SHORT_EDGE,
    VIDEO_TIER_SHORT_EDGE,
    aspect_size,
    parse_aspect_ratio,
    resolution_to_short_edge,
)
from utils.image_pipeline import (
    convert_image_bytes_to_png,
    data_url_from_bytes,
    prepare_provider_image_bytes,
    prepare_provider_image_data_uri,
    save_project_image,
    save_provider_output_image,
)
from utils.media_backends import (
    cancel_video_media_job,
    endpoint_supports_media_generation,
    infer_model_endpoint,
    media_endpoint_type,
    normalize_media_endpoint,
    generate_image_media,
    generate_video_media,
    poll_video_media_job,
    provider_supports_media_generation,
    submit_video_media_job,
)


from .catalogs import DEFAULT_ASSETS
from .catalogs import DEFAULT_GLOBAL_CONFIG
from .catalogs import DEFAULT_MODEL_CAPABILITIES
from .catalogs import DEFAULT_PROVIDER_PRESETS
from .catalogs import DEFAULT_SCRIPT_ADAPTATION_TEMPLATES
from .catalogs import DEFAULT_STYLE_TEMPLATES
from .catalogs import DEFAULT_TEXT_REPLACEMENT_RULES
from .catalogs import FAVORITE_STYLE_THUMBNAILS_DIR
from .catalogs import GLOBAL_ASSETS_PATH
from .catalogs import GLOBAL_ASSET_MEDIA_DIR
from .catalogs import GLOBAL_CONFIG_PATH
from .catalogs import GLOBAL_DIR
from .catalogs import GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH
from .catalogs import GLOBAL_STYLE_TEMPLATES_PATH
from .catalogs import GLOBAL_TASKS_PATH
from .catalogs import GLOBAL_TEXT_REPLACEMENT_RULES_PATH
from .catalogs import GLOBAL_USAGE_PATH
from .catalogs import PROJECTS_DIR
from .catalogs import STYLE_THUMBNAILS_DIR
from .runtime_state import _AGENT_EVENT_EMITTER

_JSON_WRITE_LOCK = threading.RLock()
_GLOBAL_CONFIG_UPDATE_LOCK = threading.RLock()
_PROJECT_CONFIG_LOCKS_GUARD = threading.Lock()
_PROJECT_CONFIG_LOCKS: dict[str, threading.RLock] = {}


def _serialized_project_config_write(function):
    """Serialize each project's config.json read-modify-write transaction."""
    @wraps(function)
    def wrapped(project_id: str, *args: Any, **kwargs: Any):
        lock_key = str(project_id).strip().casefold()
        with _PROJECT_CONFIG_LOCKS_GUARD:
            lock = _PROJECT_CONFIG_LOCKS.setdefault(lock_key, threading.RLock())
        with lock:
            return function(project_id, *args, **kwargs)
    return wrapped


def _serialized_global_config_write(function):
    """Keep a global config read-modify-write operation indivisible in this process."""
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any):
        with _GLOBAL_CONFIG_UPDATE_LOCK:
            return function(*args, **kwargs)
    return wrapped


def _display_time(iso_value: str | None) -> str:
    if not iso_value:
        return "刚刚"
    try:
        dt = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
    except ValueError:
        return str(iso_value)
    return dt.astimezone().strftime("%m-%d %H:%M")


def _normalize_asset_type_key(asset_type: Any) -> str | None:
    if not isinstance(asset_type, str):
        return None
    key = asset_type.strip()
    return key if key in DEFAULT_ASSETS else None


ASSET_LIFECYCLE_ACTIVE = "active"
ASSET_LIFECYCLE_OFFLINE = "offline"
ASSET_LIFECYCLE_ALL = "all"
ASSET_LIFECYCLE_FILTERS = {
    ASSET_LIFECYCLE_ACTIVE,
    ASSET_LIFECYCLE_OFFLINE,
    ASSET_LIFECYCLE_ALL,
}


def _normalize_asset_lifecycle_status(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return ASSET_LIFECYCLE_OFFLINE if text == ASSET_LIFECYCLE_OFFLINE else ASSET_LIFECYCLE_ACTIVE


def _normalize_asset_lifecycle_filter(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return text if text in ASSET_LIFECYCLE_FILTERS else ASSET_LIFECYCLE_ALL


def _asset_lifecycle_status(item: Any) -> str:
    if not isinstance(item, dict):
        return ASSET_LIFECYCLE_ACTIVE
    return _normalize_asset_lifecycle_status(
        item.get("lifecycleStatus") if "lifecycleStatus" in item else item.get("lifecycle_status")
    )


def _asset_is_offline(item: Any) -> bool:
    return _asset_lifecycle_status(item) == ASSET_LIFECYCLE_OFFLINE


def _asset_lifecycle_matches(item: Any, lifecycle_status: Any) -> bool:
    lifecycle_filter = _normalize_asset_lifecycle_filter(lifecycle_status)
    if lifecycle_filter == ASSET_LIFECYCLE_ALL:
        return True
    return _asset_lifecycle_status(item) == lifecycle_filter


def _asset_lifecycle_patch_value(patch: Any) -> Any:
    if not isinstance(patch, dict):
        return None
    if "lifecycleStatus" in patch:
        return patch.get("lifecycleStatus")
    if "lifecycle_status" in patch:
        return patch.get("lifecycle_status")
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_asset_lifecycle_status(item: dict[str, Any], status: Any) -> bool:
    before = json.dumps(
        {
            "lifecycleStatus": item.get("lifecycleStatus"),
            "lifecycle_status": item.get("lifecycle_status"),
            "offlineAt": item.get("offlineAt"),
            "offline_at": item.get("offline_at"),
            "lifecycleChangedAt": item.get("lifecycleChangedAt"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    normalized = _normalize_asset_lifecycle_status(status)
    item.pop("lifecycle_status", None)
    item.pop("offline_at", None)
    if normalized == ASSET_LIFECYCLE_OFFLINE:
        item["lifecycleStatus"] = ASSET_LIFECYCLE_OFFLINE
        item.setdefault("offlineAt", _now())
    else:
        item.pop("lifecycleStatus", None)
        item.pop("offlineAt", None)
    item["lifecycleChangedAt"] = _now()
    after = json.dumps(
        {
            "lifecycleStatus": item.get("lifecycleStatus"),
            "offlineAt": item.get("offlineAt"),
            "lifecycleChangedAt": item.get("lifecycleChangedAt"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return before != after


def _asset_row_for_response(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    row = copy.deepcopy(item)
    row["lifecycleStatus"] = _asset_lifecycle_status(row)
    return row


def _filter_asset_store_by_lifecycle(data: Any, lifecycle_status: Any) -> dict[str, Any]:
    lifecycle_filter = _normalize_asset_lifecycle_filter(lifecycle_status)
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULT_ASSETS)
    result = copy.deepcopy(data)
    for asset_type in ("characters", "creatures", "scenes", "props"):
        rows = result.get(asset_type)
        if not isinstance(rows, list):
            result[asset_type] = []
            continue
        result[asset_type] = [
            item
            for item in rows
            if isinstance(item, dict) and _asset_lifecycle_matches(item, lifecycle_filter)
        ]
    return result


def _read_json(path: Path, default: Any) -> Any:
    if path.name in {"assets.json", "source_coverage.json"}:
        from .asset_analysis_commit import recover_asset_analysis_for_path
        with _JSON_WRITE_LOCK:
            recover_asset_analysis_for_path(path)
            return _read_json_file(path, default)
    return _read_json_file(path, default)


def _read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    with path.open("r", encoding="utf-8-sig") as fp:
        return json.load(fp)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    with _JSON_WRITE_LOCK:
        try:
            if path.name in {"assets.json", "source_coverage.json"}:
                from .asset_analysis_commit import recover_asset_analysis_for_path
                recover_asset_analysis_for_path(path)
            with tmp.open("w", encoding="utf-8", newline="\n") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
                fp.write("\n")
            last_error: OSError | None = None
            for attempt in range(8):
                try:
                    tmp.replace(path)
                    return
                except OSError as exc:
                    last_error = exc
                    if getattr(exc, "winerror", None) not in {5, 32}:
                        raise
                    time.sleep(0.05 * (attempt + 1))
            if last_error is not None:
                raise last_error
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


def _ensure_builtin_template_catalog(path: Path, defaults: list[dict[str, Any]]) -> None:
    if not path.exists():
        _write_json(path, defaults)
        return
    try:
        rows = _read_json(path, [])
    except Exception as exc:
        print(f"[store] failed to migrate builtin templates {path}: {exc}", flush=True)
        return
    if not isinstance(rows, list):
        return
    default_ids = {str(item.get("id") or "") for item in defaults if isinstance(item, dict)}
    custom_rows = [
        copy.deepcopy(item)
        for item in rows
        if not (isinstance(item, dict) and str(item.get("id") or "") in default_ids)
    ]
    next_rows = [copy.deepcopy(item) for item in defaults] + custom_rows
    if next_rows != rows:
        _write_json(path, next_rows)


def _normalize_text_replacement_rules(value: Any) -> list[dict[str, str]]:
    rows: list[Any]
    if isinstance(value, dict):
        rows = value.get("rules") if isinstance(value.get("rules"), list) else value.get("replacements")
        rows = rows if isinstance(rows, list) else [value]
    elif isinstance(value, str):
        rows = [line for line in re.split(r"\r?\n", value) if line.strip()]
    elif isinstance(value, list):
        rows = value
    else:
        rows = []

    normalized: list[dict[str, str]] = []
    for row in rows:
        if isinstance(row, dict):
            if not any(key in row for key in ("from", "source", "original", "pattern")) and (
                isinstance(row.get("replacements"), list) or isinstance(row.get("rules"), list)
            ):
                nested = row.get("replacements") if isinstance(row.get("replacements"), list) else row.get("rules")
                for item in _normalize_text_replacement_rules(nested):
                    if item not in normalized:
                        normalized.append(item)
                continue
            source = str(row.get("from") or row.get("source") or row.get("original") or row.get("pattern") or "").strip()
            target = str(row.get("to") or row.get("target") or row.get("replacement") or "").strip()
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            source = str(row[0] or "").strip()
            target = str(row[1] or "").strip()
        elif isinstance(row, str):
            parts = re.split(r"\s*(?:=>|->|=|：|:)\s*", row.strip(), maxsplit=1)
            if len(parts) != 2:
                continue
            source, target = parts[0].strip(), parts[1].strip()
        else:
            continue
        if not source or not target:
            continue
        try:
            re.compile(source)
        except re.error:
            continue
        item = {"from": source[:120], "to": target[:120]}
        if item not in normalized:
            normalized.append(item)
        if len(normalized) >= 200:
            break
    return normalized


def set_agent_event_emitter(emitter: Any | None) -> None:
    global _AGENT_EVENT_EMITTER
    _AGENT_EVENT_EMITTER = emitter if callable(emitter) else None


_TASK_EVENT_NAMES = {
    "task_created",
    "task_progress",
    "task_completed",
    "task_failed",
    "task_cancelled",
}
_TASK_LIKE_EVENT_NAMES = _TASK_EVENT_NAMES | {
    "home_archive_completed",
    "home_archive_failed",
    "jianying_export_completed",
    "jianying_export_failed",
}
_EVENT_TEXT_LIMIT = 1200
_EVENT_DEBUG_TEXT_LIMIT = 6000
_EVENT_TASK_SUMMARY_KEYS = {
    "id",
    "type",
    "clientRequestId",
    "promptOperation",
    "projectId",
    "project_id",
    "episodeId",
    "episode_id",
    "nodeId",
    "node_id",
    "nodeType",
    "node_type",
    "generationTaskType",
    "generation_task_type",
    "generationTaskNodeId",
    "generation_task_node_id",
    "versionId",
    "version_id",
    "routeId",
    "route_id",
    "routeLabel",
    "route_label",
    "workChainId",
    "work_chain_id",
    "workChainLabel",
    "work_chain_label",
    "workChainTitle",
    "work_chain_title",
    "workChainName",
    "work_chain_name",
    "segmentId",
    "segment_id",
    "strategy",
    "modelId",
    "model_id",
    "providerId",
    "provider_id",
    "assetType",
    "asset_type",
    "assetId",
    "asset_id",
    "assetName",
    "asset_name",
    "assetScope",
    "asset_scope",
    "assetRangeId",
    "asset_range_id",
    "agentAction",
    "agent_action",
    "workerName",
    "worker_name",
    "workerRunId",
    "worker_run_id",
    "parentSessionId",
    "parent_session_id",
    "sessionId",
    "session_id",
    "executionId",
    "imageEditKind",
    "image_edit_kind",
    "estimatedCost",
    "estimated_cost",
    "consumedCost",
    "consumed_cost",
    "elapsedMs",
    "elapsed_ms",
    "durationMs",
    "duration_ms",
    "startedAt",
    "started_at",
    "updatedAt",
    "updated_at",
    "completedAt",
    "completed_at",
    "failedAt",
    "failed_at",
    "cancelledAt",
    "cancelled_at",
    "cancelled",
    "notificationClearedAt",
    "notification_cleared_at",
    "status",
    "progress",
    "message",
    "notice",
    "error",
    "failureReason",
    "failure_reason",
    "errorSummary",
    "error_summary",
    "providerResponseSummary",
    "provider_response_summary",
    "errorDebug",
    "error_debug",
    "traceback",
    "stackTrace",
    "stack_trace",
    "focusTarget",
    "focus_target",
    "projectEffect",
    "project_effect",
    "createdAt",
    "created_at",
    "exportPath",
    "export_path",
    "importPath",
    "import_path",
    "draftPath",
    "draft_path",
    "workflowVersion",
    "workflow_version",
    "txId",
    "tx_id",
    "seq",
    "revision",
    "baseRevision",
    "base_revision",
    "opType",
    "op_type",
    "records",
    "changedResources",
    "changed_resources",
    "documentExtras",
    "document_extras",
    "productionStatus",
    "production_status",
}
_EVENT_TASK_TEXT_KEYS = {
    "message",
    "notice",
    "error",
    "failureReason",
    "failure_reason",
    "errorSummary",
    "error_summary",
    "providerResponseSummary",
    "provider_response_summary",
    "errorDebug",
    "error_debug",
    "traceback",
    "stackTrace",
    "stack_trace",
}
_EVENT_TASK_DEBUG_TEXT_KEYS = {"errorDebug", "error_debug", "traceback", "stackTrace", "stack_trace"}
_EVENT_WORKER_RUN_KEYS = {
    "id",
    "executionId",
    "workerRunId",
    "worker_run_id",
    "workerName",
    "worker_name",
    "status",
    "progress",
    "stage",
    "cyclePhase",
    "message",
    "notice",
    "typeProgress",
    "type_progress",
    "parallelTypeCycles",
    "parallel_type_cycles",
    "sessionId",
    "session_id",
    "assetRangeId",
    "asset_range_id",
    "error",
}
_EVENT_TASK_RESULT_KEYS = {
    "draftVideoPrompt",
    "assetNameMap",
    "promptBindings",
    "shots",
    "videoDurationSyncWarning",
    "videoDurationSyncWarnings",
    "nodeId",
    "node_id",
    "node",
    "resultNode",
    "result_node",
    "versionId",
    "version_id",
    "version",
    "media",
    "assetId",
    "asset_id",
    "assetType",
    "asset_type",
    "asset",
    "workflowVersion",
    "workflow_version",
    "productionStatus",
    "production_status",
    "skipped",
    "imageEditKind",
    "image_edit_kind",
    "txId",
    "tx_id",
    "seq",
    "revision",
    "baseRevision",
    "base_revision",
    "opType",
    "op_type",
    "records",
    "changedResources",
    "changed_resources",
    "documentExtras",
    "document_extras",
}
_EVENT_VERSION_KEYS = {
    "id",
    "type",
    "title",
    "summary",
    "source",
    "status",
    "media",
    "model",
    "provider",
    "createdAt",
    "created_at",
    "updatedAt",
    "updated_at",
    "completedAt",
    "completed_at",
    "workflowVersion",
    "workflow_version",
    "txId",
    "tx_id",
    "seq",
    "revision",
    "baseRevision",
    "base_revision",
    "opType",
    "op_type",
    "records",
    "changedResources",
    "changed_resources",
    "documentExtras",
    "document_extras",
    "failedAt",
    "failed_at",
}
_EVENT_INLINE_MEDIA_KEYS = {
    "base64",
    "bytes",
    "dataurl",
    "datauri",
    "imagedata",
    "imagebytes",
    "imagebase64",
    "imagedataurl",
    "inputimagedataurl",
    "outputimagedataurl",
    "pngdataurl",
    "storedpngdataurl",
    "videodata",
    "videobytes",
    "videobase64",
}
_PROJECT_CHANGED_DROP_KEYS = {
    "project",
    "workflow",
    "videojob",
    "providerrequest",
    "generationdebug",
    "debug",
    "payload",
}
_LOCAL_CANVAS_PROJECT_CHANGE_ACTIONS = {
    "canvas_result_committed",
    "workflow_input_linked",
    "workflow_input_unlinked",
    "workflow_media_imported",
    "workflow_asset_nodes_added",
    "workflow_task_card_created",
    "workflow_item_upserted",
    "workflow_route_updated",
    "workflow_item_deleted",
    "workflow_node_layout_updated",
    "workflow_node_inline_saved",
    "canvas_asset_images_resolved",
    "workflow_node_generated",
    "workflow_cinematic_script_generated",
    "workflow_batch_generated",
    "workflow_variant_selected",
    "workflow_node_preflight_checked",
    "storyboard_image_requested",
    "storyboard_image_generated",
    "storyboard_image_edited",
    "storyboard_image_edit_completed",
    "storyboard_image_edit_failed",
    "storyboard_result_version_activated",
    "storyboard_version_deleted",
    "visual_handoff_image_generated",
    "visual_handoff_cross_episode_imported",
    "visual_handoff_cross_episode_linked",
    "storyboard_video_requested",
    "storyboard_video_generated",
    "route_video_requested",
    "route_video_generated",
    "variant_quality_result_saved",
    "variant_quality_auto_reviewed",
    "shot_prompt_patched",
    "episode_production_status_updated",
    "node_edit_history_restored",
    "node_edit_history_deleted",
    "agent_split_completed",
}
_EVENT_CANVAS_CHANGED_RESOURCE_ALIASES = {
    "workflow": "",
    "workflow_card": "canvas_node",
    "workflow_cards": "canvas_node",
    "workflow_node": "canvas_node",
    "workflow_nodes": "canvas_node",
    "workflow_node_inline": "canvas_node",
    "workflow_node_layout": "canvas_node",
    "workflow_media": "canvas_node",
    "canvas_card": "canvas_node",
    "canvas_cards": "canvas_node",
    "workflow_edge": "canvas_edge",
    "workflow_edges": "canvas_edge",
    "workflow_route": "canvas_route",
    "workflow_routes": "canvas_route",
    "workflow_work_chain": "canvas_work_chain",
    "workflow_work_chains": "canvas_work_chain",
    "workflow_task": "canvas_task",
    "workflow_tasks": "canvas_task",
    "task": "canvas_task",
    "tasks": "canvas_task",
    "workflow_version": "canvas_version",
    "workflow_versions": "canvas_version",
    "version": "canvas_version",
    "versions": "canvas_version",
    "workflow_asset_refs": "canvas_projection",
}
_EVENT_PROJECT_EFFECT_KEY_TOKENS = {
    "action",
    "type",
    "projectid",
    "episodeid",
    "episodeids",
    "scope",
    "conversationid",
    "workflowid",
    "sessionid",
    "changedresources",
    "focustarget",
    "notice",
    "message",
    "error",
    "assettype",
    "assetid",
    "assetname",
    "asset",
    "workflowassetsync",
}
_EVENT_PROJECT_EFFECT_TEXT_TOKENS = {"notice", "message", "error"}


def _event_key_token(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key or "").lower())


def _event_clean_text(value: Any, limit: int = _EVENT_TEXT_LIMIT) -> str:
    text = str(value or "").strip()
    if not text or text == "NoneType: None":
        return ""
    text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,}\]]+", r"\1<redacted>", text)
    text = re.sub(
        r"(?i)((?:api[_-]?key|apiKey|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+",
        r"\1<redacted>",
        text,
    )
    text = re.sub(r"\s+\n", "\n", text).strip()
    if len(text) > limit:
        return f"{text[:limit].rstrip()}...（已截断）"
    return text


def _event_canvas_changed_resource_name(value: Any) -> str:
    resource = str(value or "").strip()
    return _EVENT_CANVAS_CHANGED_RESOURCE_ALIASES.get(resource, resource)


def _event_normalize_changed_resources(resources: Any) -> list[str]:
    if resources is None:
        return []
    rows = resources if isinstance(resources, (list, tuple, set)) else [resources]
    normalized: list[str] = []
    for item in rows:
        resource = _event_canvas_changed_resource_name(item)
        if resource and resource not in normalized:
            normalized.append(resource)
    return normalized


def _event_is_inline_media_string(value: str) -> bool:
    return value.lstrip().lower().startswith("data:")


def _event_looks_like_large_base64(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    if len(compact) < 1024 or len(compact) % 4 != 0:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact))


def _compact_event_value(value: Any, *, key: Any = None) -> Any:
    token = _event_key_token(key)
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_token = _event_key_token(child_key)
            if child_token in _EVENT_INLINE_MEDIA_KEYS:
                continue
            if child_token == "preview" and isinstance(child_value, str) and _event_is_inline_media_string(child_value):
                continue
            if child_token == "data" and isinstance(child_value, str):
                if _event_is_inline_media_string(child_value) or _event_looks_like_large_base64(child_value):
                    continue
            cleaned[child_key] = _compact_event_value(child_value, key=child_key)
        return cleaned
    if isinstance(value, list):
        return [_compact_event_value(item, key=key) for item in value]
    if isinstance(value, str):
        if _event_is_inline_media_string(value):
            return "<redacted-inline-media>"
        if token == "data" and _event_looks_like_large_base64(value):
            return "<redacted-binary-media>"
    return copy.deepcopy(value)


def _compact_event_worker_run(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    summary: dict[str, Any] = {}
    for key in _EVENT_WORKER_RUN_KEYS:
        if key in value:
            item = value.get(key)
            summary[key] = _event_clean_text(item) if key in _EVENT_TASK_TEXT_KEYS else _compact_event_value(item, key=key)
    return summary or None


def _compact_event_version(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    summary: dict[str, Any] = {}
    for key in _EVENT_VERSION_KEYS:
        if key in value:
            item = value.get(key)
            if key in {"changedResources", "changed_resources"}:
                summary["changedResources"] = _event_normalize_changed_resources(item)
            else:
                summary[key] = _event_clean_text(item) if key in {"summary", "title"} else _compact_event_value(item, key=key)
    return summary or None


def _compact_event_task_result(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    summary: dict[str, Any] = {}
    for key in _EVENT_TASK_RESULT_KEYS:
        if key not in value:
            continue
        item = value.get(key)
        if key in {"version"}:
            version = _compact_event_version(item)
            if version:
                summary[key] = version
        elif key in {"changedResources", "changed_resources"}:
            summary["changedResources"] = _event_normalize_changed_resources(item)
        else:
            summary[key] = _compact_event_value(item, key=key)
    return summary or None


def _compact_event_project_effect(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        token = _event_key_token(key)
        if token not in _EVENT_PROJECT_EFFECT_KEY_TOKENS:
            continue
        if token in _EVENT_PROJECT_EFFECT_TEXT_TOKENS:
            cleaned[key] = _event_clean_text(item)
        elif token == "changedresources" and isinstance(item, list):
            cleaned["changedResources"] = _event_normalize_changed_resources(item)
        else:
            cleaned[key] = _compact_event_value(item, key=key)
    return cleaned or None


def _compact_task_event_payload(task: Any) -> dict[str, Any]:
    if not isinstance(task, dict):
        return {}
    row: dict[str, Any] = {}
    for key in _EVENT_TASK_SUMMARY_KEYS:
        if key not in task:
            continue
        item = task.get(key)
        if key in _EVENT_TASK_TEXT_KEYS:
            limit = _EVENT_DEBUG_TEXT_LIMIT if key in _EVENT_TASK_DEBUG_TEXT_KEYS else _EVENT_TEXT_LIMIT
            row[key] = _event_clean_text(item, limit)
        elif key in {"projectEffect", "project_effect"}:
            effect = _compact_event_project_effect(item)
            if effect:
                row[key] = effect
        elif key in {"changedResources", "changed_resources"}:
            row["changedResources"] = _event_normalize_changed_resources(item)
        else:
            row[key] = _compact_event_value(item, key=key)

    focus_target = task.get("focusTarget") if isinstance(task.get("focusTarget"), dict) else task.get("focus_target")
    if isinstance(focus_target, dict):
        row.setdefault("focusTarget", _compact_event_value(focus_target, key="focusTarget"))

    worker_run = _compact_event_worker_run(task.get("workerRun") or task.get("worker_run"))
    if worker_run:
        row["workerRun"] = worker_run
        row.setdefault("workerName", worker_run.get("workerName") or worker_run.get("worker_name"))
        row.setdefault("workerRunId", worker_run.get("workerRunId") or worker_run.get("worker_run_id"))

    job = task.get("videoJob") if isinstance(task.get("videoJob"), dict) else {}
    if job:
        row.setdefault("versionId", job.get("versionId") or job.get("version_id"))
        row.setdefault("providerId", job.get("providerId") or job.get("provider_id"))
        row.setdefault("modelId", job.get("modelId") or job.get("model_id") or job.get("modelName"))

    result = _compact_event_task_result(task.get("result"))
    if result:
        row["result"] = result
    version = _compact_event_version(task.get("version"))
    if version:
        row["version"] = version
    if isinstance(task.get("asset"), dict):
        row["asset"] = _compact_event_value(task.get("asset"), key="asset")
    if isinstance(task.get("media"), dict):
        row["media"] = _compact_event_value(task.get("media"), key="media")
    return {key: value for key, value in row.items() if value is not None}


def _compact_project_changed_payload(payload: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    workflow_omitted = False
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    project_id = payload.get("projectId") or payload.get("project_id") or project.get("id")
    for key, value in payload.items():
        token = _event_key_token(key)
        if token == "workflow":
            workflow_omitted = True
            continue
        if token == "project":
            continue
        if token == "task":
            row[key] = _compact_task_event_payload(value)
            continue
        if token == "tasks" and isinstance(value, list):
            row[key] = [_compact_task_event_payload(item) if isinstance(item, dict) else _compact_event_value(item, key=key) for item in value]
            continue
        if token == "projecteffect":
            effect = _compact_event_project_effect(value)
            if effect:
                row[key] = effect
            continue
        if token == "changedresources":
            row["changedResources"] = _event_normalize_changed_resources(value)
            continue
        if token in _PROJECT_CHANGED_DROP_KEYS:
            continue
        row[key] = _event_clean_text(value) if key in {"message", "notice", "error"} else _compact_event_value(value, key=key)
    if project_id:
        row["projectId"] = project_id
    if workflow_omitted:
        changed = _event_normalize_changed_resources(
            row.get("changedResources") or row.get("changed_resources") or []
        )
        if not changed:
            action = str(row.get("action") or payload.get("action") or "").strip()
            changed.append(
                "canvas_document"
                if action in _LOCAL_CANVAS_PROJECT_CHANGE_ACTIONS
                else "workflow"
            )
        row["changedResources"] = changed
        row["workflowOmitted"] = True
    return row


def _compact_event_payload_dict(payload: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in payload.items():
        token = _event_key_token(key)
        if token in _PROJECT_CHANGED_DROP_KEYS:
            continue
        if token == "task":
            row[key] = _compact_task_event_payload(value)
        elif token == "tasks" and isinstance(value, list):
            row[key] = [_compact_task_event_payload(item) if isinstance(item, dict) else _compact_event_value(item, key=key) for item in value]
        elif token == "projecteffect":
            effect = _compact_event_project_effect(value)
            if effect:
                row[key] = effect
        elif token == "changedresources":
            row["changedResources"] = _event_normalize_changed_resources(value)
        else:
            row[key] = _compact_event_value(value, key=key)
    return row


def compact_agent_event_payload(event_name: str, payload: Any | None = None) -> dict[str, Any]:
    # 后端通知前端/主程序的统一消息处理接口。
    # 任务存储可保留完整调试数据，但协议事件只能发送前端可展示的摘要；
    # 新增事件发送路径必须走 _emit_agent_event 或 handlers._send_event，不能直接发送完整 task。
    if not isinstance(payload, dict):
        return {}
    normalized_event_name = str(event_name or "").strip()
    if normalized_event_name in _TASK_LIKE_EVENT_NAMES:
        return _compact_task_event_payload(payload)
    if normalized_event_name == "project_changed":
        return _compact_project_changed_payload(payload)
    if normalized_event_name == "agent_project_effect":
        return _compact_event_project_effect(payload) or {}
    return _compact_event_payload_dict(payload)


def _emit_agent_event(event_name: str, payload: dict[str, Any] | None = None) -> None:
    from .agent_sessions import append_agent_execution_error
    emitter = _AGENT_EVENT_EMITTER
    if not callable(emitter):
        return
    event_payload = compact_agent_event_payload(event_name, payload)
    try:
        emitter(event_name, event_payload)
    except Exception as exc:
        print(f"[agent-event] failed to emit {event_name}: {exc}", flush=True)
        payload_row = event_payload if isinstance(event_payload, dict) else {}
        project_id = str(payload_row.get("projectId") or payload_row.get("project_id") or "").strip()
        if project_id:
            append_agent_execution_error(
                project_id,
                stage="emit_agent_event",
                message=f"推送智能体事件失败：{event_name}",
                episode_id=str(payload_row.get("episodeId") or payload_row.get("episode_id") or ""),
                session_id=str(payload_row.get("sessionId") or payload_row.get("session_id") or ""),
                category="event_emit_error",
                source="backend_event",
                error=exc,
                details={"eventName": event_name, "payload": payload_row},
                include_traceback=True,
            )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def ensure_store() -> None:
    from .provider_models import _storage_global_config
    GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    STYLE_THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    FAVORITE_STYLE_THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    GLOBAL_ASSET_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    if not GLOBAL_CONFIG_PATH.exists():
        _write_json(GLOBAL_CONFIG_PATH, _storage_global_config(DEFAULT_GLOBAL_CONFIG))
    if not GLOBAL_ASSETS_PATH.exists():
        _write_json(GLOBAL_ASSETS_PATH, DEFAULT_ASSETS)
    if not GLOBAL_STYLE_TEMPLATES_PATH.exists():
        _write_json(GLOBAL_STYLE_TEMPLATES_PATH, DEFAULT_STYLE_TEMPLATES)
    _ensure_builtin_template_catalog(
        GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH,
        DEFAULT_SCRIPT_ADAPTATION_TEMPLATES,
    )
    if not GLOBAL_TEXT_REPLACEMENT_RULES_PATH.exists():
        _write_json(GLOBAL_TEXT_REPLACEMENT_RULES_PATH, DEFAULT_TEXT_REPLACEMENT_RULES)
    if not GLOBAL_TASKS_PATH.exists():
        _write_json(GLOBAL_TASKS_PATH, [])
    if not GLOBAL_USAGE_PATH.exists():
        _write_json(
            GLOBAL_USAGE_PATH,
            {
                "monthCost": 0,
                "storyboardImages": 0,
                "storyboardVideos": 0,
                "failedTasks": 0,
            },
        )

def _merge_provider_presets(value: Any) -> list[dict[str, Any]]:
    return [copy.deepcopy(default) for default in DEFAULT_PROVIDER_PRESETS]


def _merge_model_capabilities(value: Any) -> dict[str, list[dict[str, Any]]]:
    return copy.deepcopy(DEFAULT_MODEL_CAPABILITIES)


AGENT_TEMPERATURE_OPTIONS = [0.2, 0.4, 0.7, 1.0]
AGENT_MAX_TOKEN_OPTIONS = [4096, 8192, 16384, 32768]
AI_VIDEO_AGENT_TASK_TEMPERATURE = 0.4
AI_VIDEO_AGENT_TASK_MAX_TOKENS = 8192


def _mask_key(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if len(text) <= 8:
        return "••••"
    return f"{text[:4]}••••{text[-4:]}"


def _truthy_confirmation(value: Any) -> bool:
    if value is True:
        return True
    text = str(value or "").strip().casefold()
    return text in {"true", "1", "yes", "y", "confirm", "confirmed", "delete_all", "clear_all"}


def _assert_explicit_delete_all_confirmed(
    payload: dict[str, Any] | None,
    *,
    target_label: str,
    target_terms: tuple[str, ...],
    require_all: bool = True,
) -> str:
    data = payload if isinstance(payload, dict) else {}
    confirmed = any(
        _truthy_confirmation(data.get(key))
        for key in (
            "confirmDeleteAll",
            "confirm_delete_all",
            "explicitUserConfirmed",
            "explicit_user_confirmed",
            "confirmed",
        )
    )
    instruction = " ".join(
        str(data.get(key) or "")
        for key in (
            "userInstruction",
            "user_instruction",
            "confirmationText",
            "confirmation_text",
        )
    ).strip()
    normalized = instruction.casefold()
    delete_terms = (
        "删除",
        "清空",
        "清除",
        "移除",
        "删掉",
        "删光",
        "重置",
        "delete",
        "clear",
        "remove",
        "reset",
    )
    all_terms = (
        "全部",
        "所有",
        "全量",
        "一键",
        "整项",
        "all",
        "everything",
        "entire",
    )
    if not confirmed:
        raise ValueError(f"{target_label}删除全部必须传入 confirmDeleteAll=true")
    if not instruction:
        raise ValueError(f"{target_label}删除全部必须传入原始用户明确指令")
    if not any(term.casefold() in normalized for term in target_terms):
        raise ValueError(f"用户指令未明确指向{target_label}，禁止删除全部")
    if not any(term in normalized for term in delete_terms):
        raise ValueError(f"用户指令未明确要求删除、清空或重置{target_label}")
    if require_all and not any(term in normalized for term in all_terms):
        raise ValueError(f"用户指令未明确要求全部/所有{target_label}")
    return instruction

__all__ = (
    '_normalize_asset_type_key', 'ASSET_LIFECYCLE_ACTIVE', 'ASSET_LIFECYCLE_OFFLINE',
    'ASSET_LIFECYCLE_ALL', '_normalize_asset_lifecycle_status', '_normalize_asset_lifecycle_filter',
    '_asset_lifecycle_status', '_asset_is_offline', '_asset_lifecycle_matches',
    '_asset_lifecycle_patch_value', '_set_asset_lifecycle_status',
    '_asset_row_for_response', '_filter_asset_store_by_lifecycle',
    '_now', '_read_json', '_write_json', '_JSON_WRITE_LOCK', '_serialized_project_config_write',
    '_GLOBAL_CONFIG_UPDATE_LOCK', '_serialized_global_config_write', '_normalize_text_replacement_rules',
    'set_agent_event_emitter',
    'compact_agent_event_payload', '_emit_agent_event', '_deep_merge', 'ensure_store', '_merge_provider_presets', '_merge_model_capabilities',
    'AGENT_TEMPERATURE_OPTIONS', 'AGENT_MAX_TOKEN_OPTIONS', 'AI_VIDEO_AGENT_TASK_TEMPERATURE',
    'AI_VIDEO_AGENT_TASK_MAX_TOKENS', '_mask_key', '_truthy_confirmation',
    '_assert_explicit_delete_all_confirmed'
)

# Preserve the implementation that was previously effective through package exports.
