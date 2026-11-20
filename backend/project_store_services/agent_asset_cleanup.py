# -*- coding: utf-8 -*-
"""项目资产与画布删除操作的本地确认控制器。"""

from __future__ import annotations

from .runtime_state import (
    _AGENT_CANCEL_FLAGS,
)
from .agent_pending_operations import (
    _agent_message_is_pending_operation_confirmation_reply,
)
from .agent_result_presentation import (
    _agent_episode_session_project_delete_rejection,
    _agent_session_task_policy_rejection,
    _agent_controller_decision_from_result,
)
from .agent_progress_recommendations import (
    _agent_progress_message,
    _agent_progress_state,
)
from .agent_model_runtime import (
    _agent_runtime_config_failure_message,
    _agent_sdk_runtime_config,
)
from .agent_contracts import (
    _agent_steps_from_state,
)

from .agent_asset_range_state import (
    _AGENT_ASSET_REPORT_TYPES,
    _ASSET_RANGE_ANALYSIS_COMPLETED_STATUSES,
    _agent_asset_range_analysis_status,
    _agent_asset_range_id_tokens,
    _agent_asset_range_label,
    _agent_asset_range_output_preview,
    _agent_asset_range_user_label,
    _agent_latest_asset_range_row,
    _agent_range_int,
    _agent_remove_asset_range_refs_from_asset,
    _agent_source_coverage_safe,
)
from .agent_canvas_events import (
    _agent_project_effect_from_save,
    _emit_agent_project_effect,
    _merge_changed_resources,
)
from .agent_context_runtime import (
    _agent_compact_proposal,
)
from .agent_contracts import (
    _agent_chinese_ordinal_value,
)
from .agent_pending_operations import (
    _agent_current_message_allows_model_user_instruction,
    _agent_pending_operation_revision_instruction,
)
from .agent_production_scope import (
    _agent_episode_title_for_agent,
    _agent_latest_episode_id_for_agent,
    _agent_project_episode_rows_for_agent,
)
from .agent_session_events import (
    _emit_agent_session_update,
)
from .agent_session_policy import (
    validate_agent_session_episode_target,
    validate_project_planning_delete_for_session,
)
from .agent_sessions import (
    _agent_message_row,
    _agent_session_detail,
    _apply_agent_message_retention,
    _load_agent_sessions,
    _normalize_agent_message_rows,
    _save_agent_sessions,
    append_agent_execution_error,
)
from .assets import (
    _asset_store_path,
    _delete_project_asset_media_files,
    _project_asset_is_referenced,
    delete_all_project_assets,
)
from .catalogs import (
    DEFAULT_ASSETS,
)
from .projects import (
    _touch_project_meta,
)
from .runtime_state import (
    AgentTurnCancelled,
    _LOCK,
)
from .project_resource_revisions import _append_resource_revision, _json_hash, _resource_revision_value
from .source_coverage import _load_source_coverage, _write_source_coverage
from .source_text_store import _compact_text
from .store_core import (
    _emit_agent_event,
    _now,
    _read_json,
    _write_json,
)
from .workflow_planning_lifecycle import (
    delete_project_planning_outputs,
)
import copy
import json
import re
import traceback
from pathlib import Path
from typing import Any














def _agent_deleted_asset_counts_message(deleted_counts: dict[str, Any] | None) -> str:
    counts = deleted_counts if isinstance(deleted_counts, dict) else {}
    parts = []
    for asset_type, label in _AGENT_ASSET_REPORT_TYPES:
        try:
            count = int(counts.get(asset_type) or 0)
        except (TypeError, ValueError):
            count = 0
        parts.append(f"{label} {count} 个")
    return "，".join(parts)


def _agent_project_asset_counts(project_id: str) -> dict[str, int]:
    assets = _read_json(_asset_store_path("project", project_id), DEFAULT_ASSETS)
    counts: dict[str, int] = {}
    for asset_type, _label in _AGENT_ASSET_REPORT_TYPES:
        rows = assets.get(asset_type)
        counts[asset_type] = len([item for item in rows if isinstance(item, dict)]) if isinstance(rows, list) else 0
    return counts


