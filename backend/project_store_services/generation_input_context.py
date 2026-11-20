# -*- coding: utf-8 -*-
"""生成任务的节点、范围、提示词来源和用户覆盖输入解析。"""
from __future__ import annotations


from .canvas_ownership import (
    is_video_task_type,
    video_task_scope as canvas_video_task_scope,
)
from .planning_contract import (
    _workflow_prompt_text_value,
)
from .planning_workflow_inputs import (
    _normalize_multiline_prompt_text,
    _safe_video_prompt_text,
)
from .work_chain_context import (
    card_text,
    script_source_text,
    work_chain_stage_node,
)
from typing import (
    Any,
)


GENERATION_USER_INSTRUCTION_KEYS = (
    "userInstruction",
    "user_instruction",
    "revisionInstruction",
    "revision_instruction",
    "feedback",
)


def _first_mapping_text(source: dict[str, Any] | None, *keys: str) -> str:
    row = source if isinstance(source, dict) else {}
    for key in keys:
        value = row.get(key)
        if isinstance(value, (dict, list, tuple, set)):
            continue
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _generation_user_instruction(source: dict[str, Any] | None) -> str:
    return _first_mapping_text(source, *GENERATION_USER_INSTRUCTION_KEYS)


def _workflow_video_task_scope_for_config(
    payload: dict[str, Any],
    node: dict[str, Any] | None,
) -> str:
    if isinstance(node, dict):
        return canvas_video_task_scope(node)
    scope = payload.get("videoTaskScope")
    return scope if scope in {"work_chain", "standalone"} else ""


def _asset_refs_resolved_by_input_links(*sources: Any) -> bool:
    for source in sources:
        if not isinstance(source, dict):
            continue
        if _truthy_payload_flag(source.get("assetRefsResolvedByInputLinks")):
            return True
        for key in ("resolvedConfig", "generationConfig", "videoTaskCard", "storyboardTaskCard", "directorTaskCard"):
            nested = source.get(key)
            if isinstance(nested, dict) and _asset_refs_resolved_by_input_links(nested):
                return True
    return False


def _workflow_route_by_id(workflow: dict[str, Any], route_id: str) -> dict[str, Any]:
    for route in workflow.get("routes", []):
        if isinstance(route, dict) and str(route.get("id") or "") == route_id:
            return route
    return {}


def _workflow_node_by_id(workflow: dict[str, Any], node_id: str) -> dict[str, Any]:
    for node in workflow.get("nodes", []):
        if isinstance(node, dict) and str(node.get("id") or "") == node_id:
            return node
    return {}


def _workflow_prompt_text(
    data: dict[str, Any],
    media_type: str,
    *,
    include_fallback_fields: bool = True,
) -> str:
    preferred_prompt_keys = (
        (
            "videoPrompt",
            "video_prompt",
            "prompt",
            "action",
            "cameraMotion",
            "temporalContinuity",
        )
        if media_type == "video"
        else (
            "cinematicStoryText",
            "cinematic_story_text",
            "sceneBrief",
            "scene_brief",
            "userNotes",
            "user_notes",
            "dialogueText",
            "dialogue_text",
            "storyboardImagePrompt",
            "imagePrompt",
            "visualPrompt",
            "prompt",
            "action",
            "camera",
        )
    )
    sources = [data.get("prompt"), data.get("screenplay")]
    if include_fallback_fields:
        sources.extend([data.get("summary"), data.get("description"), data.get("script")])
    for source in sources:
        text = _workflow_prompt_text_value(source, preferred_prompt_keys)
        if text:
            if media_type == "video":
                return _safe_video_prompt_text(text)
            return _normalize_multiline_prompt_text(text)
    return ""


def _workflow_node_data_dict(node: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(node, dict):
        return {}
    data = node.get("data")
    return data if isinstance(data, dict) else {}


def _workflow_node_type_name(node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return ""
    return str(node.get("type") or "").strip()


def _workflow_generation_config_source_node(
    workflow: dict[str, Any],
    node: dict[str, Any],
    media_type: str,
) -> dict[str, Any]:
    # Keep the legacy call signature, but use the execution-side ownership rules.
    from .workflow_generation_config import _workflow_generation_config_source_node as resolve_owner

    return resolve_owner(workflow, node) or {}


def _workflow_resolved_prompt_text(
    workflow: dict[str, Any],
    node: dict[str, Any],
    media_type: str,
) -> tuple[str, str]:
    data = _workflow_node_data_dict(node)
    node_type = _workflow_node_type_name(node)
    if node_type == "prompt.storyboard":
        return script_source_text(data), str(node.get("id") or "")
    if node_type in {"director.board", "storyboard.image"} and (node.get("workChainId") or node_type == "director.board"):
        director = work_chain_stage_node(workflow, node, "director.board")
        return card_text(_workflow_node_data_dict(director), "directorPlan"), str((director or {}).get("id") or "")
    if is_video_task_type(node_type) or node_type == "video.result":
        video = _workflow_generation_config_source_node(workflow, node, "video")
        video_data = _workflow_node_data_dict(video)
        return card_text(video_data.get("videoTaskCard"), "finalVideoPrompt"), str((video or {}).get("id") or "")
    return _workflow_prompt_text(data, media_type), str(node.get("id") or "")


def _truthy_payload_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _video_generation_node_id_from_payload(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
    *,
    workflow: dict[str, Any] | None = None,
) -> str:
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    if node_id:
        from .workflow_projection import get_canvas_workflow_projection
        from .workflow_input_resolution import resolve_generation_task_node_id

        workflow = workflow if isinstance(workflow, dict) else get_canvas_workflow_projection(project_id, episode_id)
        return (
            resolve_generation_task_node_id(
                workflow,
                "storyboard_video",
                node_id,
            )
            or node_id
        )
    route_id = str(payload.get("routeId") or payload.get("route_id") or "").strip()
    if not route_id:
        return ""
    from .workflow_projection import get_canvas_workflow_projection
    from .workflow_input_resolution import resolve_generation_task_node_id

    workflow = workflow if isinstance(workflow, dict) else get_canvas_workflow_projection(project_id, episode_id)
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "").strip()
        if node_type not in {"video.storyboard",  "video.result"}:
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        current_route_id = str(node.get("routeId") or data.get("routeId") or "").strip()
        if current_route_id == route_id:
            return (
                resolve_generation_task_node_id(
                    workflow,
                    "storyboard_video",
                    str(node.get("id") or "").strip(),
                )
                or str(node.get("id") or "").strip()
            )
    return ""


def _work_chain_video_task_ids_for_director(
    workflow: dict[str, Any],
    director_node_id: str,
) -> list[str]:
    normalized_director_id = str(director_node_id or "").strip()
    if not normalized_director_id:
        return []
    from .workflow_input_resolution import workflow_storyboard_image_director_node_id
    from .workflow_input_resolution import workflow_video_task_work_chain_storyboard_node_ids

    result: list[str] = []
    for node in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
        if not isinstance(node, dict) or _workflow_node_type_name(node) != "video.storyboard":
            continue
        video_node_id = str(node.get("id") or "").strip()
        if not video_node_id or video_node_id in result:
            continue
        storyboard_node_ids = workflow_video_task_work_chain_storyboard_node_ids(
            workflow,
            node,
        )
        if any(
            workflow_storyboard_image_director_node_id(workflow, storyboard_node_id)
            == normalized_director_id
            for storyboard_node_id in storyboard_node_ids
        ):
            result.append(video_node_id)
    return result
