# -*- coding: utf-8 -*-
"""在调用者事务中写入画布记录、关联行和变更日志。"""
from __future__ import annotations

import copy
import sqlite3
import uuid
from .canvas_ownership import (
    normalize_node_ownership,
)
from .canvas_reference_views import (
    remove_reference_views,
)
from .canvas_store_indexes import (
    _upsert_canvas_node_source_refs_in_conn,
    _upsert_canvas_version_identity_refs_in_conn,
)
from .canvas_store_records import (
    _CANVAS_VERSION_REFERENCE_DATA_KEYS,
    _CANVAS_VERSION_SELECTION_DATA_KEYS,
    _canvas_node_version_storage_node_id,
    _edge_data_record,
    _json_dumps,
    _json_loads,
    _json_signature,
    _node_position_record,
    _node_status_record,
    _node_summary_record,
    _normalized_card_versions,
    _record_edge_id,
    _record_node_id,
    _record_ref,
    _record_route_id,
    _record_work_chain_id,
    _records_payload,
    _route_summary_record,
    _row_node,
    _work_chain_summary_record,
    normalize_canvas_changed_resources,
)
from .store_core import (
    _now,
)
from typing import (
    Any,
    Callable,
)


_CANVAS_OP_LOG_RETENTION_REVISIONS = 2000


_CANVAS_OP_LOG_TRIM_INTERVAL_REVISIONS = 100


def _trim_canvas_ops_in_conn(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    current_revision: int,
) -> None:
    revision = int(current_revision or 0)
    if revision <= _CANVAS_OP_LOG_RETENTION_REVISIONS:
        return
    if revision % _CANVAS_OP_LOG_TRIM_INTERVAL_REVISIONS != 0:
        return
    cutoff_revision = revision - _CANVAS_OP_LOG_RETENTION_REVISIONS
    conn.execute(
        "DELETE FROM canvas_ops WHERE episode_id = ? AND revision <= ?",
        (episode_id, cutoff_revision),
    )


