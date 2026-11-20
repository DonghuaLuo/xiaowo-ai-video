"""Map editor mentions and canonical prompt tokens to stable reference identities."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

MENTION_PATTERN = re.compile(r"@\[([^\[\]\r\n]+)\]")
# Numbered videos are a reference protocol, not natural-language name detection.
PROMPT_REFERENCE_PATTERN = re.compile(r"@\[([^\[\]\r\n]+)\]|(?<!<)<([^<>\r\n]+)>(?!>)|[@＠]?参考视频[ \t]*([0-9]+)")
NAMED_KINDS = {"character", "scene", "prop", "creature"}


def prompt_reference_label(match: re.Match[str]) -> str:
    return match.group(1) or match.group(2) or f"参考视频{int(match.group(3))}"


def prompt_reference_labels(text: str, *additional_texts: str) -> list[str]:
    return list(dict.fromkeys(
        prompt_reference_label(match)
        for field_text in (text, *additional_texts)
        for match in PROMPT_REFERENCE_PATTERN.finditer(field_text)
    ))


def canonicalize_editor_mentions(text: str) -> str:
    """Keep editor @[...] markers out of stored and Agent-facing prompt prose."""
    converted = MENTION_PATTERN.sub(lambda match: f"<{match.group(1)}>", text)
    if "@[" in converted:
        raise ValueError("提示词包含未完成或格式错误的资产引用，请补全或删除引用记号")
    return converted


def prompt_mention_label(label: str) -> str:
    """Use one protocol-safe spelling in model inputs, editor labels and submission."""
    return re.sub(r"\s+", " ", label).strip().translate(str.maketrans({"[": "［", "]": "］", "<": "＜", ">": "＞"}))


def with_prompt_mentions(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in manifest]
    for row in rows:
        slot = str(row.get("slot") or "")
        asset_type = str(row.get("assetType") or "")
        if row.get("kind") == "video":
            kind, label = "video", str(row.get("referenceLabel") or "")
        elif slot == "custom_image" or asset_type == "custom_image":
            kind, label = "custom_image", str(row.get("displayName") or row.get("referenceLabel") or "自定义图片")
        elif row.get("frameRole") or slot in {"frame_reference", "first_frame", "last_frame"} or asset_type == "frame_image" or row.get("transportRole") in {"first_frame", "last_frame"}:
            kind = "frame"
            label = "尾帧" if (row.get("frameRole") or row.get("transportRole") or slot) == "last_frame" else "首帧"
        elif slot == "visual_handoff_reference" or asset_type == "visual_handoff":
            kind, label = "handoff", "视觉交接图"
        elif slot == "storyboard_image" or asset_type in {"storyboard", "storyboard_image"}:
            kind, label = "storyboard", "分镜图"
        else:
            kind = next((value for value in sorted(NAMED_KINDS) if slot == f"{value}_reference" or asset_type == value), "image")
            label = str(row.get("displayName") or row.get("referenceLabel") or "参考图") if kind in NAMED_KINDS else str(row.get("referenceLabel") or "参考图")
        key = f"asset:{row['assetId']}" if kind in NAMED_KINDS and row.get("assetId") else f"{kind}:{row.get('identity') or ''}"
        label = prompt_mention_label(label)
        row.update(mentionKind=kind, mentionKey=key, mentionLabel=label)
        # Old duplicate source cards may still be bound in a saved prompt.
        # Resolve those IDs to this one row without adding duplicate model inputs.
        row["mentionAliasKeys"] = [f"{kind}:{source_id}" for source_id in row.get("referenceSourceNodeIds") or []
                                   if kind not in NAMED_KINDS and f"{kind}:{source_id}" != key]
    # Business names are authoritative; only repeated unnamed reference roles need numbering.
    labels = {row["mentionKey"]: row["mentionLabel"] for row in rows}
    named_keys = {row["mentionKey"] for row in rows if row["mentionKind"] in NAMED_KINDS}
    counts = Counter(labels.values())
    used = set(labels.values())
    for key in sorted(labels):
        label = labels[key]
        if key in named_keys or counts[label] < 2:
            continue
        number = 1
        while f"{label}（{number}）" in used:
            number += 1
        labels[key] = f"{label}（{number}）"
        used.add(labels[key])
    for row in rows:
        row["mentionLabel"] = labels[row["mentionKey"]]
    return rows


def merge_prompt_manifest(actual: list[dict[str, Any]], displayed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map every association to its submitted media index, including shared files."""
    def identities(row: dict[str, Any]) -> set[str]:
        return {str(row[key]) for key in ("identity", "sourceNodeId", "mediaId") if row.get(key)}

    def same_media(left: dict[str, Any], right: dict[str, Any]) -> bool:
        return bool(left.get("mediaId")) and all(
            (left.get(key) or "") == (right.get(key) or "")
            for key in ("kind", "mediaId", "mediaVersionId", "frameRole")
        )

    merged = []
    for row in actual:
        same_kind = [item for item in displayed if item.get("kind") == row.get("kind")]
        source = next((item for item in same_kind if row.get("identity") and item.get("identity") == row["identity"]), None)
        if source is None:
            candidates = [item for item in same_kind if identities(item) & identities(row)
                          and not (item.get("sourceNodeId") and row.get("sourceNodeId") and item["sourceNodeId"] != row["sourceNodeId"])]
            source = candidates[0] if len(candidates) == 1 else None
        if source is None and row.get("assetId"):
            candidates = [item for item in displayed if item.get("assetId") == row["assetId"] and item.get("kind") == row.get("kind")]
            source = candidates[0] if len(candidates) == 1 else None
        # Deduplicating media must not discard other enabled source identities.
        # Compare versions and frame roles too: the same file in a first-frame
        # slot and an ordinary reference slot are distinct transport inputs.
        sources = [source] if source is not None else []
        sources.extend(item for item in same_kind
                       if item is not source and same_media(source or row, item))
        for item in sources or [{}]:
            merged.append({**item, **row, **{
                key: item[key] for key in ("identity", "sourceNodeId", "assetId", "displayName", "slot", "assetType", "frameRole", "mediaVersionId", "referenceSourceNodeIds")
                if item.get(key)
            }})
    return with_prompt_mentions(merged)


