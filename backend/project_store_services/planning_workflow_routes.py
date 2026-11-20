# -*- coding: utf-8 -*-
"""工作链路线规则与附加路线投影。"""
from __future__ import annotations

import copy
from .planning_contract import (
    _WORKFLOW_VIDEO_INPUT_HANDLE,
    _explicit_storyboard_template_id,
    _node_capability_requirements,
    _node_model_selection,
    _normalize_video_generation_strategy,
    _route_reference_specs,
    _safe_workflow_id,
    _video_node_type_for_strategy,
    _video_task_generation_config,
    _workflow_card_template_fields,
    _workflow_shot_timing_plan_duration,
    _workflow_shot_timing_plan_for_segment,
    _workflow_storyboard_template_fields,
)
from .planning_workflow_assets import (
    _asset_ref_canvas_materials,
)
from .planning_workflow_inputs import (
    _compact_multiline_prompt_text,
    _normalize_multiline_prompt_text,
    _segment_prompts,
    _shot_plan_generation_config,
    _shot_text,
    _workflow_apply_timing_to_shots,
)
from .source_text_store import _compact_text
from .splitting_templates import (
    _string_list,
)
from .storyboard_templates import (
    storyboard_template_label,
)
from typing import (
    Any,
)


def _segment_route_specs(segment: dict[str, Any], default_strategy: str) -> list[dict[str, Any]]:
    raw_routes: Any = None
    for key in (
        "routes",
        "candidateRoutes",
        "candidate_routes",
        "routeCandidates",
        "route_candidates",
        "generationRoutes",
        "generation_routes",
        "strategies",
        "generationStrategies",
    ):
        value = segment.get(key)
        if isinstance(value, list) and value:
            raw_routes = value
            break
        if isinstance(value, dict) and value:
            raw_routes = list(value.values())
            break
    if not raw_routes:
        raw_routes = [{"strategy": default_strategy}]

    specs: list[dict[str, Any]] = []
    for index, item in enumerate(raw_routes, start=1):
        if isinstance(item, str):
            spec: dict[str, Any] = {"strategy": item}
        elif isinstance(item, dict):
            spec = copy.deepcopy(item)
        else:
            continue
        strategy = str(
            spec.get("strategy")
            or spec.get("generationStrategy")
            or spec.get("generation_strategy")
            or spec.get("type")
            or default_strategy
            or "storyboard_multi_shot"
        ).strip() or "storyboard_multi_shot"
        spec["strategy"] = strategy
        spec["routeIndex"] = index
        specs.append(spec)
    return specs or [{"strategy": default_strategy or "storyboard_multi_shot", "routeIndex": 1}]


def _route_spec_id(segment_id: str, strategy: str, spec: dict[str, Any], segment_index: int, route_index: int) -> str:
    explicit_id = str(spec.get("routeId") or spec.get("route_id") or spec.get("id") or "").strip()
    fallback = (
        f"route_{segment_id}_{strategy}"
        if route_index == 1
        else f"route_{segment_id}_{route_index:02d}_{strategy}"
    )
    return _safe_workflow_id(explicit_id or fallback, f"route_{segment_index:03d}_{route_index:02d}")


def _route_spec_label(segment: dict[str, Any], spec: dict[str, Any], segment_index: int, route_index: int) -> str:
    base_title = str(segment.get("title") or f"Segment {segment_index}")
    return str(
        spec.get("label")
        or spec.get("title")
        or spec.get("name")
        or (base_title if route_index == 1 else f"{base_title} 方案 {route_index}")
    )


