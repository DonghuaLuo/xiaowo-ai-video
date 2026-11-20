# -*- coding: utf-8 -*-
"""Read one work-chain video task and commit an Agent-authored prompt without a model call."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any
from utils.video_prompt_mentions import agent_video_reference_options, canonicalize_editor_mentions, validate_agent_video_shot_mentions
from .canvas_store_queries import read_canvas_card_record_v4
from .generation_config import _video_task_card_target_model_context
from .prompt_asset_context import _video_task_card_asset_voice_style_map
from .store_core import _JSON_WRITE_LOCK
from .storyboard_allocation import assert_video_shot_allocation_current
from .storyboard_timing import speech_seconds
from .video_prompt_generation import deduplicate_video_prompt_voices, deduplicate_video_voice_prompt, normalize_video_prompt_voices
from .video_task_card_prompts import (
    VIDEO_TASK_CARD_INTERMEDIATE_CONTRACT,
    _director_plan_shot_rows_from_structured,
    _video_task_card_format_voice_design_for_prompt,
    _video_task_card_timed_rows,
    _video_task_card_prompt_from_structured_shots,
)
from .video_task_card_references import _resolve_video_task_card_references
from .video_task_card_context import _prepare_video_task_card_context
from .video_task_cards import (
    _compose_video_task_card_patch,
    _finish_video_task_card,
    _load_video_task_card_source,
)


def _locked_workchain_shot_durations(shots: list[dict[str, Any]], clip_duration: Any) -> list[float]:
    """Scale formal shot estimates to the current card length at 0.1-second precision."""
    target = float(clip_duration)
    target_ticks = round(target * 10)
    if abs(target_ticks / 10 - target) > 0.005:
        raise ValueError("视频卡时长无法按 0.1 秒精度分配")
    planned = [float(shot.get("durationSec") or 0) for shot in shots]
    if not planned or any(seconds <= 0 for seconds in planned):
        raise ValueError("正式分镜镜长无效")
    if target_ticks < len(planned):
        raise ValueError("视频卡时长无法给每镜分配至少 0.1 秒")
    planned_total = sum(planned)
    scaled = [seconds * target_ticks / planned_total for seconds in planned]
    ticks = [int(value) for value in scaled]
    for index in sorted(range(len(ticks)), key=lambda item: (-(scaled[item] - ticks[item]), item))[:target_ticks - sum(ticks)]:
        ticks[index] += 1
    for index, value in enumerate(ticks):
        if value > 0:
            continue
        donor = max((item for item, count in enumerate(ticks) if count > 1), key=lambda item: ticks[item], default=None)
        if donor is None:
            raise ValueError("视频卡时长无法给每镜分配至少 0.1 秒")
        ticks[index] = 1
        ticks[donor] -= 1
    return [value / 10 for value in ticks]


def _workchain_voice_timing_issues(shots: list[dict[str, Any]], locked_durations: list[float]) -> list[str]:
    """A video card may compress visual slack, but cannot accelerate normal speech."""
    issues: list[str] = []
    for index, (shot, duration) in enumerate(zip(shots, locked_durations), start=1):
        required = speech_seconds(shot, 1.0)
        if required > duration + 0.05:
            issues.append(f"镜头 {index} 正常发声至少需 {required:g} 秒，当前卡只分配 {duration:g} 秒")
    return issues


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _failure(path: str, code: str, message: str, repair_action: str) -> dict[str, Any]:
    return {
        "success": False, "status": "validation_failed", "message": message,
        "errors": [{"path": path, "code": code, "message": message, "repairAction": repair_action}],
        "projectChanged": False,
    }


_VIDEO_PROMPT_SHOT_FIELDS = (
    "shotNo", "durationSec", "visualPurpose", "storyboardFrame", "videoExecution", "endState",
    "entryBoundaryKind", "audioBoundaryKind", "assets", "visibleAssets", "startVisibleAssets",
    "screenTextEvents", "soundEvents", "presentation",
)


def _video_prompt_shot_projection(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Legacy decorations and per-shot medium overrides never enter new prompts."""
    projected = [{key: copy.deepcopy(shot[key]) for key in _VIDEO_PROMPT_SHOT_FIELDS if key in shot}
                 for shot in shots if isinstance(shot, dict)]
    for shot in projected:
        presentation = shot.get("presentation")
        if isinstance(presentation, dict):
            presentation.pop("visualTreatment", None)
    return projected


