# -*- coding: utf-8 -*-
"""项目配置构建、创建、导入、删除、项目设置和有效配置读取。"""

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


from .catalogs import ACCENTS
from .catalogs import CUSTOM_STYLE_REQUIRED_MESSAGE
from .catalogs import DEFAULT_ASSETS
from .catalogs import DEFAULT_ASSET_EXTRACTION_TARGET_UNITS
from .catalogs import DEFAULT_EPISODE_TARGET_UNITS
from .catalogs import DEFAULT_STYLE_TEMPLATES
from .catalogs import GENERAL_STYLE_TEMPLATE_ID
from .catalogs import GENERAL_VISUAL_TYPE_PROMPTS
from .catalogs import GENERAL_VISUAL_TYPE_TAGS
from .catalogs import GENERAL_VISUAL_TYPE_TAG_ALIASES
from .catalogs import MODEL_CONFIG_REQUIRED_MESSAGE
from .catalogs import PROJECTS_DIR
from .catalogs import PROJECT_NAME_EXISTS_MESSAGE
from .catalogs import SOURCE_LANGUAGE_OPTIONS
from .catalogs import _general_visual_type_style_prompt
from .catalogs import _normalize_style_phase_visual_context
from .catalogs import _normalize_style_phase_visuals
from .catalogs import _normalize_style_theme_visual_context
from .catalogs import _style_active_phase_visual_id_from_mapping
from .catalogs import _style_phase_visuals_from_mapping
from .runtime_state import _LOCK
from .store_core import _deep_merge
from .store_core import _now
from .store_core import _read_json
from .store_core import _serialized_project_config_write
from .store_core import _write_json
from .store_core import ensure_store

_STYLE_ASSET_PROMPT_KEYS = {
    "character": (
        "characterAssetPrompt",
        "character_asset_prompt",
        "characterStylePrompt",
        "character_style_prompt",
    ),
    "creature": (
        "creatureAssetPrompt",
        "creature_asset_prompt",
        "creatureStylePrompt",
        "creature_style_prompt",
    ),
}


def _style_prompt_value(source: dict[str, Any], *keys: str, fallback: str = "") -> str:
    for key in keys:
        if key in source:
            return str(source.get(key) or "").strip()
    return str(fallback or "").strip()


def _style_asset_prompt_value(source: dict[str, Any], asset_kind: str, fallback: str = "") -> str:
    return _style_prompt_value(
        source,
        *_STYLE_ASSET_PROMPT_KEYS.get(asset_kind, ()),
        fallback=fallback,
    )


def _project_favorite_style_snapshot(project_id: str, template: dict[str, Any]) -> dict[str, Any]:
    """Copy a global favorite style into the project before saving its selection."""
    from .projects import _favorite_style_thumbnail_path
    template_id = str(template.get("id") or "").strip()
    snapshot = copy.deepcopy(template)
    snapshot["sourceGlobalStyleId"] = template_id
    source_path = _favorite_style_thumbnail_path(template)
    if not source_path or not source_path.is_file():
        raise ValueError("收藏风格缺少可复制的本地缩略图")
    from .media_files import _copy_local_project_config_image_file, _mime_from_image_suffix

    copied = _copy_local_project_config_image_file(
        project_id,
        source_path,
        media_id=f"favorite-style-{template_id or uuid.uuid4().hex[:10]}",
        subdir="styles",
        original_name=source_path.name,
        source_mime=_mime_from_image_suffix(source_path),
    )
    for key in ("thumbnailFile", "thumbnail_file", "relativePath", "relative_path", "file"):
        snapshot.pop(key, None)
    snapshot["thumbnailPath"] = copied.get("path")
    snapshot["filePath"] = copied.get("path")
    snapshot["path"] = copied.get("path")
    snapshot["source"] = "project_favorite_snapshot"
    snapshot["category"] = "favorite"
    snapshot["categoryLabel"] = "风格收藏"
    return snapshot


def _delete_project_config_media_ref(project_id: str, snapshot: Any, subdir: str) -> None:
    from .projects import _is_path_within
    from .agent_sessions import _project_dir
    if not isinstance(snapshot, dict):
        return
    raw_path = str(snapshot.get("path") or "").strip()
    if not raw_path:
        return
    path = Path(raw_path).resolve()
    project_media_dir = (_project_dir(project_id) / "config_media" / subdir).resolve()
    if not _is_path_within(path, project_media_dir):
        return
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        return


def _delete_project_favorite_style_snapshot_media(project_id: str, snapshot: Any) -> None:
    _delete_project_config_media_ref(project_id, snapshot, "styles")


def _delete_project_cover_media(project_id: str, cover: Any) -> None:
    _delete_project_config_media_ref(project_id, cover, "covers")


def _project_snapshot_media_path(snapshot: Any) -> str:
    if not isinstance(snapshot, dict):
        return ""
    return str(snapshot.get("path") or "").strip()


def _is_general_style_template(style_template: dict[str, Any] | None) -> bool:
    if not isinstance(style_template, dict):
        return False
    return (
        str(style_template.get("id") or "") == GENERAL_STYLE_TEMPLATE_ID
        or str(style_template.get("category") or "") == "general"
    )


def _style_tag_options(style_template: dict[str, Any], key: str, fallback: list[str]) -> list[str]:
    value = style_template.get(key) or style_template.get(_camel_key(key))
    if isinstance(value, list):
        options = [str(item or "").strip() for item in value if str(item or "").strip()]
        if options:
            return options
    return list(fallback)


def _camel_key(key: str) -> str:
    parts = key.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _normalize_style_tag(value: Any, options: list[str], default_value: str = "") -> str:
    text = str(value or "").strip()
    if text in GENERAL_VISUAL_TYPE_TAG_ALIASES:
        text = GENERAL_VISUAL_TYPE_TAG_ALIASES[text]
    if text in options:
        return text
    return default_value if default_value in options else (options[0] if options else "")


def _normalize_visual_context(value: Any) -> str:
    return _normalize_style_theme_visual_context(value)


def _style_tag_value(source: dict[str, Any], *keys: str, fallback: str = "") -> str:
    for key in keys:
        if key in source:
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return str(fallback or "").strip()


def _general_style_visual_type_tag(
    style_template: dict[str, Any],
    source: dict[str, Any],
    existing_style: dict[str, Any] | None = None,
) -> str:
    existing_style = existing_style if isinstance(existing_style, dict) else {}
    visual_type_options = _style_tag_options(style_template, "visual_type_tags", GENERAL_VISUAL_TYPE_TAGS)
    default_visual_type = str(
        style_template.get("default_visual_type_tag")
        or style_template.get("defaultVisualTypeTag")
        or ""
    ).strip()
    visual_type_tag = _style_tag_value(
        source,
        "styleVisualTypeTag",
        "style_visual_type_tag",
        "visualTypeTag",
        "visual_type_tag",
        fallback=str(existing_style.get("visual_type_tag") or ""),
    )
    return _normalize_style_tag(visual_type_tag, visual_type_options, default_visual_type)


