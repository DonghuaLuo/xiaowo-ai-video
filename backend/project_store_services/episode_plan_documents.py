# -*- coding: utf-8 -*-
"""分集计划和世界观文档存储、锁定项保护及规划摘要。"""
from __future__ import annotations

from .agent_text_planning import _agent_text_unit_count
from .asset_reference_scope import _auto_bind_shot_plan_asset_refs
from .asset_reference_scope import _normalize_shot_plan_asset_refs
from .asset_reference_scope import _trusted_context_provenance_for_episode
from .asset_reference_scope import _validate_plan_asset_refs
from .asset_text_contract import _agent_text_row_text
from .canvas_store_queries import get_canvas_context_v4
from .generation_input_context import _generation_user_instruction
from .planning_contract import _is_user_locked_item
from .planning_contract import _payload_document
from .planning_contract import _preserve_locked_plan_document
from .planning_contract import _storyboard_only_shot_plan
from .planning_contract import _workflow_clean_seconds
from .planning_contract import _workflow_shot_timing_plan_duration
from .planning_contract import _workflow_timing_number
from .planning_workflow_inputs import _panels_to_shot_plan
from .project_resource_revisions import _append_resource_revision
from .project_resource_revisions import _assert_resource_write_guard
from .project_resource_revisions import _json_hash
from .project_resource_revisions import _resource_revision_value
from .source_coverage import _load_source_coverage
from .source_reference_scope import _stamp_source_units_on_shot_plan
from .source_reference_scope import _validate_shot_plan_source_refs
from .source_text_store import _compact_text
from .source_text_store import _episode_source_ref_path
from .source_text_store import _read_episode_source_text
from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json
from typing import Any
import copy


def _agent_text_episode_id(row: dict[str, Any], fallback: str) -> str:
    return _agent_text_row_text(row, "episodeId", "episode_id", "id") or fallback


def _workflow_retime_shot_timing_plan(
    value: Any,
    duration_seconds: int | float | None,
) -> dict[str, Any]:
    plan = copy.deepcopy(value) if isinstance(value, dict) else {}
    target_duration = _workflow_timing_number(duration_seconds)
    if not plan or not target_duration or target_duration <= 0:
        return plan
    rows = plan.get("shots") if isinstance(plan.get("shots"), list) else []
    if not rows:
        plan["durationSeconds"] = _workflow_clean_seconds(float(target_duration))
        return plan
    current_duration = _workflow_shot_timing_plan_duration(plan)
    current_duration = _workflow_timing_number(current_duration)
    if not current_duration or current_duration <= 0:
        current_duration = float(len(rows))
    running = 0.0
    next_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        next_row = copy.deepcopy(row)
        row_duration = _workflow_timing_number(
            row.get("durationSeconds")
            or row.get("duration_seconds")
            or row.get("duration")
        )
        if not row_duration:
            start_second = _workflow_timing_number(row.get("startSecond") or row.get("start_second")) or 0
            end_second = _workflow_timing_number(row.get("endSecond") or row.get("end_second")) or 0
            row_duration = max(0.0, float(end_second) - float(start_second))
        if not row_duration:
            row_duration = float(current_duration) / max(1, len(rows))
        start_second = running
        if index == len(rows) - 1:
            end_second = float(target_duration)
        else:
            end_second = running + float(row_duration) / float(current_duration) * float(target_duration)
        end_second = min(float(target_duration), max(start_second, end_second))
        next_row["startSecond"] = _workflow_clean_seconds(start_second)
        next_row["endSecond"] = _workflow_clean_seconds(end_second)
        next_row["durationSeconds"] = _workflow_clean_seconds(end_second - start_second)
        running = end_second
        next_rows.append(next_row)
    plan["durationSeconds"] = _workflow_clean_seconds(float(target_duration))
    plan["shotCount"] = len(next_rows)
    plan["shots"] = next_rows
    return plan


