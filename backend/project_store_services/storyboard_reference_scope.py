# -*- coding: utf-8 -*-
"""Select only assets visible in the frozen starting frames of a storyboard group."""
from __future__ import annotations

import copy
from typing import Any


_SLOT_KINDS = {
    "character_reference": "characters", "creature_reference": "creatures",
    "scene_reference": "scenes", "prop_reference": "props",
}
_TYPE_KINDS = {
    "character": "characters", "characters": "characters",
    "creature": "creatures", "creatures": "creatures",
    "scene": "scenes", "scenes": "scenes",
    "prop": "props", "props": "props",
}


def storyboard_start_asset_ids(panels: list[dict[str, Any]]) -> dict[str, set[str]] | None:
    """Use legacy visibleAssets only when a saved shot has no start subset."""
    allowed = {kind: set() for kind in ("characters", "creatures", "scenes", "props")}
    if not panels:
        return None
    for panel in panels:
        start = panel.get("startVisibleAssets")
        visible = start if isinstance(start, dict) else panel.get("visibleAssets")
        if not isinstance(visible, dict):
            return None  # Historical plans without visibility data retain their bindings.
        for kind in allowed:
            ids = visible.get(kind)
            if isinstance(ids, list):
                allowed[kind].update(str(item) for item in ids if str(item).strip())
    return allowed


def storyboard_reference_is_start_visible(row: dict[str, Any], allowed: dict[str, set[str]] | None) -> bool:
    if allowed is None:
        return True
    slot = str(row.get("slot") or "").strip().casefold()
    if slot in {"style_reference", "custom_image", "visual_handoff_reference"}:
        return True
    kind = _SLOT_KINDS.get(slot) or _TYPE_KINDS.get(str(row.get("assetType") or "").strip().casefold())
    asset_id = str(row.get("assetId") or "").strip()
    if kind:
        return bool(asset_id and asset_id in allowed[kind])
    if asset_id:
        return any(asset_id in ids for ids in allowed.values())
    return True  # Style, visual handoff and user reference images are not scene assets.


def scope_storyboard_reference_manifest(
    panels: list[dict[str, Any]], manifest: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    allowed = storyboard_start_asset_ids(panels)
    kept, excluded = [], []
    for row in manifest:
        if not isinstance(row, dict):
            continue
        (kept if storyboard_reference_is_start_visible(row, allowed) else excluded).append(copy.deepcopy(row))
    visual_prefixes = {"character_reference": "R", "creature_reference": "B",
                       "scene_reference": "S", "prop_reference": "P",
                       "style_reference": "V", "visual_handoff_reference": "H"}
    visual_counts: dict[str, int] = {}
    for index, row in enumerate(kept, start=1):
        row["refId"] = f"R{index:02d}"
        prefix = visual_prefixes.get(str(row.get("slot") or ""))
        if prefix and row.get("visualId"):
            visual_counts[prefix] = visual_counts.get(prefix, 0) + 1
            row["visualId"] = f"{prefix}{visual_counts[prefix]:02d}"
    return kept, excluded


def scope_storyboard_reference_images(
    panels: list[dict[str, Any]], manifest: list[dict[str, Any]],
    excluded_ids: list[str], references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match transport images to the same starting-frame scope as the prompt."""
    allowed = storyboard_start_asset_ids(panels)
    kept_tokens = {str(row.get(key) or "").strip() for row in manifest if isinstance(row, dict)
                   for key in ("mediaId", "assetId")}
    kept_tokens.discard("")
    excluded_tokens = set(excluded_ids)
    selected: list[dict[str, Any]] = []
    for reference in references:
        tokens = {str(reference.get(key) or "").strip() for key in (
            "requestedReferenceId", "mediaId", "assetId", "versionId",
        )}
        if tokens & kept_tokens or (not tokens & excluded_tokens
                                   and storyboard_reference_is_start_visible(reference, allowed)):
            selected.append(reference)
    return selected
