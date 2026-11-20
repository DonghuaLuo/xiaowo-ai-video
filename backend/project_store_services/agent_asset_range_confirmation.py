# -*- coding: utf-8 -*-
"""Deterministic confirmation of a saved asset-range candidate."""
from __future__ import annotations

import copy
import traceback
from typing import Any

from .agent_boundary_report import build_boundary_completion_report
from .agent_run_store import (
    change_asset_range_candidate_status,
    get_asset_range_candidate,
    list_open_asset_range_candidates,
    refresh_asset_range_candidate_freshness,
)
from .agent_session_policy import validate_agent_session_pending_operation
from .asset_range_planning import commit_asset_range
from .catalogs import _style_phase_visuals_from_mapping
from .runtime_state import _LOCK
from .source_coverage import _load_source_coverage
from .store_core import _emit_agent_event, _read_json


def _verified_asset_range(project_id: str, proposal: dict[str, Any]) -> dict[str, Any] | None:
    source_id = str(proposal.get("sourceId") or "")
    range_id = str(proposal.get("rangeId") or "")
    coverage = _load_source_coverage(project_id, source_id)
    row = next((item for item in (coverage.get("assetRanges") or [])
                if isinstance(item, dict) and str(item.get("rangeId") or "") == range_id), None)
    if not row or any(row.get(key) != proposal.get(key)
                      for key in ("sourceId", "absoluteStart", "absoluteEnd", "assetTypes", "targetUnits",
                                  "reason", "boundaryReason", "boundaryEndText", "phaseVisualContexts")):
        return None
    if int((coverage.get("assetCursor") or {}).get("nextOffset") or -1) != int(proposal["absoluteEnd"]):
        return None
    phase_visuals = proposal.get("phaseVisualContexts") or []
    if phase_visuals:
        from .agent_sessions import _project_config_path
        config = _read_json(_project_config_path(project_id), {})
        style = config.get("style") if isinstance(config.get("style"), dict) else {}
        actual_visuals = _style_phase_visuals_from_mapping(style)
        expected_prompts = {str(item.get("visualPrompt") or "") for item in phase_visuals}
        actual_prompts = {str(item.get("prompt") or "") for item in actual_visuals}
        if not expected_prompts.issubset(actual_prompts):
            return None
    return copy.deepcopy(row)


def _result(project_id: str, candidate_id: str, row: dict[str, Any], *, repeated: bool = False,
            changed_resources: list[str] | None = None) -> dict[str, Any]:
    range_label = row.get('rangeId') or '资产范围'
    message = (f"{range_label} 已保存，本次未重复写入。" if repeated
               else f"{range_label} 已确认并写入项目。")
    resources = [] if repeated else (changed_resources if changed_resources is not None else ["sourceCoverage", "assetRanges", "projectConfig"])
    try:
        if resources:
            _emit_agent_event("project_changed", {
                "action": "asset_range_committed", "projectId": project_id,
                "changedResources": resources,
            })
    except Exception:
        print(traceback.format_exc(), flush=True)
    return {
        "success": True, "status": "committed", "message": message,
        "completionReport": None if repeated else build_boundary_completion_report(project_id, row, kind="asset_range"),
        "contentBlocks": [], "pendingOperation": None,
        "confirmedCandidateId": candidate_id, "repeatedConfirmation": repeated,
        "projectChanged": bool(resources), "suppressSessionMessage": not repeated,
        "completedTaskType": "asset_range_confirmed", "sessionStatus": "idle",
        "agentModelMeta": {"source": "local-controller", "resultProtocol": "task-result-protocol@v1"},
        "projectEffect": {"projectChanged": bool(resources),
                          "changedResources": resources,
                          "focusTarget": {"section": "assets"}, "notice": message},
    }


