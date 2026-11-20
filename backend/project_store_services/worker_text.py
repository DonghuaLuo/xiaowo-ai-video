# -*- coding: utf-8 -*-
"""worker 文本、JSON 和重试反馈的格式化。"""
from __future__ import annotations

import copy
import json
import re
from .source_text_store import _compact_text
from typing import (
    Any,
)
def _worker_prompt_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)




def _strip_empty_prompt_fields(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(row)
        for key, row in value.items()
        if row not in (None, "", [], {})
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("worker 未返回 JSON 文本")
    fence_matches = re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
    candidates = [match.strip() for match in fence_matches if match.strip()] + [raw]
    decoder = json.JSONDecoder()
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("worker JSON 根节点必须是对象")
        except json.JSONDecodeError as exc:
            last_error = exc
        if candidate.startswith("["):
            continue
        index = candidate.find("{")
        if index >= 0:
            try:
                parsed, _end = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(parsed, dict):
                return parsed
    if last_error is not None:
        raise ValueError(f"worker JSON 根对象格式错误（第 {last_error.lineno} 行，第 {last_error.colno} 列）：{last_error.msg}")
    raise ValueError("worker 输出不是可解析的 JSON 对象")


def _compact_analyze_assets_brief_list(value: Any, *, limit: int = 8, item_limit: int = 70) -> list[str]:
    rows = value if isinstance(value, list) else []
    result: list[str] = []
    for item in rows:
        text = _compact_text(item, item_limit)
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _iter_revision_feedback_strings(value: Any) -> list[str]:
    result: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, str):
            text = item.strip()
            if text:
                result.append(text)

    walk(value)
    return result


def _revision_feedback_terms(feedback: dict[str, Any] | None, *, limit: int = 24) -> list[str]:
    terms: list[str] = []

    def add(value: Any) -> None:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if 2 <= len(text) <= 80 and text not in terms:
            terms.append(text)

    def add_terms_from_text(text: Any) -> None:
        source = str(text or "").strip()
        if not source:
            return
        for match in re.findall(r"[“\"'‘]([^”\"'’]{2,80})[”\"'’]", source):
            add(match)
        for match in re.findall(
            r"(?:重点修正|修正|补入|新增|补充|漏拆|错误跳过|重新判断|重新审查|明确跳过)[^。；\n]{0,36}?([A-Za-z0-9_\u4e00-\u9fff]{2,24})",
            source,
        ):
            add(match)

    def add_key_terms(value: Any) -> None:
        if len(terms) >= limit:
            return
        if isinstance(value, dict):
            for key in ("name", "mention", "assetName", "parentAssetName"):
                add(value.get(key))
                if len(terms) >= limit:
                    return
            for child in value.values():
                add_key_terms(child)
                if len(terms) >= limit:
                    return
        elif isinstance(value, list):
            for child in value:
                add_key_terms(child)
                if len(terms) >= limit:
                    return

    # Review feedback can contain a large copy of the previous output. If we
    # collect names from that output first, the actual blocking issue may be
    # pushed out of the term budget and the retry prompt will miss its source
    # window. Prioritize quoted/explicit terms from feedback text before walking
    # structured output rows.
    for text in _iter_revision_feedback_strings(feedback):
        add_terms_from_text(text)
        if len(terms) >= limit:
            return terms[:limit]

    add_key_terms(feedback)
    if len(terms) >= limit:
        return terms[:limit]

    for text in _iter_revision_feedback_strings(feedback):
        for match in re.findall(r"(?:漏拆|漏审|补充|补查|重新处理|明确跳过)(?:/漏审)?([A-Za-z0-9_\u4e00-\u9fff/、]{2,60})[:：]", text):
            for part in re.split(r"[/、,，\s]+", match):
                add(part)
        if len(terms) >= limit:
            break
    return terms[:limit]


