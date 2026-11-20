# -*- coding: utf-8 -*-
"""画布结果提交、活动版本选择和结果版本删除的完整事务。"""
from __future__ import annotations

import copy
from .canvas_store_database import (
    _SQLITE_WRITE_LOCK,
    _canvas_connection,
    _canvas_document_row,
    _canvas_mutation_document_in_conn,
)
from .canvas_store_queries import (
    _read_card_results_in_conn,
    _version_refs_for_nodes,
)
from .canvas_store_records import (
    _active_card_version_id,
    _canvas_version_ref_payload,
    _canvas_version_ref_payloads,
    _json_dumps,
    _record_ref,
    _records_payload,
    _row_node,
)
from .canvas_store_rows import (
    _clear_deleted_version_refs_in_conn,
    _patch_workflow_cards_in_conn,
    _record_op,
    _write_card_results_in_conn,
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


def commit_canvas_result_v4(
    project_id: str,
    episode_id: str,
    *,
    node_id: str,
    versions: list[dict[str, Any]],
    active_version_id: str = "",
    nodes: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
    changed_resources: list[str] | None = None,
    expected_revision: int | str | None = None,
) -> dict[str, Any]:
    perf_started_at = canvas_perf_start()
    target_node_id = str(node_id or "").strip()
    if not target_node_id:
        raise ValueError("缺少节点ID")
    now = _now()
    changed = copy.deepcopy(
        changed_resources
        if isinstance(changed_resources, list)
        else ["canvas_node", "canvas_version", "canvas_task"]
    )
    status = "ok"
    revision = 0
    patched_node_count = 0
    normalized_version_count = 0
    task_count = 0
    try:
        with _SQLITE_WRITE_LOCK:
            with _canvas_connection(project_id) as conn:
                document = _canvas_mutation_document_in_conn(
                    conn, episode_id, now=now, expected_revision=expected_revision, create_if_missing=True,
                )
                base_revision = int(document["revision"] or 0)
                revision = base_revision
                normalized_versions = _write_card_results_in_conn(
                    conn,
                    episode_id=episode_id,
                    card_id=target_node_id,
                    versions=versions,
                    active_version_id=active_version_id,
                    now=now,
                )
                normalized_version_count = len(normalized_versions)
                patched_nodes = _patch_workflow_cards_in_conn(
                    conn,
                    episode_id=episode_id,
                    nodes=nodes if isinstance(nodes, list) else [],
                    now=now,
                )
                patched_node_count = len(patched_nodes)
                task_refs: list[dict[str, Any]] = []
                task_rows: list[dict[str, Any]] = []
                for task in tasks if isinstance(tasks, list) else []:
                    if not isinstance(task, dict):
                        continue
                    task_row = copy.deepcopy(task)
                    task_id = str(task_row.get("id") or task_row.get("taskId") or task_row.get("task_id") or "").strip()
                    if not task_id:
                        continue
                    task_node_id = str(task_row.get("nodeId") or task_row.get("node_id") or target_node_id).strip()
                    status_text = str(task_row.get("status") or "").strip()
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
                        (episode_id, task_id, task_node_id, status_text, _json_dumps(task_row), now),
                    )
                    task_rows.append(task_row)
                    task_refs.append(_record_ref("canvas_task", task_id, nodeId=task_node_id))
                task_count = len(task_rows)
                revision = base_revision + 1
                conn.execute(
                    """
                    UPDATE canvas_documents
                    SET revision = ?, updated_at = ?
                    WHERE episode_id = ?
                    """,
                    (revision, now, episode_id),
                )
                node_ids = [str(node.get("id") or "") for node in patched_nodes if isinstance(node, dict)]
                version_refs = [
                    _record_ref(
                        "canvas_version",
                        str(version.get("id") or ""),
                        nodeId=str(version.get("nodeId") or target_node_id),
                        active=str(version.get("id") or "") == str(active_version_id or ""),
                    )
                    for version in normalized_versions
                    if str(version.get("id") or "").strip()
                ]
                records = _records_payload(
                    updated=[
                        *[_record_ref("canvas_node", current_node_id) for current_node_id in node_ids if current_node_id],
                        *version_refs,
                        *task_refs,
                    ]
                )
                mutation = _record_op(
                    conn,
                    episode_id=episode_id,
                    op_type="result_commit",
                    base_revision=base_revision,
                    revision=revision,
                    payload={
                        "records": records,
                        "nodeIds": node_ids,
                        "versionRefs": [
                            ref
                            for ref in (
                                _canvas_version_ref_payload(
                                    version.get("nodeId") or target_node_id,
                                    version.get("id"),
                                )
                                for version in normalized_versions
                            )
                            if ref is not None
                        ],
                        "taskIds": [str(ref.get("id") or "") for ref in task_refs],
                        "changedResources": changed,
                    },
                )
                if task_rows:
                    mutation_fields = {
                        key: copy.deepcopy(mutation.get(key))
                        for key in ("txId", "seq", "revision", "baseRevision", "opType", "records", "changedResources")
                        if mutation.get(key) is not None
                    }
                    for task_row in task_rows:
                        task_id = str(task_row.get("id") or task_row.get("taskId") or task_row.get("task_id") or "").strip()
                        if not task_id:
                            continue
                        task_result = task_row.get("result") if isinstance(task_row.get("result"), dict) else {}
                        task_row["result"] = {
                            **copy.deepcopy(task_result),
                            **mutation_fields,
                        }
                        conn.execute(
                            """
                            UPDATE canvas_tasks
                            SET task_json = ?, updated_at = ?
                            WHERE episode_id = ? AND task_id = ?
                            """,
                            (_json_dumps(task_row), now, episode_id, task_id),
                        )
        return {
            "success": True,
            "episodeId": episode_id,
            "workflowVersion": revision,
            **{key: copy.deepcopy(value) for key, value in mutation.items() if key != "payload"},
            "nodes": patched_nodes,
            "versions": normalized_versions,
        }
    except Exception:
        status = "error"
        raise
    finally:
        canvas_perf_log(
            "commit_canvas_result_v4",
            projectId=project_id,
            episodeId=episode_id,
            nodeId=target_node_id,
            status=status,
            durationMs=canvas_perf_elapsed_ms(perf_started_at),
            inputVersionCount=len(versions) if isinstance(versions, list) else 0,
            normalizedVersionCount=normalized_version_count,
            inputNodeCount=len(nodes) if isinstance(nodes, list) else 0,
            patchedNodeCount=patched_node_count,
            taskCount=task_count,
            changedResourceCount=len(changed),
            revision=revision,
        )


