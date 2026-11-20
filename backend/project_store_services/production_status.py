# -*- coding: utf-8 -*-
"""Episode production status and workflow review result persistence."""

from __future__ import annotations
from .canvas_ownership import VIDEO_TASK_NODE_TYPES

import copy
import hashlib
import re
import traceback
from pathlib import Path
from typing import Any
from .settings_loaders import model_settings_revision

from .work_chain_context import card_text, script_source_text
from .work_chain_actions import recommend_work_chain_actions

from .agent_sessions import _project_dir
from .store_core import _now, _read_json, _write_json, _JSON_WRITE_LOCK
from .canvas_ownership import source_work_chain_ids, work_chain_scope
from .canvas_store_queries import read_episode_card_results, read_previous_cinematic_script_text_v4
from .canvas_store_database import CanvasRevisionConflict, retry_canvas_mutation_v4
from .canvas_store_documents import write_canvas_production_status_v4
from .workflow_projection import get_canvas_workflow_projection
from .workflow_contract import workflow_video_task_scope
from .workflow_input_resolution import (
    workflow_current_media_version_has_media,
)
from .quality_gate import workflow_node_quality_blocks, workflow_node_quality_block_message


_REVIEW_SEVERITIES = {"blocker", "warning", "info"}
_OPTIONAL_PRODUCTION_STATES = {"cinematic_script.generated", "storyboard.generated", "visual_handoff.generated"}

_EPISODE_CURRENT_STATUS_LABELS = {
    "video_prompt.ready": "待生成视频提示词",
    "video.generated": "待生成视频片段",
    "visual_handoff.generated": "待生成视觉交接图",
    "storyboard.generated": "待生成分镜图",
    "director_plan.generated": "待生成分镜脚本",
    "cinematic_script.generated": "待生成片段剧本",
    "asset_references.linked": "待绑定资产引用",
    "workflow.ready": "待生成画布工作链",
    "episode.source_ready": "待提交原文",
}

_EPISODE_READY_STATUS_LABEL = "当前集全部视频片段已生成"

_WORKFLOW_NEXT_ACTION_BY_STATE = {
    "video_prompt.ready": "generate_video_prompt",
    "video.generated": "generate_video",
    "storyboard.generated": "generate_storyboard",
    "director_plan.generated": "generate_director_plan",
    "cinematic_script.generated": "generate_cinematic_script",
    "asset_references.linked": "link_assets",
    "workflow.ready": "build_workflow_chain",
    "episode.source_ready": "submit_episode_source",
}

def _episode_file_path(project_id: str, episode_id: str, filename: str) -> Path:
    episode_key = str(episode_id or "").strip()
    if not episode_key:
        raise ValueError("缺少 episodeId")
    return _project_dir(project_id) / "episodes" / episode_key / filename


def _episode_production_status_path(project_id: str, episode_id: str) -> Path:
    return _episode_file_path(project_id, episode_id, "episode_production_status.json")


def _episode_review_results_path(project_id: str, episode_id: str) -> Path:
    return _episode_file_path(project_id, episode_id, "review_results.json")


def _production_status_sidebar_label(status: dict[str, Any]) -> str:
    overall_status = str(status.get("overallStatus") or "").strip()
    current_state = str(status.get("currentState") or "").strip()
    if overall_status == "ready":
        return _EPISODE_READY_STATUS_LABEL
    if overall_status == "blocked":
        if current_state:
            return _EPISODE_CURRENT_STATUS_LABELS.get(current_state, current_state)
        blocked_by = status.get("blockedBy") if isinstance(status.get("blockedBy"), list) else []
        for item in blocked_by:
            text = _text_items(item)
            if text:
                return f"生产阻塞：{text[0]}"
        return "生产阻塞，需处理"
    return _EPISODE_CURRENT_STATUS_LABELS.get(current_state, current_state)


def _sync_project_episode_status(project_id: str, episode_id: str, status: dict[str, Any]) -> bool:
    label = _production_status_sidebar_label(status)
    if not label:
        return False
    meta_path = _project_dir(project_id) / "project.json"
    meta = _read_json(meta_path, {})
    episodes = meta.get("episodes") if isinstance(meta.get("episodes"), list) else []
    changed = False
    next_episodes: list[dict[str, Any]] = []
    for item in episodes:
        if not isinstance(item, dict):
            continue
        row = copy.deepcopy(item)
        if str(row.get("id") or "") == str(episode_id):
            if row.get("status") != label:
                row["status"] = label
                changed = True
        next_episodes.append(row)
    if changed:
        meta["episodes"] = next_episodes
        meta["updated_at"] = _now()
        _write_json(meta_path, meta)
    return changed


def _status_from_completed_states(completed_states: list[str], blocked_states: list[str] | None = None) -> str:
    blocked = set(blocked_states or [])
    completed = set(completed_states or [])
    if blocked:
        return "blocked"
    if "video.generated" in completed:
        return "completed"
    if "storyboard.generated" in completed:
        return "storyboard_generated"
    if "director_plan.generated" in completed:
        return "director_plan_generated"
    if "cinematic_script.generated" in completed:
        return "cinematic_script_generated"
    return "draft"


def _sync_workflow_status_fields(workflow: dict[str, Any], status: dict[str, Any]) -> bool:
    """Keep canvas metadata aligned with the persisted production status."""
    changed = False
    current_state = str(status.get("currentState") or "").strip()
    state = workflow.get("state") if isinstance(workflow.get("state"), dict) else {}
    if str(status.get("overallStatus") or "").strip() == "ready":
        next_action = str(status.get("nextAction") or "review_or_continue_next_episode")
    else:
        next_action = _WORKFLOW_NEXT_ACTION_BY_STATE.get(current_state, state.get("nextAction") or "")
    if current_state and state.get("productionState") != current_state:
        state["productionState"] = current_state
        changed = True
    if next_action and state.get("nextAction") != next_action:
        state["nextAction"] = next_action
        changed = True
    if workflow.get("state") != state:
        workflow["state"] = state
        changed = True

    route_state_by_id = {
        str(item.get("routeId") or ""): item
        for item in status.get("routeStates") or []
        if isinstance(item, dict) and str(item.get("routeId") or "")
    }
    for chain_status in (status.get("independentWorkChains") or {}).values():
        for row in chain_status.get("routeStates") or []:
            if row.get("routeId"):
                route_state_by_id[str(row["routeId"])] = row
    route_status_by_chain: dict[str, list[str]] = {}
    for route in workflow.get("routes") or []:
        if not isinstance(route, dict):
            continue
        route_id = str(route.get("id") or "").strip()
        route_state = route_state_by_id.get(route_id, {})
        completed_states = [
            str(item)
            for item in route_state.get("completedStates") or []
            if str(item)
        ]
        blocked_states = [
            str(item)
            for item in route_state.get("blockedStates") or []
            if str(item)
        ]
        next_status = _status_from_completed_states(completed_states, blocked_states)
        if route.get("status") != next_status:
            route["status"] = next_status
            changed = True
        work_chain_id = str(route.get("workChainId") or "").strip()
        if work_chain_id:
            route_status_by_chain.setdefault(work_chain_id, []).append(next_status)

    for chain in workflow.get("workChains") or []:
        if not isinstance(chain, dict):
            continue
        chain_id = str(chain.get("id") or "").strip()
        route_statuses = route_status_by_chain.get(chain_id, [])
        if route_statuses:
            if any(item == "blocked" for item in route_statuses):
                next_status = "blocked"
            elif all(item == "completed" for item in route_statuses):
                next_status = "completed"
            else:
                next_status = route_statuses[0]
        else:
            next_status = _status_from_completed_states(
                [
                    str(item)
                    for item in status.get("completedStates") or []
                    if str(item)
                ],
                [
                    str(item.get("state") or item.get("id") or "")
                    for item in status.get("blockedBy") or []
                    if isinstance(item, dict)
                ],
            )
        if chain.get("status") != next_status:
            chain["status"] = next_status
            changed = True
    return changed


def _sync_workflow_status_records(
    workflow: dict[str, Any],
    status: dict[str, Any],
) -> dict[str, Any]:
    before_state = copy.deepcopy(workflow.get("state") if isinstance(workflow.get("state"), dict) else {})
    before_routes = {
        str(route.get("id") or "").strip(): route.get("status")
        for route in workflow.get("routes") or []
        if isinstance(route, dict) and str(route.get("id") or "").strip()
    }
    before_work_chains = {
        str(chain.get("id") or "").strip(): chain.get("status")
        for chain in workflow.get("workChains") or []
        if isinstance(chain, dict) and str(chain.get("id") or "").strip()
    }
    if not _sync_workflow_status_fields(workflow, status):
        return {"state": {}, "routeStatuses": {}, "workChainStatuses": {}}
    state = workflow.get("state") if isinstance(workflow.get("state"), dict) else {}
    route_statuses = {
        str(route["id"]): route["status"]
        for route in workflow.get("routes") or []
        if isinstance(route, dict)
        and str(route.get("id") or "").strip()
        and before_routes.get(str(route.get("id") or "").strip()) != route["status"]
    }
    work_chain_statuses = {
        str(chain["id"]): chain["status"]
        for chain in workflow.get("workChains") or []
        if isinstance(chain, dict)
        and str(chain.get("id") or "").strip()
        and before_work_chains.get(str(chain.get("id") or "").strip()) != chain["status"]
    }
    return {
        "state": {key: state[key] for key in ("productionState", "nextAction") if key in state and state[key] != before_state.get(key)},
        "routeStatuses": route_statuses,
        "workChainStatuses": work_chain_statuses,
    }


def _episode_source_files_ready(project_id: str, episode_id: str) -> bool:
    episode_dir = _project_dir(project_id) / "episodes" / str(episode_id or "").strip()
    return (episode_dir / "source.txt").exists() and (episode_dir / "source_ref.json").exists()


def _text_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        return [item for row in value for item in _text_items(row)]
    if isinstance(value, dict):
        for key in ("message", "text", "title", "summary", "reason", "suggestion"):
            items = _text_items(value.get(key))
            if items:
                return items
    return []


