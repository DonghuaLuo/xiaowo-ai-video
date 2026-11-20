# -*- coding: utf-8 -*-
"""已确认的剧情拆分候选校验与画布工作链装配。"""

from __future__ import annotations

from .worker_plot_validation import (
    validate_plot_splitting_worker_output,
)
from .worker_task_context import (
    _asset_name_rows,
    _filter_plot_splitting_candidate_assets,
    _resolved_plot_context_assets,
)
from .agent_canvas_events import (
    _agent_project_effect_from_save,
    _canvas_mutation_event_payload,
)
from .agent_pending_operations import _plot_split_pending_operation, _plot_split_pending_retry_fields
from .agent_plot_contract import (
    _agent_compact_plot_split_proposal,
    _agent_plot_split_revision_count,
)
from .agent_sessions import (
    append_agent_execution_error,
)
from .agent_work_chain_plan_projection import (
    _agent_work_chain_plan_saved_message,
)
from .canvas_store_queries import get_canvas_context_v4
from .episode_plan_documents import save_episode_work_chain_plan
from .reference_utils import asset_refs_has_value as _asset_refs_has_value
from .planning_contract import (
    _safe_workflow_id,
)
from .plot_split_one_request import clean_plot_source_text, resolve_plot_split_source_range_text, validate_plot_split_asset_ids, validate_plot_split_source_coverage
from .runtime_state import (
    AgentTurnCancelled,
    _LOCK,
)
from .episode_boundary_planning import _ensure_episode_meta_entry
from .source_boundary_contract import _normalize_episode_boundary_title
from .source_text_store import _compact_text, get_episode_source_text
from .store_core import _emit_agent_event
from .workflow_projection import (
    build_episode_workflow_from_work_chain_plan,
)
from .agent_plot_contract import (
    _compact_source_excerpt,
)

import copy
import traceback
from typing import Any


def _plot_split_asset_refs(item: dict[str, Any]) -> dict[str, Any]:
    refs = item.get("assetHints")
    return copy.deepcopy(refs if isinstance(refs, dict) else {})


def _work_chain_plan_from_plot_split_proposal(
    episode_id: str,
    proposal: dict[str, Any],
    *,
    source_text: str,
    source_ref: dict[str, Any],
) -> dict[str, Any]:
    items = proposal.get("items") if isinstance(proposal.get("items"), list) else []
    episode_title = _normalize_episode_boundary_title(
        proposal.get("episodeTitle"),
        episode_id,
    )
    segments: list[dict[str, Any]] = []
    shots: list[dict[str, Any]] = []
    for index, item in enumerate([row for row in items if isinstance(row, dict)], start=1):
        plot_item_id = str(item.get("id") or f"plot_{index:03d}").strip() or f"plot_{index:03d}"
        segment_id = _safe_workflow_id(str(item.get("segmentId") or f"seg_{index:03d}"), f"seg_{index:03d}")
        title = _compact_text(item.get("title") or f"原文拆分内容 {index}", 80)
        # Keep source refs on the full validated slice, and hand only the cleaned
        # story text to downstream cards and previews.
        source_fact_text = clean_plot_source_text(
            str(item.get("sourceFactText") or ""), item.get("excludedTexts", []),
        )
        source_preview = _compact_source_excerpt(
            source_fact_text,
            260,
        )
        source_refs = item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else []
        asset_refs = _plot_split_asset_refs(item)
        asset_bindings = copy.deepcopy(
            item.get("assetBindings")
            if isinstance(item.get("assetBindings"), list)
            else []
        )
        asset_refs_missing = not _asset_refs_has_value(asset_refs)
        narrative_purpose = _compact_text(source_fact_text or source_preview or title, 280)
        segment = {
            "id": segment_id,
            "title": title,
            "workChainTitle": title,
            "workChainLabel": title,
            "workChainId": f"chain_{index:03d}",
            "plotSplitItemId": plot_item_id,
            "sourceRefs": copy.deepcopy(source_refs),
            "sourcePreview": source_preview,
            "sourceFactText": source_fact_text,
            "cinematicStoryText": "",
            "assetRefs": asset_refs,
            "assetBindings": copy.deepcopy(asset_bindings),
            "assetRefsOptional": asset_refs_missing,
            "splitReason": _compact_text(item.get("splitReason"), 180),
            "narrativePurpose": narrative_purpose,
            "generationStrategy": "storyboard_multi_shot",
            "storyboardAnalysis": {
                "storyFacts": [narrative_purpose] if narrative_purpose else [],
                "characters": [],
                "creatures": [],
                "scene": "",
                "props": [],
                "panelIntent": [],
                "dramaticIntent": "",
                "cinematicStrategy": "",
                "performanceBeats": [],
                "cameraRhythm": "",
                "transitionPlan": "",
                "effectGuidance": "",
            },
            "storyboardTaskCard": {
                "title": title,
                "cinematicStoryText": "",
                "sourceFactText": source_fact_text,
                "sourcePreview": source_preview,
                "state": "pending_script",
                "scriptState": "pending_script",
                "assetState": "assets_ready" if any(asset_refs.get(key) for key in ("characters", "creatures", "scenes", "props")) else "draft",
                "assetRefs": copy.deepcopy(asset_refs),
                "assetBindings": copy.deepcopy(asset_bindings),
                "assetRefsOptional": asset_refs_missing,
            },
        }
        shot_id = f"shot_{index:03d}"
        shots.append(
            {
                "id": shot_id,
                "segmentId": segment_id,
                "shotLabel": "Shot 01",
                "title": title,
                "sourceRefs": copy.deepcopy(source_refs),
                "assetRefs": copy.deepcopy(asset_refs),
                "assetBindings": copy.deepcopy(asset_bindings),
                "assetRefsOptional": asset_refs_missing,
                "coverageRole": "storyboard_task_placeholder",
                "visibleAction": narrative_purpose or title,
                "startState": {},
                "endState": {},
                "camera": {},
                "referencePlan": {"mode": "storyboard_image", "requiredImages": []},
                "storyboardImagePrompt": "",
                "generationStrategy": "storyboard_multi_shot",
            }
        )
        segments.append(segment)
    return {
        "schemaVersion": 2,
        "episodeId": episode_id,
        "contentMode": "plot_split_canvas",
        "episodeTitle": episode_title or str(proposal.get("episodeTitle") or episode_id),
        "title": episode_title or str(proposal.get("episodeTitle") or episode_id),
        "sourceRange": copy.deepcopy(source_ref),
        "sourceRefs": [copy.deepcopy(source_ref)] if source_ref else [],
        "sourceText": source_text,
        "episodeScript": "",
        "segments": segments,
        "shots": shots,
        "plotSplitProposal": copy.deepcopy(proposal),
        "strategyPlan": [{"strategy": "storyboard_multi_shot", "segmentCount": len(segments)}],
    }


