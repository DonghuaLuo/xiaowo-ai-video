# -*- coding: utf-8 -*-
"""分镜脚本返工要求与完整修改版本之间的轻量关联。"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import copy
import uuid

from .canvas_store_database import card_dir
from .projects import _touch_project_meta
from .store_core import _JSON_WRITE_LOCK, _display_time, _now, _read_json, _write_json
from .workflow_edit_history import _read_node_edit_history
from .workflow_planning_lifecycle import _safe_episode_id


_SCHEMA_VERSION = 1


def _rework_records_path(project_id: str, episode_id: str, node_id: str) -> Path:
    return card_dir(project_id, _safe_episode_id(episode_id), node_id) / "history" / "director_rework_records.json"


def _read_rework_records(project_id: str, episode_id: str, node_id: str) -> list[dict[str, str]]:
    data = _read_json(_rework_records_path(project_id, episode_id, node_id), {})
    if not isinstance(data, dict) or data.get("schemaVersion") != _SCHEMA_VERSION:
        return []
    rows = data.get("items")
    if not isinstance(rows, list):
        return []
    return [
        {
            "id": str(row["id"]),
            "instruction": str(row["instruction"]),
            "versionId": str(row["versionId"]),
            "createdAt": str(row.get("createdAt") or ""),
            "displayTime": str(row.get("displayTime") or ""),
        }
        for row in rows
        if isinstance(row, dict)
        and all(isinstance(row.get(key), str) and row[key].strip() for key in ("id", "instruction", "versionId"))
    ]


def _write_rework_records(project_id: str, episode_id: str, node_id: str, rows: list[dict[str, str]]) -> None:
    _write_json(_rework_records_path(project_id, episode_id, node_id), {
        "schemaVersion": _SCHEMA_VERSION,
        "episodeId": _safe_episode_id(episode_id),
        "nodeId": node_id,
        "updatedAt": _now(),
        "items": rows,
    })


def list_director_rework_records(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    node_id = str((payload or {}).get("nodeId") or "").strip()
    if not node_id:
        raise ValueError("缺少 nodeId")
    rows = _read_rework_records(project_id, episode_id, node_id)
    return {"success": True, "episodeId": episode_id, "nodeId": node_id, "items": list(reversed(rows))}


def record_director_rework_record(project_id: str, episode_id: str, node_id: str,
                                  instruction: str, version_id: str) -> dict[str, Any]:
    instruction = str(instruction or "").strip()
    version_id = str(version_id or "").strip()
    if not instruction or not version_id:
        raise ValueError("返工记录缺少要求或修改版本")
    with _JSON_WRITE_LOCK:
        versions = _read_node_edit_history(project_id, episode_id, node_id)
        if not any(row.get("id") == version_id and row.get("nodeType") == "director.board" for row in versions):
            raise FileNotFoundError("返工结果对应的修改版本不存在")
        rows = _read_rework_records(project_id, episode_id, node_id)
        created_at = _now()
        item = {
            "id": uuid.uuid4().hex,
            "instruction": instruction,
            "versionId": version_id,
            "createdAt": created_at,
            "displayTime": _display_time(created_at),
        }
        rows.append(item)
        _write_rework_records(project_id, episode_id, node_id, rows)
    _touch_project_meta(project_id)
    return {"success": True, "episodeId": episode_id, "nodeId": node_id, "item": copy.deepcopy(item)}


def delete_director_rework_record(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    node_id = str(payload.get("nodeId") or "").strip()
    record_id = str(payload.get("recordId") or "").strip()
    clear_all = payload.get("clearAll") is True
    if not node_id or (not record_id and not clear_all):
        raise ValueError("缺少分镜脚本或返工记录标识")
    with _JSON_WRITE_LOCK:
        rows = _read_rework_records(project_id, episode_id, node_id)
        if record_id and not any(row["id"] == record_id for row in rows):
            raise FileNotFoundError("返工记录不存在")
        next_rows = [] if clear_all else [row for row in rows if row["id"] != record_id]
        _write_rework_records(project_id, episode_id, node_id, next_rows)
    _touch_project_meta(project_id)
    return {
        "success": True, "episodeId": episode_id, "nodeId": node_id,
        "recordId": record_id, "deletedCount": len(rows) - len(next_rows),
        "projectChanged": True, "changedResources": ["director_rework_records"],
    }
