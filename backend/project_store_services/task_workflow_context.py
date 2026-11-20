# -*- coding: utf-8 -*-
"""任务关联画布节点、工作链、结果卡和显示标题。"""
from __future__ import annotations

from .canvas_store_queries import read_workflow_card_neighborhood_v4
from .project_management import get_effective_config
from .task_contract import _storyboard_video_task_node_type
from .work_chain_context import card_text
from .work_chain_context import work_chain_stage_node
from .workflow_contract import _workflow_node
from .workflow_input_resolution import resolve_generation_task_node_id
from .workflow_generation_context import validate_workflow_node_inputs_ready
from typing import Any
import copy
import re


def _video_generation_debug_block_enabled(project_id: str) -> bool:
    try:
        config = get_effective_config(project_id)
    except Exception:
        return False
    video_config = config.get("video") if isinstance(config.get("video"), dict) else {}
    return bool(
        video_config.get("generation_debug_block_enabled")
        or video_config.get("generationDebugBlockEnabled")
        or video_config.get("block_generation_debug_mode")
        or video_config.get("blockGenerationDebugMode")
        or config.get("videoGenerationDebugBlockEnabled")
    )


def _canvas_task_context_workflow(
    project_id: str,
    episode_id: str,
    node_id: str,
    *,
    detail: str = "full",
) -> dict[str, Any]:
    detail = "summary" if str(detail or "").strip().lower() == "summary" else "full"
    if not project_id or not episode_id or not str(node_id or "").strip():
        return {}
    return read_workflow_card_neighborhood_v4(project_id, episode_id, node_id, detail=detail)


def _workflow_task_focus_target(
    episode_id: str | None,
    node_id: str | None,
    *,
    version_id: str | None = None,
) -> dict[str, Any]:
    target = {
        "section": "episode",
        "episodeId": episode_id or "",
        "nodeId": node_id or "",
    }
    if version_id:
        target["versionId"] = version_id
    return target


def _workflow_node_title(workflow: dict[str, Any], node_id: str | None, fallback: str = "") -> str:
    node = _workflow_node(workflow, str(node_id or "").strip()) if node_id else None
    if not isinstance(node, dict):
        return fallback
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(
        data.get("title")
        or data.get("name")
        or node.get("title")
        or node.get("label")
        or fallback
    ).strip()


_GENERATION_GENERIC_OUTPUT_TITLE_KEYS = {
    re.sub(r"\s+", "", item).lower()
    for item in (
        "生成版本",
        "任务",
        "分镜",
        "片段剧本",
        "分镜图",
        "分镜图资产",
        "分镜图",
        "分镜图结果卡",
        "故事版分镜图",
        "当前分镜图",
        "视频",
        "视频片段",
        "视频片段",
        "故事版视频",
        "最终视频",
        "当前视频",
        "视频提示词",
        "视频提示词",
        "视频任务",
        "视频生成",
        "影视化剧本",
    )
}


