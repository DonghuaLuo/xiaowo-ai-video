#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Handler 函数模块。"""

import traceback
import copy
from utils.xiaowo_sdk import sdk
from utils import project_store as store
from project_store_services.agent_test_inspection import (
    get_agent_test_execution_report,
    get_agent_test_inspection_domain,
)

store.set_agent_event_emitter(sdk.send_event)


def _send_event(event_name, payload=None):
    # 业务事件必须走统一出口：这里会在写入协议前生成前端所需摘要，
    # 禁止直接把完整 task/project/workflow 传给 sdk.send_event。
    sdk.send_event(event_name, store.compact_agent_event_payload(event_name, payload))


def _emit_custom_canvas_catalog_changed(action, project_id, result, canvas_id=""):
    if not result.get("success"):
        return
    changed_resources = result.get("changedResources")
    if not isinstance(changed_resources, list):
        changed_resources = []
    changed_resources = list(dict.fromkeys([*changed_resources, "canvas_catalog"]))
    payload = {
        "action": action,
        "projectId": project_id,
        "changedResources": changed_resources,
    }
    canvas = result.get("canvas")
    if isinstance(canvas, dict):
        payload["canvas"] = canvas
        payload["canvasId"] = canvas.get("canvasId") or canvas.get("canvas_id") or canvas_id
    else:
        payload["canvasId"] = result.get("canvasId") or canvas_id
    _send_event("project_changed", payload)


_CANVAS_MUTATION_ENVELOPE_KEYS = (
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
)


def _canvas_mutation_has_envelope(source):
    return isinstance(source, dict) and any(source.get(key) is not None for key in _CANVAS_MUTATION_ENVELOPE_KEYS)


def _canvas_mutation_single_sync_mutation(source):
    if not isinstance(source, dict):
        return {}
    mutations = source.get("mutations")
    if not isinstance(mutations, list):
        return {}
    mutation_rows = [row for row in mutations if _canvas_mutation_has_envelope(row)]
    return mutation_rows[0] if len(mutation_rows) == 1 else {}




def _canvas_mutation_event_sources(*sources):
    rows = []
    seen = set()

    def append(source):
        if not isinstance(source, dict) or not source:
            return
        marker = id(source)
        if marker in seen:
            return
        seen.add(marker)
        rows.append(source)

    for source in sources:
        if not isinstance(source, dict):
            continue
        if _canvas_mutation_has_envelope(source):
            append(source)
        version = source.get("version") if isinstance(source.get("version"), dict) else {}
        if _canvas_mutation_has_envelope(version):
            append(version)
        project_effect = source.get("projectEffect") if isinstance(source.get("projectEffect"), dict) else {}
        if _canvas_mutation_has_envelope(project_effect):
            append(project_effect)
        append(_canvas_mutation_single_sync_mutation(source))
    return rows


def _canvas_mutation_event_fields(*sources):
    fields = {}
    changed_resources = []
    key_aliases = (
        ("workflowVersion", ("workflowVersion", "workflow_version")),
        ("txId", ("txId", "tx_id")),
        ("seq", ("seq",)),
        ("revision", ("revision",)),
        ("baseRevision", ("baseRevision", "base_revision")),
        ("opType", ("opType", "op_type")),
        ("records", ("records",)),
        ("changedResources", ("changedResources", "changed_resources")),
        ("documentExtras", ("documentExtras", "document_extras")),
        ("productionStatus", ("productionStatus", "production_status")),
    )
    for source in _canvas_mutation_event_sources(*sources):
        for output_key, aliases in key_aliases:
            value = next((source.get(key) for key in aliases if source.get(key) is not None), None)
            if value is None:
                continue
            if output_key == "changedResources":
                rows = value if isinstance(value, list) else [value]
                changed_resources.extend(rows)
            else:
                fields[output_key] = copy.deepcopy(value)
    if changed_resources:
        fields["changedResources"] = _normalize_canvas_changed_resources(changed_resources)
    return fields


def _canvas_changed_resources_from_records(records):
    if not isinstance(records, dict):
        return []
    resources = []
    seen = set()
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


def _canvas_changed_resource_name(value):
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
        "workflow_asset_refs": "canvas_projection",
    }.get(resource, resource)


def _normalize_canvas_changed_resources(resources):
    normalized = []
    for item in resources if isinstance(resources, list) else []:
        resource = _canvas_changed_resource_name(item)
        if resource and resource not in normalized:
            normalized.append(resource)
    return normalized


def _canvas_event_changed_resources(result, fallback=None):
    mutation_fields = _canvas_mutation_event_fields(result)
    resources = mutation_fields.get("changedResources")
    if isinstance(resources, list) and resources:
        return _normalize_canvas_changed_resources(resources)
    resources = _canvas_changed_resources_from_records(mutation_fields.get("records"))
    if resources:
        return _normalize_canvas_changed_resources(resources)
    result = result if isinstance(result, dict) else {}
    resources = result.get("changedResources")
    if isinstance(resources, list) and resources:
        return _normalize_canvas_changed_resources(resources)
    return _normalize_canvas_changed_resources(fallback if isinstance(fallback, list) else [])




def _agent_split_completed_event_payload(result, project_id, episode_id=None):
    result = result if isinstance(result, dict) else {}
    project_effect = result.get("projectEffect") if isinstance(result.get("projectEffect"), dict) else {}
    event_payload = {
        "action": "agent_split_completed",
        "projectId": project_id,
    }
    if episode_id:
        event_payload["episodeId"] = episode_id
    mutation_fields = _canvas_mutation_event_fields(result)
    mutation_fields.update(_canvas_mutation_event_fields(project_effect))
    event_payload.update(mutation_fields)
    changed_resources = _merge_changed_resources(result, project_effect)
    if changed_resources:
        event_payload["changedResources"] = changed_resources
    if isinstance(project_effect.get("focusTarget"), dict):
        event_payload["focusTarget"] = copy.deepcopy(project_effect.get("focusTarget"))
    return event_payload


def _send_visual_handoff_cross_episode_event(result, project_id, episode_id, node_id, version_id):
    result = result if isinstance(result, dict) else {}
    version = result.get("version") if isinstance(result.get("version"), dict) else {}
    cross_link = result.get("crossEpisodeLink") if isinstance(result.get("crossEpisodeLink"), dict) else {}
    if not cross_link and isinstance(version, dict):
        cross_link = version.get("crossEpisodeLink") if isinstance(version.get("crossEpisodeLink"), dict) else {}
    if not cross_link or not cross_link.get("linked"):
        return
    target_episode_id = str(cross_link.get("episodeId") or "").strip()
    if not target_episode_id or target_episode_id == str(episode_id or "").strip():
        return
    mutation_fields = _canvas_mutation_event_fields(version, cross_link)
    if cross_link.get("workflowVersion") is not None:
        mutation_fields["workflowVersion"] = copy.deepcopy(cross_link.get("workflowVersion"))
    _send_event(
        "project_changed",
        {
            "action": "visual_handoff_cross_episode_linked",
            "projectId": project_id,
            "episodeId": target_episode_id,
            "sourceEpisodeId": episode_id,
            "sourceNodeId": cross_link.get("sourceNodeId") or node_id,
            "nodeId": cross_link.get("targetNodeId") or cross_link.get("mediaNodeId") or "",
            "mediaNodeId": cross_link.get("mediaNodeId") or "",
            "versionId": version_id,
            "workflowVersion": cross_link.get("workflowVersion"),
            **mutation_fields,
            "changedResources": _canvas_event_changed_resources(
                cross_link,
                ["canvas_node", "canvas_version", "visual_handoff"],
            ),
        },
    )


_STARTUP_RECOVERY_ERROR = ""
try:
    store.recover_home_archive_imports()
except Exception as exc:  # noqa: BLE001
    _STARTUP_RECOVERY_ERROR = str(exc)
    print(traceback.format_exc(), flush=True)

from project_store_services.model_request_logs import cleanup_model_logs_on_startup


def _ok(callable_, *args, agent_log_context=None, **kwargs):
    try:
        return callable_(*args, **kwargs)
    except Exception as exc:
        print(traceback.format_exc(), flush=True)
        context = agent_log_context if isinstance(agent_log_context, dict) else {}
        project_id = context.get("projectId") or context.get("project_id")
        if project_id:
            try:
                store.append_agent_execution_error(
                    project_id,
                    stage=context.get("stage") or "backend_handler",
                    message=context.get("message") or "智能体后端接口处理失败",
                    episode_id=context.get("episodeId") or context.get("episode_id"),
                    session_id=context.get("sessionId"),
                    category=context.get("category") or "handler_error",
                    source="backend_handler",
                    error=exc,
                    details={
                        "handler": getattr(callable_, "__name__", str(callable_)),
                        **(context.get("details") if isinstance(context.get("details"), dict) else {}),
                    },
                    include_traceback=True,
                )
            except Exception as log_exc:  # noqa: BLE001
                print(f"[agent-log] failed to record handler error: {log_exc}", flush=True)
        return {"success": False, "message": str(exc)}


def _param_bool(params, camel_key, snake_key=None, default=False):
    if camel_key in params:
        raw = params.get(camel_key)
    elif snake_key:
        raw = params.get(snake_key, default)
    else:
        raw = default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _episode_ids_param(params):
    params = params if isinstance(params, dict) else {}
    raw = params.get("episodeIds") if "episodeIds" in params else params.get("episode_ids")
    if isinstance(raw, list):
        episode_ids = [str(item or "").strip() for item in raw if str(item or "").strip()]
        return list(dict.fromkeys(episode_ids)) or None
    episode_id = str(params.get("episodeId") or params.get("episode_id") or "").strip()
    return [episode_id] if episode_id else None


def _generation_config_request(params, task_type):
    for key in ("generationConfig", "generation_config"):
        value = params.get(key)
        if isinstance(value, dict):
            return value, True
    node_type = str(params.get("nodeType") or params.get("node_type") or "").strip()
    if task_type == "storyboard_video" and node_type in {"video.storyboard", "video.keyframe"}:
        return {}, True
    return {}, False


def _generation_instruction_request(params):
    params = params or {}
    for key in (
        "userInstruction",
        "user_instruction",
        "revisionInstruction",
        "revision_instruction",
        "feedback",
        "prompt",
    ):
        value = params.get(key)
        if isinstance(value, (dict, list, tuple, set)):
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _merge_changed_resources(*items):
    resources = []
    for item in items:
        rows = item.get("changedResources") if isinstance(item, dict) else item
        if not isinstance(rows, list):
            continue
        resources.extend(str(row) for row in rows if str(row or "").strip())
    return _normalize_canvas_changed_resources(resources)


