# -*- coding: utf-8 -*-
"""工作链规划的节点、输入、时长与模型选择契约。"""
from __future__ import annotations

from .storyboard_templates import (
    storyboard_template_id,
    storyboard_template_label,
)
from typing import (
    Any,
)

import copy
import re
import traceback
from .agent_sessions import (
    _project_meta_path,
)
from .projects import (
    _first_text,
)
from .reference_utils import (
    asset_ref_tokens as _shared_asset_ref_tokens,
)
from .splitting_templates import (
    _string_list,
)
from .store_core import (
    _read_json,
)
from .video_input_plan import (
    normalize_video_input_mode as _shared_normalize_video_input_mode,
    video_input_required_slots as _shared_video_input_required_slots,
    video_reference_mode_for_input_mode as _shared_video_reference_mode_for_input_mode,
    video_strategy_for_input_mode as _shared_video_strategy_for_input_mode,
)


_WORKFLOW_LAYOUT_CHAIN_GAP_Y = 463


_WORKFLOW_LAYOUT_ASSET_TO_MAIN_GAP_Y = 87


_LEGACY_STORYBOARD_VIDEO_STRATEGIES = {
    "storyboard_reference",
    "storyboard_reference_image",
    "storyboard_reference_if_supported",
    "storyboard_image",
}


_IMAGE_REFERENCE_VIDEO_STRATEGIES = {
    "image_reference",
    "image_reference_video",
    "reference_image",
    "asset_image",
    "asset_reference",
    "first_last",
    "first_last_frame",
    "first_frame_last_frame",
    "keyframe",
    "keyframes",
    "multi_keyframe",
    "multi_keyframes",
    "keyframe_reference",
    "single_image",
    "image_to_video",
    "single_image_to_video",
}


_CANVAS_NODE_ROLE_IMAGE_ASSET = "image_asset"


_WORKFLOW_ASSET_INPUT_HANDLE = "asset_input"


_WORKFLOW_VIDEO_INPUT_HANDLE = "video_input"


_DEFERRED_VIDEO_PLANNING_FIELDS = (
    "videoIntent",
    "video_intent",
    "videoPrompt",
    "video_prompt",
    "durationSeconds",
    "duration",
    "shotTimingPlan",
    "shot_timing_plan",
    "storyboardAnalysis",
    "storyboard_analysis",
    "storyboardAnalysisStoryTextHash",
    "storyboard_analysis_story_text_hash",
    "storyboardPlanHash",
    "storyboard_plan_hash",
    "storyboardPlanState",
    "storyboard_plan_state",
    "visualBeats",
    "visual_beats",
    "panels",
)


def _workflow_episode_title(project_id: str | None, episode_id: str, shot_plan: dict[str, Any]) -> str:
    from .source_boundary_contract import _normalize_episode_boundary_title
    from .source_text_store import _episode_source_ref_path

    proposal = shot_plan.get("plotSplitProposal") if isinstance(shot_plan.get("plotSplitProposal"), dict) else {}
    candidates: list[Any] = [
        shot_plan.get("episodeTitle"),
        shot_plan.get("episode_title"),
        shot_plan.get("title"),
        shot_plan.get("name"),
        proposal.get("episodeTitle"),
        proposal.get("episode_title"),
        proposal.get("title"),
    ]
    if project_id:
        try:
            source_ref = _read_json(_episode_source_ref_path(project_id, episode_id), {})
            if isinstance(source_ref, dict):
                candidates.extend(
                    [
                        source_ref.get("title"),
                        source_ref.get("episodeTitle"),
                        source_ref.get("episode_title"),
                    ]
                )
        except Exception:
            print(traceback.format_exc(), flush=True)
        try:
            meta = _read_json(_project_meta_path(project_id), {})
            episodes = meta.get("episodes") if isinstance(meta.get("episodes"), list) else []
            for episode in episodes:
                if not isinstance(episode, dict):
                    continue
                if str(episode.get("id") or "") == str(episode_id):
                    candidates.extend([episode.get("title"), episode.get("name")])
                    break
        except Exception:
            print(traceback.format_exc(), flush=True)
    for candidate in candidates:
        title = _normalize_episode_boundary_title(candidate, episode_id)
        if title:
            return title
    return ""


