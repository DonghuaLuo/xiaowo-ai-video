# -*- coding: utf-8 -*-
"""项目原文文件、完整快照、追加片段和分集正文的读取与写入。"""
from __future__ import annotations

from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json
from pathlib import Path
from typing import Any
from utils.common import open_in_file_explorer
from utils.text_metrics import content_char_count
import base64
import hashlib
import re
import uuid


SOURCE_GROUP_NOVEL = "novel"


SOURCE_GROUP_SUPPLEMENTAL = "supplemental"


_SOURCE_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5")


_SUPPLEMENTAL_SOURCE_GROUP_ALIASES = {
    "attachment",
    "attachments",
    "extra",
    "extras",
    "extension",
    "extensions",
    "material",
    "materials",
    "reference",
    "references",
    "supplement",
    "supplemental",
    "资料",
    "扩展资料",
    "附加资料",
}


_NOVEL_SOURCE_GROUP_ALIASES = {
    "novel",
    "original",
    "primary",
    "source",
    "text",
    "txt",
    "正文",
    "原文",
    "小说",
    "小说原文",
}


def _source_payload_label(source: dict[str, Any] | None, fallback: str = "文本文件") -> str:
    item = source if isinstance(source, dict) else {}
    return str(
        item.get("rawFilename")
        or item.get("raw_filename")
        or item.get("title")
        or fallback
    ).strip() or fallback


def _source_text_corruption_reason(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    replacement_count = value.count("\ufffd")
    if replacement_count > max(2, int(len(value) * 0.001)):
        return "文本包含大量编码替换字符"
    mojibake_count = sum(value.count(token) for token in ("锟斤拷", "ï¿½"))
    if mojibake_count > max(1, int(len(value) * 0.0005)):
        return "文本疑似已被错误编码转换"
    return ""


def _assert_source_text_not_corrupted(text: str, label: str = "文本文件") -> str:
    content = str(text or "")
    reason = _source_text_corruption_reason(content)
    if reason:
        raise ValueError(
            f"「{label}」疑似编码读取失败：{reason}。请重新导入原始 TXT 文件，"
            "支持 UTF-8、GB18030、GBK 等常见中文编码。"
        )
    return content


def _decode_source_text_bytes(raw: bytes, label: str = "文本文件") -> str:
    data = bytes(raw or b"")
    if not data:
        return ""
    last_error = ""
    for encoding in _SOURCE_TEXT_ENCODINGS:
        try:
            text = data.decode(encoding).removeprefix("\ufeff")
        except UnicodeDecodeError as exc:
            last_error = f"{encoding}: {exc}"
            continue
        reason = _source_text_corruption_reason(text)
        if not reason:
            return text
        last_error = f"{encoding}: {reason}"
    suffix = f"（{last_error}）" if last_error else ""
    raise ValueError(
        f"「{label}」编码无法识别或疑似乱码{suffix}。请使用 UTF-8、GB18030 或 GBK 编码的 TXT 文件。"
    )


def _source_payload_content(source: dict[str, Any]) -> str:
    label = _source_payload_label(source)
    encoded = str(
        source.get("contentBase64")
        or source.get("content_base64")
        or source.get("contentBytes")
        or source.get("content_bytes")
        or ""
    ).strip()
    if encoded:
        try:
            return _decode_source_text_bytes(base64.b64decode(encoded, validate=True), label).strip()
        except Exception as exc:
            raise ValueError(f"「{label}」文本内容解码失败：{exc}") from exc
    return _assert_source_text_not_corrupted(str(source.get("content") or ""), label).strip()


def _source_group(source: dict[str, Any]) -> str:
    explicit = str(
        source.get("sourceGroup")
        or source.get("source_group")
        or source.get("group")
        or ""
    ).strip().casefold()
    if explicit in _SUPPLEMENTAL_SOURCE_GROUP_ALIASES:
        return SOURCE_GROUP_SUPPLEMENTAL
    if explicit in _NOVEL_SOURCE_GROUP_ALIASES:
        return SOURCE_GROUP_NOVEL
    kind = str(source.get("kind") or "").strip().casefold()
    if kind in _SUPPLEMENTAL_SOURCE_GROUP_ALIASES:
        return SOURCE_GROUP_SUPPLEMENTAL
    return SOURCE_GROUP_NOVEL


def _is_novel_source(source: dict[str, Any]) -> bool:
    return _source_group(source) == SOURCE_GROUP_NOVEL


def _source_refs_for_meta(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_refs: list[dict[str, Any]] = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        content_path = str(item.get("contentPath") or item.get("content_path") or "").strip()
        relative_path = str(item.get("relativePath") or item.get("relative_path") or "").strip()
        try:
            word_count = int(
                item.get("wordCount")
                or item.get("word_count")
                or item.get("charCount")
                or item.get("char_count")
                or 0
            )
        except (TypeError, ValueError):
            word_count = 0
        if not relative_path and content_path:
            relative_path = f"sources/{content_path}"
        source_refs.append(
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or "小说文本").strip() or "小说文本",
                "contentPath": content_path,
                "relativePath": relative_path,
                "rawFilename": item.get("rawFilename") or item.get("raw_filename") or "",
                "sourceGroup": _source_group(item),
                "wordCount": max(0, word_count),
                "charCount": max(0, word_count),
            }
        )
    return source_refs


def _source_filename_stem(raw_filename: str, fallback: str) -> str:
    base_name = Path(str(raw_filename or fallback or "")).name
    if "." in base_name:
        base_name = re.sub(r"\.[^.]+$", "", base_name)
    base_name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "", base_name)
    base_name = re.sub(r"\s+", "", base_name)
    base_name = base_name.strip(" .")
    if base_name:
        return base_name
    fallback_name = re.sub(r"[\x00-\x1f<>:\"/\\|?*\s]+", "", str(fallback or ""))
    return fallback_name.strip(" .") or "小说文本"


def _source_filename_extension(raw_filename: str, group: str) -> str:
    suffix = Path(str(raw_filename or "")).suffix.casefold()
    if group == SOURCE_GROUP_SUPPLEMENTAL and suffix == ".md":
        return ".md"
    return ".txt"


