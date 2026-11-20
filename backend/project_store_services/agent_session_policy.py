# -*- coding: utf-8 -*-
"""Trusted session policy for ai-video agent conversations."""

from __future__ import annotations

import re
from typing import Any

from .catalogs import PROJECTS_DIR
from .store_core import _read_json

_EPISODE_PLANNING_DEFAULT_TARGETS = {"source_splits", "storyboards"}
_ALL_PLANNING_TARGETS = {"source_index", "source_splits", "asset_ranges", "storyboards"}
_CURRENT_EPISODE_SESSION_LABEL = "当前集会话"
_EPISODE_SESSION_PROJECT_FLOW_REJECTION = (
    "当前集会话（从分集/剧集列表进入某一集后的会话）只能处理当前集画布和当前集工作链细节，"
    "不能执行项目主流程：生成项目概述、拆分资产、规划/提交分集断点或修改项目默认拆分配置。请切换到项目会话处理。"
)
_EPISODE_SESSION_PROJECT_DELETE_REJECTION = (
    "当前集会话（从分集/剧集列表进入某一集后的会话）不能执行项目级资产删除或清空。请切换到项目会话后再操作。"
)
_PROJECT_SESSION_EPISODE_FLOW_REJECTION = (
    "这是分集画布任务。请打开目标分集的会话后执行；项目会话中的讨论和待确认候选会保留在原会话。"
)
_PROJECT_SESSION_BLOCKED_EPISODE_FLOW_TOOLS = {
    f"mcp__ai_video__{name}" for name in {
        "save_episode_work_chain_plan", "patch_shot_prompt", "upsert_workflow_node",
        "delete_workflow_node", "save_workflow_node_inline_edit", "create_workflow_task_card",
        "add_workflow_asset_nodes", "update_workflow_route", "link_workflow_input",
        "unlink_workflow_input",
        "request_storyboard_image_generation",
        "request_visual_handoff_image_generation",
        "get_cinematic_script_context", "submit_cinematic_script_result",
        "list_workflow_node_versions", "read_workflow_node_version",
        "get_director_plan_context", "validate_director_plan_draft", "submit_director_plan_result",
        "get_video_prompt_context", "submit_video_prompt_result",
        "get_video_prompt_optimization_context", "submit_video_prompt_optimization_result",
        "get_video_prompt_standalone_context", "submit_video_prompt_standalone_result",
        "request_storyboard_video_generation",
        "edit_storyboard_image", "request_route_video_generation", "request_asset_image_generation",
    }
}
_PROJECT_SESSION_BLOCKED_EPISODE_TASK_TYPES = {
    "work_chain_plan_discuss", "work_chain_plan_save", "shot_prompt_patch",
    "workflow_node_content_update", "workflow_node_update", "workflow_update",
    "workflow_cinematic_script_generation", "director_plan_generation",
    "video_prompt_generation", "video_prompt_optimization", "video_prompt_standalone_generation", "storyboard_image_generation",
    "visual_handoff_image_generation", "storyboard_video_generation",
    "asset_image_generation", "generation_request",
}
_EPISODE_SESSION_BLOCKED_PROJECT_FLOW_TOOLS = {
    "mcp__ai_video__request_overview_analysis",
    "mcp__ai_video__save_story_world_map",
    "mcp__ai_video__get_asset_range_context",
    "mcp__ai_video__submit_asset_range_candidate",
    "mcp__ai_video__get_asset_extraction_context",
    "mcp__ai_video__get_asset_extraction_asset_catalog",
    "mcp__ai_video__submit_asset_extraction_result",
    "mcp__ai_video__submit_episode_boundary_candidate",
    "mcp__ai_video__update_project_settings",
}
_EPISODE_SESSION_BLOCKED_PROJECT_DELETE_TOOLS = {
    "mcp__ai_video__delete_all_project_assets",
    "mcp__ai_video__delete_asset",
}
_EPISODE_SESSION_BLOCKED_TOOLS = (
    _EPISODE_SESSION_BLOCKED_PROJECT_FLOW_TOOLS | _EPISODE_SESSION_BLOCKED_PROJECT_DELETE_TOOLS
)
_EPISODE_SESSION_BLOCKED_TASK_TYPES = {
    "overview_request",
    "settings_update",
    "asset_range_propose",
    "asset_extraction",
    "asset_range_commit",
    "episode_boundary_propose",
}
_EPISODE_SESSION_BLOCKED_PENDING_OPERATION_TYPES = {
    "commit_asset_range",
    "asset_range",
    "commit_episode_boundary",
    "episode_boundary",
}
_EPISODE_SESSION_BLOCKED_ACTIONS = {"analyze_overview"}


