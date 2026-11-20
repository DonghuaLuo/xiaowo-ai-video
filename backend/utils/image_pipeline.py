#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unified image pipeline for ai-video storage and transport policy."""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageOps
except Exception:  # pragma: no cover - Pillow may be absent in minimal runtimes.
    Image = None
    ImageOps = None

_PNG_MIME = "image/png"
_JPEG_MIME = "image/jpeg"
_PROVIDER_JPEG_QUALITY = 92
_PROVIDER_PNG_TRANSPARENCY_MIN = 0.60
_PROVIDER_PNG_TRANSPARENT_AREA_MIN = 0.05
# Alpha 0 is fully transparent and 255 is fully opaque; <=102 means >=60% transparent.
_PROVIDER_PNG_TRANSPARENT_ALPHA_MAX = int(round(255 * (1.0 - _PROVIDER_PNG_TRANSPARENCY_MIN)))
PROVIDER_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE = 2048
PROVIDER_IMAGE_INPUT_DEFAULT_MAX_BYTES = 12 * 1024 * 1024
_MAX_LONG_EDGE = PROVIDER_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE


@dataclass(frozen=True)
class PreparedProviderImageBytes:
    """Provider-safe in-memory image payload plus audit metadata."""

    data: bytes
    prepared_mime: str
    original_width: int
    original_height: int
    prepared_width: int
    prepared_height: int
    resized: bool
    transcoded: bool
    purpose: str
    jpeg_quality: int | None
    max_long_edge: int | None
    max_bytes: int | None

    @property
    def data_url(self) -> str:
        return data_url_from_bytes(self.prepared_mime, self.data)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "input_mime": self.prepared_mime,
            "input_bytes": len(self.data),
            "source_size": {"width": self.original_width, "height": self.original_height},
            "input_size": {"width": self.prepared_width, "height": self.prepared_height},
            "resized": self.resized,
            "transcoded": self.transcoded,
            "jpeg_quality": self.jpeg_quality,
            "max_long_edge": self.max_long_edge,
            "max_bytes": self.max_bytes,
        }