def _panel_row_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, dict):
            text = _first_text(value)
        else:
            text = str(value or "").strip()
        if text:
            return text
    return ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text and text not in result:
                result.append(text)
        return result
    text = str(value or "").strip()
    return [text] if text else []


def _append_unique_string(values: Any, value: str) -> list[str]:
    result = _string_list(values)
    text = str(value or "").strip()
    if text and text not in result:
        result.append(text)
    return result


def _panel_reference_media_ids(panel: dict[str, Any]) -> list[str]:
    for key in ("referenceMediaIds", "reference_media_ids", "requiredImages", "inputImages"):
        values = _string_list(panel.get(key))
        if values:
            return values
    reference_plan = panel.get("referencePlan") if isinstance(panel.get("referencePlan"), dict) else {}
    values = []
    for key in ("requiredImages", "optionalImages", "images"):
        values.extend(_string_list(reference_plan.get(key)))
    return list(dict.fromkeys(values))


def _normalize_video_generation_strategy(strategy: Any) -> str:
    text = str(strategy or "").strip()
    if not text:
        return "storyboard_multi_shot"
    normalized = _shared_normalize_video_input_mode(text)
    if normalized == "text_to_video_draft" or text == "text_to_video_draft":
        return "text_to_video_draft"
    if normalized == "image_reference" or text in _IMAGE_REFERENCE_VIDEO_STRATEGIES:
        return "image_reference_video"
    if normalized == "storyboard_reference" or text in _LEGACY_STORYBOARD_VIDEO_STRATEGIES:
        return "storyboard_multi_shot"
    return text


def _panel_generation_strategy(panel: dict[str, Any]) -> str:
    strategy = _panel_row_text(panel, "generationStrategy", "generation_strategy", "strategy")
    if strategy:
        return _normalize_video_generation_strategy(strategy)
    return "storyboard_multi_shot"


def _strategy_reference_mode(strategy: str) -> str:
    strategy = _normalize_video_generation_strategy(strategy)
    if strategy == "text_to_video_draft":
        return "none"
    if strategy == "image_reference_video":
        return "image_reference"
    return "storyboard_image"


def _normalize_video_input_mode(value: Any, fallback_strategy: str = "") -> str:
    mode = _shared_normalize_video_input_mode(value)
    if mode:
        return mode
    strategy = _normalize_video_generation_strategy(fallback_strategy)
    if strategy == "text_to_video_draft":
        return "text_to_video_draft"
    if strategy == "image_reference_video":
        return "image_reference"
    return "storyboard_reference"


def _video_input_mode_to_reference_mode(mode: str) -> str:
    return _shared_video_reference_mode_for_input_mode(mode)


def _video_strategy_for_input_mode(strategy: str, mode: str) -> str:
    return _shared_video_strategy_for_input_mode(strategy, mode)


def _video_input_required_slots(mode: str) -> list[str]:
    return _shared_video_input_required_slots(mode)


def _segment_video_input_plan(segment: dict[str, Any], shots: list[dict[str, Any]], strategy: str) -> dict[str, Any]:
    raw_plan = segment.get("videoInputPlan") or segment.get("video_input_plan")
    if not isinstance(raw_plan, dict):
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            shot_plan = shot.get("videoInputPlan") or shot.get("video_input_plan")
            if isinstance(shot_plan, dict):
                raw_plan = shot_plan
                break
    plan = copy.deepcopy(raw_plan) if isinstance(raw_plan, dict) else {}
    raw_mode = (
        plan.get("mode")
        or plan.get("inputMode")
        or plan.get("input_mode")
        or plan.get("referenceMode")
        or plan.get("reference_mode")
        or raw_plan
    )
    mode = _normalize_video_input_mode(raw_mode, strategy)
    plan["mode"] = mode
    plan["referenceMode"] = _video_input_mode_to_reference_mode(mode)
    plan["videoStrategy"] = _video_strategy_for_input_mode(strategy, mode)
    plan["requiredSlots"] = _video_input_required_slots(mode)
    if not str(plan.get("reason") or "").strip():
        plan["reason"] = "故事版工作页负责导演规划，视频输入由本计划按模型能力单独执行。"
    return plan


