"""Read-only persisted checkpoints for isolated agent evaluations.

These reads deliberately bypass UI hydration, coverage recovery, and canvas
schema initialization so taking a baseline cannot change the project.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_sessions import _agent_sessions_db_path, _project_dir
from .canvas_store_database import canvas_db_path


_ASSET_TYPES = ("characters", "creatures", "scenes", "props", "styles")
_CANVAS_TABLES = {
    "nodes": ("canvas_nodes", "node_id, sort_index, node_type, route_id, segment_id, work_chain_id, position_json, status, data_json, node_json, summary_json", "sort_index, node_id"),
    "edges": ("canvas_edges", "edge_id, sort_index, source_node_id, target_node_id, source_handle, target_handle, edge_data_json, edge_json", "sort_index, edge_id"),
    "routes": ("canvas_routes", "route_id, sort_index, route_json, summary_json", "sort_index, route_id"),
    "workChains": ("canvas_work_chains", "work_chain_id, sort_index, work_chain_json, summary_json", "sort_index, work_chain_id"),
    "versions": ("canvas_versions", "node_id, version_id, sort_index, version_type, status, active, media_json, version_json", "node_id, sort_index, version_id"),
    "sourceRefs": ("canvas_node_source_refs", "source_node_id, target_node_id, ref_kind, sort_index", "source_node_id, target_node_id, ref_kind, sort_index"),
    "identityRefs": ("canvas_version_identity_refs", "identity, node_id, version_id, ref_kind, sort_index", "identity, node_id, version_id, ref_kind, sort_index"),
}


def _document(path: Path, *, default: Any = None) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "value": default}
    return {"exists": True, "value": json.loads(path.read_text(encoding="utf-8"))}


def _canvas_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        key: json.loads(row[key]) if key.endswith("_json") else row[key]
        for key in row.keys()
    }


def _canvas_checkpoint(project_id: str, episode_id: str) -> dict[str, Any]:
    db_path = canvas_db_path(project_id)
    records: dict[str, list[dict[str, Any]]] = {key: [] for key in _CANVAS_TABLES}
    if not db_path.is_file():
        return {"exists": False, "document": None, "records": records}
    connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN")
        row = connection.execute(
            "SELECT viewport_json, routes_json, work_chains_json, state_json, extras_json "
            "FROM canvas_documents WHERE episode_id = ?", (episode_id,),
        ).fetchone()
        document = _canvas_record(row) if row is not None else None
        if document is not None:
            for key, (table, columns, order) in _CANVAS_TABLES.items():
                rows = connection.execute(
                    f"SELECT {columns} FROM {table} WHERE episode_id = ? ORDER BY {order}",
                    (episode_id,),
                ).fetchall()
                records[key] = [_canvas_record(item) for item in rows]
        return {"exists": document is not None, "document": document, "records": records}
    finally:
        connection.close()


def get_agent_test_inspection_domain(
    project_id: str, domain: str, episode_id: str | None = None,
) -> dict[str, Any]:
    """Return stored creative data without running any normalizing read handler."""
    if not project_id.startswith("agent-eval-"):
        raise ValueError("检查点只允许隔离测试项目")
    if domain not in {"planning", "coverage", "assets", "canvas"}:
        raise ValueError("检查点领域无效")
    project_dir = _project_dir(project_id)
    project_doc = _document(project_dir / "project.json")
    project = project_doc["value"]
    if not project_doc["exists"] or not isinstance(project, dict) or project.get("id") != project_id:
        raise FileNotFoundError("隔离测试项目不存在或项目 ID 不匹配")
    episodes = project.get("episodes") if isinstance(project.get("episodes"), list) else []
    selected_episode_id = str(episode_id or (
        episodes[0].get("id") if episodes and isinstance(episodes[0], dict) else "E01"
    ) or "E01").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", selected_episode_id) or selected_episode_id in {".", ".."}:
        raise ValueError("检查点分集 ID 无效")
    if domain == "planning":
        data = {
            "episodeId": selected_episode_id,
            "episodes": episodes,
            "storyWorld": _document(project_dir / "story_world.json"),
            "workChainPlan": _document(project_dir / "episodes" / selected_episode_id / "work_chain_plan.json"),
        }
    elif domain == "coverage":
        data = {
            "coverage": _document(project_dir / "source_coverage.json"),
            "sources": _document(project_dir / "sources" / "sources.json"),
        }
    elif domain == "assets":
        data = _document(project_dir / "assets" / "assets.json", default={key: [] for key in _ASSET_TYPES})
        if not isinstance(data["value"], dict) or any(
            not isinstance(data["value"].get(key), list) for key in _ASSET_TYPES
        ):
            raise ValueError("资产文件缺少必要列表")
    else:
        data = _canvas_checkpoint(project_id, selected_episode_id)
    return {"success": True, "schemaVersion": 1, "domain": domain, "data": data}


def get_agent_test_execution_report(
    project_id: str, session_id: str, since: str,
) -> dict[str, Any]:
    """Aggregate every persisted execution since this bridge opened the session."""
    if not project_id.startswith("agent-eval-"):
        raise ValueError("执行报告只允许隔离测试项目")
    if not session_id:
        raise ValueError("执行报告需要会话 ID")
    try:
        since_time = datetime.fromisoformat(since.replace("Z", "+00:00"))
        if since_time.tzinfo is None:
            raise ValueError("时区缺失")
        since_time = since_time.astimezone(timezone.utc)
    except (AttributeError, ValueError) as exc:
        raise ValueError("执行报告起始时间无效") from exc
    path = _agent_sessions_db_path(project_id)
    if not path.is_file():
        raise FileNotFoundError("智能体会话数据库不存在")
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN")
        owner = connection.execute(
            "SELECT project_id FROM agent_sessions WHERE id = ?", (session_id,),
        ).fetchone()
        if owner is None or owner["project_id"] != project_id:
            raise FileNotFoundError("隔离测试会话不存在")
        present = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'agent_execution_traces'",
        ).fetchone()
        metrics: dict[str, int | float] = {}
        recent: deque[dict[str, Any]] = deque(maxlen=20)
        trace_count = 0
        unmeasured_model_runs = 0
        if present:
            rows = connection.execute(
                "SELECT execution_id, task_type, status, started_at, finished_at, metrics_json, "
                "candidate_json, result_json, errors_json FROM agent_execution_traces "
                "WHERE project_id = ? AND session_id = ? ORDER BY started_at, rowid",
                (project_id, session_id),
            )
            for row in rows:
                started = datetime.fromisoformat(row["started_at"]).astimezone(timezone.utc)
                if started < since_time:
                    continue
                trace_count += 1
                values = json.loads(row["metrics_json"])
                if values.get("modelRequestCount") is None:
                    unmeasured_model_runs += 1
                for key, value in values.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        metrics[key] = metrics.get(key, 0) + value
                recent.append({
                    "executionId": row["execution_id"],
                    "taskType": row["task_type"], "status": row["status"],
                    "startedAt": row["started_at"], "finishedAt": row["finished_at"],
                    "metrics": values,
                    "candidate": json.loads(row["candidate_json"]),
                    "result": json.loads(row["result_json"]),
                    "errors": json.loads(row["errors_json"]),
                })
        return {
            "success": True, "traceCount": trace_count, "metrics": metrics,
            "unmeasuredModelRuns": unmeasured_model_runs,
            "executionTraces": list(recent),
        }
    finally:
        connection.close()
