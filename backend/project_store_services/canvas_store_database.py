# -*- coding: utf-8 -*-
"""画布 SQLite 连接、schema、写锁、修订检查和事务重试的唯一所有者。"""
from __future__ import annotations

import sqlite3
import threading
from .agent_sessions import (
    _project_dir,
)
from .canvas_store_indexes import (
    _ensure_canvas_node_source_refs_initialized,
    _ensure_canvas_version_identity_refs_initialized,
)
from .canvas_store_records import (
    _json_dumps,
    _safe_part,
)
from contextlib import (
    contextmanager,
)
from typing import (
    Callable,
    TypeVar,
)


_SQLITE_WRITE_LOCK = threading.RLock()


_CANVAS_WAL_AUTOCHECKPOINT_PAGES = 1000


_CANVAS_MUTATION_MAX_ATTEMPTS = 4


_MutationResult = TypeVar("_MutationResult")


def episode_root(project_id: str, episode_id: str):
    return _project_dir(project_id) / "episodes" / _safe_part(episode_id, "episode")


def canvas_dir(project_id: str, episode_id: str):
    return episode_root(project_id, episode_id) / "canvas"


def card_root(project_id: str, episode_id: str):
    return episode_root(project_id, episode_id) / "cards"


def card_dir(project_id: str, episode_id: str, card_id: str):
    return card_root(project_id, episode_id) / _safe_part(card_id, "card")


def card_results_dir(project_id: str, episode_id: str, card_id: str):
    return card_dir(project_id, episode_id, card_id) / "results"


def canvas_db_path(project_id: str):
    return _project_dir(project_id) / "canvas_v4.sqlite3"


def _canvas_db(project_id: str) -> sqlite3.Connection:
    path = canvas_db_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute(f"PRAGMA wal_autocheckpoint = {_CANVAS_WAL_AUTOCHECKPOINT_PAGES}")
        _ensure_canvas_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


@contextmanager
def _canvas_connection(project_id: str):
    from .project_deletion_guard import canvas_project_access

    with canvas_project_access(project_id):
        conn = _canvas_db(project_id)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


@contextmanager
def _canvas_snapshot_connection(project_id: str):
    with _canvas_connection(project_id) as conn:
        # Finish any schema initialization before establishing the read snapshot.
        if conn.in_transaction:
            conn.commit()
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        yield conn


