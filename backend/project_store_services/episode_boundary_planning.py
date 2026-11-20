# -*- coding: utf-8 -*-
"""分集候选校验、暂存与确认后的原文提交。"""
from __future__ import annotations

from .catalogs import DEFAULT_EPISODE_TARGET_UNITS
from .episode_boundary_transaction import EPISODE_COMMIT_LOCK, episode_boundary_transaction, recover_episode_boundary_commit
from .project_resource_revisions import _append_resource_revision
from .project_resource_revisions import _assert_resource_write_guard
from .project_resource_revisions import _payload_first_present
from .project_resource_revisions import _payload_first_present_from_sources
from .project_resource_revisions import _resource_revision_value
from .source_boundary_contract import _commit_next_step
from .source_boundary_contract import _episode_boundary_asset_cursor_end
from .source_boundary_contract import _episode_boundary_commit_payload
from .source_boundary_contract import _episode_boundary_pending_matches_payload
from .source_boundary_contract import _episode_boundary_planning_window_end
from .source_boundary_contract import _episode_boundary_risk_notes
from .source_boundary_contract import _episode_boundary_text_length_issue
from .source_boundary_contract import _episode_boundary_title_context
from .source_boundary_contract import _episode_boundary_title_from_payload
from .source_boundary_contract import _episode_boundary_tolerance_units
from .source_boundary_contract import _episode_title_rules_payload
from .source_boundary_contract import _genre_context_policy_for_stage
from .source_boundary_contract import _match_source_boundary_text_end
from .source_boundary_contract import _next_episode_id
from .source_boundary_contract import _normalize_episode_boundary_title
from .source_boundary_contract import _project_genre_context
from .source_boundary_contract import _range_source_excerpt
from .source_boundary_contract import _unwrap_agent_commit_payload
from .source_coverage import _episode_asset_coverage_gap
from .source_coverage import _episode_requires_asset_extraction_response
from .source_coverage import _load_source_coverage
from .source_coverage import _write_source_coverage
from .source_text_store import _compact_text
from .source_text_store import _episode_source_ref_path
from .source_text_store import _episode_source_text_path
from .source_text_store import _read_source_content
from .source_text_store import _select_project_sources
from .source_text_store import _sha256_text
from .store_core import _JSON_WRITE_LOCK
from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json
from typing import Any
from utils.text_metrics import content_char_count
from utils.text_metrics import content_offset_after_units
import copy
import shutil
import uuid
from .agent_episode_boundary_tools import (
    episode_boundary_inputs, episode_boundary_context_version, assert_episode_revision_safe,
)


