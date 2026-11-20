# -*- coding: utf-8 -*-
"""Access to local director-rule documents and user editable overrides."""

from __future__ import annotations

from .director_plan_contract import (
    _normalize_multiline_text,
)
from .source_text_store import _compact_text
from typing import (
    Any,
)

import os
from pathlib import Path

from .catalogs import GLOBAL_DIR
from .store_core import _now, _read_json, _write_json, ensure_store


_BACKEND_ROOT = Path(os.getcwd()).resolve()
_DIRECTOR_RULES_ROOT = _BACKEND_ROOT / "agent_ops" / "director_rules"
GLOBAL_DIRECTOR_RULE_OVERRIDES_PATH = GLOBAL_DIR / "director_rule_overrides.json"
_TEXT_EXTENSIONS = {".md", ".txt", ".json"}
_DEFAULT_MAX_CHARS = 8000
_MAX_CHARS_LIMIT = 24000
_DEFAULT_MAX_MATCHES = 30
_MAX_MATCHES_LIMIT = 80
_DIRECTOR_RULE_OVERRIDE_SCHEMA = "ai-video.director-rule-overrides.v1"
_SELECTABLE_DIRECTOR_RULE_PRESETS: tuple[dict[str, str], ...] = (
    {"ruleId": "dialogue_power", "file": "techniques-dialogue-power.md"},
    {"ruleId": "action_impact", "file": "techniques-action-impact.md"},
    {"ruleId": "suspense_presence", "file": "techniques-suspense-presence.md"},
    {"ruleId": "intimacy_emotion", "file": "techniques-intimacy-emotion.md"},
    {"ruleId": "reveal_subjective", "file": "techniques-reveal-subjective.md"},
    {"ruleId": "motion_transition", "file": "techniques-motion-transition.md"},
    {"ruleId": "environment_symbol", "file": "techniques-environment-symbol.md"},
    {"ruleId": "scale_montage", "file": "techniques-scale-montage.md"},
    {"ruleId": "character_entrance", "file": "techniques-character-entrance.md"},
    {"ruleId": "transformation_power", "file": "techniques-transformation-power.md"},
)
_RULE_ID_TO_FILE = {row["ruleId"]: row["file"] for row in _SELECTABLE_DIRECTOR_RULE_PRESETS}
_SELECTABLE_DIRECTOR_RULE_FILES = {row["file"] for row in _SELECTABLE_DIRECTOR_RULE_PRESETS}


def _clamp_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 100) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _safe_rule_path(value: Any) -> Path:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("缺少导演规则文件路径")
    candidate = (_DIRECTOR_RULES_ROOT / raw).resolve()
    root = _DIRECTOR_RULES_ROOT.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("导演规则路径必须位于 agent_ops/director_rules 内")
    if candidate.suffix.lower() not in _TEXT_EXTENSIONS:
        raise ValueError("导演规则只允许读取文本文件")
    if not candidate.is_file():
        raise FileNotFoundError(f"未找到导演规则文件：{raw}")
    return candidate


def _relative_rule_path(path: Path) -> str:
    return path.resolve().relative_to(_DIRECTOR_RULES_ROOT.resolve()).as_posix()


def _read_text(path: Path, max_chars: int | None = None) -> tuple[str, bool]:
    text = path.read_text(encoding="utf-8")
    limit = _clamp_int(max_chars, _DEFAULT_MAX_CHARS, maximum=_MAX_CHARS_LIMIT) if max_chars is not None else _DEFAULT_MAX_CHARS
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip(), True


def _truncate_text(text: Any, max_chars: int) -> tuple[str, bool]:
    value = str(text or "")
    limit = _clamp_int(max_chars, _DEFAULT_MAX_CHARS, maximum=_MAX_CHARS_LIMIT)
    if len(value) <= limit:
        return value, False
    return value[:limit].rstrip(), True