def _save_episode_production_plan_from_panels(
    project_id: str,
    episode_id: str,
    *,
    title: str,
    source_text: str,
    episode_script: str,
    panels: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any] | None:
    panel_rows = [item for item in panels if isinstance(item, dict)]
    if not panel_rows:
        return None
    content_mode = str(config.get("content_mode") or "drama")
    shot_plan = _panels_to_shot_plan(
        episode_id,
        title=title,
        source_text=source_text,
        episode_script=episode_script,
        panels=panel_rows,
        content_mode=content_mode,
    )
    shot_result = save_episode_work_chain_plan(project_id, episode_id, {"workChainPlan": shot_plan})
    from .workflow_planning_lifecycle import build_episode_workflow_from_work_chain_plan
    workflow_result = build_episode_workflow_from_work_chain_plan(
        project_id, episode_id, {"workChainPlan": shot_plan, "source": "system", "reason": "generated_from_panels"},
    )
    return {
        "episodeId": episode_id,
        "workChainPlan": shot_result.get("changedResources") or [],
        "workflow": workflow_result.get("changedResources") or [],
        "segmentCount": len(shot_plan.get("segments") or []),
        "routeCount": workflow_result.get("routeCount") or 0,
    }


def _save_agent_text_episodes(
    project_id: str,
    payload: dict[str, Any],
    *,
    selected_episode_id: str | None = None,
) -> dict[str, Any]:
    from .agent_output_validation import _update_agent_workflow
    from .agent_sessions import _project_meta_path
    from .project_management import get_effective_config
    rows = payload.get("episodes")
    if not isinstance(rows, list):
        return {"changed": False, "episodeCount": 0, "focusEpisodeId": selected_episode_id or ""}
    meta = _read_json(_project_meta_path(project_id), {})
    episodes = meta.get("episodes") if isinstance(meta.get("episodes"), list) else []
    episodes = [copy.deepcopy(item) for item in episodes if isinstance(item, dict)]
    by_id = {str(item.get("id") or ""): index for index, item in enumerate(episodes) if str(item.get("id") or "")}
    config = get_effective_config(project_id)
    default_panel_count = max(1, min(3, int((config.get("storyboard") or {}).get("panel_count") or 3)))
    changed_ids: list[str] = []
    production_results: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        fallback_id = (
            str((episodes[index] or {}).get("id") or "")
            if index < len(episodes) and isinstance(episodes[index], dict)
            else f"E{index + 1:02d}"
        )
        episode_id = _agent_text_episode_id(row, fallback_id)
        if not episode_id:
            continue
        if episode_id in by_id:
            episode = episodes[by_id[episode_id]]
        elif index < len(episodes) and not _agent_text_row_text(row, "episodeId", "episode_id", "id"):
            episode = episodes[index]
            episode_id = str(episode.get("id") or episode_id)
            by_id[episode_id] = index
        else:
            episode = {"id": episode_id}
            by_id[episode_id] = len(episodes)
            episodes.append(episode)
        title = _agent_text_row_text(row, "title", "name") or str(episode.get("title") or episode_id)
        source_text = _agent_text_row_text(row, "sourceText", "source_text", "text") or str(episode.get("sourceText") or "")
        stored_source_text = _read_episode_source_text(project_id, episode_id)
        if stored_source_text:
            source_text = stored_source_text
        episode_script = (
            _agent_text_row_text(row, "episodeScript", "episode_script", "script", "shootingScript")
            or str(episode.get("episodeScript") or "")
        )
        panels = row.get("panels") if isinstance(row.get("panels"), list) else []
        panel_count = max(1, len(panels) or default_panel_count)
        episode.update(
            {
                "id": episode_id,
                "title": title,
                "status": _agent_text_row_text(row, "status") or f"已保存 {panel_count} 个分镜草稿",
                "sourceText": source_text,
                "episodeScript": episode_script,
                "wordCount": _agent_text_unit_count(source_text),
            }
        )
        _update_agent_workflow(
            project_id,
            episode_id,
            source_text,
            panel_count,
            panels if panels else None,
            episode_script,
        )
        production_plan = _save_episode_production_plan_from_panels(
            project_id,
            episode_id,
            title=title,
            source_text=source_text,
            episode_script=episode_script,
            panels=panels,
            config=config,
        )
        if production_plan:
            production_results.append(production_plan)
        changed_ids.append(episode_id)
    if not changed_ids:
        return {"changed": False, "episodeCount": 0, "focusEpisodeId": selected_episode_id or ""}
    meta["episodes"] = episodes
    agent_split = meta.get("agent_split") if isinstance(meta.get("agent_split"), dict) else {}
    agent_split["source"] = "agent-sdk"
    agent_split["lastTextResult"] = {
        "episodeIds": changed_ids,
        "productionPlans": production_results,
        "summary": _compact_text(str(payload.get("summary") or ""), 300),
        "userInstruction": _generation_user_instruction(payload),
        "updatedAt": _now(),
    }
    meta["agent_split"] = agent_split
    meta["status_type"] = "running"
    meta["status"] = "智能体已保存文本拆分结果"
    if payload.get("summary"):
        meta["summary"] = str(payload.get("summary") or "").strip()
    meta["updated_at"] = _now()
    _write_json(_project_meta_path(project_id), meta)
    return {
        "changed": True,
        "episodeCount": len(changed_ids),
        "episodeIds": changed_ids,
        "productionPlans": production_results,
        "focusEpisodeId": str(payload.get("focusEpisodeId") or selected_episode_id or changed_ids[0]),
    }


