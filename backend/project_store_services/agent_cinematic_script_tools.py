# -*- coding: utf-8 -*-
"""Scoped context and verified commit for Agent-authored cinematic scripts."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from .canvas_store_queries import read_canvas_card_record_v4, read_previous_cinematic_script_text_v4
from .director_plan_contract import _normalize_multiline_text
from .settings_loaders import load_script_adaptation_templates
from .script_delivery_contract import normalize_script_delivery_contract
from .workflow_cinematic_script import _CinematicScriptWriter
from .work_chain_context import script_narrative_mode


def _digest(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def cinematic_script_output_digest(value: Any, delivery_contract: Any = None) -> str:
    text = _normalize_multiline_text(value)
    return _digest(text if delivery_contract is None else {"script": text, "deliveryContract": delivery_contract})


_EDITORIAL_SCRIPT_LINE = re.compile(r"^\s*(?:编辑层字卡|编辑层文字|人物介绍卡|装饰字卡)\s*[：:]", re.MULTILINE)
_READABLE_MEDIA_LINE = re.compile(r"^\s*(?:画面文字|屏幕文字)([^\n：:]{0,120})[：:]\s*(.*?)\s*$")
_SCENE_HEADING = re.compile(r"^\s*(?:内景|外景)[·.]")
_LIVE_DIALOGUE_LINE = re.compile(r"^\s*[^\n]{1,100}（对白）[：:]")


def _media_exposition_budget_issue(script: str) -> str:
    """Catch a passive scene built from serial must-read screen text."""
    beats: list[int] = []
    has_live_dialogue = False
    for line_no, line in enumerate([*script.splitlines(), "内景·结束"], start=1):
        if _SCENE_HEADING.match(line):
            if len(beats) > 2 and not has_live_dialogue:
                return (f"第 {beats[0]}、{beats[1]}、{beats[2]} 行起，同一现场连续要求读清多条长屏幕文字，"
                        "且没有真实现场对白或新的互动来承载。请将决定剧情的讨论交给有来源的不同人声，"
                        "屏幕保留消息信息流；字面不是线索的内容不要求逐字阅读，也不要交给分镜逐条切镜。")
            beats = []
            has_live_dialogue = False
            continue
        if _LIVE_DIALOGUE_LINE.match(line):
            has_live_dialogue = True
        screen = _READABLE_MEDIA_LINE.match(line)
        if screen and any(tag in screen.group(1) for tag in ("清晰可读", "清楚可读", "完整读完", "清楚读完")):
            content = "".join(screen.group(2).split())
            if len(content) >= 12:
                beats.append(line_no)
    return ""


def _failure(path: str, code: str, message: str, repair_action: str) -> dict[str, Any]:
    return {
        "success": False,
        "status": "validation_failed",
        "message": message,
        "errors": [{"path": path, "code": code, "message": message, "repairAction": repair_action}],
        "projectChanged": False,
    }


def _preceding_novel_context(excerpt: str, fragment: str) -> str:
    """Return only source before this fragment; the fragment has its own read part."""
    source = _normalize_multiline_text(excerpt)
    target = _normalize_multiline_text(fragment)
    if not source or not target or source.count(target) != 1:
        # An ambiguous repeated excerpt cannot establish a preceding boundary.
        # The current fragment remains authoritative, so continue without one.
        return ""
    return source[:source.index(target)].rstrip()


def _previous_script_context(project_id: str, episode_id: str, node: dict[str, Any]) -> str:
    """Read the immediately preceding work chain's saved script for scene continuity."""
    current_chain_id = str(node.get("workChainId") or "")
    if not current_chain_id:
        return ""
    return _normalize_multiline_text(
        read_previous_cinematic_script_text_v4(project_id, episode_id, current_chain_id)
    )