def _agent_project_asset_cleanup_pending_operation(
    project_id: str,
    session_id: str | None,
    user_message: str,
) -> dict[str, Any]:
    counts = _agent_project_asset_counts(project_id)
    coverage = _agent_source_coverage_safe(project_id)
    asset_ranges = coverage.get("assetRanges") if isinstance(coverage.get("assetRanges"), list) else []
    removed_ranges = len([item for item in asset_ranges if isinstance(item, dict)])
    counts_text = _agent_deleted_asset_counts_message(counts)
    message = (
        f"我理解你要清空当前项目全部已拆分资产：{counts_text}。"
        f"同时会清空资产拆分记录 {removed_ranges} 条，并把资产拆分游标回到开头。\n\n"
        "这一步只执行删除，不会自动重新拆分。"
    )
    return {
        "success": True,
        "message": message,
        "contentBlocks": [{"type": "text", "text": message}],
        "projectChanged": False,
        "pendingOperation": {
            "type": "confirm_project_asset_cleanup",
            "operationType": "confirm_project_asset_cleanup",
            "source": "local-controller",
            "sessionId": str(session_id or ""),
            "createdAt": _now(),
            "requiresUserConfirmation": True,
            "expectedNextTool": "delete_all_project_assets",
            "nextAllowedTools": ["delete_all_project_assets"],
            "proposal": {
                "scope": "all_project_assets",
                "assetCounts": counts,
                "assetRangeCount": removed_ranges,
            },
            "commitPayload": {
                "assetTypes": [asset_type for asset_type, _label in _AGENT_ASSET_REPORT_TYPES],
                "resetAssetRanges": True,
                "confirmDeleteAll": True,
                "reason": "agent_project_asset_cleanup",
                "userInstruction": str(user_message or ""),
                "coverageRevision": _resource_revision_value(coverage),
                "coverageBaseHash": _json_hash(coverage),
            },
            "message": message,
        },
    }


def _agent_latest_asset_range_delete_pending_operation(
    project_id: str,
    session_id: str | None,
    user_message: str,
) -> dict[str, Any]:
    coverage = _load_source_coverage(project_id)
    latest = _agent_latest_asset_range_row(coverage)
    if not isinstance(latest, dict):
        message = "当前项目还没有可删除的资产拆分组。"
        return {
            "success": True,
            "message": message,
            "contentBlocks": [{"type": "text", "text": message}],
            "projectChanged": False,
            "pendingOperation": None,
        }
    asset_range_id = str(latest.get("rangeId") or "").strip()
    if not asset_range_id:
        raise ValueError("最新资产拆分组缺少 rangeId")
    preview = _agent_asset_range_output_preview(project_id, asset_range_id)
    delete_text = _agent_deleted_asset_counts_message(preview.get("delete"))
    detach_text = _agent_deleted_asset_counts_message(preview.get("detach"))
    keep_text = _agent_deleted_asset_counts_message(preview.get("keepReferenced"))
    start_offset = _agent_range_int(latest, "absoluteStart", "startOffset")
    label = _agent_asset_range_label(latest)
    message = (
        f"我理解你要删除最新一组资产拆分：{label}。\n\n"
        f"预计删除仅属于该组的资产：{delete_text}；"
        f"已被其他内容引用的资产会保留并解除该组关联：{keep_text}；"
        f"跨多组复用资产只解除本组关联：{detach_text}。\n\n"
        f"删除后资产拆分游标会回到 {start_offset}，下一次资产拆分会从这里重新开始。"
        "\n这一步只删除最新一组，不会自动重新拆分。"
    )
    return {
        "success": True,
        "message": message,
        "contentBlocks": [{"type": "text", "text": message}],
        "projectChanged": False,
        "pendingOperation": {
            "type": "confirm_latest_asset_range_delete",
            "operationType": "confirm_latest_asset_range_delete",
            "source": "local-controller",
            "sessionId": str(session_id or ""),
            "createdAt": _now(),
            "requiresUserConfirmation": True,
            "expectedNextTool": "delete_latest_asset_range",
            "nextAllowedTools": ["delete_latest_asset_range"],
            "proposal": {
                "scope": "latest_asset_range",
                "assetRangeId": asset_range_id,
                "rangeLabel": label,
                "preview": preview,
            },
            "commitPayload": {
                "assetRangeId": asset_range_id,
                "rangeId": asset_range_id,
                "sourceId": str(latest.get("sourceId") or coverage.get("sourceId") or ""),
                "absoluteStart": _agent_range_int(latest, "absoluteStart"),
                "absoluteEnd": _agent_range_int(latest, "absoluteEnd"),
                "reason": "agent_delete_latest_asset_range",
                "userInstruction": str(user_message or ""),
                "coverageRevision": _resource_revision_value(coverage),
                "coverageBaseHash": _json_hash(coverage),
            },
            "message": message,
        },
    }


