# -*- coding: utf-8 -*-
"""Prepare local video assets: trim only oversized inputs, encode only non-MP4 inputs."""

from __future__ import annotations

import json
import logging
import math
import subprocess
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator

MAX_IMPORT_VIDEO_SECONDS = 30 * 60
SUPPORTED_IMPORT_VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
_logger = logging.getLogger(__name__)


def _run(args: list[str], *, label: str, timeout: float) -> str:
    try:
        result = subprocess.run(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{label}超时，请重试") from exc
    if result.returncode:
        _logger.error("%s failed: %s", label, result.stderr)
        raise RuntimeError(f"{label}失败，请确认视频未损坏且编码受支持")
    return result.stdout


def _probe(path: Path, ffprobe: str) -> dict[str, Any]:
    data = json.loads(_run([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration:format=duration",
        "-of", "json", str(path),
    ], label="读取视频信息", timeout=60))
    streams = data.get("streams") or []
    if not streams:
        raise ValueError("所选文件没有可用的视频画面")
    stream = streams[0]
    durations = []
    for raw in ((data.get("format") or {}).get("duration"), stream.get("duration")):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            durations.append(value)
    if not durations:
        raise ValueError("无法确认视频时长，请选择具有有效时长的视频文件")
    return {
        "duration": max(durations),
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
    }


@contextmanager
def prepare_import_video(
    source: Path, *, ffmpeg: str, ffprobe: str,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Yield a prepared MP4; keep temporary files alive until the caller stores it."""
    if not source.is_file() or source.suffix.lower() not in SUPPORTED_IMPORT_VIDEO_SUFFIXES:
        raise ValueError("请选择 MP4、MOV、WebM、MKV、AVI 或 M4V 视频文件")
    source_info = _probe(source, ffprobe)
    trim = source_info["duration"] > MAX_IMPORT_VIDEO_SECONDS
    transcode = source.suffix.lower() != ".mp4"
    if not trim and not transcode:
        yield source, source_info
        return

    with TemporaryDirectory(prefix="ai-video-import-") as temp_dir:
        prepared = source
        if trim:
            prepared = Path(temp_dir) / f"trimmed{source.suffix.lower()}"
            _run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(source), "-t", str(MAX_IMPORT_VIDEO_SECONDS),
                "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", str(prepared),
            ], label="截取前 30 分钟", timeout=3600)
        if transcode:
            output = Path(temp_dir) / "converted.mp4"
            # The encoder only reads the retained clip when the input was oversized.
            _run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(prepared), "-map", "0:v:0", "-map", "0:a:0?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-movflags", "+faststart", str(output),
            ], label="转换 MP4", timeout=36000)
            prepared = output
        yield prepared, _probe(prepared, ffprobe)
