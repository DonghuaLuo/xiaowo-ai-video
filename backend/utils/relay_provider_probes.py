"""Discover relay models without submitting media generation jobs.

Endpoint metadata describes the relay contract, not the upstream vendor API.
Unknown media contracts remain discoverable but are excluded from task models.
"""

from __future__ import annotations

import copy
import re
import time
import traceback
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from utils.preset_provider_probes import CAPABILITY_GROUPS, _error_message


# https://github.com/QuantumNous/new-api/blob/main/relaykit/types/endpoint_type.go
ENDPOINT_ALIASES = {
    "openai": "openai-chat",
    "openai-response": "openai-responses",
    "anthropic": "anthropic-messages",
    "gemini": "gemini-generate",
    "image-generation": "openai-images-generations",
    "openai-video": "openai-video",
    "/v1/chat/completions": "openai-chat",
    "/v1/responses": "openai-responses",
    "/v1/messages": "anthropic-messages",
    "/v1/images/generations": "openai-images-generations",
    "/v1/images/generations/async": "openai-images-async",
    "/v1/videos": "openai-video",
    "/v1/videos/generations": "grok-video",
}
TEXT_ENDPOINTS = {"openai-chat", "openai-responses", "anthropic-messages", "gemini-generate"}
MEDIA_ENDPOINTS = {
    "openai-images", "openai-images-generations", "openai-images-async", "newapi-video", "ark-seedream", "dashscope-image",
    "gemini-image", "vidu-image", "grok-image", "grok-video", "qiniu-chat-image", "qiniu-images", "qiniu-seedance", "ark-seedance", "dashscope-async-video", "vidu-video",
}


def _endpoint_types(row: dict[str, Any]) -> list[str]:
    value = row.get("supported_endpoint_types")
    if not isinstance(value, list):
        value = []
    explicit = row.get("endpoint") or row.get("generation_endpoint")
    values = [explicit, *value] if explicit else value
    if not values and model_output_kind(row) == "text":
        protocols = row.get("support_api_protocols")
        if isinstance(protocols, list):
            values = [item for item in protocols if item in {"openai", "anthropic"}]
    return list(dict.fromkeys(ENDPOINT_ALIASES.get(str(item), str(item)) for item in values if isinstance(item, str)))


def _is_qiniu(provider: dict[str, Any]) -> bool:
    from project_store_services.provider_connections import _http_url_base

    # Only apply official routes to the official service, including custom entries using it.
    return (urlparse(_http_url_base(str(provider.get("base_url") or ""))).hostname or "").lower() == "api.qnaigc.com"


def model_is_active(row: dict[str, Any]) -> bool:
    from utils.model_exclusions import model_is_excluded

    return not model_is_excluded(row)


def model_output_kinds(row: dict[str, Any]) -> list[str]:
    from utils.model_classification import classify_model

    classification = classify_model(row)
    if not classification["source"].startswith("metadata:"):
        return []
    return [kind for kind in classification["kinds"] if kind in {"image", "video", "text"}] or ["unknown"]


def model_output_kind(row: dict[str, Any]) -> str | None:
    return next(iter(model_output_kinds(row)), None)


