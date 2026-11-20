# -*- coding: utf-8 -*-
"""Agent read/commit contract for a standalone video card's editor draft."""
from __future__ import annotations

import copy
import json
from typing import Any
from utils.video_prompt_mentions import agent_video_reference_options, canonicalize_editor_mentions, resolve_prompt_mentions, validate_agent_video_shot_mentions

from .agent_video_prompt_tools import _digest, _failure, video_prompt_submission_digest
from .canvas_ownership import video_task_scope
from .canvas_store_queries import read_canvas_card_record_v4, read_canvas_task_context_v4
from .generation_config import _video_task_card_target_model_context
from .prompt_asset_context import (
    _video_task_card_asset_name_map_from_inputs,
    _video_task_card_asset_voice_style_map,
    resolve_prompt_assets,
    video_task_voice_input_snapshot,
)
from .project_overview import get_project_narrator_voice_profile
from .store_core import _JSON_WRITE_LOCK
from .video_prompt_generation import deduplicate_video_prompt_voices, deduplicate_video_voice_prompt, normalize_video_prompt_voices
from .video_prompt_optimization import _draft_saved_voice_design, optimize_video_prompt_draft
from .video_task_card_prompts import (
    _video_task_card_compact_intermediate_rows,
    _video_task_card_format_voice_design_for_prompt,
    _video_task_card_timed_rows,
    _video_task_card_prompt_from_structured_shots,
)
from .video_task_card_references import video_task_card_current_reference_snapshot
from .workflow_input_resolution import _resolve_workflow_node_inputs_from_workflow


class VideoPromptDraftSuperseded(ValueError):
    """The persisted prompt changed after this turn locked its editor draft."""


def read_video_prompt_edit_digest(project_id: str, episode_id: str, node_id: str) -> str:
    node = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
    return video_prompt_edit_digest(node.get("data") or {})


def video_prompt_edit_digest(data: dict[str, Any]) -> str:
    card = data.get("videoTaskCard") or {}
    return _digest({
        "prompt": (data.get("prompt") or {}).get("videoPrompt"),
        "card": {key: card.get(key) for key in (
            "finalVideoPrompt", "soundPrompt", "promptBindings", "voiceDesign", "usedSpeakerIds", "shotPromptPlan", "voiceOverrides",
        )},
    })


def _require_current_editor_draft(project_id: str, episode_id: str, node_id: str, baseline: str) -> None:
    if baseline and read_video_prompt_edit_digest(project_id, episode_id, node_id) != baseline:
        raise VideoPromptDraftSuperseded(
            "卡片提示词已在本次优化开始后被修改，本轮编辑稿已过期；已停止旧稿写入，请从当前编辑稿重新发起优化"
        )


def _source_card_text(node_type: str, data: dict[str, Any]) -> str:
    """Choose one authoritative creative value instead of serializing a whole card."""
    preferred = {
        "source.text": ("sourceText", "text"),
        "prompt.storyboard": ("cinematicStoryText", "sourceFactText"),
        "director.board": ("directorPlanShots", "directorPlan"),
    }.get(node_type, ())
    for key in (*preferred, "content", "text", "script", "storyboard", "prompt", "summary", "description"):
        value = data.get(key)
        if key == "prompt" and isinstance(value, dict):
            value = value.get("videoPrompt") or value.get("storyboardPrompt") or value.get("text")
        if isinstance(value, str) and value.strip():
            return value[:12000]
        if isinstance(value, (list, dict)) and value:
            return json.dumps(value, ensure_ascii=False, default=str)[:12000]
    return ""


