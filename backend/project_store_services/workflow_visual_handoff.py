# -*- coding: utf-8 -*-
"""跨分集视觉交接领域。

这里承载视觉交接结果节点、项目级媒体提升、跨分集链接和清理。
旧 workflows API 通过直接名称绑定保持兼容。
"""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Any

from .agent_sessions import (
    _image_suffix_from_mime_or_name,
    _project_dir,
)
from .canvas_ownership import source_work_chain_ids
from .canvas_store_queries import episode_canvas_exists, read_canvas_card_record_v4, read_canvas_cross_episode_visual_handoff_node_v4, read_canvas_visual_handoff_result_node_v4, read_canvas_workflow_projection_v4, read_workflow_card_neighborhood_v4
from .canvas_store_mutations import write_canvas_records_v4
from .canvas_store_database import retry_canvas_mutation_v4
from .media_files import (
    _copy_local_project_image_media_file,
    _copy_local_project_video_media_file,
    _project_media_storage_dir,
    _safe_file_stem,
    _stored_media_path,
    _video_suffix_from_mime_or_name,
)
from .planning_contract import _WORKFLOW_LAYOUT_ASSET_TO_MAIN_GAP_Y, _WORKFLOW_VISUAL_HANDOFF_CROSS_EPISODE_CARD_SIZE, _WORKFLOW_VISUAL_HANDOFF_RESULT_CARD_SIZE, _is_user_locked_item, _safe_workflow_id
from .projects import (
    _is_path_within,
    _touch_project_meta,
)
from .store_core import (
    _JSON_WRITE_LOCK,
    _now,
    _read_json,
)
from .workflow_contract import (
    _PROMPT_STORYBOARD_NODE_TYPES,
    _VISUAL_HANDOFF_SLOT,
    _VISUAL_HANDOFF_SOURCE_NODE_TYPES,
    _append_unique_string,
    _apply_workflow_input_link_contract,
    _ensure_saved_workflow_edge_contract,
    _ensure_saved_workflow_node_contract,
    _node_route_id,
    _node_work_chain_id,
    _workflow_data_active_version_id,
    _workflow_default_card_size,
    _workflow_material_source_default_handle,
    _workflow_material_source_handle,
    _workflow_meaningful_output_title,
    _workflow_node,
    _workflow_node_is_visual_handoff_asset_like,
    _workflow_node_meaningful_title,
    _workflow_node_payload_data,
    _workflow_node_type,
    _workflow_node_type_value,
    _workflow_node_work_chain_id,
    _workflow_unique_id,
    _node_segment_id,
)
from .workflow_input_resolution import (
    _workflow_visual_handoff_node_for_prompt,
    _link_reference_media_id,
    _next_input_links,
    _upsert_workflow_material_edge,
    _workflow_downstream_node_ids,
)
from .workflow_contract import _workflow_mutation_event_fields

def ensure_visual_handoff_result_node(
    project_id: str,
    episode_id: str,
    prompt_node_id: str,
) -> dict[str, Any]:
    prompt_node_id = str(prompt_node_id or "").strip()
    if not project_id or not episode_id or not prompt_node_id:
        raise ValueError("生成视觉交接图缺少 projectId、episodeId 或 nodeId")
    return retry_canvas_mutation_v4(
        lambda: _ensure_visual_handoff_result_node_once(project_id, episode_id, prompt_node_id)
    )


