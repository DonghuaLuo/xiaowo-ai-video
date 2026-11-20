# -*- coding: utf-8 -*-
"""文本模型协议调用、结构化结果解析与请求响应日志。"""
from __future__ import annotations

from utils.model_reasoning import apply_model_reasoning

from .catalogs import AGENT_ATTACHMENT_MAX_BYTES
from .catalogs import AGENT_MODEL_IMAGE_INPUT_MAX_BYTES
from .media_files import _decode_data_url
from .model_provider_config import _api_model_name
from .model_provider_config import _configured_text_model
from .model_provider_config import _openai_compatible_generation_base_url
from .model_provider_config import _provider_base_url
from .model_request_logs import model_request_log_reference
from .model_request_logs import model_response_log_reference
from .model_request_logs import write_model_request_log
from .model_request_logs import write_model_response_log
from .projects import _normalize_structured_payload
from .projects import _provider_native_structured_endpoint
from .projects import _provider_native_structured_model_record
from .projects import _provider_native_structured_status
from .projects import _provider_supports_native_structured_output
from .projects import _provider_with_native_structured_model_result
from .projects import _save_global_config
from .projects import _structured_model_api_name
from .projects import _structured_prompt
from .projects import _structured_repair_prompt
from .projects import _structured_response_format
from .projects import _structured_system_prompt
from .provider_connections import _NATIVE_JSON_SCHEMA_PROBE_NAME
from .provider_connections import _anthropic_messages_auth_headers
from .provider_connections import _anthropic_messages_url
from .provider_connections import _google_discovery_root_url
from .provider_connections import _notify_response_received
from .provider_connections import _provider_default_base_url
from .provider_connections import _request_json
from .provider_connections import _response_json_for_log
from .provider_connections import _run_native_json_schema_probe
from .provider_models import _is_connected_provider
from .provider_models import _text_model_generation_endpoint
from .provider_models import _model_reference_image_input_limits
from .provider_models import _model_supports_vision_input
from .provider_models import _normalize_provider_id
from .provider_models import _provider_adapter_id
from .provider_models import _provider_service_id
from .provider_reference_media import _data_url_base64_payload
from .provider_reference_media import _provider_image_data_url_from_file_info
from .provider_reference_media import _provider_model_input_images
from .settings_loaders import load_global_config
from .store_core import _serialized_global_config_write
from .task_control import _check_generation_task_cancelled
from typing import Any, Callable
from utils.generation_requests import GenerationCancelled
from utils.generation_requests import run_cancellable_model_request
from utils.media_backends import normalize_media_endpoint
from utils.model_timeouts import MODEL_TEXT_REQUEST_TIMEOUT_SECONDS
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class TextOutputLimitError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("模型输出额度不足，尚未生成完整结果。请提高输出上限后重试。")


def _raise_for_text_output_limit(data: Any) -> None:
    if not isinstance(data, dict):
        return
    details = data.get("incomplete_details")
    choices = data.get("choices")
    candidates = data.get("candidates")
    choice = choices[0] if isinstance(choices, list) and choices else None
    candidate = candidates[0] if isinstance(candidates, list) and candidates else None
    if (
        data.get("stop_reason") == "max_tokens"
        or (isinstance(details, dict) and details.get("reason") == "max_output_tokens")
        or (isinstance(choice, dict) and choice.get("finish_reason") == "length")
        or (isinstance(candidate, dict) and candidate.get("finishReason") == "MAX_TOKENS")
    ):
        raise TextOutputLimitError()


def _notify_text_request_prepared(
    callback: Callable[[dict[str, Any]], None] | None,
    request_info: dict[str, Any],
) -> None:
    if callback is None:
        return
    try:
        callback({"captureLevel": "application_submission", "captureSource": "http_adapter",
                  **request_info})
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "allow_request_prepared_abort", False):
            raise
        print(
            f"[model-request-log] 文本模型请求日志回调失败，已继续主流程: {exc}",
            flush=True,
        )


def _record_text_output_budget(meta: dict[str, Any], request_info: dict[str, Any], requested: int) -> None:
    body = request_info.get("requestBody") or {}
    actual = next((body[key] for key in ("max_tokens", "max_completion_tokens", "max_output_tokens") if key in body),
                  (body.get("generationConfig") or {}).get("maxOutputTokens", requested))
    meta["requestedMaxTokens"] = requested
    meta["maxTokens"] = actual
    meta["reasoningParameters"] = {
        key: body[key] for key in ("thinking", "reasoning", "reasoning_effort", "enable_thinking") if key in body
    }
    effort = (body.get("output_config") or {}).get("effort")
    if effort is not None:
        meta["reasoningParameters"]["effort"] = effort
    thinking_config = (body.get("generationConfig") or {}).get("thinkingConfig")
    if thinking_config is not None:
        meta["reasoningParameters"]["thinkingConfig"] = thinking_config