def _project_video_context(public: dict[str, Any], part: str, *, standalone: bool) -> dict[str, Any]:
    allowed = {"asset_names", "references", "voice_context", "target_model", "current_prompt", "submission_state"}
    allowed.add("source_cards" if standalone else "draft_text")
    if part not in allowed:
        return _failure("part", "invalid_part", "请选择明确的独立视频卡资料类型", "revise_and_resubmit")
    if part == "draft_text":
        return {"success": True, "draftText": public["draftText"], "soundPrompt": public["soundPrompt"],
                "inputDigest": public["inputDigest"],
                **({"currentShotPromptPlan": public["currentShotPromptPlan"]}
                   if public.get("currentShotPromptPlan") else {})}
    if part == "source_cards":
        return {"success": True, "sourceCards": public["sourceCards"], "inputDigest": public["inputDigest"]}
    if part == "asset_names":
        return {"success": True, "assetNameMap": public["assetNameMap"],
                "excludedAssets": public.get("excludedAssets") or []}
    if part == "references":
        return {"success": True, "promptBindings": public["promptBindings"],
                **agent_video_reference_options(public["referenceManifest"]),
                "hasStoryboardReference": public["hasStoryboardReference"]}
    if part == "voice_context":
        return {"success": True, "knownSpeakers": public["knownSpeakers"],
                "fallbackAssetSpeakers": public["fallbackAssetSpeakers"],
                "preservedVoices": public["preservedVoices"], "soundPrompt": public["soundPrompt"],
                "taskVoiceStyles": public.get("taskVoiceStyles") or {}}
    if part == "target_model":
        return {"success": True, "targetModel": {
            key: public["targetModel"].get(key) for key in (
                "modelId", "finalPromptProfile", "maxReferenceImages", "allowedDurations",
            )
        }, "clipDurationSeconds": public["clipDurationSeconds"]}
    if part == "current_prompt":
        return {"success": True, "currentFinalVideoPrompt": public["currentFinalVideoPrompt"],
                "currentSoundPrompt": public.get("currentSoundPrompt", ""),
                **({"currentShotPromptPlan": public["currentShotPromptPlan"]}
                   if public.get("currentShotPromptPlan") else {})}
    return {"success": True, "inputDigest": public["inputDigest"]}