def set_card_active_version(
    project_id: str,
    episode_id: str,
    card_id: str,
    version_id: str,
    *,
    record_node_patch: bool = True,
) -> dict[str, Any]:
    node_id = str(card_id or "").strip()
    target_version_id = str(version_id or "").strip()
    if not node_id:
        raise ValueError("缺少节点ID")
    if not target_version_id:
        raise ValueError("缺少版本ID")
    now = _now()
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            document = _canvas_document_row(conn, episode_id)
            if document is None:
                raise FileNotFoundError("画布不存在")
            versions = _read_card_results_in_conn(conn, episode_id, node_id)
            selected = next(
                (item for item in versions if str(item.get("id") or "") == target_version_id),
                None,
            )
            if not selected:
                raise FileNotFoundError("版本不存在")
            selected = copy.deepcopy(selected)
            selected["active"] = True
            base_revision = int(document["revision"] or 0)
            _write_card_results_in_conn(
                conn,
                episode_id=episode_id,
                card_id=node_id,
                versions=versions,
                active_version_id=target_version_id,
                now=now,
            )
            patched_nodes: list[dict[str, Any]] = []
            if record_node_patch:
                row = conn.execute(
                    """
                    SELECT node_id, node_type, route_id, segment_id, work_chain_id,
                           position_json, status, data_json, node_json, summary_json
                    FROM canvas_nodes
                    WHERE episode_id = ? AND node_id = ?
                    """,
                    (episode_id, node_id),
                ).fetchone()
                if row is not None:
                    node = _row_node(row, detail="full")
                    data = node.get("data") if isinstance(node.get("data"), dict) else {}
                    data["activeVersionId"] = target_version_id
                    data["activeMediaVersionId"] = target_version_id
                    data["mediaVersionId"] = target_version_id
                    data["status"] = "ready"
                    media = selected.get("media") if isinstance(selected.get("media"), dict) else None
                    if media:
                        data["media"] = copy.deepcopy(media)
                        if selected.get("preview"):
                            data["preview"] = selected.get("preview")
                    else:
                        data.pop("media", None)
                        data.pop("preview", None)
                    node["data"] = data
                    node["activeVersionId"] = target_version_id
                    node["activeMediaVersionId"] = target_version_id
                    node["mediaVersionId"] = target_version_id
                    node["status"] = "ready"
                    node["updatedAt"] = now
                    patched_nodes = _patch_workflow_cards_in_conn(
                        conn,
                        episode_id=episode_id,
                        nodes=[node],
                        now=now,
                    )
            revision = base_revision + 1
            conn.execute(
                """
                UPDATE canvas_documents
                SET revision = ?, updated_at = ?
                WHERE episode_id = ?
                """,
                (revision, now, episode_id),
            )
            node_ids = [
                str(node.get("id") or "").strip()
                for node in patched_nodes
                if isinstance(node, dict) and str(node.get("id") or "").strip()
            ]
            version_refs = _version_refs_for_nodes(conn, episode_id=episode_id, node_ids=[node_id])
            changed_resources = ["canvas_version"]
            if node_ids:
                changed_resources.insert(0, "canvas_node")
            records = _records_payload(
                updated=[
                    *[_record_ref("canvas_node", current_node_id) for current_node_id in node_ids],
                    *version_refs,
                ]
            )
            mutation = _record_op(
                conn,
                episode_id=episode_id,
                op_type="result_commit",
                base_revision=base_revision,
                revision=revision,
                payload={
                    "records": records,
                    "nodeIds": node_ids,
                    "versionRefs": _canvas_version_ref_payloads(version_refs),
                    "changedResources": changed_resources,
                },
            )
    return {
        "success": True,
        "version": copy.deepcopy(selected),
        "workflowVersion": revision,
        **{key: copy.deepcopy(value) for key, value in mutation.items() if key != "payload"},
    }


