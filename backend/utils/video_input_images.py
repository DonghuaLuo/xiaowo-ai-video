"""One quality-bounded image preparation pass over the final video request."""

from __future__ import annotations

import base64
import json
import math
from io import BytesIO
from typing import Any

from PIL import Image, ImageOps

from utils.image_pipeline import data_url_from_bytes, image_display_size
from utils.video_model_capabilities import video_model_capability

MIN_DIMENSION_SCALE = 0.75
HD_SHORT_EDGE = 720
MIN_JPEG_QUALITY = 85


def minimum_media_scale(width: int, height: int, minimum_side: int = 0) -> float:
    """Do not downsize existing sub-HD media or turn HD media into sub-HD."""
    return max(MIN_DIMENSION_SCALE, min(HD_SHORT_EDGE, width, height) / min(width, height),
               minimum_side / min(width, height))


def request_body_bytes(body: dict[str, Any]) -> int:
    # ASCII escaping also bounds SDK serializers; HTTP uses smaller UTF-8 JSON.
    return len(json.dumps(body, ensure_ascii=True, allow_nan=False).encode("utf-8"))


def _image_fields(body: dict[str, Any]) -> list[tuple[Any, Any, str]]:
    if isinstance(body.get("metadata"), dict) and "images" not in body:
        return _image_fields(body["metadata"])
    if "first_frame_url" in body or "last_frame_url" in body:
        return [(body, key, role) for key, role in (("first_frame_url", "first_frame"), ("last_frame_url", "last_frame")) if key in body]
    if "image_list" in body:
        return [(row, "image", {"end_frame": "last_frame", "first_frame": "first_frame"}.get(row.get("type"), "reference_image"))
                for row in body["image_list"]]
    if "input_reference" in body or "image_tail" in body:
        return [(body, key, role) for key, role in (("input_reference", "first_frame"), ("image_tail", "last_frame")) if key in body]
    if "image_url" in body or "reference_image_urls" in body:
        return ([(body, "image_url", "first_frame")] if "image_url" in body else []) + [
            (body["reference_image_urls"], index, "reference_image") for index in range(len(body.get("reference_image_urls", [])))
        ]
    if "content" in body:
        return [(row["image_url"], "url", row.get("role", "reference_image"))
                for row in body["content"] if row.get("type") == "image_url"]
    if "input" in body:
        return [(row, "url", row["type"]) for row in body["input"].get("media", [])
                if row.get("type") in {"reference_image", "first_frame", "last_frame"}]
    if any(key in body for key in ("image", "last_frame", "reference_images")):
        return ([(body[key], "url", role) for key, role in (("image", "first_frame"), ("last_frame", "last_frame")) if key in body]
                + [(row, "url", "reference_image") for row in body.get("reference_images", [])])
    return [(body["images"], index, "reference_image") for index in range(len(body.get("images", [])))]


def _image_size_options(source: dict[str, Any], scale: float, limits: dict[str, Any]) -> list[tuple[int, int]]:
    applied = min(source["ceiling"], max(source["floor"], scale))
    minimum_width = math.ceil(source["width"] * source["floor"])
    minimum_height = math.ceil(source["height"] * source["floor"])
    width = max(minimum_width, int(source["width"] * applied))
    height = max(minimum_height, int(source["height"] * applied))
    options = [
        (w, h) for w in range(width - 1, width + 2) for h in range(height - 1, height + 2)
        if minimum_width <= w <= min(source["width"], limits.get("max_side") or source["width"])
        and minimum_height <= h <= min(source["height"], limits.get("max_side") or source["height"])
        and limits.get("min_ratio", 0) <= w / h <= limits.get("max_ratio", math.inf)
    ]
    # Keep the current rung unchanged unless rounding violates a constraint.
    return sorted(options, key=lambda size: (
        size != (width, height), abs(size[0] / size[1] - source["width"] / source["height"]),
    ))


