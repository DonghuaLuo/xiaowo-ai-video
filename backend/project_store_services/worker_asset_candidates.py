# -*- coding: utf-8 -*-
"""资产候选分类、保留决策和候选列表合并。"""
from __future__ import annotations

import copy
import json
import re
from .assets import (
    _asset_type_label,
)
from .reference_utils import (
    is_short_asset_candidate_id as _is_short_asset_candidate_id,
    short_asset_candidate_id as _short_asset_candidate_id,
)
from .source_text_store import _compact_text
from .worker_asset_contract import (
    _ANALYZE_ASSETS_AUDIT_PLACEHOLDER_MARKERS,
    _ANALYZE_ASSETS_DESIGN_BATCH_LIMITS,
    _ANALYZE_ASSETS_KEEP_DECISIONS,
    _ANALYZE_ASSETS_MERGE_DECISIONS,
    _ANALYZE_ASSETS_NEW_DESIGN_DECISIONS,
    _ANALYZE_ASSETS_REUSE_DECISIONS,
    _ANALYZE_ASSETS_SKIP_DECISIONS,
    _ASSET_TYPES,
)
from .worker_text import (
    _review_text,
)
from typing import (
    Any,
)


def _analyze_assets_candidate_review_name_lists(candidates: dict[str, Any]) -> dict[str, list[str]]:
    normalized = _normalize_analyze_assets_candidates(candidates)
    result: dict[str, list[str]] = {}
    for asset_type in _ASSET_TYPES:
        rows: list[str] = []
        seen: set[str] = set()
        for row in normalized.get(asset_type) or []:
            name = _candidate_asset_name(row).strip()
            key = name.casefold()
            if not name or key in seen:
                continue
            seen.add(key)
            rows.append(name)
        result[asset_type] = rows
    return result


