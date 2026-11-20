# -*- coding: utf-8 -*-
"""项目质量校验以及通过校验后的工作流写入。"""
from __future__ import annotations

import copy as copy
from .agent_sessions import (
    _project_meta_path,
)
from .assets import (
    list_assets,
)
from .canvas_store_mutations import write_canvas_card_records_v4
from .asset_reference_scope import _validate_workflow_asset_refs
from .source_reference_scope import _episode_range_for_id, _shot_source_refs, _source_ref_has_valid_unit_ref, _source_ref_in_episode_range
from .production_status import (
    _workflow_has_generated_work_chain,
)
from .projects import (
    _touch_project_meta,
)
from .source_coverage import _load_source_coverage, _source_ref_bounds
from .source_text_store import _compact_text, _episode_source_ref_path, _episode_source_text_path, _read_episode_source_text, _read_source_content, _select_project_sources, _sha256_text
from .splitting_templates import (
    _string_list,
)
from .store_core import (
    ASSET_LIFECYCLE_ACTIVE,
    _read_json,
)
from .workflow_input_resolution import (
    resolve_generation_task_node_id,
    workflow_storyboard_reference_node_ids,
)
from .workflow_projection import (
    get_canvas_workflow_projection,
)
from .workflow_generation_context import workflow_generation_related_node_ids

from typing import Any


def _asset_ref_in_confirmed_range(ref: dict[str, Any], ranges: list[dict[str, Any]]) -> bool:
    asset_range_id = str(ref.get("assetRangeId") or "")
    start, end = _source_ref_bounds(ref)
    ref_source_id = str(ref.get("sourceId") or "")
    for item in ranges:
        if not isinstance(item, dict):
            continue
        if start is None or end is None:
            continue
        range_id = str(item.get("rangeId") or "")
        if asset_range_id and range_id != asset_range_id:
            continue
        range_start = int(item.get("absoluteStart") or 0)
        range_end = int(item.get("absoluteEnd") or 0)
        range_source_id = str(item.get("sourceId") or "")
        if ref_source_id == range_source_id and range_start <= start < end <= range_end:
            return True
    return False


def _quality_node_ids_for_generation_task(
    task_type: str | None,
    workflow: dict[str, Any] | None = None,
    node_id: str | None = None,
) -> set[str] | None:
    normalized = str(task_type or "").strip()
    if isinstance(workflow, dict) and workflow:
        if normalized in {"storyboard_image", "storyboard_image_edit", "visual_handoff_image"}:
            resolved_node_id = resolve_generation_task_node_id(workflow, normalized, node_id)
            nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
            routes = workflow.get("routes") if isinstance(workflow.get("routes"), list) else []
            if not resolved_node_id and normalized in {"storyboard_image", "storyboard_image_edit"}:
                resolved_node_id = next(
                    (
                        str(item.get("id") or "").strip()
                        for item in nodes
                        if isinstance(item, dict)
                        and str(item.get("type") or "").strip() == "storyboard.image"
                        and str(item.get("id") or "").strip()
                    ),
                    "",
                )
            if not resolved_node_id and normalized == "visual_handoff_image":
                resolved_node_id = next(
                    (
                        str(item.get("id") or "").strip()
                        for item in nodes
                        if isinstance(item, dict)
                        and str(item.get("type") or "").strip() == "asset.image"
                        and str(item.get("id") or "").strip()
                    ),
                    "",
                )

            def node_by_id(value: str) -> dict[str, Any] | None:
                normalized_id = str(value or "").strip()
                return next(
                    (
                        item
                        for item in nodes
                        if isinstance(item, dict)
                        and str(item.get("id") or "").strip() == normalized_id
                    ),
                    None,
                )

            def node_data(value: dict[str, Any] | None) -> dict[str, Any]:
                data = value.get("data") if isinstance(value, dict) and isinstance(value.get("data"), dict) else {}
                return data if isinstance(data, dict) else {}

            def route_id_for(value: dict[str, Any] | None) -> str:
                data = node_data(value)
                return str((value or {}).get("routeId") or data.get("routeId") or "").strip()

            def work_chain_id_for(value: dict[str, Any] | None) -> str:
                data = node_data(value)
                direct = str((value or {}).get("workChainId") or data.get("workChainId") or "").strip()
                if direct:
                    return direct
                route_id = route_id_for(value)
                if not route_id:
                    return ""
                for route in routes:
                    if not isinstance(route, dict):
                        continue
                    if str(route.get("id") or route.get("routeId") or "").strip() == route_id:
                        return str(route.get("workChainId") or route.get("work_chain_id") or "").strip()
                return ""

            resolved_node = node_by_id(resolved_node_id) if resolved_node_id else None
            route_id = route_id_for(resolved_node)
            work_chain_id = work_chain_id_for(resolved_node)
            result: set[str] = {resolved_node_id} if resolved_node_id else set()
            prompt_node_types = {"prompt.storyboard", "director.board"}
            for candidate in nodes:
                if not isinstance(candidate, dict):
                    continue
                candidate_id = str(candidate.get("id") or "").strip()
                if not candidate_id or str(candidate.get("type") or "").strip() not in prompt_node_types:
                    continue
                if work_chain_id and work_chain_id_for(candidate) == work_chain_id:
                    result.add(candidate_id)
                    continue
                if route_id and route_id_for(candidate) == route_id:
                    result.add(candidate_id)
            if result:
                return result
        related_ids = workflow_generation_related_node_ids(workflow, normalized, node_id)
        if related_ids:
            return related_ids
    return None


