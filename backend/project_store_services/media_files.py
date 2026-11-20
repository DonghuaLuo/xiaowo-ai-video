# -*- coding: utf-8 -*-
"""项目/全局媒体文件保存、复制、解码、下载和引用转换。"""

from __future__ import annotations

from .agent_sessions import _project_dir


import base64
import copy
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from array import array
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from utils.image_pipeline import (
    convert_image_bytes_to_png,
    data_url_from_bytes,
    image_file_metadata,
    save_project_image,
    save_provider_output_image,
)
from utils.model_timeouts import MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS


from .catalogs import FAVORITE_STYLE_THUMBNAILS_DIR
from .catalogs import GLOBAL_ASSET_MEDIA_DIR
from .catalogs import GLOBAL_ASSETS_PATH
from .catalogs import GLOBAL_DIR
from .catalogs import IMAGE_EXTENSIONS
from .catalogs import STYLE_THUMBNAILS_DIR
from .catalogs import VIDEO_EXTENSIONS

# Use the shortest maximum clip duration among the currently supported
# reference-audio video models so one normalized file remains portable.
# The currently supported reference-audio models accept clips from 2 to 15
# seconds.  Keep both bounds in one place so the upload and crop paths cannot
# silently produce clips that the next stage rejects.
VOICE_REFERENCE_AUDIO_MIN_DURATION_SECONDS = 2
VOICE_REFERENCE_AUDIO_DEFAULT_DURATION_SECONDS = 15
VOICE_REFERENCE_AUDIO_PREVIEW_MAX_SECONDS = 10 * 60
VOICE_REFERENCE_AUDIO_SAMPLE_RATE = 24000
VOICE_REFERENCE_AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".flac", ".wma",
    ".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v",
}


def _reference_audio_temp_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "xiaowo-ai-video-reference-audio"
    path.mkdir(parents=True, exist_ok=True)
    # Temporary previews are intentionally short lived. This also cleans up
    # previews left behind when the desktop window is closed mid-edit.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for candidate in path.glob("*.wav"):
        try:
            modified = datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc)
            if modified < cutoff:
                candidate.unlink(missing_ok=True)
        except OSError:
            continue
    return path


def _reference_audio_temp_path(raw_path: str | Path) -> Path:
    path = Path(str(raw_path)).expanduser().resolve()
    temp_dir = _reference_audio_temp_dir().resolve()
    try:
        if not path.is_relative_to(temp_dir):
            raise ValueError("参考音频临时文件无效")
    except AttributeError:
        if not str(path).startswith(str(temp_dir)):
            raise ValueError("参考音频临时文件无效")
    if not path.is_file() or path.suffix.lower() != ".wav":
        raise ValueError("参考音频临时文件不存在")
    return path


def _read_pcm_wav(path: Path) -> tuple[array, int, int]:
    with wave.open(str(path), "rb") as reader:
        channels = reader.getnchannels()
        sample_width = reader.getsampwidth()
        sample_rate = reader.getframerate()
        if sample_width != 2 or sample_rate <= 0:
            raise ValueError("参考音频格式不受支持")
        frames = reader.readframes(reader.getnframes())
    samples = array("h")
    samples.frombytes(frames)
    if channels > 1:
        mono = array("h")
        for index in range(0, len(samples), channels):
            chunk = samples[index : index + channels]
            mono.append(int(sum(chunk) / max(len(chunk), 1)))
        samples = mono
    return samples, sample_rate, len(samples)


def _quiet_cut_sample(samples: array, sample_rate: int, max_seconds: float) -> int:
    """Match the reference plugins: choose the quietest continuous 50ms window."""
    total = len(samples)
    target = min(total, max(1, int(round(max_seconds * sample_rate))))
    if total <= target or sample_rate <= 0:
        return total
    search_window_samples = min(5 * sample_rate, target)
    min_sample = max(0, target - search_window_samples)
    frame = max(1, int(round(0.010 * sample_rate)))
    hop = max(1, int(round(0.005 * sample_rate)))
    required_samples = max(frame, int(round(0.050 * sample_rate)))
    if target <= min_sample:
        return target

    frames: list[tuple[int, float]] = []
    cursor = min_sample
    while cursor + frame <= target:
        block = samples[cursor : cursor + frame]
        if block:
            rms = math.sqrt(sum(value * value for value in block) / len(block))
            frames.append((cursor, rms))
        cursor += hop
    if not frames:
        return target

    required_frames = max(1, math.ceil(max(0, required_samples - frame) / hop) + 1)
    if len(frames) < required_frames:
        return target
    prefix = [0.0]
    for _, rms in frames:
        prefix.append(prefix[-1] + rms)
    best_avg: float | None = None
    best_cut = target
    for start_index in range(len(frames) - required_frames + 1):
        end_index = start_index + required_frames - 1
        average = (prefix[end_index + 1] - prefix[start_index]) / required_frames
        cut_sample = min(target, frames[end_index][0] + frame)
        if (
            best_avg is None
            or average < best_avg - 1e-12
            or (abs(average - best_avg) <= 1e-12 and cut_sample > best_cut)
        ):
            best_avg = average
            best_cut = cut_sample
    return max(1, min(target, best_cut))