def _read_context(project_id: str, episode_id: str, node_id: str, user_instruction: str,
                  expected_route_id: str = "", expected_work_chain_id: str = ""):
    if not str(episode_id or "").strip() or not str(node_id or "").strip():
        raise ValueError("必须明确提供 episodeId 和 nodeId")
    workflow, node, data, old_card = _load_video_task_card_source(
        project_id, episode_id, {"nodeId": node_id},
    )
    if str(node.get("id") or "") != node_id:
        raise ValueError("视频任务目标与读取的节点不一致")
    references = _resolve_video_task_card_references(project_id, episode_id, workflow, node)
    payload = {"nodeId": node_id, "userInstruction": user_instruction}
    context = _prepare_video_task_card_context(
        project_id, episode_id, workflow, node, payload, references,
    )
    # A video task produces one clip for its assigned group. Individual director
    # shots are allowed to be shorter than the model's whole-clip duration slots.
    # Prompt drafting remains available when a selected video model cannot
    # produce this group's duration; production checks model support later.
    assert_video_shot_allocation_current(project_id, workflow, node, check_model_duration=False)
    target_model = _video_task_card_target_model_context(project_id, data, {}, include_timing=False)
    reference_total = sum(
        float(shot.get("durationSec") or 0) for shot in context["directorPlanShots"]
    )
    clip_duration = float(data.get("durationSeconds") or old_card.get("durationSeconds") or 0)
    locked_durations = _locked_workchain_shot_durations(context["directorPlanShots"], clip_duration)
    voice_timing_issues = _workchain_voice_timing_issues(context["directorPlanShots"], locked_durations)
    public = {
        "episodeId": episode_id, "nodeId": node_id,
        "nodeTitle": str(node.get("title") or data.get("title") or ""),
        "workChainId": str(node.get("workChainId") or data.get("workChainId") or ""),
        "routeId": str(node.get("routeId") or data.get("routeId") or ""),
        "directorPlanShots": _video_prompt_shot_projection(context["directorPlanShots"]),
        "assignedShotNos": copy.deepcopy(context["assignedShotNos"]),
        "clipDurationSeconds": data.get("durationSeconds") or old_card.get("durationSeconds"),
        "timingBudget": {
            "referenceTotalSeconds": round(reference_total, 3),
            "lockedShotDurations": locked_durations,
            "normalSpeechSeconds": [speech_seconds(shot, 1.0) for shot in context["directorPlanShots"]],
            "voiceTimingIssues": voice_timing_issues,
        },
        "speakerRoster": copy.deepcopy(context["speakerRoster"]),
        "directorRuleId": context["directorRuleId"],
        "continuityInstruction": context["continuityInstruction"],
        "boundaryPlan": copy.deepcopy(context["boundaryPlan"]),
        "userInstruction": context["userInstruction"],
        "assetNameMap": copy.deepcopy(context["assetNameMap"]),
        "voiceAssetNameMap": copy.deepcopy(context["voiceAssetNameMap"]),
        "assetVoiceDesign": copy.deepcopy(context["assetVoiceDesign"]),
        "referenceManifest": copy.deepcopy(context["referenceManifest"]),
        "hasStoryboardReference": context["hasStoryboardReference"],
        "storyboardInterpretationContract": copy.deepcopy(context["storyboardInterpretationContract"]),
        "targetModel": {key: copy.deepcopy(target_model.get(key)) for key in (
            "modelId", "providerId", "label", "finalPromptProfile", "maxReferenceImages",
        )},
        "currentFinalVideoPrompt": canonicalize_editor_mentions(str(old_card.get("finalVideoPrompt") or "")),
        "currentSoundPrompt": str(old_card.get("soundPrompt") or ""),
        "currentVoiceDesign": copy.deepcopy(old_card.get("voiceDesign") or {"speakers": []}),
    }
    if expected_route_id and public["routeId"] != expected_route_id:
        raise ValueError("视频任务所在路线已变化，请从当前画布重新发起")
    if expected_work_chain_id and public["workChainId"] != expected_work_chain_id:
        raise ValueError("视频任务所在工作链已变化，请从当前画布重新发起")
    # The digest includes the complete derived inputs and current destination, not just
    # the fields shown to the model. A changed binding, voice, model or manual edit
    # makes an older proposal stale before the write begins.
    public["inputDigest"] = _digest({
        "public": public,
        "context": {key: value for key, value in context.items()
                    if key not in {"directorPlan", "directorTaskCard", "taskId"}},
        "referenceRecord": references.record_patch,
        "referenceCard": references.card_patch,
        "nodeData": data, "targetModel": target_model,
    })
    return public, workflow, node, data, context, references