def _inputs(project_id: str, episode_id: str, node_id: str, user_instruction: str, preferred_template_id: str = "") -> tuple[dict[str, Any], _CinematicScriptWriter]:
    if not str(episode_id or "").strip() or not str(node_id or "").strip():
        raise ValueError("必须明确提供 episodeId 和 nodeId")
    writer = _CinematicScriptWriter(project_id, episode_id, {
        "nodeId": node_id,
        "userInstruction": user_instruction,
        "scriptTemplateId": preferred_template_id,
    })
    writer._load_script_context()
    if preferred_template_id and writer.script_template["id"] != preferred_template_id:
        raise ValueError(f"本轮指定的创作策略不存在：{preferred_template_id}")
    sample, context_episodes = writer._load_input_sample()
    writer.input_sample = copy.deepcopy(sample)
    writer.context_episodes = copy.deepcopy(context_episodes)
    node_data = writer.node.get("data") if isinstance(writer.node.get("data"), dict) else {}
    narrative_mode = script_narrative_mode(node_data)
    templates = [
        {key: copy.deepcopy(item.get(key)) for key in ("id", "name", "prompt")}
        for item in load_script_adaptation_templates() if isinstance(item, dict) and item.get("id")
    ]
    raw_asset_refs = copy.deepcopy(node_data.get("assetRefs"))
    asset_refs = raw_asset_refs if isinstance(raw_asset_refs, dict) else {}
    writer.expected_asset_refs = raw_asset_refs
    writer.expected_asset_bindings = copy.deepcopy(node_data.get("assetBindings") or [])
    preceding_text = _preceding_novel_context(sample["novelExcerpt"], writer.source_fact_text)
    previous_script = _previous_script_context(project_id, episode_id, writer.node)
    context = {
        "episodeId": episode_id,
        "nodeId": node_id,
        "nodeTitle": str(writer.node.get("title") or node_data.get("title") or ""),
        "sourceFactText": writer.source_fact_text,
        "narrativeMode": narrative_mode,
        "sourceRefs": copy.deepcopy(node_data.get("sourceRefs") or []),
        "novelExcerpt": preceding_text,
        "previousCinematicStoryText": previous_script,
        "entryAnchorText": (previous_script or preceding_text)[-360:],
        "contextKind": sample.get("contextKind") or "episode",
        "contextEpisodeIds": context_episodes,
        "assetRefs": asset_refs,
        "assetBindings": copy.deepcopy(node_data.get("assetBindings") or []),
        "currentCinematicStoryText": _normalize_multiline_text(node_data.get("cinematicStoryText")),
        "userInstruction": user_instruction,
        "defaultScriptTemplateId": writer.script_template["id"],
        "scriptTemplates": templates,
        "nodeGenerationState": copy.deepcopy(writer.initial_card_state),
    }
    context["inputDigest"] = _digest(context)
    context.pop("nodeGenerationState")
    return context, writer


def validate_cinematic_script_reads(read_versions: dict[str, str], input_digest: str, *,
                                    require_submission_state: bool = False,
                                    require_current_script: bool = False) -> dict[str, Any] | None:
    """A fresh digest cannot authorize content composed from earlier reads."""
    bundle_version = read_versions.get("generation_bundle")
    if bundle_version == input_digest and input_digest:
        return None
    if bundle_version:
        result = _failure("inputDigest", "stale_context", "剧本创作资料已变化，请重新读取完整资料包并修订正文", "reread_context")
        result["requiredParts"] = ["generation_bundle"]
        return result
    required = {"source_fragment", "novel_context", "strategies"}
    if require_submission_state:
        required.add("submission_state")
    if require_current_script:
        required.add("current_script")
    # Optional material that was actually read must also remain consistent.
    parts = required | (set(read_versions) - {"submission_state"})
    stale = sorted(part for part in parts if not input_digest or read_versions.get(part) != input_digest)
    if not stale:
        return None
    result = _failure("inputDigest", "stale_context", "创作资料尚未读取或版本已变化，请重新读取所列资料并按最新内容修订", "reread_context")
    result["requiredParts"] = stale
    return result


