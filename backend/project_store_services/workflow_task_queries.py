# -*- coding: utf-8 -*-
"""工作流领域实际实现。"""
from __future__ import annotations

from datetime import datetime
from datetime import timezone
from .canvas_store_queries import get_canvas_snapshot_v4
from .canvas_store_queries import read_card_results
from .store_core import _now
from .workflow_asset_resolution import resolve_workflow_node_inputs
from .workflow_contract import _node_route_id
from .workflow_contract import _node_segment_id
from .workflow_contract import _workflow_data_active_version_id
from .workflow_contract import _workflow_is_video_task_type
from .workflow_contract import _workflow_node
from .workflow_contract import _workflow_node_work_chain_id
from .workflow_generation_config import _workflow_task_config_from_node
from .workflow_generation_context import find_workflow_nodes
from .workflow_media_batch import _workflow_task_estimated_cost
from .workflow_projection import _read_workflow_tasks
from .workflow_projection import _workflow_payload_flag
from typing import Any
import copy
import re
import traceback


def _workflow_task_listing_canvas_view(
    project_id: str,
    episode_id: str,
    *,
    detail: str,
) -> dict[str, Any]:
    snapshot = get_canvas_snapshot_v4(
        project_id,
        episode_id,
        {
            "detail": "summary" if detail == "summary" else "full",
            "includeVersions": False,
            "includeTasks": False,
            "includeProjections": False,
        },
    )
    records = snapshot.get("records") if isinstance(snapshot.get("records"), dict) else {}
    document = snapshot.get("document") if isinstance(snapshot.get("document"), dict) else {}
    workflow = {
        "id": episode_id,
        "episodeId": episode_id,
        "schemaVersion": 4,
        "version": snapshot.get("currentRevision") or snapshot.get("revision") or 0,
        "nodes": copy.deepcopy(records.get("nodes") if isinstance(records.get("nodes"), list) else []),
        "edges": copy.deepcopy(records.get("edges") if isinstance(records.get("edges"), list) else []),
        "routes": copy.deepcopy(records.get("routes") if isinstance(records.get("routes"), list) else []),
        "workChains": copy.deepcopy(records.get("workChains") if isinstance(records.get("workChains"), list) else []),
    }
    for key in ("state", "inputLinks", "productionStatus", "build"):
        value = document.get(key)
        if isinstance(value, (dict, list)):
            workflow[key] = copy.deepcopy(value)
    return workflow


_REAL_WORKFLOW_TASK_ACTIVE_STATUSES = {
    "created",
    "queued",
    "waiting_upstream",
    "running",
    "processing",
}


_REAL_WORKFLOW_TASK_TERMINAL_OVERLAY_STATUSES = {
    "failed",
    "blocked",
    "preflight_failed",
    "cancelled",
}


_REAL_WORKFLOW_TASK_SUCCESS_OVERLAY_STATUSES = {
    "completed",
    "succeeded",
}


_REAL_WORKFLOW_GENERATION_TASK_TYPES = {
    "storyboard_image",
    "storyboard_image_edit",
    "visual_handoff_image",
    "storyboard_video",
    "workflow",
    "route_video",
}


