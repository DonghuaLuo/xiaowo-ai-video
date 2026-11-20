# -*- coding: utf-8 -*-
"""画布目录、文档附加信息、任务记录及生产状态的事务写入。"""
from __future__ import annotations

import copy
import sqlite3
import uuid
from .canvas_store_database import (
    _SQLITE_WRITE_LOCK,
    _canvas_connection,
    _canvas_document_row,
    _canvas_mutation_document_in_conn,
    _ensure_canvas_document_in_conn,
    canvas_db_path,
)
from .canvas_store_records import (
    _canvas_document_extras_payload,
    _json_dumps,
    _json_loads,
    _json_signature,
    _merge_canvas_document_extras,
    _record_ref,
    _records_payload,
    _route_summary_record,
    _work_chain_summary_record,
    normalize_canvas_changed_resources,
)
from .canvas_store_rows import (
    _record_op,
    _write_canvas_task_rows_in_conn,
)
from .perf_logging import (
    canvas_perf_elapsed_ms,
    canvas_perf_log,
    canvas_perf_start,
)
from .store_core import (
    _now,
)
from typing import (
    Any,
)


_CUSTOM_CANVAS_BASE_TITLE = "自定义画布"


def _canvas_catalog_row_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "canvasId": str(row["canvas_id"] or ""),
        "kind": str(row["canvas_kind"] or ""),
        "episodeId": str(row["episode_id"] or ""),
        "title": str(row["title"] or ""),
        "storageKey": str(row["storage_key"] or ""),
        "sortIndex": int(row["sort_index"] or 0),
        "archived": bool(row["archived"]),
        "createdAt": str(row["created_at"] or ""),
        "updatedAt": str(row["updated_at"] or ""),
    }


def _custom_canvas_catalog_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT catalog.canvas_id,
               catalog.canvas_kind,
               catalog.episode_id,
               catalog.title,
               catalog.storage_key,
               catalog.sort_index,
               catalog.archived,
               catalog.created_at,
               COALESCE(document.updated_at, catalog.updated_at) AS updated_at
        FROM canvas_catalog AS catalog
        LEFT JOIN canvas_documents AS document
            ON document.episode_id = catalog.storage_key
        WHERE catalog.canvas_kind = 'custom' AND catalog.archived = 0
        ORDER BY catalog.sort_index DESC,
                 COALESCE(document.updated_at, catalog.updated_at) DESC,
                 catalog.canvas_id DESC
        """
    ).fetchall()


def _unique_custom_canvas_title(conn: sqlite3.Connection, requested_title: str = "") -> str:
    base_title = str(requested_title or "").strip() or _CUSTOM_CANVAS_BASE_TITLE
    existing_titles = {
        str(row["title"] or "").strip()
        for row in _custom_canvas_catalog_rows(conn)
    }
    if base_title not in existing_titles:
        return base_title
    index = 2
    while True:
        candidate = f"{base_title} {index}"
        if candidate not in existing_titles:
            return candidate
        index += 1


def _new_custom_canvas_id(conn: sqlite3.Connection) -> str:
    for _attempt in range(12):
        canvas_id = f"cc_{uuid.uuid4().hex[:16]}"
        row = conn.execute(
            "SELECT 1 FROM canvas_catalog WHERE canvas_id = ? OR storage_key = ?",
            (canvas_id, canvas_id),
        ).fetchone()
        if row is None:
            return canvas_id
    raise RuntimeError("自定义画布 ID 生成失败")


def _ensure_custom_canvas_document_in_conn(
    conn: sqlite3.Connection,
    storage_key: str,
    *,
    now: str,
) -> None:
    if _canvas_document_row(conn, storage_key) is not None:
        return
    state = {
        "kind": "custom",
        "reason": "custom_canvas_created",
        "sourceReady": False,
        "workChainPlanReady": False,
        "workflowChainReady": True,
        "nextAction": "edit_custom_canvas",
    }
    conn.execute(
        """
        INSERT INTO canvas_documents (
            episode_id, schema_version, revision, viewport_json,
            routes_json, work_chains_json, state_json, extras_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            storage_key,
            4,
            0,
            _json_dumps({"x": 0, "y": 0, "zoom": 0.82}),
            _json_dumps([]),
            _json_dumps([]),
            _json_dumps(state),
            _json_dumps({"canvasKind": "custom", "autoWorkflowInitialized": False}),
            now,
        ),
    )