def get_cinematic_script_context(project_id: str, episode_id: str, node_id: str, *,
                                 user_instruction: str = "", preferred_template_id: str = "",
                                 part: str, read_versions: dict[str, str] | None = None) -> dict[str, Any]:
    """Expose a versioned generation bundle or a scoped legacy read."""
    fields = {
        "source_fragment": ("sourceFactText", "sourceFactText"),
        "novel_context": ("novelExcerpt", "novelExcerpt"),
        "previous_script": ("previousCinematicStoryText", "previousCinematicStoryText"),
        "strategies": ("scriptTemplates", "scriptTemplates"),
        "current_script": ("currentCinematicStoryText", "currentCinematicStoryText"),
    }
    if part not in {*fields, "generation_bundle", "submission_state"}:
        return _failure("part", "invalid_part", "请选择剧本创作资料包或所需单项资料", "stop")
    try:
        context, _ = _inputs(project_id, episode_id, node_id, _normalize_multiline_text(user_instruction), preferred_template_id)
    except (ValueError, FileNotFoundError, OSError) as exc:
        return _failure("nodeId", "context_unavailable", str(exc), "stop")
    if part == "generation_bundle":
        return {
            "success": True,
            "generationBundle": copy.deepcopy(context),
            "contextVersion": context["inputDigest"],
        }
    if part == "submission_state":
        if read_versions is not None:
            failure = validate_cinematic_script_reads(
                read_versions, context["inputDigest"],
                require_current_script=bool(context.get("currentCinematicStoryText")),
            )
            if failure:
                return failure
        return {"success": True, "submissionState": {
            "inputDigest": context["inputDigest"],
            "defaultScriptTemplateId": context["defaultScriptTemplateId"],
            "narrativeMode": context.get("narrativeMode", "drama"),
        }}
    source_key, public_key = fields[part]
    result = {"success": True, public_key: copy.deepcopy(context[source_key]), "contextVersion": context["inputDigest"]}
    if part == "source_fragment":
        result["narrativeMode"] = context.get("narrativeMode", "drama")
        result["hasCurrentScript"] = bool(context.get("currentCinematicStoryText"))
        result["hasPreviousScript"] = bool(context.get("previousCinematicStoryText"))
    return result


