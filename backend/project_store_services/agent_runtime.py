# -*- coding: utf-8 -*-
"""智能体公开消息/问答入口与历史 API 的显式名称导出。

领域实现直接依赖自己的实际所有者；本模块不再被拆出模块反向导入。
"""
from __future__ import annotations

import re
from .agent_action_contract import (
    _AGENT_ACTION_ORDER,
    _AGENT_ALLOWED_ACTIONS,
    _AGENT_BACKGROUND_ACTIONS,
    _AGENT_PROGRAM_DIRECT_ACTIONS,
    _agent_action_description,
    _agent_action_icon,
    _agent_action_order,
    _agent_action_order_for_session_policy,
    _agent_action_prompt,
    _agent_allowed_actions,
    _agent_episode_title_reference,
    _agent_is_background_action,
    _agent_is_plot_split_quick_control_message,
    _agent_plot_split_quick_prompt,
    _agent_program_action_from_message,
    _agent_program_direct_actions,
    _agent_quick_prompts,
    _agent_quick_prompts_for_session_policy,
    _agent_task_catalog_for_session_policy,
    _agent_validate_action,
    _agent_validate_task_type,
)
from .agent_asset_cleanup import (
    _agent_clear_asset_range_outputs,
    _agent_delete_latest_asset_range_outputs,
)
from .agent_asset_range_state import (
    _AGENT_ASSET_REPORT_TYPES,
    _ASSET_RANGE_ANALYSIS_COMPLETED_STATUSES,
    _agent_asset_range_analysis_completed,
    _agent_asset_range_analysis_status,
    _agent_asset_range_bounds,
    _agent_asset_range_id_tokens,
    _agent_asset_range_label,
    _agent_asset_range_output_preview,
    _agent_asset_range_user_label,
    _agent_blocking_asset_analysis_ranges,
    _agent_current_source_asset_ranges,
    _agent_latest_asset_range_row,
    _agent_range_int,
    _agent_remove_asset_range_refs_from_asset,
    _agent_source_coverage_safe,
)
from .agent_canvas_events import (
    _CANVAS_MUTATION_ENVELOPE_KEYS,
    _agent_project_effect_from_save,
    _canvas_changed_resource_name,
    _canvas_mutation_event_fields,
    _canvas_mutation_event_payload,
    _canvas_mutation_event_source_rows,
    _canvas_mutation_has_envelope,
    _canvas_mutation_payload,
    _canvas_mutation_single_sync_mutation,
    _emit_agent_project_effect,
    _merge_changed_resources,
)
from .agent_capabilities import (
    _agent_skill_frontmatter,
    list_agent_skills,
)
from .agent_context_runtime import (
    _agent_episode_number,
    _agent_json_object_from_text,
    _load_agent_ops_permissions,
)
from .agent_contracts import (
    _AGENT_PRODUCTION_STEP_STATES,
    _agent_action_footer_instruction,
    _agent_chinese_ordinal_value,
    _agent_compact_message_for_intent,
    _agent_confirmation_reply_instruction,
    _agent_continue_reply_instruction,
)
from .agent_conversation_context import (
    _agent_conversation_context_for_prompt,
    _agent_intent_conversation_context_for_prompt,
    _agent_sdk_session_id_for_resume,
    _agent_session_history_summary_for_prompt,
    _agent_session_messages_for_prompt,
    _agent_turn_context_scope,
    _agent_turn_session_episode_id,
    _agent_turn_workflow_id,
    _apply_agent_session_context,
    _save_agent_turn_conversation_context,
)
from .agent_file_tools import (
    AGENT_ASSET_CONTEXT_FILE_ALLOWED_PATHS,
    AGENT_ASSET_CONTEXT_FILE_ALLOWED_PREFIXES,
    AGENT_MEDIA_CONTEXT_FILE_ALLOWED_PREFIXES,
    AGENT_MEDIA_CONTEXT_ROOT_FILE_EXTENSIONS,
    AGENT_PROJECT_FILE_ASSET_CONTEXT_SCOPES,
    AGENT_PROJECT_FILE_BLOCKED_READ_PATHS,
    AGENT_PROJECT_FILE_BLOCKED_READ_PREFIXES,
    AGENT_PROJECT_FILE_MEDIA_CONTEXT_SCOPES,
    _agent_media_arg_looks_like_path,
    _agent_media_tool_args,
    _agent_media_tool_int,
    _agent_media_tool_project_root,
    _agent_media_tool_reject_unsafe_text,
    _agent_media_tool_resolve_arg,
    _agent_project_file_entry,
    _truncate_process_text,
    list_project_files_for_agent,
    read_project_file_for_agent,
    run_project_media_tool,
    search_project_files_for_agent,
)
from .agent_scope_hints import _agent_message_requests_episode_detail

