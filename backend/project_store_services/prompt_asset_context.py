"""Resolve prompt identities from current canvas bindings, without guessing by name."""

from typing import Any
from utils.video_prompt_mentions import prompt_mention_label
from .reference_read_context import ReferenceReadContext


PROMPT_ASSET_SLOTS = {
    "character_reference": "characters",
    "creature_reference": "creatures",
    "scene_reference": "scenes",
    "prop_reference": "props",
    "visual_handoff_reference": "visual_handoff",
    "storyboard_image": "storyboard",
}


import copy


def prompt_asset_identity(row: dict[str, Any]) -> str:
    """Library assets retain their ID; imported materials retain their canvas node ID."""
    return str(row.get("rootAssetId") or row.get("assetId") or row.get("sourceNodeId") or "").strip()


def resolve_prompt_assets(
    project_id: str, input_snapshot: dict[str, Any], *, read_context: ReferenceReadContext | None = None,
) -> dict[str, dict[str, Any]]:
    links = [
        row for row in input_snapshot.get("inputLinks") or []
        if isinstance(row, dict) and (row.get("targetSlot") or row.get("slot")) in PROMPT_ASSET_SLOTS
    ]
    needs_library = any(
        row.get("rootAssetId") or row.get("assetId") for row in links
    )
    context = read_context or ReferenceReadContext(project_id)
    index = context.asset_index if needs_library else {}
    result: dict[str, dict[str, Any]] = {}
    for link in links:
        identity = prompt_asset_identity(link)
        if not identity:
            continue
        kind = PROMPT_ASSET_SLOTS[link.get("targetSlot") or link.get("slot")]
        asset_id = str(link.get("rootAssetId") or link.get("assetId") or "").strip()
        if asset_id:
            source_project = str(link.get("rootAssetProjectId") or project_id).strip()
            asset = index.get((kind, asset_id), {}) if source_project == project_id else {}
            name = str(asset.get("name") or link.get("assetName") or link.get("label") or identity).strip()
            voice_style = str(asset.get("voiceStyle") or "").strip()
            reference_audio = asset.get("voiceReferenceAudio")
            exists = bool(asset)
        else:
            name = str(link.get("assetName") or link.get("label") or identity).strip()
            voice_style = str(link.get("voiceStyle") or "").strip()
            reference_audio = link.get("voiceReferenceAudio")
            exists = True
        result[identity] = {
            "id": identity,
            "assetType": kind,
            "displayName": name,
            "voiceStyle": voice_style if kind in {"characters", "creatures"} else "",
            "referenceAudio": copy.deepcopy(reference_audio) if kind in {"characters", "creatures"} else None,
            "exists": exists,
        }
    return result


