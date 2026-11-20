# -*- coding: utf-8 -*-
"""已有资产候选检索与统一语义身份决定。"""
from __future__ import annotations

import copy
import re
import unicodedata
from .agent_sessions import (
    _project_dir,
)
from .source_text_store import _compact_text
from .store_core import (
    _asset_is_offline,
    _read_json,
)
from .worker_asset_candidates import (
    _analyze_assets_candidate_asset_id,
    _analyze_assets_candidate_decision,
    _analyze_assets_candidate_id,
    _analyze_assets_candidate_id_key,
    _analyze_assets_candidate_is_reuse_existing,
    _analyze_assets_identity_candidate_search_terms,
    _candidate_original_name,
    _normalize_asset_evidence,
)
from .worker_asset_context import (
    _asset_tagged_media_versions_for_context,
)
from .worker_asset_contract import (
    _ASSET_TYPES,
)
from typing import (
    Any,
)


def _iter_analyze_assets_identity_rows(identity_output: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(identity_output, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in (
        "items",
        "decisions",
        "identityDecisions",
        "identity_decisions",
        "matches",
        "results",
        "sameAs",
        "same_as",
    ):
        value = identity_output.get(key)
        if isinstance(value, list):
            rows.extend(copy.deepcopy(row) for row in value if isinstance(row, dict))
    if not rows:
        for asset_type in _ASSET_TYPES:
            value = identity_output.get(asset_type)
            if isinstance(value, list):
                rows.extend(copy.deepcopy(row) for row in value if isinstance(row, dict))
    return rows




def _analyze_assets_identity_asset_id(decision: dict[str, Any]) -> str:
    if not isinstance(decision, dict):
        return ""
    for key in (
        "assetId",
        "existingAssetId",
        "targetAssetId",
        "matchedAssetId",
        "reuseAssetId",
    ):
        value = str(decision.get(key) or "").strip()
        if value:
            return value
    return ""




def _analyze_assets_direct_source_mentions_value(
    value: Any,
    context: dict[str, Any],
    evidence: list[str] | None = None,
) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = unicodedata.normalize("NFKC", text).casefold()
    haystacks = [str(context.get("sourceText") or "")]
    haystacks.extend(str(item or "") for item in (evidence or []) if str(item or "").strip())
    for haystack in haystacks:
        if normalized in unicodedata.normalize("NFKC", haystack).casefold():
            return True
    return False


def _analyze_assets_identity_alias_kind_is_stable(value: Any) -> bool:
    normalized = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if not normalized:
        return True
    return normalized in {"proper_name", "formal_name", "stable_alias", "正式名", "专名", "稳定别名"}


def _analyze_assets_identity_alias_kind_allows_canonical(value: Any) -> bool:
    normalized = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    return normalized in {
        "proper_name",
        "formal_name",
        "true_name",
        "canonical_name",
    }


def _analyze_assets_identity_promotable_canonical_name(
    decision: dict[str, Any],
    *,
    alias_kind: str,
    existing_name: str,
    original_name: str,
    context: dict[str, Any],
    evidence: list[str],
) -> str:
    if not isinstance(decision, dict) or not _analyze_assets_identity_alias_kind_allows_canonical(alias_kind):
        return ""
    values = [
        decision.get("canonicalName"),
        decision.get("canonical_name"),
        decision.get("promoteName"),
        decision.get("promote_name"),
        decision.get("aliasName"),
        decision.get("alias_name"),
        decision.get("currentName"),
        decision.get("current_name"),
        decision.get("candidateName"),
        decision.get("candidate_name"),
        original_name,
    ]
    existing_key = str(existing_name or "").strip().casefold()
    seen: set[str] = set()
    for value in values:
        name = str(value or "").strip()
        key = name.casefold()
        if not name or len(name) > 80 or key in seen or key == existing_key:
            continue
        seen.add(key)
        if not _analyze_assets_direct_source_mentions_value(name, context, evidence):
            continue
        return name
    return ""


def _apply_analyze_assets_identity_output(
    candidates: dict[str, Any],
    identity_output: dict[str, Any],
    *,
    asset_type: str,
    existing_assets: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
    target_candidate_ids: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply a first pass, or mutate only explicitly authorized candidate IDs."""
    updated = copy.deepcopy(candidates)
    target_keys = (
        {_analyze_assets_candidate_id_key(value) for value in target_candidate_ids}
        if target_candidate_ids is not None else None
    )
    if target_keys is not None:
        updated, _ = _prepare_analyze_assets_identity_rerun_candidates(
            updated, asset_type, target_candidate_ids=target_keys,
        )
        if not target_keys:
            return updated, {"reused": 0, "new": 0, "unmatched": 0}
    task_context = context if isinstance(context, dict) else {}
    existing_by_id = {
        str(row.get("id") or "").strip(): row
        for row in existing_assets
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    result_rows = _iter_analyze_assets_identity_rows(identity_output)
    decisions_by_id: dict[str, dict[str, Any]] = {}
    candidate_keys = {_analyze_assets_candidate_id_key(_analyze_assets_candidate_id(row))
                      for row in updated.get(asset_type) or [] if isinstance(row, dict)}
    if target_keys is not None and target_keys - candidate_keys:
        raise ValueError(f"{asset_type} 身份判断目标 candidateId 不存在：{sorted(target_keys - candidate_keys)}")
    for row in result_rows:
        if not isinstance(row, dict):
            continue
        candidate_id_key = _analyze_assets_candidate_id_key(row.get("candidateId") or row.get("candidate_id"))
        if target_keys is not None and candidate_id_key in candidate_keys and candidate_id_key not in target_keys:
            continue
        if not candidate_id_key or candidate_id_key not in candidate_keys or candidate_id_key in decisions_by_id:
            raise ValueError(f"{asset_type} 身份判断包含缺失、未知或重复的 candidateId：{candidate_id_key}")
        decisions_by_id[candidate_id_key] = row
    stats = {"reused": 0, "new": 0, "unmatched": 0}
    next_rows: list[dict[str, Any]] = []
    for row in updated.get(asset_type) or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        item = copy.deepcopy(row)
        if target_keys is not None and _analyze_assets_candidate_id_key(_analyze_assets_candidate_id(item)) not in target_keys:
            next_rows.append(item)
            continue
        if _analyze_assets_candidate_asset_id(item):
            if _analyze_assets_candidate_asset_id(item) not in existing_by_id:
                raise ValueError(f"{asset_type} 候选引用的已有资产不存在")
            stats["reused"] += 1
            next_rows.append(item)
            continue
        if _analyze_assets_candidate_decision(item) in {"skip", "merge", "part_of"}:
            next_rows.append(item)
            continue
        candidate_id = _analyze_assets_candidate_id(item)
        decision = decisions_by_id.get(_analyze_assets_candidate_id_key(candidate_id))
        if not isinstance(decision, dict):
            raise ValueError(f"{asset_type} 候选 {candidate_id} 缺少资产决定，不能默认新增")
        action = str(decision.get("decision") or "").strip()
        if action not in {"reuse_existing", "keep_new", "part_of", "skip", "merge", "unresolved"}:
            raise ValueError(f"{asset_type} 候选 {candidate_id} 的 decision 无效：{action}")
        reason = str(decision.get("reason") or "").strip()
        source_use = str(decision.get("sourceUse") or "").strip()
        independent_need = str(decision.get("independentNeed") or "").strip()
        owner_id = str(decision.get("ownerCandidateId") or "").strip()
        if action != "part_of" and owner_id:
            raise ValueError(f"{candidate_id} 非附属细节决定不能携带归属目标")
        item.pop("ownerCandidateId", None)
        item.pop("sourceUse", None)
        item.pop("independentNeed", None)
        if source_use:
            item["sourceUse"] = source_use
        if independent_need and action == "keep_new":
            item["independentNeed"] = independent_need
        item["identityMethod"] = "model_semantic_identity"
        if action == "unresolved":
            raise ValueError(f"资产身份待确认：{name}；{reason or '需要补充身份信息'}")
        if action == "part_of":
            if asset_type in {"characters", "creatures"}:
                raise ValueError(f"{candidate_id} 活体主体不能按附属细节归入另一资产，请按活体边界判定")
            inventory = {_analyze_assets_candidate_id(r): r for kind in _ASSET_TYPES
                         for r in updated.get(kind) or [] if isinstance(r, dict)}
            if not owner_id or owner_id == candidate_id or owner_id not in inventory:
                raise ValueError(f"{candidate_id} 附属细节的归属目标不存在或指向自身：{owner_id}")
            if not source_use or not reason:
                raise ValueError(f"{candidate_id} 附属细节缺少事实用途或归属理由")
            item.update(decision="skip", needsDesign=False, ownerCandidateId=owner_id,
                        identityReason=reason, designRationale=reason, reason=reason)
            next_rows.append(item)
            continue
        if action in {"skip", "merge"}:
            if not reason:
                raise ValueError(f"{asset_type} 候选 {candidate_id} 缺少{action}理由")
            item.update(decision=action, needsDesign=False, designRationale=reason, reason=reason)
            if action == "merge":
                target_id = str(decision.get("targetCandidateId") or "").strip()
                target = next((r for r in updated.get(asset_type) or []
                               if _analyze_assets_candidate_id_key(_analyze_assets_candidate_id(r)) == _analyze_assets_candidate_id_key(target_id)), None)
                target_decision = decisions_by_id.get(_analyze_assets_candidate_id_key(target_id))
                if target is not None and (
                    target_keys is not None and _analyze_assets_candidate_id_key(target_id) not in target_keys
                    or target_decision is None
                ):
                    target_decision = target
                if (not target or _analyze_assets_candidate_id_key(target_id) == _analyze_assets_candidate_id_key(candidate_id)
                        or _analyze_assets_candidate_decision(target_decision or {}) not in {"keep_new", "reuse_existing"}):
                    raise ValueError(f"{asset_type} 候选 {candidate_id} 合并目标无效或未保留：{target_id}")
                item["mergedInto"] = str(target_decision.get("name") or target.get("name") or "")
                item["targetName"] = item["mergedInto"]
                item["targetCandidateId"] = _analyze_assets_candidate_id(target)
            next_rows.append(item)
            continue
        if action == "reuse_existing":
            asset_id = _analyze_assets_identity_asset_id(decision)
            if not asset_id:
                raise ValueError(f"{asset_type} 候选 {candidate_id or name} 判定复用已有资产时缺少 assetId")
            existing = existing_by_id.get(asset_id)
            if not existing:
                raise ValueError(f"{asset_type} 候选 {candidate_id or name} 判定复用的 assetId 不存在：{asset_id}")
            if existing:
                original_name = name
                existing_name = str(existing.get("name") or decision.get("name") or name).strip()
                existing_asset_type = str(existing.get("assetType") or "").strip()
                evidence = _normalize_asset_evidence(
                    decision.get("sourceEvidence") or decision.get("source_evidence")
                )
                if not evidence:
                    aliases = existing.get("aliases") if isinstance(existing.get("aliases"), list) else []
                    evidence = _source_evidence_for_candidate_names(
                        task_context,
                        [name, decision.get("candidateName"), decision.get("name"), existing.get("name"), *aliases],
                    )
                item["assetId"] = asset_id
                item["name"] = existing_name
                if existing_asset_type and existing_asset_type != asset_type:
                    item["reusedAssetType"] = existing_asset_type
                alias_kind = str(
                    decision.get("aliasKind")
                    or decision.get("alias_kind")
                    or decision.get("aliasType")
                    or decision.get("alias_type")
                    or ""
                ).strip()
                original_name_supported = _analyze_assets_direct_source_mentions_value(
                    original_name,
                    task_context,
                    evidence,
                )
                if (
                    original_name
                    and existing_name
                    and original_name.casefold() != existing_name.casefold()
                    and original_name_supported
                ):
                    item["originalName"] = original_name
                item["decision"] = "reuse_existing"
                item["needsDesign"] = False
                item["identityMethod"] = (
                    "model_semantic_cross_type_identity"
                    if existing_asset_type and existing_asset_type != asset_type
                    else "model_semantic_identity"
                )
                existing_aliases = [
                    str(alias or "").strip()
                    for alias in (existing.get("aliases") if isinstance(existing.get("aliases"), list) else [])
                    if str(alias or "").strip()
                ]
                existing_name_keys = {
                    value.casefold()
                    for value in [existing_name, str(existing.get("title") or "").strip(), *existing_aliases]
                    if value
                }
                canonical_name = _analyze_assets_identity_promotable_canonical_name(
                    decision,
                    alias_kind=alias_kind,
                    existing_name=existing_name,
                    original_name=original_name,
                    context=task_context,
                    evidence=evidence,
                )
                if canonical_name:
                    item["canonicalName"] = canonical_name
                    item["canonicalKind"] = alias_kind or "proper_name"
                if (
                    original_name
                    and existing_name
                    and original_name.casefold() != existing_name.casefold()
                    and original_name.casefold() in existing_name_keys
                    and original_name_supported
                    and not item.get("aliasName")
                ):
                    item["aliasName"] = original_name
                    item["aliasKind"] = alias_kind or "stable_alias"
                    if existing_aliases:
                        item["aliases"] = existing_aliases
                alias_values = [
                    decision.get("aliasName"),
                    decision.get("alias_name"),
                    decision.get("currentName"),
                    decision.get("current_name"),
                    decision.get("currentMention"),
                    decision.get("current_mention"),
                ]
                decision_candidate_name = str(decision.get("candidateName") or decision.get("candidate_name") or "").strip()
                if decision_candidate_name:
                    alias_values.append(decision_candidate_name)
                if original_name:
                    alias_values.append(original_name)
                new_aliases: list[str] = []
                if _analyze_assets_identity_alias_kind_is_stable(alias_kind):
                    for alias_value in alias_values:
                        alias = str(alias_value or "").strip()
                        alias_key = alias.casefold()
                        if not alias or alias_key in existing_name_keys:
                            continue
                        if not _analyze_assets_direct_source_mentions_value(alias, task_context, evidence):
                            continue
                        if alias_key in {value.casefold() for value in new_aliases}:
                            continue
                        new_aliases.append(alias)
                if new_aliases:
                    item["aliasName"] = new_aliases[0]
                    if alias_kind:
                        item["aliasKind"] = alias_kind
                    item["aliases"] = [*existing_aliases, *new_aliases]
                reason = str(decision.get("reason") or "").strip()
                if reason:
                    item["identityReason"] = _compact_text(reason, 120)
                    item["designRationale"] = _compact_text(reason, 120)
                if evidence:
                    item["sourceEvidence"] = evidence[:2]
                stats["reused"] += 1
                next_rows.append(item)
                continue
        if asset_type in {"scenes", "props"} and (not source_use or not independent_need):
            raise ValueError(f"{candidate_id} 新增资产缺少事实用途或独立管理依据")
        item["decision"] = "keep_new"
        item["needsDesign"] = True
        new_name = str(decision.get("name") or name).strip()
        existing_names = {str(value).strip().casefold() for asset in existing_assets
                          for value in [asset.get("name"), *(asset.get("aliases") or [])] if value}
        if not new_name or new_name.casefold() in existing_names:
            raise ValueError(f"{asset_type} 候选 {candidate_id} 已判新增，但名称与已有资产冲突；请按真实身份区分名称")
        if new_name != name:
            item["originalName"] = name
            item["name"] = new_name
        item["identityReason"] = reason
        item["designRationale"] = reason
        if isinstance(decision, dict):
            evidence = _normalize_asset_evidence(
                decision.get("sourceEvidence") or decision.get("source_evidence")
            )
            if not evidence:
                evidence = _source_evidence_for_candidate_names(
                    task_context,
                    [name, decision.get("candidateName"), decision.get("name")],
                )
            if evidence:
                item["sourceEvidence"] = evidence[:2]
        stats["new"] += 1
        next_rows.append(item)
    updated[asset_type] = next_rows
    return updated, stats


def _analyze_assets_identity_source_hints(
    context: dict[str, Any],
    candidates: dict[str, Any],
    asset_type: str,
) -> list[dict[str, Any]]:
    rows = candidates.get(asset_type) if isinstance(candidates, dict) else []
    hints: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return hints
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate_id = str(row.get("candidateId") or row.get("candidate_id") or "").strip()
        name = str(row.get("name") or row.get("candidateName") or row.get("assetName") or "").strip()
        if not candidate_id or not name:
            continue
        evidence: list[str] = []
        source_evidence = row.get("sourceEvidence") or row.get("source_evidence")
        if isinstance(source_evidence, list):
            for item in source_evidence:
                text = _compact_text(item, 118)
                if text and text not in evidence:
                    evidence.append(text)
                if len(evidence) >= 2:
                    break
        names = _analyze_assets_identity_candidate_search_terms(row, name)
        if not names:
            names = [name, _candidate_original_name(row, name)]
        search_evidence = _source_identity_evidence_for_candidate_names(
            context,
            names,
            window=36,
            limit=118,
            max_items=max(0, 2 - len(evidence)),
        )
        for item in search_evidence:
            if item and item not in evidence:
                evidence.append(item)
            if len(evidence) >= 2:
                break
        if evidence:
            hints.append({"candidateId": candidate_id, "sourceHints": evidence})
    return hints


def _source_evidence_for_candidate_names(
    context: dict[str, Any],
    names: list[Any] | tuple[Any, ...],
    *,
    window: int = 28,
    limit: int = 96,
) -> list[str]:
    source_text = str(context.get("sourceText") or "")
    if not source_text:
        return []
    for value in names:
        needle = str(value or "").strip()
        if not needle:
            continue
        index = source_text.find(needle)
        if index < 0:
            continue
        start = max(0, index - max(0, window))
        end = min(len(source_text), index + len(needle) + max(0, window))
        if limit > 0 and end - start > limit:
            budget = max(len(needle), limit)
            side = max(0, (budget - len(needle)) // 2)
            start = max(0, index - side)
            end = min(len(source_text), start + budget)
            if index + len(needle) > end:
                end = min(len(source_text), index + len(needle))
                start = max(0, end - budget)
        excerpt = source_text[start:end].strip()
        if excerpt:
            return [excerpt]
    return []


def _identity_source_search_variants(value: Any) -> list[str]:
    text = re.sub(r"\s+", "", str(value or "")).strip()
    if not text:
        return []
    variants = [text]
    # For short compound names, a stable suffix often carries the actual object
    # noun while the full phrase may only appear in a later comparison.
    if 4 <= len(text) <= 6:
        variants.append(text[-3:])
    if len(text) == 4:
        variants.append(text[-2:])
    result: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        if variant and variant not in seen:
            seen.add(variant)
            result.append(variant)
    return result


def _source_identity_evidence_for_candidate_names(
    context: dict[str, Any],
    names: list[Any] | tuple[Any, ...],
    *,
    window: int = 36,
    limit: int = 118,
    max_items: int = 2,
) -> list[str]:
    source_text = str(context.get("sourceText") or "")
    if not source_text or max_items <= 0:
        return []
    matches: list[tuple[int, str]] = []
    seen_match: set[tuple[int, str]] = set()
    for value in names:
        for needle in _identity_source_search_variants(value):
            start_at = 0
            while True:
                index = source_text.find(needle, start_at)
                if index < 0:
                    break
                key = (index, needle)
                if key not in seen_match:
                    seen_match.add(key)
                    matches.append((index, needle))
                start_at = index + max(1, len(needle))
    if not matches:
        return []
    matches.sort(key=lambda item: item[0])
    selected: list[tuple[int, str]] = [matches[0]]
    if len(matches) > 1 and matches[-1][0] != matches[0][0]:
        selected.append(matches[-1])
    evidence: list[str] = []
    seen_text: set[str] = set()
    for index, needle in selected:
        start = max(0, index - max(0, window))
        end = min(len(source_text), index + len(needle) + max(0, window))
        if limit > 0 and end - start > limit:
            budget = max(len(needle), limit)
            side = max(0, (budget - len(needle)) // 2)
            start = max(0, index - side)
            end = min(len(source_text), start + budget)
            if index + len(needle) > end:
                end = min(len(source_text), index + len(needle))
                start = max(0, end - budget)
        excerpt = source_text[start:end].strip()
        excerpt = re.sub(r"\s+", " ", excerpt).strip()
        if excerpt and excerpt not in seen_text:
            seen_text.add(excerpt)
            evidence.append(excerpt)
        if len(evidence) >= max_items:
            break
    return evidence


def _existing_asset_lookup_rows(
    project_id: str,
    context: dict[str, Any],
    asset_type: str,
    *,
    include_state_versions: bool = False,
) -> list[dict[str, Any]]:
    rows = _asset_existing_rows_for_validation(project_id, context, asset_type)
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        asset_id = str(row.get("id") or "").strip()
        if not asset_id or asset_id in seen_ids:
            continue
        seen_ids.add(asset_id)
        item: dict[str, Any] = {
            "id": asset_id,
            "assetType": asset_type,
            "name": str(row.get("name") or row.get("title") or "").strip(),
            "aliases": copy.deepcopy(row.get("aliases") if isinstance(row.get("aliases"), list) else []),
            "desc": _compact_text(row.get("desc") or row.get("description"), 120),
        }
        if asset_type in {"characters", "creatures"}:
            item["voiceStyle"] = _compact_text(row.get("voiceStyle") or row.get("voice_style"), 80)
        if asset_type == "creatures":
            item["canSpeak"] = bool(item.get("voiceStyle"))
        if include_state_versions:
            tagged_versions = _asset_tagged_media_versions_for_context(row)
            if tagged_versions:
                item["stateVersions"] = tagged_versions
        result.append({key: value for key, value in item.items() if value not in (None, "", [], {})})
    return result


def _existing_asset_identity_lookup_rows(
    project_id: str,
    context: dict[str, Any],
    asset_type: str,
) -> list[dict[str, Any]]:
    target_types = [asset_type]
    if asset_type == "characters":
        target_types.append("creatures")
    elif asset_type == "creatures":
        target_types.append("characters")

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for current_type in target_types:
        if current_type not in _ASSET_TYPES:
            continue
        evidence_by_id = {
            str(row.get("id") or ""): row
            for row in _asset_existing_rows_for_validation(project_id, context, current_type)
        }
        for row in _existing_asset_lookup_rows(project_id, context, current_type):
            if not isinstance(row, dict):
                continue
            asset_id = str(row.get("id") or "").strip()
            name = str(row.get("name") or row.get("title") or "").strip()
            if not asset_id or asset_id in seen:
                continue
            seen.add(asset_id)
            item = copy.deepcopy(row)
            if evidence_by_id:
                original = evidence_by_id.get(asset_id, {})
                item["desc"] = _compact_text(original.get("desc") or original.get("description"), 360)
                item["sourceEvidence"] = [
                    _compact_text(ref.get("sourcePreview"), 240)
                    for ref in (original.get("sourceRefs") or [])
                    if isinstance(ref, dict) and ref.get("sourcePreview")
                ][:3]
            item["assetType"] = current_type
            item["identityScope"] = "same_type" if current_type == asset_type else "cross_type_living"
            result.append(item)
    return result




def _retrieve_existing_asset_matches(
    project_id: str,
    context: dict[str, Any],
    candidates: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Retrieve identity candidates; a name match is never an identity decision."""
    checked = copy.deepcopy(candidates)
    stats = {}
    for asset_type in _ASSET_TYPES:
        existing = _existing_asset_identity_lookup_rows(project_id, context, asset_type)
        matches = 0
        for item in checked.get(asset_type) or []:
            if not isinstance(item, dict) or _analyze_assets_candidate_asset_id(item):
                continue
            name = str(item.get("name") or "").strip().casefold()
            related = [
                {"id": row["id"], "name": row["name"], "assetType": row.get("assetType", asset_type)}
                for row in existing
                if name and name in {
                    str(value).strip().casefold()
                    for value in [row.get("name"), *(row.get("aliases") or [])]
                }
            ]
            if related:
                item["existingMatches"] = related
                matches += 1
        stats[asset_type] = {"matched": matches}
    checked["existingAssetMatches"] = {"status": "completed", "stats": stats}
    return checked, stats


def _prepare_analyze_assets_identity_rerun_candidates(
    candidates: dict[str, Any],
    asset_type: str,
    *,
    target_candidate_ids: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reopen explicit targets only; None and an empty set both leave state intact."""
    updated = copy.deepcopy(candidates)
    target_keys = {_analyze_assets_candidate_id_key(value) for value in (target_candidate_ids or set())}
    rows = updated.get(asset_type)
    if not isinstance(rows, list) or not target_keys:
        return updated, {"reopened": 0}
    stats = {"reopened": 0}
    reuse_keys = (
        "assetId",
        "asset_id",
        "existingAssetId",
        "existing_asset_id",
        "targetAssetId",
        "target_asset_id",
        "matchedAssetId",
        "matched_asset_id",
        "dedupMethod",
        "identityMethod",
        "canonicalName",
        "canonicalKind",
        "aliasName",
        "aliasKind",
        "aliases",
        "reusedAssetType",
        "ownerCandidateId",
        "targetCandidateId",
        "targetName",
        "targetType",
        "targetCandidateIds",
        "targetNames",
        "mergedInto",
        "reason",
        "rationale",
        "identityReason",
        "designRationale",
        "independentNeed",
        "identityRerunFromReuse",
    )
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if _analyze_assets_candidate_id_key(_analyze_assets_candidate_id(row)) not in target_keys:
            continue
        was_reuse = bool(_analyze_assets_candidate_asset_id(row) or _analyze_assets_candidate_is_reuse_existing(row))
        item = copy.deepcopy(row)
        previous_name = str(item.get("name") or "").strip()
        current_name = str(item.get("originalName") or item.get("original_name") or "").strip()
        if was_reuse and current_name and previous_name and current_name.casefold() != previous_name.casefold():
            item["previousMatchedName"] = previous_name
            item["name"] = current_name
        for key in reuse_keys:
            item.pop(key, None)
        item["decision"] = "keep_new"
        item["needsDesign"] = True
        if was_reuse:
            item["identityRerunFromReuse"] = True
        rows[index] = item
        stats["reopened"] += 1
    return updated, stats


def _asset_context_existing_rows(task_context: dict[str, Any], asset_type: str) -> list[dict[str, Any]]:
    assets = task_context.get("assets") if isinstance(task_context.get("assets"), dict) else {}
    rows = assets.get(asset_type) if isinstance(assets.get(asset_type), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _asset_store_existing_rows(project_id: str, asset_type: str) -> list[dict[str, Any]]:
    if not project_id:
        return []
    try:
        assets = _read_json(_project_dir(project_id) / "assets" / "assets.json", {})
    except Exception:
        return []
    if not isinstance(assets, dict):
        return []
    rows = assets.get(asset_type)
    return [row for row in rows if isinstance(row, dict) and not _asset_is_offline(row)] if isinstance(rows, list) else []


def _asset_existing_rows_for_validation(
    project_id: str,
    task_context: dict[str, Any],
    asset_type: str,
) -> list[dict[str, Any]]:
    rows = [copy.deepcopy(row) for row in _asset_store_existing_rows(project_id, asset_type)]
    stored_ids = {str(row.get("id") or "") for row in rows}
    rows.extend(copy.deepcopy(row) for row in _asset_context_existing_rows(task_context, asset_type)
                if str(row.get("id") or "") not in stored_ids)
    return rows
