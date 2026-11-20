# -*- coding: utf-8 -*-
"""Native Agent asset extraction reads and verified commits."""
from __future__ import annotations

import copy
import traceback
from difflib import SequenceMatcher
from typing import Any

from .agent_sessions import _load_agent_sessions
from .asset_analysis_commit import _hash, commit_asset_analysis, source_snapshot
from .asset_range_bindings import _source_window_for_asset_range
from .assets import list_assets, _asset_project_style
from .production_specs import build_project_production_spec
from .runtime_state import _LOCK
from .source_coverage import _load_source_coverage
from .store_core import _emit_agent_event, _read_json
from .worker_asset_validation import (
    _find_asset_evidence_range,
    validate_analyze_assets_worker_output,
)
from .agent_sessions import _project_dir
from .worker_asset_contract import _ASSET_ADJACENT_SOURCE_CHARS
from .agent_asset_extraction_materials import (
    asset_material_manifest, asset_material_catalog, asset_material_evidence,
)
from .worker_task_context import (
    _asset_adjacent_source_context, _project_genre_context, build_worker_task_context,
)


_ASSET_TYPES = ("characters", "creatures", "scenes", "props")
_ELIGIBLE_STATES = {"committed", "failed"}


def _error(path: str, code: str, message: str, repair_action: str = "revise_and_resubmit") -> dict[str, Any]:
    return {"path": path, "code": code, "message": message, "repairAction": repair_action}


def _failure(*errors: dict[str, Any], status: str = "rejected") -> dict[str, Any]:
    return {"success": False, "status": status, "message": errors[0]["message"],
            "errors": list(errors), "projectChanged": False}


def _session_revision(project_id: str, session_id: str) -> int:
    session = next((row for row in _load_agent_sessions(project_id)
                    if str(row.get("id") or "") == session_id), None)
    if not isinstance(session, dict) or str(session.get("scope") or "") != "project":
        raise ValueError("资产拆分只允许在当前项目会话中执行")
    return int(session.get("requirementRevision") or 0)


def _target_range(project_id: str, asset_range_id: str = "") -> dict[str, Any]:
    coverage = _load_source_coverage(project_id)
    ranges = [row for row in (coverage.get("assetRanges") or []) if isinstance(row, dict)]
    if asset_range_id:
        row = next((item for item in ranges if str(item.get("rangeId") or "") == asset_range_id), None)
        if row is None:
            raise ValueError("目标资产范围不存在")
    else:
        candidates = [row for row in ranges
                      if str(row.get("analysisStatus") or "committed") in _ELIGIBLE_STATES]
        if len(candidates) != 1:
            if not candidates and ranges and all(item.get("analysisStatus") == "completed" for item in ranges):
                raise ValueError("当前已规划的资产范围均已完成拆分，无需重复新增；如需调整已有资产，请明确资产和修改要求")
            raise ValueError("当前没有唯一待拆分的资产范围，请指定 assetRangeId 或先确认范围")
        row = candidates[0]
    status = str(row.get("analysisStatus") or "committed")
    if status not in _ELIGIBLE_STATES:
        raise ValueError(f"资产范围当前状态为 {status}，不能重复启动资产拆分")
    return copy.deepcopy(row)


def _task_context(project_id: str, row: dict[str, Any]) -> dict[str, Any]:
    return build_worker_task_context(project_id, "analyze-assets", {"range": row})


def _production_spec(project_id: str) -> dict[str, Any]:
    return build_project_production_spec(_read_json(_project_dir(project_id) / "config.json", {}))


def _input_digest(snapshot: dict[str, Any], row: dict[str, Any],
                  context: dict[str, Any], requirement_revision: int) -> str:
    return _hash({
        "snapshot": snapshot,
        "range": {key: row.get(key) for key in (
            "rangeId", "sourceId", "absoluteStart", "absoluteEnd", "assetTypes",
            "phaseVisualContexts", "analysisStatus",
        )},
        "productionSpec": context.get("productionSpec") or {},
        "designInputs": context.get("designInputs") or {},
        "requirementRevision": requirement_revision,
    })


