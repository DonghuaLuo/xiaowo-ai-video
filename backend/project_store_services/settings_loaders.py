# -*- coding: utf-8 -*-
"""全局设置、拆分模板和风格模板加载。"""

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


from .catalogs import DEFAULT_GLOBAL_CONFIG
from .catalogs import DEFAULT_SCRIPT_ADAPTATION_TEMPLATES
from .catalogs import DEFAULT_STYLE_TEMPLATES
from .catalogs import DEFAULT_TEXT_REPLACEMENT_RULES
from .catalogs import GLOBAL_CONFIG_PATH
from .catalogs import GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH
from .catalogs import GLOBAL_STYLE_TEMPLATES_PATH
from .catalogs import GLOBAL_TEXT_REPLACEMENT_RULES_PATH
from .store_core import _deep_merge
from .store_core import _merge_model_capabilities
from .store_core import _merge_provider_presets
from .store_core import _normalize_text_replacement_rules
from .store_core import _read_json
from .store_core import _write_json
from .store_core import ensure_store

_CONFIG_SNAPSHOT_LOCK = threading.RLock()
_DEFAULTS_SNAPSHOT_LOCK = threading.RLock()
_CONFIG_SNAPSHOT_KEY: tuple[Any, ...] | None = None
_CONFIG_SNAPSHOT: dict[str, Any] | None = None
_MODEL_CATALOG_SNAPSHOT: tuple[dict[str, Any], dict[str, Any]] | None = None
_DEFAULTS_SNAPSHOT_KEY: tuple[Any, ...] | None = None
_DEFAULTS_SNAPSHOT: dict[str, Any] | None = None