def _write_pcm_wav(
    path: Path,
    samples: array,
    sample_rate: int,
    *,
    fade_in_ms: float = 10.0,
    fade_out_ms: float = 10.0,
) -> None:
    samples = array("h", samples)
    fade_in_samples = min(int(round(sample_rate * fade_in_ms / 1000.0)), len(samples) // 2)
    fade_out_samples = min(int(round(sample_rate * fade_out_ms / 1000.0)), len(samples) // 2)
    if fade_in_samples:
        for index in range(fade_in_samples):
            samples[index] = int(samples[index] * (index + 1) / fade_in_samples)
    if fade_out_samples:
        for index in range(fade_out_samples):
            reverse_index = len(samples) - fade_out_samples + index
            samples[reverse_index] = int(
                samples[reverse_index] * (fade_out_samples - index) / fade_out_samples
            )
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(samples.tobytes())


def prepare_reference_audio(
    media: dict[str, Any] | str | None,
    *,
    max_seconds: float = VOICE_REFERENCE_AUDIO_PREVIEW_MAX_SECONDS,
) -> dict[str, Any]:
    """Convert a selected audio/video file to a temporary PCM WAV preview."""
    if isinstance(media, str):
        media = {"path": media}
    source = _audio_source_from_media(None, media or {})
    if not source:
        raise ValueError("请选择有效的音频或视频文件")
    source_path, source_mime = source
    max_seconds = max(1.0, min(float(max_seconds), VOICE_REFERENCE_AUDIO_PREVIEW_MAX_SECONDS))
    output_path = _reference_audio_temp_dir() / f"preview-{uuid.uuid4().hex}.wav"
    from .video_clips import _media_tool_executable

    result = subprocess.run(
        [
            _media_tool_executable("ffmpeg"), "-y", "-i", str(source_path),
            "-map", "0:a:0", "-t", f"{max_seconds:.3f}", "-vn", "-ac", "1",
            "-ar", str(VOICE_REFERENCE_AUDIO_SAMPLE_RATE), "-c:a", "pcm_s16le",
            str(output_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or not output_path.is_file():
        output_path.unlink(missing_ok=True)
        detail = (result.stderr or "").strip().splitlines()[-1:] or ["音频预处理失败"]
        raise ValueError(detail[0][:240])
    duration = _audio_duration_seconds(output_path) or 0.0
    return {
        "success": True,
        "processedPath": str(output_path),
        "duration": duration,
        "originalDuration": _audio_duration_seconds(source_path),
        "sourceMimeType": source_mime,
        "sourceName": source_path.name,
    }


def crop_reference_audio(
    audio_path: str,
    *,
    start: float | None = None,
    end: float | None = None,
    max_seconds: float = VOICE_REFERENCE_AUDIO_DEFAULT_DURATION_SECONDS,
) -> dict[str, Any]:
    """Crop a preview to a final <=15s WAV, using a quiet boundary by default."""
    source_path = _reference_audio_temp_path(audio_path)
    samples, sample_rate, total = _read_pcm_wav(source_path)
    if total <= 0 or sample_rate <= 0:
        raise ValueError("参考音频没有可用内容")
    duration = total / sample_rate if sample_rate else 0.0
    if duration < VOICE_REFERENCE_AUDIO_MIN_DURATION_SECONDS:
        raise ValueError(
            f"参考音频时长不能少于 {VOICE_REFERENCE_AUDIO_MIN_DURATION_SECONDS} 秒"
        )
    max_seconds = max(
        VOICE_REFERENCE_AUDIO_MIN_DURATION_SECONDS,
        min(float(max_seconds), VOICE_REFERENCE_AUDIO_DEFAULT_DURATION_SECONDS),
    )
    has_any_range = start is not None or end is not None
    if has_any_range:
        if start is None or end is None:
            raise ValueError("裁剪时间范围不完整")
        try:
            requested_start = float(start)
            requested_end = float(end)
        except (TypeError, ValueError):
            raise ValueError("裁剪时间参数无效") from None
        if not math.isfinite(requested_start) or not math.isfinite(requested_end):
            raise ValueError("裁剪时间参数无效")
        if requested_end <= requested_start:
            raise ValueError("裁剪结束时间必须大于开始时间")
        start_sample = max(0, min(total - 1, int(round(requested_start * sample_rate))))
        end_sample = max(start_sample + 1, min(total, int(round(requested_end * sample_rate))))
        if (end_sample - start_sample) / sample_rate < VOICE_REFERENCE_AUDIO_MIN_DURATION_SECONDS:
            raise ValueError(
                f"裁剪范围过短，至少需要 {VOICE_REFERENCE_AUDIO_MIN_DURATION_SECONDS} 秒"
            )
        if (end_sample - start_sample) / sample_rate > max_seconds + 0.01:
            raise ValueError(f"截取范围不能超过 {int(max_seconds)} 秒")
    else:
        start_sample = 0
        end_sample = _quiet_cut_sample(samples, sample_rate, max_seconds)
    output_path = _reference_audio_temp_dir() / f"crop-{uuid.uuid4().hex}.wav"
    _write_pcm_wav(
        output_path,
        samples[start_sample:end_sample],
        sample_rate,
        fade_in_ms=0.0 if not has_any_range else 10.0,
        fade_out_ms=20.0 if not has_any_range else 10.0,
    )
    return {
        "success": True,
        "processedPath": str(output_path),
        "duration": (end_sample - start_sample) / sample_rate,
        "start": start_sample / sample_rate,
        "end": end_sample / sample_rate,
        "sourceDuration": duration,
    }


def cleanup_reference_audio(paths: list[str] | str | None) -> dict[str, Any]:
    values = [paths] if isinstance(paths, str) else (paths or [])
    removed = 0
    for value in values:
        try:
            path = _reference_audio_temp_path(str(value))
            path.unlink(missing_ok=True)
            removed += 1
        except (ValueError, OSError):
            continue
    return {"success": True, "removed": removed}

def _storage_png_data_url(file_info: dict[str, Any]) -> str:
    return str(
        file_info.get("outputPngDataUrl")
        or file_info.get("pngDataUrl")
        or file_info.get("storedPngDataUrl")
        or file_info.get("dataUrl")
        or ""
    ).strip()


def _source_image_data_url(file_info: dict[str, Any]) -> str:
    return str(
        file_info.get("dataUrl")
        or file_info.get("pngDataUrl")
        or file_info.get("outputPngDataUrl")
        or file_info.get("storedPngDataUrl")
        or file_info.get("preview")
        or ""
    ).strip()


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    if "," not in data_url:
        return base64.b64decode(data_url), "application/octet-stream"
    header, payload = data_url.split(",", 1)
    mime = "application/octet-stream"
    match = re.match(r"data:([^;]+);base64", header)
    if match:
        mime = match.group(1)
    return base64.b64decode(payload), mime


def _data_url(mime: str, raw: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _source_media_data_url(file_info: dict[str, Any]) -> str:
    for key in ("dataUrl", "data_url", "pngDataUrl", "png_data_url", "outputPngDataUrl", "output_png_data_url", "preview"):
        value = file_info.get(key)
        if isinstance(value, str) and value.startswith("data:"):
            return value
    return ""


def _normalized_image_payload(raw: bytes, mime: str, *, include_data_url: bool = True) -> dict[str, Any]:
    try:
        png_raw = convert_image_bytes_to_png(raw)
        result: dict[str, Any] = {"pngRaw": png_raw}
        if include_data_url:
            result["pngDataUrl"] = data_url_from_bytes("image/png", png_raw)
        return result
    except Exception as exc:
        fallback_mime = mime if str(mime).startswith("image/") else "application/octet-stream"
        result = {
            "pngRaw": raw,
            "conversionWarning": f"图片格式转换失败，已保留原始数据：{exc}",
        }
        if include_data_url:
            result["pngDataUrl"] = _data_url(fallback_mime, raw)
        return result


def _file_extension(file_info: dict[str, Any], mime: str) -> str:
    mime_ext = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }.get(mime)
    if mime_ext in IMAGE_EXTENSIONS:
        return mime_ext
    name = str(file_info.get("name") or "")
    suffix = Path(name).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix
    return ".bin"


def _detect_image_mime(raw: bytes, fallback: str = "image/png") -> str:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith(b"RIFF") and len(raw) >= 12 and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    fallback_text = str(fallback or "").strip().lower()
    return fallback_text if fallback_text.startswith("image/") else "application/octet-stream"


def _safe_file_stem(value: Any, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-")
    return text or fallback


def _project_media_relative_path(project_id: str, path: Path) -> str:
    from .projects import _project_relative_path
    return _project_relative_path(project_id, path)


def _project_media_storage_dir(
    project_id: str,
    subdir: str,
    *,
    storage_scope: str = "assets",
    episode_id: str | None = None,
) -> Path:
    if storage_scope == "episode_results":
        safe_episode_id = _safe_file_stem(episode_id or "", "episode")
        return _project_dir(project_id) / "episodes" / safe_episode_id / "results" / subdir
    return _project_dir(project_id) / "assets" / subdir


def _save_project_media_file(
    project_id: str,
    raw: bytes,
    *,
    media_id: str,
    suffix: str,
    subdir: str = "generated",
    storage_scope: str = "assets",
    episode_id: str | None = None,
) -> dict[str, Any]:
    safe_id = _safe_file_stem(media_id, f"media-{uuid.uuid4().hex[:10]}")
    clean_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    media_dir = _project_media_storage_dir(
        project_id,
        subdir,
        storage_scope=storage_scope,
        episode_id=episode_id,
    )
    media_dir.mkdir(parents=True, exist_ok=True)
    path = media_dir / f"{safe_id}{clean_suffix.lower()}"
    path.write_bytes(raw)
    relative_path = _project_media_relative_path(project_id, path)
    return {
        "id": safe_id,
        "path": str(path),
        "relativePath": relative_path,
        "relative_path": relative_path,
        "file": relative_path,
        "filePath": str(path),
        "size": len(raw),
    }


def _save_project_image_media_file(
    project_id: str,
    raw: bytes,
    *,
    media_id: str,
    subdir: str = "media",
    original_name: str | None = None,
    source_mime: str = "image/png",
    storage_scope: str = "assets",
    episode_id: str | None = None,
) -> dict[str, Any]:
    normalized = _normalized_image_payload(raw, source_mime, include_data_url=False)
    safe_id = _safe_file_stem(media_id, f"media-{uuid.uuid4().hex[:10]}")
    media_dir = _project_media_storage_dir(
        project_id,
        subdir,
        storage_scope=storage_scope,
        episode_id=episode_id,
    )
    media_dir.mkdir(parents=True, exist_ok=True)
    output_path = media_dir / f"{safe_id}.png"
    final_path = save_provider_output_image(normalized["pngRaw"], output_path)
    relative_path = _project_media_relative_path(project_id, final_path)
    file_meta = {
        "id": safe_id,
        "path": str(final_path),
        "relativePath": relative_path,
        "relative_path": relative_path,
        "file": relative_path,
        "filePath": str(final_path),
        "size": final_path.stat().st_size,
        **image_file_metadata(final_path),
    }
    result = {
        **file_meta,
        "kind": "image",
        "originalName": original_name or "",
        "mimeType": "image/png",
        "pngFile": file_meta.get("file"),
    }
    if normalized.get("conversionWarning"):
        result["conversionWarning"] = normalized["conversionWarning"]
    return result


def _save_project_original_image_media_file(
    project_id: str,
    raw: bytes,
    *,
    media_id: str,
    subdir: str,
    source_mime: str = "",
    storage_scope: str = "assets",
    episode_id: str | None = None,
) -> dict[str, Any]:
    """Store a generated storyboard exactly as returned by the image provider."""
    mime = _detect_image_mime(raw, source_mime or "application/octet-stream")
    suffix = {"image/png": ".png", "image/jpeg": ".jpg",
              "image/webp": ".webp", "image/gif": ".gif"}.get(mime, ".bin")
    file_meta = _save_project_media_file(
        project_id, raw, media_id=media_id, suffix=suffix, subdir=subdir,
        storage_scope=storage_scope, episode_id=episode_id,
    )
    result = {
        **file_meta,
        **image_file_metadata(file_meta["path"]),
        "kind": "image",
        "originalName": f"{file_meta['id']}{suffix}",
        "mimeType": mime,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    if suffix == ".png":
        result["pngFile"] = file_meta["file"]
    return result


def _copy_local_project_image_media_file(
    project_id: str,
    source_path: Path,
    *,
    media_id: str,
    subdir: str = "media",
    original_name: str | None = None,
    source_mime: str | None = None,
    storage_scope: str = "assets",
    episode_id: str | None = None,
) -> dict[str, Any]:
    safe_id = _safe_file_stem(media_id, f"media-{uuid.uuid4().hex[:10]}")
    suffix = _image_suffix_from_mime_or_name(source_mime or "", original_name or source_path.name)
    media_dir = _project_media_storage_dir(
        project_id,
        subdir,
        storage_scope=storage_scope,
        episode_id=episode_id,
    )
    media_dir.mkdir(parents=True, exist_ok=True)
    final_path = media_dir / f"{safe_id}{suffix}"
    if source_path.resolve() != final_path.resolve():
        shutil.copy2(source_path, final_path)
    relative_path = _project_media_relative_path(project_id, final_path)
    return {
        "id": safe_id,
        "kind": "image",
        "path": str(final_path),
        "relativePath": relative_path,
        "relative_path": relative_path,
        "file": relative_path,
        "filePath": str(final_path),
        "size": final_path.stat().st_size,
        "originalName": original_name or source_path.name,
        "mimeType": str(source_mime or _mime_from_image_suffix(final_path)),
        "pngFile": relative_path,
    }


def _video_suffix_from_mime_or_name(mime: str, name: str) -> str:
    mime_ext = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "video/mov": ".mov",
        "video/x-matroska": ".mkv",
        "video/x-msvideo": ".avi",
        "video/x-m4v": ".m4v",
    }.get(str(mime or "").strip().lower())
    if mime_ext in VIDEO_EXTENSIONS:
        return mime_ext
    suffix = Path(str(name or "")).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return suffix
    return ".mp4"


def _mime_from_video_suffix(path: Path, fallback: str = "video/mp4") -> str:
    return {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
        ".m4v": "video/x-m4v",
    }.get(path.suffix.lower(), fallback)


def original_reference_video_media(media: dict[str, Any]) -> dict[str, Any]:
    """Read the original snapshot; normalized copies never become compression inputs."""
    if "referenceVideoOriginal" not in media:
        return dict(media)
    snapshot = media["referenceVideoOriginal"]
    if not isinstance(snapshot, dict) or not _local_video_source_from_media(snapshot):
        raise ValueError("参考视频的原始文件已丢失或来源无效，不能继续压缩副本，请重新关联原始视频")
    return dict(snapshot)


def video_media_metadata(project_id: str, media: dict[str, Any]) -> dict[str, Any]:
    """Probe the actual file (the probe cache is keyed by its size and mtime)."""
    from .video_clips import _probe_video

    path, info = _probe_video(project_id, media)
    stat = path.stat()
    return {
        **media, "kind": "video", "duration": float(info["duration"]),
        "videoDuration": float(info.get("videoDuration") or 0),
        "audioDuration": float(info.get("audioDuration") or 0),
        "containerDuration": float(info.get("containerDuration") or 0),
        "width": int(info.get("width") or 0), "height": int(info.get("height") or 0),
        "fps": float(info.get("fps") or 0), "size": stat.st_size,
        "format": path.suffix.lower().lstrip("."),
        "videoCodec": str(info.get("videoCodec") or ""),
        "audioCodecs": list(info.get("audioCodecs") or []),
        "durationFileSignature": {"size": stat.st_size, "mtimeNs": stat.st_mtime_ns},
    }


def _local_video_source_from_media(media: dict[str, Any]) -> tuple[Path, str] | None:
    for key in ("path", "filePath", "file_path"):
        raw = str(media.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).resolve()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            return path, str(media.get("mimeType") or media.get("mime_type") or _mime_from_video_suffix(path))
    return None


def _copy_local_project_video_media_file(
    project_id: str,
    source_path: Path,
    *,
    media_id: str,
    subdir: str = "media",
    original_name: str | None = None,
    source_mime: str | None = None,
    storage_scope: str = "assets",
    episode_id: str | None = None,
) -> dict[str, Any]:
    safe_id = _safe_file_stem(media_id, f"video-{uuid.uuid4().hex[:10]}")
    suffix = _video_suffix_from_mime_or_name(source_mime or "", original_name or source_path.name)
    media_dir = _project_media_storage_dir(
        project_id,
        subdir,
        storage_scope=storage_scope,
        episode_id=episode_id,
    )
    media_dir.mkdir(parents=True, exist_ok=True)
    final_path = media_dir / f"{safe_id}{suffix}"
    if source_path.resolve() != final_path.resolve():
        pending_path = final_path.with_name(f".{final_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copy2(source_path, pending_path)
            pending_path.replace(final_path)
        finally:
            pending_path.unlink(missing_ok=True)
    relative_path = _project_media_relative_path(project_id, final_path)
    return {
        "id": safe_id,
        "kind": "video",
        "path": str(final_path),
        "relativePath": relative_path,
        "relative_path": relative_path,
        "file": relative_path,
        "filePath": str(final_path),
        "size": final_path.stat().st_size,
        "originalName": original_name or source_path.name,
        "mimeType": str(source_mime or _mime_from_video_suffix(final_path)),
    }


def _audio_source_from_media(project_id: str | None, media: dict[str, Any]) -> tuple[Path, str] | None:
    """Resolve an uploaded audio/video path without accepting arbitrary project refs."""
    if not isinstance(media, dict):
        return None
    candidates: list[str] = []
    for key in ("path", "filePath", "file_path"):
        value = str(media.get(key) or "").strip()
        if value:
            candidates.append(value)
    if project_id:
        from .agent_sessions import _project_file_from_ref

        project_path = _project_file_from_ref(project_id, media)
        if project_path:
            candidates.append(str(project_path))
    global_path = _global_file_from_ref(media)
    if global_path:
        candidates.append(str(global_path))
    for raw in candidates:
        path = Path(raw).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in VOICE_REFERENCE_AUDIO_EXTENSIONS:
            continue
        mime = str(media.get("mimeType") or media.get("mime_type") or "").strip()
        return path, mime or "application/octet-stream"
    return None


def _audio_duration_seconds(path: Path) -> float | None:
    try:
        from .video_clips import _media_tool_executable

        result = subprocess.run(
            [
                _media_tool_executable("ffprobe"),
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                str(path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
        )
        payload = json.loads(result.stdout or "{}") if result.returncode == 0 else {}
        value = (payload.get("format") or {}).get("duration") if isinstance(payload, dict) else None
        duration = float(value)
        return duration if duration > 0 else None
    except Exception:
        return None


def _normalized_voice_wav_info(path: Path) -> dict[str, Any] | None:
    """Recognize an already prepared WAV without re-encoding or trimming it."""
    if path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(str(path), "rb") as reader:
            sample_rate = reader.getframerate()
            duration = reader.getnframes() / sample_rate if sample_rate else 0.0
            if (
                reader.getnchannels() != 1
                or reader.getsampwidth() != 2
                or sample_rate != VOICE_REFERENCE_AUDIO_SAMPLE_RATE
                or reader.getcomptype() != "NONE"
                or duration < VOICE_REFERENCE_AUDIO_MIN_DURATION_SECONDS
                or duration > VOICE_REFERENCE_AUDIO_DEFAULT_DURATION_SECONDS + 0.01
            ):
                return None
    except (OSError, EOFError, wave.Error):
        return None
    return {
        "kind": "audio",
        "mimeType": "audio/wav",
        "format": "wav",
        "codec": "pcm_s16le",
        "sampleRate": VOICE_REFERENCE_AUDIO_SAMPLE_RATE,
        "channels": 1,
        "duration": duration,
        "size": path.stat().st_size,
    }


def _store_voice_reference_audio_file(
    source_path: Path,
    source_mime: str,
    media: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Create an independently owned WAV; preserve prepared clips byte for byte."""
    from .video_clips import _media_tool_executable

    safe_id = f"voice-{uuid.uuid4().hex}"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_id}.wav"
    pending_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
    source_info = _normalized_voice_wav_info(source_path)
    try:
        if source_info:
            shutil.copyfile(source_path, pending_path)
            output_info = source_info
        else:
            result = subprocess.run(
                [
                    _media_tool_executable("ffmpeg"), "-y", "-i", str(source_path),
                    "-map", "0:a:0", "-t", str(VOICE_REFERENCE_AUDIO_DEFAULT_DURATION_SECONDS),
                    "-vn", "-ac", "1", "-ar", str(VOICE_REFERENCE_AUDIO_SAMPLE_RATE),
                    "-c:a", "pcm_s16le", "-f", "wav", str(pending_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode != 0 or not pending_path.is_file():
                detail = (result.stderr or "").strip().splitlines()[-1:] or ["ffmpeg 转码失败"]
                raise ValueError(detail[0][:240])
            duration = _audio_duration_seconds(pending_path) or 0.0
            if duration < VOICE_REFERENCE_AUDIO_MIN_DURATION_SECONDS:
                raise ValueError(f"参考音频时长不能少于 {VOICE_REFERENCE_AUDIO_MIN_DURATION_SECONDS} 秒")
            output_info = {
                "kind": "audio", "mimeType": "audio/wav", "format": "wav",
                "codec": "pcm_s16le", "sampleRate": VOICE_REFERENCE_AUDIO_SAMPLE_RATE,
                "channels": 1, "duration": duration, "size": pending_path.stat().st_size,
            }
        pending_path.replace(output_path)
    finally:
        pending_path.unlink(missing_ok=True)
    return {
        **output_info,
        "id": safe_id,
        "originalName": str(media.get("originalName") or media.get("name") or source_path.name),
        "path": str(output_path),
        "filePath": str(output_path),
        "sourceMimeType": source_mime,
        "sourceDuration": source_info["duration"] if source_info else _audio_duration_seconds(source_path),
    }


def _normalize_voice_reference_audio(
    project_id: str,
    media: dict[str, Any] | None,
    *,
    subdir: str = "voice",
    force_copy: bool = False,
) -> dict[str, Any] | None:
    """Store a project-owned voice reference, copying imports to an independent file."""
    from .agent_sessions import _media_ref_for_storage

    if not isinstance(media, dict):
        return None
    source = _audio_source_from_media(project_id, media)
    if not source:
        raise ValueError("请选择有效的音频或视频文件")
    source_path, source_mime = source
    info = _normalized_voice_wav_info(source_path)
    project_assets = (_project_dir(project_id) / "assets").resolve()
    if not force_copy and info and source_path.is_relative_to(project_assets):
        result = {**media, **info, "path": str(source_path), "filePath": str(source_path)}
    else:
        result = _store_voice_reference_audio_file(
            source_path, source_mime, media, _project_media_storage_dir(project_id, subdir)
        )
    relative_path = _project_media_relative_path(project_id, Path(result["path"]))
    return _media_ref_for_storage({
        **result,
        "relativePath": relative_path,
        "relative_path": relative_path,
        "file": relative_path,
    })


def _normalize_global_voice_reference_audio(
    asset_type: str,
    media: dict[str, Any] | None,
    *,
    force_copy: bool = False,
) -> dict[str, Any] | None:
    from .agent_sessions import _media_ref_for_storage
    from .projects import _global_relative_path

    if asset_type not in {"characters", "creatures"} or not isinstance(media, dict):
        return None
    source = _audio_source_from_media(None, media)
    if not source:
        raise ValueError("请选择有效的音频或视频文件")
    source_path, source_mime = source
    output_dir = (GLOBAL_ASSET_MEDIA_DIR / asset_type / "voice").resolve()
    info = _normalized_voice_wav_info(source_path)
    if not force_copy and info and source_path.is_relative_to(output_dir):
        result = {**media, **info, "path": str(source_path), "filePath": str(source_path)}
    else:
        result = _store_voice_reference_audio_file(source_path, source_mime, media, output_dir)
    relative_path = _global_relative_path(Path(result["path"]))
    return _media_ref_for_storage({
        **result,
        "relativePath": relative_path,
        "relative_path": relative_path,
        "file": relative_path,
    })


def _delete_global_voice_reference_audio_if_unreferenced(media: Any) -> bool:
    from .store_core import _read_json

    path = _global_asset_media_path(media)
    if not path or path.suffix.lower() != ".wav":
        return False
    path = path.resolve()

    def references(value: Any) -> bool:
        if isinstance(value, dict):
            candidate = _global_asset_media_path(value)
            if candidate and candidate.resolve() == path:
                return True
            return any(references(child) for child in value.values())
        if isinstance(value, list):
            return any(references(child) for child in value)
        return False

    if references(_read_json(GLOBAL_ASSETS_PATH, {})):
        return False
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _project_voice_reference_audio_path(project_id: str, media: Any) -> Path | None:
    """Resolve a stored voice reference path, limited to this project's assets."""
    if not isinstance(media, dict):
        return None
    from .agent_sessions import _project_file_from_ref

    path = _project_file_from_ref(project_id, media)
    if not path:
        return None
    assets_root = (_project_dir(project_id) / "assets").resolve()
    try:
        resolved = path.resolve()
        resolved.relative_to(assets_root)
    except (OSError, ValueError):
        return None
    return resolved


def _project_voice_reference_audio_paths(project_id: str) -> set[Path]:
    """Collect all persisted voice-reference paths before deleting a stale file."""
    from .agent_sessions import _project_meta_path
    from .store_core import _read_json

    paths: set[Path] = set()
    meta = _read_json(_project_meta_path(project_id), {})
    overview = meta.get("overview_analysis") if isinstance(meta, dict) else {}
    overview_result = overview.get("result") if isinstance(overview, dict) else {}
    def collect(value: Any) -> None:
        if isinstance(value, dict):
            # Retain any in-project WAV referenced by a nested media object,
            # including legacy fields and snapshots that are not voice-specific.
            path = _project_voice_reference_audio_path(project_id, value)
            if path and path.suffix.lower() == ".wav":
                paths.add(path)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(overview_result)

    assets_path = _project_dir(project_id) / "assets" / "assets.json"
    assets = _read_json(assets_path, {})
    collect(assets)
    return paths


def _delete_project_voice_reference_audio_if_unreferenced(
    project_id: str,
    media: Any,
) -> bool:
    """Delete a replaced/removed WAV only after the current store is written."""
    path = _project_voice_reference_audio_path(project_id, media)
    if not path or path.suffix.lower() != ".wav":
        return False
    if path in _project_voice_reference_audio_paths(project_id):
        return False
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _video_media_from_file_info(
    project_id: str | None,
    file_info: dict[str, Any],
    *,
    media_id: str | None = None,
    subdir: str = "media",
    storage_scope: str = "assets",
    episode_id: str | None = None,
) -> dict[str, Any]:
    from .agent_sessions import _media_ref_for_storage
    data_url = _source_media_data_url(file_info)
    if not (isinstance(data_url, str) and data_url.startswith("data:video/")):
        data_url = None
    local_source = _local_video_source_from_media(file_info)
    if not data_url and not local_source:
        raise ValueError("请选择视频文件")
    safe_id = _safe_file_stem(media_id or file_info.get("id"), f"video-{uuid.uuid4().hex[:10]}")
    original_name = str(file_info.get("name") or file_info.get("originalName") or "")
    if local_source and project_id:
        source_path, source_mime = local_source
        if not str(source_mime).startswith("video/"):
            raise ValueError("只支持视频文件")
        stored = _copy_local_project_video_media_file(
            project_id,
            source_path,
            media_id=safe_id,
            subdir=subdir,
            original_name=original_name or source_path.name,
            source_mime=source_mime,
            storage_scope=storage_scope,
            episode_id=episode_id,
        )
        return _media_ref_for_storage(stored)
    raw, mime = _decode_data_url(str(data_url))
    if not str(mime).startswith("video/"):
        raise ValueError("只支持视频文件")
    if project_id:
        suffix = _video_suffix_from_mime_or_name(mime, original_name)
        stored = _save_project_media_file(
            project_id,
            raw,
            media_id=safe_id,
            suffix=suffix,
            subdir=subdir,
            storage_scope=storage_scope,
            episode_id=episode_id,
        )
        return _media_ref_for_storage(
            {
                **stored,
                "kind": "video",
                "originalName": original_name,
                "mimeType": mime,
            }
        )
    return {
        "id": safe_id,
        "kind": "video",
        "originalName": original_name,
        "mimeType": mime,
        "dataUrl": str(data_url),
        "preview": str(data_url),
    }


def _save_project_config_image_file(
    project_id: str,
    raw: bytes,
    *,
    media_id: str,
    subdir: str,
    original_name: str | None = None,
    source_mime: str = "image/png",
) -> dict[str, Any]:
    normalized = _normalized_image_payload(raw, source_mime, include_data_url=False)
    safe_id = _safe_file_stem(media_id, f"config-image-{uuid.uuid4().hex[:10]}")
    media_dir = _project_dir(project_id) / "config_media" / subdir
    media_dir.mkdir(parents=True, exist_ok=True)
    output_path = media_dir / f"{safe_id}.png"
    final_path = save_provider_output_image(normalized["pngRaw"], output_path)
    relative_path = _project_media_relative_path(project_id, final_path)
    image_meta = image_file_metadata(final_path)
    result = {
        "id": safe_id,
        "kind": "image",
        "path": str(final_path),
        "relativePath": relative_path,
        "relative_path": relative_path,
        "file": relative_path,
        "filePath": str(final_path),
        "size": final_path.stat().st_size,
        **image_meta,
        "originalName": original_name or "",
        "mimeType": "image/png",
        "pngFile": relative_path,
    }
    if normalized.get("conversionWarning"):
        result["conversionWarning"] = normalized["conversionWarning"]
    return result


def _copy_local_project_config_image_file(
    project_id: str,
    source_path: Path,
    *,
    media_id: str,
    subdir: str,
    original_name: str | None = None,
    source_mime: str | None = None,
) -> dict[str, Any]:
    safe_id = _safe_file_stem(media_id, f"config-image-{uuid.uuid4().hex[:10]}")
    suffix = _image_suffix_from_mime_or_name(source_mime or "", original_name or source_path.name)
    media_dir = _project_dir(project_id) / "config_media" / subdir
    media_dir.mkdir(parents=True, exist_ok=True)
    final_path = media_dir / f"{safe_id}{suffix}"
    if source_path.resolve() != final_path.resolve():
        shutil.copy2(source_path, final_path)
    relative_path = _project_media_relative_path(project_id, final_path)
    return {
        "id": safe_id,
        "kind": "image",
        "path": str(final_path),
        "relativePath": relative_path,
        "relative_path": relative_path,
        "file": relative_path,
        "filePath": str(final_path),
        "size": final_path.stat().st_size,
        "originalName": original_name or source_path.name,
        "mimeType": str(source_mime or _mime_from_image_suffix(final_path)),
        "pngFile": relative_path,
    }


def _global_file_from_ref(value: dict[str, Any]) -> Path | None:
    from .projects import _is_path_within
    if not isinstance(value, dict):
        return None
    global_root = GLOBAL_DIR.resolve()
    for key in ("relativePath", "relative_path", "file", "pngFile"):
        raw = str(value.get(key) or "").strip()
        if not raw:
            continue
        path = (global_root / raw).resolve()
        if _is_path_within(path, GLOBAL_DIR):
            return path
    for key in ("path", "filePath", "file_path"):
        raw = str(value.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).resolve()
        if _is_path_within(path, GLOBAL_DIR):
            return path
    return None


def _save_global_asset_image_media_file(
    asset_type: str,
    raw: bytes,
    *,
    media_id: str,
    original_name: str | None = None,
    source_mime: str = "image/png",
) -> dict[str, Any]:
    from .projects import _global_relative_path
    normalized = _normalized_image_payload(raw, source_mime, include_data_url=False)
    safe_type = _safe_file_stem(asset_type, "assets")
    safe_id = _safe_file_stem(media_id, f"asset-{uuid.uuid4().hex[:10]}")
    media_dir = GLOBAL_ASSET_MEDIA_DIR / safe_type
    media_dir.mkdir(parents=True, exist_ok=True)
    output_path = media_dir / f"{safe_id}.png"
    final_path = save_provider_output_image(normalized["pngRaw"], output_path)
    relative_path = _global_relative_path(final_path)
    image_meta = image_file_metadata(final_path)
    result = {
        "id": safe_id,
        "kind": "image",
        "path": str(final_path),
        "relativePath": relative_path,
        "relative_path": relative_path,
        "file": relative_path,
        "filePath": str(final_path),
        "size": final_path.stat().st_size,
        **image_meta,
        "originalName": original_name or "",
        "mimeType": "image/png",
        "pngFile": relative_path,
    }
    if normalized.get("conversionWarning"):
        result["conversionWarning"] = normalized["conversionWarning"]
    return result


def _copy_local_global_asset_image_media_file(
    asset_type: str,
    source_path: Path,
    *,
    media_id: str,
    original_name: str | None = None,
    source_mime: str | None = None,
) -> dict[str, Any]:
    from .projects import _global_relative_path
    safe_type = _safe_file_stem(asset_type, "assets")
    safe_id = _safe_file_stem(media_id, f"asset-{uuid.uuid4().hex[:10]}")
    suffix = _image_suffix_from_mime_or_name(source_mime or "", original_name or source_path.name)
    media_dir = GLOBAL_ASSET_MEDIA_DIR / safe_type
    media_dir.mkdir(parents=True, exist_ok=True)
    final_path = media_dir / f"{safe_id}{suffix}"
    if source_path.resolve() != final_path.resolve():
        shutil.copy2(source_path, final_path)
    relative_path = _global_relative_path(final_path)
    return {
        "id": safe_id,
        "kind": "image",
        "path": str(final_path),
        "relativePath": relative_path,
        "relative_path": relative_path,
        "file": relative_path,
        "filePath": str(final_path),
        "size": final_path.stat().st_size,
        "originalName": original_name or source_path.name,
        "mimeType": str(source_mime or _mime_from_image_suffix(final_path)),
        "pngFile": relative_path,
    }


def _local_image_source_from_media(media: dict[str, Any]) -> tuple[Path, str] | None:
    from .projects import _favorite_style_thumbnail_path
    from .projects import _is_path_within
    for key in ("path", "filePath", "file_path"):
        raw = str(media.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).resolve()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            return path, str(media.get("mimeType") or media.get("mime_type") or _mime_from_image_suffix(path))
    source = str(media.get("source") or "").strip()
    is_favorite_source = source in {"favorite_style", "global_style"} or media.get("category") == "favorite"
    if is_favorite_source:
        path = _favorite_style_thumbnail_path(media)
        if path and path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            return path.resolve(), str(media.get("mimeType") or media.get("mime_type") or _mime_from_image_suffix(path))
    raw_thumbnail = str(media.get("styleThumbnailFile") or media.get("style_thumbnail_file") or "").strip()
    if not raw_thumbnail and not is_favorite_source:
        raw_thumbnail = str(media.get("thumbnailFile") or media.get("thumbnail_file") or "").strip()
    if raw_thumbnail:
        clean = Path(raw_thumbnail.replace("\\", "/")).name
        path = (STYLE_THUMBNAILS_DIR / clean).resolve()
        if (
            clean
            and Path(clean).suffix.lower() in IMAGE_EXTENSIONS
            and _is_path_within(path, STYLE_THUMBNAILS_DIR)
            and path.is_file()
        ):
            return path, str(media.get("mimeType") or media.get("mime_type") or _mime_from_image_suffix(path))
    return None


def _has_image_file_input(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    data_url = _source_image_data_url(value)
    if isinstance(data_url, str) and data_url.startswith("data:image/"):
        return True
    return _local_image_source_from_media(value) is not None


def _normalize_global_media_asset(asset_type: str, media: Any) -> dict[str, Any] | None:
    from .projects import _global_relative_path
    from .agent_sessions import _media_ref_for_storage
    if not isinstance(media, dict):
        return None
    result = copy.deepcopy(media)
    result["kind"] = result.get("kind") or "image"
    existing_file = _global_file_from_ref(result)
    if existing_file and existing_file.is_file() and existing_file.suffix.lower() in IMAGE_EXTENSIONS:
        relative_path = _global_relative_path(existing_file)
        result.update(
            {
                "path": str(existing_file),
                "filePath": str(existing_file),
                "relativePath": relative_path,
                "relative_path": relative_path,
                "file": relative_path,
                "pngFile": relative_path,
                "mimeType": str(result.get("mimeType") or _mime_from_image_suffix(existing_file)),
                "kind": "image",
            }
        )
        return _media_ref_for_storage(result)

    data_url = _source_image_data_url(result)
    raw: bytes | None = None
    mime = str(result.get("mimeType") or result.get("mime_type") or "image/png")
    if data_url.startswith("data:image/"):
        raw, mime = _decode_data_url(data_url)
    else:
        local_source = _local_image_source_from_media(result)
        if local_source:
            path, mime = local_source
            media_id = str(result.get("id") or f"asset-{asset_type}-{uuid.uuid4().hex[:10]}")
            return _copy_local_global_asset_image_media_file(
                asset_type,
                path,
                media_id=media_id,
                original_name=str(result.get("originalName") or result.get("name") or path.name),
                source_mime=mime,
            )

    if raw is None:
        # A global asset must own a file inside GLOBAL_ASSET_MEDIA_DIR.  Do not
        # persist a missing or external absolute path that the global deleter
        # cannot safely remove later.
        raise ValueError("全局资产图片无可用本地文件或图片数据")

    media_id = str(result.get("id") or f"asset-{asset_type}-{uuid.uuid4().hex[:10]}")
    return _save_global_asset_image_media_file(
        asset_type,
        raw,
        media_id=media_id,
        original_name=str(result.get("originalName") or result.get("name") or ""),
        source_mime=mime,
    )


def _global_asset_media_path(media: Any) -> Path | None:
    from .projects import _is_path_within
    if not isinstance(media, dict):
        return None
    path = _global_file_from_ref(media)
    if not path or not _is_path_within(path, GLOBAL_ASSET_MEDIA_DIR):
        return None
    return path


def _delete_global_asset_media_file(media: Any) -> None:
    path = _global_asset_media_path(media)
    if path and path.exists():
        path.unlink()


def _image_media_from_file_info(
    project_id: str | None,
    file_info: dict[str, Any],
    *,
    media_id: str | None = None,
    subdir: str = "media",
    storage_scope: str = "assets",
    episode_id: str | None = None,
) -> dict[str, Any]:
    from .agent_sessions import _media_ref_for_storage
    data_url = _storage_png_data_url(file_info)
    local_source = _local_image_source_from_media(file_info)
    if not data_url and not local_source:
        raise ValueError("请上传图片")
    safe_id = _safe_file_stem(media_id or file_info.get("id"), f"media-{uuid.uuid4().hex[:10]}")
    original_name = str(file_info.get("name") or file_info.get("originalName") or "")
    if not data_url and local_source and project_id:
        source_path, source_mime = local_source
        if not str(source_mime).startswith("image/"):
            raise ValueError("只支持图片文件")
        stored = _copy_local_project_image_media_file(
            project_id,
            source_path,
            media_id=safe_id,
            subdir=subdir,
            original_name=original_name or source_path.name,
            source_mime=source_mime,
            storage_scope=storage_scope,
            episode_id=episode_id,
        )
        return _media_ref_for_storage(stored)
    if data_url:
        raw, mime = _decode_data_url(data_url)
    else:
        source_path, source_mime = local_source
        raw, mime = source_path.read_bytes(), source_mime
    if not str(mime).startswith("image/"):
        raise ValueError("只支持图片文件")
    normalized = _normalized_image_payload(raw, mime, include_data_url=not bool(project_id))
    result = {
        "id": safe_id,
        "kind": "image",
        "originalName": original_name,
        "mimeType": "image/png",
    }
    if normalized.get("pngDataUrl"):
        result["pngDataUrl"] = normalized["pngDataUrl"]
        result["outputPngDataUrl"] = normalized["pngDataUrl"]
        result["preview"] = normalized["pngDataUrl"]
    if normalized.get("conversionWarning"):
        result["conversionWarning"] = normalized["conversionWarning"]
    if project_id:
        stored = _save_project_image_media_file(
            project_id,
            raw,
            media_id=result["id"],
            subdir=subdir,
            original_name=str(result.get("originalName") or ""),
            source_mime=mime,
            storage_scope=storage_scope,
            episode_id=episode_id,
        )
        result.update(stored)
        result = _media_ref_for_storage(result)
    return result


def _download_image_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "image/*,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        message = detail or str(exc.reason or exc)
        raise RuntimeError(f"图片 URL 下载失败 HTTP {exc.code}: {message[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"图片 URL 下载失败: {exc.reason or exc}") from exc


def _decode_image_response_value(value: Any) -> bytes | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.startswith("data:image/"):
        raw, _mime = _decode_data_url(text)
        return raw
    if re.match(r"^https?://", text, re.IGNORECASE):
        return _download_image_url(text)
    try:
        return base64.b64decode(text, validate=True)
    except Exception:
        return None


def _extract_first_image_bytes(data: Any) -> bytes | None:
    if not isinstance(data, dict):
        return None
    candidates: list[Any] = []
    for key in ("b64_json", "b64", "base64", "image_base64", "url", "image_url"):
        value = data.get(key)
        if value is not None:
            candidates.append(value)
    for key in ("data", "output", "images"):
        value = data.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        elif value is not None:
            candidates.append(value)
    if isinstance(data.get("image"), dict):
        candidates.append(data.get("image"))
    for item in candidates:
        raw = _decode_image_response_value(item)
        if raw:
            return raw
        if not isinstance(item, dict):
            continue
        for key in ("b64_json", "b64", "base64", "image_base64", "data", "url", "image_url"):
            value = item.get(key)
            raw = _decode_image_response_value(value)
            if raw:
                return raw
    return None


def _extract_first_media_url(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("url", "video_url", "videoUrl", "download_url", "downloadUrl"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("data", "output", "videos"):
        value = data.get(key)
        rows = value if isinstance(value, list) else [value]
        for item in rows:
            if isinstance(item, dict):
                url = _extract_first_media_url(item)
                if url:
                    return url
    return ""


def _extract_video_job_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("id", "task_id", "taskId", "video_id", "videoId", "job_id", "jobId"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _save_favorite_style_thumbnail(template_id: str, file_info: dict[str, Any]) -> dict[str, Any]:
    from .projects import _favorite_style_thumbnail_fields
    if not isinstance(file_info, dict) or not _has_image_file_input(file_info):
        raise ValueError("请上传风格图片")
    data_url = _storage_png_data_url(file_info)
    local_source = _local_image_source_from_media(file_info)
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", template_id)
    if not data_url and local_source:
        source_path, source_mime = local_source
        if not source_mime.startswith("image/"):
            raise ValueError("风格图片只支持 png、jpg 或 webp")
        suffix = _image_suffix_from_mime_or_name(source_mime, source_path.name)
        file_name = f"{safe_id}{suffix}"
        path = FAVORITE_STYLE_THUMBNAILS_DIR / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.resolve() != path.resolve():
            shutil.copy2(source_path, path)
        return _favorite_style_thumbnail_fields(file_name, path)
    if data_url:
        raw, mime = _decode_data_url(data_url)
    else:
        raise ValueError("请上传风格图片")
    if not mime.startswith("image/"):
        raise ValueError("风格图片只支持 png、jpg 或 webp")
    file_name = f"{safe_id}.png"
    path = FAVORITE_STYLE_THUMBNAILS_DIR / file_name
    path.parent.mkdir(parents=True, exist_ok=True)
    save_project_image(raw, path)
    return _favorite_style_thumbnail_fields(file_name, path)

__all__ = (
    '_decode_data_url', '_data_url', '_source_media_data_url', '_source_image_data_url',
    '_storage_png_data_url', '_normalized_image_payload', '_file_extension', '_safe_file_stem',
    '_project_media_relative_path', '_project_media_storage_dir', '_save_project_media_file',
    '_save_project_image_media_file', '_copy_local_project_image_media_file',
    '_video_media_from_file_info', '_copy_local_project_video_media_file',
    '_save_project_config_image_file',
    '_copy_local_project_config_image_file', '_global_file_from_ref', '_save_global_asset_image_media_file',
    '_copy_local_global_asset_image_media_file', '_local_image_source_from_media', '_has_image_file_input',
    '_normalize_global_media_asset', '_global_asset_media_path', '_delete_global_asset_media_file',
    '_image_media_from_file_info', '_download_image_url', '_decode_image_response_value',
    '_extract_first_image_bytes', '_extract_first_media_url', '_extract_video_job_id',
    '_save_favorite_style_thumbnail'
)


def _stored_media_path(project_id: str, media: dict[str, Any]) -> Path | None:
    path_text = str(
        media.get("path")
        or media.get("filePath")
        or media.get("file_path")
        or media.get("relativePath")
        or media.get("relative_path")
        or media.get("file")
        or ""
    ).strip()
    if not path_text:
        return None
    path = Path(path_text)
    if path.is_absolute():
        return path
    return _project_dir(project_id) / path_text

# Preserve the implementation that was previously effective through package exports.
from .agent_sessions import _image_suffix_from_mime_or_name
from .agent_sessions import _mime_from_image_suffix
