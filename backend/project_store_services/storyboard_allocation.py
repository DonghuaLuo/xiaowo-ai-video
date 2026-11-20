# -*- coding: utf-8 -*-
"""Allocate one director plan to ordered storyboard/video branches."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import traceback
import uuid
from typing import Any

from .canvas_store_database import retry_canvas_mutation_v4
from .canvas_store_mutations import replace_canvas_records_from_workflow_projection_v4
from .generation_config import (
    _video_task_card_allowed_duration_values,
    _video_task_card_target_model_context,
)
from .planning_workflow_layout import _layout_workflow_by_work_chain
from .projects import _touch_project_meta
from .planning_contract import _is_user_locked_item
from .workflow_contract import _assert_canvas_mutation_does_not_return_workflow, _workflow_mutation_event_fields
from .workflow_projection import get_canvas_workflow_projection
from .workflow_input_resolution import _link_reference_media_id, _workflow_remove_unlinked_asset_refs_from_node_data
from .storyboard_timing import (
    SPEECH_ESTIMATE_TOLERANCE_SECONDS,
    effective_rhythm, project_storyboard_timing,
    speech_seconds, validate_shot_timing,
)


def director_shots_hash(shots: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(shots, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def require_direct_continuation_previous_group(
    project_id: str, episode_id: str, work_chain_id: str,
    previous_boundary: dict[str, Any] | None = None,
) -> None:
    """Require a formal immediately preceding video group before accepting a direct join."""
    from .canvas_store_queries import read_canvas_card_record_v4, read_previous_director_plan_boundary_v4

    boundary = previous_boundary if previous_boundary is not None else read_previous_director_plan_boundary_v4(
        project_id, episode_id, work_chain_id,
    )
    if boundary.get("status") != "available" or not boundary.get("nodeId"):
        raise ValueError("首镜无切镜直续需要紧邻上一工作链的正式末镜；请改用切镜或先完成上一工作链分镜")
    try:
        previous_director = read_canvas_card_record_v4(
            project_id, episode_id, str(boundary["nodeId"]), detail="full",
        )
    except FileNotFoundError as exc:
        raise ValueError("上一工作链分镜已变化，请重新读取并调整接续类型") from exc
    previous_data = previous_director.get("data") if isinstance(previous_director.get("data"), dict) else {}
    previous_shots = previous_data.get("directorPlanShots") or []
    allocation = (previous_data.get("storyboardAllocation")
                  if isinstance(previous_data.get("storyboardAllocation"), dict) else {})
    groups = allocation.get("groups") or []
    last_group = groups[-1] if isinstance(groups, list) and groups else {}
    last_shot_nos = last_group.get("shotNos") if isinstance(last_group, dict) else None
    if (not isinstance(previous_shots, list) or not previous_shots
            or allocation.get("directorPlanHash") != director_shots_hash(previous_shots)
            or not isinstance(last_group, dict) or not last_group.get("id")
            or not isinstance(last_shot_nos, list)
            or last_shot_nos[-1:] != [len(previous_shots)]):
        raise ValueError("首镜无切镜直续需要上一工作链已完成正式视频分组；请先完成前链分配")


def _allocation_groups(raw: Any, shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("请至少保留一个分镜单元")
    shot_numbers = [int(shot.get("shotNo") or 0) for shot in shots]
    if shot_numbers != list(range(1, len(shots) + 1)):
        raise ValueError("分镜脚本镜头编号需要从 1 连续递增")
    groups: list[dict[str, Any]] = []
    assigned: list[int] = []
    used_ids: set[str] = set()
    for index, value in enumerate(raw, start=1):
        if not isinstance(value, dict):
            raise ValueError(f"第 {index} 个分配组无效")
        numbers = value.get("shotNos")
        if not isinstance(numbers, list) or not numbers:
            raise ValueError(f"第 {index} 个分配组缺少镜头")
        try:
            shot_nos = [int(number) for number in numbers]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"第 {index} 个分配组镜头编号无效") from exc
        if shot_nos != list(range(shot_nos[0], shot_nos[-1] + 1)):
            raise ValueError("同一分镜单元只能包含相邻镜头，且必须保持原顺序")
        if any(number < 1 or number > len(shots) for number in shot_nos):
            raise ValueError("分配组镜头编号超出当前分镜脚本范围")
        if any(shots[number - 1].get("groupBreakBefore") for number in shot_nos[1:]):
            raise ValueError("镜头组跨越必须另起视频段的边界，请从标记镜头开始新组")
        if (len(shot_nos) > 1
                and shots[shot_nos[0] - 1].get("entryBoundaryKind") == "direct_continuation"):
            raise ValueError("无切镜直续作为视频组首镜时必须单镜成组，请调整分组")
        group_id = str(value.get("id") or f"group_{uuid.uuid4().hex[:12]}").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", group_id) or group_id in used_ids:
            raise ValueError("分配组 ID 无效或重复")
        used_ids.add(group_id)
        assigned.extend(shot_nos)
        group = {"id": group_id, "shotNos": shot_nos, "order": index}
        reason = value.get("reason")
        if isinstance(reason, str) and reason.strip():
            group["reason"] = reason.strip()
        groups.append(group)
    if assigned != shot_numbers:
        raise ValueError("所有导演镜头必须按原顺序分配一次，不能遗漏或重复")
    return groups


def default_storyboard_groups(
    shots: list[dict[str, Any]], prior_allocation: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Reuse an unchanged manual allocation; never invent single-shot groups."""
    prior = prior_allocation.get("groups") if isinstance(prior_allocation, dict) else None
    try:
        groups = _allocation_groups(prior, shots)
        return [{"id": group["id"], "shotNos": group["shotNos"],
                 **({"reason": group["reason"]} if group.get("reason") else {})} for group in groups]
    except ValueError:
        return []


