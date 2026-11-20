# -*- coding: utf-8 -*-
"""画布、节点、关联上下文、变更日志和版本的只读查询。"""
from __future__ import annotations

import copy
import json
import sqlite3
from .canvas_store_database import (
    _canvas_connection,
    _canvas_document_row,
    _canvas_snapshot_connection,
    canvas_db_path,
)
from .canvas_store_records import (
    CanvasProjectionState,
    _json_signature,
    _canvas_change_row,
    _canvas_document_extras_payload,
    _canvas_document_payload,
    _canvas_record_ids_from_payload,
    _canvas_signature_hash_from_json,
    _canvas_version_ref_from_value,
    _empty_canvas_document_payload,
    _input_link_source_node_ids,
    _json_loads,
    _merge_canvas_record_ids,
    _node_route_ids,
    _node_work_chain_ids,
    _record_id_set,
    _record_ref,
    _row_edge,
    _row_node,
    _row_route,
    _row_version,
    _row_work_chain,
    empty_canvas_workflow_projection_v4,
)
from .perf_logging import (
    canvas_perf_elapsed_ms,
    canvas_perf_log,
    canvas_perf_start,
)
from typing import (
    Any,
)


def get_canvas_context_v4(project_id: str, episode_id: str) -> dict[str, Any]:
    if not canvas_db_path(project_id).exists():
        return {
            "canvasKind": "work_chain", "autoWorkflowInitialized": False,
        }
    with _canvas_connection(project_id) as conn:
        document = _canvas_document_row(conn, episode_id)
        extras = _canvas_document_extras_payload(document)
        custom = conn.execute(
            "SELECT canvas_id FROM canvas_catalog WHERE storage_key = ? AND canvas_kind = 'custom' AND archived = 0",
            (episode_id,),
        ).fetchone()
        return {
            "canvasKind": "custom" if custom else "work_chain",
            "autoWorkflowInitialized": bool(extras.get("autoWorkflowInitialized")) if not custom else False,
        }


def read_canvas_card_locator_v4(project_id: str, episode_id: str, node: dict[str, Any]) -> str:
    """Match workflowCardHeaderLocator without loading other cards' content."""
    data = node.get("data") or {}
    if not any(node.get(key) or data.get(key) for key in ("segmentId", "routeId", "workChainId")):
        return str(data.get("title") or node.get("title") or "").strip()
    with _canvas_snapshot_connection(project_id) as conn:
        routes = [_json_loads(row[0], {}) for row in conn.execute(
            "SELECT route_json FROM canvas_routes WHERE episode_id = ? ORDER BY sort_index, route_id", (episode_id,))]
        chains = [_json_loads(row[0], {}) for row in conn.execute(
            "SELECT work_chain_json FROM canvas_work_chains WHERE episode_id = ? ORDER BY sort_index, work_chain_id", (episode_id,))]
        node_segments = [row[0] for row in conn.execute(
            "SELECT segment_id FROM canvas_nodes WHERE episode_id = ? ORDER BY sort_index, node_id", (episode_id,))]
    segments = list(dict.fromkeys(value for value in [
        *(route.get("segmentId") for route in routes),
        *(segment for chain in chains for segment in chain.get("segmentIds") or []),
        *node_segments,
    ] if value))
    route = next((row for row in routes if row.get("id") == (node.get("routeId") or data.get("routeId"))), {})
    segment_id = node.get("segmentId") or data.get("segmentId") or route.get("segmentId")
    segment = f"片段{segments.index(segment_id) + 1 if segment_id in segments else 1:02d}"
    if node.get("type") in {"prompt.storyboard", "director.board"}:
        return segment
    shots = sorted(value for value in data.get("shotNos") or [] if type(value) is int and value > 0)
    if not shots:
        return segment
    last = f"-{shots[-1]:02d}" if len(shots) > 1 else ""
    return f"{segment}/镜头{shots[0]:02d}{last}"


def _version_refs_for_nodes(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    node_ids: list[str],
) -> list[dict[str, Any]]:
    cleaned_ids = [str(node_id or "").strip() for node_id in node_ids if str(node_id or "").strip()]
    if not cleaned_ids:
        return []
    placeholders = ",".join("?" for _ in cleaned_ids)
    rows = conn.execute(
        f"""
        SELECT node_id, version_id, active
        FROM canvas_versions
        WHERE episode_id = ? AND node_id IN ({placeholders})
        ORDER BY node_id ASC, sort_index ASC, version_id ASC
        """,
        (episode_id, *cleaned_ids),
    ).fetchall()
    return [
        _record_ref(
            "canvas_version",
            row["version_id"],
            nodeId=row["node_id"],
            active=bool(row["active"]),
        )
        for row in rows
    ]


def _canvas_records_for_ids_in_conn(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    ids: dict[str, set[Any]],
    detail: str = "full",
) -> dict[str, list[Any]]:
    records: dict[str, list[Any]] = {
        "nodes": [],
        "edges": [],
        "routes": [],
        "workChains": [],
        "versions": [],
        "tasks": [],
        "projections": [],
    }

    node_ids = sorted(ids.get("nodes") or set())
    if node_ids:
        placeholders = ",".join("?" for _ in node_ids)
        rows = conn.execute(
            f"""
            SELECT node_id, node_type, route_id, segment_id, work_chain_id,
                   position_json, status, data_json, node_json, summary_json
            FROM canvas_nodes
            WHERE episode_id = ? AND node_id IN ({placeholders})
            ORDER BY sort_index ASC, node_id ASC
            """,
            (episode_id, *node_ids),
        ).fetchall()
        records["nodes"] = [_row_node(row, detail=detail) for row in rows]

    edge_ids = sorted(ids.get("edges") or set())
    if edge_ids:
        placeholders = ",".join("?" for _ in edge_ids)
        rows = conn.execute(
            f"""
            SELECT edge_json
            FROM canvas_edges
            WHERE episode_id = ? AND edge_id IN ({placeholders})
            ORDER BY sort_index ASC, edge_id ASC
            """,
            (episode_id, *edge_ids),
        ).fetchall()
        records["edges"] = [
            edge
            for edge in (_json_loads(row["edge_json"], {}) for row in rows)
            if isinstance(edge, dict)
        ]

    route_ids = sorted(ids.get("routes") or set())
    if route_ids:
        placeholders = ",".join("?" for _ in route_ids)
        rows = conn.execute(
            f"""
            SELECT route_json, summary_json
            FROM canvas_routes
            WHERE episode_id = ? AND route_id IN ({placeholders})
            ORDER BY sort_index ASC, route_id ASC
            """,
            (episode_id, *route_ids),
        ).fetchall()
        records["routes"] = [_row_route(row, detail=detail) for row in rows]

    work_chain_ids = sorted(ids.get("workChains") or set())
    if work_chain_ids:
        placeholders = ",".join("?" for _ in work_chain_ids)
        rows = conn.execute(
            f"""
            SELECT work_chain_json, summary_json
            FROM canvas_work_chains
            WHERE episode_id = ? AND work_chain_id IN ({placeholders})
            ORDER BY sort_index ASC, work_chain_id ASC
            """,
            (episode_id, *work_chain_ids),
        ).fetchall()
        records["workChains"] = [_row_work_chain(row, detail=detail) for row in rows]

    version_refs = sorted(
        ref
        for ref in (ids.get("versionRefs") or set())
        if isinstance(ref, tuple) and len(ref) == 2 and ref[0] and ref[1]
    )
    if version_refs:
        rows: list[sqlite3.Row] = []
        for start in range(0, len(version_refs), 400):
            chunk = version_refs[start : start + 400]
            clauses = " OR ".join("(node_id = ? AND version_id = ?)" for _ in chunk)
            params: list[Any] = [episode_id]
            for node_id, version_id in chunk:
                params.extend([node_id, version_id])
            rows.extend(
                conn.execute(
                    f"""
                    SELECT node_id, version_id, active, version_json
                    FROM canvas_versions
                    WHERE episode_id = ? AND ({clauses})
                    ORDER BY node_id ASC, sort_index ASC, version_id ASC
                    """,
                    tuple(params),
                ).fetchall()
            )
        records["versions"] = [_row_version(row) for row in rows]

    task_ids = sorted(ids.get("tasks") or set())
    if task_ids:
        placeholders = ",".join("?" for _ in task_ids)
        rows = conn.execute(
            f"""
            SELECT task_json
            FROM canvas_tasks
            WHERE episode_id = ? AND task_id IN ({placeholders})
            ORDER BY updated_at ASC, task_id ASC
            """,
            (episode_id, *task_ids),
        ).fetchall()
        records["tasks"] = [
            task
            for task in (_json_loads(row["task_json"], {}) for row in rows)
            if isinstance(task, dict)
        ]

    projection_keys = sorted(ids.get("projections") or set())
    if projection_keys:
        placeholders = ",".join("?" for _ in projection_keys)
        rows = conn.execute(
            f"""
            SELECT cache_key, cache_type, payload_json, revision, updated_at
            FROM canvas_projection_cache
            WHERE episode_id = ? AND cache_key IN ({placeholders})
            ORDER BY cache_type ASC, cache_key ASC
            """,
            (episode_id, *projection_keys),
        ).fetchall()
        records["projections"] = [
            {
                "id": row["cache_key"],
                "key": row["cache_key"],
                "type": row["cache_type"],
                "payload": _json_loads(row["payload_json"], {}),
                "revision": int(row["revision"] or 0),
                "updatedAt": row["updated_at"],
            }
            for row in rows
        ]

    return records