def _emit_agent_result(project_id, episode_id, result):
    session = result.get("session")
    project_effect = result.get("projectEffect")
    payload_episode_id = (
        result.get("episodeId")
        or episode_id
        or (session.get("episodeId") if isinstance(session, dict) else None)
    )
    payload_scope = result.get("scope") or (session.get("scope") if isinstance(session, dict) else None)
    payload_session_id = result.get("sessionId") or (session.get("id") if isinstance(session, dict) else None)
    payload_workflow_id = result.get("workflowId") or (session.get("workflowId") if isinstance(session, dict) else None)
    payload = {
        "projectId": project_id,
        "episodeId": payload_episode_id,
        "scope": payload_scope,
        "sessionId": payload_session_id,
        "workflowId": payload_workflow_id,
        "message": result.get("message"),
        "steps": result.get("steps") or [],
        "pendingQuestion": result.get("pendingQuestion"),
        "clientAction": result.get("clientAction"),
        "projectEffect": project_effect,
        "session": session,
        "sessions": result.get("sessions") or [],
    }
    _send_event("agent_session_updated", payload)
    snapshot = result.get("snapshot")
    if snapshot:
        _send_event("agent_session_snapshot", {**payload, "snapshot": snapshot})
    if isinstance(project_effect, dict) and project_effect:
        _send_event(
            "agent_project_effect",
            {
                "projectId": project_id,
                "episodeId": payload_episode_id,
                "scope": payload_scope,
                "workflowId": payload_workflow_id,
                "sessionId": payload_session_id,
                **project_effect,
            },
        )




@sdk.handler("hello")
def handle_hello(params):
    """演示 send_response - 简单请求响应"""
    name = params.get("name", "World")
    return {"message": f"Hello, {name}!", "from": "Python Backend"}


@sdk.handler("get_status")
def handle_get_status(params):
    """演示 send_response - 获取状态"""
    store.ensure_store()
    transport_stats = {}
    get_transport_stats = getattr(sdk, "protocol_transport_stats", None)
    if callable(get_transport_stats):
        transport_stats = get_transport_stats()
    return {
        "status": "running",
        "plugin_id": sdk.plugin_id,
        "plugin_dir": sdk.plugin_dir,
        "data_dir": str(store.DATA_DIR),
        "transportStats": transport_stats,
    }


@sdk.handler("get_dashboard")
def handle_get_dashboard(params):
    if _STARTUP_RECOVERY_ERROR:
        return {"success": False, "message": f"首页导入恢复失败：{_STARTUP_RECOVERY_ERROR}"}
    return _ok(store.get_dashboard)


@sdk.handler("set_current_project")
def handle_set_current_project(params):
    project_id = (params or {}).get("projectId") or (params or {}).get("project_id")
    return _ok(store.set_current_project, project_id)


@sdk.handler("check_extmodel_ready")
def handle_check_extmodel_ready(params):
    return {"success": True, "ready": True}


@sdk.handler("initialize_plugin")
def handle_initialize_plugin(params):
    result = cleanup_model_logs_on_startup()
    return {
        "success": bool(result.get("success", True)),
        "status": result.get("status", "running"),
    }


@sdk.handler("get_project_creation_options")
def handle_get_project_creation_options(params):
    params = params if isinstance(params, dict) else {}
    project_id = params.get("projectId")
    return _ok(store.get_creation_options, project_id)


@sdk.handler("create_project")
def handle_create_project(params):
    result = _ok(store.create_project, params or {})
    if result.get("success"):
        _send_event("project_changed", {"action": "created", "project": result.get("project")})
    return result


@sdk.handler("import_project")
def handle_import_project(params):
    result = _ok(store.import_project, params or {})
    if result.get("success"):
        _send_event("project_changed", {"action": "imported", "project": result.get("project")})
    return result


@sdk.handler("start_home_archive_import")
def handle_start_home_archive_import(params):
    return _ok(store.start_home_archive_import, params or {})


@sdk.handler("start_home_archive_export")
def handle_start_home_archive_export(params):
    return _ok(store.start_home_archive_export, params or {})


@sdk.handler("delete_project")
def handle_delete_project(params):
    project_id = (params or {}).get("projectId") or (params or {}).get("project_id")
    result = _ok(store.delete_project, project_id)
    if result.get("success"):
        _send_event("project_changed", {"action": "deleted", "projectId": project_id})
    return result


@sdk.handler("get_global_settings")
def handle_get_global_settings(params):
    return _ok(store.get_global_settings)


@sdk.handler("list_providers")
def handle_list_providers(params):
    return _ok(store.list_providers)


@sdk.handler("add_provider")
def handle_add_provider(params):
    result = _ok(store.add_provider, params or {})
    if result.get("success"):
        _send_event("model_config_changed", {})
    return result


@sdk.handler("update_provider")
def handle_update_provider(params):
    result = _ok(store.update_provider, params or {})
    if result.get("success"):
        _send_event("model_config_changed", {})
    return result


@sdk.handler("delete_provider")
def handle_delete_provider(params):
    result = _ok(store.delete_provider, (params or {}).get("providerId") or (params or {}).get("provider_id"))
    if result.get("success"):
        _send_event("model_config_changed", {})
    return result


@sdk.handler("test_provider_connection")
def handle_test_provider_connection(params):
    payload = params or {}
    request_id = str(payload.get("probeRequestId") or "") if isinstance(payload, dict) else ""
    result = _ok(
        store.test_provider_connection,
        payload,
        on_progress=(
            lambda progress: _send_event("provider_probe_progress", {**progress, "requestId": request_id})
        ) if request_id else None,
    )
    if result.get("provider"):
        _send_event("model_config_changed", {})
    return result


@sdk.handler("list_models")
def handle_list_models(params):
    params = params if isinstance(params, dict) else {}
    project_id = params.get("projectId") or params.get("project_id")
    if project_id:
        return _ok(
            store.list_model_capabilities,
            project_id,
            params.get("episodeId") or params.get("episode_id"),
            params,
        )
    return _ok(store.get_model_config, params.get("status") or "adapted")


@sdk.handler("save_model_config")
def handle_save_model_config(params):
    result = _ok(store.save_model_config, params or {})
    if result.get("success"):
        _send_event("model_config_changed", {})
    return result


@sdk.handler("get_script_adaptation_templates")
def handle_get_script_adaptation_templates(params):
    return _ok(store.get_script_adaptation_templates)


@sdk.handler("save_script_adaptation_template")
def handle_save_script_adaptation_template(params):
    return _ok(store.save_script_adaptation_template, params or {})


@sdk.handler("delete_script_adaptation_template")
def handle_delete_script_adaptation_template(params):
    params = params or {}
    return _ok(
        store.delete_script_adaptation_template,
        params.get("templateId") or params.get("template_id"),
    )


@sdk.handler("get_director_rules")
def handle_get_director_rules(params):
    return _ok(store.get_director_rules)


@sdk.handler("save_director_rule")
def handle_save_director_rule(params):
    return _ok(store.save_director_rule, params or {})


@sdk.handler("reset_director_rule")
def handle_reset_director_rule(params):
    return _ok(store.reset_director_rule, params or {})


@sdk.handler("get_text_replacement_rules")
def handle_get_text_replacement_rules(params):
    return _ok(store.get_text_replacement_rules)


@sdk.handler("save_text_replacement_rules")
def handle_save_text_replacement_rules(params):
    return _ok(store.save_text_replacement_rules, params or {})


@sdk.handler("get_storyboard_templates")
def handle_get_storyboard_templates(params):
    return _ok(store.get_storyboard_templates)


@sdk.handler("save_storyboard_template")
def handle_save_storyboard_template(params):
    return _ok(store.save_storyboard_template, params or {})


@sdk.handler("delete_storyboard_template")
def handle_delete_storyboard_template(params):
    params = params or {}
    return _ok(
        store.delete_storyboard_template,
        params.get("templateId") or params.get("template_id"),
    )


