"""Shared target and generation contracts for agent messages and task adapters."""

import re as re
from .work_chain_actions import (
    WORK_CHAIN_ACTIONS,
)

from typing import Any


AGENT_TARGET_CONTEXT_FIELDS = (
    "source", "intent", "section", "episodeId", "canvasKind", "canvasId", "canvasTitle",
    "assetTab", "assetType", "assetId", "assetName", "nodeId", "nodeType", "nodeTitle",
    "routeId", "segmentId", "workChainId", "cardTitle", "field", "targetType", "targetId",
)
_PROJECT_TARGET_FIELDS = {
    "source", "intent", "section", "assetTab", "assetType", "assetId", "assetName",
    "cardTitle", "field", "targetType", "targetId",
}
_EPISODE_TARGET_FIELDS = set(AGENT_TARGET_CONTEXT_FIELDS) - _PROJECT_TARGET_FIELDS


def sanitize_agent_target_context(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        field: str(value[field]).strip()[:240]
        for field in AGENT_TARGET_CONTEXT_FIELDS
        if value.get(field) is not None and str(value[field]).strip()
    }


def agent_target_for_scope(scope: str | None, value: Any) -> dict[str, str]:
    target = sanitize_agent_target_context(value)
    if str(scope or "").strip() == "project":
        if target.get("section") == "episode" or any(target.get(key) for key in _EPISODE_TARGET_FIELDS - {"episodeId"}):
            return {}
        return {key: value for key, value in target.items() if key in _PROJECT_TARGET_FIELDS}
    if str(scope or "").strip() == "episode" and target.get("section") != "episode":
        return {}
    return target


def recent_creative_task_target(value: Any, episode_id: str) -> dict[str, str]:
    """Keep a session-local hint for follow-up edits, never a write authority."""
    target = agent_target_for_scope("episode", value)
    if (
        target.get("source") != "storyboard_canvas"
        or target.get("intent") != "generate"
        or target.get("canvasKind") != "work_chain"
        or target.get("episodeId") != str(episode_id or "").strip()
        or target.get("nodeType") not in {"prompt.storyboard", "director.board"}
        or not all(target.get(key) for key in ("nodeId", "routeId", "workChainId"))
    ):
        return {}
    return target


def is_work_chain_recommendation_target(value: Any) -> bool:
    target = sanitize_agent_target_context(value)
    return (
        target.get("source") == "agent_recommendation"
        and target.get("section") == "episode"
        and all(target.get(key) for key in ("episodeId", "workChainId", "nodeId", "nodeType"))
    )


AGENT_GENERATION_TASKS = {
    "asset_image": {"label": "资产图", "action": "asset_media_generated", "tool": "request_asset_image_generation", "output": "image"},
    "storyboard_image": {"label": "故事版分镜图", "action": "storyboard_image_generated", "tool": "request_storyboard_image_generation", "output": "image"},
    "storyboard_image_edit": {"label": "分镜图编辑结果", "action": "storyboard_image_edited", "tool": "edit_storyboard_image", "output": "image"},
    "visual_handoff_image": {"label": "视觉交接图", "action": "visual_handoff_image_generated", "tool": "request_visual_handoff_image_generation", "output": "image"},
    "storyboard_video": {"label": "视频", "action": "storyboard_video_generated", "tool": "request_storyboard_video_generation", "output": "video"},
    "route_video": {"label": "视频", "action": "route_video_generated", "tool": "request_route_video_generation", "output": "video"},
}

# Configuration resolution belongs to the existing media submission path.
AGENT_MEDIA_GENERATION_TOOLS = frozenset({
    row["tool"] for row in AGENT_GENERATION_TASKS.values() if row["output"] in {"image", "video"}
}) | {"resolve_generation_config"}


_AGENT_PRODUCTION_STEP_STATES = {action["taskType"]: action["stateId"] for action in WORK_CHAIN_ACTIONS}


def _agent_compact_message_for_intent(message: str) -> str:
    return re.sub(
        r"[\s,，、/／;；:：。！？!?（）()\[\]【】\"'“”‘’]+",
        "",
        str(message or ""),
    ).lower()


