# -*- coding: utf-8 -*-
"""全局模型、片段剧本策略和文字替换设置。"""

from __future__ import annotations

import re
import uuid
from typing import Any

from .catalogs import DEFAULT_SCRIPT_ADAPTATION_TEMPLATES
from .catalogs import GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH
from .catalogs import GLOBAL_TEXT_REPLACEMENT_RULES_PATH
from .store_core import _deep_merge
from .store_core import _normalize_text_replacement_rules
from .store_core import _now
from .store_core import _serialized_global_config_write
from .store_core import _write_json

def get_model_config(status: str = "adapted") -> dict[str, Any]:
    from .settings_loaders import load_model_settings

    return load_model_settings(status)


@_serialized_global_config_write
def save_model_config(payload: dict[str, Any]) -> dict[str, Any]:
    from .project_resource_revisions import _json_hash
    from .provider_models import _available_model_capabilities
    from .provider_models import _empty_model_config
    from .provider_models import _find_model
    from .provider_models import _normalize_model_config
    from .projects import _save_global_config
    from .settings_loaders import filter_model_capabilities_by_status
    from .settings_loaders import load_global_config
    config = load_global_config()
    incoming = payload.get("config") if isinstance(payload.get("config"), dict) else payload
    capabilities = _available_model_capabilities(config)
    current_model_config = _normalize_model_config(config.get("model_config", _empty_model_config()), capabilities)
    if payload.get("expectedConfigVersion") != _json_hash(current_model_config):
        raise ValueError("全局模型配置已变化，请刷新后重试")
    adapted = filter_model_capabilities_by_status(capabilities, "adapted")
    for section in ("image", "video", "agent", "text"):
        submitted = incoming.get(section) if isinstance(incoming, dict) else None
        if not isinstance(submitted, dict) or "model_id" not in submitted:
            continue
        submitted_id = str(submitted.get("model_id") or "").strip()
        current_id = str(current_model_config.get(section, {}).get("model_id") or "").strip()
        if submitted_id and submitted_id != current_id and not any(
            row.get("id") == submitted_id for row in adapted.get(section, [])
        ):
            raise ValueError(f"{section} 模型未适配或不可用，请重新选择")
    config["model_config"] = _normalize_model_config(
        _deep_merge(config.get("model_config", _empty_model_config()), incoming if isinstance(incoming, dict) else {}),
        capabilities,
    )
    model_config = config["model_config"]
    image_model = _find_model(model_config["image"]["model_id"], "image", capabilities) or {}
    video_model = _find_model(model_config["video"]["model_id"], "video", capabilities) or {}
    model_config["video"]["generate_audio"] = bool(video_model.get("audio", False))
    config["defaults"]["models"]["image"] = image_model.get("label") or model_config["image"]["model_id"]
    config["defaults"]["models"]["video"] = video_model.get("label") or model_config["video"]["model_id"]
    config["defaults"]["models"]["agent"] = model_config["agent"].get("model_id")
    config["defaults"]["models"]["text"] = model_config["text"].get("model_id")
    config["defaults"]["storyboard"]["image_model"] = image_model.get("label") or model_config["image"]["model_id"]
    config["defaults"]["storyboard"]["image_size"] = model_config["image"]["storyboard_resolution"]
    config["defaults"]["storyboard"]["image_output_format"] = model_config["image"]["image_output_format"]
    config["defaults"]["video"]["model"] = video_model.get("label") or model_config["video"]["model_id"]
    config["defaults"]["video"]["provider"] = video_model.get("provider_id") or "ark-seedance"
    config["defaults"]["video"]["resolution"] = model_config["video"]["resolution"]
    config["defaults"]["video"]["duration_seconds"] = model_config["video"]["duration_seconds"]
    config["defaults"]["video"]["generate_audio"] = model_config["video"]["generate_audio"]
    _save_global_config(config)
    return {"success": True, **get_model_config()}


def get_script_adaptation_templates() -> dict[str, Any]:
    from .settings_loaders import load_script_adaptation_templates
    return {"templates": load_script_adaptation_templates()}


def get_text_replacement_rules() -> dict[str, Any]:
    from .settings_loaders import load_text_replacement_rules
    return {"rules": load_text_replacement_rules()}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip() for line in re.split(r"\r?\n", value) if line.strip()]
    return []


