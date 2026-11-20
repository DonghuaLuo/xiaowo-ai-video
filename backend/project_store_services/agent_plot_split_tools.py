# -*- coding: utf-8 -*-
"""Project-bound read and candidate submission tools for native plot splitting."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from typing import Any

from .agent_pending_operations import (
    _plot_split_next_revision_state,
    _plot_split_pending_operation,
)
from .agent_plot_contract import _plot_split_proposal_block, _plot_split_proposal_message
from .canvas_store_queries import get_canvas_context_v4
from .plot_split_one_request import (
    ASSET_TYPES,
    compact_plot_asset_catalog,
    proposal_from_one_request,
    resolve_plot_split_source_range_text,
)
from .source_text_store import get_episode_source_text
from .worker_plot_validation import validate_plot_splitting_worker_output
from .worker_task_context import _asset_name_rows, _filter_plot_splitting_candidate_assets


_SEGMENT_FIELDS = frozenset({"text", "title", "splitReason", "excludedTexts", *ASSET_TYPES})


def _stable_digest(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def plot_split_source_digest(source_ref: dict[str, Any], source_text: str) -> str:
    """Fingerprint the committed source used by a candidate, including its range."""
    return _stable_digest({"sourceRef": source_ref, "sourceText": source_text})


def plot_split_candidate_digest(proposal: dict[str, Any]) -> str:
    return _stable_digest(proposal)


def _field_error(path: str, code: str, message: str, *, repair_action: str = "revise_and_resubmit") -> dict[str, str]:
    return {"path": path, "code": code, "message": message, "repairAction": repair_action}


def _failure(errors: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "success": False,
        "status": "validation_failed",
        "message": errors[0]["message"] if errors else "剧情拆分候选未通过校验",
        "errors": errors,
        "projectChanged": False,
    }


def _plot_split_inputs(project_id: str, episode_id: str, *, include_assets: bool = True) -> dict[str, Any]:
    source = get_episode_source_text(project_id, episode_id)
    if not source.get("available"):
        raise ValueError(f"{episode_id} 缺少已提交分集原文")
    source_ref = source.get("sourceRef") if isinstance(source.get("sourceRef"), dict) else {}
    if not source_ref:
        raise ValueError(f"{episode_id} 缺少已提交 source range")
    source_text = resolve_plot_split_source_range_text(
        project_id, str(source.get("text") or ""), source_ref,
    )
    assets = _filter_plot_splitting_candidate_assets(
        _asset_name_rows(
            project_id, include_desc=True, source_ref=source_ref,
            include_state_versions=False, desc_limit=500,
        )
    ) if include_assets else {}
    return {
        "episodeId": episode_id,
        "episodeTitle": str(source.get("title") or episode_id),
        "sourceText": source_text,
        "sourceRef": copy.deepcopy(source_ref),
        "sourceDigest": plot_split_source_digest(source_ref, source_text),
        "assets": assets,
    }


def get_plot_split_context(project_id: str, episode_id: str, *, part: str) -> dict[str, Any]:
    """Return one task datum per read; never mix episode prose with the catalog."""
    if part not in {"source_text", "asset_catalog"}:
        return _failure([_field_error("part", "invalid_part", "请选择本集原文或可关联资产", repair_action="stop")])
    try:
        canvas = get_canvas_context_v4(project_id, episode_id)
        if canvas.get("canvasKind") == "custom" or canvas.get("autoWorkflowInitialized"):
            return _failure([_field_error(
                "episodeId", "canvas_already_initialized",
                "当前画布已有正式工作链，请先处理现有结果，不能直接覆盖重建", repair_action="stop",
            )])
        context = _plot_split_inputs(project_id, episode_id, include_assets=part == "asset_catalog")
    except (ValueError, FileNotFoundError) as exc:
        return _failure([_field_error("episodeId", "source_unavailable", str(exc), repair_action="stop")])
    if part == "source_text":
        return {"success": True, "sourceText": context["sourceText"]}
    return {"success": True, "assets": compact_plot_asset_catalog(context["assets"])}


def _segment_shape_errors(segments: Any) -> list[dict[str, str]]:
    if not isinstance(segments, list) or not segments:
        return [_field_error("segments", "required", "segments 必须是非空数组")]
    errors: list[dict[str, str]] = []
    for index, segment in enumerate(segments):
        path = f"segments[{index}]"
        if not isinstance(segment, dict):
            errors.append(_field_error(path, "invalid_type", "每个剧情片段必须是对象"))
            continue
        unknown = sorted(set(segment) - _SEGMENT_FIELDS)
        if unknown:
            errors.append(_field_error(
                path, "unsupported_field",
                f"剧情片段包含不允许的字段：{', '.join(unknown)}；来源坐标由后端推导",
            ))
        if not isinstance(segment.get("text"), str) or not segment["text"].strip():
            errors.append(_field_error(f"{path}.text", "required", "剧情片段缺少连续原文 text"))
        if not isinstance(segment.get("title"), str) or not segment["title"].strip():
            errors.append(_field_error(f"{path}.title", "required", "每段剧情需要体现本段行动的标题"))
        if not isinstance(segment.get("splitReason"), str) or not segment["splitReason"].strip():
            errors.append(_field_error(f"{path}.splitReason", "required", "每段剧情需要说明该行动的边界依据"))
        excluded = segment.get("excludedTexts", [])
        if not isinstance(excluded, list) or any(not isinstance(value, str) or not value.strip() for value in excluded):
            errors.append(_field_error(f"{path}.excludedTexts", "invalid_exclusions", "清理片段必须是按原文顺序排列的非空原文字符串数组"))
        for kind in ASSET_TYPES:
            ids = segment.get(kind)
            if not isinstance(ids, list) or any(not isinstance(value, str) or not value.strip() for value in ids):
                errors.append(_field_error(
                    f"{path}.{kind}", "invalid_asset_ids", f"{kind} 必须是资产 ID 字符串数组，可为空数组",
                ))
    return errors[:20]


def _proposal_error_path(message: str) -> str:
    match = re.search(r"剧情\s*(\d+)", message)
    prefix = f"segments[{int(match.group(1)) - 1}]" if match else "segments"
    for kind in ASSET_TYPES:
        if kind in message:
            return f"{prefix}.{kind}"
    if "原文" in message or "text" in message:
        return f"{prefix}.text" if match else "segments"
    return prefix


def submit_plot_split_candidate(
    project_id: str,
    episode_id: str,
    segments: Any,
    *,
    session_id: str,
    user_instruction: str = "",
    previous_pending: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate source coverage and assets, then stage a session-owned candidate."""
    if not session_id:
        return _failure([_field_error("sessionId", "missing_session", "剧情拆分候选需要当前分集会话", repair_action="stop")])
    shape_errors = _segment_shape_errors(segments)
    if shape_errors:
        return _failure(shape_errors)
    try:
        canvas = get_canvas_context_v4(project_id, episode_id)
    except (ValueError, FileNotFoundError) as exc:
        return _failure([_field_error("episodeId", "canvas_unavailable", str(exc), repair_action="stop")])
    if canvas.get("canvasKind") == "custom" or canvas.get("autoWorkflowInitialized"):
        return _failure([_field_error(
            "episodeId", "canvas_already_initialized", "当前画布不支持再次自动创建工作链", repair_action="stop",
        )])
    try:
        context = _plot_split_inputs(project_id, episode_id)
    except (ValueError, FileNotFoundError) as exc:
        return _failure([_field_error("episodeId", "source_unavailable", str(exc), repair_action="stop")])
    try:
        proposal = proposal_from_one_request(
            {"segments": segments},
            episode_id=episode_id,
            episode_title=context["episodeTitle"],
            source_text=context["sourceText"],
            source_range_text=context["sourceText"],
            source_ref=context["sourceRef"],
            assets=context["assets"],
        )
        validation = validate_plot_splitting_worker_output(
            {"plotSplitProposal": proposal},
            episode_id=episode_id,
            source_ref=context["sourceRef"],
            episode_text=context["sourceText"],
            assets=context["assets"],
            allow_asset_hints=True,
        )
        if not validation.get("success"):
            issues = [str(issue) for issue in validation.get("blockingIssues") or []]
            return _failure([
                _field_error("plotSplitProposal.items", "contract_validation_failed", issue)
                for issue in issues[:12]
            ])
        proposal = validation["plotSplitProposal"]
    except (ValueError, FileNotFoundError) as exc:
        message = str(exc)
        return _failure([_field_error(_proposal_error_path(message), "invalid_candidate", message)])

    previous = previous_pending if isinstance(previous_pending, dict) else {}
    if previous.get("active") and str(previous.get("sessionId") or "") != session_id:
        return _failure([_field_error("sessionId", "candidate_owned_by_other_session", "待确认候选属于其他会话", repair_action="stop")])
    if previous.get("active") and str(previous.get("operationType") or "") != "commit_plot_split":
        return _failure([_field_error("pendingOperation", "pending_operation_exists", "当前会话已有其他待确认任务", repair_action="stop")])
    previous_payload = previous.get("commitPayload") if isinstance(previous.get("commitPayload"), dict) else {}
    if previous.get("active") and str(previous_payload.get("episodeId") or "") not in {"", episode_id}:
        return _failure([_field_error("episodeId", "pending_episode_mismatch", "待确认候选属于其他分集", repair_action="stop")])
    is_revision = bool(previous.get("active") and previous_payload)
    revision = _plot_split_next_revision_state(previous, previous_payload, user_instruction) if is_revision else {}
    pending = _plot_split_pending_operation(
        episode_id=episode_id,
        proposal=proposal,
        session_id=session_id,
        user_instruction=str(user_instruction or ""),
        source="submit_plot_split_candidate.result",
        message="剧情和资产关联候选已暂存，等待当前会话用户确认。",
        source_ref=context["sourceRef"],
        base_user_instruction=revision.get("baseUserInstruction") if is_revision else user_instruction,
        effective_revision_requirements=revision.get("effectiveRevisionRequirements") if is_revision else None,
        revision_count=revision.get("revisionCount") if is_revision else None,
    )
    candidate_id = f"plot-{uuid.uuid4().hex}"
    candidate_digest = plot_split_candidate_digest(pending["commitPayload"]["plotSplitProposal"])
    candidate_version = int(previous.get("candidateVersion") or 0) + 1 if is_revision else 1
    pending.update({
        "episodeId": episode_id,
        "candidateId": candidate_id,
        "runId": candidate_id,
        "candidateDigest": candidate_digest,
        "candidateVersion": candidate_version,
        "sourceDigest": context["sourceDigest"],
    })
    pending["sourceInputRef"]["sourceDigest"] = context["sourceDigest"]
    pending["commitPayload"]["sourceInputRef"]["sourceDigest"] = context["sourceDigest"]
    pending["commitPayload"]["candidateId"] = candidate_id
    pending["commitPayload"]["candidateDigest"] = candidate_digest
    preview = _plot_split_proposal_message(proposal, context["assets"])
    preview_block = _plot_split_proposal_block(
        proposal, context["assets"],
        candidate_id=candidate_id, candidate_version=candidate_version,
    )
    return {
        "success": True,
        "status": "pending_confirmation",
        "requiresUserConfirmation": True,
        "episodeId": episode_id,
        "itemCount": len(proposal.get("items") or []),
        "plotSplitProposal": proposal,
        "pendingOperation": pending,
        "previewText": preview,
        "previewBlock": preview_block,
        "candidateId": candidate_id,
        "candidateDigest": candidate_digest,
        "message": "剧情拆分候选已暂存，等待用户确认。",
        "projectChanged": False,
    }