def _apply_video_input_plan_to_generation_config(
    generation_config: dict[str, Any],
    video_input_plan: dict[str, Any],
) -> dict[str, Any]:
    config = copy.deepcopy(generation_config)
    video_config = config.get("video") if isinstance(config.get("video"), dict) else {}
    video_config = copy.deepcopy(video_config)
    mode = str(video_input_plan.get("mode") or "").strip()
    reference_mode = str(video_input_plan.get("referenceMode") or _video_input_mode_to_reference_mode(mode)).strip()
    if reference_mode:
        video_config["inputMode"] = reference_mode
        video_config["referenceMode"] = reference_mode
    if mode:
        video_config["videoInputMode"] = mode
    video_config["videoInputPlan"] = copy.deepcopy(video_input_plan)
    config["video"] = video_config
    return config


def _video_node_type_for_strategy(strategy: str) -> str:
    return "video.storyboard"


def _generation_section_config(generation_config: dict[str, Any], section: str) -> dict[str, Any]:
    value = generation_config.get(section) if isinstance(generation_config, dict) else {}
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _node_model_selection(section: str, generation_config: dict[str, Any]) -> dict[str, Any]:
    section_config = _generation_section_config(generation_config, section)
    selection: dict[str, Any] = {"section": section}
    model_id = section_config.get("modelId") or section_config.get("model_id") or section_config.get("model")
    provider_id = section_config.get("providerId") or section_config.get("provider_id")
    provider_preset_id = section_config.get("providerPresetId") or section_config.get("provider_preset_id")
    if model_id:
        selection["modelId"] = model_id
    if provider_id:
        selection["providerId"] = provider_id
    if provider_preset_id:
        selection["providerPresetId"] = provider_preset_id
    for key in ("resolution", "size", "aspectRatio", "aspect_ratio", "fps"):
        if key in section_config and section_config.get(key) is not None:
            selection[key] = copy.deepcopy(section_config.get(key))
    return selection


def _video_task_generation_config(value: Any) -> dict[str, Any]:
    config = copy.deepcopy(value) if isinstance(value, dict) else {}
    for key in ("durationSeconds", "duration_seconds", "duration"):
        config.pop(key, None)
    return config


def _node_capability_requirements(
    strategy: str,
    generation_config: dict[str, Any],
    media_type: str,
    *,
    frame_slot: str = "",
) -> dict[str, Any]:
    if media_type == "video":
        strategy = _normalize_video_generation_strategy(strategy)
    if media_type == "video":
        video_config = _generation_section_config(generation_config, "video")
        reference_mode = str(video_config.get("referenceMode") or video_config.get("inputMode") or _strategy_reference_mode(strategy))
        min_image_inputs = 1 if strategy == "storyboard_multi_shot" else 0
        return {
            "mediaType": "video",
            "strategy": strategy,
            "inputMode": reference_mode,
            "minImageInputs": min_image_inputs,
            "requiresImageToVideo": strategy == "storyboard_multi_shot",
            "requiresStoryboardReferenceImage": strategy == "storyboard_multi_shot",
            "resolution": video_config.get("resolution"),
            "aspectRatio": video_config.get("aspectRatio") or video_config.get("aspect_ratio"),
            "fps": video_config.get("fps"),
        }
    image_config = _generation_section_config(generation_config, "image")
    return {
        "mediaType": "image",
        "strategy": strategy,
        "outputSlot": frame_slot or "storyboard_image",
        "requiresAssetReferences": strategy != "text_to_video_draft",
        "resolution": image_config.get("resolution") or image_config.get("size"),
        "aspectRatio": image_config.get("aspectRatio") or image_config.get("aspect_ratio"),
    }