def _compact_line(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _rule_concrete_text(text: str) -> str:
    rows: list[str] = []
    skipped_title = False
    for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw_line.strip()
        if not skipped_title and stripped.startswith("# "):
            skipped_title = True
            continue
        if stripped.startswith(("规则标识：", "规则标识:", "一句话用途：", "一句话用途:")):
            continue
        if not rows and not stripped:
            continue
        rows.append(raw_line.rstrip())
    return "\n".join(rows).strip()


def _empty_overrides() -> dict[str, Any]:
    return {"schema": _DIRECTOR_RULE_OVERRIDE_SCHEMA, "rules": []}


def normalize_director_rule_identifier(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw not in _RULE_ID_TO_FILE:
        raise ValueError(f"不可用的导演规则标识：{raw}")
    return raw


def _require_director_rule_identifier(value: Any) -> str:
    rule_id = normalize_director_rule_identifier(value)
    if not rule_id:
        raise ValueError("缺少导演规则标识")
    return rule_id


def _selectable_rule_path(rule_id: str) -> Path:
    file_name = _RULE_ID_TO_FILE.get(rule_id)
    if not file_name:
        raise ValueError(f"不可用的导演规则标识：{rule_id}")
    return _safe_rule_path(file_name)


def _load_director_rule_overrides() -> dict[str, dict[str, Any]]:
    ensure_store()
    raw = _read_json(GLOBAL_DIRECTOR_RULE_OVERRIDES_PATH, _empty_overrides())
    rows = raw.get("rules") if isinstance(raw, dict) and isinstance(raw.get("rules"), list) else []
    overrides: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rule_id = _require_director_rule_identifier(row.get("id"))
        description = str(row.get("description") or "").strip()
        content = str(row.get("content") or "").strip()
        if not description and not content:
            continue
        overrides[rule_id] = {
            "id": rule_id,
            "description": description,
            "content": content,
            "updatedAt": str(row.get("updatedAt") or "").strip(),
        }
    return overrides


def _save_director_rule_overrides(overrides: dict[str, dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for preset in _SELECTABLE_DIRECTOR_RULE_PRESETS:
        rule_id = preset["ruleId"]
        override = overrides.get(rule_id)
        if not override:
            continue
        rows.append(
            {
                "id": rule_id,
                "description": str(override.get("description") or "").strip(),
                "content": str(override.get("content") or "").strip(),
                "updatedAt": str(override.get("updatedAt") or "").strip() or _now(),
            }
        )
    _write_json(
        GLOBAL_DIRECTOR_RULE_OVERRIDES_PATH,
        {"schema": _DIRECTOR_RULE_OVERRIDE_SCHEMA, "rules": rows},
    )


def _default_director_rule(rule_id: str) -> dict[str, Any]:
    path = _selectable_rule_path(rule_id)
    text, truncated = _read_text(path, _MAX_CHARS_LIMIT)
    summary = _rule_summary(path)
    description = str(summary.get("description") or "").strip()
    content = _rule_concrete_text(text)
    return {
        "id": rule_id,
        "ruleId": rule_id,
        "title": str(summary.get("title") or path.stem).strip(),
        "description": description,
        "content": content,
        "defaultDescription": description,
        "defaultContent": content,
        "size": path.stat().st_size,
        "truncated": truncated,
        "source": "builtin",
        "customized": False,
        "selectable": True,
    }


def _effective_director_rule(rule_id: str, overrides: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    rule = _default_director_rule(rule_id)
    override = (overrides if overrides is not None else _load_director_rule_overrides()).get(rule_id)
    if override:
        description = str(override.get("description") or "").strip()
        content = str(override.get("content") or "").strip()
        if description:
            rule["description"] = description
        if content:
            rule["content"] = content
        rule["source"] = "user_customized"
        rule["customized"] = True
        if override.get("updatedAt"):
            rule["updatedAt"] = override.get("updatedAt")
    return rule


def _director_rule_text(rule: dict[str, Any]) -> str:
    return (
        f"# {rule.get('title') or rule.get('ruleId')}\n\n"
        f"规则标识：{rule.get('ruleId') or rule.get('id')}\n\n"
        f"一句话用途：{rule.get('description') or ''}\n\n"
        f"{rule.get('content') or ''}"
    ).strip()


def _director_rule_summary_from_effective(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "ruleId": rule.get("ruleId") or rule.get("id"),
        "title": _compact_line(rule.get("title") or rule.get("ruleId")),
        "description": _compact_line(rule.get("description") or ""),
        "size": rule.get("size") or 0,
        "truncated": bool(rule.get("truncated")),
        "source": rule.get("source") or "builtin",
        "customized": bool(rule.get("customized")),
        "selectable": True,
    }


def _settings_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": rule.get("id") or rule.get("ruleId"),
        "title": rule.get("title") or "",
        "description": rule.get("description") or "",
        "content": rule.get("content") or "",
        "defaultDescription": rule.get("defaultDescription") or "",
        "defaultContent": rule.get("defaultContent") or "",
        "source": rule.get("source") or "builtin",
        "customized": bool(rule.get("customized")),
        "updatedAt": rule.get("updatedAt") or "",
    }


def _selectable_director_rules() -> list[dict[str, Any]]:
    overrides = _load_director_rule_overrides()
    return [
        _effective_director_rule(preset["ruleId"], overrides)
        for preset in _SELECTABLE_DIRECTOR_RULE_PRESETS
    ]


def _rule_summary(path: Path) -> dict[str, Any]:
    try:
        text, truncated = _read_text(path, 5000)
    except UnicodeDecodeError:
        text, truncated = "", False
    title = ""
    description = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") and not title:
            title = stripped.lstrip("#").strip()
            continue
        if stripped.startswith(("规则标识：", "规则标识:")):
            continue
        if stripped.startswith("一句话用途：") and not description:
            description = stripped.removeprefix("一句话用途：").strip()
            continue
        if stripped.startswith("一句话用途:") and not description:
            description = stripped.removeprefix("一句话用途:").strip()
            continue
        if not description and not stripped.startswith("#"):
            description = stripped
        if title and description:
            break
    summary = {
        "file": _relative_rule_path(path),
        "title": _compact_line(title or path.stem),
        "description": _compact_line(description),
        "size": path.stat().st_size,
        "truncated": truncated,
    }
    return summary


def list_director_rules_for_agent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    rules = [
        _director_rule_summary_from_effective(rule)
        for rule in _selectable_director_rules()
    ]
    return {
        "success": True,
        "rules": rules,
        "ruleCount": len(rules),
        "usage": "只返回可选导演规则标识和简介；按当前剧情选择 1 个规则标识，不要输出规则正文。",
    }


def search_director_rules_for_agent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    query = str(payload.get("query") or "").strip()
    max_matches = _clamp_int(
        payload.get("maxMatches") or payload.get("max_matches"),
        _DEFAULT_MAX_MATCHES,
        maximum=_MAX_MATCHES_LIMIT,
    )
    if not query:
        listed = list_director_rules_for_agent()
        listed["matches"] = []
        listed["matchCount"] = 0
        listed["message"] = "query 为空，已返回导演规则索引。"
        return listed

    folded_query = query.casefold()
    query_parts = [part for part in folded_query.split() if part]
    matches: list[dict[str, Any]] = []
    for rule in _selectable_director_rules():
        rule_id = str(rule.get("ruleId") or rule.get("id") or "").strip()
        text = _director_rule_text(rule)
        haystack = f"{rule_id}\n{text}".casefold()
        if folded_query not in haystack and not (query_parts and all(part in haystack for part in query_parts)):
            continue
        lines = text.splitlines()
        matched_line = ""
        line_number = 0
        for index, line in enumerate(lines, start=1):
            folded_line = line.casefold()
            if folded_query in folded_line or (query_parts and all(part in folded_line for part in query_parts)):
                matched_line = line
                line_number = index
                break
        if not matched_line:
            matched_line = str(rule.get("description") or rule_id)
        matches.append(
            {
                "ruleId": rule_id,
                "title": rule.get("title") or rule_id,
                "line": line_number,
                "preview": _compact_line(matched_line, 260),
            }
        )
        if len(matches) >= max_matches:
            break
    return {
        "success": True,
        "query": query,
        "matches": matches,
        "matchCount": len(matches),
        "usage": "搜索结果只用于定位可选导演规则；真正取用前应调用 read_director_rule 并传 ruleId。",
    }


def read_director_rule_for_agent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    rule_value = payload.get("ruleId")
    max_chars = _clamp_int(payload.get("maxChars") or payload.get("max_chars"), _DEFAULT_MAX_CHARS, maximum=_MAX_CHARS_LIMIT)
    try:
        rule_id = _require_director_rule_identifier(rule_value)
        rule = _effective_director_rule(rule_id)
        text, truncated = _truncate_text(_director_rule_text(rule), max_chars)
        concrete_text, concrete_truncated = _truncate_text(rule.get("content") or "", max_chars)
    except (FileNotFoundError, UnicodeDecodeError, ValueError) as exc:
        return {
            "success": False,
            "error": str(exc),
        }
    return {
        "success": True,
        "rule": _director_rule_summary_from_effective(rule),
        "text": text,
        "concreteText": concrete_text,
        "truncated": truncated or concrete_truncated,
        "maxChars": max_chars,
        "usage": "只把规则转化为服务当前影视化剧本的导演镜头方法；不得承担资产绑定、故事版绘制、供应商提示词适配或补写剧情事实。",
    }


def read_director_rule_document(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    file_value = payload.get("file")
    max_chars = _clamp_int(payload.get("maxChars") or payload.get("max_chars"), _DEFAULT_MAX_CHARS, maximum=_MAX_CHARS_LIMIT)
    try:
        path = _safe_rule_path(file_value)
        relative = _relative_rule_path(path)
        if relative in _SELECTABLE_DIRECTOR_RULE_FILES:
            raise ValueError("可选导演规则必须通过规则标识读取")
        text, truncated = _read_text(path, max_chars)
        concrete_text = _rule_concrete_text(text)
    except (FileNotFoundError, UnicodeDecodeError, ValueError) as exc:
        return {
            "success": False,
            "error": str(exc),
            "rulesRoot": "agent_ops/director_rules",
        }
    return {
        "success": True,
        "document": {
            "file": _relative_rule_path(path),
            "title": _rule_summary(path).get("title") or path.stem,
        },
        "text": text,
        "concreteText": concrete_text,
        "truncated": truncated,
        "maxChars": max_chars,
        "usage": "只把规则转化为服务当前影视化剧本的导演镜头方法；不得承担资产绑定、故事版绘制、供应商提示词适配或补写剧情事实。",
    }


def get_director_rules() -> dict[str, Any]:
    return {
        "success": True,
        "rules": [_settings_rule(rule) for rule in _selectable_director_rules()],
    }


def save_director_rule(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    rule_data = payload.get("rule") if isinstance(payload.get("rule"), dict) else payload
    rule_id = _require_director_rule_identifier(rule_data.get("id"))
    default_rule = _default_director_rule(rule_id)
    incoming_title = str(rule_data.get("title") or "").strip()
    if incoming_title and incoming_title != default_rule["title"]:
        raise ValueError("导演规则标题不可修改")
    description = str(rule_data.get("description") or "").strip()
    content = str(rule_data.get("content") or "").strip()
    if not description:
        raise ValueError("导演规则简介不能为空")
    if not content:
        raise ValueError("导演规则内容不能为空")
    overrides = _load_director_rule_overrides()
    if description == default_rule["defaultDescription"] and content == default_rule["defaultContent"]:
        overrides.pop(rule_id, None)
    else:
        overrides[rule_id] = {
            "id": rule_id,
            "description": description,
            "content": content,
            "updatedAt": _now(),
        }
    _save_director_rule_overrides(overrides)
    rule = _effective_director_rule(rule_id, _load_director_rule_overrides())
    return {
        "success": True,
        "rule": _settings_rule(rule),
        "rules": [_settings_rule(item) for item in _selectable_director_rules()],
    }


def reset_director_rule(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    rule_id = _require_director_rule_identifier(payload.get("id"))
    overrides = _load_director_rule_overrides()
    overrides.pop(rule_id, None)
    _save_director_rule_overrides(overrides)
    rule = _effective_director_rule(rule_id, _load_director_rule_overrides())
    return {
        "success": True,
        "rule": _settings_rule(rule),
        "rules": [_settings_rule(item) for item in _selectable_director_rules()],
    }


__all__ = [
    "GLOBAL_DIRECTOR_RULE_OVERRIDES_PATH",
    "normalize_director_rule_identifier",
    "list_director_rules_for_agent",
    "search_director_rules_for_agent",
    "read_director_rule_for_agent",
    "read_director_rule_document",
    "get_director_rules",
    "save_director_rule",
    "reset_director_rule",
]


def _script_director_rule_ids() -> set[str]:
    listed = list_director_rules_for_agent()
    rules = listed.get("rules") if isinstance(listed, dict) and isinstance(listed.get("rules"), list) else []
    rule_ids = {
        str(row.get("ruleId") or row.get("id") or "").strip()
        for row in rules
        if isinstance(row, dict)
        and row.get("selectable") is not False
        and str(row.get("ruleId") or row.get("id") or "").strip()
    }
    if not rule_ids:
        raise ValueError("导演规则库没有可用的场面导演规则")
    return rule_ids


def _normalize_director_rule_id(
    value: Any,
    *,
    source_label: str,
    require_non_empty: bool = False,
) -> str:
    rule_id = str(value or "").strip()
    if require_non_empty and not rule_id:
        raise ValueError(f"{source_label}为空")
    if not rule_id:
        return ""
    try:
        normalized_rule_id = normalize_director_rule_identifier(rule_id)
    except ValueError as exc:
        raise ValueError(f"{source_label}包含不可用的导演规则：{rule_id}") from exc
    if normalized_rule_id not in _script_director_rule_ids():
        raise ValueError(f"{source_label}包含不可用的导演规则：{rule_id}")
    return normalized_rule_id


def _director_rule_details_text(rule_refs: list[str]) -> str:
    rows: list[str] = []
    for rule_ref in rule_refs:
        rule_ref = str(rule_ref or "").strip()
        if not rule_ref:
            continue
        result = read_director_rule_for_agent({"ruleId": rule_ref, "maxChars": 24000})
        if not isinstance(result, dict) or not result.get("success"):
            raise ValueError(f"已选导演规则不存在或无法读取：{rule_ref}")
        text = _normalize_multiline_text(result.get("concreteText") or result.get("text"))
        if not text:
            raise ValueError(f"已选导演规则内容为空：{rule_ref}")
        rows.append(text)
    return "\n\n".join(rows)
