# -*- coding: utf-8 -*-
"""同一 SQLite 连接内的节点来源及版本身份索引维护。"""
from __future__ import annotations

import sqlite3
from .canvas_store_records import (
    _json_loads,
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


_CANVAS_NODE_SOURCE_REFS_META_KEY = "canvas_node_source_refs:v1"


_CANVAS_VERSION_IDENTITY_REFS_META_KEY = "canvas_version_identity_refs:v1"


def _canvas_node_source_refs_from_data(data: dict[str, Any]) -> list[tuple[str, str]]:
    if not isinstance(data, dict):
        return []
    refs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_ref(value: Any, ref_kind: str) -> None:
        source_node_id = str(value or "").strip()
        normalized_kind = str(ref_kind or "").strip()
        if not source_node_id or not normalized_kind:
            return
        key = (source_node_id, normalized_kind)
        if key in seen:
            return
        seen.add(key)
        refs.append(key)

    for key, ref_kind in (
        ("resultOfNodeId", "result"),
        ("result_of_node_id", "result"),
        ("sourceNodeId", "source"),
        ("source_node_id", "source"),
        ("taskNodeId", "task"),
        ("task_node_id", "task"),
    ):
        add_ref(data.get(key), ref_kind)
    input_links = data.get("inputLinks")
    iterable_input_links = input_links if isinstance(input_links, list) else []
    for link in iterable_input_links:
        if not isinstance(link, dict):
            continue
        add_ref(
            link.get("sourceNodeId")
            or link.get("source_node_id")
            or link.get("source"),
            "input_link",
        )
    return refs


def _upsert_canvas_node_source_refs_in_conn(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    target_node_id: str,
    data: dict[str, Any],
    now: str,
) -> None:
    normalized_target_node_id = str(target_node_id or "").strip()
    if not normalized_target_node_id:
        return
    conn.execute(
        """
        DELETE FROM canvas_node_source_refs
        WHERE episode_id = ? AND target_node_id = ?
        """,
        (episode_id, normalized_target_node_id),
    )
    refs = _canvas_node_source_refs_from_data(data)
    for index, (source_node_id, ref_kind) in enumerate(refs):
        conn.execute(
            """
            INSERT INTO canvas_node_source_refs (
                episode_id, source_node_id, target_node_id,
                ref_kind, sort_index, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id, source_node_id, target_node_id, ref_kind)
            DO UPDATE SET
                sort_index = excluded.sort_index,
                updated_at = excluded.updated_at
            """,
            (
                episode_id,
                source_node_id,
                normalized_target_node_id,
                ref_kind,
                index,
                now,
            ),
        )


def _rebuild_canvas_node_source_refs_in_conn(conn: sqlite3.Connection) -> int:
    now = _now()
    rows = conn.execute(
        """
        SELECT episode_id, node_id, data_json
        FROM canvas_nodes
        ORDER BY episode_id ASC, node_id ASC
        """
    ).fetchall()
    conn.execute("DELETE FROM canvas_node_source_refs")
    ref_count = 0
    for row in rows:
        data = _json_loads(row["data_json"], {})
        refs = _canvas_node_source_refs_from_data(data)
        ref_count += len(refs)
        if not refs:
            continue
        _upsert_canvas_node_source_refs_in_conn(
            conn,
            episode_id=str(row["episode_id"] or ""),
            target_node_id=str(row["node_id"] or ""),
            data=data,
            now=now,
        )
    return ref_count


def _ensure_canvas_node_source_refs_initialized(conn: sqlite3.Connection) -> None:
    perf_started_at = canvas_perf_start()
    row = conn.execute(
        """
        SELECT value
        FROM canvas_runtime_meta
        WHERE key = ?
        """,
        (_CANVAS_NODE_SOURCE_REFS_META_KEY,),
    ).fetchone()
    if row is not None and str(row["value"] or "") == "ok":
        return
    ref_count = _rebuild_canvas_node_source_refs_in_conn(conn)
    conn.execute(
        """
        INSERT INTO canvas_runtime_meta(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key)
        DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (_CANVAS_NODE_SOURCE_REFS_META_KEY, "ok", _now()),
    )
    canvas_perf_log(
        "canvas_node_source_refs.initialize",
        status="ok",
        refCount=ref_count,
        durationMs=canvas_perf_elapsed_ms(perf_started_at),
    )


def _canvas_version_identity_refs_from_version(version: dict[str, Any]) -> list[tuple[str, str]]:
    if not isinstance(version, dict):
        return []
    refs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_ref(value: Any, ref_kind: str) -> None:
        identity = str(value or "").strip()
        normalized_kind = str(ref_kind or "").strip()
        if not identity or not normalized_kind:
            return
        key = (identity, normalized_kind)
        if key in seen:
            return
        seen.add(key)
        refs.append(key)

    for key, ref_kind in (
        ("id", "version"),
        ("versionId", "version"),
        ("mediaId", "media"),
        ("sourceVersionId", "source_version"),
    ):
        add_ref(version.get(key), ref_kind)
    media = version.get("media") if isinstance(version.get("media"), dict) else {}
    for key, ref_kind in (
        ("id", "media"),
        ("mediaId", "media"),
        ("versionId", "media_version"),
    ):
        add_ref(media.get(key), ref_kind)
    return refs


def _upsert_canvas_version_identity_refs_in_conn(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    node_id: str,
    version_id: str,
    version: dict[str, Any],
    now: str,
) -> None:
    normalized_node_id = str(node_id or "").strip()
    normalized_version_id = str(version_id or "").strip()
    if not normalized_node_id or not normalized_version_id:
        return
    conn.execute(
        """
        DELETE FROM canvas_version_identity_refs
        WHERE episode_id = ? AND node_id = ? AND version_id = ?
        """,
        (episode_id, normalized_node_id, normalized_version_id),
    )
    for index, (identity, ref_kind) in enumerate(_canvas_version_identity_refs_from_version(version)):
        conn.execute(
            """
            INSERT INTO canvas_version_identity_refs (
                episode_id, identity, node_id, version_id,
                ref_kind, sort_index, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id, identity, node_id, version_id, ref_kind)
            DO UPDATE SET
                sort_index = excluded.sort_index,
                updated_at = excluded.updated_at
            """,
            (
                episode_id,
                identity,
                normalized_node_id,
                normalized_version_id,
                ref_kind,
                index,
                now,
            ),
        )


def _rebuild_canvas_version_identity_refs_in_conn(conn: sqlite3.Connection) -> int:
    now = _now()
    rows = conn.execute(
        """
        SELECT episode_id, node_id, version_id, version_json
        FROM canvas_versions
        ORDER BY episode_id ASC, node_id ASC, version_id ASC
        """
    ).fetchall()
    conn.execute("DELETE FROM canvas_version_identity_refs")
    ref_count = 0
    for row in rows:
        version = _json_loads(row["version_json"], {})
        if not isinstance(version, dict):
            version = {}
        version.setdefault("id", str(row["version_id"] or ""))
        version.setdefault("nodeId", str(row["node_id"] or ""))
        refs = _canvas_version_identity_refs_from_version(version)
        ref_count += len(refs)
        if not refs:
            continue
        _upsert_canvas_version_identity_refs_in_conn(
            conn,
            episode_id=str(row["episode_id"] or ""),
            node_id=str(row["node_id"] or ""),
            version_id=str(row["version_id"] or ""),
            version=version,
            now=now,
        )
    return ref_count


def _ensure_canvas_version_identity_refs_initialized(conn: sqlite3.Connection) -> None:
    perf_started_at = canvas_perf_start()
    row = conn.execute(
        """
        SELECT value
        FROM canvas_runtime_meta
        WHERE key = ?
        """,
        (_CANVAS_VERSION_IDENTITY_REFS_META_KEY,),
    ).fetchone()
    if row is not None and str(row["value"] or "") == "ok":
        return
    ref_count = _rebuild_canvas_version_identity_refs_in_conn(conn)
    conn.execute(
        """
        INSERT INTO canvas_runtime_meta(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key)
        DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (_CANVAS_VERSION_IDENTITY_REFS_META_KEY, "ok", _now()),
    )
    canvas_perf_log(
        "canvas_version_identity_refs.initialize",
        status="ok",
        refCount=ref_count,
        durationMs=canvas_perf_elapsed_ms(perf_started_at),
    )
