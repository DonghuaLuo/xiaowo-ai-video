# -*- coding: utf-8 -*-
"""项目列表、仪表盘、创建选项和全局设置。"""

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

from .canvas_store_queries import read_episode_card_results

from .catalogs import ACCENTS
from .catalogs import DEFAULT_GLOBAL_CONFIG
from .catalogs import DEFAULT_STYLE_TEMPLATES
from .catalogs import FAVORITE_STYLE_THUMBNAILS_DIR
from .catalogs import GLOBAL_CONFIG_PATH
from .catalogs import GLOBAL_DIR
from .catalogs import IMAGE_EXTENSIONS
from .catalogs import PROJECTS_DIR
from .catalogs import STYLE_CATEGORY_META
from .catalogs import STYLE_THUMBNAILS_DIR
from .catalogs import _ensure_prompt_sentence_end
from .store_core import _asset_is_offline
from .store_core import _merge_model_capabilities
from .store_core import _merge_provider_presets
from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json
from .store_core import ensure_store

CURRENT_PROJECT_STATE_PATH = GLOBAL_DIR / "current_project.json"
CURRENT_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


from .store_core import _display_time

def _normalize_project_id(value: str | None, *, max_length: int = 64) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().casefold())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("._-")
    return normalized[:max_length].strip("._-")


def _validate_current_project_id(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if (
        normalized in {".", ".."}
        or not CURRENT_PROJECT_ID_PATTERN.fullmatch(normalized)
    ):
        raise ValueError("项目 ID 无效")
    project_root = (PROJECTS_DIR / normalized).resolve()
    projects_root = PROJECTS_DIR.resolve()
    if project_root == projects_root:
        raise ValueError("项目 ID 无效")
    try:
        project_root.relative_to(projects_root)
    except ValueError:
        raise ValueError("项目 ID 无效") from None
    return normalized


def _write_current_project_cleared_state(
    *,
    reason: str = "",
    invalid_project_id: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "projectId": None,
        "projectTitle": "",
        "cleared": True,
        "savedAt": _now(),
    }
    if reason:
        payload["reason"] = reason
    if invalid_project_id:
        payload["invalidProjectId"] = invalid_project_id
    _write_json(CURRENT_PROJECT_STATE_PATH, payload)
    return payload


def _slug_from_title(title: str) -> str:
    cleaned = _normalize_project_id(title, max_length=32) or "project"
    suffix = uuid.uuid4().hex[:8]
    return f"proj-{cleaned}-{suffix}"


def _find_template(template_id: str | None, templates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not template_id:
        return None
    return next((tpl for tpl in templates if tpl.get("id") == template_id), None)


def _duration_to_seconds(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            return int(match.group(0))
    return 8


def _status_label(status_type: str) -> str:
    return {
        "running": "创作中",
        "completed": "已完成",
        "draft": "未完成",
    }.get(status_type, "未完成")


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            text = _first_text(item)
            if text:
                return text
    return ""


def _text_list(value: Any, limit: int = 8) -> list[str]:
    if isinstance(value, list):
        rows = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str):
        rows = [item.strip() for item in re.split(r"[,，、/|]\s*", value) if item.strip()]
    else:
        rows = []
    return rows[:limit]


def _structured_fields(schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    fields = (schema or {}).get("fields")
    return [field for field in fields if isinstance(field, dict)] if isinstance(fields, list) else []


def _structured_template_value(field: dict[str, Any]) -> Any:
    field_type = str(field.get("type") or "string")
    if field_type == "array":
        item_spec = field.get("items") if isinstance(field.get("items"), dict) else {}
        if str(item_spec.get("type") or "string") == "object":
            return [_structured_template_object(item_spec)]
        return ["<按字段定义生成>"]
    if field_type == "object":
        return _structured_template_object(field)
    if field_type in {"integer", "number"}:
        return 0
    if field_type == "boolean":
        return False
    enum_values = field.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return enum_values[0]
    return "<按字段定义生成>"


def _structured_template_object(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        str(field.get("name") or ""): _structured_template_value(field)
        for field in _structured_fields(schema)
        if str(field.get("name") or "").strip()
    }


def _structured_schema_contract(schema: dict[str, Any] | None) -> str:
    if not isinstance(schema, dict):
        return ""
    schema_name = str(schema.get("name") or "structured_payload").strip()
    schema_description = str(schema.get("description") or "").strip()
    required_names: list[str] = []

    def field_contract_lines(current_schema: dict[str, Any], *, path_prefix: str = "") -> list[str]:
        lines: list[str] = []
        for field in _structured_fields(current_schema):
            name = str(field.get("name") or "").strip()
            if not name:
                continue
            path = f"{path_prefix}.{name}" if path_prefix else name
            field_type = str(field.get("type") or "string")
            description = str(field.get("description") or "").strip()
            enum_values = field.get("enum")
            enum_note = (
                "；可选值："
                + ", ".join(f"`{str(item)}`" for item in enum_values)
                if isinstance(enum_values, list) and enum_values
                else ""
            )
            required = bool(field.get("required"))
            empty_note = "；允许空数组" if field_type == "array" and bool(field.get("allow_empty")) else ""
            if required:
                required_names.append(path)
            lines.append(
                f"- 字段名 `{path}`（类型：`{field_type}`{'，必填' if required else ''}{empty_note}）：{description}{enum_note}"
            )
            if field_type == "array":
                item_spec = field.get("items") if isinstance(field.get("items"), dict) else {}
                if str(item_spec.get("type") or "string") == "object":
                    lines.extend(field_contract_lines(item_spec, path_prefix=f"{path}[]"))
            elif field_type == "object":
                lines.extend(field_contract_lines(field, path_prefix=path))
        return lines

    field_lines = field_contract_lines(schema)
    template = json.dumps(_structured_template_object(schema), ensure_ascii=False, indent=2)
    return (
        "\n\n结构化输出契约：\n"
        f"- 契约名称：`{schema_name}`\n"
        + (f"- 契约说明：{schema_description}\n" if schema_description else "")
        + "- 只输出一个 JSON 对象，不要代码块、解释文字、寒暄或额外包裹字段。\n"
        + "- 字段名必须与模板完全一致；不知道时也要给出最可信的空安全值，不要省略必填字段。\n"
        + "- JSON 模板只表示字段结构，占位值不要原样输出。\n"
        + (f"- 必填字段：{', '.join(f'`{item}`' for item in required_names)}\n" if required_names else "")
        + "字段定义：\n"
        + "\n".join(field_lines)
        + "\nJSON 模板：\n"
        + template
    )


def _structured_prompt(prompt: str, schema: dict[str, Any] | None) -> str:
    return str(prompt or "") + _structured_schema_contract(schema)


def _structured_system_prompt(system_prompt: str, schema: dict[str, Any] | None) -> str:
    if not isinstance(schema, dict):
        return system_prompt
    prefix = (
        "输出格式要求：必须按用户提供的结构化输出契约输出一个可解析 JSON 对象；"
        "不要输出解释、寒暄或契约之外的包裹层。"
    )
    base = str(system_prompt or "").strip()
    return base + "\n\n" + prefix if base else prefix


def _structured_json_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(schema, dict):
        return None

    def field_schema(field: dict[str, Any]) -> dict[str, Any]:
        field_type = str(field.get("type") or "string")
        result: dict[str, Any]
        if field_type == "array":
            item_spec = field.get("items") if isinstance(field.get("items"), dict) else {"type": "string"}
            result = {"type": "array", "items": field_schema(item_spec)}
        elif field_type == "object":
            result = _structured_json_schema(field) or {"type": "object"}
        elif field_type in {"integer", "number", "boolean"}:
            result = {"type": field_type}
        else:
            result = {"type": "string"}
        description = str(field.get("description") or "").strip()
        if description:
            result["description"] = description
        enum_values = field.get("enum")
        if isinstance(enum_values, list) and enum_values:
            result["enum"] = enum_values
        return result

    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in _structured_fields(schema):
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        properties[name] = field_schema(field)
        if field.get("required"):
            required.append(name)
    result: dict[str, Any] = {
        "type": "object",
        "additionalProperties": bool(schema.get("allow_extras")),
        "properties": properties,
    }
    if required:
        result["required"] = required
    return result


def _structured_response_format(schema: dict[str, Any] | None, *, api: str) -> dict[str, Any] | None:
    json_schema = _structured_json_schema(schema)
    if not json_schema:
        return None
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(schema.get("name") or "response")).strip("_") or "response"
    if api == "responses":
        return {"type": "json_schema", "name": name, "strict": True, "schema": json_schema}
    if api == "anthropic-messages":
        return {
            "format": {
                "type": "json_schema",
                "schema": json_schema,
            }
        }
    if api == "gemini-generate":
        return {
            "responseMimeType": "application/json",
            "responseJsonSchema": json_schema,
        }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": json_schema,
        },
    }


