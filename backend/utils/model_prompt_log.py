# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_DATA_URL_RE = re.compile(r"^data:([^;,]+)(?:;[^,]*)?,", re.IGNORECASE)
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\r\n]+$")
_INLINE_MEDIA_KEY_PARTS = (
    "image",
    "video",
    "audio",
    "media",
    "file",
    "files",
    "reference",
)
CAPTURE_METADATA_FIELDS = (
    "captureLevel", "captureSource", "requestPurpose", "requestId", "parentRequestId",
    "executed", "dryRun", "applicationTools",
)
# Keep provenance level and tool definitions in equivalence checks, while a
# per-call ID or execution status cannot change the model's input contents.
NON_INPUT_CAPTURE_FIELDS = frozenset({
    "requestId", "parentRequestId", "captureSource", "requestPurpose", "executed", "dryRun",
})
_AUTH_FIELDS = {"headers", "authorization", "api_key", "apikey", "api-key", "x-api-key",
                "x-goog-api-key", "access_token", "token", "key"}


def _is_inline_media_key(path: tuple[str, ...]) -> bool:
    key_text = ".".join(str(item or "") for item in path).casefold()
    return any(part in key_text for part in _INLINE_MEDIA_KEY_PARTS)


def _redacted_media(value: str, *, kind: str, media_type: str = "") -> dict[str, Any]:
    return {
        "redacted": True,
        "redactionReason": kind,
        "mediaType": media_type,
        "chars": len(value),
    }


def sanitize_for_prompt_log(value: Any, *, path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, bytes):
        return {
            "redacted": True,
            "redactionReason": "bytes_media_or_binary",
            "byteLength": len(value),
        }
    if isinstance(value, bytearray):
        return {
            "redacted": True,
            "redactionReason": "bytearray_media_or_binary",
            "byteLength": len(value),
        }
    if isinstance(value, str):
        data_url = _DATA_URL_RE.match(value.strip())
        if data_url:
            return _redacted_media(value, kind="inline_data_url", media_type=data_url.group(1))
        if _is_inline_media_key(path) and len(value) > 4096 and _BASE64_RE.fullmatch(value.strip()):
            return _redacted_media(value, kind="inline_base64_media")
        return value
    if isinstance(value, dict):
        return {
            str(key): sanitize_for_prompt_log(item, path=(*path, str(key)))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            sanitize_for_prompt_log(item, path=(*path, str(index)))
            for index, item in enumerate(value)
        ]
    if isinstance(value, tuple):
        return [
            sanitize_for_prompt_log(item, path=(*path, str(index)))
            for index, item in enumerate(value)
        ]
    return copy.deepcopy(value)


def _first_dict(value: Any, *keys: str) -> dict[str, Any]:
    for key in keys:
        item = value.get(key) if isinstance(value, dict) else None
        if isinstance(item, dict):
            return item
    return {}


def _request_data_from_log(value: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value.get("effectiveModelInput"), dict):
        return copy.deepcopy(value["effectiveModelInput"])
    for key in ("requestData", "requestInfo", "request", "providerRequest"):
        item = value.get(key)
        if isinstance(item, dict):
            return copy.deepcopy(item)
    if isinstance(value.get("requestBody"), dict):
        return copy.deepcopy(value)
    return copy.deepcopy(value)


def _compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if item in (None, "", [], {}):
            continue
        result[key] = item
    return result


def extract_effective_model_input(log_or_request: dict[str, Any]) -> dict[str, Any]:
    source = log_or_request if isinstance(log_or_request, dict) else {}
    if source.get("promptOnly"):
        return _compact_dict(
            {
                "provider": source.get("provider") or source.get("providerId"),
                "model": source.get("model") or source.get("modelName"),
                "endpoint": source.get("endpoint"),
                "promptOnly": True,
                "finalPrompt": source.get("finalPrompt") or "",
                "mediaOmitted": bool(source.get("mediaOmitted")),
            }
        )

    request_data = _request_data_from_log(source)
    request_body = _first_dict(request_data, "requestBody", "body", "payload")
    if not request_body and isinstance(request_data, dict):
        request_body = {
            key: value
            for key, value in request_data.items()
            if key
            not in {
                "provider",
                "transport",
                "method",
                "url",
                "headers",
                "authorization",
                "apiKey",
                "api_key",
                "note",
                *CAPTURE_METADATA_FIELDS,
            }
        }

    effective = {
        "provider": request_data.get("provider") or source.get("provider") or source.get("providerId"),
        "transport": request_data.get("transport"),
        "method": request_data.get("method"),
        "url": request_data.get("url") or source.get("endpoint"),
        "requestBody": sanitize_for_prompt_log(request_body),
    }
    if isinstance(effective["url"], str):
        parts = urlsplit(effective["url"])
        query = urlencode([(key, "<redacted>" if key.casefold() in _AUTH_FIELDS else item)
                           for key, item in parse_qsl(parts.query, keep_blank_values=True)])
        effective["url"] = urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, query, parts.fragment))
    effective["requestBody"] = {key: item for key, item in effective["requestBody"].items()
                                if key.casefold() not in _AUTH_FIELDS}
    options = effective["requestBody"].get("options")
    if isinstance(options, dict) and isinstance(options.get("env"), dict):
        options["env"] = {key: item if isinstance(item, dict) and item.get("redacted") is True
                          else {"redacted": True} for key, item in options["env"].items()}
    for key in CAPTURE_METADATA_FIELDS:
        if key in request_data or key in source:
            effective[key] = sanitize_for_prompt_log(request_data.get(key, source.get(key)))
    return _compact_dict(effective)


def canonical_json(value: Any) -> str:
    return json.dumps(
        sanitize_for_prompt_log(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def fingerprint(value: Any) -> str:
    if isinstance(value, dict) and "requestBody" in value:
        value = {key: item for key, item in value.items() if key not in NON_INPUT_CAPTURE_FIELDS}
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def build_prompt_request_log(
    *,
    role: str,
    stage: str,
    step: str,
    request_info: dict[str, Any] | None,
    system_prompt: str = "",
    prompt: str = "",
    messages: list[dict[str, Any]] | None = None,
    structured_schema: dict[str, Any] | None = None,
    template: dict[str, Any] | None = None,
    variable_inputs: dict[str, Any] | None = None,
    media_inputs: list[dict[str, Any]] | None = None,
    excluded_context_types: list[str] | tuple[str, ...] | None = None,
    source: dict[str, Any] | None = None,
) -> Any:
    clean_request_info = sanitize_for_prompt_log(request_info or {})
    if not clean_request_info:
        return None
    effective_input = extract_effective_model_input({"requestInfo": clean_request_info})
    return effective_input


def write_prompt_request_log(path: str | Path, **kwargs: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(build_prompt_request_log(**kwargs), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8", newline="\n",
    )
    return target