def _write_project_document(
    project_id: str,
    filename: str,
    document: dict[str, Any],
    *,
    resource: str,
    focus_target: dict[str, Any],
    expected_revision: Any = None,
    base_hash: Any = None,
    reason: str = "",
    user_instruction: str = "",
) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    from .projects import _touch_project_meta
    if not isinstance(document, dict):
        raise ValueError("保存内容必须是对象")
    path = _project_dir(project_id) / filename
    existing = _read_json(path, {}) if path.exists() else {}
    _assert_resource_write_guard(existing, expected_revision, base_hash)
    revision = _append_resource_revision(
        project_id,
        resource=resource,
        relative_path=filename,
        document=existing,
        reason=reason,
        user_instruction=user_instruction,
    ) if existing else None
    stored = copy.deepcopy(document)
    stored.setdefault("schemaVersion", 1)
    stored["revision"] = _resource_revision_value(existing) + 1
    stored["updatedAt"] = _now()
    _write_json(path, stored)
    _touch_project_meta(project_id)
    result = {
        "success": True,
        "document": stored,
        "changedResources": [resource],
        "focusTarget": focus_target,
        "projectChanged": True,
        "resourceHash": _json_hash(stored),
        "resourceRevision": _resource_revision_value(stored),
    }
    if revision:
        result["revision"] = revision
    return result