def _general_style_tag_prefix(visual_type_tag: str) -> str:
    visual_type_text = str(visual_type_tag or "").strip()
    visual_prompt = (
        GENERAL_VISUAL_TYPE_PROMPTS.get(visual_type_text)
        or (f"画面类型：{visual_type_text}。" if visual_type_text else "")
    )
    return visual_prompt


def _strip_general_style_tag_prefix(prompt: str) -> str:
    text = str(prompt or "").strip()
    labeled_prefix_match = re.match(r"^画面类型[:：]([^。]*)。\s*", text)
    if labeled_prefix_match and "统一美术风格" not in labeled_prefix_match.group(1):
        return text[len(labeled_prefix_match.group(0)):].lstrip(" \t\r\n，,；;。")
    for visual_type_tag in GENERAL_VISUAL_TYPE_TAGS:
        prefix = _general_style_tag_prefix(visual_type_tag)
        if not prefix:
            continue
        if text == prefix:
            return ""
        if text.startswith(prefix):
            return text[len(prefix):].lstrip(" \t\r\n，,；;。")
    return text


def _with_general_style_tag_prefix(prompt: str, visual_type_tag: str) -> str:
    raw_text = str(prompt or "").strip()
    if raw_text.startswith("画面类型：") and "统一美术风格" in raw_text:
        return raw_text
    text = _strip_general_style_tag_prefix(prompt)
    prefix = _general_style_tag_prefix(visual_type_tag)
    if not prefix:
        return text
    if not text:
        return prefix
    if text == prefix or text.startswith(prefix):
        return text
    return f"{prefix}{text}"


def _general_style_prompt(prompt: str, visual_type_tag: str, field: str = "asset_prompt") -> str:
    preset_prompt = _general_visual_type_style_prompt(visual_type_tag, field)
    if preset_prompt:
        return preset_prompt
    return _with_general_style_tag_prefix(prompt, visual_type_tag)


def apply_theme_visual_context_to_config(config: dict[str, Any], theme_visual_context: Any) -> bool:
    from .projects import _find_template
    from .settings_loaders import load_style_templates
    if not isinstance(config, dict):
        return False
    context = _normalize_visual_context(theme_visual_context)
    if not context:
        return False
    style_config = config.get("style") if isinstance(config.get("style"), dict) else {}
    if not isinstance(style_config, dict):
        style_config = {}
    config["style"] = style_config
    config["theme_visual_context"] = context
    style_config.pop("theme_visual_context", None)
    style_config.pop("scene_asset_prompt", None)
    style_config.pop("prop_asset_prompt", None)

    style_template_id = str(config.get("style_template_id") or "").strip()
    style_template = _find_template(style_template_id, load_style_templates()) if style_template_id else None
    if not _is_general_style_template(style_template):
        return True

    visual_type_tag = _general_style_visual_type_tag(style_template, {}, style_config)
    style_config["visual_type_tag"] = visual_type_tag
    global_prompt = str(style_template.get("prompt") or "").strip()
    asset_prompt = str(
        style_template.get("asset_prompt")
        or style_template.get("assetPrompt")
        or global_prompt
    ).strip()
    style_config["prompt"] = _general_style_prompt(global_prompt, visual_type_tag, "prompt")
    style_config["asset_prompt"] = _general_style_prompt(asset_prompt, visual_type_tag, "asset_prompt")
    style_config["character_asset_prompt"] = _general_style_prompt(
        _style_asset_prompt_value(style_template, "character", fallback=asset_prompt),
        visual_type_tag,
        "character_asset_prompt",
    )
    style_config["creature_asset_prompt"] = _general_style_prompt(
        _style_asset_prompt_value(style_template, "creature", fallback=asset_prompt),
        visual_type_tag,
        "creature_asset_prompt",
    )
    return True


def apply_phase_visual_context_to_config(
    config: dict[str, Any],
    phase_id: Any,
    name: Any,
    phase_visual_context: Any,
    *,
    activate: bool = True,
) -> bool:
    if not isinstance(config, dict):
        return False
    context = _normalize_style_phase_visual_context(phase_visual_context)
    if not context:
        return False
    style_config = config.get("style") if isinstance(config.get("style"), dict) else {}
    if not isinstance(style_config, dict):
        style_config = {}
    config["style"] = style_config

    raw_id = str(phase_id or "").strip()
    item_id = re.sub(r"[^A-Za-z0-9_-]+", "-", raw_id).strip("-") or f"phase-visual-{uuid.uuid4().hex[:8]}"
    phase_visuals = _normalize_style_phase_visuals(style_config.get("phase_visuals"))
    name_text = re.sub(r"\s+", " ", str(name or "").strip()).strip("。；;，, ")
    if len(name_text) > 40:
        name_text = name_text[:40].rstrip("。；;，, ")
    if not name_text:
        name_text = "自动阶段视觉"

    updated = False
    for item in phase_visuals:
        if str(item.get("id") or "") != item_id:
            continue
        item["name"] = name_text
        item["prompt"] = context
        updated = True
        break
    if not updated:
        phase_visuals.append({"id": item_id, "name": name_text, "prompt": context})
    style_config["phase_visuals"] = phase_visuals
    if activate:
        style_config["active_phase_visual_id"] = item_id
    return True


def remove_phase_visual_context_from_config(config: dict[str, Any], phase_id: Any) -> bool:
    if not isinstance(config, dict):
        return False
    style_config = config.get("style") if isinstance(config.get("style"), dict) else {}
    if not isinstance(style_config, dict):
        return False
    item_id = re.sub(r"[^A-Za-z0-9_-]+", "-", str(phase_id or "").strip()).strip("-")
    if not item_id:
        return False
    phase_visuals = _normalize_style_phase_visuals(style_config.get("phase_visuals"))
    next_visuals = [item for item in phase_visuals if str(item.get("id") or "") != item_id]
    if len(next_visuals) == len(phase_visuals):
        return False
    style_config["phase_visuals"] = next_visuals
    if str(style_config.get("active_phase_visual_id") or "") == item_id:
        style_config["active_phase_visual_id"] = (
            str(next_visuals[-1].get("id") or "") if next_visuals else None
        )
    return True


