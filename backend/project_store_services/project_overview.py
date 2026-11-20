# -*- coding: utf-8 -*-
"""项目原文概览分析、更新与主题视觉上下文同步。"""
from __future__ import annotations

from .catalogs import PROJECT_OVERVIEW_STRUCTURED_SCHEMA
from .catalogs import _ensure_prompt_sentence_end
from .model_provider_config import _project_model_config
from .model_request_logs import STAGE_PROJECT_OVERVIEW_PROMPT
from .model_text_client import _model_json_or_none
from .project_overview_prompts import PROJECT_OVERVIEW_SYSTEM_PROMPT
from .project_overview_prompts import build_project_overview_prompt
from .project_resource_revisions import _resource_revision_value
from .provider_models import _normalize_overview_excerpt_chars
from .runtime_state import _raise_if_agent_cancelled
from .source_text_store import _compact_text
from .source_text_store import _is_novel_source
from .source_text_store import _read_source_content
from .source_text_store import _select_project_sources
from .source_text_store import _source_collection_text
from .source_text_store import list_sources
from .store_core import _now
from .store_core import _read_json
from .store_core import _serialized_project_config_write
from .store_core import _write_json
from typing import Any
from utils.text_metrics import content_char_count
import copy
import re


_PROJECT_OVERVIEW_TEXT_FIELDS: tuple[str, ...] = (
    "excerpt_summary",
    "genre_context",
    "theme_visual_context",
    "narrator_voice_design_prompt",
)


_PROJECT_OVERVIEW_FIELDS: tuple[str, ...] = _PROJECT_OVERVIEW_TEXT_FIELDS


def _overview_payload_value(data: dict[str, Any], snake_key: str) -> Any:
    from .projects import _snake_to_camel
    if snake_key in data:
        return data.get(snake_key)
    camel_key = _snake_to_camel(snake_key)
    if camel_key in data:
        return data.get(camel_key)
    return None


def _overview_narrator_voice_design_text(data: dict[str, Any]) -> str:
    if "narrator_voice_design" in data or "narratorVoiceDesign" in data:
        design = _overview_payload_value(data, "narrator_voice_design")
        if not isinstance(design, dict):
            return ""
        voice_base = str(
            design.get("voice_base") or design.get("voiceBase") or ""
        ).strip(" \t\r\n。，,；;")
        relation = str(
            design.get("narration_relation") or design.get("narrationRelation") or ""
        ).strip(" \t\r\n。，,；;")
        return "；".join(part for part in (voice_base, relation) if part)
    return str(_overview_payload_value(data, "narrator_voice_design_prompt") or "").strip()


def _normalize_project_overview_result(data: Any) -> dict[str, Any]:
    from .project_management import _normalize_visual_context
    source = data if isinstance(data, dict) else {}
    result: dict[str, Any] = {}
    for key in _PROJECT_OVERVIEW_TEXT_FIELDS:
        value = (
            _overview_narrator_voice_design_text(source)
            if key == "narrator_voice_design_prompt"
            else str(_overview_payload_value(source, key) or "").strip()
        )
        value = (
            _normalize_visual_context(value)
            if key == "theme_visual_context"
            else re.sub(r"\s+", " ", value)
        )
        if key == "excerpt_summary":
            value = _ensure_prompt_sentence_end(value)
        result[key] = value
    audio = _overview_payload_value(source, "narrator_reference_audio")
    result["narrator_reference_audio"] = copy.deepcopy(audio) if isinstance(audio, dict) else None
    return result


def _project_overview_summary_text(
    source_title: str,
    source_word_count: int,
    overview_result: dict[str, Any],
) -> str:
    summary_parts = [f"已导入{source_title or '小说文本'}"]
    if source_word_count > 0:
        summary_parts.append(f"约 {source_word_count:,} 字")
    genre_context = str(overview_result.get("genre_context") or "").strip()
    theme_visual_context = str(
        overview_result.get("theme_visual_context") or ""
    ).strip()
    if genre_context:
        summary_parts.append(f"题材语境：{_compact_text(genre_context, 80)}")
    if theme_visual_context:
        summary_parts.append(f"主题视觉：{theme_visual_context}")
    return _ensure_prompt_sentence_end("，".join(summary_parts))