def _agent_current_canvas_clear_pending_operation(
    project_id: str,
    episode_id: str,
    session_id: str | None,
    user_message: str,
    *,
    episode_title: str = "",
) -> dict[str, Any]:
    target_episode_id = str(episode_id or "").strip() or "E01"
    display_title = str(episode_title or target_episode_id).strip()
    target_label = (
        f"{target_episode_id}《{display_title}》"
        if display_title and display_title != target_episode_id
        else target_episode_id
    )
    original_instruction = str(user_message or "").strip()
    if not original_instruction:
        original_instruction = f"清空 {target_episode_id} 当前集画布"
    message = (
        f"我理解你要清空 {target_label} 的当前画布和工作链派生结果。\n\n"
        "会删除该集已生成的剧情拆分结果、片段剧本、画布工作链、分镜图片/视频片段、版本记录和生产状态；"
        "不会删除分集原文，也不会删除项目角色、生物、场景、道具资产。"
    )
    return {
        "success": True,
        "message": message,
        "contentBlocks": [{"type": "text", "text": message}],
        "projectChanged": False,
        "pendingOperation": {
            "type": "confirm_current_canvas_clear",
            "operationType": "confirm_current_canvas_clear",
            "source": "local-controller",
            "sessionId": str(session_id or ""),
            "createdAt": _now(),
            "requiresUserConfirmation": True,
            "expectedNextTool": "delete_project_planning_outputs",
            "nextAllowedTools": ["delete_project_planning_outputs"],
            "proposal": {
                "scope": "current_episode_canvas",
                "episodeId": target_episode_id,
                "episodeTitle": display_title,
                "targets": ["storyboards"],
                "preserve": ["episode_source", "project_assets", "source_coverage_episode_range"],
            },
            "commitPayload": {
                "episodeIds": [target_episode_id],
                "targets": ["storyboards"],
                "confirmDeleteAll": True,
                "reason": "agent_current_canvas_clear",
                "userInstruction": original_instruction,
            },
            "message": message,
        },
    }


