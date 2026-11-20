# -*- coding: utf-8 -*-
"""Shared reference-video validation. Durations are measured from local files."""

from __future__ import annotations

import math
import subprocess
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from utils.video_model_capabilities import video_model_capability
from utils.video_prompt_mentions import with_prompt_mentions
from utils.video_input_images import minimum_media_scale

VIDEO_REFERENCE_SLOT = "reference_video"


def reference_rows_in_transport_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Put the storyboard sheet first and preserve every other row's order."""
    storyboard_rows: list[dict[str, Any]] = []
    other_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slot = str(row.get("slot") or row.get("targetSlot") or row.get("target_slot") or "").strip()
        source_type = str(row.get("sourceType") or row.get("source_type") or "").strip().lower()
        asset_type = str(row.get("assetType") or row.get("asset_type") or "").strip().lower()
        is_storyboard = (
            slot == "storyboard_image"
            or source_type in {"storyboard_image", "storyboard_version"}
            or asset_type == "storyboard"
        )
        (storyboard_rows if is_storyboard else other_rows).append(row)
    return [*storyboard_rows, *other_rows]


def reference_manifest_from_rows(
    image_rows: list[dict[str, Any]],
    video_rows: list[dict[str, Any]],
    *,
    video_source_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build the UI/provider reference index without adding prompt prose."""
    manifest: list[dict[str, Any]] = []

    def identity(row: dict[str, Any]) -> str:
        return str(
            row.get("requestedReferenceId")
            or row.get("sourceNodeId") or row.get("source_node_id")
            or row.get("mediaId") or row.get("media_id")
            or row.get("mediaVersionId") or row.get("media_version_id")
            or row.get("assetId") or row.get("asset_id") or ""
        ).strip()

    if video_source_ids is not None:
        by_identity = {identity(row): row for row in video_rows}
        video_rows = [
            {**by_identity.get(source_id, {}), "requestedReferenceId": source_id}
            for source_id in video_source_ids
        ]

    def append(kind: str, rows: list[dict[str, Any]]) -> None:
        seen: set[str] = set()
        index = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            source_id = identity(row)
            if source_id and source_id in seen:
                continue
            if source_id:
                seen.add(source_id)
            transport_role = str(row.get("transportRole") or ("reference_video" if kind == "video" else "reference_image"))
            numbered = transport_role in {"reference_image", "reference_video"}
            if numbered:
                index += 1
            name = str(
                row.get("displayName")
                or row.get("display_name")
                or row.get("label")
                or row.get("name")
                or row.get("title")
                or ""
            ).strip()
            reference_label = f"参考视频{index}" if kind == "video" else f"参考图{index}"
            if not numbered:
                reference_label = {"first_frame": "原生首帧", "last_frame": "原生尾帧"}.get(transport_role, "")
            manifest.append({
                "kind": kind,
                "index": index if numbered else 0,
                "referenceLabel": reference_label,
                "transportRole": transport_role,
                "identity": source_id,
                "sourceNodeId": str(row.get("sourceNodeId") or row.get("source_node_id") or "").strip(),
                "referenceSourceNodeIds": list(row.get("referenceSourceNodeIds") or []),
                "mediaId": str(row.get("mediaId") or row.get("media_id") or "").strip(),
                "mediaVersionId": str(row.get("mediaVersionId") or row.get("sourceVersionId") or row.get("assetVersionId") or row.get("versionId") or "").strip(),
                "assetId": str(row.get("assetId") or row.get("asset_id") or "").strip(),
                "displayName": name,
                "slot": str(row.get("targetSlot") or row.get("target_slot") or row.get("slot") or "").strip(),
                "assetType": str(row.get("assetType") or row.get("asset_type") or ""),
                "frameRole": str(row.get("frameRole") or ""),
            })

    append("image", reference_rows_in_transport_order(image_rows))
    append("video", video_rows)
    return with_prompt_mentions(manifest)


def reference_video_capability(model: Any) -> dict[str, Any]:
    # Always use the canonical catalog rather than client-supplied capability flags.
    return video_model_capability(model) or {}


def reference_video_limits(model: Any) -> dict[str, Any]:
    spec = reference_video_capability(model)
    return dict((spec.get("adapter_capabilities") or {}).get("reference_video_limits") or {})


def reference_video_needs_transcode(video: dict[str, Any], limits: dict[str, Any]) -> bool:
    if not _reference_video_codecs_valid(video, limits):
        return True
    format_name = str(video.get("format") or "").strip().lower().lstrip(".")
    if format_name not in {str(item).strip().lower().lstrip(".") for item in limits.get("formats") or []}:
        return True
    max_bytes = int(limits.get("max_bytes") or 0)
    if max_bytes and int(video.get("size") or 0) > max_bytes:
        return True
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if width > int(limits.get("max_width") or width) or height > int(limits.get("max_height") or height):
        return True
    max_pixels = int(limits.get("max_pixels") or 0)
    if max_pixels and width * height > max_pixels:
        return True
    max_fps = float(limits.get("max_fps") or 0)
    return bool(max_fps and float(video.get("fps") or 0) > max_fps + 0.001)


def _reference_video_codecs_valid(video: dict[str, Any], limits: dict[str, Any]) -> bool:
    video_codec = video.get("videoCodec")
    allowed_video_codecs = limits.get("video_codecs") or []
    if allowed_video_codecs and (not video_codec or video_codec not in allowed_video_codecs):
        # Missing metadata is not proof of compatibility. A provider may reject
        # a VP9/MPEG-4 file even when the container and extension look valid.
        return False
    audio_codecs = video.get("audioCodecs") or []
    return not limits.get("audio_codecs") or not audio_codecs or all(
        codec in limits["audio_codecs"] for codec in audio_codecs
    )


def validate_reference_video_durations(
    videos: list[dict[str, Any]], model: Any, *, image_count: int | None = None,
    output_duration: float | None = None,
) -> None:
    """Validate association-time limits that cannot be repaired by transcoding."""
    if not videos:
        return
    spec = reference_video_capability(model)
    adapter = spec.get("adapter_capabilities") or {}
    label = spec.get("title") or "当前模型"
    limits = adapter.get("reference_video_limits") or {}
    if not adapter.get("supports_reference_video") or not limits:
        raise ValueError(f"{label}不支持参考视频，请移除视频关联或切换模型")
    max_count = int(adapter.get("max_reference_videos") or 0)
    if len(videos) > max_count:
        raise ValueError(f"{label}最多支持 {max_count} 段参考视频，当前关联了 {len(videos)} 段")
    total = 0.0
    for index, video in enumerate(videos, 1):
        duration = float(video.get("duration") or 0)
        title = str(video.get("title") or video.get("originalName") or f"视频{index}")
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"无法读取「{title}」的真实时长，请重新添加视频")
        if duration > limits.get("max_seconds", math.inf) + 0.000001:
            raise ValueError(f"{label}参考视频上限为 {limits['max_seconds']:g} 秒，「{title}」为 {duration:.3f} 秒，请先剪辑")
        if duration < limits.get("min_seconds", 0) - 0.000001:
            raise ValueError(f"{label}参考视频至少 {limits['min_seconds']:g} 秒，「{title}」仅 {duration:.3f} 秒")
        total += duration
    total_limit = limits.get("total_max_seconds")
    if total_limit and total > total_limit + 0.000001:
        raise ValueError(f"{label}参考视频总时长上限为 {total_limit:g} 秒，当前合计 {total:.3f} 秒")
    _validate_input_output_duration(limits, total, output_duration, label)
    _validate_reference_material_combination(
        adapter,
        image_count=image_count,
        video_count=len(videos),
        label=label,
    )
    durations = adapter.get("durations_with_reference_video") or []
    if output_duration and durations and output_duration not in durations:
        raise ValueError(f"{label}使用参考视频时生成时长需为 {min(durations)}～{max(durations)} 秒，当前设置为 {output_duration:g} 秒")


def _reference_video_geometry_error(width: int, height: int, limits: dict[str, Any]) -> str:
    """Use the same geometry constraints when choosing an encode and validating it."""
    if not (int(limits.get("min_width") or 1) <= width <= (limits.get("max_width") or math.inf)
            and int(limits.get("min_height") or 1) <= height <= (limits.get("max_height") or math.inf)):
        return "dimensions"
    if not limits.get("min_ratio", 0) <= width / height <= limits.get("max_ratio", math.inf):
        return "ratio"
    if not int(limits.get("min_pixels") or 0) <= width * height <= (limits.get("max_pixels") or math.inf):
        return "pixels"
    return ""


def _reference_video_size_options(
    width: int, height: int, scale: float, floor: float, limits: dict[str, Any],
) -> list[tuple[int, int]]:
    minimum_width, minimum_height = math.ceil(width * floor / 2) * 2, math.ceil(height * floor / 2) * 2
    target = (max(minimum_width, int(width * scale) // 2 * 2),
              max(minimum_height, int(height * scale) // 2 * 2))
    # Correct rounding by at most one encoder unit, without crossing the quality floor.
    options = [
        (w, h) for w in range(target[0] - 2, target[0] + 3, 2)
        for h in range(target[1] - 2, target[1] + 3, 2)
        if minimum_width <= w <= math.ceil(width / 2) * 2
        and minimum_height <= h <= math.ceil(height / 2) * 2
        and not _reference_video_geometry_error(w, h, limits)
    ]
    return sorted(options, key=lambda size: (size != target, abs(size[0] / size[1] - width / height)))


@contextmanager
def prepare_reference_video(
    source: Path,
    video: dict[str, Any],
    limits: dict[str, Any],
    *,
    ffmpeg: str,
):
    """Transcode only oversized reference inputs and keep the temporary file alive."""
    if not reference_video_needs_transcode(video, limits):
        yield source, {"compressed": False, "originalSize": int(video.get("size") or 0)}
        return
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("无法读取参考视频的原始尺寸，已中断生成，请重新添加视频")
    title = str(video.get("title") or video.get("originalName") or source.name)
    duration = float(video.get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("无法读取参考视频的原始时长，已中断生成，请重新添加视频")
    floor = max(
        minimum_media_scale(width, height),
        int(limits.get("min_width") or 0) / width,
        int(limits.get("min_height") or 0) / height,
        math.sqrt(int(limits.get("min_pixels") or 0) / (width * height)),
    )
    scale = 1.0
    max_width = int(limits.get("max_width") or width)
    max_height = int(limits.get("max_height") or height)
    max_pixels = int(limits.get("max_pixels") or 0)
    if width > max_width or height > max_height:
        scale = min(scale, max_width / max(width, 1), max_height / max(height, 1))
    if max_pixels and width * height > max_pixels:
        scale = min(scale, math.sqrt(max_pixels / max(width * height, 1)))
    if scale + 1e-9 < floor:
        raise ValueError(
            f"参考视频「{title}」为 {width}×{height}，满足模型尺寸限制需要缩小至原尺寸的 {scale:.1%}，"
            "低于清晰度保护下限（宽高至少保留 75%，高清短边不低于 720）。已中断生成，请更换素材。"
        )
    max_fps = float(limits.get("max_fps") or 0)
    reduce_fps = bool(max_fps and float(video.get("fps") or 0) > max_fps + 0.001)
    max_bytes = int(limits.get("max_bytes") or 0)
    with TemporaryDirectory(prefix="ai-video-reference-") as temp_dir:
        last_size = 0
        output_path = Path(temp_dir) / "reference.mp4"
        candidates = [(scale, crf) for crf in (18, 20, 22)]
        candidates += [(max(floor, scale * step), 22) for step in (0.95, 0.9, 0.85, 0.8, 0.75)]
        attempted = set()
        for candidate_scale, crf in candidates:
            sizes = _reference_video_size_options(width, height, candidate_scale, floor, limits)
            if not sizes:
                continue
            output_width, output_height = sizes[0]
            attempt = (output_width, output_height, crf)
            if attempt in attempted:
                continue
            attempted.add(attempt)
            filters = []
            if output_width != width or output_height != height:
                filters.append(f"scale={output_width}:{output_height}:flags=lanczos")
            if reduce_fps:
                filters.append(f"fps={max_fps:g}:round=near:eof_action=pass")
            output_path.unlink(missing_ok=True)
            args = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
                *( ["-vf", ",".join(filters)] if filters else [] ),
                "-t", f"{duration:.9f}", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                str(output_path),
            ]
            result = subprocess.run(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", timeout=3600,
                check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode or not output_path.is_file():
                raise RuntimeError("参考视频压缩失败，请确认视频文件未损坏")
            last_size = output_path.stat().st_size
            if not max_bytes or last_size <= max_bytes:
                yield output_path, {
                    "compressed": True,
                    "originalSize": int(video.get("size") or 0),
                    "compressedSize": last_size,
                    "originalWidth": width,
                    "originalHeight": height,
                    "width": output_width,
                    "height": output_height,
                    "crf": crf,
                }
                return
        raise ValueError(
            f"参考视频「{title}」已达到清晰度保护下限（宽高至少保留 75%，高清短边不低于 720，编码 CRF 不高于 22），"
            f"压缩后 {last_size / 1048576:.2f} MB，模型文件上限 {max_bytes / 1048576:g} MB，仍无法满足文件或尺寸限制。"
            "已中断生成，未截短视频或移除声音；请替换素材、手动剪辑后重新关联，或选择容量更大的模型。"
        )


def validate_reference_videos(
    videos: list[dict[str, Any]], model: Any, *,
    image_count: int | None = None, output_duration: float | None = None,
) -> None:
    if not videos:
        return
    spec = reference_video_capability(model)
    adapter = spec.get("adapter_capabilities") or {}
    label = spec.get("title") or "当前模型"
    limits = adapter.get("reference_video_limits") or {}
    if not adapter.get("supports_reference_video") or not limits:
        raise ValueError(f"{label}不支持参考视频，请移除视频关联或切换模型")
    max_count = int(adapter.get("max_reference_videos") or 0)
    if len(videos) > max_count:
        raise ValueError(f"{label}最多支持 {max_count} 段参考视频，当前关联了 {len(videos)} 段")
    total = 0.0
    for index, video in enumerate(videos, 1):
        duration = float(video.get("duration") or 0)
        title = str(video.get("title") or video.get("originalName") or f"视频{index}")
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"无法读取「{title}」的真实时长，请重新添加视频")
        if duration > limits.get("max_seconds", math.inf) + 0.000001:
            raise ValueError(f"{label}参考视频上限为 {limits['max_seconds']:g} 秒，「{title}」为 {duration:.3f} 秒，请先剪辑")
        if duration < limits.get("min_seconds", 0) - 0.000001:
            raise ValueError(f"{label}参考视频至少 {limits['min_seconds']:g} 秒，「{title}」仅 {duration:.3f} 秒")
        total += duration
        if limits.get("max_bytes") and int(video.get("size") or 0) > limits["max_bytes"]:
            raise ValueError(f"「{title}」超过 {label} 的参考视频文件上限 {limits['max_bytes'] // (1024 * 1024)} MB")
        if str(video.get("format") or "").lower() not in limits["formats"]:
            raise ValueError(f"{label}参考视频仅支持 {'、'.join(limits['formats'])} 格式")
        if not _reference_video_codecs_valid(video, limits):
            raise ValueError(f"「{title}」视频或音频编码不符合 {label} 的参考视频要求，请转换格式后重试")
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
        geometry_error = _reference_video_geometry_error(width, height, limits)
        if geometry_error == "dimensions":
            raise ValueError(f"「{title}」尺寸 {width}×{height} 不符合 {label} 的参考视频尺寸要求")
        if geometry_error == "ratio":
            raise ValueError(f"「{title}」宽高比不符合 {label} 的参考视频要求")
        if geometry_error == "pixels":
            raise ValueError(f"「{title}」总像素数不符合 {label} 的参考视频要求")
        fps = float(video.get("fps") or 0)
        if limits.get("min_fps") and (not math.isfinite(fps) or fps < limits["min_fps"]):
            raise ValueError(f"「{title}」帧率至少为 {limits['min_fps']} FPS")
        if limits.get("max_fps") and fps > limits["max_fps"]:
            raise ValueError(f"「{title}」帧率不能超过 {limits['max_fps']} FPS")
    total_limit = limits.get("total_max_seconds")
    if total_limit and total > total_limit + 0.000001:
        raise ValueError(f"{label}参考视频总时长上限为 {total_limit:g} 秒，当前合计 {total:.3f} 秒")
    _validate_input_output_duration(limits, total, output_duration, label)
    _validate_reference_material_combination(
        adapter,
        image_count=image_count,
        video_count=len(videos),
        label=label,
    )
    durations = adapter.get("durations_with_reference_video") or []
    if output_duration and durations and output_duration not in durations:
        raise ValueError(f"{label}使用参考视频时生成时长需为 {min(durations)}～{max(durations)} 秒，当前设置为 {output_duration:g} 秒")


def _validate_input_output_duration(
    limits: dict[str, Any], total: float, output_duration: float | None, label: str,
) -> None:
    maximum = limits.get("input_output_max_seconds")
    if maximum and output_duration and total + output_duration > maximum + 0.000001:
        raise ValueError(
            f"{label}参考视频与生成视频总时长不能超过 {maximum:g} 秒，"
            f"当前参考 {total:.3f} 秒、生成 {output_duration:g} 秒，请缩短时长"
        )


def _validate_reference_material_combination(
    adapter: dict[str, Any],
    *,
    image_count: int | None,
    video_count: int,
    label: str,
) -> None:
    if image_count is None:
        return
    if image_count < 0:
        raise ValueError("参考图数量不能为负数")
    modes = (adapter.get("visual_inputs") or {}).get("modes") or []
    if not any(
        image_count <= int((mode.get("max_counts") or {}).get("reference_image", 0))
        and video_count <= int((mode.get("max_counts") or {}).get("reference_video", 0))
        and int(mode.get("min_reference_materials") or 0) <= image_count + video_count <= int(mode.get("max_reference_materials") or 0)
        for mode in modes
    ):
        raise ValueError(f"{label}不支持当前 {image_count} 张参考图与 {video_count} 段参考视频的组合，请减少素材")


def reference_video_source_ids(payload: dict[str, Any]) -> list[str]:
    """Project associations to unique video uploads in authoritative link order."""
    links = payload.get("inputLinksSnapshot")
    if not isinstance(links, list):
        links = payload.get("inputLinks")
    rows = links if isinstance(links, list) else [
        row
        for key in ("referenceVideoThumbnails", "referenceThumbnails", "assetThumbnails")
        for row in (payload.get(key) or [])
    ]
    result: list[str] = []
    seen_media: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("enabled") is False:
            continue
        slot = str(row.get("targetSlot") or row.get("target_slot") or row.get("slot") or "")
        if slot not in {"reference_video", "video_reference"}:
            continue
        if str(row.get("status") or "").lower() in {
            "deleted", "input_link_removed", "input_link_unlinked", "linked_item_deleted",
            "material_edge_removed", "removed", "unlinked",
        }:
            continue
        identity = str(row.get("sourceNodeId") or row.get("source_node_id") or row.get("mediaId") or row.get("media_id") or "").strip()
        media = row.get("media") if isinstance(row.get("media"), dict) else {}
        media_id = str(row.get("mediaId") or media.get("id") or row.get("path") or media.get("path") or row.get("url") or media.get("url") or identity)
        version = str(row.get("mediaVersionId") or row.get("sourceVersionId") or row.get("assetVersionId") or media.get("versionId") or "")
        key = (media_id, version)
        if key in seen_media:
            continue
        if identity and identity not in result:
            seen_media.add(key)
            result.append(identity)
    return result
