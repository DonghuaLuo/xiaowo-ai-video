# -*- coding: utf-8 -*-
"""Video clipping and frame extraction helpers for canvas media."""

from __future__ import annotations

import hashlib
import base64
import json
import os
import shutil
import subprocess
import threading
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from utils.image_pipeline import image_file_metadata

from .agent_sessions import _media_ref_for_storage
from .media_files import (
    _image_media_from_file_info,
    _mime_from_video_suffix,
    _project_media_relative_path,
    _project_media_storage_dir,
    _safe_file_stem,
)
from .projects import _is_path_within

from .catalogs import PROJECTS_DIR
from .catalogs import VIDEO_EXTENSIONS
from .store_core import _now

_FRAME_PREVIEW_CACHE_MAX = 180
_FRAME_PREVIEW_CACHE: OrderedDict[str, str] = OrderedDict()
_FRAME_PREVIEW_CACHE_LOCK = threading.Lock()
_VIDEO_PROBE_CACHE_MAX = 96
_VIDEO_PROBE_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_VIDEO_PROBE_CACHE_LOCK = threading.Lock()
_VIDEO_CAPTURE_CACHE_MAX = 4
_VIDEO_CAPTURE_CACHE: OrderedDict[str, Any] = OrderedDict()
_VIDEO_CAPTURE_CACHE_LOCK = threading.Lock()
_CLIP_MANIFEST_LOCKS: dict[str, threading.Lock] = {}
_CLIP_MANIFEST_LOCKS_LOCK = threading.Lock()
_VIDEO_THUMBNAIL_LOCKS: dict[str, threading.Lock] = {}
_VIDEO_THUMBNAIL_LOCKS_LOCK = threading.Lock()
_VIDEO_CONTENT_HASH_CACHE: dict[str, tuple[int, int, str]] = {}
_VIDEO_CONTENT_HASH_CACHE_LOCK = threading.Lock()
VIDEO_THUMBNAIL_CACHE_VERSION = "v1"
VIDEO_THUMBNAIL_MAX_WIDTH = 480


class _OpenCvFrameReader:
    def __init__(self, path: Path) -> None:
        import cv2  # type: ignore

        self.cv2 = cv2
        self.lock = threading.Lock()
        self.capture = cv2.VideoCapture(str(path))
        if not self.capture.isOpened():
            self.capture.release()
            raise RuntimeError("无法打开视频")

    def close(self) -> None:
        try:
            self.capture.release()
        except Exception:
            pass

    def read(self, frame_index: int):
        with self.lock:
            self.capture.set(self.cv2.CAP_PROP_POS_FRAMES, max(0, int(frame_index)))
            ok, frame = self.capture.read()
        if not ok or frame is None:
            return None
        return frame


def _media_tool_executable(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    plugin_dir = Path(os.environ.get("PLUGIN_DIR") or "").resolve()
    candidates: list[Path] = []
    if plugin_dir:
        candidates.append(plugin_dir.parent.parent / "extlibs" / "ffmpeg" / f"{name}.exe")
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "extlibs" / "ffmpeg" / f"{name}.exe")
    for path in candidates:
        if path.is_file():
            return str(path)
    raise RuntimeError(f"未找到 {name}，无法处理视频")


