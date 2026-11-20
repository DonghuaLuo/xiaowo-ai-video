# -*- coding: utf-8 -*-
"""单段工作链的路线、任务卡、素材和连线投影。"""
from __future__ import annotations

import copy
from .planning_contract import (
    _WORKFLOW_VIDEO_INPUT_HANDLE,
    _append_unique_string,
    _apply_video_input_plan_to_generation_config,
    _explicit_storyboard_template_id,
    _node_capability_requirements,
    _node_model_selection,
    _normalize_video_generation_strategy,
    _route_reference_specs,
    _safe_workflow_id,
    _segment_video_input_plan,
    _video_node_type_for_strategy,
    _video_strategy_for_input_mode,
    _video_task_generation_config,
    _workflow_card_template_fields,
    _workflow_chain_continuity,
    _workflow_shot_timing_plan_duration,
    _workflow_shot_timing_plan_for_segment,
    _workflow_storyboard_template_fields,
)
from .planning_workflow_assets import (
    _asset_ref_canvas_materials,
)
from .planning_workflow_inputs import (
    _normalize_multiline_prompt_text,
    _shot_plan_generation_config,
    _shot_text,
    _shots_for_segment,
    _workflow_apply_timing_to_shots,
)
from .planning_workflow_routes import (
    _route_spec_asset_refs,
    _route_spec_id,
    _route_spec_label,
    _route_spec_prompts,
    _route_spec_reference_plan,
    _segment_route_specs,
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


class WorkChainSegmentProjector:
    """将一个规划段落投影为路线、任务卡、素材和连线。派生状态仅属于本次投影。"""

    def __init__(
        self,
        *,
        edges: list[dict[str, Any]],
        generation_config_source: dict[str, Any],
        include_episode_source_node: bool,
        index: int,
        input_links: list[dict[str, Any]],
        nodes: list[dict[str, Any]],
        project_id: str | None,
        route_expansions: list[dict[str, Any]],
        routes: list[dict[str, Any]],
        segment: dict[str, Any],
        work_chains: list[dict[str, Any]],
        workflow_shot_plan: dict[str, Any],
    ) -> None:
        self.edges = edges
        self.generation_config_source = generation_config_source
        self.include_episode_source_node = include_episode_source_node
        self.index = index
        self.input_links = input_links
        self.nodes = nodes
        self.project_id = project_id
        self.route_expansions = route_expansions
        self.routes = routes
        self.segment = segment
        self.work_chains = work_chains
        self.workflow_shot_plan = workflow_shot_plan

    def apply(self) -> None:
        self._prepare_route()
        self._resolve_material_inputs()
        self._register_route()
        self._project_reference_nodes()
        self._project_task_nodes()
        self._project_edges()

    def _prepare_route(self) -> None:
        self.segment_id = str(self.segment.get("id") or self.segment.get("segmentId") or self.segment.get("segment_id") or f"seg_{self.index:03d}")
        self.default_strategy = str(self.segment.get("generationStrategy") or "storyboard_multi_shot")
        self.task_card = self.segment.get("storyboardTaskCard") if isinstance(self.segment.get("storyboardTaskCard"), dict) else {}
        self.segment_storyboard_template = _explicit_storyboard_template_id(
            self.segment.get("storyboardTemplate")
            or self.segment.get("storyboard_template")
            or self.task_card.get("template")
            or self.task_card.get("templateId")
            or self.task_card.get("template_id")
        )
        self.route_specs = _segment_route_specs(self.segment, self.default_strategy)
        self.primary_route_spec = self.route_specs[0]
        self.strategy = _normalize_video_generation_strategy(
            self.primary_route_spec.get("strategy") or self.default_strategy or "storyboard_multi_shot"
        )
        self.work_chain_id = _safe_workflow_id(
            str(
                self.segment.get("workChainId")
                or self.segment.get("work_chain_id")
                or self.segment.get("chainId")
                or self.segment.get("chain_id")
                or f"chain_{self.index:03d}"
            ),
            f"chain_{self.index:03d}",
        )
        self.route_id = _route_spec_id(self.segment_id, self.strategy, self.primary_route_spec, self.index, 1)
        self.raw_route_label = _route_spec_label(self.segment, self.primary_route_spec, self.index, 1)
        self.stage_title = str(
            self.segment.get("workChainTitle")
            or self.segment.get("workChainLabel")
            or self.segment.get("title")
            or self.raw_route_label
        ).strip()
        self.route_label = self.stage_title or f"原文事实段落 {self.index}"
        self.director_node_id = _safe_workflow_id(f"director_board_{self.segment_id}", f"director_board_{self.index:03d}")
        self.script_node_id = _safe_workflow_id(f"prompt_storyboard_{self.segment_id}", f"prompt_storyboard_{self.index:03d}")
        self.video_node_id = _safe_workflow_id(f"video_{self.segment_id}", f"video_{self.index:03d}")
        self.video_result_node_id = _safe_workflow_id(f"video_result_{self.segment_id}", f"video_result_{self.index:03d}")
        self.shots = _shots_for_segment(self.workflow_shot_plan, self.segment_id)
        self.shot_timing_plan = _workflow_shot_timing_plan_for_segment(self.segment, self.shots)
        self.segment_duration_seconds = _workflow_shot_timing_plan_duration(self.shot_timing_plan)
        if self.shot_timing_plan:
            self.shots = _workflow_apply_timing_to_shots(self.shots, self.shot_timing_plan)
        self.video_input_plan = _segment_video_input_plan(self.segment, [], self.strategy)
        self.effective_video_strategy = str(self.video_input_plan.get("videoStrategy") or _video_strategy_for_input_mode(self.strategy, str(self.video_input_plan.get("mode") or "")))
        self.generation_config = _apply_video_input_plan_to_generation_config(
            _shot_plan_generation_config(self.strategy, self.generation_config_source),
            self.video_input_plan,
        )
        self.video_generation_config = _video_task_generation_config(self.generation_config.get("video"))
        self.image_model_selection = _node_model_selection("image", self.generation_config)
        self.image_capability_requirements = _node_capability_requirements(self.strategy, self.generation_config, "image")
        self.prompts = _route_spec_prompts(self.segment, [], self.primary_route_spec)
        self.cinematic_story_text = _normalize_multiline_prompt_text(
            self.segment.get("cinematicStoryText")
            or self.segment.get("cinematic_story_text")
            or self.task_card.get("cinematicStoryText")
            or self.task_card.get("cinematic_story_text")
            or "",
        )
        self.source_fact_text = _normalize_multiline_prompt_text(
            self.segment.get("sourceFactText")
            or self.segment.get("source_fact_text")
            or self.task_card.get("sourceFactText")
            or self.task_card.get("source_fact_text")
            or self.prompts.get("sourceFactText")
            or self.prompts.get("source_fact_text")
            or "",
        )
        self.script_template_recommendation = copy.deepcopy(
            self.segment.get("scriptTemplateRecommendation")
            if isinstance(self.segment.get("scriptTemplateRecommendation"), dict)
            else self.segment.get("script_template_recommendation")
            if isinstance(self.segment.get("script_template_recommendation"), dict)
            else self.task_card.get("scriptTemplateRecommendation")
            if isinstance(self.task_card.get("scriptTemplateRecommendation"), dict)
            else self.task_card.get("script_template_recommendation")
            if isinstance(self.task_card.get("script_template_recommendation"), dict)
            else {}
        )
        self.adaptation_style = copy.deepcopy(
            self.segment.get("adaptationStyle")
            if isinstance(self.segment.get("adaptationStyle"), dict)
            else self.segment.get("adaptation_style")
            if isinstance(self.segment.get("adaptation_style"), dict)
            else self.task_card.get("adaptationStyle")
            if isinstance(self.task_card.get("adaptationStyle"), dict)
            else self.task_card.get("adaptation_style")
            if isinstance(self.task_card.get("adaptation_style"), dict)
            else {}
        )
        self.anchor_text = (
            str(self.segment.get("anchorText") or self.segment.get("anchor_text") or "").strip()
            or str(self.segment.get("narrativePurpose") or "").strip()
            or "；".join(_shot_text(shot) for shot in self.shots[:3] if isinstance(shot, dict))
        )
        self.is_text_to_video = self.strategy == "text_to_video_draft"
        self.reference_specs = _route_reference_specs(
            self.segment_id,
            self.strategy,
            self.prompts,
            self.index,
            shots=[],
            video_input_mode=str(self.video_input_plan.get("mode") or ""),
        )
        self.video_node_type = _video_node_type_for_strategy(self.effective_video_strategy)
        self.video_position_x = 1200 if len(self.reference_specs) <= 1 else 900 + len(self.reference_specs) * 250 + 80

    def _resolve_material_inputs(self) -> None:
        self.video_input_links = [
            {
                "id": _safe_workflow_id(
                    f"link_{self.segment_id}_{spec['id']}_to_{self.video_node_id}_{spec['targetSlot']}",
                    f"link_video_{self.index:03d}_{ref_index:02d}",
                ),
                "sourceType": "generated_media",
                "sourceNodeId": spec["id"],
                "sourceNodeType": spec["type"],
                "label": str(spec.get("label") or "分镜图"),
                "displayName": str(spec.get("label") or "分镜图"),
                "assetType": "storyboard" if spec["targetSlot"] == "storyboard_image" else "reference",
                "targetNodeId": self.video_node_id,
                "targetNodeType": self.video_node_type,
                "targetSlot": spec["targetSlot"],
                "slot": spec["targetSlot"],
                "workChainId": self.work_chain_id,
                "routeId": self.route_id,
                "segmentId": self.segment_id,
                "status": "pending_generation",
                "locked": True,
                "lockedByUser": False,
                "preserveOnReplan": True,
                "lockedReason": "workflow_chain_storyboard_video_input",
            }
            for ref_index, spec in enumerate(self.reference_specs, start=1)
        ]
        self.video_result_input_link = {
            "id": _safe_workflow_id(
                f"link_{self.segment_id}_{self.video_node_id}_to_{self.video_result_node_id}",
                f"link_video_result_{self.index:03d}",
            ),
            "sourceType": "generated_video",
            "sourceNodeId": self.video_node_id,
            "sourceNodeType": self.video_node_type,
            "targetNodeId": self.video_result_node_id,
            "targetNodeType": "video.result",
            "targetSlot": "video_result",
            "slot": "video_result",
            "workChainId": self.work_chain_id,
            "routeId": self.route_id,
            "segmentId": self.segment_id,
            "status": "pending_generation",
            "locked": True,
            "lockedByUser": False,
            "preserveOnReplan": True,
            "lockedReason": "workflow_chain_video_result_input",
        }
        self.shot_ids = [
            str(shot.get("id") or f"shot_{shot_index:03d}")
            for shot_index, shot in enumerate(self.shots, start=1)
            if isinstance(shot, dict)
        ]
        self.asset_refs = _route_spec_asset_refs(self.segment, self.primary_route_spec)
        self.director_task_card = {
            "title": self.stage_title or self.route_label or f"原文事实段落 {self.index}",
            "directorPlan": "",
            "directorPlanShots": [],
            "speakerRoster": [],
            "directorRuleId": "",
            **_workflow_card_template_fields(self.segment_storyboard_template),
            "state": "pending_director_plan",
        }
        if self.is_text_to_video:
            self.segment_input_links, self.asset_nodes, self.asset_edges, self.missing_asset_refs = [], [], [], []
        else:
            self.segment_input_links, self.asset_nodes, self.asset_edges, self.missing_asset_refs = _asset_ref_canvas_materials(
                self.project_id,
                self.asset_refs,
                target_node_id=self.director_node_id,
                route_id=self.route_id,
                segment_id=self.segment_id,
                work_chain_id=self.work_chain_id,
            )
        self.input_links.extend(self.segment_input_links)
        self.reference_plan = _route_spec_reference_plan(self.segment, self.primary_route_spec)
        self.reference_media_ids = _string_list(self.reference_plan.get("requiredImages") if isinstance(self.reference_plan, dict) else [])

    def _register_route(self) -> None:
        self.existing_chain = next((chain for chain in self.work_chains if isinstance(chain, dict) and str(chain.get("id") or "") == self.work_chain_id), None)
        if self.existing_chain:
            self.existing_chain["segmentIds"] = _append_unique_string(self.existing_chain.get("segmentIds"), self.segment_id)
            for shot_id in self.shot_ids:
                self.existing_chain["shotIds"] = _append_unique_string(self.existing_chain.get("shotIds"), shot_id)
            self.existing_chain["routeIds"] = _append_unique_string(self.existing_chain.get("routeIds"), self.route_id)
            if "videoInputPlan" not in self.existing_chain:
                self.existing_chain["videoInputPlan"] = copy.deepcopy(self.video_input_plan)
        else:
            self.continuity_value = (
                (self.segment.get("continuity") or {}).get("type")
                if isinstance(self.segment.get("continuity"), dict)
                else self.segment.get("continuity")
            )
            self.anchor_order = len(self.work_chains) + 1
            self.work_chains.append(
                {
                    "id": self.work_chain_id,
                    "label": self.stage_title or f"原文事实段落 {self.anchor_order}",
                    "origin": {"kind": "source_split", "sourceNodeId": "source_text_1"} if self.include_episode_source_node else {"kind": "independent", "sourceNodeId": None},
                    "title": self.stage_title or f"原文事实段落 {self.anchor_order}",
                    "continuity": _workflow_chain_continuity(self.continuity_value, self.shot_ids),
                    **_workflow_storyboard_template_fields(self.segment_storyboard_template),
                    "videoInputPlan": copy.deepcopy(self.video_input_plan),
                    "segmentIds": [self.segment_id],
                    "shotIds": self.shot_ids,
                    "routeIds": [self.route_id],
                    "order": self.anchor_order,
                    "layout": {"y": 120 + len(self.work_chains) * 200, "height": 280},
                    "status": "draft",
                }
            )
        self.route = {
            "id": self.route_id,
            "label": self.route_label,
            "workChainId": self.work_chain_id,
            "segmentId": self.segment_id,
            "strategy": self.strategy,
            **_workflow_storyboard_template_fields(self.segment_storyboard_template),
            "videoInputPlan": copy.deepcopy(self.video_input_plan),
            "videoInputStrategy": self.effective_video_strategy,
            "status": "draft",
            "shotIds": self.shot_ids,
            "shotCount": len(self.shot_ids),
            "laneIndex": self.index - 1,
            "quality": copy.deepcopy(self.segment.get("quality") or {}),
        }
        self.routes.append(self.route)
        self.route_expansions.append(
            {
                "segment": copy.deepcopy(self.segment),
                "segmentId": self.segment_id,
                "workChainId": self.work_chain_id,
                "primaryRouteId": self.route_id,
                "routeSpecs": self.route_specs,
                "segmentIndex": self.index,
                "shots": copy.deepcopy(self.shots),
                "shotIds": copy.deepcopy(self.shot_ids),
                "videoInputPlan": copy.deepcopy(self.video_input_plan),
                "videoInputStrategy": self.effective_video_strategy,
            }
        )
        self.base_y = 120 + (self.index - 1) * 300

    def _project_reference_nodes(self) -> None:
        self.reference_nodes = [
            {
                "id": spec["id"],
                "type": spec["type"],
                "position": {"x": 900 + ref_index * 250, "y": self.base_y + 90},
                "workChainId": self.work_chain_id,
                "routeId": self.route_id,
                "segmentId": self.segment_id,
                "strategy": self.strategy,
                "data": {
                    "title": str(spec["label"] or "分镜图"),
                    "status": "waiting",
                    "summary": "由分镜脚本和资产图生成候选分镜图，并选择 active 版本供视频节点使用。",
                    "workChainId": self.work_chain_id,
                    "routeId": self.route_id,
                    "segmentId": self.segment_id,
                    "strategy": self.strategy,
                    "videoInputPlan": copy.deepcopy(self.video_input_plan),
                    "videoInputStrategy": self.effective_video_strategy,
                    **_workflow_storyboard_template_fields(self.segment_storyboard_template),
                    "frameSlot": spec["targetSlot"],
                    "panelIndex": spec.get("panelIndex"),
                    "sourceRefs": copy.deepcopy(self.segment.get("sourceRefs") or []),
                    "referencePlan": copy.deepcopy(self.segment.get("referencePlan") or {}),
                },
            }
            for ref_index, spec in enumerate(self.reference_specs)
        ]
        self.reference_dependency_edges = [
            {
                "id": f"{self.director_node_id}_to_{spec['id']}",
                "source": self.director_node_id,
                "sourceHandle": "plan",
                "target": spec["id"],
                "targetHandle": "generates",
                "data": {
                    "kind": "dependency",
                    "role": "generates",
                    "sourceNodeType": "director.board",
                    "targetNodeType": spec["type"],
                    "targetSlot": "generates",
                    "slot": "generates",
                    "workChainId": self.work_chain_id,
                    "routeId": self.route_id,
                    "segmentId": self.segment_id,
                },
            }
            for spec in self.reference_specs
        ]
        self.reference_material_edges = [
            {
                "id": f"{spec['id']}_to_{self.video_node_id}_{spec['targetSlot']}",
                "source": spec["id"],
                "sourceHandle": "image",
                "target": self.video_node_id,
                "targetHandle": spec["targetSlot"],
                "locked": True,
                "lockedByUser": False,
                "preserveOnReplan": True,
                "deletable": False,
                "data": {
                    "kind": "material",
                    "role": spec["targetSlot"],
                    "inputLinkId": self.video_input_links[ref_index]["id"],
                    "sourceType": "generated_media",
                    "sourceNodeType": spec["type"],
                    "targetNodeType": self.video_node_type,
                    "targetSlot": spec["targetSlot"],
                    "workChainId": self.work_chain_id,
                    "routeId": self.route_id,
                    "segmentId": self.segment_id,
                    "locked": True,
                    "lockedReason": "workflow_chain_storyboard_video_input",
                    "preserveOnReplan": True,
                },
            }
            for ref_index, spec in enumerate(self.reference_specs)
        ]

    def _project_task_nodes(self) -> None:
        self.route_nodes = [
            {
                "id": self.director_node_id,
                "type": "director.board",
                "position": {"x": 330, "y": self.base_y},
                "workChainId": self.work_chain_id,
                "routeId": self.route_id,
                "segmentId": self.segment_id,
                "strategy": self.strategy,
                "data": {
                    "title": f"分镜脚本 · 片段{self.index:02d}",
                    "status": "draft",
                    "summary": "",
                    "workChainId": self.work_chain_id,
                    "routeId": self.route_id,
                    "segmentId": self.segment_id,
                    "strategy": self.strategy,
                    "videoInputPlan": copy.deepcopy(self.video_input_plan),
                    "videoInputStrategy": self.effective_video_strategy,
                    **_workflow_storyboard_template_fields(self.segment_storyboard_template),
                    "prompt": {
                        "directorPlan": "",
                        "directorPlanShots": [],
                        "speakerRoster": [],
                        "directorRuleId": "",
                        "storyboardTemplate": self.segment_storyboard_template,
                        "storyboardTemplateLabel": storyboard_template_label(self.segment_storyboard_template),
                    },
                    "directorPlan": "",
                    "directorPlanShots": [],
                    "speakerRoster": [],
                    "directorRuleId": "",
                    "directorRuleSelectionMode": "auto",
                    "directorTaskCard": copy.deepcopy(self.director_task_card),
                    "sourceRefs": copy.deepcopy(self.segment.get("sourceRefs") or []),
                    "assetRefs": self.asset_refs,
                    "inputLinks": self.segment_input_links,
                    "missingAssetRefs": self.missing_asset_refs,
                    "referenceMediaIds": self.reference_media_ids,
                    "generationConfig": copy.deepcopy(self.generation_config.get("image") or {}),
                    "modelSelection": copy.deepcopy(self.image_model_selection),
                    "capabilityRequirements": copy.deepcopy(self.image_capability_requirements),
                },
            },
        ]
        if not self.is_text_to_video:
            self.route_nodes.extend(
                [
                    {
                        "id": self.script_node_id,
                        "type": "prompt.storyboard",
                        "position": {"x": 600, "y": self.base_y + 90},
                        "workChainId": self.work_chain_id,
                        "routeId": self.route_id,
                        "segmentId": self.segment_id,
                        "strategy": self.strategy,
                        "data": {
                            "title": f"片段剧本 · 片段{self.index:02d}",
                            "status": "ready",
                            "summary": _compact_text(str(self.source_fact_text or ""), 160) or "已生成原文事实，等待生成影视化剧本。",
                            "cardState": {
                                "state": "ready" if self.cinematic_story_text else "pending_script",
                                "scriptState": "ready" if self.cinematic_story_text else "pending_script",
                                **_workflow_card_template_fields(self.segment_storyboard_template),
                            },
                            "workChainId": self.work_chain_id,
                            "routeId": self.route_id,
                            "segmentId": self.segment_id,
                            "strategy": self.strategy,
                            "videoInputPlan": copy.deepcopy(self.video_input_plan),
                            "videoInputStrategy": self.effective_video_strategy,
                            **_workflow_storyboard_template_fields(self.segment_storyboard_template),
                            "prompt": {
                                "cinematicStoryText": self.cinematic_story_text,
                                "sourceFactText": self.source_fact_text,
                            },
                            "cinematicStoryText": self.cinematic_story_text,
                            "sourceFactText": self.source_fact_text,
                            "narrativeMode": "drama",
                            **({"scriptTemplateRecommendation": self.script_template_recommendation} if self.script_template_recommendation else {}),
                            **({"adaptationStyle": self.adaptation_style} if self.adaptation_style else {}),
                            "storyboardTaskCard": {
                                "title": self.stage_title or self.route_label or f"原文事实段落 {self.index}",
                                "cinematicStoryText": self.cinematic_story_text,
                                "sourceFactText": self.source_fact_text,
                                **({"scriptTemplateRecommendation": self.script_template_recommendation} if self.script_template_recommendation else {}),
                                **({"adaptationStyle": self.adaptation_style} if self.adaptation_style else {}),
                                **_workflow_card_template_fields(self.segment_storyboard_template),
                                "state": "ready" if self.cinematic_story_text else "pending_script",
                                "scriptState": "ready" if self.cinematic_story_text else "pending_script",
                            },
                            "screenplay": copy.deepcopy(self.segment.get("screenplay") or {}),
                            "dialogue": copy.deepcopy(self.segment.get("dialogue") or []),
                            "sourceRefs": copy.deepcopy(self.segment.get("sourceRefs") or []),
                            "quality": copy.deepcopy(self.segment.get("quality") or {}),
                        },
                    },
                    *self.reference_nodes,
                ]
            )
        self.route_nodes.append(
            {
                "id": self.video_node_id,
                "type": self.video_node_type,
                "position": {"x": self.video_position_x, "y": self.base_y + 90},
                "workChainId": self.work_chain_id,
                "routeId": self.route_id,
                "segmentId": self.segment_id,
                "strategy": self.effective_video_strategy,
                "data": {
                    "title": "视频生成",
                    "status": "waiting",
                    "summary": "",
                    "workChainId": self.work_chain_id,
                    "routeId": self.route_id,
                    "segmentId": self.segment_id,
                    "strategy": self.effective_video_strategy,
                    "planningStrategy": self.strategy,
                    "videoInputPlan": copy.deepcopy(self.video_input_plan),
                    "videoInputStrategy": self.effective_video_strategy,
                    "prompt": {},
                    "inputLinks": self.video_input_links,
                    "referenceThumbnails": copy.deepcopy(self.video_input_links),
                    "sourceRefs": copy.deepcopy(self.segment.get("sourceRefs") or []),
                    "generationConfig": copy.deepcopy(self.video_generation_config),
                    "quality": copy.deepcopy(self.segment.get("quality") or {}),
                    "modelSelection": _node_model_selection("video", {"video": self.video_generation_config}),
                    "capabilityRequirements": _node_capability_requirements(
                        self.effective_video_strategy,
                        {"video": self.video_generation_config},
                        "video",
                    ),
                },
            }
        )
        self.route_nodes.append(
            {
                "id": self.video_result_node_id,
                "type": "video.result",
                "position": {"x": self.video_position_x + 460, "y": self.base_y + 90},
                "workChainId": self.work_chain_id,
                "routeId": self.route_id,
                "segmentId": self.segment_id,
                "strategy": self.effective_video_strategy,
                "data": {
                    "title": "视频片段",
                    "status": "waiting",
                    "summary": "",
                    "workChainId": self.work_chain_id,
                    "routeId": self.route_id,
                    "segmentId": self.segment_id,
                    "strategy": self.effective_video_strategy,
                    "planningStrategy": self.strategy,
                    "videoInputPlan": copy.deepcopy(self.video_input_plan),
                    "videoInputStrategy": self.effective_video_strategy,
                    "resultOfNodeId": self.video_node_id,
                    "sourceNodeId": self.video_node_id,
                    "inputLinks": [self.video_result_input_link],
                    "sourceRefs": copy.deepcopy(self.segment.get("sourceRefs") or []),
                },
            }
        )
        self.visible_route_node_types = {
            "prompt.storyboard",
            "director.board",
            "storyboard.image",
            "video.storyboard",
            "video.result",
        }
        self.route_nodes = [
            node
            for node in self.route_nodes
            if str(node.get("type") or "").strip() in self.visible_route_node_types
        ]
        self.nodes.extend(self.route_nodes)
        self.nodes.extend(self.asset_nodes)

    def _project_edges(self) -> None:
        self.route_edges = [
            {
                "id": f"{self.script_node_id}_to_{self.director_node_id}",
                "source": self.script_node_id,
                "sourceHandle": "prompt",
                "target": self.director_node_id,
                "targetHandle": "story",
                "data": {"kind": "context", "role": "context", "sourceNodeType": "prompt.storyboard", "targetNodeType": "director.board", "workChainId": self.work_chain_id, "routeId": self.route_id, "segmentId": self.segment_id},
            },
        ]
        if self.include_episode_source_node:
            self.route_edges.insert(
                0,
                {
                    "id": f"source_to_{self.script_node_id}",
                    "source": "source_text_1",
                    "sourceHandle": "output",
                    "target": self.script_node_id,
                    "targetHandle": "story",
                    "data": {"kind": "dependency", "role": "context", "sourceNodeType": "source.text", "targetNodeType": "prompt.storyboard", "workChainId": self.work_chain_id, "routeId": self.route_id, "segmentId": self.segment_id},
                },
            )
        if self.is_text_to_video:
            if self.include_episode_source_node:
                self.route_edges.append(
                    {
                        "id": f"source_to_{self.director_node_id}",
                        "source": "source_text_1",
                        "sourceHandle": "output",
                        "target": self.director_node_id,
                        "targetHandle": "story",
                        "data": {"kind": "dependency", "role": "context", "sourceNodeType": "source.text", "targetNodeType": "director.board", "workChainId": self.work_chain_id, "routeId": self.route_id, "segmentId": self.segment_id},
                    }
                )
            self.route_edges.append(
                {
                    "id": f"{self.director_node_id}_to_{self.video_node_id}",
                    "source": self.director_node_id,
                    "sourceHandle": "plan",
                    "target": self.video_node_id,
                    "targetHandle": _WORKFLOW_VIDEO_INPUT_HANDLE,
                    "data": {"kind": "dependency", "role": "context", "sourceNodeType": "director.board", "targetNodeType": self.video_node_type, "workChainId": self.work_chain_id, "routeId": self.route_id, "segmentId": self.segment_id},
                }
            )
        else:
            self.route_edges.extend(
                [
                    *self.reference_dependency_edges,
                    *self.reference_material_edges,
                ]
            )
        self.route_edges.append(
            {
                "id": f"{self.video_node_id}_to_{self.video_result_node_id}",
                "source": self.video_node_id,
                "sourceHandle": "video",
                "target": self.video_result_node_id,
                "targetHandle": "generates",
                "locked": True,
                "lockedByUser": False,
                "preserveOnReplan": True,
                "deletable": False,
                "data": {
                    "kind": "dependency",
                    "role": "generates",
                    "inputLinkId": self.video_result_input_link["id"],
                    "sourceType": "generated_video",
                    "sourceNodeType": self.video_node_type,
                    "targetNodeType": "video.result",
                    "targetSlot": "video_result",
                    "workChainId": self.work_chain_id,
                    "routeId": self.route_id,
                    "segmentId": self.segment_id,
                    "locked": True,
                    "lockedReason": "workflow_chain_video_result_input",
                    "preserveOnReplan": True,
                },
            }
        )
        self.visible_edge_node_ids = {
            *({"source_text_1"} if self.include_episode_source_node else set()),
            *[str(node.get("id") or "") for node in self.route_nodes],
            *[str(node.get("id") or "") for node in self.asset_nodes],
        }
        self.route_edges = [
            edge
            for edge in self.route_edges
            if str(edge.get("source") or "") in self.visible_edge_node_ids
            and str(edge.get("target") or "") in self.visible_edge_node_ids
        ]
        if self.include_episode_source_node and self.script_node_id in self.visible_edge_node_ids and not any(
            str(edge.get("source") or "") == "source_text_1"
            and str(edge.get("target") or "") == self.script_node_id
            for edge in self.route_edges
        ):
            self.route_edges.insert(
                0,
                {
                    "id": f"source_to_{self.script_node_id}",
                    "source": "source_text_1",
                    "sourceHandle": "output",
                    "target": self.script_node_id,
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
                        "workChainId": self.work_chain_id,
                        "routeId": self.route_id,
                        "segmentId": self.segment_id,
                        "locked": True,
                        "lockedReason": "system_episode_source_context",
                        "preserveOnReplan": True,
                    },
                },
            )
        self.edges.extend(self.route_edges)
        self.edges.extend(self.asset_edges)