def _task_timestamp_ms(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return 0


def _real_workflow_task_is_recent(task: dict[str, Any]) -> bool:
    task_type = str(task.get("type") or "").strip()
    timestamp_ms = _task_timestamp_ms(task.get("updatedAt")) or _task_timestamp_ms(task.get("createdAt"))
    if timestamp_ms <= 0:
        return True
    max_age_ms = 6 * 60 * 60 * 1000 if task_type in {"storyboard_video", "route_video"} else 45 * 60 * 1000
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return timestamp_ms >= now_ms - max_age_ms


def _task_workflow_node_id_from_real_task(task: dict[str, Any]) -> str:
    node_id = str(task.get("nodeId") or "").strip()
    if node_id:
        return node_id
    focus_target = task.get("focusTarget") if isinstance(task.get("focusTarget"), dict) else {}
    node_id = str(focus_target.get("nodeId") or "").strip()
    if node_id:
        return node_id
    project_effect = task.get("projectEffect") if isinstance(task.get("projectEffect"), dict) else {}
    effect_target = (
        project_effect.get("focusTarget")
        if isinstance(project_effect.get("focusTarget"), dict)
        else {}
    )
    return str(effect_target.get("nodeId") or "").strip()


def _read_overlay_real_workflow_tasks(project_id: str, episode_id: str) -> list[dict[str, Any]]:
    from .task_storage import _load_tasks_for_project

    data = _load_tasks_for_project(project_id)
    candidates: list[dict[str, Any]] = []
    latest_success_by_node_id: dict[str, int] = {}
    for task in data:
        if not isinstance(task, dict):
            continue
        if str(task.get("projectId") or "") != str(project_id):
            continue
        if str(task.get("episodeId") or "") != str(episode_id):
            continue
        if str(task.get("type") or "").strip() not in _REAL_WORKFLOW_GENERATION_TASK_TYPES:
            continue
        if not _real_workflow_task_is_recent(task):
            continue
        status = str(task.get("status") or "").strip()
        node_id = _task_workflow_node_id_from_real_task(task)
        timestamp = _task_timestamp_ms(task.get("updatedAt")) or _task_timestamp_ms(task.get("createdAt"))
        if status in _REAL_WORKFLOW_TASK_SUCCESS_OVERLAY_STATUSES and node_id:
            latest_success_by_node_id[node_id] = max(
                latest_success_by_node_id.get(node_id, 0),
                timestamp,
            )
        if (
            status not in _REAL_WORKFLOW_TASK_ACTIVE_STATUSES
            and status not in _REAL_WORKFLOW_TASK_TERMINAL_OVERLAY_STATUSES
            and status not in _REAL_WORKFLOW_TASK_SUCCESS_OVERLAY_STATUSES
        ):
            continue
        candidates.append(copy.deepcopy(task))
    result: list[dict[str, Any]] = []
    for task in candidates:
        status = str(task.get("status") or "").strip()
        if status in _REAL_WORKFLOW_TASK_TERMINAL_OVERLAY_STATUSES:
            node_id = _task_workflow_node_id_from_real_task(task)
            timestamp = _task_timestamp_ms(task.get("updatedAt")) or _task_timestamp_ms(task.get("createdAt"))
            if node_id and latest_success_by_node_id.get(node_id, 0) > timestamp:
                continue
        result.append(task)
    result.sort(
        key=lambda item: (
            _task_timestamp_ms(item.get("updatedAt")) or _task_timestamp_ms(item.get("createdAt")),
            str(item.get("id") or ""),
        )
    )
    return result


def _read_real_workflow_task_by_id(project_id: str, episode_id: str) -> dict[str, dict[str, Any]]:
    from .task_storage import _load_tasks_for_project

    result: dict[str, dict[str, Any]] = {}
    for task in _load_tasks_for_project(project_id):
        if not isinstance(task, dict):
            continue
        if str(task.get("projectId") or "") != str(project_id):
            continue
        if str(task.get("episodeId") or "") != str(episode_id):
            continue
        if str(task.get("type") or "").strip() not in _REAL_WORKFLOW_GENERATION_TASK_TYPES:
            continue
        task_id = str(task.get("id") or "").strip()
        if task_id:
            result[task_id] = copy.deepcopy(task)
    return result


def _workflow_task_from_real_generation_task(
    real_task: dict[str, Any],
    target_node_id: str,
    node_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    node = node_by_id.get(str(target_node_id or ""))
    node_data = node.get("data") if isinstance(node, dict) and isinstance(node.get("data"), dict) else {}
    focus_target = real_task.get("focusTarget") if isinstance(real_task.get("focusTarget"), dict) else {}
    return {
        "id": str(real_task.get("id") or f"real-task-{target_node_id}"),
        "type": str(real_task.get("type") or "workflow_node"),
        "projectId": real_task.get("projectId") or "",
        "episodeId": real_task.get("episodeId") or "",
        "nodeId": target_node_id,
        "nodeType": str((node or {}).get("type") or ""),
        "title": str(node_data.get("title") or real_task.get("title") or target_node_id),
        "status": str(real_task.get("status") or "running"),
        "progress": real_task.get("progress", 0),
        "message": real_task.get("message") or real_task.get("notice") or "",
        "error": real_task.get("error") or real_task.get("failureReason") or "",
        "modelId": real_task.get("modelId") or "",
        "providerId": real_task.get("providerId") or "",
        "focusTarget": copy.deepcopy(focus_target),
        "realTaskId": str(real_task.get("id") or ""),
        "generationTaskType": str(real_task.get("type") or ""),
        "generationTaskNodeId": str(real_task.get("nodeId") or ""),
        "startedAt": real_task.get("createdAt"),
        "updatedAt": real_task.get("updatedAt", real_task.get("createdAt")),
        "source": "global_generation_task",
    }


def _workflow_nodes_for_generation_task(
    workflow: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    task: dict[str, Any],
) -> set[str]:
    node_ids: set[str] = set()
    direct_node_id = str(task.get("nodeId") or "").strip()
    if direct_node_id:
        node_ids.add(direct_node_id)
    node = node_by_id.get(direct_node_id) if direct_node_id else None
    node_type = str((node or {}).get("type") or task.get("nodeType") or "").strip()
    task_type = str(task.get("type") or "").strip()
    image_edit_kind = str(task.get("imageEditKind") or task.get("image_edit_kind") or "").strip()
    is_canvas_image_edit = task_type == "storyboard_image_edit" and image_edit_kind == "canvas_image"
    route_id = str(task.get("routeId") or "").strip() or (_node_route_id(node) if isinstance(node, dict) else "")
    segment_id = str(task.get("segmentId") or "").strip() or (_node_segment_id(node) if isinstance(node, dict) else "")
    work_chain_id = _workflow_node_work_chain_id(workflow, node) if isinstance(node, dict) else ""

    def add_related(node_kind: str) -> None:
        candidates = []
        if route_id:
            candidates.extend(find_workflow_nodes(workflow, type=node_kind, route_id=route_id))
        if not candidates and work_chain_id:
            candidates.extend(find_workflow_nodes(workflow, type=node_kind, work_chain_id=work_chain_id))
        if not candidates and segment_id:
            candidates.extend(find_workflow_nodes(workflow, type=node_kind, segment_id=segment_id))
        for candidate in candidates:
            candidate_id = str(candidate.get("id") or "").strip()
            if candidate_id:
                node_ids.add(candidate_id)

    if (
        (task_type == "storyboard_image" or (task_type == "storyboard_image_edit" and not is_canvas_image_edit))
        or node_type == "storyboard.image"
    ):
        add_related("prompt.storyboard")
    if task_type in {"storyboard_video", "route_video"} or _workflow_is_video_task_type(node_type) or node_type == "video.result":
        add_related("video.storyboard")
    return node_ids


def _workflow_task_overlay_display_key(task: dict[str, Any]) -> str:
    task_type = str(task.get("generationTaskType") or task.get("type") or "").strip()
    if task_type not in _REAL_WORKFLOW_GENERATION_TASK_TYPES:
        return ""
    return _workflow_task_display_dedupe_key(task)


def _workflow_task_overlay_candidate(
    real_task: dict[str, Any],
    target_node_id: str,
    node_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidate = _workflow_task_from_real_generation_task(real_task, target_node_id, node_by_id)
    _apply_real_workflow_task_fields(candidate, real_task)
    return candidate


def _apply_real_workflow_task_overlay(
    workflow: dict[str, Any],
    tasks: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    project_id: str,
    episode_id: str,
) -> None:
    real_task_by_id = _read_real_workflow_task_by_id(project_id, episode_id)
    task_by_display_key = {
        display_key: task
        for task in tasks
        if isinstance(task, dict)
        for display_key in (_workflow_task_overlay_display_key(task),)
        if display_key
    }
    for workflow_task in tasks:
        if not isinstance(workflow_task, dict):
            continue
        real_task_id = str(workflow_task.get("realTaskId") or workflow_task.get("id") or "").strip()
        real_task = real_task_by_id.get(real_task_id)
        if not real_task:
            continue
        _apply_real_workflow_task_fields(workflow_task, real_task)
        display_key = _workflow_task_overlay_display_key(workflow_task)
        if display_key:
            task_by_display_key[display_key] = workflow_task

    for real_task in _read_overlay_real_workflow_tasks(project_id, episode_id):
        for target_node_id in _workflow_nodes_for_generation_task(workflow, node_by_id, real_task):
            candidate = _workflow_task_overlay_candidate(real_task, target_node_id, node_by_id)
            display_key = _workflow_task_overlay_display_key(candidate)
            workflow_task = task_by_display_key.get(display_key) if display_key else None
            if not workflow_task:
                tasks.append(candidate)
                if display_key:
                    task_by_display_key[display_key] = candidate
                continue
            _apply_real_workflow_task_fields(workflow_task, real_task)


def _workflow_task_idempotency_part(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text.replace("|", "%7C")


def _workflow_task_display_idempotency_key(task: dict[str, Any]) -> str:
    task_type = str(task.get("generationTaskType") or task.get("type") or "").strip()
    if task_type not in _REAL_WORKFLOW_GENERATION_TASK_TYPES:
        return ""
    project_id = str(task.get("projectId") or "").strip()
    episode_id = str(task.get("episodeId") or "").strip()
    node_id = str(task.get("generationTaskNodeId") or task.get("taskNodeId") or task.get("nodeId") or "").strip()
    if not project_id or not episode_id or not node_id:
        return ""
    result_node_id = str(task.get("resultNodeId") or task.get("outputNodeId") or "").strip()
    version_node_id = str(task.get("versionNodeId") or task.get("outputNodeId") or result_node_id or "").strip()
    parts = (
        "canvas-task",
        task_type,
        project_id,
        episode_id,
        node_id,
        result_node_id,
        version_node_id,
    )
    return "|".join(_workflow_task_idempotency_part(part) for part in parts)


def _apply_real_workflow_task_fields(
    workflow_task: dict[str, Any],
    real_task: dict[str, Any],
) -> None:
    workflow_task["status"] = str(real_task.get("status") or workflow_task.get("status") or "").strip()
    workflow_task["progress"] = real_task.get("progress", workflow_task.get("progress"))
    if real_task.get("message"):
        workflow_task["message"] = real_task.get("message")
    if real_task.get("notice"):
        workflow_task["notice"] = real_task.get("notice")
    if real_task.get("error") or real_task.get("failureReason"):
        workflow_task["error"] = real_task.get("error") or real_task.get("failureReason")
    generation_task_type = str(real_task.get("type") or "").strip()
    if generation_task_type:
        workflow_task["type"] = generation_task_type
    workflow_task["realTaskId"] = str(real_task.get("id") or "")
    workflow_task["generationTaskType"] = generation_task_type
    workflow_task["generationTaskNodeId"] = str(real_task.get("nodeId") or "")
    for key in ("completedAt", "failedAt", "cancelledAt", "blockedAt"):
        if real_task.get(key) is None:
            workflow_task.pop(key, None)
    for key in (
        "clientRequestId",
        "promptOperation",
        "idempotencyKey",
        "resultNodeId",
        "outputNodeId",
        "versionNodeId",
        "versionId",
        "completedAt",
        "failedAt",
        "cancelledAt",
        "blockedAt",
        "updatedAt",
    ):
        if real_task.get(key) is not None:
            workflow_task[key] = copy.deepcopy(real_task.get(key))
    if not str(workflow_task.get("idempotencyKey") or "").strip():
        idempotency_key = _workflow_task_display_idempotency_key(workflow_task)
        if idempotency_key:
            workflow_task["idempotencyKey"] = idempotency_key
    workflow_task["startedAt"] = real_task.get("createdAt", workflow_task.get("startedAt"))
    workflow_task["updatedAt"] = real_task.get("updatedAt", workflow_task.get("updatedAt"))


def _workflow_task_display_timestamp(task: dict[str, Any]) -> int:
    for key in ("updatedAt", "completedAt", "failedAt", "cancelledAt", "blockedAt", "startedAt", "createdAt"):
        timestamp = _task_timestamp_ms(task.get(key))
        if timestamp > 0:
            return timestamp
    return 0


def _workflow_task_is_active(task: dict[str, Any]) -> bool:
    return str(task.get("status") or "").strip() in _REAL_WORKFLOW_TASK_ACTIVE_STATUSES


def _workflow_task_display_dedupe_key(task: dict[str, Any]) -> str:
    task_id = str(task.get("id") or "").strip()
    stored_idempotency_key = str(task.get("idempotencyKey") or "").strip()
    computed_idempotency_key = _workflow_task_display_idempotency_key(task)
    has_output_identity = any(
        str(task.get(key) or "").strip()
        for key in ("resultNodeId", "outputNodeId", "versionNodeId")
    )
    idempotency_key = stored_idempotency_key
    if computed_idempotency_key and (not stored_idempotency_key or has_output_identity):
        idempotency_key = computed_idempotency_key
        task["idempotencyKey"] = computed_idempotency_key
    if idempotency_key:
        return f"intent:{idempotency_key}"
    if not _workflow_task_is_active(task):
        return f"id:{task_id}" if task_id else ""

    task_type = str(task.get("generationTaskType") or task.get("type") or "").strip()
    project_id = str(task.get("projectId") or "").strip()
    episode_id = str(task.get("episodeId") or "").strip()
    node_ids = sorted(
        {
            str(value or "").strip()
            for value in (
                task.get("generationTaskNodeId"),
                task.get("taskNodeId"),
                task.get("nodeId"),
            )
            if str(value or "").strip()
        }
    )
    result_node_ids = sorted(
        {
            str(value or "").strip()
            for value in (
                task.get("resultNodeId"),
                task.get("outputNodeId"),
                task.get("versionNodeId"),
            )
            if str(value or "").strip()
        }
    )
    if not task_type or not node_ids:
        return f"id:{task_id}" if task_id else ""
    return ":".join(
        (
            "active",
            project_id,
            episode_id,
            task_type,
            ",".join(node_ids),
            ",".join(result_node_ids),
        )
    )


def _select_workflow_display_task(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    if not existing:
        return incoming
    existing_timestamp = _workflow_task_display_timestamp(existing)
    incoming_timestamp = _workflow_task_display_timestamp(incoming)
    if (
        not _workflow_task_is_active(existing)
        and _workflow_task_is_active(incoming)
        and incoming_timestamp <= existing_timestamp
    ):
        return existing
    if existing_timestamp > incoming_timestamp:
        return existing
    return incoming


def _dedupe_workflow_display_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        key = _workflow_task_display_dedupe_key(task)
        if not key:
            unkeyed.append(task)
            continue
        by_key[key] = _select_workflow_display_task(by_key.get(key), task)
    return [*by_key.values(), *unkeyed]


_WORKFLOW_TASK_LIGHTWEIGHT_PROJECT_EFFECT_KEYS = {
    "action",
    "changedResources",
    "focusTarget",
    "nodeId",
    "notice",
    "opType",
    "projectChanged",
    "revision",
    "seq",
    "txId",
    "workflowVersion",
}


def _workflow_task_lightweight_project_effect(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    effect = {
        key: copy.deepcopy(value.get(key))
        for key in _WORKFLOW_TASK_LIGHTWEIGHT_PROJECT_EFFECT_KEYS
        if value.get(key) is not None
    }
    records = value.get("records") if isinstance(value.get("records"), dict) else {}
    if records:
        effect["recordSummary"] = {
            bucket: len(rows)
            for bucket, rows in records.items()
            if isinstance(rows, list)
        }
    return effect or None


def _workflow_task_lightweight_input_snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    links = value.get("inputLinks") if isinstance(value.get("inputLinks"), list) else []
    reference_media_ids = value.get("referenceMediaIds")
    return {
        "inputLinkCount": len([link for link in links if isinstance(link, dict)]),
        "referenceMediaIdCount": len(reference_media_ids) if isinstance(reference_media_ids, list) else 0,
    }


def _workflow_task_lightweight_row(task: dict[str, Any]) -> dict[str, Any]:
    row = copy.deepcopy(task)
    for key in ("result", "version", "versions", "nodes", "edges", "routes", "workChains", "workflow"):
        row.pop(key, None)
    project_effect = _workflow_task_lightweight_project_effect(row.get("projectEffect"))
    if project_effect is not None:
        row["projectEffect"] = project_effect
    else:
        row.pop("projectEffect", None)
    input_snapshot = _workflow_task_lightweight_input_snapshot(row.get("inputSnapshot"))
    if input_snapshot is not None:
        row["inputSnapshot"] = input_snapshot
    return row


def _workflow_task_blocking_issues(data: dict[str, Any]) -> list[str]:
    quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
    sources = (
        data.get("capabilityCheck") if isinstance(data.get("capabilityCheck"), dict) else {},
        quality.get("modelPreflight") if isinstance(quality.get("modelPreflight"), dict) else {},
        quality.get("batchPreflight") if isinstance(quality.get("batchPreflight"), dict) else {},
        quality.get("variantQualityResult") if isinstance(quality.get("variantQualityResult"), dict) else {},
        quality.get("lastVariantQualityResult") if isinstance(quality.get("lastVariantQualityResult"), dict) else {},
    )
    issues: list[str] = []
    for source in sources:
        if source.get("reportOnly") is True:
            continue
        for key in ("blockingIssues", "blockers", "errors"):
            value = source.get(key)
            rows = value if isinstance(value, list) else [value] if value else []
            for row in rows:
                text = str(row.get("message") if isinstance(row, dict) else row or "").strip()
                if text and text not in issues:
                    issues.append(text)
    return issues


def _workflow_task_error_summary(data: dict[str, Any], status: str) -> str:
    issues = _workflow_task_blocking_issues(data)
    if issues:
        return "；".join(issues[:5])
    for key in ("error", "errorSummary", "failureReason", "summary"):
        text = str(data.get(key) or "").strip()
        if text and status in {"failed", "blocked", "preflight_failed"}:
            return text
    return ""


def _workflow_normalized_reference_ids(value: Any) -> list[str]:
    result: list[str] = []
    rows = value if isinstance(value, list) else [value] if value else []
    for row in rows:
        text = str(row or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _workflow_task_resolved_input_snapshot(
    project_id: str,
    episode_id: str,
    node_id: str,
) -> dict[str, Any]:
    try:
        snapshot = resolve_workflow_node_inputs(project_id, episode_id, {"nodeId": node_id})
    except Exception:
        print(traceback.format_exc(), flush=True)
        return {}
    if not isinstance(snapshot, dict):
        return {}
    return {
        "inputLinks": copy.deepcopy(snapshot.get("inputLinks") or []),
        "groupedBySlot": copy.deepcopy(snapshot.get("groupedBySlot") or {}),
        "referenceMediaIds": copy.deepcopy(snapshot.get("referenceMediaIds") or []),
        "assetRefs": copy.deepcopy(snapshot.get("assetRefs") or []),
        "needsRelink": copy.deepcopy(snapshot.get("needsRelink") or []),
        "inputOwnerNodeId": snapshot.get("inputOwnerNodeId"),
        "inputOwnerNodeType": snapshot.get("inputOwnerNodeType"),
        "inheritedFromNodeId": snapshot.get("inheritedFromNodeId"),
    }


def _workflow_active_version_input_issue(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_id: str,
    input_snapshot: dict[str, Any],
) -> dict[str, Any]:
    node = _workflow_node(workflow, node_id) or {}
    node_type = str(node.get("type") or "").strip()
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    active_version_id = _workflow_data_active_version_id(data)
    current_refs = _workflow_normalized_reference_ids(input_snapshot.get("referenceMediaIds"))
    if not active_version_id or not current_refs:
        return {}
    versions = read_card_results(project_id, episode_id, node_id)
    active_version = next(
        (
            item
            for item in versions
            if isinstance(item, dict) and str(item.get("id") or "") == active_version_id
        ),
        {},
    ) if isinstance(versions, list) else {}
    if not isinstance(active_version, dict):
        return {}
    payload = active_version.get("payload") if isinstance(active_version.get("payload"), dict) else {}
    version_refs = _workflow_normalized_reference_ids(
        payload.get("referenceMediaIdsSnapshot") or payload.get("referenceMediaIds")
    )
    issue: dict[str, Any] = {}
    if set(current_refs) != set(version_refs):
        issue = {
            "reason": "active_version_reference_snapshot_mismatch",
            "message": "当前结果版本不是按已连接的参考资产生成，请重新生成。",
        }
    debug = active_version.get("generationDebug") if isinstance(active_version.get("generationDebug"), dict) else {}
    if node_type == "storyboard.image":
        reference_plan = debug.get("referencePlan") if isinstance(debug.get("referencePlan"), dict) else {}
        resolved_count = int(reference_plan.get("resolvedReferenceCount") or 0) if reference_plan else 0
        transport_count = int(reference_plan.get("transportReferenceCount") or 0) if reference_plan else 0
        if current_refs and (not reference_plan or resolved_count <= 0 or transport_count <= 0):
            issue = {
                "reason": "active_version_reference_not_sent",
                "severity": "warning",
                "message": "当前分镜图版本未记录到已连接资产参考图传输。已按模型实际输出保存，请人工检查参考图一致性。",
            }
    elif _workflow_is_video_task_type(node_type):
        provider_request = debug.get("providerRequest") if isinstance(debug.get("providerRequest"), dict) else {}
        reference_plan = provider_request.get("referencePlan") if isinstance(provider_request.get("referencePlan"), dict) else {}
        if (
            current_refs
            and reference_plan
            and (
                str(reference_plan.get("adapterTransport") or "") == "text_prompt_only"
                or int(reference_plan.get("transportReferenceCount") or 0) <= 0
            )
        ):
            issue = {
                "reason": "active_version_reference_not_transported",
                "message": "当前视频版本没有把已连接参考图发送给供应商，请改用可传输参考图的输入后重新生成。",
            }
    if not issue:
        return {}
    issue.update(
        {
            "activeVersionId": active_version_id,
            "currentReferenceMediaIds": current_refs,
            "versionReferenceMediaIds": version_refs,
        }
    )
    return issue


def _workflow_task_from_node(
    node: dict[str, Any],
    *,
    project_id: str,
    episode_id: str,
) -> dict[str, Any] | None:
    node_type = str(node.get("type") or "")
    is_runnable = (
        node_type in {"prompt.storyboard", "storyboard.image"}

        or _workflow_is_video_task_type(node_type)
    )
    if not is_runnable:
        return None
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    node_id = str(node.get("id") or "").strip()
    if not node_id:
        return None
    status = str(data.get("status") or "draft")
    task_id = str(data.get("taskId") or f"workflow-task-{node_id}")
    config = _workflow_task_config_from_node(node)
    cost_estimate = data.get("costEstimate") if isinstance(data.get("costEstimate"), dict) else {}
    model_id = str(
        config.get("modelId")
        or config.get("model_id")
        or data.get("model")
        or ""
    ).strip()
    provider_id = str(
        config.get("providerId")
        or config.get("provider_id")
        or data.get("providerId")
        or data.get("provider_id")
        or ""
    ).strip()
    estimated_cost = None
    for key in ("estimatedCost", "estimated_cost", "cost"):
        if data.get(key) is not None:
            estimated_cost = data.get(key)
            break
        if cost_estimate.get(key) is not None:
            estimated_cost = cost_estimate.get(key)
            break
        if config.get(key) is not None:
            estimated_cost = config.get(key)
            break
    error_summary = _workflow_task_error_summary(data, status)
    return {
        "id": task_id,
        "type": "workflow_node",
        "projectId": project_id,
        "episodeId": episode_id,
        "nodeId": node_id,
        "nodeType": node_type,
        "routeId": _node_route_id(node),
        "segmentId": _node_segment_id(node),
        "title": str(data.get("title") or node_id),
        "status": status,
        "progress": 100 if status in {"ready", "succeeded"} else 50 if status == "running" else 0,
        "message": str(data.get("summary") or ""),
        "modelId": model_id,
        "providerId": provider_id,
        "estimatedCost": estimated_cost,
        "error": error_summary,
        "failureReason": error_summary,
        "quality": copy.deepcopy(data.get("quality")) if isinstance(data.get("quality"), dict) else {},
        "inputSnapshot": {
            "inputLinks": copy.deepcopy(data.get("inputLinks") or []),
            "referenceMediaIds": copy.deepcopy(data.get("referenceMediaIds") or []),
        },
        "updatedAt": _now(),
        "source": "workflow_node",
    }


def list_workflow_tasks(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    lightweight = _workflow_payload_flag(
        payload.get("lightweight")
        or payload.get("compact")
        or payload.get("summary")
    )
    explicit_listing_mode = any(key in payload for key in ("lightweight", "compact", "summary"))
    detail_mode = str(payload.get("detail") or payload.get("mode") or "").strip().lower()
    full_requested = _workflow_payload_flag(payload.get("full")) or detail_mode == "full"
    if full_requested:
        lightweight = False
    elif not explicit_listing_mode:
        lightweight = True
    workflow = _workflow_task_listing_canvas_view(
        project_id,
        episode_id,
        detail="summary" if lightweight else "full",
    )
    route_id = str(payload.get("routeId") or payload.get("route_id") or "").strip()
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    explicit_tasks = _read_workflow_tasks(project_id, episode_id)
    tasks_by_id = {
        str(task.get("id") or ""): copy.deepcopy(task)
        for task in explicit_tasks
        if str(task.get("id") or "").strip()
    }
    node_rows = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    node_by_id = {
        str(node.get("id") or ""): node
        for node in node_rows
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }
    route_by_id = {
        str(route.get("id") or ""): route
        for route in workflow.get("routes", [])
        if isinstance(route, dict) and str(route.get("id") or "").strip()
    } if isinstance(workflow.get("routes"), list) else {}
    for node in node_rows:
        task = _workflow_task_from_node(node, project_id=project_id, episode_id=episode_id)
        if not task:
            continue
        existing = tasks_by_id.get(task["id"])
        if existing:
            task = {**task, **existing, "workflowStatus": task.get("status")}
        tasks_by_id[task["id"]] = task
    tasks = list(tasks_by_id.values())
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task.setdefault("projectId", project_id)
        task.setdefault("episodeId", episode_id)
        node = node_by_id.get(str(task.get("nodeId") or ""))
        if isinstance(node, dict):
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            task.setdefault("nodeType", str(node.get("type") or ""))
            task.setdefault("segmentId", _node_segment_id(node))
            task.setdefault("routeId", _node_route_id(node))
            task.setdefault("title", str(data.get("title") or node.get("id") or ""))
            config = _workflow_task_config_from_node(node)
            if not task.get("modelId"):
                task["modelId"] = str(config.get("modelId") or config.get("model_id") or data.get("model") or "").strip()
            if not task.get("providerId"):
                task["providerId"] = str(
                    config.get("providerId")
                    or config.get("provider_id")
                    or data.get("providerId")
                    or data.get("provider_id")
                    or ""
                ).strip()
            if not task.get("error") and str(task.get("status") or "") in {"failed", "blocked", "preflight_failed"}:
                task["error"] = _workflow_task_error_summary(data, str(task.get("status") or ""))
            if lightweight:
                if not task.get("inputSnapshot"):
                    task["inputSnapshot"] = {
                        "inputLinks": copy.deepcopy(data.get("inputLinks") or []),
                        "referenceMediaIds": copy.deepcopy(data.get("referenceMediaIds") or []),
                    }
            else:
                resolved_input_snapshot = _workflow_task_resolved_input_snapshot(
                    project_id,
                    episode_id,
                    str(node.get("id") or ""),
                )
                if resolved_input_snapshot:
                    task["inputSnapshot"] = resolved_input_snapshot
                    input_issue = _workflow_active_version_input_issue(
                        project_id,
                        episode_id,
                        workflow,
                        str(node.get("id") or ""),
                        resolved_input_snapshot,
                    )
                    if input_issue:
                        quality = task.get("quality") if isinstance(task.get("quality"), dict) else {}
                        if str(input_issue.get("severity") or "") == "warning":
                            quality["referenceTransportWarning"] = input_issue
                            task["quality"] = quality
                        else:
                            quality["activeVersionInputIssue"] = input_issue
                            task["quality"] = quality
                elif not task.get("inputSnapshot"):
                    task["inputSnapshot"] = {
                        "inputLinks": copy.deepcopy(data.get("inputLinks") or []),
                        "referenceMediaIds": copy.deepcopy(data.get("referenceMediaIds") or []),
                    }
        route = route_by_id.get(str(task.get("routeId") or ""))
        if isinstance(route, dict):
            task.setdefault("routeLabel", str(route.get("label") or route.get("title") or route.get("id") or ""))
            task.setdefault("workChainId", str(route.get("workChainId") or route.get("work_chain_id") or ""))
            task.setdefault("strategy", str(route.get("strategy") or ""))
    _apply_real_workflow_task_overlay(workflow, tasks, node_by_id, project_id, episode_id)
    tasks = _dedupe_workflow_display_tasks(tasks)
    if route_id:
        tasks = [task for task in tasks if str(task.get("routeId") or "") == route_id]
    if node_id:
        tasks = [task for task in tasks if str(task.get("nodeId") or "") == node_id]
    status = str(payload.get("status") or "").strip()
    if status:
        tasks = [task for task in tasks if str(task.get("status") or "") == status]
    tasks.sort(key=lambda item: (str(item.get("routeId") or ""), str(item.get("nodeId") or ""), str(item.get("id") or "")))
    if lightweight:
        tasks = [_workflow_task_lightweight_row(task) for task in tasks if isinstance(task, dict)]
    cost_summary = {
        "estimatedCost": 0.0,
        "queuedCost": 0.0,
        "runningCost": 0.0,
        "consumedCost": 0.0,
        "failedCost": 0.0,
    }
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_cost = _workflow_task_estimated_cost(task)
        task_status = str(task.get("status") or "").strip()
        if task_status in {"queued"}:
            cost_summary["queuedCost"] += task_cost
        elif task_status in {"running"}:
            cost_summary["runningCost"] += task_cost
        elif task_status in {"completed", "succeeded"}:
            cost_summary["consumedCost"] += task_cost
        elif task_status == "failed":
            cost_summary["failedCost"] += task_cost
        if task_status not in {"cancelled", "failed"}:
            cost_summary["estimatedCost"] += task_cost
    cost_summary = {key: round(value, 4) for key, value in cost_summary.items()}
    return {"success": True, "episodeId": episode_id, "tasks": tasks, "costSummary": cost_summary}