def list_project_custom_canvases_v4(project_id: str) -> dict[str, Any]:
    path = canvas_db_path(project_id)
    if not path.exists():
        return {"success": True, "customCanvases": []}
    with _canvas_connection(project_id) as conn:
        rows = _custom_canvas_catalog_rows(conn)
    return {
        "success": True,
        "customCanvases": [_canvas_catalog_row_payload(row) for row in rows],
    }


def create_custom_canvas_v4(
    project_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = payload if isinstance(payload, dict) else {}
    now = _now()
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            title = _unique_custom_canvas_title(conn, str(params.get("title") or ""))
            rows = _custom_canvas_catalog_rows(conn)
            sort_index = max([int(row["sort_index"] or 0) for row in rows], default=0) + 1
            canvas_id = _new_custom_canvas_id(conn)
            storage_key = canvas_id
            conn.execute(
                """
                INSERT INTO canvas_catalog (
                    canvas_id, canvas_kind, episode_id, title, storage_key,
                    sort_index, archived, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canvas_id,
                    "custom",
                    "",
                    title,
                    storage_key,
                    sort_index,
                    0,
                    now,
                    now,
                ),
            )
            _ensure_custom_canvas_document_in_conn(conn, storage_key, now=now)
            row = conn.execute(
                """
                SELECT canvas_id, canvas_kind, episode_id, title, storage_key,
                       sort_index, archived, created_at, updated_at
                FROM canvas_catalog
                WHERE canvas_id = ?
                """,
                (canvas_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("自定义画布创建失败")
            canvas = _canvas_catalog_row_payload(row)
    return {
        "success": True,
        "canvas": canvas,
        "projectChanged": True,
        "changedResources": ["canvas_catalog"],
    }


def rename_custom_canvas_v4(
    project_id: str,
    canvas_id: str,
    title: str,
) -> dict[str, Any]:
    normalized_canvas_id = str(canvas_id or "").strip()
    normalized_title = str(title or "").strip()
    if not normalized_canvas_id:
        raise ValueError("缺少 canvasId")
    if not normalized_title:
        raise ValueError("画布名称不能为空")
    now = _now()
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            row = conn.execute(
                """
                SELECT canvas_id, canvas_kind, episode_id, title, storage_key,
                       sort_index, archived, created_at, updated_at
                FROM canvas_catalog
                WHERE canvas_id = ? AND canvas_kind = 'custom' AND archived = 0
                """,
                (normalized_canvas_id,),
            ).fetchone()
            if row is None:
                raise ValueError("自定义画布不存在")
            conn.execute(
                "UPDATE canvas_catalog SET title = ?, updated_at = ? WHERE canvas_id = ?",
                (normalized_title, now, normalized_canvas_id),
            )
            updated = conn.execute(
                """
                SELECT canvas_id, canvas_kind, episode_id, title, storage_key,
                       sort_index, archived, created_at, updated_at
                FROM canvas_catalog
                WHERE canvas_id = ?
                """,
                (normalized_canvas_id,),
            ).fetchone()
            if updated is None:
                raise RuntimeError("自定义画布重命名失败")
            canvas = _canvas_catalog_row_payload(updated)
    return {
        "success": True,
        "canvas": canvas,
        "projectChanged": True,
        "changedResources": ["canvas_catalog"],
    }


def delete_custom_canvas_v4(project_id: str, canvas_id: str) -> dict[str, Any]:
    normalized_canvas_id = str(canvas_id or "").strip()
    if not normalized_canvas_id:
        raise ValueError("缺少 canvasId")
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            row = conn.execute(
                """
                SELECT storage_key, title
                FROM canvas_catalog
                WHERE canvas_id = ? AND canvas_kind = 'custom'
                """,
                (normalized_canvas_id,),
            ).fetchone()
            if row is None:
                raise ValueError("自定义画布不存在")
            storage_key = str(row["storage_key"] or "").strip()
            title = str(row["title"] or "").strip()
            conn.execute("DELETE FROM canvas_catalog WHERE canvas_id = ?", (normalized_canvas_id,))
    deleted = delete_episode_canvas_v4(project_id, storage_key)
    return {
        "success": True,
        "canvasId": normalized_canvas_id,
        "title": title,
        "storageKey": storage_key,
        "deleted": bool(deleted.get("deleted")),
        "deletedCount": int(deleted.get("deletedCount") or 0),
        "deletedRecords": copy.deepcopy(deleted.get("deletedRecords") or {}),
        "projectChanged": True,
        "changedResources": ["canvas_catalog", *list(deleted.get("changedResources") or [])],
    }


def delete_episode_canvas_v4(project_id: str, episode_id: str) -> dict[str, Any]:
    normalized_episode_id = str(episode_id or "").strip()
    if not normalized_episode_id:
        raise ValueError("缺少 episodeId")
    path = canvas_db_path(project_id)
    if not path.exists():
        return {
            "success": True,
            "episodeId": normalized_episode_id,
            "deleted": False,
            "deletedCount": 0,
            "deletedRecords": {},
            "changedResources": [],
        }
    tables = (
        ("canvas_projection_cache", "canvas_projection"),
        ("canvas_tasks", "canvas_task"),
        ("canvas_versions", "canvas_version"),
        ("canvas_edges", "canvas_edge"),
        ("canvas_nodes", "canvas_node"),
        ("canvas_routes", "canvas_route"),
        ("canvas_work_chains", "canvas_work_chain"),
        ("canvas_ops", "canvas_op"),
        ("canvas_documents", "canvas_document"),
    )
    deleted_records: dict[str, int] = {}
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            for table, _resource in tables:
                cursor = conn.execute(f"DELETE FROM {table} WHERE episode_id = ?", (normalized_episode_id,))
                deleted_count = int(cursor.rowcount or 0)
                if deleted_count > 0:
                    deleted_records[table] = deleted_count
    changed_resources = [
        resource
        for table, resource in tables
        if deleted_records.get(table)
    ]
    return {
        "success": True,
        "episodeId": normalized_episode_id,
        "deleted": bool(deleted_records),
        "deletedCount": sum(deleted_records.values()),
        "deletedRecords": deleted_records,
        "changedResources": changed_resources,
    }


def write_canvas_task_record_v4(
    project_id: str,
    episode_id: str,
    task: dict[str, Any] | None,
    *,
    op_type: str = "card_patch",
    changed_resources: list[str] | None = None,
) -> dict[str, Any]:
    perf_started_at = canvas_perf_start()
    task_row = copy.deepcopy(task if isinstance(task, dict) else {})
    task_id = str(task_row.get("id") or task_row.get("taskId") or task_row.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("缺少任务ID")
    normalized_op_type = str(op_type or "card_patch").strip() or "card_patch"
    changed = normalize_canvas_changed_resources(changed_resources or ["canvas_task"])
    now = _now()
    status = "ok"
    no_op = False
    revision = 0
    updated_record_count = 0
    try:
        with _SQLITE_WRITE_LOCK:
            with _canvas_connection(project_id) as conn:
                document = _ensure_canvas_document_in_conn(conn, episode_id, now=now)
                base_revision = int(document["revision"] or 0)
                revision = base_revision
                stored_tasks, updated_refs, _removed_refs = _write_canvas_task_rows_in_conn(
                    conn,
                    episode_id=episode_id,
                    tasks=[task_row],
                    now=now,
                    replace_all=False,
                )
                updated_record_count = len(updated_refs)
                if not updated_refs:
                    no_op = True
                    return {
                        "success": True,
                        "episodeId": episode_id,
                        "taskId": task_id,
                        "workflowVersion": base_revision,
                        "revision": base_revision,
                        "opType": normalized_op_type,
                        "records": _records_payload(),
                        "changedResources": [],
                        "task": copy.deepcopy(stored_tasks[0] if stored_tasks else task_row),
                    }
                revision = base_revision + 1
                now = _now()
                conn.execute(
                    """
                    UPDATE canvas_documents
                    SET revision = ?, updated_at = ?
                    WHERE episode_id = ?
                    """,
                    (revision, now, episode_id),
                )
                records = _records_payload(updated=updated_refs)
                mutation = _record_op(
                    conn,
                    episode_id=episode_id,
                    op_type=normalized_op_type,
                    base_revision=base_revision,
                    revision=revision,
                    payload={
                        "records": records,
                        "taskIds": [str(ref.get("id") or "") for ref in updated_refs],
                        "changedResources": changed,
                    },
                )
        return {
            "success": True,
            "episodeId": episode_id,
            "taskId": task_id,
            "workflowVersion": revision,
            **{key: copy.deepcopy(value) for key, value in mutation.items() if key != "payload"},
            "task": copy.deepcopy(stored_tasks[0] if stored_tasks else task_row),
        }
    except Exception:
        status = "error"
        raise
    finally:
        canvas_perf_log(
            "write_canvas_task_record_v4",
            projectId=project_id,
            episodeId=episode_id,
            taskId=task_id,
            taskStatus=str(task_row.get("status") or ""),
            opType=normalized_op_type,
            status=status,
            noOp=no_op,
            durationMs=canvas_perf_elapsed_ms(perf_started_at),
            changedResourceCount=len(changed),
            updatedRecordCount=updated_record_count,
            revision=revision,
        )


def write_canvas_task_records_v4(
    project_id: str,
    episode_id: str,
    tasks: list[dict[str, Any]],
    *,
    op_type: str = "derived_refresh",
    changed_resources: list[str] | None = None,
) -> dict[str, Any]:
    task_rows = [copy.deepcopy(task) for task in (tasks if isinstance(tasks, list) else []) if isinstance(task, dict)]
    normalized_op_type = str(op_type or "derived_refresh").strip() or "derived_refresh"
    changed = normalize_canvas_changed_resources(changed_resources or ["canvas_task"])
    now = _now()
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            document = _ensure_canvas_document_in_conn(conn, episode_id, now=now)
            base_revision = int(document["revision"] or 0)
            stored_tasks, updated_refs, removed_refs = _write_canvas_task_rows_in_conn(
                conn,
                episode_id=episode_id,
                tasks=task_rows[-300:],
                now=now,
                replace_all=True,
            )
            if not updated_refs and not removed_refs:
                return {
                    "success": True,
                    "episodeId": episode_id,
                    "taskCount": len(stored_tasks),
                    "workflowVersion": base_revision,
                    "revision": base_revision,
                    "opType": normalized_op_type,
                    "records": _records_payload(),
                    "changedResources": [],
                    "tasks": copy.deepcopy(stored_tasks),
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
            records = _records_payload(updated=updated_refs, removed=removed_refs)
            mutation = _record_op(
                conn,
                episode_id=episode_id,
                op_type=normalized_op_type,
                base_revision=base_revision,
                revision=revision,
                payload={
                    "records": records,
                    "taskIds": [str(ref.get("id") or "") for ref in updated_refs],
                    "removedTaskIds": [str(ref.get("id") or "") for ref in removed_refs],
                    "changedResources": changed,
                },
            )
    return {
        "success": True,
        "episodeId": episode_id,
        "taskCount": len(stored_tasks),
        "workflowVersion": revision,
        **{key: copy.deepcopy(value) for key, value in mutation.items() if key != "payload"},
        "tasks": copy.deepcopy(stored_tasks),
    }


def _production_status_content(status: Any) -> Any:
    if not isinstance(status, dict):
        return status
    content = {key: value for key, value in status.items() if key != "updatedAt"}
    if isinstance(content.get("independentWorkChains"), dict):
        content["independentWorkChains"] = {
            key: _production_status_content(value)
            for key, value in content["independentWorkChains"].items()
        }
    return content


def write_canvas_production_status_v4(
    project_id: str,
    episode_id: str,
    production_status: dict[str, Any],
    *,
    route_statuses: dict[str, str],
    work_chain_statuses: dict[str, str],
    state: dict[str, Any],
    expected_revision: int,
) -> dict[str, Any]:
    """Commit derived status only; this entry cannot insert structural records."""
    now = _now()
    stored: dict[str, list[dict[str, Any]]] = {"routes": [], "workChains": []}
    changed = ["canvas_document", "episode_production_status"]
    updated_refs: list[dict[str, Any]] = []
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            document = _canvas_mutation_document_in_conn(
                conn, episode_id, now=now, expected_revision=expected_revision,
            )
            base_revision = int(document["revision"] or 0)
            for table, id_column, json_column, statuses, output_key, resource, summarize in (
                ("canvas_routes", "route_id", "route_json", route_statuses, "routes", "canvas_route", _route_summary_record),
                ("canvas_work_chains", "work_chain_id", "work_chain_json", work_chain_statuses, "workChains", "canvas_work_chain", _work_chain_summary_record),
            ):
                if not statuses:
                    continue
                rows = conn.execute(
                    f"SELECT {id_column}, {json_column} FROM {table} WHERE episode_id = ?",
                    (episode_id,),
                ).fetchall()
                for row in rows:
                    record_id = str(row[id_column])
                    if record_id not in statuses:
                        continue
                    item = _json_loads(row[json_column], {})
                    if item.get("status") == statuses[record_id]:
                        continue
                    item["status"] = statuses[record_id]
                    conn.execute(
                        f"UPDATE {table} SET {json_column} = ?, summary_json = ?, updated_at = ? "
                        f"WHERE episode_id = ? AND {id_column} = ?",
                        (_json_dumps(item), _json_dumps(summarize(item)), now, episode_id, record_id),
                    )
                    stored[output_key].append(item)
                    updated_refs.append(_record_ref(resource, record_id))
                if stored[output_key]:
                    changed.append(resource)
            current_extras = _canvas_document_extras_payload(document)
            previous_status = current_extras.get("productionStatus")
            if _json_signature(_production_status_content(previous_status)) == _json_signature(_production_status_content(production_status)):
                # Keep the timestamp of the last semantic change on no-op reads.
                production_status = copy.deepcopy(previous_status)
            next_extras = _merge_canvas_document_extras(current_extras, {"productionStatus": production_status})
            current_state = _json_loads(document["state_json"], {})
            next_state = copy.deepcopy(current_state)
            for key in ("productionState", "nextAction"):
                if key in state:
                    next_state[key] = state[key]
            if (
                not updated_refs
                and _json_signature(current_extras) == _json_signature(next_extras)
                and _json_signature(current_state) == _json_signature(next_state)
            ):
                # Advancing the projection's coverage is bookkeeping, not a new
                # canvas mutation. Otherwise every no-op refresh creates a revision.
                next_extras["productionStatusRevision"] = base_revision
                if current_extras.get("productionStatusRevision") != base_revision:
                    conn.execute(
                        "UPDATE canvas_documents SET extras_json = ? WHERE episode_id = ?",
                        (_json_dumps(next_extras), episode_id),
                    )
                return {
                    "success": True, "episodeId": episode_id, "stored": True,
                    "workflowVersion": base_revision, "revision": base_revision,
                    "opType": "derived_refresh", "records": _records_payload(),
                    "changedResources": [], "documentExtras": next_extras, "state": next_state,
                    "productionStatus": copy.deepcopy(production_status), **stored,
                }
            revision = base_revision + 1
            next_extras["productionStatusRevision"] = revision
            conn.execute(
                "UPDATE canvas_documents SET revision = ?, state_json = ?, extras_json = ?, updated_at = ? WHERE episode_id = ?",
                (revision, _json_dumps(next_state), _json_dumps(next_extras), now, episode_id),
            )
            records = _records_payload(updated=[_record_ref("canvas_document", episode_id), *updated_refs])
            mutation = _record_op(
                conn, episode_id=episode_id, op_type="derived_refresh",
                base_revision=base_revision, revision=revision,
                payload={
                    "records": records, "state": next_state, "documentExtras": next_extras,
                    "productionStatus": copy.deepcopy(production_status), "changedResources": changed,
                    "routeIds": [row["id"] for row in stored["routes"]],
                    "workChainIds": [row["id"] for row in stored["workChains"]],
                },
            )
    return {
        "success": True, "episodeId": episode_id, "stored": True,
        "workflowVersion": revision, "state": next_state, "documentExtras": next_extras,
        "productionStatus": copy.deepcopy(production_status), **stored,
        **{key: copy.deepcopy(value) for key, value in mutation.items() if key != "payload"},
    }


def write_canvas_document_extras_v4(
    project_id: str,
    episode_id: str,
    extras: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    state_delete_keys: list[str] | None = None,
    op_type: str = "derived_refresh",
    changed_resources: list[str] | None = None,
) -> dict[str, Any]:
    patch = _merge_canvas_document_extras({}, extras if isinstance(extras, dict) else {})
    state_patch = copy.deepcopy(state if isinstance(state, dict) else {})
    delete_state_keys = {
        str(item or "").strip()
        for item in (state_delete_keys if isinstance(state_delete_keys, list) else [])
        if str(item or "").strip()
    }
    normalized_op_type = str(op_type or "derived_refresh").strip() or "derived_refresh"
    changed = copy.deepcopy(
        changed_resources
        if isinstance(changed_resources, list)
        else ["canvas_document"]
    )
    now = _now()
    mutation: dict[str, Any] = {}
    revision = 0
    next_extras: dict[str, Any] = {}
    next_state: dict[str, Any] = {}
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            document = _canvas_document_row(conn, episode_id)
            if document is None:
                return {
                    "success": True,
                    "episodeId": episode_id,
                    "stored": False,
                    "workflowVersion": 0,
                    "revision": 0,
                    "opType": normalized_op_type,
                    "records": _records_payload(),
                    "changedResources": [],
                }
            base_revision = int(document["revision"] or 0)
            current_extras = _canvas_document_extras_payload(document)
            current_state = _json_loads(document["state_json"], {})
            current_state = copy.deepcopy(current_state) if isinstance(current_state, dict) else {}
            next_extras = _merge_canvas_document_extras(current_extras, patch)
            next_state = copy.deepcopy(current_state)
            for key in delete_state_keys:
                next_state.pop(key, None)
            if state_patch:
                next_state.update(state_patch)
            if (
                _json_signature(current_extras) == _json_signature(next_extras)
                and _json_signature(current_state) == _json_signature(next_state)
            ):
                return {
                    "success": True,
                    "episodeId": episode_id,
                    "stored": True,
                    "workflowVersion": base_revision,
                    "revision": base_revision,
                    "opType": normalized_op_type,
                    "records": _records_payload(),
                    "changedResources": [],
                    "documentExtras": copy.deepcopy(next_extras),
                    "state": copy.deepcopy(next_state),
                }
            revision = base_revision + 1
            conn.execute(
                """
                UPDATE canvas_documents
                SET revision = ?, state_json = ?, extras_json = ?, updated_at = ?
                WHERE episode_id = ?
                """,
                (revision, _json_dumps(next_state), _json_dumps(next_extras), now, episode_id),
            )
            records = _records_payload(updated=[_record_ref("canvas_document", episode_id)])
            op_payload: dict[str, Any] = {
                "records": records,
                "state": copy.deepcopy(next_state),
                "documentExtras": copy.deepcopy(next_extras),
                "changedResources": changed,
            }
            if isinstance(next_extras.get("productionStatus"), dict):
                op_payload["productionStatus"] = copy.deepcopy(next_extras["productionStatus"])
            mutation = _record_op(
                conn,
                episode_id=episode_id,
                op_type=normalized_op_type,
                base_revision=base_revision,
                revision=revision,
                payload=op_payload,
            )
    result = {
        "success": True,
        "episodeId": episode_id,
        "stored": True,
        "workflowVersion": revision,
        "state": copy.deepcopy(next_state),
        "documentExtras": copy.deepcopy(next_extras),
        **{key: copy.deepcopy(value) for key, value in mutation.items() if key != "payload"},
    }
    if isinstance(next_extras.get("productionStatus"), dict):
        result["productionStatus"] = copy.deepcopy(next_extras["productionStatus"])
    return result


def write_canvas_projection_cache_v4(
    project_id: str,
    episode_id: str,
    cache_key: str,
    cache_type: str,
    payload: dict[str, Any] | list[Any] | None,
    *,
    revision: int | None = None,
    record_op: bool = False,
    changed_resources: list[str] | None = None,
) -> dict[str, Any]:
    key = str(cache_key or "").strip()
    projection_type = str(cache_type or "projection").strip() or "projection"
    if not key:
        raise ValueError("缺少派生缓存 key")
    payload_row = copy.deepcopy(payload if isinstance(payload, (dict, list)) else {})
    mutation: dict[str, Any] = {}
    op_revision = 0
    changed = normalize_canvas_changed_resources(changed_resources or ["canvas_projection"])
    records = _records_payload(updated=[_record_ref("canvas_projection", key, cacheType=projection_type)])
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            document = _canvas_mutation_document_in_conn(
                conn, episode_id, now=_now(), expected_revision=revision,
            )
            base_revision = int(document["revision"] or 0)
            op_revision = base_revision + 1 if record_op else int(revision if revision is not None else base_revision)
            existing = conn.execute(
                """
                SELECT cache_type, payload_json, revision
                FROM canvas_projection_cache
                WHERE episode_id = ? AND cache_key = ?
                """,
                (episode_id, key),
            ).fetchone()
            if existing is not None:
                existing_type = str(existing["cache_type"] or "")
                existing_payload = _json_loads(existing["payload_json"], {})
                if existing_type == projection_type and _json_signature(existing_payload) == _json_signature(payload_row):
                    existing_revision = int(existing["revision"] or base_revision)
                    return {
                        "success": True,
                        "episodeId": episode_id,
                        "cacheKey": key,
                        "cacheType": projection_type,
                        "workflowVersion": existing_revision if not record_op else base_revision,
                        "revision": existing_revision if not record_op else base_revision,
                        "txId": "",
                        "seq": None,
                        "opType": "derived_refresh" if record_op else "",
                        "records": _records_payload(),
                        "changedResources": [],
                    }
            records = _records_payload(
                added=[] if existing is not None else [_record_ref("canvas_projection", key, cacheType=projection_type)],
                updated=[_record_ref("canvas_projection", key, cacheType=projection_type)] if existing is not None else [],
            )
            conn.execute(
                """
                INSERT INTO canvas_projection_cache (
                    episode_id, cache_key, cache_type, payload_json, revision, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(episode_id, cache_key) DO UPDATE SET
                    cache_type = excluded.cache_type,
                    payload_json = excluded.payload_json,
                    revision = excluded.revision,
                    updated_at = excluded.updated_at
                """,
                (episode_id, key, projection_type, _json_dumps(payload_row), op_revision, _now()),
            )
            if record_op:
                conn.execute(
                    """
                    UPDATE canvas_documents
                    SET revision = ?, updated_at = ?
                    WHERE episode_id = ?
                    """,
                    (op_revision, _now(), episode_id),
                )
                mutation = _record_op(
                    conn,
                    episode_id=episode_id,
                    op_type="derived_refresh",
                    base_revision=base_revision,
                    revision=op_revision,
                    payload={
                        "records": records,
                        "projectionKeys": [key],
                        "changedResources": changed,
                    },
                )
    return {
        "success": True,
        "episodeId": episode_id,
        "cacheKey": key,
        "cacheType": projection_type,
        "workflowVersion": mutation.get("revision", op_revision),
        "revision": mutation.get("revision", op_revision),
        "txId": mutation.get("txId", ""),
        "seq": mutation.get("seq"),
        "opType": mutation.get("opType", "derived_refresh" if record_op else ""),
        "records": mutation.get("records", records),
        "changedResources": mutation.get("changedResources", changed if record_op else []),
    }
