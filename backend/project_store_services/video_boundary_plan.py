# -*- coding: utf-8 -*-
"""Derive a video group's boundary and input mode from the formal director plan."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .storyboard_allocation import director_shots_hash
from .work_chain_context import work_chain_stage_node


def _active_preceding_clip(project_id: str, episode_id: str, chain_id: str, group_id: str) -> dict[str, Any]:
    from .archive_transfers import _episode_video_plan

    clips = _episode_video_plan(project_id, episode_id)["clips"]
    clip = next((row for row in clips
                 if row.get("workChainId") == chain_id and row.get("shotGroupId") == group_id
                 and row.get("kind") == "work_chain"), None)
    if not clip:
        raise ValueError("上一段实际视频尚未生成或未选定可用版本，不能准备无切镜直续")
    return clip


def work_chain_video_boundary_plan(
    workflow: dict[str, Any], node: dict[str, Any],
    *, project_id: str = "", episode_id: str = "",
) -> dict[str, Any]:
    director = work_chain_stage_node(workflow, node, "director.board")
    director_data = (director or {}).get("data") or {}
    video_data = node.get("data") or {}
    shots = director_data.get("directorPlanShots") or []
    allocation = director_data.get("storyboardAllocation") or {}
    shot_nos = video_data.get("shotNos") or []
    group_id = str(video_data.get("shotGroupId") or "")
    if not isinstance(shots, list) or not isinstance(shot_nos, list) or not shot_nos:
        raise ValueError("视频任务缺少正式分镜或镜头分配")
    if allocation.get("directorPlanHash") != director_shots_hash(shots):
        raise ValueError("分镜脚本已变化，请重新保存分镜分配")
    group = next((row for row in allocation.get("groups") or []
                  if isinstance(row, dict) and row.get("id") == group_id), None)
    if not group or group.get("shotNos") != shot_nos:
        raise ValueError("视频任务与分镜镜头分配不一致")
    first_no = shot_nos[0]
    if any(not isinstance(number, int) or number < 1 or number > len(shots) for number in shot_nos):
        raise ValueError("视频任务的镜头编号无效")
    first = shots[first_no - 1]
    kind = str(first.get("entryBoundaryKind") or "")
    audio_kind = str(first.get("audioBoundaryKind") or "")
    if kind not in {"direct_continuation", "spatial_cut", "ordinary_cut", "time_space_jump"}:
        raise ValueError("视频任务的画面接续类型无效，请修正分镜脚本")
    if audio_kind not in {"continuous_ambience", "dialogue_overlap", "hard_cut", "intentional_silence"}:
        raise ValueError("视频任务的声音交接类型无效，请修正分镜脚本")
    if kind == "direct_continuation" and len(shot_nos) != 1:
        raise ValueError("无切镜直续必须单镜成组；请在分镜阶段调整分组或自然切点")
    previous = shots[first_no - 2] if first_no > 1 else {}
    previous_boundary_hash = ""
    previous_work_chain_id = ""
    previous_group_id = ""
    current_groups = allocation.get("groups") or []
    current_group_index = next((index for index, row in enumerate(current_groups)
                                if isinstance(row, dict) and row.get("id") == group_id), -1)
    if current_group_index > 0:
        previous_group_id = str(current_groups[current_group_index - 1].get("id") or "")
    if first_no == 1 and project_id and episode_id:
        from .canvas_store_queries import read_previous_director_plan_boundary_v4
        chain_id = str(node.get("workChainId") or video_data.get("workChainId") or "")
        boundary = read_previous_director_plan_boundary_v4(project_id, episode_id, chain_id)
        if boundary.get("status") == "available":
            previous = boundary["lastShot"]
            previous_boundary_hash = director_shots_hash([boundary["lastShot"]])
            previous_work_chain_id = str(boundary.get("workChainId") or "")
            if kind == "direct_continuation":
                from .canvas_store_queries import read_canvas_card_record_v4
                previous_director = read_canvas_card_record_v4(
                    project_id, episode_id, str(boundary.get("nodeId") or ""), detail="full",
                )
                previous_groups = ((previous_director.get("data") or {}).get("storyboardAllocation") or {}).get("groups") or []
                previous_group_id = str(previous_groups[-1].get("id") or "") if previous_groups else ""
        elif kind == "direct_continuation":
            raise ValueError("无切镜直续缺少紧邻上一工作链的正式末镜，无法准备真实视频末帧")
    if kind == "direct_continuation" and project_id and not previous_group_id:
        raise ValueError("无切镜直续缺少紧邻上一段的正式视频组")
    previous_video_version_id = ""
    previous_video_file_signature: dict[str, int] = {}
    if kind == "direct_continuation" and project_id and episode_id:
        preceding = _active_preceding_clip(
            project_id, episode_id, previous_work_chain_id or str(node.get("workChainId") or video_data.get("workChainId") or ""),
            previous_group_id,
        )
        stat = Path(preceding["path"]).stat()
        previous_video_version_id = str(preceding.get("versionId") or "")
        previous_video_file_signature = {"size": stat.st_size, "mtimeNs": stat.st_mtime_ns}
    last_no = shot_nos[-1]
    following_start_frame = (
        str(shots[last_no].get("storyboardFrame") or "") if last_no < len(shots) else ""
    )
    group_dependency_hash = director_shots_hash([{
        "previousShot": previous,
        "groupShots": [shots[number - 1] for number in shot_nos],
        "followingStartFrame": following_start_frame,
    }])
    return {
        "boundaryKind": kind,
        "audioBoundaryKind": audio_kind,
        "previousEndState": str(previous.get("endState") or ""),
        "previousBoundaryHash": previous_boundary_hash,
        "previousWorkChainId": previous_work_chain_id,
        "previousShotGroupId": previous_group_id,
        "previousVideoVersionId": previous_video_version_id,
        "previousVideoFileSignature": previous_video_file_signature,
        "currentStartFrame": str(first.get("storyboardFrame") or ""),
        "currentEndState": str(first.get("endState") or ""),
        "sourceDirectorNodeId": str((director or {}).get("id") or ""),
        "sourceGroupDependencyHash": group_dependency_hash,
        "shotGroupId": group_id,
        "shotNos": list(shot_nos),
        "mode": "native_keyframe" if kind == "direct_continuation" else "storyboard_reference",
        "requiredSlots": ["first_frame", "last_frame"] if kind == "direct_continuation" else ["storyboard_image"],
    }


def validate_direct_continuation_first_frame(
    project_id: str, episode_id: str, workflow: dict[str, Any],
    node: dict[str, Any], boundary_plan: dict[str, Any],
    input_links: list[dict[str, Any]],
) -> None:
    """A first-frame link must be an extracted tail of the active preceding clip."""
    if boundary_plan.get("boundaryKind") != "direct_continuation":
        return
    previous_chain_id = str(boundary_plan.get("previousWorkChainId") or
                            node.get("workChainId") or (node.get("data") or {}).get("workChainId") or "")
    previous_group_id = str(boundary_plan.get("previousShotGroupId") or "")
    preceding = _active_preceding_clip(project_id, episode_id, previous_chain_id, previous_group_id)
    if (boundary_plan.get("previousVideoVersionId") != str(preceding.get("versionId") or "")
            or boundary_plan.get("previousVideoFileSignature") != {
                "size": Path(preceding["path"]).stat().st_size,
                "mtimeNs": Path(preceding["path"]).stat().st_mtime_ns,
            }):
        raise ValueError("上一段视频版本或文件已变化，请重新准备视频提示词")
    first_links = [row for row in input_links if isinstance(row, dict)
                   and str(row.get("slot") or row.get("targetSlot") or "") == "frame_reference"
                   and row.get("frameRole", "first_frame") == "first_frame"
                   and row.get("enabled") is not False]
    if len(first_links) != 1:
        raise ValueError("无切镜直续须绑定唯一的上一段实际末帧")
    link = first_links[0]
    source_node_id = str(link.get("sourceNodeId") or "")
    source_node = next((row for row in workflow.get("nodes") or []
                        if row.get("id") == source_node_id), None)
    if not source_node and source_node_id:
        from .canvas_store_queries import read_canvas_card_record_v4
        source_node = read_canvas_card_record_v4(project_id, episode_id, source_node_id, detail="full")
    source_data = (source_node or {}).get("data") or {}
    media = source_data.get("media") or source_data.get("storage") or link.get("media") or {}
    if not isinstance(media, dict) or not isinstance(media.get("frameOrigin"), dict):
        raise ValueError("原生首帧缺少视频截帧来源；请从上一段当前视频版本提取真实末帧")
    from .video_clips import validated_frame_origin
    try:
        origin = validated_frame_origin(media)
    except (OSError, ValueError) as exc:
        raise ValueError("原生首帧的截帧来源无法核验；请重新从上一段视频截帧") from exc
    origin_path = str(origin.get("inputPath") or origin.get("sourcePath") or "")
    if not origin_path or str(Path(origin_path).resolve()).casefold() != str(Path(preceding["path"]).resolve()).casefold():
        raise ValueError("原生首帧不是上一段当前选用视频的末帧，请重新截帧并关联")
    if origin.get("captureKind") != "tail" or str(origin.get("sourceVersionId") or "") != str(preceding.get("versionId") or ""):
        raise ValueError("原生首帧需要从上一段当前选用版本重新提取实际末帧")
    video_stat = Path(preceding["path"]).stat()
    if origin.get("sourceFileSignature") != {"size": video_stat.st_size, "mtimeNs": video_stat.st_mtime_ns}:
        raise ValueError("上一段视频文件已变化，请重新提取实际末帧")
    from .video_clips import _resolve_project_media_path

    image_stat = _resolve_project_media_path(project_id, media).stat()
    if origin.get("imageFileSignature") != {"size": image_stat.st_size, "mtimeNs": image_stat.st_mtime_ns}:
        raise ValueError("原生首帧文件已变化，请重新提取实际末帧")
