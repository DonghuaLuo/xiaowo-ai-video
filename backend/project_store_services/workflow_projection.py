# -*- coding: utf-8 -*-
"""工作流画布投影、初始化和布局。

本模块负责把工作链规划投影为画布记录，并提供读取、初始化和布局
相关操作，直接依赖契约、输入解析和视觉交接领域。
"""

from __future__ import annotations
from .reference_read_context import ReferenceReadContext

from .canvas_store_mutations import write_canvas_card_records_v4
from .canvas_store_queries import get_canvas_records_v4
from .canvas_store_queries import read_canvas_card_record_v4
from .projects import _touch_project_meta
from .store_core import _JSON_WRITE_LOCK
from .workflow_contract import _ensure_saved_workflow_node_contract
from typing import Any
import copy

import threading
from .canvas_store_queries import read_canvas_task_records_v4
from .canvas_store_documents import write_canvas_task_records_v4
from .workflow_planning_lifecycle import (
    _safe_episode_id,
)

import uuid
import traceback
from pathlib import Path
from .agent_sessions import _project_dir
from .canvas_ownership import (
    source_work_chain_ids,
    work_chain_scope,
)
from .canvas_reference_views import (
    REFERENCE_NODE_TYPES,
    REFERENCE_VIEW_FIELDS,
)
from .canvas_store_records import empty_canvas_workflow_projection_v4
from .canvas_store_queries import episode_canvas_exists, get_canvas_context_v4, read_canvas_visual_handoff_result_node_v4, read_canvas_workflow_projection_v4
from .canvas_store_mutations import replace_canvas_records_from_workflow_projection_v4, write_canvas_records_v4
from .perf_logging import (
    canvas_perf_elapsed_ms,
    canvas_perf_log,
    canvas_perf_start,
)
from .asset_reference_scope import _auto_bind_shot_plan_asset_refs, _normalize_shot_plan_asset_refs, _trusted_context_provenance_for_episode, _validate_plan_asset_refs, _validate_workflow_asset_refs
from .planning_workflow_layout import _layout_workflow_by_work_chain
from .planning_contract import _safe_workflow_id
from .source_reference_scope import _stamp_source_units_on_shot_plan, _stamp_source_units_on_workflow, _validate_shot_plan_source_refs
from .video_task_card_references import (
    _workflow_input_thumbnail_for_display,
    video_task_card_current_reference_snapshot,
)
from .planning_workflow_builder import _work_chain_plan_to_workflow
from .project_management import get_effective_config
from .store_core import (
    _now,
    _read_json,
    _write_json,
)
from .workflow_contract import (
    _assert_user_workflow_save_keeps_protected_items,
    _ensure_saved_workflow_contract,
    _normalize_workflow_work_chain_route_fields,
    _translate_workflow_layout,
    _workflow_is_video_task_type,
    _workflow_mutation_event_fields,
    _workflow_node,
    _workflow_unique_id,
)
from .workflow_input_resolution import (
    _populate_workflow_video_reference_views,
    _resolve_workflow_node_inputs_from_workflow,
    _workflow_active_card_version,
)
from .workflow_visual_handoff import (
    _next_project_episode_id,
    _previous_project_episode_id,
    _workflow_episode_storyboard_card_boundary_node,
    sync_visual_handoff_cross_episode_link,
)


def _workflow_state(project_id: str, episode_id: str, workflow: dict[str, Any] | None, reason: str) -> dict[str, Any]:
    if isinstance(workflow, dict) and workflow.get("canvasKind") == "custom":
        return {
            "kind": "custom", "reason": reason, "sourceReady": False,
            "workChainPlanReady": False, "workflowChainReady": bool(workflow.get("workChains")),
            "nextAction": "run_workflow" if workflow.get("workChains") else "edit_custom_canvas",
        }
    source_ready = _episode_source_ready(project_id, episode_id)
    production_status = (
        workflow.get("productionStatus")
        if isinstance(workflow, dict) and isinstance(workflow.get("productionStatus"), dict)
        else {}
    )
    production_state = str(
        production_status.get("currentState")
        or ""
    ).strip()
    has_real_nodes = bool(isinstance(workflow, dict) and workflow.get("nodes"))
    work_chain_plan_ready = _work_chain_plan_ready(project_id, episode_id)
    workflow_chain_ready = has_real_nodes
    kind = "ready" if has_real_nodes else "empty"
    if has_real_nodes:
        overall_status = str(production_status.get("overallStatus") or "").strip()
        if overall_status == "ready":
            next_action = "review_or_continue_next_episode"
        else:
            next_action = _WORKFLOW_NEXT_ACTION_BY_PRODUCTION_STATE.get(production_state) or "run_workflow"
    else:
        next_action = "build_workflow_chain" if (source_ready or work_chain_plan_ready) else "commit_episode_source"
    return {
        "kind": kind,
        "reason": reason,
        "sourceReady": source_ready,
        "workChainPlanReady": work_chain_plan_ready,
        "workflowChainReady": workflow_chain_ready,
        **({"productionState": production_state} if production_state else {}),
        "nextAction": next_action,
    }


