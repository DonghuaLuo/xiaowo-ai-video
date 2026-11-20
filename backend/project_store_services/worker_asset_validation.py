# -*- coding: utf-8 -*-
"""资产输出字段、证据和设计契约验证。"""
from __future__ import annotations

import copy
import re
from .assets import (
    _asset_type_label,
)
from .source_coverage import _source_ref_bounds
from .source_text_store import _compact_text
from .worker_asset_candidates import (
    _clean_analyze_assets_coverage_audit,
    _normalize_asset_evidence,
    _prune_analyze_assets_conflicting_audit_rows,
)
from .worker_asset_contract import (
    _ANALYZE_ASSETS_NATURAL_LANGUAGE_FIELDS,
    _ASSET_TYPES,
    _DISALLOWED_ASSET_ITEM_KEYS,
    _DISALLOWED_WORKER_OUTPUT_KEYS,
    _SCENE_REFERENCE_ROLE_WORK_CHAIN,
    _apply_scene_reference_role,
    _scene_reference_role,
)
from .worker_asset_identity import (
    _asset_existing_rows_for_validation,
)
from .worker_asset_ownership import asset_ownership_issues
from .worker_contract import (
    _natural_language_forbidden_latin_terms,
)
from typing import (
    Any,
)


def _asset_source_document(output: dict[str, Any]) -> dict[str, Any]:
    for key in ("assetBatch", "asset_batch", "assets", "output", "result"):
        value = output.get(key)
        if isinstance(value, dict) and any(asset_type in value for asset_type in _ASSET_TYPES):
            return value
    return output


def _find_asset_evidence_range(source_text: str, excerpt: str) -> tuple[int, int, str] | None:
    text = str(excerpt or "").strip()
    if not source_text or not text:
        return None
    local_start = source_text.find(text)
    if local_start >= 0:
        return local_start, local_start + len(text), text

    compact_text = re.sub(r"\s+", "", text)
    if compact_text:
        compact_source_parts: list[str] = []
        compact_source_positions: list[int] = []
        for index, char in enumerate(source_text):
            if char.isspace():
                continue
            compact_source_parts.append(char)
            compact_source_positions.append(index)
        compact_source = "".join(compact_source_parts)
        compact_start = compact_source.find(compact_text)
        if compact_start >= 0:
            compact_end = compact_start + len(compact_text)
            local_start = compact_source_positions[compact_start]
            local_end = compact_source_positions[compact_end - 1] + 1
            return local_start, local_end, source_text[local_start:local_end]

    parts = [part for part in re.split(r"\s+", text) if part]
    if len(parts) <= 1:
        return None
    pattern = r"\s+".join(re.escape(part) for part in parts)
    match = re.search(pattern, source_text)
    if not match:
        return None
    return match.start(), match.end(), source_text[match.start() : match.end()]


