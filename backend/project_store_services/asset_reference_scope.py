# -*- coding: utf-8 -*-
"""资产引用类型、当前分集范围、文本绑定与计划引用校验。"""
from __future__ import annotations

from .asset_text_contract import _asset_range_ids_from_row
from .context_resolver import context_provenance as _context_provenance
from .context_resolver import merge_asset_candidates as _merge_context_asset_candidates
from .context_resolver import resolve_work_context as _resolve_work_context
from .generation_input_context import _truthy_payload_flag
from .planning_contract import _asset_ref_tokens
from .planning_contract import _is_user_locked_item
from .planning_workflow_assets import _asset_ref_entries
from .planning_workflow_assets import _asset_row_canonical_identity_strings
from .planning_workflow_assets import _asset_row_display_name
from .planning_workflow_assets import _asset_row_identity_strings
from .planning_workflow_routes import _segment_route_specs
from .reference_utils import asset_canonical_reference_ids_from_refs as _asset_canonical_reference_ids_from_refs
from .reference_utils import asset_ref_canonical_tokens as _asset_ref_canonical_tokens
from .reference_utils import asset_refs_has_value as _asset_refs_has_value
from .reference_utils import dedupe_reference_tokens as _dedupe_reference_tokens
from .source_coverage import _asset_ranges_for_source_ref
from .source_coverage import _load_source_coverage
from .source_coverage import _source_ref_bounds
from .source_reference_scope import _episode_range_for_id
from .source_text_store import get_episode_source_text
from .store_core import ASSET_LIFECYCLE_ACTIVE
from .store_core import _read_json
from .video_task_card_references import _ASSET_REF_COLLECTIONS
from typing import Any
import copy
import re


def _asset_refs_from_plan_item(item: dict[str, Any]) -> Any:
    if "assetRefs" in item:
        return item.get("assetRefs")
    return item.get("asset_refs")


def _normalize_shot_plan_asset_refs(document: dict[str, Any]) -> dict[str, Any]:
    segments = document.get("segments")
    shots = document.get("shots")
    if not isinstance(segments, list) or not isinstance(shots, list):
        return document
    segment_refs: dict[str, Any] = {}
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment_id = str(segment.get("id") or segment.get("segmentId") or segment.get("segment_id") or "").strip()
        refs = _asset_refs_from_plan_item(segment)
        if segment_id and _asset_refs_has_value(refs):
            segment_refs[segment_id] = copy.deepcopy(refs)
    shot_refs_by_segment: dict[str, Any] = {}
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        segment_id = str(shot.get("segmentId") or shot.get("segment_id") or "").strip()
        refs = _asset_refs_from_plan_item(shot)
        if _asset_refs_has_value(refs):
            if segment_id and segment_id not in shot_refs_by_segment:
                shot_refs_by_segment[segment_id] = copy.deepcopy(refs)
            continue
        if segment_id and segment_id in segment_refs:
            shot["assetRefs"] = copy.deepcopy(segment_refs[segment_id])
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        refs = _asset_refs_from_plan_item(segment)
        if _asset_refs_has_value(refs):
            continue
        segment_id = str(segment.get("id") or segment.get("segmentId") or segment.get("segment_id") or "").strip()
        if segment_id and segment_id in shot_refs_by_segment:
            segment["assetRefs"] = copy.deepcopy(shot_refs_by_segment[segment_id])
    return document


_ASSET_REF_LABELS = {"characters": "角色", "creatures": "生物", "scenes": "场景", "props": "道具"}


def _asset_ref_collection_from_value(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"character", "characters", "role", "roles", "person", "people", "角色", "人物"}:
        return "characters"
    if normalized in {
        "creature",
        "creatures",
        "monster",
        "monsters",
        "beast",
        "beasts",
        "living",
        "organism",
        "生物",
        "怪物",
        "活体",
        "妖兽",
        "魔兽",
        "异兽",
        "灵兽",
    }:
        return "creatures"
    if normalized in {"scene", "scenes", "location", "locations", "setting", "场景", "地点"}:
        return "scenes"
    if normalized in {"prop", "props", "item", "items", "object", "objects", "道具", "物件"}:
        return "props"
    return ""


