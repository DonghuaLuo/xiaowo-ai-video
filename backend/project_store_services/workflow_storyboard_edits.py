# -*- coding: utf-8 -*-
"""分镜图编辑、版本元数据和结果版本切换领域。

旧 workflows API 通过直接名称绑定保留；未闭合的画布契约依赖
通过运行时兼容模块解析，以保留既有 patch seam。
"""

from __future__ import annotations

import copy
import re
from .image_prompt_guidance import uses_original_image_reference
from utils.frame_references import is_frame_image
from .agent_sessions import (
    _persistent_media_data_removed,
)
from .assets import (
    _ASSET_CHARACTER_HEADED_TURNAROUND,
    _ASSET_CHARACTER_HEADLESS_TURNAROUND,
    _asset_generation_aspect_ratio,
    _asset_generation_prompt,
    _asset_generation_resolution,
    _asset_media_version,
    _asset_store_path,
    _ensure_asset_media_versions,
    _normalize_asset_item_for_storage,
    _normalize_media_asset,
)
from .canvas_store_results import commit_canvas_result_v4
from .canvas_store_queries import read_canvas_task_context_v4, read_card_results, read_episode_card_results
from .catalogs import (
    ASSET_TYPES,
    DEFAULT_ASSETS,
)
from .model_provider_config import (
    _project_model_config,
)
from .storyboard_image_generation import (
    _generate_storyboard_image_media,
)
from .production_specs import build_storyboard_render_spec
from .storyboard_prompt_content import _storyboard_template_layout_block
from .storyboard_templates import (
    storyboard_image_prompt_spec,
    storyboard_template_layout_kind,
    storyboard_template_label,
    storyboard_template_layout_spec,
    storyboard_template_prompt_rules,
)
from .perf_logging import (
    canvas_perf_elapsed_ms,
    canvas_perf_log,
    canvas_perf_start,
)
from .production_status import (
    update_episode_production_status,
)
from .project_management import (
    get_effective_config,
)
from .store_core import _display_time
from .projects import _touch_project_meta
from .source_text_store import _compact_text
from .store_core import (
    _JSON_WRITE_LOCK,
    _asset_is_offline,
    _emit_agent_event,
    _now,
    _read_json,
    _write_json,
)
from .task_control import (
    _emit_task_update,
    _raise_if_workflow_generation_task_cancelled,
    _workflow_begin_generation_result_commit,
    _workflow_generation_task_session_fields,
    _workflow_update_task_if_active,
    create_task,
)
from .workflow_asset_resolution import (
    resolve_canvas_asset_images,
)
from .workflow_asset_resolution import _asset_media_version_as_storyboard_version, _workflow_canvas_project_asset_info
from .workflow_contract import (
    _STORYBOARD_REFERENCE_NODE_TYPES,
    _VISUAL_HANDOFF_SLOT,
    _apply_workflow_input_link_contract,
    _workflow_active_version_has_usable_media,
    _workflow_canvas_project_asset_type_from_value,
    _workflow_data_active_version_id,
    _workflow_image_node_type,
    _workflow_input_link_version_binding,
    _workflow_is_video_task_type,
    _workflow_node,
    _workflow_node_is_independent_image_asset,
    _workflow_node_is_visual_handoff_asset_like,
    _workflow_node_status_after_input_availability_change,
    _workflow_status_with_usable_active_media,
)
from .workflow_generation_config import (
    _clean_runtime_generation_config,
)
from .workflow_input_resolution import (
    workflow_current_media_reference,
    _workflow_asset_node_has_image_binding,
    _workflow_explicit_storyboard_reference_node_ids,
    _workflow_node_data,
    _workflow_visual_handoff_node_is_generated,
    resolve_generation_task_node_id,
)
from .workflow_projection import (
    get_canvas_workflow_projection,
)
from .workflow_storyboard_versions import (
    add_storyboard_version,
    list_storyboard_versions,
)
from .workflow_visual_handoff import (
    sync_visual_handoff_cross_episode_link,
)
from .workflow_contract import (
    _VISUAL_HANDOFF_TARGET_NODE_TYPES,
)
from datetime import (
    datetime,
)
from typing import (
    Any,
)

import json
import traceback
from pathlib import Path

from .workflow_contract import (
    _assert_canvas_mutation_does_not_return_workflow,
    _workflow_mutation_returns_production_status,
)
from .workflow_contract import (
    _append_unique_string,
)
from .workflow_input_resolution import (
    _link_reference_media_id,
)

