# -*- coding: utf-8 -*-
"""分镜面板文本、布局、时长与素材提示词内容。"""
from __future__ import annotations

import re
from .director_plan_contract import (
    _normalize_multiline_text,
)
from .reference_utils import asset_refs_has_value as _asset_refs_has_value
from .planning_contract import (
    _segment_asset_refs,
    _workflow_clean_seconds,
    _workflow_timing_number,
)
from .production_specs import (
    build_storyboard_render_spec,
)
from .storyboard_templates import (
    storyboard_template_layout_spec,
)
from .work_chain_context import (
    card_text,
)
from typing import (
    Any,
)


def _storyboard_target_frame_composition_note(target_video_spec: dict[str, Any]) -> str:
    orientation = str(target_video_spec.get("orientation") or "landscape").strip().lower()
    if orientation == "portrait":
        return "竖屏镜头用上下层级、前后景和纵向空间组织关系，并为纵向动作保留完整运动余量。"
    if orientation == "square":
        return "方形镜头用前后景、中心与四角关系组织主体，并在完整方形安全区内保留动作余量。"
    return "横屏镜头用左右关系、纵深和前后景组织主体，并为横向运动、视线和出入画保留余量。"


def _storyboard_template_layout_block(
    template_id: str,
    storyboard_render_spec: dict[str, Any] | None = None,
) -> str:
    spec = storyboard_template_layout_spec(template_id)
    render_spec = (
        storyboard_render_spec
        if isinstance(storyboard_render_spec, dict)
        else build_storyboard_render_spec({}, spec)
    )
    sheet_spec = render_spec.get("sheet") if isinstance(render_spec.get("sheet"), dict) else {}
    target_video_spec = (
        render_spec.get("targetVideo")
        if isinstance(render_spec.get("targetVideo"), dict)
        else {}
    )
    shot_frame_spec = (
        render_spec.get("shotFrame")
        if isinstance(render_spec.get("shotFrame"), dict)
        else {}
    )
    language = target_video_spec.get("language") if isinstance(target_video_spec.get("language"), dict) else {}
    text_annotation_note = "画面文字与版式标注：镜头画面内的可见文字按分镜脚本的内容与时机呈现；版式层的编号、短标签、箭头和图示符号由所选版式决定。工作页只呈现与镜头画面和版式有关的信息。"
    frame_note = (
        f"主要镜头画格：每个有效取景框保持项目"
        f"{shot_frame_spec.get('orientationLabel') or target_video_spec.get('orientationLabel') or '横屏'}方向，"
        "不要求工作页或单格逐像素等于视频宽高比；关键人物、手部和道具保持在安全画框内。"
        "素材原有的横竖比例不强制添加遮幅或黑边；所有版式元素不得挤压主要镜头画格。"
    )
    return "\n".join(
        row
        for row in (
            f"分镜图工作页参考画布：{sheet_spec.get('orientationLabel') or '横屏'} "
            f"{sheet_spec.get('aspectRatio') or spec.get('sheetAspectRatio') or spec.get('aspectRatio') or '16:9'}；"
            "这是整页构图的参考比例；实际输出宽高以图片模型返回的原图为准。",
            f"视频片段画幅：{target_video_spec.get('orientationLabel') or '横屏'} "
            f"{target_video_spec.get('aspectRatio') or '16:9'}；该比例来自项目配置，版式和参考图不得覆盖。",
            (
                f"项目语言：{language.get('label') or '简体中文'}"
                f"（{language.get('code') or 'zh-CN'}）。"
                f"{language.get('instruction') or '所有模型生成的画面短标签使用简体中文，禁止无原文依据的中英混写。'}"
            ),
            text_annotation_note,
            frame_note,
            _storyboard_target_frame_composition_note(target_video_spec),
        )
        if row
    )


