# -*- coding: utf-8 -*-
"""视频生成使用的工作链导演稿与故事板解释上下文。"""
from __future__ import annotations

import copy
from .generation_input_context import (
    _generation_user_instruction,
    _workflow_node_by_id,
    _workflow_node_data_dict,
)
from .generation_reference_validation import (
    _active_reference_node_ids,
)
from .planning_contract import (
    _workflow_clean_seconds,
    _workflow_timing_number,
)
from .planning_workflow_inputs import (
    _normalize_multiline_prompt_text,
)
from .quality_gate import workflow_node_quality_block_message
from .video_task_card_prompts import (
    _director_plan_shot_rows_from_structured,
)
from .video_task_card_references import (
    VideoTaskCardReferences,
    _video_task_card_storyboard_version_from_node,
)
from .work_chain_context import (
    card_text,
    work_chain_stage_node,
)
from typing import (
    Any,
)


from .prompt_asset_context import (
    _video_task_card_asset_name_map_from_inputs,
    _video_task_card_asset_voice_style_map,
    _video_task_card_voice_context,
)


def _video_task_card_text_value(value: Any) -> str:
    """Lossless text extraction for video task-card model context."""
    if value is None:
        return ""
    if isinstance(value, str):
        return _normalize_multiline_prompt_text(value)
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        rows = [
            _video_task_card_text_value(item)
            for item in value
        ]
        return _normalize_multiline_prompt_text("；".join(row for row in rows if row))
    if isinstance(value, dict):
        priority_keys = (
            "cinematicStoryText",
            "sourceFactText",
            "sourceText",
            "content",
            "summary",
            "description",
            "storyboardImagePrompt",
            "prompt",
            "screenplay",
            "dialogue",
            "visibleAction",
            "cameraMotion",
            "temporalContinuity",
        )
        rows: list[str] = []
        for key in priority_keys:
            text = _video_task_card_text_value(value.get(key))
            if text and text not in rows:
                rows.append(text)
        if not rows:
            for key, item in value.items():
                text = _video_task_card_text_value(item)
                if text:
                    rows.append(f"{key}:{text}")
        return _normalize_multiline_prompt_text("；".join(rows))
    return _normalize_multiline_prompt_text(str(value))