def _ensure_visual_handoff_result_node_once(
    project_id: str, episode_id: str, prompt_node_id: str,
) -> dict[str, Any]:
    with _JSON_WRITE_LOCK:
        workflow = read_workflow_card_neighborhood_v4(
            project_id,
            episode_id,
            prompt_node_id,
            detail="full",
        )
        prompt_node = _workflow_node(workflow, prompt_node_id)
        if not prompt_node or _workflow_node_type(prompt_node) not in _VISUAL_HANDOFF_SOURCE_NODE_TYPES:
            raise ValueError("请选择分镜单元生成视觉交接图")
        prompt_data = prompt_node.get("data") if isinstance(prompt_node.get("data"), dict) else {}
        if not prompt_data.get("shotGroupId"):
            raise ValueError("请选择已分配的分镜单元生成视觉交接图")
        episode_workflow = read_canvas_workflow_projection_v4(project_id, episode_id, detail="summary")
        episode_prompt_node = _workflow_node(episode_workflow, prompt_node_id) or prompt_node
        next_prompt_node = _workflow_next_storyboard_card_node(episode_workflow, episode_prompt_node)
        if isinstance(next_prompt_node, dict):
            next_prompt_node_id = str(next_prompt_node.get("id") or "").strip()
            if next_prompt_node_id:
                try:
                    full_next_prompt_node = read_canvas_card_record_v4(
                        project_id,
                        episode_id,
                        next_prompt_node_id,
                        detail="full",
                    )
                except FileNotFoundError:
                    full_next_prompt_node = {}
                if isinstance(full_next_prompt_node, dict) and full_next_prompt_node:
                    next_prompt_node = full_next_prompt_node
                _workflow_append_or_replace_node(workflow, next_prompt_node)
        else:
            next_prompt_node = None
        handoff_node = _workflow_visual_handoff_node_for_prompt(workflow, prompt_node_id)
        if not handoff_node:
            handoff_node = read_canvas_visual_handoff_result_node_v4(
                project_id,
                episode_id,
                prompt_node_id=prompt_node_id,
                detail="full",
            )
            handoff_node_id = str(handoff_node.get("id") or "").strip() if isinstance(handoff_node, dict) else ""
            if handoff_node_id and not _workflow_node(workflow, handoff_node_id):
                workflow.setdefault("nodes", []).append(handoff_node)
        created = False
        layout_owner_node = next_prompt_node if isinstance(next_prompt_node, dict) else prompt_node
        route_id = _node_route_id(layout_owner_node)
        work_chain_id = _workflow_node_work_chain_id(workflow, layout_owner_node)
        segment_id = _node_segment_id(layout_owner_node)
        if not handoff_node:
            handoff_node_id = _workflow_visual_handoff_result_node_id(workflow, prompt_node_id)
            position = _workflow_visual_handoff_position(prompt_node, next_prompt_node)
            title = _workflow_visual_handoff_title(workflow, prompt_node)
            handoff_node = {
                "id": handoff_node_id,
                "type": "asset.image",
                "position": position,
                "routeId": route_id,
                "segmentId": segment_id,
                "workChainId": work_chain_id,
                "data": {
                    "title": title,
                    "assetName": title,
                    "status": "waiting",
                    "summary": "等待根据当前分镜单元的分镜图生成空间连续性交接板。",
                    "routeId": route_id,
                    "segmentId": segment_id,
                    "workChainId": work_chain_id,
                    "resultOfNodeId": prompt_node_id,
                    "sourceNodeId": prompt_node_id,
                    "sourceType": "visual_handoff_generation",
                    "mediaPurpose": "visual_handoff",
                    "preferredTargetSlot": _VISUAL_HANDOFF_SLOT,
                    "assetScope": "result",
                    "assetKind": "visual_handoff",
                    "assetType": "visual_handoff",
                    "visibilityScope": "workChain",
                    "cardState": {
                        "size": copy.deepcopy(_WORKFLOW_VISUAL_HANDOFF_RESULT_CARD_SIZE),
                    },
                    "provenance": {
                        "source": "system",
                        "action": "visual_handoff_result_created",
                        "createdAt": _now(),
                    },
                },
            }
            _ensure_saved_workflow_node_contract(handoff_node)
            workflow.setdefault("nodes", []).append(handoff_node)
            created = True
        else:
            handoff_node_id = str(handoff_node.get("id") or "").strip()
            handoff_data = handoff_node.setdefault("data", {})
            if not isinstance(handoff_data, dict):
                handoff_data = {}
                handoff_node["data"] = handoff_data
            handoff_data["resultOfNodeId"] = prompt_node_id
            handoff_data["sourceNodeId"] = prompt_node_id
            handoff_data["sourceType"] = "visual_handoff_generation"
            handoff_data["mediaPurpose"] = "visual_handoff"
            handoff_data["preferredTargetSlot"] = _VISUAL_HANDOFF_SLOT
            handoff_data["assetKind"] = "visual_handoff"
            handoff_data["assetType"] = "visual_handoff"
            _ensure_saved_workflow_node_contract(handoff_node)

        _workflow_ensure_visual_handoff_source_edge(workflow, prompt_node_id, handoff_node_id)
        linked_target_node_id = ""
        linked_input_link: dict[str, Any] = {}
        next_prompt_node_id = str((next_prompt_node or {}).get("id") or "").strip()
        previously_considered_target_id = str(handoff_node["data"].get("autoLinkTargetNodeId") or "").strip()
        removed_old_target_id = ""
        deleted_edge_ids: list[str] = []
        should_consider_next_target = not previously_considered_target_id
        if previously_considered_target_id and previously_considered_target_id != next_prompt_node_id:
            try:
                previous_target = read_canvas_card_record_v4(
                    project_id, episode_id, previously_considered_target_id, detail="full",
                )
            except FileNotFoundError:
                previous_target = {}
            if not previous_target:
                should_consider_next_target = True
            else:
                previous_data = previous_target.get("data") if isinstance(previous_target.get("data"), dict) else {}
                previous_links = previous_data.get("inputLinks") if isinstance(previous_data.get("inputLinks"), list) else []
                auto_links = [
                    link for link in previous_links
                    if isinstance(link, dict)
                    and str(link.get("sourceNodeId") or "").strip() == handoff_node_id
                    and str(link.get("targetSlot") or "").strip() == _VISUAL_HANDOFF_SLOT
                    and isinstance(link.get("provenance"), dict)
                    and link["provenance"].get("action") == "visual_handoff_auto_linked"
                    and link.get("enabled") is not False
                ]
                auto_edges = [
                    edge for edge in episode_workflow.get("edges") or []
                    if isinstance(edge, dict)
                    and str(edge.get("source") or "").strip() == handoff_node_id
                    and str(edge.get("target") or "").strip() == previously_considered_target_id
                    and isinstance(edge.get("data"), dict)
                    and str(edge["data"].get("kind") or "").strip() == "material"
                    and str(edge["data"].get("targetSlot") or edge["data"].get("slot") or edge["data"].get("role") or "").strip() == _VISUAL_HANDOFF_SLOT
                ]
                reference_source_ids = {
                    str(link.get("sourceNodeId") or "").strip()
                    for link in previous_links
                    if isinstance(link, dict)
                    and str(link.get("targetSlot") or link.get("slot") or "").strip() == _VISUAL_HANDOFF_SLOT
                    and str(link.get("sourceNodeId") or "").strip()
                } | {
                    str(edge.get("source") or "").strip()
                    for edge in episode_workflow.get("edges") or []
                    if isinstance(edge, dict)
                    and str(edge.get("target") or "").strip() == previously_considered_target_id
                    and isinstance(edge.get("data"), dict)
                    and str(edge["data"].get("kind") or "").strip() == "material"
                    and str(edge["data"].get("targetSlot") or edge["data"].get("slot") or edge["data"].get("role") or "").strip() == _VISUAL_HANDOFF_SLOT
                    and str(edge.get("source") or "").strip()
                }
                if auto_links and not (
                    _is_user_locked_item(previous_target)
                    or any(_is_user_locked_item(link) for link in auto_links)
                    or any(_is_user_locked_item(edge) for edge in auto_edges)
                ):
                    previous_data["inputLinks"] = [link for link in previous_links if link not in auto_links]
                    removed_media_ids = {_link_reference_media_id(link) for link in auto_links}
                    remaining_media_ids = {
                        _link_reference_media_id(link)
                        for link in previous_data["inputLinks"] if isinstance(link, dict)
                    }
                    previous_media_ids = previous_data.get("referenceMediaIds") if isinstance(previous_data.get("referenceMediaIds"), list) else []
                    previous_data["referenceMediaIds"] = [
                        media_id for media_id in previous_media_ids
                        if media_id not in removed_media_ids or media_id in remaining_media_ids
                    ]
                    _workflow_append_or_replace_node(workflow, previous_target)
                    removed_old_target_id = previously_considered_target_id
                    should_consider_next_target = True
                    deleted_edge_ids = [
                        str(edge.get("id") or "").strip()
                        for edge in auto_edges
                        if str(edge.get("id") or "").strip()
                    ]
                    workflow["edges"] = [
                        edge for edge in workflow.get("edges") or []
                        if not (isinstance(edge, dict) and str(edge.get("id") or "").strip() in deleted_edge_ids)
                    ]
                elif not auto_links and reference_source_ids and handoff_node_id not in reference_source_ids:
                    # The old target had its own handoff, so our result was never linked there.
                    should_consider_next_target = True
        if next_prompt_node_id and should_consider_next_target:
            if _is_user_locked_item(next_prompt_node):
                handoff_node["data"].pop("autoLinkTargetNodeId", None)
            else:
                handoff_node["data"]["autoLinkTargetNodeId"] = next_prompt_node_id
            if not _is_user_locked_item(next_prompt_node) and not _workflow_prompt_has_visual_handoff_reference(workflow, next_prompt_node):
                linked = _workflow_link_visual_handoff_to_prompt(
                    workflow,
                    handoff_node,
                    next_prompt_node,
                    provenance_action="visual_handoff_auto_linked",
                )
                linked_input_link = copy.deepcopy(linked) if isinstance(linked, dict) else {}
                linked_target_node_id = str(linked.get("targetNodeId") or "").strip()

        if not next_prompt_node_id and should_consider_next_target:
            handoff_node["data"].pop("autoLinkTargetNodeId", None)

        if not created and (
            should_consider_next_target or previously_considered_target_id == next_prompt_node_id
        ):
            owner_changed = any(
                str(handoff_node.get(key) or "") != str(value or "")
                for key, value in (
                    ("routeId", route_id), ("segmentId", segment_id), ("workChainId", work_chain_id),
                )
            )
            for key, value in (
                ("routeId", route_id), ("segmentId", segment_id), ("workChainId", work_chain_id),
            ):
                handoff_node[key] = value
                handoff_node["data"][key] = value
            if (
                (previously_considered_target_id != next_prompt_node_id or owner_changed)
                and not handoff_node["data"].get("positionEditedByUser")
            ):
                handoff_node["position"] = _workflow_visual_handoff_position(prompt_node, next_prompt_node)

        related_node_ids = {
            item
            for item in [prompt_node_id, handoff_node_id, linked_target_node_id, removed_old_target_id]
            if item
        }
        related_nodes, related_edges = _workflow_related_canvas_records(
            workflow,
            related_node_ids,
        )
        save_result = write_canvas_records_v4(
            project_id,
            episode_id,
            nodes=related_nodes,
            edges=related_edges,
            delete_edge_ids=deleted_edge_ids,
            expected_revision=workflow.get("version"),
            op_type="structure_patch",
            changed_resources=["canvas_node", "canvas_edge", "visual_handoff"],
        )
        _touch_project_meta(project_id)
        workflow["version"] = save_result.get("workflowVersion") or workflow.get("version")
        mutation_fields = _workflow_mutation_event_fields(
            save_result,
            ["canvas_node", "canvas_edge", "visual_handoff"],
        )
        return {
            "success": True,
            "episodeId": episode_id,
            "nodeId": handoff_node_id,
            "sourceNodeId": prompt_node_id,
            "created": created,
            "linkedTargetNodeId": linked_target_node_id,
            "inputLink": linked_input_link,
            "nodes": related_nodes,
            "edges": related_edges,
            "workflowOmitted": True,
            "workflowVersion": save_result.get("workflowVersion") or workflow.get("version"),
            **mutation_fields,
        }