def _node_data(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data")
    return data if isinstance(data, dict) else {}


def _active_output(node: dict[str, Any]) -> bool:
    data = _node_data(node)
    return bool(data.get("activeVersionId") or data.get("activeMediaVersionId") or data.get("mediaVersionId"))


def _reset_branch_output(node: dict[str, Any]) -> None:
    data = node.setdefault("data", {})
    for key in (
        "activeVersionId", "activeMediaVersionId", "mediaVersionId", "sourceVersionId",
        "winnerVersionId", "selectionReason", "selectedAt", "variantSelection",
        "media", "qualityResult", "modelMeta",
        "workpageMedia", "storyboardInterpretationContract", "shotTimingPlan",
    ):
        data.pop(key, None)
    data["status"] = "waiting"
    data["summary"] = ""
    links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
    for link in links:
        if isinstance(link, dict):
            link["status"] = "pending_generation"
            link.pop("sourceVersionId", None)
            link.pop("mediaVersionId", None)
    if node.get("type") in {"video.storyboard", "video.keyframe"}:
        data["prompt"] = {}
        for key in ("referenceManifest", "promptBindings", "assetNameMap", "intermediatePlan", "finalVideoPrompt"):
            data.pop(key, None)
        data["videoTaskCard"] = {}
        data["referenceThumbnails"] = copy.deepcopy(links)


def _remove_deleted_node_inputs(project_id: str, nodes: list[dict[str, Any]], removed_ids: set[str]) -> None:
    """Remove material references left on cards that survive a regrouping."""
    if not removed_ids:
        return

    def usage_of_deleted_node(key: str) -> bool:
        if key in removed_ids:
            return True
        if not key.startswith("identity:"):
            return False
        try:
            identity = json.loads(key[len("identity:"):])
        except ValueError:
            return False
        return (isinstance(identity, list) and len(identity) == 2
                and isinstance(identity[1], str)
                and any(identity[1].startswith(f"node:{node_id}:") for node_id in removed_ids))

    for node in nodes:
        links = _node_data(node).get("inputLinks")
        if not isinstance(links, list):
            continue
        removed_links = [
            link for link in links if isinstance(link, dict)
            and (str(link.get("sourceNodeId") or "") in removed_ids
                 or str(link.get("targetNodeId") or "") in removed_ids)
        ]
        if removed_links and _is_user_locked_item(node):
            raise ValueError("关联卡片已由用户锁定，请先解锁，本次分镜分配未保存")

    for node in nodes:
        data = _node_data(node)
        links = data.get("inputLinks")
        if not isinstance(links, list):
            continue
        removed_links = [
            link for link in links if isinstance(link, dict)
            and (str(link.get("sourceNodeId") or "") in removed_ids
                 or str(link.get("targetNodeId") or "") in removed_ids)
        ]
        if not removed_links:
            continue
        kept_links = [link for link in links if link not in removed_links]
        data["inputLinks"] = kept_links
        removed_media_ids = {_link_reference_media_id(link) for link in removed_links}
        kept_media_ids = {_link_reference_media_id(link) for link in kept_links if isinstance(link, dict)}
        for key in ("referenceMediaIds", "assetReferenceMediaIds"):
            if isinstance(data.get(key), list):
                data[key] = [media_id for media_id in data[key]
                             if media_id not in removed_media_ids or media_id in kept_media_ids]
        for key in ("referenceDisplayRows", "referenceThumbnails", "referenceVideoThumbnails",
                    "assetThumbnails", "referenceManifest"):
            rows = data.get(key)
            if isinstance(rows, list):
                data[key] = [row for row in rows if not isinstance(row, dict)
                             or str(row.get("sourceNodeId") or "") not in removed_ids]
        usage = data.get("referenceUsage")
        if isinstance(usage, dict):
            data["referenceUsage"] = {
                key: value for key, value in usage.items()
                if not usage_of_deleted_node(key)
            }
        _workflow_remove_unlinked_asset_refs_from_node_data(project_id, data, removed_links)


def _branch_for_image(workflow: dict[str, Any], image: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    node_by_id = {str(node.get("id") or ""): node for node in workflow.get("nodes", []) if isinstance(node, dict)}
    image_id = str(image.get("id") or "")
    for edge in workflow.get("edges", []):
        if not isinstance(edge, dict) or str(edge.get("source") or "") != image_id:
            continue
        video = node_by_id.get(str(edge.get("target") or ""))
        if not video or str(video.get("type") or "") not in {"video.storyboard", "video.keyframe"}:
            continue
        for result in workflow.get("nodes", []):
            if not isinstance(result, dict) or str(result.get("type") or "") != "video.result":
                continue
            if str(_node_data(result).get("resultOfNodeId") or "") == str(video.get("id") or ""):
                return video, result
    return None


def _director_branches(workflow: dict[str, Any], director: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]]:
    director_id = str(director.get("id") or "")
    chain_id = str(director.get("workChainId") or _node_data(director).get("workChainId") or "")
    node_by_id = {str(node.get("id") or ""): node for node in workflow.get("nodes", []) if isinstance(node, dict)}
    rows = []
    for image in workflow.get("nodes", []):
        if not isinstance(image, dict) or str(image.get("type") or "") != "storyboard.image":
            continue
        if str(image.get("workChainId") or _node_data(image).get("workChainId") or "") != chain_id:
            continue
        image_id = str(image.get("id") or "")
        card = node_by_id.get(str(_node_data(image).get("sourceNodeId") or ""))
        if not card or card.get("type") != "storyboard.card":
            card = next((node_by_id.get(str(edge.get("source") or "")) for edge in workflow.get("edges", [])
                         if isinstance(edge, dict) and edge.get("target") == image_id
                         and node_by_id.get(str(edge.get("source") or ""), {}).get("type") == "storyboard.card"), None)
        if not card:
            continue
        linked_to_director = any(
            isinstance(edge, dict)
            and str(edge.get("source") or "") == director_id
            and str(edge.get("target") or "") == str(card.get("id") or "")
            for edge in workflow.get("edges", [])
        )
        if not linked_to_director:
            continue
        pair = _branch_for_image(workflow, image)
        if pair:
            rows.append((card, image, *pair))
    rows.sort(key=lambda row: int(_node_data(row[0]).get("shotGroupOrder") or 0))
    return rows


def _allocation_branch_templates(
    groups: list[dict[str, Any]],
    branches: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]],
    original_branches: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]] | None = None,
    *, shots: list[dict[str, Any]] | None = None, source_shot_nos: list[int | None] | None = None,
) -> list[tuple[tuple[dict[str, Any], ...] | None, tuple[dict[str, Any], ...], bool]]:
    """Choose the same video template for preflight and the eventual allocation."""
    originals = original_branches if original_branches is not None else copy.deepcopy(branches)
    allocated = {
        str(_node_data(card).get("shotGroupId") or ""): branch
        for branch in branches for card in [branch[0]]
        if _node_data(card).get("shotGroupId")
    }
    unallocated = next((branch for branch in branches if not _node_data(branch[0]).get("shotGroupId")), None)
    choices = []
    for group in groups:
        branch = allocated.get(group["id"])
        if branch is None and unallocated is not None:
            branch, unallocated = unallocated, None
        source = branch or next(
            (row for row in originals if any(
                number in (_node_data(row[0]).get("shotNos") or []) for number in group["shotNos"]
            )), originals[0],
        )
        preserve = bool(branch and _node_data(branch[0]).get("shotNos") == group["shotNos"])
        if shots is not None and not preserve:
            # Regrouping unchanged shots keeps the choices belonging to those
            # shots, including splits and reordered/renamed groups. Never copy
            # choices merely because an old group has the same numeric index.
            if source_shot_nos is not None:
                signatures = {source_shot_nos[number - 1] for number in group["shotNos"]
                              if source_shot_nos[number - 1] is not None}
            else:
                selected = [shots[number - 1] for number in group["shotNos"]]
                signatures = {director_shots_hash([{k: v for k, v in shot.items() if k != "shotNo"}])
                              for shot in selected}
            sources = []
            covered = set()
            for original in originals:
                if source_shot_nos is not None:
                    old_signatures = set(_node_data(original[0]).get("shotNos") or [])
                else:
                    old = _node_data(original[0]).get("directorPlanShots") or []
                    old_signatures = {director_shots_hash([{k: v for k, v in shot.items() if k != "shotNo"}]) for shot in old}
                matched = signatures & old_signatures
                if matched:
                    sources.append(original)
                    covered.update(matched)
            if sources and covered == signatures:
                settings = [_branch_reference_choices(row) for row in sources]
                if any(value != settings[0] for value in settings[1:]):
                    raise ValueError("拟合并的分镜单元有不同的局部资产关联或启用选择；请保留这些分组边界，或先在原单元统一选择后重试。未写入分镜。")
                source, preserve = sources[0], True
            elif signatures and any(_branch_has_reference_choices(row) for row in originals):
                raise ValueError("分镜重排后无法确定原单元局部资产选择对应的新镜头；请保留原分组，或先明确调整原单元的资产选择后重试。未写入分镜。")
        choices.append((branch, source, preserve))
    return choices


