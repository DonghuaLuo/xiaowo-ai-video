# -*- coding: utf-8 -*-
"""Version-bound audience information map for an authored cinematic script."""
from __future__ import annotations

import copy
import re
from typing import Any

from .workflow_cinematic_script import _workflow_script_story_text_hash


_DELIVERY_PATHS = frozenset({
    "visible_action", "dialogue", "inner_voice", "narration",
    "screen_text",
})
_SOURCE_KINDS = frozenset({"source_fragment", "user_instruction"})


def _plain(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_script_delivery_contract(
    value: Any, *, source_text: str, script_text: str, user_instruction: str,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """Check literal anchors and shape; semantic completeness remains an agent/eval duty."""
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        return None, [{"path": "deliveryContract.items", "code": "required",
                       "message": "请提交观众信息交付条目", "repairAction": "revise_and_resubmit"}]
    items = value["items"]
    if not items or len(items) > 64:
        return None, [{"path": "deliveryContract.items", "code": "invalid_count",
                       "message": "交付条目须包含本片段必要信息，最多 64 条", "repairAction": "revise_and_resubmit"}]
    normalized: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    source_haystacks = {
        "source_fragment": _plain(source_text),
        "user_instruction": _plain(user_instruction),
    }
    script_haystack = _plain(script_text)
    for index, item in enumerate(items):
        prefix = f"deliveryContract.items[{index}]"
        if not isinstance(item, dict):
            errors.append({"path": prefix, "code": "invalid_item", "message": "交付条目须为对象",
                           "repairAction": "revise_and_resubmit"})
            continue
        source_kind = _plain(item.get("sourceKind"))
        source_quote = _plain(item.get("sourceQuote"))
        audience_information = _plain(item.get("audienceInformation"))
        time_and_certainty = _plain(item.get("timeAndCertainty"))
        script_evidence = _plain(item.get("scriptEvidence"))
        paths = item.get("deliveryPaths")
        if source_kind not in _SOURCE_KINDS:
            errors.append({"path": f"{prefix}.sourceKind", "code": "invalid_source",
                           "message": "来源须为片段原文或本轮用户要求", "repairAction": "revise_and_resubmit"})
        if not 2 <= len(source_quote) <= 240 or source_quote not in source_haystacks.get(source_kind, ""):
            errors.append({"path": f"{prefix}.sourceQuote", "code": "source_mismatch",
                           "message": "来源短引文须逐字出现在对应资料中", "repairAction": "revise_and_resubmit"})
        if not audience_information or len(audience_information) > 240:
            errors.append({"path": f"{prefix}.audienceInformation", "code": "invalid_text",
                           "message": "请简述观众必须获得的信息", "repairAction": "revise_and_resubmit"})
        if not time_and_certainty or len(time_and_certainty) > 120:
            errors.append({"path": f"{prefix}.timeAndCertainty", "code": "invalid_text",
                           "message": "请简述时间关系和事实确定程度", "repairAction": "revise_and_resubmit"})
        if not isinstance(paths, list) or not paths or any(
            not isinstance(path, str) or path not in _DELIVERY_PATHS for path in paths
        ):
            errors.append({"path": f"{prefix}.deliveryPaths", "code": "invalid_path",
                           "message": "请使用有效的声画交付方式", "repairAction": "revise_and_resubmit"})
        if not 2 <= len(script_evidence) <= 240 or script_evidence not in script_haystack:
            errors.append({"path": f"{prefix}.scriptEvidence", "code": "script_mismatch",
                           "message": "剧本短引文须逐字出现在本次提交的剧本中", "repairAction": "revise_and_resubmit"})
        if isinstance(paths, list) and paths and all(path == "screen_text" for path in paths):
            errors.append({"path": f"{prefix}.deliveryPaths", "code": "screen_text_only",
                           "message": "关键媒介信息不能只靠观众读屏交付；保留画面信息流，同时用有来源的人声或可见行动传达关键意思",
                           "repairAction": "revise_and_resubmit"})
        if any(error["path"].startswith(prefix) for error in errors):
            continue
        normalized.append({
            "sourceKind": source_kind,
            "sourceQuote": source_quote,
            "audienceInformation": audience_information,
            "timeAndCertainty": time_and_certainty,
            "deliveryPaths": list(dict.fromkeys(paths)),
            "scriptEvidence": script_evidence,
        })
    if errors:
        return None, errors
    return {
        "schemaVersion": 1,
        "sourceTextHash": _workflow_script_story_text_hash(source_text),
        "scriptStoryTextHash": _workflow_script_story_text_hash(script_text),
        "items": normalized,
    }, []


def current_script_delivery_contract(script_data: dict[str, Any]) -> dict[str, Any] | None:
    """Never carry a stale sidecar across manual script/source edits."""
    contract = script_data.get("scriptDeliveryContract")
    if not isinstance(contract, dict) or contract.get("schemaVersion") != 1:
        return None
    if not isinstance(contract.get("items"), list) or not contract["items"]:
        return None
    script_text = script_data.get("cinematicStoryText")
    source_text = script_data.get("sourceFactText")
    if contract.get("scriptStoryTextHash") != _workflow_script_story_text_hash(script_text):
        return None
    if contract.get("sourceTextHash") != _workflow_script_story_text_hash(source_text):
        return None
    return copy.deepcopy(contract)
