# -*- coding: utf-8 -*-
"""SDK tool execution: request policy, domain dispatch and per-turn outcomes."""
from __future__ import annotations

import copy
import re
import uuid
from dataclasses import dataclass, replace
from threading import Event, Lock
from typing import Any

from .agent_tool_results import (
    _agent_raw_diagnostic_text, _sdk_tool_result_is_business_feedback,
    _sdk_tool_read_observation, _sdk_tool_result_summary,
)
from .agent_turn_stream import AgentTurnStream
from .video_prompt_submission import video_prompt_result_fields


from .agent_asset_range_state import (
    _ASSET_RANGE_ANALYSIS_COMPLETED_STATUSES,
    _agent_asset_range_analysis_status,
    _agent_asset_range_user_label,
)
from .agent_canvas_events import (
    _canvas_mutation_event_fields,
    _canvas_mutation_event_payload,
    _canvas_mutation_payload,
    _merge_changed_resources,
)
from .agent_contracts import (
    AGENT_MEDIA_GENERATION_TOOLS,
    _AGENT_PRODUCTION_STEP_STATES,
    _agent_task_pending_action,
)
from .agent_file_tools import (
    list_project_files_for_agent,
    read_project_file_for_agent,
    run_project_media_tool,
    search_project_files_for_agent,
)
from .agent_operation_catalog import (
    agent_operation_expected_tool,
    agent_operation_reply,
)
from .agent_output_validation import (
    _agent_focus_workflow_node_id,
    validate_project_quality,
)
from .agent_pending_operations import (
    _agent_current_message_allows_model_user_instruction,
    _agent_message_confirms_destructive_operation,
    _agent_pending_operation_from_tool_result,
    _agent_pending_operation_kind,
    _agent_pending_operation_revision_instruction,
    _agent_without_user_instruction_fields,
)
from .agent_production_scope import (
    _agent_current_flow_asset_image_keys,
    _agent_generation_flow_step_hypothesis,
)
from .agent_requirements import (
    _agent_empty_extracted_requirements,
    _agent_extract_work_requirements,
    _agent_program_work_effective_instruction,
    _agent_work_definition,
)
from .agent_session_policy import (
    validate_agent_session_task_type,
    validate_agent_session_tool_allowed,
    validate_agent_tool_episode_scope,
    validate_project_planning_delete_for_session,
)
from .agent_sessions import (
    _agent_log_sanitize,
    _load_agent_sessions,
    _save_agent_sessions,
    _normalize_agent_message_rows,
    _normalize_agent_history_summary,
    append_agent_execution_error,
)
from .agent_action_contract import _agent_validate_task_type
from .assets import (
    _asset_design_prompt_from_asset,
    delete_all_project_assets,
    delete_asset,
    start_asset_media_generation,
)
from .director_rules import (
    list_director_rules_for_agent,
    read_director_rule_for_agent,
    search_director_rules_for_agent,
)
from .asset_text_ingestion import upsert_asset
from .episode_plan_documents import save_episode_work_chain_plan, save_story_world_map
from .generation_input_context import _generation_user_instruction
from .generation_requests import request_route_video_generation
from .shot_prompt_updates import patch_shot_prompt
from .project_management import (
    save_project_settings,
)
from .runtime_state import (
    AgentTurnCancelled,
    _LOCK,
    _raise_if_agent_cancelled,
)
from utils.agent_execution_state import current_execution_id
from .agent_asset_range_tools import get_asset_range_context, submit_asset_range_candidate
from .agent_asset_range_confirmation import confirm_asset_range_locally
from .agent_asset_extraction_tools import (
    get_asset_extraction_context,
    get_asset_extraction_asset_catalog,
    submit_asset_extraction_result,
)
from .episode_boundary_planning import submit_episode_boundary_candidate
from .agent_episode_confirmation import confirm_episode_boundary_locally
from .project_resource_revisions import _json_hash
from .agent_plot_split_tools import get_plot_split_context, submit_plot_split_candidate
from .agent_cinematic_script_tools import (
    cinematic_script_output_digest,
    validate_cinematic_script_reads,
    get_cinematic_script_context,
    submit_cinematic_script_result,
)
from .agent_director_plan_tools import (
    director_plan_submission_digest,
    get_director_plan_context,
    submit_director_plan_result,
    validate_director_plan_draft,
)
from .canvas_store_queries import read_canvas_card_record_v4
from .agent_node_version_tools import list_workflow_node_versions, read_workflow_node_version
from .agent_video_prompt_tools import (
    get_video_prompt_context,
    submit_video_prompt_result,
    video_prompt_submission_digest,
)
from .agent_video_prompt_optimization_tools import (
    read_video_prompt_edit_digest,
    get_video_prompt_optimization_context,
    get_video_prompt_standalone_context,
    submit_video_prompt_optimization_result,
    submit_video_prompt_standalone_result,
)
from .source_coverage import get_source_coverage
from .agent_episode_boundary_tools import get_episode_boundary_context
from .source_index import read_source_window, search_source_text
from .store_core import (
    _emit_agent_event,
)
from .workflow_canvas_creation import add_workflow_asset_nodes, create_workflow_task_card
from .workflow_canvas_deletion import delete_workflow_item
from .workflow_inline_editing import save_workflow_node_inline_edit
from .workflow_canvas_updates import update_workflow_route, upsert_workflow_node
from .workflow_planning_lifecycle import (
    delete_project_planning_outputs,
)
from .workflow_projection import (
    build_episode_workflow_from_work_chain_plan,
    get_canvas_workflow_projection,
)
from .workflow_input_links import (
    link_workflow_input,
    list_workflow_inputs,
    unlink_workflow_input,
)

_VIDEO_PROMPT_TOOL_TASKS = {
    "get_video_prompt_context": "video_prompt_generation",
    "submit_video_prompt_result": "video_prompt_generation",
    "get_video_prompt_optimization_context": "video_prompt_optimization",
    "submit_video_prompt_optimization_result": "video_prompt_optimization",
    "get_video_prompt_standalone_context": "video_prompt_standalone_generation",
    "submit_video_prompt_standalone_result": "video_prompt_standalone_generation",
}

PRODUCTION_STEP_TOOLS = {
    "video_prompt_generation": "submit_video_prompt_result",
    "video_prompt_optimization": "submit_video_prompt_optimization_result",
    "video_prompt_standalone_generation": "submit_video_prompt_standalone_result",
    "asset_image_generation": "request_asset_image_generation",
    "storyboard_image_generation": "request_storyboard_image_generation",
    "visual_handoff_image_generation": "request_visual_handoff_image_generation",
    "storyboard_video_generation": "request_storyboard_video_generation",
}

BUSINESS_TASK_HANDOFF_TYPES = frozenset({
    "overview_request",
    "storyboard_image_generation",
    "visual_handoff_image_generation",
    "storyboard_video_generation",
    "asset_range_delete_latest",
    "project_cleanup",
})

PRODUCTION_WRITE_TOOLS = {
    "submit_video_prompt_result",
    "submit_video_prompt_optimization_result",
    "submit_video_prompt_standalone_result",
    "request_asset_image_generation",
    "request_storyboard_image_generation",
    "request_visual_handoff_image_generation",
    "request_storyboard_video_generation",
}

DESTRUCTIVE_DIRECT_WRITE_TOOLS = {
    "delete_asset",
    "delete_workflow_node",
    "unlink_workflow_input",
}


@dataclass(frozen=True)
class AgentToolContext:
    project_id: str
    episode_id: str | None
    session_id: str | None
    message: str
    images: list[dict[str, Any]] | None
    state: dict[str, Any]
    task_hypothesis: dict[str, Any]
    task_type: str
    runtime_config: dict[str, Any]
    cancel_event: Event | None
    session_policy: dict[str, Any] | None
    allowed_tools: list[str]
    pending_operation_context: dict[str, Any]
    pending_confirmation_requested: bool
    task_options: dict[str, Any] | None = None
    active_target: dict[str, Any] | None = None


def validate_director_plan_target(project_id: str, task_type: str, active_target: Any,
                                  selected_episode_id: str, node_id: str) -> None:
    target = active_target if isinstance(active_target, dict) else {}
    target_node_id = str(target.get("nodeId") or "").strip()
    target_episode_id = str(target.get("episodeId") or "").strip()
    trusted_source = str(target.get("source") or "").strip() in {"storyboard_canvas", "agent_recommendation"}
    director_node = str(target.get("nodeType") or "").strip() == "director.board"
    if task_type == "director_plan_generation":
        if not (trusted_source and director_node and target_node_id and target_episode_id
                and str(target.get("workChainId") or "").strip()
                and str(target.get("routeId") or "").strip()):
            raise ValueError("结构化任务缺少可信分镜脚本目标；请从当前分集画布重新发起")
        if selected_episode_id != target_episode_id or node_id != target_node_id:
            raise ValueError("工具目标与本轮结构化任务的分镜脚本目标不一致")
    elif trusted_source and director_node and target_node_id:
        if selected_episode_id != target_episode_id or node_id != target_node_id:
            raise ValueError("工具目标与当前对话锁定的分镜脚本不一致")
    else:
        return
    try:
        saved_node = read_canvas_card_record_v4(project_id, selected_episode_id, node_id, detail="summary")
    except FileNotFoundError as exc:
        raise ValueError("分镜脚本目标已不存在，请从当前分集画布重新发起") from exc
    target_route_id = str(target.get("routeId") or "").strip()
    target_work_chain_id = str(target.get("workChainId") or "").strip()
    if (str(saved_node.get("type") or "").strip() != "director.board"
            or (target_route_id and str(saved_node.get("routeId") or "").strip() != target_route_id)
            or (target_work_chain_id and str(saved_node.get("workChainId") or "").strip() != target_work_chain_id)):
        raise ValueError("分镜脚本目标与当前画布的节点、线路或工作链不一致，请从当前分集画布重新发起")


def validate_video_prompt_target(project_id: str, task_type: str, active_target: Any,
                                 selected_episode_id: str, node_id: str) -> None:
    target = active_target if isinstance(active_target, dict) else {}
    target_episode_id = str(target.get("episodeId") or "").strip()
    target_node_id = str(target.get("nodeId") or "").strip()
    trusted = (str(target.get("source") or "").strip() in {"storyboard_canvas", "agent_recommendation"}
               and str(target.get("nodeType") or "").strip() == "video.storyboard")
    if task_type == "video_prompt_generation":
        if not (trusted and target_episode_id and target_node_id
                and str(target.get("workChainId") or "").strip()
                and str(target.get("routeId") or "").strip()):
            raise ValueError("结构化任务缺少可信视频生成目标；请从当前分集画布重新发起")
        if selected_episode_id != target_episode_id or node_id != target_node_id:
            raise ValueError("工具目标与本轮结构化任务的视频生成节点不一致")
    elif trusted and target_node_id:
        if selected_episode_id != target_episode_id or node_id != target_node_id:
            raise ValueError("工具目标与当前对话锁定的视频生成节点不一致")
    else:
        return
    try:
        saved_node = read_canvas_card_record_v4(project_id, selected_episode_id, node_id, detail="summary")
    except FileNotFoundError as exc:
        raise ValueError("视频生成目标已不存在，请从当前分集画布重新发起") from exc
    if (str(saved_node.get("type") or "").strip() != "video.storyboard"
            or str(saved_node.get("routeId") or "").strip() != str(target.get("routeId") or "").strip()
            or str(saved_node.get("workChainId") or "").strip() != str(target.get("workChainId") or "").strip()):
        raise ValueError("视频生成目标与当前画布的节点、线路或工作链不一致，请从当前分集画布重新发起")


