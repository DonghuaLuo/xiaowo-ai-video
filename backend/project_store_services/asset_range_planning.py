# -*- coding: utf-8 -*-
"""已确认资产范围的覆盖账本提交。"""
from __future__ import annotations

from .catalogs import DEFAULT_ASSET_EXTRACTION_TARGET_UNITS
from .catalogs import _normalize_style_phase_visual_context
from .catalogs import _style_phase_visuals_from_mapping
from .project_resource_revisions import _append_resource_revision
from .project_resource_revisions import _assert_resource_write_guard
from .project_resource_revisions import _payload_first_present
from .project_resource_revisions import _resource_revision_value
from .source_boundary_contract import _asset_range_phase_visual_context_items
from .source_boundary_contract import _unwrap_agent_commit_payload
from .source_coverage import _asset_range_analysis_state
from .source_coverage import _asset_range_target_payload
from .source_coverage import _blocking_asset_analysis_range
from .source_coverage import _load_source_coverage
from .source_coverage import _write_source_coverage
from .source_text_store import _read_source_content
from .source_text_store import _select_project_sources
from .store_core import _now
from .store_core import _read_json
from .store_core import _serialized_project_config_write
from .store_core import _write_json
from typing import Any
from utils.text_metrics import content_units_between
import copy


def _asset_range_existing_phase_visuals_for_prompt(project_id: str) -> list[dict[str, str]]:
    """读取当前项目的阶段视觉约束，供资产范围规划上下文使用。"""
    from .agent_sessions import _project_config_path

    project_config = _read_json(_project_config_path(project_id), {})
    style_config = project_config.get("style") if isinstance(project_config.get("style"), dict) else {}
    normalized: list[dict[str, str]] = []
    for item in _style_phase_visuals_from_mapping(style_config):
        if not isinstance(item, dict):
            continue
        prompt = _normalize_style_phase_visual_context(item.get("prompt") or "")
        if prompt:
            normalized.append({
                "id": str(item.get("id") or "").strip(),
                "name": str(item.get("name") or "").strip()[:40],
                "prompt": prompt,
            })
    return normalized


def _asset_range_revision_target(coverage: dict[str, Any], range_id: str) -> dict[str, Any] | None:
    """Only the latest, unused range can be revised without invalidating downstream work."""
    if not range_id:
        return None
    rows = [item for item in coverage.get("assetRanges", []) if isinstance(item, dict)]
    row = next((item for item in rows if item.get("rangeId") == range_id), None)
    if not row:
        raise ValueError("指定的资产范围不存在，请重新读取当前项目范围")
    if row is not rows[-1] or row.get("analysisStatus") != "committed" or row.get("createdAssetIds"):
        raise ValueError("仅可修订最新且尚未开始资产拆分的范围；已有下游结果不能直接覆盖")
    return row


def _asset_range_owns_visual(range_id: str, visual_id: str) -> bool:
    prefix = f"asset-phase-{range_id}"
    return visual_id == prefix or (visual_id.startswith(prefix + "-")
                                  and visual_id[len(prefix) + 1:].isdigit())