def _workflow_node_default_card_size(node_type: str) -> dict[str, int]:
    if node_type in {"asset.image", "media.external"}:
        return {"width": 240, "height": 300, "minWidth": 220, "minHeight": 220}
    if node_type == "storyboard.image":
        return {"width": 320, "height": 300, "minWidth": 280, "minHeight": 240}
    if node_type == "video.result":
        return {"width": 360, "height": 260, "minWidth": 320, "minHeight": 220}
    if node_type.startswith("video."):
        return {"width": 360, "height": 300, "minWidth": 320, "minHeight": 240}
    if node_type == "prompt.storyboard":
        return {"width": 340, "height": 280, "minWidth": 300, "minHeight": 240}
    if node_type == "director.board":
        return {"width": 380, "height": 360, "minWidth": 340, "minHeight": 300}
    if node_type == "storyboard.card":
        return {"width": 360, "height": 300, "minWidth": 320, "minHeight": 240}
    if node_type == "source.text":
        return {"width": 340, "height": 160, "minWidth": 320, "minHeight": 140}
    return {"width": 320, "height": 360, "minWidth": 280, "minHeight": 260}


def _ensure_workflow_node_contract(node: dict[str, Any]) -> None:
    node_type = str(node.get("type") or "")
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    node["data"] = data
    for key in ("workChainId", "routeId", "segmentId", "strategy"):
        if node.get(key) is None and data.get(key) is not None:
            node[key] = data.get(key)
        elif key not in node:
            node[key] = data.get(key) or ""
        data.setdefault(key, node.get(key) or "")
    data.setdefault("title", node.get("id") or node_type or "工作流节点")
    data.setdefault("status", "idle")
    data.setdefault("summary", "")
    data.setdefault("assetRefs", {})
    data.setdefault("prompt", {})
    if node_type == "prompt.storyboard":
        data.setdefault("screenplay", {})
        data.setdefault("dialogue", [])
    data.setdefault("generationConfig", {})
    data.setdefault("modelSelection", {})
    data.setdefault("capabilityRequirements", {})
    data.setdefault("capabilityCheck", {})
    data.setdefault("referenceMediaIds", [])
    data.setdefault("inputLinks", [])
    data.setdefault("resultOfNodeId", "")
    card_state = data.get("cardState") if isinstance(data.get("cardState"), dict) else {}
    size = card_state.get("size") if isinstance(card_state.get("size"), dict) else {}
    for key, value in _workflow_node_default_card_size(node_type).items():
        size.setdefault(key, value)
    card_state["size"] = size
    data["cardState"] = card_state


def _ensure_workflow_nodes_contract(nodes: list[dict[str, Any]]) -> None:
    for node in nodes:
        if isinstance(node, dict):
            _ensure_workflow_node_contract(node)


def _workflow_chain_continuity(value: Any, shot_ids: list[str] | None = None) -> str:
    text = str(value or "").strip().lower()
    if text in {"continuous", "single_shot", "manual"}:
        return text
    if text in {"single", "single-shot", "single_shot", "shot"}:
        return "single_shot"
    if text in {"manual", "custom"}:
        return "manual"
    if shot_ids is not None and len(shot_ids) <= 1:
        return "single_shot"
    return "continuous"