def _read_context(project_id: str, episode_id: str, node_id: str, draft_text: str,
                  asset_name_map: Any, prompt_bindings: Any, expected_canvas_kind: str = "",
                  *, allow_empty_draft: bool = False, sound_prompt: str | None = None):
    if not episode_id or not node_id:
        raise ValueError("必须明确提供 episodeId 和 nodeId")
    if not isinstance(draft_text, str) or (not draft_text.strip() and not allow_empty_draft):
        raise ValueError("请先输入需要优化的视频提示词")
    draft_text = canonicalize_editor_mentions(draft_text)
    if not isinstance(asset_name_map, dict) or any(
        not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip()
        for key, value in asset_name_map.items()
    ):
        raise ValueError("视频提示词的资产名称映射无效")
    if not isinstance(prompt_bindings, dict):
        raise ValueError("视频提示词的资产引用绑定无效")
    workflow = read_canvas_task_context_v4(project_id, episode_id, node_id, detail="full")
    node = next((row for row in workflow.get("nodes") or []
                 if isinstance(row, dict) and str(row.get("id") or "") == node_id), None)
    if not node:
        node = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
    if video_task_scope(node) != "standalone":
        raise ValueError("当前节点不是独立视频任务卡")
    if str(node.get("type") or "") not in {"video.storyboard", "video.keyframe"}:
        raise ValueError("当前节点不支持视频提示词优化")
    canvas_kind = str(workflow.get("canvasKind") or "episode")
    if expected_canvas_kind and canvas_kind != expected_canvas_kind:
        raise ValueError("当前画布类型已变化，请从原画布重新发起")
    inputs = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, node_id)
    names = _video_task_card_asset_name_map_from_inputs(inputs, project_id, asset_name_map=asset_name_map)
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    card = data.get("videoTaskCard") if isinstance(data.get("videoTaskCard"), dict) else {}
    voice_inputs = video_task_voice_input_snapshot(project_id, inputs, card)
    voice_names = _video_task_card_asset_name_map_from_inputs(
        voice_inputs, project_id, asset_name_map=asset_name_map,
    )
    references = video_task_card_current_reference_snapshot(
        project_id, episode_id, workflow, node_id, inputs, asset_name_map=names,
    )
    manifest = references.get("referenceManifest") or []
    if draft_text.strip():
        resolve_prompt_mentions(draft_text, prompt_bindings, manifest, require_transport=False)
    # Generation has no editor draft. A saved card still owns stable temporary
    # speaker identities; expose them when regenerating instead of inventing
    # new IDs. Optimization continues to honor the actual editor's voice edits.
    voice_text = str(card.get("soundPrompt") or "") if sound_prompt is None else sound_prompt
    if not isinstance(voice_text, str):
        raise ValueError("声音提示词必须是文本")
    voice_text = canonicalize_editor_mentions(voice_text)
    resolve_prompt_mentions(voice_text, prompt_bindings, manifest, require_transport=False)
    preserved = _draft_saved_voice_design(voice_text, card.get("voiceDesign"))
    profile = get_project_narrator_voice_profile(project_id)
    known = {"project:narrator": "旁白"} if profile["voiceStyle"] or profile.get("referenceAudio") else {}
    for speaker_id, override in (card.get("voiceOverrides") or {}).items():
        if isinstance(override, dict) and (override.get("voiceStyle") or override.get("referenceAudio")):
            known[speaker_id] = override.get("displayName") or speaker_id
    fallback_assets: dict[str, str] = {}
    for identity, row in resolve_prompt_assets(project_id, voice_inputs).items():
        if not row["exists"] or row["assetType"] not in {"characters", "creatures"}:
            continue
        speaker_id = f"asset:{identity}"
        display_name = ((card.get("voiceOverrides") or {}).get(speaker_id) or {}).get("displayName") or voice_names.get(identity) or row["displayName"]
        if row["voiceStyle"] or row.get("referenceAudio") or speaker_id in known:
            known[speaker_id] = display_name
        else:
            fallback_assets[speaker_id] = display_name
    preserved_rows: dict[str, dict[str, str]] = {}
    for row in preserved.get("speakers") or []:
        speaker_id = str(row.get("speakerId") or "").strip()
        if not speaker_id or speaker_id in known or (speaker_id.startswith("asset:") and speaker_id not in fallback_assets):
            continue
        preserved_rows[speaker_id] = copy.deepcopy(row)
        known[speaker_id] = row["displayName"]
    target_model = _video_task_card_target_model_context(project_id, data, {})
    public = {
        "episodeId": episode_id, "nodeId": node_id, "canvasKind": canvas_kind,
        "nodeType": str(node.get("type") or ""),
        "draftText": draft_text, "assetNameMap": names,
        "soundPrompt": voice_text,
        "excludedAssets": copy.deepcopy(inputs.get("excludedAssets") or []),
        "voiceAssetNameMap": voice_names, "promptBindings": copy.deepcopy(prompt_bindings),
        "referenceManifest": copy.deepcopy(manifest),
        "hasStoryboardReference": bool(references.get("referenceThumbnails")),
        "knownSpeakers": known, "fallbackAssetSpeakers": fallback_assets,
        "taskVoiceStyles": {key: {"displayName": row.get("displayName") or known.get(key) or key,
                                  "voiceStyle": row["voiceStyle"]}
                            for key, row in (card.get("voiceOverrides") or {}).items()
                            if isinstance(row, dict) and "voiceStyle" in row},
        "preservedVoices": preserved_rows,
        "currentFinalVideoPrompt": canonicalize_editor_mentions(str(card.get("finalVideoPrompt") or "")),
        "currentSoundPrompt": canonicalize_editor_mentions(str(card.get("soundPrompt") or "")),
        "targetModel": {key: copy.deepcopy(target_model.get(key)) for key in (
            "modelId", "providerId", "label", "finalPromptProfile", "maxReferenceImages",
            "allowedDurations",
        )},
        "clipDurationSeconds": data.get("durationSeconds") or card.get("durationSeconds"),
        "workflowVersion": workflow.get("version"),
    }
    saved_plan = card.get("shotPromptPlan")
    if (isinstance(saved_plan, dict) and isinstance(saved_plan.get("shots"), list)
            and saved_plan["shots"] and public["currentFinalVideoPrompt"] == draft_text):
        public["currentShotPromptPlan"] = copy.deepcopy(saved_plan)
    if allow_empty_draft:
        source_ids = {
            str(link.get("sourceNodeId") or "").strip()
            for link in inputs.get("inputLinks") or []
            if isinstance(link, dict)
        }
        public["sourceCards"] = []
        for source in workflow.get("nodes") or []:
            if not isinstance(source, dict) or str(source.get("id") or "").strip() not in source_ids:
                continue
            source_data = source.get("data") if isinstance(source.get("data"), dict) else {}
            source_text = _source_card_text(str(source.get("type") or ""), source_data)
            if not source_text:
                continue
            public["sourceCards"].append({
                "nodeId": source.get("id"), "nodeType": source.get("type"),
                "title": source.get("title") or source_data.get("title") or "",
                "readableData": source_text,
            })
    public["inputDigest"] = _digest({
        "public": public, "node": node, "inputs": inputs,
        "references": references, "targetModel": target_model,
    })
    return public, voice_inputs