def _custom_library_template_id(prefix: str, name: str | None = None) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", str(name or "").strip().lower()).strip("_")
    if not base or not re.match(r"^[a-z]", base):
        base = prefix
    base = base[:60].strip("_")
    return f"{base}_{uuid.uuid4().hex[:8]}"


def _normalize_replacement_rows(value: Any) -> list[dict[str, str]]:
    return _normalize_text_replacement_rules(value)


def save_script_adaptation_template(payload: dict[str, Any]) -> dict[str, Any]:
    from .projects import _find_template
    from .settings_loaders import load_script_adaptation_templates
    template = payload.get("template") if isinstance(payload.get("template"), dict) else payload
    if not isinstance(template, dict):
        raise ValueError("片段剧本策略模板数据无效")
    templates = load_script_adaptation_templates()
    template = dict(template)
    template_id = str(template.get("id") or "").strip()
    if not template_id:
        template_id = _custom_library_template_id("script_style", template.get("name"))
        template["id"] = template_id
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,79}", template_id):
        raise ValueError("模板 ID 必须是小写字母、数字和下划线")
    builtin_ids = {str(item.get("id")) for item in DEFAULT_SCRIPT_ADAPTATION_TEMPLATES}
    if template_id in builtin_ids:
        raise ValueError("内置片段剧本策略模板不能被覆盖")
    name = str(template.get("name") or "").strip()
    if not name:
        raise ValueError("模板标题不能为空")
    description = str(template.get("desc") or template.get("description") or "").strip()
    if not description:
        raise ValueError("模板描述不能为空")
    prompt = str(template.get("prompt") or "").strip()
    rules = _string_list(template.get("rules") or template.get("scriptRules") or template.get("script_rules"))
    if not prompt and not rules:
        raise ValueError("创作规则不能为空")
    existing = _find_template(template_id, templates)
    saved_template = {
        "id": template_id,
        "name": name,
        "desc": description,
        "description": description,
        "badge": str(template.get("badge") or "自定义").strip() or "自定义",
        "source": "user_generated",
        "prompt": prompt or "\n".join(rules),
        "rules": rules or _string_list(prompt),
        "recommended_use": str(template.get("recommended_use") or template.get("recommendedUse") or "").strip(),
        "version": int(template.get("version") or 1),
        "created_at": (existing or {}).get("created_at") or _now(),
        "updated_at": _now(),
    }
    next_templates = [item for item in templates if item.get("id") != template_id]
    next_templates.append(saved_template)
    _write_json(GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH, next_templates)
    return {"success": True, "template": saved_template, "templates": load_script_adaptation_templates()}


def delete_script_adaptation_template(template_id: str | None) -> dict[str, Any]:
    from .projects import _find_template
    from .settings_loaders import load_script_adaptation_templates
    template_id = str(template_id or "").strip()
    if not template_id:
        raise ValueError("片段剧本策略模板 ID 不能为空")
    templates = load_script_adaptation_templates()
    target = _find_template(template_id, templates)
    if not target:
        raise ValueError("片段剧本策略模板不存在")
    builtin_ids = {str(item.get("id")) for item in DEFAULT_SCRIPT_ADAPTATION_TEMPLATES}
    if template_id in builtin_ids or target.get("source") == "builtin":
        raise ValueError("内置片段剧本策略模板不能删除")
    next_templates = [item for item in templates if item.get("id") != template_id]
    _write_json(GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH, next_templates)
    return {"success": True, "templateId": template_id, "templates": load_script_adaptation_templates()}


def save_text_replacement_rules(payload: dict[str, Any]) -> dict[str, Any]:
    from .settings_loaders import load_text_replacement_rules
    data = payload if isinstance(payload, dict) else {}
    raw_rules = (
        data.get("rules")
        if "rules" in data
        else data.get("replacements")
        if "replacements" in data
        else data.get("items")
        if "items" in data
        else data.get("text")
    )
    rules = _normalize_replacement_rows(raw_rules)
    _write_json(GLOBAL_TEXT_REPLACEMENT_RULES_PATH, rules)
    return {"success": True, "rules": load_text_replacement_rules()}


__all__ = (
    'get_model_config', 'save_model_config',
    'get_script_adaptation_templates', 'get_text_replacement_rules',
    '_string_list',
    'save_script_adaptation_template', 'delete_script_adaptation_template',
    'save_text_replacement_rules',
)
