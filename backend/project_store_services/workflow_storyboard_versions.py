# -*- coding: utf-8 -*-
"""分镜版本提交与变体选择领域。

这里承载分镜结果版本写入、版本元数据和变体选择；旧 workflows
API 通过直接名称绑定保持兼容。
"""

from __future__ import annotations

from .canvas_store_queries import read_card_results
from .canvas_store_results import delete_card_result_version
from .media_files import _image_media_from_file_info
from .media_files import _stored_media_path
from .production_status import update_episode_production_status
from .projects import _touch_project_meta
from .store_core import _JSON_WRITE_LOCK
from .store_core import _now
from .workflow_contract import _STORYBOARD_REFERENCE_NODE_TYPES
from .workflow_contract import _assert_canvas_mutation_does_not_return_workflow
from .workflow_contract import _workflow_mutation_returns_production_status
from .workflow_contract import _workflow_node
from .workflow_projection import get_canvas_workflow_projection
from typing import Any
import copy
import traceback
import uuid

from .agent_sessions import (
    _persistent_media_data_removed,
)
from .canvas_store_database import card_dir, card_root
from .canvas_store_results import commit_canvas_result_v4
from .canvas_store_queries import (
    episode_canvas_exists,
    read_canvas_card_record_v4,
    read_canvas_task_context_v4,
)
from .perf_logging import (
    canvas_perf_elapsed_ms,
    canvas_perf_log,
    canvas_perf_start,
)
from .store_core import _display_time
from .store_core import (
    _emit_agent_event,
    _read_json,
)
from .workflow_asset_resolution import _workflow_canvas_project_asset_versions
from .workflow_contract import (
    _VISUAL_HANDOFF_SLOT,
    _apply_workflow_input_link_contract,
    _normalize_workflow_work_chain_route_fields,
    _workflow_active_version_has_usable_media,
    _workflow_data_active_version_id,
    _workflow_input_link_version_binding,
    _workflow_is_video_task_type,
    _workflow_meaningful_output_title,
    _workflow_node_status_after_input_availability_change,
    _workflow_status_with_usable_active_media,
    _workflow_version_has_usable_media,
)
from .workflow_storyboard_prompts import _generated_version_preview
from .workflow_generation_config import (
    _merge_version_payload_snapshots,
    _workflow_version_payload_snapshots,
)
from .workflow_input_resolution import (
    _resolve_workflow_node_inputs_from_workflow,
    _workflow_explicit_storyboard_reference_node_ids,
    _workflow_visual_handoff_node_is_generated,
)
from .workflow_planning_lifecycle import (
    _safe_episode_id,
)
from .workflow_projection import (
    _workflow_state,
)
from .workflow_visual_handoff import (
    sync_visual_handoff_cross_episode_link,
)
from .workflow_contract import (
    _VISUAL_HANDOFF_TARGET_NODE_TYPES,
)
from pathlib import (
    Path,
)

import json

from .workflow_contract import (
    _append_unique_string,
)
from .workflow_input_resolution import (
    _link_reference_media_id,
)