def _commit_plot_split_to_workflow_controller(
    project_id: str,
    episode_id: str | None,
    *,
    parent_session_id: str | None,
    user_message: str,
    plot_split_proposal: dict[str, Any] | None,
    pending_operation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Check, plan save and graph initialization must exclude another confirmation.
    with _LOCK:
        return _commit_plot_split_to_workflow_locked(
            project_id, episode_id, parent_session_id=parent_session_id,
            user_message=user_message, plot_split_proposal=plot_split_proposal,
            pending_operation=pending_operation,
        )


def _commit_plot_split_to_workflow_locked(
    project_id: str,
    episode_id: str | None,
    *,
    parent_session_id: str | None,
    user_message: str,
    plot_split_proposal: dict[str, Any] | None,
    pending_operation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_episode_id = str(episode_id or "E01").strip() or "E01"
    canvas_context = get_canvas_context_v4(project_id, selected_episode_id)
    if canvas_context["canvasKind"] == "custom" or canvas_context["autoWorkflowInitialized"]:
        raise ValueError("当前画布不支持再次自动创建工作链")
    proposal = _agent_compact_plot_split_proposal(plot_split_proposal)
    pending_operation_context = pending_operation if isinstance(pending_operation, dict) else {}
    pending_commit_payload = (
        pending_operation_context.get("commitPayload")
        if isinstance(pending_operation_context.get("commitPayload"), dict)
        else {}
    )
    retry_fields = _plot_split_pending_retry_fields(pending_operation_context, pending_commit_payload)
    retry_source_ref = retry_fields.get("source_ref")
    source_ref = copy.deepcopy(retry_source_ref if isinstance(retry_source_ref, dict) else {})
    write_started = False
    try:
        source = get_episode_source_text(project_id, selected_episode_id)
        if source.get("available") is False:
            raise ValueError(f"{selected_episode_id} 缺少已提交 source range")
        latest_source_ref = source.get("sourceRef") if isinstance(source.get("sourceRef"), dict) else {}
        if latest_source_ref:
            source_ref = latest_source_ref
        if not source_ref:
            raise ValueError(f"{selected_episode_id} 缺少可提交的 source range")
        source_range_text = resolve_plot_split_source_range_text(
            project_id, str(source.get("text") or ""), source_ref
        )
        _, context_envelope = _resolved_plot_context_assets(  # noqa: SLF001
            project_id,
            selected_episode_id,
            source,
            production_memory={},
        )
        assets = _filter_plot_splitting_candidate_assets(
            _asset_name_rows(
                project_id,
                include_desc=True,
                source_ref=source_ref,
                include_state_versions=False,
                desc_limit=500,
            )
        )
        validate_plot_split_asset_ids(proposal, assets)
        validate_plot_split_source_coverage(proposal, source_range_text, source_ref)
        validation = validate_plot_splitting_worker_output(
            {"plotSplitProposal": proposal},
            episode_id=selected_episode_id,
            source_ref=source_ref,
            episode_text=source_range_text,
            assets=assets,
            context_envelope=context_envelope if isinstance(context_envelope, dict) else {},
            allow_asset_hints=True,
        )
        if not validation.get("success"):
            raise ValueError("；".join(validation.get("blockingIssues") or ["剧情及资产关联结果校验失败"]))
        proposal = validation.get("plotSplitProposal") if isinstance(validation.get("plotSplitProposal"), dict) else {}
        work_chain_plan = _work_chain_plan_from_plot_split_proposal(
            selected_episode_id,
            proposal,
            source_text=str(source.get("text") or ""),
            source_ref=source_ref,
        )
        if isinstance(proposal, dict):
            write_started = True
            episode_title = str(proposal.get("episodeTitle") or "").strip()
            if episode_title:
                _ensure_episode_meta_entry(project_id, selected_episode_id, episode_title, source_ref)
        save_result = save_episode_work_chain_plan(
            project_id,
            selected_episode_id,
            {
                "episodeId": selected_episode_id,
                "workChainPlan": work_chain_plan,
                "reason": "plot-splitting canvas assembly",
                "userInstruction": user_message,
                "plotSplitProposal": proposal,
            },
        )
        workflow_result = build_episode_workflow_from_work_chain_plan(
            project_id,
            selected_episode_id,
            {
                "source": "agent",
                "reason": "plot-splitting canvas assembly",
            },
        )
        canvas_event_fields = _canvas_mutation_event_payload(
            save_result,
            workflow_result,
            fallback_changed_resources=["workChainPlan", "storyboard", "canvas_document"],
        )
        _emit_agent_event(
            "project_changed",
            {
                "action": "episode_workflow_canvas_saved",
                "projectId": project_id,
                "episodeId": selected_episode_id,
                **canvas_event_fields,
            },
        )
        save_result.update(copy.deepcopy(canvas_event_fields))
        changed_resources = canvas_event_fields.get("changedResources") or []
        if not changed_resources:
            changed_resources = ["workChainPlan", "storyboard", "canvas_document"]
        message = _agent_work_chain_plan_saved_message(selected_episode_id, work_chain_plan, workflow_result)
        project_effect = _agent_project_effect_from_save(
            changed_resources,
            save_result,
            project_id=project_id,
            episode_id=selected_episode_id,
            notice=message,
        )
        return {
            "success": True,
            "message": message,
            "projectChanged": True,
            "projectEffect": project_effect,
            "toolResult": message,
            "saveResult": save_result,
            "episodeId": selected_episode_id,
            "pendingOperation": None,
        }
    except AgentTurnCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (ValueError, FileNotFoundError)) and not write_started:
            return {
                "success": False, "status": "blocked", "projectChanged": False,
                "message": f"未写入工作链：{exc}。请修订候选或恢复相关资料后再确认。",
                "pendingOperation": copy.deepcopy(pending_operation_context) or None,
            }
        append_agent_execution_error(
            project_id,
            stage="plot_split_canvas_assembly",
            message="工作链画布装配失败",
            episode_id=selected_episode_id,
            session_id=parent_session_id,
            category="plot_split_commit_error",
            source="plot_split_commit",
            error=exc,
            include_traceback=True,
        )
        print(traceback.format_exc(), flush=True)
        message = f"工作链画布装配失败：{exc}"
        return {
            "success": False,
            "message": message,
            "error": str(exc),
            "pendingOperation": copy.deepcopy(pending_operation_context) or _plot_split_pending_operation(
                episode_id=selected_episode_id,
                proposal=proposal,
                session_id=parent_session_id,
                user_instruction=user_message,
                source="plot-splitting.canvas-assembly-retry",
                message="工作链画布装配失败，当前拆分结果仍可重新提交。",
                source_ref=source_ref,
                base_user_instruction=str(retry_fields.get("base_user_instruction") or ""),
                effective_revision_requirements=retry_fields.get("effective_revision_requirements")
                if isinstance(retry_fields.get("effective_revision_requirements"), list)
                else [],
                revision_count=_agent_plot_split_revision_count(retry_fields.get("revision_count")),
            )
            if proposal.get("items")
            else None,
        }