class AgentSessionPolicyError(ValueError):
    """Raised when a trusted session policy blocks an agent operation."""


def _policy_safe_episode_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text in {".", ".."} or "/" in text or "\\" in text or ":" in text:
        raise ValueError(f"分集 ID 无效：{text}")
    return text


def _episode_sort_key(episode_id: str) -> tuple[Any, ...]:
    text = _policy_safe_episode_id(episode_id)
    match = re.fullmatch(r"([A-Za-z]*)(\d+)", text)
    if match:
        return (0, match.group(1).casefold(), int(match.group(2)), len(match.group(2)), text)
    return (1, text.casefold())


def agent_session_context_scope(scope: str | None, episode_id: str | None) -> str:
    value = str(scope or "").strip()
    if value in {"project", "episode"}:
        return value
    episode = str(episode_id or "").strip()
    if episode in {"", "__project__"} or episode.casefold() == "project":
        return "project"
    return "episode"


def _project_dir(project_id: str):
    if not str(project_id or "").strip():
        raise ValueError("缺少 projectId")
    return PROJECTS_DIR / str(project_id).strip()


def _project_episode_ids(project_id: str) -> list[str]:
    project_dir = _project_dir(project_id)
    coverage = _read_json(project_dir / "source_coverage.json", {})
    result: list[str] = []
    if isinstance(coverage, dict):
        for item in coverage.get("episodeRanges") or []:
            if not isinstance(item, dict):
                continue
            episode_id = _policy_safe_episode_id(item.get("episodeId") or item.get("episode_id"))
            if episode_id and episode_id not in result:
                result.append(episode_id)
    meta = _read_json(project_dir / "project.json", {})
    episodes = meta.get("episodes") if isinstance(meta, dict) else []
    for item in episodes if isinstance(episodes, list) else []:
        if not isinstance(item, dict):
            continue
        episode_id = _policy_safe_episode_id(item.get("id") or item.get("episodeId") or item.get("episode_id"))
        if episode_id and episode_id not in result:
            result.append(episode_id)
    if result:
        return result
    episodes_dir = project_dir / "episodes"
    if episodes_dir.exists() and episodes_dir.is_dir():
        for path in sorted(episodes_dir.iterdir()):
            if not path.is_dir():
                continue
            episode_id = _policy_safe_episode_id(path.name)
            if episode_id and episode_id not in result:
                result.append(episode_id)
    return result


def latest_project_episode_id(project_id: str) -> str:
    episode_ids = _project_episode_ids(project_id)
    return sorted(episode_ids, key=_episode_sort_key)[-1] if episode_ids else ""


def build_agent_session_policy(
    project_id: str,
    *,
    scope: str | None = None,
    episode_id: str | None = None,
    selected_episode_id: str | None = None,
) -> dict[str, Any]:
    context_scope = agent_session_context_scope(scope, episode_id)
    selected_episode = _policy_safe_episode_id(selected_episode_id or episode_id or "")
    latest_episode = latest_project_episode_id(project_id)
    current_episode = selected_episode or latest_episode or "E01"
    is_project_scope = context_scope == "project"
    return {
        "scope": context_scope,
        "progressMode": "project_main_flow" if is_project_scope else "episode_detail_flow",
        "currentEpisodeId": current_episode,
        "selectedEpisodeId": selected_episode,
        "latestEpisodeId": latest_episode,
        "mayCrossEpisode": is_project_scope,
        "mayDeleteAllPlanning": is_project_scope,
        "mayDeleteOtherEpisodeCanvas": is_project_scope,
        "mayDeleteEpisodeSource": is_project_scope or (current_episode and current_episode == latest_episode),
        "allowedEpisodeIds": [] if is_project_scope else [current_episode],
        "notes": [
            "项目会话按主流程推进：拆分资产、规划/提交分集原文；当前集分集原文完成后继续下一集。",
            "当前集会话只处理当前集；默认下一步按当前集工作链细节顺序推荐。",
            "跨范围创作任务请切换到目标项目或分集会话，原会话的消息、运行与候选不会转移。",
        ],
    }


def _episode_session_policy_enabled(policy: dict[str, Any] | None) -> bool:
    return isinstance(policy, dict) and policy.get("scope") == "episode"