def _record_text_response_metrics(meta: dict[str, Any], data: Any, started_at: float) -> None:
    if not isinstance(data, dict):
        return
    usage = data.get("usage") or data.get("usageMetadata") or {}
    if not isinstance(usage, dict):
        usage = {}
    # Preserve the provider's accounting names; missing reasoning usage is
    # unknown, not zero. Do not include prompts, answers, URLs or credentials.
    counts = {key: value for key, value in usage.items()
              if isinstance(value, (int, float)) and not isinstance(value, bool)
              and ("token" in key.lower() or key.lower().endswith("count"))}
    for key in ("completion_tokens_details", "output_tokens_details"):
        details = usage.get(key)
        if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
            counts["reasoning_tokens"] = details["reasoning_tokens"]
    choices = data.get("choices") or data.get("candidates") or []
    first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    meta.setdefault("modelCalls", []).append({
        "elapsedMs": round((time.monotonic() - started_at) * 1000),
        "maxTokens": meta.get("maxTokens"),
        "reasoningParameters": meta.get("reasoningParameters", {}),
        "usage": counts,
        "finishReason": data.get("stop_reason") or first.get("finish_reason") or first.get("finishReason") or data.get("status"),
    })


def _extract_response_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict) and item.get("text")
            ]
            return "\n".join(parts).strip()
    output = data.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text") or part.get("output_text")
                    if text:
                        parts.append(str(text))
        return "\n".join(parts).strip()
    return ""


def _extract_anthropic_response_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    content = data.get("content")
    if not isinstance(content, list):
        return ""
    parts = [
        str(item.get("text") or "")
        for item in content
        if isinstance(item, dict) and item.get("text")
    ]
    return "\n".join(parts).strip()


def _extract_gemini_response_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return ""
    text_parts = [
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict) and part.get("text") and not part.get("thought")
    ]
    return "\n".join(text_parts).strip()


def _post_json(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    *,
    timeout: int = MODEL_TEXT_REQUEST_TIMEOUT_SECONDS,
    on_response_received: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        _notify_response_received(on_response_received, _response_json_for_log(detail))
        raise RuntimeError(f"模型请求失败 HTTP {exc.code}: {detail[:2000]}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError(f"模型请求超时（{timeout} 秒）") from exc
    except urllib.error.URLError as exc:
        if _is_text_request_timeout(exc):
            raise RuntimeError(f"模型请求超时（{timeout} 秒）") from exc
        raise
    try:
        document = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        _notify_response_received(on_response_received, _response_json_for_log(raw))
        raise
    _notify_response_received(on_response_received, document)
    return document


def _is_text_request_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, BaseException) and reason is not exc:
        return _is_text_request_timeout(reason)
    text = str(exc or "").strip().lower()
    return "timed out" in text or "timeout" in text or "请求超时" in text


def _call_openai_compatible_text_model(
    provider: dict[str, Any],
    provider_id: str,
    base_url: str,
    model_name: str,
    prompt: str,
    *,
    system_prompt: str = "",
    temperature: float = 0.4,
    max_tokens: int = 4096,
    input_images: list[str] | None = None,
    structured_schema: dict[str, Any] | None = None,
    endpoint: str | None = None,
    native_structured_endpoint: str | None = None,
    reasoning_task: str = "",
    on_request_prepared: Callable[[dict[str, Any]], None] | None = None,
    on_response_received: Callable[[Any], None] | None = None,
) -> str:
    generation_base_url = _openai_compatible_generation_base_url(
        provider,
        provider_id,
        base_url,
    )
    normalized_endpoint = normalize_media_endpoint(endpoint)
    if normalized_endpoint == "openai-responses":
        use_responses = True
    elif normalized_endpoint == "openai-chat":
        use_responses = False
    else:
        use_responses = provider_id == "openai" and re.search(r"(^|[-_:/])gpt[-_]?5", model_name, re.I)
    native_structured_endpoint = (
        normalize_media_endpoint(native_structured_endpoint)
        if structured_schema
        else ""
    )
    if structured_schema and not native_structured_endpoint:
        native_structured_endpoint = _provider_native_structured_endpoint(provider)
    if native_structured_endpoint == "openai-responses":
        use_responses = True
    elif native_structured_endpoint == "openai-chat":
        use_responses = False
    api_key = str(provider.get("api_key") or provider.get("apiKey") or "").strip()
    image_inputs = [item for item in (input_images or []) if str(item).startswith("data:image/")]
    if use_responses:
        input_messages = []
        if image_inputs:
            input_messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        *(
                            {"type": "input_image", "image_url": data_url}
                            for data_url in image_inputs
                        ),
                    ],
                }
            )
        else:
            input_messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model_name,
            "input": input_messages,
            "max_output_tokens": max_tokens,
        }
        if system_prompt:
            payload["instructions"] = system_prompt
        response_format = _structured_response_format(structured_schema, api="responses")
        if response_format:
            payload["text"] = {"format": response_format}
        url = f"{generation_base_url}/responses"
        apply_model_reasoning(
            payload, base_url=generation_base_url, model=model_name,
            endpoint="openai-responses", task=reasoning_task,
        )
        _notify_text_request_prepared(
            on_request_prepared,
            {
                "provider": provider_id or _provider_adapter_id(provider) or "openai-compatible",
                "transport": "http",
                "method": "POST",
                "url": url,
                "requestBody": payload,
            },
        )
        data = _post_json(
            url,
            payload,
            api_key,
            timeout=MODEL_TEXT_REQUEST_TIMEOUT_SECONDS,
            on_response_received=on_response_received,
        )
    else:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if image_inputs:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        *(
                            {"type": "image_url", "image_url": {"url": data_url}}
                            for data_url in image_inputs
                        ),
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response_format = _structured_response_format(structured_schema, api="chat")
        if response_format:
            payload["response_format"] = response_format
        url = f"{generation_base_url}/chat/completions"
        apply_model_reasoning(
            payload, base_url=generation_base_url, model=model_name,
            endpoint="openai-chat", task=reasoning_task,
        )
        _notify_text_request_prepared(
            on_request_prepared,
            {
                "provider": provider_id or _provider_adapter_id(provider) or "openai-compatible",
                "transport": "http",
                "method": "POST",
                "url": url,
                "requestBody": payload,
            },
        )
        data = _post_json(
            url,
            payload,
            api_key,
            timeout=MODEL_TEXT_REQUEST_TIMEOUT_SECONDS,
            on_response_received=on_response_received,
        )
    _raise_for_text_output_limit(data)
    return _extract_response_text(data)