def get_video_prompt_optimization_context(
    project_id: str, episode_id: str, node_id: str, *,
    draft_text: str, asset_name_map: Any, prompt_bindings: Any,
    expected_canvas_kind: str = "", part: str = "", expected_saved_prompt_digest: str = "",
    sound_prompt: str | None = None,
) -> dict[str, Any]:
    if part not in {"draft_text", "asset_names", "references", "voice_context", "target_model", "current_prompt", "submission_state"}:
        return _failure("part", "invalid_part", "请选择明确的独立视频卡资料类型", "revise_and_resubmit")
    try:
        _require_current_editor_draft(project_id, episode_id, node_id, expected_saved_prompt_digest)
        public, _ = _read_context(
            project_id, episode_id, node_id, draft_text, asset_name_map,
            prompt_bindings, expected_canvas_kind,
            sound_prompt=sound_prompt,
        )
    except VideoPromptDraftSuperseded as exc:
        return _failure("draftText", "editor_draft_superseded", str(exc), "stop")
    except (ValueError, FileNotFoundError, OSError) as exc:
        return _failure("nodeId/draftText", "context_unavailable", str(exc), "stop")
    return _project_video_context(public, part, standalone=False)


def get_video_prompt_standalone_context(
    project_id: str, episode_id: str, node_id: str, *, expected_canvas_kind: str = "", part: str = "",
) -> dict[str, Any]:
    if part not in {"source_cards", "asset_names", "references", "voice_context", "target_model", "current_prompt", "submission_state"}:
        return _failure("part", "invalid_part", "请选择明确的独立视频卡资料类型", "revise_and_resubmit")
    try:
        public, _ = _read_context(
            project_id, episode_id, node_id, "", {}, {}, expected_canvas_kind,
            allow_empty_draft=True,
        )
    except (ValueError, FileNotFoundError, OSError) as exc:
        return _failure("nodeId", "context_unavailable", str(exc), "stop")
    return _project_video_context(public, part, standalone=True)


def _generated_from_agent(project_id: str, public: dict[str, Any], voice_inputs: dict[str, Any],
                          shots: list[dict[str, Any]], used_speaker_ids: list[str],
                          voice_design: dict[str, Any], sound_prompt: str = "") -> dict[str, Any]:
    if not isinstance(sound_prompt, str):
        raise ValueError("声音提示词必须是文本")
    sound_prompt = canonicalize_editor_mentions(sound_prompt)
    manifest = public.get("referenceManifest") or []
    draft = str(public.get("draftText") or "")
    existing = {}
    for field_text in (draft, str(public.get("soundPrompt") or "")):
        existing.update(resolve_prompt_mentions(
            field_text, public.get("promptBindings") or {}, manifest, require_transport=False,
        ))
    validate_agent_video_shot_mentions(shots, manifest, existing_mentions=existing)
    rows = _video_task_card_timed_rows(
        [{} for _ in shots], shots, public["clipDurationSeconds"],
    )
    known = public["knownSpeakers"]
    fallback = public["fallbackAssetSpeakers"]
    used, design = normalize_video_prompt_voices(
        {"usedSpeakerIds": used_speaker_ids, "voiceDesign": voice_design}, known,
        fallback_asset_speakers=fallback,
    )
    design["speakers"] = [
        *[copy.deepcopy(row) for speaker_id, row in public["preservedVoices"].items() if speaker_id in used],
        *design["speakers"],
    ]
    speaker_names = {**fallback, **known, **{row["speakerId"]: row["displayName"] for row in design["speakers"]},
                     **{key: row["displayName"] for key, row in (public.get("taskVoiceStyles") or {}).items()}}
    used, design = deduplicate_video_prompt_voices(used_speaker_ids, design, speaker_names,
        preferred_ids=set(public.get("taskVoiceStyles") or {}))
    row_labels = [{**row, "shotLabel": f"Shot {index:02d}"} for index, row in enumerate(rows, start=1)]
    voices = _video_task_card_asset_voice_style_map(
        project_id, asset_names=public["voiceAssetNameMap"],
        input_snapshot=voice_inputs, speaker_ids=used,
    )
    voices.update({key: copy.deepcopy(row) for key, row in (public.get("taskVoiceStyles") or {}).items() if key in used})
    final_prompt = _video_task_card_prompt_from_structured_shots(row_labels)
    speaker_prompt = _video_task_card_format_voice_design_for_prompt(
        design, voices, fallback_asset_ids=set(fallback),
    )
    return {
        "shots": row_labels, "usedSpeakerIds": sorted(used),
        "voiceDesign": design, "prompt": final_prompt,
        "soundPrompt": deduplicate_video_voice_prompt("\n\n".join(part for part in (speaker_prompt, sound_prompt) if part),
            [speaker_names[key] for key in used]),
        "modelMeta": {"source": "agent_verified_video_prompt_optimization"},
    }