def get_video_prompt_context(project_id: str, episode_id: str, node_id: str, *,
                             user_instruction: str = "", expected_route_id: str = "",
                             expected_work_chain_id: str = "", part: str = "") -> dict[str, Any]:
    if part not in {"generation_bundle", "assigned_shots", "voice_context", "asset_names", "references",
                    "continuity", "target_model", "current_prompt", "submission_state"}:
        return _failure("part", "invalid_part", "请选择明确的视频提示词资料类型", "revise_and_resubmit")
    try:
        public, *_ = _read_context(project_id, episode_id, node_id, user_instruction,
                                   expected_route_id, expected_work_chain_id)
    except (ValueError, FileNotFoundError, OSError) as exc:
        return _failure("nodeId", "context_unavailable", str(exc), "stop")
    if part == "generation_bundle":
        used_ids = {
            str(event.get("speakerId") or "")
            for shot in public["directorPlanShots"] if isinstance(shot, dict)
            for event in shot.get("soundEvents") or [] if isinstance(event, dict)
            and event.get("kind") == "voice" and event.get("speakerId")
        }
        result = {
            "success": True, "inputDigest": public["inputDigest"],
            "directorPlanShots": public["directorPlanShots"],
            "sourceShotNos": public["assignedShotNos"],
            "submissionShotNos": list(range(1, len(public["directorPlanShots"]) + 1)),
            "clipDurationSeconds": public["clipDurationSeconds"],
            "timingBudget": public["timingBudget"],
            "assetNameMap": public["assetNameMap"],
            "referenceOptions": agent_video_reference_options(public["referenceManifest"]),
            "hasStoryboardReference": public["hasStoryboardReference"],
            "speakerRoster": [row for row in public["speakerRoster"]
                              if isinstance(row, dict) and row.get("speakerId") in used_ids],
            "assetVoiceDesign": {key: value for key, value in public["assetVoiceDesign"].items()
                                 if key in used_ids},
            "voiceAssetNameMap": {key: value for key, value in public["voiceAssetNameMap"].items()
                                  if f"asset:{key}" in used_ids},
            "continuityInstruction": public["continuityInstruction"],
            "boundaryPlan": copy.deepcopy(public["boundaryPlan"]),
            "targetModel": {key: public["targetModel"].get(key)
                            for key in ("modelId", "finalPromptProfile", "maxReferenceImages")},
        }
        if public["currentFinalVideoPrompt"]:
            result["currentFinalVideoPrompt"] = public["currentFinalVideoPrompt"]
        if public.get("currentSoundPrompt"):
            result["currentSoundPrompt"] = public["currentSoundPrompt"]
        return result
    if part == "assigned_shots":
        return {"success": True, "directorPlanShots": public["directorPlanShots"],
                "sourceShotNos": public["assignedShotNos"],
                "submissionShotNos": list(range(1, len(public["directorPlanShots"]) + 1)),
                "clipDurationSeconds": public["clipDurationSeconds"],
                "timingBudget": public["timingBudget"]}
    if part == "voice_context":
        used_ids = {
            str(event.get("speakerId") or "")
            for shot in public["directorPlanShots"] if isinstance(shot, dict)
            for event in shot.get("soundEvents") or [] if isinstance(event, dict)
            and event.get("kind") == "voice" and event.get("speakerId")
        }
        return {"success": True,
                "speakerRoster": [row for row in public["speakerRoster"]
                                  if isinstance(row, dict) and row.get("speakerId") in used_ids],
                "assetVoiceDesign": {key: value for key, value in public["assetVoiceDesign"].items()
                                     if key in used_ids},
                "voiceAssetNameMap": {key: value for key, value in public["voiceAssetNameMap"].items()
                                      if f"asset:{key}" in used_ids},
                "currentSoundPrompt": public.get("currentSoundPrompt", "")}
    if part == "asset_names":
        return {"success": True, "assetNameMap": public["assetNameMap"]}
    if part == "references":
        return {"success": True, **agent_video_reference_options(public["referenceManifest"]),
                "hasStoryboardReference": public["hasStoryboardReference"],
                "storyboardReferences": [
                    {"sourceNodeId": row.get("sourceNodeId"),
                     "mediaVersionId": row.get("mediaVersionId"),
                     "mediaId": row.get("mediaId")}
                    for row in public["referenceManifest"] if isinstance(row, dict)
                    and row.get("mentionKind") == "storyboard"
                ]}
    if part == "continuity":
        return {"success": True, "continuityInstruction": public["continuityInstruction"],
                "boundaryPlan": copy.deepcopy(public["boundaryPlan"])}
    if part == "target_model":
        return {"success": True, "targetModel": {
            key: public["targetModel"].get(key) for key in ("modelId", "finalPromptProfile", "maxReferenceImages")
        }}
    if part == "current_prompt":
        return {"success": True, "currentFinalVideoPrompt": public["currentFinalVideoPrompt"],
                "currentSoundPrompt": public.get("currentSoundPrompt", "")}
    return {"success": True, "inputDigest": public["inputDigest"]}


