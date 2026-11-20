# -*- coding: utf-8 -*-
"""任务变化向画布任务记录同步及延迟合并。"""
from __future__ import annotations

import copy
import threading
import time
import traceback
from .canvas_store_queries import episode_canvas_exists
from .canvas_store_records import normalize_canvas_changed_resources
from .canvas_store_documents import write_canvas_task_record_v4
from .task_storage import (
    _task_project_id,
)
from typing import (
    Any,
)


_CANVAS_TASK_RECORD_SYNC_LOCK = threading.Lock()


_CANVAS_TASK_RECORD_SYNC_PENDING: dict[str, dict[str, Any]] = {}


_CANVAS_TASK_RECORD_SYNC_THREAD: threading.Thread | None = None


_CANVAS_TASK_RECORD_SYNC_DELAY_SECONDS = 0.08


def _task_canvas_episode_id(task: dict[str, Any] | None) -> str:
    if not isinstance(task, dict):
        return ""
    return str(task.get("episodeId") or task.get("episode_id") or "").strip()


def _task_canvas_node_id(task: dict[str, Any] | None) -> str:
    if not isinstance(task, dict):
        return ""
    for key in (
        "nodeId",
        "node_id",
        "generationTaskNodeId",
        "generation_task_node_id",
        "taskNodeId",
        "task_node_id",
        "resultNodeId",
        "result_node_id",
        "outputNodeId",
        "output_node_id",
        "versionNodeId",
        "version_node_id",
    ):
        node_id = str(task.get(key) or "").strip()
        if node_id:
            return node_id
    focus_target = task.get("focusTarget") if isinstance(task.get("focusTarget"), dict) else {}
    return str(focus_target.get("nodeId") or focus_target.get("node_id") or "").strip()