def _episode_sort_key(episode_id: str, fallback_index: int) -> tuple[int, str]:
    match = re.search(r"\d+", str(episode_id or ""))
    if match:
        try:
            return int(match.group(0)), str(episode_id or "")
        except ValueError:
            pass
    return fallback_index + 100000, str(episode_id or "")


def _project_episode_ids_ordered(project_id: str) -> list[str]:
    project_root = _project_dir(project_id)
    meta = _read_json(project_root / "project.json", {})
    rows: list[tuple[int, str]] = []
    seen: set[str] = set()
    episodes = meta.get("episodes") if isinstance(meta, dict) and isinstance(meta.get("episodes"), list) else []
    for index, item in enumerate(episodes):
        if not isinstance(item, dict):
            continue
        episode_id = str(item.get("id") or f"E{index + 1:02d}").strip()
        if not episode_id or episode_id in seen:
            continue
        seen.add(episode_id)
        order = _episode_sort_key(episode_id, index)[0]
        rows.append((order, episode_id))
    episodes_dir = project_root / "episodes"
    if episodes_dir.is_dir():
        for index, path in enumerate(sorted(item for item in episodes_dir.iterdir() if item.is_dir())):
            episode_id = path.name
            if episode_id in seen:
                continue
            seen.add(episode_id)
            rows.append((_episode_sort_key(episode_id, index)[0], episode_id))
    rows.sort(key=lambda item: (item[0], item[1]))
    return [episode_id for _order, episode_id in rows]


def _next_project_episode_id(project_id: str, episode_id: str) -> str:
    episode_ids = _project_episode_ids_ordered(project_id)
    current = str(episode_id or "").strip()
    for index, item in enumerate(episode_ids):
        if item == current and index + 1 < len(episode_ids):
            return episode_ids[index + 1]
    return ""


def _previous_project_episode_id(project_id: str, episode_id: str) -> str:
    episode_ids = _project_episode_ids_ordered(project_id)
    current = str(episode_id or "").strip()
    for index, item in enumerate(episode_ids):
        if item == current and index > 0:
            return episode_ids[index - 1]
    return ""


def _visual_handoff_cross_episode_media_node_id(source_episode_id: str, source_node_id: str) -> str:
    digest = hashlib.sha1(f"{source_episode_id}:{source_node_id}".encode("utf-8")).hexdigest()[:12]
    return f"media_external_visual_handoff_{digest}"


def _promote_visual_handoff_media_to_project_scope(
    project_id: str,
    media: dict[str, Any],
    *,
    source_episode_id: str = "",
) -> dict[str, Any]:
    """Give cross-episode handoffs a project-owned copy.

    A target episode must not depend on a source episode directory that can be
    deleted independently.  The content hash makes repeated syncs reuse the
    same project copy while keeping the source media immutable.
    """
    source_path = _stored_media_path(project_id, media)
    if not source_path or not source_path.is_file():
        raise FileNotFoundError("视觉交接图来源文件不存在")
    project_root = _project_dir(project_id).resolve()
    resolved_source = source_path.resolve()
    if not _is_path_within(resolved_source, project_root):
        raise ValueError("视觉交接图来源必须属于当前项目")
    digest = hashlib.sha256(resolved_source.read_bytes()).hexdigest()
    media_id = f"visual-handoff-{digest[:32]}"
    destination_suffix = _image_suffix_from_mime_or_name(
        str(media.get("mimeType") or "image/png"),
        str(media.get("originalName") or resolved_source.name),
    )
    destination_path = (
        _project_media_storage_dir(project_id, "continuity", storage_scope="assets")
        / f"{_safe_file_stem(media_id, media_id)}{destination_suffix}"
    )
    destination_existed = destination_path.is_file()
    copied = _copy_local_project_image_media_file(
        project_id,
        resolved_source,
        media_id=media_id,
        subdir="continuity",
        original_name=str(media.get("originalName") or resolved_source.name),
        source_mime=str(media.get("mimeType") or "image/png"),
        storage_scope="assets",
    )
    result = {
        **copy.deepcopy(media),
        **copied,
        "kind": "image",
        "assetType": "visual_handoff",
        "storageScope": "project",
        "sourceEpisodeId": source_episode_id,
        "sourceMediaId": str(media.get("id") or ""),
        "contentHash": digest,
    }
    if not destination_existed:
        result["_promotionPath"] = str(destination_path)
    return result


