# -*- coding: utf-8 -*-
"""镜头提示词修订与对应画布任务卡字段更新。"""
from __future__ import annotations

from .asset_reference_scope import _normalize_shot_plan_asset_refs
from .asset_reference_scope import _validate_plan_asset_refs
from .project_resource_revisions import _append_resource_revision
from .project_resource_revisions import _assert_resource_write_guard
from .project_resource_revisions import _resource_revision_value
from .source_reference_scope import _stamp_source_units_on_shot_plan
from .source_reference_scope import _validate_shot_plan_source_refs
from .store_core import _deep_merge
from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json
from typing import Any
import copy


def _workflow_prompt_patch_target_tokens(node: dict[str, Any]) -> set[str]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    tokens = {
        str(node.get("id") or "").strip(),
        str(node.get("segmentId") or "").strip(),
        str(node.get("shotId") or "").strip(),
        str(data.get("id") or "").strip(),
        str(data.get("segmentId") or data.get("segment_id") or "").strip(),
        str(data.get("shotId") or data.get("shot_id") or "").strip(),
    }
    for key in ("shots", "panels"):
        rows = data.get(key) if isinstance(data.get(key), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            tokens.update(
                {
                    str(row.get("id") or "").strip(),
                    str(row.get("segmentId") or row.get("segment_id") or "").strip(),
                    str(row.get("shotId") or row.get("shot_id") or "").strip(),
                }
            )
    return {token for token in tokens if token}


def _workflow_prompt_patch_for_data(
    node: dict[str, Any],
    target_id: str,
    target_kind: str,
    patch_fields: dict[str, Any],
    prompt_patch: dict[str, Any],
) -> dict[str, Any]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    target_kind = str(target_kind or "").strip().lower()
    if target_id and target_kind == "shot":
        for key in ("shots", "panels"):
            rows = data.get(key) if isinstance(data.get(key), list) else []
            patched_rows: list[dict[str, Any]] = []
            changed = False
            for row in rows:
                if not isinstance(row, dict):
                    patched_rows.append(row)
                    continue
                row_tokens = {
                    str(row.get("id") or "").strip(),
                    str(row.get("shotId") or row.get("shot_id") or "").strip(),
                }
                if target_id not in row_tokens:
                    patched_rows.append(row)
                    continue
                next_row = _deep_merge(row, {**copy.deepcopy(patch_fields), **copy.deepcopy(prompt_patch)})
                prompts = next_row.get("prompts") if isinstance(next_row.get("prompts"), dict) else {}
                if prompt_patch:
                    prompts = _deep_merge(prompts, prompt_patch)
                    next_row["prompts"] = prompts
                patched_rows.append(next_row)
                changed = True
            if changed:
                return {key: patched_rows}
    if target_id and target_kind == "segment":
        rows = data.get("segments") if isinstance(data.get("segments"), list) else []
        patched_rows: list[dict[str, Any]] = []
        changed = False
        for row in rows:
            if not isinstance(row, dict):
                patched_rows.append(row)
                continue
            row_tokens = {
                str(row.get("id") or "").strip(),
                str(row.get("segmentId") or row.get("segment_id") or "").strip(),
            }
            if target_id not in row_tokens:
                patched_rows.append(row)
                continue
            next_row = _deep_merge(row, copy.deepcopy(patch_fields))
            prompts = next_row.get("prompts") if isinstance(next_row.get("prompts"), dict) else {}
            if prompt_patch:
                prompts = _deep_merge(prompts, prompt_patch)
                next_row["prompts"] = prompts
            patched_rows.append(next_row)
            changed = True
        if changed:
            return {"segments": patched_rows}
    data_patch = copy.deepcopy(patch_fields)
    if prompt_patch:
        data_patch.update(prompt_patch)
        data_patch["prompt"] = _deep_merge(data.get("prompt") if isinstance(data.get("prompt"), dict) else {}, prompt_patch)
        data_patch["prompts"] = _deep_merge(data.get("prompts") if isinstance(data.get("prompts"), dict) else {}, prompt_patch)
    return data_patch


def _patch_workflow_prompt_from_shot_patch(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
    *,
    target_id: str,
    target_kind: str,
    target_index: int,
    patch_fields: dict[str, Any],
    prompt_patch: dict[str, Any],
) -> dict[str, Any]:
    from .workflow_projection import get_canvas_workflow_projection
    from .workflow_inline_editing import save_workflow_node_inline_edit

    workflow = get_canvas_workflow_projection(project_id, episode_id)
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    prompt_nodes = [
        node
        for node in nodes
        if isinstance(node, dict) and str(node.get("type") or "").strip() in {"prompt.storyboard", "director.board"}
    ]
    if not prompt_nodes:
        return {"success": True, "changed": False, "reason": "workflow_empty"}
    target_node: dict[str, Any] | None = None
    if target_id:
        for node in prompt_nodes:
            if target_id in _workflow_prompt_patch_target_tokens(node):
                target_node = node
                break
            node_id = str(node.get("id") or "").strip()
            if node_id and node_id.endswith(target_id):
                target_node = node
                break
    elif target_index > 0 and target_index <= len(prompt_nodes):
        target_node = prompt_nodes[target_index - 1]
    if not isinstance(target_node, dict):
        return {"success": True, "changed": False, "reason": "workflow_target_not_found"}
    node_id = str(target_node.get("id") or "").strip()
    data_patch = _workflow_prompt_patch_for_data(target_node, target_id, target_kind, patch_fields, prompt_patch)
    if not data_patch:
        return {"success": True, "changed": False, "reason": "empty_patch"}
    result = save_workflow_node_inline_edit(
        project_id,
        episode_id,
        {
            "nodeId": node_id,
            "data": data_patch,
            "reason": str(payload.get("reason") or "patch_shot_prompt"),
            "userInstruction": str(payload.get("userInstruction") or payload.get("user_instruction") or ""),
            "returnProductionStatus": True,
        },
    )
    result["changed"] = bool(result.get("success"))
    return result


def patch_shot_prompt(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    from .projects import _touch_project_meta
    if not episode_id:
        raise ValueError("缺少 episodeId")
    path = _project_dir(project_id) / "episodes" / episode_id / "work_chain_plan.json"
    shot_plan = _read_json(path, {})
    has_shot_plan = isinstance(shot_plan, dict) and bool(shot_plan)
    if not isinstance(shot_plan, dict):
        shot_plan = {}
    if has_shot_plan:
        _assert_resource_write_guard(
            shot_plan,
            payload.get("expectedRevision") or payload.get("expected_revision"),
            payload.get("baseHash") or payload.get("base_hash"),
        )
    before = copy.deepcopy(shot_plan)
    shot_target_id = str(payload.get("shotId") or payload.get("shot_id") or "").strip()
    segment_target_id = str(payload.get("segmentId") or payload.get("segment_id") or "").strip()
    target_id = shot_target_id or segment_target_id
    target_kind = "shot" if shot_target_id else "segment" if segment_target_id else ""
    try:
        target_index = int(payload.get("index") or payload.get("shotIndex") or payload.get("shot_index") or 0)
    except (TypeError, ValueError):
        target_index = 0
    if not target_id and target_index <= 0:
        raise ValueError("缺少 shotId、segmentId 或 index")
    patch_fields = copy.deepcopy(payload.get("fields")) if isinstance(payload.get("fields"), dict) else {}
    prompt_patch: dict[str, Any] = {}
    if "storyboardImagePrompt" in payload or "storyboard_image_prompt" in payload:
        prompt_patch["storyboardImagePrompt"] = str(payload.get("storyboardImagePrompt") or payload.get("storyboard_image_prompt") or "")
    if "videoPrompt" in payload or "video_prompt" in payload:
        prompt_patch["videoPrompt"] = payload.get("videoPrompt") if "videoPrompt" in payload else payload.get("video_prompt")
    if "sourceRefs" in payload or "source_refs" in payload:
        patch_fields["sourceRefs"] = payload.get("sourceRefs") if "sourceRefs" in payload else payload.get("source_refs")
    if "assetRefs" in payload or "asset_refs" in payload:
        patch_fields["assetRefs"] = payload.get("assetRefs") if "assetRefs" in payload else payload.get("asset_refs")
    updated = False
    if target_kind != "segment":
        for index, shot in enumerate(shot_plan.get("shots", []), start=1):
            if not isinstance(shot, dict):
                continue
            if target_id and str(shot.get("id") or "") != target_id:
                continue
            if not target_id and index != target_index:
                continue
            merged = _deep_merge(shot, {**patch_fields, **prompt_patch})
            shot.clear()
            shot.update(merged)
            updated = True
            break
    if target_kind != "shot":
        for index, segment in enumerate(shot_plan.get("segments", []), start=1):
            if not isinstance(segment, dict):
                continue
            if target_id and str(segment.get("id") or "") != target_id:
                continue
            if not target_id and index != target_index:
                continue
            if patch_fields:
                merged = _deep_merge(segment, patch_fields)
                segment.clear()
                segment.update(merged)
            prompts = segment.setdefault("prompts", {})
            if not isinstance(prompts, dict):
                prompts = {}
                segment["prompts"] = prompts
            prompts.update(prompt_patch)
            updated = True
            break
    warnings: list[str] = []
    revision = None
    if updated:
        shot_plan = _normalize_shot_plan_asset_refs(shot_plan)
        shot_plan = _stamp_source_units_on_shot_plan(project_id, episode_id, shot_plan)
        shot_plan["revision"] = _resource_revision_value(before) + 1
        shot_plan["updatedAt"] = _now()
        blocking, warnings = _validate_shot_plan_source_refs(project_id, episode_id, shot_plan)
        asset_blocking, asset_warnings = _validate_plan_asset_refs(project_id, shot_plan, episode_id)
        blocking.extend(asset_blocking)
        warnings.extend(asset_warnings)
        if blocking:
            raise ValueError("；".join(blocking))
        revision = _append_resource_revision(
            project_id,
            resource="workChainPlan",
            relative_path=f"episodes/{episode_id}/work_chain_plan.json",
            document=before,
            reason=str(payload.get("reason") or "patch_shot_prompt"),
            user_instruction=str(payload.get("userInstruction") or payload.get("user_instruction") or ""),
        )
        _write_json(path, shot_plan)

    workflow_patch_result = _patch_workflow_prompt_from_shot_patch(
        project_id,
        episode_id,
        payload,
        target_id=target_id,
        target_kind=target_kind,
        target_index=target_index,
        patch_fields=patch_fields,
        prompt_patch=prompt_patch,
    )
    workflow_changed = bool(workflow_patch_result.get("changed"))
    if not updated and not workflow_changed:
        raise FileNotFoundError("未找到目标 shot/segment 或工作流片段剧本")
    _touch_project_meta(project_id)
    return {
        "success": True,
        "episodeId": episode_id,
        "workChainPlan": shot_plan,
        "revision": revision,
        "warnings": warnings,
        "workflowPatch": workflow_patch_result if workflow_changed else None,
        "changedResources": [
            *(["workChainPlan"] if updated else []),
            *(["canvas_node"] if workflow_changed else []),
            *(["episode_production_status"] if workflow_patch_result.get("productionStatus") else []),
        ],
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": target_id},
        "projectChanged": True,
    }