def _record_op(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    op_type: str,
    base_revision: int,
    revision: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    tx_id = f"canvas-tx-{uuid.uuid4().hex[:12]}"
    seq_row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM canvas_ops WHERE episode_id = ?",
        (episode_id,),
    ).fetchone()
    seq = int(seq_row["next_seq"] or 1) if seq_row is not None else 1
    payload_row = copy.deepcopy(payload if isinstance(payload, dict) else {})
    records = payload_row.get("records") if isinstance(payload_row.get("records"), dict) else _records_payload()
    changed_resources = normalize_canvas_changed_resources(payload_row.get("changedResources"))
    payload_row["changedResources"] = copy.deepcopy(changed_resources)
    conn.execute(
        """
        INSERT INTO canvas_ops (
            episode_id, seq, tx_id, op_type, base_revision, revision, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            episode_id,
            seq,
            tx_id,
            op_type,
            int(base_revision),
            int(revision),
            _json_dumps(payload_row),
            _now(),
        ),
    )
    _trim_canvas_ops_in_conn(
        conn,
        episode_id=episode_id,
        current_revision=int(revision),
    )
    return {
        "txId": tx_id,
        "seq": seq,
        "revision": int(revision),
        "baseRevision": int(base_revision),
        "opType": str(op_type or ""),
        "records": copy.deepcopy(records),
        "changedResources": copy.deepcopy(changed_resources),
        "payload": payload_row,
    }


def _write_canvas_task_rows_in_conn(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    tasks: list[dict[str, Any]],
    now: str,
    replace_all: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    existing_rows = conn.execute(
        """
        SELECT task_id, node_id, status, task_json
        FROM canvas_tasks
        WHERE episode_id = ?
        """,
        (episode_id,),
    ).fetchall()
    existing_signatures = {
        str(row["task_id"] or ""): _json_signature(
            {
                "nodeId": str(row["node_id"] or ""),
                "status": str(row["status"] or ""),
                "task": _json_loads(row["task_json"], {}),
            }
        )
        for row in existing_rows
    }
    existing_task_ids = set(existing_signatures.keys())
    updated_refs: list[dict[str, Any]] = []
    removed_refs: list[dict[str, Any]] = []
    stored_tasks: list[dict[str, Any]] = []
    active_task_ids: set[str] = set()
    for index, task in enumerate(tasks if isinstance(tasks, list) else []):
        if not isinstance(task, dict):
            continue
        task_row = copy.deepcopy(task)
        task_id = str(task_row.get("id") or task_row.get("taskId") or task_row.get("task_id") or "").strip()
        if not task_id and replace_all:
            task_id = f"workflow-task-{index + 1}"
            task_row["id"] = task_id
        if not task_id:
            continue
        active_task_ids.add(task_id)
        node_id = str(task_row.get("nodeId") or task_row.get("node_id") or "").strip()
        status = str(task_row.get("status") or "").strip()
        next_signature = _json_signature(
            {
                "nodeId": node_id,
                "status": status,
                "task": task_row,
            }
        )
        conn.execute(
            """
            INSERT INTO canvas_tasks (
                episode_id, task_id, node_id, status, task_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id, task_id) DO UPDATE SET
                node_id = excluded.node_id,
                status = excluded.status,
                task_json = excluded.task_json,
                updated_at = excluded.updated_at
            """,
            (episode_id, task_id, node_id, status, _json_dumps(task_row), now),
        )
        stored_tasks.append(task_row)
        if existing_signatures.get(task_id) != next_signature:
            updated_refs.append(_record_ref("canvas_task", task_id, nodeId=node_id))
    if replace_all:
        removed_task_ids = existing_task_ids - active_task_ids
        if active_task_ids:
            placeholders = ",".join("?" for _ in active_task_ids)
            removed_rows = conn.execute(
                f"""
                SELECT task_id, node_id
                FROM canvas_tasks
                WHERE episode_id = ? AND task_id NOT IN ({placeholders})
                """,
                (episode_id, *sorted(active_task_ids)),
            ).fetchall()
            conn.execute(
                f"DELETE FROM canvas_tasks WHERE episode_id = ? AND task_id NOT IN ({placeholders})",
                (episode_id, *sorted(active_task_ids)),
            )
        else:
            removed_rows = conn.execute(
                "SELECT task_id, node_id FROM canvas_tasks WHERE episode_id = ?",
                (episode_id,),
            ).fetchall()
            conn.execute("DELETE FROM canvas_tasks WHERE episode_id = ?", (episode_id,))
        removed_refs = [
            _record_ref("canvas_task", row["task_id"], nodeId=row["node_id"])
            for row in removed_rows
            if str(row["task_id"] or "") in removed_task_ids
        ]
    return stored_tasks, updated_refs, removed_refs


def _replace_canvas_routes(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    routes: list[Any],
    now: str,
) -> tuple[set[str], dict[str, str]]:
    active_route_ids: set[str] = set()
    active_route_signatures: dict[str, str] = {}
    for index, raw_route in enumerate(routes if isinstance(routes, list) else []):
        if not isinstance(raw_route, dict):
            continue
        route = copy.deepcopy(raw_route)
        route_id = _record_route_id(route, index)
        active_route_ids.add(route_id)
        active_route_signatures[route_id] = _json_signature(
            {
                "sortIndex": index,
                "route": route,
            }
        )
        conn.execute(
            """
            INSERT INTO canvas_routes (
                episode_id, route_id, sort_index, route_json, summary_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id, route_id) DO UPDATE SET
                sort_index = excluded.sort_index,
                route_json = excluded.route_json,
                summary_json = excluded.summary_json,
                updated_at = excluded.updated_at
            """,
            (
                episode_id,
                route_id,
                index,
                _json_dumps(route),
                _json_dumps(_route_summary_record(route)),
                now,
            ),
        )
    if active_route_ids:
        placeholders = ",".join("?" for _ in active_route_ids)
        conn.execute(
            f"DELETE FROM canvas_routes WHERE episode_id = ? AND route_id NOT IN ({placeholders})",
            (episode_id, *sorted(active_route_ids)),
        )
    else:
        conn.execute("DELETE FROM canvas_routes WHERE episode_id = ?", (episode_id,))
    return active_route_ids, active_route_signatures


def _replace_canvas_work_chains(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    work_chains: list[Any],
    now: str,
) -> tuple[set[str], dict[str, str]]:
    active_work_chain_ids: set[str] = set()
    active_work_chain_signatures: dict[str, str] = {}
    for index, raw_work_chain in enumerate(work_chains if isinstance(work_chains, list) else []):
        if not isinstance(raw_work_chain, dict):
            continue
        work_chain = copy.deepcopy(raw_work_chain)
        work_chain_id = _record_work_chain_id(work_chain, index)
        active_work_chain_ids.add(work_chain_id)
        active_work_chain_signatures[work_chain_id] = _json_signature(
            {
                "sortIndex": index,
                "workChain": work_chain,
            }
        )
        conn.execute(
            """
            INSERT INTO canvas_work_chains (
                episode_id, work_chain_id, sort_index, work_chain_json, summary_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id, work_chain_id) DO UPDATE SET
                sort_index = excluded.sort_index,
                work_chain_json = excluded.work_chain_json,
                summary_json = excluded.summary_json,
                updated_at = excluded.updated_at
            """,
            (
                episode_id,
                work_chain_id,
                index,
                _json_dumps(work_chain),
                _json_dumps(_work_chain_summary_record(work_chain)),
                now,
            ),
        )
    if active_work_chain_ids:
        placeholders = ",".join("?" for _ in active_work_chain_ids)
        conn.execute(
            f"DELETE FROM canvas_work_chains WHERE episode_id = ? AND work_chain_id NOT IN ({placeholders})",
            (episode_id, *sorted(active_work_chain_ids)),
        )
    else:
        conn.execute("DELETE FROM canvas_work_chains WHERE episode_id = ?", (episode_id,))
    return active_work_chain_ids, active_work_chain_signatures


def _patch_workflow_cards_in_conn(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    nodes: list[dict[str, Any]],
    now: str,
    merge_data: bool = False,
    data_transform: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    skip_missing: bool = False,
) -> list[dict[str, Any]]:
    patched_nodes: list[dict[str, Any]] = []
    seen_node_ids: set[str] = set()
    for raw_node in nodes if isinstance(nodes, list) else []:
        if not isinstance(raw_node, dict):
            continue
        node_id = str(raw_node.get("id") or "").strip()
        if not node_id or node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)
        existing = conn.execute(
            """
            SELECT sort_index, data_json, node_json
            FROM canvas_nodes
            WHERE episode_id = ? AND node_id = ?
            """,
            (episode_id, node_id),
        ).fetchone()
        if existing is None:
            if skip_missing:
                continue
            if merge_data or data_transform is not None:
                raise FileNotFoundError("任务卡已删除，结果未保存")
            continue
        stored_node = _json_loads(existing["node_json"], {})
        if not isinstance(stored_node, dict):
            stored_node = {}
        stored_data = _json_loads(existing["data_json"], {})
        if isinstance(stored_data, dict):
            stored_node["data"] = copy.deepcopy(stored_data)
        if raw_node.get("type") is not None:
            stored_node["type"] = str(raw_node.get("type") or "")
        for key in (
            "routeId",
            "segmentId",
            "workChainId",
            "locked",
            "lockedByUser",
            "locked_by_user",
            "lockedReason",
            "locked_reason",
            "preserveOnReplan",
            "preserve_on_replan",
            "position",
            "width",
            "height",
            "style",
            "className",
        ):
            if key in raw_node:
                stored_node[key] = copy.deepcopy(raw_node.get(key))
        stored_node["id"] = node_id
        if data_transform is not None:
            transformed_data = data_transform(copy.deepcopy(stored_node))
            if transformed_data is None:
                continue
            stored_node["data"] = transformed_data
        elif "data" in raw_node:
            patch_data = raw_node.get("data") if isinstance(raw_node.get("data"), dict) else {}
            if merge_data:
                next_data = stored_node.setdefault("data", {})
                for key, value in patch_data.items():
                    next_data[key] = (
                        {**next_data[key], **copy.deepcopy(value)}
                        if isinstance(next_data.get(key), dict) and isinstance(value, dict)
                        else copy.deepcopy(value)
                    )
            else:
                stored_node["data"] = copy.deepcopy(patch_data)
        remove_reference_views(stored_node)
        data = stored_node.get("data") if isinstance(stored_node.get("data"), dict) else {}
        summary = _node_summary_record(stored_node)
        conn.execute(
            """
            UPDATE canvas_nodes
            SET node_type = ?,
                route_id = ?,
                segment_id = ?,
                work_chain_id = ?,
                position_json = ?,
                status = ?,
                data_json = ?,
                node_json = ?,
                summary_json = ?,
                updated_at = ?
            WHERE episode_id = ? AND node_id = ?
            """,
            (
                str(stored_node.get("type") or ""),
                str(stored_node.get("routeId") or data.get("routeId") or ""),
                str(stored_node.get("segmentId") or data.get("segmentId") or ""),
                normalize_node_ownership(stored_node),
                _json_dumps(_node_position_record(stored_node)),
                _node_status_record(stored_node, data),
                _json_dumps(data),
                _json_dumps(stored_node),
                _json_dumps(summary),
                now,
                episode_id,
                node_id,
            ),
        )
        patched_nodes.append(copy.deepcopy(stored_node))
    return patched_nodes


def _upsert_canvas_nodes_in_conn(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    nodes: list[dict[str, Any]],
    now: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    stored_nodes: list[dict[str, Any]] = []
    added_refs: list[dict[str, Any]] = []
    updated_refs: list[dict[str, Any]] = []
    next_sort_row = conn.execute(
        "SELECT COALESCE(MAX(sort_index), -1) + 1 AS next_sort FROM canvas_nodes WHERE episode_id = ?",
        (episode_id,),
    ).fetchone()
    next_sort = int(next_sort_row["next_sort"] or 0) if next_sort_row is not None else 0
    seen_node_ids: set[str] = set()
    for raw_node in nodes if isinstance(nodes, list) else []:
        if not isinstance(raw_node, dict):
            continue
        node = copy.deepcopy(raw_node)
        node_id = _record_node_id(node, "")
        if not node_id:
            continue
        if node_id in seen_node_ids:
            raise ValueError(f"节点 id 重复：{node_id}")
        seen_node_ids.add(node_id)
        node["id"] = node_id
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node["data"] = data
        node_type = str(node.get("type") or data.get("eyebrow") or "").strip()
        if node_type:
            node["type"] = node_type
        remove_reference_views(node)
        route_id = str(node.get("routeId") or data.get("routeId") or "").strip()
        segment_id = str(node.get("segmentId") or data.get("segmentId") or "").strip()
        work_chain_id = normalize_node_ownership(node)
        position = _node_position_record(node)
        status = _node_status_record(node, data)
        summary = _node_summary_record(node)
        node_signature = _json_signature(
            {
                "sortIndex": None,
                "type": node_type,
                "routeId": route_id,
                "segmentId": segment_id,
                "workChainId": work_chain_id,
                "position": position,
                "status": status,
                "data": data,
                "node": node,
                "summary": summary,
            }
        )
        existing = conn.execute(
            """
            SELECT sort_index, node_type, route_id, segment_id, work_chain_id,
                   position_json, status, data_json, node_json, summary_json
            FROM canvas_nodes
            WHERE episode_id = ? AND node_id = ?
            """,
            (episode_id, node_id),
        ).fetchone()
        if existing is None:
            sort_index = next_sort
            next_sort += 1
            added_refs.append(_record_ref("canvas_node", node_id))
        else:
            sort_index = int(existing["sort_index"] or 0)
            existing_signature = _json_signature(
                {
                    "sortIndex": None,
                    "type": str(existing["node_type"] or ""),
                    "routeId": str(existing["route_id"] or ""),
                    "segmentId": str(existing["segment_id"] or ""),
                    "workChainId": str(existing["work_chain_id"] or ""),
                    "position": _json_loads(existing["position_json"], {}),
                    "status": str(existing["status"] or ""),
                    "data": _json_loads(existing["data_json"], {}),
                    "node": _json_loads(existing["node_json"], {}),
                    "summary": _json_loads(existing["summary_json"], {}),
                }
            )
            if existing_signature == node_signature:
                continue
            updated_refs.append(_record_ref("canvas_node", node_id))
        conn.execute(
            """
            INSERT INTO canvas_nodes (
                episode_id, node_id, sort_index, node_type, route_id,
                segment_id, work_chain_id, position_json, status,
                data_json, node_json, summary_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id, node_id) DO UPDATE SET
                sort_index = excluded.sort_index,
                node_type = excluded.node_type,
                route_id = excluded.route_id,
                segment_id = excluded.segment_id,
                work_chain_id = excluded.work_chain_id,
                position_json = excluded.position_json,
                status = excluded.status,
                data_json = excluded.data_json,
                node_json = excluded.node_json,
                summary_json = excluded.summary_json,
                updated_at = excluded.updated_at
            """,
            (
                episode_id,
                node_id,
                sort_index,
                node_type,
                route_id,
                segment_id,
                work_chain_id,
                _json_dumps(position),
                status,
                _json_dumps(data),
                _json_dumps(node),
                _json_dumps(summary),
                now,
            ),
        )
        _upsert_canvas_node_source_refs_in_conn(
            conn,
            episode_id=episode_id,
            target_node_id=node_id,
            data=data,
            now=now,
        )
        stored_nodes.append(copy.deepcopy(node))
    return stored_nodes, added_refs, updated_refs


def _upsert_canvas_edges_in_conn(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    edges: list[dict[str, Any]],
    now: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    stored_edges: list[dict[str, Any]] = []
    added_refs: list[dict[str, Any]] = []
    updated_refs: list[dict[str, Any]] = []
    next_sort_row = conn.execute(
        "SELECT COALESCE(MAX(sort_index), -1) + 1 AS next_sort FROM canvas_edges WHERE episode_id = ?",
        (episode_id,),
    ).fetchone()
    next_sort = int(next_sort_row["next_sort"] or 0) if next_sort_row is not None else 0
    seen_edge_ids: set[str] = set()
    for index, raw_edge in enumerate(edges if isinstance(edges, list) else []):
        if not isinstance(raw_edge, dict):
            continue
        edge = copy.deepcopy(raw_edge)
        edge_id = _record_edge_id(edge, index)
        if edge_id in seen_edge_ids:
            raise ValueError(f"连线 id 重复：{edge_id}")
        seen_edge_ids.add(edge_id)
        edge_source = str(edge.get("source") or "").strip()
        edge_target = str(edge.get("target") or "").strip()
        if not edge_source or not edge_target:
            raise ValueError("连线缺少 source 或 target")
        missing_endpoint = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM canvas_nodes
            WHERE episode_id = ? AND node_id IN (?, ?)
            """,
            (episode_id, edge_source, edge_target),
        ).fetchone()
        endpoint_count = int(missing_endpoint["total"] or 0) if missing_endpoint is not None else 0
        if endpoint_count < 2:
            raise ValueError("连线引用的节点不存在")
        source_handle = str(edge.get("sourceHandle") or edge.get("source_handle") or "").strip()
        target_handle = str(edge.get("targetHandle") or edge.get("target_handle") or "").strip()
        edge_data = _edge_data_record(edge)
        edge_signature = _json_signature(
            {
                "sortIndex": None,
                "source": edge_source,
                "target": edge_target,
                "sourceHandle": source_handle,
                "targetHandle": target_handle,
                "data": edge_data,
                "edge": edge,
            }
        )
        existing = conn.execute(
            """
            SELECT sort_index, source_node_id, target_node_id, source_handle,
                   target_handle, edge_data_json, edge_json
            FROM canvas_edges
            WHERE episode_id = ? AND edge_id = ?
            """,
            (episode_id, edge_id),
        ).fetchone()
        if existing is None:
            sort_index = next_sort
            next_sort += 1
            added_refs.append(_record_ref("canvas_edge", edge_id))
        else:
            sort_index = int(existing["sort_index"] or 0)
            existing_signature = _json_signature(
                {
                    "sortIndex": None,
                    "source": str(existing["source_node_id"] or ""),
                    "target": str(existing["target_node_id"] or ""),
                    "sourceHandle": str(existing["source_handle"] or ""),
                    "targetHandle": str(existing["target_handle"] or ""),
                    "data": _json_loads(existing["edge_data_json"], {}),
                    "edge": _json_loads(existing["edge_json"], {}),
                }
            )
            if existing_signature == edge_signature:
                continue
            updated_refs.append(_record_ref("canvas_edge", edge_id))
        conn.execute(
            """
            INSERT INTO canvas_edges (
                episode_id, edge_id, sort_index, source_node_id,
                target_node_id, source_handle, target_handle,
                edge_data_json, edge_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id, edge_id) DO UPDATE SET
                sort_index = excluded.sort_index,
                source_node_id = excluded.source_node_id,
                target_node_id = excluded.target_node_id,
                source_handle = excluded.source_handle,
                target_handle = excluded.target_handle,
                edge_data_json = excluded.edge_data_json,
                edge_json = excluded.edge_json,
                updated_at = excluded.updated_at
            """,
            (
                episode_id,
                edge_id,
                sort_index,
                edge_source,
                edge_target,
                source_handle,
                target_handle,
                _json_dumps(edge_data),
                _json_dumps(edge),
                now,
            ),
        )
        stored_edges.append(copy.deepcopy(edge))
    return stored_edges, added_refs, updated_refs


