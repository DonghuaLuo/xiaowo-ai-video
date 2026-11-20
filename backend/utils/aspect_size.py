"""统一「比例优先、清晰度其次」的尺寸计算。"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_SHORT_EDGE = 720

IMAGE_TIER_SHORT_EDGE: dict[str, int] = {"512px": 512, "1K": 1024, "2K": 2048, "3K": 3072, "4K": 4096}
IMAGE_TIER_LONG_EDGE: dict[str, int] = {"512px": 512, "1K": 1024, "2K": 2048, "3K": 3072, "4K": 4096}
VIDEO_TIER_SHORT_EDGE: dict[str, int] = {
    "360p": 360,
    "480p": 480,
    "540p": 540,
    "720p": 720,
    "1024p": 1024,
    "1080p": 1080,
    "4K": 2160,
}

_DEFAULT_ASPECT: tuple[int, int] = (9, 16)
_WH_RE = re.compile(r"^\s*(\d+)\s*[xX×*]\s*(\d+)\s*$")
_RATIO_SEP_RE = re.compile(r"[:：]")

IMAGE_GENERATION_PRESETS: dict[str, dict[str, str]] = {
    "character": {
        "label": "角色图",
        "aspect_ratio": "16:9",
        "default_resolution": "2K",
        "summary": "横向角色设定图，优先展示角色脸部、服装、多视角和关键配饰。",
    },
    "scene": {
        "label": "场景图",
        "aspect_ratio": "3:2",
        "default_resolution": "2K",
        "summary": "横向环境资产图，优先展示空间关系、光线和场景层次。",
    },
    "prop": {
        "label": "道具图",
        "aspect_ratio": "2:1",
        "default_resolution": "1K",
        "summary": "横向宽幅道具设定图，优先展示主体结构、多视角和关键细节。",
    },
    "storyboard": {
        "label": "分镜图",
        "aspect_ratio": "16:9",
        "default_resolution": "2K",
        "summary": "多镜头故事板工作页，信息密度高，默认 2048x1152。",
    },
    "asset": {
        "label": "通用资产图",
        "aspect_ratio": "16:9",
        "default_resolution": "2K",
        "summary": "无法归类到角色、生物、场景或道具时使用的通用图片资产。",
    },
}

IMAGE_GENERATION_PRESET_ALIASES: dict[str, str] = {
    "asset": "asset",
    "assets": "asset",
    "generic": "asset",
    "generic_asset": "asset",
    "character": "character",
    "characters": "character",
    "role": "character",
    "roles": "character",
    "person": "character",
    "scene": "scene",
    "scenes": "scene",
    "environment": "scene",
    "environments": "scene",
    "landscape": "scene",
    "prop": "prop",
    "props": "prop",
    "object": "prop",
    "objects": "prop",
    "storyboard": "storyboard",
    "storyboards": "storyboard",
    "storyboard_image": "storyboard",
    "storyboard-sheet": "storyboard",
    "storyboard_sheet": "storyboard",
    "分镜图": "storyboard",
    "风景图": "storyboard",
}


def parse_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    """把 ``"9:16"`` 解析成约简互质的 ``(9, 16)``；非法值回退默认竖屏比例。"""
    try:
        parts = _RATIO_SEP_RE.split(aspect_ratio.strip())
        if len(parts) != 2:
            raise ValueError(aspect_ratio)
        aw, ah = int(parts[0]), int(parts[1])
        if aw <= 0 or ah <= 0:
            raise ValueError(aspect_ratio)
    except (AttributeError, ValueError, IndexError):
        logger.warning("无法解析 aspect_ratio=%r，回退默认 %d:%d", aspect_ratio, *_DEFAULT_ASPECT)
        return _DEFAULT_ASPECT
    g = math.gcd(aw, ah)
    return aw // g, ah // g


def aspect_size(
    aspect_ratio: str,
    short_edge: int,
    *,
    round_to: int = 16,
    max_long_edge: int | None = None,
    max_total_pixels: int | None = None,
    max_ratio: float | None = None,
) -> tuple[int, int]:
    """按比例 + 短边目标算出精确遵循比例、且被 ``round_to`` 整除的 ``(宽, 高)``。"""
    aw, ah = parse_aspect_ratio(aspect_ratio)

    if max_ratio is not None:
        ratio = max(aw / ah, ah / aw)
        if ratio > max_ratio + 1e-9:
            logger.warning(
                "aspect_ratio=%s 比例 %.2f 超出后端支持上限 %.2f，可能被 API 拒绝或裁剪",
                aspect_ratio,
                ratio,
                max_ratio,
            )

    short_comp = min(aw, ah)
    long_comp = max(aw, ah)
    short_unit = round_to * short_comp
    t = max(1, round(short_edge / short_unit))

    if max_long_edge is not None:
        max_t_long = max_long_edge // (round_to * long_comp)
        t = min(t, max(1, max_t_long))

    if max_total_pixels is not None:
        denom = aw * ah * round_to * round_to
        max_t_pixels = math.isqrt(max_total_pixels // denom) if denom > 0 else 0
        t = min(t, max(1, max_t_pixels))

    t = max(1, t)
    return aw * round_to * t, ah * round_to * t


def normalize_image_generation_preset(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "asset"
    return IMAGE_GENERATION_PRESET_ALIASES.get(text, IMAGE_GENERATION_PRESET_ALIASES.get(text.lower(), "asset"))


def image_generation_preset(value: Any) -> dict[str, str]:
    return dict(IMAGE_GENERATION_PRESETS[normalize_image_generation_preset(value)])


def image_default_aspect_ratio(value: Any) -> str:
    return image_generation_preset(value)["aspect_ratio"]


def image_default_resolution(value: Any) -> str:
    return image_generation_preset(value)["default_resolution"]


def aspect_size_from_long_edge(
    aspect_ratio: str,
    long_edge: int,
    *,
    round_to: int = 16,
    max_long_edge: int | None = None,
    max_total_pixels: int | None = None,
    max_ratio: float | None = None,
) -> tuple[int, int]:
    """按比例 + 长边目标算出精确遵循比例、且被 ``round_to`` 整除的 ``(宽, 高)``。"""
    aw, ah = parse_aspect_ratio(aspect_ratio)

    if max_ratio is not None:
        ratio = max(aw / ah, ah / aw)
        if ratio > max_ratio + 1e-9:
            logger.warning(
                "aspect_ratio=%s 比例 %.2f 超出后端支持上限 %.2f，可能被 API 拒绝或裁剪",
                aspect_ratio,
                ratio,
                max_ratio,
            )

    long_comp = max(aw, ah)
    long_unit = round_to * long_comp
    t = max(1, round(long_edge / long_unit))

    if max_long_edge is not None:
        max_t_long = max_long_edge // (round_to * long_comp)
        t = min(t, max(1, max_t_long))

    if max_total_pixels is not None:
        denom = aw * ah * round_to * round_to
        max_t_pixels = math.isqrt(max_total_pixels // denom) if denom > 0 else 0
        t = min(t, max(1, max_t_pixels))

    t = max(1, t)
    return aw * round_to * t, ah * round_to * t


def resolution_to_long_edge(
    resolution: str | None,
    *,
    tier_map: dict[str, int] | None = None,
    default_long: int = 1024,
) -> int:
    """把图片分辨率规范化成长边像素；1K/2K/3K/4K 均以长边为锚点。"""
    if resolution is None:
        return default_long
    text = resolution.strip()
    if not text:
        return default_long

    normalized = {key.lower(): value for key, value in (tier_map or IMAGE_TIER_LONG_EDGE).items()}
    if text.lower() in normalized:
        return normalized[text.lower()]

    match = _WH_RE.match(text)
    if match:
        return max(int(match.group(1)), int(match.group(2)))

    if text.isdigit():
        return int(text)

    logger.warning("无法解析 image resolution=%r，回退默认长边 %d", resolution, default_long)
    return default_long


def image_size_for_resolution(
    resolution: str | None,
    aspect_ratio: str | None,
    *,
    default_resolution: str = "1K",
    default_long_edge: int | None = None,
    round_to: int = 16,
    max_long_edge: int | None = None,
    max_total_pixels: int | None = None,
    max_ratio: float | None = None,
) -> tuple[int, int]:
    """图片生成唯一尺寸换算入口：K 档取长边，再按业务比例计算宽高并应用上限。"""
    default_long = default_long_edge or resolution_to_long_edge(
        default_resolution,
        tier_map=IMAGE_TIER_LONG_EDGE,
        default_long=1024,
    )
    requested = str(resolution or "").strip()
    long_edge = (
        resolution_to_long_edge(requested, tier_map=IMAGE_TIER_LONG_EDGE, default_long=default_long)
        if requested
        else default_long
    )
    return aspect_size_from_long_edge(
        str(aspect_ratio or ""),
        long_edge,
        round_to=round_to,
        max_long_edge=max_long_edge,
        max_total_pixels=max_total_pixels,
        max_ratio=max_ratio,
    )


def image_size_for_preset(
    preset: Any,
    resolution: str | None = None,
    *,
    round_to: int = 16,
    max_long_edge: int | None = None,
    max_total_pixels: int | None = None,
    max_ratio: float | None = None,
) -> tuple[int, int]:
    row = image_generation_preset(preset)
    return image_size_for_resolution(
        resolution or row["default_resolution"],
        row["aspect_ratio"],
        default_resolution=row["default_resolution"],
        round_to=round_to,
        max_long_edge=max_long_edge,
        max_total_pixels=max_total_pixels,
        max_ratio=max_ratio,
    )


def resolution_to_short_edge(
    resolution: str | None,
    *,
    tier_map: dict[str, int],
    default_short: int = DEFAULT_SHORT_EDGE,
) -> int:
    """把分辨率规范化成短边像素；自定义 ``宽*高`` 只取短边，比例仍由项目决定。"""
    if resolution is None:
        return default_short
    text = resolution.strip()
    if not text:
        return default_short

    normalized = {key.lower(): value for key, value in tier_map.items()}
    if text.lower() in normalized:
        return normalized[text.lower()]

    match = _WH_RE.match(text)
    if match:
        return min(int(match.group(1)), int(match.group(2)))

    if text.isdigit():
        return int(text)

    logger.warning("无法解析 resolution=%r，回退默认短边 %d", resolution, default_short)
    return default_short
