"""Structural checks for details represented by another candidate's master asset."""
from __future__ import annotations

import copy
from typing import Any

from .worker_asset_contract import _ASSET_TYPES


ASSET_OWNERSHIP_CONTRACT = (
    "不独立建卡分两种：由另一候选的母版承载时用 part_of 并填写 ownerCandidateId；"
    "只留给分镜、不归入任何候选母版的内容才用无 owner 的 skip。"
    "不能只在跳过理由里写由另一候选覆盖而遗漏结构化归属。"
    "part_of 在覆盖表中表示为 skipped 加 ownerCandidateId，不能仅凭 skipped 判定归属无效。"
    "允许沿 ownerCandidateId 和 merge 的 targetCandidateId 多级到达新增或复用母版，不要求直接引用最终节点；"
    "整体与细节确实均不建卡时可共同留给分镜。缺失目标、自引用、循环和未决目标不可接受。"
    "归属对象是否正确按原文和资料判断，不因名称相似或位置接近猜测。"
)


def owner_only_repair_candidates(before: dict, issues: list[dict], asset_type: str) -> dict[str, dict]:
    """Share the field-level repair boundary between the prompt and controller."""
    by_candidate: dict[str, list[dict]] = {}
    for issue in issues:
        if issue.get("assetType") == asset_type and issue.get("category") != "aesthetic":
            by_candidate.setdefault(issue.get("candidateId", ""), []).append(issue)
    return {row["candidateId"]: row for row in before.get(asset_type, [])
            if row.get("candidateId") in by_candidate and row.get("ownerCandidateId")
            and all(issue.get("field") == "ownerCandidateId" for issue in by_candidate[row["candidateId"]])}


def _owner_repair_path(candidates: dict, candidate_id: str) -> tuple:
    by_id = {row.get("candidateId"): row for kind in _ASSET_TYPES for row in candidates.get(kind, [])}
    path, seen = [], set()
    current = candidate_id
    while current:
        if current in seen or current not in by_id:
            raise ValueError(f"{candidate_id} 归属链存在循环或缺失目标：{current}")
        seen.add(current)
        row = by_id[current]
        owner = row.get("ownerCandidateId")
        target = row.get("targetCandidateId") if row.get("decision") == "merge" else None
        path.append((current, row.get("decision"), owner, target, row.get("assetId")))
        if not owner and not target:
            if row.get("decision") not in {"keep_new", "reuse_existing", "skip"}:
                raise ValueError(f"{candidate_id} 归属链目标未决：{current}")
            return tuple(path)
        current = owner or target
    return tuple(path)


def preserve_owner_only_repairs(
    before: dict, after: dict, issues: list[dict], asset_type: str, *, validate_paths: bool = True,
) -> dict:
    """Preserve detail facts, then check progress against the complete repaired graph."""
    original = owner_only_repair_candidates(before, issues, asset_type)
    result = copy.deepcopy(after)
    for index, row in enumerate(result.get(asset_type, [])):
        candidate_id = row.get("candidateId")
        previous = original.get(candidate_id, {})
        if not previous:
            continue
        if row.get("decision") != previous.get("decision") or not row.get("ownerCandidateId"):
            raise ValueError(f"{candidate_id} 本轮只允许修正归属，不能改变资产处置")
        result[asset_type][index] = {**copy.deepcopy(previous), "ownerCandidateId": row["ownerCandidateId"]}
    if not validate_paths:
        # Batch identity repairs validate paths only after every type has contributed.
        return result
    for candidate_id in original:
        repaired_path = _owner_repair_path(result, candidate_id)
        try:
            previous_path = _owner_repair_path(before, candidate_id)
        except ValueError:
            previous_path = None
        if repaired_path == previous_path:
            raise ValueError(f"{candidate_id} 归属返工未产生修改，不能宣告修复完成")
    return result


