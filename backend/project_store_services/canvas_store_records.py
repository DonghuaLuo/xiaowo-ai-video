# -*- coding: utf-8 -*-
"""画布记录的编码、摘要、身份、版本引用和响应数据契约。"""
from __future__ import annotations
from .canvas_ownership import VIDEO_TASK_NODE_TYPES

from dataclasses import dataclass, field

import copy
import hashlib
import json
import re
import sqlite3
from .store_core import (
    _now,
)
from typing import (
    Any,
)


_CARD_ID_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


_CANVAS_DOMAIN_EXTRA_KEYS = ("canvasKind", "autoWorkflowInitialized")


_CANVAS_VERSION_REFERENCE_DATA_KEYS = (
    "activeVersionId",
    "winnerVersionId",
    "sourceVersionId",
    "mediaVersionId",
    "assetVersionId",
    "activeMediaVersionId",
)


_CANVAS_VERSION_SELECTION_DATA_KEYS = ("selectionReason", "selectedAt")


_SUMMARY_DATA_KEYS = {
    "sourceMode",
    "title",
    "episodeTitle",
    "status",
    "summary",
    "eyebrow",
    "routeId",
    "segmentId",
    "workChainId",
    "strategy",
    "planningStrategy",
    "activeVersionId",
    "winnerVersionId",
    "sourceVersionId",
    "mediaVersionId",
    "assetVersionId",
    "activeMediaVersionId",
    "resultOfNodeId",
    "sourceNodeId",
    "resultRole",
    "cardState",
    "inputLinks",
    "referenceUsage",
    "assetId",
    "asset_id",
    "assetType",
    "asset_type",
    # Empty asset cards need this identity for open-time and event-driven binding.
    "rootAssetId",
    "rootAssetType",
    "rootAssetProjectId",
    "assetName",
    "asset_name",
    "displayName",
    "display_name",
    "sourceType",
    "source_type",
    "sourceId",
    "source_id",
    "source_node_id",
    "sourceMediaId",
    "source_media_id",
    "visibilityScope",
    "visibility_scope",
    "assetScope",
    "asset_scope",
    "stateTag",
    "state_tag",
    "mediaId",
    "media_id",
    "quality",
    "media",
    "storage",
    "preview",
    "progress",
    "cinematicStoryText",
    "cinematic_story_text",
    "sourceFactText",
    "source_fact_text",
    "sourcePreview",
    "source_preview",
    "visualBeats",
    "visual_beats",
    "storyboardTemplate",
    "storyboard_template",
    "storyboardTemplateLabel",
    "storyboard_template_label",
    "template",
    "templateLabel",
    "durationSeconds",
    "maxDurationSeconds",
    "max_duration_seconds",
    "directorPlan",
    "director_plan",
    "storyboardAllocation",
    "shotGroupId",
    "shotGroupOrder",
    "shotNos",
    "directorRuleId",
    "directorRuleSelectionMode",
    "rhythmMultiplier",
    "director_rule_id",
    "directorRuleOptions",
    "director_rule_options",
    "directorGeneratedAt",
    "director_generated_at",
    "directorPlanRevision",
    "director_plan_revision",
    "shotCount",
    "shot_count",
    "shotTimingPlan",
    "shot_timing_plan",
    "scriptState",
    "script_state",
    "assetState",
    "asset_state",
    "scriptTemplateId",
    "scriptGeneratedAt",
    "script_generated_at",
    "scriptManualEdited",
    "script_manual_edited",
    "userScriptSupplement",
    "user_script_supplement",
}


_SUMMARY_TEXT_LIMIT = 800


_SUMMARY_PROMPT_TEXT_LIMIT = 1800


_SUMMARY_SCRIPT_TEXT_LIMIT = 2400


_SUMMARY_LIST_LIMIT = 16


_SUMMARY_INLINE_MEDIA_KEYS = {
    "base64",
    "bytes",
    "dataurl",
    "datauri",
    "imagedata",
    "imagebytes",
    "imagebase64",
    "imagedataurl",
    "inputimagedataurl",
    "outputimagedataurl",
    "pngdataurl",
    "storedpngdataurl",
    "videodata",
    "videobytes",
    "videobase64",
}


_SUMMARY_MEDIA_REF_KEYS = {
    "id",
    "mediaId",
    "media_id",
    "kind",
    "mimeType",
    "mime_type",
    "originalName",
    "original_name",
    "name",
    "width",
    "height",
    "size",
    "duration",
    "durationSeconds",
    "aspectRatio",
    "aspect_ratio",
    "path",
    "filePath",
    "file_path",
    "file",
    "pngFile",
    "png_file",
    "relativePath",
    "relative_path",
    "url",
    "preview",
}


_SUMMARY_VIDEO_TASK_CARD_KEYS = {
    "source",
    "contentHash",
    "content_hash",
    "generatedAt",
    "generated_at",
    "durationSeconds",
    "maxDurationSeconds",
    "max_duration_seconds",
    "resolution",
    "size",
    "aspectRatio",
    "aspect_ratio",
    "modelId",
    "model_id",
    "providerId",
    "provider_id",
    "strategy",
}


_SUMMARY_STORYBOARD_TASK_CARD_KEYS = {
    "title",
    "state",
    "scriptState",
    "script_state",
    "assetState",
    "asset_state",
    "cinematicStoryText",
    "cinematic_story_text",
    "sourceFactText",
    "source_fact_text",
    "sourcePreview",
    "source_preview",
    "visualBeats",
    "visual_beats",
    "storyboardTemplate",
    "storyboard_template",
    "storyboardTemplateLabel",
    "storyboard_template_label",
    "template",
    "templateLabel",
    "durationSeconds",
    "shotCount",
    "shot_count",
    "shotTimingPlan",
    "shot_timing_plan",
    "scriptTemplateId",
    "scriptManualEdited",
    "script_manual_edited",
    "userScriptSupplement",
    "user_script_supplement",
}


