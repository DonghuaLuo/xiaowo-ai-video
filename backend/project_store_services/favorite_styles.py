# -*- coding: utf-8 -*-
"""收藏风格模板的创建、删除、更新和风格图上传入口。"""

from __future__ import annotations

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
    parse_aspect_ratio,
    resolution_to_short_edge,
)
from utils.image_pipeline import (
    convert_image_bytes_to_png,
    data_url_from_bytes,
    prepare_provider_image_bytes,
    prepare_provider_image_data_uri,
    save_project_image,
    save_provider_output_image,
)
from utils.media_backends import (
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

from .catalogs import FAVORITE_STYLE_THUMBNAILS_DIR
from .catalogs import GLOBAL_STYLE_TEMPLATES_PATH
from .store_core import _now
from .store_core import _read_json
from .store_core import _serialized_project_config_write
from .store_core import _write_json
from .store_core import ensure_store

pass  # 此处未使用任务 API。  # noqa: F401,F403

def _favorite_style_name_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _find_favorite_style_index_by_name(templates: list[dict[str, Any]], name: str) -> int | None:
    target = _favorite_style_name_key(name)
    if not target:
        return None
    for index, item in enumerate(templates):
        if item.get("category") != "favorite":
            continue
        if _favorite_style_name_key(item.get("name")) == target:
            return index
    return None


def _favorite_style_prompt_value(payload: dict[str, Any], existing: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key in payload:
            return str(payload.get(key) or "").strip()
    for key in keys:
        if key in existing:
            return str(existing.get(key) or "").strip()
    return ""


def _favorite_style_asset_prompt_fields(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, str]:
    existing = existing if isinstance(existing, dict) else {}
    return {
        "character_asset_prompt": _favorite_style_prompt_value(
            payload,
            existing,
            "characterAssetPrompt",
            "character_asset_prompt",
            "characterStylePrompt",
            "character_style_prompt",
        ),
        "creature_asset_prompt": _favorite_style_prompt_value(
            payload,
            existing,
            "creatureAssetPrompt",
            "creature_asset_prompt",
            "creatureStylePrompt",
            "creature_style_prompt",
        ),
    }


def create_favorite_style_template(payload: dict[str, Any]) -> dict[str, Any]:
    from .projects import _favorite_style_thumbnail_path
    from .media_files import _has_image_file_input
    from .projects import _is_path_within
    from .media_files import _save_favorite_style_thumbnail
    from .settings_loaders import load_style_templates
    ensure_store()
    templates = load_style_templates()
    name = str(payload.get("name") or "收藏风格").strip() or "收藏风格"
    prompt = str(payload.get("prompt") or payload.get("stylePrompt") or "").strip()
    if not prompt:
        raise ValueError("请先输入风格提示词")
    style_file = payload.get("styleFile") or payload.get("style_file")
    if not isinstance(style_file, dict) or not _has_image_file_input(style_file):
        raise ValueError("请上传风格图片")
    overwrite = bool(payload.get("overwrite"))
    duplicate_index = _find_favorite_style_index_by_name(templates, name)
    if duplicate_index is not None and not overwrite:
        return {
            "success": False,
            "code": "duplicate_name",
            "message": f"收藏风格「{name}」已存在",
            "duplicate": templates[duplicate_index],
        }
    existing = templates[duplicate_index] if duplicate_index is not None else {}
    template_id = str(existing.get("id") or f"favorite_{uuid.uuid4().hex[:8]}")
    old_path = _favorite_style_thumbnail_path(existing) if existing else None
    thumbnail = _save_favorite_style_thumbnail(template_id, style_file)
    now = _now()
    item = {
        "id": template_id,
        "name": name,
        "desc": str(payload.get("desc") or "").strip(),
        "category": "favorite",
        "categoryLabel": "风格收藏",
        "accent": payload.get("accent")
        or existing.get("accent")
        or "from-slate-600 via-sky-500 to-violet-500",
        **thumbnail,
        "prompt": prompt,
        "asset_prompt": prompt,
        **_favorite_style_asset_prompt_fields(payload, existing),
        "source": "favorite",
        "createdAt": existing.get("createdAt") or now,
        "updatedAt": now,
    }
    if duplicate_index is not None:
        templates[duplicate_index] = item
        next_path = _favorite_style_thumbnail_path(item)
        if (
            old_path
            and next_path
            and old_path != next_path
            and _is_path_within(old_path, FAVORITE_STYLE_THUMBNAILS_DIR)
            and old_path.exists()
        ):
            old_path.unlink()
    else:
        templates.append(item)
    _write_json(GLOBAL_STYLE_TEMPLATES_PATH, templates)
    return {"success": True, "template": item}


def delete_favorite_style_template(template_id: str) -> dict[str, Any]:
    from .projects import _favorite_style_thumbnail_path
    from .projects import _is_path_within
    from .settings_loaders import load_style_templates
    templates = load_style_templates()
    deleted_items = [
        item
        for item in templates
        if item.get("id") == template_id and item.get("category") == "favorite"
    ]
    templates = [
        item
        for item in templates
        if not (item.get("id") == template_id and item.get("category") == "favorite")
    ]
    for item in deleted_items:
        path = _favorite_style_thumbnail_path(item)
        if path and _is_path_within(path, FAVORITE_STYLE_THUMBNAILS_DIR) and path.exists():
            path.unlink()
    _write_json(GLOBAL_STYLE_TEMPLATES_PATH, templates)
    return {"success": True}


def update_favorite_style_template(payload: dict[str, Any]) -> dict[str, Any]:
    from .projects import _favorite_style_thumbnail_path
    from .media_files import _has_image_file_input
    from .projects import _is_path_within
    from .media_files import _save_favorite_style_thumbnail
    from .settings_loaders import load_style_templates
    ensure_store()
    template_id = str(payload.get("templateId") or payload.get("template_id") or "").strip()
    if not template_id:
        raise ValueError("收藏风格 ID 不能为空")
    templates = load_style_templates()
    for index, item in enumerate(templates):
        if item.get("id") != template_id or item.get("category") != "favorite":
            continue
        name = str(payload.get("name") or item.get("name") or "").strip()
        prompt = str(payload.get("prompt") or payload.get("stylePrompt") or item.get("prompt") or "").strip()
        if not name:
            raise ValueError("收藏风格名称不能为空")
        if not prompt:
            raise ValueError("收藏风格提示词不能为空")
        updated = copy.deepcopy(item)
        updated["name"] = name
        updated["desc"] = str(payload.get("desc") if "desc" in payload else item.get("desc") or "")
        updated["prompt"] = prompt
        updated["asset_prompt"] = prompt
        updated.update(_favorite_style_asset_prompt_fields(payload, item))
        updated["updatedAt"] = _now()
        style_file = payload.get("styleFile") or payload.get("style_file")
        if isinstance(style_file, dict) and _has_image_file_input(style_file):
            old_path = _favorite_style_thumbnail_path(updated)
            thumbnail = _save_favorite_style_thumbnail(template_id, style_file)
            updated.update(thumbnail)
            next_path = _favorite_style_thumbnail_path(updated)
            if (
                old_path
                and next_path
                and old_path != next_path
                and _is_path_within(old_path, FAVORITE_STYLE_THUMBNAILS_DIR)
                and old_path.exists()
            ):
                old_path.unlink()
        templates[index] = updated
        _write_json(GLOBAL_STYLE_TEMPLATES_PATH, templates)
        return {"success": True, "template": updated}
    raise ValueError("收藏风格不存在")


@_serialized_project_config_write
def upload_style_image(project_id: str, file_info: dict[str, Any], style_description: str = "") -> dict[str, Any]:
    from .agent_sessions import _project_config_path
    from .agent_sessions import _project_meta_path
    from .style_analysis import _save_style_reference
    style_ref = _save_style_reference(project_id, file_info, style_description)
    meta_path = _project_meta_path(project_id)
    meta = _read_json(meta_path, {})
    meta["style_reference"] = style_ref
    meta["updated_at"] = _now()
    _write_json(meta_path, meta)
    config_path = _project_config_path(project_id)
    config = _read_json(config_path, {})
    config.setdefault("style", {})["reference"] = style_ref
    if style_description:
        config["style"]["prompt"] = style_description
        config["style"]["asset_prompt"] = style_description
        config["style"]["character_asset_prompt"] = ""
        config["style"]["creature_asset_prompt"] = ""
    config["style"].pop("scene_asset_prompt", None)
    config["style"].pop("prop_asset_prompt", None)
    _write_json(config_path, config)
    return {"success": True, "style_reference": style_ref}

__all__ = (
    '_favorite_style_name_key', '_find_favorite_style_index_by_name', 'create_favorite_style_template',
    'delete_favorite_style_template', 'update_favorite_style_template', 'upload_style_image'
)