def resolve_relay_model(provider: dict[str, Any], raw: dict[str, Any], *, output_kind: str | None = None) -> dict[str, Any]:
    from utils.agent_model_contracts import anthropic_protocol_support
    from utils.text_model_contracts import general_text_pending_reason
    from utils.media_backends import media_endpoint_type
    from utils.model_classification import classify_model
    from utils.video_model_capabilities import QINIU_KLING_MODELS, QINIU_SEEDANCE_MODELS, RETIRED_NEWAPI_VEO_MODELS, newapi_video_capability, qiniu_vidu_capability, video_model_capability, veo_video_capability

    row = copy.deepcopy(raw)
    # Keep directory evidence separate from inferred text defaults below.
    row["agent_protocol_support"] = anthropic_protocol_support(raw)
    name = str(row.get("id") or row.get("model_id") or row.get("name") or "").removeprefix("models/")
    classification = classify_model(raw)
    kinds = classification["kinds"]
    endpoints = _endpoint_types(row)
    generic_openai = raw.get("supported_endpoint_types") == ["openai"] and not (raw.get("endpoint") or raw.get("generation_endpoint"))
    video_contract = video_model_capability(name) if _is_qiniu(provider) and name in {*QINIU_SEEDANCE_MODELS, *QINIU_KLING_MODELS} else None
    if _is_qiniu(provider) and not video_contract:
        video_contract = qiniu_vidu_capability(name) or veo_video_capability(name, qiniu=True)
    # A platform probe only identifies the relay's public base schema. It does
    # not prove that the relay implements the official New API video wire
    # contract: New API-derived services can expose a different JSON task API
    # at the same /v1/videos paths. Only the explicit legacy adapter or an
    # explicit video endpoint declaration is sufficient here.
    from project_store_services.provider_models import _provider_adapter_id

    official_newapi_protocol = _provider_adapter_id(provider) == "newapi-video"
    newapi_contract = (
        newapi_video_capability(name)
        if not _is_qiniu(provider)
        and (official_newapi_protocol or set(endpoints) & {"openai-video", "newapi-video"})
        else None
    )
    if newapi_contract:
        video_contract = newapi_contract
    if not _is_qiniu(provider) and name == "grok-imagine-video-1.5" and (
        not endpoints or generic_openai or "grok-video" in endpoints
    ):
        video_contract = video_model_capability(name)
    # An implemented contract outranks ambiguous names, never explicit output metadata.
    if video_contract and kinds == ["unknown"] and classification["source"] in {"unknown", "series-regex"} and output_kind in {None, "video"}:
        kinds = ["video"]
        classification.update(source="adapter-contract", rule="video.implemented-contract")
    if video_contract and (output_kind == "video" or output_kind is None and "video" in kinds):
        row.update(copy.deepcopy(video_contract))
        row.update(video_contract["metadata"])
        row["output_modalities"] = ["video"]
    endpoints = _endpoint_types(row)
    kind = output_kind or next(iter(kinds), "unknown")
    if kinds == ["unknown"] and str(classification["rule"]).startswith("unknown."):
        if any(endpoint == "openai-video" or media_endpoint_type(endpoint) == "video" for endpoint in endpoints):
            kind = "video"
        elif any(media_endpoint_type(endpoint) == "image" for endpoint in endpoints):
            kind = "image"
        elif any(endpoint in TEXT_ENDPOINTS for endpoint in endpoints):
            kind = "text"
        if kind != "unknown":
            kinds = [kind]
            classification.update(source="metadata:supported_endpoint_types", rule="explicit.endpoint")
    endpoint = ""
    if kind == "text":
        endpoint = next((item for item in endpoints if item in TEXT_ENDPOINTS), "")
        if not endpoints:
            from project_store_services.provider_models import _provider_adapter_id

            adapter_id = _provider_adapter_id(provider)
            if adapter_id == "anthropic-compatible":
                endpoint = "anthropic-messages"
                endpoints = [endpoint]
            elif adapter_id == "gemini-compatible":
                endpoint = "gemini-generate"
                endpoints = [endpoint]
            elif adapter_id == "openai-compatible":
                endpoint = "openai-chat"
                if _is_qiniu(provider):
                    endpoints = ["openai-chat"]
                    row["endpoint_constraints"] = True
    elif kind in {"image", "video"}:
        endpoint = next((item for item in endpoints if item in MEDIA_ENDPOINTS and media_endpoint_type(item) == kind), "")
        # An exact, implemented protocol family is the only name-based media fallback.
        if (not endpoints or generic_openai) and not _is_qiniu(provider) and re.fullmatch(r"gpt-image-[\w.-]+", name):
            endpoint = "openai-images"
        if kind == "image" and "gemini-generate" in endpoints and re.fullmatch(
            r"(?:google/)?gemini-(?:2\.5-flash|3(?:\.0)?-pro|3\.1-flash)-image(?:-preview)?", name,
        ):
            endpoint = "gemini-image"
            row.update(resolutions=["1K"] if "2.5-flash" in name else ["1K", "2K", "4K"], default_resolution="1K")
        if kind == "video" and video_contract and video_contract["provider_prefix"] == "grok":
            endpoint = "grok-video"
        if kind == "video" and newapi_contract:
            endpoint = "newapi-video"
        if _is_qiniu(provider):
            endpoint = ""
            if kind == "video" and video_contract:
                endpoint = {"qiniu-kling": "qiniu-kling-video", "qiniu-vidu": "qiniu-vidu-video", "qiniu-veo": "qiniu-veo-video"}.get(video_contract["provider_prefix"], "qiniu-seedance")
            elif kind == "image" and name == "openai/gpt-image-2":
                endpoint = "qiniu-images"
            elif kind == "image" and name in {"kling-v2-1", "kling-image-o1"}:
                endpoint = "qiniu-kling-image"
                row.update(resolutions=["1K", "2K"] if name == "kling-image-o1" else ["auto"],
                           default_resolution="1K" if name == "kling-image-o1" else "auto",
                           max_reference_images=10 if name == "kling-image-o1" else 1,
                           prompt_hard_limit_chars=2500,
                           capability_source_url="https://apidocs.qnaigc.com/" + ("411327685e0.md" if name == "kling-image-o1" else "397002563e0.md"))
            elif kind == "image" and re.fullmatch(r"(?:google/)?gemini-(?:2\.5-flash|3(?:\.0)?-pro|3\.1-flash)-image(?:-preview)?", name):
                endpoint = "qiniu-chat-image"
            if kind == "image":
                row.setdefault("resolutions", ["auto"])
                row.setdefault("default_resolution", "auto")
    row.update({
        "id": name, "api_model_id": name, "type": kind or "unknown",
        "endpoint": endpoint, "routing_status": "ready" if endpoint else "pending",
        "routing_source": "relay-discovery",
        "routing_note": "" if endpoint else "当前接口尚未适配",
        "supported_endpoint_types": endpoints,
        "model_vendor": classification.get("vendor", "unknown"),
        "vendor_source": classification.get("vendor_source", "unknown"),
        "classification_source": classification["source"],
        "classification_rule": classification["rule"],
    })
    if kind == "text" and (reason := general_text_pending_reason(row)):
        row.update(routing_status="pending", routing_note=reason)
    if kind == "video" and (not endpoint or not row.get("durations") or not row.get("adapter_capabilities")):
        # Metadata alone cannot establish the native keyframe/audio contract of a new relay.
        row.update(endpoint="", routing_status="pending", routing_note="视频提交、进度查询及素材参数待适配")
    if kind == "video" and name in {"sora-2", "sora-2-pro"}:
        row.update(endpoint="", routing_status="pending", routing_note="原厂视频 API 已停用，中转可用性与协议未确认")
    if kind == "video" and not _is_qiniu(provider) and name in RETIRED_NEWAPI_VEO_MODELS:
        row.update(endpoint="", routing_status="pending", routing_note="Gemini API 的 Veo 3.1 Preview 已于 2026-10-22 停用")
    if _is_qiniu(provider) and row["routing_status"] == "pending":
        if name in {"viduq1", "viduq2", "viduq2-turbo", "viduq2-pro", "kling-v2-1", "kling-v2-5-turbo", "kling-video-o1"} and kind == "video":
            row["routing_note"] = "未确认符合有声输出要求，暂不启用"
        elif name in {"minimax/minimax-h3", "minimax/minimax-h3-max", "bytedance/doubao-seedream-5.0-pro"}:
            row["routing_note"] = "七牛网关提交与查询协议待确认，不能套用原厂接口"
        elif name == "kling-video/kling-3.0-turbo":
            row["routing_note"] = "七牛接口未明确有声参数，暂不启用"
    if output_kind is None:
        row["capability_routes"] = {}
        for item in kinds:
            view = row if item == row["type"] else resolve_relay_model(provider, raw, output_kind=item)
            row["capability_routes"][item] = {
                key: copy.deepcopy(view[key]) for key in (
                    "endpoint", "routing_status", "routing_note", "endpoint_constraints", "supported_endpoint_types", "resolutions", "default_resolution",
                    "max_reference_images", "prompt_hard_limit_chars", "capability_source_url",
                ) if key in view
            }
            if item == "image" and item != row["type"] and not view.get("resolutions"):
                row["capability_routes"][item].update(resolutions=["auto"], default_resolution="auto")
    return row