@sdk.handler("list_assets")
def handle_list_assets(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    scope = params.get("scope") or params.get("assetScope") or params.get("asset_scope")
    if not scope and project_id:
        scope = "project"
    return _ok(
        store.list_assets,
        scope or "global",
        project_id,
        asset_type=params.get("assetType") or params.get("asset_type"),
        lifecycle_status=params.get("lifecycleStatus") or params.get("lifecycle_status"),
        include_source_metadata=_param_bool(
            params,
            "includeSourceMetadata",
            "include_source_metadata",
            False,
        ),
    )


@sdk.handler("get_project_asset_counts")
def handle_get_project_asset_counts(params):
    params = params or {}
    return _ok(
        store.get_project_asset_counts,
        params.get("projectId") or params.get("project_id"),
    )


@sdk.handler("create_asset")
def handle_create_asset(params):
    params = params or {}
    result = _ok(
        store.create_asset,
        params.get("assetType") or params.get("asset_type"),
        params.get("asset") or {},
        params.get("scope", "global"),
        params.get("projectId") or params.get("project_id"),
    )
    if result.get("success") and params.get("scope") == "project":
        asset_type = params.get("assetType") or params.get("asset_type")
        _send_event(
            "project_changed",
            {
                "action": "asset_created",
                "projectId": params.get("projectId") or params.get("project_id"),
                "assetType": asset_type,
                "assetId": (result.get("asset") or {}).get("id") if isinstance(result.get("asset"), dict) else None,
                "asset": copy.deepcopy(result.get("asset")) if isinstance(result.get("asset"), dict) else None,
                "changedResources": _merge_changed_resources(
                    result,
                    {"changedResources": ["assets", asset_type]},
                ),
            },
        )
    return result


@sdk.handler("update_asset")
def handle_update_asset(params):
    params = params or {}
    result = _ok(
        store.update_asset,
        params.get("assetType") or params.get("asset_type"),
        params.get("assetId") or params.get("asset_id"),
        params.get("asset") or {},
        params.get("scope", "global"),
        params.get("projectId") or params.get("project_id"),
    )
    if result.get("success") and params.get("scope") == "project":
        asset_type = params.get("assetType") or params.get("asset_type")
        asset_id = params.get("assetId") or params.get("asset_id")
        _send_event(
            "project_changed",
            {
                "action": "asset_updated",
                "projectId": params.get("projectId") or params.get("project_id"),
                "assetType": asset_type,
                "assetId": asset_id,
                "asset": copy.deepcopy(result.get("asset")) if isinstance(result.get("asset"), dict) else None,
                "changedResources": _merge_changed_resources(
                    result,
                    {"changedResources": ["assets", asset_type]},
                ),
            },
        )
    return result


@sdk.handler("delete_asset")
def handle_delete_asset(params):
    params = params or {}
    result = _ok(
        store.delete_asset,
        params.get("assetType") or params.get("asset_type"),
        params.get("assetId") or params.get("asset_id"),
        params.get("scope", "global"),
        params.get("projectId") or params.get("project_id"),
        expected_revision=params.get("expectedRevision") or params.get("expected_revision"),
        base_hash=params.get("baseHash") or params.get("base_hash"),
        reason=str(params.get("reason") or "delete_asset"),
        user_instruction=str(params.get("userInstruction") or params.get("user_instruction") or ""),
    )
    if result.get("success") and params.get("scope") == "project":
        asset_type = params.get("assetType") or params.get("asset_type")
        _send_event(
            "project_changed",
            {
                "action": "asset_deleted",
                "projectId": params.get("projectId") or params.get("project_id"),
                "assetType": asset_type,
                "assetId": params.get("assetId") or params.get("asset_id"),
                "changedResources": _merge_changed_resources(
                    result,
                    {"changedResources": ["assets", asset_type]},
                ),
            },
        )
    return result


@sdk.handler("delete_all_project_assets")
def handle_delete_all_project_assets(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    result = _ok(store.delete_all_project_assets, project_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event(
            "project_changed",
            {
                "action": "project_assets_deleted_all",
                "projectId": project_id,
                "changedResources": result.get("changedResources") or [],
            },
        )
    return result


@sdk.handler("set_active_asset_media_version")
def handle_set_active_asset_media_version(params):
    params = params or {}
    result = _ok(
        store.set_active_asset_media_version,
        params.get("assetType") or params.get("asset_type"),
        params.get("assetId") or params.get("asset_id"),
        params.get("versionId") or params.get("version_id"),
        params.get("scope", "global"),
        params.get("projectId") or params.get("project_id"),
    )
    if result.get("success") and params.get("scope") == "project":
        asset_type = params.get("assetType") or params.get("asset_type")
        _send_event(
            "project_changed",
            {
                "action": "asset_media_version_activated",
                "projectId": params.get("projectId") or params.get("project_id"),
                "assetType": asset_type,
                "assetId": params.get("assetId") or params.get("asset_id"),
                "versionId": params.get("versionId") or params.get("version_id"),
                "asset": copy.deepcopy(result.get("asset")) if isinstance(result.get("asset"), dict) else None,
                "changedResources": _merge_changed_resources(
                    result,
                    {"changedResources": ["assets", asset_type]},
                ),
            },
        )
    return result


@sdk.handler("update_asset_media_version")
def handle_update_asset_media_version(params):
    params = params or {}
    result = _ok(
        store.update_asset_media_version,
        params.get("assetType") or params.get("asset_type"),
        params.get("assetId") or params.get("asset_id"),
        params.get("versionId") or params.get("version_id"),
        params.get("patch") or params.get("version") or {},
        params.get("scope", "global"),
        params.get("projectId") or params.get("project_id"),
    )
    if result.get("success") and params.get("scope") == "project":
        asset_type = params.get("assetType") or params.get("asset_type")
        _send_event(
            "project_changed",
            {
                "action": "asset_media_version_updated",
                "projectId": params.get("projectId") or params.get("project_id"),
                "assetType": asset_type,
                "assetId": params.get("assetId") or params.get("asset_id"),
                "versionId": params.get("versionId") or params.get("version_id"),
                "asset": copy.deepcopy(result.get("asset")) if isinstance(result.get("asset"), dict) else None,
                "changedResources": _merge_changed_resources(
                    result,
                    {"changedResources": ["assets", asset_type]},
                ),
            },
        )
    return result


@sdk.handler("delete_asset_media_version")
def handle_delete_asset_media_version(params):
    params = params or {}
    result = _ok(
        store.delete_asset_media_version,
        params.get("assetType") or params.get("asset_type"),
        params.get("assetId") or params.get("asset_id"),
        params.get("versionId") or params.get("version_id"),
        params.get("scope", "global"),
        params.get("projectId") or params.get("project_id"),
    )
    if result.get("success") and params.get("scope") == "project":
        asset_type = params.get("assetType") or params.get("asset_type")
        _send_event(
            "project_changed",
            {
                "action": "asset_media_version_deleted",
                "projectId": params.get("projectId") or params.get("project_id"),
                "assetType": asset_type,
                "assetId": params.get("assetId") or params.get("asset_id"),
                "versionId": params.get("versionId") or params.get("version_id"),
                "asset": copy.deepcopy(result.get("asset")) if isinstance(result.get("asset"), dict) else None,
                "changedResources": _merge_changed_resources(
                    result,
                    {"changedResources": ["assets", asset_type]},
                ),
            },
        )
    return result


@sdk.handler("generate_asset_media")
def handle_generate_asset_media(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    result = _ok(
        store.start_asset_media_generation,
        params.get("assetType") or params.get("asset_type"),
        params.get("assetId") or params.get("asset_id"),
        params.get("scope", "project"),
        project_id,
        None,
        hide_turnaround_heads=_param_bool(params, "hideTurnaroundHeads", "hide_turnaround_heads", default=None),
        episode_ids=_episode_ids_param(params),
    )
    return result


@sdk.handler("list_sources")
def handle_list_sources(params):
    return _ok(
        store.list_sources,
        (params or {}).get("projectId") or (params or {}).get("project_id"),
        True,
    )


@sdk.handler("get_source_text")
def handle_get_source_text(params):
    params = params or {}
    return _ok(
        store.get_source_text,
        params.get("projectId") or params.get("project_id"),
        params.get("sourceId") or params.get("source_id"),
    )


@sdk.handler("open_source_file_location")
def handle_open_source_file_location(params):
    params = params or {}
    return _ok(
        store.open_source_file_location,
        params.get("projectId") or params.get("project_id"),
        params.get("sourceId") or params.get("source_id"),
    )


@sdk.handler("save_source_text")
def handle_save_source_text(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    source_id = params.get("sourceId") or params.get("source_id")
    result = _ok(
        store.save_source_text,
        project_id,
        source_id,
        params.get("text") if "text" in params else params.get("sourceText") or params.get("source_text") or "",
        title=params.get("title"),
        reason=str(params.get("reason") or "manual_source_saved"),
    )
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "source_text_saved",
                "projectId": project_id,
                "sourceId": source_id,
                "changedResources": result.get("changedResources") or ["sources"],
            },
        )
    return result


@sdk.handler("append_novel_source_files")
def handle_append_novel_source_files(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    source_id = params.get("sourceId") or params.get("source_id")
    result = _ok(
        store.append_novel_source_files,
        project_id,
        source_id,
        params.get("files") or params.get("sources") or [],
    )
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "novel_source_files_appended",
                "projectId": project_id,
                "sourceId": source_id,
                "changedResources": result.get("changedResources") or ["sources", "sourceIndex"],
            },
        )
    return result


@sdk.handler("restore_source_total_snapshot")
def handle_restore_source_total_snapshot(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    source_id = params.get("sourceId") or params.get("source_id")
    result = _ok(
        store.restore_source_total_snapshot,
        project_id,
        source_id,
    )
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "source_total_restored",
                "projectId": project_id,
                "sourceId": source_id,
                "changedResources": result.get("changedResources") or ["sources", "sourceIndex"],
            },
        )
    return result


@sdk.handler("build_source_index")
def handle_build_source_index(params):
    params = params or {}
    return _ok(store.build_source_index, params.get("projectId") or params.get("project_id"))


@sdk.handler("list_source_index")
def handle_list_source_index(params):
    params = params or {}
    return _ok(store.list_source_index, params.get("projectId") or params.get("project_id"))


@sdk.handler("read_source_window")
def handle_read_source_window(params):
    params = params or {}
    return _ok(
        store.read_source_window,
        params.get("projectId") or params.get("project_id"),
        params.get("sourceId") or params.get("source_id"),
        params.get("chapterId") or params.get("chapter_id"),
        params.get("offset") or 0,
        params.get("length") or params.get("limit") or 4000,
    )


@sdk.handler("get_episode_source_text")
def handle_get_episode_source_text(params):
    params = params or {}
    return _ok(
        store.get_episode_source_text,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
    )


@sdk.handler("open_episode_source_file_location")
def handle_open_episode_source_file_location(params):
    params = params or {}
    return _ok(
        store.open_episode_source_file_location,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
    )


@sdk.handler("save_episode_source_text")
def handle_save_episode_source_text(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(
        store.save_episode_source_text,
        project_id,
        episode_id,
        params.get("text") if "text" in params else params.get("sourceText") or params.get("source_text") or "",
        title=params.get("title"),
        reason=str(params.get("reason") or "manual_source_text_saved"),
    )
    if result.get("success"):
        try:
            history_result = store.record_node_edit_history(
                project_id,
                episode_id,
                {
                    "nodeId": "source_text_1",
                    "nodeType": "source.text",
                    "title": result.get("title") or "原文",
                    "content": {"sourceText": result.get("text") or ""},
                    "reason": str(params.get("reason") or "manual_source_text_saved"),
                },
            )
            if history_result.get("item"):
                result["editHistory"] = history_result.get("item")
                result["editHistoryItems"] = [history_result.get("item")]
                result["changedResources"] = list(
                    dict.fromkeys(
                        [*(result.get("changedResources") or []), "node_edit_history"]
                    )
                )
        except Exception:
            print(traceback.format_exc(), flush=True)
        _send_event(
            "project_changed",
            {
                "action": "episode_source_text_saved",
                "projectId": project_id,
                "episodeId": episode_id,
                "changedResources": result.get("changedResources") or ["episodeSource"],
            },
        )
    return result


@sdk.handler("get_source_coverage")
def handle_get_source_coverage(params):
    params = params or {}
    return _ok(
        store.get_source_coverage,
        params.get("projectId") or params.get("project_id"),
        params.get("sourceId"),
    )


@sdk.handler("get_agent_test_inspection_domain")
def handle_get_agent_test_inspection_domain(params):
    params = params or {}
    return _ok(
        get_agent_test_inspection_domain,
        params.get("projectId") or params.get("project_id"),
        params.get("domain"),
        params.get("episodeId") or params.get("episode_id"),
    )


@sdk.handler("get_agent_test_execution_report")
def handle_get_agent_test_execution_report(params):
    params = params or {}
    return _ok(
        get_agent_test_execution_report,
        params.get("projectId") or params.get("project_id"),
        params.get("sessionId") or params.get("session_id"),
        params.get("since"),
    )


@sdk.handler("list_asset_split_batches")
def handle_list_asset_split_batches(params):
    params = params or {}
    return _ok(
        store.list_asset_split_batches,
        params.get("projectId") or params.get("project_id"),
        params.get("sourceId"),
        source_text_limit=params.get("sourceTextLimit"),
    )


@sdk.handler("get_asset_split_batch_source_text")
def handle_get_asset_split_batch_source_text(params):
    params = params or {}
    return _ok(
        store.get_asset_split_batch_source_text,
        params.get("projectId") or params.get("project_id"),
        params.get("rangeId"),
        params.get("sourceId"),
    )


@sdk.handler("create_source")
def handle_create_source(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    result = _ok(
        store.create_source,
        project_id,
        params.get("source") or {},
        params.get("onConflict") or params.get("on_conflict"),
    )
    if result.get("success"):
        _send_event("project_changed", {"action": "source_created", "projectId": project_id})
    return result


@sdk.handler("replace_sources")
def handle_replace_sources(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    result = _ok(
        store.replace_sources,
        project_id,
        params.get("sources") or [],
    )
    if result.get("success"):
        _send_event("project_changed", {"action": "sources_replaced", "projectId": project_id})
    return result


@sdk.handler("analyze_project_overview")
def handle_analyze_project_overview(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    excerpt_chars = params.get("excerptChars")
    if excerpt_chars is None:
        excerpt_chars = params.get("excerpt_chars")
    result = _ok(
        store.analyze_project_overview,
        project_id,
        params.get("sourceId") or params.get("source_id"),
        excerpt_chars,
    )
    if result.get("success"):
        _send_event("task_created", result.get("task"))
        _send_event("task_completed", result.get("task"))
        _send_event("project_changed", {"action": "overview_analyzed", "projectId": project_id})
    return result


@sdk.handler("update_project_overview")
def handle_update_project_overview(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    result = _ok(
        store.update_project_overview,
        project_id,
        params.get("overview") or params.get("values") or {},
    )
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "overview_updated",
                "projectId": project_id,
                "project": result.get("project"),
            },
        )
    return result


@sdk.handler("list_agent_sessions")
def handle_list_agent_sessions(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    return _ok(
        store.list_agent_sessions,
        project_id,
        episode_id,
        agent_log_context={
            "projectId": project_id,
            "episodeId": episode_id,
            "stage": "handle_list_agent_sessions",
            "message": "读取智能体会话列表失败",
        },
    )


@sdk.handler("get_agent_conversation_context")
def handle_get_agent_conversation_context(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    return _ok(store.get_agent_conversation_context, project_id, episode_id, params)


@sdk.handler("set_agent_conversation_context")
def handle_set_agent_conversation_context(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.set_agent_conversation_context, project_id, episode_id, params)
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "agent_conversation_context_updated",
                "projectId": project_id,
                "episodeId": episode_id,
                "scope": result.get("scope"),
                "sessionId": result.get("sessionId"),
            },
        )
    return result


@sdk.handler("list_agent_conversations")
def handle_list_agent_conversations(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    return _ok(store.list_agent_conversations, project_id, episode_id, params)


@sdk.handler("create_agent_conversation")
def handle_create_agent_conversation(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    return _ok(store.create_agent_conversation, project_id, episode_id, params)


@sdk.handler("ensure_episode_agent_conversation")
def handle_ensure_episode_agent_conversation(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.ensure_episode_agent_conversation, project_id, episode_id, params)
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "episode_agent_conversation_ensured",
                "projectId": project_id,
                "episodeId": episode_id,
                "sessionId": ((result.get("conversation") or {}).get("id")
                if isinstance(result.get("conversation"), dict)
                else None),
            },
        )
    return result


@sdk.handler("get_agent_session")
def handle_get_agent_session(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    session_id = params.get("sessionId")
    return _ok(
        store.get_agent_session,
        project_id,
        session_id,
        scope=params.get("scope"), episode_id=params.get("episodeId") or params.get("episode_id"),
        agent_log_context={
            "projectId": project_id,
            "sessionId": session_id,
            "stage": "handle_get_agent_session",
            "message": "读取智能体会话详情失败",
        },
    )


@sdk.handler("get_agent_snapshot")
def handle_get_agent_snapshot(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    session_id = params.get("sessionId")
    return _ok(
        store.get_agent_snapshot,
        project_id,
        session_id,
        scope=params.get("scope"), episode_id=params.get("episodeId") or params.get("episode_id"),
        agent_log_context={
            "projectId": project_id,
            "sessionId": session_id,
            "stage": "handle_get_agent_snapshot",
            "message": "读取智能体实时快照失败",
        },
    )


@sdk.handler("get_agent_execution_trace")
def handle_get_agent_execution_trace(params):
    from project_store_services.agent_execution_traces import get_agent_execution_trace

    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    session_id = params.get("sessionId") or params.get("session_id")
    return _ok(
        get_agent_execution_trace,
        project_id,
        session_id,
        params.get("executionId") or params.get("execution_id"),
        agent_log_context={
            "projectId": project_id,
            "sessionId": session_id,
            "stage": "handle_get_agent_execution_trace",
            "message": "读取智能体执行轨迹失败",
        },
    )


@sdk.handler("save_agent_attachment")
def handle_save_agent_attachment(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    return _ok(
        store.save_agent_attachment,
        project_id,
        params.get("attachment") or {},
        agent_log_context={
            "projectId": project_id,
            "stage": "handle_save_agent_attachment",
            "message": "保存智能体附件失败",
        },
    )


@sdk.handler("list_agent_skills")
def handle_list_agent_skills(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    scope = params.get("scope") or params.get("contextScope") or params.get("context_scope")
    return _ok(
        store.list_agent_skills,
        project_id,
        episode_id,
        scope=scope,
        agent_log_context={
            "projectId": project_id,
            "episodeId": episode_id,
            "stage": "handle_list_agent_skills",
            "message": "读取智能体技能列表失败",
        },
    )


@sdk.handler("list_agent_error_logs")
def handle_list_agent_error_logs(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    return _ok(
        store.list_agent_error_logs,
        project_id,
        limit=params.get("limit") or 80,
        days=params.get("days") or 7,
        agent_log_context={
            "projectId": project_id,
            "stage": "handle_list_agent_error_logs",
            "message": "读取智能体错误日志失败",
        },
    )


@sdk.handler("clear_agent_error_logs")
def handle_clear_agent_error_logs(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    return _ok(
        store.clear_agent_error_logs,
        project_id,
        agent_log_context={
            "projectId": project_id,
            "stage": "handle_clear_agent_error_logs",
            "message": "清空智能体错误日志失败",
        },
    )


@sdk.handler("delete_agent_session")
def handle_delete_agent_session(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    session_id = params.get("sessionId")
    result = _ok(
        store.delete_agent_session,
        project_id,
        session_id,
        agent_log_context={
            "projectId": project_id,
            "sessionId": session_id,
            "stage": "handle_delete_agent_session",
            "message": "删除智能体会话失败",
        },
    )
    if result.get("task"):
        _send_event("task_failed", result.get("task"))
    return result


@sdk.handler("run_canvas_agent_task")
def handle_run_canvas_agent_task(params):
    from project_store_services.agent_canvas_tasks import start_canvas_agent_task

    params = params or {}
    return _ok(start_canvas_agent_task, params.get("projectId"), params.get("episodeId"), params,
               agent_log_context={"projectId": params.get("projectId"),
                                  "stage": "handle_run_canvas_agent_task",
                                  "message": "启动画布智能体任务失败"})


@sdk.handler("run_agent_message")
def handle_run_agent_message(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    scope = params.get("scope") or params.get("contextScope") or params.get("context_scope")
    workflow_id = params.get("workflowId") or params.get("workflow_id")
    session_id = params.get("sessionId")
    active_target = params.get("activeTarget") or params.get("active_target")
    raw_control_only = params.get("controlOnly")
    if raw_control_only is None:
        raw_control_only = params.get("control_only")
    control_only = raw_control_only is True or str(raw_control_only or "").strip().lower() == "true"
    display_message = params.get("displayMessage") or params.get("display_message")
    quick_prompt_id = params.get("quickPromptId") or params.get("quick_prompt_id")
    result = _ok(
        store.run_agent_message,
        project_id,
        episode_id,
        params.get("message") or "",
        params.get("images") or [],
        session_id,
        params.get("preferredAction") or params.get("preferred_action"),
        params.get("preferredTaskType") or params.get("preferred_task_type"),
        display_message,
        quick_prompt_id,
        control_only,
        scope=scope,
        workflow_id=workflow_id,
        active_target=active_target,
        candidate_ref=params.get("candidateRef") or params.get("candidate_ref"),
        task_options=params.get("taskOptions") or params.get("task_options"),
        # 只转发结构化快捷指令/推荐项元数据；普通 action 不进入聊天入口。
        # 后端会校验 action/taskType 白名单，未带元数据的自然语言仍由显式路由或模型探针判断。
        agent_log_context={
            "projectId": project_id,
            "episodeId": episode_id,
            "sessionId": session_id,
            "stage": "handle_run_agent_message",
            "message": "智能体消息接口处理失败",
            "details": {
                "messagePreview": str(params.get("message") or "")[:200],
                "displayMessagePreview": str(display_message or "")[:200],
                "imageCount": len(params.get("images") or []),
                "preferredAction": params.get("preferredAction") or params.get("preferred_action") or "",
                "preferredTaskType": params.get("preferredTaskType") or params.get("preferred_task_type") or "",
                "quickPromptId": quick_prompt_id or "",
                "controlOnly": control_only,
                "scope": scope or "",
                "workflowId": workflow_id or "",
            },
        },
    )
    if result.get("success") and not result.get("backgroundStarted"):
        for task in result.get("tasks") or []:
            _send_event("task_created", task)
            _send_event("task_completed", task)
        _emit_agent_result(project_id, episode_id, result)
        if result.get("projectChanged"):
            _send_event(
                "project_changed",
                _agent_split_completed_event_payload(result, project_id, episode_id),
            )
    return result


@sdk.handler("answer_agent_question")
def handle_answer_agent_question(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    scope = params.get("scope") or params.get("contextScope") or params.get("context_scope")
    workflow_id = params.get("workflowId") or params.get("workflow_id")
    session_id = params.get("sessionId")
    result = _ok(
        store.answer_agent_question,
        project_id,
        episode_id,
        params.get("questionId") or params.get("question_id") or "",
        params.get("action") or "",
        params.get("label") or "",
        session_id,
        params.get("answers") or params.get("answer") or {},
        scope=scope,
        workflow_id=workflow_id,
        agent_log_context={
            "projectId": project_id,
            "episodeId": episode_id,
            "sessionId": session_id,
            "stage": "handle_answer_agent_question",
            "message": "智能体追问回答接口处理失败",
            "details": {
                "questionId": params.get("questionId") or params.get("question_id") or "",
                "action": params.get("action") or "",
                "scope": scope or "",
                "workflowId": workflow_id or "",
            },
        },
    )
    if result.get("success") and not result.get("backgroundStarted"):
        for task in result.get("tasks") or []:
            _send_event("task_created", task)
            _send_event("task_completed", task)
        _emit_agent_result(project_id, episode_id, result)
        if result.get("projectChanged"):
            _send_event(
                "project_changed",
                _agent_split_completed_event_payload(result, project_id, episode_id),
            )
    return result


@sdk.handler("interrupt_agent_session")
def handle_interrupt_agent_session(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    result = _ok(
        store.interrupt_agent_session,
        project_id,
        params.get("sessionId"),
        agent_log_context={
            "projectId": project_id,
            "episodeId": params.get("episodeId") or params.get("episode_id"),
            "sessionId": params.get("sessionId"),
            "stage": "handle_interrupt_agent_session",
            "message": "停止智能体会话失败",
        },
    )
    if result.get("task"):
        _send_event("task_failed", result.get("task"))
    if result.get("success"):
        _emit_agent_result(project_id, params.get("episodeId") or params.get("episode_id"), result)
    return result




@sdk.handler("delete_source")
def handle_delete_source(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    source_id = params.get("sourceId") or params.get("source_id")
    result = _ok(
        store.delete_source,
        project_id,
        source_id,
    )
    if result.get("success"):
        _send_event(
            "project_changed",
            {"action": "source_deleted", "projectId": project_id, "sourceId": source_id},
        )
    return result


@sdk.handler("delete_source_segment")
def handle_delete_source_segment(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    source_id = params.get("sourceId") or params.get("source_id")
    segment_id = params.get("segmentId") or params.get("segment_id")
    result = _ok(
        store.delete_source_segment,
        project_id,
        source_id,
        segment_id,
    )
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "source_segment_deleted",
                "projectId": project_id,
                "sourceId": source_id,
                "segmentId": segment_id,
                "changedResources": result.get("changedResources") or ["sources", "sourceIndex"],
            },
        )
    return result


@sdk.handler("get_project_settings")
def handle_get_project_settings(params):
    return _ok(store.get_project_settings, (params or {}).get("projectId") or (params or {}).get("project_id"))


@sdk.handler("save_project_settings")
def handle_save_project_settings(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    result = _ok(
        store.save_project_settings,
        project_id,
        params.get("settings") or {},
    )
    if result.get("success"):
        _send_event("project_changed", {"action": "settings_saved", "projectId": project_id})
    return result


@sdk.handler("update_project_settings")
def handle_update_project_settings(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    settings = params.get("settings") if isinstance(params.get("settings"), dict) else params
    result = _ok(store.save_project_settings, project_id, settings or {})
    if result.get("success"):
        _send_event("project_changed", {"action": "settings_saved", "projectId": project_id})
    return result


@sdk.handler("delete_project_planning_outputs")
def handle_delete_project_planning_outputs(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    result = _ok(store.delete_project_planning_outputs, project_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event(
            "project_changed",
            {
                "action": "project_planning_outputs_deleted",
                "projectId": project_id,
                "episodeIds": result.get("episodeIds") or [],
                "targets": result.get("targets") or [],
                "changedResources": result.get("changedResources") or [],
            },
        )
    return result


@sdk.handler("get_canvas_changes")
def handle_get_canvas_changes(params):
    params = params or {}
    return _ok(
        store.list_canvas_changes_v4,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params.get("sinceRevision") or params.get("since_revision") or 0,
    )


@sdk.handler("list_project_custom_canvases")
def handle_list_project_custom_canvases(params):
    params = params or {}
    return _ok(
        store.list_project_custom_canvases_v4,
        params.get("projectId") or params.get("project_id"),
    )


@sdk.handler("create_custom_canvas")
def handle_create_custom_canvas(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    result = _ok(
        store.create_custom_canvas_v4,
        project_id,
        params,
    )
    _emit_custom_canvas_catalog_changed("custom_canvas_created", project_id, result)
    return result


@sdk.handler("rename_custom_canvas")
def handle_rename_custom_canvas(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    canvas_id = params.get("canvasId") or params.get("canvas_id")
    result = _ok(
        store.rename_custom_canvas_v4,
        project_id,
        canvas_id,
        params.get("title") or "",
    )
    _emit_custom_canvas_catalog_changed("custom_canvas_renamed", project_id, result, canvas_id)
    return result


@sdk.handler("delete_custom_canvas")
def handle_delete_custom_canvas(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    canvas_id = params.get("canvasId") or params.get("canvas_id")
    result = _ok(
        store.delete_custom_canvas_v4,
        project_id,
        canvas_id,
    )
    _emit_custom_canvas_catalog_changed("custom_canvas_deleted", project_id, result, canvas_id)
    return result


@sdk.handler("get_canvas_snapshot")
def handle_get_canvas_snapshot(params):
    from project_store_services.workflow_production_sync import get_canvas_snapshot_with_production_status

    params = params or {}
    return _ok(
        get_canvas_snapshot_with_production_status,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("get_canvas_records")
def handle_get_canvas_records(params):
    params = params or {}
    return _ok(
        store.get_canvas_records_v4,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("get_canvas_reference_views")
def handle_get_canvas_reference_views(params):
    from project_store_services.workflows import get_canvas_reference_views

    params = params or {}
    return _ok(get_canvas_reference_views, params.get("projectId"), params.get("episodeId"))


@sdk.handler("resolve_canvas_asset_images")
def handle_resolve_canvas_asset_images(params):
    params = params or {}
    return _ok(store.resolve_canvas_asset_images, params.get("projectId"), params.get("episodeId"), params)


@sdk.handler("build_episode_workflow_from_work_chain_plan")
def handle_build_episode_workflow_from_work_chain_plan(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.build_episode_workflow_from_work_chain_plan, project_id, episode_id, params)
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "episode_workflow_built",
                "projectId": project_id,
                "episodeId": episode_id,
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(result, ["canvas_document"]),
            },
        )
    return result


@sdk.handler("adjust_source_split_workflow")
def handle_adjust_source_split_workflow(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.adjust_source_split_workflow, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event(
            "project_changed",
            {
                "action": "source_split_workflow_adjusted",
                "projectId": project_id,
                "episodeId": episode_id,
                "sourceNodeId": result.get("sourceNodeId") or "",
                "segmentCount": result.get("segmentCount"),
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(
                    result,
                    ["canvas_node", "canvas_edge", "canvas_route", "canvas_work_chain"],
                ),
            },
        )
    return result




@sdk.handler("create_independent_source_card")
def handle_create_independent_source_card(params):
    params = params or {}
    project_id = params.get("projectId")
    episode_id = params.get("episodeId")
    result = _ok(store.create_independent_source_card, project_id, episode_id, params)
    if result.get("success"):
        _send_event("project_changed", {
            "action": "independent_source_card_created",
            "projectId": project_id, "episodeId": episode_id,
            "sourceNodeId": result.get("sourceNodeId"),
            "workflowVersion": result.get("workflowVersion"),
            **_canvas_mutation_event_fields(result),
            "changedResources": _canvas_event_changed_resources(result, ["canvas_node"]),
        })
    return result


@sdk.handler("apply_storyboard_allocation")
def handle_apply_storyboard_allocation(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.apply_storyboard_allocation, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event(
            "project_changed",
            {
                "action": "storyboard_allocation_applied",
                "projectId": project_id,
                "episodeId": episode_id,
                "directorNodeId": result.get("directorNodeId") or "",
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(
                    result, ["canvas_node", "canvas_edge", "canvas_route", "canvas_work_chain"],
                ),
            },
        )
    return result


@sdk.handler("get_director_plan_asset_catalog")
def handle_get_director_plan_asset_catalog(params):
    from project_store_services.director_plan_contract import get_director_plan_asset_catalog

    params = params or {}
    return _ok(
        get_director_plan_asset_catalog,
        params.get("projectId"), params.get("episodeId"), params.get("nodeId"),
    )


@sdk.handler("save_project_narrator_reference_audio")
def handle_save_project_narrator_reference_audio(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    result = _ok(
        store.save_project_narrator_reference_audio,
        project_id,
        params.get("media"),
    )
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "narrator_reference_audio_updated",
                "projectId": project_id,
                "project": result.get("project"),
            },
        )
    return result


@sdk.handler("prepare_reference_audio")
def handle_prepare_reference_audio(params):
    params = params or {}
    media = params.get("media") or params.get("filePath") or params.get("file_path")
    return _ok(
        store.prepare_reference_audio,
        media,
        max_seconds=params.get("maxSeconds") or params.get("max_seconds") or 600,
    )


@sdk.handler("import_video_task_reference_audio")
def handle_import_video_task_reference_audio(params):
    from project_store_services.video_reference_audio import import_video_task_reference_audio

    params = params or {}
    return _ok(import_video_task_reference_audio, params.get("projectId") or "", params.get("media"))


@sdk.handler("preview_video_task_voices")
def handle_preview_video_task_voices(params):
    from project_store_services.video_reference_audio import preview_video_task_voices

    params = params or {}
    return _ok(preview_video_task_voices, params.get("projectId") or "",
               params.get("data") or {}, params.get("prompt") or "")


@sdk.handler("crop_reference_audio")
def handle_crop_reference_audio(params):
    params = params or {}
    return _ok(
        store.crop_reference_audio,
        params.get("audioPath") or params.get("audio_path") or "",
        start=params.get("start"),
        end=params.get("end"),
        max_seconds=params.get("maxSeconds") or params.get("max_seconds") or 15,
    )


@sdk.handler("cleanup_reference_audio")
def handle_cleanup_reference_audio(params):
    params = params or {}
    return _ok(
        store.cleanup_reference_audio,
        params.get("paths") or params.get("path") or [],
    )


@sdk.handler("apply_independent_source_workflow")
def handle_apply_independent_source_workflow(params):
    params = params or {}
    project_id = params.get("projectId")
    episode_id = params.get("episodeId")
    result = _ok(store.apply_independent_source_workflow, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event("project_changed", {
            "action": "independent_source_workflow_applied",
            "projectId": project_id, "episodeId": episode_id,
            "sourceNodeId": result.get("sourceNodeId"),
            "segmentCount": result.get("segmentCount"),
            "workflowVersion": result.get("workflowVersion"),
            **_canvas_mutation_event_fields(result),
            "changedResources": _canvas_event_changed_resources(result, ["canvas_node", "canvas_edge", "canvas_route", "canvas_work_chain"]),
        })
    return result


@sdk.handler("create_manual_workflow_chain")
def handle_create_manual_workflow_chain(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.create_manual_workflow_chain, project_id, episode_id, params)
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "manual_workflow_chain_created",
                "projectId": project_id,
                "episodeId": episode_id,
                "workChainId": result.get("workChainId") or "",
                "segmentId": result.get("segmentId") or "",
                "workflowVersion": result.get("workflowVersion"),
                "focusTarget": result.get("focusTarget"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(result, ["canvas_document"]),
            },
        )
    return result


@sdk.handler("relayout_episode_workflow")
def handle_relayout_episode_workflow(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.relayout_episode_workflow, project_id, episode_id, params)
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "episode_workflow_relayout",
                "projectId": project_id,
                "episodeId": episode_id,
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(result, ["canvas_document"]),
            },
        )
    return result


@sdk.handler("get_project_planning_summary")
def handle_get_project_planning_summary(params):
    params = params or {}
    return _ok(
        store.get_project_planning_summary,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
    )


@sdk.handler("save_story_world_map")
def handle_save_story_world_map(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    result = _ok(store.save_story_world_map, project_id, params)
    if result.get("success"):
        _send_event("project_changed", {"action": "story_world_saved", "projectId": project_id})
    return result


@sdk.handler("upsert_asset")
def handle_upsert_asset(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    result = _ok(store.upsert_asset, project_id, params)
    if result.get("success"):
        asset = result.get("asset") if isinstance(result.get("asset"), dict) else {}
        _send_event(
            "project_changed",
            {
                "action": "asset_upserted",
                "projectId": project_id,
                "assetType": params.get("assetType") or params.get("asset_type"),
                "assetId": asset.get("id"),
                "asset": copy.deepcopy(asset) if asset else None,
                "changedResources": result.get("changedResources") or [],
            },
        )
    return result


@sdk.handler("save_episode_work_chain_plan")
def handle_save_episode_work_chain_plan(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.save_episode_work_chain_plan, project_id, episode_id, params)
    if result.get("success"):
        workflow_result = _ok(
            store.build_episode_workflow_from_work_chain_plan,
            project_id,
            result.get("episodeId") or episode_id,
            {
                "source": "agent",
                "reason": "save_episode_work_chain_plan",
            },
        )
        if workflow_result.get("success"):
            for key, value in _canvas_mutation_event_fields(workflow_result).items():
                result[key] = copy.deepcopy(value)
            result["changedResources"] = list(
                dict.fromkeys(
                    [
                        *(result.get("changedResources") or []),
                        *_canvas_event_changed_resources(workflow_result, ["canvas_document"]),
                    ]
                )
            )
        else:
            build_message = str(workflow_result.get("message") or "生成画布工作链失败").strip()
            result["success"] = False
            result["workflowBuild"] = copy.deepcopy(workflow_result)
            result["message"] = (
                f"{str(result.get('message') or '工作链计划已保存').rstrip('。')}，"
                f"但画布工作链生成失败：{build_message}"
            )
            result["changedResources"] = list(
                dict.fromkeys([*(result.get("changedResources") or []), "workChainPlan"])
            )
        _send_event(
            "project_changed",
            {
                "action": "episode_work_chain_plan_saved",
                "projectId": project_id,
                "episodeId": result.get("episodeId") or episode_id,
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(
                    result,
                    ["canvas_document"] if workflow_result.get("success") else [],
                ),
            },
        )
    return result


@sdk.handler("save_workflow_node_inline_edit")
def handle_save_workflow_node_inline_edit(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.save_workflow_node_inline_edit, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        event_payload = {
            "action": "workflow_node_inline_saved",
            "projectId": project_id,
            "episodeId": episode_id,
            "nodeId": result.get("nodeId"),
            "node": result.get("node") if isinstance(result.get("node"), dict) else None,
            "nodes": result.get("nodes") if isinstance(result.get("nodes"), list) else [],
            "edges": result.get("edges") if isinstance(result.get("edges"), list) else [],
            "editHistory": result.get("editHistory") if isinstance(result.get("editHistory"), dict) else None,
            "editHistoryItems": result.get("editHistoryItems") if isinstance(result.get("editHistoryItems"), list) else [],
            "editHistoryWarning": result.get("editHistoryWarning") or "",
            "dirtyNodeIds": result.get("dirtyNodeIds") if isinstance(result.get("dirtyNodeIds"), list) else [],
            "inputDirtyNodeIds": result.get("inputDirtyNodeIds") if isinstance(result.get("inputDirtyNodeIds"), list) else [],
            "workflowVersion": result.get("workflowVersion"),
            **_canvas_mutation_event_fields(result),
            "changedResources": _canvas_event_changed_resources(result, []),
        }
        _send_event("project_changed", event_payload)
    return result








@sdk.handler("update_workflow_node_layout")
def handle_update_workflow_node_layout(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.update_workflow_node_layout, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event(
            "project_changed",
            {
                "action": "workflow_node_layout_updated",
                "projectId": project_id,
                "episodeId": episode_id,
                "nodeId": result.get("nodeId"),
                "node": result.get("node") if isinstance(result.get("node"), dict) else None,
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(result, []),
                "focusTarget": result.get("focusTarget"),
            },
        )
    return result


@sdk.handler("list_node_edit_history")
def handle_list_node_edit_history(params):
    params = params or {}
    return _ok(
        store.list_node_edit_history,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("restore_node_edit_history")
def handle_restore_node_edit_history(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.restore_node_edit_history, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event(
            "project_changed",
            {
                "action": "node_edit_history_restored",
                "projectId": project_id,
                "episodeId": episode_id,
                "nodeId": result.get("nodeId"),
                "node": result.get("node") if isinstance(result.get("node"), dict) else None,
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(
                    result,
                    ["canvas_node", "workflow_node_inline", "node_edit_history"],
                ),
                "focusTarget": result.get("focusTarget"),
            },
        )
    return result


@sdk.handler("delete_node_edit_history")
def handle_delete_node_edit_history(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.delete_node_edit_history, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event(
            "project_changed",
            {
                "action": "node_edit_history_deleted",
                "projectId": project_id,
                "episodeId": episode_id,
                "nodeId": result.get("nodeId"),
                "versionId": result.get("versionId"),
                "projection": result.get("projection") if isinstance(result.get("projection"), dict) else None,
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(result, ["node_edit_history"]),
            },
        )
    return result


@sdk.handler("list_director_rework_records")
def handle_list_director_rework_records(params):
    params = params or {}
    return _ok(
        store.list_director_rework_records,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("delete_director_rework_record")
def handle_delete_director_rework_record(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.delete_director_rework_record, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event("project_changed", {
            "action": "director_rework_record_deleted",
            "projectId": project_id,
            "episodeId": episode_id,
            "nodeId": result.get("nodeId"),
            "changedResources": result.get("changedResources") or [],
        })
    return result


@sdk.handler("patch_shot_prompt")
def handle_patch_shot_prompt(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.patch_shot_prompt, project_id, episode_id, params)
    if result.get("success"):
        workflow_patch = (
            result.get("workflowPatch")
            if isinstance(result.get("workflowPatch"), dict)
            else {}
        )
        _send_event(
            "project_changed",
            {
                "action": "shot_prompt_patched",
                "projectId": project_id,
                "episodeId": result.get("episodeId") or episode_id,
                "nodeId": workflow_patch.get("nodeId") or result.get("nodeId"),
                "node": workflow_patch.get("node") if isinstance(workflow_patch.get("node"), dict) else None,
                "workflowVersion": workflow_patch.get("workflowVersion"),
                **_canvas_mutation_event_fields(workflow_patch),
                "changedResources": _merge_changed_resources(result, workflow_patch),
                "focusTarget": result.get("focusTarget"),
                "productionStatus": workflow_patch.get("productionStatus")
                if isinstance(workflow_patch.get("productionStatus"), dict)
                else None,
            },
        )
    return result


@sdk.handler("upsert_workflow_node")
def handle_upsert_workflow_node(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.upsert_workflow_node, project_id, episode_id, params)
    if result.get("success"):
        event_payload = {
            "action": "workflow_item_upserted",
            "projectId": project_id,
            "episodeId": episode_id,
            "itemType": result.get("itemType"),
            "itemId": (result.get("item") or {}).get("id") if isinstance(result.get("item"), dict) else None,
            "item": result.get("item") if isinstance(result.get("item"), dict) else None,
            "workflowVersion": result.get("workflowVersion"),
            **_canvas_mutation_event_fields(result),
            "changedResources": _canvas_event_changed_resources(result, []),
            "focusTarget": result.get("focusTarget"),
        }
        if not isinstance(event_payload.get("item"), dict):
            event_payload["workflowOmitted"] = "workflow" not in result
        _send_event("project_changed", event_payload)
    return result


@sdk.handler("rename_workflow_asset_node")
def handle_rename_workflow_asset_node(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.rename_workflow_asset_node, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        event_payload = {
            "action": "workflow_asset_node_renamed",
            "projectId": project_id,
            "episodeId": episode_id,
            "nodeId": result.get("nodeId"),
            "itemType": result.get("itemType") or "node",
            "itemId": (result.get("item") or {}).get("id") if isinstance(result.get("item"), dict) else result.get("nodeId"),
            "item": result.get("item") if isinstance(result.get("item"), dict) else None,
            "node": result.get("node") if isinstance(result.get("node"), dict) else None,
            "workflowVersion": result.get("workflowVersion"),
            **_canvas_mutation_event_fields(result),
            "changedResources": _canvas_event_changed_resources(result, []),
            "focusTarget": result.get("focusTarget"),
        }
        _send_event("project_changed", event_payload)
    return result


@sdk.handler("create_workflow_task_card")
def handle_create_workflow_task_card(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.create_workflow_task_card, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event(
            "project_changed",
            {
                "action": "workflow_task_card_created",
                "projectId": project_id,
                "episodeId": episode_id,
                "nodeId": (result.get("node") or {}).get("id")
                if isinstance(result.get("node"), dict)
                else None,
                "node": result.get("node") if isinstance(result.get("node"), dict) else None,
                "resultNode": result.get("resultNode") if isinstance(result.get("resultNode"), dict) else None,
                "edge": result.get("edge") if isinstance(result.get("edge"), dict) else None,
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(result, []),
                "focusTarget": result.get("focusTarget"),
            },
        )
    return result


@sdk.handler("add_workflow_asset_nodes")
def handle_add_workflow_asset_nodes(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.add_workflow_asset_nodes, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event(
            "project_changed",
            {
                "action": "workflow_asset_nodes_added",
                "projectId": project_id,
                "episodeId": episode_id,
                "nodes": result.get("nodes") if isinstance(result.get("nodes"), list) else [],
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(result, []),
                "focusTarget": result.get("focusTarget"),
            },
        )
    return result


@sdk.handler("paste_workflow_asset_node")
def handle_paste_workflow_asset_node(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.paste_workflow_asset_node, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event(
            "project_changed",
            {
                "action": "workflow_asset_nodes_added",
                "projectId": project_id,
                "episodeId": episode_id,
                "nodes": result.get("nodes") if isinstance(result.get("nodes"), list) else [],
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(result, []),
                "focusTarget": result.get("focusTarget"),
            },
        )
    return result


@sdk.handler("update_workflow_route")
def handle_update_workflow_route(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.update_workflow_route, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        event_payload = {
            "action": "workflow_route_updated",
            "projectId": project_id,
            "episodeId": episode_id,
            "routeId": (result.get("route") or {}).get("id")
            if isinstance(result.get("route"), dict)
            else None,
            "route": result.get("route") if isinstance(result.get("route"), dict) else None,
            "workflowVersion": result.get("workflowVersion"),
            **_canvas_mutation_event_fields(result),
            "changedResources": _canvas_event_changed_resources(result, []),
            "focusTarget": result.get("focusTarget"),
        }
        if not isinstance(event_payload.get("route"), dict):
            event_payload["workflowOmitted"] = "workflow" not in result
        _send_event("project_changed", event_payload)
    return result


@sdk.handler("list_workflow_media")
def handle_list_workflow_media(params):
    params = params or {}
    return _ok(
        store.list_workflow_media,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
    )


@sdk.handler("link_workflow_input")
def handle_link_workflow_input(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.link_workflow_input, project_id, episode_id, params)
    if result.get("success"):
        event_payload = {
            "action": "workflow_input_linked",
            "projectId": project_id,
            "episodeId": episode_id,
            "inputLinkId": (result.get("inputLink") or {}).get("id")
            if isinstance(result.get("inputLink"), dict)
            else None,
            "inputLink": result.get("inputLink") if isinstance(result.get("inputLink"), dict) else None,
            "node": result.get("node") if isinstance(result.get("node"), dict) else None,
            "nodes": result.get("nodes") if isinstance(result.get("nodes"), list) else [],
            "edge": result.get("edge") if isinstance(result.get("edge"), dict) else None,
            "removedEdgeIds": result.get("removedEdgeIds") if isinstance(result.get("removedEdgeIds"), list) else [],
            "targetNodeId": result.get("targetNodeId"),
            "workflowVersion": result.get("workflowVersion"),
            "productionStatus": result.get("productionStatus"),
            **_canvas_mutation_event_fields(result),
            "changedResources": _canvas_event_changed_resources(
                result,
                ["canvas_node", "canvas_edge"],
            ),
        }
        if not any(isinstance(event_payload.get(key), dict) for key in ("inputLink", "node", "edge")):
            event_payload["workflowOmitted"] = "workflow" not in result
        _send_event("project_changed", event_payload)
    return result


@sdk.handler("set_workflow_reference_usage")
def handle_set_workflow_reference_usage(params):
    from project_store_services.workflow_input_links import set_workflow_reference_usage
    params = params or {}
    project_id, episode_id = params.get("projectId"), params.get("episodeId")
    result = _ok(set_workflow_reference_usage, project_id, episode_id, params)
    if result.get("success"):
        _send_event("project_changed", {
            **result, "action": "workflow_reference_usage_updated",
            "projectId": project_id, "episodeId": episode_id,
        })
    return result


@sdk.handler("unlink_workflow_input")
def handle_unlink_workflow_input(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.unlink_workflow_input, project_id, episode_id, params)
    if result.get("success"):
        event_payload = {
            "action": "workflow_input_unlinked",
            "projectId": project_id,
            "episodeId": episode_id,
            "removedLinks": result.get("removedLinks") if isinstance(result.get("removedLinks"), list) else [],
            "removedLinkIds": result.get("removedLinkIds") if isinstance(result.get("removedLinkIds"), list) else [],
            "removedEdgeIds": result.get("removedEdgeIds") if isinstance(result.get("removedEdgeIds"), list) else [],
            "node": result.get("node") if isinstance(result.get("node"), dict) else None,
            "nodes": result.get("nodes") if isinstance(result.get("nodes"), list) else [],
            "targetNodeId": result.get("targetNodeId"),
            "workflowVersion": result.get("workflowVersion"),
            "productionStatus": result.get("productionStatus"),
            **_canvas_mutation_event_fields(result),
            "changedResources": _canvas_event_changed_resources(
                result,
                ["canvas_node", "canvas_edge"],
            ),
        }
        if not event_payload["removedLinkIds"] and not isinstance(event_payload.get("node"), dict):
            event_payload["workflowOmitted"] = "workflow" not in result
        _send_event("project_changed", event_payload)
    return result


@sdk.handler("list_workflow_inputs")
def handle_list_workflow_inputs(params):
    params = params or {}
    return _ok(
        store.list_workflow_inputs,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("resolve_workflow_node_inputs")
def handle_resolve_workflow_node_inputs(params):
    params = params or {}
    return _ok(
        store.resolve_workflow_node_inputs,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("list_workflow_tasks")
def handle_list_workflow_tasks(params):
    params = params or {}
    return _ok(
        store.list_workflow_tasks,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )






@sdk.handler("run_workflow_batch")
def handle_run_workflow_batch(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.run_workflow_batch, project_id, episode_id, params)
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "workflow_batch_generated",
                "projectId": project_id,
                "episodeId": episode_id,
                "nodeId": params.get("nodeId") or params.get("node_id"),
                "batchId": result.get("batchId"),
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(
                    result,
                    ["canvas_task", "canvas_version"],
                ),
            },
        )
    return result


@sdk.handler("save_variant_quality_result")
def handle_save_variant_quality_result(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.save_variant_quality_result, project_id, episode_id, params)
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "variant_quality_result_saved",
                "projectId": project_id,
                "episodeId": episode_id,
                "nodeId": params.get("nodeId") or params.get("node_id"),
                "versionId": params.get("versionId") or params.get("version_id"),
                "version": result.get("version") if isinstance(result.get("version"), dict) else None,
                "node": result.get("node") if isinstance(result.get("node"), dict) else None,
                "qualityResult": result.get("qualityResult") if isinstance(result.get("qualityResult"), dict) else None,
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(
                    result,
                    ["variant_quality_results", "canvas_version", "canvas_node"],
                ),
                "focusTarget": result.get("focusTarget"),
            },
        )
    return result


@sdk.handler("auto_review_variant_quality")
def handle_auto_review_variant_quality(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.auto_review_variant_quality, project_id, episode_id, params)
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "variant_quality_auto_reviewed",
                "projectId": project_id,
                "episodeId": episode_id,
                "nodeId": params.get("nodeId") or params.get("node_id"),
                "versionId": params.get("versionId") or params.get("version_id"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(
                    result,
                    [
                        "variant_quality_results",
                        "canvas_version",
                        "canvas_node",
                        "episode_production_status",
                    ],
                ),
            },
        )
    return result


@sdk.handler("get_storyboard_consistency_report")
def handle_get_storyboard_consistency_report(params):
    from project_store_services.workflow_variant_quality import get_storyboard_consistency_report

    params = params or {}
    return _ok(get_storyboard_consistency_report, params.get("projectId"), params.get("episodeId"), params)


@sdk.handler("get_storyboard_correction_context")
def handle_get_storyboard_correction_context(params):
    from utils.storyboard_consistency_correction import get_correction_context
    params = params or {}
    return _ok(get_correction_context, params.get("projectId"), params.get("episodeId"), params)


@sdk.handler("start_storyboard_correction")
def handle_start_storyboard_correction(params):
    from utils.storyboard_consistency_correction import start_correction
    params = params or {}
    return _ok(start_correction, params.get("projectId"), params.get("episodeId"), params)


@sdk.handler("start_storyboard_consistency_check")
def handle_start_storyboard_consistency_check(params):
    from project_store_services.workflow_variant_quality import start_storyboard_consistency_check
    params = params or {}
    return _ok(start_storyboard_consistency_check, params.get("projectId"), params.get("episodeId"), params)


@sdk.handler("import_workflow_media")
def handle_import_workflow_media(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.import_workflow_media, project_id, episode_id, params)
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "workflow_media_imported",
                "projectId": project_id,
                "episodeId": episode_id,
                "mediaId": (result.get("mediaRecord") or {}).get("id")
                if isinstance(result.get("mediaRecord"), dict)
                else None,
                "node": result.get("node") if isinstance(result.get("node"), dict) else None,
                "nodes": result.get("nodes") if isinstance(result.get("nodes"), list) else [],
                "edge": result.get("edge") if isinstance(result.get("edge"), dict) else None,
                "removedEdgeIds": result.get("removedEdgeIds") if isinstance(result.get("removedEdgeIds"), list) else [],
                "inputLink": result.get("inputLink") if isinstance(result.get("inputLink"), dict) else None,
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(
                    result,
                    ["workflow_media", "canvas_node", "canvas_edge"],
                ),
                "focusTarget": result.get("focusTarget"),
            },
        )
    return result


@sdk.handler("save_clipboard_image_media")
def handle_save_clipboard_image_media(params):
    params = params or {}
    return _ok(
        store.save_clipboard_image_media,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("get_video_clip_info")
def handle_get_video_clip_info(params):
    params = params or {}
    return _ok(
        store.get_video_clip_info,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("list_video_clip_results")
def handle_list_video_clip_results(params):
    params = params or {}
    return _ok(
        store.list_video_clip_results,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("delete_video_clip_results")
def handle_delete_video_clip_results(params):
    params = params or {}
    return _ok(
        store.delete_video_clip_results,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("extract_video_frame_preview")
def handle_extract_video_frame_preview(params):
    params = params or {}
    return _ok(
        store.extract_video_frame_preview,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("extract_video_frame")
def handle_extract_video_frame(params):
    params = params or {}
    return _ok(
        store.extract_video_frame,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("trim_video_clip")
def handle_trim_video_clip(params):
    params = params or {}
    return _ok(
        store.trim_video_clip,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("get_episode_production_status")
def handle_get_episode_production_status(params):
    params = params or {}
    return _ok(
        store.get_episode_production_status,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
    )


@sdk.handler("update_episode_production_status")
def handle_update_episode_production_status(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.update_episode_production_status, project_id, episode_id)
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "episode_production_status_updated",
                "projectId": project_id,
                "episodeId": episode_id,
                "productionStatus": result.get("status"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(
                    result,
                    ["episode_production_status", "canvas_projection"],
                ),
            },
        )
    return result




@sdk.handler("create_workflow_node")
def handle_create_workflow_node(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    node_type = params.get("nodeType") or params.get("node_type") or params.get("type") or "custom"
    result = _ok(store.create_workflow_node, project_id, episode_id, node_type, params.get("node"))
    if result.get("success"):
        event_payload = {
            "action": "workflow_item_upserted",
            "projectId": project_id,
            "episodeId": episode_id,
            "itemType": "node",
            "itemId": (result.get("node") or {}).get("id") if isinstance(result.get("node"), dict) else None,
            "item": result.get("node") if isinstance(result.get("node"), dict) else None,
            "node": result.get("node") if isinstance(result.get("node"), dict) else None,
            "workflowVersion": result.get("workflowVersion"),
            **_canvas_mutation_event_fields(result),
            "changedResources": _canvas_event_changed_resources(result, ["canvas_node"]),
            "focusTarget": result.get("focusTarget"),
        }
        if not isinstance(event_payload.get("node"), dict):
            event_payload["workflowOmitted"] = "workflow" not in result
        _send_event("project_changed", event_payload)
    return result


@sdk.handler("resolve_generation_config")
def handle_resolve_generation_config(params):
    params = params or {}
    return _ok(
        store.resolve_generation_config,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("preflight_workflow_node")
def handle_preflight_workflow_node(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    result = _ok(store.preflight_workflow_node, project_id, episode_id, params)
    if result.get("success") or result.get("preflight"):
        _send_event(
            "project_changed",
            {
                "action": "workflow_node_preflight_checked",
                "projectId": project_id,
                "episodeId": episode_id,
                "nodeId": params.get("nodeId") or params.get("node_id"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(result, ["canvas_node"]),
            },
        )
    return result


@sdk.handler("validate_project_quality")
def handle_validate_project_quality(params):
    params = params or {}
    return _ok(
        store.validate_project_quality,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
    )


@sdk.handler("delete_workflow_node")
def handle_delete_workflow_node(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    item_id = params.get("itemId") or params.get("item_id") or params.get("nodeId") or params.get("node_id")
    user_payload = {
        **{
            key: value
            for key, value in params.items()
            if key not in {"returnWorkflow", "return_workflow", "includeWorkflow", "include_workflow"}
        },
        "source": "user",
        "versionSource": "user",
        "version_source": "user",
    }
    result = _ok(store.delete_workflow_item, project_id, episode_id, user_payload)
    if result.get("success") and result.get("projectChanged"):
        _send_event(
            "project_changed",
            {
                "action": "workflow_item_deleted",
                "projectId": project_id,
                "episodeId": episode_id,
                "itemType": result.get("itemType") or params.get("itemType") or "node",
                "itemId": item_id,
                "deletedNodeIds": result.get("deletedNodeIds") if isinstance(result.get("deletedNodeIds"), list) else [],
                "deletedRouteIds": result.get("deletedRouteIds") if isinstance(result.get("deletedRouteIds"), list) else [],
                "deletedWorkChainIds": result.get("deletedWorkChainIds") if isinstance(result.get("deletedWorkChainIds"), list) else [],
                "deletedEdgeIds": result.get("deletedEdgeIds") if isinstance(result.get("deletedEdgeIds"), list) else [],
                "removedInputLinkIds": result.get("removedInputLinkIds") if isinstance(result.get("removedInputLinkIds"), list) else [],
                "inputDirtyNodeIds": result.get("inputDirtyNodeIds") if isinstance(result.get("inputDirtyNodeIds"), list) else [],
                "syncedVideoTaskNodeIds": result.get("syncedVideoTaskNodeIds") if isinstance(result.get("syncedVideoTaskNodeIds"), list) else [],
                "nodes": result.get("nodes") if isinstance(result.get("nodes"), list) else [],
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(result, []),
                "focusTarget": result.get("focusTarget"),
            },
        )
    return result


@sdk.handler("delete_workflow_nodes")
def handle_delete_workflow_nodes(params):
    from utils.canvas_selection import delete_canvas_selection
    params = params or {}
    project_id, episode_id = params.get("projectId"), params.get("episodeId")
    result = _ok(delete_canvas_selection, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event("project_changed", {
            **result, "action": "workflow_item_deleted", "projectId": project_id, "episodeId": episode_id,
            **_canvas_mutation_event_fields(result),
        })
    return result


@sdk.handler("update_workflow_nodes_layout")
def handle_update_workflow_nodes_layout(params):
    from utils.canvas_selection import update_canvas_selection_layout
    params = params or {}
    project_id, episode_id = params.get("projectId"), params.get("episodeId")
    result = _ok(update_canvas_selection_layout, project_id, episode_id, params)
    if result.get("success") and result.get("projectChanged"):
        _send_event("project_changed", {
            **result, "action": "workflow_node_layout_updated", "projectId": project_id, "episodeId": episode_id,
            **_canvas_mutation_event_fields(result),
        })
    return result


def _finish_generation_task(task_type, params, version_type=None):
    params = params or {}
    node_id = params.get("nodeId") or params.get("node_id")
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    client_request_id = params.get("clientRequestId") or params.get("client_request_id")
    generation_config, generation_config_provided = _generation_config_request(params, task_type)
    payload_overrides = params if task_type == "storyboard_video" else None
    user_instruction = _generation_instruction_request(params)
    return store.run_storyboard_generation_task(
        task_type,
        project_id=project_id,
        episode_id=episode_id,
        node_id=node_id,
        version_type=version_type,
        user_instruction=user_instruction,
        generation_config=generation_config,
        generation_config_provided=generation_config_provided,
        payload_overrides=payload_overrides,
        client_request_id=client_request_id,
    )


@sdk.handler("generate_storyboard_image")
def handle_generate_storyboard_image(params):
    return _finish_generation_task("storyboard_image", params, "image")


@sdk.handler("generate_visual_handoff_image")
def handle_generate_visual_handoff_image(params):
    return _finish_generation_task("visual_handoff_image", params, "image")


@sdk.handler("upload_storyboard_image")
def handle_upload_storyboard_image(params):
    params = params or {}
    return _ok(
        store.upload_storyboard_image,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params.get("nodeId") or params.get("node_id"),
        params,
    )


@sdk.handler("edit_storyboard_image")
def handle_edit_storyboard_image(params):
    params = params or {}
    result = _ok(
        store.edit_storyboard_image,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params.get("nodeId") or params.get("node_id"),
        params,
    )
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "storyboard_image_edited",
                "projectId": result.get("projectId") or params.get("projectId") or params.get("project_id"),
                "episodeId": result.get("episodeId") or params.get("episodeId") or params.get("episode_id"),
                "nodeId": result.get("nodeId") or params.get("nodeId") or params.get("node_id"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(
                    result,
                    ["canvas_version", "canvas_node"],
                ),
            },
        )
    return result


@sdk.handler("generate_storyboard_video")
def handle_generate_storyboard_video(params):
    return _finish_generation_task("storyboard_video", params, "video")


@sdk.handler("generate_keyframe_image")
def handle_generate_keyframe_image(params):
    params = params or {}
    return _ok(
        store.request_keyframe_image_generation,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params,
    )


@sdk.handler("generate_keyframe_video")
def handle_generate_keyframe_video(params):
    return _finish_generation_task("storyboard_video", params, "video")


@sdk.handler("generate_route_video")
def handle_generate_route_video(params):
    return _finish_generation_task("storyboard_video", params, "video")


@sdk.handler("run_workflow_from_node")
def handle_run_workflow_from_node(params):
    return _finish_generation_task("workflow", params)


@sdk.handler("list_storyboard_versions")
def handle_list_storyboard_versions(params):
    params = params or {}
    return _ok(
        store.list_storyboard_versions,
        params.get("projectId") or params.get("project_id"),
        params.get("episodeId") or params.get("episode_id"),
        params.get("nodeId") or params.get("node_id"),
    )


@sdk.handler("set_storyboard_result_active_version")
def handle_set_storyboard_result_active_version(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    node_id = params.get("nodeId") or params.get("node_id")
    version_id = params.get("versionId") or params.get("version_id")
    result_node_id = params.get("resultNodeId") or params.get("result_node_id") or ""
    result = _ok(
        store.set_storyboard_result_active_version,
        project_id,
        episode_id,
        node_id,
        version_id,
        result_node_id,
    )
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "storyboard_result_version_activated",
                "projectId": project_id,
                "episodeId": episode_id,
                "nodeId": node_id,
                "resultNodeId": result.get("resultNodeId") or result_node_id,
                "versionId": version_id,
                "version": result.get("version") if isinstance(result.get("version"), dict) else None,
                "node": result.get("node") if isinstance(result.get("node"), dict) else None,
                "nodes": result.get("nodes") if isinstance(result.get("nodes"), list) else [],
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(
                    result,
                    ["canvas_node", "canvas_version"],
                ),
                "focusTarget": result.get("focusTarget"),
            },
        )
        _send_visual_handoff_cross_episode_event(result, project_id, episode_id, node_id, version_id)
    return result


@sdk.handler("select_workflow_variant")
def handle_select_workflow_variant(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    node_id = params.get("nodeId") or params.get("node_id")
    version_id = params.get("versionId") or params.get("version_id")
    reason = params.get("reason") or params.get("selectionReason") or params.get("selection_reason")
    result = _ok(
        store.select_workflow_variant,
        project_id,
        episode_id,
        node_id,
        version_id,
        reason,
        params,
    )
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "workflow_variant_selected",
                "projectId": project_id,
                "episodeId": episode_id,
                "nodeId": node_id,
                "versionId": version_id,
                "version": result.get("version") if isinstance(result.get("version"), dict) else None,
                "node": result.get("node") if isinstance(result.get("node"), dict) else None,
                "nodes": result.get("nodes") if isinstance(result.get("nodes"), list) else [],
                "workflowVersion": result.get("workflowVersion"),
                "productionStatus": result.get("productionStatus"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(
                    result,
                    ["canvas_node", "canvas_version", "episode_production_status"],
                ),
                "focusTarget": result.get("focusTarget"),
            },
        )
    return result


@sdk.handler("delete_storyboard_version")
def handle_delete_storyboard_version(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    episode_id = params.get("episodeId") or params.get("episode_id")
    node_id = params.get("nodeId") or params.get("node_id")
    version_id = params.get("versionId") or params.get("version_id")
    result = _ok(
        store.delete_storyboard_version,
        project_id,
        episode_id,
        node_id,
        version_id,
    )
    if result.get("success"):
        _send_event(
            "project_changed",
            {
                "action": "storyboard_version_deleted",
                "projectId": project_id,
                "episodeId": episode_id,
                "nodeId": node_id,
                "versionId": version_id,
                "nodes": result.get("nodes") if isinstance(result.get("nodes"), list) else [],
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": _canvas_event_changed_resources(
                    result,
                    ["canvas_node", "canvas_version"],
                ),
            },
        )
    return result


@sdk.handler("diagnose_storyboard_task")
def handle_diagnose_storyboard_task(params):
    return _ok(store.diagnose_task, (params or {}).get("taskId") or (params or {}).get("task_id"))


@sdk.handler("list_tasks")
def handle_list_tasks(params):
    return _ok(store.list_tasks, params or {})


@sdk.handler("clear_task_notifications")
def handle_clear_task_notifications(params):
    params = params or {}
    project_id = params.get("projectId") or params.get("project_id")
    result = _ok(store.clear_task_notifications, project_id)
    if result.get("success"):
        _send_event(
            "task_notifications_cleared",
            {
                "projectId": project_id,
                "cleared": result.get("cleared") or 0,
            },
        )
    return result


@sdk.handler("cancel_task")
def handle_cancel_task(params):
    return _ok(store.cancel_task, (params or {}).get("taskId") or (params or {}).get("task_id"))


@sdk.handler("get_usage_summary")
def handle_get_usage_summary(params):
    return _ok(store.get_usage_summary)


@sdk.handler("export_project_assets")
def handle_export_project_assets(params):
    params = params or {}
    return _ok(
        store.export_project_assets,
        params.get("projectId") or params.get("project_id"),
        params.get("scopes") or [],
    )


@sdk.handler("get_jianying_export_info")
def handle_get_jianying_export_info(params):
    params = params or {}
    return _ok(
        store.get_jianying_export_info,
        params.get("projectId") or params.get("project_id"),
    )


@sdk.handler("detect_jianying_draft_root")
def handle_detect_jianying_draft_root(params):
    _ = params
    return _ok(store.detect_jianying_draft_root)


@sdk.handler("start_jianying_draft_export")
def handle_start_jianying_draft_export(params):
    return _ok(store.start_jianying_draft_export, params or {})


@sdk.handler("start_video_files_export")
def handle_start_video_files_export(params):
    return _ok(store.start_video_files_export, params or {})


@sdk.handler("analyze_style_image")
def handle_analyze_style_image(params):
    params = params or {}
    return _ok(
        store.analyze_style_image,
        params.get("file"),
        params.get("projectId") or params.get("project_id"),
    )


@sdk.handler("upload_style_image")
def handle_upload_style_image(params):
    params = params or {}
    return _ok(
        store.upload_style_image,
        params.get("projectId") or params.get("project_id"),
        params.get("file") or {},
        params.get("styleDescription") or params.get("style_description") or "",
    )


@sdk.handler("create_favorite_style_template")
def handle_create_favorite_style_template(params):
    return _ok(store.create_favorite_style_template, params or {})


@sdk.handler("delete_favorite_style_template")
def handle_delete_favorite_style_template(params):
    return _ok(store.delete_favorite_style_template, (params or {}).get("templateId") or (params or {}).get("template_id"))


@sdk.handler("update_favorite_style_template")
def handle_update_favorite_style_template(params):
    return _ok(store.update_favorite_style_template, params or {})
