# -*- coding: utf-8 -*-
"""供应商增删改、模型发现、连接测试和探针。"""

from __future__ import annotations

from utils.model_reasoning import apply_model_reasoning

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
from typing import Any, Callable
from utils.generation_requests import GenerationCancelled, run_cancellable_model_request

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
from utils.model_timeouts import MODEL_PROVIDER_PROBE_TIMEOUT_SECONDS


from .catalogs import DEFAULT_PROVIDER_PRESETS
from .store_core import _deep_merge
from .store_core import _mask_key
from .store_core import _now
from .store_core import _serialized_global_config_write

def list_providers() -> dict[str, Any]:
    from .projects import _public_provider
    from .settings_loaders import load_global_config
    config = load_global_config()
    return {
        "providers": [_public_provider(provider) for provider in config.get("providers", [])],
        "presets": [
            _public_provider(preset)
            for preset in config.get("provider_presets", [])
            if not preset.get("hidden")
        ],
    }


def _build_provider_from_add_payload(
    config: dict[str, Any],
    payload: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .provider_models import _normalize_provider_adapter_id
    from .provider_models import _normalize_provider_capabilities
    from .provider_models import _normalize_provider_id
    from .provider_models import _provider_model_matches_capabilities
    from .provider_models import _provider_service_id
    presets = config.get("provider_presets", DEFAULT_PROVIDER_PRESETS)
    existing = existing or {}
    explicit_provider_id = _normalize_provider_id(payload.get("providerId") or payload.get("provider_id"))
    explicit_preset_id = _normalize_provider_id(payload.get("presetId") or payload.get("preset_id"))
    if not explicit_preset_id and explicit_provider_id and existing:
        explicit_preset_id = _provider_service_id(existing)
    preset_id = _normalize_provider_id(
        explicit_preset_id or payload.get("id") or explicit_provider_id
    )
    preset = next((item for item in presets if item.get("id") == preset_id), None)
    if preset is None:
        raise ValueError("供应商预设不存在")
    adapter_id = _normalize_provider_adapter_id(
        payload.get("adapterId")
        or payload.get("adapter_id")
        or preset.get("adapter_id")
        or existing.get("adapter_id")
        or preset_id
    )

    models = _provider_models_from_payload(payload, preset or existing or {})
    provider_id = explicit_provider_id or preset_id or f"provider-{uuid.uuid4().hex[:8]}"

    base = copy.deepcopy(preset or existing or {})
    payload_has_capabilities = "capabilities" in payload
    raw_capabilities = (
        payload.get("capabilities")
        if payload_has_capabilities
        else base.get("capabilities", [])
    )
    capabilities = _normalize_provider_capabilities(
        raw_capabilities, supported=preset.get("capabilities"),
    )
    models = [
        model
        for model in models
        if isinstance(model, dict)
        and _provider_model_matches_capabilities(model, list(capabilities))
    ]
    base.update(
        {
            "id": provider_id,
            "adapter_id": adapter_id,
            "preset_id": preset_id if preset else existing.get("preset_id") or existing.get("presetId") or "",
            "official_title": preset.get("title") if preset else base.get("official_title") or "",
            "title": payload.get("title") or base.get("title") or "供应商实例",
            "logo": payload.get("logo") or base.get("logo") or str(payload.get("title") or "API")[:3].upper(),
            "description": payload.get("description") or base.get("description") or "供应商实例",
            "base_url": payload.get("baseUrl") or payload.get("base_url") or base.get("base_url") or "",
            "default_base_url": base.get("base_url") or "",
            "base_url_options": payload.get("baseUrlOptions") or payload.get("base_url_options") or base.get("base_url_options") or [],
            "base_url_note": payload.get("baseUrlNote") or payload.get("base_url_note") or base.get("base_url_note") or "",
            "docs_url": payload.get("docsUrl") or payload.get("docs_url") or base.get("docs_url") or "",
            "key_label": payload.get("keyLabel") or payload.get("key_label") or base.get("key_label") or "API_KEY",
            "capabilities": capabilities,
            "models": models,
            "probe_summary": {},
            "native_structured_output": "unknown",
            "user_added": True,
            "added_at": existing.get("added_at") or _now(),
        }
    )
    incoming_key = str(payload.get("apiKey") or payload.get("api_key") or "").strip()
    api_key = incoming_key or (str(existing.get("api_key") or "") if explicit_provider_id else "")
    base["api_key"] = api_key
    base["api_key_masked"] = _mask_key(api_key)
    base["configured"] = bool(api_key)
    base["connection_status"] = "untested" if api_key else "unconfigured"
    base["last_test"] = None
    return base


def _provider_models_from_payload(payload: dict[str, Any], fallback: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        raw_models = payload.get("availableModels") or payload.get("available_models")
    if not isinstance(raw_models, list):
        last_test = payload.get("lastTest") or payload.get("last_test")
        if isinstance(last_test, dict):
            raw_models = last_test.get("availableModels") or last_test.get("available_models")
    if not isinstance(raw_models, list):
        raw_models = (fallback or {}).get("models") or []
    return [copy.deepcopy(model) for model in raw_models if isinstance(model, dict)]


def _extract_provider_model_ids(data: Any) -> list[str]:
    from .provider_models import _remote_model_entry_id
    return [
        _remote_model_entry_id(item)
        for item in _extract_provider_model_rows(data)
        if _remote_model_entry_id(item)
    ]


def _extract_provider_model_rows(data: Any) -> list[dict[str, Any]]:
    from .provider_models import _remote_model_entry_id
    if not isinstance(data, dict):
        return []
    rows = data.get("data")
    if not isinstance(rows, list):
        rows = data.get("models") if isinstance(data.get("models"), list) else []
    models: list[dict[str, Any]] = []
    for item in rows:
        if isinstance(item, dict):
            model_id = _remote_model_entry_id(item)
            if not model_id:
                continue
            model = copy.deepcopy(item)
            model["model_id"] = model_id
            if "id" not in model:
                model["id"] = model_id
            models.append(model)
        elif isinstance(item, str):
            model_id = _remote_model_entry_id(item)
            if model_id:
                models.append({"id": model_id, "model_id": model_id})
    return models


def _response_json_for_log(raw: str) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"rawResponseText": raw}


def _notify_response_received(callback: Callable[[Any], None] | None, value: Any) -> None:
    if not callable(callback):
        return
    try:
        callback(copy.deepcopy(value))
    except Exception:
        pass


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
    timeout: int = MODEL_PROVIDER_PROBE_TIMEOUT_SECONDS,
    on_response_received: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        _notify_response_received(on_response_received, _response_json_for_log(detail))
        raise RuntimeError(f"HTTP {exc.code}: {detail[:800] or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason or exc)) from exc
    try:
        document = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        _notify_response_received(on_response_received, _response_json_for_log(raw))
        raise
    _notify_response_received(on_response_received, document)
    return document


def _deepseek_discovery_root(base_url: str) -> str:
    root = (base_url or "https://api.deepseek.com/anthropic").rstrip("/")
    for suffix in ("/anthropic/v1", "/anthropic", "/v1"):
        if root.endswith(suffix):
            return root[: -len(suffix)] or root
    return root


def _provider_default_base_url(provider_id: str) -> str:
    defaults = {
        "anthropic": "https://api.anthropic.com",
        "ark-seedance": "https://ark.cn-beijing.volces.com/api/v3",
        "ark-agent-plan": "https://ark.cn-beijing.volces.com/api/plan",
        "deepseek": "https://api.deepseek.com/anthropic",
        "minimax": "https://api.minimax.cn/anthropic",
        "gemini": "https://generativelanguage.googleapis.com",
        "vidu": "https://api.vidu.com/ent/v2",
        "dashscope": "https://dashscope.aliyuncs.com",
        "grok": "https://api.x.ai/v1",
        "custom-provider": "",
    }
    return defaults.get(provider_id, "")


def _provider_default_text_model(provider: dict[str, Any]) -> str:
    from .model_provider_config import _api_model_name
    for model in provider.get("models", []):
        if not isinstance(model, dict) or model.get("type") != "text":
            continue
        model_id = str(model.get("id") or model.get("label") or "").strip()
        return _api_model_name(model_id)
    return "model"


def _anthropic_messages_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1/messages"):
        return base
    if base.endswith("/v1"):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def _anthropic_models_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1/models"):
        return base
    if base.endswith("/v1"):
        return f"{base}/models"
    return f"{base}/v1/models"


def _anthropic_auth_headers(provider: dict[str, Any], api_key: str) -> dict[str, str]:
    from .provider_models import _provider_adapter_id
    from .model_provider_config import _provider_base_url
    from .provider_models import _provider_service_id
    provider_id = _provider_service_id(provider)
    base_url = _provider_base_url(provider)
    headers = {"anthropic-version": "2023-06-01"}
    if provider_id in {"deepseek", "minimax", "ark-agent-plan"} or (
        _provider_adapter_id(provider) == "anthropic-compatible"
        and base_url
        and "anthropic.com" not in base_url.lower()
    ):
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        headers["x-api-key"] = api_key
    return headers


_ANTHROPIC_AUTH_TOKEN_GATEWAY_PATHS: dict[str, tuple[str, ...]] = {
    "api.deepseek.com": ("/anthropic",),
    "open.bigmodel.cn": ("/api/anthropic",),
    "api.z.ai": ("/api/anthropic",),
    "api.minimax.io": ("/anthropic",),
    "api.minimaxi.com": ("/anthropic",),
    "api.minimax.cn": ("/anthropic",),
    "api.moonshot.ai": ("/anthropic",),
    "api.moonshot.cn": ("/anthropic",),
    "ark.cn-beijing.volces.com": ("/api/coding", "/api/plan"),
}

_ANTHROPIC_MESSAGES_GATEWAY_PATHS: dict[str, tuple[str, ...]] = {
    "api.qnaigc.com": ("/bypass/anthropic",),
    "api.modelink.ai": ("/bypass/anthropic",),
}


def _looks_like_anthropic_auth_token_gateway(base_url: str | None) -> bool:
    raw = str(base_url or "").strip()
    if not raw:
        return False
    parsed = urllib.parse.urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host == "api.anthropic.com":
        return False
    expected_paths = _ANTHROPIC_AUTH_TOKEN_GATEWAY_PATHS.get(host)
    if expected_paths is None:
        return False
    path = "/" + (parsed.path or "").strip("/")
    return any(path == expected or path.startswith(f"{expected}/") for expected in expected_paths)


def _anthropic_sdk_base_url(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    for suffix in ("/v1/messages", "/v1"):
        if base.endswith(suffix):
            return base[: -len(suffix)].rstrip("/")
    return base


def _anthropic_messages_auth_headers(
    provider: dict[str, Any], api_key: str, base_url: str,
) -> dict[str, str]:
    summary = provider.get("probe_summary") if isinstance(provider.get("probe_summary"), dict) else {}
    last_test = provider.get("last_test") if isinstance(provider.get("last_test"), dict) else {}
    if not summary:
        summary = last_test.get("probeSummary") if isinstance(last_test.get("probeSummary"), dict) else {}
    # Authentication evidence is reusable only for the same Messages endpoint.
    url = _anthropic_messages_url(base_url)
    evidence = [
        (summary.get("nativeJsonSchemaUrl"), summary.get("nativeJsonSchemaAuthMode")),
        (_provider_claude_agent_base_url(provider), _provider_claude_agent_auth_mode(provider)),
    ]
    for verified_base, auth_mode in evidence:
        if not verified_base or _anthropic_messages_url(str(verified_base)) != url:
            continue
        if auth_mode == "bearer":
            return {"anthropic-version": "2023-06-01", "Authorization": f"Bearer {api_key}"}
        if auth_mode == "x-api-key":
            return {"anthropic-version": "2023-06-01", "x-api-key": api_key}
    return _anthropic_auth_headers(provider, api_key)


def _provider_claude_agent_base_url(provider: dict[str, Any]) -> str:
    summary = provider.get("probe_summary") if isinstance(provider.get("probe_summary"), dict) else {}
    if not summary:
        last_test = provider.get("last_test") if isinstance(provider.get("last_test"), dict) else {}
        summary = last_test.get("probeSummary") if isinstance(last_test.get("probeSummary"), dict) else {}
    if isinstance(summary, dict):
        base_url = str(summary.get("claudeAgentBaseUrl") or summary.get("claude_agent_base_url") or "").strip()
        if base_url:
            return base_url.rstrip("/")
    return ""


def _provider_claude_agent_model(provider: dict[str, Any]) -> str:
    summary = provider.get("probe_summary") if isinstance(provider.get("probe_summary"), dict) else {}
    if not summary:
        last_test = provider.get("last_test") if isinstance(provider.get("last_test"), dict) else {}
        summary = last_test.get("probeSummary") if isinstance(last_test.get("probeSummary"), dict) else {}
    if isinstance(summary, dict):
        return str(summary.get("claudeAgentModel") or summary.get("claude_agent_model") or "").strip()
    return ""


def _provider_claude_agent_auth_mode(provider: dict[str, Any]) -> str:
    summary = provider.get("probe_summary") if isinstance(provider.get("probe_summary"), dict) else {}
    last_test = provider.get("last_test") if isinstance(provider.get("last_test"), dict) else {}
    if not summary:
        summary = last_test.get("probeSummary") if isinstance(last_test.get("probeSummary"), dict) else {}
    if isinstance(summary, dict):
        auth_mode = str(summary.get("claudeAgentAuthMode") or summary.get("claude_agent_auth_mode") or "").strip()
        if auth_mode in {"bearer", "x-api-key"}:
            return auth_mode
    probe = _claude_agent_sdk_probe_from_result(last_test)
    if isinstance(probe, dict):
        auth_mode = str(probe.get("authMode") or "").strip()
        if auth_mode in {"bearer", "x-api-key"}:
            return auth_mode
    return ""


def _anthropic_sdk_env(provider: dict[str, Any], api_key: str, model_name: str) -> dict[str, str]:
    from .model_provider_config import _provider_base_url
    from .provider_models import _provider_service_id
    base_url = (
        _provider_claude_agent_base_url(provider)
        or _provider_base_url(provider)
        or _provider_default_base_url(_provider_service_id(provider))
    )
    agent_auth_mode = _provider_claude_agent_auth_mode(provider)
    use_auth_token = (
        agent_auth_mode == "bearer"
        or (not agent_auth_mode and _looks_like_anthropic_auth_token_gateway(base_url))
    )
    env = {
        "ANTHROPIC_API_KEY": "" if use_auth_token else api_key,
        "ANTHROPIC_AUTH_TOKEN": api_key if use_auth_token else "",
        "ANTHROPIC_BASE_URL": _anthropic_sdk_base_url(base_url),
        "ANTHROPIC_MODEL": model_name,
        # SDK auxiliary turns must use this instance's selected model, not an
        # inherited alias or a gateway's default small model.
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": model_name,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model_name,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": model_name,
        "ANTHROPIC_SMALL_FAST_MODEL": model_name,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    return env


def _http_url_base(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if base and not re.match(r"^[a-z][a-z0-9+.-]*://", base, flags=re.IGNORECASE):
        base = f"https://{base}"
    return base


def _openai_compatible_discovery_base_url(base_url: str) -> str:
    base = _http_url_base(base_url)
    if base.endswith("/models"):
        base = base[: -len("/models")].rstrip("/")
    if re.search(r"/v\d+$", base):
        return base
    return f"{base}/v1"


def _google_discovery_root_url(base_url: str) -> str:
    base = _http_url_base(base_url)
    if base.endswith("/models"):
        base = base[: -len("/models")].rstrip("/")
    return re.sub(r"/v\d+\w*$", "", base).rstrip("/")


def _provider_declares_agent_capability(provider: dict[str, Any]) -> bool:
    capabilities = provider.get("capabilities")
    return isinstance(capabilities, list) and "agent" in {str(item) for item in capabilities if item}


def _provider_declares_text_capability(provider: dict[str, Any]) -> bool:
    from .provider_models import _normalize_provider_capabilities
    capabilities = provider.get("capabilities")
    if not isinstance(capabilities, list):
        return False
    return "text_generation" in _normalize_provider_capabilities(capabilities)


def _normalized_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def _candidate_anthropic_agent_base_urls(provider: dict[str, Any]) -> list[str]:
    from .provider_models import _provider_adapter_id
    from .model_provider_config import _provider_base_url
    from .provider_models import _provider_service_id
    provider_id = _provider_service_id(provider)
    raw_base = _provider_base_url(provider) or _provider_default_base_url(provider_id)
    base = _http_url_base(raw_base)
    if not base:
        return []

    adapter_id = _provider_adapter_id(provider)
    roots: list[str] = []

    def add(value: str) -> None:
        normalized = _normalized_url(value)
        if normalized and normalized not in roots:
            roots.append(normalized)

    add(base)
    sdk_base = _anthropic_sdk_base_url(base)
    add(sdk_base)

    parsed = urllib.parse.urlparse(sdk_base)
    if parsed.scheme and parsed.netloc:
        origin = f"{parsed.scheme}://{parsed.netloc}"
        for path in _ANTHROPIC_MESSAGES_GATEWAY_PATHS.get((parsed.hostname or "").lower(), ()):
            add(f"{origin}{path}")
    else:
        origin = ""

    if adapter_id != "anthropic-compatible":
        if parsed.scheme and parsed.netloc:
            add(f"{origin}/anthropic")
            add(f"{origin}/api/anthropic")
            if parsed.path.strip("/"):
                add(f"{sdk_base}/anthropic")
        else:
            add(f"{sdk_base}/anthropic")
            add(f"{sdk_base}/api/anthropic")
    return roots


def _anthropic_probe_auth_headers(provider: dict[str, Any], api_key: str) -> list[dict[str, str]]:
    candidates = [
        _anthropic_auth_headers(provider, api_key),
        {"anthropic-version": "2023-06-01", "Authorization": f"Bearer {api_key}"},
        {"anthropic-version": "2023-06-01", "x-api-key": api_key},
    ]
    seen: set[tuple[tuple[str, str], ...]] = set()
    unique: list[dict[str, str]] = []
    for headers in candidates:
        key = tuple(sorted((str(name).lower(), str(value)) for name, value in headers.items()))
        if key in seen:
            continue
        seen.add(key)
        unique.append(headers)
    return unique


def _provider_probe_url_and_headers(provider: dict[str, Any]) -> tuple[str, dict[str, str], str]:
    from .provider_models import _provider_adapter_id
    from .model_provider_config import _provider_base_url
    from .provider_models import _provider_service_id
    provider_id = _provider_service_id(provider)
    adapter_id = _provider_adapter_id(provider)
    api_key = str(provider.get("api_key") or "").strip()
    base_url = _provider_base_url(provider)
    if adapter_id in {"openai-compatible", "newapi-video"}:
        base = _openai_compatible_discovery_base_url(base_url or _provider_default_base_url("openai"))
        return (
            f"{base}/models",
            {"Authorization": f"Bearer {api_key}"},
            "models.list",
        )
    if adapter_id == "anthropic-compatible":
        base = (
            _deepseek_discovery_root(base_url)
            if provider_id == "deepseek"
            else base_url or _provider_default_base_url(provider_id)
        )
        headers = _anthropic_auth_headers(provider, api_key)
        return (
            _anthropic_models_url(base),
            headers,
            "models.list",
        )
    if adapter_id == "gemini-compatible":
        base = base_url or _provider_default_base_url(provider_id)
        return (
            f"{base}/v1beta/models",
            {"x-goog-api-key": api_key},
            "models.list",
        )
    if provider_id == "vidu":
        base = base_url or _provider_default_base_url(provider_id)
        return (
            f"{base}/tasks/0/creations",
            {"Authorization": f"Token {api_key}"},
            "tasks.get",
        )
    if provider_id == "dashscope":
        base = base_url or _provider_default_base_url(provider_id)
        if "/compatible-mode/v1" not in base:
            base = f"{base}/compatible-mode/v1"
        return (
            f"{base}/models",
            {"Authorization": f"Bearer {api_key}"},
            "models.list",
        )
    base = base_url or _provider_default_base_url(provider_id)
    return (
        f"{base}/models",
        {"Authorization": f"Bearer {api_key}"},
        "models.list",
    )


_CLAUDE_AGENT_SDK_PROBE_NAME = "claude_agent_sdk.messages.create"
_NATIVE_JSON_SCHEMA_PROBE_NAME = "native_json_schema.response_format"
_NATIVE_JSON_SCHEMA_PROBE_SCHEMA: dict[str, Any] = {
    "name": "native_json_schema_probe",
    "description": "供应商原生 JSON Schema 结构化输出探测。",
    "fields": [
        {"name": "ok", "type": "boolean", "required": True},
        {"name": "label", "type": "string", "required": True},
    ],
}


def _claude_agent_sdk_probe_from_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    probes = result.get("probes")
    if not isinstance(probes, list):
        return None
    for probe in probes:
        if not isinstance(probe, dict):
            continue
        name = str(probe.get("name") or "")
        if name == _CLAUDE_AGENT_SDK_PROBE_NAME:
            return probe
    return None


def _native_json_schema_probe_from_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    probes = result.get("probes")
    if not isinstance(probes, list):
        return None
    candidates = [probe for probe in probes if isinstance(probe, dict) and probe.get("name") == _NATIVE_JSON_SCHEMA_PROBE_NAME]
    return next((probe for probe in candidates if probe.get("status") == "ok"), candidates[-1] if candidates else None)


def _validate_native_json_schema_probe_text(text: str) -> None:
    from .model_text_client import _extract_json_payload
    from .projects import _normalize_structured_payload
    data = _extract_json_payload(text)
    if not isinstance(data, dict):
        raise RuntimeError("native_json_schema response is not JSON object")
    normalized, errors = _normalize_structured_payload(data, _NATIVE_JSON_SCHEMA_PROBE_SCHEMA)
    if errors:
        raise RuntimeError("；".join(errors))
    if normalized.get("ok") is not True:
        raise RuntimeError("native_json_schema response missing ok=true")


def _extract_anthropic_probe_response_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    content = data.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = str(item.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _native_json_schema_probe_model(provider: dict[str, Any], model: dict[str, Any] | Any | None = None) -> str:
    from .projects import _structured_model_api_name
    if isinstance(model, dict) and model.get("api_model_id"):
        return str(model["api_model_id"])
    return _structured_model_api_name(model) or _provider_default_text_model(provider)


def _native_schema_error_status(exc: Exception) -> str:
    # Transport/auth/quota errors say nothing about support for the schema parameter.
    match = re.search(r"HTTP\s+(400|422):\s*(\{.*\})", str(exc), re.S)
    if not match:
        return "unknown"
    try:
        payload = json.loads(match.group(2))
    except (ValueError, TypeError):
        return "unknown"
    if not isinstance(payload, dict):
        return "unknown"
    error = payload.get("error", payload)
    if not isinstance(error, dict):
        return "unknown"
    param = str(error.get("param") or "")
    code = str(error.get("code") or error.get("type") or "")
    fields = ("response_format", "text.format", "output_config.format", "output_format", "responseJsonSchema", "responseSchema")
    if any(param == field or param.startswith(field + ".") for field in fields) and code in {
        "unsupported_parameter", "unsupported_value", "unsupported_response_format", "not_supported",
    }:
        return "unsupported"
    return "unknown"


def _probe_request_timeout(deadline: float | None) -> float:
    if deadline is None:
        return MODEL_PROVIDER_PROBE_TIMEOUT_SECONDS
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("configuration_probe_budget_exhausted")
    return min(remaining, MODEL_PROVIDER_PROBE_TIMEOUT_SECONDS)


def _probe_json_request(method: str, url: str, *, headers: dict[str, str],
                        data: dict[str, Any], timeout: float,
                        on_exchange: Callable[[dict[str, Any]], Any] | None = None) -> Any:
    """Observe each probe attempt, including auth/endpoint retries and failures."""
    if on_exchange is None:
        return _request_json(method, url, headers=headers, data=data, timeout=timeout)
    from utils.sdk_request_capture import _redact, _AUTH_HEADERS, _url_secrets

    secrets = {value for key, value in headers.items() if key.casefold() in _AUTH_HEADERS}
    secrets.update(value.split(" ", 1)[1] for key, value in headers.items()
                   if key.casefold() == "authorization" and " " in value)
    secrets.update(_url_secrets(url))
    request_id = uuid.uuid4().hex
    response: Any = None
    error = ""
    def received(value: Any) -> None:
        nonlocal response
        response = value
    try:
        response = _request_json(method, url, headers=headers, data=data, timeout=timeout,
                                 on_response_received=received)
        return response
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        exchange = _redact({"executed": True, "success": not bool(error), "error": error,
            "requestInfo": {"transport": "http", "method": method, "url": url,
                "requestBody": data, "captureLevel": "api_outbound", "captureSource": "ai_video_http",
                "requestPurpose": "capability_probe", "requestId": request_id},
            "data": response}, secrets)
        try:
            on_exchange(exchange)
        except Exception:
            traceback.print_exc()


def _run_openai_native_json_schema_probe(
    provider: dict[str, Any],
    model: dict[str, Any] | Any | None = None,
    *,
    check_cancelled: Callable[[], None] | None = None,
    deadline: float | None = None,
    on_exchange: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    from .provider_models import _adapter_endpoint_format
    from .model_text_client import _extract_response_text
    from .model_provider_config import _openai_compatible_generation_base_url
    from .model_provider_config import _provider_base_url
    from .provider_models import _provider_service_id
    from .projects import _structured_response_format
    api_key = str(provider.get("api_key") or "").strip()
    provider_id = _provider_service_id(provider)
    base_url = _provider_base_url(provider) or _provider_default_base_url(provider_id)
    generation_base_url = _openai_compatible_generation_base_url(provider, provider_id, base_url)
    probe_model = _native_json_schema_probe_model(provider, model)
    schema = copy.deepcopy(_NATIVE_JSON_SCHEMA_PROBE_SCHEMA)
    prompt = "Return a JSON object with ok=true and label=\"probe\"."
    endpoint_hint = (model.get("endpoint") if isinstance(model, dict) else "") or infer_model_endpoint(
        probe_model,
        _adapter_endpoint_format(provider),
        provider=provider,
    )
    endpoints = (
        ["openai-responses", "openai-chat"]
        if normalize_media_endpoint(endpoint_hint) == "openai-responses"
        else ["openai-chat", "openai-responses"]
    )
    if isinstance(model, dict) and model.get("supported_endpoint_types") and (
        model.get("endpoint_constraints") or model.get("routing_source") != "relay-discovery"
    ):
        endpoints = [endpoint for endpoint in endpoints if endpoint in model["supported_endpoint_types"]]
    errors: list[str] = []
    statuses: list[str] = []
    for endpoint in endpoints:
        try:
            if endpoint == "openai-responses":
                response_format = _structured_response_format(schema, api="responses")
                payload = {
                    "model": probe_model,
                    "input": [{"role": "user", "content": prompt}],
                    "max_output_tokens": 256,
                    "text": {"format": response_format},
                }
                url = f"{generation_base_url}/responses"
            else:
                response_format = _structured_response_format(schema, api="chat")
                payload = {
                    "model": probe_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 256,
                    "response_format": response_format,
                }
                url = f"{generation_base_url}/chat/completions"
            apply_model_reasoning(
                payload, base_url=generation_base_url, model=probe_model,
                endpoint=endpoint, task="structured-probe",
            )
            data = run_cancellable_model_request(
                lambda: _probe_json_request(
                    "POST",
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    data=payload,
                    timeout=_probe_request_timeout(deadline),
                    on_exchange=on_exchange,
                ),
                check_cancelled,
            )
            _probe_request_timeout(deadline)
            text = _extract_response_text(data)
            _validate_native_json_schema_probe_text(text)
            return {
                "name": _NATIVE_JSON_SCHEMA_PROBE_NAME,
                "status": "ok",
                "url": url,
                "endpoint": endpoint,
                "model": probe_model,
            }
        except GenerationCancelled:
            raise
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")
            if deadline is not None and time.monotonic() >= deadline:
                errors.append("configuration_probe_budget_exhausted")
                statuses.append("unknown")
                break
            statuses.append(_native_schema_error_status(exc))
            if re.search(r"HTTP\s+(401|402|403|429):", str(exc)):
                break
    return {
        "name": _NATIVE_JSON_SCHEMA_PROBE_NAME,
        "status": "unsupported" if statuses and all(status == "unsupported" for status in statuses) else "unknown",
        "error": errors[-1] if errors else "native_json_schema_probe_failed",
        "attempts": errors[-4:],
        "model": probe_model,
        "endpoint": endpoints[0] if len(endpoints) == 1 else "",
    }


def _run_gemini_native_json_schema_probe(
    provider: dict[str, Any],
    model: dict[str, Any] | Any | None = None,
    *,
    check_cancelled: Callable[[], None] | None = None,
    deadline: float | None = None,
    on_exchange: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    from .model_text_client import _extract_gemini_response_text
    from .model_provider_config import _provider_base_url
    from .provider_models import _provider_service_id
    from .projects import _structured_response_format
    api_key = str(provider.get("api_key") or "").strip()
    provider_id = _provider_service_id(provider)
    base_url = _provider_base_url(provider) or _provider_default_base_url(provider_id)
    root = _google_discovery_root_url(base_url)
    probe_model = _native_json_schema_probe_model(provider, model)
    model_resource = probe_model if probe_model.startswith("models/") else f"models/{probe_model}"
    url = f"{root}/v1beta/{model_resource}:generateContent"
    schema = copy.deepcopy(_NATIVE_JSON_SCHEMA_PROBE_SCHEMA)
    response_format = _structured_response_format(schema, api="gemini-generate")
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "Return ok=true and label=probe."}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 256,
        },
    }
    if response_format:
        payload["generationConfig"].update(response_format)
    try:
        data = run_cancellable_model_request(
            lambda: _probe_json_request(
                "POST",
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                data=payload,
                timeout=_probe_request_timeout(deadline),
                on_exchange=on_exchange,
            ),
            check_cancelled,
        )
        _probe_request_timeout(deadline)
        text = _extract_gemini_response_text(data)
        _validate_native_json_schema_probe_text(text)
        return {
            "name": _NATIVE_JSON_SCHEMA_PROBE_NAME,
            "status": "ok",
            "url": url,
            "endpoint": "gemini-generate",
            "model": probe_model,
        }
    except GenerationCancelled:
        raise
    except Exception as exc:
        return {
            "name": _NATIVE_JSON_SCHEMA_PROBE_NAME,
            "status": "unknown" if deadline is not None and time.monotonic() >= deadline else _native_schema_error_status(exc),
            "url": url,
            "endpoint": "gemini-generate",
            "error": str(exc),
            "model": probe_model,
        }


def _run_anthropic_native_json_schema_probe(
    provider: dict[str, Any],
    model: dict[str, Any] | Any | None = None,
    *,
    check_cancelled: Callable[[], None] | None = None,
    deadline: float | None = None,
    on_exchange: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    from .model_provider_config import _provider_base_url
    from .provider_models import _provider_service_id
    from .projects import _structured_response_format
    from utils.text_model_contracts import anthropic_sampling_parameters
    api_key = str(provider.get("api_key") or "").strip()
    provider_id = _provider_service_id(provider)
    base_url = _provider_base_url(provider) or _provider_default_base_url(provider_id)
    probe_model = _native_json_schema_probe_model(provider, model)
    schema = copy.deepcopy(_NATIVE_JSON_SCHEMA_PROBE_SCHEMA)
    response_format = _structured_response_format(schema, api="anthropic-messages")
    payload = {
        "model": probe_model,
        # Anthropic-compatible thinking models count thinking and final text
        # in the same budget.  256 is enough for a plain model but can end
        # before the required JSON object is emitted.
        "max_tokens": 2048,
        **anthropic_sampling_parameters(probe_model, 0),
        "messages": [{"role": "user", "content": "Return ok=true and label=probe."}],
    }
    if response_format:
        payload["output_config"] = response_format
    url = _anthropic_messages_url(base_url)
    auth_mode = ""
    apply_model_reasoning(
        payload, base_url=base_url, model=probe_model,
        endpoint="anthropic-messages", task="structured-probe",
    )
    try:
        for headers in _anthropic_probe_auth_headers(provider, api_key):
            candidate_mode = "bearer" if "Authorization" in headers else "x-api-key"
            try:
                data = run_cancellable_model_request(
                    lambda: _probe_json_request(
                        "POST", url, headers=headers, data=payload,
                        timeout=_probe_request_timeout(deadline),
                        on_exchange=on_exchange,
                    ),
                    check_cancelled,
                )
                _probe_request_timeout(deadline)
                auth_mode = candidate_mode
                break
            except GenerationCancelled:
                raise
            except Exception as exc:
                _probe_request_timeout(deadline)
                if re.search(r"HTTP\s+401:", str(exc)):
                    continue
                if _native_schema_error_status(exc) == "unsupported":
                    auth_mode = candidate_mode
                raise
        else:
            raise RuntimeError("HTTP 401: Anthropic 接口鉴权失败")
        text = _extract_anthropic_probe_response_text(data)
        _validate_native_json_schema_probe_text(text)
        return {
            "name": _NATIVE_JSON_SCHEMA_PROBE_NAME,
            "status": "ok",
            "url": url,
            "endpoint": "anthropic-messages",
            "model": probe_model,
            "authMode": auth_mode,
        }
    except GenerationCancelled:
        raise
    except Exception as exc:
        return {
            "name": _NATIVE_JSON_SCHEMA_PROBE_NAME,
            "status": _native_schema_error_status(exc),
            "url": url,
            "endpoint": "anthropic-messages",
            "error": str(exc),
            "model": probe_model,
            **({"authMode": auth_mode} if auth_mode else {}),
        }


def _run_native_json_schema_probe(
    provider: dict[str, Any],
    model: dict[str, Any] | Any | None = None,
    *,
    check_cancelled: Callable[[], None] | None = None,
    deadline: float | None = None,
    on_exchange: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    from .provider_models import _text_model_generation_endpoint
    if check_cancelled:
        check_cancelled()
    if not _provider_declares_text_capability(provider):
        return {
            "name": _NATIVE_JSON_SCHEMA_PROBE_NAME,
            "status": "unsupported",
            "error": "no_text_capability",
        }
    api_key = str(provider.get("api_key") or "").strip()
    if not api_key:
        return {
            "name": _NATIVE_JSON_SCHEMA_PROBE_NAME,
            "status": "unknown",
            "error": "missing_api_key",
        }
    probe_model = dict(model) if isinstance(model, dict) else {"id": _native_json_schema_probe_model(provider, model)}
    endpoint = _text_model_generation_endpoint(provider, probe_model)
    model = {**probe_model, "endpoint": endpoint}
    options = {"check_cancelled": check_cancelled}
    if on_exchange is not None:
        options["on_exchange"] = on_exchange
    if deadline is not None:
        options["deadline"] = deadline
    if endpoint == "gemini-generate":
        return _run_gemini_native_json_schema_probe(provider, model, **options)
    if endpoint == "anthropic-messages":
        return _run_anthropic_native_json_schema_probe(provider, model, **options)
    return _run_openai_native_json_schema_probe(provider, model, **options)


def _run_vidu_connection_test(provider: dict[str, Any]) -> dict[str, Any]:
    from .provider_models import _provider_available_models_for_test
    from .model_provider_config import _provider_base_url
    now = _now()
    api_key = str(provider.get("api_key") or "").strip()
    base_url = _provider_base_url(provider) or _provider_default_base_url("vidu")
    url = f"{base_url}/tasks/0/creations"
    started = time.perf_counter()
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Token {api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=MODEL_PROVIDER_PROBE_TIMEOUT_SECONDS) as response:
            detail = response.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {response.status}: 连接测试无法判定（{detail[:200]}）")
    except urllib.error.HTTPError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404:
            return _with_provider_probe_summary(provider, {
                "overall": "ok",
                "status": "connected",
                "message": "联通成功：Vidu 鉴权通过，测试任务不存在符合预期。",
                "error": "",
                "checkedAt": now,
                "latencyMs": latency_ms,
                "availableModels": _provider_available_models_for_test(provider),
                "capabilities": provider.get("capabilities", []),
                "probes": [{"name": "tasks.get", "status": "ok", "url": url, "expectedStatus": 404}],
            })
        error = f"HTTP {exc.code}: {detail[:800] or exc.reason}"
        return _with_provider_probe_summary(provider, {
            "overall": "fail",
            "status": "failed",
            "message": "联通失败：Vidu 接口未通过测试。",
            "error": error,
            "checkedAt": now,
            "latencyMs": latency_ms,
            "availableModels": [],
            "capabilities": provider.get("capabilities", []),
            "probes": [{"name": "tasks.get", "status": "failed", "url": url, "error": error}],
        })
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _with_provider_probe_summary(provider, {
            "overall": "fail",
            "status": "failed",
            "message": "联通失败：Vidu 接口未通过测试。",
            "error": str(exc),
            "checkedAt": now,
            "latencyMs": latency_ms,
            "availableModels": [],
            "capabilities": provider.get("capabilities", []),
            "probes": [{"name": "tasks.get", "status": "failed", "url": url, "error": str(exc)}],
        })


def _run_ark_seedance_connection_test(provider: dict[str, Any]) -> dict[str, Any]:
    from .provider_models import _provider_available_models_for_test
    from .model_provider_config import _provider_base_url
    from .provider_models import _provider_service_id
    now = _now()
    api_key = str(provider.get("api_key") or "").strip()
    provider_id = _provider_service_id(provider)
    base_url = _provider_base_url(provider) or _provider_default_base_url(provider_id)
    started = time.perf_counter()
    try:
        from volcenginesdkarkruntime import Ark

        client = Ark(base_url=base_url, api_key=api_key, timeout=MODEL_PROVIDER_PROBE_TIMEOUT_SECONDS, max_retries=0)
        client.content_generation.tasks.list(page_size=1)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _with_provider_probe_summary(provider, {
            "overall": "ok",
            "status": "connected",
            "message": "联通成功：Ark 鉴权与任务列表接口测试通过。",
            "error": "",
            "checkedAt": now,
            "latencyMs": latency_ms,
            "availableModels": _provider_available_models_for_test(provider),
            "capabilities": provider.get("capabilities", []),
            "probes": [
                {
                    "name": "content_generation.tasks.list",
                    "status": "ok",
                    "url": base_url,
                    "params": {"page_size": 1},
                }
            ],
        })
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _with_provider_probe_summary(provider, {
            "overall": "fail",
            "status": "failed",
            "message": "联通失败：Ark 任务列表接口未通过测试。",
            "error": str(exc),
            "checkedAt": now,
            "latencyMs": latency_ms,
            "availableModels": [],
            "capabilities": provider.get("capabilities", []),
            "probes": [
                {
                    "name": "content_generation.tasks.list",
                    "status": "failed",
                    "url": base_url,
                    "params": {"page_size": 1},
                    "error": str(exc),
                }
            ],
        })


def _probe_claude_agent_sdk_runtime(provider: dict[str, Any], result: dict[str, Any] | None = None) -> str:
    if not agent_sdk_runtime.is_claude_agent_sdk_available():
        return "unsupported"
    probe = _claude_agent_sdk_probe_from_result(result)
    if isinstance(probe, dict):
        status = str(probe.get("status") or "").lower()
        if status == "ok":
            return "supported"
        if status == "unsupported":
            return "unsupported"
        return "unknown"
    summary = provider.get("probe_summary") if isinstance(provider.get("probe_summary"), dict) else {}
    if not summary:
        last_test = provider.get("last_test") if isinstance(provider.get("last_test"), dict) else {}
        summary = last_test.get("probeSummary") if isinstance(last_test.get("probeSummary"), dict) else {}
    status = summary.get("claudeAgentSdk") if isinstance(summary, dict) else None
    if status in {"supported", "unsupported", "unknown"}:
        return str(status)
    if not _provider_declares_agent_capability(provider):
        return "unknown"
    if not str(provider.get("api_key") or "").strip():
        return "unknown"
    return "unknown"


def _provider_supports_claude_agent_sdk(provider: dict[str, Any]) -> bool:
    summary = provider.get("probe_summary") if isinstance(provider.get("probe_summary"), dict) else {}
    if not summary:
        last_test = provider.get("last_test") if isinstance(provider.get("last_test"), dict) else {}
        summary = last_test.get("probeSummary") if isinstance(last_test.get("probeSummary"), dict) else {}
    return bool(summary.get("agentRouteReady"))


def _probe_summary_for_result(
    provider: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    probes = result.get("probes") if isinstance(result.get("probes"), list) else []
    model_probe = next(
        (
            probe
            for probe in probes
            if isinstance(probe, dict) and str(probe.get("name") or "") == "models.list"
        ),
        None,
    )
    models_status = "unknown"
    if isinstance(model_probe, dict):
        probe_status = str(model_probe.get("status") or "").lower()
        if probe_status == "ok":
            models_status = "ok"
        elif probe_status == "warn":
            models_status = "warn"
        elif probe_status:
            models_status = "failed"
    elif result.get("availableModels") and not result.get("capabilityResults"):
        models_status = "ok"
    catalog_only = any(
        isinstance(probe, dict) and probe.get("catalogOnly") is True
        for probe in probes
    )
    auth_status = (
        "unknown"
        if catalog_only and not any(
            isinstance(probe, dict)
            and probe.get("status") == "ok"
            and probe.get("catalogOnly") is not True
            and probe.get("name") not in {"agent.route", "models.list"}
            for probe in probes
        )
        else "ok" if result.get("overall") in {"ok", "warn"} else "failed"
    )
    native_structured = str(
        provider.get("native_structured_output")
        or provider.get("nativeStructuredOutput")
        or "unknown"
    )
    native_probe = _native_json_schema_probe_from_result(result)
    native_endpoint = ""
    native_model = ""
    if isinstance(native_probe, dict):
        native_status = str(native_probe.get("status") or "").lower()
        if native_status == "ok":
            native_structured = "supported"
        elif native_status == "unsupported":
            native_structured = "unsupported"
        elif native_status:
            native_structured = "unknown"
        native_endpoint = str(native_probe.get("endpoint") or "").strip()
        native_model = str(native_probe.get("model") or "").strip()
    if native_structured not in {"supported", "unsupported", "unknown"}:
        native_structured = "unknown"
    native_auth = {}
    if isinstance(native_probe, dict) and native_probe.get("authMode") in {"bearer", "x-api-key"}:
        native_auth = {
            "nativeJsonSchemaUrl": native_probe["url"],
            "nativeJsonSchemaAuthMode": native_probe["authMode"],
        }
    agent_probe = _claude_agent_sdk_probe_from_result(result)
    agent_base_url = ""
    agent_model = ""
    agent_auth_mode = ""
    if isinstance(agent_probe, dict) and agent_probe.get("status") == "ok":
        agent_base_url = str(agent_probe.get("baseUrl") or "").strip()
        agent_model = str(agent_probe.get("model") or "").strip()
        agent_auth_mode = str(agent_probe.get("authMode") or "").strip()
    platform_probe = next(
        (
            probe
            for probe in probes
            if probe.get("name") == "platform.contract"
            and probe.get("status") == "ok"
            and probe.get("platform") in {"new-api", "sub2api"}
        ),
        {},
    )
    route_probe = next(
        (
            probe
            for probe in probes
            if probe.get("name") in {"agent.models", "agent.route"}
            and probe.get("status") == "ok"
        ),
        {},
    )
    if route_probe:
        agent_base_url = str(route_probe.get("baseUrl") or "")
        agent_auth_mode = str(route_probe.get("authMode") or "")
    return {
        "auth": auth_status,
        "modelsList": models_status,
        **({"relayPlatform": platform_probe.get("platform")} if platform_probe else {}),
        "nativeJsonSchema": native_structured,
        **({"nativeJsonSchemaEndpoint": native_endpoint} if native_endpoint else {}),
        **({"nativeJsonSchemaModel": native_model} if native_model else {}),
        **native_auth,
        "claudeAgentSdk": _probe_claude_agent_sdk_runtime(provider, result),
        "agentRouteReady": bool(route_probe),
        **({"claudeAgentBaseUrl": agent_base_url} if agent_base_url else {}),
        **({"claudeAgentModel": agent_model} if agent_model else {}),
        **({"claudeAgentAuthMode": agent_auth_mode} if agent_auth_mode else {}),
    }


def _with_provider_probe_summary(
    provider: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    summary = _probe_summary_for_result(provider, result)
    result["probeSummary"] = summary
    result["nativeStructuredOutput"] = summary.get("nativeJsonSchema", "unknown")
    return result


def _provider_connection_test_fingerprint(provider: dict[str, Any]) -> dict[str, Any]:
    from .provider_models import _normalize_provider_capabilities
    from .provider_models import _provider_adapter_id
    from .model_provider_config import _provider_base_url
    from .provider_models import _provider_service_id
    raw_capabilities = provider.get("capabilities")
    capabilities = sorted(_normalize_provider_capabilities(raw_capabilities))
    return {
        "presetId": _provider_service_id(provider),
        "adapterId": _provider_adapter_id(provider),
        "baseUrl": _normalized_url(_provider_base_url(provider)),
        "apiKeyMasked": _mask_key(str(provider.get("api_key") or "")),
        "capabilities": capabilities,
    }


def _with_provider_connection_test_context(
    provider: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    result = _redact_connection_test_result(result, str(provider.get("api_key") or ""))
    # Fingerprint the user's configured selection. Verification is evidence
    # stored in the result and must not change the save contract.
    result["connectionFingerprint"] = _provider_connection_test_fingerprint(provider)
    return result


def _redact_connection_test_result(value: Any, api_key: str) -> Any:
    """Remove credentials from probe errors before they reach the frontend or store."""
    if isinstance(value, str):
        text = value.replace(api_key, "[redacted]") if api_key else value
        return re.sub(
            r"([?&](?:api[_-]?key|key|token|access[_-]?token|authorization)=)[^&#\s]+",
            r"\1[redacted]",
            text,
            flags=re.IGNORECASE,
        )
    if isinstance(value, dict):
        return {key: _redact_connection_test_result(item, api_key) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_connection_test_result(item, api_key) for item in value]
    return value


def _rebase_connection_test_models(provider: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    from .provider_models import _provider_available_models_for_test
    remote_models = result.get("remoteModels") or result.get("remote_models")
    available_models = result.get("availableModels") or result.get("available_models")
    model_source = remote_models if isinstance(remote_models, list) and remote_models else available_models
    if isinstance(model_source, list) and model_source:
        if isinstance(result.get("capabilityResults"), dict):
            provider = {**provider, "models": [], "probe_summary": result.get("probeSummary", {})}
        result["availableModels"] = _provider_available_models_for_test(provider, model_source)
    return result


def _validated_payload_connection_test_result(
    provider: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    last_test = payload.get("lastTest") or payload.get("last_test")
    if not isinstance(last_test, dict):
        raise ValueError("缺少刚刚通过的连接测试结果，请重新测试后再保存")
    result = copy.deepcopy(last_test)
    if result.get("overall") != "ok":
        raise ValueError(f"供应商连接测试未通过：{result.get('error') or result.get('message')}")
    fingerprint = result.get("connectionFingerprint") or result.get("connection_fingerprint")
    if isinstance(fingerprint, dict) and fingerprint != _provider_connection_test_fingerprint(provider):
        raise ValueError("表单内容已变更，请重新测试连接后再保存")
    result = _rebase_connection_test_models(provider, result)
    if not isinstance(result.get("probeSummary"), dict):
        result = _with_provider_probe_summary(provider, result)
    return _with_provider_connection_test_context(provider, result)


def _verified_capabilities_from_result(
    result: dict[str, Any],
    fallback: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    """Return verification evidence independently of configured capabilities."""
    from .provider_models import _normalize_provider_capabilities

    explicit = result.get("verifiedCapabilities")
    groups = result.get("capabilityResults")
    if not isinstance(groups, dict):
        if isinstance(explicit, list):
            return _normalize_provider_capabilities(explicit)
        return _normalize_provider_capabilities(list(fallback or result.get("capabilities") or []))
    mapping = {
        "image": ("storyboard_image", "asset_image"),
        "agent": ("agent",),
        "text": ("text_generation",),
        "video": ("storyboard_video",),
    }
    verified: list[str] = []
    for group, capabilities in mapping.items():
        if isinstance(groups.get(group), dict) and groups[group].get("status") == "ok":
            verified.extend(capabilities)
    if isinstance(explicit, list):
        verified = [capability for capability in verified if capability in explicit]
    return _normalize_provider_capabilities(verified)


def _capabilities_after_connection_test(
    selected: list[str] | tuple[str, ...] | None,
    result: dict[str, Any],
) -> list[str]:
    """Reconcile selected capabilities with a successful capability probe.

    A failed whole-connection test must leave the user's draft untouched so it
    can be retried. Once the model directory is connected and at least one
    selected capability is positively classified, keep only the selected
    capabilities backed by that result. If classification produced no usable
    intersection, keep the selection because the directory connection itself
    is still a valid configuration result and the capability remains unknown.
    """
    from .provider_models import _normalize_provider_capabilities

    selected_capabilities = _normalize_provider_capabilities(list(selected or []))
    verified = set(_verified_capabilities_from_result(result, selected_capabilities))
    if result.get("overall") != "ok" or not verified:
        return selected_capabilities
    reconciled = [capability for capability in selected_capabilities if capability in verified]
    return reconciled or selected_capabilities


def _finalize_provider_capability_result(
    provider: dict[str, Any], *, started: float, results: dict[str, Any],
    models: list[dict[str, Any]], capability_models: dict[str, list[str]],
    probes: list[dict[str, Any]], pending_models: list[dict[str, Any]],
    discovered_models: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from utils.preset_provider_probes import CAPABILITY_GROUPS, _redact_probe
    from .provider_models import _provider_available_models_for_test

    requested = set(provider.get("capabilities") or [])
    discovery_ok = any(probe.get("name") == "models.list" and probe.get("status") == "ok" for probe in probes)
    verified = [
        capability for group, capabilities in CAPABILITY_GROUPS.items()
        if results.get(group, {}).get("status") == "ok"
        for capability in capabilities if capability in requested
    ]
    # Configuration success, protocol readiness and generation verification are
    # separate facts. A successful list never implies a successful generation.
    configured = bool(results) and (bool(verified) or discovery_ok)
    result = {
        "overall": "ok" if configured else "fail", "status": "connected" if configured else "failed",
        "message": "配置检查通过" if verified else "模型列表已连通，能力待确认" if configured else "配置检查失败" if results else "请至少选择一类能力",
        "checkedAt": _now(), "latencyMs": int((time.perf_counter() - started) * 1000),
        "capabilities": list(provider.get("capabilities") or []) if configured else [],
        "verifiedCapabilities": verified, "capabilityResults": results, "probes": probes,
        "pendingModels": pending_models,
        "catalogComplete": not any(row.get("status") == "failed" for row in results.values()),
        "remoteModels": models, "remoteModelIds": [row["id"] for row in models],
    }
    if discovered_models is not None:
        result["discoveredModels"] = discovered_models
    clean_provider = {
        **provider, "models": [], "probe_summary": {}, "last_test": {},
        "native_structured_output": "unknown", "native_structured_models": {},
    }
    result = _with_provider_probe_summary(clean_provider, result)
    if discovery_ok:
        result["probeSummary"]["modelsList"] = "ok"
    result["probeSummary"]["capabilityModels"] = capability_models
    result["availableModels"] = _provider_available_models_for_test(
        {**clean_provider, "probe_summary": result["probeSummary"]}, models,
    ) if models else []
    return _redact_probe(result, str(provider.get("api_key") or ""))


def _run_provider_connection_test(
    provider: dict[str, Any],
    *,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    from utils.preset_provider_probes import uses_preset_capability_probes, run_preset_capability_probes
    from .provider_models import _provider_adapter_id
    from .provider_models import _provider_available_models_for_test
    from .provider_models import _provider_service_id
    from .provider_models import _remote_model_entry_id
    from .provider_models import _normalize_provider_capabilities
    now = _now()
    provider_id = _provider_service_id(provider)
    preset = next((item for item in DEFAULT_PROVIDER_PRESETS if item.get("id") == provider_id), None)
    if preset is not None:
        provider = {**provider, "capabilities": _normalize_provider_capabilities(
            provider.get("capabilities", preset.get("capabilities")), supported=preset.get("capabilities"),
        )}
    adapter_id = _provider_adapter_id(provider)
    api_key = str(provider.get("api_key") or "")
    base_url = str(provider.get("base_url") or "")
    if not api_key:
        return _with_provider_probe_summary(provider, {
            "overall": "fail",
            "status": "failed",
            "message": "联通失败：未配置 API Key。",
            "error": f"{provider.get('key_label') or 'API_KEY'} 为空",
            "checkedAt": now,
            "latencyMs": 0,
            "availableModels": [],
            "probes": [{"name": "credential", "status": "failed", "error": "missing_api_key"}],
        })
    if adapter_id in {"openai-compatible", "anthropic-compatible", "gemini-compatible", "newapi-video"} and not base_url:
        return _with_provider_probe_summary(provider, {
            "overall": "fail",
            "status": "failed",
            "message": "联通失败：供应商缺少 Base URL。",
            "error": "base_url 为空，无法派生连接测试端点。",
            "checkedAt": now,
            "latencyMs": 0,
            "availableModels": [],
            "probes": [{"name": "base_url", "status": "failed", "error": "missing_base_url"}],
        })
    if re.search(r"\{[^{}]+\}", base_url):
        return _with_provider_probe_summary(provider, {
            "overall": "fail",
            "status": "failed",
            "message": "联通失败：Base URL 仍包含未替换的地址模板。",
            "error": "base_url 包含未替换的模板变量，请先填写完整的请求地址。",
            "checkedAt": now,
            "latencyMs": 0,
            "availableModels": [],
            "probes": [{"name": "base_url", "status": "failed", "error": "unresolved_base_url_template"}],
        })

    if uses_preset_capability_probes(provider):
        return run_preset_capability_probes(provider, on_progress=on_progress)
    if adapter_id in {"openai-compatible", "anthropic-compatible", "gemini-compatible", "newapi-video"}:
        from utils.relay_provider_probes import run_relay_capability_probes

        return run_relay_capability_probes(provider, on_progress=on_progress)
    if provider_id == "ark-seedance":
        return _run_ark_seedance_connection_test(provider)
    if provider_id == "vidu":
        return _run_vidu_connection_test(provider)

    started = time.perf_counter()
    url, headers, probe_name = _provider_probe_url_and_headers(provider)
    try:
        response = _request_json("GET", url, headers=headers)
        latency_ms = int((time.perf_counter() - started) * 1000)
        remote_models = _extract_provider_model_rows(response)
        remote_model_ids = [_remote_model_entry_id(item) for item in remote_models]
        return _with_provider_probe_summary(provider, {
            "overall": "ok",
            "status": "connected",
            "message": "联通成功：模型列表获取通过。",
            "error": "",
            "checkedAt": now,
            "latencyMs": latency_ms,
            "availableModels": _provider_available_models_for_test(provider, remote_models),
            "remoteModelIds": remote_model_ids,
            "remoteModels": remote_models,
            "capabilities": provider.get("capabilities", []),
            "probes": [{"name": probe_name, "status": "ok", "url": url}],
        })
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _with_provider_probe_summary(provider, {
            "overall": "fail",
            "status": "failed",
            "message": "联通失败：供应商接口未通过测试。",
            "error": str(exc),
            "checkedAt": now,
            "latencyMs": latency_ms,
            "availableModels": [],
            "capabilities": provider.get("capabilities", []),
            "probes": [{"name": probe_name, "status": "failed", "url": url, "error": str(exc)}],
        })


@_serialized_global_config_write
def add_provider(payload: dict[str, Any]) -> dict[str, Any]:
    from .provider_models import _normalize_provider_capabilities
    from .provider_models import _normalize_provider_id
    from .provider_models import _provider_model_matches_capabilities
    from .provider_models import _provider_service_id
    from .projects import _public_provider
    from .projects import _save_global_config
    from .provider_models import _unique_provider_instance_id
    from .provider_models import _unique_provider_title
    from .settings_loaders import load_global_config
    config = load_global_config()
    base = _build_provider_from_add_payload(
        config,
        payload,
        existing={},
    )
    preset_id = _provider_service_id(base)
    provider_id = _unique_provider_instance_id(config.get("providers", []), _normalize_provider_id(base.get("id")))
    base["id"] = provider_id
    if preset_id:
        base["preset_id"] = preset_id
    base["title"] = _unique_provider_title(
        config.get("providers", []),
        str(base.get("title") or "供应商实例"),
        exclude_provider_id=provider_id,
    )
    if not (payload.get("connectionTestPassed") or payload.get("connection_test_passed")):
        raise ValueError("请先完成并通过连接测试")

    result = _validated_payload_connection_test_result(base, payload)
    result_models = result.get("availableModels")
    verified_capabilities = _verified_capabilities_from_result(
        result, base.get("capabilities", [])
    )
    result["verifiedCapabilities"] = verified_capabilities
    capability_list = _capabilities_after_connection_test(base.get("capabilities", []), result)
    base["capabilities"] = capability_list
    result = _with_provider_connection_test_context(base, result)
    if isinstance(result_models, list):
        base["models"] = [
            copy.deepcopy(model)
            for model in result_models
            if isinstance(model, dict)
            and _provider_model_matches_capabilities(model, capability_list)
        ]
    base["configured"] = True
    base["connection_status"] = "connected"
    base["last_test"] = result
    base["probe_summary"] = result.get("probeSummary", {})
    base["native_structured_output"] = result.get("nativeStructuredOutput", "unknown")

    config["providers"] = [*config.get("providers", []), base]
    config = _save_global_config(config)
    provider = next(row for row in config["providers"] if row.get("id") == provider_id)
    return {"success": True, "provider": _public_provider(provider)}


@_serialized_global_config_write
def update_provider(payload: dict[str, Any]) -> dict[str, Any]:
    from .provider_models import _normalize_provider_adapter_id
    from .provider_models import _normalize_provider_capabilities
    from .provider_models import _normalize_provider_id
    from .provider_models import _provider_adapter_id
    from .provider_models import _provider_model_matches_capabilities
    from .provider_models import _provider_service_id
    from .projects import _public_provider
    from .projects import _save_global_config
    from .provider_models import _unique_provider_title
    from .settings_loaders import load_global_config
    config = load_global_config()
    presets = config.get("provider_presets", DEFAULT_PROVIDER_PRESETS)
    provider_id = _normalize_provider_id(payload.get("providerId") or payload.get("provider_id") or payload.get("id"))
    if not provider_id:
        raise ValueError("供应商 ID 不能为空")

    existing = next(
        (
            row
            for row in config.get("providers", [])
            if _normalize_provider_id(row.get("id")) == provider_id
        ),
        None,
    )
    if not existing:
        raise ValueError("供应商不存在")

    service_id = _provider_service_id(existing) or provider_id
    preset = next((item for item in presets if item.get("id") == service_id), None)
    base = _deep_merge(copy.deepcopy(preset or {}), existing)
    adapter_id = _normalize_provider_adapter_id(
        payload.get("adapterId")
        or payload.get("adapter_id")
        or base.get("adapter_id")
        or service_id
    )
    payload_has_capabilities = isinstance(payload.get("capabilities"), list)
    raw_capabilities = payload.get("capabilities") if payload_has_capabilities else base.get("capabilities", [])
    capabilities = _normalize_provider_capabilities(
        raw_capabilities, supported=preset.get("capabilities") if preset else None,
    )
    models = _provider_models_from_payload(payload, base)
    models = [
        model
        for model in models
        if isinstance(model, dict)
        and _provider_model_matches_capabilities(model, capabilities)
    ]

    next_base_url = (
        payload.get("baseUrl")
        or payload.get("base_url")
        or base.get("base_url")
        or ""
    )
    next_title = _unique_provider_title(
        config.get("providers", []),
        payload.get("title")
        or base.get("title")
        or "供应商实例",
        exclude_provider_id=provider_id,
    )
    incoming_key = str(payload.get("apiKey") or payload.get("api_key") or "").strip()
    api_key = incoming_key or str(existing.get("api_key") or "")
    model_connection_changed = any(
        [
            api_key != str(existing.get("api_key") or ""),
            next_base_url != str(existing.get("base_url") or ""),
            adapter_id != _provider_adapter_id(existing),
        ]
    )
    connection_inputs_changed = model_connection_changed or (
        capabilities != _normalize_provider_capabilities(existing.get("capabilities"))
    )

    updated = copy.deepcopy(base)
    updated.update(
        {
            "id": provider_id,
            "adapter_id": adapter_id,
            "preset_id": service_id if preset else existing.get("preset_id") or existing.get("presetId") or "",
            "official_title": preset.get("title") if preset else existing.get("official_title") or "",
            "title": next_title,
            "description": payload.get("description") or base.get("description") or "供应商实例",
            "base_url": next_base_url,
            "default_base_url": base.get("default_base_url") or (preset or {}).get("base_url") or "",
            "base_url_options": payload.get("baseUrlOptions") or payload.get("base_url_options") or base.get("base_url_options") or [],
            "base_url_note": payload.get("baseUrlNote") or payload.get("base_url_note") or base.get("base_url_note") or "",
            "docs_url": payload.get("docsUrl") or payload.get("docs_url") or base.get("docs_url") or "",
            "key_label": payload.get("keyLabel") or payload.get("key_label") or base.get("key_label") or "API_KEY",
            "capabilities": capabilities,
            "models": models,
            "user_added": True,
            "added_at": existing.get("added_at") or _now(),
            "api_key": api_key,
            "api_key_masked": _mask_key(api_key),
            "configured": bool(api_key),
            "connection_status": (
                "untested"
                if connection_inputs_changed and api_key
                else ("unconfigured" if not api_key else existing.get("connection_status") or "untested")
            ),
            "last_test": None if connection_inputs_changed else existing.get("last_test"),
            "probe_summary": {} if connection_inputs_changed else existing.get("probe_summary", {}),
            "native_structured_output": (
                "unknown"
                if connection_inputs_changed
                else existing.get("native_structured_output", "unknown")
            ),
        }
    )
    updated["logo"] = payload.get("logo") or base.get("logo") or str(next_title or "API")[:3].upper()
    updated["icon_key"] = payload.get("iconKey") or payload.get("icon_key") or base.get("icon_key") or "API"
    if model_connection_changed:
        updated["native_structured_models"] = {}

    if payload.get("connectionTestPassed") or payload.get("connection_test_passed"):
        result = _validated_payload_connection_test_result(updated, payload)
        if result.get("catalogComplete") is False and (existing.get("last_test") or {}).get("overall") == "ok":
            raise ValueError("部分模型目录获取失败，已保留原配置，请重试")
        verified_capabilities = _verified_capabilities_from_result(
            result, updated.get("capabilities", [])
        )
        result["verifiedCapabilities"] = verified_capabilities
        capabilities = _capabilities_after_connection_test(capabilities, result)
        updated["capabilities"] = capabilities
        result = _with_provider_connection_test_context(updated, result)
        result_models = result.get("availableModels")
        if isinstance(result_models, list):
            updated["models"] = [
                copy.deepcopy(model)
                for model in result_models
                if isinstance(model, dict)
                and _provider_model_matches_capabilities(model, capabilities)
            ]
        updated["configured"] = True
        updated["connection_status"] = "connected"
        updated["last_test"] = result
        updated["probe_summary"] = result.get("probeSummary", {})
        updated["native_structured_output"] = result.get("nativeStructuredOutput", "unknown")

    rows = [
        updated if _normalize_provider_id(row.get("id")) == provider_id else row
        for row in config.get("providers", [])
    ]
    config["providers"] = rows
    config = _save_global_config(config)
    provider = next(row for row in config["providers"] if row.get("id") == provider_id)
    return {"success": True, "provider": _public_provider(provider)}


@_serialized_global_config_write
def delete_provider(provider_id: str | None) -> dict[str, Any]:
    from .provider_models import _normalize_provider_id
    from .projects import _save_global_config
    from .settings_loaders import load_global_config
    provider_id = _normalize_provider_id(provider_id)
    if not provider_id:
        raise ValueError("供应商 ID 不能为空")
    config = load_global_config()
    rows = [
        row
        for row in config.get("providers", [])
        if _normalize_provider_id(row.get("id")) != provider_id
    ]
    if len(rows) == len(config.get("providers", [])):
        raise ValueError("供应商不存在")
    config["providers"] = rows
    _save_global_config(config)
    return {"success": True, "providerId": provider_id}


@_serialized_global_config_write
def _persist_provider_connection_test(
    probed_provider: dict[str, Any], result: dict[str, Any],
) -> dict[str, Any]:
    from .provider_models import _normalize_provider_capabilities
    from .provider_models import _normalize_provider_id
    from .provider_models import _provider_model_matches_capabilities
    from .projects import _public_provider
    from .projects import _save_global_config
    from .settings_loaders import load_global_config

    config = load_global_config()
    provider_id = _normalize_provider_id(probed_provider.get("id"))
    providers = config.get("providers", [])
    current = next(
        (row for row in providers if _normalize_provider_id(row.get("id")) == provider_id), None,
    )
    if not current or (
        _provider_connection_test_fingerprint(current) != _provider_connection_test_fingerprint(probed_provider)
        or current.get("api_key") != probed_provider.get("api_key")
        or current.get("last_test") != probed_provider.get("last_test")
        or current.get("models") != probed_provider.get("models")
    ):
        stale_result = {**result, "overall": "fail", "message": "供应商配置已变化，请重新测试连接", "configurationPreserved": True}
        return {"success": False, "provider": _public_provider(current or probed_provider), "result": stale_result}

    provider = copy.deepcopy(current)
    previous = provider.get("last_test") or {}
    if previous.get("overall") == "ok" and (
        result.get("overall") != "ok" or result.get("catalogComplete") is False
    ):
        provider["last_refresh"] = copy.deepcopy(result)
        config["providers"] = [provider if row is current else row for row in providers]
        _save_global_config(config)
        result["message"] = "模型目录刷新未完成，已保留原配置"
        result["configurationPreserved"] = True
        return {"success": False, "provider": _public_provider(provider), "result": result}
    if isinstance(result.get("capabilityResults"), dict) and result.get("overall") == "ok":
        result["verifiedCapabilities"] = _verified_capabilities_from_result(
            result, provider.get("capabilities") or [],
        )
        provider["capabilities"] = _capabilities_after_connection_test(
            provider.get("capabilities") or [], result,
        )
        result = _with_provider_connection_test_context(provider, result)
    provider["last_test"] = result
    if result.get("overall") == "ok":
        provider["probe_summary"] = result.get("probeSummary", {})
        provider["native_structured_output"] = result.get("nativeStructuredOutput", "unknown")
    provider["connection_status"] = "connected" if result["overall"] == "ok" else "failed"
    provider["configured"] = bool(provider.get("api_key"))
    result_models = result.get("availableModels")
    if result.get("overall") == "ok" and isinstance(result_models, list):
        capability_list = _normalize_provider_capabilities(provider.get("capabilities", []))
        provider["models"] = [
            copy.deepcopy(model)
            for model in result_models
            if isinstance(model, dict)
            and _provider_model_matches_capabilities(model, capability_list)
        ]
    config["providers"] = [provider if row is current else row for row in providers]
    saved = _save_global_config(config)
    provider = next(
        (row for row in saved.get("providers", []) if _normalize_provider_id(row.get("id")) == provider_id),
        provider,
    )
    return {"success": result["overall"] == "ok", "provider": _public_provider(provider), "result": result}


def test_provider_connection(
    payload: dict[str, Any] | str | None,
    *,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    from .provider_models import _normalize_provider_id
    from .projects import _public_provider
    from .settings_loaders import load_global_config
    config = load_global_config()
    providers = config.get("providers", [])

    provider_id = ""
    provider: dict[str, Any] | None = None
    should_persist = False
    if isinstance(payload, dict):
        provider_id = _normalize_provider_id(payload.get("providerId") or payload.get("provider_id"))
        has_draft_fields = any(
            key in payload
            for key in (
                "presetId",
                "preset_id",
                "apiKey",
                "api_key",
                "baseUrl",
                "base_url",
                "adapterId",
                "adapter_id",
                "capabilities",
            )
        )
        if provider_id and not has_draft_fields:
            provider = next((row for row in providers if _normalize_provider_id(row.get("id")) == provider_id), None)
            should_persist = True
        else:
            draft_provider_id = _normalize_provider_id(
                payload.get("providerId")
                or payload.get("provider_id")
                or payload.get("presetId")
                or payload.get("preset_id")
                or payload.get("id")
            )
            existing = next(
                (
                    row
                    for row in providers
                    if _normalize_provider_id(row.get("id")) == draft_provider_id
                ),
                {},
            )
            provider = _build_provider_from_add_payload(config, payload, existing=existing)
    else:
        provider_id = _normalize_provider_id(payload)
        provider = next((row for row in providers if _normalize_provider_id(row.get("id")) == provider_id), None)
        should_persist = True

    if not provider:
        raise ValueError("供应商不存在")

    connection_result = (
        _run_provider_connection_test(provider, on_progress=on_progress)
        if on_progress else _run_provider_connection_test(provider)
    )
    result = _with_provider_connection_test_context(provider, connection_result)
    if should_persist:
        return _persist_provider_connection_test(provider, result)
    if isinstance(result.get("capabilityResults"), dict) and result.get("overall") == "ok":
        verified_capabilities = _verified_capabilities_from_result(
            result, provider.get("capabilities") or []
        )
        result["verifiedCapabilities"] = verified_capabilities
        provider = copy.deepcopy(provider)
        provider["capabilities"] = _capabilities_after_connection_test(
            provider.get("capabilities") or [], result,
        )
        result = _with_provider_connection_test_context(provider, result)
    provider = copy.deepcopy(provider)
    provider["connection_status"] = "connected" if result["overall"] == "ok" else "failed"
    provider["configured"] = bool(provider.get("api_key"))
    provider["last_test"] = result
    provider["probe_summary"] = result.get("probeSummary", {})
    provider["native_structured_output"] = result.get("nativeStructuredOutput", "unknown")
    return {"success": result["overall"] == "ok", "provider": _public_provider(provider), "result": result}

__all__ = (
    'list_providers', '_build_provider_from_add_payload', '_provider_models_from_payload',
    '_extract_provider_model_ids', '_extract_provider_model_rows',
    '_request_json', '_response_json_for_log', '_notify_response_received',
    '_deepseek_discovery_root', '_provider_default_base_url', '_provider_default_text_model',
    '_anthropic_messages_url', '_anthropic_models_url',
    '_anthropic_auth_headers', '_ANTHROPIC_AUTH_TOKEN_GATEWAY_PATHS', '_ANTHROPIC_MESSAGES_GATEWAY_PATHS',
    '_looks_like_anthropic_auth_token_gateway', '_anthropic_sdk_base_url', '_anthropic_messages_auth_headers',
    '_provider_claude_agent_base_url',
    '_provider_claude_agent_model', '_provider_claude_agent_auth_mode', '_anthropic_sdk_env', '_http_url_base',
    '_openai_compatible_discovery_base_url', '_google_discovery_root_url',
    '_provider_declares_agent_capability', '_provider_declares_text_capability', '_normalized_url',
    '_candidate_anthropic_agent_base_urls', '_anthropic_probe_auth_headers', '_provider_probe_url_and_headers',
    '_CLAUDE_AGENT_SDK_PROBE_NAME', '_NATIVE_JSON_SCHEMA_PROBE_NAME',
    '_NATIVE_JSON_SCHEMA_PROBE_SCHEMA', '_claude_agent_sdk_probe_from_result',
    '_native_json_schema_probe_from_result', '_validate_native_json_schema_probe_text',
    '_run_openai_native_json_schema_probe', '_run_gemini_native_json_schema_probe',
    '_run_native_json_schema_probe',
    '_run_vidu_connection_test', '_run_ark_seedance_connection_test',
    '_probe_claude_agent_sdk_runtime', '_provider_supports_claude_agent_sdk', '_probe_summary_for_result',
    '_with_provider_probe_summary', '_provider_connection_test_fingerprint',
    '_with_provider_connection_test_context', '_rebase_connection_test_models',
    '_validated_payload_connection_test_result', '_run_provider_connection_test', 'add_provider',
    'update_provider', 'delete_provider', 'test_provider_connection'
)
