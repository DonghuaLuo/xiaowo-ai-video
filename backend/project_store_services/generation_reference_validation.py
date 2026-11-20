# -*- coding: utf-8 -*-
"""生成前参考素材身份、可用性、计数和输入槽约束。"""
from __future__ import annotations

import copy
import urllib
from .video_reference_metadata import video_reference_usage
from .assets import (
    list_assets,
)
from .canvas_store_queries import read_canvas_reference_versions_by_ids_v4, read_card_results, read_episode_card_results
from .planning_contract import (
    _normalize_video_input_mode,
)
from .reference_utils import (
    dedupe_reference_tokens as _dedupe_reference_tokens,
    workflow_media_identity_values as _preflight_workflow_media_identity_values,
)
from .splitting_templates import (
    _string_list,
)
from .store_core import (
    ASSET_LIFECYCLE_ACTIVE,
)
from pathlib import (
    Path,
)
from typing import (
    Any,
)


_PREFLIGHT_REFERENCE_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".avif",
}


def _preflight_reference_identity_values(value: dict[str, Any] | None) -> set[str]:
    if not isinstance(value, dict):
        return set()
    keys = (
        "id",
        "nodeId",
        "node_id",
        "linkId",
        "link_id",
        "inputLinkId",
        "input_link_id",
        "sourceNodeId",
        "source_node_id",
        "rootAssetId",
        "assetId",
        "mediaVersionId",
        "media_version_id",
        "sourceVersionId",
        "source_version_id",
        "versionId",
        "version_id",
        "mediaId",
        "media_id",
        "relativePath",
        "relative_path",
        "file",
        "filePath",
        "file_path",
        "path",
    )
    return {
        str(value.get(key) or "").strip()
        for key in keys
        if str(value.get(key) or "").strip()
    }