def empty_episode_workflow(project_id: str, episode_id: str, reason: str = "missing_workflow") -> dict[str, Any]:
    workflow = empty_canvas_workflow_projection_v4(project_id, episode_id, reason)
    workflow["state"] = _workflow_state(project_id, episode_id, None, reason)
    return workflow


def _populate_workflow_video_reference_views_for_read(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
) -> None:
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        return
    video_node_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        if _workflow_is_video_task_type(str(node.get("type") or "")):
            video_node_ids.add(node_id)
    if video_node_ids:
        _populate_workflow_video_reference_views(project_id, episode_id, workflow, video_node_ids)


def _populate_workflow_material_reference_views(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    *,
    read_context: ReferenceReadContext | None = None,
) -> set[str]:
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        return set()
    normalized_node_ids = {
        str(node_id or "").strip()
        for node_id in (node_ids if isinstance(node_ids, (set, list, tuple)) else [])
        if str(node_id or "").strip()
    }
    synced_node_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        node_type = str(node.get("type") or "").strip()
        if not node_id or node_type not in {"director.board", "storyboard.card"}:
            continue
        if normalized_node_ids and node_id not in normalized_node_ids:
            continue
        data = node.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            node["data"] = data
        before = {
            key: copy.deepcopy(data.get(key))
            for key in _WORKFLOW_MATERIAL_INPUT_REFERENCE_SYNC_KEYS
        }
        input_snapshot = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, node_id, read_context=read_context)
        input_links = [
            _workflow_input_thumbnail_for_display(project_id, link)
            for link in (input_snapshot.get("inputLinks") or [])
            if isinstance(link, dict)
        ]
        reference_snapshot = video_task_card_current_reference_snapshot(
            project_id,
            episode_id,
            workflow,
            node_id,
            input_snapshot=input_snapshot,
            read_context=read_context,
        )
        next_fields = {
            "referenceDisplayRows": copy.deepcopy(reference_snapshot["referenceDisplayRows"]),
            "inputLinks": input_links,
            "assetThumbnails": copy.deepcopy(reference_snapshot.get("assetThumbnails") or input_links),
            "referenceThumbnails": copy.deepcopy(reference_snapshot.get("referenceThumbnails") or []),
            "referenceVideoThumbnails": copy.deepcopy(reference_snapshot.get("referenceVideoThumbnails") or []),
            "referenceManifest": copy.deepcopy(reference_snapshot.get("referenceManifest") or []),
            "referenceMediaIds": copy.deepcopy(reference_snapshot.get("referenceMediaIds") or input_snapshot.get("referenceMediaIds") or []),
            "assetRefs": copy.deepcopy(reference_snapshot.get("assetRefs") or input_snapshot.get("assetRefs") or {}),
            "assetRefsResolvedByInputLinks": bool(
                reference_snapshot.get("assetRefsResolvedByInputLinks")
                or input_snapshot.get("assetRefsResolvedByInputLinks")
            ),
            "inputContract": copy.deepcopy(input_snapshot.get("inputContract") or {}),
            "needsRelink": copy.deepcopy(input_snapshot.get("needsRelink") or []),
        }
        for key, value in next_fields.items():
            data[key] = value
        if any(before.get(key) != data.get(key) for key in _WORKFLOW_MATERIAL_INPUT_REFERENCE_SYNC_KEYS):
            synced_node_ids.add(node_id)
    return synced_node_ids


def _populate_workflow_material_reference_views_for_read(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
) -> None:
    _populate_workflow_material_reference_views(project_id, episode_id, workflow)


