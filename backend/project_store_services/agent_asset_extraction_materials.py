"""Versioned discovery and focused text reads for native asset extraction."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .agent_sessions import _project_dir

_TEXT_SUFFIXES = {'.md', '.txt', '.json', '.csv', '.yaml', '.yml'}


def asset_material_manifest(project_id: str) -> list[dict[str, Any]]:
    root = _project_dir(project_id).resolve()
    materials = root / 'sources' / 'materials'
    rows = []
    if not materials.exists():
        return rows
    for path in sorted(materials.rglob('*'), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(materials.resolve()) or not resolved.is_relative_to(root):
            continue
        raw = resolved.read_bytes()
        rows.append({'relativePath': path.relative_to(root).as_posix(), 'name': path.name,
                     'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                     'textReadable': path.suffix.lower() in _TEXT_SUFFIXES})
    return rows


def asset_material_catalog(manifest: list[dict[str, Any]], offset: int = 0) -> dict[str, Any]:
    offset = max(0, int(offset))
    page = manifest[offset:offset + 20]
    has_more = offset + len(page) < len(manifest)
    return {'files': page, 'total': len(manifest), 'hasMore': has_more,
            **({'nextOffset': offset + len(page)} if has_more else {})}


def asset_material_evidence(
    project_id: str, manifest: list[dict[str, Any]], *, queries: list[str] | None = None,
    relative_path: str = '', offset: int = 0, line_start: int = 1, line_count: int = 80,
) -> dict[str, Any]:
    """Search literal candidate names/aliases, or read a catalogued file by lines.

    A search result is a locator, not a claim that every relevant fact was found.
    Unsupported formats remain visible so the existing file reader can supplement.
    """
    root = _project_dir(project_id).resolve()
    selected = manifest
    if relative_path:
        selected = [row for row in manifest if row['relativePath'] == relative_path]
        if not selected:
            raise ValueError('请选择当前扩展资料目录中的 relativePath')
    terms = list(dict.fromkeys(str(value).strip() for value in (queries or []) if str(value).strip()))
    if not relative_path and not terms:
        raise ValueError('请给出候选名称/别名 queries，或指定资料 relativePath 按行读取')
    matches, unreadable = [], []
    for entry in selected:
        if not entry['textReadable']:
            unreadable.append({'relativePath': entry['relativePath'], 'reason': '请用 read_project_file 读取此格式'})
            continue
        raw = (root / entry['relativePath']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('扩展资料读取期间已变化，请重读任务资料')
        try:
            lines = raw.decode('utf-8-sig').splitlines()
        except UnicodeDecodeError:
            unreadable.append({'relativePath': entry['relativePath'], 'reason': '资料不是有效 UTF-8，请核对原文件编码'})
            continue
        if relative_path and not terms:
            start = max(0, int(line_start) - 1)
            end = min(len(lines), start + max(1, min(120, int(line_count))))
            return {'file': entry, 'lineStart': start + 1, 'lineEnd': end,
                    'totalLines': len(lines), 'text': '\n'.join(lines[start:end]),
                    'hasMore': end < len(lines), **({'nextLine': end + 1} if end < len(lines) else {})}
        spans = []
        for index, line in enumerate(lines):
            if any(term.casefold() in line.casefold() for term in terms):
                start, end = max(0, index - 3), min(len(lines), index + 18)
                if spans and start <= spans[-1][1] and end - spans[-1][0] <= 100:
                    spans[-1] = (spans[-1][0], end)
                else:
                    spans.append((start, end))
        for start, end in spans:
            matches.append({'relativePath': entry['relativePath'], 'sha256': entry['sha256'],
                            'lineStart': start + 1, 'lineEnd': end, 'text': '\n'.join(lines[start:end])})
    offset = max(0, int(offset))
    page, size = [], 0
    for row in matches[offset:]:
        length = len(row['text'])
        if page and (size + length > 12000 or len(page) >= 12):
            break
        page.append(row)
        size += length
    has_more = offset + len(page) < len(matches)
    return {'queries': terms, 'matches': page, 'totalMatches': len(matches),
            'searchedFiles': len(selected) - len(unreadable), 'unreadableFiles': unreadable,
            'hasMore': has_more, **({'nextOffset': offset + len(page)} if has_more else {}),
            'scopeNote': '字面检索只定位线索；别名或未命中时结合目录按行补读，不能据此宣称没有相关设定。'}