def _build_project_config(
    payload: dict[str, Any],
    style_prompt: str,
    style_template_id: str | None,
    style_asset_prompt: str = "",
    character_asset_prompt: str = "",
    creature_asset_prompt: str = "",
    style_visual_type_tag: str = "",
    phase_visuals: list[dict[str, str]] | None = None,
    active_phase_visual_id: str | None = None,
) -> dict[str, Any]:
    from .settings_loaders import load_global_config
    from .storyboard_timing import DEFAULT_CLIP_MAX_SECONDS, DEFAULT_RHYTHM
    global_config = load_global_config()
    global_defaults = global_config["defaults"]
    content_mode = "drama"
    narrative_mode = str(payload.get("narrativeMode") or payload.get("narrative_mode") or "drama").strip()
    if narrative_mode != "drama":
        raise ValueError("旁白讲述模式尚未开放")
    project_config = {
        "pipeline_mode": "storyboard_video",
        "content_mode": content_mode,
        "narrative_mode": narrative_mode,
        "aspect_ratio": payload.get("aspectRatio") or payload.get("aspect_ratio") or global_defaults["aspect_ratio"],
        "source_language": payload.get("sourceLanguage") or payload.get("source_language") or global_defaults["source_language"],
        "episode_target_units": int(
            payload.get("episodeTargetUnits")
            or payload.get("episode_target_units")
            or global_defaults.get("episode_target_units")
            or DEFAULT_EPISODE_TARGET_UNITS
        ),
        "asset_extraction_target_units": int(
            payload.get("assetExtractionTargetUnits")
            or payload.get("asset_extraction_target_units")
            or global_defaults.get("asset_extraction_target_units")
            or DEFAULT_ASSET_EXTRACTION_TARGET_UNITS
        ),
        "style_template_id": style_template_id,
        "style": {
            "mode": payload.get("styleMode") or "template",
            "category": payload.get("styleCategory"),
            "prompt": style_prompt,
            "asset_prompt": style_asset_prompt,
            "character_asset_prompt": character_asset_prompt,
            "creature_asset_prompt": creature_asset_prompt,
            "visual_type_tag": style_visual_type_tag,
            "phase_visuals": _normalize_style_phase_visuals(phase_visuals),
            "active_phase_visual_id": _style_active_phase_visual_id_from_mapping(
                {"active_phase_visual_id": active_phase_visual_id},
                _normalize_style_phase_visuals(phase_visuals),
            ),
        },
        "storyboard": {
            "rhythm_multiplier": DEFAULT_RHYTHM,
            "clip_max_seconds": DEFAULT_CLIP_MAX_SECONDS,
            "panel_count": int(payload.get("panelCount") or global_defaults["storyboard"]["panel_count"]),
            "layout": "auto",
            "reading_order": "left_to_right",
            "allow_manual_storyboard": True,
        },
        "video": {
            "seed": None,
        },
    }
    config = _deep_merge(global_defaults, project_config)
    _strip_project_model_fields(config)
    return config


def _strip_project_model_fields(config: dict[str, Any]) -> None:
    config.pop("models", None)
    config.pop("agent", None)
    storyboard = config.get("storyboard")
    if isinstance(storyboard, dict):
        for key in ("image_model", "image_size", "image_output_format"):
            storyboard.pop(key, None)
    video = config.get("video")
    if isinstance(video, dict):
        for key in ("provider", "model", "duration_seconds", "resolution", "generate_audio"):
            video.pop(key, None)


def _episode_count_from_payload(payload: dict[str, Any]) -> int:
    if isinstance(payload.get("episodeCount"), int):
        return max(1, min(24, int(payload["episodeCount"])))
    preset = str(payload.get("episodePreset") or "")
    if "六" in preset or "6" in preset:
        return 6
    if "三" in preset or "3" in preset:
        return 3
    return 1


def _default_workflow(episode_id: str, project_config: dict[str, Any]) -> dict[str, Any]:
    _ = project_config
    return {
        "episodeId": episode_id,
        "schemaVersion": 2,
        "version": 1,
        "viewport": {"x": 0, "y": 0, "zoom": 0.85},
        "routes": [],
        "nodes": [],
        "edges": [],
        "state": {
            "kind": "empty",
            "reason": "default_template_disabled",
            "workflowChainReady": False,
            "nextAction": "build_workflow_chain",
        },
    }