def _promote_cross_episode_media_reference(
    project_id: str,
    media: dict[str, Any],
    *,
    source_episode_id: str,
    target_episode_id: str,
    visual_handoff: bool = False,
) -> dict[str, Any]:
    """Copy episode-owned media before pasting it into another episode."""
    source_path = _stored_media_path(project_id, media)
    if not source_path or not source_path.is_file():
        raise FileNotFoundError("跨分集复制的媒体文件不存在")
    project_root = _project_dir(project_id).resolve()
    resolved_source = source_path.resolve()
    if not _is_path_within(resolved_source, project_root):
        raise ValueError("跨分集复制的媒体必须属于当前项目")
    if _is_path_within(resolved_source, (_project_dir(project_id) / "assets").resolve()):
        return copy.deepcopy(media)
    if visual_handoff:
        return _promote_visual_handoff_media_to_project_scope(
            project_id,
            media,
            source_episode_id=source_episode_id,
        )
    digest = hashlib.sha256(resolved_source.read_bytes()).hexdigest()
    kind = str(media.get("kind") or media.get("mediaType") or "image").strip().lower()
    media_id = f"cross-episode-{kind}-{digest[:24]}"
    source_name = str(media.get("originalName") or resolved_source.name)
    source_mime = str(media.get("mimeType") or ("video/mp4" if kind == "video" else "image/png"))
    if kind == "video":
        destination_suffix = _video_suffix_from_mime_or_name(source_mime, source_name)
        destination_dir = _project_media_storage_dir(
            project_id, "videos", storage_scope="episode_results", episode_id=target_episode_id,
        )
    else:
        destination_suffix = _image_suffix_from_mime_or_name(source_mime, source_name)
        destination_dir = _project_media_storage_dir(
            project_id, "canvas_media", storage_scope="episode_results", episode_id=target_episode_id,
        )
    destination_path = destination_dir / f"{_safe_file_stem(media_id, media_id)}{destination_suffix}"
    destination_existed = destination_path.is_file()
    if kind == "video":
        copied = _copy_local_project_video_media_file(
            project_id,
            resolved_source,
            media_id=media_id,
            subdir="videos",
            original_name=source_name,
            source_mime=source_mime,
            storage_scope="episode_results",
            episode_id=target_episode_id,
        )
    else:
        copied = _copy_local_project_image_media_file(
            project_id,
            resolved_source,
            media_id=media_id,
            subdir="canvas_media",
            original_name=source_name,
            source_mime=source_mime,
            storage_scope="episode_results",
            episode_id=target_episode_id,
        )
    result = {
        **copy.deepcopy(media),
        **copied,
        "sourceEpisodeId": source_episode_id,
        "sourceMediaId": str(media.get("id") or ""),
        "contentHash": digest,
        "storageScope": "episode_results",
    }
    if not destination_existed:
        result["_promotionPath"] = str(destination_path)
    return result


def _cleanup_promoted_media_copy(project_id: str, path_value: Any) -> None:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return
    path = Path(raw_path).resolve()
    project_root = _project_dir(project_id).resolve()
    if not _is_path_within(path, project_root):
        return
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        return


def sync_visual_handoff_cross_episode_link(
    project_id: str,
    episode_id: str,
    source_node: dict[str, Any],
    version: dict[str, Any],
    *,
    allow_auto_link: bool = True,
) -> dict[str, Any]:
    return retry_canvas_mutation_v4(
        lambda: _sync_visual_handoff_cross_episode_link_once(
            project_id, episode_id, source_node, version, allow_auto_link=allow_auto_link,
        )
    )