def _remap_reference_usage_key(key: str, node_ids: dict[str, str]) -> str:
    """Remap node-backed identities without changing media versions or duties."""
    if key in node_ids:
        return node_ids[key]
    if not key.startswith("identity:"):
        return key
    try:
        identity = json.loads(key[len("identity:"):])
    except (TypeError, ValueError):
        return key
    if not isinstance(identity, list) or len(identity) != 2 or not isinstance(identity[1], str):
        return key
    for old_id, new_id in node_ids.items():
        prefix = f"node:{old_id}:"
        if identity[1].startswith(prefix):
            identity[1] = f"node:{new_id}:" + identity[1][len(prefix):]
            return "identity:" + json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return key


def _branch_reference_choices(branch: tuple[dict[str, Any], ...]) -> str:
    """Compare explicit per-consumer choices independently of branch node IDs."""
    ids = {str(node["id"]): f"branch:{index}" for index, node in enumerate(branch)}

    def canonical(value):
        if isinstance(value, dict):
            return {_remap_reference_usage_key(key, ids): canonical(item) for key, item in value.items()}
        if isinstance(value, list):
            return [canonical(item) for item in value]
        return ids.get(value, value) if isinstance(value, str) else value

    rows = []
    for node in branch:
        data = _node_data(node)
        links = [
            {key: value for key, value in link.items() if key not in {"id", "linkId", "targetNodeId", "createdAt"}}
            for link in data.get("inputLinks") or []
            if isinstance(link, dict) and str(link.get("sourceNodeId") or "") not in ids
        ]
        rows.append({"usage": canonical(data.get("referenceUsage") or {}),
                     "links": sorted(json.dumps(canonical(link), ensure_ascii=False, sort_keys=True) for link in links)})
    return json.dumps(rows, ensure_ascii=False, sort_keys=True)


def _branch_has_reference_choices(branch: tuple[dict[str, Any], ...]) -> bool:
    ids = {str(node["id"]) for node in branch}
    return any(_node_data(node).get("referenceUsage") or any(
        isinstance(link, dict) and str(link.get("sourceNodeId") or "") not in ids
        for link in _node_data(node).get("inputLinks") or []
    ) for node in branch)