def _edit_canvas_image_node(
    project_id: str,
    episode_id: str,
    node_id: str,
    payload: dict[str, Any],
    edit_prompt: str,
    reference_files: list[dict[str, Any]],
) -> dict[str, Any]:
    _assert_canvas_mutation_does_not_return_workflow(payload, "编辑画布图片节点")
    workflow = get_canvas_workflow_projection(project_id, episode_id)
    node = _workflow_node(workflow, node_id)
    use_original = payload.get("useOriginal", True)
    if not isinstance(use_original, bool):
        raise ValueError("使用原图必须为布尔值")
    if (
        use_original and node and node.get("type") == "asset.image"
        and not _workflow_asset_node_has_image_binding(node)
    ):
        resolve_canvas_asset_images(project_id, episode_id, {"nodeIds": [node_id]}, workflow=workflow)
        workflow = get_canvas_workflow_projection(project_id, episode_id)
        node = _workflow_node(workflow, node_id)
    if not node:
        raise FileNotFoundError("节点不存在")
    if not _is_canvas_editable_image_node(node):
        raise ValueError("只有图片类资产可以编辑图片")
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    is_custom_image = data.get("mediaPurpose") == "custom_image"
    use_project_visual = payload.get("useProjectVisual", data.get("useProjectVisual", True)) if is_custom_image else False
    if not isinstance(use_project_visual, bool):
        raise ValueError("项目视觉必须为布尔值")
    title = str(payload.get("title") or data.get("title") or "图片").strip() or "图片"
    node_type = _workflow_image_node_type(node)
    base_media = (
        workflow_current_media_reference(project_id, episode_id, workflow, node_id)
        or _workflow_image_node_media(node)
    ) if use_original else None
    edit_original = uses_original_image_reference(base_media, "original" if base_media else None)
    is_visual_handoff = _workflow_node_is_visual_handoff_asset_like(node)
    is_freeform_image = is_visual_handoff or is_frame_image(data) or is_custom_image
    canvas_asset_type = (
        _workflow_canvas_image_asset_generation_type(data, payload) if not is_freeform_image else ""
    )
    canvas_asset_generation_type = canvas_asset_type if not edit_original else ""
    has_head_option = canvas_asset_type == "characters" and "hideTurnaroundHeads" in payload
    hide_turnaround_heads = payload.get("hideTurnaroundHeads", False)
    if has_head_option and not isinstance(hide_turnaround_heads, bool):
        raise ValueError("三视图头部设置必须为布尔值")
    is_storyboard_generation = (
        data.get("mediaPurpose") == "storyboard_image"
        and not edit_original
    )
    if not edit_original and not canvas_asset_generation_type and not is_storyboard_generation and not (is_freeform_image and not use_original):
        raise ValueError("当前卡片不使用原图时，请通过对应的生成入口生成图片")
    template_id = str(payload.get("storyboardTemplate") or "").strip()
    storyboard_generation: dict[str, Any] = {}
    if template_id and not is_storyboard_generation:
        raise ValueError("只有不使用原图的独立分镜图可以选择版式")
    if is_storyboard_generation:
        if not template_id:
            raise ValueError("请选择分镜图版式")
        storyboard_generation = _canvas_storyboard_generation_payload(
            project_id, template_id, edit_prompt,
        )
    session_fields = _workflow_generation_task_session_fields(payload)

    task_initial_fields = {
        "imageEditKind": "canvas_image",
        "nodeType": node_type,
        **session_fields,
        "updatedAt": int(datetime.now().timestamp() * 1000),
    }
    task = create_task(
        "storyboard_image_edit",
        project_id=project_id,
        episode_id=episode_id,
        node_id=node_id,
        message=_canvas_image_edit_task_message(title, "running"),
        status="running",
        progress=5,
        focus_target=_storyboard_image_edit_focus_target(episode_id, node_id),
        task_fields=task_initial_fields,
    )
    from .agent_sessions import _bind_agent_execution_task
    _bind_agent_execution_task(project_id, task)
    try:
        _emit_task_update(task, "task_created")
        _emit_task_update(task, "task_progress")

        canvas_asset_aspect_ratio = ""
        canvas_asset_resolution: Any = None
        if canvas_asset_generation_type:
            project_config = get_effective_config(project_id)
            try:
                model_config = _project_model_config(project_id)[2]
            except Exception:
                model_config = {}
            image_config = model_config.get("image", {}) if isinstance(model_config.get("image"), dict) else {}
            canvas_asset_aspect_ratio = _asset_generation_aspect_ratio(
                canvas_asset_generation_type,
                project_config.get("aspect_ratio"),
            )
            canvas_asset_resolution = _asset_generation_resolution(
                image_config,
                canvas_asset_generation_type,
            )
        if storyboard_generation:
            generation_prompt = storyboard_generation["storyboardImagePrompt"]
            generation_stage = "canvas_storyboard_generation"
        elif canvas_asset_generation_type:
            generation_prompt = _workflow_canvas_image_asset_generation_prompt(
                project_id,
                canvas_asset_generation_type,
                data,
                payload,
                title,
                edit_prompt,
                request_size=canvas_asset_resolution,
                reference_file_count=len(reference_files),
            )
            generation_stage = "canvas_asset_image_generation"
        else:
            instruction_label = "本次生成要求" if is_custom_image and not edit_original else "本次修改要求"
            generation_prompt = f"【{instruction_label}】\n{edit_prompt}"
            if has_head_option:
                head_requirement = (
                    _ASSET_CHARACTER_HEADLESS_TURNAROUND
                    if hide_turnaround_heads else _ASSET_CHARACTER_HEADED_TURNAROUND
                )
                generation_prompt += f"\n\n【三视图显示要求】\n{head_requirement}"
            generation_stage = "canvas_image_edit" if edit_original else "canvas_image_direct"
        generation_payload: dict[str, Any] = {
            "storyboardImagePrompt": generation_prompt,
            "finalEditPrompt": edit_prompt,
            "userInstruction": edit_prompt,
            "effectiveEditPrompt": edit_prompt,
            "referenceFiles": reference_files,
            "imageGenerationMode": "image_edit" if edit_original else "image_generation",
            "imageOperation": "edit" if edit_original else "generate",
            "editOriginal": edit_original,
            "baseNodeId": node_id,
            "nodeType": node_type,
            "generationStage": generation_stage,
            "taskType": "storyboard_image_edit",
            "taskId": task.get("id"),
        }
        if is_custom_image:
            generation_payload.update({"assetType": "custom_image", "useProjectVisual": use_project_visual})
        if has_head_option:
            generation_payload["hideTurnaroundHeads"] = hide_turnaround_heads
        if session_fields:
            generation_payload.update(copy.deepcopy(session_fields))
        if base_media:
            generation_payload["baseReferenceMedia"] = copy.deepcopy(base_media)
            generation_payload["baseMediaId"] = base_media.get("id")
            spec = storyboard_image_prompt_spec(base_media)
            if spec:
                generation_payload["storyboardPromptSpec"] = spec
        aspect_ratio = (
            canvas_asset_aspect_ratio
            or str(data.get("aspectRatio") or data.get("aspect_ratio") or "").strip()
        )
        if base_media and base_media.get("width") and base_media.get("height"):
            aspect_ratio = f"{base_media['width']}:{base_media['height']}"
        if aspect_ratio:
            generation_payload["storyboardRenderSpec"] = {"sheet": {"aspectRatio": aspect_ratio}}
        if storyboard_generation:
            generation_payload.update(storyboard_generation)
        if canvas_asset_generation_type:
            generation_payload["assetType"] = canvas_asset_generation_type
            generation_payload["assetName"] = (
                str(payload.get("assetName") or payload.get("asset_name") or "").strip()
                or str(data.get("assetName") or data.get("asset_name") or "").strip()
                or title
            )
            generation_payload["canvasAssetGeneration"] = True
            generation_payload["targetImageParameters"] = {
                "kind": {
                    "characters": "character",
                    "creatures": "creature",
                    "scenes": "scene",
                    "props": "prop",
                }.get(canvas_asset_generation_type, "asset"),
                "assetType": canvas_asset_generation_type,
                "desiredAspectRatio": canvas_asset_aspect_ratio or aspect_ratio,
                "resolution": canvas_asset_resolution,
            }

        generation_config = _storyboard_image_edit_generation_config(workflow, node_id, payload, None)
        if canvas_asset_generation_type and canvas_asset_resolution:
            generation_config = copy.deepcopy(generation_config) if isinstance(generation_config, dict) else {}
            has_resolution = any(
                str(generation_config.get(key) or "").strip()
                for key in ("resolution", "size", "storyboardResolution", "storyboard_resolution")
            )
            if not has_resolution:
                generation_config.update(
                    {
                        "resolution": canvas_asset_resolution,
                        "size": canvas_asset_resolution,
                        "storyboardResolution": canvas_asset_resolution,
                        "storyboard_resolution": canvas_asset_resolution,
                    }
                )
        if generation_config:
            generation_payload["resolvedConfig"] = generation_config
            task_config = _clean_runtime_generation_config(generation_config)
            if task_config:
                updated_task = _workflow_update_task_if_active(
                    str(task.get("id") or ""),
                    resolvedConfig=task_config,
                    generationConfig=task_config,
                    modelId=str(task_config.get("modelId") or task_config.get("model_id") or "") or task.get("modelId"),
                    providerId=str(task_config.get("providerId") or task_config.get("provider_id") or "") or task.get("providerId"),
                    updatedAt=int(datetime.now().timestamp() * 1000),
                )
                if not updated_task:
                    raise RuntimeError("任务已取消")
                task = updated_task
                _emit_task_update(task, "task_progress")

        _raise_if_workflow_generation_task_cancelled(generation_payload)
        media_result = _generate_storyboard_image_media(
            project_id,
            episode_id,
            title,
            generation_payload,
            workflow_projection=workflow,
        )
        if isinstance(media_result.get("payload"), dict):
            generation_payload = copy.deepcopy(media_result["payload"])
        generation_payload["taskId"] = task.get("id")
        if session_fields:
            generation_payload.update(copy.deepcopy(session_fields))
        reference_file_meta = [
            {
                "name": item.get("name") or item.get("originalName"),
                "mimeType": item.get("mimeType") or item.get("mime_type"),
                "size": item.get("size"),
            }
            for item in reference_files
        ]
        version_payload = copy.deepcopy(generation_payload)
        version_payload["referenceFiles"] = reference_file_meta
        if isinstance(version_payload.get("baseReferenceMedia"), dict):
            version_payload["baseReferenceMedia"] = _persistent_media_data_removed(
                version_payload.get("baseReferenceMedia")
            )
        media = media_result.get("media") if isinstance(media_result.get("media"), dict) else None
        if not media:
            raise RuntimeError("图片模型未返回可用图片数据")
        summary = f"已根据修改要求生成新图片：{_compact_text(edit_prompt, 120)}"
        clean_media_for_node = _persistent_media_data_removed(media)
        completed_message = _canvas_image_edit_task_message(title, "completed")
        completed_at = _display_time(_now())
        completed_updated_at = int(datetime.now().timestamp() * 1000)
        canvas_task_commit_result: dict[str, Any] = {
            "imageEditKind": "canvas_image",
            "nodeType": node_type,
            "media": _persistent_media_data_removed(media),
        }
        canvas_task_commit_row = copy.deepcopy(task)
        canvas_task_commit_row.update(
            {
                "projectId": project_id,
                "episodeId": episode_id,
                "nodeId": node_id,
                "status": "completed",
                "progress": 100,
                "message": completed_message,
                "notice": completed_message,
                "modelId": media_result.get("model") or task.get("modelId"),
                "providerId": media_result.get("provider") or task.get("providerId"),
                "imageEditKind": "canvas_image",
                "nodeType": node_type,
                "result": canvas_task_commit_result,
                "completedAt": completed_at,
                "updatedAt": completed_updated_at,
                "focusTarget": _storyboard_image_edit_focus_target(episode_id, node_id),
            }
        )
        metadata = {
            "title": str(payload.get("versionTitle") or payload.get("version_title") or f"{title} 编辑版"),
            "summary": summary,
            "source": media_result.get("source") or ("model-image-edit" if edit_original else "model-image-generation"),
            "payload": version_payload,
            "media": media,
            "model": media_result.get("model"),
            "provider": media_result.get("provider"),
            "generationDebug": _persistent_media_data_removed(media_result.get("debug")),
            "nodeDataPatch": {
                "storage": clean_media_for_node,
                "mediaId": media.get("id"),
                "provenance": {
                    "lastImageEditAt": _now(),
                    "lastImageEditOriginal": edit_original,
                },
            },
            "canvasTasks": [canvas_task_commit_row],
        }
        if storyboard_generation:
            metadata["nodeDataPatch"].update({
                key: copy.deepcopy(generation_payload[key])
                for key in ("storyboardTemplate", "storyboardTemplateLabel", "storyboardTemplateLayoutSpec", "storyboardRenderSpec")
            })
        if is_custom_image:
            metadata["nodeDataPatch"]["useProjectVisual"] = use_project_visual
        _workflow_begin_generation_result_commit(
            generation_payload,
            message="正在保存分镜图编辑结果。",
            task_types={"storyboard_image_edit"},
        )
        version = _append_canvas_project_asset_media_version(
            project_id,
            episode_id,
            node_id,
            node,
            media,
            metadata,
        ) or add_storyboard_version(
            project_id,
            episode_id,
            node_id,
            "image",
            metadata,
        )

        updated_node = copy.deepcopy(node)
        workflow_version: Any = workflow.get("version")
        save_result: dict[str, Any] = {
            key: copy.deepcopy(version.get(key))
            for key in ("txId", "seq", "revision", "baseRevision", "opType", "records", "changedResources", "workflowVersion")
            if isinstance(version, dict) and version.get(key) is not None
        }
        if updated_node:
            updated_data = updated_node.setdefault("data", {})
            if not isinstance(updated_data, dict):
                updated_data = {}
                updated_node["data"] = updated_data
            updated_data["status"] = "ready"
            if is_custom_image:
                updated_data["useProjectVisual"] = use_project_visual
            updated_data["summary"] = summary
            updated_data["media"] = clean_media_for_node
            updated_data["storage"] = clean_media_for_node
            updated_data["mediaId"] = media.get("id")
            updated_data["sourceVersionId"] = version.get("id")
            updated_data["mediaVersionId"] = version.get("id")
            updated_data["activeMediaVersionId"] = version.get("id")
            updated_data["activeVersionId"] = version.get("id")
            if storyboard_generation:
                updated_data.update({
                    key: copy.deepcopy(metadata["nodeDataPatch"][key])
                    for key in ("storyboardTemplate", "storyboardTemplateLabel", "storyboardTemplateLayoutSpec", "storyboardRenderSpec")
                })
            provenance = updated_data.get("provenance") if isinstance(updated_data.get("provenance"), dict) else {}
            updated_data["provenance"] = {
                **provenance,
                "lastImageEditAt": _now(),
                "lastImageEditOriginal": edit_original,
            }
            version_id = str(version.get("id") or "").strip()
            if version_id:
                canvas_task_commit_row["versionId"] = version_id
                canvas_task_commit_row["focusTarget"] = _storyboard_image_edit_focus_target(
                    episode_id,
                    node_id,
                    version_id=version_id,
                )
            if not save_result.get("txId"):
                versions = read_card_results(project_id, episode_id, node_id)
                if version_id and not any(
                    isinstance(item, dict) and str(item.get("id") or "") == version_id
                    for item in versions
                ):
                    versions.append(copy.deepcopy(version))
                canvas_task_commit_result = (
                    canvas_task_commit_row.get("result")
                    if isinstance(canvas_task_commit_row.get("result"), dict)
                    else {}
                )
                canvas_task_commit_result = copy.deepcopy(canvas_task_commit_result)
                canvas_task_commit_result["version"] = _persistent_media_data_removed(version)
                clean_commit_node = _persistent_media_data_removed(updated_node)
                if isinstance(clean_commit_node, dict):
                    canvas_task_commit_result["node"] = clean_commit_node
                canvas_task_commit_row["result"] = canvas_task_commit_result
                save_result = commit_canvas_result_v4(
                    project_id,
                    episode_id,
                    node_id=node_id,
                    versions=versions,
                    active_version_id=version_id,
                    nodes=[copy.deepcopy(updated_node)],
                    tasks=[copy.deepcopy(canvas_task_commit_row)],
                    changed_resources=["canvas_node", "canvas_version", "canvas_task"],
                )
            workflow_version = save_result.get("workflowVersion") or workflow_version

        clean_updated_node = _persistent_media_data_removed(updated_node)
        if not isinstance(clean_updated_node, dict):
            clean_updated_node = None
        task_result: dict[str, Any] = {
            "imageEditKind": "canvas_image",
            "nodeType": node_type,
            "version": _persistent_media_data_removed(version),
            "media": _persistent_media_data_removed(media),
        }
        for key in ("txId", "seq", "revision", "baseRevision", "opType", "records", "changedResources"):
            if save_result.get(key) is not None:
                task_result[key] = copy.deepcopy(save_result.get(key))
        if clean_updated_node:
            task_result["node"] = copy.deepcopy(clean_updated_node)

        task = _workflow_update_task_if_active(
            str(task.get("id") or ""),
            status="completed",
            progress=100,
            message=completed_message,
            notice=completed_message,
            versionId=version.get("id"),
            modelId=media_result.get("model") or task.get("modelId"),
            providerId=media_result.get("provider") or task.get("providerId"),
            imageEditKind="canvas_image",
            nodeType=node_type,
            result=task_result,
            completedAt=completed_at,
            updatedAt=completed_updated_at,
            focusTarget=_storyboard_image_edit_focus_target(
                episode_id,
                node_id,
                version_id=str(version.get("id") or ""),
            ),
        )
        if not task:
            return {
                "success": True,
                "episodeId": episode_id,
                "nodeId": node_id,
                "requestedNodeId": node_id,
                "version": version,
                "cancelled": True,
                "message": "任务已取消",
            }
        _emit_task_update(task, "task_completed")
        _emit_storyboard_image_edit_project_changed(
            project_id,
            episode_id,
            node_id,
            version_id=str(version.get("id") or ""),
            action="storyboard_image_edit_completed",
            changed_resources=["canvas_task", "canvas_version", "canvas_node"],
            node=clean_updated_node,
            result=task_result,
            image_edit_kind="canvas_image",
            node_type=node_type,
        )
    except Exception as exc:
        traceback_text = traceback.format_exc()
        failure_message = str(exc) or exc.__class__.__name__ or "编辑图片失败。"
        failed_message = _canvas_image_edit_task_message(title, "failed")
        task = _workflow_update_task_if_active(
            str(task.get("id") or ""),
            status="failed",
            progress=0,
            failedAt=_display_time(_now()),
            updatedAt=int(datetime.now().timestamp() * 1000),
            imageEditKind="canvas_image",
            nodeType=node_type,
            **{
                **_storyboard_image_edit_failure_fields(failure_message, traceback_text),
                "message": failed_message,
                "notice": failed_message,
            },
        )
        if task:
            _emit_task_update(task, "task_failed")
            _emit_storyboard_image_edit_project_changed(
                project_id,
                episode_id,
                node_id,
                action="storyboard_image_edit_failed",
                changed_resources=["canvas_task"],
                image_edit_kind="canvas_image",
                node_type=node_type,
            )
        raise

    return_production_status = _workflow_mutation_returns_production_status(payload)
    production_status = None
    if return_production_status:
        try:
            status_result = update_episode_production_status(project_id, episode_id)
            production_status = status_result.get("status") if isinstance(status_result, dict) else None
        except Exception:
            print(traceback.format_exc(), flush=True)
    result = {
        "success": True,
        "episodeId": episode_id,
        "nodeId": node_id,
        "requestedNodeId": node_id,
        "version": version,
        "media": media,
        "task": task,
        "workflowVersion": workflow_version,
        "txId": task_result.get("txId"),
        "seq": task_result.get("seq"),
        "revision": task_result.get("revision"),
        "opType": task_result.get("opType"),
        "records": task_result.get("records"),
        "changedResources": ["canvas_task", "canvas_version", "canvas_node"] + (["episode_production_status"] if production_status else []),
    }
    if return_production_status:
        result["productionStatus"] = production_status
    return result