def bind_prompt_mentions(text: str, bindings: Any, manifest: list[dict[str, Any]], *,
                        additional_texts: tuple[str, ...] = ()) -> dict[str, str]:
    """Bind newly authored mentions; never retarget an existing binding by name."""
    if not isinstance(bindings, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in bindings.items()):
        raise ValueError("视频提示词的资产引用绑定无效")
    available: dict[str, str] = {}
    for row in manifest:
        label, key = row["mentionLabel"], row["mentionKey"]
        previous = available.get(label)
        available[label] = key if previous is None or previous == key else ""
    videos = {row["mentionLabel"]: row["mentionKey"] for row in manifest if row.get("kind") == "video"}
    result = {}
    for field_text in (text, *additional_texts):
        for match in PROMPT_REFERENCE_PATTERN.finditer(field_text):
            label = prompt_reference_label(match)
            candidates = videos if match.group(3) is not None else available
            result[label] = bindings.get(label) or candidates.get(label, "")
    return result


def resolve_prompt_mentions(text: str, bindings: dict[str, str], manifest: list[dict[str, Any]], *, require_transport: bool = True, enabled_manifest: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    if "@[" in MENTION_PATTERN.sub("", text):
        raise ValueError("提示词包含未完成或格式错误的资产引用，请补全或删除引用记号")
    matches = list(PROMPT_REFERENCE_PATTERN.finditer(text))
    if not matches:
        return {}
    if not isinstance(bindings, dict):
        raise ValueError("视频提示词的资产引用绑定无效")
    bindings = bind_prompt_mentions(text, bindings, enabled_manifest or manifest)
    by_key = {row["mentionKey"]: row for row in manifest}
    for row in manifest:
        for alias in row.get("mentionAliasKeys") or []:
            by_key.setdefault(alias, row)
    enabled_keys = {key for row in enabled_manifest or [] for key in [row["mentionKey"], *row.get("mentionAliasKeys", [])]}
    resolved = {}
    for match in matches:
        label = prompt_reference_label(match)
        key = bindings.get(label, "")
        row = by_key.get(key)
        if row is None:
            if require_transport and key in enabled_keys:
                raise ValueError(f"提示词引用的「{label}」已启用，但没有可用参考素材，请补齐素材或禁用该资产")
            # A story may mention any subject without providing its reference.
            # Preserve the text and binding; never retarget it to a same-name asset.
            row = {"kind": "text", "mentionKey": key, "mentionLabel": label}
        elif (match.group(3) is not None and row.get("kind") != "video") or (require_transport and row.get("transportRole") == "unresolved"):
            raise ValueError(f"提示词引用的「{label}」已启用，但没有可用参考素材，请补齐素材或禁用该资产")
        resolved[label] = row
    return resolved


def bind_generated_prompt_mentions(
    text: str,
    manifest: list[dict[str, Any]],
    *,
    existing_mentions: dict[str, dict[str, Any]] | None = None,
    additional_texts: tuple[str, ...] = (),
) -> dict[str, str]:
    """Bind optional explicit references without requiring markers in generated prose."""
    existing = {label: row["mentionKey"] for label, row in (existing_mentions or {}).items()}
    bindings = bind_prompt_mentions(text, existing, manifest, additional_texts=additional_texts)
    for field_text in (text, *additional_texts):
        resolve_prompt_mentions(field_text, bindings, manifest, require_transport=False)
    return bindings


def agent_video_reference_options(manifest: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    """Expose canonical identity tokens, not editor syntax or supplier indexes."""
    assets: list[dict[str, str]] = []
    videos: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in manifest:
        key = str(row.get("mentionKey") or "")
        label = str(row.get("mentionLabel") or "")
        if not key or not label or key in seen:
            continue
        seen.add(key)
        if row.get("mentionKind") in NAMED_KINDS and row.get("assetId"):
            assets.append({"assetId": str(row["assetId"]), "token": f"<{label}>"})
        elif row.get("mentionKind") == "video":
            videos.append({"token": f"<{label}>"})
    return {"assetMentions": assets, "videoMentions": videos}


def validate_agent_video_shot_mentions(
    shots: list[dict[str, Any]], manifest: list[dict[str, Any]], *,
    existing_mentions: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Require canonical shot prose and resolvable explicit identity tokens."""
    keys = {str(row["mentionKey"]) for row in manifest if row.get("mentionKey")}
    for index, shot in enumerate(shots, start=1):
        prompt = str(shot.get("prompt") or "")
        if "@[" in prompt or MENTION_PATTERN.search(prompt):
            raise ValueError(f"镜头{index}使用了界面编辑标记；请改用 references 返回的 <资产名称> 正文格式")
        # Supplier image numbers are assembled from the enabled media at submit time.
        if re.search(r"参考图\s*[0-9０-９]+", prompt):
            raise ValueError(f"镜头{index}直接写了参考图编号；请只描述画面，并用可用的 <资产名称> 标记资产")
        bindings = bind_generated_prompt_mentions(prompt, manifest, existing_mentions=existing_mentions)
        for label in prompt_reference_labels(prompt):
            if bindings.get(label, "") not in keys:
                raise ValueError(f"镜头{index}的资产引用「{label}」无法绑定当前素材；请使用 references 返回的标记或改写为普通名称")
