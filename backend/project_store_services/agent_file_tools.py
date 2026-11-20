# -*- coding: utf-8 -*-
"""项目文件读取、搜索、文件名预览及媒体工具参数与调用。"""

from __future__ import annotations

from .catalogs import (
    AGENT_ATTACHMENT_MAX_BYTES,
    DEFAULT_ASSETS,
    MEDIA_TOOL_DEFAULT_ROOTS,
)
from .source_text_store import _compact_text
from .store_core import (
    ASSET_LIFECYCLE_ACTIVE,
    _filter_asset_store_by_lifecycle,
    _read_json,
)
from .task_control import (
    _update_task_fields,
    create_task,
)
from utils.image_pipeline import (
    prepare_provider_image_bytes,
)

from .agent_sessions import (
    _project_dir,
)
from .catalogs import (
    MEDIA_TOOL_FILE_EXTENSIONS,
    MEDIA_TOOL_MAX_ARGS,
    MEDIA_TOOL_STDIO_LIMIT,
    VIDEO_EXTENSIONS,
)

import base64
import copy
import json
import mimetypes
import re
import shutil
import subprocess
import traceback
import zipfile
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .agent_sessions import _mime_from_file_suffix
from .catalogs import IMAGE_EXTENSIONS

def _agent_project_file_relative_path(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root).as_posix()


def _agent_project_file_scope(
    payload: dict[str, Any] | None = None,
    *,
    trusted_scope: str | None = None,
) -> str:
    # Scope is a trust boundary: public agent tool payloads are model-controlled.
    raw_scope = str(trusted_scope or "project").strip().casefold()
    return raw_scope or "project"


def _agent_project_file_in_prefix(relative_path: str, prefixes: tuple[str, ...]) -> bool:
    normalized = relative_path.strip("/").casefold()
    for prefix in prefixes:
        allowed = prefix.strip("/").casefold()
        if normalized == allowed or normalized.startswith(f"{allowed}/"):
            return True
    return False


def _agent_project_file_scope_allows(project_root: Path, path: Path, scope: str) -> bool:
    relative_path = _agent_project_file_relative_path(project_root, path).strip("/").casefold()
    normalized_scope = str(scope or "project").strip().casefold()
    if normalized_scope in AGENT_PROJECT_FILE_ASSET_CONTEXT_SCOPES:
        allowed_paths = {
            item.strip("/").casefold()
            for item in AGENT_ASSET_CONTEXT_FILE_ALLOWED_PATHS
        }
        return (
            relative_path in allowed_paths
            or _agent_project_file_in_prefix(relative_path, AGENT_ASSET_CONTEXT_FILE_ALLOWED_PREFIXES)
        )
    if normalized_scope in AGENT_PROJECT_FILE_MEDIA_CONTEXT_SCOPES:
        return (
            _agent_project_file_in_prefix(relative_path, AGENT_MEDIA_CONTEXT_FILE_ALLOWED_PREFIXES)
            or ("/" not in relative_path and path.suffix.lower() in AGENT_MEDIA_CONTEXT_ROOT_FILE_EXTENSIONS)
        )
    return True


def _agent_project_file_default_roots(project_root: Path, scope: str) -> list[str]:
    normalized_scope = str(scope or "project").strip().casefold()
    if normalized_scope in AGENT_PROJECT_FILE_ASSET_CONTEXT_SCOPES:
        roots = [
            root
            for root in (*AGENT_ASSET_CONTEXT_FILE_ALLOWED_PREFIXES, *AGENT_ASSET_CONTEXT_FILE_ALLOWED_PATHS)
            if (project_root / root).exists()
        ]
        return roots or list(AGENT_ASSET_CONTEXT_FILE_ALLOWED_PREFIXES)
    if normalized_scope in AGENT_PROJECT_FILE_MEDIA_CONTEXT_SCOPES:
        roots = [
            root
            for root in AGENT_MEDIA_CONTEXT_FILE_ALLOWED_PREFIXES
            if (project_root / root).exists()
        ]
        return roots or ["."]
    roots = [root for root in MEDIA_TOOL_DEFAULT_ROOTS if (project_root / root).exists()]
    return roots or ["."]


