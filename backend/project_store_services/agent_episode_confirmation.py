"""Local confirmation of a saved episode boundary candidate."""
from __future__ import annotations

import traceback
from typing import Any

from .agent_boundary_report import build_boundary_completion_report
from .agent_contracts import _agent_steps_from_state
from .agent_progress_recommendations import _agent_progress_state
from .agent_run_store import (
    change_episode_candidate_status, get_episode_candidate, list_open_episode_candidates,
    stale_other_episode_candidates,
)
from .agent_session_policy import validate_agent_session_pending_operation
from .episode_boundary_planning import commit_episode_boundary
from .episode_boundary_transaction import EPISODE_COMMIT_LOCK, recover_episode_boundary_commit
from .source_coverage import get_source_coverage
from .source_text_store import _episode_source_ref_path, _episode_source_text_path, _sha256_text
from .store_core import _emit_agent_event, _read_json


def _confirmed_episode_range(project_id: str, candidate_id: str) -> dict[str, Any] | None:
    from .agent_sessions import _project_meta_path

    coverage_result = get_source_coverage(project_id)
    coverage = coverage_result.get("coverage") if isinstance(coverage_result.get("coverage"), dict) else {}
    ranges = coverage.get("episodeRanges") if isinstance(coverage.get("episodeRanges"), list) else []
    row = next((item for item in ranges if isinstance(item, dict)
                and str(item.get("proposalId") or "") == candidate_id), None)
    if not row:
        return None
    episode_id = str(row.get("episodeId") or "").strip()
    source_ref = _read_json(_episode_source_ref_path(project_id, episode_id), {})
    text_path = _episode_source_text_path(project_id, episode_id)
    meta = _read_json(_project_meta_path(project_id), {})
    meta_episodes = meta.get("episodes") if isinstance(meta.get("episodes"), list) else []
    actual_text_hash = ""
    if text_path.is_file():
        with text_path.open("r", encoding="utf-8", newline="") as source_file:
            actual_text_hash = _sha256_text(source_file.read())
    if (
        not episode_id or not text_path.is_file()
        or not any(isinstance(item, dict) and str(item.get("id") or "") == episode_id for item in meta_episodes)
        or source_ref.get("proposalId") != candidate_id
        or source_ref.get("textHash") != row.get("textHash")
        or actual_text_hash != row.get("textHash")
    ):
        return None
    return row


def _range_matches_receipt(actual: dict[str, Any] | None, expected: dict[str, Any]) -> bool:
    if not actual:
        return False
    if not expected:
        # A repeated confirmation can find a fully verified commit even if the
        # first tool response was lost before a receipt reached this process.
        return True
    keys = ("absoluteStart", "absoluteEnd", "textHash")
    return all(expected.get(key) is not None and actual.get(key) == expected.get(key) for key in keys)


def _confirmed_episode_result(
    project_id: str, candidate_id: str, actual: dict[str, Any], committed: dict[str, Any],
) -> dict[str, Any]:
    try:
        _emit_agent_event("project_changed", {
            "action": "episode_boundary_committed", "projectId": project_id,
            "episodeId": committed.get("episodeId"),
            "changedResources": committed.get("changedResources") or [],
        })
    except Exception:
        print(traceback.format_exc(), flush=True)
    reply = f"{actual.get('episodeId') or '分集'}已确认并写入项目。"
    return {
        "success": True, "message": reply, "contentBlocks": [],
        "completionReport": build_boundary_completion_report(project_id, actual, kind="episode"),
        "pendingOperation": None, "confirmedCandidateId": candidate_id,
        "suppressSessionMessage": True, "projectChanged": True,
        "completedTaskType": "episode_boundary_confirmed", "sessionStatus": "idle",
        "steps": _agent_steps_from_state(_agent_progress_state(project_id, None)),
        "agentModelMeta": {"source": "local-controller", "resultProtocol": "task-result-protocol@v1"},
        "projectEffect": {
            "projectChanged": True, "changedResources": committed.get("changedResources") or [],
            "focusTarget": committed.get("focusTarget") or {}, "notice": reply,
        },
    }