def _call_anthropic_text_model(
    provider: dict[str, Any],
    base_url: str,
    model_name: str,
    prompt: str,
    *,
    system_prompt: str = "",
    temperature: float = 0.4,
    max_tokens: int = 4096,
    input_images: list[str] | None = None,
    structured_schema: dict[str, Any] | None = None,
    reasoning_task: str = "",
    on_request_prepared: Callable[[dict[str, Any]], None] | None = None,
    on_response_received: Callable[[Any], None] | None = None,
) -> str:
    from utils.text_model_contracts import anthropic_sampling_parameters

    content: list[dict[str, Any]] | str
    image_inputs = [item for item in (input_images or []) if str(item).startswith("data:image/")]
    if image_inputs:
        content = [{"type": "text", "text": prompt}]
        for data_url in image_inputs:
            image_data, mime = _data_url_base64_payload(data_url)
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": image_data,
                    },
                }
            )
    else:
        content = prompt
    api_key = str(provider.get("api_key") or provider.get("apiKey") or "").strip()
    payload: dict[str, Any] = {
        "model": model_name,
        "max_tokens": max_tokens,
        **anthropic_sampling_parameters(model_name, temperature),
        "messages": [{"role": "user", "content": content}],
    }
    if system_prompt:
        payload["system"] = system_prompt
    response_format = _structured_response_format(structured_schema, api="anthropic-messages")
    if response_format:
        payload["output_config"] = response_format
    url = _anthropic_messages_url(base_url)
    apply_model_reasoning(
        payload, base_url=base_url, model=model_name,
        endpoint="anthropic-messages", task=reasoning_task,
    )
    _notify_text_request_prepared(
        on_request_prepared,
        {
            "provider": _provider_service_id(provider) or _provider_adapter_id(provider) or "anthropic-compatible",
            "transport": "http",
            "method": "POST",
            "url": url,
            "requestBody": payload,
        },
    )
    data = _request_json(
        "POST",
        url,
        headers=_anthropic_messages_auth_headers(provider, api_key, base_url),
        data=payload,
        timeout=MODEL_TEXT_REQUEST_TIMEOUT_SECONDS,
        on_response_received=on_response_received,
    )
    _raise_for_text_output_limit(data)
    return _extract_anthropic_response_text(data)