def _storyboard_image_edit_base_version(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_id: str,
    base_version_id: str = "",
) -> tuple[str, dict[str, Any]]:
    requested_version_id = str(base_version_id or "").strip()
    for candidate_id in _storyboard_image_edit_candidate_node_ids(workflow, node_id):
        versions = list_storyboard_versions(project_id, episode_id, candidate_id).get("versions", [])
        if not isinstance(versions, list) or not versions:
            continue
        candidate_data = _workflow_node_data(workflow, candidate_id)
        active_version_id = _workflow_data_active_version_id(candidate_data)
        preferred_id = requested_version_id or active_version_id
        selected = next(
            (
                item
                for item in versions
                if isinstance(item, dict) and preferred_id and str(item.get("id") or "") == preferred_id
            ),
            None,
        )
        if isinstance(selected, dict) and selected.get("media"):
            return candidate_id, selected
    if requested_version_id:
        # Canvas route aliases can point to a different group in the same work
        # chain. An explicit version ID identifies the exact persisted image.
        requested_node = _workflow_node(workflow, node_id) or {}
        requested_data = requested_node.get("data") if isinstance(requested_node.get("data"), dict) else {}
        for version in read_episode_card_results(project_id, episode_id):
            if not isinstance(version, dict) or str(version.get("id") or "") != requested_version_id or not version.get("media"):
                continue
            version_node_id = str(version.get("nodeId") or version.get("cardId") or "").strip()
            version_node = _workflow_node(workflow, version_node_id)
            if not _is_work_chain_storyboard_result_image_node(version_node):
                break
            version_data = version_node.get("data") if isinstance(version_node.get("data"), dict) else {}
            if (requested_data.get("workChainId") and version_data.get("workChainId")
                    and requested_data["workChainId"] != version_data["workChainId"]):
                break
            return version_node_id, version
    raise FileNotFoundError("当前结果图还没有可编辑的生成版本")