def submit_cinematic_script_result(
    project_id: str,
    episode_id: str,
    node_id: str,
    cinematic_story_text: Any,
    script_template_id: str,
    input_digest: str,
    *,
    user_instruction: str,
    session_id: str,
    execution_id: str,
    preferred_template_id: str = "",
    delivery_contract: Any = None,
) -> dict[str, Any]:
    """Commit one Agent result through the existing node writer; no model call here."""
    if not str(episode_id or "").strip():
        return _failure("episodeId", "required", "缺少 episodeId", "stop")
    if not str(node_id or "").strip():
        return _failure("nodeId", "required", "缺少 nodeId", "stop")
    if not isinstance(cinematic_story_text, str) or not _normalize_multiline_text(cinematic_story_text):
        return _failure("cinematicStoryText", "required", "影视化剧本正文不能为空", "revise_and_resubmit")
    if _EDITORIAL_SCRIPT_LINE.search(cinematic_story_text):
        return _failure("cinematicStoryText", "editorial_text_not_supported",
                        "当前剧情演绎剧本不生成编辑层装饰文字，请删除旧字卡行后重提", "revise_and_resubmit")
    if not str(script_template_id or "").strip():
        return _failure("scriptTemplateId", "required", "缺少创作策略 ID", "revise_and_resubmit")
    if not str(input_digest or "").strip():
        return _failure("inputDigest", "required", "缺少读取上下文返回的 inputDigest", "reread_context")
    if preferred_template_id and script_template_id != preferred_template_id:
        return _failure("scriptTemplateId", "strategy_mismatch", "创作策略与本轮结构化任务不一致", "revise_and_resubmit")
    if not session_id or not execution_id:
        return _failure("executionId", "execution_unavailable", "当前智能体执行轮次已失效", "stop")

    instruction = _normalize_multiline_text(user_instruction)
    try:
        context, writer = _inputs(project_id, episode_id, node_id, instruction, preferred_template_id)
    except (ValueError, FileNotFoundError, OSError) as exc:
        return _failure("nodeId", "context_unavailable", str(exc), "reread_context")
    if context["inputDigest"] != input_digest:
        return _failure("inputDigest", "stale_context", "创作输入已改变，请重新读取目标片段并修改结果", "reread_context")
    media_exposition_issue = _media_exposition_budget_issue(cinematic_story_text)
    if media_exposition_issue:
        return _failure("cinematicStoryText", "media_exposition_overload", media_exposition_issue,
                        "revise_and_resubmit")
    templates = context["scriptTemplates"]
    if not any(item.get("id") == script_template_id for item in templates):
        return _failure("scriptTemplateId", "unknown_strategy", "创作策略 ID 不在当前模板目录中", "revise_and_resubmit")
    normalized_contract = None
    if delivery_contract is not None:
        normalized_contract, errors = normalize_script_delivery_contract(
            delivery_contract, source_text=context["sourceFactText"],
            script_text=cinematic_story_text, user_instruction=instruction,
        )
        if errors:
            return {
                "success": False, "status": "validation_failed",
                "message": "剧本信息交付契约有误，请按字段修订",
                "errors": errors, "projectChanged": False,
            }

    try:
        writer.script_template = copy.deepcopy(next(item for item in templates if item["id"] == script_template_id))
        writer.input_sample["scriptTemplateId"] = script_template_id
        writer.cinematic_story_text = _normalize_multiline_text(cinematic_story_text)
        writer.script_delivery_contract = normalized_contract
        writer.persist_user_instruction = True
        writer.expected_previous_script = context.get("previousCinematicStoryText", "")
        writer.model_meta = {
            "source": "agent_sdk",
            "contextEpisodeIds": writer.context_episodes,
            "contextKind": "independent_source" if writer.independent_source_id else "episode",
            "sessionId": session_id,
            "executionId": execution_id,
        }
        writer._commit_script()
        save_result = writer._record_history_and_respond()
    except (ValueError, FileNotFoundError, OSError) as exc:
        message = str(exc)
        repair_action = "stop" if "锁定" in message else "reread_context"
        return _failure("nodeId", "commit_conflict", message, repair_action)

    try:
        stored = read_canvas_card_record_v4(project_id, episode_id, node_id, detail="full")
        stored_data = stored.get("data") if isinstance(stored.get("data"), dict) else {}
        if _normalize_multiline_text(stored_data.get("cinematicStoryText")) != writer.cinematic_story_text:
            raise RuntimeError("剧本已提交但回读正文不一致，请检查节点状态")
        if stored_data.get("scriptTemplateId") != script_template_id:
            raise RuntimeError("剧本已提交但回读创作策略不一致，请检查节点状态")
        if stored_data.get("scriptDeliveryContract") != normalized_contract:
            raise RuntimeError("剧本已提交但回读信息交付契约不一致，请检查节点状态")
    except (ValueError, RuntimeError, FileNotFoundError, OSError) as exc:
        result = _failure("nodeId", "commit_unverified", str(exc), "stop")
        result.update({
            "status": "commit_unverified",
            "projectChanged": True,
            "changedResources": save_result.get("changedResources") or ["canvas_node"],
            "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id},
            "txId": save_result.get("txId"),
            "workflowVersion": save_result.get("workflowVersion"),
        })
        return result

    output_digest = cinematic_script_output_digest(writer.cinematic_story_text, delivery_contract)
    receipt_id = _digest({
        "executionId": execution_id,
        "nodeId": node_id,
        "inputDigest": input_digest,
        "outputDigest": output_digest,
    })
    receipt = {
        "receiptId": receipt_id,
        "runId": execution_id,
        "projectId": project_id,
        "episodeId": episode_id,
        "sessionId": session_id,
        "executionId": execution_id,
        "taskType": "workflow_cinematic_script_generation",
        "scriptTemplateId": script_template_id,
        "changedResources": save_result.get("changedResources") or ["canvas_node"],
        "targetIds": [node_id],
        "inputDigest": input_digest,
        "outputDigest": output_digest,
    }
    return {
        "success": True,
        "status": "committed",
        "episodeId": episode_id,
        "nodeId": node_id,
        "scriptTemplateId": script_template_id,
        "receiptId": receipt_id,
        "commitReceipt": receipt,
        "changedResources": receipt["changedResources"],
        "projectChanged": True,
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id},
        "workflowVersion": save_result.get("workflowVersion"),
        "txId": save_result.get("txId"),
        "seq": save_result.get("seq"),
        "revision": save_result.get("revision"),
        **{key: copy.deepcopy(save_result[key]) for key in (
            "productionStatusRefreshFailed", "productionStatusWarning", "productionWarnings",
        ) if key in save_result},
    }