def confirm_episode_boundary_locally(
    project_id: str,
    session_id: str | None,
    session_policy: dict[str, Any],
    *,
    candidate_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # The commit lock also covers candidate state changes and recovery. It is
    # reentrant because the domain commit acquires it again for file writes.
    with EPISODE_COMMIT_LOCK:
        return _confirm_episode_boundary_locked(
            project_id, session_id, session_policy, candidate_ref=candidate_ref,
        )


def cancel_episode_boundary_locally(
    project_id: str, session_id: str | None, *, candidate_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with EPISODE_COMMIT_LOCK:
        reference = candidate_ref if isinstance(candidate_ref, dict) else {}
        if not reference:
            candidates = list_open_episode_candidates(project_id, session_id)
            if len(candidates) != 1:
                reply = ("当前会话有多个待确认候选，请点击要取消的候选卡片。" if candidates
                         else "当前会话没有可取消的分集候选。")
                return {"success": False, "message": reply,
                        "contentBlocks": [{"type": "text", "text": reply}], "sessionStatus": "idle"}
            candidate = candidates[0]
            reference = {"candidateId": candidate["candidateId"],
                         "candidateDigest": candidate["digest"],
                         "candidateVersion": candidate["version"], "runId": candidate["runId"]}
        candidate_id = str(reference.get("candidateId") or "").strip()
        record = get_episode_candidate(project_id, session_id, candidate_id)
        if (not record or record["status"] != "awaiting_confirmation"
                or str(reference.get("runId") or "") != record["runId"]
                or str(reference.get("candidateDigest") or "") != record["digest"]
                or reference.get("candidateVersion") != record["version"]):
            reply = "该分集候选已处理或版本已变化，请重新查看会话。"
            return {"success": False, "message": reply,
                    "contentBlocks": [{"type": "text", "text": reply}], "sessionStatus": "idle"}
        change_episode_candidate_status(project_id, str(session_id), candidate_id, "cancelled",
                                        expected_digest=record["digest"])
        return {"success": True, "message": "已取消该分集候选。", "contentBlocks": [],
                "cancelledCandidateId": candidate_id,
                "pendingOperation": None, "suppressSessionMessage": True, "sessionStatus": "idle",
                "agentModelMeta": {"source": "local-controller", "resultProtocol": "task-result-protocol@v1"}}


def _confirm_episode_boundary_locked(
    project_id: str,
    session_id: str | None,
    session_policy: dict[str, Any],
    *,
    candidate_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_ref = candidate_ref if isinstance(candidate_ref, dict) else {}
    if not candidate_ref:
        candidates = list_open_episode_candidates(project_id, session_id)
        if len(candidates) != 1:
            reply = ("当前会话有多个待确认候选，请点击要确认的候选卡片。" if candidates
                     else "当前会话没有可确认的分集候选。")
            return {"success": False, "message": reply,
                    "contentBlocks": [{"type": "text", "text": reply}], "sessionStatus": "idle"}
        candidate = candidates[0]
        candidate_ref = {"candidateId": candidate["candidateId"], "candidateDigest": candidate["digest"],
                         "candidateVersion": candidate["version"], "runId": candidate["runId"]}
    requested_id = str(candidate_ref.get("candidateId") or "").strip()
    requested_digest = str(candidate_ref.get("candidateDigest") or "").strip()
    requested_run_id = str(candidate_ref.get("runId") or "").strip()
    requested_version = candidate_ref.get("candidateVersion")
    record = get_episode_candidate(project_id, session_id, requested_id) if requested_id else None
    if (
        not record or not requested_digest or record["digest"] != requested_digest
        or record["runId"] != requested_run_id
        or requested_version != record["version"]
    ):
        reply = "候选版本已变化或当前会话没有展示该候选，请重新打开并审阅候选。"
        return {"success": False, "message": reply, "contentBlocks": [{"type": "text", "text": reply}],
                "sessionStatus": "error"}
    if record["status"] == "committed":
        actual = _confirmed_episode_range(project_id, requested_id)
        if actual:
            committed = {"episodeId": actual.get("episodeId"),
                         "changedResources": ["sourceCoverage", "episodes", "episodeSource"],
                         "focusTarget": {"section": "sources", "episodeId": actual.get("episodeId")}}
            return _confirmed_episode_result(project_id, requested_id, actual, committed)
    proposal = record["proposal"]
    payload = record["commitPayload"]
    candidate_id = record["candidateId"]
    pending = {
        "active": record["status"] == "awaiting_confirmation",
        "status": record["status"], "operationType": "commit_episode_boundary",
        "sessionId": session_id, "runId": record["runId"],
        "candidateDigest": record["digest"], "candidateVersion": record["version"],
        "proposal": proposal, "commitPayload": payload,
    }
    state = _agent_progress_state(project_id, None)
    if record["status"] not in {"awaiting_confirmation", "committing", "commit_unknown"} or not payload:
        reply = "该分集候选已处理或失效，请重新查看当前会话。"
        return {"success": False, "message": reply, "contentBlocks": [{"type": "text", "text": reply}],
                "steps": _agent_steps_from_state(state), "sessionStatus": "error"}
    if record["status"] in {"committing", "commit_unknown"}:
        try:
            validate_agent_session_pending_operation("commit_episode_boundary", session_policy)
            recover_episode_boundary_commit(project_id)
            actual = _confirmed_episode_range(project_id, candidate_id)
        except Exception:
            print(traceback.format_exc(), flush=True)
            reply = "分集写入状态仍无法核实，请不要重复提交。"
            return {"success": False, "message": reply, "contentBlocks": [{"type": "text", "text": reply}],
                    "pendingOperation": pending, "steps": _agent_steps_from_state(state), "sessionStatus": "error"}
        if actual:
            change_episode_candidate_status(project_id, session_id, candidate_id, "committed",
                                            expected_digest=requested_digest, receipt=actual)
            stale_other_episode_candidates(
                project_id, candidate_id,
                f"episode_boundary:{proposal.get('sourceId')}:{proposal.get('startOffset')}",
            )
            committed = {"episodeId": actual.get("episodeId"),
                         "changedResources": ["sourceCoverage", "episodes", "episodeSource"],
                         "focusTarget": {"section": "sources", "episodeId": actual.get("episodeId")}}
            return _confirmed_episode_result(project_id, candidate_id, actual, committed)
        change_episode_candidate_status(project_id, session_id, candidate_id, "awaiting_confirmation",
                                        expected_digest=requested_digest)
        pending["status"] = "active"
        reply = "已核实上次分集写入未完成，项目数据已恢复；候选仍待确认，请重新点击确认。"
        return {"success": False, "message": reply, "contentBlocks": [{"type": "text", "text": reply}],
                "pendingOperation": pending, "steps": _agent_steps_from_state(state), "sessionStatus": "idle"}
    expected: dict[str, Any] = {}
    try:
        validate_agent_session_pending_operation("commit_episode_boundary", session_policy)
        change_episode_candidate_status(project_id, session_id, candidate_id, "committing",
                                        expected_digest=requested_digest)
        committed = commit_episode_boundary(project_id, payload, trusted_proposal=record["proposal"])
        expected = committed.get("range") if isinstance(committed.get("range"), dict) else {}
        actual = _confirmed_episode_range(project_id, candidate_id)
        if not _range_matches_receipt(actual, expected):
            raise RuntimeError("分集写入后核验未通过，请检查项目状态")
    except ValueError as exc:
        try:
            actual = _confirmed_episode_range(project_id, candidate_id)
        except Exception:
            print(traceback.format_exc(), flush=True)
            actual = None
        if not _range_matches_receipt(actual, expected):
            change_episode_candidate_status(project_id, session_id, candidate_id, "stale",
                                            expected_digest=requested_digest)
            reply = f"分集候选未写入：{exc}。请根据当前项目状态重新规划候选。"
            return {"success": False, "message": reply, "contentBlocks": [{"type": "text", "text": reply}],
                    "pendingOperation": pending, "steps": _agent_steps_from_state(state), "sessionStatus": "error"}
        committed = {
            "episodeId": actual.get("episodeId"),
            "changedResources": ["sourceCoverage", "episodes", "episodeSource"],
            "focusTarget": {"section": "sources", "episodeId": actual.get("episodeId")},
        }
    except Exception:
        print(traceback.format_exc(), flush=True)
        recovered = False
        try:
            recover_episode_boundary_commit(project_id)
            recovered = True
            actual = _confirmed_episode_range(project_id, candidate_id)
        except Exception:
            print(traceback.format_exc(), flush=True)
            actual = None
        if not _range_matches_receipt(actual, expected):
            if recovered and not actual:
                change_episode_candidate_status(project_id, session_id, candidate_id, "awaiting_confirmation",
                                                expected_digest=requested_digest)
                reply = "分集写入失败，已恢复原有数据；候选仍待确认，可检查项目状态后重试。"
            else:
                change_episode_candidate_status(project_id, session_id, candidate_id, "commit_unknown",
                                                expected_digest=requested_digest)
                reply = "分集写入状态需要核查，请不要重复确认。"
                pending["status"] = "commit_unknown"
            return {"success": False, "message": reply, "contentBlocks": [{"type": "text", "text": reply}],
                    "pendingOperation": pending, "steps": _agent_steps_from_state(state), "sessionStatus": "error"}
        committed = {
            "episodeId": actual.get("episodeId"),
            "changedResources": ["sourceCoverage", "episodes", "episodeSource"],
            "focusTarget": {"section": "sources", "episodeId": actual.get("episodeId")},
        }
    change_episode_candidate_status(project_id, session_id, candidate_id, "committed",
                                    expected_digest=requested_digest, receipt=actual)
    stale_other_episode_candidates(
        project_id, candidate_id,
        f"episode_boundary:{proposal.get('sourceId')}:{proposal.get('startOffset')}",
    )
    return _confirmed_episode_result(project_id, candidate_id, actual, committed)
