"""Completion reports built from verified source boundaries."""
from __future__ import annotations

import re
import traceback
from typing import Any

from utils.text_metrics import content_offset_after_units

from .source_text_store import _read_source_content, _select_project_sources


def _boundary_excerpt(text: str, *, tail: bool = False) -> str:
    ordered = text[::-1] if tail else text
    end = content_offset_after_units(ordered, 0, 100)
    excerpt = ordered[:end]
    return (excerpt[::-1] if tail else excerpt).strip()


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines())


def build_boundary_completion_report(
    project_id: str, row: dict[str, Any], *, kind: str,
) -> str:
    """Use the committed row, never a model-supplied preview or the next cursor."""
    is_episode = kind == "episode"
    label = "分集规划" if is_episode else "资产范围规划"
    target = str(row.get("episodeId" if is_episode else "rangeId") or "")
    title = str(row.get("episodeTitle") or "") if is_episode else ""
    heading = " · ".join(part for part in (f"{label}完成", target, title) if part)
    reason = re.sub(r"\s+", " ", str(row.get("boundaryReason") or "")).strip()
    if len(reason) > 180:
        reason = reason[:179] + "…"
    sections = [f"**{heading}**"]
    try:
        source_id = str(row["sourceId"])
        if not source_id:
            raise ValueError("已保存的断点缺少原文来源")
        source = _select_project_sources(project_id, source_id)[0]
        content = _read_source_content(project_id, source)
        start, end = int(row["absoluteStart"]), int(row["absoluteEnd"])
        if not 0 <= start < end <= len(content):
            raise ValueError("已保存的断点超出当前原文范围")
        before = _boundary_excerpt(content[start:end], tail=True)
        after = _boundary_excerpt(content[end:])
        sections.extend([
            f"原文位置 {start}–{end} · 约 {row['actualUnits']} 字",
            f"**{'本集' if is_episode else '本段'}结尾（断点前）**\n\n{_quote(before)}",
            f"**{'下一集' if is_episode else '下一段'}开头（断点后）**\n\n"
            + (_quote(after) if after else "已到原文末尾，无下一段。"),
        ])
    except Exception:
        # Reporting must not turn a verified commit into a failed submission.
        print(traceback.format_exc(), flush=True)
        sections.append("结果已保存；暂时无法读取断点前后原文，请在项目原文中查看。")
    sections.append(f"**断点理由**：{reason or '本次未提供断点理由。'}")
    return "\n\n".join(sections)
