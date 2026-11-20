# -*- coding: utf-8 -*-
"""画布结构替换、增删和卡片补丁的完整事务。"""
from __future__ import annotations

import copy
from .canvas_ownership import (
    normalize_node_ownership,
)
from .canvas_reference_views import (
    remove_reference_views,
)
from .canvas_store_database import (
    _SQLITE_WRITE_LOCK,
    _canvas_connection,
    _canvas_mutation_document_in_conn,
)
from .canvas_store_indexes import (
    _upsert_canvas_node_source_refs_in_conn,
)
from .canvas_store_queries import (
    _read_canvas_projection_state_in_conn,
    _version_refs_for_nodes,
)
from .canvas_store_records import (
    CanvasProjectionState,
    _canvas_projection_change_payload,
    _canvas_document_extras_payload,
    _canvas_version_ref_payload,
    _canvas_version_ref_payloads,
    _edge_data_record,
    _json_dumps,
    _json_loads,
    _json_signature,
    _merge_canvas_document_extras,
    _node_position_record,
    _node_status_record,
    _node_summary_record,
    _record_edge_id,
    _record_id_set,
    _record_node_id,
    _record_ref,
    _records_payload,
    _workflow_document_extras,
    normalize_canvas_changed_resources,
)
from .canvas_store_rows import (
    _write_canvas_projection_document_in_conn,
    _replace_canvas_projection_nodes_in_conn,
    _replace_canvas_projection_edges_in_conn,
    _patch_workflow_cards_in_conn,
    _record_op,
    _replace_canvas_routes,
    _replace_canvas_work_chains,
    _upsert_canvas_edges_in_conn,
    _upsert_canvas_nodes_in_conn,
    _upsert_canvas_routes_in_conn,
    _upsert_canvas_work_chains_in_conn,
)
from .store_core import (
    _now,
)
from typing import (
    Any,
    Callable,
)


def replace_canvas_records_from_workflow_projection_v4(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    *,
    op_type: str = "document_replace",
    initialize_only: bool = False,
    expected_revision: int | str | None = None,
) -> dict[str, Any]:
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    viewport = copy.deepcopy(workflow.get("viewport") if isinstance(workflow.get("viewport"), dict) else {"x": 0, "y": 0, "zoom": 0.82})
    routes = copy.deepcopy(workflow.get("routes") if isinstance(workflow.get("routes"), list) else [])
    work_chains = copy.deepcopy(workflow.get("workChains") if isinstance(workflow.get("workChains"), list) else [])
    state = copy.deepcopy(workflow.get("state") if isinstance(workflow.get("state"), dict) else {})
    root_extras = _workflow_document_extras(workflow)
    now = _now()
    normalized_op_type = str(op_type or "document_replace").strip() or "document_replace"
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            if initialize_only and not conn.in_transaction:
                conn.execute("BEGIN IMMEDIATE")
            previous_document = _canvas_mutation_document_in_conn(
                conn,
                episode_id,
                now=now,
                expected_revision=expected_revision,
                create_if_missing=True,
            )
            if initialize_only:
                custom = conn.execute("SELECT 1 FROM canvas_catalog WHERE storage_key = ? AND canvas_kind = 'custom'", (episode_id,)).fetchone()
                if custom:
                    raise ValueError("自定义画布不支持原文工作链初始化")
                if _canvas_document_extras_payload(previous_document).get("autoWorkflowInitialized"):
                    raise ValueError("当前画布已完成自动初始化，不能重复生成工作链")
                if conn.execute("SELECT 1 FROM canvas_nodes WHERE episode_id = ? AND node_type != 'source.text' LIMIT 1", (episode_id,)).fetchone():
                    raise ValueError("当前画布已有内容，不能重新初始化")
            base_revision = int(previous_document["revision"] or 0) if previous_document is not None else 0
            revision = base_revision + 1
            extras = _merge_canvas_document_extras(
                _canvas_document_extras_payload(previous_document),
                root_extras,
                replace=normalized_op_type == "document_replace",
            )
            custom = conn.execute("SELECT canvas_id FROM canvas_catalog WHERE storage_key = ? AND canvas_kind = 'custom'", (episode_id,)).fetchone()
            extras.update({
                "canvasKind": "custom" if custom else "work_chain",
                "autoWorkflowInitialized": bool(_canvas_document_extras_payload(previous_document).get("autoWorkflowInitialized") or initialize_only) if not custom else False,
            })
            previous = _read_canvas_projection_state_in_conn(conn, episode_id)
            _write_canvas_projection_document_in_conn(
                conn, episode_id, revision, viewport, routes, work_chains, state, extras, now,
            )
            active_node_ids, active_node_signatures = _replace_canvas_projection_nodes_in_conn(
                conn, episode_id, nodes, now,
            )
            active_edge_ids, active_edge_signatures = _replace_canvas_projection_edges_in_conn(
                conn, episode_id, edges, now,
            )
            active_route_ids, active_route_signatures = _replace_canvas_routes(
                conn,
                episode_id=episode_id,
                routes=routes,
                now=now,
            )
            active_work_chain_ids, active_work_chain_signatures = _replace_canvas_work_chains(
                conn,
                episode_id=episode_id,
                work_chains=work_chains,
                now=now,
            )
            active = CanvasProjectionState(
                node_ids=active_node_ids,
                edge_ids=active_edge_ids,
                route_ids=active_route_ids,
                work_chain_ids=active_work_chain_ids,
                node_signatures=active_node_signatures,
                edge_signatures=active_edge_signatures,
                route_signatures=active_route_signatures,
                work_chain_signatures=active_work_chain_signatures,
            )
            op_payload = _canvas_projection_change_payload(previous, active, extras)
            mutation = _record_op(
                conn,
                episode_id=episode_id,
                op_type=normalized_op_type,
                base_revision=base_revision,
                revision=revision,
                payload=op_payload,
            )
    result = copy.deepcopy(workflow)
    result["schemaVersion"] = 4
    result["episodeId"] = episode_id
    result["version"] = revision
    result["workflowVersion"] = revision
    result["documentExtras"] = copy.deepcopy(extras)
    if isinstance(extras.get("productionStatus"), dict):
        result["productionStatus"] = copy.deepcopy(extras["productionStatus"])
    result.update({key: copy.deepcopy(value) for key, value in mutation.items() if key != "payload"})
    return result


