# -*- coding: utf-8 -*-
"""Shared helpers for generated media quality gate checks."""

from __future__ import annotations

import copy
from typing import Any


BLOCKING_VARIANT_QUALITY_STATUSES = {"failed", "blocked"}


def _quality_result_status(result: dict[str, Any]) -> str:
    return str(result.get("status") or result.get("result") or "").strip().lower()


def _quality_result_waived(result: dict[str, Any]) -> bool:
    return bool(result.get("waived") or result.get("exempted"))


def _quality_result_version_id(result: dict[str, Any]) -> str:
    return str(result.get("versionId") or result.get("version_id") or "").strip()


def _quality_result_matches_version(result: dict[str, Any], version_id: str) -> bool:
    if not version_id:
        return True
    result_version_id = _quality_result_version_id(result)
    return not result_version_id or result_version_id == version_id


def variant_quality_result_blocks(result: Any, *, version_id: str = "") -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("reportOnly") is True:
        return False
    if not _quality_result_matches_version(result, version_id):
        return False
    if _quality_result_waived(result):
        return False
    return _quality_result_status(result) in BLOCKING_VARIANT_QUALITY_STATUSES


def _workflow_node_quality(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
    return quality


def workflow_node_quality_result(
    node: dict[str, Any],
    *,
    version: dict[str, Any] | None = None,
    version_id: str = "",
) -> dict[str, Any]:
    active_version_id = str(version_id or ((version or {}).get("id") if isinstance(version, dict) else "") or "").strip()
    if isinstance(version, dict) and isinstance(version.get("qualityResult"), dict):
        result = copy.deepcopy(version["qualityResult"])
        if _quality_result_matches_version(result, active_version_id):
            return result
    node_result = _workflow_node_quality(node).get("lastVariantQualityResult")
    if isinstance(node_result, dict) and _quality_result_matches_version(node_result, active_version_id):
        return copy.deepcopy(node_result)
    return {}


def workflow_node_quality_blocks(
    node: dict[str, Any],
    *,
    version: dict[str, Any] | None = None,
    version_id: str = "",
) -> bool:
    active_version_id = str(version_id or ((version or {}).get("id") if isinstance(version, dict) else "") or "").strip()
    if isinstance(version, dict) and variant_quality_result_blocks(version.get("qualityResult"), version_id=active_version_id):
        return True
    node_result = workflow_node_quality_result(node, version=version, version_id=active_version_id)
    if variant_quality_result_blocks(node_result, version_id=active_version_id):
        return True
    quality = _workflow_node_quality(node)
    if bool(quality.get("variantQualityBlocked")):
        raw_node_result = quality.get("lastVariantQualityResult")
        if isinstance(raw_node_result, dict):
            if raw_node_result.get("reportOnly") is True:
                return False
            if not _quality_result_matches_version(raw_node_result, active_version_id):
                return False
            return not _quality_result_waived(raw_node_result)
        return True
    return False


def workflow_node_quality_block_message(
    node: dict[str, Any],
    *,
    version: dict[str, Any] | None = None,
    version_id: str = "",
) -> str:
    if not workflow_node_quality_blocks(node, version=version, version_id=version_id):
        return ""
    result = workflow_node_quality_result(node, version=version, version_id=version_id)
    blockers = result.get("blockers") if isinstance(result.get("blockers"), list) else []
    first_blocker = next((item for item in blockers if item), None)
    if isinstance(first_blocker, dict):
        detail = str(first_blocker.get("message") or first_blocker.get("description") or "").strip()
        if not detail:
            detail = str(first_blocker.get("id") or first_blocker.get("code") or "").strip()
    else:
        detail = str(first_blocker or "").strip()
    status = _quality_result_status(result) or "blocked"
    if detail:
        return f"自动质检未通过（{status}）：{detail}"
    return f"自动质检未通过（{status}），请重新生成、改用其它候选或填写豁免原因。"


__all__ = (
    "BLOCKING_VARIANT_QUALITY_STATUSES",
    "variant_quality_result_blocks",
    "workflow_node_quality_result",
    "workflow_node_quality_blocks",
    "workflow_node_quality_block_message",
)
