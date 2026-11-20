# -*- coding: utf-8 -*-
"""供模型读取的资产索引、版本和证据摘要。"""
from __future__ import annotations

import copy
import json
from .assets import (
    list_assets,
)
from .source_text_store import _compact_text
from .worker_asset_candidates import (
    _analyze_assets_asset_type_key,
)
from .worker_asset_contract import (
    _ASSET_CATALOG_DESC_CHARS,
    _ASSET_CATALOG_LIMIT_PER_TYPE,
    _ASSET_CATALOG_PROMPT_PREVIEW_CHARS,
    _ASSET_CATALOG_VOICE_STYLE_CHARS,
    _ASSET_TYPES,
)
from .worker_text import (
    _compact_analyze_assets_brief_list,
    _compact_source_excerpt,
    _revision_feedback_terms,
    _strip_empty_prompt_fields,
)
from typing import (
    Any,
)


def _analyze_assets_prompt_production_spec(value: Any) -> dict[str, Any]:
    production_spec = value if isinstance(value, dict) else {}
    language = production_spec.get("language") if isinstance(production_spec.get("language"), dict) else {}
    if not language:
        return {}
    return {"language": copy.deepcopy(language)}


def _asset_catalog_count_map(value: Any) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    result: dict[str, int] = {}
    for asset_type in _ASSET_TYPES:
        try:
            count = int(source.get(asset_type) or 0)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            result[asset_type] = count
    return result


def _analyze_assets_prompt_asset_catalog_meta(value: Any) -> dict[str, Any]:
    meta = value if isinstance(value, dict) else {}
    total_counts = _asset_catalog_count_map(meta.get("totalCounts"))
    included_counts = _asset_catalog_count_map(meta.get("includedCounts"))
    truncated_types = [
        asset_type
        for asset_type in (
            meta.get("truncatedTypes") if isinstance(meta.get("truncatedTypes"), list) else []
        )
        if str(asset_type) in _ASSET_TYPES
    ]
    for asset_type in _ASSET_TYPES:
        if total_counts.get(asset_type, 0) > included_counts.get(asset_type, 0) and asset_type not in truncated_types:
            truncated_types.append(asset_type)
    if not total_counts and not truncated_types:
        return {}
    result: dict[str, Any] = {}
    if total_counts:
        result["totalCounts"] = total_counts
    if included_counts:
        result["includedCounts"] = included_counts
    if truncated_types:
        result["truncatedTypes"] = truncated_types
        for key in ("limitPerType", "descChars", "assetImagePromptPreviewChars", "voiceStyleChars"):
            if meta.get(key) not in (None, "", [], {}):
                result[key] = copy.deepcopy(meta.get(key))
        retrieval_rule = _compact_text(meta.get("retrievalRule"), 180)
        if retrieval_rule:
            result["retrievalRule"] = retrieval_rule
    return result


