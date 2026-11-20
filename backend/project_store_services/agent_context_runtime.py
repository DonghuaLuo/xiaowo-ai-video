# -*- coding: utf-8 -*-
"""项目权限读取与待确认候选的紧凑领域表示。"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from .catalogs import AGENT_OPS_PERMISSIONS_DIR


def _compact_text(value: str, limit: int = 80) -> str:
    """Lossy excerpt helper for agent diagnostics/context windows only.

    Do not use this for canonical project data, generated prompts, provider API
    payloads, or any field that must remain complete for generation.
    """
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def _load_agent_ops_permissions() -> dict[str, Any]:
    path = AGENT_OPS_PERMISSIONS_DIR / "desktop_allowed_actions.json"
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _agent_json_chars(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        return len(str(value or ""))


def _agent_context_budget_for_task(_task_hypothesis: dict[str, Any] | None) -> dict[str, Any]:
    # Source windows used by the on-demand snapshot have an explicit bound.
    return {"sourceTextMaxChars": 1800, "recentMessageLimit": 8,
            "creativeMemoryMaxChars": 1200, "productionMemoryMaxChars": 1000}



def _agent_compact_proposal(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    text_limits = {
        "reason": 260,
        "title": 120,
        "episodeTitle": 120,
        "hook": 220,
        "endingQuestion": 180,
        "summary": 260,
        "storyUnitSummary": 220,
        "boundaryEndText": 180,
        "workflowBenefit": 220,
        "planningMethod": 80,
        "excerpt": 180,
        "createdAt": 80,
    }
    keys = (
        "proposalId",
        "rangeId",
        "episodeId",
        "title",
        "episodeTitle",
        "sourceId",
        "startOffset",
        "endOffset",
        "recommendedEndOffset",
        "absoluteStart",
        "absoluteEnd",
        "targetUnits",
        "actualUnits",
        "boundaryToleranceUnits",
        "planningLookaheadUnits",
        "planningWindowEnd",
        "planningMethod",
        "boundaryEndText",
        "assetTypes",
        "phaseVisualContext",
        "phase_visual_context",
        "stageVisualChanged",
        "phaseVisualContexts",
        "phase_visual_contexts",
        "reason",
        "boundaryReason",
        "hook",
        "endingQuestion",
        "summary",
        "storyUnitSummary",
        "workflowBenefit",
        "riskNotes",
        "excerpt",
        "createdAt",
    )
    proposal: dict[str, Any] = {}
    for key in keys:
        if key not in value:
            continue
        item = value.get(key)
        if item is None:
            continue
        if isinstance(item, str):
            proposal[key] = _compact_text(item, text_limits.get(key, 160))
        elif isinstance(item, list):
            if key == "riskNotes":
                proposal[key] = [_compact_text(str(row or ""), 120) for row in item[:4] if str(row or "").strip()]
            else:
                proposal[key] = copy.deepcopy(item[:8])
        else:
            proposal[key] = copy.deepcopy(item)
    candidates = value.get("candidates") if isinstance(value.get("candidates"), list) else []
    if candidates:
        proposal["candidateCount"] = len(candidates)
        proposal["candidatePreview"] = [
            {
                "endOffset": item.get("endOffset"),
                "actualUnits": item.get("actualUnits"),
                "reason": _compact_text(str(item.get("reason") or ""), 120),
            }
            for item in candidates[:3]
            if isinstance(item, dict)
        ]
    return proposal


def _agent_compact_commit_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = (
        "proposalId",
        "proposal_id",
        "sourceId",
        "episodeId",
        "rangeId",
        "startOffset",
        "start_offset",
        "endOffset",
        "end_offset",
        "recommendedEndOffset",
        "absoluteStart",
        "absoluteEnd",
        "targetUnits",
        "target_units",
        "assetTypes",
        "reason",
        "summary",
        "boundaryReason",
        "boundaryToleranceUnits",
        "planningLookaheadUnits",
        "planningWindowEnd",
        "planningMethod",
        "boundaryEndText",
        "storyUnitSummary",
        "phaseVisualContext",
        "phase_visual_context",
        "stageVisualChanged",
        "phaseVisualContexts",
        "phase_visual_contexts",
        "workflowBenefit",
        "riskNotes",
        "expectedRevision",
        "expected_revision",
        "baseHash",
        "base_hash",
        "committedBy",
        "committed_by",
        "title",
        "episodeTitle",
        "episode_title",
    )
    payload: dict[str, Any] = {}
    for key in keys:
        if key not in value:
            continue
        item = value.get(key)
        if item is None:
            continue
        if isinstance(item, str):
            if key == "boundaryEndText":
                payload[key] = item.strip()
            else:
                payload[key] = _compact_text(item, 260 if key in {"reason", "summary", "title"} else 160)
        elif isinstance(item, list):
            payload[key] = copy.deepcopy(item[:8])
        else:
            payload[key] = copy.deepcopy(item)
    proposal = _agent_compact_proposal(value.get("proposal"))
    if proposal:
        payload["proposal"] = proposal
    return payload


def _agent_json_object_from_text(value: Any) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _agent_episode_number(episode_id: str) -> int:
    match = re.search(r"(\d+)", str(episode_id or ""))
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0