def _stage_episode_boundary_candidate(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload or {}
    genre_context = _project_genre_context(project_id)
    genre_context_policy = _genre_context_policy_for_stage("episode_boundary")
    data = episode_boundary_inputs(project_id, str(payload.get("episodeId") or ""))
    coverage, source_id, content = data["coverage"], data["sourceId"], data["content"]
    total_chars = len(content)
    start, target_units = data["start"], data["targetUnits"]
    episode_id = data["episodeId"]
    version = episode_boundary_context_version(data)
    if payload.get("contextVersion") and payload["contextVersion"] != version:
        return {"success": False, "error": "source_revision_conflict", "message": "分集资料已变化，请重新读取正文和规划状态"}
    proposal_id = f"ep-boundary-{uuid.uuid4().hex[:8]}"
    boundary_tolerance_units = _episode_boundary_tolerance_units(payload, target_units)
    target_end = content_offset_after_units(content, start, target_units)
    initial_gap = _episode_asset_coverage_gap(
        coverage,
        project_id=project_id,
        source_id=source_id,
        start=start,
        required_end=target_end,
        total_chars=total_chars,
    )
    if initial_gap:
        return _episode_requires_asset_extraction_response(
            coverage,
            initial_gap,
            genre_context=genre_context,
            genre_context_policy=genre_context_policy,
        )
    planning_upper_limit = content_offset_after_units(
        content,
        start,
        target_units + boundary_tolerance_units,
    )
    asset_cursor_offset = _episode_boundary_asset_cursor_end(coverage, total_chars)
    if asset_cursor_offset > start:
        planning_upper_limit = min(planning_upper_limit, asset_cursor_offset)
    planning_upper = _episode_boundary_planning_window_end(
        content,
        start,
        target_units,
        boundary_tolerance_units,
        planning_upper_limit,
    )
    if planning_upper <= start:
        return _episode_requires_asset_extraction_response(
            coverage,
            {
                "sourceId": source_id,
                "episodeStartOffset": start,
                "episodeRequiredEndOffset": target_end,
                "assetCursorOffset": asset_cursor_offset,
                "reason": f"资产拆分游标只覆盖到 {asset_cursor_offset}，不足以进行分集断点规划。",
            },
            genre_context=genre_context,
            genre_context_policy=genre_context_policy,
        )
    planning_lookahead_units = 0
    boundary_end_text = str(payload.get("boundaryEndText") or "").strip()
    min_boundary_end = min(
        planning_upper,
        content_offset_after_units(content, start, max(1, target_units - boundary_tolerance_units)),
    )
    current = data["currentEpisode"]
    if current and boundary_end_text == str(current.get("boundaryEndText") or "").strip():
        # Retitling an existing episode does not reapply a changed length target.
        planning_upper = min_boundary_end = int(current["absoluteEnd"])
    match_result = _match_source_boundary_text_end(
        content, start, planning_upper, boundary_end_text, min_boundary_end=min_boundary_end,
    )
    length_issue = (
        _episode_boundary_text_length_issue(
            boundary_end_text,
            available_text=content[start:int(match_result["endOffset"])],
        )
        if match_result.get("status") == "unique"
        else ""
    )
    if match_result.get("status") != "unique" or length_issue:
        return {
            "success": False,
            "error": "episode_boundary_candidate_invalid",
            "message": str(length_issue or match_result.get("reason") or "断点尾句无效，请重新检查原文后提交候选。"),
            "planningWindow": {"startOffset": start, "endOffset": planning_upper, "minBoundaryEndOffset": min_boundary_end},
            "boundaryMatch": match_result,
            "coverage": coverage,
        }
    boundary_end = int(match_result["endOffset"])
    try:
        assert_episode_revision_safe(project_id, coverage, episode_id, boundary_end)
    except ValueError as exc:
        return {"success": False, "error": "episode_revision_blocked", "message": str(exc)}
    recommended_gap = _episode_asset_coverage_gap(
        coverage,
        project_id=project_id,
        source_id=source_id,
        start=start,
        required_end=boundary_end,
        total_chars=total_chars,
    )
    if recommended_gap:
        return _episode_requires_asset_extraction_response(
            coverage,
            recommended_gap,
            genre_context=genre_context,
            genre_context_policy=genre_context_policy,
        )
    recommended_end = boundary_end
    proposed_text = content[start:recommended_end].strip()
    proposed_units = content_char_count(proposed_text)
    episode_title = _episode_boundary_title_from_payload(payload, episode_id)
    reason = _compact_text(
        str(payload.get("reason") or "按智能体核验的剧情断点规划分集。"),
        180,
    )
    risk_notes = _episode_boundary_risk_notes(payload.get("riskNotes") or [])
    proposal = {
        "proposalId": proposal_id,
        "episodeId": episode_id,
        "title": episode_title,
        "episodeTitle": episode_title,
        "titleRequired": True,
        "titleRules": _episode_title_rules_payload(),
        "titleContext": _episode_boundary_title_context(content, start, recommended_end),
        "sourceId": source_id,
        "startOffset": start,
        "recommendedEndOffset": recommended_end,
        "targetUnits": target_units,
        "actualUnits": proposed_units,
        "reason": reason,
        "boundaryReason": reason,
        "boundaryEndText": boundary_end_text,
        "boundaryToleranceUnits": boundary_tolerance_units,
        "planningLookaheadUnits": planning_lookahead_units,
        "planningWindowEnd": planning_upper,
        "planningMethod": "agent_episode_boundary",
        "boundaryMatchMode": str(match_result.get("matchMode") or ""),
        "planningModelMeta": {"source": "claude-agent-sdk-skill"},
        "contextVersion": version,
        "revisionEpisodeId": episode_id if current else "",
        "hook": _range_source_excerpt(content, start, min(total_chars, start + 160), 120),
        "endingQuestion": "",
        "genreContext": genre_context,
        "genreContextPolicy": genre_context_policy if genre_context else "",
        "riskNotes": risk_notes,
        "excerpt": _range_source_excerpt(content, start, recommended_end),
        "createdAt": _now(),
    }
    commit_payload = _episode_boundary_commit_payload(proposal, coverage)
    response = {
        "success": True,
        "proposal": proposal,
        "episodeSourceText": {
            "episodeId": episode_id,
            "title": episode_title,
            "sourceId": source_id,
            "text": proposed_text,
            "charCount": proposed_units,
        },
        "commitPayload": commit_payload,
        "nextStep": _commit_next_step("commit_episode_boundary"),
        "requiresUserConfirmation": True,
        "coverage": coverage,
    }
    if genre_context:
        response["genreContext"] = genre_context
        response["genreContextPolicy"] = genre_context_policy
    return response


def submit_episode_boundary_candidate(project_id: str, candidate: dict[str, Any] | None = None,
                                      *, session_id: str | None = None,
                                      requirement_text: str = "") -> dict[str, Any]:
    """Validate an SDK-selected boundary without issuing another model request."""
    from .agent_run_store import stage_episode_candidate

    candidate = candidate if isinstance(candidate, dict) else {}
    if not session_id:
        return {"success": False, "status": "rejected", "error": "session_required",
                "message": "分集候选缺少所属会话", "errors": [{"code": "session_required",
                "path": "sessionId", "message": "请从项目会话重新执行任务", "repairAction": "stop"}]}
    title = _normalize_episode_boundary_title(candidate.get("episodeTitle") or candidate.get("title"))
    if not title:
        result = {"success": False, "error": "episode_boundary_title_required", "message": "请为本集提供具体的短标题，不能只写集数。"}
    elif not str(candidate.get("reason") or "").strip():
        result = {"success": False, "error": "episode_boundary_reason_required", "message": "请说明这个原文断点为何能形成完整的当集落点。"}
    else:
        try:
            data = episode_boundary_inputs(project_id, str(candidate.get("episodeId") or ""))
            if candidate.get("contextVersion") != episode_boundary_context_version(data):
                return {"success": False, "status": "rejected", "message": "原文、目标字数或覆盖状态已变化，请重新读取正文和规划状态", "projectChanged": False,
                        "errors": [{"code": "source_revision_conflict", "path": "contextVersion",
                                    "message": "请重新读取同一目标的正文和规划状态后提交", "repairAction": "refresh_context"}]}
            result = _existing_agent_episode_candidate(project_id, session_id, candidate, title) or _stage_episode_boundary_candidate(project_id, {
                "boundaryEndText": candidate.get("boundaryEndText"),
                "episodeTitle": title,
                "reason": candidate.get("reason"),
                "riskNotes": candidate.get("riskNotes"),
                "episodeId": candidate.get("episodeId"),
                "contextVersion": candidate.get("contextVersion"),
            })
        except ValueError as exc:
            result = {"success": False, "error": "source_context_invalid", "message": str(exc)}
    if result.get("success") and result.get("requiresUserConfirmation"):
        record = stage_episode_candidate(project_id, session_id, result["proposal"],
                                         result["commitPayload"], requirement_text)
        return {**result, **record, "status": "pending_confirmation"}
    error_code = str(result.get("error") or "episode_boundary_rejected").strip()
    repair_action = (
        "refresh_context" if error_code in {"source_coverage_conflict", "source_revision_conflict", "source_context_invalid"}
        else "stop" if result.get("requiresAssetExtraction") or error_code == "episode_revision_blocked"
        else "revise_payload"
    )
    error_path = (
        "episodeTitle" if error_code == "episode_boundary_title_required"
        else "reason" if error_code == "episode_boundary_reason_required"
        else "sourceCoverage" if repair_action in {"refresh_context", "stop"}
        else "boundaryEndText"
    )
    return {
        **result,
        "success": False,
        "status": "rejected",
        "errors": [{"code": error_code, "path": error_path, "message": str(result.get("message") or "候选未通过校验"),
                    "repairAction": repair_action}],
    }


def _existing_agent_episode_candidate(project_id: str, session_id: str,
                                      candidate: dict[str, Any], title: str) -> dict[str, Any] | None:
    """Return the same saved candidate when a lost tool reply causes a retry."""
    from .agent_run_store import refresh_episode_candidate_freshness

    coverage = _load_source_coverage(project_id)
    saved = refresh_episode_candidate_freshness(project_id, session_id)
    if not saved or saved["status"] != "awaiting_confirmation":
        return None
    pending = saved.get("proposal") if isinstance(saved, dict) and isinstance(saved.get("proposal"), dict) else {}
    cursor = coverage.get("episodeCursor") if isinstance(coverage.get("episodeCursor"), dict) else {}
    if (
        pending.get("planningMethod") != "agent_episode_boundary"
        or pending.get("contextVersion") != candidate.get("contextVersion")
        or str(pending.get("episodeTitle") or "") != title
        or str(pending.get("boundaryEndText") or "").strip() != str(candidate.get("boundaryEndText") or "").strip()
        or str(pending.get("reason") or "").strip() != _compact_text(str(candidate.get("reason") or ""), 180).strip()
        or _episode_boundary_risk_notes(pending.get("riskNotes") or []) != _episode_boundary_risk_notes(candidate.get("riskNotes") or [])
        or int(pending.get("startOffset") if pending.get("startOffset") is not None else -1) != int(cursor.get("nextOffset") or 0)
        or str(pending.get("sourceId") or "") != str(coverage.get("sourceId") or "")
    ):
        return None
    source = _select_project_sources(project_id, str(pending.get("sourceId") or ""))[0]
    content = _read_source_content(project_id, source)
    start = int(pending.get("startOffset") or 0)
    end = int(pending.get("recommendedEndOffset") or 0)
    if end <= start or end > len(content):
        return None
    episode_id = str(pending.get("episodeId") or "")
    return {
        "success": True, "proposal": copy.deepcopy(pending),
        "episodeSourceText": {"episodeId": episode_id, "title": title,
                              "sourceId": pending.get("sourceId"), "text": content[start:end].strip(),
                              "charCount": content_char_count(content[start:end].strip())},
        "commitPayload": copy.deepcopy(saved["commitPayload"]),
        "nextStep": _commit_next_step("commit_episode_boundary"),
        "requiresUserConfirmation": True, "coverage": coverage,
        "reusedCandidate": True,
    }


def _ensure_episode_meta_entry(
    project_id: str,
    episode_id: str,
    title: str,
    source_ref: dict[str, Any],
    *,
    title_locked: bool | None = None,
    title_source: str = "",
) -> None:
    from .agent_sessions import _project_meta_path
    meta = _read_json(_project_meta_path(project_id), {})
    episodes = meta.get("episodes") if isinstance(meta.get("episodes"), list) else []
    episodes = [copy.deepcopy(item) for item in episodes if isinstance(item, dict)]
    match = next((item for item in episodes if str(item.get("id") or "") == episode_id), None)
    if match is None:
        match = {"id": episode_id}
        episodes.append(match)
    current_source_ref = match.get("sourceRef") if isinstance(match.get("sourceRef"), dict) else {}
    existing_title = _normalize_episode_boundary_title(match.get("title"), episode_id)
    next_title = _normalize_episode_boundary_title(title, episode_id)
    existing_locked = bool(
        match.get("titleLocked")
        or current_source_ref.get("titleLocked")
        or (source_ref if isinstance(source_ref, dict) else {}).get("titleLocked")
    )
    should_update_title = bool(next_title) and (
        title_locked is True or not existing_locked or not existing_title
    )
    display_title = next_title if should_update_title else (existing_title or next_title or episode_id)
    meta_patch = {
        "id": episode_id,
        "title": display_title,
        "status": "已提交原文断点，等待生成片段剧本/分镜脚本",
        "wordCount": source_ref.get("charCount") or 0,
        "sourceRef": source_ref,
        "sourcePath": f"episodes/{episode_id}/source.txt",
    }
    if current_source_ref.get("textHash") == source_ref.get("textHash") and match.get("status"):
        meta_patch["status"] = match["status"]
    if title_locked is not None:
        meta_patch["titleLocked"] = bool(title_locked)
    elif existing_locked:
        meta_patch["titleLocked"] = True
    if title_source:
        meta_patch["titleSource"] = title_source
    elif match.get("titleSource"):
        meta_patch["titleSource"] = match.get("titleSource")
    match.update(
        meta_patch
    )
    meta["episodes"] = episodes
    meta["episode_count"] = len(episodes)
    meta["status_type"] = "running"
    meta["status"] = f"{episode_id} 原文断点已提交"
    meta["updated_at"] = _now()
    _write_json(_project_meta_path(project_id), meta)


def _verify_episode_commit_files(project_id: str, episode_id: str, proposal_id: str, text_hash: str) -> None:
    from .agent_sessions import _project_meta_path
    from .source_coverage import _source_coverage_path

    coverage = _read_json(_source_coverage_path(project_id), {})
    ranges = coverage.get("episodeRanges") if isinstance(coverage.get("episodeRanges"), list) else []
    stored_range = next((row for row in ranges if isinstance(row, dict)
                         and row.get("proposalId") == proposal_id), None)
    source_ref = _read_json(_episode_source_ref_path(project_id, episode_id), {})
    meta = _read_json(_project_meta_path(project_id), {})
    episodes = meta.get("episodes") if isinstance(meta.get("episodes"), list) else []
    text_path = _episode_source_text_path(project_id, episode_id)
    if not text_path.is_file():
        raise RuntimeError("分集提交后的原文文件缺失")
    with text_path.open("r", encoding="utf-8", newline="") as source_file:
        actual_hash = _sha256_text(source_file.read())
    if (
        not stored_range or stored_range.get("episodeId") != episode_id
        or stored_range.get("textHash") != text_hash
        or source_ref.get("proposalId") != proposal_id
        or source_ref.get("textHash") != text_hash
        or actual_hash != text_hash
        or not any(isinstance(row, dict) and row.get("id") == episode_id for row in episodes)
    ):
        raise RuntimeError("分集提交后回读核验未通过")


def commit_episode_boundary(project_id: str, payload: dict[str, Any],
                            *, trusted_proposal: dict[str, Any]) -> dict[str, Any]:
    with EPISODE_COMMIT_LOCK, _JSON_WRITE_LOCK:
        recover_episode_boundary_commit(project_id)
        return _commit_episode_boundary_locked(project_id, payload, trusted_proposal)


def _commit_episode_boundary_locked(project_id: str, payload: dict[str, Any],
                                    trusted_proposal: dict[str, Any]) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    from .agent_sessions import _project_meta_path
    if not isinstance(payload, dict):
        raise ValueError("缺少分集断点参数")
    payload = _unwrap_agent_commit_payload(payload)
    coverage = _load_source_coverage(project_id, payload.get("sourceId") or payload.get("source_id"))
    expected_revision = _payload_first_present(payload, "expectedRevision", "expected_revision")
    base_hash = _payload_first_present(payload, "baseHash", "base_hash")
    if expected_revision is None or not str(expected_revision).strip() or not str(base_hash or "").strip():
        raise ValueError("分集断点提交缺少 sourceCoverage 校验信息；请重新生成分集候选。")
    _assert_resource_write_guard(
        coverage,
        expected_revision,
        base_hash,
    )
    coverage_before = copy.deepcopy(coverage)
    pending = copy.deepcopy(trusted_proposal) if isinstance(trusted_proposal, dict) else {}
    proposal = pending
    if pending.get("contextVersion"):
        current_inputs = episode_boundary_inputs(project_id, str(pending.get("revisionEpisodeId") or ""))
        if pending["contextVersion"] != episode_boundary_context_version(current_inputs):
            raise ValueError("候选读取后分集资料已变化，请重新读取并生成候选")
    if not _episode_boundary_pending_matches_payload(pending, payload, proposal):
        raise ValueError("分集断点提交必须匹配后端保存的智能体断点候选；请重新生成分集候选。")
    source_id = str(payload.get("sourceId") or proposal.get("sourceId") or pending.get("sourceId") or coverage.get("sourceId") or "")
    source = _select_project_sources(project_id, source_id)[0]
    content = _read_source_content(project_id, source)
    total_chars = len(content)
    cursor = coverage.get("episodeCursor") if isinstance(coverage.get("episodeCursor"), dict) else {}
    saved_start = _payload_first_present_from_sources([payload, proposal, pending], "startOffset", "start_offset")
    start = int(saved_start if saved_start is not None else cursor.get("nextOffset") or 0)
    end = int(
        payload.get("endOffset")
        or payload.get("absoluteEnd")
        or payload.get("recommendedEndOffset")
        or proposal.get("recommendedEndOffset")
        or pending.get("recommendedEndOffset")
        or 0
    )
    if end <= start or end > total_chars:
        raise ValueError("分集断点范围无效")
    asset_gap = _episode_asset_coverage_gap(
        coverage,
        project_id=project_id,
        source_id=source_id,
        start=start,
        required_end=end,
        total_chars=total_chars,
    )
    if asset_gap:
        raise ValueError(f"{asset_gap.get('reason')}请先提交并拆分下一段资产范围，再继续提交分集断点。")
    planning_method = str(
        payload.get("planningMethod")
        or proposal.get("planningMethod")
        or pending.get("planningMethod")
        or ""
    ).strip()
    boundary_end_text = str(
        payload.get("boundaryEndText")
        or proposal.get("boundaryEndText")
        or pending.get("boundaryEndText")
        or ""
    ).strip()
    if planning_method != "agent_episode_boundary" or not boundary_end_text:
        raise ValueError("分集断点提交必须来自智能体断点候选；请重新生成分集候选。")
    boundary_match = _match_source_boundary_text_end(
        content,
        start,
        end,
        boundary_end_text,
        min_boundary_end=end,
    )
    located_boundary_end = boundary_match.get("endOffset") if boundary_match.get("status") == "unique" else None
    if located_boundary_end != end:
        raise ValueError("分集断点提交的断点末尾原文与结束位置不一致；请重新生成分集候选。")
    episode_id = str(payload.get("episodeId") or payload.get("episode_id") or proposal.get("episodeId") or pending.get("episodeId") or _next_episode_id(coverage)).strip()
    if not episode_id:
        raise ValueError("缺少 episodeId")
    ranges = [item for item in coverage.get("episodeRanges", []) if isinstance(item, dict)]
    replace_index = next(
        (
            index
            for index, item in enumerate(ranges)
            if str(item.get("episodeId") or "") == episode_id
        ),
        -1,
    )
    removed_episode_ids: list[str] = []
    if replace_index >= 0:
        existing = ranges[replace_index]
        existing_start = int(existing.get("absoluteStart") or 0)
        if start != existing_start:
            raise ValueError(f"重提 {episode_id} 断点必须从原起点 {existing_start} 开始，收到 {start}")
        assert_episode_revision_safe(project_id, coverage, episode_id, end)
        # Keep directories, downstream data and later episodes. Only this row
        # is replaced; moving a non-last boundary was rejected above.
        coverage["episodeRanges"] = [row for index, row in enumerate(ranges) if index != replace_index]
    else:
        expected_start = int(cursor.get("nextOffset") or 0)
        if start != expected_start:
            raise ValueError(f"分集断点必须从当前游标 {expected_start} 开始，收到 {start}")
    for item in coverage.get("episodeRanges", []):
        if not isinstance(item, dict):
            continue
        existing_start = int(item.get("absoluteStart") or 0)
        existing_end = int(item.get("absoluteEnd") or 0)
        if max(start, existing_start) < min(end, existing_end):
            raise ValueError("分集断点与已提交范围重叠")
    text = content[start:end].strip()
    text_units = content_char_count(text)
    text_hash = _sha256_text(text)
    title = (
        _episode_boundary_title_from_payload(payload, episode_id)
        or _episode_boundary_title_from_payload(proposal, episode_id)
        or _episode_boundary_title_from_payload(pending, episode_id)
    )
    if not title:
        raise ValueError(
            "分集标题缺失：请先按分集标题取名约束，从本集原文提炼短标题，并通过 title 或 episodeTitle 传入。"
        )
    reason = str(payload.get("boundaryReason") or payload.get("reason") or proposal.get("reason") or pending.get("reason") or "")
    risk_notes = _episode_boundary_risk_notes(
        payload.get("riskNotes")
        or proposal.get("riskNotes")
        or pending.get("riskNotes")
        or []
    )
    with episode_boundary_transaction(project_id, [*removed_episode_ids, episode_id]):
        # Complete deterministic validation before removing any older episode files.
        if removed_episode_ids:
            project_root = _project_dir(project_id).resolve()
            for removed_episode_id in removed_episode_ids:
                episode_path = (_project_dir(project_id) / "episodes" / removed_episode_id).resolve()
                try:
                    episode_path.relative_to(project_root)
                except ValueError:
                    continue
                if episode_path.exists() and episode_path.is_dir():
                    shutil.rmtree(episode_path)
            meta = _read_json(_project_meta_path(project_id), {})
            episodes = meta.get("episodes") if isinstance(meta.get("episodes"), list) else []
            meta["episodes"] = [
                item for item in episodes
                if not isinstance(item, dict) or str(item.get("id") or "") not in set(removed_episode_ids)
            ]
            meta["episode_count"] = len(meta["episodes"])
            meta["updated_at"] = _now()
            _write_json(_project_meta_path(project_id), meta)
        episode_dir = _project_dir(project_id) / "episodes" / episode_id
        episode_dir.mkdir(parents=True, exist_ok=True)
        _episode_source_text_path(project_id, episode_id).write_text(text, encoding="utf-8", newline="\n")
        source_ref = {
            "proposalId": str(pending.get("proposalId") or ""),
            "episodeId": episode_id,
            "title": title,
            "episodeTitle": title,
            "titleLocked": True,
            "titleSource": "episode_boundary",
            "titleRulesVersion": "episode_title_memory_hook_v1",
            "sourceId": source_id,
            "absoluteStart": start,
            "absoluteEnd": end,
            "charCount": text_units,
            "textHash": text_hash,
            "boundaryReason": reason,
            "boundaryEndText": boundary_end_text,
            "planningMethod": planning_method,
            "boundaryToleranceUnits": _payload_first_present_from_sources(
                [payload, proposal, pending],
                "boundaryToleranceUnits",
                "boundary_tolerance_units",
            ),
            "planningLookaheadUnits": _payload_first_present_from_sources(
                [payload, proposal, pending],
                "planningLookaheadUnits",
                "planning_lookahead_units",
            ),
            "planningWindowEnd": _payload_first_present_from_sources(
                [payload, proposal, pending],
                "planningWindowEnd",
                "planning_window_end",
            ),
            "riskNotes": risk_notes,
            "committedBy": str(payload.get("committedBy") or payload.get("committed_by") or "agent"),
            "committedAt": _now(),
        }
        _write_json(_episode_source_ref_path(project_id, episode_id), source_ref)
        range_row = {
            "proposalId": str(pending.get("proposalId") or ""),
            "episodeId": episode_id,
            "title": title,
            "episodeTitle": title,
            "titleLocked": True,
            "titleSource": "episode_boundary",
            "titleRulesVersion": "episode_title_memory_hook_v1",
            "sourceId": source_id,
            "absoluteStart": start,
            "absoluteEnd": end,
            "targetUnits": int(payload.get("targetUnits") or payload.get("target_units") or cursor.get("targetUnits") or DEFAULT_EPISODE_TARGET_UNITS),
            "actualUnits": text_units,
            "charCount": text_units,
            "status": "committed",
            "boundaryReason": reason,
            "boundaryEndText": boundary_end_text,
            "planningMethod": planning_method,
            "boundaryToleranceUnits": _payload_first_present_from_sources(
                [payload, proposal, pending],
                "boundaryToleranceUnits",
                "boundary_tolerance_units",
            ),
            "planningLookaheadUnits": _payload_first_present_from_sources(
                [payload, proposal, pending],
                "planningLookaheadUnits",
                "planning_lookahead_units",
            ),
            "planningWindowEnd": _payload_first_present_from_sources(
                [payload, proposal, pending],
                "planningWindowEnd",
                "planning_window_end",
            ),
            "riskNotes": risk_notes,
            "textHash": text_hash,
            "relativePath": f"episodes/{episode_id}/source.txt",
            "createdAt": _now(),
        }
        if replace_index >= 0:
            coverage["episodeRanges"].insert(replace_index, range_row)
        else:
            coverage.setdefault("episodeRanges", []).append(range_row)
        if replace_index < 0 or replace_index == len(ranges) - 1:
            coverage.setdefault("episodeCursor", {})["nextOffset"] = end
            coverage["episodeCursor"]["lastEpisodeId"] = episode_id
        _append_resource_revision(
            project_id,
            resource="sourceCoverage",
            relative_path="source_coverage.json",
            document=coverage_before,
            reason=str(payload.get("reason") or "commit_episode_boundary"),
            user_instruction=str(payload.get("userInstruction") or payload.get("user_instruction") or ""),
        )
        coverage["revision"] = _resource_revision_value(coverage_before) + 1
        _write_source_coverage(project_id, coverage)
        _ensure_episode_meta_entry(
            project_id,
            episode_id,
            title,
            source_ref,
            title_locked=True,
            title_source="episode_boundary",
        )
        _verify_episode_commit_files(project_id, episode_id, str(pending.get("proposalId") or ""), text_hash)
    return {
        "success": True,
        "message": f"{episode_id} 原文断点已提交。",
        "episodeId": episode_id,
        "sourceRef": source_ref,
        "range": range_row,
        "coverage": coverage,
        "changedResources": ["sourceCoverage", "episodes", "episodeSource"],
        "resetEpisodeIds": removed_episode_ids,
        "focusTarget": {"section": "sources", "episodeId": episode_id},
        "projectChanged": True,
    }
