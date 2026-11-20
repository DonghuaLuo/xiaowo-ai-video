#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Agent session persistence service for ai-video."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

from utils.agent_session_sql import AgentSessionRepository, retained_agent_session_ids


NormalizeSession = Callable[[Any, str], dict[str, Any] | None]
SnapshotBuilder = Callable[[str, dict[str, Any]], dict[str, Any]]
RecoverSessions = Callable[[str, list[dict[str, Any]]], list[dict[str, Any]]]
SessionSummary = Callable[[dict[str, Any]], dict[str, Any]]


class AgentSessionService:
    """Coordinates SQL persistence without pulling project business logic into the repo layer."""

    def __init__(
        self,
        *,
        project_dir: Callable[[str], Path],
        normalize_session: NormalizeSession,
        snapshot_from_session: SnapshotBuilder,
        recover_sessions: RecoverSessions,
        summarize_session: SessionSummary,
        lock: Any,
        limit: int = 1000,
    ) -> None:
        self._project_dir = project_dir
        self._normalize_session = normalize_session
        self._snapshot_from_session = snapshot_from_session
        self._recover_sessions = recover_sessions
        self._summarize_session = summarize_session
        self._lock = lock
        self._limit = max(1, int(limit))

    def db_path(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "assistant" / "agent_sessions.sqlite3"

    def repo(self, project_id: str) -> AgentSessionRepository:
        return AgentSessionRepository(self.db_path(project_id))

    def sql_failure(self, project_id: str, action: str, exc: Exception) -> RuntimeError:
        return RuntimeError(f"智能体会话数据库{action}失败：{self.db_path(project_id)}：{exc}")

    def load_snapshot(self, project_id: str, session_id: str) -> dict[str, Any] | None:
        try:
            snapshot = self.repo(project_id).get_session_snapshot(project_id, session_id)
        except Exception as exc:
            raise self.sql_failure(project_id, f"读取 snapshot({session_id})", exc) from exc
        if not isinstance(snapshot, dict):
            return None
        snapshot_session_id = str(snapshot.get("session_id") or snapshot.get("sessionId") or "").strip()
        if snapshot_session_id != str(session_id):
            return None
        return snapshot

    def save_snapshot(
        self,
        project_id: str,
        session_id: str,
        snapshot: dict[str, Any],
        *,
        updated_at: str,
    ) -> None:
        with self._lock:
            try:
                current = self.repo(project_id).get_session_snapshot(project_id, session_id)
                current_session = (current or {}).get("session") or {}
                incoming_session = snapshot.get("session") or {}
                if current_session and (
                    int(incoming_session.get("stateRevision") or 0) != int(current_session.get("stateRevision") or 0)
                    or (incoming_session.get("execution") or {}).get("id") != (current_session.get("execution") or {}).get("id")
                    or incoming_session.get("status") != current_session.get("status")
                ):
                    return
                self.repo(project_id).save_session_snapshot(
                    project_id,
                    session_id,
                    snapshot,
                    updated_at=updated_at,
                )
            except RuntimeError:
                raise
            except Exception as exc:
                raise self.sql_failure(project_id, f"保存 snapshot({session_id})", exc) from exc

    def load_sessions(self, project_id: str) -> list[dict[str, Any]]:
        with self._lock:
            try:
                sessions = self.repo(project_id).list_project_sessions(project_id, limit=self._limit)
                normalized = [
                    row
                    for row in (self._normalize_session(item, project_id) for item in sessions)
                    if isinstance(row, dict)
                ]
                normalized.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
                return self._recover_sessions(project_id, normalized)
            except RuntimeError:
                raise
            except Exception as exc:
                raise self.sql_failure(project_id, "读取", exc) from exc

    def save_sessions(self, project_id: str, sessions: list[dict[str, Any]]) -> None:
        with self._lock:
            try:
                repository = self.repo(project_id)
                previous = {
                    str(row["id"]): self._normalize_session(row, project_id)
                    for row in repository.list_project_sessions(project_id, limit=self._limit)
                }
                normalized = [
                    row
                    for row in (self._normalize_session(item, project_id) for item in sessions)
                    if isinstance(row, dict)
                ]
                for row in normalized:
                    old = previous.get(str(row["id"])) or {}
                    before = {key: value for key, value in old.items() if key != "stateRevision"}
                    after = {key: value for key, value in row.items() if key != "stateRevision"}
                    row["stateRevision"] = int(old.get("stateRevision") or 0) + int(before != after)
                normalized.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
                retained = retained_agent_session_ids(normalized, limit=self._limit)
                kept = [row for row in normalized if row["id"] in retained]
                snapshots = {}
                for session in kept:
                    session_id = str(session.get("id") or "").strip()
                    if not session_id:
                        continue
                    snapshot = self._snapshot_from_session(project_id, session)
                    execution_id = (session.get("execution") or {}).get("id")
                    if session.get("status") == "running" and execution_id:
                        live = repository.get_session_snapshot(project_id, session_id) or {}
                        live_session = live.get("session") or {}
                        if (live.get("status") == "running"
                                and live.get("dispatchExecutionId") == execution_id
                                and (live_session.get("execution") or {}).get("id") == execution_id):
                            # Saving another conversation must not erase this
                            # execution's stages or streaming reply. Session fields
                            # and revisions still come from the fresh snapshot.
                            for key in ("live_activity", "draft_turn", "dispatchExecutionId"):
                                if key in live:
                                    snapshot[key] = copy.deepcopy(live[key])
                    snapshots[session_id] = snapshot
                repository.save_project_sessions(
                    project_id,
                    kept,
                    limit=self._limit,
                    snapshots=snapshots,
                )
                revisions = {row["id"]: row["stateRevision"] for row in kept}
                for row in sessions:
                    if row.get("id") in revisions:
                        row["stateRevision"] = revisions[row["id"]]
            except RuntimeError:
                raise
            except Exception as exc:
                raise self.sql_failure(project_id, "保存", exc) from exc

    def delete_session(self, project_id: str, session_id: str) -> bool:
        with self._lock:
            try:
                return self.repo(project_id).delete_project_session(project_id, session_id)
            except ValueError:
                raise
            except Exception as exc:
                raise self.sql_failure(project_id, "删除", exc) from exc

    def session_summaries(
        self,
        project_id: str,
        episode_id: str | None = None,
    ) -> list[dict[str, Any]]:
        sessions = self.load_sessions(project_id)
        if episode_id:
            sessions = [row for row in sessions if str(row.get("episodeId") or "") == str(episode_id)]
        return [self._summarize_session(row) for row in sessions]