def write_canvas_records_v4(
    project_id: str,
    episode_id: str,
    *,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    routes: list[dict[str, Any]] | None = None,
    work_chains: list[dict[str, Any]] | None = None,
    delete_edge_ids: Any = None,
    op_type: str = "structure_patch",
    changed_resources: list[str] | None = None,
    expected_revision: int | str | None = None,
    create_only: bool = False,
) -> dict[str, Any]:
    now = _now()
    normalized_op_type = str(op_type or "structure_patch").strip() or "structure_patch"
    explicit_delete_edge_ids = _record_id_set(delete_edge_ids)
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            if create_only:
                if not conn.in_transaction:
                    conn.execute("BEGIN IMMEDIATE")
                for table, column, items in (
                    ("canvas_nodes", "node_id", nodes), ("canvas_edges", "edge_id", edges),
                    ("canvas_routes", "route_id", routes), ("canvas_work_chains", "work_chain_id", work_chains),
                ):
                    for item in items or []:
                        if conn.execute(f"SELECT 1 FROM {table} WHERE episode_id = ? AND {column} = ?", (episode_id, item["id"])).fetchone():
                            raise ValueError("画布记录已存在，创建操作不能覆盖已有记录")
            document = _canvas_mutation_document_in_conn(
                conn, episode_id, now=now, expected_revision=expected_revision, create_if_missing=not create_only,
            )
            base_revision = int(document["revision"] or 0)
            existing_deleted_edge_ids: set[str] = set()
            if explicit_delete_edge_ids:
                for start in range(0, len(explicit_delete_edge_ids), 800):
                    chunk = sorted(explicit_delete_edge_ids)[start : start + 800]
                    placeholders = ",".join("?" for _ in chunk)
                    rows = conn.execute(
                        f"""
                        SELECT edge_id
                        FROM canvas_edges
                        WHERE episode_id = ? AND edge_id IN ({placeholders})
                        """,
                        (episode_id, *chunk),
                    ).fetchall()
                    existing_deleted_edge_ids.update(
                        str(row["edge_id"] or "").strip()
                        for row in rows
                        if str(row["edge_id"] or "").strip()
                    )
                if existing_deleted_edge_ids:
                    for start in range(0, len(existing_deleted_edge_ids), 800):
                        chunk = sorted(existing_deleted_edge_ids)[start : start + 800]
                        placeholders = ",".join("?" for _ in chunk)
                        conn.execute(
                            f"DELETE FROM canvas_edges WHERE episode_id = ? AND edge_id IN ({placeholders})",
                            (episode_id, *chunk),
                        )
            stored_nodes, added_node_refs, updated_node_refs = _upsert_canvas_nodes_in_conn(
                conn,
                episode_id=episode_id,
                nodes=nodes or [],
                now=now,
            )
            stored_edges, added_edge_refs, updated_edge_refs = _upsert_canvas_edges_in_conn(
                conn,
                episode_id=episode_id,
                edges=edges or [],
                now=now,
            )
            stored_routes, added_route_refs, updated_route_refs = _upsert_canvas_routes_in_conn(
                conn,
                episode_id=episode_id,
                routes=routes or [],
                now=now,
            )
            stored_work_chains, added_work_chain_refs, updated_work_chain_refs = _upsert_canvas_work_chains_in_conn(
                conn,
                episode_id=episode_id,
                work_chains=work_chains or [],
                now=now,
            )
            if (
                not stored_nodes
                and not stored_edges
                and not stored_routes
                and not stored_work_chains
                and not existing_deleted_edge_ids
            ):
                return {
                    "success": True,
                    "episodeId": episode_id,
                    "workflowVersion": base_revision,
                    "revision": base_revision,
                    "opType": normalized_op_type,
                    "nodes": [],
                    "edges": [],
                    "records": _records_payload(),
                    "changedResources": [],
                }

            revision = base_revision + 1
            conn.execute(
                """
                UPDATE canvas_documents
                SET revision = ?, updated_at = ?
                WHERE episode_id = ?
                """,
                (revision, now, episode_id),
            )
            node_ids = [str(node.get("id") or "") for node in stored_nodes]
            records = _records_payload(
                added=[
                    *added_node_refs,
                    *added_edge_refs,
                    *added_route_refs,
                    *added_work_chain_refs,
                ],
                updated=[
                    *updated_node_refs,
                    *updated_edge_refs,
                    *updated_route_refs,
                    *updated_work_chain_refs,
                    *_version_refs_for_nodes(conn, episode_id=episode_id, node_ids=node_ids),
                ],
                removed=[_record_ref("canvas_edge", edge_id) for edge_id in sorted(existing_deleted_edge_ids)],
            )
            mutation = _record_op(
                conn,
                episode_id=episode_id,
                op_type=normalized_op_type,
                base_revision=base_revision,
                revision=revision,
                payload={
                    "records": records,
                    "nodeIds": node_ids,
                    "edgeIds": [str(edge.get("id") or "") for edge in stored_edges],
                    "routeIds": [str(route.get("id") or "") for route in stored_routes],
                    "workChainIds": [str(chain.get("id") or "") for chain in stored_work_chains],
                    "removedEdgeIds": sorted(existing_deleted_edge_ids),
                    "changedResources": copy.deepcopy(
                        changed_resources if isinstance(changed_resources, list) else []
                    ),
                },
            )
    return {
        "success": True,
        "episodeId": episode_id,
        "workflowVersion": revision,
        **{key: copy.deepcopy(value) for key, value in mutation.items() if key != "payload"},
        "nodes": stored_nodes,
        "edges": stored_edges,
        "routes": stored_routes,
        "workChains": stored_work_chains,
        "removedEdgeIds": sorted(existing_deleted_edge_ids),
    }


