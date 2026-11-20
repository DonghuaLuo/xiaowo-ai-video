# -*- coding: utf-8 -*-
"""工作链规划转画布的输入装配与整体投影编排。"""
from __future__ import annotations

import copy
import traceback
from .model_provider_config import (
    _project_model_config,
)
from .planning_contract import (
    _ensure_workflow_nodes_contract,
    _explicit_storyboard_template_id,
    _storyboard_only_shot_plan,
    _workflow_card_template_fields,
    _workflow_episode_title,
    _workflow_storyboard_template_fields,
)
from .planning_workflow_assets import (
    _asset_canvas_media,
    _asset_input_links,
    _asset_media_version_state_tags,
    _asset_ref_canvas_index,
    _asset_ref_canvas_materials,
    _asset_ref_entries,
    _asset_ref_preferred_media_version_id,
    _asset_ref_preferred_state_tag,
    _asset_ref_target_slot,
    _asset_row_aliases,
    _asset_row_canonical_identity_strings,
    _asset_row_display_name,
    _asset_row_identity_strings,
    _normalize_generated_workflow_material_edges,
    _video_task_initial_asset_thumbnails,
)
from .planning_workflow_inputs import (
    _compact_multiline_prompt_text,
    _normalize_inline_prompt_text,
    _normalize_multiline_prompt_text,
    _panel_to_prompts,
    _panels_to_shot_plan,
    _safe_video_prompt_text,
    _segment_has_explicit_routes,
    _segment_prompt_field_text,
    _segment_prompts,
    _segment_story_text,
    _shot_asset_refs,
    _shot_camera_text,
    _shot_plan_generation_config,
    _shot_plan_segment_rows,
    _shot_segment_id,
    _shot_text,
    _shots_for_segment,
    _storyboard_analysis_story_text_hash,
    _storyboard_segment_prompt,
    _workflow_apply_timing_to_shots,
    _workflow_segments_for_shot_plan,
)
from .planning_workflow_layout import (
    _layout_workflow_by_work_chain,
)
from .planning_workflow_routes import (
    _apply_route_node_data,
    _expand_extra_segment_routes,
    _remap_route_link,
    _route_node_kind,
    _route_spec_asset_refs,
    _route_spec_id,
    _route_spec_label,
    _route_spec_prompts,
    _route_spec_reference_plan,
    _segment_route_specs,
)
from .planning_workflow_segment import (
    WorkChainSegmentProjector,
)
from .source_text_store import _compact_text, _read_episode_source_text
from typing import (
    Any,
)


def _work_chain_plan_to_workflow(
    episode_id: str,
    shot_plan: dict[str, Any],
    config: dict[str, Any],
    project_id: str | None = None,
    include_episode_source_text: bool = True,
    include_episode_source_node: bool = True,
) -> dict[str, Any]:
    shot_plan = _storyboard_only_shot_plan(shot_plan)
    generation_config_source = copy.deepcopy(config if isinstance(config, dict) else {})
    if project_id:
        try:
            _, _, model_config = _project_model_config(project_id)
        except Exception:
            print(traceback.format_exc(), flush=True)
        else:
            generation_config_source["model_config"] = copy.deepcopy(model_config)
    source_text = str(shot_plan.get("sourceText") or "")
    if project_id and include_episode_source_text:
        try:
            stored_source_text = _read_episode_source_text(project_id, episode_id)
            if stored_source_text:
                source_text = stored_source_text
        except Exception:
            print(traceback.format_exc(), flush=True)
    episode_title = _workflow_episode_title(project_id, episode_id, shot_plan)
    source_card_title = episode_title or str(episode_id or "当前分集").strip() or "当前分集"
    routes: list[dict[str, Any]] = []
    work_chains: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    if include_episode_source_node:
        nodes.append(
            {
                "id": "source_text_1",
                "type": "source.text",
                "position": {"x": -1500, "y": 140},
                "data": {
                    "title": source_card_title,
                    "episodeTitle": source_card_title,
                    "status": "ready",
                    "summary": _compact_text(source_text, 180),
                    "sourceText": source_text,
                    "episodeScript": shot_plan.get("episodeScript") or "",
                    "sourceRefs": copy.deepcopy(shot_plan.get("sourceRefs") or []),
                    "cardState": {"size": {"width": 340, "height": 160, "minWidth": 320, "minHeight": 140}},
                },
            }
        )
    edges: list[dict[str, Any]] = []
    input_links: list[dict[str, Any]] = []
    route_expansions: list[dict[str, Any]] = []
    segments, workflow_shot_plan = _workflow_segments_for_shot_plan(shot_plan)
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        WorkChainSegmentProjector(
            edges=edges,
            generation_config_source=generation_config_source,
            include_episode_source_node=include_episode_source_node,
            index=index,
            input_links=input_links,
            nodes=nodes,
            project_id=project_id,
            route_expansions=route_expansions,
            routes=routes,
            segment=segment,
            work_chains=work_chains,
            workflow_shot_plan=workflow_shot_plan,
        ).apply()
    _expand_extra_segment_routes(
        project_id=project_id,
        routes=routes,
        work_chains=work_chains,
        nodes=nodes,
        edges=edges,
        input_links=input_links,
        route_expansions=route_expansions,
        config=generation_config_source,
    )
    from .planning_workflow_storyboard_cards import add_storyboard_cards
    add_storyboard_cards(nodes, edges)
    _normalize_generated_workflow_material_edges(nodes, edges)
    _layout_workflow_by_work_chain(nodes, routes, work_chains, edges)
    _ensure_workflow_nodes_contract(nodes)
    workflow = {
        "episodeId": episode_id,
        "schemaVersion": 2,
        "version": 1,
        "viewport": {"x": 0, "y": 0, "zoom": 0.82},
        "workChains": work_chains,
        "routes": routes,
        "nodes": nodes,
        "edges": edges,
        "productionStatus": {
            "state": "workflow.ready" if routes else "episode.source_ready",
            "blocking": [] if routes else ["尚未生成可执行画布工作链"],
            "nextAction": "run_workflow" if routes else "build_workflow_chain",
        },
    }
    context_provenance = (
        shot_plan.get("contextProvenance") if isinstance(shot_plan.get("contextProvenance"), dict) else {}
    )
    if context_provenance:
        workflow["contextProvenance"] = copy.deepcopy(context_provenance)
    return workflow
