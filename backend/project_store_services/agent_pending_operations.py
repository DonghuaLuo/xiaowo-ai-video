# -*- coding: utf-8 -*-
"""待确认操作的状态、语义上下文、修订及剧情拆分提案。"""

from __future__ import annotations

from .agent_asset_range_state import (
    _agent_latest_asset_range_row,
    _agent_source_coverage_safe,
)
from .agent_context_runtime import (
    _agent_compact_commit_payload,
    _agent_compact_proposal,
    _agent_episode_number,
)
from .agent_contracts import (
    _agent_action_footer_instruction,
    _agent_compact_message_for_intent,
    _agent_steps_from_state,
    _agent_task_pending_action,
)
from .agent_operation_catalog import (
    agent_operation_action_footer,
    agent_operation_high_risk,
    agent_operation_interaction_policy,
    agent_operation_kind,
    agent_operation_label,
    agent_operation_reply,
    agent_operation_stale_reason,
    agent_operation_task_type,
)
from .agent_plot_contract import (
    _PLOT_SPLIT_REVISION_REQUIREMENT_LIMIT,
    _agent_compact_plot_split_commit_payload,
    _agent_compact_plot_split_proposal,
    _agent_plot_split_proposal_from_pending_operation,
    _agent_plot_split_revision_count,
    _agent_plot_split_revision_requirements,
    _compact_source_excerpt,
)
from .agent_sessions import (
    _load_agent_sessions,
    _normalize_agent_pending_operation,
    _project_meta_path,
    _save_agent_sessions,
)
from .runtime_state import (
    _LOCK,
)
from .project_resource_revisions import _json_hash, _resource_revision_value
from .source_coverage import _load_source_coverage
from .source_text_store import _compact_text
from .store_core import (
    _now,
    _read_json,
)

import copy
import json
import re
import traceback
from pathlib import Path
from typing import Any


def _combine_agent_user_instructions(*values: Any) -> str:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        rows.append(text)
        seen.add(text)
    return "\n".join(rows)


