#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SQLite-backed agent session repository for ai-video."""

from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SESSION_STATUSES = {"idle", "running", "completed", "error", "interrupted"}
MESSAGE_ROLES = {"user", "assistant", "system"}
TURN_TYPES = {"user", "assistant", "system"}
TRANSIENT_ATTACHMENT_KEYS = {
    "apiJpegDataUrl",
    "api_jpeg_data_url",
    "dataUrl",
    "data_url",
    "outputPngDataUrl",
    "pngDataUrl",
    "storedPngDataUrl",
}
SCHEMA_VERSION = 9




def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return copy.deepcopy(default)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return copy.deepcopy(default)


def _clean_status(value: Any) -> str:
    status = str(value or "idle").strip()
    return status if status in SESSION_STATUSES else "idle"


def _clean_role(value: Any) -> str:
    role = str(value or "user").strip()
    return role if role in MESSAGE_ROLES else "user"


def _clean_turn_type(value: Any) -> str:
    turn_type = str(value or "assistant").strip()
    return turn_type if turn_type in TURN_TYPES else "assistant"


def _truthy_flag(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return str(value or "").strip().lower() in {"true", "1", "yes", "y", "on"}


def _text_from_content_blocks(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    rows: list[str] = []
    for block in value:
        if not isinstance(block, dict):
            continue
        if block.get("contextExcluded") or block.get("context_excluded"):
            continue
        if str(block.get("type") or "") in {"source_text", "sourceText", "tool_result"}:
            continue
        text = str(block.get("text") or block.get("content") or block.get("result") or "").strip()
        if text:
            rows.append(text)
    return "\n".join(rows).strip()


def _clean_attachment_ref(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    cleaned = {
        str(key): copy.deepcopy(item)
        for key, item in value.items()
        if str(key) not in TRANSIENT_ATTACHMENT_KEYS
    }
    preview = cleaned.get("preview")
    if isinstance(preview, str) and preview.startswith("data:"):
        cleaned.pop("preview", None)
    media = cleaned.get("media")
    if isinstance(media, dict):
        cleaned_media = _clean_attachment_ref(media)
        if cleaned_media:
            cleaned["media"] = cleaned_media
        else:
            cleaned.pop("media", None)
    return cleaned


def _clean_attachment_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        cleaned = _clean_attachment_ref(item)
        if cleaned:
            rows.append(cleaned)
    return rows






def _delete_session_children(conn: sqlite3.Connection, session_ids: set[str]) -> None:
    cleaned_ids = {str(session_id).strip() for session_id in session_ids if str(session_id).strip()}
    if not cleaned_ids:
        return
    placeholders = ",".join("?" for _ in cleaned_ids)
    params = tuple(sorted(cleaned_ids))
    for table_name in (
        "agent_messages",
        "agent_pending_questions",
        "agent_pending_operations",
        "agent_snapshots",
        "agent_turns",
    ):
        conn.execute(
            f"DELETE FROM {table_name} WHERE session_id IN ({placeholders})",
            params,
        )


def retained_agent_session_ids(sessions: list[dict[str, Any]], *, limit: int) -> set[str]:
    """Apply the visible-conversation limit without evicting its task history."""
    conversations = [row for row in sessions
                     if not (row.get("canvasTask") or {}).get("parentSessionId")]
    retained = {row["id"] for row in conversations[:max(1, int(limit))]}
    for row in sessions:
        metadata = row.get("canvasTask") or {}
        if row.get("status") not in {"error", "interrupted"} and (
            row.get("status") == "running"
            or (row.get("status") == "idle" and metadata.get("starting"))
            or row.get("pendingQuestion") or row.get("pendingOperation")
        ):
            retained.add(row["id"])
            if metadata.get("parentSessionId"):
                retained.add(metadata["parentSessionId"])
    retained.update(row["id"] for row in sessions
                    if (row.get("canvasTask") or {}).get("parentSessionId") in retained)
    return retained


class AgentSessionRepository:
    """Small repository layer for agent session store data."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        self._ensure_schema(conn)
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                episode_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'idle',
                task_id TEXT,
                running_action TEXT,
                history_summary TEXT NOT NULL DEFAULT '',
                steps_json TEXT NOT NULL DEFAULT '[]',
                sdk_session_id TEXT NOT NULL DEFAULT '',
                provider_instance_id TEXT NOT NULL DEFAULT '',
                adapter_id TEXT NOT NULL DEFAULT '',
                tools_used_json TEXT NOT NULL DEFAULT '[]',
                reported_generation_task_ids_json TEXT NOT NULL DEFAULT '[]',
                recent_task_target_json TEXT NOT NULL DEFAULT '{}',
                execution_json TEXT NOT NULL DEFAULT '{}',
                canvas_task_json TEXT NOT NULL DEFAULT '{}',
                state_revision INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_messages (
                id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                content_json TEXT NOT NULL DEFAULT '[]',
                attachments_json TEXT NOT NULL DEFAULT '[]',
                control_only INTEGER NOT NULL DEFAULT 0,
                quick_prompt_id TEXT NOT NULL DEFAULT '',
                execution_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                PRIMARY KEY(session_id, id),
                FOREIGN KEY(session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS agent_pending_questions (
                session_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS agent_pending_operations (
                session_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS agent_snapshots (
                session_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS agent_turns (
                id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                turn_type TEXT NOT NULL DEFAULT 'assistant',
                text TEXT NOT NULL,
                content_json TEXT NOT NULL DEFAULT '[]',
                attachments_json TEXT NOT NULL DEFAULT '[]',
                control_only INTEGER NOT NULL DEFAULT 0,
                quick_prompt_id TEXT NOT NULL DEFAULT '',
                execution_message TEXT NOT NULL DEFAULT '',
                timestamp TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                PRIMARY KEY(session_id, id),
                FOREIGN KEY(session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
            );
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_sessions)")}
        if "canvas_task_json" not in columns:
            conn.execute("ALTER TABLE agent_sessions ADD COLUMN canvas_task_json TEXT NOT NULL DEFAULT '{}'")
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_agent_sessions_project_updated
                ON agent_sessions(project_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_sessions_project_episode
                ON agent_sessions(project_id, episode_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_sessions_status
                ON agent_sessions(status);
            CREATE INDEX IF NOT EXISTS idx_agent_messages_session
                ON agent_messages(session_id, ordinal);
            CREATE INDEX IF NOT EXISTS idx_agent_pending_project
                ON agent_pending_questions(project_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_pending_operations_project
                ON agent_pending_operations(project_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_snapshots_project
                ON agent_snapshots(project_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_turns_session
                ON agent_turns(session_id, ordinal);
            """
        )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()

    def list_project_sessions(self, project_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute(
                """
                SELECT s.*,
                  EXISTS(SELECT 1 FROM agent_pending_questions q WHERE q.session_id = s.id) AS has_question,
                  EXISTS(SELECT 1 FROM agent_pending_operations p WHERE p.session_id = s.id) AS has_operation
                FROM agent_sessions s WHERE project_id = ?
                ORDER BY updated_at DESC
                """,
                (project_id,),
            ).fetchall()
            retained = retained_agent_session_ids([
                {"id": row["id"], "status": row["status"],
                 "canvasTask": _json_loads(row["canvas_task_json"], {}),
                 "pendingQuestion": bool(row["has_question"]),
                 "pendingOperation": bool(row["has_operation"])} for row in rows
            ], limit=limit)
            return [self._session_from_row(conn, row) for row in rows if row["id"] in retained]

    def save_project_sessions(
        self,
        project_id: str,
        sessions: list[dict[str, Any]],
        *,
        limit: int = 1000,
        snapshots: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        kept_sessions = list(sessions)
        with self._session() as conn:
            for session in kept_sessions:
                self._upsert_session(conn, project_id, session)
                session_id = str(session.get("id") or "").strip()
                snapshot = (snapshots or {}).get(session_id)
                if isinstance(snapshot, dict):
                    updated_at = str(session.get("updatedAt") or session.get("updated_at") or "")
                    self._upsert_snapshot(conn, project_id, session_id, snapshot, updated_at=updated_at)

    def delete_project_session(self, project_id: str, session_id: str) -> bool:
        with self._session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT id FROM agent_sessions WHERE project_id = ? AND id = ?",
                (project_id, session_id),
            ).fetchone()
            if not existing:
                return False
            session_ids = {session_id}
            children = conn.execute(
                """SELECT id, status, canvas_task_json,
                   EXISTS(SELECT 1 FROM agent_pending_questions q WHERE q.session_id = s.id) AS has_question,
                   EXISTS(SELECT 1 FROM agent_pending_operations p WHERE p.session_id = s.id) AS has_operation
                   FROM agent_sessions s WHERE project_id = ?""",
                (project_id,),
            ).fetchall()
            for child in children:
                metadata = _json_loads(child["canvas_task_json"], {})
                if metadata.get("parentSessionId") != session_id:
                    continue
                if child["status"] not in {"error", "interrupted"} and (
                    child["status"] == "running"
                    or (child["status"] == "idle" and metadata.get("starting"))
                    or child["has_question"] or child["has_operation"]
                ):
                    raise ValueError("此画布会话还有执行中或待处理的任务，请处理后再删除")
                session_ids.add(child["id"])
            placeholders = ",".join("?" for _ in session_ids)
            params = tuple(sorted(session_ids))
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'agent_candidates'").fetchone():
                committing = conn.execute(
                    f"""SELECT 1 FROM agent_candidates WHERE project_id = ?
                        AND owner_session_id IN ({placeholders})
                        AND status IN ('committing', 'commit_unknown') LIMIT 1""",
                    (project_id, *params),
                ).fetchone()
                if committing:
                    raise ValueError("会话有正在提交的候选，请等待提交状态核实后再删除")
            _delete_session_children(conn, session_ids)
            cursor = conn.execute(
                f"DELETE FROM agent_sessions WHERE project_id = ? AND id IN ({placeholders})",
                (project_id, *params),
            )
            return cursor.rowcount > 0

    def save_session_snapshot(
        self,
        project_id: str,
        session_id: str,
        snapshot: dict[str, Any],
        *,
        updated_at: str,
    ) -> None:
        with self._session() as conn:
            self._upsert_snapshot(conn, project_id, session_id, snapshot, updated_at=updated_at)

    def get_session_snapshot(self, project_id: str, session_id: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM agent_snapshots
                WHERE project_id = ? AND session_id = ?
                """,
                (project_id, session_id),
            ).fetchone()
            if not row:
                return self._snapshot_from_sql_state(conn, project_id, session_id)
            payload = _json_loads(row["payload_json"], None)
            if not isinstance(payload, dict):
                return self._snapshot_from_sql_state(conn, project_id, session_id)
            payload_session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
            if payload_session_id and payload_session_id != str(session_id):
                return self._snapshot_from_sql_state(conn, project_id, session_id)

            snapshot = copy.deepcopy(payload)
            current = self._snapshot_from_sql_state(conn, project_id, session_id)
            if current and int((snapshot.get("session") or {}).get("stateRevision") or 0) < int((current.get("session") or {}).get("stateRevision") or 0):
                return current
            snapshot.setdefault("session_id", str(session_id))
            session = snapshot.get("session")
            if not isinstance(session, dict):
                sql_snapshot = self._snapshot_from_sql_state(conn, project_id, session_id)
                if sql_snapshot is None:
                    return snapshot
                snapshot["session"] = sql_snapshot["session"]
                if not isinstance(snapshot.get("pending_questions"), list):
                    snapshot["pending_questions"] = sql_snapshot["pending_questions"]
                if not str(snapshot.get("status") or "").strip():
                    snapshot["status"] = sql_snapshot["status"]
            turns = snapshot.get("turns")
            if not isinstance(turns, list) or not turns:
                sql_turns = self._turns_from_rows(conn, session_id)
                if not sql_turns:
                    sql_session = self._session_from_id(conn, project_id, session_id)
                    sql_turns = self._turns_from_messages(sql_session.get("messages") if sql_session else [])
                if sql_turns:
                    snapshot["turns"] = sql_turns
            snapshot.setdefault("turns", [])
            snapshot.setdefault("draft_turn", None)
            snapshot.setdefault("pending_questions", [])
            return snapshot

    def _upsert_session(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        session: dict[str, Any],
    ) -> None:
        session_id = str(session.get("id") or "").strip()
        if not session_id:
            return
        created_at = str(session.get("createdAt") or session.get("created_at") or "")
        updated_at = str(session.get("updatedAt") or session.get("updated_at") or created_at)
        episode_id = str(session.get("episodeId") or session.get("episode_id") or "E01").strip() or "E01"
        values = (
            project_id,
            episode_id,
            str(session.get("title") or "新会话").strip() or "新会话",
            _clean_status(session.get("status")),
            str(session.get("taskId") or session.get("task_id") or "").strip() or None,
            str(session.get("runningAction") or session.get("running_action") or "").strip() or None,
            str(session.get("historySummary") or session.get("history_summary") or "").strip(),
            _json_dumps(session.get("steps") if isinstance(session.get("steps"), list) else []),
            str(session.get("sdkSessionId") or session.get("sdk_session_id") or "").strip(),
            str(session.get("providerInstanceId") or session.get("provider_instance_id") or "").strip(),
            str(session.get("adapterId") or session.get("adapter_id") or "").strip(),
            _json_dumps(session.get("toolsUsed") if isinstance(session.get("toolsUsed"), list) else []),
            _json_dumps(session.get("reportedGenerationTaskIds") if isinstance(session.get("reportedGenerationTaskIds"), list) else []),
            _json_dumps(session.get("recentTaskTarget") if isinstance(session.get("recentTaskTarget"), dict) else {}),
            _json_dumps(session.get("execution") or {}),
            _json_dumps(session.get("canvasTask") or {}),
            int(session.get("stateRevision") or 0),
            updated_at or created_at,
            session_id,
        )
        existing = conn.execute(
            "SELECT id FROM agent_sessions WHERE id = ? LIMIT 1",
            (session_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE agent_sessions
                SET project_id = ?, episode_id = ?, title = ?, status = ?,
                    task_id = ?, running_action = ?, history_summary = ?,
                    steps_json = ?, sdk_session_id = ?, provider_instance_id = ?,
                    adapter_id = ?, tools_used_json = ?,
                    reported_generation_task_ids_json = ?, recent_task_target_json = ?,
                    execution_json = ?, canvas_task_json = ?, state_revision = ?, updated_at = ?
                WHERE id = ?
                """,
                values,
            )
        else:
            conn.execute(
                """
                INSERT INTO agent_sessions(
                    project_id, episode_id, title, status, task_id,
                    running_action, history_summary, steps_json,
                    sdk_session_id, provider_instance_id, adapter_id,
                    tools_used_json, reported_generation_task_ids_json, recent_task_target_json,
                    execution_json, canvas_task_json, state_revision, updated_at, id, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*values, created_at or updated_at),
            )
        conn.execute("DELETE FROM agent_messages WHERE session_id = ?", (session_id,))
        seen_message_ids: set[str] = set()
        for ordinal, message in enumerate(session.get("messages") or []):
            if not isinstance(message, dict):
                continue
            message_id = str(message.get("id") or "").strip()
            content = message.get("content") if isinstance(message.get("content"), list) else []
            text = str(message.get("text") or "").strip() or _text_from_content_blocks(content)
            if not message_id or (not text and not content):
                continue
            if message_id in seen_message_ids:
                message_id = f"{message_id}-{ordinal}"
            seen_message_ids.add(message_id)
            attachments = _clean_attachment_refs(message.get("attachments"))
            role = _clean_role(message.get("role"))
            conn.execute(
                """
                INSERT INTO agent_messages(
                    id, session_id, project_id, role, text, content_json,
                    attachments_json, control_only, quick_prompt_id,
                    execution_message, created_at, ordinal
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    session_id,
                    project_id,
                    role,
                    text,
                    _json_dumps(content),
                    _json_dumps(attachments),
                    1 if role == "user" and _truthy_flag(message.get("controlOnly") or message.get("control_only")) else 0,
                    str(message.get("quickPromptId") or message.get("quick_prompt_id") or "").strip(),
                    str(message.get("executionMessage") or message.get("execution_message") or "").strip(),
                    str(message.get("createdAt") or message.get("created_at") or updated_at or created_at),
                    ordinal,
                ),
            )
        conn.execute("DELETE FROM agent_pending_questions WHERE session_id = ?", (session_id,))
        pending = session.get("pendingQuestion") or session.get("pending_question")
        if isinstance(pending, dict):
            question_id = str(
                pending.get("questionId")
                or pending.get("question_id")
                or ""
            ).strip()
            if question_id:
                conn.execute(
                    """
                    INSERT INTO agent_pending_questions(
                        session_id, project_id, question_id, payload_json, created_at, updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        project_id,
                        question_id,
                        _json_dumps(pending),
                        updated_at or created_at,
                        updated_at or created_at,
                    ),
                )
        conn.execute("DELETE FROM agent_pending_operations WHERE session_id = ?", (session_id,))
        pending_operation = session.get("pendingOperation") or session.get("pending_operation")
        if isinstance(pending_operation, dict):
            operation_type = str(
                pending_operation.get("type")
                or pending_operation.get("operationType")
                or pending_operation.get("operation_type")
                or ""
            ).strip()
            if operation_type:
                conn.execute(
                    """
                    INSERT INTO agent_pending_operations(
                        session_id, project_id, operation_type, payload_json, created_at, updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        project_id,
                        operation_type,
                        _json_dumps(pending_operation),
                        updated_at or created_at,
                        updated_at or created_at,
                    ),
                )

    def _upsert_snapshot(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        session_id: str,
        snapshot: dict[str, Any],
        *,
        updated_at: str,
    ) -> None:
        if not session_id:
            return
        timestamp = str(updated_at or "")
        existing = conn.execute(
            "SELECT created_at FROM agent_snapshots WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        created_at = str(existing["created_at"]) if existing else timestamp
        payload_json = _json_dumps(snapshot)
        if existing:
            conn.execute(
                """
                UPDATE agent_snapshots
                SET project_id = ?, payload_json = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (project_id, payload_json, timestamp, session_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO agent_snapshots(session_id, project_id, payload_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (session_id, project_id, payload_json, created_at, timestamp),
            )

        self._replace_turns(conn, project_id, session_id, snapshot)

    def _replace_turns(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        session_id: str,
        snapshot: dict[str, Any],
    ) -> None:
        conn.execute("DELETE FROM agent_turns WHERE session_id = ?", (session_id,))
        turns = snapshot.get("turns") if isinstance(snapshot.get("turns"), list) else []
        seen_turn_ids: set[str] = set()
        for ordinal, turn in enumerate(turns):
            if not isinstance(turn, dict):
                continue
            turn_id = str(turn.get("uuid") or turn.get("id") or "").strip()
            if not turn_id:
                turn_id = f"turn-{ordinal + 1}"
            if turn_id in seen_turn_ids:
                turn_id = f"{turn_id}-{ordinal}"
            seen_turn_ids.add(turn_id)
            content = turn.get("content") if isinstance(turn.get("content"), list) else []
            text = str(turn.get("text") or "").strip() or _text_from_content_blocks(content)
            if not text and not content:
                continue
            turn_type = _clean_turn_type(turn.get("type") or turn.get("role"))
            conn.execute(
                """
                INSERT INTO agent_turns(
                    id, session_id, project_id, turn_type, text, content_json,
                    attachments_json, control_only, quick_prompt_id,
                    execution_message, timestamp, ordinal
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    session_id,
                    project_id,
                    turn_type,
                    text,
                    _json_dumps(content),
                    _json_dumps(_clean_attachment_refs(turn.get("attachments"))),
                    1 if turn_type == "user" and _truthy_flag(turn.get("controlOnly") or turn.get("control_only")) else 0,
                    str(turn.get("quickPromptId") or turn.get("quick_prompt_id") or "").strip(),
                    str(turn.get("executionMessage") or turn.get("execution_message") or "").strip(),
                    str(turn.get("timestamp") or turn.get("createdAt") or turn.get("created_at") or ""),
                    ordinal,
                ),
            )

    def _turns_from_rows(
        self,
        conn: sqlite3.Connection,
        session_id: str,
    ) -> list[dict[str, Any]]:
        turns: list[dict[str, Any]] = []
        for turn_row in conn.execute(
            """
            SELECT * FROM agent_turns
            WHERE session_id = ?
            ORDER BY ordinal ASC, timestamp ASC, id ASC
            """,
            (session_id,),
        ).fetchall():
            text = str(turn_row["text"] or "")
            content = _json_loads(turn_row["content_json"], [])
            turn: dict[str, Any] = {
                "type": _clean_turn_type(turn_row["turn_type"]),
                "uuid": str(turn_row["id"]),
                "timestamp": str(turn_row["timestamp"] or ""),
                "text": text,
                "content": content if isinstance(content, list) and content else (
                    [{"type": "text", "text": text}] if text else []
                ),
            }
            attachments = _json_loads(turn_row["attachments_json"], [])
            if isinstance(attachments, list) and attachments:
                turn["attachments"] = attachments
            if _truthy_flag(turn_row["control_only"]) and turn["type"] == "user":
                turn["controlOnly"] = True
            quick_prompt_id = str(turn_row["quick_prompt_id"] or "").strip()
            if quick_prompt_id:
                turn["quickPromptId"] = quick_prompt_id
            execution_message = str(turn_row["execution_message"] or "").strip()
            if execution_message:
                turn["executionMessage"] = execution_message
            turns.append(turn)
        return turns

    @staticmethod
    def _turns_from_messages(messages: Any) -> list[dict[str, Any]]:
        if not isinstance(messages, list):
            return []
        turns: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            text = str(message.get("text") or "").strip()
            content = message.get("content") if isinstance(message.get("content"), list) else []
            if not content and text:
                content = [{"type": "text", "text": text}]
            if not text and not content:
                continue
            turn: dict[str, Any] = {
                "type": _clean_turn_type(message.get("role")),
                "uuid": str(message.get("id") or f"turn-{index + 1}"),
                "timestamp": str(message.get("createdAt") or message.get("created_at") or ""),
                "text": text or _text_from_content_blocks(content),
                "content": content,
            }
            attachments = _clean_attachment_refs(message.get("attachments"))
            if attachments:
                turn["attachments"] = attachments
            if _truthy_flag(message.get("controlOnly") or message.get("control_only")) and turn["type"] == "user":
                turn["controlOnly"] = True
            quick_prompt_id = str(message.get("quickPromptId") or message.get("quick_prompt_id") or "").strip()
            if quick_prompt_id:
                turn["quickPromptId"] = quick_prompt_id
            execution_message = str(message.get("executionMessage") or message.get("execution_message") or "").strip()
            if execution_message:
                turn["executionMessage"] = execution_message
            turns.append(turn)
        return turns

    def _session_from_id(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT * FROM agent_sessions
            WHERE project_id = ? AND id = ?
            """,
            (project_id, session_id),
        ).fetchone()
        if not row:
            return None
        return self._session_from_row(conn, row)

    def _snapshot_from_sql_state(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        session = self._session_from_id(conn, project_id, session_id)
        if not session:
            return None
        turns = self._turns_from_rows(conn, session_id)
        if not turns:
            turns = self._turns_from_messages(session.get("messages"))
        pending = session.get("pendingQuestion") if _clean_status(session.get("status")) == "running" else None
        pending_operation = session.get("pendingOperation")
        return {
            "session_id": session_id,
            "status": _clean_status(session.get("status")),
            "turns": turns,
            "draft_turn": None,
            "pending_questions": [pending] if isinstance(pending, dict) else [],
            "pending_operations": [pending_operation] if isinstance(pending_operation, dict) else [],
            "session": session,
        }

    def _session_from_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        session_id = str(row["id"])
        messages = []
        for message_row in conn.execute(
            """
            SELECT * FROM agent_messages
            WHERE session_id = ?
            ORDER BY ordinal ASC, created_at ASC, id ASC
            """,
            (session_id,),
        ).fetchall():
            message: dict[str, Any] = {
                "id": str(message_row["id"]),
                "role": _clean_role(message_row["role"]),
                "text": str(message_row["text"] or ""),
                "createdAt": str(message_row["created_at"] or ""),
            }
            content = _json_loads(message_row["content_json"], [])
            if isinstance(content, list) and content:
                message["content"] = content
            attachments = _json_loads(message_row["attachments_json"], [])
            if isinstance(attachments, list) and attachments:
                message["attachments"] = attachments
            if _truthy_flag(message_row["control_only"]) and message["role"] == "user":
                message["controlOnly"] = True
            quick_prompt_id = str(message_row["quick_prompt_id"] or "").strip()
            if quick_prompt_id:
                message["quickPromptId"] = quick_prompt_id
            execution_message = str(message_row["execution_message"] or "").strip()
            if execution_message:
                message["executionMessage"] = execution_message
            messages.append(message)
        session: dict[str, Any] = {
            "id": session_id,
            "title": str(row["title"] or "新会话"),
            "episodeId": str(row["episode_id"] or "E01"),
            "status": _clean_status(row["status"]),
            "createdAt": str(row["created_at"] or ""),
            "updatedAt": str(row["updated_at"] or ""),
            "messages": messages,
            "steps": _json_loads(row["steps_json"], []),
            "execution": _json_loads(row["execution_json"], {}),
            "canvasTask": _json_loads(row["canvas_task_json"], {}),
            "stateRevision": int(row["state_revision"] or 0),
        }
        history_summary = str(row["history_summary"] or "").strip()
        if history_summary:
            session["historySummary"] = history_summary
        sdk_session_id = str(row["sdk_session_id"] or "").strip()
        if sdk_session_id:
            session["sdkSessionId"] = sdk_session_id
        provider_instance_id = str(row["provider_instance_id"] or "").strip()
        if provider_instance_id:
            session["providerInstanceId"] = provider_instance_id
        adapter_id = str(row["adapter_id"] or "").strip()
        if adapter_id:
            session["adapterId"] = adapter_id
        tools_used = _json_loads(row["tools_used_json"], [])
        if isinstance(tools_used, list) and tools_used:
            session["toolsUsed"] = [str(item) for item in tools_used if str(item or "").strip()]
        reported_task_ids = _json_loads(row["reported_generation_task_ids_json"], [])
        if isinstance(reported_task_ids, list):
            session["reportedGenerationTaskIds"] = reported_task_ids
        recent_task_target = _json_loads(row["recent_task_target_json"], {})
        if isinstance(recent_task_target, dict) and recent_task_target:
            session["recentTaskTarget"] = recent_task_target
        task_id = str(row["task_id"] or "").strip()
        if task_id:
            session["taskId"] = task_id
        running_action = str(row["running_action"] or "").strip()
        if running_action:
            session["runningAction"] = running_action
        pending_row = conn.execute(
            "SELECT payload_json FROM agent_pending_questions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if pending_row:
            pending = _json_loads(pending_row["payload_json"], None)
            if isinstance(pending, dict):
                session["pendingQuestion"] = pending
        pending_operation_row = conn.execute(
            "SELECT payload_json FROM agent_pending_operations WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if pending_operation_row:
            pending_operation = _json_loads(pending_operation_row["payload_json"], None)
            if isinstance(pending_operation, dict):
                session["pendingOperation"] = pending_operation
        return session