def get_project_narrator_voice_profile(project_id: str) -> dict[str, Any]:
    """Return the persisted project-wide narrator identity for prompt assembly."""
    from .agent_sessions import _project_meta_path

    meta = _read_json(_project_meta_path(project_id), {})
    overview_analysis = meta.get("overview_analysis") if isinstance(meta.get("overview_analysis"), dict) else {}
    result = overview_analysis.get("result") if isinstance(overview_analysis.get("result"), dict) else {}
    prompt = str(_overview_payload_value(result, "narrator_voice_design_prompt") or "").strip()
    audio = result.get("narrator_reference_audio") or result.get("narratorReferenceAudio")
    has_reference_audio = isinstance(audio, dict) and bool(audio)
    return {
        "speakerId": "project:narrator",
        "displayName": "旁白",
        "voiceStyle": prompt,
        "voiceDesignPrompt": prompt,
        "referenceAudio": copy.deepcopy(audio) if has_reference_audio else None,
        "source": "reference_audio" if has_reference_audio else "voice_design_prompt",
    }


@_serialized_project_config_write
def _sync_project_theme_visual_context(
    project_id: str,
    meta: dict[str, Any],
    theme_visual_context: str,
) -> None:
    from .agent_sessions import _project_config_path
    from .project_management import _normalize_visual_context
    from .project_management import apply_theme_visual_context_to_config
    project_config_path = _project_config_path(project_id)
    project_config = _read_json(project_config_path, {})
    theme_visual_context = _normalize_visual_context(theme_visual_context)
    if theme_visual_context:
        meta["theme_visual_context"] = theme_visual_context
    else:
        meta.pop("theme_visual_context", None)
    if not isinstance(project_config, dict):
        return
    before = copy.deepcopy(project_config)
    if theme_visual_context:
        apply_theme_visual_context_to_config(project_config, theme_visual_context)
    else:
        project_config.pop("theme_visual_context", None)
    if project_config != before:
        project_config["revision"] = _resource_revision_value(before) + 1
        project_config["updatedAt"] = _now()
        _write_json(project_config_path, project_config)