def _analyze_assets_asset_type_key(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    aliases = {
        "character": "characters",
        "characters": "characters",
        "person": "characters",
        "people": "characters",
        "角色": "characters",
        "人物": "characters",
        "creature": "creatures",
        "creatures": "creatures",
        "being": "creatures",
        "beings": "creatures",
        "monster": "creatures",
        "monsters": "creatures",
        "生物": "creatures",
        "怪物": "creatures",
        "活体": "creatures",
        "scene": "scenes",
        "scenes": "scenes",
        "location": "scenes",
        "locations": "scenes",
        "place": "scenes",
        "places": "scenes",
        "场景": "scenes",
        "空间": "scenes",
        "地点": "scenes",
        "prop": "props",
        "props": "props",
        "item": "props",
        "items": "props",
        "object": "props",
        "objects": "props",
        "道具": "props",
        "物件": "props",
        "器物": "props",
    }
    return aliases.get(text, "")


def _analyze_assets_candidates_for_types(
    candidates: dict[str, Any],
    asset_types: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    selected = {str(item) for item in asset_types if str(item) in _ASSET_TYPES}
    result = copy.deepcopy(candidates if isinstance(candidates, dict) else {})
    for asset_type in _ASSET_TYPES:
        if asset_type not in selected:
            result[asset_type] = []
    return result


def _analyze_assets_identity_candidate_row(row: dict[str, Any]) -> dict[str, Any]:
    candidate_id = str(row.get("candidateId") or row.get("candidate_id") or "").strip()
    name = str(row.get("name") or row.get("candidateName") or row.get("assetName") or "").strip()
    item = {
        "candidateId": candidate_id,
        "name": name,
    }
    original_name = _candidate_original_name(row, name)
    if original_name and original_name != name:
        item["originalName"] = original_name
    if row.get("existingMatches"):
        item["existingMatches"] = copy.deepcopy(row["existingMatches"])
    return {key: value for key, value in item.items() if value not in (None, "", [], {})}


def _analyze_assets_identity_candidates_for_type(
    candidates: dict[str, Any],
    asset_type: str,
) -> dict[str, Any]:
    rows = candidates.get(asset_type) if isinstance(candidates, dict) else []
    compact_rows: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not _analyze_assets_candidate_needs_design(row):
                continue
            item = _analyze_assets_identity_candidate_row(row)
            if item:
                compact_rows.append(item)
    return {asset_type: compact_rows}


def _analyze_assets_identity_existing_assets(existing_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact_rows: list[dict[str, Any]] = []
    for row in existing_assets:
        if not isinstance(row, dict):
            continue
        asset_id = str(row.get("id") or "").strip()
        name = str(row.get("name") or row.get("title") or row.get("assetName") or "").strip()
        if not asset_id or not name:
            continue
        item: dict[str, Any] = {"id": asset_id, "name": name}
        asset_type = str(row.get("assetType") or row.get("type") or "").strip()
        if asset_type:
            item["assetType"] = asset_type
        identity_scope = str(row.get("identityScope") or "").strip()
        if identity_scope:
            item["identityScope"] = identity_scope
        item["desc"] = _compact_text(row.get("desc"), 360)
        item["sourceEvidence"] = copy.deepcopy(row.get("sourceEvidence") or [])[:3]
        aliases = row.get("aliases")
        if isinstance(aliases, list):
            compact_aliases = [
                _compact_text(alias, 28)
                for alias in aliases
                if str(alias or "").strip()
            ][:6]
            if compact_aliases:
                item["aliases"] = compact_aliases
        compact_rows.append(item)
    return compact_rows


def _analyze_assets_identity_candidate_search_terms(row: dict[str, Any], name: str) -> list[str]:
    raw_values: list[Any] = [name, _candidate_original_name(row, name)]
    aliases = row.get("aliases")
    if isinstance(aliases, list):
        raw_values.extend(aliases[:4])
    terms: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        text = str(value or "").strip()
        if not text:
            continue
        variants = [text]
        if "的" in text:
            tail = text.rsplit("的", 1)[-1].strip()
            if len(tail) >= 2:
                variants.append(tail)
        for variant in variants:
            key = variant.casefold()
            if key in seen:
                continue
            seen.add(key)
            terms.append(variant)
    return terms


def _analyze_assets_coverage_table_for_types(
    coverage_table: Any,
    asset_types: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    if not isinstance(coverage_table, dict):
        return {}
    selected = {str(asset_type) for asset_type in asset_types if str(asset_type) in _ASSET_TYPES}
    if not selected:
        return {}
    result: dict[str, Any] = {}
    asset_type_rows = coverage_table.get("assetTypes")
    if isinstance(asset_type_rows, dict):
        result["assetTypes"] = {
            asset_type: copy.deepcopy(asset_type_rows.get(asset_type) or [])
            for asset_type in _ASSET_TYPES
            if asset_type in selected
        }
    summary = coverage_table.get("summary")
    if isinstance(summary, dict):
        result["summary"] = copy.deepcopy(summary)
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def _analyze_assets_candidate_has_rows(candidates: dict[str, Any] | None, asset_type: str) -> bool:
    if not isinstance(candidates, dict):
        return False
    rows = candidates.get(asset_type)
    if not isinstance(rows, list):
        return False
    for row in rows:
        if isinstance(row, str) and row.strip():
            return True
        if not isinstance(row, dict):
            continue
        if _analyze_assets_candidate_is_kept(row) and str(row.get("assetId") or row.get("name") or row.get("assetName") or "").strip():
            return True
    return False


def _analyze_assets_candidate_asset_id(row: dict[str, Any]) -> str:
    return str(row.get("assetId") or row.get("asset_id") or "").strip()


def _analyze_assets_candidate_decision(row: dict[str, Any]) -> str:
    if not isinstance(row, dict):
        return ""
    for key in ("decision", "boundaryDecision", "assetDecision", "keepDecision"):
        value = str(row.get(key) or "").strip().casefold()
        if value:
            return value
    return ""


def _analyze_assets_candidate_is_kept(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    decision = _analyze_assets_candidate_decision(row)
    if not decision:
        return False
    return decision in {item.casefold() for item in _ANALYZE_ASSETS_KEEP_DECISIONS}


def _analyze_assets_candidate_is_reuse_existing(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    decision = _analyze_assets_candidate_decision(row).replace("-", "_")
    if decision in {item.casefold() for item in _ANALYZE_ASSETS_REUSE_DECISIONS}:
        return True
    return False


def _analyze_assets_candidate_has_new_design_decision(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    decision = _analyze_assets_candidate_decision(row).replace("-", "_")
    return decision in {item.casefold() for item in _ANALYZE_ASSETS_NEW_DESIGN_DECISIONS}


def _analyze_assets_candidate_has_skip_decision(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    decision = _analyze_assets_candidate_decision(row).replace("-", "_")
    return decision in {item.casefold().replace("-", "_") for item in _ANALYZE_ASSETS_SKIP_DECISIONS}


def _analyze_assets_candidate_has_merge_decision(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    decision = _analyze_assets_candidate_decision(row).replace("-", "_")
    return decision in {item.casefold().replace("-", "_") for item in _ANALYZE_ASSETS_MERGE_DECISIONS}


def _analyze_assets_candidate_needs_design(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    if _analyze_assets_candidate_has_skip_decision(row) or _analyze_assets_candidate_has_merge_decision(row):
        return False
    if not _analyze_assets_candidate_is_kept(row):
        return False
    if _analyze_assets_candidate_asset_id(row):
        return False
    if _analyze_assets_candidate_is_reuse_existing(row):
        return False
    if not _analyze_assets_candidate_has_new_design_decision(row):
        return False
    return bool(str(row.get("name") or "").strip())


def _analyze_assets_candidate_type_needs_design(candidates: dict[str, Any] | None, asset_type: str) -> bool:
    if not isinstance(candidates, dict):
        return False
    rows = candidates.get(asset_type)
    if not isinstance(rows, list):
        return False
    return any(
        bool(str(row or "").strip()) if isinstance(row, str) else _analyze_assets_candidate_needs_design(row)
        for row in rows
        if isinstance(row, (dict, str))
    )


def _analyze_assets_feedback_text(value: Any) -> str:
    parts: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for child in item.values():
                walk(child)
            return
        if isinstance(item, list):
            for child in item:
                walk(child)
            return
        text = str(item or "").strip()
        if text:
            parts.append(text)

    walk(value)
    return "\n".join(parts)


def _analyze_assets_design_candidates_for_types(
    candidates: dict[str, Any],
    asset_types: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    result = _analyze_assets_candidates_for_types(candidates, asset_types)
    for asset_type in _ASSET_TYPES:
        rows = result.get(asset_type)
        if not isinstance(rows, list):
            result[asset_type] = []
            continue
        result[asset_type] = [
            copy.deepcopy(row)
            for row in rows
            if isinstance(row, dict) and _analyze_assets_candidate_needs_design(row)
        ]
    coverage = result.get("coverageAudit") if isinstance(result.get("coverageAudit"), dict) else {}
    if coverage:
        result["coverageAudit"] = {
            "checked": coverage.get("checked") is True,
            "mergeDecisions": [],
            "skippedMentions": [],
            "unresolved": [],
        }
    result["notes"] = []
    return result


def _analyze_assets_design_rows_for_type(candidates: dict[str, Any], asset_type: str) -> list[dict[str, Any]]:
    if asset_type not in _ASSET_TYPES or not isinstance(candidates, dict):
        return []
    rows = candidates.get(asset_type)
    if not isinstance(rows, list):
        return []
    return [
        copy.deepcopy(row)
        for row in rows
        if isinstance(row, dict) and _analyze_assets_candidate_needs_design(row)
    ]


def _chunk_analyze_assets_design_rows(rows: list[dict[str, Any]], asset_type: str) -> list[list[dict[str, Any]]]:
    if not rows:
        return []
    limit = int(_ANALYZE_ASSETS_DESIGN_BATCH_LIMITS.get(asset_type) or 6)
    limit = max(1, limit)
    return [rows[index : index + limit] for index in range(0, len(rows), limit)]


def _analyze_assets_candidates_for_design_batch(
    candidates: dict[str, Any],
    *,
    asset_type: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    batch_candidates = _analyze_assets_candidates_for_types(candidates, (asset_type,))
    batch_candidates[asset_type] = [copy.deepcopy(row) for row in rows if isinstance(row, dict)]
    coverage = batch_candidates.get("coverageAudit") if isinstance(batch_candidates.get("coverageAudit"), dict) else {}
    if coverage:
        batch_candidates["coverageAudit"] = {
            "checked": coverage.get("checked") is True,
            "mergeDecisions": [],
            "skippedMentions": [],
            "unresolved": [],
        }
    batch_candidates["notes"] = []
    return batch_candidates


def _analyze_assets_candidate_id(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("candidateId") or row.get("candidate_id") or "").strip()


def _analyze_assets_candidate_id_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"[^a-zA-Z0-9_.:-]+", "-", text).strip("-").casefold()


def _analyze_assets_allowed_candidate_ids_by_type(
    candidates: dict[str, Any],
    asset_types: tuple[str, ...] | list[str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if not isinstance(candidates, dict):
        return result
    for asset_type in asset_types:
        if asset_type not in _ASSET_TYPES:
            continue
        ids: list[str] = []
        seen: set[str] = set()
        rows = candidates.get(asset_type)
        if not isinstance(rows, list):
            result[asset_type] = ids
            continue
        for row in rows:
            candidate_id = _analyze_assets_candidate_id(row)
            candidate_key = _analyze_assets_candidate_id_key(candidate_id)
            if not candidate_id or not candidate_key or candidate_key in seen:
                continue
            seen.add(candidate_key)
            ids.append(candidate_id)
        result[asset_type] = ids
    return result


def _analyze_assets_generated_candidate_id(asset_type: str, index: int) -> str:
    return _short_asset_candidate_id(asset_type, index)


def _analyze_assets_next_candidate_id(asset_type: str, used_keys: set[str], start_index: int) -> str:
    index = max(1, int(start_index))
    while True:
        candidate_id = _analyze_assets_generated_candidate_id(asset_type, index)
        candidate_key = _analyze_assets_candidate_id_key(candidate_id)
        if candidate_key and candidate_key not in used_keys:
            return candidate_id
        index += 1


def _analyze_assets_audit_row_is_placeholder(row: Any) -> bool:
    if not isinstance(row, dict):
        return True
    values: list[str] = []
    for key in (
        "candidateId",
        "candidate_id",
        "sourceCandidateId",
        "source_candidate_id",
        "fromCandidateId",
        "from_candidate_id",
        "mention",
        "name",
        "assetName",
        "asset_name",
        "target",
        "targetName",
        "target_name",
        "type",
        "assetType",
        "asset_type",
        "decision",
        "reason",
        "rationale",
    ):
        value = row.get(key)
        if value not in (None, "", [], {}):
            values.append(str(value).strip())
    joined = " | ".join(value for value in values if value)
    if not joined:
        return True
    lowered = joined.casefold()
    if any(marker.casefold() in lowered for marker in _ANALYZE_ASSETS_AUDIT_PLACEHOLDER_MARKERS):
        return True
    for key in (
        "candidateId",
        "candidate_id",
        "sourceCandidateId",
        "source_candidate_id",
        "fromCandidateId",
        "from_candidate_id",
    ):
        candidate_key = _analyze_assets_candidate_id_key(row.get(key))
        if candidate_key in {"id", "candidate-id", "candidateid", "source-candidate-id", "from-candidate-id"}:
            return True
    return False


def _clean_analyze_assets_audit_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if _analyze_assets_audit_row_is_placeholder(row):
            continue
        signature = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if signature in seen:
            continue
        seen.add(signature)
        result.append(copy.deepcopy(row))
    return result


def _clean_analyze_assets_coverage_audit(value: Any) -> dict[str, Any]:
    coverage = value if isinstance(value, dict) else {}
    return {
        "checked": coverage.get("checked") is True,
        "assetBoundaryAudit": _clean_analyze_assets_audit_rows(coverage.get("assetBoundaryAudit")),
        "mergeDecisions": _clean_analyze_assets_audit_rows(coverage.get("mergeDecisions")),
        "skippedMentions": _clean_analyze_assets_audit_rows(coverage.get("skippedMentions")),
        "unresolved": _clean_analyze_assets_audit_rows(coverage.get("unresolved")),
    }


def _analyze_assets_output_candidate_id_keys(output: dict[str, Any] | None) -> set[str]:
    result: set[str] = set()
    if not isinstance(output, dict):
        return result
    for asset_type in _ASSET_TYPES:
        rows = output.get(asset_type)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if _analyze_assets_candidate_decision(row) in {"skip", "merge", "unresolved"}:
                continue
            if not str(row.get("name") or row.get("assetName") or row.get("assetId") or row.get("asset_id") or "").strip():
                continue
            candidate_id_key = _analyze_assets_candidate_id_key(row.get("candidateId") or row.get("candidate_id"))
            if candidate_id_key:
                result.add(candidate_id_key)
    return result


def _analyze_assets_audit_candidate_id_keys(row: dict[str, Any], *, merge_only_source: bool = False) -> set[str]:
    keys = (
        ("sourceCandidateId", "source_candidate_id", "fromCandidateId", "from_candidate_id", "candidateId", "candidate_id")
        if merge_only_source
        else ("candidateId", "candidate_id", "sourceCandidateId", "source_candidate_id", "fromCandidateId", "from_candidate_id")
    )
    result: set[str] = set()
    for key in keys:
        candidate_id_key = _analyze_assets_candidate_id_key(row.get(key))
        if candidate_id_key:
            result.add(candidate_id_key)
    return result


def _prune_analyze_assets_conflicting_audit_rows(output: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {}
    pruned = output
    coverage = _clean_analyze_assets_coverage_audit(pruned.get("coverageAudit"))
    designed_ids = _analyze_assets_output_candidate_id_keys(pruned)
    if designed_ids:
        coverage["skippedMentions"] = [
            row
            for row in coverage.get("skippedMentions") or []
            if not (_analyze_assets_audit_candidate_id_keys(row) & designed_ids)
        ]
        coverage["mergeDecisions"] = [
            row
            for row in coverage.get("mergeDecisions") or []
            if not (_analyze_assets_audit_candidate_id_keys(row, merge_only_source=True) & designed_ids)
        ]
    skipped_ids: set[str] = set()
    for row in coverage.get("skippedMentions") or []:
        skipped_ids.update(_analyze_assets_audit_candidate_id_keys(row))
    if skipped_ids:
        coverage["assetBoundaryAudit"] = [
            row
            for row in coverage.get("assetBoundaryAudit") or []
            if not (_analyze_assets_audit_candidate_id_keys(row) & skipped_ids)
        ]
        coverage["mergeDecisions"] = [
            row
            for row in coverage.get("mergeDecisions") or []
            if not (_analyze_assets_audit_candidate_id_keys(row, merge_only_source=True) & skipped_ids)
        ]
    pruned["coverageAudit"] = coverage
    return pruned


def _analyze_assets_valid_candidate_id_keys_for_types(
    candidates: dict[str, Any] | None,
    asset_types: tuple[str, ...] | list[str],
) -> set[str]:
    selected = {asset_type for asset_type in asset_types if asset_type in _ASSET_TYPES}
    result: set[str] = set()
    if not isinstance(candidates, dict):
        return result
    for asset_type in selected:
        rows = candidates.get(asset_type)
        if not isinstance(rows, list):
            continue
        for row in rows:
            candidate_id_key = _analyze_assets_candidate_id_key(
                _analyze_assets_candidate_id(row) if isinstance(row, dict) else ""
            )
            if candidate_id_key:
                result.add(candidate_id_key)
    return result


def _analyze_assets_design_candidate_id_contract_issues(
    output: dict[str, Any] | None,
    candidates: dict[str, Any] | None,
    *,
    asset_type: str,
) -> list[str]:
    if asset_type not in _ASSET_TYPES:
        return []
    rows = output.get(asset_type) if isinstance(output, dict) else []
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        return [f"{_asset_type_label(asset_type)}设计输出必须是数组"]
    candidate_rows = candidates.get(asset_type) if isinstance(candidates, dict) else []
    if not isinstance(candidate_rows, list):
        candidate_rows = []
    required_by_id: dict[str, dict[str, Any]] = {}
    for row in candidate_rows:
        if not isinstance(row, dict) or not _analyze_assets_candidate_needs_design(row):
            continue
        candidate_id = _analyze_assets_candidate_id(row)
        candidate_id_key = _analyze_assets_candidate_id_key(candidate_id)
        if candidate_id_key:
            required_by_id[candidate_id_key] = row
    if not required_by_id and not rows:
        return []
    coverage_audit = _clean_analyze_assets_coverage_audit(
        output.get("coverageAudit") if isinstance(output, dict) else {}
    )
    addressed_by_audit: set[str] = set()
    issues: list[str] = []
    for audit_key in ("mergeDecisions", "skippedMentions"):
        if any(_analyze_assets_audit_candidate_id_keys(row).intersection(required_by_id)
               for row in coverage_audit.get(audit_key) or [] if isinstance(row, dict)):
            issues.append("设计阶段不得跳过或合并已确认保留的候选；请完成设计，有明确新矛盾则报告 unresolved")
    for audit_key in ("unresolved",):
        for audit_row in coverage_audit.get(audit_key) or []:
            if isinstance(audit_row, dict):
                addressed_by_audit.update(_analyze_assets_audit_candidate_id_keys(audit_row))
    seen_by_id: dict[str, str] = {}
    output_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            issues.append(f"{_asset_type_label(asset_type)}设计输出第 {index} 条必须是对象")
            continue
        candidate_id = str(row.get("candidateId") or row.get("candidate_id") or "").strip()
        candidate_id_key = _analyze_assets_candidate_id_key(candidate_id)
        name = str(row.get("name") or row.get("title") or "").strip()
        if not candidate_id_key:
            issues.append(f"{_asset_type_label(asset_type)}设计输出第 {index} 条缺少 candidateId")
            continue
        if candidate_id_key not in required_by_id:
            issues.append(
                f"{_asset_type_label(asset_type)}设计输出第 {index} 条 candidateId 不属于本批候选：{candidate_id}"
            )
            continue
        output_ids.add(candidate_id_key)
        previous_name = seen_by_id.get(candidate_id_key)
        if previous_name is not None and name and previous_name and previous_name.casefold() != name.casefold():
            issues.append(
                f"{_asset_type_label(asset_type)}设计输出重复使用 candidateId {candidate_id}："
                f"「{previous_name}」与「{name}」不能共用同一候选编号"
            )
        elif previous_name is None:
            seen_by_id[candidate_id_key] = name
    for candidate_id_key, row in required_by_id.items():
        if candidate_id_key not in output_ids and candidate_id_key not in addressed_by_audit:
            issues.append(
                f"{_asset_type_label(asset_type)}设计输出缺少候选 {_analyze_assets_candidate_id(row)}："
                f"{_candidate_asset_name(row)}"
            )
    return issues


def _analyze_assets_audit_row_type(row: dict[str, Any]) -> str:
    raw_type = str(row.get("type") or row.get("assetType") or row.get("asset_type") or "").strip()
    aliases = {
        "character": "characters",
        "characters": "characters",
        "角色": "characters",
        "creature": "creatures",
        "creatures": "creatures",
        "生物": "creatures",
        "scene": "scenes",
        "scenes": "scenes",
        "场景": "scenes",
        "prop": "props",
        "props": "props",
        "道具": "props",
    }
    return aliases.get(raw_type, "")


def _filter_analyze_assets_output_audit_for_types(
    output: dict[str, Any] | None,
    *,
    asset_types: tuple[str, ...] | list[str],
    candidates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {}
    selected = {asset_type for asset_type in asset_types if asset_type in _ASSET_TYPES}
    if not selected:
        return output
    filtered = output
    valid_ids = _analyze_assets_valid_candidate_id_keys_for_types(candidates, tuple(selected))
    coverage = _clean_analyze_assets_coverage_audit(filtered.get("coverageAudit"))
    for key in ("assetBoundaryAudit", "mergeDecisions", "skippedMentions", "unresolved"):
        kept: list[dict[str, Any]] = []
        for row in coverage.get(key) or []:
            row_type = _analyze_assets_audit_row_type(row)
            if row_type and row_type not in selected:
                continue
            row_ids = _analyze_assets_audit_candidate_id_keys(row)
            if valid_ids:
                if not row_ids:
                    continue
                if not (row_ids & valid_ids):
                    continue
            kept.append(row)
        coverage[key] = kept
    filtered["coverageAudit"] = coverage
    return _prune_analyze_assets_conflicting_audit_rows(filtered)


def _candidate_asset_name(row: Any) -> str:
    if isinstance(row, str):
        return row.strip()
    if not isinstance(row, dict):
        return ""
    for key in ("name", "canonicalName", "canonical_name", "assetName", "asset_name", "title", "mention"):
        text = str(row.get(key) or "").strip()
        if text:
            return text
    return ""


def _candidate_original_name(row: Any, fallback: str = "") -> str:
    if isinstance(row, str):
        return row.strip()
    if not isinstance(row, dict):
        return str(fallback or "").strip()
    for key in ("originalName", "original_name", "mention", "rawName", "raw_name", "candidateName", "candidate_name"):
        text = str(row.get(key) or "").strip()
        if text:
            return text
    return str(fallback or "").strip()


def _normalize_analyze_assets_candidates(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    result: dict[str, Any] = {asset_type: [] for asset_type in _ASSET_TYPES}
    for asset_type in _ASSET_TYPES:
        rows = raw.get(asset_type)
        if not isinstance(rows, list):
            continue
        seen: set[str] = set()
        seen_candidate_ids: set[str] = set()
        for row in rows:
            name = _candidate_asset_name(row)
            key = name.casefold()
            if not name or (key in seen and not (isinstance(row, dict) and _analyze_assets_candidate_id(row))):
                continue
            seen.add(key)
            item = copy.deepcopy(row) if isinstance(row, dict) else {"name": name}
            candidate_id = _analyze_assets_candidate_id(item)
            candidate_id_key = _analyze_assets_candidate_id_key(candidate_id)
            if (
                not candidate_id
                or not _is_short_asset_candidate_id(asset_type, candidate_id)
                or candidate_id_key in seen_candidate_ids
            ):
                candidate_id = _analyze_assets_next_candidate_id(asset_type, seen_candidate_ids, len(result[asset_type]) + 1)
                candidate_id_key = _analyze_assets_candidate_id_key(candidate_id)
            seen_candidate_ids.add(candidate_id_key)
            original_name = _candidate_original_name(item, name)
            item["candidateId"] = candidate_id
            if original_name and original_name != name:
                item["originalName"] = original_name
            item["name"] = name
            raw_asset_id = str(item.get("assetId") or item.get("asset_id") or "").strip()
            item.pop("asset_id", None)
            item.pop("id", None)
            if raw_asset_id:
                item["assetId"] = raw_asset_id
            else:
                item.pop("assetId", None)
            if not _analyze_assets_candidate_decision(item):
                item["decision"] = "reuse_existing" if raw_asset_id else "keep_new"
            decision_key = str(_analyze_assets_candidate_decision(item) or "").strip().casefold().replace("-", "_")
            if raw_asset_id or _analyze_assets_candidate_is_reuse_existing(item):
                item["needsDesign"] = False
            elif decision_key in {"skip", "skipped", "remove", "drop", "合并", "跳过", "删除"}:
                item["needsDesign"] = False
            elif "needsDesign" not in item and "needs_design" in item:
                item["needsDesign"] = bool(item.get("needs_design"))
            elif item.get("needsDesign") is not False:
                item["needsDesign"] = True
            item.pop("needs_design", None)
            result[asset_type].append(item)
    review = raw.get("candidateReview") if isinstance(raw.get("candidateReview"), dict) else {}
    if review:
        result["candidateReview"] = copy.deepcopy(review)
    result["coverageAudit"] = _clean_analyze_assets_coverage_audit(raw.get("coverageAudit"))
    notes = raw.get("notes")
    result["notes"] = copy.deepcopy(notes if isinstance(notes, list) else [])
    return _filter_analyze_assets_output_audit_for_types(
        result,
        asset_types=_ASSET_TYPES,
        candidates=result,
    )


def _apply_candidate_inventory_review(candidates: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    """Apply a complete disposition ledger without deleting the original candidates."""
    if not isinstance(review, dict) or review.get("coverageChecked") is not True:
        raise ValueError("候选审查未确认全文覆盖")
    decisions, additions = review.get("decisions"), review.get("additions")
    if not isinstance(decisions, list) or not isinstance(additions, list):
        raise ValueError("候选审查必须提供 decisions 和 additions 数组")
    result = _normalize_analyze_assets_candidates(candidates)
    by_id = {row["candidateId"]: (asset_type, row)
             for asset_type in _ASSET_TYPES for row in result[asset_type]}
    original_ids = set(by_id)
    indexed = {}
    for item in decisions:
        if not isinstance(item, dict):
            raise ValueError("候选处置记录必须是对象")
        candidate_id = item.get("candidateId")
        if not isinstance(candidate_id, str) or candidate_id not in original_ids or candidate_id in indexed:
            raise ValueError("候选处置编号未知或重复")
        if item.get("action") not in {"keep", "merge", "reclassify"}:
            raise ValueError(f"候选 {candidate_id} 处置无效；跳过须由资料辅助的身份阶段决定")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ValueError(f"候选 {candidate_id} 缺少处置理由")
        indexed[candidate_id] = item
    if set(indexed) != original_ids:
        raise ValueError("候选审查遗漏处置：" + ", ".join(sorted(original_ids - set(indexed))))

    def add_candidate(asset_type: str, name: str, reason: str, evidence: str = "") -> dict[str, Any]:
        used = {_analyze_assets_candidate_id_key(row["candidateId"]) for row in result[asset_type]}
        candidate_id = _analyze_assets_next_candidate_id(asset_type, used, len(result[asset_type]) + 1)
        row = {"candidateId": candidate_id, "name": name, "decision": "keep_new", "needsDesign": True,
               "candidateReviewReason": reason}
        if evidence:
            row["sourceEvidence"] = evidence
        result[asset_type].append(row)
        by_id[candidate_id] = (asset_type, row)
        return row

    for item in additions:
        if (not isinstance(item, dict) or item.get("assetType") not in _ASSET_TYPES
                or any(not isinstance(item.get(key), str) or not item[key].strip()
                       for key in ("name", "reason", "sourceEvidence"))):
            raise ValueError("补充候选必须提供类型、名称、理由和正文依据")
        if any(row["name"] == item["name"] for row in result[item["assetType"]]):
            raise ValueError("补充候选与已有候选重名，应使用其候选编号")
        add_candidate(item["assetType"], item["name"], item["reason"], item["sourceEvidence"])
    coverage = result["coverageAudit"]
    for candidate_id, item in indexed.items():
        asset_type, row = by_id[candidate_id]
        action, reason = item["action"], item["reason"]
        row["candidateReviewReason"] = reason
        if action == "keep":
            continue
        if action == "merge":
            target_id = item.get("targetCandidateId")
            if (not isinstance(target_id, str) or target_id not in indexed
                    or indexed[target_id]["action"] != "keep" or target_id == candidate_id):
                raise ValueError(f"候选 {candidate_id} 合并目标必须是保留的原候选")
            target_type, target = by_id[target_id]
        else:
            target_type = item.get("targetType")
            if target_type not in _ASSET_TYPES or target_type == asset_type:
                raise ValueError(f"候选 {candidate_id} 改类目标无效")
            target = add_candidate(target_type, row["name"], reason, str(row.get("sourceEvidence") or ""))
        row.update(decision="merge", needsDesign=False, reason=reason, targetType=target_type,
                   targetName=target["name"], targetCandidateId=target["candidateId"])
        coverage["mergeDecisions"].append({"candidateId": candidate_id, "type": asset_type,
                                           "mention": row["name"], "targetType": target_type,
                                           "targetName": target["name"], "targetCandidateId": target["candidateId"],
                                           "reason": reason})
    coverage["checked"] = True
    result["candidateReview"] = {"pass": True, "coverageChecked": True,
                                 "decisions": copy.deepcopy(decisions), "additions": copy.deepcopy(additions)}
    return _normalize_analyze_assets_candidates(result)


def _merge_candidate_review_output(candidates: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(review, dict):
        return candidates
    original = _normalize_analyze_assets_candidates(candidates)
    if "reviewedCandidates" in review or "reviewed_candidates" in review:
        raise ValueError("不支持无处置记录的整表候选替换")
    merged = copy.deepcopy(original)
    patch = review.get("patch") if isinstance(review.get("patch"), dict) else {}
    additions = patch.get("add") or patch.get("additions") or review.get("additions")
    if isinstance(additions, dict):
        for asset_type in _ASSET_TYPES:
            rows = additions.get(asset_type)
            if not isinstance(rows, list):
                continue
            existing_names = {
                str(row.get("name") or "").strip().casefold()
                for row in merged.get(asset_type) or []
                if isinstance(row, dict)
            }
            for row in rows:
                name = _candidate_asset_name(row)
                key = name.casefold()
                if not name or key in existing_names:
                    continue
                existing_names.add(key)
                merged.setdefault(asset_type, []).append({"name": name, "decision": "keep_new", "needsDesign": True})
    removals = patch.get("remove") or patch.get("removals") or review.get("removals")
    if isinstance(removals, dict):
        for asset_type in _ASSET_TYPES:
            names = {
                _candidate_asset_name(row).casefold()
                for row in removals.get(asset_type) or []
                if _candidate_asset_name(row)
            }
            if names:
                merged[asset_type] = [
                    row
                    for row in merged.get(asset_type) or []
                    if isinstance(row, dict) and str(row.get("name") or "").strip().casefold() not in names
                ]
    original_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    original_by_name: dict[str, tuple[str, dict[str, Any]]] = {}
    for asset_type in _ASSET_TYPES:
        for row in original.get(asset_type) or []:
            if not isinstance(row, dict):
                continue
            candidate_id_key = _analyze_assets_candidate_id_key(row.get("candidateId") or row.get("candidate_id"))
            if candidate_id_key:
                original_by_id.setdefault(candidate_id_key, (asset_type, row))
            name_key = _analyze_assets_candidate_name_key(row.get("name") or row.get("assetName") or row.get("title"))
            if name_key:
                original_by_name.setdefault(name_key, (asset_type, row))

    def next_candidate_id(asset_type: str) -> str:
        existing_ids = {
            _analyze_assets_candidate_id_key(row.get("candidateId") or row.get("candidate_id"))
            for row in merged.get(asset_type) or []
            if isinstance(row, dict)
        }
        index = len(merged.get(asset_type) or []) + 1
        while True:
            candidate_id = _analyze_assets_generated_candidate_id(asset_type, index)
            if _analyze_assets_candidate_id_key(candidate_id) not in existing_ids:
                return candidate_id
            index += 1

    def mark_source_redirected(
        *,
        source_type: str,
        source_candidate_id: str,
        source_name: str,
        target_type: str,
        target_name: str,
        reason: str,
    ) -> None:
        if source_type not in _ASSET_TYPES or source_type == target_type:
            return
        source_id_key = _analyze_assets_candidate_id_key(source_candidate_id)
        source_name_key = _analyze_assets_candidate_name_key(source_name)
        matched = False
        for index, row in enumerate(merged.get(source_type) or []):
            if not isinstance(row, dict):
                continue
            row_id_key = _analyze_assets_candidate_id_key(row.get("candidateId") or row.get("candidate_id"))
            row_name_key = _analyze_assets_candidate_name_key(row.get("name") or row.get("assetName") or row.get("title"))
            if (source_id_key and row_id_key == source_id_key) or (source_name_key and row_name_key == source_name_key):
                matched = True
                item = copy.deepcopy(row)
                item["decision"] = "merge"
                item["needsDesign"] = False
                item["boundaryDecisionSource"] = "candidateReviewRedirect"
                item["targetType"] = target_type
                item["targetName"] = target_name
                if reason:
                    item["reason"] = reason
                merged[source_type][index] = item
        if matched:
            return
        original_match = original_by_id.get(source_id_key) if source_id_key else None
        if not original_match and source_name_key:
            original_match = original_by_name.get(source_name_key)
        if not original_match:
            return
        item = copy.deepcopy(original_match[1])
        if source_candidate_id:
            item["candidateId"] = source_candidate_id
        if source_name:
            item["name"] = source_name
        item["decision"] = "merge"
        item["needsDesign"] = False
        item["boundaryDecisionSource"] = "candidateReviewRedirect"
        item["targetType"] = target_type
        item["targetName"] = target_name
        if reason:
            item["reason"] = reason
        merged.setdefault(source_type, []).append(item)

    def apply_review_redirects(rows: Any) -> None:
        if not isinstance(rows, list):
            return
        for raw_row in rows:
            if not isinstance(raw_row, dict):
                continue
            target_type = _analyze_assets_asset_type_key(
                raw_row.get("redirectType")
                or raw_row.get("redirect_type")
                or raw_row.get("targetType")
                or raw_row.get("target_type")
                or raw_row.get("toType")
                or raw_row.get("to_type")
                or raw_row.get("targetAssetType")
                or raw_row.get("target_asset_type")
            )
            if target_type not in _ASSET_TYPES:
                continue
            source_candidate_id = str(
                raw_row.get("candidateId")
                or raw_row.get("candidate_id")
                or raw_row.get("sourceCandidateId")
                or raw_row.get("source_candidate_id")
                or raw_row.get("fromCandidateId")
                or raw_row.get("from_candidate_id")
                or ""
            ).strip()
            source_name = str(
                raw_row.get("mention")
                or raw_row.get("name")
                or raw_row.get("assetName")
                or raw_row.get("asset_name")
                or raw_row.get("candidate")
                or raw_row.get("title")
                or raw_row.get("sourceName")
                or raw_row.get("source_name")
                or ""
            ).strip()
            source_type = _analyze_assets_asset_type_key(
                raw_row.get("sourceType")
                or raw_row.get("source_type")
                or raw_row.get("fromType")
                or raw_row.get("from_type")
                or raw_row.get("type")
                or raw_row.get("assetType")
                or raw_row.get("asset_type")
            )
            original_row: dict[str, Any] = {}
            if source_candidate_id:
                original_match = original_by_id.get(_analyze_assets_candidate_id_key(source_candidate_id))
                if original_match:
                    source_type = source_type or original_match[0]
                    original_row = original_match[1]
            if not original_row and source_name:
                original_match = original_by_name.get(_analyze_assets_candidate_name_key(source_name))
                if original_match:
                    source_type = source_type or original_match[0]
                    original_row = original_match[1]
            if source_type == target_type:
                continue
            target_name = str(
                raw_row.get("redirectName")
                or raw_row.get("redirect_name")
                or raw_row.get("targetName")
                or raw_row.get("target_name")
                or raw_row.get("normalizedName")
                or raw_row.get("normalized_name")
                or raw_row.get("canonicalName")
                or raw_row.get("canonical_name")
                or ""
            ).strip()
            if not target_name:
                target_name = source_name or _candidate_asset_name(original_row)
            if not target_name:
                continue
            existing_names = {
                str(row.get("name") or "").strip().casefold()
                for row in merged.get(target_type) or []
                if isinstance(row, dict)
            }
            if target_name.casefold() not in existing_names:
                item = {
                    "candidateId": next_candidate_id(target_type),
                    "name": target_name,
                    "decision": "keep_new",
                    "needsDesign": True,
                    "redirectedFromType": source_type,
                    "redirectedFromCandidateId": source_candidate_id,
                }
                original_name = _candidate_original_name(original_row, target_name)
                if original_name and original_name != target_name:
                    item["originalName"] = original_name
                reason = str(raw_row.get("reason") or raw_row.get("rationale") or "").strip()
                if reason:
                    item["redirectReason"] = reason
                merged.setdefault(target_type, []).append(item)
            mark_source_redirected(
                source_type=source_type,
                source_candidate_id=source_candidate_id,
                source_name=source_name or _candidate_asset_name(original_row),
                target_type=target_type,
                target_name=target_name,
                reason=str(raw_row.get("reason") or raw_row.get("rationale") or "").strip(),
            )

    input_names = _analyze_assets_candidate_review_name_lists(original)
    reviewed_names = _analyze_assets_candidate_review_name_lists(merged)
    merged["candidateReview"] = {
        "pass": bool(review.get("pass", True)),
        "blockingIssues": copy.deepcopy(review.get("blockingIssues") if isinstance(review.get("blockingIssues"), list) else []),
        "warnings": copy.deepcopy(review.get("warnings") if isinstance(review.get("warnings"), list) else []),
        "inputCounts": {asset_type: len(input_names.get(asset_type) or []) for asset_type in _ASSET_TYPES},
        "reviewedCounts": {asset_type: len(reviewed_names.get(asset_type) or []) for asset_type in _ASSET_TYPES},
        "reviewedNames": reviewed_names,
    }
    coverage = merged.get("coverageAudit") if isinstance(merged.get("coverageAudit"), dict) else {}
    skipped = coverage.setdefault("skippedMentions", [])
    review_skipped = review.get("skippedMentions") or review.get("skipped_mentions")
    if isinstance(skipped, list) and isinstance(review_skipped, list):
        cleaned_review_skipped = _clean_analyze_assets_audit_rows(review_skipped)
        skipped.extend(cleaned_review_skipped)
        apply_review_redirects(cleaned_review_skipped)
    coverage["checked"] = True
    merged["coverageAudit"] = _clean_analyze_assets_coverage_audit(coverage)
    return _normalize_analyze_assets_candidates(merged)


def _analyze_assets_cross_type_candidate_conflicts(candidates: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(candidates, dict):
        return []
    by_name: dict[str, list[dict[str, Any]]] = {}
    for asset_type in _ASSET_TYPES:
        rows = candidates.get(asset_type)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not _analyze_assets_candidate_is_kept(row):
                continue
            name = _candidate_asset_name(row)
            name_key = _analyze_assets_candidate_name_key(name)
            if not name_key:
                continue
            by_name.setdefault(name_key, []).append(
                {
                    "assetType": asset_type,
                    "candidateId": _analyze_assets_candidate_id(row),
                    "name": name,
                    "decision": _analyze_assets_candidate_decision(row) or "keep_new",
                    "needsDesign": row.get("needsDesign") is not False,
                }
            )
    conflicts: list[dict[str, Any]] = []
    for rows in by_name.values():
        asset_types = sorted({str(row.get("assetType") or "") for row in rows if row.get("assetType")})
        if len(asset_types) <= 1:
            continue
        conflicts.append(
            {
                "name": str(rows[0].get("name") or "").strip(),
                "assetTypes": asset_types,
                "candidates": rows,
            }
        )
    return conflicts


def _analyze_assets_candidate_name_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"[\s\"'“”‘’《》<>（）()【】\[\]{}:：,，;；、]+", "", text)
    replacements = (
        ("的", ""),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text.casefold()


def _analyze_assets_candidate_source_digest(
    candidates: dict[str, Any] | None,
    *,
    asset_types: tuple[str, ...] | list[str],
    limit: int = 2600,
) -> str:
    if not isinstance(candidates, dict):
        return ""
    parts: list[str] = []
    seen: set[str] = set()
    for asset_type in asset_types:
        rows = candidates.get(asset_type)
        if not isinstance(rows, list):
            continue
        label = _asset_type_label(str(asset_type))
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            evidences = row.get("sourceEvidence") if isinstance(row.get("sourceEvidence"), list) else []
            for evidence in evidences:
                text = re.sub(r"\s+", " ", str(evidence or "")).strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                prefix = f"{label}:{name} | " if name else f"{label} | "
                parts.append(prefix + text)
                if sum(len(part) + 1 for part in parts) >= limit:
                    break
            if sum(len(part) + 1 for part in parts) >= limit:
                break
        if sum(len(part) + 1 for part in parts) >= limit:
            break
    digest = "\n".join(parts).strip()
    if len(digest) > limit:
        return digest[:limit].rstrip() + "...（候选证据已截断）"
    return digest


def _compact_asset_audit_rows(rows: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return result
    for row in _clean_analyze_assets_audit_rows(rows)[:25]:
        if not isinstance(row, dict):
            continue
        item: dict[str, Any] = {}
        for key in (
            "candidateId",
            "mention",
            "type",
            "decision",
            "assetName",
            "parentAssetName",
            "independence",
            "specificity",
            "evidenceLevel",
            "reason",
        ):
            value = row.get(key)
            if value not in (None, "", [], {}):
                item[key] = _review_text(value)
        if item:
            result.append(item)
    return result


def _normalize_asset_evidence(value: Any) -> list[str]:
    rows = value if isinstance(value, list) else [value] if value not in (None, "") else []
    result: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            text = str(row.get("text") or row.get("excerpt") or row.get("sourcePreview") or "").strip()
        else:
            text = str(row or "").strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= 8:
            break
    return result
