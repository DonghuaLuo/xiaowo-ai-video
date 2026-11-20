# -*- coding: utf-8 -*-
"""创作要求的上下文提取、缓存和分析任务调用。"""
from __future__ import annotations

import utils.agent_sdk_runtime as agent_sdk_runtime
from .worker_contract import (
    worker_work_definition,
)
import copy as copy
import hashlib as hashlib
import json as json
import re as re
import threading as threading
import time as time
import traceback as traceback
from .agent_context_runtime import (
    _agent_json_chars,
    _agent_json_object_from_text,
)
from .agent_conversation_context import (
    _agent_session_messages_for_prompt,
)
from .agent_sessions import (
    append_agent_execution_error,
)
from .source_text_store import _compact_text
from pathlib import (
    Path,
)

from typing import Any


_REQUIREMENT_EXTRACTOR_CACHE_MAX = 128


_REQUIREMENT_EXTRACTOR_CACHE: dict[str, dict[str, Any]] = {}


_REQUIREMENT_EXTRACTOR_CACHE_LOCK = threading.Lock()


def _agent_dialogue_rows_for_requirement_extractor(
    project_id: str,
    session_id: str | None,
    *,
    current_message: str = "",
    limit: int = 12,
) -> list[dict[str, Any]]:
    rows: list[dict[str, str]] = []
    messages = _agent_session_messages_for_prompt(
        project_id,
        session_id,
        current_message=current_message,
    )
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = "assistant" if str(item.get("role") or "") == "assistant" else "user"
        text = _compact_text(str(item.get("text") or ""), 1200)
        if text:
            rows.append({"role": role, "text": text})
    current_text = _compact_text(str(current_message or ""), 1200)
    if current_text and (not rows or rows[-1].get("role") != "user" or rows[-1].get("text") != current_text):
        rows.append({"role": "user", "text": current_text})
    sliced = rows[-max(1, int(limit or 12)) :]
    return [{"index": index, **row} for index, row in enumerate(sliced, start=1)]


_AGENT_PROGRAM_WORK_DEFINITIONS: dict[str, dict[str, Any]] = {
    "storyboard-image-generation": {
        "workType": "storyboard_image_generation",
        "description": "依据当前分镜脚本、参考素材和版式生成分镜图。",
        "constraintFocus": [
            "本次分镜图的画面、镜头、版式、风格或质量要求",
            "当前镜头必须保留的主体、构图、空间关系和故事版格式",
            "用户提供的参考图用法和本轮画面修改意见",
        ],
    },
    "storyboard-image-edit": {
        "workType": "storyboard_image_edit",
        "description": "依据已有分镜图、本轮修改意见和可选参考图编辑画面。",
        "constraintFocus": [
            "本次编辑要修改的具体画面内容",
            "需要保留的原图结构、镜头顺序、角色位置、场景关系和版式",
            "本轮参考图与原图各自的使用方式",
        ],
    },
    "visual-handoff-image-generation": {
        "workType": "visual_handoff_image_generation",
        "description": "依据当前分镜图和相邻片段衔接要求生成视觉交接图。",
        "constraintFocus": [
            "本次视觉交接图生成的衔接方向、保留元素、画面变化或风格补充要求",
            "需要从当前分镜图中保留的角色、场景、构图、动作和视觉连续性",
            "本轮用户对交接画面的具体修改意见",
        ],
    },
}


def _agent_work_definition(work_name: str) -> dict[str, Any]:
    normalized = str(work_name or "").strip()
    program_work = _AGENT_PROGRAM_WORK_DEFINITIONS.get(normalized)
    if program_work:
        return copy.deepcopy(program_work)
    return worker_work_definition(normalized)


def _agent_requirement_extractor_system_prompt() -> str:
    return (
        "你负责提炼影视制作任务的用户约束。"
        "只从双方对话历史中提炼与当前任务相关的用户要求。"
        "只根据提供的对话记录判断。"
        "有约束就是有，没有就是没有；不要为了填字段强行总结。"
        "允许根据真实意图做语义判断，但必须能从对话中得到依据。"
        "只输出严格 JSON 对象，不要 Markdown。"
    )