def _strip_analyze_assets_controller_source_refs(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_analyze_assets_controller_source_refs(item) for item in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    result: dict[str, Any] = {}
    for key, child in value.items():
        if key == "sourceRefs":
            continue
        result[key] = _strip_analyze_assets_controller_source_refs(child)
    return result


def _normalize_worker_asset(asset_type: str, row: dict[str, Any]) -> dict[str, Any]:
    name = str(row.get("name") or row.get("title") or "").strip()
    desc = str(row.get("desc") or row.get("description") or "").strip()
    item: dict[str, Any] = {
        "name": name,
        "desc": desc,
        "assetImagePrompt": str(row.get("assetImagePrompt") or "").strip(),
        "sourceEvidence": _normalize_asset_evidence(row.get("sourceEvidence") or row.get("source_evidence")),
        "designRationale": str(row.get("designRationale") or row.get("design_rationale") or "").strip(),
    }
    candidate_id = str(row.get("candidateId") or row.get("candidate_id") or "").strip()
    if candidate_id:
        item["candidateId"] = candidate_id
    asset_id = str(row.get("assetId") or row.get("asset_id") or "").strip()
    if asset_id:
        item["assetId"] = asset_id
    aliases = row.get("aliases")
    if isinstance(aliases, list):
        item["aliases"] = list(dict.fromkeys(str(value).strip() for value in aliases if str(value or "").strip()))
    source_refs = row.get("sourceRefs")
    if isinstance(source_refs, list):
        item["sourceRefs"] = [copy.deepcopy(ref) for ref in source_refs if isinstance(ref, dict)]
    if asset_type == "characters":
        item["voiceStyle"] = str(row.get("voiceStyle") or row.get("voice_style") or "").strip()
    elif asset_type == "creatures":
        voice_style = str(row.get("voiceStyle") or row.get("voice_style") or "").strip()
        can_speak = bool(voice_style)
        item["canSpeak"] = can_speak
        if can_speak:
            item["voiceStyle"] = voice_style
    elif asset_type == "scenes":
        _apply_scene_reference_role(item, row)
    return {key: value for key, value in item.items() if value not in (None, "", [], {})}


def _asset_existing_design_prompt(row: dict[str, Any]) -> str:
    prompts = row.get("prompts") if isinstance(row.get("prompts"), dict) else {}
    for value in (
        row.get("assetImagePrompt"),
        row.get("asset_image_prompt"),
        prompts.get("assetImagePrompt"),
        prompts.get("asset_image_prompt"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _asset_existing_voice_style(row: dict[str, Any]) -> str:
    return str(row.get("voiceStyle") or row.get("voice_style") or "").strip()


def _asset_existing_prompt_is_reusable(prompt: str) -> bool:
    return bool(str(prompt or "").strip())


def _asset_source_refs_from_evidence(
    item: dict[str, Any],
    *,
    task_context: dict[str, Any],
    label: str,
    blocking: list[str],
    require_evidence: bool,
) -> list[dict[str, Any]]:
    source_text = str(task_context.get("sourceText") or "")
    source_id = str(task_context.get("sourceId") or "").strip()
    absolute_start = int(task_context.get("absoluteStart") or 0)
    absolute_end = int(task_context.get("absoluteEnd") or absolute_start + len(source_text))
    existing_refs = item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else []
    refs: list[dict[str, Any]] = []
    if require_evidence and existing_refs:
        blocking.append(f"{label} 不允许直接提供 sourceRefs；必须提供 sourceEvidence 由 controller 定位")
    else:
        for ref in existing_refs:
            if not isinstance(ref, dict):
                continue
            ref_source_id = str(ref.get("sourceId") or "").strip()
            ref_start, ref_end = _source_ref_bounds(ref)
            if (
                not ref_source_id
                or ref_source_id != source_id
                or ref_start is None
                or ref_end is None
                or ref_start < absolute_start
                or ref_end > absolute_end
                or ref_end <= ref_start
            ):
                blocking.append(f"{label} 的 sourceRefs 不能定位到当前已提交资产范围")
                continue
            refs.append(copy.deepcopy(ref))
    evidence = item.get("sourceEvidence") if isinstance(item.get("sourceEvidence"), list) else []
    for excerpt in evidence:
        text = str(excerpt or "").strip()
        if not text:
            continue
        evidence_range = _find_asset_evidence_range(source_text, text)
        if not evidence_range:
            continue
        local_start, local_end, source_preview = evidence_range
        ref = {
            "sourceId": source_id,
            "absoluteStart": absolute_start + local_start,
            "absoluteEnd": absolute_start + local_end,
            "sourcePreview": source_preview,
        }
        key = (ref["sourceId"], ref["absoluteStart"], ref["absoluteEnd"])
        if not any(
            (
                str(row.get("sourceId") or ""),
                row.get("absoluteStart"),
                row.get("absoluteEnd"),
            )
            == key
            for row in refs
        ):
            refs.append(ref)
    if require_evidence and not refs:
        # A paraphrase is not a source coordinate. Keep the trusted scope instead;
        # semantic review, not substring matching, decides whether it supports an asset.
        if source_id and source_text and absolute_end > absolute_start:
            refs.append({
                "sourceId": source_id,
                "absoluteStart": absolute_start,
                "absoluteEnd": absolute_end,
                "sourcePreview": "",
                "precision": "range",
            })
        else:
            blocking.append(f"{label} 缺少有效的分析原文范围")
    return refs


def validate_analyze_assets_worker_output(
    project_id: str,
    output: dict[str, Any],
    *,
    asset_range_id: str,
    task_context: dict[str, Any] | None = None,
    require_design_contract: bool = False,
    enforce_coverage_table_completeness: bool = True,
    enforce_ownership_targets: bool = True,
) -> dict[str, Any]:
    original_output = copy.deepcopy(output if isinstance(output, dict) else {})
    raw_output = _prune_analyze_assets_conflicting_audit_rows(copy.deepcopy(original_output))
    original_document = _asset_source_document(original_output)
    document = _asset_source_document(raw_output)
    context = task_context if isinstance(task_context, dict) else {}
    blocking: list[str] = asset_ownership_issues(original_document, complete=enforce_ownership_targets)
    notes = document.get("notes") if isinstance(document.get("notes"), list) else []
    for key in _DISALLOWED_WORKER_OUTPUT_KEYS:
        if key in raw_output or key in document:
            blocking.append(f"analyze-assets 不允许输出 {key}")
    skipped_duplicates: dict[str, list[str]] = {asset_type: [] for asset_type in _ASSET_TYPES}
    asset_batch: dict[str, Any] = {
        "assetMode": "upsert",
        "assetRangeId": asset_range_id,
        "reason": "analyze-assets worker reviewed",
    }
    raw_coverage_audit = original_document.get("coverageAudit") if isinstance(original_document, dict) else None
    coverage_audit = _clean_analyze_assets_coverage_audit(raw_coverage_audit)
    if require_design_contract:
        if coverage_audit.get("checked") is not True:
            blocking.append("analyze-assets 缺少已完成的 coverageAudit.checked=true")
        raw_audit = raw_coverage_audit if isinstance(raw_coverage_audit, dict) else {}
        for audit_key in ("assetBoundaryAudit", "mergeDecisions", "skippedMentions", "unresolved"):
            audit_rows = raw_audit.get(audit_key)
            if audit_rows is None:
                continue
            if not isinstance(audit_rows, list):
                blocking.append(f"coverageAudit.{audit_key} 必须是数组")
                continue
            bad_index = next((index for index, item in enumerate(audit_rows) if not isinstance(item, dict)), None)
            if bad_index is not None:
                blocking.append(f"coverageAudit.{audit_key}[{bad_index}] 必须是对象，不能是字符串或其他类型")
        unresolved = raw_audit.get("unresolved") if isinstance(raw_audit.get("unresolved"), list) else []
        if unresolved:
            blocking.append(
                "coverageAudit 仍有未解决项："
                + "；".join(_compact_text(item, 120) for item in unresolved[:6])
            )
    if coverage_audit:
        asset_batch["coverageAudit"] = copy.deepcopy(coverage_audit)
    asset_coverage_table = document.get("assetCoverageTable") or document.get("asset_coverage_table")
    if isinstance(asset_coverage_table, dict):
        asset_batch["assetCoverageTable"] = copy.deepcopy(asset_coverage_table)
    if notes:
        asset_batch["notes"] = [str(item).strip() for item in notes if str(item).strip()]
    for asset_type in _ASSET_TYPES:
        clean_rows: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        seen_asset_ids: set[str] = set()
        existing_rows = _asset_existing_rows_for_validation(project_id, context, asset_type)
        existing_by_id = {
            str(row.get("id") or "").strip(): row
            for row in existing_rows
            if str(row.get("id") or "").strip()
        }
        existing_name_keys: set[str] = set()
        for row in existing_rows:
            lookup_names = [
                str(row.get("name") or row.get("title") or "").strip(),
                *[
                    str(alias or "").strip()
                    for alias in (row.get("aliases") if isinstance(row.get("aliases"), list) else [])
                ],
            ]
            for lookup_name in lookup_names:
                if lookup_name:
                    existing_name_keys.add(lookup_name.casefold())
        rows = document.get(asset_type)
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            blocking.append(f"{asset_type} 必须是数组")
            continue
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                blocking.append(f"{asset_type} 第 {index} 条必须是对象")
                continue
            disallowed = sorted(key for key in _DISALLOWED_ASSET_ITEM_KEYS if key in row)
            if disallowed:
                row = {key: value for key, value in row.items() if key not in _DISALLOWED_ASSET_ITEM_KEYS}
            item = _normalize_worker_asset(asset_type, row)
            name = str(item.get("name") or "").strip()
            if not name:
                blocking.append(f"{asset_type} 第 {index} 条缺少 name")
                continue
            asset_id = str(item.get("assetId") or "").strip()
            existing = existing_by_id.get(asset_id) if asset_id else None
            if asset_id and not existing:
                blocking.append(f"{asset_type} 第 {index} 条 assetId 不属于同类已有资产：{asset_id}")
                continue
            if not asset_id and name.casefold() in existing_name_keys:
                blocking.append(f"{asset_type} 第 {index} 条名称与已有资产重复；复用已有资产必须填写 assetId：{name}")
                continue
            if existing:
                existing_name = str(existing.get("name") or existing.get("title") or "").strip()
                if asset_id and existing_name and existing_name.casefold() != name.casefold():
                    blocking.append(
                        f"{asset_type} 第 {index} 条复用 assetId 时必须使用已有规范名「{existing_name}」，不能写成「{name}」"
                    )
                    continue
                existing_id = str(existing.get("id") or "").strip()
                if existing_id:
                    item["assetId"] = existing_id
                    asset_id = existing_id
                if existing_name and existing_name.casefold() != name.casefold():
                    item["name"] = existing_name
                    name = existing_name
                existing_desc = str(existing.get("desc") or existing.get("description") or "").strip()
                if existing_desc:
                    item["desc"] = existing_desc
                existing_prompt = _asset_existing_design_prompt(existing)
                if _asset_existing_prompt_is_reusable(existing_prompt):
                    item["assetImagePrompt"] = existing_prompt
                if asset_type in {"characters", "creatures"}:
                    existing_voice_style = _asset_existing_voice_style(existing)
                    if existing_voice_style:
                        item["voiceStyle"] = existing_voice_style
                if asset_type == "scenes":
                    _apply_scene_reference_role(item, existing)
                if asset_type == "creatures":
                    item["canSpeak"] = bool(item.get("voiceStyle"))
            desc = str(item.get("desc") or "").strip()
            if not desc and not asset_id:
                blocking.append(f"{asset_type} 第 {index} 条缺少 desc")
                continue
            if asset_type == "creatures":
                item["canSpeak"] = bool(str(item.get("voiceStyle") or "").strip())
            if require_design_contract:
                if not asset_id:
                    for natural_field in _ANALYZE_ASSETS_NATURAL_LANGUAGE_FIELDS:
                        latin_terms = _natural_language_forbidden_latin_terms(item.get(natural_field))
                        if latin_terms:
                            blocking.append(
                                f"{asset_type} 第 {index} 条 {natural_field} 含非项目语言英文词："
                                + "、".join(latin_terms)
                            )
                prompt = str(item.get("assetImagePrompt") or "").strip()
                rationale = str(item.get("designRationale") or "").strip()
                if not prompt and not asset_id:
                    blocking.append(f"{asset_type} 第 {index} 条缺少 assetImagePrompt")
                if not rationale:
                    blocking.append(f"{asset_type} 第 {index} 条缺少 designRationale")
                if asset_type == "scenes" and _scene_reference_role(item) != _SCENE_REFERENCE_ROLE_WORK_CHAIN:
                    blocking.append(
                        f"scenes 第 {index} 条 sceneReferenceRole 必须是 "
                        f"{_SCENE_REFERENCE_ROLE_WORK_CHAIN}；纯背景地点、父级范围或非直接取景语境不得输出到 scenes"
                    )
                source_refs = _asset_source_refs_from_evidence(
                    item,
                    task_context=context,
                    label=f"{asset_type} 第 {index} 条",
                    blocking=blocking,
                    require_evidence=True,
                )
                if source_refs:
                    item["sourceRefs"] = source_refs
            name_key = name.casefold()
            if name_key in seen_names:
                skipped_duplicates[asset_type].append(name)
                continue
            if asset_id and asset_id.casefold() in seen_asset_ids:
                skipped_duplicates[asset_type].append(name)
                continue
            seen_names.add(name_key)
            if asset_id:
                seen_asset_ids.add(asset_id.casefold())
            clean_rows.append(item)
        asset_batch[asset_type] = clean_rows
    if (
        require_design_contract
        and enforce_coverage_table_completeness
        and isinstance(asset_batch.get("assetCoverageTable"), dict)
    ):
        pending_names: list[str] = []
        table_types = asset_batch["assetCoverageTable"].get("assetTypes")
        if isinstance(table_types, dict):
            for asset_type in _ASSET_TYPES:
                rows = table_types.get(asset_type)
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("status") or "").strip() == "new_pending_design":
                        name = str(row.get("name") or "").strip()
                        pending_names.append(f"{_asset_type_label(asset_type)}「{name}」" if name else _asset_type_label(asset_type))
        if pending_names:
            blocking.append(
                "assetCoverageTable 仍有未设计且未跳过的新资产："
                + "、".join(pending_names[:12])
            )
    skipped_duplicates = {
        asset_type: list(dict.fromkeys(skipped_duplicates.get(asset_type, [])))
        for asset_type in _ASSET_TYPES
    }
    return {
        "success": not blocking,
        "blockingIssues": blocking,
        "assetBatch": asset_batch,
        "skippedDuplicates": skipped_duplicates,
        "notes": [str(item).strip() for item in notes if str(item).strip()],
        "newCounts": {
            asset_type: sum(not row.get("assetId") for row in (asset_batch.get(asset_type) or []))
            for asset_type in _ASSET_TYPES
        },
    }
