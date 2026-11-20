# -*- coding: utf-8 -*-
"""Normalize SDK tool outcomes and diagnostics without owning a running turn."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from .agent_context_runtime import (
    _agent_compact_commit_payload,
    _agent_compact_proposal,
)
from .source_text_store import _compact_text


_READ_TOOL_PREFIXES = ("get_", "read_", "search_", "list_")
_READ_TARGET_KEYS = (
    "sourceId", "chapterId", "nodeId", "workflowId", "assetId", "rangeId", "assetRangeId",
    "beforeMessageId", "offset", "start", "end", "length", "limit", "maxMatches",
    "file", "path", "relativePath", "relative_path", "filePath", "file_path",
)


def _observation_digest(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str,
                            separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _observation_identifier(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
        return value
    return {"digest": _observation_digest(value), "chars": len(value)}


def _sdk_tool_read_observation(
    tool_name: str, result: dict[str, Any], args: dict[str, Any], *,
    project_id: str, episode_id: str,
) -> dict[str, Any] | None:
    if not tool_name.startswith(_READ_TOOL_PREFIXES):
        return None
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str,
                            separators=(",", ":"))
    target = {"projectId": _observation_identifier(project_id)}
    if episode_id:
        target["episodeId"] = _observation_identifier(episode_id)
    for key in _READ_TARGET_KEYS:
        if key in args:
            value = _observation_identifier(args[key])
            if value is not None:
                target[key] = value
    if isinstance(args.get("query"), str):
        target["queryDigest"] = _observation_digest(args["query"])
        target["queryChars"] = len(args["query"])
    file_info = result.get("file")
    if tool_name == "read_project_file" and isinstance(file_info, dict):
        relative_path = file_info.get("relativePath")
        if isinstance(relative_path, str) and relative_path and len(relative_path) <= 256:
            normalized = relative_path.replace("\\", "/")
            if not normalized.startswith("/") and ".." not in normalized.split("/"):
                target["resolvedRelativePath"] = normalized
    observation: dict[str, Any] = {
        "target": target,
        "outputDigest": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "outputChars": len(serialized),
    }
    for key in ("inputDigest", "contextVersion", "candidateVersion", "truncated", "sampled",
                "totalMatches", "searchedSourceCount", "hasMore"):
        if key in result:
            value = _observation_identifier(result[key])
            if value is not None:
                observation[key] = value
    window = result.get("sourceWindow")
    if isinstance(window, dict):
        observation["sourceWindow"] = {
            key: value for key in ("sourceId", "absoluteStart", "absoluteEnd", "length", "hasAfter", "hasBefore")
            if (value := _observation_identifier(window.get(key))) is not None
        }
    return observation


def _agent_raw_diagnostic_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:  # noqa: BLE001
        return str(value)


def _agent_diagnostic_content_blocks(title: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"type": "text", "text": f"{title}\n\n下面是后端保留的原始错误信息，便于排查。"},
        {
            "type": "tool_result",
            "content": _agent_raw_diagnostic_text(payload),
            "is_error": True,
            "contextExcluded": True,
        },
    ]


def _agent_sdk_tool_result_event_text(item: dict[str, Any]) -> str:
    def _flatten(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            parts: list[str] = []
            for child in value:
                parts.extend(_flatten(child))
            return parts
        if isinstance(value, dict):
            text = value.get("text") or value.get("content") or value.get("result")
            if text is not None:
                return _flatten(text)
            return [json.dumps(value, ensure_ascii=False, default=str)]
        return [str(value)] if value is not None else []

    return "\n".join(part.strip() for part in _flatten(item.get("content")) if part and part.strip()).strip()


def _agent_sdk_tool_result_error_summary(items: list[dict[str, Any]]) -> str:
    for item in reversed(items):
        text = _agent_sdk_tool_result_event_text(item)
        if not text:
            continue
        json_start = text.find("{")
        if json_start >= 0:
            try:
                payload = json.loads(text[json_start:])
                if isinstance(payload, dict):
                    for key in ("error", "message", "detail"):
                        value = payload.get(key)
                        if value:
                            return _compact_text(str(value), 240)
            except Exception:  # noqa: BLE001
                pass
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            return _compact_text(lines[-1] if len(lines) > 1 else lines[0], 240)
    return "工具执行失败"


def _sdk_tool_result_summary(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    task = result.get("task") if isinstance(result.get("task"), dict) else {}
    version = result.get("version") if isinstance(result.get("version"), dict) else {}
    asset = result.get("asset") if isinstance(result.get("asset"), dict) else {}
    summary = {
        "tool": tool_name,
        "success": bool(result.get("success", True)),
    }
    if result.get("status"):
        summary["status"] = str(result["status"])
    for key in ("productionStatusRefreshFailed", "productionStatusWarning", "productionWarnings"):
        if result.get(key):
            summary[key] = copy.deepcopy(result[key])
    if tool_name == "validate_director_plan_draft" and result.get("status") == "validated":
        # The model must be able to reference the exact draft stored by this turn.
        # Omitting this digest forces it to regenerate a long JSON payload at commit.
        summary["submissionDigest"] = str(result.get("submissionDigest") or "")
        summary["inputDigest"] = str(result.get("inputDigest") or "")
        summary["shotCount"] = result.get("shotCount")
        summary["groupCount"] = result.get("groupCount")
    if isinstance(result.get("errors"), list):
        summary["errors"] = copy.deepcopy(result["errors"])
    if result.get("backgroundStarted"):
        summary["backgroundStarted"] = True
    if result.get("suppressSessionMessage") or result.get("suppress_session_message"):
        summary["suppressSessionMessage"] = True
    if task:
        summary["task"] = {
            "id": task.get("id"),
            "type": task.get("type"),
            "status": task.get("status"),
            "progress": task.get("progress"),
            "message": task.get("message"),
        }
    if version:
        summary["version"] = {
            "id": version.get("id"),
            "nodeId": version.get("nodeId"),
            "status": version.get("status"),
            "title": version.get("title"),
        }
    if asset:
        summary["asset"] = {
            "id": asset.get("id"),
            "name": asset.get("name") or asset.get("title"),
            "type": asset.get("type"),
        }
    if result.get("error"):
        summary["error"] = str(result.get("error"))
    if result.get("summary") or result.get("message"):
        summary["message"] = str(result.get("summary") or result.get("message") or "")
    if result.get("changedResources"):
        summary["changedResources"] = result.get("changedResources")
    if result.get("focusTarget"):
        summary["focusTarget"] = result.get("focusTarget")
    if result.get("projectChanged"):
        summary["projectChanged"] = True
    if isinstance(result.get("extractedRequirements"), dict):
        extracted = result.get("extractedRequirements") or {}
        summary["extractedRequirements"] = {
            "workType": extracted.get("workType"),
            "constraintCount": len(extracted.get("constraints") or []),
            "skippedReason": extracted.get("skippedReason"),
        }
    if result.get("assetCounts"):
        summary["assetCounts"] = result.get("assetCounts")
    if isinstance(result.get("workerRun"), dict):
        worker_run = result.get("workerRun") or {}
        summary["workerRun"] = {
            "workerRunId": worker_run.get("workerRunId"),
            "workerName": worker_run.get("workerName"),
            "sessionId": worker_run.get("sessionId"),
            "taskId": worker_run.get("taskId"),
            "assetRangeId": worker_run.get("assetRangeId"),
            "episodeId": worker_run.get("episodeId"),
            "sdkSessionId": worker_run.get("sdkSessionId"),
            "status": worker_run.get("status"),
            "error": worker_run.get("error"),
        }
    if result.get("episodeCount"):
        summary["episodeCount"] = result.get("episodeCount")
    if result.get("sourceWindow"):
        window = result.get("sourceWindow")
        summary["sourceWindow"] = {
            "sourceId": window.get("sourceId"),
            "chapterId": window.get("chapterId"),
            "absoluteStart": window.get("absoluteStart"),
            "absoluteEnd": window.get("absoluteEnd"),
            "length": window.get("length"),
            "hasAfter": window.get("hasAfter"),
        }
    if result.get("coverage"):
        coverage = result.get("coverage")
        if isinstance(coverage, dict):
            summary["coverage"] = {
                "sourceId": coverage.get("sourceId"),
                "episodeCursor": coverage.get("episodeCursor"),
                "assetCursor": coverage.get("assetCursor"),
                "episodeRangeCount": len(coverage.get("episodeRanges") or []),
                "assetRangeCount": len(coverage.get("assetRanges") or []),
            }
    if result.get("proposal"):
        summary["proposal"] = _agent_compact_proposal(result.get("proposal"))
    if result.get("commitPayload"):
        summary["commitPayload"] = _agent_compact_commit_payload(result.get("commitPayload"))
    if result.get("nextStep"):
        summary["nextStep"] = result.get("nextStep")
    if result.get("recoveryAdvice"):
        summary["recoveryAdvice"] = result.get("recoveryAdvice")
    if result.get("nextAllowedTools"):
        summary["nextAllowedTools"] = result.get("nextAllowedTools")
    if result.get("requiresAssetExtraction"):
        summary["requiresAssetExtraction"] = True
    if result.get("assetCoverage"):
        summary["assetCoverage"] = result.get("assetCoverage")
    if result.get("recommendedAction"):
        summary["recommendedAction"] = result.get("recommendedAction")
    if result.get("recommendedPayload"):
        summary["recommendedPayload"] = result.get("recommendedPayload")
    if "requiresUserConfirmation" in result:
        summary["requiresUserConfirmation"] = bool(result.get("requiresUserConfirmation"))
    if result.get("range"):
        summary["range"] = result.get("range")
    if result.get("episodeSources"):
        summary["episodeSources"] = result.get("episodeSources")
    if result.get("qualityGates"):
        summary["qualityGates"] = result.get("qualityGates")
    if isinstance(result.get("rules"), list):
        summary["ruleCount"] = len(result.get("rules") or [])
    if isinstance(result.get("matches"), list):
        summary["matchCount"] = len(result.get("matches") or [])
    if isinstance(result.get("rule"), dict):
        rule = result.get("rule") or {}
        summary["rule"] = {
            "file": rule.get("file"),
            "title": rule.get("title"),
            "truncated": rule.get("truncated"),
        }
    if not bool(summary.get("success", True)):
        summary["rawResult"] = copy.deepcopy(result)
    return summary


def _sdk_tool_result_is_business_feedback(summary: dict[str, Any]) -> bool:
    if bool(summary.get("success", True)):
        return False
    errors = summary.get("errors")
    if (summary.get("status") in {"validation_failed", "rejected"}
            and isinstance(errors, list) and errors
            and all(isinstance(error, dict) and error.get("repairAction") in
                    {"revise_and_resubmit", "reread_context"} for error in errors)):
        return True
    if bool(summary.get("requiresAssetExtraction")) and str(summary.get("recommendedAction") or "").strip() in {
        "asset_range_propose",
        "asset_extraction",
    }:
        return True
    return str(summary.get("tool") or "").strip() in {
        "submit_episode_boundary_candidate",
        "validate_project_quality",
    }


def _agent_business_feedback_recommendation(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Turn a recoverable tool result into one executable next-step card."""
    if not _sdk_tool_result_is_business_feedback(summary):
        return None
    action = str(summary.get("recommendedAction") or "").strip()
    if action == "asset_range_propose":
        coverage = summary.get("assetCoverage") if isinstance(summary.get("assetCoverage"), dict) else {}
        cursor = coverage.get("assetCursorOffset")
        required_end = coverage.get("episodeRequiredEndOffset")
        range_text = ""
        if cursor is not None and required_end is not None:
            range_text = f"当前资产已覆盖到 {cursor}，本次分集需要覆盖到 {required_end}。"
        return {
            "type": "recommendations",
            "origin": "task_feedback",
            "title": "下一步建议",
            "items": [
                {
                    "id": "propose_next_asset_range",
                    "label": "拆下一段资产",
                    "description": (
                        f"{range_text}点击后规划并写入下一段范围，再拆分角色、生物、场景和道具。"
                        if range_text
                        else "点击后规划并写入下一段范围，再拆分角色、生物、场景和道具。"
                    ),
                    "mode": "prompt",
                    "prompt": (
                        "请规划当前缺口所需的下一段资产范围；"
                        "请调用 submit_asset_range_candidate 校验并写入范围；资产拆分另行发起。"
                    ),
                    "taskType": "asset_range_propose",
                    "controlOnly": True,
                    "recommended": True,
                }
            ],
        }
    if action == "asset_extraction":
        payload = summary.get("recommendedPayload") if isinstance(summary.get("recommendedPayload"), dict) else {}
        range_id = str(payload.get("rangeId") or "").strip()
        target = f"资产范围 {range_id}" if range_id else "上一段已确认的资产范围"
        return {
            "type": "recommendations",
            "origin": "task_feedback",
            "title": "下一步建议",
            "items": [
                {
                    "id": "resume_asset_extraction",
                    "label": "继续拆分资产",
                    "description": f"{target}尚未拆分完成；读取该范围并继续拆分。",
                    "mode": "prompt",
                    "prompt": f"请读取{target}，继续拆分资产并提交结果；完成后再规划分集断点。",
                    "taskType": "asset_extraction",
                    "controlOnly": True,
                    "recommended": True,
                }
            ],
        }
    return None