def _ensure_canvas_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS canvas_documents (
            episode_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            viewport_json TEXT NOT NULL,
            routes_json TEXT NOT NULL,
            work_chains_json TEXT NOT NULL,
            state_json TEXT NOT NULL,
            extras_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS canvas_nodes (
            episode_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            sort_index INTEGER NOT NULL,
            node_type TEXT NOT NULL,
            route_id TEXT NOT NULL,
            segment_id TEXT NOT NULL,
            work_chain_id TEXT NOT NULL,
            position_json TEXT NOT NULL,
            status TEXT NOT NULL,
            data_json TEXT NOT NULL,
            node_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (episode_id, node_id),
            FOREIGN KEY (episode_id)
                REFERENCES canvas_documents(episode_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_canvas_nodes_episode_sort
            ON canvas_nodes(episode_id, sort_index);

        CREATE INDEX IF NOT EXISTS idx_canvas_nodes_episode_type_sort
            ON canvas_nodes(episode_id, node_type, sort_index);

        CREATE TABLE IF NOT EXISTS canvas_edges (
            episode_id TEXT NOT NULL,
            edge_id TEXT NOT NULL,
            sort_index INTEGER NOT NULL,
            source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            source_handle TEXT NOT NULL,
            target_handle TEXT NOT NULL,
            edge_data_json TEXT NOT NULL,
            edge_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (episode_id, edge_id),
            FOREIGN KEY (episode_id)
                REFERENCES canvas_documents(episode_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_canvas_edges_episode_sort
            ON canvas_edges(episode_id, sort_index);

        CREATE TABLE IF NOT EXISTS canvas_routes (
            episode_id TEXT NOT NULL,
            route_id TEXT NOT NULL,
            sort_index INTEGER NOT NULL,
            route_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (episode_id, route_id),
            FOREIGN KEY (episode_id)
                REFERENCES canvas_documents(episode_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_canvas_routes_episode_sort
            ON canvas_routes(episode_id, sort_index);

        CREATE TABLE IF NOT EXISTS canvas_work_chains (
            episode_id TEXT NOT NULL,
            work_chain_id TEXT NOT NULL,
            sort_index INTEGER NOT NULL,
            work_chain_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (episode_id, work_chain_id),
            FOREIGN KEY (episode_id)
                REFERENCES canvas_documents(episode_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_canvas_work_chains_episode_sort
            ON canvas_work_chains(episode_id, sort_index);

        CREATE TABLE IF NOT EXISTS canvas_versions (
            episode_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            sort_index INTEGER NOT NULL,
            version_type TEXT NOT NULL,
            status TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 0,
            media_json TEXT NOT NULL,
            version_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (episode_id, node_id, version_id),
            FOREIGN KEY (episode_id)
                REFERENCES canvas_documents(episode_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_canvas_versions_episode_node_sort
            ON canvas_versions(episode_id, node_id, sort_index);

        CREATE INDEX IF NOT EXISTS idx_canvas_versions_episode_active
            ON canvas_versions(episode_id, active);

        CREATE TABLE IF NOT EXISTS canvas_version_identity_refs (
            episode_id TEXT NOT NULL,
            identity TEXT NOT NULL,
            node_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            ref_kind TEXT NOT NULL,
            sort_index INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (episode_id, identity, node_id, version_id, ref_kind),
            FOREIGN KEY (episode_id, node_id, version_id)
                REFERENCES canvas_versions(episode_id, node_id, version_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_canvas_version_identity_refs_episode_identity
            ON canvas_version_identity_refs(episode_id, identity);

        CREATE INDEX IF NOT EXISTS idx_canvas_version_identity_refs_episode_version
            ON canvas_version_identity_refs(episode_id, node_id, version_id);

        CREATE TABLE IF NOT EXISTS canvas_tasks (
            episode_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            status TEXT NOT NULL,
            task_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (episode_id, task_id),
            FOREIGN KEY (episode_id)
                REFERENCES canvas_documents(episode_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_canvas_tasks_episode_node
            ON canvas_tasks(episode_id, node_id);

        CREATE TABLE IF NOT EXISTS canvas_node_source_refs (
            episode_id TEXT NOT NULL,
            source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            ref_kind TEXT NOT NULL,
            sort_index INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (episode_id, source_node_id, target_node_id, ref_kind),
            FOREIGN KEY (episode_id, target_node_id)
                REFERENCES canvas_nodes(episode_id, node_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_canvas_node_source_refs_episode_source
            ON canvas_node_source_refs(episode_id, source_node_id);

        CREATE INDEX IF NOT EXISTS idx_canvas_node_source_refs_episode_target
            ON canvas_node_source_refs(episode_id, target_node_id);

        CREATE TABLE IF NOT EXISTS canvas_runtime_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS canvas_catalog (
            canvas_id TEXT PRIMARY KEY,
            canvas_kind TEXT NOT NULL,
            episode_id TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            storage_key TEXT NOT NULL UNIQUE,
            sort_index INTEGER NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_canvas_catalog_kind_sort
            ON canvas_catalog(canvas_kind, archived, sort_index, updated_at);

        CREATE TABLE IF NOT EXISTS canvas_projection_cache (
            episode_id TEXT NOT NULL,
            cache_key TEXT NOT NULL,
            cache_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            revision INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (episode_id, cache_key),
            FOREIGN KEY (episode_id)
                REFERENCES canvas_documents(episode_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_canvas_projection_cache_episode_type
            ON canvas_projection_cache(episode_id, cache_type);

        CREATE TABLE IF NOT EXISTS canvas_ops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            tx_id TEXT NOT NULL,
            op_type TEXT NOT NULL,
            base_revision INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_canvas_ops_episode_revision
            ON canvas_ops(episode_id, revision);

        """
    )
    for table, columns in {
        "canvas_documents": {
            "extras_json": "TEXT NOT NULL DEFAULT '{}'",
        },
        "canvas_nodes": {
            "position_json": "TEXT NOT NULL DEFAULT '{}'",
            "status": "TEXT NOT NULL DEFAULT ''",
            "data_json": "TEXT NOT NULL DEFAULT '{}'",
        },
        "canvas_edges": {
            "source_node_id": "TEXT NOT NULL DEFAULT ''",
            "target_node_id": "TEXT NOT NULL DEFAULT ''",
            "source_handle": "TEXT NOT NULL DEFAULT ''",
            "target_handle": "TEXT NOT NULL DEFAULT ''",
            "edge_data_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    }.items():
        existing_columns = {
            str(row["name"] or "")
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for column, declaration in columns.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_canvas_nodes_episode_status ON canvas_nodes(episode_id, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_canvas_edges_episode_source ON canvas_edges(episode_id, source_node_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_canvas_edges_episode_target ON canvas_edges(episode_id, target_node_id)"
    )
    op_columns = {
        str(row["name"] or "")
        for row in conn.execute("PRAGMA table_info(canvas_ops)").fetchall()
    }
    if "seq" not in op_columns:
        conn.execute("ALTER TABLE canvas_ops ADD COLUMN seq INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_canvas_ops_episode_seq ON canvas_ops(episode_id, seq)"
    )
    _ensure_canvas_node_source_refs_initialized(conn)
    _ensure_canvas_version_identity_refs_initialized(conn)


def _canvas_document_row(conn: sqlite3.Connection, episode_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT episode_id, schema_version, revision, viewport_json, routes_json,
               work_chains_json, state_json, extras_json, updated_at
        FROM canvas_documents
        WHERE episode_id = ?
        """,
        (episode_id,),
    ).fetchone()


class CanvasRevisionConflict(ValueError):
    """A snapshot was superseded before its transaction could commit."""


def validate_canvas_revision_v4(revision: int, expected_revision: int | str | None) -> None:
    if expected_revision in (None, ""):
        return
    try:
        expected = int(expected_revision)
    except (TypeError, ValueError) as exc:
        raise ValueError("expectedRevision 无效") from exc
    if expected < 0:
        raise ValueError("expectedRevision 无效")
    if expected != revision:
        raise CanvasRevisionConflict("画布版本已变化，请刷新后重试")


def retry_canvas_mutation_v4(
    operation: Callable[[], _MutationResult],
    *,
    expected_revision: int | str | None = None,
) -> _MutationResult:
    """Reread and recompute on conflicts only; an explicit client revision is binding."""
    attempts = _CANVAS_MUTATION_MAX_ATTEMPTS if expected_revision in (None, "") else 1
    for attempt in range(attempts):
        try:
            return operation()
        except CanvasRevisionConflict:
            if attempt == attempts - 1:
                raise
    raise AssertionError("unreachable")


def _canvas_mutation_document_in_conn(
    conn: sqlite3.Connection,
    episode_id: str,
    *,
    now: str,
    expected_revision: int | str | None,
    create_if_missing: bool = False,
) -> sqlite3.Row:
    # Serialize the revision check with the writes, including other processes.
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    document = _canvas_document_row(conn, episode_id)
    if document is None:
        if not create_if_missing or expected_revision not in (None, ""):
            raise FileNotFoundError("画布不存在")
        document = _ensure_canvas_document_in_conn(conn, episode_id, now=now)
    validate_canvas_revision_v4(int(document["revision"] or 0), expected_revision)
    return document


def _workflow_revision(conn: sqlite3.Connection, episode_id: str) -> int:
    row = _canvas_document_row(conn, episode_id)
    return int(row["revision"] or 0) if row is not None else 0


def _ensure_canvas_document_in_conn(
    conn: sqlite3.Connection,
    episode_id: str,
    *,
    now: str,
) -> sqlite3.Row:
    document = _canvas_document_row(conn, episode_id)
    if document is not None:
        return document
    state = {
        "kind": "canvas",
        "reason": "created_by_record_store",
        "sourceReady": False,
        "workChainPlanReady": False,
        "workflowChainReady": False,
        "nextAction": "build_workflow_chain",
    }
    conn.execute(
        """
        INSERT INTO canvas_documents (
            episode_id, schema_version, revision, viewport_json,
            routes_json, work_chains_json, state_json, extras_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            episode_id,
            4,
            0,
            _json_dumps({"x": 0, "y": 0, "zoom": 0.82}),
            _json_dumps([]),
            _json_dumps([]),
            _json_dumps(state),
            _json_dumps({}),
            now,
        ),
    )
    document = _canvas_document_row(conn, episode_id)
    if document is None:
        raise RuntimeError("画布初始化失败")
    return document


def ensure_episode_storage(project_id: str, episode_id: str) -> None:
    canvas_dir(project_id, episode_id).mkdir(parents=True, exist_ok=True)
    (canvas_dir(project_id, episode_id) / "indexes").mkdir(parents=True, exist_ok=True)
    card_root(project_id, episode_id).mkdir(parents=True, exist_ok=True)
