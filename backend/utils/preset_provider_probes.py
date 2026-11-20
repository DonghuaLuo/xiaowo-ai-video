"""Named-provider capability probes. Never submit image or video generation jobs."""

from __future__ import annotations

import copy
import time
import traceback
from typing import Any, Callable
from urllib.parse import urlencode, urlparse


CAPABILITY_GROUPS = {
    "image": ("storyboard_image", "asset_image"),
    "text": ("text_generation",),
    "video": ("storyboard_video",),
    "agent": ("agent",),
}
PRESET_GROUPS = {
    "ark-seedance": ("image", "text", "video", "agent"),
    "ark-agent-plan": ("agent",),
    "anthropic": ("text", "agent"),
    "deepseek": ("text", "agent"),
    "minimax": ("image", "text", "video", "agent"),
    "metaso": ("video",),
    "autodl-comfyui": ("video",),
    "dashscope": ("image", "text", "video", "agent"),
    "gemini": ("image", "text"),
    "vidu": ("image", "video"),
}

# Official endpoint references (media probes only read existing account/task data):
# https://docs.volcengine.com/docs/ark/messages-api
# https://help.aliyun.com/zh/model-studio/base-url
# https://help.aliyun.com/zh/model-studio/list-models
# https://api-docs.deepseek.com/api/list-models/
# https://ai.google.dev/api/models
# https://docs.platform.vidu.com/334420735e0


