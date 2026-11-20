# -*- coding: utf-8 -*-
"""剧情拆分的结构约束、来源片段与提案紧凑投影。"""
from __future__ import annotations

from .source_text_store import get_episode_source_text

import copy as copy
from .source_text_store import _compact_text
from .plot_split_one_request import clean_plot_source_text

import re as re

from typing import Any


def _compact_story_text(value: Any, limit: int = 700) -> str:
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


def _agent_compact_plot_split_shots(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    shots: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if isinstance(row, dict):
            compact = {
                "shotId": str(row.get("shotId") or row.get("shot_id") or f"shot_{index:02d}").strip(),
                "purpose": _compact_text(row.get("purpose") or row.get("intent") or row.get("summary"), 160),
                "visualAction": _compact_text(
                    row.get("visualAction")
                    or row.get("visual_action")
                    or row.get("action")
                    or row.get("visibleAction")
                    or row.get("visible_action"),
                    220,
                ),
                "cameraIntent": _compact_text(
                    row.get("cameraIntent") or row.get("camera_intent") or row.get("camera") or row.get("view"),
                    160,
                ),
                "emotion": _compact_text(row.get("emotion") or row.get("mood") or row.get("feeling"), 120),
            }
        else:
            text = _compact_text(row, 220)
            compact = {
                "shotId": f"shot_{index:02d}",
                "purpose": text,
                "visualAction": text,
                "cameraIntent": "",
                "emotion": "",
            }
        compact = {key: item for key, item in compact.items() if item not in ("", {}, [], None)}
        if compact:
            shots.append(compact)
    return shots


def _agent_compact_plot_split_proposal(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    items = value.get("items") if isinstance(value.get("items"), list) else []
    compact_items: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        compact_item = {
            "index": item.get("index") or index,
            "id": str(item.get("id") or f"plot_{index:03d}"),
            "title": _compact_text(item.get("title") or item.get("name"), 80),
            "sourceStartAnchor": _compact_source_excerpt(
                item.get("sourceStartAnchor")
                or item.get("source_start_anchor")
                or item.get("startAnchor")
                or item.get("start_anchor"),
                500,
            ),
            "sourceEndAnchor": _compact_source_excerpt(
                item.get("sourceEndAnchor")
                or item.get("source_end_anchor")
                or item.get("endAnchor")
                or item.get("end_anchor"),
                500,
                keep_tail=True,
            ),
            "sourceFactText": str(item.get("sourceFactText") or item.get("source_fact_text") or ""),
            "excludedTexts": copy.deepcopy(item.get("excludedTexts") or []),
            "sourcePreview": _compact_source_excerpt(
                item.get("sourcePreview") or item.get("source_preview") or item.get("excerpt"),
                500,
            ),
            "sourceRefs": copy.deepcopy(item.get("sourceRefs") or item.get("source_refs") or []),
            "sourceRange": copy.deepcopy(item.get("sourceRange") or item.get("source_range") or {}),
            "reason": _compact_text(item.get("reason") or item.get("splitReason") or item.get("split_reason"), 360),
            "splitReason": _compact_text(item.get("splitReason") or item.get("split_reason") or item.get("reason"), 360),
            "assetHints": copy.deepcopy(item.get("assetHints") if isinstance(item.get("assetHints"), dict) else {}),
            "assetBindings": copy.deepcopy(item.get("assetBindings") if isinstance(item.get("assetBindings"), list) else []),
        }
        compact = {key: val for key, val in compact_item.items() if val not in ("", {}, [], None)}
        if isinstance(item.get("assetHints"), dict):
            compact["assetHints"] = copy.deepcopy(item["assetHints"])
        if isinstance(item.get("assetBindings"), list):
            compact["assetBindings"] = copy.deepcopy(item["assetBindings"])
        compact_items.append(compact)
    compact_proposal = {
        "episodeId": str(value.get("episodeId") or value.get("episode_id") or "").strip(),
        "episodeTitle": _compact_text(value.get("episodeTitle") or value.get("episode_title") or value.get("title"), 80),
        "count": int(value.get("count") or len(items) or 0),
        "items": compact_items,
    }
    context_provenance = value.get("contextProvenance") or value.get("context_provenance")
    if isinstance(context_provenance, dict) and context_provenance:
        compact_proposal["contextProvenance"] = copy.deepcopy(context_provenance)
    return compact_proposal


_PLOT_SPLIT_REVISION_REQUIREMENT_LIMIT = 8


_PLOT_SPLIT_REVISION_REQUIREMENT_CHARS = 500


def _agent_plot_split_revision_requirements(value: Any) -> list[str]:
    if isinstance(value, list):
        rows = value
    elif isinstance(value, str):
        rows = [value]
    else:
        rows = []
    requirements: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            raw_text = (
                row.get("text")
                or row.get("instruction")
                or row.get("message")
                or row.get("requirement")
                or ""
            )
        else:
            raw_text = row
        text = _compact_text(raw_text, _PLOT_SPLIT_REVISION_REQUIREMENT_CHARS)
        key = re.sub(r"\s+", "", text)
        if not key or key in seen:
            continue
        requirements.append(text)
        seen.add(key)
    return requirements[-_PLOT_SPLIT_REVISION_REQUIREMENT_LIMIT:]


def _agent_plot_split_revision_count(value: Any, *, fallback: int = 0) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = fallback
    return max(0, count)


def _agent_compact_plot_split_commit_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    proposal = _agent_compact_plot_split_proposal(value.get("plotSplitProposal"))
    revision_requirements = _agent_plot_split_revision_requirements(
        value.get("effectiveRevisionRequirements")
    )
    revision_count = _agent_plot_split_revision_count(
        value.get("revisionCount"),
        fallback=len(revision_requirements),
    )
    source_input_ref = (
        copy.deepcopy(value.get("sourceInputRef"))
        if isinstance(value.get("sourceInputRef"), dict)
        else {}
    )
    result = {
        "episodeId": str(value.get("episodeId") or proposal.get("episodeId") or "").strip(),
        "userInstruction": _compact_text(value.get("userInstruction"), 1200),
        "baseUserInstruction": _compact_text(
            value.get("baseUserInstruction"),
            500,
        ),
    }
    if proposal:
        result["plotSplitProposal"] = proposal
    if source_input_ref:
        result["sourceInputRef"] = source_input_ref
    if revision_requirements:
        result["effectiveRevisionRequirements"] = revision_requirements
    if revision_count:
        result["revisionCount"] = revision_count
    return {key: item for key, item in result.items() if item not in ("", {}, [], None)}




def _agent_plot_split_proposal_from_pending_operation(operation: dict[str, Any]) -> dict[str, Any]:
    candidates: list[Any] = []
    proposal = operation.get("proposal") if isinstance(operation.get("proposal"), dict) else {}
    if proposal:
        candidates.append(proposal)
    latest_result = operation.get("latestResult") if isinstance(operation.get("latestResult"), dict) else {}
    if isinstance(latest_result.get("plotSplitProposal"), dict):
        candidates.append(latest_result.get("plotSplitProposal"))
    commit_payload = operation.get("commitPayload") if isinstance(operation.get("commitPayload"), dict) else {}
    if isinstance(commit_payload.get("plotSplitProposal"), dict):
        candidates.append(commit_payload.get("plotSplitProposal"))
    for candidate in candidates:
        items = candidate.get("items") if isinstance(candidate, dict) else []
        if isinstance(items, list) and items:
            return candidate
    return candidates[0] if candidates and isinstance(candidates[0], dict) else {}


def _work_chain_planning_source_ref(project_id: str, episode_id: str) -> dict[str, Any]:
    source = get_episode_source_text(project_id, episode_id)
    if source.get("available") is False:
        raise ValueError(f"{episode_id} 缺少已提交 source range")
    source_ref = source.get("sourceRef") if isinstance(source.get("sourceRef"), dict) else {}
    if not source_ref:
        raise ValueError(f"{episode_id} 缺少已提交 source range")
    return source_ref


def _plot_split_proposal_message(
    proposal: dict[str, Any], assets: dict[str, list[dict[str, Any]]] | None = None
) -> str:
    preview = _plot_split_proposal_block(proposal, assets)
    episode_title = preview["episodeTitle"]
    items = preview["segments"]
    lines = ["当前集剧情拆分待确认："]
    if episode_title:
        lines.append(f"- 分集标题：{episode_title}")
    lines.append(f"- 剧情段落：{len(items)} 段")
    for item in items:
        lines.append(f"{item['index']}. **{item['title']}**（约 {item['charCount']} 字）")
        if item["text"]:
            lines.extend(("", item["text"]))
        if item["splitReason"]:
            lines.extend(("", f"   分段理由：{item['splitReason']}"))
        for asset in item["assets"]:
            lines.extend(("", f"   {asset['label']}：{'、'.join(asset['names'])}"))
        if not item["assets"]:
            lines.extend(("", "   暂无关联资产"))
        lines.append("")
    return "\n".join(lines)


def _plot_split_proposal_block(
    proposal: dict[str, Any], assets: dict[str, list[dict[str, Any]]] | None = None,
    *, candidate_id: str = "", candidate_version: int = 0,
) -> dict[str, Any]:
    items = proposal.get("items") if isinstance(proposal.get("items"), list) else []
    asset_names = {
        kind: {
            str(row.get("id") or ""): str(row.get("name") or row.get("id") or "")
            for row in rows if isinstance(row, dict)
        }
        for kind, rows in (assets or {}).items() if isinstance(rows, list)
    }
    for kind, rows in (assets or {}).items():
        if not isinstance(rows, list):
            continue
        names = [str(row.get("name") or "") for row in rows if isinstance(row, dict)]
        for row in rows:
            if not isinstance(row, dict) or names.count(str(row.get("name") or "")) < 2:
                continue
            identity = str(row.get("desc") or row.get("identityHint") or "").split("。")[0]
            qualifier = _compact_text(identity, 48) or str(row.get("id") or "")
            asset_names[kind][str(row.get("id") or "")] = f"{row.get('name')}（{qualifier}）"
    asset_labels = {"scenes": "场景", "characters": "人物", "creatures": "生物", "props": "道具"}
    segments = []
    for item in items:
        if not isinstance(item, dict):
            continue
        index = item.get("index") or len(segments) + 1
        title = str(item.get("title") or "").strip() or f"原文拆分内容 {index}"
        description = str(
            item.get("sourceFactText")
            or item.get("source_fact_text")
            or item.get("sourcePreview")
            or item.get("source_preview")
            or item.get("description")
            or "",
        ).strip()
        description = clean_plot_source_text(description, item.get("excludedTexts", []))
        reason = _compact_text(item.get("splitReason") or item.get("reason"), 90)
        hints = item.get("assetHints") if isinstance(item.get("assetHints"), dict) else {}
        asset_rows = [
            {
                "label": label,
                "names": [
                    asset_names.get(kind, {}).get(asset_id, asset_id)
                    for asset_id in hints[kind] if isinstance(asset_id, str)
                ],
            }
            for kind, label in asset_labels.items()
            if isinstance(hints.get(kind), list) and hints.get(kind)
        ]
        segments.append({
            "index": index, "title": title, "text": description,
            "charCount": len(description), "splitReason": reason,
            "assets": asset_rows,
        })
    return {
        "type": "plot_split_preview",
        "candidateId": candidate_id,
        "candidateVersion": candidate_version,
        "status": "pending_confirmation",
        "episodeTitle": str(proposal.get("episodeTitle") or "").strip(),
        "segments": segments,
    }


PLOT_SPLIT_PROPOSAL_STRUCTURED_SCHEMA: dict[str, Any] = {
    "name": "plot_split_proposal",
    "description": "当前分集原文剧情拆分结果。",
    "fields": [
        {
            "name": "plotSplitProposal",
            "type": "object",
            "required": True,
            "description": "只包含当前分集的原文剧情拆分内容。",
            "fields": [
                {"name": "episodeId", "type": "string", "required": True, "description": "当前分集 ID。"},
                {"name": "episodeTitle", "type": "string", "required": True, "description": "当前分集标题。"},
                {
                    "name": "items",
                    "type": "array",
                    "required": True,
                    "description": "按原文顺序排列的完整剧情单元；数量由事件边界和叙事推进决定。",
                    "items": {
                        "type": "object",
                        "fields": [
                            {"name": "title", "type": "string", "required": True, "description": "当前剧情单元标题。"},
                            {
                                "name": "sourceStartAnchor",
                                "type": "string",
                                "required": True,
                                "description": "从当前剧情单元原文范围第一个字开始的连续逐字原文短摘录；有效字符数必须大于 10。",
                            },
                            {
                                "name": "sourceEndAnchor",
                                "type": "string",
                                "required": True,
                                "description": "以当前剧情单元原文范围最后一个字结束的连续逐字原文短摘录；有效字符数必须大于 10。",
                            },
                            {"name": "splitReason", "type": "string", "required": True, "description": "当前拆分边界成立原因。"},
                        ],
                    },
                },
            ],
        }
    ],
}