def prepare_video_request_images(
    body: dict[str, Any], model_name: str, *, image_roles: list[str] | None = None,
    capability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mutate transport copies only. Never drop images or alter prompt/roles/audio."""
    spec = capability if capability is not None else video_model_capability(model_name) or {}
    adapter = spec.get("adapter_capabilities") or {}
    limits = adapter.get("reference_image_limits") or {}
    label = spec.get("title") or model_name
    body_limit = int(adapter.get("request_body_max_bytes") or 0)
    image_limit = int(limits.get("max_bytes") or 20 * 1024 * 1024)
    fields = _image_fields(body)
    if image_roles is not None:
        if len(image_roles) != len(fields):
            raise RuntimeError("视频输入图片与首尾帧用途数量不一致，已中断生成")
        fields = [(container, key, role) for (container, key, _), role in zip(fields, image_roles)]
    sources = []
    for index, (container, key, role) in enumerate(fields, 1):
        url = str(container[key])
        try:
            if not url.startswith("data:image/"):
                raise ValueError("image data URL required")
            raw = base64.b64decode(url.split(",", 1)[1], validate=True)
            with Image.open(BytesIO(raw)) as opened:
                width, height = image_display_size(opened)
                img = ImageOps.exif_transpose(opened)
                has_alpha = "A" in img.getbands() or "transparency" in img.info
                alpha = has_alpha and img.convert("RGBA").getchannel("A").getextrema()[0] < 255
                orientation = opened.getexif().get(274, 1)
                original_format = opened.format
        except Exception as exc:
            raise RuntimeError(f"{label}第 {index} 张输入图片无法读取，请重新关联本地图片") from exc
        minimum = int(limits.get("min_side") or 0)
        ratio = width / height
        if min(width, height) < minimum:
            raise RuntimeError(f"{label}输入图片短边至少 {minimum} 像素，第 {index} 张为 {width}×{height}，请更换清晰图片")
        if ratio < limits.get("min_ratio", 0) or ratio > limits.get("max_ratio", math.inf):
            raise RuntimeError(f"{label}第 {index} 张输入图片的宽高比不符合模型要求，请更换图片")
        floor = minimum_media_scale(width, height, minimum)
        ceiling = min(1.0, int(limits.get("max_side") or max(width, height)) / max(width, height))
        if ceiling + 1e-9 < floor:
            raise RuntimeError(
                f"{label}第 {index} 张图片为 {width}×{height}，模型尺寸上限要求缩小到原图的 {ceiling:.1%}，"
                "低于清晰度保护下限（宽高至少保留 75%，高清短边不低于 720）。已中断生成，请更换素材。"
            )
        sources.append(dict(raw=raw, url=url, width=width, height=height, alpha=alpha, has_alpha=has_alpha,
                            orientation=orientation, format=original_format, floor=floor, ceiling=ceiling))

    pair_range = adapter.get("native_frame_ratio_range")
    frame_indices = {role: index for index, (_, _, role) in enumerate(fields) if role in {"first_frame", "last_frame"}}
    frame_pair = (frame_indices["first_frame"], frame_indices["last_frame"]) if pair_range and len(frame_indices) == 2 else None
    if frame_pair:
        first, last = (sources[index] for index in frame_pair)
        original_pair_ratio = (first["width"] / first["height"]) / (last["width"] / last["height"])
        if not pair_range[0] - 1e-6 <= original_pair_ratio <= pair_range[1] + 1e-6:
            raise RuntimeError(f"{label}首尾帧画幅不兼容，请更换同画幅图片")
    original_size = request_body_bytes(body)
    candidates = [(1.0, quality) for quality in (100, 98, 96, 94, 92, 90, 88, 86, MIN_JPEG_QUALITY)]
    candidates += [(scale, MIN_JPEG_QUALITY) for scale in (0.95, 0.9, 0.85, 0.8, MIN_DIMENSION_SCALE)]
    last_sizes: list[int] = []
    metadata: list[dict[str, Any]] = []
    for attempt, (scale, quality) in enumerate(candidates):
        last_sizes, metadata = [], []
        options = [_image_size_options(source, scale, limits) for source in sources]
        if any(not sizes for sizes in options):
            raise RuntimeError(f"{label}图片无法在清晰度下限内满足尺寸和宽高比要求，请更换素材")
        sizes = [choices[0] for choices in options]
        if frame_pair:
            first_index, last_index = frame_pair
            valid_pairs = [
                (first, last) for first in options[first_index] for last in options[last_index]
                if pair_range[0] - 1e-6 <= (first[0] / first[1]) / (last[0] / last[1]) <= pair_range[1] + 1e-6
            ]
            if not valid_pairs:
                raise RuntimeError(f"{label}首尾帧无法在清晰度下限内满足配对比例，请更换同画幅图片")
            sizes[first_index], sizes[last_index] = valid_pairs[0]
        for (container, key, role), source, size in zip(fields, sources, sizes):
            width, height = size
            keep_alpha = source["alpha"] and limits.get("allow_alpha") is not False
            with Image.open(BytesIO(source["raw"])) as opened:
                img = ImageOps.exif_transpose(opened).convert("RGBA" if source["has_alpha"] else "RGB")
                if not keep_alpha and img.mode == "RGBA":
                    background = Image.new("RGB", img.size, "white")
                    background.paste(img, mask=img.getchannel("A"))
                    img = background
                if img.size != size:
                    img = img.resize(size, Image.Resampling.LANCZOS)
                out = BytesIO()
                if keep_alpha:
                    img.save(out, format="PNG", optimize=True)
                    mime = "image/png"
                else:
                    try:
                        img.save(out, format="JPEG", quality=quality, subsampling=0, optimize=True)
                    except OSError:
                        # Some Pillow/libjpeg builds exhaust the optimized encoder's
                        # buffer on high-entropy 4:4:4 images. Keep quality unchanged.
                        out = BytesIO()
                        img.save(out, format="JPEG", quality=quality, subsampling=0, optimize=False)
                    mime = "image/jpeg"
                encoded = out.getvalue()
            unchanged = size == (source["width"], source["height"]) and source["orientation"] == 1
            # Reuse only the transport format; opaque PNGs must first become JPEGs.
            can_keep = source["format"] == ("PNG" if keep_alpha else "JPEG") and (
                not source["has_alpha"] or keep_alpha
            )
            if unchanged and can_keep and len(source["raw"]) <= len(encoded):
                encoded, url = source["raw"], source["url"]
            else:
                url = data_url_from_bytes(mime, encoded)
            container[key] = url
            last_sizes.append(len(encoded))
            metadata.append({"originalWidth": source["width"], "originalHeight": source["height"],
                             "width": width, "height": height, "bytes": len(encoded)})
        final_size = request_body_bytes(body)
        if all(size <= image_limit for size in last_sizes) and (not body_limit or final_size <= body_limit):
            frame_ratios = {}
            for (_, _, role), item in zip(fields, metadata):
                ratio = item["width"] / item["height"]
                if ratio < limits.get("min_ratio", 0) or ratio > limits.get("max_ratio", math.inf):
                    raise RuntimeError(f"{label}压缩后的图片宽高比不符合模型要求，已中断生成，请更换素材")
                frame_ratios[role] = ratio
            pair_range = adapter.get("native_frame_ratio_range")
            if pair_range and "first_frame" in frame_ratios and "last_frame" in frame_ratios:
                ratio = frame_ratios["first_frame"] / frame_ratios["last_frame"]
                if not pair_range[0] - 1e-6 <= ratio <= pair_range[1] + 1e-6:
                    raise RuntimeError(f"{label}压缩后的首尾帧画幅不兼容，已中断生成，请更换同画幅图片")
            return {"originalRequestBytes": original_size, "requestBytes": final_size,
                    "attempts": attempt + 1, "jpegQuality": quality, "images": metadata}

    oversized = [f"第 {i} 张 {size / 1048576:.2f} MB" for i, size in enumerate(last_sizes, 1) if size >= image_limit]
    reason = (f"请求总大小 {final_size / 1048576:.2f} MB，上限 {body_limit / 1048576:g} MB"
              if body_limit and final_size >= body_limit else "")
    if oversized:
        reason += f"；单图上限 {image_limit / 1048576:g} MB：" + "、".join(oversized)
    raise RuntimeError(
        f"{label}输入素材压缩达到清晰度保护下限后仍超限：{reason}。"
        "宽高至少保留原图 75%，高清短边不低于 720，低于高清的原图不再缩小，JPEG 质量不低于 85。"
        "已中断生成，未删除任何素材；请减少关联图片、替换体积过大的素材或选择容量更大的模型。"
    )
