"""Commit reviewed inventory and range completion with a recoverable journal."""
from __future__ import annotations

import copy
import hashlib
import json
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from .store_core import _JSON_WRITE_LOCK, _now, _read_json, _write_json

_RECOVERING = ContextVar("asset_analysis_recovery", default=False)
_JOURNAL = ".asset-analysis-commit.json"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def source_snapshot(project_id: str, range_id: str) -> dict[str, Any]:
    from .asset_range_bindings import _source_window_for_asset_range
    source_id, start, end, text = _source_window_for_asset_range(project_id, range_id)
    if not source_id or not text or end <= start:
        raise ValueError("资产拆分缺少有效原文范围")
    return {"sourceId": source_id, "absoluteStart": start, "absoluteEnd": end, "sha256": _hash(text),
            "assetIdentityHash": asset_identity_hash(project_id)}


def asset_identity_hash(project_id: str) -> str:
    from .agent_sessions import _project_dir
    assets = _read_json(_project_dir(project_id) / "assets/assets.json", {})
    fields = ("id", "name", "aliases", "desc", "assetImagePrompt", "prompts", "voiceStyle", "lifecycleStatus", "userLocked")
    return _hash({kind: sorted(({key: row.get(key) for key in fields} for row in assets.get(kind, [])
                              if isinstance(row, dict)), key=lambda row: str(row.get("id") or ""))
                  for kind in ("characters", "creatures", "scenes", "props")})


def recover_asset_analysis_for_path(path: Path) -> None:
    if _RECOVERING.get():
        return
    if path.name == "source_coverage.json":
        root = path.parent
    elif path.name == "assets.json" and path.parent.name == "assets":
        root = path.parent.parent
    else:
        return
    journal_path = root / _JOURNAL
    with _JSON_WRITE_LOCK:
        if not journal_path.exists():
            return
        token = _RECOVERING.set(True)
        try:
            journal = _read_json(journal_path, {})
            documents = journal["documents"]
            if set(documents) != {"assets/assets.json", "source_coverage.json"}:
                raise ValueError("资产提交日志的文件范围无效")
            # Validate both documents before touching either one. Never overwrite later edits.
            for relative, entry in documents.items():
                current = _read_json(root / relative, {})
                if _hash(current) not in {entry["beforeHash"], _hash(entry["after"])}:
                    raise ValueError("资产提交恢复遇到后续修改，请保留提交日志并人工检查")
            for relative, entry in documents.items():
                target = root / relative
                if _read_json(target, {}) != entry["after"]:
                    _write_json(target, entry["after"])
            journal_path.unlink()
        finally:
            _RECOVERING.reset(token)


def commit_asset_analysis(
    project_id: str, payload: dict[str, Any], *, snapshot: dict[str, Any],
    worker_run_id: str, details: dict[str, Any],
) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    from .asset_text_ingestion import _save_agent_text_assets
    from .runtime_state import _LOCK
    from .source_coverage import _load_source_coverage, _validate_asset_batch_refs_in_range, _stamp_asset_range_id
    from .project_resource_revisions import _append_resource_revision
    from .projects import _touch_project_meta
    from .worker_asset_ownership import asset_ownership_issues

    range_id = str(payload.get("assetRangeId") or "")
    if not range_id or not worker_run_id or not snapshot:
        raise ValueError("资产提交缺少范围、任务编号或原文快照，请重新分析")
    ownership_issues = asset_ownership_issues(payload)
    if ownership_issues:
        raise ValueError("；".join(ownership_issues[:3]))
    root = _project_dir(project_id)
    with _LOCK, _JSON_WRITE_LOCK:
        coverage = _load_source_coverage(project_id)
        row = next((r for r in coverage["assetRanges"] if r.get("rangeId") == range_id), None)
        if row is None:
            raise ValueError("资产范围已不存在")
        previous = row.get("analysisResult") or {}
        if row.get("analysisStatus") == "completed" and previous.get("workerRunId") == worker_run_id:
            return copy.deepcopy(previous["saveResult"])
        if source_snapshot(project_id, range_id) != snapshot:
            raise ValueError("分析期间原文、范围或已有资产设计已变更，本次结果未保存，请重新分析")
        _validate_asset_batch_refs_in_range(project_id, payload, range_id)
        before_assets = _read_json(root / "assets/assets.json", {})
        before_coverage = _read_json(root / "source_coverage.json", {})
        result = _save_agent_text_assets(project_id, _stamp_asset_range_id(payload, range_id),
                                         persist=False, asset_document=before_assets)
        assets = result.pop("document")
        changed = list(result["changedTypes"])
        if changed:
            assets["revision"] = int(before_assets.get("revision") or 0) + 1
            assets["updatedAt"] = _now()
        row["createdAssetIds"] = [
            str(asset["id"]) for kind in ("characters", "creatures", "scenes", "props")
            for asset in assets.get(kind, []) if isinstance(asset, dict) and asset.get("id")
            and (asset.get("assetRangeId") == range_id or range_id in (asset.get("assetRangeIds") or []))
        ]
        save_result = {
            "success": True, "assetRangeId": range_id, "assetCounts": result.pop("counts"),
            "changedResources": list(dict.fromkeys([*changed, "sourceCoverage", "assetRanges"])),
            "projectChanged": True, "assetCoverageTable": copy.deepcopy(payload.get("assetCoverageTable") or {}),
            **result,
        }
        row.update(analysisStatus="completed", analysisUpdatedAt=_now(), analysisResult={
            **copy.deepcopy(details), "workerRunId": worker_run_id, "sourceSnapshot": snapshot,
            "saveResult": save_result,
        })
        row.pop("analysisError", None)
        row.pop("analysisDetails", None)
        coverage["revision"] = int(before_coverage.get("revision") or 0) + 1
        coverage["updatedAt"] = _now()
        # Revision backups are ancillary; neither live document changes before the journal exists.
        for resource, relative, before in (("assets", "assets/assets.json", before_assets),
                                           ("sourceCoverage", "source_coverage.json", before_coverage)):
            _append_resource_revision(project_id, resource=resource, relative_path=relative,
                                      document=before, reason="asset_analysis_commit")
        _write_json(root / _JOURNAL, {"documents": {
            "assets/assets.json": {"beforeHash": _hash(before_assets), "after": assets},
            "source_coverage.json": {"beforeHash": _hash(before_coverage), "after": coverage},
        }})
        recover_asset_analysis_for_path(root / "source_coverage.json")
        _touch_project_meta(project_id)
        return save_result


def completed_asset_analysis(project_id: str, range_id: str, worker_run_id: str) -> dict[str, Any] | None:
    from .agent_sessions import _project_dir
    coverage = _read_json(_project_dir(project_id) / "source_coverage.json", {})
    for row in coverage.get("assetRanges", []):
        details = row.get("analysisResult") or {}
        if (row.get("rangeId") == range_id and row.get("analysisStatus") == "completed"
                and details.get("workerRunId") == worker_run_id):
            return copy.deepcopy(details.get("saveResult"))
    return None