def _sync_canvas_task_record(
    task: dict[str, Any] | None,
    *,
    changed_resources: list[str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(task, dict):
        return task
    project_id = _task_project_id(task)
    episode_id = _task_canvas_episode_id(task)
    node_id = _task_canvas_node_id(task)
    task_id = str(task.get("id") or task.get("taskId") or task.get("task_id") or "").strip()
    if not project_id or not episode_id or not node_id or not task_id:
        return task
    try:
        if not episode_canvas_exists(project_id, episode_id):
            return task
        task_row = copy.deepcopy(task)
        task_row["projectId"] = project_id
        task_row["episodeId"] = episode_id
        task_row.setdefault("nodeId", node_id)
        changed = _task_canvas_changed_resources(
            {"changedResources": changed_resources or []},
            task_row,
            fallback=["canvas_task"],
        )
        sync_result = write_canvas_task_record_v4(
            project_id,
            episode_id,
            task_row,
            op_type="card_patch",
            changed_resources=changed,
        )
        synced = copy.deepcopy(task_row)
        if sync_result.get("workflowVersion") is not None:
            synced["workflowVersion"] = copy.deepcopy(sync_result.get("workflowVersion"))
        records = sync_result.get("records") if isinstance(sync_result.get("records"), dict) else {}
        has_record_refs = any(
            isinstance(records.get(bucket), list) and bool(records.get(bucket))
            for bucket in ("added", "updated", "removed")
        )
        has_mutation = bool(sync_result.get("txId") or sync_result.get("changedResources") or has_record_refs)
        if has_mutation:
            for key in ("txId", "seq", "revision", "baseRevision", "opType", "records", "changedResources"):
                if sync_result.get(key) is not None:
                    synced[key] = copy.deepcopy(sync_result.get(key))
        return synced
    except Exception:
        print(traceback.format_exc(), flush=True)
        return task


def _canvas_task_record_sync_key(task: dict[str, Any] | None) -> str:
    task_id = str((task or {}).get("id") or (task or {}).get("taskId") or (task or {}).get("task_id") or "").strip()
    if not task_id:
        return ""
    project_id = _task_project_id(task)
    episode_id = _task_canvas_episode_id(task)
    if not project_id or not episode_id:
        return ""
    return f"{project_id}\0{episode_id}\0{task_id}"


def _run_deferred_canvas_task_record_sync() -> None:
    global _CANVAS_TASK_RECORD_SYNC_THREAD
    while True:
        time.sleep(_CANVAS_TASK_RECORD_SYNC_DELAY_SECONDS)
        with _CANVAS_TASK_RECORD_SYNC_LOCK:
            pending = dict(_CANVAS_TASK_RECORD_SYNC_PENDING)
            _CANVAS_TASK_RECORD_SYNC_PENDING.clear()
        if not pending:
            with _CANVAS_TASK_RECORD_SYNC_LOCK:
                if not _CANVAS_TASK_RECORD_SYNC_PENDING:
                    _CANVAS_TASK_RECORD_SYNC_THREAD = None
                    return
            continue
        for row in pending.values():
            task = row.get("task") if isinstance(row, dict) else None
            changed_resources = row.get("changedResources") if isinstance(row, dict) else None
            try:
                _sync_canvas_task_record(
                    task if isinstance(task, dict) else None,
                    changed_resources=changed_resources if isinstance(changed_resources, list) else None,
                )
            except Exception:
                print(traceback.format_exc(), flush=True)


def _defer_canvas_task_record_sync(
    task: dict[str, Any] | None,
    *,
    changed_resources: list[str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(task, dict):
        return task
    sync_key = _canvas_task_record_sync_key(task)
    if not sync_key:
        return task
    global _CANVAS_TASK_RECORD_SYNC_THREAD
    changed = _task_canvas_changed_resources(
        {"changedResources": changed_resources or []},
        task,
        fallback=["canvas_task"],
    )
    with _CANVAS_TASK_RECORD_SYNC_LOCK:
        existing = _CANVAS_TASK_RECORD_SYNC_PENDING.get(sync_key)
        if isinstance(existing, dict):
            existing_changed = existing.get("changedResources") if isinstance(existing.get("changedResources"), list) else []
            changed = normalize_canvas_changed_resources([*existing_changed, *changed])
        _CANVAS_TASK_RECORD_SYNC_PENDING[sync_key] = {
            "task": copy.deepcopy(task),
            "changedResources": changed,
        }
        if _CANVAS_TASK_RECORD_SYNC_THREAD is None or not _CANVAS_TASK_RECORD_SYNC_THREAD.is_alive():
            _CANVAS_TASK_RECORD_SYNC_THREAD = threading.Thread(
                target=_run_deferred_canvas_task_record_sync,
                name="ai-video-canvas-task-record-sync",
                daemon=True,
            )
            _CANVAS_TASK_RECORD_SYNC_THREAD.start()
    return task


def _task_canvas_record_sync_mode(value: Any) -> str:
    if value is False:
        return "none"
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"none", "false", "off", "skip"}:
            return "none"
        if normalized in {"async", "defer", "deferred", "queued"}:
            return "deferred"
    return "sync"


def _should_defer_canvas_task_record_sync(task: dict[str, Any] | None, fields: dict[str, Any]) -> bool:
    if not isinstance(task, dict):
        return False
    status = str(task.get("status") or fields.get("status") or "").strip().lower()
    if status in {"completed", "failed", "cancelled", "canceled"}:
        return False
    field_keys = {str(key) for key in fields.keys()}
    material_keys = {
        "result",
        "projectEffect",
        "changedResources",
        "generationError",
        "error",
        "failedAt",
        "completedAt",
        "media",
        "version",
        "versions",
        "workflowVersion",
    }
    if field_keys & material_keys:
        return False
    progress_keys = {
        "status",
        "progress",
        "message",
        "notice",
        "updatedAt",
        "startedAt",
        "videoJob",
        "modelMeta",
        "debug",
    }
    return bool(field_keys) and field_keys <= progress_keys and status in {"created", "running"}


_CANVAS_MUTATION_EVENT_FIELD_ALIASES = (
    ("workflowVersion", ("workflowVersion", "workflow_version")),
    ("txId", ("txId", "tx_id")),
    ("seq", ("seq",)),
    ("revision", ("revision",)),
    ("baseRevision", ("baseRevision", "base_revision")),
    ("opType", ("opType", "op_type")),
    ("records", ("records",)),
    ("documentExtras", ("documentExtras", "document_extras")),
    ("productionStatus", ("productionStatus", "production_status")),
)


_CANVAS_MUTATION_ENVELOPE_KEYS = tuple(
    key
    for _, aliases in _CANVAS_MUTATION_EVENT_FIELD_ALIASES
    for key in aliases
) + (
    "changedResources",
    "changed_resources",
)


def _task_canvas_mutation_has_envelope(source: Any) -> bool:
    return isinstance(source, dict) and any(
        source.get(key) is not None for key in _CANVAS_MUTATION_ENVELOPE_KEYS
    )


def _task_canvas_mutation_single_sync_mutation(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    mutations = source.get("mutations")
    if not isinstance(mutations, list) or len(mutations) != 1:
        return {}
    mutation = mutations[0]
    return mutation if _task_canvas_mutation_has_envelope(mutation) else {}


def _task_canvas_mutation_sources(*sources: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()

    def append(source: Any) -> None:
        if not isinstance(source, dict) or not source:
            return
        identity = id(source)
        if identity in seen:
            return
        seen.add(identity)
        rows.append(source)

    for source in sources:
        if not isinstance(source, dict):
            continue
        append(source)
        for nested_key in ("result", "version", "projectEffect"):
            nested = source.get(nested_key)
            if isinstance(nested, dict):
                append(nested)
        append(_task_canvas_mutation_single_sync_mutation(source))
    return rows


def _task_canvas_changed_resources_from_records(records: Any) -> list[str]:
    if not isinstance(records, dict):
        return []
    resources: list[str] = []
    seen: set[str] = set()
    for bucket_name in ("added", "updated", "removed"):
        bucket = records.get(bucket_name)
        if not isinstance(bucket, list):
            continue
        for record in bucket:
            if not isinstance(record, dict):
                continue
            resource = str(record.get("type") or "").strip()
            if resource and resource not in seen:
                seen.add(resource)
                resources.append(resource)
    return resources


def _task_canvas_changed_resource_name(value: Any) -> str:
    resource = str(value or "").strip()
    return {
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
        "workflow_version": "canvas_version",
        "workflow_versions": "canvas_version",
        "task": "canvas_task",
        "tasks": "canvas_task",
        "version": "canvas_version",
        "versions": "canvas_version",
        "workflow_video_task_references": "canvas_projection",
        "workflow_asset_refs": "canvas_projection",
    }.get(resource, resource)


def _task_canvas_changed_resources(
    *sources: Any,
    fallback: list[str] | None = None,
) -> list[str]:
    resources: list[str] = []
    for row in _task_canvas_mutation_sources(*sources):
        changed = row.get("changedResources")
        if changed is None:
            changed = row.get("changed_resources")
        if isinstance(changed, list):
            resources.extend(str(item) for item in changed if str(item or "").strip())
        resources.extend(_task_canvas_changed_resources_from_records(row.get("records")))
    resources.extend(str(item) for item in (fallback or []) if str(item or "").strip())
    return list(
        dict.fromkeys(
            normalized
            for resource in resources
            for normalized in [_task_canvas_changed_resource_name(resource)]
            if normalized
        )
    )