def _storyboard_image_edit_version_generation_config(base_version: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(base_version, dict):
        return {}
    payload = base_version.get("payload") if isinstance(base_version.get("payload"), dict) else {}
    snapshot = (
        payload.get("generationConfigSnapshot")
        if isinstance(payload.get("generationConfigSnapshot"), dict)
        else {}
    )
    candidates: list[dict[str, Any]] = []
    for value in (
        snapshot.get("merged"),
        snapshot.get("resolved"),
        payload.get("resolvedConfig"),
        payload.get("resolved_config"),
        payload.get("generationConfig"),
        payload.get("generation_config"),
    ):
        if isinstance(value, dict) and value:
            candidates.append(value)
    config: dict[str, Any] = {}
    for candidate in candidates:
        config.update(_clean_runtime_generation_config(candidate))
    for key in ("modelId", "model_id", "model", "providerId", "provider_id", "providerPresetId", "provider_preset_id"):
        config.pop(key, None)
    return _clean_runtime_generation_config(config)


def _storyboard_image_edit_generation_config(
    workflow: dict[str, Any],
    node_id: str,
    payload: dict[str, Any],
    base_version: dict[str, Any] | None = None,
) -> dict[str, Any]:
    allow_request_override = bool(
        payload.get("allowGenerationConfigOverride")
        or payload.get("allow_generation_config_override")
        or payload.get("forceGenerationConfigOverride")
        or payload.get("force_generation_config_override")
    )
    version_config = _storyboard_image_edit_version_generation_config(base_version)
    node_data = _workflow_node_data(workflow, node_id)
    node_config = node_data.get("generationConfig")
    source_id = str(node_data.get("resultOfNodeId") or node_data.get("sourceNodeId") or "").strip()
    source_config = None
    if source_id:
        source_data = _workflow_node_data(workflow, source_id)
        source_config = source_data.get("generationConfig")
    generation_config = dict(version_config)

    def apply_override(override: dict[str, Any]) -> None:
        override_model_id = str(override.get("modelId") or override.get("model_id") or "").strip()
        current_model_id = str(generation_config.get("modelId") or generation_config.get("model_id") or "").strip()
        if override_model_id and override_model_id != current_model_id:
            for key in ("modelId", "model_id", "model", "providerId", "provider_id", "providerPresetId", "provider_preset_id"):
                generation_config.pop(key, None)
        generation_config.update(override)

    if isinstance(source_config, dict):
        apply_override(source_config)
    if isinstance(node_config, dict):
        apply_override(node_config)
    if allow_request_override:
        for key in ("resolvedConfig", "resolved_config", "generationConfig", "generation_config"):
            override = payload.get(key)
            if isinstance(override, dict) and override:
                apply_override(override)
                break
    return _clean_runtime_generation_config(generation_config)


_STORYBOARD_IMAGE_EDIT_VERSION_CONTEXT_KEYS = (
    "episodeTitle",
    "sourceRef",
    "panelCount",
    "routePanelCount",
    "panels",
    "userStoryText",
    "projectStylePrompt",
    "storyContextPrompt",
    "panelPromptRows",
    "storyboardTemplate",
    "storyboardTemplateLabel",
    "storyboardTemplateLayoutSpec",
    "storyboardPromptSpec",
    "assetRefs",
    "referenceManifest",
    "storyboardInterpretationContract",
    "storyboardRenderSpec",
)


def _storyboard_image_edit_version_payload(version: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(version, dict):
        return {}
    payload = version.get("payload")
    return copy.deepcopy(payload) if isinstance(payload, dict) else {}


def _storyboard_image_edit_version_context(
    version: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = _storyboard_image_edit_version_payload(version)
    return {
        key: copy.deepcopy(payload[key])
        for key in _STORYBOARD_IMAGE_EDIT_VERSION_CONTEXT_KEYS
        if key in payload
    }


def _storyboard_image_edit_focus_target(
    episode_id: str | None,
    node_id: str | None,
    *,
    version_id: str | None = None,
) -> dict[str, Any]:
    target = {
        "section": "episode",
        "episodeId": episode_id or "",
        "nodeId": node_id or "",
    }
    if version_id:
        target["versionId"] = version_id
    return target


def _emit_storyboard_image_edit_project_changed(
    project_id: str,
    episode_id: str,
    node_id: str,
    *,
    requested_node_id: str = "",
    version_id: str = "",
    action: str = "storyboard_image_edit_completed",
    changed_resources: list[str] | None = None,
    node: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    image_edit_kind: str = "",
    node_type: str = "",
) -> None:
    payload: dict[str, Any] = {
        "action": action,
        "projectId": project_id,
        "episodeId": episode_id,
        "nodeId": node_id,
        "changedResources": changed_resources or ["canvas_task", "canvas_version", "canvas_node"],
    }
    if requested_node_id and requested_node_id != node_id:
        payload["requestedNodeId"] = requested_node_id
    if version_id:
        payload["versionId"] = version_id
    if node_type:
        payload["nodeType"] = node_type
    if image_edit_kind:
        payload["imageEditKind"] = image_edit_kind
    if node:
        payload["node"] = copy.deepcopy(node)
    if result:
        payload["result"] = copy.deepcopy(result)
        for key in ("txId", "seq", "revision", "baseRevision", "opType", "records", "changedResources"):
            if isinstance(result, dict) and result.get(key) is not None:
                payload[key] = copy.deepcopy(result.get(key))
    _emit_agent_event("project_changed", payload)


def _storyboard_image_edit_failure_fields(
    reason: Any,
    traceback_text: str = "",
) -> dict[str, Any]:
    def clean(value: Any, limit: int) -> str:
        text = str(value or "").strip()
        if not text or text == "NoneType: None":
            return ""
        text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,}\]]+", r"\1<redacted>", text)
        text = re.sub(
            r"(?i)((?:api[_-]?key|apiKey|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+",
            r"\1<redacted>",
            text,
        )
        text = re.sub(r"\s+\n", "\n", text).strip()
        if len(text) > limit:
            return f"{text[:limit].rstrip()}...（已截断）"
        return text

    failure_reason = clean(reason, 3000)
    debug_text = clean(traceback_text, 6000)
    summary = f"修改分镜图失败：{failure_reason}" if failure_reason else "修改分镜图失败。"
    fields: dict[str, Any] = {
        "message": summary,
        "notice": summary,
        "failureReason": failure_reason,
        "errorSummary": summary,
        "error": failure_reason,
    }
    if failure_reason:
        fields["providerResponseSummary"] = failure_reason
    if debug_text:
        fields["errorDebug"] = debug_text
    return fields