def get_canvas_workflow_projection(project_id: str, episode_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    perf_started_at = canvas_perf_start()
    status = "ok"
    node_count = 0
    edge_count = 0
    route_count = 0
    work_chain_count = 0
    reference_sync_ms = 0.0
    payload = payload if isinstance(payload, dict) else {}
    detail = str(payload.get("detail") or payload.get("mode") or "").strip().lower()
    if detail not in {"summary", "full"}:
        detail = "full"
    sync_references = _workflow_payload_flag(payload.get("syncReferences")) or _workflow_payload_flag(
        payload.get("sync_references")
    )
    try:
        if not episode_canvas_exists(project_id, episode_id):
            status = "missing_canvas"
            return empty_episode_workflow(project_id, episode_id)
        workflow = read_canvas_workflow_projection_v4(
            project_id,
            episode_id,
            detail=detail,
        )
        if not isinstance(workflow, dict) or not workflow:
            status = "invalid_canvas"
            return empty_episode_workflow(project_id, episode_id, "invalid_canvas")
        _normalize_workflow_work_chain_route_fields(workflow)
        if detail == "full" and sync_references:
            sync_started_at = canvas_perf_start()
            _populate_workflow_material_reference_views_for_read(project_id, episode_id, workflow)
            _populate_workflow_video_reference_views_for_read(project_id, episode_id, workflow)
            reference_sync_ms = canvas_perf_elapsed_ms(sync_started_at)
        nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
        edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
        routes = workflow.get("routes") if isinstance(workflow.get("routes"), list) else []
        work_chains = workflow.get("workChains") if isinstance(workflow.get("workChains"), list) else []
        node_count = len(nodes)
        edge_count = len(edges)
        route_count = len(routes)
        work_chain_count = len(work_chains)
        workflow.setdefault("episodeId", episode_id)
        workflow["state"] = _workflow_state(project_id, episode_id, workflow, "loaded")
        return workflow
    except Exception:
        status = "error"
        raise
    finally:
        canvas_perf_log(
            "get_canvas_workflow_projection",
            projectId=project_id,
            episodeId=episode_id,
            detail=detail,
            syncReferences=sync_references,
            status=status,
            durationMs=canvas_perf_elapsed_ms(perf_started_at),
            nodeCount=node_count,
            edgeCount=edge_count,
            routeCount=route_count,
            workChainCount=work_chain_count,
            referenceSyncMs=reference_sync_ms,
        )


def get_canvas_reference_views(project_id: str, episode_id: str) -> dict[str, Any]:
    workflow = read_canvas_workflow_projection_v4(project_id, episode_id, detail="full")
    ids = {node["id"] for node in workflow.get("nodes", []) if node.get("type") in REFERENCE_NODE_TYPES}
    if ids:
        with ReferenceReadContext(project_id) as read_context:
            _populate_workflow_material_reference_views(project_id, episode_id, workflow, ids, read_context=read_context)
            _populate_workflow_video_reference_views(project_id, episode_id, workflow, ids, read_context=read_context)
    views = []
    for node in workflow.get("nodes", []):
        if node.get("id") not in ids:
            continue
        data = node.get("data") or {}
        defaults = {"assetRefsResolvedByInputLinks": False, "inputContract": {}}
        fields = {key: copy.deepcopy(data.get(key, defaults.get(key, []))) for key in REFERENCE_VIEW_FIELDS}
        views.append({"nodeId": node["id"], "data": fields})
    return {"success": True, "episodeId": episode_id, "revision": workflow["version"], "views": views}


def build_episode_workflow_from_work_chain_plan(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    context = get_canvas_context_v4(project_id, episode_id)
    if context["canvasKind"] == "custom":
        raise ValueError("自定义画布不支持原文工作链初始化")
    if context["autoWorkflowInitialized"]:
        raise ValueError("当前画布已完成自动初始化，不能重复生成工作链")
    shot_plan = {}
    for key in (
        "workChainPlan",
        "work_chain_plan",
        "episodeWorkChainPlan",
        "episode_work_chain_plan",
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            shot_plan = copy.deepcopy(value)
            break
    if not shot_plan:
        shot_plan = _read_json(_work_chain_plan_path(project_id, episode_id), {})
    if not isinstance(shot_plan, dict) or not shot_plan:
        raise FileNotFoundError("当前集尚未生成可执行工作链计划，请先拆分剧情并生成工作链")
    if not _work_chain_plan_has_executable_shots(shot_plan):
        raise ValueError("工作链计划缺少可执行 shots[]，无法生成画布工作流")
    if isinstance(shot_plan.get("contextProvenance"), dict) and shot_plan.get("contextProvenance"):
        shot_plan["contextProvenance"] = _trusted_context_provenance_for_episode(project_id, episode_id)

    shot_plan = _auto_bind_shot_plan_asset_refs(project_id, episode_id, shot_plan)
    shot_plan = _normalize_shot_plan_asset_refs(copy.deepcopy(shot_plan))
    shot_plan = _stamp_source_units_on_shot_plan(project_id, episode_id, shot_plan)
    blocking, warnings = _validate_shot_plan_source_refs(project_id, episode_id, shot_plan)
    asset_blocking, asset_warnings = _validate_plan_asset_refs(project_id, shot_plan, episode_id)
    blocking.extend(asset_blocking)
    warnings.extend(asset_warnings)
    if blocking:
        raise ValueError("；".join(blocking))
    config = get_effective_config(project_id)
    workflow = _work_chain_plan_to_workflow(episode_id, shot_plan, config, project_id=project_id)
    existing_workflow = get_canvas_workflow_projection(project_id, episode_id) if episode_canvas_exists(project_id, episode_id) else {}
    workflow.update({**context, "autoWorkflowInitialized": True})
    workflow["version"] = int((existing_workflow if isinstance(existing_workflow, dict) else {}).get("version") or 0)
    workflow["build"] = {
        "source": "workflow_chain",
        "builder": "build_episode_workflow_from_work_chain_plan",
        "builtAt": _now(),
        "workChainPlanRevision": shot_plan.get("revision"),
        "workChainPlanUpdatedAt": shot_plan.get("updatedAt") or shot_plan.get("updated_at"),
    }
    workflow["state"] = {
        "kind": "ready",
        "reason": "built_workflow_chain",
        "sourceReady": _episode_source_ready(project_id, episode_id),
        "workflowChainReady": True,
        "nextAction": "run_workflow",
    }
    save_result = replace_canvas_workflow_projection(
        project_id,
        episode_id,
        workflow,
        save_version=True,
        version_source=str(payload.get("source") or "agent"),
        version_reason=str(payload.get("reason") or "build_episode_workflow_from_work_chain_plan"),
        initialize_only=True,
    )
    visual_handoff_backfill = _apply_previous_episode_visual_handoff_backfill(
        project_id,
        episode_id,
        save_result,
    )
    production_status = None
    try:
        from .production_status import update_episode_production_status
        status_result = update_episode_production_status(project_id, episode_id)
        production_status = status_result.get("status") if isinstance(status_result, dict) else None
        if production_status:
            save_result["workflow"]["productionStatus"] = production_status
    except Exception:
        print(traceback.format_exc(), flush=True)
    mutation_fields = _workflow_mutation_event_fields(
        save_result,
        [
            *(["episode_production_status"] if production_status else []),
            *(["visual_handoff"] if isinstance(visual_handoff_backfill, dict) and visual_handoff_backfill.get("linked") else []),
        ],
    )
    result = {
        "success": True,
        "episodeId": episode_id,
        "workflow": save_result.get("workflow") or workflow,
        "routeCount": len((save_result.get("workflow") or workflow).get("routes") or []),
        "nodeCount": len((save_result.get("workflow") or workflow).get("nodes") or []),
        "message": "已根据工作链计划生成分集画布工作流。",
        **mutation_fields,
        "projectChanged": True,
        "focusTarget": {"section": "episode", "episodeId": episode_id},
    }
    if production_status:
        result["productionStatus"] = production_status
    if warnings:
        result["warnings"] = warnings
    if isinstance(visual_handoff_backfill, dict) and visual_handoff_backfill:
        result["visualHandoffBackfill"] = visual_handoff_backfill
    if save_result.get("workflowVersion"):
        result["workflowVersion"] = save_result["workflowVersion"]
    return result


def _apply_previous_episode_visual_handoff_backfill(
    project_id: str,
    episode_id: str,
    save_result: dict[str, Any],
) -> dict[str, Any]:
    try:
        backfill = sync_previous_episode_visual_handoff_link(project_id, episode_id)
        if isinstance(backfill, dict) and (
            backfill.get("linked") or backfill.get("updated")
        ):
            workflow = get_canvas_workflow_projection(project_id, episode_id)
            save_result["workflow"] = workflow
            save_result["workflowVersion"] = workflow.get("version")
        return backfill if isinstance(backfill, dict) else {}
    except Exception:
        print(traceback.format_exc(), flush=True)
        return {}


def _workflow_relayout_document(workflow: dict[str, Any]) -> dict[str, Any]:
    nodes = workflow.setdefault("nodes", [])
    routes = workflow.setdefault("routes", [])
    work_chains = workflow.setdefault("workChains", [])
    edges = workflow.setdefault("edges", [])
    if not isinstance(nodes, list):
        nodes = []
        workflow["nodes"] = nodes
    if not isinstance(routes, list):
        routes = []
        workflow["routes"] = routes
    if not isinstance(work_chains, list):
        work_chains = []
        workflow["workChains"] = work_chains
    if not isinstance(edges, list):
        edges = []
        workflow["edges"] = edges
    _layout_workflow_by_work_chain(nodes, routes, work_chains, edges)
    _ensure_saved_workflow_contract(workflow)
    return workflow


def relayout_episode_workflow(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    current = get_canvas_workflow_projection(project_id, episode_id)
    chain_id = str(payload.get("workChainId") or "").strip()
    chain_ids = {chain_id} if chain_id else source_work_chain_ids(current)
    if not chain_ids or not any(chain.get("id") in chain_ids for chain in current.get("workChains", [])):
        raise ValueError("请选择需要整理的工作链")
    workflow = work_chain_scope(current, chain_ids, include_source=not bool(chain_id))
    anchor = next((node for node in workflow["nodes"] if node.get("type") == ("prompt.storyboard" if chain_id else "source.text")), None)
    if anchor is None:
        raise ValueError("工作链缺少布局锚点")
    anchor_id, position = anchor["id"], copy.deepcopy(anchor["position"])
    _workflow_relayout_document(workflow)
    anchor = _workflow_node(workflow, anchor_id)
    _translate_workflow_layout(workflow, position["x"] - anchor["position"]["x"], position["y"] - anchor["position"]["y"])
    result = write_canvas_records_v4(
        project_id, episode_id, nodes=workflow["nodes"], routes=workflow["routes"],
        work_chains=workflow["workChains"], op_type="layout_patch",
        expected_revision=current.get("version"),
    )
    _touch_project_meta(project_id)
    return result


__all__ = (
    '_apply_previous_episode_visual_handoff_backfill',
    '_populate_workflow_material_reference_views',
    '_populate_workflow_material_reference_views_for_read',
    '_populate_workflow_video_reference_views_for_read',
    '_workflow_relayout_document',
    '_workflow_state',
    '_workflow_unique_id',
    'build_episode_workflow_from_work_chain_plan',
    'empty_episode_workflow',
    'get_canvas_reference_views',
    'get_canvas_workflow_projection',
    'relayout_episode_workflow',
)


_WORKFLOW_NEXT_ACTION_BY_PRODUCTION_STATE = {
    "video.generated": "generate_video",
    "storyboard.generated": "generate_storyboard",
    "director_plan.generated": "generate_director_plan",
    "cinematic_script.generated": "generate_cinematic_script",
    "asset_references.linked": "link_assets",
    "workflow.ready": "build_workflow_chain",
    "episode.source_ready": "submit_episode_source",
}

_WORKFLOW_MATERIAL_INPUT_REFERENCE_SYNC_KEYS = (
    "referenceDisplayRows",
    "inputLinks",
    "assetThumbnails",
    "referenceThumbnails",
    "referenceVideoThumbnails",
    "referenceManifest",
    "referenceMediaIds",
    "assetRefs",
    "assetRefsResolvedByInputLinks",
    "inputContract",
    "needsRelink",
)

def _work_chain_plan_path(project_id: str, episode_id: str) -> Path:
    return _project_dir(project_id) / "episodes" / episode_id / "work_chain_plan.json"

def _episode_source_ready(project_id: str, episode_id: str) -> bool:
    episode_dir = _project_dir(project_id) / "episodes" / episode_id
    return (episode_dir / "source.txt").exists() and (episode_dir / "source_ref.json").exists()

def _work_chain_plan_has_executable_shots(document: Any) -> bool:
    return isinstance(document, dict) and isinstance(document.get("shots"), list) and bool(document.get("shots"))

def _work_chain_plan_ready(project_id: str, episode_id: str) -> bool:
    document = _read_json(_work_chain_plan_path(project_id, episode_id), {})
    return _work_chain_plan_has_executable_shots(document)

def _workflow_versions_path(project_id: str, episode_id: str) -> Path:
    return _project_dir(project_id) / "episodes" / episode_id / "canvas" / "history" / "index.json"

def _workflow_version_label(source: str, reason: str) -> str:
    if source == "agent":
        return "智能体规划版本"
    if source == "user":
        return "用户保存版本"
    if source == "config":
        return "生成配置版本"
    return reason or "工作流版本"

def _append_workflow_version(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    *,
    source: str,
    reason: str = "",
) -> dict[str, Any]:
    path = _workflow_versions_path(project_id, episode_id)
    versions = _read_json(path, [])
    if not isinstance(versions, list):
        versions = []
    now = _now()
    route_count = len(workflow.get("routes") or [])
    node_count = len(workflow.get("nodes") or [])
    edge_count = len(workflow.get("edges") or [])
    version = {
        "id": f"workflow-version-{uuid.uuid4().hex[:10]}",
        "episodeId": episode_id,
        "workflowVersion": workflow.get("version"),
        "title": _workflow_version_label(source, reason),
        "source": source or "manual",
        "reason": reason,
        "createdAt": now,
        "routeCount": route_count,
        "nodeCount": node_count,
        "edgeCount": edge_count,
    }
    versions.append(version)
    _write_json(path, versions[-80:])
    return version

def replace_canvas_workflow_projection(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    *,
    save_version: bool = False,
    version_source: str = "manual",
    version_reason: str = "",
    stamp_source_units: bool = False,
    op_type: str | None = None,
    initialize_only: bool = False,
) -> dict[str, Any]:
    previous_workflow = get_canvas_workflow_projection(project_id, episode_id) if episode_canvas_exists(project_id, episode_id) else {}
    if str(version_source or "").strip().lower() == "user":
        _assert_user_workflow_save_keeps_protected_items(previous_workflow, workflow)
    # Source unit stamping is a derived projection. It must not block hot canvas
    # mutations such as model result commits or card edits.
    if stamp_source_units:
        workflow = _stamp_source_units_on_workflow(project_id, episode_id, workflow)
    _ensure_saved_workflow_contract(workflow)
    asset_ref_blocking, asset_ref_warnings = _validate_workflow_asset_refs(project_id, episode_id, workflow)
    if asset_ref_blocking:
        raise ValueError("；".join(asset_ref_blocking))
    workflow["episodeId"] = episode_id
    workflow_op_type = str(op_type or "").strip()
    if not workflow_op_type:
        reason = str(version_reason or "").strip()
        workflow_op_type = "layout_patch" if "layout" in reason else "document_replace"
    workflow = replace_canvas_records_from_workflow_projection_v4(project_id, episode_id, workflow, op_type=workflow_op_type, initialize_only=initialize_only)
    workflow_version = workflow.get("version")
    workflow_history_version = None
    if save_version:
        workflow_history_version = _append_workflow_version(
            project_id,
            episode_id,
            workflow,
            source=version_source,
            reason=version_reason,
        )
    _touch_project_meta(project_id)
    result = {"success": True, "workflow": workflow}
    if workflow_version:
        result["workflowVersion"] = workflow_version
    for key in (
        "txId",
        "seq",
        "revision",
        "baseRevision",
        "opType",
        "records",
        "changedResources",
        "documentExtras",
        "productionStatus",
    ):
        if workflow.get(key) is not None:
            result[key] = copy.deepcopy(workflow.get(key))
    if workflow_history_version:
        result["workflowHistoryVersion"] = workflow_history_version
    if asset_ref_warnings:
        result["warnings"] = asset_ref_warnings
    return result

def _workflow_payload_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False

def _workflow_ready_visual_handoff_version(
    project_id: str,
    episode_id: str,
    handoff_node: dict[str, Any],
) -> dict[str, Any]:
    handoff_node_id = str(handoff_node.get("id") or "").strip()
    if not handoff_node_id:
        return {}
    version = _workflow_active_card_version(project_id, episode_id, handoff_node_id, handoff_node)
    status = str(version.get("status") or "").strip()
    if status in {"failed", "blocked", "cancelled", "canceled", "processing"}:
        return {}
    if not isinstance(version.get("media"), dict) or not version.get("media"):
        return {}
    return version

def sync_previous_episode_visual_handoff_link(project_id: str, episode_id: str) -> dict[str, Any]:
    episode_id = str(episode_id or "").strip()
    if not project_id or not episode_id:
        return {"linked": False, "reason": "missing_project_or_episode"}
    previous_episode_id = _previous_project_episode_id(project_id, episode_id)
    if not previous_episode_id:
        return {"linked": False, "reason": "previous_episode_missing"}
    if _next_project_episode_id(project_id, previous_episode_id) != episode_id:
        return {"linked": False, "reason": "episode_order_mismatch", "previousEpisodeId": previous_episode_id}
    if not episode_canvas_exists(project_id, previous_episode_id):
        return {"linked": False, "reason": "previous_episode_canvas_missing", "previousEpisodeId": previous_episode_id}
    if not episode_canvas_exists(project_id, episode_id):
        return {"linked": False, "reason": "current_episode_canvas_missing", "previousEpisodeId": previous_episode_id}
    previous_card_node = _workflow_episode_storyboard_card_boundary_node(
        project_id,
        previous_episode_id,
        boundary="last",
        detail="full",
    )
    if not previous_card_node:
        return {"linked": False, "reason": "previous_episode_storyboard_card_missing", "previousEpisodeId": previous_episode_id}
    previous_card_node_id = str(previous_card_node.get("id") or "").strip()
    handoff_node = read_canvas_visual_handoff_result_node_v4(
        project_id,
        previous_episode_id,
        prompt_node_id=previous_card_node_id,
        detail="full",
    )
    if not handoff_node:
        return {
            "linked": False,
            "reason": "previous_visual_handoff_missing",
            "previousEpisodeId": previous_episode_id,
            "sourceStoryboardCardNodeId": previous_card_node_id,
        }
    handoff_version = _workflow_ready_visual_handoff_version(
        project_id,
        previous_episode_id,
        handoff_node,
    )
    if not handoff_version:
        return {
            "linked": False,
            "reason": "previous_visual_handoff_media_missing",
            "previousEpisodeId": previous_episode_id,
            "sourceStoryboardCardNodeId": previous_card_node_id,
            "sourceNodeId": str(handoff_node.get("id") or "").strip(),
        }
    result = sync_visual_handoff_cross_episode_link(
        project_id,
        previous_episode_id,
        handoff_node,
        handoff_version,
    )
    if isinstance(result, dict):
        result.setdefault("previousEpisodeId", previous_episode_id)
        result.setdefault("episodeId", episode_id)
        result.setdefault("sourceStoryboardCardNodeId", previous_card_node_id)
        result.setdefault("sourceNodeId", str(handoff_node.get("id") or "").strip())
        result.setdefault("sourceVersionId", str(handoff_version.get("id") or "").strip())
        result.setdefault("action", "previous_visual_handoff_backfilled")
    return result if isinstance(result, dict) else {"linked": False, "reason": "sync_failed"}


def _workflow_media_path(project_id: str, episode_id: str) -> Path:
    return _project_dir(project_id) / "episodes" / _safe_episode_id(episode_id) / "workflow_media.json"


def _empty_workflow_media(episode_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "episodeId": episode_id,
        "items": [],
        "updatedAt": _now(),
    }


def _read_workflow_media(project_id: str, episode_id: str) -> dict[str, Any]:
    data = _read_json(_workflow_media_path(project_id, episode_id), _empty_workflow_media(episode_id))
    if isinstance(data, list):
        data = {"schemaVersion": 1, "episodeId": episode_id, "items": data}
    if not isinstance(data, dict):
        data = _empty_workflow_media(episode_id)
    items = data.get("items")
    data["items"] = items if isinstance(items, list) else []
    data.setdefault("schemaVersion", 1)
    data["episodeId"] = episode_id
    return data


def _write_workflow_media(project_id: str, episode_id: str, data: dict[str, Any]) -> None:
    data = copy.deepcopy(data)
    data.setdefault("schemaVersion", 1)
    data["episodeId"] = episode_id
    data["updatedAt"] = _now()
    _write_json(_workflow_media_path(project_id, episode_id), data)


def _read_workflow_tasks(project_id: str, episode_id: str) -> list[dict[str, Any]]:
    return read_canvas_task_records_v4(project_id, episode_id)


def _write_workflow_tasks(
    project_id: str,
    episode_id: str,
    tasks: list[dict[str, Any]],
    *,
    op_type: str = "card_patch",
    changed_resources: list[str] | None = None,
) -> dict[str, Any]:
    return write_canvas_task_records_v4(
        project_id,
        episode_id,
        tasks[-300:] if isinstance(tasks, list) else [],
        op_type=op_type,
        changed_resources=changed_resources or ["canvas_task"],
    )


_WORKFLOW_TASK_LOCKS_GUARD = threading.Lock()


_WORKFLOW_TASK_LOCKS: dict[tuple[str, str], threading.RLock] = {}


def _workflow_tasks_lock(project_id: str, episode_id: str) -> threading.RLock:
    key = (str(project_id or ""), _safe_episode_id(episode_id))
    with _WORKFLOW_TASK_LOCKS_GUARD:
        lock = _WORKFLOW_TASK_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _WORKFLOW_TASK_LOCKS[key] = lock
        return lock


def _append_workflow_task(project_id: str, episode_id: str, task: dict[str, Any]) -> dict[str, Any]:
    with _workflow_tasks_lock(project_id, episode_id):
        tasks = _read_workflow_tasks(project_id, episode_id)
        return _write_workflow_tasks(project_id, episode_id, tasks + [copy.deepcopy(task)])


def _workflow_cards_mutation_write(
    project_id: str,
    episode_id: str,
    nodes: list[dict[str, Any]],
    *,
    op_type: str = "card_patch",
    changed_resources: list[str] | None = None,
    expected_revision: int | str | None = None,
) -> dict[str, Any]:
    with _JSON_WRITE_LOCK:
        node_rows = nodes if isinstance(nodes, list) else []
        for node in node_rows:
            if isinstance(node, dict):
                _ensure_saved_workflow_node_contract(node)
        saved = write_canvas_card_records_v4(
            project_id,
            episode_id,
            node_rows,
            op_type=op_type,
            changed_resources=changed_resources or ["canvas_node"],
            expected_revision=expected_revision,
        )
        _touch_project_meta(project_id)
        return saved


def _canvas_node_exists_v4(project_id: str, episode_id: str, node_id: str) -> bool:
    node_id = str(node_id or "").strip()
    if not node_id:
        return False
    try:
        read_canvas_card_record_v4(project_id, episode_id, node_id, detail="summary")
        return True
    except FileNotFoundError:
        return False


def _canvas_records_v4(
    project_id: str,
    episode_id: str,
    *,
    node_ids: list[str] | None = None,
    edge_ids: list[str] | None = None,
    route_ids: list[str] | None = None,
    work_chain_ids: list[str] | None = None,
    detail: str = "full",
) -> dict[str, list[Any]]:
    try:
        result = get_canvas_records_v4(
            project_id,
            episode_id,
            {
                "detail": detail,
                "ids": {
                    "nodeIds": node_ids or [],
                    "edgeIds": edge_ids or [],
                    "routeIds": route_ids or [],
                    "workChainIds": work_chain_ids or [],
                },
            },
        )
    except FileNotFoundError:
        return {"nodes": [], "edges": [], "routes": [], "workChains": []}
    records = result.get("records") if isinstance(result, dict) else {}
    return records if isinstance(records, dict) else {}


def _read_canvas_route_v4(project_id: str, episode_id: str, route_id: str) -> dict[str, Any] | None:
    route_id = str(route_id or "").strip()
    if not route_id:
        return None
    records = _canvas_records_v4(project_id, episode_id, route_ids=[route_id], detail="full")
    routes = records.get("routes") if isinstance(records.get("routes"), list) else []
    return copy.deepcopy(routes[0]) if routes and isinstance(routes[0], dict) else None


def list_workflow_media(project_id: str, episode_id: str) -> dict[str, Any]:
    workflow_media = _read_workflow_media(project_id, episode_id)
    return {
        "success": True,
        "episodeId": episode_id,
        "items": workflow_media.get("items") or [],
        "media": workflow_media.get("items") or [],
        "workflowMedia": workflow_media,
    }