from .agent_model_runtime import (
    _agent_api_key_looks_like_placeholder,
    _agent_configured_model_summary,
    _agent_provider_connection_test_error,
    _agent_runtime_config_failure_message,
    _agent_sdk_runtime_config,
)
from .agent_output_validation import (
    _agent_focus_workflow_node_id,
    _asset_ref_in_confirmed_range,
    _quality_node_ids_for_generation_task,
    _update_agent_workflow,
    validate_project_quality,
)
from .agent_pending_operations import (
    _agent_clear_pending_operation_state,
    _agent_current_message_allows_model_user_instruction,
    _agent_message_cancels_destructive_operation,
    _agent_message_confirms,
    _agent_message_confirms_destructive_operation,
    _agent_message_continues_flow,
    _agent_message_is_direct_control_instruction,
    _agent_message_is_pending_operation_confirmation_reply,
    _agent_message_is_pending_operation_protocol_reply,
    _agent_pending_operation_action_footer,
    _agent_pending_operation_context,
    _agent_pending_operation_from_tool_result,
    _agent_pending_operation_interaction_policy_for_kind,
    _agent_pending_operation_kind,
    _agent_pending_operation_matches_coverage,
    _agent_pending_operation_reproposal_task_type,
    _agent_pending_operation_requires_semantic_probe,
    _agent_pending_operation_revision_instruction,
    _agent_session_pending_operation_for_prompt,
    _agent_without_user_instruction_fields,
    _plot_split_initial_user_instruction,
    _plot_split_pending_operation,
    _plot_split_pending_retry_fields,
    _plot_split_source_ref_from_input_ref,
)
from .agent_plot_contract import (
    PLOT_SPLIT_PROPOSAL_STRUCTURED_SCHEMA,
    _PLOT_SPLIT_REVISION_REQUIREMENT_CHARS,
    _PLOT_SPLIT_REVISION_REQUIREMENT_LIMIT,
    _agent_compact_plot_split_commit_payload,
    _agent_compact_plot_split_proposal,
    _agent_compact_plot_split_shots,
    _agent_plot_split_proposal_from_pending_operation,
    _agent_plot_split_revision_count,
    _agent_plot_split_revision_requirements,
    _plot_split_proposal_message,
    _work_chain_planning_source_ref,
)
from .agent_production_controller import (
    _agent_direct_production_task_hypothesis,
    _agent_generation_controller_started_result,
    _execute_agent_action,
    _run_workflow_storyboard_image_generation_controller,
    _run_workflow_storyboard_video_generation_controller,
    _run_workflow_visual_handoff_image_generation_controller,
)
from .agent_production_scope import (
    _AGENT_ASSET_IMAGE_TYPES,
    _agent_asset_image_root_identity,
    _agent_collect_asset_ref_keys,
    _agent_current_flow_asset_image_keys,
    _agent_current_flow_director_board_node_id,
    _agent_current_flow_prompt_storyboard_node_id,
    _agent_current_flow_workflow_node_id,
    _agent_episode_sort_key_for_id,
    _agent_episode_title_for_agent,
    _agent_flow_node_data,
    _agent_flow_node_matches_scope,
    _agent_flow_node_route_id,
    _agent_flow_node_work_chain_id,
    _agent_flow_step_instruction,
    _agent_generation_flow_step_hypothesis,
    _agent_latest_episode_id_for_agent,
    _agent_normalize_asset_image_type,
    _agent_production_status_from_state,
    _agent_project_episode_rows_for_agent,
    _agent_recommendation_node_id,
    _agent_route_ids_for_work_chain,
)
from .agent_progress_recommendations import (
    _AGENT_CONTROL_ONLY_QUICK_PROMPT_MESSAGES,
    _AGENT_CONTROL_ONLY_TASK_TYPES,
    _AGENT_DEFAULT_PRODUCTION_TASK_TYPES,
    _AGENT_PRODUCTION_TASK_COMPLETED_MESSAGES,
    _AGENT_STALE_PRODUCTION_RECOMMENDATION_MESSAGE,
    _agent_action_label,
    _agent_episode_boundary_ready,
    _agent_episode_production_progress,
    _agent_next_running_step_id,
    _agent_overview_ready,
    _agent_progress_message,
    _agent_progress_state,
    _agent_project_effect_for_action,
    _agent_project_status_result,
    _agent_recommendation_item,
    _agent_recommended_action,
    _agent_recommended_next_step,
    _agent_result_content_blocks,
    _agent_source_total_chars,
    _agent_stage_next_step_label,
    _agent_stage_recommendations,
    _agent_steps_from_state,
    _agent_task_progress_content_block,
    _agent_tool_result_summary,
    _agent_workflow_explainer,
)
from .agent_prompt_context import (
    _agent_overview_context_for_prompt,
    _agent_source_context_for_prompt,
)