def _agent_requirement_extractor_payload(
    project_id: str,
    session_id: str | None,
    work_name: str,
    user_message: str,
) -> dict[str, Any]:
    work_definition = _agent_work_definition(work_name)
    return {
        "workName": work_name,
        "work": work_definition,
        "dialogueMessages": _agent_dialogue_rows_for_requirement_extractor(
            project_id,
            session_id,
            current_message=user_message,
        ),
        "rules": [
            "只提炼与 work.workType 相关的用户约束、偏好、注意事项或专属信息。",
            "智能体回复只能作为理解用户意图的上下文，不要把执行结果或流程解释当成用户约束。",
            "如果没有相关约束，constraints 返回空数组，summary 返回空字符串。",
            "单纯的执行动作不是约束，例如生成、重新生成、编辑、修改；只有画面、风格、镜头、构图、色彩、氛围、质量、保留项、参考方式等补充要求才算约束。",
            "结合 work.workType 和用户完整表达判断某句话是否属于本次任务约束。",
            "约束要短句化、可执行，不要输出长解释。",
            "evidence 只能引用 dialogueMessages[].index，不要复制完整对话原文。",
        ],
        "responseSchema": {
            "workType": work_definition.get("workType"),
            "constraints": ["与当前 work 相关的约束短句；没有则空数组"],
            "summary": "一句话总括；没有约束则空字符串",
            "evidence": [
                {
                    "constraint": "必须等于 constraints 中的一条约束",
                    "messageIndexes": ["该约束依据的 dialogueMessages[].index"],
                }
            ],
        },
    }


def _agent_requirement_extractor_prompt(payload: dict[str, Any]) -> str:
    return (
        "请从下面的双方对话历史中，提炼与当前 work 相关的用户约束。\n"
        "要求：\n"
        "1. 只输出 JSON，不执行任何任务。\n"
        "2. 只使用 dialogueMessages；不要假设文件、日志或项目状态中存在额外要求。\n"
        "3. 必须先按 work.workType 理解当前 work，再判断哪些对话内容相关。\n"
        "4. 结合 work 类型与对话上下文，判断用户表达是否约束本次任务。\n"
        "5. 没有相关约束时返回空 constraints、空 summary 和空 evidence。\n"
        "6. evidence 只返回 messageIndexes，不要复制对话原文。\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _agent_empty_extracted_requirements(
    work_definition: dict[str, Any],
    *,
    skipped_reason: str = "",
) -> dict[str, Any]:
    result = {
        "workType": str(work_definition.get("workType") or ""),
        "constraints": [],
        "summary": "",
        "evidence": [],
        "source": "requirement_extractor",
    }
    if skipped_reason:
        result["skippedReason"] = skipped_reason
    return result


def _agent_requirement_is_action_only(text: str, work_type: str) -> bool:
    return not str(text or "").strip()


def _agent_clean_work_requirement_constraint(text: str, work_type: str) -> str:
    return _compact_text(str(text or ""), 260)