def create_project(payload: dict[str, Any]) -> dict[str, Any]:
    from .provider_models import _creation_model_config_status
    from .projects import _favorite_style_thumbnail_path
    from .projects import _find_template
    from .media_files import _has_image_file_input
    from .projects import _normalize_project_id
    from .agent_sessions import _project_dir
    from .projects import _project_row
    from .projects import _project_title_exists
    from .style_analysis import _save_style_reference
    from .projects import _slug_from_title
    from .settings_loaders import load_global_config
    from .settings_loaders import load_style_templates
    ensure_store()
    project_payload = payload.get("project") if isinstance(payload.get("project"), dict) else payload
    title = str(project_payload.get("name") or project_payload.get("title") or "").strip()
    if not title:
        raise ValueError("项目标题不能为空")
    if _project_title_exists(title):
        return {
            "success": False,
            "code": "project_name_exists",
            "field": "name",
            "message": PROJECT_NAME_EXISTS_MESSAGE,
        }
    model_status = _creation_model_config_status(load_global_config())
    if not model_status.get("ready"):
        return {
            "success": False,
            "code": "model_config_required",
            "field": "model_config",
            "message": model_status.get("message") or MODEL_CONFIG_REQUIRED_MESSAGE,
            "missing": model_status.get("missing", []),
            "providerCount": model_status.get("providerCount", 0),
        }
    aspect_ratio = project_payload.get("aspectRatio") or project_payload.get("aspect_ratio") or "16:9"
    if aspect_ratio not in {"9:16", "16:9"}:
        raise ValueError("画面比例只能选择 9:16 或 16:9")
    content_mode = "drama"
    narrative_mode = str(project_payload.get("narrativeMode") or project_payload.get("narrative_mode") or "drama").strip()
    if narrative_mode != "drama":
        raise ValueError("旁白讲述模式尚未开放")

    style_templates = load_style_templates()
    style_mode = str(project_payload.get("styleMode") or project_payload.get("style_mode") or "template")
    if style_mode not in {"template", "favorite", "custom"}:
        raise ValueError("视觉风格模式不存在")
    style_template_id = project_payload.get("styleTemplateId") or project_payload.get("style_template_id")
    style_template = _find_template(style_template_id, style_templates)
    style_visual_type_tag = ""
    if (
        not style_template
        and style_mode == "template"
        and style_templates
    ):
        style_template = style_templates[0]
        style_template_id = style_template.get("id")
    if style_mode == "custom":
        style_template_id = None
        style_prompt = str(project_payload.get("stylePrompt") or "").strip()
        style_asset_prompt = str(
            project_payload.get("styleAssetPrompt")
            or project_payload.get("style_asset_prompt")
            or ""
        ).strip()
        style_asset_prompt = style_asset_prompt or style_prompt
        character_asset_prompt = _style_asset_prompt_value(project_payload, "character")
        creature_asset_prompt = _style_asset_prompt_value(project_payload, "creature")
    else:
        if not style_template:
            raise ValueError("视觉风格不存在")
        if style_template.get("category") == "favorite":
            style_mode = "favorite"
            favorite_thumbnail = _favorite_style_thumbnail_path(style_template)
            if not favorite_thumbnail or not favorite_thumbnail.is_file():
                raise ValueError("收藏风格缺少可复制的本地缩略图")
        style_template_id = style_template.get("id")
        style_prompt = str(style_template.get("prompt") or "").strip()
        style_asset_prompt = str(
            style_template.get("asset_prompt")
            or style_template.get("assetPrompt")
            or ""
        ).strip()
        character_asset_prompt = _style_asset_prompt_value(style_template, "character")
        creature_asset_prompt = _style_asset_prompt_value(style_template, "creature")
        if _is_general_style_template(style_template):
            style_visual_type_tag = _general_style_visual_type_tag(
                style_template,
                project_payload,
            )
            style_prompt = _general_style_prompt(
                style_prompt,
                style_visual_type_tag,
                "prompt",
            )
            style_asset_prompt = _general_style_prompt(
                style_asset_prompt or style_prompt,
                style_visual_type_tag,
                "asset_prompt",
            )
            character_asset_prompt = _general_style_prompt(
                character_asset_prompt,
                style_visual_type_tag,
                "character_asset_prompt",
            )
            creature_asset_prompt = _general_style_prompt(
                creature_asset_prompt,
                style_visual_type_tag,
                "creature_asset_prompt",
            )
    style_file = project_payload.get("styleFile") or project_payload.get("style_file")
    if style_mode == "custom" and (
        not style_prompt
        or not isinstance(style_file, dict)
        or not _has_image_file_input(style_file)
    ):
        return {
            "success": False,
            "code": "custom_style_required",
            "field": "style",
            "message": CUSTOM_STYLE_REQUIRED_MESSAGE,
        }
    phase_visuals = _style_phase_visuals_from_mapping(project_payload)
    active_phase_visual_id = _style_active_phase_visual_id_from_mapping(
        project_payload,
        phase_visuals,
    )

    payload_project_id = _normalize_project_id(project_payload.get("id"))
    project_id = payload_project_id or _slug_from_title(title)
    project_dir = _project_dir(project_id)
    if project_dir.exists():
        raise ValueError("项目目录已存在")
    now = _now()
    config = _build_project_config(
        {
            **project_payload,
            "contentMode": content_mode,
            "narrativeMode": narrative_mode,
            "aspectRatio": aspect_ratio,
            "styleCategory": (style_template or {}).get("category") or project_payload.get("styleCategory"),
            "styleMode": style_mode,
        },
        style_prompt,
        style_template_id,
        style_asset_prompt,
        character_asset_prompt,
        creature_asset_prompt,
        style_visual_type_tag,
        phase_visuals,
        active_phase_visual_id,
    )
    episode_count = _episode_count_from_payload(project_payload)
    episodes = [
        {
            "id": f"E{index:02d}",
            "title": "第一集" if index == 1 else f"第 {index} 集",
            "status": "草稿",
        }
        for index in range(1, episode_count + 1)
    ]
    meta = {
        "schema_version": 1,
        "id": project_id,
        "title": title,
        "pipeline_mode": "storyboard_video",
        "content_mode": content_mode,
        "narrative_mode": narrative_mode,
        "aspect_ratio": aspect_ratio,
        "source_language": config.get("source_language", "zh-CN"),
        "style_template_id": style_template_id,
        "style_prompt": style_prompt,
        "summary": project_payload.get("summary") or "故事版视频项目，等待导入源文本并生成故事版计划。",
        "status_type": "draft",
        "source_count": 0,
        "episodes": episodes,
        "accent": (style_template or {}).get("accent") or ACCENTS[0],
        "created_at": now,
        "updated_at": now,
    }

    with _LOCK:
        project_dir.mkdir(parents=False, exist_ok=False)
        try:
            for rel in (
                "assets/characters",
                "assets/scenes",
                "assets/props",
                "assets/styles",
                "sources",
                "episodes",
                "features/storyboard",
                "versions",
                "exports",
                "diagnostics",
            ):
                (project_dir / rel).mkdir(parents=True, exist_ok=True)

            if style_mode == "favorite" and isinstance(style_template, dict):
                config.setdefault("style", {})["favorite_snapshot"] = _project_favorite_style_snapshot(
                    project_id,
                    style_template,
                )
            if isinstance(style_file, dict) and _has_image_file_input(style_file):
                style_ref = _save_style_reference(project_id, style_file, style_prompt)
                meta["style_reference"] = style_ref
                config["style"]["reference"] = style_ref

            _write_json(project_dir / "project.json", meta)
            _write_json(project_dir / "config.json", config)
            _write_json(project_dir / "sources" / "sources.json", [])
            _write_json(project_dir / "assets" / "assets.json", copy.deepcopy(DEFAULT_ASSETS))
            _write_json(
                project_dir / "features" / "storyboard" / "config.json",
                {
                    "inherits": ["global", "project"],
                    "panel_count": config["storyboard"]["panel_count"],
                },
            )
            for episode in episodes:
                episode_dir = project_dir / "episodes" / episode["id"]
                episode_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Project creation is atomic from the caller's perspective.  A
            # failed snapshot, JSON write, or episode initialization must not
            # leave a partial project directory behind.
            shutil.rmtree(project_dir, ignore_errors=True)
            raise

    return {"success": True, "project": _project_row(project_id, meta), "config": config}


def import_project(payload: dict[str, Any]) -> dict[str, Any]:
    project = payload.get("project") if isinstance(payload.get("project"), dict) else payload
    project = {**project, "name": f"{project.get('name') or project.get('title') or '导入项目'}"}
    return create_project({"project": project})


def _project_background_threads(project_dir: Path) -> list[threading.Thread]:
    from .agent_sessions import _agent_sessions_db_path, _load_agent_sessions
    from .runtime_state import (
        _AGENT_CANCEL_FLAGS,
        _AGENT_THREADS,
        _ASSET_IMAGE_TASK_CANCEL_FLAGS,
        _ASSET_IMAGE_TASK_THREADS,
        _VIDEO_TASK_CANCEL_FLAGS,
        _VIDEO_TASK_THREADS,
    )
    from .task_lifecycle import _BACKGROUND_STORYBOARD_TASK_THREADS

    try:
        tasks = _read_json(project_dir / "tasks" / "tasks.json", [])
    except (OSError, ValueError):
        tasks = []
    if not isinstance(tasks, list):
        tasks = []
    threads: dict[int, threading.Thread] = {}
    sessions = []
    if _agent_sessions_db_path(project_dir.name).exists():
        try:
            sessions = _load_agent_sessions(project_dir.name)
        except Exception:
            pass
    for session in sessions:
        session_id = str(session.get("id") or "").strip() if isinstance(session, dict) else ""
        thread = _AGENT_THREADS.get(session_id) if session_id else None
        if thread and thread.is_alive():
            threads[id(thread)] = thread
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or "").strip()
        session_id = str(task.get("sessionId") or "").strip()
        if task_id:
            for cancel_flags in (_AGENT_CANCEL_FLAGS, _ASSET_IMAGE_TASK_CANCEL_FLAGS, _VIDEO_TASK_CANCEL_FLAGS):
                flag = cancel_flags.get(task_id)
                if flag:
                    flag.set()
        for key in (task_id, session_id):
            if key:
                flag = _AGENT_CANCEL_FLAGS.get(key)
                if flag:
                    flag.set()
        for registry, key in (
            (_AGENT_THREADS, task_id),
            (_AGENT_THREADS, session_id),
            (_ASSET_IMAGE_TASK_THREADS, task_id),
            (_VIDEO_TASK_THREADS, task_id),
            (_BACKGROUND_STORYBOARD_TASK_THREADS, task_id),
        ):
            thread = registry.get(key) if key else None
            if thread and thread.is_alive():
                threads[id(thread)] = thread
    return list(threads.values())