def _agent_episode_source_delete_pending_operation(
    project_id: str,
    episode_id: str,
    session_id: str | None,
    user_message: str,
    *,
    state: dict[str, Any] | None = None,
    session_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_episode_id = str(episode_id or "").strip()
    if not target_episode_id:
        message = "我需要先确认要删除哪一集。目前只能删除最新一集。"
        return {
            "success": True,
            "message": message,
            "contentBlocks": [{"type": "text", "text": message}],
            "projectChanged": False,
            "pendingOperation": None,
        }
    coverage = _agent_source_coverage_safe(project_id)
    episode_rows = _agent_project_episode_rows_for_agent(project_id, state, coverage=coverage)
    episode_ids = {
        str(item.get("id") or "").strip()
        for item in episode_rows
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    if episode_ids and target_episode_id not in episode_ids:
        message = f"当前项目没有找到 {target_episode_id}，无法删除。"
        return {
            "success": True,
            "message": message,
            "contentBlocks": [{"type": "text", "text": message}],
            "projectChanged": False,
            "pendingOperation": None,
        }
    latest_episode_id = _agent_latest_episode_id_for_agent(
        project_id,
        state,
        session_policy=session_policy,
        episodes=episode_rows,
    )
    if latest_episode_id and target_episode_id != latest_episode_id:
        message = f"当前只能按倒序删除最新一集（最新为 {latest_episode_id}），不能直接删除 {target_episode_id}。"
        return {
            "success": True,
            "message": message,
            "contentBlocks": [{"type": "text", "text": message}],
            "projectChanged": False,
            "pendingOperation": None,
        }
    display_title = _agent_episode_title_for_agent(
        project_id,
        state,
        target_episode_id,
        coverage=coverage,
    )
    target_label = (
        f"{target_episode_id}《{display_title}》"
        if display_title and display_title != target_episode_id
        else target_episode_id
    )
    original_instruction = str(user_message or "").strip()
    if not original_instruction:
        original_instruction = f"删除 {target_episode_id} 分集原文和画布派生结果"
    commit_payload = {
        "episodeIds": [target_episode_id],
        "targets": ["source_splits", "storyboards"],
        "confirmDeleteAll": True,
        "reason": "agent_episode_source_delete",
        "userInstruction": original_instruction,
    }
    try:
        validate_project_planning_delete_for_session(project_id, commit_payload, session_policy)
    except ValueError as exc:
        message = str(exc)
        return {
            "success": True,
            "message": message,
            "contentBlocks": [{"type": "text", "text": message}],
            "projectChanged": False,
            "pendingOperation": None,
        }
    message = (
        f"我理解你要删除 {target_label} 的分集原文和对应工作链画布数据。\n\n"
        "会删除该集分集原文范围、剧情拆分结果、片段剧本、画布工作链、分镜图片/视频片段、版本记录和生产状态；"
        "不会删除原始导入小说文本，也不会删除项目角色、生物、场景、道具资产。\n\n"
        "这一步只删除最新一集，不会自动重新规划。"
    )
    return {
        "success": True,
        "message": message,
        "contentBlocks": [{"type": "text", "text": message}],
        "projectChanged": False,
        "pendingOperation": {
            "type": "confirm_episode_source_delete",
            "operationType": "confirm_episode_source_delete",
            "source": "local-controller",
            "sessionId": str(session_id or ""),
            "createdAt": _now(),
            "requiresUserConfirmation": True,
            "expectedNextTool": "delete_project_planning_outputs",
            "nextAllowedTools": ["delete_project_planning_outputs"],
            "proposal": {
                "scope": "episode_source",
                "episodeId": target_episode_id,
                "episodeTitle": display_title,
                "targets": ["source_splits", "storyboards"],
                "preserve": ["source_import", "project_assets", "source_index", "asset_ranges"],
            },
            "commitPayload": commit_payload,
            "message": message,
        },
    }


def _agent_project_cleanup_pending_operation_from_target(
    project_id: str,
    state: dict[str, Any],
    cleanup_target: dict[str, Any] | None,
    session_id: str | None,
    user_message: str,
    *,
    fallback_episode_id: str = "",
    session_policy: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    target = cleanup_target if isinstance(cleanup_target, dict) else {}
    action = str(target.get("action") or "").strip()
    if action == "clear_project_assets":
        return _agent_project_asset_cleanup_pending_operation(project_id, session_id, user_message)
    if action not in {"clear_episode_canvas", "delete_episode_source"}:
        return None
    target_episode_id = str(target.get("episodeId") or "").strip()
    if action == "clear_episode_canvas" and not target_episode_id:
        target_episode_id = str(fallback_episode_id or state.get("selectedEpisodeId") or "").strip()
    if action == "clear_episode_canvas":
        if not target_episode_id:
            message = "我需要先确认要清空哪一集画布。"
            return {
                "success": True,
                "message": message,
                "contentBlocks": [{"type": "text", "text": message}],
                "projectChanged": False,
                "pendingOperation": None,
            }
        validate_agent_session_episode_target(target_episode_id, session_policy)
        return _agent_current_canvas_clear_pending_operation(
            project_id,
            target_episode_id,
            session_id,
            user_message,
            episode_title=_agent_episode_title_for_agent(project_id, state, target_episode_id),
        )
    return _agent_episode_source_delete_pending_operation(
        project_id,
        target_episode_id,
        session_id,
        user_message,
        state=state,
        session_policy=session_policy,
    )


def _run_project_asset_cleanup_controller(
    project_id: str,
    *,
    pending_operation: dict[str, Any] | None = None,
    user_message: str,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    if cancel_event is not None and cancel_event.is_set():
        raise AgentTurnCancelled()
    commit_payload = (
        copy.deepcopy(pending_operation.get("commitPayload"))
        if isinstance(pending_operation, dict) and isinstance(pending_operation.get("commitPayload"), dict)
        else {}
    )
    original_instruction = str(commit_payload.get("userInstruction") or user_message or "").strip()
    delete_result = delete_all_project_assets(
        project_id,
        {
            **commit_payload,
            "assetTypes": commit_payload.get("assetTypes") or [asset_type for asset_type, _label in _AGENT_ASSET_REPORT_TYPES],
            "resetAssetRanges": commit_payload.get("resetAssetRanges", True),
            "confirmDeleteAll": True,
            "reason": str(commit_payload.get("reason") or "agent_project_asset_cleanup"),
            "userInstruction": original_instruction,
        },
    )
    _emit_agent_event(
        "project_changed",
        {
            "action": "project_assets_deleted_all",
            "projectId": project_id,
            "changedResources": delete_result.get("changedResources") or [],
        },
    )
    deleted_counts_text = _agent_deleted_asset_counts_message(delete_result.get("deletedCounts"))
    reset = delete_result.get("assetRangeReset") if isinstance(delete_result.get("assetRangeReset"), dict) else {}
    removed_ranges = int(reset.get("removedCount") or 0)
    cleanup_message = (
        f"已清空当前项目已拆分资产：{deleted_counts_text}。"
        f"已同步清空资产拆分记录 {removed_ranges} 条。"
    )
    changed_resources = _merge_changed_resources(
        delete_result,
        {"changedResources": ["assets", "sourceCoverage", "assetRanges"]},
    )
    return {
        "success": True,
        "message": cleanup_message,
        "contentBlocks": [{"type": "text", "text": cleanup_message}],
        "projectChanged": True,
        "changedResources": changed_resources,
        "projectEffect": {
            "changedResources": changed_resources,
            "focusTarget": {"section": "assets"},
            "notice": cleanup_message,
        },
        "toolResult": cleanup_message,
        "pendingOperation": None,
    }


def _run_current_canvas_clear_controller(
    project_id: str,
    *,
    pending_operation: dict[str, Any] | None = None,
    user_message: str,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    if cancel_event is not None and cancel_event.is_set():
        raise AgentTurnCancelled()
    commit_payload = (
        copy.deepcopy(pending_operation.get("commitPayload"))
        if isinstance(pending_operation, dict) and isinstance(pending_operation.get("commitPayload"), dict)
        else {}
    )
    episode_ids = [
        str(item or "").strip()
        for item in (commit_payload.get("episodeIds") if isinstance(commit_payload.get("episodeIds"), list) else [])
        if str(item or "").strip()
    ]
    if len(episode_ids) != 1:
        raise ValueError("当前集画布清空必须锁定且只能锁定一个分集")
    original_instruction = str(commit_payload.get("userInstruction") or "").strip()
    if not original_instruction:
        original_instruction = f"清空 {episode_ids[0]} 当前集画布"
    delete_result = delete_project_planning_outputs(
        project_id,
        {
            **commit_payload,
            "episodeIds": episode_ids,
            "targets": ["storyboards"],
            "confirmDeleteAll": True,
            "reason": str(commit_payload.get("reason") or "agent_current_canvas_clear"),
            "userInstruction": original_instruction,
        },
    )
    _emit_agent_event(
        "project_changed",
        {
            "action": "project_planning_outputs_deleted",
            "projectId": project_id,
            "episodeIds": delete_result.get("episodeIds") or episode_ids,
            "targets": delete_result.get("targets") or ["storyboards"],
            "changedResources": delete_result.get("changedResources") or [],
        },
    )
    episode_id = episode_ids[0]
    changed_resources = _merge_changed_resources(
        delete_result,
        {"changedResources": ["workChainPlan", "storyboard", "canvas_document", "productionStatus"]},
    )
    deleted_canvas = int(delete_result.get("deletedCanvasRecordCount") or 0)
    deleted_outputs = int(delete_result.get("deletedStoryboardOutputCount") or 0)
    clear_message = (
        f"已清空 {episode_id} 当前画布和工作链派生结果。"
        f"删除画布记录 {deleted_canvas} 条，分镜输出 {deleted_outputs} 个。"
    )
    return {
        "success": True,
        "message": clear_message,
        "contentBlocks": [{"type": "text", "text": clear_message}],
        "projectChanged": True,
        "changedResources": changed_resources,
        "projectEffect": {
            "changedResources": changed_resources,
            "focusTarget": {"section": "episode", "episodeId": episode_id},
            "notice": clear_message,
        },
        "toolResult": clear_message,
        "deleteResult": delete_result,
        "pendingOperation": None,
    }


def _run_episode_source_delete_controller(
    project_id: str,
    *,
    pending_operation: dict[str, Any] | None = None,
    user_message: str,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    if cancel_event is not None and cancel_event.is_set():
        raise AgentTurnCancelled()
    commit_payload = (
        copy.deepcopy(pending_operation.get("commitPayload"))
        if isinstance(pending_operation, dict) and isinstance(pending_operation.get("commitPayload"), dict)
        else {}
    )
    episode_ids = [
        str(item or "").strip()
        for item in (commit_payload.get("episodeIds") if isinstance(commit_payload.get("episodeIds"), list) else [])
        if str(item or "").strip()
    ]
    if len(episode_ids) != 1:
        raise ValueError("删除分集必须锁定且只能锁定一个分集")
    original_instruction = str(commit_payload.get("userInstruction") or user_message or "").strip()
    if not original_instruction:
        original_instruction = f"删除 {episode_ids[0]} 分集原文和画布派生结果"
    delete_result = delete_project_planning_outputs(
        project_id,
        {
            **commit_payload,
            "episodeIds": episode_ids,
            "targets": ["source_splits", "storyboards"],
            "confirmDeleteAll": True,
            "reason": str(commit_payload.get("reason") or "agent_episode_source_delete"),
            "userInstruction": original_instruction,
        },
    )
    _emit_agent_event(
        "project_changed",
        {
            "action": "project_planning_outputs_deleted",
            "projectId": project_id,
            "episodeIds": delete_result.get("episodeIds") or episode_ids,
            "targets": delete_result.get("targets") or ["source_splits", "storyboards"],
            "changedResources": delete_result.get("changedResources") or [],
        },
    )
    episode_id = episode_ids[0]
    proposal = (
        pending_operation.get("proposal")
        if isinstance(pending_operation, dict) and isinstance(pending_operation.get("proposal"), dict)
        else {}
    )
    episode_title = str(proposal.get("episodeTitle") or "").strip()
    episode_label = (
        f"{episode_id}《{episode_title}》"
        if episode_title and episode_title != episode_id
        else episode_id
    )
    changed_resources = _merge_changed_resources(
        delete_result,
        {"changedResources": ["sourceCoverage", "episodes", "storyboards", "workflow", "workflow_tasks", "versions", "episode_production_status", "tasks"]},
    )
    deleted_canvas = int(delete_result.get("deletedCanvasRecordCount") or 0)
    deleted_tasks = int(delete_result.get("deletedTaskCount") or 0)
    cleanup_message = (
        f"已删除 {episode_label} 的分集原文和对应工作链画布数据。"
        f"删除画布记录 {deleted_canvas} 条，关联任务 {deleted_tasks} 个。"
    )
    return {
        "success": True,
        "message": cleanup_message,
        "contentBlocks": [{"type": "text", "text": cleanup_message}],
        "projectChanged": True,
        "changedResources": changed_resources,
        "projectEffect": {
            "changedResources": changed_resources,
            "focusTarget": {"section": "sources"},
            "notice": cleanup_message,
        },
        "toolResult": cleanup_message,
        "deleteResult": delete_result,
        "pendingOperation": None,
    }


def _run_latest_asset_range_delete_controller(
    project_id: str,
    *,
    pending_operation: dict[str, Any],
    user_message: str,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    if cancel_event is not None and cancel_event.is_set():
        raise AgentTurnCancelled()
    commit_payload = pending_operation.get("commitPayload") if isinstance(pending_operation.get("commitPayload"), dict) else {}
    asset_range_id = str(commit_payload.get("assetRangeId") or commit_payload.get("rangeId") or "").strip()
    if not asset_range_id:
        raise ValueError("缺少要删除的最新资产拆分组")
    user_instruction = str(commit_payload.get("userInstruction") or user_message or "").strip()
    delete_result = _agent_delete_latest_asset_range_outputs(
        project_id,
        asset_range_id,
        reason=str(commit_payload.get("reason") or "agent_delete_latest_asset_range"),
        user_instruction=user_instruction,
    )
    _emit_agent_event(
        "project_changed",
        {
            "action": "latest_asset_range_deleted",
            "projectId": project_id,
            "assetRangeId": asset_range_id,
            "changedResources": delete_result.get("changedResources") or [],
        },
    )
    deleted_text = _agent_deleted_asset_counts_message(delete_result.get("deletedCounts"))
    detached_text = _agent_deleted_asset_counts_message(delete_result.get("detachedCounts"))
    kept_text = _agent_deleted_asset_counts_message(delete_result.get("keptReferencedCounts"))
    removed_range = delete_result.get("removedRange") if isinstance(delete_result.get("removedRange"), dict) else {}
    next_offset = int(delete_result.get("nextAssetOffset") or 0)
    message = (
        f"已删除最新一组资产拆分：{_agent_asset_range_label(removed_range)}。\n\n"
        f"删除资产：{deleted_text}；解除本组关联：{detached_text}；保留已引用资产：{kept_text}。\n\n"
        f"资产拆分游标已回到 {next_offset}。本次只删除，不会自动重新拆分。"
    )
    changed_resources = _merge_changed_resources(delete_result, {"changedResources": ["assets", "sourceCoverage", "assetRanges"]})
    return {
        "success": True,
        "message": message,
        "contentBlocks": [{"type": "text", "text": message}],
        "projectChanged": True,
        "changedResources": changed_resources,
        "projectEffect": {
            "changedResources": changed_resources,
            "focusTarget": {"section": "assets"},
            "notice": message,
        },
        "toolResult": message,
        "pendingOperation": None,
    }


def _agent_clear_asset_range_outputs(
    project_id: str,
    asset_range_id: str,
    *,
    reason: str,
    user_instruction: str,
) -> dict[str, Any]:
    if not project_id or not asset_range_id:
        return {"success": False, "message": "缺少要清理的资产范围"}
    asset_path = _asset_store_path("project", project_id)
    assets_before = _read_json(asset_path, DEFAULT_ASSETS)
    assets = copy.deepcopy(assets_before)
    deleted_counts: dict[str, int] = {}
    detached_counts: dict[str, int] = {}
    kept_referenced_counts: dict[str, int] = {}
    changed_assets = False
    for asset_type, _label in _AGENT_ASSET_REPORT_TYPES:
        rows = assets.get(asset_type)
        if not isinstance(rows, list):
            continue
        next_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            range_ids = _agent_asset_range_id_tokens(
                row.get("assetRangeIds"),
                row.get("assetRangeId"),
            )
            if asset_range_id not in range_ids:
                next_rows.append(row)
                continue
            remaining = [range_id for range_id in range_ids if range_id != asset_range_id]
            if not remaining and not _project_asset_is_referenced(project_id, asset_type, row):
                _delete_project_asset_media_files(project_id, row)
                deleted_counts[asset_type] = deleted_counts.get(asset_type, 0) + 1
                changed_assets = True
                continue
            updated, changed = _agent_remove_asset_range_refs_from_asset(row, asset_range_id)
            next_rows.append(updated)
            if changed:
                detached_counts[asset_type] = detached_counts.get(asset_type, 0) + 1
                changed_assets = True
            if not remaining:
                kept_referenced_counts[asset_type] = kept_referenced_counts.get(asset_type, 0) + 1
        assets[asset_type] = next_rows
    changed_resources: list[str] = []
    if changed_assets:
        assets["revision"] = _resource_revision_value(assets_before) + 1
        assets["updatedAt"] = _now()
        _write_json(asset_path, assets)
        _append_resource_revision(
            project_id,
            resource="assets",
            relative_path="assets/assets.json",
            document=assets_before,
            reason=reason or "asset_range_cleanup",
            user_instruction=user_instruction,
        )
        _touch_project_meta(project_id)
        changed_resources.append("assets")
    coverage_before = _load_source_coverage(project_id)
    coverage = copy.deepcopy(coverage_before)
    coverage_changed = False
    coverage_ranges = coverage.get("assetRanges") if isinstance(coverage.get("assetRanges"), list) else []
    for item in coverage_ranges:
        if not isinstance(item, dict) or str(item.get("rangeId") or "").strip() != asset_range_id:
            continue
        item["createdAssetIds"] = []
        item["analysisStatus"] = "committed"
        item["analysisUpdatedAt"] = _now()
        item.pop("analysisError", None)
        item.pop("analysisDetails", None)
        item.pop("analysisResult", None)
        coverage_changed = True
        break
    if coverage_changed:
        coverage["revision"] = _resource_revision_value(coverage_before) + 1
        _write_source_coverage(project_id, coverage)
        _append_resource_revision(
            project_id,
            resource="sourceCoverage",
            relative_path="source_coverage.json",
            document=coverage_before,
            reason=reason or "asset_range_cleanup",
            user_instruction=user_instruction,
        )
        changed_resources.append("assetRanges")
    return {
        "success": True,
        "assetRangeId": asset_range_id,
        "deletedCounts": deleted_counts,
        "detachedCounts": detached_counts,
        "keptReferencedCounts": kept_referenced_counts,
        "changedResources": changed_resources,
        "projectChanged": bool(changed_resources),
    }


def _agent_delete_latest_asset_range_outputs(
    project_id: str,
    asset_range_id: str,
    *,
    reason: str,
    user_instruction: str,
) -> dict[str, Any]:
    coverage_before = _load_source_coverage(project_id)
    latest = _agent_latest_asset_range_row(coverage_before)
    if not isinstance(latest, dict):
        raise ValueError("当前项目没有可删除的资产拆分组")
    latest_id = str(latest.get("rangeId") or "").strip()
    if not latest_id or latest_id != asset_range_id:
        raise ValueError("只能删除最新一组资产拆分；不能从中间删除")
    status = str(latest.get("analysisStatus") or "").strip().lower()
    if status in {"running", "queued", "processing", "analyzing", "submitted"}:
        raise ValueError("最新资产拆分组仍在运行中，不能删除；请先停止或等待任务结束")

    cleanup_result = _agent_clear_asset_range_outputs(
        project_id,
        asset_range_id,
        reason=reason or "delete_latest_asset_range_outputs",
        user_instruction=user_instruction,
    )
    coverage_after_cleanup = _load_source_coverage(project_id)
    latest_after_cleanup = _agent_latest_asset_range_row(coverage_after_cleanup)
    latest_after_id = (
        str((latest_after_cleanup or {}).get("rangeId") or "").strip()
        if isinstance(latest_after_cleanup, dict)
        else ""
    )
    if latest_after_id != asset_range_id:
        raise ValueError("资产范围已变化，删除最新组已停止；请重新确认当前最新一组")

    coverage_before_remove = copy.deepcopy(coverage_after_cleanup)
    ranges = coverage_after_cleanup.get("assetRanges") if isinstance(coverage_after_cleanup.get("assetRanges"), list) else []
    coverage_after_cleanup["assetRanges"] = [
        item
        for item in ranges
        if not (
            isinstance(item, dict)
            and str(item.get("rangeId") or "").strip() == asset_range_id
        )
    ]
    previous_latest = _agent_latest_asset_range_row(coverage_after_cleanup)
    start_offset = _agent_range_int(latest, "absoluteStart")
    cursor = coverage_after_cleanup.setdefault("assetCursor", {})
    cursor["nextOffset"] = start_offset
    cursor["lastRangeId"] = (
        str((previous_latest or {}).get("rangeId") or "").strip()
        if isinstance(previous_latest, dict)
        else None
    )
    coverage_after_cleanup["revision"] = _resource_revision_value(coverage_before_remove) + 1
    _write_source_coverage(project_id, coverage_after_cleanup)
    _append_resource_revision(
        project_id,
        resource="sourceCoverage",
        relative_path="source_coverage.json",
        document=coverage_before_remove,
        reason=reason or "delete_latest_asset_range_outputs",
        user_instruction=user_instruction,
    )
    _touch_project_meta(project_id)
    changed_resources = _merge_changed_resources(
        cleanup_result,
        {"changedResources": ["assetRanges", "sourceCoverage"]},
    )
    return {
        "success": True,
        "assetRangeId": asset_range_id,
        "deletedCounts": cleanup_result.get("deletedCounts") or {},
        "detachedCounts": cleanup_result.get("detachedCounts") or {},
        "keptReferencedCounts": cleanup_result.get("keptReferencedCounts") or {},
        "removedRange": latest,
        "previousRangeId": cursor.get("lastRangeId"),
        "nextAssetOffset": start_offset,
        "changedResources": changed_resources,
        "projectChanged": True,
    }
