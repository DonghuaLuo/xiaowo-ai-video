# -*- coding: utf-8 -*-
"""智能体会话、日志、附件、消息块和实时活动快照。"""

from __future__ import annotations

import base64
import copy
import hashlib
import html
import json
import random
import re
import shutil
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.agent_context import (
    AGENT_CONTEXT_MESSAGE_TEXT_LIMIT,
    AGENT_CONTEXT_RECENT_WINDOW,
    AGENT_CONTEXT_SUMMARY_CHARS,
    build_agent_conversation_context,
)
from utils import agent_sdk_runtime
from utils.agent_session_service import AgentSessionService
from utils.aspect_size import (
    IMAGE_TIER_SHORT_EDGE,
    VIDEO_TIER_SHORT_EDGE,
    aspect_size,
    parse_aspect_ratio,
    resolution_to_short_edge,
)
from utils.image_pipeline import (
    convert_image_bytes_to_png,
    data_url_from_bytes,
    prepare_provider_image_bytes,
    prepare_provider_image_data_uri,
    save_project_image,
    save_provider_output_image,
)
from utils.media_backends import (
    cancel_video_media_job,
    endpoint_supports_media_generation,
    infer_model_endpoint,
    media_endpoint_type,
    normalize_media_endpoint,
    generate_image_media,
    generate_video_media,
    poll_video_media_job,
    provider_supports_media_generation,
    submit_video_media_job,
)

from .agent_task_catalog import _agent_known_task_types
from .agent_contracts import sanitize_agent_target_context as _sanitize_agent_target_context


from .catalogs import AGENT_ATTACHMENT_MAX_BYTES
from .catalogs import AGENT_FILE_EXTENSIONS
from .catalogs import AGENT_IMAGE_EXTENSIONS
from .catalogs import ASSET_TYPES
from .catalogs import DEFAULT_ASSETS
from .catalogs import GLOBAL_TASKS_PATH
from .catalogs import IMAGE_EXTENSIONS
from .catalogs import PROJECTS_DIR
from .runtime_state import AGENT_SESSION_HISTORY_SUMMARY_MESSAGE_LIMIT
from .runtime_state import AGENT_SESSION_MESSAGE_RETAIN_LIMIT
from .runtime_state import AGENT_STALE_RUNNING_GRACE_SECONDS
from .runtime_state import _AGENT_CANCEL_FLAGS
from .runtime_state import _AGENT_SESSION_SERVICE
from .runtime_state import _AGENT_THREADS
from .runtime_state import _AGENT_BACKEND_INSTANCE_ID
from .runtime_state import _LOCK
from .store_core import _asset_row_for_response
from .store_core import _emit_agent_event
from .store_core import _normalize_asset_type_key
from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json

def _project_dir(project_id: str) -> Path:
    if not project_id or not re.fullmatch(r"[A-Za-z0-9._-]+", project_id):
        raise ValueError("项目 ID 无效")
    from .project_deletion_guard import assert_project_available

    assert_project_available(project_id)
    return PROJECTS_DIR / project_id


def _project_meta_path(project_id: str) -> Path:
    return _project_dir(project_id) / "project.json"


def _project_config_path(project_id: str) -> Path:
    return _project_dir(project_id) / "config.json"


def _agent_session_service() -> AgentSessionService:
    global _AGENT_SESSION_SERVICE
    if _AGENT_SESSION_SERVICE is None:
        _AGENT_SESSION_SERVICE = AgentSessionService(
            project_dir=_project_dir,
            normalize_session=lambda value, project_id: _normalize_agent_session_row(value, project_id),
            snapshot_from_session=lambda project_id, session: _agent_snapshot_from_session(
                project_id,
                session,
                hydrate=False,
            ),
            recover_sessions=_recover_stale_running_agent_sessions,
            summarize_session=_agent_session_summary,
            lock=_LOCK,
        )
    return _AGENT_SESSION_SERVICE


def _agent_sessions_db_path(project_id: str) -> Path:
    return _agent_session_service().db_path(project_id)


def _agent_session_repo(project_id: str) -> Any:
    return _agent_session_service().repo(project_id)


def _agent_session_sql_failure(project_id: str, action: str, exc: Exception) -> RuntimeError:
    return _agent_session_service().sql_failure(project_id, action, exc)


def _project_agent_attachments_dir(project_id: str) -> Path:
    return _project_dir(project_id) / "assistant" / "attachments"


def _project_agent_logs_dir(project_id: str) -> Path:
    return _project_dir(project_id) / "assistant" / "logs"


def _agent_log_date_key(timestamp: str | None = None) -> str:
    if timestamp:
        return str(timestamp).split("T", 1)[0] or datetime.now(timezone.utc).date().isoformat()
    return datetime.now(timezone.utc).date().isoformat()


def _agent_log_sanitize(value: Any, *, depth: int = 0) -> Any:
    from .source_text_store import _compact_text
    if depth > 3:
        return _compact_text(str(value), 240)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _compact_text(value, 1200)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        row: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 32:
                row["..."] = f"还有 {len(value) - index} 项"
                break
            row[str(key)] = _agent_log_sanitize(item, depth=depth + 1)
        return row
    if isinstance(value, (list, tuple, set)):
        rows = list(value)
        compact_rows = [_agent_log_sanitize(item, depth=depth + 1) for item in rows[:24]]
        if len(rows) > 24:
            compact_rows.append(f"...还有 {len(rows) - 24} 项")
        return compact_rows
    return _compact_text(str(value), 500)


def append_agent_execution_error(
    project_id: str | None,
    *,
    stage: str,
    message: str,
    episode_id: str | None = None,
    session_id: str | None = None,
    category: str = "agent_execution",
    source: str = "backend",
    severity: str = "error",
    tool: str = "",
    action: str = "",
    error: BaseException | str | None = None,
    details: dict[str, Any] | None = None,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
    # 项目级智能体执行日志：只记录失败/异常，集中保存到当前项目 assistant/logs/YYYY-MM-DD.jsonl。
    # 执行日志集中保存，便于按时间复盘同一次任务的完整过程。
    from .source_text_store import _compact_text
    project_id_value = str(project_id or "").strip()
    if not project_id_value:
        return None
    timestamp = _now()
    error_text = str(error or message or "").strip()
    entry = {
        "id": f"log-{uuid.uuid4().hex[:12]}",
        "timestamp": timestamp,
        "date": _agent_log_date_key(timestamp),
        "projectId": project_id_value,
        "episodeId": str(episode_id or "").strip(),
        "sessionId": str(session_id or "").strip(),
        "severity": str(severity or "error").strip() or "error",
        "category": str(category or "agent_execution").strip() or "agent_execution",
        "stage": str(stage or "unknown").strip() or "unknown",
        "source": str(source or "backend").strip() or "backend",
        "tool": str(tool or "").strip(),
        "action": str(action or "").strip(),
        "message": _compact_text(message or error_text or "智能体执行异常", 800),
        "errorType": type(error).__name__ if isinstance(error, BaseException) else "",
        "error": _compact_text(error_text, 1200),
        "details": _agent_log_sanitize(details or {}),
    }
    if include_traceback and isinstance(error, BaseException):
        entry["traceback"] = _compact_text(traceback.format_exc(), 4000)
    try:
        logs_dir = _project_agent_logs_dir(project_id_value)
        logs_dir.mkdir(parents=True, exist_ok=True)
        path = logs_dir / f"{entry['date']}.jsonl"
        with _LOCK:
            with path.open("a", encoding="utf-8", newline="\n") as fp:
                fp.write(json.dumps(entry, ensure_ascii=False, default=str))
                fp.write("\n")
        return entry
    except Exception as log_exc:  # noqa: BLE001
        print(f"[agent-log] failed to append project log: {log_exc}", flush=True)
        return None


def list_agent_error_logs(
    project_id: str,
    *,
    limit: int = 80,
    days: int = 7,
) -> dict[str, Any]:
    limit_value = max(1, min(int(limit or 80), 300))
    day_limit = max(1, min(int(days or 7), 30))
    logs_dir = _project_agent_logs_dir(project_id)
    if not logs_dir.is_dir():
        return {"success": True, "logs": [], "files": []}
    today = datetime.now(timezone.utc).date()
    min_date = today.toordinal() - day_limit + 1
    files: list[Path] = []
    for path in logs_dir.glob("*.jsonl"):
        try:
            date_value = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if date_value.toordinal() >= min_date:
            files.append(path)
    entries: list[dict[str, Any]] = []
    for path in sorted(files, key=lambda item: item.name, reverse=True):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:  # noqa: BLE001
            append_agent_execution_error(
                project_id,
                stage="read_agent_error_logs",
                message="读取智能体错误日志失败",
                category="local_file_error",
                error=exc,
                details={"path": str(path)},
                include_traceback=True,
            )
            continue
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                row.setdefault("file", f"assistant/logs/{path.name}")
                entries.append(row)
            if len(entries) >= limit_value:
                break
        if len(entries) >= limit_value:
            break
    return {
        "success": True,
        "logs": entries[:limit_value],
        "files": [f"assistant/logs/{path.name}" for path in sorted(files, key=lambda item: item.name, reverse=True)],
    }


def clear_agent_error_logs(project_id: str) -> dict[str, Any]:
    logs_dir = _project_agent_logs_dir(project_id)
    if not logs_dir.is_dir():
        return {"success": True, "cleared": 0, "files": []}

    cleared = 0
    files: list[str] = []
    errors: list[str] = []
    with _LOCK:
        for path in sorted(logs_dir.glob("*.jsonl")):
            try:
                try:
                    cleared += sum(
                        1
                        for line in path.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    )
                except Exception:  # noqa: BLE001
                    cleared += 1
                path.unlink()
                files.append(f"assistant/logs/{path.name}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path.name}: {exc}")

    if errors:
        raise RuntimeError("部分智能体错误日志删除失败：" + "；".join(errors[:3]))

    return {"success": True, "cleared": cleared, "files": files}


def _image_suffix_from_mime_or_name(mime: str, name: str, *, allowed: set[str] | None = None) -> str:
    allowed_exts = allowed or IMAGE_EXTENSIONS
    mime_ext = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(str(mime or "").strip().lower())
    if mime_ext in allowed_exts:
        return mime_ext
    suffix = Path(str(name or "")).suffix.lower()
    if suffix in allowed_exts:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".png"


def _mime_from_image_suffix(path: Path, fallback: str = "image/png") -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".jp": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), fallback)


def _file_suffix_from_mime_or_name(mime: str, name: str, *, allowed: set[str] | None = None) -> str:
    allowed_exts = allowed or AGENT_FILE_EXTENSIONS
    mime_ext = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "text/plain": ".txt",
        "text/markdown": ".md",
        "application/json": ".json",
        "text/csv": ".csv",
        "application/pdf": ".pdf",
        "application/octet-stream": ".bin",
    }.get(str(mime or "").strip().lower())
    if mime_ext in allowed_exts:
        return mime_ext
    suffix = Path(str(name or "")).suffix.lower()
    if suffix in allowed_exts:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".bin"


def _mime_from_file_suffix(path: Path, fallback: str = "application/octet-stream") -> str:
    image_mime = _mime_from_image_suffix(path, "")
    if image_mime:
        return image_mime
    return {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".json": "application/json",
        ".csv": "text/csv",
        ".pdf": "application/pdf",
    }.get(path.suffix.lower(), fallback)


def _decode_agent_attachment_data_url(data_url: str) -> tuple[bytes, str]:
    if "," not in data_url:
        raise ValueError("智能体附件 data URL 格式无效")
    header, payload = data_url.split(",", 1)
    payload = re.sub(r"\s+", "", payload)
    match = re.match(r"data:([^;]+);base64", header)
    if not match:
        raise ValueError("智能体附件必须使用 base64 data URL")
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError("智能体附件 base64 数据无效") from exc
    return raw, match.group(1) or "application/octet-stream"


def _project_file_from_ref(project_id: str | None, value: dict[str, Any]) -> Path | None:
    if not project_id or not isinstance(value, dict):
        return None
    project_root = _project_dir(project_id).resolve()
    for key in ("relativePath", "relative_path", "file", "pngFile"):
        raw = str(value.get(key) or "").strip()
        if not raw:
            continue
        path = (project_root / raw).resolve()
        try:
            path.relative_to(project_root)
        except ValueError:
            continue
        return path
    for key in ("path", "filePath", "file_path"):
        raw = str(value.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).resolve()
        try:
            path.relative_to(project_root)
        except ValueError:
            continue
        return path
    return None


def _agent_attachment_ref_from_path(
    project_id: str,
    path: Path,
    *,
    attachment_id: str,
    name: str,
    mime_type: str,
) -> dict[str, Any] | None:
    from .projects import _project_relative_path
    if not path.is_file():
        return None
    relative_path = _project_relative_path(project_id, path)
    if not relative_path:
        return None
    return {
        "id": attachment_id,
        "name": name or path.name,
        "mimeType": mime_type or _mime_from_file_suffix(path),
        "relativePath": relative_path,
        "relative_path": relative_path,
        "file": relative_path,
        "size": path.stat().st_size,
    }


def _local_agent_attachment_source_from_media(media: dict[str, Any]) -> tuple[Path, str] | None:
    for key in ("path", "filePath", "file_path"):
        raw = str(media.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).resolve()
        if path.is_file() and path.suffix.lower() in AGENT_FILE_EXTENSIONS:
            return path, str(media.get("mimeType") or media.get("mime_type") or _mime_from_file_suffix(path))
    return None


