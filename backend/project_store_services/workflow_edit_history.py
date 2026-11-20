# -*- coding: utf-8 -*-
"""工作流领域实际实现。"""
from __future__ import annotations
from .canvas_ownership import VIDEO_TASK_NODE_TYPES

from pathlib import Path
from .canvas_store_database import card_dir
from .canvas_store_database import card_root
from .canvas_store_documents import write_canvas_projection_cache_v4
from .canvas_store_queries import episode_canvas_exists, read_canvas_card_record_v4
from .director_plan_contract import _normalize_multiline_text
from .store_core import _display_time
from .projects import _touch_project_meta
from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json
from .workflow_contract import _workflow_mutation_event_fields
from .workflow_planning_lifecycle import _safe_episode_id
from typing import Any
from utils.text_metrics import content_char_count
from utils.video_prompt_mentions import prompt_reference_labels
import copy
import traceback
import uuid


_NODE_EDIT_HISTORY_NODE_TYPES = {
    "source.text",
    "prompt.storyboard",
    "director.board",
    *VIDEO_TASK_NODE_TYPES,
}


_NODE_EDIT_HISTORY_SCHEMA_VERSION = 2


_NODE_EDIT_HISTORY_SAVE_REASONS = {
    "inline_storyboard_prompt_saved",
    "storyboard_detail_script_saved",
    "inline_storyboard_template_saved",
    "inline_director_plan_saved",
    "inline_source_text_saved",
    "independent_source_text_saved",
    "inline_generation_config_saved",
    "inline_node_edit_saved",
}


_NODE_EDIT_HISTORY_GENERATION_CONFIG_KEYS = {
    "modelId",
    "model_id",
    "providerId",
    "provider_id",
    "resolution",
    "aspectRatio",
    "replacementSubject",
    "size",
    "width",
    "height",
    "fps",
    "inputMode",
    "input_mode",
    "referenceMode",
    "reference_mode",
    "shotType",
    "shot_type",
    "cameraMotion",
    "camera_motion",
    "motionStrength",
    "motion_strength",
    "continuityMode",
    "continuity_mode",
    "continuityControl",
    "continuity_control",
}


_NODE_EDIT_HISTORY_DURATION_KEYS = (
    "durationSeconds",
)


def _node_edit_history_path(project_id: str, episode_id: str, node_id: str) -> Path:
    return card_dir(project_id, _safe_episode_id(episode_id), node_id) / "history" / "edit_history.json"


def _read_node_edit_history(project_id: str, episode_id: str, node_id: str = "") -> list[dict[str, Any]]:
    if not episode_canvas_exists(project_id, episode_id):
        return []
    node_id = str(node_id or "").strip()
    paths = (
        [_node_edit_history_path(project_id, episode_id, node_id)]
        if node_id
        else sorted(card_root(project_id, episode_id).glob("*/history/edit_history.json"))
    )
    items: list[dict[str, Any]] = []
    for path in paths:
        data = _read_json(path, {})
        if not isinstance(data, dict) or data.get("schemaVersion") != _NODE_EDIT_HISTORY_SCHEMA_VERSION:
            continue
        rows = data.get("items")
        if isinstance(rows, list):
            items.extend(copy.deepcopy(item) for item in rows if isinstance(item, dict))
    return items


def _write_node_edit_history(project_id: str, episode_id: str, node_id: str, items: list[dict[str, Any]]) -> None:
    retained = items[-500:]
    if len(items) > 500 and any(row.get("nodeType") == "director.board" for row in items):
        from .workflow_director_rework_records import _read_rework_records
        referenced_ids = {
            row["versionId"] for row in _read_rework_records(project_id, episode_id, node_id)
        }
        retained_ids = {str(row.get("id") or "") for row in retained} | referenced_ids
        retained = [row for row in items if str(row.get("id") or "") in retained_ids]
    _write_json(
        _node_edit_history_path(project_id, episode_id, node_id),
        {
            "schemaVersion": _NODE_EDIT_HISTORY_SCHEMA_VERSION,
            "episodeId": _safe_episode_id(episode_id),
            "nodeId": str(node_id or "").strip(),
            "updatedAt": _now(),
            "items": retained,
        },
    )


def _node_edit_history_allowed(node_type: str) -> bool:
    return str(node_type or "").strip() in _NODE_EDIT_HISTORY_NODE_TYPES


def _node_edit_history_save_reason_allowed(reason: str) -> bool:
    return str(reason or "").strip() in _NODE_EDIT_HISTORY_SAVE_REASONS


