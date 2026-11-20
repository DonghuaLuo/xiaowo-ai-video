# -*- coding: utf-8 -*-
"""智能体动作、任务类型与公开工具能力的协议约束。"""
from __future__ import annotations

import re as re
from .agent_context_runtime import _load_agent_ops_permissions
from .agent_task_catalog import _agent_known_task_types, _agent_task_catalog
from .agent_session_policy import (
    agent_session_task_type_allowed,
    validate_agent_session_action,
)

from typing import Any


_AGENT_BACKGROUND_ACTIONS = {
    "analyze_overview",
}


_AGENT_ALLOWED_ACTIONS = _AGENT_BACKGROUND_ACTIONS | {
    "show_progress",
    "explain_workflow",
}


_AGENT_ACTION_ORDER = [
    "show_progress",
    "explain_workflow",
    "analyze_overview",
]


_AGENT_PROGRAM_DIRECT_ACTIONS = {
    "show_progress",
    "explain_workflow",
    "analyze_overview",
}


def _agent_program_action_from_message(
    message: str,
    state: dict[str, Any] | None = None,
) -> str | None:
    normalized = re.sub(r"\s+", "", str(message or "")).strip("。！？!?.,，")
    if normalized in {"/progress", "查看当前进度", "检查当前进度", "检查当前阶段"}:
        return "show_progress" if "show_progress" in _agent_allowed_actions() else None
    if normalized in {"/workflow", "说明完整拆分流程"}:
        return "explain_workflow" if "explain_workflow" in _agent_allowed_actions() else None
    if normalized in {"/analyze_overview"}:
        return "analyze_overview" if "analyze_overview" in _agent_allowed_actions() else None
    return None


def _agent_allowed_actions() -> set[str]:
    configured = _load_agent_ops_permissions().get("agent_actions")
    if not isinstance(configured, list):
        return set(_AGENT_ALLOWED_ACTIONS)
    configured_actions = {str(item).strip() for item in configured if str(item).strip()}
    if not configured_actions:
        return set(_AGENT_ALLOWED_ACTIONS)
    return set(_AGENT_ALLOWED_ACTIONS) & configured_actions


def _agent_action_order() -> list[str]:
    allowed = _agent_allowed_actions()
    return [action for action in _AGENT_ACTION_ORDER if action in allowed]


def _agent_program_direct_actions() -> set[str]:
    return _agent_allowed_actions() & _AGENT_PROGRAM_DIRECT_ACTIONS


def _agent_action_order_for_session_policy(session_policy: dict[str, Any] | None) -> list[str]:
    result: list[str] = []
    for action in _agent_action_order():
        try:
            validate_agent_session_action(action, session_policy)
        except ValueError:
            continue
        result.append(action)
    return result