def _agent_project_file_read_blocked(project_root: Path, path: Path, scope: str = "project") -> bool:
    relative_path = _agent_project_file_relative_path(project_root, path).strip("/").casefold()
    if relative_path.split("/", 1)[0] in {".git", ".agent-runtime", ".claude", "assistant"}:
        return True
    if relative_path in {".gitignore", ".gitattributes", ".gitmodules"}:
        return True
    if not _agent_project_file_scope_allows(project_root, path, scope):
        return True
    normalized_scope = str(scope or "project").strip().casefold()
    if (
        normalized_scope in AGENT_PROJECT_FILE_ASSET_CONTEXT_SCOPES
        or normalized_scope in AGENT_PROJECT_FILE_MEDIA_CONTEXT_SCOPES
    ):
        return False
    if relative_path in {
        item.strip("/").casefold()
        for item in AGENT_PROJECT_FILE_BLOCKED_READ_PATHS
    }:
        return True
    for prefix in AGENT_PROJECT_FILE_BLOCKED_READ_PREFIXES:
        blocked = prefix.strip("/").casefold()
        if relative_path == blocked or relative_path.startswith(f"{blocked}/"):
            return True
    return False


def _agent_project_file_assert_readable(project_root: Path, path: Path, scope: str = "project") -> None:
    if _agent_project_file_read_blocked(project_root, path, scope):
        normalized_scope = str(scope or "project").strip().casefold()
        if normalized_scope in AGENT_PROJECT_FILE_ASSET_CONTEXT_SCOPES:
            raise PermissionError("资产拆分只允许读取扩展资料板块和完整资产表")
        if normalized_scope in AGENT_PROJECT_FILE_MEDIA_CONTEXT_SCOPES:
            raise PermissionError("该任务只允许读取生产媒体相关项目文件")
        raise PermissionError("项目文件工具不允许读取小说源文件、源文件列表或扩展资料；小说正文请使用 source 工具")


def _agent_project_file_entry(project_root: Path, path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "relativePath": _agent_project_file_relative_path(project_root, path),
        "name": path.name,
        "suffix": path.suffix.lower(),
        "size": stat.st_size,
        "modifiedAt": int(stat.st_mtime * 1000),
    }


AGENT_PROJECT_READ_ARCHIVE_MAX_MEMBERS = 120
AGENT_PROJECT_READ_ARCHIVE_MEMBER_MAX_BYTES = 2 * 1024 * 1024
AGENT_PROJECT_READ_ARCHIVE_TOTAL_MAX_BYTES = 8 * 1024 * 1024
AGENT_PROJECT_READ_PDF_STREAM_MAX_BYTES = 4 * 1024 * 1024


def _agent_project_file_resolve_arg(project_root: Path, value: str) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ValueError("缺少文件路径")
    if "\0" in text:
        raise ValueError("文件路径不能包含 NUL 字符")
    if re.search(r"[A-Za-z][A-Za-z0-9+.-]*://", text):
        raise ValueError("读取工具不允许访问外部 URL")
    if re.search(r"(^|[\\/])\.\.([\\/]|$)", text):
        raise ValueError("读取工具不允许使用 .. 越界路径")
    raw_path = Path(text)
    path = raw_path if raw_path.is_absolute() else project_root / raw_path
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("读取文件必须位于当前项目目录内") from exc
    return resolved


def _agent_decode_text_bytes(raw: bytes) -> tuple[str, str, bool]:
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding), encoding, False
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replace", True


