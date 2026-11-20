# -*- coding: utf-8 -*-
"""智能体模型配置、SDK 可用性和服务连接错误说明。"""
from __future__ import annotations

import utils.agent_sdk_runtime as agent_sdk_runtime
import re as re
from .agent_sessions import (
    _project_dir,
)
from .model_provider_config import (
    _api_model_name,
    _configured_text_model,
    _project_agent_reasoning_effort,
)
from utils.model_reasoning import agent_reasoning_modes, default_agent_reasoning_mode
from .provider_connections import (
    _anthropic_sdk_env,
    _provider_connection_test_fingerprint,
    _provider_supports_claude_agent_sdk,
)
from .provider_models import (
    _is_connected_provider,
    _provider_adapter_id,
    _provider_model_available_for_group,
)
from .source_text_store import _compact_text

from typing import Any


def _agent_api_key_looks_like_placeholder(api_key: str) -> bool:
    normalized = re.sub(r"[\s_]+", "-", str(api_key or "").strip().lower())
    if not normalized:
        return False
    return normalized in {
        "test-key",
        "demo-key",
        "api-key",
        "your-api-key",
        "placeholder-key",
        "changeme",
        "replace-me",
        "sk-test",
    } or normalized.startswith("sk-test-")


def _agent_provider_connection_test_error(provider: dict[str, Any]) -> str:
    last_test = provider.get("last_test") if isinstance(provider.get("last_test"), dict) else provider.get("lastTest")
    if not isinstance(last_test, dict) or not last_test:
        return "Claude Agent SDK 智能体供应商缺少已通过的连接测试记录，请在全局设置中重新测试连接"
    if last_test.get("overall") != "ok":
        detail = str(last_test.get("error") or last_test.get("message") or "").strip()
        suffix = f"：{_compact_text(detail, 180)}" if detail else ""
        return f"Claude Agent SDK 智能体供应商连接测试未通过{suffix}"
    fingerprint = last_test.get("connectionFingerprint") or last_test.get("connection_fingerprint")
    if not isinstance(fingerprint, dict):
        return "Claude Agent SDK 智能体供应商连接测试记录缺少校验信息，请在全局设置中重新测试连接"
    current_fingerprint = _provider_connection_test_fingerprint(provider)
    connection_keys = ("presetId", "adapterId", "baseUrl", "apiKeyMasked")
    if any(fingerprint.get(key) != current_fingerprint.get(key) for key in connection_keys):
        return "Claude Agent SDK 智能体供应商配置已变更，请在全局设置中重新测试连接"
    return ""


def _agent_sdk_runtime_config(project_id: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    provider, model, _model_config = _configured_text_model(project_id, "agent", "model_id")
    meta = {
        "source": "claude-agent-sdk",
        "modelId": model.get("id") if model else "",
        "modelLabel": model.get("label") if model else "",
        "providerId": model.get("provider_id") if model else "",
        "providerInstanceId": provider.get("id") if provider else "",
        "adapterId": _provider_adapter_id(provider) if provider else "",
        "error": "",
    }
    if not provider or not model:
        meta["error"] = "Claude Agent SDK 智能体供应商未连接或所选模型不可用，请在智能体对话区选择模型，并在全局设置中完成供应商连接测试"
        return None, meta
    if not agent_sdk_runtime.is_claude_agent_sdk_available():
        meta["error"] = f"claude-agent-sdk 不可用：{agent_sdk_runtime.unavailable_reason()}"
        return None, meta

    api_key = str(provider.get("api_key") or "").strip()
    if not api_key:
        meta["error"] = "Claude Agent SDK 智能体供应商缺少 API Key"
        return None, meta
    if _agent_api_key_looks_like_placeholder(api_key):
        meta["error"] = "Claude Agent SDK 智能体供应商 API Key 是测试占位值，请配置真实 API Key 并重新测试连接"
        return None, meta
    if not _is_connected_provider(provider):
        meta["error"] = "Claude Agent SDK 智能体供应商未连接，请先在全局设置中重新测试连接"
        return None, meta
    connection_error = _agent_provider_connection_test_error(provider)
    if connection_error:
        meta["error"] = connection_error
        return None, meta
    if not _provider_supports_claude_agent_sdk(provider):
        meta["error"] = "当前供应商尚未配置 Anthropic 兼容智能体接口"
        return None, meta
    selected_model = str(model.get("api_model_id") or _api_model_name(model.get("id")))
    if not _provider_model_available_for_group(provider, model, "agent"):
        meta["error"] = "所选模型的智能体接口尚未确认，请重新测试连接或选择已确认的模型"
        return None, meta
    model_name = selected_model
    meta["runtimeModelName"] = model_name
    meta["runtimePolicy"] = "selected_claude_agent_sdk"
    route = model.get("agent_route") or {}
    runtime_provider = {**provider, "probe_summary": {
        **(provider.get("probe_summary") or {}),
        "claudeAgentBaseUrl": route.get("baseUrl"),
        "claudeAgentAuthMode": route.get("authMode"),
    }}
    env = _anthropic_sdk_env(runtime_provider, api_key, model_name)
    from .model_request_logs import create_model_exchange_logger

    # Keep CLI preferences, memory and session files away from user/global
    # coding-agent configuration. Business tools still resolve project_id.
    runtime_root = _project_dir(project_id) / ".agent-runtime" / agent_sdk_runtime.SDK_CONTEXT_VERSION
    runtime_cwd = runtime_root / "work"
    config_dir = runtime_root / "config"
    env.update({
        "CLAUDE_CONFIG_DIR": str(config_dir),
        "GIT_CEILING_DIRECTORIES": str(runtime_root),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    })
    saved_reasoning_mode = _project_agent_reasoning_effort(project_id)
    available_reasoning_modes = agent_reasoning_modes(env.get("ANTHROPIC_BASE_URL", ""), model_name)
    return {
        "provider": provider,
        "model": model,
        "modelName": model_name,
        "reasoningMode": (
            saved_reasoning_mode
            if saved_reasoning_mode in available_reasoning_modes
            else default_agent_reasoning_mode(model_name, env.get("ANTHROPIC_BASE_URL", ""))
        ) if available_reasoning_modes else None,
        "env": env,
        "cwd": runtime_cwd,
        "onApiExchange": create_model_exchange_logger(project_id),
    }, meta


def _agent_configured_model_summary(project_id: str) -> str:
    from .model_provider_config import _project_model_selection
    from .provider_models import _find_model

    capabilities, model_config = _project_model_selection(project_id)
    model = _find_model(str((model_config.get("agent") or {}).get("model_id") or "").strip(), "agent", capabilities)
    if not model:
        return "当前项目还没有配置可用的智能体模型"
    label = str(model.get("label") or "").strip()
    model_id = str(model.get("id") or "").strip()
    provider_id = str(model.get("provider_id") or "").strip()
    display = label or model_id or "未命名模型"
    if provider_id:
        return f"{display}（{provider_id}）"
    return display


def _agent_runtime_config_failure_message(model_meta: dict[str, Any] | None) -> str:
    meta = model_meta or {}
    error_text = str(meta.get("error") or meta.get("message") or "").strip()
    reason = f"：{_compact_text(error_text, 360)}" if error_text else ""
    return (
        f"当前智能体供应商配置不可用{reason}。\n\n"
        "请先在全局设置中配置真实 API Key，并通过连接测试后再继续运行智能体任务。"
    )