def _normalize_agent_tool_name(tool_name: str | None) -> str:
    text = str(tool_name or "").strip()
    if not text:
        return ""
    if text.startswith("mcp__ai_video__"):
        return text
    if text.startswith("ai_video__"):
        return f"mcp__{text}"
    if text.startswith("mcp__"):
        return text
    return f"mcp__ai_video__{text}"


def validate_agent_session_task_type(
    task_type: str | None,
    policy: dict[str, Any] | None,
) -> None:
    normalized = str(task_type or "").strip()
    if _episode_session_policy_enabled(policy) and normalized in _EPISODE_SESSION_BLOCKED_TASK_TYPES:
        raise ValueError(_EPISODE_SESSION_PROJECT_FLOW_REJECTION)
    if isinstance(policy, dict) and policy.get("scope") == "project" and normalized in _PROJECT_SESSION_BLOCKED_EPISODE_TASK_TYPES:
        raise ValueError(_PROJECT_SESSION_EPISODE_FLOW_REJECTION)


def agent_session_task_type_allowed(
    task_type: str | None,
    policy: dict[str, Any] | None,
) -> bool:
    try:
        validate_agent_session_task_type(task_type, policy)
    except ValueError:
        return False
    return True


def validate_agent_session_pending_operation(
    operation_type: str | None,
    policy: dict[str, Any] | None,
) -> None:
    if not _episode_session_policy_enabled(policy):
        return
    normalized = str(operation_type or "").strip()
    if normalized in _EPISODE_SESSION_BLOCKED_PENDING_OPERATION_TYPES:
        raise ValueError(_EPISODE_SESSION_PROJECT_FLOW_REJECTION)


def validate_agent_session_action(
    action: str | None,
    policy: dict[str, Any] | None,
) -> None:
    if not _episode_session_policy_enabled(policy):
        return
    normalized = str(action or "").strip()
    if normalized in _EPISODE_SESSION_BLOCKED_ACTIONS:
        raise ValueError(_EPISODE_SESSION_PROJECT_FLOW_REJECTION)


def validate_agent_session_tool_allowed(
    tool_name: str | None,
    policy: dict[str, Any] | None,
) -> None:
    normalized = _normalize_agent_tool_name(tool_name)
    if isinstance(policy, dict) and policy.get("scope") == "project":
        if normalized in _PROJECT_SESSION_BLOCKED_EPISODE_FLOW_TOOLS:
            raise ValueError(_PROJECT_SESSION_EPISODE_FLOW_REJECTION)
        return
    if not _episode_session_policy_enabled(policy):
        return
    if normalized in _EPISODE_SESSION_BLOCKED_PROJECT_FLOW_TOOLS:
        raise ValueError(_EPISODE_SESSION_PROJECT_FLOW_REJECTION)
    if normalized in _EPISODE_SESSION_BLOCKED_PROJECT_DELETE_TOOLS:
        raise ValueError(_EPISODE_SESSION_PROJECT_DELETE_REJECTION)


def filter_tools_for_agent_session_policy(
    tools: list[str],
    policy: dict[str, Any] | None,
) -> list[str]:
    if isinstance(policy, dict) and policy.get("scope") == "project":
        return [tool for tool in tools
                if _normalize_agent_tool_name(tool) not in _PROJECT_SESSION_BLOCKED_EPISODE_FLOW_TOOLS]
    if not _episode_session_policy_enabled(policy):
        return tools
    # Keep planning deletion available so episode sessions can clear the current canvas;
    # validate_project_planning_delete_for_session enforces the payload boundary.
    return [
        tool
        for tool in tools
        if _normalize_agent_tool_name(tool) not in _EPISODE_SESSION_BLOCKED_TOOLS
    ]


