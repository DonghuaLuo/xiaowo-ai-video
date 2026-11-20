# -*- coding: utf-8 -*-
"""视频生成生成的上下文、提示词、写回与时长同步编排。"""
from __future__ import annotations
from .canvas_ownership import VIDEO_TASK_NODE_TYPES

import copy
from utils.video_prompt_mentions import bind_generated_prompt_mentions
from .canvas_ownership import (
    video_task_scope as canvas_video_task_scope,
)
from .canvas_store_queries import read_canvas_task_context_v4, read_canvas_card_record_v4
from .canvas_store_mutations import write_canvas_card_records_v4
from .generation_config import (
    _video_task_card_target_model_context,
)
from .generation_input_context import (
    _work_chain_video_task_ids_for_director,
    _truthy_payload_flag,
    _video_generation_node_id_from_payload,
    _workflow_node_by_id,
    _workflow_node_data_dict,
    _workflow_node_type_name,
)
from .model_provider_config import _api_model_name
from .planning_contract import _workflow_timing_number
from .projects import (
    _touch_project_meta,
)
from .source_text_store import _compact_text
from .store_core import (
    _JSON_WRITE_LOCK,
    _now,
)
from .video_task_card_context import _prepare_video_task_card_context
from .video_task_card_prompts import (
    VIDEO_TASK_CARD_INTERMEDIATE_CONTRACT,
    VIDEO_TASK_CARD_PROMPT_HASH_BASIS_VERSION,
    VIDEO_TASK_CARD_PROMPT_TEMPLATE_VERSION,
    _video_task_card_compact_intermediate_rows,
    _video_task_card_content_hash,
    _video_task_card_intermediate_plan_hash,
    _video_task_card_source_prompt_from_context,
)
from .video_task_card_references import VideoTaskCardReferences, _resolve_video_task_card_references
from .workflow_edit_history import record_video_prompt_edit_history
from typing import (
    Any,
)
from utils.media_backends import (
    video_prompt_char_limit,
)


def _video_task_card_node_id_for_worker(
    workflow: dict[str, Any],
    payload: dict[str, Any],
) -> str:
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    node = _workflow_node_by_id(workflow, node_id) if node_id else None
    if node and _workflow_node_type_name(node) in VIDEO_TASK_NODE_TYPES:
        return node_id
    route_id = str(payload.get("routeId") or payload.get("route_id") or "").strip()
    work_chain_id = str(payload.get("workChainId") or payload.get("work_chain_id") or "").strip()
    candidates = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if _workflow_node_type_name(candidate) != "video.storyboard":
            continue
        data = _workflow_node_data_dict(candidate)
        if route_id and str(data.get("routeId") or "").strip() == route_id:
            return str(candidate.get("id") or "").strip()
        if work_chain_id and str(data.get("workChainId") or "").strip() == work_chain_id:
            return str(candidate.get("id") or "").strip()
    return ""








def sync_work_chain_video_duration(
    project_id: str,
    episode_id: str,
    director_node_id: str,
) -> dict[str, Any]:
    from .workflow_storyboard_prompts import _workflow_director_context_payload

    with _JSON_WRITE_LOCK:
        workflow = read_canvas_task_context_v4(project_id, episode_id, director_node_id, detail="full")
        director = _workflow_node_by_id(workflow, director_node_id)
        if not director or _workflow_node_type_name(director) != "director.board":
            raise ValueError("视频时长只能从分镜脚本同步")
        director_data = _workflow_node_data_dict(director)
        director_context = _workflow_director_context_payload(
            workflow,
            director,
        )
        patches = []
        for node_id in _work_chain_video_task_ids_for_director(workflow, director_node_id):
            node = _workflow_node_by_id(workflow, node_id) or {}
            data = _workflow_node_data_dict(node)
            assigned_shot_nos = data.get("shotNos") if isinstance(data.get("shotNos"), list) else []
            if not assigned_shot_nos:
                continue
            from .storyboard_allocation import _group_duration, director_shots_hash

            allocation = director_data.get("storyboardAllocation") if isinstance(director_data.get("storyboardAllocation"), dict) else {}
            shots = director_context.get("directorPlanShots") or []
            if allocation.get("directorPlanHash") != director_shots_hash(shots):
                continue
            if any(not isinstance(value, int) or value < 1 or value > len(shots) for value in assigned_shot_nos):
                continue
            selected_duration = _group_duration(project_id, node, [shots[number - 1] for number in assigned_shot_nos])
            if _workflow_timing_number(data.get("durationSeconds")) == selected_duration:
                continue
            patches.append({"id": node_id, "data": {"durationSeconds": selected_duration}})
        if not patches:
            return {"nodes": [], "changedResources": []}
        # Patch only the parameter; never replay an old prompt or asset snapshot.
        result = write_canvas_card_records_v4(project_id, episode_id, patches, merge_data=True)
        _touch_project_meta(project_id)
        return result