def _agent_focus_workflow_node_id(project_id: str, episode_id: str | None) -> str:
    current_episode_id = str(episode_id or "E01")
    try:
        workflow = get_canvas_workflow_projection(project_id, current_episode_id)
        node_id = resolve_generation_task_node_id(workflow, "storyboard_plan")
        if node_id:
            return node_id
    except Exception:
        return
    return ""


def validate_project_quality(
    project_id: str,
    episode_id: str | None = None,
    *,
    generation_task_type: str | None = None,
    generation_node_id: str | None = None,
) -> dict[str, Any]:
    blocking: list[str] = []
    warnings: list[str] = []
    coverage = _load_source_coverage(project_id)
    source_id = str(coverage.get("sourceId") or "")
    source = _select_project_sources(project_id, source_id)[0]
    content = _read_source_content(project_id, source)
    ranges = [item for item in coverage.get("episodeRanges", []) if isinstance(item, dict)]
    asset_ranges = [item for item in coverage.get("assetRanges", []) if isinstance(item, dict)]
    ranges.sort(key=lambda item: int(item.get("absoluteStart") or 0))
    expected_start = 0
    seen_episode_ids: set[str] = set()
    for item in ranges:
        current_episode_id = str(item.get("episodeId") or "")
        start = int(item.get("absoluteStart") or 0)
        end = int(item.get("absoluteEnd") or 0)
        if not current_episode_id:
            blocking.append("分集范围缺少 episodeId")
        elif current_episode_id in seen_episode_ids:
            blocking.append(f"{current_episode_id} 分集范围重复")
        seen_episode_ids.add(current_episode_id)
        if start != expected_start:
            blocking.append(f"{current_episode_id or '未知分集'} 原文范围不连续：期望从 {expected_start} 开始，实际 {start}")
        if end <= start:
            blocking.append(f"{current_episode_id or '未知分集'} 原文范围无效")
        expected_start = max(expected_start, end)
        source_text_path = _episode_source_text_path(project_id, current_episode_id)
        source_ref_path = _episode_source_ref_path(project_id, current_episode_id)
        source_ref = _read_json(source_ref_path, {}) if source_ref_path.exists() else {}
        if not source_text_path.exists():
            blocking.append(f"{current_episode_id} 缺少 source.txt")
            continue
        if not source_ref_path.exists() or not isinstance(source_ref, dict) or not source_ref:
            blocking.append(f"{current_episode_id} 缺少 source_ref.json")
        else:
            ref_episode_id = str(source_ref.get("episodeId") or source_ref.get("episode_id") or "")
            ref_source_id = str(source_ref.get("sourceId") or "")
            ref_start, ref_end = _source_ref_bounds(source_ref)
            range_source_id = str(item.get("sourceId") or "")
            if ref_episode_id != current_episode_id:
                blocking.append(f"{current_episode_id} source_ref.json episodeId 不一致")
            if ref_source_id != range_source_id:
                blocking.append(f"{current_episode_id} source_ref.json sourceId 不一致")
            if ref_start != start or ref_end != end:
                blocking.append(f"{current_episode_id} source_ref.json 原文范围不一致")
        source_text = _read_episode_source_text(project_id, current_episode_id)
        original_slice = content[start:end].strip()
        expected_hash = _sha256_text(original_slice)
        file_hash = _sha256_text(source_text)
        ref_hash = str(source_ref.get("textHash") or "")
        range_hash = str(item.get("textHash") or "")
        manual_edited = bool(source_ref.get("manualEdited") or item.get("manualEdited"))
        if not manual_edited and (source_text != original_slice or file_hash != expected_hash):
            blocking.append(f"{current_episode_id} source.txt 与原文切片不一致")
        if not ref_hash:
            blocking.append(f"{current_episode_id} source_ref.json textHash 缺失")
        elif ref_hash != file_hash:
            blocking.append(f"{current_episode_id} source_ref.json textHash 不一致")
        if range_hash and range_hash != file_hash:
            blocking.append(f"{current_episode_id} source_coverage textHash 不一致")
    if ranges and expected_start > len(content):
        blocking.append("分集范围超出源文件长度")

    committed_episode_ids = {str(item.get("episodeId") or "").strip() for item in ranges if str(item.get("episodeId") or "").strip()}
    meta = _read_json(_project_meta_path(project_id), {})
    meta_episode_ids = [
        str(item.get("id") or item.get("episodeId") or item.get("episode_id") or "").strip()
        for item in (meta.get("episodes") if isinstance(meta.get("episodes"), list) else [])
        if isinstance(item, dict) and str(item.get("id") or item.get("episodeId") or item.get("episode_id") or "").strip()
    ]
    if episode_id:
        if episode_id not in committed_episode_ids:
            blocking.append(f"{episode_id} 尚未提交分集原文范围，缺少 source.txt/source_ref.json 闭环")
        selected_episode_ids = [episode_id]
    else:
        if not ranges:
            blocking.append("尚未提交任何分集原文范围，缺少 source.txt/source_ref.json 闭环")
        selected_episode_ids = [str(item.get("episodeId") or "") for item in ranges]
        for meta_episode_id in meta_episode_ids:
            if meta_episode_id not in committed_episode_ids:
                blocking.append(f"{meta_episode_id} 尚未提交分集原文范围，缺少 source.txt/source_ref.json 闭环")
                selected_episode_ids.append(meta_episode_id)

    for current_episode_id in [item for item in selected_episode_ids if item]:
        workflow = get_canvas_workflow_projection(project_id, current_episode_id)
        workflow_nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
        if not _workflow_has_generated_work_chain(workflow, workflow_nodes):
            warnings.append(f"{current_episode_id} 尚未生成画布工作链")

    assets = list_assets("project", project_id, hydrate=False, lifecycle_status=ASSET_LIFECYCLE_ACTIVE)
    for asset_type, label in (("characters", "角色"), ("creatures", "生物"), ("scenes", "场景"), ("props", "道具")):
        rows = assets.get(asset_type)
        if not isinstance(rows, list):
            continue
        for index, item in enumerate(rows, start=1):
            if not isinstance(item, dict):
                continue
            if not str(item.get("desc") or "").strip():
                warnings.append(f"{label}资产「{item.get('name') or item.get('id') or index}」缺少资产描述")
            if asset_type == "characters" and not str(item.get("voiceStyle") or item.get("voice_style") or "").strip():
                warnings.append(f"角色资产「{item.get('name') or item.get('id') or index}」缺少角色声线设计 voiceStyle")
            if (
                asset_type == "creatures"
                and bool(item.get("canSpeak") or item.get("can_speak"))
                and not str(item.get("voiceStyle") or item.get("voice_style") or "").strip()
            ):
                warnings.append(f"生物资产「{item.get('name') or item.get('id') or index}」标记为可说话但缺少语气设计 voiceStyle")

    for current_episode_id in [item for item in selected_episode_ids if item]:
        workflow = get_canvas_workflow_projection(project_id, current_episode_id)
        workflow_asset_blocking, workflow_asset_warnings = _validate_workflow_asset_refs(
            project_id,
            current_episode_id,
            workflow,
        )
        blocking.extend(workflow_asset_blocking)
        warnings.extend(workflow_asset_warnings)
        stage_node_ids = _quality_node_ids_for_generation_task(
            generation_task_type,
            workflow,
            generation_node_id,
        )
        episode_range = _episode_range_for_id(project_id, current_episode_id)
        for node in workflow.get("nodes", []):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "")
            node_type = str(node.get("type") or "")
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            generation_config = data.get("generationConfig") if isinstance(data.get("generationConfig"), dict) else {}
            resolved_config = data.get("resolvedConfig") if isinstance(data.get("resolvedConfig"), dict) else {}
            node_strategy = str(node.get("strategy") or data.get("strategy") or "").strip()
            if not node_strategy:
                node_route_id = str(node.get("routeId") or data.get("routeId") or "").strip()
                for route in workflow.get("routes", []):
                    if isinstance(route, dict) and str(route.get("id") or route.get("routeId") or "").strip() == node_route_id:
                        node_strategy = str(route.get("strategy") or "").strip()
                        break
            text_to_video_node = node_type.startswith("video") and node_strategy == "text_to_video_draft"
            is_generation_node = node_type in {"prompt.storyboard", "video.storyboard"}
            if is_generation_node:
                if stage_node_ids is not None and node_id not in stage_node_ids:
                    continue
                has_prompt = any(
                    str(data.get(key) or "").strip()
                    for key in ("prompt", "summary", "storyboardImagePrompt", "videoPrompt", "episodeScript", "script")
                )
                if not has_prompt:
                    blocking.append(f"{current_episode_id} 节点 {node_id} 缺少提示词或摘要")
                refs = _shot_source_refs(data) or _shot_source_refs(node)
                if not refs:
                    blocking.append(f"{current_episode_id} 节点 {node_id} 缺少 sourceRefs")
                else:
                    for ref in refs:
                        if not _source_ref_in_episode_range(ref, current_episode_id, episode_range):
                            blocking.append(f"{current_episode_id} 节点 {node_id} sourceRefs 不属于本集原文范围")
                            continue
                        if not _source_ref_has_valid_unit_ref(project_id, ref, episode_range):
                            blocking.append(f"{current_episode_id} 节点 {node_id} sourceRefs 缺少有效 sourceUnitId/sourceUnitIds")
                reference_ids = _string_list(
                    data.get("referenceMediaIds")
                    or generation_config.get("referenceMediaIds")
                    or resolved_config.get("referenceMediaIds")
                    or []
                )
                has_upstream_active_reference = False
                if node_type.startswith("video"):
                    try:
                        from .workflow_input_resolution import workflow_current_media_version_has_media
                    except Exception:
                        workflow_current_media_version_has_media = None
                    for reference_node_id in workflow_storyboard_reference_node_ids(workflow, node_id=node_id):
                        if (
                            workflow_current_media_version_has_media
                            and workflow_current_media_version_has_media(
                                project_id,
                                current_episode_id,
                                workflow,
                                reference_node_id,
                            )
                        ):
                            has_upstream_active_reference = True
                            break
                if (
                    node_type.startswith(("video", "keyframe"))
                    and not text_to_video_node
                    and not data.get("referencePlan")
                    and not reference_ids
                    and not has_upstream_active_reference
                ):
                    blocking.append(f"{current_episode_id} 节点 {node_id} 缺少参考图来源")
    return {
        "success": not blocking,
        "projectId": project_id,
        "episodeId": episode_id or None,
        "qualityGates": {
            "blockingCount": len(blocking),
            "blockingIssueCount": len(blocking),
            "warningCount": len(warnings),
        },
        "blockingIssues": blocking,
        "warnings": warnings,
        "coverage": {
            "episodeRangeCount": len(ranges),
            "assetRangeCount": len(asset_ranges),
            "episodeCursor": coverage.get("episodeCursor"),
            "assetCursor": coverage.get("assetCursor"),
        },
    }