def data_url_from_bytes(mime: str, raw: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _fit_long_edge(width: int, height: int, max_long_edge: int) -> tuple[int, int]:
    if max_long_edge <= 0:
        return width, height
    long_edge = max(width, height)
    if long_edge <= max_long_edge:
        return width, height
    scale = max_long_edge / long_edge
    return max(1, int(width * scale)), max(1, int(height * scale))


def _aspect_ratio_from_size(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return ""
    divisor = math.gcd(width, height) or 1
    return f"{width // divisor}:{height // divisor}"


def _has_alpha_channel(img: Image.Image) -> bool:
    if "A" in img.getbands():
        return True
    if img.mode == "P" and "transparency" in img.info:
        return True
    return False


def _alpha_channel(img: Image.Image) -> Image.Image | None:
    if "A" in img.getbands():
        return img.getchannel("A")
    if img.mode == "P" and "transparency" in img.info:
        return img.convert("RGBA").getchannel("A")
    return None


def _has_provider_png_transparency(img: Image.Image) -> bool:
    alpha = _alpha_channel(img)
    if alpha is None:
        return False
    extrema = alpha.getextrema()
    if not extrema or extrema[0] > _PROVIDER_PNG_TRANSPARENT_ALPHA_MAX:
        return False
    total_pixels = max(1, int(alpha.width) * int(alpha.height))
    histogram = alpha.histogram()
    transparent_pixels = sum(histogram[: _PROVIDER_PNG_TRANSPARENT_ALPHA_MAX + 1])
    return (transparent_pixels / total_pixels) >= _PROVIDER_PNG_TRANSPARENT_AREA_MIN


def _require_pillow() -> None:
    if Image is None or ImageOps is None:
        raise RuntimeError("当前运行时未安装 Pillow，无法执行统一图片转码")


def _save_png_bytes(img: Image.Image) -> bytes:
    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _save_jpeg_bytes(img: Image.Image, quality: int) -> bytes:
    out = BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def _next_byte_limit_size(width: int, height: int, current_bytes: int, max_bytes: int) -> tuple[int, int]:
    if width <= 1 or height <= 1 or current_bytes <= 0 or max_bytes <= 0:
        return width, height
    scale = math.sqrt(max_bytes / current_bytes) * 0.92
    scale = max(0.45, min(0.92, scale))
    next_width = max(1, int(width * scale))
    next_height = max(1, int(height * scale))
    if (next_width, next_height) == (width, height):
        next_width = max(1, width - 1)
        next_height = max(1, height - 1)
    return next_width, next_height


def _png_under_byte_limit(img: Image.Image, max_bytes: int | None) -> tuple[Image.Image, bytes, bool]:
    prepared = img
    data = _save_png_bytes(prepared)
    resized = False
    attempts = 0
    while max_bytes and len(data) > max_bytes and attempts < 10 and max(prepared.size) > 256:
        next_size = _next_byte_limit_size(prepared.size[0], prepared.size[1], len(data), max_bytes)
        if next_size == prepared.size:
            break
        prepared = prepared.resize(next_size, Image.Resampling.LANCZOS)
        data = _save_png_bytes(prepared)
        resized = True
        attempts += 1
    if max_bytes and len(data) > max_bytes:
        raise ValueError("Reference image exceeds provider input byte limit")
    return prepared, data, resized


def _jpeg_under_byte_limit(
    img: Image.Image,
    jpeg_quality: int,
    max_bytes: int | None,
) -> tuple[Image.Image, bytes, bool, int]:
    prepared = img.convert("RGB")
    quality = max(1, min(95, int(jpeg_quality or _PROVIDER_JPEG_QUALITY)))
    qualities = [quality, 88, 82, 76, 70, 64, 58, 52, 46]
    qualities = [item for index, item in enumerate(qualities) if item <= quality and item not in qualities[:index]]
    data = _save_jpeg_bytes(prepared, qualities[0])
    final_quality = qualities[0]
    resized = False

    def try_qualities(target: Image.Image, current_quality: int) -> tuple[bytes, int]:
        best_data = _save_jpeg_bytes(target, current_quality)
        best_quality = current_quality
        if not max_bytes or len(best_data) <= max_bytes:
            return best_data, best_quality
        for candidate_quality in qualities:
            if candidate_quality > current_quality:
                continue
            candidate_data = _save_jpeg_bytes(target, candidate_quality)
            best_data = candidate_data
            best_quality = candidate_quality
            if len(candidate_data) <= max_bytes:
                break
        return best_data, best_quality

    data, final_quality = try_qualities(prepared, final_quality)
    attempts = 0
    while max_bytes and len(data) > max_bytes and attempts < 10 and max(prepared.size) > 256:
        next_size = _next_byte_limit_size(prepared.size[0], prepared.size[1], len(data), max_bytes)
        if next_size == prepared.size:
            break
        prepared = prepared.resize(next_size, Image.Resampling.LANCZOS)
        resized = True
        data, final_quality = try_qualities(prepared, min(final_quality, 82))
        attempts += 1
    if max_bytes and len(data) > max_bytes:
        raise ValueError("Reference image exceeds provider input byte limit")
    return prepared, data, resized, final_quality


def _png_safe_image(img: Image.Image) -> Image.Image:
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if _has_alpha_channel(img) else "RGB")
    return img


def _decode_source(source: Path | bytes | Image.Image) -> Image.Image:
    _require_pillow()
    if isinstance(source, Image.Image):
        return source.copy()
    if isinstance(source, bytes):
        return Image.open(BytesIO(source))
    return Image.open(Path(source))


def image_display_size(image: Image.Image) -> tuple[int, int]:
    """Geometry after EXIF orientation, without changing source bytes or pixels."""
    width, height = image.size
    return (height, width) if image.getexif().get(274) in (5, 6, 7, 8) else (width, height)


def convert_image_bytes_to_png(content: bytes) -> bytes:
    """Convert arbitrary image bytes to PNG bytes."""

    _require_pillow()
    try:
        with Image.open(BytesIO(content)) as img:
            normalized = _png_safe_image(img)
            out = BytesIO()
            normalized.save(out, format="PNG")
            return out.getvalue()
    except Exception as exc:
        raise ValueError("Invalid image") from exc


def save_project_image(source: Path | bytes | Image.Image, output_path: Path) -> Path:
    """Store project master assets as real PNG files."""

    _require_pillow()
    final_path = Path(output_path).with_suffix(".png")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _decode_source(source) as img:
            normalized = _png_safe_image(img)
            normalized.save(final_path, format="PNG")
        return final_path
    except Exception as exc:
        raise ValueError("Invalid image") from exc


def save_provider_output_image(source: Path | bytes | Image.Image, output_path: Path) -> Path:
    """Store provider output as PNG without changing its pixel dimensions."""

    return save_project_image(source, output_path)


def image_file_metadata(path: Path | str) -> dict[str, Any]:
    try:
        _require_pillow()
        with Image.open(Path(path)) as img:
            width, height = int(img.width), int(img.height)
        return {
            "width": width,
            "height": height,
            "aspectRatio": _aspect_ratio_from_size(width, height),
        }
    except Exception:
        return {}


def image_bytes_metadata(content: bytes) -> dict[str, Any]:
    try:
        _require_pillow()
        with Image.open(BytesIO(content)) as img:
            width, height = int(img.width), int(img.height)
        return {
            "width": width,
            "height": height,
            "aspectRatio": _aspect_ratio_from_size(width, height),
        }
    except Exception:
        return {}


def image_has_provider_png_transparency(source: Path | str | bytes | Image.Image) -> bool:
    try:
        _require_pillow()
        raw_source = Path(source) if isinstance(source, str) else source
        with _decode_source(raw_source) as img:
            normalized = ImageOps.exif_transpose(img)
            return _has_provider_png_transparency(normalized)
    except Exception:
        return False


def prepare_provider_image_bytes(
    source: Path | str | bytes | Image.Image,
    *,
    purpose: str = "provider",
    max_long_edge: int = _MAX_LONG_EDGE,
    max_bytes: int | None = PROVIDER_IMAGE_INPUT_DEFAULT_MAX_BYTES,
    jpeg_quality: int = _PROVIDER_JPEG_QUALITY,
    preserve_alpha: bool = False,
) -> PreparedProviderImageBytes:
    """Prepare provider input bytes, defaulting to JPEG transport."""

    _require_pillow()
    raw_source = Path(source) if isinstance(source, str) else source
    try:
        with _decode_source(raw_source) as img:
            img = ImageOps.exif_transpose(img)
            original_width, original_height = img.size
            next_width, next_height = _fit_long_edge(
                original_width, original_height, max_long_edge
            )
            resized = (next_width, next_height) != (original_width, original_height)
            if resized:
                img = img.resize((next_width, next_height), Image.Resampling.LANCZOS)

            if preserve_alpha and _has_provider_png_transparency(img):
                prepared_mime = _PNG_MIME
                prepared = _png_safe_image(img)
                prepared, data, byte_resized = _png_under_byte_limit(prepared, max_bytes)
                return PreparedProviderImageBytes(
                    data=data,
                    prepared_mime=prepared_mime,
                    original_width=original_width,
                    original_height=original_height,
                    prepared_width=prepared.size[0],
                    prepared_height=prepared.size[1],
                    resized=resized or byte_resized,
                    transcoded=True,
                    purpose=purpose,
                    jpeg_quality=None,
                    max_long_edge=max_long_edge,
                    max_bytes=max_bytes,
                )

            prepared = img.convert("RGBA") if _has_alpha_channel(img) else img.convert("RGB")
            if prepared.mode == "RGBA":
                background = Image.new("RGB", prepared.size, (255, 255, 255))
                background.paste(prepared, mask=prepared.getchannel("A"))
                prepared = background
            else:
                prepared = prepared.convert("RGB")

            prepared, data, byte_resized, final_quality = _jpeg_under_byte_limit(
                prepared,
                jpeg_quality,
                max_bytes,
            )
            return PreparedProviderImageBytes(
                data=data,
                prepared_mime=_JPEG_MIME,
                original_width=original_width,
                original_height=original_height,
                prepared_width=prepared.size[0],
                prepared_height=prepared.size[1],
                resized=resized or byte_resized,
                transcoded=True,
                purpose=purpose,
                jpeg_quality=final_quality,
                max_long_edge=max_long_edge,
                max_bytes=max_bytes,
            )
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise ValueError("Invalid image") from exc


def prepare_provider_image_data_uri(
    source: Path | str | bytes | Image.Image,
    *,
    purpose: str = "provider-data-uri",
    max_long_edge: int = _MAX_LONG_EDGE,
    max_bytes: int | None = PROVIDER_IMAGE_INPUT_DEFAULT_MAX_BYTES,
    jpeg_quality: int = _PROVIDER_JPEG_QUALITY,
    preserve_alpha: bool = False,
    defer_video_preparation: bool = False,
) -> str:
    if defer_video_preparation:
        # Video requests share one final byte budget; retain the original here.
        raw_source = Path(source) if isinstance(source, str) else source
        with _decode_source(raw_source) as img:
            mime = Image.MIME.get(img.format)
            if mime and not isinstance(raw_source, Image.Image):
                raw = raw_source if isinstance(raw_source, bytes) else raw_source.read_bytes()
                return data_url_from_bytes(mime, raw)
            out = BytesIO()
            _png_safe_image(img).save(out, format="PNG")
            return data_url_from_bytes(_PNG_MIME, out.getvalue())
    prepared = prepare_provider_image_bytes(
        source,
        purpose=purpose,
        max_long_edge=max_long_edge,
        max_bytes=max_bytes,
        jpeg_quality=jpeg_quality,
        preserve_alpha=preserve_alpha,
    )
    return prepared.data_url