def delete_canvas_records_v4(
    project_id: str,
    episode_id: str,
    *,
    node_ids: Any = None,
    edge_ids: Any = None,
    route_ids: Any = None,
    work_chain_ids: Any = None,
    nodes: list[dict[str, Any]] | None = None,
    routes: list[dict[str, Any]] | None = None,
    work_chains: list[dict[str, Any]] | None = None,
    op_type: str = "structure_patch",
    changed_resources: list[str] | None = None,
    expected_revision: int | str | None = None,
) -> dict[str, Any]:
    delete_node_ids = _record_id_set(node_ids)
    explicit_edge_ids = _record_id_set(edge_ids)
    explicit_route_ids = _record_id_set(route_ids)
    explicit_work_chain_ids = _record_id_set(work_chain_ids)
    patch_nodes = [
        copy.deepcopy(node)
        for node in nodes or []
        if isinstance(node, dict)
        and str(node.get("id") or "").strip()
        and str(node.get("id") or "").strip() not in delete_node_ids
    ]
    patch_routes = [
        copy.deepcopy(route)
        for route in routes or []
        if isinstance(route, dict)
        and str(route.get("id") or "").strip()
        and str(route.get("id") or "").strip() not in explicit_route_ids
    ]
    patch_work_chains = [
        copy.deepcopy(chain)
        for chain in work_chains or []
        if isinstance(chain, dict)
        and str(chain.get("id") or "").strip()
        and str(chain.get("id") or "").strip() not in explicit_work_chain_ids
    ]
    now = _now()
    normalized_op_type = str(op_type or "structure_patch").strip() or "structure_patch"
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            document = _canvas_mutation_document_in_conn(
                conn, episode_id, now=now, expected_revision=expected_revision,
            )
            base_revision = int(document["revision"] or 0)

            existing_node_ids: set[str] = set()
            if delete_node_ids:
                for start in range(0, len(delete_node_ids), 800):
                    chunk = sorted(delete_node_ids)[start : start + 800]
                    placeholders = ",".join("?" for _ in chunk)
                    rows = conn.execute(
                        f"""
                        SELECT node_id
                        FROM canvas_nodes
                        WHERE episode_id = ? AND node_id IN ({placeholders})
                        """,
                        (episode_id, *chunk),
                    ).fetchall()
                    existing_node_ids.update(
                        str(row["node_id"] or "").strip()
                        for row in rows
                        if str(row["node_id"] or "").strip()
                    )

            edge_ids_to_delete = set(explicit_edge_ids)
            if existing_node_ids:
                for start in range(0, len(existing_node_ids), 400):
                    chunk = sorted(existing_node_ids)[start : start + 400]
                    placeholders = ",".join("?" for _ in chunk)
                    rows = conn.execute(
                        f"""
                        SELECT edge_id
                        FROM canvas_edges
                        WHERE episode_id = ?
                          AND (source_node_id IN ({placeholders}) OR target_node_id IN ({placeholders}))
                        """,
                        (episode_id, *chunk, *chunk),
                    ).fetchall()
                    edge_ids_to_delete.update(
                        str(row["edge_id"] or "").strip()
                        for row in rows
                        if str(row["edge_id"] or "").strip()
                    )

            existing_edge_ids: set[str] = set()
            if edge_ids_to_delete:
                for start in range(0, len(edge_ids_to_delete), 800):
                    chunk = sorted(edge_ids_to_delete)[start : start + 800]
                    placeholders = ",".join("?" for _ in chunk)
                    rows = conn.execute(
                        f"""
                        SELECT edge_id
                        FROM canvas_edges
                        WHERE episode_id = ? AND edge_id IN ({placeholders})
                        """,
                        (episode_id, *chunk),
                    ).fetchall()
                    existing_edge_ids.update(
                        str(row["edge_id"] or "").strip()
                        for row in rows
                        if str(row["edge_id"] or "").strip()
                    )

            existing_route_ids: set[str] = set()
            if explicit_route_ids:
                for start in range(0, len(explicit_route_ids), 800):
                    chunk = sorted(explicit_route_ids)[start : start + 800]
                    placeholders = ",".join("?" for _ in chunk)
                    rows = conn.execute(
                        f"""
                        SELECT route_id
                        FROM canvas_routes
                        WHERE episode_id = ? AND route_id IN ({placeholders})
                        """,
                        (episode_id, *chunk),
                    ).fetchall()
                    existing_route_ids.update(
                        str(row["route_id"] or "").strip()
                        for row in rows
                        if str(row["route_id"] or "").strip()
                    )

            existing_work_chain_ids: set[str] = set()
            if explicit_work_chain_ids:
                for start in range(0, len(explicit_work_chain_ids), 800):
                    chunk = sorted(explicit_work_chain_ids)[start : start + 800]
                    placeholders = ",".join("?" for _ in chunk)
                    rows = conn.execute(
                        f"""
                        SELECT work_chain_id
                        FROM canvas_work_chains
                        WHERE episode_id = ? AND work_chain_id IN ({placeholders})
                        """,
                        (episode_id, *chunk),
                    ).fetchall()
                    existing_work_chain_ids.update(
                        str(row["work_chain_id"] or "").strip()
                        for row in rows
                        if str(row["work_chain_id"] or "").strip()
                    )

            removed_version_refs: list[dict[str, Any]] = []
            removed_task_refs: list[dict[str, Any]] = []
            if existing_node_ids:
                for start in range(0, len(existing_node_ids), 800):
                    chunk = sorted(existing_node_ids)[start : start + 800]
                    placeholders = ",".join("?" for _ in chunk)
                    version_rows = conn.execute(
                        f"""
                        SELECT node_id, version_id
                        FROM canvas_versions
                        WHERE episode_id = ? AND node_id IN ({placeholders})
                        """,
                        (episode_id, *chunk),
                    ).fetchall()
                    removed_version_refs.extend(
                        _record_ref("canvas_version", row["version_id"], nodeId=row["node_id"])
                        for row in version_rows
                        if str(row["version_id"] or "").strip()
                    )
                    task_rows = conn.execute(
                        f"""
                        SELECT node_id, task_id
                        FROM canvas_tasks
                        WHERE episode_id = ? AND node_id IN ({placeholders})
                        """,
                        (episode_id, *chunk),
                    ).fetchall()
                    removed_task_refs.extend(
                        _record_ref("canvas_task", row["task_id"], nodeId=row["node_id"])
                        for row in task_rows
                        if str(row["task_id"] or "").strip()
                    )

            def delete_by_ids(table: str, column: str, ids: set[str]) -> None:
                if not ids:
                    return
                for start in range(0, len(ids), 800):
                    chunk = sorted(ids)[start : start + 800]
                    placeholders = ",".join("?" for _ in chunk)
                    conn.execute(
                        f"DELETE FROM {table} WHERE episode_id = ? AND {column} IN ({placeholders})",
                        (episode_id, *chunk),
                    )

            delete_by_ids("canvas_edges", "edge_id", existing_edge_ids)
            delete_by_ids("canvas_routes", "route_id", existing_route_ids)
            delete_by_ids("canvas_work_chains", "work_chain_id", existing_work_chain_ids)
            if existing_node_ids:
                delete_by_ids("canvas_versions", "node_id", existing_node_ids)
                delete_by_ids("canvas_tasks", "node_id", existing_node_ids)
                delete_by_ids("canvas_nodes", "node_id", existing_node_ids)

            stored_nodes, added_node_refs, updated_node_refs = _upsert_canvas_nodes_in_conn(
                conn,
                episode_id=episode_id,
                nodes=patch_nodes,
                now=now,
            )
            stored_node_ids = [str(node.get("id") or "") for node in stored_nodes]
            stored_routes, added_route_refs, updated_route_refs = _upsert_canvas_routes_in_conn(
                conn,
                episode_id=episode_id,
                routes=patch_routes,
                now=now,
            )
            stored_work_chains, added_work_chain_refs, updated_work_chain_refs = _upsert_canvas_work_chains_in_conn(
                conn,
                episode_id=episode_id,
                work_chains=patch_work_chains,
                now=now,
            )

            if (
                not existing_node_ids
                and not existing_edge_ids
                and not existing_route_ids
                and not existing_work_chain_ids
                and not added_node_refs
                and not updated_node_refs
                and not added_route_refs
                and not updated_route_refs
                and not added_work_chain_refs
                and not updated_work_chain_refs
            ):
                return {
                    "success": True,
                    "episodeId": episode_id,
                    "workflowVersion": base_revision,
                    "revision": base_revision,
                    "opType": normalized_op_type,
                    "nodes": [],
                    "records": _records_payload(),
                    "changedResources": [],
                }

            revision = base_revision + 1
            conn.execute(
                """
                UPDATE canvas_documents
                SET revision = ?, updated_at = ?
                WHERE episode_id = ?
                """,
                (revision, now, episode_id),
            )
            records = _records_payload(
                added=[*added_node_refs, *added_route_refs, *added_work_chain_refs],
                updated=[
                    *updated_node_refs,
                    *updated_route_refs,
                    *updated_work_chain_refs,
                    *_version_refs_for_nodes(conn, episode_id=episode_id, node_ids=stored_node_ids),
                ],
                removed=[
                    *[_record_ref("canvas_node", node_id) for node_id in sorted(existing_node_ids)],
                    *[_record_ref("canvas_edge", edge_id) for edge_id in sorted(existing_edge_ids)],
                    *[_record_ref("canvas_route", route_id) for route_id in sorted(existing_route_ids)],
                    *[
                        _record_ref("canvas_work_chain", work_chain_id)
                        for work_chain_id in sorted(existing_work_chain_ids)
                    ],
                    *removed_version_refs,
                    *removed_task_refs,
                ],
            )
            resolved_changed_resources: list[str] = normalize_canvas_changed_resources(changed_resources)
            if existing_node_ids or added_node_refs or updated_node_refs:
                resolved_changed_resources.append("canvas_node")
            if existing_edge_ids:
                resolved_changed_resources.append("canvas_edge")
            if existing_route_ids:
                resolved_changed_resources.append("canvas_route")
            if added_route_refs or updated_route_refs:
                resolved_changed_resources.append("canvas_route")
            if existing_work_chain_ids:
                resolved_changed_resources.append("canvas_work_chain")
            if added_work_chain_refs or updated_work_chain_refs:
                resolved_changed_resources.append("canvas_work_chain")
            if removed_version_refs:
                resolved_changed_resources.append("canvas_version")
            if removed_task_refs:
                resolved_changed_resources.append("canvas_task")
            resolved_changed_resources = list(dict.fromkeys(resolved_changed_resources))
            mutation = _record_op(
                conn,
                episode_id=episode_id,
                op_type=normalized_op_type,
                base_revision=base_revision,
                revision=revision,
                payload={
                    "records": records,
                    "nodeIds": stored_node_ids,
                    "routeIds": [str(route.get("id") or "") for route in stored_routes],
                    "workChainIds": [str(chain.get("id") or "") for chain in stored_work_chains],
                    "removedNodeIds": sorted(existing_node_ids),
                    "removedEdgeIds": sorted(existing_edge_ids),
                    "removedRouteIds": sorted(existing_route_ids),
                    "removedWorkChainIds": sorted(existing_work_chain_ids),
                    "removedVersionRefs": _canvas_version_ref_payloads(removed_version_refs),
                    "removedTaskIds": [str(ref.get("id") or "") for ref in removed_task_refs],
                    "changedResources": resolved_changed_resources,
                },
            )
    return {
        "success": True,
        "episodeId": episode_id,
        "workflowVersion": revision,
        **{key: copy.deepcopy(value) for key, value in mutation.items() if key != "payload"},
        "nodes": stored_nodes,
        "routes": stored_routes,
        "workChains": stored_work_chains,
        "removedNodeIds": sorted(existing_node_ids),
        "removedEdgeIds": sorted(existing_edge_ids),
        "removedRouteIds": sorted(existing_route_ids),
        "removedWorkChainIds": sorted(existing_work_chain_ids),
        "removedVersionRefs": _canvas_version_ref_payloads(removed_version_refs),
        "removedTaskIds": [str(ref.get("id") or "") for ref in removed_task_refs],
    }