def _save_agent_attachment_source_file(
    project_id: str,
    item: dict[str, Any],
    *,
    index: int,
) -> dict[str, Any] | None:
    from .media_files import _safe_file_stem
    path = _project_file_from_ref(project_id, item)
    local_source = None
    if path and path.is_file() and path.suffix.lower() in AGENT_FILE_EXTENSIONS:
        local_source = (path, str(item.get("mimeType") or item.get("mime_type") or _mime_from_file_suffix(path)))
    else:
        local_source = _local_agent_attachment_source_from_media(item)
    if local_source:
        path, source_mime = local_source
        attachment_id = str(item.get("id") or f"attachment-{uuid.uuid4().hex[:10]}")
        name = str(item.get("name") or item.get("originalName") or path.name or f"附件 {index + 1}").strip()
        mime_type = str(item.get("mimeType") or item.get("mime_type") or source_mime or _mime_from_file_suffix(path)).strip()
        if path.suffix.lower() in AGENT_IMAGE_EXTENSIONS:
            prepare_provider_image_bytes(path, purpose="agent-attachment-validate", preserve_alpha=True)
        suffix = _file_suffix_from_mime_or_name(mime_type, name)
        stem = _safe_file_stem(Path(name).stem or attachment_id, f"attachment-{index + 1}")
        target_dir = _project_agent_attachments_dir(project_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{stem}-{uuid.uuid4().hex[:10]}{suffix}"
        shutil.copy2(path, target_path)
        return _agent_attachment_ref_from_path(
            project_id,
            target_path,
            attachment_id=attachment_id,
            name=name,
            mime_type=mime_type or _mime_from_file_suffix(target_path),
        )

    data_url = str(item.get("dataUrl") or item.get("data_url") or item.get("storedPngDataUrl") or "").strip()
    if not data_url.startswith("data:"):
        return None
    raw, mime = _decode_agent_attachment_data_url(data_url)
    if len(raw) > AGENT_ATTACHMENT_MAX_BYTES:
        raise ValueError("智能体附件超过 8MB，无法保存")
    attachment_id = str(item.get("id") or f"attachment-{uuid.uuid4().hex[:10]}")
    name = str(item.get("name") or item.get("originalName") or f"附件 {index + 1}").strip()
    mime_type = str(item.get("mimeType") or item.get("mime_type") or mime or "application/octet-stream").strip()
    if str(mime_type or mime).startswith("image/"):
        prepare_provider_image_bytes(raw, purpose="agent-attachment-validate", preserve_alpha=True)
        suffix = _image_suffix_from_mime_or_name(mime_type or mime, name, allowed=AGENT_IMAGE_EXTENSIONS)
    else:
        suffix = _file_suffix_from_mime_or_name(mime_type or mime, name)
    stem = _safe_file_stem(Path(name).stem or attachment_id, f"attachment-{index + 1}")
    target_dir = _project_agent_attachments_dir(project_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{stem}-{uuid.uuid4().hex[:10]}{suffix}"
    path.write_bytes(raw)
    return _agent_attachment_ref_from_path(
        project_id,
        path,
        attachment_id=attachment_id,
        name=name,
        mime_type=mime_type or _mime_from_file_suffix(path),
    )


def _hydrate_agent_attachment_row(project_id: str | None, row: dict[str, Any]) -> dict[str, Any]:
    hydrated = copy.deepcopy(row)
    path = _project_file_from_ref(project_id, hydrated)
    if path and path.is_file() and path.suffix.lower() in AGENT_FILE_EXTENSIONS:
        hydrated["path"] = str(path)
        hydrated["filePath"] = str(path)
        hydrated["mimeType"] = str(hydrated.get("mimeType") or _mime_from_file_suffix(path))
    return hydrated


def _agent_message_attachment_rows(
    value: Any,
    project_id: str | None = None,
    *,
    hydrate: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value[:5]):
        if not isinstance(item, dict):
            continue
        attachment_id = str(item.get("id") or f"attachment-{index + 1}")
        name = str(item.get("name") or item.get("originalName") or f"附件 {index + 1}")
        mime_type = str(item.get("mimeType") or item.get("mime_type") or "")
        path = _project_file_from_ref(project_id, item)
        if path and path.is_file() and path.suffix.lower() in AGENT_FILE_EXTENSIONS:
            row = _agent_attachment_ref_from_path(
                project_id or "",
                path,
                attachment_id=attachment_id,
                name=name,
                mime_type=mime_type or _mime_from_file_suffix(path),
            )
        else:
            row = _save_agent_attachment_source_file(project_id, item, index=index) if project_id else None
        if not row:
            continue
        rows.append(_hydrate_agent_attachment_row(project_id, row) if hydrate else row)
    return rows


def save_agent_attachment(project_id: str, attachment: dict[str, Any]) -> dict[str, Any]:
    rows = _agent_message_attachment_rows([attachment], project_id, hydrate=True)
    if not rows:
        raise ValueError("未能保存智能体附件")
    return {"success": True, "attachment": rows[0]}


_PERSISTENT_MEDIA_DATA_KEYS = {
    "apijpegdataurl",
    "apijpegdatauri",
    "apitransport",
    "audiobase64",
    "b64",
    "b64json",
    "base64",
    "dataurl",
    "datauri",
    "imagebase64",
    "imagedata",
    "imagebytes",
    "inlineimage",
    "outputpngdataurl",
    "pngdataurl",
    "storedpngdataurl",
    "videobase64",
    "videodata",
    "videobytes",
}


def _storage_key_token(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key or "").lower())


def _is_inline_media_string(value: str) -> bool:
    return value.lstrip().lower().startswith("data:")


def _looks_like_large_base64(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    if len(compact) < 1024:
        return False
    if len(compact) % 4 != 0:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact))


def _persistent_media_data_removed(value: Any, *, key: Any = None) -> Any:
    token = _storage_key_token(key)
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_token = _storage_key_token(child_key)
            if child_token in _PERSISTENT_MEDIA_DATA_KEYS:
                continue
            if child_token == "preview" and isinstance(child_value, str) and _is_inline_media_string(child_value):
                continue
            if child_token == "data" and isinstance(child_value, str):
                if _is_inline_media_string(child_value) or _looks_like_large_base64(child_value):
                    continue
            cleaned[child_key] = _persistent_media_data_removed(child_value, key=child_key)
        return cleaned
    if isinstance(value, list):
        return [_persistent_media_data_removed(item, key=key) for item in value]
    if isinstance(value, str):
        if _is_inline_media_string(value):
            return "<redacted-inline-media>"
        if token == "data" and _looks_like_large_base64(value):
            return "<redacted-binary-media>"
    return value


def _transient_image_keys_removed(value: dict[str, Any]) -> dict[str, Any]:
    cleaned = _persistent_media_data_removed(value)
    return cleaned if isinstance(cleaned, dict) else {}


def _media_ref_for_storage(value: dict[str, Any]) -> dict[str, Any]:
    return _transient_image_keys_removed(value)


def _thumbnail_ref_for_storage(value: dict[str, Any]) -> dict[str, Any]:
    return _transient_image_keys_removed(value)


def _hydrate_media_asset_for_ui(project_id: str | None, media: Any) -> dict[str, Any] | None:
    if not isinstance(media, dict):
        return None
    hydrated = copy.deepcopy(media)
    if not project_id or hydrated.get("kind") not in {"image", "audio"}:
        return hydrated
    path = _project_file_from_ref(project_id, hydrated)
    if not path or not path.is_file():
        return hydrated
    hydrated["path"] = str(path)
    hydrated["filePath"] = str(path)
    if hydrated.get("kind") == "audio":
        hydrated["mimeType"] = str(hydrated.get("mimeType") or "audio/wav")
    else:
        hydrated["mimeType"] = str(hydrated.get("mimeType") or _mime_from_image_suffix(path))
    return hydrated