def edit_storyboard_image(
    project_id: str,
    episode_id: str,
    node_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    session_fields = _workflow_generation_task_session_fields(payload)
    _assert_canvas_mutation_does_not_return_workflow(payload, "编辑分镜图")
    workflow = get_canvas_workflow_projection(project_id, episode_id)
    requested_node = _workflow_node(workflow, node_id)
    if not requested_node:
        raise FileNotFoundError("节点不存在")

    edit_prompt = str(
        payload.get("prompt")
        or payload.get("editPrompt")
        or payload.get("edit_prompt")
        or payload.get("userInstruction")
        or payload.get("user_instruction")
        or ""
    ).strip()
    effective_edit_prompt = str(
        payload.get("effectiveEditPrompt")
        or payload.get("effective_edit_prompt")
        or payload.get("agentRefinedEditPrompt")
        or payload.get("agent_refined_edit_prompt")
        or payload.get("finalEditPrompt")
        or payload.get("final_edit_prompt")
        or ""
    ).strip()
    reference_files = payload.get("referenceFiles")
    if not isinstance(reference_files, list):
        reference_files = payload.get("reference_files")
    if not isinstance(reference_files, list):
        reference_files = []
    reference_files = [item for item in reference_files if isinstance(item, dict)]
    if not edit_prompt:
        raise ValueError("请输入修改描述")
    if not _is_work_chain_storyboard_result_image_node(requested_node):
        if _is_canvas_editable_image_node(requested_node):
            return _edit_canvas_image_node(
                project_id,
                episode_id,
                node_id,
                payload,
                edit_prompt,
                reference_files,
            )
        raise ValueError("只有图片类资产可以编辑图片")

    use_original = payload.get("useOriginal", True)
    if not isinstance(use_original, bool):
        raise ValueError("使用原图必须为布尔值")
    if isinstance(payload.get("consistencyCorrection"), dict) and not use_original:
        raise ValueError("报告修正必须使用报告对应的原图")
    base_version_id = str(payload.get("baseVersionId") or payload.get("base_version_id") or "").strip()
    target_node_id, base_version = _storyboard_image_edit_base_version(
        project_id,
        episode_id,
        workflow,
        node_id,
        base_version_id,
    )
    target_node = _workflow_node(workflow, target_node_id) or requested_node
    target_data = target_node.get("data") if isinstance(target_node.get("data"), dict) else {}
    title = str(payload.get("title") or target_data.get("title") or "分镜图")
    base_media = base_version.get("media") if isinstance(base_version.get("media"), dict) else {}
    base_media_id = str(base_media.get("id") or payload.get("baseMediaId") or payload.get("base_media_id") or "").strip()
    panel_edit: dict[str, Any] | None = None
    requested_panel_index = payload.get("panelIndex", payload.get("panel_index"))
    if requested_panel_index is not None:
        if isinstance(requested_panel_index, bool) or not isinstance(requested_panel_index, int):
            raise ValueError("局部修改的画格序号必须为整数")
        if not use_original:
            raise ValueError("局部修改必须使用原图")
        base_payload = _storyboard_image_edit_version_payload(base_version)
        base_panels = base_payload.get("panels") if isinstance(base_payload.get("panels"), list) else []
        if not 1 <= requested_panel_index <= len(base_panels):
            raise ValueError("画格序号超出原分镜图镜头数量")
        panel_edit = {"panelIndex": requested_panel_index, "baseVersionId": str(base_version.get("id") or "")}
    edit_instruction = effective_edit_prompt or edit_prompt
    base_version_id_for_reference = str(base_version.get("id") or base_version_id)
    edit_mode = "consistency_correction" if isinstance(payload.get("consistencyCorrection"), dict) else "manual"
    edit_source_prompt = f"【本次修改要求】\n{edit_instruction}"
    version_context = _storyboard_image_edit_version_context(base_version)
    storyboard_generation: dict[str, Any] = {}
    if not use_original:
        template_id = str(payload.get("storyboardTemplate") or "").strip()
        if not template_id:
            raise ValueError("请选择分镜图版式")
        storyboard_generation = _canvas_storyboard_generation_payload(project_id, template_id, edit_instruction)
        edit_source_prompt = storyboard_generation["storyboardImagePrompt"]
    elif payload.get("storyboardTemplate"):
        raise ValueError("使用原图时不应用固定版式")
    edit_record: dict[str, Any] = {
        "prompt": edit_prompt,
        "baseVersionId": base_version_id_for_reference,
        "mode": edit_mode,
        "referenceFileCount": len(reference_files),
        "createdAt": _now(),
    }
    if panel_edit:
        edit_record["panelIndex"] = panel_edit["panelIndex"]
    if edit_instruction and edit_instruction != edit_prompt:
        edit_record["effectivePrompt"] = edit_instruction
    original_instruction = _compact_text(
        str(payload.get("agentOriginalUserInstruction") or payload.get("agent_original_user_instruction") or "").strip(),
        1800,
    )
    if original_instruction and original_instruction != edit_prompt:
        edit_record["agentOriginalUserInstruction"] = original_instruction
    if isinstance(payload.get("agentExtractedRequirements"), dict):
        edit_record["agentExtractedRequirements"] = copy.deepcopy(payload["agentExtractedRequirements"])
    if isinstance(payload.get("consistencyCorrection"), dict):
        edit_record["consistencyCorrection"] = copy.deepcopy(payload["consistencyCorrection"])
    task_initial_fields = {
        **session_fields,
        "updatedAt": int(datetime.now().timestamp() * 1000),
    }
    task = create_task(
        "storyboard_image_edit",
        project_id=project_id,
        episode_id=episode_id,
        node_id=target_node_id,
        message="正在修改分镜图。",
        status="running",
        progress=5,
        focus_target=_storyboard_image_edit_focus_target(episode_id, target_node_id),
        task_fields=task_initial_fields,
    )
    from .agent_sessions import _bind_agent_execution_task
    _bind_agent_execution_task(project_id, task)
    _emit_task_update(task, "task_created")
    _emit_task_update(task, "task_progress")
    generation_payload: dict[str, Any] = {
        # Only output settings enter generation; plan/history stay in stored versions.
        **{key: copy.deepcopy(version_context[key]) for key in ("storyboardRenderSpec", "storyboardTemplateLayoutSpec") if key in version_context},
        "storyboardImagePrompt": edit_source_prompt,
        "storyboardImagePromptRaw": edit_source_prompt,
        "imageEditMode": edit_mode,
        "editRecord": copy.deepcopy(edit_record),
        "finalEditPrompt": edit_instruction,
        "userInstruction": edit_instruction,
        "effectiveEditPrompt": edit_instruction,
        "referenceMediaIds": [],
        "referenceFiles": reference_files,
        "imageGenerationMode": "image_edit" if use_original else "image_generation",
        "imageOperation": "edit" if use_original else "generate",
        "baseVersionId": base_version_id_for_reference,
        "baseNodeId": target_node_id,
        "baseMediaId": base_media_id,
        "storyboardImageSource": "image_edit",
        "editPrompt": edit_prompt,
        "generationStage": "storyboard_image_edit" if use_original else "canvas_storyboard_generation",
        "taskType": "storyboard_image_edit",
        "taskId": task.get("id"),
    }
    if panel_edit:
        generation_payload["storyboardPanelEdit"] = panel_edit
        generation_payload["panels"] = copy.deepcopy(version_context.get("panels") or [])
    if use_original:
        generation_payload["baseReferenceMediaIds"] = [base_version_id_for_reference] if base_version_id_for_reference else []
        generation_payload["baseReferenceMedia"] = copy.deepcopy(base_media)
    else:
        generation_payload.pop("baseVersionId", None)
        generation_payload.pop("baseMediaId", None)
        generation_payload["referenceMediaIds"] = []
    if storyboard_generation:
        generation_payload.update(storyboard_generation)
    if session_fields:
        generation_payload.update(copy.deepcopy(session_fields))
    try:
        generation_config = _storyboard_image_edit_generation_config(workflow, target_node_id, payload, base_version)
        if generation_config:
            generation_payload["resolvedConfig"] = generation_config

        task_config = _clean_runtime_generation_config(generation_config)
        if task_config:
            task_update: dict[str, Any] = {
                "resolvedConfig": task_config,
                "generationConfig": task_config,
                "updatedAt": int(datetime.now().timestamp() * 1000),
            }
            model_id = str(task_config.get("modelId") or task_config.get("model_id") or "").strip()
            provider_id = str(task_config.get("providerId") or task_config.get("provider_id") or "").strip()
            if model_id:
                task_update["modelId"] = model_id
            if provider_id:
                task_update["providerId"] = provider_id
            updated_task = _workflow_update_task_if_active(str(task.get("id") or ""), **task_update)
            if not updated_task:
                raise RuntimeError("任务已取消")
            task = updated_task
            _emit_task_update(task, "task_progress")

        _raise_if_workflow_generation_task_cancelled(generation_payload)
        media_result = _generate_storyboard_image_media(
            project_id,
            episode_id,
            title,
            generation_payload,
            workflow_projection=workflow,
        )
        if isinstance(media_result.get("payload"), dict):
            generation_payload = copy.deepcopy(media_result["payload"])
        generation_payload["taskId"] = task.get("id")
        if session_fields:
            generation_payload.update(copy.deepcopy(session_fields))
        reference_file_meta = [
            {
                "name": item.get("name") or item.get("originalName"),
                "mimeType": item.get("mimeType") or item.get("mime_type"),
                "size": item.get("size"),
            }
            for item in reference_files
        ]
        version_payload = {**version_context, **copy.deepcopy(generation_payload)}
        if isinstance(media_result.get("workpageMedia"), dict):
            version_payload["workpageMedia"] = copy.deepcopy(media_result["workpageMedia"])
        version_payload["referenceFiles"] = reference_file_meta
        edit_record = {
            **edit_record,
            "referenceFiles": reference_file_meta,
            "outputMediaId": (media_result.get("media") if isinstance(media_result.get("media"), dict) else {}).get("id"),
        }
        version_payload["editRecord"] = edit_record
        summary = (
            f"已根据修改要求生成新版本：{_compact_text(edit_prompt, 120)}"
            if edit_prompt
            else "已根据上传参考图生成图片编辑新版本。"
        )
        metadata = {
            "title": str(payload.get("versionTitle") or payload.get("version_title") or f"{title} 修改版"),
            "summary": summary,
            "source": "model-image-edit",
            "payload": version_payload,
            "media": media_result.get("media"),
            "model": media_result.get("model"),
            "provider": media_result.get("provider"),
            "generationDebug": _persistent_media_data_removed(media_result.get("debug")),
        }
        if isinstance(media_result.get("workpageMedia"), dict):
            metadata["workpageMedia"] = media_result["workpageMedia"]
            metadata["nodeDataPatch"] = {"workpageMedia": media_result["workpageMedia"]}
        _workflow_begin_generation_result_commit(
            generation_payload,
            message="正在保存分镜图编辑结果。",
            task_types={"storyboard_image_edit"},
        )
        version = add_storyboard_version(
            project_id,
            episode_id,
            target_node_id,
            "image",
            metadata,
        )
        completed_fields: dict[str, Any] = {
            "status": "completed",
            "progress": 100,
            "message": summary,
            "notice": summary,
            "versionId": version.get("id"),
            "modelId": media_result.get("model") or task.get("modelId"),
            "providerId": media_result.get("provider") or task.get("providerId"),
            "completedAt": _display_time(_now()),
            "updatedAt": int(datetime.now().timestamp() * 1000),
            "focusTarget": _storyboard_image_edit_focus_target(
                episode_id,
                target_node_id,
                version_id=str(version.get("id") or ""),
            ),
        }
        task = _workflow_update_task_if_active(str(task.get("id") or ""), **completed_fields)
        if not task:
            return {
                "success": True,
                "episodeId": episode_id,
                "nodeId": target_node_id,
                "requestedNodeId": node_id,
                "version": version,
                "cancelled": True,
                "message": "任务已取消",
            }
        _emit_task_update(task, "task_completed")
        _emit_storyboard_image_edit_project_changed(
            project_id,
            episode_id,
            target_node_id,
            requested_node_id=node_id,
            version_id=str(version.get("id") or ""),
            action="storyboard_image_edit_completed",
            changed_resources=["canvas_task", "canvas_version", "canvas_node"],
        )
        # Checking is advisory and must never turn a saved edit into a failed generation.
        try:
            if (get_effective_config(project_id).get("storyboard") or {}).get("consistency_report_enabled", True) is True:
                from .workflow_variant_quality import start_storyboard_consistency_check
                start_storyboard_consistency_check(project_id, episode_id, {
                    "nodeId": target_node_id, "versionId": version["id"],
                })
        except Exception:
            print(traceback.format_exc(), flush=True)
    except Exception as exc:
        traceback_text = traceback.format_exc()
        failure_message = str(exc) or exc.__class__.__name__ or "修改分镜图失败。"
        failed_fields = {
            "status": "failed",
            "progress": 0,
            "failedAt": _display_time(_now()),
            "updatedAt": int(datetime.now().timestamp() * 1000),
            **_storyboard_image_edit_failure_fields(failure_message, traceback_text),
        }
        task = _workflow_update_task_if_active(str(task.get("id") or ""), **failed_fields)
        if task:
            _emit_task_update(task, "task_failed")
            _emit_storyboard_image_edit_project_changed(
                project_id,
                episode_id,
                target_node_id,
                requested_node_id=node_id,
                action="storyboard_image_edit_failed",
                changed_resources=["canvas_task"],
            )
        raise
    return_production_status = _workflow_mutation_returns_production_status(payload)
    workflow_version = version.get("workflowVersion") or workflow.get("version")
    production_status = None
    if return_production_status:
        try:
            status_result = update_episode_production_status(project_id, episode_id)
            production_status = status_result.get("status") if isinstance(status_result, dict) else None
        except Exception:
            print(traceback.format_exc(), flush=True)
    result = {
        "success": True,
        "episodeId": episode_id,
        "nodeId": target_node_id,
        "requestedNodeId": node_id,
        "version": version,
        "workflowVersion": workflow_version,
        "txId": version.get("txId") if isinstance(version, dict) else None,
        "seq": version.get("seq") if isinstance(version, dict) else None,
        "revision": version.get("revision") if isinstance(version, dict) else None,
        "opType": version.get("opType") if isinstance(version, dict) else None,
        "records": version.get("records") if isinstance(version, dict) else None,
        "changedResources": ["canvas_task", "canvas_version", "canvas_node"] + (["episode_production_status"] if production_status else []),
    }
    if return_production_status:
        result["productionStatus"] = production_status
    return result


def _update_storyboard_version_metadata(
    project_id: str,
    episode_id: str,
    version_id: str,
    metadata: dict[str, Any],
    *,
    workflow: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    perf_started_at = canvas_perf_start()
    status = "ok"
    node_id = ""
    workflow_source = "projection"
    patched_node_count = 0
    version_count = 0
    try:
        existing_version = next(
            (
                item
                for item in read_episode_card_results(project_id, episode_id)
                if isinstance(item, dict) and str(item.get("id") or "") == str(version_id)
            ),
            None,
        )
        if not existing_version:
            status = "missing_version"
            return None
        node_id = str(existing_version.get("nodeId") or existing_version.get("cardId") or "")
        if not node_id:
            status = "missing_node_id"
            return None
        versions = read_card_results(project_id, episode_id, node_id)
        version_count = len(versions) if isinstance(versions, list) else 0
        updated: dict[str, Any] | None = None
        for index, version in enumerate(versions):
            if not isinstance(version, dict) or str(version.get("id") or "") != str(version_id):
                continue
            next_version = {**version}
            for key in (
                "title",
                "summary",
                "source",
                "payload",
                "preview",
                "media",
                "workpageMedia",
                "model",
                "provider",
                "generationDebug",
                "generationError",
            ):
                if key in metadata:
                    next_version[key] = _persistent_media_data_removed(metadata[key])
            if metadata.get("status"):
                next_version["status"] = str(metadata["status"])
            if metadata.get("completedAt"):
                next_version["completedAt"] = metadata["completedAt"]
            versions[index] = next_version
            updated = next_version
            break
        if not updated:
            status = "version_not_in_card"
            return None

        provided_workflow = workflow if isinstance(workflow, dict) and isinstance(workflow.get("nodes"), list) else None
        if provided_workflow and _workflow_node(provided_workflow, node_id):
            workflow_projection = copy.deepcopy(provided_workflow)
            workflow_source = "provided"
        else:
            workflow_projection = get_canvas_workflow_projection(project_id, episode_id)
        before_node_signatures = {
            str(item.get("id") or ""): json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in workflow_projection.get("nodes", [])
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        updated_status = str(updated.get("status") or "").strip()
        updated_ready = (
            updated_status
            not in {"processing", "failed", "blocked", "cancelled", "canceled"}
            and bool(updated.get("media"))
        )
        active_version_id = _workflow_data_active_version_id(_workflow_node_data(workflow_projection, node_id))
        if updated_ready:
            active_version_id = str(updated.get("id") or "")
        active_version_has_media = _workflow_active_version_has_usable_media(
            versions,
            _workflow_node_data(workflow_projection, node_id),
        )
        updated_node_type = ""
        downstream_result_node_ids = {
            str(edge.get("target") or "").strip()
            for edge in workflow_projection.get("edges", [])
            if isinstance(edge, dict)
            and str(edge.get("source") or "").strip() == node_id
            and str((edge.get("data") if isinstance(edge.get("data"), dict) else {}).get("kind") or "") == "dependency"
        }
        for node in workflow_projection.get("nodes", []):
            if node.get("id") != node_id:
                continue
            updated_node_type = str(node.get("type") or "")
            data = node.setdefault("data", {})
            if not isinstance(data, dict):
                data = {}
                node["data"] = data
            status_text = updated_status
            if updated_ready:
                data["activeVersionId"] = updated["id"]
                data["activeMediaVersionId"] = updated["id"]
                data["mediaVersionId"] = updated["id"]
                data["sourceVersionId"] = updated["id"]
                data["media"] = _persistent_media_data_removed(updated.get("media"))
                if "workpageMedia" in updated:
                    data["workpageMedia"] = _persistent_media_data_removed(updated["workpageMedia"])
            if status_text == "processing":
                data["status"] = "running"
            elif status_text in {"failed", "blocked", "cancelled", "canceled"}:
                data["status"] = (
                    _workflow_status_with_usable_active_media(data.get("status"))
                    if active_version_has_media
                    else "failed"
                )
            else:
                data["status"] = "ready"
            data["summary"] = str(updated.get("summary") or data.get("summary") or "生成版本已写入。")
            break
        affected_video_task_ids: set[str] = set()
        if updated_node_type in _STORYBOARD_REFERENCE_NODE_TYPES and updated_ready:
            source_node = _workflow_node(workflow_projection, node_id) or {}
            for candidate in workflow_projection.get("nodes", []) if isinstance(workflow_projection.get("nodes"), list) else []:
                if not isinstance(candidate, dict) or not _workflow_is_video_task_type(str(candidate.get("type") or "")):
                    continue
                candidate_id = str(candidate.get("id") or "").strip()
                if not candidate_id:
                    continue
                data = candidate.setdefault("data", {})
                if not isinstance(data, dict):
                    data = {}
                    candidate["data"] = data
                links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
                if node_id not in _workflow_explicit_storyboard_reference_node_ids(workflow_projection, candidate):
                    continue
                explicit_link_changed = False
                for link in links:
                    if not isinstance(link, dict):
                        continue
                    if str(link.get("sourceNodeId") or link.get("source_node_id") or "") != node_id:
                        continue
                    _apply_workflow_input_link_contract(link, source_node)
                    if _workflow_input_link_version_binding(link) == "pinned":
                        continue
                    before_pointer = (
                        str(link.get("status") or ""),
                        str(link.get("sourceVersionId") or ""),
                        str(link.get("mediaVersionId") or ""),
                    )
                    link["status"] = "linked"
                    link["sourceVersionId"] = updated["id"]
                    link["mediaVersionId"] = updated["id"]
                    after_pointer = (
                        str(link.get("status") or ""),
                        str(link.get("sourceVersionId") or ""),
                        str(link.get("mediaVersionId") or ""),
                    )
                    if after_pointer != before_pointer:
                        explicit_link_changed = True
                affected_video_task_ids.add(candidate_id)
                if explicit_link_changed:
                    data["status"] = _workflow_node_status_after_input_availability_change(
                        data.get("status"),
                        input_ready=True,
                    )
                    data["summary"] = data.get("summary") or "参考图已准备，可继续生成视频候选。"
        if _workflow_is_video_task_type(updated_node_type):
            version_status = str(updated.get("status") or "")
            version_ready = (
                version_status not in {"processing", "failed", "blocked", "cancelled", "canceled"}
                and bool(updated.get("media"))
            )
            version_failed = version_status in {"failed", "blocked", "cancelled", "canceled"}
            for result_node in workflow_projection.get("nodes", []):
                if not isinstance(result_node, dict) or str(result_node.get("type") or "") != "video.result":
                    continue
                result_node_id = str(result_node.get("id") or "").strip()
                result_data = result_node.setdefault("data", {})
                if not isinstance(result_data, dict):
                    result_data = {}
                    result_node["data"] = result_data
                input_links = result_data.get("inputLinks") if isinstance(result_data.get("inputLinks"), list) else []
                linked_to_source = (
                    str(result_data.get("resultOfNodeId") or result_data.get("sourceNodeId") or "") == node_id
                    or result_node_id in downstream_result_node_ids
                    or any(
                        isinstance(link, dict)
                        and str(link.get("sourceNodeId") or link.get("source_node_id") or "") == node_id
                        for link in input_links
                    )
                )
                if not linked_to_source:
                    continue
                result_versions = (
                    versions
                    if result_node_id == node_id
                    else read_card_results(project_id, episode_id, result_node_id)
                )
                result_active_version_id = _workflow_data_active_version_id(result_data)
                preserve_result_active = bool(
                    not version_ready
                    and result_active_version_id
                    and _workflow_active_version_has_usable_media(result_versions, result_data)
                )
                result_data["resultOfNodeId"] = node_id
                result_data["sourceNodeId"] = node_id
                result_data["sourceVersionId"] = result_active_version_id if preserve_result_active else updated["id"]
                if version_ready:
                    result_data["activeVersionId"] = updated["id"]
                    result_data["activeMediaVersionId"] = updated["id"]
                    result_data["mediaVersionId"] = updated["id"]
                    result_data["status"] = "ready"
                    result_data["summary"] = str(updated.get("summary") or "视频片段已生成。")
                    result_data["media"] = _persistent_media_data_removed(updated.get("media"))
                elif preserve_result_active:
                    result_data["status"] = _workflow_status_with_usable_active_media(result_data.get("status"))
                    result_data["summary"] = result_data.get("summary") or "视频片段已生成。"
                elif version_failed:
                    result_data["status"] = "failed"
                    result_data["summary"] = str(updated.get("summary") or updated.get("generationError") or "视频生成失败。")
                else:
                    result_data["status"] = "waiting"
                    result_data["summary"] = str(updated.get("summary") or "视频生成正在进行，等待视频片段。")
                for link in input_links:
                    if not isinstance(link, dict):
                        continue
                    if str(link.get("sourceNodeId") or link.get("source_node_id") or "") != node_id:
                        continue
                    link["sourceNodeType"] = updated_node_type
                    link["targetNodeId"] = result_node_id
                    link["targetNodeType"] = "video.result"
                    link["targetSlot"] = "video_result"
                    link["slot"] = "video_result"
                    link["sourceType"] = "generated_video"
                    if preserve_result_active:
                        link["sourceVersionId"] = result_active_version_id
                        link["mediaVersionId"] = result_active_version_id
                        link["status"] = "linked"
                    else:
                        link["sourceVersionId"] = updated["id"]
                        link["mediaVersionId"] = updated["id"]
                        link["status"] = "linked" if version_ready else "failed" if version_failed else "pending_generation"
                quality = result_data.get("quality") if isinstance(result_data.get("quality"), dict) else {}
                if quality.get("inputLinkBlockers") or quality.get("inputLinkStatus") == "blocked":
                    quality.pop("inputLinkBlockers", None)
                    if quality.get("inputLinkStatus") == "blocked":
                        quality.pop("inputLinkStatus", None)
                    result_data["quality"] = quality
        patched_nodes: list[dict[str, Any]] = []
        for item in workflow_projection.get("nodes", []) if isinstance(workflow_projection.get("nodes"), list) else []:
            if not isinstance(item, dict):
                continue
            current_id = str(item.get("id") or "")
            if not current_id:
                continue
            current_signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if before_node_signatures.get(current_id) != current_signature:
                patched_nodes.append(copy.deepcopy(item))
        patched_node_count = len(patched_nodes)
        save_result = commit_canvas_result_v4(
            project_id,
            episode_id,
            node_id=node_id,
            versions=versions,
            active_version_id=active_version_id,
            nodes=patched_nodes,
            changed_resources=["canvas_node", "canvas_version"],
        )
        updated["workflowVersion"] = save_result.get("workflowVersion")
        for key in ("txId", "seq", "revision", "baseRevision", "opType", "records", "changedResources"):
            if save_result.get(key) is not None:
                updated[key] = copy.deepcopy(save_result.get(key))
        return updated
    except Exception:
        status = "error"
        raise
    finally:
        canvas_perf_log(
            "update_storyboard_version_metadata",
            projectId=project_id,
            episodeId=episode_id,
            nodeId=node_id,
            versionId=str(version_id or ""),
            status=status,
            workflowSource=workflow_source,
            versionCount=version_count,
            patchedNodeCount=patched_node_count,
            durationMs=canvas_perf_elapsed_ms(perf_started_at),
        )


def _workflow_result_version_target_nodes(
    workflow: dict[str, Any],
    node_id: str,
    result_node_id: str = "",
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(candidate: dict[str, Any] | None) -> None:
        if not isinstance(candidate, dict):
            return
        candidate_type = str(candidate.get("type") or "").strip()
        if candidate_type not in {"storyboard.image", "video.result"} and not _workflow_visual_handoff_node_is_generated(candidate):
            return
        candidate_id = str(candidate.get("id") or "").strip()
        if not candidate_id or candidate_id in seen:
            return
        seen.add(candidate_id)
        result.append(candidate)

    if result_node_id:
        add(_workflow_node(workflow, result_node_id))
    add(_workflow_node(workflow, node_id))
    for edge in workflow.get("edges", []):
        if not isinstance(edge, dict) or str(edge.get("source") or "").strip() != node_id:
            continue
        add(_workflow_node(workflow, str(edge.get("target") or "").strip()))
    for item in workflow.get("nodes", []):
        if not isinstance(item, dict):
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if str(data.get("resultOfNodeId") or data.get("sourceNodeId") or "").strip() == node_id:
            add(item)
    return result


def _workflow_result_node_matches_sources(
    workflow: dict[str, Any],
    result_node: dict[str, Any] | None,
    source_node_ids: set[str],
) -> bool:
    if not isinstance(result_node, dict):
        return False
    result_node_id = str(result_node.get("id") or "").strip()
    if not result_node_id:
        return False
    if result_node_id in source_node_ids:
        return True
    data = result_node.get("data") if isinstance(result_node.get("data"), dict) else {}
    linked_source_id = str(data.get("resultOfNodeId") or data.get("sourceNodeId") or "").strip()
    if linked_source_id in source_node_ids:
        return True
    for edge in workflow.get("edges", []):
        if not isinstance(edge, dict):
            continue
        if str(edge.get("target") or "").strip() != result_node_id:
            continue
        if str(edge.get("source") or "").strip() in source_node_ids:
            return True
    return False


def set_storyboard_result_active_version(
    project_id: str,
    episode_id: str,
    node_id: str,
    version_id: str,
    result_node_id: str = "",
) -> dict[str, Any]:
    node_id = str(node_id or "").strip()
    version_id = str(version_id or "").strip()
    result_node_id = str(result_node_id or "").strip()
    if not episode_id:
        raise ValueError("缺少 episodeId")
    if not node_id:
        raise ValueError("缺少 nodeId")
    if not version_id:
        raise ValueError("缺少 versionId")

    with _JSON_WRITE_LOCK:
        workflow = read_canvas_task_context_v4(
            project_id,
            episode_id,
            result_node_id or node_id,
            detail="full",
            include_input_consumers=True,
            consumer_source_node_ids={node_id, result_node_id} - {""},
        )
        versions = read_card_results(project_id, episode_id, node_id)
        if result_node_id and result_node_id != node_id:
            versions.extend(read_card_results(project_id, episode_id, result_node_id))
        allowed_node_ids = {node_id}
        if result_node_id:
            allowed_node_ids.add(result_node_id)
        selected_version = next(
            (
                item
                for item in versions
                if isinstance(item, dict)
                and str(item.get("id") or "") == version_id
                and str(item.get("nodeId") or "") in allowed_node_ids
            ),
            None,
        )
        if not selected_version:
            raise FileNotFoundError("版本不存在")
        if not selected_version.get("media") and not selected_version.get("preview"):
            raise ValueError("该版本没有可显示的媒体内容")
        selected_media = selected_version.get("media") if isinstance(selected_version.get("media"), dict) else {}
        selected_kind = str(
            selected_version.get("kind")
            or selected_media.get("kind")
            or selected_media.get("mediaType")
            or selected_media.get("media_type")
            or ""
        ).strip().lower()
        selected_mime = str(selected_media.get("mimeType") or selected_media.get("mime_type") or "").strip().lower()
        is_video_version = selected_kind == "video" or selected_mime.startswith("video/")
        requested_result_node = _workflow_node(workflow, result_node_id) if result_node_id else None
        requested_is_visual_handoff = _workflow_visual_handoff_node_is_generated(requested_result_node)
        result_label = "视觉交接图" if requested_is_visual_handoff else "视频片段" if is_video_version else "分镜图"
        version_label = "视觉交接图版本" if requested_is_visual_handoff else "视频版本" if is_video_version else "分镜图版本"

        version_node_id = str(selected_version.get("nodeId") or node_id).strip()
        source_node_ids = {node_id, version_node_id} - {""}
        if result_node_id:
            result_node = _workflow_node(workflow, result_node_id)
            if not _workflow_result_node_matches_sources(workflow, result_node, source_node_ids):
                raise ValueError("结果卡与版本归属节点不匹配")
        target_nodes = _workflow_result_version_target_nodes(
            workflow,
            version_node_id,
            result_node_id,
        )
        if not target_nodes and version_node_id != node_id:
            target_nodes = _workflow_result_version_target_nodes(
                workflow,
                node_id,
                result_node_id,
            )
        if not target_nodes:
            raise FileNotFoundError(f"未找到对应的{result_label}")
        target_node = target_nodes[0]
        target_node_id = str(target_node.get("id") or "").strip()
        data = target_node.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            target_node["data"] = data
        previous_active_is_usable = _workflow_active_version_has_usable_media(versions, data)
        if target_node_id != version_node_id:
            data.setdefault("resultOfNodeId", version_node_id)
            data.setdefault("sourceNodeId", version_node_id)
        data["activeVersionId"] = version_id
        data["activeMediaVersionId"] = version_id
        data["mediaVersionId"] = version_id
        data["sourceVersionId"] = version_id
        data["status"] = "ready"
        data["summary"] = str(selected_version.get("summary") or data.get("summary") or f"已切换{version_label}。")
        if isinstance(selected_version.get("media"), dict):
            data["media"] = _persistent_media_data_removed(selected_version.get("media"))
            data["mediaId"] = str(selected_media.get("id") or data.get("mediaId") or "")
        else:
            data.pop("media", None)
            data.pop("mediaId", None)
        data.pop("storage", None)

        links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
        for link in links:
            if not isinstance(link, dict):
                continue
            source_id = str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip()
            if source_id and source_id not in {node_id, version_node_id}:
                continue
            link["sourceVersionId"] = version_id
            link["mediaVersionId"] = version_id
            link["status"] = "linked"

        affected_node_ids: set[str] = set()
        cross_episode_link: dict[str, Any] = {}
        if _workflow_visual_handoff_node_is_generated(target_node):
            for node in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
                if not isinstance(node, dict) or str(node.get("type") or "") not in _VISUAL_HANDOFF_TARGET_NODE_TYPES:
                    continue
                node_data = node.setdefault("data", {})
                if not isinstance(node_data, dict):
                    node_data = {}
                    node["data"] = node_data
                input_links = node_data.get("inputLinks") if isinstance(node_data.get("inputLinks"), list) else []
                link_updated = False
                for link in input_links:
                    if not isinstance(link, dict):
                        continue
                    if str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip() != target_node_id:
                        continue
                    slot = str(link.get("targetSlot") or link.get("slot") or "").strip()
                    if slot != _VISUAL_HANDOFF_SLOT:
                        continue
                    _apply_workflow_input_link_contract(link, target_node)
                    if _workflow_input_link_version_binding(link) == "pinned":
                        continue
                    link_updated = True
                    link["status"] = "linked"
                    link["sourceVersionId"] = version_id
                    link["mediaVersionId"] = version_id
                    if selected_media:
                        link["mediaId"] = str(selected_media.get("id") or link.get("mediaId") or "")
                        link["mediaType"] = str(selected_media.get("kind") or selected_media.get("mediaType") or "image")
                        link["mediaKind"] = link["mediaType"]
                        path = str(
                            selected_media.get("relativePath")
                            or selected_media.get("relative_path")
                            or selected_media.get("file")
                            or selected_media.get("path")
                            or selected_media.get("filePath")
                            or selected_media.get("file_path")
                            or ""
                        ).strip()
                        if path:
                            link["path"] = path
                if link_updated:
                    refs: list[str] = []
                    for link in input_links:
                        if isinstance(link, dict):
                            refs = _append_unique_string(refs, _link_reference_media_id(link))
                    node_data["referenceMediaIds"] = refs
                    node_data["summary"] = node_data.get("summary") or "视觉交接图已更新，可用于判断本工作链开头空间连续性。"
                    affected_node_ids.add(str(node.get("id") or "").strip())
            if selected_media:
                try:
                    cross_episode_link = sync_visual_handoff_cross_episode_link(
                        project_id,
                        episode_id,
                        target_node,
                        selected_version,
                        allow_auto_link=not previous_active_is_usable,
                    )
                    if isinstance(cross_episode_link, dict) and cross_episode_link:
                        selected_version["crossEpisodeLink"] = cross_episode_link
                except Exception:
                    print(traceback.format_exc(), flush=True)

        patched_nodes = [copy.deepcopy(target_node)]
        for node in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
            if not isinstance(node, dict):
                continue
            current_node_id = str(node.get("id") or "").strip()
            if current_node_id in affected_node_ids and current_node_id != target_node_id:
                patched_nodes.append(copy.deepcopy(node))
        save_result = commit_canvas_result_v4(
            project_id,
            episode_id,
            node_id=version_node_id,
            versions=versions,
            active_version_id=version_id,
            nodes=patched_nodes,
            changed_resources=["canvas_node", "canvas_version"],
        )
        workflow["version"] = save_result.get("workflowVersion") or workflow.get("version")
        return {
            "success": True,
            "episodeId": episode_id,
            "nodeId": version_node_id,
            "resultNodeId": target_node_id,
            "version": copy.deepcopy(selected_version),
            "node": copy.deepcopy(target_node),
            "nodes": patched_nodes,
            "workflowVersion": workflow.get("version"),
            "txId": save_result.get("txId"),
            "seq": save_result.get("seq"),
            "revision": save_result.get("revision"),
            "opType": save_result.get("opType"),
            "records": save_result.get("records"),
            "changedResources": save_result.get("changedResources") or ["canvas_node", "canvas_version"],
            "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": target_node_id},
            "crossEpisodeLink": copy.deepcopy(cross_episode_link) if isinstance(cross_episode_link, dict) else {},
        }


def _storyboard_image_edit_candidate_node_ids(
    workflow: dict[str, Any],
    node_id: str,
) -> list[str]:
    result: list[str] = []

    def add(value: Any) -> None:
        current = str(value or "").strip()
        if current and current not in result:
            result.append(current)

    add(node_id)
    node = _workflow_node(workflow, node_id) or {}
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    add(data.get("resultOfNodeId"))
    add(data.get("sourceNodeId"))
    add(resolve_generation_task_node_id(workflow, "storyboard_image", node_id))
    for edge in workflow.get("edges", []):
        if not isinstance(edge, dict) or str(edge.get("source") or "") != str(node_id):
            continue
        target_id = str(edge.get("target") or "").strip()
        target = _workflow_node(workflow, target_id)
        if target and str(target.get("type") or "") in _STORYBOARD_REFERENCE_NODE_TYPES:
            add(target_id)
    for item in workflow.get("nodes", []):
        if not isinstance(item, dict) or str(item.get("type") or "") not in _STORYBOARD_REFERENCE_NODE_TYPES:
            continue
        item_data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if str(item_data.get("resultOfNodeId") or item_data.get("sourceNodeId") or "") == str(node_id):
            add(item.get("id"))
    return result


def _is_work_chain_storyboard_result_image_node(node: dict[str, Any] | None) -> bool:
    if not isinstance(node, dict) or _workflow_image_node_type(node) not in _STORYBOARD_REFERENCE_NODE_TYPES:
        return False
    return not _workflow_node_is_independent_image_asset(node)


def _is_canvas_editable_image_node(node: dict[str, Any] | None) -> bool:
    node_type = _workflow_image_node_type(node)
    if node_type not in {"asset.image", "media.external", "storyboard.image"}:
        return False
    if node_type != "media.external":
        return True
    data = node.get("data") if isinstance(node, dict) and isinstance(node.get("data"), dict) else {}
    media = data.get("media") if isinstance(data.get("media"), dict) else data.get("storage")
    media_kind = str(
        (media or {}).get("kind")
        or (media or {}).get("mediaType")
        or (media or {}).get("media_type")
        or ""
    ).strip().lower() if isinstance(media, dict) else ""
    return media_kind != "video"


def _workflow_image_node_media(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(node, dict):
        return None
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    for key in ("media", "storage"):
        value = data.get(key)
        if isinstance(value, dict) and value:
            return copy.deepcopy(value)
    return None


def _workflow_canvas_image_asset_generation_type(
    data: dict[str, Any],
    payload: dict[str, Any],
) -> str:
    for value in (
        data.get("rootAssetType"),
        payload.get("assetType"),
        payload.get("asset_type"),
        data.get("assetType"),
        data.get("asset_type"),
        data.get("assetKind"),
        data.get("asset_kind"),
        data.get("mediaPurpose"),
        data.get("media_purpose"),
        data.get("preferredTargetSlot"),
        data.get("preferred_target_slot"),
    ):
        asset_type = _workflow_canvas_project_asset_type_from_value(value)
        if asset_type:
            return asset_type
    return ""


def _canvas_storyboard_generation_payload(
    project_id: str,
    template_id: str,
    user_instruction: str,
) -> dict[str, Any]:
    layout_spec = storyboard_template_layout_spec(template_id)
    render_spec = build_storyboard_render_spec(get_effective_config(project_id), layout_spec)
    template_label = storyboard_template_label(template_id)
    prompt = "\n\n".join((
        "【任务】\n根据用户内容生成一张完整分镜图工作页。"
        "本次没有外部分镜脚本，先依据用户内容在内部组织镜头计划，再按所选版式绘制。"
        "用户已指定的镜头数量、顺序、主体、动作和画面要求必须保留；"
        "未指定的镜头细节可为表达内容进行必要补全，不添加无关剧情。"
        "下文版式规则中的分镜脚本均指本次依据用户内容组织的镜头计划。"
        "只输出图片，不输出文字形式的计划或说明。",
        f"【用户内容】\n{user_instruction.strip()}",
        f"【分镜图版式：{template_label}】\n{storyboard_template_prompt_rules(template_id)}",
        f"【画幅与语言】\n{_storyboard_template_layout_block(template_id, render_spec)}",
        "【参考图】\n若提供参考图，按用户说明参考主体外观、场景或道具；"
        "参考图的拼接布局、文字和边框不作为输出版式，输出始终采用本次所选版式。",
    ))
    return {
        "storyboardImagePrompt": prompt,
        "storyboardTemplate": template_id,
        "storyboardTemplateLabel": template_label,
        "storyboardTemplateLayoutSpec": layout_spec,
        "storyboardRenderSpec": render_spec,
        "storyboardPromptSpec": {
            "format": "storyboard_panel_sequence",
            "template": template_id,
            "layoutKind": storyboard_template_layout_kind(template_id),
        },
    }


def _workflow_canvas_image_asset_generation_prompt(
    project_id: str,
    asset_type: str,
    data: dict[str, Any],
    payload: dict[str, Any],
    title: str,
    edit_prompt: str,
    *,
    request_size: Any = None,
    reference_file_count: int,
) -> str:
    asset_name = (
        str(payload.get("assetName") or payload.get("asset_name") or "").strip()
        or str(data.get("assetName") or data.get("asset_name") or "").strip()
        or title
    )
    prompt_text = edit_prompt.strip()
    asset = {
        "id": str(data.get("assetId") or data.get("asset_id") or "").strip(),
        "name": asset_name or title or "未命名资产",
        "desc": prompt_text,
        "prompts": {"assetImagePrompt": prompt_text},
    }
    request_size = str(
        payload.get("size") or payload.get("resolution") or request_size or ""
    ).strip() or None
    result = _asset_generation_prompt(
        project_id,
        asset_type,
        asset,
        None,
        None,
        request_size,
        hide_turnaround_heads=asset_type == "characters" and payload.get("hideTurnaroundHeads") is True,
    )
    if reference_file_count:
        result = (
            f"{result}\n\n"
            "【上传参考图】\n"
            "结合本次上传参考图中的风格、局部元素或细节生成，但必须继续遵守上述资产类型的构图与展示规则。"
        )
    return re.sub(r"\n{3,}", "\n\n", result).strip()


def _canvas_image_edit_task_message(title: str, status: str) -> str:
    title = _compact_text(title, 80) or "图片"
    if status == "completed":
        return f"图片「{title}」编辑完成。"
    if status == "failed":
        return f"图片「{title}」编辑失败。"
    return f"正在编辑图片「{title}」。"


def _append_canvas_project_asset_media_version(
    project_id: str,
    episode_id: str,
    node_id: str,
    node: dict[str, Any],
    media: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    asset_info = _workflow_canvas_project_asset_info(node)
    if not asset_info:
        return None
    asset_type = asset_info["assetType"]
    asset_id = asset_info["assetId"]
    path = _asset_store_path("project", project_id)
    with _JSON_WRITE_LOCK:
        assets = _read_json(path, copy.deepcopy(DEFAULT_ASSETS))
        if not isinstance(assets, dict):
            assets = copy.deepcopy(DEFAULT_ASSETS)
        for current_type in ASSET_TYPES:
            if not isinstance(assets.get(current_type), list):
                assets[current_type] = []
        rows = assets.get(asset_type)
        if not isinstance(rows, list):
            raise FileNotFoundError("资产类型不存在")
        asset = next(
            (
                item
                for item in rows
                if isinstance(item, dict)
                and str(item.get("id") or "") == asset_id
            ),
            None,
        )
        if not isinstance(asset, dict):
            raise FileNotFoundError("项目资产不存在")
        if _asset_is_offline(asset):
            raise ValueError("下线资产不参与视频工作流，请先恢复到活跃组")
        _normalize_asset_item_for_storage(project_id, asset)
        versions = _ensure_asset_media_versions(asset)
        previous_active_id = str(asset.get("activeMediaVersionId") or "").strip()
        previous_media = (
            copy.deepcopy(asset.get("media"))
            if isinstance(asset.get("media"), dict)
            else None
        )
        normalized_media = _normalize_media_asset(project_id, media) or copy.deepcopy(media)
        clean_media = _persistent_media_data_removed(normalized_media)
        if not isinstance(clean_media, dict):
            raise RuntimeError("图片模型未返回可用图片数据")
        version_title = str(
            metadata.get("title") or f"{asset_info.get('assetName') or '资产'} 画布编辑版"
        )
        asset_version = _asset_media_version(
            clean_media,
            version_title,
            snapshot=asset,
        )
        if not asset_version:
            raise RuntimeError("资产版本创建失败")
        asset_version["summary"] = str(metadata.get("summary") or "")
        asset_version["source"] = str(metadata.get("source") or "canvas-image-edit")
        asset_version["payload"] = _persistent_media_data_removed(
            {
                **(
                    metadata.get("payload")
                    if isinstance(metadata.get("payload"), dict)
                    else {}
                ),
                "versionSource": "project_asset",
                "canvasInstanceOnly": True,
                "canvasNodeId": node_id,
                "episodeId": episode_id,
                "assetType": asset_type,
                "assetId": asset_id,
                "assetName": asset_info.get("assetName") or asset.get("name") or "",
            }
        )
        for key in ("model", "provider", "generationDebug", "generationError"):
            if metadata.get(key) is not None:
                asset_version[key] = _persistent_media_data_removed(metadata.get(key))
        versions.append(asset_version)
        asset["mediaVersions"] = versions
        if previous_active_id:
            asset["activeMediaVersionId"] = previous_active_id
        if previous_media:
            asset["media"] = previous_media
        _write_json(path, assets)
        _touch_project_meta(project_id)
    row = _asset_media_version_as_storyboard_version(
        project_id,
        episode_id,
        node_id,
        asset_info,
        asset_version,
    )
    return row