def _upsert_canvas_routes_in_conn(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    routes: list[dict[str, Any]],
    now: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    stored_routes: list[dict[str, Any]] = []
    added_refs: list[dict[str, Any]] = []
    updated_refs: list[dict[str, Any]] = []
    next_sort_row = conn.execute(
        "SELECT COALESCE(MAX(sort_index), -1) + 1 AS next_sort FROM canvas_routes WHERE episode_id = ?",
        (episode_id,),
    ).fetchone()
    next_sort = int(next_sort_row["next_sort"] or 0) if next_sort_row is not None else 0
    seen_route_ids: set[str] = set()
    for index, raw_route in enumerate(routes if isinstance(routes, list) else []):
        if not isinstance(raw_route, dict):
            continue
        route = copy.deepcopy(raw_route)
        route_id = _record_route_id(route, index)
        if route_id in seen_route_ids:
            raise ValueError(f"路线 id 重复：{route_id}")
        seen_route_ids.add(route_id)
        route_summary = _route_summary_record(route)
        route_signature = _json_signature(
            {
                "sortIndex": None,
                "route": route,
                "summary": route_summary,
            }
        )
        existing = conn.execute(
            """
            SELECT sort_index, route_json, summary_json
            FROM canvas_routes
            WHERE episode_id = ? AND route_id = ?
            """,
            (episode_id, route_id),
        ).fetchone()
        if existing is None:
            sort_index = next_sort
            next_sort += 1
            added_refs.append(_record_ref("canvas_route", route_id))
        else:
            sort_index = int(existing["sort_index"] or 0)
            existing_signature = _json_signature(
                {
                    "sortIndex": None,
                    "route": _json_loads(existing["route_json"], {}),
                    "summary": _json_loads(existing["summary_json"], {}),
                }
            )
            if existing_signature == route_signature:
                continue
            updated_refs.append(_record_ref("canvas_route", route_id))
        conn.execute(
            """
            INSERT INTO canvas_routes (
                episode_id, route_id, sort_index, route_json, summary_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id, route_id) DO UPDATE SET
                sort_index = excluded.sort_index,
                route_json = excluded.route_json,
                summary_json = excluded.summary_json,
                updated_at = excluded.updated_at
            """,
            (
                episode_id,
                route_id,
                sort_index,
                _json_dumps(route),
                _json_dumps(route_summary),
                now,
            ),
        )
        stored_routes.append(copy.deepcopy(route))
    return stored_routes, added_refs, updated_refs


def _upsert_canvas_work_chains_in_conn(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    work_chains: list[dict[str, Any]],
    now: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    stored_work_chains: list[dict[str, Any]] = []
    added_refs: list[dict[str, Any]] = []
    updated_refs: list[dict[str, Any]] = []
    next_sort_row = conn.execute(
        "SELECT COALESCE(MAX(sort_index), -1) + 1 AS next_sort FROM canvas_work_chains WHERE episode_id = ?",
        (episode_id,),
    ).fetchone()
    next_sort = int(next_sort_row["next_sort"] or 0) if next_sort_row is not None else 0
    seen_work_chain_ids: set[str] = set()
    for index, raw_work_chain in enumerate(work_chains if isinstance(work_chains, list) else []):
        if not isinstance(raw_work_chain, dict):
            continue
        work_chain = copy.deepcopy(raw_work_chain)
        work_chain_id = _record_work_chain_id(work_chain, index)
        if work_chain_id in seen_work_chain_ids:
            raise ValueError(f"工作链 id 重复：{work_chain_id}")
        seen_work_chain_ids.add(work_chain_id)
        work_chain_summary = _work_chain_summary_record(work_chain)
        work_chain_signature = _json_signature(
            {
                "sortIndex": None,
                "workChain": work_chain,
                "summary": work_chain_summary,
            }
        )
        existing = conn.execute(
            """
            SELECT sort_index, work_chain_json, summary_json
            FROM canvas_work_chains
            WHERE episode_id = ? AND work_chain_id = ?
            """,
            (episode_id, work_chain_id),
        ).fetchone()
        if existing is None:
            sort_index = next_sort
            next_sort += 1
            added_refs.append(_record_ref("canvas_work_chain", work_chain_id))
        else:
            sort_index = int(existing["sort_index"] or 0)
            existing_signature = _json_signature(
                {
                    "sortIndex": None,
                    "workChain": _json_loads(existing["work_chain_json"], {}),
                    "summary": _json_loads(existing["summary_json"], {}),
                }
            )
            if existing_signature == work_chain_signature:
                continue
            updated_refs.append(_record_ref("canvas_work_chain", work_chain_id))
        conn.execute(
            """
            INSERT INTO canvas_work_chains (
                episode_id, work_chain_id, sort_index, work_chain_json, summary_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id, work_chain_id) DO UPDATE SET
                sort_index = excluded.sort_index,
                work_chain_json = excluded.work_chain_json,
                summary_json = excluded.summary_json,
                updated_at = excluded.updated_at
            """,
            (
                episode_id,
                work_chain_id,
                sort_index,
                _json_dumps(work_chain),
                _json_dumps(work_chain_summary),
                now,
            ),
        )
        stored_work_chains.append(copy.deepcopy(work_chain))
    return stored_work_chains, added_refs, updated_refs


def _write_card_results_in_conn(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    card_id: str,
    versions: list[dict[str, Any]],
    active_version_id: str = "",
    now: str,
) -> list[dict[str, Any]]:
    normalized_versions = _normalized_card_versions(card_id, versions)
    default_node_id = str(card_id or "").strip()
    active_id = str(active_version_id or "").strip()
    active_version_ids_by_node: dict[str, set[str]] = {}
    sort_index_by_node: dict[str, int] = {}
    for version in normalized_versions:
        version_id = str(version.get("id") or "").strip()
        if not version_id:
            continue
        version["id"] = version_id
        row_node_id = str(version.get("nodeId") or default_node_id).strip() or default_node_id
        version["nodeId"] = row_node_id
        version["cardId"] = str(version.get("cardId") or row_node_id)
        active_version_ids_by_node.setdefault(row_node_id, set()).add(version_id)
        sort_index = sort_index_by_node.get(row_node_id, 0)
        sort_index_by_node[row_node_id] = sort_index + 1
        media = version.get("media") if isinstance(version.get("media"), dict) else {}
        conn.execute(
            """
            INSERT INTO canvas_versions (
                episode_id, node_id, version_id, sort_index, version_type,
                status, active, media_json, version_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id, node_id, version_id) DO UPDATE SET
                sort_index = excluded.sort_index,
                version_type = excluded.version_type,
                status = excluded.status,
                active = excluded.active,
                media_json = excluded.media_json,
                version_json = excluded.version_json,
                updated_at = excluded.updated_at
            """,
            (
                episode_id,
                row_node_id,
                version_id,
                sort_index,
                str(version.get("type") or ""),
                str(version.get("status") or ""),
                1 if row_node_id == default_node_id and version_id == active_id else 0,
                _json_dumps(media if isinstance(media, dict) else {}),
                _json_dumps(version),
                now,
            ),
        )
        _upsert_canvas_version_identity_refs_in_conn(
            conn,
            episode_id=episode_id,
            node_id=row_node_id,
            version_id=version_id,
            version=version,
            now=now,
        )
    for row_node_id, active_version_ids in active_version_ids_by_node.items():
        placeholders = ",".join("?" for _ in active_version_ids)
        conn.execute(
            f"""
            DELETE FROM canvas_versions
            WHERE episode_id = ? AND node_id = ? AND version_id NOT IN ({placeholders})
            """,
            (episode_id, row_node_id, *sorted(active_version_ids)),
        )
    if not active_version_ids_by_node:
        conn.execute(
            "DELETE FROM canvas_versions WHERE episode_id = ? AND node_id = ?",
            (episode_id, default_node_id),
        )
    return normalized_versions


def _clear_deleted_version_refs_in_conn(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    node_id: str,
    version_id: str,
    fallback_version: dict[str, Any] | None = None,
    now: str,
) -> list[dict[str, Any]]:
    target_node_id = str(node_id or "").strip()
    target_version_id = str(version_id or "").strip()
    if not target_node_id or not target_version_id:
        return []
    fallback = copy.deepcopy(fallback_version) if isinstance(fallback_version, dict) else {}
    fallback_version_id = str(fallback.get("id") or "").strip()
    fallback_media = fallback.get("media") if isinstance(fallback.get("media"), dict) else None
    rows = conn.execute(
        """
        SELECT node_id, node_type, route_id, segment_id, work_chain_id,
               position_json, status, data_json, node_json, summary_json
        FROM canvas_nodes
        WHERE episode_id = ?
        """,
        (episode_id,),
    ).fetchall()
    patched_nodes: list[dict[str, Any]] = []
    media_pointer_keys = {
        "activeVersionId",
        "sourceVersionId",
        "mediaVersionId",
        "assetVersionId",
        "activeMediaVersionId",
    }
    for row in rows:
        node = _row_node(row, detail="full")
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        row_node_id = str(node.get("id") or row["node_id"] or "").strip()
        version_owner_node_id = _canvas_node_version_storage_node_id(
            row_node_id,
            str(row["node_type"] or ""),
            data,
        )
        if version_owner_node_id != target_node_id:
            continue
        next_data = copy.deepcopy(data if isinstance(data, dict) else {})
        changed = False
        cleared_winner = False
        cleared_media_pointer = False
        for key in _CANVAS_VERSION_REFERENCE_DATA_KEYS:
            value = str(next_data.get(key) or "").strip()
            if value != target_version_id:
                continue
            if key == "winnerVersionId":
                next_data[key] = None
                cleared_winner = True
            elif fallback_version_id:
                next_data[key] = fallback_version_id
            else:
                next_data[key] = None
            changed = True
            if key in media_pointer_keys:
                cleared_media_pointer = True
        for key in _CANVAS_VERSION_REFERENCE_DATA_KEYS:
            value = str(node.get(key) or "").strip()
            if value != target_version_id:
                continue
            if key == "winnerVersionId":
                node[key] = None
                cleared_winner = True
            elif fallback_version_id:
                node[key] = fallback_version_id
            else:
                node[key] = None
            changed = True
        if cleared_winner:
            for key in _CANVAS_VERSION_SELECTION_DATA_KEYS:
                if key in next_data and next_data.get(key) is not None:
                    next_data[key] = None
                    changed = True
                if key in node and node.get(key) is not None:
                    node[key] = None
                    changed = True
        if cleared_media_pointer:
            if fallback_version_id:
                next_data["status"] = "ready"
                next_data["summary"] = str(fallback.get("summary") or next_data.get("summary") or "")
                if fallback_media:
                    next_data["media"] = copy.deepcopy(fallback_media)
                    next_data["mediaId"] = str(fallback_media.get("id") or next_data.get("mediaId") or "")
                    next_data.pop("storage", None)
                    if fallback.get("preview"):
                        next_data["preview"] = fallback.get("preview")
                else:
                    next_data.pop("media", None)
                    next_data.pop("mediaId", None)
                    next_data.pop("preview", None)
                    next_data.pop("storage", None)
            else:
                next_data.pop("media", None)
                next_data.pop("mediaId", None)
                next_data.pop("preview", None)
                next_data.pop("storage", None)
        if not changed:
            continue
        node["data"] = next_data
        node["updatedAt"] = now
        patched_nodes.extend(
            _patch_workflow_cards_in_conn(
                conn,
                episode_id=episode_id,
                nodes=[node],
                now=now,
            )
        )
    return patched_nodes


def _write_canvas_projection_document_in_conn(
    conn: sqlite3.Connection,
    episode_id: str,
    revision: int,
    viewport: dict[str, Any],
    routes: list[dict[str, Any]],
    work_chains: list[dict[str, Any]],
    state: dict[str, Any],
    extras: dict[str, Any],
    now: str,
) -> None:
    conn.execute(
        """
                INSERT INTO canvas_documents (
                    episode_id, schema_version, revision, viewport_json,
                    routes_json, work_chains_json, state_json, extras_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(episode_id) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    revision = excluded.revision,
                    viewport_json = excluded.viewport_json,
                    routes_json = excluded.routes_json,
                    work_chains_json = excluded.work_chains_json,
                    state_json = excluded.state_json,
                    extras_json = excluded.extras_json,
                    updated_at = excluded.updated_at
                """,
        (
            episode_id,
            4,
            revision,
            _json_dumps(viewport),
            _json_dumps(routes),
            _json_dumps(work_chains),
            _json_dumps(state),
            _json_dumps(extras),
            now,
        ),
    )


def _replace_canvas_projection_nodes_in_conn(
    conn: sqlite3.Connection,
    episode_id: str,
    nodes: list[dict[str, Any]],
    now: str,
) -> tuple[set[str], dict[str, str]]:
    active_node_ids: set[str] = set()
    active_node_signatures: dict[str, str] = {}
    for index, raw_node in enumerate(nodes):
        if not isinstance(raw_node, dict):
            continue
        node = copy.deepcopy(raw_node)
        remove_reference_views(node)
        node_id = _record_node_id(node, f"node-{index + 1}")
        node["id"] = node_id
        active_node_ids.add(node_id)
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node_type = str(node.get("type") or "")
        route_id = str(node.get("routeId") or data.get("routeId") or "")
        segment_id = str(node.get("segmentId") or data.get("segmentId") or "")
        work_chain_id = normalize_node_ownership(node)
        position = _node_position_record(node)
        status = _node_status_record(node, data)
        summary = _node_summary_record(node)
        active_node_signatures[node_id] = _json_signature(
            {
                "sortIndex": index,
                "type": node_type,
                "routeId": route_id,
                "segmentId": segment_id,
                "workChainId": work_chain_id,
                "position": position,
                "status": status,
                "data": data,
                "node": node,
            }
        )
        conn.execute(
            """
                    INSERT INTO canvas_nodes (
                        episode_id, node_id, sort_index, node_type, route_id,
                        segment_id, work_chain_id, position_json, status,
                        data_json, node_json, summary_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(episode_id, node_id) DO UPDATE SET
                        sort_index = excluded.sort_index,
                        node_type = excluded.node_type,
                        route_id = excluded.route_id,
                        segment_id = excluded.segment_id,
                        work_chain_id = excluded.work_chain_id,
                        position_json = excluded.position_json,
                        status = excluded.status,
                        data_json = excluded.data_json,
                        node_json = excluded.node_json,
                        summary_json = excluded.summary_json,
                        updated_at = excluded.updated_at
                    """,
            (
                episode_id,
                node_id,
                index,
                node_type,
                route_id,
                segment_id,
                work_chain_id,
                _json_dumps(position),
                status,
                _json_dumps(data),
                _json_dumps(node),
                _json_dumps(summary),
                now,
            ),
        )
        _upsert_canvas_node_source_refs_in_conn(
            conn,
            episode_id=episode_id,
            target_node_id=node_id,
            data=data,
            now=now,
        )
    if active_node_ids:
        placeholders = ",".join("?" for _ in active_node_ids)
        conn.execute(
            f"DELETE FROM canvas_nodes WHERE episode_id = ? AND node_id NOT IN ({placeholders})",
            (episode_id, *sorted(active_node_ids)),
        )
        conn.execute(
            f"DELETE FROM canvas_versions WHERE episode_id = ? AND node_id NOT IN ({placeholders})",
            (episode_id, *sorted(active_node_ids)),
        )
        conn.execute(
            f"DELETE FROM canvas_tasks WHERE episode_id = ? AND node_id NOT IN ({placeholders})",
            (episode_id, *sorted(active_node_ids)),
        )
    else:
        conn.execute("DELETE FROM canvas_nodes WHERE episode_id = ?", (episode_id,))
        conn.execute("DELETE FROM canvas_versions WHERE episode_id = ?", (episode_id,))
        conn.execute("DELETE FROM canvas_tasks WHERE episode_id = ?", (episode_id,))
    return active_node_ids, active_node_signatures


def _replace_canvas_projection_edges_in_conn(
    conn: sqlite3.Connection,
    episode_id: str,
    edges: list[dict[str, Any]],
    now: str,
) -> tuple[set[str], dict[str, str]]:
    active_edge_ids: set[str] = set()
    active_edge_signatures: dict[str, str] = {}
    for index, raw_edge in enumerate(edges):
        if not isinstance(raw_edge, dict):
            continue
        edge = copy.deepcopy(raw_edge)
        edge_id = _record_edge_id(edge, index)
        active_edge_ids.add(edge_id)
        edge_source = str(edge.get("source") or "").strip()
        edge_target = str(edge.get("target") or "").strip()
        source_handle = str(edge.get("sourceHandle") or edge.get("source_handle") or "").strip()
        target_handle = str(edge.get("targetHandle") or edge.get("target_handle") or "").strip()
        edge_data = _edge_data_record(edge)
        active_edge_signatures[edge_id] = _json_signature(
            {
                "sortIndex": index,
                "source": edge_source,
                "target": edge_target,
                "sourceHandle": source_handle,
                "targetHandle": target_handle,
                "data": edge_data,
                "edge": edge,
            }
        )
        conn.execute(
            """
                    INSERT INTO canvas_edges (
                        episode_id, edge_id, sort_index, source_node_id,
                        target_node_id, source_handle, target_handle,
                        edge_data_json, edge_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(episode_id, edge_id) DO UPDATE SET
                        sort_index = excluded.sort_index,
                        source_node_id = excluded.source_node_id,
                        target_node_id = excluded.target_node_id,
                        source_handle = excluded.source_handle,
                        target_handle = excluded.target_handle,
                        edge_data_json = excluded.edge_data_json,
                        edge_json = excluded.edge_json,
                        updated_at = excluded.updated_at
                    """,
            (
                episode_id,
                edge_id,
                index,
                edge_source,
                edge_target,
                source_handle,
                target_handle,
                _json_dumps(edge_data),
                _json_dumps(edge),
                now,
            ),
        )
    if active_edge_ids:
        placeholders = ",".join("?" for _ in active_edge_ids)
        conn.execute(
            f"DELETE FROM canvas_edges WHERE episode_id = ? AND edge_id NOT IN ({placeholders})",
            (episode_id, *sorted(active_edge_ids)),
        )
    else:
        conn.execute("DELETE FROM canvas_edges WHERE episode_id = ?", (episode_id,))
    return active_edge_ids, active_edge_signatures