def _add_storyboard_version_unlocked(
    project_id: str,
    episode_id: str,
    node_id: str,
    version_type: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    versions = read_card_results(project_id, episode_id, node_id)
    workflow = _workflow_result_commit_context(project_id, episode_id, node_id)
    node = next((item for item in workflow.get("nodes", []) if item.get("id") == node_id), {})
    node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
    title = str((metadata or {}).get("title") or node_data.get("title") or "生成版本")
    meaningful_title = _workflow_meaningful_output_title(title)
    summary = str((metadata or {}).get("summary") or node_data.get("summary") or "")
    metadata_row = metadata or {}
    payload = copy.deepcopy(metadata_row.get("payload") if isinstance(metadata_row.get("payload"), dict) else {})
    version_input_snapshot = _workflow_result_commit_input_snapshot(
        project_id,
        episode_id,
        workflow,
        node_id,
    )
    payload = _merge_version_payload_snapshots(
        payload,
        _workflow_version_payload_snapshots(
            project_id,
            episode_id,
            workflow,
            node_id,
            version_type=version_type,
            prompt_payload=payload,
            input_snapshot=version_input_snapshot,
        ),
    )
    version_is_image_edit = (
        str(metadata_row.get("source") or "") == "model-image-edit"
        or str(payload.get("generationStage") or payload.get("generation_stage") or "") == "storyboard_image_edit"
        or str(payload.get("imageGenerationMode") or payload.get("image_generation_mode") or "").strip().lower() == "image_edit"
        or str(payload.get("imageOperation") or payload.get("image_operation") or "").strip().lower() == "edit"
    )
    if "referenceMediaIdsSnapshot" in payload:
        if version_is_image_edit:
            payload["inputReferenceMediaIdsSnapshot"] = copy.deepcopy(payload.get("referenceMediaIdsSnapshot") or [])
        else:
            payload["referenceMediaIds"] = copy.deepcopy(payload.get("referenceMediaIdsSnapshot") or [])
    if "assetRefsSnapshot" in payload:
        snapshot_asset_refs = copy.deepcopy(payload.get("assetRefsSnapshot") or [])
        if not version_is_image_edit:
            if snapshot_asset_refs:
                payload["assetRefs"] = snapshot_asset_refs
            else:
                payload.pop("assetRefs", None)
    if "referenceManifestSnapshot" in payload and not version_is_image_edit:
        payload["referenceManifest"] = copy.deepcopy(payload.get("referenceManifestSnapshot") or [])
    version_status = str((metadata or {}).get("status") or "ready")
    version_failed_or_pending = version_status in {"failed", "blocked", "cancelled", "canceled", "processing"}
    preview = metadata_row.get("preview")
    if not version_failed_or_pending and not preview and not metadata_row.get("media"):
        preview = _generated_version_preview(version_type, title, payload)
    version = {
        "id": f"{version_type}-{uuid.uuid4().hex[:8]}",
        "nodeId": node_id,
        "title": title,
        "status": version_status,
        "createdAt": _display_time(_now()),
        "summary": summary,
        "source": (metadata or {}).get("source") or "local-generation",
        "payload": payload,
    }
    if preview:
        version["preview"] = preview
    for key in ("media", "workpageMedia", "model", "provider", "generationDebug", "generationError"):
        if (metadata or {}).get(key) is not None:
            version[key] = _persistent_media_data_removed((metadata or {}).get(key))
    versions.append(version)
    source_node = _workflow_node(workflow, node_id) or {}
    source_type = str(source_node.get("type") or "")
    source_data = source_node.get("data") if isinstance(source_node.get("data"), dict) else {}
    source_is_reference_image = source_type == "storyboard.image"
    source_is_visual_handoff = _workflow_visual_handoff_node_is_generated(source_node)
    source_is_video_task = _workflow_is_video_task_type(source_type)
    version_failed = version_status in {"failed", "blocked", "cancelled", "canceled"}
    reference_ready = version_status != "processing" and not version_failed
    version_has_media = bool(version.get("media"))
    previous_active_version = next(
        (
            item
            for item in versions
            if isinstance(item, dict)
            and str(item.get("id") or "") == _workflow_data_active_version_id(source_data)
        ),
        {},
    )
    previous_active_is_usable = _workflow_version_has_usable_media(previous_active_version)
    version_became_active = reference_ready and version_has_media
    active_version_id = (
        version["id"]
        if version_became_active
        else _workflow_data_active_version_id(source_data)
        if previous_active_is_usable
        else ""
    )
    affected_video_task_ids: set[str] = set()
    before_node_signatures = {
        str(item.get("id") or ""): json.dumps(item, ensure_ascii=False, sort_keys=True)
        for item in workflow.get("nodes", [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    workflow_version: Any = workflow.get("version")
    if source_is_reference_image:
        for candidate in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
            if not isinstance(candidate, dict) or not _workflow_is_video_task_type(str(candidate.get("type") or "")):
                continue
            candidate_id = str(candidate.get("id") or "").strip()
            if candidate_id and node_id in _workflow_explicit_storyboard_reference_node_ids(workflow, candidate):
                affected_video_task_ids.add(candidate_id)
    for node in workflow.get("nodes", []):
        if node.get("id") == node_id:
            node_data = node.setdefault("data", {})
            if not isinstance(node_data, dict):
                node_data = {}
                node["data"] = node_data
            if version_became_active:
                node_data["activeVersionId"] = version["id"]
                node_data["activeMediaVersionId"] = version["id"]
                node_data["mediaVersionId"] = version["id"]
                node_data["sourceVersionId"] = version["id"]
                node_data["media"] = _persistent_media_data_removed(version.get("media"))
                if meaningful_title and not _workflow_meaningful_output_title(node_data.get("title")):
                    node_data["title"] = meaningful_title
                    if not _workflow_meaningful_output_title(node_data.get("assetName")):
                        node_data["assetName"] = meaningful_title
            elif not previous_active_is_usable:
                node_data.pop("activeVersionId", None)
                node_data.pop("activeMediaVersionId", None)
                node_data.pop("mediaVersionId", None)
            node_data["status"] = (
                "ready"
                if version_became_active
                else _workflow_status_with_usable_active_media(node_data.get("status"))
                if previous_active_is_usable
                else "failed"
                if version_failed
                else "running"
                if version_status == "processing"
                else "ready"
            )
            node_data["summary"] = summary or node_data.get("summary") or "生成版本已写入。"
            node_data_patch = (
                metadata_row.get("nodeDataPatch")
                if isinstance(metadata_row.get("nodeDataPatch"), dict)
                else {}
            )
            for patch_key, patch_value in node_data_patch.items():
                if patch_key == "provenance" and isinstance(patch_value, dict):
                    current_provenance = (
                        node_data.get("provenance")
                        if isinstance(node_data.get("provenance"), dict)
                        else {}
                    )
                    node_data["provenance"] = {
                        **copy.deepcopy(current_provenance),
                        **copy.deepcopy(patch_value),
                    }
                else:
                    node_data[str(patch_key)] = copy.deepcopy(patch_value)
            if meaningful_title and not _workflow_meaningful_output_title(node_data.get("title")):
                node_data["title"] = meaningful_title
                if not _workflow_meaningful_output_title(node_data.get("assetName")):
                    node_data["assetName"] = meaningful_title
        elif source_is_reference_image:
            node_type = str(node.get("type") or "")
            if _workflow_is_video_task_type(node_type):
                data = node.setdefault("data", {})
                if not isinstance(data, dict):
                    data = {}
                    node["data"] = data
                links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
                active_link_updated = False
                reference_snapshot_changed = False
                for link in links:
                    if not isinstance(link, dict):
                        continue
                    if str(link.get("sourceNodeId") or link.get("source_node_id") or "") != node_id:
                        continue
                    _apply_workflow_input_link_contract(link, source_node)
                    if _workflow_input_link_version_binding(link) == "pinned":
                        continue
                    if version_became_active:
                        active_link_updated = True
                        link["status"] = "linked"
                        link["sourceVersionId"] = version["id"]
                        link["mediaVersionId"] = version["id"]
                    elif previous_active_is_usable and active_version_id:
                        before_pointer = (
                            str(link.get("status") or ""),
                            str(link.get("sourceVersionId") or ""),
                            str(link.get("mediaVersionId") or ""),
                        )
                        link["status"] = "linked"
                        link["sourceVersionId"] = active_version_id
                        link["mediaVersionId"] = active_version_id
                        after_pointer = (
                            str(link.get("status") or ""),
                            str(link.get("sourceVersionId") or ""),
                            str(link.get("mediaVersionId") or ""),
                        )
                        if after_pointer != before_pointer:
                            reference_snapshot_changed = True
                    else:
                        active_link_updated = True
                        link["status"] = "pending_generation"
                        link["sourceVersionId"] = version["id"]
                        link["mediaVersionId"] = version["id"]
                if reference_snapshot_changed:
                    affected_video_task_ids.add(str(node.get("id") or ""))
                if active_link_updated:
                    affected_video_task_ids.add(str(node.get("id") or ""))
                    data["status"] = _workflow_node_status_after_input_availability_change(
                        data.get("status"),
                        input_ready=version_became_active,
                    )
                    data["summary"] = (
                        data.get("summary")
                        or ("参考图已准备，可继续生成视频候选。" if version_became_active else "参考图生成中，视频任务等待输入。")
                    )
        elif source_is_visual_handoff:
            node_type = str(node.get("type") or "")
            if node_type not in _VISUAL_HANDOFF_TARGET_NODE_TYPES:
                continue
            data = node.setdefault("data", {})
            if not isinstance(data, dict):
                data = {}
                node["data"] = data
            links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
            link_updated = False
            for link in links:
                if not isinstance(link, dict):
                    continue
                if str(link.get("sourceNodeId") or link.get("source_node_id") or "") != node_id:
                    continue
                slot = str(link.get("targetSlot") or link.get("slot") or "").strip()
                if slot != _VISUAL_HANDOFF_SLOT:
                    continue
                _apply_workflow_input_link_contract(link, source_node)
                if _workflow_input_link_version_binding(link) == "pinned":
                    continue
                link_updated = True
                if version_became_active:
                    link["status"] = "linked"
                    link["sourceVersionId"] = version["id"]
                    link["mediaVersionId"] = version["id"]
                    if version.get("media"):
                        media = version.get("media")
                        if isinstance(media, dict):
                            link["mediaId"] = str(media.get("id") or link.get("mediaId") or "")
                            link["mediaType"] = str(media.get("kind") or media.get("mediaType") or "image")
                            link["mediaKind"] = link["mediaType"]
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
                                link["path"] = path
                elif previous_active_is_usable and active_version_id:
                    link["status"] = "linked"
                    link["sourceVersionId"] = active_version_id
                    link["mediaVersionId"] = active_version_id
                else:
                    link["status"] = "pending_generation"
                    link["sourceVersionId"] = version["id"]
                    link["mediaVersionId"] = version["id"]
            if link_updated:
                refs: list[str] = []
                for link in links:
                    if isinstance(link, dict):
                        refs = _append_unique_string(refs, _link_reference_media_id(link))
                data["referenceMediaIds"] = refs
                data["summary"] = data.get("summary") or (
                    "视觉交接图已准备，可用于判断本工作链开头空间连续性。"
                    if version_became_active
                    else "视觉交接图生成中，等待空间连续性参考。"
                )
        elif source_is_video_task:
            node_type = str(node.get("type") or "")
            if node_type != "video.result":
                continue
            result_node_id = str(node.get("id") or "").strip()
            data = node.setdefault("data", {})
            if not isinstance(data, dict):
                data = {}
                node["data"] = data
            links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
            result_versions = versions if result_node_id == node_id else read_card_results(project_id, episode_id, result_node_id)
            result_active_version_id = _workflow_data_active_version_id(data)
            preserve_result_active = bool(
                not (reference_ready and version.get("media"))
                and result_active_version_id
                and _workflow_active_version_has_usable_media(result_versions, data)
            )
            linked_to_source = (
                str(data.get("resultOfNodeId") or data.get("sourceNodeId") or "") == node_id
                or any(
                    isinstance(link, dict)
                    and str(link.get("sourceNodeId") or link.get("source_node_id") or "") == node_id
                    for link in links
                )
            )
            if not linked_to_source:
                continue
            data["resultOfNodeId"] = node_id
            data["sourceNodeId"] = node_id
            data["sourceVersionId"] = result_active_version_id if preserve_result_active else version["id"]
            if meaningful_title and not _workflow_meaningful_output_title(data.get("title")):
                data["title"] = meaningful_title
                if not _workflow_meaningful_output_title(data.get("assetName")):
                    data["assetName"] = meaningful_title
            for link in links:
                if not isinstance(link, dict):
                    continue
                if str(link.get("sourceNodeId") or link.get("source_node_id") or "") != node_id:
                    continue
                link["sourceType"] = "generated_video"
                link["sourceNodeType"] = source_type
                link["targetNodeId"] = str(node.get("id") or "")
                link["targetNodeType"] = "video.result"
                link["targetSlot"] = "video_result"
                link["slot"] = "video_result"
                if preserve_result_active:
                    link["status"] = "linked"
                    link["sourceVersionId"] = result_active_version_id
                    link["mediaVersionId"] = result_active_version_id
                else:
                    link["status"] = "linked" if reference_ready else "failed" if version_failed else "pending_generation"
                    link["sourceVersionId"] = version["id"]
                    link["mediaVersionId"] = version["id"]
            if reference_ready and version.get("media"):
                data["activeVersionId"] = version["id"]
                data["activeMediaVersionId"] = version["id"]
                data["mediaVersionId"] = version["id"]
                data["media"] = _persistent_media_data_removed(version.get("media"))
                data["status"] = "ready"
                data["summary"] = summary or "视频片段已生成。"
                if meaningful_title and not _workflow_meaningful_output_title(data.get("title")):
                    data["title"] = meaningful_title
                    if not _workflow_meaningful_output_title(data.get("assetName")):
                        data["assetName"] = meaningful_title
            elif preserve_result_active:
                data["status"] = _workflow_status_with_usable_active_media(data.get("status"))
                data["summary"] = data.get("summary") or "视频片段已生成。"
            elif version_failed:
                data.pop("activeVersionId", None)
                data.pop("activeMediaVersionId", None)
                data.pop("mediaVersionId", None)
                data.pop("media", None)
                data["status"] = "failed"
                data["summary"] = summary or str(version.get("generationError") or "视频生成失败。")
            elif not reference_ready:
                data["status"] = "waiting"
                data["summary"] = summary or "视频生成正在进行，等待视频片段。"
    patched_nodes = []
    save_result: dict[str, Any] = {}
    for item in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
        if not isinstance(item, dict):
            continue
        current_id = str(item.get("id") or "")
        if not current_id:
            continue
        current_signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if before_node_signatures.get(current_id) != current_signature:
            patched_nodes.append(copy.deepcopy(item))
    result_commit_tasks: list[dict[str, Any]] = []
    raw_commit_tasks = metadata_row.get("canvasTasks") if isinstance(metadata_row.get("canvasTasks"), list) else []
    for raw_task in raw_commit_tasks:
        if not isinstance(raw_task, dict):
            continue
        task_row = copy.deepcopy(raw_task)
        task_row["nodeId"] = str(task_row.get("nodeId") or task_row.get("node_id") or node_id)
        task_row["versionId"] = str(task_row.get("versionId") or task_row.get("version_id") or version.get("id") or "")
        task_result = task_row.get("result") if isinstance(task_row.get("result"), dict) else {}
        task_result = copy.deepcopy(task_result)
        task_result.setdefault("version", _persistent_media_data_removed(version))
        if version.get("media"):
            task_result.setdefault("media", _persistent_media_data_removed(version.get("media")))
        task_row["result"] = task_result
        result_commit_tasks.append(task_row)
    changed_resources = ["canvas_node", "canvas_version"]
    if result_commit_tasks:
        changed_resources.append("canvas_task")
    save_result = commit_canvas_result_v4(
        project_id,
        episode_id,
        node_id=node_id,
        versions=versions,
        active_version_id=active_version_id,
        nodes=patched_nodes,
        tasks=result_commit_tasks,
        changed_resources=changed_resources,
    )
    workflow_version = save_result.get("workflowVersion") or workflow_version
    workflow["version"] = workflow_version
    if workflow_version:
        version["workflowVersion"] = workflow_version
    for key in ("txId", "seq", "revision", "baseRevision", "opType", "records", "changedResources"):
        if save_result.get(key) is not None:
            version[key] = copy.deepcopy(save_result.get(key))
    _emit_canvas_result_commit_event(
        project_id,
        episode_id,
        node_id,
        version,
        patched_nodes,
        result_commit_tasks,
        save_result,
    )
    if source_is_visual_handoff and version_became_active:
        try:
            cross_episode_link = sync_visual_handoff_cross_episode_link(
                project_id,
                episode_id,
                source_node,
                version,
                allow_auto_link=not previous_active_is_usable,
            )
            if isinstance(cross_episode_link, dict) and cross_episode_link:
                version["crossEpisodeLink"] = cross_episode_link
        except Exception:
            pass
    return version


def _select_workflow_variant_unlocked(
    project_id: str,
    episode_id: str,
    node_id: str,
    version_id: str,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "选择画布候选版本")
    workflow = read_canvas_task_context_v4(
        project_id,
        episode_id,
        node_id,
        detail="full",
        include_input_consumers=True,
        consumer_source_node_ids={node_id},
    )
    versions = read_card_results(project_id, episode_id, node_id)
    version = next(
        (
            item
            for item in versions
            if isinstance(item, dict)
            and str(item.get("id") or "") == str(version_id)
            and str(item.get("nodeId") or "") == str(node_id)
        ),
        None,
    )
    if not version:
        raise FileNotFoundError("版本不存在")

    node = _workflow_node(workflow, node_id)
    if not node:
        raise FileNotFoundError("节点不存在")
    node_type = str(node.get("type") or "")
    is_video_node = _workflow_is_video_task_type(node_type)
    is_image_node = node_type == "storyboard.image"
    if not (is_video_node or is_image_node):
        raise ValueError("只有分镜图或视频节点可以选择 winner")

    selected_at = _display_time(_now())
    selection_reason = str(reason or "").strip()
    if not selection_reason or selection_reason == "manual_winner_selected":
        raise ValueError("请选择 winner 前填写选择原因")
    data = node.setdefault("data", {})
    if not isinstance(data, dict):
        data = {}
        node["data"] = data
    quality_blocker = _workflow_variant_quality_blocker(
        project_id,
        episode_id,
        node_id,
        version_id,
        data,
        version,
    )
    if quality_blocker:
        messages = quality_blocker.get("messages") if isinstance(quality_blocker, dict) else []
        message = "；".join(str(item) for item in messages[:3] if str(item).strip())
        suffix = f"：{message}" if message else ""
        raise ValueError(f"候选存在未豁免的质检 blocker，不能设为 winner{suffix}")
    provenance = {
        "source": "user",
        "action": "variant_selected",
        "selectedAt": selected_at,
        "nodeId": node_id,
        "versionId": version_id,
        "routeId": node.get("routeId") or (node.get("data") if isinstance(node.get("data"), dict) else {}).get("routeId"),
        "segmentId": node.get("segmentId") or (node.get("data") if isinstance(node.get("data"), dict) else {}).get("segmentId"),
    }

    data["activeVersionId"] = version_id
    data["activeMediaVersionId"] = version_id
    data["mediaVersionId"] = version_id
    data["winnerVersionId"] = version_id
    data["selectionReason"] = selection_reason
    data["selectedAt"] = selected_at
    data["variantSelection"] = {
        "versionId": version_id,
        "reason": selection_reason,
        "selectedAt": selected_at,
        "provenance": provenance,
    }
    data["status"] = "succeeded"
    data["summary"] = str(version.get("summary") or data.get("summary") or "候选 winner 已选择。")
    patched_node_ids: set[str] = {node_id}

    if is_video_node:
        selected_media = version.get("media") if isinstance(version.get("media"), dict) else None
        for result_node in (
            workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []
        ):
            if not isinstance(result_node, dict) or str(result_node.get("type") or "") != "video.result":
                continue
            result_node_id = str(result_node.get("id") or "").strip()
            if not result_node_id:
                continue
            result_data = result_node.setdefault("data", {})
            if not isinstance(result_data, dict):
                result_data = {}
                result_node["data"] = result_data
            links = result_data.get("inputLinks") if isinstance(result_data.get("inputLinks"), list) else []
            # Winner propagation follows explicit result/source links only.
            # Asset groups and route membership stop mattering after work-chain generation.
            linked_to_source = (
                str(result_data.get("resultOfNodeId") or result_data.get("sourceNodeId") or "") == node_id
                or any(
                    isinstance(link, dict)
                    and str(link.get("sourceNodeId") or link.get("source_node_id") or "") == node_id
                    for link in links
                )
            )
            if not linked_to_source:
                continue
            result_data["resultOfNodeId"] = node_id
            result_data["sourceNodeId"] = node_id
            result_data["sourceVersionId"] = version_id
            result_data["activeVersionId"] = version_id
            result_data["activeMediaVersionId"] = version_id
            result_data["mediaVersionId"] = version_id
            result_data["winnerVersionId"] = version_id
            result_data["selectionReason"] = selection_reason
            result_data["selectedAt"] = selected_at
            result_data["status"] = "succeeded"
            result_data["summary"] = str(version.get("summary") or result_data.get("summary") or "候选 winner 已选择。")
            if selected_media:
                result_data["media"] = _persistent_media_data_removed(selected_media)
            else:
                result_data.pop("media", None)
            result_data.pop("storage", None)
            for link in links:
                if not isinstance(link, dict):
                    continue
                if str(link.get("sourceNodeId") or link.get("source_node_id") or "") != node_id:
                    continue
                link["sourceType"] = "generated_video"
                link["sourceNodeType"] = node_type
                link["targetNodeId"] = result_node_id
                link["targetNodeType"] = "video.result"
                link["targetSlot"] = "video_result"
                link["slot"] = "video_result"
                link["status"] = "linked"
                link["sourceVersionId"] = version_id
                link["mediaVersionId"] = version_id
            patched_node_ids.add(result_node_id)

    version["winner"] = True
    version["selectionReason"] = selection_reason
    version["selectedAt"] = selected_at
    version["selectionProvenance"] = provenance
    for item in versions:
        if (
            isinstance(item, dict)
            and str(item.get("nodeId") or "") == str(node_id)
            and str(item.get("id") or "") != str(version_id)
        ):
            item.pop("winner", None)
            item.pop("selectionReason", None)
            item.pop("selectedAt", None)
            item.pop("selectionProvenance", None)

    return_production_status = (
        is_video_node and _workflow_mutation_returns_production_status(payload)
    )
    patched_nodes_for_save = [
        copy.deepcopy(item)
        for item in (
            workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []
        )
        if isinstance(item, dict) and str(item.get("id") or "").strip() in patched_node_ids
    ]
    workflow_result = commit_canvas_result_v4(
        project_id,
        episode_id,
        node_id=node_id,
        versions=versions,
        active_version_id=version_id,
        nodes=patched_nodes_for_save,
        changed_resources=["canvas_node", "canvas_version"],
    )
    workflow["version"] = workflow_result.get("workflowVersion") or workflow.get("version")
    production_status = None
    if return_production_status:
        try:
            status_result = update_episode_production_status(project_id, episode_id)
            production_status = status_result.get("status") if isinstance(status_result, dict) else None
        except Exception:
            print(traceback.format_exc(), flush=True)
            production_status = None

    patched_nodes = [
        copy.deepcopy(item)
        for item in (
            workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []
        )
        if isinstance(item, dict) and str(item.get("id") or "").strip() in patched_node_ids
    ]
    result = {
        "success": True,
        "workflowVersion": workflow_result.get("workflowVersion"),
        "version": copy.deepcopy(version),
        "node": copy.deepcopy(node),
        "nodes": patched_nodes,
        "productionStatus": production_status,
        "txId": workflow_result.get("txId"),
        "seq": workflow_result.get("seq"),
        "revision": workflow_result.get("revision"),
        "opType": workflow_result.get("opType"),
        "records": workflow_result.get("records"),
        "changedResources": ["canvas_node", "canvas_version"] + (["episode_production_status"] if production_status else []),
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id},
    }
    if not production_status:
        result.pop("productionStatus", None)
    return result


def _variant_quality_results_path(project_id: str, episode_id: str, node_id: str) -> Path:
    return card_dir(project_id, _safe_episode_id(episode_id), node_id) / "results" / "quality_results.json"


def _read_variant_quality_results(project_id: str, episode_id: str, node_id: str = "") -> list[dict[str, Any]]:
    if not episode_canvas_exists(project_id, episode_id):
        return []
    node_id = str(node_id or "").strip()
    paths = (
        [_variant_quality_results_path(project_id, episode_id, node_id)]
        if node_id
        else sorted(card_root(project_id, episode_id).glob("*/results/quality_results.json"))
    )
    results: list[dict[str, Any]] = []
    for path in paths:
        data = _read_json(path, [])
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            data = data.get("results")
        if isinstance(data, list):
            results.extend(copy.deepcopy(item) for item in data if isinstance(item, dict))
    return results


def list_storyboard_versions(project_id: str, episode_id: str, node_id: str) -> dict[str, Any]:
    local_versions = read_card_results(project_id, episode_id, node_id)
    try:
        node = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
    except FileNotFoundError:
        node = None
    asset_versions = _workflow_canvas_project_asset_versions(
        project_id,
        episode_id,
        node_id,
        node,
    )
    if not asset_versions:
        return {"versions": local_versions}
    seen_ids = {str(item.get("id") or "") for item in asset_versions}
    merged = asset_versions + [
        item
        for item in local_versions
        if str(item.get("id") or "") not in seen_ids
    ]
    return {"versions": merged}


def add_storyboard_version(
    project_id: str,
    episode_id: str,
    node_id: str,
    version_type: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _JSON_WRITE_LOCK:
        return _add_storyboard_version_unlocked(
            project_id,
            episode_id,
            node_id,
            version_type,
            metadata,
        )


def _workflow_result_commit_context(
    project_id: str,
    episode_id: str,
    node_id: str,
) -> dict[str, Any]:
    perf_started_at = canvas_perf_start()
    workflow = read_canvas_task_context_v4(
        project_id,
        episode_id,
        node_id,
        detail="full",
        include_input_consumers=True,
        consumer_source_node_ids={node_id},
    )
    _normalize_workflow_work_chain_route_fields(workflow)
    workflow.setdefault("episodeId", episode_id)
    workflow["state"] = _workflow_state(
        project_id,
        episode_id,
        workflow,
        "result_commit_context",
    )
    canvas_perf_log(
        "workflow_result_commit_context",
        projectId=project_id,
        episodeId=episode_id,
        nodeId=node_id,
        durationMs=canvas_perf_elapsed_ms(perf_started_at),
        nodeCount=len(workflow.get("nodes")) if isinstance(workflow.get("nodes"), list) else 0,
        edgeCount=len(workflow.get("edges")) if isinstance(workflow.get("edges"), list) else 0,
    )
    return workflow


def _workflow_result_commit_input_snapshot(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_id: str,
) -> dict[str, Any]:
    try:
        snapshot = _resolve_workflow_node_inputs_from_workflow(
            project_id,
            workflow,
            episode_id,
            node_id,
        )
        return snapshot if isinstance(snapshot, dict) else {}
    except Exception:
        pass
        return {}


def _emit_canvas_result_commit_event(
    project_id: str,
    episode_id: str,
    node_id: str,
    version: dict[str, Any],
    patched_nodes: list[dict[str, Any]],
    result_commit_tasks: list[dict[str, Any]],
    save_result: dict[str, Any],
) -> None:
    try:
        nodes = [
            copy.deepcopy(item)
            for item in patched_nodes
            if isinstance(item, dict) and str(item.get("id") or "")
        ]
        tasks = [
            copy.deepcopy(item)
            for item in result_commit_tasks
            if isinstance(item, dict) and str(item.get("id") or "")
        ]
        changed_resources = save_result.get("changedResources")
        if not isinstance(changed_resources, list):
            changed_resources = ["canvas_node", "canvas_version"]
            if tasks:
                changed_resources.append("canvas_task")
        payload: dict[str, Any] = {
            "action": "canvas_result_committed",
            "projectId": project_id,
            "episodeId": episode_id,
            "nodeId": node_id,
            "versionId": str(version.get("id") or ""),
            "version": _persistent_media_data_removed(version),
            "workflowOmitted": True,
            "changedResources": copy.deepcopy(changed_resources),
        }
        if nodes:
            payload["nodes"] = nodes
            target_node = next(
                (
                    item
                    for item in nodes
                    if isinstance(item, dict) and str(item.get("id") or "") == node_id
                ),
                nodes[0],
            )
            payload["node"] = copy.deepcopy(target_node)
        if tasks:
            payload["tasks"] = tasks
        for key in (
            "txId",
            "seq",
            "revision",
            "baseRevision",
            "opType",
            "records",
            "workflowVersion",
        ):
            if save_result.get(key) is not None:
                payload[key] = copy.deepcopy(save_result.get(key))
        _emit_agent_event("project_changed", payload)
    except Exception:
        print(traceback.format_exc(), flush=True)


def _variant_quality_messages(result: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for key in ("blockingIssues", "blockers", "errors"):
        value = result.get(key)
        rows = value if isinstance(value, list) else [value] if value else []
        for row in rows:
            if isinstance(row, dict):
                text = str(
                    row.get("message")
                    or row.get("title")
                    or row.get("reason")
                    or row.get("summary")
                    or ""
                ).strip()
            else:
                text = str(row or "").strip()
            if text and text not in messages:
                messages.append(text)
    return messages


def _quality_result_matches_variant(
    result: dict[str, Any],
    node_id: str,
    version_id: str,
    *,
    assume_current_version: bool = False,
) -> bool:
    result_node_id = str(result.get("nodeId") or result.get("node_id") or "").strip()
    if result_node_id and result_node_id != node_id:
        return False
    result_version_id = str(result.get("versionId") or result.get("version_id") or "").strip()
    if result_version_id:
        return result_version_id == version_id
    return assume_current_version


def _workflow_variant_quality_blocker(
    project_id: str,
    episode_id: str,
    node_id: str,
    version_id: str,
    node_data: dict[str, Any],
    version: dict[str, Any],
) -> dict[str, Any] | None:
    sidecar_result: dict[str, Any] | None = None
    for result in _read_variant_quality_results(project_id, episode_id, node_id):
        if isinstance(result, dict) and _quality_result_matches_variant(result, node_id, version_id):
            sidecar_result = result

    candidates: list[tuple[dict[str, Any], bool]] = []

    def add_candidate(value: Any, *, assume_current_version: bool = False) -> None:
        if isinstance(value, dict):
            candidates.append((value, assume_current_version))

    if sidecar_result:
        add_candidate(sidecar_result, assume_current_version=True)
    else:
        add_candidate(version.get("qualityResult"), assume_current_version=True)
        add_candidate(version.get("quality"), assume_current_version=True)
        add_candidate(version.get("qualityReview"), assume_current_version=True)

        quality = node_data.get("quality") if isinstance(node_data.get("quality"), dict) else {}
        add_candidate(quality.get("lastVariantQualityResult"))
        add_candidate(quality.get("variantQualityResult"))

    for result, assume_current_version in candidates:
        if result.get("reportOnly") is True:
            continue
        if not _quality_result_matches_variant(
            result,
            node_id,
            version_id,
            assume_current_version=assume_current_version,
        ):
            continue
        status = str(result.get("status") or result.get("result") or "").strip().lower()
        messages = _variant_quality_messages(result)
        is_blocked = status in {"failed", "blocked"} or bool(messages)
        if not is_blocked:
            continue
        waiver_reason = str(result.get("waiverReason") or result.get("waiver_reason") or "").strip()
        if bool(result.get("waived") or result.get("exempted")) and waiver_reason:
            continue
        if bool(result.get("waived") or result.get("exempted")) and not waiver_reason:
            messages = messages or ["质检 blocker 已标记豁免但缺少豁免原因"]
        return {
            "status": status or "blocked",
            "messages": messages or [f"质检状态：{status or 'blocked'}"],
        }
    return None




def _is_storyboard_result_image_node(node: dict[str, Any] | None) -> bool:
    if not isinstance(node, dict) or str(node.get("type") or "") not in _STORYBOARD_REFERENCE_NODE_TYPES:
        return False
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    asset_scope = str(data.get("assetScope") or data.get("asset_scope") or "").strip().lower()
    return asset_scope in {"", "result"}


def select_workflow_variant(
    project_id: str,
    episode_id: str,
    node_id: str,
    version_id: str,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _JSON_WRITE_LOCK:
        return _select_workflow_variant_unlocked(project_id, episode_id, node_id, version_id, reason, payload)


def delete_storyboard_version(project_id: str, episode_id: str, node_id: str, version_id: str) -> dict[str, Any]:
    versions = read_card_results(project_id, episode_id, node_id)
    node_versions = [item for item in versions if item.get("nodeId") == node_id]
    target = next((item for item in node_versions if item.get("id") == version_id), None)
    if not target:
        raise FileNotFoundError("版本不存在")
    if len(node_versions) <= 1:
        raise ValueError("至少保留一个版本")
    delete_result = delete_card_result_version(project_id, episode_id, node_id, version_id)
    _touch_project_meta(project_id)
    return {
        "success": True,
        "episodeId": episode_id,
        "nodeId": node_id,
        "versionId": version_id,
        "deletedVersion": copy.deepcopy(target),
        **delete_result,
    }