def _asset_source_metadata_for_ui(
    project_id: str | None,
    item: dict[str, Any],
    source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .source_coverage import _load_source_coverage
    from .source_coverage import _source_ref_bounds
    from .source_coverage import _source_refs_from_asset_row
    if not project_id or not isinstance(item, dict):
        return {}
    metadata: dict[str, Any] = {}
    refs = _source_refs_from_asset_row(item)
    range_id = str(item.get("assetRangeId") or "").strip()
    first_episode_id = ""
    source_id = ""
    start: int | None = None
    end: int | None = None
    for ref in refs:
        if not range_id:
            range_id = str(ref.get("assetRangeId") or "").strip()
        if not first_episode_id:
            first_episode_id = str(ref.get("episodeId") or ref.get("episode_id") or "").strip()
        if not source_id:
            source_id = str(ref.get("sourceId") or "").strip()
        ref_start, ref_end = _source_ref_bounds(ref)
        if start is None and ref_start is not None and ref_end is not None:
            start, end = ref_start, ref_end

    range_row: dict[str, Any] | None = None
    if isinstance(source_coverage, dict):
        coverage = source_coverage
    else:
        try:
            coverage = _load_source_coverage(project_id)
        except Exception:
            coverage = {}
    for candidate in coverage.get("assetRanges", []) if isinstance(coverage.get("assetRanges"), list) else []:
        if not isinstance(candidate, dict):
            continue
        if range_id and str(candidate.get("rangeId") or "") == range_id:
            range_row = candidate
            break
        if start is None:
            continue
        try:
            candidate_start = int(candidate.get("absoluteStart") or 0)
            candidate_end = int(candidate.get("absoluteEnd") or 0)
        except (TypeError, ValueError):
            continue
        candidate_source_id = str(candidate.get("sourceId") or "")
        if source_id and candidate_source_id and source_id != candidate_source_id:
            continue
        if candidate_start <= start < candidate_end:
            range_row = candidate
            break

    if range_row:
        range_id = range_id or str(range_row.get("rangeId") or "").strip()
        source_id = source_id or str(range_row.get("sourceId") or "").strip()
        if start is None:
            try:
                start = int(range_row.get("absoluteStart") or 0)
                end = int(range_row.get("absoluteEnd") or 0)
            except (TypeError, ValueError):
                start = None
                end = None
        summary = str(range_row.get("summary") or "").strip()
        if summary:
            metadata["sourceRangeSummary"] = summary

    if not first_episode_id and start is not None:
        for episode_range in coverage.get("episodeRanges", []) if isinstance(coverage.get("episodeRanges"), list) else []:
            if not isinstance(episode_range, dict):
                continue
            try:
                episode_start = int(episode_range.get("absoluteStart") or 0)
                episode_end = int(episode_range.get("absoluteEnd") or 0)
            except (TypeError, ValueError):
                continue
            episode_source_id = str(episode_range.get("sourceId") or "")
            if source_id and episode_source_id and source_id != episode_source_id:
                continue
            if episode_start <= start < episode_end:
                first_episode_id = str(episode_range.get("episodeId") or "").strip()
                break

    if range_id:
        metadata["assetRangeId"] = range_id
    if first_episode_id:
        metadata["firstEpisodeId"] = first_episode_id
    if start is not None and end is not None:
        metadata["sourceRange"] = {"sourceId": source_id, "absoluteStart": start, "absoluteEnd": end}
        metadata["sourceRangeLabel"] = f"{start}-{end}"
    return metadata


def _hydrate_asset_row_for_ui(
    project_id: str | None,
    item: dict[str, Any],
    source_coverage: dict[str, Any] | None = None,
    *,
    include_source_metadata: bool = True,
) -> dict[str, Any]:
    hydrated = _asset_row_for_response(item)
    for key in ("media", "referenceMedia", "voiceReferenceAudio"):
        media = _hydrate_media_asset_for_ui(project_id, hydrated.get(key))
        if media is not None:
            hydrated[key] = media
    versions = hydrated.get("mediaVersions")
    if isinstance(versions, list):
        hydrated_versions: list[dict[str, Any]] = []
        for version in versions:
            if not isinstance(version, dict):
                continue
            row = copy.deepcopy(version)
            media = _hydrate_media_asset_for_ui(project_id, row.get("media"))
            if media is not None:
                row["media"] = media
            hydrated_versions.append(row)
        hydrated["mediaVersions"] = hydrated_versions
    if include_source_metadata:
        hydrated.update(_asset_source_metadata_for_ui(project_id, hydrated, source_coverage))
    return hydrated


def _hydrate_assets_for_ui(
    project_id: str | None,
    data: dict[str, Any],
    *,
    include_source_metadata: bool = True,
    asset_type: str | None = None,
    source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .source_coverage import _load_source_coverage
    if not project_id:
        return data
    selected_asset_type = _normalize_asset_type_key(asset_type)
    asset_types = (selected_asset_type,) if selected_asset_type else ASSET_TYPES
    if selected_asset_type:
        hydrated = copy.deepcopy(DEFAULT_ASSETS)
        rows = data.get(selected_asset_type)
        hydrated[selected_asset_type] = copy.deepcopy(rows if isinstance(rows, list) else [])
    else:
        hydrated = copy.deepcopy(data)
    if include_source_metadata and source_coverage is None:
        try:
            source_coverage = _load_source_coverage(project_id)
        except Exception:
            source_coverage = {}
    source_coverage = source_coverage if include_source_metadata and isinstance(source_coverage, dict) else {}
    for current_asset_type in asset_types:
        rows = hydrated.get(current_asset_type)
        if not isinstance(rows, list):
            continue
        hydrated[current_asset_type] = [
            _hydrate_asset_row_for_ui(
                project_id,
                item,
                source_coverage,
                include_source_metadata=include_source_metadata,
            )
            if isinstance(item, dict)
            else item
            for item in rows
        ]
    return hydrated


def _agent_message_row(
    role: str,
    text: str,
    *,
    attachments: list[dict[str, Any]] | None = None,
    content: list[dict[str, Any]] | None = None,
    project_id: str | None = None,
    control_only: bool = False,
    quick_prompt_id: str = "",
    execution_message: str = "",
) -> dict[str, Any]:
    cleaned_text = str(text or "").strip()
    row: dict[str, Any] = {
        "id": f"assistant-message-{uuid.uuid4().hex[:10]}",
        "role": "assistant" if role == "assistant" else "user",
        "text": cleaned_text,
        "createdAt": _now(),
    }
    normalized_content = _normalize_agent_content_blocks(content, project_id, hydrate=False)
    if normalized_content:
        row["content"] = normalized_content
    elif cleaned_text:
        row["content"] = _normalize_agent_content_blocks(
            [{"type": "text", "text": cleaned_text}],
            project_id,
            hydrate=False,
        )
    normalized_attachments = _agent_message_attachment_rows(attachments or [], project_id)
    if normalized_attachments:
        row["attachments"] = normalized_attachments
    if control_only and row["role"] == "user":
        row["controlOnly"] = True
    clean_quick_prompt_id = str(quick_prompt_id or "").strip()
    if clean_quick_prompt_id:
        row["quickPromptId"] = clean_quick_prompt_id
    clean_execution_message = str(execution_message or "").strip()
    if clean_execution_message:
        row["executionMessage"] = clean_execution_message
    return row


def _agent_message_is_control_only(message: dict[str, Any]) -> bool:
    if not isinstance(message, dict):
        return False
    if str(message.get("role") or "") != "user":
        return False
    raw_control_only = message.get("controlOnly")
    if raw_control_only is None:
        raw_control_only = message.get("control_only")
    return _agent_truthy_flag(raw_control_only)


def _agent_truthy_flag(value: Any) -> bool:
    return value is True or str(value or "").strip().lower() in {"true", "1", "yes", "y", "on"}


def _agent_attachment_input_from_block(
    item: dict[str, Any],
    *,
    default_name: str,
    default_mime: str,
    id_prefix: str,
) -> dict[str, Any] | None:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    media = item.get("media") if isinstance(item.get("media"), dict) else {}
    source_dict = source if isinstance(source, dict) else {}
    media_dict = media if isinstance(media, dict) else {}
    path_name = ""
    path_mime = ""
    for key in ("path", "filePath", "file_path", "relativePath", "relative_path", "file"):
        for raw_candidate in (item.get(key), source_dict.get(key), media_dict.get(key)):
            raw_text = str(raw_candidate or "").strip()
            if not raw_text:
                continue
            path = Path(raw_text)
            path_name = path.name
            path_mime = _mime_from_file_suffix(path, "")
            break
        if path_name:
            break
    attachment: dict[str, Any] = {
        "id": str(item.get("id") or media_dict.get("id") or f"{id_prefix}-{uuid.uuid4().hex[:10]}"),
        "name": str(
            item.get("name")
            or item.get("title")
            or source_dict.get("name")
            or media_dict.get("originalName")
            or media_dict.get("name")
            or path_name
            or default_name
        ),
        "mimeType": str(
            item.get("mimeType")
            or item.get("mime_type")
            or item.get("media_type")
            or source_dict.get("media_type")
            or source_dict.get("mimeType")
            or source_dict.get("mime_type")
            or media_dict.get("mimeType")
            or path_mime
            or default_mime
        ),
    }
    for key in ("path", "filePath", "file_path", "relativePath", "relative_path", "file"):
        value = item.get(key)
        if value:
            attachment[key] = value
        source_value = source_dict.get(key)
        if source_value:
            attachment[key] = source_value
        media_value = media_dict.get(key)
        if media_value:
            attachment[key] = media_value
    data_url = (
        item.get("dataUrl")
        or item.get("data_url")
        or source_dict.get("dataUrl")
        or source_dict.get("data_url")
        or media_dict.get("dataUrl")
        or media_dict.get("data_url")
    )
    data = source_dict.get("data") or item.get("data") or media_dict.get("data")
    if isinstance(data_url, str) and data_url.startswith("data:"):
        attachment["dataUrl"] = data_url
    elif isinstance(data, str) and data.strip():
        clean_data = data.strip()
        if clean_data.startswith("data:"):
            attachment["dataUrl"] = clean_data
        else:
            attachment["dataUrl"] = f"data:{attachment['mimeType']};base64,{clean_data}"
    if not any(attachment.get(key) for key in ("dataUrl", "path", "filePath", "file_path", "relativePath", "relative_path", "file")):
        return None
    return attachment


def _agent_image_attachment_input_from_block(item: dict[str, Any]) -> dict[str, Any] | None:
    return _agent_attachment_input_from_block(
        item,
        default_name="agent-image.png",
        default_mime="image/png",
        id_prefix="image",
    )


def _agent_file_attachment_input_from_block(item: dict[str, Any]) -> dict[str, Any] | None:
    return _agent_attachment_input_from_block(
        item,
        default_name="agent-file.bin",
        default_mime="application/octet-stream",
        id_prefix="file",
    )


def _agent_attachment_error_content_block(kind: str, item: dict[str, Any], exc: Exception) -> dict[str, Any]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    media = item.get("media") if isinstance(item.get("media"), dict) else {}
    label = "图片" if kind == "image" else "文件"
    name = str(
        item.get("name")
        or item.get("title")
        or source.get("name")
        or media.get("name")
        or ""
    ).strip()
    mime_type = str(
        item.get("mimeType")
        or item.get("mime_type")
        or item.get("media_type")
        or source.get("mimeType")
        or source.get("mime_type")
        or source.get("media_type")
        or media.get("mimeType")
        or ""
    ).strip()
    text = f"供应商返回的{label}附件无法保存：{exc}"
    if name:
        text = f"{text}（{name}）"
    row = {
        "type": "attachment_error",
        "kind": kind,
        "text": text,
    }
    if name:
        row["name"] = name
    if mime_type:
        row["mimeType"] = mime_type
        row["media_type"] = mime_type
    return row


def _agent_content_block_log_details(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    media = item.get("media") if isinstance(item.get("media"), dict) else {}
    data_url = (
        item.get("dataUrl")
        or item.get("data_url")
        or source.get("dataUrl")
        or source.get("data_url")
        or media.get("dataUrl")
        or media.get("data_url")
    )
    return {
        "kind": kind,
        "type": item.get("type"),
        "name": item.get("name") or source.get("name") or media.get("name"),
        "mimeType": item.get("mimeType") or item.get("media_type") or source.get("mimeType") or media.get("mimeType"),
        "path": item.get("path") or item.get("filePath") or source.get("path") or source.get("filePath"),
        "relativePath": item.get("relativePath") or item.get("relative_path") or source.get("relativePath") or source.get("relative_path"),
        "hasDataUrl": isinstance(data_url, str) and bool(data_url.strip()),
    }


def _agent_image_content_block_from_ref(
    project_id: str | None,
    item: dict[str, Any],
    *,
    hydrate: bool,
) -> dict[str, Any] | None:
    attachment_input = _agent_image_attachment_input_from_block(item)
    if not attachment_input:
        return None
    try:
        rows = _agent_message_attachment_rows([attachment_input], project_id, hydrate=hydrate)
    except Exception as exc:
        print(f"[agent-content-block] 跳过无效图片附件：{exc}", flush=True)
        if project_id and not hydrate:
            append_agent_execution_error(
                project_id,
                stage="normalize_agent_image_block",
                message="模型返回图片附件本地处理失败",
                category="local_file_error",
                source="agent_content_block",
                error=exc,
                details=_agent_content_block_log_details("image", item),
                include_traceback=True,
            )
        return _agent_attachment_error_content_block("image", item, exc)
    if not rows:
        return None
    ref = rows[0]
    source: dict[str, Any] = {
        "type": "file",
        "mimeType": ref.get("mimeType"),
        "media_type": ref.get("mimeType"),
        "name": ref.get("name"),
        "relativePath": ref.get("relativePath"),
        "relative_path": ref.get("relative_path"),
        "file": ref.get("file"),
        "size": ref.get("size"),
    }
    if hydrate:
        source["path"] = ref.get("path")
        source["filePath"] = ref.get("filePath")
    source = {key: value for key, value in source.items() if value}
    return {"type": "image", "source": source}


def _agent_file_content_block_from_ref(
    project_id: str | None,
    item: dict[str, Any],
    *,
    hydrate: bool,
) -> dict[str, Any] | None:
    attachment_input = _agent_file_attachment_input_from_block(item)
    if not attachment_input:
        return None
    try:
        rows = _agent_message_attachment_rows([attachment_input], project_id, hydrate=hydrate)
    except Exception as exc:
        print(f"[agent-content-block] 跳过无效文件附件：{exc}", flush=True)
        if project_id and not hydrate:
            append_agent_execution_error(
                project_id,
                stage="normalize_agent_file_block",
                message="模型返回文件附件本地处理失败",
                category="local_file_error",
                source="agent_content_block",
                error=exc,
                details=_agent_content_block_log_details("file", item),
                include_traceback=True,
            )
        return _agent_attachment_error_content_block("file", item, exc)
    if not rows:
        return None
    ref = rows[0]
    source: dict[str, Any] = {
        "type": "file",
        "mimeType": ref.get("mimeType"),
        "media_type": ref.get("mimeType"),
        "name": ref.get("name"),
        "relativePath": ref.get("relativePath"),
        "relative_path": ref.get("relative_path"),
        "file": ref.get("file"),
        "size": ref.get("size"),
    }
    if hydrate:
        source["path"] = ref.get("path")
        source["filePath"] = ref.get("filePath")
    source = {key: value for key, value in source.items() if value}
    return {"type": "file", "source": source}


def _agent_blocks_from_attachment_fields(project_id: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    def append_rows(raw: Any, block_type: str) -> None:
        if raw is None:
            return
        values = raw if isinstance(raw, list) else [raw]
        for item in values[:5]:
            if isinstance(item, str):
                text = item.strip()
                if not text:
                    continue
                row: dict[str, Any] = {"type": block_type}
                if text.startswith("data:"):
                    row["dataUrl"] = text
                else:
                    row["path"] = text
            elif isinstance(item, dict):
                row = copy.deepcopy(item)
                row["type"] = block_type
            else:
                continue
            blocks.extend(_normalize_agent_content_blocks([row], project_id, hydrate=False))

    for key in ("image", "images", "imageData", "image_data"):
        append_rows(data.get(key), "image")
    for key in ("file", "files", "attachment", "attachments", "artifact", "artifacts"):
        append_rows(data.get(key), "file")
    return blocks


_AGENT_UI_ONLY_RECOMMENDATION_ACTIONS = {
    "goto_sources",
    "open_current_episode",
    "open_characters",
    "open_creatures",
    "open_scenes",
    "open_props",
}
_AGENT_UI_ONLY_RECOMMENDATION_PATTERNS = (
    "打开源文件页",
    "前往源文件页",
    "查看源文件页",
    "打开当前绘画",
    "打开当前集",
    "打开角色页",
    "打开生物页",
    "打开场景页",
    "打开道具页",
)


def _agent_is_ui_only_recommendation(action: str, label: str, prompt: str) -> bool:
    if action in _AGENT_UI_ONLY_RECOMMENDATION_ACTIONS:
        return True
    text = re.sub(r"\s+", "", f"{label}{prompt}")
    return any(pattern in text for pattern in _AGENT_UI_ONLY_RECOMMENDATION_PATTERNS)


_AGENT_ACTION_FOOTER_FIELDS = ("label", "title", "description", "reply", "text")
_AGENT_ACTION_FOOTER_PROTOCOL_REPLIES = {"确认", "继续", "确认清空", "确认删除"}


def _agent_clean_action_footer_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\xa0", " ").replace("\u200b", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


def _agent_clean_action_footer_inline(value: Any) -> str:
    return re.sub(r"\s+", " ", _agent_clean_action_footer_text(value)).strip()


def _agent_clean_action_footer_reply_value(value: Any) -> str:
    text = _agent_clean_action_footer_inline(value)
    text = re.sub(r"[。.!！]+$", "", text).strip()
    compact = re.sub(r"\s+", "", text)
    if compact in _AGENT_ACTION_FOOTER_PROTOCOL_REPLIES:
        return compact
    if compact == "确认清除":
        return "确认清空"
    return text


def _agent_reply_value_requires_confirmation(value: Any) -> bool:
    return _agent_clean_action_footer_inline(value).startswith("确认")


def _agent_action_footer_title_for_reply(reply: str) -> str:
    clean_reply = _agent_clean_action_footer_inline(reply)
    if _agent_reply_value_requires_confirmation(clean_reply):
        return clean_reply if clean_reply != "确认" else "确认后继续"
    return "继续下一步"


def _normalize_agent_action_footer(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    footer = {
        key: _agent_clean_action_footer_text(value.get(key))
        for key in _AGENT_ACTION_FOOTER_FIELDS
    }
    footer = {key: text for key, text in footer.items() if text}
    if footer.get("reply"):
        footer["reply"] = _agent_clean_action_footer_reply_value(footer["reply"])
    return footer


def _agent_action_footer_text(value: Any) -> str:
    footer = _normalize_agent_action_footer(value)
    if not footer:
        return ""
    if footer.get("text") and not any(footer.get(key) for key in ("label", "title", "description", "reply")):
        return footer["text"]
    rows: list[str] = []
    label = _agent_clean_action_footer_inline(footer.get("label"))
    if label:
        rows.append(f"{label}:")
    for key in ("title", "description"):
        text = _agent_clean_action_footer_text(footer.get(key))
        if text:
            rows.append(text)
    reply = _agent_clean_action_footer_inline(footer.get("reply"))
    if reply:
        rows.append("回复:")
        rows.append(reply)
    text = _agent_clean_action_footer_text(footer.get("text"))
    if text:
        rows.append(text)
    return "\n".join(rows).strip()


def _agent_merge_action_footer_values(*values: Any) -> dict[str, str]:
    merged: dict[str, str] = {}
    description_rows: list[str] = []
    text_rows: list[str] = []
    for value in values:
        footer = _normalize_agent_action_footer(value)
        if not footer:
            continue
        for key in ("label", "title", "reply"):
            if footer.get(key) and not merged.get(key):
                merged[key] = footer[key]
        if footer.get("description") and footer["description"] not in description_rows:
            description_rows.append(footer["description"])
        if footer.get("text") and footer["text"] not in text_rows:
            text_rows.append(footer["text"])
    if description_rows:
        merged["description"] = "\n".join(description_rows)
    elif text_rows and not any(merged.get(key) for key in ("title", "reply")):
        merged["text"] = "\n".join(text_rows)
    elif text_rows:
        merged["description"] = "\n".join(text_rows)
    return merged


def _agent_attach_action_footer_to_content_blocks(
    blocks: list[dict[str, Any]],
    footer_text: Any,
    *,
    base_text: str = "",
) -> list[dict[str, Any]]:
    footer = _normalize_agent_action_footer(footer_text)
    if not footer:
        return copy.deepcopy(blocks or [])
    next_blocks = copy.deepcopy(blocks or [])
    if base_text and not _agent_blocks_have_body_text(next_blocks):
        next_blocks.append({"type": "text", "text": str(base_text or "").strip()})
    block = next_blocks[-1] if next_blocks else None
    if (
        isinstance(block, dict)
        and str(block.get("type") or "") == "text"
        and not str(block.get("text") or "").strip()
        and bool(block.get("actionFooter") or block.get("action_footer"))
    ):
        block["actionFooter"] = _agent_merge_action_footer_values(
            footer,
            block.get("actionFooter") or block.get("action_footer"),
        )
        block.pop("action_footer", None)
        return next_blocks
    next_blocks.append({"type": "text", "text": "", "actionFooter": footer})
    return next_blocks


def _normalize_agent_content_blocks(
    value: Any,
    project_id: str | None = None,
    *,
    hydrate: bool = False,
) -> list[dict[str, Any]]:
    from .agent_action_contract import _agent_action_label
    from .agent_action_contract import _agent_program_direct_actions
    from .source_text_store import _compact_text
    if not isinstance(value, list):
        return []
    blocks: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        block_type = str(item.get("type") or "text").strip()
        if block_type == "text":
            text = str(item.get("text") or "").strip()
            raw_action_footer = item.get("actionFooter") or item.get("action_footer")
            action_footer = _normalize_agent_action_footer(raw_action_footer)
            body_text = text
            if body_text or action_footer:
                block = {"type": "text", "text": body_text}
                if action_footer:
                    block["actionFooter"] = action_footer
                blocks.append(block)
        elif block_type == "task_progress":
            title = str(item.get("title") or "创建项目拆分流程").strip()
            status = str(item.get("status") or "idle").strip()
            steps = _normalize_agent_session_step_rows(item.get("steps"))
            blocks.append(
                {
                    "type": "task_progress",
                    "title": title,
                    "status": status if status in {"idle", "running", "completed", "failed"} else "idle",
                    "steps": steps,
                }
            )
        elif block_type == "thinking":
            text = str(item.get("text") or "").strip()
            if text:
                blocks.append({"type": "thinking", "text": text, "title": str(item.get("title") or "思考过程")})
        elif block_type == "skill_content":
            text = str(item.get("text") or item.get("content") or "").strip()
            if text:
                blocks.append({"type": "skill_content", "text": text, "title": str(item.get("title") or "技能输出")})
        elif block_type == "tool_use":
            tool_id = str(item.get("id") or item.get("tool_use_id") or f"tool-{uuid.uuid4().hex[:8]}").strip()
            name = str(item.get("name") or "Tool").strip() or "Tool"
            tool_input = item.get("input") if isinstance(item.get("input"), dict) else {}
            row = {
                "type": "tool_use",
                "id": tool_id,
                "name": name,
                "input": tool_input,
            }
            result = str(item.get("result") or "").strip()
            if result:
                row["result"] = result
            if item.get("is_error"):
                row["is_error"] = True
            skill_content = str(item.get("skill_content") or "").strip()
            if skill_content:
                row["skill_content"] = skill_content
            blocks.append(row)
        elif block_type == "tool_result":
            content = str(item.get("content") or item.get("result") or "").strip()
            if content:
                row = {
                    "type": "tool_result",
                    "tool_use_id": str(item.get("tool_use_id") or item.get("id") or "").strip(),
                    "content": content,
                    "is_error": bool(item.get("is_error")),
                }
                if item.get("outcome") == "revision_required":
                    row["outcome"] = "revision_required"
                if item.get("contextExcluded") or item.get("context_excluded"):
                    row["contextExcluded"] = True
                blocks.append(row)
        elif block_type in {"source_text", "sourceText"}:
            text = str(
                item.get("text")
                or item.get("content")
                or item.get("sourceText")
                or item.get("source_text")
                or ""
            ).replace("\r\n", "\n").replace("\r", "\n")
            if text.strip():
                row = {
                    "type": "source_text",
                    "text": text,
                    "contextExcluded": True,
                }
                title = str(item.get("title") or "本集原文").strip()
                meta = str(item.get("meta") or item.get("description") or "").strip()
                episode_id = str(item.get("episodeId") or item.get("episode_id") or "").strip()
                source_id = str(item.get("sourceId") or item.get("source_id") or "").strip()
                if title:
                    row["title"] = title
                if meta:
                    row["meta"] = meta
                if episode_id:
                    row["episodeId"] = episode_id
                if source_id:
                    row["sourceId"] = source_id
                blocks.append(row)
        elif block_type == "plot_split_preview":
            candidate_id = str(item.get("candidateId") or "").strip()
            if not candidate_id:
                continue
            segments = []
            raw_segments = item.get("segments") if isinstance(item.get("segments"), list) else []
            for raw_segment in raw_segments:
                if not isinstance(raw_segment, dict):
                    continue
                assets = []
                raw_assets = raw_segment.get("assets") if isinstance(raw_segment.get("assets"), list) else []
                for raw_asset in raw_assets:
                    if not isinstance(raw_asset, dict):
                        continue
                    label = str(raw_asset.get("label") or "").strip()
                    raw_names = raw_asset.get("names") if isinstance(raw_asset.get("names"), list) else []
                    names = [str(name).strip() for name in raw_names if str(name).strip()]
                    if label and names:
                        assets.append({"label": label, "names": names})
                text = str(raw_segment.get("text") or "").replace("\r\n", "\n").replace("\r", "\n")
                segments.append({
                    "index": raw_segment.get("index") or len(segments) + 1,
                    "title": str(raw_segment.get("title") or "").strip(),
                    "text": text,
                    "charCount": len(text),
                    "splitReason": str(raw_segment.get("splitReason") or "").strip(),
                    "assets": assets,
                })
            if segments:
                blocks.append({
                    "type": "plot_split_preview",
                    "candidateId": candidate_id,
                    "candidateVersion": item.get("candidateVersion") if isinstance(item.get("candidateVersion"), int) and item["candidateVersion"] > 0 else 1,
                    "status": item.get("status") if item.get("status") in {"pending_confirmation", "superseded", "committed", "cancelled"} else "pending_confirmation",
                    "episodeTitle": str(item.get("episodeTitle") or "").strip(),
                    "segments": segments,
                })
        elif block_type == "episode_boundary_candidate":
            candidate_id = str(item.get("candidateId") or "").strip()
            episode_id = str(item.get("episodeId") or "").strip()
            if candidate_id and episode_id:
                blocks.append({
                    "type": "episode_boundary_candidate",
                    "candidateId": candidate_id,
                    "status": str(item.get("status")) if item.get("status") in {"committed", "superseded", "cancelled"} else "pending_confirmation",
                    "episodeId": episode_id,
                    "title": str(item.get("title") or "").strip(),
                    "startOffset": item.get("startOffset"),
                    "endOffset": item.get("endOffset"),
                    "targetUnits": item.get("targetUnits"),
                    "actualUnits": item.get("actualUnits"),
                    "boundaryEndText": str(item.get("boundaryEndText") or "").strip(),
                    "reason": str(item.get("reason") or "").strip(),
                    "riskNotes": [str(note).strip() for note in (item.get("riskNotes") or []) if str(note).strip()][:8]
                    if isinstance(item.get("riskNotes"), list) else [],
                })
        elif block_type == "interrupt_notice":
            text = str(item.get("text") or item.get("content") or "").strip()
            if text:
                blocks.append({"type": "interrupt_notice", "text": text})
        elif block_type == "attachment_error":
            text = str(item.get("text") or item.get("content") or "").strip()
            if text:
                row = {
                    "type": "attachment_error",
                    "kind": str(item.get("kind") or "file").strip() or "file",
                    "text": text,
                }
                name = str(item.get("name") or "").strip()
                mime_type = str(item.get("mimeType") or item.get("media_type") or "").strip()
                if name:
                    row["name"] = name
                if mime_type:
                    row["mimeType"] = mime_type
                    row["media_type"] = mime_type
                blocks.append(row)
        elif block_type == "recommendations":
            items: list[dict[str, Any]] = []
            raw_items = item.get("items") or item.get("options") or []
            if isinstance(raw_items, list):
                for index, raw_item in enumerate(raw_items[:6]):
                    if not isinstance(raw_item, dict):
                        continue
                    # Navigation is a local UI command, never an agent task or prompt.
                    if raw_item.get("mode") == "navigation":
                        if raw_item.get("destination") == "project_session":
                            items.append({
                                "id": "open_project_conversation",
                                "label": "前往项目会话",
                                "description": _compact_text(str(raw_item.get("description") or "").strip(), 160),
                                "mode": "navigation",
                                "destination": "project_session",
                                "prompt": "",
                                "recommended": _agent_truthy_flag(raw_item.get("recommended")),
                            })
                        continue
                    label = str(raw_item.get("label") or "").strip()
                    prompt = str(raw_item.get("prompt") or "").strip()
                    action = str(raw_item.get("action") or "").strip()
                    task_type = str(
                        raw_item.get("taskType") or raw_item.get("task_type") or ""
                    ).strip()
                    if task_type not in _agent_known_task_types():
                        task_type = ""
                    mode = str(raw_item.get("mode") or "").strip()
                    if mode not in {"action", "prompt"}:
                        mode = "action" if action else "prompt"
                    # content block 推荐项同样遵循边界：只有程序直达白名单中的固定操作保留 action。
                    # 页面导航、上传文本等界面操作不能作为对话推荐露出，直接过滤。
                    if _agent_is_ui_only_recommendation(action, label, prompt):
                        continue
                    # 其余非程序直达动作降级为自然语言提示，避免绕过智能体判断。
                    if mode == "action" and action not in _agent_program_direct_actions():
                        mode = "prompt"
                        action = ""
                    if not label:
                        label = _agent_action_label(action, {}) if action else prompt
                    if not prompt:
                        prompt = label
                    if not label or not prompt:
                        continue
                    row = {
                        "id": str(raw_item.get("id") or action or f"rec-{index + 1}").strip(),
                        "label": _compact_text(label, 64),
                        "description": _compact_text(str(raw_item.get("description") or "").strip(), 160),
                        "mode": mode,
                        "prompt": _compact_text(prompt, 240),
                        "recommended": _agent_truthy_flag(raw_item.get("recommended")),
                    }
                    if mode == "action" and action in _agent_program_direct_actions():
                        row["action"] = action
                    elif task_type:
                        row["taskType"] = task_type
                    raw_control_only = raw_item.get("controlOnly")
                    if raw_control_only is None:
                        raw_control_only = raw_item.get("control_only")
                    if _agent_truthy_flag(raw_control_only):
                        row["controlOnly"] = True
                    if "targetContext" in raw_item:
                        row["targetContext"] = _sanitize_agent_target_context(raw_item["targetContext"])
                    items.append(row)
            if items:
                block = {
                    "type": "recommendations",
                    "title": str(item.get("title") or "下一步建议").strip(),
                    "items": items,
                }
                origin = str(item.get("origin") or "").strip()
                if origin in {"progress_query", "task_completion", "task_feedback"}:
                    block["origin"] = origin
                summary = str(item.get("summary") or "").strip()
                if summary and origin == "progress_query":
                    block["summary"] = summary[:4000]
                blocks.append(block)
        elif block_type == "image":
            image_block = _agent_image_content_block_from_ref(project_id, item, hydrate=hydrate)
            if image_block:
                blocks.append(image_block)
        elif block_type in {"file", "attachment", "document"}:
            file_block = _agent_file_content_block_from_ref(project_id, item, hydrate=hydrate)
            if file_block:
                blocks.append(file_block)
    return blocks


def _agent_text_from_content_blocks(blocks: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("contextExcluded") or block.get("context_excluded"):
            continue
        block_type = str(block.get("type") or "")
        if block_type in {"source_text", "sourceText", "tool_result"}:
            continue
        if block_type == "text":
            text = str(block.get("text") or "").strip()
            if text:
                rows.append(text)
            continue
        for key in ("text", "content", "result"):
            text = str(block.get(key) or "").strip()
            if text:
                rows.append(text)
                break
    return "\n".join(rows).strip()


def _agent_blocks_have_body_text(blocks: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(block, dict)
        and (
            (str(block.get("type") or "") == "text" and str(block.get("text") or "").strip())
            or (block.get("type") == "plot_split_preview" and bool(block.get("segments")))
        )
        for block in blocks
    )


def _agent_blocks_have_text(blocks: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(block, dict)
        and str(block.get("type") or "") == "text"
        and (
            str(block.get("text") or "").strip()
            or _agent_action_footer_text(block.get("actionFooter") or block.get("action_footer"))
        )
        for block in blocks
    )


def _normalize_agent_message_rows(
    value: Any,
    project_id: str | None = None,
    *,
    hydrate: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        content = _normalize_agent_content_blocks(item.get("content"), project_id, hydrate=hydrate)
        text = str(item.get("text") or "").strip() or _agent_text_from_content_blocks(content)
        if not text and not content:
            continue
        row: dict[str, Any] = {
            "id": str(item.get("id") or f"assistant-message-{uuid.uuid4().hex[:10]}"),
            "role": "assistant" if str(item.get("role") or "").strip() == "assistant" else "user",
            "text": text,
            "createdAt": str(item.get("createdAt") or item.get("created_at") or _now()),
        }
        if _agent_message_is_control_only(item) and row["role"] == "user":
            row["controlOnly"] = True
        quick_prompt_id = str(item.get("quickPromptId") or item.get("quick_prompt_id") or "").strip()
        if quick_prompt_id:
            row["quickPromptId"] = quick_prompt_id
        execution_message = str(item.get("executionMessage") or item.get("execution_message") or "").strip()
        if execution_message:
            row["executionMessage"] = execution_message
        if content:
            row["content"] = content
        elif text:
            row["content"] = _normalize_agent_content_blocks(
                [{"type": "text", "text": text}],
                project_id,
                hydrate=hydrate,
            )
        attachments = _agent_message_attachment_rows(item.get("attachments"), project_id, hydrate=hydrate)
        if attachments:
            row["attachments"] = attachments
        rows.append(row)
    return rows


def _normalize_agent_history_summary(value: Any) -> str:
    from .source_text_store import _compact_text
    text = str(value or "").strip()
    if not text:
        return ""
    return _compact_text(text, AGENT_CONTEXT_SUMMARY_CHARS)


def _agent_message_summary_line(message: dict[str, Any]) -> str:
    from .source_text_store import _compact_text
    role = "用户" if str(message.get("role") or "") == "user" else "助手"
    text = str(message.get("text") or "").strip()
    if not text:
        content = message.get("content") if isinstance(message.get("content"), list) else []
        text = _agent_text_from_content_blocks(content)
    text = _compact_text(text, 180)
    timestamp = str(message.get("createdAt") or message.get("created_at") or "").strip()
    prefix = f"{timestamp} " if timestamp else ""
    return f"{prefix}{role}: {text}".strip()


def _merge_agent_history_summary(existing: Any, archived_messages: list[dict[str, Any]]) -> str:
    from .source_text_store import _compact_text
    summary = _normalize_agent_history_summary(existing)
    if not archived_messages:
        return summary
    lines = [
        _agent_message_summary_line(message)
        for message in archived_messages[-AGENT_SESSION_HISTORY_SUMMARY_MESSAGE_LIMIT:]
        if isinstance(message, dict) and not _agent_message_is_control_only(message)
    ]
    lines = [line for line in lines if line]
    if not lines:
        return summary
    archived_summary = "被压缩的更早对话：\n" + "\n".join(lines)
    return _compact_text(
        "\n".join(part for part in (summary, archived_summary) if part),
        AGENT_CONTEXT_SUMMARY_CHARS,
    )


def _apply_agent_message_retention(session: dict[str, Any], messages: list[dict[str, Any]]) -> None:
    if len(messages) <= AGENT_SESSION_MESSAGE_RETAIN_LIMIT:
        session["messages"] = messages
        summary = _normalize_agent_history_summary(session.get("historySummary"))
        if summary:
            session["historySummary"] = summary
        else:
            session.pop("historySummary", None)
        return
    archive_count = len(messages) - AGENT_SESSION_MESSAGE_RETAIN_LIMIT
    archived_messages = messages[:archive_count]
    session["messages"] = messages[archive_count:]
    summary = _merge_agent_history_summary(session.get("historySummary"), archived_messages)
    if summary:
        session["historySummary"] = summary
    else:
        session.pop("historySummary", None)


def _normalize_agent_session_step_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        step_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or "").strip()
        status = str(item.get("status") or "idle").strip()
        if not step_id or not label:
            continue
        if status not in {"idle", "running", "done", "failed"}:
            status = "idle"
        rows.append({"id": step_id, "label": label, "status": status})
    return rows


def _normalize_agent_pending_question(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    question_id = str(value.get("questionId") or value.get("question_id") or "").strip()
    questions = value.get("questions")
    if not question_id or not isinstance(questions, list) or not questions:
        return None
    normalized_questions: list[dict[str, Any]] = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("question") or "").strip()
        options = item.get("options")
        if not prompt or not isinstance(options, list) or not options:
            continue
        normalized_options: list[dict[str, Any]] = []
        for option in options:
            if not isinstance(option, dict):
                continue
            value_text = str(option.get("value") or "").strip()
            label_text = str(option.get("label") or value_text).strip()
            description = str(option.get("description") or "").strip()
            if not label_text:
                continue
            row = {
                "value": value_text or label_text,
                "label": label_text,
                "description": description,
            }
            normalized_options.append(row)
        if not normalized_options:
            continue
        normalized_questions.append(
            {
                "header": str(item.get("header") or "").strip() or None,
                "question": prompt,
                "multiSelect": bool(item.get("multiSelect") or item.get("multi_select")),
                "options": normalized_options,
            }
        )
    if not normalized_questions:
        return None
    return {
        "question_id": question_id,
        "questionId": question_id,
        "questions": normalized_questions,
    }


def _normalize_agent_pending_operation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    operation_type = str(
        value.get("type")
        or value.get("operationType")
        or value.get("operation_type")
        or ""
    ).strip()
    if not operation_type:
        return None
    normalized = copy.deepcopy(value)
    normalized["type"] = operation_type
    normalized.setdefault("operationType", operation_type)
    return normalized


def _normalize_agent_session_row(
    value: Any,
    project_id: str | None = None,
    *,
    hydrate: bool = False,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    session_id = str(value.get("id") or "").strip()
    if not session_id:
        return None
    status = str(value.get("status") or "idle").strip()
    if status not in {"idle", "running", "completed", "error", "interrupted"}:
        status = "idle"
    episode_id = str(value.get("episodeId") or value.get("episode_id") or "E01").strip() or "E01"
    scope = str(
        value.get("scope")
        or value.get("contextScope")
        or value.get("context_scope")
        or ""
    ).strip()
    if scope not in {"project", "episode"}:
        scope = "project" if episode_id in {"__project__", "project"} else "episode"
    if scope == "project":
        episode_id = "__project__"
    row: dict[str, Any] = {
        "stateRevision": max(0, int(value.get("stateRevision") or 0)),
        "requirementRevision": max(0, int(value.get("requirementRevision") or 0)),
        "execution": copy.deepcopy(value.get("execution")) if isinstance(value.get("execution"), dict) else {},
        "id": session_id,
        "title": str(value.get("title") or "新会话").strip() or "新会话",
        "episodeId": episode_id,
        "scope": scope,
        "contextScope": scope,
        "status": status,
        "createdAt": str(value.get("createdAt") or value.get("created_at") or _now()),
        "updatedAt": str(value.get("updatedAt") or value.get("updated_at") or _now()),
        "messages": _normalize_agent_message_rows(value.get("messages"), project_id, hydrate=hydrate),
        "steps": _normalize_agent_session_step_rows(value.get("steps")),
    }
    workflow_id = str(value.get("workflowId") or value.get("workflow_id") or "").strip()
    if workflow_id:
        row["workflowId"] = workflow_id
    if scope == "episode":
        canvas_task = value.get("canvasTask")
        if isinstance(canvas_task, dict) and canvas_task.get("parentSessionId"):
            row["canvasTask"] = copy.deepcopy(canvas_task)
        from .agent_contracts import recent_creative_task_target
        recent_target = recent_creative_task_target(value.get("recentTaskTarget"), episode_id)
        if recent_target:
            row["recentTaskTarget"] = recent_target
    history_summary = _normalize_agent_history_summary(
        value.get("historySummary") or value.get("history_summary")
    )
    if history_summary:
        row["historySummary"] = history_summary
    sdk_session_id = str(value.get("sdkSessionId") or value.get("sdk_session_id") or "").strip()
    superseded_execution_id = str(value.get("supersededExecutionId") or "").strip()
    if superseded_execution_id:
        row["supersededExecutionId"] = superseded_execution_id
    if sdk_session_id:
        row["sdkSessionId"] = sdk_session_id
        row["sdkContextVersion"] = str(value.get("sdkContextVersion") or "")
    provider_instance_id = str(value.get("providerInstanceId") or value.get("provider_instance_id") or "").strip()
    if provider_instance_id:
        row["providerInstanceId"] = provider_instance_id
    adapter_id = str(value.get("adapterId") or value.get("adapter_id") or "").strip()
    if adapter_id:
        row["adapterId"] = adapter_id
    tools_used = value.get("toolsUsed") or value.get("tools_used")
    if isinstance(tools_used, list):
        row["toolsUsed"] = [str(item) for item in tools_used if str(item or "").strip()]
    reported_task_ids = value.get("reportedGenerationTaskIds")
    if isinstance(reported_task_ids, list):
        row["reportedGenerationTaskIds"] = list(dict.fromkeys(
            item.strip() for item in reported_task_ids if isinstance(item, str) and item.strip()
        ))[-50:]
    task_id = str(value.get("taskId") or value.get("task_id") or "").strip()
    if task_id:
        row["taskId"] = task_id
    running_action = str(value.get("runningAction") or value.get("running_action") or "").strip()
    if running_action:
        row["runningAction"] = running_action
    running_task_type = str(value.get("runningTaskType") or (
        (row.get("canvasTask") or {}).get("taskType") if status == "running" else ""
    ) or "").strip()
    if running_task_type:
        row["runningTaskType"] = running_task_type
    pending_question = _normalize_agent_pending_question(value.get("pendingQuestion") or value.get("pending_question"))
    if pending_question:
        row["pendingQuestion"] = pending_question
    pending_operation = _normalize_agent_pending_operation(value.get("pendingOperation") or value.get("pending_operation"))
    if pending_operation:
        row["pendingOperation"] = pending_operation
    return row


def _bind_agent_execution_task(project_id: str, task: dict[str, Any]) -> None:
    """Bind after task-storage locks are released, before starting any worker."""
    from utils.agent_execution_state import accepts_execution
    from .runtime_state import AgentTurnCancelled

    identity = str(task.get("executionId") or "")
    if not identity or task.get("type") == "agent_turn":
        return
    try:
        with _LOCK:
            sessions = _load_agent_sessions(project_id)
            session = next((row for row in sessions if row.get("id") == task.get("sessionId")), None)
            if not session or not accepts_execution(session, identity) or session.get("status") in {"completed", "error", "interrupted"}:
                raise AgentTurnCancelled()
            execution = session["execution"]
            execution["blockingTaskIds"] = list(dict.fromkeys([*execution.get("blockingTaskIds", []), task["id"]]))
            _save_agent_sessions(project_id, sessions)
    except Exception:
        from .task_control import _update_task_if_active
        _update_task_if_active(task["id"], status="cancelled", message="所属智能体执行已结束")
        raise


def _load_agent_session_snapshot(project_id: str, session_id: str) -> dict[str, Any] | None:
    return _agent_session_service().load_snapshot(project_id, session_id)


def _load_agent_sessions(project_id: str) -> list[dict[str, Any]]:
    return _agent_session_service().load_sessions(project_id)


def _save_agent_sessions(project_id: str, sessions: list[dict[str, Any]]) -> None:
    conversations = _publish_finished_canvas_task_messages(project_id, sessions)
    _agent_session_service().save_sessions(project_id, sessions)
    for conversation in conversations:
        # Use the persisted snapshot so a concurrent ordinary conversation keeps
        # its own streaming activity when a canvas task adds its final messages.
        _emit_agent_event("agent_session_snapshot", {
            "projectId": project_id,
            "episodeId": conversation.get("episodeId"),
            "sessions": _agent_session_summaries(project_id, conversation.get("episodeId")),
            "snapshot": _load_agent_session_snapshot(project_id, conversation["id"]),
        })


def _publish_finished_canvas_task_messages(
    project_id: str, sessions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append one-shot task messages to their conversation in completion order."""
    index = {row["id"]: row for row in sessions}
    changed: dict[str, dict[str, Any]] = {}
    for task in sorted(sessions, key=lambda row: str(row.get("updatedAt") or "")):
        metadata = task.get("canvasTask") or {}
        if (not metadata or metadata.get("reportedToConversation")
                or task.get("status") == "running"
                or (task.get("status") == "idle" and metadata.get("starting"))):
            continue
        parent = index.get(str(metadata.get("parentSessionId") or ""))
        if not parent or parent.get("canvasTask") or parent.get("episodeId") != task.get("episodeId"):
            continue
        messages = _normalize_agent_message_rows(task.get("messages"), project_id)
        # Keep the existing report and recommendation blocks. Only supply the
        # original card target when a recommendation did not already specify it.
        for message in messages:
            for block in message.get("content") or []:
                if block.get("type") == "recommendations":
                    for item in block.get("items") or []:
                        if not item.get("targetContext"):
                            item["targetContext"] = copy.deepcopy(metadata.get("target") or {})
        parent_messages = _normalize_agent_message_rows(parent.get("messages"), project_id)
        existing_ids = {message["id"] for message in parent_messages}
        parent_messages.extend(message for message in messages if message["id"] not in existing_ids)
        _apply_agent_message_retention(parent, parent_messages)
        if task.get("recentTaskTarget"):
            parent["recentTaskTarget"] = copy.deepcopy(task["recentTaskTarget"])
        # A remote SDK transcript does not contain reports delivered by other
        # executions. The next turn must start from the saved conversation.
        parent.pop("sdkSessionId", None)
        parent.pop("sdkContextVersion", None)
        if parent.get("status") == "running" and parent.get("execution"):
            parent["execution"]["conversationHistoryChanged"] = True
        parent["updatedAt"] = max(str(parent.get("updatedAt") or ""), str(task.get("updatedAt") or ""))
        metadata["reportedToConversation"] = True
        changed[parent["id"]] = parent
    return list(changed.values())


def _agent_session_updated_age_seconds(session: dict[str, Any]) -> float | None:
    updated_at = str(session.get("updatedAt") or session.get("updated_at") or "").strip()
    if not updated_at:
        return None
    try:
        parsed = datetime.fromisoformat(updated_at)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()


def _agent_session_recovery_task_rows(project_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    project_tasks = _read_json(_project_dir(project_id) / "tasks" / "tasks.json", [])
    if isinstance(project_tasks, list):
        rows.extend(item for item in project_tasks if isinstance(item, dict))
    global_tasks = _read_json(GLOBAL_TASKS_PATH, [])
    if isinstance(global_tasks, list):
        rows.extend(
            item
            for item in global_tasks
            if isinstance(item, dict)
            and str(item.get("projectId") or item.get("project_id") or "").strip()
            == project_id
        )
    return rows








def _recover_stale_running_agent_sessions(
    project_id: str,
    sessions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from utils.agent_execution_state import bound_task_status, TERMINAL_TASK_STATUSES
    from .task_control import _ACTIVE_GLOBAL_TASK_STATUSES
    from .task_lifecycle import _agent_task_has_running_thread
    from .runtime_state import _agent_thread_is_alive
    changed = False
    recovered: list[dict[str, Any]] = []
    interrupted_text = "插件已重启，未找到这轮智能体后台任务，已将会话恢复为已中断。你可以继续输入新的指令。"
    task_index = {
        str(task.get("id")): task
        for task in _agent_session_recovery_task_rows(project_id)
        if str(task.get("id") or "").strip()
    }
    for session in sessions:
        row = copy.deepcopy(session)
        session_id = str(row.get("id") or "").strip()
        canvas_task = row.get("canvasTask") or {}
        abandoned_start = bool(
            canvas_task.get("starting")
            and canvas_task.get("startingInstanceId") != _AGENT_BACKEND_INSTANCE_ID
        )
        if abandoned_start:
            canvas_task["starting"] = False
            canvas_task.pop("startingInstanceId", None)
            changed = True
        has_pending_question = bool(_normalize_agent_pending_question(row.get("pendingQuestion")))
        age_seconds = _agent_session_updated_age_seconds(row)
        execution = row.get("execution") or {}
        parent_alive = _agent_thread_is_alive(str(execution.get("id") or ""))
        grace_elapsed = age_seconds is None or age_seconds >= AGENT_STALE_RUNNING_GRACE_SECONDS
        related_tasks = [task for task in task_index.values()
                         if str(task.get("sessionId") or "") == session_id
                         and (task.get("executionId") == execution.get("id") or task.get("id") == execution.get("parentTaskId"))]
        def task_is_live(task: dict[str, Any]) -> bool:
            if task.get("status") not in _ACTIVE_GLOBAL_TASK_STATUSES:
                return False
            if task.get("type") != "agent_turn":
                return True  # Provider tasks have their own recovery lifecycle.
            return _agent_task_has_running_thread(task)
        has_live_tasks = any(task_is_live(task) for task in related_tasks)
        settled_status = None
        if row.get("status") == "running" and not has_pending_question:
            if execution:
                parent_task = task_index.get(str(execution.get("parentTaskId") or ""), {})
                if not parent_alive and (parent_task.get("status") in TERMINAL_TASK_STATUSES or grace_elapsed):
                    if not execution.get("dispatchClosed"):
                        changed = True
                    execution["dispatchClosed"] = True
                settled_status = bound_task_status(row, list(task_index.values()))
                if not has_live_tasks and parent_task.get("status") in {"failed", "error"}:
                    settled_status = "error"
            if settled_status in {"completed", "error", "interrupted"}:
                row["status"] = settled_status
                row.pop("taskId", None)
                row.pop("runningAction", None)
                row["updatedAt"] = _now()
                changed = True
        is_stale_running = (abandoned_start and row.get("status") == "idle") or (
            str(row.get("status") or "") == "running"
            and session_id
            and not parent_alive
            and not has_live_tasks
            and not has_pending_question
            and grace_elapsed
        )
        if is_stale_running:
            steps = []
            for step in _normalize_agent_session_step_rows(row.get("steps")):
                if step.get("status") == "running":
                    step["status"] = "failed"
                steps.append(step)
            messages = _normalize_agent_message_rows(row.get("messages"), project_id)
            last_blocks = messages[-1].get("content") if messages else []
            already_interrupted = any(
                isinstance(block, dict) and block.get("type") == "interrupt_notice"
                for block in (last_blocks if isinstance(last_blocks, list) else [])
            )
            if not already_interrupted:
                messages.append(
                    _agent_message_row(
                        "assistant",
                        interrupted_text,
                        content=[{"type": "interrupt_notice", "text": interrupted_text}],
                        project_id=project_id,
                    )
                )
            _apply_agent_message_retention(row, messages)
            row["steps"] = steps
            row["status"] = "interrupted"
            row["updatedAt"] = _now()
            row.pop("pendingQuestion", None)
            row.pop("taskId", None)
            row.pop("runningAction", None)
            changed = True
        recovered.append(row)
    if _publish_finished_canvas_task_messages(project_id, recovered):
        changed = True
    if changed:
        _save_agent_sessions(project_id, recovered)
        return _load_agent_sessions(project_id)
    return recovered


def _agent_session_title_for_message(episode_title: str, message: str) -> str:
    from .source_text_store import _compact_text
    cleaned = _compact_text(str(message or "").strip(), 24)
    generic = {
        "继续",
        "下一步",
        "开始拆分",
        "继续执行项目拆分流程",
        "开始拆分小说，生成场景、角色、生物、道具、分集剧本和分镜。",
    }
    if not cleaned or cleaned in generic:
        return episode_title or "新会话"
    return cleaned


def _agent_session_summary(session: dict[str, Any]) -> dict[str, Any]:
    episode_id = str(session.get("episodeId") or "E01")
    scope = str(session.get("scope") or session.get("contextScope") or "").strip()
    if scope not in {"project", "episode"}:
        scope = "project" if episode_id in {"__project__", "project"} else "episode"
    row = {
        "stateRevision": int(session.get("stateRevision") or 0),
        "execution": copy.deepcopy(session.get("execution") or {}),
        "id": str(session.get("id") or ""),
        "title": str(session.get("title") or "新会话"),
        "episodeId": "__project__" if scope == "project" else episode_id,
        "scope": scope,
        "sessionId": str(session.get("sessionId") or session.get("id") or ""),
        "status": str(session.get("status") or "idle"),
        "runningTaskType": str(session.get("runningTaskType") or ""),
        "waitingForInput": bool(session.get("pendingQuestion")),
        "waitingForConfirmation": bool(session.get("pendingOperation")),
        "canvasTask": copy.deepcopy(session.get("canvasTask") or {}),
        "createdAt": str(session.get("createdAt") or _now()),
        "updatedAt": str(session.get("updatedAt") or _now()),
    }
    workflow_id = str(session.get("workflowId") or session.get("workflow_id") or "").strip()
    if workflow_id:
        row["workflowId"] = workflow_id
    return row


def _agent_session_summaries(
    project_id: str,
    episode_id: str | None = None,
) -> list[dict[str, Any]]:
    from .agent_run_store import session_open_candidate_counts

    summaries = _agent_session_service().session_summaries(project_id, episode_id)
    counts = session_open_candidate_counts(project_id)
    for row in summaries:
        row["pendingCandidateCount"] = counts.get(str(row.get("id") or ""), 0)
    return summaries


def _agent_session_detail(project_id: str, session: dict[str, Any]) -> dict[str, Any]:
    from .agent_run_store import (
        project_session_asset_range_candidate_messages,
        project_session_candidate_messages,
    )

    detail = copy.deepcopy(_normalize_agent_session_row(session, project_id, hydrate=True) or {})
    if not detail:
        raise FileNotFoundError("智能体会话不存在")
    detail["messages"] = project_session_candidate_messages(
        project_id, str(detail["id"]), detail.get("messages") or [],
    )
    detail["messages"] = project_session_asset_range_candidate_messages(
        project_id, str(detail["id"]), detail["messages"],
    )
    from .agent_pending_operations import _agent_pending_operation_contexts
    from .agent_operation_catalog import agent_operation_action_footer, agent_operation_high_risk
    def interaction_from_pending(pending: dict[str, Any]) -> dict[str, Any]:
        footer = agent_operation_action_footer(str(pending.get("kind") or ""))
        high_risk = agent_operation_high_risk(str(pending.get("kind") or ""))
        awaiting_decision = bool(pending.get("active")) and str(
            pending.get("operationStatus") or ""
        ) not in {"committing", "commit_unknown"}
        return {
            "active": bool(pending.get("active")),
            "status": str(pending.get("status") or "stale"),
            "operationStatus": str(pending.get("operationStatus") or ""),
            "sessionId": str(detail["id"]),
            "operationType": str(pending.get("operationType") or ""),
            "pendingOperationId": str(pending.get("pendingOperationId") or ""),
            "kind": str(pending.get("kind") or ""),
            "createdAt": str(pending.get("createdAt") or ""),
            "candidateId": str(pending.get("candidateId") or ""),
            "runId": str(pending.get("runId") or ""),
            "candidateDigest": str(pending.get("candidateDigest") or ""),
            "candidateVersion": pending.get("candidateVersion"),
            "title": str(footer.get("title") or "确认当前操作"),
            "description": str(footer.get("description") or ""),
            "message": str(pending.get("message") or ""),
            "staleReason": str(pending.get("staleReason") or ""),
            "highRisk": high_risk,
            "confirmationMode": "button_only" if high_risk else "message_or_button",
            "canConfirm": awaiting_decision and bool((pending.get("interactionPolicy") or {}).get("canConfirm")),
            "canCancel": awaiting_decision and bool((pending.get("interactionPolicy") or {}).get("canCancel")),
        }
    pending_items = [interaction_from_pending(pending) for pending in
                     _agent_pending_operation_contexts(project_id, str(detail["id"]))]
    detail["pendingInteractions"] = pending_items
    detail["waitingForInput"] = bool(detail.get("pendingQuestion"))
    detail["waitingForConfirmation"] = any(item.get("active") for item in pending_items)
    return detail


def _agent_snapshot_from_session(
    project_id: str,
    session: dict[str, Any],
    *,
    hydrate: bool = True,
    draft_turn: dict[str, Any] | None = None,
    live_activity: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    detail = (
        _agent_session_detail(project_id, session)
        if hydrate
        else copy.deepcopy(_normalize_agent_session_row(session, project_id, hydrate=False) or {})
    )
    if not detail:
        raise FileNotFoundError("智能体会话不存在")
    turns: list[dict[str, Any]] = []
    for message in detail.get("messages") or []:
        if not isinstance(message, dict):
            continue
        text = str(message.get("text") or "").strip()
        content = _normalize_agent_content_blocks(message.get("content"), project_id, hydrate=hydrate)
        if not content and text:
            content = _normalize_agent_content_blocks(
                [{"type": "text", "text": text}],
                project_id,
                hydrate=hydrate,
            )
        turn: dict[str, Any] = {
            "type": str(message.get("role") or "assistant"),
            "uuid": str(message.get("id") or f"turn-{uuid.uuid4().hex[:10]}"),
            "timestamp": str(message.get("createdAt") or ""),
            "text": text,
            "content": content,
        }
        attachments = _agent_message_attachment_rows(message.get("attachments"), project_id, hydrate=hydrate)
        if attachments:
            turn["attachments"] = attachments
        if _agent_message_is_control_only(message) and turn["type"] == "user":
            turn["controlOnly"] = True
        quick_prompt_id = str(message.get("quickPromptId") or message.get("quick_prompt_id") or "").strip()
        if quick_prompt_id:
            turn["quickPromptId"] = quick_prompt_id
        execution_message = str(message.get("executionMessage") or message.get("execution_message") or "").strip()
        if execution_message:
            turn["executionMessage"] = execution_message
        turns.append(
            turn
        )
    pending_question = (
        _normalize_agent_pending_question(detail.get("pendingQuestion"))
        if detail.get("status") == "running"
        else None
    )
    pending_operation = _normalize_agent_pending_operation(detail.get("pendingOperation"))
    snapshot = {
        "sessionId": detail["id"],
        "status": detail.get("status") or "idle",
        "turns": turns,
        "draft_turn": draft_turn,
        "pending_questions": [pending_question] if pending_question else [],
        "pending_operations": [pending_operation] if pending_operation else [],
        "session": detail,
    }
    if live_activity:
        snapshot["live_activity"] = live_activity
    return snapshot


def _normalize_agent_live_activity(items: Any) -> list[dict[str, Any]]:
    from .source_text_store import _compact_text
    if not isinstance(items, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            text = item.strip()
            item_id = f"live-{index + 1}"
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("label") or "").strip()
            item_id = str(item.get("id") or f"live-{index + 1}").strip()
        else:
            continue
        if not text:
            continue
        row: dict[str, Any] = {"id": item_id or f"live-{index + 1}", "text": _compact_text(text, 140)}
        if isinstance(item, dict):
            kind = str(item.get("kind") or "").strip()
            if kind in {"phase", "thought", "tool_use", "tool_result"}:
                row["kind"] = kind
            phase = str(item.get("phase") or "").strip()
            if phase in {"start", "thinking", "finalizing"}:
                row["phase"] = phase
            goal = str(item.get("goal") or "").strip()
            if goal:
                row["goal"] = _compact_text(goal, 80)
            tool_name = str(item.get("toolName") or "").strip()
            if tool_name:
                row["toolName"] = _compact_text(tool_name, 80)
            tool_use_id = str(item.get("toolUseId") or "").strip()
            if tool_use_id:
                row["toolUseId"] = tool_use_id[:100]
            if "isError" in item:
                row["isError"] = bool(item["isError"])
            if item.get("outcome") == "revision_required":
                row["outcome"] = "revision_required"
        rows.append(row)
    return rows[-120:]


def _agent_stream_tool_name(name: str) -> str:
    text = str(name or "").strip()
    return text.removeprefix("mcp__ai_video__")


def _normalize_agent_stream_block(block: Any) -> dict[str, Any] | None:
    from .source_text_store import _compact_text
    if not isinstance(block, dict):
        return None
    block_type = str(block.get("type") or "").strip()
    if block_type == "text":
        text = _compact_text(str(block.get("text") or ""), 900).strip()
        return {"type": "text", "text": text} if text else None
    if block_type == "tool_use":
        name = _agent_stream_tool_name(str(block.get("name") or "Tool"))
        raw_input = block.get("input") if isinstance(block.get("input"), dict) else {}
        return {
            "type": "tool_use",
            "id": str(block.get("id") or f"tool-{uuid.uuid4().hex[:8]}"),
            "name": name or "Tool",
            "input": copy.deepcopy(raw_input),
        }
    if block_type == "tool_result":
        is_error = bool(block.get("is_error") or block.get("isError"))
        raw_content = str(block.get("content") or block.get("result") or "").strip()
        content = raw_content if is_error else _compact_text(raw_content, 900).strip()
        row = {
            "type": "tool_result",
            "tool_use_id": str(block.get("tool_use_id") or block.get("toolUseId") or ""),
            "content": content or ("工具返回异常" if is_error else "工具已返回结果"),
            "is_error": is_error,
        }
        if block.get("outcome") == "revision_required":
            row["outcome"] = "revision_required"
        if block.get("contextExcluded") or block.get("context_excluded"):
            row["contextExcluded"] = True
        return row
    return None


def _agent_stream_block_key(block: dict[str, Any]) -> str:
    block_type = str(block.get("type") or "")
    if block_type == "text":
        return f"text:{str(block.get('text') or '').strip()}"
    if block_type == "tool_use":
        input_text = json.dumps(block.get("input") or {}, ensure_ascii=False, sort_keys=True)
        return f"tool_use:{block.get('name')}:{input_text}"
    if block_type == "tool_result":
        return f"tool_result:{block.get('tool_use_id')}:{str(block.get('content') or '').strip()}:{block.get('outcome') or ''}"
    return json.dumps(block, ensure_ascii=False, sort_keys=True)


def _agent_live_activity_from_stream_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in blocks[-8:]:
        block_type = str(block.get("type") or "")
        event_id = "stream-" + hashlib.sha256(_agent_stream_block_key(block).encode("utf-8")).hexdigest()[:16]
        if block_type == "text":
            text = str(block.get("text") or "").strip()
            if text:
                rows.append({"id": event_id, "text": text, "kind": "thought"})
        elif block_type == "tool_use":
            name = _agent_stream_tool_name(str(block.get("name") or "Tool"))
            summary = ""
            raw_input = block.get("input") if isinstance(block.get("input"), dict) else {}
            for key in ("label", "action", "episodeId", "episode_id", "assetType", "asset_type", "nodeId", "node_id"):
                if raw_input.get(key):
                    summary = str(raw_input.get(key))
                    break
            rows.append({"id": event_id, "text": f"调用工具：{name}{f'（{summary}）' if summary else ''}",
                         "kind": "tool_use", "toolName": name, "toolUseId": str(block.get("id") or "")})
        elif block_type == "tool_result":
            revision_required = block.get("outcome") == "revision_required"
            rows.append({"id": event_id, "text": "校验未通过，正在修订候选" if revision_required else "工具返回异常，正在保留原始错误" if block.get("is_error") else "工具已返回结果，正在整理回复",
                         "kind": "tool_result", "toolUseId": str(block.get("tool_use_id") or ""),
                         "isError": bool(block.get("is_error")),
                         **({"outcome": "revision_required"} if revision_required else {})})
    return _normalize_agent_live_activity(rows[-6:])


def _agent_draft_turn_from_stream_blocks(
    project_id: str,
    session_id: str,
    blocks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    content = [
        normalized
        for normalized in (_normalize_agent_stream_block(block) for block in blocks)
        if normalized and not (normalized.get("type") == "tool_use" and not normalized.get("is_error"))
        and not (normalized.get("type") == "tool_result" and not normalized.get("is_error"))
    ]
    if not content:
        return None
    return {
        "type": "assistant",
        "uuid": f"draft-{session_id}",
        "timestamp": _now(),
        "text": _agent_text_from_content_blocks(content),
        "content": _normalize_agent_content_blocks(content, project_id, hydrate=False),
    }


def _agent_live_activity_for_turn(
    state: dict[str, Any],
    message: str,
    *,
    phase: str = "start",
    preferred_action: str = "",
    goal: str = "",
) -> list[dict[str, Any]]:
    from .agent_action_contract import _agent_action_label
    from .source_text_store import _compact_text
    action_label = _agent_action_label(preferred_action, state) if preferred_action else ""
    received = _compact_text(str(message or "继续").strip(), 48)
    display_goal = _compact_text(str(goal or "").strip(), 80) or received
    if phase == "thinking":
        lines = [
            f"正在处理指令：{received}",
            "等待模型与工具返回执行事件",
        ]
    elif phase == "finalizing":
        lines = [
            "正在保存会话回复与项目状态",
        ]
    else:
        lines = [
            f"已收到指令：{received}",
            f"正在启动{action_label or '智能体回合'}",
        ]
    return _normalize_agent_live_activity([
        {"id": f"phase-{phase}-{index}", "text": line, "kind": "phase", "phase": phase,
         "goal": display_goal if phase == "start" and index == 0 else ""}
        for index, line in enumerate(lines)
    ])


def _save_agent_live_snapshot(
    project_id: str,
    session: dict[str, Any],
    live_activity: list[dict[str, Any]],
    *,
    draft_turn: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = _normalize_agent_live_activity(live_activity)
    session_id = str(session.get("id") or "").strip()
    execution = session.get("execution") if isinstance(session.get("execution"), dict) else {}
    execution_id = str(execution.get("id") or "").strip()
    if session_id and execution_id:
        try:
            previous = _load_agent_session_snapshot(project_id, session_id)
        except Exception:
            previous = None
        if isinstance(previous, dict) and previous.get("dispatchExecutionId") == execution_id:
            previous_rows = _normalize_agent_live_activity(previous.get("live_activity"))
            seen = {str(item.get("id") or "") for item in previous_rows}
            rows = previous_rows + [item for item in rows if str(item.get("id") or "") not in seen]
            rows = rows[-120:]
    snapshot = _agent_snapshot_from_session(
        project_id,
        session,
        hydrate=False,
        draft_turn=draft_turn,
        live_activity=rows,
    )
    if execution_id:
        snapshot["dispatchExecutionId"] = execution_id
    if session_id:
        try:
            _agent_session_service().save_snapshot(
                project_id,
                session_id,
                snapshot,
                updated_at=str(session.get("updatedAt") or _now()),
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"[agent-live] failed to save live snapshot({session_id}): {exc}",
                flush=True,
            )
    return snapshot


def _emit_agent_live_activity(
    project_id: str,
    episode_id: str | None,
    session_id: str,
    live_activity: list[dict[str, Any]],
    *,
    draft_turn: dict[str, Any] | None = None,
    expected_execution_id: str | None = None,
) -> None:
    from .agent_session_events import _agent_session_payload
    from utils.agent_execution_state import accepts_execution, current_execution_id
    with _LOCK:
        sessions = _load_agent_sessions(project_id)
        session = next((row for row in sessions if str(row.get("id") or "") == str(session_id)), None)
        if not isinstance(session, dict):
            return
        identity = current_execution_id(session_id) if expected_execution_id is None else expected_execution_id
        if not accepts_execution(session, identity) or session.get("status") != "running":
            return
        if draft_turn is None:
            try:
                existing_snapshot = _load_agent_session_snapshot(project_id, session_id)
                if isinstance(existing_snapshot, dict) and isinstance(existing_snapshot.get("draft_turn"), dict):
                    draft_turn = existing_snapshot.get("draft_turn")
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[agent-live] failed to load live snapshot({session_id}): {exc}",
                    flush=True,
                )
        snapshot = _save_agent_live_snapshot(
            project_id,
            session,
            live_activity,
            draft_turn=draft_turn,
        )
        payload = _agent_session_payload(
            project_id,
            episode_id,
            session,
            steps=session.get("steps") or [],
            pending_question=_normalize_agent_pending_question(session.get("pendingQuestion")),
        )
    _emit_agent_event(
        "agent_session_snapshot",
        {
            **payload,
            "snapshot": snapshot,
        },
    )


def _try_emit_agent_live_activity(
    project_id: str,
    episode_id: str | None,
    session_id: str,
    live_activity: list[dict[str, Any]],
    *,
    draft_turn: dict[str, Any] | None = None,
    expected_execution_id: str | None = None,
) -> None:
    try:
        _emit_agent_live_activity(
            project_id,
            episode_id,
            session_id,
            live_activity,
            draft_turn=draft_turn,
            expected_execution_id=expected_execution_id,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"[agent-live] failed to emit live activity({session_id}): {exc}",
            flush=True,
        )
        append_agent_execution_error(
            project_id,
            stage="emit_live_activity",
            message="推送智能体实时活动失败",
            episode_id=episode_id,
            session_id=session_id,
            category="event_emit_error",
            source="backend_event",
            error=exc,
            details={"liveActivity": live_activity, "draftTurn": draft_turn},
            include_traceback=True,
        )


def _hydrate_agent_snapshot_for_ui(project_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    hydrated = copy.deepcopy(snapshot)
    session = hydrated.get("session")
    if isinstance(session, dict):
        try:
            hydrated["session"] = _agent_session_detail(project_id, session)
        except FileNotFoundError:
            hydrated["session"] = session
    turns = hydrated.get("turns")
    if isinstance(turns, list):
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            content = _normalize_agent_content_blocks(turn.get("content"), project_id, hydrate=True)
            if content:
                turn["content"] = content
            attachments = _agent_message_attachment_rows(turn.get("attachments"), project_id, hydrate=True)
            if attachments:
                turn["attachments"] = attachments
    draft_turn = hydrated.get("draft_turn")
    if isinstance(draft_turn, dict):
        content = _normalize_agent_content_blocks(draft_turn.get("content"), project_id, hydrate=True)
        if content:
            draft_turn["content"] = content
            draft_turn["text"] = str(draft_turn.get("text") or "").strip() or _agent_text_from_content_blocks(content)
        attachments = _agent_message_attachment_rows(draft_turn.get("attachments"), project_id, hydrate=True)
        if attachments:
            draft_turn["attachments"] = attachments
    return hydrated


def list_agent_sessions(project_id: str, episode_id: str | None = None) -> dict[str, Any]:
    return {"success": True, "sessions": _agent_session_summaries(project_id, episode_id)}


def _agent_conversation_context_path(project_id: str) -> Path:
    return _project_dir(project_id) / "assistant" / "agent_conversation_context.json"


def _read_agent_conversation_context(project_id: str) -> dict[str, Any]:
    data = _read_json(_agent_conversation_context_path(project_id), {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schemaVersion", 1)
    data.setdefault("project", {})
    data.setdefault("episodes", {})
    return data


def _write_agent_conversation_context(project_id: str, data: dict[str, Any]) -> None:
    data = copy.deepcopy(data)
    data.setdefault("schemaVersion", 1)
    data["updatedAt"] = _now()
    _write_json(_agent_conversation_context_path(project_id), data)


def _agent_context_scope_key(scope: str, episode_id: str | None = None) -> tuple[str, str]:
    normalized_scope = str(scope or "").strip() or ("episode" if episode_id else "project")
    if normalized_scope not in {"project", "episode"}:
        normalized_scope = "episode" if episode_id else "project"
    key = str(episode_id or "").strip() if normalized_scope == "episode" else "project"
    return normalized_scope, key


def _latest_agent_session_id(project_id: str, scope: str, episode_id: str | None = None) -> str:
    filter_episode_id = episode_id if scope == "episode" else "__project__"
    sessions = _agent_session_summaries(project_id, filter_episode_id)
    if not sessions and scope == "project":
        sessions = [
            item
            for item in _agent_session_summaries(project_id, None)
            if str(item.get("scope") or "") == "project"
            or str(item.get("episodeId") or "") in {"", "__project__", "project"}
        ]
    return str((sessions[0] if sessions else {}).get("id") or "")


def get_agent_conversation_context(
    project_id: str,
    episode_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    scope, key = _agent_context_scope_key(str(payload.get("scope") or ""), episode_id)
    context = _read_agent_conversation_context(project_id)
    bucket = context.get("project") if scope == "project" else context.get("episodes", {}).get(key)
    bucket = bucket if isinstance(bucket, dict) else {}
    session_id = str(bucket.get("sessionId") or "").strip()
    if not session_id:
        session_id = _latest_agent_session_id(project_id, scope, episode_id)
    active_target = (
        bucket.get("activeTarget")
        if isinstance(bucket.get("activeTarget"), dict)
        else None
    )
    if scope == "project" and isinstance(active_target, dict) and active_target.get("section") == "episode":
        active_target = None
    context_bucket = copy.deepcopy(bucket)
    if active_target is None:
        context_bucket.pop("activeTarget", None)
    else:
        context_bucket["activeTarget"] = active_target
    return {
        "success": True,
        "projectId": project_id,
        "episodeId": episode_id,
        "scope": scope,
        "sessionId": session_id,
        "context": context_bucket,
        "activeTarget": active_target,
    }


def set_agent_conversation_context(
    project_id: str,
    episode_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    scope, key = _agent_context_scope_key(str(payload.get("scope") or ""), episode_id)
    session_id = str(payload.get("sessionId") or "").strip()
    if not session_id:
        raise ValueError("缺少 sessionId")
    expected_episode_id = "__project__" if scope == "project" else str(episode_id or "").strip()
    existing_session = next(
        (row for row in _load_agent_sessions(project_id) if str(row.get("id") or "") == session_id),
        None,
    )
    if not existing_session or str(existing_session.get("episodeId") or "") != expected_episode_id:
        raise ValueError("会话不属于当前项目或分集范围")
    active_target = _sanitize_agent_target_context(
        payload.get("activeTarget") or payload.get("active_target")
    )
    if existing_session.get("canvasTask"):
        active_target = copy.deepcopy(existing_session["canvasTask"]["target"])
    if scope == "project" and active_target.get("section") == "episode":
        active_target = {}
    context = _read_agent_conversation_context(project_id)
    row = {
        "scope": scope,
        "sessionId": session_id,
        "episodeId": episode_id if scope == "episode" else None,
        "workflowId": payload.get("workflowId") or payload.get("workflow_id"),
        "updatedAt": _now(),
    }
    if active_target:
        row["activeTarget"] = active_target
    if scope == "project":
        context["project"] = row
    else:
        episodes = context.get("episodes") if isinstance(context.get("episodes"), dict) else {}
        episodes[key] = row
        context["episodes"] = episodes
    _write_agent_conversation_context(project_id, context)
    return {"success": True, **row, "projectId": project_id}


def list_agent_conversations(
    project_id: str,
    episode_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    scope, _key = _agent_context_scope_key(str(payload.get("scope") or ""), episode_id)
    filter_episode_id = episode_id if scope == "episode" else "__project__"
    sessions = _agent_session_summaries(project_id, filter_episode_id)
    if scope == "project" and not sessions:
        sessions = [
            item
            for item in _agent_session_summaries(project_id, None)
            if str(item.get("episodeId") or "") in {"", "__project__", "project"}
        ]
    return {"success": True, "scope": scope, "episodeId": episode_id, "conversations": sessions, "sessions": sessions}


def create_agent_conversation(project_id: str, episode_id: str | None = None,
                              payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from .agent_conversation_context import _apply_agent_session_context

    payload = payload if isinstance(payload, dict) else {}
    scope, _ = _agent_context_scope_key(str(payload.get("scope") or ""), episode_id)
    owner_episode_id = "__project__" if scope == "project" else str(episode_id or "").strip()
    if scope == "episode" and not owner_episode_id:
        raise ValueError("创建分集会话需要明确分集")
    title = str(payload.get("title") or ("项目会话" if scope == "project" else f"{owner_episode_id} 分集会话"))
    with _LOCK:
        session, sessions = _ensure_agent_session(project_id, None, owner_episode_id, title)
        _apply_agent_session_context(session, scope=scope, episode_id=owner_episode_id,
                                     workflow_id=payload.get("workflowId"))
        _save_agent_sessions(project_id, sessions)
    set_agent_conversation_context(project_id, episode_id,
                                   {"scope": scope, "sessionId": session["id"],
                                    "workflowId": payload.get("workflowId")})
    return {"success": True, "conversation": _agent_session_summary(session),
            "session": _agent_session_detail(project_id, session), "sessionId": session["id"]}


def ensure_episode_agent_conversation(project_id: str, episode_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    title = str(payload.get("title") or f"{episode_id} 分集会话")
    session_id = str(payload.get("sessionId") or "").strip() or None
    session, sessions = _ensure_agent_session(project_id, session_id, episode_id, title)
    session["scope"] = "episode"
    session["contextScope"] = "episode"
    workflow_id = str(payload.get("workflowId") or payload.get("workflow_id") or "").strip()
    if workflow_id:
        session["workflowId"] = workflow_id
    _save_agent_sessions(project_id, sessions)
    context_result = set_agent_conversation_context(
        project_id,
        episode_id,
        {
            "scope": "episode",
            "sessionId": session.get("id"),
            "workflowId": payload.get("workflowId") or payload.get("workflow_id"),
        },
    )
    return {
        "success": True,
        "conversation": _agent_session_summary(session),
        "session": _agent_session_detail(project_id, session),
        "context": context_result,
    }


def _session_matches_requested_scope(session: dict[str, Any], scope: str | None,
                                     episode_id: str | None) -> bool:
    if not scope:
        return True
    expected_scope, _ = _agent_context_scope_key(scope, episode_id)
    expected_episode = "__project__" if expected_scope == "project" else str(episode_id or "").strip()
    return (str(session.get("scope") or "") == expected_scope
            and str(session.get("episodeId") or "") == expected_episode)


def get_agent_session(project_id: str, session_id: str, *, scope: str | None = None,
                      episode_id: str | None = None) -> dict[str, Any]:
    for row in _load_agent_sessions(project_id):
        if str(row.get("id") or "") == str(session_id):
            if not _session_matches_requested_scope(row, scope, episode_id):
                raise ValueError("会话不属于当前项目或分集范围")
            return {"success": True, "session": _agent_session_detail(project_id, row)}
    raise FileNotFoundError("智能体会话不存在")


def get_agent_snapshot(project_id: str, session_id: str, *, scope: str | None = None,
                       episode_id: str | None = None) -> dict[str, Any]:
    from .agent_run_store import session_candidate_statuses

    matching_session: dict[str, Any] | None = None
    for row in _load_agent_sessions(project_id):
        if str(row.get("id") or "") == str(session_id):
            matching_session = row
            break
    if matching_session is None:
        raise FileNotFoundError("智能体会话不存在")
    if not _session_matches_requested_scope(matching_session, scope, episode_id):
        raise ValueError("会话不属于当前项目或分集范围")
    if session_candidate_statuses(project_id, str(session_id)):
        live_snapshot = _load_agent_session_snapshot(project_id, str(session_id))
        is_running = str(matching_session.get("status") or "") == "running"
        return {"success": True, "snapshot": _agent_snapshot_from_session(
            project_id, matching_session,
            draft_turn=live_snapshot.get("draft_turn") if is_running and isinstance(live_snapshot, dict) else None,
            live_activity=live_snapshot.get("live_activity") if is_running and isinstance(live_snapshot, dict) else None,
        )}
    snapshot = _load_agent_session_snapshot(project_id, str(session_id))
    if snapshot is not None:
        snapshot_session = snapshot.get("session") if isinstance(snapshot.get("session"), dict) else {}
        snapshot_status = str(snapshot.get("status") or snapshot_session.get("status") or "").strip()
        session_status = str(matching_session.get("status") or "").strip()
        snapshot_updated_at = str(
            snapshot_session.get("updatedAt")
            or snapshot_session.get("updated_at")
            or ""
        ).strip()
        session_updated_at = str(
            matching_session.get("updatedAt")
            or matching_session.get("updated_at")
            or ""
        ).strip()
        snapshot_is_stale = bool(
            (session_status and snapshot_status and snapshot_status != session_status)
            or (
                session_updated_at
                and snapshot_updated_at
                and snapshot_updated_at != session_updated_at
            )
        )
        if snapshot_is_stale:
            return {"success": True, "snapshot": _agent_snapshot_from_session(project_id, matching_session)}
        return {"success": True, "snapshot": _hydrate_agent_snapshot_for_ui(project_id, snapshot)}
    return {"success": True, "snapshot": _agent_snapshot_from_session(project_id, matching_session)}


def delete_agent_session(project_id: str, session_id: str) -> dict[str, Any]:
    from .task_control import _update_task_fields
    session_id_value = str(session_id)
    task = None
    task_id = ""
    cancelled = False
    with _LOCK:
        sessions = _load_agent_sessions(project_id)
        session = next((row for row in sessions if str(row.get("id") or "") == session_id_value), None)
        if session is None:
            raise FileNotFoundError("智能体会话不存在")
        if str(session.get("status") or "") == "running":
            raise ValueError("当前会话仍在执行，请先停止任务再删除会话")
        if any((row.get("canvasTask") or {}).get("parentSessionId") == session_id_value
               and row.get("status") not in {"error", "interrupted"}
               and (row.get("status") == "running" or (row.get("status") == "idle" and
                    (row.get("canvasTask") or {}).get("starting")) or row.get("pendingQuestion") or row.get("pendingOperation"))
               for row in sessions):
            raise ValueError("此画布会话还有执行中或待处理的任务，请处理后再删除")
        deleted = _agent_session_service().delete_session(project_id, session_id_value)
        cancel_flag = _AGENT_CANCEL_FLAGS.get(session_id_value)
        if cancel_flag:
            cancel_flag.set()
            cancelled = True
        task_id = str(session.get("taskId") or "").strip()
    if not deleted:
        raise FileNotFoundError("智能体会话不存在")
    if task_id:
        task = _update_task_fields(
            task_id,
            status="failed",
            progress=0,
            message="智能体会话已删除，后台执行已取消",
        )
    return {"success": True, "sessionId": session_id, "cancelled": cancelled, "task": task}


def _prepare_agent_sessions_for_project_delete(project_id: str) -> dict[str, Any]:
    db_path = _agent_sessions_db_path(project_id)
    if not db_path.exists():
        return {
            "agentSessionDatabase": "missing",
            "agentSessionCount": 0,
            "cancelledAgentSessionCount": 0,
        }

    try:
        sessions = _load_agent_sessions(project_id)
    except Exception as exc:  # noqa: BLE001 - project delete should still remove a bad DB file.
        return {
            "agentSessionDatabase": "delete_with_project",
            "agentSessionCount": 0,
            "cancelledAgentSessionCount": 0,
            "agentSessionCleanupWarning": str(exc),
        }

    cancelled: set[str] = set()
    with _LOCK:
        for session in sessions:
            session_id = str(session.get("id") or "").strip()
            if not session_id:
                continue
            cancel_flag = _AGENT_CANCEL_FLAGS.get(session_id)
            if cancel_flag:
                cancel_flag.set()
                cancelled.add(session_id)
            elif str(session.get("status") or "") == "running":
                cancelled.add(session_id)

    return {
        "agentSessionDatabase": "delete_with_project",
        "agentSessionCount": len(sessions),
        "cancelledAgentSessionCount": len(cancelled),
    }


def _ensure_agent_session(project_id: str, session_id: str | None, episode_id: str, title: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sessions = _load_agent_sessions(project_id)
    target: dict[str, Any] | None = None
    if session_id:
        target = next((row for row in sessions if str(row.get("id") or "") == str(session_id)), None)
    if target is None and session_id:
        raise FileNotFoundError("当前会话不存在，请重新选择或创建会话")
    if target is None:
        now = _now()
        target = {
            "id": session_id or f"assistant-session-{uuid.uuid4().hex[:10]}",
            "title": title or "新会话",
            "episodeId": episode_id or "E01",
            "status": "idle",
            "createdAt": now,
            "updatedAt": now,
            "messages": [],
            "steps": [],
        }
        sessions.insert(0, target)
    else:
        stored_episode_id = str(target.get("episodeId") or "E01")
        requested_episode_id = str(episode_id or "E01")
        if stored_episode_id != requested_episode_id:
            raise ValueError("会话所属范围已变化，请切换到对应项目或分集会话")
        target["title"] = str(target.get("title") or title or "新会话")
    return target, sessions

__all__ = (
    '_project_dir', '_project_meta_path', '_project_config_path', '_agent_session_service',
    '_agent_sessions_db_path', '_agent_session_repo', '_agent_session_sql_failure',
    '_project_agent_attachments_dir', '_project_agent_logs_dir', '_agent_log_date_key', '_agent_log_sanitize',
    'append_agent_execution_error', 'list_agent_error_logs', 'clear_agent_error_logs', '_image_suffix_from_mime_or_name',
    '_mime_from_image_suffix', '_file_suffix_from_mime_or_name', '_mime_from_file_suffix',
    '_decode_agent_attachment_data_url', '_project_file_from_ref', '_agent_attachment_ref_from_path',
    '_local_agent_attachment_source_from_media', '_save_agent_attachment_source_file',
    '_hydrate_agent_attachment_row', '_agent_message_attachment_rows', 'save_agent_attachment',
    '_PERSISTENT_MEDIA_DATA_KEYS', '_storage_key_token', '_is_inline_media_string', '_looks_like_large_base64',
    '_persistent_media_data_removed', '_transient_image_keys_removed', '_media_ref_for_storage',
    '_thumbnail_ref_for_storage', '_hydrate_media_asset_for_ui', '_asset_source_metadata_for_ui',
    '_hydrate_asset_row_for_ui', '_hydrate_assets_for_ui', '_agent_message_row',
    '_agent_attachment_input_from_block', '_agent_image_attachment_input_from_block',
    '_agent_file_attachment_input_from_block', '_agent_attachment_error_content_block',
    '_agent_content_block_log_details', '_agent_image_content_block_from_ref',
    '_agent_file_content_block_from_ref', '_agent_blocks_from_attachment_fields',
    '_AGENT_UI_ONLY_RECOMMENDATION_ACTIONS', '_AGENT_UI_ONLY_RECOMMENDATION_PATTERNS',
    '_agent_is_ui_only_recommendation', '_normalize_agent_action_footer',
    '_agent_action_footer_text', '_agent_merge_action_footer_values',
    '_agent_attach_action_footer_to_content_blocks', '_normalize_agent_content_blocks', '_agent_text_from_content_blocks',
    '_agent_blocks_have_body_text', '_agent_blocks_have_text', '_agent_message_is_control_only',
    '_normalize_agent_message_rows', '_normalize_agent_history_summary',
    '_agent_message_summary_line', '_merge_agent_history_summary', '_apply_agent_message_retention',
    '_normalize_agent_session_step_rows', '_normalize_agent_pending_question', '_normalize_agent_pending_operation',
    '_normalize_agent_session_row',
    '_load_agent_session_snapshot', '_load_agent_sessions', '_save_agent_sessions',
    '_agent_session_updated_age_seconds', '_recover_stale_running_agent_sessions',
    '_agent_session_title_for_message', '_agent_session_summary', '_agent_session_summaries',
    '_agent_session_detail', '_agent_snapshot_from_session', '_normalize_agent_live_activity',
    '_agent_stream_tool_name', '_normalize_agent_stream_block', '_agent_stream_block_key',
    '_agent_live_activity_from_stream_blocks', '_agent_draft_turn_from_stream_blocks',
    '_agent_live_activity_for_turn', '_save_agent_live_snapshot', '_emit_agent_live_activity',
    '_try_emit_agent_live_activity', '_hydrate_agent_snapshot_for_ui', 'list_agent_sessions',
    'get_agent_conversation_context', 'set_agent_conversation_context',
    'list_agent_conversations', 'create_agent_conversation', 'ensure_episode_agent_conversation',
    'get_agent_session', 'get_agent_snapshot', 'delete_agent_session',
    '_prepare_agent_sessions_for_project_delete', '_ensure_agent_session'
)