def video_task_voice_input_snapshot(project_id: str, inputs: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """Explicit task speakers may use library voices without adding visual inputs."""
    links = list(inputs.get("inputLinks") or [])
    linked = {prompt_asset_identity(row) for row in links if isinstance(row, dict)}
    selected = [key.removeprefix("asset:") for key, row in (card.get("voiceOverrides") or {}).items()
                if key.startswith("asset:") and isinstance(row, dict) and row.get("displayName")
                and key.removeprefix("asset:") not in linked]
    if not selected:
        return inputs
    index = ReferenceReadContext(project_id).asset_index
    for identity in selected:
        for kind, slot in (("characters", "character_reference"), ("creatures", "creature_reference")):
            if (kind, identity) in index:
                links.append({"assetId": identity, "slot": slot})
                break
    return {**inputs, "inputLinks": links}


def _video_task_card_asset_name_map_from_inputs(
    input_snapshot: dict[str, Any],
    project_id: str,
    *,
    asset_name_map: dict[str, str] | None = None,
    read_context: ReferenceReadContext | None = None,
) -> dict[str, str]:
    """Use current resolved asset links, including assets without reference images."""
    mapping = {
        identity: row["displayName"]
        for identity, row in resolve_prompt_assets(project_id, input_snapshot, read_context=read_context).items()
        if row.get("assetType") != "storyboard"
    }
    if asset_name_map is not None:
        # Existing prose retains the names used when it was generated. Keep those
        # labels for still-bound assets; new references use their current names.
        saved_names = {
            identity: name.strip() for identity, name in asset_name_map.items()
            if identity in mapping and isinstance(name, str) and name.strip()
        }
        return {**mapping, **saved_names}
    return mapping


def _video_task_card_named_input_snapshot(
    project_id: str,
    input_snapshot: dict[str, Any],
    *,
    asset_name_map: dict[str, str] | None = None,
    read_context: ReferenceReadContext | None = None,
) -> dict[str, Any]:
    """Keep model input names and final image-reference labels on the same bound identities."""
    mapping = _video_task_card_asset_name_map_from_inputs(
        input_snapshot, project_id, asset_name_map=asset_name_map, read_context=read_context,
    )
    result = copy.deepcopy(input_snapshot)

    def update(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                update(item)
        elif isinstance(value, dict):
            asset_id = prompt_asset_identity(value)
            if asset_id in mapping:
                value["label"] = mapping[asset_id]
                value["assetName"] = mapping[asset_id]
            for item in value.values():
                if isinstance(item, (dict, list)):
                    update(item)

    update(result)
    return result


def _video_task_card_asset_voice_style_map(
    project_id: str,
    shots: list[dict[str, Any]] | None = None,
    asset_names: dict[str, str] | None = None,
    *,
    input_snapshot: dict[str, Any],
    speaker_ids: set[str] | None = None,
) -> dict[str, dict[str, str]]:
    """Resolve existing voices by identity, including the project's narrator."""
    referenced = set(asset_names or {})
    if shots is not None:
        speaker_ids = {
            str(event.get("speakerId") or "")
            for shot in shots if isinstance(shot, dict)
            for event in shot.get("soundEvents") or []
            if isinstance(event, dict) and event.get("kind") == "voice"
        }
    if speaker_ids is not None:
        speakers = {key.removeprefix("asset:") for key in speaker_ids if key.startswith("asset:")}
        missing = speakers - referenced
        if missing:
            raise ValueError("分镜脚本引用的发声资产未关联到当前工作链：" + "、".join(sorted(missing)))
        referenced = speakers
    result: dict[str, dict[str, str]] = {}
    if speaker_ids is not None and "project:narrator" in speaker_ids:
        from .project_overview import get_project_narrator_voice_profile

        profile = get_project_narrator_voice_profile(project_id)
        # Reference audio remains local in phase 1, just as it does for assets.
        if profile["voiceStyle"]:
            result["project:narrator"] = {
                "displayName": profile["displayName"],
                "voiceStyle": profile["voiceStyle"],
            }
    if not referenced:
        return result
    resolved_asset_ids: set[str] = set()
    for asset_id, row in resolve_prompt_assets(project_id, input_snapshot).items():
        if asset_id not in referenced or not row["exists"]:
            continue
        resolved_asset_ids.add(asset_id)
        if not row["voiceStyle"]:
            continue
        result[f"asset:{asset_id}"] = {
            "displayName": (asset_names or {}).get(asset_id) or row["displayName"],
            "voiceStyle": row["voiceStyle"],
        }
    if speaker_ids is not None:
        missing = referenced - resolved_asset_ids
        if missing:
            raise ValueError("分镜脚本引用的发声资产不存在或未关联：" + "、".join(sorted(missing)))
    return result


def _video_task_card_voice_context(context: dict[str, Any]) -> dict[str, Any]:
    """Resolve readable identities on a request copy, without rewriting stored plans or dialogue."""
    from .director_plan_contract import _director_plan_normalized_speaker_roster

    result = copy.deepcopy(context)
    shots = result.get("directorPlanShots") or []
    assets = result.get("assetVoiceDesign") or {}
    names = result.get("assetNameMap") or {}
    # Image selection and speaker association have different lifetimes. Preserve
    # the complete association set for every normalization of this request.
    voice_names = result.get("voiceAssetNameMap")
    if not isinstance(voice_names, dict):
        voice_names = names
    roster = _director_plan_normalized_speaker_roster(
        result.get("speakerRoster"), shots=shots, speaker_asset_ids=set(voice_names),
    )
    labels = {f"asset:{key}": name for key, name in names.items()}
    labels.update({f"asset:{key}": name for key, name in voice_names.items()})
    labels.update({key: row["displayName"] for key, row in assets.items()})
    labels["project:narrator"] = "旁白"
    labels.update({row["speakerId"]: row["displayName"] for row in roster})
    for shot in shots:
        for event in shot.get("soundEvents") or []:
            if event.get("kind") != "voice":
                continue
            speaker_id = event["speakerId"]
            if speaker_id.startswith("asset:") and speaker_id.removeprefix("asset:") not in voice_names:
                raise ValueError(f"分镜脚本引用的发声资产未关联：{speaker_id}")
            label = labels[speaker_id]
            if event.get("sourceName") != label:
                event["sourceNameOriginal"] = event.get("sourceName") or ""
            event["sourceName"] = label
    for speaker in roster:
        speaker["displayName"] = labels[speaker["speakerId"]]
    for speaker_id, row in assets.items():
        row["displayName"] = labels[speaker_id]
    result["speakerRoster"] = roster
    result["assetVoiceDesign"] = assets
    result["assetNameMap"] = {key: labels[f"asset:{key}"] for key in names}
    result["voiceAssetNameMap"] = {key: labels[f"asset:{key}"] for key in voice_names}
    return result


def _video_task_card_format_asset_name_map_for_prompt(mapping: dict[str, str]) -> str:
    if not mapping:
        return "无"
    return "\n".join(f"- @[{prompt_mention_label(name)}]" for name in mapping.values())