def _video_task_card_context_payload(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
    _input_snapshot: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    director_node = work_chain_stage_node(workflow, node, "director.board")
    director_data = _workflow_node_data_dict(director_node)
    try:
        storyboard_node_ids = _active_reference_node_ids(
            project_id,
            episode_id,
            workflow,
            str(node.get("id") or ""),
        )
    except Exception:
        storyboard_node_ids = []
    storyboard_node: dict[str, Any] | None = None
    for storyboard_node_id in storyboard_node_ids:
        candidate = _workflow_node_by_id(workflow, storyboard_node_id)
        if candidate:
            storyboard_node = candidate
            break
    storyboard_contract = _video_task_card_storyboard_interpretation_contract(
        project_id,
        episode_id,
        storyboard_node,
    )
    director_task_card = (
        director_data.get("directorTaskCard")
        if isinstance(director_data.get("directorTaskCard"), dict)
        else {}
    )
    director_plan_text = card_text(director_data, "directorPlan")
    director_plan_shots = copy.deepcopy(
        director_data.get("directorPlanShots")
        if isinstance(director_data.get("directorPlanShots"), list)
        else []
    )
    node_data = _workflow_node_data_dict(node)
    assigned_shot_nos = node_data.get("shotNos") if isinstance(node_data.get("shotNos"), list) else []
    if not assigned_shot_nos:
        raise ValueError("当前视频任务尚未分配导演镜头，请先在分镜脚本保存分镜分配")
    continuity_instruction = ""
    from .storyboard_allocation import director_shots_hash
    allocation = director_data.get("storyboardAllocation") if isinstance(director_data.get("storyboardAllocation"), dict) else {}
    if allocation.get("directorPlanHash") != director_shots_hash(director_plan_shots):
        raise ValueError("分镜脚本已变化，请先重新保存分镜分配")
    group_id = str(node_data.get("shotGroupId") or "")
    group = next(
        (row for row in allocation.get("groups") or [] if isinstance(row, dict) and row.get("id") == group_id),
        None,
    )
    if not group_id or not group or group.get("shotNos") != assigned_shot_nos:
        raise ValueError("视频任务与分镜脚本的镜头分配不一致，请重新保存分镜分配")
    if any(not isinstance(value, int) or value < 1 or value > len(director_plan_shots) for value in assigned_shot_nos):
        raise ValueError("视频任务分配包含无效镜头")
    boundaries = []
    first_no, last_no = assigned_shot_nos[0], assigned_shot_nos[-1]
    if first_no > 1:
        previous = director_plan_shots[first_no - 2]
        boundaries.append(f"开场承接上一任务的可见终态：{previous.get('endState') or previous.get('storyboardFrame') or ''}")
    if last_no < len(director_plan_shots):
        following = director_plan_shots[last_no]
        boundaries.append(f"收尾衔接下一任务的开场构图与空间关系：{following.get('storyboardFrame') or ''}")
    if boundaries:
        continuity_instruction = "相邻任务连续性约束：" + "；".join(boundaries) + "。只生成当前分配镜头的动作和台词，不提前演出相邻任务内容。"
    director_plan_shots = [
        {**copy.deepcopy(director_plan_shots[number - 1]), "shotNo": index}
        for index, number in enumerate(assigned_shot_nos, start=1)
    ]
    director_speaker_roster = copy.deepcopy(
        director_data.get("speakerRoster")
        if isinstance(director_data.get("speakerRoster"), list)
        else []
    )
    from .director_plan_contract import speaker_roster_for_shots

    director_speaker_roster = speaker_roster_for_shots(director_speaker_roster, director_plan_shots)
    director_rule_id = card_text(director_data, "directorRuleId")
    context = {
        "sourceMode": "work_chain_director_plan",
        "directorPlan": director_plan_text,
        "directorPlanShots": director_plan_shots,
        "assignedShotNos": copy.deepcopy(assigned_shot_nos),
        "continuityInstruction": continuity_instruction,
        "speakerRoster": director_speaker_roster,
        "directorRuleId": director_rule_id,
        "directorTaskCard": copy.deepcopy(director_task_card),
        "storyboardInterpretationContract": storyboard_contract,
        "userInstruction": _generation_user_instruction(payload),
    }
    from .video_boundary_plan import work_chain_video_boundary_plan
    context["boundaryPlan"] = work_chain_video_boundary_plan(
        workflow, node, project_id=project_id, episode_id=episode_id,
    )
    return context


def _assert_storyboard_image_reference_quality(
    project_id: str,
    episode_id: str,
    storyboard_node: dict[str, Any] | None,
) -> None:
    if not isinstance(storyboard_node, dict):
        return
    selected = _video_task_card_storyboard_version_from_node(
        project_id, episode_id, storyboard_node,
    )
    if not isinstance(selected, dict):
        return
    issue = workflow_node_quality_block_message(storyboard_node, version=selected)
    if issue:
        raise ValueError(f"当前分镜图与镜头起始画面冲突：{issue} 请先修复分镜图或明确豁免。")


def _validate_video_task_card_context(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
    context: dict[str, Any],
) -> None:
    director_plan_shots = _director_plan_shot_rows_from_structured(
        context.get("directorPlanShots"),
    )
    if not director_plan_shots:
        raise ValueError("当前分镜脚本缺少镜头，请重新生成或保存修改")


def _video_task_card_storyboard_interpretation_contract(
    project_id: str,
    episode_id: str,
    storyboard_node: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the private legend used to interpret a generated storyboard sheet."""
    selected = _video_task_card_storyboard_version_from_node(
        project_id,
        episode_id,
        storyboard_node,
    )
    if not isinstance(selected, dict):
        return {}
    payload = selected.get("payload") if isinstance(selected.get("payload"), dict) else {}
    panels = payload.get("panels") if isinstance(payload.get("panels"), list) else []
    shot_order: list[dict[str, Any]] = []
    timing_rows: list[dict[str, Any]] = []
    running = 0.0
    for index, panel in enumerate(panels, start=1):
        if not isinstance(panel, dict):
            continue
        shot_label = str(panel.get("shotLabel") or panel.get("shot_label") or f"Shot {index:02d}").strip()
        duration = _workflow_timing_number(
            panel.get("durationSeconds") or panel.get("duration_seconds") or panel.get("duration")
        )
        start_second = _workflow_timing_number(panel.get("startSecond") or panel.get("start_second"))
        end_second = _workflow_timing_number(panel.get("endSecond") or panel.get("end_second"))
        if start_second is None and duration and duration > 0:
            start_second = running
        if end_second is None and start_second is not None and duration and duration > 0:
            end_second = start_second + duration
        if start_second is not None and end_second is not None and end_second > start_second:
            duration = end_second - start_second
            running = end_second
            timing_rows.append(
                {
                    "shotLabel": shot_label,
                    "durationSeconds": _workflow_clean_seconds(float(duration)),
                    "startSecond": _workflow_clean_seconds(float(start_second)),
                    "endSecond": _workflow_clean_seconds(float(end_second)),
                }
            )
        row = {
            "shotLabel": shot_label,
            "shotId": str(panel.get("id") or panel.get("shotId") or "").strip(),
            "title": _video_task_card_text_value(panel.get("title")),
            "visibleAction": _video_task_card_text_value(
                panel.get("visibleAction") or panel.get("visualAction"),
            ),
        }
        if timing_rows and len(timing_rows) == len(shot_order) + 1:
            row.update(copy.deepcopy(timing_rows[-1]))
        shot_order.append(row)
    manifest = payload.get("referenceManifest") if isinstance(payload.get("referenceManifest"), list) else []
    visual_counts = {"R": 0, "B": 0, "S": 0, "P": 0, "V": 0}
    asset_bindings: list[dict[str, Any]] = []
    for row in manifest:
        if not isinstance(row, dict):
            continue
        asset_type = str(row.get("assetType") or row.get("asset_type") or "").strip().lower()
        prefix = (
            "R"
            if "character" in asset_type
            else "B"
            if "creature" in asset_type
            else "S"
            if "scene" in asset_type
            else "P"
            if "prop" in asset_type
            else "V"
            if "style" in asset_type or "visual" in asset_type
            else ""
        )
        visual_id = str(row.get("visualId") or row.get("visual_id") or "").strip().upper()
        if not visual_id and prefix:
            visual_counts[prefix] += 1
            visual_id = f"{prefix}{visual_counts[prefix]:02d}"
        elif visual_id[:1] in visual_counts:
            try:
                visual_counts[visual_id[:1]] = max(visual_counts[visual_id[:1]], int(visual_id[1:]))
            except (TypeError, ValueError):
                pass
        if not visual_id:
            continue
        asset_bindings.append(
            {
                "visualId": visual_id,
                "assetType": asset_type,
                "displayName": str(row.get("displayName") or row.get("label") or "").strip(),
                "assetId": str(row.get("assetId") or "").strip(),
                "mediaId": str(row.get("mediaId") or "").strip(),
            }
        )
    visual_presentation = {
        "rewritten": False,
        "source": "director_plan",
    }
    duration_seconds = _workflow_clean_seconds(float(timing_rows[-1].get("endSecond") or 0)) if timing_rows else None
    shot_timing_plan = (
        {
            "schemaVersion": 1,
            "durationSeconds": duration_seconds,
            "shotCount": len(timing_rows),
            "shots": copy.deepcopy(timing_rows),
            "source": "work_chain_planning",
            "scope": "work_chain",
        }
        if duration_seconds and len(timing_rows) == len(shot_order)
        else {}
    )
    result = {
        "storyboardVersionId": str(selected.get("id") or "").strip(),
        "storyboardNodeId": str((storyboard_node or {}).get("id") or "").strip(),
        "panelCount": int(payload.get("panelCount") or len(shot_order) or 0),
        "shotOrder": shot_order,
        "durationSeconds": duration_seconds,
        "shotTimingPlan": shot_timing_plan,
        "assetBindings": asset_bindings,
        "symbolLegend": {
            "storyboardSheet": "整张故事版分镜图是一张参考图，内部包含多个编号 Shot；它不是单一镜头图。",
            "Shot NN": "主要取景框及视频片段的镜头顺序",
            "RNN": "角色身份与角色在 Shot/俯视调度图中的位置",
            "BNN": "生物身份与生物在 Shot/俯视调度图中的位置",
            "SNN": "场景身份或场景区域",
            "PNN": "关键道具身份、位置、归属或状态",
            "VNN": "风格或用户绑定参考图，不是角色、生物、场景、道具或镜头顺序",
            "CNN": "摄影机机位或轴线侧，不是角色、生物或道具",
            "solidArrow": "角色、生物或道具的行动方向",
            "dashedArrow": "机位路径、视线、轴线或辅助关系，以图中上下文为准",
        },
        "containerRules": [
            "一张故事版分镜图内部可以包含多个主要 Shot；视频提示词中的同编号 Shot 时间段与图内同编号 Shot 一一对应。",
            "整张故事板是视觉规划容器，不是视频片段首帧。",
            "只把主要 Shot 取景框按顺序转为成片；边框、编号、文字、图例、缩略图、俯视图和箭头不进入成片。",
            "角色、生物、场景、道具参考图只约束外观和空间连续性；风格或用户绑定参考图只约束被明确指定的视觉参考用途；它们都不代表独立镜头，也不参与 Shot 顺序编号。",
            "若故事板包含俯视调度图、箭头或其他辅助图示，只把它们理解为空间位置、朝向、动线、机位侧、轴线和连续性参考；不得把它们理解为新增镜头或真实环境细节。",
            "参考图上传序号与故事板内部 R/B/S/P/V 视觉编号是两套编号，不得混用。",
        ],
        "visualPresentation": visual_presentation,
    }
    stored_contract = (
        payload.get("storyboardInterpretationContract")
        if isinstance(payload.get("storyboardInterpretationContract"), dict)
        else payload.get("storyboard_interpretation_contract")
        if isinstance(payload.get("storyboard_interpretation_contract"), dict)
        else {}
    )
    stored_shot_order = (
        stored_contract.get("shotOrder")
        if isinstance(stored_contract.get("shotOrder"), list)
        else stored_contract.get("shot_order")
        if isinstance(stored_contract.get("shot_order"), list)
        else []
    )
    if stored_shot_order:
        merged = {
            **copy.deepcopy(result),
            **copy.deepcopy(stored_contract),
            "storyboardVersionId": str(
                stored_contract.get("storyboardVersionId")
                or stored_contract.get("storyboard_version_id")
                or selected.get("id")
                or ""
            ).strip(),
            "storyboardNodeId": str(
                stored_contract.get("storyboardNodeId")
                or stored_contract.get("storyboard_node_id")
                or (storyboard_node or {}).get("id")
                or ""
            ).strip(),
            "shotOrder": copy.deepcopy(stored_shot_order),
        }
        return merged
    return result




def _prepare_video_task_card_context(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
    payload: dict[str, Any],
    references: VideoTaskCardReferences,
) -> dict[str, Any]:
    input_snapshot = references.input_snapshot
    asset_names = references.asset_names
    context = _video_task_card_context_payload(
        project_id,
        episode_id,
        workflow,
        node,
        input_snapshot,
        payload,
    )
    excluded = {str(row["assetId"]): str(row["name"]) for row in input_snapshot.get("excludedAssets") or []}
    conflicts: list[str] = []
    conflicting_assets: set[str] = set()
    for shot in context.get("directorPlanShots") or []:
        used = {str(asset_id) for ids in (shot.get("assets") or {}).values() for asset_id in ids}
        used.update(str(event.get("speakerId") or "").removeprefix("asset:")
                    for event in shot.get("soundEvents") or [] if event.get("kind") == "voice")
        conflict = used.intersection(excluded)
        if conflict:
            conflicts.append(str(shot.get("shotNo")))
            conflicting_assets.update(conflict)
    if conflicts:
        names = "、".join(excluded[key] for key in sorted(conflicting_assets))
        raise ValueError("当前分镜的镜头 " + "、".join(conflicts) + " 仍要求已禁用资产出场（" + names +
                         "）。请先修改上游分镜或明确恢复资产使用；不能仅去除引用标记后继续生成。")
    # Disabled identities cannot return through the saved plan's voice context.
    voice_inputs = input_snapshot
    context["assetNameMap"] = copy.deepcopy(asset_names)
    context["voiceAssetNameMap"] = _video_task_card_asset_name_map_from_inputs(
        voice_inputs, project_id, asset_name_map=asset_names,
    )
    context["referenceManifest"] = copy.deepcopy(references.record_patch.get("referenceManifest") or [])
    context["hasStoryboardReference"] = bool(references.reference_thumbnails)
    context["assetVoiceDesign"] = _video_task_card_asset_voice_style_map(
        project_id,
        context.get("directorPlanShots") if isinstance(context.get("directorPlanShots"), list) else [],
        context["voiceAssetNameMap"],
        input_snapshot=voice_inputs,
    )
    context["voiceInputSnapshot"] = voice_inputs
    context["taskId"] = str(payload.get("taskId") or "").strip()
    context = _video_task_card_voice_context(context)
    _validate_video_task_card_context(
        project_id,
        episode_id,
        workflow,
        node,
        context,
    )
    return context