def video_prompt_submission_digest(shots: Any, used_speaker_ids: Any, voice_design: Any, sound_prompt: str = "") -> str:
    return _digest({"shots": shots, "usedSpeakerIds": used_speaker_ids, "voiceDesign": voice_design, "soundPrompt": sound_prompt})


def _generated_from_agent(project_id: str, source: dict[str, Any], candidate_shots: list[dict[str, Any]],
                          used_speaker_ids: list[str], voice_design: dict[str, Any],
                           clip_duration_seconds: Any, locked_durations: list[float] | None = None,
                           sound_prompt: str = "") -> dict[str, Any]:
    if not isinstance(sound_prompt, str):
        raise ValueError("声音提示词必须是文本")
    validate_agent_video_shot_mentions(candidate_shots, source.get("referenceManifest") or [])
    source_rows = _director_plan_shot_rows_from_structured(source["directorPlanShots"])
    rows = _video_task_card_timed_rows(source_rows, candidate_shots, clip_duration_seconds)
    if locked_durations is None:
        locked_durations = _locked_workchain_shot_durations(
            source["directorPlanShots"], clip_duration_seconds,
        )
    voice_timing_issues = _workchain_voice_timing_issues(source["directorPlanShots"], locked_durations)
    if voice_timing_issues:
        raise ValueError("视频卡时长不足以按正常语速完成原话：" + "；".join(voice_timing_issues))
    for index, (row, locked) in enumerate(zip(rows, locked_durations), start=1):
        if abs(float(row["durationSec"]) - locked) > 0.005:
            raise ValueError(
                f"镜头 {index} 的视频时长必须沿用分镜时间账 {locked:g} 秒；"
                "请按读取上下文返回的 lockedShotDurations 提交，不在视频提示词阶段重排镜长"
            )
    expected_speaker_ids = {
        event["speakerId"]
        for shot in source["directorPlanShots"]
        for event in shot.get("soundEvents") or []
        if event.get("kind") == "voice"
    }
    asset_voices = source["assetVoiceDesign"]
    known = {speaker_id: row["displayName"] for speaker_id, row in asset_voices.items()}
    fallback_assets = {
        f"asset:{asset_id}": name
        for asset_id, name in source["voiceAssetNameMap"].items()
        if f"asset:{asset_id}" not in known
    }
    used, design = normalize_video_prompt_voices(
        {"usedSpeakerIds": used_speaker_ids, "voiceDesign": voice_design}, known,
        expected_speaker_ids=expected_speaker_ids,
        fallback_asset_speakers=fallback_assets,
    )
    roster_names = {row["speakerId"]: row["displayName"] for row in source["speakerRoster"]}
    for row in design["speakers"]:
        if row["speakerId"] in roster_names:
            row["displayName"] = roster_names[row["speakerId"]]
    speaker_names = {**fallback_assets, **known, **{row["speakerId"]: row["displayName"] for row in design["speakers"]}}
    used, design = deduplicate_video_prompt_voices(used_speaker_ids, design, speaker_names,
        preferred_ids=set(known))
    row_labels = [{**row, "shotLabel": f"Shot {index:02d}"} for index, row in enumerate(rows, start=1)]
    voices = _video_task_card_asset_voice_style_map(
        project_id,
        asset_names=source["voiceAssetNameMap"],
        input_snapshot=source["voiceInputSnapshot"],
        speaker_ids=used,
    )
    final_prompt = _video_task_card_prompt_from_structured_shots(row_labels)
    speaker_prompt = _video_task_card_format_voice_design_for_prompt(
        design, voices, fallback_asset_ids=set(fallback_assets),
    )
    if not final_prompt.strip():
        raise ValueError("视频提示词为空")
    return {
        "shots": row_labels, "usedSpeakerIds": sorted(used), "voiceDesign": design,
        "prompt": final_prompt,
        "soundPrompt": deduplicate_video_voice_prompt("\n\n".join(part for part in (speaker_prompt, sound_prompt) if part),
            [speaker_names[key] for key in used]),
        "modelMeta": {
            "source": "agent_verified_video_prompt",
            "intermediateContract": VIDEO_TASK_CARD_INTERMEDIATE_CONTRACT,
        },
    }


