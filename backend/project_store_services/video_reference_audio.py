"""Resolve task speakers once for the card preview and the actual video request."""

from __future__ import annotations

import base64
import copy
import hashlib
import wave
from typing import Any

from utils.reference_audio import reference_audio_limits, validate_reference_audios
from .prompt_asset_context import resolve_prompt_assets, video_task_voice_input_snapshot
from .video_prompt_generation import deduplicate_video_voice_prompt, unique_video_speaker_ids


def _video_task_speaker_names(card: dict[str, Any], assets: dict[str, Any]) -> dict[str, str]:
    designs = {row["speakerId"]: row for row in (card.get("voiceDesign") or {}).get("speakers", [])
               if isinstance(row, dict) and row.get("speakerId")}
    overrides = card.get("voiceOverrides") or {}
    names = card.get("assetNameMap") or {}
    result = {}
    for key in card.get("usedSpeakerIds", list(designs)):
        identity = key.removeprefix("asset:")
        source_name = "旁白" if key == "project:narrator" else (assets.get(identity) or {}).get("displayName")
        result[key] = str((overrides.get(key) or {}).get("displayName") or names.get(identity)
                          or source_name or (designs.get(key) or {}).get("displayName") or key).strip()
    return result


def validate_video_task_voice_names(project_id: str, data: dict[str, Any]) -> None:
    card = data.get("videoTaskCard") or {}
    names = _video_task_speaker_names(card, {})
    if any(key.startswith("asset:") and name == key for key, name in names.items()):
        inputs = video_task_voice_input_snapshot(project_id, {"inputLinks": data.get("inputLinks") or []}, card)
        names = _video_task_speaker_names(card, resolve_prompt_assets(project_id, inputs))
    if len(set(names.values())) != len(names):
        raise ValueError("同名角色不能重复添加声音")


def normalize_video_task_voice_overrides(project_id: str, overrides: Any) -> dict[str, Any]:
    if not isinstance(overrides, dict):
        raise ValueError("任务声音来源设置无效")
    normalized = copy.deepcopy(overrides)
    for speaker_id, row in normalized.items():
        if not isinstance(speaker_id, str) or not speaker_id.strip():
            raise ValueError("任务声音身份无效")
        if row is None:
            continue
        if (not isinstance(row, dict) or set(row) - {"mode", "displayName", "referenceAudio", "voiceStyle"}
                or row.get("mode") not in {"auto", "text", "reference_audio"}):
            raise ValueError("任务声音来源设置无效")
        if "displayName" in row and (not isinstance(row["displayName"], str) or not row["displayName"].strip()):
            raise ValueError("请指定声音对应的角色")
        if "voiceStyle" in row and not isinstance(row["voiceStyle"], str):
            raise ValueError("声音设计提示词必须是文本")
        if row.get("referenceAudio") is not None:
            if not isinstance(row["referenceAudio"], dict):
                raise ValueError("参考音频格式无效")
            from .media_files import _normalize_voice_reference_audio
            row["referenceAudio"] = _normalize_voice_reference_audio(project_id, row["referenceAudio"], subdir="video-task-voices")
    return normalized


def import_video_task_reference_audio(project_id: str, media: dict[str, Any]) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    from .media_files import _normalize_voice_reference_audio
    if not _project_dir(project_id).is_dir():
        raise FileNotFoundError("项目不存在")
    audio = _normalize_voice_reference_audio(project_id, media, subdir="video-task-voices", force_copy=True)
    if not audio:
        raise ValueError("请选择有效的参考音频")
    return {"success": True, "referenceAudio": audio}