_SUMMARY_DIRECTOR_TASK_CARD_KEYS = {
    "title",
    "state",
    "directorPlan",
    "director_plan",
    "directorRuleId",
    "director_rule_id",
    "storyboardTemplate",
    "storyboard_template",
    "storyboardTemplateLabel",
    "storyboard_template_label",
    "template",
    "templateLabel",
    "durationSeconds",
    "shotCount",
    "shot_count",
    "shotTimingPlan",
    "shot_timing_plan",
    "cinematicStoryText",
    "cinematic_story_text",
    "sourceFactText",
    "source_fact_text",
}


_SUMMARY_STORYBOARD_PROMPT_KEYS = {
    "cinematicStoryText",
    "cinematic_story_text",
    "sourceFactText",
    "source_fact_text",
    "sourcePreview",
    "source_preview",
    "visualBeats",
    "visual_beats",
    "storyboardTemplate",
    "storyboard_template",
    "storyboardTemplateLabel",
    "storyboard_template_label",
    "durationSeconds",
}


_SUMMARY_DIRECTOR_PROMPT_KEYS = {
    "directorPlan",
    "director_plan",
    "directorRuleId",
    "director_rule_id",
    "storyboardTemplate",
    "storyboard_template",
    "storyboardTemplateLabel",
    "storyboard_template_label",
    "durationSeconds",
}


_SUMMARY_SCRIPT_TEXT_TOKENS = {
    "cinematicstorytext",
    "directorplan",
    "sourcetext",
    "sourcefacttext",
    "sourcepreview",
    "userscriptsupplement",
    "visibleaction",
    "stageaction",
    "performance",
    "dialogue",
    "text",
    "content",
    "description",
    "summary",
    "reason",
    "intent",
    "narrativepurpose",
}


_SUMMARY_MODEL_PREFLIGHT_KEYS = {
    "success",
    "checkedAt",
    "checked_at",
    "mediaType",
    "media_type",
    "strategy",
    "modelId",
    "model_id",
    "warnings",
    "blockingIssues",
    "blocking_issues",
    "requiredSlots",
    "required_slots",
}


_SUMMARY_MODEL_PREFLIGHT_CONFIG_KEYS = {
    "mediaType",
    "media_type",
    "modelId",
    "model_id",
    "resolution",
    "outputFormat",
    "output_format",
    "referenceMode",
    "reference_mode",
    "purpose",
    "size",
    "aspectRatio",
    "aspect_ratio",
    "resolvedReferenceImageCount",
    "resolved_reference_image_count",
    "promptSourceNodeId",
    "prompt_source_node_id",
}


def _safe_part(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    text = _CARD_ID_PATTERN.sub("_", text).strip("._-")
    return text or fallback


def _summary_key_token(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key or "").lower())


def _summary_is_inline_media_string(value: str) -> bool:
    return value.lstrip().lower().startswith("data:")


def _summary_looks_like_large_base64(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    if len(compact) < 1024 or len(compact) % 4 != 0:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact))


def _summary_text(value: Any, limit: int = _SUMMARY_TEXT_LIMIT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}...（已截断）"


