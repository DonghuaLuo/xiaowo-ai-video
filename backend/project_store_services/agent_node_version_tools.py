"""Read-only, episode-scoped modification history for script agents."""
from __future__ import annotations

import copy
from typing import Any

from .canvas_store_queries import read_canvas_card_record_v4
from .workflow_director_rework_records import list_director_rework_records
from .workflow_edit_history import list_node_edit_history


_SUPPORTED_TYPES = {"prompt.storyboard", "director.board"}
_VERSION_FIELDS = {
    "prompt.storyboard": (
        "sourceFactText", "cinematicStoryText", "scriptUserInstruction",
        "scriptTemplateId", "scriptTemplateLabel",
    ),
    "director.board": (
        "directorPlan", "directorPlanShots", "speakerRoster", "directorRuleId", "directorRuleSelectionMode",
        "rhythmMultiplier", "durationSeconds", "speechBudgetNote",
    ),
}


def _preview(value: Any, length: int = 120) -> str:
    return " ".join(str(value or "").split())[:length]


def _node_versions(project_id: str, episode_id: str, node_id: str,
                   expected_type: str = "") -> tuple[str, list[dict[str, Any]], dict[str, str]]:
    if not episode_id or not node_id:
        raise ValueError("必须明确提供 episodeId 和 nodeId")
    node = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="summary")
    node_type = str(node.get("type") or "").strip()
    if node_type not in _SUPPORTED_TYPES or (expected_type and node_type != expected_type):
        raise ValueError("修改记录目标必须是当前集的片段剧本或分镜脚本节点")
    # The existing history service sanitizes and orders newest first. Do not
    # expose its restorePatch, unrelated node fields or filesystem location.
    items = [item for item in list_node_edit_history(
        project_id, episode_id, {"nodeId": node_id},
    )["items"] if item.get("nodeType") == node_type]
    feedback = {}
    if node_type == "director.board":
        feedback = {
            row["versionId"]: row["instruction"]
            for row in list_director_rework_records(
                project_id, episode_id, {"nodeId": node_id},
            )["items"]
        }
    return node_type, items, feedback


def list_workflow_node_versions(project_id: str, episode_id: str, node_id: str,
                                *, offset: int = 0, limit: int = 20,
                                expected_type: str = "") -> dict[str, Any]:
    node_type, items, feedback = _node_versions(project_id, episode_id, node_id, expected_type)
    offset = max(0, int(offset))
    limit = max(1, min(50, int(limit)))
    total = len(items)
    page = items[offset:offset + limit]
    summaries = []
    for index, item in enumerate(page):
        content = (item.get("restorePatch") or {}).get("data") or {}
        instruction = feedback.get(item["id"]) if node_type == "director.board" else content.get("scriptUserInstruction")
        shots = content.get("directorPlanShots") if node_type == "director.board" else None
        first_shot = shots[0] if isinstance(shots, list) and shots and isinstance(shots[0], dict) else {}
        preview = (
            _preview(first_shot.get("visualPurpose") or first_shot.get("storyboardFrame") or content.get("directorPlan"))
            if node_type == "director.board" else _preview(content.get("cinematicStoryText"))
        )
        summaries.append({
            "versionId": item["id"], "versionNumber": total - offset - index,
            "createdAt": item.get("createdAt") or "",
            "summary": item.get("summary") or "", "preview": preview,
            "source": item.get("source") or "", "reason": item.get("reason") or "",
            "feedbackPreview": _preview(instruction),
            **({"shotCount": len(shots)} if isinstance(shots, list) else {}),
        })
    return {
        "success": True, "episodeId": episode_id, "nodeId": node_id,
        "nodeType": node_type, "total": total, "offset": offset,
        "hasMore": offset + len(page) < total,
        "items": summaries,
    }


def read_workflow_node_version(project_id: str, episode_id: str, node_id: str,
                               *, version_id: str = "", version_number: int = 0,
                               expected_type: str = "") -> dict[str, Any]:
    node_type, items, feedback = _node_versions(project_id, episode_id, node_id, expected_type)
    version_id = str(version_id or "").strip()
    if bool(version_id) == bool(version_number):
        raise ValueError("请提供 versionId 或 versionNumber，且只能提供其中一个")
    total = len(items)
    if version_number:
        if not 1 <= version_number <= total:
            raise ValueError("所选修改版本不存在")
        item = items[total - version_number]
    else:
        item = next((row for row in items if row["id"] == version_id), None)
        if item is None:
            raise ValueError("所选修改版本不存在")
    content = (item.get("restorePatch") or {}).get("data") or {}
    selected = {key: copy.deepcopy(content[key]) for key in _VERSION_FIELDS[node_type] if key in content}
    instruction = feedback.get(item["id"]) if node_type == "director.board" else selected.pop("scriptUserInstruction", "")
    if node_type == "director.board" and selected.get("directorPlanShots"):
        selected.pop("directorPlan", None)
    return {
        "success": True, "episodeId": episode_id, "nodeId": node_id,
        "nodeType": node_type, "versionId": item["id"],
        "versionNumber": total - items.index(item),
        "createdAt": item.get("createdAt") or "",
        "content": selected,
        "feedback": instruction or "",
    }