def save_story_world_map(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    document = _payload_document(payload, "storyWorld", "story_world", "storyWorldMap", "story_world_map")
    result = _write_project_document(
        project_id,
        "story_world.json",
        document,
        resource="storyWorld",
        focus_target={"section": "story-world"},
        expected_revision=payload.get("expectedRevision") or payload.get("expected_revision"),
        base_hash=payload.get("baseHash") or payload.get("base_hash"),
        reason=str(payload.get("reason") or payload.get("summary") or "save_story_world_map"),
        user_instruction=str(payload.get("userInstruction") or payload.get("user_instruction") or ""),
    )
    result["message"] = "智能体已保存全书故事地图。"
    return result


def save_episode_work_chain_plan(project_id: str, episode_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    document = _payload_document(
        payload,
        "workChainPlan",
        "work_chain_plan",
        "episodeWorkChainPlan",
        "episode_work_chain_plan",
    )
    selected_episode_id = str(
        episode_id
        or document.get("episodeId")
        or document.get("episode_id")
        or payload.get("episodeId")
        or payload.get("episode_id")
        or ""
    ).strip()
    if not selected_episode_id:
        raise ValueError("缺少 episodeId")
    context = get_canvas_context_v4(project_id, selected_episode_id)
    if context["canvasKind"] == "custom" or context["autoWorkflowInitialized"]:
        raise ValueError("当前画布不接受原文工作链计划；自动工作链仅在初始化时创建")
    document["episodeId"] = selected_episode_id
    existing_document = _read_json(
        _project_dir(project_id) / "episodes" / selected_episode_id / "work_chain_plan.json",
        {},
    )
    if isinstance(existing_document, dict):
        document = _preserve_locked_plan_document(existing_document, document)
        document["episodeId"] = selected_episode_id
    document = _storyboard_only_shot_plan(document)
    if not isinstance(document.get("shots"), list) or not document.get("shots"):
        raise ValueError("工作链计划缺少可执行 shots[]，无法生成画布工作流")
    if isinstance(document.get("contextProvenance"), dict) and document.get("contextProvenance"):
        document["contextProvenance"] = _trusted_context_provenance_for_episode(
            project_id,
            selected_episode_id,
        )
    document = _auto_bind_shot_plan_asset_refs(project_id, selected_episode_id, document)
    document = _normalize_shot_plan_asset_refs(document)
    document = _stamp_source_units_on_shot_plan(project_id, selected_episode_id, document)
    blocking, warnings = _validate_shot_plan_source_refs(project_id, selected_episode_id, document)
    asset_blocking, asset_warnings = _validate_plan_asset_refs(project_id, document, selected_episode_id)
    blocking.extend(asset_blocking)
    warnings.extend(asset_warnings)
    if blocking:
        raise ValueError("；".join(blocking))
    result = _write_project_document(
        project_id,
        f"episodes/{selected_episode_id}/work_chain_plan.json",
        document,
        resource="workChainPlan",
        focus_target={"section": "episode", "episodeId": selected_episode_id},
        expected_revision=payload.get("expectedRevision") or payload.get("expected_revision"),
        base_hash=payload.get("baseHash") or payload.get("base_hash"),
        reason=str(payload.get("reason") or payload.get("summary") or "save_episode_work_chain_plan"),
        user_instruction=str(payload.get("userInstruction") or payload.get("user_instruction") or ""),
    )
    result["episodeId"] = selected_episode_id
    segment_count = _planning_count(document, "segments")
    shot_count = _planning_count(document, "shots")
    details = []
    if segment_count:
        details.append(f"{segment_count} 个原文事实段落")
    if shot_count:
        details.append(f"{shot_count} 个镜头面板")
    detail_text = f"，包含{'、'.join(details)}" if details else ""
    result["message"] = f"智能体已保存 {selected_episode_id} 工作链计划{detail_text}。"
    if warnings:
        result["warnings"] = warnings
    return result


def _planning_count(document: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = document.get(key)
        if isinstance(value, list):
            return len([item for item in value if item])
        if isinstance(value, dict):
            return len(value)
        if isinstance(value, str) and value.strip():
            return 1
    return 0


def _planning_text(document: dict[str, Any], *keys: str) -> str:
    from .projects import _first_text
    for key in keys:
        value = document.get(key)
        text = _first_text(value)
        if text:
            return text
    return ""


def _planning_episode_range_summary(range_ref: dict[str, Any] | None, source_ref: dict[str, Any] | None) -> str:
    ref = range_ref if isinstance(range_ref, dict) and range_ref else source_ref if isinstance(source_ref, dict) else {}
    if not ref:
        return ""
    start = ref.get("absoluteStart")
    end = ref.get("absoluteEnd")
    char_count = ref.get("charCount") or ref.get("actualUnits")
    reason = str(ref.get("boundaryReason") or ref.get("reason") or "").strip()
    parts: list[str] = []
    if start is not None and end is not None:
        parts.append(f"{start}-{end}")
    if char_count:
        parts.append(f"{char_count} 字")
    if reason:
        parts.append(reason)
    return " · ".join(parts)


def _planning_boundary_plan_from_source_coverage(
    project_id: str,
    episode_id: str,
) -> dict[str, Any]:
    coverage = _load_source_coverage(project_id)
    episode_ranges = [
        copy.deepcopy(item)
        for item in coverage.get("episodeRanges") or []
        if isinstance(item, dict)
    ]
    episode_range = next(
        (
            item
            for item in episode_ranges
            if str(item.get("episodeId") or item.get("episode_id") or "") == episode_id
        ),
        {},
    )
    source_ref_path = _episode_source_ref_path(project_id, episode_id)
    source_ref = _read_json(source_ref_path, {}) if source_ref_path.exists() else {}
    ready = bool(episode_range or source_ref)
    summary = _planning_episode_range_summary(episode_range, source_ref)
    return {
        "ready": ready,
        "updatedAt": (
            (episode_range.get("updatedAt") if isinstance(episode_range, dict) else None)
            or (source_ref.get("updatedAt") if isinstance(source_ref, dict) else None)
            or coverage.get("updatedAt")
        ),
        "summary": summary,
        "candidateCount": len(episode_ranges),
        "sourceCoverage": coverage,
        "sourceRef": source_ref if isinstance(source_ref, dict) else {},
        "episodeRange": episode_range if isinstance(episode_range, dict) else {},
    }


def _planning_episode_boundary_export(project_id: str) -> dict[str, Any]:
    coverage = _load_source_coverage(project_id)
    episode_ranges = [
        copy.deepcopy(item)
        for item in coverage.get("episodeRanges") or []
        if isinstance(item, dict)
    ]
    source_refs: dict[str, Any] = {}
    for item in episode_ranges:
        episode_id = str(item.get("episodeId") or item.get("episode_id") or "").strip()
        if not episode_id:
            continue
        path = _episode_source_ref_path(project_id, episode_id)
        ref = _read_json(path, {}) if path.exists() else {}
        if isinstance(ref, dict) and ref:
            source_refs[episode_id] = ref
    return {
        "schemaVersion": 2,
        "sourceCoverage": coverage,
        "episodeRanges": episode_ranges,
        "sourceRefs": source_refs,
        "updatedAt": coverage.get("updatedAt"),
    }


def get_project_planning_summary(
    project_id: str,
    episode_id: str | None = None,
) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    from .agent_sessions import _project_meta_path
    from .workflow_projection import get_canvas_workflow_projection
    project_dir = _project_dir(project_id)
    meta = _read_json(_project_meta_path(project_id), {})
    episodes = meta.get("episodes") if isinstance(meta.get("episodes"), list) else []
    selected_episode_id = str(
        episode_id
        or (episodes[0].get("id") if episodes and isinstance(episodes[0], dict) else "")
        or "E01"
    ).strip()
    story_world = _read_json(project_dir / "story_world.json", {})
    boundary_plan = _planning_boundary_plan_from_source_coverage(project_id, selected_episode_id)
    shot_plan = _read_json(project_dir / "episodes" / selected_episode_id / "work_chain_plan.json", {})
    workflow = get_canvas_workflow_projection(project_id, selected_episode_id)
    workflow_versions: list[dict[str, Any]] = []
    routes = workflow.get("routes") if isinstance(workflow.get("routes"), list) else []
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    locked_routes = [
        item for item in routes if isinstance(item, dict) and _is_user_locked_item(item)
    ]
    locked_nodes = [
        item for item in nodes if isinstance(item, dict) and _is_user_locked_item(item)
    ]
    story_world_ready = isinstance(story_world, dict) and bool(story_world)
    shot_ready = isinstance(shot_plan, dict) and bool(shot_plan)
    return {
        "success": True,
        "projectId": project_id,
        "episodeId": selected_episode_id,
        "storyWorld": {
            "ready": story_world_ready,
            "updatedAt": story_world.get("updatedAt") if isinstance(story_world, dict) else None,
            "summary": _planning_text(story_world, "overview", "summary", "synopsis", "storyBible"),
            "counts": {
                "characters": _planning_count(story_world, "characters", "characterMap", "roles"),
                "scenes": _planning_count(story_world, "scenes", "sceneMap", "locations"),
                "props": _planning_count(story_world, "props", "propMap", "items"),
            },
        },
        "boundaryPlan": {
            "ready": bool(boundary_plan.get("ready")),
            "updatedAt": boundary_plan.get("updatedAt"),
            "summary": str(boundary_plan.get("summary") or ""),
            "candidateCount": int(boundary_plan.get("candidateCount") or 0),
            "sourceRef": boundary_plan.get("sourceRef") or {},
            "episodeRange": boundary_plan.get("episodeRange") or {},
        },
        "workChainPlan": {
            "ready": shot_ready,
            "updatedAt": shot_plan.get("updatedAt") if isinstance(shot_plan, dict) else None,
            "summary": _planning_text(shot_plan, "summary", "strategy", "episodeGoal"),
            "segmentCount": _planning_count(shot_plan, "segments", "acts"),
            "shotCount": _planning_count(shot_plan, "shots", "shotList", "panels"),
        },
        "workflow": {
            "ready": bool(nodes or routes),
            "routeCount": len(routes),
            "nodeCount": len(nodes),
            "edgeCount": len(edges),
            "lockedRouteCount": len(locked_routes),
            "lockedNodeCount": len(locked_nodes),
            "versionCount": len(workflow_versions) if isinstance(workflow_versions, list) else 0,
        },
    }