def _provider_probe_summary(provider: dict[str, Any]) -> dict[str, Any]:
    summary = provider.get("probe_summary") if isinstance(provider.get("probe_summary"), dict) else {}
    if not summary:
        last_test = provider.get("last_test") if isinstance(provider.get("last_test"), dict) else {}
        summary = last_test.get("probeSummary") if isinstance(last_test.get("probeSummary"), dict) else {}
    return summary if isinstance(summary, dict) else {}


def _structured_model_api_name(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("api_model_id"):
            return str(value["api_model_id"]).removeprefix("models/").strip()
        value = value.get("id") or value.get("model") or value.get("name") or value.get("label") or ""
    text = str(value or "").strip()
    if not text:
        return ""
    if ":" in text:
        text = text.split(":", 1)[1]
    if text.startswith("models/"):
        text = text.split("/", 1)[1]
    return text.strip()


def _provider_native_structured_probe_model(provider: dict[str, Any]) -> str:
    summary = _provider_probe_summary(provider)
    return str(
        summary.get("nativeJsonSchemaModel")
        or summary.get("native_json_schema_model")
        or ""
    ).removeprefix("models/").strip()


def _provider_native_structured_model_records(provider: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = provider.get("native_structured_models")
    if not isinstance(raw, dict):
        raw = provider.get("nativeStructuredModels")
    if not isinstance(raw, dict):
        return {}
    records: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            record = copy.deepcopy(value)
        else:
            record = {"status": str(value or "").strip()}
        model_name = str(record.get("model") or key).removeprefix("models/").strip()
        if not model_name:
            continue
        status = str(record.get("status") or "").strip()
        if status not in {"supported", "unsupported", "unknown"}:
            status = "unknown"
        record["model"] = model_name
        record["status"] = status
        endpoint = str(record.get("endpoint") or record.get("nativeJsonSchemaEndpoint") or "").strip()
        if endpoint:
            record["endpoint"] = normalize_media_endpoint(endpoint)
        records[model_name] = record
    return records


def _provider_native_structured_model_record(
    provider: dict[str, Any],
    model: dict[str, Any] | Any,
) -> dict[str, Any] | None:
    model_name = _structured_model_api_name(model)
    if not model_name:
        return None
    records = _provider_native_structured_model_records(provider)
    record = records.get(model_name)
    return copy.deepcopy(record) if isinstance(record, dict) else None


def _provider_native_structured_status(provider: dict[str, Any], model: dict[str, Any]) -> str:
    from .provider_models import _text_model_generation_endpoint

    endpoint = _text_model_generation_endpoint(provider, model)
    record = _provider_native_structured_model_record(provider, model)
    if isinstance(record, dict):
        probe_endpoint = record.get("probeEndpoint") or record.get("endpoint")
        if probe_endpoint and endpoint != normalize_media_endpoint(probe_endpoint):
            return "unknown"
        if isinstance(model, dict) and model.get("supported_endpoint_types") and (
            model.get("endpoint_constraints") or model.get("routing_source") != "relay-discovery"
        ) and record.get("endpoint") and record["endpoint"] not in model["supported_endpoint_types"]:
            return "unknown"
        status = str(record.get("status") or "").strip()
        return status if status in {"supported", "unsupported"} else "unknown"
    summary = _provider_probe_summary(provider)
    provider_status = str(provider.get("native_structured_output") or provider.get("nativeStructuredOutput") or "").strip()
    summary_status = str(summary.get("nativeJsonSchema") or "").strip() if isinstance(summary, dict) else ""
    status = provider_status if provider_status in {"supported", "unsupported"} else summary_status or "unknown"
    if status not in {"supported", "unsupported"}:
        return "unknown"
    probe_model = _provider_native_structured_probe_model(provider)
    if not probe_model:
        return "unknown"
    current_model = _structured_model_api_name(model)
    probe_endpoint = summary.get("nativeJsonSchemaEndpoint")
    if probe_endpoint and endpoint != normalize_media_endpoint(probe_endpoint):
        return "unknown"
    return status if current_model and current_model == probe_model else "unknown"


def _provider_supports_native_structured_output(provider: dict[str, Any], model: dict[str, Any]) -> bool:
    return _provider_native_structured_status(provider, model) == "supported"


def _provider_native_structured_endpoint(
    provider: dict[str, Any],
    model: dict[str, Any] | Any | None = None,
) -> str:
    if model is not None:
        record = _provider_native_structured_model_record(provider, model)
        if isinstance(record, dict):
            endpoint = str(record.get("endpoint") or "").strip()
            if endpoint:
                return normalize_media_endpoint(endpoint)
    summary = _provider_probe_summary(provider)
    if model is not None and _structured_model_api_name(model) != _provider_native_structured_probe_model(provider):
        return ""
    if isinstance(summary, dict):
        endpoint = str(
            summary.get("nativeJsonSchemaEndpoint")
            or summary.get("native_json_schema_endpoint")
            or ""
        ).strip()
        if endpoint:
            return normalize_media_endpoint(endpoint)
    return ""


def _provider_with_native_structured_model_result(
    provider: dict[str, Any],
    model: dict[str, Any] | Any,
    result: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    from .provider_models import _text_model_generation_endpoint

    updated = copy.deepcopy(provider)
    model_name = str(result["model"]).removeprefix("models/").strip() if result.get("model") else _structured_model_api_name(model)
    if not model_name:
        return updated
    raw_status = str(result.get("status") or "").strip().lower()
    if raw_status == "ok":
        status = "supported"
    elif raw_status == "unsupported":
        status = "unsupported"
    else:
        status = "unknown"
    endpoint = normalize_media_endpoint(result.get("endpoint") or "")
    record: dict[str, Any] = {
        "status": status,
        "model": model_name,
        "checkedAt": _now(),
        "source": source,
    }
    # A schema probe may validate a different OpenAI route from ordinary text.
    # Bind that result to the original selection so later route changes invalidate it.
    record["probeEndpoint"] = _text_model_generation_endpoint(provider, model if isinstance(model, dict) else None)
    if endpoint:
        record["endpoint"] = endpoint
    error = str(result.get("error") or "").strip()
    if error:
        record["error"] = error
    records = _provider_native_structured_model_records(updated)
    records[model_name] = record
    updated["native_structured_models"] = records
    updated.pop("nativeStructuredModels", None)
    summary = _provider_probe_summary(updated)
    summary["nativeJsonSchema"] = status
    summary["nativeJsonSchemaModel"] = model_name
    if endpoint:
        summary["nativeJsonSchemaEndpoint"] = endpoint
    if endpoint == "anthropic-messages" and result.get("url") and result.get("authMode") in {"bearer", "x-api-key"}:
        summary["nativeJsonSchemaUrl"] = result["url"]
        summary["nativeJsonSchemaAuthMode"] = result["authMode"]
    updated["probe_summary"] = summary
    updated["native_structured_output"] = status
    return updated


def _structured_repair_prompt(
    original_prompt: str,
    schema: dict[str, Any] | None,
    *,
    raw_text: str,
    error: str,
) -> str:
    return (
        str(original_prompt or "")
        + _structured_schema_contract(schema)
        + "\n\n上一次模型输出未通过本地 JSON 校验。"
        + "\n请只根据原任务重新输出一个符合结构化输出契约的 JSON 对象，不要解释。"
        + f"\n校验错误：{error or '未知错误'}"
        + "\n上一次输出：\n"
        + str(raw_text or "")[:4000]
    )


def _snake_to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)([A-Z])", r"_\1", value).lower()


def _structured_field_keys(field: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for raw in [field.get("name"), *list(field.get("aliases") or [])]:
        text = str(raw or "").strip()
        if not text:
            continue
        for item in (text, _snake_to_camel(text), _camel_to_snake(text)):
            if item and item not in keys:
                keys.append(item)
    return keys


def _structured_raw_value(data: dict[str, Any], field: dict[str, Any]) -> Any:
    for key in _structured_field_keys(field):
        if key in data:
            return data.get(key)
    return None


def _coerce_structured_value(value: Any, field: dict[str, Any]) -> Any:
    field_type = str(field.get("type") or "string")
    if value is None:
        return field.get("default")
    if field_type == "array":
        item_spec = field.get("items") if isinstance(field.get("items"), dict) else {}
        item_type = str(item_spec.get("type") or "string")
        rows = value if isinstance(value, list) else _text_list(value)
        if item_type == "object":
            result = []
            for item in rows if isinstance(rows, list) else []:
                if isinstance(item, dict):
                    normalized, _errors = _normalize_structured_payload(item, item_spec)
                    result.append(normalized)
            return result
        if item_type in {"integer", "number", "boolean"}:
            return [_coerce_structured_value(item, item_spec) for item in rows]
        return _text_list(rows)
    if field_type == "object":
        if isinstance(value, dict):
            normalized, _errors = _normalize_structured_payload(value, field)
            return normalized
        return {}
    if field_type == "integer":
        try:
            return int(value)
        except (TypeError, ValueError):
            return field.get("default")
    if field_type == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return field.get("default")
    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        lowered = str(value).strip().lower()
        if lowered in {"true", "1", "yes", "y", "是"}:
            return True
        if lowered in {"false", "0", "no", "n", "否"}:
            return False
        return field.get("default")

    if isinstance(value, list) and field.get("join_list") is not None:
        text = str(field.get("join_list") or "").join(_text_list(value, limit=16))
    else:
        text = _first_text(value)
    enum_values = field.get("enum")
    if isinstance(enum_values, list) and enum_values:
        aliases = field.get("enum_aliases") if isinstance(field.get("enum_aliases"), dict) else {}
        normalized = text.strip().lower()
        text = str(aliases.get(normalized) or text).strip()
        if text not in enum_values:
            return field.get("default") or ""
    return text


def _structured_value_missing(value: Any, field: dict[str, Any]) -> bool:
    if value is None:
        return True
    field_type = str(field.get("type") or "string")
    if field_type == "array":
        return not isinstance(value, list) or (not value and not bool(field.get("allow_empty")))
    if field_type == "object":
        return not isinstance(value, dict) or not value
    if field_type in {"integer", "number"}:
        return value is None
    if field_type == "boolean":
        return not isinstance(value, bool)
    return not str(value).strip()


def _normalize_structured_payload(
    data: dict[str, Any],
    schema: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(schema, dict):
        return data, []
    normalized: dict[str, Any] = {}
    errors: list[str] = []
    for field in _structured_fields(schema):
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        value = _coerce_structured_value(_structured_raw_value(data, field), field)
        if (
            field.get("required")
            and not field.get("allow_missing_in_response")
            and _structured_value_missing(value, field)
        ):
            errors.append(f"缺少或无法归一化字段：{name}")
        normalized[name] = value
    if bool(schema.get("allow_extras")):
        for key, value in data.items():
            normalized.setdefault(str(key), value)
    return normalized, errors




def _timestamp_rank(iso_value: str | None) -> int:
    if not iso_value:
        return 0
    try:
        return int(datetime.fromisoformat(str(iso_value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def _normalize_project_title(title: str | None) -> str:
    return re.sub(r"\s+", " ", str(title or "").strip()).casefold()


def _project_title_exists(title: str, exclude_project_id: str | None = None) -> bool:
    target = _normalize_project_title(title)
    if not target:
        return False
    ensure_store()
    for path in PROJECTS_DIR.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        if exclude_project_id and path.name == exclude_project_id:
            continue
        meta = _read_json(path / "project.json", {})
        if not isinstance(meta, dict) or meta.get("deleted_at"):
            continue
        if _normalize_project_title(meta.get("title")) == target:
            return True
    return False


def _project_relative_path(project_id: str, path: Path) -> str | None:
    from .agent_sessions import _project_dir
    try:
        return path.resolve().relative_to(_project_dir(project_id).resolve()).as_posix()
    except ValueError:
        return None


def _global_relative_path(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(GLOBAL_DIR.resolve()).as_posix()
    except ValueError:
        return None


def _is_path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _touch_project_meta(project_id: str | None) -> None:
    from .agent_sessions import _project_meta_path
    if not project_id:
        return
    path = _project_meta_path(project_id)
    meta = _read_json(path, {})
    if not isinstance(meta, dict):
        return
    meta["updated_at"] = _now()
    _write_json(path, meta)


def _local_project_image_ref(project_id: str, path: Path, source: str) -> dict[str, Any] | None:
    if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file():
        return None
    relative_path = _project_relative_path(project_id, path)
    if not relative_path:
        return None
    return {
        "source": source,
        "path": str(path),
        "relativePath": relative_path,
        "relative_path": relative_path,
    }


def _image_ref_from_value(project_id: str, value: Any, source: str) -> dict[str, Any] | None:
    from .agent_sessions import _project_dir
    if isinstance(value, dict):
        if value.get("dataUrl"):
            return _image_ref_from_value(project_id, value.get("dataUrl"), source)
        if value.get("url"):
            return _image_ref_from_value(project_id, value.get("url"), source)
        for key in ("path", "filePath", "file_path", "imagePath", "image_path", "previewPath", "preview_path"):
            if value.get(key):
                return _image_ref_from_value(project_id, value.get(key), source)
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.startswith(("data:image/", "http://", "https://")):
        return {"source": source, "url": text}
    raw_path = Path(text)
    path = raw_path if raw_path.is_absolute() else _project_dir(project_id) / raw_path
    return _local_project_image_ref(project_id, path, source)


def _project_style_reference_ref(project_id: str, value: Any) -> dict[str, Any] | None:
    ref = _image_ref_from_value(project_id, value, "visual_style")
    if not ref:
        return None
    if isinstance(value, dict):
        for key in ("id", "name", "mimeType", "mime_type", "styleDescription", "style_description"):
            if value.get(key):
                ref[key] = value[key]
    return ref


def _style_thumbnail_ref(file_name: str | None) -> dict[str, Any] | None:
    if not file_name:
        return None
    clean = Path(str(file_name).replace("\\", "/")).name
    if not clean or Path(clean).suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    if not (STYLE_THUMBNAILS_DIR / clean).is_file():
        return None
    return {
        "source": "visual_style",
        "styleThumbnailFile": clean,
        "style_thumbnail_file": clean,
    }


def _favorite_style_thumbnail_path(value: Any) -> Path | None:
    if isinstance(value, dict):
        for key in (
            "thumbnailPath",
            "thumbnail_path",
            "filePath",
            "file_path",
            "path",
        ):
            raw = str(value.get(key) or "").strip()
            if not raw:
                continue
            path = Path(raw)
            if not path.is_absolute():
                path = GLOBAL_DIR / raw
            path = path.resolve()
            if _is_path_within(path, GLOBAL_DIR) and path.suffix.lower() in IMAGE_EXTENSIONS:
                return path
        for key in ("relativePath", "relative_path", "file"):
            raw = str(value.get(key) or "").strip()
            if not raw:
                continue
            path = (GLOBAL_DIR / raw).resolve()
            if _is_path_within(path, GLOBAL_DIR) and path.suffix.lower() in IMAGE_EXTENSIONS:
                return path
        file_name = value.get("thumbnail_file") or value.get("thumbnailFile")
    else:
        file_name = value

    if not isinstance(file_name, str) or not file_name.strip():
        return None
    clean = Path(file_name.replace("\\", "/")).name
    if not clean or Path(clean).suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    return FAVORITE_STYLE_THUMBNAILS_DIR / clean


def _favorite_style_thumbnail_fields(file_name: str, path: Path) -> dict[str, Any]:
    relative_path = _global_relative_path(path)
    return {
        "thumbnailFile": file_name,
        "thumbnail_file": file_name,
        "thumbnailPath": str(path),
        "thumbnail_path": str(path),
        "filePath": str(path),
        "relativePath": relative_path,
        "relative_path": relative_path,
    }


def _favorite_style_thumbnail_ref(template: dict[str, Any]) -> dict[str, Any] | None:
    path = _favorite_style_thumbnail_path(template)
    if not path or not path.is_file():
        return None
    relative_path = _global_relative_path(path)
    if not relative_path:
        return None
    return {
        "source": "favorite_style",
        "path": str(path),
        "filePath": str(path),
        "relativePath": relative_path,
        "relative_path": relative_path,
    }


def _style_template_thumbnail_ref(template: dict[str, Any]) -> dict[str, Any] | None:
    if template.get("category") == "favorite" or template.get("source") == "favorite":
        return _favorite_style_thumbnail_ref(template)
    return _style_thumbnail_ref(template.get("thumbnail_file") or template.get("thumbnailFile"))


def _project_content_image_refs(project_id: str) -> list[dict[str, Any]]:
    from .agent_sessions import _project_dir
    refs: list[dict[str, Any]] = []
    episodes_root = _project_dir(project_id) / "episodes"
    if episodes_root.exists():
        for episode_path in sorted(path for path in episodes_root.iterdir() if path.is_dir()):
            for item in read_episode_card_results(project_id, episode_path.name):
                for key in ("preview", "image", "path", "file", "filePath", "imagePath"):
                    ref = _image_ref_from_value(project_id, item.get(key), "project_content")
                    if ref:
                        refs.append(ref)
                        break

    assets = _read_json(_project_dir(project_id) / "assets" / "assets.json", {})
    if isinstance(assets, dict):
        for group in ("characters", "scenes"):
            items = assets.get(group)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                if _asset_is_offline(item):
                    continue
                for key in (
                    "thumbnail",
                    "thumbnailPath",
                    "thumbnail_path",
                    "image",
                    "imagePath",
                    "image_path",
                    "reference_image",
                    "referenceImage",
                ):
                    ref = _image_ref_from_value(project_id, item.get(key), "project_content")
                    if ref:
                        refs.append(ref)
                        break
    return refs


def _project_thumbnail_ref(project_id: str, meta: dict[str, Any]) -> dict[str, Any] | None:
    from .settings_loaders import load_style_templates
    cover_ref = _image_ref_from_value(project_id, meta.get("cover_image"), "project_cover")
    if cover_ref:
        return cover_ref

    content_refs = _project_content_image_refs(project_id)
    if content_refs:
        return random.choice(content_refs)

    style_ref = _image_ref_from_value(project_id, meta.get("style_reference"), "visual_style")
    if style_ref:
        return style_ref

    style_template = _find_template(str(meta.get("style_template_id") or ""), load_style_templates())
    if style_template:
        return _style_template_thumbnail_ref(style_template)
    return None


def _project_asset_counts(project_id: str) -> dict[str, int]:
    from .agent_sessions import _project_dir
    assets = _read_json(_project_dir(project_id) / "assets" / "assets.json", {})
    if not isinstance(assets, dict):
        return {"characters": 0, "creatures": 0, "scenes": 0, "props": 0}
    return {
        "characters": len([item for item in assets.get("characters", []) if isinstance(item, dict) and not _asset_is_offline(item)]),
        "creatures": len([item for item in assets.get("creatures", []) if isinstance(item, dict) and not _asset_is_offline(item)]),
        "scenes": len([item for item in assets.get("scenes", []) if isinstance(item, dict) and not _asset_is_offline(item)]),
        "props": len([item for item in assets.get("props", []) if isinstance(item, dict) and not _asset_is_offline(item)]),
    }


def get_project_asset_counts(project_id: str | None) -> dict[str, int]:
    if not project_id:
        return {"characters": 0, "creatures": 0, "scenes": 0, "props": 0}
    return _project_asset_counts(str(project_id))


_EPISODE_PRODUCTION_CURRENT_STATUS_LABELS = {
    "video.generated": "待生成当前工作链视频",
    "storyboard.generated": "待生成分镜图",
    "director_plan.generated": "待生成分镜脚本",
    "cinematic_script.generated": "待生成影视化剧本",
    "asset_references.linked": "待绑定资产引用",
    "workflow.ready": "待生成画布工作链",
    "episode.source_ready": "待提交原文",
}

_EPISODE_PRODUCTION_READY_STATUS_LABEL = "当前集全部视频已生成"


def _episode_status_state_set(status: dict[str, Any], key: str) -> set[str]:
    value = status.get(key) if isinstance(status, dict) else []
    if not isinstance(value, list):
        return set()
    return {str(item or "").strip() for item in value if str(item or "").strip()}


def _episode_production_complete(status: dict[str, Any]) -> bool:
    if not isinstance(status, dict):
        return False
    overall_status = str(status.get("overallStatus") or "").strip()
    route_states = status.get("routeStates") if isinstance(status.get("routeStates"), list) else []
    route_completed = [
        _episode_status_state_set(route, "completedStates")
        for route in route_states
        if isinstance(route, dict)
    ]
    if route_completed:
        return all(
            "video.generated" in completed
            for completed in route_completed
        )
    terminal_state = str(status.get("currentState") or "").strip()
    return overall_status == "ready" and terminal_state == "video.generated"


def _episode_production_blocker_message(status: dict[str, Any]) -> str:
    blockers = status.get("blockedBy")
    if not isinstance(blockers, list):
        blockers = status.get("blockingIssues") if isinstance(status.get("blockingIssues"), list) else []
    for item in blockers:
        if isinstance(item, dict):
            for key in ("message", "text", "title", "summary", "reason", "suggestion"):
                message = str(item.get(key) or "").strip()
                if message:
                    return message
        else:
            message = str(item or "").strip()
            if message:
                return message
    return ""


def _episode_production_status_label(status: dict[str, Any]) -> str:
    overall_status = str(status.get("overallStatus") or "").strip()
    current_state = str(status.get("currentState") or "").strip()
    if overall_status == "ready":
        return _EPISODE_PRODUCTION_READY_STATUS_LABEL
    if overall_status == "blocked" and not current_state:
        message = _episode_production_blocker_message(status)
        return f"生产阻塞：{message}" if message else "生产阻塞，需处理"
    return _EPISODE_PRODUCTION_CURRENT_STATUS_LABELS.get(current_state, current_state)


def _episode_status_label(project_id: str, episode_id: str, fallback: Any) -> str:
    from .agent_sessions import _project_dir
    status_path = _project_dir(project_id) / "episodes" / episode_id / "episode_production_status.json"
    status = _read_json(status_path, {}) if status_path.is_file() else {}
    if isinstance(status, dict):
        label = _episode_production_status_label(status)
        if label:
            return label
    return str(fallback or "草稿")


def _current_project_episode_id(project_id: str, episodes: list[Any]) -> str:
    from .agent_sessions import _project_dir
    fallback_id = "E01"
    for index, item in enumerate(episodes):
        if not isinstance(item, dict):
            continue
        episode_id = str(item.get("id") or f"E{index + 1:02d}")
        fallback_id = episode_id
        status_path = _project_dir(project_id) / "episodes" / episode_id / "episode_production_status.json"
        status = _read_json(status_path, {}) if status_path.is_file() else {}
        complete = _episode_production_complete(status)
        if not complete:
            return episode_id
    return fallback_id


def _project_row(project_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    episodes = meta.get("episodes") if isinstance(meta.get("episodes"), list) else []
    updated_at = meta.get("updated_at") or meta.get("created_at")
    status_type = str(meta.get("status_type") or "draft")
    episode_count = len(episodes)
    thumbnail = _project_thumbnail_ref(project_id, meta)
    asset_counts = _project_asset_counts(project_id)
    overview_analysis = meta.get("overview_analysis") if isinstance(meta.get("overview_analysis"), dict) else {}
    overview_result = overview_analysis.get("result") if isinstance(overview_analysis.get("result"), dict) else {}
    overview_excerpt_summary = _first_text(
        overview_result.get("excerpt_summary") or overview_result.get("excerptSummary")
    )
    overview_excerpt_summary = _ensure_prompt_sentence_end(overview_excerpt_summary)
    overview_genre_context = _first_text(
        overview_result.get("genre_context") or overview_result.get("genreContext")
    )
    overview_theme_visual_context = _first_text(
        overview_result.get("theme_visual_context")
        or overview_result.get("themeVisualContext")
        or meta.get("theme_visual_context")
    )
    overview_narrator_voice_design_prompt = _first_text(
        overview_result.get("narrator_voice_design_prompt")
        or overview_result.get("narratorVoiceDesignPrompt")
    )
    overview_narrator_reference_audio = (
        overview_result.get("narrator_reference_audio")
        or overview_result.get("narratorReferenceAudio")
    )
    if isinstance(overview_narrator_reference_audio, dict):
        from .agent_sessions import _hydrate_media_asset_for_ui
        overview_narrator_reference_audio = _hydrate_media_asset_for_ui(
            project_id, overview_narrator_reference_audio
        )
    overview = {
        "excerptSummary": overview_excerpt_summary,
        "excerpt_summary": overview_excerpt_summary,
        "genreContext": overview_genre_context,
        "genre_context": overview_genre_context,
        "themeVisualContext": overview_theme_visual_context,
        "theme_visual_context": overview_theme_visual_context,
        "narratorVoiceDesignPrompt": overview_narrator_voice_design_prompt,
        "narrator_voice_design_prompt": overview_narrator_voice_design_prompt,
        "narratorReferenceAudio": overview_narrator_reference_audio,
        "narrator_reference_audio": overview_narrator_reference_audio,
        "source": overview_analysis.get("source"),
        "modelId": overview_analysis.get("modelId"),
        "modelLabel": overview_analysis.get("modelLabel"),
        "providerId": overview_analysis.get("providerId"),
        "sourceId": overview_analysis.get("sourceId"),
        "sourceTitle": overview_analysis.get("sourceTitle"),
        "contentPath": overview_analysis.get("contentPath"),
        "relativePath": overview_analysis.get("relativePath"),
        "excerptChars": overview_analysis.get("excerptChars"),
        "error": overview_analysis.get("error"),
    }
    if not any(
        overview.get(key)
        for key in (
            "excerptSummary",
            "genreContext",
            "themeVisualContext",
            "narratorVoiceDesignPrompt",
            "narratorReferenceAudio",
        )
    ):
        overview = None
    return {
        "id": project_id,
        "name": meta.get("title") or project_id,
        "updatedAt": _display_time(updated_at),
        "updatedAtRank": _timestamp_rank(updated_at),
        "episodeCount": episode_count,
        "episodes": [
            {
                "id": episode_id,
                "title": str(item.get("title") or f"第 {index + 1} 集"),
                "status": _episode_status_label(project_id, episode_id, item.get("status")),
            }
            for index, item in enumerate(episodes)
            if isinstance(item, dict)
            for episode_id in [str(item.get("id") or f"E{index + 1:02d}")]
        ],
        "sourceCount": int(meta.get("source_count") or 0),
        "characterCount": asset_counts["characters"],
        "creatureCount": asset_counts["creatures"],
        "sceneCount": asset_counts["scenes"],
        "propCount": asset_counts["props"],
        "status": _status_label(status_type),
        "statusType": status_type,
        "contentMode": meta.get("content_mode") or "drama",
        "content_mode": meta.get("content_mode") or "drama",
        "narrativeMode": meta.get("narrative_mode") or "drama",
        "wordCount": meta.get("wordCount") or meta.get("word_count"),
        "word_count": meta.get("word_count") or meta.get("wordCount"),
        "aspectRatio": meta.get("aspect_ratio") or "9:16",
        "summary": meta.get("summary") or "故事版视频项目，等待导入源文本并生成故事版计划。",
        "overview": overview,
        "sourceFile": meta.get("source") if isinstance(meta.get("source"), dict) else None,
        "accent": meta.get("accent") or ACCENTS[abs(hash(project_id)) % len(ACCENTS)],
        "currentEpisodeId": _current_project_episode_id(project_id, episodes),
        "thumbnail": thumbnail,
        "thumbnailSource": thumbnail.get("source") if thumbnail else None,
        "thumbnailPath": thumbnail.get("path") if thumbnail else None,
        "thumbnailRelativePath": thumbnail.get("relativePath") if thumbnail else None,
        "thumbnailStyleFile": thumbnail.get("styleThumbnailFile") if thumbnail else None,
        "thumbnailUrl": thumbnail.get("url") if thumbnail else None,
    }


def list_projects() -> list[dict[str, Any]]:
    from .project_deletion_guard import is_project_deleting

    ensure_store()
    rows: list[dict[str, Any]] = []
    for path in PROJECTS_DIR.iterdir():
        if not path.is_dir() or path.name.startswith(".") or is_project_deleting(path.name):
            continue
        meta_path = path / "project.json"
        if not meta_path.is_file():
            continue
        try:
            meta = _read_json(meta_path, {})
            if not isinstance(meta, dict) or meta.get("deleted_at"):
                continue
            rows.append(_project_row(path.name, meta))
        except FileNotFoundError:
            if not is_project_deleting(path.name) and path.exists():
                raise
    rows.sort(key=lambda row: row["updatedAtRank"], reverse=True)
    return rows


def get_dashboard() -> dict[str, Any]:
    projects = list_projects()
    stats = {
        "total": len(projects),
        "running": sum(1 for row in projects if row["statusType"] == "running"),
        "completed": sum(1 for row in projects if row["statusType"] == "completed"),
    }
    return {
        "projects": projects,
        "stats": stats,
        "featuredProjectId": projects[0]["id"] if projects else None,
    }


def set_current_project(project_id: str | None) -> dict[str, Any]:
    from .agent_sessions import _project_meta_path
    ensure_store()
    normalized_id = _validate_current_project_id(project_id)
    if not normalized_id:
        payload = _write_current_project_cleared_state()
        return {"success": True, **payload}

    meta_path = _project_meta_path(normalized_id)
    if not meta_path.is_file():
        _write_current_project_cleared_state(
            reason="project_missing",
            invalid_project_id=normalized_id,
        )
        raise ValueError(f"项目不存在：{normalized_id}")
    meta = _read_json(meta_path, {})
    if not isinstance(meta, dict) or meta.get("deleted_at"):
        _write_current_project_cleared_state(
            reason="project_unavailable",
            invalid_project_id=normalized_id,
        )
        raise ValueError(f"项目不可用：{normalized_id}")
    title = str(meta.get("title") or meta.get("name") or normalized_id).strip()
    payload = {
        "projectId": normalized_id,
        "projectTitle": title,
        "projectUpdatedAt": meta.get("updated_at")
        or meta.get("updatedAt")
        or meta.get("created_at")
        or meta.get("createdAt"),
        "savedAt": _now(),
    }
    _write_json(CURRENT_PROJECT_STATE_PATH, payload)
    return {"success": True, **payload}


def get_creation_options(project_id: str | None = None) -> dict[str, Any]:
    from .provider_models import _available_model_capabilities
    from .provider_models import _creation_model_config_status
    from .agent_sessions import _project_dir
    from .settings_loaders import load_global_config
    from .settings_loaders import load_script_adaptation_templates
    from .settings_loaders import load_style_templates
    from .settings_loaders import load_text_replacement_rules
    config = load_global_config()
    style_templates = load_style_templates()
    normalized_project_id = str(project_id or "").strip()
    if normalized_project_id:
        project_config = _read_json(_project_dir(normalized_project_id) / "config.json", {})
        style_config = project_config.get("style") if isinstance(project_config, dict) else None
        snapshot = style_config.get("favorite_snapshot") if isinstance(style_config, dict) else None
        snapshot_id = str(snapshot.get("id") or "").strip() if isinstance(snapshot, dict) else ""
        if snapshot_id:
            style_templates = [
                item for item in style_templates
                if str(item.get("id") or "") != snapshot_id
            ]
            style_templates.append(copy.deepcopy(snapshot))
    script_adaptation_templates = load_script_adaptation_templates()
    text_replacement_rules = load_text_replacement_rules()
    content_modes = [
        copy.deepcopy(item)
        for item in DEFAULT_GLOBAL_CONFIG.get("content_modes", [])
        if isinstance(item, dict) and item.get("id") == "drama"
    ]
    content_modes = content_modes or [
        {
            "id": "drama",
            "name": "故事版视频",
            "description": "基于分集原文创作剧情、剧本、分镜脚本、分镜和视频。",
        }
    ]
    aspect_ratio_order = {"16:9": 0, "9:16": 1}
    aspect_ratios = sorted(
        [str(item) for item in config.get("aspect_ratios", ["16:9", "9:16"])],
        key=lambda item: aspect_ratio_order.get(item, 99),
    )
    if not aspect_ratios:
        aspect_ratios = ["16:9", "9:16"]
    global_defaults = config.get("defaults") if isinstance(config.get("defaults"), dict) else {}
    defaults = {
        key: copy.deepcopy(global_defaults[key])
        for key in ("content_mode", "aspect_ratio", "source_language", "style_template_id")
        if key in global_defaults
    }
    defaults["content_mode"] = "drama"
    default_aspect_ratio = str(defaults.get("aspect_ratio") or "16:9")
    if default_aspect_ratio not in aspect_ratios:
        default_aspect_ratio = "16:9" if "16:9" in aspect_ratios else aspect_ratios[0]
    defaults["aspect_ratio"] = default_aspect_ratio
    capabilities = _available_model_capabilities(config)
    model_status = _creation_model_config_status(config, capabilities)
    if not _find_template(defaults.get("style_template_id"), style_templates):
        defaults["style_template_id"] = DEFAULT_STYLE_TEMPLATES[0]["id"]
    return {
        "contentModes": content_modes,
        "aspectRatios": aspect_ratios,
        "scriptAdaptationTemplates": script_adaptation_templates,
        "textReplacementRules": text_replacement_rules,
        "styleCategories": [
            {"id": category_id, "label": meta["label"]}
            for category_id, meta in STYLE_CATEGORY_META.items()
        ] + [
            *(
                [{"id": "favorite", "label": "风格收藏"}]
                if any(item.get("category") == "favorite" for item in style_templates)
                else []
            ),
        ],
        "styleTemplates": style_templates,
        "modelReadiness": model_status,
        "defaults": defaults,
    }


def get_global_settings() -> dict[str, Any]:
    from .splitting_templates import get_model_config
    from .settings_loaders import load_global_config
    from .settings_loaders import load_script_adaptation_templates
    from .settings_loaders import load_text_replacement_rules
    config = load_global_config()
    defaults = config["defaults"]
    return {
        "providers": [_public_provider(provider, include_models=False) for provider in config.get("providers", [])],
        "mediaProfiles": {
            "storyboardImage": {
                "model": defaults["storyboard"]["image_model"],
                "size": defaults["storyboard"]["image_size"],
                "panelCount": defaults["storyboard"]["panel_count"],
            },
            "storyboardVideo": {
                "provider": defaults["video"]["provider"],
                "model": defaults["video"]["model"],
                "durationSeconds": defaults["video"]["duration_seconds"],
                "resolution": defaults["video"]["resolution"],
                "generateAudio": defaults["video"]["generate_audio"],
            },
        },
        "creationOptions": get_creation_options(),
        "modelConfig": get_model_config(),
        "scriptAdaptationTemplates": load_script_adaptation_templates(),
        "textReplacementRules": load_text_replacement_rules(),
    }


def _save_global_config(config: dict[str, Any]) -> dict[str, Any]:
    from .provider_models import _model_capabilities_with_provider_models
    from .provider_models import _normalize_provider_rows
    from .provider_models import _provider_specific_model_id
    from .provider_models import _storage_global_config
    from .provider_models import _sync_defaults_with_model_config
    original_model_config = config.get("model_config") if isinstance(config.get("model_config"), dict) else {}
    original_model_ids = {
        section: str(original_model_config.get(section, {}).get("model_id") or "").strip()
        for section in ("image", "video", "agent", "text")
        if isinstance(original_model_config.get(section), dict)
    }
    config["provider_presets"] = _merge_provider_presets(config.get("provider_presets"))
    config["model_capabilities"] = _merge_model_capabilities(config.get("model_capabilities"))
    config["providers"] = _normalize_provider_rows(config.get("providers"), config["provider_presets"])
    retained_provider_model_ids: set[str] = set()
    for provider in config["providers"]:
        provider_id = str(provider.get("id") or "").strip()
        preset_id = str(provider.get("preset_id") or provider.get("presetId") or "").strip()
        for model in provider.get("models", []):
            if not isinstance(model, dict):
                continue
            raw_id = str(model.get("id") or model.get("api_model_id") or "").strip()
            if not raw_id:
                continue
            retained_provider_model_ids.add(raw_id)
            retained_provider_model_ids.add(_provider_specific_model_id(provider_id, raw_id, preset_id))
    config["model_capabilities"] = _model_capabilities_with_provider_models(
        config["model_capabilities"],
        config["providers"],
    )
    # 持久化全局配置时保留已保存的模型选择；是否可执行由运行时 connected 检查判断。
    _sync_defaults_with_model_config(config, config["model_capabilities"])
    for section, model_id in original_model_ids.items():
        if (
            model_id
            and not config["model_config"].get(section, {}).get("model_id")
            and model_id in retained_provider_model_ids
        ):
            config["model_config"][section]["model_id"] = model_id
    _write_json(GLOBAL_CONFIG_PATH, _storage_global_config(config))
    return config


def _public_provider(provider: dict[str, Any], *, include_models: bool = True) -> dict[str, Any]:
    from .provider_models import _provider_adapter_id
    visible = dict(provider)
    if not include_models:
        visible.pop("models", None)
    history = visible.pop("last_test", visible.get("lastTest", None))
    if isinstance(history, dict):
        compact_history = {key: value for key, value in history.items() if key not in {"remoteModels", "availableModels", "discoveredModels"}}
        if "remoteModelIds" not in history and isinstance(history.get("availableModels"), list):
            compact_history["remoteModelIds"] = [
                model["id"] for model in history["availableModels"]
                if isinstance(model, dict) and model.get("id")
            ]
        history = compact_history
    visible["lastTest"] = history
    result = copy.deepcopy(visible)
    # The local settings editor needs the stored key for explicit reveal/copy.
    result["apiKey"] = result.pop("api_key", result.get("apiKey", ""))
    result["adapterId"] = result.pop("adapter_id", result.get("adapterId", _provider_adapter_id(provider)))
    result["presetId"] = result.pop("preset_id", result.get("presetId", ""))
    result["officialTitle"] = result.pop("official_title", result.get("officialTitle", ""))
    result["apiKeyMasked"] = result.pop("api_key_masked", result.get("apiKeyMasked", ""))
    result["connectionStatus"] = result.pop("connection_status", result.get("connectionStatus", "untested"))
    result["baseUrl"] = result.pop("base_url", result.get("baseUrl", ""))
    result["defaultBaseUrl"] = result.pop("default_base_url", result.get("defaultBaseUrl", result.get("baseUrl", "")))
    result["baseUrlOptions"] = result.pop("base_url_options", result.get("baseUrlOptions", []))
    for option in result["baseUrlOptions"]:
        for stored_key, public_key in (("base_url", "baseUrl"), ("base_url_template", "baseUrlTemplate")):
            if stored_key in option:
                option[public_key] = option.pop(stored_key)
    result["baseUrlNote"] = result.pop("base_url_note", result.get("baseUrlNote", ""))
    result["docsUrl"] = result.pop("docs_url", result.get("docsUrl", ""))
    result["keyLabel"] = result.pop("key_label", result.get("keyLabel", "API_KEY"))
    result["iconKey"] = result.pop("icon_key", result.get("iconKey", result.get("logo", "")))
    result["probeSummary"] = result.pop("probe_summary", result.get("probeSummary", {}))
    result["nativeStructuredOutput"] = result.pop(
        "native_structured_output",
        result.get("nativeStructuredOutput", "unknown"),
    )
    result["nativeStructuredModels"] = result.pop(
        "native_structured_models",
        result.get("nativeStructuredModels", {}),
    )
    result.pop("agent_runtime", None)
    result.pop("agentRuntime", None)
    result["userAdded"] = result.pop("user_added", result.get("userAdded", False))
    result["addedAt"] = result.pop("added_at", result.get("addedAt", None))
    result["name"] = result.get("title") or result.get("name") or result.get("id")
    return result

__all__ = (
    '_normalize_project_id', '_slug_from_title', '_find_template',
    '_duration_to_seconds', '_status_label', '_first_text', '_text_list',
    '_structured_fields', '_structured_template_value',
    '_structured_template_object', '_structured_schema_contract', '_structured_prompt',
    '_structured_system_prompt', '_structured_json_schema', '_structured_response_format',
    '_structured_model_api_name', '_provider_native_structured_status',
    '_provider_supports_native_structured_output', '_provider_native_structured_endpoint',
    '_provider_with_native_structured_model_result',
    '_structured_repair_prompt', '_snake_to_camel', '_camel_to_snake', '_structured_field_keys',
    '_structured_raw_value', '_coerce_structured_value', '_structured_value_missing',
    '_normalize_structured_payload', '_display_time', '_timestamp_rank', '_normalize_project_title',
    '_project_title_exists', '_project_relative_path', '_global_relative_path', '_is_path_within',
    '_touch_project_meta', '_local_project_image_ref', '_image_ref_from_value', '_project_style_reference_ref',
    '_style_thumbnail_ref', '_favorite_style_thumbnail_path', '_favorite_style_thumbnail_fields',
    '_favorite_style_thumbnail_ref', '_style_template_thumbnail_ref', '_project_content_image_refs',
    '_project_thumbnail_ref', '_project_asset_counts', 'get_project_asset_counts', '_project_row',
    'list_projects', 'get_dashboard', 'set_current_project', 'get_creation_options',
    'get_global_settings', '_save_global_config', '_public_provider'
)
