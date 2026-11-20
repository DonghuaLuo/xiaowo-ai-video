"""Optimize and persist an independent video task card prompt."""

import copy
from typing import Any
from utils.video_prompt_mentions import bind_generated_prompt_mentions, canonicalize_editor_mentions, resolve_prompt_mentions

from .canvas_ownership import video_task_scope
from .canvas_store_queries import read_canvas_card_record_v4, read_canvas_task_context_v4
from .video_task_card_references import video_task_card_current_reference_snapshot
from .prompt_asset_context import _video_task_card_asset_name_map_from_inputs
from .video_task_card_prompts import (
    VIDEO_TASK_CARD_INTERMEDIATE_CONTRACT,
    _video_task_card_compact_intermediate_rows,
)


def _draft_saved_voice_design(sound_prompt: str, saved_design: Any) -> dict[str, Any]:
    """Keep voice identities while honoring edits to the visible voice section."""
    if not isinstance(saved_design, dict):
        return {"speakers": []}
    lines = [line.strip() for line in sound_prompt.splitlines()]
    speakers = []
    for row in saved_design.get("speakers") or []:
        if not isinstance(row, dict) or not isinstance(row.get("displayName"), str):
            continue
        prefix = f"- {row['displayName'].strip()}："
        style = next((line[len(prefix):].strip() for line in lines if line.startswith(prefix)), "")
        if style:
            speakers.append({**row, "voiceStyle": style})
    return {"speakers": speakers}


def optimize_video_prompt_draft(project_id: str, episode_id: str, node_id: str, request: dict[str, Any], *,
                                generated_result: dict[str, Any] | None = None,
                                allow_empty_draft: bool = False) -> dict[str, Any]:
    from .workflow_inline_editing import save_workflow_node_inline_edit
    from .workflow_input_resolution import _resolve_workflow_node_inputs_from_workflow

    workflow = read_canvas_task_context_v4(project_id, episode_id, node_id, detail="full")
    node = next(
        (
            item for item in (workflow.get("nodes") or [])
            if isinstance(item, dict) and str(item.get("id") or "").strip() == node_id
        ),
        None,
    )
    if not isinstance(node, dict):
        node = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="summary")
    if video_task_scope(node) != "standalone":
        raise ValueError("仅独立视频生成支持优化编辑草稿")
    text = request.get("draftText")
    if not isinstance(text, str) or (not text.strip() and not (allow_empty_draft and generated_result is not None)):
        raise ValueError("请先输入需要优化的视频提示词")
    text = canonicalize_editor_mentions(text)
    # The optimizer receives the editor draft; supplier labels are applied later.
    draft_names = request.get("assetNameMap", {})
    if not isinstance(draft_names, dict) or any(
        not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip()
        for key, value in draft_names.items()
    ):
        raise ValueError("视频提示词的资产名称映射无效")
    inputs = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, node_id)
    asset_name_map = _video_task_card_asset_name_map_from_inputs(inputs, project_id, asset_name_map=draft_names)
    # Disabling a reference image leaves its speaker linked, as in director workflows.
    # Keep the full voice associations separate from enabled visual references.
    voice_inputs = {**inputs, "inputLinks": inputs.get("referenceDisplayRows", inputs.get("inputLinks", []))}
    voice_asset_names = _video_task_card_asset_name_map_from_inputs(
        voice_inputs, project_id, asset_name_map=draft_names,
    )
    reference_snapshot = video_task_card_current_reference_snapshot(
        project_id, episode_id, workflow, node_id, inputs, asset_name_map=asset_name_map,
    )
    manifest = reference_snapshot.get("referenceManifest") or []
    bindings = request.get("promptBindings", {})
    if not isinstance(bindings, dict):
        raise ValueError("视频提示词的资产引用绑定无效")
    node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
    saved_card = node_data.get("videoTaskCard") if isinstance(node_data.get("videoTaskCard"), dict) else {}
    draft_sound = request.get("soundPrompt")
    if draft_sound is None:
        draft_sound = str(saved_card.get("soundPrompt") or "")
    if not isinstance(draft_sound, str):
        raise ValueError("声音提示词必须是文本")
    existing_mentions = {}
    for field_text in (text, draft_sound):
        existing_mentions.update(resolve_prompt_mentions(field_text, bindings, manifest, require_transport=False))
    if not isinstance(generated_result, dict):
        raise ValueError("视频提示词结果必须由智能体提交")
    generated = generated_result
    rows = generated["shots"]
    final_prompt = generated["prompt"]
    final_bindings = bind_generated_prompt_mentions(
        final_prompt, manifest, existing_mentions=existing_mentions,
        additional_texts=(generated.get("soundPrompt", ""),),
    )
    task_id = str(request.get("taskId") or "").strip()
    if task_id:
        from .task_control import _begin_task_result_commit

        if not _begin_task_result_commit(
            task_id,
            message="正在保存优化后的视频提示词。",
            sync_canvas_task_record="none",
        ):
            raise RuntimeError("视频提示词优化任务已停止，结果未保存")

    video_task_card_patch = {
        "promptKind": "final_provider_prompt",
        "videoPromptKind": "final_provider_prompt",
        "source": "agent_generated_provider_prompt" if allow_empty_draft else "manual_final_provider_prompt",
        "finalVideoPrompt": final_prompt,
        "soundPrompt": generated.get("soundPrompt", ""),
        "assetNameMap": copy.deepcopy(asset_name_map),
        "promptBindings": final_bindings,
        "usedSpeakerIds": generated["usedSpeakerIds"],
        "voiceDesign": generated["voiceDesign"],
        "shotPromptPlan": {
            "schemaVersion": 2,
            "intermediateContract": VIDEO_TASK_CARD_INTERMEDIATE_CONTRACT,
            "sourceMode": "standalone",
            "shots": _video_task_card_compact_intermediate_rows(rows),
        },
        "manualEdited": not allow_empty_draft,
        "dynamicPrompt": False,
    }
    data_patch = {
        "prompt": {"videoPrompt": final_prompt},
        "videoTaskCard": video_task_card_patch,
    }
    save_result = save_workflow_node_inline_edit(
        project_id,
        episode_id,
        {
            "nodeId": node_id,
            "data": data_patch,
            "expectedRevision": workflow.get("version"),
            "source": "agent",
            "reason": "video_prompt_generated" if allow_empty_draft else "video_prompt_optimized",
        },
    )
    if save_result.get("skippedLocked") or save_result.get("projectChanged") is False:
        raise ValueError("视频生成已锁定，优化后的视频提示词未保存")
    result = {
        "success": True,
        "nodeId": node_id,
        "draftVideoPrompt": final_prompt,
        "assetNameMap": asset_name_map,
        "promptBindings": final_bindings,
        "shots": rows,
        "data": data_patch,
        "videoTaskCard": copy.deepcopy(video_task_card_patch),
        "changedResources": copy.deepcopy(save_result.get("changedResources") or ["canvas_node"]),
        "projectChanged": bool(save_result.get("projectChanged", True)),
    }
    for key in ("node", "workflowVersion", "txId", "seq", "revision", "opType", "records", "focusTarget", "editHistory", "editHistoryItems", "editHistoryWarning"):
        if key in save_result:
            result[key] = copy.deepcopy(save_result[key])
    return result
