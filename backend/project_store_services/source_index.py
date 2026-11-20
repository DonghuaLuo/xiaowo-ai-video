# -*- coding: utf-8 -*-
"""原文章节与稳定文本单元索引，以及窗口读取。"""
from __future__ import annotations

from .source_text_store import _read_source_content
from .source_text_store import _select_project_sources
from .source_text_store import _sha256_text
from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json
from pathlib import Path
from typing import Any
from utils.text_metrics import content_char_count
from utils.text_metrics import content_offset_after_units
from utils.text_metrics import content_units_between
import re


_SOURCE_INDEX_SCHEMA_VERSION = 3


_SOURCE_INDEX_MAX_UNITS_PER_SOURCE = 12000


_SOURCE_INDEX_SENTENCE_MAX_CHARS = 300000


_CHAPTER_HEADING_RE = re.compile(
    r"(?m)^\s*(第[一二三四五六七八九十百千万\d]+[章节回卷集部][^\n]{0,40}|Chapter\s+\d+[^\n]{0,60})\s*$",
    re.IGNORECASE,
)


def _source_index_path(project_id: str) -> Path:
    from .agent_sessions import _project_dir
    return _project_dir(project_id) / "source_index.json"


def _chapter_rows_for_source(source: dict[str, Any], content: str) -> list[dict[str, Any]]:
    source_id = str(source.get("id") or "").strip()
    matches = list(_CHAPTER_HEADING_RE.finditer(content))
    if not matches:
        return [
            {
                "id": f"{source_id}_ch_0001" if source_id else "ch_0001",
                "sourceId": source_id,
                "title": "全文",
                "start": 0,
                "end": len(content),
                "charCount": content_char_count(content),
                "excerpt": content[:160],
            }
        ]
    chapters: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = int(match.start())
        end = int(matches[index + 1].start()) if index + 1 < len(matches) else len(content)
        title = match.group(1).strip() or f"章节 {index + 1}"
        chapters.append(
            {
                "id": f"{source_id}_ch_{index + 1:04d}" if source_id else f"ch_{index + 1:04d}",
                "sourceId": source_id,
                "title": title,
                "start": start,
                "end": end,
                "charCount": content_units_between(content, start, end),
                "excerpt": content[start:min(end, start + 160)],
            }
        )
    return chapters


def _chapter_id_for_offset(chapters: list[dict[str, Any]], absolute_start: int) -> str:
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        start = int(chapter.get("start") or 0)
        end = int(chapter.get("end") or start)
        if start <= absolute_start < end:
            return str(chapter.get("id") or "")
    return str((chapters[0] or {}).get("id") or "") if chapters else ""


