"""Persist compact diagnostics for one agent execution, scoped to its conversation."""
from __future__ import annotations


def record_agent_eval_tool_io(project_id, session_id, execution_id, tool_id, tool_name, args, result):
    """Keep full business IO only for isolated bridge projects, without model reasoning."""
    if not str(project_id).startswith("agent-eval-") or not execution_id:
        return
    import json
    import uuid
    import traceback
    from .agent_sessions import _project_dir
    try:
        root = _project_dir(project_id) / "debug" / "agent-tool-io"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{uuid.uuid4().hex}.json"
        path.write_text(json.dumps({"executionId": execution_id, "sessionId": session_id,
                                   "toolUseId": tool_id, "tool": tool_name,
                                   "input": args, "result": result}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        print(traceback.format_exc(), flush=True)

import json
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator


_WRITE_TASK_TYPES = frozenset({
    "asset_range_propose", "asset_extraction", "episode_boundary_propose",
    "work_chain_plan_save", "workflow_cinematic_script_generation",
    "director_plan_generation", "video_prompt_generation",
    "video_prompt_optimization", "video_prompt_standalone_generation",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _excerpt(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _elapsed_ms(started_at: str, finished_at: str) -> int:
    return max(0, int((datetime.fromisoformat(finished_at) -
                       datetime.fromisoformat(started_at)).total_seconds() * 1000))


@contextmanager
def _database(project_id: str) -> Iterator[sqlite3.Connection]:
    from .agent_sessions import _agent_sessions_db_path

    path = _agent_sessions_db_path(project_id)
    if not path.is_file():
        raise FileNotFoundError("智能体会话数据库不存在")
    connection = sqlite3.connect(str(path), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS agent_execution_traces (
            execution_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL DEFAULT '',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            api_exchanges_json TEXT NOT NULL DEFAULT '[]',
            tool_calls_json TEXT NOT NULL DEFAULT '[]',
            candidate_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            errors_json TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY(session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_agent_execution_traces_session
            ON agent_execution_traces(project_id, session_id, started_at DESC);
    """)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _require_session(connection: sqlite3.Connection, project_id: str, session_id: str) -> None:
    row = connection.execute(
        "SELECT project_id FROM agent_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None or row["project_id"] not in {project_id, ""}:
        raise FileNotFoundError("智能体会话不存在")


def start_agent_execution_trace(project_id: str, session_id: str, execution_id: str, *,
                                scope: str, episode_id: str | None, task_type: str) -> None:
    with _database(project_id) as connection:
        _require_session(connection, project_id, session_id)
        connection.execute(
            """INSERT INTO agent_execution_traces(
                execution_id, project_id, session_id, scope, episode_id, task_type, status, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?)""",
            (execution_id, project_id, session_id, scope, episode_id or "", task_type, _now()),
        )


def _tool_name(value: Any) -> str:
    name = str(value or "").strip()
    return name.rsplit("__", 1)[-1] if name.startswith("mcp__") else name


def _tool_observation(name: str, matched: Any) -> dict[str, Any]:
    result = matched if isinstance(matched, dict) else {}
    if not name.startswith(("get_", "read_", "search_", "list_")):
        return {}
    observation = result.get("readObservation")
    return {"read": observation} if isinstance(observation, dict) else {"read": {"available": False}}


def _tool_request_summary(name: str, value: Any) -> dict[str, Any]:
    """Keep enough of a failed read to diagnose routing, without storing content."""
    args = value if isinstance(value, dict) else {}
    if name in {
        "get_episode_boundary_context", "get_asset_range_context", "get_asset_extraction_context",
        "get_plot_split_context", "get_cinematic_script_context",
        "get_director_plan_context", "get_video_prompt_context",
        "get_video_prompt_optimization_context", "get_video_prompt_standalone_context",
    }:
        return {key: args[key] for key in ("part", "ruleId")
                if key in args and isinstance(args[key], str)}
    if name == "get_asset_extraction_asset_catalog":
        return {key: args[key] for key in ("assetType", "offset", "limit")
                if key in args and isinstance(args[key], (str, int))}
    if name == "read_project_file":
        raw = str(args.get("file") or "")
        normalized = raw.replace("\\", "/")
        safe_relative = bool(normalized) and not normalized.startswith("/") and ":" not in normalized
        safe_relative = safe_relative and not any(part in {"", ".", ".."} for part in normalized.split("/"))
        return {"file": normalized[:180] if safe_relative else "<absolute-or-invalid-path>",
                "fileDigest": hashlib.sha256(raw.encode("utf-8")).hexdigest()}
    return {}


def _tool_calls(model_meta: dict[str, Any]) -> list[dict[str, Any]]:
    events = model_meta.get("sdkEvents") if isinstance(model_meta.get("sdkEvents"), dict) else {}
    uses = events.get("toolUses") if isinstance(events.get("toolUses"), list) else []
    sdk_results = events.get("toolResults") if isinstance(events.get("toolResults"), list) else []
    business = model_meta.get("sdkToolResults") if isinstance(model_meta.get("sdkToolResults"), list) else []
    by_id = {str(item.get("toolUseId") or ""): item for item in sdk_results if isinstance(item, dict)}
    available = [item for item in business if isinstance(item, dict)]
    rows: list[dict[str, Any]] = []
    for item in uses:
        if not isinstance(item, dict):
            continue
        name = _tool_name(item.get("name"))
        matched = next((entry for entry in available if _tool_name(entry.get("tool")) == name), None)
        if matched is not None:
            available.remove(matched)
        sdk_result = by_id.get(str(item.get("id") or ""), {})
        success = (bool(matched.get("success", True)) if matched is not None
                   else not bool(sdk_result.get("isError") or sdk_result.get("is_error")))
        row = {"name": name, "success": success}
        if item.get("id"):
            row["toolUseId"] = str(item["id"])
        if "isError" in sdk_result or "is_error" in sdk_result:
            row["sdkIsError"] = bool(sdk_result.get("isError") or sdk_result.get("is_error"))
        row.update(_tool_observation(name, matched))
        request_summary = _tool_request_summary(name, item.get("input"))
        if request_summary:
            row["request"] = request_summary
        if matched is not None:
            if matched.get("status"):
                row["status"] = str(matched["status"])
            if not success:
                row["error"] = _excerpt(matched.get("error") or matched.get("message"))
                row["errors"] = [
                    {key: _excerpt(error.get(key), 160) for key in ("type", "code", "field", "repairAction", "message")
                     if error.get(key) is not None}
                    for error in (matched.get("errors") or [])[:8] if isinstance(error, dict)
                ]
        elif not success:
            row["error"] = "SDK 工具调用失败"
        rows.append(row)
    for item in available:
        row = {"name": _tool_name(item.get("tool")), "success": bool(item.get("success", True))}
        row.update(_tool_observation(row["name"], item))
        if item.get("status"):
            row["status"] = str(item["status"])
        if not row["success"]:
            row["error"] = _excerpt(item.get("error") or item.get("message"))
        rows.append(row)
    return rows


def _candidate(result: dict[str, Any]) -> dict[str, Any]:
    blocks = result.get("contentBlocks") if isinstance(result.get("contentBlocks"), list) else []
    block = next((item for item in blocks if isinstance(item, dict)
                  and item.get("type") == "episode_boundary_candidate"), {})
    pending = result.get("pendingOperation") if isinstance(result.get("pendingOperation"), dict) else {}
    proposal = pending.get("proposal") if isinstance(pending.get("proposal"), dict) else {}
    candidate_id = str(block.get("candidateId") or proposal.get("proposalId")
                       or pending.get("candidateId") or pending.get("runId")
                       or result.get("confirmedCandidateId") or result.get("cancelledCandidateId") or "")
    if not candidate_id:
        return {}
    candidate = {"runId": str(block.get("runId") or pending.get("runId") or ""),
                 "candidateId": candidate_id,
                 "status": str(block.get("status") or ("awaiting_confirmation" if pending else ""))}
    if pending.get("operationType") == "commit_plot_split":
        candidate["kind"] = "plot_split"
        candidate["episodeId"] = str(pending.get("episodeId") or proposal.get("episodeId") or "")
        candidate["itemCount"] = len(proposal.get("items") or [])
        candidate["version"] = pending.get("candidateVersion")
        candidate["digest"] = str(pending.get("candidateDigest") or "")
    return candidate


def _summarize(result: dict[str, Any], *, task_type: str) -> dict[str, Any]:
    meta = result.get("agentModelMeta") if isinstance(result.get("agentModelMeta"), dict) else {}
    diagnostics = meta.get("sdkDiagnostics") if isinstance(meta.get("sdkDiagnostics"), dict) else {}
    raw_exchanges = diagnostics.get("apiExchanges") if isinstance(diagnostics.get("apiExchanges"), list) else None
    capture_available = bool(diagnostics.get("apiCaptureEnabled"))
    exchanges = [
        {"requestNumber": item.get("requestNumber"), "status": item.get("status"),
         "success": bool(item.get("success")), "error": _excerpt(item.get("error"), 200)}
        for item in (raw_exchanges or []) if isinstance(item, dict) and not item.get("auxiliary")
    ]
    tools = _tool_calls(meta)
    submits = [item for item in tools if item["name"].startswith(("submit_", "commit_"))]
    local_no_model = (task_type == "local_confirmation" or meta.get("preflightNoModel") is True) and not capture_available
    metric = {
        "modelRequestCount": len(exchanges) if capture_available and raw_exchanges is not None else 0 if local_no_model else None,
        "modelRequestMeasurement": "sdk_http_capture" if capture_available else "local_no_model" if local_no_model else "unavailable",
        "modelFailureCount": sum(not item["success"] for item in exchanges),
        "toolCallCount": len(tools),
        "toolFailureCount": sum(not item["success"] for item in tools),
        "submitAttemptCount": len(submits),
        "submitFailureCount": sum(not item["success"] for item in submits),
        "durationMs": None,
        "sdkDurationMs": diagnostics.get("totalMs") if isinstance(diagnostics.get("totalMs"), int) else None,
        "firstEventMs": diagnostics.get("firstEventMs") if isinstance(diagnostics.get("firstEventMs"), int) else None,
    }
    errors = []
    if diagnostics.get("failureKind"):
        errors.append({"type": "failureKind", "value": _excerpt(diagnostics["failureKind"], 160)})
        if diagnostics.get("executionStage"):
            errors.append({"type": "executionStage", "value": _excerpt(diagnostics["executionStage"], 160)})
    if str(diagnostics.get("resultSubtype") or "").startswith("error_"):
        errors.append({"type": "resultSubtype", "value": _excerpt(diagnostics["resultSubtype"], 160)})
    if result.get("success") is False:
        errors.append({"type": "result", "value": _excerpt(result.get("error") or result.get("message"))})
    pending = result.get("pendingOperation") if isinstance(result.get("pendingOperation"), dict) else {}
    pending_proposal = pending.get("proposal") if isinstance(pending.get("proposal"), dict) else {}
    message_summary = _excerpt(result.get("message"), 500)
    if pending.get("operationType") == "commit_plot_split":
        message_summary = f"剧情拆分候选已暂存：{len(pending_proposal.get('items') or [])} 段，等待用户确认"
    result_summary = {
        "success": bool(result.get("success")),
        "message": message_summary,
        "sessionStatus": str(result.get("sessionStatus") or ""),
        "projectChanged": bool(result.get("projectChanged")),
        "pendingOperationType": str(pending.get("type") or ""),
        "contentTypes": [str(item.get("type")) for item in (result.get("contentBlocks") or [])
                         if isinstance(item, dict)],
    }
    receipt = result.get("commitReceipt") if isinstance(result.get("commitReceipt"), dict) else {}
    if receipt:
        result_summary["commitReceipt"] = {
            "receiptId": str(receipt.get("receiptId") or ""),
            "taskType": str(receipt.get("taskType") or ""),
            "targetIds": receipt.get("targetIds") if isinstance(receipt.get("targetIds"), list) else [],
            "changedResources": receipt.get("changedResources") if isinstance(receipt.get("changedResources"), list) else [],
        }
    candidate = _candidate(result)
    if candidate and pending:
        status = "awaiting_confirmation"
    elif not result.get("success"):
        status = "failed"
    elif task_type in _WRITE_TASK_TYPES and not receipt:
        # The SDK can finish a turn after explaining a validation block.
        # Such a turn has completed, but the requested write has not.
        status = "incomplete"
        errors.append({"type": "missing_commit", "value": "任务结束时没有可核验的提交回执"})
    else:
        status = "completed"
    return {"status": status, "metrics": metric, "apiExchanges": exchanges,
            "toolCalls": tools, "candidate": candidate, "result": result_summary, "errors": errors}


def finish_agent_execution_trace(project_id: str, session_id: str, execution_id: str,
                                 result: dict[str, Any]) -> None:
    with _database(project_id) as connection:
        _require_session(connection, project_id, session_id)
        started = connection.execute(
            """SELECT started_at, task_type FROM agent_execution_traces WHERE execution_id = ?
               AND project_id = ? AND session_id = ?""", (execution_id, project_id, session_id),
        ).fetchone()
        if started is None:
            raise FileNotFoundError("智能体执行轨迹不存在")
        summary = _summarize(result, task_type=started["task_type"])
        finished_at = _now()
        summary["metrics"]["durationMs"] = _elapsed_ms(started["started_at"], finished_at)
        connection.execute(
            """UPDATE agent_execution_traces SET status = ?, finished_at = ?, metrics_json = ?,
               api_exchanges_json = ?, tool_calls_json = ?, candidate_json = ?, result_json = ?, errors_json = ?
               WHERE execution_id = ? AND project_id = ? AND session_id = ?""",
            (summary["status"], finished_at, _json(summary["metrics"]), _json(summary["apiExchanges"]),
             _json(summary["toolCalls"]), _json(summary["candidate"]), _json(summary["result"]),
             _json(summary["errors"]), execution_id, project_id, session_id),
        )


def cancel_agent_execution_trace(project_id: str, session_id: str, execution_id: str) -> None:
    with _database(project_id) as connection:
        connection.execute(
            """UPDATE agent_execution_traces SET status = 'cancelled', finished_at = ?
               WHERE execution_id = ? AND project_id = ? AND session_id = ? AND status = 'running'""",
            (_now(), execution_id, project_id, session_id),
        )


def get_agent_execution_trace(project_id: str, session_id: str,
                              execution_id: str | None = None) -> dict[str, Any]:
    with _database(project_id) as connection:
        _require_session(connection, project_id, session_id)
        if execution_id:
            row = connection.execute(
                """SELECT * FROM agent_execution_traces WHERE project_id = ?
                   AND session_id = ? AND execution_id = ?""",
                (project_id, session_id, execution_id),
            ).fetchone()
        else:
            row = connection.execute(
                """SELECT * FROM agent_execution_traces WHERE project_id = ?
                   AND session_id = ? ORDER BY started_at DESC, rowid DESC LIMIT 1""",
                (project_id, session_id),
            ).fetchone()
    if row is None:
        return {"success": False, "message": "该会话没有可查询的智能体执行记录", "trace": None}
    trace = {
        "projectId": row["project_id"], "sessionId": row["session_id"],
        "executionId": row["execution_id"], "scope": row["scope"],
        "episodeId": row["episode_id"] or None, "taskType": row["task_type"],
        "status": row["status"], "startedAt": row["started_at"],
        "finishedAt": row["finished_at"] or None,
        "durationMs": _elapsed_ms(row["started_at"], row["finished_at"] or _now()),
        "metrics": json.loads(row["metrics_json"]),
        "apiExchanges": json.loads(row["api_exchanges_json"]),
        "toolCalls": json.loads(row["tool_calls_json"]),
        "candidate": json.loads(row["candidate_json"]),
        "result": json.loads(row["result_json"]),
        "errors": json.loads(row["errors_json"]),
    }
    candidate_id = str(trace["candidate"].get("candidateId") or "")
    if candidate_id:
        from .agent_run_store import get_episode_candidate

        current = get_episode_candidate(project_id, session_id, candidate_id)
        if current:
            trace["candidate"].update({
                "runId": current["runId"], "status": current["status"],
                "version": current["version"], "digest": current["digest"],
            })
    return {"success": True, "trace": trace}