def _sync_visual_handoff_cross_episode_link_once(
    project_id: str,
    episode_id: str,
    source_node: dict[str, Any],
    version: dict[str, Any],
    *,
    allow_auto_link: bool = True,
) -> dict[str, Any]:
    source_node_id = str(source_node.get("id") or "").strip()
    if not source_node_id:
        return {"linked": False, "reason": "missing_source_node_id"}
    source_data = source_node.get("data") if isinstance(source_node.get("data"), dict) else {}
    source_card_node_id = str(source_data.get("resultOfNodeId") or source_data.get("sourceNodeId") or "").strip()
    if not source_card_node_id:
        return {"linked": False, "reason": "missing_source_storyboard_card"}
    source_episode_workflow = read_canvas_workflow_projection_v4(project_id, episode_id, detail="summary")
    source_card_node = _workflow_node(source_episode_workflow, source_card_node_id)
    if not source_card_node or _workflow_node_type(source_card_node) != "storyboard.card":
        return {"linked": False, "reason": "source_storyboard_card_missing"}
    same_episode_next_card = _workflow_next_storyboard_card_node(source_episode_workflow, source_card_node)
    if same_episode_next_card:
        return {
            "linked": False,
            "reason": "same_episode_next_storyboard_card_exists",
            "targetNodeId": str(same_episode_next_card.get("id") or "").strip(),
        }
    if _workflow_node_work_chain_id(source_episode_workflow, source_card_node) not in source_work_chain_ids(source_episode_workflow):
        return {"linked": False, "reason": "source_storyboard_card_not_episode_chain"}
    media = version.get("media") if isinstance(version.get("media"), dict) else {}
    if not media:
        return {"linked": False, "reason": "missing_media"}
    next_episode_id = _next_project_episode_id(project_id, episode_id)
    if not next_episode_id or not episode_canvas_exists(project_id, next_episode_id):
        return {"linked": False, "reason": "next_episode_canvas_missing", "episodeId": next_episode_id}
    target_episode_workflow = read_canvas_workflow_projection_v4(project_id, next_episode_id, detail="summary")
    target_card_node = _workflow_episode_storyboard_card_boundary_node(
        project_id,
        next_episode_id,
        detail="full",
    )
    if not target_card_node:
        return {"linked": False, "reason": "next_episode_storyboard_card_missing", "episodeId": next_episode_id}
    _workflow_append_or_replace_node(target_episode_workflow, target_card_node)
    target_workflow = {
        "episodeId": next_episode_id,
        "nodes": [target_card_node],
        "edges": [],
        "routes": [],
        "workChains": [],
    }
    target_has_visual_handoff_reference = _workflow_prompt_has_visual_handoff_reference(
        target_episode_workflow,
        target_card_node,
    )
    source_version_id = str(version.get("id") or "").strip()
    media_node = read_canvas_cross_episode_visual_handoff_node_v4(
        project_id,
        next_episode_id,
        source_episode_id=episode_id,
        source_node_id=source_node_id,
        detail="full",
    )
    media_node_created = False
    if media_node:
        target_workflow.setdefault("nodes", []).append(media_node)
    target_locked = _is_user_locked_item(target_card_node)
    if target_locked and not media_node:
        return {
            "linked": False,
            "reason": "target_storyboard_card_locked",
            "episodeId": next_episode_id,
            "targetNodeId": str(target_card_node.get("id") or "").strip(),
        }
    if target_has_visual_handoff_reference and not media_node:
        return {
            "linked": False,
            "reason": "target_visual_handoff_reference_exists",
            "episodeId": next_episode_id,
            "targetNodeId": str(target_card_node.get("id") or "").strip(),
        }
    if not media_node and not allow_auto_link:
        return {
            "linked": False,
            "updated": False,
            "reason": "cross_episode_visual_handoff_auto_link_skipped",
            "episodeId": next_episode_id,
            "sourceNodeId": source_node_id,
            "targetNodeId": str(target_card_node.get("id") or "").strip(),
        }
    promotion_path = ""
    try:
        media = _promote_visual_handoff_media_to_project_scope(
            project_id,
            media,
            source_episode_id=episode_id,
        )
        promotion_path = str(media.pop("_promotionPath", "") or "")
    except (FileNotFoundError, ValueError) as exc:
        return {"linked": False, "reason": "media_promotion_failed", "message": str(exc)}
    title = str(source_data.get("title") or source_data.get("assetName") or version.get("title") or "上一集视觉交接图")
    target_pos = _workflow_node_position(target_card_node)
    target_size = _workflow_node_actual_card_size(target_card_node)
    media_size = _WORKFLOW_VISUAL_HANDOFF_CROSS_EPISODE_CARD_SIZE
    asset_row_top = _workflow_visual_handoff_target_asset_row_top(target_episode_workflow, target_card_node)
    if asset_row_top is None:
        asset_row_top = target_pos["y"]
    media_position = {
        "x": target_pos["x"] + (target_size.get("width", 380) - media_size.get("width", 240)) / 2,
        "y": max(
            40,
            asset_row_top
            - media_size.get("height", 260)
            - _WORKFLOW_LAYOUT_ASSET_TO_MAIN_GAP_Y,
        ),
    }
    if not media_node:
        base_media_node_id = _visual_handoff_cross_episode_media_node_id(episode_id, source_node_id)
        media_node_id = base_media_node_id
        used_media_node_ids: set[str] = set()
        while True:
            try:
                existing_media_node = read_canvas_card_record_v4(
                    project_id,
                    next_episode_id,
                    media_node_id,
                    detail="full",
                )
            except FileNotFoundError:
                existing_media_node = {}
            if not existing_media_node:
                break
            used_media_node_ids.add(media_node_id)
            if str(existing_media_node.get("type") or "").strip() == "media.external":
                media_node = existing_media_node
                target_workflow.setdefault("nodes", []).append(media_node)
                break
            media_node_id = _workflow_unique_id(base_media_node_id, used_media_node_ids, base_media_node_id)
        if not media_node:
            media_node = {
                "id": media_node_id,
                "type": "media.external",
                "position": media_position,
                "data": {
                    "title": title,
                    "assetName": title,
                    "status": "ready",
                    "summary": "上一画布生成的视觉交接图，已接入当前画布的第一个分镜单元。",
                    "sourceType": "cross_episode_visual_handoff",
                    "mediaPurpose": "visual_handoff",
                    "preferredTargetSlot": _VISUAL_HANDOFF_SLOT,
                    "assetScope": "result",
                    "assetKind": "visual_handoff",
                    "assetType": "visual_handoff",
                    "visibilityScope": "global",
                    "mediaId": str(media.get("id") or ""),
                    "media": copy.deepcopy(media),
                    "storage": copy.deepcopy(media),
                    "sourceEpisodeId": episode_id,
                    "sourceNodeId": source_node_id,
                    "sourceVersionId": source_version_id,
                    "cardState": {"size": copy.deepcopy(_WORKFLOW_VISUAL_HANDOFF_CROSS_EPISODE_CARD_SIZE)},
                    "provenance": {
                        "source": "system",
                        "action": "visual_handoff_cross_episode_imported",
                        "createdAt": _now(),
                    },
                },
            }
            _ensure_saved_workflow_node_contract(media_node)
            target_workflow.setdefault("nodes", []).append(media_node)
            media_node_created = True
    elif not _workflow_node(target_workflow, str(media_node.get("id") or "").strip()):
        target_workflow.setdefault("nodes", []).append(media_node)
    if media_node:
        if media_node_created or not isinstance(media_node.get("position"), dict):
            media_node["position"] = media_position
        media_data = media_node.setdefault("data", {})
        if not isinstance(media_data, dict):
            media_data = {}
            media_node["data"] = media_data
        media_data.update(
            {
                "title": title,
                "assetName": title,
                "status": "ready",
                "mediaId": str(media.get("id") or ""),
                "media": copy.deepcopy(media),
                "storage": copy.deepcopy(media),
                "sourceEpisodeId": episode_id,
                "sourceNodeId": source_node_id,
                "sourceVersionId": source_version_id,
                "sourceType": "cross_episode_visual_handoff",
                "mediaPurpose": "visual_handoff",
                "preferredTargetSlot": _VISUAL_HANDOFF_SLOT,
                "assetKind": "visual_handoff",
                "assetType": "visual_handoff",
                "assetScope": "result",
            }
        )
    media_node_id = str(media_node.get("id") or "").strip()
    target_node_id = ""
    changed_target_node_id = ""
    target_has_same_visual_handoff_reference = _workflow_prompt_has_visual_handoff_reference_from_source(
        target_episode_workflow,
        target_card_node,
        media_node_id,
    )
    if target_locked and target_has_same_visual_handoff_reference:
        target_node_id = str(target_card_node.get("id") or "").strip()
    elif not target_locked and (media_node_created or target_has_same_visual_handoff_reference):
        try:
            input_link = _workflow_link_visual_handoff_to_prompt(
                target_workflow,
                media_node,
                target_card_node,
                provenance_action="visual_handoff_cross_episode_auto_linked",
            )
        except Exception:
            _cleanup_promoted_media_copy(project_id, promotion_path)
            raise
        target_node_id = str(input_link.get("targetNodeId") or target_card_node.get("id") or "").strip()
        changed_target_node_id = target_node_id
    try:
        related_nodes, related_edges = _workflow_related_canvas_records(
            target_workflow,
            {item for item in [media_node_id, changed_target_node_id] if item},
        )
    except Exception:
        _cleanup_promoted_media_copy(project_id, promotion_path)
        raise
    changed_resources = ["canvas_node", "visual_handoff"]
    if related_edges:
        changed_resources = ["canvas_node", "canvas_edge", "visual_handoff"]
    try:
        save_result = write_canvas_records_v4(
            project_id,
            next_episode_id,
            nodes=related_nodes,
            edges=related_edges,
            expected_revision=target_episode_workflow.get("version"),
            op_type="structure_patch",
            changed_resources=changed_resources,
        )
    except Exception:
        _cleanup_promoted_media_copy(project_id, promotion_path)
        raise
    _touch_project_meta(project_id)
    target_workflow["version"] = save_result.get("workflowVersion") or target_workflow.get("version")
    mutation_fields = _workflow_mutation_event_fields(save_result, changed_resources)
    linked_to_target = bool(target_node_id)
    auto_linked = media_node_created and linked_to_target
    return {
        "linked": linked_to_target,
        "autoLinked": auto_linked,
        "updated": bool(media_node_id),
        **({} if media_node_created or linked_to_target else {"reason": "cross_episode_visual_handoff_node_exists"}),
        "episodeId": next_episode_id,
        "sourceNodeId": source_node_id,
        "mediaNodeId": media_node_id,
        "targetNodeId": target_node_id,
        "workflowVersion": target_workflow.get("version"),
        **mutation_fields,
    }


