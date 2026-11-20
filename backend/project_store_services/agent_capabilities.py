# -*- coding: utf-8 -*-
"""按会话范围与当前项目阶段公开智能体可用技能。"""
from __future__ import annotations
from typing import Any
from .catalogs import AGENT_OPS_DIR, AGENT_OPS_SKILLS_DIR

from .agent_action_contract import (
    _agent_action_description,
    _agent_action_icon,
    _agent_action_label,
    _agent_action_order_for_session_policy,
    _agent_action_prompt,
    _agent_is_background_action,
    _agent_program_direct_actions,
    _agent_quick_prompts_for_session_policy,
    _agent_task_catalog_for_session_policy,
)
from .agent_conversation_context import (
    _agent_turn_context_scope,
)
from .agent_progress_recommendations import (
    _agent_progress_state,
)
from .agent_session_policy import (
    build_agent_session_policy,
)

def _agent_skill_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    meta: dict[str, str] = {}
    for line in text[3:end].splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        normalized_key = key.strip()
        if not normalized_key:
            continue
        meta[normalized_key] = value.strip().strip("\"'")
    return meta


def list_agent_skills(
    project_id: str | None = None,
    episode_id: str | None = None,
    *,
    scope: str | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {}
    if project_id:
        try:
            context_scope = _agent_turn_context_scope(scope, episode_id)
            progress_episode_id = None if context_scope == "project" else episode_id
            state = _agent_progress_state(
                project_id,
                progress_episode_id,
                detail_mode=context_scope == "episode",
            )
        except Exception:
            state = {}
    else:
        context_scope = _agent_turn_context_scope(scope, episode_id)
        progress_episode_id = None if context_scope == "project" else episode_id
    selected_episode_id = str(state.get("selectedEpisodeId") or progress_episode_id or episode_id or "E01")
    session_policy = (
        build_agent_session_policy(
            str(project_id),
            scope=context_scope,
            episode_id=progress_episode_id,
            selected_episode_id=selected_episode_id,
        )
        if project_id
        else None
    )
    skills: list[dict[str, Any]] = []
    if AGENT_OPS_SKILLS_DIR.is_dir():
        for skill_file in sorted(AGENT_OPS_SKILLS_DIR.glob("*/SKILL.md")):
            try:
                text = skill_file.read_text(encoding="utf-8")
            except Exception:
                continue
            meta = _agent_skill_frontmatter(text)
            name = str(meta.get("name") or skill_file.parent.name).strip()
            if not name:
                continue
            skills.append(
                {
                    "name": name,
                    "label": name.replace("-", " "),
                    "description": str(meta.get("description") or "").strip(),
                    "prompt": "继续",
                    "icon": "clapperboard",
                    "source": "agent_ops_skill",
                    "path": str(skill_file.relative_to(AGENT_OPS_DIR)).replace("\\", "/"),
                }
            )
    commands = [
        {
            "id": action,
            "name": action,
            "label": _agent_action_label(action, state),
            "description": _agent_action_description(action, state),
            "prompt": _agent_action_prompt(action, state),
            "background": _agent_is_background_action(action),
            "icon": _agent_action_icon(action),
            "source": "agent_action",
            "execution": "program" if action in _agent_program_direct_actions() else "agent",
        }
        for action in _agent_action_order_for_session_policy(session_policy)
    ]
    return {
        "success": True,
        "skills": skills,
        "commands": commands,
        "quickPrompts": _agent_quick_prompts_for_session_policy(state, session_policy),
        "taskCatalog": _agent_task_catalog_for_session_policy(session_policy),
        "runtimeProfile": {
            "resourceRoot": "plugins/ai-video/backend/agent_ops",
            "transport": "callBackend/onBackendEvent",
        },
    }