def _agent_requirement_extractor_cache_key(
    project_id: str,
    session_id: str | None,
    work_name: str,
    payload: dict[str, Any],
) -> str:
    work = payload.get("work") if isinstance(payload.get("work"), dict) else {}
    cache_payload = {
        "projectId": str(project_id or ""),
        "sessionId": str(session_id or ""),
        "workName": str(work_name or ""),
        "workType": str(work.get("workType") or ""),
        "workDescription": str(work.get("description") or ""),
        "dialogueMessages": payload.get("dialogueMessages") if isinstance(payload.get("dialogueMessages"), list) else [],
    }
    raw = json.dumps(cache_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _agent_requirement_extractor_skip_reason(
    payload: dict[str, Any],
    user_message: str,
) -> str:
    messages = payload.get("dialogueMessages") if isinstance(payload.get("dialogueMessages"), list) else []
    if not messages:
        return "empty_dialogue"
    user_rows = [
        row
        for row in messages
        if isinstance(row, dict) and str(row.get("role") or "").strip().lower() == "user"
    ]
    if not user_rows:
        return "no_user_dialogue"
    current_text = re.sub(r"\s+", "", str(user_message or "").strip()).casefold()
    user_texts = [
        re.sub(r"\s+", "", str(row.get("text") or "").strip()).casefold()
        for row in user_rows
        if str(row.get("text") or "").strip()
    ]
    has_prior_user_text = any(text and text != current_text for text in user_texts)
    if has_prior_user_text:
        return ""
    return ""


def _agent_normalize_extracted_requirements(
    data: dict[str, Any],
    work_definition: dict[str, Any],
) -> dict[str, Any]:
    work_type = str(work_definition.get("workType") or "").strip()
    if not isinstance(data, dict):
        return _agent_empty_extracted_requirements(work_definition, skipped_reason="invalid_output")
    constraints: list[str] = []
    seen: set[str] = set()
    raw_constraints = data.get("constraints") if isinstance(data.get("constraints"), list) else []
    for item in raw_constraints:
        text = _agent_clean_work_requirement_constraint(str(item or ""), work_type)
        if _agent_requirement_is_action_only(text, work_type):
            continue
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        constraints.append(text)
        if len(constraints) >= 12:
            break
    if not constraints:
        return _agent_empty_extracted_requirements(work_definition)
    constraint_map = {constraint.casefold(): constraint for constraint in constraints}
    evidence: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
    raw_evidence = data.get("evidence") if isinstance(data.get("evidence"), list) else []
    for item in raw_evidence:
        if not isinstance(item, dict):
            continue
        constraint_text = _compact_text(
            str(item.get("constraint") or item.get("text") or item.get("requirement") or ""),
            260,
        )
        constraint = constraint_map.get(constraint_text.casefold())
        if not constraint:
            continue
        raw_indexes = (
            item.get("messageIndexes")
            if isinstance(item.get("messageIndexes"), list)
            else item.get("message_indices")
        )
        if not isinstance(raw_indexes, list):
            raw_indexes = [raw_indexes]
        indexes: list[int] = []
        for raw_index in raw_indexes:
            try:
                message_index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if message_index <= 0 or message_index in indexes:
                continue
            indexes.append(message_index)
            if len(indexes) >= 8:
                break
        if not indexes:
            continue
        evidence_key = f"{constraint.casefold()}:{','.join(str(index) for index in indexes)}"
        if evidence_key in seen_evidence:
            continue
        seen_evidence.add(evidence_key)
        evidence.append({"constraint": constraint, "messageIndexes": indexes})
        if len(evidence) >= 12:
            break
    return {
        "workType": str(data.get("workType") or data.get("work_type") or work_type),
        "constraints": constraints,
        "summary": _compact_text(str(data.get("summary") or ""), 500),
        "evidence": evidence,
        "source": "requirement_extractor",
    }


def _agent_extract_work_requirements(
    project_id: str,
    session_id: str | None,
    work_name: str,
    user_message: str,
    runtime_config: dict[str, Any],
    *,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    work_definition = _agent_work_definition(work_name)
    payload = _agent_requirement_extractor_payload(project_id, session_id, work_name, user_message)
    if not payload.get("dialogueMessages"):
        return _agent_empty_extracted_requirements(work_definition, skipped_reason="empty_dialogue")
    skipped_reason = _agent_requirement_extractor_skip_reason(payload, user_message)
    if skipped_reason:
        return _agent_empty_extracted_requirements(work_definition, skipped_reason=skipped_reason)
    cache_key = _agent_requirement_extractor_cache_key(project_id, session_id, work_name, payload)
    with _REQUIREMENT_EXTRACTOR_CACHE_LOCK:
        cached = _REQUIREMENT_EXTRACTOR_CACHE.get(cache_key)
    if cached is not None:
        extracted = copy.deepcopy(cached)
        extracted["diagnostics"] = {
            "cacheHit": True,
            "payloadChars": _agent_json_chars(payload),
        }
        return extracted
    prompt = _agent_requirement_extractor_prompt(payload)
    started_at = time.monotonic()
    try:
        result = agent_sdk_runtime.run_sdk_turn(
            reasoning_task="agent-requirements",
            reasoning_mode=runtime_config.get("reasoningMode"),
            prompt=prompt,
            system_prompt=_agent_requirement_extractor_system_prompt(),
            cwd=Path(runtime_config["cwd"]),
            env=dict(runtime_config["env"]),
            model=str(runtime_config.get("modelName") or ""),
            on_api_exchange=runtime_config.get("onApiExchange"),
            snapshot_provider=lambda: payload,
            action_request_handler=lambda _action, _rationale: {},
            tool_request_handler=lambda _tool_name, _args: {
                "success": False,
                "error": "requirement_extractor 不允许调用工具",
            },
            stream_event_handler=None,
            resume_id=None,
            allowed_tools=[],
            max_turns=1,
            cancel_event=cancel_event,
        )
    except Exception as exc:  # noqa: BLE001
        append_agent_execution_error(
            project_id,
            stage="requirement_extractor",
            message="关键需求提炼失败",
            session_id=session_id,
            category="requirement_extractor_error",
            source="agent_requirement_extractor",
            error=exc,
            details={"workName": work_name, "workType": work_definition.get("workType")},
            include_traceback=True,
        )
        print(traceback.format_exc(), flush=True)
        return _agent_empty_extracted_requirements(work_definition, skipped_reason="extractor_exception")
    if result.get("cancelled"):
        return _agent_empty_extracted_requirements(work_definition, skipped_reason="cancelled")
    raw_reply = str(result.get("reply") or "").strip()
    data = _agent_json_object_from_text(raw_reply)
    extracted = _agent_normalize_extracted_requirements(data, work_definition)
    extracted["diagnostics"] = {
        "promptChars": len(prompt),
        "payloadChars": _agent_json_chars(payload),
        "replyChars": len(raw_reply),
        "totalMs": int((time.monotonic() - started_at) * 1000),
    }
    if not result.get("success"):
        extracted["skippedReason"] = "extractor_failed"
    elif not data:
        extracted["skippedReason"] = "invalid_json"
    if result.get("success") and data:
        cache_value = copy.deepcopy(extracted)
        cache_value.pop("diagnostics", None)
        with _REQUIREMENT_EXTRACTOR_CACHE_LOCK:
            if len(_REQUIREMENT_EXTRACTOR_CACHE) >= _REQUIREMENT_EXTRACTOR_CACHE_MAX:
                try:
                    _REQUIREMENT_EXTRACTOR_CACHE.pop(next(iter(_REQUIREMENT_EXTRACTOR_CACHE)))
                except StopIteration:
                    pass
            _REQUIREMENT_EXTRACTOR_CACHE[cache_key] = cache_value
    return extracted


def _agent_extract_worker_requirements(
    project_id: str,
    session_id: str | None,
    worker_name: str,
    user_message: str,
    runtime_config: dict[str, Any],
    *,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    if str(worker_name or "").strip() == "analyze-assets":
        return _agent_empty_extracted_requirements(
            _agent_work_definition(worker_name),
            skipped_reason="not_required_for_analyze_assets",
        )
    return _agent_extract_work_requirements(
        project_id,
        session_id,
        worker_name,
        user_message,
        runtime_config,
        cancel_event=cancel_event,
    )


def _agent_program_work_effective_instruction(
    user_instruction: str,
    extracted_requirements: dict[str, Any] | None,
    *,
    limit: int = 2400,
) -> str:
    base_text = re.sub(r"[ \t]+", " ", str(user_instruction or "").strip())
    base_text = re.sub(r"\n{3,}", "\n\n", base_text)
    extracted = extracted_requirements if isinstance(extracted_requirements, dict) else {}
    constraints = [
        _compact_text(str(item or ""), 260)
        for item in (extracted.get("constraints") if isinstance(extracted.get("constraints"), list) else [])
    ]
    rows: list[str] = []
    seen: set[str] = set()

    def _append_row(value: str) -> None:
        text = _compact_text(value, 700)
        key = re.sub(r"\s+", "", text).casefold()
        if not text or key in seen:
            return
        seen.add(key)
        rows.append(text)

    _append_row(base_text)
    for constraint in constraints:
        _append_row(constraint)
    summary = _compact_text(str(extracted.get("summary") or ""), 500)
    if summary and not any(summary in row or row in summary for row in rows):
        _append_row(summary)
    if not rows:
        return ""
    if len(rows) == 1:
        return rows[0][:limit]
    combined = "本次执行补充要求：\n" + "\n".join(
        f"{index}. {row}" for index, row in enumerate(rows, start=1)
    )
    if len(combined) > limit:
        return f"{combined[: max(0, limit - 8)].rstrip()}...（截断）"
    return combined