def _config_file_signature() -> tuple[Any, ...]:
    try:
        stat = GLOBAL_CONFIG_PATH.stat()
        return (str(GLOBAL_CONFIG_PATH), stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except FileNotFoundError:
        return (str(GLOBAL_CONFIG_PATH), None)


def load_project_defaults() -> dict[str, Any]:
    """Read business defaults without compiling the provider/model catalog."""
    global _DEFAULTS_SNAPSHOT_KEY, _DEFAULTS_SNAPSHOT
    ensure_store()
    with _DEFAULTS_SNAPSHOT_LOCK:
        signature = _config_file_signature()
        if _DEFAULTS_SNAPSHOT is None or signature != _DEFAULTS_SNAPSHOT_KEY:
            raw = _read_json(GLOBAL_CONFIG_PATH, {})
            defaults = raw.get("defaults") if isinstance(raw, dict) else None
            value = _deep_merge(DEFAULT_GLOBAL_CONFIG["defaults"], defaults if isinstance(defaults, dict) else {})
            _normalize_business_defaults(value)
            _DEFAULTS_SNAPSHOT = value
            _DEFAULTS_SNAPSHOT_KEY = signature
        return copy.deepcopy(_DEFAULTS_SNAPSHOT)


def _normalize_business_defaults(defaults: dict[str, Any]) -> None:
    defaults["content_mode"] = "drama"
    storyboard_defaults = defaults.setdefault("storyboard", {})
    if isinstance(storyboard_defaults, dict):
        try:
            panel_count = int(storyboard_defaults.get("panel_count") or 0)
        except (TypeError, ValueError):
            panel_count = 0
        storyboard_defaults["panel_count"] = max(1, min(3, panel_count or 3))


def load_global_config() -> dict[str, Any]:
    """Compile once per file revision; callers always own their mutable copy."""
    with _CONFIG_SNAPSHOT_LOCK:
        return copy.deepcopy(_global_config_snapshot())


def _global_config_snapshot() -> dict[str, Any]:
    # Only used while holding _CONFIG_SNAPSHOT_LOCK; never expose this mutable object.
    global _CONFIG_SNAPSHOT_KEY, _CONFIG_SNAPSHOT, _MODEL_CATALOG_SNAPSHOT
    ensure_store()
    signature = _config_file_signature()
    if _CONFIG_SNAPSHOT is None or signature != _CONFIG_SNAPSHOT_KEY:
        _CONFIG_SNAPSHOT = _load_normalized_global_config()
        _CONFIG_SNAPSHOT_KEY = signature
        _MODEL_CATALOG_SNAPSHOT = None
    return _CONFIG_SNAPSHOT


def load_model_catalog() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return owned capability/selection copies without copying credentials or discovery history."""
    with _CONFIG_SNAPSHOT_LOCK:
        config = _global_config_snapshot()
        return copy.deepcopy(_model_catalog_snapshot(config))


def model_settings_revision() -> str:
    """A cheap invalidation token; never serialize the provider discovery history."""
    return hashlib.sha256(repr(_config_file_signature()).encode("utf-8")).hexdigest()


def load_video_model_catalog() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Owned model matching data, without credentials or provider test results."""
    with _CONFIG_SNAPSHOT_LOCK:
        config = _global_config_snapshot()
        available, selection = _model_catalog_snapshot(config)
        all_models = config.get("model_capabilities") or {}
        kinds = ("image", "video")
        return copy.deepcopy((
            {kind: available.get(kind, []) for kind in kinds},
            {kind: all_models.get(kind, []) for kind in kinds},
            selection,
        ))


def _model_catalog_snapshot(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    # Called only under _CONFIG_SNAPSHOT_LOCK with its current configuration snapshot.
    from .provider_models import _available_model_capabilities, _empty_model_config

    global _MODEL_CATALOG_SNAPSHOT
    if _MODEL_CATALOG_SNAPSHOT is None:
        _MODEL_CATALOG_SNAPSHOT = (
            _available_model_capabilities(config),
            copy.deepcopy(config.get("model_config", _empty_model_config())),
        )
    return _MODEL_CATALOG_SNAPSHOT


MODEL_LIST_STATUSES = frozenset({"all", "adapted", "unadapted"})


def filter_model_capabilities_by_status(
    capabilities: dict[str, Any], status: str = "adapted",
) -> dict[str, Any]:
    """Apply the same adaptation policy to every public model list."""
    if status not in MODEL_LIST_STATUSES:
        raise ValueError(f"无效的模型状态：{status}")
    if status == "all":
        return capabilities
    return {
        key: [
            model for model in rows
            if isinstance(model, dict) and (
                model.get("available") is not False
                and not model.get("model_exclusion_status")
            ) == (status == "adapted")
        ] if isinstance(rows, list) else []
        for key, rows in capabilities.items()
    }


def load_model_settings(status: str = "adapted") -> dict[str, Any]:
    from .project_resource_revisions import _json_hash
    from .provider_models import _normalize_model_config
    from .projects import _public_provider
    from utils.model_reasoning import agent_reasoning_modes, default_agent_reasoning_mode, model_reasoning_mode

    with _CONFIG_SNAPSHOT_LOCK:
        config = _global_config_snapshot()
        capabilities, selection = copy.deepcopy(_model_catalog_snapshot(config))
        providers_by_id = {
            str(row.get("id") or ""): row
            for row in config.get("providers", []) if isinstance(row, dict)
        }
        for model in capabilities.get("agent", []):
            if not isinstance(model, dict):
                continue
            model_name = str(model.get("api_model_id") or model.get("id") or "").split(":", 1)[-1]
            provider = providers_by_id.get(str(model.get("provider_id") or ""), {})
            route = model.get("agent_route") if isinstance(model.get("agent_route"), dict) else {}
            base_url = str(route.get("baseUrl") or provider.get("base_url") or provider.get("baseUrl") or "")
            model["reasoning_default_mode"] = default_agent_reasoning_mode(model_name, base_url)
            reasoning_levels = agent_reasoning_modes(base_url, model_name)
            model["reasoning_levels"] = list(reasoning_levels)
            model["reasoning_supported"] = bool(reasoning_levels) and model_reasoning_mode(base_url, model_name, "agent:free_chat") is not None
        normalized_config = _normalize_model_config(selection, capabilities)
        return {
            "config": normalized_config,
            "configVersion": _json_hash(normalized_config),
            "capabilities": filter_model_capabilities_by_status(capabilities, status),
            "providers": [_public_provider(row, include_models=False) for row in config.get("providers", [])],
        }


def _load_normalized_global_config() -> dict[str, Any]:
    from .provider_models import _model_capabilities_with_provider_models
    from .provider_models import _normalize_provider_rows
    from .provider_models import _sync_defaults_with_model_config
    raw = _read_json(GLOBAL_CONFIG_PATH, {})
    if not isinstance(raw, dict):
        raw = {}
    merged = _deep_merge(DEFAULT_GLOBAL_CONFIG, raw)
    merged["content_modes"] = copy.deepcopy(DEFAULT_GLOBAL_CONFIG.get("content_modes", []))
    defaults = merged.setdefault("defaults", {})
    if isinstance(defaults, dict):
        _normalize_business_defaults(defaults)
    merged["provider_presets"] = _merge_provider_presets(merged.get("provider_presets"))
    merged["model_capabilities"] = _merge_model_capabilities(merged.get("model_capabilities"))
    merged["providers"] = _normalize_provider_rows(merged.get("providers"), merged["provider_presets"])
    merged["model_capabilities"] = _model_capabilities_with_provider_models(
        merged["model_capabilities"],
        merged["providers"],
    )
    # 保存/加载配置时使用完整模型目录，避免供应商临时未连接或连接测试失败时
    # 把用户已经选择的模型写成空值；真正执行任务时仍由运行时只使用 connected 供应商。
    _sync_defaults_with_model_config(merged, merged["model_capabilities"])
    return merged


def _load_template_library(
    path: Path,
    defaults: list[dict[str, Any]],
    *,
    builtin_source: str = "builtin",
) -> list[dict[str, Any]]:
    ensure_store()
    data = _read_json(path, defaults)
    if not isinstance(data, list):
        data = []
    changed = False
    default_ids = {str(item.get("id")) for item in defaults}
    default_by_id = {str(item.get("id")): item for item in defaults}
    active_data: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            changed = True
            continue
        if item.get("source") == builtin_source and str(item.get("id") or "") not in default_ids:
            changed = True
            continue
        normalized_item = copy.deepcopy(item)
        if normalized_item.get("source") == builtin_source and str(normalized_item.get("id") or "") in default_ids:
            if normalized_item != default_by_id.get(str(normalized_item.get("id") or "")):
                changed = True
            continue
        active_data.append(normalized_item)

    existing_by_id = {str(item.get("id")): item for item in active_data if item.get("id")}
    merged: list[dict[str, Any]] = []
    for default in defaults:
        if str(default.get("id")) not in {
            str(item.get("id") or "")
            for item in data
            if isinstance(item, dict)
        }:
            changed = True
        existing_by_id.pop(str(default.get("id")), None)
        merged.append(copy.deepcopy(default))
    merged.extend(item for item in active_data if str(item.get("id")) in existing_by_id)
    if changed:
        _write_json(path, merged)
    return merged


def load_script_adaptation_templates() -> list[dict[str, Any]]:
    return _load_template_library(
        GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH,
        DEFAULT_SCRIPT_ADAPTATION_TEMPLATES,
    )


def load_text_replacement_rules() -> list[dict[str, str]]:
    ensure_store()
    data = _read_json(GLOBAL_TEXT_REPLACEMENT_RULES_PATH, DEFAULT_TEXT_REPLACEMENT_RULES)
    rules = _normalize_text_replacement_rules(data)
    if rules != data:
        _write_json(GLOBAL_TEXT_REPLACEMENT_RULES_PATH, rules)
    return rules


def load_style_templates() -> list[dict[str, Any]]:
    from .projects import _favorite_style_thumbnail_fields
    from .projects import _favorite_style_thumbnail_path
    ensure_store()
    data = _read_json(GLOBAL_STYLE_TEMPLATES_PATH, DEFAULT_STYLE_TEMPLATES)
    if not isinstance(data, list):
        data = []
    favorites: list[dict[str, Any]] = []
    for item in data:
        if (
            not isinstance(item, dict)
            or item.get("category") != "favorite"
            or not str(item.get("id", "")).startswith("favorite_")
        ):
            continue
        favorite = copy.deepcopy(item)
        path = _favorite_style_thumbnail_path(favorite)
        if path and path.is_file():
            favorite.update(_favorite_style_thumbnail_fields(path.name, path))
        favorites.append(favorite)
    templates = [copy.deepcopy(item) for item in DEFAULT_STYLE_TEMPLATES]
    templates.extend(favorites)
    if data != templates:
        _write_json(GLOBAL_STYLE_TEMPLATES_PATH, templates)
    return templates

__all__ = (
    'load_global_config',
    'load_script_adaptation_templates',
    'load_text_replacement_rules',
    'load_style_templates',
)