def _route_reference_specs(
    segment_id: str,
    strategy: str,
    prompts: dict[str, Any],
    segment_index: int,
    route_index: int = 1,
    shots: list[dict[str, Any]] | None = None,
    video_input_mode: str = "",
) -> list[dict[str, Any]]:
    def scoped_id(kind: str, fallback: str, index: int | None = None) -> str:
        route_suffix = "" if route_index <= 1 else f"_route_{route_index:02d}"
        raw_parts = [kind, segment_id]
        if index is not None:
            raw_parts.append(f"{index:02d}")
        raw = "_".join(raw_parts) + route_suffix
        scoped_fallback = fallback if route_index <= 1 else f"{fallback}_{route_index:02d}"
        return _safe_workflow_id(raw, scoped_fallback)

    video_input_mode = _normalize_video_input_mode(video_input_mode, strategy)

    def storyboard_specs() -> list[dict[str, Any]]:
        shot_rows = [copy.deepcopy(shot) for shot in (shots or []) if isinstance(shot, dict)]
        shot_ids = [
            str(shot.get("id") or shot.get("shotId") or shot.get("shot_id") or f"shot_{shot_index:03d}")
            for shot_index, shot in enumerate(shot_rows, start=1)
        ]
        return [
            {
                "id": scoped_id("storyboard_image", f"storyboard_image_{segment_index:03d}"),
                "type": "storyboard.image",
                "label": "分镜图",
                "targetSlot": "storyboard_image",
                "panelCount": len(shot_rows) or 1,
                "shotIds": shot_ids,
                "shots": shot_rows,
            }
        ]

    if strategy == "text_to_video_draft":
        return []
    if strategy == "storyboard_multi_shot":
        return storyboard_specs()
    return [
        {
            "id": scoped_id("storyboard_image", f"storyboard_image_{segment_index:03d}"),
            "type": "storyboard.image",
            "label": "分镜图",
            "targetSlot": "storyboard_image",
        }
    ]


def _segment_asset_refs(panel: dict[str, Any]) -> dict[str, Any]:
    refs = panel.get("assetRefs") or panel.get("asset_refs")
    if isinstance(refs, dict):
        return copy.deepcopy(refs)
    if isinstance(refs, list):
        return {"items": copy.deepcopy(refs)}
    return {
        "characters": _string_list(panel.get("characters") or panel.get("characterRefs")),
        "creatures": _string_list(panel.get("creatures") or panel.get("creatureRefs")),
        "scenes": _string_list(panel.get("scenes") or panel.get("sceneRefs")),
        "props": _string_list(panel.get("props") or panel.get("propRefs")),
    }


def _storyboard_only_planning_item(value: Any) -> dict[str, Any]:
    row = copy.deepcopy(value) if isinstance(value, dict) else {}
    for key in _DEFERRED_VIDEO_PLANNING_FIELDS:
        row.pop(key, None)
    prompts = row.get("prompts") if isinstance(row.get("prompts"), dict) else None
    if prompts is not None:
        prompts = copy.deepcopy(prompts)
        prompts.pop("videoPrompt", None)
        prompts.pop("video_prompt", None)
        row["prompts"] = prompts
    return row


def _storyboard_only_shot_plan(value: Any) -> dict[str, Any]:
    document = copy.deepcopy(value) if isinstance(value, dict) else {}
    for key in ("segments", "shots"):
        rows = document.get(key)
        if isinstance(rows, list):
            document[key] = [
                _storyboard_only_planning_item(item)
                for item in rows
                if isinstance(item, dict)
            ]
    return document


def _workflow_timing_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
        if not match:
            return None
        try:
            return float(match.group(0))
        except (TypeError, ValueError):
            return None


def _workflow_clean_seconds(value: float) -> int | float:
    if abs(value - round(value)) < 0.005:
        return int(round(value))
    return round(value, 2)