def _call_gemini_text_model(
    base_url: str,
    model_name: str,
    prompt: str,
    api_key: str,
    *,
    reasoning_task: str = "",
    system_prompt: str = "",
    temperature: float = 0.4,
    max_tokens: int = 4096,
    input_images: list[str] | None = None,
    structured_schema: dict[str, Any] | None = None,
    on_request_prepared: Callable[[dict[str, Any]], None] | None = None,
    on_response_received: Callable[[Any], None] | None = None,
) -> str:
    root = _google_discovery_root_url(base_url or _provider_default_base_url("gemini"))
    model_resource = model_name if model_name.startswith("models/") else f"models/{model_name}"
    url = f"{root}/v1beta/{model_resource}:generateContent"
    parts = []
    if system_prompt:
        parts.append({"text": system_prompt})
    parts.append({"text": prompt})
    for data_url in input_images or []:
        if not str(data_url).startswith("data:image/"):
            continue
        image_data, mime = _data_url_base64_payload(data_url)
        parts.append(
            {
                "inlineData": {
                    "mimeType": mime,
                    "data": image_data,
                }
            }
        )
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    apply_model_reasoning(payload, base_url=root, model=model_name,
                          endpoint="gemini-generate", task=reasoning_task)
    response_format = _structured_response_format(structured_schema, api="gemini-generate")
    if response_format:
        payload["generationConfig"].update(response_format)
    _notify_text_request_prepared(
        on_request_prepared,
        {
            "provider": "gemini",
            "transport": "http",
            "method": "POST",
            "url": url,
            "requestBody": payload,
        },
    )
    data = _request_json(
        "POST",
        url,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        data=payload,
        timeout=MODEL_TEXT_REQUEST_TIMEOUT_SECONDS,
        on_response_received=on_response_received,
    )
    _raise_for_text_output_limit(data)
    return _extract_gemini_response_text(data)


def _call_text_model(
    provider: dict[str, Any],
    model: dict[str, Any],
    prompt: str,
    *,
    system_prompt: str = "",
    temperature: float = 0.4,
    max_tokens: int = 4096,
    input_images: list[str] | None = None,
    structured_schema: dict[str, Any] | None = None,
    reasoning_task: str = "",
    on_request_prepared: Callable[[dict[str, Any]], None] | None = None,
    on_response_received: Callable[[Any], None] | None = None,
) -> str:
    api_key = str(provider.get("api_key") or provider.get("apiKey") or "").strip()
    if not api_key:
        raise RuntimeError(f"{provider.get('key_label') or provider.get('keyLabel') or 'API_KEY'} 为空")
    base_url = _provider_base_url(provider)
    if not base_url:
        raise RuntimeError("供应商 Base URL 为空")
    model_name = _api_model_name(model.get("id"))
    provider_id = _provider_service_id(provider)
    native_structured_schema = (
        structured_schema
        if structured_schema and _provider_supports_native_structured_output(provider, model)
        else None
    )
    native_structured_endpoint = (
        _provider_native_structured_endpoint(provider, model)
        if native_structured_schema
        else ""
    )
    endpoint = _text_model_generation_endpoint(provider, model)
    input_images = _provider_model_input_images(
        input_images,
        purpose="text-model-input",
        image_input_limits=_model_reference_image_input_limits(model),
    )
    if endpoint == "gemini-generate":
        text = _call_gemini_text_model(
            base_url,
            model_name,
            prompt,
            api_key,
            reasoning_task=reasoning_task,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            input_images=input_images,
            structured_schema=native_structured_schema,
            on_request_prepared=on_request_prepared,
            on_response_received=on_response_received,
        )
    elif endpoint == "anthropic-messages":
        text = _call_anthropic_text_model(
            provider,
            base_url,
            model_name,
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            input_images=input_images,
            structured_schema=native_structured_schema,
            reasoning_task=reasoning_task,
            on_request_prepared=on_request_prepared,
            on_response_received=on_response_received,
        )
    else:
        text = _call_openai_compatible_text_model(
            provider,
            provider_id,
            base_url,
            model_name,
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            input_images=input_images,
            structured_schema=native_structured_schema,
            endpoint=endpoint,
            native_structured_endpoint=native_structured_endpoint,
            reasoning_task=reasoning_task,
            on_request_prepared=on_request_prepared,
            on_response_received=on_response_received,
        )
    if not text:
        raise RuntimeError("模型未返回可用文本")
    return text.strip()


