"""Durable, session-owned creative runs and immutable result candidates."""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(proposal: dict[str, Any], commit_payload: dict[str, Any]) -> str:
    return hashlib.sha256(_json({"proposal": proposal, "commitPayload": commit_payload}).encode("utf-8")).hexdigest()


@contextmanager
def _database(project_id: str) -> Iterator[sqlite3.Connection]:
    from .agent_sessions import _agent_sessions_db_path

    path = _agent_sessions_db_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            owner_session_id TEXT NOT NULL,
            owner_scope TEXT NOT NULL,
            owner_episode_id TEXT NOT NULL,
            task_type TEXT NOT NULL,
            target_key TEXT NOT NULL,
            status TEXT NOT NULL,
            requirement_text TEXT NOT NULL DEFAULT '',
            requirement_feedback_json TEXT NOT NULL DEFAULT '[]',
            requirement_revision INTEGER NOT NULL DEFAULT 1,
            latest_candidate_id TEXT NOT NULL DEFAULT '',
            commit_receipt_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(owner_session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_agent_runs_session
            ON agent_runs(project_id, owner_session_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS agent_candidates (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            owner_session_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            digest TEXT NOT NULL,
            status TEXT NOT NULL,
            proposal_json TEXT NOT NULL,
            commit_payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES agent_runs(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_agent_candidates_session
            ON agent_candidates(project_id, owner_session_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS agent_run_events (
            run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            project_id TEXT NOT NULL,
            owner_session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(run_id, sequence),
            FOREIGN KEY(run_id) REFERENCES agent_runs(id) ON DELETE CASCADE
        );
    """)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _event(connection: sqlite3.Connection, project_id: str, session_id: str, run_id: str,
           kind: str, payload: dict[str, Any]) -> None:
    sequence = connection.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_run_events WHERE run_id = ?", (run_id,)
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO agent_run_events VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, sequence, project_id, session_id, kind, _json(payload), _now()),
    )


def _candidate_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "candidateId": row["id"], "runId": row["run_id"],
        "projectId": row["project_id"], "sessionId": row["owner_session_id"],
        "version": row["version"], "digest": row["digest"], "status": row["status"],
        "proposal": json.loads(row["proposal_json"]),
        "commitPayload": json.loads(row["commit_payload_json"]),
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        "requirementText": row["requirement_text"] if "requirement_text" in row.keys() else "",
        "revisionFeedback": json.loads(row["requirement_feedback_json"])
        if "requirement_feedback_json" in row.keys() else [],
    }


def stage_episode_candidate(project_id: str, session_id: str, proposal: dict[str, Any],
                            commit_payload: dict[str, Any], requirement_text: str = "") -> dict[str, Any]:
    candidate_id = str(proposal.get("proposalId") or "").strip()
    if not session_id or not candidate_id:
        raise ValueError("分集候选缺少所属会话或候选编号")
    target_key = f"episode_boundary:{proposal.get('sourceId')}:{proposal.get('startOffset')}"
    digest = _digest(proposal, commit_payload)
    now = _now()
    with _database(project_id) as connection:
        session = connection.execute(
            "SELECT project_id, episode_id FROM agent_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session is None or session["project_id"] not in {project_id, ""} or session["episode_id"] != "__project__":
            raise ValueError("分集候选只能保存到发起任务的项目会话")
        existing = connection.execute("SELECT * FROM agent_candidates WHERE id = ?", (candidate_id,)).fetchone()
        if existing is not None:
            if existing["owner_session_id"] != session_id or existing["digest"] != digest:
                raise ValueError("候选编号已被其他会话或不同内容占用")
            return {"runId": existing["run_id"], "candidateId": candidate_id,
                    "candidateDigest": existing["digest"], "candidateVersion": existing["version"],
                    "status": existing["status"]}
        run = connection.execute(
            """SELECT * FROM agent_runs WHERE project_id = ? AND owner_session_id = ?
               AND task_type = 'episode_boundary_propose' AND target_key = ?
               AND status IN ('running', 'awaiting_confirmation', 'superseded') ORDER BY updated_at DESC LIMIT 1""",
            (project_id, session_id, target_key),
        ).fetchone()
        run_id = str(run["id"]) if run else f"agent-run-{uuid.uuid4().hex}"
        version = 1
        if run:
            version = connection.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM agent_candidates WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            feedback = json.loads(run["requirement_feedback_json"] or "[]")
            if requirement_text and requirement_text != run["requirement_text"]:
                feedback.append(requirement_text)
            connection.execute(
                """UPDATE agent_candidates SET status = 'superseded', updated_at = ?
                   WHERE run_id = ? AND status = 'awaiting_confirmation'""", (now, run_id),
            )
            connection.execute(
                """UPDATE agent_runs SET status = 'awaiting_confirmation', latest_candidate_id = ?,
                   requirement_feedback_json = ?, requirement_revision = requirement_revision + ?,
                   updated_at = ? WHERE id = ?""",
                (candidate_id, _json(feedback[-12:]),
                 int(bool(requirement_text and requirement_text != run["requirement_text"])), now, run_id),
            )
        else:
            connection.execute(
                """INSERT INTO agent_runs (id, project_id, owner_session_id, owner_scope, owner_episode_id,
                   task_type, target_key, status, requirement_text, latest_candidate_id, created_at, updated_at)
                   VALUES (?, ?, ?, 'project', '__project__', 'episode_boundary_propose', ?,
                   'awaiting_confirmation', ?, ?, ?, ?)""",
                (run_id, project_id, session_id, target_key, requirement_text, candidate_id, now, now),
            )
        connection.execute(
            """INSERT INTO agent_candidates (id, run_id, project_id, owner_session_id, version,
               digest, status, proposal_json, commit_payload_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'awaiting_confirmation', ?, ?, ?, ?)""",
            (candidate_id, run_id, project_id, session_id, version, digest,
             _json(proposal), _json(commit_payload), now, now),
        )
        _event(connection, project_id, session_id, run_id, "candidate_ready",
               {"candidateId": candidate_id, "version": version, "digest": digest})
    return {"runId": run_id, "candidateId": candidate_id, "candidateDigest": digest,
            "candidateVersion": version, "status": "awaiting_confirmation"}


def get_episode_candidate(project_id: str, session_id: str | None,
                          candidate_id: str | None = None) -> dict[str, Any] | None:
    if not session_id:
        return None
    with _database(project_id) as connection:
        if candidate_id:
            row = connection.execute(
                """SELECT c.*, r.requirement_text, r.requirement_feedback_json FROM agent_candidates c JOIN agent_runs r ON r.id = c.run_id
                   WHERE c.project_id = ? AND c.owner_session_id = ? AND c.id = ?
                   AND r.task_type = 'episode_boundary_propose'""",
                (project_id, session_id, candidate_id),
            ).fetchone()
        else:
            row = connection.execute(
                """SELECT c.*, r.requirement_text, r.requirement_feedback_json FROM agent_candidates c JOIN agent_runs r ON r.id = c.run_id
                   WHERE c.project_id = ? AND c.owner_session_id = ?
                   AND r.task_type = 'episode_boundary_propose'
                   AND c.status IN ('awaiting_confirmation', 'committing', 'commit_unknown')
                   ORDER BY c.created_at DESC LIMIT 1""", (project_id, session_id),
            ).fetchone()
        return _candidate_row(row)


def list_open_episode_candidates(project_id: str, session_id: str | None) -> list[dict[str, Any]]:
    if not session_id:
        return []
    with _database(project_id) as connection:
        rows = connection.execute(
            """SELECT c.*, r.requirement_text, r.requirement_feedback_json FROM agent_candidates c JOIN agent_runs r ON r.id = c.run_id
               WHERE c.project_id = ? AND c.owner_session_id = ?
               AND r.task_type = 'episode_boundary_propose'
               AND c.status IN ('awaiting_confirmation', 'committing', 'commit_unknown')
               ORDER BY c.created_at DESC, c.id DESC""", (project_id, session_id),
        ).fetchall()
    return [candidate for row in rows if (candidate := _candidate_row(row))]


def refresh_episode_candidate_freshness(project_id: str, session_id: str | None,
                                        candidate_id: str | None = None) -> dict[str, Any] | None:
    from .project_resource_revisions import _json_hash, _resource_revision_value
    from .source_coverage import _load_source_coverage

    saved = get_episode_candidate(project_id, session_id, candidate_id)
    if not saved or saved["status"] != "awaiting_confirmation":
        return saved
    guard = saved["commitPayload"]
    coverage = _load_source_coverage(project_id)
    try:
        fresh = (_resource_revision_value(coverage) == int(guard.get("expectedRevision"))
                 and _json_hash(coverage) == str(guard.get("baseHash") or ""))
    except (TypeError, ValueError):
        fresh = False
    if fresh:
        return saved
    try:
        change_episode_candidate_status(project_id, str(session_id), saved["candidateId"], "stale",
                                        expected_digest=saved["digest"])
    except ValueError:
        # A concurrent verified commit may have moved this candidate to
        # committing/committed after we read its old revision.
        return get_episode_candidate(project_id, session_id, saved["candidateId"])
    return None


def session_candidate_statuses(project_id: str, session_id: str) -> dict[str, dict[str, Any]]:
    for candidate in list_open_episode_candidates(project_id, session_id):
        if candidate["status"] == "awaiting_confirmation":
            refresh_episode_candidate_freshness(project_id, session_id, candidate["candidateId"])
    with _database(project_id) as connection:
        rows = connection.execute(
            """SELECT c.id, c.run_id, c.status, c.digest, c.version FROM agent_candidates c
               JOIN agent_runs r ON r.id = c.run_id WHERE c.project_id = ? AND c.owner_session_id = ?
               AND r.task_type = 'episode_boundary_propose'""",
            (project_id, session_id),
        ).fetchall()
    return {row["id"]: {"runId": row["run_id"], "status": row["status"],
                        "candidateDigest": row["digest"], "candidateVersion": row["version"]} for row in rows}


def session_open_candidate_counts(project_id: str) -> dict[str, int]:
    with _database(project_id) as connection:
        rows = connection.execute(
            """SELECT owner_session_id, COUNT(*) AS candidate_count FROM agent_candidates
               WHERE project_id = ? AND status IN ('awaiting_confirmation', 'committing', 'commit_unknown')
               GROUP BY owner_session_id""", (project_id,),
        ).fetchall()
    return {row["owner_session_id"]: int(row["candidate_count"]) for row in rows}


def session_latest_stale_candidate_ids(project_id: str, session_id: str | None) -> dict[str, str]:
    """每种确认型任务只保留最近一条失效候选，用于解释不能再确认的原因。"""
    if not session_id:
        return {}
    with _database(project_id) as connection:
        rows = connection.execute(
            """SELECT c.id, c.status, r.task_type FROM agent_candidates c
               JOIN agent_runs r ON r.id = c.run_id
               WHERE c.project_id = ? AND c.owner_session_id = ?
               AND r.task_type IN ('episode_boundary_propose', 'asset_range_propose')
               ORDER BY c.created_at DESC, c.id DESC""",
            (project_id, session_id),
        ).fetchall()
    latest: dict[str, str] = {}
    seen: set[str] = set()
    for row in rows:
        task_type = str(row["task_type"])
        if task_type in seen:
            continue
        seen.add(task_type)
        if row["status"] == "stale":
            latest[task_type] = str(row["id"])
    return latest


def project_session_candidate_messages(project_id: str, session_id: str,
                                       messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project persisted candidate state into this session's conversation view."""
    statuses = session_candidate_statuses(project_id, session_id)
    active = get_episode_candidate(project_id, session_id)
    result = copy.deepcopy(messages)
    seen: set[str] = set()
    display_status = {
        "awaiting_confirmation": "pending_confirmation",
        "committing": "committing",
        "commit_unknown": "commit_unknown",
        "committed": "committed",
        "superseded": "superseded",
        "cancelled": "cancelled",
        "stale": "stale",
    }
    for message in result:
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "episode_boundary_candidate":
                continue
            candidate_id = str(block.get("candidateId") or "")
            status = statuses.get(candidate_id)
            if status:
                seen.add(candidate_id)
                block["status"] = display_status.get(status["status"], "stale")
                block["runId"] = status["runId"]
                block["candidateDigest"] = status["candidateDigest"]
                block["candidateVersion"] = status["candidateVersion"]
            else:
                block["status"] = "stale"
    if active and active["candidateId"] not in seen:
        proposal = active["proposal"]
        card = {
            "type": "episode_boundary_candidate", "candidateId": active["candidateId"],
            "runId": active["runId"], "candidateDigest": active["digest"],
            "candidateVersion": active["version"],
            "status": display_status.get(active["status"], "stale"),
            "episodeId": str(proposal.get("episodeId") or ""),
            "title": str(proposal.get("episodeTitle") or proposal.get("title") or ""),
            "startOffset": proposal.get("startOffset"),
            "endOffset": proposal.get("recommendedEndOffset"),
            "targetUnits": proposal.get("targetUnits"),
            "actualUnits": proposal.get("actualUnits"),
            "boundaryEndText": str(proposal.get("boundaryEndText") or ""),
            "reason": str(proposal.get("reason") or ""),
            "riskNotes": proposal.get("riskNotes") if isinstance(proposal.get("riskNotes"), list) else [],
        }
        result.append({"id": f"candidate-{active['candidateId']}", "role": "assistant",
                       "text": "分集候选已准备，请审阅。", "content": [card],
                       "createdAt": active["createdAt"]})
    return result


def change_episode_candidate_status(project_id: str, session_id: str, candidate_id: str,
                                    status: str, *, expected_digest: str | None = None,
                                    receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    if status not in {"awaiting_confirmation", "committing", "commit_unknown", "committed", "cancelled", "stale", "superseded"}:
        raise ValueError("未知候选状态")
    with _database(project_id) as connection:
        row = connection.execute(
            "SELECT * FROM agent_candidates WHERE project_id = ? AND owner_session_id = ? AND id = ?",
            (project_id, session_id, candidate_id),
        ).fetchone()
        if row is None or (expected_digest and row["digest"] != expected_digest):
            raise ValueError("候选版本已变化，请重新审阅")
        if row["status"] == "committed" and status == "committed":
            return _candidate_row(row) or {}
        allowed = {
            "awaiting_confirmation": {"committing", "cancelled", "stale", "superseded"},
            "committing": {"committed", "commit_unknown", "awaiting_confirmation", "stale"},
            "commit_unknown": {"committed", "awaiting_confirmation", "stale"},
        }
        if row["status"] != status and status not in allowed.get(row["status"], set()):
            raise ValueError("候选已处理或失效，请重新查看会话")
        now = _now()
        changed = connection.execute(
            "UPDATE agent_candidates SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
            (status, now, candidate_id, row["status"]),
        )
        if changed.rowcount != 1:
            raise ValueError("候选状态已变化，请重新查看会话")
        connection.execute(
            "UPDATE agent_runs SET status = ?, commit_receipt_json = ?, updated_at = ? WHERE id = ?",
            ("completed" if status == "committed" else status,
             _json(receipt or {}) if receipt is not None else
             connection.execute("SELECT commit_receipt_json FROM agent_runs WHERE id = ?", (row["run_id"],)).fetchone()[0],
             now, row["run_id"]),
        )
        _event(connection, project_id, session_id, row["run_id"], status,
               {"candidateId": candidate_id, "receipt": receipt or {}})
        return _candidate_row(connection.execute("SELECT * FROM agent_candidates WHERE id = ?", (candidate_id,)).fetchone()) or {}


def stale_other_episode_candidates(project_id: str, committed_candidate_id: str,
                                   target_key: str) -> None:
    with _database(project_id) as connection:
        rows = connection.execute(
            """SELECT c.id, c.run_id, c.owner_session_id FROM agent_candidates c
               JOIN agent_runs r ON r.id = c.run_id WHERE c.project_id = ? AND c.id != ?
               AND r.target_key = ? AND c.status = 'awaiting_confirmation'""",
            (project_id, committed_candidate_id, target_key),
        ).fetchall()
        for row in rows:
            connection.execute("UPDATE agent_candidates SET status = 'stale', updated_at = ? WHERE id = ?",
                               (_now(), row["id"]))
            connection.execute("UPDATE agent_runs SET status = 'stale', updated_at = ? WHERE id = ?",
                               (_now(), row["run_id"]))
            _event(connection, project_id, row["owner_session_id"], row["run_id"], "stale",
                   {"candidateId": row["id"], "reason": "target_revision_changed"})


def cancel_session_open_candidates(project_id: str, session_id: str) -> None:
    with _database(project_id) as connection:
        rows = connection.execute(
            """SELECT id, run_id FROM agent_candidates WHERE project_id = ? AND owner_session_id = ?
               AND status IN ('awaiting_confirmation', 'committing', 'commit_unknown')""",
            (project_id, session_id),
        ).fetchall()
        if any(connection.execute("SELECT status FROM agent_candidates WHERE id = ?", (row["id"],)).fetchone()[0]
               in {"committing", "commit_unknown"} for row in rows):
            raise ValueError("会话有正在提交的候选，请等待提交状态核实后再删除")
        for row in rows:
            connection.execute("UPDATE agent_candidates SET status = 'cancelled', updated_at = ? WHERE id = ?",
                               (_now(), row["id"]))
            connection.execute("UPDATE agent_runs SET status = 'cancelled', updated_at = ? WHERE id = ?",
                               (_now(), row["run_id"]))
            _event(connection, project_id, session_id, row["run_id"], "cancelled", {"candidateId": row["id"]})


def stage_asset_range_candidate(
    project_id: str, session_id: str, proposal: dict[str, Any],
    commit_payload: dict[str, Any], *, requirement_text: str = "",
) -> dict[str, Any]:
    """Save one immutable asset-range candidate owned by a project session."""
    source_id = str(proposal.get("sourceId") or "").strip()
    start = proposal.get("absoluteStart")
    if not session_id or not source_id or not isinstance(start, int):
        raise ValueError("资产范围候选缺少所属会话或目标原文")
    target_key = f"asset_range:{source_id}:{start}"
    candidate_id = f"asset-range-candidate-{uuid.uuid4().hex}"
    digest = _digest(proposal, commit_payload)
    now = _now()
    with _database(project_id) as connection:
        connection.execute("BEGIN IMMEDIATE")
        session = connection.execute(
            "SELECT project_id, episode_id FROM agent_sessions WHERE id = ?", (session_id,),
        ).fetchone()
        if session is None or session["project_id"] not in {project_id, ""} or session["episode_id"] != "__project__":
            raise ValueError("资产范围候选只能保存到发起任务的项目会话")
        run = connection.execute(
            """SELECT * FROM agent_runs WHERE project_id = ? AND owner_session_id = ?
               AND task_type = 'asset_range_propose' AND target_key = ?
               AND status IN ('running', 'awaiting_confirmation', 'superseded')
               ORDER BY updated_at DESC LIMIT 1""",
            (project_id, session_id, target_key),
        ).fetchone()
        run_id = str(run["id"]) if run else f"agent-run-{uuid.uuid4().hex}"
        version = int(connection.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM agent_candidates WHERE run_id = ?", (run_id,),
        ).fetchone()[0]) if run else 1
        if run:
            feedback = json.loads(run["requirement_feedback_json"] or "[]")
            if requirement_text and requirement_text != run["requirement_text"]:
                feedback.append(requirement_text)
            connection.execute(
                "UPDATE agent_candidates SET status = 'superseded', updated_at = ? WHERE run_id = ? AND status = 'awaiting_confirmation'",
                (now, run_id),
            )
            connection.execute(
                """UPDATE agent_runs SET status = 'awaiting_confirmation', latest_candidate_id = ?,
                   requirement_feedback_json = ?, requirement_revision = requirement_revision + ?, updated_at = ?
                   WHERE id = ?""",
                (candidate_id, _json(feedback[-12:]),
                 int(bool(requirement_text and requirement_text != run["requirement_text"])), now, run_id),
            )
        else:
            connection.execute(
                """INSERT INTO agent_runs (id, project_id, owner_session_id, owner_scope, owner_episode_id,
                   task_type, target_key, status, requirement_text, latest_candidate_id, created_at, updated_at)
                   VALUES (?, ?, ?, 'project', '__project__', 'asset_range_propose', ?,
                   'awaiting_confirmation', ?, ?, ?, ?)""",
                (run_id, project_id, session_id, target_key, requirement_text, candidate_id, now, now),
            )
        connection.execute(
            """INSERT INTO agent_candidates (id, run_id, project_id, owner_session_id, version,
               digest, status, proposal_json, commit_payload_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'awaiting_confirmation', ?, ?, ?, ?)""",
            (candidate_id, run_id, project_id, session_id, version, digest,
             _json(proposal), _json(commit_payload), now, now),
        )
        _event(connection, project_id, session_id, run_id, "candidate_ready",
               {"candidateId": candidate_id, "version": version, "digest": digest})
    return {"runId": run_id, "candidateId": candidate_id, "candidateDigest": digest,
            "candidateVersion": version, "status": "awaiting_confirmation"}


def get_asset_range_candidate(
    project_id: str, session_id: str | None, candidate_id: str | None = None,
) -> dict[str, Any] | None:
    if not session_id:
        return None
    with _database(project_id) as connection:
        where = "AND c.id = ?" if candidate_id else "AND c.status IN ('awaiting_confirmation', 'committing', 'commit_unknown')"
        params: tuple[Any, ...] = (project_id, session_id, candidate_id) if candidate_id else (project_id, session_id)
        row = connection.execute(
            f"""SELECT c.*, r.requirement_text, r.requirement_feedback_json FROM agent_candidates c
                JOIN agent_runs r ON r.id = c.run_id WHERE c.project_id = ? AND c.owner_session_id = ?
                AND r.task_type = 'asset_range_propose' {where}
                ORDER BY c.created_at DESC, c.id DESC LIMIT 1""", params,
        ).fetchone()
        return _candidate_row(row)


def list_open_asset_range_candidates(project_id: str, session_id: str | None) -> list[dict[str, Any]]:
    if not session_id:
        return []
    with _database(project_id) as connection:
        rows = connection.execute(
            """SELECT c.*, r.requirement_text, r.requirement_feedback_json FROM agent_candidates c
               JOIN agent_runs r ON r.id = c.run_id WHERE c.project_id = ? AND c.owner_session_id = ?
               AND r.task_type = 'asset_range_propose'
               AND c.status IN ('awaiting_confirmation', 'committing', 'commit_unknown')
               ORDER BY c.created_at DESC, c.id DESC""", (project_id, session_id),
        ).fetchall()
        return [candidate for row in rows if (candidate := _candidate_row(row))]


def refresh_asset_range_candidate_freshness(
    project_id: str, session_id: str | None, candidate_id: str | None = None,
) -> dict[str, Any] | None:
    from .project_resource_revisions import _json_hash, _resource_revision_value
    from .source_coverage import _load_source_coverage

    saved = get_asset_range_candidate(project_id, session_id, candidate_id)
    if not saved or saved["status"] != "awaiting_confirmation":
        return saved
    coverage = _load_source_coverage(project_id, saved["proposal"].get("sourceId"))
    guard = saved["commitPayload"]
    try:
        fresh = (_resource_revision_value(coverage) == int(guard.get("expectedRevision"))
                 and _json_hash(coverage) == str(guard.get("baseHash") or ""))
    except (TypeError, ValueError):
        fresh = False
    if fresh:
        return saved
    try:
        change_asset_range_candidate_status(project_id, str(session_id), saved["candidateId"], "stale",
                                            expected_digest=saved["digest"])
    except ValueError:
        return get_asset_range_candidate(project_id, session_id, saved["candidateId"])
    return None


def change_asset_range_candidate_status(
    project_id: str, session_id: str, candidate_id: str, status: str,
    *, expected_digest: str | None = None, receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if get_asset_range_candidate(project_id, session_id, candidate_id) is None:
        raise ValueError("当前会话没有该资产范围候选")
    return change_episode_candidate_status(
        project_id, session_id, candidate_id, status,
        expected_digest=expected_digest, receipt=receipt,
    )


def project_session_asset_range_candidate_messages(
    project_id: str, session_id: str, messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Refresh asset-range cards from durable candidate state for one session."""
    for candidate in list_open_asset_range_candidates(project_id, session_id):
        if candidate["status"] == "awaiting_confirmation":
            refresh_asset_range_candidate_freshness(project_id, session_id, candidate["candidateId"])
    with _database(project_id) as connection:
        rows = connection.execute(
            """SELECT c.id, c.run_id, c.status, c.digest, c.version FROM agent_candidates c
               JOIN agent_runs r ON r.id = c.run_id WHERE c.project_id = ? AND c.owner_session_id = ?
               AND r.task_type = 'asset_range_propose'""", (project_id, session_id),
        ).fetchall()
    statuses = {row["id"]: {"status": row["status"], "runId": row["run_id"],
                            "candidateDigest": row["digest"], "candidateVersion": row["version"]}
                for row in rows}
    display = {"awaiting_confirmation": "pending_confirmation", "committing": "committing",
               "commit_unknown": "commit_unknown", "committed": "committed", "superseded": "superseded",
               "cancelled": "cancelled", "stale": "stale"}
    result = copy.deepcopy(messages)
    seen: set[str] = set()
    for message in result:
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "asset_range_candidate":
                continue
            candidate_id = str(block.get("candidateId") or "")
            status = statuses.get(candidate_id)
            if not status:
                block["status"] = "stale"
                continue
            seen.add(candidate_id)
            block.update(status)
            block["status"] = display.get(status["status"], "stale")
    active = get_asset_range_candidate(project_id, session_id)
    if active and active["candidateId"] not in seen:
        card = {"type": "asset_range_candidate", "status": display.get(active["status"], "stale"),
                "runId": active["runId"], "candidateId": active["candidateId"],
                "candidateDigest": active["digest"], "candidateVersion": active["version"],
                **copy.deepcopy(active["proposal"])}
        result.append({"id": f"candidate-{active['candidateId']}", "role": "assistant",
                       "text": "资产范围候选已准备，请审阅。", "content": [card],
                       "createdAt": active["createdAt"]})
    return result