def _agent_task_catalog_for_session_policy(session_policy: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [
        item
        for item in _agent_task_catalog()
        if agent_session_task_type_allowed(item.get("taskType"), session_policy)
    ]


def _agent_quick_prompts_for_session_policy(
    state: dict[str, Any],
    session_policy: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    policy_scope = str((session_policy or {}).get("scope") or "").strip()
    project_scope = (
        policy_scope == "project"
        if policy_scope in {"project", "episode"}
        else bool(state.get("projectScope", True))
    )
    for item in _agent_quick_prompts(state):
        if (
            project_scope
            and str(item.get("id") or "").strip() == "plan_episode_work_chains"
        ):
            continue
        task_type = str(item.get("taskType") or "").strip()
        if task_type and not agent_session_task_type_allowed(task_type, session_policy):
            continue
        result.append(item)
    if project_scope:
        result.sort(key=lambda item: item.get("id") != "next_step")
    return result




def _agent_validate_task_type(task_type: str | None) -> str:
    normalized = str(task_type or "").strip()
    if not normalized:
        return ""
    if normalized not in _agent_known_task_types():
        raise ValueError("智能体任务阶段不在允许范围内")
    return normalized


def _agent_is_background_action(action: str | None) -> bool:
    normalized = str(action or "").strip()
    return normalized in _AGENT_BACKGROUND_ACTIONS and normalized in _agent_allowed_actions()


def _agent_validate_action(action: str | None) -> str:
    normalized = str(action or "").strip()
    if normalized not in _agent_allowed_actions():
        raise ValueError("智能体动作不在允许范围内")
    return normalized


def _agent_action_description(action: str, state: dict[str, Any]) -> str:
    descriptions = {
        "show_progress": "汇总当前会话范围内的项目进度，并给出默认下一步。",
        "explain_workflow": "解释当前项目从小说到分集剧本和分镜的创作流程。",
        "analyze_overview": "读取小说文本，生成项目概述、题材语境和主题视觉。",
    }
    return descriptions.get(action, _agent_action_label(action, state))


def _agent_action_prompt(action: str, state: dict[str, Any]) -> str:
    prompts = {
        "show_progress": "查看当前进度",
        "explain_workflow": "说明完整拆分流程",
        "analyze_overview": "请生成项目概述、题材语境和主题视觉。",
    }
    return prompts.get(action, _agent_action_label(action, state))


def _agent_action_icon(action: str) -> str:
    if action == "show_progress":
        return "list-checks"
    if action == "explain_workflow":
        return "workflow"
    return "zap"


def _agent_episode_title_reference(title: Any) -> str:
    text = str(title or "").strip() or "当前集"
    if text.startswith("《") and text.endswith("》"):
        return text
    return f"《{text}》"


def _agent_plot_split_quick_prompt(selected_title: Any) -> str:
    return (
        f"请拆分当前分集{_agent_episode_title_reference(selected_title)}的剧情，"
        "并为每段关联已有的场景、人物、生物和道具。"
    )


def _agent_is_plot_split_quick_control_message(
    message: str,
    state: dict[str, Any],
    task_hypothesis: dict[str, Any] | None,
) -> bool:
    hypothesis = task_hypothesis if isinstance(task_hypothesis, dict) else {}
    return str(hypothesis.get("preferredTaskType") or "").strip() == "work_chain_plan_save"


def _agent_quick_prompts(state: dict[str, Any]) -> list[dict[str, Any]]:
    selected_title = str(
        state.get("selectedEpisodeTitle") or state.get("selectedEpisodeId") or "当前集"
    ).strip() or "当前集"
    rows = [
        {
            "id": "asset_range",
            "label": "规划资产范围",
            "prompt": (
                "请根据当前小说进度，规划下一段资产提取的原文断点，"
                "并判断是否需要新增整体阶段视觉。"
            ),
            "taskType": _agent_validate_task_type("asset_range_propose"),
            "controlOnly": True,
        },
        {
            "id": "episode_boundary",
            "label": "规划下一集",
            "prompt": (
                "请根据当前小说进度，为下一集选择自然断点和具体短标题，说明依据。"
            ),
            "taskType": _agent_validate_task_type("episode_boundary_propose"),
            "controlOnly": True,
        },
        {
            "id": "next_step",
            "label": "查看当前进度",
            "prompt": "查看当前进度",
            "taskType": _agent_validate_task_type("project_status"),
            "controlOnly": True,
        },
        {
            "id": "plan_episode_work_chains",
            "label": "生成当前集画布",
            "prompt": _agent_plot_split_quick_prompt(selected_title),
            "taskType": _agent_validate_task_type("work_chain_plan_save"),
            "controlOnly": True,
        },
    ]
    blocking_range = state.get("blockingAssetRange") if isinstance(state.get("blockingAssetRange"), dict) else {}
    if (int(state.get("blockingAssetRangeCount") or 0) > 0
            and str(blocking_range.get("analysisStatus") or "").strip().lower()
            in {"committed", "failed", "cancelled", "canceled"}):
        rows.insert(3, {
            "id": "asset_extraction",
            "label": "拆分当前资产",
            "prompt": "请拆分当前已确认资产范围内的角色、生物、场景和道具。读取本段原文与已有资产，验收结构化结果后提交并简要报告。",
            "taskType": _agent_validate_task_type("asset_extraction"),
            "controlOnly": True,
        })
    return rows


def _agent_action_label(action: str, state: dict[str, Any]) -> str:
    mapping = {
        "show_progress": "查看当前进度",
        "explain_workflow": "说明完整拆分流程",
        "analyze_overview": "先生成项目概述",
    }
    return mapping.get(action, action)