def _xml_text(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _panel_value(panel: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = panel.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _duration_seconds_value(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            seconds = int(round(float(value)))
        else:
            match = re.search(r"\d+(?:\.\d+)?", str(value).strip())
            if not match:
                return None
            seconds = int(round(float(match.group(0))))
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _panel_duration_seconds(panel: dict[str, Any]) -> int | None:
    for key in ("durationSeconds", "duration_seconds", "duration", "seconds", "durationSec"):
        seconds = _duration_seconds_value(panel.get(key))
        if seconds:
            return seconds
    return None


def _storyboard_panels_duration_seconds(panels: Any) -> int | None:
    if not isinstance(panels, list):
        return None
    durations = [
        duration
        for item in panels
        if isinstance(item, dict)
        for duration in [_panel_duration_seconds(item)]
        if duration
    ]
    if not durations:
        return None
    return sum(durations)


def _storyboard_payload_duration_seconds(payload: dict[str, Any], workflow: dict[str, Any]) -> int | None:
    resolved_config = payload.get("resolvedConfig") if isinstance(payload.get("resolvedConfig"), dict) else {}
    for source in (resolved_config, payload):
        for key in ("durationSeconds", "duration_seconds", "duration"):
            seconds = _duration_seconds_value(source.get(key))
            if seconds:
                return seconds
    return _storyboard_panels_duration_seconds(payload.get("panels"))


def _storyboard_panels_shot_timing_plan(panels: Any) -> dict[str, Any]:
    if not isinstance(panels, list) or not panels:
        return {}
    rows: list[dict[str, Any]] = []
    running = 0
    for index, panel in enumerate(panels, start=1):
        if not isinstance(panel, dict):
            continue
        duration = _workflow_timing_number(panel.get("durationSeconds") or panel.get("duration_seconds") or panel.get("duration"))
        start_second = _workflow_timing_number(
            panel.get("startSecond") if "startSecond" in panel else panel.get("start_second")
        )
        end_second = _workflow_timing_number(
            panel.get("endSecond") if "endSecond" in panel else panel.get("end_second")
        )
        if start_second is None and duration:
            start_second = running
        if end_second is None and start_second is not None and duration:
            end_second = start_second + duration
        if duration is None and start_second is not None and end_second is not None and end_second > start_second:
            duration = end_second - start_second
        if duration is None or start_second is None or end_second is None or end_second <= start_second:
            return {}
        running = end_second
        rows.append(
            {
                "shotLabel": str(panel.get("shotLabel") or panel.get("shot_label") or f"Shot {index:02d}").strip(),
                "durationSeconds": _workflow_clean_seconds(float(duration)),
                "startSecond": _workflow_clean_seconds(float(start_second)),
                "endSecond": _workflow_clean_seconds(float(end_second)),
            }
        )
    if not rows or len(rows) != len([panel for panel in panels if isinstance(panel, dict)]):
        return {}
    return {
        "schemaVersion": 1,
        "durationSeconds": rows[-1]["endSecond"],
        "shotCount": len(rows),
        "shots": rows,
        "source": "work_chain_planning",
        "scope": "work_chain",
    }


def _workflow_video_task_card_duration_seconds(data: dict[str, Any] | None) -> int | float | None:
    if not isinstance(data, dict):
        return None
    task_card = data.get("videoTaskCard") if isinstance(data.get("videoTaskCard"), dict) else {}
    for source in (data, task_card):
        for key in ("durationSeconds",):
            duration_seconds = _duration_seconds_value(source.get(key))
            if duration_seconds:
                return duration_seconds
    return None


def _panel_title(panel: dict[str, Any], index: int) -> str:
    return _panel_value(panel, "title", "shot", "name", "id", "coverageRole") or f"分镜 {index + 1}"


def _panel_asset_ref_text(panel: dict[str, Any]) -> str:
    refs = _segment_asset_refs(panel)
    if not _asset_refs_has_value(refs):
        return ""

    def item_text(value: Any, *, include_position: bool = False) -> str:
        if isinstance(value, dict):
            label = (
                str(value.get("rootAssetId") or value.get("assetId") or value.get("asset_id") or value.get("id") or "")
                .strip()
            )
            details: list[str] = []
            if include_position:
                for key in ("position", "screenPosition", "screen_position", "placement", "staging", "pose"):
                    text = str(value.get(key) or "").strip()
                    if text:
                        details.append(f"站位：{text}")
                        break
            return f"{label}（{'，'.join(details)}）" if label and details else label
        text = str(value or "").strip()
        return text

    def list_text(value: Any, *, include_position: bool = False) -> str:
        if isinstance(value, list):
            values = [item_text(item, include_position=include_position) for item in value]
        else:
            values = [item_text(value, include_position=include_position)]
        return "、".join(item for item in values if item)

    parts: list[str] = []
    characters = list_text(refs.get("characters"), include_position=True)
    creatures = list_text(refs.get("creatures"), include_position=True)
    scenes = list_text(refs.get("scenes"))
    props = list_text(refs.get("props"))
    if characters:
        parts.append(f"角色：{characters}")
    if creatures:
        parts.append(f"生物：{creatures}")
    if scenes:
        parts.append(f"场景：{scenes}")
    if props:
        parts.append(f"道具：{props}")
    return "；".join(parts)


def _panel_timing_text(panel: dict[str, Any]) -> str:
    duration = _workflow_timing_number(panel.get("durationSeconds") or panel.get("duration_seconds") or panel.get("duration"))
    start_second = _workflow_timing_number(
        panel.get("startSecond") if "startSecond" in panel else panel.get("start_second")
    )
    end_second = _workflow_timing_number(
        panel.get("endSecond") if "endSecond" in panel else panel.get("end_second")
    )
    if start_second is not None and end_second is not None and end_second > start_second:
        return f"{_workflow_clean_seconds(float(start_second)):g}-{_workflow_clean_seconds(float(end_second)):g}秒"
    if duration:
        return f"约{_workflow_clean_seconds(float(duration)):g}秒"
    return ""


def _panel_prompt(panel: dict[str, Any], index: int) -> str:
    title = _panel_title(panel, index)
    action = _panel_value(
        panel,
        "storyboardFrame",
        "storyboard_frame",
    )
    reference_plan = panel.get("referencePlan") if isinstance(panel.get("referencePlan"), dict) else {}
    visual_anchor = str(reference_plan.get("visualAnchor") or reference_plan.get("visual_anchor") or "").strip()
    parts = [title]
    if action:
        parts.append(f"分镜画面：{action}")
    if visual_anchor:
        parts.append(f"参考锚点：{visual_anchor}")
    asset_ref_text = _panel_asset_ref_text(panel)
    if asset_ref_text:
        parts.append(f"资产引用：{asset_ref_text}")
    timing_text = _panel_timing_text(panel)
    if timing_text:
        parts.append(f"节奏时长：{timing_text}")
    return "；".join(parts)


def _panel_action_text(panel: dict[str, Any]) -> str:
    return _panel_value(
        panel,
        "storyboardFrame",
        "storyboard_frame",
    )


def _storyboard_prompt_text_from_data(data: dict[str, Any]) -> str:
    return _normalize_multiline_text(card_text(data, "cinematicStoryText"))


def _storyboard_source_fact_text_from_data(data: dict[str, Any]) -> str:
    return _normalize_multiline_text(card_text(data, "sourceFactText"))


def _workflow_storyboard_asset_refs_text(project_id: str, input_snapshot: dict[str, Any]) -> str:
    """Render only identities resolved from this work chain's current asset links."""
    from .prompt_asset_context import resolve_prompt_assets

    labels = {"characters": "角色", "creatures": "生物", "scenes": "场景", "props": "道具"}
    grouped: dict[str, list[str]] = {key: [] for key in labels}
    for asset in resolve_prompt_assets(project_id, input_snapshot).values():
        asset_type = asset["assetType"]
        if not asset["exists"] or asset_type not in grouped:
            continue
        text = asset["displayName"]
        if text not in grouped[asset_type]:
            grouped[asset_type].append(text)
    return "\n".join(f"{labels[key]}：" + "、".join(values) for key, values in grouped.items() if values)


def _workflow_storyboard_speaker_identity_map(project_id: str, input_snapshot: dict[str, Any]) -> list[dict[str, str]]:
    from .prompt_asset_context import resolve_prompt_assets

    return [
        {"name": asset["displayName"], "speakerId": f"asset:{identity}"}
        for identity, asset in resolve_prompt_assets(project_id, input_snapshot).items()
        if asset["exists"] and asset["assetType"] in {"characters", "creatures"}
    ]


def _compact_multiline_text(value: Any, limit: int = 4000) -> str:
    """Lossy multiline preview helper.

    Use only for UI summaries, notes, diagnostics, and explicit preview fields.
    Do not use for canonical screenplay/source/prompt data or provider/model
    payload text that affects generation.
    """
    text = _normalize_multiline_text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