def _plot_split_pending_revision_requirements(
    pending_operation: dict[str, Any],
    commit_payload: dict[str, Any],
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for source in (pending_operation, commit_payload):
        if not isinstance(source, dict):
            continue
        for item in _agent_plot_split_revision_requirements(
            source.get("effectiveRevisionRequirements")
        ):
            key = re.sub(r"\s+", "", item)
            if not key or key in seen:
                continue
            merged.append(item)
            seen.add(key)
    return merged[-_PLOT_SPLIT_REVISION_REQUIREMENT_LIMIT:]


def _plot_split_next_revision_state(
    pending_operation: dict[str, Any],
    commit_payload: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    requirements = _plot_split_pending_revision_requirements(pending_operation, commit_payload)
    for item in _agent_plot_split_revision_requirements(message):
        key = re.sub(r"\s+", "", item)
        if key and key not in {re.sub(r"\s+", "", row) for row in requirements}:
            requirements.append(item)
    requirements = requirements[-_PLOT_SPLIT_REVISION_REQUIREMENT_LIMIT:]
    existing_count = max(
        _agent_plot_split_revision_count(pending_operation.get("revisionCount")),
        _agent_plot_split_revision_count(commit_payload.get("revisionCount")),
    )
    revision_count = max(existing_count + 1, len(requirements))
    base_user_instruction = _compact_text(
        commit_payload.get("baseUserInstruction")
        or pending_operation.get("baseUserInstruction")
        or "",
        500,
    )
    if not base_user_instruction and not _plot_split_pending_revision_requirements(pending_operation, commit_payload):
        base_user_instruction = _compact_text(commit_payload.get("userInstruction"), 500)
    return {
        "userInstruction": str(message or "").strip(),
        "effectiveRevisionRequirements": requirements,
        "revisionCount": revision_count,
        "baseUserInstruction": base_user_instruction,
    }


def _plot_split_fresh_rerun_state(
    pending_operation: dict[str, Any],
    commit_payload: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    existing_count = max(
        _agent_plot_split_revision_count(pending_operation.get("revisionCount")),
        _agent_plot_split_revision_count(commit_payload.get("revisionCount")),
    )
    base_user_instruction = _compact_text(
        commit_payload.get("baseUserInstruction")
        or pending_operation.get("baseUserInstruction")
        or commit_payload.get("userInstruction")
        or "",
        500,
    )
    current_requirement = str(message or "").strip()
    requirements = _agent_plot_split_revision_requirements([current_requirement] if current_requirement else [])
    return {
        "userInstruction": current_requirement,
        "effectiveRevisionRequirements": requirements,
        "revisionCount": existing_count + 1,
        "baseUserInstruction": base_user_instruction,
        "freshRerun": True,
    }


def _agent_message_cancels_plot_split_pending(message: str) -> bool:
    compact = re.sub(r"[\s，。！？、,.!?:：；;（）()\[\]【】\"'“”‘’]+", "", str(message or "")).casefold()
    if not compact:
        return False
    exact_terms = {
        "取消",
        "停止",
        "不确认",
        "不继续",
        "不提交",
        "不保存",
        "不要确认",
        "不要继续",
        "不要提交",
        "不要保存",
        "先不确认",
        "先不继续",
        "先不提交",
        "先不保存",
        "暂不确认",
        "暂不继续",
        "暂不提交",
        "暂不保存",
        "不用确认",
        "不用继续",
        "不用提交",
        "不用保存",
        "取消当前",
        "取消这次",
        "取消本次",
        "取消当前操作",
        "取消待确认",
        "放弃当前",
        "放弃这次",
        "放弃本次",
    }
    if compact in exact_terms:
        return True
    return False


def _agent_message_cancels_pending_operation(message: str) -> bool:
    compact = _agent_compact_message_for_intent(message)
    if not compact:
        return False
    exact_terms = {
        "取消",
        "停止",
        "不提交",
        "不确认",
        "不继续",
        "不保存",
        "不要确认",
        "不要提交",
        "不要继续",
        "不要保存",
        "取消当前",
        "取消这次",
        "取消本次",
        "取消当前操作",
        "取消待确认",
        "放弃当前",
        "放弃这次",
        "放弃本次",
        "不用确认",
        "不用提交",
        "不用继续",
        "不用保存",
        "先不提交",
        "先不继续",
        "先不保存",
        "暂不提交",
        "暂不继续",
        "暂不保存",
    }
    if compact in exact_terms:
        return True
    return False


def _plot_split_pending_explanation_message(proposal: dict[str, Any]) -> str:
    items = proposal.get("items") if isinstance(proposal.get("items"), list) else []
    lines = ["当前拆分结果还在等待确认，我先说明这版拆分的依据，不会提交也不会重新请求模型："]
    if not items:
        lines.append("")
        lines.append("当前没有可解释的拆分条目。")
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        title = _compact_text(item.get("title") or item.get("name") or f"剧情段 {index}", 80)
        reason = _compact_text(item.get("splitReason") or item.get("reason") or "", 160)
        preview = _compact_source_excerpt(item.get("sourcePreview") or item.get("sourceFactText") or "", 120)
        detail = reason or preview
        lines.append(f"{index}. {title}" + (f"：{detail}" if detail else ""))
    lines.extend(
        [
            "",
            "当前拆分结果仍未提交。",
        ]
    )
    return "\n".join(lines)


def _agent_pending_operation_label(operation_kind: str) -> str:
    return agent_operation_label(operation_kind)


def _agent_pending_operation_generic_explanation_message(pending_operation: dict[str, Any]) -> str:
    kind = str(pending_operation.get("kind") or "").strip()
    label = _agent_pending_operation_label(kind)
    lines = [f"当前有一个待确认操作：{label}。"]
    message = _compact_text(pending_operation.get("message"), 240)
    if message:
        lines.extend(["", message])
    lines.extend(["", "当前待确认状态仍保留，尚未提交。"])
    return "\n".join(lines)


def _agent_pending_operation_can_resolve_locally(
    message: str,
    pending_operation_context: dict[str, Any] | None,
) -> bool:
    pending = pending_operation_context if isinstance(pending_operation_context, dict) else {}
    if not pending.get("active"):
        return False
    kind = str(pending.get("kind") or "").strip()
    if agent_operation_high_risk(kind):
        return False
    policy = (
        pending.get("interactionPolicy")
        if isinstance(pending.get("interactionPolicy"), dict)
        else _agent_pending_operation_interaction_policy_for_kind(kind)
    )
    if policy.get("canCancel") and _agent_message_cancels_pending_operation(message):
        return True
    return False


def _agent_pending_operation_local_result(
    project_id: str,
    state: dict[str, Any],
    message: str,
    pending_operation_context: dict[str, Any],
    *,
    session_id: str | None = None,
    task_hypothesis: dict[str, Any] | None = None,
    model_meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    pending_action = _agent_task_pending_action(task_hypothesis)
    if pending_action == "chat":
        return None
    pending = pending_operation_context if isinstance(pending_operation_context, dict) else {}
    kind = str(pending.get("kind") or "").strip()
    policy = (
        pending.get("interactionPolicy")
        if isinstance(pending.get("interactionPolicy"), dict)
        else _agent_pending_operation_interaction_policy_for_kind(kind)
    )
    semantic_local_action = bool(
        pending.get("active")
        and (
            pending_action in {"cancel", "explain"}
            or (pending_action in {"revise", "fresh_rerun"} and not policy.get("canRevise"))
        )
    )
    if not (
        _agent_pending_operation_can_resolve_locally(message, pending_operation_context)
        or semantic_local_action
    ):
        return None
    label = _agent_pending_operation_label(kind)
    route_source = "pending_operation_local_interaction"
    pending_update: Any = pending_operation_context
    if policy.get("canCancel") and (
        _agent_message_cancels_pending_operation(message) or pending_action == "cancel"
    ):
        route_source = "pending_operation_cancelled"
        _agent_clear_pending_operation_state(
            project_id,
            session_id,
            pending_operation_context,
            reason="agent_pending_operation_cancelled",
            user_instruction=message,
        )
        pending_update = None
        reply = f"已取消当前{label}。本轮不会提交，也不会重新执行。"
    elif policy.get("canExplain") and pending_action == "explain":
        route_source = "pending_operation_explained"
        if kind == "plot_split":
            proposal = (
                pending_operation_context.get("proposal")
                if isinstance(pending_operation_context.get("proposal"), dict)
                else {}
            )
            reply = _plot_split_pending_explanation_message(proposal)
        else:
            reply = _agent_pending_operation_generic_explanation_message(pending_operation_context)
    elif not policy.get("canRevise") and pending_action in {"revise", "fresh_rerun"}:
        route_source = "pending_operation_revision_not_supported"
        reply = (
            f"当前{label}只支持确认、取消或查看说明，不能直接把这轮修改意见和上一轮结果一起发给模型重跑。\n\n"
            "如果要调整，请先取消当前待确认结果，再重新发起对应规划。"
        )
    else:
        return None
    merged_meta = copy.deepcopy(model_meta) if isinstance(model_meta, dict) else {}
    task_meta = copy.deepcopy(task_hypothesis) if isinstance(task_hypothesis, dict) else {}
    if not task_meta:
        task_meta = {
            "taskType": _agent_task_type_for_pending_operation(
                str(pending_operation_context.get("operationType") or "")
            ),
        }
    task_meta["routeSource"] = route_source
    merged_meta.update(
        {
            "source": "local-controller",
            "taskHypothesis": task_meta,
            "pendingInteractionPolicy": policy,
        }
    )
    return {
        "success": True,
        "message": reply,
        "contentBlocks": [{"type": "text", "text": reply}],
        "steps": _agent_steps_from_state(state),
        "pendingQuestion": None,
        "project": state["project"],
        "agentModelMeta": merged_meta,
        "sessionStatus": "idle",
        "pendingOperation": pending_update,
        **({"cancelledCandidateId": str(pending.get("candidateId") or pending.get("runId") or "")}
           if route_source == "pending_operation_cancelled" and kind == "plot_split" else {}),
    }


def _agent_chinese_episode_number(value: str) -> int:
    text = re.sub(r"\s+", "", str(value or "")).strip()
    if not text:
        return 0
    if text.isdigit():
        try:
            return int(text)
        except ValueError:
            return 0
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    units = {"十": 10, "百": 100, "千": 1000}
    total = 0
    section = 0
    number = 0
    saw_unit = False
    for char in text:
        if char in digits:
            number = digits[char]
            continue
        unit = units.get(char)
        if unit:
            saw_unit = True
            section += (number or 1) * unit
            number = 0
            continue
        return 0
    total = section + number
    if not saw_unit and len(text) > 1:
        total = 0
        for char in text:
            if char not in digits:
                return 0
            total = total * 10 + digits[char]
    return total


def _episode_id_from_user_message(
    project_id: str,
    state: dict[str, Any],
    message: str,
    fallback_episode_id: str,
) -> str:
    fallback = str(fallback_episode_id or "E01").strip() or "E01"
    text = re.sub(r"\s+", "", str(message or "")).casefold()
    if not text:
        return fallback
    if any(term in text for term in ("当前集", "本集", "这一集", "这集")):
        return fallback
    meta = state.get("meta") if isinstance(state.get("meta"), dict) else {}
    episodes = [item for item in meta.get("episodes", []) if isinstance(item, dict)]
    if not episodes:
        project_meta = _read_json(_project_meta_path(project_id), {})
        episodes = [item for item in project_meta.get("episodes", []) if isinstance(item, dict)]

    def _episode_id_for_number(number: int) -> str:
        if number <= 0:
            return ""
        for item in episodes:
            episode_id = str(item.get("id") or item.get("episodeId") or "").strip()
            if episode_id and _agent_episode_number(episode_id) == number:
                return episode_id
        return f"E{number:02d}"

    for item in episodes:
        episode_id = str(item.get("id") or item.get("episodeId") or "").strip()
        if not episode_id:
            continue
        episode_number = _agent_episode_number(episode_id)
        variants = {
            re.sub(r"\s+", "", episode_id).casefold(),
            f"e{episode_number}" if episode_number else "",
            f"e{episode_number:02d}" if episode_number else "",
            f"ep{episode_number}" if episode_number else "",
            f"episode{episode_number}" if episode_number else "",
            f"第{episode_number}集" if episode_number else "",
            f"第{episode_number:02d}集" if episode_number else "",
        }
        title = re.sub(r"\s+", "", str(item.get("title") or "")).casefold()
        if title:
            variants.add(title)
        if any(variant and variant in text for variant in variants):
            return episode_id

    for pattern in (
        r"(?:^|[^a-z0-9])e0*(\d+)(?:集|$|[^0-9])",
        r"(?:episode|ep)0*(\d+)",
        r"第([一二两三四五六七八九十百千零〇\d]+)[集话回]",
        r"(\d+)[集话回]",
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        episode_number = _agent_chinese_episode_number(match.group(1))
        episode_id = _episode_id_for_number(episode_number)
        if episode_id:
            return episode_id
    return fallback


def _agent_pending_operation_action_footer(operation: dict[str, Any]) -> dict[str, str]:
    operation_kind = _agent_pending_operation_kind(operation)
    footer = agent_operation_action_footer(operation_kind)
    if footer:
        return footer
    if bool((operation or {}).get("requiresUserConfirmation")):
        return _agent_action_footer_instruction(
            "需要确认",
            "确认后继续",
            description="回复“确认”后，我会提交当前待确认结果。",
            reply="确认",
        )
    return {}


def _agent_pending_operation_interaction_policy_for_kind(operation_kind: str) -> dict[str, Any]:
    return agent_operation_interaction_policy(operation_kind)


def _agent_pending_operation_kind(operation: dict[str, Any] | None) -> str:
    operation_type = str((operation or {}).get("type") or (operation or {}).get("operationType") or "").strip()
    return agent_operation_kind(operation_type)




def _agent_message_is_pending_operation_protocol_reply(
    message: str,
    pending_operation_context: dict[str, Any] | None,
) -> bool:
    pending = pending_operation_context if isinstance(pending_operation_context, dict) else {}
    if not pending.get("active"):
        return False
    compact = _agent_compact_message_for_intent(message)
    if not compact:
        return False
    if _agent_message_is_pending_operation_confirmation_reply(message, pending):
        return True
    operation_type = str(pending.get("operationType") or "").strip()
    kind = str(pending.get("kind") or "").strip()
    if agent_operation_high_risk(kind):
        return (
            _agent_message_cancels_destructive_operation(message)
            or _agent_message_confirms_destructive_operation(message, operation_type)
            or _agent_message_cancels_pending_operation(message)
            or _agent_message_confirms(message)
        )
    policy = (
        pending.get("interactionPolicy")
        if isinstance(pending.get("interactionPolicy"), dict)
        else _agent_pending_operation_interaction_policy_for_kind(kind)
    )
    # 这里只识别明确的界面协议回复；自然语言由意图分析判断。
    if policy.get("canCancel") and _agent_message_cancels_pending_operation(message):
        return True
    return False


def _agent_message_is_pending_operation_confirmation_reply(
    message: str,
    pending_operation_context: dict[str, Any] | None,
) -> bool:
    pending = pending_operation_context if isinstance(pending_operation_context, dict) else {}
    reconciling_episode_commit = (
        pending.get("operationType") == "commit_episode_boundary"
        and pending.get("operationStatus") in {"committing", "commit_unknown"}
        and isinstance(pending.get("proposal"), dict)
        and pending["proposal"].get("planningMethod") == "agent_episode_boundary"
    )
    if not pending.get("active") and not reconciling_episode_commit:
        return False
    compact = _agent_compact_message_for_intent(message)
    if not compact:
        return False
    footer = _agent_pending_operation_action_footer(pending)
    expected_reply = _agent_compact_message_for_intent(footer.get("reply") or "")
    if expected_reply and compact == expected_reply:
        return True
    return compact in {"确认", "确定", "继续"}


def _agent_pending_operation_requires_semantic_probe(
    message: str,
    pending_operation_context: dict[str, Any] | None,
) -> bool:
    pending = pending_operation_context if isinstance(pending_operation_context, dict) else {}
    return bool(
        pending.get("active")
        and str(message or "").strip()
        and not _agent_message_is_pending_operation_protocol_reply(message, pending)
    )


def _agent_current_message_allows_model_user_instruction(
    task_hypothesis: dict[str, Any] | None,
    pending_operation_context: dict[str, Any] | None = None,
) -> bool:
    task = task_hypothesis if isinstance(task_hypothesis, dict) else {}
    pending_action = _agent_task_pending_action(task)
    if pending_action in {"revise", "fresh_rerun"}:
        return True
    if bool(task.get("pendingOperationActive")):
        return False
    pending = pending_operation_context if isinstance(pending_operation_context, dict) else {}
    if pending.get("active"):
        return False
    if pending_action:
        if pending_action == "new_task":
            return True
        return False
    return True


def _agent_pending_operation_reproposal_task_type(operation_type_or_kind: str | None) -> str:
    kind = agent_operation_kind(operation_type_or_kind)
    return {
        "asset_range": "asset_range_propose",
        "episode_boundary": "episode_boundary_propose",
    }.get(kind, "")


def _agent_message_is_direct_control_instruction(message: str) -> bool:
    compact = _agent_compact_message_for_intent(message)
    return compact in {
        "继续",
        "继续执行",
        "继续下一步",
        "下一步继续",
        "接着做",
        "接着来",
        "确认",
        "确认提交",
        "提交",
        "保存",
        "可以",
        "好的",
        "好",
        "ok",
        "yes",
        "同意",
        "就这样",
        "按这个",
    }


def _agent_pending_operation_revision_instruction(
    message: str,
    task_hypothesis: dict[str, Any] | None = None,
    pending_operation_context: dict[str, Any] | None = None,
) -> str:
    text = str(message or "").strip()
    if not text:
        return ""
    if _agent_message_is_direct_control_instruction(text):
        return ""
    if not _agent_current_message_allows_model_user_instruction(
        task_hypothesis,
        pending_operation_context,
    ):
        return ""
    return text


def _agent_without_user_instruction_fields(payload: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(payload) if isinstance(payload, dict) else {}
    for key in (
        "rawUserInstruction",
        "raw_user_instruction",
        "userMessage",
        "user_message",
        "userInstruction",
        "user_instruction",
    ):
        result.pop(key, None)
    return result


def _agent_clear_pending_operation_state(
    project_id: str,
    session_id: str | None,
    pending_operation_context: dict[str, Any] | None,
    *,
    reason: str,
    user_instruction: str = "",
) -> dict[str, bool]:
    from .agent_run_store import change_episode_candidate_status

    pending = pending_operation_context if isinstance(pending_operation_context, dict) else {}
    pending_kind = str(pending.get("kind") or _agent_pending_operation_kind(pending)).strip()
    changed = {"session": False, "coverage": False}
    if pending_kind == "episode_boundary" and session_id:
        proposal = pending.get("proposal") if isinstance(pending.get("proposal"), dict) else {}
        candidate_id = str(proposal.get("proposalId") or "").strip()
        if candidate_id and pending.get("active"):
            change_episode_candidate_status(
                project_id, session_id, candidate_id, "cancelled",
                expected_digest=str(pending.get("candidateDigest") or "") or None,
            )
    with _LOCK:
        if session_id:
            sessions = _load_agent_sessions(project_id)
            for index, session in enumerate(sessions):
                if str(session.get("id") or "") != str(session_id):
                    continue
                if _normalize_agent_pending_operation(session.get("pendingOperation")):
                    session.pop("pendingOperation", None)
                    session["updatedAt"] = _now()
                    sessions[index] = session
                    _save_agent_sessions(project_id, sessions)
                    changed["session"] = True
                break
    return changed




def _plot_split_source_ref_from_input_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    source_ref = value.get("sourceRef")
    if isinstance(source_ref, dict) and source_ref:
        return copy.deepcopy(source_ref)
    if str(value.get("type") or "") != "episode_source_text" and value:
        return copy.deepcopy(value)
    return {}


def _plot_split_pending_retry_fields(
    pending_operation: dict[str, Any] | None,
    commit_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    operation = pending_operation if isinstance(pending_operation, dict) else {}
    payload = commit_payload if isinstance(commit_payload, dict) else {}
    source_ref: dict[str, Any] = {}
    for source_input_ref in (payload.get("sourceInputRef"), operation.get("sourceInputRef")):
        source_ref = _plot_split_source_ref_from_input_ref(source_input_ref)
        if source_ref:
            break
    revision_requirements = _plot_split_pending_revision_requirements(operation, payload)
    revision_count = max(
        _agent_plot_split_revision_count(operation.get("revisionCount")),
        _agent_plot_split_revision_count(payload.get("revisionCount")),
        len(revision_requirements),
    )
    return {
        "source_ref": source_ref,
        "base_user_instruction": _compact_text(
            payload.get("baseUserInstruction")
            or operation.get("baseUserInstruction")
            or payload.get("userInstruction")
            or "",
            500,
        ),
        "effective_revision_requirements": revision_requirements,
        "revision_count": revision_count,
    }


def _agent_pending_operation_matches_coverage(operation: dict[str, Any] | None, coverage: dict[str, Any]) -> bool:
    operation_kind = _agent_pending_operation_kind(operation)
    if not operation_kind:
        return False
    operation = operation or {}
    proposal = operation.get("proposal") if isinstance(operation.get("proposal"), dict) else {}
    commit_payload = operation.get("commitPayload") if isinstance(operation.get("commitPayload"), dict) else {}
    if operation_kind == "episode_boundary" and proposal.get("planningMethod") != "agent_episode_boundary":
        return False
    if operation_kind == "project_asset_cleanup":
        expected_revision = commit_payload.get("coverageRevision", commit_payload.get("expectedCoverageRevision"))
        base_hash = commit_payload.get("coverageBaseHash", commit_payload.get("expectedCoverageBaseHash"))
        try:
            if expected_revision is not None and str(expected_revision).strip():
                if _resource_revision_value(coverage) != int(expected_revision):
                    return False
            if base_hash is not None and str(base_hash).strip() and _json_hash(coverage) != str(base_hash).strip():
                return False
        except (TypeError, ValueError):
            return False
        return True
    if operation_kind == "latest_asset_range_delete":
        asset_range_id = str(commit_payload.get("assetRangeId") or commit_payload.get("rangeId") or "").strip()
        if not asset_range_id:
            return False
        latest = _agent_latest_asset_range_row(coverage)
        if not isinstance(latest, dict):
            return False
        latest_id = str(latest.get("rangeId") or "").strip()
        if latest_id != asset_range_id:
            return False
        expected_revision = commit_payload.get("coverageRevision", commit_payload.get("expectedCoverageRevision"))
        base_hash = commit_payload.get("coverageBaseHash", commit_payload.get("expectedCoverageBaseHash"))
        try:
            if expected_revision is not None and str(expected_revision).strip():
                if _resource_revision_value(coverage) != int(expected_revision):
                    return False
            if base_hash is not None and str(base_hash).strip() and _json_hash(coverage) != str(base_hash).strip():
                return False
        except (TypeError, ValueError):
            return False
        return True
    if operation_kind == "current_canvas_clear":
        episode_ids = commit_payload.get("episodeIds")
        if not isinstance(episode_ids, list):
            raw_episode_id = commit_payload.get("episodeId") or proposal.get("episodeId")
            episode_ids = [raw_episode_id] if raw_episode_id else []
        normalized_episode_ids = [
            str(item or "").strip()
            for item in episode_ids
            if str(item or "").strip()
        ]
        targets = commit_payload.get("targets")
        if targets is None:
            targets = proposal.get("targets")
        normalized_targets = {
            str(item or "").strip()
            for item in (targets if isinstance(targets, list) else [targets])
            if str(item or "").strip()
        }
        return len(normalized_episode_ids) == 1 and normalized_targets == {"storyboards"}
    if operation_kind == "episode_source_delete":
        episode_ids = commit_payload.get("episodeIds")
        if not isinstance(episode_ids, list):
            raw_episode_id = commit_payload.get("episodeId") or proposal.get("episodeId")
            episode_ids = [raw_episode_id] if raw_episode_id else []
        normalized_episode_ids = [
            str(item or "").strip()
            for item in episode_ids
            if str(item or "").strip()
        ]
        targets = commit_payload.get("targets")
        if targets is None:
            targets = proposal.get("targets")
        normalized_targets = {
            str(item or "").strip()
            for item in (targets if isinstance(targets, list) else [targets])
            if str(item or "").strip()
        }
        if len(normalized_episode_ids) != 1 or normalized_targets != {"source_splits", "storyboards"}:
            return False
        target_episode_id = normalized_episode_ids[0]
        episode_ranges = [
            item
            for item in coverage.get("episodeRanges") or []
            if isinstance(item, dict)
        ]
        latest_episode_range = episode_ranges[-1] if episode_ranges else {}
        latest_episode_id = str(latest_episode_range.get("episodeId") or latest_episode_range.get("episode_id") or "").strip()
        return bool(latest_episode_id and latest_episode_id == target_episode_id)
    if operation_kind == "plot_split":
        plot_proposal = (
            commit_payload.get("plotSplitProposal")
            if isinstance(commit_payload.get("plotSplitProposal"), dict)
            else proposal
        )
        items = plot_proposal.get("items") if isinstance(plot_proposal, dict) else []
        episode_id = str(commit_payload.get("episodeId") or plot_proposal.get("episodeId") or "").strip()
        return bool(episode_id and isinstance(items, list) and items)
    expected_revision = commit_payload.get("expectedRevision", commit_payload.get("expected_revision"))
    base_hash = commit_payload.get("baseHash", commit_payload.get("base_hash"))
    try:
        if expected_revision is not None and str(expected_revision).strip():
            if _resource_revision_value(coverage) != int(expected_revision):
                return False
        if base_hash is not None and str(base_hash).strip() and _json_hash(coverage) != str(base_hash).strip():
            return False
    except (TypeError, ValueError):
        return False
    cursor_key = "assetCursor" if operation_kind == "asset_range" else "episodeCursor"
    cursor = coverage.get(cursor_key) if isinstance(coverage.get(cursor_key), dict) else {}
    start_value = (
        commit_payload.get("absoluteStart")
        if operation_kind == "asset_range"
        else commit_payload.get("startOffset")
    )
    if start_value is None:
        start_value = commit_payload.get("startOffset")
    end_value = (
        commit_payload.get("absoluteEnd")
        if operation_kind == "asset_range"
        else commit_payload.get("endOffset")
    )
    if end_value is None:
        end_value = commit_payload.get("endOffset")
    try:
        start = int(start_value)
        end = int(end_value)
        cursor_start = int(cursor.get("nextOffset") or 0)
    except (TypeError, ValueError):
        return False
    if start != cursor_start or end <= start:
        return False
    if operation_kind == "asset_range":
        range_id = str(commit_payload.get("rangeId") or proposal.get("rangeId") or "").strip()
        for item in coverage.get("assetRanges") or []:
            if isinstance(item, dict) and range_id and str(item.get("rangeId") or "") == range_id:
                return False
    if operation_kind == "episode_boundary":
        episode_id = str(commit_payload.get("episodeId") or proposal.get("episodeId") or "").strip()
        for item in coverage.get("episodeRanges") or []:
            if isinstance(item, dict) and episode_id and str(item.get("episodeId") or "") == episode_id:
                return False
    return True


def _agent_session_pending_operation_for_prompt(project_id: str, session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    session = next(
        (
            row
            for row in _load_agent_sessions(project_id)
            if str(row.get("id") or "") == str(session_id)
        ),
        None,
    )
    if not isinstance(session, dict):
        return None
    return _normalize_agent_pending_operation(session.get("pendingOperation"))


def _agent_pending_operation_context(
    project_id: str, session_id: str | None, *,
    candidate_id: str | None = None, source_filter: str | None = None,
) -> dict[str, Any]:
    from .agent_run_store import (
        get_asset_range_candidate,
        get_episode_candidate,
        refresh_asset_range_candidate_freshness,
        refresh_episode_candidate_freshness,
    )

    coverage = _agent_source_coverage_safe(project_id)
    saved_episode = (
        refresh_episode_candidate_freshness(project_id, session_id, candidate_id)
        if source_filter != "session" else None
    )
    saved_asset_range = (
        refresh_asset_range_candidate_freshness(project_id, session_id, candidate_id)
        if source_filter != "session" else None
    )
    # 刷新可能刚把候选标成 stale；保留该候选供界面解释失效原因。
    if candidate_id and source_filter != "session":
        saved_episode = saved_episode or get_episode_candidate(project_id, session_id, candidate_id)
        saved_asset_range = saved_asset_range or get_asset_range_candidate(project_id, session_id, candidate_id)
    if saved_asset_range and isinstance(saved_asset_range.get("proposal"), dict):
        coverage = _load_source_coverage(
            project_id, str(saved_asset_range["proposal"].get("sourceId") or "") or None,
        )
    session_operation = _agent_session_pending_operation_for_prompt(project_id, session_id)
    if candidate_id and str((session_operation or {}).get("candidateId") or "") != candidate_id:
        session_operation = None
    operation = None
    source = ""
    if saved_episode:
        proposal = saved_episode["proposal"]
        operation = {
            "type": "commit_episode_boundary", "operationType": "commit_episode_boundary",
            "source": "agent_run.candidate", "sessionId": session_id,
            "runId": saved_episode["runId"], "candidateId": saved_episode["candidateId"],
            "candidateDigest": saved_episode["digest"],
            "candidateVersion": saved_episode["version"],
            "status": saved_episode["status"], "createdAt": saved_episode["createdAt"],
            "proposal": proposal, "commitPayload": saved_episode["commitPayload"],
            "requiresUserConfirmation": True,
            "nextAllowedTools": ["commit_episode_boundary"],
            "originalUserMessage": str(saved_episode.get("requirementText") or ""),
            "revisionFeedback": saved_episode.get("revisionFeedback") or [],
        }
        if isinstance(session_operation, dict) and str((session_operation.get("proposal") or {}).get("proposalId") or "") == saved_episode["candidateId"]:
            operation["originalUserMessage"] = str(session_operation.get("originalUserMessage") or operation["originalUserMessage"])
            operation["revisionFeedback"] = session_operation.get("revisionFeedback") or []
        source = "agent_run.candidate"
    elif saved_asset_range:
        operation = {
            "type": "commit_asset_range", "operationType": "commit_asset_range",
            "source": "agent_run.asset_range_candidate", "sessionId": session_id,
            "runId": saved_asset_range["runId"],
            "candidateId": saved_asset_range["candidateId"],
            "candidateDigest": saved_asset_range["digest"],
            "candidateVersion": saved_asset_range["version"],
            "status": saved_asset_range["status"], "createdAt": saved_asset_range["createdAt"],
            "proposal": saved_asset_range["proposal"],
            "commitPayload": saved_asset_range["commitPayload"],
            "requiresUserConfirmation": True,
            "expectedNextTool": "commit_asset_range", "nextAllowedTools": ["commit_asset_range"],
            "originalUserMessage": str(saved_asset_range.get("requirementText") or ""),
            "revisionFeedback": saved_asset_range.get("revisionFeedback") or [],
        }
        source = "agent_run.asset_range_candidate"
    elif session_operation and _agent_pending_operation_kind(session_operation) not in {"episode_boundary", "asset_range"}:
        operation = session_operation
        source = "session.pendingOperation"
    if not operation:
        return {"active": False, "status": "none"}
    normalized = _normalize_agent_pending_operation(operation)
    if not normalized:
        return {"active": False, "status": "none"}
    operation_type = str(normalized.get("type") or "").strip()
    operation_kind = _agent_pending_operation_kind(normalized)
    if operation_kind in {"direct_asset_delete", "direct_workflow_delete", "direct_workflow_unlink"}:
        from .agent_direct_deletion import agent_direct_delete_is_current
        active = agent_direct_delete_is_current(project_id, normalized)
    elif source in {"agent_run.candidate", "agent_run.asset_range_candidate"}:
        saved_candidate = saved_episode if source == "agent_run.candidate" else saved_asset_range
        commit_guard = saved_candidate["commitPayload"]
        try:
            active = (
                saved_candidate["status"] in {"committing", "commit_unknown"}
                or (
                    saved_candidate["status"] == "awaiting_confirmation"
                    and _resource_revision_value(coverage) == int(commit_guard.get("expectedRevision"))
                    and _json_hash(coverage) == str(commit_guard.get("baseHash") or "")
                )
            )
        except (TypeError, ValueError):
            active = False
    else:
        active = _agent_pending_operation_matches_coverage(normalized, coverage)
    if operation_kind in {"project_asset_cleanup", "latest_asset_range_delete", "current_canvas_clear", "episode_source_delete",
                          "direct_asset_delete", "direct_workflow_delete", "direct_workflow_unlink"}:
        proposal = (
            copy.deepcopy(normalized.get("proposal"))
            if isinstance(normalized.get("proposal"), dict)
            else {}
        )
        commit_payload = (
            copy.deepcopy(normalized.get("commitPayload"))
            if isinstance(normalized.get("commitPayload"), dict)
            else {}
        )
    elif operation_kind == "plot_split":
        proposal = _agent_compact_plot_split_proposal(normalized.get("proposal"))
        commit_payload = _agent_compact_plot_split_commit_payload(normalized.get("commitPayload"))
    else:
        proposal = _agent_compact_proposal(normalized.get("proposal"))
        commit_payload = _agent_compact_commit_payload(normalized.get("commitPayload"))
    stale_reason = (
        agent_operation_stale_reason(operation_kind)
        or "当前待确认操作已变化或已提交，请读取最新会话状态。"
    )
    interaction_policy = _agent_pending_operation_interaction_policy_for_kind(operation_kind)
    if not active:
        interaction_policy = {
            **interaction_policy,
            "canConfirm": False,
            "canRevise": False,
            "staleReason": stale_reason,
        }
    context = {
        "active": active,
        "status": "active" if active else "stale",
        "operationStatus": str(normalized.get("status") or "").strip(),
        "type": operation_type,
        "source": source,
        "operationType": operation_type,
        "kind": operation_kind,
        "operationLabel": _agent_pending_operation_label(operation_kind),
        "expectedNextTool": str(normalized.get("expectedNextTool") or operation_type),
        "requiresUserConfirmation": bool(normalized.get("requiresUserConfirmation", True)),
        "proposal": proposal,
        "commitPayload": commit_payload,
        "nextAllowedTools": normalized.get("nextAllowedTools") if isinstance(normalized.get("nextAllowedTools"), list) else [operation_type],
        "staleReason": "" if active else stale_reason,
        "interactionPolicy": interaction_policy,
        "createdAt": str(normalized.get("createdAt") or "").strip(),
        "sessionId": str(normalized.get("sessionId") or "").strip(),
        "runId": str(normalized.get("runId") or "").strip(),
        "candidateId": str(normalized.get("candidateId") or "").strip(),
        "candidateDigest": str(normalized.get("candidateDigest") or "").strip(),
        "candidateVersion": normalized.get("candidateVersion"),
        "message": str(normalized.get("message") or "").strip(),
    }
    context["pendingOperationId"] = _json_hash({
        "sessionId": str(session_id or ""),
        "operationType": operation_type,
        "createdAt": context["createdAt"],
        "candidateId": context["candidateId"],
    })
    if operation_kind in {"episode_boundary", "asset_range"}:
        context["originalUserMessage"] = str(normalized.get("originalUserMessage") or "").strip()
        context["revisionFeedback"] = [
            str(item).strip() for item in (normalized.get("revisionFeedback") or [])
            if isinstance(item, str) and str(item).strip()
        ][-12:]
    if operation_kind == "plot_split":
        revision_requirements = _agent_plot_split_revision_requirements(
            normalized.get("effectiveRevisionRequirements")
        )
        revision_count = _agent_plot_split_revision_count(
            normalized.get("revisionCount"),
            fallback=len(revision_requirements),
        )
        latest_result = (
            copy.deepcopy(normalized.get("latestResult"))
            if isinstance(normalized.get("latestResult"), dict)
            else {"plotSplitProposal": copy.deepcopy(proposal)}
            if proposal
            else {}
        )
        source_input_ref = (
            copy.deepcopy(normalized.get("sourceInputRef"))
            if isinstance(normalized.get("sourceInputRef"), dict)
            else {}
        )
        if latest_result:
            context["latestResult"] = latest_result
        if source_input_ref:
            context["sourceInputRef"] = source_input_ref
        if revision_requirements:
            context["effectiveRevisionRequirements"] = revision_requirements
        context["revisionCount"] = revision_count
    return context


def _agent_pending_operation_contexts(project_id: str, session_id: str | None) -> list[dict[str, Any]]:
    """返回本会话可见的待办；候选卡的归属不依赖聊天文本顺序。"""
    from .agent_run_store import (
        list_open_asset_range_candidates,
        list_open_episode_candidates,
        session_latest_stale_candidate_ids,
    )

    if not session_id:
        return []
    contexts: list[dict[str, Any]] = []
    for candidate in (
        list_open_episode_candidates(project_id, session_id)
        + list_open_asset_range_candidates(project_id, session_id)
    ):
        context = _agent_pending_operation_context(
            project_id, session_id, candidate_id=str(candidate["candidateId"]),
        )
        if context.get("status") != "none":
            contexts.append(context)
    active_kinds = {str(item.get("kind") or "") for item in contexts if item.get("active")}
    for task_type, candidate_id in session_latest_stale_candidate_ids(project_id, session_id).items():
        kind = "episode_boundary" if task_type == "episode_boundary_propose" else "asset_range"
        if kind in active_kinds or any(item.get("candidateId") == candidate_id for item in contexts):
            continue
        context = _agent_pending_operation_context(project_id, session_id, candidate_id=candidate_id)
        if context.get("status") == "stale":
            contexts.append(context)
    session_context = _agent_pending_operation_context(
        project_id, session_id, source_filter="session",
    )
    if session_context.get("status") != "none" and not any(
        item.get("operationType") == session_context.get("operationType")
        and item.get("candidateId") == session_context.get("candidateId")
        and item.get("createdAt") == session_context.get("createdAt")
        for item in contexts
    ):
        contexts.append(session_context)
    return sorted(contexts, key=lambda item: str(item.get("createdAt") or ""), reverse=True)


def _agent_pending_operation_from_tool_result(
    tool_name: str,
    result: dict[str, Any],
    *,
    session_id: str | None = None,
    user_message: str = "",
    previous_pending: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if tool_name != "submit_episode_boundary_candidate":
        return None
    next_step = result.get("nextStep") if isinstance(result.get("nextStep"), dict) else {}
    if not bool(result.get("success", True)) or not result.get("requiresUserConfirmation"):
        return None
    operation_type = str(next_step.get("commitTool") or "").strip()
    if not operation_type:
        operation_type = "commit_episode_boundary"
    proposal = _agent_compact_proposal(result.get("proposal"))
    commit_payload = _agent_compact_commit_payload(result.get("commitPayload"))
    if not proposal or not commit_payload:
        return None
    operation = {
        "type": operation_type,
        "operationType": operation_type,
        "source": f"{tool_name}.result",
        "sessionId": str(session_id or ""),
        "createdAt": _now(),
        "requiresUserConfirmation": True,
        "expectedNextTool": operation_type,
        "proposal": proposal,
        "commitPayload": commit_payload,
        "nextAllowedTools": [operation_type],
        "message": _compact_text(str((result.get("nextStep") or {}).get("message") or result.get("message") or ""), 240),
    }
    if tool_name == "submit_episode_boundary_candidate":
        operation["runId"] = str(result.get("runId") or "")
        operation["candidateDigest"] = str(result.get("candidateDigest") or "")
        operation["candidateVersion"] = result.get("candidateVersion")
        previous = previous_pending if isinstance(previous_pending, dict) else {}
        current = str(user_message or "").strip()
        original = str(previous.get("originalUserMessage") or "").strip() if previous.get("active") else ""
        feedback = [
            str(item).strip() for item in (previous.get("revisionFeedback") or [])
            if isinstance(item, str) and str(item).strip()
        ] if original else []
        if original and current and current != original:
            feedback.append(current)
        operation["originalUserMessage"] = original or current
        operation["revisionFeedback"] = feedback[-12:]
    return operation


def _agent_message_confirms(message: str) -> bool:
    raw = str(message or "").strip()
    if not raw:
        return False
    text = _agent_compact_message_for_intent(raw)
    if not text:
        return False
    hard_cancel_terms = (
        "不确认",
        "不继续",
        "不提交",
        "不保存",
        "不执行",
        "不是",
        "而是",
        "说错",
        "错了",
        "纠正",
        "更正",
        "撤回",
        "别按",
        "不要按",
        "不要继续",
        "不要提交",
        "不要保存",
        "不要执行",
        "先不继续",
        "先不提交",
        "先不保存",
        "先不执行",
        "暂不继续",
        "暂不提交",
        "暂不保存",
        "暂不执行",
        "不用继续",
        "不用提交",
        "不用保存",
        "不用执行",
        "别继续",
        "别提交",
        "别保存",
        "别执行",
        "不可以",
        "取消",
        "停止",
    )
    if any(term in text for term in hard_cancel_terms):
        return False
    exact_confirm_terms = {
        "继续",
        "确认",
        "可以",
        "提交",
        "保存",
        "好的",
        "好",
        "ok",
        "yes",
        "同意",
        "就这样",
        "按这个",
        "确认提交",
        "继续执行",
    }
    if text in exact_confirm_terms:
        return True
    confirm_prefixes = ("确认", "继续", "同意", "可以", "好的", "ok", "yes")
    allowed_suffixes = {
        "执行",
        "提交",
        "保存",
        "处理",
        "开始",
        "继续",
        "下一步",
        "继续下一步",
        "提交当前结果",
        "提交当前方案",
        "提交当前拆分结果",
        "保存当前结果",
        "保存当前方案",
        "执行当前结果",
        "执行当前方案",
        "执行当前操作",
        "吧",
        "了",
        "这版",
        "这个",
        "当前结果",
        "当前方案",
        "当前拆分",
        "本次结果",
        "本次方案",
        "当前待确认结果",
    }
    for prefix in (*confirm_prefixes, "好"):
        if not text.startswith(prefix):
            continue
        suffix = text[len(prefix):]
        if suffix in allowed_suffixes:
            return True
    return False


def _agent_message_continues_flow(message: str) -> bool:
    text = _agent_compact_message_for_intent(message)
    return text in {"继续", "继续执行", "继续下一步", "下一步继续", "接着做", "接着来"}


def _agent_message_confirms_destructive_operation(message: str, operation_type: str) -> bool:
    compact = _agent_compact_message_for_intent(message)
    if not compact:
        return False
    expected_reply = _agent_compact_message_for_intent(agent_operation_reply(operation_type))
    return bool(expected_reply and compact == expected_reply)


def _plot_split_initial_user_instruction(message: str, *, control_message: bool = False) -> str:
    if control_message or _agent_message_confirms(message):
        return ""
    return str(message or "").strip()


def _agent_message_cancels_destructive_operation(message: str) -> bool:
    compact = _agent_compact_message_for_intent(message)
    if not compact:
        return False
    exact_cancel_terms = {
        "取消",
        "停止",
        "算了",
        "先不",
        "暂不",
        "不用",
        "先不要",
        "先别",
        "不删了",
        "不删除了",
        "不清空了",
        "取消删除",
        "取消清空",
        "先不删",
        "先不删除",
        "先不清空",
        "不用删",
        "不用删除",
        "不用清空",
    }
    if compact in exact_cancel_terms:
        return True
    cancel_terms = ("取消", "停止", "先不", "暂不", "不用", "别", "不要", "不删", "不删除", "不清空")
    destructive_target_terms = (
        "删除",
        "删",
        "删掉",
        "清空",
        "清除",
        "资产",
        "拆分",
        "最新一组",
        "上一组",
        "这一组",
        "这组",
        "全部",
        "所有",
    )
    return any(term in compact for term in cancel_terms) and any(
        term in compact for term in destructive_target_terms
    )


def _agent_task_type_for_pending_operation(operation_type: str | None) -> str:
    return agent_operation_task_type(operation_type)


def _plot_split_pending_operation(
    *,
    episode_id: str,
    proposal: dict[str, Any],
    session_id: str | None,
    user_instruction: str,
    source: str,
    message: str,
    source_ref: dict[str, Any] | None = None,
    base_user_instruction: str | None = None,
    effective_revision_requirements: list[str] | None = None,
    revision_count: int | None = None,
) -> dict[str, Any]:
    clean_proposal = _agent_compact_plot_split_proposal(proposal)
    requirements = _agent_plot_split_revision_requirements(effective_revision_requirements or [])
    clean_revision_count = _agent_plot_split_revision_count(
        revision_count,
        fallback=len(requirements),
    )
    source_input_ref: dict[str, Any] = {
        "type": "episode_source_text",
        "episodeId": episode_id,
    }
    if isinstance(source_ref, dict) and source_ref:
        source_input_ref["sourceRef"] = copy.deepcopy(source_ref)
    clean_base_instruction = _compact_text(
        base_user_instruction if base_user_instruction is not None else user_instruction,
        500,
    )
    commit_payload = {
        "episodeId": episode_id,
        "plotSplitProposal": clean_proposal,
        "userInstruction": _compact_text(user_instruction, 1200),
        "sourceInputRef": source_input_ref,
    }
    if clean_base_instruction:
        commit_payload["baseUserInstruction"] = clean_base_instruction
    if requirements:
        commit_payload["effectiveRevisionRequirements"] = requirements
    if clean_revision_count:
        commit_payload["revisionCount"] = clean_revision_count
    return {
        "type": "commit_plot_split",
        "operationType": "commit_plot_split",
        "status": "waiting_user_confirmation",
        "source": source,
        "sessionId": str(session_id or ""),
        "createdAt": _now(),
        "requiresUserConfirmation": True,
        "expectedNextTool": "commit_plot_split",
        "proposal": clean_proposal,
        "latestResult": {"plotSplitProposal": clean_proposal},
        "sourceInputRef": source_input_ref,
        "effectiveRevisionRequirements": requirements,
        "revisionCount": clean_revision_count,
        "commitPayload": commit_payload,
        "nextAllowedTools": ["commit_plot_split"],
        "message": message,
    }