def _clear_deleted_current_project(project_id: str) -> None:
    from .projects import CURRENT_PROJECT_STATE_PATH, _write_current_project_cleared_state

    try:
        current = _read_json(CURRENT_PROJECT_STATE_PATH, {})
        if isinstance(current, dict) and current.get("projectId") == project_id:
            _write_current_project_cleared_state(reason="project_deleted", invalid_project_id=project_id)
    except Exception:
        traceback.print_exc()


def delete_project(project_id: str) -> dict[str, Any]:
    from .agent_sessions import _prepare_agent_sessions_for_project_delete, _project_dir
    from .project_deletion_guard import deleting_project, wait_for_canvas_idle

    project_dir = _project_dir(project_id)
    projects_root = PROJECTS_DIR.resolve()
    delete_target = project_dir.resolve()
    if delete_target == projects_root or projects_root not in delete_target.parents:
        raise ValueError("项目目录无效")

    with deleting_project(project_id):
        if not project_dir.exists():
            _clear_deleted_current_project(project_id)
            return {"success": True, "projectId": project_id, "deleted": "missing"}
        if not project_dir.is_dir():
            raise ValueError("项目目录无效")

        meta_path = project_dir / "project.json"
        meta_bytes = meta_path.read_bytes() if meta_path.is_file() else None
        deleted = "permanent" if meta_bytes is not None else "orphan"
        agent_session_cleanup = _prepare_agent_sessions_for_project_delete(project_id)
        threads = _project_background_threads(project_dir)
        deadline = time.monotonic() + 5.0
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            raise RuntimeError("项目仍有后台任务运行，请稍后重试删除")
        if not wait_for_canvas_idle(project_id, max(0.0, deadline - time.monotonic())):
            raise RuntimeError("项目画布仍在使用，请稍后重试删除")

        try:
            for attempt in range(4):
                try:
                    shutil.rmtree(delete_target)
                    break
                except OSError:
                    if not project_dir.exists():
                        break
                    if attempt == 3:
                        raise
                    time.sleep(0.15 * (attempt + 1))
        except OSError as exc:
            try:
                # rmtree may remove project.json before a locked file stops the deletion.
                if meta_bytes is not None and not meta_path.exists():
                    meta_path.write_bytes(meta_bytes)
            except OSError:
                traceback.print_exc()
                raise RuntimeError("项目删除未完成，且项目列表信息恢复失败，请检查后端日志") from exc
            raise RuntimeError("项目文件仍被占用，请稍后重试删除") from exc

        _clear_deleted_current_project(project_id)
        return {
            "success": True,
            "projectId": project_id,
            "deleted": deleted,
            **agent_session_cleanup,
        }


def _project_agent_model_id_from_config(config: Any) -> str:
    if not isinstance(config, dict):
        return ""
    return str(config.get("agent_model_id") or "").strip()


def get_project_settings(project_id: str) -> dict[str, Any]:
    from .project_resource_revisions import _resource_revision_value
    from .projects import _find_template
    from .agent_sessions import _project_config_path
    from .agent_sessions import _project_meta_path
    from .projects import _project_style_reference_ref
    from .projects import _project_thumbnail_ref
    from .settings_loaders import load_style_templates
    project_config = _read_json(_project_config_path(project_id), {})
    meta = _read_json(_project_meta_path(project_id), {})
    config = get_effective_config(project_id)
    style_config = config.get("style", {})
    if not isinstance(style_config, dict):
        style_config = {}
    phase_visuals = _style_phase_visuals_from_mapping(style_config)
    active_phase_visual_id = _style_active_phase_visual_id_from_mapping(
        style_config,
        phase_visuals,
    )
    style_template_id = str(config.get("style_template_id") or "")
    style_template = _find_template(style_template_id, load_style_templates()) if style_template_id else None
    style_mode = str(
        style_config.get("mode")
        or ("favorite" if style_template and style_template.get("category") == "favorite" else "template")
    )
    if style_mode == "custom":
        style_category = "all"
    elif style_template and style_template.get("category") == "favorite":
        style_mode = "favorite"
        style_category = "favorite"
    elif style_template:
        style_category = str(style_template.get("category") or style_config.get("category") or "all")
    else:
        style_category = str(style_config.get("category") or "all")
    thumbnail = _project_thumbnail_ref(project_id, meta if isinstance(meta, dict) else {})
    style_reference = _project_style_reference_ref(
        project_id,
        style_config.get("reference")
        if isinstance(style_config.get("reference"), dict)
        else meta.get("style_reference") if isinstance(meta, dict) else None,
    )
    style_visual_type_tag = str(style_config.get("visual_type_tag") or "")
    if _is_general_style_template(style_template):
        style_visual_type_tag = _general_style_visual_type_tag(style_template, {}, style_config)
    return {
        "projectConfigRevision": _resource_revision_value(project_config),
        "pipelineMode": "storyboard_video",
        "contentMode": config.get("content_mode", "drama"),
        "narrativeMode": config.get("narrative_mode", "drama"),
        "aspectRatio": config.get("aspect_ratio", "9:16"),
        "sourceLanguage": config.get("source_language", "zh-CN"),
        "episodeTargetUnits": int(config.get("episode_target_units", DEFAULT_EPISODE_TARGET_UNITS) or DEFAULT_EPISODE_TARGET_UNITS),
        "assetExtractionTargetUnits": int(
            config.get("asset_extraction_target_units", DEFAULT_ASSET_EXTRACTION_TARGET_UNITS)
            or DEFAULT_ASSET_EXTRACTION_TARGET_UNITS
        ),
        "agentModelId": _project_agent_model_id_from_config(project_config),
        "agentReasoningEffort": str(project_config.get("agent_reasoning_effort") or "").strip() if isinstance(project_config, dict) else "",
        "styleMode": style_mode,
        "styleCategory": style_category,
        "styleTemplateId": style_template_id or None,
        "stylePrompt": str(style_config.get("prompt") or ""),
        "styleAssetPrompt": str(style_config.get("asset_prompt") or ""),
        "style_asset_prompt": str(style_config.get("asset_prompt") or ""),
        "styleVisualTypeTag": style_visual_type_tag,
        "style_visual_type_tag": style_visual_type_tag,
        "characterAssetPrompt": str(style_config.get("character_asset_prompt") or ""),
        "character_asset_prompt": str(style_config.get("character_asset_prompt") or ""),
        "creatureAssetPrompt": str(style_config.get("creature_asset_prompt") or ""),
        "creature_asset_prompt": str(style_config.get("creature_asset_prompt") or ""),
        "phaseVisuals": copy.deepcopy(phase_visuals),
        "phase_visuals": copy.deepcopy(phase_visuals),
        "activePhaseVisualId": active_phase_visual_id,
        "active_phase_visual_id": active_phase_visual_id,
        "panelCount": max(1, min(3, int(config.get("storyboard", {}).get("panel_count", 3) or 3))),
        "storyboardRhythmMultiplier": config.get("storyboard", {}).get("rhythm_multiplier", 1.0),
        "storyboardClipMaxSeconds": config.get("storyboard", {}).get("clip_max_seconds", 15),
        "videoGenerationDebugBlockEnabled": bool(config.get("video", {}).get("generation_debug_block_enabled", False)),
        "video_generation_debug_block_enabled": bool(config.get("video", {}).get("generation_debug_block_enabled", False)),
        "allowManualStoryboard": config.get("storyboard", {}).get("allow_manual_storyboard", True),
        "storyboardConsistencyReportEnabled": config.get("storyboard", {}).get("consistency_report_enabled", True) is True,
        "coverImage": meta.get("cover_image") if isinstance(meta, dict) else None,
        "cover_image": meta.get("cover_image") if isinstance(meta, dict) else None,
        "styleReference": style_reference,
        "style_reference": style_reference,
        "thumbnail": thumbnail,
    }


