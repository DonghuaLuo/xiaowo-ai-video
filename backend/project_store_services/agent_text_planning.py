# -*- coding: utf-8 -*-
"""智能体文本分块、资产文本生成与分集文本生成。"""
from __future__ import annotations

from .catalogs import ACCENTS
from .source_text_store import _compact_text
from typing import Any
from utils.text_metrics import content_char_count
import copy
import re


def _append_generation_instruction(prompt: str, instruction: str) -> str:
    base = str(prompt or "").strip()
    note = str(instruction or "").strip()
    if not note:
        return base
    if note in base:
        return base
    if not base:
        return note
    return f"{base}\n\n用户本轮优化要求：{note}"


def _split_sentences(text: str) -> list[str]:
    parts = [item.strip() for item in re.split(r"[。！？!?；;\n]+", text) if item.strip()]
    return parts or [_compact_text(text, 120)]


def _agent_text_unit_count(text: str) -> int:
    return content_char_count(text)


def _join_agent_sentences(sentences: list[str]) -> str:
    return "。".join([sentence for sentence in sentences if sentence]).strip()


def _chunk_text_by_units(text: str, count: int) -> list[str]:
    count = max(1, count)
    clean_text = str(text or "").strip()
    if not clean_text:
        return ["" for _ in range(count)]
    total_units = max(1, _agent_text_unit_count(clean_text))
    target_units = max(1, (total_units + count - 1) // count)
    chunks: list[str] = []
    bucket: list[str] = []
    bucket_units = 0
    for char in clean_text:
        bucket.append(char)
        if not char.isspace():
            bucket_units += 1
        if bucket_units >= target_units and len(chunks) < count - 1:
            chunks.append("".join(bucket).strip())
            bucket = []
            bucket_units = 0
    if bucket:
        chunks.append("".join(bucket).strip())
    while len(chunks) < count:
        chunks.append("")
    return chunks[:count]


def _chunk_sentences(sentences: list[str], count: int) -> list[str]:
    count = max(1, count)
    clean_sentences = [str(sentence or "").strip() for sentence in sentences if str(sentence or "").strip()]
    if not clean_sentences:
        return ["" for _ in range(count)]
    total_units = sum(max(1, _agent_text_unit_count(sentence)) for sentence in clean_sentences)
    target_units = max(1, (total_units + count - 1) // count)
    chunks: list[str] = []
    bucket: list[str] = []
    bucket_units = 0
    for index, sentence in enumerate(clean_sentences):
        remaining_sentences = len(clean_sentences) - index
        remaining_slots = count - len(chunks)
        if bucket and bucket_units >= target_units and remaining_slots > 1 and remaining_sentences >= remaining_slots:
            chunks.append(_join_agent_sentences(bucket))
            bucket = []
            bucket_units = 0
        bucket.append(sentence)
        bucket_units += max(1, _agent_text_unit_count(sentence))
    if bucket:
        chunks.append(_join_agent_sentences(bucket))
    while len(chunks) > count:
        extra = chunks.pop()
        chunks[-1] = _join_agent_sentences([chunks[-1], extra])
    if len(chunks) < count:
        return _chunk_text_by_units(_join_agent_sentences(clean_sentences), count)
    while len(chunks) < count:
        chunks.append("")
    return chunks[:count]


def _build_agent_assets(title: str, text: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "characters": [],
        "scenes": [],
        "props": [],
        "styles": [],
    }


def _normalize_agent_asset_rows(
    rows: Any,
    *,
    prefix: str,
    default_tag: str,
    source: str,
    accent_offset: int = 0,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if isinstance(row, str):
            name = row.strip()
            desc = ""
            tag = ""
        elif isinstance(row, dict):
            name = str(row.get("name") or row.get("title") or "").strip()
            desc = str(row.get("desc") or row.get("description") or row.get("summary") or "").strip()
            tag = str(row.get("tag") or row.get("category") or "").strip()
        else:
            continue
        if not name or not desc:
            continue
        item = {
            "id": f"{prefix}-{index + 1}",
            "name": name,
            "desc": desc,
            "accent": ACCENTS[(index + accent_offset) % len(ACCENTS)],
            "source": source,
        }
        if tag:
            item["tag"] = tag
        if isinstance(row, dict):
            structured_aliases = {
                "aliases": ("aliases",),
                "importance": ("importance", "priority"),
                "referenceMediaIds": ("referenceMediaIds", "reference_media_ids"),
            }
            for target_key, aliases in structured_aliases.items():
                for alias in aliases:
                    if alias in row:
                        item[target_key] = copy.deepcopy(row[alias])
                        break
        result.append(item)
    return result


def _agent_assets_from_model(data: dict[str, Any], title: str, text: str) -> dict[str, list[dict[str, Any]]]:
    characters = _normalize_agent_asset_rows(
        data.get("characters"),
        prefix="agent-character",
        default_tag="",
        source="agent-model",
    )
    scenes = _normalize_agent_asset_rows(
        data.get("scenes"),
        prefix="agent-scene",
        default_tag="",
        source="agent-model",
        accent_offset=1,
    )
    props = _normalize_agent_asset_rows(
        data.get("props"),
        prefix="agent-prop",
        default_tag="",
        source="agent-model",
        accent_offset=2,
    )
    return {
        "characters": characters,
        "scenes": scenes,
        "props": props,
        "styles": [],
    }


def _agent_episode_script_from_chunk(
    title: str,
    source_text: str,
    panels: list[dict[str, Any]],
    panel_count: int,
) -> str:
    from .projects import _first_text
    lines = [
        str(title or "当前分集").strip(),
        "",
        f"剧情段落：{_compact_text(source_text, 360) or '根据源文本继续整理本集剧情。'}",
        "",
        "分镜剧本：",
    ]
    for index in range(max(1, panel_count)):
        panel = panels[index] if index < len(panels) and isinstance(panels[index], dict) else {}
        panel_title = _first_text(panel.get("title")) or f"镜头 {index + 1}"
        visual = _first_text(panel.get("visualPrompt") or panel.get("visual") or panel.get("description"))
        dialogue = _first_text(panel.get("dialogue") or panel.get("voiceover") or panel.get("narration"))
        anchor = _first_text(panel.get("continuityAnchor") or panel.get("continuity_anchor"))
        lines.append(f"{index + 1}. {panel_title}")
        lines.append(f"   画面：{visual or _compact_text(source_text, 120) or '承接本集剧情推进关键动作。'}")
        if dialogue:
            lines.append(f"   台词/旁白：{dialogue}")
        if anchor:
            lines.append(f"   连续性锚点：{anchor}")
    return "\n".join(lines).strip()


def _model_episode_chunks(
    data: dict[str, Any] | None,
    fallback_chunks: list[str],
    panel_count: int,
) -> list[dict[str, Any]]:
    episodes = data.get("episodes") if isinstance(data, dict) else None
    if not isinstance(episodes, list):
        episodes = []
    result: list[dict[str, Any]] = []
    for index, chunk in enumerate(fallback_chunks):
        row = episodes[index] if index < len(episodes) and isinstance(episodes[index], dict) else {}
        panels = row.get("panels") if isinstance(row.get("panels"), list) else []
        title = str(row.get("title") or f"第 {index + 1} 集：{_compact_text(chunk, 14)}")
        source_text = str(row.get("sourceText") or row.get("source_text") or chunk).strip()
        script = str(
            row.get("episodeScript")
            or row.get("episode_script")
            or row.get("script")
            or row.get("shootingScript")
            or ""
        ).strip()
        if not script:
            script = _agent_episode_script_from_chunk(title, source_text, panels, panel_count)
        result.append(
            {
                "id": str(row.get("id") or f"E{index + 1:02d}"),
                "title": title,
                "status": str(row.get("status") or f"已完成 {panel_count} 个分镜草稿"),
                "sourceText": source_text,
                "episodeScript": script,
                "wordCount": _agent_text_unit_count(source_text),
                "panels": panels[:panel_count],
            }
        )
    return result