def relay_model_for_capability(row: dict[str, Any], kind: str) -> dict[str, Any] | None:
    from utils.model_exclusions import model_is_excluded

    if model_is_excluded(row, output_kind=kind):
        return None
    routes = row.get("capability_routes")
    if not isinstance(routes, dict):
        return copy.deepcopy(row) if row.get("type") == kind else None
    if kind not in routes:
        return None
    return {**copy.deepcopy(row), **copy.deepcopy(routes[kind]), "type": kind}


def _qiniu_catalog_models() -> list[dict[str, Any]]:
    from project_store_services.provider_connections import _extract_provider_model_rows, _request_json

    # Public metadata is fetched without credentials and never validates a user Key.
    data = _request_json("GET", "https://web-api.qiniu.com/api/proxy/ai-inference/inapi/v2/models?sort=rank&order=asc", headers={
        "Origin": "https://www.qiniu.com", "Referer": "https://www.qiniu.com/ai/models", "User-Agent": "Mozilla/5.0",
    }, timeout=3)
    return _extract_provider_model_rows(data)


def _merge_catalog_metadata(catalog: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(catalog)
    for key, value in remote.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_catalog_metadata(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _supplement_qiniu_models(rows: list[dict[str, Any]], probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from utils.video_model_capabilities import QINIU_SEEDANCE_MODELS, QINIU_VEO_MODELS

    indexed = {row["id"]: {**row, "discovery_source": "key-model-list"} for row in rows}
    try:
        catalog = [{**row, "discovery_source": "official-catalog"} for row in _qiniu_catalog_models()]
        probes.append({"name": "models.catalog", "status": "ok", "remoteModelCount": len(catalog)})
    except Exception:
        print(traceback.format_exc(), flush=True)
        catalog = []
        probes.append({"name": "models.catalog", "status": "warn", "error": "官方目录暂不可用"})
    # Documented image contract currently absent from both official model lists.
    catalog.append({"id": "openai/gpt-image-2", "type": "image", "capability_source_url": "https://apidocs.qnaigc.com/448014490e0.md", "discovery_source": "official-documentation"})
    catalog.extend({"id": name, "type": "video", "capability_source_url": source, "discovery_source": "official-documentation"}
                   for name, source in {**QINIU_SEEDANCE_MODELS, **QINIU_VEO_MODELS}.items())
    by_id: dict[str, dict[str, Any]] = {}
    aliases: dict[str, set[str]] = {}
    for row in catalog:
        name = row["id"]
        by_id[name] = {**row, **by_id.get(name, {})}
        for alias in row.get("model_alias") or []:
            if isinstance(alias, str):
                aliases.setdefault(alias, set()).add(name)
    # Match against the entire catalog, including retired rows, before filtering.
    for name, row in list(indexed.items()):
        targets = {name} if name in by_id else aliases.get(name, set())
        if len(targets) == 1:
            target = next(iter(targets))
            indexed[name] = {
                **_merge_catalog_metadata(by_id[target], row), "id": name,
                "catalog_model_id": target, "catalog_match": "exact" if target == name else "alias",
            }
    for name, row in by_id.items():
        if name not in indexed and set(model_output_kinds(row)) & {"image", "video"}:
            indexed[name] = {**row, "discovery_source": row.get("discovery_source") or "official-catalog"}
    return list(indexed.values())




def _discover_models(provider: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from project_store_services.provider_connections import _provider_probe_url_and_headers

    url, headers, _ = _provider_probe_url_and_headers(provider)
    attempts = []
    rows: dict[str, dict[str, Any]] = {}
    primary_probe = None
    deadline = time.monotonic() + 12
    try:
        batch, primary_probe = _fetch_model_pages(
            url,
            headers,
            str(provider["api_key"]),
            gemini=provider.get("adapter_id") == "gemini-compatible",
            deadline=deadline,
        )
        rows.update({row["id"]: row for row in batch})
    except Exception as exc:
        attempts.append({"url": url, "error": _error_message(exc, str(provider["api_key"]))})
    if not rows or primary_probe is None:
        raise ValueError(attempts[0]["error"] if attempts else "没有获取到模型列表")
    return list(rows.values()), {**primary_probe, "attempts": attempts}


def _fetch_model_pages(url: str, headers: dict[str, str], key: str, *, gemini: bool = False, deadline: float | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from project_store_services.provider_connections import (
        _extract_provider_model_rows, _request_json,
    )

    rows: dict[str, dict[str, Any]] = {}
    after = ""
    seen: set[str] = set()
    cursor_key = "pageToken" if gemini else "after"
    deadline = deadline if deadline is not None else time.monotonic() + 12
    def request(page_url: str) -> Any:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("模型列表获取超时，未完成分页")
        return _request_json("GET", page_url, headers=headers, timeout=min(5, remaining))
    for _ in range(20):
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        if after:
            query[cursor_key] = after
        page_url = urlunsplit(parts._replace(query=urlencode(query)))
        try:
            data = request(page_url)
        except Exception as exc:
            if gemini or rows or not re.search(r"HTTP\s+(401|403):", str(exc)):
                raise
            headers = (
                {"x-api-key": key, "anthropic-version": "2023-06-01"}
                if "Authorization" in headers else
                {"Authorization": f"Bearer {key}", "anthropic-version": "2023-06-01"}
            )
            data = request(page_url)
        if not isinstance(data, dict) or (gemini and not isinstance(data.get("models"), list)):
            raise ValueError("模型列表格式不匹配")
        batch = _extract_provider_model_rows(data)
        if not batch:
            raise ValueError("没有获取到模型列表")
        for row in batch:
            row["id"] = str(row["id"]).removeprefix("models/")
            row["discovery_source"] = "key-model-list"
            if gemini:
                methods = row.get("supportedGenerationMethods") or []
                if "generateContent" in methods:
                    row["supported_endpoint_types"] = ["gemini-generate"]
                elif methods:
                    row["output_modalities"] = ["unknown"]
            rows[row["id"]] = row
        if not data.get("has_more") and not data.get("nextPageToken"):
            return list(rows.values()), {"name": "models.list", "status": "ok", "url": url,
                                         "authMode": "google-api-key" if gemini else "bearer" if "Authorization" in headers else "x-api-key"}
        cursor_key = "pageToken" if data.get("nextPageToken") else "after_id" if (
            "anthropic-version" in headers or "first_id" in data
        ) else "after"
        after = str(data.get("nextPageToken") or data.get("last_id") or "")
        if not after or after in seen:
            raise ValueError("模型列表分页信息无效")
        seen.add(after)
    raise ValueError("模型列表分页超过探测上限")


def _discover_agent_route(
    provider: dict[str, Any], *, deadline: float,
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    """Discover an Anthropic route with a model-list request only.

    A shared OpenAI directory is not evidence of a Messages endpoint.
    """
    from project_store_services.provider_connections import (
        _candidate_anthropic_agent_base_urls,
        _provider_probe_url_and_headers,
    )
    from utils.agent_model_contracts import agent_route, anthropic_protocol_support

    attempts: list[dict[str, Any]] = []
    candidates = _candidate_anthropic_agent_base_urls(provider)
    for base in candidates:
        if time.monotonic() >= deadline:
            break
        candidate = {**provider, "adapter_id": "anthropic-compatible", "base_url": base}
        url, headers, _ = _provider_probe_url_and_headers(candidate)
        try:
            rows, probe = _fetch_model_pages(
                url, headers, str(provider.get("api_key") or ""), deadline=deadline,
            )
            # Response serialization is not a Messages capability declaration.
            rows = [row for row in rows if anthropic_protocol_support(row) is True]
            route = agent_route({**provider, "agent_base_url": base})
            if route and rows:
                route["authMode"] = str(probe.get("authMode") or "bearer")
                route["source"] = "anthropic-model-directory"
                return rows, route, [
                    *attempts,
                    {**probe, **route, "name": "agent.models", "status": "ok", "url": url},
                ]
        except Exception as exc:
            attempts.append({
                "name": "agent.models", "status": "unknown", "url": url,
                "error": _error_message(exc, str(provider.get("api_key") or "")),
            })
    return [], {}, attempts


def _detect_relay_platform(provider: dict[str, Any], *, deadline: float) -> tuple[str, dict[str, Any]]:
    """Identify a relay platform from its public schema, never its site name."""
    from project_store_services.provider_connections import _anthropic_sdk_base_url, _request_json

    base = _anthropic_sdk_base_url(str(provider.get("base_url") or ""))
    if not base:
        return "", {}
    attempts = []
    for platform, path in (("sub2api", "/api/v1/settings/public"), ("new-api", "/api/status")):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        url = f"{base}{path}"
        attempts.append(url)
        try:
            response = _request_json("GET", url, headers={}, timeout=min(1, remaining))
        except Exception:
            continue
        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, dict):
            continue
        if platform == "sub2api":
            # PublicSettings DTO; gateway.go converts Messages for OpenAI groups.
            flags = ("hide_ccs_import_button", "purchase_subscription_enabled", "backend_mode_enabled")
            matches = (all(isinstance(data.get(key), bool) for key in flags)
                       and isinstance(data.get("api_base_url"), str))
        else:
            # QuantumNous/new-api controller/misc.go GetStatus + relay/claude_handler.go.
            # Do not depend on site names, optional panel content or a version string's value.
            flags = ("api_info_enabled", "enable_drawing", "enable_task", "default_use_auto_group")
            matches = (response.get("success") is True
                       and all(isinstance(data.get(key), bool) for key in flags)
                       and all(isinstance(data.get(key), str) for key in
                               ("version", "HeaderNavModules", "SidebarModulesAdmin")))
        if matches:
            # Public metadata is evidence only. Never follow its advertised server/API URL.
            return platform, {"name": "platform.contract", "status": "ok", "platform": platform, "url": url}
    return "", {"name": "platform.contract", "status": "unknown", "attempts": attempts}


def _relay_platform_agent_contract(provider: dict[str, Any], *, deadline: float) -> tuple[dict[str, str], dict[str, Any]]:
    """Identify the public platform schema and build its Messages route."""
    from utils.agent_model_contracts import agent_route

    platform, probe = _detect_relay_platform(provider, deadline=deadline)
    if not platform:
        return {}, probe
    route = agent_route(provider, base_url=str(provider.get("base_url") or ""))
    route["source"] = f"{platform}-messages-contract"
    return route, probe


def run_relay_capability_probes(
    provider: dict[str, Any], *, on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    from project_store_services.provider_connections import _finalize_provider_capability_result

    started = time.perf_counter()
    requested = set(provider.get("capabilities") or [])
    results: dict[str, Any] = {}
    allowed: dict[str, list[str]] = {}
    probes: list[dict[str, Any]] = []
    discovered: list[dict[str, Any]] | None = None
    discovery_error = ""
    retained: dict[str, dict[str, Any]] = {}
    pending: dict[str, dict[str, str]] = {}
    inventory: list[dict[str, Any]] = []

    relay_platform = ""
    platform_probe: dict[str, Any] = {}
    from project_store_services.provider_models import _provider_adapter_id
    # Platform identification is needed only for OpenAI-compatible relays.
    # Native Anthropic/Gemini video adapters use their own contracts and must
    # not receive unrelated public platform probes.
    if (
        "storyboard_video" in requested
        and _provider_adapter_id(provider) in {"openai-compatible", "newapi-video"}
        and not _is_qiniu(provider)
    ):
        relay_platform, platform_probe = _detect_relay_platform(
            provider, deadline=time.monotonic() + 2,
        )
        if platform_probe:
            probes.append(platform_probe)
    effective_provider = provider

    def report(group: str, status: str, count: int = 0) -> None:
        if on_progress:
            try:
                on_progress({"group": group, "status": status, "modelCount": count})
            except Exception:
                print(traceback.format_exc(), flush=True)

    for group, capabilities in CAPABILITY_GROUPS.items():
        if not requested.intersection(capabilities):
            continue
        allowed[group] = []
        report(group, "testing")
        try:
            if discovered is None:
                discovered = []
                try:
                    remote, probe = _discover_models(effective_provider)
                    probes.append(probe)
                    if _is_qiniu(provider):
                        remote = _supplement_qiniu_models(remote, probes)
                    inventory = [resolve_relay_model(effective_provider, row) for row in remote]
                    discovered = [row for row in inventory if model_is_active(row)]
                except Exception as exc:
                    discovery_error = _error_message(exc, str(provider["api_key"]))
                    probes.append({"name": "models.list", "status": "failed", "error": discovery_error})
            if discovery_error and group != "agent":
                raise ValueError(discovery_error)
            if group == "agent":
                from utils.agent_model_contracts import agent_route, anthropic_protocol_support
                from project_store_services.provider_connections import _anthropic_models_url

                route = agent_route(provider)
                agent_directory_ids = None
                if not route and any(anthropic_protocol_support(row) is True for row in discovered):
                    route = agent_route(provider, base_url=str(provider.get("base_url") or ""))
                    if route:
                        route["source"] = "model-protocol-declaration"
                if discovered and (not route or route.get("source") == "model-protocol-declaration"):
                    # A model's endpoint hints cannot describe the platform's conversion paths.
                    # At most two public GETs with one shared budget; never generate content here.
                    platform_route, platform_probe = _relay_platform_agent_contract(provider, deadline=time.monotonic() + 2)
                    if platform_route:
                        route = platform_route
                    if platform_probe:
                        probes.append(platform_probe)
                if not route:
                    agent_rows, discovered_route, agent_probes = _discover_agent_route(
                        provider, deadline=time.monotonic() + 4,
                    )
                    probes.extend(agent_probes)
                    if discovered_route:
                        route = discovered_route
                        agent_directory_ids = {str(row["id"]) for row in agent_rows}
                        by_id = {row["id"]: row for row in discovered}
                        for raw in agent_rows:
                            resolved = resolve_relay_model(effective_provider, raw)
                            if model_is_active(resolved):
                                existing = by_id.setdefault(resolved["id"], resolved)
                                # A separate agent directory may expose a different
                                # protocol for the same model than the text directory.
                                existing["agent_protocol_support"] = resolved["agent_protocol_support"]
                                if resolved["id"] not in {row["id"] for row in inventory}:
                                    inventory.append(copy.deepcopy(resolved))
                        discovered = list(by_id.values())
                if route:
                    matching_probe = next((item for item in probes if (
                        item.get("name") == "models.list" and item.get("status") == "ok"
                        and item.get("url") == _anthropic_models_url(route["baseUrl"])
                    )), {})
                    if matching_probe.get("authMode") in {"bearer", "x-api-key"}:
                        route["authMode"] = matching_probe["authMode"]
                if discovery_error and not discovered:
                    raise ValueError(discovery_error)
            kind = "text" if group == "agent" else group
            rows = [view for row in discovered if (view := relay_model_for_capability(row, kind)) is not None]
            if not rows:
                results[group] = {"status": "unsupported", "message": "未发现此类模型", "modelCount": 0}
                report(group, "unsupported")
                continue
            message = "已获取模型"
            state = "ok"
            if group == "agent":
                from utils.agent_model_contracts import classify_agent_models

                classify_agent_models(rows, route)
                if agent_directory_ids is not None:
                    classify_agent_models([row for row in rows if row["id"] not in agent_directory_ids], {})
                allowed[group] = [row["id"] for row in rows if row["agent_route"]]
                # Discovery succeeds even when every execution contract is pending.
                state = "ok"
                probes.append({"name": "agent.route", "status": "ok" if route else "unknown", **route})
                message = "已获取模型"
            if group != "agent":
                allowed[group] = [row["id"] for row in rows if row["routing_status"] == "ready"]
                if not allowed[group]:
                    message = "已获取模型，但当前模型尚未完成接口适配"
            for row in rows:
                original = retained.setdefault(row["id"], copy.deepcopy(next((item for item in discovered if item["id"] == row["id"]), row)))
                if group == "agent":
                    original["agent_protocol_support"] = row.get("agent_protocol_support")
                    original["agent_support_source"] = row.get("agent_support_source", "")
                    original["agent_route"] = row.get("agent_route", {})
                    original["agent_note"] = row.get("agent_note", "")
                if group != "agent" and kind in original.get("capability_routes", {}):
                    original["capability_routes"][kind].update({key: row[key] for key in ("endpoint", "routing_status", "routing_note")})
                if group != "agent" and original["type"] == kind:
                    original.update({key: row[key] for key in ("endpoint", "routing_status", "routing_note")})
                if row["id"] not in allowed[group]:
                    pending[f"{group}:{row['id']}"] = {"id": row["id"], "type": group, "reason": row.get("agent_note") if group == "agent" else row["routing_note"]}
            missing = len(rows) - len(allowed[group])
            if missing and group != "agent":
                message += f"；{missing} 个待适配"
            sources = {row.get("discovery_source", "key-model-list") for row in rows}
            # Public catalog rows are fetched online; only documentation supplements are local.
            source = "remote" if sources <= {"key-model-list", "official-catalog"} else (
                "preset" if sources == {"official-documentation"} else "mixed"
            )
            results[group] = {"status": state, "message": message, "modelCount": len(rows), "pendingModelCount": missing, "modelSource": source}
        except Exception as exc:
            results[group] = {"status": "failed", "message": _error_message(exc, str(provider["api_key"])), "modelCount": 0}
        report(group, results[group]["status"], results[group]["modelCount"])

    # Preserve unknown discoveries for diagnostics, but never turn them into text models.
    for row in discovered or []:
        if row["type"] not in {"image", "video", "text"}:
            pending[row["id"]] = {"id": row["id"], "type": row["type"], "reason": "模型能力未识别" if row["type"] == "unknown" else "非当前插件生成类型"}
    return _finalize_provider_capability_result(
        provider, started=started, results=results, models=list(retained.values()),
        capability_models=allowed, probes=probes, pending_models=list(pending.values()),
        discovered_models=inventory,
    )
