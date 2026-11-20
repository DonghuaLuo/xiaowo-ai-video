# -*- coding: utf-8 -*-
"""全局/项目资产管理、资产媒体版本和资产图生成。"""

from __future__ import annotations

from .image_prompt_guidance import uses_original_image_reference
from .provider_models import validate_image_model_inputs

import base64
import copy
import hashlib
import json
import random
import re
import shutil
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from utils.generation_requests import run_cancellable_model_request

from utils.agent_context import (
    AGENT_CONTEXT_MESSAGE_TEXT_LIMIT,
    AGENT_CONTEXT_RECENT_WINDOW,
    AGENT_CONTEXT_SUMMARY_CHARS,
    build_agent_conversation_context,
)
from utils import agent_sdk_runtime
from utils.agent_session_service import AgentSessionService
from utils.aspect_size import (
    IMAGE_TIER_SHORT_EDGE,
    VIDEO_TIER_SHORT_EDGE,
    aspect_size,
    image_default_aspect_ratio,
    image_default_resolution,
    parse_aspect_ratio,
    resolution_to_short_edge,
)
from utils.image_pipeline import (
    convert_image_bytes_to_png,
    data_url_from_bytes,
    image_bytes_metadata,
    prepare_provider_image_bytes,
    prepare_provider_image_data_uri,
    save_project_image,
    save_provider_output_image,
)
from utils.image_resolution_schema import (
    image_resolution_actual_report,
    image_resolution_request_plan,
    image_resolution_schema_for_model,
    normalize_image_resolution_for_schema,
    resolve_image_aspect_ratio_for_model,
)
from utils.media_backends import (
    RequestPreparedCallback,
    cancel_video_media_job,
    endpoint_supports_media_generation,
    infer_model_endpoint,
    media_endpoint_type,
    normalize_media_endpoint,
    generate_image_media,
    generate_video_media,
    poll_video_media_job,
    provider_supports_media_generation,
    submit_video_media_job,
)

from .reference_utils import (
    SHORT_ASSET_ID_PREFIX_BY_TYPE as _SHORT_ASSET_ID_PREFIX_BY_TYPE,
    asset_ref_canonical_tokens as _shared_asset_ref_canonical_tokens,
    asset_row_ids as _asset_row_ids,
    next_short_asset_id as _next_short_asset_id,
)
from .model_provider_config import (
    _api_model_name,
    _configured_media_model,
    _provider_base_url,
)
from .provider_reference_media import (
    _provider_reference_image_from_media,
)
from .image_prompt_guidance import (
    append_image_landscape_retry_instruction,
    append_image_request_prompt_instruction,
    image_metadata_needs_landscape_retry,
    image_request_size_label,
)
from .project_management import get_effective_config
from .canvas_store_queries import episode_canvas_exists, read_canvas_workflow_projection_v4

from .catalogs import ACCENTS
from .catalogs import ASSET_TYPES
from .catalogs import DEFAULT_ASSETS
from .catalogs import GENERAL_STYLE_TEMPLATE_ID
from .catalogs import GENERAL_VISUAL_TYPE_PROMPTS
from .catalogs import GENERAL_VISUAL_TYPE_TAGS
from .catalogs import GLOBAL_ASSETS_PATH
from .catalogs import _join_prompt_blocks
from .catalogs import _prompt_labeled_block
from .catalogs import _strip_style_theme_visual_overlap_text
from .catalogs import _style_phase_visual_prompt_block
from .catalogs import _style_phase_visual_prompt_from_config
from .catalogs import _style_theme_visual_prompt_block
from .catalogs import _style_theme_visual_prompt_from_config
from .runtime_state import _ASSET_IMAGE_TASK_CANCEL_FLAGS
from .runtime_state import _ASSET_IMAGE_TASK_THREADS
from .runtime_state import _LOCK
from .store_core import ASSET_LIFECYCLE_ACTIVE
from .store_core import ASSET_LIFECYCLE_ALL
from .store_core import _JSON_WRITE_LOCK
from .store_core import _assert_explicit_delete_all_confirmed
from .store_core import _asset_is_offline
from .store_core import _asset_lifecycle_matches
from .store_core import _asset_lifecycle_patch_value
from .store_core import _emit_agent_event
from .store_core import _filter_asset_store_by_lifecycle
from .store_core import _normalize_asset_lifecycle_status
from .store_core import _normalize_asset_type_key
from .store_core import _now
from .store_core import _read_json
from .store_core import _set_asset_lifecycle_status
from .store_core import _truthy_confirmation
from .store_core import _write_json
from .store_core import ensure_store

def list_assets(
    asset_scope: str = "global",
    project_id: str | None = None,
    *,
    hydrate: bool = True,
    include_source_metadata: bool = True,
    asset_type: str | None = None,
    lifecycle_status: str | None = None,
    source_coverage: dict[str, Any] | None = None,
    persist_normalization: bool = True,
) -> dict[str, Any]:
    from .agent_sessions import _hydrate_assets_for_ui
    from .agent_sessions import _project_dir
    ensure_store()
    path = GLOBAL_ASSETS_PATH if asset_scope == "global" or not project_id else _project_dir(project_id) / "assets" / "assets.json"
    data = _read_json(path, DEFAULT_ASSETS)
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULT_ASSETS)
    project_asset_scope = asset_scope != "global" and bool(project_id)
    selected_asset_type = _normalize_asset_type_key(asset_type)
    asset_types = (selected_asset_type,) if selected_asset_type else ASSET_TYPES
    source_order = _asset_source_order_for_project(project_id) if project_asset_scope else None
    before_snapshot = (
        {selected_asset_type: data.get(selected_asset_type)}
        if selected_asset_type
        else data
    )
    before = json.dumps(before_snapshot, ensure_ascii=False, sort_keys=True)
    for current_asset_type in asset_types:
        rows = data.get(current_asset_type)
        if not isinstance(rows, list):
            data[current_asset_type] = []
            continue
        for item in rows:
            if isinstance(item, dict):
                if project_asset_scope:
                    _ensure_asset_media_versions(item)
                    if current_asset_type not in {"characters", "creatures"}:
                        item.pop("voiceReferenceAudio", None)
                        item.pop("voice_reference_audio", None)
                    _normalize_asset_item_for_storage(project_id, item)
                    _ensure_asset_design_prompt_for_storage(current_asset_type, item)
                else:
                    _normalize_global_asset_item_for_storage(current_asset_type, item)
        if project_asset_scope and current_asset_type in {"characters", "creatures", "scenes", "props"}:
            _sort_asset_rows_by_source_order(rows, source_order)
    after_snapshot = (
        {selected_asset_type: data.get(selected_asset_type)}
        if selected_asset_type
        else data
    )
    after = json.dumps(after_snapshot, ensure_ascii=False, sort_keys=True)
    if after != before and persist_normalization:
        _write_json(path, data)
    response_data = _filter_asset_store_by_lifecycle(data, lifecycle_status)
    if project_asset_scope and hydrate:
        return _hydrate_assets_for_ui(
            project_id,
            response_data,
            include_source_metadata=include_source_metadata,
            asset_type=selected_asset_type,
            source_coverage=source_coverage,
        )
    if selected_asset_type:
        filtered = copy.deepcopy(DEFAULT_ASSETS)
        rows = response_data.get(selected_asset_type)
        filtered[selected_asset_type] = copy.deepcopy(rows if isinstance(rows, list) else [])
        return filtered
    return response_data


def _asset_source_refs_for_order(row: dict[str, Any]) -> list[dict[str, Any]]:
    refs = row.get("sourceRefs")
    if isinstance(refs, dict):
        return [refs]
    if isinstance(refs, list):
        return [item for item in refs if isinstance(item, dict)]
    return []


def _asset_source_order_for_project(project_id: str | None) -> dict[str, int]:
    from .agent_sessions import _project_dir
    if not project_id:
        return {}
    rows = _read_json(_project_dir(project_id) / "sources" / "sources.json", [])
    if not isinstance(rows, list):
        return {}
    source_order: dict[str, int] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        source_id = str(row.get("id") or row.get("sourceId") or "").strip()
        if source_id and source_id not in source_order:
            source_order[source_id] = index
    return source_order


def _asset_source_ref_start(ref: dict[str, Any]) -> int | None:
    start_value = ref.get("absoluteStart")
    try:
        return int(start_value)
    except (TypeError, ValueError):
        return None


def _asset_source_ref_order_key(
    ref: dict[str, Any],
    source_order: dict[str, int] | None = None,
) -> tuple[int, int, int] | None:
    start = _asset_source_ref_start(ref)
    if start is None:
        return None
    if not source_order:
        return (0, 0, start)
    source_id = str(ref.get("sourceId") or "").strip()
    if source_id in source_order:
        return (0, source_order[source_id], start)
    if not source_id and len(source_order) == 1:
        return (0, next(iter(source_order.values())), start)
    if source_id:
        return (1, 0, start)
    return (2, 0, start)


def _asset_first_source_order_key(
    row: dict[str, Any],
    source_order: dict[str, int] | None = None,
) -> tuple[int, int, int] | None:
    keys = [
        key
        for key in (
            _asset_source_ref_order_key(ref, source_order)
            for ref in _asset_source_refs_for_order(row)
        )
        if key is not None
    ]
    return min(keys) if keys else None


def _asset_first_source_start(row: dict[str, Any]) -> int | None:
    first_key = _asset_first_source_order_key(row)
    return first_key[2] if first_key else None


def _sort_asset_rows_by_source_order(
    rows: list[Any],
    source_order: dict[str, int] | None = None,
) -> bool:
    decorated: list[tuple[int, int, int, int, Any]] = []
    has_source_order = False
    for index, row in enumerate(rows):
        first_key = _asset_first_source_order_key(row, source_order) if isinstance(row, dict) else None
        if first_key is None:
            decorated.append((3, 0, 0, index, row))
            continue
        has_source_order = True
        decorated.append((*first_key, index, row))
    if not has_source_order:
        return False
    sorted_rows = [item[4] for item in sorted(decorated)]
    if sorted_rows == rows:
        return False
    rows[:] = sorted_rows
    return True


def _normalize_global_asset_item_for_storage(asset_type: str, item: dict[str, Any]) -> None:
    from .media_files import _normalize_global_media_asset
    from .media_files import _normalize_global_voice_reference_audio
    if isinstance(item.get("media"), dict):
        item["media"] = _normalize_global_media_asset(asset_type, item.get("media"))
    item.pop("referenceMedia", None)
    item.pop("referenceMediaRole", None)
    item.pop("mediaVersions", None)
    item.pop("activeMediaVersionId", None)
    item.pop("version", None)
    if asset_type not in {"characters", "creatures"}:
        item.pop("voiceStyle", None)
        item.pop("canSpeak", None)
    elif asset_type == "creatures":
        voice_style = str(item.get("voiceStyle") or item.get("voice_style") or "").strip()
        item["canSpeak"] = bool(voice_style)
        if voice_style:
            item["voiceStyle"] = voice_style
        else:
            item.pop("voiceStyle", None)
    item.pop("tag", None)
    item.pop("stateTag", None)
    item.pop("stateTags", None)
    voice_reference_audio = item.get("voiceReferenceAudio") or item.get("voice_reference_audio")
    if asset_type in {"characters", "creatures"} and isinstance(voice_reference_audio, dict):
        item["voiceReferenceAudio"] = _normalize_global_voice_reference_audio(asset_type, voice_reference_audio)
    else:
        item.pop("voiceReferenceAudio", None)
    item.pop("voice_reference_audio", None)