def _preflight_reference_text_suffix(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    path_text = parsed.path if parsed.scheme in {"http", "https", "file"} else text
    path_text = path_text.split("?", 1)[0].split("#", 1)[0]
    return Path(path_text).suffix.lower()


def _preflight_reference_media_is_image(media: dict[str, Any] | None) -> bool:
    if not isinstance(media, dict):
        return False
    kind = str(
        media.get("kind")
        or media.get("type")
        or media.get("mediaType")
        or media.get("media_type")
        or ""
    ).strip().lower()
    if kind == "image" or kind.startswith("image/"):
        return True
    mime = str(media.get("mimeType") or media.get("mime_type") or media.get("mime") or "").strip().lower()
    if mime.startswith("image/"):
        return True
    for key in ("dataUrl", "pngDataUrl", "outputPngDataUrl", "storedPngDataUrl", "preview"):
        if str(media.get(key) or "").strip().startswith("data:image/"):
            return True
    for key in (
        "relativePath",
        "relative_path",
        "file",
        "filePath",
        "file_path",
        "path",
        "url",
        "originalName",
        "name",
    ):
        suffix = _preflight_reference_text_suffix(str(media.get(key) or ""))
        if suffix in _PREFLIGHT_REFERENCE_IMAGE_EXTENSIONS:
            return True
    return False


def _preflight_active_asset_media_candidate(item: dict[str, Any]) -> dict[str, Any] | None:
    versions = item.get("mediaVersions") if isinstance(item.get("mediaVersions"), list) else []
    active_id = str(item.get("activeMediaVersionId") or "").strip()
    selected = next(
        (
            version
            for version in versions
            if isinstance(version, dict) and active_id and str(version.get("id") or "") == active_id
        ),
        None,
    )
    if isinstance(selected, dict) and isinstance(selected.get("media"), dict):
        return selected["media"]
    return None


def _preflight_reference_count_key(
    reference_id: str,
    media: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    for source in (media, metadata):
        if not isinstance(source, dict):
            continue
        for key in ("mediaId", "id", "versionId"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return str(reference_id or "").strip()


def _preflight_reference_image_key_by_id(
    reference_id: str,
    versions: list[Any],
    assets: dict[str, Any],
    active_storyboard_version_ids: set[str] | None = None,
    workflow: dict[str, Any] | None = None,
    *,
    allow_asset_library_lookup: bool = True,
) -> str:
    reference_id = str(reference_id or "").strip()
    if not reference_id:
        return ""
    active_storyboard_version_ids = active_storyboard_version_ids or set()

    if isinstance(versions, list):
        for version in versions:
            if not isinstance(version, dict):
                continue
            version_id = str(version.get("id") or "").strip()
            if not version_id or version_id not in active_storyboard_version_ids:
                continue
            media = version.get("media") if isinstance(version.get("media"), dict) else {}
            identities = _preflight_reference_identity_values(version) | _preflight_reference_identity_values(media)
            if reference_id not in identities:
                continue
            if _preflight_reference_media_is_image(media) or str(version.get("preview") or "").startswith("data:image/"):
                return _preflight_reference_count_key(reference_id, media, version)

    source_workflow = workflow if isinstance(workflow, dict) else {}
    for node in source_workflow.get("nodes", []) if isinstance(source_workflow.get("nodes"), list) else []:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "").strip()
        if node_type not in {"asset.image", "media.external"}:
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        media = data.get("media") if isinstance(data.get("media"), dict) else data.get("storage")
        if not isinstance(media, dict):
            continue
        identities = _preflight_workflow_media_identity_values(node, data, media)
        if reference_id not in identities:
            continue
        if _preflight_reference_media_is_image(media):
            return _preflight_reference_count_key(
                reference_id,
                media,
                {"sourceNodeId": node.get("id") or node.get("nodeId"), "nodeType": node_type},
            )

    if not allow_asset_library_lookup:
        return ""

    for asset_type in ("characters", "creatures", "scenes", "props", "styles"):
        rows = assets.get(asset_type) if isinstance(assets, dict) else []
        if not isinstance(rows, list):
            continue
        for item in rows:
            if not isinstance(item, dict):
                continue
            media_candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
            active_media = _preflight_active_asset_media_candidate(item)
            if isinstance(active_media, dict):
                media_candidates.append(
                    (
                        active_media,
                        {
                            "assetId": item.get("id"),
                            "assetType": asset_type,
                            "versionId": item.get("activeMediaVersionId"),
                        },
                    )
                )
            item_matches = reference_id in _preflight_reference_identity_values(item)
            for media, metadata in media_candidates:
                identities = (
                    _preflight_reference_identity_values(media)
                    | _preflight_reference_identity_values(metadata)
                    | _preflight_reference_identity_values(media.get("metadata") if isinstance(media, dict) else None)
                )
                if not item_matches and reference_id not in identities:
                    continue
                if _preflight_reference_media_is_image(media):
                    return _preflight_reference_count_key(reference_id, media, metadata)
    return ""


def _preflight_resolved_reference_image_count(
    project_id: str,
    episode_id: str,
    reference_media_ids: list[str],
    *,
    workflow: dict[str, Any] | None = None,
    allow_asset_library_lookup: bool = True,
    input_links: list[dict[str, Any]] | None = None,
) -> int:
    from .workflow_projection import get_canvas_workflow_projection
    requested_ids = _dedupe_reference_tokens(reference_media_ids)
    if not requested_ids:
        return 0
    source_workflow = workflow if isinstance(workflow, dict) else {}
    workflow_reused = isinstance(workflow, dict)
    versions: list[Any] = []
    seen_version_keys: set[tuple[str, str]] = set()
    active_storyboard_version_ids: set[str] = set()
    active_storyboard_card_ids: set[str] = set()
    if workflow_reused:
        for node in source_workflow.get("nodes", []) if isinstance(source_workflow.get("nodes"), list) else []:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or node.get("nodeId") or "").strip()
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            version_id = str(
                data.get("activeVersionId")
                or data.get("activeMediaVersionId")
                or data.get("mediaVersionId")
                or ""
            ).strip()
            if version_id:
                active_storyboard_version_ids.add(version_id)
                if node_id:
                    active_storyboard_card_ids.add(node_id)
        for card_id in sorted(active_storyboard_card_ids):
            for version in read_card_results(project_id, episode_id, card_id):
                if not isinstance(version, dict):
                    continue
                key = (str(version.get("nodeId") or card_id), str(version.get("id") or ""))
                if key in seen_version_keys:
                    continue
                seen_version_keys.add(key)
                versions.append(version)
    else:
        versions = read_episode_card_results(project_id, episode_id)
        seen_version_keys.update(
            (str(version.get("nodeId") or ""), str(version.get("id") or ""))
            for version in versions
            if isinstance(version, dict)
        )
    assets = (
        list_assets("project", project_id, hydrate=False, lifecycle_status=ASSET_LIFECYCLE_ACTIVE)
        if allow_asset_library_lookup
        else {}
    )
    if not isinstance(assets, dict):
        assets = {}
    if not workflow_reused:
        try:
            source_workflow = get_canvas_workflow_projection(project_id, episode_id)
            for node in source_workflow.get("nodes", []) if isinstance(source_workflow.get("nodes"), list) else []:
                if not isinstance(node, dict):
                    continue
                data = node.get("data") if isinstance(node.get("data"), dict) else {}
                version_id = str(
                    data.get("activeVersionId")
                    or data.get("activeMediaVersionId")
                    or data.get("mediaVersionId")
                    or ""
                ).strip()
                if version_id:
                    active_storyboard_version_ids.add(version_id)
        except Exception:
            active_storyboard_version_ids = set()
    for version in read_canvas_reference_versions_by_ids_v4(project_id, episode_id, requested_ids):
        if not isinstance(version, dict):
            continue
        version_id = str(version.get("id") or "").strip()
        key = (str(version.get("nodeId") or ""), version_id)
        if key not in seen_version_keys:
            seen_version_keys.add(key)
            versions.append(version)
        if version_id:
            active_storyboard_version_ids.add(version_id)

    usages: dict[str, set[str]] = {}
    for link in input_links or []:
        if not isinstance(link, dict):
            continue
        source_id = str(link.get("sourceNodeId") or link.get("source_node_id") or "")
        key = _preflight_reference_image_key_by_id(
            source_id, versions, assets, active_storyboard_version_ids, source_workflow,
            allow_asset_library_lookup=allow_asset_library_lookup,
        )
        if key:
            usages.setdefault(key, set()).add(video_reference_usage(link))
    seen: set[tuple[str, str]] = set()
    for reference_id in requested_ids:
        key = _preflight_reference_image_key_by_id(
            reference_id,
            versions,
            assets,
            active_storyboard_version_ids,
            source_workflow,
            allow_asset_library_lookup=allow_asset_library_lookup,
        )
        if key:
            seen.update((key, usage) for usage in usages.get(key, {"reference_image"}))
    return len(seen)


WORKFLOW_NODE_SLOT_SCHEMA: dict[str, list[dict[str, Any]]] = {
    "image": [
        {"id": "custom_image", "label": "自定义图片", "required": False, "cardinality": "many"},
        {"id": "prompt", "label": "图片提示词", "required": True, "cardinality": "one"},
        {"id": "character_reference", "label": "角色参考", "required": False, "cardinality": "many"},
        {"id": "creature_reference", "label": "生物参考", "required": False, "cardinality": "many"},
        {"id": "scene_reference", "label": "场景参考", "required": False, "cardinality": "many"},
        {"id": "prop_reference", "label": "道具参考", "required": False, "cardinality": "many"},
        {"id": "storyboard_image", "label": "分镜图", "required": False, "cardinality": "many"},
    ],
    "video": [
        {"id": "custom_image", "label": "自定义图片", "required": False, "cardinality": "many"},
        {"id": "prompt", "label": "视频提示词", "required": True, "cardinality": "one"},
        {"id": "storyboard_image", "label": "分镜图", "required": False, "cardinality": "one"},
        {"id": "character_reference", "label": "角色图", "required": False, "cardinality": "many"},
        {"id": "creature_reference", "label": "生物图", "required": False, "cardinality": "many"},
        {"id": "scene_reference", "label": "场景图", "required": False, "cardinality": "many"},
        {"id": "prop_reference", "label": "道具图", "required": False, "cardinality": "many"},
    ],
}


_VIDEO_IMAGE_REFERENCE_SLOTS = (
    "custom_image",
    "frame_reference",
    "storyboard_image",
    "character_reference",
    "creature_reference",
    "scene_reference",
    "prop_reference",
    "visual_handoff_reference",
)


def _slot_rows(input_snapshot: dict[str, Any], slot: str) -> list[dict[str, Any]]:
    grouped = input_snapshot.get("groupedBySlot") if isinstance(input_snapshot.get("groupedBySlot"), dict) else {}
    rows = grouped.get(slot)
    return [copy.deepcopy(item) for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


def _snapshot_row_has_media_reference(row: dict[str, Any]) -> bool:
    media = row.get("media") if isinstance(row.get("media"), dict) else {}
    for container in (row, media):
        for key in (
            "mediaId",
            "media_id",
            "path",
            "filePath",
            "file_path",
            "url",
            "preview",
            "previewUrl",
            "thumbnail",
            "thumbnailUrl",
            "dataUrl",
        ):
            if str(container.get(key) or "").strip():
                return True
    return False


def _has_slot_rows(input_snapshot: dict[str, Any], slots: list[str]) -> bool:
    return any(_slot_rows(input_snapshot, slot) for slot in slots)


def _active_reference_node_ids(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_id: str,
) -> list[str]:
    from .workflow_input_resolution import workflow_storyboard_reference_node_ids
    try:
        node_ids = workflow_storyboard_reference_node_ids(workflow, node_id=node_id)
    except Exception:
        node_ids = []
    try:
        from .workflow_input_resolution import workflow_current_media_version_has_media
    except Exception:
        workflow_current_media_version_has_media = None
    result: list[str] = []
    for reference_node_id in node_ids:
        if (
            workflow_current_media_version_has_media
            and workflow_current_media_version_has_media(
                project_id,
                episode_id,
                workflow,
                reference_node_id,
            )
            and reference_node_id not in result
        ):
            result.append(reference_node_id)
    return result


def _input_reference_count(
    input_snapshot: dict[str, Any],
    active_reference_node_ids: list[str],
    *,
    slots: list[str] | None = None,
) -> int:
    slots = slots or ["storyboard_image"]
    reference_ids: set[str] = set()
    if not _has_slot_rows(input_snapshot, slots) and isinstance(input_snapshot.get("referenceMediaIds"), list):
        reference_ids = {
            str(item or "").strip()
            for item in input_snapshot.get("referenceMediaIds", [])
            if str(item or "").strip()
        }
    count = len(reference_ids) + len(active_reference_node_ids)
    for slot in slots:
        for row in _slot_rows(input_snapshot, slot):
            if _snapshot_row_has_media_reference(row):
                count += 1
    return count


def _video_required_slot_status(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_id: str,
    strategy: str,
    resolved_config: dict[str, Any],
    input_snapshot: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    blocking: list[str] = []
    warnings: list[str] = []
    required_slots: list[dict[str, Any]] = []
    active_reference_nodes = _active_reference_node_ids(
        project_id,
        episode_id,
        workflow,
        node_id,
    )
    reference_mode = str(
        resolved_config.get("inputMode")
        or resolved_config.get("referenceMode")
        or strategy
        or ""
    ).strip()
    mode = reference_mode or strategy
    normalized_mode = _normalize_video_input_mode(mode, strategy)

    def add_slot(slot: str, label: str, satisfied: bool, reason: str) -> None:
        row = {
            "slot": slot,
            "label": label,
            "required": True,
            "satisfied": bool(satisfied),
            "reason": "" if satisfied else reason,
        }
        required_slots.append(row)
        if not satisfied:
            blocking.append(reason)

    has_image_reference = (
        _input_reference_count(
            input_snapshot,
            active_reference_nodes,
            slots=list(_VIDEO_IMAGE_REFERENCE_SLOTS),
        )
        > 0
    )
    if normalized_mode == "character_replace":
        from utils.video_task_types import CHARACTER_REPLACE_IMAGE_SLOTS, CHARACTER_REPLACE_INPUT_SLOTS
        image_rows = [row for slot in CHARACTER_REPLACE_IMAGE_SLOTS for row in _slot_rows(input_snapshot, slot)]
        video_rows = _slot_rows(input_snapshot, "reference_video")
        add_slot("character_reference", "替换角色图", bool(image_rows) and all(_snapshot_row_has_media_reference(row) for row in image_rows),
                 "角色替换需要至少一张当前可用的角色图")
        add_slot("reference_video", "源视频", len(video_rows) == 1 and _snapshot_row_has_media_reference(video_rows[0]),
                 "角色替换需要且只能关联一段当前可用的源视频")
        if any(rows and slot not in CHARACTER_REPLACE_INPUT_SLOTS for slot, rows in (input_snapshot.get("groupedBySlot") or {}).items()):
            blocking.append("角色替换仅支持源视频与角色图，请移除其他用途的素材")
    elif normalized_mode == "native_keyframe":
        has_first_frame = any(
            row.get("frameRole", "first_frame") == "first_frame"
            and row.get("useNativeFrame") is not False
            and _snapshot_row_has_media_reference(row)
            for row in _slot_rows(input_snapshot, "frame_reference")
        )
        add_slot("frame_reference", "原生首帧", has_first_frame, "缺少原生首帧输入，请先关联首帧图片")
    elif normalized_mode == "image_reference":
        required_slots.append({"slot": "image_reference", "label": "图片资产参考",
                               "required": False, "satisfied": has_image_reference, "reason": ""})
    elif normalized_mode == "text_to_video_draft":
        warnings.append("当前为纯文本草稿模式，建议后续补充故事版分镜图以保证一致性")

    return required_slots, blocking, warnings


def _video_storyboard_sheet_transport_blocker(
    strategy: str,
    resolved_config: dict[str, Any],
    input_snapshot: dict[str, Any],
) -> str:
    if strategy != "storyboard_multi_shot":
        return ""
    capabilities = resolved_config.get("modelCapabilities") if isinstance(resolved_config.get("modelCapabilities"), dict) else {}
    supports = capabilities.get("supports") if isinstance(capabilities.get("supports"), dict) else {}
    if supports.get("storyboardReferenceImage"):
        return ""
    if supports.get("multiReferenceVideo"):
        return ""
    storyboard_rows = _slot_rows(input_snapshot, "storyboard_image")
    storyboard_sheet_rows = [
        row
        for row in storyboard_rows
        if str(row.get("sourceNodeType") or row.get("source_node_type") or "").strip() == "storyboard.image"
        and _snapshot_row_has_media_reference(row)
    ]
    if not storyboard_sheet_rows:
        return ""
    model_id = str(resolved_config.get("modelId") or resolved_config.get("model_id") or "").strip()
    return (
        f"模型 {model_id or '当前视频模型'} 不支持把整页分镜图作为参考图传输，"
        "继续生成会退化成纯文本视频。请切换支持故事版参考图的模型，"
        "或更换支持故事版参考图输入的视频模型后再生成视频。"
    )