def _node_edit_history_scalar_value(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _node_edit_generation_config_content(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key in _NODE_EDIT_HISTORY_GENERATION_CONFIG_KEYS
        and _node_edit_history_scalar_value(item)
    }


_NODE_EDIT_MISSING = object()


_NODE_EDIT_HISTORY_FIELD_SPECS: dict[str, tuple[dict[str, Any], ...]] = {
    "source.text": (
        {"key": "sourceText", "title": "修改内容", "slot": "middle", "kind": "scalar", "aliases": ("sourceText",)},
    ),
    "prompt.storyboard": (
        {"key": "sourceFactText", "title": "原文事实", "slot": "middle", "kind": "scalar", "aliases": ("sourceFactText", "source_fact_text")},
        {"key": "cinematicStoryText", "title": "影视化剧本", "slot": "right", "kind": "scalar", "aliases": ("cinematicStoryText", "cinematic_story_text")},
        {"key": "scriptUserInstruction", "kind": "scalar", "aliases": ("scriptUserInstruction", "script_user_instruction")},
        {"key": "scriptTemplateId", "kind": "scalar", "aliases": ("scriptTemplateId",)},
        {"key": "narrativeMode", "kind": "scalar", "aliases": ("narrativeMode",)},
        {"key": "scriptTemplateLabel", "kind": "scalar", "aliases": ("scriptTemplateLabel",)},
    ),
    "director.board": (
        {"key": "directorPlan", "title": "分镜脚本", "slot": "middle", "kind": "scalar", "aliases": ("directorPlan",)},
        {"key": "directorPlanShots", "kind": "list", "aliases": ("directorPlanShots",)},
        {"key": "speakerRoster", "kind": "list", "aliases": ("speakerRoster",)},
        {"key": "directorRuleId", "kind": "scalar", "aliases": ("directorRuleId",)},
        {"key": "directorRuleSelectionMode", "kind": "scalar", "aliases": ("directorRuleSelectionMode",)},
        {"key": "storyboardTemplate", "kind": "scalar", "aliases": ("storyboardTemplate", "storyboard_template", "storyboardTemplateId", "storyboard_template_id", "template", "templateId")},
        {"key": "storyboardTemplateLabel", "kind": "scalar", "aliases": ("storyboardTemplateLabel", "storyboard_template_label", "templateLabel", "template_label")},
        {"key": "durationSeconds", "kind": "scalar", "aliases": ("durationSeconds", "duration_seconds")},
        {"key": "rhythmMultiplier", "kind": "scalar", "aliases": ("rhythmMultiplier",)},
        {"key": "speechBudgetNote", "kind": "scalar", "aliases": ("speechBudgetNote",)},
    ),
    "video.storyboard": (
        {"key": "finalVideoPrompt", "title": "视频提示词", "slot": "right", "kind": "scalar", "aliases": ("finalVideoPrompt",)},
        {"key": "soundPrompt", "title": "声音提示词", "slot": "right", "kind": "scalar", "aliases": ("soundPrompt",)},
        {"key": "promptBindings", "kind": "dict", "aliases": ("promptBindings",)},
        {"key": "voiceOverrides", "kind": "dict", "aliases": ("voiceOverrides",)},
        {"key": "usedSpeakerIds", "kind": "list", "aliases": ("usedSpeakerIds",)},
        {"key": "voiceDesign", "kind": "dict", "aliases": ("voiceDesign",)},
        {"key": "assetNameMap", "kind": "dict", "aliases": ("assetNameMap",)},
        {"key": "durationSeconds", "kind": "scalar", "aliases": ("durationSeconds",)},
    ),
}
for _video_task_type in VIDEO_TASK_NODE_TYPES:
    _NODE_EDIT_HISTORY_FIELD_SPECS[_video_task_type] = _NODE_EDIT_HISTORY_FIELD_SPECS["video.storyboard"]


def _node_edit_history_sources(content: dict[str, Any], node_type: str) -> list[dict[str, Any]]:
    if node_type in VIDEO_TASK_NODE_TYPES:
        card = content.get("videoTaskCard")
        return [content, card] if isinstance(card, dict) else [content]
    if node_type == "director.board":
        return [content]
    prompt = content.get("prompt") if isinstance(content.get("prompt"), dict) else {}
    card_state = content.get("cardState") if isinstance(content.get("cardState"), dict) else {}
    task_card = content.get("storyboardTaskCard") if isinstance(content.get("storyboardTaskCard"), dict) else {}
    return [content, prompt, task_card, card_state]


def _node_edit_history_first_present(sources: list[dict[str, Any]], *keys: str) -> tuple[Any, bool]:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            if key in source:
                return copy.deepcopy(source.get(key)), True
    return None, False


def _node_edit_history_extract_content(node_type: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    content: dict[str, Any] = {}
    sources = _node_edit_history_sources(value, node_type)
    for spec in _NODE_EDIT_HISTORY_FIELD_SPECS.get(str(node_type or "").strip(), ()):
        found, present = _node_edit_history_first_present(sources, *spec["aliases"])
        if not present:
            continue
        if spec.get("kind") == "list":
            if isinstance(found, list):
                content[str(spec["key"])] = copy.deepcopy(found)
        elif spec.get("kind") == "dict":
            if isinstance(found, dict):
                content[str(spec["key"])] = copy.deepcopy(found)
        elif _node_edit_history_scalar_value(found):
            if str(spec["key"]) == "scriptUserInstruction":
                normalized_instruction = _normalize_multiline_text(found)
                if not normalized_instruction:
                    continue
                content[str(spec["key"])] = normalized_instruction
                continue
            content[str(spec["key"])] = copy.deepcopy(found)
    generation_config = _node_edit_generation_config_content(value.get("generationConfig"))
    if node_type in {"director.board", *VIDEO_TASK_NODE_TYPES}:
        # Explicit defaults let restoring a version clear later selections.
        for key, aliases in (
            ("modelId", ("model_id",)),
            ("providerId", ("provider_id",)),
            ("resolution", ("size",)),
        ):
            if key not in generation_config:
                generation_config[key] = next((generation_config[alias] for alias in aliases if alias in generation_config), None)
            for alias in aliases:
                generation_config.pop(alias, None)
        content.setdefault("durationSeconds", None)
    if node_type == "video.character_replace":
        generation_config.pop("aspectRatio", None)
        generation_config.setdefault("replacementSubject", "person")
    if node_type in VIDEO_TASK_NODE_TYPES:
        content.setdefault("finalVideoPrompt", "")
        content.setdefault("soundPrompt", "")
        # Voice identities belong to the prompt version; media still follows current assets.
        design = content.get("voiceDesign") or {}
        speakers = [row for row in design.get("speakers") or [] if isinstance(row, dict) and isinstance(row.get("speakerId"), str)]
        used = content.get("usedSpeakerIds", [row["speakerId"] for row in speakers])
        content["usedSpeakerIds"] = list(dict.fromkeys(key for key in used if isinstance(key, str) and key))
        used_ids = set(content["usedSpeakerIds"])
        content["voiceDesign"] = {"speakers": [row for row in speakers if row["speakerId"] in used_ids]}
        names = content.get("assetNameMap") or {}
        content["assetNameMap"] = {key: name for key, name in names.items() if f"asset:{key}" in used_ids}
        # Preserve task-owned voice choices and audio with this prompt version.
        overrides = {key: value for key, value in (content.get("voiceOverrides") or {}).items()
                     if isinstance(value, dict) and (value.get("mode") != "auto"
                                                    or value.get("displayName") or "referenceAudio" in value
                                                    or "voiceStyle" in value)}
        content["voiceOverrides"] = overrides
        labels = prompt_reference_labels(str(content["finalVideoPrompt"] or ""), str(content.get("soundPrompt") or ""))
        bindings = content.get("promptBindings", {})
        content["promptBindings"] = {label: bindings.get(label, "") for label in labels}
    elif node_type == "director.board":
        for key in ("directorPlan", "directorRuleId", "storyboardTemplate", "storyboardTemplateLabel"):
            content.setdefault(key, "")
        content.setdefault("directorRuleSelectionMode", "auto")
        content.setdefault("directorPlanShots", [])
        content.setdefault("speakerRoster", [])
        content.setdefault("rhythmMultiplier", None)
        content.setdefault("speechBudgetNote", "")
    if generation_config:
        content["generationConfig"] = generation_config
    return content


def _node_edit_history_filtered_content(node_type: str, value: Any, *keys: str) -> dict[str, Any]:
    content = _node_edit_history_extract_content(node_type, value)
    sources = _node_edit_history_sources(value, node_type) if isinstance(value, dict) else []
    present_keys = {
        spec["key"] for spec in _NODE_EDIT_HISTORY_FIELD_SPECS.get(node_type, ())
        if _node_edit_history_first_present(sources, *spec["aliases"])[1]
    }
    return {key: copy.deepcopy(content[key]) for key in keys if key in content and key in present_keys}


def _node_edit_storyboard_template_content(value: Any) -> dict[str, Any]:
    return _node_edit_history_filtered_content(
        "director.board",
        value,
        "storyboardTemplate",
        "storyboardTemplateLabel",
    )


def _node_edit_storyboard_text_content(value: Any) -> dict[str, Any]:
    return _node_edit_history_filtered_content(
        "prompt.storyboard",
        value,
        "sourceFactText",
        "cinematicStoryText",
        "scriptUserInstruction",
        "scriptTemplateId",
        "narrativeMode",
        "scriptTemplateLabel",
    )


def _node_edit_director_text_content(value: Any) -> dict[str, Any]:
    return _node_edit_history_filtered_content(
        "director.board",
        value,
        "directorPlan",
        "directorPlanShots",
        "speakerRoster",
        "directorRuleId",
        "directorRuleSelectionMode",
        "storyboardTemplate",
        "storyboardTemplateLabel",
        "durationSeconds",
        "rhythmMultiplier",
        "speechBudgetNote",
    )


def _node_edit_content_from_node(node: dict[str, Any]) -> dict[str, Any]:
    node_type = str(node.get("type") or "").strip()
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return _node_edit_history_extract_content(node_type, data)


def _node_edit_history_subject(node_type: str) -> str:
    normalized = str(node_type or "").strip()
    if normalized == "prompt.storyboard":
        return "script"
    if normalized == "director.board":
        return "director"
    if normalized == "source.text":
        return "source"
    if normalized in VIDEO_TASK_NODE_TYPES:
        return "video"
    return "node"


def _node_edit_history_source(reason: str, fallback: Any = "") -> str:
    explicit = str(fallback or "").strip().lower()
    if explicit in {"user", "model", "restore", "system"}:
        return explicit
    normalized = str(reason or "").strip().lower()
    if normalized == "video_prompt_optimized":
        return "model"
    if any(token in normalized for token in ("generated", "revised", "recommended", "analyzed")):
        return "model"
    return "user"


_NODE_EDIT_HISTORY_GENERATION_PARAMETER_SPECS = (
    ("modelId", "模型", ("modelId", "model_id")),
    ("providerId", "供应商", ("providerId", "provider_id")),
    ("resolution", "分辨率", ("resolution",)),
    ("aspectRatio", "画幅", ("aspectRatio",)),
    ("replacementSubject", "替换对象", ("replacementSubject",)),
    ("size", "尺寸", ("size",)),
    ("width", "宽度", ("width",)),
    ("height", "高度", ("height",)),
    ("fps", "帧率", ("fps",)),
    ("inputMode", "输入模式", ("inputMode", "input_mode")),
    ("referenceMode", "参考模式", ("referenceMode", "reference_mode")),
    ("shotType", "镜头类型", ("shotType", "shot_type")),
    ("cameraMotion", "运镜", ("cameraMotion", "camera_motion")),
    ("motionStrength", "运动强度", ("motionStrength", "motion_strength")),
    ("continuityMode", "连续性", ("continuityMode", "continuity_mode")),
    ("continuityControl", "连续性控制", ("continuityControl", "continuity_control")),
)


_NODE_EDIT_HISTORY_PARAMETER_SPECS = {
    "prompt.storyboard": (
        ("narrativeMode", "叙事模式", "", "剧情演绎"),
        ("scriptTemplateId", "创作策略", "scriptTemplateLabel", "标准忠实影视化"),
    ),
    "director.board": (
        ("directorRuleId", "导演规则", "", "未选择"),
        ("storyboardTemplate", "版式", "storyboardTemplateLabel", "跟随推荐"),
        ("durationSeconds", "时长", "", ""),
    ),
    "video.storyboard": (
        ("durationSeconds", "时长", "", ""),
    ),
}
for _video_task_type in VIDEO_TASK_NODE_TYPES:
    _NODE_EDIT_HISTORY_PARAMETER_SPECS[_video_task_type] = _NODE_EDIT_HISTORY_PARAMETER_SPECS["video.storyboard"]


def _node_edit_history_text_field(key: str, title: str, value: Any, present: bool) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "text": str(value or "") if value is not None else "",
        "present": bool(present),
    }


def _node_edit_history_parameter_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return f"{value:g}" if isinstance(value, float) else str(value)
    return str(value or "").strip()


def _node_edit_history_parameter_entry(
    key: str,
    label: str,
    value: Any,
    display_value: Any = None,
    *,
    scope: str = "data",
) -> dict[str, Any]:
    display = _node_edit_history_parameter_value(display_value)
    raw_display = _node_edit_history_parameter_value(value)
    return {
        "key": key,
        "label": label,
        "value": copy.deepcopy(value),
        "displayValue": display or raw_display,
        "scope": scope,
    }


def _node_edit_history_config_display_value(key: str, value: Any) -> str:
    text = _node_edit_history_parameter_value(value)
    if not text:
        if key in {"inputMode", "referenceMode"}:
            return "自动"
        if key in {"modelId", "providerId", "resolution", "size"}:
            return "跟随全局设置"
        return "跟随项目设置"
    if key in {"inputMode", "referenceMode"}:
        return {
            "storyboard_reference_image": "分镜图 + 提示词",
            "text_to_video_draft": "文生草稿",
        }.get(text, text)
    return text


def _node_edit_history_generation_config_parameters(content: dict[str, Any]) -> list[dict[str, Any]]:
    config = _node_edit_generation_config_content(content.get("generationConfig"))
    parameters: list[dict[str, Any]] = []
    for canonical_key, label, keys in _NODE_EDIT_HISTORY_GENERATION_PARAMETER_SPECS:
        value, present = _node_edit_history_first_present([config], *keys)
        if present:
            parameters.append(
                _node_edit_history_parameter_entry(
                    canonical_key,
                    label,
                    value,
                    _node_edit_history_config_display_value(canonical_key, value),
                    scope="generationConfig",
                )
            )
    return parameters


def _node_edit_history_parameters(node_type: str, content: dict[str, Any]) -> list[dict[str, Any]]:
    normalized_type = str(node_type or "").strip()
    content = _node_edit_history_extract_content(normalized_type, content)
    parameters: list[dict[str, Any]] = []
    for key, label, display_key, empty_display in _NODE_EDIT_HISTORY_PARAMETER_SPECS.get(normalized_type, ()):
        if key not in content and (not display_key or display_key not in content):
            continue
        value = content.get(key)
        display_value = content.get(display_key) if display_key else None
        if key == "durationSeconds":
            display_text = _node_edit_history_parameter_value(value)
            display_value = (
                "未设置"
                if value is None
                else f"{display_text}s"
                if display_text and display_text.replace(".", "", 1).isdigit()
                else display_text
            )
        else:
            display_value = display_value or value or empty_display
        parameters.append(
            _node_edit_history_parameter_entry(key, label, value, display_value)
        )
    parameters.extend(_node_edit_history_generation_config_parameters(content))
    return parameters


def _node_edit_history_version_field(
    node_type: str,
    content: dict[str, Any],
    slot: str,
    fallback_key: str,
    fallback_title: str,
) -> dict[str, Any]:
    for spec in _NODE_EDIT_HISTORY_FIELD_SPECS.get(str(node_type or "").strip(), ()):
        if spec.get("slot") != slot:
            continue
        key = str(spec["key"])
        return _node_edit_history_text_field(
            key,
            str(spec.get("title") or fallback_title),
            content.get(key),
            key in content,
        )
    return _node_edit_history_text_field(fallback_key, fallback_title, "", False)


def _node_edit_history_version(node_type: str, content: dict[str, Any]) -> dict[str, Any]:
    normalized_type = str(node_type or "").strip()
    content = _node_edit_history_extract_content(normalized_type, content)
    return {
        "middle": _node_edit_history_version_field(normalized_type, content, "middle", "sourceText", "修改内容"),
        "right": _node_edit_history_version_field(normalized_type, content, "right", "notes", "提示词记录"),
        "parameters": _node_edit_history_parameters(node_type, content),
    }


def _node_edit_history_restore_patch(node_type: str, content: dict[str, Any]) -> dict[str, Any]:
    normalized_type = str(node_type or "").strip()
    content = _node_edit_history_extract_content(normalized_type, content)
    data_patch: dict[str, Any] = {}
    for spec in _NODE_EDIT_HISTORY_FIELD_SPECS.get(normalized_type, ()):
        key = str(spec["key"])
        if key in content:
            data_patch[key] = copy.deepcopy(content[key])
    restore_patch: dict[str, Any] = {"data": data_patch}
    generation_config = _node_edit_generation_config_content(content.get("generationConfig"))
    if generation_config:
        restore_patch["generationConfig"] = generation_config
        if normalized_type in {"director.board", *VIDEO_TASK_NODE_TYPES}:
            for key in ("model_id", "provider_id", "size"):
                restore_patch["generationConfig"].setdefault(key, None)
            if normalized_type == "director.board":
                restore_patch["generationConfig"]["size"] = generation_config.get("resolution")
    return restore_patch


def _build_node_edit_history_item(
    node_id: str,
    node_type: str,
    title: Any,
    content: dict[str, Any],
    reason: str,
    *,
    source: Any = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _now()
    safe_content = _node_edit_history_extract_content(node_type, content)
    return {
        "id": f"node-edit-{uuid.uuid4().hex[:10]}",
        "schemaVersion": _NODE_EDIT_HISTORY_SCHEMA_VERSION,
        "nodeId": node_id,
        "nodeType": node_type,
        "title": str(title or node_id),
        "summary": _node_edit_history_summary(safe_content),
        "createdAt": now,
        "displayTime": _display_time(now),
        "reason": str(reason or "node_edit_saved"),
        "source": _node_edit_history_source(reason, source),
        "subject": _node_edit_history_subject(node_type),
        "version": _node_edit_history_version(node_type, safe_content),
        "restorePatch": _node_edit_history_restore_patch(node_type, safe_content),
        "meta": copy.deepcopy(meta) if isinstance(meta, dict) else {},
    }


def _node_edit_history_summary(content: dict[str, Any]) -> str:
    if "sourceText" in content:
        return f"原文 {content_char_count(content.get('sourceText'))} 字"
    labels: list[str] = []
    if "sourceFactText" in content:
        labels.append("原文事实")
    if "scriptUserInstruction" in content:
        labels.append("用户补充")
    if "cinematicStoryText" in content:
        labels.append("影视化剧本")
    if "directorPlan" in content:
        labels.append("分镜脚本")
    if "finalVideoPrompt" in content:
        labels.append("视频提示词")
    if "directorRuleId" in content:
        labels.append("导演规则")
    if "scriptTemplateId" in content or "scriptTemplateLabel" in content:
        labels.append("剧本规则")
    if "prompt" in content or "prompts" in content:
        if not any(label in labels for label in ("原文事实", "影视化剧本")):
            labels.append("提示词")
    if "storyboardTemplate" in content or "storyboardTemplateLabel" in content:
        labels.append("版式")
    if "generationConfig" in content or any(key in content for key in _NODE_EDIT_HISTORY_DURATION_KEYS):
        labels.append("参数")
    return "、".join(labels) or "修改内容"


def _node_edit_history_summary_from_version(version: dict[str, Any]) -> str:
    labels: list[str] = []
    for key in ("middle", "right"):
        field = version.get(key) if isinstance(version.get(key), dict) else {}
        if not field.get("present"):
            continue
        label = str(field.get("title") or "").strip()
        if label and label not in labels:
            labels.append(label)
    parameters = version.get("parameters")
    if isinstance(parameters, list) and parameters and "参数" not in labels:
        labels.append("参数")
    return "、".join(labels) or "修改内容"


def record_node_edit_history(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    node_type = str(payload.get("nodeType") or payload.get("node_type") or "").strip()
    if not node_id:
        raise ValueError("缺少 nodeId")
    if not episode_canvas_exists(project_id, episode_id):
        return {"success": True, "skipped": True, "reason": "missing_canvas"}
    if not _node_edit_history_allowed(node_type):
        return {"success": True, "skipped": True, "reason": "unsupported_node_type"}
    content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
    content = _node_edit_history_extract_content(node_type, content)
    if not content:
        return {"success": True, "skipped": True, "reason": "empty_content"}
    reason = str(payload.get("reason") or "node_edit_saved")
    item = _build_node_edit_history_item(
        node_id,
        node_type,
        payload.get("title") or node_id,
        content,
        reason,
        source=payload.get("source"),
        meta=payload.get("meta") if isinstance(payload.get("meta"), dict) else None,
    )
    items: list[dict[str, Any]] = []
    for row in _read_node_edit_history(project_id, episode_id, node_id):
        safe_row = _sanitize_node_edit_history_item(row)
        if safe_row is not None:
            items.append(safe_row)
    items.append(item)
    _write_node_edit_history(project_id, episode_id, node_id, items)
    return {"success": True, "episodeId": episode_id, "item": item, "changedResources": ["node_edit_history"]}


def record_workflow_node_edit_history(project_id: str, episode_id: str, node: dict[str, Any], reason: str = "node_edit_saved") -> dict[str, Any]:
    node_type = str(node.get("type") or "").strip()
    if not _node_edit_history_allowed(node_type):
        return {"success": True, "skipped": True, "reason": "unsupported_node_type"}
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return record_node_edit_history(
        project_id,
        episode_id,
        {
            "nodeId": str(node.get("id") or ""),
            "nodeType": node_type,
            "title": data.get("title") or node.get("id"),
            "content": _node_edit_content_from_node(node),
            "reason": reason,
        },
    )


def _video_prompt_history_content(value: dict[str, Any]) -> dict[str, Any]:
    content = _node_edit_history_extract_content("video.storyboard", value)
    content["finalVideoPrompt"] = str(content.get("finalVideoPrompt") or "")
    return content


def record_video_prompt_edit_history(
    project_id: str,
    episode_id: str,
    node: dict[str, Any],
    previous_node: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    try:
        current = _video_prompt_history_content(node.get("data") or {})
        previous = _video_prompt_history_content(previous_node.get("data") or {})
        if current == previous:
            return {"success": True, "skipped": True}
        node_id = str(node.get("id") or "")
        result = record_node_edit_history(project_id, episode_id, {
            "nodeId": node_id,
            "nodeType": str(node.get("type") or "video.storyboard"),
            "title": (node.get("data") or {}).get("title") or node_id,
            "content": current,
            "reason": reason,
        })
        return {**result, "items": [result["item"]] if result.get("item") else []}
    except Exception:
        print(traceback.format_exc(), flush=True)
        return {"success": False, "skipped": True, "error": "视频提示词已保存，但修改记录写入失败"}


def _sanitize_node_edit_history_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    if item.get("schemaVersion") != _NODE_EDIT_HISTORY_SCHEMA_VERSION:
        return None
    version_id = str(item.get("id") or "").strip()
    node_id = str(item.get("nodeId") or "").strip()
    node_type = str(item.get("nodeType") or "").strip()
    version = item.get("version")
    restore_patch = item.get("restorePatch")
    if (
        not version_id
        or not node_id
        or not _node_edit_history_allowed(node_type)
        or not isinstance(version, dict)
        or not isinstance(restore_patch, dict)
    ):
        return None

    if node_type in {"director.board", *VIDEO_TASK_NODE_TYPES}:
        data = restore_patch.get("data")
        config = restore_patch.get("generationConfig")
        specs = _NODE_EDIT_HISTORY_FIELD_SPECS[node_type]
        if node_type == "director.board" and isinstance(data, dict) and "directorScriptSource" in data:
            # Retain histories written during the retired source-stamp experiment.
            # Stage regeneration is optional; source provenance is not a gate.
            restore_patch = copy.deepcopy(restore_patch)
            data = restore_patch["data"]
            data.pop("directorScriptSource")
        if (
            not isinstance(data, dict)
            or set(data) != {spec["key"] for spec in specs}
            or not isinstance(config, dict)
            or not {"modelId", "providerId", "resolution"}.issubset(config)
            or config != _node_edit_generation_config_content(config)
        ):
            return None
        for spec in specs:
            value = data[spec["key"]]
            kind = spec["kind"]
            if (
                (kind == "list" and not isinstance(value, list))
                or (kind == "dict" and not isinstance(value, dict))
                or (kind == "scalar" and not _node_edit_history_scalar_value(value))
            ):
                return None
        text_key = "directorPlan" if node_type == "director.board" else "finalVideoPrompt"
        if not isinstance(data[text_key], str):
            return None

    safe_item = {key: copy.deepcopy(item[key]) for key in (
        "id", "schemaVersion", "nodeId", "nodeType", "title", "summary", "createdAt",
        "displayTime", "reason", "source", "subject", "version", "restorePatch", "meta",
    ) if key in item}
    safe_item["schemaVersion"] = _NODE_EDIT_HISTORY_SCHEMA_VERSION
    safe_item["id"] = version_id
    safe_item["nodeId"] = node_id
    safe_item["nodeType"] = node_type
    safe_item["title"] = str(safe_item.get("title") or node_id)
    safe_item["version"] = copy.deepcopy(version)
    safe_item["restorePatch"] = copy.deepcopy(restore_patch)
    if node_type == "video.character_replace":
        content = {
            **restore_patch["data"],
            "generationConfig": restore_patch["generationConfig"],
        }
        safe_item["version"] = _node_edit_history_version(node_type, content)
        safe_item["restorePatch"] = _node_edit_history_restore_patch(node_type, content)
    safe_item["subject"] = str(safe_item.get("subject") or _node_edit_history_subject(node_type))
    safe_item["source"] = _node_edit_history_source(str(safe_item.get("reason") or ""), safe_item.get("source"))
    safe_item["meta"] = copy.deepcopy(safe_item.get("meta")) if isinstance(safe_item.get("meta"), dict) else {}
    safe_item["summary"] = str(safe_item.get("summary") or "").strip() or _node_edit_history_summary_from_version(version)
    return safe_item


def list_node_edit_history(project_id: str, episode_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    items = [item for item in _read_node_edit_history(project_id, episode_id, node_id) if isinstance(item, dict)]
    if node_id:
        items = [item for item in items if str(item.get("nodeId") or "") == node_id]
    items = sorted(reversed(items), key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    sanitized_items: list[dict[str, Any]] = []
    for item in items:
        safe_item = _sanitize_node_edit_history_item(item)
        if safe_item is not None:
            sanitized_items.append(safe_item)
    result = {"success": True, "episodeId": episode_id, "items": sanitized_items}
    if node_id and any(item["nodeType"] in {"director.board", *VIDEO_TASK_NODE_TYPES} for item in sanitized_items):
        node = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
        node_type = node.get("type")
        current = _node_edit_content_from_node(node)
        current["generationConfig"] = {key: value for key, value in current.get("generationConfig", {}).items() if value is not None}
        result["activeId"] = ""
        for item in sanitized_items:
            if item["nodeType"] != node_type:
                continue
            snapshot = _node_edit_history_extract_content(node_type, {
                **item["restorePatch"].get("data", {}),
                "generationConfig": item["restorePatch"].get("generationConfig", {}),
            })
            snapshot["generationConfig"] = {key: value for key, value in snapshot.get("generationConfig", {}).items() if value is not None}
            if snapshot == current:
                result["activeId"] = item["id"]
                break
    return result


def delete_node_edit_history(project_id: str, episode_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    version_id = str(payload.get("versionId") or payload.get("version_id") or payload.get("id") or "").strip()
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    if not version_id:
        raise ValueError("缺少 versionId")
    items = _read_node_edit_history(project_id, episode_id, node_id)
    deleted_item = next(
        (
            item
            for item in items
            if isinstance(item, dict)
            and str(item.get("id") or "") == version_id
            and (not node_id or str(item.get("nodeId") or "") == node_id)
        ),
        None,
    )
    if not deleted_item:
        raise FileNotFoundError("修改记录不存在")
    target_node_id = node_id or str(deleted_item.get("nodeId") or "").strip()
    if not target_node_id:
        raise ValueError("修改记录缺少 nodeId")
    if deleted_item.get("nodeType") == "director.board":
        from .workflow_director_rework_records import _read_rework_records
        if any(row["versionId"] == version_id for row in _read_rework_records(project_id, episode_id, target_node_id)):
            raise ValueError("该修改版本仍被返工记录引用，请先删除关联的返工记录")
    next_items: list[dict[str, Any]] = []
    for item in _read_node_edit_history(project_id, episode_id, target_node_id):
        if not isinstance(item, dict) or str(item.get("id") or "") == version_id:
            continue
        safe_item = _sanitize_node_edit_history_item(item)
        if safe_item is not None:
            next_items.append(safe_item)
    _write_node_edit_history(project_id, episode_id, target_node_id, next_items)
    save_result = write_canvas_projection_cache_v4(
        project_id,
        episode_id,
        f"node:{target_node_id}:edit_history",
        "node_edit_history",
        {
            "nodeId": target_node_id,
            "items": copy.deepcopy(next_items),
            "deletedVersionId": version_id,
            "updatedAt": _now(),
        },
        record_op=True,
        changed_resources=["canvas_projection", "node_edit_history"],
    )
    _touch_project_meta(project_id)
    mutation_fields = _workflow_mutation_event_fields(
        save_result,
        ["canvas_projection", "node_edit_history"],
    )
    return {
        "success": True,
        "episodeId": episode_id,
        "nodeId": node_id or str(deleted_item.get("nodeId") or ""),
        "versionId": version_id,
        "deleted": True,
        "projection": {
            "id": f"node:{target_node_id}:edit_history",
            "key": f"node:{target_node_id}:edit_history",
            "type": "node_edit_history",
            "payload": {
                "nodeId": target_node_id,
                "items": copy.deepcopy(next_items),
                "deletedVersionId": version_id,
            },
        },
        "workflowVersion": save_result.get("workflowVersion"),
        **mutation_fields,
        "projectChanged": True,
    }