def _asset_ref_collection_from_slot(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized == "character_reference":
        return "characters"
    if normalized == "creature_reference":
        return "creatures"
    if normalized == "scene_reference":
        return "scenes"
    if normalized == "prop_reference":
        return "props"
    return ""


def _asset_ref_tokens_by_collection(value: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {key: [] for key in _ASSET_REF_COLLECTIONS}

    def add(collection: str, token: Any) -> None:
        text = str(token or "").strip()
        if collection in result and text:
            result[collection].append(text)

    def walk(ref: Any, collection_hint: str = "") -> None:
        if isinstance(ref, dict):
            collection = collection_hint
            for key in ("assetType", "asset_type", "collection", "type", "kind"):
                collection = collection or _asset_ref_collection_from_value(ref.get(key))
            for key in ("slot", "targetSlot", "target_slot", "sourceSlot", "source_slot"):
                collection = collection or _asset_ref_collection_from_slot(ref.get(key))

            handled_collection_key = False
            collection_keys = {
                "characters": ("characters", "characterRefs", "character_refs", "roles"),
                "creatures": ("creatures", "creatureRefs", "creature_refs", "monsters", "beasts"),
                "scenes": ("scenes", "sceneRefs", "scene_refs", "locations"),
                "props": ("props", "propRefs", "prop_refs"),
            }
            for asset_type, keys in collection_keys.items():
                for key in keys:
                    if key not in ref:
                        continue
                    handled_collection_key = True
                    walk(ref.get(key), asset_type)

            for key in ("assetRefs", "asset_refs", "items", "inputLinks", "input_links", "inputs"):
                if key in ref:
                    walk(ref.get(key), collection)

            if collection:
                for token in _asset_ref_tokens(ref):
                    add(collection, token)
            return
        if isinstance(ref, (list, tuple, set)):
            for item in ref:
                walk(item, collection_hint)
            return
        if collection_hint:
            for token in _asset_ref_tokens(ref):
                add(collection_hint, token)

    walk(value)
    return {key: _dedupe_reference_tokens(tokens) for key, tokens in result.items()}


def _asset_ref_canonical_tokens_by_collection(value: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {key: [] for key in _ASSET_REF_COLLECTIONS}

    def add(collection: str, token: Any) -> None:
        text = str(token or "").strip()
        if collection in result and text:
            result[collection].append(text)

    def walk(ref: Any, collection_hint: str = "") -> None:
        if isinstance(ref, dict):
            collection = collection_hint
            for key in ("assetType", "asset_type", "collection", "type", "kind"):
                collection = collection or _asset_ref_collection_from_value(ref.get(key))
            for key in ("slot", "targetSlot", "target_slot", "sourceSlot", "source_slot"):
                collection = collection or _asset_ref_collection_from_slot(ref.get(key))

            handled_collection_key = False
            collection_keys = {
                "characters": ("characters", "characterRefs", "character_refs", "roles"),
                "creatures": ("creatures", "creatureRefs", "creature_refs", "monsters", "beasts"),
                "scenes": ("scenes", "sceneRefs", "scene_refs", "locations"),
                "props": ("props", "propRefs", "prop_refs"),
            }
            for asset_type, keys in collection_keys.items():
                for key in keys:
                    if key not in ref:
                        continue
                    handled_collection_key = True
                    walk(ref.get(key), asset_type)

            for key in ("assetRefs", "asset_refs", "items", "inputLinks", "input_links", "inputs"):
                if key in ref:
                    walk(ref.get(key), collection)

            if collection:
                for token in _asset_ref_canonical_tokens(ref):
                    add(collection, token)
            return
        if isinstance(ref, (list, tuple, set)):
            for item in ref:
                walk(item, collection_hint)
            return
        if collection_hint:
            for token in _asset_ref_canonical_tokens(ref):
                add(collection_hint, token)

    walk(value)
    return {key: _dedupe_reference_tokens(tokens) for key, tokens in result.items()}


def _asset_ref_entries_by_collection(value: Any) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {key: [] for key in _ASSET_REF_COLLECTIONS}

    def add(collection: str, entry: dict[str, str]) -> None:
        if collection not in result:
            return
        token = str(entry.get("token") or "").strip()
        if token:
            result[collection].append(entry)

    def walk(ref: Any, collection_hint: str = "") -> None:
        if isinstance(ref, dict):
            collection = collection_hint
            for key in ("assetType", "asset_type", "collection", "type", "kind"):
                collection = collection or _asset_ref_collection_from_value(ref.get(key))
            for key in ("slot", "targetSlot", "target_slot", "sourceSlot", "source_slot"):
                collection = collection or _asset_ref_collection_from_slot(ref.get(key))

            handled_collection_key = False
            collection_keys = {
                "characters": ("characters", "characterRefs", "character_refs", "roles"),
                "creatures": ("creatures", "creatureRefs", "creature_refs", "monsters", "beasts"),
                "scenes": ("scenes", "sceneRefs", "scene_refs", "locations"),
                "props": ("props", "propRefs", "prop_refs"),
            }
            for asset_type, keys in collection_keys.items():
                for key in keys:
                    if key not in ref:
                        continue
                    handled_collection_key = True
                    walk(ref.get(key), asset_type)

            for key in ("assetRefs", "asset_refs", "items", "inputLinks", "input_links", "inputs"):
                if key in ref:
                    walk(ref.get(key), collection)

            if collection:
                for entry in _asset_ref_entries(ref):
                    add(collection, entry)
            return
        if isinstance(ref, (list, tuple, set)):
            for item in ref:
                walk(item, collection_hint)
            return
        if collection_hint:
            for entry in _asset_ref_entries(ref):
                add(collection_hint, entry)

    walk(value)
    compacted: dict[str, list[dict[str, str]]] = {}
    for key, entries in result.items():
        deduped: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for entry in entries:
            identity = (
                str(entry.get("token") or "").casefold(),
                str(entry.get("mediaVersionId") or ""),
                str(entry.get("stateTag") or "").casefold(),
            )
            if not identity[0] or identity in seen:
                continue
            seen.add(identity)
            deduped.append(entry)
        if deduped:
            compacted[key] = deduped
    return compacted


def _workflow_asset_ref_panel_rows(
    workflow: dict[str, Any],
    panels: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if panels is not None:
        return [copy.deepcopy(item) for item in panels if isinstance(item, dict)]
    panel_rows: list[dict[str, Any]] = []
    for key in ("panels", "shots"):
        rows = workflow.get(key)
        if isinstance(rows, list):
            panel_rows.extend(copy.deepcopy(item) for item in rows if isinstance(item, dict))
    for node in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "").strip()
        if node_type not in {"prompt.storyboard", "director.board"}:
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        for key in ("panels", "shots"):
            rows = data.get(key)
            if isinstance(rows, list):
                panel_rows.extend(copy.deepcopy(item) for item in rows if isinstance(item, dict))
    return panel_rows


def _collect_workflow_asset_refs(
    workflow: dict[str, Any],
    panels: list[dict[str, Any]] | None = None,
    *,
    project_id: str | None = None,
    episode_id: str | None = None,
    context_provenance: dict[str, Any] | None = None,
    route_id: str | None = None,
    work_chain_id: str | None = None,
    token_to_id: dict[str, dict[str, str]] | None = None,
) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {key: [] for key in _ASSET_REF_COLLECTIONS}

    def add(value: Any) -> None:
        grouped = _asset_ref_canonical_tokens_by_collection(value)
        for key in _ASSET_REF_COLLECTIONS:
            refs[key].extend(grouped.get(key) or [])

    for panel in _workflow_asset_ref_panel_rows(workflow, panels):
        add(_asset_refs_from_plan_item(panel))
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if route_id or work_chain_id:
            node_route_id = str(
                node.get("routeId")
                or node.get("route_id")
                or data.get("routeId")
                or data.get("route_id")
                or ""
            ).strip()
            node_work_chain_id = str(
                node.get("workChainId")
                or node.get("work_chain_id")
                or data.get("workChainId")
                or data.get("work_chain_id")
                or ""
            ).strip()
            matches_scope = (
                (not route_id or node_route_id == route_id)
                and (not work_chain_id or node_work_chain_id == work_chain_id)
            )
            if not matches_scope:
                continue
        add(_asset_refs_from_plan_item(node))
        add(_asset_refs_from_plan_item(data))

    compacted: dict[str, list[str]] = {}
    for key, tokens in refs.items():
        deduped = _dedupe_reference_tokens(tokens)
        if deduped:
            compacted[key] = deduped
    if project_id and _asset_refs_has_value(compacted):
        return _filter_asset_refs_to_active_project_assets(
            project_id,
            compacted,
            episode_id=episode_id,
            context_provenance=context_provenance,
            token_to_id=token_to_id,
        )
    return compacted


def _asset_scope_for_episode(project_id: str, episode_id: str | None) -> tuple[set[str], set[str], bool]:
    selected_episode_id = str(episode_id or "").strip()
    if not selected_episode_id:
        return set(), set(), False
    episode_range = _episode_range_for_id(project_id, selected_episode_id)
    if not episode_range:
        return set(), set(), False
    source_id = str(episode_range.get("sourceId") or episode_range.get("source_id") or "").strip()
    start, end = _source_ref_bounds(episode_range)
    if not source_id or start is None or end is None or end <= start:
        return set(), set(), False
    ranges = _asset_ranges_for_source_ref(project_id, episode_range)
    range_ids: set[str] = set()
    asset_tokens: set[str] = set()
    for range_row in ranges:
        range_id = str(range_row.get("rangeId") or range_row.get("range_id") or "").strip()
        if range_id:
            range_ids.add(range_id.casefold())
        created_ids = range_row.get("createdAssetIds") if isinstance(range_row.get("createdAssetIds"), list) else []
        for value in created_ids:
            token = str(value or "").strip()
            if token:
                asset_tokens.add(token.casefold())
    if ranges:
        return range_ids, asset_tokens, True
    try:
        coverage = _load_source_coverage(project_id, source_id or None)
    except Exception:
        return set(), set(), False
    has_ranges_for_source = any(
        isinstance(item, dict)
        and (
            not source_id
            or str(item.get("sourceId") or item.get("source_id") or "").strip() == source_id
        )
        for item in (coverage.get("assetRanges") if isinstance(coverage.get("assetRanges"), list) else [])
    )
    return set(), set(), bool(has_ranges_for_source)


def _asset_row_matches_episode_scope(
    row: dict[str, Any],
    range_ids: set[str],
    asset_tokens: set[str],
) -> bool:
    for row_range_id in _asset_range_ids_from_row(row):
        if row_range_id.casefold() in range_ids:
            return True
    for token in _asset_row_canonical_identity_strings(row):
        if token and token.casefold() in asset_tokens:
            return True
    return False


def _carryover_asset_tokens_from_provenance(value: Any) -> dict[str, set[str]]:
    provenance = value if isinstance(value, dict) else {}
    candidates = provenance.get("assetCandidates") if isinstance(provenance.get("assetCandidates"), dict) else {}
    result: dict[str, set[str]] = {asset_type: set() for asset_type in _ASSET_REF_COLLECTIONS}
    for asset_type in _ASSET_REF_COLLECTIONS:
        group = candidates.get(asset_type) if isinstance(candidates.get(asset_type), dict) else {}
        rows = group.get("carryover") if isinstance(group.get("carryover"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            token = str(row.get("id") or "").strip()
            if token:
                result[asset_type].add(token.casefold())
    return result


def _asset_row_matches_allowed_carryover(row: dict[str, Any], allowed_tokens: set[str]) -> bool:
    if not allowed_tokens:
        return False
    return any(
        token and token.casefold() in allowed_tokens
        for token in _asset_row_canonical_identity_strings(row)
    )


def _project_asset_binding_index(
    project_id: str,
    episode_id: str | None = None,
    context_provenance: dict[str, Any] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, str]]]:
    from .assets import list_assets
    assets = list_assets("project", project_id, hydrate=False, lifecycle_status=ASSET_LIFECYCLE_ACTIVE, persist_normalization=False)
    range_ids, asset_tokens, scoped = _asset_scope_for_episode(project_id, episode_id)
    allowed_carryover = _carryover_asset_tokens_from_provenance(context_provenance)
    rows_by_type: dict[str, list[dict[str, Any]]] = {key: [] for key in _ASSET_REF_COLLECTIONS}
    token_to_id: dict[str, dict[str, str]] = {key: {} for key in _ASSET_REF_COLLECTIONS}
    for asset_type in _ASSET_REF_COLLECTIONS:
        rows = assets.get(asset_type) if isinstance(assets, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            if (
                scoped
                and not _asset_row_matches_episode_scope(row, range_ids, asset_tokens)
                and not _asset_row_matches_allowed_carryover(row, allowed_carryover.get(asset_type) or set())
            ):
                continue
            asset_id = str(row.get("id") or "").strip()
            if not asset_id:
                continue
            aliases = _asset_row_identity_strings(row, include_ids=True, include_aliases=True)
            match_aliases = _asset_row_identity_strings(row, include_ids=False, include_aliases=True)
            row_data = {
                "assetId": asset_id,
                "assetType": asset_type,
                "displayName": _asset_row_display_name(row) or asset_id,
                "aliases": aliases,
                "matchAliases": match_aliases,
            }
            rows_by_type[asset_type].append(row_data)
            for token in aliases:
                token_to_id[asset_type].setdefault(token.casefold(), asset_id)
    return rows_by_type, token_to_id


def _storyboard_asset_text_fragments(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(_storyboard_asset_text_fragments(item))
        return parts
    if isinstance(value, dict):
        skip_keys = {
            "id",
            "segmentId",
            "segment_id",
            "plotSplitItemId",
            "sourceRefs",
            "source_refs",
            "sourceUnitIds",
            "source_unit_ids",
            "assetRefs",
            "asset_refs",
            "inputLinks",
            "input_links",
            "referenceMediaIds",
            "reference_media_ids",
        }
        parts: list[str] = []
        for key, item in value.items():
            if key in skip_keys:
                continue
            parts.extend(_storyboard_asset_text_fragments(item))
        return parts
    return []


def _storyboard_asset_binding_text(row: dict[str, Any]) -> str:
    task_card = row.get("storyboardTaskCard") if isinstance(row.get("storyboardTaskCard"), dict) else {}
    sources: list[Any] = [
        row.get("title"),
        row.get("summary"),
        row.get("narrativePurpose"),
        row.get("sourceFactText"),
        row.get("source_fact_text"),
        row.get("cinematicStoryText"),
        row.get("cinematic_story_text"),
        row.get("dialogueText"),
        row.get("dialogue"),
        row.get("userNotes"),
        row.get("sceneBrief"),
        row.get("storyboardAnalysis"),
        row.get("prompt"),
        row.get("prompts"),
        row.get("screenplay"),
        row.get("shots"),
        row.get("panels"),
        task_card.get("title"),
        task_card.get("sourceFactText"),
        task_card.get("source_fact_text"),
        task_card.get("cinematicStoryText"),
        task_card.get("cinematic_story_text"),
    ]
    parts: list[str] = []
    for source in sources:
        parts.extend(_storyboard_asset_text_fragments(source))
    return "\n".join(part for part in parts if part)


def _asset_text_contains_alias(text: str, alias: str) -> bool:
    needle = str(alias or "").strip()
    if len(needle) < 2:
        return False
    haystack = str(text or "")
    if not haystack:
        return False
    if re.search(r"[A-Za-z0-9_]", needle):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(needle.casefold())}(?![A-Za-z0-9_])"
        return bool(re.search(pattern, haystack.casefold()))
    return needle in haystack


def _matched_asset_refs_from_text(
    text: str,
    rows_by_type: dict[str, list[dict[str, Any]]],
) -> dict[str, list[str]]:
    matches: dict[str, list[str]] = {key: [] for key in _ASSET_REF_COLLECTIONS}
    for asset_type in _ASSET_REF_COLLECTIONS:
        for row in rows_by_type.get(asset_type) or []:
            asset_id = str(row.get("assetId") or "").strip()
            aliases = row.get("matchAliases") if isinstance(row.get("matchAliases"), list) else []
            if not asset_id or not any(_asset_text_contains_alias(text, str(alias)) for alias in aliases):
                continue
            if asset_id not in matches[asset_type]:
                matches[asset_type].append(asset_id)
    return {key: values for key, values in matches.items() if values}


_STORYBOARD_AT_MENTION_RE = re.compile(r"@([^\s@,，.。;；:：!！?？()（）\[\]【】{}<>《》\"'“”‘’]{1,48})")


def _typed_storyboard_asset_mentions(row: dict[str, Any]) -> dict[str, list[str]]:
    mentions: dict[str, list[str]] = {key: [] for key in _ASSET_REF_COLLECTIONS}
    if not isinstance(row, dict):
        return {}
    analysis = row.get("storyboardAnalysis") if isinstance(row.get("storyboardAnalysis"), dict) else {}
    if not analysis and isinstance(row.get("storyboard_analysis"), dict):
        analysis = row.get("storyboard_analysis") or {}
    sources: dict[str, list[Any]] = {
        "characters": [
            row.get("characterNames"),
            row.get("character_names"),
            row.get("roles"),
            analysis.get("characters"),
            analysis.get("characterNames"),
            analysis.get("character_names"),
            analysis.get("roles"),
        ],
        "scenes": [
            row.get("scene"),
            row.get("scenes"),
            row.get("location"),
            row.get("locations"),
            row.get("setting"),
            analysis.get("scene"),
            analysis.get("scenes"),
            analysis.get("location"),
            analysis.get("locations"),
            analysis.get("setting"),
        ],
        "props": [
            row.get("props"),
            row.get("prop"),
            row.get("items"),
            row.get("objects"),
            analysis.get("props"),
            analysis.get("prop"),
            analysis.get("items"),
            analysis.get("objects"),
        ],
    }
    for asset_type, values in sources.items():
        for value in values:
            for token in _asset_ref_tokens(value):
                text = str(token or "").strip()
                if text and text not in mentions[asset_type]:
                    mentions[asset_type].append(text)
    return {key: values for key, values in mentions.items() if values}


def _storyboard_at_mentions(row: dict[str, Any]) -> list[str]:
    text = _storyboard_asset_binding_text(row)
    mentions: list[str] = []
    for match in _STORYBOARD_AT_MENTION_RE.finditer(text):
        token = str(match.group(1) or "").strip()
        if token and token not in mentions:
            mentions.append(token)
    return mentions


def _asset_ref_token_present(
    refs: Any,
    asset_type: str,
    token: str,
    token_to_id: dict[str, dict[str, str]],
) -> bool:
    text = str(token or "").strip()
    if not text:
        return False
    grouped_refs = _asset_ref_tokens_by_collection(refs)
    canonical = token_to_id.get(asset_type, {}).get(text.casefold()) or text
    candidates = {
        item.casefold()
        for item in _asset_ref_tokens(grouped_refs.get(asset_type))
        if str(item or "").strip()
    }
    return text.casefold() in candidates or canonical.casefold() in candidates


def _typed_storyboard_mention_type(token: str) -> tuple[str, str]:
    text = str(token or "").strip()
    if not text:
        return "", ""
    for separator in (":", "：", "/", "／"):
        if separator not in text:
            continue
        prefix, name = text.split(separator, 1)
        asset_type = _asset_ref_collection_from_value(prefix)
        name = name.strip()
        if asset_type and name:
            return asset_type, name
    return "", text


def _storyboard_unmatched_asset_mentions(
    row: dict[str, Any],
    *,
    token_to_id: dict[str, dict[str, str]],
    bound_refs: Any = None,
) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(asset_type: str, token: str, reason: str) -> None:
        text = str(token or "").strip()
        if not text:
            return
        key = (asset_type, text.casefold(), reason)
        if key in seen:
            return
        seen.add(key)
        missing.append({"assetType": asset_type, "token": text, "reason": reason})

    typed_mentions = _typed_storyboard_asset_mentions(row)
    typed_missing_tokens: set[str] = set()
    for asset_type, tokens in typed_mentions.items():
        known_tokens = token_to_id.get(asset_type, {})
        for token in tokens:
            text = str(token or "").strip()
            if not text:
                continue
            if text.casefold() in known_tokens:
                continue
            if _asset_ref_token_present(bound_refs, asset_type, text, token_to_id):
                continue
            add(asset_type, text, "asset_mention_not_matched")
            typed_missing_tokens.add(text.casefold())

    for mention in _storyboard_at_mentions(row):
        explicit_type, token = _typed_storyboard_mention_type(mention)
        if explicit_type:
            if token.casefold() in token_to_id.get(explicit_type, {}):
                continue
            if _asset_ref_token_present(bound_refs, explicit_type, token, token_to_id):
                continue
            add(explicit_type, token, "explicit_mention_not_matched")
            continue
        matched = False
        for asset_type in _ASSET_REF_COLLECTIONS:
            if mention.casefold() in token_to_id.get(asset_type, {}):
                matched = True
                break
            if _asset_ref_token_present(bound_refs, asset_type, mention, token_to_id):
                matched = True
                break
        if not matched and mention.casefold() not in typed_missing_tokens:
            add("unknown", mention, "explicit_mention_not_matched")
    return missing


def storyboard_unmatched_asset_mentions(project_id: str, episode_id: str | None, row: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(row, dict):
        return []
    _, token_to_id = _project_asset_binding_index(project_id, episode_id)
    refs = row.get("assetRefs") if "assetRefs" in row else row.get("asset_refs")
    return _storyboard_unmatched_asset_mentions(row, token_to_id=token_to_id, bound_refs=refs)


def _merge_asset_ref_groups(
    sources: list[Any],
    auto_refs: dict[str, list[str]],
    token_to_id: dict[str, dict[str, str]],
    *,
    preserve_unknown: bool = False,
) -> dict[str, list[Any]]:
    merged: dict[str, list[Any]] = {key: [] for key in _ASSET_REF_COLLECTIONS}
    seen: dict[str, set[str]] = {key: set() for key in _ASSET_REF_COLLECTIONS}

    def add(asset_type: str, entry: Any, *, preserve_token: bool) -> None:
        if isinstance(entry, dict):
            text = str(entry.get("token") or "").strip()
            media_version_id = str(entry.get("mediaVersionId") or "").strip()
            state_tag = str(entry.get("stateTag") or "").strip()
        else:
            text = str(entry or "").strip()
            media_version_id = ""
            state_tag = ""
        if asset_type not in merged or not text:
            return
        canonical = token_to_id.get(asset_type, {}).get(text.casefold())
        if preserve_token:
            if not canonical and not preserve_unknown:
                return
            if canonical and canonical.casefold() != text.casefold():
                return
        elif not canonical:
            return
        canonical_key = (canonical or text).casefold()
        if canonical_key in seen[asset_type]:
            return
        seen[asset_type].add(canonical_key)
        has_ref_metadata = bool(
            media_version_id
            or state_tag
            or any(str(entry.get(key) or "").strip() for key in ("position", "role", "note", "label"))
        ) if isinstance(entry, dict) else False
        if preserve_token and isinstance(entry, dict) and has_ref_metadata:
            ref: dict[str, str] = {"assetId": canonical or text}
            if text and text != ref["assetId"]:
                ref["id"] = text
            if media_version_id:
                ref["versionId"] = media_version_id
                ref["mediaVersionId"] = media_version_id
            if state_tag:
                ref["stateTag"] = state_tag
            for key in ("position", "role", "note", "label"):
                value = str(entry.get(key) or "").strip()
                if value:
                    ref[key] = value
            merged[asset_type].append(ref)
            return
        merged[asset_type].append((canonical or text) if preserve_token else canonical)

    for source in sources:
        grouped = _asset_ref_entries_by_collection(source)
        for asset_type in _ASSET_REF_COLLECTIONS:
            for entry in grouped.get(asset_type) or []:
                add(asset_type, entry, preserve_token=True)
    for asset_type in _ASSET_REF_COLLECTIONS:
        for token in auto_refs.get(asset_type) or []:
            add(asset_type, token, preserve_token=False)
    return {key: values for key, values in merged.items() if values}


def _filter_asset_refs_to_active_project_assets(
    project_id: str,
    refs: Any,
    *,
    episode_id: str | None = None,
    context_provenance: dict[str, Any] | None = None,
    token_to_id: dict[str, dict[str, str]] | None = None,
) -> dict[str, list[Any]]:
    if not project_id or not _asset_refs_has_value(refs):
        return {}
    resolved_token_to_id = token_to_id
    if resolved_token_to_id is None:
        _rows_by_type, resolved_token_to_id = _project_asset_binding_index(
            project_id,
            episode_id,
            context_provenance=context_provenance,
        )
    return _merge_asset_ref_groups([refs], {}, resolved_token_to_id)


def _row_asset_ref_sources(row: dict[str, Any]) -> list[Any]:
    sources: list[Any] = []
    for key in ("assetRefs", "asset_refs", "inputLinks", "input_links"):
        if key in row:
            sources.append(row.get(key))
    task_card = row.get("storyboardTaskCard") if isinstance(row.get("storyboardTaskCard"), dict) else {}
    for key in ("assetRefs", "asset_refs", "inputLinks", "input_links"):
        if key in task_card:
            sources.append(task_card.get(key))
    return sources


def storyboard_asset_refs_from_current_sources(project_id: str, episode_id: str | None, row: dict[str, Any]) -> dict[str, list[Any]]:
    if not isinstance(row, dict):
        return {}
    # Existing workflow/canvas links still need to respect the asset lifecycle:
    # offline project assets are preserved in storage but cannot participate in
    # storyboard or video generation until they are restored to active.
    _, token_to_id = _project_asset_binding_index(project_id, None)
    return _merge_asset_ref_groups(_row_asset_ref_sources(row), {}, token_to_id)


def bind_storyboard_asset_refs_from_text(project_id: str, episode_id: str, row: dict[str, Any]) -> dict[str, list[Any]]:
    if not isinstance(row, dict):
        return {}
    rows_by_type, token_to_id = _project_asset_binding_index(project_id, episode_id)
    if not any(rows_by_type.get(asset_type) for asset_type in _ASSET_REF_COLLECTIONS):
        return {}
    text = _storyboard_asset_binding_text(row)
    auto_refs = _matched_asset_refs_from_text(text, rows_by_type)
    return _merge_asset_ref_groups(_row_asset_ref_sources(row), auto_refs, token_to_id)


def _auto_bind_shot_plan_asset_refs(project_id: str, episode_id: str, document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        return document
    context_provenance = (
        document.get("contextProvenance") if isinstance(document.get("contextProvenance"), dict) else {}
    )
    rows_by_type, token_to_id = _project_asset_binding_index(
        project_id,
        episode_id,
        context_provenance=context_provenance,
    )
    has_active_assets = any(rows_by_type.get(asset_type) for asset_type in _ASSET_REF_COLLECTIONS)
    content_mode = str(document.get("contentMode") or document.get("content_mode") or "").strip().casefold()
    allow_text_auto_refs = (
        has_active_assets
        and not bool(context_provenance)
        and content_mode != "plot_split_canvas"
    )
    bound = copy.deepcopy(document)
    segment_refs: dict[str, dict[str, list[Any]]] = {}
    segments = bound.get("segments") if isinstance(bound.get("segments"), list) else []
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        text = _storyboard_asset_binding_text(segment) if allow_text_auto_refs else ""
        auto_refs = _matched_asset_refs_from_text(text, rows_by_type) if allow_text_auto_refs else {}
        merged_refs = _merge_asset_ref_groups(
            _row_asset_ref_sources(segment),
            auto_refs,
            token_to_id,
            preserve_unknown=True,
        )
        segment.pop("assetRefs", None)
        segment.pop("asset_refs", None)
        task_card = segment.get("storyboardTaskCard") if isinstance(segment.get("storyboardTaskCard"), dict) else {}
        if isinstance(task_card, dict):
            task_card.pop("assetRefs", None)
            task_card.pop("asset_refs", None)
        if merged_refs:
            segment["assetRefs"] = merged_refs
            task_card["assetRefs"] = copy.deepcopy(merged_refs)
            task_card["state"] = "assets_ready"
            segment["storyboardTaskCard"] = task_card
        elif task_card:
            if str(task_card.get("state") or "").strip() == "assets_ready":
                task_card["state"] = "draft"
            segment["storyboardTaskCard"] = task_card
        segment.pop("missingAssetRefs", None)
        task_card = segment.get("storyboardTaskCard") if isinstance(segment.get("storyboardTaskCard"), dict) else {}
        if isinstance(task_card, dict):
            task_card.pop("missingAssetRefs", None)
        segment_id = str(segment.get("id") or segment.get("segmentId") or segment.get("segment_id") or f"seg_{index:03d}").strip()
        if segment_id and merged_refs:
            segment_refs[segment_id] = copy.deepcopy(merged_refs)

    shots = bound.get("shots") if isinstance(bound.get("shots"), list) else []
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            continue
        segment_id = str(shot.get("segmentId") or shot.get("segment_id") or "").strip()
        text = (
            "\n".join(
                part
                for part in (
                    _storyboard_asset_binding_text(shot),
                    _storyboard_asset_binding_text(segments[index - 1]) if not segment_id and index - 1 < len(segments) and isinstance(segments[index - 1], dict) else "",
                )
                if part
            )
            if allow_text_auto_refs
            else ""
        )
        auto_refs = _matched_asset_refs_from_text(text, rows_by_type) if allow_text_auto_refs else {}
        sources = _row_asset_ref_sources(shot)
        if segment_id and segment_id in segment_refs:
            sources.append(segment_refs[segment_id])
        merged_refs = _merge_asset_ref_groups(
            sources,
            auto_refs,
            token_to_id,
            preserve_unknown=True,
        )
        shot.pop("assetRefs", None)
        shot.pop("asset_refs", None)
        if merged_refs:
            shot["assetRefs"] = merged_refs
    return bound


def _project_asset_lookup_with_scope(
    project_id: str,
    episode_id: str | None = None,
    context_provenance: dict[str, Any] | None = None,
) -> tuple[dict[str, set[str]], bool]:
    from .assets import list_assets
    assets = list_assets("project", project_id, hydrate=False, lifecycle_status=ASSET_LIFECYCLE_ACTIVE, persist_normalization=False)
    range_ids, asset_tokens, scoped = _asset_scope_for_episode(project_id, episode_id)
    allowed_carryover = _carryover_asset_tokens_from_provenance(context_provenance)
    lookup: dict[str, set[str]] = {}
    for asset_type in _ASSET_REF_COLLECTIONS:
        tokens: set[str] = set()
        rows = assets.get(asset_type) if isinstance(assets, dict) else []
        asset_rows = rows if isinstance(rows, list) else []
        for row in asset_rows:
            if not isinstance(row, dict):
                continue
            if (
                scoped
                and not _asset_row_matches_episode_scope(row, range_ids, asset_tokens)
                and not _asset_row_matches_allowed_carryover(row, allowed_carryover.get(asset_type) or set())
            ):
                continue
            for text in _asset_row_canonical_identity_strings(row):
                if text:
                    tokens.add(text.casefold())
        lookup[asset_type] = tokens
    has_evidence_scope = isinstance(
        (context_provenance or {}).get("assetCandidates") if isinstance(context_provenance, dict) else None,
        dict,
    )
    if (
        scoped
        and not has_evidence_scope
        and not any(lookup.values())
        and not _project_has_asset_scope_bindings(project_id)
    ):
        return _project_asset_lookup_with_scope(project_id)
    return lookup, scoped


def _project_asset_lookup(project_id: str, episode_id: str | None = None) -> dict[str, set[str]]:
    return _project_asset_lookup_with_scope(project_id, episode_id)[0]


def _project_has_asset_scope_bindings(project_id: str) -> bool:
    from .agent_sessions import _project_dir
    from .assets import list_assets
    coverage = _read_json(_project_dir(project_id) / "source_coverage.json", {})
    asset_ranges = coverage.get("assetRanges") if isinstance(coverage, dict) else []
    for row in asset_ranges or []:
        if not isinstance(row, dict):
            continue
        if any(str(value or "").strip() for value in (row.get("createdAssetIds") or [])):
            return True
    assets = list_assets("project", project_id, hydrate=False, lifecycle_status=ASSET_LIFECYCLE_ACTIVE, persist_normalization=False)
    for asset_type in _ASSET_REF_COLLECTIONS:
        for row in assets.get(asset_type) or []:
            if isinstance(row, dict) and _asset_range_ids_from_row(row):
                return True
    return False


def _context_asset_rows_from_binding_index(
    project_id: str,
    episode_id: str,
) -> dict[str, list[dict[str, str]]]:
    rows_by_type, _token_to_id = _project_asset_binding_index(project_id, episode_id)
    return {
        asset_type: [
            {
                "id": str(row.get("assetId") or "").strip(),
                "name": str(row.get("displayName") or row.get("assetId") or "").strip(),
            }
            for row in rows_by_type.get(asset_type) or []
            if isinstance(row, dict) and str(row.get("assetId") or "").strip()
        ]
        for asset_type in _ASSET_REF_COLLECTIONS
    }


def _trusted_context_provenance_for_episode(project_id: str, episode_id: str) -> dict[str, Any]:
    source = get_episode_source_text(project_id, episode_id)
    if source.get("available") is False:
        raise ValueError(f"{episode_id} 缺少已提交 source range，无法验证跨集上下文")
    envelope = _resolve_work_context(
        project_id,
        "plot_splitting",
        episode_id=episode_id,
        current_source=source,
    )
    continuity = envelope.get("continuity") if isinstance(envelope.get("continuity"), dict) else {}
    previous_episode = (
        continuity.get("previousEpisode") if isinstance(continuity.get("previousEpisode"), dict) else {}
    )
    previous_episode_id = str(previous_episode.get("episodeId") or "").strip()
    current_assets = _context_asset_rows_from_binding_index(project_id, episode_id)
    carryover_assets = (
        _context_asset_rows_from_binding_index(project_id, previous_episode_id)
        if previous_episode_id
        else {}
    )
    _assets, resolved_envelope = _merge_context_asset_candidates(
        current_assets,
        carryover_assets,
        current_text=str(source.get("text") or ""),
        context_envelope=envelope,
    )
    return _context_provenance(resolved_envelope)


def _validate_asset_refs_for_episode_scope(
    project_id: str,
    episode_id: str | None,
    refs: Any,
    label: str,
    *,
    locked: bool = False,
    lookup: dict[str, set[str]] | None = None,
    scoped: bool | None = None,
    context_provenance: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    warnings: list[str] = []
    if not _asset_refs_has_value(refs):
        return blocking, warnings
    if lookup is None:
        lookup, resolved_scoped = _project_asset_lookup_with_scope(
            project_id,
            episode_id,
            context_provenance=context_provenance,
        )
        if scoped is None:
            scoped = resolved_scoped
    elif scoped is None:
        scoped = _asset_scope_for_episode(project_id, episode_id)[2]
    grouped_refs = _asset_ref_canonical_tokens_by_collection(refs)
    scope_label = "当前资产库"
    scope_note = "（已按当前集资产候选范围校验）" if scoped else ""

    def known_tokens_for(asset_type: str) -> set[str]:
        return set(lookup.get(asset_type, set()))

    typed_token_count = 0
    for asset_type in _ASSET_REF_COLLECTIONS:
        tokens = grouped_refs.get(asset_type) or []
        typed_token_count += len(tokens)
        unknown = [token for token in tokens if token.casefold() not in known_tokens_for(asset_type)]
        if not unknown:
            continue
        noun = _ASSET_REF_LABELS.get(asset_type, asset_type)
        message = f"{label}引用的{noun}资产未在{scope_label}中找到{scope_note}：{', '.join(unknown[:4])}"
        if locked:
            warnings.append(message)
        else:
            blocking.append(message)
    if typed_token_count == 0:
        tokens = _asset_canonical_reference_ids_from_refs(refs)
        if tokens:
            known_tokens = set().union(*(known_tokens_for(asset_type) for asset_type in _ASSET_REF_COLLECTIONS))
            unknown = [token for token in tokens if token.casefold() not in known_tokens]
            if unknown:
                message = f"{label}引用的资产未在{scope_label}中找到{scope_note}：{', '.join(unknown[:4])}"
                if locked:
                    warnings.append(message)
                else:
                    blocking.append(message)
    return blocking, warnings


def _validate_workflow_asset_refs(
    project_id: str,
    episode_id: str | None,
    workflow: dict[str, Any],
) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    warnings: list[str] = []
    # Asset scope is only an agent-planning input before the work chain is generated.
    # Once a workflow exists, canvas saves/links/edits are free project-level edits:
    # do not block them with the episode asset candidate range.
    lookup, _unused_scoped = _project_asset_lookup_with_scope(project_id)
    scoped = False

    def merge(result: tuple[list[str], list[str]]) -> None:
        result_blocking, result_warnings = result
        blocking.extend(result_blocking)
        warnings.extend(result_warnings)

    for index, panel in enumerate(_workflow_asset_ref_panel_rows(workflow), start=1):
        if not isinstance(panel, dict):
            continue
        refs = _asset_refs_from_plan_item(panel)
        if _asset_refs_has_value(refs):
            merge(
                _validate_asset_refs_for_episode_scope(
                    project_id,
                    episode_id,
                    refs,
                    f"画布分镜第 {index} 条",
                    locked=_is_user_locked_item(panel),
                    lookup=lookup,
                    scoped=scoped,
                )
            )

    for index, node in enumerate(workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else [], start=1):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or index).strip()
        locked = _is_user_locked_item(node)
        refs = _asset_refs_from_plan_item(node)
        if _asset_refs_has_value(refs):
            merge(
                _validate_asset_refs_for_episode_scope(
                    project_id,
                    episode_id,
                    refs,
                    f"画布节点 {node_id}",
                    locked=locked,
                    lookup=lookup,
                    scoped=scoped,
                )
            )
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        data_refs = _asset_refs_from_plan_item(data)
        if _asset_refs_has_value(data_refs):
            merge(
                _validate_asset_refs_for_episode_scope(
                    project_id,
                    episode_id,
                    data_refs,
                    f"画布节点 {node_id}",
                    locked=locked,
                    lookup=lookup,
                    scoped=scoped,
                )
            )
        input_links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
        if input_links:
            merge(
                _validate_asset_refs_for_episode_scope(
                    project_id,
                    episode_id,
                    input_links,
                    f"画布节点 {node_id} 输入链接",
                    locked=locked,
                    lookup=lookup,
                    scoped=scoped,
                )
            )

    return blocking, warnings


def _plan_item_allows_missing_asset_refs(row: dict[str, Any]) -> bool:
    explicit_flags = (
        row.get("assetRefsOptional"),
        row.get("asset_refs_optional"),
        row.get("allowMissingAssetRefs"),
        row.get("allow_missing_asset_refs"),
    )
    if any(_truthy_payload_flag(value) for value in explicit_flags):
        return True
    task_card = row.get("storyboardTaskCard") or row.get("storyboard_task_card")
    if isinstance(task_card, dict):
        task_card_flags = (
            task_card.get("assetRefsOptional"),
            task_card.get("asset_refs_optional"),
            task_card.get("allowMissingAssetRefs"),
            task_card.get("allow_missing_asset_refs"),
        )
        if any(_truthy_payload_flag(value) for value in task_card_flags):
            return True
    default_strategy = str(
        row.get("generationStrategy")
        or row.get("generation_strategy")
        or row.get("strategy")
        or ""
    ).strip()
    route_specs = _segment_route_specs(row, default_strategy or "storyboard_multi_shot")
    strategies = {
        str(spec.get("strategy") or default_strategy or "").strip()
        for spec in route_specs
        if isinstance(spec, dict)
    }
    return bool(strategies) and strategies <= {"text_to_video_draft"}


def _validate_plan_asset_refs(
    project_id: str,
    document: dict[str, Any],
    episode_id: str | None = None,
) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    warnings: list[str] = []
    context_provenance = (
        document.get("contextProvenance") if isinstance(document.get("contextProvenance"), dict) else {}
    )
    # This is the planning-time gate. Episode asset scope belongs here so the
    # agent builds the initial work chain from the intended candidate assets.
    lookup, scoped = _project_asset_lookup_with_scope(
        project_id,
        episode_id,
        context_provenance=context_provenance,
    )
    project_lookup, _ = _project_asset_lookup_with_scope(project_id)
    has_project_assets = any(project_lookup.get(asset_type) for asset_type in _ASSET_REF_COLLECTIONS)
    for collection_name, label in (("segments", "镜头段"), ("shots", "分镜")):
        rows = document.get(collection_name)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            refs = _asset_refs_from_plan_item(row)
            if not _asset_refs_has_value(refs):
                if _plan_item_allows_missing_asset_refs(row):
                    continue
                message = f"{label}第 {index} 条缺少 assetRefs，后续分镜无法稳定引用角色/生物/场景/道具资产"
                if has_project_assets and not _is_user_locked_item(row):
                    blocking.append(message)
                else:
                    warnings.append(message)
                continue
            ref_blocking, ref_warnings = _validate_asset_refs_for_episode_scope(
                project_id,
                episode_id,
                refs,
                f"{label}第 {index} 条",
                locked=_is_user_locked_item(row),
                lookup=lookup,
                scoped=scoped,
                context_provenance=context_provenance,
            )
            blocking.extend(ref_blocking)
            warnings.extend(ref_warnings)
    return blocking, warnings