def _source_storage_path(
    project_id: str,
    source: dict[str, Any],
    sources: list[dict[str, Any]],
) -> tuple[Path, str]:
    from .agent_sessions import _project_dir
    raw_filename = str(source.get("rawFilename") or source.get("raw_filename") or source.get("title") or "")
    title = str(source.get("title") or "小说文本").strip() or "小说文本"
    stem = _source_filename_stem(raw_filename, title)
    group = _source_group(source)
    extension = _source_filename_extension(raw_filename, group)
    folder = "materials" if group == SOURCE_GROUP_SUPPLEMENTAL else ""
    existing_paths = {
        str(item.get("contentPath") or item.get("content_path") or "").replace("\\", "/").casefold()
        for item in sources
        if isinstance(item, dict)
    }
    index = 1
    while True:
        suffix = "" if index == 1 else f"-{index}"
        filename = f"{stem}{suffix}{extension}"
        content_path = f"{folder}/{filename}" if folder else filename
        path = _project_dir(project_id) / "sources" / content_path
        if content_path.casefold() not in existing_paths and not path.exists():
            return path, content_path
        index += 1


def list_sources(project_id: str, include_status: bool = False) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    path = _project_dir(project_id) / "sources" / "sources.json"
    sources = _read_json(path, [])
    if include_status:
        sources = [
            _source_with_runtime_status(project_id, item) if isinstance(item, dict) else item
            for item in sources
        ]
    return {"sources": sources}


def _source_text_result(
    project_id: str,
    source: dict[str, Any],
    text: str | None = None,
) -> dict[str, Any]:
    from .projects import _project_relative_path
    content = _read_source_content(project_id, source) if text is None else str(text or "")
    path = _safe_source_content_path(project_id, source)
    content_units = content_char_count(content)
    result = {
        "success": True,
        "sourceId": str(source.get("id") or ""),
        "title": str(source.get("title") or "小说文本"),
        "text": content,
        "charCount": content_units,
        "wordCount": content_units,
        "contentPath": str(source.get("contentPath") or source.get("content_path") or ""),
        "relativePath": str(
            source.get("relativePath")
            or source.get("relative_path")
            or (_project_relative_path(project_id, path) if path else "")
            or ""
        ),
        "rawFilename": str(source.get("rawFilename") or source.get("raw_filename") or ""),
        "appendSegments": _source_append_segments(source),
    }
    if _is_novel_source(source):
        result.update(_source_total_hash_status(project_id, source, content))
    return result


def get_source_text(project_id: str, source_id: str | None = None) -> dict[str, Any]:
    source = _select_project_sources(project_id, source_id)[0]
    return _source_text_result(project_id, source)


def open_source_file_location(project_id: str, source_id: str | None = None) -> dict[str, Any]:
    from .projects import _project_relative_path
    source = _select_project_sources(project_id, source_id, include_supplemental=True)[0]
    path = _safe_source_content_path(project_id, source)
    if not path:
        return {"success": False, "message": "未记录完整总文件路径"}
    result = open_in_file_explorer(path)
    if isinstance(result, dict):
        result.setdefault("sourceId", str(source.get("id") or ""))
        result.setdefault("relativePath", _project_relative_path(project_id, path) or "")
    return result


def open_episode_source_file_location(project_id: str, episode_id: str) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    from .projects import _is_path_within
    from .projects import _project_relative_path
    episode_id = str(episode_id or "").strip()
    if not episode_id:
        raise ValueError("缺少 episodeId")
    path = _episode_source_text_path(project_id, episode_id)
    if not _is_path_within(path, _project_dir(project_id) / "episodes"):
        raise ValueError("分集原文路径越界")
    result = open_in_file_explorer(path)
    if isinstance(result, dict):
        result.setdefault("episodeId", episode_id)
        result.setdefault(
            "relativePath",
            _project_relative_path(project_id, path) or f"episodes/{episode_id}/source.txt",
        )
    return result