@_serialized_project_config_write
def commit_asset_range(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from .agent_sessions import _project_config_path
    from .project_management import apply_phase_visual_context_to_config
    if not isinstance(payload, dict):
        raise ValueError("缺少资产范围参数")
    payload = _unwrap_agent_commit_payload(payload)
    coverage = _load_source_coverage(project_id, payload.get("sourceId"))
    _assert_resource_write_guard(
        coverage,
        _payload_first_present(payload, "expectedRevision"),
        _payload_first_present(payload, "baseHash"),
    )
    coverage_before = copy.deepcopy(coverage)
    proposal = payload.get("proposal") if isinstance(payload.get("proposal"), dict) else {}
    revision_id = str(payload.get("assetRangeId") or "")
    revision_row = _asset_range_revision_target(coverage, revision_id)
    source_id = str(payload.get("sourceId") or proposal.get("sourceId") or coverage.get("sourceId") or "")
    source = _select_project_sources(project_id, source_id)[0]
    content = _read_source_content(project_id, source)
    if payload.get("contextVersion"):
        from .agent_asset_range_tools import _asset_range_inputs, asset_range_context_version
        inputs = _asset_range_inputs(project_id, source_id, payload.get("targetUnits"), asset_range_id=revision_id)
        if payload["contextVersion"] != asset_range_context_version(inputs):
            raise ValueError("原文、规划参数或阶段视觉已变化，请重新读取后提交")
    total_chars = len(content)
    blocking_range = _blocking_asset_analysis_range(coverage, project_id=project_id, source_id=source_id)
    if blocking_range and blocking_range is not revision_row:
        blocking_payload = _asset_range_target_payload(blocking_range, source_id)
        blocking_state = _asset_range_analysis_state(blocking_range) or "committed"
        raise ValueError(
            f"资产范围 {blocking_payload.get('rangeId') or ''} 尚未完成分析，当前状态：{blocking_state}；"
            "请先完成该范围的资产拆分。"
        )
    cursor = coverage.get("assetCursor") if isinstance(coverage.get("assetCursor"), dict) else {}
    start_value = payload.get("startOffset", proposal.get("absoluteStart"))
    start = int(start_value if start_value is not None else cursor.get("nextOffset") or 0)
    end = int(payload.get("endOffset") or payload.get("absoluteEnd") or proposal.get("absoluteEnd") or 0)
    expected_start = int(revision_row["absoluteStart"] if revision_row else cursor.get("nextOffset") or 0)
    if start != expected_start:
        raise ValueError(f"资产范围必须从当前游标 {expected_start} 开始，收到 {start}")
    if end <= start or end > total_chars:
        raise ValueError("资产范围无效")
    range_id = str(payload.get("rangeId") or proposal.get("rangeId") or f"asset-range-{len(coverage.get('assetRanges', [])) + 1:03d}")
    if revision_row and range_id != revision_id:
        raise ValueError("修订范围 ID 与目标不一致")
    for item in coverage.get("assetRanges", []):
        if not isinstance(item, dict):
            continue
        if item is revision_row:
            continue
        if str(item.get("rangeId") or "") == range_id:
            raise ValueError("资产范围 ID 已存在")
        existing_start = int(item.get("absoluteStart") or 0)
        existing_end = int(item.get("absoluteEnd") or 0)
        if max(start, existing_start) < min(end, existing_end):
            raise ValueError("资产范围与已提交范围重叠")
    phase_visual_contexts = _asset_range_phase_visual_context_items(payload)
    if not phase_visual_contexts:
        phase_visual_contexts = _asset_range_phase_visual_context_items(proposal)
    phase_visual_context = _normalize_style_phase_visual_context(
        payload.get("phaseVisualContext")
        or proposal.get("phaseVisualContext")
        or ""
    )
    if not phase_visual_context and phase_visual_contexts:
        phase_visual_context = phase_visual_contexts[0]["visualPrompt"]
    phase_visual_name = str(
        payload.get("phaseVisualName")
        or (phase_visual_contexts[0]["name"] if phase_visual_contexts else "")
        or proposal.get("summary")
        or range_id
    ).strip()
    row = {
        "rangeId": range_id,
        "sourceId": source_id,
        "absoluteStart": start,
        "absoluteEnd": end,
        "targetUnits": int(payload.get("targetUnits") or cursor.get("targetUnits") or DEFAULT_ASSET_EXTRACTION_TARGET_UNITS),
        "actualUnits": content_units_between(content, start, end),
        "analysisStatus": "committed",
        "assetTypes": payload.get("assetTypes") if isinstance(payload.get("assetTypes"), list) else (proposal.get("assetTypes") or ["characters", "creatures", "scenes", "props"]),
        "summary": str(payload.get("summary") or proposal.get("summary") or ""),
        "reason": str(payload.get("reason") or proposal.get("reason") or ""),
        "boundaryReason": str(payload.get("boundaryReason") or proposal.get("boundaryReason") or ""),
        "boundaryToleranceUnits": int(
            payload.get("boundaryToleranceUnits")
            or proposal.get("boundaryToleranceUnits")
            or 0
        ),
        "planningLookaheadUnits": int(
            payload.get("planningLookaheadUnits")
            or proposal.get("planningLookaheadUnits")
            or 0
        ),
        "planningWindowEnd": int(
            payload.get("planningWindowEnd")
            or proposal.get("planningWindowEnd")
            or end
        ),
        "planningMethod": str(payload.get("planningMethod") or proposal.get("planningMethod") or ""),
        "boundaryEndText": str(payload.get("boundaryEndText") or proposal.get("boundaryEndText") or ""),
        "phaseVisualContext": phase_visual_context,
        "stageVisualChanged": bool(phase_visual_contexts),
        "phaseVisualContexts": phase_visual_contexts,
        "riskNotes": (
            payload.get("riskNotes")
            if isinstance(payload.get("riskNotes"), list)
            else (
                proposal.get("riskNotes")
                if isinstance(proposal.get("riskNotes"), list)
                else []
            )
        ),
        "createdAssetIds": payload.get("createdAssetIds") if isinstance(payload.get("createdAssetIds"), list) else [],
        "createdAt": _now(),
    }
    if revision_row:
        row["createdAt"] = revision_row.get("createdAt") or row["createdAt"]
        row["updatedAt"] = _now()
        coverage["assetRanges"][coverage["assetRanges"].index(revision_row)] = row
    else:
        coverage.setdefault("assetRanges", []).append(row)
    coverage.setdefault("assetCursor", {})["nextOffset"] = end
    coverage["assetCursor"]["lastRangeId"] = range_id
    _append_resource_revision(
        project_id,
        resource="sourceCoverage",
        relative_path="source_coverage.json",
        document=coverage_before,
        reason=str(payload.get("reason") or "commit_asset_range"),
        user_instruction=str(payload.get("userInstruction") or ""),
    )
    coverage["revision"] = _resource_revision_value(coverage_before) + 1
    _write_source_coverage(project_id, coverage)
    changed_resources = ["sourceCoverage", "assetRanges"]
    project_config_path = _project_config_path(project_id)
    project_config = _read_json(project_config_path, {})
    if isinstance(project_config, dict) and (revision_row or phase_visual_contexts or phase_visual_context):
        project_config_before = copy.deepcopy(project_config)
        changed_project_config = False
        if revision_row:
            style = project_config.get("style") or {}
            previous_visuals = style.get("phase_visuals") or []
            style["phase_visuals"] = [item for item in previous_visuals
                                      if not _asset_range_owns_visual(range_id, str(item.get("id") or ""))]
            changed_project_config = previous_visuals != style["phase_visuals"]
            project_config["style"] = style
        append_items = phase_visual_contexts or ([
            {
                "name": phase_visual_name,
                "visualPrompt": phase_visual_context,
                "sourceSpan": "",
                "visualChangeReason": "",
                "transitionType": "initial_or_single_stage",
            }
        ] if phase_visual_context else [])
        for index, item in enumerate(append_items, 1):
            item_prompt = _normalize_style_phase_visual_context(item.get("visualPrompt") or "")
            if not item_prompt:
                continue
            item_id = f"asset-phase-{range_id}" if len(append_items) == 1 else f"asset-phase-{range_id}-{index:02d}"
            changed_project_config = apply_phase_visual_context_to_config(
                project_config,
                item_id,
                item.get("name") or phase_visual_name,
                item_prompt,
                activate=False,
            ) or changed_project_config
        changed_project_config = project_config != project_config_before
        if changed_project_config:
            style = project_config.get("style") or {}
            if style.get("active_phase_visual_id") and not any(
                item.get("id") == style["active_phase_visual_id"] for item in style.get("phase_visuals", [])
            ):
                style["active_phase_visual_id"] = None
            _append_resource_revision(project_id, resource="projectConfig", relative_path="config.json",
                                      document=project_config_before, reason="asset_range_visual_revision",
                                      user_instruction=str(payload.get("userInstruction") or ""))
            project_config["revision"] = _resource_revision_value(project_config_before) + 1
            project_config["updatedAt"] = _now()
            _write_json(project_config_path, project_config)
            changed_resources.append("projectConfig")
    return {
        "success": True,
        "message": f"{range_id} 资产提取范围已提交。",
        "range": row,
        "coverage": coverage,
        "changedResources": changed_resources,
        "focusTarget": {"section": "assets"},
        "projectChanged": True,
    }
