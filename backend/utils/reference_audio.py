"""Provider reference-voice contracts, independent of local storage and uploads."""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlsplit

from utils.video_model_capabilities import video_model_capability


def reference_audio_limits(model: Any) -> dict[str, Any]:
    adapter = (video_model_capability(model) or {}).get("adapter_capabilities") or {}
    return adapter.get("reference_audio_limits", {}) if adapter.get("supports_reference_audio_input") else {}


def validate_reference_audios(rows: list[dict[str, Any]], model: Any, *, native: bool = False,
                              image_count: int = 0, video_count: int = 0,
                              require_urls: bool = True) -> list[str]:
    if not rows:
        return []
    limits = reference_audio_limits(model)
    if not limits:
        raise ValueError("当前模型尚未接入参考音频，请使用文字音色")
    if native and not limits["supports_native_frames"]:
        raise ValueError("当前模型的原生首尾帧模式不支持参考音频")
    if len(rows) > limits["max_count"]:
        raise ValueError(f"参考音频数量超过模型上限 {limits['max_count']} 段")
    if limits["requires_visual"] and image_count + video_count <= 0:
        raise ValueError("当前模型的参考音频需要同时传入参考图或参考视频")
    mixed_limit = limits.get("max_mixed_materials", 0)
    if mixed_limit and image_count + video_count + len(rows) > mixed_limit:
        raise ValueError(f"图片、视频、音频参考素材总数超过模型上限 {mixed_limit}")
    total = 0.0
    urls = []
    for row in rows:
        label = row.get("displayName") or "说话人"
        duration = float(row.get("duration") or 0)
        if not math.isfinite(duration) or not limits["min_seconds"] <= duration <= limits["max_seconds"] + 0.01:
            raise ValueError(f"{label}的参考音频须为 {limits['min_seconds']}–{limits['max_seconds']} 秒，请在声音设置中裁剪")
        if row.get("format") not in limits["formats"] or not 0 < int(row.get("size") or 0) <= limits["max_bytes"]:
            raise ValueError(f"{label}的参考音频须为 WAV/MP3，且不超过 15 MB")
        total += duration
        url = str(row.get("audioUrl") or row.get("url") or "")
        if require_urls:
            parsed = urlsplit(url)
            public = parsed.scheme in {"http", "https"} and bool(parsed.hostname) and parsed.username is None
            inline = url.startswith(("data:audio/wav;base64,", "data:audio/mpeg;base64,", "data:audio/mp3;base64,"))
            if not public and not (inline and limits["transport"] == "data_url"):
                raise ValueError(f"{label}的参考音频传输地址无效")
        urls.append(url)
    if total > limits["total_max_seconds"] + 0.01:
        raise ValueError(f"参考音频总时长超过模型上限 {limits['total_max_seconds']} 秒")
    return urls


def audio_content(rows: list[dict[str, Any]], model: Any, **kwargs: Any) -> list[dict[str, Any]]:
    return [{"type": "audio_url", "audio_url": {"url": url}, "role": "reference_audio"}
            for url in validate_reference_audios(rows, model, **kwargs)]
