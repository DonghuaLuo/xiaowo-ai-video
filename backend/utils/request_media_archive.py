"""Persist final media bytes in each model request's independent archive."""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import threading
import traceback
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote_to_bytes

_DIRECTORY_LOCK = threading.Lock()
_ACTIVE_DIRECTORIES: dict[Path, int] = {}


@contextmanager
def log_directory_activity(directory: Path):
    """Protect only directory lifetime, never hold the lock during media I/O."""
    directory = directory.resolve()
    with _DIRECTORY_LOCK:
        _ACTIVE_DIRECTORIES[directory] = _ACTIVE_DIRECTORIES.get(directory, 0) + 1
    try:
        yield
    finally:
        with _DIRECTORY_LOCK:
            remaining = _ACTIVE_DIRECTORIES[directory] - 1
            if remaining:
                _ACTIVE_DIRECTORIES[directory] = remaining
            else:
                del _ACTIVE_DIRECTORIES[directory]


def remove_empty_log_directory(directory: Path) -> bool:
    directory = directory.resolve()
    with _DIRECTORY_LOCK:
        if any(active.is_relative_to(directory) or directory.is_relative_to(active)
               for active in _ACTIVE_DIRECTORIES):
            return False
        if any(directory.iterdir()):
            return False
        directory.rmdir()
        return True


def _remove_temporary(path: Path | None) -> None:
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            traceback.print_exc()


def archive_uploaded_media(source: Path, remote: dict[str, Any], directory: Path, *, media_kind: str = "video") -> dict[str, Any]:
    """Keep the exact uploaded file before a transcoder removes its temporary output."""
    with log_directory_activity(directory):
        return _archive_uploaded_media(source, remote, directory, media_kind=media_kind)


def _archive_uploaded_media(source: Path, remote: dict[str, Any], directory: Path, *, media_kind: str = "video") -> dict[str, Any]:
    entry = {"__type": "media_reference", "mediaKind": media_kind, "sourceRole": f"reference_{media_kind}",
             "sourceUrl": remote.get("url", ""), "captureEncoding": "url",
             "mimeType": remote.get("contentType") or ("audio/wav" if media_kind == "audio" else "video/mp4")}
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / (uuid.uuid4().hex + ".tmp")
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as reader, temporary.open("wb") as writer:
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        sha = digest.hexdigest()
        if not remote.get("sha256") or sha != remote["sha256"]:
            raise ValueError("视频片段附件与已上传文件的 SHA-256 不一致")
        target = directory / (sha + "-" + uuid.uuid4().hex + media_suffix(entry["mimeType"]))
        os.replace(temporary, target)
        return {**entry, "stagedFile": str(target.resolve()), "sha256": sha, "byteLength": size,
                "captureStatus": "exact-uploaded-bytes"}
    except Exception as exc:
        traceback.print_exc()
        return {**entry, "captureStatus": "failed", "captureError": str(exc)}
    finally:
        _remove_temporary(temporary)


def with_transport_media(callback: Any, references: list[dict[str, Any]] | None) -> Any:
    """Enrich only diagnostic metadata; provider body/URLs remain untouched."""
    if callback is None or not references:
        return callback

    def prepared(info: dict[str, Any]) -> None:
        def strings(value: Any):
            if isinstance(value, dict):
                for child in value.values():
                    yield from strings(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    yield from strings(child)
            elif isinstance(value, str) and value.startswith(("https://", "http://")):
                yield value
        urls = set(strings(info.get("requestBody") or info.get("request") or {}))
        attached = [row["requestLogMedia"] for row in references
                    if isinstance(row, dict) and isinstance(row.get("requestLogMedia"), dict)
                    and row["requestLogMedia"].get("sourceUrl") in urls]
        callback({**info, "transportMedia": attached} if attached else info)
    return prepared


def copy_transport_archive(entry: dict[str, Any], directory: Path) -> dict[str, Any]:
    """Associate the prepared upload with this request's independently retained files."""
    result = {key: value for key, value in entry.items() if key != "stagedFile"}
    temporary = None
    try:
        if not entry.get("stagedFile"):
            return result
        source = Path(entry["stagedFile"]).resolve(strict=True)
        if not source.is_relative_to((directory.parents[2] / "_transport").resolve()):
            raise ValueError("视频附件不在当前项目请求日志暂存目录中")
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (entry["sha256"] + media_suffix(entry["mimeType"]))
        temporary = directory / (uuid.uuid4().hex + ".tmp")
        shutil.copyfile(source, temporary)
        with temporary.open("rb") as reader:
            digest = hashlib.sha256()
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != entry["sha256"]:
            raise ValueError("视频附件归档时 SHA-256 校验失败")
        os.replace(temporary, target)
        return {**result, "capturedFile": f"{directory.name}/{target.name}"}
    except Exception as exc:
        traceback.print_exc()
        return {**result, "captureStatus": "failed", "captureError": str(exc)}
    finally:
        _remove_temporary(temporary)


def media_bytes(value: bytes | str, mime: str = "") -> tuple[bytes, str, str, str]:
    if isinstance(value, bytes):
        raw, encoding, header = value, "bytes", ""
    elif value.startswith("data:"):
        header, encoded = value.split(",", 1)
        mime = header[5:].split(";", 1)[0]
        raw = base64.b64decode(encoded, validate=True) if ";base64" in header else unquote_to_bytes(encoded)
        encoding = "data-url"
    else:
        raw, encoding, header = base64.b64decode(value, validate=True), "base64", ""
    if not mime or mime == "application/octet-stream":
        if raw.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif raw.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            mime = "image/webp"
        elif raw[4:8] == b"ftyp":
            mime = "video/mp4"
    return raw, mime or "application/octet-stream", encoding, header


def media_suffix(mime: str) -> str:
    return {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
            "image/gif": ".gif", "video/mp4": ".mp4", "video/quicktime": ".mov",
            "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
            "audio/x-wav": ".wav", "audio/wave": ".wav"}.get(mime, ".bin")


def media_archive_writer(directory: Path) -> Callable[[Any, dict[str, Any]], dict[str, Any]]:
    def write(value: Any, entry: dict[str, Any]) -> dict[str, Any]:
        temporary = None
        try:
            raw, mime, encoding, header = media_bytes(value, entry.get("mimeType", ""))
            digest = hashlib.sha256(raw).hexdigest()
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / (digest + media_suffix(mime))
            if not path.exists():
                temporary = directory / (uuid.uuid4().hex + ".tmp")
                temporary.write_bytes(raw)
                os.replace(temporary, path)
            return {"capturedFile": f"{directory.name}/{path.name}", "sha256": digest,
                    "byteLength": len(raw), "mimeType": mime, "captureEncoding": encoding,
                    "dataUrlHeader": header, "captureStatus": "exact-request-bytes"}
        except Exception as exc:
            # Logging must not prevent the already prepared provider request.
            traceback.print_exc()
            return {"captureStatus": "failed", "captureError": str(exc)}
        finally:
            _remove_temporary(temporary)
    return write