def submit_video_prompt_result(
    project_id: str, episode_id: str, node_id: str,
    shots: Any, used_speaker_ids: Any, voice_design: Any, input_digest: str,
    *, user_instruction: str, session_id: str, execution_id: str,
    expected_route_id: str = "", expected_work_chain_id: str = "",
    sound_prompt: str = "",
) -> dict[str, Any]:
    if not str(input_digest or "").strip():
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
    save_result: dict[str, Any] = {}
    try:
        with _JSON_WRITE_LOCK:
            source, workflow, node, data, context, references = _read_context(
                project_id, episode_id, node_id, user_instruction,
                expected_route_id, expected_work_chain_id,
            )
            if source["inputDigest"] != input_digest:
                return _failure("inputDigest", "stale_context",
                                "分镜、素材、声音、模型配置或当前提示词已变化，请重新读取后提交", "reread_context")
            generated = _generated_from_agent(
                project_id, context, shots, used_speaker_ids, voice_design,
                source["clipDurationSeconds"], source["timingBudget"]["lockedShotDurations"],
                sound_prompt=sound_prompt,
            )
            patch = _compose_video_task_card_patch(
                project_id, episode_id, node, data, context, references,
                generated=generated,
            )
            expected_prompt = patch["finalVideoPrompt"]
            expected_sound_prompt = patch.get("soundPrompt", "")
            expected_rows = patch["shotPromptPlan"]["shots"]
            attempted = True
            save_result = _finish_video_task_card(
                project_id, episode_id, workflow, node,
                {"nodeId": node_id, "writeBack": True}, context, references, patch,
            )
    except Exception as exc:
        if attempted:
            try:
                stored = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
                card = (stored.get("data") or {}).get("videoTaskCard") or {}
                if card.get("soundPrompt", "") == expected_sound_prompt and card.get("finalVideoPrompt") == expected_prompt and (
                    (card.get("shotPromptPlan") or {}).get("shots") == expected_rows
                ):
                    failed = _failure("nodeId", "commit_unverified",
                                      f"写入后的附加步骤失败，当前节点可能已更新：{exc}；请回读画布", "stop")
                    failed.update({"status": "commit_unverified", "projectChanged": True,
                                   "changedResources": ["canvas_node"],
                                   "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id}})
                    return failed
            except Exception:
                failed = _failure("nodeId", "commit_unverified",
                                  f"视频提示词提交后无法回读核验：{exc}", "stop")
                failed.update({"status": "commit_unverified", "projectChanged": True,
                               "changedResources": ["canvas_node"]})
                return failed
        if isinstance(exc, RuntimeError) and "超过模型上限" in str(exc):
            return _failure("shots", "prompt_too_long", str(exc), "revise_and_resubmit")
        if isinstance(exc, ValueError):
            return _failure("shots", "invalid_or_stale_result", str(exc),
                            "reread_context" if attempted else "revise_and_resubmit")
        if isinstance(exc, (FileNotFoundError, OSError)):
            return _failure("nodeId", "context_unavailable", str(exc), "stop")
        return _failure("nodeId", "program_error", str(exc), "stop")

    try:
        stored = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
        card = (stored.get("data") or {}).get("videoTaskCard") or {}
        if (card.get("soundPrompt", "") != expected_sound_prompt
                or card.get("finalVideoPrompt") != expected_prompt
                or (card.get("shotPromptPlan") or {}).get("shots") != expected_rows
                or (stored.get("data") or {}).get("prompt", {}).get("videoPrompt") != expected_prompt):
            raise RuntimeError("视频提示词写入后回读不一致")
    except Exception as exc:
        failed = _failure("nodeId", "commit_unverified", str(exc), "stop")
        failed.update({"status": "commit_unverified", "projectChanged": True,
                       "changedResources": ["canvas_node"],
                       "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id}})
        return failed

    output_digest = _digest({"finalVideoPrompt": expected_prompt, "soundPrompt": expected_sound_prompt, "shots": expected_rows,
                             "usedSpeakerIds": card.get("usedSpeakerIds"), "voiceDesign": card.get("voiceDesign")})
    receipt_id = _digest({"executionId": execution_id, "nodeId": node_id,
                          "inputDigest": input_digest, "outputDigest": output_digest})
    receipt = {
        "receiptId": receipt_id, "runId": execution_id,
        "projectId": project_id, "episodeId": episode_id,
        "sessionId": session_id, "executionId": execution_id,
        "taskType": "video_prompt_generation", "targetIds": [node_id],
        "inputDigest": input_digest, "outputDigest": output_digest,
        "submissionDigest": video_prompt_submission_digest(shots, used_speaker_ids, voice_design, sound_prompt),
        "shotCount": len(expected_rows), "promptChars": len(expected_prompt),
        "changedResources": save_result.get("changedResources") or ["canvas_node"],
    }
    return {
        "success": True, "status": "committed", "episodeId": episode_id, "nodeId": node_id,
        "shotCount": len(expected_rows), "promptChars": len(expected_prompt),
        "receiptId": receipt_id, "commitReceipt": receipt,
        "changedResources": receipt["changedResources"], "projectChanged": True,
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id},
        **{key: copy.deepcopy(save_result.get(key)) for key in (
            "txId", "seq", "revision", "opType", "records", "workflowVersion",
        ) if save_result.get(key) is not None},
    }