def _apply_model_config_projection(
    config: dict[str, Any],
    model_config: dict[str, Any],
    capabilities: dict[str, list[dict[str, Any]]],
) -> None:
    from .provider_models import _find_model
    image_model = _find_model(model_config["image"]["model_id"], "image", capabilities) or {}
    video_model = _find_model(model_config["video"]["model_id"], "video", capabilities) or {}
    config.setdefault("models", {})
    config["models"]["image"] = image_model.get("label") or model_config["image"]["model_id"]
    config["models"]["video"] = video_model.get("label") or model_config["video"]["model_id"]
    config["models"]["agent"] = model_config["agent"].get("model_id") or ""
    config["models"]["text"] = model_config["text"].get("model_id") or ""
    config.setdefault("storyboard", {})["image_model"] = config["models"]["image"]
    config["storyboard"]["image_size"] = model_config["image"].get("storyboard_resolution") or ""
    config["storyboard"]["image_output_format"] = model_config["image"].get("image_output_format") or "auto"
    config.setdefault("video", {})["model"] = config["models"]["video"]
    config["video"]["provider"] = video_model.get("provider_id") or ""
    config["video"]["resolution"] = model_config["video"].get("resolution") or ""
    config["video"]["duration_seconds"] = model_config["video"].get("duration_seconds") or 8
    config["video"]["generate_audio"] = model_config["video"].get("generate_audio")


def _apply_global_model_config(config: dict[str, Any]) -> None:
    from .provider_models import _normalize_model_config
    from .settings_loaders import load_model_catalog
    capabilities, global_model_config = load_model_catalog()
    model_config = _normalize_model_config(global_model_config, capabilities)
    agent_model_id = _project_agent_model_id_from_config(config)
    if agent_model_id:
        model_config["agent"]["model_id"] = agent_model_id
    _apply_model_config_projection(config, model_config, capabilities)


def _apply_project_agent_model_settings(config: dict[str, Any], settings: dict[str, Any]) -> None:
    if "agentModelId" in settings or "agent_model_id" in settings:
        from .provider_models import _find_model
        from .settings_loaders import load_model_catalog

        agent_model_id = str(settings.get("agentModelId") or settings.get("agent_model_id") or "").strip()
        if agent_model_id:
            capabilities, _ = load_model_catalog()
            model = _find_model(agent_model_id, "agent", capabilities)
            if not model or model.get("available") is False or model.get("model_exclusion_status"):
                raise ValueError("智能体模型不可用，请重新选择")
        config["agent_model_id"] = agent_model_id
        if "agentReasoningEffort" not in settings and "agent_reasoning_effort" not in settings:
            config.pop("agent_reasoning_effort", None)
    if "agentReasoningEffort" in settings or "agent_reasoning_effort" in settings:
        from utils.model_reasoning import AGENT_REASONING_MODES

        effort = str(settings.get("agentReasoningEffort") or settings.get("agent_reasoning_effort") or "").strip()
        if effort and effort not in AGENT_REASONING_MODES:
            raise ValueError("无效的智能体推理能力")
        if effort:
            from .settings_loaders import load_model_settings

            model_settings = load_model_settings("adapted")
            agent_model_id = str(config.get("agent_model_id") or model_settings["config"]["agent"].get("model_id") or "")
            agent_model = next(
                (row for row in model_settings["capabilities"]["agent"] if row.get("id") == agent_model_id),
                None,
            )
            if not agent_model or not agent_model.get("reasoning_supported") or effort not in agent_model.get("reasoning_levels", []):
                raise ValueError("所选智能体模型不支持该推理能力")
            config["agent_reasoning_effort"] = effort
        else:
            config.pop("agent_reasoning_effort", None)