def _extract_json_payload(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1).strip()
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _attached_model_input_images(project_id: str, images: list[dict[str, Any]] | None) -> list[str]:
    rows: list[str] = []
    total_bytes = 0
    for index, item in enumerate(images or []):
        if not isinstance(item, dict):
            raise RuntimeError(
                f"第 {index + 1} 张模型输入图片不是有效图片对象；"
                "已阻断模型请求，不能跳过缺失参考图后继续生成。"
            )
        data_url = _provider_image_data_url_from_file_info(
            project_id,
            item,
            purpose=f"agent-chat-image-{index + 1}",
        )
        if not (isinstance(data_url, str) and data_url.startswith("data:image/")):
            raise RuntimeError(
                f"第 {index + 1} 张模型输入图片无法解析为可发送的图片数据；"
                "已阻断模型请求，不能跳过缺失参考图后继续生成。"
            )
        try:
            raw, _mime = _decode_data_url(data_url)
        except Exception as exc:
            raise RuntimeError(
                f"第 {index + 1} 张模型输入图片数据解析失败；"
                "已阻断模型请求，不能跳过缺失参考图后继续生成。"
            ) from exc
        if len(raw) > AGENT_ATTACHMENT_MAX_BYTES:
            raise RuntimeError(
                f"第 {index + 1} 张模型输入图片超过单张上限 {AGENT_ATTACHMENT_MAX_BYTES} 字节；"
                "已阻断模型请求，不能压缩剪切或跳过参考图后继续生成。"
            )
        if total_bytes + len(raw) > AGENT_MODEL_IMAGE_INPUT_MAX_BYTES:
            raise RuntimeError(
                f"模型输入图片总大小超过上限 {AGENT_MODEL_IMAGE_INPUT_MAX_BYTES} 字节；"
                "已阻断模型请求，不能压缩剪切或跳过参考图后继续生成。"
            )
        rows.append(data_url)
        total_bytes += len(raw)
    return rows