def _planning_targets_from_payload(payload: dict[str, Any]) -> set[str]:
    value = payload.get("targets")
    if value is None:
        value = payload.get("target")
    if value in (None, ""):
        episode_ids = payload.get("episodeIds") or payload.get("episode_ids") or payload.get("episodeId") or payload.get("episode_id")
        return set(_EPISODE_PLANNING_DEFAULT_TARGETS if episode_ids else _ALL_PLANNING_TARGETS)
    rows = value if isinstance(value, list) else [value]
    aliases = {
        "source": "source_splits",
        "sources": "source_splits",
        "source_split": "source_splits",
        "source_splits": "source_splits",
        "episode": "source_splits",
        "episodes": "source_splits",
        "episode_boundary": "source_splits",
        "episode_boundaries": "source_splits",
        "分集": "source_splits",
        "原文": "source_splits",
        "asset_range": "asset_ranges",
        "asset_ranges": "asset_ranges",
        "资产范围": "asset_ranges",
        "资产拆分": "asset_ranges",
        "storyboard": "storyboards",
        "storyboards": "storyboards",
        "shot_plan": "storyboards",
        "shot_plans": "storyboards",
        "workflow": "storyboards",
        "workflows": "storyboards",
        "分镜": "storyboards",
        "故事版": "storyboards",
        "画布": "storyboards",
        "source_index": "source_index",
        "index": "source_index",
        "索引": "source_index",
        "all": "all",
        "*": "all",
        "全部": "all",
        "所有": "all",
    }
    selected: set[str] = set()
    for item in rows:
        key = str(item or "").strip()
        if not key:
            continue
        normalized = aliases.get(key) or aliases.get(key.casefold())
        if normalized == "all":
            return set(_ALL_PLANNING_TARGETS)
        if normalized:
            selected.add(normalized)
    return selected or set(_ALL_PLANNING_TARGETS)


def _planning_episode_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("episodeIds") or payload.get("episode_ids") or payload.get("episodeId") or payload.get("episode_id")
    rows = raw if isinstance(raw, list) else [raw] if raw else []
    result: list[str] = []
    for item in rows:
        episode_id = _policy_safe_episode_id(item)
        if episode_id and episode_id not in result:
            result.append(episode_id)
    return result


def validate_project_planning_delete_for_session(
    project_id: str,
    payload: dict[str, Any] | None,
    policy: dict[str, Any] | None,
) -> None:
    if not isinstance(policy, dict):
        return
    payload = payload if isinstance(payload, dict) else {}
    targets = _planning_targets_from_payload(payload)
    episode_ids = _planning_episode_ids_from_payload(payload)
    current_episode = _policy_safe_episode_id(policy.get("currentEpisodeId"))
    latest_episode = _policy_safe_episode_id(policy.get("latestEpisodeId") or latest_project_episode_id(project_id))
    if policy.get("scope") == "project":
        if "source_splits" in targets:
            if not episode_ids:
                raise ValueError(f"项目会话删除分集必须指定最新一集（最新为 {latest_episode or '未知'}），不能一次清空全部分集。")
            if len(episode_ids) != 1 or episode_ids[0] != latest_episode:
                raise ValueError(f"项目会话删除分集必须从最新集开始（最新为 {latest_episode or '未知'}），不能从中间删除。")
        if "storyboards" in targets and not episode_ids:
            raise ValueError("项目会话清空画布必须指定分集，避免一次清空全部分集画布。")
        return
    if policy.get("scope") != "episode":
        return
    if not episode_ids:
        raise ValueError("当前集会话不能清空全部项目规划，只能清理当前集画布。")
    if len(episode_ids) != 1 or episode_ids[0] != current_episode:
        raise ValueError(f"当前集会话只能操作当前集（{current_episode}），不能清理其他分集。")
    disallowed_global_targets = targets & {"source_index", "asset_ranges"}
    if disallowed_global_targets:
        raise ValueError("当前集会话不能清理全局索引或资产拆分范围。")
    if "source_splits" in targets and current_episode != latest_episode:
        raise ValueError(f"当前集不是最新一集（最新为 {latest_episode or '未知'}），当前集会话不能删除本集原文和画布。")


def validate_agent_tool_episode_scope(
    tool_name: str,
    selected_episode_id: str,
    policy: dict[str, Any] | None,
) -> None:
    if not _episode_session_policy_enabled(policy):
        return
    validate_agent_session_tool_allowed(tool_name, policy)
    validate_agent_session_episode_target(selected_episode_id, policy)


def validate_agent_session_episode_target(
    selected_episode_id: str | None,
    policy: dict[str, Any] | None,
) -> None:
    if not _episode_session_policy_enabled(policy):
        return
    try:
        current_episode = _policy_safe_episode_id(policy.get("currentEpisodeId"))
        selected_episode = _policy_safe_episode_id(selected_episode_id)
    except ValueError as exc:
        raise AgentSessionPolicyError(str(exc)) from exc
    if selected_episode and current_episode and selected_episode != current_episode:
        raise AgentSessionPolicyError(f"当前集会话只能操作当前集（{current_episode}），不能跨集操作 {selected_episode}。")