@_serialized_project_config_write
def save_project_settings(project_id: str, settings: dict[str, Any]) -> dict[str, Any]:
    from .project_resource_revisions import _append_resource_revision
    from .project_resource_revisions import _assert_resource_write_guard
    from .projects import _find_template
    from .media_files import _has_image_file_input
    from .agent_sessions import _project_config_path
    from .agent_sessions import _project_meta_path
    from .projects import _project_title_exists
    from .project_resource_revisions import _resource_revision_value
    from .style_analysis import _save_project_cover
    from .style_analysis import _save_style_reference
    from .source_coverage import _sync_source_coverage_targets
    from .settings_loaders import load_style_templates
    path = _project_config_path(project_id)
    if not path.exists():
        raise FileNotFoundError("项目不存在")
    config = _read_json(path, {})
    _assert_resource_write_guard(
        config,
        settings["expectedRevision"] if "expectedRevision" in settings else settings.get("expected_revision"),
        settings.get("baseHash") or settings.get("base_hash"),
    )
    agent_selection_keys = {"agentModelId", "agent_model_id", "agentReasoningEffort", "agent_reasoning_effort"}
    guard_keys = {"expectedRevision", "expected_revision", "baseHash", "base_hash", "reason", "userInstruction", "user_instruction"}
    if settings.keys() <= agent_selection_keys | guard_keys and settings.keys() & agent_selection_keys:
        before = copy.deepcopy(config)
        _apply_project_agent_model_settings(config, settings)
        if before:
            _append_resource_revision(
                project_id, resource="projectConfig", relative_path="config.json",
                document=before, reason=str(settings.get("reason") or "save_project_settings"),
                user_instruction=str(settings.get("userInstruction") or settings.get("user_instruction") or ""),
            )
        config["revision"] = _resource_revision_value(before) + 1
        config["updatedAt"] = _now()
        _write_json(path, config)
        return {"success": True, "settings": get_project_settings(project_id)}
    config_before = copy.deepcopy(config)
    existing_style = config.get("style") if isinstance(config.get("style"), dict) else {}
    previous_favorite_style_snapshot = existing_style.get("favorite_snapshot")
    favorite_style_snapshot = previous_favorite_style_snapshot
    meta_path = _project_meta_path(project_id)
    meta_before = _read_json(meta_path, {})
    title_key_present = "name" in settings or "title" in settings
    if title_key_present:
        title = str(settings.get("name") or settings.get("title") or "").strip()
        if not title:
            raise ValueError("项目标题不能为空")
        if _project_title_exists(title, exclude_project_id=project_id):
            return {
                "success": False,
                "code": "project_name_exists",
                "field": "name",
                "message": PROJECT_NAME_EXISTS_MESSAGE,
            }
    config["aspect_ratio"] = settings.get("aspectRatio", config.get("aspect_ratio", "9:16"))
    if "sourceLanguage" in settings or "source_language" in settings:
        source_language = settings.get("sourceLanguage") or settings.get("source_language")
        if source_language not in SOURCE_LANGUAGE_OPTIONS:
            raise ValueError("语言地区只能选择中文、繁体、英文或越南语")
        config["source_language"] = source_language
    if "episodeTargetUnits" in settings or "episode_target_units" in settings:
        episode_target_units = int(settings.get("episodeTargetUnits") or settings.get("episode_target_units") or DEFAULT_EPISODE_TARGET_UNITS)
        if episode_target_units <= 0:
            raise ValueError("每集分割字数必须大于 0")
        config["episode_target_units"] = episode_target_units
    if "assetExtractionTargetUnits" in settings or "asset_extraction_target_units" in settings:
        asset_target_units = int(
            settings.get("assetExtractionTargetUnits")
            or settings.get("asset_extraction_target_units")
            or DEFAULT_ASSET_EXTRACTION_TARGET_UNITS
        )
        if asset_target_units <= 0:
            raise ValueError("资产拆分字数必须大于 0")
        config["asset_extraction_target_units"] = asset_target_units
    if any(
        key in settings
        for key in (
            "styleMode",
            "style_mode",
            "styleCategory",
            "style_category",
            "styleTemplateId",
            "style_template_id",
            "stylePrompt",
            "style_prompt",
            "styleVisualTypeTag",
            "style_visual_type_tag",
            "visualTypeTag",
            "visual_type_tag",
            "characterAssetPrompt",
            "character_asset_prompt",
            "characterStylePrompt",
            "character_style_prompt",
            "creatureAssetPrompt",
            "creature_asset_prompt",
            "creatureStylePrompt",
            "creature_style_prompt",
            "phaseVisuals",
            "phase_visuals",
            "stylePhaseVisuals",
            "style_phase_visuals",
            "activePhaseVisualId",
            "active_phase_visual_id",
            "activeStylePhaseVisualId",
            "active_style_phase_visual_id",
            "styleFile",
            "style_file",
        )
    ):
        style_mode = str(settings.get("styleMode") or settings.get("style_mode") or existing_style.get("mode") or "template")
        if style_mode not in {"template", "favorite", "custom"}:
            raise ValueError("视觉风格模式不存在")
        style_category = settings.get("styleCategory") or settings.get("style_category") or existing_style.get("category")
        has_style_prompt = "stylePrompt" in settings or "style_prompt" in settings
        raw_style_prompt = (
            settings.get("stylePrompt")
            if "stylePrompt" in settings
            else settings.get("style_prompt") if "style_prompt" in settings else ""
        )
        if style_mode == "custom" and not has_style_prompt:
            raw_style_prompt = existing_style.get("prompt", "")
        style_prompt = str(raw_style_prompt or "").strip()
        style_visual_type_tag = ""
        has_style_asset_prompt = "styleAssetPrompt" in settings or "style_asset_prompt" in settings
        raw_style_asset_prompt = (
            settings.get("styleAssetPrompt")
            if "styleAssetPrompt" in settings
            else settings.get("style_asset_prompt") if "style_asset_prompt" in settings else ""
        )
        style_asset_prompt = str(raw_style_asset_prompt or "").strip()
        style_template_id = settings.get("styleTemplateId") if "styleTemplateId" in settings else settings.get("style_template_id")
        existing_meta_style_reference = None
        favorite_style_snapshot = None
        if style_mode != "custom":
            style_template_id = style_template_id or config.get("style_template_id") or DEFAULT_STYLE_TEMPLATES[0]["id"]
            style_template = _find_template(str(style_template_id), load_style_templates())
            if not style_template:
                project_snapshot = existing_style.get("favorite_snapshot")
                if (
                    isinstance(project_snapshot, dict)
                    and str(project_snapshot.get("id") or "") == str(style_template_id)
                ):
                    style_template = copy.deepcopy(project_snapshot)
            if not style_template:
                raise ValueError("视觉风格不存在")
            style_prompt = str(style_template.get("prompt") or "").strip()
            style_asset_prompt = str(
                style_template.get("asset_prompt")
                or style_template.get("assetPrompt")
                or ""
            ).strip()
            character_asset_prompt = _style_asset_prompt_value(style_template, "character")
            creature_asset_prompt = _style_asset_prompt_value(style_template, "creature")
            if _is_general_style_template(style_template):
                style_visual_type_tag = _general_style_visual_type_tag(
                    style_template,
                    settings,
                    existing_style,
                )
                style_prompt = _general_style_prompt(
                    style_prompt,
                    style_visual_type_tag,
                    "prompt",
                )
                style_asset_prompt = _general_style_prompt(
                    style_asset_prompt or style_prompt,
                    style_visual_type_tag,
                    "asset_prompt",
                )
                character_asset_prompt = _general_style_prompt(
                    character_asset_prompt,
                    style_visual_type_tag,
                    "character_asset_prompt",
                )
                creature_asset_prompt = _general_style_prompt(
                    creature_asset_prompt,
                    style_visual_type_tag,
                    "creature_asset_prompt",
                )
            if style_template.get("category") == "favorite":
                style_mode = "favorite"
                style_category = "favorite"
                favorite_style_snapshot = _project_favorite_style_snapshot(project_id, style_template)
            else:
                style_category = style_template.get("category") or style_category or "all"
            config["style_template_id"] = str(style_template_id)
        else:
            style_category = "all"
            config["style_template_id"] = None
            existing_meta = _read_json(_project_meta_path(project_id), {})
            if isinstance(existing_meta, dict):
                existing_meta_style_reference = existing_meta.get("style_reference")
            if not has_style_asset_prompt:
                style_asset_prompt = str(existing_style.get("asset_prompt") or "").strip()
            style_asset_prompt = style_asset_prompt or style_prompt
            character_asset_prompt = _style_asset_prompt_value(
                settings,
                "character",
                fallback=str(existing_style.get("character_asset_prompt") or ""),
            )
            creature_asset_prompt = _style_asset_prompt_value(
                settings,
                "creature",
                fallback=str(existing_style.get("creature_asset_prompt") or ""),
            )
        phase_visuals = _style_phase_visuals_from_mapping(
            settings,
            fallback=existing_style.get("phase_visuals"),
        )
        active_phase_visual_id = _style_active_phase_visual_id_from_mapping(
            settings,
            phase_visuals,
            fallback=existing_style.get("active_phase_visual_id"),
        )
        style_file = settings.get("styleFile") or settings.get("style_file")
        has_new_style_file = isinstance(style_file, dict) and _has_image_file_input(style_file)
        has_existing_style_reference = isinstance(existing_style.get("reference"), dict) or isinstance(existing_meta_style_reference, dict)
        if style_mode == "custom" and (not style_prompt or not (has_new_style_file or has_existing_style_reference)):
            return {
                "success": False,
                "code": "custom_style_required",
                "field": "style",
                "message": CUSTOM_STYLE_REQUIRED_MESSAGE,
            }
        style_config = dict(existing_style)
        style_config.pop("scene_asset_prompt", None)
        style_config.pop("prop_asset_prompt", None)
        style_config.pop("theme_visual_context", None)
        style_config.pop("favorite_snapshot", None)
        if not isinstance(style_config.get("reference"), dict) and isinstance(existing_meta_style_reference, dict):
            style_config["reference"] = existing_meta_style_reference
        style_config.update(
            {
                "mode": style_mode,
                "category": style_category,
                "prompt": style_prompt,
                "asset_prompt": style_asset_prompt,
                "character_asset_prompt": character_asset_prompt,
                "creature_asset_prompt": creature_asset_prompt,
                "visual_type_tag": style_visual_type_tag,
                "phase_visuals": phase_visuals,
                "active_phase_visual_id": active_phase_visual_id,
            }
        )
        if isinstance(favorite_style_snapshot, dict):
            style_config["favorite_snapshot"] = favorite_style_snapshot
        if has_new_style_file:
            style_config["reference"] = _save_style_reference(project_id, style_file, style_prompt)
        elif style_mode != "custom":
            style_config.pop("reference", None)
        config["style"] = style_config
    _apply_project_agent_model_settings(config, settings)
    _strip_project_model_fields(config)
    raw_panel_count = settings.get("panelCount", config.get("storyboard", {}).get("panel_count", 3))
    config.setdefault("storyboard", {})["panel_count"] = max(1, min(3, int(raw_panel_count or 3)))
    config["storyboard"]["allow_manual_storyboard"] = bool(settings.get("allowManualStoryboard", config["storyboard"].get("allow_manual_storyboard", True)))
    from .storyboard_timing import valid_clip_max, valid_rhythm
    config["storyboard"]["rhythm_multiplier"] = valid_rhythm(
        settings.get("storyboardRhythmMultiplier", config["storyboard"].get("rhythm_multiplier", 1.0))
    )
    previous_clip_max = config_before.get("storyboard", {}).get("clip_max_seconds", 15)
    config["storyboard"]["clip_max_seconds"] = valid_clip_max(
        settings.get("storyboardClipMaxSeconds", previous_clip_max)
    )
    if "storyboardConsistencyReportEnabled" in settings:
        config["storyboard"]["consistency_report_enabled"] = settings["storyboardConsistencyReportEnabled"] is True
    if "videoGenerationDebugBlockEnabled" in settings or "video_generation_debug_block_enabled" in settings:
        config["video"]["generation_debug_block_enabled"] = bool(
            settings.get("videoGenerationDebugBlockEnabled")
            if "videoGenerationDebugBlockEnabled" in settings
            else settings.get("video_generation_debug_block_enabled")
        )
    if config_before:
        _append_resource_revision(
            project_id,
            resource="projectConfig",
            relative_path="config.json",
            document=config_before,
            reason=str(settings.get("reason") or "save_project_settings"),
            user_instruction=str(settings.get("userInstruction") or settings.get("user_instruction") or ""),
        )
    config["revision"] = _resource_revision_value(config_before) + 1
    config["updatedAt"] = _now()
    new_favorite_snapshot_path = _project_snapshot_media_path(favorite_style_snapshot)
    previous_favorite_snapshot_path = _project_snapshot_media_path(previous_favorite_style_snapshot)
    previous_cover_image = meta_before.get("cover_image") if isinstance(meta_before, dict) else None
    new_cover_image: dict[str, Any] | None = None
    clear_cover = bool(settings.get("clearCoverImage") or settings.get("clear_cover_image"))
    cover_changed = clear_cover
    try:
        _write_json(path, config)
        meta = copy.deepcopy(meta_before) if isinstance(meta_before, dict) else {}
        if title_key_present:
            meta["title"] = title
        if clear_cover:
            meta.pop("cover_image", None)
        cover_file = settings.get("coverFile") or settings.get("cover_file")
        if isinstance(cover_file, dict) and _has_image_file_input(cover_file):
            new_cover_image = _save_project_cover(project_id, cover_file)
            meta["cover_image"] = new_cover_image
            cover_changed = True
        meta["aspect_ratio"] = config["aspect_ratio"]
        meta["source_language"] = config.get("source_language", "zh-CN")
        meta["style_template_id"] = config.get("style_template_id", "")
        style_config = config.get("style", {})
        if isinstance(style_config, dict):
            meta["style_prompt"] = str(style_config.get("prompt") or "")
            if isinstance(style_config.get("reference"), dict):
                meta["style_reference"] = style_config["reference"]
            else:
                meta.pop("style_reference", None)
        meta["updated_at"] = _now()
        _write_json(meta_path, meta)
    except Exception:
        try:
            _write_json(path, config_before)
            _write_json(meta_path, meta_before if isinstance(meta_before, dict) else {})
        except Exception:
            print(traceback.format_exc(), flush=True)
        if new_favorite_snapshot_path and new_favorite_snapshot_path != previous_favorite_snapshot_path:
            _delete_project_favorite_style_snapshot_media(project_id, favorite_style_snapshot)
        _delete_project_cover_media(project_id, new_cover_image)
        raise
    if previous_favorite_snapshot_path and previous_favorite_snapshot_path != new_favorite_snapshot_path:
        _delete_project_favorite_style_snapshot_media(project_id, previous_favorite_style_snapshot)
    previous_cover_path = _project_snapshot_media_path(previous_cover_image)
    new_cover_path = _project_snapshot_media_path(new_cover_image)
    if cover_changed and previous_cover_path and previous_cover_path != new_cover_path:
        _delete_project_cover_media(project_id, previous_cover_image)
    _sync_source_coverage_targets(project_id, config)
    return {"success": True, "settings": get_project_settings(project_id)}