def _summary_media_ref(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    media: dict[str, Any] = {}
    for key in _SUMMARY_MEDIA_REF_KEYS:
        if key not in value:
            continue
        item = value.get(key)
        if item in (None, ""):
            continue
        if isinstance(item, str) and _summary_is_inline_media_string(item):
            continue
        media[key] = copy.deepcopy(item)
    return media or None


def _summary_model_preflight(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    preflight: dict[str, Any] = {}
    for key in _SUMMARY_MODEL_PREFLIGHT_KEYS:
        if key in value:
            compact = _summary_value(key, value.get(key))
            if compact is not None:
                preflight[key] = compact
    resolved_config = value.get("resolvedConfig") or value.get("resolved_config")
    if isinstance(resolved_config, dict):
        config_summary: dict[str, Any] = {}
        for key in _SUMMARY_MODEL_PREFLIGHT_CONFIG_KEYS:
            if key in resolved_config:
                compact = _summary_value(key, resolved_config.get(key))
                if compact is not None:
                    config_summary[key] = compact
        if config_summary:
            preflight["resolvedConfig"] = config_summary
    return preflight or None


def _summary_quality(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    quality: dict[str, Any] = {}
    for key, item in value.items():
        token = _summary_key_token(key)
        if token == "modelpreflight":
            compact = _summary_model_preflight(item)
        elif token in {"inputsnapshot", "slotschema", "modelcapabilities", "resolvedconfig"}:
            continue
        else:
            compact = _summary_value(key, item)
        if compact is not None:
            quality[key] = compact
    return quality or None


def _summary_value(key: Any, value: Any) -> Any:
    token = _summary_key_token(key)
    if token in _SUMMARY_INLINE_MEDIA_KEYS:
        return None
    if isinstance(value, dict):
        if token == "quality":
            return _summary_quality(value)
        if token in {"media", "storage"}:
            return _summary_media_ref(value)
        cleaned: dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_token = _summary_key_token(child_key)
            if child_token in _SUMMARY_INLINE_MEDIA_KEYS:
                continue
            if child_token == "preview" and isinstance(child_value, str) and _summary_is_inline_media_string(child_value):
                continue
            if child_token == "data" and isinstance(child_value, str):
                if _summary_is_inline_media_string(child_value) or _summary_looks_like_large_base64(child_value):
                    continue
            compact = _summary_value(child_key, child_value)
            if compact is not None:
                cleaned[child_key] = compact
        return cleaned
    if isinstance(value, list):
        return [
            compact
            for compact in (_summary_value(key, item) for item in value[:_SUMMARY_LIST_LIMIT])
            if compact is not None
        ]
    if isinstance(value, str):
        if _summary_is_inline_media_string(value):
            return None
        if token == "data" and _summary_looks_like_large_base64(value):
            return None
        if token in _SUMMARY_SCRIPT_TEXT_TOKENS:
            return _summary_text(value, _SUMMARY_SCRIPT_TEXT_LIMIT)
        if "prompt" in token or "instruction" in token:
            return _summary_text(value, _SUMMARY_PROMPT_TEXT_LIMIT)
        if token in {"summary", "title", "message", "notice", "error", "failurereason"}:
            return _summary_text(value, _SUMMARY_TEXT_LIMIT)
    return copy.deepcopy(value)


def _summary_video_task_card(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    card: dict[str, Any] = {}
    for key in _SUMMARY_VIDEO_TASK_CARD_KEYS:
        if key in value:
            compact = _summary_value(key, value.get(key))
            if compact is not None:
                card[key] = compact
    return card or None


def _summary_storyboard_task_card(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    card: dict[str, Any] = {}
    for key in _SUMMARY_STORYBOARD_TASK_CARD_KEYS:
        if key in value:
            compact = _summary_value(key, value.get(key))
            if compact is not None:
                card[key] = compact
    return card or None


def _summary_director_task_card(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    card: dict[str, Any] = {}
    for key in _SUMMARY_DIRECTOR_TASK_CARD_KEYS:
        if key in value:
            compact = _summary_value(key, value.get(key))
            if compact is not None:
                card[key] = compact
    return card or None


def _summary_storyboard_prompt(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    prompt: dict[str, Any] = {}
    for key in _SUMMARY_STORYBOARD_PROMPT_KEYS:
        if key in value:
            compact = _summary_value(key, value.get(key))
            if compact is not None:
                prompt[key] = compact
    return prompt or None


def _summary_director_prompt(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    prompt: dict[str, Any] = {}
    for key in _SUMMARY_DIRECTOR_PROMPT_KEYS:
        if key in value:
            compact = _summary_value(key, value.get(key))
            if compact is not None:
                prompt[key] = compact
    return prompt or None


def _summary_prompt(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key in ("videoPrompt", "video_prompt", "prompt", "summary", "title"):
            if key in value:
                compact = _summary_value(key, value.get(key))
                if compact is not None:
                    cleaned[key] = compact
        return cleaned
    return _summary_value("prompt", value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_signature(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_CANVAS_SIGNATURE_OMIT_KEYS = {
    "status",
    "progress",
    "message",
    "notice",
    "createdat",
    "startedat",
    "updatedat",
    "completedat",
    "failedat",
    "blockedat",
    "cancelledat",
    "position",
    "viewport",
}


def _canvas_signature_key_token(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key or "").strip().lower())


def _canvas_signature_large_string(value: str) -> dict[str, Any]:
    return {
        "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "chars": len(value),
    }


def _canvas_signature_sanitize(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 12:
        return str(value)
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for child_key in sorted(value.keys(), key=lambda item: str(item)):
            token = _canvas_signature_key_token(child_key)
            if token in _CANVAS_SIGNATURE_OMIT_KEYS:
                continue
            sanitized[str(child_key)] = _canvas_signature_sanitize(
                value.get(child_key),
                key=str(child_key),
                depth=depth + 1,
            )
        return sanitized
    if isinstance(value, (list, tuple)):
        return [
            _canvas_signature_sanitize(item, key=key, depth=depth + 1)
            for item in value
        ]
    if isinstance(value, set):
        return [
            _canvas_signature_sanitize(item, key=key, depth=depth + 1)
            for item in sorted(value, key=lambda item: str(item))
        ]
    if isinstance(value, str):
        token = _canvas_signature_key_token(key)
        if (
            len(value) > 4096
            or _summary_is_inline_media_string(value)
            or (token == "data" and _summary_looks_like_large_base64(value))
        ):
            return _canvas_signature_large_string(value)
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _canvas_signature_hash_from_json(raw_json: Any) -> str:
    raw_text = raw_json if isinstance(raw_json, str) else ""
    if not raw_text:
        return hashlib.sha256(b"").hexdigest()
    try:
        value = json.loads(raw_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        value = raw_text
    normalized = _json_signature(_canvas_signature_sanitize(value))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str) or not value:
        return copy.deepcopy(default)
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return copy.deepcopy(default)


def _empty_canvas_document_payload(episode_id: str, reason: str = "missing_canvas") -> dict[str, Any]:
    return {
        "episodeId": episode_id,
        "schemaVersion": 4,
        "revision": 0,
        "currentRevision": 0,
        "viewport": {"x": 0, "y": 0, "zoom": 0.82},
        "state": {
            "kind": "empty",
            "reason": reason,
            "sourceReady": False,
            "workChainPlanReady": False,
            "workflowChainReady": False,
            "nextAction": "build_workflow_chain",
        },
        "updatedAt": None,
    }


def _workflow_document_extras(workflow: dict[str, Any]) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    if not isinstance(workflow, dict):
        return extras
    if "productionStatus" in workflow and isinstance(workflow.get("productionStatus"), dict):
        extras["productionStatus"] = copy.deepcopy(workflow.get("productionStatus") or {})
    if "build" in workflow and isinstance(workflow.get("build"), dict):
        extras["build"] = copy.deepcopy(workflow.get("build") or {})
    for key in _CANVAS_DOMAIN_EXTRA_KEYS:
        if key in workflow:
            extras[key] = copy.deepcopy(workflow[key])
    return extras


def _canvas_document_extras_payload(document: sqlite3.Row | None) -> dict[str, Any]:
    if document is None or "extras_json" not in document.keys():
        return {}
    extras = _json_loads(document["extras_json"], {})
    if not isinstance(extras, dict):
        return {}
    payload: dict[str, Any] = {}
    if isinstance(extras.get("productionStatus"), dict):
        payload["productionStatus"] = copy.deepcopy(extras.get("productionStatus") or {})
    if type(extras.get("productionStatusRevision")) is int:
        payload["productionStatusRevision"] = extras["productionStatusRevision"]
    if isinstance(extras.get("build"), dict):
        payload["build"] = copy.deepcopy(extras.get("build") or {})
    for key in _CANVAS_DOMAIN_EXTRA_KEYS:
        if key in extras:
            payload[key] = copy.deepcopy(extras[key])
    return payload


def _merge_canvas_document_extras(
    current: dict[str, Any],
    patch: dict[str, Any],
    *,
    replace: bool = False,
) -> dict[str, Any]:
    next_extras = {} if replace else copy.deepcopy(current if isinstance(current, dict) else {})
    for key in ("productionStatus", "build", *_CANVAS_DOMAIN_EXTRA_KEYS):
        if key not in patch:
            continue
        value = patch.get(key)
        if key in _CANVAS_DOMAIN_EXTRA_KEYS:
            next_extras[key] = copy.deepcopy(value)
        elif value is None:
            next_extras.pop(key, None)
        elif key in {"productionStatus", "build"} and isinstance(value, dict):
            next_extras[key] = copy.deepcopy(value)
    return next_extras


def _canvas_document_payload(
    document: sqlite3.Row | None,
    episode_id: str,
    *,
    has_nodes: bool | None = None,
) -> dict[str, Any]:
    if document is None:
        return _empty_canvas_document_payload(episode_id)
    revision = int(document["revision"] or 0)
    state = _json_loads(document["state_json"], {})
    state = copy.deepcopy(state) if isinstance(state, dict) else {}
    has_canvas_records = bool(has_nodes)
    if not str(state.get("kind") or "").strip():
        state["kind"] = "ready" if has_canvas_records else "empty"
    if not str(state.get("reason") or "").strip():
        state["reason"] = "loaded"
    if "sourceReady" not in state:
        state["sourceReady"] = has_canvas_records
    if "workChainPlanReady" not in state:
        state["workChainPlanReady"] = False
    if "workflowChainReady" not in state:
        state["workflowChainReady"] = has_canvas_records
    if not str(state.get("nextAction") or "").strip():
        state["nextAction"] = "run_workflow" if has_canvas_records else "build_workflow_chain"
    payload = {
        "episodeId": episode_id,
        "schemaVersion": int(document["schema_version"] or 4),
        "revision": revision,
        "currentRevision": revision,
        "viewport": _json_loads(document["viewport_json"], {"x": 0, "y": 0, "zoom": 0.82}),
        "state": state,
        "updatedAt": document["updated_at"],
    }
    payload.update(_canvas_document_extras_payload(document))
    return payload


def _record_node_id(node: dict[str, Any], fallback: str) -> str:
    return str(node.get("id") or "").strip() or fallback


def _record_edge_id(edge: dict[str, Any], index: int) -> str:
    edge_id = str(edge.get("id") or "").strip()
    if edge_id:
        return edge_id
    edge_id = f"edge-{index + 1}"
    edge["id"] = edge_id
    return edge_id


def _record_route_id(route: dict[str, Any], index: int) -> str:
    route_id = str(route.get("id") or route.get("routeId") or route.get("route_id") or "").strip()
    if route_id:
        route["id"] = route_id
        return route_id
    route_id = f"route-{index + 1}"
    route["id"] = route_id
    return route_id


def _record_work_chain_id(work_chain: dict[str, Any], index: int) -> str:
    work_chain_id = str(
        work_chain.get("id") or work_chain.get("workChainId") or work_chain.get("work_chain_id") or ""
    ).strip()
    if work_chain_id:
        work_chain["id"] = work_chain_id
        return work_chain_id
    work_chain_id = f"work-chain-{index + 1}"
    work_chain["id"] = work_chain_id
    return work_chain_id


def _record_ref(record_type: str, record_id: str, **extra: Any) -> dict[str, Any]:
    row = {"type": record_type, "id": str(record_id or "")}
    for key, value in extra.items():
        if value is not None and value != "":
            row[key] = copy.deepcopy(value)
    return row


_CANVAS_CHANGED_RESOURCE_ALIASES = {
    "workflow": "",
    "workflow_card": "canvas_node",
    "workflow_cards": "canvas_node",
    "workflow_node": "canvas_node",
    "workflow_nodes": "canvas_node",
    "workflow_node_inline": "canvas_node",
    "workflow_node_layout": "canvas_node",
    "workflow_media": "canvas_node",
    "canvas_card": "canvas_node",
    "canvas_cards": "canvas_node",
    "workflow_edge": "canvas_edge",
    "workflow_edges": "canvas_edge",
    "workflow_route": "canvas_route",
    "workflow_routes": "canvas_route",
    "workflow_work_chain": "canvas_work_chain",
    "workflow_work_chains": "canvas_work_chain",
    "workflow_task": "canvas_task",
    "workflow_tasks": "canvas_task",
    "task": "canvas_task",
    "tasks": "canvas_task",
    "workflow_version": "canvas_version",
    "workflow_versions": "canvas_version",
    "version": "canvas_version",
    "versions": "canvas_version",
    "workflow_asset_refs": "canvas_projection",
}


def normalize_canvas_changed_resource_name(value: Any) -> str:
    resource = str(value or "").strip()
    return _CANVAS_CHANGED_RESOURCE_ALIASES.get(resource, resource)


def normalize_canvas_changed_resources(*sources: Any) -> list[str]:
    resources: list[str] = []
    for source in sources:
        rows = source.get("changedResources") if isinstance(source, dict) else source
        if rows is None:
            continue
        if not isinstance(rows, (list, tuple, set)):
            rows = [rows]
        for item in rows:
            resource = normalize_canvas_changed_resource_name(item)
            if resource and resource not in resources:
                resources.append(resource)
    return resources


def _record_id_set(values: Any) -> set[str]:
    if values is None:
        return set()
    rows = values if isinstance(values, (list, tuple, set)) else [values]
    return {str(value or "").strip() for value in rows if str(value or "").strip()}


def _records_payload(
    *,
    added: list[dict[str, Any]] | None = None,
    updated: list[dict[str, Any]] | None = None,
    removed: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "added": copy.deepcopy(added if isinstance(added, list) else []),
        "updated": copy.deepcopy(updated if isinstance(updated, list) else []),
        "removed": copy.deepcopy(removed if isinstance(removed, list) else []),
    }


def _canvas_version_ref_from_value(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        return None
    node_id = str(
        value.get("nodeId")
        or value.get("node_id")
        or value.get("cardId")
        or value.get("card_id")
        or ""
    ).strip()
    version_id = str(
        value.get("versionId")
        or value.get("version_id")
        or value.get("id")
        or ""
    ).strip()
    if not node_id or not version_id:
        return None
    return node_id, version_id


def _canvas_version_ref_payload(node_id: Any, version_id: Any) -> dict[str, str] | None:
    normalized_node_id = str(node_id or "").strip()
    normalized_version_id = str(version_id or "").strip()
    if not normalized_node_id or not normalized_version_id:
        return None
    return {"nodeId": normalized_node_id, "versionId": normalized_version_id}


def _canvas_version_ref_payloads(values: list[Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for value in values if isinstance(values, list) else []:
        ref = _canvas_version_ref_from_value(value)
        if ref is None or ref in seen:
            continue
        seen.add(ref)
        rows.append({"nodeId": ref[0], "versionId": ref[1]})
    return rows


def _canvas_node_data_is_visual_handoff_asset(data: dict[str, Any]) -> bool:
    if str(data.get("eyebrow") or "").strip() != "asset.image":
        return False
    values = [
        data.get("mediaPurpose"),
        data.get("media_purpose"),
        data.get("assetKind"),
        data.get("asset_kind"),
        data.get("assetType"),
        data.get("asset_type"),
        data.get("preferredTargetSlot"),
        data.get("preferred_target_slot"),
    ]
    return any(
        str(value or "").strip() in {"visual_handoff", "visual_handoff_reference"}
        for value in values
    )


def _canvas_node_stores_own_versions(node_type: str, data: dict[str, Any]) -> bool:
    normalized_type = str(data.get("eyebrow") or node_type or "").strip()
    return normalized_type in {
        "storyboard.image",
        "video.result",
    } or _canvas_node_data_is_visual_handoff_asset(data)


def _canvas_node_version_storage_node_id(
    node_id: str,
    node_type: str,
    data: dict[str, Any],
) -> str:
    normalized_node_id = str(node_id or "").strip()
    if _canvas_node_stores_own_versions(node_type, data):
        return normalized_node_id
    owner_node_id = str(
        data.get("resultOfNodeId") or data.get("result_of_node_id") or ""
    ).strip()
    return owner_node_id or normalized_node_id


def _node_summary_record(node: dict[str, Any]) -> dict[str, Any]:
    canvas_node = _canvas_node_from_workflow_node(node)
    card = _card_document_from_workflow_node(node)
    return _card_summary_from_card(str(node.get("id") or ""), card, canvas_node)


def _node_data_record(node: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(node.get("data") if isinstance(node.get("data"), dict) else {})


def _node_position_record(node: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(node.get("position") if isinstance(node.get("position"), dict) else {})


def _node_status_record(node: dict[str, Any], data: dict[str, Any] | None = None) -> str:
    source_data = data if isinstance(data, dict) else _node_data_record(node)
    return str(source_data.get("status") or node.get("status") or "").strip()


def _edge_data_record(edge: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(edge.get("data") if isinstance(edge.get("data"), dict) else {})


def _row_node(row: sqlite3.Row, *, detail: str) -> dict[str, Any]:
    node = _json_loads(row["node_json"], {})
    if not isinstance(node, dict):
        node = {}
    keys = set(row.keys())
    node["id"] = str(row["node_id"] or node.get("id") or "").strip()
    if "node_type" in keys:
        node["type"] = str(row["node_type"] or node.get("type") or "")
    if "route_id" in keys:
        route_id = str(row["route_id"] or "").strip()
        if route_id:
            node["routeId"] = route_id
    if "segment_id" in keys:
        segment_id = str(row["segment_id"] or "").strip()
        if segment_id:
            node["segmentId"] = segment_id
    if "work_chain_id" in keys:
        node["workChainId"] = str(row["work_chain_id"] or "").strip()
    if "position_json" in keys:
        position = _json_loads(row["position_json"], {})
        if isinstance(position, dict) and position:
            node["position"] = position
    data_record = (
        _json_loads(row["data_json"], {})
        if "data_json" in keys
        else node.get("data") if isinstance(node.get("data"), dict) else {}
    )
    if not isinstance(data_record, dict):
        data_record = {}
    if "status" in keys:
        status = str(row["status"] or "").strip()
        if status and not data_record.get("status"):
            data_record["status"] = status
    if detail == "full":
        node["data"] = copy.deepcopy(data_record)
        return node
    computed_summary_data = _node_data_summary(
        data_record,
        str(node.get("type") or ""),
    )
    compact = copy.deepcopy(node)
    compact["data"] = copy.deepcopy(computed_summary_data)
    return compact


_ROUTE_SUMMARY_KEYS = (
    "id",
    "title",
    "label",
    "name",
    "episodeId",
    "episode_id",
    "workChainId",
    "work_chain_id",
    "segmentId",
    "segment_id",
    "segmentIds",
    "segment_ids",
    "nodeIds",
    "node_ids",
    "strategy",
    "storyboardTemplate",
    "storyboard_template",
    "storyboardTemplateLabel",
    "storyboard_template_label",
    "status",
    "shotIds",
    "shot_ids",
    "shotCount",
    "shot_count",
    "laneIndex",
    "lane_index",
    "locked",
    "lockedByUser",
    "locked_by_user",
    "preserveOnReplan",
    "preserve_on_replan",
    "lockedReason",
    "locked_reason",
    "modelRequirements",
    "model_requirements",
    "generationConfig",
    "generation_config",
    "quality",
)


def _row_route(row: sqlite3.Row, *, detail: str) -> dict[str, Any]:
    route = _json_loads(row["route_json"], {})
    if not isinstance(route, dict):
        route = {}
    if detail == "full":
        return route
    summary = _json_loads(row["summary_json"], {})
    if not isinstance(summary, dict) or not summary:
        return route
    route_summary = copy.deepcopy(summary)
    for key in _ROUTE_SUMMARY_KEYS:
        if key not in route_summary and route.get(key) is not None:
            route_summary[key] = copy.deepcopy(route.get(key))
    return route_summary


def _row_work_chain(row: sqlite3.Row, *, detail: str) -> dict[str, Any]:
    work_chain = _json_loads(row["work_chain_json"], {})
    if not isinstance(work_chain, dict):
        work_chain = {}
    if detail == "full":
        return work_chain
    summary = _json_loads(row["summary_json"], {})
    return summary if isinstance(summary, dict) and summary else work_chain


def _route_summary_record(route: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(route.get(key))
        for key in _ROUTE_SUMMARY_KEYS
        if route.get(key) is not None
    }


def _work_chain_summary_record(work_chain: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(work_chain.get(key))
        for key in ("id", "title", "label", "name", "routeIds", "nodeIds", "status", "summary", "origin", "order", "layout")
        if work_chain.get(key) is not None
    }


def _row_version(row: sqlite3.Row) -> dict[str, Any]:
    version = _json_loads(row["version_json"], {})
    if not isinstance(version, dict):
        version = {}
    node_id = str(row["node_id"] or "")
    version_id = str(row["version_id"] or "")
    version.setdefault("id", version_id)
    version.setdefault("nodeId", node_id)
    version.setdefault("cardId", node_id)
    if "active" in row.keys():
        version["active"] = bool(row["active"])
    return version


def _active_card_version_id(conn: sqlite3.Connection, episode_id: str, node_id: str) -> str:
    row = conn.execute(
        """
        SELECT version_id
        FROM canvas_versions
        WHERE episode_id = ? AND node_id = ? AND active = 1
        ORDER BY sort_index DESC, version_id DESC
        LIMIT 1
        """,
        (episode_id, node_id),
    ).fetchone()
    return str(row["version_id"] or "") if row is not None else ""


def _canvas_change_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = _json_loads(row["payload_json"], {})
    if not isinstance(payload, dict):
        payload = {}
    records = payload.get("records") if isinstance(payload.get("records"), dict) else _records_payload()
    changed_resources = normalize_canvas_changed_resources(payload.get("changedResources"))
    payload["changedResources"] = copy.deepcopy(changed_resources)
    return {
        "txId": row["tx_id"],
        "seq": int(row["seq"] or 0),
        "opType": row["op_type"],
        "baseRevision": int(row["base_revision"] or 0),
        "revision": int(row["revision"] or 0),
        "records": records,
        "changedResources": changed_resources,
        "payload": payload,
        "createdAt": row["created_at"],
    }


def _canvas_record_ids_from_payload(payload: dict[str, Any]) -> dict[str, set[Any]]:
    ids: dict[str, set[Any]] = {
        "nodes": set(),
        "edges": set(),
        "routes": set(),
        "workChains": set(),
        "versionRefs": set(),
        "tasks": set(),
        "projections": set(),
    }

    def add_many(target: str, values: Any) -> None:
        for value in values if isinstance(values, list) else []:
            text = str(value or "").strip()
            if text:
                ids[target].add(text)

    add_many("nodes", payload.get("nodeIds"))
    add_many("edges", payload.get("edgeIds"))
    add_many("routes", payload.get("routeIds"))
    add_many("workChains", payload.get("workChainIds"))
    add_many("tasks", payload.get("taskIds"))
    add_many("projections", payload.get("projectionKeys"))
    for value in payload.get("versionRefs") if isinstance(payload.get("versionRefs"), list) else []:
        ref = _canvas_version_ref_from_value(value)
        if ref is not None:
            ids["versionRefs"].add(ref)

    records = payload.get("records") if isinstance(payload.get("records"), dict) else {}
    type_targets = {
        "canvas_node": "nodes",
        "canvas_edge": "edges",
        "canvas_route": "routes",
        "canvas_work_chain": "workChains",
        "canvas_task": "tasks",
        "canvas_projection": "projections",
    }
    for bucket_name in ("added", "updated"):
        bucket = records.get(bucket_name) if isinstance(records, dict) else []
        for record in bucket if isinstance(bucket, list) else []:
            if not isinstance(record, dict):
                continue
            record_type = str(record.get("type") or "").strip()
            if record_type == "canvas_version":
                ref = _canvas_version_ref_from_value(record)
                if ref is not None:
                    ids["versionRefs"].add(ref)
                continue
            target = type_targets.get(record_type)
            record_id = str(record.get("id") or "").strip()
            if target and record_id:
                ids[target].add(record_id)
    return ids


def _merge_canvas_record_ids(
    target: dict[str, set[Any]],
    source: dict[str, set[Any]],
) -> dict[str, set[Any]]:
    for key, values in source.items():
        target.setdefault(key, set()).update(values)
    return target


def empty_canvas_workflow_projection_v4(project_id: str, episode_id: str, reason: str = "missing_canvas") -> dict[str, Any]:
    return {
        "episodeId": episode_id,
        "schemaVersion": 4,
        "version": 0,
        "viewport": {"x": 0, "y": 0, "zoom": 0.82},
        "routes": [],
        "nodes": [],
        "edges": [],
        "workChains": [],
        "state": {
            "kind": "empty",
            "reason": reason,
            "sourceReady": False,
            "workChainPlanReady": False,
            "workflowChainReady": False,
            "nextAction": "build_workflow_chain",
        },
    }


def _node_data_summary(data: dict[str, Any], node_type: str = "") -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if node_type == "source.text" and data.get("sourceMode") == "independent":
        summary["sourceText"] = _summary_value("sourceText", data.get("sourceText", ""))
    for key in _SUMMARY_DATA_KEYS:
        if key in data:
            compact = _summary_value(key, data.get(key))
            if compact is not None:
                summary[key] = compact
    if node_type in VIDEO_TASK_NODE_TYPES:
        if "videoTaskCard" in data:
            card = _summary_video_task_card(data.get("videoTaskCard"))
            if card:
                summary["videoTaskCard"] = card
        if "prompt" in data:
            prompt = _summary_prompt(data.get("prompt"))
            if prompt:
                summary["prompt"] = prompt
    if node_type == "prompt.storyboard":
        if "storyboardTaskCard" in data:
            card = _summary_storyboard_task_card(data.get("storyboardTaskCard"))
            if card:
                summary["storyboardTaskCard"] = card
        if "prompt" in data:
            prompt = _summary_storyboard_prompt(data.get("prompt"))
            if prompt:
                summary["prompt"] = prompt
    if node_type == "storyboard.card":
        summary["directorPlanShots"] = copy.deepcopy(data.get("directorPlanShots") or [])
    if node_type == "director.board":
        if "directorTaskCard" in data:
            card = _summary_director_task_card(data.get("directorTaskCard"))
            if card:
                summary["directorTaskCard"] = card
        if "prompt" in data:
            prompt = _summary_director_prompt(data.get("prompt"))
            if prompt:
                summary["prompt"] = prompt
    return summary


def _canvas_node_from_workflow_node(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    canvas_node = {
        key: copy.deepcopy(value)
        for key, value in node.items()
        if key not in {"data", "measured", "selected", "dragging"}
    }
    node_id = str(canvas_node.get("id") or "").strip()
    canvas_node["cardRef"] = f"cards/{_safe_part(node_id, 'card')}/card.json"
    summary = _node_data_summary(data, str(node.get("type") or data.get("eyebrow") or ""))
    if summary:
        canvas_node["data"] = summary
    return canvas_node


def _card_document_from_workflow_node(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    node_id = str(node.get("id") or "").strip()
    return {
        "schemaVersion": 1,
        "id": node_id,
        "type": str(node.get("type") or ""),
        "routeId": str(node.get("routeId") or data.get("routeId") or ""),
        "segmentId": str(node.get("segmentId") or data.get("segmentId") or ""),
        "workChainId": str(data.get("workChainId") or node.get("workChainId") or ""),
        "title": str(data.get("title") or node_id),
        "status": str(data.get("status") or ""),
        "summary": str(data.get("summary") or ""),
        "activeVersionId": str(data.get("activeVersionId") or ""),
        "updatedAt": _now(),
        "data": copy.deepcopy(data),
    }


def _card_summary_from_card(node_id: str, card: dict[str, Any], canvas_node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": card.get("type") or "",
        "title": card.get("title") or node_id,
        "status": card.get("status") or "",
        "summary": card.get("summary") or "",
        "activeVersionId": card.get("activeVersionId") or "",
        "routeId": card.get("routeId") or "",
        "segmentId": card.get("segmentId") or "",
        "workChainId": card.get("workChainId") or "",
        "data": copy.deepcopy(canvas_node.get("data") if isinstance(canvas_node.get("data"), dict) else {}),
    }


def _row_edge(row: sqlite3.Row) -> dict[str, Any]:
    edge = _json_loads(row["edge_json"], {})
    if not isinstance(edge, dict):
        edge = {}
    edge_id = str(row["edge_id"] or edge.get("id") or "").strip()
    source = str(row["source_node_id"] or edge.get("source") or "").strip()
    target = str(row["target_node_id"] or edge.get("target") or "").strip()
    source_handle = str(row["source_handle"] or edge.get("sourceHandle") or "")
    target_handle = str(row["target_handle"] or edge.get("targetHandle") or "")
    edge_data = _json_loads(row["edge_data_json"], {})
    if edge_id:
        edge["id"] = edge_id
    if source:
        edge["source"] = source
    if target:
        edge["target"] = target
    if source_handle:
        edge["sourceHandle"] = source_handle
    if target_handle:
        edge["targetHandle"] = target_handle
    if isinstance(edge_data, dict) and edge_data and not isinstance(edge.get("data"), dict):
        edge["data"] = edge_data
    return edge


def _node_route_ids(node: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    for source in (node, data):
        for key in ("routeId", "route_id"):
            value = str(source.get(key) or "").strip() if isinstance(source, dict) else ""
            if value:
                ids.add(value)
    return ids


def _node_work_chain_ids(node: dict[str, Any]) -> set[str]:
    owner = str(node.get("workChainId") or "").strip()
    return {owner} if owner else set()


def _input_link_source_node_ids(value: Any, *, target_node_ids: set[str] | None = None) -> set[str]:
    result: set[str] = set()
    links = value if isinstance(value, list) else []
    allowed_targets = target_node_ids or set()
    for link in links:
        if not isinstance(link, dict):
            continue
        if allowed_targets:
            target = str(link.get("targetNodeId") or link.get("target_node_id") or "").strip()
            if target and target not in allowed_targets:
                continue
        source_node_id = str(link.get("sourceNodeId") or link.get("source_node_id") or link.get("source") or "").strip()
        if source_node_id:
            result.add(source_node_id)
    return result


def _input_link_target_node_ids_for_sources(
    value: Any,
    *,
    source_node_ids: set[str],
    fallback_target_node_id: str = "",
) -> set[str]:
    result: set[str] = set()
    links = value if isinstance(value, list) else []
    allowed_sources = {str(item or "").strip() for item in source_node_ids if str(item or "").strip()}
    if not allowed_sources:
        return result
    fallback_target = str(fallback_target_node_id or "").strip()
    for link in links:
        if not isinstance(link, dict):
            continue
        source_node_id = str(link.get("sourceNodeId") or link.get("source_node_id") or link.get("source") or "").strip()
        if source_node_id not in allowed_sources:
            continue
        target_node_id = str(link.get("targetNodeId") or link.get("target_node_id") or "").strip() or fallback_target
        if target_node_id:
            result.add(target_node_id)
    return result


def _normalized_card_versions(card_id: str, versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_versions: list[dict[str, Any]] = []
    for item in (versions if isinstance(versions, list) else []):
        if not isinstance(item, dict):
            continue
        row = copy.deepcopy(item)
        if not str(row.get("nodeId") or "").strip():
            row["nodeId"] = card_id
        if not str(row.get("cardId") or "").strip():
            row["cardId"] = card_id
        normalized_versions.append(row)
    return normalized_versions


@dataclass(frozen=True)
class CanvasProjectionState:
    """Record identities and signatures observed within one canvas transaction."""

    node_ids: set[str]
    edge_ids: set[str]
    route_ids: set[str]
    work_chain_ids: set[str]
    node_signatures: dict[str, str]
    edge_signatures: dict[str, str]
    route_signatures: dict[str, str]
    work_chain_signatures: dict[str, str]
    version_refs: list[dict[str, str]] = field(default_factory=list)
    task_refs: list[dict[str, str]] = field(default_factory=list)


def _canvas_projection_change_payload(
    previous: CanvasProjectionState,
    active: CanvasProjectionState,
    extras: dict[str, Any],
) -> dict[str, Any]:
    removed_node_ids = previous.node_ids - active.node_ids
    removed_edge_ids = previous.edge_ids - active.edge_ids
    removed_route_ids = previous.route_ids - active.route_ids
    removed_work_chain_ids = previous.work_chain_ids - active.work_chain_ids
    removed_version_refs = [
        ref
        for ref in previous.version_refs
        if ref["nodeId"] in removed_node_ids and ref["versionId"]
    ]
    removed_task_refs = [
        ref
        for ref in previous.task_refs
        if ref["nodeId"] in removed_node_ids and ref["taskId"]
    ]
    added_node_ids = active.node_ids - previous.node_ids
    added_edge_ids = active.edge_ids - previous.edge_ids
    added_route_ids = active.route_ids - previous.route_ids
    added_work_chain_ids = active.work_chain_ids - previous.work_chain_ids
    updated_node_ids = {
        node_id
        for node_id in active.node_ids & previous.node_ids
        if active.node_signatures.get(node_id) != previous.node_signatures.get(node_id)
    }
    updated_edge_ids = {
        edge_id
        for edge_id in active.edge_ids & previous.edge_ids
        if active.edge_signatures.get(edge_id) != previous.edge_signatures.get(edge_id)
    }
    updated_route_ids = {
        route_id
        for route_id in active.route_ids & previous.route_ids
        if active.route_signatures.get(route_id) != previous.route_signatures.get(route_id)
    }
    updated_work_chain_ids = {
        work_chain_id
        for work_chain_id in active.work_chain_ids & previous.work_chain_ids
        if active.work_chain_signatures.get(work_chain_id)
        != previous.work_chain_signatures.get(work_chain_id)
    }
    records = _records_payload(
        added=[
            *[_record_ref("canvas_node", node_id) for node_id in sorted(added_node_ids)],
            *[_record_ref("canvas_edge", edge_id) for edge_id in sorted(added_edge_ids)],
            *[_record_ref("canvas_route", route_id) for route_id in sorted(added_route_ids)],
            *[
                _record_ref("canvas_work_chain", work_chain_id)
                for work_chain_id in sorted(added_work_chain_ids)
            ],
        ],
        updated=[
            *[_record_ref("canvas_node", node_id) for node_id in sorted(updated_node_ids)],
            *[_record_ref("canvas_edge", edge_id) for edge_id in sorted(updated_edge_ids)],
            *[_record_ref("canvas_route", route_id) for route_id in sorted(updated_route_ids)],
            *[
                _record_ref("canvas_work_chain", work_chain_id)
                for work_chain_id in sorted(updated_work_chain_ids)
            ],
        ],
        removed=[
            *[_record_ref("canvas_node", node_id) for node_id in sorted(removed_node_ids)],
            *[_record_ref("canvas_edge", edge_id) for edge_id in sorted(removed_edge_ids)],
            *[_record_ref("canvas_route", route_id) for route_id in sorted(removed_route_ids)],
            *[
                _record_ref("canvas_work_chain", work_chain_id)
                for work_chain_id in sorted(removed_work_chain_ids)
            ],
            *[
                _record_ref(
                    "canvas_version",
                    ref["versionId"],
                    nodeId=ref["nodeId"],
                )
                for ref in removed_version_refs
            ],
            *[
                _record_ref(
                    "canvas_task",
                    ref["taskId"],
                    nodeId=ref["nodeId"],
                )
                for ref in removed_task_refs
            ],
        ]
    )
    changed_resources = ["canvas_document"]
    if added_node_ids or updated_node_ids or removed_node_ids:
        changed_resources.append("canvas_node")
    if added_edge_ids or updated_edge_ids or removed_edge_ids:
        changed_resources.append("canvas_edge")
    if added_route_ids or updated_route_ids or removed_route_ids:
        changed_resources.append("canvas_route")
    if added_work_chain_ids or updated_work_chain_ids or removed_work_chain_ids:
        changed_resources.append("canvas_work_chain")
    if removed_version_refs:
        changed_resources.append("canvas_version")
    if removed_task_refs:
        changed_resources.append("canvas_task")
    changed_node_ids = sorted(added_node_ids | updated_node_ids)
    changed_edge_ids = sorted(added_edge_ids | updated_edge_ids)
    changed_route_ids = sorted(added_route_ids | updated_route_ids)
    changed_work_chain_ids = sorted(added_work_chain_ids | updated_work_chain_ids)
    op_payload: dict[str, Any] = {
        "records": records,
        "documentExtras": copy.deepcopy(extras),
        "nodeIds": changed_node_ids,
        "edgeIds": changed_edge_ids,
        "routeIds": changed_route_ids,
        "workChainIds": changed_work_chain_ids,
        "removedNodeIds": sorted(removed_node_ids),
        "removedEdgeIds": sorted(removed_edge_ids),
        "removedRouteIds": sorted(removed_route_ids),
        "removedWorkChainIds": sorted(removed_work_chain_ids),
        "removedVersionRefs": [
            ref
            for ref in (
                _canvas_version_ref_payload(item.get("nodeId"), item.get("versionId"))
                for item in removed_version_refs
            )
            if ref is not None
        ],
        "removedTaskIds": [ref["taskId"] for ref in removed_task_refs],
        "changedResources": changed_resources,
    }
    if isinstance(extras.get("productionStatus"), dict):
        op_payload["productionStatus"] = copy.deepcopy(extras["productionStatus"])
    return op_payload