def _generation_meaningful_title(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.sub(r"\s+", "", text).lower() in _GENERATION_GENERIC_OUTPUT_TITLE_KEYS:
        return ""
    return text


def _generation_title_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _generation_output_text(title: Any, output_label: str, suffix: str) -> str:
    clean_title = str(title or "").strip()
    if not clean_title:
        return f"{output_label}{suffix}"
    if _generation_title_key(clean_title).endswith(_generation_title_key(output_label)):
        return f"{clean_title}{suffix}"
    return f"{clean_title}{output_label}{suffix}"


def _generation_output_success_text(title: Any, output_label: str) -> str:
    return _generation_output_text(title, output_label, "已生成成功")


def _generation_output_created_message(title: Any, output_label: str) -> str:
    return _generation_output_text(title, output_label, "生成任务已创建。")


def _generation_output_running_message(title: Any, output_label: str) -> str:
    return _generation_output_text(title, output_label, "正在生成。")


def _workflow_node_meaningful_title(
    workflow: dict[str, Any],
    node_id: str | None,
    *fallbacks: Any,
) -> str:
    node = _workflow_node(workflow, str(node_id or "").strip()) if node_id else None
    data = node.get("data") if isinstance((node or {}).get("data"), dict) else {}
    for value in (
        data.get("assetName"),
        data.get("title"),
        data.get("name"),
        (node or {}).get("title"),
        (node or {}).get("label"),
        *fallbacks,
    ):
        title = _generation_meaningful_title(value)
        if title:
            return title
    return ""


def _workflow_route_by_id(workflow: dict[str, Any], route_id: str | None) -> dict[str, Any] | None:
    normalized_route_id = str(route_id or "").strip()
    if not normalized_route_id:
        return None
    for route in workflow.get("routes", []):
        if not isinstance(route, dict):
            continue
        if str(route.get("id") or route.get("routeId") or "").strip() == normalized_route_id:
            return route
    return None


def _workflow_work_chain_display_name(work_chain: dict[str, Any], index: int) -> str:
    raw = str(work_chain.get("label") or work_chain.get("title") or "").strip()
    if not raw:
        return f"第 {index + 1} 条工作链"
    stripped = re.sub(
        r"^(?:(?:锚点|工作链)\s*[一二三四五六七八九十百千万零〇两\d]+\s*)+",
        "",
        raw,
    )
    stripped = re.sub(r"^[:：、,，/／|·•>\-\s]+", "", stripped).strip()
    return stripped or raw


def _workflow_work_chain_by_id(
    workflow: dict[str, Any],
    work_chain_id: str | None,
) -> tuple[dict[str, Any] | None, int]:
    normalized_work_chain_id = str(work_chain_id or "").strip()
    if not normalized_work_chain_id:
        return None, -1
    for index, work_chain in enumerate(workflow.get("workChains", []) or []):
        if not isinstance(work_chain, dict):
            continue
        if str(work_chain.get("id") or work_chain.get("workChainId") or "").strip() == normalized_work_chain_id:
            return work_chain, index
    return None, -1


def _workflow_task_work_chain_fields(
    workflow: dict[str, Any],
    node_id: str | None,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    node = _workflow_node(workflow, str(node_id or "").strip()) if node_id else None
    data = node.get("data") if isinstance((node or {}).get("data"), dict) else {}
    route_id = str(
        payload.get("routeId")
        or payload.get("route_id")
        or (node or {}).get("routeId")
        or data.get("routeId")
        or data.get("route_id")
        or ""
    ).strip()
    route = _workflow_route_by_id(workflow, route_id)
    work_chain_id = str(
        payload.get("workChainId")
        or payload.get("work_chain_id")
        or (node or {}).get("workChainId")
        or data.get("workChainId")
        or data.get("work_chain_id")
        or (route or {}).get("workChainId")
        or (route or {}).get("work_chain_id")
        or ""
    ).strip()
    if not route and work_chain_id:
        for candidate in workflow.get("routes", []) or []:
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("workChainId") or candidate.get("work_chain_id") or "").strip() == work_chain_id:
                route = candidate
                route_id = str(candidate.get("id") or candidate.get("routeId") or route_id or "").strip()
                break
    work_chain, work_chain_index = _workflow_work_chain_by_id(workflow, work_chain_id)
    fields: dict[str, Any] = {}
    if route_id:
        fields["routeId"] = route_id
    route_label = str((route or {}).get("label") or (route or {}).get("title") or "").strip()
    if route_label:
        fields["routeLabel"] = route_label
    if work_chain_id:
        fields["workChainId"] = work_chain_id
    if work_chain:
        work_chain_label = _workflow_work_chain_display_name(work_chain, max(work_chain_index, 0))
        if work_chain_label:
            fields["workChainLabel"] = work_chain_label
            fields["workChainTitle"] = work_chain_label
            fields["workChainName"] = work_chain_label
    else:
        fallback_label = str(
            payload.get("workChainLabel")
            or payload.get("work_chain_label")
            or payload.get("workChainTitle")
            or payload.get("work_chain_title")
            or data.get("workChainLabel")
            or data.get("work_chain_label")
            or data.get("workChainTitle")
            or data.get("work_chain_title")
            or ""
        ).strip()
        if fallback_label:
            fields["workChainLabel"] = fallback_label
            fields["workChainTitle"] = fallback_label
            fields["workChainName"] = fallback_label
    return fields


def _task_stored_work_chain_fields(
    task: dict[str, Any] | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = task if isinstance(task, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    fields: dict[str, Any] = {}
    aliases = {
        "routeId": ("routeId", "route_id"),
        "routeLabel": ("routeLabel", "route_label"),
        "workChainId": ("workChainId", "work_chain_id"),
        "workChainLabel": ("workChainLabel", "work_chain_label"),
        "workChainTitle": ("workChainTitle", "work_chain_title"),
        "workChainName": ("workChainName", "work_chain_name"),
        "segmentId": ("segmentId", "segment_id"),
    }
    for output_key, keys in aliases.items():
        value = next(
            (
                row.get(key)
                for row in (task, payload)
                for key in keys
                if isinstance(row, dict) and str(row.get(key) or "").strip()
            ),
            "",
        )
        if value:
            fields[output_key] = value
    label = str(
        fields.get("workChainLabel")
        or fields.get("workChainTitle")
        or fields.get("workChainName")
        or ""
    ).strip()
    if label:
        fields.setdefault("workChainLabel", label)
        fields.setdefault("workChainTitle", label)
        fields.setdefault("workChainName", label)
    return fields


def _workflow_storyboard_script_text_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value).strip()
    if isinstance(value, dict):
        for key in (
            "cinematicStoryText",
            "cinematic_story_text",
        ):
            text = _workflow_storyboard_script_text_value(value.get(key))
            if text:
                return text
    if isinstance(value, list):
        rows = [
            _workflow_storyboard_script_text_value(item)
            for item in value
        ]
        return "\n".join(item for item in rows if item).strip()
    return ""


def _workflow_storyboard_cinematic_script_text(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    task_card = data.get("storyboardTaskCard") if isinstance(data.get("storyboardTaskCard"), dict) else {}
    prompt = data.get("prompt") if isinstance(data.get("prompt"), dict) else {}
    for value in (
        data.get("cinematicStoryText"),
        data.get("cinematic_story_text"),
        task_card.get("cinematicStoryText"),
        task_card.get("cinematic_story_text"),
        prompt.get("cinematicStoryText"),
        prompt.get("cinematic_story_text"),
    ):
        text = _workflow_storyboard_script_text_value(value)
        if text:
            return text
    return ""


def _assert_storyboard_image_has_required_director_context(
    workflow: dict[str, Any],
    selected_node_id: str,
    requested_node_id: str | None = None,
) -> None:
    current = _workflow_node(workflow, str(selected_node_id or requested_node_id or ""))
    director = work_chain_stage_node(workflow, current, "director.board")
    if not director or not card_text(director.get("data"), "directorPlan"):
        raise ValueError("请先填写或生成分镜脚本，再生成分镜图")


def _visual_handoff_prompt_node_id_for_request(
    workflow: dict[str, Any],
    requested_node_id: str | None,
) -> str:
    requested_id = str(requested_node_id or "").strip()
    requested_node = _workflow_node(workflow, requested_id) if requested_id else None
    requested_type = str((requested_node or {}).get("type") or "").strip()
    requested_data = requested_node.get("data") if isinstance((requested_node or {}).get("data"), dict) else {}
    if requested_node and requested_type == "storyboard.card" and requested_data.get("shotGroupId"):
        return requested_id
    is_visual_handoff = str(
        requested_data.get("mediaPurpose")
        or requested_data.get("media_purpose")
        or requested_data.get("assetKind")
        or requested_data.get("asset_kind")
        or requested_data.get("assetType")
        or requested_data.get("asset_type")
        or ""
    ).strip() == "visual_handoff"
    if requested_node and requested_type == "asset.image" and is_visual_handoff:
        return str(requested_data.get("resultOfNodeId") or requested_data.get("sourceNodeId") or "").strip()
    return ""


def _visual_handoff_canvas_payload_from_ensure_result(ensure_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ensure_result, dict):
        return {}
    return {
        key: copy.deepcopy(ensure_result.get(key))
        for key in (
            "nodes",
            "edges",
            "inputLink",
            "workflowOmitted",
            "workflowVersion",
            "changedResources",
        )
        if ensure_result.get(key)
    }


def _workflow_generation_source_matches_task_type(node_type: str, task_type: str) -> bool:
    normalized_task_type = str(task_type or "").strip()
    if normalized_task_type in {"storyboard_image", "storyboard_image_edit"}:
        return str(node_type or "").strip() == "director.board"
    if normalized_task_type == "visual_handoff_image":
        return str(node_type or "").strip() == "storyboard.card"
    if normalized_task_type in {"storyboard_video", "route_video"}:
        return _storyboard_video_task_node_type(node_type)
    return False


def _workflow_generation_source_node_id(
    workflow: dict[str, Any],
    result_node_id: str | None,
    task_type: str,
) -> str:
    target_id = str(result_node_id or "").strip()
    if not target_id:
        return ""
    result_node = _workflow_node(workflow, target_id) or {}
    data = result_node.get("data") if isinstance(result_node.get("data"), dict) else {}
    for value in (data.get("resultOfNodeId"), data.get("sourceNodeId")):
        source_id = str(value or "").strip()
        source_node = _workflow_node(workflow, source_id) if source_id else None
        source_type = str((source_node or {}).get("type") or "")
        if source_node and _workflow_generation_source_matches_task_type(source_type, task_type):
            return source_id
    for edge in workflow.get("edges", []):
        if not isinstance(edge, dict) or str(edge.get("target") or "").strip() != target_id:
            continue
        source_id = str(edge.get("source") or "").strip()
        source_node = _workflow_node(workflow, source_id) if source_id else None
        source_type = str((source_node or {}).get("type") or "")
        if source_node and _workflow_generation_source_matches_task_type(source_type, task_type):
            return source_id
    return ""


def _workflow_generation_output_title(
    workflow: dict[str, Any],
    node_id: str | None,
    task_type: str,
    *,
    fallback_title: Any = "",
) -> str:
    title = _workflow_node_meaningful_title(workflow, node_id)
    if title:
        return title
    source_node_id = _workflow_generation_source_node_id(workflow, node_id, task_type)
    source_title = _workflow_node_meaningful_title(workflow, source_node_id)
    if source_title:
        return source_title
    return _generation_meaningful_title(fallback_title)


def _workflow_result_node_for_task(
    workflow: dict[str, Any],
    task_node_id: str,
    result_node_type: str,
) -> str:
    task_node_id = str(task_node_id or "").strip()
    result_node_type = str(result_node_type or "").strip()
    if not task_node_id or not result_node_type:
        return ""
    for edge in workflow.get("edges", []):
        if not isinstance(edge, dict) or str(edge.get("source") or "").strip() != task_node_id:
            continue
        target_id = str(edge.get("target") or "").strip()
        target_node = _workflow_node(workflow, target_id) if target_id else None
        if not isinstance(target_node, dict) or str(target_node.get("type") or "").strip() != result_node_type:
            continue
        edge_data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        role = str(edge_data.get("role") or "").strip()
        target_slot = str(edge.get("targetHandle") or edge_data.get("targetSlot") or edge_data.get("slot") or "").strip()
        if not role or role == "generates" or target_slot in {"generates", "video_result"}:
            return target_id
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict) or str(node.get("type") or "").strip() != result_node_type:
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if str(data.get("resultOfNodeId") or data.get("sourceNodeId") or "").strip() == task_node_id:
            return str(node.get("id") or "").strip()
    return ""


def _workflow_task_node_for_result(
    workflow: dict[str, Any],
    result_node_id: str,
) -> str:
    result_node_id = str(result_node_id or "").strip()
    result_node = _workflow_node(workflow, result_node_id) if result_node_id else None
    data = result_node.get("data") if isinstance((result_node or {}).get("data"), dict) else {}
    for value in (data.get("resultOfNodeId"), data.get("sourceNodeId")):
        candidate_id = str(value or "").strip()
        candidate = _workflow_node(workflow, candidate_id) if candidate_id else None
        if isinstance(candidate, dict) and _storyboard_video_task_node_type(candidate.get("type")):
            return candidate_id
    for edge in workflow.get("edges", []):
        if not isinstance(edge, dict) or str(edge.get("target") or "").strip() != result_node_id:
            continue
        source_id = str(edge.get("source") or "").strip()
        source_node = _workflow_node(workflow, source_id) if source_id else None
        if isinstance(source_node, dict) and _storyboard_video_task_node_type(source_node.get("type")):
            return source_id
    return ""


def _resolve_storyboard_video_task_and_result_nodes(
    workflow: dict[str, Any],
    node_id: str | None,
) -> tuple[str, str]:
    requested_id = str(node_id or "").strip()
    requested_node = _workflow_node(workflow, requested_id) if requested_id else None
    requested_type = str((requested_node or {}).get("type") or "").strip()
    task_node_id = ""
    result_node_id = ""
    if _storyboard_video_task_node_type(requested_type):
        task_node_id = requested_id
        result_node_id = _workflow_result_node_for_task(workflow, task_node_id, "video.result")
    elif requested_type == "video.result":
        result_node_id = requested_id
        task_node_id = _workflow_task_node_for_result(workflow, result_node_id)
    else:
        resolved_id = resolve_generation_task_node_id(workflow, "storyboard_video", requested_id)
        resolved_node = _workflow_node(workflow, resolved_id) if resolved_id else None
        resolved_type = str((resolved_node or {}).get("type") or "").strip()
        if _storyboard_video_task_node_type(resolved_type):
            task_node_id = resolved_id
            result_node_id = _workflow_result_node_for_task(workflow, task_node_id, "video.result")
        elif resolved_type == "video.result":
            result_node_id = resolved_id
            task_node_id = _workflow_task_node_for_result(workflow, result_node_id)
    if task_node_id and not result_node_id:
        result_node_id = _workflow_result_node_for_task(workflow, task_node_id, "video.result")
    return task_node_id or requested_id, result_node_id


def _generation_success_notice(
    workflow: dict[str, Any],
    node_id: str,
    task_type: str,
    *,
    fallback_title: str = "",
) -> str:
    title = _workflow_generation_output_title(
        workflow,
        node_id,
        task_type,
        fallback_title=fallback_title,
    ).strip()
    if task_type == "storyboard_image":
        return _generation_output_success_text(title, "分镜图")
    if task_type == "visual_handoff_image":
        return _generation_output_success_text(title, "视觉交接图")
    if task_type == "storyboard_video":
        return _generation_output_success_text(title, "视频")
    return f"{title or '任务'}已完成"


def _assert_generation_closure_ready(
    project_id: str,
    episode_id: str,
    task_type: str,
    *,
    node_id: str | None = None,
    workflow: dict[str, Any] | None = None,
    video_task_scope: str | None = None,
) -> None:
    # Video execution is validated against the final card and resolved references.
    # Director/source quality gates apply only while preparing storyboard images.
    if task_type != "storyboard_image":
        return
    current_workflow = workflow if isinstance(workflow, dict) else _canvas_task_context_workflow(project_id, episode_id, str(node_id or ""))
    _assert_storyboard_image_has_required_director_context(current_workflow, str(node_id or ""))
    validate_workflow_node_inputs_ready(project_id, episode_id, {"nodeId": node_id}, workflow=current_workflow)