def _normalize_asset_state_tags(value: Any) -> list[str]:
    rows = value if isinstance(value, list) else [value] if value not in (None, "") else []
    result: list[str] = []
    for row in rows:
        text = str(row or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _apply_asset_version_state_patch(item: dict[str, Any], payload: dict[str, Any]) -> None:
    state_tag = str(payload.get("stateTag") or payload.get("state_tag") or "").strip()
    state_tags = _normalize_asset_state_tags(payload.get("stateTags") or payload.get("state_tags"))
    if state_tag:
        item["stateTag"] = state_tag
    elif "stateTag" in payload or "state_tag" in payload:
        item.pop("stateTag", None)
    if state_tags:
        item["stateTags"] = state_tags
        if not item.get("stateTag"):
            item["stateTag"] = state_tags[0]
    elif "stateTags" in payload or "state_tags" in payload:
        item.pop("stateTags", None)


def _normalize_media_asset(project_id: str | None, media: Any) -> dict[str, Any] | None:
    from .media_files import _copy_local_project_image_media_file
    from .media_files import _image_media_from_file_info
    from .projects import _is_path_within
    from .media_files import _local_image_source_from_media
    from .agent_sessions import _media_ref_for_storage
    from .agent_sessions import _mime_from_image_suffix
    from .agent_sessions import _project_dir
    from .agent_sessions import _project_file_from_ref
    if not isinstance(media, dict):
        return None
    result = copy.deepcopy(media)
    result["kind"] = result.get("kind") or "image"
    png_data_url = (
        result.get("outputPngDataUrl")
        or result.get("pngDataUrl")
        or result.get("preview")
        or result.get("dataUrl")
    )
    if not (isinstance(png_data_url, str) and png_data_url.startswith("data:image/")):
        png_data_url = None
    existing_file = _project_file_from_ref(project_id, result) if project_id else None
    if project_id and result.get("kind") == "image" and existing_file and existing_file.is_file():
        resolved_existing = existing_file.resolve()
        project_assets_dir = (_project_dir(project_id) / "assets").resolve()
        if not _is_path_within(resolved_existing, project_assets_dir):
            media_id = str(result.get("id") or f"media-{uuid.uuid4().hex[:10]}")
            stored = _copy_local_project_image_media_file(
                project_id,
                resolved_existing,
                media_id=media_id,
                subdir="media",
                original_name=str(
                    result.get("originalName") or result.get("name") or resolved_existing.name
                ),
                source_mime=str(
                    result.get("mimeType")
                    or result.get("mime_type")
                    or _mime_from_image_suffix(resolved_existing)
                ),
            )
            result.update(stored)
            existing_file = Path(str(stored.get("path") or resolved_existing))
    if result.get("kind") == "image" and png_data_url and not (existing_file and existing_file.is_file()):
        try:
            media_id = str(result.get("id") or f"media-{uuid.uuid4().hex[:10]}")
            normalized = _image_media_from_file_info(
                project_id,
                {
                    **result,
                    "id": media_id,
                    "name": result.get("originalName") or result.get("name") or "media.png",
                    "dataUrl": str(png_data_url),
                },
                media_id=media_id,
                subdir="media",
            )
            result.update(normalized)
        except Exception as exc:
            if project_id:
                raise ValueError(f"图片 PNG 落盘失败：{exc}") from exc
            result["pngFileError"] = f"图片 PNG 落盘失败，已保留临时预览：{exc}"
            result["pngDataUrl"] = png_data_url
            result["outputPngDataUrl"] = png_data_url
            result["mimeType"] = "image/png"
    elif project_id and result.get("kind") == "image" and not (existing_file and existing_file.is_file()):
        local_source = _local_image_source_from_media(result)
        if local_source:
            path, mime = local_source
            media_id = str(result.get("id") or f"media-{uuid.uuid4().hex[:10]}")
            stored = _copy_local_project_image_media_file(
                project_id,
                path,
                media_id=media_id,
                subdir="media",
                original_name=str(result.get("originalName") or result.get("name") or path.name),
                source_mime=mime,
            )
            result.update(stored)
    result.pop("apiJpegDataUrl", None)
    result.pop("api_jpeg_data_url", None)
    result.pop("apiTransport", None)
    if project_id and result.get("kind") == "image":
        stored_path = _project_file_from_ref(project_id, result)
        project_assets_dir = (_project_dir(project_id) / "assets").resolve()
        if stored_path and (
            not stored_path.is_file()
            or not _is_path_within(stored_path.resolve(), project_assets_dir)
        ):
            raise ValueError("项目资产图片必须先保存到项目资产目录")
        # Provider/plugin URLs are already durable references and do not map
        # to a local path that this process can validate or delete.
        if not stored_path and not any(
            str(result.get(key) or "").strip()
            for key in ("url", "preview", "thumbnail", "dataUrl", "pngDataUrl")
        ):
            raise ValueError("项目资产图片缺少可持久化的本地文件或媒体地址")
        return _media_ref_for_storage(result)
    return result


def _normalize_asset_item_for_storage(project_id: str | None, item: dict[str, Any]) -> None:
    if not project_id:
        return
    item.pop("stateTag", None)
    item.pop("stateTags", None)
    for key in ("media", "referenceMedia"):
        if isinstance(item.get(key), dict):
            normalized = _normalize_media_asset(project_id, item.get(key))
            item[key] = normalized if isinstance(normalized, dict) else None
    voice_reference_audio = item.get("voiceReferenceAudio") or item.get("voice_reference_audio")
    if isinstance(voice_reference_audio, dict) and project_id:
        from .media_files import _normalize_voice_reference_audio

        item["voiceReferenceAudio"] = _normalize_voice_reference_audio(
            project_id,
            voice_reference_audio,
        )
    item.pop("voice_reference_audio", None)
    versions = item.get("mediaVersions")
    if isinstance(versions, list):
        normalized_versions: list[dict[str, Any]] = []
        for version in versions:
            if not isinstance(version, dict):
                continue
            if isinstance(version.get("media"), dict):
                normalized = _normalize_media_asset(project_id, version.get("media"))
                version["media"] = normalized if isinstance(normalized, dict) else None
            normalized_versions.append(version)
        item["mediaVersions"] = normalized_versions


def _asset_store_path(asset_scope: str = "global", project_id: str | None = None) -> Path:
    from .agent_sessions import _project_dir
    return GLOBAL_ASSETS_PATH if asset_scope == "global" or not project_id else _project_dir(project_id) / "assets" / "assets.json"


def _asset_version_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    if "desc" in item:
        snapshot["desc"] = str(item.get("desc") or "")
    if "voiceStyle" in item:
        snapshot["voiceStyle"] = str(item.get("voiceStyle") or "")
    if "canSpeak" in item:
        snapshot["canSpeak"] = bool(item.get("canSpeak"))
    return snapshot


def _asset_version_state_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return _asset_version_snapshot(before) != _asset_version_snapshot(after)


def _asset_media_version_created_at(value: Any = None) -> str:
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S")

    text = str(value or "").strip()
    if not text:
        return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _asset_media_version(
    media: dict[str, Any] | None,
    title: str | None = None,
    *,
    snapshot: dict[str, Any] | None = None,
    allow_empty: bool = False,
) -> dict[str, Any] | None:
    if not isinstance(media, dict) and not allow_empty:
        return None
    version_id = str(
        (media.get("versionId") if isinstance(media, dict) else "")
        or f"media-version-{uuid.uuid4().hex[:8]}"
    )
    version: dict[str, Any] = {
        "id": version_id,
        "title": title
        or str((media or {}).get("originalName") or "设计图版本"),
        "createdAt": _asset_media_version_created_at(),
        "status": "ready",
    }
    version["media"] = media if isinstance(media, dict) else None
    if isinstance(snapshot, dict):
        version.update(_asset_version_snapshot(snapshot))
    return version


def _asset_media_version_from_payload(
    project_id: str | None,
    value: Any,
    *,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    media = value.get("media") if isinstance(value.get("media"), dict) else None
    normalized_media = _normalize_media_asset(project_id, media) if project_id else media
    version = _asset_media_version(
        normalized_media if isinstance(normalized_media, dict) else None,
        str(value.get("title") or value.get("name") or ""),
        snapshot=snapshot,
        allow_empty=True,
    )
    if not version:
        return None
    for key in (
        "id",
        "title",
        "status",
        "summary",
        "source",
        "payload",
        "model",
        "provider",
        "generationError",
        "generationDebug",
        "preview",
    ):
        if key in value and value.get(key) is not None:
            version[key] = copy.deepcopy(value.get(key))
    if value.get("createdAt") is not None:
        version["createdAt"] = _asset_media_version_created_at(value.get("createdAt"))
    if isinstance(normalized_media, dict):
        version["media"] = normalized_media
    return version


def _ensure_asset_media_versions(item: dict[str, Any]) -> list[dict[str, Any]]:
    versions = item.get("mediaVersions")
    if not isinstance(versions, list):
        versions = []
    versions = [version for version in versions if isinstance(version, dict)]
    previous_active_id = str(item.get("activeMediaVersionId") or "")
    seen_ids: dict[str, int] = {}
    active_candidates: list[str] = []
    for index, version in enumerate(versions):
        raw_id = str(version.get("id") or f"media-version-{index + 1}")
        seen_ids[raw_id] = seen_ids.get(raw_id, 0) + 1
        if seen_ids[raw_id] > 1:
            version["id"] = f"{raw_id}-v{index + 1}-{uuid.uuid4().hex[:4]}"
        else:
            version["id"] = raw_id
        if raw_id == previous_active_id:
            active_candidates.append(str(version["id"]))
    media = item.get("media")
    if isinstance(media, dict) and not versions:
        first = _asset_media_version(media, "初始设计图", snapshot=item)
        if first:
            versions = [first]
            item["activeMediaVersionId"] = first["id"]
    if active_candidates:
        item["activeMediaVersionId"] = active_candidates[-1]
    item["mediaVersions"] = versions
    return versions


def _asset_payload_has_design_prompt(value: dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    prompts = value.get("prompts")
    if isinstance(prompts, dict) and any(key in prompts for key in _ASSET_IMAGE_PROMPT_KEYS):
        return True
    return any(key in value for key in _ASSET_IMAGE_PROMPT_KEYS)


def _asset_name_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _find_asset_index_by_name(rows: Any, name: Any, lifecycle_status: Any = None) -> int | None:
    if not isinstance(rows, list):
        return None
    target = _asset_name_key(name)
    if not target:
        return None
    for index, item in enumerate(rows):
        if (
            isinstance(item, dict)
            and _asset_lifecycle_matches(item, lifecycle_status)
            and _asset_name_key(item.get("name")) == target
        ):
            return index
    return None


def _project_asset_media_paths(project_id: str, item: Any) -> set[Path]:
    from .projects import _is_path_within
    from .agent_sessions import _project_dir
    from .agent_sessions import _project_file_from_ref
    if not isinstance(item, dict):
        return set()
    project_assets_dir = (_project_dir(project_id) / "assets").resolve()
    paths: set[Path] = set()

    def add_media(media: Any) -> None:
        if not isinstance(media, dict):
            return
        path = _project_file_from_ref(project_id, media)
        if not path:
            return
        try:
            resolved = path.resolve()
        except OSError:
            return
        if _is_path_within(resolved, project_assets_dir):
            paths.add(resolved)

    add_media(item.get("media"))
    add_media(item.get("referenceMedia"))
    add_media(item.get("voiceReferenceAudio") or item.get("voice_reference_audio"))
    versions = item.get("mediaVersions")
    if isinstance(versions, list):
        for version in versions:
            if isinstance(version, dict):
                add_media(version.get("media"))
    return paths


def _delete_project_asset_media_files(
    project_id: str,
    item: Any,
    *,
    keep: set[Path] | None = None,
    keep_voice_reference: bool = False,
) -> None:
    from .media_files import _project_voice_reference_audio_path

    keep_paths = {path.resolve() for path in (keep or set())}
    if keep_voice_reference and isinstance(item, dict):
        voice_path = _project_voice_reference_audio_path(
            project_id, item.get("voiceReferenceAudio") or item.get("voice_reference_audio")
        )
        if voice_path:
            keep_paths.add(voice_path)
    for path in _project_asset_media_paths(project_id, item):
        if path in keep_paths:
            continue
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except OSError:
            continue


def _delete_asset_voice_reference_audio_if_unreferenced(
    asset_scope: str,
    project_id: str | None,
    media: Any,
) -> None:
    from .media_files import _delete_global_voice_reference_audio_if_unreferenced
    from .media_files import _delete_project_voice_reference_audio_if_unreferenced

    if asset_scope != "global" and project_id:
        _delete_project_voice_reference_audio_if_unreferenced(project_id, media)
    else:
        _delete_global_voice_reference_audio_if_unreferenced(media)


def _dedupe_project_asset_ref_tokens(tokens: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        text = str(token or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped


def _project_asset_ref_canonical_tokens(value: Any) -> list[str]:
    return _shared_asset_ref_canonical_tokens(value)


def _collect_plan_asset_refs(document: Any) -> dict[str, list[str]]:
    from .video_task_card_references import _ASSET_REF_COLLECTIONS
    from .asset_reference_scope import _asset_refs_from_plan_item
    refs: dict[str, list[str]] = {key: [] for key in _ASSET_REF_COLLECTIONS}
    if not isinstance(document, dict):
        return {}

    def add(value: Any) -> None:
        if not isinstance(value, dict):
            return
        for key in _ASSET_REF_COLLECTIONS:
            refs[key].extend(_project_asset_ref_canonical_tokens(value.get(key)))

    for collection_name in ("segments", "shots", "panels"):
        rows = document.get(collection_name)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                add(_asset_refs_from_plan_item(row))

    compacted: dict[str, list[str]] = {}
    for key, tokens in refs.items():
        deduped = _dedupe_project_asset_ref_tokens(tokens)
        if deduped:
            compacted[key] = deduped
    return compacted


def _project_storyboard_asset_refs(project_id: str) -> dict[str, set[str]]:
    from .video_task_card_references import _ASSET_REF_COLLECTIONS
    from .asset_reference_scope import _collect_workflow_asset_refs
    from .agent_sessions import _project_dir
    from .agent_sessions import _project_meta_path
    refs: dict[str, set[str]] = {key: set() for key in _ASSET_REF_COLLECTIONS}
    project_root = _project_dir(project_id)
    episode_ids: set[str] = set()
    meta = _read_json(_project_meta_path(project_id), {})
    episodes = meta.get("episodes") if isinstance(meta, dict) else []
    if isinstance(episodes, list):
        for episode in episodes:
            if isinstance(episode, dict):
                episode_id = str(episode.get("id") or episode.get("episodeId") or "").strip()
                if episode_id:
                    episode_ids.add(episode_id)
    episodes_dir = project_root / "episodes"
    if episodes_dir.exists():
        for path in episodes_dir.iterdir():
            if path.is_dir():
                episode_ids.add(path.name)

    def merge(rows: dict[str, list[str]]) -> None:
        for key, tokens in rows.items():
            if key not in refs:
                continue
            refs[key].update(str(token).strip().casefold() for token in tokens if str(token).strip())

    for episode_id in episode_ids:
        episode_dir = episodes_dir / episode_id
        shot_plan_path = episode_dir / "work_chain_plan.json"
        if shot_plan_path.exists():
            merge(_collect_plan_asset_refs(_read_json(shot_plan_path, {})))
        if episode_canvas_exists(project_id, episode_id):
            workflow = read_canvas_workflow_projection_v4(project_id, episode_id)
            if isinstance(workflow, dict):
                merge(_collect_workflow_asset_refs(workflow, project_id=project_id))
    return refs


def _project_asset_is_referenced(project_id: str, asset_type: str, item: dict[str, Any]) -> bool:
    from .video_task_card_references import _ASSET_REF_COLLECTIONS
    if asset_type not in _ASSET_REF_COLLECTIONS:
        return False
    target_id = str(item.get("id") or "").strip().casefold()
    if not target_id:
        return False
    referenced_tokens = _project_storyboard_asset_refs(project_id).get(asset_type, set())
    return target_id in referenced_tokens


def _apply_asset_design_prompt_patch(item: dict[str, Any], patch: dict[str, Any]) -> None:
    if not _asset_payload_has_design_prompt(patch):
        return
    design_prompt = _asset_design_prompt_from_asset(patch)
    prompts = copy.deepcopy(item.get("prompts")) if isinstance(item.get("prompts"), dict) else {}
    if design_prompt:
        prompts["assetImagePrompt"] = design_prompt
    else:
        prompts.pop("assetImagePrompt", None)
    if prompts:
        item["prompts"] = prompts
    else:
        item.pop("prompts", None)


def _preserve_asset_grouping_metadata(item: dict[str, Any], previous: dict[str, Any] | None) -> None:
    if not isinstance(previous, dict):
        return
    for key in ("assetRangeId", "assetRangeIds", "sourceRefs"):
        if key in previous:
            item[key] = copy.deepcopy(previous[key])


def _asset_write_changed_resources(asset_type: str) -> list[str]:
    return ["assets", asset_type]


def _create_asset_unlocked(
    asset_type: str,
    asset: dict[str, Any],
    asset_scope: str = "global",
    project_id: str | None = None,
) -> dict[str, Any]:
    from .media_files import _delete_global_asset_media_file
    from .media_files import _global_asset_media_path
    from .agent_sessions import _hydrate_asset_row_for_ui
    from .media_files import _normalize_global_media_asset
    from .projects import _touch_project_meta
    assets = list_assets(asset_scope, project_id, hydrate=False)
    if asset_type not in assets:
        raise ValueError("资产类型无效")
    name = str(asset.get("name") or asset.get("title") or "").strip()
    if not name:
        raise ValueError(f"{_asset_type_label(asset_type)}名称不能为空")
    overwrite = bool(asset.get("overwrite"))
    project_asset_scope = asset_scope != "global" and bool(project_id)
    duplicate_index = _find_asset_index_by_name(
        assets.get(asset_type),
        name,
        ASSET_LIFECYCLE_ACTIVE if project_asset_scope and asset_type in {"characters", "creatures", "scenes", "props"} else ASSET_LIFECYCLE_ALL,
    )
    previous_item = (
        copy.deepcopy(assets[asset_type][duplicate_index])
        if duplicate_index is not None and isinstance(assets[asset_type][duplicate_index], dict)
        else None
    )
    if duplicate_index is not None and not overwrite:
        raise FileExistsError(f"{_asset_type_label(asset_type)}名称已存在")
    media = (
        _normalize_media_asset(project_id, asset.get("media"))
        if project_asset_scope
        else _normalize_global_media_asset(asset_type, asset.get("media"))
    )
    reference_media = (
        _normalize_media_asset(project_id, asset.get("referenceMedia"))
        if asset_scope == "project" and project_id and isinstance(asset.get("referenceMedia"), dict)
        else asset.get("referenceMedia")
    )
    asset_id = (
        _next_short_asset_id(asset_type, _asset_row_ids(assets.get(asset_type)))
        if asset_type in _SHORT_ASSET_ID_PREFIX_BY_TYPE
        else f"{asset_type}-{uuid.uuid4().hex[:8]}"
    )
    item = {
        "id": asset_id,
        "name": name,
        "desc": str(asset.get("desc") or ""),
        "accent": asset.get("accent") or ACCENTS[len(assets[asset_type]) % len(ACCENTS)],
        "media": media if isinstance(media, dict) else None,
    }
    lifecycle_patch = _asset_lifecycle_patch_value(asset)
    if lifecycle_patch is not None:
        _set_asset_lifecycle_status(item, lifecycle_patch)
    if previous_item and overwrite:
        item["id"] = str(previous_item.get("id") or item["id"])
        item["accent"] = previous_item.get("accent") or item["accent"]
        _preserve_asset_grouping_metadata(item, previous_item)
    if asset_type == "characters":
        item["voiceStyle"] = str(asset.get("voiceStyle") or asset.get("voice_style") or "")
    elif asset_type == "creatures":
        voice_style = str(asset.get("voiceStyle") or asset.get("voice_style") or "").strip()
        item["canSpeak"] = bool(voice_style)
        if voice_style:
            item["voiceStyle"] = voice_style
    if asset_type in {"characters", "creatures"}:
        if "voiceReferenceAudio" in asset or "voice_reference_audio" in asset:
            voice_reference_audio = asset.get("voiceReferenceAudio", asset.get("voice_reference_audio"))
            if isinstance(voice_reference_audio, dict):
                from .media_files import _normalize_global_voice_reference_audio
                from .media_files import _normalize_voice_reference_audio

                item["voiceReferenceAudio"] = (
                    _normalize_voice_reference_audio(project_id, voice_reference_audio, force_copy=True)
                    if project_asset_scope
                    else _normalize_global_voice_reference_audio(asset_type, voice_reference_audio, force_copy=True)
                )
        elif previous_item and overwrite:
            previous_audio = previous_item.get("voiceReferenceAudio") or previous_item.get("voice_reference_audio")
            if isinstance(previous_audio, dict):
                item["voiceReferenceAudio"] = copy.deepcopy(previous_audio)
    if project_asset_scope:
        _apply_asset_design_prompt_patch(item, asset)
        _ensure_asset_design_prompt_for_storage(asset_type, item)
    else:
        _apply_asset_design_prompt_patch(item, asset)
    if project_asset_scope:
        tag = str(asset.get("tag") or "").strip()
        if tag:
            item["tag"] = tag
        item["version"] = asset.get("version") or "v1"
        item["referenceMedia"] = reference_media if isinstance(reference_media, dict) else None
        if item["referenceMedia"]:
            item["referenceMediaRole"] = asset.get("referenceMediaRole", "reference")
            uses_original_image_reference(item["referenceMedia"], item["referenceMediaRole"])
        incoming_versions = asset.get("mediaVersions") if isinstance(asset.get("mediaVersions"), list) else []
        media_versions = [
            version
            for version in (
                _asset_media_version_from_payload(project_id, version, snapshot=item)
                for version in incoming_versions
            )
            if version
        ]
        if media_versions:
            item["mediaVersions"] = media_versions
            active_version_id = str(
                asset.get("activeMediaVersionId")
                or asset.get("activeVersionId")
                or asset.get("mediaVersionId")
                or asset.get("sourceVersionId")
                or ""
            ).strip()
            active_version = next(
                (
                    version
                    for version in media_versions
                    if str(version.get("id") or "") == active_version_id
                ),
                None,
            )
            if not active_version:
                active_version = next(
                    (
                        version
                        for version in reversed(media_versions)
                        if isinstance(version.get("media"), dict)
                    ),
                    media_versions[-1],
                )
            item["activeMediaVersionId"] = str(active_version.get("id") or "") or None
            if isinstance(active_version.get("media"), dict):
                item["media"] = copy.deepcopy(active_version.get("media"))
        else:
            media_version = _asset_media_version(
                item.get("media") if isinstance(item.get("media"), dict) else None,
                "v1 设计图",
                snapshot=item,
                allow_empty=True,
            )
            item["mediaVersions"] = [media_version] if media_version else []
            item["activeMediaVersionId"] = media_version.get("id") if media_version else None
        normalized_versions = _ensure_asset_media_versions(item)
        active_version_id = str(item.get("activeMediaVersionId") or "").strip()
        active_version = next(
            (
                version
                for version in normalized_versions
                if str(version.get("id") or "") == active_version_id
            ),
            None,
        )
        if isinstance((active_version or {}).get("media"), dict):
            item["media"] = copy.deepcopy(active_version.get("media"))
    if duplicate_index is not None and overwrite:
        assets[asset_type][duplicate_index] = item
        if project_asset_scope and project_id and previous_item:
            remaining_media_paths: set[Path] = set()
            for current_asset_type in ASSET_TYPES:
                for asset_row in assets.get(current_asset_type) or []:
                    remaining_media_paths.update(_project_asset_media_paths(project_id, asset_row))
            _delete_project_asset_media_files(
                project_id,
                previous_item,
                keep=remaining_media_paths,
                keep_voice_reference=True,
            )
        elif previous_item:
            previous_path = _global_asset_media_path(previous_item.get("media"))
            next_path = _global_asset_media_path(item.get("media"))
            if previous_path and previous_path != next_path:
                _delete_global_asset_media_file(previous_item.get("media"))
    else:
        assets[asset_type].append(item)
    _write_json(_asset_store_path(asset_scope, project_id), assets)
    if previous_item and overwrite:
        _delete_asset_voice_reference_audio_if_unreferenced(
            asset_scope,
            project_id,
            previous_item.get("voiceReferenceAudio") or previous_item.get("voice_reference_audio"),
        )
    if asset_scope == "project":
        _touch_project_meta(project_id)
    response_asset = _hydrate_asset_row_for_ui(project_id, item) if asset_scope == "project" and project_id else item
    if (
        previous_item and overwrite
        and ("voiceReferenceAudio" in asset or "voice_reference_audio" in asset)
        and "voiceReferenceAudio" not in response_asset
    ):
        response_asset = {**response_asset, "voiceReferenceAudio": None}
    result = {"success": True, "asset": response_asset}
    if project_asset_scope:
        result["changedResources"] = _asset_write_changed_resources(asset_type)
    return result


def create_asset(
    asset_type: str,
    asset: dict[str, Any],
    asset_scope: str = "global",
    project_id: str | None = None,
) -> dict[str, Any]:
    with _JSON_WRITE_LOCK:
        return _create_asset_unlocked(
            asset_type,
            asset,
            asset_scope,
            project_id,
        )


def update_asset(
    asset_type: str,
    asset_id: str,
    patch: dict[str, Any],
    asset_scope: str = "global",
    project_id: str | None = None,
) -> dict[str, Any]:
    from .media_files import _delete_global_asset_media_file
    from .media_files import _global_asset_media_path
    from .agent_sessions import _hydrate_asset_row_for_ui
    from .media_files import _normalize_global_media_asset
    from .projects import _touch_project_meta
    assets = list_assets(asset_scope, project_id, hydrate=False)
    if asset_type not in assets:
        raise ValueError("资产类型无效")
    project_asset_scope = asset_scope != "global" and bool(project_id)
    if "name" in patch:
        next_name = str(patch.get("name") or "").strip()
        duplicate_index = _find_asset_index_by_name(
            assets.get(asset_type),
            next_name,
            ASSET_LIFECYCLE_ACTIVE if project_asset_scope and asset_type in {"characters", "creatures", "scenes", "props"} else ASSET_LIFECYCLE_ALL,
        )
        if duplicate_index is not None:
            duplicate = assets[asset_type][duplicate_index]
            if isinstance(duplicate, dict) and duplicate.get("id") != asset_id:
                raise FileExistsError(f"{_asset_type_label(asset_type)}名称已存在")
    updated = None
    previous_voice_reference_audio: dict[str, Any] | None = None
    for item in assets[asset_type]:
        if item.get("id") != asset_id:
            continue
        previous_item = copy.deepcopy(item)
        previous_voice_value = item.get("voiceReferenceAudio") or item.get("voice_reference_audio")
        if isinstance(previous_voice_value, dict):
            previous_voice_reference_audio = copy.deepcopy(previous_voice_value)
        lifecycle_patch = _asset_lifecycle_patch_value(patch)
        if (
            lifecycle_patch is not None
            and _normalize_asset_lifecycle_status(lifecycle_patch) == ASSET_LIFECYCLE_ACTIVE
            and project_asset_scope
            and asset_type in {"characters", "creatures", "scenes", "props"}
        ):
            restore_name = str(patch.get("name") or item.get("name") or item.get("title") or "").strip()
            duplicate_index = _find_asset_index_by_name(assets.get(asset_type), restore_name, ASSET_LIFECYCLE_ACTIVE)
            if duplicate_index is not None:
                duplicate = assets[asset_type][duplicate_index]
                if isinstance(duplicate, dict) and duplicate.get("id") != asset_id:
                    raise FileExistsError(f"{_asset_type_label(asset_type)}名称已存在，请先处理活跃组中的同名资产")
        if "name" in patch:
            item["name"] = str(patch.get("name") or item.get("name") or "未命名资产")
        if "desc" in patch:
            item["desc"] = str(patch.get("desc") or "")
        if asset_type == "characters" and "hideTurnaroundHeads" in patch:
            if not isinstance(patch["hideTurnaroundHeads"], bool):
                raise ValueError("三视图头部设置必须为布尔值")
            item["hideTurnaroundHeads"] = patch["hideTurnaroundHeads"]
        if "tag" in patch:
            tag = str(patch.get("tag") or "").strip()
            if tag:
                item["tag"] = tag
            else:
                item.pop("tag", None)
        if lifecycle_patch is not None:
            _set_asset_lifecycle_status(item, lifecycle_patch)
        if "voiceStyle" in patch or "voice_style" in patch:
            if asset_type == "characters":
                item["voiceStyle"] = str(
                    patch.get("voiceStyle") or patch.get("voice_style") or ""
                )
            elif asset_type == "creatures":
                voice_style = str(patch.get("voiceStyle") or patch.get("voice_style") or "").strip()
                item["canSpeak"] = bool(voice_style)
                if voice_style:
                    item["voiceStyle"] = voice_style
                else:
                    item.pop("voiceStyle", None)
            elif not project_asset_scope:
                item.pop("voiceStyle", None)
        if "voiceReferenceAudio" in patch or "voice_reference_audio" in patch:
            if asset_type not in {"characters", "creatures"}:
                item.pop("voiceReferenceAudio", None)
                item.pop("voice_reference_audio", None)
            elif isinstance(patch.get("voiceReferenceAudio", patch.get("voice_reference_audio")), dict):
                from .media_files import _normalize_global_voice_reference_audio
                from .media_files import _normalize_voice_reference_audio

                item.pop("voice_reference_audio", None)
                voice_reference_audio = patch.get("voiceReferenceAudio", patch.get("voice_reference_audio"))
                item["voiceReferenceAudio"] = (
                    _normalize_voice_reference_audio(project_id, voice_reference_audio, force_copy=True)
                    if project_asset_scope
                    else _normalize_global_voice_reference_audio(asset_type, voice_reference_audio, force_copy=True)
                )
            else:
                item.pop("voiceReferenceAudio", None)
                item.pop("voice_reference_audio", None)
        elif asset_type == "creatures" and ("canSpeak" in patch or "can_speak" in patch):
            if patch.get("canSpeak") or patch.get("can_speak"):
                item["canSpeak"] = bool(str(item.get("voiceStyle") or "").strip())
            else:
                item["canSpeak"] = False
                item.pop("voiceStyle", None)
        if project_asset_scope:
            if "desc" in patch and not _asset_payload_has_design_prompt(patch):
                item.pop("prompts", None)
            _apply_asset_design_prompt_patch(item, patch)
            _ensure_asset_design_prompt_for_storage(asset_type, item)
        else:
            _apply_asset_design_prompt_patch(item, patch)
        if "media" in patch:
            previous_media = copy.deepcopy(item.get("media"))
            media = (
                _normalize_media_asset(project_id, patch.get("media"))
                if project_asset_scope
                else _normalize_global_media_asset(asset_type, patch.get("media"))
            )
            item["media"] = media if isinstance(media, dict) else None
            if not project_asset_scope:
                previous_path = _global_asset_media_path(previous_media)
                next_path = _global_asset_media_path(media)
                if previous_path and previous_path != next_path:
                    _delete_global_asset_media_file(previous_media)
        if patch.get("referenceMediaRole") == "original" and "referenceMedia" not in patch:
            original_media = item.get("media")
            if not isinstance(original_media, dict) or not original_media:
                raise ValueError("当前资产没有原图，无法使用原图")
            item["referenceMedia"] = copy.deepcopy(original_media)
            item["referenceMediaRole"] = "original"
        elif "referenceMedia" in patch:
            if isinstance(patch.get("referenceMedia"), dict):
                reference_media = (
                    _normalize_media_asset(project_id, patch.get("referenceMedia"))
                    if asset_scope == "project" and project_id
                    else patch.get("referenceMedia")
                )
                role = patch.get("referenceMediaRole", "reference")
                uses_original_image_reference(reference_media, role)
                item["referenceMedia"] = reference_media
                item["referenceMediaRole"] = role
            else:
                item["referenceMedia"] = None
                item["referenceMediaRole"] = None
        if not project_asset_scope:
            _normalize_global_asset_item_for_storage(asset_type, item)
        elif "media" in patch or _asset_version_state_changed(previous_item, item):
            versions = _ensure_asset_media_versions(item)
            next_version = len(versions) + 1
            item["version"] = f"v{next_version}"
            title = (
                f"v{next_version} 设计图"
                if "media" in patch
                else f"v{next_version} 提示词版本"
            )
            media_version = _asset_media_version(
                item.get("media") if isinstance(item.get("media"), dict) else None,
                title,
                snapshot=item,
                allow_empty=True,
            )
            if media_version:
                versions.append(media_version)
                item["mediaVersions"] = versions
                item["activeMediaVersionId"] = media_version["id"]
        updated = item
        break
    if not updated:
        raise FileNotFoundError("资产不存在")
    _write_json(_asset_store_path(asset_scope, project_id), assets)
    if (
        previous_voice_reference_audio is not None
        and ("voiceReferenceAudio" in patch or "voice_reference_audio" in patch)
    ):
        _delete_asset_voice_reference_audio_if_unreferenced(
            asset_scope,
            project_id,
            previous_voice_reference_audio,
        )
    if asset_scope == "project":
        _touch_project_meta(project_id)
    response_asset = _hydrate_asset_row_for_ui(project_id, updated) if asset_scope == "project" and project_id else updated
    if (
        ("voiceReferenceAudio" in patch or "voice_reference_audio" in patch)
        and "voiceReferenceAudio" not in response_asset
    ):
        response_asset = {**response_asset, "voiceReferenceAudio": None}
    result = {"success": True, "asset": response_asset}
    if project_asset_scope:
        result["changedResources"] = _asset_write_changed_resources(asset_type)
    return result


def delete_asset(
    asset_type: str,
    asset_id: str,
    asset_scope: str = "global",
    project_id: str | None = None,
    *,
    expected_revision: Any = None,
    base_hash: Any = None,
    reason: str = "",
    user_instruction: str = "",
) -> dict[str, Any]:
    from .project_resource_revisions import _append_resource_revision
    from .project_resource_revisions import _assert_resource_write_guard
    from .media_files import _delete_global_asset_media_file
    from .project_resource_revisions import _json_hash
    from .project_resource_revisions import _resource_revision_value
    from .projects import _touch_project_meta
    assets = list_assets(asset_scope, project_id, hydrate=False)
    assets_before = copy.deepcopy(assets)
    if asset_scope == "project" and project_id:
        _assert_resource_write_guard(assets_before, expected_revision, base_hash)
    if asset_type not in assets:
        raise ValueError("资产类型无效")
    deleted_items = [item for item in assets[asset_type] if item.get("id") == asset_id]
    if asset_scope == "project" and project_id:
        for item in deleted_items:
            if isinstance(item, dict) and _project_asset_is_referenced(project_id, asset_type, item):
                raise ValueError("资产已被引用，禁止删除")
    assets[asset_type] = [item for item in assets[asset_type] if item.get("id") != asset_id]
    if asset_scope == "global" or not project_id:
        for item in deleted_items:
            _delete_global_asset_media_file(item.get("media") if isinstance(item, dict) else None)
    if asset_scope == "project" and project_id:
        remaining_media_paths: set[Path] = set()
        for current_asset_type in ASSET_TYPES:
            for asset_row in assets.get(current_asset_type) or []:
                remaining_media_paths.update(_project_asset_media_paths(project_id, asset_row))
        for item in deleted_items:
            _delete_project_asset_media_files(project_id, item, keep=remaining_media_paths, keep_voice_reference=True)
        assets["revision"] = _resource_revision_value(assets_before) + 1
        assets["updatedAt"] = _now()
    _write_json(_asset_store_path(asset_scope, project_id), assets)
    for item in deleted_items:
        if isinstance(item, dict):
            _delete_asset_voice_reference_audio_if_unreferenced(
                asset_scope, project_id,
                item.get("voiceReferenceAudio") or item.get("voice_reference_audio"),
            )
    if asset_scope == "project":
        _append_resource_revision(
            project_id,
            resource="assets",
            relative_path="assets/assets.json",
            document=assets_before,
            reason=reason or "delete_asset",
            user_instruction=user_instruction,
        )
        _touch_project_meta(project_id)
    return {
        "success": True,
        "assetType": asset_type,
        "assetId": asset_id,
        "deletedCount": len(deleted_items),
        "changedResources": [asset_type] if asset_scope == "project" else [],
        "focusTarget": {"section": asset_type, "assetTab": asset_type} if asset_scope == "project" else {},
        "projectChanged": bool(asset_scope == "project"),
        "resourceHash": _json_hash(assets),
        "resourceRevision": _resource_revision_value(assets),
    }


def _delete_all_asset_types(value: Any) -> tuple[str, ...]:
    if value in (None, "", "split", "project"):
        return ("characters", "creatures", "scenes", "props")
    rows = value if isinstance(value, list) else [value]
    if not rows:
        return ("characters", "creatures", "scenes", "props")
    aliases = {
        "角色": "characters",
        "人物": "characters",
        "character": "characters",
        "生物": "creatures",
        "怪物": "creatures",
        "妖兽": "creatures",
        "魔兽": "creatures",
        "creature": "creatures",
        "creatures": "creatures",
        "monster": "creatures",
        "monsters": "creatures",
        "scene": "scenes",
        "场景": "scenes",
        "prop": "props",
        "道具": "props",
        "style": "styles",
        "风格": "styles",
        "样式": "styles",
    }
    selected: list[str] = []
    unknown: list[str] = []
    for item in rows:
        text = str(item or "").strip()
        if not text:
            continue
        if text.casefold() in {"all", "*", "全部", "所有"}:
            return tuple(ASSET_TYPES)
        key = aliases.get(text) or aliases.get(text.casefold()) or _normalize_asset_type_key(text)
        if key and key not in selected:
            selected.append(key)
        elif not key:
            unknown.append(text)
    if unknown:
        raise ValueError(f"无法识别的资产删除类型：{', '.join(unknown)}")
    return tuple(selected or ("characters", "creatures", "scenes", "props"))


def _reset_project_asset_ranges(
    project_id: str,
    *,
    reason: str,
    user_instruction: str,
) -> dict[str, Any]:
    from .project_resource_revisions import _append_resource_revision
    from .source_coverage import _load_source_coverage
    from .project_resource_revisions import _resource_revision_value
    from .source_coverage import _source_coverage_path
    from .source_coverage import _write_source_coverage
    path = _source_coverage_path(project_id)
    if not path.exists():
        return {"changed": False, "removedCount": 0}
    try:
        coverage = _load_source_coverage(project_id)
    except Exception as exc:  # noqa: BLE001 - no source may exist yet.
        return {"changed": False, "removedCount": 0, "skippedReason": str(exc)}
    coverage_before = copy.deepcopy(coverage)
    removed_count = len(coverage.get("assetRanges") or []) if isinstance(coverage.get("assetRanges"), list) else 0
    coverage["assetRanges"] = []
    coverage.setdefault("assetCursor", {})["nextOffset"] = 0
    coverage["assetCursor"]["lastRangeId"] = None
    if coverage == coverage_before:
        return {"changed": False, "removedCount": 0}
    _append_resource_revision(
        project_id,
        resource="sourceCoverage",
        relative_path="source_coverage.json",
        document=coverage_before,
        reason=reason or "delete_all_project_assets",
        user_instruction=user_instruction,
    )
    coverage["revision"] = _resource_revision_value(coverage_before) + 1
    _write_source_coverage(project_id, coverage)
    return {"changed": True, "removedCount": removed_count, "coverage": coverage}


def delete_all_project_assets(project_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from .project_resource_revisions import _append_resource_revision
    from .project_resource_revisions import _assert_resource_write_guard
    from .project_resource_revisions import _json_hash
    from .project_resource_revisions import _resource_revision_value
    from .projects import _touch_project_meta
    if not str(project_id or "").strip():
        raise ValueError("缺少 projectId")
    payload = payload if isinstance(payload, dict) else {}
    user_instruction = _assert_explicit_delete_all_confirmed(
        payload,
        target_label="项目资产",
        target_terms=(
            "资产",
            "角色",
            "生物",
            "怪物",
            "场景",
            "道具",
            "风格",
            "characters",
            "creatures",
            "scenes",
            "props",
            "styles",
            "asset",
            "assets",
        ),
    )
    asset_types = _delete_all_asset_types(payload.get("assetTypes") or payload.get("asset_types"))
    expected_revision = payload.get("expectedRevision") or payload.get("expected_revision")
    base_hash = payload.get("baseHash") or payload.get("base_hash")
    reason = str(payload.get("reason") or "delete_all_project_assets")
    reset_asset_ranges = payload.get("resetAssetRanges")
    if reset_asset_ranges is None:
        reset_asset_ranges = payload.get("reset_asset_ranges")
    reset_asset_ranges = True if reset_asset_ranges is None else _truthy_confirmation(reset_asset_ranges)

    assets = list_assets("project", project_id, hydrate=False)
    assets_before = copy.deepcopy(assets)
    _assert_resource_write_guard(assets_before, expected_revision, base_hash)

    deleted_counts: dict[str, int] = {}
    for asset_type in asset_types:
        rows = assets.get(asset_type)
        if not isinstance(rows, list):
            rows = []
        deleted_counts[asset_type] = len([item for item in rows if isinstance(item, dict)])
        for item in rows:
            _delete_project_asset_media_files(project_id, item, keep_voice_reference=True)
        assets[asset_type] = []

    changed_asset_types = [asset_type for asset_type, count in deleted_counts.items() if count > 0]
    if changed_asset_types:
        assets["revision"] = _resource_revision_value(assets_before) + 1
        assets["updatedAt"] = _now()
        _write_json(_asset_store_path("project", project_id), assets)
        for asset_type in asset_types:
            for item in assets_before.get(asset_type) or []:
                if isinstance(item, dict):
                    _delete_asset_voice_reference_audio_if_unreferenced(
                        "project", project_id,
                        item.get("voiceReferenceAudio") or item.get("voice_reference_audio"),
                    )
        _append_resource_revision(
            project_id,
            resource="assets",
            relative_path="assets/assets.json",
            document=assets_before,
            reason=reason,
            user_instruction=user_instruction,
        )
        _touch_project_meta(project_id)

    asset_range_reset = (
        _reset_project_asset_ranges(project_id, reason=reason, user_instruction=user_instruction)
        if reset_asset_ranges
        else {"changed": False, "removedCount": 0}
    )
    changed_resources = list(changed_asset_types)
    if asset_range_reset.get("changed"):
        changed_resources.append("assetRanges")
    return {
        "success": True,
        "message": "已删除当前项目已拆分资产。" if changed_resources else "当前项目没有可删除的已拆分资产。",
        "assetTypes": list(asset_types),
        "deletedCounts": deleted_counts,
        "deletedCount": sum(deleted_counts.values()),
        "assetRangeReset": {
            "changed": bool(asset_range_reset.get("changed")),
            "removedCount": int(asset_range_reset.get("removedCount") or 0),
            **(
                {"skippedReason": str(asset_range_reset.get("skippedReason") or "")}
                if asset_range_reset.get("skippedReason")
                else {}
            ),
        },
        "changedResources": changed_resources,
        "focusTarget": {"section": "assets"},
        "projectChanged": bool(changed_resources),
        "resourceHash": _json_hash(assets),
        "resourceRevision": _resource_revision_value(assets),
    }


def set_active_asset_media_version(
    asset_type: str,
    asset_id: str,
    version_id: str,
    asset_scope: str = "global",
    project_id: str | None = None,
) -> dict[str, Any]:
    from .agent_sessions import _hydrate_asset_row_for_ui
    from .projects import _touch_project_meta
    if asset_scope == "global" or not project_id:
        raise ValueError("全局资产库不支持版本切换")
    assets = list_assets(asset_scope, project_id, hydrate=False)
    if asset_type not in assets:
        raise ValueError("资产类型无效")
    for item in assets[asset_type]:
        if item.get("id") != asset_id:
            continue
        versions = _ensure_asset_media_versions(item)
        version = next((entry for entry in versions if entry.get("id") == version_id), None)
        if not version:
            raise FileNotFoundError("版本不存在")
        item["activeMediaVersionId"] = version_id
        item["media"] = copy.deepcopy(version.get("media")) if isinstance(version.get("media"), dict) else None
        if "desc" in version:
            item["desc"] = str(version.get("desc") or "")
        if asset_type in {"characters", "creatures"} and "voiceStyle" in version:
            item["voiceStyle"] = str(version.get("voiceStyle") or "")
        if asset_type == "creatures":
            voice_style = str(item.get("voiceStyle") or "").strip()
            item["canSpeak"] = bool(voice_style)
            if voice_style:
                item["voiceStyle"] = voice_style
            else:
                item.pop("voiceStyle", None)
        _ensure_asset_design_prompt_for_storage(asset_type, item)
        item["version"] = f"v{versions.index(version) + 1}"
        _write_json(_asset_store_path(asset_scope, project_id), assets)
        if asset_scope == "project":
            _touch_project_meta(project_id)
        response_asset = _hydrate_asset_row_for_ui(project_id, item) if asset_scope == "project" and project_id else item
        result = {"success": True, "asset": response_asset}
        result["changedResources"] = _asset_write_changed_resources(asset_type)
        return result
    raise FileNotFoundError("资产不存在")


def update_asset_media_version(
    asset_type: str,
    asset_id: str,
    version_id: str,
    patch: dict[str, Any],
    asset_scope: str = "global",
    project_id: str | None = None,
) -> dict[str, Any]:
    from .agent_sessions import _hydrate_asset_row_for_ui
    from .projects import _touch_project_meta
    if asset_scope == "global" or not project_id:
        raise ValueError("全局资产库不支持版本编辑")
    assets = list_assets(asset_scope, project_id, hydrate=False)
    if asset_type not in assets:
        raise ValueError("资产类型无效")
    patch = patch if isinstance(patch, dict) else {}
    for item in assets[asset_type]:
        if item.get("id") != asset_id:
            continue
        versions = _ensure_asset_media_versions(item)
        version = next((entry for entry in versions if entry.get("id") == version_id), None)
        if not version:
            raise FileNotFoundError("版本不存在")
        _apply_asset_version_state_patch(version, patch)
        _write_json(_asset_store_path(asset_scope, project_id), assets)
        _touch_project_meta(project_id)
        response_asset = _hydrate_asset_row_for_ui(project_id, item)
        return {"success": True, "asset": response_asset}
    raise FileNotFoundError("资产不存在")


def delete_asset_media_version(
    asset_type: str,
    asset_id: str,
    version_id: str,
    asset_scope: str = "global",
    project_id: str | None = None,
) -> dict[str, Any]:
    from .agent_sessions import _hydrate_asset_row_for_ui
    from .projects import _is_path_within
    from .agent_sessions import _project_dir
    from .agent_sessions import _project_file_from_ref
    from .projects import _touch_project_meta
    if asset_scope == "global" or not project_id:
        raise ValueError("全局资产库不支持版本删除")
    assets = list_assets(asset_scope, project_id, hydrate=False)
    if asset_type not in assets:
        raise ValueError("资产类型无效")
    for item in assets[asset_type]:
        if item.get("id") != asset_id:
            continue
        versions = _ensure_asset_media_versions(item)
        version = next((entry for entry in versions if entry.get("id") == version_id), None)
        if not version:
            raise FileNotFoundError("版本不存在")
        if len(versions) <= 1:
            raise ValueError("至少保留一个版本")
        if item.get("activeMediaVersionId") == version_id:
            raise ValueError("当前版本不能删除，请先切换到其它版本")
        removed_media = copy.deepcopy(version.get("media")) if isinstance(version.get("media"), dict) else None
        removed_paths: set[Path] = set()
        if isinstance(removed_media, dict):
            removed_path = _project_file_from_ref(project_id, removed_media)
            project_assets_dir = (_project_dir(project_id) / "assets").resolve()
            if removed_path:
                resolved_removed_path = removed_path.resolve()
                if _is_path_within(resolved_removed_path, project_assets_dir):
                    removed_paths.add(resolved_removed_path)
        next_versions = [entry for entry in versions if entry.get("id") != version_id]
        if len(next_versions) == len(versions):
            raise FileNotFoundError("版本不存在")
        item["mediaVersions"] = next_versions
        _write_json(_asset_store_path(asset_scope, project_id), assets)
        if removed_paths:
            referenced_paths: set[Path] = set()
            for current_asset_type in ASSET_TYPES:
                for asset_row in assets.get(current_asset_type) or []:
                    referenced_paths.update(_project_asset_media_paths(project_id, asset_row))
            for path in removed_paths - referenced_paths:
                try:
                    if path.is_file():
                        path.unlink()
                except OSError:
                    continue
        if asset_scope == "project":
            _touch_project_meta(project_id)
        response_asset = _hydrate_asset_row_for_ui(project_id, item) if asset_scope == "project" and project_id else item
        return {"success": True, "asset": response_asset}
    raise FileNotFoundError("资产不存在")


def _asset_type_label(asset_type: str) -> str:
    return {
        "characters": "角色",
        "creatures": "生物",
        "scenes": "场景",
        "props": "道具",
        "styles": "风格",
    }.get(asset_type, "资产")


def _default_asset_design_prompt(asset_type: str, item: dict[str, Any]) -> str:
    name = str(item.get("name") or item.get("title") or "").strip()
    desc = str(item.get("desc") or item.get("description") or "").strip()
    if not name or not desc:
        return ""
    if asset_type == "characters":
        return f"角色「{name}」视觉设定：{desc}"
    if asset_type == "creatures":
        return f"生物「{name}」视觉设定：{desc}"
    if asset_type == "scenes":
        return f"场景「{name}」视觉设定：{desc}"
    if asset_type == "props":
        return f"道具「{name}」视觉设定：{desc}"
    return ""


def _is_legacy_default_asset_design_prompt(asset_type: str, item: dict[str, Any], prompt: str) -> bool:
    name = str(item.get("name") or item.get("title") or "").strip()
    label = _asset_type_label(asset_type)
    return bool(name and str(prompt or "").strip().startswith(f"{label}「{name}」视觉设定："))


def _ensure_asset_design_prompt_for_storage(
    asset_type: str,
    item: dict[str, Any],
    *,
    previous_item: dict[str, Any] | None = None,
) -> None:
    if asset_type not in {"characters", "creatures", "scenes", "props"} or not isinstance(item, dict):
        return
    existing_prompt = _asset_design_prompt_from_asset(item)
    previous_prompt = _asset_design_prompt_from_asset(previous_item or {})
    for key in ("prompt", *_ASSET_IMAGE_PROMPT_KEYS):
        item.pop(key, None)
    design_prompt = existing_prompt or previous_prompt or _default_asset_design_prompt(asset_type, item)
    if design_prompt:
        item["prompts"] = {"assetImagePrompt": design_prompt}
    else:
        item.pop("prompts", None)


_ASSET_IMAGE_PROMPT_KEYS = (
    "assetImagePrompt",
    "asset_image_prompt",
    "assetVisualPrompt",
    "asset_visual_prompt",
    "designPrompt",
    "design_prompt",
    "imagePrompt",
    "image_prompt",
    "imageGenerationPrompt",
    "image_generation_prompt",
    "image",
    "visualPrompt",
    "visual_prompt",
    "visualDescription",
    "visual_description",
    "appearancePrompt",
    "appearance_prompt",
    "referencePrompt",
    "reference_prompt",
    "generationPrompt",
    "generation_prompt",
    "closeupPrompt",
    "closeup_prompt",
    "prompt",
)

_ASSET_CHARACTER_LAYOUT = (
    "横版 16:9 构图，纯白 (#FFFFFF) 背景。\n"
    "仅四个视图区：左侧约 40% 宽为正面头肩主图，完整展示头部、脖颈和肩部；"
    "右侧约 60% 宽为三个等宽的全身视图面板，依次展示正面、面朝画面右侧的 90° 纯侧面和背面，保持自然 A-Pose。"
    "三个视图等高、同一基线，双脚完整。"
)
_ASSET_CHARACTER_HEADED_TURNAROUND = "右侧三视图均完整展示头部和脖颈。"
_ASSET_CHARACTER_HEADLESS_TURNAROUND = (
    "右侧三视图仅省略头部，完整保留颈部及以下的身体、服装和配饰；"
    "躯干保持完整连续，不留空洞或透明区域；左侧头肩主图仍完整展示头部与脖颈。"
)
_ASSET_CHARACTER_PROP_RULE = (
    "服装材质和已有配饰直接体现在对应视图中。"
    "默认不增加局部放大框、材质板、拆解图、独立道具特写或额外视图区。"
)
_ASSET_SCENE_LAYOUT = "单一完整纯场景画面，完整展示环境整体外观、空间层次、氛围与陈设。"
_ASSET_PROP_LAYOUT = "横向宽幅构图，三视图水平排列于纯净浅灰背景：左侧正面全视图、中间 45° 侧视图体现立体感、右侧关键细节特写。"
_ASSET_CHARACTER_GUARD = (
    "各视图保持同一身份和同一基础造型，可见的面部、发型、体型、服装与配饰一致，服装结构随视角正确对应。"
    "群体资产以一名代表成员展示母版确定的服饰体系和身份标识，不混排不同成员。"
)
_ASSET_CHARACTER_PRESENTATION_GUIDE = "中性表情、均匀柔光，清晰呈现人物外观和服装结构。"
_ASSET_CREATURE_LAYOUT = (
    "横版 16:9 构图，纯白 (#FFFFFF) 背景，干净高级的非人形活体设定集版式。\n\n"
    "版式要求：左侧展示完整主体轮廓与主要姿态，右侧分为结构细节、头部/感官特写、肢体/翅翼/鳞甲/皮毛/外壳等关键部位特写；"
    "如果原文体现飞行、水生、爬行、巨型或群体特征，版式需让运动方式和尺度关系清晰可辨。"
)
_ASSET_CREATURE_GUARD = (
    "一致性要求：所有视图必须是同一种生物，同一体型、头部结构、肢体数量、表皮材质和标志性器官；"
    "保持母版确定的非人形解剖结构；已有依据的服饰、饰件与装配在各视图中保持一致。"
)
_ASSET_CREATURE_PRESENTATION_GUIDE = "展示要求：白底静态设定图，突出物种结构、尺度、习性和识别锚点。"
_ASSET_MASTER_DESCRIPTION_SCOPE = (
    "从资产母版资料提取主体身份、结构、材质、尺度、色彩、长期装配和识别锚点。"
    "描述中的版式或制作说明不属于主体外观；本张图的版式以下方展示要求为准。\n\n"
)
_ASSET_SCENE_GUARD = (
    "空间透视正常，陈设固定，光影统一。"
    "表现可供后续取景的空场景，突出空间结构、固定家具设施、长期陈设、材质光线及稳定绿化。"
    "不加入人物、生物或仅属于某次剧情事件的物件与动作。"
)
_ASSET_SCENE_DESCRIPTION_SCOPE = (
    "从空间母版资料提取空间结构、固定家具设施、长期陈设、材质、光线和稳定使用痕迹。"
    "人物活动、临时事件和版式说明不属于本张空场景的空间母版；版式以下方展示要求为准。\n\n"
)
_ASSET_PROP_GUARD = "外观结构完整，焦点清晰。"
_ASSET_NEGATIVE_TAIL_CHARACTER = (
    "画质要求：主体清晰，面部、手部和肢体结构符合角色设定，"
    "遵循项目画风；画面无水印。"
)
_ASSET_QUALITY_TAIL_CREATURE = (
    "画质要求：主体清晰，解剖结构与材质符合生物设定，各视图的物种识别点及已确定的服饰、装配一致，"
    "背景和文字标注简洁，遵循项目画风；画面无水印。"
)
_ASSET_NEGATIVE_TAIL = (
    "画质要求：主体清晰，结构与材质准确，画面整洁，遵循项目画风；画面无水印。"
)
_ASSET_TEXT_LANGUAGE_LABELS = {
    "zh-CN": "简体中文",
    "zh-TW": "繁体中文",
    "en-US": "英文",
    "vi-VN": "越南语",
}


def _asset_character_text_guard(text_language: str = "简体中文") -> str:
    return (
        "文字约束：仅保留母版明确要求的服装图案、徽记及实物文字；"
        "不生成角色简介、说明文字、视图标签或尺寸、身高标注。"
    )


def _asset_creature_text_guard(text_language: str = "简体中文") -> str:
    language = str(text_language or "").strip() or "简体中文"
    return (
        f"文字约束：图内若使用物种名称或结构短标签，统一使用{language}，"
        "保持简短清晰并贴近对应图示；画面以生物本体和结构细节为主。"
    )


def _asset_mapping_text(source: Any, keys: tuple[str, ...]) -> str:
    if not isinstance(source, dict):
        return ""
    nested_keys = tuple(dict.fromkeys((*keys, "text", "content", "description", "summary", "value")))
    for key in keys:
        value = source.get(key)
        if isinstance(value, dict):
            nested = _asset_mapping_text(value, nested_keys)
            if nested:
                return nested
        elif isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, dict):
                    nested = _asset_mapping_text(item, nested_keys)
                    if nested:
                        parts.append(nested)
                elif item is not None and str(item).strip():
                    parts.append(str(item).strip())
            text = " ".join(parts)
            if text:
                return text
        elif value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _asset_design_prompt_from_asset(asset: dict[str, Any]) -> str:
    prompts = asset.get("prompts") if isinstance(asset.get("prompts"), dict) else {}
    return _asset_mapping_text(prompts, _ASSET_IMAGE_PROMPT_KEYS) or _asset_mapping_text(asset, _ASSET_IMAGE_PROMPT_KEYS)


def _character_visual_prompt_is_complete(text: str, asset_name: str | None = None) -> bool:
    return bool(str(text or "").strip())


def _asset_reference_image(
    project_id: str | None,
    asset_type: str,
    asset: dict[str, Any],
    image_input_limits: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    reference_media = asset.get("referenceMedia") if isinstance(asset.get("referenceMedia"), dict) else None
    if not reference_media:
        return None
    return _provider_reference_image_from_media(
        project_id,
        reference_media,
        purpose=f"asset-{asset_type}-reference",
        image_input_limits=image_input_limits,
    )


def _raise_if_character_visual_prompt_incomplete(
    asset: dict[str, Any],
    prompt: str | None = None,
    project_id: str | None = None,
    reference_image: dict[str, Any] | None = None,
) -> None:
    name = str(asset.get("name") or asset.get("title") or "未命名角色").strip() or "未命名角色"
    if reference_image or _asset_reference_image(project_id, "characters", asset):
        return
    desc = str(asset.get("desc") or asset.get("description") or "").strip()
    if _character_visual_prompt_is_complete(desc, name):
        return
    raise ValueError(f"角色「{name}」缺少可用于生成设计图的外貌/服饰设定，请先补充角色视觉设定后再生成设计图。")


def _raise_if_asset_generation_prompt_override(prompt: str | None = None) -> None:
    """Keep old callers harmless: asset image generation ignores prompt overrides."""
    return


def _asset_style_prefix(style: str = "", style_description: str = "") -> str:
    description = str(style_description or "").strip()
    if not description:
        return ""
    description = re.sub(r"^\s*(?:画风|风格|视觉风格)\s*[:：]\s*", "", description)
    if not description:
        return ""
    if re.match(r"^\s*【[^】]+】", description):
        return f"{description}\n\n"
    return f"【视觉风格】\n{description}\n\n"


_ASSET_SPECIFIC_STYLE_PROMPT_KEYS = {
    "characters": (
        "characterAssetPrompt",
        "character_asset_prompt",
        "characterStylePrompt",
        "character_style_prompt",
    ),
    "creatures": (
        "creatureAssetPrompt",
        "creature_asset_prompt",
        "creatureStylePrompt",
        "creature_style_prompt",
    ),
}


def _is_general_style_template_mapping(source: Any) -> bool:
    if not isinstance(source, dict):
        return False
    return (
        str(source.get("id") or "") == GENERAL_STYLE_TEMPLATE_ID
        or str(source.get("category") or "") == "general"
    )


def _general_asset_style_tag_prefix(visual_type_tag: Any) -> str:
    visual_type_text = str(visual_type_tag or "").strip()
    visual_prompt = (
        GENERAL_VISUAL_TYPE_PROMPTS.get(visual_type_text)
        or (f"画面类型：{visual_type_text}。" if visual_type_text else "")
    )
    return visual_prompt


def _strip_general_asset_style_tag_prefix(prompt: str) -> str:
    text = str(prompt or "").strip()
    labeled_prefix_match = re.match(r"^画面类型[:：]([^，,。；;\r\n]*)(?:[，,。；;]\s*|$)", text)
    if labeled_prefix_match and "统一美术风格" not in labeled_prefix_match.group(1):
        return text[len(labeled_prefix_match.group(0)):].lstrip(" \t\r\n，,；;。")
    for visual_type_tag in GENERAL_VISUAL_TYPE_TAGS:
        prefix = _general_asset_style_tag_prefix(visual_type_tag)
        if not prefix:
            continue
        if text == prefix:
            return ""
        if text.startswith(prefix):
            return text[len(prefix):].lstrip(" \t\r\n，,；;。")
    return text


def _with_general_asset_style_tag_prefix(prompt: str, visual_type_tag: Any) -> str:
    raw_text = str(prompt or "").strip()
    if raw_text.startswith("画面类型：") and "统一美术风格" in raw_text:
        return raw_text
    prefix = _general_asset_style_tag_prefix(visual_type_tag)
    text = _strip_general_asset_style_tag_prefix(prompt)
    if not prefix:
        return text
    if not text:
        return prefix
    if text == prefix or text.startswith(prefix):
        return text
    return f"{prefix}{text}"


def _asset_visual_prompt_label(asset_type: str | None) -> str:
    if asset_type == "characters":
        return "角色视觉"
    if asset_type == "creatures":
        return "生物视觉"
    return "全局视觉"


def _asset_style_prompt_from_mapping_with_label(
    source: Any,
    asset_type: str | None = None,
) -> tuple[str, str]:
    if not isinstance(source, dict):
        return "", _asset_visual_prompt_label(None)
    normalized_asset_type = str(asset_type or "")
    for key in _ASSET_SPECIFIC_STYLE_PROMPT_KEYS.get(normalized_asset_type, ()):
        value = str(source.get(key) or "").strip()
        if value:
            return value, _asset_visual_prompt_label(normalized_asset_type)
    value = str(
        source.get("assetPrompt")
        or source.get("asset_prompt")
        or source.get("visualStylePrompt")
        or source.get("visual_style_prompt")
        or ""
    ).strip()
    return value, _asset_visual_prompt_label(None)


def _asset_style_prompt_from_mapping(source: Any, asset_type: str | None = None) -> str:
    prompt, _label = _asset_style_prompt_from_mapping_with_label(source, asset_type)
    return prompt


def _asset_visual_prompt_block(base_prompt: Any, label: str) -> str:
    base = str(base_prompt or "").strip()
    if not base:
        return ""
    if re.match(r"^\s*【[^】]+】", base):
        stripped = re.sub(
            r"^\s*【(?:画风|风格|视觉风格|视觉风格提示词|全局视觉|角色视觉|生物视觉)】\s*",
            "",
            base,
        ).strip()
        if stripped != base:
            base = stripped
        else:
            return base
    base = re.sub(r"^\s*(?:画风|风格|视觉风格|视觉风格提示词)\s*[:：]\s*", "", base).strip()
    base = _strip_style_theme_visual_overlap_text(base)
    if not base:
        return ""
    if re.match(r"^\s*【[^】]+】", base):
        stripped = re.sub(
            r"^\s*【(?:画风|风格|视觉风格|视觉风格提示词|全局视觉|角色视觉|生物视觉)】\s*",
            "",
            base,
        ).strip()
        if stripped != base:
            base = stripped
        else:
            return base
    if not base:
        return ""
    return _prompt_labeled_block(label or "全局视觉", base)


def _compose_asset_visual_prompt(
    base_prompt: Any,
    theme_visual_prompt: Any,
    phase_visual_prompt: Any,
    visual_label: str = "全局视觉",
) -> str:
    parts: list[str] = []
    for block in (
        _style_theme_visual_prompt_block(theme_visual_prompt),
        _asset_visual_prompt_block(base_prompt, visual_label),
        _style_phase_visual_prompt_block(phase_visual_prompt),
    ):
        if block and block not in parts:
            parts.append(block)
    return _join_prompt_blocks(parts)


def _asset_project_style(project_id: str | None, asset_type: str | None = None) -> tuple[str, str]:
    from .projects import _find_template
    from .settings_loaders import load_style_templates
    if not project_id:
        return "", ""
    config = get_effective_config(project_id)
    style = config.get("style") if isinstance(config.get("style"), dict) else {}
    theme_visual_prompt = _style_theme_visual_prompt_from_config(config)
    phase_visual_prompt = _style_phase_visual_prompt_from_config(config)
    style_name = str(style.get("name") or style.get("label") or "").strip()
    style_mode = str(style.get("mode") or "").strip()
    style_template_id = str(config.get("style_template_id") or "").strip()
    if style_template_id and style_mode in {"template", "favorite", ""}:
        style_template = _find_template(style_template_id, load_style_templates())
        template_name = str(
            (style_template or {}).get("name") or (style_template or {}).get("label") or ""
        ).strip()
        template_asset_style, template_asset_label = _asset_style_prompt_from_mapping_with_label(style_template, asset_type)
        project_asset_style, project_asset_label = _asset_style_prompt_from_mapping_with_label(style, asset_type)
        if project_asset_style and _is_general_style_template_mapping(style_template):
            project_asset_style = _with_general_asset_style_tag_prefix(
                project_asset_style,
                style.get("visual_type_tag"),
            )
            return style_name or template_name, _compose_asset_visual_prompt(
                project_asset_style,
                theme_visual_prompt,
                phase_visual_prompt,
                project_asset_label,
            )
        if template_asset_style:
            return style_name or template_name, _compose_asset_visual_prompt(
                template_asset_style,
                theme_visual_prompt,
                phase_visual_prompt,
                template_asset_label,
            )
        if project_asset_style:
            if _is_general_style_template_mapping(style_template):
                project_asset_style = _with_general_asset_style_tag_prefix(
                    project_asset_style,
                    style.get("visual_type_tag"),
                )
            return style_name or template_name, _compose_asset_visual_prompt(
                project_asset_style,
                theme_visual_prompt,
                phase_visual_prompt,
                project_asset_label,
            )
        return style_name or template_name, _compose_asset_visual_prompt("", theme_visual_prompt, phase_visual_prompt)
    if style_mode in {"template", "favorite"}:
        return style_name, _compose_asset_visual_prompt("", theme_visual_prompt, phase_visual_prompt)
    asset_style, asset_style_label = _asset_style_prompt_from_mapping_with_label(style, asset_type)
    if asset_style:
        return style_name, _compose_asset_visual_prompt(
            asset_style,
            theme_visual_prompt,
            phase_visual_prompt,
            asset_style_label,
        )
    style_reference = style.get("reference") if isinstance(style.get("reference"), dict) else {}
    reference_style, reference_style_label = _asset_style_prompt_from_mapping_with_label(style_reference, asset_type)
    if reference_style:
        return style_name, _compose_asset_visual_prompt(
            reference_style,
            theme_visual_prompt,
            phase_visual_prompt,
            reference_style_label,
        )
    return style_name, _compose_asset_visual_prompt("", theme_visual_prompt, phase_visual_prompt)


def _asset_project_text_language(project_id: str | None) -> str:
    if not project_id:
        return "简体中文"
    config = get_effective_config(project_id)
    source_language = str(config.get("source_language") or "").strip()
    return _ASSET_TEXT_LANGUAGE_LABELS.get(source_language, "简体中文")


def _asset_generation_description(
    asset_type: str,
    asset: dict[str, Any],
    prompt: str | None = None,
    project_id: str | None = None,
    reference_image: dict[str, Any] | None = None,
) -> str:
    label = _asset_type_label(asset_type)
    desc = str(asset.get("desc") or "").strip()
    design_prompt = _asset_design_prompt_from_asset(asset)
    if _is_legacy_default_asset_design_prompt(asset_type, asset, design_prompt):
        design_prompt = ""
    name = str(asset.get("name") or asset.get("title") or "未命名").strip() or "未命名"
    has_reference_image = bool(reference_image) or bool(_asset_reference_image(project_id, asset_type, asset))
    description = design_prompt or desc
    if asset_type == "characters" and has_reference_image and not description:
        description = f"角色「{name}」的{label}设计参考，以已上传参考图作为主体视觉依据。"
    parts = [description or f"{name}的{label}设计参考。"]
    if has_reference_image:
        parts.append(f"已上传{label}参考图；生成时需保持主体轮廓、气质和关键视觉特征一致。")
    return "\n".join(part for part in parts if part)


def _build_asset_character_prompt(
    name: str,
    description: str,
    style: str = "",
    style_description: str = "",
    text_language: str = "简体中文",
    *,
    hide_turnaround_heads: bool = False,
) -> str:
    style_block = _asset_style_prefix(style, style_description)
    head_visibility = (
        _ASSET_CHARACTER_HEADLESS_TURNAROUND
        if hide_turnaround_heads
        else _ASSET_CHARACTER_HEADED_TURNAROUND
    )
    return (
        f"{style_block}"
        "【设计对象】\n"
        f"角色「{name}」的设计参考图 / character reference sheet / turnaround sheet，展示同一基础造型。\n\n"
        f"{_ASSET_MASTER_DESCRIPTION_SCOPE}"
        "【资产母版资料】\n"
        f"{description}\n\n"
        "【版式】\n"
        f"{_ASSET_CHARACTER_LAYOUT}\n{head_visibility}\n\n"
        f"{_ASSET_CHARACTER_GUARD}\n\n"
        "【呈现要求】\n"
        f"{_ASSET_CHARACTER_PRESENTATION_GUIDE}\n"
        f"{_ASSET_CHARACTER_PROP_RULE}\n"
        f"{_asset_character_text_guard(text_language)}\n"
        f"{_ASSET_NEGATIVE_TAIL_CHARACTER}"
    )


def _build_asset_creature_prompt(
    name: str,
    description: str,
    style: str = "",
    style_description: str = "",
    text_language: str = "简体中文",
) -> str:
    style_block = _asset_style_prefix(style, style_description)
    return (
        f"{style_block}"
        "【设计对象】\n"
        f"生物「{name}」的设计参考图 / creature reference sheet。\n\n"
        f"{_ASSET_MASTER_DESCRIPTION_SCOPE}"
        "【资产母版资料】\n"
        f"{description}\n\n"
        f"{_ASSET_CREATURE_LAYOUT}\n\n"
        f"{_asset_creature_text_guard(text_language)}\n\n"
        f"{_ASSET_CREATURE_GUARD}\n\n"
        f"{_ASSET_CREATURE_PRESENTATION_GUIDE}\n\n"
        f"{_ASSET_QUALITY_TAIL_CREATURE}"
    )


def _build_asset_scene_prompt(name: str, description: str, style: str = "", style_description: str = "") -> str:
    style_block = _asset_style_prefix(style, style_description)
    return (
        f"{style_block}"
        "【设计对象】\n"
        f"标志性场景「{name}」的视觉参考。\n\n"
        f"{_ASSET_SCENE_DESCRIPTION_SCOPE}"
        "【空间母版资料】\n"
        f"{description}\n\n"
        f"{_ASSET_SCENE_LAYOUT}\n\n"
        f"{_ASSET_SCENE_GUARD}\n\n"
        f"{_ASSET_NEGATIVE_TAIL}"
    )


def _build_asset_prop_prompt(name: str, description: str, style: str = "", style_description: str = "") -> str:
    style_block = _asset_style_prefix(style, style_description)
    return (
        f"{style_block}"
        "【设计对象】\n"
        f"道具「{name}」的多视角展示。\n\n"
        f"{_ASSET_MASTER_DESCRIPTION_SCOPE}"
        "【资产母版资料】\n"
        f"{description}\n\n"
        f"{_ASSET_PROP_LAYOUT}\n\n"
        f"{_ASSET_PROP_GUARD}\n\n"
        f"{_ASSET_NEGATIVE_TAIL}"
    )


def _asset_generation_aspect_ratio(asset_type: str, project_aspect_ratio: Any = None) -> str:
    if asset_type == "characters":
        return image_default_aspect_ratio("character")
    if asset_type == "creatures":
        return image_default_aspect_ratio("character")
    if asset_type == "scenes":
        return image_default_aspect_ratio("scene")
    if asset_type == "props":
        return image_default_aspect_ratio("prop")
    return image_default_aspect_ratio("asset")


def _asset_generation_resolution(image_config: dict[str, Any], asset_type: str) -> Any:
    role_keys = {
        "characters": "character_resolution",
        "creatures": "character_resolution",
        "scenes": "scene_resolution",
        "props": "prop_resolution",
    }
    default_presets = {
        "characters": "character",
        "creatures": "character",
        "scenes": "scene",
        "props": "prop",
    }
    role_key = role_keys.get(asset_type)
    if role_key:
        resolution = image_config.get(role_key)
        if resolution:
            return resolution
        return image_default_resolution(default_presets.get(asset_type))
    return image_config.get("asset_resolution") or image_default_resolution("asset")


def _asset_generation_prompt(
    project_id: str | None,
    asset_type: str,
    asset: dict[str, Any],
    prompt: str | None = None,
    reference_image: dict[str, Any] | None = None,
    request_size: str | None = None,
    *,
    hide_turnaround_heads: bool = False,
) -> str:
    name = str(asset.get("name") or "未命名").strip() or "未命名"
    description = _asset_generation_description(asset_type, asset, prompt, project_id, reference_image)
    style, style_description = _asset_project_style(project_id, asset_type)
    if asset_type == "characters":
        result = _build_asset_character_prompt(
            name, description, style, style_description, _asset_project_text_language(project_id),
            hide_turnaround_heads=hide_turnaround_heads,
        )
        return append_image_request_prompt_instruction(result, request_size)
    if asset_type == "creatures":
        result = _build_asset_creature_prompt(name, description, style, style_description, _asset_project_text_language(project_id))
        return append_image_request_prompt_instruction(result, request_size)
    if asset_type == "scenes":
        result = _build_asset_scene_prompt(name, description, style, style_description)
        return append_image_request_prompt_instruction(result, request_size)
    if asset_type == "props":
        result = _build_asset_prop_prompt(name, description, style, style_description)
        return append_image_request_prompt_instruction(result, request_size)
    result = (
        f"{_asset_style_prefix(style, style_description)}"
        "【设计对象】\n"
        f"{_asset_type_label(asset_type)}「{name}」的设计参考。\n\n"
        f"{description}\n\n"
        f"{_ASSET_NEGATIVE_TAIL}"
    )
    return append_image_request_prompt_instruction(result, request_size)


def _asset_image_request_parameters(
    model: dict[str, Any],
    resolution: Any,
    aspect_ratio: str,
    *,
    has_reference_images: bool,
) -> tuple[Any, str, dict[str, Any], str]:
    from .provider_models import _image_output_size
    from .splitting_templates import _string_list
    normalized_resolution = normalize_image_resolution_for_schema(
        resolution,
        _string_list(model.get("resolutions")),
        str(model.get("default_resolution") or resolution or "2K"),
        image_resolution_schema_for_model(model),
        aspect_ratio,
        has_reference_images=has_reference_images,
    )
    size = _image_output_size(
        model,
        normalized_resolution,
        aspect_ratio,
        has_reference_images=has_reference_images,
    )
    request_plan = image_resolution_request_plan(
        model,
        normalized_resolution,
        aspect_ratio,
        size=size,
        has_reference_images=has_reference_images,
    )
    request_size_label = image_request_size_label(request_plan, size, normalized_resolution)
    return normalized_resolution, size, request_plan, request_size_label


def _call_asset_image_model(
    provider: dict[str, Any],
    provider_id: str,
    base_url: str,
    model_name: str,
    prompt: str,
    *,
    size: str,
    aspect_ratio: str,
    resolution: Any,
    reference_image: dict[str, Any] | None,
    reference_images: list[dict[str, Any]] | None = None,
    output_format: str | None,
    endpoint: str | None,
    max_reference_images: int | None,
    image_input_limits: dict[str, Any] | None,
    allow_landscape_retry: bool,
    cancel_event: threading.Event | None = None,
    on_request_prepared: RequestPreparedCallback | None = None,
) -> tuple[Any, bytes, dict[str, Any], dict[str, Any] | None]:
    from .agent_sessions import _persistent_media_data_removed
    def request_image(prompt_to_send: str) -> Any:
        return run_cancellable_model_request(
            lambda: generate_image_media(
                provider, provider_id, base_url, model_name, prompt_to_send,
                size=size, aspect_ratio=aspect_ratio, resolution=str(resolution or ""),
                reference_image=reference_image, reference_images=reference_images,
                output_format=output_format, endpoint=endpoint,
                max_reference_images=max_reference_images, image_input_limits=image_input_limits,
                on_request_prepared=on_request_prepared,
            ),
            lambda: _raise_if_asset_image_cancelled(cancel_event),
        )

    response = request_image(prompt)
    raw = response.raw
    if raw is None:
        raise RuntimeError("图片模型未返回可用图片数据")
    orientation_retry: dict[str, Any] | None = None
    if allow_landscape_retry:
        first_orientation = image_bytes_metadata(raw)
        if image_metadata_needs_landscape_retry(first_orientation):
            retry_prompt = append_image_landscape_retry_instruction(prompt)
            retry_response = request_image(retry_prompt)
            retry_raw = retry_response.raw
            if retry_raw is None:
                raise RuntimeError("图片模型横向构图重试未返回可用图片数据")
            retry_orientation = image_bytes_metadata(retry_raw)
            orientation_retry = {
                "reason": "non_landscape_output",
                "firstImage": first_orientation,
                "retryImage": retry_orientation,
                "promptStrengthened": True,
            }
            if image_metadata_needs_landscape_retry(retry_orientation):
                raise RuntimeError("图片模型连续返回非横向宽幅图片，已停止保存竖版/方图结果")
            response = retry_response
            raw = retry_raw
    debug = _persistent_media_data_removed(response.debug)
    if orientation_retry:
        debug = {
            **debug,
            "orientationRetry": orientation_retry,
        }
    return response, raw, debug, orientation_retry


def _asset_image_generation_source(
    asset: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, bool]:
    source_asset = copy.deepcopy(asset)
    selected = asset.get("referenceMedia")
    source_media = selected if isinstance(selected, dict) and selected else None
    edit_original = uses_original_image_reference(source_media, asset.get("referenceMediaRole"))
    source_asset.pop("media", None)
    return source_asset, source_media, edit_original


def _generate_asset_image_media(
    project_id: str | None,
    asset_type: str,
    asset: dict[str, Any],
    prompt: str | None = None,
    *,
    hide_turnaround_heads: bool = False,
    task_id: str | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    from .provider_models import _image_output_source_mime
    from .provider_models import _is_connected_provider
    from .provider_models import _model_generation_endpoint
    from .provider_models import _model_reference_image_input_limits
    from .provider_models import _normalize_provider_id
    from .provider_models import _provider_supports_direct_media_generation
    from .provider_models import _resolve_image_output_format
    from .media_files import _save_project_image_media_file
    from .splitting_templates import _string_list
    _raise_if_asset_image_cancelled(cancel_event)
    if not project_id:
        raise ValueError("生成资产设计图需要项目 ID")
    _raise_if_asset_generation_prompt_override(prompt)
    provider, model, model_config = _configured_media_model(project_id, "image")
    if not provider or not model or not _is_connected_provider(provider):
        raise RuntimeError("图片模型供应商未连接")
    base_url = _provider_base_url(provider)
    if not base_url:
        raise RuntimeError("图片供应商 Base URL 为空")
    provider_id = _normalize_provider_id(provider.get("id"))
    model_name = _api_model_name(model.get("id"))
    image_config = model_config.get("image", {}) if isinstance(model_config.get("image"), dict) else {}
    project_config = get_effective_config(project_id)
    endpoint = _model_generation_endpoint(provider, model)
    if not _provider_supports_direct_media_generation(provider, "image", model):
        raise RuntimeError(f"当前图片供应商 {provider_id or 'unknown'} 暂未接入 ai-video 资产直接出图适配")
    image_input_limits = _model_reference_image_input_limits(model)
    asset, source_media, edit_original = _asset_image_generation_source(asset)
    max_reference_images = validate_image_model_inputs(
        model, image_edit=edit_original, reference_count=1 if source_media else 0,
    )
    reference_image = _provider_reference_image_from_media(
        project_id, source_media,
        purpose=f"asset-{asset_type}-primary-reference",
        image_input_limits=image_input_limits,
    ) if source_media else None
    if source_media and not reference_image:
        raise ValueError("所选原图或参考图无法读取，请重新上传后重试")
    if asset_type == "characters" and not edit_original:
        _raise_if_character_visual_prompt_incomplete(asset, prompt, project_id, reference_image)
    desired_asset_aspect_ratio = _asset_generation_aspect_ratio(asset_type, project_config.get("aspect_ratio"))
    if edit_original and source_media.get("width") and source_media.get("height"):
        desired_asset_aspect_ratio = f"{source_media['width']}:{source_media['height']}"
    asset_aspect_ratio = resolve_image_aspect_ratio_for_model(
        model,
        desired_asset_aspect_ratio,
        fallback_aspect_ratio="16:9",
        options=_string_list(model.get("resolutions")),
        has_reference_images=bool(reference_image),
    )
    asset_resolution = _asset_generation_resolution(image_config, asset_type)
    output_format = _resolve_image_output_format(image_config, model)
    asset_resolution, size, request_plan, request_size_label = _asset_image_request_parameters(
        model,
        asset_resolution,
        asset_aspect_ratio,
        has_reference_images=bool(reference_image),
    )
    if edit_original:
        instruction = _asset_design_prompt_from_asset(asset) or str(asset.get("desc") or "").strip()
        if not instruction:
            raise ValueError("请先填写并保存设计图修改要求")
        head_visibility = ""
        if asset_type == "characters":
            head_requirement = (
                _ASSET_CHARACTER_HEADLESS_TURNAROUND
                if hide_turnaround_heads
                else _ASSET_CHARACTER_HEADED_TURNAROUND
            )
            head_visibility = f"【三视图显示要求】\n{head_requirement}\n\n"
        final_prompt = (
            "以所提供的原图为编辑基础，仅修改本次要求涉及的内容；"
            "未要求修改的身份、造型、版式与构图保持不变。\n\n"
            f"【本次修改要求】\n{instruction}\n\n"
            f"{head_visibility}"
            f"【输出参数】\n分辨率：{request_size_label}；宽高比：{asset_aspect_ratio}。"
        )
    else:
        final_prompt = _asset_generation_prompt(
            project_id, asset_type, asset, prompt, reference_image,
            request_size=request_size_label,
            hide_turnaround_heads=hide_turnaround_heads,
        )
    from .model_request_logs import STAGE_ASSET_IMAGE_GENERATION_REQUEST, model_request_log_reference, write_model_request_log

    request_logs: list[dict[str, Any]] = []
    request_log_errors: list[str] = []

    def log_asset_image_request(request_info: dict[str, Any]) -> None:
        result = write_model_request_log(
            project_id, STAGE_ASSET_IMAGE_GENERATION_REQUEST, request_info,
            task_id=str(task_id or ""), node_id=str(asset.get("id") or ""),
            phase=asset_type, provider_id=provider_id, model_name=model_name,
            endpoint=str(endpoint or ""), source="_generate_asset_image_media",
        )
        if result.get("success"):
            request_logs.append(model_request_log_reference(result, phase=asset_type))
        else:
            request_log_errors.append(str(result.get("error") or "日志写入失败"))

    response, raw, debug, orientation_retry = _call_asset_image_model(
        provider,
        provider_id,
        base_url,
        model_name,
        final_prompt,
        size=size,
        aspect_ratio=asset_aspect_ratio,
        resolution=asset_resolution,
        reference_image=reference_image,
        reference_images=None,
        output_format=output_format,
        endpoint=endpoint,
        max_reference_images=max_reference_images,
        image_input_limits=image_input_limits,
        allow_landscape_retry=not edit_original,
        cancel_event=cancel_event,
        on_request_prepared=log_asset_image_request,
    )
    debug = {
        **debug,
        "modelRequestLogs": request_logs,
        "modelRequestLogErrors": request_log_errors,
        "primaryReferenceRole": asset.get("referenceMediaRole") if source_media else None,
        "imageOperation": "edit" if edit_original else "generate",
        "hideTurnaroundHeads": asset_type == "characters" and hide_turnaround_heads,
        "targetImageParameters": {
            "kind": {
                "characters": "character",
                "scenes": "scene",
                "props": "prop",
            }.get(asset_type, "asset"),
            "desiredAspectRatio": desired_asset_aspect_ratio,
            "aspectRatio": asset_aspect_ratio,
            "resolution": str(asset_resolution or ""),
            "size": size,
            "request": request_plan,
            "aspectRatioAdaptation": {
                "desired": desired_asset_aspect_ratio,
                "request": asset_aspect_ratio,
                "appliedBeforeRequest": desired_asset_aspect_ratio != asset_aspect_ratio,
            },
        },
        "imageResolutionRequest": request_plan,
        "referenceInputLimits": image_input_limits,
    }
    media_id = f"asset-{asset_type}-{asset.get('id') or uuid.uuid4().hex[:8]}-{uuid.uuid4().hex[:8]}"
    _raise_if_asset_image_cancelled(cancel_event)
    if task_id:
        from .task_control import _begin_task_result_commit

        # File and asset-record writes share the same non-cancellable commit boundary.
        if not _begin_task_result_commit(task_id, message="正在保存资产图。"):
            raise _AssetImageTaskCancelled(_asset_image_cancel_message())
    media = _save_project_image_media_file(
        project_id,
        raw,
        media_id=media_id,
        subdir="generated",
        original_name=f"{media_id}.png",
        source_mime=str(debug.get("mimeType") or _image_output_source_mime(output_format)),
    )
    debug = {
        **debug,
        "actualImageParameters": image_resolution_actual_report(media, request_plan),
    }
    return {
        **media,
        "source": "model-asset-image-generation",
        "model": model.get("id"),
        "provider": provider_id,
        "generationDebug": debug,
    }


def _asset_image_task_focus_target(asset_type: str, asset_id: str) -> dict[str, Any]:
    section = asset_type if asset_type in {"characters", "creatures", "scenes", "props"} else "characters"
    return {"section": section, "assetTab": asset_type, "nodeId": asset_id}


def _asset_image_task_message(
    asset_type: str,
    asset_name: str,
    status: str,
    error: str | None = None,
) -> str:
    label = _asset_type_label(asset_type)
    name = str(asset_name or "").strip() or "未命名资产"
    if status == "running":
        return f"{label}「{name}」设计图正在生成。"
    if status == "created":
        return f"{label}「{name}」设计图已进入后台任务。"
    if status == "failed":
        detail = f"：{_asset_task_error_text(error or '', 160)}" if error else ""
        return f"{label}「{name}」设计图生成失败{detail}"
    return f"{label}「{name}」设计图生成成功。"


def _asset_task_error_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "").strip()
    if not text or text == "NoneType: None":
        return ""
    text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,}\]]+", r"\1<redacted>", text)
    text = re.sub(
        r"(?i)((?:api[_-]?key|apiKey|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+",
        r"\1<redacted>",
        text,
    )
    if len(text) > limit:
        return f"{text[:limit].rstrip()}...（已截断）"
    return text


def _asset_task_failure_fields(reason: Any, traceback_text: str = "") -> dict[str, Any]:
    failure_reason = _asset_task_error_text(reason, 3000)
    debug_text = _asset_task_error_text(traceback_text, 6000)
    fields: dict[str, Any] = {
        "failureReason": failure_reason,
        "errorSummary": failure_reason,
        "error": failure_reason,
        "providerResponseSummary": failure_reason,
    }
    if debug_text:
        fields["errorDebug"] = debug_text
    return fields


class _AssetImageTaskCancelled(RuntimeError):
    pass


def _asset_image_cancel_message() -> str:
    return "已取消"


def _raise_if_asset_image_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event and cancel_event.is_set():
        raise _AssetImageTaskCancelled(_asset_image_cancel_message())


def _asset_turnaround_head_setting(
    asset_type: str,
    asset: dict[str, Any],
    override: bool | None,
) -> bool:
    if asset_type != "characters":
        return False
    if override is None:
        return asset.get("hideTurnaroundHeads") is True
    if not isinstance(override, bool):
        raise ValueError("三视图头部设置必须为布尔值")
    return override


def _find_asset_image_source_row(
    asset_type: str,
    asset_id: str,
    asset_scope: str,
    project_id: str | None,
) -> dict[str, Any]:
    if asset_scope == "global" or not project_id:
        raise ValueError("全局资产库不支持生成设计图，请在项目资产中操作")
    assets = list_assets(asset_scope, project_id, hydrate=False)
    if asset_type not in assets:
        raise ValueError("资产类型无效")
    for item in assets[asset_type]:
        if item.get("id") == asset_id:
            if _asset_is_offline(item):
                raise ValueError("下线资产不参与视频工作流，请先恢复到活跃组")
            return item
    raise FileNotFoundError("资产不存在")


def _active_asset_image_task(project_id: str, asset_type: str, asset_id: str) -> dict[str, Any] | None:
    from .task_storage import _load_tasks_for_project

    for task in reversed(_load_tasks_for_project(project_id)):
        if task.get("type") != "asset_image":
            continue
        if task.get("projectId") != project_id:
            continue
        if task.get("assetType") != asset_type:
            continue
        if str(task.get("assetId") or task.get("nodeId") or "") != str(asset_id):
            continue
        if task.get("status") not in {"created", "running"}:
            continue
        thread = _ASSET_IMAGE_TASK_THREADS.get(str(task.get("id") or ""))
        if thread:
            return task
    return None


def _report_asset_image_session_task(task: dict[str, Any] | None, *, success: bool) -> None:
    if not isinstance(task, dict):
        return
    try:
        from . import task_events as _task_events_services

        reporter = getattr(_task_events_services, "_maybe_report_agent_bound_generation_task", None)
        if callable(reporter):
            reporter(task, success=success)
    except Exception:
        print(traceback.format_exc(), flush=True)


def _run_asset_media_generation_task(
    task_id: str,
    asset_type: str,
    asset_id: str,
    asset_scope: str,
    project_id: str,
    prompt: str | None,
    cancel_event: threading.Event | None = None,
    hide_turnaround_heads: bool = False,
) -> None:
    from .store_core import _display_time
    from .task_control import _get_task
    from .task_control import _update_asset_image_task
    task = _get_task(task_id)
    asset_name = str((task or {}).get("assetName") or "").strip()
    try:
        if not task:
            return
        _raise_if_asset_image_cancelled(cancel_event)
        asset_name = asset_name or str(task.get("nodeId") or asset_id)
        task = _update_asset_image_task(
            task_id,
            status="running",
            progress=8,
            message=_asset_image_task_message(asset_type, asset_name, "running"),
        )
        if not task:
            return
        _raise_if_asset_image_cancelled(cancel_event)
        result = generate_asset_media(
            asset_type,
            asset_id,
            asset_scope,
            project_id,
            prompt,
            hide_turnaround_heads=hide_turnaround_heads,
            task_id=task_id,
            cancel_event=cancel_event,
        )
        task = result.get("task") if isinstance(result, dict) else None
        _emit_agent_event(
            "project_changed",
            {
                "action": "asset_media_generated",
                "projectId": project_id,
                "assetType": asset_type,
                "assetId": asset_id,
                "asset": copy.deepcopy(result.get("asset")) if isinstance(result.get("asset"), dict) else None,
                "changedResources": _asset_write_changed_resources(asset_type),
            },
        )
        if isinstance(task, dict):
            changed_resources = _asset_write_changed_resources(asset_type)
            _emit_agent_event(
                "agent_project_effect",
                {
                    "action": "asset_media_generated",
                    "projectId": project_id,
                    "assetType": asset_type,
                    "assetId": asset_id,
                    "assetName": asset_name,
                    "asset": copy.deepcopy(result.get("asset")) if isinstance(result.get("asset"), dict) else None,
                    "changedResources": changed_resources,
                    "focusTarget": _asset_image_task_focus_target(asset_type, asset_id),
                    "notice": task.get("notice") or task.get("message"),
                },
            )
            _report_asset_image_session_task(task, success=True)
    except _AssetImageTaskCancelled:
        message = _asset_image_cancel_message()
        task = _update_asset_image_task(
            task_id,
            preferred_event="task_cancelled",
            status="cancelled",
            progress=0,
            message=message,
            notice=message,
            cancelledAt=_display_time(_now()),
            changedResources=["canvas_task"],
        )
        _report_asset_image_session_task(task, success=False)
    except Exception as exc:
        traceback_text = traceback.format_exc()
        print(traceback_text, flush=True)
        reason = str(exc) or exc.__class__.__name__
        message = _asset_image_task_message(asset_type, asset_name or asset_id, "failed", reason)
        task = _update_asset_image_task(
            task_id,
            status="failed",
            progress=0,
            message=message,
            notice=message,
            **_asset_task_failure_fields(reason, traceback_text),
        )
        _report_asset_image_session_task(task, success=False)
    finally:
        with _LOCK:
            _ASSET_IMAGE_TASK_THREADS.pop(task_id, None)
            _ASSET_IMAGE_TASK_CANCEL_FLAGS.pop(task_id, None)


def start_asset_media_generation(
    asset_type: str,
    asset_id: str,
    asset_scope: str = "project",
    project_id: str | None = None,
    prompt: str | None = None,
    *,
    hide_turnaround_heads: bool | None = None,
    episode_ids: list[str] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    from .task_control import _update_asset_image_task
    from .task_control import _update_task_fields
    from .task_control import create_task
    item = _find_asset_image_source_row(asset_type, asset_id, asset_scope, project_id)
    hide_turnaround_heads = _asset_turnaround_head_setting(asset_type, item, hide_turnaround_heads)
    asset_name = str(item.get("name") or item.get("title") or "").strip() or str(asset_id)
    _raise_if_asset_generation_prompt_override(prompt)
    source_asset, _, edit_original = _asset_image_generation_source(item)
    if asset_type == "characters" and not edit_original:
        _raise_if_character_visual_prompt_incomplete(source_asset, prompt, project_id)
    from .task_contract import _task_agent_session_fields
    from utils.agent_execution_state import current_execution_id, require_task_execution
    from .task_storage import _TASK_STORAGE_LOCK

    normalized_episode_ids = [
        str(item or "").strip()
        for item in (episode_ids or [])
        if str(item or "").strip()
    ]
    session_fields = _task_agent_session_fields(session_id)
    with _TASK_STORAGE_LOCK:
        active_task = _active_asset_image_task(str(project_id or ""), asset_type, asset_id)
        if active_task:
            requested_session_id = session_fields.get("sessionId", "")
            if requested_session_id:
                require_task_execution(active_task, requested_session_id, current_execution_id(requested_session_id))
            task = active_task
        else:
            task = create_task(
                "asset_image",
                project_id=project_id,
                node_id=asset_id,
                message=_asset_image_task_message(asset_type, asset_name, "created"),
                status="running",
                progress=3,
                task_fields=session_fields,
            )
            task = _update_task_fields(
                task["id"],
                assetType=asset_type,
                assetId=asset_id,
                assetName=asset_name,
                hideTurnaroundHeads=asset_type == "characters" and hide_turnaround_heads,
                **({"episodeId": normalized_episode_ids[0]} if len(normalized_episode_ids) == 1 else {}),
                **({"episodeIds": normalized_episode_ids} if normalized_episode_ids else {}),
                **session_fields,
                focusTarget=_asset_image_task_focus_target(asset_type, asset_id),
                notice=_asset_image_task_message(asset_type, asset_name, "created"),
            ) or task
    from .agent_sessions import _bind_agent_execution_task
    if not active_task or session_fields:
        _bind_agent_execution_task(str(project_id or ""), task)
    if active_task:
        return {
            "success": True,
            "backgroundStarted": True,
            "message": active_task.get("message") or _asset_image_task_message(asset_type, asset_name, "running"),
            "task": active_task,
            "tasks": [active_task],
        }
    cancel_event = threading.Event()
    thread = threading.Thread(
        target=_run_asset_media_generation_task,
        args=(
            task["id"],
            asset_type,
            asset_id,
            asset_scope,
            str(project_id or ""),
            prompt,
            cancel_event,
            hide_turnaround_heads,
        ),
        name=f"ai-video-asset-image-{task['id']}",
        daemon=True,
    )
    with _LOCK:
        _ASSET_IMAGE_TASK_THREADS[task["id"]] = thread
        _ASSET_IMAGE_TASK_CANCEL_FLAGS[task["id"]] = cancel_event
    _emit_agent_event("task_created", task)
    try:
        thread.start()
    except Exception as exc:
        traceback_text = traceback.format_exc()
        print(traceback_text, flush=True)
        with _LOCK:
            _ASSET_IMAGE_TASK_THREADS.pop(task["id"], None)
            _ASSET_IMAGE_TASK_CANCEL_FLAGS.pop(task["id"], None)
        reason = str(exc) or exc.__class__.__name__
        message = _asset_image_task_message(asset_type, asset_name, "failed", reason)
        task = _update_asset_image_task(
            task["id"],
            status="failed",
            progress=0,
            message=message,
            notice=message,
            **_asset_task_failure_fields(reason, traceback_text),
        ) or task
        _report_asset_image_session_task(task, success=False)
    return {
        "success": task.get("status") not in {"failed", "cancelled", "canceled"},
        "backgroundStarted": task.get("status") in {"created", "running"},
        "message": task.get("message") or _asset_image_task_message(asset_type, asset_name, "created"),
        "task": task,
        "tasks": [task],
    }


def generate_asset_media(
    asset_type: str,
    asset_id: str,
    asset_scope: str = "project",
    project_id: str | None = None,
    prompt: str | None = None,
    *,
    hide_turnaround_heads: bool | None = None,
    task_id: str | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    from .task_control import _emit_task_update
    from .agent_sessions import _hydrate_asset_row_for_ui
    from .agent_sessions import _hydrate_media_asset_for_ui
    from .projects import _touch_project_meta
    from .task_control import _update_task_fields
    from .task_control import create_task
    _raise_if_asset_image_cancelled(cancel_event)
    _raise_if_asset_generation_prompt_override(prompt)
    if asset_scope == "global" or not project_id:
        raise ValueError("全局资产库不支持生成设计图，请在项目资产中操作")
    assets = list_assets(asset_scope, project_id, hydrate=False)
    if asset_type not in assets:
        raise ValueError("资产类型无效")
    source_item: dict[str, Any] | None = None
    for item in assets[asset_type]:
        if item.get("id") != asset_id:
            continue
        if _asset_is_offline(item):
            raise ValueError("下线资产不参与视频工作流，请先恢复到活跃组")
        source_item = copy.deepcopy(item)
        break
    if source_item is None:
        raise FileNotFoundError("资产不存在")

    hide_turnaround_heads = _asset_turnaround_head_setting(asset_type, source_item, hide_turnaround_heads)
    _raise_if_asset_image_cancelled(cancel_event)
    generated_media = _generate_asset_image_media(
        project_id, asset_type, source_item, prompt, task_id=task_id, cancel_event=cancel_event,
        hide_turnaround_heads=hide_turnaround_heads,
    )
    _raise_if_asset_image_cancelled(cancel_event)
    media = (
        _normalize_media_asset(project_id, generated_media)
        if asset_scope == "project" and project_id
        else generated_media
    )
    with _LOCK:
        _raise_if_asset_image_cancelled(cancel_event)
        latest_assets = list_assets(asset_scope, project_id, hydrate=False)
        if asset_type not in latest_assets:
            raise ValueError("资产类型无效")
        target_item: dict[str, Any] | None = None
        for item in latest_assets[asset_type]:
            if item.get("id") == asset_id:
                target_item = item
                break
        if target_item is None:
            raise FileNotFoundError("资产不存在")
        if _asset_is_offline(target_item):
            raise ValueError("下线资产不参与视频工作流，请先恢复到活跃组")
        versions = _ensure_asset_media_versions(target_item)
        next_version = len(versions) + 1
        target_item["version"] = f"v{next_version}"
        target_item["media"] = media
        media_version = _asset_media_version(
            media,
            f"v{next_version} 模型生成图",
            snapshot=target_item,
        )
        if media_version:
            versions.append(media_version)
            target_item["mediaVersions"] = versions
            target_item["activeMediaVersionId"] = media_version["id"]
        _write_json(_asset_store_path(asset_scope, project_id), latest_assets)
        if asset_scope == "project":
            _touch_project_meta(project_id)
        stored_item = copy.deepcopy(target_item)
        asset_name = str(stored_item.get("name") or stored_item.get("title") or "").strip() or str(asset_id)
        message = _asset_image_task_message(asset_type, asset_name, "completed")
        if task_id:
            now_ms = int(datetime.now().timestamp() * 1000)
            task = _update_task_fields(
                task_id,
                status="completed",
                progress=100,
                message=message,
                notice=message,
                assetType=asset_type,
                assetId=asset_id,
                assetName=asset_name,
                hideTurnaroundHeads=asset_type == "characters" and hide_turnaround_heads,
                focusTarget=_asset_image_task_focus_target(asset_type, asset_id),
                completedAt=now_ms,
                updatedAt=now_ms,
            )
        else:
            task = create_task(
                "asset_image",
                project_id=project_id,
                node_id=asset_id,
                message=message,
                status="completed",
                progress=100,
            )
            task = _update_task_fields(
                task["id"],
                assetType=asset_type,
                assetId=asset_id,
                assetName=asset_name,
                hideTurnaroundHeads=asset_type == "characters" and hide_turnaround_heads,
                focusTarget=_asset_image_task_focus_target(asset_type, asset_id),
                notice=message,
            ) or task
    response_asset = _hydrate_asset_row_for_ui(project_id, stored_item) if asset_scope == "project" and project_id else stored_item
    response_media = _hydrate_media_asset_for_ui(project_id, media) if asset_scope == "project" and project_id else media
    if isinstance(task, dict):
        task_result = {
            "assetType": asset_type,
            "assetId": asset_id,
            "asset": copy.deepcopy(response_asset),
            "media": copy.deepcopy(response_media),
        }
        task = _update_task_fields(
            task["id"],
            result=task_result,
            updatedAt=int(datetime.now().timestamp() * 1000),
        ) or {**task, "result": task_result}
    if task_id:
        _emit_task_update(task, "task_completed")
    result = {"success": True, "asset": response_asset, "media": response_media, "task": task}
    result["changedResources"] = _asset_write_changed_resources(asset_type)
    return result

__all__ = (
    'list_assets', '_normalize_global_asset_item_for_storage', '_normalize_media_asset',
    '_normalize_asset_item_for_storage', '_asset_store_path', '_asset_version_snapshot',
    '_asset_version_state_changed', '_asset_media_version', '_ensure_asset_media_versions',
    '_asset_source_order_for_project', '_sort_asset_rows_by_source_order',
    '_asset_payload_has_design_prompt', '_asset_name_key', '_find_asset_index_by_name',
    '_project_asset_media_paths', '_delete_project_asset_media_files', '_collect_plan_asset_refs',
    '_project_storyboard_asset_refs', '_project_asset_is_referenced', '_apply_asset_design_prompt_patch',
    'create_asset', 'update_asset', 'delete_asset', 'delete_all_project_assets', 'set_active_asset_media_version',
    'update_asset_media_version', 'delete_asset_media_version', '_asset_type_label', '_default_asset_design_prompt',
    '_ensure_asset_design_prompt_for_storage', '_ASSET_IMAGE_PROMPT_KEYS', '_ASSET_CHARACTER_LAYOUT',
    '_ASSET_CHARACTER_PROP_RULE', '_ASSET_SCENE_LAYOUT', '_ASSET_PROP_LAYOUT', '_ASSET_CHARACTER_GUARD',
    '_ASSET_CHARACTER_PRESENTATION_GUIDE', '_ASSET_SCENE_GUARD', '_ASSET_PROP_GUARD',
    '_ASSET_NEGATIVE_TAIL_CHARACTER', '_ASSET_NEGATIVE_TAIL', '_asset_mapping_text',
    '_asset_design_prompt_from_asset', '_asset_style_prefix', '_asset_project_style',
    '_asset_generation_description', '_build_asset_character_prompt', '_build_asset_scene_prompt',
    '_build_asset_prop_prompt', '_asset_generation_aspect_ratio', '_asset_generation_resolution',
    '_asset_generation_prompt', '_character_visual_prompt_is_complete',
    '_raise_if_character_visual_prompt_incomplete', '_raise_if_asset_generation_prompt_override',
    '_generate_asset_image_media', '_asset_image_task_focus_target',
    '_asset_image_task_message', '_AssetImageTaskCancelled', '_asset_image_cancel_message',
    '_raise_if_asset_image_cancelled', '_find_asset_image_source_row', '_active_asset_image_task',
    '_run_asset_media_generation_task', 'start_asset_media_generation', 'generate_asset_media'
)