@_serialized_global_config_write
def _persist_native_structured_model_result(
    provider: dict[str, Any],
    model: dict[str, Any],
    result: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    provider_id = _normalize_provider_id(provider.get("id"))
    updated_provider = _provider_with_native_structured_model_result(
        provider,
        model,
        result,
        source=source,
    )
    if not provider_id:
        return updated_provider
    try:
        config = load_global_config()
        rows = config.get("providers", [])
        current = next((row for row in rows if _normalize_provider_id(row.get("id")) == provider_id), None)
        if current is None or any((
            current.get("api_key") != provider.get("api_key"),
            _provider_base_url(current) != _provider_base_url(provider),
            _provider_adapter_id(current) != _provider_adapter_id(provider),
            _provider_service_id(current) != _provider_service_id(provider),
            current.get("capabilities") != provider.get("capabilities"),
            current.get("models") != provider.get("models"),
        )):
            return updated_provider
        updated_provider = _provider_with_native_structured_model_result(
            current, model, result, source=source,
        )
        config["providers"] = [updated_provider if row is current else row for row in rows]
        saved = _save_global_config(config)
        for row in saved.get("providers", []):
            if _normalize_provider_id(row.get("id")) == provider_id:
                return row
    except Exception:
        return updated_provider
    return updated_provider


def _ensure_native_structured_model_checked(
    provider: dict[str, Any],
    model: dict[str, Any],
    meta: dict[str, Any] | None = None,
    *,
    check_cancelled: Callable[[], None] | None = None,
    on_probe_exchange: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    if check_cancelled:
        check_cancelled()
    # The result is global per provider/model/endpoint. Cache unknown as well:
    # a failed or inconclusive probe must not be repeated for every project.
    cached_record = _provider_native_structured_model_record(provider, model)
    current_endpoint = _text_model_generation_endpoint(provider, model)
    cached_endpoint = normalize_media_endpoint(
        cached_record.get("probeEndpoint")
    ) if isinstance(cached_record, dict) else ""
    if isinstance(cached_record, dict) and (
        not cached_endpoint or cached_endpoint == current_endpoint
    ):
        status = _provider_native_structured_status(provider, model)
        # ``unknown`` means the request was inconclusive (timeout, quota,
        # gateway error, or another transport problem), not that the model
        # lacks structured output.  Keep the record for diagnostics, but let
        # the next real model use retry the probe instead of freezing that
        # transient result forever.
        if status in {"supported", "unsupported"}:
            if meta is not None:
                meta["nativeStructuredCapability"] = status
            return provider
    status = _provider_native_structured_status(provider, model)
    if status in {"supported", "unsupported"}:
        if meta is not None:
            meta["nativeStructuredCapability"] = status
        return provider
    try:
        options = {"check_cancelled": check_cancelled}
        if on_probe_exchange is not None:
            options["on_exchange"] = on_probe_exchange
        result = _run_native_json_schema_probe(provider, model, **options)
    except GenerationCancelled:
        raise
    except Exception as exc:
        if check_cancelled:
            check_cancelled()
        result = {
            "name": _NATIVE_JSON_SCHEMA_PROBE_NAME,
            "status": "unknown",
            "error": str(exc),
            "model": _structured_model_api_name(model),
        }
    if check_cancelled:
        check_cancelled()
    updated_provider = _persist_native_structured_model_result(
        provider,
        model,
        result,
        source="runtime_probe",
    )
    if meta is not None:
        meta["nativeStructuredCapability"] = _provider_native_structured_status(updated_provider, model)
        meta["nativeStructuredProbe"] = {
            "status": result.get("status") or "",
            "model": result.get("model") or _structured_model_api_name(model),
            **({"endpoint": result.get("endpoint")} if result.get("endpoint") else {}),
            **({"error": result.get("error")} if result.get("error") else {}),
        }
    return updated_provider


def _model_json_or_none(
    project_id: str,
    model_section: str,
    model_key: str,
    prompt: str,
    *,
    system_prompt: str,
    temperature: float = 0.4,
    max_tokens: int = 4096,
    images: list[dict[str, Any]] | None = None,
    structured_schema: dict[str, Any] | None = None,
    model_request_log_stage: str = "",
    model_request_log_context: dict[str, Any] | None = None,
    task_id: str | None = None,
    reasoning_task: str = "",
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    # Provider-agnostic structured text entry; pass structured_schema to add prompt contract and local validation.
    check_cancelled = lambda: _check_generation_task_cancelled(task_id)
    check_cancelled()
    provider, model, _model_config = _configured_text_model(project_id, model_section, model_key)
    meta = {
        "source": "fallback",
        "modelId": model.get("id") if model else "",
        "modelLabel": model.get("label") if model else "",
        "providerId": model.get("provider_id") if model else "",
        "error": "",
    }
    if isinstance(structured_schema, dict):
        meta["structuredSchema"] = structured_schema.get("name") or ""
    if not provider or not model or not _is_connected_provider(provider):
        meta["error"] = "文本模型供应商未连接"
        return None, meta
    model_label = "智能体模型" if model_section == "agent" else "文本模型"
    if images and not _model_supports_vision_input(model):
        raise RuntimeError(
            f"当前{model_label}不支持图片输入；已阻断模型请求，不能忽略参考图后继续生成。"
        )
    input_images = _attached_model_input_images(project_id, images)
    if structured_schema:
        from .model_request_logs import create_model_exchange_logger

        provider = _ensure_native_structured_model_checked(
            provider,
            model,
            meta,
            check_cancelled=check_cancelled,
            on_probe_exchange=create_model_exchange_logger(project_id, source="native-schema-probe", stage_prefix="model"),
        )
    meta["providerInstanceId"] = provider.get("id") or ""
    meta["adapterId"] = _provider_adapter_id(provider)
    native_schema = (
        structured_schema
        if structured_schema and _provider_supports_native_structured_output(provider, model)
        else None
    )
    attempts = 2 if structured_schema else 1
    last_error = ""
    last_text = ""
    errors: list[str] = []
    request_errors: list[str] = []
    if structured_schema:
        meta["structuredMode"] = "native_json_schema" if native_schema else "non_strict_validated"
    for attempt_index in range(attempts):
        check_cancelled()
        repair_attempt = attempt_index > 0
        attempt_text = ""
        attempt_native_schema = native_schema if attempt_index == 0 else None
        attempt_prompt = (
            _structured_repair_prompt(
                prompt,
                structured_schema,
                raw_text=last_text,
                error=last_error,
            )
            if repair_attempt
            else _structured_prompt(prompt, structured_schema)
        )
        try:
            log_context = model_request_log_context if isinstance(model_request_log_context, dict) else {}
            log_phase = str(log_context.get("phase") or ("repair" if repair_attempt else "initial"))
            model_call_id = uuid.uuid4().hex[:12]
            model_call_started_at = time.monotonic()

            def log_text_request(request_info: dict[str, Any]) -> None:
                _record_text_output_budget(meta, request_info, max_tokens)
                if not model_request_log_stage:
                    return
                request_info = {**request_info, "requestId": model_call_id,
                                "requestPurpose": "repair" if repair_attempt else (reasoning_task or model_request_log_stage)}
                result = write_model_request_log(
                    project_id,
                    model_request_log_stage,
                    request_info,
                    episode_id=str(log_context.get("episodeId") or log_context.get("episode_id") or ""),
                    node_id=str(log_context.get("nodeId") or log_context.get("node_id") or ""),
                    task_id=str(log_context.get("taskId") or log_context.get("task_id") or ""),
                    phase=log_phase,
                    provider_id=str(meta.get("providerId") or ""),
                    model_name=str(meta.get("modelId") or ""),
                    endpoint=str(log_context.get("endpoint") or ""),
                    source=str(log_context.get("source") or "_model_json_or_none"),
                    call_id=model_call_id,
                )
                if result.get("success"):
                    meta.setdefault("modelRequestLogs", []).append(
                        model_request_log_reference(
                            result,
                            phase=log_phase,
                        )
                    )
                else:
                    meta.setdefault("modelRequestLogErrors", []).append(
                        {
                            "stage": model_request_log_stage,
                            "phase": log_phase,
                            "error": str(result.get("error") or "日志写入失败"),
                        }
                    )

            def log_text_response(response_data: Any) -> None:
                _record_text_response_metrics(meta, response_data, model_call_started_at)
                if not model_request_log_stage:
                    return
                result = write_model_response_log(
                    project_id,
                    model_request_log_stage,
                    response_data,
                    episode_id=str(log_context.get("episodeId") or log_context.get("episode_id") or ""),
                    node_id=str(log_context.get("nodeId") or log_context.get("node_id") or ""),
                    task_id=str(log_context.get("taskId") or log_context.get("task_id") or ""),
                    phase=log_phase,
                    provider_id=str(meta.get("providerId") or ""),
                    model_name=str(meta.get("modelId") or ""),
                    endpoint=str(log_context.get("endpoint") or ""),
                    source=str(log_context.get("source") or "_model_json_or_none"),
                    call_id=model_call_id,
                )
                if result.get("success"):
                    meta.setdefault("modelResponseLogs", []).append(
                        model_response_log_reference(result, phase=log_phase)
                    )
                else:
                    meta.setdefault("modelResponseLogErrors", []).append(
                        {
                            "stage": model_request_log_stage,
                            "phase": log_phase,
                            "error": str(result.get("error") or "响应日志写入失败"),
                        }
                    )

            text = run_cancellable_model_request(
                lambda: _call_text_model(
                    provider,
                    model,
                    attempt_prompt,
                    system_prompt=_structured_system_prompt(system_prompt, structured_schema),
                    temperature=temperature,
                    max_tokens=max_tokens,
                    input_images=input_images,
                    structured_schema=attempt_native_schema,
                    reasoning_task=reasoning_task or model_request_log_stage,
                    on_request_prepared=log_text_request,
                    on_response_received=log_text_response,
                ),
                check_cancelled,
            )
            attempt_text = text
            last_text = text
            data = _extract_json_payload(text)
            if not data:
                raise RuntimeError("模型返回内容不是可解析 JSON")
            raw_data = data
            if structured_schema:
                data, validation_errors = _normalize_structured_payload(data, structured_schema)
                if validation_errors:
                    meta["validationErrors"] = validation_errors
                    meta["rawData"] = raw_data
                    raise RuntimeError("；".join(validation_errors))
            meta["source"] = "model"
            meta["rawText"] = text[:4000]
            meta["temperature"] = temperature
            meta.setdefault("maxTokens", max_tokens)
            meta["inputImageCount"] = len(input_images)
            if attempt_native_schema:
                meta["structuredMode"] = "native_json_schema"
            elif repair_attempt:
                meta["structuredMode"] = "non_strict_validated_repair"
            elif structured_schema:
                meta["structuredMode"] = "non_strict_validated"
            if errors:
                meta["repairErrors"] = errors
                meta["repairAttempts"] = len(errors)
            if structured_schema:
                meta["normalized"] = True
            if model_section == "agent":
                meta["runtimePolicy"] = "ai_video_agent_task_default"
            return data, meta
        except GenerationCancelled:
            raise
        except TextOutputLimitError as exc:
            check_cancelled()
            last_error = str(exc)
            meta.setdefault("maxTokens", max_tokens)
            request_errors.append(last_error)
            break
        except Exception as exc:
            check_cancelled()
            last_error = str(exc)
            timed_out = _is_text_request_timeout(exc)
            if attempt_native_schema and not timed_out:
                provider = _persist_native_structured_model_result(
                    provider,
                    model,
                    {
                        "name": _NATIVE_JSON_SCHEMA_PROBE_NAME,
                        "status": "unsupported",
                        "model": _structured_model_api_name(model),
                        "endpoint": _provider_native_structured_endpoint(provider, model),
                        "error": last_error,
                    },
                    source="generation_failure",
                )
                meta["nativeStructuredOutput"] = "unsupported"
                meta["structuredMode"] = "native_json_schema_failed_fallback"
            should_retry = (
                bool(structured_schema)
                and attempt_index < attempts - 1
                and (
                    bool(attempt_text)
                    or bool(attempt_native_schema and not timed_out)
                )
            )
            if should_retry:
                errors.append(last_error)
            else:
                request_errors.append(last_error)
                break
    meta["error"] = last_error
    if last_text:
        meta["rawText"] = last_text[:4000]
    if errors:
        meta["repairErrors"] = errors
        meta["repairAttempts"] = len(errors)
    if request_errors:
        meta["requestErrors"] = request_errors
    return None, meta


def _model_text_or_none(
    project_id: str,
    model_section: str,
    model_key: str,
    prompt: str,
    *,
    system_prompt: str,
    temperature: float = 0.4,
    max_tokens: int = 4096,
    images: list[dict[str, Any]] | None = None,
    model_request_log_stage: str = "",
    model_request_log_context: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    check_cancelled = lambda: _check_generation_task_cancelled(task_id)
    check_cancelled()
    provider, model, _model_config = _configured_text_model(project_id, model_section, model_key)
    meta = {
        "source": "fallback",
        "modelId": model.get("id") if model else "",
        "modelLabel": model.get("label") if model else "",
        "providerId": model.get("provider_id") if model else "",
        "error": "",
    }
    if not provider or not model or not _is_connected_provider(provider):
        meta["error"] = "文本模型供应商未连接"
        return "", meta
    model_label = "智能体模型" if model_section == "agent" else "文本模型"
    if images and not _model_supports_vision_input(model):
        raise RuntimeError(
            f"当前{model_label}不支持图片输入；已阻断模型请求，不能忽略参考图后继续生成。"
        )
    input_images = _attached_model_input_images(project_id, images)
    try:
        log_context = model_request_log_context if isinstance(model_request_log_context, dict) else {}
        log_phase = str(log_context.get("phase") or "initial")
        model_call_id = uuid.uuid4().hex[:12]
        model_call_started_at = time.monotonic()

        def log_text_request(request_info: dict[str, Any]) -> None:
            _record_text_output_budget(meta, request_info, max_tokens)
            if not model_request_log_stage:
                return
            result = write_model_request_log(
                project_id,
                model_request_log_stage,
                request_info,
                episode_id=str(log_context.get("episodeId") or log_context.get("episode_id") or ""),
                node_id=str(log_context.get("nodeId") or log_context.get("node_id") or ""),
                task_id=str(log_context.get("taskId") or log_context.get("task_id") or ""),
                phase=log_phase,
                provider_id=str(meta.get("providerId") or ""),
                model_name=str(meta.get("modelId") or ""),
                endpoint=str(log_context.get("endpoint") or ""),
                source=str(log_context.get("source") or "_model_text_or_none"),
                call_id=model_call_id,
            )
            if result.get("success"):
                meta.setdefault("modelRequestLogs", []).append(
                    model_request_log_reference(
                        result,
                        phase=log_phase,
                    )
                )
            else:
                meta.setdefault("modelRequestLogErrors", []).append(
                    {
                        "stage": model_request_log_stage,
                        "phase": log_phase,
                        "error": str(result.get("error") or "日志写入失败"),
                    }
                )

        def log_text_response(response_data: Any) -> None:
            _record_text_response_metrics(meta, response_data, model_call_started_at)
            if not model_request_log_stage:
                return
            result = write_model_response_log(
                project_id,
                model_request_log_stage,
                response_data,
                episode_id=str(log_context.get("episodeId") or log_context.get("episode_id") or ""),
                node_id=str(log_context.get("nodeId") or log_context.get("node_id") or ""),
                task_id=str(log_context.get("taskId") or log_context.get("task_id") or ""),
                phase=log_phase,
                provider_id=str(meta.get("providerId") or ""),
                model_name=str(meta.get("modelId") or ""),
                endpoint=str(log_context.get("endpoint") or ""),
                source=str(log_context.get("source") or "_model_text_or_none"),
                call_id=model_call_id,
            )
            if result.get("success"):
                meta.setdefault("modelResponseLogs", []).append(
                    model_response_log_reference(result, phase=log_phase)
                )
            else:
                meta.setdefault("modelResponseLogErrors", []).append(
                    {
                        "stage": model_request_log_stage,
                        "phase": log_phase,
                        "error": str(result.get("error") or "响应日志写入失败"),
                    }
                )

        text = run_cancellable_model_request(
            lambda: _call_text_model(
                provider,
                model,
                prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                input_images=input_images,
                reasoning_task=model_request_log_stage,
                on_request_prepared=log_text_request,
                on_response_received=log_text_response,
            ),
            check_cancelled,
        )
        meta["source"] = "model"
        meta["rawText"] = text[:4000]
        meta["temperature"] = temperature
        meta.setdefault("maxTokens", max_tokens)
        meta["inputImageCount"] = len(input_images)
        return text.strip(), meta
    except GenerationCancelled:
        raise
    except Exception as exc:
        check_cancelled()
        meta["error"] = str(exc)
        return "", meta
