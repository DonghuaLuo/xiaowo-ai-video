# -*- coding: utf-8 -*-
"""视频参考素材分配、角色与顺序、供应商参考图整理。"""
from __future__ import annotations

from .model_generation_contract import _model_supports_storyboard_reference_image
from .model_generation_contract import _reference_has_storyboard_asset_type
from .model_generation_contract import _reference_is_storyboard_sheet
from .model_generation_contract import _reference_is_visual_handoff
from .perf_logging import canvas_perf_elapsed_ms
from .perf_logging import canvas_perf_log
from .perf_logging import canvas_perf_start
from .provider_reference_media import _VIDEO_REFERENCE_FILE_SUFFIXES
from .provider_reference_media import _asset_refs_resolved_by_input_links_for_provider
from .provider_reference_media import _extract_storyboard_reference_image
from .provider_reference_media import _provider_media_reference_suffix
from .provider_reference_media import _provider_reference_images_from_ids
from .provider_reference_media import _provider_reference_images_from_inline_files
from .provider_reference_media import _provider_reference_metadata
from .provider_reference_media import _provider_reference_videos_from_ids
from .reference_utils import asset_reference_ids_from_generation_sources as _asset_reference_ids_from_generation_sources
from .reference_utils import merge_reference_ids as _merge_reference_ids
from .safe_visual_language import uses_safety_policy_language
from .video_reference_metadata import normalize_reference_text
from .video_reference_metadata import strip_inline_asset_mention_markers as _strip_inline_asset_mention_markers
from .video_reference_metadata import video_reference_input_identity
from pathlib import Path
from typing import Any
from utils.frame_references import FRAME_IMAGE
from utils.frame_references import FRAME_SLOT
from utils.frame_references import frame_options
from utils.frame_references import frame_reference_brief
from utils.frame_references import is_frame_image
from utils.frame_references import select_frame_transport
from utils.video_model_capabilities import video_model_capability
from utils.video_references import reference_video_source_ids
from utils.video_references import reference_manifest_from_rows
from utils.video_prompt_mentions import merge_prompt_manifest
from utils.video_references import validate_reference_videos
import copy
import json
import re

def _video_reference_row_slot(row: dict[str, Any]) -> str:
    return str(row.get("targetSlot") or row.get("target_slot") or row.get("slot") or "").strip()


def _video_reference_row_label(row: dict[str, Any], fallback: str = "") -> str:
    for key in ("label", "displayName", "display_name", "assetName", "asset_name", "name", "title"):
        text = str(row.get(key) or "").strip()
        if text:
            return text
    return fallback


def _video_reference_inline_text(value: Any) -> str:
    return normalize_reference_text(_strip_inline_asset_mention_markers(value))


def _video_reference_row_media(row: dict[str, Any]) -> dict[str, Any]:
    media = row.get("media") if isinstance(row.get("media"), dict) else {}
    return media


def _video_reference_row_is_input_link(row: dict[str, Any]) -> bool:
    return any(
        str(row.get(key) or "").strip()
        for key in (
            "inputLinkId",
            "input_link_id",
            "targetNodeId",
            "target_node_id",
            "targetSlot",
            "target_slot",
            "targetHandle",
            "target_handle",
            "linkAction",
        )
    )


def _video_reference_row_is_direct_asset_reference(row: dict[str, Any]) -> bool:
    if _video_reference_row_is_input_link(row):
        return False
    return str(row.get("sourceType") or row.get("source_type") or "").strip().casefold() == "asset"


