# -*- coding: utf-8 -*-
"""工作链规划段落、镜头与生成输入规范化。"""
from __future__ import annotations

import copy
import hashlib
import re
from .planning_contract import (
    _normalize_video_generation_strategy,
    _panel_generation_strategy,
    _panel_reference_media_ids,
    _panel_row_text,
    _safe_workflow_id,
    _segment_asset_refs,
    _storyboard_only_planning_item,
    _strategy_reference_mode,
    _workflow_clean_seconds,
    _workflow_prompt_text_value,
    _workflow_timing_number,
)
from .projects import (
    _first_text,
)
from typing import (
    Any,
)


def _workflow_apply_timing_to_shots(
    shots: list[dict[str, Any]],
    timing_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = timing_plan.get("shots") if isinstance(timing_plan.get("shots"), list) else []
    if not rows:
        return copy.deepcopy(shots)
    result: list[dict[str, Any]] = []
    for index, shot in enumerate(shots, start=1):
        cloned = copy.deepcopy(shot) if isinstance(shot, dict) else {}
        row = rows[index - 1] if index - 1 < len(rows) and isinstance(rows[index - 1], dict) else {}
        if row:
            cloned["shotLabel"] = str(row.get("shotLabel") or cloned.get("shotLabel") or f"Shot {index:02d}").strip()
            for key in ("durationSeconds", "startSecond", "endSecond"):
                if row.get(key) is not None:
                    cloned[key] = copy.deepcopy(row.get(key))
        result.append(cloned)
    return result


def _panel_to_prompts(panel: dict[str, Any]) -> dict[str, Any]:
    prompts = panel.get("prompts") if isinstance(panel.get("prompts"), dict) else {}
    return {
        "storyboardImagePrompt": (
            prompts.get("storyboardImagePrompt")
            or prompts.get("storyboardPanelPrompt")
            or _panel_row_text(panel, "storyboardImagePrompt", "visualPrompt", "visual_prompt", "visual", "description")
        ),
        "storyboardSheetPrompt": prompts.get("storyboardSheetPrompt") or "",
    }


def _panels_to_shot_plan(
    episode_id: str,
    *,
    title: str,
    source_text: str,
    episode_script: str,
    panels: list[dict[str, Any]],
    content_mode: str,
) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    shots: list[dict[str, Any]] = []
    strategy_counts: dict[str, int] = {}
    for index, panel in enumerate([item for item in panels if isinstance(item, dict)], start=1):
        segment_id = _safe_workflow_id(str(panel.get("segmentId") or panel.get("segment_id") or f"seg_{index:03d}"), f"seg_{index:03d}")
        shot_id = _safe_workflow_id(str(panel.get("shotId") or panel.get("shot_id") or f"shot_{index:03d}"), f"shot_{index:03d}")
        strategy = _panel_generation_strategy(panel)
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        prompts = _panel_to_prompts(panel)
        reference_media_ids = _panel_reference_media_ids(panel)
        continuity_anchor = _panel_row_text(panel, "continuityAnchor", "continuity_anchor")
        title_text = _panel_row_text(panel, "title", "name") or f"镜头 {index}"
        visible_action = (
            _panel_row_text(panel, "visibleAction", "visible_action")
            or _first_text(prompts.get("storyboardImagePrompt"))
        )
        reference_plan = panel.get("referencePlan") if isinstance(panel.get("referencePlan"), dict) else {}
        reference_plan = {
            "mode": reference_plan.get("mode") or _strategy_reference_mode(strategy),
            "requiredImages": reference_plan.get("requiredImages") or reference_media_ids,
            "optionalImages": reference_plan.get("optionalImages") or [],
            "videoRefs": reference_plan.get("videoRefs") or [],
        }
        segment = {
            "id": segment_id,
            "title": title_text,
            "purpose": _panel_row_text(panel, "purpose", "dramaticPurpose", "dramatic_purpose", "narrativePurpose") or "beat",
            "sourceRefs": panel.get("sourceRefs") or panel.get("source_refs") or [{"episodeId": episode_id, "panelIndex": index}],
            "sourceText": _panel_row_text(panel, "sourceText", "source_text") or source_text,
            "summary": _panel_row_text(panel, "summary") or title_text,
            "generationStrategy": strategy,
            "assetRefs": _segment_asset_refs(panel),
            "screenplay": panel.get("screenplay") if isinstance(panel.get("screenplay"), dict) else {
                "sceneText": _panel_row_text(panel, "sceneText", "scene_text", "visualPrompt", "visual_prompt"),
                "narrationText": _panel_row_text(panel, "narrationText", "narration", "voiceover"),
                "performanceBeat": _panel_row_text(panel, "performanceBeat", "performance_beat"),
                "blocking": _panel_row_text(panel, "blocking"),
            },
            "dialogue": panel.get("dialogue") if isinstance(panel.get("dialogue"), list) else [],
            "prompts": prompts,
            "referencePlan": reference_plan,
            "quality": {
                "continuityAnchor": continuity_anchor,
                "riskNotes": panel.get("riskNotes") if isinstance(panel.get("riskNotes"), list) else [],
                "safeToGenerate": bool(prompts.get("storyboardImagePrompt")),
            },
        }
        shot = {
            "id": shot_id,
            "segmentId": segment_id,
            "title": title_text,
            "assetRefs": copy.deepcopy(segment.get("assetRefs") or {}),
            "coverageRole": _panel_row_text(panel, "coverageRole", "coverage_role") or "storyboard",
            "shotSize": _panel_row_text(panel, "shotSize", "shot_size"),
            "visibleAction": visible_action,
            "startState": panel.get("startState") if isinstance(panel.get("startState"), dict) else {},
            "endState": panel.get("endState") if isinstance(panel.get("endState"), dict) else {},
            "camera": panel.get("camera") if isinstance(panel.get("camera"), dict) else {
                "motion": _panel_row_text(panel, "cameraMotion", "camera_motion"),
                "angle": _panel_row_text(panel, "cameraAngle", "camera_angle"),
            },
            "referencePlan": copy.deepcopy(reference_plan),
            "storyboardImagePrompt": segment["prompts"].get("storyboardImagePrompt") or "",
        }
        segments.append(segment)
        shots.append(shot)
    return {
        "schemaVersion": 2,
        "episodeId": episode_id,
        "contentMode": content_mode,
        "episodeTitle": title,
        "sourceRange": {"episodeId": episode_id},
        "sourceText": source_text,
        "episodeScript": episode_script,
        "segments": segments,
        "shots": shots,
        "strategyPlan": [
            {"strategy": strategy, "segmentCount": count}
            for strategy, count in sorted(strategy_counts.items())
        ],
        "modelCapabilityRequirements": [
            "imageGeneration",
            "resolutions",
        ],
    }


def _shot_plan_generation_config(strategy: str, config: dict[str, Any]) -> dict[str, Any]:
    strategy = _normalize_video_generation_strategy(strategy)
    model_config = (
        config.get("model_config")
        if isinstance(config.get("model_config"), dict)
        else config.get("modelConfig")
        if isinstance(config.get("modelConfig"), dict)
        else {}
    )
    defaults_config = config.get("defaults") if isinstance(config.get("defaults"), dict) else {}

    def merged_section(*sections: Any) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for section in sections:
            if isinstance(section, dict):
                merged.update(copy.deepcopy(section))
        return merged

    video_config = merged_section(
        defaults_config.get("video") if isinstance(defaults_config, dict) else {},
        config.get("video") if isinstance(config.get("video"), dict) else {},
        model_config.get("video") if isinstance(model_config, dict) else {},
    )
    image_config = merged_section(
        defaults_config.get("image") if isinstance(defaults_config, dict) else {},
        config.get("image") if isinstance(config.get("image"), dict) else {},
        model_config.get("image") if isinstance(model_config, dict) else {},
    )
    storyboard_config = merged_section(
        defaults_config.get("storyboard") if isinstance(defaults_config, dict) else {},
        config.get("storyboard") if isinstance(config.get("storyboard"), dict) else {},
    )
    aspect_ratio = (
        config.get("aspect_ratio")
        or config.get("aspectRatio")
        or defaults_config.get("aspect_ratio")
        or defaults_config.get("aspectRatio")
    )
    image_size = (
        image_config.get("storyboard_resolution")
        or image_config.get("storyboardResolution")
        or storyboard_config.get("image_size")
        or storyboard_config.get("imageSize")
        or image_config.get("resolution")
        or image_config.get("asset_resolution")
        or "2K"
    )
    video_section = {
        "purpose": (
            "storyboard_to_video"
            if strategy == "storyboard_multi_shot"
            else "text_to_video"
            if strategy == "text_to_video_draft"
            else "image_to_video"
        ),
        "resolution": video_config.get("resolution") or "720p",
        "referenceMode": _strategy_reference_mode(strategy),
        "requiresReferenceMedia": strategy == "storyboard_multi_shot",
    }
    image_section = {
        "purpose": "storyboard_image",
        "size": image_size,
        "resolution": image_size,
    }
    if aspect_ratio:
        video_section["aspectRatio"] = aspect_ratio
        image_section["aspectRatio"] = aspect_ratio
    return {
        "video": video_section,
        "image": image_section,
    }


def _shot_segment_id(shot: dict[str, Any], index: int) -> str:
    return str(shot.get("segmentId") or shot.get("segment_id") or shot.get("segment") or f"seg_{index:03d}").strip()


def _shot_plan_segment_rows(shot_plan: dict[str, Any]) -> list[dict[str, Any]]:
    raw_segments = [item for item in (shot_plan.get("segments") or []) if isinstance(item, dict)]
    if raw_segments:
        return [_storyboard_only_planning_item(item) for item in raw_segments]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for index, shot in enumerate(shot_plan.get("shots") or [], start=1):
        if not isinstance(shot, dict):
            continue
        segment_id = _shot_segment_id(shot, index)
        grouped.setdefault(segment_id, []).append(shot)
    rows: list[dict[str, Any]] = []
    for index, (segment_id, shots) in enumerate(grouped.items(), start=1):
        first_shot = shots[0] if shots else {}
        rows.append(
            {
                "id": segment_id or f"seg_{index:03d}",
                "title": str(first_shot.get("title") or first_shot.get("coverageRole") or f"镜头段 {index}"),
                "sourceRefs": copy.deepcopy(first_shot.get("sourceRefs") or []),
                "assetRefs": copy.deepcopy(first_shot.get("assetRefs") or {}),
                "generationStrategy": first_shot.get("generationStrategy") or "storyboard_multi_shot",
                "narrativePurpose": first_shot.get("visibleAction") or first_shot.get("coverageRole") or "",
            }
        )
    return rows


def _shots_for_segment(shot_plan: dict[str, Any], segment_id: str) -> list[dict[str, Any]]:
    shots: list[dict[str, Any]] = []
    for index, shot in enumerate(shot_plan.get("shots") or [], start=1):
        if not isinstance(shot, dict):
            continue
        if _shot_segment_id(shot, index) == segment_id:
            shots.append(_storyboard_only_planning_item(shot))
    return shots


def _segment_has_explicit_routes(segment: dict[str, Any]) -> bool:
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
            return True
        if isinstance(value, dict) and value:
            return True
    return False


def _shot_asset_refs(shot: dict[str, Any], segment: dict[str, Any]) -> dict[str, Any]:
    value = shot.get("assetRefs") or shot.get("asset_refs")
    if isinstance(value, dict):
        return copy.deepcopy(value)
    value = segment.get("assetRefs") or segment.get("asset_refs")
    return copy.deepcopy(value if isinstance(value, dict) else {})


def _workflow_segments_for_shot_plan(shot_plan: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    segments = _shot_plan_segment_rows(shot_plan)
    expanded_segments: list[dict[str, Any]] = []
    expanded_shots: list[dict[str, Any]] = []
    used_work_chain_ids: set[str] = set()

    def next_work_chain_id() -> str:
        index = len(expanded_segments) + 1
        while True:
            chain_id = f"chain_{index:03d}"
            if chain_id not in used_work_chain_ids:
                used_work_chain_ids.add(chain_id)
                return chain_id
            index += 1

    for segment_index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        segment_id = str(segment.get("id") or segment.get("segmentId") or segment.get("segment_id") or f"seg_{segment_index:03d}")
        segment_shots = _shots_for_segment(shot_plan, segment_id)
        split_mode = str(
            segment.get("workflowSplitMode")
            or segment.get("workflow_split_mode")
            or segment.get("splitMode")
            or ""
        ).strip().lower()
        keep_together = split_mode in {"segment", "single", "single_chain", "keep", "keep_together"}
        split_by_shot = split_mode in {
            "shot",
            "shots",
            "per_shot",
            "split_shots",
            "split_by_shot",
            "shot_chain",
            "shot_chains",
        }
        should_split = (
            len(segment_shots) > 1
            and split_by_shot
            and not keep_together
            and not _segment_has_explicit_routes(segment)
        )
        if not should_split:
            copied_segment = copy.deepcopy(segment)
            existing_chain_id = str(
                copied_segment.get("workChainId")
                or copied_segment.get("work_chain_id")
                or copied_segment.get("chainId")
                or copied_segment.get("chain_id")
                or ""
            ).strip()
            if existing_chain_id:
                used_work_chain_ids.add(_safe_workflow_id(existing_chain_id, existing_chain_id))
            expanded_segments.append(copied_segment)
            expanded_shots.extend(copy.deepcopy(segment_shots))
            continue

        for shot_index, shot in enumerate(segment_shots, start=1):
            if not isinstance(shot, dict):
                continue
            shot_id = str(shot.get("id") or f"shot_{shot_index:03d}").strip()
            split_segment_id = _safe_workflow_id(
                f"{segment_id}_{shot_id}",
                f"{segment_id}_shot_{shot_index:03d}",
            )
            split_segment = copy.deepcopy(segment)
            shot_title = str(shot.get("title") or shot.get("name") or f"镜头 {shot_index}").strip()
            visible_action = str(shot.get("visibleAction") or shot.get("summary") or _shot_text(shot)).strip()
            split_segment.update(
                {
                    "id": split_segment_id,
                    "segmentId": split_segment_id,
                    "title": shot_title,
                    "sourceRefs": copy.deepcopy(shot.get("sourceRefs") or segment.get("sourceRefs") or []),
                    "assetRefs": _shot_asset_refs(shot, segment),
                    "anchorText": visible_action or shot_title,
                    "narrativePurpose": visible_action or shot_title,
                    "generationStrategy": str(
                        shot.get("generationStrategy")
                        or shot.get("generation_strategy")
                        or segment.get("generationStrategy")
                        or "storyboard_multi_shot"
                    ),
                    "workChainId": next_work_chain_id(),
                    "workChainLabel": shot_title,
                    "workflowSplitSource": {
                        "segmentId": segment_id,
                        "shotId": shot_id,
                        "mode": "shot",
                    },
                    "prompts": {
                        "storyText": (
                            shot.get("storyText")
                            or shot.get("story_text")
                            or shot.get("visibleAction")
                            or shot.get("summary")
                            or ""
                        ),
                        "storyboardImagePrompt": shot.get("storyboardImagePrompt") or "",
                    },
                    "quality": copy.deepcopy(shot.get("quality") or segment.get("quality") or {}),
                    "referencePlan": copy.deepcopy(shot.get("referencePlan") or segment.get("referencePlan") or {}),
                }
            )
            split_shot = copy.deepcopy(shot)
            split_shot["segmentId"] = split_segment_id
            split_shot["sourceSegmentId"] = segment_id
            source_timing_plan = segment.get("shotTimingPlan") if isinstance(segment.get("shotTimingPlan"), dict) else {}
            source_timing_rows = source_timing_plan.get("shots") if isinstance(source_timing_plan.get("shots"), list) else []
            source_timing_row = (
                source_timing_rows[shot_index - 1]
                if shot_index - 1 < len(source_timing_rows) and isinstance(source_timing_rows[shot_index - 1], dict)
                else {}
            )
            shot_duration = _workflow_timing_number(
                source_timing_row.get("durationSeconds")
                or source_timing_row.get("duration_seconds")
                or source_timing_row.get("duration")
                or split_shot.get("durationSeconds")
                or split_shot.get("duration_seconds")
                or split_shot.get("duration")
            )
            if shot_duration and shot_duration > 0:
                clean_duration = _workflow_clean_seconds(float(shot_duration))
                split_timing_plan = {
                    "schemaVersion": 1,
                    "durationSeconds": clean_duration,
                    "shotCount": 1,
                    "shots": [
                        {
                            "shotLabel": "Shot 01",
                            "durationSeconds": clean_duration,
                            "startSecond": 0,
                            "endSecond": clean_duration,
                        }
                    ],
                    "source": "work_chain_planning",
                    "scope": "work_chain",
                    "title": shot_title,
                }
                split_segment["durationSeconds"] = clean_duration
                split_segment["shotTimingPlan"] = copy.deepcopy(split_timing_plan)
                split_shot["shotLabel"] = "Shot 01"
                split_shot["durationSeconds"] = clean_duration
                split_shot["startSecond"] = 0
                split_shot["endSecond"] = clean_duration
            expanded_segments.append(split_segment)
            expanded_shots.append(split_shot)

    expanded_shot_plan = {**shot_plan, "segments": expanded_segments, "shots": expanded_shots}
    return expanded_segments, expanded_shot_plan


def _shot_text(shot: dict[str, Any]) -> str:
    parts = [
        shot.get("coverageRole"),
        shot.get("visibleAction"),
        (shot.get("camera") or {}).get("shotType") if isinstance(shot.get("camera"), dict) else "",
        (shot.get("camera") or {}).get("composition") if isinstance(shot.get("camera"), dict) else "",
        (shot.get("camera") or {}).get("cameraMotion") if isinstance(shot.get("camera"), dict) else "",
    ]
    return "；".join(str(item).strip() for item in parts if str(item or "").strip())


def _shot_camera_text(shot: dict[str, Any]) -> str:
    camera = shot.get("camera") if isinstance(shot.get("camera"), dict) else {}
    return "，".join(
        str(camera.get(key) or "").strip()
        for key in ("shotType", "angle", "composition", "lighting", "cameraMotion")
        if str(camera.get(key) or "").strip()
    )


def _storyboard_segment_prompt(segment: dict[str, Any], shots: list[dict[str, Any]], shot_lines: list[str]) -> str:
    shot_count = len(shots)
    narrative = str(segment.get("narrativePurpose") or segment.get("summary") or "").strip()
    label = str(segment.get("label") or segment.get("title") or narrative or "连续剧情").strip()
    lines = [
        f"为“{label}”生成专业电影故事版分镜页，包含 {shot_count or '多'} 个按时间顺序排列的面板。",
        "按真实镜头数量灵活排版。每个面板要有镜头编号、景别/构图、角色调度、关键道具和人物或镜头运动箭头。",
        "同一剧情中的角色造型、场景空间、光线方向、道具位置保持连续，用于导演预演和后续视频生成。",
        "故事版页就是后续视频模型的主参考图，必须清楚表达连续镜头、起止状态和叙事节奏。",
    ]
    if narrative:
        lines.append(f"剧情目的：{narrative}")
    for index, shot in enumerate(shots, start=1):
        action = str(shot.get("visibleAction") or shot.get("summary") or "").strip()
        camera = _shot_camera_text(shot)
        fallback = shot_lines[index - 1] if index - 1 < len(shot_lines) else ""
        parts = [f"{index}. {action or fallback or '连续镜头'}"]
        if camera:
            parts.append(f"镜头：{camera}")
        lines.append("；".join(parts))
    return _normalize_multiline_prompt_text("\n".join(lines))


def _safe_video_prompt_text(prompt: str) -> str:
    """Lossless cleanup for functional video prompt context.

    Do not delete negative constraints or trim by length here. This text can be
    fed back into model/API prompt chains, so missing data must be handled by
    validation/blocking at the caller boundary instead of local hard cutting.
    """
    value = str(prompt or "").strip()
    if not value:
        return value
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    normalized: list[str] = []
    for line in lines:
        if line:
            normalized.append(line)
        elif normalized and normalized[-1]:
            normalized.append("")
    return "\n".join(normalized).strip()


def _storyboard_analysis_story_text_hash(value: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").replace("@", "").replace("＠", "")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _segment_prompt_field_text(
    segment: dict[str, Any],
    prompts: dict[str, Any] | None,
    keys: tuple[str, ...],
    *,
    include_task_card: bool = False,
    limit: int = 1200,
    preserve_newlines: bool = False,
) -> str:
    task_card = segment.get("storyboardTaskCard") if isinstance(segment.get("storyboardTaskCard"), dict) else {}
    candidates: list[Any] = []
    if include_task_card:
        for key in keys:
            candidates.append(task_card.get(key))
        if "content" in keys:
            candidates.append(task_card.get("content"))
    for source in (segment, prompts if isinstance(prompts, dict) else {}):
        if not isinstance(source, dict):
            continue
        for key in keys:
            candidates.append(source.get(key))
    for value in candidates:
        text = _workflow_prompt_text_value(value)
        if text:
            if preserve_newlines:
                return _normalize_multiline_prompt_text(text)
            return _normalize_inline_prompt_text(text)
    return ""


def _normalize_inline_prompt_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_multiline_prompt_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized: list[str] = []
    for line in lines:
        if line:
            normalized.append(line)
        elif normalized and normalized[-1]:
            normalized.append("")
    return "\n".join(normalized).strip()


def _compact_multiline_prompt_text(value: Any, limit: int = 1200) -> str:
    """Lossy preview helper.

    Only use this for UI summaries, logs, diagnostics, and fields whose name
    explicitly means preview/summary. Never use it for canonical story text,
    prompts, model request payloads, provider API payloads, or any value that
    affects generation results.
    """
    text = _normalize_multiline_prompt_text(value)
    return text[:limit] + ("..." if len(text) > limit else "")


def _segment_story_text(segment: dict[str, Any]) -> str:
    return _segment_prompt_field_text(
        segment,
        {},
        (
            "cinematicStoryText",
            "cinematic_story_text",
        ),
        include_task_card=True,
        limit=1200,
        preserve_newlines=True,
    )


def _segment_prompts(segment: dict[str, Any], shots: list[dict[str, Any]]) -> dict[str, Any]:
    prompts = copy.deepcopy(segment.get("prompts") if isinstance(segment.get("prompts"), dict) else {})
    shot_lines = [_shot_text(shot) for shot in shots]
    shot_lines = [line for line in shot_lines if line]
    story_text = _segment_prompt_field_text(
        segment,
        prompts,
        (
            "cinematicStoryText",
            "cinematic_story_text",
        ),
        include_task_card=True,
        limit=1200,
        preserve_newlines=True,
    )
    source_fact_text = _segment_prompt_field_text(
        segment,
        prompts,
        (
            "sourceFactText",
            "source_fact_text",
            "originalFactText",
            "original_fact_text",
            "sourcePreview",
            "source_preview",
            "sceneBrief",
            "scene_brief",
            "narrativePurpose",
            "summary",
            "description",
        ),
        include_task_card=True,
        limit=1600,
        preserve_newlines=True,
    )
    dialogue_text = _segment_prompt_field_text(
        segment,
        prompts,
        ("dialogueText", "dialogue_text", "dialogue", "narrationText", "narration_text"),
        limit=800,
        preserve_newlines=True,
    )
    user_notes = _segment_prompt_field_text(
        segment,
        prompts,
        ("userNotes", "user_notes", "notes", "instruction", "userInstruction", "user_instruction"),
        limit=800,
        preserve_newlines=True,
    )
    complete_story_parts = [story_text] if story_text else []
    if dialogue_text and dialogue_text not in complete_story_parts:
        complete_story_parts.append(f"台词/旁白线索：{dialogue_text}")
    if user_notes and user_notes not in complete_story_parts:
        complete_story_parts.append(f"补充要求：{user_notes}")
    complete_story_text = _normalize_multiline_prompt_text("\n".join(complete_story_parts))
    storyboard_prompt = _normalize_multiline_prompt_text(
        prompts.get("storyboardImagePrompt") or prompts.get("imagePrompt") or complete_story_text,
    )
    if not storyboard_prompt:
        storyboard_prompt = _storyboard_segment_prompt(segment, shots, shot_lines)
    return {
        "cinematicStoryText": complete_story_text,
        "sourceFactText": source_fact_text,
        "dialogueText": dialogue_text,
        "userNotes": user_notes,
        "storyboardImagePrompt": storyboard_prompt,
    }