def _subject_binding(speaker_id: str, manifest: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not speaker_id.startswith("asset:"):
        return None
    asset_id = speaker_id.removeprefix("asset:")
    candidates = [row for row in manifest if row.get("kind") in {"image", "video"}
                  and row.get("transportRole") in {"reference_image", "reference_video"}
                  and (row.get("assetId") or row.get("sourceNodeId")) == asset_id
                  and row.get("slot") not in {"storyboard_image", "visual_handoff_reference"}]
    return {"kind": candidates[0]["kind"], "index": candidates[0]["index"]} if candidates else None


def resolve_video_task_voices(project_id: str, payload: dict[str, Any], model: Any, *,
                              prompt: str, manifest: list[dict[str, Any]],
                              native: bool = False, enabled: bool = True,
                              prepare_transport: bool = False,
                              validate_files: bool = False) -> dict[str, Any]:
    card = payload.get("videoTaskCard") or {}
    sound_prompt = str(card.get("soundPrompt") or "")
    designs = {row["speakerId"]: row for row in (card.get("voiceDesign") or {}).get("speakers", [])
               if isinstance(row, dict) and row.get("speakerId")}
    used = card.get("usedSpeakerIds")
    speaker_ids = list(dict.fromkeys(used if isinstance(used, list) else designs.keys()))
    if not speaker_ids:
        return {"speakers": [], "referenceAudios": [], "prompt": prompt, "soundPrompt": sound_prompt}
    inputs = video_task_voice_input_snapshot(project_id, {
        "inputLinks": payload.get("inputLinksSnapshot") or payload.get("inputLinks") or [],
    }, card)
    assets = resolve_prompt_assets(project_id, inputs)
    limits = reference_audio_limits(model)
    overrides = card.get("voiceOverrides") or {}
    names = _video_task_speaker_names(card, assets)
    speaker_ids = unique_video_speaker_ids(speaker_ids, names,
        preferred_ids={key for key, row in overrides.items() if isinstance(row, dict)})
    lines = sound_prompt.splitlines()
    speakers, references = [], []
    prompt_changed = False
    for speaker_id in speaker_ids:
        design = designs.get(speaker_id) or {}
        override = overrides.get(speaker_id) or {}
        if speaker_id == "project:narrator":
            from .project_overview import get_project_narrator_voice_profile
            source = get_project_narrator_voice_profile(project_id)
            audio = source.get("referenceAudio")
            origin = "项目旁白"
        elif speaker_id.startswith("asset:"):
            asset_id = speaker_id.removeprefix("asset:")
            source = assets.get(asset_id) or {}
            audio = source.get("referenceAudio")
            origin = "角色资产"
        else:
            source, audio, origin = {}, None, "本任务"
        if "referenceAudio" in override:
            audio = override["referenceAudio"]
            origin = "本任务"
        name = names[speaker_id]
        prefix = f"- {name}："
        old_line = next((line.strip() for line in lines if line.strip().startswith(prefix)), "")
        style = (str(override["voiceStyle"]).strip() if "voiceStyle" in override else
                 old_line[len(prefix):].strip() if old_line else str(source.get("voiceStyle") or design.get("voiceStyle") or "").strip())
        mode = override.get("mode", "auto")
        if mode == "reference_audio" and not audio and enabled and (validate_files or prepare_transport):
            raise ValueError(f"请为{name}上传参考音频")
        if mode == "text" and not style and enabled and (validate_files or prepare_transport):
            raise ValueError(f"请填写{name}的声音设计提示词")
        reason = ""
        binding = _subject_binding(speaker_id, manifest)
        if audio:
            if mode == "text":
                reason = "本任务使用文字音色"
            elif not enabled:
                reason = "当前任务不使用原生声音"
            elif not limits:
                reason = "当前模型尚未接入参考音频"
            elif native and not limits["supports_native_frames"]:
                reason = "当前模型的原生首尾帧模式不支持参考音频"
            elif limits["binding"] == "visual_subject" and not binding:
                reason = "该模型需要关联此角色的参考图或参考视频"
        use_audio = bool(audio and not reason)
        if audio and not use_audio and enabled and not style and (validate_files or prepare_transport):
            raise ValueError(f"{name}的参考音频在当前模式不可用，且没有备用文字音色，请补充音色描述")
        row = {"speakerId": speaker_id, "displayName": name, "voiceStyle": style,
               "referenceAudio": copy.deepcopy(audio), "origin": origin, "mode": mode,
               "effectiveSource": "reference_audio" if use_audio else "voice_style",
               "reason": reason, "binding": binding}
        speakers.append(row)
        if use_audio:
            reference = {"speakerId": speaker_id, "displayName": name, "binding": binding,
                         "media": copy.deepcopy(audio)}
            if validate_files or prepare_transport:
                from .media_files import _audio_source_from_media, _audio_duration_seconds
                resolved = _audio_source_from_media(project_id, audio)
                if not resolved:
                    raise ValueError(f"{name}的参考音频文件不可用，请在声音设置中重新上传")
                path = resolved[0]
                try:
                    with wave.open(str(path), "rb") as reader:
                        duration = reader.getnframes() / reader.getframerate()
                except (wave.Error, EOFError):
                    duration = _audio_duration_seconds(path)
                reference.update({"duration": duration, "size": path.stat().st_size, "format": path.suffix.lower().lstrip(".")})
                reference["_path"] = path
            else:
                reference.update({"duration": audio.get("duration"), "size": audio.get("size"),
                                  "format": str(audio.get("format") or "wav")})
            references.append(reference)
        # Only canonical per-speaker lines are replaced; keep all other manual sound instructions.
        if use_audio:
            index = len(references)
            if limits["binding"] == "visual_subject":
                label = f"{'图' if binding['kind'] == 'image' else '视频'}{binding['index']}的参考音色"
            else:
                label = limits["prompt_label"].format(index=index)
            line = prefix + f"音色参考{label}；只参考音色，台词和表演按镜头内容。"
        else:
            line = prefix + style if style else ""
        if old_line and (use_audio or "voiceStyle" in override):
            lines = [line if item.strip() == old_line else item for item in lines]
            prompt_changed = True
        elif line and not old_line:
            lines.append(line)
            prompt_changed = True
    if validate_files or prepare_transport:
        validate_reference_audios(references, model, native=native,
            image_count=sum(row.get("kind") == "image" and row.get("transportRole") == "reference_image" for row in manifest),
            video_count=sum(row.get("kind") == "video" for row in manifest), require_urls=False)
    # Validate every file before any public upload, and preserve exact submitted bytes in request logs.
    for reference in references:
        path = reference.pop("_path", None)
        if not prepare_transport:
            continue
        reference["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        reference["transport"] = limits["transport"]
        if limits["transport"] == "public_url":
            from utils.temporary_media_storage import ensure_public_url
            from utils.request_media_archive import archive_uploaded_media
            from .catalogs import PROJECTS_DIR
            remote = ensure_public_url(path, "audio")
            reference["audioUrl"] = remote["url"]
            reference["storage"] = remote
            reference["requestLogMedia"] = archive_uploaded_media(path, remote,
                PROJECTS_DIR / project_id / "debug" / "model-request-logs" / "final-video-generation-request" / "_transport",
                media_kind="audio")
        else:
            mime = "audio/wav" if reference["format"] == "wav" else "audio/mpeg"
            reference["audioUrl"] = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    sound = deduplicate_video_voice_prompt("\n".join(line for line in lines if line.strip()) if prompt_changed else sound_prompt,
                                           [names[key] for key in speaker_ids])
    return {"speakers": speakers, "referenceAudios": references, "prompt": prompt,
            "soundPrompt": sound}


def preview_video_task_voices(project_id: str, data: dict[str, Any], prompt: str) -> dict[str, Any]:
    from .generation_config import _video_task_card_target_model_context
    model = _video_task_card_target_model_context(project_id, data, {}, include_timing=False)
    model["provider_preset_id"] = model.get("providerId")
    plan = (data.get("videoTaskCard") or {}).get("boundaryPlan") or {}
    config = data.get("generationConfig") or {}
    options = {"prompt": prompt, "manifest": data.get("referenceManifest") or data.get("referenceDisplayRows") or [],
        "native": plan.get("mode") == "native_keyframe" or config.get("strategy") == "native_keyframe_video"
                  or data.get("eyebrow") == "video.keyframe"}
    validation_error = ""
    try:
        result = resolve_video_task_voices(project_id, data, model, validate_files=True, **options)
    except ValueError as exc:
        validation_error = str(exc)
        result = resolve_video_task_voices(project_id, data, model, **options)
    from .reference_read_context import ReferenceReadContext
    from .project_overview import get_project_narrator_voice_profile
    context = ReferenceReadContext(project_id)
    project_choices = {}
    for kind, rows in context.assets.items():
        if kind not in {"characters", "creatures"} or not isinstance(rows, list):
            continue
        for asset in rows:
            if not isinstance(asset, dict) or not asset.get("id"):
                continue
            identity = f"asset:{asset['id']}"
            project_choices[identity] = {"speakerId": identity, "displayName": asset.get("name") or asset["id"],
                                         "voiceStyle": asset.get("voiceStyle") or "", "referenceAudio": asset.get("voiceReferenceAudio")}
    # The card's resolved inputs already contain its inherited work-chain links.
    # Keep the project library separate from these task-local candidates.
    choices = {}
    links = [row for row in data.get("inputLinks") or [] if isinstance(row, dict) and row.get("enabled") is not False]
    linked = resolve_prompt_assets(project_id, {"inputLinks": links}, read_context=context)
    for identity, row in linked.items():
        if row.get("assetType") in {"characters", "creatures"}:
            choices[f"asset:{identity}"] = {"speakerId": f"asset:{identity}", **row}
    for row in ((data.get("videoTaskCard") or {}).get("voiceDesign") or {}).get("speakers", []):
        if not isinstance(row, dict):
            continue
        identity = row.get("speakerId")
        if isinstance(identity, str) and identity and not identity.startswith(("asset:", "project:")) and row.get("displayName"):
            choices[identity] = {"speakerId": identity, "displayName": row["displayName"], "voiceStyle": row.get("voiceStyle") or ""}
    narrator = get_project_narrator_voice_profile(project_id)
    choices["project:narrator"] = {"speakerId": "project:narrator", "displayName": "旁白",
                                   "voiceStyle": narrator.get("voiceStyle") or "", "referenceAudio": narrator.get("referenceAudio")}
    return {"success": True, "speakers": result["speakers"], "availableSpeakers": list(choices.values()),
            "projectSpeakers": list(project_choices.values()), "validationError": validation_error}