def write_canvas_card_records_v4(
    project_id: str,
    episode_id: str,
    nodes: list[dict[str, Any]],
    *,
    op_type: str = "card_patch",
    changed_resources: list[str] | None = None,
    expected_revision: int | str | None = None,
    merge_data: bool = False,
    data_transform: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    skip_missing: bool = False,
) -> dict[str, Any]:
    now = _now()
    normalized_op_type = str(op_type or "card_patch").strip() or "card_patch"
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            document = _canvas_mutation_document_in_conn(
                conn, episode_id, now=now, expected_revision=expected_revision,
            )
            base_revision = int(document["revision"] or 0)
            patched_nodes = _patch_workflow_cards_in_conn(
                conn,
                episode_id=episode_id,
                nodes=nodes,
                now=now,
                merge_data=merge_data,
                data_transform=data_transform,
                skip_missing=skip_missing,
            )

            if not patched_nodes:
                return {
                    "success": True,
                    "episodeId": episode_id,
                    "workflowVersion": base_revision,
                    "revision": base_revision,
                    "opType": normalized_op_type,
                    "nodes": [],
                    "records": _records_payload(),
                    "changedResources": [],
                }

            revision = base_revision + 1
            conn.execute(
                """
                UPDATE canvas_documents
                SET revision = ?, updated_at = ?
                WHERE episode_id = ?
                """,
                (revision, now, episode_id),
            )
            node_ids = [str(node.get("id") or "") for node in patched_nodes]
            records = _records_payload(
                updated=[
                    *[_record_ref("canvas_node", node_id) for node_id in node_ids if node_id],
                    *_version_refs_for_nodes(conn, episode_id=episode_id, node_ids=node_ids),
                ]
            )
            mutation = _record_op(
                conn,
                episode_id=episode_id,
                op_type=normalized_op_type,
                base_revision=base_revision,
                revision=revision,
                payload={
                    "records": records,
                    "nodeIds": node_ids,
                    "changedResources": copy.deepcopy(
                        changed_resources if isinstance(changed_resources, list) else []
                    ),
                },
            )
    return {
        "success": True,
        "episodeId": episode_id,
        "workflowVersion": revision,
        **{key: copy.deepcopy(value) for key, value in mutation.items() if key != "payload"},
        "nodes": patched_nodes,
    }