def _agent_compact_read_text(text: str, max_chars: int) -> tuple[str, bool]:
    limit = max(1, min(int(max_chars or 60000), 200000))
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _agent_file_mime(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS or suffix == ".gif":
        return _mime_from_file_suffix(path, "image/*")
    return "application/octet-stream"


def _agent_xml_text(value: str) -> str:
    try:
        root = ET.fromstring(value)
    except ET.ParseError:
        return ""
    texts = [str(item or "").strip() for item in root.itertext() if str(item or "").strip()]
    return "\n".join(texts)


def _agent_zip_member_texts(path: Path, prefixes: tuple[str, ...], suffix: str = ".xml") -> list[str]:
    rows: list[str] = []
    total_bytes = 0
    member_count = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = info.filename
            normalized = name.replace("\\", "/")
            if not normalized.lower().endswith(suffix):
                continue
            if prefixes and not any(normalized.startswith(prefix) for prefix in prefixes):
                continue
            member_count += 1
            if member_count > AGENT_PROJECT_READ_ARCHIVE_MAX_MEMBERS:
                break
            if total_bytes >= AGENT_PROJECT_READ_ARCHIVE_TOTAL_MAX_BYTES:
                break
            member_limit = min(
                AGENT_PROJECT_READ_ARCHIVE_MEMBER_MAX_BYTES,
                AGENT_PROJECT_READ_ARCHIVE_TOTAL_MAX_BYTES - total_bytes,
            )
            if info.file_size > member_limit:
                continue
            try:
                with archive.open(info) as member:
                    raw = member.read(member_limit + 1)
            except KeyError:
                continue
            if len(raw) > member_limit:
                continue
            total_bytes += len(raw)
            text, _encoding, _lossy = _agent_decode_text_bytes(raw)
            extracted = _agent_xml_text(text)
            if extracted:
                rows.append(extracted)
    return rows


def _agent_extract_office_text(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        rows = _agent_zip_member_texts(path, ("word/document.xml", "word/header", "word/footer"))
        return "\n\n".join(rows), "docx-zip-xml"
    if suffix == ".pptx":
        rows = _agent_zip_member_texts(path, ("ppt/slides/", "ppt/notesSlides/"))
        return "\n\n".join(rows), "pptx-zip-xml"
    if suffix == ".xlsx":
        rows = _agent_zip_member_texts(path, ("xl/sharedStrings.xml", "xl/worksheets/"))
        return "\n\n".join(rows), "xlsx-zip-xml"
    return "", ""


def _agent_pdf_literal_text(value: bytes) -> str:
    output = bytearray()
    index = 0
    length = len(value)
    while index < length:
        byte = value[index]
        if byte != 0x5C:
            output.append(byte)
            index += 1
            continue
        index += 1
        if index >= length:
            break
        escaped = value[index]
        index += 1
        if escaped in b"nrtbf":
            output.append({ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}[escaped])
        elif escaped in b"()\\":
            output.append(escaped)
        elif escaped in b"\r\n":
            if escaped == 13 and index < length and value[index] == 10:
                index += 1
        elif 48 <= escaped <= 55:
            octal = bytes([escaped])
            while index < length and len(octal) < 3 and 48 <= value[index] <= 55:
                octal += bytes([value[index]])
                index += 1
            try:
                output.append(int(octal, 8) & 0xFF)
            except ValueError:
                pass
        else:
            output.append(escaped)
    text, _encoding, _lossy = _agent_decode_text_bytes(bytes(output))
    return text.strip()


def _agent_pdf_hex_text(value: bytes) -> str:
    cleaned = re.sub(rb"\s+", b"", value)
    if len(cleaned) % 2:
        cleaned += b"0"
    try:
        raw = bytes.fromhex(cleaned.decode("ascii"))
    except Exception:
        return ""
    if raw.startswith(b"\xfe\xff"):
        try:
            return raw[2:].decode("utf-16-be").strip()
        except UnicodeDecodeError:
            return ""
    text, _encoding, _lossy = _agent_decode_text_bytes(raw)
    return text.strip()


def _agent_extract_pdf_text_basic(path: Path) -> str:
    raw = _agent_read_file_head(path, 20 * 1024 * 1024)
    chunks = [raw]
    for match in re.finditer(rb"stream[\r\n]+(.*?)\r?\nendstream", raw, re.DOTALL):
        payload = match.group(1).strip(b"\r\n")
        header = raw[max(0, match.start() - 700) : match.start()]
        if b"FlateDecode" in header:
            try:
                decompressor = zlib.decompressobj()
                chunks.append(decompressor.decompress(payload, AGENT_PROJECT_READ_PDF_STREAM_MAX_BYTES + 1))
            except Exception:
                continue
        else:
            chunks.append(payload[:AGENT_PROJECT_READ_PDF_STREAM_MAX_BYTES])

    rows: list[str] = []
    for chunk in chunks:
        for match in re.finditer(rb"\(((?:\\.|[^\\)])*)\)\s*(?:Tj|'|\")", chunk, re.DOTALL):
            text = _agent_pdf_literal_text(match.group(1))
            if text:
                rows.append(text)
        for match in re.finditer(rb"<([0-9A-Fa-f\s]+)>\s*(?:Tj|'|\")", chunk, re.DOTALL):
            text = _agent_pdf_hex_text(match.group(1))
            if text:
                rows.append(text)
        for match in re.finditer(rb"\[(.*?)\]\s*TJ", chunk, re.DOTALL):
            array = match.group(1)
            parts: list[str] = []
            for literal in re.finditer(rb"\(((?:\\.|[^\\)])*)\)", array, re.DOTALL):
                text = _agent_pdf_literal_text(literal.group(1))
                if text:
                    parts.append(text)
            for hex_text in re.finditer(rb"<([0-9A-Fa-f\s]+)>", array, re.DOTALL):
                text = _agent_pdf_hex_text(hex_text.group(1))
                if text:
                    parts.append(text)
            if parts:
                rows.append("".join(parts))
    compacted = [re.sub(r"\s+", " ", item).strip() for item in rows if item.strip()]
    return "\n".join(dict.fromkeys(item for item in compacted if item))


def _agent_extract_pdf_text(path: Path) -> tuple[str, str]:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages[:40]:
            pages.append(page.extract_text() or "")
        text = "\n\n".join(item for item in pages if item.strip())
        if text.strip():
            return text, "pypdf"
    except Exception:
        pass
    try:
        text = _agent_extract_pdf_text_basic(path)
        if text.strip():
            return text, "pdf-basic-scan"
    except Exception:
        pass
    return "", "pdf-metadata-only"


def _agent_read_file_head(path: Path, max_bytes: int = 1024 * 1024) -> bytes:
    limit = max(1, int(max_bytes or 1024 * 1024))
    with path.open("rb") as handle:
        return handle.read(limit)


def _agent_image_metadata(path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as image:
            metadata.update(
                {
                    "width": image.width,
                    "height": image.height,
                    "mode": image.mode,
                    "format": image.format,
                }
            )
    except Exception as exc:  # noqa: BLE001
        metadata["metadataWarning"] = str(exc)
    return metadata


def _agent_binary_preview(raw: bytes, max_bytes: int = 96) -> str:
    return raw[:max_bytes].hex(" ")


def read_project_file_for_agent(
    project_id: str,
    payload: dict[str, Any] | None = None,
    *,
    trusted_scope: str | None = None,
) -> dict[str, Any]:
    args = payload if isinstance(payload, dict) else {}
    project_root = _agent_media_tool_project_root(project_id)
    scope = _agent_project_file_scope(args, trusted_scope=trusted_scope)
    raw_path = (
        args.get("file")
        or args.get("path")
        or args.get("relativePath")
        or args.get("relative_path")
        or args.get("filePath")
        or args.get("file_path")
    )
    path = _agent_project_file_resolve_arg(project_root, str(raw_path or ""))
    _agent_project_file_assert_readable(project_root, path, scope)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError("项目文件不存在")
    stat = path.stat()
    max_chars = _agent_media_tool_int(args.get("maxChars") or args.get("max_chars"), default=60000, minimum=1000, maximum=200000)
    include_image = str(args.get("includeImage") if "includeImage" in args else args.get("include_image") if "include_image" in args else "true").strip().lower() not in {"false", "0", "no"}
    relative_path = path.resolve().relative_to(project_root).as_posix()
    suffix = path.suffix.lower()
    mime_type = _agent_file_mime(path)
    file_info = {
        "relativePath": relative_path,
        "name": path.name,
        "suffix": suffix,
        "mimeType": mime_type,
        "size": stat.st_size,
        "modifiedAt": int(stat.st_mtime * 1000),
    }

    if relative_path.strip("/").casefold() == "assets/assets.json":
        try:
            text = json.dumps(
                _filter_asset_store_by_lifecycle(_read_json(path, DEFAULT_ASSETS), ASSET_LIFECYCLE_ACTIVE),
                ensure_ascii=False,
                indent=2,
            )
        except Exception:
            text = ""
        text, truncated = _agent_compact_read_text(text, max_chars)
        return {
            "success": True,
            "scope": scope,
            "file": file_info,
            "kind": "json",
            "text": text,
            "encoding": "utf-8",
            "extractor": "active-assets-json",
            "truncated": truncated,
        }

    if suffix in IMAGE_EXTENSIONS or suffix in {".gif"} or mime_type.startswith("image/"):
        image_meta = _agent_image_metadata(path)
        content_blocks: list[dict[str, Any]] = []
        image_content_unavailable_reason = ""
        if include_image and stat.st_size <= AGENT_ATTACHMENT_MAX_BYTES:
            raw = path.read_bytes()
            prepared = prepare_provider_image_bytes(
                raw,
                purpose="agent-read-project-image",
                max_bytes=AGENT_ATTACHMENT_MAX_BYTES,
                preserve_alpha=True,
            )
            content_blocks.append(
                {
                    "type": "image",
                    "data": base64.b64encode(prepared.data).decode("ascii"),
                    "mimeType": prepared.prepared_mime,
                }
            )
        elif not include_image:
            image_content_unavailable_reason = "include_image_false"
        elif stat.st_size > AGENT_ATTACHMENT_MAX_BYTES:
            image_content_unavailable_reason = "file_too_large"
        return {
            "success": True,
            "scope": scope,
            "file": {**file_info, **image_meta},
            "kind": "image",
            "text": "",
            "encoding": "",
            "extractor": "pillow-metadata" if image_meta else "image-bytes",
            "truncated": False,
            "imageContentRequested": include_image,
            "imageContentIncluded": bool(content_blocks),
            "imageContentUnavailableReason": image_content_unavailable_reason,
            "attachmentMaxBytes": AGENT_ATTACHMENT_MAX_BYTES,
            "mcpContent": content_blocks,
        }

    if suffix == ".pdf" or mime_type == "application/pdf":
        text, extractor = _agent_extract_pdf_text(path)
        text, truncated = _agent_compact_read_text(text, max_chars)
        return {
            "success": True,
            "scope": scope,
            "file": file_info,
            "kind": "pdf",
            "text": text,
            "encoding": "",
            "extractor": extractor,
            "truncated": truncated,
            "binaryPreview": _agent_binary_preview(_agent_read_file_head(path, 96)) if not text else "",
        }

    if suffix in {".docx", ".pptx", ".xlsx"}:
        text, extractor = _agent_extract_office_text(path)
        text, truncated = _agent_compact_read_text(text, max_chars)
        return {
            "success": True,
            "scope": scope,
            "file": file_info,
            "kind": "office",
            "text": text,
            "encoding": "",
            "extractor": extractor,
            "truncated": truncated,
            "binaryPreview": _agent_binary_preview(_agent_read_file_head(path, 96)) if not text else "",
        }

    text_read_bytes = max(4096, min(max(max_chars * 4, 1024 * 1024), 4 * 1024 * 1024))
    raw = _agent_read_file_head(path, text_read_bytes)
    bytes_truncated = stat.st_size > len(raw)
    text, encoding, lossy = _agent_decode_text_bytes(raw)
    decoded_has_binary_markers = "\0" in text[:4000]
    if not decoded_has_binary_markers:
        text, chars_truncated = _agent_compact_read_text(text, max_chars)
        return {
            "success": True,
            "scope": scope,
            "file": file_info,
            "kind": "text",
            "text": text,
            "encoding": encoding,
            "lossy": lossy,
            "extractor": "text-decode",
            "truncated": bool(bytes_truncated or chars_truncated),
        }

    return {
        "success": True,
        "scope": scope,
        "file": file_info,
        "kind": "binary",
        "text": "",
        "encoding": "",
        "extractor": "binary-preview",
        "truncated": False,
        "binaryPreview": _agent_binary_preview(raw),
    }


def search_project_files_for_agent(
    project_id: str,
    payload: dict[str, Any] | None = None,
    *,
    trusted_scope: str | None = None,
) -> dict[str, Any]:
    args = payload if isinstance(payload, dict) else {}
    project_root = _agent_media_tool_project_root(project_id)
    scope = _agent_project_file_scope(args, trusted_scope=trusted_scope)
    query = str(args.get("query") or args.get("q") or "").strip()
    roots = args.get("roots")
    if not isinstance(roots, list) or not roots:
        roots = _agent_project_file_default_roots(project_root, scope)
    extensions = args.get("extensions")
    extension_filter = {
        (str(item).strip().lower() if str(item).strip().startswith(".") else f".{str(item).strip().lower()}")
        for item in (extensions if isinstance(extensions, list) else [])
        if str(item or "").strip()
    }
    max_files = _agent_media_tool_int(args.get("maxFiles") or args.get("max_files"), default=120, minimum=1, maximum=500)
    max_matches = _agent_media_tool_int(args.get("maxMatches") or args.get("max_matches"), default=80, minimum=1, maximum=300)
    matches: list[dict[str, Any]] = []
    query_lower = query.lower()
    seen: set[str] = set()
    for root_value in roots:
        root_path = _agent_project_file_resolve_arg(project_root, str(root_value or "."))
        if not root_path.exists():
            continue
        paths = [root_path] if root_path.is_file() else [item for item in root_path.rglob("*") if item.is_file()]
        for path in paths:
            if _agent_project_file_read_blocked(project_root, path, scope):
                continue
            suffix = path.suffix.lower()
            if extension_filter and suffix not in extension_filter:
                continue
            try:
                relative_path = _agent_project_file_relative_path(project_root, path)
            except ValueError:
                continue
            if relative_path in seen:
                continue
            seen.add(relative_path)
            name_hit = bool(query_lower and query_lower in relative_path.lower())
            row = _agent_project_file_entry(project_root, path)
            row["matchType"] = "name" if name_hit else ""
            if name_hit:
                matches.append(row)
            if query_lower and len(matches) < max_matches and path.stat().st_size <= 1024 * 1024:
                try:
                    text, encoding, _lossy = _agent_decode_text_bytes(path.read_bytes())
                except Exception:
                    text = ""
                    encoding = ""
                if "\0" not in text[:4000]:
                    for index, line in enumerate(text.splitlines(), start=1):
                        if query_lower in line.lower():
                            text_row = dict(row)
                            text_row.update(
                                {
                                    "matchType": "content",
                                    "line": index,
                                    "encoding": encoding,
                                    "preview": _compact_text(line, 260),
                                }
                            )
                            matches.append(text_row)
                            break
            elif not query_lower:
                matches.append(row)
            if len(matches) >= max_matches or len(seen) >= max_files:
                return {
                    "success": True,
                    "scope": scope,
                    "projectDir": str(project_root),
                    "query": query,
                    "matches": matches[:max_matches],
                    "truncated": True,
                    "maxFiles": max_files,
                    "maxMatches": max_matches,
                }
    return {
        "success": True,
        "scope": scope,
        "projectDir": str(project_root),
        "query": query,
        "matches": matches[:max_matches],
        "truncated": False,
        "maxFiles": max_files,
        "maxMatches": max_matches,
    }


def list_project_files_for_agent(
    project_id: str,
    payload: dict[str, Any] | None = None,
    *,
    trusted_scope: str | None = None,
) -> dict[str, Any]:
    args = payload if isinstance(payload, dict) else {}
    project_root = _agent_media_tool_project_root(project_id)
    scope = _agent_project_file_scope(args, trusted_scope=trusted_scope)
    roots = args.get("roots")
    if not isinstance(roots, list) or not roots:
        roots = _agent_project_file_default_roots(project_root, scope)
    extensions = args.get("extensions")
    extension_filter = {
        (str(item).strip().lower() if str(item).strip().startswith(".") else f".{str(item).strip().lower()}")
        for item in (extensions if isinstance(extensions, list) else [])
        if str(item or "").strip()
    }
    max_files = _agent_media_tool_int(args.get("maxFiles") or args.get("max_files"), default=120, minimum=1, maximum=300)
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root_value in roots:
        root_text = str(root_value or "").strip() or "."
        _agent_media_tool_reject_unsafe_text(root_text)
        root_path = _agent_media_tool_resolve_arg(project_root, root_text)
        if not root_path.exists():
            continue
        paths = [root_path] if root_path.is_file() else [item for item in root_path.rglob("*") if item.is_file()]
        for path in paths:
            if _agent_project_file_read_blocked(project_root, path, scope):
                continue
            suffix = path.suffix.lower()
            if extension_filter and suffix not in extension_filter:
                continue
            relative_path = _agent_project_file_relative_path(project_root, path)
            if relative_path in seen:
                continue
            seen.add(relative_path)
            files.append(_agent_project_file_entry(project_root, path))
            if len(files) >= max_files:
                return {
                    "success": True,
                    "scope": scope,
                    "projectDir": str(project_root),
                    "files": files,
                    "truncated": True,
                    "maxFiles": max_files,
                }
    return {
        "success": True,
        "scope": scope,
        "projectDir": str(project_root),
        "files": files,
        "truncated": False,
        "maxFiles": max_files,
    }


def run_project_media_tool(project_id: str, executable_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    args = payload if isinstance(payload, dict) else {}
    executable = executable_name.strip().lower()
    if executable not in {"ffmpeg", "ffprobe"}:
        raise ValueError("只允许运行 ffmpeg 或 ffprobe")
    executable_path = shutil.which(executable)
    if not executable_path:
        raise FileNotFoundError(f"未找到 {executable} 可执行文件")
    default_timeout = 60 if executable == "ffprobe" else 300
    max_timeout = 300 if executable == "ffprobe" else 1800
    timeout_seconds = _agent_media_tool_int(
        args.get("timeoutSeconds") or args.get("timeout_seconds"),
        default=default_timeout,
        minimum=1,
        maximum=max_timeout,
    )
    project_root, command_args = _agent_media_tool_args(project_id, args.get("args"))
    command = [executable_path, *command_args]
    try:
        completed = subprocess.run(
            command,
            cwd=str(project_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
        )
        success = completed.returncode == 0
        message = f"{executable} 执行{'完成' if success else '失败'}。"
        task = create_task(
            "media_tool",
            project_id=project_id,
            message=message,
            status="completed" if success else "failed",
            progress=100,
        )
        _update_task_fields(
            task.get("id"),
            executable=executable,
            command=[executable, *command_args],
            returnCode=completed.returncode,
        )
        return {
            "success": success,
            "executable": executable,
            "executablePath": executable_path,
            "args": command_args,
            "cwd": str(project_root),
            "returnCode": completed.returncode,
            "stdout": _truncate_process_text(completed.stdout),
            "stderr": _truncate_process_text(completed.stderr),
            "timeoutSeconds": timeout_seconds,
            "task": task,
        }
    except subprocess.TimeoutExpired as exc:
        task = create_task(
            "media_tool",
            project_id=project_id,
            message=f"{executable} 执行超时。",
            status="failed",
            progress=100,
        )
        _update_task_fields(
            task.get("id"),
            executable=executable,
            command=[executable, *command_args],
            timedOut=True,
        )
        return {
            "success": False,
            "executable": executable,
            "executablePath": executable_path,
            "args": command_args,
            "cwd": str(project_root),
            "returnCode": None,
            "stdout": _truncate_process_text(exc.stdout),
            "stderr": _truncate_process_text(exc.stderr),
            "timeoutSeconds": timeout_seconds,
            "timedOut": True,
            "error": f"{executable} 执行超时",
            "task": task,
        }


def _truncate_process_text(value: Any, limit: int = MEDIA_TOOL_STDIO_LIMIT) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
    if len(text) <= limit:
        return text
    return text[-limit:]


def _agent_media_tool_project_root(project_id: str) -> Path:
    root = _project_dir(project_id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _agent_media_tool_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _agent_media_tool_reject_unsafe_text(value: str) -> None:
    if "\0" in value:
        raise ValueError("ffmpeg/ffprobe 参数不能包含 NUL 字符")
    if re.search(r"[A-Za-z][A-Za-z0-9+.-]*://", value):
        raise ValueError("ffmpeg/ffprobe 不允许访问外部 URL")
    if re.search(r"(^|[=,:;])([A-Za-z]:[\\/]|/|\\\\|~)", value):
        raise ValueError("ffmpeg/ffprobe 只能访问当前项目目录内的相对路径")
    if re.search(r"(^|[\\/])\.\.([\\/]|$)", value):
        raise ValueError("ffmpeg/ffprobe 参数不能包含 .. 越界路径")


def _agent_media_arg_looks_like_path(value: str) -> bool:
    if not value or value == "-" or value.startswith("-"):
        return False
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return True
    if value.startswith((".", "~", "/", "\\")):
        return True
    if "/" in value or "\\" in value:
        return "=" not in value
    return Path(value).suffix.lower() in MEDIA_TOOL_FILE_EXTENSIONS


def _agent_media_tool_resolve_arg(project_root: Path, value: str) -> Path:
    raw_path = Path(value)
    path = raw_path if raw_path.is_absolute() else project_root / raw_path
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("ffmpeg/ffprobe 文件路径必须位于当前项目目录内") from exc
    return resolved


def _agent_media_tool_args(project_id: str, args: Any) -> tuple[Path, list[str]]:
    if not isinstance(args, list) or not args:
        raise ValueError("请提供 ffmpeg/ffprobe 参数数组")
    if len(args) > MEDIA_TOOL_MAX_ARGS:
        raise ValueError(f"ffmpeg/ffprobe 参数过多，最多 {MEDIA_TOOL_MAX_ARGS} 个")
    project_root = _agent_media_tool_project_root(project_id)
    normalized: list[str] = []
    for value in args:
        text = str(value or "").strip()
        if not text:
            raise ValueError("ffmpeg/ffprobe 参数不能为空")
        if text.lower() in {"ffmpeg", "ffmpeg.exe", "ffprobe", "ffprobe.exe"}:
            raise ValueError("args 里不要包含可执行文件名")
        _agent_media_tool_reject_unsafe_text(text)
        if _agent_media_arg_looks_like_path(text):
            path = _agent_media_tool_resolve_arg(project_root, text)
            path.parent.mkdir(parents=True, exist_ok=True)
        normalized.append(text)
    return project_root, normalized


AGENT_PROJECT_FILE_BLOCKED_READ_PATHS = ("sources/sources.json",)


AGENT_PROJECT_FILE_BLOCKED_READ_PREFIXES = (
    "sources",
    "sources/.source-backups",
    "sources/materials",
)


AGENT_ASSET_CONTEXT_FILE_ALLOWED_PATHS = ("assets/assets.json",)


AGENT_ASSET_CONTEXT_FILE_ALLOWED_PREFIXES = ("sources/materials",)


AGENT_MEDIA_CONTEXT_FILE_ALLOWED_PREFIXES = (
    "assets",
    "episodes",
    "exports",
    "generated",
    "media",
    "temp",
)


AGENT_MEDIA_CONTEXT_ROOT_FILE_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


AGENT_PROJECT_FILE_ASSET_CONTEXT_SCOPES = {
    "asset_context",
    "asset_extraction",
    "asset_materials",
    "analyze_assets",
}


AGENT_PROJECT_FILE_MEDIA_CONTEXT_SCOPES = {
    "media_context",
    "production_media",
    "video_task",
    "video_task_media",
}