def _agent_task_pending_action(task_hypothesis: dict[str, Any] | None) -> str:
    task = task_hypothesis if isinstance(task_hypothesis, dict) else {}
    intent_status = str(task.get("intentStatus") or "").strip().lower()
    if bool(task.get("requiresClarification")) or intent_status in {"needs_clarification", "uncertain"}:
        return ""
    return _agent_normalize_pending_action(task.get("pendingAction"))


def _agent_normalize_pending_action(value: Any) -> str:
    raw = str(value or "").strip().lower()
    normalized = re.sub(r"[\s_-]+", "", raw)
    mapping = {
        "confirm": "confirm",
        "accept": "confirm",
        "continue": "confirm",
        "submit": "confirm",
        "commit": "confirm",
        "确认": "confirm",
        "继续": "confirm",
        "提交": "confirm",
        "认可": "confirm",
        "cancel": "cancel",
        "stop": "cancel",
        "discard": "cancel",
        "取消": "cancel",
        "停止": "cancel",
        "放弃": "cancel",
        "explain": "explain",
        "chat": "chat",
        "解释": "explain",
        "说明": "explain",
        "revise": "revise",
        "modify": "revise",
        "adjust": "revise",
        "rerun": "revise",
        "修改": "revise",
        "调整": "revise",
        "重跑": "revise",
        "重新生成": "revise",
        "freshrerun": "fresh_rerun",
        "restart": "fresh_rerun",
        "startover": "fresh_rerun",
        "重新来": "fresh_rerun",
        "从头来": "fresh_rerun",
        "不参考上次": "fresh_rerun",
        "newtask": "new_task",
        "switchtask": "new_task",
        "新任务": "new_task",
        "换任务": "new_task",
        "unclear": "unclear",
        "unknown": "unclear",
        "": "",
    }
    return mapping.get(normalized, raw if raw in {"confirm", "cancel", "explain", "chat", "revise", "fresh_rerun", "new_task", "unclear"} else "")


def _agent_steps_from_state(
    state: dict[str, Any],
    *,
    running_step: str | None = None,
    failed_step: str | None = None,
) -> list[dict[str, Any]]:
    rows = [
        ("source", "源文本", bool(state.get("sourceReady"))),
        ("overview", "项目概述", bool(state.get("overviewReady"))),
        ("characters", "角色", bool(state.get("characterReady"))),
        ("scenes", "场景", bool(state.get("sceneReady"))),
        ("props", "道具", bool(state.get("propReady"))),
        ("episodes", "分集原文", bool(state.get("episodeBoundaryReady"))),
    ]
    if not bool(state.get("projectScope", True)):
        rows.extend(
            [
                ("script", "原文事实拆分", bool(state.get("episodeSourceSplitReady") or state.get("episodeScriptReady"))),
                ("storyboard", "分镜工作流", bool(state.get("episodeWorkflowReady"))),
            ]
        )
    result: list[dict[str, Any]] = []
    for step_id, label, done in rows:
        status = "done" if done else "idle"
        if failed_step == step_id:
            status = "failed"
        elif running_step == step_id and not done:
            status = "running"
        result.append({"id": step_id, "label": label, "status": status})
    return result


def _agent_action_footer_instruction(
    label: str,
    title: str,
    *,
    description: str = "",
    reply: str = "",
) -> dict[str, str]:
    clean_label = str(label or "").strip()
    clean_title = str(title or "").strip()
    clean_description = str(description or "").strip()
    clean_reply = str(reply or "").strip()
    footer: dict[str, str] = {}
    if clean_label:
        footer["label"] = clean_label
    if clean_title:
        footer["title"] = clean_title
    if clean_description:
        footer["description"] = clean_description
    if clean_reply:
        footer["reply"] = clean_reply
    return footer


def _agent_continue_reply_instruction() -> dict[str, str]:
    return {
        "label": "下一步",
        "title": "继续下一步",
        "description": "回复“继续”后，我会按当前推荐的下一步执行。",
        "reply": "继续",
    }


def _agent_confirmation_reply_instruction() -> dict[str, str]:
    return {
        "label": "需要确认",
        "title": "确认后继续",
        "description": "回复“确认”后，我会提交当前待确认结果。",
        "reply": "确认",
    }


def _agent_chinese_ordinal_value(value: str) -> int:
    text = re.sub(r"\s+", "", str(value or "").strip())
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
    if text in digits:
        return digits[text]
    if "十" in text:
        left, right = text.split("十", 1)
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return 0
