# -*- coding: utf-8 -*-
"""智能体提示词所需的来源、资产、工作流与可编辑上下文。"""
from __future__ import annotations
from .canvas_ownership import VIDEO_TASK_NODE_TYPES

import copy as copy
import json as json
import re as re
from .agent_action_contract import (
    _agent_action_description,
    _agent_action_label,
    _agent_action_order_for_session_policy,
    _agent_is_background_action,
    _agent_program_direct_actions,
)
from .agent_asset_range_state import (
    _agent_source_coverage_safe,
)
from .agent_context_runtime import (
    _agent_context_budget_for_task,
    _agent_episode_number,
)
from .agent_contracts import (
    _agent_task_pending_action,
    agent_target_for_scope as _agent_active_target_for_scope,
)
from .agent_conversation_context import (
    _agent_conversation_context_for_prompt,
)
from .agent_model_runtime import (
    _agent_configured_model_summary,
)
from .agent_pending_operations import (
    _agent_pending_operation_context,
)
from .agent_production_scope import (
    _agent_current_route_identity,
    _agent_generation_flow_step_hypothesis,
)
from .agent_progress_recommendations import (
    _agent_default_production_flow_step,
    _agent_production_actions,
    _agent_recommended_action,
    _agent_recommended_next_step,
    _agent_stage_next_step_label,
)
from .agent_sessions import (
    _project_dir,
)
from .assets import (
    _asset_design_prompt_from_asset,
    _asset_store_path,
)
from .catalogs import (
    DEFAULT_ASSETS,
    DEFAULT_ASSET_EXTRACTION_TARGET_UNITS,
    DEFAULT_EPISODE_TARGET_UNITS,
    _ensure_prompt_sentence_end,
)
from .project_management import (
    get_effective_config,
)
from .projects import (
    _first_text,
)
from .source_index import read_source_window
from .source_text_store import _compact_text, _project_source_text
from .store_core import (
    ASSET_LIFECYCLE_ACTIVE,
    _filter_asset_store_by_lifecycle,
    _read_json,
)
from .workflow_projection import (
    get_canvas_workflow_projection,
)
from utils.agent_context import (
    AGENT_CONTEXT_RECENT_WINDOW,
)
from utils.text_metrics import (
    content_char_count,
)

from typing import Any


def _agent_compact_source_text(text: str, *, max_chars: int = 6000) -> str:
    """Lossy source excerpt for generic agent context windows.

    The returned text is not complete source material. Do not persist it as
    canonical source/prompt data or send it as a provider API payload.
    Generation paths that require full evidence must use dedicated source
    windows/full fields and block when complete context is unavailable.
    """
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max_chars - 200]}\n...\n{cleaned[-180:]}"


def _agent_source_window_context(
    project_id: str,
    *,
    offset: int = 0,
    length: int = 4000,
    strategy: str,
    max_chars: int = 6000,
) -> dict[str, Any]:
    try:
        window = read_source_window(project_id, offset=offset, length=length)
    except Exception as exc:
        return {"available": False, "strategy": strategy, "error": str(exc)}
    text = str(window.get("text") or "")
    return {
        "available": True,
        "strategy": strategy,
        "sourceId": window.get("sourceId"),
        "sourceTitle": window.get("sourceTitle"),
        "absoluteStart": window.get("absoluteStart"),
        "absoluteEnd": window.get("absoluteEnd"),
        "length": window.get("length"),
        "totalChars": window.get("totalChars"),
        "hasBefore": window.get("hasBefore"),
        "hasAfter": window.get("hasAfter"),
        "excerpt": _agent_compact_source_text(text, max_chars=max(600, int(max_chars or 6000))),
    }


def _agent_episode_source_context(
    project_id: str,
    episode_id: str,
    *,
    strategy: str,
    max_chars: int = 6000,
) -> dict[str, Any]:
    source_path = _project_dir(project_id) / "episodes" / episode_id / "source.txt"
    source_ref_path = _project_dir(project_id) / "episodes" / episode_id / "source_ref.json"
    if not source_path.is_file():
        return {"available": False, "strategy": strategy, "episodeId": episode_id, "error": "episode source not found"}
    try:
        text = source_path.read_text(encoding="utf-8")
    except Exception as exc:
        return {"available": False, "strategy": strategy, "episodeId": episode_id, "error": str(exc)}
    source_ref = _read_json(source_ref_path, {}) if source_ref_path.is_file() else {}
    return {
        "available": True,
        "strategy": strategy,
        "episodeId": episode_id,
        "sourceId": source_ref.get("sourceId") if isinstance(source_ref, dict) else "",
        "absoluteStart": source_ref.get("absoluteStart") if isinstance(source_ref, dict) else None,
        "absoluteEnd": source_ref.get("absoluteEnd") if isinstance(source_ref, dict) else None,
        "charCount": content_char_count(text),
        "textHash": source_ref.get("textHash") if isinstance(source_ref, dict) else "",
        "excerpt": _agent_compact_source_text(text, max_chars=max(600, int(max_chars or 6000))),
    }


