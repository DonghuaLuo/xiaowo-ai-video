"""Publish committed content and its derived production status as separate mutations."""
from __future__ import annotations

import copy
import traceback
from typing import Any

from .store_core import _emit_agent_event


def _refresh_failure() -> dict[str, Any]:
    return {
        "action": "episode_production_status_refresh_failed",
        "productionStatusRefreshFailed": True,
        "changedResources": [],
        "message": "内容已保存，工作链状态同步失败，请重试同步。",
    }


def refresh_workflow_production_status(project_id: str, episode_id: str) -> dict[str, Any]:
    from .production_status import update_episode_production_status

    # A refresh failure must never retry the already committed content writer.
    for _ in range(2):
        try:
            result = update_episode_production_status(project_id, episode_id)
            return {
                **result,
                "action": "episode_production_status_updated",
                "productionStatus": result["status"],
            }
        except Exception:
            print(traceback.format_exc(), flush=True)
    return _refresh_failure()


def _publish(project_id: str, episode_id: str, event: dict[str, Any]) -> None:
    try:
        _emit_agent_event("project_changed", {
            **event, "projectId": project_id, "episodeId": episode_id,
        })
    except Exception:
        print(traceback.format_exc(), flush=True)


def sync_workflow_production_after_commit(
    project_id: str, episode_id: str, result: dict[str, Any],
) -> dict[str, Any]:
    from .canvas_store_queries import episode_canvas_exists

    if not result.get("success") or result.get("skippedLocked"):
        return result
    try:
        if not episode_canvas_exists(project_id, episode_id):
            return result
        # Publish the content revision first. Do not replace its transaction identity
        # with the later derived_refresh revision or hide structure records in it.
        content = {key: copy.deepcopy(result[key]) for key in (
            "workflowVersion", "txId", "seq", "revision", "baseRevision", "opType",
            "records", "changedResources",
        ) if key in result}
        _publish(project_id, episode_id, {"action": "workflow_content_committed", **content})
        status = refresh_workflow_production_status(project_id, episode_id)
    except Exception:
        print(traceback.format_exc(), flush=True)
        status = _refresh_failure()
    _publish(project_id, episode_id, status)
    if status.get("productionStatusRefreshFailed"):
        result = {
            **result, "productionStatusRefreshFailed": True,
            "productionStatusWarning": status["message"],
            "productionWarnings": [*(result.get("productionWarnings") or []), {
                "code": "production_status_refresh_failed", "message": status["message"],
            }],
        }
    else:
        # Each mutation keeps its own transaction identity and revision.
        result = {**result, "productionStatusMutation": copy.deepcopy(status)}
    return result


def get_canvas_snapshot_with_production_status(
    project_id: str, episode_id: str, payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .canvas_store_queries import get_canvas_snapshot_v4
    from .production_status import production_status_needs_refresh

    params = payload if isinstance(payload, dict) else {}
    snapshot = get_canvas_snapshot_v4(project_id, episode_id, params)
    # Queries never write or publish. Legacy/config-stale projections can be
    # refreshed explicitly by the client after the graph has been displayed.
    document = snapshot.get("document", {})
    snapshot["productionStatusNeedsRefresh"] = bool(snapshot.get("records", {}).get("nodes")) and production_status_needs_refresh(
        document.get("productionStatus"), snapshot["revision"], document.get("productionStatusRevision"),
    )
    return snapshot