def save_source_text(
    project_id: str,
    source_id: str,
    text: str,
    *,
    title: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    from .agent_sessions import _project_meta_path
    from .projects import _touch_project_meta
    from .source_coverage import _load_source_coverage
    from .source_coverage import _write_source_coverage
    from .source_index import build_source_index
    source_id = str(source_id or "").strip()
    if not source_id:
        raise ValueError("缺少 sourceId")
    sources = [
        item
        for item in list_sources(project_id)["sources"]
        if isinstance(item, dict)
    ]
    source_index = next(
        (
            index
            for index, item in enumerate(sources)
            if str(item.get("id") or "") == source_id
        ),
        -1,
    )
    if source_index < 0:
        raise ValueError("未找到指定的小说文本")
    source = dict(sources[source_index])
    source_is_novel = _is_novel_source(source)
    next_title = str(title or source.get("title") or "小说文本").strip() or "小说文本"
    content = _assert_source_text_not_corrupted(str(text or ""), next_title).strip()
    path = _safe_source_content_path(project_id, source)
    if not path:
        path = _project_dir(project_id) / "sources" / f"{source_id}.txt"
        source["contentPath"] = path.name
        source["relativePath"] = f"sources/{path.name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    content_units = content_char_count(content)

    source.update(
        {
            "title": next_title,
            "kind": str(source.get("kind") or "TXT"),
            "status": "ready",
            "wordCount": content_units,
            "charCount": content_units,
            "excerpt": content[:120],
            "contentPath": str(source.get("contentPath") or path.name),
            "relativePath": str(source.get("relativePath") or f"sources/{path.name}"),
        }
    )
    if not str(source.get("rawFilename") or source.get("raw_filename") or "").strip():
        source["rawFilename"] = next_title
    sources[source_index] = source
    _write_json(_project_dir(project_id) / "sources" / "sources.json", sources)

    meta = _read_json(_project_meta_path(project_id), {})
    if isinstance(meta, dict):
        if source_is_novel:
            novel_sources = [
                item
                for item in sources
                if isinstance(item, dict) and _is_novel_source(item)
            ]
            source_refs = _source_refs_for_meta(novel_sources)
            total_word_count = sum(int(ref.get("wordCount") or 0) for ref in source_refs)
            selected_ref = next(
                (ref for ref in source_refs if ref.get("id") == source_id),
                None,
            )
            meta["source_count"] = len(novel_sources)
            meta["word_count"] = total_word_count
            meta["wordCount"] = total_word_count
            meta["sources"] = source_refs
            if selected_ref and (
                not isinstance(meta.get("source"), dict)
                or str(meta.get("source", {}).get("id") or "") == source_id
                or len(source_refs) == 1
            ):
                meta["source"] = selected_ref
        meta["updated_at"] = _now()
        _write_json(_project_meta_path(project_id), meta)

    if source_is_novel:
        build_source_index(project_id)
        try:
            coverage = _load_source_coverage(project_id)
            if str(coverage.get("sourceId") or "") == source_id:
                coverage["revision"] = int(coverage.get("revision") or 0) + 1
                _write_source_coverage(project_id, coverage)
        except Exception:
            _touch_project_meta(project_id)
    result = _source_text_result(project_id, source, content)
    result["changedResources"] = (
        ["sources", "sourceIndex", "sourceCoverage"]
        if source_is_novel
        else ["sources"]
    )
    result["reason"] = str(reason or "manual_source_saved")
    return result


def append_novel_source_files(
    project_id: str,
    source_id: str | None,
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    if not isinstance(files, list) or not files:
        raise ValueError("请至少选择一个 .txt 原文件")
    sources, source_index, source = _find_source_record(project_id, source_id)
    if not _is_novel_source(source):
        raise ValueError("只能向小说原文件追加内容")
    current_text = _ensure_source_total_text_state(
        project_id,
        source,
        _read_source_content(project_id, source),
    )
    segments = _ensure_initial_source_segment(source, current_text)
    next_text = current_text
    added_segments: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        content = _source_payload_content(item)
        if not content.strip():
            continue
        title = str(item.get("title") or item.get("rawFilename") or item.get("raw_filename") or "原文件").strip() or "原文件"
        raw_filename = str(item.get("rawFilename") or item.get("raw_filename") or title)
        prefix = "\n\n" if next_text else ""
        block = f"{prefix}--- {title} ---\n{content.strip()}"
        segment = _source_segment_from_text(
            source_id=str(source.get("id") or ""),
            title=title,
            raw_filename=raw_filename,
            text=block,
            start=len(next_text),
            kind="append",
            base_text=next_text,
        )
        segments.append(segment)
        added_segments.append(segment)
        next_text += block
    if not added_segments:
        raise ValueError("原文件内容为空，请选择包含正文的 .txt 文件")
    _write_source_total_backup(project_id, source, next_text)
    source["appendSegments"] = segments
    sources[source_index] = source
    _write_json(_project_dir(project_id) / "sources" / "sources.json", sources)
    result = save_source_text(
        project_id,
        str(source.get("id") or ""),
        next_text,
        title=str(source.get("title") or "小说文本"),
        reason="append_novel_source_files",
    )
    result["source"] = _latest_source_with_runtime_status(
        project_id,
        str(source.get("id") or ""),
    ) or _source_with_runtime_status(project_id, source)
    result["segments"] = added_segments
    return result


def restore_source_total_snapshot(
    project_id: str,
    source_id: str,
) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    sources, source_index, source = _find_source_record(project_id, source_id)
    if not _is_novel_source(source):
        raise ValueError("只能恢复小说原文件")
    snapshot = _read_source_total_backup(project_id, source)
    expected_hash = _source_recorded_total_hash(source)
    snapshot_hash = _source_text_hash(snapshot)
    if expected_hash and snapshot_hash != expected_hash:
        rebased_snapshot = _rebaseline_source_total_from_consistent_backup(
            project_id,
            source,
            _read_source_content(project_id, source),
            snapshot,
        )
        if rebased_snapshot is None:
            raise ValueError("原文备份校验失败，禁止恢复")
        snapshot = rebased_snapshot
        snapshot_hash = _source_text_hash(snapshot)
    source["totalTextHash"] = snapshot_hash
    _write_source_total_backup(project_id, source, snapshot)
    sources[source_index] = source
    _write_json(_project_dir(project_id) / "sources" / "sources.json", sources)
    result = save_source_text(
        project_id,
        str(source.get("id") or ""),
        snapshot,
        title=str(source.get("title") or "小说文本"),
        reason="restore_source_total_snapshot",
    )
    result["restoredHash"] = snapshot_hash
    result["source"] = _latest_source_with_runtime_status(
        project_id,
        str(source.get("id") or ""),
    ) or _source_with_runtime_status(project_id, source)
    return result


def delete_source_segment(
    project_id: str,
    source_id: str,
    segment_id: str,
) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    sources, source_index, source = _find_source_record(project_id, source_id)
    if not _is_novel_source(source):
        raise ValueError("只能删除小说原文件段")
    content = _ensure_source_total_text_state(
        project_id,
        source,
        _read_source_content(project_id, source),
    )
    segments = _source_append_segments(source)
    if not segments:
        raise ValueError("当前原文件没有可删除的追加记录")
    if str(segments[-1].get("id") or "") != str(segment_id or ""):
        raise ValueError("原文件只能按最后添加的顺序删除，请先删除最后添加的文件")
    segment = dict(segments[-1])
    segment_kind = str(segment.get("kind") or "").strip().lower()
    if len(segments) <= 1 or segment_kind != "append":
        raise ValueError("只能删除后续追加的小说原文件，初始总文件不能在此删除")
    start, end, _segment_text = _assert_segment_text_unchanged(content, segment)
    next_content = content[:start] + content[end:]
    _write_source_total_backup(project_id, source, next_content)
    source["appendSegments"] = segments[:-1]
    sources[source_index] = source
    _write_json(_project_dir(project_id) / "sources" / "sources.json", sources)
    result = save_source_text(
        project_id,
        str(source.get("id") or ""),
        next_content,
        title=str(source.get("title") or "小说文本"),
        reason="delete_source_segment",
    )
    result["deletedSegment"] = segment
    result["source"] = _latest_source_with_runtime_status(
        project_id,
        str(source.get("id") or ""),
    ) or _source_with_runtime_status(project_id, source)
    return result


def _source_content_path(project_id: str, source: dict[str, Any]) -> Path | None:
    from .agent_sessions import _project_dir
    content_path = str(source.get("contentPath") or source.get("content_path") or "").strip()
    if not content_path:
        return None
    return _project_dir(project_id) / "sources" / content_path


def _safe_source_content_path(project_id: str, source: dict[str, Any]) -> Path | None:
    from .agent_sessions import _project_dir
    from .projects import _is_path_within
    path = _source_content_path(project_id, source)
    if not path:
        return None
    sources_root = _project_dir(project_id) / "sources"
    if not _is_path_within(path, sources_root):
        raise ValueError("小说文本路径越界")
    return path


def _read_source_content(project_id: str, source: dict[str, Any]) -> str:
    path = _safe_source_content_path(project_id, source)
    if path and path.exists() and path.is_file():
        return _decode_source_text_bytes(path.read_bytes(), _source_payload_label(source))
    return _assert_source_text_not_corrupted(
        str(source.get("content") or source.get("excerpt") or ""),
        _source_payload_label(source),
    )


def _source_text_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _source_recorded_total_hash(source: dict[str, Any]) -> str:
    return str(source.get("totalTextHash") or source.get("total_text_hash") or "").strip()


def _source_total_backup_path(project_id: str, source: dict[str, Any]) -> Path:
    from .agent_sessions import _project_dir
    from .projects import _is_path_within
    sources_root = _project_dir(project_id) / "sources"
    source_id = str(source.get("id") or "").strip()
    backup_path = str(
        source.get("totalTextBackupPath") or source.get("total_text_backup_path") or ""
    ).replace("\\", "/").strip()
    if not backup_path:
        backup_path = f".source-backups/{source_id or 'source'}.txt"
    path = sources_root / backup_path
    if not _is_path_within(path, sources_root):
        raise ValueError("原文备份路径越界")
    return path


def _write_source_total_backup(
    project_id: str,
    source: dict[str, Any],
    content: str,
) -> str:
    from .store_core import _display_time
    from .projects import _project_relative_path
    text = str(content or "")
    text_hash = _source_text_hash(text)
    backup_path = _source_total_backup_path(project_id, source)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(text, encoding="utf-8", newline="\n")
    relative_backup_path = (
        _project_relative_path(project_id, backup_path)
        or f"sources/.source-backups/{str(source.get('id') or 'source')}.txt"
    )
    source["totalTextHash"] = text_hash
    source["totalTextBackupHash"] = text_hash
    source["totalTextBackupPath"] = relative_backup_path.replace(
        "\\",
        "/",
    ).removeprefix("sources/")
    source["totalTextSnapshotAt"] = _display_time(_now())
    return text_hash


def _read_source_total_backup(project_id: str, source: dict[str, Any]) -> str:
    backup_path = _source_total_backup_path(project_id, source)
    if not backup_path.exists() or not backup_path.is_file():
        raise ValueError("未找到可恢复的原文备份")
    return _decode_source_text_bytes(backup_path.read_bytes(), _source_payload_label(source))


def _source_total_hash_status(
    project_id: str,
    source: dict[str, Any],
    content: str | None = None,
) -> dict[str, Any]:
    expected_hash = _source_recorded_total_hash(source)
    backup_path = _source_total_backup_path(project_id, source)
    has_backup = backup_path.exists() and backup_path.is_file()
    try:
        current_text = _read_source_content(project_id, source) if content is None else str(content or "")
        current_hash = _source_text_hash(current_text)
    except Exception as exc:
        return {
            "totalTextHash": expected_hash,
            "currentTotalTextHash": "",
            "totalTextHashStatus": "unavailable",
            "needsRestore": False,
            "hasTotalTextBackup": has_backup,
            "totalTextHashError": str(exc),
        }
    status = "untracked"
    if expected_hash:
        if current_hash == expected_hash:
            status = "ok"
        else:
            status = "mismatch"
    return {
        "totalTextHash": expected_hash,
        "currentTotalTextHash": current_hash,
        "totalTextHashStatus": status,
        "needsRestore": status == "mismatch",
        "hasTotalTextBackup": has_backup,
    }


def _source_with_runtime_status(project_id: str, source: dict[str, Any]) -> dict[str, Any]:
    row = dict(source)
    if _is_novel_source(row):
        try:
            content_units = content_char_count(_read_source_content(project_id, row))
            row["charCount"] = content_units
            row["wordCount"] = content_units
        except Exception:
            pass
        row.update(_source_total_hash_status(project_id, row))
    return row


def _latest_source_with_runtime_status(
    project_id: str,
    source_id: str | None,
) -> dict[str, Any] | None:
    requested_id = str(source_id or "").strip()
    if not requested_id:
        return None
    latest = next(
        (
            item
            for item in list_sources(project_id)["sources"]
            if isinstance(item, dict) and str(item.get("id") or "") == requested_id
        ),
        None,
    )
    return _source_with_runtime_status(project_id, latest) if latest else None


def _ensure_source_total_text_state(
    project_id: str,
    source: dict[str, Any],
    content: str,
) -> str:
    text = str(content or "")
    current_hash = _source_text_hash(text)
    expected_hash = _source_recorded_total_hash(source)
    if expected_hash and current_hash != expected_hash:
        return _restore_source_total_text_from_backup(
            project_id,
            source,
            expected_hash,
            text,
        )
    if not expected_hash:
        _write_source_total_backup(project_id, source, text)
        return text
    backup_path = _source_total_backup_path(project_id, source)
    if not backup_path.exists() or not backup_path.is_file():
        _write_source_total_backup(project_id, source, text)
    return text


def _restore_source_total_text_from_backup(
    project_id: str,
    source: dict[str, Any],
    expected_hash: str,
    current_text: str = "",
) -> str:
    snapshot = _read_source_total_backup(project_id, source)
    snapshot_hash = _source_text_hash(snapshot)
    if snapshot_hash != expected_hash:
        rebased_text = _rebaseline_source_total_from_consistent_backup(
            project_id,
            source,
            current_text,
            snapshot,
        )
        if rebased_text is not None:
            return rebased_text
        raise ValueError("总文件内容已被修改，且备份校验失败，无法自动恢复")
    path = _safe_source_content_path(project_id, source)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(snapshot, encoding="utf-8", newline="\n")
    source["totalTextHash"] = snapshot_hash
    _write_source_total_backup(project_id, source, snapshot)
    return snapshot


def _rebaseline_source_total_from_consistent_backup(
    project_id: str,
    source: dict[str, Any],
    current_text: str,
    backup_text: str,
) -> str | None:
    current = current_text
    backup = backup_text
    if not current or current != backup:
        return None
    next_segments = _rebaseline_source_segments_for_content(source, current)
    if next_segments is None:
        return None
    path = _safe_source_content_path(project_id, source)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(current, encoding="utf-8", newline="\n")
    source["appendSegments"] = next_segments
    _write_source_total_backup(project_id, source, current)
    return current


def _rebaseline_source_segments_for_content(
    source: dict[str, Any],
    content: str,
) -> list[dict[str, Any]] | None:
    source_id = str(source.get("id") or "")
    title = str(source.get("title") or "小说文本").strip() or "小说文本"
    raw_filename = str(source.get("rawFilename") or source.get("raw_filename") or title)
    segments = _source_append_segments(source)
    if not segments:
        return [
            _source_segment_from_text(
                source_id=source_id,
                title=title,
                raw_filename=raw_filename,
                text=content,
                start=0,
                kind="initial",
                created_at=str(source.get("createdAt") or ""),
            )
        ]
    if len(segments) == 1 and str(segments[0].get("kind") or "").strip().lower() == "initial":
        old_segment = dict(segments[0])
        next_segment = _source_segment_from_text(
            source_id=source_id,
            title=str(old_segment.get("title") or title),
            raw_filename=str(old_segment.get("rawFilename") or old_segment.get("raw_filename") or raw_filename),
            text=content,
            start=0,
            kind="initial",
            created_at=str(old_segment.get("createdAt") or old_segment.get("created_at") or source.get("createdAt") or ""),
        )
        next_segment["id"] = str(old_segment.get("id") or next_segment["id"])
        return [next_segment]
    next_segments: list[dict[str, Any]] = []
    for segment in segments:
        try:
            start, end = _segment_bounds(segment)
        except Exception:
            return None
        if end > len(content):
            return None
        segment_text = content[start:end]
        expected_hash = str(segment.get("textHash") or segment.get("text_hash") or "")
        if expected_hash and _source_text_hash(segment_text) != expected_hash:
            return None
        row = dict(segment)
        line_start, line_end, line_count = _source_segment_line_range(
            content[:start],
            segment_text,
        )
        row["lineStart"] = line_start
        row["lineEnd"] = line_end
        row["lineCount"] = line_count
        next_segments.append(row)
    return next_segments


def _source_append_segments(source: dict[str, Any]) -> list[dict[str, Any]]:
    rows = source.get("appendSegments")
    if not isinstance(rows, list):
        rows = source.get("append_segments")
    if not isinstance(rows, list):
        return []
    return [dict(item) for item in rows if isinstance(item, dict)]


def _source_segment_from_text(
    *,
    source_id: str,
    title: str,
    raw_filename: str,
    text: str,
    start: int,
    kind: str,
    base_text: str = "",
    created_at: str | None = None,
) -> dict[str, Any]:
    from .store_core import _display_time
    end = start + len(text)
    line_start, line_end, line_count = _source_segment_line_range(base_text, text)
    content_units = content_char_count(text)
    return {
        "id": f"seg-{uuid.uuid4().hex[:10]}",
        "sourceId": source_id,
        "kind": kind,
        "title": title,
        "rawFilename": raw_filename,
        "charStart": start,
        "charEnd": end,
        "charCount": content_units,
        "wordCount": content_units,
        "lineStart": line_start,
        "lineEnd": line_end,
        "lineCount": line_count,
        "textHash": _source_text_hash(text),
        "createdAt": created_at or _display_time(_now()),
    }


def _source_line_count(text: str) -> int:
    value = str(text or "")
    return value.count("\n") + 1 if value else 0


def _source_segment_line_range(base_text: str, text: str) -> tuple[int, int, int]:
    base = str(base_text or "")
    segment = str(text or "")
    if not segment:
        return 0, 0, 0
    line_start = base.count("\n") + 1
    line_count = segment.count("\n") + 1
    if base and segment.startswith("\n") and not base.endswith("\n"):
        line_start += 1
        line_count = max(1, line_count - 1)
    return line_start, line_start + max(0, line_count - 1), line_count


def _ensure_initial_source_segment(source: dict[str, Any], content: str) -> list[dict[str, Any]]:
    segments = _source_append_segments(source)
    if segments or not content:
        return segments
    source_id = str(source.get("id") or "")
    title = str(source.get("title") or "小说文本").strip() or "小说文本"
    raw_filename = str(source.get("rawFilename") or source.get("raw_filename") or title)
    segments.append(
        _source_segment_from_text(
            source_id=source_id,
            title=title,
            raw_filename=raw_filename,
            text=content,
            start=0,
            kind="initial",
            created_at=str(source.get("createdAt") or ""),
        )
    )
    source["appendSegments"] = segments
    return segments


def _segment_bounds(segment: dict[str, Any]) -> tuple[int, int]:
    start = int(segment.get("charStart") or segment.get("start") or 0)
    end = int(segment.get("charEnd") or segment.get("end") or 0)
    if start < 0 or end < start:
        raise ValueError("原文件段记录无效")
    return start, end


def _assert_segment_text_unchanged(content: str, segment: dict[str, Any]) -> tuple[int, int, str]:
    start, end = _segment_bounds(segment)
    if end > len(content):
        raise ValueError("总文件内容已被修改，当前原文件段位置无效，禁止继续操作")
    current_text = content[start:end]
    expected_hash = str(segment.get("textHash") or segment.get("text_hash") or "")
    if expected_hash and _source_text_hash(current_text) != expected_hash:
        raise ValueError("总文件内容已被修改，原文件段校验失败，禁止继续操作")
    return start, end, current_text


def _find_source_record(
    project_id: str,
    source_id: str | None = None,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    rows = [
        item
        for item in list_sources(project_id)["sources"]
        if isinstance(item, dict)
    ]
    requested_id = str(source_id or "").strip()
    for index, item in enumerate(rows):
        if requested_id and str(item.get("id") or "") != requested_id:
            continue
        if not requested_id and not _is_novel_source(item):
            continue
        return rows, index, dict(item)
    raise ValueError("未找到指定的小说文本")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _episode_source_ref_path(project_id: str, episode_id: str) -> Path:
    from .agent_sessions import _project_dir
    return _project_dir(project_id) / "episodes" / episode_id / "source_ref.json"


def _episode_source_text_path(project_id: str, episode_id: str) -> Path:
    from .agent_sessions import _project_dir
    return _project_dir(project_id) / "episodes" / episode_id / "source.txt"


def _read_episode_source_text(project_id: str, episode_id: str) -> str:
    path = _episode_source_text_path(project_id, episode_id)
    if path.exists() and path.is_file():
        # read_text() converts CRLF to LF, changing the committed text hash.
        return path.read_bytes().decode("utf-8")
    return ""


def _episode_source_display_title(
    project_id: str,
    episode_id: str,
    range_row: dict[str, Any] | None,
    source_ref: dict[str, Any] | None,
    text: str = "",
) -> str:
    from .source_boundary_contract import _episode_boundary_title_from_payload
    from .source_boundary_contract import _episode_title_from_shot_plan
    range_row = range_row if isinstance(range_row, dict) else {}
    source_ref = source_ref if isinstance(source_ref, dict) else {}
    title = _episode_boundary_title_from_payload(
        {
            "title": range_row.get("title") or source_ref.get("title"),
            "episodeTitle": range_row.get("episodeTitle") or source_ref.get("episodeTitle"),
            "episode_title": range_row.get("episode_title") or source_ref.get("episode_title"),
        },
        episode_id,
        text,
    )
    return title or _episode_title_from_shot_plan(project_id, episode_id) or episode_id


def _episode_source_status(project_id: str, episode_id: str, default_status: str = "") -> str:
    from .agent_sessions import _project_dir
    from .agent_sessions import _project_meta_path
    from .exports import _has_export_value
    shot_plan_path = _project_dir(project_id) / "episodes" / episode_id / "work_chain_plan.json"
    shot_plan = _read_json(shot_plan_path, {}) if shot_plan_path.exists() else {}
    if isinstance(shot_plan, dict) and (
        _has_export_value(shot_plan.get("segments")) or _has_export_value(shot_plan.get("shots"))
    ):
        # The plan contains placeholders; their existence does not prove that
        # a director script or storyboard has been generated.
        return "已生成工作链"
    meta = _read_json(_project_meta_path(project_id), {})
    for episode in meta.get("episodes") or []:
        if not isinstance(episode, dict) or str(episode.get("id") or "") != episode_id:
            continue
        if str(episode.get("episodeScript") or episode.get("script") or "").strip():
            return "已生成片段剧本"
        break
    return default_status or "已提交"


def _episode_source_rows(project_id: str, coverage: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    from .projects import _project_relative_path
    from .source_coverage import _load_source_coverage
    coverage = coverage if isinstance(coverage, dict) else _load_source_coverage(project_id)
    rows: list[dict[str, Any]] = []
    for item in coverage.get("episodeRanges", []):
        if not isinstance(item, dict):
            continue
        episode_id = str(item.get("episodeId") or item.get("episode_id") or "").strip()
        if not episode_id:
            continue
        ref = _read_json(_episode_source_ref_path(project_id, episode_id), {})
        path = _episode_source_text_path(project_id, episode_id)
        text = _read_episode_source_text(project_id, episode_id)
        title = _episode_source_display_title(project_id, episode_id, item, ref, text)
        text_units = (
            content_char_count(text)
            if text
            else int(item.get("charCount") or ref.get("charCount") or 0)
        )
        rows.append(
            {
                "episodeId": episode_id,
                "title": title,
                "sourceId": str(item.get("sourceId") or ref.get("sourceId") or coverage.get("sourceId") or ""),
                "absoluteStart": int(item.get("absoluteStart") or ref.get("absoluteStart") or 0),
                "absoluteEnd": int(item.get("absoluteEnd") or ref.get("absoluteEnd") or 0),
                "charCount": text_units,
                "boundaryReason": str(item.get("boundaryReason") or ref.get("boundaryReason") or ""),
                "status": _episode_source_status(project_id, episode_id, str(item.get("status") or "")),
                "relativePath": _project_relative_path(project_id, path) or f"episodes/{episode_id}/source.txt",
                "excerpt": _compact_text(text, 220) if text else "",
                "sourceRef": ref if isinstance(ref, dict) else {},
            }
        )
    return rows


def get_episode_source_text(project_id: str, episode_id: str) -> dict[str, Any]:
    from .projects import _project_relative_path
    episode_id = str(episode_id or "").strip()
    if not episode_id:
        raise ValueError("缺少 episodeId")
    path = _episode_source_text_path(project_id, episode_id)
    ref = _read_json(_episode_source_ref_path(project_id, episode_id), {})
    row = next(
        (item for item in _episode_source_rows(project_id) if str(item.get("episodeId") or "") == episode_id),
        {},
    )
    relative_path = _project_relative_path(project_id, path) or f"episodes/{episode_id}/source.txt"
    if not path.exists() or not path.is_file():
        return {
            "success": True,
            "available": False,
            "episodeId": episode_id,
            "title": _episode_source_display_title(project_id, episode_id, row, ref, ""),
            "text": "",
            "charCount": 0,
            "relativePath": relative_path,
            "sourceRef": ref if isinstance(ref, dict) else {},
            "message": f"本集原文尚未提交：episodes/{episode_id}/source.txt",
        }
    text = _read_episode_source_text(project_id, episode_id)
    text_units = content_char_count(text)
    return {
        "success": True,
        "available": True,
        "episodeId": episode_id,
        "title": _episode_source_display_title(project_id, episode_id, row, ref, text),
        "text": text,
        "charCount": text_units,
        "relativePath": relative_path,
        "sourceRef": ref if isinstance(ref, dict) else {},
    }


def save_episode_source_text(
    project_id: str,
    episode_id: str,
    text: str,
    *,
    title: str | None = None,
    reason: str = "manual_source_text_saved",
) -> dict[str, Any]:
    from .agent_sessions import _project_meta_path
    from .projects import _project_relative_path
    from .source_boundary_contract import _episode_boundary_title_from_payload
    from .source_boundary_contract import _episode_title_from_shot_plan
    from .source_coverage import _load_source_coverage
    from .source_coverage import _write_source_coverage
    episode_id = str(episode_id or "").strip()
    if not episode_id:
        raise ValueError("缺少 episodeId")
    path = _episode_source_text_path(project_id, episode_id)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"本集原文文件不存在：episodes/{episode_id}/source.txt")

    next_text = str(text or "")
    next_text_units = content_char_count(next_text)
    now = _now()
    text_hash = _sha256_text(next_text)
    path.write_text(next_text, encoding="utf-8", newline="\n")

    source_ref_path = _episode_source_ref_path(project_id, episode_id)
    source_ref = _read_json(source_ref_path, {})
    if not isinstance(source_ref, dict):
        source_ref = {}
    source_ref.update(
        {
            "episodeId": episode_id,
            "charCount": next_text_units,
            "textHash": text_hash,
            "manualEdited": True,
            "updatedBy": "user",
            "updatedAt": now,
            "updateReason": reason,
        }
    )
    title_text = (
        _episode_boundary_title_from_payload({"title": title}, episode_id, next_text)
        or _episode_boundary_title_from_payload(
            {
                "title": source_ref.get("title"),
                "episodeTitle": source_ref.get("episodeTitle"),
                "episode_title": source_ref.get("episode_title"),
            },
            episode_id,
            next_text,
        )
        or _episode_title_from_shot_plan(project_id, episode_id)
    )
    if title_text:
        source_ref["title"] = title_text
    _write_json(source_ref_path, source_ref)

    changed_resources = ["episodeSource"]
    coverage = _load_source_coverage(project_id, source_ref.get("sourceId"))
    episode_ranges = coverage.get("episodeRanges") if isinstance(coverage.get("episodeRanges"), list) else []
    coverage_updated = False
    for item in episode_ranges:
        if not isinstance(item, dict) or str(item.get("episodeId") or item.get("episode_id") or "") != episode_id:
            continue
        item["charCount"] = next_text_units
        item["actualUnits"] = next_text_units
        item["textHash"] = text_hash
        item["manualEdited"] = True
        item["updatedAt"] = now
        if title_text:
            item["title"] = title_text
        coverage_updated = True
        break
    if coverage_updated:
        coverage["updatedAt"] = now
        _write_source_coverage(project_id, coverage)
        changed_resources.append("sourceCoverage")

    meta = _read_json(_project_meta_path(project_id), {})
    episodes = meta.get("episodes") if isinstance(meta.get("episodes"), list) else []
    meta_updated = False
    for episode in episodes:
        if not isinstance(episode, dict) or str(episode.get("id") or "") != episode_id:
            continue
        episode["wordCount"] = next_text_units
        episode["sourceRef"] = source_ref
        episode["sourcePath"] = f"episodes/{episode_id}/source.txt"
        if title_text:
            episode["title"] = title_text
        meta_updated = True
        break
    if meta_updated:
        meta["updated_at"] = now
        _write_json(_project_meta_path(project_id), meta)
        changed_resources.append("projectMeta")

    return {
        "success": True,
        "episodeId": episode_id,
        "title": title_text or episode_id,
        "text": next_text,
        "charCount": next_text_units,
        "relativePath": _project_relative_path(project_id, path) or f"episodes/{episode_id}/source.txt",
        "sourceRef": source_ref,
        "changedResources": changed_resources,
        "projectChanged": True,
    }


def _select_project_sources(
    project_id: str,
    source_id: str | None = None,
    *,
    include_supplemental: bool = False,
) -> list[dict[str, Any]]:
    sources = [
        item
        for item in list_sources(project_id)["sources"]
        if isinstance(item, dict)
    ]
    if not include_supplemental:
        sources = [item for item in sources if _is_novel_source(item)]
    if not sources:
        raise ValueError("请先上传小说文本")
    requested_source_id = str(source_id or "").strip()
    if not requested_source_id:
        return sources
    selected = [
        item
        for item in sources
        if str(item.get("id") or "") == requested_source_id
    ]
    if not selected:
        raise ValueError("未找到指定的小说文本，请重新选择后再分析概述")
    return selected


def _source_collection_title(sources: list[dict[str, Any]]) -> str:
    titles = [
        str(item.get("title") or "小说文本").strip() or "小说文本"
        for item in sources
    ]
    if not titles:
        return "小说文本"
    if len(titles) == 1:
        return titles[0]
    preview = "、".join(f"《{title}》" for title in titles[:3])
    suffix = "…" if len(titles) > 3 else ""
    return f"{len(titles)} 部小说合集：{preview}{suffix}"


def _source_collection_text(project_id: str, sources: list[dict[str, Any]]) -> tuple[str, str, int]:
    chunks: list[str] = []
    total_word_count = 0
    for item in sources:
        title = str(item.get("title") or "小说文本").strip() or "小说文本"
        content = _read_source_content(project_id, item).strip()
        if not content:
            continue
        chunks.append(f"--- {title} ---\n{content}")
        total_word_count += content_char_count(content)
    combined_text = "\n\n".join(chunks).strip()
    if not combined_text:
        raise ValueError("小说文本为空，请重新添加包含正文的 .txt 文件")
    return _source_collection_title(sources), combined_text, total_word_count


def create_source(project_id: str, source: dict[str, Any], on_conflict: str | None = None) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    from .agent_sessions import _project_meta_path
    from .store_core import _display_time
    from .source_coverage import _load_source_coverage
    from .source_index import build_source_index
    sources = list_sources(project_id)["sources"]
    content = _source_payload_content(source)
    title = str(source.get("title") or "未命名源文件").strip() or "未命名源文件"
    source_group = _source_group(source)
    conflict_policy = str(on_conflict or source.get("onConflict") or source.get("on_conflict") or "fail").strip().lower()
    conflict_policy = conflict_policy if conflict_policy in {"fail", "replace", "rename"} else "fail"
    normalized_title = title.casefold()
    duplicate = next(
        (
            item
            for item in sources
            if _source_group(item) == source_group
            and str(item.get("title") or "").strip().casefold() == normalized_title
        ),
        None,
    )
    if duplicate and conflict_policy == "fail":
        return {
            "success": False,
            "code": "source_conflict",
            "message": f"项目中已存在同名小说「{title}」",
            "conflict": duplicate,
        }
    if duplicate and conflict_policy == "replace":
        duplicate_path = _source_content_path(project_id, duplicate)
        if duplicate_path and duplicate_path.exists() and duplicate_path.is_file():
            duplicate_path.unlink()
        duplicate_id = str(duplicate.get("id") or "")
        sources = [
            item
            for item in sources
            if not isinstance(item, dict) or str(item.get("id") or "") != duplicate_id
        ]
    if duplicate and conflict_policy == "rename":
        existing_titles = {
            str(item.get("title") or "").strip().casefold()
            for item in sources
            if isinstance(item, dict) and _source_group(item) == source_group
        }
        index = 2
        next_title = f"{title} ({index})"
        while next_title.casefold() in existing_titles:
            index += 1
            next_title = f"{title} ({index})"
        title = next_title
    source_id = f"src-{uuid.uuid4().hex[:8]}"
    if source_group == SOURCE_GROUP_SUPPLEMENTAL:
        content_path, stored_content_path = _source_storage_path(project_id, source, sources)
    else:
        content_path = _project_dir(project_id) / "sources" / f"{source_id}.txt"
        stored_content_path = content_path.name
    content_path.parent.mkdir(parents=True, exist_ok=True)
    content_path.write_text(content, encoding="utf-8", newline="\n")
    content_units = content_char_count(content)
    item = {
        "id": source_id,
        "title": title,
        "kind": str(source.get("kind") or "Text"),
        "sourceGroup": source_group,
        "status": "ready",
        "wordCount": content_units,
        "charCount": content_units,
        "excerpt": content[:120],
        "rawFilename": str(source.get("rawFilename") or source.get("raw_filename") or source.get("title") or ""),
        "contentPath": stored_content_path,
        "relativePath": f"sources/{stored_content_path}",
        "createdAt": _display_time(_now()),
    }
    if source_group == SOURCE_GROUP_NOVEL and content:
        item["appendSegments"] = [
            _source_segment_from_text(
                source_id=source_id,
                title=title,
                raw_filename=item["rawFilename"] or title,
                text=content,
                start=0,
                kind="initial",
                created_at=item["createdAt"],
            )
        ]
        _write_source_total_backup(project_id, item, content)
    sources.append(item)
    _write_json(_project_dir(project_id) / "sources" / "sources.json", sources)
    meta = _read_json(_project_meta_path(project_id), {})
    if source_group == SOURCE_GROUP_NOVEL:
        novel_sources = [
            row
            for row in sources
            if isinstance(row, dict) and _is_novel_source(row)
        ]
        source_refs = _source_refs_for_meta(novel_sources)
        total_word_count = sum(int(ref.get("wordCount") or 0) for ref in source_refs)
        meta["source_count"] = len(novel_sources)
        meta["word_count"] = total_word_count
        meta["wordCount"] = total_word_count
        meta["sources"] = source_refs
        if source_refs:
            current_source_id = str((meta.get("source") or {}).get("id") or "")
            meta["source"] = next(
                (ref for ref in source_refs if ref.get("id") == current_source_id),
                source_refs[0],
            )
        else:
            meta.pop("source", None)
    meta["updated_at"] = _now()
    _write_json(_project_meta_path(project_id), meta)
    if source_group == SOURCE_GROUP_NOVEL:
        build_source_index(project_id)
        _load_source_coverage(project_id)
    return {"success": True, "source": item}


def replace_sources(project_id: str, new_sources: list[dict[str, Any]]) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    from .agent_sessions import _project_meta_path
    from .project_overview import _sync_project_theme_visual_context
    from .source_coverage import _load_source_coverage
    from .source_coverage import _reset_source_planning_state
    from .source_index import build_source_index
    if not isinstance(new_sources, list) or not new_sources:
        raise ValueError("请至少选择一个 .txt 小说文本")
    if len([source for source in new_sources if isinstance(source, dict)]) > 1:
        raise ValueError("初次导入阶段只能选择一个小说总文件，后续章节请在项目概览的原文件列表中追加")
    normalized_sources: list[dict[str, Any]] = []
    for source in new_sources:
        if not isinstance(source, dict):
            continue
        content = _source_payload_content(source)
        if not content.strip():
            raise ValueError("小说文本为空，请选择包含正文的 .txt 文件")
        normalized_sources.append(
            {
                **source,
                "title": str(source.get("title") or "未命名源文件").strip() or "未命名源文件",
                "content": content,
                "kind": str(source.get("kind") or "TXT"),
            }
        )
    if not normalized_sources:
        raise ValueError("请至少选择一个 .txt 小说文本")

    existing_sources = [
        item
        for item in list_sources(project_id)["sources"]
        if isinstance(item, dict)
    ]
    supplemental_sources = [item for item in existing_sources if not _is_novel_source(item)]
    for item in existing_sources:
        if not isinstance(item, dict):
            continue
        if not _is_novel_source(item):
            continue
        content_path = _source_content_path(project_id, item)
        if content_path and content_path.exists() and content_path.is_file():
            content_path.unlink()
    _write_json(_project_dir(project_id) / "sources" / "sources.json", supplemental_sources)
    _reset_source_planning_state(project_id)

    created: list[dict[str, Any]] = []
    for source in normalized_sources:
        result = create_source(project_id, source, "rename")
        if result.get("success") and isinstance(result.get("source"), dict):
            created.append(result["source"])
    if not created:
        raise RuntimeError("小说文本保存失败，请重新选择 .txt 文件")
    source_refs = _source_refs_for_meta(created)
    total_word_count = sum(int(ref.get("wordCount") or 0) for ref in source_refs)
    meta = _read_json(_project_meta_path(project_id), {})
    source_title = _source_collection_title(created)
    meta["source_count"] = len(created)
    meta["word_count"] = total_word_count
    meta["wordCount"] = total_word_count
    meta["source"] = source_refs[0] if source_refs else None
    meta["sources"] = source_refs
    meta["summary"] = f"已添加{source_title}，等待小说概述分析"
    meta["status_type"] = "running"
    meta["status"] = "小说文本已添加，等待分析概述"
    meta.pop("overview_analysis", None)
    _sync_project_theme_visual_context(project_id, meta, "")
    meta["updated_at"] = _now()
    _write_json(_project_meta_path(project_id), meta)
    build_source_index(project_id)
    _load_source_coverage(project_id)
    return {"success": True, "sources": created}


def _project_source_text(project_id: str, source_id: str | None = None) -> tuple[str, str, int]:
    sources = _select_project_sources(project_id, source_id)
    return _source_collection_text(project_id, sources)


def _compact_text(value: str, limit: int = 80) -> str:
    """Lossy display helper for source lists/previews only.

    Full source content must be read through source window/content APIs. Do not
    use this helper for model prompts, provider payloads, or canonical storage.
    """
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] + ("..." if len(text) > limit else "")
