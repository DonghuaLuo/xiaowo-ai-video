# -*- coding: utf-8 -*-
"""剧情拆分结果到工作链计划的投影领域。"""

from __future__ import annotations

from .agent_plot_contract import (
    _compact_source_excerpt,
)
from .source_boundary_contract import _normalize_episode_boundary_title

import copy
from typing import Any


def _apply_plot_split_to_work_chain_plan(
    work_chain_plan: dict[str, Any],
    plot_split_proposal: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(plot_split_proposal, dict):
        return work_chain_plan
    episode_id = str(
        work_chain_plan.get("episodeId")
        or work_chain_plan.get("episode_id")
        or plot_split_proposal.get("episodeId")
        or plot_split_proposal.get("episode_id")
        or ""
    ).strip()
    episode_title = _normalize_episode_boundary_title(
        plot_split_proposal.get("episodeTitle")
        or plot_split_proposal.get("episode_title")
        or plot_split_proposal.get("title"),
        episode_id,
    )
    if episode_title:
        work_chain_plan["episodeTitle"] = episode_title
        work_chain_plan["title"] = episode_title
    items = plot_split_proposal.get("items") if isinstance(plot_split_proposal.get("items"), list) else []
    if not items:
        return work_chain_plan
    segments = work_chain_plan.get("segments") if isinstance(work_chain_plan.get("segments"), list) else []
    if len(segments) != len(items):
        raise ValueError(
            f"work-chain-planning 输出的 segment 数量（{len(segments)}）必须等于已确认原文拆分内容数量（{len(items)}）"
        )
    for index, item in enumerate(items):
        if not isinstance(item, dict) or index >= len(segments) or not isinstance(segments[index], dict):
            continue
        segment = segments[index]
        title = str(item.get("title") or segment.get("title") or f"原文拆分内容 {index + 1}").strip()
        source_refs = item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else []
        segment["title"] = title
        segment["workChainTitle"] = title
        segment["workChainLabel"] = title
        segment["plotSplitItemId"] = str(item.get("id") or f"plot_{index + 1:03d}")
        if source_refs:
            segment["sourceRefs"] = copy.deepcopy(source_refs)
        asset_bindings = copy.deepcopy(
            item.get("assetBindings")
            if isinstance(item.get("assetBindings"), list)
            else item.get("asset_bindings")
            if isinstance(item.get("asset_bindings"), list)
            else segment.get("assetBindings")
            if isinstance(segment.get("assetBindings"), list)
            else []
        )
        missing_visual_needs = copy.deepcopy(
            item.get("missingVisualNeeds")
            if isinstance(item.get("missingVisualNeeds"), list)
            else item.get("missing_visual_needs")
            if isinstance(item.get("missing_visual_needs"), list)
            else segment.get("missingVisualNeeds")
            if isinstance(segment.get("missingVisualNeeds"), list)
            else []
        )
        if asset_bindings:
            segment["assetBindings"] = copy.deepcopy(asset_bindings)
        if missing_visual_needs:
            segment["missingVisualNeeds"] = copy.deepcopy(missing_visual_needs)
        task_card = segment.get("storyboardTaskCard") if isinstance(segment.get("storyboardTaskCard"), dict) else {}
        content = ""
        source_fact_text = (
            str(task_card.get("sourceFactText") or task_card.get("source_fact_text") or "").strip()
            or str(item.get("sourceFactText") or item.get("source_fact_text") or "").strip()
        )
        segment["cinematicStoryText"] = content
        segment["sourceFactText"] = source_fact_text
        segment.pop("scriptTemplateRecommendation", None)
        segment.pop("script_template_recommendation", None)
        segment.pop("adaptationStyle", None)
        segment.pop("adaptation_style", None)
        segment.pop("storyboardTemplate", None)
        segment.pop("storyboard_template", None)
        segment["storyboardTaskCard"] = {
            **task_card,
            "title": title,
            "cinematicStoryText": content,
            "sourceFactText": source_fact_text,
            "sourcePreview": _compact_source_excerpt(
                segment.get("sourcePreview")
                or segment.get("source_preview")
                or task_card.get("sourcePreview")
                or task_card.get("source_preview")
                or item.get("sourcePreview")
                or item.get("source_preview")
                or item.get("excerpt"),
                260,
            ),
            "state": "ready" if content else "pending_script",
            "scriptState": "ready" if content else "pending_script",
            "assetState": str(task_card.get("assetState") or task_card.get("asset_state") or "assets_ready"),
            "assetRefs": copy.deepcopy(segment.get("assetRefs") or {}),
            "assetBindings": copy.deepcopy(asset_bindings),
            "missingVisualNeeds": copy.deepcopy(missing_visual_needs),
        }
        segment["storyboardTaskCard"].pop("scriptTemplateRecommendation", None)
        segment["storyboardTaskCard"].pop("script_template_recommendation", None)
        segment["storyboardTaskCard"].pop("adaptationStyle", None)
        segment["storyboardTaskCard"].pop("adaptation_style", None)
        segment["storyboardTaskCard"].pop("template", None)
        segment["storyboardTaskCard"].pop("templateLabel", None)
    work_chain_plan["segments"] = segments
    work_chain_plan["plotSplitProposal"] = copy.deepcopy(plot_split_proposal)
    return work_chain_plan


def _agent_work_chain_plan_saved_message(
    episode_id: str,
    work_chain_plan: dict[str, Any],
    workflow_result: dict[str, Any],
) -> str:
    segments = work_chain_plan.get("segments") if isinstance(work_chain_plan.get("segments"), list) else []
    route_count = int(workflow_result.get("routeCount") or 0)
    if not route_count:
        workflow = workflow_result.get("workflow") if isinstance(workflow_result.get("workflow"), dict) else {}
        route_count = len(workflow.get("routes") or [])
    segment_count = len(segments)
    parts = [f"智能体已生成 {episode_id} 工作链画布"]
    if segment_count and route_count:
        relation = "，二者一一对应" if segment_count == route_count else ""
        parts.append(f"{segment_count} 个原文拆分内容已生成 {route_count} 条工作链{relation}")
    elif segment_count:
        parts.append(f"包含 {segment_count} 个原文拆分内容")
    elif route_count:
        parts.append(f"已生成 {route_count} 条工作链")
    if segment_count:
        parts.append(f"已创建 {segment_count} 张片段剧本")
    if len(parts) == 1:
        return f"{parts[0]}。"
    return f"{parts[0]}：{'，'.join(parts[1:])}。"