def episode_canvas_exists(project_id: str, episode_id: str) -> bool:
    with _canvas_connection(project_id) as conn:
        return _canvas_document_row(conn, episode_id) is not None


def read_canvas_workflow_projection_v4(
    project_id: str,
    episode_id: str,
    *,
    detail: str = "full",
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    perf_started_at = canvas_perf_start()
    detail = "summary" if str(detail or "").strip().lower() == "summary" else "full"
    status = "ok"
    node_count = 0
    edge_count = 0
    route_count = 0
    work_chain_count = 0
    revision = 0
    try:
        with _canvas_snapshot_connection(project_id) as conn:
            document = _canvas_document_row(conn, episode_id)
            if document is None:
                status = "missing_document"
                return empty_canvas_workflow_projection_v4(project_id, episode_id)
            revision = int(document["revision"] or 0)
            node_rows = conn.execute(
                """
                SELECT node_id, node_type, route_id, segment_id, work_chain_id,
                       position_json, status, data_json, node_json, summary_json
                FROM canvas_nodes
                WHERE episode_id = ?
                ORDER BY sort_index ASC, node_id ASC
                """,
                (episode_id,),
            ).fetchall()
            edge_rows = conn.execute(
                """
                SELECT edge_json
                FROM canvas_edges
                WHERE episode_id = ?
                ORDER BY sort_index ASC, edge_id ASC
                """,
                (episode_id,),
            ).fetchall()
            route_rows = conn.execute(
                """
                SELECT route_json, summary_json
                FROM canvas_routes
                WHERE episode_id = ?
                ORDER BY sort_index ASC, route_id ASC
                """,
                (episode_id,),
            ).fetchall()
            work_chain_rows = conn.execute(
                """
                SELECT work_chain_json, summary_json
                FROM canvas_work_chains
                WHERE episode_id = ?
                ORDER BY sort_index ASC, work_chain_id ASC
                """,
                (episode_id,),
            ).fetchall()
        nodes = [_row_node(row, detail=detail) for row in node_rows]
        edges = [
            edge
            for edge in (_json_loads(row["edge_json"], {}) for row in edge_rows)
            if isinstance(edge, dict)
        ]
        routes = [_row_route(row, detail=detail) for row in route_rows]
        work_chains = [_row_work_chain(row, detail=detail) for row in work_chain_rows]
        node_count = len(nodes)
        edge_count = len(edges)
        route_count = len(routes)
        work_chain_count = len(work_chains)
        document_state = _json_loads(document["state_json"], {})
        workflow_state = copy.deepcopy(document_state) if isinstance(document_state, dict) else {}
        if isinstance(state, dict) and state:
            workflow_state.update(copy.deepcopy(state))
        workflow = {
            "episodeId": episode_id,
            "schemaVersion": int(document["schema_version"] or 4),
            "version": revision,
            "viewport": _json_loads(document["viewport_json"], {"x": 0, "y": 0, "zoom": 0.82}),
            "routes": routes,
            "nodes": nodes,
            "edges": edges,
            "workChains": work_chains,
            "state": workflow_state,
        }
        if not workflow["state"]:
            workflow["state"] = {
                "kind": "canvas",
                "reason": "loaded",
                "sourceReady": True,
                "workChainPlanReady": False,
                "workflowChainReady": bool(nodes),
                "nextAction": "run_workflow",
            }
        workflow.update(_canvas_document_extras_payload(document))
        return workflow
    except Exception:
        status = "error"
        raise
    finally:
        canvas_perf_log(
            "read_canvas_workflow_projection_v4",
            projectId=project_id,
            episodeId=episode_id,
            detail=detail,
            status=status,
            durationMs=canvas_perf_elapsed_ms(perf_started_at),
            nodeCount=node_count,
            edgeCount=edge_count,
            routeCount=route_count,
            workChainCount=work_chain_count,
            revision=revision,
        )


def _immediate_previous_work_chain_v4(
    conn: sqlite3.Connection, episode_id: str, current_work_chain_id: str,
) -> tuple[str, str]:
    """Resolve a neighbor only when both positions have an unambiguous order."""
    current = conn.execute(
        "SELECT sort_index, work_chain_json FROM canvas_work_chains WHERE episode_id = ? AND work_chain_id = ?",
        (episode_id, current_work_chain_id),
    ).fetchone()
    if current is None:
        return "unavailable_order", ""
    chain = _json_loads(current["work_chain_json"], {})
    origin = chain.get("origin") if isinstance(chain, dict) else None
    if not isinstance(origin, dict) or origin.get("kind") not in {"source_split", "independent", "independent_source"}:
        return "unavailable_order", ""
    if origin["kind"] in {"independent", "independent_source"}:
        return "no_previous", ""
    source_id = str(origin.get("sourceNodeId") or "")
    if not source_id:
        return "unavailable_order", ""
    same_position = conn.execute(
        "SELECT work_chain_id FROM canvas_work_chains WHERE episode_id = ? AND sort_index = ? LIMIT 2",
        (episode_id, current["sort_index"]),
    ).fetchall()
    if len(same_position) != 1:
        return "unavailable_order", ""
    previous = conn.execute(
        """SELECT work_chain_id, sort_index, work_chain_json FROM canvas_work_chains
           WHERE episode_id = ? AND sort_index < ?
           ORDER BY sort_index DESC LIMIT 2""",
        (episode_id, current["sort_index"]),
    ).fetchall()
    if not previous:
        return "no_previous", ""
    if len(previous) > 1 and previous[0]["sort_index"] == previous[1]["sort_index"]:
        return "unavailable_order", ""
    prior_chain = _json_loads(previous[0]["work_chain_json"], {})
    prior_origin = prior_chain.get("origin") if isinstance(prior_chain, dict) else None
    if (not isinstance(prior_origin, dict) or prior_origin.get("kind") != "source_split"
            or str(prior_origin.get("sourceNodeId") or "") != source_id):
        return "no_previous", ""
    return "available", str(previous[0]["work_chain_id"])


def read_previous_cinematic_script_text_v4(
    project_id: str, episode_id: str, current_work_chain_id: str,
) -> str:
    """Read only the immediately preceding chain's saved script text."""
    if not current_work_chain_id:
        return ""
    with _canvas_snapshot_connection(project_id) as conn:
        status, previous_chain_id = _immediate_previous_work_chain_v4(conn, episode_id, current_work_chain_id)
        if status == "unavailable_order":
            raise ValueError("无法确定紧邻上一工作链的顺序，请检查当前画布后再生成")
        if status == "no_previous":
            return ""
        rows = conn.execute(
            """SELECT data_json FROM canvas_nodes
               WHERE episode_id = ? AND work_chain_id = ? AND node_type = 'prompt.storyboard'
               LIMIT 2""",
            (episode_id, previous_chain_id),
        ).fetchall()
        if len(rows) != 1:
            return ""
        data = _json_loads(rows[0]["data_json"], {})
        return str(data.get("cinematicStoryText") or "") if isinstance(data, dict) else ""


def read_work_chain_shootable_context_v4(
    project_id: str, episode_id: str, work_chain_id: str,
) -> dict[str, str]:
    """Read one chain's saved script, or its saved source fragment if no script exists."""
    if not work_chain_id:
        return {"kind": "none", "text": ""}
    with _canvas_snapshot_connection(project_id) as conn:
        rows = conn.execute(
            """SELECT node_id, data_json FROM canvas_nodes
               WHERE episode_id = ? AND work_chain_id = ? AND node_type = 'prompt.storyboard'
               ORDER BY node_id LIMIT 2""",
            (episode_id, work_chain_id),
        ).fetchall()
    if len(rows) != 1:
        return {"kind": "none", "text": ""}
    data = _json_loads(rows[0]["data_json"], {})
    if not isinstance(data, dict):
        return {"kind": "none", "text": ""}
    script = str(data.get("cinematicStoryText") or "").strip()
    source = str(data.get("sourceFactText") or "").strip()
    if script:
        return {"kind": "cinematic_script", "text": script, "nodeId": rows[0]["node_id"]}
    if source:
        return {"kind": "source_fragment", "text": source, "nodeId": rows[0]["node_id"]}
    return {"kind": "none", "text": ""}


def read_previous_director_plan_boundary_v4(
    project_id: str, episode_id: str, current_work_chain_id: str,
) -> dict[str, Any]:
    """Read the preceding saved plan's last shot, never another session's draft.

    Chain order is the persisted episode order, independent of card coordinates.
    An empty immediate predecessor must not fall back to an older completed chain.
    """
    if not current_work_chain_id:
        return {"status": "unavailable_order"}
    with _canvas_snapshot_connection(project_id) as conn:
        status, previous_chain_id = _immediate_previous_work_chain_v4(conn, episode_id, current_work_chain_id)
        if status == "unavailable_order":
            return {"status": "unavailable_order"}
        if status == "no_previous":
            return {"status": "no_previous"}
        result: dict[str, Any] = {
            "episodeId": episode_id, "workChainId": previous_chain_id,
            "status": "missing_plan",
        }
        rows = conn.execute(
            """SELECT node_id, data_json FROM canvas_nodes
               WHERE episode_id = ? AND work_chain_id = ? AND node_type = 'director.board'
               ORDER BY node_id LIMIT 2""",
            (episode_id, previous_chain_id),
        ).fetchall()
        if len(rows) > 1:
            return {**result, "status": "ambiguous", "nodeIds": [row["node_id"] for row in rows]}
        if not rows:
            return result
        row = rows[0]
        data = _json_loads(row["data_json"], {})
        data = data if isinstance(data, dict) else {}
        shots = data.get("directorPlanShots")
        text = str(data.get("directorPlan") or "").strip()
        result.update({
            "nodeId": row["node_id"],
            "sourceVersion": _canvas_signature_hash_from_json(_json_signature({
                "shots": shots, "text": text, "speakerRoster": data.get("speakerRoster"),
            })),
        })
        if isinstance(shots, list) and shots and isinstance(shots[-1], dict) and shots[-1].get("storyboardFrame"):
            last_shot = copy.deepcopy(shots[-1])
            speaker_ids = {event.get("speakerId") for event in last_shot.get("soundEvents") or []
                           if isinstance(event, dict)}
            result.update({"status": "available", "lastShot": last_shot,
                           "speakerRoster": [copy.deepcopy(item) for item in data.get("speakerRoster") or []
                                             if isinstance(item, dict) and item.get("speakerId") in speaker_ids]})
        elif text:
            # Legacy/manual text has no safe syntactic last-shot extraction.
            result.update({"status": "text_only", "directorPlanText": text})
        return result


def read_canvas_card_record_v4(
    project_id: str,
    episode_id: str,
    card_id: str,
    *,
    detail: str = "full",
) -> dict[str, Any]:
    node_id = str(card_id or "").strip()
    if not node_id:
        raise ValueError("缺少节点ID")
    detail = "summary" if str(detail or "").strip().lower() == "summary" else "full"
    with _canvas_connection(project_id) as conn:
        if _canvas_document_row(conn, episode_id) is None:
            raise FileNotFoundError("画布不存在")
        row = conn.execute(
            """
            SELECT node_id, node_type, route_id, segment_id, work_chain_id,
                   position_json, status, data_json, node_json, summary_json
            FROM canvas_nodes
            WHERE episode_id = ? AND node_id = ?
            """,
            (episode_id, node_id),
        ).fetchone()
    if row is None:
        raise FileNotFoundError("节点不存在")
    return _row_node(row, detail=detail)


def _canvas_node_row_by_id_in_conn(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    node_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT node_id, node_type, route_id, segment_id, work_chain_id,
               position_json, status, data_json, node_json, summary_json
        FROM canvas_nodes
        WHERE episode_id = ? AND node_id = ?
        """,
        (episode_id, node_id),
    ).fetchone()


def _canvas_prompt_storyboard_order_rows(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            n.node_id,
            n.sort_index AS node_sort_index,
            COALESCE(w.sort_index, 2147483647) AS work_chain_sort_index,
            COALESCE(r.sort_index, 2147483647) AS route_sort_index,
            CAST(COALESCE(json_extract(n.position_json, '$.y'), 0) AS REAL) AS node_y,
            CAST(COALESCE(json_extract(n.position_json, '$.x'), 0) AS REAL) AS node_x
        FROM canvas_nodes n
        LEFT JOIN canvas_routes r
          ON r.episode_id = n.episode_id
         AND r.route_id = n.route_id
        LEFT JOIN canvas_work_chains w
          ON w.episode_id = n.episode_id
         AND w.work_chain_id = COALESCE(
                NULLIF(n.work_chain_id, ''),
                NULLIF(json_extract(r.route_json, '$.workChainId'), ''),
                NULLIF(json_extract(r.route_json, '$.work_chain_id'), '')
             )
        WHERE n.episode_id = ?
          AND n.node_type = 'prompt.storyboard'
        ORDER BY
            work_chain_sort_index ASC,
            route_sort_index ASC,
            node_y ASC,
            node_x ASC,
            n.sort_index ASC,
            n.node_id ASC
        """,
        (episode_id,),
    ).fetchall()


def read_canvas_prompt_storyboard_boundary_node_v4(
    project_id: str,
    episode_id: str,
    *,
    boundary: str = "first",
    detail: str = "full",
) -> dict[str, Any]:
    detail = "summary" if str(detail or "").strip().lower() == "summary" else "full"
    normalized_boundary = str(boundary or "first").strip().lower()
    with _canvas_connection(project_id) as conn:
        if _canvas_document_row(conn, episode_id) is None:
            return {}
        order_rows = _canvas_prompt_storyboard_order_rows(conn, episode_id=episode_id)
        if not order_rows:
            return {}
        selected_row = order_rows[-1] if normalized_boundary == "last" else order_rows[0]
        selected_node_id = str(selected_row["node_id"] or "").strip()
        node_row = _canvas_node_row_by_id_in_conn(
            conn,
            episode_id=episode_id,
            node_id=selected_node_id,
        )
    return _row_node(node_row, detail=detail) if node_row is not None else {}


def read_canvas_prompt_storyboard_neighbor_node_v4(
    project_id: str,
    episode_id: str,
    node_id: str,
    *,
    direction: str = "next",
    detail: str = "full",
) -> dict[str, Any]:
    current_node_id = str(node_id or "").strip()
    if not current_node_id:
        return {}
    detail = "summary" if str(detail or "").strip().lower() == "summary" else "full"
    normalized_direction = str(direction or "next").strip().lower()
    step = -1 if normalized_direction in {"previous", "prev", "before"} else 1
    with _canvas_connection(project_id) as conn:
        if _canvas_document_row(conn, episode_id) is None:
            return {}
        order_rows = _canvas_prompt_storyboard_order_rows(conn, episode_id=episode_id)
        current_index = next(
            (
                index
                for index, row in enumerate(order_rows)
                if str(row["node_id"] or "").strip() == current_node_id
            ),
            -1,
        )
        target_index = current_index + step
        if current_index < 0 or target_index < 0 or target_index >= len(order_rows):
            return {}
        target_node_id = str(order_rows[target_index]["node_id"] or "").strip()
        node_row = _canvas_node_row_by_id_in_conn(
            conn,
            episode_id=episode_id,
            node_id=target_node_id,
        )
    return _row_node(node_row, detail=detail) if node_row is not None else {}


def read_canvas_cross_episode_visual_handoff_node_v4(
    project_id: str,
    episode_id: str,
    *,
    source_episode_id: str,
    source_node_id: str,
    detail: str = "full",
) -> dict[str, Any]:
    normalized_source_episode_id = str(source_episode_id or "").strip()
    normalized_source_node_id = str(source_node_id or "").strip()
    if not normalized_source_episode_id or not normalized_source_node_id:
        return {}
    detail = "summary" if str(detail or "").strip().lower() == "summary" else "full"
    with _canvas_connection(project_id) as conn:
        if _canvas_document_row(conn, episode_id) is None:
            return {}
        row = conn.execute(
            """
            SELECT node_id, node_type, route_id, segment_id, work_chain_id,
                   position_json, status, data_json, node_json, summary_json
            FROM canvas_nodes
            WHERE episode_id = ?
              AND node_type = 'media.external'
              AND json_extract(data_json, '$.mediaPurpose') = 'visual_handoff'
              AND json_extract(data_json, '$.sourceEpisodeId') = ?
              AND json_extract(data_json, '$.sourceNodeId') = ?
            ORDER BY sort_index ASC, node_id ASC
            LIMIT 1
            """,
            (episode_id, normalized_source_episode_id, normalized_source_node_id),
        ).fetchone()
    return _row_node(row, detail=detail) if row is not None else {}


def read_canvas_visual_handoff_result_node_v4(
    project_id: str,
    episode_id: str,
    *,
    prompt_node_id: str,
    detail: str = "full",
) -> dict[str, Any]:
    normalized_prompt_node_id = str(prompt_node_id or "").strip()
    if not normalized_prompt_node_id:
        return {}
    detail = "summary" if str(detail or "").strip().lower() == "summary" else "full"
    with _canvas_connection(project_id) as conn:
        if _canvas_document_row(conn, episode_id) is None:
            return {}
        row = conn.execute(
            """
            SELECT n.node_id, n.node_type, n.route_id, n.segment_id, n.work_chain_id,
                   n.position_json, n.status, n.data_json, n.node_json, n.summary_json
            FROM canvas_node_source_refs s
            JOIN canvas_nodes n
              ON n.episode_id = s.episode_id
             AND n.node_id = s.target_node_id
            WHERE s.episode_id = ?
              AND s.source_node_id = ?
              AND s.ref_kind IN ('result', 'source')
              AND n.node_type = 'asset.image'
              AND (
                    json_extract(n.data_json, '$.mediaPurpose') = 'visual_handoff'
                 OR json_extract(n.data_json, '$.media_purpose') = 'visual_handoff'
                 OR json_extract(n.data_json, '$.assetKind') = 'visual_handoff'
                 OR json_extract(n.data_json, '$.asset_kind') = 'visual_handoff'
                 OR json_extract(n.data_json, '$.assetType') = 'visual_handoff'
                 OR json_extract(n.data_json, '$.asset_type') = 'visual_handoff'
              )
            ORDER BY n.sort_index ASC, n.node_id ASC
            LIMIT 1
            """,
            (episode_id, normalized_prompt_node_id),
        ).fetchone()
    return _row_node(row, detail=detail) if row is not None else {}


def _fetch_canvas_node_source_ref_consumer_ids(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    source_node_ids: set[str],
    ref_kinds: set[str] | None = None,
) -> set[str]:
    normalized_sources = sorted({str(node_id or "").strip() for node_id in source_node_ids if str(node_id or "").strip()})
    if not normalized_sources:
        return set()
    normalized_ref_kinds = sorted({str(kind or "").strip() for kind in ref_kinds or set() if str(kind or "").strip()})
    result: set[str] = set()
    for start in range(0, len(normalized_sources), 800):
        chunk = normalized_sources[start : start + 800]
        source_placeholders = ",".join("?" for _ in chunk)
        params: list[Any] = [episode_id, *chunk]
        kind_clause = ""
        if normalized_ref_kinds:
            kind_placeholders = ",".join("?" for _ in normalized_ref_kinds)
            kind_clause = f" AND ref_kind IN ({kind_placeholders})"
            params.extend(normalized_ref_kinds)
        rows = conn.execute(
            f"""
            SELECT DISTINCT target_node_id
            FROM canvas_node_source_refs
            WHERE episode_id = ?
              AND source_node_id IN ({source_placeholders})
              {kind_clause}
            ORDER BY target_node_id ASC
            """,
            tuple(params),
        ).fetchall()
        result.update(str(row["target_node_id"] or "").strip() for row in rows if str(row["target_node_id"] or "").strip())
    return result


def _fetch_canvas_node_rows(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    node_ids: set[str],
) -> list[sqlite3.Row]:
    normalized_ids = sorted({str(node_id or "").strip() for node_id in node_ids if str(node_id or "").strip()})
    if not normalized_ids:
        return []
    rows: list[sqlite3.Row] = []
    for start in range(0, len(normalized_ids), 800):
        chunk = normalized_ids[start : start + 800]
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(
            conn.execute(
                f"""
                SELECT node_id, node_type, route_id, segment_id, work_chain_id,
                       position_json, status, data_json, node_json, summary_json
                FROM canvas_nodes
                WHERE episode_id = ? AND node_id IN ({placeholders})
                ORDER BY sort_index ASC, node_id ASC
                """,
                (episode_id, *chunk),
            ).fetchall()
        )
    return rows


def _fetch_canvas_input_link_consumer_node_ids(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    source_node_ids: set[str],
) -> set[str]:
    normalized_sources = {str(node_id or "").strip() for node_id in source_node_ids if str(node_id or "").strip()}
    if not normalized_sources:
        return set()
    result: set[str] = set()
    result.update(
        _fetch_canvas_node_source_ref_consumer_ids(
            conn,
            episode_id=episode_id,
            source_node_ids=normalized_sources,
        )
    )
    return result


def _fetch_canvas_result_consumer_node_ids(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    source_node_ids: set[str],
) -> set[str]:
    normalized_sources = {str(node_id or "").strip() for node_id in source_node_ids if str(node_id or "").strip()}
    if not normalized_sources:
        return set()
    return _fetch_canvas_node_source_ref_consumer_ids(
        conn,
        episode_id=episode_id,
        source_node_ids=normalized_sources,
        ref_kinds={"result", "source", "task"},
    )


def _fetch_canvas_edges_touching_nodes(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    node_ids: set[str],
) -> list[sqlite3.Row]:
    normalized_ids = sorted({str(node_id or "").strip() for node_id in node_ids if str(node_id or "").strip()})
    if not normalized_ids:
        return []
    rows: list[sqlite3.Row] = []
    for start in range(0, len(normalized_ids), 400):
        chunk = normalized_ids[start : start + 400]
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(
            conn.execute(
                f"""
                SELECT edge_id, sort_index, source_node_id, target_node_id,
                       source_handle, target_handle, edge_data_json, edge_json
                FROM canvas_edges
                WHERE episode_id = ?
                  AND (source_node_id IN ({placeholders}) OR target_node_id IN ({placeholders}))
                ORDER BY sort_index ASC, edge_id ASC
                """,
                (episode_id, *chunk, *chunk),
            ).fetchall()
        )
    return rows


def _build_canvas_workflow_projection_from_node_ids(
    conn: sqlite3.Connection,
    *,
    document: sqlite3.Row,
    episode_id: str,
    node_ids: set[str],
    edge_rows_by_id: dict[str, sqlite3.Row],
    detail: str,
) -> dict[str, Any]:
    node_rows = _fetch_canvas_node_rows(conn, episode_id=episode_id, node_ids=node_ids)
    nodes = [_row_node(row, detail=detail) for row in node_rows]
    edges = [
        _row_edge(row)
        for row in sorted(
            edge_rows_by_id.values(),
            key=lambda item: (int(item["sort_index"] or 0), str(item["edge_id"] or "")),
        )
    ]
    route_ids: set[str] = set()
    work_chain_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        route_ids.update(_node_route_ids(node))
        work_chain_ids.update(_node_work_chain_ids(node))
    for edge in edges:
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        route_id = str(data.get("routeId") or data.get("route_id") or "").strip()
        work_chain_id = str(data.get("workChainId") or data.get("work_chain_id") or "").strip()
        if route_id:
            route_ids.add(route_id)
        if work_chain_id:
            work_chain_ids.add(work_chain_id)

    route_rows: list[sqlite3.Row] = []
    if route_ids:
        placeholders = ",".join("?" for _ in route_ids)
        route_rows = conn.execute(
            f"""
            SELECT route_json, summary_json
            FROM canvas_routes
            WHERE episode_id = ? AND route_id IN ({placeholders})
            ORDER BY sort_index ASC, route_id ASC
            """,
            (episode_id, *sorted(route_ids)),
        ).fetchall()
    work_chain_rows: list[sqlite3.Row] = []
    if work_chain_ids:
        placeholders = ",".join("?" for _ in work_chain_ids)
        work_chain_rows = conn.execute(
            f"""
            SELECT work_chain_json, summary_json
            FROM canvas_work_chains
            WHERE episode_id = ? AND work_chain_id IN ({placeholders})
            ORDER BY sort_index ASC, work_chain_id ASC
            """,
            (episode_id, *sorted(work_chain_ids)),
        ).fetchall()

    document_state = _json_loads(document["state_json"], {})
    workflow = {
        "episodeId": episode_id,
        "schemaVersion": int(document["schema_version"] or 4),
        "version": int(document["revision"] or 0),
        "viewport": _json_loads(document["viewport_json"], {"x": 0, "y": 0, "zoom": 0.82}),
        "routes": [_row_route(row, detail=detail) for row in route_rows],
        "nodes": nodes,
        "edges": edges,
        "workChains": [_row_work_chain(row, detail=detail) for row in work_chain_rows],
        "state": copy.deepcopy(document_state if isinstance(document_state, dict) else {}),
    }
    workflow.update(_canvas_document_extras_payload(document))
    return workflow


def read_canvas_task_context_v4(
    project_id: str,
    episode_id: str,
    card_id: str,
    *,
    detail: str = "full",
    include_route: bool = True,
    include_work_chain: bool = True,
    include_adjacent_storyboard: bool = True,
    include_input_sources: bool = True,
    include_input_consumers: bool = False,
    consumer_source_node_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    extra_node_ids: list[str] | set[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    node_id = str(card_id or "").strip()
    if not node_id:
        raise ValueError("缺少节点ID")
    detail = "summary" if str(detail or "").strip().lower() == "summary" else "full"
    with _canvas_snapshot_connection(project_id) as conn:
        document = _canvas_document_row(conn, episode_id)
        if document is None:
            raise FileNotFoundError("画布不存在")
        target_row = conn.execute(
            """
            SELECT node_id, sort_index, node_type, route_id, segment_id, work_chain_id,
                   position_json, status, data_json, node_json, summary_json
            FROM canvas_nodes
            WHERE episode_id = ? AND node_id = ?
            """,
            (episode_id, node_id),
        ).fetchone()
        if target_row is None:
            raise FileNotFoundError("节点不存在")

        document_extras = _canvas_document_extras_payload(document)
        target_node = _row_node(target_row, detail=detail)
        node_ids: set[str] = {node_id}
        edge_anchor_node_ids: set[str] = {node_id}
        target_route_ids = _node_route_ids(target_node)
        target_work_chain_ids = _node_work_chain_ids(target_node)
        target_sort_index = int(target_row["sort_index"] or 0)

        if include_adjacent_storyboard and str(target_row["node_type"] or "").strip() == "prompt.storyboard":
            scope_parts: list[str] = []
            scope_params: list[Any] = []
            if target_route_ids:
                placeholders = ",".join("?" for _ in target_route_ids)
                scope_parts.append(f"route_id IN ({placeholders})")
                scope_params.extend(sorted(target_route_ids))
            if target_work_chain_ids:
                placeholders = ",".join("?" for _ in target_work_chain_ids)
                scope_parts.append(f"work_chain_id IN ({placeholders})")
                scope_params.extend(sorted(target_work_chain_ids))
            scope_clause = f" AND ({' OR '.join(scope_parts)})" if scope_parts else ""
            for operator, sort_direction in (("<", "DESC"), (">", "ASC")):
                adjacent_row = conn.execute(
                    f"""
                    SELECT node_id
                    FROM canvas_nodes
                    WHERE episode_id = ?
                      AND node_type = ?
                      AND sort_index {operator} ?
                      {scope_clause}
                    ORDER BY sort_index {sort_direction}, node_id {sort_direction}
                    LIMIT 1
                    """,
                    (episode_id, "prompt.storyboard", target_sort_index, *scope_params),
                ).fetchone()
                adjacent_node_id = str(adjacent_row["node_id"] or "").strip() if adjacent_row is not None else ""
                if adjacent_node_id:
                    node_ids.add(adjacent_node_id)
        if extra_node_ids:
            explicit_extra_node_ids = {
                str(item or "").strip()
                for item in extra_node_ids
                if str(item or "").strip()
            }
            node_ids.update(explicit_extra_node_ids)
            edge_anchor_node_ids.update(explicit_extra_node_ids)

        where_parts: list[str] = []
        params: list[Any] = [episode_id]
        if include_route and target_route_ids:
            placeholders = ",".join("?" for _ in target_route_ids)
            where_parts.append(f"route_id IN ({placeholders})")
            params.extend(sorted(target_route_ids))
        if include_work_chain and target_work_chain_ids:
            placeholders = ",".join("?" for _ in target_work_chain_ids)
            where_parts.append(f"work_chain_id IN ({placeholders})")
            params.extend(sorted(target_work_chain_ids))
        if where_parts:
            rows = conn.execute(
                f"""
                SELECT node_id
                FROM canvas_nodes
                WHERE episode_id = ? AND ({" OR ".join(where_parts)})
                """,
                tuple(params),
            ).fetchall()
            route_or_chain_node_ids = {
                str(row["node_id"] or "").strip()
                for row in rows
                if str(row["node_id"] or "").strip()
            }
            node_ids.update(route_or_chain_node_ids)
            edge_anchor_node_ids.update(route_or_chain_node_ids)

        edge_rows_by_id: dict[str, sqlite3.Row] = {}
        for row in _fetch_canvas_edges_touching_nodes(conn, episode_id=episode_id, node_ids=edge_anchor_node_ids):
            edge_id = str(row["edge_id"] or "").strip()
            if edge_id:
                edge_rows_by_id[edge_id] = row
            source = str(row["source_node_id"] or "").strip()
            target = str(row["target_node_id"] or "").strip()
            if source:
                node_ids.add(source)
            if target:
                node_ids.add(target)

        node_rows = _fetch_canvas_node_rows(conn, episode_id=episode_id, node_ids=node_ids)
        nodes = [_row_node(row, detail=detail) for row in node_rows]
        if include_input_sources:
            source_scan_node_ids = set(edge_anchor_node_ids)
            for _ in range(2):
                linked_node_ids: set[str] = set()
                for node in nodes:
                    current_node_id = str(node.get("id") or "").strip() if isinstance(node, dict) else ""
                    if current_node_id not in source_scan_node_ids:
                        continue
                    data = node.get("data") if isinstance(node.get("data"), dict) else {}
                    linked_node_ids.update(_input_link_source_node_ids(data.get("inputLinks")))
                new_node_ids = linked_node_ids - node_ids
                if not new_node_ids:
                    break
                node_ids.update(new_node_ids)
                for row in _fetch_canvas_edges_touching_nodes(conn, episode_id=episode_id, node_ids=new_node_ids):
                    edge_id = str(row["edge_id"] or "").strip()
                    source = str(row["source_node_id"] or "").strip()
                    target = str(row["target_node_id"] or "").strip()
                    if edge_id and source in node_ids and target in node_ids:
                        edge_rows_by_id[edge_id] = row
                node_rows = _fetch_canvas_node_rows(conn, episode_id=episode_id, node_ids=node_ids)
                nodes = [_row_node(row, detail=detail) for row in node_rows]
                source_scan_node_ids = new_node_ids

        if include_input_consumers:
            consumer_source_ids = {
                str(item or "").strip()
                for item in (
                    consumer_source_node_ids
                    if consumer_source_node_ids is not None
                    else edge_anchor_node_ids
                )
                if str(item or "").strip()
            }
            seen_consumer_source_ids: set[str] = set()
            for _ in range(2):
                current_consumer_source_ids = consumer_source_ids - seen_consumer_source_ids
                if not current_consumer_source_ids:
                    break
                seen_consumer_source_ids.update(current_consumer_source_ids)
                consumer_ids = _fetch_canvas_input_link_consumer_node_ids(
                    conn,
                    episode_id=episode_id,
                    source_node_ids=current_consumer_source_ids,
                )
                consumer_ids.update(
                    _fetch_canvas_result_consumer_node_ids(
                        conn,
                        episode_id=episode_id,
                        source_node_ids=current_consumer_source_ids,
                    )
                )
                next_consumer_source_ids = consumer_ids - seen_consumer_source_ids
                new_consumer_ids = consumer_ids - node_ids
                if not new_consumer_ids and not next_consumer_source_ids:
                    break
                if new_consumer_ids:
                    node_ids.update(new_consumer_ids)
                    for row in _fetch_canvas_edges_touching_nodes(conn, episode_id=episode_id, node_ids=new_consumer_ids):
                        edge_id = str(row["edge_id"] or "").strip()
                        source = str(row["source_node_id"] or "").strip()
                        target = str(row["target_node_id"] or "").strip()
                        if edge_id and source in node_ids and target in node_ids:
                            edge_rows_by_id[edge_id] = row
                consumer_source_ids = next_consumer_source_ids

        return _build_canvas_workflow_projection_from_node_ids(
            conn,
            document=document,
            episode_id=episode_id,
            node_ids=node_ids,
            edge_rows_by_id=edge_rows_by_id,
            detail=detail,
        )


def read_workflow_card_neighborhood_v4(
    project_id: str,
    episode_id: str,
    card_id: str,
    *,
    detail: str = "full",
) -> dict[str, Any]:
    workflow = read_canvas_task_context_v4(
        project_id,
        episode_id,
        card_id,
        detail=detail,
    )
    return workflow


def read_canvas_node_signatures_v4(
    project_id: str,
    episode_id: str,
    node_ids: list[str] | set[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    normalized_ids = sorted(
        {
            str(node_id or "").strip()
            for node_id in (node_ids if isinstance(node_ids, (list, set, tuple)) else [])
            if str(node_id or "").strip()
        }
    )
    if not normalized_ids or not episode_canvas_exists(project_id, episode_id):
        return []
    rows: list[sqlite3.Row] = []
    with _canvas_connection(project_id) as conn:
        for start in range(0, len(normalized_ids), 400):
            chunk = normalized_ids[start : start + 400]
            placeholders = ",".join("?" for _ in chunk)
            rows.extend(
                conn.execute(
                    f"""
                    SELECT node_id, node_type, route_id, segment_id, work_chain_id,
                           data_json, node_json
                    FROM canvas_nodes
                    WHERE episode_id = ? AND node_id IN ({placeholders})
                    ORDER BY node_id ASC
                    """,
                    (episode_id, *chunk),
                ).fetchall()
            )
    rows = sorted(rows, key=lambda row: str(row["node_id"] or ""))
    return [
        {
            "id": str(row["node_id"] or "").strip(),
            "type": str(row["node_type"] or "").strip(),
            "routeId": str(row["route_id"] or "").strip(),
            "segmentId": str(row["segment_id"] or "").strip(),
            "workChainId": str(row["work_chain_id"] or "").strip(),
            "dataHash": _canvas_signature_hash_from_json(row["data_json"]),
            "nodeHash": _canvas_signature_hash_from_json(row["node_json"]),
        }
        for row in rows
    ]


def read_canvas_reference_versions_by_ids_v4(
    project_id: str,
    episode_id: str,
    reference_ids: list[str] | set[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    normalized_ids = sorted(
        {
            str(reference_id or "").strip()
            for reference_id in reference_ids
            if str(reference_id or "").strip()
        }
    )
    if not normalized_ids or not episode_canvas_exists(project_id, episode_id):
        return []
    matched: list[dict[str, Any]] = []
    seen_versions: set[tuple[str, str]] = set()
    with _canvas_connection(project_id) as conn:
        rows: list[sqlite3.Row] = []
        for start in range(0, len(normalized_ids), 800):
            chunk = normalized_ids[start : start + 800]
            placeholders = ",".join("?" for _ in chunk)
            rows.extend(
                conn.execute(
                    f"""
                    SELECT DISTINCT v.node_id, v.version_id, v.active, v.version_json, v.sort_index
                    FROM canvas_version_identity_refs AS r
                    JOIN canvas_versions AS v
                      ON v.episode_id = r.episode_id
                     AND v.node_id = r.node_id
                     AND v.version_id = r.version_id
                    WHERE r.episode_id = ?
                      AND r.identity IN ({placeholders})
                    ORDER BY v.active DESC, v.node_id ASC, v.sort_index ASC, v.version_id ASC
                    """,
                    (episode_id, *chunk),
                ).fetchall()
            )
    for row in rows:
        version = _row_version(row)
        key = (str(version.get("nodeId") or ""), str(version.get("id") or ""))
        if key in seen_versions:
            continue
        seen_versions.add(key)
        matched.append(version)
    return matched


_CANVAS_CHANGES_MAX_OPERATIONS = 128
_CANVAS_CHANGES_MAX_BYTES = 1024 * 1024


def list_canvas_changes_v4(project_id: str, episode_id: str, since_revision: int | str | None = 0) -> dict[str, Any]:
    try:
        since = max(0, int(since_revision or 0))
    except (TypeError, ValueError):
        since = 0
    with _canvas_snapshot_connection(project_id) as conn:
        document = _canvas_document_row(conn, episode_id)
        if document is None:
            return {
                "success": True,
                "episodeId": episode_id,
                "currentRevision": 0,
                "changes": [],
            }
        current_revision = int(document["revision"] or 0)

        def snapshot_required(reason: str) -> dict[str, Any]:
            return {
                "success": True,
                "episodeId": episode_id,
                "currentRevision": current_revision,
                "snapshotRequired": True,
                "snapshotRequiredReason": reason,
                "changes": [],
                "records": _canvas_records_for_ids_in_conn(
                    conn,
                    episode_id=episode_id,
                    ids={
                        "nodes": set(),
                        "edges": set(),
                        "routes": set(),
                        "workChains": set(),
                        "versionRefs": set(),
                        "tasks": set(),
                        "projections": set(),
                    },
                    detail="summary",
                ),
            }

        oldest_op_row = conn.execute(
            "SELECT MIN(revision) AS oldest_revision FROM canvas_ops WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        oldest_revision = (
            int(oldest_op_row["oldest_revision"] or 0)
            if oldest_op_row is not None
            else 0
        )
        if oldest_revision and since < oldest_revision - 1:
            return snapshot_required("op_log_trimmed")
        rows = conn.execute(
            """
            SELECT tx_id, seq, op_type, base_revision, revision, payload_json, created_at
            FROM canvas_ops
            WHERE episode_id = ? AND revision > ?
            ORDER BY revision ASC, seq ASC, id ASC
            LIMIT ?
            """,
            (episode_id, since, _CANVAS_CHANGES_MAX_OPERATIONS + 1),
        ).fetchall()
        if len(rows) > _CANVAS_CHANGES_MAX_OPERATIONS:
            return snapshot_required("op_count_limit")
        if sum(len(str(row["payload_json"] or "").encode("utf-8")) for row in rows) > _CANVAS_CHANGES_MAX_BYTES:
            return snapshot_required("op_bytes_limit")
        if current_revision > since and not rows:
            return snapshot_required("missing_ops")
        if rows:
            last_seen_revision = since
            for row in rows:
                row_base_revision = int(row["base_revision"] or 0)
                row_revision = int(row["revision"] or 0)
                if row_revision <= last_seen_revision:
                    continue
                if row_base_revision > last_seen_revision or row_revision > last_seen_revision + 1:
                    return snapshot_required("op_log_gap")
                last_seen_revision = row_revision
            if last_seen_revision < current_revision:
                return snapshot_required("op_log_incomplete")
        changed_record_ids: dict[str, set[Any]] = {
            "nodes": set(),
            "edges": set(),
            "routes": set(),
            "workChains": set(),
            "versionRefs": set(),
            "tasks": set(),
            "projections": set(),
        }
        for row in rows:
            payload = _json_loads(row["payload_json"], {})
            if isinstance(payload, dict):
                _merge_canvas_record_ids(
                    changed_record_ids,
                    _canvas_record_ids_from_payload(payload),
                )
        records = _canvas_records_for_ids_in_conn(
            conn,
            episode_id=episode_id,
            ids=changed_record_ids,
            detail="full",
        )
        result = {
            "success": True,
            "episodeId": episode_id,
            "currentRevision": current_revision,
            "snapshotRequired": False,
            "changes": [_canvas_change_row(row) for row in rows],
            "records": records,
        }
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > _CANVAS_CHANGES_MAX_BYTES:
            return snapshot_required("record_bytes_limit")
        return result


def get_canvas_snapshot_v4(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = payload if isinstance(payload, dict) else {}
    detail = "summary" if str(params.get("detail") or "").strip().lower() == "summary" else "full"
    include_versions = params.get("includeVersions", params.get("include_versions", detail == "full")) is not False
    include_tasks = params.get("includeTasks", params.get("include_tasks", detail == "full")) is not False
    include_projections = bool(params.get("includeProjections", params.get("include_projections", False)))
    with _canvas_snapshot_connection(project_id) as conn:
        document = _canvas_document_row(conn, episode_id)
        document_payload = _empty_canvas_document_payload(episode_id)
        if document is None:
            records = {
                "nodes": [],
                "edges": [],
                "routes": [],
                "workChains": [],
                "versions": [],
                "tasks": [],
                "projections": [],
            }
        else:
            node_rows = conn.execute(
                """
                SELECT node_id, node_type, route_id, segment_id, work_chain_id,
                       position_json, status, data_json, node_json, summary_json
                FROM canvas_nodes
                WHERE episode_id = ?
                ORDER BY sort_index ASC, node_id ASC
                """,
                (episode_id,),
            ).fetchall()
            document_payload = _canvas_document_payload(
                document,
                episode_id,
                has_nodes=bool(node_rows),
            )
            edge_rows = conn.execute(
                """
                SELECT edge_json
                FROM canvas_edges
                WHERE episode_id = ?
                ORDER BY sort_index ASC, edge_id ASC
                """,
                (episode_id,),
            ).fetchall()
            route_rows = conn.execute(
                """
                SELECT route_json, summary_json
                FROM canvas_routes
                WHERE episode_id = ?
                ORDER BY sort_index ASC, route_id ASC
                """,
                (episode_id,),
            ).fetchall()
            work_chain_rows = conn.execute(
                """
                SELECT work_chain_json, summary_json
                FROM canvas_work_chains
                WHERE episode_id = ?
                ORDER BY sort_index ASC, work_chain_id ASC
                """,
                (episode_id,),
            ).fetchall()
            version_rows = (
                conn.execute(
                    """
                    SELECT node_id, version_id, active, version_json
                    FROM canvas_versions
                    WHERE episode_id = ?
                    ORDER BY node_id ASC, sort_index ASC, version_id ASC
                    """,
                    (episode_id,),
                ).fetchall()
                if include_versions
                else []
            )
            task_rows = (
                conn.execute(
                    """
                    SELECT task_json
                    FROM canvas_tasks
                    WHERE episode_id = ?
                    ORDER BY updated_at ASC, task_id ASC
                    """,
                    (episode_id,),
                ).fetchall()
                if include_tasks
                else []
            )
            projection_rows = (
                conn.execute(
                    """
                    SELECT cache_key, cache_type, payload_json, revision, updated_at
                    FROM canvas_projection_cache
                    WHERE episode_id = ?
                    ORDER BY cache_type ASC, cache_key ASC
                    """,
                    (episode_id,),
                ).fetchall()
                if include_projections
                else []
            )
            records = {
                "nodes": [_row_node(row, detail=detail) for row in node_rows],
                "edges": [
                    edge
                    for edge in (_json_loads(row["edge_json"], {}) for row in edge_rows)
                    if isinstance(edge, dict)
                ],
                "routes": [_row_route(row, detail=detail) for row in route_rows],
                "workChains": [_row_work_chain(row, detail=detail) for row in work_chain_rows],
                "versions": [_row_version(row) for row in version_rows],
                "tasks": [
                    task
                    for task in (_json_loads(row["task_json"], {}) for row in task_rows)
                    if isinstance(task, dict)
                ],
                "projections": [
                    {
                        "id": row["cache_key"],
                        "key": row["cache_key"],
                        "type": row["cache_type"],
                        "payload": _json_loads(row["payload_json"], {}),
                        "revision": int(row["revision"] or 0),
                        "updatedAt": row["updated_at"],
                    }
                    for row in projection_rows
                ],
            }
    if not records["nodes"]:
        # A missing graph does not mean the committed episode source is missing.
        # Resolve after closing the SQLite snapshot; state lookup also reads JSON.
        from .workflow_projection import _workflow_state
        document_payload["state"] = _workflow_state(
            project_id, episode_id, {**document_payload, "nodes": []}, "loaded",
        )
    return {
        "success": True,
        "episodeId": episode_id,
        "schemaVersion": 4,
        "revision": int(document_payload.get("revision") or 0),
        "currentRevision": int(document_payload.get("currentRevision") or 0),
        "detail": detail,
        "document": document_payload,
        "records": records,
    }


def get_canvas_records_v4(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = payload if isinstance(payload, dict) else {}
    ids = params.get("ids") if isinstance(params.get("ids"), dict) else {}
    detail = "summary" if str(params.get("detail") or "").strip().lower() == "summary" else "full"

    def id_list(*keys: str) -> list[str]:
        rows: list[Any] = []
        for key in keys:
            source = ids.get(key) if isinstance(ids, dict) and key in ids else params.get(key)
            if isinstance(source, list):
                rows.extend(source)
            elif source is not None:
                rows.append(source)
        return [str(item or "").strip() for item in rows if str(item or "").strip()]

    def version_ref_list(*keys: str) -> list[tuple[str, str]]:
        rows: list[Any] = []
        for key in keys:
            source = ids.get(key) if isinstance(ids, dict) and key in ids else params.get(key)
            if isinstance(source, list):
                rows.extend(source)
            elif source is not None:
                rows.append(source)
        refs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            ref = _canvas_version_ref_from_value(row)
            if ref is None or ref in seen:
                continue
            seen.add(ref)
            refs.append(ref)
        return refs

    node_ids = id_list("nodeIds", "node_ids", "nodes")
    edge_ids = id_list("edgeIds", "edge_ids", "edges")
    route_ids = id_list("routeIds", "route_ids", "routes")
    work_chain_ids = id_list("workChainIds", "work_chain_ids", "workChains", "work_chains")
    version_refs = version_ref_list("versionRefs", "version_refs", "versions")
    task_ids = id_list("taskIds", "task_ids", "tasks")
    projection_keys = id_list("projectionKeys", "projection_keys", "projections")

    with _canvas_snapshot_connection(project_id) as conn:
        document = _canvas_document_row(conn, episode_id)
        if document is None:
            raise FileNotFoundError("画布不存在")
        current_revision = int(document["revision"] or 0)
        records = _canvas_records_for_ids_in_conn(
            conn,
            episode_id=episode_id,
            ids={
                "nodes": set(node_ids),
                "edges": set(edge_ids),
                "routes": set(route_ids),
                "workChains": set(work_chain_ids),
                "versionRefs": set(version_refs),
                "tasks": set(task_ids),
                "projections": set(projection_keys),
            },
            detail=detail,
        )

    return {
        "success": True,
        "episodeId": episode_id,
        "currentRevision": current_revision,
        "detail": detail,
        "records": records,
    }


def get_canvas_scope_records_v4(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = payload if isinstance(payload, dict) else {}
    detail = "summary" if str(params.get("detail") or "").strip().lower() == "summary" else "full"
    selected_route_ids = _record_id_set(params.get("routeIds") or params.get("route_ids"))
    selected_work_chain_ids = _record_id_set(
        params.get("workChainIds") or params.get("work_chain_ids") or params.get("workChains")
    )
    delete_orphan_work_chains = params.get("deleteOrphanWorkChains", params.get("delete_orphan_work_chains", True)) is not False

    def chain_route_ids(chain: dict[str, Any]) -> set[str]:
        route_ids: set[str] = set()
        for key in ("routeIds", "route_ids"):
            values = chain.get(key)
            if not isinstance(values, list):
                continue
            route_ids.update(str(value or "").strip() for value in values if str(value or "").strip())
        return route_ids

    with _canvas_snapshot_connection(project_id) as conn:
        document = _canvas_document_row(conn, episode_id)
        if document is None:
            raise FileNotFoundError("画布不存在")
        current_revision = int(document["revision"] or 0)
        route_rows = conn.execute(
            """
            SELECT route_json, summary_json
            FROM canvas_routes
            WHERE episode_id = ?
            ORDER BY sort_index ASC, route_id ASC
            """,
            (episode_id,),
        ).fetchall()
        work_chain_rows = conn.execute(
            """
            SELECT work_chain_json, summary_json
            FROM canvas_work_chains
            WHERE episode_id = ?
            ORDER BY sort_index ASC, work_chain_id ASC
            """,
            (episode_id,),
        ).fetchall()
        all_routes = [_row_route(row, detail="full") for row in route_rows]
        all_work_chains = [_row_work_chain(row, detail="full") for row in work_chain_rows]

        for route in all_routes:
            if not isinstance(route, dict):
                continue
            route_id = str(route.get("id") or "").strip()
            work_chain_id = str(route.get("workChainId") or route.get("work_chain_id") or "").strip()
            if work_chain_id and work_chain_id in selected_work_chain_ids and route_id:
                selected_route_ids.add(route_id)
        for chain in all_work_chains:
            if not isinstance(chain, dict):
                continue
            chain_id = str(chain.get("id") or "").strip()
            route_ids = chain_route_ids(chain)
            if chain_id in selected_work_chain_ids:
                selected_route_ids.update(route_ids)

        if delete_orphan_work_chains:
            for chain in all_work_chains:
                if not isinstance(chain, dict):
                    continue
                chain_id = str(chain.get("id") or "").strip()
                if not chain_id or chain_id in selected_work_chain_ids:
                    continue
                chain_routes = chain_route_ids(chain)
                if not chain_routes:
                    chain_routes = {
                        str(route.get("id") or "").strip()
                        for route in all_routes
                        if isinstance(route, dict)
                        and str(route.get("workChainId") or route.get("work_chain_id") or "").strip() == chain_id
                        and str(route.get("id") or "").strip()
                    }
                if chain_routes and not (chain_routes - selected_route_ids):
                    selected_work_chain_ids.add(chain_id)
        selected_routes = [
            route
            for route in all_routes
            if isinstance(route, dict)
            and (
                str(route.get("id") or "").strip() in selected_route_ids
                or str(route.get("workChainId") or route.get("work_chain_id") or "").strip() in selected_work_chain_ids
            )
        ]
        selected_work_chains = [
            chain
            for chain in all_work_chains
            if isinstance(chain, dict)
            and str(chain.get("id") or "").strip() in selected_work_chain_ids
        ]

        where_parts: list[str] = []
        query_params: list[Any] = [episode_id]
        if selected_route_ids:
            placeholders = ",".join("?" for _ in selected_route_ids)
            where_parts.append(f"route_id IN ({placeholders})")
            query_params.extend(sorted(selected_route_ids))
        if selected_work_chain_ids:
            placeholders = ",".join("?" for _ in selected_work_chain_ids)
            where_parts.append(f"work_chain_id IN ({placeholders})")
            query_params.extend(sorted(selected_work_chain_ids))
        node_rows: list[sqlite3.Row] = []
        if where_parts:
            node_rows = conn.execute(
                f"""
                SELECT node_id, node_type, route_id, segment_id, work_chain_id,
                       position_json, status, data_json, node_json, summary_json
                FROM canvas_nodes
                WHERE episode_id = ? AND ({" OR ".join(where_parts)})
                ORDER BY sort_index ASC, node_id ASC
                """,
                tuple(query_params),
            ).fetchall()
        nodes = [_row_node(row, detail=detail) for row in node_rows]
        node_ids = {
            str(node.get("id") or "").strip()
            for node in nodes
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        edge_rows = _fetch_canvas_edges_touching_nodes(conn, episode_id=episode_id, node_ids=node_ids)
        edges = [_row_edge(row) for row in edge_rows]

    return {
        "success": True,
        "episodeId": episode_id,
        "currentRevision": current_revision,
        "detail": detail,
        "routeIds": sorted(selected_route_ids),
        "workChainIds": sorted(selected_work_chain_ids),
        "records": {
            "nodes": nodes,
            "edges": edges,
            "routes": selected_routes,
            "workChains": selected_work_chains,
        },
    }


def read_canvas_task_records_v4(project_id: str, episode_id: str) -> list[dict[str, Any]]:
    if not episode_canvas_exists(project_id, episode_id):
        return []
    with _canvas_connection(project_id) as conn:
        rows = conn.execute(
            """
            SELECT task_json
            FROM canvas_tasks
            WHERE episode_id = ?
            ORDER BY updated_at ASC, task_id ASC
            """,
            (episode_id,),
        ).fetchall()
    tasks: list[dict[str, Any]] = []
    for row in rows:
        task = _json_loads(row["task_json"], {})
        if isinstance(task, dict):
            tasks.append(task)
    return tasks


def _read_card_results_in_conn(
    conn: sqlite3.Connection,
    episode_id: str,
    card_id: str,
) -> list[dict[str, Any]]:
    node_id = str(card_id or "").strip()
    if not node_id:
        return []
    rows = conn.execute(
        """
        SELECT node_id, version_id, active, version_json
        FROM canvas_versions
        WHERE episode_id = ? AND node_id = ?
        ORDER BY sort_index ASC, version_id ASC
        """,
        (episode_id, node_id),
    ).fetchall()
    return [_row_version(row) for row in rows]


def read_card_results(project_id: str, episode_id: str, card_id: str) -> list[dict[str, Any]]:
    if not episode_canvas_exists(project_id, episode_id):
        return []
    with _canvas_connection(project_id) as conn:
        return _read_card_results_in_conn(conn, episode_id, card_id)


def read_episode_card_results(project_id: str, episode_id: str) -> list[dict[str, Any]]:
    if not episode_canvas_exists(project_id, episode_id):
        return []
    with _canvas_connection(project_id) as conn:
        rows = conn.execute(
            """
            SELECT node_id, version_id, active, version_json
            FROM canvas_versions
            WHERE episode_id = ?
            ORDER BY node_id ASC, sort_index ASC, version_id ASC
            """,
            (episode_id,),
        ).fetchall()
    return [_row_version(row) for row in rows]


def _read_canvas_projection_state_in_conn(
    conn: sqlite3.Connection,
    episode_id: str,
) -> CanvasProjectionState:
    previous_node_rows = conn.execute(
        """
                SELECT node_id, sort_index, node_type, route_id, segment_id,
                       work_chain_id, position_json, status, data_json, node_json
                FROM canvas_nodes
                WHERE episode_id = ?
                """,
        (episode_id,),
    ).fetchall()
    previous_edge_rows = conn.execute(
        """
                SELECT edge_id, sort_index, source_node_id, target_node_id,
                       source_handle, target_handle, edge_data_json, edge_json
                FROM canvas_edges
                WHERE episode_id = ?
                """,
        (episode_id,),
    ).fetchall()
    previous_route_rows = conn.execute(
        """
                SELECT route_id, sort_index, route_json
                FROM canvas_routes
                WHERE episode_id = ?
                """,
        (episode_id,),
    ).fetchall()
    previous_work_chain_rows = conn.execute(
        """
                SELECT work_chain_id, sort_index, work_chain_json
                FROM canvas_work_chains
                WHERE episode_id = ?
                """,
        (episode_id,),
    ).fetchall()
    previous_node_ids = {str(row["node_id"] or "") for row in previous_node_rows}
    previous_edge_ids = {str(row["edge_id"] or "") for row in previous_edge_rows}
    previous_route_ids = {str(row["route_id"] or "") for row in previous_route_rows}
    previous_work_chain_ids = {
        str(row["work_chain_id"] or "") for row in previous_work_chain_rows
    }
    previous_node_signatures = {
        str(row["node_id"] or ""): _json_signature(
            {
                "sortIndex": int(row["sort_index"] or 0),
                "type": str(row["node_type"] or ""),
                "routeId": str(row["route_id"] or ""),
                "segmentId": str(row["segment_id"] or ""),
                "workChainId": str(row["work_chain_id"] or ""),
                "position": _json_loads(row["position_json"], {}),
                "status": str(row["status"] or ""),
                "data": _json_loads(row["data_json"], {}),
                "node": _json_loads(row["node_json"], {}),
            }
        )
        for row in previous_node_rows
    }
    previous_edge_signatures = {
        str(row["edge_id"] or ""): _json_signature(
            {
                "sortIndex": int(row["sort_index"] or 0),
                "source": str(row["source_node_id"] or ""),
                "target": str(row["target_node_id"] or ""),
                "sourceHandle": str(row["source_handle"] or ""),
                "targetHandle": str(row["target_handle"] or ""),
                "data": _json_loads(row["edge_data_json"], {}),
                "edge": _json_loads(row["edge_json"], {}),
            }
        )
        for row in previous_edge_rows
    }
    previous_route_signatures = {
        str(row["route_id"] or ""): _json_signature(
            {
                "sortIndex": int(row["sort_index"] or 0),
                "route": _json_loads(row["route_json"], {}),
            }
        )
        for row in previous_route_rows
    }
    previous_work_chain_signatures = {
        str(row["work_chain_id"] or ""): _json_signature(
            {
                "sortIndex": int(row["sort_index"] or 0),
                "workChain": _json_loads(row["work_chain_json"], {}),
            }
        )
        for row in previous_work_chain_rows
    }
    previous_version_refs = [
        {
            "nodeId": str(row["node_id"] or ""),
            "versionId": str(row["version_id"] or ""),
        }
        for row in conn.execute(
            "SELECT node_id, version_id FROM canvas_versions WHERE episode_id = ?",
            (episode_id,),
        ).fetchall()
    ]
    previous_task_refs = [
        {
            "nodeId": str(row["node_id"] or ""),
            "taskId": str(row["task_id"] or ""),
        }
        for row in conn.execute(
            "SELECT node_id, task_id FROM canvas_tasks WHERE episode_id = ?",
            (episode_id,),
        ).fetchall()
    ]
    return CanvasProjectionState(
        node_ids=previous_node_ids,
        edge_ids=previous_edge_ids,
        route_ids=previous_route_ids,
        work_chain_ids=previous_work_chain_ids,
        node_signatures=previous_node_signatures,
        edge_signatures=previous_edge_signatures,
        route_signatures=previous_route_signatures,
        work_chain_signatures=previous_work_chain_signatures,
        version_refs=previous_version_refs,
        task_refs=previous_task_refs,
    )
