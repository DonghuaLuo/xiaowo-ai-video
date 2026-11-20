# -*- coding: utf-8 -*-
"""画布生成请求、版本创建与视频任务提交协调。"""
from __future__ import annotations
from .canvas_ownership import VIDEO_TASK_NODE_TYPES

import copy
from .canvas_store_mutations import write_canvas_card_records_v4, write_canvas_records_v4
from .generation_config import (
    resolve_generation_config,
)
from .generation_input_context import (
    _generation_user_instruction,
    _truthy_payload_flag,
    _video_generation_node_id_from_payload,
)
from .projects import (
    _touch_project_meta,
)
from .reference_utils import (
    asset_refs_has_value as _asset_refs_has_value,
)
from .store_core import (
    _JSON_WRITE_LOCK,
)
from .task_control import (
    _update_task_fields,
    create_task,
)
from typing import (
    Any,
)


def _ensure_generation_workflow_node(
    project_id: str,
    episode_id: str,
    *,
    node_id: str,
    node_type: str,
    title: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from .workflow_projection import get_canvas_workflow_projection
    with _JSON_WRITE_LOCK:
        workflow = get_canvas_workflow_projection(project_id, episode_id)
        nodes = workflow.setdefault("nodes", [])
        node = next((item for item in nodes if isinstance(item, dict) and str(item.get("id") or "") == node_id), None)
        created = False
        if not node:
            node = {
                "id": node_id,
                "type": node_type,
                "position": {"x": 120 + len(nodes) * 80, "y": 360 + len(nodes) * 30},
                "data": {"title": title, "status": "draft", "summary": "等待生成。"},
            }
            nodes.append(node)
            created = True
        node["type"] = node_type
        data = node.setdefault("data", {})
        data["title"] = title
        data["status"] = "ready"
        data["summary"] = str(payload.get("summary") or payload.get("prompt") or payload.get("userInstruction") or title)
        payload_asset_refs = payload.get("assetRefs") if "assetRefs" in payload else payload.get("asset_refs")
        if _asset_refs_has_value(payload_asset_refs):
            data["assetRefs"] = copy.deepcopy(payload_asset_refs)
        copy_keys = ["routeId", "segmentId", "strategy", "prompt", "dialogue", "referenceMediaIds"]
        if node_type in {"prompt.storyboard", *VIDEO_TASK_NODE_TYPES}:
            copy_keys.append("generationConfig")
        for key in copy_keys:
            if key in payload:
                data[key] = copy.deepcopy(payload[key])
        if created:
            write_canvas_records_v4(
                project_id,
                episode_id,
                nodes=[copy.deepcopy(node)],
                op_type="structure_patch",
                changed_resources=["canvas_node"],
            )
        else:
            write_canvas_card_records_v4(project_id, episode_id, [copy.deepcopy(node)])
        _touch_project_meta(project_id)
        return node


def _submit_real_provider_requested(payload: dict[str, Any]) -> bool:
    return any(
        _truthy_payload_flag(payload.get(key))
        for key in (
            "submitRealProvider",
            "submit_real_provider",
            "execute",
            "confirmed",
            "userConfirmed",
            "user_confirmed",
        )
    )


def _request_generation_version(
    project_id: str,
    episode_id: str,
    *,
    node_id: str,
    node_type: str,
    title: str,
    task_type: str,
    version_type: str,
    payload: dict[str, Any],
    emit_events: bool = True,
) -> dict[str, Any]:
    from .task_events import _emit_generation_task_result
    from .video_task_execution import _ensure_storyboard_video_worker
    from .workflow_storyboard_prompts import _generated_version_preview
    from .workflow_storyboard_versions import add_storyboard_version
    config_check = resolve_generation_config(
        project_id,
        episode_id,
        {
            **payload,
            "nodeId": node_id,
            "nodeType": node_type,
            "mediaType": version_type,
        },
    )
    enriched_payload = {
        **copy.deepcopy(payload),
        "nodeId": node_id,
        "nodeType": node_type,
        "mediaType": version_type,
        "resolvedConfig": config_check.get("resolvedConfig"),
        "configWarnings": config_check.get("warnings") or [],
        "configBlockingIssues": config_check.get("blockingIssues") or [],
    }
    _ensure_generation_workflow_node(
        project_id,
        episode_id,
        node_id=node_id,
        node_type=node_type,
        title=title,
        payload=enriched_payload,
    )
    blocking_issues = config_check.get("blockingIssues") or []
    if blocking_issues:
        message = f"{title} 预检未通过：{blocking_issues[0]}"
        task = create_task(
            task_type,
            project_id=project_id,
            episode_id=episode_id,
            node_id=node_id,
            message=message,
            status="failed",
            progress=100,
        )
        version_payload = {
            **enriched_payload,
            "generationStage": task_type,
            "taskId": task.get("id"),
            "preflightFailed": True,
        }
        version = add_storyboard_version(
            project_id,
            episode_id,
            node_id,
            version_type,
            {
                "title": f"{title} 预检失败",
                "summary": message,
                "source": "agent-sdk-preflight",
                "payload": version_payload,
                "preview": _generated_version_preview(version_type, title, version_payload),
            },
        )
        result = {
            "success": False,
            "message": message,
            "task": task,
            "version": version,
            "resolvedConfig": config_check.get("resolvedConfig"),
            "warnings": config_check.get("warnings") or [],
            "blockingIssues": blocking_issues,
        }
        if emit_events:
            _emit_generation_task_result(
                result,
                project_id=project_id,
                episode_id=episode_id,
                node_id=node_id,
                project_action=f"{task_type}_preflight_failed",
        )
        return result
    if version_type == "video" and _submit_real_provider_requested(payload):
        task = create_task(
            task_type,
            project_id=project_id,
            episode_id=episode_id,
            node_id=node_id,
            message=f"{title} 已进入真实视频生成队列，正在等待供应商提交。",
            status="running",
            progress=5,
        )
        version_payload = {
            **enriched_payload,
            "generationStage": task_type,
            "taskId": task.get("id"),
            "realProviderSubmission": True,
        }
        version = add_storyboard_version(
            project_id,
            episode_id,
            node_id,
            version_type,
            {
                "title": title,
                "summary": f"{title} 已进入真实视频生成队列。",
                "source": "model-video-job",
                "payload": version_payload,
                "status": "processing",
                "preview": _generated_version_preview(version_type, title, version_payload),
            },
        )
        job = {
            "phase": "created",
            "title": title,
            "payload": version_payload,
            "versionId": version["id"],
        }
        task = _update_task_fields(task["id"], versionId=version["id"], videoJob=job) or task
        _ensure_storyboard_video_worker(task["id"])
        result = {
            "success": True,
            "task": task,
            "version": version,
            "resolvedConfig": config_check.get("resolvedConfig"),
            "warnings": config_check.get("warnings") or [],
            "blockingIssues": [],
        }
        if emit_events:
            _emit_generation_task_result(
                result,
                project_id=project_id,
                episode_id=episode_id,
                node_id=node_id,
                project_action=f"{task_type}_submitted",
            )
        return result
    task = create_task(
        task_type,
        project_id=project_id,
        episode_id=episode_id,
        node_id=node_id,
        message=str(payload.get("taskMessage") or payload.get("task_message") or f"{title} 请求已记录。"),
        status="completed",
        progress=100,
    )
    version_payload = {
        **enriched_payload,
        "generationStage": task_type,
        "taskId": task.get("id"),
    }
    version = add_storyboard_version(
        project_id,
        episode_id,
        node_id,
        version_type,
        {
            "title": title,
            "summary": str(payload.get("summary") or f"{title} 生成请求已保存。"),
            "source": "agent-sdk-request",
            "payload": version_payload,
            "preview": _generated_version_preview(version_type, title, version_payload),
        },
    )
    result = {
        "success": True,
        "task": task,
        "version": version,
        "resolvedConfig": config_check.get("resolvedConfig"),
        "warnings": config_check.get("warnings") or [],
        "blockingIssues": config_check.get("blockingIssues") or [],
    }
    if emit_events:
        _emit_generation_task_result(
            result,
            project_id=project_id,
            episode_id=episode_id,
            node_id=node_id,
            project_action=f"{task_type}_requested",
        )
    return result


def _request_storyboard_video_task_from_payload(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
    *,
    emit_events: bool,
) -> dict[str, Any]:
    from .storyboard_task_execution import run_storyboard_generation_task

    request_payload = payload if isinstance(payload, dict) else {}
    generation_config: dict[str, Any] = {}
    generation_config_provided = False
    for key in ("generationConfig", "generation_config"):
        value = request_payload.get(key)
        if isinstance(value, dict):
            generation_config = copy.deepcopy(value)
            generation_config_provided = True
            break
    if not generation_config_provided:
        node_type = str(request_payload.get("nodeType") or request_payload.get("node_type") or "").strip()
        if node_type in VIDEO_TASK_NODE_TYPES:
            generation_config_provided = True
    client_request_id = str(
        request_payload.get("clientRequestId")
        or request_payload.get("client_request_id")
        or request_payload.get("requestId")
        or request_payload.get("request_id")
        or ""
    ).strip()
    session_id = str(request_payload.get("sessionId") or "").strip()
    node_id = _video_generation_node_id_from_payload(project_id, episode_id, request_payload)
    return run_storyboard_generation_task(
        "storyboard_video",
        project_id,
        episode_id,
        node_id,
        "video",
        user_instruction=_generation_user_instruction(request_payload),
        emit_events=emit_events,
        generation_config=generation_config,
        generation_config_provided=generation_config_provided,
        payload_overrides=request_payload,
        client_request_id=client_request_id or None,
        session_id=session_id or None,
    )


def request_route_video_generation(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
    *,
    emit_events: bool = True,
) -> dict[str, Any]:
    return _request_storyboard_video_task_from_payload(project_id, episode_id, payload, emit_events=emit_events)
