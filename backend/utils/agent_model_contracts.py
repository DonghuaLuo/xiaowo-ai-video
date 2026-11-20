"""Anthropic route classification is independent of generation verification."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit


def documented_plan_catalog(base_url: str) -> list[dict[str, Any]]:
    parsed = urlsplit(base_url)
    path = parsed.path.rstrip("/")
    if parsed.hostname != "ark.cn-beijing.volces.com" or path not in {"/api/plan", "/api/coding"}:
        return []
    # These products do not expose a directory to their inference API Key.
    # https://docs.volcengine.com/docs/ark/agent-plan-personal-zcode
    # https://docs.volcengine.com/docs/ark/coding-plan-personal-ai-claude-code
    names = """ark-code-latest doubao-seed-evolving doubao-seed-2.1-pro doubao-seed-2.1-lite
    doubao-seed-2.0-mini minimax-m3 glm-5.3 glm-latest glm-5.3-flash
    deepseek-v4.1-flash deepseek-v4-flash deepseek-v4-pro kimi-k2.7-code kimi-k2.8-preview kimi-k3""".split()
    source = "https://docs.volcengine.com/docs/ark/" + (
        "agent-plan-personal-zcode" if path == "/api/plan" else "coding-plan-personal-ai-claude-code"
    )
    return [{"id": name, "api_model_id": name, "type": "text", "agent_only": True,
             "discovery_source": "official-catalog", "catalog_source_url": source} for name in names]


def agent_route(provider: dict[str, Any], *, base_url: str = "", auth_mode: str = "") -> dict[str, str]:
    from project_store_services.provider_models import _provider_service_id, _provider_adapter_id
    from project_store_services.provider_connections import _anthropic_sdk_base_url

    service = _provider_service_id(provider)
    configured_agent_base = str(
        provider.get("agent_base_url")
        or provider.get("agentBaseUrl")
        or provider.get("anthropic_base_url")
        or provider.get("anthropicBaseUrl")
        or ""
    ).strip()
    explicit_base = base_url or configured_agent_base
    source = "configured-anthropic-contract" if explicit_base else "provider-contract"
    base = explicit_base or str(provider.get("base_url") or "")
    host = (urlsplit(base).hostname or "").lower()
    if not explicit_base:
        if host == "ark.cn-beijing.volces.com" and urlsplit(base).path.rstrip("/") in {"/api/plan", "/api/coding"}:
            auth_mode = "bearer"
        elif service == "ark-seedance" and host == "ark.cn-beijing.volces.com":
            base, auth_mode = "https://ark.cn-beijing.volces.com/api/compatible", "x-api-key"
        elif service == "deepseek" and host == "api.deepseek.com":
            base, auth_mode = "https://api.deepseek.com/anthropic", "bearer"
        elif service == "dashscope" and (host.endswith(".aliyuncs.com") or host.endswith(".maas.aliyuncs.com")):
            base = base.rstrip("/") + "/apps/anthropic"
            auth_mode = "bearer"
        elif service == "minimax" and host in {"api.minimax.cn", "api.minimax.io", "api.minimaxi.com"}:
            auth_mode = "bearer"
        elif host == "api.qnaigc.com":
            base, auth_mode = "https://api.qnaigc.com", "bearer"
        elif _provider_adapter_id(provider) == "anthropic-compatible":
            # An Anthropic-compatible adapter is an explicit Messages contract.
            source = "configured-anthropic-contract"
        else:
            return {}
    base = _anthropic_sdk_base_url(base)
    if not base:
        return {}
    return {"baseUrl": base, "authMode": auth_mode or "bearer", "source": source}


def anthropic_protocol_support(row: dict[str, Any]) -> bool | None:
    """Read directory evidence, not the default endpoint chosen for text calls."""
    if "agent_protocol_support" in row:
        return row["agent_protocol_support"]
    aliases = {"anthropic", "anthropic-messages", "anthropic_messages", "/v1/messages"}
    capabilities = row.get("api_capabilities")
    if isinstance(capabilities, dict) and "anthropic_messages" in capabilities:
        value = capabilities["anthropic_messages"]
        if isinstance(value, bool):
            return value
        if isinstance(value, dict):
            return value.get("supported") is not False
    for field in ("support_api_protocols", "supported_protocols", "api_protocols", "supported_endpoint_types"):
        values = row.get(field)
        if isinstance(values, list) and values:
            if aliases.intersection(str(value).strip().lower() for value in values):
                return True
            # new-api endpoint hints are not an exhaustive list of conversion paths.
            return None if field == "supported_endpoint_types" else False
    if str(row.get("endpoint") or row.get("generation_endpoint") or "").lower() in aliases:
        return True
    return None


def tool_calling_support(row: dict[str, Any], *, exhaustive_features: bool = False) -> bool | None:
    """Normalize supplier declarations once; an explicit denial always wins."""
    from utils.model_exclusions import normalized_model_id
    from utils.text_model_contracts import general_text_pending_reason

    # These specialist families lack tools even when a saved generic Messages
    # route exists. Include official aliases and dated versions, not substrings.
    name = normalized_model_id(row)
    if general_text_pending_reason(row):
        return False
    if re.fullmatch(
        r"qwen-(?:long|(?:plus|flash)-character)"
        r"(?:-latest|-\d{4}(?:-\d{2}-\d{2})?)?",
        name,
    ):
        return False
    values = []
    architecture = row.get("architecture")
    if isinstance(architecture, dict):
        values.append(architecture.get("function_calling"))
    features = row.get("features")
    if isinstance(features, dict):
        tools = features.get("tools")
        if isinstance(tools, dict):
            values.append(tools.get("function_calling"))
    elif isinstance(features, list):
        declared = "function-calling" in features
        if declared or exhaustive_features:
            values.append(declared)
    states = [value.get("supported") if isinstance(value, dict) else value for value in values]
    if any(value is False for value in states):
        return False
    return True if any(value is True for value in states) else None


def _dashscope_messages_model(row: dict[str, Any]) -> bool:
    # https://help.aliyun.com/zh/model-studio/anthropic-api-messages
    # A provider label is not a protocol contract: Bailian also serves third-party models.
    name = str(row.get("api_model_id") or row.get("id") or "").lower()
    families = (
        r"qwen(?:3\.(?:5|6|7|8)-(?:max|plus|flash)|3-max|plus|flash|turbo)",
        r"qwen3-coder-(?:next|plus|flash)", r"qwen(?:3-vl-(?:plus|flash)|-vl-(?:max|plus))",
        r"qwen3\.(?:5-(?:397b-a17b|122b-a10b|27b|35b-a3b)|6-27b|8-(?:2\.4t-a95b|27b))",
        r"deepseek-(?:v4\.1-flash|v4-(?:pro|flash)|v3\.2)",
        r"kimi-(?:k3|k2\.7-code|k2\.6|k2\.5|k2-thinking)",
        r"glm-(?:5\.3|5\.2|5\.1|5|4\.7|4\.6)", r"minimax-(?:m2\.5|m2\.1)",
    )
    return any(re.fullmatch(f"(?:{family})(?:-latest|-preview|-\\d{{4}}(?:-\\d{{2}}-\\d{{2}})?)?", name) for family in families)


def _newapi_messages_family(row: dict[str, Any]) -> bool:
    from utils.model_classification import classify_model
    from utils.model_exclusions import normalized_model_id

    # Only fallback contracts backed by new-api's native channel converters.
    # relay/channel/{openai,claude,ali,gemini,volcengine,deepseek,moonshot,minimax,zhipu_4v}
    # Site identity alone says nothing about Cohere, xAI or unknown channels.
    name = normalized_model_id(row)
    classification = classify_model(name)
    if classification["kinds"] != ["text"]:
        return False
    vendor = classification["vendor"]
    if vendor == "google":
        return name.startswith("gemini-")
    if vendor == "zhipu":
        return bool(re.match(r"glm-(?:[4-9]|\d{2,})(?:[.-]|$)", name))
    if vendor == "minimax":
        return name.startswith("minimax-m")
    return vendor in {"openai", "anthropic", "alibaba", "volcengine", "deepseek", "moonshot"}


def agent_pending_reason(row: dict[str, Any], route: dict[str, str]) -> str:
    from utils.model_exclusions import normalized_model_id
    from utils.text_model_contracts import general_text_pending_reason

    reason = general_text_pending_reason(row)
    if reason:
        return reason
    if route.get("source") == "new-api-messages-contract":
        protocol = anthropic_protocol_support(row)
        if protocol is False or (protocol is not True and not _newapi_messages_family(row)):
            return "当前模型的智能体协议待适配"
    parsed = urlsplit(str(route.get("baseUrl") or ""))
    # Reproduced on the official Plan Messages route, not on MiniMax or Qiniu.
    if (parsed.hostname == "ark.cn-beijing.volces.com"
            and parsed.path.rstrip("/") == "/api/plan"
            and normalized_model_id(row) == "minimax-m3"):
        return "当前 Agent Plan 路径的工具调用待适配"
    return ""


def classify_agent_models(rows: list[dict[str, Any]], route: dict[str, str]) -> None:
    route_host = (urlsplit(str(route.get("baseUrl") or "")).hostname or "").lower()
    route_path = urlsplit(str(route.get("baseUrl") or "")).path.lower()
    service = "dashscope" if route_host.endswith((".aliyuncs.com", ".maas.aliyuncs.com")) and "/anthropic" in route_path else ""
    for row in rows:
        pending_reason = agent_pending_reason(row, route)
        unsupported = tool_calling_support(row, exhaustive_features=service == "dashscope") is False
        protocol = anthropic_protocol_support(row)
        excluded = protocol is False
        contract = route.get("source") in {"provider-contract", "configured-anthropic-contract", "sub2api-messages-contract", "new-api-messages-contract"}
        if service == "dashscope" and route.get("source") != "configured-anthropic-contract" and protocol is not True:
            contract = _dashscope_messages_model(row)
        excluded = excluded or (protocol is not True and not contract)
        ready = bool(route) and not unsupported and not excluded and not pending_reason
        row["agent_route"] = dict(route) if ready else {}
        row["agent_support_source"] = route.get("source", "") if ready else ""
        row["agent_note"] = pending_reason or ("模型不支持工具调用" if unsupported else "未提供智能体协议" if excluded else "" if route else "智能体接口待配置")