def submit_video_prompt_optimization_result(
    project_id: str, episode_id: str, node_id: str,
    shots: Any, used_speaker_ids: Any, voice_design: Any, input_digest: str, *,
    draft_text: str, asset_name_map: Any, prompt_bindings: Any,
    expected_canvas_kind: str = "", session_id: str, execution_id: str,
    allow_empty_draft: bool = False,
    draft_sound_prompt: str | None = None,
    sound_prompt: str = "",
    task_type: str = "video_prompt_optimization",
    expected_saved_prompt_digest: str = "",
) -> dict[str, Any]:
    if not input_digest:
        return _failure("inputDigest", "required", "缺少读取上下文返回的 inputDigest", "reread_context")
    if not session_id or not execution_id:
        return _failure("executionId", "execution_unavailable", "当前智能体执行轮次已失效", "stop")
    if not isinstance(shots, list) or not shots:
        return _failure("shots", "invalid_shots", "镜头结果必须为非空数组", "revise_and_resubmit")
    if not isinstance(used_speaker_ids, list) or not isinstance(voice_design, dict):
        return _failure("usedSpeakerIds/voiceDesign", "invalid_voice_result",
                        "声音身份和声音设计必须按结构化格式提交", "revise_and_resubmit")
    attempted = False
    expected_prompt = ""
    expected_sound_prompt = ""
    expected_rows: list[dict[str, Any]] = []
    saved: dict[str, Any] = {}
    try:
        with _JSON_WRITE_LOCK:
            _require_current_editor_draft(project_id, episode_id, node_id, expected_saved_prompt_digest)
            public, voice_inputs = _read_context(
                project_id, episode_id, node_id, draft_text, asset_name_map,
                prompt_bindings, expected_canvas_kind,
                allow_empty_draft=allow_empty_draft,
                sound_prompt=draft_sound_prompt,
            )
            if public["inputDigest"] != input_digest:
                return _failure("inputDigest", "stale_context",
                                "编辑草稿、画布、素材、声音或当前提示词已变化，请重新读取后提交", "reread_context")
            generated = _generated_from_agent(
                project_id, public, voice_inputs, shots, used_speaker_ids, voice_design, sound_prompt,
            )
            expected_prompt = generated["prompt"]
            expected_sound_prompt = generated.get("soundPrompt", "")
            expected_rows = _video_task_card_compact_intermediate_rows(generated["shots"])
            attempted = True
            saved = optimize_video_prompt_draft(
                project_id, episode_id, node_id,
                {"draftText": draft_text, "soundPrompt": draft_sound_prompt, "assetNameMap": asset_name_map,
                 "promptBindings": prompt_bindings},
                generated_result=generated,
                **({"allow_empty_draft": True} if allow_empty_draft else {}),
            )
    except Exception as exc:
        if isinstance(exc, VideoPromptDraftSuperseded):
            return _failure("draftText", "editor_draft_superseded", str(exc), "stop")
        if attempted:
            try:
                stored = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
                card = (stored.get("data") or {}).get("videoTaskCard") or {}
                if (card.get("soundPrompt", "") == expected_sound_prompt
                        and card.get("finalVideoPrompt") == expected_prompt
                        and (card.get("shotPromptPlan") or {}).get("shots") == expected_rows):
                    failed = _failure("nodeId", "commit_unverified",
                                      f"优化结果可能已写入，但后续步骤失败：{exc}；请回读画布", "stop")
                    failed.update({"status": "commit_unverified", "projectChanged": True,
                                   "changedResources": ["canvas_node"]})
                    return failed
            except Exception:
                failed = _failure("nodeId", "commit_unverified",
                                  f"优化结果提交后无法回读核验：{exc}", "stop")
                failed.update({"status": "commit_unverified", "projectChanged": True,
                               "changedResources": ["canvas_node"]})
                return failed
        if isinstance(exc, ValueError):
            return _failure("shots", "invalid_or_stale_result", str(exc),
                            "reread_context" if attempted else "revise_and_resubmit")
        if isinstance(exc, (FileNotFoundError, OSError)):
            return _failure("nodeId", "context_unavailable", str(exc), "stop")
        return _failure("nodeId", "program_error", str(exc), "stop")
    try:
        stored = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
        data = stored.get("data") if isinstance(stored.get("data"), dict) else {}
        card = data.get("videoTaskCard") if isinstance(data.get("videoTaskCard"), dict) else {}
        if (card.get("soundPrompt", "") != expected_sound_prompt
                or card.get("finalVideoPrompt") != expected_prompt
                or (card.get("shotPromptPlan") or {}).get("shots") != expected_rows
                or (data.get("prompt") or {}).get("videoPrompt") != expected_prompt):
            raise RuntimeError("优化提示词写入后回读不一致")
    except Exception as exc:
        failed = _failure("nodeId", "commit_unverified", str(exc), "stop")
        failed.update({"status": "commit_unverified", "projectChanged": True,
                       "changedResources": ["canvas_node"]})
        return failed
    output_digest = _digest({"finalVideoPrompt": expected_prompt, "soundPrompt": expected_sound_prompt,
                             "usedSpeakerIds": card.get("usedSpeakerIds"), "voiceDesign": card.get("voiceDesign")})
    receipt_id = _digest({"executionId": execution_id, "nodeId": node_id,
                          "inputDigest": input_digest, "outputDigest": output_digest})
    receipt = {
        "receiptId": receipt_id, "runId": execution_id,
        "projectId": project_id, "episodeId": episode_id,
        "sessionId": session_id, "executionId": execution_id,
        "taskType": task_type, "targetIds": [node_id],
        "inputDigest": input_digest, "outputDigest": output_digest,
        "submissionDigest": video_prompt_submission_digest(shots, used_speaker_ids, voice_design, sound_prompt),
        "shotCount": len(shots), "promptChars": len(expected_prompt),
        "changedResources": saved.get("changedResources") or ["canvas_node"],
    }
    return {
        "success": True, "status": "committed", "episodeId": episode_id, "nodeId": node_id,
        "shotCount": len(shots), "promptChars": len(expected_prompt),
        "receiptId": receipt_id, "commitReceipt": receipt,
        "changedResources": receipt["changedResources"], "projectChanged": True,
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id},
        **{key: copy.deepcopy(saved.get(key)) for key in (
            "txId", "seq", "revision", "opType", "records", "workflowVersion",
        ) if saved.get(key) is not None},
    }


def submit_video_prompt_standalone_result(
    project_id: str, episode_id: str, node_id: str,
    shots: Any, used_speaker_ids: Any, voice_design: Any, input_digest: str, *,
    expected_canvas_kind: str = "", session_id: str, execution_id: str,
    sound_prompt: str = "",
) -> dict[str, Any]:
    return submit_video_prompt_optimization_result(
        project_id, episode_id, node_id,
        shots, used_speaker_ids, voice_design, input_digest,
        draft_text="", asset_name_map={}, prompt_bindings={},
        expected_canvas_kind=expected_canvas_kind,
        session_id=session_id, execution_id=execution_id,
        allow_empty_draft=True,
        task_type="video_prompt_standalone_generation",
        sound_prompt=sound_prompt,
    )
