# -*- coding: utf-8 -*-
"""Reference identity helpers shared by planning and provider calls."""

from __future__ import annotations

import re
from typing import Any, Iterable


ASSET_REF_COLLECTIONS = ("characters", "creatures", "scenes", "props")
SHORT_ASSET_ID_PREFIX_BY_TYPE = {
    "characters": "c",
    "creatures": "b",
    "scenes": "s",
    "props": "p",
}
SHORT_ASSET_CANDIDATE_ID_PREFIX_BY_TYPE = {
    "characters": "cc",
    "creatures": "cb",
    "scenes": "cs",
    "props": "cp",
}


def next_short_asset_id(asset_type: Any, existing_ids: Iterable[Any] | None = None) -> str:
    prefix = SHORT_ASSET_ID_PREFIX_BY_TYPE.get(str(asset_type or "").strip(), "")
    if not prefix:
        raise ValueError(f"Unsupported short asset id type: {asset_type}")
    max_number = 0
    for value in existing_ids or []:
        text = str(value or "").strip()
        match = re.fullmatch(rf"{re.escape(prefix)}(\d+)", text)
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"{prefix}{max_number + 1:03d}"


def short_asset_candidate_id(asset_type: Any, index: Any) -> str:
    prefix = SHORT_ASSET_CANDIDATE_ID_PREFIX_BY_TYPE.get(str(asset_type or "").strip(), "")
    if not prefix:
        raise ValueError(f"Unsupported short asset candidate id type: {asset_type}")
    return f"{prefix}{max(1, int(index)):03d}"


def is_short_asset_candidate_id(asset_type: Any, value: Any) -> bool:
    prefix = SHORT_ASSET_CANDIDATE_ID_PREFIX_BY_TYPE.get(str(asset_type or "").strip(), "")
    text = str(value or "").strip()
    return bool(prefix and re.fullmatch(rf"{re.escape(prefix)}\d{{3,}}", text))


def asset_row_ids(rows: Iterable[Any] | None) -> list[str]:
    result: list[str] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("id") or "").strip()
        if text:
            result.append(text)
    return result


def dedupe_reference_tokens(tokens: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        text = str(token or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def asset_refs_has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return any(asset_refs_has_value(item) for item in value)
    if isinstance(value, dict):
        return any(asset_refs_has_value(item) for item in value.values())
    return True


def asset_ref_tokens(value: Any) -> list[str]:
    tokens: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        for item in value:
            tokens.extend(asset_ref_tokens(item))
        return dedupe_reference_tokens(tokens)
    if isinstance(value, dict):
        link_like = any(
            key in value
            for key in (
                "inputLinkId",
                "input_link_id",
                "sourceNodeId",
                "source_node_id",
                "targetNodeId",
                "target_node_id",
                "targetSlot",
                "target_slot",
                "linkAction",
                "visibilityScope",
                "sourceType",
                "source_type",
            )
        )
        token_keys = ["rootAssetId", "assetId"]
        if not link_like:
            token_keys.append("id")
        for key in token_keys:
            text = str(value.get(key) or "").strip()
            if text:
                tokens.append(text)
        return dedupe_reference_tokens(tokens)
    return []


def asset_ref_canonical_tokens(value: Any) -> list[str]:
    return asset_ref_tokens(value)


def asset_reference_ids_from_refs(value: Any) -> list[str]:
    if isinstance(value, dict) and any(key in value for key in ASSET_REF_COLLECTIONS):
        tokens: list[str] = []
        for key in ASSET_REF_COLLECTIONS:
            tokens.extend(asset_ref_tokens(value.get(key)))
        return dedupe_reference_tokens(tokens)
    return dedupe_reference_tokens(asset_ref_tokens(value))


def asset_canonical_reference_ids_from_refs(value: Any) -> list[str]:
    if isinstance(value, dict) and any(key in value for key in ASSET_REF_COLLECTIONS):
        tokens: list[str] = []
        for key in ASSET_REF_COLLECTIONS:
            tokens.extend(asset_ref_canonical_tokens(value.get(key)))
        return dedupe_reference_tokens(tokens)
    return dedupe_reference_tokens(asset_ref_canonical_tokens(value))


def merge_reference_ids(*values: Any) -> list[str]:
    tokens: list[str] = []
    for value in values:
        if value is None:
            continue
        tokens.extend(asset_reference_ids_from_refs(value))
    return dedupe_reference_tokens(tokens)


def asset_reference_ids_from_generation_sources(*sources: Any) -> list[str]:
    tokens: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("assetRefs", "asset_refs"):
            refs = source.get(key)
            if asset_refs_has_value(refs):
                tokens.extend(asset_reference_ids_from_refs(refs))
    return dedupe_reference_tokens(tokens)


def workflow_media_identity_values(
    node: dict[str, Any] | None,
    data: dict[str, Any] | None,
    media: dict[str, Any] | None,
) -> set[str]:
    identities: set[str] = set()

    def add_values(source: dict[str, Any] | None, keys: tuple[str, ...]) -> None:
        if not isinstance(source, dict):
            return
        for key in keys:
            text = str(source.get(key) or "").strip()
            if text:
                identities.add(text)

    node_keys = ("id", "nodeId", "node_id")
    media_keys = (
        "mediaVersionId",
        "media_version_id",
        "sourceVersionId",
        "source_version_id",
        "versionId",
        "version_id",
        "mediaId",
        "media_id",
        "relativePath",
        "relative_path",
        "file",
        "filePath",
        "file_path",
        "path",
    )
    add_values(node, node_keys)
    add_values(data, media_keys)
    add_values(media, ("id", *media_keys))
    add_values(media.get("metadata") if isinstance(media, dict) else None, media_keys)
    return identities