def _compact_analyze_assets_material_digest_for_prompt(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    candidate_id = str(row.get("candidateId") or row.get("candidate_id") or "").strip()
    asset_name = _compact_text(row.get("assetName") or row.get("name"), 60)
    item: dict[str, Any] = {
        "candidateId": candidate_id,
        "assetName": asset_name,
    }
    if "matched" in row:
        item["matched"] = row.get("matched") is True
    digest = _compact_text(row.get("materialDigest") or row.get("summary"), 420)
    if digest:
        item["materialDigest"] = digest
    identity_facts = _compact_analyze_assets_brief_list(row.get("identityFacts"), limit=5, item_limit=80)
    if identity_facts:
        item["identityFacts"] = identity_facts
    visual_facts = _compact_analyze_assets_brief_list(row.get("visualFacts"), limit=6, item_limit=90)
    if visual_facts:
        item["visualFacts"] = visual_facts
    constraints = _compact_analyze_assets_brief_list(row.get("constraints"), limit=6, item_limit=90)
    if constraints:
        item["constraints"] = constraints
    source_refs: list[dict[str, str]] = []
    for ref in row.get("sourceMaterialRefs") if isinstance(row.get("sourceMaterialRefs"), list) else []:
        if not isinstance(ref, dict):
            continue
        relative_path = str(ref.get("relativePath") or "").strip()
        matched_text = _compact_text(ref.get("matchedText") or ref.get("text"), 100)
        source_ref = {
            key: value
            for key, value in {
                "relativePath": relative_path,
                "matchedText": matched_text,
            }.items()
            if value
        }
        if not source_ref:
            continue
        source_refs.append(source_ref)
        if len(source_refs) >= 2:
            break
    if source_refs:
        item["sourceMaterialRefs"] = source_refs
    return {key: value for key, value in item.items() if value not in (None, "", [], {})}


def _compact_analyze_assets_material_digest_map_for_prompt(
    value: Any,
    *,
    asset_types: tuple[str, ...] | list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    source = value if isinstance(value, dict) else {}
    selected_asset_types = tuple(
        asset_type for asset_type in (asset_types or _ASSET_TYPES) if str(asset_type) in _ASSET_TYPES
    )
    result: dict[str, list[dict[str, Any]]] = {}
    for asset_type in selected_asset_types:
        rows = source.get(asset_type)
        selected: list[dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            compacted = _compact_analyze_assets_material_digest_for_prompt(row)
            if compacted:
                selected.append(compacted)
        if selected:
            result[asset_type] = selected
    return result


def _asset_state_versions_for_prompt(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tag = _compact_text(row.get("tag") or row.get("stateTag") or row.get("label") or row.get("name"), 40)
        tags = [
            _compact_text(item, 40)
            for item in (row.get("tags") if isinstance(row.get("tags"), list) else [])
            if str(item or "").strip()
        ][:6]
        desc = _compact_text(row.get("desc") or row.get("description") or row.get("prompt"), 120)
        item = {
            key: value
            for key, value in {"tag": tag, "tags": tags, "desc": desc}.items()
            if value not in (None, "", [], {})
        }
        if item.get("tag") or item.get("tags"):
            result.append(item)
    return result


def _asset_source_evidence_for_prompt(row: dict[str, Any]) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []

    def add_preview(value: Any) -> None:
        preview = _compact_source_excerpt(value, 80)
        if preview and all(item.get("sourcePreview") != preview for item in evidence):
            evidence.append({"sourcePreview": preview})

    raw_evidence = row.get("sourceEvidence") if isinstance(row.get("sourceEvidence"), list) else []
    for item in raw_evidence:
        if len(evidence) >= 2:
            break
        if isinstance(item, dict):
            add_preview(item.get("sourcePreview") or item.get("source_preview") or item.get("excerpt") or item.get("text"))
        else:
            add_preview(item)

    refs = row.get("sourceRefs") if isinstance(row.get("sourceRefs"), list) else []
    refs = refs if isinstance(refs, list) else []
    for ref in refs:
        if len(evidence) >= 2:
            break
        if isinstance(ref, dict):
            add_preview(ref.get("sourcePreview") or ref.get("source_preview") or ref.get("excerpt"))
    return evidence


def _asset_catalog_row_for_prompt(asset_type: str, row: dict[str, Any]) -> dict[str, Any]:
    asset_id = str(row.get("id") or "").strip()
    if not asset_id:
        return {}
    item: dict[str, Any] = {
        "id": asset_id,
        "name": _compact_text(row.get("name") or row.get("title") or row.get("assetName"), 80),
        "desc": _compact_text(row.get("desc") or row.get("description") or row.get("summary"), 220),
    }
    aliases = [
        _compact_text(alias, 40)
        for alias in (row.get("aliases") if isinstance(row.get("aliases"), list) else [])
        if str(alias or "").strip()
    ][:6]
    if aliases:
        item["aliases"] = aliases
    if asset_type in {"characters", "creatures"}:
        voice_style = _compact_text(row.get("voiceStyle") or row.get("voice_style"), 90)
        if voice_style:
            item["voiceStyle"] = voice_style
        if asset_type == "creatures":
            item["canSpeak"] = bool(voice_style or row.get("canSpeak") is True)
    if asset_type == "scenes":
        role = str(row.get("sceneReferenceRole") or row.get("scene_reference_role") or "").strip()
        if role:
            item["sceneReferenceRole"] = role
    source_evidence = _asset_source_evidence_for_prompt(row)
    if source_evidence:
        item["sourceEvidence"] = source_evidence
    versions = _asset_state_versions_for_prompt(row.get("stateVersions"))
    if versions:
        item["stateVersions"] = versions
    return {key: value for key, value in item.items() if value not in (None, "", [], {})}


def _asset_catalog_for_prompt(value: Any) -> dict[str, list[dict[str, Any]]]:
    source = value if isinstance(value, dict) else {}
    result: dict[str, list[dict[str, Any]]] = {}
    for asset_type in _ASSET_TYPES:
        rows = source.get(asset_type) if isinstance(source.get(asset_type), list) else []
        clean_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = _asset_catalog_row_for_prompt(asset_type, row)
            if item:
                clean_rows.append(item)
        result[asset_type] = clean_rows
    return result


def _asset_state_tag_map_for_prompt(value: Any) -> dict[tuple[str, str, str], str]:
    source = value if isinstance(value, dict) else {}
    result: dict[tuple[str, str, str], str] = {}
    for asset_type in _ASSET_TYPES:
        rows = source.get(asset_type) if isinstance(source.get(asset_type), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            asset_id = str(row.get("id") or "").strip()
            if not asset_id:
                continue
            versions = row.get("stateVersions") if isinstance(row.get("stateVersions"), list) else []
            for version in versions:
                if not isinstance(version, dict):
                    continue
                version_id = str(
                    version.get("versionId")
                    or version.get("version_id")
                    or version.get("mediaVersionId")
                    or version.get("media_version_id")
                    or version.get("id")
                    or ""
                ).strip()
                tag = str(version.get("tag") or version.get("stateTag") or version.get("state_tag") or "").strip()
                if version_id and tag:
                    result[(asset_type, asset_id, version_id)] = tag
    return result


def _plot_asset_hints_for_prompt(value: Any, assets: Any) -> dict[str, list[Any]]:
    source = value if isinstance(value, dict) else {}
    state_tags = _asset_state_tag_map_for_prompt(assets)
    result: dict[str, list[Any]] = {asset_type: [] for asset_type in _ASSET_TYPES}
    for asset_type in _ASSET_TYPES:
        rows = source.get(asset_type)
        if rows is None:
            continue
        if not isinstance(rows, list):
            rows = [rows]
        values: list[Any] = []
        for row in rows:
            if isinstance(row, dict):
                asset_id = str(row.get("id") or "").strip()
                version_id = str(row.get("versionId") or row.get("version_id") or "").strip()
                state_tag = str(row.get("stateTag") or row.get("state_tag") or row.get("tag") or "").strip()
                if not state_tag and asset_id and version_id:
                    state_tag = state_tags.get((asset_type, asset_id, version_id), "")
                if not asset_id:
                    continue
                values.append({"id": asset_id, "stateTag": state_tag} if state_tag else asset_id)
            else:
                asset_id = str(row or "").strip()
                if asset_id:
                    values.append(asset_id)
        result[asset_type] = values
    return result


def _plot_asset_bindings_for_prompt(value: Any, assets: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    state_tags = _asset_state_tag_map_for_prompt(assets)
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = copy.deepcopy(row)
        asset_type = _analyze_assets_asset_type_key(item.get("assetType") or item.get("asset_type") or item.get("type"))
        asset_id = str(item.get("id") or "").strip()
        version_id = str(item.get("versionId") or item.get("version_id") or "").strip()
        state_tag = str(item.get("stateTag") or item.get("state_tag") or item.get("tag") or "").strip()
        if not state_tag and asset_type and asset_id and version_id:
            state_tag = state_tags.get((asset_type, asset_id, version_id), "")
        item.pop("assetId", None)
        item.pop("versionId", None)
        item.pop("version_id", None)
        item.pop("mediaVersionId", None)
        item.pop("media_version_id", None)
        if asset_id:
            item["id"] = asset_id
        if state_tag:
            item["stateTag"] = state_tag
        result.append({key: value for key, value in item.items() if value not in (None, "", [], {})})
    return result


def _plot_split_proposal_for_prompt(value: Any, assets: Any) -> dict[str, Any]:
    proposal = copy.deepcopy(value if isinstance(value, dict) else {})
    items = proposal.get("items") if isinstance(proposal.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        item.pop("sourcePreview", None)
        item.pop("source_preview", None)
        if isinstance(item.get("assetHints"), dict):
            item["assetHints"] = _plot_asset_hints_for_prompt(item.get("assetHints"), assets)
        if isinstance(item.get("assetBindings"), list):
            item["assetBindings"] = _plot_asset_bindings_for_prompt(item.get("assetBindings"), assets)
    return proposal


def _analyze_assets_phase_context(context: dict[str, Any], *, phase: str) -> dict[str, Any]:
    if phase == "candidates":
        return _strip_empty_prompt_fields({"sourceText": copy.deepcopy(context.get("sourceText"))})
    common_keys = ("sourceText", "assets", "assetContextSnippets")
    result = {
        key: copy.deepcopy(context.get(key))
        for key in common_keys
        if key in context
    }
    if "assets" in result:
        result["assets"] = _analyze_assets_phase_asset_catalog(result.get("assets"), phase=phase)
    return _strip_empty_prompt_fields(result)


def _asset_tagged_media_versions_for_context(
    row: dict[str, Any],
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    versions = row.get("mediaVersions") if isinstance(row.get("mediaVersions"), list) else []
    active_id = str(row.get("activeMediaVersionId") or "").strip()
    by_tag: dict[str, dict[str, str]] = {}
    for version in versions:
        if not isinstance(version, dict):
            continue
        version_id = str(version.get("id") or version.get("versionId") or "").strip()
        state_tags = version.get("stateTags") if isinstance(version.get("stateTags"), list) else []
        direct_tag = str(version.get("stateTag") or version.get("state_tag") or "").strip()
        tags = [direct_tag] if direct_tag else []
        tags.extend(str(tag).strip() for tag in state_tags if str(tag or "").strip())
        if not version_id or not tags:
            continue
        for state_tag in tags:
            tag_key = state_tag.casefold()
            existing = by_tag.get(tag_key)
            if not existing or version_id == active_id:
                by_tag[tag_key] = {"tag": state_tag, "versionId": version_id}
    result = list(by_tag.values())
    if limit is not None and limit > 0:
        return result[:limit]
    return result


def _asset_design_catalog_rows(
    project_id: str,
    *,
    include_state_versions: bool = False,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    assets = list_assets("project", project_id, hydrate=False, lifecycle_status="active", persist_normalization=False)
    result: dict[str, list[dict[str, Any]]] = {}
    total_counts: dict[str, int] = {}
    included_counts: dict[str, int] = {}
    for asset_type in _ASSET_TYPES:
        rows = assets.get(asset_type) if isinstance(assets, dict) else []
        compact_rows: list[dict[str, Any]] = []
        total_count = 0
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("title") or "").strip()
            if not name:
                continue
            total_count += 1
            if len(compact_rows) >= _ASSET_CATALOG_LIMIT_PER_TYPE:
                continue
            prompts = row.get("prompts") if isinstance(row.get("prompts"), dict) else {}
            raw_prompt = str(prompts.get("assetImagePrompt") or "").strip()
            prompt_preview = _compact_text(raw_prompt, _ASSET_CATALOG_PROMPT_PREVIEW_CHARS)
            item: dict[str, Any] = {
                "id": str(row.get("id") or "").strip(),
                "name": name,
                "desc": _compact_text(row.get("desc") or row.get("description"), _ASSET_CATALOG_DESC_CHARS),
                "aliases": copy.deepcopy(row.get("aliases") or []),
            }
            if prompt_preview:
                item["assetImagePromptPreview"] = prompt_preview
                if len(raw_prompt) > len(prompt_preview):
                    item["assetImagePromptPreviewOnly"] = True
            if asset_type in {"characters", "creatures"}:
                item["voiceStyle"] = _compact_text(
                    row.get("voiceStyle") or row.get("voice_style"),
                    _ASSET_CATALOG_VOICE_STYLE_CHARS,
                )
            if asset_type == "creatures":
                item["canSpeak"] = bool(item.get("voiceStyle"))
            if include_state_versions:
                tagged_versions = _asset_tagged_media_versions_for_context(row)
                if tagged_versions:
                    item["stateVersions"] = tagged_versions
            compact_rows.append({key: value for key, value in item.items() if value not in (None, "", [], {})})
        result[asset_type] = compact_rows
        total_counts[asset_type] = total_count
        included_counts[asset_type] = len(compact_rows)
    truncated_types = [
        asset_type
        for asset_type in _ASSET_TYPES
        if total_counts.get(asset_type, 0) > included_counts.get(asset_type, 0)
    ]
    return result, {
        "limitPerType": _ASSET_CATALOG_LIMIT_PER_TYPE,
        "descChars": _ASSET_CATALOG_DESC_CHARS,
        "assetImagePromptPreviewChars": _ASSET_CATALOG_PROMPT_PREVIEW_CHARS,
        "voiceStyleChars": _ASSET_CATALOG_VOICE_STYLE_CHARS,
        "totalCounts": total_counts,
        "includedCounts": included_counts,
        "truncatedTypes": truncated_types,
        "catalogFile": "assets/assets.json",
        "retrievalRule": (
            "assets 是紧凑索引，只用于优先识别同一资产、别名和连续性；"
            "truncatedTypes 非空、当前称谓无法确认身份，或需要精确既有 assetImagePrompt/voiceStyle 时，"
            "在 coverageAudit.unresolved 写清疑点；controller 保存前会从完整资产库回填可复用提示词。"
        ),
    }


def _analyze_assets_phase_asset_catalog(
    assets: dict[str, Any] | None,
    *,
    phase: str,
    candidates: dict[str, Any] | None = None,
    asset_types: tuple[str, ...] | list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(assets, dict):
        return {}
    selected_asset_types = {
        str(asset_type)
        for asset_type in (asset_types or _ASSET_TYPES)
        if str(asset_type) in _ASSET_TYPES
    } or set(_ASSET_TYPES)
    candidates_provided = isinstance(candidates, dict)
    candidate_ids: set[str] = set()
    candidate_names: set[str] = set()
    if isinstance(candidates, dict):
        for asset_type in _ASSET_TYPES:
            rows = candidates.get(asset_type)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                asset_id = str(row.get("assetId") or "").strip()
                name = str(row.get("name") or "").strip()
                if asset_id:
                    candidate_ids.add(asset_id)
                if name:
                    candidate_names.add(name)
    result: dict[str, list[dict[str, Any]]] = {}
    for asset_type in _ASSET_TYPES:
        if asset_type not in selected_asset_types:
            continue
        rows = assets.get(asset_type) if isinstance(assets.get(asset_type), list) else []
        compact_rows: list[dict[str, Any]] = []
        if phase == "design" and candidates_provided and not candidate_ids and not candidate_names:
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            asset_id = str(row.get("id") or "").strip()
            name = str(row.get("name") or row.get("title") or "").strip()
            if not asset_id or not name:
                continue
            if (
                phase == "design"
                and candidates_provided
                and asset_id not in candidate_ids
                and name not in candidate_names
            ):
                continue
            item: dict[str, Any] = {"id": asset_id, "name": name}
            aliases = row.get("aliases")
            if aliases and phase in {"candidates", "review"}:
                item["aliases"] = [
                    _compact_text(alias, 30)
                    for alias in aliases
                    if str(alias or "").strip()
                ][:5]
            if phase == "review":
                desc = _compact_text(row.get("desc") or row.get("description"), 50)
                if desc:
                    item["desc"] = desc
            if phase == "review" and asset_type in {"characters", "creatures"}:
                voice_style = _compact_text(row.get("voiceStyle") or row.get("voice_style"), 120)
                if voice_style:
                    item["voiceStyle"] = voice_style
            if phase == "review" and asset_type == "creatures":
                item["canSpeak"] = bool(item.get("voiceStyle"))
            compact_rows.append({key: value for key, value in item.items() if value not in (None, "", [], {})})
        if compact_rows:
            result[asset_type] = compact_rows
    return result


def _analyze_assets_design_context_snippets(
    context: dict[str, Any],
    candidates: dict[str, Any],
    revision_feedback: dict[str, Any] | None,
    *,
    asset_types: tuple[str, ...] | list[str],
    max_snippets: int = 4,
    excerpt_limit: int = 650,
    total_limit: int = 2400,
) -> list[dict[str, Any]]:
    snippets = context.get("assetContextSnippets")
    if not isinstance(snippets, list):
        return []
    terms = _revision_feedback_terms(revision_feedback)
    for asset_type in asset_types:
        rows = candidates.get(asset_type)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if name and name not in terms:
                terms.append(name)
    selected: list[dict[str, Any]] = []
    total = 0
    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        haystack = json.dumps(snippet, ensure_ascii=False)
        if terms and not any(term and term in haystack for term in terms):
            continue
        excerpt = _compact_text(snippet.get("excerpt"), excerpt_limit)
        if not excerpt:
            continue
        row = {
            "relativePath": snippet.get("relativePath"),
            "matchedTerms": [
                _compact_text(term, 30)
                for term in (snippet.get("matchedTerms") if isinstance(snippet.get("matchedTerms"), list) else [])
                if str(term or "").strip()
            ][:8],
            "excerpt": excerpt,
        }
        row = {key: value for key, value in row.items() if value not in (None, "", [], {})}
        row_chars = len(json.dumps(row, ensure_ascii=False))
        if selected and total + row_chars > total_limit:
            break
        selected.append(row)
        total += row_chars
        if len(selected) >= max_snippets:
            break
    return selected


def _normalize_plot_asset_hints(value: Any, assets: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, list[Any]]:
    assets = assets if isinstance(assets, dict) else {}
    allowed: dict[str, set[str]] = {}
    canonical: dict[str, dict[str, str]] = {}
    version_ids: dict[str, dict[str, set[str]]] = {}
    tagged_versions: dict[str, dict[str, dict[str, str]]] = {}
    for asset_type in _ASSET_TYPES:
        rows = assets.get(asset_type) if isinstance(assets.get(asset_type), list) else []
        allowed[asset_type] = set()
        canonical[asset_type] = {}
        version_ids[asset_type] = {}
        tagged_versions[asset_type] = {}
        for item in rows:
            if not isinstance(item, dict):
                continue
            asset_id = str(item.get("id") or "").strip()
            if not asset_id:
                continue
            canonical_id = asset_id
            allowed[asset_type].add(asset_id)
            canonical[asset_type].setdefault(asset_id.casefold(), canonical_id)
            versions = item.get("stateVersions") if isinstance(item.get("stateVersions"), list) else []
            if versions:
                version_ids[asset_type].setdefault(canonical_id, set())
                tagged_versions[asset_type].setdefault(canonical_id, {})
            for version in versions:
                if not isinstance(version, dict):
                    continue
                version_id = str(
                    version.get("versionId")
                    or version.get("version_id")
                    or version.get("mediaVersionId")
                    or version.get("media_version_id")
                    or version.get("id")
                    or ""
                ).strip()
                tag = str(version.get("tag") or version.get("stateTag") or version.get("state_tag") or "").strip()
                if version_id:
                    version_ids[asset_type][canonical_id].add(version_id)
                if version_id and tag:
                    tagged_versions[asset_type][canonical_id].setdefault(tag.casefold(), version_id)
    result: dict[str, list[Any]] = {asset_type: [] for asset_type in _ASSET_TYPES}
    source = value if isinstance(value, dict) else {}
    for asset_type in _ASSET_TYPES:
        rows = source.get(asset_type)
        if rows is None:
            continue
        if not isinstance(rows, list):
            rows = [rows]
        selected: dict[str, Any] = {}
        order: list[str] = []
        for item in rows:
            if isinstance(item, dict):
                text = str(item.get("id") or "").strip()
                raw_version_id = ""
                raw_state_tag = str(item.get("stateTag") or item.get("state_tag") or item.get("tag") or "").strip()
            else:
                text = str(item or "").strip()
                raw_version_id = ""
                raw_state_tag = ""
            if not text:
                continue
            if text not in allowed.get(asset_type, set()) and text.casefold() not in canonical.get(asset_type, {}):
                continue
            normalized = canonical.get(asset_type, {}).get(text.casefold()) or text
            valid_version_ids = version_ids.get(asset_type, {}).get(normalized, set())
            version_id = ""
            if raw_version_id and raw_version_id in valid_version_ids:
                version_id = raw_version_id
            if not version_id and raw_state_tag:
                version_id = tagged_versions.get(asset_type, {}).get(normalized, {}).get(raw_state_tag.casefold(), "")
            hint: Any = {"id": normalized, "versionId": version_id} if version_id else normalized
            if version_id:
                if normalized not in selected or not isinstance(selected[normalized], dict):
                    selected[normalized] = hint
                if normalized not in order:
                    order.append(normalized)
            elif normalized not in selected:
                selected[normalized] = hint
                order.append(normalized)
        result[asset_type] = [selected[key] for key in order]
    return result
