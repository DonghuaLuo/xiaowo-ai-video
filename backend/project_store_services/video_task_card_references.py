# -*- coding: utf-8 -*-
"""视频生成引用身份、预览、缩略图与统一引用清单。"""
from __future__ import annotations
from .reference_read_context import ReferenceReadContext
from .canvas_ownership import VIDEO_TASK_NODE_TYPES

from dataclasses import dataclass

import copy
import json
import re
import traceback
from .agent_sessions import (
    _project_dir,
)
from .canvas_store_queries import read_card_results
from .catalogs import (
    GLOBAL_DIR,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
)
from .generation_input_context import (
    _workflow_node_by_id,
    _workflow_node_data_dict,
    _workflow_node_type_name,
)
from .planning_contract import (
    _append_unique_string,
)
from .prompt_asset_context import (
    _video_task_card_asset_name_map_from_inputs,
    _video_task_card_named_input_snapshot,
)
from .reference_utils import (
    ASSET_REF_COLLECTIONS as _SHARED_ASSET_REF_COLLECTIONS,
)
from .video_reference_metadata import (
    REFERENCE_DESCRIPTION_KEYS,
    is_reference_text_placeholder,
    normalize_reference_text,
    video_reference_input_identity,
)
from pathlib import (
    Path,
)
from typing import (
    Any,
)
from utils.video_references import (
    VIDEO_REFERENCE_SLOT,
    reference_manifest_from_rows,
    reference_rows_in_transport_order,
    reference_video_source_ids,
)
from utils.frame_references import is_frame_image, select_frame_transport
from utils.video_model_capabilities import video_model_capability
from utils.video_prompt_mentions import bind_prompt_mentions, merge_prompt_manifest, resolve_prompt_mentions


_ASSET_REF_COLLECTIONS = _SHARED_ASSET_REF_COLLECTIONS


def _video_task_card_row_is_input_link(row: dict[str, Any]) -> bool:
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


