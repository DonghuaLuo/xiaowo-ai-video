# -*- coding: utf-8 -*-
"""画布变更资源、事件载荷与项目更新通知。"""
from __future__ import annotations

from .store_core import (
    _emit_agent_event,
)

import copy as copy
from .agent_output_validation import (
    _agent_focus_workflow_node_id,
)

from typing import Any


def _merge_changed_resources(*items: Any) -> list[str]:
    resources: list[str] = []
    for item in items:
        rows = item.get("changedResources") if isinstance(item, dict) else item
        if not isinstance(rows, list):
            continue
        resources.extend(str(row) for row in rows if str(row or "").strip())
    return list(dict.fromkeys(resources))


def _canvas_changed_resource_name(value: Any) -> str:
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


def _canvas_mutation_has_envelope(source: Any) -> bool:
    return isinstance(source, dict) and any(source.get(key) is not None for key in _CANVAS_MUTATION_ENVELOPE_KEYS)


def _canvas_mutation_single_sync_mutation(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    mutations = source.get("mutations")
    if not isinstance(mutations, list):
        return {}
    mutation_rows = [row for row in mutations if _canvas_mutation_has_envelope(row)]
    return mutation_rows[0] if len(mutation_rows) == 1 else {}


def _canvas_mutation_event_source_rows(*items: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()

    def append(source: Any) -> None:
        if not isinstance(source, dict) or not source:
            return
        marker = id(source)
        if marker in seen:
            return
        seen.add(marker)
        rows.append(source)

    for item in items:
        if not isinstance(item, dict):
            continue
        if _canvas_mutation_has_envelope(item):
            append(item)
        version = item.get("version") if isinstance(item.get("version"), dict) else {}
        if _canvas_mutation_has_envelope(version):
            append(version)
        project_effect = item.get("projectEffect") if isinstance(item.get("projectEffect"), dict) else {}
        if _canvas_mutation_has_envelope(project_effect):
            append(project_effect)
        append(_canvas_mutation_single_sync_mutation(item))
    return rows


def _canvas_mutation_event_fields(result: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    key_aliases = (
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
    for source in _canvas_mutation_event_source_rows(result):
        for output_key, aliases in key_aliases:
            value = next((source.get(key) for key in aliases if source.get(key) is not None), None)
            if value is not None:
                fields[output_key] = copy.deepcopy(value)
    return fields


def _canvas_mutation_event_payload(
    *items: Any,
    fallback_changed_resources: list[str] | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for item in items:
        row = item if isinstance(item, dict) else {}
        if row.get("workflowVersion") is not None:
            fields["workflowVersion"] = copy.deepcopy(row.get("workflowVersion"))
        fields.update(_canvas_mutation_event_fields(row))
    changed_resources = list(
        dict.fromkeys(
            normalized
            for resource in _merge_changed_resources(
                *items,
                {"changedResources": fallback_changed_resources or []},
            )
            for normalized in [_canvas_changed_resource_name(resource)]
            if normalized
        )
    )
    if changed_resources:
        fields["changedResources"] = changed_resources
    return fields


def _canvas_mutation_payload(args: Any) -> dict[str, Any]:
    payload = copy.deepcopy(args if isinstance(args, dict) else {})
    for key in ("returnWorkflow", "return_workflow", "includeWorkflow", "include_workflow"):
        payload.pop(key, None)
    return payload


def _agent_project_effect_from_save(
    changed_resources: list[str],
    save_result: dict[str, Any] | None,
    *,
    project_id: str | None = None,
    episode_id: str | None = None,
    notice: str = "",
) -> dict[str, Any]:
    focus_target = (save_result or {}).get("focusTarget") if isinstance((save_result or {}).get("focusTarget"), dict) else {}
    if not focus_target:
        if any(resource in changed_resources for resource in ("workChainPlan", "storyboard", "episodes")):
            current_episode_id = episode_id or "E01"
            focus_node_id = (
                _agent_focus_workflow_node_id(project_id, current_episode_id)
                if project_id
                else ""
            )
            focus_target = {
                "section": "episode",
                "episodeId": current_episode_id,
            }
            if focus_node_id:
                focus_target["nodeId"] = focus_node_id
        elif changed_resources:
            first = changed_resources[0]
            focus_target = {"section": first, "assetTab": first} if first in {"characters", "creatures", "scenes", "props"} else {"section": first}
    return {
        "changedResources": changed_resources,
        "focusTarget": focus_target,
        "notice": notice or str((save_result or {}).get("message") or "worker 已完成"),
    }


def _emit_agent_project_effect(
    project_id: str,
    episode_id: str | None,
    effect: dict[str, Any] | None,
    *,
    session_id: str | None = None,
) -> None:
    if not isinstance(effect, dict) or not effect:
        return
    _emit_agent_event(
        "agent_project_effect",
        {
            "projectId": project_id,
            "episodeId": episode_id,
            "sessionId": session_id,
            **copy.deepcopy(effect),
        },
    )