def delete_card_result_version(project_id: str, episode_id: str, card_id: str, version_id: str) -> dict[str, Any]:
    node_id = str(card_id or "").strip()
    target_version_id = str(version_id or "").strip()
    if not node_id:
        raise ValueError("缺少节点ID")
    if not target_version_id:
        raise ValueError("缺少版本ID")
    now = _now()
    with _SQLITE_WRITE_LOCK:
        with _canvas_connection(project_id) as conn:
            document = _canvas_document_row(conn, episode_id)
            if document is None:
                raise FileNotFoundError("画布不存在")
            versions = _read_card_results_in_conn(conn, episode_id, node_id)
            target = next(
                (item for item in versions if str(item.get("id") or "") == target_version_id),
                None,
            )
            if not target:
                raise FileNotFoundError("版本不存在")
            active_version_id = _active_card_version_id(conn, episode_id, node_id)
            if active_version_id == target_version_id:
                raise ValueError("当前版本不能删除，请先切换到其它版本")
            if len(versions) <= 1:
                raise ValueError("至少保留一个版本")
            base_revision = int(document["revision"] or 0)
            remaining_versions = [
                item for item in versions if str(item.get("id") or "") != target_version_id
            ]
            fallback_version = next(
                (
                    item
                    for item in remaining_versions
                    if str(item.get("id") or "").strip() == active_version_id
                ),
                None,
            )
            _write_card_results_in_conn(
                conn,
                episode_id=episode_id,
                card_id=node_id,
                versions=remaining_versions,
                active_version_id=active_version_id,
                now=now,
            )
            patched_nodes = _clear_deleted_version_refs_in_conn(
                conn,
                episode_id=episode_id,
                node_id=node_id,
                version_id=target_version_id,
                fallback_version=fallback_version,
                now=now,
            )
            revision = base_revision + 1
            conn.execute(
                """
                UPDATE canvas_documents
                SET revision = ?, updated_at = ?
                WHERE episode_id = ?
                """,
                (revision, now, episode_id),
            )
            node_ids = [
                str(node.get("id") or "").strip()
                for node in patched_nodes
                if isinstance(node, dict) and str(node.get("id") or "").strip()
            ]
            changed_resources = ["canvas_version"]
            if node_ids:
                changed_resources.insert(0, "canvas_node")
            records = _records_payload(
                updated=[_record_ref("canvas_node", current_node_id) for current_node_id in node_ids],
                removed=[_record_ref("canvas_version", target_version_id, nodeId=node_id)],
            )
            mutation = _record_op(
                conn,
                episode_id=episode_id,
                op_type="result_commit",
                base_revision=base_revision,
                revision=revision,
                payload={
                    "records": records,
                    "nodeIds": node_ids,
                    "versionRefs": [],
                    "removedVersionRefs": [
                        _canvas_version_ref_payload(node_id, target_version_id)
                    ],
                    "changedResources": changed_resources,
                },
            )
    return {
        "success": True,
        "nodes": copy.deepcopy(patched_nodes),
        "workflowVersion": revision,
        **{key: copy.deepcopy(value) for key, value in mutation.items() if key != "payload"},
    }