from .agent_requirements import (
    _AGENT_PROGRAM_WORK_DEFINITIONS,
    _REQUIREMENT_EXTRACTOR_CACHE,
    _REQUIREMENT_EXTRACTOR_CACHE_LOCK,
    _REQUIREMENT_EXTRACTOR_CACHE_MAX,
    _agent_clean_work_requirement_constraint,
    _agent_dialogue_rows_for_requirement_extractor,
    _agent_empty_extracted_requirements,
    _agent_extract_work_requirements,
    _agent_extract_worker_requirements,
    _agent_normalize_extracted_requirements,
    _agent_program_work_effective_instruction,
    _agent_requirement_extractor_cache_key,
    _agent_requirement_extractor_payload,
    _agent_requirement_extractor_prompt,
    _agent_requirement_extractor_skip_reason,
    _agent_requirement_extractor_system_prompt,
    _agent_requirement_is_action_only,
    _agent_work_definition,
)
from .agent_result_presentation import (
    _AGENT_USER_FACING_TOOL_LABELS,
    _agent_append_action_reply_instruction,
    _agent_append_text_content_block,
    _agent_attach_action_footer_instruction,
    _agent_blocks_have_action_footer,
    _agent_decision_content_blocks,
    _agent_decision_requires_answer,
    _agent_followup_progress_state,
    _agent_maybe_append_completion_next_step,
    _agent_next_step_action_footer,
    _agent_normalize_result_action_footer_blocks,
    _agent_normalize_turn_decision,
    _agent_pending_question_from_decision,
    _agent_result_background_started,
    _agent_result_episode_id_for_followup,
    _agent_result_suppresses_session_message,
    _agent_result_waits_for_background_session_report,
    _agent_sanitize_pending_question,
    _agent_sanitize_user_facing_content_blocks,
    _agent_sanitize_user_facing_text,
    _agent_session_policy_rejection,
    _agent_turn_result_from_worker_decision,
    _agent_controller_decision_from_result,
)
from .agent_session_events import (
    _agent_session_payload,
    _emit_agent_session_update,
)
from .agent_session_lifecycle import (
    _resolve_agent_turn_result,
)
from .agent_session_results import (
    _agent_generation_task_project_effect,
    _agent_generation_task_report_message,
    _agent_generation_task_session_id,
    _agent_runtime_config_failure_result,
    _finish_agent_session_local_result,
    _finish_agent_session_policy_rejection,
    _finish_agent_session_result,
    _interrupt_agent_session_state,
    append_agent_generation_task_session_report,
    interrupt_agent_session,
)
from .agent_sessions import (
    _load_agent_sessions,
    _normalize_agent_pending_question,
)
from .agent_turn_execution import (
    _agent_turn_background_worker,
    _run_agent_inline_turn,
    _start_agent_background_turn,
)
from .agent_turn_routing import (
    _agent_result_used_sdk_stream,
    _agent_turn_requires_sdk_runtime,
)
from .agent_task_status import (
    _agent_task_error_text,
    _agent_task_failure_fields,
    _agent_update_task_if_active,
)
from .director_rules import (
    list_director_rules_for_agent,
    read_director_rule_for_agent,
    search_director_rules_for_agent,
)
from .source_text_store import _compact_text
from .task_control import (
    _update_task_fields,
)
from typing import (
    Any,
)