def _group_duration(
    project_id: str, video: dict[str, Any], shots: list[dict[str, Any]], rhythm: float,
) -> int | float:
    """Choose a video-card default after grouping, without changing group boundaries."""
    # The speech estimator is approximate. The same narrow tolerance accepted
    # by the per-shot preflight must apply when selecting the model duration.
    total = sum(max(float(shot.get("durationSec") or 0),
                    speech_seconds(shot, rhythm) - SPEECH_ESTIMATE_TOLERANCE_SECONDS)
                for shot in shots)
    if total <= 0:
        raise ValueError("导演镜头缺少有效的参考时长")
    model = _video_task_card_target_model_context(project_id, _node_data(video), {})
    allowed = _video_task_card_allowed_duration_values(model.get("allowedDurations") or model.get("durations"))
    if allowed:
        chosen = next((duration for duration in allowed if duration + 0.005 >= total), None)
        if chosen is not None:
            return chosen
        # The storyboard still saves. Video production will report model
        # incompatibility for this card instead of forcing another grouping.
    chosen = max(1, math.ceil(total))
    return chosen


def _duration_is_allowed(
    project_id: str, video: dict[str, Any], duration: int | float,
    generation_config: dict[str, Any] | None = None,
) -> bool:
    model = _video_task_card_target_model_context(
        project_id, _node_data(video),
        {"resolvedConfig": generation_config} if isinstance(generation_config, dict) else {},
    )
    allowed = _video_task_card_allowed_duration_values(model.get("allowedDurations") or model.get("durations"))
    return bool(allowed) and any(abs(float(duration) - float(value)) <= 0.005 for value in allowed)


