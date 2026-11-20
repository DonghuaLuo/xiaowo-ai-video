# -*- coding: utf-8 -*-
"""Resolve small, evidence-backed project context for production workers."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .agent_sessions import _project_dir
from .source_coverage import _source_ref_bounds
from .source_text_store import _episode_source_rows, get_episode_source_text
from .store_core import _read_json


CONTEXT_ENVELOPE_SCHEMA_VERSION = 1
PLOT_PREVIOUS_TAIL_CHARS = 1800
_ASSET_TYPES = ("characters", "creatures", "scenes", "props")
_CARRYOVER_ASSET_LIMITS = {"characters": 12, "creatures": 10, "scenes": 8, "props": 12}


def _hash_text(value: Any) -> str:
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _compact_text(value: Any, limit: int) -> str:
    """Lossy preview/excerpt helper.

    Use only for summaries, diagnostics, or bounded context excerpts. Do not use
    for canonical source text, generated prompts, provider API payloads, or any
    generation-affecting value that must remain complete.
    """
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _compact_json(value: Any, limit: int) -> str:
    if value in (None, "", [], {}):
        return ""
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        text = str(value)
    return _compact_text(text, limit)


def _source_ref_summary(value: Any) -> dict[str, Any]:
    ref = value if isinstance(value, dict) else {}
    result: dict[str, Any] = {}
    for key in (
        "sourceId",
        "episodeId",
        "absoluteStart",
        "absoluteEnd",
        "charCount",
        "title",
        "episodeTitle",
    ):
        if ref.get(key) not in (None, ""):
            result[key] = copy.deepcopy(ref.get(key))
    return result


def _previous_episode_row(project_id: str, episode_id: str, current_source_ref: dict[str, Any]) -> dict[str, Any]:
    try:
        coverage = _read_json(_project_dir(project_id) / "source_coverage.json", {})
        rows = _episode_source_rows(project_id, coverage)
    except Exception:  # noqa: BLE001 - context resolution must degrade to current facts
        return {}
    source_id = str(current_source_ref.get("sourceId") or current_source_ref.get("source_id") or "").strip()
    current_start, _current_end = _source_ref_bounds(current_source_ref)
    if source_id and current_start is not None:
        candidates = []
        for row in rows:
            if str(row.get("episodeId") or "") == episode_id:
                continue
            if str(row.get("sourceId") or "").strip() != source_id:
                continue
            try:
                row_end = int(row.get("absoluteEnd") or 0)
            except (TypeError, ValueError):
                continue
            if 0 < row_end <= current_start:
                candidates.append(row)
        if candidates:
            return copy.deepcopy(max(candidates, key=lambda row: int(row.get("absoluteEnd") or 0)))
        return {}

    for index, row in enumerate(rows):
        if str(row.get("episodeId") or "") != episode_id or index <= 0:
            continue
        previous = rows[index - 1]
        previous_source_id = str(previous.get("sourceId") or "").strip()
        current_row_source_id = str(row.get("sourceId") or "").strip()
        if previous_source_id and current_row_source_id and previous_source_id != current_row_source_id:
            return {}
        return copy.deepcopy(previous)
    return {}


def _previous_episode_tail(project_id: str, row: dict[str, Any], limit: int) -> dict[str, Any]:
    episode_id = str(row.get("episodeId") or "").strip()
    if not episode_id:
        return {}
    try:
        source = get_episode_source_text(project_id, episode_id)
    except Exception:  # noqa: BLE001 - an unavailable neighbor must not block the target episode
        return {}
    if source.get("available") is False:
        return {}
    text = str(source.get("text") or "")
    if not text:
        return {}
    tail = text[-max(1, limit) :]
    source_ref = source.get("sourceRef") if isinstance(source.get("sourceRef"), dict) else {}
    ref_start, ref_end = _source_ref_bounds(source_ref)
    if ref_start is None:
        try:
            ref_start = int(row.get("absoluteStart") or 0)
        except (TypeError, ValueError):
            ref_start = 0
    absolute_start = ref_start + max(0, len(text) - len(tail))
    if ref_end is None:
        ref_end = absolute_start + len(tail)
    evidence_ref = {
        "sourceId": str(source_ref.get("sourceId") or row.get("sourceId") or ""),
        "episodeId": episode_id,
        "absoluteStart": absolute_start,
        "absoluteEnd": ref_end,
    }
    return {
        "episodeId": episode_id,
        "title": str(source.get("title") or row.get("title") or episode_id),
        "sourceRef": _source_ref_summary(source_ref or row),
        "evidenceRef": evidence_ref,
        "text": tail,
        "contentHash": _hash_text(text),
    }


def _last_continuity_state(project_id: str, episode_id: str) -> dict[str, Any]:
    if not episode_id:
        return {}
    path = _project_dir(project_id) / "episodes" / episode_id / "work_chain_plan.json"
    if not path.is_file():
        return {}
    shot_plan = _read_json(path, {})
    if not isinstance(shot_plan, dict):
        return {}
    shots = [row for row in shot_plan.get("shots") or [] if isinstance(row, dict)]
    if shots:
        row = shots[-1]
        state = {
            "shotId": str(row.get("id") or ""),
            "segmentId": str(row.get("segmentId") or row.get("segment_id") or ""),
            "assetRefs": copy.deepcopy(row.get("assetRefs") or row.get("asset_refs") or {}),
            "endState": copy.deepcopy(row.get("endState") or row.get("end_state") or {}),
            "continuityAnchor": _compact_text(
                row.get("continuityAnchor")
                or row.get("continuity")
                or row.get("stateContinuity")
                or row.get("visualContinuity"),
                280,
            ),
        }
        return {key: value for key, value in state.items() if value not in (None, "", [], {})}

    segments = [row for row in shot_plan.get("segments") or [] if isinstance(row, dict)]
    if not segments:
        return {}
    row = segments[-1]
    state = {
        "segmentId": str(row.get("id") or row.get("segmentId") or row.get("segment_id") or ""),
        "title": _compact_text(row.get("title") or row.get("name"), 100),
        "storyTail": _compact_text(
            row.get("cinematicStoryText")
            or row.get("cinematic_story_text")
            or row.get("sourceFactText")
            or row.get("source_fact_text"),
            360,
        ),
        "assetRefs": copy.deepcopy(
            row.get("assetRefs") or row.get("asset_refs") or row.get("assetHints") or row.get("asset_hints") or {}
        ),
        "endState": copy.deepcopy(row.get("endState") or row.get("end_state") or {}),
    }
    return {key: value for key, value in state.items() if value not in (None, "", [], {})}


def resolve_work_context(
    project_id: str,
    work_type: str,
    *,
    episode_id: str,
    current_source: dict[str, Any],
    production_memory: dict[str, Any] | None = None,
    previous_tail_chars: int = PLOT_PREVIOUS_TAIL_CHARS,
) -> dict[str, Any]:
    """Build a bounded context envelope for task agents and controller review."""

    source_ref = current_source.get("sourceRef") if isinstance(current_source.get("sourceRef"), dict) else {}
    current_text = str(current_source.get("text") or "")
    previous_row = _previous_episode_row(project_id, episode_id, source_ref)
    previous_tail = _previous_episode_tail(project_id, previous_row, previous_tail_chars)
    previous_episode_id = str(previous_tail.get("episodeId") or previous_row.get("episodeId") or "")
    previous_end_state = _last_continuity_state(project_id, previous_episode_id)

    evidence: list[dict[str, Any]] = []
    if previous_tail.get("text"):
        evidence.append(
            {
                "kind": "previous_episode_tail",
                "sourceRef": copy.deepcopy(previous_tail.get("evidenceRef") or {}),
                "text": previous_tail["text"],
                "reason": "用于判断当前集开头未重复交代的地点、在场对象和延续道具；不得把上一集事件拆入当前集。",
            }
        )

    continuity: dict[str, Any] = {
        "inheritanceRule": "当前原文未明确改变时，才可继承上一集结束状态；当前原文明示永远覆盖继承信息。",
    }
    if previous_episode_id:
        continuity["previousEpisode"] = {
            "episodeId": previous_episode_id,
            "title": str(previous_tail.get("title") or previous_row.get("title") or previous_episode_id),
            "sourceRef": _source_ref_summary(previous_tail.get("sourceRef") or previous_row.get("sourceRef") or previous_row),
        }
    if previous_end_state:
        continuity["previousEndState"] = previous_end_state
    memory_summary = _compact_json(production_memory or {}, 900)
    if memory_summary:
        continuity["providedProductionMemory"] = memory_summary

    consulted = ["current_episode_source"]
    if previous_tail.get("text"):
        consulted.append("previous_episode_tail")
    if previous_end_state:
        consulted.append("previous_episode_work_chain_plan_end_state")
    if memory_summary:
        consulted.append("provided_production_memory")

    return {
        "schemaVersion": CONTEXT_ENVELOPE_SCHEMA_VERSION,
        "workType": str(work_type or ""),
        "target": {
            "episodeId": episode_id,
            "sourceRef": _source_ref_summary(source_ref),
        },
        "factPriority": [
            "current_episode_explicit_text",
            "confirmed_task_data",
            "adjacent_continuity_evidence",
            "story_core_theme_context",
            "model_inference",
        ],
        "continuity": continuity,
        "evidence": evidence,
        "gaps": [],
        "budget": {
            "retrievalRounds": 1,
            "previousTailMaxChars": max(1, int(previous_tail_chars)),
            "evidenceChars": sum(len(str(item.get("text") or "")) for item in evidence),
        },
        "provenance": {
            "consultedResources": consulted,
            "currentSourceHash": _hash_text(current_text),
            "previousSourceHash": str(previous_tail.get("contentHash") or ""),
        },
    }


def _asset_tokens(row: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key in ("id", "assetId", "asset_id", "name", "title"):
        token = str(row.get(key) or "").strip()
        if token and token.casefold() not in {item.casefold() for item in result}:
            result.append(token)
    return result


def _asset_key(row: dict[str, Any]) -> str:
    tokens = _asset_tokens(row)
    return "|".join(token.casefold() for token in tokens) or _compact_json(row, 200).casefold()


def _asset_matches_cues(row: dict[str, Any], cues: str) -> bool:
    folded = cues.casefold()
    return any(token.casefold() in folded for token in _asset_tokens(row))


def merge_asset_candidates(
    current_assets: dict[str, list[dict[str, Any]]] | None,
    carryover_assets: dict[str, list[dict[str, Any]]] | None,
    *,
    current_text: str,
    context_envelope: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Prefer current assets and add only bounded, evidence-relevant neighbor assets."""

    current_assets = current_assets if isinstance(current_assets, dict) else {}
    carryover_assets = carryover_assets if isinstance(carryover_assets, dict) else {}
    evidence_text = "\n".join(
        str(item.get("text") or "")
        for item in context_envelope.get("evidence") or []
        if isinstance(item, dict)
    )
    continuity_text = _compact_json(context_envelope.get("continuity") or {}, 2400)
    current_cues = str(current_text or "")
    carryover_cues = "\n".join((current_cues, evidence_text, continuity_text))

    merged: dict[str, list[dict[str, Any]]] = {}
    trace: dict[str, Any] = {}
    unresolved_gaps: list[dict[str, str]] = []
    for asset_type in _ASSET_TYPES:
        current_rows = [copy.deepcopy(row) for row in current_assets.get(asset_type) or [] if isinstance(row, dict)]
        carryover_rows = [copy.deepcopy(row) for row in carryover_assets.get(asset_type) or [] if isinstance(row, dict)]
        selected_current = current_rows
        seen = {_asset_key(row) for row in selected_current}

        current_matches = [row for row in current_rows if _asset_matches_cues(row, current_cues)]
        current_carryover_matches = (
            [row for row in carryover_rows if _asset_matches_cues(row, current_cues)]
            if asset_type == "scenes"
            else []
        )
        has_explicit_current_scene = asset_type == "scenes" and bool(current_matches or current_carryover_matches)
        if has_explicit_current_scene:
            matched_carryover = [] if current_matches else current_carryover_matches
        else:
            matched_carryover = [row for row in carryover_rows if _asset_matches_cues(row, carryover_cues)]
        if (
            asset_type == "scenes"
            and not has_explicit_current_scene
            and not matched_carryover
            and carryover_rows
            and (evidence_text or continuity_text)
        ):
            unresolved_gaps.append(
                {
                    "field": "sceneAsset",
                    "reason": "相邻集证据不足以确认当前场景资产，未扩大候选范围。",
                    "handling": "由任务智能体结合当前原文、相邻连续性资料和相关资产信息核实具体场景。",
                    "suggestedReadTools": [
                        "get_project_snapshot",
                        "get_source_coverage",
                        "read_source_window",
                    ],
                }
            )
        selected_carryover: list[dict[str, Any]] = []
        for row in matched_carryover:
            key = _asset_key(row)
            if key in seen:
                continue
            item = copy.deepcopy(row)
            item["contextScope"] = "previous_episode_carryover"
            selected_carryover.append(item)
            seen.add(key)
            if len(selected_carryover) >= _CARRYOVER_ASSET_LIMITS[asset_type]:
                break

        merged[asset_type] = selected_current + selected_carryover
        trace[asset_type] = {
            "currentCount": len(selected_current),
            "carryover": [
                {key: row.get(key) for key in ("id", "name") if row.get(key)} for row in selected_carryover
            ],
        }

    next_envelope = copy.deepcopy(context_envelope)
    next_envelope["assetCandidates"] = trace
    if unresolved_gaps:
        next_envelope["gaps"] = [
            copy.deepcopy(row)
            for row in (next_envelope.get("gaps") or [])
            if isinstance(row, dict)
        ] + unresolved_gaps
    return merged, next_envelope


def context_provenance(context_envelope: dict[str, Any] | None) -> dict[str, Any]:
    """Remove retrieved text while preserving enough data to audit a proposal."""

    envelope = context_envelope if isinstance(context_envelope, dict) else {}
    evidence = []
    for item in envelope.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        evidence.append(
            {
                key: copy.deepcopy(item.get(key))
                for key in ("kind", "sourceRef", "reason")
                if item.get(key) not in (None, "", [], {})
            }
        )
    return {
        key: copy.deepcopy(value)
        for key, value in {
            "schemaVersion": envelope.get("schemaVersion"),
            "workType": envelope.get("workType"),
            "target": envelope.get("target"),
            "continuitySource": (envelope.get("continuity") or {}).get("previousEpisode")
            if isinstance(envelope.get("continuity"), dict)
            else None,
            "evidence": evidence,
            "assetCandidates": envelope.get("assetCandidates"),
            "provenance": envelope.get("provenance"),
        }.items()
        if value not in (None, "", [], {})
    }


__all__ = (
    "CONTEXT_ENVELOPE_SCHEMA_VERSION",
    "PLOT_PREVIOUS_TAIL_CHARS",
    "context_provenance",
    "merge_asset_candidates",
    "resolve_work_context",
)