def _source_windows_for_terms(
    source_text: Any,
    terms: list[str],
    *,
    window: int = 180,
    limit: int = 2400,
) -> str:
    source = str(source_text or "")
    if not source or not terms:
        return ""
    chunks: list[str] = []
    covered: list[tuple[int, int]] = []
    total = 0
    for term in terms:
        needle = str(term or "").strip()
        if not needle:
            continue
        index = source.find(needle)
        if index < 0:
            continue
        start = max(0, index - window)
        end = min(len(source), index + len(needle) + window)
        if any(start >= old_start and end <= old_end for old_start, old_end in covered):
            continue
        covered.append((start, end))
        chunk = re.sub(r"\s+", " ", source[start:end]).strip()
        if not chunk:
            continue
        chunks.append(chunk)
        total += len(chunk) + 1
        if total >= limit:
            break
    digest = "\n".join(chunks).strip()
    if len(digest) > limit:
        return digest[:limit].rstrip() + "...（相关原文片段已截断）"
    return digest


def _complete_generation_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _compact_text_head_tail(value: Any, limit: int = 400) -> str:
    """Lossy head/tail excerpt helper for bounded worker context windows only.

    The result is intentionally incomplete. It must be labeled/used as an
    excerpt and never written back as canonical prompt or provider payload.
    """
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    if limit <= 20:
        return text[:limit] + "..."
    head_limit = max(1, limit // 2)
    tail_limit = max(1, limit - head_limit - 8)
    return f"{text[:head_limit]}...（中略）...{text[-tail_limit:]}"


def _compact_story_text(value: Any, limit: int = 700) -> str:
    """Lossy story excerpt helper for worker prompts/review summaries only.

    Keep the original story/source fields outside this helper. If complete
    context is required for generation, pass the full value or block upstream.
    """
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    compacted: list[str] = []
    for line in lines:
        if line:
            compacted.append(line)
        elif compacted and compacted[-1]:
            compacted.append("")
    text = "\n".join(compacted).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def _compact_source_excerpt(value: Any, limit: int = 700, *, keep_tail: bool = False) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= limit:
        return text
    if keep_tail:
        return text[-limit:].lstrip()
    return text[:limit].rstrip()


def _json_chars(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        return len(str(value or ""))


def _compact_json(value: Any, limit: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        text = str(value or "")
    return _compact_text(text, limit)


def _payload_text_arg(payload: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return default


def _payload_int_arg(
    payload: dict[str, Any],
    *keys: str,
    default: int = 0,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value: Any = None
    for key in keys:
        if payload.get(key) not in (None, ""):
            value = payload.get(key)
            break
    try:
        result = int(value if value is not None else default)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _worker_source_excerpt_from_context(context: dict[str, Any]) -> dict[str, Any]:
    source_text = context.get("episodeSourceText") or context.get("sourceText") or ""
    if not source_text and isinstance(context.get("videoTaskContext"), dict):
        source_text = (context.get("videoTaskContext") or {}).get("scriptContent") or ""
    source_ref = context.get("episodeSourceRef") if isinstance(context.get("episodeSourceRef"), dict) else {}
    if not source_ref:
        source_ref = context.get("sourceRef") if isinstance(context.get("sourceRef"), dict) else {}
    source_window = context.get("sourceWindow") if isinstance(context.get("sourceWindow"), dict) else {}
    return {
        "episodeId": str(context.get("episodeId") or ""),
        "sourceId": str(source_ref.get("sourceId") or source_window.get("sourceId") or ""),
        "sourceRef": copy.deepcopy(source_ref),
        "sourceWindow": copy.deepcopy(source_window),
        "excerpt": _compact_story_text(source_text, 6000),
    }






def _review_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _review_text_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _review_text(item)
        if not text:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _review_source_refs(value: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        item: dict[str, Any] = {}
        for key in ("sourceId", "absoluteStart", "absoluteEnd"):
            if row.get(key) not in (None, "", [], {}):
                item[key] = copy.deepcopy(row.get(key))
        preview = _review_text(row.get("sourcePreview"))
        if preview:
            item["sourcePreview"] = preview
        if item:
            result.append(item)
        if len(result) >= limit:
            break
    return result
