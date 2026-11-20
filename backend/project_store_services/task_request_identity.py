# -*- coding: utf-8 -*-
"""任务请求签名、幂等标识和重复任务复用条件。"""
from __future__ import annotations

from .canvas_store_queries import read_canvas_node_signatures_v4
from .task_contract import _task_idempotency_part
from .task_contract import _task_workflow_node_id
from .task_control import _ACTIVE_GLOBAL_TASK_STATUSES
from .task_storage import _hydrate_task_runtime_fields
from .task_storage import _load_tasks_for_project
from .task_storage import _normalized_task_status
from typing import Any
import copy
import hashlib
import json
import re


_CANVAS_TASK_SIGNATURE_OMIT_KEYS = {
    "clientrequestid",
    "requestid",
    "taskid",
    "idempotencykey",
    "requestsignature",
    "payloadsignature",
    "inputsignature",
    "synccanvastaskrecord",
    "returnproductionstatus",
    "returnworkflow",
    "includeworkflow",
    "includeprojections",
    "includeversions",
    "includetasks",
    "includerecords",
    "includeprojecteffect",
    "includemutation",
    "detail",
    "mode",
    "summary",
    "lightweight",
    "compact",
    "reused",
    "status",
    "progress",
    "message",
    "notice",
    "createdat",
    "startedat",
    "updatedat",
    "completedat",
    "failedat",
    "blockedat",
    "cancelledat",
    "position",
    "viewport",
}


def _canvas_task_signature_key_token(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key or "").strip().lower())