def _agent_source_context_for_prompt(
    project_id: str,
    state: dict[str, Any] | None = None,
    task_hypothesis: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_type = str((task_hypothesis or {}).get("taskType") or "").strip()
    episode_id = str((state or {}).get("selectedEpisodeId") or "E01").strip() or "E01"
    coverage = _agent_source_coverage_safe(project_id)
    budget = budget or _agent_context_budget_for_task(task_hypothesis)
    source_max_chars = int(budget.get("sourceTextMaxChars") or 4200)
    if task_type in {
        "work_chain_plan_discuss",
        "work_chain_plan_save",
        "shot_prompt_patch",
        "workflow_node_content_update",
        "workflow_node_update",
        "workflow_update",
    }:
        episode_context = _agent_episode_source_context(
            project_id,
            episode_id,
            strategy="episode_source",
            max_chars=source_max_chars,
        )
        if episode_context.get("available"):
            return episode_context
    if task_type in {"asset_range_propose", "asset_range_commit"}:
        cursor = coverage.get("assetCursor") if isinstance(coverage.get("assetCursor"), dict) else {}
        offset = int(cursor.get("nextOffset") or 0)
        length = int(cursor.get("targetUnits") or DEFAULT_ASSET_EXTRACTION_TARGET_UNITS)
        window_length = min(max(length, 1600), max(2200, source_max_chars + 1200))
        return _agent_source_window_context(
            project_id,
            offset=offset,
            length=window_length,
            strategy="asset_cursor_window",
            max_chars=source_max_chars,
        )
    if task_type == "episode_boundary_propose":
        cursor = coverage.get("episodeCursor") if isinstance(coverage.get("episodeCursor"), dict) else {}
        offset = int(cursor.get("nextOffset") or 0)
        length = int(cursor.get("targetUnits") or DEFAULT_EPISODE_TARGET_UNITS)
        window_length = min(max(length * 2, 1600), max(2200, source_max_chars + 1200))
        return _agent_source_window_context(
            project_id,
            offset=offset,
            length=window_length,
            strategy="episode_cursor_window",
            max_chars=source_max_chars,
        )
    try:
        title, text, word_count = _project_source_text(project_id)
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) > source_max_chars:
        head_chars = max(400, int(source_max_chars * 0.72))
        tail_chars = max(160, source_max_chars - head_chars - 8)
        excerpt = f"{cleaned[:head_chars]}\n...\n{cleaned[-tail_chars:]}"
    else:
        excerpt = cleaned
    return {
        "available": True,
        "strategy": "global_head_tail_excerpt",
        "title": title,
        "wordCount": word_count,
        "excerpt": excerpt,
    }


def _agent_overview_context_for_prompt(state: dict[str, Any]) -> dict[str, Any]:
    meta = state.get("meta") if isinstance(state.get("meta"), dict) else {}
    overview = meta.get("overview_analysis") if isinstance(meta.get("overview_analysis"), dict) else {}
    result = overview.get("result") if isinstance(overview.get("result"), dict) else {}
    excerpt_summary = _first_text(result.get("excerpt_summary") or result.get("excerptSummary"))
    genre_context = _first_text(result.get("genre_context") or result.get("genreContext"))
    return {
        "excerptSummary": _compact_text(_ensure_prompt_sentence_end(excerpt_summary), 800),
        "genreContext": _compact_text(genre_context, 160),
        "themeVisualContext": _compact_text(
            str(result.get("theme_visual_context") or result.get("themeVisualContext") or ""),
            120,
        ),
    }


def _agent_cursor_facts(cursor: Any) -> dict[str, Any]:
    if not isinstance(cursor, dict):
        return {}
    return {
        "nextOffset": cursor.get("nextOffset"),
        "targetUnits": cursor.get("targetUnits"),
        "lastEpisodeId": cursor.get("lastEpisodeId"),
        "lastRangeId": cursor.get("lastRangeId"),
    }