def uses_preset_capability_probes(provider: dict[str, Any]) -> bool:
    from project_store_services.provider_models import _provider_service_id

    service = _provider_service_id(provider)
    if service in {"metaso", "autodl-comfyui"}:
        # Validate the native deployment address before authenticated discovery,
        # including when a caller bypasses the UI.
        return True
    host = (urlparse(str(provider.get("base_url") or "")).hostname or "").lower()
    hosts = {
        "ark-seedance": {"ark.cn-beijing.volces.com"},
        "ark-agent-plan": {"ark.cn-beijing.volces.com"},
        "anthropic": {"api.anthropic.com"},
        "deepseek": {"api.deepseek.com"},
        "minimax": {"api.minimax.cn", "api.minimax.io", "api.minimaxi.com"},
        "dashscope": {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com", "cn-hongkong.dashscope.aliyuncs.com"},
        "gemini": {"generativelanguage.googleapis.com"},
        "vidu": {"api.vidu.com", "api.vidu.cn"},
    }
    return host in hosts.get(service, set()) or (
        service == "dashscope" and host.endswith(".maas.aliyuncs.com")
    )


def _catalog_models(provider: dict[str, Any], group: str) -> list[dict[str, Any]]:
    from project_store_services.catalogs import BUILTIN_PROVIDER_MODELS
    from project_store_services.provider_models import _provider_service_id

    kind = "text" if group == "agent" else group
    return [copy.deepcopy(row) for row in BUILTIN_PROVIDER_MODELS.get(_provider_service_id(provider), []) if row.get("type") == kind]


def _model_name(row: dict[str, Any]) -> str:
    from project_store_services.model_provider_config import _api_model_name

    return str(row["api_model_id"]) if row.get("api_model_id") else _api_model_name(row.get("id") or row.get("model") or row.get("name")).removeprefix("models/")


def _documented_media_models(provider: dict[str, Any], group: str) -> list[dict[str, Any]]:
    """Return the locally adapted subset of the official operation catalogs."""
    from project_store_services.provider_models import _provider_service_id

    service = _provider_service_id(provider)
    sources = {
        ("vidu", "image"): "https://platform.vidu.com/docs/reference-to-image",
        ("vidu", "video"): "https://platform.vidu.com/docs/model-map",
        ("minimax", "image"): "https://platform.minimax.cn/docs/api-reference/image-generation-t2i",
        ("minimax", "video"): "https://platform.minimax.cn/docs/api-reference/video-generation-v2-create",
    }
    source = sources.get((service, group))
    if not source:
        return []
    rows = _catalog_models(provider, group)
    for row in rows:
        name = _model_name(row)
        row.update(
            id=name, api_model_id=name, discovery_source="official-catalog",
            catalog_source_url=row.get("capability_source_url") or source,
            catalog_scope="local-adapted-media", catalog_only=True,
            auth_checked=False, entitlement_checked=False, generation_verified=False,
        )
    return rows


def _official_plan_bases(provider: dict[str, Any]) -> list[str]:
    """Return only documented Ark Plan roots eligible for the no-directory exception."""
    from project_store_services.provider_models import _provider_service_id

    service = _provider_service_id(provider)
    if service != "ark-agent-plan":
        return []
    base = str(provider.get("base_url") or "").rstrip("/")
    parsed = urlparse(base)
    if parsed.hostname != "ark.cn-beijing.volces.com":
        return []
    path = parsed.path.rstrip("/")
    if path in {"/api/plan", "/api/coding"}:
        return [base]
    return []


def _error_message(exc: Exception, api_key: str) -> str:
    print(traceback.format_exc().replace(api_key, "[redacted]"), flush=True)
    return str(exc).replace(api_key, "[redacted]").replace("\n", " ")[:240]


def _redact_probe(value: Any, api_key: str) -> Any:
    if isinstance(value, str):
        return value.replace(api_key, "[redacted]")
    if isinstance(value, dict):
        return {key: _redact_probe(item, api_key) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_probe(item, api_key) for item in value]
    return value


def _list_models(provider: dict[str, Any], group: str) -> list[dict[str, Any]]:
    from project_store_services.provider_connections import _request_json
    from project_store_services.provider_models import _provider_service_id

    service = _provider_service_id(provider)
    if service == "metaso":
        parsed = urlparse(str(provider.get("base_url") or ""))
        if (parsed.scheme != "https" or parsed.netloc.lower() != "metaso.cn"
                or parsed.path.rstrip("/") != "/api/minimax" or parsed.query or parsed.fragment):
            raise ValueError("秘塔请求地址应为 https://metaso.cn/api/minimax")
    if service == "vidu":
        # Official docs enumerate models per operation, not through a GET
        # /models contract. Loading that catalog does not validate a key.
        return _documented_media_models(provider, group)
    base = str(provider["base_url"]).rstrip("/")
    key = str(provider["api_key"])
    headers = {"Authorization": f"Bearer {key}"}
    deadline = time.monotonic() + 12
    def request(url: str, request_headers: dict[str, str]) -> Any:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("模型列表获取超时，未完成分页")
        return _request_json("GET", url, headers=request_headers, timeout=min(5, remaining))

    rows: list[dict[str, Any]] = []
    token = ""
    seen_tokens: set[str] = set()
    for page in range(1, 21):
        if service == "gemini":
            query = {"pageSize": 1000, **({"pageToken": token} if token else {})}
            url = f"{base}/v1beta/models?{urlencode(query)}"
            data = request(url, {"x-goog-api-key": key})
            batch = data.get("models")
        elif service == "dashscope":
            query = {"capabilities": {"image": "IG", "video": "VG", "text": "TG", "agent": "TG"}[group], "page_no": page, "page_size": 100}
            url = f"{base}/api/v1/models?{urlencode(query)}"
            data = request(url, headers)
            output = data.get("output") or {}
            batch = output.get("models")
        elif service == "metaso":
            # Verified against the live deployment on 2026-10-08. The separate
            # /api/openai catalog also lists models with a different protocol.
            data = request(f"{base}/v1/models", headers)
            if not isinstance(data, dict) or data.get("has_more"):
                raise ValueError("秘塔模型列表响应无效或目录不完整")
            batch = data.get("data")
        elif service == "minimax":
            parsed = urlparse(base)
            origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base
            # Text/agent use MiniMax's Anthropic-compatible catalog; media uses
            # the official OpenAI-compatible catalog at the origin root.
            url = f"{base.rstrip('/')}/v1/models" if group in {"text", "agent"} else f"{origin}/v1/models"
            if token:
                url += "?" + urlencode({"after_id": token})
            data = request(url, headers)
            batch = data.get("data")
        elif service == "anthropic":
            from project_store_services.provider_connections import _anthropic_auth_headers, _anthropic_models_url

            url = _anthropic_models_url(base)
            if token:
                url += "?" + urlencode({"after_id": token})
            data = request(url, _anthropic_auth_headers(provider, key))
            batch = data.get("data")
        elif service == "deepseek":
            # DeepSeek exposes model discovery on the OpenAI-compatible root.
            # Its Anthropic-compatible base is only used for messages.create.
            from project_store_services.provider_connections import _deepseek_discovery_root

            url = f"{_deepseek_discovery_root(base)}/models"
            data = request(url, headers)
            batch = data.get("data")
        else:
            data = request("https://api.deepseek.com/models", headers)
            batch = data.get("data")
        if not isinstance(batch, list):
            raise ValueError("模型列表响应格式不正确")
        for row in batch:
            if isinstance(row, dict):
                model_id = str(row.get("model") or row.get("id") or row.get("name") or "").removeprefix("models/")
                if model_id:
                    rows.append({**row, "id": model_id, "api_model_id": model_id})
        if service == "gemini":
            token = str(data.get("nextPageToken") or "")
            if not token:
                return rows
            if token in seen_tokens:
                raise ValueError("模型列表返回了重复的分页标记")
            seen_tokens.add(token)
        elif service == "dashscope":
            if not batch or len(rows) >= int(output.get("total") or 0):
                return rows
        elif service in {"minimax", "anthropic"} and data.get("has_more"):
            token = str(data.get("last_id") or "")
            if not token or token in seen_tokens:
                raise ValueError("模型列表分页信息无效")
            seen_tokens.add(token)
        else:
            return rows
    raise ValueError("模型列表分页超过探测上限，请稍后重试")


def _discovered_models(provider: dict[str, Any], group: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from project_store_services.provider_models import _provider_service_id
    from utils.model_classification import classify_model
    from utils.model_exclusions import model_is_excluded
    from utils.text_model_contracts import general_text_pending_reason

    service = _provider_service_id(provider)
    kind = "text" if group == "agent" else group
    catalog = {_model_name(row): row for row in _catalog_models(provider, group)}
    result = []
    for raw in rows:
        name = _model_name(raw)
        classification = classify_model(raw, **(
            {"list_kind": kind, "list_source": f"dashscope:capabilities={kind}"}
            if service == "dashscope" else {}
        ))
        if kind not in classification["kinds"]:
            continue
        if model_is_excluded({**raw, "provider_preset_id": service}, output_kind=kind):
            continue
        row = {**raw, "classification_source": classification["source"], "classification_rule": classification["rule"],
               "model_vendor": classification.get("vendor", "unknown"), "vendor_source": classification.get("vendor_source", "unknown")}
        if kind in {"image", "video"}:
            if name in catalog:
                result.append({**catalog[name], **row, "id": name, "api_model_id": name, "type": kind})
            else:
                result.append({**row, "id": name, "api_model_id": name, "type": kind,
                               "routing_status": "pending", "routing_source": "relay-discovery",
                               "endpoint": "", "routing_note": "当前模型的生成参数待适配"})
        else:
            result.append({**catalog.get(name, {}), **row, "id": name, "api_model_id": name, "type": "text",
                           **({"endpoint": "gemini-generate"} if service == "gemini" else {}),
                           **({"routing_status": "pending", "routing_note": reason}
                              if (reason := general_text_pending_reason(row)) else {})})
    return result


def run_preset_capability_probes(
    provider: dict[str, Any],
    *,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    from project_store_services.provider_connections import _finalize_provider_capability_result
    from project_store_services.provider_models import _provider_service_id, _with_model_generation_endpoint
    from utils.agent_model_contracts import agent_route, classify_agent_models, documented_plan_catalog
    from utils.relay_provider_probes import _discover_models

    started = time.perf_counter()
    service = _provider_service_id(provider)
    requested = set(provider.get("capabilities") or [])
    if service == "autodl-comfyui":
        from utils.autodl_comfyui import probe_autodl_provider

        return probe_autodl_provider(provider, on_progress=on_progress)
    results: dict[str, Any] = {}
    models: dict[str, dict[str, Any]] = {}
    capability_models: dict[str, list[str]] = {}
    probes: list[dict[str, Any]] = []
    pending_models: list[dict[str, str]] = []
    inventory: dict[str, dict[str, Any]] = {}
    cache: dict[str, Any] = {}
    route = agent_route(provider, auth_mode="x-api-key") if service == "anthropic" else agent_route(provider)
    plan_bases = _official_plan_bases(provider)
    plan_catalog: list[dict[str, Any]] = []
    plan_auth_checked = False

    def discover_official_plan() -> list[dict[str, Any]]:
        nonlocal route, plan_auth_checked
        if plan_auth_checked:
            return plan_catalog
        plan_auth_checked = True
        for base in plan_bases:
            catalog = documented_plan_catalog(base)
            if not catalog:
                continue
            # Agent Plan has no model-directory endpoint. Its documented
            # catalog is the discovery source; configuration must not send a
            # paid Messages request just to prove the key.
            route = agent_route(provider, base_url=base, auth_mode="bearer")
            plan_catalog.extend(catalog)
            probes.append({
                # Agent Plan has no model-directory endpoint. The documented
                # catalog is enough to build the local directory, while the
                # actual key/entitlement remains a runtime concern.
                "name": "models.list", "status": "ok", "source": "official-catalog",
                "catalogOnly": True, "authChecked": False, "url": base,
            })
            return plan_catalog
        return []

    def list_models(group: str) -> list[dict[str, Any]]:
        nonlocal route
        if plan_bases and group == "agent":
            rows = discover_official_plan()
            for row in rows:
                inventory[_model_name(row)] = copy.deepcopy(row)
            return rows
        scope = "all" if service in {"ark-seedance", "gemini"} else "text" if group == "agent" else group
        if service == "minimax" and group in {"image", "video"}:
            scope = "media"
        if scope not in cache:
            try:
                if service == "ark-seedance":
                    rows, probe = _discover_models(provider)
                    probes.append(probe)
                else:
                    rows = _list_models(provider, group)
                    probes.append({"name": "models.list", "status": "ok", "group": scope,
                                   **({"source": "official-catalog", "catalogOnly": True,
                                       "authChecked": False, "entitlementChecked": False,
                                       "catalogScope": "local-adapted-media"} if service == "vidu" else {}),
                                   **({"url": f"{str(provider['base_url']).rstrip('/')}/v1/models",
                                       "authChecked": True, "entitlementChecked": False,
                                       "generationVerified": False} if service == "metaso" else {})})
                cache[scope] = rows
                for row in rows:
                    inventory[_model_name(row)] = copy.deepcopy(row)
            except Exception as exc:
                cache[scope] = exc
                probes.append({"name": "models.list", "status": "failed", "group": scope,
                               "error": _error_message(exc, str(provider["api_key"]))})
        value = cache[scope]
        if isinstance(value, Exception):
            raise value
        return value

    def report(group: str, status: str, count: int = 0) -> None:
        if on_progress:
            try:
                on_progress({"group": group, "status": status, "modelCount": count})
            except Exception:
                print(traceback.format_exc(), flush=True)

    for group, capabilities in CAPABILITY_GROUPS.items():
        if not requested.intersection(capabilities):
            continue
        capability_models[group] = []
        report(group, "testing")
        try:
            if group not in PRESET_GROUPS[service]:
                results[group] = {"status": "unsupported", "message": "当前预设未接入此能力", "modelCount": 0}
                continue
            source = "remote"
            if plan_bases and group != "agent":
                results[group] = {"status": "unsupported", "message": "此接口未配置该能力", "modelCount": 0}
                continue
            remote = list_models(group)
            if service == "minimax" and group in {"image", "video"}:
                # An OpenAI-compatible directory may contain text only. Add
                # missing operation contracts without overriding key metadata.
                seen = {_model_name(row) for row in remote}
                documented = [row for row in _documented_media_models(provider, group)
                              if _model_name(row) not in seen]
                if documented:
                    remote = [*remote, *documented]
                    for row in documented:
                        inventory.setdefault(_model_name(row), copy.deepcopy(row))
                    probes.append({"name": "models.list", "status": "ok", "group": group,
                                   "source": "official-catalog", "catalogOnly": True,
                                   "authChecked": False, "entitlementChecked": False,
                                   "catalogScope": "local-adapted-media"})
            rows = _discovered_models(provider, group, remote)
            documented_count = sum(row.get("discovery_source") == "official-catalog" for row in rows)
            if documented_count:
                source = "preset" if documented_count == len(rows) else "mixed"
            for row in rows:
                row.setdefault("discovery_source", "official-catalog" if source == "preset" else "key-model-list")
            if not rows:
                results[group] = {"status": "unsupported", "message": "未发现此类模型", "modelCount": 0}
                continue
            if group == "agent":
                # Provider setup only builds the model directory. The agent
                # route is derived from the provider contract; real requests
                # happen when the model is first used.
                classify_agent_models(rows, route)
                ready = [row for row in rows if row["agent_route"]]
                probes.append({
                    "name": "agent.route",
                    "status": "ok" if route else "unknown",
                    "source": "official-catalog" if plan_bases else route.get("source", ""),
                    **route,
                })
            else:
                ready = [row for row in rows if row.get("routing_status") != "pending"]
            capability_models[group] = [_model_name(row) for row in ready]
            for row in rows:
                name = _model_name(row)
                previous = models.get(name, {})
                merged = {**previous, **row, "id": name}
                if previous and previous.get("type") != row.get("type"):
                    routes = copy.deepcopy(previous.get("capability_routes") or {})
                    for view in (previous, row):
                        view = _with_model_generation_endpoint(provider, view)
                        routes[view["type"]] = {key: value for key, value in view.items() if key not in {"id", "api_model_id", "type", "capability_routes"}}
                    merged["capability_routes"] = routes
                models[name] = merged
                if name not in capability_models[group]:
                    pending_models.append({"id": name, "type": group,
                                           "reason": (
                                               row.get("agent_note") if group == "agent"
                                               else row.get("routing_note") or "待适配"
                                           )})
            results[group] = {
                              "status": "ok",
                              "message": "已载入模型" if documented_count or (group == "agent" and plan_bases) else "已获取模型",
                              "modelCount": len(rows),
                              "pendingModelCount": len(rows) - len(ready), "modelSource": source,
                              **({"documentedModelCount": documented_count, "authChecked": False,
                                  "entitlementChecked": False, "generationVerified": False}
                                 if documented_count and group in {"image", "video"} else {})}
        except Exception as exc:
            results[group] = {"status": "failed", "message": _error_message(exc, str(provider["api_key"])), "modelCount": 0}
        finally:
            if group in results:
                report(group, results[group]["status"], results[group]["modelCount"])
    return _finalize_provider_capability_result(
        provider, started=started, results=results, models=list(models.values()),
        capability_models=capability_models, probes=probes, pending_models=pending_models,
        discovered_models=list(inventory.values()),
    )