def _load_video_task_card_source(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    workflow: dict[str, Any] = {}
    if node_id:
        workflow = read_canvas_task_context_v4(project_id, episode_id, node_id, detail="full")
        if _workflow_node_type_name(_workflow_node_by_id(workflow, node_id) or {}) != "video.storyboard":
            node_id = _video_generation_node_id_from_payload(project_id, episode_id, payload, workflow=workflow)
            if node_id:
                workflow = read_canvas_task_context_v4(project_id, episode_id, node_id, detail="full")
    if not node_id:
        node_id = _video_generation_node_id_from_payload(project_id, episode_id, payload)
        if node_id:
            workflow = read_canvas_task_context_v4(project_id, episode_id, node_id, detail="full")
    if not node_id:
        raise ValueError("缺少视频生成 nodeId")
    if not workflow:
        workflow = read_canvas_task_context_v4(project_id, episode_id, node_id, detail="full")
    node = _workflow_node_by_id(workflow, node_id)
    if not node:
        raise FileNotFoundError("未找到视频生成节点")
    node_type = _workflow_node_type_name(node)
    if node_type != "video.storyboard":
        raise ValueError("当前节点不是视频生成")
    if canvas_video_task_scope(node) != "work_chain":
        raise ValueError("独立视频生成请使用编辑弹窗的优化提示词")
    data = _workflow_node_data_dict(node)
    existing_card = data.get("videoTaskCard") if isinstance(data.get("videoTaskCard"), dict) else {}
    return workflow, node, data, existing_card


def _compose_video_task_card_patch(
    project_id: str,
    episode_id: str,
    node: dict[str, Any],
    data: dict[str, Any],
    context: dict[str, Any],
    references: VideoTaskCardReferences,
    *,
    generated: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node_id = str(node.get("id") or "")
    reference_ids = references.reference_ids
    thumbnail_reference_ids = references.thumbnail_reference_ids
    asset_reference_media_ids = references.asset_reference_media_ids
    video_task_card_reference_patch = references.card_patch
    source_mode = "work_chain_director_plan"
    source_prompt_source = "director_plan_intermediate_model"
    final_prompt_source = "video_task_card_editor_formatter"
    content_hash = _video_task_card_content_hash(context, reference_ids)
    source_plan_hash = _video_task_card_intermediate_plan_hash(context)
    if not isinstance(generated, dict):
        raise ValueError("视频提示词结果必须由智能体提交")
    generated_intermediate_shots = generated["shots"]
    source_plan_meta = generated["modelMeta"]
    source_plan_meta["source"] = source_plan_meta.get("source") or "model_director_plan_intermediate"
    source_plan_meta["userInstruction"] = str(context.get("userInstruction") or "")
    source_plan_meta["generatedAt"] = _now()
    structured_shots = [
        {**row, "shotLabel": f"Shot {index:02d}"}
        for index, row in enumerate(generated_intermediate_shots, start=1)
    ]
    source_prompt = _video_task_card_source_prompt_from_context(context, structured_shots)
    target_model = _video_task_card_target_model_context(project_id, data, {}, include_timing=False)
    final_prompt_profile = str(target_model.get("finalPromptProfile") or "").strip()
    final_prompt = generated["prompt"]
    sound_prompt = generated.get("soundPrompt", "")
    if not final_prompt:
        raise RuntimeError("视频提示词组装失败，未得到可提交给视频模型的提示词")
    prompt_bindings = bind_generated_prompt_mentions(
        final_prompt, context["referenceManifest"], additional_texts=(sound_prompt,),
    )
    content_chars = len(final_prompt) + len(sound_prompt) + (1 if final_prompt and sound_prompt else 0)
    prompt_limit = video_prompt_char_limit(
        str(target_model.get("providerId") or ""),
        _api_model_name(str(target_model.get("modelId") or "")),
    )
    prompt_budget = {
        "limit": prompt_limit,
        "finalPromptProfile": final_prompt_profile,
        "originalCoreChars": len(source_prompt),
        "finalCoreChars": len(final_prompt),
        "originalFinalPromptChars": content_chars,
        "finalPromptChars": content_chars,
        "soundPromptChars": len(sound_prompt),
        "promptHardLimitChars": prompt_limit,
        "promptHardLimitExceeded": bool(prompt_limit and content_chars > prompt_limit),
        "finalPromptAlreadyPrepared": False,
        "finalPromptSource": final_prompt_source,
        "taskCardAssetReferencePromptIncluded": False,
        "taskCardVisibleFinalPromptChars": len(final_prompt),
        "taskCardVisiblePromptAssembly": {
            "source": "model_fused_shot_prompts",
            "structuredShotCount": len(structured_shots),
            "storyboardReferenceCount": len(thumbnail_reference_ids),
            "supplierLabelsAddedAtSubmission": True,
            "sourcePlanReused": bool(source_plan_meta.get("reused")),
        },
    }
    if prompt_budget["promptHardLimitExceeded"]:
        raise RuntimeError(
            f"视频正文与声音提示词共 {content_chars} 字符，"
            f"超过模型上限 {prompt_limit} 字符，已停止保存。"
        )
    source = "programmatic_final_provider_prompt"
    model_meta = {
        "source": source,
        "modelId": str(target_model.get("modelId") or ""),
        "modelName": str(target_model.get("label") or ""),
        "providerId": str(target_model.get("providerId") or ""),
        "endpoint": "",
        "finalPromptProfile": str(prompt_budget.get("finalPromptProfile") or ""),
        "promptBudget": copy.deepcopy(prompt_budget),
        "referencePlan": {
            "source": "video_task_card_reference_snapshot",
            "taskCardAssetReferencePromptIncluded": False,
            "resolvedReferenceCount": len(reference_ids),
            "storyboardReferenceCount": len(thumbnail_reference_ids),
            "assetReferenceCount": len(asset_reference_media_ids),
            "strategy": str(node.get("strategy") or data.get("strategy") or "storyboard_multi_shot"),
        },
    }
    if source_plan_meta:
        model_meta["sourcePlan"] = copy.deepcopy(source_plan_meta)
    quality_notes: list[str] = []
    if (context.get("boundaryPlan") or {}).get("mode") == "native_keyframe":
        reference_notes = (
            "本卡为单镜无切镜直续：提交前须绑定上一段实际末帧与本镜终态目标尾帧。"
            "原生首尾帧与普通分镜图、视觉交接图分属不同输入职责。"
        )
    elif not thumbnail_reference_ids:
        reference_notes = (
            "分镜图为可选参考，当前可直接按视频提示词和已绑定素材生成视频。"
            "如后续生成分镜图，提交视频时将使用其当前可用版本。"
        )
    elif int(target_model.get("maxReferenceImages") or 0) <= 1:
        reference_notes = (
            "分镜图负责镜头、站位、空间调度和画面中已呈现的资产外观；"
            "当前目标视频模型最多接收 1 张参考图，最终只发送整张分镜图，不会再假定独立角色、生物、场景或道具图片可见。"
            "故事板中的编号、箭头和辅助区只用于解释调度，不进入成片。"
        )
    else:
        reference_notes = (
            "分镜图负责镜头、站位和空间调度；角色、生物、场景、道具资产在模型参考图容量允许时由后端独立绑定；"
            "故事板中的编号、箭头和辅助区只用于解释调度，不进入成片。"
        )
    parameter_hints: dict[str, Any] = {}
    video_task_card_patch = {
        "source": source,
        "promptKind": "final_provider_prompt",
        "videoPromptKind": "final_provider_prompt",
        "dynamicPrompt": True,
        "manualEdited": False,
        "sourceAdapter": source_mode,
        "promptTemplateVersion": VIDEO_TASK_CARD_PROMPT_TEMPLATE_VERSION,
        "promptHashBasisVersion": VIDEO_TASK_CARD_PROMPT_HASH_BASIS_VERSION,
        "promptContentHash": content_hash,
        "sourcePlanContentHash": source_plan_hash,
        "contentHash": content_hash,
        "finalVideoPrompt": final_prompt,
        "soundPrompt": sound_prompt,
        **({"boundaryPlan": copy.deepcopy(context["boundaryPlan"])} if context.get("boundaryPlan") else {}),
        "usedSpeakerIds": generated["usedSpeakerIds"],
        "voiceDesign": generated["voiceDesign"],
        "assetNameMap": copy.deepcopy(context.get("assetNameMap") or {}),
        "promptBindings": prompt_bindings,
        "sourcePrompt": source_prompt,
        "sourcePromptSource": source_prompt_source,
        "modelId": str(model_meta.get("modelId") or ""),
        "modelName": str(model_meta.get("modelName") or ""),
        "providerId": str(model_meta.get("providerId") or ""),
        "endpoint": str(model_meta.get("endpoint") or ""),
        "finalPromptProfile": str(model_meta.get("finalPromptProfile") or ""),
        "referenceBindingNotes": reference_notes,
        "parameterHints": copy.deepcopy(parameter_hints),
        "qualityNotes": copy.deepcopy(quality_notes),
        "sourcePlanMeta": copy.deepcopy(source_plan_meta),
        **copy.deepcopy(video_task_card_reference_patch),
        "modelMeta": copy.deepcopy(model_meta),
        "shotPromptPlan": {
            "schemaVersion": 2,
            "intermediateContract": VIDEO_TASK_CARD_INTERMEDIATE_CONTRACT,
            "sourceMode": source_mode,
            "sourceAdapter": source_mode,
            "shots": _video_task_card_compact_intermediate_rows(generated_intermediate_shots),
        },
    }
    return video_task_card_patch


def _finish_video_task_card(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
    payload: dict[str, Any],
    context: dict[str, Any],
    references: VideoTaskCardReferences,
    video_task_card_patch: dict[str, Any],
) -> dict[str, Any]:
    node_id = str(node.get("id") or "")
    final_prompt = video_task_card_patch["finalVideoPrompt"]
    reference_record_patch = references.record_patch
    work_chain_duration = (
        (node.get("data") or {}).get("durationSeconds")
        if context.get("sourceMode") == "work_chain_director_plan"
        else None
    )
    if work_chain_duration is not None:
        video_task_card_patch = {**video_task_card_patch, "durationSeconds": work_chain_duration}
    data_patch = {
        "status": "ready",
        "summary": _compact_text(final_prompt, 180),
        "prompt": {"videoPrompt": final_prompt},
        **copy.deepcopy(reference_record_patch),
        "videoTaskCard": video_task_card_patch,
        **({"generationConfig": {"durationSeconds": work_chain_duration}} if work_chain_duration is not None else {}),
    }
    hydrated_node = copy.deepcopy(node)
    hydrated_data = hydrated_node.get("data") if isinstance(hydrated_node.get("data"), dict) else {}
    hydrated_node["data"] = hydrated_data
    for stale_key in ("videoPrompt", "videoPromptRaw"):
        hydrated_data.pop(stale_key, None)
    hydrated_data["prompt"] = {"videoPrompt": final_prompt}
    hydrated_card = hydrated_data.get("videoTaskCard") if isinstance(hydrated_data.get("videoTaskCard"), dict) else {}
    hydrated_card.update(copy.deepcopy(video_task_card_patch))
    for key, value in data_patch.items():
        if key in {"prompt", "videoTaskCard"}:
            continue
        hydrated_data[key] = (
            {**hydrated_data[key], **copy.deepcopy(value)}
            if isinstance(hydrated_data.get(key), dict) and isinstance(value, dict)
            else copy.deepcopy(value)
        )
    hydrated_data["videoTaskCard"] = hydrated_card
    write_back = _truthy_payload_flag(payload.get("writeBack"))
    save_result: dict[str, Any] = {}
    history_result: dict[str, Any] = {}
    changed_resources: list[str] = []
    if write_back:
        task_id = str(payload.get("taskId") or "").strip()
        if task_id:
            from .task_control import _begin_task_result_commit

            if not _begin_task_result_commit(task_id, message="正在保存视频提示词。"):
                raise RuntimeError("视频提示词生成任务已停止，结果未保存")
        with _JSON_WRITE_LOCK:
            previous_node = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
            prompt_card_patch = {
                key: value for key, value in video_task_card_patch.items()
                if key not in {
                    "referenceMediaIds", "assetReferenceMediaIds", "assetRefs", "assetRefsResolvedByInputLinks",
                    "referenceThumbnailCount", "assetThumbnailCount",
                }
            }
            data_patch = {
                "summary": _compact_text(final_prompt, 180),
                "prompt": {"videoPrompt": final_prompt},
                "videoTaskCard": prompt_card_patch,
                **({"generationConfig": {"durationSeconds": work_chain_duration}} if work_chain_duration is not None else {}),
            }
            save_result = write_canvas_card_records_v4(
                project_id,
                episode_id,
                [{"id": node_id, "data": data_patch}],
                merge_data=True,
            )
            hydrated_node = save_result["nodes"][0]
            history_result = record_video_prompt_edit_history(
                project_id, episode_id, hydrated_node, previous_node, "video_prompt_generated",
            )
            _touch_project_meta(project_id)
            workflow["version"] = save_result.get("workflowVersion") or workflow.get("version")
        changed_resources = ["canvas_node"]
        if history_result.get("item"):
            changed_resources.append("node_edit_history")
    return {
        'success': True,
        'ready': True,
        'dynamic': True,
        'projectId': project_id,
        'episodeId': episode_id,
        'nodeId': node_id,
        'node': hydrated_node,
        'nodes': [hydrated_node],
        'workflowVersion': workflow.get('version'),
        'txId': save_result.get('txId'),
        'seq': save_result.get('seq'),
        'revision': save_result.get('revision'),
        'opType': save_result.get('opType'),
        'records': save_result.get('records'),
        'changedResources': changed_resources,
        'editHistory': history_result.get('item'),
        'editHistoryItems': history_result.get('items') or [],
        'editHistoryWarning': history_result.get('error') or '',
        'data': data_patch,
        'videoTaskCard': copy.deepcopy(video_task_card_patch),
        'videoPrompt': final_prompt,
        'sourcePrompt': video_task_card_patch['sourcePrompt'],
        'sourcePlanContentHash': video_task_card_patch['sourcePlanContentHash'],
        'sourcePlanMeta': copy.deepcopy(video_task_card_patch['sourcePlanMeta']),
        'referenceBindingNotes': video_task_card_patch['referenceBindingNotes'],
        'parameterHints': copy.deepcopy(video_task_card_patch['parameterHints']),
        'qualityNotes': copy.deepcopy(video_task_card_patch['qualityNotes']),
        'shotPromptPlan': copy.deepcopy(video_task_card_patch['shotPromptPlan']),
        'modelMeta': copy.deepcopy(video_task_card_patch['modelMeta']),
        'storyboardInterpretationContract': copy.deepcopy(context.get('storyboardInterpretationContract') or {}),
    }