def _design_inputs(project_id: str, manifest: list[dict[str, Any]]) -> dict[str, Any]:
    config = _read_json(_project_dir(project_id) / "config.json", {})
    return {"materials": manifest, "genreContext": _project_genre_context(project_id),
            "visualDirection": {kind: _asset_project_style(project_id, kind)[1]
                                for kind in _ASSET_TYPES},
            "phaseVisuals": (config.get("style") or {}).get("phase_visuals") or []}


def _asset_identity_index(project_id: str) -> tuple[dict[str, Any], list[str]]:
    """Expose compact identities before the model decides what details to page."""
    document = list_assets("project", project_id, hydrate=False, lifecycle_status="active", persist_normalization=False)
    index: dict[str, list[dict[str, Any]]] = {}
    truncated: list[str] = []
    for kind in _ASSET_TYPES:
        rows = document.get(kind) if isinstance(document, dict) else []
        rows = [row for row in rows if isinstance(row, dict) and row.get("id")]
        if len(rows) > 200:
            truncated.append(kind)
        index[kind] = [
            {"id": str(row.get("id") or ""),
             "name": str(row.get("name") or row.get("title") or ""),
             "aliases": copy.deepcopy(row.get("aliases") or [])}
            for row in rows[:200]
        ]
    return index, truncated


def get_asset_extraction_context(
    project_id: str, *, asset_range_id: str = "", session_id: str,
    part: str, offset: int = 0, queries: list[str] | None = None,
    relative_path: str = "", line_start: int = 1, line_count: int = 80,
) -> dict[str, Any]:
    if part not in {"source_text", "task_state", "identity_index", "design_context", "material_catalog", "material_evidence", "adjacent_evidence"}:
        return _failure(_error("part", "invalid_part", "请选择资产拆分所需的单项资料", "stop"))
    try:
        revision = _session_revision(project_id, session_id)
        row = _target_range(project_id, asset_range_id)
        range_id = str(row.get("rangeId") or "")
        manifest = asset_material_manifest(project_id)
        snapshot = source_snapshot(project_id, range_id)
        context = {"productionSpec": _production_spec(project_id),
                   "designInputs": _design_inputs(project_id, manifest)}
        digest = _input_digest(snapshot, row, context, revision)
        receipt = {"success": True, "assetRangeId": range_id, "inputDigest": digest}
        if part == "source_text":
            _source_id, start, end, text = _source_window_for_asset_range(project_id, range_id)
            if end <= start or not text or len(text) != end - start:
                raise ValueError("当前资产范围原文不完整")
            return {**receipt, "sourceText": text}
        if part == "identity_index":
            index, truncated = _asset_identity_index(project_id)
            return {**receipt, "identityIndex": {"assets": index, "truncatedTypes": truncated}}
        if part == "adjacent_evidence":
            return {**receipt, "adjacentEvidence": _asset_adjacent_source_context(
                project_id, str(row.get("sourceId") or ""), int(row.get("absoluteStart") or 0),
                int(row.get("absoluteEnd") or 0), window_chars=_ASSET_ADJACENT_SOURCE_CHARS,
            )}
        if part == "material_catalog":
            return {**receipt, "materialCatalog": asset_material_catalog(manifest, offset)}
        if part == "material_evidence":
            return {**receipt, "materialEvidence": asset_material_evidence(
                project_id, manifest, queries=queries, relative_path=relative_path,
                offset=offset, line_start=line_start, line_count=line_count)}
        if part == "design_context":
            return {**receipt, "designContext": {
                "phaseVisualContexts": row.get("phaseVisualContexts") or [],
                "productionSpec": context["productionSpec"],
                "genreContext": context["designInputs"]["genreContext"],
                "visualDirection": context["designInputs"].get("visualDirection") or {},
            }}
    except (ValueError, OSError, IndexError) as exc:
        return _failure(_error("assetRangeId", "range_unavailable", str(exc), "stop"))
    if part == "task_state":
        return {**receipt, "taskState": {
            "assetRangeId": range_id, "inputDigest": digest,
            "requirementRevision": revision,
            "assetTypes": row.get("assetTypes") or list(_ASSET_TYPES),
            "materialCatalog": asset_material_catalog(manifest),
        }}
    raise AssertionError("已校验的资料分支必须返回结果")