def _agent_project_facts_for_prompt(
    project_id: str,
    state: dict[str, Any],
    *,
    pending_operation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    coverage = _agent_source_coverage_safe(project_id)
    selected_episode_id = str(state.get("selectedEpisodeId") or "E01").strip() or "E01"
    source_ref_path = _project_dir(project_id) / "episodes" / selected_episode_id / "source_ref.json"
    source_ref = _read_json(source_ref_path, {}) if source_ref_path.is_file() else {}
    production_status = state.get("productionStatus") if isinstance(state.get("productionStatus"), dict) else {}
    default_flow_active = str(state.get("stage") or "").strip() == "production"
    if default_flow_active:
        default_flow_step = _agent_default_production_flow_step(state)
        default_route_identity = _agent_current_route_identity(state)
    else:
        default_flow_step = {}
        default_route_identity = {}
    return {
        "stage": state.get("stage"),
        "selectedEpisode": {
            "id": selected_episode_id,
            "title": state.get("selectedEpisodeTitle"),
            "status": state.get("selectedEpisodeStatus"),
            "hasSourceRef": bool(source_ref),
            "sourceRange": {
                "sourceId": source_ref.get("sourceId") if isinstance(source_ref, dict) else "",
                "absoluteStart": source_ref.get("absoluteStart") if isinstance(source_ref, dict) else None,
                "absoluteEnd": source_ref.get("absoluteEnd") if isinstance(source_ref, dict) else None,
                "charCount": source_ref.get("charCount") if isinstance(source_ref, dict) else None,
            },
        },
        "assetCounts": {
            "characters": int(state.get("characterCount") or 0),
            "creatures": int(state.get("creatureCount") or 0),
            "scenes": int(state.get("sceneCount") or 0),
            "props": int(state.get("propCount") or 0),
        },
        "readiness": {
            "sourceReady": bool(state.get("sourceReady")),
            "overviewReady": bool(state.get("overviewReady")),
            "episodeBoundaryReady": bool(state.get("episodeBoundaryReady")),
            "episodeWorkflowReady": bool(state.get("episodeWorkflowReady")),
            "episodeScriptReady": bool(state.get("episodeScriptReady")),
        },
        "productionStatus": {
            "currentState": production_status.get("currentState"),
            "nextAction": production_status.get("nextAction"),
            "currentRouteId": production_status.get("currentRouteId"),
            "currentWorkChainId": production_status.get("currentWorkChainId"),
            "currentSegmentId": production_status.get("currentSegmentId"),
            "overallStatus": production_status.get("overallStatus"),
            "progress": copy.deepcopy(production_status.get("progress") or {}),
        },
        "defaultProductionFlow": {
            "active": default_flow_active,
            "currentState": default_flow_step.get("stateId"),
            "currentLabel": default_flow_step.get("label"),
            "taskType": default_flow_step.get("taskType"),
            "currentRouteId": (
                default_route_identity.get("routeId") or production_status.get("currentRouteId")
            ) if default_flow_active else None,
            "currentWorkChainId": (
                default_route_identity.get("workChainId") or production_status.get("currentWorkChainId")
            ) if default_flow_active else None,
            "currentSegmentId": (
                default_route_identity.get("segmentId") or production_status.get("currentSegmentId")
            ) if default_flow_active else None,
            "availableActions": _agent_production_actions(state) if default_flow_active else [],
        },
        "sourceCoverage": {
            "sourceId": coverage.get("sourceId"),
            "episodeCursor": _agent_cursor_facts(coverage.get("episodeCursor")),
            "assetCursor": _agent_cursor_facts(coverage.get("assetCursor")),
            "episodeRangeCount": len(coverage.get("episodeRanges") or []),
            "assetRangeCount": len(coverage.get("assetRanges") or []),
        },
        "pendingOperation": {
            "active": bool((pending_operation or {}).get("active")),
            "operationType": str((pending_operation or {}).get("operationType") or ""),
            "expectedNextTool": str((pending_operation or {}).get("expectedNextTool") or ""),
        },
    }


def _agent_creative_memory_for_prompt(
    project_id: str,
    state: dict[str, Any],
    session_id: str | None,
    *,
    budget: dict[str, Any],
) -> dict[str, Any]:
    meta = state.get("meta") if isinstance(state.get("meta"), dict) else {}
    try:
        config = get_effective_config(project_id)
    except Exception:
        config = {}
    style_config = config.get("style") if isinstance(config.get("style"), dict) else {}
    style_prompt = _agent_visual_style_prompt_for_model(style_config.get("prompt") or meta.get("style_prompt"))
    return {
        "stylePrompt": _compact_text(style_prompt, 500),
        "stableInstruction": "用户反馈、风格约束及本轮提供的制作连续性要求要落实进保存的资产、分集、分镜或提示词，不要只在回复里提到。",
    }


def _agent_first_mapping_value(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping.get(key) not in (None, "", [], {}):
            return mapping.get(key)
    return None


def _agent_compact_any(value: Any, max_chars: int = 600) -> Any:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        return _compact_text(value, max_chars)
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for key, item in value.items():
            compact_item = _agent_compact_any(item, max(120, max_chars // 2))
            if compact_item not in (None, "", [], {}):
                compacted[str(key)] = compact_item
        return compacted or None
    if isinstance(value, list):
        rows = []
        for item in value[:8]:
            compact_item = _agent_compact_any(item, max(120, max_chars // 2))
            if compact_item not in (None, "", [], {}):
                rows.append(compact_item)
        return rows or None
    return value


def _agent_visual_style_prompt_for_model(value: Any) -> str:
    prompt = str(value or "").replace("@", "").replace("＠", "").strip()
    if not prompt:
        return ""
    prompt = re.sub(r"^\s*(?:画风|风格|视觉风格)\s*[:：]\s*", "", prompt)
    if not prompt:
        return ""
    return f"视觉风格：{prompt}"


def _agent_nearby_episode_memory(state: dict[str, Any], selected_episode_id: str) -> dict[str, Any]:
    meta = state.get("meta") if isinstance(state.get("meta"), dict) else {}
    episodes = [item for item in meta.get("episodes", []) if isinstance(item, dict)]
    if not episodes:
        return {}
    selected_number = _agent_episode_number(selected_episode_id)
    selected = next((item for item in episodes if str(item.get("id") or "") == selected_episode_id), None)
    previous_rows = [
        item
        for item in sorted(episodes, key=lambda row: _agent_episode_number(str(row.get("id") or "")))
        if _agent_episode_number(str(item.get("id") or "")) < selected_number
    ][-2:]

    def _row(item: dict[str, Any]) -> dict[str, Any]:
        source_ref = item.get("sourceRef") if isinstance(item.get("sourceRef"), dict) else {}
        return {
            "id": str(item.get("id") or ""),
            "title": _compact_text(str(item.get("title") or ""), 120),
            "status": _compact_text(str(item.get("status") or ""), 160),
            "sourceRange": {
                "absoluteStart": source_ref.get("absoluteStart"),
                "absoluteEnd": source_ref.get("absoluteEnd"),
                "charCount": source_ref.get("charCount") or item.get("wordCount"),
            },
        }

    result: dict[str, Any] = {}
    if selected:
        result["selected"] = _row(selected)
    if previous_rows:
        result["previous"] = [_row(item) for item in previous_rows]
    return result


def _agent_work_chain_plan_continuity_memory(project_id: str, episode_id: str, max_rows: int = 8) -> dict[str, Any]:
    def _first_non_empty(*values: Any) -> Any:
        for value in values:
            if value not in (None, "", [], {}):
                return value
        return None

    def _row_from_plan_item(item: dict[str, Any], parent: dict[str, Any] | None = None) -> dict[str, Any]:
        parent = parent if isinstance(parent, dict) else {}
        parent_data = parent.get("data") if isinstance(parent.get("data"), dict) else {}
        continuity = _first_non_empty(
            item.get("continuityAnchor"),
            item.get("continuity"),
            item.get("stateContinuity"),
            item.get("visualContinuity"),
            item.get("continuity_anchor"),
        )
        row = {
            "id": str(_first_non_empty(item.get("id"), parent.get("id")) or ""),
            "nodeType": str(parent.get("type") or ""),
            "segmentId": str(
                _first_non_empty(
                    item.get("segmentId"),
                    item.get("segment_id"),
                    parent.get("segmentId"),
                    parent_data.get("segmentId"),
                    parent_data.get("segment_id"),
                )
                or ""
            ),
            "workChainId": str(_first_non_empty(parent.get("workChainId"), parent_data.get("workChainId")) or ""),
            "routeId": str(_first_non_empty(parent.get("routeId"), parent_data.get("routeId")) or ""),
            "title": _compact_text(str(_first_non_empty(item.get("title"), parent_data.get("title"), parent.get("title")) or ""), 120),
            "assetRefs": _agent_compact_any(
                _first_non_empty(item.get("assetRefs"), item.get("asset_refs"), parent_data.get("assetRefs")),
                360,
            ),
            "startState": _agent_compact_any(_first_non_empty(item.get("startState"), item.get("start_state")), 360),
            "endState": _agent_compact_any(_first_non_empty(item.get("endState"), item.get("end_state")), 360),
            "referencePlan": _agent_compact_any(
                _first_non_empty(item.get("referencePlan"), item.get("reference_plan"), parent_data.get("referencePlan")),
                360,
            ),
            "continuityAnchor": _compact_text(str(continuity or ""), 220),
        }
        return {key: value for key, value in row.items() if value not in (None, "", [], {})}

    rows: list[dict[str, Any]] = []
    seen_row_keys: set[tuple[str, str]] = set()

    def _append_row(row: dict[str, Any]) -> None:
        if not row:
            return
        row_key = (
            str(row.get("id") or "").strip(),
            str(row.get("segmentId") or "").strip(),
        )
        if str(row.get("nodeType") or "").strip() in {
            "script.creation",
            "prompt.storyboard",
            "director.board",
        } and row_key[1]:
            row_key = ("workflow-card-segment", row_key[1])
        if not row_key[0] and not row_key[1]:
            row_key = (
                str(row.get("nodeType") or "").strip(),
                str(row.get("title") or "").strip(),
            )
        if row_key in seen_row_keys:
            return
        seen_row_keys.add(row_key)
        rows.append(row)

    workflow_nodes: list[dict[str, Any]] = []
    try:
        workflow = get_canvas_workflow_projection(project_id, episode_id, {"detail": "full"})
        workflow_nodes = [
            item
            for item in workflow.get("nodes", [])
            if isinstance(item, dict)
            and str(item.get("type") or "").strip()
            in {"prompt.storyboard", "director.board"}
        ]
    except Exception:
        workflow_nodes = []
    for node in workflow_nodes:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        nested_items: list[dict[str, Any]] = []
        for key in ("shots", "panels", "segments"):
            value = data.get(key)
            if isinstance(value, list):
                nested_items.extend([item for item in value if isinstance(item, dict)])
        if nested_items:
            for item in nested_items:
                row = _row_from_plan_item(item, node)
                _append_row(row)
                if len(rows) >= max_rows:
                    break
        else:
            row = _row_from_plan_item(data, node)
            _append_row(row)
        if len(rows) >= max_rows:
            break
    if rows:
        return {
            "episodeId": episode_id,
            "source": "workflowCards",
            "cardCount": len(workflow_nodes),
            "sampledShots": rows[:max_rows],
        }

    path = _project_dir(project_id) / "episodes" / episode_id / "work_chain_plan.json"
    if not path.is_file():
        return {}
    work_chain_plan = _read_json(path, {})
    if not isinstance(work_chain_plan, dict):
        return {}
    for item in work_chain_plan.get("shots") if isinstance(work_chain_plan.get("shots"), list) else []:
        if not isinstance(item, dict):
            continue
        row = _row_from_plan_item(item)
        _append_row(row)
        if len(rows) >= max_rows:
            break
    if not rows:
        return {}
    return {
        "episodeId": episode_id,
        "source": "workChainPlan",
        "shotCount": len(work_chain_plan.get("shots") or []),
        "sampledShots": rows,
    }


def _agent_ai_content_disclosure_memory(config: dict[str, Any]) -> dict[str, Any]:
    production = config.get("production") if isinstance(config.get("production"), dict) else {}
    disclosure = (
        production.get("aiContentDisclosure")
        if isinstance(production.get("aiContentDisclosure"), dict)
        else config.get("aiContentDisclosure")
        if isinstance(config.get("aiContentDisclosure"), dict)
        else {}
    )
    enabled = disclosure.get("enabled")
    if enabled is None:
        enabled = True
    visible_label = str(disclosure.get("visibleLabel") or "本视频含 AI 生成内容").strip()
    metadata_label = str(disclosure.get("metadataLabel") or "AI-generated").strip()
    return {
        "enabled": bool(enabled),
        "visibleLabel": visible_label,
        "metadataLabel": metadata_label,
        "scope": "生成媒体、项目导出和发布物标识。",
    }


def _agent_production_memory_for_prompt(
    project_id: str,
    state: dict[str, Any],
    *,
    budget: dict[str, Any],
) -> dict[str, Any]:
    meta = state.get("meta") if isinstance(state.get("meta"), dict) else {}
    max_chars = int(budget.get("productionMemoryMaxChars") or 1200)
    try:
        config = get_effective_config(project_id)
    except Exception:
        config = {}
    storyboard_config = config.get("storyboard") if isinstance(config.get("storyboard"), dict) else {}
    visual_bible = (
        _agent_first_mapping_value(config, "visualBible", "visual_bible", "productionBible", "production_bible")
        if isinstance(config, dict)
        else None
    )
    if not isinstance(visual_bible, dict):
        visual_bible = _agent_first_mapping_value(meta, "visualBible", "visual_bible", "productionBible", "production_bible")
    if not isinstance(visual_bible, dict):
        visual_bible = {}
    selected_episode_id = str(state.get("selectedEpisodeId") or "E01").strip() or "E01"
    work_chain_plan_memory = _agent_work_chain_plan_continuity_memory(project_id, selected_episode_id)
    result = {
        "policy": "video_production_context_only",
        "visualBible": {
            "aspectRatio": config.get("aspect_ratio") if isinstance(config, dict) else "",
            "panelCount": storyboard_config.get("panel_count"),
            "constraints": _agent_compact_any(visual_bible, max(320, max_chars // 2)),
        },
        "continuity": {
            "episodes": _agent_nearby_episode_memory(state, selected_episode_id),
            "workChainPlan": work_chain_plan_memory,
            "requiredFields": [
                "sourceRefs",
                "assetRefs",
                "startState",
                "endState",
                "camera",
                "referencePlan",
                "generationStrategy",
            ],
        },
        "generationTrace": {
            "preserveReferencePlan": True,
            "recordModelPromptAndReferenceMedia": True,
            "aiContentDisclosure": _agent_ai_content_disclosure_memory(config if isinstance(config, dict) else {}),
        },
        "qualityGates": [
            "分镜必须能追溯到当前集 sourceRefs，不能脱离原文事实。",
            "角色、生物、场景、道具优先引用已有 assetRefs，避免重复造资产。",
            "镜头之间要维护服装、道具、伤势、情绪、光线和空间方向连续性。",
            "生成图/视频时优先使用 referencePlan 和资产参考图保持一致性。",
        ],
    }
    return _agent_compact_any(result, max_chars) or {}


_AGENT_EDITABLE_ASSET_TYPES = (
    ("characters", "角色"),
    ("creatures", "生物"),
    ("scenes", "场景"),
    ("props", "道具"),
)


def _agent_asset_fact_row(asset_type: str, item: dict[str, Any]) -> dict[str, Any]:
    """Only editable business facts, without media blobs, versions or runtime metadata."""
    result = {"id": str(item.get("id") or ""), "assetType": asset_type, "name": str(item.get("name") or "")}
    for key in ("desc", "voiceStyle", "canSpeak", "sourceRefs", "sourceEvidence", "designRationale", "tag"):
        if key in item:
            result[key] = copy.deepcopy(item[key])
    prompts = item.get("prompts") if isinstance(item.get("prompts"), dict) else {}
    if "assetImagePrompt" in prompts:
        result["prompts"] = {"assetImagePrompt": copy.deepcopy(prompts["assetImagePrompt"])}
    return result


def _agent_select_fact_fields(row: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    if not fields:
        return row
    result = {key: row[key] for key in ("id", "assetType", "name") if key in row}
    for field in fields:
        parts = str(field).split(".")
        source: Any = row
        for part in parts:
            if not isinstance(source, dict) or part not in source:
                break
            source = source[part]
        else:
            target = result
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = copy.deepcopy(source)
    return result


def _agent_project_snapshot_payload(
    project_id: str,
    state: dict[str, Any],
    session_id: str | None,
    *,
    domains: list[str] | None = None,
    asset_ids: list[str] | None = None,
    fields: list[str] | None = None,
    session_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """On-demand facts only; never replay a turn's instructions or conversation."""
    selected = set(domains or (["assets"] if asset_ids else ["project", "overview"]))
    unknown = selected - {"project", "overview", "assets", "settings", "workflow", "source", "pending"}
    if unknown:
        raise ValueError("不支持的项目快照范围：" + ", ".join(sorted(unknown)))
    result: dict[str, Any] = {"projectId": project_id}
    if "project" in selected:
        next_step = _agent_recommended_next_step(state)
        result["projectProgress"] = {
            "projectId": project_id,
            "projectName": state.get("projectName"),
            "stage": state.get("stage"),
            "projectScope": bool(state.get("projectScope")),
            "configuredAgentModel": _agent_configured_model_summary(project_id),
            "nextAction": next_step.get("id") or _agent_recommended_action(state),
            "nextActionLabel": next_step.get("label") or _agent_stage_next_step_label(state),
        }
        result["projectFacts"] = _agent_project_facts_for_prompt(project_id, state)
        result["projectFacts"].pop("pendingOperation", None)
        # Action identifiers are capabilities, not another copy of task instructions.
        result["availableActions"] = [
            {"action": action, "label": _agent_action_label(action, state)}
            for action in _agent_action_order_for_session_policy(session_policy)
        ]
    if "overview" in selected:
        result["overview"] = _agent_overview_context_for_prompt(state)
    if "assets" in selected:
        assets = _read_json(_asset_store_path("project", project_id), DEFAULT_ASSETS)
        assets = _filter_asset_store_by_lifecycle(assets if isinstance(assets, dict) else {}, ASSET_LIFECYCLE_ACTIVE)
        wanted = set(asset_ids or [])
        rows = []
        for asset_type, _label in _AGENT_EDITABLE_ASSET_TYPES:
            for item in assets.get(asset_type, []):
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                if wanted and str(item["id"]) not in wanted:
                    continue
                fact = _agent_asset_fact_row(asset_type, item)
                # Without IDs, expose a complete lightweight index for discovery.
                rows.append(_agent_select_fact_fields(fact, fields or (None if wanted else ["id", "assetType", "name"])))
        result["assets"] = {"items": rows, "count": len(rows), "detail": "selected" if wanted else "index"}
        for key in ("revision", "updatedAt"):
            if key in assets:
                result["assets"][key] = copy.deepcopy(assets[key])
        if wanted:
            result["assets"]["missingIds"] = sorted(wanted - {row["id"] for row in rows})
    if "settings" in selected:
        settings = _agent_editable_settings_for_prompt(project_id, state, [])
        result["settings"] = {
            row["key"]: copy.deepcopy(row.get("currentValue"))
            for row in settings.get("targets", []) if isinstance(row, dict) and row.get("key")
        }
    if "workflow" in selected:
        result["workflow"] = get_canvas_workflow_projection(
            project_id, str(state.get("selectedEpisodeId") or "E01"), {"detail": "full"},
        )
    if "source" in selected:
        result["sourceText"] = _agent_source_context_for_prompt(project_id, state, {}, budget={"sourceTextMaxChars": 1800})
    if "pending" in selected:
        result["pendingOperation"] = _agent_pending_operation_context(project_id, session_id)
    return result






def _agent_tool_allowed_for_prompt(allowed_tools: list[str] | tuple[str, ...] | None, tool_name: str) -> bool:
    return f"mcp__ai_video__{tool_name}" in set(allowed_tools or [])


def _agent_compact_value_for_prompt(value: Any, limit: int = 180) -> Any:
    compacted = _agent_compact_any(value, limit)
    return "" if compacted is None else compacted


def _agent_editable_setting_target(
    *,
    key: str,
    label: str,
    current_value: Any,
    write_key: str,
    allowed_tools: list[str] | tuple[str, ...] | None,
    note: str = "",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "targetRef": f"settings:{key}",
        "key": key,
        "label": label,
        "fieldPath": f"settings.{write_key}",
        "updateTool": "update_project_settings",
        "updateToolAllowed": _agent_tool_allowed_for_prompt(allowed_tools, "update_project_settings"),
        "currentValue": copy.deepcopy(current_value),
        "payloadShape": {"settings": {write_key: "<new value>"}},
    }
    if note:
        row["note"] = note
    return row


def _agent_editable_settings_for_prompt(
    project_id: str,
    state: dict[str, Any],
    allowed_tools: list[str] | tuple[str, ...] | None,
) -> dict[str, Any]:
    try:
        config = get_effective_config(project_id)
    except Exception:
        config = {}
    if not isinstance(config, dict):
        config = {}
    style = config.get("style") if isinstance(config.get("style"), dict) else {}
    storyboard = config.get("storyboard") if isinstance(config.get("storyboard"), dict) else {}
    targets = [
        _agent_editable_setting_target(
            key="projectName",
            label="项目标题",
            current_value=state.get("projectName"),
            write_key="name",
            allowed_tools=allowed_tools,
        ),
        _agent_editable_setting_target(
            key="aspectRatio",
            label="项目画幅比例",
            current_value=config.get("aspect_ratio") or config.get("aspectRatio"),
            write_key="aspectRatio",
            allowed_tools=allowed_tools,
        ),
        _agent_editable_setting_target(
            key="sourceLanguage",
            label="项目语言",
            current_value=config.get("source_language") or config.get("sourceLanguage"),
            write_key="sourceLanguage",
            allowed_tools=allowed_tools,
        ),
        _agent_editable_setting_target(
            key="episodeTargetUnits",
            label="默认分集目标字数",
            current_value=config.get("episode_target_units") or config.get("episodeTargetUnits"),
            write_key="episodeTargetUnits",
            allowed_tools=allowed_tools,
            note="分集断点按项目设置的目标字数规划；只有用户明确要求修改项目默认配置时才写入。",
        ),
        _agent_editable_setting_target(
            key="assetExtractionTargetUnits",
            label="默认资产拆分目标字数",
            current_value=config.get("asset_extraction_target_units") or config.get("assetExtractionTargetUnits"),
            write_key="assetExtractionTargetUnits",
            allowed_tools=allowed_tools,
            note="只有用户明确要求修改项目默认配置时写入；本次临时资产范围字数传给 get_asset_range_context.targetUnits。",
        ),
        _agent_editable_setting_target(
            key="styleMode",
            label="项目视觉风格模式",
            current_value=style.get("mode"),
            write_key="styleMode",
            allowed_tools=allowed_tools,
        ),
        _agent_editable_setting_target(
            key="styleTemplateId",
            label="项目视觉模板",
            current_value=config.get("style_template_id") or style.get("template_id"),
            write_key="styleTemplateId",
            allowed_tools=allowed_tools,
        ),
        _agent_editable_setting_target(
            key="stylePrompt",
            label="自定义视觉风格提示词",
            current_value=style.get("prompt"),
            write_key="stylePrompt",
            allowed_tools=allowed_tools,
        ),
        _agent_editable_setting_target(
            key="styleAssetPrompt",
            label="资产通用视觉风格提示词",
            current_value=style.get("asset_prompt") or style.get("assetPrompt"),
            write_key="styleAssetPrompt",
            allowed_tools=allowed_tools,
        ),
        _agent_editable_setting_target(
            key="activePhaseVisualId",
            label="当前使用的阶段视觉 ID",
            current_value=style.get("active_phase_visual_id") or style.get("activePhaseVisualId"),
            write_key="activePhaseVisualId",
            allowed_tools=allowed_tools,
            note="空值表示项目设置中不使用阶段视觉语境。",
        ),
        _agent_editable_setting_target(
            key="phaseVisuals",
            label="阶段视觉列表",
            current_value=style.get("phase_visuals") or style.get("phaseVisuals"),
            write_key="phaseVisuals",
            allowed_tools=allowed_tools,
            note="追加/调整阶段视觉列表时整组写回 phaseVisuals；不要本地自动删除或去重。",
        ),
        _agent_editable_setting_target(
            key="panelCount",
            label="故事板分镜格数量",
            current_value=storyboard.get("panel_count") or storyboard.get("panelCount"),
            write_key="panelCount",
            allowed_tools=allowed_tools,
        ),
        _agent_editable_setting_target(
            key="storyboardRhythmMultiplier",
            label="项目视频节奏倍率",
            current_value=storyboard.get("rhythm_multiplier", 1.0),
            write_key="storyboardRhythmMultiplier",
            allowed_tools=allowed_tools,
            note="1.0～2.0 倍；未单独设置的分镜脚本卡继承此值。",
        ),
        _agent_editable_setting_target(
            key="storyboardClipMaxSeconds",
            label="剧情视频时长上限",
            current_value=storyboard.get("clip_max_seconds", 15),
            write_key="storyboardClipMaxSeconds",
            allowed_tools=allowed_tools,
            note="镜头分组的视频上限，仍需符合所选视频模型的时长档位。",
        ),
    ]
    phase_visuals = style.get("phase_visuals") if isinstance(style.get("phase_visuals"), list) else style.get("phaseVisuals")
    phase_rows: list[dict[str, Any]] = []
    if isinstance(phase_visuals, list):
        for index, item in enumerate(phase_visuals[:12], start=1):
            if not isinstance(item, dict):
                continue
            phase_id = str(item.get("id") or item.get("phaseVisualId") or item.get("phase_visual_id") or "").strip()
            phase_rows.append(
                {
                    "targetRef": f"settings:phaseVisuals:{phase_id or index}",
                    "id": phase_id,
                    "name": _compact_text(str(item.get("name") or item.get("label") or f"阶段视觉 {index}"), 80),
                    "promptPreview": _compact_text(
                        str(
                            item.get("visualPrompt")
                            or item.get("prompt")
                            or item.get("description")
                            or ""
                        ),
                        220,
                    ),
                    "order": index,
                    "updateTool": "update_project_settings",
                    "updateToolAllowed": _agent_tool_allowed_for_prompt(allowed_tools, "update_project_settings"),
                    "editableFields": ["settings.phaseVisuals", "settings.activePhaseVisualId"],
                }
            )
    return {
        "updateTool": "update_project_settings",
        "targets": targets,
        "phaseVisualRows": phase_rows,
    }