def _video_task_card_reference_id_from_row(row: dict[str, Any]) -> str:
    if _video_task_card_row_is_input_link(row):
        for key in ("sourceNodeId", "source_node_id"):
            text = str(row.get(key) or "").strip()
            if text:
                return text
    for key in (
        "mediaId",
        "media_id",
        "mediaVersionId",
        "media_version_id",
        "sourceVersionId",
        "source_version_id",
        "versionId",
        "version_id",
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
    return ""


_VIDEO_TASK_CARD_IMAGE_REFERENCE_FILE_RE = re.compile(r"\.(png|jpe?g|webp|gif|bmp|tiff?|avif)(?:[?#].*)?$", re.I)


_VIDEO_TASK_CARD_VIDEO_REFERENCE_FILE_RE = re.compile(r"\.(mp4|m4v|mov|webm|avi|mkv)(?:[?#].*)?$", re.I)


_VIDEO_TASK_CARD_ASSET_REFERENCE_SLOTS = (
    "custom_image",
    "frame_reference",
    "character_reference",
    "creature_reference",
    "scene_reference",
    "prop_reference",
    "visual_handoff_reference",
)


_VIDEO_TASK_CARD_ASSET_SLOT_TO_COLLECTION = {
    "character_reference": "characters",
    "creature_reference": "creatures",
    "scene_reference": "scenes",
    "prop_reference": "props",
}


def _video_task_card_media_reference_path(*records: Any) -> str:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in (
            "path",
            "file",
            "filePath",
            "file_path",
            "relativePath",
            "relative_path",
            "url",
            "preview",
            "previewUrl",
            "preview_url",
            "previewSrc",
            "preview_src",
            "thumbnail",
            "thumbnailUrl",
            "thumbnail_url",
            "dataUrl",
            "data_url",
        ):
            text = str(record.get(key) or "").strip()
            if text:
                return text
    return ""


def _video_task_card_media_reference_kind(*records: Any) -> str:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in (
            "mediaKind",
            "media_kind",
            "mediaType",
            "media_type",
            "kind",
            "mimeType",
            "mime_type",
        ):
            text = str(record.get(key) or "").strip().lower()
            if text == "video" or text.startswith("video/"):
                return "video"
            if text == "image" or text.startswith("image/"):
                return "image"
    path = _video_task_card_media_reference_path(*records)
    if _VIDEO_TASK_CARD_VIDEO_REFERENCE_FILE_RE.search(path):
        return "video"
    if _VIDEO_TASK_CARD_IMAGE_REFERENCE_FILE_RE.search(path):
        return "image"
    return ""


def _video_task_card_row_is_image_reference(
    workflow: dict[str, Any] | None,
    row: dict[str, Any],
) -> bool:
    if not isinstance(row, dict):
        return False
    slot = str(row.get("slot") or row.get("targetSlot") or row.get("target_slot") or "").strip()
    if slot and slot not in ("storyboard_image", *_VIDEO_TASK_CARD_ASSET_REFERENCE_SLOTS):
        return False
    source_node_id = (
        str(row.get("sourceNodeId") or row.get("source_node_id") or "").strip()
        if _video_task_card_row_is_input_link(row)
        else ""
    )
    source_node = _workflow_node_by_id(workflow or {}, source_node_id) if source_node_id else None
    if source_node:
        source_type = _workflow_node_type_name(source_node)
        if source_type in {"asset.image", "storyboard.image"}:
            return True
        if source_type == "media.external":
            data = _workflow_node_data_dict(source_node)
            media = data.get("media") if isinstance(data.get("media"), dict) else {}
            storage = data.get("storage") if isinstance(data.get("storage"), dict) else {}
            return _video_task_card_media_reference_kind(data, media, storage) == "image"
        return False
    source_node_type = str(row.get("sourceNodeType") or row.get("source_node_type") or "").strip()
    if source_node_type in {"video.result", *VIDEO_TASK_NODE_TYPES}:
        return False
    if source_node_type in {"asset.image", "storyboard.image"}:
        return True
    media = row.get("media") if isinstance(row.get("media"), dict) else {}
    storage = row.get("storage") if isinstance(row.get("storage"), dict) else {}
    return _video_task_card_media_reference_kind(row, media, storage) == "image"


def _video_task_card_reference_ids(
    input_snapshot: dict[str, Any],
    workflow: dict[str, Any] | None = None,
) -> list[str]:
    reference_rows: list[dict[str, Any]] = []
    allowed_slots = {"storyboard_image", *_VIDEO_TASK_CARD_ASSET_REFERENCE_SLOTS}
    for row in input_snapshot.get("inputLinks") or []:
        if not isinstance(row, dict):
            continue
        slot = str(
            row.get("targetSlot") or row.get("target_slot") or row.get("slot") or ""
        ).strip()
        if slot not in allowed_slots or not _video_task_card_row_is_image_reference(workflow, row):
            continue
        if _video_task_card_reference_id_from_row(row):
            reference_rows.append(row)
    rows: list[str] = []
    for row in reference_rows_in_transport_order(reference_rows):
        rows = _append_unique_string(rows, _video_task_card_reference_id_from_row(row))
    return rows


def _video_task_card_thumbnail_label(row: dict[str, Any], fallback: str) -> str:
    for key in ("label", "displayName", "display_name", "assetName", "asset_name", "name", "title"):
        text = str(row.get(key) or "").strip()
        if text:
            return text
    return fallback


def _video_task_card_thumbnail_text_from_keys(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    media = row.get("media") if isinstance(row.get("media"), dict) else {}
    storage = row.get("storage") if isinstance(row.get("storage"), dict) else {}
    for source in (row, media, storage):
        if not isinstance(source, dict):
            continue
        for key in keys:
            text = normalize_reference_text(source.get(key))
            if not text:
                continue
            if is_reference_text_placeholder(text):
                continue
            return text
    return ""


def _video_task_card_thumbnail_description(row: dict[str, Any]) -> str:
    """Full local reference semantics for task-card understanding, not supplier prompt."""
    return _video_task_card_thumbnail_text_from_keys(row, REFERENCE_DESCRIPTION_KEYS)


def _video_task_card_thumbnail_identity_values(row: dict[str, Any]) -> list[str]:
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
    if _video_task_card_row_is_input_link(row):
        for key in ("sourceNodeId", "source_node_id"):
            add(row.get(key))
    for nested_key in ("media", "storage"):
        nested = row.get(nested_key)
        if not isinstance(nested, dict):
            continue
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


def _video_task_card_thumbnail_media_reference_id(row: dict[str, Any]) -> str:
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
    return ""


def _video_task_card_inline_or_remote_media_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.casefold().startswith(("http://", "https://", "data:", "blob:")):
        return text
    return ""


def _video_task_card_displayable_media_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text or _video_task_card_inline_or_remote_media_value(text):
        return ""
    clean = text.split("?", 1)[0].split("#", 1)[0]
    suffix = Path(clean).suffix.lower()
    if suffix not in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS):
        return ""
    return text


def _video_task_card_resolve_local_media_path(project_id: str, value: Any) -> str:
    text = _video_task_card_displayable_media_path(value)
    if not text:
        return ""
    raw_path = Path(text)
    if raw_path.is_absolute():
        return str(raw_path)
    clean = text.replace("\\", "/").lstrip("/")
    parts = [part for part in clean.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        return ""
    project_root = _project_dir(project_id).resolve()
    global_root = GLOBAL_DIR.resolve()
    clean_key = clean.casefold()
    roots = (
        [global_root, project_root]
        if clean_key.startswith(("asset_media/", "style_references/"))
        else [project_root, global_root]
    )
    fallback = ""
    for root in roots:
        candidate = (root / Path(*parts)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        fallback = fallback or str(candidate)
        if candidate.exists():
            return str(candidate)
    return fallback


def _video_task_card_first_media_field(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _video_task_card_thumbnail_preview_value(*rows: dict[str, Any]) -> str:
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in (
            "previewSrc",
            "preview_src",
            "preview",
            "url",
            "previewUrl",
            "preview_url",
            "thumbnail",
            "thumbnailUrl",
            "thumbnail_url",
            "dataUrl",
            "data_url",
        ):
            preview = _video_task_card_inline_or_remote_media_value(row.get(key))
            if preview:
                return preview
    return ""


def _video_task_card_thumbnail_local_path(project_id: str, *rows: dict[str, Any]) -> str:
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in (
            "path",
            "filePath",
            "file_path",
            "relativePath",
            "relative_path",
            "file",
            "pngFile",
            "png_file",
        ):
            path = _video_task_card_resolve_local_media_path(project_id, row.get(key))
            if path:
                return path
    return ""


def _workflow_input_thumbnail_for_display(
    project_id: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    item = copy.deepcopy(row)
    media = (
        copy.deepcopy(item.get("media"))
        if isinstance(item.get("media"), dict)
        else copy.deepcopy(item.get("storage"))
        if isinstance(item.get("storage"), dict)
        else {}
    )
    storage = item.get("storage") if isinstance(item.get("storage"), dict) else {}

    for key in (
        "kind",
        "mimeType",
        "mime_type",
        "width",
        "height",
        "aspectRatio",
        "aspect_ratio",
        "durationSeconds",
        "duration_seconds",
        "relativePath",
        "relative_path",
        "file",
        "pngFile",
        "png_file",
        "url",
        "preview",
    ):
        value = _video_task_card_first_media_field(media, key)
        if value in (None, ""):
            value = _video_task_card_first_media_field(item, key)
        if value not in (None, "") and media.get(key) in (None, ""):
            media[key] = copy.deepcopy(value)

    media_id = _video_task_card_thumbnail_media_reference_id(item)
    if media_id:
        media.setdefault("id", media_id)
        media.setdefault("mediaId", media_id)
        item.setdefault("mediaId", media_id)

    preview = _video_task_card_thumbnail_preview_value(media, item, storage)
    local_path = _video_task_card_thumbnail_local_path(project_id, media, item, storage)
    if local_path:
        media["path"] = local_path
        media["filePath"] = local_path
        item.setdefault("path", local_path)
        item.setdefault("filePath", local_path)
    media_kind = _video_task_card_media_reference_kind(media, item)
    if local_path and media_kind == "video":
        try:
            from .video_clips import ensure_video_thumbnail

            media.update(ensure_video_thumbnail(project_id, media))
        except Exception:
            # A missing thumbnail must not make an otherwise valid video link unusable.
            pass
    if preview:
        media.setdefault("preview", preview)
        item["previewSrc"] = preview
    elif local_path:
        item["previewSrc"] = local_path

    if _video_task_card_thumbnail_preview_value(media) or _video_task_card_thumbnail_local_path(project_id, media):
        item["media"] = media
    return item


def _video_task_card_thumbnail_key(row: dict[str, Any]) -> tuple[str, str]:
    reference_id = video_reference_input_identity(row)
    if reference_id:
        return "image", reference_id
    slot = str(row.get("targetSlot") or row.get("target_slot") or row.get("slot") or "").strip()
    identity = "|".join(_video_task_card_thumbnail_identity_values(row)).strip()
    if not identity:
        identity = "no-id:" + json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    return slot, identity


def _video_task_card_append_thumbnail(
    rows: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    row: dict[str, Any] | None,
    *,
    slot: str,
    fallback_label: str,
    source: str,
) -> None:
    if not isinstance(row, dict):
        return
    item = copy.deepcopy(row)
    item["slot"] = slot
    item["targetSlot"] = slot
    item.setdefault("displayOnly", True)
    item.setdefault("displaySource", source)
    item.setdefault("referenceRole", slot)
    inherited_from = str(
        item.get("inheritedFromNodeId")
        or item.get("inherited_from_node_id")
        or item.get("inputOwnerNodeId")
        or item.get("input_owner_node_id")
        or ""
    ).strip()
    link_scope = "work_chain" if inherited_from else "direct"
    item.setdefault("linkScope", link_scope)
    item.setdefault("link_scope", link_scope)
    label = _video_task_card_thumbnail_label(item, fallback_label)
    if label:
        item["label"] = label
        item.setdefault("displayName", label)
    if slot == "custom_image":
        item["assetType"] = "custom_image"
        item.setdefault("referenceGroup", "direct_reference")
        item.setdefault("reference_group", "direct_reference")
    elif slot == "frame_reference":
        item["assetType"] = "frame_image"
        item.setdefault("referenceGroup", "direct_reference")
        item.setdefault("reference_group", "direct_reference")
    elif slot == "visual_handoff_reference":
        item["assetType"] = "visual_handoff"
        item.setdefault("referenceGroup", "direct_reference")
        item.setdefault("reference_group", "direct_reference")
    elif slot == "storyboard_image":
        item.setdefault("assetType", "storyboard")
        item.setdefault("sourceType", "storyboard_image")
        item.setdefault("referenceGroup", "direct_reference")
        item.setdefault("reference_group", "direct_reference")
    elif slot in _VIDEO_TASK_CARD_ASSET_SLOT_TO_COLLECTION:
        collection = _VIDEO_TASK_CARD_ASSET_SLOT_TO_COLLECTION[slot]
        item.setdefault("assetType", collection.rstrip("s"))
        item.setdefault("sourceType", "asset")
        reference_group = "work_chain_asset" if link_scope == "work_chain" else "direct_reference"
        item.setdefault("referenceGroup", reference_group)
        item.setdefault("reference_group", reference_group)
    key = _video_task_card_thumbnail_key(item)
    if key[1] and key in seen:
        return
    if key[1]:
        seen.add(key)
    rows.append(item)


def _video_task_card_storyboard_version_from_node(
    project_id: str,
    episode_id: str,
    storyboard_node: dict[str, Any] | None,
    *,
    read_context: ReferenceReadContext | None = None,
) -> dict[str, Any] | None:
    if not isinstance(storyboard_node, dict):
        return None
    node_id = str(storyboard_node.get("id") or "").strip()
    if not node_id:
        return None
    data = _workflow_node_data_dict(storyboard_node)
    versions = read_context.card_results(episode_id, node_id) if read_context is not None else read_card_results(project_id, episode_id, node_id)
    active_id = str(
        data.get("activeVersionId")
        or data.get("activeMediaVersionId")
        or data.get("mediaVersionId")
        or ""
    ).strip()
    selected = (
        next((item for item in versions if str(item.get("id") or "") == active_id), None)
        if active_id
        else None
    )
    if isinstance(selected, dict):
        selected_status = str(selected.get("status") or "").strip().lower()
        if (
            selected_status
            in {
                "failed",
                "blocked",
                "cancelled",
                "canceled",
                "processing",
                "queued",
                "running",
                "waiting",
                "waiting_upstream",
            }
            or not isinstance(selected.get("media"), dict)
        ):
            selected = None
    if not isinstance(selected, dict):
        try:
            from .workflow_input_resolution import workflow_current_media_reference

            current_media = workflow_current_media_reference(
                project_id,
                episode_id,
                {"nodes": [storyboard_node], "edges": []},
                node_id,
                read_context=read_context,
            )
        except Exception:
            current_media = None
        if not isinstance(current_media, dict):
            return None
        current_version_id = str(
            active_id
            or current_media.get("versionId")
            or current_media.get("mediaVersionId")
            or current_media.get("media_version_id")
            or current_media.get("id")
            or f"current-{node_id}"
        ).strip()
        return {
            "id": current_version_id,
            "nodeId": node_id,
            "title": data.get("title") or data.get("name") or "分镜图",
            "status": "completed",
            "media": copy.deepcopy(current_media),
            "payload": {},
        }
    return copy.deepcopy(selected)


def _video_task_card_storyboard_thumbnail_from_node(
    project_id: str,
    episode_id: str,
    storyboard_node: dict[str, Any] | None,
    *,
    read_context: ReferenceReadContext | None = None,
) -> dict[str, Any] | None:
    if not isinstance(storyboard_node, dict):
        return None
    node_id = str(storyboard_node.get("id") or "").strip()
    if not node_id:
        return None
    data = _workflow_node_data_dict(storyboard_node)
    selected = _video_task_card_storyboard_version_from_node(
        project_id,
        episode_id,
        storyboard_node,
        read_context=read_context,
    )
    if not isinstance(selected, dict):
        return None
    media = copy.deepcopy(selected.get("media")) if isinstance(selected.get("media"), dict) else None
    label = str(data.get("title") or selected.get("title") or "分镜图").strip()
    row: dict[str, Any] = {
        "id": f"thumb_{node_id}_{selected.get('id') or 'active'}",
        "label": label,
        "displayName": label,
        "sourceNodeId": node_id,
        "sourceNodeType": str(storyboard_node.get("type") or "storyboard.image"),
        "sourceId": str(selected.get("id") or ""),
        "sourceVersionId": str(selected.get("id") or ""),
        "mediaVersionId": str(selected.get("id") or ""),
        "assetType": "storyboard",
        "sourceType": "storyboard_image",
    }
    if media:
        row["media"] = media
        row["mediaId"] = str(media.get("id") or selected.get("id") or "")
    return row


def _video_task_card_asset_input_links(
    input_snapshot: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    allowed_slots = set(_VIDEO_TASK_CARD_ASSET_REFERENCE_SLOTS)
    for link in input_snapshot.get("inputLinks") or []:
        if not isinstance(link, dict):
            continue
        slot = str(
            link.get("targetSlot") or link.get("target_slot") or link.get("slot") or ""
        ).strip()
        if slot not in allowed_slots:
            continue
        identity = str(
            link.get("id")
            or link.get("linkId")
            or link.get("link_id")
            or link.get("inputLinkId")
            or link.get("input_link_id")
            or link.get("sourceNodeId")
            or link.get("source_node_id")
            or link.get("rootAssetId")
            or link.get("mediaVersionId")
            or link.get("media_version_id")
            or link.get("sourceVersionId")
            or link.get("source_version_id")
            or link.get("mediaId")
            or link.get("media_id")
            or link.get("assetId")
            or ""
        ).strip()
        key = (slot, identity or json.dumps(link, ensure_ascii=False, sort_keys=True, default=str))
        if key in seen:
            continue
        seen.add(key)
        rows.append((slot, copy.deepcopy(link)))
    return rows


def _video_task_card_current_asset_refs(
    input_snapshot: dict[str, Any],
) -> tuple[dict[str, list[str]], bool]:
    grouped: dict[str, list[str]] = {key: [] for key in _ASSET_REF_COLLECTIONS}

    def add_token(collection: str, token: Any) -> None:
        if collection not in grouped:
            return
        text = str(token or "").strip()
        if text and text not in grouped[collection]:
            grouped[collection].append(text)

    asset_input_links = _video_task_card_asset_input_links(input_snapshot)
    if asset_input_links:
        for slot, link in asset_input_links:
            collection = _VIDEO_TASK_CARD_ASSET_SLOT_TO_COLLECTION.get(slot, "")
            add_token(
                collection,
                link.get("rootAssetId")
                or link.get("assetId")
            )

    return {key: value for key, value in grouped.items() if value}, bool(asset_input_links) or bool(input_snapshot.get("assetRefsResolvedByInputLinks"))


def _video_task_card_reference_thumbnails(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    input_snapshot: dict[str, Any],
    *,
    read_context: ReferenceReadContext | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in input_snapshot.get("inputLinks") or []:
        if not isinstance(row, dict):
            continue
        slot = str(
            row.get("targetSlot") or row.get("target_slot") or row.get("slot") or ""
        ).strip()
        if slot not in ("storyboard_image", *_VIDEO_TASK_CARD_ASSET_REFERENCE_SLOTS):
            continue
        if not _video_task_card_row_is_image_reference(workflow, row):
            continue
        if slot == "storyboard_image":
            source_node_id = str(row.get("sourceNodeId") or row.get("source_node_id") or "").strip()
            source_node = _workflow_node_by_id(workflow, source_node_id) if source_node_id else None
            if source_node and _workflow_node_type_name(source_node) == "storyboard.image":
                hydrated = _video_task_card_storyboard_thumbnail_from_node(
                    project_id, episode_id, source_node,
                    read_context=read_context,
                )
                if not hydrated:
                    continue
            else:
                hydrated = copy.deepcopy(row)
        else:
            hydrated = copy.deepcopy(row)
        _video_task_card_append_thumbnail(
            rows,
            seen,
            hydrated,
            slot=slot,
            fallback_label="分镜图" if slot == "storyboard_image" else "资产",
            source="video_task_input_snapshot",
        )

    return [
        _workflow_input_thumbnail_for_display(project_id, row)
        for row in rows
    ]


def _video_task_card_reference_video_thumbnails(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    input_snapshot: dict[str, Any],
    *,
    read_context: ReferenceReadContext | None = None,
) -> list[dict[str, Any]]:
    """Hydrate reference-video links with the persistent video thumbnail."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for link in input_snapshot.get("inputLinks") or []:
        if not isinstance(link, dict):
            continue
        slot = str(
            link.get("targetSlot") or link.get("target_slot") or link.get("slot") or ""
        ).strip()
        if slot != VIDEO_REFERENCE_SLOT:
            continue
        hydrated = copy.deepcopy(link)
        source_node_id = str(
            hydrated.get("sourceNodeId")
            or hydrated.get("source_node_id")
            or ""
        ).strip()
        if source_node_id:
            try:
                from .workflow_input_resolution import workflow_current_media_reference

                source_media = workflow_current_media_reference(
                    project_id,
                    episode_id,
                    workflow,
                    source_node_id,
                    read_context=read_context,
                )
            except Exception:
                source_media = None
            if not isinstance(source_media, dict) or not source_media:
                source_node = _workflow_node_by_id(workflow, source_node_id)
                source_data = (
                    source_node.get("data")
                    if isinstance(source_node, dict) and isinstance(source_node.get("data"), dict)
                    else {}
                )
                source_media = (
                    source_data.get("media")
                    if isinstance(source_data.get("media"), dict)
                    else source_data.get("storage")
                    if isinstance(source_data.get("storage"), dict)
                    else None
                )
            if isinstance(source_media, dict) and source_media:
                current_media = hydrated.get("media") if isinstance(hydrated.get("media"), dict) else {}
                hydrated["media"] = {
                    **copy.deepcopy(source_media),
                    **copy.deepcopy(current_media),
                }
        _video_task_card_append_thumbnail(
            rows,
            seen,
            hydrated,
            slot=VIDEO_REFERENCE_SLOT,
            fallback_label="参考视频",
            source="video_task_input_snapshot",
        )
    return [
        _workflow_input_thumbnail_for_display(project_id, row)
        for row in rows
    ]


def _video_task_card_split_thumbnails(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reference_thumbnails: list[dict[str, Any]] = []
    asset_thumbnails: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slot = str(row.get("targetSlot") or row.get("target_slot") or row.get("slot") or "").strip()
        if slot == "storyboard_image":
            reference_thumbnails.append(copy.deepcopy(row))
        elif slot in _VIDEO_TASK_CARD_ASSET_REFERENCE_SLOTS:
            asset_thumbnails.append(copy.deepcopy(row))
    return reference_thumbnails, asset_thumbnails


def _video_task_card_reference_manifest(
    project_id: str,
    node: dict[str, Any],
    input_snapshot: dict[str, Any],
    image_rows: list[dict[str, Any]],
    video_rows: list[dict[str, Any]],
    *,
    read_context: ReferenceReadContext | None = None,
) -> list[dict[str, Any]]:
    images = [{**row, "transportRole": "reference_image"} for row in reference_rows_in_transport_order(image_rows)]
    video_ids = reference_video_source_ids(input_snapshot)
    node_type = _workflow_node_type_name(node)
    if node_type in VIDEO_TASK_NODE_TYPES and (node_type == "video.keyframe" or any(is_frame_image(row) for row in images)):
        from .model_provider_config import _project_model_selection
        from .provider_models import _find_model

        data = _workflow_node_data_dict(node)
        config = data.get("generationConfig") if isinstance(data.get("generationConfig"), dict) else {}
        model_id = str(config.get("modelId") or config.get("model_id") or "").strip()
        capabilities, model_config = read_context.model_selection if read_context is not None else _project_model_selection(project_id)
        if not model_id:
            model_id = str((model_config.get("video") or {}).get("model_id") or "").strip()
        configured_model = _find_model(model_id, "video", capabilities)
        model = video_model_capability(configured_model or model_id)
        try:
            selection = select_frame_transport(
                images, model or {}, reference_video_count=len(video_ids),
                native_required=node_type == "video.keyframe",
            )
        except ValueError:
            # Invalid/unconfigured combinations must remain editable without claiming a transport index.
            for row in images:
                row["transportRole"] = "unresolved"
        else:
            for index, row in enumerate(images):
                row["transportRole"] = selection["nativeRoles"].get(index, "reference_image")
    submitted = reference_manifest_from_rows(images, video_rows, video_source_ids=video_ids)
    links = input_snapshot.get("inputLinks") or []
    associations = reference_manifest_from_rows(
        [row for row in links if row.get("slot") != VIDEO_REFERENCE_SLOT],
        [row for row in links if row.get("slot") == VIDEO_REFERENCE_SLOT],
    )
    return merge_prompt_manifest(submitted, associations)


def video_task_card_current_reference_snapshot(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_id: str,
    input_snapshot: dict[str, Any] | None = None,
    *,
    asset_name_map: dict[str, str] | None = None,
    read_context: ReferenceReadContext | None = None,
    for_generation: bool = False,
) -> dict[str, Any]:
    node = _workflow_node_by_id(workflow, node_id)
    if not node:
        return {}
    if not isinstance(input_snapshot, dict):
        try:
            from .workflow_asset_resolution import resolve_workflow_node_inputs

            input_snapshot = resolve_workflow_node_inputs(
                project_id,
                episode_id,
                {"nodeId": node_id},
            )
        except Exception:
            print(traceback.format_exc(), flush=True)
            input_snapshot = {}
    if asset_name_map is None:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        card = data.get("videoTaskCard") if isinstance(data.get("videoTaskCard"), dict) else {}
        asset_name_map = card.get("assetNameMap") if isinstance(card.get("assetNameMap"), dict) else {}
    display_snapshot = _video_task_card_named_input_snapshot(
        project_id, {"inputLinks": input_snapshot.get("referenceDisplayRows", input_snapshot.get("inputLinks", []))},
        asset_name_map=asset_name_map, read_context=read_context,
    )
    input_snapshot = _video_task_card_named_input_snapshot(
        project_id, input_snapshot, asset_name_map=asset_name_map, read_context=read_context,
    )
    if for_generation:
        from .workflow_input_resolution import _workflow_video_reference_link_ready
        from .workflow_reference_usage import input_reference_enabled

        links = input_snapshot.get("inputLinks") or []
        expected_links = [row for row in display_snapshot["inputLinks"] if row.get("enabled") is not False]
        expected_links.extend(row for row in input_snapshot.get("ignoredOfflineAssetLinks") or []
                              if input_reference_enabled(workflow, row))
        expected = reference_manifest_from_rows(
            [row for row in expected_links if row.get("slot") != VIDEO_REFERENCE_SLOT],
            [row for row in expected_links if row.get("slot") == VIDEO_REFERENCE_SLOT],
        )
        card = (node.get("data") or {}).get("videoTaskCard") or {}
        prompt = str(card.get("finalVideoPrompt") or "")
        bindings = bind_prompt_mentions(prompt, card.get("promptBindings") or {}, expected)
        ready = [row for row in links if _workflow_video_reference_link_ready(project_id, episode_id, workflow, row)]
        available = reference_manifest_from_rows(
            [row for row in ready if row.get("slot") != VIDEO_REFERENCE_SLOT],
            [row for row in ready if row.get("slot") == VIDEO_REFERENCE_SLOT],
        )
        resolve_prompt_mentions(prompt, bindings, available, enabled_manifest=expected)
        input_snapshot = {**input_snapshot, "inputLinks": ready}
    thumbnail_rows = _video_task_card_reference_thumbnails(
        project_id,
        episode_id,
        workflow,
        input_snapshot,
        read_context=read_context,
    )
    reference_video_thumbnails = _video_task_card_reference_video_thumbnails(
        project_id,
        episode_id,
        workflow,
        input_snapshot,
        read_context=read_context,
    )
    reference_thumbnails, asset_thumbnails = _video_task_card_split_thumbnails(thumbnail_rows)
    snapshot_reference_ids: list[str] = []
    for item in _video_task_card_reference_ids({"inputLinks": thumbnail_rows}, workflow):
        snapshot_reference_ids = _append_unique_string(snapshot_reference_ids, item)
    reference_media_ids = copy.deepcopy(snapshot_reference_ids)
    for row in reference_thumbnails + asset_thumbnails:
        reference_media_ids = _append_unique_string(
            reference_media_ids,
            _video_task_card_thumbnail_media_reference_id(row),
        )
    asset_reference_media_ids: list[str] = []
    for row in asset_thumbnails:
        asset_reference_media_ids = _append_unique_string(
            asset_reference_media_ids,
            _video_task_card_thumbnail_media_reference_id(row),
        )
    asset_refs, asset_refs_resolved_by_links = _video_task_card_current_asset_refs(
        input_snapshot,
    )
    if for_generation:
        ready_links = input_snapshot["inputLinks"]
        input_snapshot = {
            **input_snapshot, "inputs": ready_links, "referenceMediaIds": reference_media_ids,
            "assetRefs": copy.deepcopy(asset_refs),
            "groupedBySlot": {slot: [row for row in ready_links if row.get("slot") == slot]
                              for slot in dict.fromkeys(row.get("slot") for row in ready_links)},
        }
    return {
        "inputSnapshot": copy.deepcopy(input_snapshot),
        "inputLinksSnapshot": copy.deepcopy(input_snapshot.get("inputLinks") or []),
        "referenceDisplayRows": [
            _workflow_input_thumbnail_for_display(project_id, row)
            for row in display_snapshot.get("inputLinks", [])
        ],
        "referenceThumbnails": copy.deepcopy(reference_thumbnails),
        "assetThumbnails": copy.deepcopy(asset_thumbnails),
        "referenceVideoThumbnails": copy.deepcopy(reference_video_thumbnails),
        "referenceManifest": _video_task_card_reference_manifest(
            project_id, node, input_snapshot,
            thumbnail_rows,
            reference_video_thumbnails,
            read_context=read_context,
        ),
        "referenceMediaIds": reference_media_ids,
        "referenceMediaIdsSnapshot": snapshot_reference_ids,
        "assetReferenceMediaIds": asset_reference_media_ids,
        "assetRefs": copy.deepcopy(asset_refs),
        "assetRefsResolvedByInputLinks": asset_refs_resolved_by_links,
    }


@dataclass(frozen=True)
class VideoTaskCardReferences:
    """One resolved set of bound media identities and the record patches derived from it."""

    input_snapshot: dict[str, Any]
    asset_names: dict[str, str]
    reference_thumbnails: list[dict[str, Any]]
    asset_thumbnails: list[dict[str, Any]]
    thumbnail_reference_ids: list[str]
    reference_ids: list[str]
    asset_reference_media_ids: list[str]
    record_patch: dict[str, Any]
    card_patch: dict[str, Any]


def _resolve_video_task_card_references(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
) -> VideoTaskCardReferences:
    node_id = str(node.get("id") or "")
    from .workflow_asset_resolution import resolve_workflow_node_inputs
    input_snapshot = resolve_workflow_node_inputs(
        project_id,
        episode_id,
        {"nodeId": node_id},
        workflow=workflow,
    )
    asset_names = _video_task_card_asset_name_map_from_inputs(input_snapshot, project_id)
    input_snapshot = _video_task_card_named_input_snapshot(
        project_id, input_snapshot, asset_name_map=asset_names,
    )
    thumbnail_rows = _video_task_card_reference_thumbnails(
        project_id,
        episode_id,
        workflow,
        input_snapshot,
    )
    reference_video_thumbnails = _video_task_card_reference_video_thumbnails(
        project_id,
        episode_id,
        workflow,
        input_snapshot,
    )
    reference_thumbnails, asset_thumbnails = _video_task_card_split_thumbnails(thumbnail_rows)
    thumbnail_reference_ids: list[str] = []
    for row in reference_thumbnails:
        thumbnail_reference_ids = _append_unique_string(
            thumbnail_reference_ids,
            _video_task_card_thumbnail_media_reference_id(row),
        )
    reference_ids: list[str] = []
    for item in _video_task_card_reference_ids({"inputLinks": thumbnail_rows}, workflow):
        reference_ids = _append_unique_string(reference_ids, item)
    for item in thumbnail_reference_ids:
        reference_ids = _append_unique_string(reference_ids, item)
    asset_reference_media_ids: list[str] = []
    for row in asset_thumbnails:
        asset_reference_media_ids = _append_unique_string(
            asset_reference_media_ids,
            _video_task_card_thumbnail_media_reference_id(row),
        )
    current_asset_refs, asset_refs_resolved_by_links = _video_task_card_current_asset_refs(
        input_snapshot,
    )
    reference_manifest = _video_task_card_reference_manifest(
        project_id, node, input_snapshot,
        thumbnail_rows,
        reference_video_thumbnails,
    )
    reference_record_patch = {
        "referenceThumbnails": copy.deepcopy(reference_thumbnails),
        "assetThumbnails": copy.deepcopy(asset_thumbnails),
        "referenceVideoThumbnails": copy.deepcopy(reference_video_thumbnails),
        "referenceManifest": copy.deepcopy(reference_manifest),
        "referenceMediaIds": copy.deepcopy(reference_ids),
        "assetReferenceMediaIds": copy.deepcopy(asset_reference_media_ids),
        "assetRefs": copy.deepcopy(current_asset_refs),
        "assetRefsResolvedByInputLinks": asset_refs_resolved_by_links,
    }
    video_task_card_reference_patch = {
        "referenceMediaIds": copy.deepcopy(reference_ids),
        "assetReferenceMediaIds": copy.deepcopy(asset_reference_media_ids),
        "assetRefs": copy.deepcopy(current_asset_refs),
        "assetRefsResolvedByInputLinks": asset_refs_resolved_by_links,
        "referenceThumbnailCount": len(reference_thumbnails),
        "referenceVideoThumbnails": copy.deepcopy(reference_video_thumbnails),
        "assetThumbnailCount": len(asset_thumbnails),
    }
    return VideoTaskCardReferences(
        input_snapshot=input_snapshot,
        asset_names=asset_names,
        reference_thumbnails=reference_thumbnails,
        asset_thumbnails=asset_thumbnails,
        thumbnail_reference_ids=thumbnail_reference_ids,
        reference_ids=reference_ids,
        asset_reference_media_ids=asset_reference_media_ids,
        record_patch=reference_record_patch,
        card_patch=video_task_card_reference_patch,
    )
