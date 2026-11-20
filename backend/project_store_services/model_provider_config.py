# -*- coding: utf-8 -*-
"""全局模型与供应商选择，以及项目智能体模型选择。"""
from __future__ import annotations

from .agent_sessions import _project_config_path
from .catalogs import BUILTIN_PROVIDER_MODELS
from .catalogs import DEFAULT_PROVIDER_PRESETS
from .provider_connections import _openai_compatible_discovery_base_url
from .provider_models import _align_provider_model_metadata
from .provider_models import _available_model_capabilities
from .provider_models import _empty_model_config
from .provider_models import _find_model
from .provider_models import _normalize_model_config
from .provider_models import _normalize_provider_id
from .provider_models import _provider_adapter_id
from .settings_loaders import load_global_config
from .settings_loaders import load_model_catalog
from .store_core import AI_VIDEO_AGENT_TASK_MAX_TOKENS
from .store_core import AI_VIDEO_AGENT_TASK_TEMPERATURE
from .store_core import _read_json
from typing import Any, Callable
import copy
import re

def _get_effective_config(project_id: str, feature_key: str | None = None) -> dict[str, Any]:
    from .project_management import get_effective_config

    return get_effective_config(project_id, feature_key)


def _video_generation_debug_block_enabled(project_id: str) -> bool:
    try:
        config = _get_effective_config(project_id)
    except Exception:
        return False
    video_config = config.get("video") if isinstance(config.get("video"), dict) else {}
    return bool(
        video_config.get("generation_debug_block_enabled")
        or video_config.get("generationDebugBlockEnabled")
        or video_config.get("block_generation_debug_mode")
        or video_config.get("blockGenerationDebugMode")
        or config.get("videoGenerationDebugBlockEnabled")
    )


def _configured_provider_for_model(model: dict[str, Any] | None, providers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if model and model.get("available") is False:
        return None
    provider_id = _normalize_provider_id((model or {}).get("provider_id"))
    if not provider_id:
        return None
    return next(
        (
            provider
            for provider in providers
            if _normalize_provider_id(provider.get("id")) == provider_id
        ),
        None,
    )


def _debug_block_builtin_video_provider_and_model(
    model_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return catalog provider/model only for blocked video prompt inspection."""
    needle = str(model_id or "").strip().lower()
    if not needle:
        return None, None
    for provider_id, models in BUILTIN_PROVIDER_MODELS.items():
        for row in models:
            if not isinstance(row, dict) or str(row.get("type") or "").strip().lower() != "video":
                continue
            aliases = {
                str(row.get("id") or "").strip().lower(),
                _api_model_name(row.get("id")).strip().lower(),
                str(row.get("label") or "").strip().lower(),
            }
            if needle not in {item for item in aliases if item}:
                continue
            provider = next(
                (
                    copy.deepcopy(preset)
                    for preset in DEFAULT_PROVIDER_PRESETS
                    if _normalize_provider_id(preset.get("id")) == _normalize_provider_id(provider_id)
                ),
                None,
            )
            model = copy.deepcopy(row)
            if provider:
                provider["configured"] = False
                provider["connection_status"] = "debug_block_catalog"
                provider.pop("api_key", None)
                model = _align_provider_model_metadata(provider, model)
            return provider, model
    return None, None


def _api_model_name(model_id: Any) -> str:
    text = str(model_id or "").strip()
    return text.split(":", 1)[1] if ":" in text else text


def _provider_base_url(provider: dict[str, Any]) -> str:
    base_url = str(provider.get("base_url") or provider.get("baseUrl") or "").strip()
    return base_url.rstrip("/")


def _openai_compatible_generation_base_url(
    provider: dict[str, Any],
    provider_id: str,
    base_url: str,
) -> str:
    if _provider_adapter_id(provider) == "openai-compatible":
        return _openai_compatible_discovery_base_url(base_url)
    if provider_id == "dashscope" and "/compatible-mode/v1" not in base_url:
        return f"{base_url.rstrip('/')}/compatible-mode/v1"
    if provider_id == "openai" and not re.search(r"/v\d+$", base_url):
        return f"{base_url.rstrip('/')}/v1"
    return base_url.rstrip("/")


def _project_model_config(project_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    global_config = load_global_config()
    capabilities = _available_model_capabilities(global_config)
    model_config = _normalize_model_config(
        global_config.get("model_config", _empty_model_config()), capabilities,
    )
    agent_model_id = _project_agent_model_id(project_id)
    if agent_model_id:
        model_config["agent"]["model_id"] = agent_model_id
    return global_config, capabilities, model_config


def _project_model_selection(project_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    capabilities, global_model_config = load_model_catalog()
    model_config = _normalize_model_config(global_model_config, capabilities)
    agent_model_id = _project_agent_model_id(project_id)
    if agent_model_id:
        model_config["agent"]["model_id"] = agent_model_id
    return capabilities, model_config


def _project_agent_model_id(project_id: str | None) -> str:
    cleaned_project_id = str(project_id or "").strip()
    if not cleaned_project_id:
        return ""
    project_config_path = _project_config_path(cleaned_project_id)
    if not project_config_path.exists():
        return ""
    project_config = _read_json(project_config_path, {})
    if not isinstance(project_config, dict):
        return ""
    return str(project_config.get("agent_model_id") or "").strip()


def _project_agent_reasoning_effort(project_id: str | None) -> str:
    from utils.model_reasoning import AGENT_REASONING_MODES

    cleaned_project_id = str(project_id or "").strip()
    if not cleaned_project_id:
        return ""
    project_config_path = _project_config_path(cleaned_project_id)
    if not project_config_path.exists():
        return ""
    project_config = _read_json(project_config_path, {})
    value = str(project_config.get("agent_reasoning_effort") or "").strip() if isinstance(project_config, dict) else ""
    return value if value in AGENT_REASONING_MODES else ""


def _agent_model_runtime_options(
    project_id: str,
    *,
    default_temperature: float = AI_VIDEO_AGENT_TASK_TEMPERATURE,
    default_max_tokens: int = AI_VIDEO_AGENT_TASK_MAX_TOKENS,
    max_tokens_cap: int | None = None,
) -> tuple[float, int]:
    _ = project_id
    temperature = default_temperature
    max_tokens = default_max_tokens
    if max_tokens_cap is not None:
        max_tokens = min(max_tokens, max_tokens_cap)
    return temperature, max_tokens


def _configured_media_model(
    project_id: str | None,
    media_type: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    global_config, capabilities, model_config = _project_model_config(project_id)
    section = model_config.get(media_type) if isinstance(model_config.get(media_type), dict) else {}
    model = _find_model(str(section.get("model_id") or ""), media_type, capabilities)
    provider = _configured_provider_for_model(model, global_config.get("providers", []))
    if isinstance(provider, dict) and isinstance(model, dict):
        model = _align_provider_model_metadata(provider, model)
    return provider, model, model_config


def _configured_text_model(
    project_id: str | None,
    model_section: str,
    model_key: str = "model_id",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    global_config, capabilities, model_config = _project_model_config(project_id)
    section = model_config.get(model_section) if isinstance(model_config.get(model_section), dict) else {}
    model_id = str(section.get(model_key) or "").strip()
    model_type = "agent" if model_section == "agent" else "text"
    model = _find_model(model_id, model_type, capabilities)
    provider = _configured_provider_for_model(model, global_config.get("providers", []))
    return provider, model, model_config