def get_asset_extraction_asset_catalog(
    project_id: str, *, asset_type: str, offset: int = 0, limit: int = 20,
) -> dict[str, Any]:
    if asset_type not in _ASSET_TYPES:
        return _failure(_error("assetType", "invalid_type", "请选择角色、生物、场景或道具类型", "stop"))
    offset = max(0, int(offset))
    limit = max(1, min(40, int(limit)))
    document = list_assets("project", project_id, hydrate=False, lifecycle_status="active", persist_normalization=False)
    rows = [row for row in (document.get(asset_type) or []) if isinstance(row, dict)]
    page = []
    for row in rows[offset:offset + limit]:
        prompts = row.get("prompts") if isinstance(row.get("prompts"), dict) else {}
        page.append({
            "id": str(row.get("id") or ""), "name": str(row.get("name") or row.get("title") or ""),
            "aliases": copy.deepcopy(row.get("aliases") or []),
            "desc": str(row.get("desc") or "")[:300],
            "assetImagePrompt": str(prompts.get("assetImagePrompt") or "")[:300],
            "voiceStyle": str(row.get("voiceStyle") or "")[:120],
            "userLocked": bool(row.get("userLocked")),
        })
    return {"success": True, "assetType": asset_type, "offset": offset, "limit": limit,
            "total": len(rows), "hasMore": offset + len(page) < len(rows), "assets": page}


def _submission_shape_errors(batch: Any) -> list[dict[str, str]]:
    if not isinstance(batch, dict):
        return [_error("assetBatch", "invalid_type", "assetBatch 必须是对象")]
    errors: list[dict[str, str]] = []
    for kind in _ASSET_TYPES:
        rows = batch.get(kind)
        if not isinstance(rows, list):
            errors.append(_error(f"assetBatch.{kind}", "required", f"{kind} 必须是数组，可为空"))
            continue
        for index, row in enumerate(rows):
            path = f"assetBatch.{kind}[{index}]"
            if not isinstance(row, dict):
                errors.append(_error(path, "invalid_type", "资产必须是对象"))
                continue
            if "sourceRefs" in row:
                errors.append(_error(f"{path}.sourceRefs", "untrusted_coordinates",
                                     "不要填写 sourceRefs；后端从 sourceEvidence 原文推导"))
            evidence = row.get("sourceEvidence")
            if not isinstance(evidence, list) or not evidence or any(
                not isinstance(value, str) or not value.strip() for value in evidence):
                errors.append(_error(f"{path}.sourceEvidence", "required",
                                     "每条资产必须给出至少一段当前范围中的连续原文证据"))
    audit = batch.get("coverageAudit")
    if not isinstance(audit, dict) or audit.get("checked") is not True:
        errors.append(_error("assetBatch.coverageAudit.checked", "audit_required",
                             "提交前必须完成四类资产与跳过提及的覆盖审查"))
    return errors[:20]