def assert_video_shot_allocation_current(
    project_id: str, workflow: dict[str, Any], video: dict[str, Any],
    *, duration_seconds: Any = None,
    generation_config: dict[str, Any] | None = None,
    check_model_duration: bool = True,
) -> None:
    """Guard the final video submission, even when its prompt was saved earlier."""
    from .work_chain_context import work_chain_stage_node

    video_data = _node_data(video)
    planning_strategy = str(video_data.get("planningStrategy") or video.get("strategy") or "")
    if not video_data.get("shotGroupId") and planning_strategy != "storyboard_multi_shot":
        return
    director = work_chain_stage_node(workflow, video, "director.board")
    director_data = _node_data(director or {})
    shots = director_data.get("directorPlanShots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("请先生成分镜脚本并保存修改")
    allocation = director_data.get("storyboardAllocation")
    if not isinstance(allocation, dict) or allocation.get("directorPlanHash") != director_shots_hash(shots):
        raise ValueError("分镜脚本已变化或镜头尚未分配，请保存修改")
    group_id = str(video_data.get("shotGroupId") or "")
    group = next(
        (row for row in allocation.get("groups") or [] if isinstance(row, dict) and row.get("id") == group_id),
        None,
    )
    shot_nos = group.get("shotNos") if isinstance(group, dict) else None
    if not isinstance(shot_nos, list) or shot_nos != video_data.get("shotNos"):
        raise ValueError("视频生成的镜头分配已失效，请保存修改")
    if not shot_nos or any(not isinstance(number, int) or number < 1 or number > len(shots) for number in shot_nos):
        raise ValueError("视频生成的镜头分配无效，请保存修改")
    task_card = video_data.get("videoTaskCard") if isinstance(video_data.get("videoTaskCard"), dict) else {}
    try:
        current_duration = float(
            duration_seconds if duration_seconds is not None
            else video_data.get("durationSeconds") or task_card.get("durationSeconds") or 0
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("视频生成时长无效，请重新选择时长") from exc
    if not math.isfinite(current_duration) or current_duration <= 0:
        raise ValueError("视频生成时长无效，请重新选择时长")
    if check_model_duration and not _duration_is_allowed(project_id, video, current_duration, generation_config):
        raise ValueError("视频生成时长不在当前模型支持范围内，请重新选择时长")
    rhythm = effective_rhythm(project_id, director_data.get("rhythmMultiplier"))
    group_shots = [shots[number - 1] for number in shot_nos]
    validate_shot_timing(group_shots, rhythm)
    # The card may be shorter or longer than the formal group duration. The
    # prompt projection scales its per-shot estimates to this card duration.


def _clone_branch(
    template: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    template_edges: list[dict[str, Any]],
    *,
    reset_reference_overrides: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    old_ids = [str(node["id"]) for node in template]
    new_ids = [f"shot_{kind}_{uuid.uuid4().hex[:12]}" for kind in ("card", "image", "video", "result")]
    node_id_map = dict(zip(old_ids, new_ids))
    link_id_map: dict[str, str] = {}
    cloned_nodes = [copy.deepcopy(node) for node in template]
    for node, new_id in zip(cloned_nodes, new_ids):
        node["id"] = new_id
        data = node.setdefault("data", {})
        data["nodeId"] = new_id
        if data.get("resultOfNodeId") in node_id_map:
            data["resultOfNodeId"] = node_id_map[data["resultOfNodeId"]]
        if data.get("sourceNodeId") in node_id_map:
            data["sourceNodeId"] = node_id_map[data["sourceNodeId"]]
        links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
        if reset_reference_overrides:
            links = [link for link in links if isinstance(link, dict)
                     and str(link.get("sourceNodeId") or "") in node_id_map]
            data["inputLinks"] = links
            for key in ("referenceUsage", "referenceDisplayRows", "assetThumbnails",
                        "referenceThumbnails", "referenceVideoThumbnails", "referenceManifest",
                        "referenceMediaIds", "assetRefs"):
                data.pop(key, None)
        for link in links:
            if not isinstance(link, dict):
                continue
            old_link_id = str(link.get("id") or "")
            if old_link_id:
                link_id_map[old_link_id] = f"link_{uuid.uuid4().hex[:16]}"
                link["id"] = link_id_map[old_link_id]
            for key in ("sourceNodeId", "targetNodeId"):
                if link.get(key) in node_id_map:
                    link[key] = node_id_map[link[key]]
        if isinstance(data.get("referenceUsage"), dict):
            data["referenceUsage"] = {_remap_reference_usage_key(key, node_id_map): value
                                      for key, value in data["referenceUsage"].items()}
        if node.get("type") in {"video.storyboard", "video.keyframe"}:
            data["referenceThumbnails"] = copy.deepcopy(links)
        _reset_branch_output(node)
    cloned_edges = []
    for edge in template_edges:
        copied = copy.deepcopy(edge)
        copied["id"] = f"edge_{uuid.uuid4().hex[:16]}"
        for key in ("source", "target"):
            if copied.get(key) in node_id_map:
                copied[key] = node_id_map[copied[key]]
        data = copied.get("data") if isinstance(copied.get("data"), dict) else {}
        for key in ("sourceNodeId", "targetNodeId", "resultOfNodeId"):
            if data.get(key) in node_id_map:
                data[key] = node_id_map[data[key]]
        if data.get("inputLinkId") in link_id_map:
            data["inputLinkId"] = link_id_map[data["inputLinkId"]]
        cloned_edges.append(copied)
    return cloned_nodes, cloned_edges


def apply_storyboard_allocation(project_id: str, episode_id: str, payload: dict[str, Any], *,
                                preserve_generated_normal_estimates: bool = False,
                                generation_config_patch: dict[str, Any] | None = None,
                                director_replacement_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Atomically map every director shot to an ordered storyboard/video branch."""
    _assert_canvas_mutation_does_not_return_workflow(payload, "分镜分配")
    director_id = str(payload.get("directorNodeId") or "").strip()
    if not director_id:
        raise ValueError("缺少分镜脚本 ID")
    invalidate_generated = payload.get("invalidateGenerated") is True
    director_patch = payload.get("directorPlanPatch")
    if director_patch is not None and director_replacement_data is not None:
        raise ValueError("分镜脚本不能同时提交两种内容补丁")
    if director_patch is not None:
        if not isinstance(director_patch, dict) or set(director_patch) - {
            "directorPlanShots", "speakerRoster", "directorRuleId", "directorRuleSelectionMode", "rhythmMultiplier",
            "speechBudgetNote",
        }:
            raise ValueError("分镜脚本保存包含无效字段")

    def finish_save(director, groups, result, plan_content_changed, *, structure_changed, warnings=None):
        _touch_project_meta(project_id)
        history_result: dict[str, Any] = {"skipped": True}
        if plan_content_changed:
            from .workflow_edit_history import record_workflow_node_edit_history

            try:
                history_result = record_workflow_node_edit_history(
                    project_id, episode_id, director, reason="inline_director_plan_saved",
                )
            except Exception as exc:
                print(traceback.format_exc(), flush=True)
                history_result = {"skipped": True, "error": str(exc)[:200]}
        return {
            "success": True, "episodeId": episode_id, "directorNodeId": director_id,
            "node": copy.deepcopy(director), "groups": groups,
            "structureChanged": structure_changed, "productionWarnings": warnings or [],
            "editHistory": history_result.get("item"), "editHistoryWarning": history_result.get("error") or "",
            "workflowVersion": result["workflowVersion"], "projectChanged": True,
            **_workflow_mutation_event_fields(result, [
                "canvas_node",
                *(["canvas_edge", "canvas_route", "canvas_work_chain"] if structure_changed else []),
                *([] if history_result.get("skipped") else ["node_edit_history"]),
            ]),
        }

    def update_unit_content(unit, selected_shots, selected_roster):
        data = _node_data(unit)
        if data.get("directorPlanShots") == selected_shots and (data.get("speakerRoster") or []) == selected_roster:
            return
        if _is_user_locked_item(unit):
            raise ValueError("待修改的分镜单元已由用户锁定，请先解锁")
        data["directorPlanShots"] = copy.deepcopy(selected_shots)
        data["speakerRoster"] = selected_roster
        data["summary"] = " / ".join(str(shot.get("storyboardFrame") or "")[:100] for shot in selected_shots)

    def mutate() -> dict[str, Any]:
        workflow = get_canvas_workflow_projection(project_id, episode_id, {"detail": "full"})
        expected_workflow_version = payload.get("expectedWorkflowVersion")
        if expected_workflow_version is not None and workflow.get("version") != expected_workflow_version:
            raise ValueError("分镜脚本输入资料已变化，请重新读取后提交")
        node_by_id = {str(node.get("id") or ""): node for node in workflow.get("nodes", []) if isinstance(node, dict)}
        director = node_by_id.get(director_id)
        if not director or str(director.get("type") or "") != "director.board":
            raise ValueError("请选择有效的分镜脚本")
        if _is_user_locked_item(director):
            raise ValueError("分镜脚本节点已由用户锁定，本次分镜未保存")
        director_data = _node_data(director)
        previous_shots = director_data.get("directorPlanShots")
        previous_speaker_roster = copy.deepcopy(director_data.get("speakerRoster") or [])
        if payload.get("expectedShots") != previous_shots:
            raise ValueError("分镜脚本已经变化，请重新打开")
        expected_hash = str(payload.get("directorPlanHash") or "").strip()
        if expected_hash and expected_hash != director_shots_hash(previous_shots or []):
            raise ValueError("分镜脚本已经变化，请重新打开")
        if "expectedSpeakerRoster" in payload and payload["expectedSpeakerRoster"] != (director_data.get("speakerRoster") or []):
            raise ValueError("分镜脚本的临时说话者已变化，请重新打开")
        if "expectedGroups" in payload:
            current_allocation = director_data.get("storyboardAllocation")
            current_groups = current_allocation.get("groups") if isinstance(current_allocation, dict) else None
            expected_groups = payload["expectedGroups"]
            if not isinstance(current_groups, list) or not isinstance(expected_groups, list):
                raise ValueError("镜头分组已变化，请重新打开")
            current_assignment = [
                (group.get("id"), group.get("shotNos")) for group in current_groups if isinstance(group, dict)
            ]
            expected_assignment = [
                (group.get("id"), group.get("shotNos")) for group in expected_groups if isinstance(group, dict)
            ]
            if (len(current_assignment) != len(current_groups)
                    or len(expected_assignment) != len(expected_groups)
                    or current_assignment != expected_assignment):
                raise ValueError("镜头分组已变化，请重新打开")
        plan_content_changed = False
        if director_replacement_data is not None:
            from .workflow_contract import _ensure_saved_workflow_node_contract

            director["data"] = copy.deepcopy(director_replacement_data)
            _ensure_saved_workflow_node_contract(director)
            director_data = _node_data(director)
            plan_content_changed = (
                previous_shots != director_data.get("directorPlanShots")
                or director_data.get("speakerRoster") != previous_speaker_roster
            )
        if director_patch:
            from .director_plan_contract import (
                director_plan_bound_asset_ids_for_work_chain,
                director_plan_bound_speaker_asset_ids_for_work_chain,
            )
            from .workflow_inline_editing import _normalize_workflow_inline_data_patch
            from .workflow_contract import _ensure_saved_workflow_node_contract
            from .store_core import _deep_merge

            speaker_asset_ids = None
            allowed_asset_ids = None
            if "directorPlanShots" in director_patch or "speakerRoster" in director_patch:
                speaker_asset_ids = director_plan_bound_speaker_asset_ids_for_work_chain(
                    project_id, workflow, episode_id, director_id,
                )
                allowed_asset_ids = director_plan_bound_asset_ids_for_work_chain(
                    project_id, workflow, episode_id, director_id,
                )
            normalized_patch = _normalize_workflow_inline_data_patch(
                director_patch, director_data, "director.board",
                speaker_asset_ids=speaker_asset_ids, allowed_asset_ids=allowed_asset_ids,
                preserve_generated_normal_estimates=preserve_generated_normal_estimates,
            )
            if "durationSeconds" in normalized_patch:
                card_state = copy.deepcopy(director_data.get("cardState") or {})
                card_state["durationSeconds"] = normalized_patch["durationSeconds"]
                normalized_patch["cardState"] = card_state
            if "speechBudgetNote" in director_patch:
                note = str(director_patch["speechBudgetNote"] or "")
                for key in ("prompt", "directorTaskCard"):
                    nested = normalized_patch.get(key)
                    if isinstance(nested, dict):
                        nested["speechBudgetNote"] = note
            plan_content_changed = (
                director_data.get("directorPlanShots") != normalized_patch.get("directorPlanShots", director_data.get("directorPlanShots"))
                or director_data.get("speakerRoster") != normalized_patch.get("speakerRoster", director_data.get("speakerRoster"))
            )
            director["data"] = _deep_merge(director_data, normalized_patch)
            _ensure_saved_workflow_node_contract(director)
            director_data = _node_data(director)
        if generation_config_patch:
            from .workflow_contract import _merge_generation_config_patch, _ensure_saved_workflow_node_contract

            director_data["generationConfig"] = _merge_generation_config_patch(
                director_data.get("generationConfig"), generation_config_patch,
            )
            _ensure_saved_workflow_node_contract(director)
        shots = director_data.get("directorPlanShots")
        if not isinstance(shots, list) or not shots:
            raise ValueError("请先生成或保存分镜脚本")
        rhythm = effective_rhythm(project_id, director_data.get("rhythmMultiplier"))
        validate_shot_timing(shots, rhythm)
        plan_hash = director_shots_hash(shots)
        groups = _allocation_groups(payload.get("groups"), shots)
        if shots[0].get("entryBoundaryKind") == "direct_continuation":
            work_chain_id = str(director.get("workChainId") or director_data.get("workChainId") or "")
            require_direct_continuation_previous_group(project_id, episode_id, work_chain_id)
        previous_allocation = director_data.get("storyboardAllocation")
        previous_groups = previous_allocation.get("groups") if isinstance(previous_allocation, dict) else []
        shot_count_changed = isinstance(previous_shots, list) and len(previous_shots) != len(shots)
        source_shot_nos = payload.get("sourceShotNos")
        if source_shot_nos is not None:
            if (not isinstance(source_shot_nos, list) or len(source_shot_nos) != len(shots)
                    or any(number is not None and (type(number) is not int or number < 1
                                                   or number > len(previous_shots or []))
                           for number in source_shot_nos)):
                raise ValueError("镜头来源编号无效，请重新打开分镜脚本")
            sources = [number for number in source_shot_nos if number is not None]
            if len(sources) != len(set(sources)):
                raise ValueError("镜头来源编号重复，请重新打开分镜脚本")

        def same_numbered_shots(numbers):
            # After insertion/deletion, a reused number can identify a different
            # shot. That is a membership change, unlike editing fields in place.
            if source_shot_nos is not None:
                return all(source_shot_nos[number - 1] == number for number in numbers)
            return not shot_count_changed or all(
                number <= len(previous_shots) and previous_shots[number - 1] == shots[number - 1]
                for number in numbers
            )

        previous_shot_nos = {
            str(group.get("id") or ""): group.get("shotNos")
            for group in previous_groups if isinstance(group, dict)
        }
        previous_ids_by_membership = {
            tuple(group.get("shotNos") or []): str(group.get("id") or "")
            for group in previous_groups if isinstance(group, dict) and group.get("id")
        }
        # A group's ID identifies its shot membership. A revised draft may omit
        # or rename IDs even when its allocation is unchanged; keep the saved
        # identity so unaffected media nodes and their active versions survive.
        for group in groups:
            saved_id = previous_ids_by_membership.get(tuple(group["shotNos"]))
            if saved_id and same_numbered_shots(group["shotNos"]):
                group["id"] = saved_id
        used_group_ids: set[str] = set()
        for group in groups:
            if (group["id"] in used_group_ids
                    or (group["id"] in previous_shot_nos
                        and (previous_shot_nos[group["id"]] != group["shotNos"]
                             or not same_numbered_shots(group["shotNos"])))):
                group["id"] = f"group_{uuid.uuid4().hex[:12]}"
            used_group_ids.add(group["id"])

        allocation_unchanged = (
            [(group["id"], group["shotNos"]) for group in groups]
            == [(group.get("id"), group.get("shotNos")) for group in previous_groups if isinstance(group, dict)]
        )
        if allocation_unchanged:
            from .director_plan_contract import speaker_roster_for_shots

            # Unit cards are views of the canonical plan. Updating that plan
            # must not modify generated media, video settings or running jobs.
            group_by_id = {group["id"]: group for group in groups}
            unit_ids = {
                str(edge.get("target") or "") for edge in workflow.get("edges", [])
                if isinstance(edge, dict) and str(edge.get("source") or "") == director_id
            }
            for unit in workflow.get("nodes", []):
                if unit.get("type") != "storyboard.card" or str(unit.get("id") or "") not in unit_ids:
                    continue
                data = _node_data(unit)
                group = group_by_id.get(str(data.get("shotGroupId") or ""))
                if not group:
                    continue
                selected_shots = [shots[number - 1] for number in group["shotNos"]]
                selected_roster = speaker_roster_for_shots(director_data.get("speakerRoster") or [], selected_shots)
                update_unit_content(unit, selected_shots, selected_roster)
            director_data["storyboardAllocation"] = {
                "schemaVersion": 1, "directorPlanHash": plan_hash, "groups": copy.deepcopy(groups),
            }
            result = replace_canvas_records_from_workflow_projection_v4(
                project_id, episode_id, workflow, op_type="card_patch", expected_revision=workflow.get("version"),
            )
            return finish_save(director, groups, result, plan_content_changed, structure_changed=False)

        clip_max_seconds = project_storyboard_timing(project_id)["clipMaxSeconds"]
        for group in groups:
            if sum(float(shots[number - 1].get("durationSec") or 0) for number in group["shotNos"]) > clip_max_seconds + 0.005:
                raise ValueError("镜头组已超过项目时长上限，请重新分组")
        branches = _director_branches(workflow, director)
        if not branches:
            raise ValueError("当前工作链缺少分镜图、视频生成或视频片段")
        video_ids = [str(video.get("id") or "") for _, _, video, _ in branches]
        if len(video_ids) != len(set(video_ids)):
            raise ValueError("当前工作链存在多张参考图共用一个视频生成，无法按单镜分配；请改用标准分镜工作链")
        branch_card_ids = [str(card.get("id") or "") for card, _, _, _ in branches]
        if len(branch_card_ids) != len(set(branch_card_ids)):
            raise ValueError("同一分镜单元存在多张正式分镜图，请先整理为一张结果卡的多个版本")
        handoff_source_by_id = {
            str(node.get("id") or ""): str(_node_data(node).get("resultOfNodeId") or _node_data(node).get("sourceNodeId") or "")
            for node in workflow.get("nodes", [])
            if isinstance(node, dict)
            and node.get("type") == "asset.image"
            and _node_data(node).get("mediaPurpose") == "visual_handoff"
            and str(_node_data(node).get("resultOfNodeId") or _node_data(node).get("sourceNodeId") or "") in branch_card_ids
        }
        affected_branches = [
            branch for branch in branches if not any(
                group["id"] == _node_data(branch[0]).get("shotGroupId")
                and group["shotNos"] == _node_data(branch[0]).get("shotNos") for group in groups
            )
        ]
        if any(_is_user_locked_item(node) for branch in affected_branches for node in branch):
            raise ValueError("待调整分组的卡片已由用户锁定，请先解锁")
        affected_card_ids = {str(branch[0].get("id") or "") for branch in affected_branches}
        affected_node_ids = {str(node.get("id") or "") for branch in affected_branches for node in branch}
        affected_node_ids.update(handoff_id for handoff_id, source_id in handoff_source_by_id.items()
                                 if source_id in affected_card_ids)
        from .task_storage import _load_tasks_for_project

        for task in _load_tasks_for_project(project_id):
            if str(task.get("episodeId") or "") != episode_id:
                continue
            if str(task.get("nodeId") or task.get("taskNodeId") or "") not in affected_node_ids:
                continue
            if str(task.get("status") or "") in {"created", "queued", "pending", "running", "processing", "in_progress", "cancelling"}:
                raise ValueError("分镜图或视频生成仍在执行，请等待完成后调整分配")
        original_branches = copy.deepcopy(branches)
        branch_templates = _allocation_branch_templates(groups, branches, original_branches,
                                                       shots=shots, source_shot_nos=source_shot_nos)
        original_edges = copy.deepcopy(workflow.get("edges", []))

        def clone_from(source_branch, *, reset_reference_overrides=False):
            source_ids = {str(node.get("id") or "") for node in source_branch}
            source_edges = [
                edge for edge in original_edges
                if isinstance(edge, dict)
                and str(edge.get("target") or "") in source_ids
                and str(edge.get("source") or "") != str(source_branch[3].get("id") or "")
                and not (reset_reference_overrides
                         and (edge.get("data") or {}).get("kind") == "material"
                         and str(edge.get("source") or "") not in source_ids)
            ]
            return _clone_branch(source_branch, source_edges,
                                 reset_reference_overrides=reset_reference_overrides)
        used_ids: set[str] = set()
        next_nodes: list[dict[str, Any]] = []
        next_edges: list[dict[str, Any]] = []
        production_warnings: list[dict[str, Any]] = []
        from .director_plan_contract import speaker_roster_for_shots

        for group, (branch, source_branch, preserve_references) in zip(groups, branch_templates):
            selected_shots = [shots[shot_no - 1] for shot_no in group["shotNos"]]
            selected_roster = speaker_roster_for_shots(
                director_data.get("speakerRoster") or [], selected_shots,
            )
            current_nos = _node_data(branch[0]).get("shotNos") if branch else None
            changed = branch is None or current_nos != group["shotNos"]
            if changed and branch and any(_active_output(node) for node in branch) and not invalidate_generated:
                raise ValueError("已有分镜图或视频片段；调整该组会使旧结果失效，请确认后重新分配")
            if changed:
                if branch and not current_nos and not any(_active_output(node) for node in branch):
                    # The first allocation has no prior shot branch to discard.
                    for node in branch:
                        _reset_branch_output(node)
                    branch_ids = {str(node.get("id") or "") for node in branch}
                    for edge in workflow.get("edges", []):
                        if not isinstance(edge, dict) or str(edge.get("target") or "") not in branch_ids:
                            continue
                        if str(edge.get("source") or "") not in branch_ids:
                            continue
                        edge_data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
                        edge_data.pop("sourceVersionId", None)
                        edge_data.pop("mediaVersionId", None)
                else:
                    new_nodes, new_edges = clone_from(
                        source_branch,
                        reset_reference_overrides=not preserve_references,
                    )
                    branch = tuple(new_nodes)
                    next_nodes.extend(new_nodes)
                    next_edges.extend(new_edges)
            for node in branch:
                data = node.setdefault("data", {})
                data["shotGroupId"] = group["id"]
                data["shotGroupOrder"] = group["order"]
                data["shotNos"] = copy.deepcopy(group["shotNos"])
                used_ids.add(str(node.get("id") or ""))
            card_data = _node_data(branch[0])
            update_unit_content(branch[0], selected_shots, selected_roster)
            card_data["title"] = f"分镜单元 · 镜头 {group['shotNos'][0]}" + (
                f"–{group['shotNos'][-1]}" if len(group["shotNos"]) > 1 else ""
            )
            card_data["summary"] = " / ".join(str(shot.get("storyboardFrame") or "")[:100] for shot in selected_shots)
            image_data = _node_data(branch[1])
            image_data.pop("panelIndex", None)
            if len(group["shotNos"]) == 1:
                image_data["panelIndex"] = group["shotNos"][0]
            image_data.pop("panel", None)
            image_data["title"] = f"分镜图 · 镜头 {group['shotNos'][0]}" + (
                f"–{group['shotNos'][-1]}" if len(group["shotNos"]) > 1 else ""
            )
            video_data = _node_data(branch[2])
            if changed or not video_data.get("durationSeconds"):
                group_duration = _group_duration(project_id, branch[2], selected_shots, rhythm)
                video_data["durationSeconds"] = group_duration
                video_data.setdefault("generationConfig", {})["durationSeconds"] = group_duration
                video_data.setdefault("videoTaskCard", {})["durationSeconds"] = group_duration
            if not _duration_is_allowed(project_id, branch[2], video_data.get("durationSeconds") or 0):
                production_warnings.append({
                    "groupId": group["id"], "shotNos": copy.deepcopy(group["shotNos"]),
                    "code": "video_model_duration_unavailable",
                    "message": "当前视频模型没有匹配此镜头组的时长档位；镜头和分组已保存，请选择兼容模型或时长后再制作视频。",
                })
            video_data["title"] = f"视频生成 · 镜头 {group['shotNos'][0]}" + (
                f"–{group['shotNos'][-1]}" if len(group["shotNos"]) > 1 else ""
            )
            _node_data(branch[3])["title"] = video_data["title"].replace("视频生成", "视频片段", 1)
        removed_ids = {
            str(node.get("id") or "") for branch in branches for node in branch
            if str(node.get("id") or "") not in used_ids
        }
        removed_ids.update(
            handoff_id for handoff_id, source_id in handoff_source_by_id.items()
            if source_id in removed_ids
        )
        if any(_is_user_locked_item(node_by_id.get(node_id)) for node_id in removed_ids):
            raise ValueError("被移除的分镜组或视觉交接图已由用户锁定，请先解锁")
        if removed_ids and not invalidate_generated:
            removed_nodes = [node_by_id[node_id] for node_id in removed_ids if node_id in node_by_id]
            if any(_active_output(node) for node in removed_nodes):
                raise ValueError("被移除的分镜组已有生成结果，请确认失效后重新分配")
        workflow["nodes"] = [
            node for node in workflow.get("nodes", [])
            if isinstance(node, dict) and str(node.get("id") or "") not in removed_ids
        ] + next_nodes
        _remove_deleted_node_inputs(project_id, workflow["nodes"], removed_ids)
        workflow["edges"] = [
            edge for edge in [*workflow.get("edges", []), *next_edges]
            if isinstance(edge, dict)
            and str(edge.get("source") or "") not in removed_ids
            and str(edge.get("target") or "") not in removed_ids
        ]
        _node_data(director)["storyboardAllocation"] = {
            "schemaVersion": 1, "directorPlanHash": plan_hash, "groups": copy.deepcopy(groups),
        }
        _node_data(director)["status"] = "ready"
        _node_data(director).setdefault("directorTaskCard", {})["state"] = "ready"
        _layout_workflow_by_work_chain(
            workflow["nodes"], workflow.get("routes", []), workflow.get("workChains", []), workflow["edges"],
        )
        result = replace_canvas_records_from_workflow_projection_v4(
            project_id, episode_id, workflow, op_type="structure_patch", expected_revision=workflow.get("version"),
        )
        return finish_save(director, groups, result, plan_content_changed,
                           structure_changed=True, warnings=production_warnings)

    from .workflow_production_sync import sync_workflow_production_after_commit

    result = retry_canvas_mutation_v4(mutate)
    return sync_workflow_production_after_commit(project_id, episode_id, result)