def _review_severity(value: Any, default: str = "info") -> str:
    text = str(value or default).strip().lower()
    aliases = {
        "blocking": "blocker",
        "error": "blocker",
        "fatal": "blocker",
        "warn": "warning",
        "notice": "info",
    }
    return aliases.get(text, text) if aliases.get(text, text) in _REVIEW_SEVERITIES else default


def _short_hash(*values: Any) -> str:
    text = "|".join(str(value or "") for value in values)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _safe_issue_id(value: Any, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(value or "").strip()).strip("_")
    return text or fallback


def _normalize_review_issue(
    value: Any,
    *,
    default_severity: str,
    source: str,
    index: int,
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    context = context or {}
    row = copy.deepcopy(value) if isinstance(value, dict) else {}
    message_items = _text_items(value)
    message = message_items[0] if message_items else ""
    if not message:
        return None
    severity = _review_severity(row.get("severity"), default_severity)
    category = str(row.get("category") or context.get("category") or source).strip()
    node_id = str(row.get("nodeId") or row.get("node_id") or context.get("nodeId") or "").strip()
    node_type = str(row.get("nodeType") or row.get("node_type") or context.get("nodeType") or "").strip()
    route_id = str(row.get("routeId") or row.get("route_id") or context.get("routeId") or "").strip()
    segment_id = str(row.get("segmentId") or row.get("segment_id") or context.get("segmentId") or "").strip()
    issue_id = _safe_issue_id(
        row.get("id") or row.get("issueId") or row.get("issue_id"),
        f"{source}:{severity}:{_short_hash(node_id, node_type, category, message, index)}",
    )
    normalized = {
        "id": issue_id,
        "severity": severity,
        "category": category,
        "message": message,
        "source": str(row.get("source") or source),
    }
    for key, item in {
        "nodeId": node_id,
        "nodeType": node_type,
        "routeId": route_id,
        "segmentId": segment_id,
        "createdAt": row.get("createdAt") or row.get("created_at"),
        "status": row.get("status"),
    }.items():
        if item not in (None, "", [], {}):
            normalized[key] = item
    return normalized


def _workflow_review_issues(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
        preflight = quality.get("modelPreflight") if isinstance(quality.get("modelPreflight"), dict) else {}
        context = {
            "nodeId": node.get("id"),
            "nodeType": node.get("type"),
            "routeId": node.get("routeId") or data.get("routeId"),
            "segmentId": node.get("segmentId") or data.get("segmentId"),
            "category": "model_capability",
        }
        for item in preflight.get("blockingIssues") or []:
            issue = _normalize_review_issue(
                item,
                default_severity="blocker",
                source="workflow_preflight",
                index=len(issues),
                context=context,
            )
            if issue:
                issues.append(issue)
        for item in preflight.get("warnings") or []:
            issue = _normalize_review_issue(
                item,
                default_severity="warning",
                source="workflow_preflight",
                index=len(issues),
                context=context,
            )
            if issue:
                issues.append(issue)

        generation_config = (
            data.get("generationConfig") if isinstance(data.get("generationConfig"), dict) else {}
        )
        quality_review = (
            generation_config.get("qualityReview")
            if isinstance(generation_config.get("qualityReview"), dict)
            else {}
        )
        for item in quality_review.get("suggestions") or []:
            issue = _normalize_review_issue(
                item,
                default_severity="info",
                source="node_quality_review",
                index=len(issues),
                context={**context, "category": "manual_quality_review"},
            )
            if issue:
                issues.append(issue)
    return issues


def _merge_issues(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for item in group:
            issue_id = str(item.get("id") or "").strip()
            if not issue_id:
                continue
            if issue_id in merged:
                merged[issue_id] = {**merged[issue_id], **copy.deepcopy(item)}
            else:
                merged[issue_id] = copy.deepcopy(item)
    return list(merged.values())


def _normalize_waivers(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    waivers: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        issue_id = str(row.get("issueId") or row.get("issue_id") or row.get("id") or "").strip()
        reason = str(row.get("reason") or "").strip()
        if not issue_id or not reason:
            continue
        waivers.append(
            {
                "id": _safe_issue_id(
                    row.get("waiverId") or row.get("waiver_id") or row.get("id"),
                    f"waiver_{index + 1:03d}",
                ),
                "issueId": issue_id,
                "reason": reason,
                "waivedBy": str(row.get("waivedBy") or row.get("waived_by") or "user"),
                "waivedAt": row.get("waivedAt") or row.get("waived_at") or _now(),
            }
        )
    return waivers


def _apply_issue_waivers(
    issues: list[dict[str, Any]],
    waivers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    waiver_index = {str(item.get("issueId") or ""): item for item in waivers}
    result: list[dict[str, Any]] = []
    for issue in issues:
        issue_id = str(issue.get("id") or "")
        waiver = waiver_index.get(issue_id)
        if waiver:
            issue = {
                **copy.deepcopy(issue),
                "status": "waived",
                "waived": True,
                "waiver": copy.deepcopy(waiver),
            }
        result.append(issue)
    return result


def _review_status(explicit_status: str, issues: list[dict[str, Any]]) -> str:
    active_blockers = [
        item
        for item in issues
        if item.get("severity") == "blocker" and item.get("status") != "waived"
    ]
    if active_blockers:
        return "blocked"
    allowed = {"pending", "pass", "passed", "warning", "waived"}
    if explicit_status in allowed and explicit_status != "passed":
        return explicit_status
    if explicit_status == "passed":
        return "pass"
    if any(item.get("severity") == "warning" and item.get("status") != "waived" for item in issues):
        return "warning"
    return "pending"


def _normalize_review_results(
    project_id: str,
    episode_id: str,
    value: Any,
    *,
    workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = copy.deepcopy(value) if isinstance(value, dict) else {}
    workflow = workflow if isinstance(workflow, dict) else get_canvas_workflow_projection(project_id, episode_id)

    computed = _merge_issues(_workflow_review_issues(workflow))
    saved_issues = []
    for index, item in enumerate(payload.get("issues") if isinstance(payload.get("issues"), list) else []):
        issue = _normalize_review_issue(
            item,
            default_severity=_review_severity((item or {}).get("severity") if isinstance(item, dict) else None),
            source=str((item or {}).get("source") or "manual_review") if isinstance(item, dict) else "manual_review",
            index=index,
        )
        if issue:
            saved_issues.append(issue)
    issues = _merge_issues(computed, saved_issues)
    waivers = _normalize_waivers(payload.get("waivers"))
    issues = _apply_issue_waivers(issues, waivers)
    blockers = [
        copy.deepcopy(item)
        for item in issues
        if item.get("severity") == "blocker" and item.get("status") != "waived"
    ]
    warnings = [
        copy.deepcopy(item)
        for item in issues
        if item.get("severity") == "warning" and item.get("status") != "waived"
    ]
    infos = [
        copy.deepcopy(item)
        for item in issues
        if item.get("severity") == "info" and item.get("status") != "waived"
    ]
    status = _review_status(str(payload.get("status") or "").strip(), issues)
    return {
        "schemaVersion": 1,
        "projectId": project_id,
        "episodeId": episode_id,
        "status": status,
        "issues": issues,
        "blockers": blockers,
        "warnings": warnings,
        "infos": infos,
        "blockerCount": len(blockers),
        "warningCount": len(warnings),
        "infoCount": len(infos),
        "waivers": waivers,
        "reviewedAt": payload.get("reviewedAt") or payload.get("reviewed_at"),
        "reviewedBy": payload.get("reviewedBy") or payload.get("reviewed_by"),
        "updatedAt": payload.get("updatedAt") or payload.get("updated_at") or _now(),
    }


def get_episode_review_results(project_id: str, episode_id: str) -> dict[str, Any]:
    workflow = get_canvas_workflow_projection(project_id, episode_id)
    saved = _read_json(_episode_review_results_path(project_id, episode_id), {})
    review = _normalize_review_results(project_id, episode_id, saved, workflow=workflow)
    return {"success": True, "review": review}


def save_episode_review_results(
    project_id: str,
    episode_id: str,
    review: dict[str, Any] | None,
) -> dict[str, Any]:
    current = get_episode_review_results(project_id, episode_id).get("review") or {}
    payload = {**current, **(copy.deepcopy(review) if isinstance(review, dict) else {})}
    if str(payload.get("status") or "") in {"pass", "passed", "warning", "waived"}:
        payload["reviewedAt"] = payload.get("reviewedAt") or _now()
        payload["reviewedBy"] = payload.get("reviewedBy") or "user"
    normalized = _normalize_review_results(project_id, episode_id, payload)
    normalized["updatedAt"] = _now()
    _write_json(_episode_review_results_path(project_id, episode_id), normalized)
    status_result = update_episode_production_status(project_id, episode_id)
    return {
        "success": True,
        "review": normalized,
        "productionStatus": status_result.get("status"),
        "changedResources": ["review_results", "episode_production_status", "canvas_projection"],
    }


def waive_review_issue(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    issue_id = str(data.get("issueId") or data.get("issue_id") or data.get("id") or "").strip()
    reason = str(data.get("reason") or data.get("waiverReason") or data.get("waiver_reason") or "").strip()
    if not issue_id:
        raise ValueError("缺少 issueId")
    if not reason:
        raise ValueError("请填写质检豁免原因")
    review = get_episode_review_results(project_id, episode_id).get("review") or {}
    waivers = _normalize_waivers(review.get("waivers"))
    waivers = [item for item in waivers if item.get("issueId") != issue_id]
    waivers.append(
        {
            "id": f"waiver_{_short_hash(issue_id, reason, _now())}",
            "issueId": issue_id,
            "reason": reason,
            "waivedBy": str(data.get("waivedBy") or data.get("waived_by") or "user"),
            "waivedAt": _now(),
        }
    )
    review["waivers"] = waivers
    review["status"] = "waived"
    return save_episode_review_results(project_id, episode_id, review)


_NODE_INCOMPLETE_STATUSES = {
    "blocked",
    "canceled",
    "cancelled",
    "draft",
    "failed",
    "idle",
    "paused",
    "pending_generation",
    "preflight_failed",
    "processing",
    "queued",
    "running",
    "waiting",
    "waiting_upstream",
}

def _node_status(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(data.get("status") or node.get("status") or "").strip()


def _episode_versions_by_node_id(project_id: str, episode_id: str) -> dict[str, dict[str, dict[str, Any]]]:
    by_node: dict[str, dict[str, dict[str, Any]]] = {}
    for item in read_episode_card_results(project_id, episode_id):
        node_id = str(item.get("nodeId") or "").strip()
        version_id = str(item.get("id") or "").strip()
        if node_id and version_id:
            by_node.setdefault(node_id, {})[version_id] = item
    return by_node


def _node_version(
    node: dict[str, Any],
    versions_by_node_id: dict[str, dict[str, dict[str, Any]]],
    version_id: str,
) -> dict[str, Any] | None:
    node_id = str(node.get("id") or "").strip()
    if not node_id or not version_id:
        return None
    return versions_by_node_id.get(node_id, {}).get(version_id)


def _node_active_version(
    node: dict[str, Any],
    versions_by_node_id: dict[str, dict[str, dict[str, Any]]],
) -> tuple[str, dict[str, Any] | None]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    version_id = str(data.get("activeVersionId") or data.get("active_version_id") or "").strip()
    return version_id, _node_version(node, versions_by_node_id, version_id)


def _node_quality_block_message(
    node: dict[str, Any],
    versions_by_node_id: dict[str, dict[str, dict[str, Any]]],
    *,
    version_id: str = "",
) -> str:
    if version_id:
        version = _node_version(node, versions_by_node_id, version_id)
    else:
        version_id, version = _node_active_version(node, versions_by_node_id)
    return workflow_node_quality_block_message(node, version=version, version_id=version_id)


def _node_has_active_version(
    node: dict[str, Any],
    versions_by_node_id: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    versions_by_node_id = versions_by_node_id or {}
    active_version_id, version = _node_active_version(node, versions_by_node_id)
    if not active_version_id:
        return False
    if isinstance(version, dict):
        version_status = str(version.get("status") or "").strip().lower()
        if version_status in _NODE_INCOMPLETE_STATUSES:
            return False
    elif _node_status(node).lower() in _NODE_INCOMPLETE_STATUSES:
        return False
    if workflow_node_quality_blocks(node, version=version, version_id=active_version_id):
        return False
    return True

_IMAGE_REFERENCE_FILE_RE = re.compile(r"\.(png|jpe?g|webp|gif|bmp|tiff?|avif)(?:[?#].*)?$", re.I)
_VIDEO_REFERENCE_FILE_RE = re.compile(r"\.(mp4|m4v|mov|webm|avi|mkv)(?:[?#].*)?$", re.I)
_IMAGE_REFERENCE_SLOTS = {
    "custom_image",
    "frame_reference",
    "storyboard_image",
    "character_reference",
    "creature_reference",
    "scene_reference",
    "prop_reference",
    "visual_handoff_reference",
}
_IMAGE_REFERENCE_MEDIA_BINDING_KEYS = (
    "activeMediaVersionId",
    "active_media_version_id",
    "activeVersionId",
    "active_version_id",
    "mediaVersionId",
    "media_version_id",
    "sourceVersionId",
    "source_version_id",
    "versionId",
    "version_id",
    "mediaId",
    "media_id",
    "path",
    "file",
    "filePath",
    "file_path",
    "relativePath",
    "relative_path",
    "url",
    "preview",
    "previewUrl",
    "preview_url",
    "previewSrc",
    "preview_src",
    "thumbnail",
    "thumbnailUrl",
    "thumbnail_url",
    "dataUrl",
    "data_url",
)
_IMAGE_REFERENCE_NESTED_MEDIA_BINDING_KEYS = (
    "id",
    *_IMAGE_REFERENCE_MEDIA_BINDING_KEYS,
)
def _is_image_reference_type(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text == "image" or text.startswith("image/")


def _is_video_reference_type(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text == "video" or text.startswith("video/")


def _reference_record_path(*records: Any) -> str:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in (
            "path",
            "file",
            "filePath",
            "file_path",
            "relativePath",
            "relative_path",
            "url",
            "preview",
            "previewUrl",
            "preview_url",
            "previewSrc",
            "preview_src",
            "thumbnail",
            "thumbnailUrl",
            "thumbnail_url",
            "dataUrl",
            "data_url",
        ):
            text = str(record.get(key) or "").strip()
            if text:
                return text
    return ""


def _reference_record_media_kind(*records: Any) -> str:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in (
            "mediaKind",
            "media_kind",
            "mediaType",
            "media_type",
            "kind",
            "mimeType",
            "mime_type",
        ):
            value = record.get(key)
            if _is_video_reference_type(value):
                return "video"
            if _is_image_reference_type(value):
                return "image"
    path = _reference_record_path(*records)
    if _VIDEO_REFERENCE_FILE_RE.search(path):
        return "video"
    if _IMAGE_REFERENCE_FILE_RE.search(path):
        return "image"
    return ""


def _reference_record_has_media_binding(*records: Any, nested: bool = False) -> bool:
    keys = _IMAGE_REFERENCE_NESTED_MEDIA_BINDING_KEYS if nested else _IMAGE_REFERENCE_MEDIA_BINDING_KEYS
    for record in records:
        if not isinstance(record, dict):
            continue
        if any(str(record.get(key) or "").strip() for key in keys):
            return True
    return False


def _image_reference_record(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    slot = _canonical_workflow_slot(value.get("slot") or value.get("targetSlot") or value.get("target_slot"))
    if slot and slot not in _IMAGE_REFERENCE_SLOTS:
        return False
    source_node_type = str(value.get("sourceNodeType") or value.get("source_node_type") or "").strip()
    if source_node_type in {"video.result", *VIDEO_TASK_NODE_TYPES}:
        return False
    media = value.get("media") if isinstance(value.get("media"), dict) else {}
    storage = value.get("storage") if isinstance(value.get("storage"), dict) else {}
    media_kind = _reference_record_media_kind(value, media, storage)
    if source_node_type in {"asset.image", "storyboard.image"}:
        if media_kind == "video":
            return False
        if media_kind == "image":
            return True
        return _reference_record_has_media_binding(value) or _reference_record_has_media_binding(
            media,
            storage,
            nested=True,
        )
    if (
        _is_image_reference_type(value.get("mediaType"))
        or _is_image_reference_type(value.get("media_type"))
        or _is_image_reference_type(value.get("kind"))
    ):
        return True
    mime_type = str(value.get("mimeType") or value.get("mime_type") or "").strip().lower()
    if mime_type.startswith("image/"):
        return True
    if media_kind == "video":
        return False
    if media_kind == "image":
        return True
    for record in (media, storage):
        if (
            _is_image_reference_type(record.get("kind"))
            or _is_image_reference_type(record.get("mediaType"))
            or _is_image_reference_type(record.get("media_type"))
        ):
            return True
    path = str(
        value.get("path")
        or value.get("file")
        or value.get("filePath")
        or value.get("relativePath")
        or value.get("relative_path")
        or media.get("path")
        or media.get("file")
        or media.get("filePath")
        or media.get("relativePath")
        or media.get("relative_path")
        or storage.get("path")
        or storage.get("file")
        or storage.get("filePath")
        or storage.get("relativePath")
        or storage.get("relative_path")
        or ""
    ).strip()
    return bool(path and _IMAGE_REFERENCE_FILE_RE.search(path))


def _workflow_node_can_supply_image_reference(node: dict[str, Any] | None) -> bool:
    if not isinstance(node, dict):
        return False
    node_type = _node_type(node)
    if node_type in {"video.result", *VIDEO_TASK_NODE_TYPES}:
        return False
    if node_type not in {"asset.image", "storyboard.image", "media.external"}:
        return False
    if node_type == "media.external":
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        media = data.get("media") if isinstance(data.get("media"), dict) else {}
        storage = data.get("storage") if isinstance(data.get("storage"), dict) else {}
        return _reference_record_media_kind(data, media, storage) == "image"
    return True


def _video_task_has_ready_manual_image_reference(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
) -> bool:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    input_links = data.get("inputLinks")
    if not isinstance(input_links, list):
        return False
    keyframe_task = _node_type(node) == "video.keyframe"
    for item in input_links:
        if not isinstance(item, dict):
            continue
        if keyframe_task and (
            _canonical_workflow_slot(item.get("slot") or item.get("targetSlot") or item.get("target_slot")) != "frame_reference"
            or item.get("frameRole") == "last_frame"
            or item.get("useNativeFrame") is False
        ):
            continue
        source_node_id = str(item.get("sourceNodeId") or item.get("source_node_id") or "").strip()
        if not source_node_id:
            continue
        source_node = _workflow_node_by_id(workflow, source_node_id) if source_node_id else None
        if not isinstance(source_node, dict) or not _workflow_node_can_supply_image_reference(source_node):
            continue
        try:
            if workflow_current_media_version_has_media(
                project_id,
                episode_id,
                workflow,
                source_node_id,
            ):
                return True
        except Exception:
            continue
    return False


def _video_task_duration_seconds(value: Any) -> float | None:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    return duration if duration > 0 else None


def _video_task_card_truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _video_task_card_preparation_issues(
    node: dict[str, Any],
    *,
    has_manual_image_reference: bool | None = None,
    is_work_chain_node: bool | None = None,
    video_task_scope: str | None = None,
) -> list[str]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    if _node_type(node) == "video.character_replace":
        issues = []
        if not has_manual_image_reference:
            issues.append("角色替换请先关联至少一张角色图")
        if not any(isinstance(row, dict) and row.get("slot", row.get("targetSlot")) == "reference_video"
                   and row.get("enabled") is not False for row in data.get("inputLinks", [])):
            issues.append("角色替换请先关联一段源视频")
        if not _video_task_duration_seconds(data.get("durationSeconds")):
            issues.append("角色替换请先设置时长")
        return issues
    video_task_card = data.get("videoTaskCard") if isinstance(data.get("videoTaskCard"), dict) else {}
    video_prompt = ""
    video_prompt_type_invalid = False
    for prompt_value in (
        video_task_card.get("finalVideoPrompt"),
    ):
        if prompt_value in (None, ""):
            continue
        if not isinstance(prompt_value, str):
            video_prompt_type_invalid = True
            break
        video_prompt = prompt_value.strip()
        if video_prompt:
            break
    normalized_video_task_scope = str(video_task_scope or "").strip().lower()
    if video_task_scope is None:
        normalized_video_task_scope = workflow_video_task_scope({"nodes": [node]}, node)
    if normalized_video_task_scope == "work_chain":
        is_work_chain_node = True
    elif normalized_video_task_scope == "standalone":
        is_work_chain_node = False
    else:
        return ["视频生成缺少作用域标识，请重新创建任务卡"]
    issues: list[str] = []
    if is_work_chain_node:
        if video_prompt_type_invalid:
            issues.append("视频生成视频提示词类型异常，请重新保存视频生成")
        elif not video_prompt:
            issues.append("工作链视频生成缺少视频提示词，请先点击“生成视频提示词”")
        return issues
    if not is_work_chain_node:
        manual_image_ready = bool(has_manual_image_reference)
        if not manual_image_ready:
            issues.append(
                "首尾帧视频生成请先关联并开启原生首帧"
                if _node_type(node) == "video.keyframe" else "独立视频生成请先手动关联至少一张图片资产"
            )
    if video_prompt_type_invalid:
        issues.append("视频生成视频提示词类型异常，请重新保存视频生成")
    elif not video_prompt:
        issues.append("独立视频生成请先填写并保存视频提示词")
    duration_value = data.get("durationSeconds")
    duration_seconds = _video_task_duration_seconds(duration_value)
    if duration_value in (None, ""):
        issues.append("独立视频生成请先设置时长")
    elif duration_seconds is None:
        issues.append("视频生成视频时长必须是大于 0 的秒数")
    return issues


def _node_has_winner_version(
    node: dict[str, Any],
    versions_by_node_id: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    versions_by_node_id = versions_by_node_id or {}
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    active_version_id = str(data.get("activeVersionId") or data.get("active_version_id") or "").strip()
    winner_version_id = str(data.get("winnerVersionId") or data.get("winner_version_id") or "").strip()
    reason = str(
        data.get("selectionReason")
        or data.get("selection_reason")
        or (data.get("variantSelection") if isinstance(data.get("variantSelection"), dict) else {}).get("reason")
        or ""
    ).strip()
    if (
        not winner_version_id
        or winner_version_id != active_version_id
        or not (reason and reason != "manual_winner_selected")
    ):
        return False
    version = _node_version(node, versions_by_node_id, winner_version_id)
    return not workflow_node_quality_blocks(node, version=version, version_id=winner_version_id)


def _node_route_id(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(node.get("routeId") or data.get("routeId") or "").strip()


def _node_work_chain_id(node: dict[str, Any] | None) -> str:
    return str((node or {}).get("workChainId") or "").strip()


def _node_type(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(
        node.get("type")
        or data.get("eyebrow")
        or data.get("nodeType")
        or data.get("node_type")
        or ""
    ).strip()


_GENERATED_WORK_CHAIN_NODE_TYPES = {
    "prompt.storyboard",
    "director.board",
    "storyboard.image",
    "video.storyboard",
    "video.result",
}


def _workflow_declared_work_chain_ids(workflow: dict[str, Any]) -> set[str]:
    work_chain_ids: set[str] = set()
    for chain in workflow.get("workChains") if isinstance(workflow.get("workChains"), list) else []:
        if not isinstance(chain, dict):
            continue
        work_chain_id = str(chain.get("id") or chain.get("workChainId") or "").strip()
        if work_chain_id:
            work_chain_ids.add(work_chain_id)
    for route in workflow.get("routes") if isinstance(workflow.get("routes"), list) else []:
        if not isinstance(route, dict):
            continue
        work_chain_id = str(route.get("workChainId") or "").strip()
        if work_chain_id:
            work_chain_ids.add(work_chain_id)
    return work_chain_ids


def _workflow_has_generated_work_chain(workflow: dict[str, Any], nodes: list[dict[str, Any]] | None = None) -> bool:
    nodes = [item for item in (nodes if isinstance(nodes, list) else workflow.get("nodes") or []) if isinstance(item, dict)]
    if not nodes:
        return False
    work_chain_ids = _workflow_declared_work_chain_ids(workflow)
    for node in nodes:
        work_chain_id = _node_work_chain_id(node)
        if work_chain_id:
            work_chain_ids.add(work_chain_id)
    for work_chain_id in work_chain_ids:
        node_types = {
            _node_type(node)
            for node in nodes
            if _node_work_chain_id(node) == work_chain_id
        }
        if _GENERATED_WORK_CHAIN_NODE_TYPES.issubset(node_types):
            return True
    return False


def _node_strategy(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(node.get("strategy") or data.get("strategy") or "").strip()


def _has_asset_refs(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_asset_refs(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_asset_refs(item) for item in value)
    return bool(str(value or "").strip())


def _workflow_routes(workflow: dict[str, Any], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    routes = [copy.deepcopy(item) for item in workflow.get("routes") or [] if isinstance(item, dict)]
    if routes:
        return routes
    route_ids: list[str] = []
    for node in nodes:
        route_id = _node_route_id(node)
        if route_id and route_id not in route_ids:
            route_ids.append(route_id)
    if route_ids:
        return [
            {
                "id": route_id,
                "strategy": next((_node_strategy(node) for node in nodes if _node_route_id(node) == route_id and _node_strategy(node)), "storyboard_multi_shot"),
            }
            for route_id in route_ids
        ]
    return [{"id": "__workflow__", "strategy": "storyboard_multi_shot"}] if nodes else []


def _route_nodes(nodes: list[dict[str, Any]], route_id: str) -> list[dict[str, Any]]:
    if route_id == "__workflow__":
        return nodes
    return [node for node in nodes if _node_route_id(node) == route_id]


def _route_blocker(route_id: str, strategy: str, category: str, message: str, *, node: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": f"{category}:{route_id}:{node.get('id') if isinstance(node, dict) else 'route'}",
        "severity": "blocker",
        "category": category,
        "message": message,
        "routeId": None if route_id == "__workflow__" else route_id,
        "strategy": strategy,
        "nodeId": node.get("id") if isinstance(node, dict) else None,
        "nodeType": node.get("type") if isinstance(node, dict) else None,
    }


def _route_step_status(
    *,
    route_id: str,
    strategy: str,
    skipped: bool = False,
    completed: bool = False,
    blockers: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    route_completed = bool(completed or skipped)
    return {
        "routeId": None if route_id == "__workflow__" else route_id,
        "strategy": strategy,
        "completed": route_completed,
        "skipped": bool(skipped),
        "status": "skipped" if skipped else "completed" if completed else "blocked" if blockers else "pending",
        "blockers": copy.deepcopy(blockers or []),
        "warnings": copy.deepcopy(warnings or []),
        "blockerCount": len(blockers or []),
        "warningCount": len(warnings or []),
    }


def _aggregate_route_statuses(statuses: list[dict[str, Any]]) -> tuple[bool, bool, list[dict[str, Any]]]:
    if not statuses:
        return False, False, []
    completed = all(bool(item.get("completed")) for item in statuses)
    skipped = completed and all(bool(item.get("skipped")) for item in statuses)
    blockers: list[dict[str, Any]] = []
    for item in statuses:
        blockers.extend([copy.deepcopy(blocker) for blocker in item.get("blockers") or [] if isinstance(blocker, dict)])
    return completed, skipped, blockers


def _aggregate_route_warnings(statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for item in statuses:
        warnings.extend([copy.deepcopy(warning) for warning in item.get("warnings") or [] if isinstance(warning, dict)])
    return warnings


def _route_status_route_key(status: dict[str, Any]) -> str:
    return str(status.get("routeId") or "__workflow__").strip() or "__workflow__"


def _completed_video_route_ids(video_route_statuses: list[dict[str, Any]]) -> set[str]:
    return {
        _route_status_route_key(item)
        for item in video_route_statuses
        if isinstance(item, dict) and bool(item.get("completed"))
    }


def _skip_missing_route_statuses(
    statuses: list[dict[str, Any]],
    inactive_route_ids: set[str],
) -> list[dict[str, Any]]:
    if not inactive_route_ids:
        return statuses
    normalized: list[dict[str, Any]] = []
    for item in statuses:
        if (not isinstance(item, dict) or _route_status_route_key(item) not in inactive_route_ids or item.get("completed")
                or any(issue.get("category") == "script_continuity" for issue in item.get("blockers") or [])):
            normalized.append(item)
            continue
        normalized_item = copy.deepcopy(item)
        normalized_item["completed"] = True
        normalized_item["skipped"] = True
        normalized_item["status"] = "skipped"
        normalized_item["blockers"] = []
        normalized_item["blockerCount"] = 0
        normalized.append(normalized_item)
    return normalized


_STORYBOARD_VIDEO_SLOTS = {"storyboard_image"}
_WORKFLOW_VIDEO_TASK_NODE_TYPES = VIDEO_TASK_NODE_TYPES
_WORKFLOW_VIDEO_RESULT_NODE_TYPE = "video.result"
_VISUAL_HANDOFF_MARKERS = {"visual_handoff", "visual_handoff_reference"}
_VISUAL_HANDOFF_SOURCE_TYPES = {
    "visual_handoff_generation",
    "cross_episode_visual_handoff",
}


def _is_workflow_video_task_node(node: dict[str, Any]) -> bool:
    node_type = str(node.get("type") or "").strip()
    return node_type in _WORKFLOW_VIDEO_TASK_NODE_TYPES


def _is_workflow_video_result_node(node: dict[str, Any]) -> bool:
    return _node_type(node) == _WORKFLOW_VIDEO_RESULT_NODE_TYPE


def _video_result_owner_node_id(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(
        data.get("resultOfNodeId")
        or data.get("result_of_node_id")
        or data.get("sourceNodeId")
        or data.get("source_node_id")
        or ""
    ).strip()


def _video_result_nodes_for_task(
    route_nodes: list[dict[str, Any]],
    video_node: dict[str, Any],
) -> list[dict[str, Any]]:
    video_node_id = str(video_node.get("id") or "").strip()
    if not video_node_id:
        return []
    return [
        node
        for node in route_nodes
        if _is_workflow_video_result_node(node)
        and _video_result_owner_node_id(node) == video_node_id
    ]


def _video_result_has_generated_media(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
    versions_by_node_id: dict[str, dict[str, dict[str, Any]]],
) -> bool:
    if not _node_has_active_version(node, versions_by_node_id):
        return False
    node_id = str(node.get("id") or "").strip()
    return bool(
        node_id
        and workflow_current_media_version_has_media(project_id, episode_id, workflow, node_id)
    )


def _node_data_is_visual_handoff_asset(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return False
    markers = (
        data.get("mediaPurpose"),
        data.get("media_purpose"),
        data.get("preferredTargetSlot"),
        data.get("preferred_target_slot"),
        data.get("assetKind"),
        data.get("asset_kind"),
        data.get("assetType"),
        data.get("asset_type"),
    )
    if any(str(value or "").strip() in _VISUAL_HANDOFF_MARKERS for value in markers):
        return True
    source_type = str(data.get("sourceType") or data.get("source_type") or "").strip()
    return source_type in _VISUAL_HANDOFF_SOURCE_TYPES


def _is_visual_handoff_result_node(node: dict[str, Any]) -> bool:
    if _node_type(node) != "asset.image":
        return False
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return _node_data_is_visual_handoff_asset(data)


def _visual_handoff_result_has_generated_media(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
    versions_by_node_id: dict[str, dict[str, dict[str, Any]]],
) -> bool:
    if not _is_visual_handoff_result_node(node):
        return False
    if not _node_has_active_version(node, versions_by_node_id):
        return False
    node_id = str(node.get("id") or "").strip()
    return bool(
        node_id
        and workflow_current_media_version_has_media(project_id, episode_id, workflow, node_id)
    )


def _canonical_workflow_slot(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"[\s-]+", "_", text).lower()
    aliases = {
        "character": "character_reference",
        "scene": "scene_reference",
        "prop": "prop_reference",
        "image": "storyboard_image",
    }
    return aliases.get(text, text)


def _route_ready_video_slot_counts(route_nodes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in route_nodes:
        if not _is_workflow_video_task_node(node):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        input_links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
        for link in input_links:
            if not isinstance(link, dict):
                continue
            slot = _canonical_workflow_slot(link.get("targetSlot") or link.get("slot"))
            status = str(link.get("status") or "").strip().lower()
            if slot not in _STORYBOARD_VIDEO_SLOTS or status in {"", "pending", "pending_generation", "waiting", "missing", "unlinked"}:
                continue
            has_media = any(
                str(link.get(key) or "").strip()
                for key in ("mediaId", "mediaVersionId", "versionId", "sourceId", "sourceNodeId", "path")
            )
            if has_media:
                counts[slot] = counts.get(slot, 0) + 1
    return counts


def _assets_route_status(
    route: dict[str, Any],
    route_nodes: list[dict[str, Any]],
    missing_blockers: list[dict[str, Any]],
    missing_warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    route_id = str(route.get("id") or "__workflow__")
    strategy = str(route.get("strategy") or "storyboard_multi_shot")
    if strategy == "text_to_video_draft":
        return _route_step_status(route_id=route_id, strategy=strategy, skipped=True)
    has_refs = any(_has_asset_refs((node.get("data") if isinstance(node.get("data"), dict) else {}).get("assetRefs")) for node in route_nodes)
    blockers = [copy.deepcopy(item) for item in missing_blockers if str(item.get("routeId") or route_id) == route_id]
    warnings = [copy.deepcopy(item) for item in missing_warnings if str(item.get("routeId") or route_id) == route_id]
    if not has_refs and not blockers and not warnings:
        return _route_step_status(route_id=route_id, strategy=strategy, skipped=True)
    visible_asset = any(str(node.get("type") or "") in {"asset.image", "media.external"} for node in route_nodes)
    if has_refs and not visible_asset:
        blockers.append(_route_blocker(route_id, strategy, "asset_reference", "资产引用缺少可见 asset.image / media.external 节点"))
    return _route_step_status(route_id=route_id, strategy=strategy, completed=not blockers, blockers=blockers, warnings=warnings)


def _cinematic_script_route_status(
    route: dict[str, Any],
    route_nodes: list[dict[str, Any]],
    *, project_id: str = "", episode_id: str = "",
) -> dict[str, Any]:
    route_id = str(route.get("id") or "__workflow__")
    strategy = str(route.get("strategy") or "storyboard_multi_shot")
    if strategy == "text_to_video_draft":
        return _route_step_status(route_id=route_id, strategy=strategy, skipped=True)
    storyboard_task_nodes = [
        node
        for node in route_nodes
        if str(node.get("type") or "") == "prompt.storyboard"
    ]
    has_scripts = bool(storyboard_task_nodes) and all(
        card_text(node.get("data"), "cinematicStoryText") for node in storyboard_task_nodes
    )
    blockers = []
    for node in storyboard_task_nodes:
        data = node.get("data") or {}
        metadata = data.get("scriptGenerationMeta") or {}
        continuity = metadata.get("continuity") if isinstance(metadata, dict) else None
        chain_id = str(node.get("workChainId") or "")
        if not (project_id and episode_id and chain_id and isinstance(continuity, dict)
                and continuity.get("previousScriptHash") and continuity.get("generatedScriptHash")):
            continue
        from .workflow_cinematic_script import cinematic_script_context_hash

        previous_hash = None
        try:
            previous = read_previous_cinematic_script_text_v4(project_id, episode_id, chain_id)
            previous_hash = cinematic_script_context_hash(previous)
            baseline = continuity.get("reviewedPreviousScriptHash") or continuity["previousScriptHash"]
            changed = previous_hash != baseline
        except ValueError:
            print(traceback.format_exc(), flush=True)
            changed = True
        if changed:
            blocker = _route_blocker(route_id, strategy, "script_continuity",
                "前一片段剧本或工作链顺序已改变，请复核当前剧本的衔接，或重新生成。", node=node)
            if previous_hash is not None:
                blocker["reviewContext"] = {
                    "previousScriptHash": previous_hash,
                    "scriptHash": cinematic_script_context_hash(card_text(data, "cinematicStoryText")),
                }
            blockers.append(blocker)
    return _route_step_status(
        route_id=route_id, strategy=strategy, completed=has_scripts and not blockers,
        skipped=not has_scripts, blockers=blockers,
    )


def _director_plan_route_status(
    route: dict[str, Any],
    route_nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    route_id = str(route.get("id") or "__workflow__")
    strategy = str(route.get("strategy") or "storyboard_multi_shot")
    if strategy == "text_to_video_draft":
        return _route_step_status(route_id=route_id, strategy=strategy, skipped=True)
    director_nodes = [
        node
        for node in route_nodes
        if str(node.get("type") or "") == "director.board"
    ]
    if not director_nodes:
        return _route_step_status(
            route_id=route_id,
            strategy=strategy,
            blockers=[_route_blocker(route_id, strategy, "director_plan", "route 缺少分镜脚本")],
        )
    has_source = any(
        script_source_text(node.get("data"))
        for node in route_nodes if node.get("type") == "prompt.storyboard"
    )
    blockers: list[dict[str, Any]] = []
    for node in director_nodes:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        allocation = data.get("storyboardAllocation") if isinstance(data.get("storyboardAllocation"), dict) else {}
        if allocation:
            from .storyboard_allocation import director_shots_hash

            if allocation.get("directorPlanHash") != director_shots_hash(data.get("directorPlanShots") or []):
                blockers.append(_route_blocker(route_id, strategy, "storyboard_allocation", "分镜脚本已变化，请重新保存分镜分配", node=node))
                continue
        if card_text(data, "directorPlan"):
            continue
        blockers.append(
            _route_blocker(
                route_id,
                strategy,
                "director_plan",
                "分镜脚本尚未生成" if has_source else "片段剧本缺少原文事实或剧本，无法生成分镜脚本",
                node=node,
            )
        )
    return _route_step_status(route_id=route_id, strategy=strategy, completed=not blockers, blockers=blockers)


def _storyboard_route_status(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    route: dict[str, Any],
    route_nodes: list[dict[str, Any]],
    versions_by_node_id: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    route_id = str(route.get("id") or "__workflow__")
    strategy = str(route.get("strategy") or "storyboard_multi_shot")
    if strategy == "text_to_video_draft":
        return _route_step_status(route_id=route_id, strategy=strategy, skipped=True)
    reference_nodes = [
        node
        for node in route_nodes
        if str(node.get("type") or "") == "storyboard.image"
    ]
    assigned_cards = [
        node for node in route_nodes
        if node.get("type") == "storyboard.card"
        and str((node.get("data") or {}).get("shotGroupId") or "").strip()
    ]
    if assigned_cards:
        blockers = []
        from .storyboard_allocation import director_shots_hash

        for director in route_nodes:
            if director.get("type") != "director.board":
                continue
            director_data = director.get("data") if isinstance(director.get("data"), dict) else {}
            allocation = director_data.get("storyboardAllocation") if isinstance(director_data.get("storyboardAllocation"), dict) else {}
            if allocation and allocation.get("directorPlanHash") != director_shots_hash(director_data.get("directorPlanShots") or []):
                blockers.append(_route_blocker(route_id, strategy, "storyboard_allocation", "分镜脚本已变化，请重新保存分镜分配", node=director))
        result_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for node in reference_nodes:
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            card_id = str(data.get("resultOfNodeId") or data.get("sourceNodeId") or "").strip()
            group_id = str(data.get("shotGroupId") or "").strip()
            if card_id and group_id:
                result_groups.setdefault((card_id, group_id), []).append(node)
        for card in assigned_cards:
            group = result_groups.get((str(card.get("id") or ""), str((card.get("data") or {}).get("shotGroupId") or "")), [])
            if any(
                _storyboard_image_has_generated_media(project_id, episode_id, workflow, node, versions_by_node_id)
                for node in group
            ):
                continue
            node = group[0] if group else card
            message = _node_quality_block_message(node, versions_by_node_id) or "分配的分镜图尚未生成可用版本"
            blockers.append(_route_blocker(route_id, strategy, "storyboard_generation", message, node=node))
        return _route_step_status(route_id=route_id, strategy=strategy, completed=not blockers, blockers=blockers)
    if not reference_nodes:
        return _route_step_status(
            route_id=route_id,
            strategy=strategy,
            skipped=True,
        )
    ready_slot_counts = _route_ready_video_slot_counts(route_nodes)
    for node in reference_nodes:
        if _storyboard_image_has_generated_media(project_id, episode_id, workflow, node, versions_by_node_id):
            continue
        if _node_quality_block_message(node, versions_by_node_id):
            return _route_step_status(route_id=route_id, strategy=strategy, skipped=True)
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        slot = str(data.get("frameSlot") or "storyboard_image").strip()
        if ready_slot_counts.get(slot, 0) > 0:
            ready_slot_counts[slot] -= 1
            continue
        return _route_step_status(route_id=route_id, strategy=strategy, skipped=True)
    return _route_step_status(route_id=route_id, strategy=strategy, completed=True)


def _storyboard_image_has_generated_media(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
    versions_by_node_id: dict[str, dict[str, dict[str, Any]]],
) -> bool:
    node_id = str(node.get("id") or "").strip()
    return bool(
        node_id
        and _node_has_active_version(node, versions_by_node_id)
        and workflow_current_media_version_has_media(project_id, episode_id, workflow, node_id)
    )


def _visual_handoff_route_status(
    route: dict[str, Any],
    route_nodes: list[dict[str, Any]],
    generated_handoff_card_ids: set[str],
) -> dict[str, Any]:
    route_id = str(route.get("id") or "__workflow__")
    strategy = str(route.get("strategy") or "storyboard_multi_shot")
    if strategy == "text_to_video_draft":
        return _route_step_status(route_id=route_id, strategy=strategy, skipped=True)
    card_ids = {
        str(node.get("id") or "").strip()
        for node in route_nodes
        if _node_type(node) == "storyboard.card"
        and str((node.get("data") or {}).get("shotGroupId") or "").strip()
        and str(node.get("id") or "").strip()
    }
    generated_count = len(card_ids & generated_handoff_card_ids)
    all_generated = bool(card_ids) and generated_count == len(card_ids)
    result = _route_step_status(
        route_id=route_id,
        strategy=strategy,
        completed=all_generated,
        skipped=not generated_count,
    )
    result["generatedUnitCount"] = generated_count
    result["unitCount"] = len(card_ids)
    if generated_count and not all_generated:
        result["status"] = "partial"
    return result


def _video_route_status(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    route: dict[str, Any],
    route_nodes: list[dict[str, Any]],
    versions_by_node_id: dict[str, dict[str, dict[str, Any]]],
    *,
    require_winner: bool = False,
) -> dict[str, Any]:
    route_id = str(route.get("id") or "__workflow__")
    strategy = str(route.get("strategy") or "storyboard_multi_shot")
    video_nodes = [node for node in route_nodes if _is_workflow_video_task_node(node)]
    if not video_nodes:
        return _route_step_status(
            route_id=route_id,
            strategy=strategy,
            blockers=[_route_blocker(route_id, strategy, "video_generation", "route 缺少 video.* 视频生成")],
        )
    blockers = []
    for node in video_nodes:
        result_nodes = _video_result_nodes_for_task(route_nodes, node)
        if not result_nodes:
            blockers.append(_route_blocker(route_id, strategy, "video_generation", "视频片段尚未生成", node=node))
            continue
        ready_result_node = next(
            (
                result_node
                for result_node in result_nodes
                if _video_result_has_generated_media(
                    project_id,
                    episode_id,
                    workflow,
                    result_node,
                    versions_by_node_id,
                )
            ),
            None,
        )
        if require_winner:
            if not ready_result_node or not _node_has_winner_version(ready_result_node, versions_by_node_id):
                data = ready_result_node.get("data") if isinstance((ready_result_node or {}).get("data"), dict) else {}
                active_version_id = str(data.get("activeVersionId") or data.get("active_version_id") or "").strip()
                winner_version_id = str(data.get("winnerVersionId") or data.get("winner_version_id") or "").strip()
                if winner_version_id != active_version_id:
                    winner_version_id = ""
                quality_node = ready_result_node or node
                quality_message = _node_quality_block_message(quality_node, versions_by_node_id, version_id=winner_version_id)
                if quality_message:
                    blockers.append(_route_blocker(route_id, strategy, "variant_quality", quality_message, node=quality_node))
                    continue
                blockers.append(_route_blocker(route_id, strategy, "variant_selection", "视频片段尚未选择 winner 或缺少选择原因", node=quality_node))
        elif not ready_result_node:
            quality_message = ""
            for result_node in result_nodes:
                quality_message = _node_quality_block_message(result_node, versions_by_node_id)
                if quality_message:
                    break
            if quality_message:
                blockers.append(_route_blocker(route_id, strategy, "variant_quality", quality_message, node=result_nodes[0]))
                continue
            blockers.append(_route_blocker(route_id, strategy, "video_generation", "视频片段尚未生成可预览版本", node=result_nodes[0]))
    return _route_step_status(route_id=route_id, strategy=strategy, completed=not blockers, blockers=blockers)


def _step(
    step_id: str,
    label: str,
    complete: bool,
    *,
    blockers: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    next_action: str = "",
    skipped: bool = False,
    route_statuses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    is_completed = bool(complete or skipped)
    return {
        "id": step_id,
        "label": label,
        "completed": is_completed,
        "skipped": bool(skipped),
        "status": "skipped" if skipped else "completed" if is_completed else "pending",
        "blockers": copy.deepcopy(blockers or []),
        "warnings": copy.deepcopy(warnings or []),
        "blockerCount": len(blockers or []),
        "warningCount": len(warnings or []),
        "routeStatuses": copy.deepcopy(route_statuses or []),
        "nextAction": next_action,
    }


def _video_prompt_route_status(
    project_id: str, episode_id: str, workflow: dict[str, Any],
    route: dict[str, Any], nodes: list[dict[str, Any]],
    versions_by_node_id: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    route_id = str(route.get("id") or "__workflow__")
    strategy = str(route.get("strategy") or "storyboard_multi_shot")
    videos = [node for node in nodes if node.get("type") == "video.storyboard"]
    blockers = []
    for node in videos:
        if any(
            _video_result_has_generated_media(project_id, episode_id, workflow, result, versions_by_node_id)
            for result in _video_result_nodes_for_task(nodes, node)
        ):
            continue
        data = node.get("data") or {}
        if not card_text(data.get("videoTaskCard"), "finalVideoPrompt"):
            blockers.append(_route_blocker(
                route_id, strategy, "video_prompt",
                "请先生成或填写并保存视频提示词", node=node,
            ))
    return _route_step_status(route_id=route_id, strategy=strategy, completed=bool(videos) and not blockers, blockers=blockers)


def _route_status_context_from_steps(
    routes: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    *,
    completed_key: str,
    skipped_key: str,
    blocked_key: str,
) -> list[dict[str, Any]]:
    route_context = {
        str(route.get("id") or "__workflow__"): {
            "routeId": None if str(route.get("id") or "__workflow__") == "__workflow__" else str(route.get("id") or ""),
            "workChainId": route.get("workChainId"),
            "segmentId": route.get("segmentId"),
            "strategy": str(route.get("strategy") or "storyboard_multi_shot"),
            completed_key: [],
            skipped_key: [],
            blocked_key: [],
            "blockedBy": [],
        }
        for route in routes
    }
    for item in steps:
        state_id = str(item.get("id") or "")
        for row in item.get("routeStatuses") or []:
            if not isinstance(row, dict):
                continue
            route_key = str(row.get("routeId") or "__workflow__")
            route_state = route_context.setdefault(
                route_key,
                {
                    "routeId": None if route_key == "__workflow__" else route_key,
                    "workChainId": None,
                    "segmentId": None,
                    "strategy": str(row.get("strategy") or ""),
                    completed_key: [],
                    skipped_key: [],
                    blocked_key: [],
                    "blockedBy": [],
                },
            )
            if row.get("completed") and not row.get("skipped") and state_id not in route_state[completed_key]:
                route_state[completed_key].append(state_id)
            if row.get("skipped") and state_id not in route_state[skipped_key]:
                route_state[skipped_key].append(state_id)
            blockers = [blocker for blocker in row.get("blockers") or [] if isinstance(blocker, dict)]
            if blockers:
                if state_id not in route_state[blocked_key]:
                    route_state[blocked_key].append(state_id)
                for blocker in blockers:
                    route_state["blockedBy"].append(
                        {
                            **copy.deepcopy(blocker),
                            "state": state_id,
                            "reason": str(blocker.get("message") or state_id),
                        }
                    )
    return list(route_context.values())


def _current_step_blockers(
    steps: list[dict[str, Any]],
    current_state: str,
    *,
    current_route_key: str = "",
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for item in steps:
        state_id = str(item.get("id") or "")
        if current_route_key:
            if state_id != current_state:
                continue
            for row in item.get("routeStatuses") or []:
                if not isinstance(row, dict):
                    continue
                if str(row.get("routeId") or "__workflow__") != current_route_key:
                    continue
                route_blockers = [blocker for blocker in row.get("blockers") or [] if isinstance(blocker, dict)]
                for blocker in route_blockers:
                    blockers.append(
                        {
                            **copy.deepcopy(blocker),
                            "state": state_id,
                            "reason": str(blocker.get("message") or item.get("nextAction") or state_id),
                        }
                    )
            continue
        if item.get("status") != "blocked":
            continue
        for blocker in [row for row in item.get("blockers") or [] if isinstance(row, dict)]:
            blockers.append(
                {
                    **copy.deepcopy(blocker),
                    "state": state_id,
                    "reason": str(blocker.get("message") or item.get("nextAction") or state_id),
                }
            )
    return blockers


def _build_production_status(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    *,
    work_chain_id: str | None = None,
    versions_by_node_id: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config_revision = model_settings_revision()

    auto_chain_ids = source_work_chain_ids(workflow)
    source_required = workflow.get("canvasKind") != "custom" and not work_chain_id and (bool(auto_chain_ids) or not workflow.get("workChains"))
    if work_chain_id:
        workflow = work_chain_scope(workflow, {work_chain_id})
    elif auto_chain_ids:
        workflow = work_chain_scope(workflow, auto_chain_ids, include_source=True)
    nodes = [item for item in workflow.get("nodes") or [] if isinstance(item, dict)]
    if versions_by_node_id is None:
        versions_by_node_id = _episode_versions_by_node_id(project_id, episode_id)

    source_ready = _episode_source_files_ready(project_id, episode_id)
    workflow_ready = _workflow_has_generated_work_chain(workflow, nodes)
    missing_asset_ref_blockers: list[dict[str, Any]] = []
    missing_asset_ref_warnings: list[dict[str, Any]] = []
    for node in nodes:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        rows = data.get("missingAssetRefs") if isinstance(data.get("missingAssetRefs"), list) else []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            token = str(row.get("token") or row.get("assetId") or row.get("name") or "").strip()
            asset_type = str(row.get("assetType") or "").strip()
            reason = str(row.get("reason") or "asset_image_missing").strip()
            if reason in {"asset_image_missing", "asset_mention_not_matched", "explicit_mention_not_matched"}:
                continue
            asset_label = {
                "characters": "角色",
                "creatures": "生物",
                "scenes": "场景",
                "props": "道具",
            }.get(asset_type, asset_type or "资产")
            if reason == "asset_not_found":
                message = f"引用的{asset_label}未在资产库中找到：{token or index}，请重新选择资产。"
            else:
                message = f"资产引用待处理：{asset_label} {token or index}（{reason}）"
            item = {
                "id": f"missing_asset_ref:{node.get('id')}:{index}",
                "severity": "blocker",
                "category": "asset_reference",
                "message": message,
                "nodeId": node.get("id"),
                "nodeType": node.get("type"),
                "routeId": node.get("routeId") or data.get("routeId"),
                "segmentId": node.get("segmentId") or data.get("segmentId"),
                "assetType": asset_type,
                "token": token,
                "reason": reason,
            }
            missing_asset_ref_blockers.append(item)
    routes = _workflow_routes(workflow, nodes) if workflow_ready else []
    route_nodes_by_id = {
        str(route.get("id") or "__workflow__"): _route_nodes(nodes, str(route.get("id") or "__workflow__"))
        for route in routes
    }
    assets_route_statuses = [
        _assets_route_status(
            route,
            route_nodes_by_id.get(str(route.get("id") or "__workflow__"), []),
            missing_asset_ref_blockers,
            missing_asset_ref_warnings,
        )
        for route in routes
    ]
    cinematic_script_route_statuses = [
        _cinematic_script_route_status(
            route,
            route_nodes_by_id.get(str(route.get("id") or "__workflow__"), []),
            project_id=project_id, episode_id=episode_id,
        )
        for route in routes
    ]
    director_plan_route_statuses = [
        _director_plan_route_status(
            route,
            route_nodes_by_id.get(str(route.get("id") or "__workflow__"), []),
        )
        for route in routes
    ]
    storyboard_route_statuses = [
        _storyboard_route_status(
            project_id,
            episode_id,
            workflow,
            route,
            route_nodes_by_id.get(str(route.get("id") or "__workflow__"), []),
            versions_by_node_id,
        )
        for route in routes
    ]
    generated_handoff_card_ids = {
        str((node.get("data") or {}).get("resultOfNodeId") or (node.get("data") or {}).get("sourceNodeId") or "").strip()
        for node in nodes
        if _visual_handoff_result_has_generated_media(
            project_id, episode_id, workflow, node, versions_by_node_id,
        )
    }
    generated_handoff_card_ids.discard("")
    visual_handoff_route_statuses = [
        _visual_handoff_route_status(
            route,
            route_nodes_by_id.get(str(route.get("id") or "__workflow__"), []),
            generated_handoff_card_ids,
        )
        for route in routes
    ]
    video_route_statuses = [
        _video_route_status(
            project_id,
            episode_id,
            workflow,
            route,
            route_nodes_by_id.get(str(route.get("id") or "__workflow__"), []),
            versions_by_node_id,
        )
        for route in routes
    ]
    video_prompt_route_statuses = [
        _video_prompt_route_status(
            project_id, episode_id, workflow, route,
            route_nodes_by_id.get(str(route.get("id") or "__workflow__"), []),
            versions_by_node_id,
        )
        for route in routes
    ]
    actions_by_route: dict[str, list[dict[str, Any]]] = {}
    for route in routes:
        route_id = str(route.get("id") or "__workflow__")
        completed = [
            state_id
            for state_id, rows in (
                ("director_plan.generated", director_plan_route_statuses),
                ("storyboard.generated", storyboard_route_statuses),
                ("visual_handoff.generated", visual_handoff_route_statuses),
                ("video.generated", video_route_statuses),
            )
            if any(_route_status_route_key(row) == route_id and row["completed"] and not row["skipped"] for row in rows)
        ]
        route_nodes = route_nodes_by_id[route_id]
        ready_image_ids = {
            str(node.get("id") or "")
            for node in route_nodes
            if node.get("type") == "storyboard.image"
            and _storyboard_image_has_generated_media(project_id, episode_id, workflow, node, versions_by_node_id)
        }
        generated_video_ids = {
            str(node.get("id") or "")
            for node in route_nodes
            if _is_workflow_video_task_node(node)
            and any(
                _video_result_has_generated_media(project_id, episode_id, workflow, result_node, versions_by_node_id)
                for result_node in _video_result_nodes_for_task(route_nodes, node)
            )
        }
        prompt_status = next(
            (item for item in video_prompt_route_statuses if _route_status_route_key(item) == route_id),
            {},
        )
        pending_video_prompt_ids = {
            str(blocker.get("nodeId") or "")
            for blocker in prompt_status.get("blockers") or [] if isinstance(blocker, dict)
        }
        actions_by_route[route_id] = recommend_work_chain_actions(
            route_nodes,
            completed,
            ready_image_ids=ready_image_ids,
            generated_handoff_card_ids=generated_handoff_card_ids,
            generated_video_ids=generated_video_ids,
            pending_video_prompt_ids=pending_video_prompt_ids,
            include_visual_handoff=str(route.get("strategy") or "storyboard_multi_shot") != "text_to_video_draft",
        )
    terminal_route_ids = _completed_video_route_ids(video_route_statuses)
    director_not_required_ids = terminal_route_ids | {
        route_id for route_id, actions in actions_by_route.items()
        if any(action["taskType"] == "storyboard_video_generation" for action in actions)
    }
    director_plan_route_statuses = _skip_missing_route_statuses(director_plan_route_statuses, director_not_required_ids)
    if terminal_route_ids:
        video_prompt_route_statuses = _skip_missing_route_statuses(video_prompt_route_statuses, terminal_route_ids)
        assets_route_statuses = _skip_missing_route_statuses(
            assets_route_statuses,
            terminal_route_ids,
        )
        cinematic_script_route_statuses = _skip_missing_route_statuses(
            cinematic_script_route_statuses,
            terminal_route_ids,
        )
        storyboard_route_statuses = _skip_missing_route_statuses(
            storyboard_route_statuses,
            terminal_route_ids,
        )
    assets_linked, assets_skipped, assets_blockers = _aggregate_route_statuses(assets_route_statuses)
    assets_warnings = _aggregate_route_warnings(assets_route_statuses)
    cinematic_script_generated, cinematic_script_skipped, cinematic_script_blockers = _aggregate_route_statuses(cinematic_script_route_statuses)
    director_plan_generated, director_plan_skipped, director_plan_blockers = _aggregate_route_statuses(director_plan_route_statuses)
    storyboard_generated, storyboard_skipped, storyboard_blockers = _aggregate_route_statuses(storyboard_route_statuses)
    visual_handoff_generated, visual_handoff_skipped, visual_handoff_blockers = _aggregate_route_statuses(visual_handoff_route_statuses)
    video_generated, video_skipped, video_blockers = _aggregate_route_statuses(video_route_statuses)
    video_prompt_ready, _, video_prompt_blockers = _aggregate_route_statuses(video_prompt_route_statuses)

    preconditions = [
        _step("episode.source_ready", "分集原文就绪", source_ready, skipped=not source_required, next_action="先完成分集原文提交"),
        _step("workflow.ready", "画布工作链已生成", workflow_ready, next_action="拆分当前集原文并生成画布工作链" if source_required else "创建工作链"),
    ]
    if workflow_ready:
        preconditions.append(
            _step(
                "asset_references.linked",
                "资产引用已绑定",
                assets_linked,
                skipped=assets_skipped,
                blockers=assets_blockers,
                warnings=assets_warnings,
                route_statuses=assets_route_statuses,
                next_action="补齐角色、生物、场景、道具引用",
            )
        )
    precondition_first_open_index = next(
        (index for index, item in enumerate(preconditions) if not item["completed"]),
        None,
    )
    if precondition_first_open_index is not None:
        for index, item in enumerate(preconditions):
            if index == precondition_first_open_index:
                item["status"] = "blocked" if item["blockerCount"] else "current"
            elif index > precondition_first_open_index:
                item["status"] = "pending"

    steps = [
        _step(
            "cinematic_script.generated",
            "片段剧本已生成",
            cinematic_script_generated,
            skipped=cinematic_script_skipped,
            blockers=cinematic_script_blockers,
            route_statuses=cinematic_script_route_statuses,
            next_action="生成当前工作链的片段剧本",
        ),
        _step(
            "director_plan.generated",
            "分镜脚本已生成",
            director_plan_generated,
            skipped=director_plan_skipped,
            blockers=director_plan_blockers,
            route_statuses=director_plan_route_statuses,
            next_action="生成当前工作链的分镜脚本",
        ),
        _step(
            "storyboard.generated",
            "分镜图已生成",
            storyboard_generated,
            skipped=storyboard_skipped,
            blockers=storyboard_blockers,
            route_statuses=storyboard_route_statuses,
            next_action="生成当前工作链的分镜图",
        ),
        _step(
            "visual_handoff.generated",
            "视觉交接图已生成",
            visual_handoff_generated,
            skipped=visual_handoff_skipped,
            blockers=visual_handoff_blockers,
            route_statuses=visual_handoff_route_statuses,
            next_action="生成当前工作链的视觉交接图",
        ),
        _step(
            "video_prompt.ready",
            "视频提示词已就绪",
            video_prompt_ready,
            blockers=video_prompt_blockers,
            route_statuses=video_prompt_route_statuses,
            next_action="生成当前工作链的视频提示词",
        ),
        _step(
            "video.generated",
            "视频片段已生成",
            video_generated,
            skipped=video_skipped,
            blockers=video_blockers,
            route_statuses=video_route_statuses,
            next_action="生成当前工作链的视频片段",
        ),
    ]

    preconditions_ready = precondition_first_open_index is None
    first_open_index = (
        next((index for index, item in enumerate(steps) if not item["completed"]), None)
        if preconditions_ready
        else None
    )
    terminal_state = str((steps[-1] if steps else {}).get("id") or "")
    if not preconditions_ready:
        current_precondition = preconditions[precondition_first_open_index] if precondition_first_open_index is not None else {}
        current_state = str(current_precondition.get("id") or "episode.source_ready")
        next_action = str(current_precondition.get("nextAction") or "")
    elif first_open_index is None:
        current_state = terminal_state
        next_action = ""
    else:
        current_state = str(steps[first_open_index]["id"])
        next_action = str(steps[first_open_index].get("nextAction") or "")
        for index, item in enumerate(steps):
            if index == first_open_index:
                item["status"] = "blocked" if item["blockerCount"] else "current"
            elif index > first_open_index:
                item["status"] = "pending"
    progress_steps = [
        item
        for item in steps
        if str(item.get("id") or "") not in _OPTIONAL_PRODUCTION_STATES
    ]
    completed = len([item for item in progress_steps if item["completed"]])
    completed_states = [
        str(item.get("id"))
        for item in steps
        if item.get("completed") and not item.get("skipped")
    ]
    skipped_states = [
        str(item.get("id"))
        for item in steps
        if item.get("skipped")
    ]
    completed_preconditions = [
        str(item.get("id"))
        for item in preconditions
        if item.get("completed") and not item.get("skipped")
    ]
    skipped_preconditions = [
        str(item.get("id"))
        for item in preconditions
        if item.get("skipped")
    ]
    current_route: dict[str, Any] | None = None
    if preconditions_ready and workflow_ready:
        route_stage_rows = (
            ("cinematic_script.generated", cinematic_script_route_statuses, "生成当前工作链的影视化剧本"),
            ("director_plan.generated", director_plan_route_statuses, "生成当前工作链的分镜脚本"),
            ("storyboard.generated", storyboard_route_statuses, "生成当前工作链的分镜图"),
        )
        for route in routes:
            route_id = str(route.get("id") or "__workflow__")
            video_stage_rows = (
                ("video.generated", video_route_statuses, "生成当前工作链的视频片段"),
                ("video_prompt.ready", video_prompt_route_statuses, "生成当前工作链的视频提示词"),
            ) if any(
                action.get("taskType") == "storyboard_video_generation"
                for action in actions_by_route.get(route_id, [])
            ) else (
                ("video_prompt.ready", video_prompt_route_statuses, "生成当前工作链的视频提示词"),
                ("video.generated", video_route_statuses, "生成当前工作链的视频片段"),
            )
            video_row = next(
                (
                    item
                    for item in video_route_statuses
                    if isinstance(item, dict)
                    and str(item.get("routeId") or "__workflow__") == route_id
                ),
                None,
            )
            if isinstance(video_row, dict) and video_row.get("completed"):
                continue
            for stage_id, rows, action_label in (*route_stage_rows, *video_stage_rows):
                row = next(
                    (
                        item
                        for item in rows
                        if isinstance(item, dict)
                        and str(item.get("routeId") or "__workflow__") == route_id
                    ),
                    None,
                )
                if isinstance(row, dict) and row.get("completed"):
                    continue
                current_state = stage_id
                next_action = action_label
                current_route = route
                break
            if current_route is not None:
                break

    current_route_key = str((current_route or {}).get("id") or "__workflow__") if current_route is not None else ""
    blocked_by = _current_step_blockers(
        steps if preconditions_ready else preconditions,
        current_state,
        current_route_key=current_route_key if preconditions_ready else "",
    )
    blocked = bool(blocked_by) if current_route_key else any(
        item.get("status") == "blocked"
        for item in (steps if preconditions_ready else preconditions)
    )
    route_states = _route_status_context_from_steps(
        routes,
        steps,
        completed_key="completedStates",
        skipped_key="skippedStates",
        blocked_key="blockedStates",
    )
    route_preconditions = _route_status_context_from_steps(
        routes,
        preconditions,
        completed_key="completedPreconditions",
        skipped_key="skippedPreconditions",
        blocked_key="blockedPreconditions",
    )
    for row in route_states:
        row["availableActions"] = actions_by_route.get(str(row.get("routeId") or "__workflow__"), [])
    now = _now()
    overall_status = (
        "ready"
        if preconditions_ready and first_open_index is None
        else "blocked"
        if blocked
        else "in_progress"
    )
    if overall_status == "ready" and not next_action:
        next_action = "review_or_continue_next_episode" if source_required else "review_work_chain"
    return {
        "schemaVersion": 1,
        "projectId": project_id,
        "episodeId": episode_id,
        "currentState": current_state,
        "nextAction": next_action,
        "sourceReady": source_ready,
        "workflowReady": workflow_ready,
        "currentRouteId": (
            None
            if current_route is None or str(current_route.get("id") or "__workflow__") == "__workflow__"
            else str(current_route.get("id") or "")
        ),
        "currentWorkChainId": (
            current_route.get("workChainId")
            if current_route is not None
            else None
        ),
        "currentSegmentId": (
            current_route.get("segmentId")
            if current_route is not None
            else None
        ),
        "projectionVersion": 1,
        "modelConfigVersion": config_revision,
        "overallStatus": overall_status,
        "completedStates": completed_states,
        "skippedStates": skipped_states,
        "completedPreconditions": completed_preconditions,
        "skippedPreconditions": skipped_preconditions,
        "blockedBy": blocked_by,
        "routeStates": route_states,
        "routePreconditions": route_preconditions,
        "progress": {
            "completed": completed,
            "total": len(progress_steps),
            "percent": round(completed / len(progress_steps) * 100) if progress_steps else 0,
        },
        "preconditionProgress": {
            "completed": len([item for item in preconditions if item.get("completed")]),
            "total": len(preconditions),
            "percent": round(len([item for item in preconditions if item.get("completed")]) / len(preconditions) * 100) if preconditions else 0,
        },
        "preconditions": preconditions,
        "steps": steps,
        "updatedAt": now,
    }


def get_episode_production_status(project_id: str, episode_id: str) -> dict[str, Any]:
    from .canvas_store_database import _canvas_snapshot_connection, _canvas_document_row
    from .canvas_store_records import _canvas_document_extras_payload

    with _canvas_snapshot_connection(project_id) as conn:
        document = _canvas_document_row(conn, episode_id)
        extras = _canvas_document_extras_payload(document)
        status = extras.get("productionStatus")
        revision = int(document["revision"] or 0) if document is not None else 0
        return {
            "success": True,
            "status": copy.deepcopy(status) if isinstance(status, dict) else {},
            "productionStatusNeedsRefresh": production_status_needs_refresh(
                status, revision, extras.get("productionStatusRevision"),
            ),
        }


def production_status_needs_refresh(status: Any, revision: int, status_revision: Any) -> bool:
    return (
        not isinstance(status, dict)
        or status.get("projectionVersion") != 1
        or status.get("modelConfigVersion") != model_settings_revision()
        or status_revision != revision
    )


def update_episode_production_status(
    project_id: str,
    episode_id: str,
) -> dict[str, Any]:
    return retry_canvas_mutation_v4(lambda: _update_episode_production_status_once(project_id, episode_id))


def _update_episode_production_status_once(project_id: str, episode_id: str) -> dict[str, Any]:
    workflow = get_canvas_workflow_projection(project_id, episode_id)
    versions = _episode_versions_by_node_id(project_id, episode_id)
    status = _build_production_status(project_id, episode_id, workflow, versions_by_node_id=versions)
    auto_chain_ids = source_work_chain_ids(workflow)
    status["independentWorkChains"] = {
        str(chain["id"]): _build_production_status(
            project_id, episode_id, workflow, work_chain_id=str(chain["id"]), versions_by_node_id=versions,
        )
        for chain in workflow.get("workChains", [])
        if chain.get("id") and chain["id"] not in auto_chain_ids
    }
    workflow_status_sync = _sync_workflow_status_records(workflow, status)
    # Publish file projections only after the matching SQLite snapshot commits.
    # Serialize refresh publication without holding SQLite during calculation.
    with _JSON_WRITE_LOCK:
        try:
            result = write_canvas_production_status_v4(
                project_id, episode_id, status,
                route_statuses=workflow_status_sync["routeStatuses"],
                work_chain_statuses=workflow_status_sync["workChainStatuses"],
                state=workflow_status_sync["state"], expected_revision=workflow["version"],
            )
        except FileNotFoundError:
            if workflow["version"]:
                raise CanvasRevisionConflict("画布已删除，重新读取生产状态") from None
            return {"success": True, "status": status, "changedResources": []}
        status = result.get("productionStatus", status)
        _write_json(_episode_production_status_path(project_id, episode_id), status)
        if _sync_project_episode_status(project_id, episode_id, status):
            result["changedResources"] = [*result.get("changedResources", []), "project"]
    return {**result, "status": status}


__all__ = (
    "get_episode_review_results",
    "save_episode_review_results",
    "waive_review_issue",
    "get_episode_production_status",
    "update_episode_production_status",
)

# Preserve the implementation that was previously effective through package exports.
from .generation_input_context import _workflow_node_by_id