def get_project_business_config(project_id: str, feature_key: str | None = None) -> dict[str, Any]:
    from .agent_sessions import _project_config_path
    from .agent_sessions import _project_dir
    from .settings_loaders import load_project_defaults
    global_defaults = load_project_defaults()
    project_config = _read_json(_project_config_path(project_id), {})
    effective = _deep_merge(global_defaults, project_config if isinstance(project_config, dict) else {})
    if feature_key:
        feature_path = _project_dir(project_id) / "features" / feature_key / "config.json"
        if feature_path.exists():
            feature_config = _read_json(feature_path, {})
            effective = _deep_merge(effective, feature_config if isinstance(feature_config, dict) else {})
    return effective


def get_effective_config(project_id: str, feature_key: str | None = None) -> dict[str, Any]:
    effective = get_project_business_config(project_id, feature_key)
    _apply_global_model_config(effective)
    return effective

__all__ = (
    '_build_project_config', '_episode_count_from_payload', '_default_workflow', 'create_project',
    'import_project', 'delete_project', 'get_project_settings',
    '_apply_model_config_projection', '_apply_global_model_config', 'save_project_settings',
    'get_effective_config', '_normalize_visual_context', 'apply_theme_visual_context_to_config',
    'apply_phase_visual_context_to_config', 'remove_phase_visual_context_from_config'
)