def analyze_project_overview(
    project_id: str,
    source_id: str | None = None,
    excerpt_chars: Any | None = None,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    from .agent_sessions import _project_meta_path
    from .projects import _project_row
    _raise_if_agent_cancelled(session_id)
    source_items = _select_project_sources(project_id, source_id)
    primary = source_items[0]
    source_title, source_text, source_word_count = _source_collection_text(project_id, source_items)
    model_config = _project_model_config(project_id)[2]
    text_model_config = (
        model_config.get("text") if isinstance(model_config.get("text"), dict) else {}
    )
    overview_excerpt_chars = _normalize_overview_excerpt_chars(
        text_model_config.get("overview_excerpt_chars")
        if excerpt_chars is None
        else excerpt_chars
    )
    source_excerpt = source_text[:overview_excerpt_chars]
    prompt = build_project_overview_prompt(
        source_text=source_excerpt,
    )
    model_data, model_meta = _model_json_or_none(
        project_id,
        "text",
        "model_id",
        prompt,
        system_prompt=PROJECT_OVERVIEW_SYSTEM_PROMPT,
        temperature=0.4,
        max_tokens=4096,
        structured_schema=PROJECT_OVERVIEW_STRUCTURED_SCHEMA,
        model_request_log_stage=STAGE_PROJECT_OVERVIEW_PROMPT,
        model_request_log_context={
            "phase": "project-overview",
            "source": "analyze_project_overview",
        },
    )
    _raise_if_agent_cancelled(session_id)
    if not model_data:
        raise RuntimeError(model_meta.get("error") or "小说概述分析模型未返回可解析 JSON")
    model_data = _normalize_project_overview_result(model_data)

    source_content_path = str(primary.get("contentPath") or primary.get("content_path") or "").strip()
    source_relative_path = str(primary.get("relativePath") or primary.get("relative_path") or "").strip()
    if not source_relative_path and source_content_path:
        source_relative_path = f"sources/{source_content_path}"
    source_refs = []
    for item in source_items:
        content_path = str(item.get("contentPath") or item.get("content_path") or "").strip()
        relative_path = str(item.get("relativePath") or item.get("relative_path") or "").strip()
        if not relative_path and content_path:
            relative_path = f"sources/{content_path}"
        try:
            ref_word_count = content_char_count(_read_source_content(project_id, item))
        except Exception:
            try:
                ref_word_count = int(
                    item.get("wordCount")
                    or item.get("word_count")
                    or item.get("charCount")
                    or item.get("char_count")
                    or 0
                )
            except (TypeError, ValueError):
                ref_word_count = 0
        source_refs.append(
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or "小说文本").strip() or "小说文本",
                "contentPath": content_path,
                "relativePath": relative_path,
                "rawFilename": item.get("rawFilename") or item.get("raw_filename") or "",
                "wordCount": max(0, ref_word_count),
                "charCount": max(0, ref_word_count),
            }
    )

    meta = _read_json(_project_meta_path(project_id), {})
    previous_overview = meta.get("overview_analysis") if isinstance(meta.get("overview_analysis"), dict) else {}
    previous_result = previous_overview.get("result") if isinstance(previous_overview.get("result"), dict) else {}
    previous_audio = previous_result.get("narrator_reference_audio") or previous_result.get("narratorReferenceAudio")
    if isinstance(previous_audio, dict):
        model_data["narrator_reference_audio"] = copy.deepcopy(previous_audio)
    meta["summary"] = _project_overview_summary_text(
        source_title,
        source_word_count,
        model_data,
    )
    _sync_project_theme_visual_context(
        project_id,
        meta,
        str(model_data.get("theme_visual_context") or ""),
    )
    _raise_if_agent_cancelled(session_id)
    meta["overview_analysis"] = {
        "source": model_meta.get("source"),
        "modelId": model_meta.get("modelId"),
        "modelLabel": model_meta.get("modelLabel"),
        "providerId": model_meta.get("providerId"),
        "error": model_meta.get("error"),
        "schema": (
            model_meta.get("structuredSchema")
            or PROJECT_OVERVIEW_STRUCTURED_SCHEMA["name"]
        ),
        "sourceId": str(primary.get("id") or ""),
        "sourceIds": [item["id"] for item in source_refs],
        "sourceTitle": source_title,
        "sourceTitles": [item["title"] for item in source_refs],
        "contentPath": source_content_path,
        "relativePath": source_relative_path,
        "sources": source_refs,
        "excerptChars": overview_excerpt_chars,
        "result": model_data or {},
    }
    meta["status_type"] = "running"
    meta["status"] = "小说概述已分析"
    meta["source_count"] = len(
        [
            item
            for item in list_sources(project_id)["sources"]
            if isinstance(item, dict) and _is_novel_source(item)
        ]
    )
    meta["word_count"] = source_word_count
    meta["wordCount"] = source_word_count
    meta["source"] = source_refs[0] if source_refs else None
    meta["sources"] = source_refs
    meta["updated_at"] = _now()
    episodes = meta.get("episodes")
    if isinstance(episodes, list) and episodes:
        episodes[0]["status"] = "小说概述已分析，等待故事版计划"
    _raise_if_agent_cancelled(session_id)
    _write_json(_project_meta_path(project_id), meta)

    _raise_if_agent_cancelled(session_id)
    from .task_control import _update_task_fields
    from .task_control import create_task

    task = create_task(
        "source_preprocess",
        project_id=project_id,
        episode_id=(episodes[0].get("id") if isinstance(episodes, list) and episodes else None),
        node_id="source_text_1",
    )
    task = _update_task_fields(
        task.get("id"),
        message="小说文本已读取，项目概述已更新。",
    ) or task
    project_row = _project_row(project_id, meta)
    return {
        "success": True,
        "project": project_row,
        "overview": str(meta.get("summary") or ""),
        "episodes": project_row.get("episodes") or [],
        "task": task,
    }