def _workflow_shot_timing_plan_duration(value: Any) -> int | float | None:
    plan = value if isinstance(value, dict) else {}
    direct = _workflow_timing_number(
        plan.get("durationSeconds") or plan.get("duration_seconds") or plan.get("duration")
    )
    if direct and direct > 0:
        return _workflow_clean_seconds(direct)
    rows = plan.get("shots") if isinstance(plan.get("shots"), list) else []
    total = 0.0
    has_duration = False
    max_end = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        duration = _workflow_timing_number(
            row.get("durationSeconds") or row.get("duration_seconds") or row.get("duration")
        )
        if duration and duration > 0:
            total += duration
            has_duration = True
        end_second = _workflow_timing_number(row.get("endSecond") or row.get("end_second"))
        if end_second and end_second > max_end:
            max_end = end_second
    if has_duration and total > 0:
        return _workflow_clean_seconds(total)
    if max_end > 0:
        return _workflow_clean_seconds(max_end)
    return None


def _workflow_shot_timing_plan_for_segment(
    segment: dict[str, Any],
    shots: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_plan = segment.get("shotTimingPlan") if isinstance(segment.get("shotTimingPlan"), dict) else {}
    if not raw_plan:
        return {}
    rows = raw_plan.get("shots") if isinstance(raw_plan.get("shots"), list) else []
    timing_shots: list[dict[str, Any]] = []
    running = 0.0
    shot_count = len(shots) or len(rows)
    for index in range(1, shot_count + 1):
        source = rows[index - 1] if index - 1 < len(rows) and isinstance(rows[index - 1], dict) else {}
        shot = shots[index - 1] if index - 1 < len(shots) and isinstance(shots[index - 1], dict) else {}
        duration = _workflow_timing_number(
            source.get("durationSeconds")
            or source.get("duration_seconds")
            or source.get("duration")
            or shot.get("durationSeconds")
            or shot.get("duration_seconds")
            or shot.get("duration")
        )
        start_second = _workflow_timing_number(
            source.get("startSecond") or source.get("start_second") or shot.get("startSecond") or shot.get("start_second")
        )
        end_second = _workflow_timing_number(
            source.get("endSecond") or source.get("end_second") or shot.get("endSecond") or shot.get("end_second")
        )
        if start_second is None:
            start_second = running
        if end_second is None:
            end_second = start_second + max(0.5, float(duration or 1.0))
        if duration is None:
            duration = max(0.5, float(end_second) - float(start_second))
        running = float(end_second)
        timing_shots.append(
            {
                "shotLabel": str(source.get("shotLabel") or shot.get("shotLabel") or f"Shot {index:02d}").strip(),
                "durationSeconds": _workflow_clean_seconds(float(duration)),
                "startSecond": _workflow_clean_seconds(float(start_second)),
                "endSecond": _workflow_clean_seconds(float(end_second)),
            }
        )
    duration_seconds = _workflow_shot_timing_plan_duration(raw_plan)
    if not duration_seconds and timing_shots:
        duration_seconds = _workflow_clean_seconds(float(timing_shots[-1].get("endSecond") or 0))
    if not duration_seconds:
        return {}
    return {
        "schemaVersion": int(raw_plan.get("schemaVersion") or raw_plan.get("schema_version") or 1),
        "durationSeconds": duration_seconds,
        "shotCount": len(timing_shots),
        "shots": timing_shots,
        "source": str(raw_plan.get("source") or "work_chain_planning"),
        "scope": str(raw_plan.get("scope") or "work_chain"),
        "title": str(raw_plan.get("title") or segment.get("title") or "").strip(),
    }


def _asset_ref_tokens(value: Any) -> list[str]:
    return _shared_asset_ref_tokens(value)


def _workflow_prompt_text_value(value: Any, preferred_keys: tuple[str, ...] = ()) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        rows = []
        for item in value:
            text = _workflow_prompt_text_value(item, preferred_keys)
            if text and text not in rows:
                rows.append(text)
        return "；".join(rows)
    if isinstance(value, dict):
        preferred_rows = []
        for key in preferred_keys:
            if key not in value:
                continue
            text = _workflow_prompt_text_value(value.get(key), preferred_keys)
            if text and text not in preferred_rows:
                preferred_rows.append(text)
        if preferred_rows:
            return "；".join(preferred_rows)

        ordered_keys = tuple(
            dict.fromkeys(
                preferred_keys
                + (
                    "text",
                    "prompt",
                    "description",
                    "summary",
                    "content",
                    "action",
                    "visibleAction",
                    "cameraMotion",
                    "temporalContinuity",
                    "sceneText",
                    "narrationText",
                    "performanceBeat",
                )
            )
        )
        rows = []
        visited: set[str] = set()
        for key in ordered_keys:
            if key not in value:
                continue
            visited.add(key)
            text = _workflow_prompt_text_value(value.get(key), preferred_keys)
            if text and text not in rows:
                rows.append(text)
        for key, item in value.items():
            if key in visited:
                continue
            if key in {"avoid", "negative", "negativePrompt", "negative_prompt", "blocking"}:
                continue
            if key in {
                "sourceFactText",
                "source_fact_text",
                "originalFactText",
                "original_fact_text",
                "factText",
                "fact_text",
                "sourcePreview",
                "source_preview",
            } and key not in preferred_keys:
                continue
            text = _workflow_prompt_text_value(item, preferred_keys)
            if text and text not in rows:
                rows.append(text)
        return "；".join(rows)
    return ""


def _safe_workflow_id(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("_")
    return cleaned or fallback


def _explicit_storyboard_template_id(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return storyboard_template_id(text)
    return ""


def _workflow_storyboard_template_fields(template_id: str) -> dict[str, str]:
    if not template_id:
        return {}
    return {
        "storyboardTemplate": template_id,
        "storyboardTemplateLabel": storyboard_template_label(template_id),
    }


def _workflow_card_template_fields(template_id: str) -> dict[str, str]:
    if not template_id:
        return {}
    return {
        "template": template_id,
        "templateLabel": storyboard_template_label(template_id),
    }


_WORKFLOW_VISUAL_HANDOFF_RESULT_CARD_SIZE = {
    "width": 260,
    "height": 280,
    "minWidth": 220,
    "minHeight": 220,
}


_WORKFLOW_VISUAL_HANDOFF_CROSS_EPISODE_CARD_SIZE = {
    "width": 240,
    "height": 260,
    "minWidth": 220,
    "minHeight": 220,
}


def _payload_document(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return copy.deepcopy(value)
    return copy.deepcopy(payload)


def _is_user_locked_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if any(bool(item.get(key)) for key in ("locked", "lockedByUser", "userLocked", "preserveOnReplan")):
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    return any(bool(data.get(key)) for key in ("locked", "lockedByUser", "userLocked", "preserveOnReplan"))


def _item_identity(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("id") or item.get("nodeId") or item.get("routeId") or item.get("segmentId") or "").strip()


def _preserve_locked_items(
    existing_items: Any,
    incoming_items: Any,
) -> list[dict[str, Any]]:
    incoming = [copy.deepcopy(item) for item in incoming_items if isinstance(item, dict)] if isinstance(incoming_items, list) else []
    existing = [copy.deepcopy(item) for item in existing_items if isinstance(item, dict)] if isinstance(existing_items, list) else []
    locked_by_id = {
        _item_identity(item): item
        for item in existing
        if _is_user_locked_item(item) and _item_identity(item)
    }
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in incoming:
        item_id = _item_identity(item)
        if item_id and item_id in locked_by_id:
            result.append(copy.deepcopy(locked_by_id[item_id]))
            seen.add(item_id)
        else:
            result.append(item)
            if item_id:
                seen.add(item_id)
    for item_id, item in locked_by_id.items():
        if item_id not in seen:
            result.append(copy.deepcopy(item))
    return result


def _preserve_locked_plan_document(
    existing_document: dict[str, Any],
    incoming_document: dict[str, Any],
) -> dict[str, Any]:
    document = copy.deepcopy(incoming_document)
    for key in ("segments", "shots", "strategyPlan", "strategy_plan"):
        if key in existing_document or key in document:
            document[key] = _preserve_locked_items(existing_document.get(key), document.get(key))
    return document