class AgentTurnTools:
    def __init__(
        self,
        context: AgentToolContext,
        stream: AgentTurnStream,
        *,
        pending_operation_update: dict[str, Any] | None,
        pending_operation_should_clear: bool,
        initial_project_effect: dict[str, Any] | None,
    ):
        self.context = context
        self.stream = stream
        self.pending_operation_update = pending_operation_update
        self.pending_operation_should_clear = pending_operation_should_clear
        self._candidate_submission_lock = Lock()
        self._initial_project_effect = initial_project_effect
        self.results: list[dict[str, Any]] = []
        self.background_tasks: dict[str, dict[str, Any]] = {}
        self.last_tool_call: dict[str, Any] = {}
        self.business_task_handoff: dict[str, str] | None = None
        self.last_candidate_rejection: dict[str, Any] | None = None
        self.candidate_terminal_rejection: dict[str, Any] | None = None
        self.last_plot_split_submission: dict[str, Any] | None = None
        self._asset_range_read_versions: dict[tuple[str, str, str], dict[str, str]] = {}
        self._episode_boundary_read_versions: dict[str, dict[str, str]] = {}
        self._episode_boundary_target: tuple[str, str, int] | None = None
        self._episode_boundary_target_conflict = False
        self._asset_extraction_read_versions: dict[str, dict[str, str]] = {}
        self._cinematic_script_read_versions: dict[tuple[str, str], dict[str, str]] = {}
        self._commit_receipts: dict[str, dict[str, Any]] = {}
        self._boundary_completion_reports: dict[str, str] = {}
        self._director_plan_validated_drafts: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self._director_plan_input_digests: dict[tuple[str, str], str] = {}
        self._published_reports: dict[str, dict[str, Any]] = {}
        self.last_published_report: str | None = None
        self.last_published_receipt: dict[str, Any] | None = None
        self._production_step_write_tool = ''
        self._asset_context_ready = context.task_type == "asset_extraction"
        self._video_prompt_saved_edit_digest = ""
        self._video_prompt_target_lock = Lock()
        self._video_prompt_input_digests: dict[tuple[str, str, str], str] = {}
        if context.task_type == "video_prompt_optimization":
            target = context.active_target or {}
            try:
                self._video_prompt_saved_edit_digest = read_video_prompt_edit_digest(
                    context.project_id, str(target.get("episodeId") or ""),
                    str(target.get("nodeId") or ""),
                )
            except (ValueError, FileNotFoundError, OSError):
                # An unavailable initial target cannot become a valid baseline
                # later in the same turn. Normal target/context errors still
                # report through the tools rather than failing construction.
                self._video_prompt_saved_edit_digest = "unavailable"

    def _project_file_trusted_scope(self) -> str | None:
        return "asset_context" if self._asset_context_ready else None

    @property
    def last_committed_receipt(self) -> dict[str, Any] | None:
        receipts = list(self._commit_receipts.values())
        return copy.deepcopy(receipts[-1]) if receipts else None

    def request(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name in {
            "submit_episode_boundary_candidate",
            "submit_plot_split_candidate",
            "submit_asset_range_candidate",
        }:
            # SDK MCP handlers may run in parallel. Keep the pending check and
            # the durable candidate write in the same critical section.
            with self._candidate_submission_lock:
                if self.pending_operation_update:
                    return {
                        "success": False,
                        "status": "awaiting_confirmation",
                        "message": "候选已暂存，请等待用户决定。",
                    }
                receipt = self.last_committed_receipt
                expected_task_type = {
                    "submit_episode_boundary_candidate": "episode_boundary_propose",
                    "submit_asset_range_candidate": "asset_range_propose",
                }.get(tool_name)
                if receipt and expected_task_type and receipt.get("taskType") == expected_task_type:
                    return {
                        "success": True, "status": "committed", "alreadyCommitted": True,
                        "message": "本轮结果已写入项目。", "receiptId": receipt["receiptId"],
                        "commitReceipt": receipt, "projectChanged": False,
                    }
                return self._request_unlocked(tool_name, args)
        return self._request_unlocked(tool_name, args)

    def _request_unlocked(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if self.context.cancel_event is not None and self.context.cancel_event.is_set():
            raise AgentTurnCancelled()
        _raise_if_agent_cancelled(self.context.session_id)
        if not isinstance(args, dict):
            args = {}
        stream_tool_id = f"tool-{uuid.uuid4().hex[:8]}"
        self.last_tool_call = {
            "tool": tool_name,
            "args": _agent_log_sanitize(args),
            "streamToolId": stream_tool_id,
        }
        self.stream.append(
            [
                {
                    "type": "tool_use",
                    "id": stream_tool_id,
                    "name": tool_name,
                    "input": args if isinstance(args, dict) else {},
                }
            ],
            force=True,
        )

        try:
            args, selected_episode_id, node_id, user_instruction = self._prepare_request(tool_name, args)
            handler = self._handlers.get(tool_name)
            if handler is None:
                raise ValueError("未知 ai-video SDK 工具")
            if tool_name.startswith(("submit_", "validate_")):
                from .agent_canvas_task_progress import track_agent_canvas_stage
                track_agent_canvas_stage(
                    self.context.project_id, self.context.session_id, selected_episode_id,
                    node_id, tool_name, task_type=self.context.task_type,
                )
            result, args = handler(self, args, selected_episode_id, node_id, user_instruction)
            return self._record_result(tool_name, args, selected_episode_id, stream_tool_id, result)
        except ValueError as exc:
            error = str(exc).splitlines()[0].strip()
            error = re.sub(r"[A-Za-z]:[\\/][^\s,;，；]+", "[路径]", error)
            error = re.sub(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*\S+", "[敏感值]", error)
            self.results.append({"tool": tool_name, "success": False,
                                 "status": "validation_error", "error": error[:260]})
            raise

    def _tool_arg(self, args: dict[str, Any], *keys: str, default: str = "") -> str:
        for key in keys:
            value = args.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return default


    def _tool_user_instruction(self, args: dict[str, Any]) -> str:
        return _generation_user_instruction(args) or str(self.context.message or "").strip()




    def _agent_settings_update_guard(self, args: dict[str, Any], instruction: str) -> dict[str, Any] | None:
        settings = args.get("settings") if isinstance(args.get("settings"), dict) else args
        if not isinstance(settings, dict):
            return None
        split_key_tools = {
            "episodeTargetUnits": "submit_episode_boundary_candidate",
            "episode_target_units": "submit_episode_boundary_candidate",
            "assetExtractionTargetUnits": "get_asset_range_context",
            "asset_extraction_target_units": "get_asset_range_context",
        }
        touched_tools = [
            tool
            for key, tool in split_key_tools.items()
            if key in settings and str(settings.get(key) or "").strip()
        ]
        if not touched_tools:
            return None
        intent_text = "\n".join(
            str(value or "")
            for value in (
                instruction,
                args.get("userInstruction"),
                args.get("user_instruction"),
                args.get("reason"),
                args.get("summary"),
                settings.get("userInstruction"),
                settings.get("user_instruction"),
                settings.get("reason"),
                settings.get("summary"),
                self.context.message,
            )
        )
        ephemeral_intent = re.search(
            r"(本次|这次|此次|当前阶段|这一轮|这轮|临时|暂时).{0,16}(按|用|改|设|配置|拆|提取)",
            intent_text,
            flags=re.IGNORECASE,
        )
        if ephemeral_intent:
            persistent_intent = None
        else:
            persistent_intent = re.search(
                r"(默认|默认值|项目默认|以后|后续|固定|长期|永久|保存为|设为默认|作为默认|保存默认|写入配置|"
                r"项目配置|更新配置|修改配置|配置成|配置为|"
                r"当前项目.*(改|设|调整|保存|更新|配置)|(改|设|调整|保存|更新|配置).*当前项目|"
                r"\bdefault\b|\bpersist\w*\b|\bsave\b.*\bsettings\b|\bproject settings\b|\bconfiguration\b)",
                intent_text,
                flags=re.IGNORECASE,
            )
        if persistent_intent:
            return None
        next_tools = list(dict.fromkeys(touched_tools))
        touched_episode = "submit_episode_boundary_candidate" in next_tools
        touched_asset = "get_asset_range_context" in next_tools
        if touched_episode and touched_asset:
            message_text = (
                "分集断点按项目设置的目标字数规划；本次资产范围的目标字数可传给 get_asset_range_context.targetUnits。"
            )
            reason_text = (
                "分集目标字数由项目设置控制；资产范围的临时字数可留在提案工具参数里。"
            )
            example_text = (
                "分集断点：按项目设置调用 submit_episode_boundary_candidate；"
                "资产范围：get_asset_range_context(targetUnits=N) 读取资料后提交候选。"
            )
        elif touched_episode:
            message_text = (
                "分集断点按项目设置的目标字数规划；如需改变字数，请先调整项目设置。"
            )
            reason_text = (
                "提案工具不接收对话中的临时分集字数，避免与正文范围不一致。"
            )
            example_text = "调整项目设置后，调用 submit_episode_boundary_candidate。"
        else:
            message_text = "请改用 get_asset_range_context 的 targetUnits 参数读取本次范围资料。"
            reason_text = "update_project_settings 会持久修改项目默认配置；临时资产范围字数变化应留在提案工具参数里。"
            example_text = "调用 get_asset_range_context(targetUnits=N)，再调用 submit_asset_range_candidate。"
        return {
            "success": False,
            "error": "本次请求看起来只是临时拆分字数，已阻止智能体写入项目默认配置。",
            "message": message_text,
            "recoveryAdvice": {
                "reason": reason_text,
                "nextAllowedTools": next_tools,
                "example": example_text,
            },
            "nextAllowedTools": next_tools,
            "projectChanged": False,
        }


    def _prepare_program_work_instruction(self,
        work_name: str,
        instruction: str,
        *,
        include_message_as_instruction: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        explicit_instruction = str(instruction or "").strip()
        current_message = str(self.context.message or "").strip()
        extractor_message = explicit_instruction or current_message
        base_instruction = explicit_instruction or (current_message if include_message_as_instruction else "")
        extracted = _agent_extract_work_requirements(
            self.context.project_id,
            self.context.session_id,
            work_name,
            extractor_message,
            self.context.runtime_config,
            cancel_event=self.context.cancel_event,
        )
        return _agent_program_work_effective_instruction(base_instruction, extracted), extracted


    def project_effect(self) -> dict[str, Any] | None:
        changed_resources: list[str] = []
        focus_target: dict[str, Any] | None = None
        notices: list[str] = []
        project_changed = False
        base_effect = self._initial_project_effect if isinstance(self._initial_project_effect, dict) else {}
        if base_effect:
            project_changed = bool(base_effect.get("projectChanged"))
            resources = base_effect.get("changedResources")
            if isinstance(resources, list):
                changed_resources.extend(str(resource) for resource in resources if str(resource).strip())
            if isinstance(base_effect.get("focusTarget"), dict):
                focus_target = base_effect.get("focusTarget")
            notice = str(base_effect.get("notice") or "").strip()
            if notice:
                notices.append(notice)
        for item in self.results:
            if not isinstance(item, dict):
                continue
            if item.get("projectChanged"):
                project_changed = True
            resources = item.get("changedResources")
            if isinstance(resources, list):
                changed_resources.extend(str(resource) for resource in resources if str(resource).strip())
            if isinstance(item.get("focusTarget"), dict):
                focus_target = item.get("focusTarget")
            message_text = str(item.get("message") or "").strip()
            if message_text:
                notices.append(message_text)
        changed_resources = list(dict.fromkeys(changed_resources))
        if not project_changed and not changed_resources and not focus_target:
            return None
        mutation_fields = _canvas_mutation_event_payload(
            *self.results,
            fallback_changed_resources=changed_resources,
        )
        if not focus_target:
            if any(resource in changed_resources for resource in ("episodes", "script", "storyboard")):
                current_episode_id = str(self.context.state.get("selectedEpisodeId") or self.context.episode_id or "E01")
                focus_target = {
                    "section": "episode",
                    "episodeId": current_episode_id,
                    "nodeId": _agent_focus_workflow_node_id(self.context.project_id, current_episode_id),
                }
            elif changed_resources:
                first = changed_resources[0]
                focus_target = {"section": first, "assetTab": first} if first in {"characters", "creatures", "scenes", "props"} else {"section": first}
        effect = {
            "projectChanged": project_changed,
            **mutation_fields,
            "changedResources": mutation_fields.get("changedResources") or changed_resources,
            "focusTarget": focus_target or {},
            "notice": notices[-1] if notices else "智能体已保存文本结果",
        }
        for key in ("action", "pendingOperationKind"):
            if base_effect.get(key) and key not in effect:
                effect[key] = base_effect[key]
        return effect


    def attach_pending_operation(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.pending_operation_update is not None or self.pending_operation_should_clear:
            payload["pendingOperation"] = self.pending_operation_update
        return payload


    def _prepare_request(self, tool_name: str, args: dict[str, Any]) -> tuple[dict[str, Any], str, str, str]:
        if tool_name in {
            "patch_project_resource",
            "create_resource_revision",
        }:
            raise ValueError(
                "该写入入口未开放。请使用本轮允许的领域工具；若没有适用工具，说明当前阻碍。"
            )
        allowed_tool_names = {
            str(item or "").replace("mcp__ai_video__", "").strip()
            for item in (self.context.allowed_tools or [])
            if str(item or "").strip()
        }
        if tool_name not in allowed_tool_names:
            raise ValueError("当前任务不允许调用该 MCP 工具；请按本轮 allowed_tools 重新选择工具或先澄清用户意图。")
        if self.context.task_hypothesis.get("mediaGenerationDenied") and tool_name in AGENT_MEDIA_GENERATION_TOOLS:
            raise ValueError("用户本轮没有要求生成媒体，或已明确要求不生成图片/视频；已阻止媒体生成工具调用。")
        if self.context.task_hypothesis.get("destructiveToolsDenied") and tool_name in DESTRUCTIVE_DIRECT_WRITE_TOOLS:
            raise ValueError("用户本轮没有明确要求删除或移除；已阻止删除/移除类工具调用。")
        validate_agent_session_tool_allowed(tool_name, self.context.session_policy)
        if tool_name in {"delete_all_project_assets", "delete_project_planning_outputs"}:
            raise ValueError("删除项目数据必须先生成待确认操作，并由用户点击确认后交给本地控制器执行；智能体工具不能直接删除。")
        if tool_name == "delete_project_planning_outputs":
            validate_project_planning_delete_for_session(self.context.project_id, args, self.context.session_policy)
        if tool_name in _VIDEO_PROMPT_TOOL_TASKS:
            with self._video_prompt_target_lock:
                args = self._bind_video_prompt_target(tool_name, args)
        selected_episode_id = self._tool_arg(
            args,
            "episodeId",
            "episode_id",
            default=str(self.context.state.get("selectedEpisodeId") or self.context.episode_id or "E01"),
        )
        validate_agent_tool_episode_scope(tool_name, selected_episode_id, self.context.session_policy)
        node_id = self._tool_arg(args, "nodeId", "node_id", "targetNodeId", "target_node_id")
        expected_step_tool = PRODUCTION_STEP_TOOLS.get(self.context.task_type, "")
        enforce_current_flow_step = _agent_generation_flow_step_hypothesis(self.context.task_hypothesis)
        if expected_step_tool and tool_name == expected_step_tool:
            if self._production_step_write_tool:
                retry = False
                if tool_name in _VIDEO_PROMPT_TOOL_TASKS:
                    task_type = _VIDEO_PROMPT_TOOL_TASKS[tool_name]
                    fields, digest = self._video_prompt_submission_fields(args, task_type, selected_episode_id, node_id)
                    proposal = video_prompt_submission_digest(
                        fields["shots"], fields["usedSpeakerIds"], fields["voiceDesign"], fields["soundPrompt"],
                    )
                    retry = any(receipt.get("taskType") == task_type
                                and receipt.get("episodeId") == selected_episode_id
                                and receipt.get("targetIds") == [node_id]
                                and receipt.get("inputDigest") == digest
                                and receipt.get("submissionDigest") == proposal
                                for receipt in self._commit_receipts.values())
                if not retry:
                    raise ValueError("当前智能体回合已经执行过一个生产环节，请重新询问下一步后再继续。")
        if expected_step_tool and tool_name == expected_step_tool and enforce_current_flow_step:
            expected_episode_id = str(self.context.state.get("selectedEpisodeId") or self.context.episode_id or "").strip()
            if expected_episode_id and selected_episode_id != expected_episode_id:
                raise ValueError("只能执行当前集当前工作链的当前环节，不能跨集生成。")
            production_status = self.context.state.get("productionStatus") if isinstance(self.context.state.get("productionStatus"), dict) else {}
            required_state = _AGENT_PRODUCTION_STEP_STATES.get(self.context.task_type, "")
            current_state = str(
                self.context.task_hypothesis.get("productionState")
                or production_status.get("currentState")
                or ""
            ).strip()
            allowed_required_states = {required_state} if required_state else set()
            if required_state and current_state not in allowed_required_states:
                current_action = str(production_status.get("nextAction") or "").strip()
                raise ValueError(
                    f"当前工作链还不能执行该环节；下一步是：{current_action or current_state or '检查当前工作链状态'}。"
                )
            expected_route_id = str(
                self.context.task_hypothesis.get("currentRouteId")
                or production_status.get("currentRouteId")
                or ""
            ).strip()
            expected_work_chain_id = str(
                self.context.task_hypothesis.get("currentWorkChainId")
                or production_status.get("currentWorkChainId")
                or ""
            ).strip()
            requested_route_id = self._tool_arg(args, "routeId", "route_id")
            if expected_route_id and requested_route_id and requested_route_id != expected_route_id:
                raise ValueError("只能执行当前工作链的当前环节，不能跨工作链生成。")
            scope_workflow: dict[str, Any] | None = None
            if self.context.task_type == "asset_image_generation" and (expected_route_id or expected_work_chain_id):
                requested_asset_type = self._tool_arg(args, "assetType", "asset_type")
                requested_asset_id = self._tool_arg(args, "assetId", "asset_id")
                if requested_asset_type and requested_asset_id:
                    scope_workflow = get_canvas_workflow_projection(self.context.project_id, selected_episode_id)
                    allowed_asset_keys = _agent_current_flow_asset_image_keys(
                        scope_workflow,
                        expected_route_id,
                        expected_work_chain_id,
                    )
                    if allowed_asset_keys and (requested_asset_type, requested_asset_id) not in allowed_asset_keys:
                        raise ValueError("只能生成当前工作链引用的资产图，不能跨工作链生成。")
            if node_id and (expected_route_id or expected_work_chain_id):
                workflow = scope_workflow or get_canvas_workflow_projection(self.context.project_id, selected_episode_id)
                target_node = next(
                    (
                        item
                        for item in workflow.get("nodes") or []
                        if isinstance(item, dict) and str(item.get("id") or "") == node_id
                    ),
                    {},
                )
                node_data = target_node.get("data") if isinstance(target_node.get("data"), dict) else {}
                node_route_id = str(target_node.get("routeId") or node_data.get("routeId") or "").strip()
                node_work_chain_id = str(
                    target_node.get("workChainId") or node_data.get("workChainId") or ""
                ).strip()
                if expected_route_id and node_route_id and node_route_id != expected_route_id:
                    raise ValueError("只能执行当前工作链的当前环节，不能跨工作链生成。")
                if expected_work_chain_id and node_work_chain_id and node_work_chain_id != expected_work_chain_id:
                    raise ValueError("只能执行当前工作链的当前环节，不能跨工作链生成。")
        if tool_name in {"delete_all_project_assets", "delete_project_planning_outputs"} and not self._tool_arg(
            args,
            "userInstruction",
            "user_instruction",
        ):
            args["userInstruction"] = self.context.message
        user_instruction = self._tool_user_instruction(args)

        return args, selected_episode_id, node_id, user_instruction

    def _record_result(self, tool_name: str, args: dict[str, Any], selected_episode_id: str, stream_tool_id: str, result: dict[str, Any]) -> dict[str, Any]:
        from .agent_execution_traces import record_agent_eval_tool_io
        from .agent_canvas_task_progress import track_agent_canvas_stage

        if result.get("success"):
            track_agent_canvas_stage(
                self.context.project_id, self.context.session_id, selected_episode_id,
                self._tool_arg(args, "nodeId", "node_id"), tool_name,
                task_type=self.context.task_type, completed=result.get("status") == "committed",
            )
        record_agent_eval_tool_io(self.context.project_id, self.context.session_id,
                                 current_execution_id(self.context.session_id), stream_tool_id, tool_name, args, result)
        if tool_name.startswith("submit_") and result.get("success") and result.get("status") == "committed":
            receipt = result.get("commitReceipt")
            if not isinstance(receipt, dict):
                raise ValueError("提交已完成，但后端未返回可核验的提交回执；请停止本轮并检查任务状态。")
            receipt_id = str(receipt.get("receiptId") or "").strip()
            execution_id = current_execution_id(self.context.session_id)
            expected = {
                "projectId": self.context.project_id,
                "episodeId": self.context.episode_id,
                "sessionId": self.context.session_id,
                "executionId": execution_id,
            }
            if (not receipt_id or not execution_id or not str(receipt.get("taskType") or "").strip()
                    or any(str(receipt.get(key) or "") != str(value or "") for key, value in expected.items())):
                raise ValueError("提交回执与当前项目、分集、会话或执行轮次不符；已阻止发布完成报告。")
            if receipt_id in self._commit_receipts and self._commit_receipts[receipt_id] != receipt:
                raise ValueError("提交回执 ID 与本轮已有结果冲突；已阻止发布完成报告。")
            self._commit_receipts[receipt_id] = copy.deepcopy(receipt)
        if tool_name in {"submit_episode_boundary_candidate", "submit_plot_split_candidate", "submit_asset_range_candidate"}:
            if result.get("success"):
                self.last_candidate_rejection = None
                self.candidate_terminal_rejection = None
            else:
                self.last_candidate_rejection = copy.deepcopy(result)
                errors = result.get("errors") if isinstance(result.get("errors"), list) else []
                if any(isinstance(error, dict) and error.get("repairAction") == "stop" for error in errors):
                    self.candidate_terminal_rejection = copy.deepcopy(result)
        if tool_name == "submit_plot_split_candidate" and result.get("success"):
            self.last_plot_split_submission = copy.deepcopy(result)
        if tool_name in {"submit_episode_boundary_candidate", "submit_asset_range_candidate"} and result.get("status") == "committed":
            self.pending_operation_update = None
            self.pending_operation_should_clear = True
        next_pending_operation = _agent_pending_operation_from_tool_result(
            tool_name,
            result,
            session_id=self.context.session_id,
            user_message=getattr(self.context, "message", ""),
            previous_pending=getattr(self.context, "pending_operation_context", {}),
        )
        if next_pending_operation:
            self.pending_operation_update = next_pending_operation
            self.pending_operation_should_clear = False
        elif tool_name in {"submit_plot_split_candidate", "submit_asset_range_candidate", *DESTRUCTIVE_DIRECT_WRITE_TOOLS} and result.get("success") and isinstance(result.get("pendingOperation"), dict):
            self.pending_operation_update = copy.deepcopy(result["pendingOperation"])
            self.pending_operation_should_clear = False
        summary = _sdk_tool_result_summary(tool_name, result)
        read_observation = _sdk_tool_read_observation(
            tool_name, result, args,
            project_id=self.context.project_id,
            episode_id=selected_episode_id,
        )
        if read_observation is not None:
            summary["readObservation"] = read_observation
        if tool_name.startswith("submit_") and result.get("status") == "committed":
            summary["receiptId"] = str((result.get("commitReceipt") or {}).get("receiptId") or "")
        if tool_name == "publish_task_report" and result.get("success"):
            summary["reportId"] = result.get("reportId")
            summary["reportText"] = result.get("reportText")
        if tool_name == "get_plot_split_context" and result.get("success"):
            summary["plotSplitContext"] = copy.deepcopy(result)
        if tool_name == "get_episode_boundary_context" and result.get("success"):
            summary["episodeBoundaryContext"] = copy.deepcopy(result)
        if tool_name == "get_asset_range_context" and result.get("success"):
            summary["assetRangeContext"] = copy.deepcopy(result)
        if tool_name == "get_asset_extraction_context" and result.get("success"):
            summary["assetExtractionContext"] = copy.deepcopy(result)
        if tool_name == "get_cinematic_script_context" and result.get("success"):
            summary["cinematicScriptContext"] = copy.deepcopy(result)
        if tool_name in {"get_cinematic_script_context", "submit_cinematic_script_result"} and isinstance(result.get("requiredParts"), list):
            summary["requiredParts"] = copy.deepcopy(result["requiredParts"])
        if tool_name == "get_director_plan_context" and result.get("success"):
            summary["directorPlanContext"] = copy.deepcopy(result)
        if tool_name == "get_video_prompt_context" and result.get("success"):
            summary["videoPromptContext"] = copy.deepcopy(result)
        if tool_name == "get_video_prompt_optimization_context" and result.get("success"):
            summary["videoPromptOptimizationContext"] = copy.deepcopy(result)
        if tool_name == "get_video_prompt_standalone_context" and result.get("success"):
            summary["videoPromptStandaloneContext"] = copy.deepcopy(result)
        if tool_name == "submit_plot_split_candidate" and result.get("success"):
            summary["episodeId"] = result.get("episodeId")
            summary["itemCount"] = result.get("itemCount")
            summary["candidateId"] = result.get("candidateId")
            summary["requiresUserConfirmation"] = True
        if tool_name == "submit_asset_range_candidate" and result.get("success"):
            summary["candidateId"] = result.get("candidateId")
            summary["requiresUserConfirmation"] = bool(result.get("requiresUserConfirmation"))
        if tool_name == "read_source_window" and isinstance(result.get("sourceWindow"), dict):
            summary["sourceWindow"] = result["sourceWindow"]
        if tool_name == "search_source_text":
            summary.update({
                "query": result.get("query", ""),
                "searchedSourceCount": result.get("searchedSourceCount", 0),
                "totalMatches": result.get("totalMatches", 0),
                "matches": result.get("matches", []),
                "sampled": bool(result.get("sampled")),
            })
        if tool_name == "get_conversation_history":
            summary.update({
                "messages": result.get("messages") or [],
                "historySummary": result.get("historySummary") or "",
                "hasMore": bool(result.get("hasMore")),
                "nextBeforeMessageId": result.get("nextBeforeMessageId") or "",
            })
        if tool_name == "list_workflow_node_versions" and result.get("success"):
            summary.update({
                "nodeId": result.get("nodeId"), "nodeType": result.get("nodeType"),
                "total": result.get("total", 0), "items": result.get("items") or [],
                "offset": result.get("offset", 0), "hasMore": bool(result.get("hasMore")),
            })
        if tool_name == "read_workflow_node_version" and result.get("success"):
            summary.update({
                "nodeId": result.get("nodeId"), "nodeType": result.get("nodeType"),
                "versionId": result.get("versionId"),
                "versionNumber": result.get("versionNumber"),
                "content": result.get("content") or {}, "feedback": result.get("feedback") or "",
            })
        if "tasks" in result:
            summary["tasks"] = result["tasks"]
        if not bool(summary.get("success", True)):
            summary["rawArgs"] = copy.deepcopy(args)
        self.results.append(summary)
        if result.get("backgroundStarted"):
            # Preserve task records for session finalization; diagnostic summaries omit their ownership fields.
            child_tasks = result.get("tasks") if isinstance(result.get("tasks"), list) else []
            for child_task in [result.get("task"), *child_tasks]:
                if isinstance(child_task, dict) and child_task.get("id"):
                    self.background_tasks[str(child_task["id"])] = copy.deepcopy(child_task)
        if not bool(summary.get("success", True)) and not _sdk_tool_result_is_business_feedback(summary):
            raw_failure_payload = {
                "tool": tool_name,
                "args": copy.deepcopy(args),
                "result": copy.deepcopy(result),
                "summary": copy.deepcopy(summary),
                "streamToolId": stream_tool_id,
            }
            append_agent_execution_error(
                self.context.project_id,
                stage="mcp_tool_result",
                message="智能体工具返回失败结果",
                episode_id=selected_episode_id,
                session_id=self.context.session_id,
                category="mcp_tool_result_failed",
                source="agent_sdk_tool",
                tool=tool_name,
                error=summary.get("error") or summary.get("message") or "工具返回 success=false",
                details={
                    "args": args,
                    "summary": summary,
                    "streamToolId": stream_tool_id,
                },
            )
            self.stream.append(
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": stream_tool_id,
                        "content": _agent_raw_diagnostic_text(raw_failure_payload),
                        "is_error": True,
                        "contextExcluded": True,
                    }
                ],
                force=True,
            )
        # Business validation feedback is a rejected proposal, not a completed
        # production step. Allow repairs until a write succeeds or may have
        # happened; an unverified commit must still block blind retries.
        if tool_name in PRODUCTION_WRITE_TOOLS and (
            bool(summary.get("success", True)) or bool(result.get("projectChanged"))
            or result.get("status") == "commit_unverified"
        ):
            self._production_step_write_tool = tool_name
        if not bool(summary.get("success", True)) and _sdk_tool_result_is_business_feedback(summary):
            # Full arguments/results remain in self.results for diagnostics. The
            # model already has its submission; send only actionable feedback.
            return {key: value for key, value in summary.items() if key not in {"rawArgs", "rawResult"}}
        return summary


    def _run_read_source_window(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = read_source_window(
            self.context.project_id,
            args.get("sourceId"),
            args.get("chapterId"),
            args.get("offset") or 0,
            args.get("length") or args.get("limit") or 4000,
        )
        result = {"success": True, "sourceWindow": result}

        return result, args

    def _run_search_source_text(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = search_source_text(
            self.context.project_id,
            str(args.get("query") or ""),
            source_id=str(args.get("sourceId") or "").strip() or None,
            max_matches=args.get("maxMatches") or 8,
        )
        return result, args

    def _run_get_source_coverage(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = get_source_coverage(self.context.project_id, args.get("sourceId"))

        return result, args

    def _run_get_episode_boundary_context(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        target = str(args.get("episodeId") or "")
        if self._episode_boundary_target_conflict or (
                self._episode_boundary_target is not None and target != self._episode_boundary_target[0]):
            return self._episode_target_changed(), args
        result = get_episode_boundary_context(self.context.project_id, part=str(args.get("part") or ""), episode_id=target)
        if result.get("success"):
            resolved = result.get("target")
            if isinstance(resolved, dict):
                identity = (target, str(resolved["episodeId"]), int(resolved["absoluteStart"]))
                if self._episode_boundary_target is None:
                    self._episode_boundary_target = identity
                elif self._episode_boundary_target != identity:
                    self._episode_boundary_target_conflict = True
                    return self._episode_target_changed(), args
            self._episode_boundary_read_versions.setdefault(target, {})[str(args.get("part"))] = str(result["contextVersion"])
        return result, args

    @staticmethod
    def _episode_target_changed() -> dict[str, Any]:
        message = "本轮分集目标已被其他操作改变；为避免误改其他分集，本轮停止，未写入新的分集。请核对最新结果后再发起任务。"
        return {"success": False, "status": "blocked", "projectChanged": False,
                "code": "episode_target_changed", "message": message, "reason": message,
                "errors": [{"path": "episodeId", "code": "episode_target_changed",
                            "message": message, "repairAction": "stop"}]}

    def _run_get_conversation_history(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        session_id = str(self.context.session_id or "").strip()
        session = next((row for row in _load_agent_sessions(self.context.project_id)
                        if str(row.get("id") or "") == session_id), None)
        if not isinstance(session, dict):
            return {"success": True, "messages": [], "historySummary": "", "hasMore": False}, args
        messages = _normalize_agent_message_rows(session.get("messages"), self.context.project_id)
        before_id = str(args.get("beforeMessageId") or "").strip()
        if before_id:
            stop = next((index for index, row in enumerate(messages)
                         if str(row.get("id") or "") == before_id), len(messages))
            messages = messages[:stop]
        try:
            limit = max(1, min(20, int(args.get("limit") or 12)))
        except (TypeError, ValueError):
            limit = 12
        page = messages[-limit:]
        rows = [{
            "id": str(row.get("id") or ""),
            "role": str(row.get("role") or ""),
            "text": str(row.get("text") or "")[:1200],
            "createdAt": str(row.get("createdAt") or ""),
        } for row in page if row.get("role") in {"user", "assistant"}]
        return {
            "success": True, "messages": rows,
            "historySummary": _normalize_agent_history_summary(session.get("historySummary")),
            "hasMore": len(messages) > len(page),
            "nextBeforeMessageId": str(page[0].get("id") or "") if page else "",
        }, args

    def _node_version_target(self, selected_episode_id: str, node_id: str) -> str:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("节点修改记录只允许在目标分集会话中读取")
        if not node_id:
            raise ValueError("必须明确提供 nodeId")
        task_type = str(self.context.task_type or "")
        if task_type == "workflow_cinematic_script_generation":
            self._validate_script_stage_target(selected_episode_id, node_id, structured_task_type=task_type)
            return "prompt.storyboard"
        if task_type == "director_plan_generation":
            self._validate_director_plan_target(selected_episode_id, node_id)
            return "director.board"
        if task_type != "free_chat":
            raise ValueError("当前任务不能读取其他创作环节的修改记录")
        target = self.context.active_target if isinstance(self.context.active_target, dict) else {}
        if (target.get("source") in {"storyboard_canvas", "agent_recommendation"}
                and target.get("nodeType") in {"prompt.storyboard", "director.board"}
                and target.get("nodeId")):
            if (str(target.get("nodeId")) != node_id
                    or str(target.get("episodeId") or "") != selected_episode_id):
                raise ValueError("修改记录目标与当前对话锁定的节点不一致，请先明确要修改的节点")
            return str(target["nodeType"])
        return ""

    def _run_list_workflow_node_versions(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self._tool_arg(args, "episodeId") or not self._tool_arg(args, "nodeId"):
            raise ValueError("必须明确提供 episodeId 和 nodeId")
        expected_type = self._node_version_target(selected_episode_id, node_id)
        return list_workflow_node_versions(
            self.context.project_id, selected_episode_id, node_id,
            offset=args.get("offset", 0), limit=args.get("limit", 20), expected_type=expected_type,
        ), args

    def _run_read_workflow_node_version(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self._tool_arg(args, "episodeId") or not self._tool_arg(args, "nodeId"):
            raise ValueError("必须明确提供 episodeId 和 nodeId")
        expected_type = self._node_version_target(selected_episode_id, node_id)
        return read_workflow_node_version(
            self.context.project_id, selected_episode_id, node_id,
            version_id=str(args.get("versionId") or ""),
            version_number=int(args.get("versionNumber") or 0),
            expected_type=expected_type,
        ), args

    def _run_update_project_settings(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        settings = args.get("settings") if isinstance(args.get("settings"), dict) else args
        result = self._agent_settings_update_guard(args, user_instruction)
        if result is None:
            with _LOCK:
                if self.context.task_type in {"free_chat", "episode_boundary_propose"}:
                    self._require_current_running_execution()
                result = save_project_settings(self.context.project_id, settings or {})
            _emit_agent_event("project_changed", {"action": "settings_saved", "projectId": self.context.project_id})

        return result, args


    def _require_current_running_execution(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        _raise_if_agent_cancelled(self.context.session_id)
        execution_id = current_execution_id(self.context.session_id)
        sessions = _load_agent_sessions(self.context.project_id)
        owner = next((row for row in sessions if row.get("id") == self.context.session_id), None)
        if (not execution_id or owner is None
                or str((owner.get("execution") or {}).get("id") or "") != execution_id
                or owner.get("status") != "running"):
            raise AgentTurnCancelled()
        return owner, sessions

    def _run_submit_episode_boundary_candidate(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        with _LOCK:
            self._require_current_running_execution()
            if self._episode_boundary_target_conflict or (
                    self._episode_boundary_target is not None
                    and str(args.get("episodeId") or "") != self._episode_boundary_target[0]):
                return self._episode_target_changed(), args
            reads = self._episode_boundary_read_versions.get(str(args.get("episodeId") or ""), {})
            version = str(args.get("contextVersion") or "")
            if not version or any(reads.get(part) != version for part in ("source_text", "planning_state")):
                return {"success": False, "status": "rejected", "projectChanged": False,
                        "message": "请先读取同一目标、同一版本的正文和规划状态",
                        "errors": [{"path": "contextVersion", "code": "context_not_read",
                                    "message": "正文和规划状态须来自本轮同一版本", "repairAction": "refresh_context"}]}, args
            result = submit_episode_boundary_candidate(
                self.context.project_id, args, session_id=self.context.session_id,
                requirement_text=self.context.message,
            )
        if result.get("status") == "pending_confirmation" and result.get("candidateId"):
            confirmed = confirm_episode_boundary_locally(
                self.context.project_id, self.context.session_id, self.context.session_policy,
                candidate_ref=self._candidate_ref(result),
            )
            result = self._auto_committed_candidate_result(
                "episode_boundary_propose", result, confirmed,
                target_id=str((result.get("proposal") or {}).get("episodeId") or ""),
            )
        return result, args

    @staticmethod
    def _candidate_ref(staged: dict[str, Any]) -> dict[str, Any]:
        return {key: staged.get(key) for key in
                ("candidateId", "candidateDigest", "candidateVersion", "runId")}

    def _auto_committed_candidate_result(
        self, task_type: str, staged: dict[str, Any], confirmed: dict[str, Any], *, target_id: str,
    ) -> dict[str, Any]:
        if not confirmed.get("success"):
            message = str(confirmed.get("message") or "写入结果未能核验，请检查项目状态。")
            return {"success": False, "status": str(confirmed.get("status") or "commit_failed"),
                    "message": message, "projectChanged": bool(confirmed.get("projectChanged")),
                    "errors": [{"path": "commit", "code": "commit_unverified", "message": message,
                                "repairAction": "stop"}]}
        execution_id = str(current_execution_id(self.context.session_id) or "")
        candidate_id = str(staged.get("candidateId") or "")
        input_digest = str(staged.get("candidateDigest") or "")
        changed = list((confirmed.get("projectEffect") or {}).get("changedResources") or [])
        receipt = {
            "receiptId": _json_hash({"executionId": execution_id, "candidateId": candidate_id,
                                     "candidateDigest": input_digest}),
            "runId": execution_id, "projectId": self.context.project_id,
            "episodeId": str(self.context.episode_id or ""),
            "sessionId": str(self.context.session_id or ""), "executionId": execution_id,
            "taskType": task_type, "targetIds": [target_id],
            "inputDigest": input_digest, "outputDigest": _json_hash({
                "candidateId": candidate_id, "targetId": target_id, "changedResources": changed,
            }), "changedResources": changed,
        }
        report = str(confirmed.get("completionReport") or "").strip()
        if report:
            self._boundary_completion_reports[receipt["receiptId"]] = report
        return {
            "success": True, "status": "committed", "requiresUserConfirmation": False,
            "candidateId": candidate_id, "receiptId": receipt["receiptId"],
            "commitReceipt": receipt, "projectChanged": True,
            "projectEffect": confirmed.get("projectEffect") or {},
            "changedResources": changed, "message": str(confirmed.get("message") or "结果已写入项目。"),
        }

    def _run_get_plot_split_context(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("剧情拆分只允许在目标分集会话中执行")
        return get_plot_split_context(self.context.project_id, selected_episode_id,
                                      part=str(args.get("part") or "")), args

    def _run_submit_plot_split_candidate(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("剧情拆分只允许在目标分集会话中执行")
        with _LOCK:
            self._require_current_running_execution()
            result = submit_plot_split_candidate(
                self.context.project_id,
                selected_episode_id,
                args.get("segments"),
                session_id=str(self.context.session_id or ""),
                user_instruction=str(self.context.message or ""),
                previous_pending=self.context.pending_operation_context,
            )
        return result, args

    def _cinematic_script_instruction_and_strategy(self) -> tuple[str, str]:
        options = self.context.task_options if isinstance(self.context.task_options, dict) else {}
        instruction = str(options.get("userInstruction") or self.context.message or "")
        return instruction, str(options.get("scriptTemplateId") or "").strip()

    def _validate_script_stage_target(self, selected_episode_id: str, node_id: str, *, structured_task_type: str) -> None:
        target = self.context.active_target if isinstance(self.context.active_target, dict) else {}
        target_node_id = str(target.get("nodeId") or "").strip()
        target_episode_id = str(target.get("episodeId") or "").strip()
        trusted_source = str(target.get("source") or "").strip() in {"storyboard_canvas", "agent_recommendation"}
        prompt_node = str(target.get("nodeType") or "").strip() == "prompt.storyboard"
        if self.context.task_type == structured_task_type:
            if not (trusted_source and prompt_node and target_node_id and target_episode_id
                    and str(target.get("workChainId") or "").strip()
                    and str(target.get("routeId") or "").strip()):
                raise ValueError("结构化任务缺少可信片段剧本目标；请从当前分集画布重新发起")
            if selected_episode_id != target_episode_id or node_id != target_node_id:
                raise ValueError("工具目标与本轮结构化任务的片段剧本目标不一致")
        elif trusted_source and prompt_node and target_node_id:
            if selected_episode_id != target_episode_id or node_id != target_node_id:
                raise ValueError("工具目标与当前对话锁定的片段剧本不一致")

    def _run_get_cinematic_script_context(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("片段剧本创作只允许在目标分集会话中执行")
        if not self._tool_arg(args, "episodeId") or not self._tool_arg(args, "nodeId"):
            return {"success": False, "status": "validation_failed", "errors": [{
                "path": "episodeId/nodeId", "code": "required", "message": "必须明确提供 episodeId 和 nodeId",
                "repairAction": "revise_and_resubmit",
            }]}, args
        self._validate_script_stage_target(selected_episode_id, node_id, structured_task_type="workflow_cinematic_script_generation")
        instruction, preferred_template_id = self._cinematic_script_instruction_and_strategy()
        part = str(args.get("part") or "")
        versions = self._cinematic_script_read_versions.setdefault((selected_episode_id, node_id), {})
        result = get_cinematic_script_context(
            self.context.project_id, selected_episode_id, node_id,
            user_instruction=instruction, preferred_template_id=preferred_template_id,
            part=part, read_versions=versions,
        )
        if result.get("success"):
            version = result.get("contextVersion") or (result.get("submissionState") or {}).get("inputDigest")
            if version:
                versions[part] = version
        return result, args

    def _run_submit_cinematic_script_result(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("片段剧本创作只允许在目标分集会话中执行")
        if not self._tool_arg(args, "episodeId") or not self._tool_arg(args, "nodeId"):
            return {"success": False, "status": "validation_failed", "errors": [{
                "path": "episodeId/nodeId", "code": "required", "message": "必须明确提供 episodeId 和 nodeId",
                "repairAction": "revise_and_resubmit",
            }]}, args
        self._validate_script_stage_target(selected_episode_id, node_id, structured_task_type="workflow_cinematic_script_generation")
        instruction, preferred_template_id = self._cinematic_script_instruction_and_strategy()
        with _LOCK:
            self._require_current_running_execution()
            requested_template_id = self._tool_arg(args, "scriptTemplateId")
            requested_input_digest = self._tool_arg(args, "inputDigest")
            requested_contract = args.get("deliveryContract")
            read_versions = self._cinematic_script_read_versions.get((selected_episode_id, node_id), {})
            requested_output_digest = cinematic_script_output_digest(
                args.get("cinematicStoryText"), requested_contract,
            )
            for receipt in self._commit_receipts.values():
                if (
                    receipt.get("taskType") == "workflow_cinematic_script_generation"
                    and receipt.get("targetIds") == [node_id]
                    and receipt.get("episodeId") == selected_episode_id
                    and receipt.get("inputDigest") == requested_input_digest
                    and receipt.get("outputDigest") == requested_output_digest
                    and receipt.get("scriptTemplateId") == requested_template_id
                ):
                    return {
                        "success": True, "status": "committed", "alreadyCommitted": True,
                        "episodeId": selected_episode_id, "nodeId": node_id,
                        "receiptId": receipt["receiptId"], "commitReceipt": copy.deepcopy(receipt),
                        "projectChanged": False,
                    }, args
            failure = validate_cinematic_script_reads(
                read_versions,
                requested_input_digest, require_submission_state=True,
            )
            if failure:
                return failure, args
            result = submit_cinematic_script_result(
                self.context.project_id,
                selected_episode_id,
                node_id,
                args.get("cinematicStoryText"),
                requested_template_id,
                requested_input_digest,
                user_instruction=instruction,
                session_id=str(self.context.session_id or ""),
                execution_id=str(current_execution_id(self.context.session_id) or ""),
                preferred_template_id=preferred_template_id,
                delivery_contract=requested_contract,
            )
        if result.get("projectChanged"):
            _emit_agent_event("project_changed", {
                "action": "cinematic_script_committed" if result.get("status") == "committed" else "cinematic_script_commit_unverified",
                "projectId": self.context.project_id,
                "episodeId": selected_episode_id,
                "nodeId": node_id,
                "changedResources": result.get("changedResources") or ["canvas_node"],
                "focusTarget": {"section": "episode", "episodeId": selected_episode_id, "nodeId": node_id},
                **_canvas_mutation_event_fields(result),
            })
        return result, args

    def _director_plan_options(self) -> tuple[str, Any, Any]:
        options = self.context.task_options if isinstance(self.context.task_options, dict) else {}
        instruction = str(options.get("userInstruction") or self.context.message or "")
        return instruction, options.get("rhythmMultiplier"), options.get("reworkRecordIds")

    def _director_plan_input_digest(self, args: dict[str, Any], episode_id: str, node_id: str) -> str:
        # The digest is a server-side read lease for this turn. A model can copy a
        # long hash incorrectly; the backend still compares the read lease with
        # current project data before validating or committing.
        return self._director_plan_input_digests.get((episode_id, node_id)) or self._tool_arg(args, "inputDigest")

    def _validate_director_plan_target(self, selected_episode_id: str, node_id: str) -> None:
        validate_director_plan_target(self.context.project_id, self.context.task_type, self.context.active_target,
                                      selected_episode_id, node_id)

    def _run_get_director_plan_context(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("分镜脚本生成只允许在目标分集会话中执行")
        if not self._tool_arg(args, "episodeId") or not self._tool_arg(args, "nodeId"):
            return {"success": False, "status": "validation_failed", "errors": [{
                "path": "episodeId/nodeId", "code": "required", "message": "必须明确提供 episodeId 和 nodeId",
                "repairAction": "revise_and_resubmit",
            }]}, args
        self._validate_director_plan_target(selected_episode_id, node_id)
        instruction, rhythm, rework_ids = self._director_plan_options()
        result = get_director_plan_context(
            self.context.project_id, selected_episode_id, node_id,
            user_instruction=instruction, rhythm_multiplier=rhythm,
            rework_record_ids=rework_ids, part=self._tool_arg(args, "part"),
            input_digest=self._director_plan_input_digest(args, selected_episode_id, node_id),
            selected_director_rule_id=self._tool_arg(args, "selectedDirectorRuleId"),
        )
        if (result.get("success") and self._tool_arg(args, "part") in {"planning_bundle", "planning_state"}
                and isinstance(result.get("inputDigest"), str)):
            self._director_plan_input_digests[(selected_episode_id, node_id)] = result["inputDigest"]
        return result, args

    def _run_validate_director_plan_draft(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("分镜脚本生成只允许在目标分集会话中执行")
        self._validate_director_plan_target(selected_episode_id, node_id)
        instruction, rhythm, rework_ids = self._director_plan_options()
        result = validate_director_plan_draft(
            self.context.project_id, selected_episode_id, node_id,
            args.get("shots"), args.get("speakerRoster"), args.get("speechBudgetNote"),
            self._director_plan_input_digest(args, selected_episode_id, node_id),
            user_instruction=instruction, rhythm_multiplier=rhythm,
            groups=args.get("groups"), rework_record_ids=rework_ids,
            selected_director_rule_id=self._tool_arg(args, "selectedDirectorRuleId"),
        )
        if result.get("success") and result.get("status") == "validated":
            validated_args = copy.deepcopy(args)
            if isinstance(result.get("generatedGroups"), list):
                validated_args["groups"] = copy.deepcopy(result["generatedGroups"])
            self._director_plan_validated_drafts[(
                selected_episode_id, node_id, self._director_plan_input_digest(args, selected_episode_id, node_id),
                str(result.get("submissionDigest") or ""),
            )] = validated_args
        return result, args

    def _run_submit_director_plan_result(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("分镜脚本生成只允许在目标分集会话中执行")
        if not self._tool_arg(args, "episodeId") or not self._tool_arg(args, "nodeId"):
            return {"success": False, "status": "validation_failed", "errors": [{
                "path": "episodeId/nodeId", "code": "required", "message": "必须明确提供 episodeId 和 nodeId",
                "repairAction": "revise_and_resubmit",
            }]}, args
        self._validate_director_plan_target(selected_episode_id, node_id)
        instruction, rhythm, rework_ids = self._director_plan_options()
        input_digest = self._director_plan_input_digest(args, selected_episode_id, node_id)
        validated_digest = self._tool_arg(args, "validatedSubmissionDigest")
        if validated_digest:
            if any(key in args for key in ("shots", "groups", "speakerRoster", "speechBudgetNote")):
                return {
                    "success": False, "status": "validation_failed", "projectChanged": False,
                    "errors": [{"path": "validatedSubmissionDigest", "code": "commit_mode_conflict",
                                "message": "按预检摘要提交时不要重发 shots、groups、speakerRoster 或 speechBudgetNote；"
                                           "修改草稿请重新预检", "repairAction": "revise_and_resubmit"}],
                }, args
            validated_key = (selected_episode_id, node_id, input_digest, validated_digest)
            validated_args = self._director_plan_validated_drafts.get(validated_key)
            if validated_args is None:
                return {
                    "success": False, "status": "validation_failed", "projectChanged": False,
                    "errors": [{"path": "validatedSubmissionDigest", "code": "preflight_required",
                                "message": "本轮没有对应的已通过预检草稿；请重新预检当前完整草稿",
                                "repairAction": "revise_and_resubmit"}],
                }, args
            if ("selectedDirectorRuleId" in args
                    and self._tool_arg(args, "selectedDirectorRuleId")
                    != self._tool_arg(validated_args, "selectedDirectorRuleId")):
                return {
                    "success": False, "status": "validation_failed", "projectChanged": False,
                    "errors": [{"path": "selectedDirectorRuleId", "code": "commit_mode_conflict",
                                "message": "提交的导演规则与已预检草稿不一致；请使用预检摘要或重新预检",
                                "repairAction": "revise_and_resubmit"}],
                }, args
            effective_args = copy.deepcopy(validated_args)
        else:
            effective_args = args
        submission_digest = director_plan_submission_digest(
            effective_args.get("shots"), effective_args.get("speakerRoster"), effective_args.get("speechBudgetNote"), effective_args.get("groups"),
            self._tool_arg(effective_args, "selectedDirectorRuleId"),
        )
        if (selected_episode_id, node_id, input_digest, submission_digest) not in self._director_plan_validated_drafts:
            return {
                "success": False, "status": "validation_failed", "projectChanged": False,
                "message": "正式提交前必须以同一份草稿通过只读预校验；请先调用 validate_director_plan_draft",
                "errors": [{"path": "shots/groups", "code": "preflight_required",
                            "message": "草稿尚未通过本轮预校验，或预检后内容已改变",
                            "repairAction": "revise_and_resubmit"}],
            }, args
        with _LOCK:
            self._require_current_running_execution()
            for receipt in self._commit_receipts.values():
                if (receipt.get("taskType") == "director_plan_generation"
                        and receipt.get("targetIds") == [node_id]
                        and receipt.get("episodeId") == selected_episode_id
                        and receipt.get("inputDigest") == input_digest
                        and receipt.get("submissionDigest") == submission_digest):
                    return {
                        "success": True, "status": "committed", "alreadyCommitted": True,
                        "episodeId": selected_episode_id, "nodeId": node_id,
                        "receiptId": receipt["receiptId"], "commitReceipt": copy.deepcopy(receipt),
                        "projectChanged": False,
                    }, args
            result = submit_director_plan_result(
                self.context.project_id, selected_episode_id, node_id,
                effective_args.get("shots"), effective_args.get("speakerRoster"), effective_args.get("speechBudgetNote"),
                input_digest,
                user_instruction=instruction, rhythm_multiplier=rhythm,
                groups=effective_args.get("groups"),
                rework_record_ids=rework_ids,
                selected_director_rule_id=self._tool_arg(effective_args, "selectedDirectorRuleId"),
                session_id=str(self.context.session_id or ""),
                execution_id=str(current_execution_id(self.context.session_id) or ""),
            )
        if result.get("projectChanged"):
            _emit_agent_event("project_changed", {
                "action": "director_plan_committed" if result.get("status") == "committed" else "director_plan_commit_unverified",
                "projectId": self.context.project_id,
                "episodeId": selected_episode_id, "nodeId": node_id,
                "changedResources": result.get("changedResources") or ["canvas_node"],
                "focusTarget": {"section": "episode", "episodeId": selected_episode_id, "nodeId": node_id},
                **_canvas_mutation_event_fields(result),
            })
        return result, args

    def _video_prompt_instruction(self) -> str:
        options = self.context.task_options if isinstance(self.context.task_options, dict) else {}
        return str(options.get("userInstruction") or self.context.message or "")

    def _select_video_prompt_target(self, tool_name: str, node_id: str) -> None:
        policy = self.context.session_policy or {}
        episode_id = str(policy.get("currentEpisodeId") or self.context.episode_id or "").strip()
        if policy.get("scope") != "episode" or not episode_id:
            raise ValueError("请在目标视频卡所在的画布会话中读取资料")
        validate_agent_tool_episode_scope(tool_name, episode_id, policy)
        node = read_canvas_card_record_v4(self.context.project_id, episode_id, node_id, detail="full")
        if str(node.get("type") or "") not in {"video.storyboard", "video.keyframe"}:
            raise ValueError("指定节点不是支持提示词生成的视频卡")
        target = {"source": "agent_recommendation", "section": "episode",
                  "episodeId": episode_id, "nodeId": node_id, "nodeType": node["type"],
                  **{key: str(node[key]) for key in ("routeId", "workChainId") if node.get(key)}}
        self.context = replace(self.context, active_target=target)
        if tool_name == "get_video_prompt_optimization_context":
            self._capture_video_prompt_optimization_draft(node)

    def _capture_video_prompt_optimization_draft(self, node: dict[str, Any]) -> None:
        from .agent_video_prompt_optimization_tools import video_prompt_edit_digest

        data = node.get("data") or {}
        card = data.get("videoTaskCard") or {}
        options = {**(self.context.task_options or {}),
                   "draftText": str(card.get("finalVideoPrompt") or (data.get("prompt") or {}).get("videoPrompt") or ""),
                   "soundPrompt": str(card.get("soundPrompt") or ""),
                   "assetNameMap": copy.deepcopy(card.get("assetNameMap") or {}),
                   "promptBindings": copy.deepcopy(card.get("promptBindings") or {})}
        self._video_prompt_saved_edit_digest = video_prompt_edit_digest(data)
        self.context = replace(self.context, task_options=options)

    def _bind_video_prompt_target(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        args = dict(args)
        selected_node = args.pop("nodeId", None) if tool_name.startswith("get_") else None
        if any(key in args for key in ("episodeId", "episode_id", "nodeId", "node_id", "targetNodeId", "target_node_id", "inputDigest")):
            raise ValueError("视频卡目标和输入版本由系统携带，工具参数只需提交内容或读取类型")
        if selected_node is not None:
            if not isinstance(selected_node, str) or not selected_node.strip():
                raise ValueError("请选择用户指定的视频卡 nodeId")
            selected_node = selected_node.strip()
            target = self.context.active_target or {}
            if (target.get("source") in {"storyboard_canvas", "agent_recommendation"}
                    and target.get("nodeType") in {"video.storyboard", "video.keyframe"}
                    and target.get("nodeId")):
                if selected_node != target["nodeId"]:
                    raise ValueError("工具目标与本轮锁定的视频卡不一致")
            elif self.context.task_type == "free_chat":
                self._select_video_prompt_target(tool_name, selected_node)
        target = self.context.active_target if isinstance(self.context.active_target, dict) else {}
        episode_id = str(target.get("episodeId") or "").strip()
        node_id = str(target.get("nodeId") or "").strip()
        if (target.get("source") not in {"storyboard_canvas", "agent_recommendation"}
                or target.get("nodeType") not in {"video.storyboard", "video.keyframe"}
                or not episode_id or not node_id):
            raise ValueError("当前任务缺少可信视频卡目标，请先通过读取工具选择用户指定的 nodeId")
        if (tool_name == "get_video_prompt_optimization_context" and self.context.task_type == "free_chat"
                and not self._video_prompt_saved_edit_digest):
            node = read_canvas_card_record_v4(self.context.project_id, episode_id, node_id, detail="full")
            self._capture_video_prompt_optimization_draft(node)
        return {**args, "episodeId": episode_id, "nodeId": node_id}

    def _remember_video_prompt_context(self, task_type: str, episode_id: str, node_id: str,
                                       result: dict[str, Any]) -> dict[str, Any]:
        digest = result.get("inputDigest")
        if result.get("success") and isinstance(digest, str) and digest:
            with _LOCK:
                # A retry after a successful write still belongs to the same proposal.
                committed = any(receipt.get("taskType") == task_type
                                and receipt.get("episodeId") == episode_id
                                and receipt.get("targetIds") == [node_id]
                                for receipt in self._commit_receipts.values())
                if not committed:
                    self._video_prompt_input_digests[(task_type, episode_id, node_id)] = digest
        visible = {key: value for key, value in result.items() if key != "inputDigest"}
        if result.get("success") and set(visible) == {"success"}:
            visible["contextReady"] = True
        return visible

    def _video_prompt_submission_fields(self, args: dict[str, Any], task_type: str,
                                         episode_id: str, node_id: str) -> tuple[dict[str, Any], str]:
        fields = video_prompt_result_fields(args)
        digest = self._video_prompt_input_digests.get((task_type, episode_id, node_id))
        if not digest:
            raise ValueError("本轮尚未读取视频提示词上下文，请先读取资料后再提交")
        return fields, digest

    def _validate_video_prompt_target(self, selected_episode_id: str, node_id: str) -> None:
        validate_video_prompt_target(self.context.project_id, self.context.task_type,
                                     self.context.active_target, selected_episode_id, node_id)

    def _run_get_video_prompt_context(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("视频提示词生成只允许在目标分集会话中执行")
        if not self._tool_arg(args, "episodeId") or not self._tool_arg(args, "nodeId"):
            return {"success": False, "status": "validation_failed", "errors": [{
                "path": "episodeId/nodeId", "code": "required", "message": "必须明确提供 episodeId 和 nodeId",
                "repairAction": "revise_and_resubmit",
            }]}, args
        self._validate_video_prompt_target(selected_episode_id, node_id)
        target = self.context.active_target if isinstance(self.context.active_target, dict) else {}
        result = get_video_prompt_context(
            self.context.project_id, selected_episode_id, node_id,
            user_instruction=self._video_prompt_instruction(),
            expected_route_id=str(target.get("routeId") or "").strip(),
            expected_work_chain_id=str(target.get("workChainId") or "").strip(),
            part=self._tool_arg(args, "part"),
        )
        return self._remember_video_prompt_context("video_prompt_generation", selected_episode_id, node_id, result), args

    def _run_submit_video_prompt_result(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("视频提示词生成只允许在目标分集会话中执行")
        if not self._tool_arg(args, "episodeId") or not self._tool_arg(args, "nodeId"):
            return {"success": False, "status": "validation_failed", "errors": [{
                "path": "episodeId/nodeId", "code": "required", "message": "必须明确提供 episodeId 和 nodeId",
                "repairAction": "revise_and_resubmit",
            }]}, args
        self._validate_video_prompt_target(selected_episode_id, node_id)
        target = self.context.active_target if isinstance(self.context.active_target, dict) else {}
        with _LOCK:
            self._require_current_running_execution()
            fields, input_digest = self._video_prompt_submission_fields(
                args, "video_prompt_generation", selected_episode_id, node_id,
            )
            submission_digest = video_prompt_submission_digest(
                fields.get("shots"), fields.get("usedSpeakerIds"), fields.get("voiceDesign"),
                fields.get("soundPrompt", ""),
            )
            for receipt in self._commit_receipts.values():
                if (receipt.get("taskType") == "video_prompt_generation"
                        and receipt.get("targetIds") == [node_id]
                        and receipt.get("episodeId") == selected_episode_id
                        and receipt.get("inputDigest") == input_digest
                        and receipt.get("submissionDigest") == submission_digest):
                    return {
                        "success": True, "status": "committed", "alreadyCommitted": True,
                        "episodeId": selected_episode_id, "nodeId": node_id,
                        "receiptId": receipt["receiptId"], "commitReceipt": copy.deepcopy(receipt),
                        "projectChanged": False,
                    }, args
            result = submit_video_prompt_result(
                self.context.project_id, selected_episode_id, node_id,
                fields.get("shots"), fields.get("usedSpeakerIds"), fields.get("voiceDesign"), input_digest,
                user_instruction=self._video_prompt_instruction(),
                session_id=str(self.context.session_id or ""),
                execution_id=str(current_execution_id(self.context.session_id) or ""),
                expected_route_id=str(target.get("routeId") or "").strip(),
                expected_work_chain_id=str(target.get("workChainId") or "").strip(),
                sound_prompt=fields.get("soundPrompt", ""),
            )
        if result.get("projectChanged"):
            _emit_agent_event("project_changed", {
                "action": "video_prompt_committed" if result.get("status") == "committed" else "video_prompt_commit_unverified",
                "projectId": self.context.project_id, "episodeId": selected_episode_id,
                "nodeId": node_id, "changedResources": result.get("changedResources") or ["canvas_node"],
                "focusTarget": {"section": "episode", "episodeId": selected_episode_id, "nodeId": node_id},
                **_canvas_mutation_event_fields(result),
            })
        return result, args

    def _validate_video_prompt_optimization_target(self, selected_episode_id: str, node_id: str) -> dict[str, Any]:
        target = self.context.active_target if isinstance(self.context.active_target, dict) else {}
        if self.context.task_type in {"video_prompt_optimization", "video_prompt_standalone_generation"}:
            if (str(target.get("source") or "").strip() not in {"storyboard_canvas", "agent_recommendation"}
                    or str(target.get("nodeType") or "").strip() not in {"video.storyboard", "video.keyframe"}
                    or str(target.get("canvasKind") or "").strip() not in {"work_chain", "episode", "custom"}
                    or str(target.get("episodeId") or "").strip() != selected_episode_id
                    or str(target.get("nodeId") or "").strip() != node_id):
                raise ValueError("结构化任务缺少可信独立视频卡目标；请从当前画布编辑弹窗重新发起")
        return target

    def _video_prompt_optimization_options(self) -> tuple[str, Any, Any]:
        options = self.context.task_options if isinstance(self.context.task_options, dict) else {}
        return options.get("draftText"), options.get("assetNameMap", {}), options.get("promptBindings", {})

    def _run_get_video_prompt_optimization_context(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("独立视频提示词优化只允许在目标画布会话中执行")
        if not self._tool_arg(args, "episodeId") or not self._tool_arg(args, "nodeId"):
            return {"success": False, "status": "validation_failed", "errors": [{
                "path": "episodeId/nodeId", "code": "required", "message": "必须明确提供 episodeId 和 nodeId",
                "repairAction": "revise_and_resubmit",
            }]}, args
        target = self._validate_video_prompt_optimization_target(selected_episode_id, node_id)
        draft, names, bindings = self._video_prompt_optimization_options()
        result = get_video_prompt_optimization_context(
            self.context.project_id, selected_episode_id, node_id,
            draft_text=draft, asset_name_map=names, prompt_bindings=bindings,
            sound_prompt=(self.context.task_options or {}).get("soundPrompt"),
            expected_canvas_kind=str(target.get("canvasKind") or "").strip(),
            part=self._tool_arg(args, "part"),
            expected_saved_prompt_digest=self._video_prompt_saved_edit_digest,
        )
        return self._remember_video_prompt_context("video_prompt_optimization", selected_episode_id, node_id, result), args

    def _run_submit_video_prompt_optimization_result(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("独立视频提示词优化只允许在目标画布会话中执行")
        if not self._tool_arg(args, "episodeId") or not self._tool_arg(args, "nodeId"):
            return {"success": False, "status": "validation_failed", "errors": [{
                "path": "episodeId/nodeId", "code": "required", "message": "必须明确提供 episodeId 和 nodeId",
                "repairAction": "revise_and_resubmit",
            }]}, args
        target = self._validate_video_prompt_optimization_target(selected_episode_id, node_id)
        draft, names, bindings = self._video_prompt_optimization_options()
        with _LOCK:
            self._require_current_running_execution()
            fields, input_digest = self._video_prompt_submission_fields(
                args, "video_prompt_optimization", selected_episode_id, node_id,
            )
            submission_digest = video_prompt_submission_digest(
                fields.get("shots"), fields.get("usedSpeakerIds"), fields.get("voiceDesign"),
                fields.get("soundPrompt", ""),
            )
            for receipt in self._commit_receipts.values():
                if (receipt.get("taskType") == "video_prompt_optimization"
                        and receipt.get("targetIds") == [node_id]
                        and receipt.get("episodeId") == selected_episode_id
                        and receipt.get("inputDigest") == input_digest
                        and receipt.get("submissionDigest") == submission_digest):
                    return {
                        "success": True, "status": "committed", "alreadyCommitted": True,
                        "episodeId": selected_episode_id, "nodeId": node_id,
                        "receiptId": receipt["receiptId"], "commitReceipt": copy.deepcopy(receipt),
                        "projectChanged": False,
                    }, args
            result = submit_video_prompt_optimization_result(
                self.context.project_id, selected_episode_id, node_id,
                fields.get("shots"), fields.get("usedSpeakerIds"), fields.get("voiceDesign"), input_digest,
                draft_text=draft, asset_name_map=names, prompt_bindings=bindings,
                draft_sound_prompt=(self.context.task_options or {}).get("soundPrompt"),
                sound_prompt=fields.get("soundPrompt", ""),
                expected_canvas_kind=str(target.get("canvasKind") or "").strip(),
                session_id=str(self.context.session_id or ""),
                execution_id=str(current_execution_id(self.context.session_id) or ""),
                expected_saved_prompt_digest=self._video_prompt_saved_edit_digest,
            )
        if result.get("projectChanged"):
            _emit_agent_event("project_changed", {
                "action": "video_prompt_optimization_committed" if result.get("status") == "committed" else "video_prompt_optimization_commit_unverified",
                "projectId": self.context.project_id, "episodeId": selected_episode_id,
                "nodeId": node_id, "changedResources": result.get("changedResources") or ["canvas_node"],
                "focusTarget": {"section": "episode", "episodeId": selected_episode_id, "nodeId": node_id},
                **_canvas_mutation_event_fields(result),
            })
        return result, args

    def _run_get_video_prompt_standalone_context(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("独立视频提示词生成只允许在目标画布会话中执行")
        if not self._tool_arg(args, "episodeId") or not self._tool_arg(args, "nodeId"):
            return {"success": False, "status": "validation_failed", "errors": [{
                "path": "episodeId/nodeId", "code": "required", "message": "必须明确提供 episodeId 和 nodeId",
                "repairAction": "revise_and_resubmit",
            }]}, args
        target = self._validate_video_prompt_optimization_target(selected_episode_id, node_id)
        result = get_video_prompt_standalone_context(
            self.context.project_id, selected_episode_id, node_id,
            expected_canvas_kind=str(target.get("canvasKind") or "").strip(),
            part=self._tool_arg(args, "part"),
        )
        return self._remember_video_prompt_context("video_prompt_standalone_generation", selected_episode_id, node_id, result), args

    def _run_submit_video_prompt_standalone_result(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "episode":
            raise ValueError("独立视频提示词生成只允许在目标画布会话中执行")
        if not self._tool_arg(args, "episodeId") or not self._tool_arg(args, "nodeId"):
            return {"success": False, "status": "validation_failed", "errors": [{
                "path": "episodeId/nodeId", "code": "required", "message": "必须明确提供 episodeId 和 nodeId",
                "repairAction": "revise_and_resubmit",
            }]}, args
        target = self._validate_video_prompt_optimization_target(selected_episode_id, node_id)
        with _LOCK:
            self._require_current_running_execution()
            fields, input_digest = self._video_prompt_submission_fields(
                args, "video_prompt_standalone_generation", selected_episode_id, node_id,
            )
            submission_digest = video_prompt_submission_digest(
                fields.get("shots"), fields.get("usedSpeakerIds"), fields.get("voiceDesign"),
                fields.get("soundPrompt", ""),
            )
            for receipt in self._commit_receipts.values():
                if (receipt.get("taskType") == "video_prompt_standalone_generation"
                        and receipt.get("targetIds") == [node_id]
                        and receipt.get("episodeId") == selected_episode_id
                        and receipt.get("inputDigest") == input_digest
                        and receipt.get("submissionDigest") == submission_digest):
                    return {"success": True, "status": "committed", "alreadyCommitted": True,
                            "episodeId": selected_episode_id, "nodeId": node_id,
                            "receiptId": receipt["receiptId"], "commitReceipt": copy.deepcopy(receipt),
                            "projectChanged": False}, args
            result = submit_video_prompt_standalone_result(
                self.context.project_id, selected_episode_id, node_id,
                fields.get("shots"), fields.get("usedSpeakerIds"), fields.get("voiceDesign"), input_digest,
                expected_canvas_kind=str(target.get("canvasKind") or "").strip(),
                session_id=str(self.context.session_id or ""),
                execution_id=str(current_execution_id(self.context.session_id) or ""),
                sound_prompt=fields.get("soundPrompt", ""),
            )
        if result.get("projectChanged"):
            _emit_agent_event("project_changed", {
                "action": "video_prompt_standalone_committed" if result.get("status") == "committed" else "video_prompt_standalone_commit_unverified",
                "projectId": self.context.project_id, "episodeId": selected_episode_id,
                "nodeId": node_id, "changedResources": result.get("changedResources") or ["canvas_node"],
                "focusTarget": {"section": "episode", "episodeId": selected_episode_id, "nodeId": node_id},
                **_canvas_mutation_event_fields(result),
            })
        return result, args

    def _run_start_business_task(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        task_type = _agent_validate_task_type(self._tool_arg(args, "taskType"))
        if task_type not in BUSINESS_TASK_HANDOFF_TYPES:
            raise ValueError("该任务没有确定性的本地执行入口，请使用对应 Skill 或明确目标后重试。")
        validate_agent_session_task_type(task_type, self.context.session_policy)
        if self.business_task_handoff or self.pending_operation_update or self.context.pending_operation_context.get("active"):
            raise ValueError("本轮已有待处理任务或待确认候选，不能再次移交任务。")
        requirement = str(args.get("userRequirement") or "").strip()[:1500]
        self.business_task_handoff = {"taskType": task_type, "message": self.context.message,
                               "userRequirement": requirement}
        return {"success": True, "status": "handoff", "taskType": task_type,
                "message": "已选定业务任务；当前智能体回合结束后由应用启动。"}, args


    def _run_save_story_world_map(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = save_story_world_map(self.context.project_id, args or {})
        _emit_agent_event("project_changed", {"action": "story_world_saved", "projectId": self.context.project_id})

        return result, args

    def _run_upsert_asset(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        args = copy.deepcopy(args or {})
        if str(self.context.task_hypothesis.get("assetOperation") or "").strip() == "create":
            asset = args.get("asset") if isinstance(args.get("asset"), dict) else {}
            expected_type = str(self.context.task_hypothesis.get("assetType") or "").strip()
            if expected_type and str(args.get("assetType") or args.get("asset_type") or "").strip() != expected_type:
                raise ValueError("新建资产的类型与本轮任务不一致")
            if str(asset.get("id") or asset.get("assetId") or "").strip():
                raise ValueError("新建资产不能复用已有资产 ID")
            if not str(asset.get("name") or "").strip() or not str(asset.get("desc") or "").strip():
                raise ValueError("新建资产必须完成 name 和 desc 后再保存")
            if not _asset_design_prompt_from_asset(asset):
                raise ValueError("新建资产缺少 asset.prompts.assetImagePrompt，请完成视觉母版设计后再保存")
        if not args.get("replaceExisting") and not args.get("replace_existing"):
            args.setdefault("mergeExisting", True)
        result = upsert_asset(self.context.project_id, args or {})
        _emit_agent_event(
            "project_changed",
            {
                "action": "asset_upserted",
                "projectId": self.context.project_id,
                "assetType": args.get("assetType") or args.get("asset_type"),
                "assetId": (result.get("asset") or {}).get("id") if isinstance(result.get("asset"), dict) else "",
                "changedResources": result.get("changedResources") or [],
            },
        )

        return result, args

    def _run_delete_asset(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        from .agent_direct_deletion import stage_agent_direct_delete
        if self.pending_operation_update or self.context.pending_operation_context.get("active"):
            raise ValueError("已有待确认操作，请先处理后再提出新的删除请求")
        result = stage_agent_direct_delete(
            self.context.project_id, selected_episode_id, self.context.session_id,
            "delete_asset", args,
        )
        return result, args

    def _run_delete_all_project_assets(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = delete_all_project_assets(self.context.project_id, args or {})
        _emit_agent_event(
            "project_changed",
            {
                "action": "project_assets_deleted_all",
                "projectId": self.context.project_id,
                "changedResources": result.get("changedResources") or [],
            },
        )

        return result, args

    def _run_save_episode_work_chain_plan(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = save_episode_work_chain_plan(self.context.project_id, selected_episode_id, args or {})
        workflow_result = build_episode_workflow_from_work_chain_plan(
            self.context.project_id,
            result.get("episodeId") or selected_episode_id,
            {
                "source": "agent",
                "reason": "save_episode_work_chain_plan",
            },
        )
        canvas_event_fields = _canvas_mutation_event_payload(
            result,
            workflow_result,
            fallback_changed_resources=["workChainPlan", "storyboard", "canvas_document"],
        )
        result.update(copy.deepcopy(canvas_event_fields))
        _emit_agent_event(
            "project_changed",
            {
                "action": "episode_work_chain_plan_saved",
                "projectId": self.context.project_id,
                "episodeId": result.get("episodeId"),
                **canvas_event_fields,
                "focusTarget": result.get("focusTarget"),
            },
        )

        return result, args

    def _run_patch_shot_prompt(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = patch_shot_prompt(self.context.project_id, selected_episode_id, args or {})
        workflow_patch = result.get("workflowPatch") if isinstance(result.get("workflowPatch"), dict) else {}
        patch_event_fields = _canvas_mutation_event_payload(
            result,
            workflow_patch,
            fallback_changed_resources=result.get("changedResources") or [],
        )
        _emit_agent_event(
            "project_changed",
            {
                "action": "shot_prompt_patched",
                "projectId": self.context.project_id,
                "episodeId": result.get("episodeId"),
                "nodeId": workflow_patch.get("nodeId") or result.get("nodeId"),
                "node": workflow_patch.get("node") if isinstance(workflow_patch.get("node"), dict) else None,
                **patch_event_fields,
                "focusTarget": result.get("focusTarget"),
                **(
                    {"productionStatus": workflow_patch.get("productionStatus")}
                    if workflow_patch.get("productionStatus") is not None
                    else {}
                ),
            },
        )

        return result, args

    def _run_upsert_workflow_node(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = upsert_workflow_node(self.context.project_id, selected_episode_id, _canvas_mutation_payload(args))
        event_payload = {
            "action": "workflow_item_upserted",
            "projectId": self.context.project_id,
            "episodeId": selected_episode_id,
            "itemType": result.get("itemType"),
            "itemId": (result.get("item") or {}).get("id") if isinstance(result.get("item"), dict) else None,
            "item": result.get("item") if isinstance(result.get("item"), dict) else None,
            "workflowVersion": result.get("workflowVersion"),
            **_canvas_mutation_event_fields(result),
            "changedResources": result.get("changedResources") or [],
            "focusTarget": result.get("focusTarget"),
        }
        _emit_agent_event(
            "project_changed",
            event_payload,
        )

        return result, args

    def _run_delete_workflow_node(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        from .agent_direct_deletion import stage_agent_direct_delete
        if self.pending_operation_update or self.context.pending_operation_context.get("active"):
            raise ValueError("已有待确认操作，请先处理后再提出新的删除请求")
        result = stage_agent_direct_delete(
            self.context.project_id, selected_episode_id, self.context.session_id,
            "delete_workflow_node", _canvas_mutation_payload(args),
        )
        return result, args

    def _run_delete_project_planning_outputs(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = delete_project_planning_outputs(self.context.project_id, args or {})
        _emit_agent_event(
            "project_changed",
            {
                "action": "project_planning_outputs_deleted",
                "projectId": self.context.project_id,
                "episodeIds": result.get("episodeIds") or [],
                "targets": result.get("targets") or [],
                "changedResources": result.get("changedResources") or [],
            },
        )

        return result, args

    def _run_save_workflow_node_inline_edit(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = save_workflow_node_inline_edit(self.context.project_id, selected_episode_id, _canvas_mutation_payload(args))
        if result.get("projectChanged"):
            _emit_agent_event(
                "project_changed",
                {
                    "action": "workflow_node_inline_saved",
                    "projectId": self.context.project_id,
                    "episodeId": selected_episode_id,
                    "nodeId": result.get("nodeId"),
                    "node": result.get("node") if isinstance(result.get("node"), dict) else None,
                    "nodes": result.get("nodes") if isinstance(result.get("nodes"), list) else [],
                    "edges": result.get("edges") if isinstance(result.get("edges"), list) else [],
                    "workflowVersion": result.get("workflowVersion"),
                    **_canvas_mutation_event_fields(result),
                    "changedResources": result.get("changedResources") or [],
                    "focusTarget": result.get("focusTarget"),
                    "productionStatus": result.get("productionStatus"),
                },
            )

        return result, args

    def _run_create_workflow_task_card(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = create_workflow_task_card(self.context.project_id, selected_episode_id, _canvas_mutation_payload(args))
        _emit_agent_event(
            "project_changed",
            {
                "action": "workflow_task_card_created",
                "projectId": self.context.project_id,
                "episodeId": selected_episode_id,
                "nodeId": (result.get("node") or {}).get("id") if isinstance(result.get("node"), dict) else None,
                "node": result.get("node") if isinstance(result.get("node"), dict) else None,
                "resultNode": result.get("resultNode") if isinstance(result.get("resultNode"), dict) else None,
                "edge": result.get("edge") if isinstance(result.get("edge"), dict) else None,
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": result.get("changedResources") or [],
                "focusTarget": result.get("focusTarget"),
            },
        )

        return result, args

    def _run_add_workflow_asset_nodes(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = add_workflow_asset_nodes(self.context.project_id, selected_episode_id, _canvas_mutation_payload(args))
        _emit_agent_event(
            "project_changed",
            {
                "action": "workflow_asset_nodes_added",
                "projectId": self.context.project_id,
                "episodeId": selected_episode_id,
                "nodes": result.get("nodes") if isinstance(result.get("nodes"), list) else [],
                "workflowVersion": result.get("workflowVersion"),
                **_canvas_mutation_event_fields(result),
                "changedResources": result.get("changedResources") or [],
                "focusTarget": result.get("focusTarget"),
            },
        )

        return result, args

    def _run_update_workflow_route(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        route_payload = _canvas_mutation_payload(args)
        result = update_workflow_route(self.context.project_id, selected_episode_id, route_payload)
        event_payload = {
            "action": "workflow_route_updated",
            "projectId": self.context.project_id,
            "episodeId": selected_episode_id,
            "routeId": (result.get("route") or {}).get("id") if isinstance(result.get("route"), dict) else None,
            "route": result.get("route") if isinstance(result.get("route"), dict) else None,
            "workflowVersion": result.get("workflowVersion"),
            **_canvas_mutation_event_fields(result),
            "changedResources": result.get("changedResources") or [],
            "focusTarget": result.get("focusTarget"),
        }
        _emit_agent_event("project_changed", event_payload)

        return result, args

    def _run_link_workflow_input(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        link_payload = _canvas_mutation_payload(args)
        link_payload["source"] = "agent"
        link_payload["createdBy"] = "agent"
        link_provenance = link_payload.get("provenance") if isinstance(link_payload.get("provenance"), dict) else {}
        link_payload["provenance"] = {**link_provenance, "source": "agent"}
        result = link_workflow_input(self.context.project_id, selected_episode_id, link_payload)
        event_payload = {
            "action": "workflow_input_linked",
            "projectId": self.context.project_id,
            "episodeId": selected_episode_id,
            "inputLinkId": (result.get("inputLink") or {}).get("id") if isinstance(result.get("inputLink"), dict) else None,
            "inputLink": result.get("inputLink") if isinstance(result.get("inputLink"), dict) else None,
            "node": result.get("node") if isinstance(result.get("node"), dict) else None,
            "nodes": result.get("nodes") if isinstance(result.get("nodes"), list) else [],
            "edge": result.get("edge") if isinstance(result.get("edge"), dict) else None,
            "targetNodeId": result.get("targetNodeId"),
            "workflowVersion": result.get("workflowVersion"),
            "productionStatus": result.get("productionStatus"),
            **_canvas_mutation_event_fields(result),
            "changedResources": result.get("changedResources") or [],
            "focusTarget": result.get("focusTarget"),
        }
        _emit_agent_event("project_changed", event_payload)

        return result, args

    def _run_unlink_workflow_input(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        from .agent_direct_deletion import stage_agent_direct_delete
        if self.pending_operation_update or self.context.pending_operation_context.get("active"):
            raise ValueError("已有待确认操作，请先处理后再提出新的移除请求")
        result = stage_agent_direct_delete(
            self.context.project_id, selected_episode_id, self.context.session_id,
            "unlink_workflow_input", _canvas_mutation_payload(args),
        )
        return result, args

    def _run_list_workflow_inputs(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = list_workflow_inputs(self.context.project_id, selected_episode_id, args or {})

        return result, args

    def _run_validate_project_quality(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        target_episode_id = self._tool_arg(args, "episodeId", "episode_id", default="")
        result = validate_project_quality(self.context.project_id, target_episode_id or None)

        return result, args

    def _run_request_storyboard_image_generation(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        storyboard_instruction, extracted_requirements = self._prepare_program_work_instruction(
            "storyboard-image-generation",
            _generation_user_instruction(args),
        )
        from .storyboard_task_execution import run_storyboard_generation_task

        result = run_storyboard_generation_task(
            "storyboard_image",
            self.context.project_id,
            selected_episode_id,
            node_id,
            "image",
            user_instruction=storyboard_instruction,
            session_id=self.context.session_id,
        )
        result["extractedRequirements"] = extracted_requirements

        return result, args


    def _run_request_visual_handoff_image_generation(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        handoff_instruction, extracted_requirements = self._prepare_program_work_instruction(
            "visual-handoff-image-generation",
            _generation_user_instruction(args),
        )
        from .storyboard_task_execution import run_storyboard_generation_task

        result = run_storyboard_generation_task(
            "visual_handoff_image",
            self.context.project_id,
            selected_episode_id,
            node_id,
            "image",
            user_instruction=handoff_instruction,
            session_id=self.context.session_id,
        )
        result["extractedRequirements"] = extracted_requirements

        return result, args


    def _run_request_storyboard_video_generation(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        from .storyboard_task_execution import run_storyboard_generation_task

        result = run_storyboard_generation_task(
            "storyboard_video",
            self.context.project_id,
            selected_episode_id,
            node_id,
            "video",
            user_instruction=user_instruction,
            session_id=self.context.session_id,
        )

        return result, args

    def _run_edit_storyboard_image(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        edit_instruction = self._tool_arg(
            args,
            "prompt",
            "editPrompt",
            "edit_prompt",
            "userInstruction",
            "user_instruction",
            "revisionInstruction",
            "revision_instruction",
            default=str(self.context.message or "").strip(),
        )
        storyboard_instruction, extracted_requirements = self._prepare_program_work_instruction(
            "storyboard-image-edit",
            edit_instruction,
        )
        edit_payload = {
            **(args or {}),
            "prompt": edit_instruction,
            "editPrompt": edit_instruction,
            "userInstruction": edit_instruction,
            "effectiveEditPrompt": storyboard_instruction or edit_instruction,
            "agentRefinedEditPrompt": storyboard_instruction or edit_instruction,
            "agentOriginalUserInstruction": edit_instruction,
            "sessionId": self.context.session_id,
        }
        if isinstance(extracted_requirements, dict):
            edit_payload["agentExtractedRequirements"] = copy.deepcopy(extracted_requirements)
        existing_reference_files = (
            edit_payload.get("referenceFiles")
            if isinstance(edit_payload.get("referenceFiles"), list)
            else edit_payload.get("reference_files")
            if isinstance(edit_payload.get("reference_files"), list)
            else []
        )
        if not existing_reference_files:
            attached_reference_files = [
                copy.deepcopy(item)
                for item in (self.context.images or [])
                if isinstance(item, dict)
                and str(item.get("mimeType") or item.get("mime_type") or "").startswith("image/")
            ]
            if attached_reference_files:
                edit_payload["referenceFiles"] = attached_reference_files
        from .workflow_storyboard_edits import edit_storyboard_image

        result = edit_storyboard_image(self.context.project_id, selected_episode_id, node_id, edit_payload)
        result["extractedRequirements"] = extracted_requirements
        _emit_agent_event(
            "project_changed",
            {
                "action": "storyboard_image_edited",
                "projectId": self.context.project_id,
                "episodeId": result.get("episodeId") or selected_episode_id,
                "nodeId": result.get("nodeId") or node_id,
                **_canvas_mutation_event_fields(result),
                "changedResources": result.get("changedResources") or ["canvas_node", "canvas_version", "canvas_task"],
            },
        )

        return result, args

    def _run_request_route_video_generation(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = request_route_video_generation(
            self.context.project_id,
            selected_episode_id,
            {**(args or {}), "userInstruction": user_instruction, "sessionId": self.context.session_id},
        )

        return result, args

    def _run_request_asset_image_generation(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        asset_type = self._tool_arg(args, "assetType", "asset_type")
        asset_id = self._tool_arg(args, "assetId", "asset_id")
        if asset_type not in {"characters", "creatures", "scenes", "props"}:
            raise ValueError("资产类型必须是 characters、creatures、scenes 或 props")
        result = start_asset_media_generation(
            asset_type,
            asset_id,
            "project",
            self.context.project_id,
            None,
            hide_turnaround_heads=args.get("hideTurnaroundHeads", args.get("hide_turnaround_heads")),
            episode_ids=[selected_episode_id] if selected_episode_id else None,
            session_id=self.context.session_id,
        )

        return result, args

    def _run_list_generation_tasks(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        from .task_queries import list_tasks

        tasks = list_tasks().get("tasks") or []
        result = {
            "success": True,
            "tasks": [
                {
                    "id": task.get("id"),
                    "type": task.get("type"),
                    "status": task.get("status"),
                    "progress": task.get("progress"),
                    "message": task.get("message"),
                    "episodeId": task.get("episodeId"),
                    "nodeId": task.get("nodeId"),
                }
                for task in tasks[:20]
                if isinstance(task, dict)
            ],
        }

        return result, args

    def _run_cancel_generation_task(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        from .task_commands import cancel_task

        result = cancel_task(self._tool_arg(args, "taskId", "task_id"))

        return result, args

    def _run_request_project_export(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        from .exports import export_project_assets
        from .task_events import _emit_generation_task_result

        scopes = args.get("scopes")
        if not isinstance(scopes, list):
            scopes = ["overview", "sources", "characters", "creatures", "scenes", "props", "episodes", "storyboard", "tasks"]
        result = export_project_assets(self.context.project_id, [str(item) for item in scopes if str(item).strip()])
        _emit_generation_task_result(
            result,
            project_id=self.context.project_id,
            project_action="project_assets_exported",
        )

        return result, args

    def _run_list_director_rules(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = list_director_rules_for_agent(args)

        return result, args

    def _run_search_director_rules(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = search_director_rules_for_agent(args)

        return result, args

    def _run_read_director_rule(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = read_director_rule_for_agent(args)

        return result, args

    def _run_list_project_files(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = list_project_files_for_agent(
            self.context.project_id, args, trusted_scope=self._project_file_trusted_scope())

        return result, args

    def _run_search_project_files(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = search_project_files_for_agent(
            self.context.project_id, args, trusted_scope=self._project_file_trusted_scope())

        return result, args

    def _run_read_project_file(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = read_project_file_for_agent(
            self.context.project_id, args, trusted_scope=self._project_file_trusted_scope())

        return result, args

    def _run_run_ffprobe(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = run_project_media_tool(self.context.project_id, "ffprobe", args)

        return result, args

    def _run_run_ffmpeg(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = run_project_media_tool(self.context.project_id, "ffmpeg", args)

        return result, args

    def _run_get_asset_range_context(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "project":
            raise ValueError("资产范围规划只允许在项目会话中执行")
        result = get_asset_range_context(
            self.context.project_id, source_id=str(args.get("sourceId") or ""),
            target_units=args.get("targetUnits"), part=str(args.get("part") or ""),
            asset_range_id=str(args.get("assetRangeId") or ""),
        )
        if result.get("success"):
            key = (str(args.get("sourceId") or ""), str(args.get("assetRangeId") or ""),
                   str(args.get("targetUnits") or ""))
            self._asset_range_read_versions.setdefault(key, {})[str(args.get("part"))] = str(result["contextVersion"])
        return result, args

    def _run_submit_asset_range_candidate(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "project":
            raise ValueError("资产范围规划只允许在项目会话中执行")
        with _LOCK:
            self._require_current_running_execution()
            version = str(args.get("contextVersion") or "")
            # Source IDs and target units can be supplied explicitly after the first read.
            # The content-bound version, rather than argument spelling, identifies the same inputs.
            read_parts = {part for versions in self._asset_range_read_versions.values()
                          for part, read_version in versions.items() if version and read_version == version}
            if not {"source_text", "planning_state", "phase_visuals"}.issubset(read_parts):
                return {"success": False, "status": "rejected", "projectChanged": False,
                        "message": "请读取同一版本的原文、规划状态和阶段视觉后再提交",
                        "errors": [{"path": "contextVersion", "code": "context_not_read",
                                    "message": "三项专用资料缺失或来自不同版本，请重新读取后核对结果",
                                    "repairAction": "reread_context"}]}, args
            result = submit_asset_range_candidate(
                self.context.project_id, args, session_id=str(self.context.session_id or ""),
                user_instruction=str(self.context.message or ""),
                previous_pending=self.context.pending_operation_context,
            )
            if result.get("status") == "pending_confirmation" and result.get("candidateId"):
                confirmed = confirm_asset_range_locally(
                    self.context.project_id, self.context.session_id, self.context.session_policy,
                    candidate_ref=self._candidate_ref(result),
                )
                result = self._auto_committed_candidate_result(
                    "asset_range_propose", result, confirmed,
                    target_id=str((result.get("proposal") or {}).get("rangeId") or ""),
                )
        return result, args

    def _run_get_asset_extraction_context(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "project":
            raise ValueError("资产拆分只允许在项目会话中执行")
        result = get_asset_extraction_context(
            self.context.project_id, asset_range_id=str(args.get("assetRangeId") or ""),
            session_id=str(self.context.session_id or ""), part=str(args.get("part") or ""),
            offset=args.get("offset", 0),
            queries=args.get("queries"), relative_path=str(args.get("relativePath") or ""),
            line_start=args.get("lineStart", 1), line_count=args.get("lineCount", 80),
        )
        if result.get("success"):
            self._asset_context_ready = True
            self._asset_extraction_read_versions.setdefault(str(result["assetRangeId"]), {})[
                str(args.get("part"))] = str(result["inputDigest"])
        return result, args

    def _run_get_asset_extraction_asset_catalog(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "project":
            raise ValueError("资产目录只允许在项目会话中读取")
        return get_asset_extraction_asset_catalog(
            self.context.project_id, asset_type=str(args.get("assetType") or ""),
            offset=args.get("offset", 0), limit=args.get("limit", 20),
        ), args

    def _run_submit_asset_extraction_result(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(self.context.session_policy, dict) or self.context.session_policy.get("scope") != "project":
            raise ValueError("资产拆分只允许在项目会话中提交")
        with _LOCK:
            self._require_current_running_execution()
            version = str(args.get("inputDigest") or "")
            versions = self._asset_extraction_read_versions.get(str(args.get("assetRangeId") or ""), {})
            required = {"source_text", "task_state", "identity_index"}
            batch = args.get("assetBatch") or {}
            if any(not item.get("assetId") for kind in ("characters", "creatures", "scenes", "props")
                   for item in (batch.get(kind) or []) if isinstance(item, dict)):
                required.add("design_context")
            missing = sorted(part for part in required if not version or versions.get(part) != version)
            stale = sorted(part for part, read_version in versions.items() if read_version != version)
            if missing or stale:
                return {"success": False, "status": "rejected", "projectChanged": False,
                        "message": "请按同一版本读取资产拆分依据后再提交",
                        "errors": [{"path": "inputDigest", "code": "context_not_read",
                                    "message": "需重新读取并核对：" + "、".join(sorted(set(missing + stale))),
                                    "repairAction": "reread_context"}]}, args
            execution_id = str(current_execution_id(self.context.session_id) or "")
            return submit_asset_extraction_result(
                self.context.project_id, args, session_id=str(self.context.session_id or ""),
                execution_id=execution_id, user_instruction=str(self.context.message or ""),
            ), args


    def _run_publish_task_report(self, args: dict[str, Any], selected_episode_id: str, node_id: str, user_instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        receipt_id = self._tool_arg(args, "receiptId")
        receipt = self._commit_receipts.get(receipt_id)
        execution_id = current_execution_id(self.context.session_id)
        if not receipt or not execution_id or receipt.get("executionId") != execution_id:
            raise ValueError("只能报告本轮已正式提交且已核验的结果；请使用提交工具返回的 receiptId。")
        if receipt_id in self._published_reports:
            previous = copy.deepcopy(self._published_reports[receipt_id])
            self.last_published_report = str(previous["reportText"])
            self.last_published_receipt = copy.deepcopy(receipt)
            previous["status"] = "already_published"
            return previous, args

        summary = re.sub(r"\s+", " ", str(args.get("summary") or "")).strip()
        task_type = str(receipt.get("taskType") or "").strip()
        if task_type != "director_plan_generation" and len(summary) > 180:
            raise ValueError("完成报告应简短；summary 最多 180 字。")
        task_label = {
            "asset_range_propose": "资产范围规划",
            "episode_boundary_propose": "分集规划",
            "asset_extraction": "资产拆分",
            "workflow_cinematic_script_generation": "剧本创作",
            "director_plan_generation": "分镜脚本生成",
            "video_prompt_generation": "视频提示词生成",
            "video_prompt_optimization": "视频提示词优化",
            "video_prompt_standalone_generation": "视频提示词生成",
        }.get(task_type, "任务")
        report_text = self._boundary_completion_reports.get(receipt_id) or (
            f"{task_label}：{summary}" if summary else f"{task_label}已完成，结果已更新到项目。"
        )
        if task_type == "director_plan_generation":
            shot_count, group_count = receipt.get("shotCount"), receipt.get("allocationGroupCount")
            if any(type(value) is not int or value <= 0 for value in (shot_count, group_count)):
                raise ValueError("分镜提交回执缺少可信镜头数或分组数，不能发布完成报告。")
            if receipt.get("operation") in {"frame_patch", "visual_field_patch"}:
                numbers = receipt.get("revisedShotNos") or []
                report_text = (f"分镜视觉字段专项修订：已更新 {receipt['episodeId']} 的镜头 "
                               + "、".join(str(number) for number in numbers)
                               + " 的起始画面；其余分镜字段由正式稿保留，受影响图片需重生。")
            else:
                report_text = (f"分镜脚本生成：已为 {receipt['episodeId']} 当前片段提交 "
                               f"{shot_count} 个镜头、{group_count} 个视频分组。")
                for field, label in (("speechBudgetNote", "制作说明"), ("reworkRecordWarning", "修改记录提示")):
                    note = str(receipt.get(field) or "").strip()
                    if note:
                        report_text += f"\n{label}：{note}"
        result = {
            "success": True,
            "status": "published",
            "reportId": f"report-{receipt_id}",
            "receiptId": receipt_id,
            "reportText": report_text,
            "message": report_text,
            "commitReceipt": copy.deepcopy(receipt),
        }
        self._published_reports[receipt_id] = copy.deepcopy(result)
        self.last_published_report = report_text
        self.last_published_receipt = copy.deepcopy(receipt)
        return result, args

    _handlers = {
        'get_conversation_history': _run_get_conversation_history,
        'list_workflow_node_versions': _run_list_workflow_node_versions,
        'read_workflow_node_version': _run_read_workflow_node_version,
        'read_source_window': _run_read_source_window,
        'search_source_text': _run_search_source_text,
        'get_source_coverage': _run_get_source_coverage,
        'get_episode_boundary_context': _run_get_episode_boundary_context,
        'update_project_settings': _run_update_project_settings,
        'submit_episode_boundary_candidate': _run_submit_episode_boundary_candidate,
        'get_plot_split_context': _run_get_plot_split_context,
        'submit_plot_split_candidate': _run_submit_plot_split_candidate,
        'get_cinematic_script_context': _run_get_cinematic_script_context,
        'submit_cinematic_script_result': _run_submit_cinematic_script_result,
        'get_director_plan_context': _run_get_director_plan_context,
        'validate_director_plan_draft': _run_validate_director_plan_draft,
        'submit_director_plan_result': _run_submit_director_plan_result,
        'get_video_prompt_context': _run_get_video_prompt_context,
        'submit_video_prompt_result': _run_submit_video_prompt_result,
        'get_video_prompt_optimization_context': _run_get_video_prompt_optimization_context,
        'submit_video_prompt_optimization_result': _run_submit_video_prompt_optimization_result,
        'get_video_prompt_standalone_context': _run_get_video_prompt_standalone_context,
        'submit_video_prompt_standalone_result': _run_submit_video_prompt_standalone_result,
        'start_business_task': _run_start_business_task,
        'get_asset_range_context': _run_get_asset_range_context,
        'submit_asset_range_candidate': _run_submit_asset_range_candidate,
        'get_asset_extraction_context': _run_get_asset_extraction_context,
        'get_asset_extraction_asset_catalog': _run_get_asset_extraction_asset_catalog,
        'submit_asset_extraction_result': _run_submit_asset_extraction_result,
        'save_story_world_map': _run_save_story_world_map,
        'upsert_asset': _run_upsert_asset,
        'delete_asset': _run_delete_asset,
        'delete_all_project_assets': _run_delete_all_project_assets,
        'save_episode_work_chain_plan': _run_save_episode_work_chain_plan,
        'patch_shot_prompt': _run_patch_shot_prompt,
        'upsert_workflow_node': _run_upsert_workflow_node,
        'delete_workflow_node': _run_delete_workflow_node,
        'delete_project_planning_outputs': _run_delete_project_planning_outputs,
        'save_workflow_node_inline_edit': _run_save_workflow_node_inline_edit,
        'create_workflow_task_card': _run_create_workflow_task_card,
        'add_workflow_asset_nodes': _run_add_workflow_asset_nodes,
        'update_workflow_route': _run_update_workflow_route,
        'link_workflow_input': _run_link_workflow_input,
        'unlink_workflow_input': _run_unlink_workflow_input,
        'list_workflow_inputs': _run_list_workflow_inputs,
        'validate_project_quality': _run_validate_project_quality,
        'request_storyboard_image_generation': _run_request_storyboard_image_generation,
        'request_visual_handoff_image_generation': _run_request_visual_handoff_image_generation,
        'request_storyboard_video_generation': _run_request_storyboard_video_generation,
        'edit_storyboard_image': _run_edit_storyboard_image,
        'request_route_video_generation': _run_request_route_video_generation,
        'request_asset_image_generation': _run_request_asset_image_generation,
        'list_generation_tasks': _run_list_generation_tasks,
        'cancel_generation_task': _run_cancel_generation_task,
        'request_project_export': _run_request_project_export,
        'list_director_rules': _run_list_director_rules,
        'search_director_rules': _run_search_director_rules,
        'read_director_rule': _run_read_director_rule,
        'list_project_files': _run_list_project_files,
        'search_project_files': _run_search_project_files,
        'read_project_file': _run_read_project_file,
        'run_ffprobe': _run_run_ffprobe,
        'run_ffmpeg': _run_run_ffmpeg,
        'publish_task_report': _run_publish_task_report,
    }