def _analyze_assets_owner_detail_facts(
    candidates: dict, context: dict | None = None,
) -> dict[str, list[dict]]:
    """Resolve detail facts from the full inventory, before design batching."""
    by_id: dict[str, tuple[str, dict]] = {}
    duplicate_ids: set[str] = set()
    for asset_type in _ASSET_TYPES:
        for row in candidates.get(asset_type) or []:
            if not isinstance(row, dict):
                continue
            candidate_id = str(row.get("candidateId") or "").strip()
            if not candidate_id:
                continue
            if candidate_id in by_id:
                duplicate_ids.add(candidate_id)
            by_id[candidate_id] = (asset_type, row)

    material_by_id: dict[str, list[dict]] = {}
    materials = (context or {}).get("assetMaterialDigests") or {}
    if isinstance(materials, dict):
        for asset_type in _ASSET_TYPES:
            for digest in materials.get(asset_type) or []:
                if isinstance(digest, dict):
                    candidate_id = str(digest.get("candidateId") or "").strip()
                    material_by_id.setdefault(candidate_id, []).append(digest)

    result: dict[str, list[dict]] = {}
    for candidate_id, (asset_type, detail) in by_id.items():
        owner_id = str(detail.get("ownerCandidateId") or "").strip()
        if not owner_id or candidate_id in duplicate_ids:
            continue
        seen = {candidate_id}
        while owner_id:
            # Invalid chains stay with structural validation, never a guessed owner.
            if owner_id in seen or owner_id in duplicate_ids or owner_id not in by_id:
                break
            seen.add(owner_id)
            owner = by_id[owner_id][1]
            if owner.get("ownerCandidateId"):
                owner_id = str(owner["ownerCandidateId"]).strip()
                continue
            if owner.get("decision") == "merge" or owner.get("status") == "merged":
                owner_id = str(owner.get("targetCandidateId") or "").strip()
                continue
            if owner.get("decision") in {"part_of", "unresolved"}:
                break
            fact = {
                "candidateId": candidate_id,
                "name": str(detail.get("name") or "").strip(),
                "assetType": asset_type,
                "sourceUse": str(detail.get("sourceUse") or "").strip(),
                "reason": str(detail.get("reason") or detail.get("identityReason") or "").strip(),
            }
            if material_by_id.get(candidate_id):
                fact["materialDigests"] = copy.deepcopy(material_by_id[candidate_id])
            result.setdefault(owner_id, []).append(fact)
            break
    return result


def asset_ownership_issues(output: dict[str, Any], *, complete: bool = True) -> list[str]:
    table = (output.get("assetCoverageTable") or {}).get("assetTypes") or {}
    rows = [row for kind in _ASSET_TYPES for row in table.get(kind) or [] if isinstance(row, dict)]
    details = [row for row in rows if row.get("ownerCandidateId")]
    if not details:
        return []
    by_id = {str(row.get("candidateId") or ""): row for row in rows}
    designed_ids = {str(row.get("candidateId") or "") for kind in _ASSET_TYPES
                    for row in output.get(kind) or [] if isinstance(row, dict)}
    issues = []
    for detail in details:
        candidate_id = str(detail.get("candidateId") or "")
        prefix = f"附属细节 {candidate_id}"
        if any(detail in (table.get(kind) or []) for kind in ("characters", "creatures")):
            issues.append(f"{prefix} 活体主体不能使用部件归属")
        if detail.get("status") != "skipped" or candidate_id in designed_ids:
            issues.append(f"{prefix} 不得同时独立建卡")
        if not str(detail.get("sourceUse") or "").strip():
            issues.append(f"{prefix} 缺少需要承载的事实细节")
        seen = {candidate_id}
        target_id = str(detail["ownerCandidateId"])
        while target_id:
            if target_id in seen:
                issues.append(f"{prefix} 归属关系存在循环")
                break
            seen.add(target_id)
            target = by_id.get(target_id)
            if target is None:
                if complete:
                    issues.append(f"{prefix} 归属目标不存在：{target_id}")
                break
            if target.get("ownerCandidateId"):
                target_id = str(target["ownerCandidateId"])
                continue
            if target.get("status") == "merged" and target.get("targetCandidateId"):
                target_id = str(target["targetCandidateId"])
                continue
            status = target.get("status")
            if status == "reused" and target.get("assetId"):
                break
            if status == "skipped" and str(target.get("reason") or "").strip() and target_id not in designed_ids:
                break
            if status == "new_designed" and (not complete or target_id in designed_ids):
                break
            if not complete and status == "new_pending_design":
                break
            issues.append(f"{prefix} 归属目标未保留或未形成母版：{target_id}")
            break
    return issues