def _update_agent_workflow(
    project_id: str,
    episode_id: str,
    chunk: str,
    panel_count: int,
    panels: list[dict[str, Any]] | None = None,
    episode_script: str = "",
) -> None:
    workflow = get_canvas_workflow_projection(project_id, episode_id)
    patched_nodes: list[dict[str, Any]] = []
    panel_titles = []
    if isinstance(panels, list):
        for panel in panels[:panel_count]:
            if isinstance(panel, dict):
                panel_titles.append(str(panel.get("title") or panel.get("visualPrompt") or "").strip())
    panel_summary = "；".join(item for item in panel_titles if item)
    source_chunk = str(chunk or "").strip()
    script_text = str(episode_script or "").strip()
    script_summary = _compact_text(script_text, 140)
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "")
        data = node.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            node["data"] = data
        if node_type == "source.text":
            data["status"] = "ready"
            data["summary"] = _compact_text(source_chunk, 120) or "已写入当前分集源文本。"
            data["sourceText"] = source_chunk
            if script_text:
                data["episodeScript"] = script_text
            patched_nodes.append(copy.deepcopy(node))
        elif node_type == "prompt.storyboard":
            data["status"] = "ready"
            data["summary"] = (
                panel_summary or script_summary or f"已生成 {panel_count} 个连续分镜的任务卡草稿。"
            )
            if panels:
                data["panels"] = panels[:panel_count]
            if script_text:
                data["episodeScript"] = script_text
                data["script"] = script_text
            patched_nodes.append(copy.deepcopy(node))
        elif node_type == "storyboard.image":
            data["status"] = data.get("status") or "waiting"
            data["summary"] = data.get("summary") or "等待根据片段剧本生成故事版分镜图。"
            patched_nodes.append(copy.deepcopy(node))
        elif node_type.startswith("video."):
            data["status"] = data.get("status") or "waiting"
            data["summary"] = data.get("summary") or "等待生成分镜视频片段。"
            patched_nodes.append(copy.deepcopy(node))
    if patched_nodes:
        write_canvas_card_records_v4(project_id, episode_id, patched_nodes)
        _touch_project_meta(project_id)