def _video_reference_row_identity_values(row: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)

    for key in (
        "id",
        "linkId",
        "link_id",
        "inputLinkId",
        "input_link_id",
        "rootAssetId",
        "mediaVersionId",
        "media_version_id",
        "sourceVersionId",
        "source_version_id",
        "versionId",
        "version_id",
        "mediaId",
        "media_id",
        "assetId",
    ):
        add(row.get(key))
    if _video_reference_row_is_input_link(row):
        for key in ("sourceNodeId", "source_node_id"):
            add(row.get(key))
    for nested_key in ("media", "storage"):
        nested = row.get(nested_key) if isinstance(row.get(nested_key), dict) else {}
        for key in (
            "id",
            "mediaId",
            "media_id",
            "mediaVersionId",
            "media_version_id",
            "sourceVersionId",
            "source_version_id",
            "versionId",
            "version_id",
        ):
            add(nested.get(key))
    return values


def _video_reference_row_dedupe_identity(row: dict[str, Any]) -> str:
    reference_id = video_reference_input_identity(row)
    if reference_id:
        return reference_id
    identity = "|".join(_video_reference_row_identity_values(row)).strip()
    if identity:
        return identity
    return "no-id:" + json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)


def _video_reference_row_reference_id(
    row: dict[str, Any],
    *,
    allow_asset_identity_reference_ids: bool = True,
) -> str:
    if _video_reference_row_is_input_link(row):
        for key in (
            "sourceNodeId",
            "source_node_id",
        ):
            text = str(row.get(key) or "").strip()
            if text:
                return text
    for key in (
        "mediaVersionId",
        "media_version_id",
        "sourceVersionId",
        "source_version_id",
        "versionId",
        "version_id",
        "mediaId",
        "media_id",
    ):
        text = str(row.get(key) or "").strip()
        if text:
            return text
    for nested_key in ("media", "storage"):
        nested = row.get(nested_key) if isinstance(row.get(nested_key), dict) else {}
        for key in (
            "id",
            "mediaId",
            "media_id",
            "mediaVersionId",
            "media_version_id",
            "sourceVersionId",
            "source_version_id",
            "versionId",
            "version_id",
        ):
            text = str(nested.get(key) or "").strip()
            if text:
                return text
    if allow_asset_identity_reference_ids and _video_reference_row_is_direct_asset_reference(row):
        for key in (
            "rootAssetId",
            "assetId",
        ):
            text = str(row.get(key) or "").strip()
            if text:
                return text
    return ""


def _video_reference_row_name(row: dict[str, Any]) -> str:
    media = _video_reference_row_media(row)
    for source in (row, media):
        for key in (
            "name",
            "originalName",
            "original_name",
            "fileName",
            "file_name",
            "filePath",
            "file_path",
            "path",
            "relativePath",
            "relative_path",
            "url",
        ):
            text = str(source.get(key) or "").strip()
            if text:
                return text
    return ""


def _video_reference_row_is_video(row: dict[str, Any]) -> bool:
    if _video_reference_row_slot(row) == "reference_video":
        return True
    media = _video_reference_row_media(row)
    for source in (row, media):
        for key in (
            "kind",
            "mediaKind",
            "media_kind",
            "mediaType",
            "media_type",
            "assetKind",
            "asset_kind",
            "assetType",
            "asset_type",
            "sourceType",
            "source_type",
            "nodeType",
            "node_type",
            "sourceNodeType",
            "source_node_type",
            "type",
        ):
            text = str(source.get(key) or "").strip().casefold()
            if text in {"video", "generated_video", "video.result", "storyboard_video"}:
                return True
    mime_type = str(
        row.get("mimeType")
        or row.get("mime_type")
        or media.get("mimeType")
        or media.get("mime_type")
        or ""
    ).strip().casefold()
    if mime_type.startswith("video/"):
        return True
    data_url = str(row.get("dataUrl") or media.get("dataUrl") or "").strip().casefold()
    if data_url.startswith("data:video/"):
        return True
    return _provider_media_reference_suffix(_video_reference_row_name(row)) in _VIDEO_REFERENCE_FILE_SUFFIXES


