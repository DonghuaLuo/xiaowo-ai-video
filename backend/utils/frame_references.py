"""Frame asset semantics and capability-based video input selection."""

from __future__ import annotations

from typing import Any

FRAME_IMAGE = "frame_image"
FRAME_SLOT = "frame_reference"
FRAME_ROLES = ("first_frame", "last_frame")


def is_frame_image(row: Any) -> bool:
    return isinstance(row, dict) and any(
        row.get(key) in (FRAME_IMAGE, FRAME_SLOT)
        for key in ("assetType", "assetKind", "mediaPurpose", "preferredTargetSlot", "slot", "targetSlot")
    )


def frame_options(row: dict[str, Any]) -> dict[str, Any]:
    role = row.get("frameRole", "first_frame")
    if role not in FRAME_ROLES:
        raise ValueError("帧画面用途只能选择首帧或尾帧")
    return {"frameRole": role, "useNativeFrame": row.get("useNativeFrame", True) is not False}


def frame_reference_brief(role: str, *, storyboard: bool = False) -> str:
    if storyboard:
        return (
            "末镜头视觉目标，按分镜脚本趋近图中姿态、位置、朝向与光影，不改变剧情。"
            if role == "last_frame" else
            "首镜头视觉延续参考，按分镜脚本延续姿态、位置、朝向与光影，不改变剧情。"
        )
    return (
        "结尾画面参考，使末镜头自然趋近该画面。"
        if role == "last_frame" else
        "开场画面参考，延续人物姿态、空间关系与光影。"
    )


def select_frame_transport(
    references: list[dict[str, Any]], capability: dict[str, Any], *,
    reference_video_count: int = 0, native_required: bool = False, allow_incomplete: bool = False,
) -> dict[str, Any]:
    """Match one mode; drafts may omit required inputs, but never exceed its limits."""
    adapter = capability.get("adapter_capabilities") or {}
    visual = adapter.get("keyframe_visual_inputs" if native_required else "visual_inputs") or {}
    candidates = [
        index for index, row in enumerate(references)
        if is_frame_image(row) and frame_options(row)["useNativeFrame"]
    ]
    roles = [frame_options(row)["frameRole"] for row in references if is_frame_image(row)]
    if len(roles) != len(set(roles)):
        raise ValueError("每个任务最多关联一张首帧和一张尾帧，请调整帧画面用途")
    if native_required and ((not allow_incomplete and "first_frame" not in roles) or len(candidates) != len(roles)):
        raise ValueError("首尾帧视频生成必须关联并开启原生首帧；尾帧也必须使用原生约束")
    # At most two frame associations exist, so enumerate subsets to allow a
    # supported native first frame alongside a prompted last frame.
    subsets = [((1 << len(candidates)) - 1)] if native_required else sorted(range(1 << len(candidates)), key=int.bit_count, reverse=True)
    for mask in subsets:
        native = {candidates[i]: frame_options(references[candidates[i]])["frameRole"]
                  for i in range(len(candidates)) if mask & (1 << i)}
        counts = {"first_frame": 0, "last_frame": 0, "reference_image": len(references) - len(native), "reference_video": reference_video_count}
        for role in native.values():
            counts[role] += 1
        for mode in visual.get("modes", []):
            limits = mode.get("max_counts") or {}
            # Storyboard video keeps image-reference semantics even when a card
            # currently has no storyboard attached. Never switch to a separate
            # native-frame-only mode just because other images were removed.
            if not native_required and not int(limits.get("reference_image", 0)):
                continue
            if any(count > int(limits.get(role, 0)) for role, count in counts.items()):
                continue
            if not allow_incomplete and any(not counts.get(role) for role in mode.get("required_roles", [])):
                continue
            minimum = 0 if allow_incomplete else int(mode.get("min_reference_materials", 0))
            if not minimum <= counts["reference_image"] + reference_video_count <= int(mode.get("max_reference_materials", 0)):
                continue
            return {"mode": mode["id"], "nativeRoles": native}
    if native_required:
        raise ValueError("当前模型不支持这组原生首尾帧与参考图/视频输入；请调整素材或切换模型")
    raise ValueError("当前图片组合超出模型能力，请减少参考图或切换模型；系统不会丢弃已关联图片")