def update_project_overview(
    project_id: str,
    overview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    from .agent_sessions import _project_meta_path
    from .projects import _camel_to_snake
    from .projects import _normalize_project_id
    from .projects import _project_row
    project_id = _normalize_project_id(project_id)
    if not _project_dir(project_id).is_dir():
        raise FileNotFoundError("项目不存在")
    payload = overview if isinstance(overview, dict) else {}
    if isinstance(payload.get("overview"), dict):
        payload = payload.get("overview") or {}
    if isinstance(payload.get("values"), dict):
        payload = payload.get("values") or {}

    meta_path = _project_meta_path(project_id)
    meta = _read_json(meta_path, {})
    overview_analysis = (
        meta.get("overview_analysis")
        if isinstance(meta.get("overview_analysis"), dict)
        else {}
    )
    current_result = (
        overview_analysis.get("result")
        if isinstance(overview_analysis.get("result"), dict)
        else {}
    )
    merged = {
        **current_result,
        **{
            key: payload.get(key)
            for key in payload.keys()
            if key in _PROJECT_OVERVIEW_FIELDS
            or _camel_to_snake(key) in _PROJECT_OVERVIEW_FIELDS
        },
    }
    normalized = _normalize_project_overview_result(merged)
    meta_source = meta.get("source") if isinstance(meta.get("source"), dict) else {}
    source_title = str(
        overview_analysis.get("sourceTitle")
        or meta_source.get("title")
        or ""
    ).strip() or "小说文本"
    raw_word_count = (
        str(meta.get("word_count") or meta.get("wordCount") or "")
        .replace(",", "")
        .strip()
    )
    word_count = int(raw_word_count) if raw_word_count.isdigit() else 0
    meta["summary"] = _project_overview_summary_text(
        source_title,
        word_count,
        normalized,
    )
    _sync_project_theme_visual_context(
        project_id,
        meta,
        str(normalized.get("theme_visual_context") or ""),
    )
    overview_analysis["result"] = normalized
    overview_analysis["editedAt"] = _now()
    overview_analysis["editedBy"] = "user"
    meta["overview_analysis"] = overview_analysis
    meta["updated_at"] = _now()
    _write_json(meta_path, meta)
    project_row = _project_row(project_id, meta)
    return {
        "success": True,
        "project": project_row,
        "overview": str(meta.get("summary") or ""),
    }


def save_project_narrator_reference_audio(
    project_id: str,
    media: dict[str, Any] | None,
) -> dict[str, Any]:
    from .agent_sessions import _project_dir, _project_meta_path
    from .media_files import _delete_project_voice_reference_audio_if_unreferenced
    from .media_files import _normalize_voice_reference_audio
    from .projects import _normalize_project_id, _project_row

    project_id = _normalize_project_id(project_id)
    if not _project_dir(project_id).is_dir():
        raise FileNotFoundError("项目不存在")
    meta_path = _project_meta_path(project_id)
    meta = _read_json(meta_path, {})
    overview_analysis = meta.get("overview_analysis") if isinstance(meta.get("overview_analysis"), dict) else {}
    result = overview_analysis.get("result") if isinstance(overview_analysis.get("result"), dict) else {}
    previous_audio = result.get("narrator_reference_audio") or result.get("narratorReferenceAudio")
    if media is None:
        result.pop("narrator_reference_audio", None)
        result.pop("narratorReferenceAudio", None)
    else:
        # Keep one canonical persisted key so deleting an upload cannot leave
        # a legacy camel-case value that makes the removed audio reappear.
        result.pop("narratorReferenceAudio", None)
        result["narrator_reference_audio"] = _normalize_voice_reference_audio(project_id, media, subdir="narrator")
    overview_analysis["result"] = result
    overview_analysis["editedAt"] = _now()
    overview_analysis["editedBy"] = "user"
    meta["overview_analysis"] = overview_analysis
    meta["updated_at"] = _now()
    _write_json(meta_path, meta)
    if isinstance(previous_audio, dict):
        _delete_project_voice_reference_audio_if_unreferenced(project_id, previous_audio)
    return {"success": True, "project": _project_row(project_id, meta)}