def _canvas_task_signature_sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > 12:
        return str(value)
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key in sorted(value.keys(), key=lambda item: str(item)):
            key_text = str(key)
            if _canvas_task_signature_key_token(key_text) in _CANVAS_TASK_SIGNATURE_OMIT_KEYS:
                continue
            sanitized[key_text] = _canvas_task_signature_sanitize(value.get(key), depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_canvas_task_signature_sanitize(item, depth=depth + 1) for item in value]
    if isinstance(value, set):
        return [
            _canvas_task_signature_sanitize(item, depth=depth + 1)
            for item in sorted(value, key=lambda item: str(item))
        ]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _canvas_task_workflow_signature_payload(
    workflow: dict[str, Any] | None,
    *,
    project_id: str | None = None,
    episode_id: str | None = None,
    explicit_node_ids: list[str] | set[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if not isinstance(workflow, dict):
        workflow = {}
    payload: dict[str, Any] = {}
    for key in ("episodeId", "schemaVersion"):
        if workflow.get(key) is not None:
            payload[key] = workflow.get(key)
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    routes = workflow.get("routes") if isinstance(workflow.get("routes"), list) else []
    work_chains = workflow.get("workChains") if isinstance(workflow.get("workChains"), list) else []
    node_ids = {
        str(node.get("id") or "").strip()
        for node in nodes
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }
    if explicit_node_ids:
        node_ids.update(
            str(item or "").strip()
            for item in explicit_node_ids
            if str(item or "").strip()
        )
    if project_id and episode_id and node_ids:
        payload["nodeFingerprints"] = read_canvas_node_signatures_v4(project_id, episode_id, node_ids)
    payload["nodes"] = sorted(
        (
            _canvas_task_signature_sanitize(
                {
                    "id": node.get("id"),
                    "type": node.get("type"),
                    "routeId": node.get("routeId"),
                    "segmentId": node.get("segmentId"),
                    "workChainId": node.get("workChainId"),
                }
            )
            for node in nodes
            if isinstance(node, dict)
        ),
        key=lambda item: str(item.get("id") or ""),
    )
    payload["edges"] = sorted(
        (
            _canvas_task_signature_sanitize(
                {
                    "id": edge.get("id"),
                    "source": edge.get("source"),
                    "target": edge.get("target"),
                    "type": edge.get("type"),
                    "data": edge.get("data") if isinstance(edge.get("data"), dict) else {},
                }
            )
            for edge in edges
            if isinstance(edge, dict)
        ),
        key=lambda item: str(item.get("id") or ""),
    )
    payload["routes"] = sorted(
        (_canvas_task_signature_sanitize(route) for route in routes if isinstance(route, dict)),
        key=lambda item: str(item.get("id") or item.get("routeId") or ""),
    )
    payload["workChains"] = sorted(
        (_canvas_task_signature_sanitize(work_chain) for work_chain in work_chains if isinstance(work_chain, dict)),
        key=lambda item: str(item.get("id") or item.get("workChainId") or ""),
    )
    return payload


def _canvas_task_request_signature(
    task_type: str,
    project_id: str | None,
    episode_id: str | None,
    node_id: str | None,
    *,
    result_node_id: str | None = None,
    version_node_id: str | None = None,
    payload: dict[str, Any] | None = None,
    workflow: dict[str, Any] | None = None,
    signature_node_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    explicit_node_ids = {
        str(item or "").strip()
        for item in (
            node_id,
            result_node_id,
            version_node_id,
            *(signature_node_ids if isinstance(signature_node_ids, (list, set, tuple)) else []),
        )
        if str(item or "").strip()
    }
    body = {
        "taskType": str(task_type or "").strip(),
        "projectId": str(project_id or "").strip(),
        "episodeId": str(episode_id or "").strip(),
        "nodeId": str(node_id or "").strip(),
        "resultNodeId": str(result_node_id or "").strip(),
        "versionNodeId": str(version_node_id or "").strip(),
        "payload": payload if isinstance(payload, dict) else {},
        "workflow": _canvas_task_workflow_signature_payload(
            workflow,
            project_id=project_id,
            episode_id=episode_id,
            explicit_node_ids=explicit_node_ids,
        ),
        "extra": extra if isinstance(extra, dict) else {},
    }
    compact = json.dumps(
        _canvas_task_signature_sanitize(body),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()


_WORK_CHAIN_VIDEO_SIGNATURE_PAYLOAD_OMIT_KEYS = {
    "prompt",
    "processingSummary",
    "processing_summary",
    "resultTitle",
    "result_title",
    "taskMessage",
    "task_message",
    "taskTitle",
    "task_title",
    "title",
    "videoPrompt",
    "video_prompt",
    "videoPromptRaw",
    "video_prompt_raw",
    "versionTitle",
    "version_title",
}


def _storyboard_video_request_signature_payload(
    payload: dict[str, Any],
    *,
    is_work_chain_video_task: bool,
) -> dict[str, Any]:
    result = copy.deepcopy(payload) if isinstance(payload, dict) else {}
    if not is_work_chain_video_task:
        return result
    omit_tokens = {
        _canvas_task_signature_key_token(key)
        for key in _WORK_CHAIN_VIDEO_SIGNATURE_PAYLOAD_OMIT_KEYS
    }
    for key in list(result.keys()):
        if _canvas_task_signature_key_token(key) in omit_tokens:
            result.pop(key, None)
    return result


def _storyboard_video_request_signature_payload_overrides(
    payload_overrides: dict[str, Any] | None,
    *,
    is_work_chain_video_task: bool,
) -> dict[str, Any]:
    if is_work_chain_video_task:
        return {}
    return copy.deepcopy(payload_overrides) if isinstance(payload_overrides, dict) else {}


def _task_request_signature(task: dict[str, Any] | None) -> str:
    if not isinstance(task, dict):
        return ""
    for key in ("requestSignature", "payloadSignature", "inputSignature"):
        value = str(task.get(key) or "").strip()
        if value:
            return value
    job = task.get("videoJob") if isinstance(task.get("videoJob"), dict) else {}
    for key in ("requestSignature", "payloadSignature", "inputSignature"):
        value = str(job.get(key) or "").strip()
        if value:
            return value
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    for key in ("requestSignature", "payloadSignature", "inputSignature"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _assert_canvas_task_reusable_by_signature(
    task: dict[str, Any],
    request_signature: str | None,
) -> None:
    normalized_signature = str(request_signature or "").strip()
    if not normalized_signature:
        return
    existing_signature = _task_request_signature(task)
    if existing_signature and existing_signature == normalized_signature:
        return
    task_type = str(task.get("type") or task.get("generationTaskType") or "画布").strip()
    task_id = str(task.get("id") or "").strip()
    node_id = _task_workflow_node_id(task)
    suffix = f"（任务 {task_id}）" if task_id else ""
    node_suffix = f"节点 {node_id} " if node_id else ""
    raise RuntimeError(
        f"{node_suffix}已有 {task_type} 任务正在执行{suffix}，但本次请求输入已变化。"
        "请等待当前任务结束或取消后重新发起，不能复用不同输入的任务。"
    )


def _canvas_task_idempotency_key(
    task_type: str,
    project_id: str | None,
    episode_id: str | None,
    node_id: str | None,
    *,
    result_node_id: str | None = None,
    version_node_id: str | None = None,
) -> str:
    parts = (
        "canvas-task",
        task_type,
        project_id,
        episode_id,
        node_id,
        result_node_id,
        version_node_id,
    )
    return "|".join(_task_idempotency_part(part) for part in parts)


def _active_canvas_task_for_intent_unlocked(
    project_id: str,
    episode_id: str,
    task_type: str,
    node_id: str,
    *,
    result_node_id: str | None = None,
    version_node_id: str | None = None,
    idempotency_key: str | None = None,
    request_signature: str | None = None,
) -> dict[str, Any] | None:
    normalized_project_id = str(project_id or "").strip()
    normalized_episode_id = str(episode_id or "").strip()
    normalized_task_type = str(task_type or "").strip()
    normalized_node_id = str(node_id or "").strip()
    normalized_idempotency_key = str(idempotency_key or "").strip()
    target_result_ids = {
        str(result_node_id or "").strip(),
        str(version_node_id or "").strip(),
    } - {""}
    if not normalized_project_id or not normalized_episode_id or not normalized_task_type:
        return None
    for row in reversed(_load_tasks_for_project(normalized_project_id)):
        task = _hydrate_task_runtime_fields(row)
        if str(task.get("type") or "").strip() != normalized_task_type:
            continue
        if str(task.get("projectId") or "").strip() != normalized_project_id:
            continue
        if str(task.get("episodeId") or "").strip() != normalized_episode_id:
            continue
        if _normalized_task_status(task) not in _ACTIVE_GLOBAL_TASK_STATUSES:
            continue
        task_idempotency_key = str(task.get("idempotencyKey") or task.get("idempotency_key") or "").strip()
        if normalized_idempotency_key and task_idempotency_key == normalized_idempotency_key:
            _assert_canvas_task_reusable_by_signature(task, request_signature)
            return copy.deepcopy(task)
        if not normalized_node_id:
            continue
        task_node_ids = {
            str(task.get("nodeId") or "").strip(),
            str(task.get("generationTaskNodeId") or "").strip(),
            str(task.get("taskNodeId") or "").strip(),
        } - {""}
        if normalized_node_id not in task_node_ids:
            continue
        if target_result_ids:
            task_result_ids = {
                str(task.get("resultNodeId") or "").strip(),
                str(task.get("outputNodeId") or "").strip(),
                str(task.get("versionNodeId") or "").strip(),
            } - {""}
            if task_result_ids and not bool(task_result_ids & target_result_ids):
                continue
        _assert_canvas_task_reusable_by_signature(task, request_signature)
        return copy.deepcopy(task)
    return None