def _reference(project_id: str, session_id: str | None,
               candidate_ref: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    ref = candidate_ref if isinstance(candidate_ref, dict) else {}
    if not ref:
        candidates = list_open_asset_range_candidates(project_id, session_id)
        if len(candidates) != 1:
            return None, ("当前会话有多个待确认资产范围，请点击要处理的候选卡片。" if candidates
                          else "当前会话没有可确认的资产范围候选。")
        candidate = candidates[0]
        ref = {"runId": candidate["runId"], "candidateId": candidate["candidateId"],
               "candidateDigest": candidate["digest"], "candidateVersion": candidate["version"]}
    candidate_id = str(ref.get("candidateId") or "").strip()
    record = get_asset_range_candidate(project_id, session_id, candidate_id)
    if not record or any((
        str(ref.get(key) or "") != str(record[field] or "")
        for key, field in (("runId", "runId"), ("candidateDigest", "digest"),
                           ("candidateVersion", "version"))
    )):
        return None, "候选版本已变化或当前会话没有展示该候选，请重新审阅。"
    return record, ""


def confirm_asset_range_locally(
    project_id: str, session_id: str | None, session_policy: dict[str, Any],
    *, candidate_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _LOCK:
        try:
            validate_agent_session_pending_operation("commit_asset_range", session_policy)
        except ValueError as exc:
            return {"success": False, "message": str(exc), "sessionStatus": "error"}
        record, error = _reference(project_id, session_id, candidate_ref)
        if record is None:
            return {"success": False, "message": error, "sessionStatus": "error"}
        candidate_id = record["candidateId"]
        proposal = record["proposal"]
        if record["status"] == "committed":
            actual = _verified_asset_range(project_id, proposal)
            if actual:
                return _result(project_id, candidate_id, actual, repeated=True)
        if record["status"] not in {"awaiting_confirmation", "committing", "commit_unknown"}:
            return {"success": False, "message": "候选已处理或失效，请重新规划。", "sessionStatus": "error"}
        if record["status"] == "awaiting_confirmation":
            fresh = refresh_asset_range_candidate_freshness(project_id, session_id, candidate_id)
            if not fresh:
                return {"success": False, "message": "原文游标或覆盖记录已变化，候选失效，请重新规划。",
                        "sessionStatus": "error"}
            change_asset_range_candidate_status(
                project_id, str(session_id), candidate_id, "committing", expected_digest=record["digest"],
            )
        else:
            actual = _verified_asset_range(project_id, proposal)
            if actual:
                change_asset_range_candidate_status(
                    project_id, str(session_id), candidate_id, "committed",
                    expected_digest=record["digest"], receipt={"rangeId": actual["rangeId"]},
                )
                return _result(project_id, candidate_id, actual, repeated=True)
            return {"success": False, "status": "commit_unknown",
                    "message": "上次资产范围写入状态尚未核实，请检查项目数据；不会重复提交。",
                    "sessionStatus": "error"}
        try:
            committed = commit_asset_range(project_id, record["commitPayload"])
            actual = _verified_asset_range(project_id, proposal)
            if not actual:
                raise RuntimeError("资产范围写入后回读不一致")
            change_asset_range_candidate_status(
                project_id, str(session_id), candidate_id, "committed",
                expected_digest=record["digest"], receipt={"rangeId": actual["rangeId"]},
            )
            return _result(project_id, candidate_id, actual, changed_resources=committed.get("changedResources"))
        except Exception as exc:
            change_asset_range_candidate_status(
                project_id, str(session_id), candidate_id, "commit_unknown", expected_digest=record["digest"],
            )
            return {"success": False, "status": "commit_unknown",
                    "message": f"资产范围提交未能核验：{exc}。请检查当前项目状态，候选已保留。",
                    "sessionStatus": "error", "pendingOperation": None}


def cancel_asset_range_locally(
    project_id: str, session_id: str | None, *, candidate_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _LOCK:
        record, error = _reference(project_id, session_id, candidate_ref)
        if record is None:
            return {"success": False, "message": error, "sessionStatus": "error"}
        if record["status"] != "awaiting_confirmation":
            return {"success": False, "message": "候选正在提交或已处理，不能取消。", "sessionStatus": "error"}
        change_asset_range_candidate_status(
            project_id, str(session_id), record["candidateId"], "cancelled",
            expected_digest=record["digest"],
        )
        return {"success": True, "message": "已取消该资产范围候选。",
                "contentBlocks": [], "pendingOperation": None,
                "cancelledCandidateId": record["candidateId"],
                "suppressSessionMessage": True, "sessionStatus": "idle",
                "agentModelMeta": {"source": "local-controller", "resultProtocol": "task-result-protocol@v1"}}