def _route_spec_asset_refs(segment: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    value = spec.get("assetRefs") or spec.get("asset_refs") or segment.get("assetRefs") or {}
    return copy.deepcopy(value if isinstance(value, dict) else {})


def _route_spec_reference_plan(segment: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    value = spec.get("referencePlan") or spec.get("reference_plan") or segment.get("referencePlan") or {}
    return copy.deepcopy(value if isinstance(value, dict) else {})


def _route_spec_prompts(segment: dict[str, Any], shots: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    prompts = copy.deepcopy(_segment_prompts(segment, shots))
    route_prompts = spec.get("prompts") if isinstance(spec.get("prompts"), dict) else {}
    for key in ("storyboardImagePrompt",):
        if key in route_prompts:
            prompts[key] = copy.deepcopy(route_prompts.get(key))
        elif key in spec:
            prompts[key] = copy.deepcopy(spec.get(key))
    return prompts


def _route_node_kind(node_type: str, strategy: str) -> str:
    if node_type == "storyboard.image":
        return "storyboard.image"
    if node_type in {"video.storyboard"}:
        return _video_node_type_for_strategy(strategy)
    if node_type == "video.result":
        return "video.result"
    return node_type


def _remap_route_link(
    link: dict[str, Any],
    node_id_map: dict[str, str],
    *,
    route_id: str,
    segment_id: str,
    work_chain_id: str,
    route_index: int,
) -> dict[str, Any]:
    cloned = copy.deepcopy(link)
    for key in ("sourceNodeId", "source_node_id", "targetNodeId", "target_node_id", "nodeId", "node_id"):
        text = str(cloned.get(key) or "").strip()
        if text in node_id_map:
            cloned[key] = node_id_map[text]
    cloned["routeId"] = route_id
    cloned["segmentId"] = segment_id
    cloned["workChainId"] = work_chain_id
    link_id = str(cloned.get("id") or "").strip()
    if link_id:
        cloned["id"] = _safe_workflow_id(f"{link_id}_{route_id}", f"{link_id}_{route_index:02d}")
    return cloned


def _apply_route_node_data(
    node: dict[str, Any],
    *,
    label: str,
    strategy: str,
    route_id: str,
    segment_id: str,
    work_chain_id: str,
    shots: list[dict[str, Any]],
    shot_ids: list[str],
    asset_refs: dict[str, Any],
    prompts: dict[str, Any],
    reference_plan: dict[str, Any],
    reference_media_ids: list[str],
    generation_config: dict[str, Any],
    quality: dict[str, Any],
    segment: dict[str, Any],
    input_links: list[dict[str, Any]],
) -> None:
    node_type = str(node.get("type") or "")
    shot_timing_plan = _workflow_shot_timing_plan_for_segment(segment, shots)
    duration_seconds = _workflow_shot_timing_plan_duration(shot_timing_plan)
    if shot_timing_plan:
        shots = _workflow_apply_timing_to_shots(shots, shot_timing_plan)
    video_generation_config = _video_task_generation_config(generation_config.get("video"))
    task_card = segment.get("storyboardTaskCard") if isinstance(segment.get("storyboardTaskCard"), dict) else {}
    source_preview = _compact_multiline_prompt_text(
        segment.get("sourcePreview")
        or segment.get("source_preview")
        or task_card.get("sourcePreview")
        or task_card.get("source_preview")
        or prompts.get("sourcePreview")
        or prompts.get("source_preview")
        or "",
        2400,
    )
    data = node.setdefault("data", {})
    if not isinstance(data, dict):
        data = {}
        node["data"] = data
    node["workChainId"] = work_chain_id
    node["routeId"] = route_id
    node["segmentId"] = segment_id
    node["strategy"] = strategy
    node["type"] = _route_node_kind(node_type, strategy)
    data.update(
        {
            "workChainId": work_chain_id,
            "routeId": route_id,
            "segmentId": segment_id,
            "strategy": strategy,
            "assetRefs": copy.deepcopy(asset_refs),
            "sourceRefs": copy.deepcopy(segment.get("sourceRefs") or []),
            "quality": copy.deepcopy(quality),
            "modelSelection": {},
            "capabilityRequirements": {},
        }
    )
    if node["type"] == "director.board":
        data["title"] = "分镜脚本"
        data["summary"] = _compact_text(str(segment.get("narrativePurpose") or "；".join(_shot_text(shot) for shot in shots[:3])), 180)
        data["inputLinks"] = copy.deepcopy(input_links)
        data["referenceMediaIds"] = copy.deepcopy(reference_media_ids)
        data["generationConfig"] = copy.deepcopy(generation_config.get("image") or {})
        data["modelSelection"] = _node_model_selection("image", generation_config)
        data["capabilityRequirements"] = _node_capability_requirements(strategy, generation_config, "image")
    elif node["type"] == "prompt.storyboard":
        for key in ("assetRefs", "asset_refs", "inputLinks", "referenceUsage", "assetThumbnails", "referenceThumbnails", "referenceDisplayRows"):
            data.pop(key, None)
        card_state = data.get("cardState")
        if isinstance(card_state, dict):
            card_state.pop("assetState", None)
        story_text = _normalize_multiline_prompt_text(
            segment.get("cinematicStoryText")
            or segment.get("cinematic_story_text")
            or task_card.get("cinematicStoryText")
            or task_card.get("cinematic_story_text")
            or "",
        )
        source_fact_text = _normalize_multiline_prompt_text(
            segment.get("sourceFactText")
            or segment.get("source_fact_text")
            or task_card.get("sourceFactText")
            or task_card.get("source_fact_text")
            or prompts.get("sourceFactText")
            or prompts.get("source_fact_text")
            or "",
        )
        data["title"] = "片段剧本"
        data["summary"] = _compact_text(str(source_fact_text or ""), 160) or "已生成原文事实，等待生成影视化剧本。"
        data["prompt"] = {
            "cinematicStoryText": story_text,
            "sourceFactText": source_fact_text,
        }
        data["cinematicStoryText"] = story_text
        data["sourceFactText"] = source_fact_text
        data["narrativeMode"] = "drama"
        data["sourcePreview"] = source_preview
        data["storyboardTaskCard"] = {
            **{key: value for key, value in task_card.items() if key not in {"assetRefs", "asset_refs", "assetState", "asset_state"}},
            "cinematicStoryText": story_text,
            "sourceFactText": source_fact_text,
            "state": "ready" if story_text else "pending_script",
            "scriptState": "ready" if story_text else "pending_script",
        }
        data["screenplay"] = copy.deepcopy(segment.get("screenplay") or {})
        data["dialogue"] = copy.deepcopy(segment.get("dialogue") or [])
    elif node["type"] == "storyboard.image":
        for key in ("assetRefs", "referenceMediaIds"):
            data.pop(key, None)
        data["title"] = "分镜图"
        data["referencePlan"] = copy.deepcopy(reference_plan)
    elif node["type"] in {"video.storyboard", "video.keyframe"}:
        for key in ("assetRefs", "assetThumbnails", "referenceMediaIds"):
            data.pop(key, None)
        data["title"] = "视频生成"
        data["prompt"] = {"videoPrompt": ""}
        data["generationConfig"] = video_generation_config
        data["modelSelection"] = _node_model_selection("video", {"video": video_generation_config})
        data["capabilityRequirements"] = _node_capability_requirements(
            strategy,
            {"video": video_generation_config},
            "video",
        )
    elif node["type"] == "video.result":
        data.pop("assetRefs", None)
        data["title"] = "视频片段"
        data["referenceMediaIds"] = copy.deepcopy(reference_media_ids)


def _expand_extra_segment_routes(
    *,
    project_id: str | None,
    routes: list[dict[str, Any]],
    work_chains: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    input_links: list[dict[str, Any]],
    route_expansions: list[dict[str, Any]],
    config: dict[str, Any],
) -> None:
    for expansion in route_expansions:
        specs = expansion.get("routeSpecs") if isinstance(expansion.get("routeSpecs"), list) else []
        if len(specs) <= 1:
            continue
        segment = expansion.get("segment") if isinstance(expansion.get("segment"), dict) else {}
        segment_id = str(expansion.get("segmentId") or "")
        work_chain_id = str(expansion.get("workChainId") or "")
        primary_route_id = str(expansion.get("primaryRouteId") or "")
        segment_index = int(expansion.get("segmentIndex") or 1)
        shots = copy.deepcopy(expansion.get("shots") if isinstance(expansion.get("shots"), list) else [])
        shot_timing_plan = _workflow_shot_timing_plan_for_segment(segment, shots)
        segment_duration_seconds = _workflow_shot_timing_plan_duration(shot_timing_plan)
        if shot_timing_plan:
            shots = _workflow_apply_timing_to_shots(shots, shot_timing_plan)
        shot_ids = [str(item) for item in expansion.get("shotIds") or [] if str(item)]
        primary_route = next((route for route in routes if isinstance(route, dict) and str(route.get("id") or "") == primary_route_id), None)
        if not primary_route:
            continue
        for route_index, spec in enumerate(specs[1:], start=2):
            strategy = _normalize_video_generation_strategy(
                spec.get("strategy") or primary_route.get("strategy") or "storyboard_multi_shot"
            )
            route_id = _route_spec_id(segment_id, strategy, spec, segment_index, route_index)
            if any(isinstance(route, dict) and str(route.get("id") or "") == route_id for route in routes):
                continue
            raw_label = _route_spec_label(segment, spec, segment_index, route_index)
            stage_title = str(
                segment.get("workChainTitle")
                or segment.get("workChainLabel")
                or segment.get("title")
                or raw_label
            ).strip()
            label = f"{stage_title} · 路线 {route_index}" if stage_title else f"原文事实段落 {segment_index}.{route_index}"
            generation_config = _shot_plan_generation_config(strategy, config)
            video_generation_config = _video_task_generation_config(generation_config.get("video"))
            image_model_selection = _node_model_selection("image", generation_config)
            image_capability_requirements = _node_capability_requirements(strategy, generation_config, "image")
            asset_refs = _route_spec_asset_refs(segment, spec)
            prompts = _route_spec_prompts(segment, shots, spec)
            cinematic_story_text = _normalize_multiline_prompt_text(
                segment.get("cinematicStoryText")
                or segment.get("cinematic_story_text")
                or "",
            )
            source_fact_text = _normalize_multiline_prompt_text(
                segment.get("sourceFactText")
                or segment.get("source_fact_text")
                or prompts.get("sourceFactText")
                or prompts.get("source_fact_text")
                or "",
            )
            source_preview = _compact_multiline_prompt_text(
                segment.get("sourcePreview")
                or segment.get("source_preview")
                or prompts.get("sourcePreview")
                or prompts.get("source_preview")
                or "",
                2400,
            )
            script_template_recommendation = copy.deepcopy(
                segment.get("scriptTemplateRecommendation")
                if isinstance(segment.get("scriptTemplateRecommendation"), dict)
                else segment.get("script_template_recommendation")
                if isinstance(segment.get("script_template_recommendation"), dict)
                else {}
            )
            segment_storyboard_template = _explicit_storyboard_template_id(
                segment.get("storyboardTemplate")
                or segment.get("storyboard_template")
                or spec.get("storyboardTemplate")
                or spec.get("storyboard_template")
            )
            anchor_text = (
                str(segment.get("anchorText") or segment.get("anchor_text") or "").strip()
                or str(segment.get("narrativePurpose") or "").strip()
                or "；".join(_shot_text(shot) for shot in shots[:3] if isinstance(shot, dict))
            )
            is_text_to_video = strategy == "text_to_video_draft"
            reference_plan = _route_spec_reference_plan(segment, spec)
            reference_media_ids = _string_list(reference_plan.get("requiredImages") if isinstance(reference_plan, dict) else [])
            quality = copy.deepcopy(spec.get("quality") or segment.get("quality") or {})
            reference_specs = _route_reference_specs(
                segment_id,
                strategy,
                prompts,
                segment_index,
                route_index=route_index,
                shots=shots,
            )
            video_node_type = _video_node_type_for_strategy(strategy)
            video_position_x = 1200 if len(reference_specs) <= 1 else 900 + len(reference_specs) * 250 + 80
            director_node_id = _safe_workflow_id(
                f"director_board_{segment_id}_route_{route_index:02d}",
                f"director_board_{segment_index:03d}_{route_index:02d}",
            )
            script_node_id = _safe_workflow_id(
                f"prompt_storyboard_{segment_id}_route_{route_index:02d}",
                f"prompt_storyboard_{segment_index:03d}_{route_index:02d}",
            )
            video_node_id = _safe_workflow_id(
                f"video_{segment_id}_route_{route_index:02d}",
                f"video_{segment_index:03d}_{route_index:02d}",
            )
            video_result_node_id = _safe_workflow_id(
                f"video_result_{segment_id}_route_{route_index:02d}",
                f"video_result_{segment_index:03d}_{route_index:02d}",
            )
            video_input_links = [
                {
                    "id": _safe_workflow_id(
                        f"link_{segment_id}_{spec_row['id']}_to_{video_node_id}_{spec_row['targetSlot']}",
                        f"link_video_{segment_index:03d}_{route_index:02d}_{ref_index:02d}",
                    ),
                    "sourceType": "generated_media",
                    "sourceNodeId": spec_row["id"],
                    "sourceNodeType": spec_row["type"],
                    "label": str(spec_row.get("label") or "分镜图"),
                    "displayName": str(spec_row.get("label") or "分镜图"),
                    "assetType": "storyboard" if spec_row["targetSlot"] == "storyboard_image" else "reference",
                    "targetNodeId": video_node_id,
                    "targetNodeType": video_node_type,
                    "targetHandle": _WORKFLOW_VIDEO_INPUT_HANDLE,
                    "targetSlot": spec_row["targetSlot"],
                    "slot": spec_row["targetSlot"],
                    "workChainId": work_chain_id,
                    "routeId": route_id,
                    "segmentId": segment_id,
                    "status": "pending_generation",
                    "locked": True,
                    "lockedByUser": False,
                    "preserveOnReplan": True,
                    "lockedReason": "workflow_chain_storyboard_video_input",
                }
                for ref_index, spec_row in enumerate(reference_specs, start=1)
            ]
            video_result_input_link = {
                "id": _safe_workflow_id(
                    f"link_{segment_id}_{video_node_id}_to_{video_result_node_id}",
                    f"link_video_result_{segment_index:03d}_{route_index:02d}",
                ),
                "sourceType": "generated_video",
                "sourceNodeId": video_node_id,
                "sourceNodeType": video_node_type,
                "targetNodeId": video_result_node_id,
                "targetNodeType": "video.result",
                "targetSlot": "video_result",
                "slot": "video_result",
                "workChainId": work_chain_id,
                "routeId": route_id,
                "segmentId": segment_id,
                "status": "pending_generation",
                "locked": True,
                "lockedByUser": False,
                "preserveOnReplan": True,
                "lockedReason": "workflow_chain_video_result_input",
            }
            if is_text_to_video:
                segment_input_links, asset_nodes, asset_edges, missing_asset_refs = [], [], [], []
            else:
                segment_input_links, asset_nodes, asset_edges, missing_asset_refs = _asset_ref_canvas_materials(
                    project_id,
                    asset_refs,
                    target_node_id=director_node_id,
                    route_id=route_id,
                    segment_id=segment_id,
                    work_chain_id=work_chain_id,
                    node_id_suffix=f"_route_{route_index:02d}",
                )
            input_links.extend(segment_input_links)
            route = {
                "id": route_id,
                "label": label,
                "workChainId": work_chain_id,
                "segmentId": segment_id,
                "strategy": strategy,
                "status": "draft",
                "shotIds": copy.deepcopy(shot_ids),
                "shotCount": len(shot_ids),
                "laneIndex": route_index - 1,
                "quality": copy.deepcopy(quality),
            }
            routes.append(route)

            base_y = 120 + (segment_index - 1) * 300 + (route_index - 1) * 300
            reference_nodes = [
                {
                    "id": spec_row["id"],
                    "type": spec_row["type"],
                    "position": {"x": 900 + ref_index * 250, "y": base_y + 90},
                    "workChainId": work_chain_id,
                    "routeId": route_id,
                    "segmentId": segment_id,
                    "strategy": strategy,
                    "data": {
                        "title": str(spec_row["label"] or "分镜图"),
                        "status": "waiting",
                        "summary": "由分镜脚本和资产图生成候选分镜图，并选择 active 版本供视频节点使用。",
                        "workChainId": work_chain_id,
                        "routeId": route_id,
                        "segmentId": segment_id,
                        "strategy": strategy,
                        "frameSlot": spec_row["targetSlot"],
                        "panelIndex": spec_row.get("panelIndex"),
                        "sourceRefs": copy.deepcopy(segment.get("sourceRefs") or []),
                        "referencePlan": copy.deepcopy(reference_plan),
                    },
                }
                for ref_index, spec_row in enumerate(reference_specs)
            ]
            reference_dependency_edges = [
                {
                    "id": f"{director_node_id}_to_{spec_row['id']}",
                    "source": director_node_id,
                    "sourceHandle": "plan",
                    "target": spec_row["id"],
                    "targetHandle": "generates",
                    "data": {
                        "kind": "dependency",
                        "role": "generates",
                        "sourceNodeType": "director.board",
                        "targetNodeType": spec_row["type"],
                        "targetSlot": "generates",
                        "slot": "generates",
                        "workChainId": work_chain_id,
                        "routeId": route_id,
                        "segmentId": segment_id,
                    },
                }
                for spec_row in reference_specs
            ]
            reference_material_edges = [
                {
                    "id": f"{spec_row['id']}_to_{video_node_id}_{spec_row['targetSlot']}",
                    "source": spec_row["id"],
                    "sourceHandle": "image",
                    "target": video_node_id,
                    "targetHandle": _WORKFLOW_VIDEO_INPUT_HANDLE,
                    "locked": True,
                    "lockedByUser": False,
                    "preserveOnReplan": True,
                    "deletable": False,
                    "data": {
                        "kind": "material",
                        "role": spec_row["targetSlot"],
                        "inputLinkId": video_input_links[ref_index]["id"],
                        "sourceType": "generated_media",
                        "sourceNodeType": spec_row["type"],
                        "targetNodeType": video_node_type,
                        "targetHandle": _WORKFLOW_VIDEO_INPUT_HANDLE,
                        "targetSlot": spec_row["targetSlot"],
                        "workChainId": work_chain_id,
                        "routeId": route_id,
                        "segmentId": segment_id,
                        "locked": True,
                        "lockedReason": "workflow_chain_storyboard_video_input",
                        "preserveOnReplan": True,
                    },
                }
                for ref_index, spec_row in enumerate(reference_specs)
            ]
            route_nodes = [
                {
                    "id": director_node_id,
                    "type": "director.board",
                    "position": {"x": 330, "y": base_y},
                    "workChainId": work_chain_id,
                    "routeId": route_id,
                    "segmentId": segment_id,
                    "strategy": strategy,
                    "data": {
                        "title": "分镜脚本",
                        "status": "draft",
                        "summary": "",
                        "workChainId": work_chain_id,
                        "routeId": route_id,
                        "segmentId": segment_id,
                        "strategy": strategy,
                        "sourceRefs": copy.deepcopy(segment.get("sourceRefs") or []),
                        "assetRefs": asset_refs,
                        "inputLinks": segment_input_links,
                        "missingAssetRefs": missing_asset_refs,
                        "prompt": {
                            "directorPlan": "",
                            "directorPlanShots": [],
                            "speakerRoster": [],
                            "directorRuleId": "",
                            "storyboardTemplate": segment_storyboard_template,
                            "storyboardTemplateLabel": storyboard_template_label(segment_storyboard_template),
                        },
                        "directorPlan": "",
                        "directorPlanShots": [],
                        "speakerRoster": [],
                        "directorRuleId": "",
                        "directorRuleSelectionMode": "auto",
                        "directorTaskCard": {
                            "title": stage_title or label or f"原文事实段落 {segment_index}",
                            "directorPlan": "",
                            "directorPlanShots": [],
                            "speakerRoster": [],
                            "directorRuleId": "",
                            "storyboardTemplate": segment_storyboard_template,
                            "storyboardTemplateLabel": storyboard_template_label(segment_storyboard_template),
                            "state": "pending_director_plan",
                        },
                        "modelSelection": {},
                        "capabilityRequirements": {},
                    },
                },
            ]
            if not is_text_to_video:
                route_nodes.extend(
                    [
                        {
                            "id": script_node_id,
                            "type": "prompt.storyboard",
                            "position": {"x": 600, "y": base_y + 90},
                            "workChainId": work_chain_id,
                            "routeId": route_id,
                            "segmentId": segment_id,
                            "strategy": strategy,
                            "data": {
                                "title": "片段剧本",
                                "status": "ready",
                                "summary": _compact_text(str(source_fact_text or ""), 160) or "已生成原文事实，等待生成影视化剧本。",
                                "cardState": {
                                    "state": "ready" if cinematic_story_text else "pending_script",
                                    "scriptState": "ready" if cinematic_story_text else "pending_script",
                                    **_workflow_card_template_fields(segment_storyboard_template),
                                },
                                "workChainId": work_chain_id,
                                "routeId": route_id,
                                "segmentId": segment_id,
                                "strategy": strategy,
                                **_workflow_storyboard_template_fields(segment_storyboard_template),
                                "prompt": {
                                    "cinematicStoryText": cinematic_story_text,
                                    "sourceFactText": source_fact_text,
                                    "sourcePreview": source_preview,
                                },
                                "cinematicStoryText": cinematic_story_text,
                                "sourceFactText": source_fact_text,
                                "sourcePreview": source_preview,
                                **({"scriptTemplateRecommendation": script_template_recommendation} if script_template_recommendation else {}),
                                "storyboardTaskCard": {
                                    "title": stage_title or label or f"原文事实段落 {segment_index}",
                                    "cinematicStoryText": cinematic_story_text,
                                    "sourceFactText": source_fact_text,
                                    "sourcePreview": source_preview,
                                    **({"scriptTemplateRecommendation": script_template_recommendation} if script_template_recommendation else {}),
                                    **_workflow_card_template_fields(segment_storyboard_template),
                                    "state": "ready" if cinematic_story_text else "pending_script",
                                    "scriptState": "ready" if cinematic_story_text else "pending_script",
                                },
                                "screenplay": copy.deepcopy(segment.get("screenplay") or {}),
                                "dialogue": copy.deepcopy(segment.get("dialogue") or []),
                                "sourceRefs": copy.deepcopy(segment.get("sourceRefs") or []),
                                "quality": copy.deepcopy(quality),
                            },
                        },
                        *reference_nodes,
                    ]
                )
            route_nodes.append(
                {
                    "id": video_node_id,
                    "type": video_node_type,
                    "position": {"x": video_position_x, "y": base_y + 90},
                    "workChainId": work_chain_id,
                    "routeId": route_id,
                    "segmentId": segment_id,
                    "strategy": strategy,
                    "data": {
                        "title": "视频生成",
                        "status": "waiting",
                        "summary": "",
                        "workChainId": work_chain_id,
                        "routeId": route_id,
                        "segmentId": segment_id,
                        "strategy": strategy,
                        "prompt": {"videoPrompt": ""},
                        "inputLinks": video_input_links,
                        "referenceThumbnails": copy.deepcopy(video_input_links),
                        "sourceRefs": copy.deepcopy(segment.get("sourceRefs") or []),
                        "generationConfig": copy.deepcopy(video_generation_config),
                        "quality": copy.deepcopy(quality),
                        "modelSelection": _node_model_selection("video", {"video": video_generation_config}),
                        "capabilityRequirements": _node_capability_requirements(
                            strategy,
                            {"video": video_generation_config},
                            "video",
                        ),
                    },
                }
            )
            route_nodes.append(
                {
                    "id": video_result_node_id,
                    "type": "video.result",
                    "position": {"x": video_position_x + 460, "y": base_y + 90},
                    "workChainId": work_chain_id,
                    "routeId": route_id,
                    "segmentId": segment_id,
                    "strategy": strategy,
                    "data": {
                        "title": "视频片段",
                        "status": "waiting",
                        "summary": "",
                        "workChainId": work_chain_id,
                        "routeId": route_id,
                        "segmentId": segment_id,
                        "strategy": strategy,
                        "resultOfNodeId": video_node_id,
                        "sourceNodeId": video_node_id,
                        "inputLinks": [video_result_input_link],
                        "sourceRefs": copy.deepcopy(segment.get("sourceRefs") or []),
                    },
                }
            )
            visible_route_node_types = {
                "prompt.storyboard",
                "director.board",
                "storyboard.image",
                "video.storyboard",
                "video.result",
            }
            route_nodes = [
                node
                for node in route_nodes
                if str(node.get("type") or "").strip() in visible_route_node_types
            ]
            nodes.extend(route_nodes)
            nodes.extend(asset_nodes)
            route_edges = [
                {
                    "id": f"source_to_{script_node_id}",
                    "source": "source_text_1",
                    "sourceHandle": "output",
                    "target": script_node_id,
                    "targetHandle": "story",
                    "data": {
                        "kind": "dependency",
                        "role": "context",
                        "sourceNodeType": "source.text",
                        "targetNodeType": "prompt.storyboard",
                        "workChainId": work_chain_id,
                        "routeId": route_id,
                        "segmentId": segment_id,
                    },
                },
                {
                    "id": f"{script_node_id}_to_{director_node_id}",
                    "source": script_node_id,
                    "sourceHandle": "prompt",
                    "target": director_node_id,
                    "targetHandle": "story",
                    "data": {
                        "kind": "context",
                        "role": "context",
                        "sourceNodeType": "prompt.storyboard",
                        "targetNodeType": "director.board",
                        "workChainId": work_chain_id,
                        "routeId": route_id,
                        "segmentId": segment_id,
                    },
                },
            ]
            if is_text_to_video:
                route_edges.append(
                    {
                        "id": f"{director_node_id}_to_{video_node_id}",
                        "source": director_node_id,
                        "sourceHandle": "plan",
                        "target": video_node_id,
                        "targetHandle": _WORKFLOW_VIDEO_INPUT_HANDLE,
                        "data": {
                            "kind": "dependency",
                            "role": "context",
                            "sourceNodeType": "director.board",
                            "targetNodeType": video_node_type,
                            "workChainId": work_chain_id,
                            "routeId": route_id,
                            "segmentId": segment_id,
                        },
                    }
                )
            else:
                route_edges.extend(
                    [
                        *reference_dependency_edges,
                        *reference_material_edges,
                    ]
                )
            route_edges.append(
                {
                    "id": f"{video_node_id}_to_{video_result_node_id}",
                    "source": video_node_id,
                    "sourceHandle": "video",
                    "target": video_result_node_id,
                    "targetHandle": "generates",
                    "locked": True,
                    "lockedByUser": False,
                    "preserveOnReplan": True,
                    "deletable": False,
                    "data": {
                        "kind": "dependency",
                        "role": "generates",
                        "inputLinkId": video_result_input_link["id"],
                        "sourceType": "generated_video",
                        "sourceNodeType": video_node_type,
                        "targetNodeType": "video.result",
                        "targetSlot": "video_result",
                        "workChainId": work_chain_id,
                        "routeId": route_id,
                        "segmentId": segment_id,
                        "locked": True,
                        "lockedReason": "workflow_chain_video_result_input",
                        "preserveOnReplan": True,
                    },
                }
            )
            visible_edge_node_ids = {
                "source_text_1",
                *[str(node.get("id") or "") for node in route_nodes],
                *[str(node.get("id") or "") for node in asset_nodes],
            }
            route_edges = [
                edge
                for edge in route_edges
                if str(edge.get("source") or "") in visible_edge_node_ids
                and str(edge.get("target") or "") in visible_edge_node_ids
            ]
            if script_node_id in visible_edge_node_ids and not any(
                str(edge.get("source") or "") == "source_text_1"
                and str(edge.get("target") or "") == script_node_id
                for edge in route_edges
            ):
                route_edges.insert(
                    0,
                    {
                        "id": f"source_to_{script_node_id}",
                        "source": "source_text_1",
                        "sourceHandle": "output",
                        "target": script_node_id,
                        "targetHandle": "story",
                        "locked": True,
                        "lockedByUser": False,
                        "preserveOnReplan": True,
                        "deletable": False,
                        "data": {
                            "kind": "dependency",
                            "role": "context",
                            "sourceNodeType": "source.text",
                            "targetNodeType": "prompt.storyboard",
                            "workChainId": work_chain_id,
                            "routeId": route_id,
                            "segmentId": segment_id,
                            "locked": True,
                            "lockedReason": "system_episode_source_context",
                            "preserveOnReplan": True,
                        },
                    },
                )
            edges.extend(route_edges)
            edges.extend(asset_edges)

            for chain in work_chains:
                if not isinstance(chain, dict) or str(chain.get("id") or "") != work_chain_id:
                    continue
                route_ids = [str(item) for item in chain.get("routeIds") or [] if str(item)]
                if route_id not in route_ids:
                    route_ids.append(route_id)
                chain["routeIds"] = route_ids
                chain["layout"] = {
                    **(chain.get("layout") if isinstance(chain.get("layout"), dict) else {}),
                    "height": max(280, len(route_ids) * 200),
                }
                break