def _source_unit_rows_for_source(source: dict[str, Any], content: str, chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_id = str(source.get("id") or "").strip()
    units: list[dict[str, Any]] = []
    chapter_cursor = 0

    def _chapter_id_for_start(start: int) -> str:
        nonlocal chapter_cursor
        while chapter_cursor + 1 < len(chapters):
            next_start = int((chapters[chapter_cursor + 1] or {}).get("start") or 0)
            if start < next_start:
                break
            chapter_cursor += 1
        if not chapters:
            return ""
        chapter = chapters[min(chapter_cursor, len(chapters) - 1)] or {}
        return str(chapter.get("id") or "")

    def _append_unit(kind: str, start: int, end: int, text: str) -> bool:
        if len(units) >= _SOURCE_INDEX_MAX_UNITS_PER_SOURCE:
            return False
        if not text.strip():
            return True
        unit_id = f"u{len(units) + 1:06d}"
        units.append(
            {
                "id": unit_id,
                "sourceId": source_id,
                "chapterId": _chapter_id_for_start(start),
                "kind": kind,
                "type": kind,
                "absoluteStart": start,
                "absoluteEnd": end,
                "charCount": content_char_count(text),
                "textHash": _sha256_text(text),
            }
        )
        return len(units) < _SOURCE_INDEX_MAX_UNITS_PER_SOURCE

    include_sentences = len(content) <= _SOURCE_INDEX_SENTENCE_MAX_CHARS
    paragraph_start: int | None = None
    paragraph_end = 0
    cursor = 0

    def _flush_paragraph() -> bool:
        nonlocal paragraph_start, paragraph_end
        if paragraph_start is None:
            return True
        start = paragraph_start
        end = paragraph_end
        text = content[start:end]
        paragraph_start = None
        paragraph_end = 0
        if not text.strip():
            return True
        if not _append_unit("paragraph", start, end, text):
            return False
        if include_sentences:
            for sentence_match in re.finditer(r"[^。！？!?；;\n]+[。！？!?；;]?", text):
                sentence_text = sentence_match.group(0)
                sentence_start = start + int(sentence_match.start())
                sentence_end = start + int(sentence_match.end())
                if not _append_unit("sentence", sentence_start, sentence_end, sentence_text):
                    return False
        return len(units) < _SOURCE_INDEX_MAX_UNITS_PER_SOURCE

    for line in content.splitlines(keepends=True):
        line_start = cursor
        line_end = cursor + len(line)
        cursor = line_end
        if not line.strip():
            if not _flush_paragraph():
                break
            continue
        if paragraph_start is None:
            paragraph_start = line_start
        paragraph_end = line_end
        if len(units) >= _SOURCE_INDEX_MAX_UNITS_PER_SOURCE:
            break
    else:
        _flush_paragraph()
    if not units and content:
        _append_unit("paragraph", 0, len(content), content)
    return units


def build_source_index(project_id: str) -> dict[str, Any]:
    from .projects import _touch_project_meta
    sources = _select_project_sources(project_id)
    source_rows: list[dict[str, Any]] = []
    chapter_index: list[dict[str, Any]] = []
    unit_index: list[dict[str, Any]] = []
    total_chars = 0
    for source in sources:
        content = _read_source_content(project_id, source)
        content_units = content_char_count(content)
        source_id = str(source.get("id") or "").strip()
        chapters = _chapter_rows_for_source(source, content)
        units = _source_unit_rows_for_source(source, content, chapters)
        total_chars += content_units
        source_rows.append(
            {
                "id": source_id,
                "title": str(source.get("title") or "小说文本").strip() or "小说文本",
                "kind": str(source.get("kind") or "TXT"),
                "charCount": content_units,
                "wordCount": content_units,
                "chapterCount": len(chapters),
                "unitCount": len(units),
                "contentHash": _sha256_text(content),
                "contentPath": str(source.get("contentPath") or source.get("content_path") or ""),
                "relativePath": str(source.get("relativePath") or source.get("relative_path") or ""),
            }
        )
        chapter_index.extend(chapters)
        unit_index.extend(units)
    index = {
        "schemaVersion": _SOURCE_INDEX_SCHEMA_VERSION,
        "builtAt": _now(),
        "sources": source_rows,
        "chapterIndex": chapter_index,
        "units": unit_index,
        "novelStats": {
            "sourceCount": len(source_rows),
            "chapterCount": len(chapter_index),
            "unitCount": len(unit_index),
            "totalChars": total_chars,
        },
    }
    _write_json(_source_index_path(project_id), index)
    _touch_project_meta(project_id)
    return {"success": True, "sourceIndex": index}


def list_source_index(project_id: str) -> dict[str, Any]:
    path = _source_index_path(project_id)
    if not path.exists():
        return build_source_index(project_id)
    index = _read_json(path, {})
    if not isinstance(index, dict):
        return build_source_index(project_id)
    if int(index.get("schemaVersion") or 0) < _SOURCE_INDEX_SCHEMA_VERSION:
        return build_source_index(project_id)
    return {"success": True, "sourceIndex": index}


def read_source_window(
    project_id: str,
    source_id: str | None = None,
    chapter_id: str | None = None,
    offset: int | str | None = 0,
    length: int | str | None = 4000,
) -> dict[str, Any]:
    window_length = max(1, min(20000, int(length or 4000)))
    requested_offset = max(0, int(offset or 0))
    selected_source_id = str(source_id or "").strip()
    selected_chapter_id = str(chapter_id or "").strip()
    index = list_source_index(project_id).get("sourceIndex") or {}
    chapter: dict[str, Any] | None = None
    if selected_chapter_id:
        chapter = next(
            (
                item
                for item in index.get("chapterIndex", [])
                if isinstance(item, dict) and str(item.get("id") or "") == selected_chapter_id
            ),
            None,
        )
        if not chapter:
            raise ValueError("未找到指定章节窗口")
        selected_source_id = str(chapter.get("sourceId") or selected_source_id)
    sources = _select_project_sources(project_id, selected_source_id or None)
    source = sources[0]
    content = _read_source_content(project_id, source)
    raw_total_chars = len(content)
    total_chars = content_char_count(content)
    if chapter:
        chapter_start = max(0, min(raw_total_chars, int(chapter.get("start") or 0)))
        chapter_end = max(chapter_start, min(raw_total_chars, int(chapter.get("end") or raw_total_chars)))
        start = min(chapter_end, chapter_start + requested_offset)
        end = min(chapter_end, content_offset_after_units(content, start, window_length))
    else:
        chapter_start = 0
        chapter_end = raw_total_chars
        start = min(raw_total_chars, requested_offset)
        end = min(raw_total_chars, content_offset_after_units(content, start, window_length))
    text = content[start:end]
    text_units = content_char_count(text)
    return {
        "success": True,
        "sourceId": str(source.get("id") or ""),
        "sourceTitle": str(source.get("title") or "小说文本"),
        "chapterId": selected_chapter_id,
        "chapterTitle": str((chapter or {}).get("title") or ""),
        "offset": start - chapter_start if chapter else start,
        "absoluteStart": start,
        "absoluteEnd": end,
        "length": text_units,
        "rawLength": len(text),
        "totalChars": total_chars,
        "totalRawChars": raw_total_chars,
        "chapterStart": chapter_start,
        "chapterEnd": chapter_end,
        "hasBefore": start > chapter_start,
        "hasAfter": end < chapter_end,
        "text": text,
    }


def search_source_text(
    project_id: str,
    query: str,
    *,
    source_id: str | None = None,
    max_matches: int = 8,
) -> dict[str, Any]:
    """Locate a literal name or phrase in novel sources before reading full windows."""
    needle = str(query or "").strip()
    if not needle or len(needle) > 120:
        raise ValueError("原文检索词长度必须为 1-120 字")
    limit = max(1, min(12, int(max_matches or 8)))
    sources = _select_project_sources(project_id, source_id)
    candidates: list[dict[str, Any]] = []
    total_matches = 0
    pattern = re.compile(re.escape(needle), re.IGNORECASE)
    for source in sources:
        content = _read_source_content(project_id, source)
        if not content:
            continue
        buckets: dict[int, dict[str, Any]] = {}
        for match in pattern.finditer(content):
            total_matches += 1
            bucket = min(7, match.start() * 8 // len(content))
            if bucket in buckets:
                continue
            start = max(0, match.start() - 180)
            end = min(len(content), match.end() + 180)
            buckets[bucket] = {
                "sourceId": str(source.get("id") or ""),
                "sourceTitle": str(source.get("title") or "小说文本"),
                "absoluteStart": match.start(),
                "absoluteEnd": match.end(),
                "windowStart": start,
                "windowEnd": end,
                "excerpt": content[start:end],
            }
        candidates.extend(buckets.values())
    selected = candidates
    if len(candidates) > limit:
        indices = (
            [0] if limit == 1 else
            sorted({round(index * (len(candidates) - 1) / (limit - 1)) for index in range(limit)})
        )
        selected = [candidates[index] for index in indices]
    return {
        "success": True,
        "query": needle,
        "searchedSourceCount": len(sources),
        "totalMatches": total_matches,
        "matches": selected,
        "sampled": total_matches > len(selected),
    }