def _workflow_position_number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback

def _workflow_node_position(node: dict[str, Any] | None) -> dict[str, float]:
    if not isinstance(node, dict):
        return {"x": 0.0, "y": 0.0}
    position = node.get("position") if isinstance(node.get("position"), dict) else {}
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    data_position = data.get("position") if isinstance(data.get("position"), dict) else {}
    return {
        "x": _workflow_position_number(position.get("x") if position else data_position.get("x"), 0.0),
        "y": _workflow_position_number(position.get("y") if position else data_position.get("y"), 0.0),
    }

def _workflow_prompt_storyboard_nodes_ordered(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    chain_order: dict[str, int] = {}
    for index, chain in enumerate(workflow.get("workChains", []) if isinstance(workflow.get("workChains"), list) else []):
        if not isinstance(chain, dict):
            continue
        chain_id = str(chain.get("id") or chain.get("workChainId") or "").strip()
        if not chain_id:
            continue
        try:
            order = int(chain.get("order") or index + 1)
        except (TypeError, ValueError):
            order = index + 1
        chain_order[chain_id] = order
    route_order: dict[str, int] = {}
    route_chain: dict[str, str] = {}
    for index, route in enumerate(workflow.get("routes", []) if isinstance(workflow.get("routes"), list) else []):
        if not isinstance(route, dict):
            continue
        route_id = str(route.get("id") or route.get("routeId") or "").strip()
        if not route_id:
            continue
        route_order[route_id] = index + 1
        route_chain[route_id] = str(route.get("workChainId") or route.get("work_chain_id") or "").strip()

    def sort_key(node: dict[str, Any]) -> tuple[int, int, float, float, str]:
        node_id = str(node.get("id") or "")
        route_id = _node_route_id(node)
        work_chain_id = _workflow_node_work_chain_id(workflow, node) or route_chain.get(route_id, "")
        position = _workflow_node_position(node)
        return (
            chain_order.get(work_chain_id, 9999),
            route_order.get(route_id, 9999),
            position["y"],
            position["x"],
            node_id,
        )

    nodes = [
        node
        for node in (workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else [])
        if isinstance(node, dict) and _workflow_node_type(node) in _PROMPT_STORYBOARD_NODE_TYPES
    ]
    return sorted(nodes, key=sort_key)


def _workflow_storyboard_card_nodes_ordered(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    chain_order = {
        str(chain.get("id") or chain.get("workChainId") or "").strip(): _workflow_position_number(chain.get("order"), index + 1)
        for index, chain in enumerate(workflow.get("workChains") or [])
        if isinstance(chain, dict)
    }
    route_order = {
        str(route.get("id") or route.get("routeId") or "").strip(): index
        for index, route in enumerate(workflow.get("routes") or [])
        if isinstance(route, dict)
    }

    def sort_key(node: dict[str, Any]) -> tuple[int, int, float, float, str]:
        position = _workflow_node_position(node)
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        try:
            group_order = float(data.get("shotGroupOrder"))
        except (TypeError, ValueError):
            group_order = position["y"]
        return (
            chain_order.get(_workflow_node_work_chain_id(workflow, node), 9999),
            route_order.get(_node_route_id(node), 9999),
            group_order,
            position["x"],
            str(node.get("id") or ""),
        )

    return sorted(
        (node for node in workflow.get("nodes") or []
         if isinstance(node, dict) and _workflow_node_type(node) == "storyboard.card"),
        key=sort_key,
    )


def _workflow_next_storyboard_card_node(
    workflow: dict[str, Any], source_node: dict[str, Any],
) -> dict[str, Any] | None:
    source_id = str(source_node.get("id") or "").strip()
    source_chain_id = _workflow_node_work_chain_id(workflow, source_node)
    source_chain_ids = source_work_chain_ids(workflow)
    eligible_chain_ids = source_chain_ids if source_chain_id in source_chain_ids else {source_chain_id}
    rows = [
        node for node in _workflow_storyboard_card_nodes_ordered(workflow)
        if _workflow_node_work_chain_id(workflow, node) in eligible_chain_ids
    ]
    return next(
        (rows[index + 1] for index, node in enumerate(rows[:-1])
         if str(node.get("id") or "").strip() == source_id),
        None,
    )


def _workflow_episode_storyboard_card_boundary_node(
    project_id: str, episode_id: str, *, boundary: str = "first", detail: str = "full",
) -> dict[str, Any] | None:
    workflow = read_canvas_workflow_projection_v4(project_id, episode_id, detail="summary")
    chain_ids = source_work_chain_ids(workflow)
    rows = [
        node for node in _workflow_storyboard_card_nodes_ordered(workflow)
        if _workflow_node_work_chain_id(workflow, node) in chain_ids
    ]
    if not rows:
        return None
    node = rows[-1] if boundary == "last" else rows[0]
    node_id = str(node.get("id") or "").strip()
    if detail == "full" and node_id:
        try:
            return read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
        except FileNotFoundError:
            pass
    return copy.deepcopy(node)

def _workflow_node_actual_card_size(node: dict[str, Any] | None) -> dict[str, int]:
    node_type = _workflow_node_type_value(node)
    data = _workflow_node_payload_data(node)
    card_state = data.get("cardState") if isinstance(data.get("cardState"), dict) else {}
    size = card_state.get("size") if isinstance(card_state.get("size"), dict) else {}
    defaults = _workflow_default_card_size(node_type)
    return {
        "width": int(size.get("width") or defaults.get("width") or 320),
        "height": int(size.get("height") or defaults.get("height") or 260),
    }

def _workflow_visual_handoff_target_asset_row_top(
    workflow: dict[str, Any],
    target_node: dict[str, Any],
) -> float | None:
    target_node_id = str((target_node or {}).get("id") or "").strip()
    if not target_node_id:
        return None
    workflow_edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    source_ids: set[str] = set()
    for edge in workflow_edges:
        if not isinstance(edge, dict) or str(edge.get("target") or "").strip() != target_node_id:
            continue
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        if str(data.get("kind") or "").strip() != "material":
            continue
        slot = str(data.get("targetSlot") or data.get("target_slot") or data.get("slot") or "").strip()
        if slot == _VISUAL_HANDOFF_SLOT:
            continue
        source_node_id = str(edge.get("source") or "").strip()
        if source_node_id:
            source_ids.add(source_node_id)
    if not source_ids:
        return None
    row_tops: list[float] = []
    for node in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
        if not isinstance(node, dict) or str(node.get("id") or "").strip() not in source_ids:
            continue
        if _workflow_node_is_visual_handoff_asset_like(node):
            continue
        node_type = _workflow_node_type_value(node)
        if node_type not in {"asset.image", "media.external", "storyboard.image"}:
            continue
        position = _workflow_node_position(node)
        row_tops.append(position["y"])
    return min(row_tops) if row_tops else None

def _workflow_visual_handoff_title(workflow: dict[str, Any], prompt_node: dict[str, Any]) -> str:
    source_title = _workflow_node_meaningful_title(workflow, str(prompt_node.get("id") or ""))
    source_title = _workflow_meaningful_output_title(source_title)
    if source_title:
        return f"{source_title} · 视觉交接图"
    return "视觉交接图"

def _workflow_visual_handoff_position(
    prompt_node: dict[str, Any],
    next_prompt_node: dict[str, Any] | None,
) -> dict[str, float]:
    source_pos = _workflow_node_position(prompt_node)
    source_size = _workflow_node_actual_card_size(prompt_node)
    handoff_size = _WORKFLOW_VISUAL_HANDOFF_RESULT_CARD_SIZE
    if isinstance(next_prompt_node, dict):
        target_pos = _workflow_node_position(next_prompt_node)
        target_size = _workflow_node_actual_card_size(next_prompt_node)
        source_bottom = source_pos["y"] + source_size["height"]
        target_top = target_pos["y"]
        return {
            "x": target_pos["x"] + (target_size["width"] - handoff_size["width"]) / 2,
            "y": max(40, source_bottom + max(40, (target_top - source_bottom - handoff_size["height"]) / 2)),
        }
    return {
        "x": source_pos["x"] + (source_size["width"] - handoff_size["width"]) / 2,
        "y": source_pos["y"] + source_size["height"] + _WORKFLOW_LAYOUT_ASSET_TO_MAIN_GAP_Y,
    }

def _workflow_visual_handoff_result_node_id(workflow: dict[str, Any], prompt_node_id: str) -> str:
    used = {
        str(node.get("id") or "").strip()
        for node in (workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else [])
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }
    base = f"visual_handoff_{prompt_node_id}"
    candidate = _safe_workflow_id(base, f"visual_handoff_{hashlib.sha1(prompt_node_id.encode('utf-8')).hexdigest()[:10]}")
    if candidate not in used:
        return candidate
    existing = _workflow_node(workflow, candidate)
    existing_data = existing.get("data") if isinstance((existing or {}).get("data"), dict) else {}
    if (
        existing
        and str(existing.get("type") or "") == "asset.image"
        and str(existing_data.get("resultOfNodeId") or existing_data.get("sourceNodeId") or "").strip() == prompt_node_id
    ):
        return candidate
    return _workflow_unique_id(base, used, f"visual_handoff_{hashlib.sha1(prompt_node_id.encode('utf-8')).hexdigest()[:10]}")

def _workflow_visual_handoff_input_link(
    source_node: dict[str, Any],
    target_node: dict[str, Any],
    *,
    action: str,
    provenance_action: str,
) -> dict[str, Any]:
    source_node_id = str(source_node.get("id") or "").strip()
    target_node_id = str(target_node.get("id") or "").strip()
    source_data = source_node.get("data") if isinstance(source_node.get("data"), dict) else {}
    source_type = str(source_node.get("type") or "").strip()
    media = source_data.get("media") if isinstance(source_data.get("media"), dict) else source_data.get("storage")
    media = media if isinstance(media, dict) else {}
    active_version_id = _workflow_data_active_version_id(source_data)
    media_id = str(
        source_data.get("mediaId")
        or source_data.get("media_id")
        or media.get("id")
        or media.get("mediaId")
        or media.get("media_id")
        or ""
    ).strip()
    source_id = active_version_id or media_id or source_node_id
    default_source_handle = _workflow_material_source_default_handle(source_node)
    input_link = {
        "id": f"input-visual-handoff-{source_node_id}-{target_node_id}",
        "label": str(source_data.get("title") or source_data.get("assetName") or "视觉交接图"),
        "sourceType": "external_media" if source_type == "media.external" else "generated_media",
        "sourceId": source_id,
        "sourceNodeId": source_node_id,
        "sourceNodeType": source_type,
        "sourceHandle": _workflow_material_source_handle(
            source_node,
            f"{default_source_handle}_bottom" if default_source_handle else "",
        ),
        "targetNodeId": target_node_id,
        "targetNodeType": str(target_node.get("type") or ""),
        "targetSlot": _VISUAL_HANDOFF_SLOT,
        "slot": _VISUAL_HANDOFF_SLOT,
        "role": _VISUAL_HANDOFF_SLOT,
        "mediaPurpose": "visual_handoff",
        "preferredTargetSlot": _VISUAL_HANDOFF_SLOT,
        "assetKind": "visual_handoff",
        "assetType": "visual_handoff",
        "assetScope": "result",
        "visibilityScope": "node",
        "status": "linked" if active_version_id or media_id else "pending_generation",
        "linkAction": action,
        "versionMode": "active",
        "versionBinding": "active",
        "provenance": {
            "source": "system",
            "action": provenance_action,
            "createdAt": _now(),
        },
        **({"routeId": _node_route_id(target_node)} if _node_route_id(target_node) else {}),
        **({"workChainId": _node_work_chain_id(target_node)} if _node_work_chain_id(target_node) else {}),
        **({"segmentId": _node_segment_id(target_node)} if _node_segment_id(target_node) else {}),
    }
    if active_version_id:
        input_link["sourceVersionId"] = active_version_id
        input_link["mediaVersionId"] = active_version_id
    if media_id:
        input_link["mediaId"] = media_id
    if media:
        path = str(
            media.get("relativePath")
            or media.get("relative_path")
            or media.get("file")
            or media.get("path")
            or media.get("filePath")
            or media.get("file_path")
            or ""
        ).strip()
        if path:
            input_link["path"] = path
        input_link["mediaType"] = str(media.get("kind") or media.get("mediaType") or "image")
        input_link["mediaKind"] = input_link["mediaType"]
    _apply_workflow_input_link_contract(input_link, source_node)
    return input_link

def _workflow_prompt_has_visual_handoff_reference(
    workflow: dict[str, Any],
    target_node: dict[str, Any],
) -> bool:
    target_node_id = str(target_node.get("id") or "").strip()
    if not target_node_id:
        return False
    data = target_node.get("data") if isinstance(target_node.get("data"), dict) else {}
    input_links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
    for link in input_links:
        if not isinstance(link, dict):
            continue
        slot = str(link.get("targetSlot") or link.get("target_slot") or link.get("slot") or "").strip()
        source_node_id = str(link.get("sourceNodeId") or link.get("source_node_id") or link.get("source") or "").strip()
        if slot == _VISUAL_HANDOFF_SLOT and source_node_id:
            return True
    for edge in workflow.get("edges", []) if isinstance(workflow.get("edges"), list) else []:
        if not isinstance(edge, dict) or str(edge.get("target") or "").strip() != target_node_id:
            continue
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        is_material = str(data.get("kind") or "").strip() == "material"
        slot = str(data.get("targetSlot") or data.get("target_slot") or data.get("slot") or data.get("role") or "").strip()
        source_node_id = str(edge.get("source") or "").strip()
        if is_material and slot == _VISUAL_HANDOFF_SLOT and source_node_id:
            return True
    return False

def _workflow_prompt_has_visual_handoff_reference_from_source(
    workflow: dict[str, Any],
    target_node: dict[str, Any],
    source_node_id: str,
) -> bool:
    target_node_id = str(target_node.get("id") or "").strip()
    source_node_id = str(source_node_id or "").strip()
    if not target_node_id or not source_node_id:
        return False
    data = target_node.get("data") if isinstance(target_node.get("data"), dict) else {}
    input_links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
    for link in input_links:
        if not isinstance(link, dict):
            continue
        slot = str(link.get("targetSlot") or link.get("target_slot") or link.get("slot") or "").strip()
        link_source_node_id = str(
            link.get("sourceNodeId")
            or link.get("source_node_id")
            or link.get("source")
            or ""
        ).strip()
        if slot == _VISUAL_HANDOFF_SLOT and link_source_node_id == source_node_id:
            return True
    for edge in workflow.get("edges", []) if isinstance(workflow.get("edges"), list) else []:
        if not isinstance(edge, dict) or str(edge.get("target") or "").strip() != target_node_id:
            continue
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        is_material = str(data.get("kind") or "").strip() == "material"
        slot = str(data.get("targetSlot") or data.get("target_slot") or data.get("slot") or data.get("role") or "").strip()
        source_id = str(edge.get("source") or "").strip()
        if is_material and slot == _VISUAL_HANDOFF_SLOT and source_id == source_node_id:
            return True
    return False

def _workflow_link_visual_handoff_to_prompt(
    workflow: dict[str, Any],
    source_node: dict[str, Any],
    target_node: dict[str, Any],
    *,
    provenance_action: str,
) -> dict[str, Any]:
    source_node_id = str(source_node.get("id") or "").strip()
    target_node_id = str(target_node.get("id") or "").strip()
    if not source_node_id or not target_node_id or _is_user_locked_item(target_node):
        return {}
    slot = _VISUAL_HANDOFF_SLOT
    input_link = _workflow_visual_handoff_input_link(
        source_node,
        target_node,
        action="replace_slot",
        provenance_action=provenance_action,
    )
    route_id = _node_route_id(target_node)
    work_chain_id = _workflow_node_work_chain_id(workflow, target_node)
    segment_id = _node_segment_id(target_node)
    _upsert_workflow_material_edge(
        workflow,
        source_node=source_node,
        target_node=target_node,
        input_link=input_link,
        slot=slot,
        action="replace_slot",
        route_id=route_id,
        segment_id=segment_id,
        work_chain_id=work_chain_id,
    )
    data = target_node.setdefault("data", {})
    if not isinstance(data, dict):
        data = {}
        target_node["data"] = data
    data["inputLinks"] = _next_input_links(
        data.get("inputLinks"),
        input_link,
        action="replace_slot",
        slot=slot,
        scope="node",
        target_node_id=target_node_id,
        route_id=route_id,
        work_chain_id=work_chain_id,
    )
    reference_media_id = _link_reference_media_id(input_link)
    if reference_media_id:
        data["referenceMediaIds"] = _append_unique_string(data.get("referenceMediaIds"), reference_media_id)
    affected_node_ids = _workflow_downstream_node_ids(workflow, target_node_id)
    affected_node_ids.add(target_node_id)
    input_link["affectedNodeIds"] = sorted(affected_node_ids)
    return input_link

def _workflow_append_or_replace_node(workflow: dict[str, Any], node: dict[str, Any] | None) -> None:
    node_id = str((node or {}).get("id") or "").strip()
    if not node_id or not isinstance(node, dict):
        return
    nodes = workflow.setdefault("nodes", [])
    if not isinstance(nodes, list):
        nodes = []
        workflow["nodes"] = nodes
    for index, item in enumerate(nodes):
        if isinstance(item, dict) and str(item.get("id") or "").strip() == node_id:
            nodes[index] = node
            return
    nodes.append(node)

def _workflow_ensure_visual_handoff_source_edge(
    workflow: dict[str, Any],
    source_node_id: str,
    handoff_node_id: str,
) -> None:
    source_node_id = str(source_node_id or "").strip()
    handoff_node_id = str(handoff_node_id or "").strip()
    if not source_node_id or not handoff_node_id:
        return
    edge_id = f"dependency-{source_node_id}-{handoff_node_id}-visual-handoff"
    edge = {
        "id": edge_id,
        "source": source_node_id,
        "target": handoff_node_id,
        "sourceHandle": "visual_handoff",
        "targetHandle": "asset_context",
        "data": {
            "kind": "dependency",
            "role": "generates",
            "targetSlot": "asset_context",
            "locked": True,
        },
    }
    edges = workflow.setdefault("edges", [])
    if not isinstance(edges, list):
        edges = []
        workflow["edges"] = edges
    for index, item in enumerate(edges):
        if not isinstance(item, dict):
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        same_edge = (
            str(item.get("id") or "").strip() == edge_id
            or (
                str(item.get("source") or "").strip() == source_node_id
                and str(item.get("target") or "").strip() == handoff_node_id
                and str(data.get("kind") or "").strip() == "dependency"
            )
        )
        if same_edge:
            edges[index] = edge
            return
    edges.append(edge)

def _workflow_related_canvas_records(
    workflow: dict[str, Any],
    node_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    related_ids = {str(item or "").strip() for item in node_ids if str(item or "").strip()}
    if not related_ids:
        return [], []
    workflow_nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    node_by_id = {
        str(node.get("id") or "").strip(): node
        for node in workflow_nodes
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }
    related_nodes: list[dict[str, Any]] = []
    for node_id in sorted(related_ids):
        node = node_by_id.get(node_id)
        if not isinstance(node, dict):
            continue
        node_copy = copy.deepcopy(node)
        _ensure_saved_workflow_node_contract(node_copy)
        related_nodes.append(node_copy)
    related_edges: list[dict[str, Any]] = []
    workflow_edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    for edge in workflow_edges:
        if not isinstance(edge, dict):
            continue
        source_id = str(edge.get("source") or "").strip()
        target_id = str(edge.get("target") or "").strip()
        if source_id not in related_ids and target_id not in related_ids:
            continue
        edge_copy = copy.deepcopy(edge)
        _ensure_saved_workflow_edge_contract(edge_copy, node_by_id, workflow)
        related_edges.append(edge_copy)
    return related_nodes, related_edges