def _run_media_command(args: list[str], *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _run_media_bytes(args: list[str], *, timeout: float = 20) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _payload_media(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("media", "file", "sourceMedia", "source_media"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def _payload_timestamp(payload: dict[str, Any]) -> float:
    raw = payload.get("time") if "time" in payload else payload.get("timestamp")
    try:
        return float(raw or 0)
    except Exception:
        return 0.0


def _float_payload(payload: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key not in payload:
            continue
        try:
            return float(payload.get(key) or 0)
        except Exception:
            return default
    return default


def _float_from_payload_or_record(
    payload: dict[str, Any],
    record: dict[str, Any],
    *keys: str,
    default: float = 0.0,
) -> float:
    for key in keys:
        value = payload.get(key)
        if value is None:
            value = record.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            return default
    return default


def _frame_timestamp(payload: dict[str, Any], duration: float) -> float:
    safe_duration = max(0.0, float(duration or 0))
    if safe_duration <= 0:
        return 0.0
    upper = max(0.0, safe_duration - 0.05)
    return max(0.0, min(_payload_timestamp(payload), upper))


def _payload_frame_index(payload: dict[str, Any]) -> int | None:
    for key in ("frameIndex", "frame_index", "frame", "frameNo", "frame_no"):
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        try:
            return max(0, int(float(value)))
        except Exception:
            return None
    return None


def _payload_tail_frame(payload: dict[str, Any]) -> bool:
    return bool(
        payload.get("tailFrame")
        or payload.get("tail_frame")
        or payload.get("lastFrame")
        or payload.get("last_frame")
    )


def _video_frame_count(info: dict[str, Any]) -> int:
    try:
        return max(0, int(float(info.get("frameCount") or info.get("frame_count") or 0)))
    except Exception:
        return 0


def _last_frame_index(info: dict[str, Any]) -> int:
    frame_count = _video_frame_count(info)
    if frame_count > 0:
        return frame_count - 1
    try:
        explicit = int(float(info.get("lastFrameIndex") or info.get("last_frame_index") or -1))
        if explicit >= 0:
            return explicit
    except Exception:
        pass
    duration = max(0.0, float(info.get("videoDuration") or info.get("duration") or 0))
    fps = max(0.0, float(info.get("fps") or 0))
    if duration > 0 and fps > 0:
        return max(0, int(round(duration * fps)) - 1)
    return 0


def _normalize_video_frame_info(info: dict[str, Any]) -> dict[str, Any]:
    frame_count = _video_frame_count(info)
    if frame_count > 0:
        info["frameCount"] = frame_count
        info["lastFrameIndex"] = frame_count - 1
    else:
        info["lastFrameIndex"] = _last_frame_index(info)
    return info


def _clamp_frame_index(frame_index: int | float, info: dict[str, Any]) -> int:
    last_index = _last_frame_index(info)
    return max(0, min(int(frame_index), last_index))


def _frame_index_from_timestamp(timestamp: float, info: dict[str, Any]) -> int:
    fps = max(0.0, float(info.get("fps") or 0))
    if fps > 0:
        return _clamp_frame_index(round(max(0.0, timestamp) * fps), info)
    duration = max(0.0, float(info.get("duration") or 0))
    last_index = _last_frame_index(info)
    if duration > 0 and last_index > 0:
        return _clamp_frame_index(round((max(0.0, timestamp) / duration) * last_index), info)
    return 0


def _frame_timestamp_from_index(frame_index: int, info: dict[str, Any]) -> float:
    fps = max(0.0, float(info.get("fps") or 0))
    if fps > 0:
        return max(0.0, frame_index / fps)
    duration = max(0.0, float(info.get("duration") or 0))
    last_index = _last_frame_index(info)
    if duration > 0 and last_index > 0:
        return max(0.0, (frame_index / last_index) * duration)
    return 0.0


def _frame_index_from_payload(payload: dict[str, Any], info: dict[str, Any]) -> int | None:
    explicit = _payload_frame_index(payload)
    if explicit is not None:
        return _clamp_frame_index(explicit, info)
    if _payload_tail_frame(payload):
        return _last_frame_index(info)
    return None


def _tail_frame_timestamp(info: dict[str, Any]) -> float:
    duration = max(0.0, float(info.get("videoDuration") or info.get("duration") or 0))
    if duration <= 0:
        return 0.0
    fps = float(info.get("fps") or 0)
    offset = (1.0 / fps) if fps > 0 else 0.1
    return max(0.0, duration - offset)


def _even_floor(value: float, *, minimum: int = 0) -> int:
    number = max(minimum, int(round(value)))
    if number % 2:
        number -= 1
    return max(minimum, number)


def _payload_crop_rect(payload: dict[str, Any], info: dict[str, Any]) -> dict[str, int] | None:
    crop_payload = payload.get("crop") if isinstance(payload.get("crop"), dict) else {}
    has_crop = bool(crop_payload) or any(
        key in payload
        for key in (
            "cropX",
            "cropY",
            "cropWidth",
            "cropHeight",
            "crop_x",
            "crop_y",
            "crop_width",
            "crop_height",
        )
    )
    if not has_crop:
        return None
    source_width = int(float(info.get("width") or 0))
    source_height = int(float(info.get("height") or 0))
    if source_width <= 1 or source_height <= 1:
        return None

    x = _float_from_payload_or_record(payload, crop_payload, "cropX", "crop_x", "x")
    y = _float_from_payload_or_record(payload, crop_payload, "cropY", "crop_y", "y")
    width = _float_from_payload_or_record(
        payload,
        crop_payload,
        "cropWidth",
        "crop_width",
        "width",
        default=float(source_width),
    )
    height = _float_from_payload_or_record(
        payload,
        crop_payload,
        "cropHeight",
        "crop_height",
        "height",
        default=float(source_height),
    )

    x = _even_floor(max(0.0, min(x, source_width - 2)))
    y = _even_floor(max(0.0, min(y, source_height - 2)))
    width = _even_floor(max(2.0, min(width, source_width - x)), minimum=2)
    height = _even_floor(max(2.0, min(height, source_height - y)), minimum=2)
    if x + width > source_width:
        width = _even_floor(source_width - x, minimum=2)
    if y + height > source_height:
        height = _even_floor(source_height - y, minimum=2)
    if width <= 1 or height <= 1:
        raise ValueError("裁剪区域太小")
    if x <= 0 and y <= 0 and width >= source_width - 1 and height >= source_height - 1:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _fps_from_rate(value: str) -> float:
    text = str(value or "").strip()
    if not text or text == "0/0":
        return 0.0
    if "/" in text:
        left, right = text.split("/", 1)
        try:
            denominator = float(right)
            return float(left) / denominator if denominator else 0.0
        except Exception:
            return 0.0
    try:
        return float(text)
    except Exception:
        return 0.0


def _source_clip_key(project_id: str, path: Path) -> str:
    try:
        source = _project_media_relative_path(project_id, path)
    except Exception:
        source = str(path)
    stat = path.stat()
    digest = hashlib.sha1(
        f"{source}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
    ).hexdigest()[:18]
    return f"source-{digest}"


def _source_clip_root(project_id: str, episode_id: str, path: Path) -> Path:
    return _project_media_storage_dir(
        project_id,
        f"video_clip_results/{_source_clip_key(project_id, path)}",
        storage_scope="episode_results",
        episode_id=episode_id,
    )


def _source_clip_manifest_path(project_id: str, episode_id: str, path: Path) -> Path:
    return _source_clip_root(project_id, episode_id, path) / "manifest.json"


def _clip_manifest_lock(project_id: str, episode_id: str, path: Path) -> threading.Lock:
    lock_key = f"{project_id}\0{episode_id}\0{_source_clip_key(project_id, path)}"
    with _CLIP_MANIFEST_LOCKS_LOCK:
        lock = _CLIP_MANIFEST_LOCKS.get(lock_key)
        if lock is None:
            lock = threading.Lock()
            _CLIP_MANIFEST_LOCKS[lock_key] = lock
        return lock


def _clip_source_payload(project_id: str, path: Path, info: dict[str, Any]) -> dict[str, Any]:
    stat = path.stat()
    try:
        relative_path = _project_media_relative_path(project_id, path)
    except Exception:
        relative_path = ""
    return {
        "key": _source_clip_key(project_id, path),
        "path": str(path),
        "relativePath": relative_path,
        "name": str(info.get("name") or path.name),
        "duration": info.get("duration"),
        "width": info.get("width"),
        "height": info.get("height"),
        "fps": info.get("fps"),
        "mimeType": info.get("mimeType"),
        "size": stat.st_size,
        "mtimeNs": stat.st_mtime_ns,
    }


def _read_clip_manifest(project_id: str, episode_id: str, path: Path, info: dict[str, Any]) -> dict[str, Any]:
    manifest_path = _source_clip_manifest_path(project_id, episode_id, path)
    data: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    results = data.get("results")
    if not isinstance(results, list):
        results = []
    return {
        "schemaVersion": 1,
        "source": _clip_source_payload(project_id, path, info),
        "results": [item for item in results if isinstance(item, dict)],
        "updatedAt": str(data.get("updatedAt") or ""),
    }


def _write_clip_manifest(
    project_id: str,
    episode_id: str,
    path: Path,
    info: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    manifest_path = _source_clip_manifest_path(project_id, episode_id, path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schemaVersion": 1,
        "source": _clip_source_payload(project_id, path, info),
        "results": manifest.get("results") if isinstance(manifest.get("results"), list) else [],
        "updatedAt": _now(),
    }
    temp_path = manifest_path.with_name(f"{manifest_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, manifest_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _frame_origin_path(origin: dict[str, Any]) -> Path:
    result_id = str(origin.get("resultId") or "")
    if not result_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in result_id):
        raise ValueError("帧画面来源标识无效")
    root = _project_media_storage_dir(
        str(origin.get("projectId") or ""), "frame_origins",
        storage_scope="episode_results", episode_id=str(origin.get("episodeId") or ""),
    )
    return root / f"{result_id}.json"


def validated_frame_origin(media: dict[str, Any]) -> dict[str, Any]:
    """Capture provenance survives deleting the clip result or source video."""
    origin = media.get("frameOrigin")
    if not isinstance(origin, dict):
        raise ValueError("帧画面只能来自视频剪辑截图")
    path = _frame_origin_path(origin)
    if not path.is_file():
        raise ValueError("未找到帧画面的截图来源，请重新截图")
    return json.loads(path.read_text(encoding="utf-8"))


def _clip_result_record(
    *,
    result_id: str,
    kind: str,
    title: str,
    media: dict[str, Any],
    source_key: str,
    start: float | None = None,
    end: float | None = None,
    duration: float | None = None,
    time: float | None = None,
    frame_index: int | None = None,
    crop: dict[str, int] | None = None,
) -> dict[str, Any]:
    now = _now()
    return {
        "id": result_id,
        "kind": kind,
        "title": title,
        "media": media,
        "sourceKey": source_key,
        **({"start": start} if start is not None else {}),
        **({"end": end} if end is not None else {}),
        **({"duration": duration} if duration is not None else {}),
        **({"time": time} if time is not None else {}),
        **({"frameIndex": frame_index} if frame_index is not None else {}),
        **({"crop": crop} if crop else {}),
        "createdAt": now,
        "updatedAt": now,
    }


def _persist_clip_result(
    project_id: str,
    episode_id: str,
    path: Path,
    info: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    with _clip_manifest_lock(project_id, episode_id, path):
        manifest = _read_clip_manifest(project_id, episode_id, path, info)
        result_id = str(record.get("id") or "").strip()
        previous = [
            item
            for item in manifest.get("results", [])
            if not isinstance(item, dict) or str(item.get("id") or "").strip() != result_id
        ]
        manifest["results"] = [record, *previous]
        _write_clip_manifest(project_id, episode_id, path, info, manifest)
    return record


def _clip_result_ids_from_payload(payload: dict[str, Any]) -> set[str]:
    raw_ids = payload.get("resultIds")
    if raw_ids is None:
        raw_ids = payload.get("result_ids")
    if raw_ids is None:
        raw_ids = payload.get("ids")
    if raw_ids is None:
        raw_id = payload.get("resultId")
        if raw_id is None:
            raw_id = payload.get("result_id")
        raw_ids = [raw_id] if raw_id is not None else []
    if isinstance(raw_ids, (str, int, float)):
        raw_ids = [raw_ids]
    if not isinstance(raw_ids, list):
        return set()
    result_ids: set[str] = set()
    for item in raw_ids:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            result_ids.add(text)
    return result_ids


def _delete_clip_result_file(project_id: str, root: Path, record: dict[str, Any]) -> bool:
    media = record.get("media")
    if not isinstance(media, dict):
        return False
    try:
        path = _resolve_project_media_path(project_id, media).resolve()
    except Exception:
        return False
    root = root.resolve()
    if not _is_path_within(path, root):
        return False
    try:
        _close_video_capture_cache(path)
        path.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _clip_results_payload(project_id: str, episode_id: str, path: Path, info: dict[str, Any]) -> dict[str, Any]:
    manifest = _read_clip_manifest(project_id, episode_id, path, info)
    results = [
        item
        for item in manifest.get("results", [])
        if isinstance(item, dict) and isinstance(item.get("media"), dict)
    ]
    results.sort(key=lambda item: str(item.get("createdAt") or item.get("updatedAt") or ""), reverse=True)
    return {
        "success": True,
        "projectId": project_id,
        "episodeId": episode_id,
        "source": manifest.get("source"),
        "sourceKey": (manifest.get("source") or {}).get("key") if isinstance(manifest.get("source"), dict) else "",
        "results": results,
    }


def _resolve_project_media_path(project_id: str, media: dict[str, Any]) -> Path:
    from .agent_sessions import _project_dir
    project_root = _project_dir(project_id).resolve()
    for key in ("path", "filePath", "file_path"):
        raw = str(media.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).resolve()
        if path.is_file():
            return path
    for key in ("relativePath", "relative_path", "file"):
        raw = str(media.get(key) or "").strip()
        if not raw:
            continue
        path = (project_root / raw.replace("\\", "/")).resolve()
        if _is_path_within(path, project_root) and path.is_file():
            return path
    raise FileNotFoundError("未找到可用的视频文件")


def _assert_video_path(path: Path) -> None:
    if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError("请选择 MP4、WebM、MOV、MKV、AVI 或 M4V 视频文件")


def _video_probe_cache_key(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha1(
        f"{path}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
    ).hexdigest()


def _video_probe_cache_get(key: str) -> dict[str, Any] | None:
    with _VIDEO_PROBE_CACHE_LOCK:
        value = _VIDEO_PROBE_CACHE.get(key)
        if not value:
            return None
        _VIDEO_PROBE_CACHE.move_to_end(key)
        return dict(value)


def _video_probe_cache_set(key: str, value: dict[str, Any]) -> None:
    with _VIDEO_PROBE_CACHE_LOCK:
        _VIDEO_PROBE_CACHE[key] = dict(value)
        _VIDEO_PROBE_CACHE.move_to_end(key)
        while len(_VIDEO_PROBE_CACHE) > _VIDEO_PROBE_CACHE_MAX:
            _VIDEO_PROBE_CACHE.popitem(last=False)


def _probe_video(project_id: str, media: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    path = _resolve_project_media_path(project_id, media)
    _assert_video_path(path)
    cache_key = _video_probe_cache_key(path)
    info = _video_probe_cache_get(cache_key)
    if info is None:
        ffprobe = _media_tool_executable("ffprobe")
        result = _run_media_command(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,codec_name,width,height,duration,avg_frame_rate,r_frame_rate,nb_frames:format=duration",
                "-of",
                "json",
                str(path),
            ],
            timeout=15,
        )
        info = {}
        if result.returncode == 0:
            try:
                probe = json.loads(result.stdout)
            except (ValueError, TypeError):
                probe = {}
            streams = probe.get("streams", []) if isinstance(probe, dict) else []
            video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
            info["videoCodec"] = str(video.get("codec_name") or "")
            info["audioCodecs"] = [str(stream.get("codec_name") or "") for stream in streams if stream.get("codec_type") == "audio"]
            container = probe.get("format") if isinstance(probe, dict) and isinstance(probe.get("format"), dict) else {}
            for name, raw in (("videoDuration", video.get("duration")),
                              ("containerDuration", container.get("duration"))):
                try:
                    measured = float(raw)
                    if measured > 0:
                        info[name] = measured
                except (TypeError, ValueError):
                    pass
            audio_durations = []
            for stream in streams:
                if stream.get("codec_type") == "audio":
                    try:
                        audio_durations.append(float(stream.get("duration")))
                    except (TypeError, ValueError):
                        pass
            if audio_durations:
                info["audioDuration"] = max(audio_durations)
            fields = [*video.items(), *(probe.get("format", {}).items() if isinstance(probe, dict) else [])]
            for key, value in fields:
                if key in {"width", "height"}:
                    try:
                        info[key] = int(float(value))
                    except Exception:
                        pass
                elif key in {"avg_frame_rate", "r_frame_rate"}:
                    fps = _fps_from_rate(value)
                    if fps > 0:
                        info["fps"] = max(float(info.get("fps") or 0), fps)
                elif key == "duration":
                    try:
                        duration = float(value)
                        if duration > 0:
                            info["duration"] = max(float(info.get("duration") or 0), duration)
                    except Exception:
                        pass
                elif key == "nb_frames":
                    try:
                        frame_count = int(float(value))
                        if frame_count > 0:
                            info["frameCount"] = frame_count
                    except Exception:
                        pass
        if (
            not info.get("duration")
            or not info.get("frameCount")
            or not info.get("fps")
            or not info.get("width")
            or not info.get("height")
        ):
            try:
                import cv2  # type: ignore

                capture = cv2.VideoCapture(str(path))
                frames = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
                width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                capture.release()
                if fps > 0 and frames > 0:
                    info.setdefault("duration", frames / fps)
                    info.setdefault("videoDuration", frames / fps)
                    info.setdefault("fps", fps)
                if frames > 0:
                    info.setdefault("frameCount", int(frames))
                if width > 0:
                    info.setdefault("width", width)
                if height > 0:
                    info.setdefault("height", height)
            except Exception:
                pass
        if not info.get("duration"):
            raise RuntimeError("无法读取视频时长")
        if not info.get("videoDuration") and info.get("frameCount") and info.get("fps"):
            info["videoDuration"] = info["frameCount"] / info["fps"]
        _normalize_video_frame_info(info)
        _video_probe_cache_set(cache_key, info)
    else:
        _normalize_video_frame_info(info)
    info["path"] = str(path)
    info["name"] = str(media.get("originalName") or media.get("name") or path.name)
    info["mimeType"] = str(media.get("mimeType") or _mime_from_video_suffix(path))
    return path, info


def _preview_cache_get(key: str) -> str | None:
    with _FRAME_PREVIEW_CACHE_LOCK:
        value = _FRAME_PREVIEW_CACHE.get(key)
        if value:
            _FRAME_PREVIEW_CACHE.move_to_end(key)
        return value


def _preview_cache_set(key: str, value: str) -> None:
    with _FRAME_PREVIEW_CACHE_LOCK:
        _FRAME_PREVIEW_CACHE[key] = value
        _FRAME_PREVIEW_CACHE.move_to_end(key)
        while len(_FRAME_PREVIEW_CACHE) > _FRAME_PREVIEW_CACHE_MAX:
            _FRAME_PREVIEW_CACHE.popitem(last=False)


def _frame_preview_cache_key(path: Path, timestamp: float, info: dict[str, Any]) -> tuple[str, float]:
    fps = float(info.get("fps") or 0)
    snapped = round(timestamp, 3)
    if fps > 0:
        snapped = max(0.0, round(round(timestamp * fps) / fps, 3))
    stat = path.stat()
    return (
        hashlib.sha1(
            f"{path}:{stat.st_size}:{stat.st_mtime_ns}:{snapped:.3f}".encode("utf-8")
        ).hexdigest(),
        snapped,
    )


def _frame_preview_index_cache_key(path: Path, frame_index: int) -> str:
    stat = path.stat()
    return hashlib.sha1(
        f"{path}:{stat.st_size}:{stat.st_mtime_ns}:frame:{frame_index}".encode("utf-8")
    ).hexdigest()


def _opencv_frame_reader(path: Path) -> _OpenCvFrameReader:
    cache_key = _video_probe_cache_key(path)
    with _VIDEO_CAPTURE_CACHE_LOCK:
        cached = _VIDEO_CAPTURE_CACHE.get(cache_key)
        if cached:
            _VIDEO_CAPTURE_CACHE.move_to_end(cache_key)
            return cached
    reader = _OpenCvFrameReader(path)
    with _VIDEO_CAPTURE_CACHE_LOCK:
        cached = _VIDEO_CAPTURE_CACHE.get(cache_key)
        if cached:
            reader.close()
            _VIDEO_CAPTURE_CACHE.move_to_end(cache_key)
            return cached
        _VIDEO_CAPTURE_CACHE[cache_key] = reader
        _VIDEO_CAPTURE_CACHE.move_to_end(cache_key)
        while len(_VIDEO_CAPTURE_CACHE) > _VIDEO_CAPTURE_CACHE_MAX:
            _, evicted = _VIDEO_CAPTURE_CACHE.popitem(last=False)
            try:
                evicted.close()
            except Exception:
                pass
    return reader


def _close_video_capture_cache(path: Path) -> None:
    try:
        cache_key = _video_probe_cache_key(path)
    except Exception:
        return
    with _VIDEO_CAPTURE_CACHE_LOCK:
        cached = _VIDEO_CAPTURE_CACHE.pop(cache_key, None)
    if cached:
        try:
            cached.close()
        except Exception:
            pass


def _video_content_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _video_thumbnail_lock(cache_key: str) -> threading.Lock:
    with _VIDEO_THUMBNAIL_LOCKS_LOCK:
        return _VIDEO_THUMBNAIL_LOCKS.setdefault(cache_key, threading.Lock())


def _video_owner_project_id(project_id: str, path: Path, media: dict[str, Any]) -> str:
    declared = str(media.get("projectId") or media.get("project_id") or "").strip()
    if declared:
        return declared
    try:
        relative = path.resolve().relative_to(PROJECTS_DIR.resolve())
        if relative.parts:
            return str(relative.parts[0])
    except ValueError:
        pass
    return project_id


def ensure_video_thumbnail(
    project_id: str,
    media: dict[str, Any],
    *,
    max_width: int = VIDEO_THUMBNAIL_MAX_WIDTH,
) -> dict[str, Any]:
    """Return a persistent, cross-project thumbnail without creating a frame asset."""
    path, info = _probe_video(project_id, media)
    owner_project_id = _video_owner_project_id(project_id, path, media)
    content_hash = str(media.get("contentHash") or media.get("content_hash") or "").strip().lower()
    if not content_hash or len(content_hash) != 64 or any(char not in "0123456789abcdef" for char in content_hash):
        stat = path.stat()
        cache_key = str(path.resolve())
        with _VIDEO_CONTENT_HASH_CACHE_LOCK:
            cached = _VIDEO_CONTENT_HASH_CACHE.get(cache_key)
        if cached and cached[:2] == (stat.st_size, stat.st_mtime_ns):
            content_hash = cached[2]
        else:
            content_hash = _video_content_sha256(path)
            with _VIDEO_CONTENT_HASH_CACHE_LOCK:
                _VIDEO_CONTENT_HASH_CACHE[cache_key] = (stat.st_size, stat.st_mtime_ns, content_hash)
                if len(_VIDEO_CONTENT_HASH_CACHE) > 256:
                    _VIDEO_CONTENT_HASH_CACHE.pop(next(iter(_VIDEO_CONTENT_HASH_CACHE)))
    cache_key = f"{VIDEO_THUMBNAIL_CACHE_VERSION}:{content_hash}:{max_width}"
    filename = f"video-thumb-{VIDEO_THUMBNAIL_CACHE_VERSION}-{content_hash[:32]}-{max_width}.jpg"
    # Keep the cache under the owning project so project deletion also removes
    # its derived thumbnails. All canvases in that project share this path.
    cache_dir = _project_media_storage_dir(owner_project_id, "video_thumbnails", storage_scope="assets")
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_path = cache_dir / filename
    lock = _video_thumbnail_lock(cache_key)
    with lock:
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            timestamp = min(0.1, max(0.0, float(info.get("duration") or 0.0)))
            data_url = _opencv_frame_preview_data_url(path, timestamp, max_width=max_width)
            if not data_url:
                data_url = _ffmpeg_frame_preview_data_url(path, timestamp, max_width=max_width)
            if not data_url or "," not in data_url:
                raise RuntimeError("视频缩略图抽取失败")
            raw = base64.b64decode(data_url.split(",", 1)[1])
            temp_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temp_path.write_bytes(raw)
                temp_path.replace(output_path)
            finally:
                temp_path.unlink(missing_ok=True)
    relative_path = _project_media_relative_path(owner_project_id, output_path) or ""
    return {
        "thumbnailPath": str(output_path),
        "thumbnailFile": relative_path,
        "thumbnailRelativePath": relative_path,
    }


def _opencv_read_frame_at_index(path: Path, frame_index: int):
    try:
        return _opencv_frame_reader(path).read(frame_index)
    except Exception:
        return None


def _opencv_encode_frame_data_url(frame, *, max_width: int = 960) -> str | None:
    try:
        import cv2  # type: ignore

        if max_width > 0 and frame.shape[1] > max_width:
            ratio = max_width / float(frame.shape[1])
            frame = cv2.resize(
                frame,
                (max_width, max(1, int(frame.shape[0] * ratio))),
                interpolation=cv2.INTER_AREA,
            )
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        if not ok:
            return None
        data = base64.b64encode(encoded.tobytes()).decode("ascii")
        return f"data:image/jpeg;base64,{data}"
    except Exception:
        return None


def _opencv_frame_preview_data_url_by_index(path: Path, frame_index: int, *, max_width: int = 960) -> str | None:
    frame = _opencv_read_frame_at_index(path, frame_index)
    if frame is None:
        return None
    return _opencv_encode_frame_data_url(frame, max_width=max_width)


def _opencv_frame_preview_data_url(path: Path, timestamp: float, *, max_width: int = 960) -> str | None:
    try:
        import cv2  # type: ignore

        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            capture.release()
            return None
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        if fps > 0:
            capture.release()
            return _opencv_frame_preview_data_url_by_index(path, max(0, int(round(timestamp * fps))), max_width=max_width)
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp) * 1000)
        ok, frame = capture.read()
        capture.release()
        if not ok or frame is None:
            return None
        return _opencv_encode_frame_data_url(frame, max_width=max_width)
    except Exception:
        return None


def _ffmpeg_frame_preview_data_url(path: Path, timestamp: float, *, max_width: int = 960) -> str:
    ffmpeg = _media_tool_executable("ffmpeg")
    result = _run_media_bytes(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={max_width}:-2:force_original_aspect_ratio=decrease",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ],
        timeout=8,
    )
    if result.returncode != 0 or not result.stdout:
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        raise RuntimeError((stderr or "截取视频帧失败").strip()[:500])
    encoded = base64.b64encode(result.stdout).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _ffmpeg_frame_preview_data_url_by_index(path: Path, frame_index: int, *, max_width: int = 960) -> str:
    ffmpeg = _media_tool_executable("ffmpeg")
    result = _run_media_bytes(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            f"select=eq(n\\,{max(0, int(frame_index))}),scale={max_width}:-2:force_original_aspect_ratio=decrease",
            "-frames:v",
            "1",
            "-vsync",
            "0",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ],
        timeout=20,
    )
    if result.returncode != 0 or not result.stdout:
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        raise RuntimeError((stderr or "截取视频帧失败").strip()[:500])
    encoded = base64.b64encode(result.stdout).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _frame_preview_data_url(path: Path, timestamp: float, info: dict[str, Any]) -> tuple[str, float]:
    cache_key, snapped_time = _frame_preview_cache_key(path, timestamp, info)
    cached = _preview_cache_get(cache_key)
    if cached:
        return cached, snapped_time
    data_url = _opencv_frame_preview_data_url(path, snapped_time)
    if not data_url:
        data_url = _ffmpeg_frame_preview_data_url(path, snapped_time)
    _preview_cache_set(cache_key, data_url)
    return data_url, snapped_time


def _frame_preview_data_url_by_index(path: Path, frame_index: int, info: dict[str, Any]) -> tuple[str, float, int]:
    safe_frame_index = _clamp_frame_index(frame_index, info)
    cache_key = _frame_preview_index_cache_key(path, safe_frame_index)
    cached = _preview_cache_get(cache_key)
    timestamp = _frame_timestamp_from_index(safe_frame_index, info)
    if cached:
        return cached, timestamp, safe_frame_index
    data_url = _opencv_frame_preview_data_url_by_index(path, safe_frame_index)
    if not data_url:
        data_url = _ffmpeg_frame_preview_data_url_by_index(path, safe_frame_index)
    _preview_cache_set(cache_key, data_url)
    return data_url, timestamp, safe_frame_index


def _opencv_extract_frame_at_index(path: Path, output_path: Path, frame_index: int) -> bool:
    try:
        import cv2  # type: ignore

        frame = _opencv_read_frame_at_index(path, frame_index)
        return bool(frame is not None and cv2.imwrite(str(output_path), frame))
    except Exception:
        return False


def _ffmpeg_extract_frame_at_index(path: Path, output_path: Path, frame_index: int) -> None:
    ffmpeg = _media_tool_executable("ffmpeg")
    result = _run_media_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            f"select=eq(n\\,{max(0, int(frame_index))})",
            "-frames:v",
            "1",
            "-vsync",
            "0",
            "-y",
            str(output_path),
        ],
        timeout=30,
    )
    if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 0:
        if output_path.exists():
            output_path.unlink()
        raise RuntimeError((result.stderr or "截取视频帧失败").strip()[:500])


def _extract_frame_file_at_index(path: Path, output_path: Path, frame_index: int, info: dict[str, Any]) -> float:
    safe_frame_index = _clamp_frame_index(frame_index, info)
    if _opencv_extract_frame_at_index(path, output_path, safe_frame_index):
        return _frame_timestamp_from_index(safe_frame_index, info)
    if output_path.exists():
        output_path.unlink()
    _ffmpeg_extract_frame_at_index(path, output_path, safe_frame_index)
    return _frame_timestamp_from_index(safe_frame_index, info)


def _opencv_extract_tail_frame(path: Path, output_path: Path) -> float | None:
    try:
        import cv2  # type: ignore

        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            capture.release()
            return None
        try:
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
            if frame_count > 0:
                frame_index = max(0, frame_count - 1)
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                if ok and frame is not None and cv2.imwrite(str(output_path), frame):
                    return frame_index / fps if fps > 0 else 0.0
            return None
        finally:
            capture.release()
    except Exception:
        return None


def _ffmpeg_extract_tail_frame(path: Path, output_path: Path, info: dict[str, Any]) -> float:
    ffmpeg = _media_tool_executable("ffmpeg")
    args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i", str(path),
        "-map", "0:v:0", "-an", "-vsync", "0",
        "-q:v", "2", "-update", "1", "-y", str(output_path),
    ]
    result = _run_media_command(args, timeout=max(20, float(info.get("videoDuration") or info.get("duration") or 0) * 4 + 10))
    if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 0:
        if output_path.exists():
            output_path.unlink()
        raise RuntimeError((result.stderr or "截取视频帧失败").strip()[:500])
    return _tail_frame_timestamp(info)


def _extract_tail_frame_file(path: Path, output_path: Path, info: dict[str, Any]) -> float:
    # Decode the video stream through its final frame; container duration may include a longer audio tail.
    return _ffmpeg_extract_tail_frame(path, output_path, info)


def _memory_image_media_ref(media_id: str, title: str, data_url: str) -> dict[str, Any]:
    return {
        "id": media_id,
        "kind": "image",
        "originalName": title,
        "mimeType": "image/jpeg",
        "preview": data_url,
        "dataUrl": data_url,
        "pngDataUrl": data_url,
        "outputPngDataUrl": data_url,
    }


def _video_media_ref(project_id: str, path: Path, media_id: str, original_name: str = "") -> dict[str, Any]:
    relative_path = _project_media_relative_path(project_id, path)
    return _media_ref_for_storage(
        {
            "id": media_id,
            "kind": "video",
            "path": str(path),
            "filePath": str(path),
            "relativePath": relative_path,
            "relative_path": relative_path,
            "file": relative_path,
            "size": path.stat().st_size,
            "originalName": original_name or path.name,
            "mimeType": _mime_from_video_suffix(path),
        }
    )


def _image_media_ref(project_id: str, path: Path, media_id: str, original_name: str = "") -> dict[str, Any]:
    relative_path = _project_media_relative_path(project_id, path)
    return _media_ref_for_storage(
        {
            "id": media_id,
            "kind": "image",
            "path": str(path),
            "filePath": str(path),
            "relativePath": relative_path,
            "relative_path": relative_path,
            "file": relative_path,
            "pngFile": relative_path,
            "size": path.stat().st_size,
            "originalName": original_name or path.name,
            "mimeType": "image/png",
            **image_file_metadata(path),
        }
    )


def save_clipboard_image_media(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    file_info = payload.get("file") if isinstance(payload.get("file"), dict) else payload
    if not isinstance(file_info, dict):
        raise ValueError("请粘贴图片")
    if "dataUrl" not in file_info and "data_url" not in file_info:
        raw_base64 = str(file_info.get("base64") or file_info.get("b64") or "").strip()
        mime = str(file_info.get("mimeType") or file_info.get("mime_type") or "image/png").strip()
        if raw_base64:
            file_info = {
                **file_info,
                "dataUrl": f"data:{mime};base64,{raw_base64}",
            }
    media_purpose = str(payload.get("mediaPurpose") or payload.get("media_purpose") or "character_reference").strip()
    asset_scope = str(payload.get("assetScope") or payload.get("asset_scope") or "").strip()
    subdir = (
        "visual_handoffs"
        if media_purpose == "visual_handoff"
        else "storyboard_images"
        if asset_scope == "result" or media_purpose in {"storyboard_image", "visual_reference"}
        else "canvas_media"
    )
    media_id = str(payload.get("mediaId") or payload.get("media_id") or f"clipboard-image-{uuid.uuid4().hex[:10]}")
    media = _image_media_from_file_info(
        project_id,
        file_info,
        media_id=media_id,
        subdir=subdir,
        storage_scope="episode_results",
        episode_id=episode_id,
    )
    name = str(file_info.get("name") or file_info.get("originalName") or media.get("originalName") or "粘贴图片.png")
    file_payload = {
        "id": media.get("id") or media_id,
        "name": name,
        "kind": "image",
        "mimeType": media.get("mimeType") or "image/png",
        "size": media.get("size"),
        "path": media.get("path"),
        "filePath": media.get("filePath") or media.get("path"),
        "relativePath": media.get("relativePath"),
        "relative_path": media.get("relative_path"),
        "file": media.get("file"),
    }
    return {
        "success": True,
        "projectId": project_id,
        "episodeId": episode_id,
        "media": media,
        "file": file_payload,
    }


def get_video_clip_info(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    path, info = _probe_video(project_id, _payload_media(payload))
    results_payload = _clip_results_payload(project_id, episode_id, path, info)
    return {
        "success": True,
        "projectId": project_id,
        "episodeId": episode_id,
        "source": results_payload.get("source"),
        "sourceKey": results_payload.get("sourceKey"),
        "sourcePath": str(path),
        "duration": info.get("duration"),
        "width": info.get("width"),
        "height": info.get("height"),
        "fps": info.get("fps"),
        "frameCount": info.get("frameCount"),
        "lastFrameIndex": info.get("lastFrameIndex"),
        "mimeType": info.get("mimeType"),
        "name": info.get("name"),
        "results": results_payload.get("results") or [],
    }


def list_video_clip_results(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    path, info = _probe_video(project_id, _payload_media(payload))
    return _clip_results_payload(project_id, episode_id, path, info)


def delete_video_clip_results(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    result_ids = _clip_result_ids_from_payload(payload)
    if not result_ids:
        raise ValueError("请选择要删除的剪辑结果")
    path, info = _probe_video(project_id, _payload_media(payload))
    with _clip_manifest_lock(project_id, episode_id, path):
        manifest = _read_clip_manifest(project_id, episode_id, path, info)
        root = _source_clip_root(project_id, episode_id, path)
        deleted_ids: list[str] = []
        kept_results: list[dict[str, Any]] = []
        for item in manifest.get("results", []):
            if not isinstance(item, dict):
                continue
            result_id = str(item.get("id") or "").strip()
            if result_id and result_id in result_ids:
                deleted_ids.append(result_id)
                _delete_clip_result_file(project_id, root, item)
                continue
            kept_results.append(item)
        manifest["results"] = kept_results
        if deleted_ids:
            _write_clip_manifest(project_id, episode_id, path, info, manifest)
        payload = _clip_results_payload(project_id, episode_id, path, info)
    return {
        **payload,
        "deletedIds": deleted_ids,
    }


def extract_video_frame_preview(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    path, info = _probe_video(project_id, _payload_media(payload))
    duration = float(info.get("duration") or 0)
    frame_index = _frame_index_from_payload(payload, info)
    if frame_index is not None:
        data_url, snapped_time, frame_index = _frame_preview_data_url_by_index(path, frame_index, info)
    else:
        timestamp = _frame_timestamp(payload, duration)
        data_url, snapped_time = _frame_preview_data_url(path, timestamp, info)
        frame_index = _frame_index_from_timestamp(snapped_time, info)
    digest = hashlib.sha1(
        f"{path}:{path.stat().st_mtime_ns}:frame:{frame_index}:{snapped_time:.3f}".encode("utf-8")
    ).hexdigest()[:16]
    media_id = f"video-frame-preview-{digest}"
    media = _memory_image_media_ref(media_id, f"{path.stem}-frame-{frame_index}.jpg", data_url)
    return {
        "success": True,
        "projectId": project_id,
        "episodeId": episode_id,
        "time": snapped_time,
        "frameIndex": frame_index,
        "media": media,
    }


def extract_video_frame(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    owner_path, owner_info = _probe_video(project_id, _payload_media(payload))
    input_media = payload.get("inputMedia") or payload.get("input_media") or payload.get("processingMedia") or payload.get("processing_media")
    input_path, input_info = (
        _probe_video(project_id, input_media)
        if isinstance(input_media, dict)
        else (owner_path, owner_info)
    )
    duration = float(input_info.get("duration") or 0)
    tail_frame = _payload_tail_frame(payload)
    frame_index = None if tail_frame else _frame_index_from_payload(payload, input_info)
    timestamp = (
        _frame_timestamp_from_index(frame_index, input_info)
        if frame_index is not None
        else (_tail_frame_timestamp(input_info) if tail_frame else _frame_timestamp(payload, duration))
    )
    media_id = _safe_file_stem(
        payload.get("mediaId") or payload.get("media_id") or f"video-frame-{uuid.uuid4().hex[:10]}",
        f"video-frame-{uuid.uuid4().hex[:10]}",
    )
    output_dir = _source_clip_root(project_id, episode_id, owner_path) / "frames"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{media_id}.png"
    if output_path.exists():
        output_path.unlink()
    if frame_index is not None:
        timestamp = _extract_frame_file_at_index(input_path, output_path, frame_index, input_info)
    elif tail_frame:
        timestamp = _extract_tail_frame_file(input_path, output_path, input_info)
    else:
        ffmpeg = _media_tool_executable("ffmpeg")
        result = _run_media_command(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(input_path),
                "-frames:v",
                "1",
                "-y",
                str(output_path),
            ],
            timeout=20,
        )
        if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 0:
            if output_path.exists():
                output_path.unlink()
            raise RuntimeError((result.stderr or "截取视频帧失败").strip()[:500])
    title = str(
        payload.get("title")
        or (
            f"{input_path.stem}-frame-{frame_index}.png"
            if frame_index is not None
            else f"{input_path.stem}-截帧-{timestamp:.2f}.png"
        )
    )
    media = _image_media_ref(project_id, output_path, media_id, title)
    source_stat = input_path.stat()
    image_stat = output_path.stat()
    source_version_id = ""
    if tail_frame and input_path.resolve() == owner_path.resolve():
        from .archive_transfers import _episode_video_plan

        active = [clip for clip in _episode_video_plan(project_id, episode_id)["clips"]
                  if clip.get("kind") == "work_chain"
                  and Path(clip["path"]).resolve() == input_path.resolve()]
        if len(active) == 1:
            source_version_id = str(active[0].get("versionId") or "")
    media.update({
        "assetType": "frame_image",
        "frameOrigin": {
            "projectId": project_id,
            "episodeId": episode_id,
            "sourcePath": str(owner_path),
            "inputPath": str(input_path),
            "resultId": media_id,
            "time": timestamp,
            "frameIndex": frame_index,
            "captureKind": "tail" if tail_frame else "frame",
            "sourceVersionId": source_version_id,
            "sourceFileSignature": {"size": source_stat.st_size, "mtimeNs": source_stat.st_mtime_ns},
            "imageFileSignature": {"size": image_stat.st_size, "mtimeNs": image_stat.st_mtime_ns},
        },
    })
    origin_path = _frame_origin_path(media["frameOrigin"])
    origin_path.parent.mkdir(parents=True, exist_ok=True)
    origin_path.write_text(json.dumps(media["frameOrigin"], ensure_ascii=False), encoding="utf-8")
    record = _persist_clip_result(
        project_id,
        episode_id,
        owner_path,
        owner_info,
        _clip_result_record(
            result_id=media_id,
            kind="image",
            title=title,
            media=media,
            source_key=_source_clip_key(project_id, owner_path),
            time=timestamp,
            frame_index=frame_index,
        ),
    )
    return {
        "success": True,
        "projectId": project_id,
        "episodeId": episode_id,
        "time": timestamp,
        **({"frameIndex": frame_index} if frame_index is not None else {}),
        "media": media,
        "result": record,
    }


def trim_video_clip(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    owner_path, owner_info = _probe_video(project_id, _payload_media(payload))
    input_media = payload.get("inputMedia") or payload.get("input_media") or payload.get("processingMedia") or payload.get("processing_media")
    input_path, input_info = (
        _probe_video(project_id, input_media)
        if isinstance(input_media, dict)
        else (owner_path, owner_info)
    )
    duration = float(input_info.get("duration") or 0)
    start = max(0.0, min(_float_payload(payload, "start", "startTime", "start_time"), duration))
    end = max(0.0, min(_float_payload(payload, "end", "endTime", "end_time", default=duration), duration))
    if end <= start:
        raise ValueError("剪切结束时间必须大于开始时间")
    clip_duration = end - start
    crop_rect = _payload_crop_rect(payload, input_info)
    media_id = _safe_file_stem(
        payload.get("mediaId") or payload.get("media_id") or f"video-clip-{uuid.uuid4().hex[:10]}",
        f"video-clip-{uuid.uuid4().hex[:10]}",
    )
    output_dir = _source_clip_root(project_id, episode_id, owner_path) / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{media_id}.mp4"
    ffmpeg = _media_tool_executable("ffmpeg")
    video_filter_args = (
        [
            "-vf",
            "crop={width}:{height}:{x}:{y}".format(**crop_rect),
        ]
        if crop_rect
        else []
    )
    encode_result = _run_media_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{clip_duration:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            *video_filter_args,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            "-avoid_negative_ts",
            "make_zero",
            "-reset_timestamps",
            "1",
            "-y",
            str(output_path),
        ],
        timeout=max(60, clip_duration * 5 + 30),
    )
    warning = ""
    if encode_result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 0:
        if output_path.exists():
            output_path.unlink()
        raise RuntimeError((encode_result.stderr or "剪切视频失败").strip()[:500])
    title = str(payload.get("title") or f"{input_path.stem}-{start:.2f}-{end:.2f}.mp4")
    media = _video_media_ref(project_id, output_path, media_id, title)
    record = _persist_clip_result(
        project_id,
        episode_id,
        owner_path,
        owner_info,
        _clip_result_record(
            result_id=media_id,
            kind="video",
            title=title,
            media=media,
            source_key=_source_clip_key(project_id, owner_path),
            start=start,
            end=end,
            duration=clip_duration,
            crop=crop_rect,
        ),
    )
    return {
        "success": True,
        "projectId": project_id,
        "episodeId": episode_id,
        "start": start,
        "end": end,
        "duration": clip_duration,
        **({"crop": crop_rect} if crop_rect else {}),
        "media": media,
        "result": record,
        **({"warning": warning} if warning else {}),
    }


__all__ = (
    "save_clipboard_image_media",
    "get_video_clip_info",
    "list_video_clip_results",
    "delete_video_clip_results",
    "extract_video_frame_preview",
    "extract_video_frame",
    "ensure_video_thumbnail",
    "trim_video_clip",
)