def _evidence_repair_hint(source_text: str, excerpt: str) -> dict[str, Any]:
    """Offer a bounded, verbatim source window, never an automatic replacement."""
    match = SequenceMatcher(None, excerpt[:600], source_text, autojunk=False).find_longest_match()
    if match.size < max(4, min(len(excerpt), 600) // 4):
        return {}
    start = max(source_text.rfind('\n', 0, match.b) + 1, match.b - 120)
    line_end = source_text.find('\n', match.b + match.size)
    end = min(len(source_text) if line_end < 0 else line_end, start + 480)
    return {'sourceExcerpt': source_text[start:end],
            'sourceExcerptStart': start, 'sourceExcerptEnd': end,
            'hint': '偏移相对当前范围；仅为相似原文定位线索，请核对身份及语义后逐字选取，不能自动替换。'}


def _evidence_errors(batch: dict[str, Any], source_text: str) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for kind in _ASSET_TYPES:
        for index, row in enumerate(batch.get(kind) or []):
            if not isinstance(row, dict):
                continue
            for evidence_index, excerpt in enumerate(row.get("sourceEvidence") or []):
                if not _find_asset_evidence_range(source_text, excerpt):
                    error = _error(
                        f"assetBatch.{kind}[{index}].sourceEvidence[{evidence_index}]",
                        "evidence_not_found", "来源证据必须逐字摘自当前已确认范围，不能概括或改写",
                    )
                    error.update({'submittedExcerpt': excerpt[:600],
                                  **_evidence_repair_hint(source_text, excerpt)})
                    errors.append(error)
    return errors[:20]


def _ensure_coverage_table(batch: dict[str, Any]) -> None:
    if isinstance(batch.get("assetCoverageTable"), dict):
        return
    table: dict[str, list[dict[str, Any]]] = {}
    for kind in _ASSET_TYPES:
        table[kind] = [
            {"candidateId": str(row.get("candidateId") or f"{kind}-{index + 1:03d}"),
             "name": str(row.get("name") or ""),
             "status": "reused" if row.get("assetId") else "new_designed",
             **({"assetId": str(row["assetId"])} if row.get("assetId") else {})}
            for index, row in enumerate(batch.get(kind) or []) if isinstance(row, dict)
        ]
    batch["assetCoverageTable"] = {"assetTypes": table}


def _committed_result(
    project_id: str, session_id: str, execution_id: str, range_id: str,
    input_digest: str, output_digest: str, save_result: dict[str, Any], *, replayed: bool = False,
) -> dict[str, Any]:
    receipt_id = _hash({"executionId": execution_id, "rangeId": range_id,
                        "inputDigest": input_digest, "outputDigest": output_digest})
    receipt = {
        "receiptId": receipt_id, "runId": execution_id,
        # Project-scope AgentToolContext carries episode_id=None. The shared
        # receipt gate compares normalized IDs and expects an empty episode ID.
        "projectId": project_id, "episodeId": "",
        "sessionId": session_id, "executionId": execution_id,
        "taskType": "asset_extraction", "targetIds": [range_id],
        "inputDigest": input_digest, "outputDigest": output_digest,
        "changedResources": save_result.get("changedResources") or ["sourceCoverage", "assetRanges"],
    }
    return {"success": True, "status": "committed", "assetRangeId": range_id,
            "commitReceipt": receipt, "receiptId": receipt_id,
            "assetCounts": save_result.get("assetCounts") or {},
            "changedResources": [] if replayed else receipt["changedResources"],
            "projectChanged": not replayed, "idempotent": replayed,
            "focusTarget": {"section": "assets"}}


def submit_asset_extraction_result(
    project_id: str, args: dict[str, Any], *, session_id: str,
    execution_id: str, user_instruction: str = "",
) -> dict[str, Any]:
    range_id = str(args.get("assetRangeId") or "").strip()
    input_digest = str(args.get("inputDigest") or "").strip()
    batch = args.get("assetBatch")
    if not range_id or not input_digest:
        return _failure(_error("assetRangeId/inputDigest", "required", "缺少目标资产范围或读取上下文返回的摘要"))
    if not session_id or not execution_id:
        return _failure(_error("executionId", "execution_unavailable", "当前智能体执行轮次无效", "stop"))
    shape_errors = _submission_shape_errors(batch)
    if shape_errors:
        return _failure(*shape_errors)
    output_digest = _hash(batch)
    worker_run_id = f"agent-asset-{execution_id}"
    with _LOCK:
        try:
            revision = _session_revision(project_id, session_id)
            if args.get("requirementRevision") != revision:
                return _failure(_error("requirementRevision", "new_user_feedback",
                                       "用户已补充新的拆分要求，请读取最新上下文并据此修订", "reread_context"))
            coverage = _load_source_coverage(project_id)
            committed_row = next((row for row in (coverage.get("assetRanges") or [])
                                  if isinstance(row, dict) and str(row.get("rangeId") or "") == range_id), None)
            if isinstance(committed_row, dict) and committed_row.get("analysisStatus") == "completed":
                details = committed_row.get("analysisResult") or {}
                if (details.get("workerRunId") == worker_run_id
                        and details.get("inputDigest") == input_digest
                        and details.get("outputDigest") == output_digest
                        and isinstance(details.get("saveResult"), dict)):
                    return _committed_result(project_id, session_id, execution_id, range_id,
                                             input_digest, output_digest, details["saveResult"], replayed=True)
                return _failure(_error("assetRangeId", "already_completed",
                                       "该资产范围已完成拆分；请勿重复写入", "stop"))
            row = _target_range(project_id, range_id)
            snapshot = source_snapshot(project_id, range_id)
            context = _task_context(project_id, row)
            context["designInputs"] = _design_inputs(project_id, asset_material_manifest(project_id))
        except (ValueError, FileNotFoundError, IndexError) as exc:
            return _failure(_error("assetRangeId", "range_unavailable", str(exc), "stop"))
        if _input_digest(snapshot, row, context, revision) != input_digest:
            return _failure(_error("inputDigest", "stale_context",
                                   "原文、已有资产设计、扩展资料或项目设置已变化，请重读受影响资料和任务状态后修订", "reread_context"))
        evidence_errors = _evidence_errors(batch, str(context.get("sourceText") or ""))
        if evidence_errors:
            return _failure(*evidence_errors)
        validation = validate_analyze_assets_worker_output(
            project_id, {"assetBatch": batch}, asset_range_id=range_id,
            task_context=context, require_design_contract=True,
        )
        if not validation.get("success"):
            return _failure(*[_error("assetBatch", "contract_validation_failed", str(issue))
                              for issue in (validation.get("blockingIssues") or ["资产结果未通过校验"])[:15]])
        duplicates = validation.get("skippedDuplicates") or {}
        if any(duplicates.get(kind) for kind in _ASSET_TYPES):
            return _failure(_error("assetBatch", "duplicate_identity",
                                   "同一类资产内存在重复名称或重复 assetId，请归并后重新提交"))
        normalized = validation.get("assetBatch") if isinstance(validation.get("assetBatch"), dict) else {}
        _ensure_coverage_table(normalized)
        details = {
            "origin": "native_agent", "inputDigest": input_digest, "outputDigest": output_digest,
            "requirementRevision": revision, "userInstruction": user_instruction[:1200],
            "newCounts": validation.get("newCounts") or {},
            "skippedDuplicates": duplicates,
            "designInputVersions": context["designInputs"],
        }
        try:
            save_result = commit_asset_analysis(
                project_id, normalized, snapshot=snapshot,
                worker_run_id=worker_run_id, details=details,
            )
        except Exception:
            print(traceback.format_exc(), flush=True)
            # The journal may have completed both writes before an ancillary
            # metadata or event update failed. Read the authoritative record
            # before declaring the commit uncertain.
            try:
                recovered = _load_source_coverage(project_id)
                recovered_row = next((item for item in (recovered.get("assetRanges") or [])
                                      if isinstance(item, dict)
                                      and str(item.get("rangeId") or "") == range_id), None)
                recovered_result = (recovered_row or {}).get("analysisResult") or {}
                if (recovered_row and recovered_row.get("analysisStatus") == "completed"
                        and recovered_result.get("workerRunId") == worker_run_id
                        and recovered_result.get("inputDigest") == input_digest
                        and recovered_result.get("outputDigest") == output_digest
                        and isinstance(recovered_result.get("saveResult"), dict)):
                    return _committed_result(project_id, session_id, execution_id, range_id,
                                             input_digest, output_digest, recovered_result["saveResult"])
            except Exception:
                print(traceback.format_exc(), flush=True)
            return _failure(_error("assetBatch", "commit_unknown",
                                   "资产提交状态暂无法核实；请先读取项目状态，不能盲目重提", "stop"),
                            status="commit_unknown")
        coverage_after = _load_source_coverage(project_id)
        row_after = next((item for item in (coverage_after.get("assetRanges") or [])
                          if isinstance(item, dict) and str(item.get("rangeId") or "") == range_id), None)
        actual = (row_after or {}).get("analysisResult") or {}
        if (not row_after or row_after.get("analysisStatus") != "completed"
                or actual.get("workerRunId") != worker_run_id
                or actual.get("inputDigest") != input_digest
                or actual.get("outputDigest") != output_digest
                or not isinstance(actual.get("saveResult"), dict)):
            return _failure(_error("assetBatch", "commit_unverified",
                                   "资产提交后回读未通过，结果未对用户宣布完成", "stop"),
                            status="commit_unverified")
        _emit_agent_event("project_changed", {
            "action": "asset_batch_saved", "projectId": project_id,
            "assetRangeId": range_id, "changedResources": save_result.get("changedResources") or [],
        })
        return _committed_result(project_id, session_id, execution_id, range_id,
                                 input_digest, output_digest, save_result)