def run_agent_message(
    project_id: str,
    episode_id: str | None,
    message: str = "",
    images: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    preferred_action: str | None = None,
    preferred_task_type: str | None = None,
    display_message: str | None = None,
    quick_prompt_id: str | None = None,
    control_only: bool = False,
    scope: str | None = None,
    workflow_id: str | None = None,
    active_target: dict[str, Any] | None = None,
    candidate_ref: dict[str, Any] | None = None,
    task_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # preferred_action / preferred_task_type 只来自结构化快捷入口或智能体推荐项；
    # 二者先过白名单，随后可能直接路由到对应的本地 controller。
    return _start_agent_background_turn(
        project_id,
        episode_id,
        message=message,
        images=images,
        session_id=session_id,
        preferred_action=preferred_action,
        preferred_task_type=preferred_task_type,
        display_message=display_message,
        quick_prompt_id=quick_prompt_id,
        control_only=control_only,
        scope=scope,
        workflow_id=workflow_id,
        active_target=active_target,
        candidate_ref=candidate_ref,
        task_options=task_options,
    )


def _agent_answer_candidates(value: Any) -> list[str]:
    if isinstance(value, list):
        rows = value
    else:
        rows = re.split(r"[,，、;；\n]+", str(value or ""))
    return [str(item or "").strip() for item in rows if str(item or "").strip()]


def _agent_answers_summary(answers: Any) -> str:
    if not isinstance(answers, dict):
        return ""
    rows: list[str] = []
    for key, value in answers.items():
        label = str(key or "").strip()
        text = "、".join(_agent_answer_candidates(value))
        if not text:
            continue
        rows.append(f"{label}：{text}" if label else text)
    return "；".join(rows)


def _agent_pending_option_label(
    pending_question: dict[str, Any] | None,
    action: str,
) -> str:
    if not isinstance(pending_question, dict):
        return ""
    for question in pending_question.get("questions") or []:
        if not isinstance(question, dict):
            continue
        for option in question.get("options") or []:
            if (
                isinstance(option, dict)
                and str(option.get("value") or "").strip() == action
            ):
                return str(option.get("label") or "").strip()
    return ""


def _agent_action_from_answers(
    answers: Any,
    pending_question: dict[str, Any] | None = None,
) -> str:
    if not isinstance(answers, dict):
        return ""
    allowed = _agent_allowed_actions()
    if isinstance(pending_question, dict):
        for question in pending_question.get("questions") or []:
            if not isinstance(question, dict):
                continue
            question_key = str(question.get("question") or "").strip()
            for candidate in _agent_answer_candidates(answers.get(question_key)):
                if candidate in allowed:
                    return candidate
                for option in question.get("options") or []:
                    if not isinstance(option, dict):
                        continue
                    option_value = str(option.get("value") or "").strip()
                    option_label = str(option.get("label") or "").strip()
                    if option_value in allowed and candidate == option_label:
                        return option_value
    for value in answers.values():
        for candidate in _agent_answer_candidates(value):
            if candidate in allowed:
                return candidate
            if isinstance(pending_question, dict):
                for question in pending_question.get("questions") or []:
                    if not isinstance(question, dict):
                        continue
                    for option in question.get("options") or []:
                        if not isinstance(option, dict):
                            continue
                        option_value = str(option.get("value") or "").strip()
                        option_label = str(option.get("label") or "").strip()
                        if option_value in allowed and candidate == option_label:
                            return option_value
    return ""


def answer_agent_question(
    project_id: str,
    episode_id: str | None,
    question_id: str,
    action: str,
    label: str = "",
    session_id: str | None = None,
    answers: dict[str, Any] | None = None,
    scope: str | None = None,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    session = None
    pending: dict[str, Any] | None = None
    session_id = str(session_id or "").strip() or None
    if session_id:
        session = next(
            (row for row in _load_agent_sessions(project_id) if str(row.get("id") or "") == str(session_id)),
            None,
        )
    if not isinstance(session, dict):
        raise FileNotFoundError("智能体会话不存在")
    pending = _normalize_agent_pending_question(session.get("pendingQuestion"))
    if not pending:
        raise ValueError("当前智能体没有待回答问题，请刷新会话后重试")
    if str(pending.get("questionId") or "") != str(question_id or ""):
        raise ValueError("智能体待回答问题已更新，请刷新后重试")
    session_scope = str(session.get("contextScope") or session.get("scope") or "").strip()
    session_episode_id = str(session.get("episodeId") or session.get("episode_id") or "").strip()
    effective_scope = session_scope or str(scope or "").strip() or None
    effective_episode_id = session_episode_id or str(episode_id or "").strip() or None
    context_scope = _agent_turn_context_scope(effective_scope, effective_episode_id)
    episode_candidate = str(effective_episode_id or "").strip()
    if context_scope == "project":
        turn_episode_id = "__project__"
    elif episode_candidate in {"", "__project__"} or episode_candidate.casefold() == "project":
        turn_episode_id = str(episode_id or "").strip() or "E01"
    else:
        turn_episode_id = episode_candidate
    progress_episode_id = None if context_scope == "project" else turn_episode_id
    workflow_id_value = str(workflow_id or session.get("workflowId") or session.get("workflow_id") or "").strip() or None
    state = _agent_progress_state(project_id, progress_episode_id)
    answer_summary = _agent_answers_summary(answers or {})
    # 待回答问题的 action 来自智能体上一轮问题和用户选择，
    # 这是智能体介导的继续执行，不是普通聊天文本的本地关键词匹配。
    if str(action or "").strip():
        selected_action = _agent_validate_action(action)
    else:
        selected_action = _agent_action_from_answers(answers or {}, pending)
        if selected_action:
            selected_action = _agent_validate_action(selected_action)
    display_label = (
        str(label or "").strip()
        or (_agent_pending_option_label(pending, selected_action) if selected_action else "")
        or answer_summary
        or "已回答"
    )
    answer_text = (
        f"我回答：{_compact_text(display_label, 160)}。"
        "请基于这个选择继续判断并执行下一步。"
    )
    if answer_summary:
        answer_text += f"\n补充答案：{_compact_text(answer_summary, 500)}"
    assistant_notice = (
        f"收到你的选择，我会继续执行：{_agent_action_label(selected_action, state)}。"
        if selected_action
        else "收到你的回答，我会继续判断下一步。"
    )
    return _start_agent_background_turn(
        project_id,
        turn_episode_id,
        message=answer_text,
        images=[],
        session_id=session_id,
        preferred_action=selected_action or None,
        assistant_notice=assistant_notice,
        append_user_message=True,
        scope=context_scope,
        workflow_id=workflow_id_value,
    )


__all__ = (
    '_asset_ref_in_confirmed_range', '_quality_node_ids_for_generation_task',
    'validate_project_quality',
    '_update_agent_workflow', '_agent_overview_ready', '_agent_episode_boundary_ready',
    '_agent_episode_production_progress', '_agent_progress_state', '_agent_steps_from_state', '_agent_task_progress_content_block',
    '_agent_result_content_blocks', '_agent_tool_result_summary', '_agent_project_effect_for_action',
    '_agent_action_label', '_agent_recommended_action', '_agent_recommendation_item',
    '_agent_stage_recommendations', '_agent_stage_next_step_label', '_agent_progress_message',
    '_agent_workflow_explainer',
    '_execute_agent_action', '_AGENT_BACKGROUND_ACTIONS', '_AGENT_ALLOWED_ACTIONS', '_AGENT_ACTION_ORDER',
    '_AGENT_PROGRAM_DIRECT_ACTIONS', '_load_agent_ops_permissions',
    '_agent_allowed_actions', '_agent_action_order', '_agent_program_direct_actions',
    '_agent_program_action_from_message',
    '_agent_is_background_action',
    '_agent_validate_action', '_agent_action_description', '_agent_action_prompt', '_agent_action_icon',
    '_agent_skill_frontmatter', 'list_agent_skills', '_agent_session_messages_for_prompt',
    '_agent_session_history_summary_for_prompt', '_agent_sdk_session_id_for_resume',
    '_agent_conversation_context_for_prompt', '_agent_source_context_for_prompt',
    '_agent_overview_context_for_prompt',
    '_agent_decision_requires_answer', '_agent_sanitize_pending_question',
    '_agent_pending_question_from_decision', '_agent_decision_content_blocks', '_agent_normalize_turn_decision',
    '_agent_sdk_runtime_config', '_truncate_process_text',
    '_agent_media_tool_project_root', '_agent_media_tool_int', '_agent_media_tool_reject_unsafe_text',
    '_agent_media_arg_looks_like_path', '_agent_media_tool_resolve_arg', '_agent_media_tool_args',
    '_agent_project_file_entry', 'list_project_files_for_agent', 'search_project_files_for_agent',
    'read_project_file_for_agent', 'list_director_rules_for_agent', 'search_director_rules_for_agent',
    'read_director_rule_for_agent', 'run_project_media_tool',
    '_agent_configured_model_summary',
    '_agent_result_used_sdk_stream',
    '_update_task_fields', '_agent_session_payload', '_emit_agent_session_update', '_emit_agent_project_effect',
    '_finish_agent_session_result', 'append_agent_generation_task_session_report',
    '_interrupt_agent_session_state', 'interrupt_agent_session',
    '_agent_next_running_step_id', '_resolve_agent_turn_result', '_start_agent_background_turn',
    '_run_agent_inline_turn', '_agent_turn_background_worker', 'run_agent_message', '_agent_answer_candidates',
    '_agent_answers_summary', '_agent_pending_option_label', '_agent_action_from_answers',
    'answer_agent_question'
)