def _video_reference_ids_from_rows(
    *values: Any,
    include_videos: bool = False,
    only_videos: bool = False,
    allow_asset_identity_reference_ids: bool = True,
) -> list[str]:
    reference_ids: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in reference_ids:
            reference_ids.append(text)

    for value in values:
        if not isinstance(value, list):
            continue
        for row in value:
            if not isinstance(row, dict):
                continue
            is_video = _video_reference_row_is_video(row)
            if only_videos and not is_video:
                continue
            if is_video and not (include_videos or only_videos):
                continue
            add(
                _video_reference_row_reference_id(
                    row,
                    allow_asset_identity_reference_ids=allow_asset_identity_reference_ids,
                )
            )
    return reference_ids


def _video_reference_rows_from_payload(
    payload: dict[str, Any],
    *,
    include_videos: bool = False,
    only_videos: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for key in (
        "referenceThumbnails",
        "referenceThumbnailsSnapshot",
        "assetThumbnails",
        "assetThumbnailsSnapshot",
        "inputLinksSnapshot",
        "inputLinks",
        "referenceManifest",
        "referenceManifestSnapshot",
    ):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            is_video = _video_reference_row_is_video(item)
            if only_videos and not is_video:
                continue
            if is_video and not (include_videos or only_videos):
                continue
            slot = _video_reference_row_slot(item)
            identity = _video_reference_row_dedupe_identity(item)
            dedupe_key = ("image", identity)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            rows.append(copy.deepcopy(item))
    return rows


def _video_inline_reference_files_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in (
        "referenceFiles",
        "reference_files",
        "inlineReferenceFiles",
        "inline_reference_files",
        "editReferenceFiles",
        "edit_reference_files",
    ):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip().lower()
            mime_type = str(item.get("mimeType") or item.get("mime_type") or "").strip().lower()
            name = str(item.get("name") or item.get("originalName") or item.get("path") or item.get("filePath") or "").strip()
            if kind == "video" or mime_type.startswith("video/") or Path(name).suffix.lower() in _VIDEO_REFERENCE_FILE_SUFFIXES:
                continue
            identity = str(
                item.get("filePath")
                or item.get("file_path")
                or item.get("path")
                or item.get("relativePath")
                or item.get("relative_path")
                or item.get("name")
                or ""
            ).strip()
            if identity and identity in seen:
                continue
            if identity:
                seen.add(identity)
            files.append(item)
    return files


def _video_storyboard_interpretation_contract_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    direct = payload.get("storyboardInterpretationContract")
    return direct if isinstance(direct, dict) else {}


def _video_safe_reference_label(value: Any, fallback: str) -> str:
    label = str(value or "").strip()
    if not label or uses_safety_policy_language(label):
        return str(fallback or "已绑定资产").strip() or "已绑定资产"
    return label


def _video_storyboard_visual_id_for_reference(
    contract: dict[str, Any],
    row: dict[str, Any],
    reference: dict[str, Any],
) -> str:
    bindings = contract.get("assetBindings") if isinstance(contract.get("assetBindings"), list) else []
    identities = {
        str(value or "").strip()
        for value in (
            *_video_reference_row_identity_values(row),
            reference.get("rootAssetId"),
            reference.get("assetId"),
            reference.get("mediaId"),
            reference.get("media_id"),
            reference.get("versionId"),
            reference.get("version_id"),
            reference.get("requestedReferenceId"),
            reference.get("sourceNodeId"),
            reference.get("source_node_id"),
        )
        if str(value or "").strip()
    }
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        binding_identities = {
            str(binding.get(key) or "").strip()
            for key in (
                "rootAssetId",
                "assetId",
                "mediaId",
                "media_id",
                "versionId",
                "version_id",
                "mediaVersionId",
                "media_version_id",
                "sourceVersionId",
                "source_version_id",
                "sourceNodeId",
                "source_node_id",
            )
            if str(binding.get(key) or "").strip()
        }
        if identities.intersection(binding_identities):
            return str(binding.get("visualId") or "").strip().upper()
    return ""


def _video_official_reference_entries(
    payload: dict[str, Any],
    reference_images: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    references = [row for row in (reference_images or []) if isinstance(row, dict)]
    if not references:
        return []
    rows = _video_reference_rows_from_payload(payload)
    row_by_identity: dict[str, dict[str, Any]] = {}
    for row in rows:
        for identity in _video_reference_row_identity_values(row):
            row_by_identity.setdefault(identity, row)
    contract = _video_storyboard_interpretation_contract_from_payload(payload)
    entries: list[dict[str, Any]] = []
    reference_index = 0
    for index, reference in enumerate(references, start=1):
        native_role = str(reference.get("transportRole") or "")
        if native_role not in {"first_frame", "last_frame"}:
            reference_index += 1
        identities = [
            str(reference.get(key) or "").strip()
            for key in ("requestedReferenceId", "mediaId", "versionId", "assetId")
            if str(reference.get(key) or "").strip()
        ]
        row = next((row_by_identity[item] for item in identities if item in row_by_identity), {})
        slot = _video_reference_row_slot(row)
        asset_type = str(
            row.get("assetType")
            or row.get("asset_type")
            or reference.get("assetType")
            or reference.get("asset_type")
            or ""
        ).strip().casefold()
        is_frame = is_frame_image(row) or is_frame_image(reference)
        frame_role = frame_options(row if is_frame_image(row) else reference)["frameRole"] if is_frame else ""
        is_handoff = _reference_is_visual_handoff(row) or _reference_is_visual_handoff(reference)
        is_custom_image = slot == "custom_image" or asset_type == "custom_image" or any(
            reference.get(key) == "custom_image" for key in ("slot", "mediaPurpose")
        )
        is_storyboard = not is_custom_image and not is_frame and not is_handoff and (_reference_is_storyboard_sheet(reference) or _reference_has_storyboard_asset_type(row))
        if is_custom_image:
            kind = "自定义图片"
            role = ""
        elif is_frame:
            kind = "帧画面"
            role = frame_reference_brief(frame_role)
        elif is_handoff:
            kind = "视觉交接图"
            role = VISUAL_HANDOFF_REFERENCE_BRIEF
        elif is_storyboard:
            kind = "故事板分镜图"
            role = "用于镜头顺序、站位和空间调度，不作为成片版式"
        elif slot == "character_reference" or "character" in asset_type:
            kind = "角色参考"
            role = "锁定对应角色身份、脸型、服装和外观连续性"
        elif slot == "creature_reference" or "creature" in asset_type:
            kind = "生物参考"
            role = "锁定对应生物形态、身份和运动连续性"
        elif slot == "scene_reference" or "scene" in asset_type:
            kind = "场景参考"
            role = "锁定对应空间结构、环境和光影连续性"
        elif slot == "prop_reference" or "prop" in asset_type:
            kind = "道具参考"
            role = "锁定对应道具外观、尺度和连续性"
        else:
            kind = "补充参考"
            role = "只约束本次明确需要的外观或局部细节"
        raw_label = (
            _video_reference_row_label(row)
            or str(reference.get("displayName") or reference.get("label") or reference.get("name") or "").strip()
            or str(reference.get("assetId") or reference.get("requestedReferenceId") or f"参考图{index}").strip()
        )
        visual_id = _video_storyboard_visual_id_for_reference(contract, row, reference)
        label = re.sub(r"\s+", " ", _video_safe_reference_label(raw_label, visual_id or kind)).strip()
        brief = ""
        if is_frame:
            brief = frame_reference_brief(frame_role)
        elif is_handoff:
            brief = VISUAL_HANDOFF_REFERENCE_BRIEF
        entries.append(
            {
                "index": reference_index if native_role not in {"first_frame", "last_frame"} else 0,
                "nativeRole": native_role,
                "isFrame": is_frame,
                "frameRole": frame_role,
                "label": "帧画面" if is_frame else label,
                "brief": brief,
                "kind": kind,
                "role": role,
                "visualId": visual_id,
                "isStoryboard": is_storyboard,
                "storyboardPromptSpec": copy.deepcopy(reference.get("storyboardPromptSpec") or {}) if is_storyboard else {},
                "isCustomImage": is_custom_image,
                "isVisualHandoff": is_handoff,
            }
        )
    return entries


def _video_provider_reference_plan(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
    workflow: dict[str, Any],
    resolved_config: dict[str, Any],
    strategy: str,
    model: dict[str, Any],
    *,
    prepare_transport_media: bool = True,
    output_duration: float | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any]]:
    perf_started_at = canvas_perf_start()
    if strategy == "character_replace_video":
        from utils.video_task_types import CHARACTER_REPLACE_INPUT_SLOTS
        from .workflow_contract import _canonical_workflow_slot
        links = payload.get("inputLinksSnapshot") or payload.get("inputLinks") or []
        if any(_canonical_workflow_slot(row.get("slot") or row.get("targetSlot")) not in CHARACTER_REPLACE_INPUT_SLOTS
               for row in links if isinstance(row, dict)):
            raise ValueError("角色替换仅支持源视频与角色图，请移除其他用途的素材")
    native_keyframe = strategy == "native_keyframe_video"
    work_chain_native = native_keyframe and payload.get("videoTaskScope") == "work_chain"
    connected_reference_video_ids = [] if work_chain_native else reference_video_source_ids(payload)
    reference_videos = _provider_reference_videos_from_ids(
        project_id,
        episode_id,
        workflow,
        connected_reference_video_ids,
        model=model,
        prepare_transport_media=prepare_transport_media,
        output_duration=output_duration,
        require_all=strategy == "character_replace_video",
    )
    asset_refs_resolved_by_input_links = _asset_refs_resolved_by_input_links_for_provider(
        payload,
        resolved_config,
    )
    explicit_reference_sources: list[Any] = [
        payload.get("referenceMediaIds"),
        payload.get("reference_media_ids"),
        _video_reference_ids_from_rows(
            payload.get("referenceThumbnails"),
            payload.get("referenceThumbnailsSnapshot"),
            payload.get("assetThumbnails"),
            payload.get("assetThumbnailsSnapshot"),
            allow_asset_identity_reference_ids=not asset_refs_resolved_by_input_links,
        ),
    ]
    if not asset_refs_resolved_by_input_links:
        explicit_reference_sources.extend(
            [
                resolved_config.get("explicitReferenceMediaIds"),
                resolved_config.get("referenceMediaIds"),
            ]
        )
    explicit_reference_ids = _merge_reference_ids(*explicit_reference_sources)
    asset_reference_ids = (
        []
        if asset_refs_resolved_by_input_links
        else _merge_reference_ids(
            _asset_reference_ids_from_generation_sources(payload),
            _asset_reference_ids_from_generation_sources(resolved_config),
            resolved_config.get("assetReferenceMediaIds"),
        )
    )
    reference_ids = _merge_reference_ids(
        explicit_reference_ids,
        asset_reference_ids,
    )
    if work_chain_native:
        # Work-chain storyboard sheets and identity pictures are not native frames.
        # The provider must receive only explicitly role-tagged frame materials.
        frame_input_rows = [row for row in _video_reference_rows_from_payload(payload) if is_frame_image(row)]
        allowed_frame_ids = {
            identity for row in frame_input_rows
            for identity in _video_reference_row_identity_values(row)
        }
        reference_ids = [item for item in reference_ids if item in allowed_frame_ids]
    # Media/version aliases may also appear in the generic media list. Exclude
    # those from image resolution without changing the ordered video inputs.
    video_reference_aliases = set(connected_reference_video_ids) | set(
        _video_reference_ids_from_rows(
            payload.get("referenceThumbnails"), payload.get("referenceThumbnailsSnapshot"),
            payload.get("assetThumbnails"), payload.get("assetThumbnailsSnapshot"),
            only_videos=True,
        )
    )
    reference_ids = [item for item in reference_ids if item not in video_reference_aliases]
    capability = video_model_capability(model) or {}
    video_image_limits = (capability.get("adapter_capabilities") or {}).get("reference_image_limits") or {}
    image_input_limits = {
        "max_long_edge": int(video_image_limits.get("max_side") or 0),
        "max_bytes": int(video_image_limits.get("max_bytes") or 20 * 1024 * 1024),
        "source": "video_model_capabilities",
        "defer_video_preparation": True,
    }
    inline_reference_images = _provider_reference_images_from_inline_files(
        project_id,
        _video_inline_reference_files_from_payload(payload),
        purpose="video-inline-reference",
        source="video_reference",
        image_input_limits=image_input_limits,
        prepare_transport_media=prepare_transport_media,
    )
    if work_chain_native and inline_reference_images:
        raise ValueError("原生首尾帧模式不能混用未标注用途的临时图片")
    resolved_references = _provider_reference_images_from_ids(
        project_id,
        episode_id,
        reference_ids,
        purpose="video-generation-reference",
        image_input_limits=image_input_limits,
        prepare_transport_media=prepare_transport_media,
        # Missing optional images may be omitted. Explicit enabled mentions are
        # checked against the actual transport manifest during prompt rendering.
        require_all=strategy == "character_replace_video",
        required_reference_label="视频生成参考图",
        resolution_workflow=workflow,
        allow_asset_library_lookup=not asset_refs_resolved_by_input_links,
        deduplicate_media=False,
    )
    linked_storyboard_reference = None
    storyboard_references: list[dict[str, Any]] = []
    asset_references: list[dict[str, Any]] = []
    seen_reference_keys: set[str] = set()

    def append_unique_reference(target: list[dict[str, Any]], reference: dict[str, Any] | None) -> None:
        if not isinstance(reference, dict):
            return
        key = video_reference_input_identity(reference) or str(
            reference.get("mediaId")
            or reference.get("versionId")
            or reference.get("requestedReferenceId")
            or reference.get("providerFileId")
            or reference.get("dataUrl")
            or ""
        )
        if key and key in seen_reference_keys:
            return
        if key:
            seen_reference_keys.add(key)
        target.append(reference)

    input_rows = _video_reference_rows_from_payload(payload)
    rows_by_reference_id = {
        _video_reference_row_reference_id(row): row for row in input_rows
        if _video_reference_row_reference_id(row)
    }
    frame_rows = {}
    for row in input_rows:
        if is_frame_image(row):
            for identity in _video_reference_row_identity_values(row):
                frame_rows[identity] = row
    for reference in resolved_references:
        # Source identity wins over media aliases: one file may also be an ordinary reference.
        row = rows_by_reference_id.get(str(reference.get("requestedReferenceId") or ""))
        if row is None:
            row = next((frame_rows[str(reference.get(key) or "")] for key in ("requestedReferenceId", "mediaId", "versionId", "assetId") if str(reference.get(key) or "") in frame_rows), None)
        if row is not None and is_frame_image(row):
            reference.update({"assetType": FRAME_IMAGE, "slot": FRAME_SLOT, **frame_options(row)})
        if row is not None and (_video_reference_row_slot(row) == "custom_image" or row.get("assetType") == "custom_image"):
            reference.update({"assetType": "custom_image", "slot": "custom_image"})
        if reference.get("assetType") != "custom_image" and not is_frame_image(reference) and _reference_is_storyboard_sheet(reference):
            append_unique_reference(storyboard_references, reference)
        else:
            append_unique_reference(asset_references, reference)
    for reference in inline_reference_images:
        append_unique_reference(asset_references, reference)
    if strategy == "storyboard_multi_shot" and not storyboard_references:
        linked_storyboard_reference = _extract_storyboard_reference_image(
            project_id,
            episode_id,
            workflow,
            node_id=str(payload.get("nodeId") or payload.get("node_id") or ""),
            route_id=str(payload.get("routeId") or payload.get("route_id") or ""),
            image_input_limits=image_input_limits,
            prepare_transport_media=prepare_transport_media,
        )
        if linked_storyboard_reference:
            append_unique_reference(storyboard_references, linked_storyboard_reference)
    references = storyboard_references + asset_references
    if prepare_transport_media:
        # 参考视频的输入限制、与图片混用限制，以及“带参考视频时”的输出时长
        # 必须在所有参考图解析完成后一次性校验，避免只校验视频本身而漏掉
        # 故事板分镜图 + 参考视频的供应商组合限制。
        validate_reference_videos(
            reference_videos,
            model,
            image_count=None if native_keyframe else len(references),
            output_duration=output_duration,
        )
    storyboard_reference_cleanup = {"enabled": False, "skipped": "original_storyboard_reference"}
    frame_transport = (
        select_frame_transport(
            references,
            model,
            reference_video_count=len(reference_videos),
            native_required=native_keyframe,
        )
        if native_keyframe or any(is_frame_image(row) for row in references)
        else {"mode": "reference_to_video", "nativeRoles": {}}
    )
    for index, reference in enumerate(references):
        reference["transportRole"] = frame_transport["nativeRoles"].get(index, "reference_image")
    if native_keyframe:
        expected_roles = {frame_options(row)["frameRole"] for row in input_rows if is_frame_image(row)}
        if work_chain_native and expected_roles != {"first_frame", "last_frame"}:
            raise ValueError("工作链无切镜直续需要实际上一段末帧作为原生首帧，以及本镜终态目标尾帧")
        if expected_roles != set(frame_transport["nativeRoles"].values()):
            raise ValueError("首尾帧关联与实际提交素材不一致，已阻止生成；请刷新素材关联后重试")
    max_reference_images = int(model.get("max_reference_images") or 0)
    supports = {str(item).strip().lower() for item in model.get("supports", []) if str(item).strip()}
    storyboard_sheet_reference_count = sum(1 for reference in references if _reference_is_storyboard_sheet(reference))
    supports_single_image_transport = "single_image_to_video" in supports
    supports_multi_reference_transport = bool(
        (
            model.get("supports_multi_reference_images") is True
            or model.get("supportsMultiReferenceImages") is True
            or supports.intersection({"multi_reference_video", "multi_reference"})
        )
        and max_reference_images >= 2
    )
    supports_storyboard_transport = (
        _model_supports_storyboard_reference_image(model)
        or bool(supports.intersection({"storyboard_reference_image", "storyboard_grid_reference"}))
    )
    supports_reference_transport = supports_storyboard_transport or supports_single_image_transport
    selected_mode = next(
        (mode for mode in ((model.get("adapter_capabilities") or {}).get("keyframe_visual_inputs") or {}).get("modes", [])
         if mode.get("id") == frame_transport["mode"]),
        {},
    ) if native_keyframe else {}
    effective_reference_limit = (
        int((selected_mode.get("max_counts") or {}).get("reference_image", 0)) + len(frame_transport["nativeRoles"])
        if native_keyframe else max_reference_images + len(frame_transport["nativeRoles"])
    )
    transport_reference_limit = 0
    transport_block_reason = ""
    if native_keyframe or supports_reference_transport:
        transport_limit = effective_reference_limit
        if not native_keyframe and transport_limit > 1 and not supports_multi_reference_transport:
            transport_limit = 1
        transport_reference_limit = max(0, transport_limit)
        if references and transport_reference_limit <= 0:
            transport_block_reason = (
                "当前模型未声明参考图数量上限，已阻断视频生成；"
                "不能猜测可传参考图数量或提交不完整资料。"
            )
            transport_references = []
        elif references and len(references) > transport_reference_limit:
            transport_block_reason = (
                f"当前任务解析到 {len(references)} 张参考图，但所选模型参考图上限为 "
                f"{transport_reference_limit} 张；已阻断生成，不能裁掉多余参考图后提交不完整资料。"
                "请减少参考图或切换支持更多参考图的模型。"
            )
            transport_references = []
        else:
            transport_references = list(references) if references else []
    else:
        if references:
            transport_block_reason = (
                "当前模型未声明参考图能力，已阻断视频生成；"
                "不能回退为纯文本或提交不完整参考图。"
            )
        transport_references = []
    selected_reference = transport_references[0] if transport_references else None
    reference_metadata = [_provider_reference_metadata(reference) for reference in references]
    reference_manifest = merge_prompt_manifest(
        reference_manifest_from_rows(transport_references, reference_videos),
        [] if work_chain_native else payload.get("referenceManifest") or [],
    )
    adapter_transport = (
        "transport_blocked"
        if transport_block_reason
        else "multi_reference_images"
        if len(transport_references) > 1
        else "single_reference_image"
        if selected_reference
        else "text_prompt_only"
    )
    reference_plan: dict[str, Any] = {
        "strategy": strategy,
        "frameTransportMode": frame_transport["mode"],
        "nativeFrameCount": len(frame_transport["nativeRoles"]),
        "referenceMediaIds": reference_ids,
        "explicitReferenceMediaIds": explicit_reference_ids,
        "assetReferenceMediaIds": asset_reference_ids,
        "resolvedReferenceCount": len(references),
        "transportReferenceCount": len(transport_references),
        "providerReferenceLimit": transport_reference_limit,
        "transportBlocked": bool(transport_block_reason),
        "transportBlockReason": transport_block_reason,
        "declaredMaxReferenceImages": max_reference_images,
        "referenceInputLimits": image_input_limits,
        "storyboardSheetReferenceCount": storyboard_sheet_reference_count,
        "assetReferenceCount": len(asset_references),
        "inlineReferenceCount": len(inline_reference_images),
        "storyboardPanelCropCount": 0,
        "selectedReference": _provider_reference_metadata(selected_reference),
        "references": reference_metadata,
        "storyboardReferenceCleanup": storyboard_reference_cleanup,
        "adapterTransport": adapter_transport,
        "referenceManifest": copy.deepcopy(reference_manifest),
        "referenceVideos": copy.deepcopy(reference_videos),
        "referenceVideoCount": len(reference_videos),
    }
    if linked_storyboard_reference:
        reference_plan["linkedStoryboardReference"] = "current_active_version"
    if transport_block_reason:
        reference_plan["adapterNote"] = transport_block_reason
    canvas_perf_log(
        "video_provider_reference_plan",
        projectId=project_id,
        episodeId=episode_id,
        nodeId=str(payload.get("nodeId") or payload.get("node_id") or ""),
        strategy=strategy,
        durationMs=canvas_perf_elapsed_ms(perf_started_at),
        referenceIdCount=len(reference_ids),
        explicitReferenceIdCount=len(explicit_reference_ids),
        assetReferenceIdCount=len(asset_reference_ids),
        inlineReferenceCount=len(inline_reference_images),
        resolvedReferenceCount=len(references),
        transportReferenceCount=len(transport_references),
        storyboardSheetReferenceCount=storyboard_sheet_reference_count,
        storyboardReferenceCleanedCount=int(storyboard_reference_cleanup.get("cleanedReferenceCount") or 0),
        storyboardReferenceLabelMaskCount=int(storyboard_reference_cleanup.get("labelMaskCount") or 0),
        transportBlocked=bool(transport_block_reason),
        prepareTransportMedia=bool(prepare_transport_media),
    )
    return selected_reference, transport_references, reference_plan


VISUAL_HANDOFF_REFERENCE_BRIEF = "仅参考空间连续性中的位置、朝向、视线与终态，不参考机位、景别、构图，不改变剧情。"
