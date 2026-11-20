# -*- coding: utf-8 -*-
"""Explicit public API for the ai-video project store domains.

Dependencies are imported by their consuming domain; package exports never mutate
service namespaces. The static export table preserves the established public API.
"""
from __future__ import annotations

from types import ModuleType
from typing import Any
from . import catalogs as catalogs
from . import runtime_state as runtime_state
from . import store_core as store_core
from . import provider_models as provider_models
from . import settings_loaders as settings_loaders
from . import agent_sessions as agent_sessions
from . import canvas_runtime_store_v4 as canvas_runtime_store_v4
from . import projects as projects
from . import provider_connections as provider_connections
from . import splitting_templates as splitting_templates
from . import storyboard_templates as storyboard_templates
from . import director_rules as director_rules
from . import media_files as media_files
from . import video_clips as video_clips
from . import model_clients as model_clients
from . import style_analysis as style_analysis
from . import project_management as project_management
from . import assets as assets
from . import sources as sources
from . import planning as planning
from . import agent_runtime as agent_runtime
from . import workflows as workflows
from . import tasks as tasks
from . import archive_transfers as archive_transfers
from . import exports as exports
from . import production_status as production_status
from . import favorite_styles as favorite_styles

_MODULES: tuple[ModuleType, ...] = (
    catalogs,
    runtime_state,
    store_core,
    provider_models,
    settings_loaders,
    agent_sessions,
    canvas_runtime_store_v4,
    projects,
    provider_connections,
    splitting_templates,
    storyboard_templates,
    director_rules,
    media_files,
    video_clips,
    model_clients,
    style_analysis,
    project_management,
    assets,
    sources,
    planning,
    agent_runtime,
    workflows,
    tasks,
    archive_transfers,
    exports,
    production_status,
    favorite_styles,
)

from .agent_action_contract import (
    _AGENT_ACTION_ORDER, _AGENT_ALLOWED_ACTIONS, _AGENT_BACKGROUND_ACTIONS,
    _AGENT_PROGRAM_DIRECT_ACTIONS, _agent_action_description, _agent_action_icon, _agent_action_label,
    _agent_action_order, _agent_action_prompt, _agent_allowed_actions, _agent_is_background_action,
    _agent_program_action_from_message, _agent_program_direct_actions,
    _agent_validate_action,
)

from .agent_canvas_events import (
    _emit_agent_project_effect,
)

from .agent_capabilities import (
    _agent_skill_frontmatter, list_agent_skills,
)

from .agent_context_runtime import (
    _load_agent_ops_permissions,
)

from .agent_contracts import (
    _agent_steps_from_state,
)

from .agent_conversation_context import (
    _agent_conversation_context_for_prompt, _agent_sdk_session_id_for_resume,
    _agent_session_history_summary_for_prompt, _agent_session_messages_for_prompt,
)

from .agent_file_tools import (
    _agent_media_arg_looks_like_path, _agent_media_tool_args, _agent_media_tool_int,
    _agent_media_tool_project_root, _agent_media_tool_reject_unsafe_text, _agent_media_tool_resolve_arg,
    _agent_project_file_entry, _truncate_process_text, list_project_files_for_agent,
    read_project_file_for_agent, run_project_media_tool, search_project_files_for_agent,
)

from .agent_model_runtime import (
    _agent_configured_model_summary, _agent_sdk_runtime_config,
)

from .agent_output_validation import (
    _asset_ref_in_confirmed_range,
    _quality_node_ids_for_generation_task, _update_agent_workflow,
    validate_project_quality,
)

from .agent_production_controller import (
    _execute_agent_action,
)

from .agent_progress_recommendations import (
    _agent_episode_boundary_ready, _agent_episode_production_progress, _agent_next_running_step_id,
    _agent_overview_ready, _agent_progress_message, _agent_progress_state,
    _agent_project_effect_for_action, _agent_recommendation_item, _agent_recommended_action,
    _agent_result_content_blocks, _agent_stage_next_step_label, _agent_stage_recommendations,
    _agent_task_progress_content_block, _agent_tool_result_summary, _agent_workflow_explainer,
)

from .agent_prompt_context import (
    _agent_overview_context_for_prompt, _agent_source_context_for_prompt,
)

from .agent_result_presentation import (
    _agent_decision_content_blocks, _agent_decision_requires_answer, _agent_normalize_turn_decision,
    _agent_pending_question_from_decision, _agent_sanitize_pending_question,
)

from .agent_runtime import (
    _agent_action_from_answers, _agent_answer_candidates, _agent_answers_summary,
    _agent_pending_option_label, answer_agent_question, run_agent_message,
)

from .agent_session_events import (
    _agent_session_payload, _emit_agent_session_update,
)

from .agent_session_lifecycle import (
    _resolve_agent_turn_result,
)

from .agent_session_results import (
    _finish_agent_session_result, _interrupt_agent_session_state,
    append_agent_generation_task_session_report, interrupt_agent_session,
)

from .agent_sessions import (
    _AGENT_UI_ONLY_RECOMMENDATION_ACTIONS, _AGENT_UI_ONLY_RECOMMENDATION_PATTERNS,
    _PERSISTENT_MEDIA_DATA_KEYS, _agent_action_footer_text,
    _agent_attach_action_footer_to_content_blocks, _agent_attachment_error_content_block,
    _agent_attachment_input_from_block, _agent_attachment_ref_from_path,
    _agent_blocks_from_attachment_fields, _agent_blocks_have_body_text, _agent_blocks_have_text,
    _agent_content_block_log_details, _agent_draft_turn_from_stream_blocks,
    _agent_file_attachment_input_from_block, _agent_file_content_block_from_ref,
    _agent_image_attachment_input_from_block, _agent_image_content_block_from_ref,
    _agent_is_ui_only_recommendation, _agent_live_activity_for_turn,
    _agent_live_activity_from_stream_blocks, _agent_log_date_key, _agent_log_sanitize,
    _agent_merge_action_footer_values, _agent_message_attachment_rows, _agent_message_is_control_only,
    _agent_message_row, _agent_message_summary_line, _agent_session_detail, _agent_session_repo,
    _agent_session_service, _agent_session_sql_failure, _agent_session_summaries,
    _agent_session_summary, _agent_session_title_for_message, _agent_session_updated_age_seconds,
    _agent_sessions_db_path, _agent_snapshot_from_session, _agent_stream_block_key,
    _agent_stream_tool_name, _agent_text_from_content_blocks, _apply_agent_message_retention,
    _asset_source_metadata_for_ui, _decode_agent_attachment_data_url, _emit_agent_live_activity,
    _ensure_agent_session, _file_suffix_from_mime_or_name, _hydrate_agent_attachment_row,
    _hydrate_agent_snapshot_for_ui, _hydrate_asset_row_for_ui, _hydrate_assets_for_ui,
    _hydrate_media_asset_for_ui, _image_suffix_from_mime_or_name, _is_inline_media_string,
    _load_agent_session_snapshot, _load_agent_sessions, _local_agent_attachment_source_from_media,
    _looks_like_large_base64, _media_ref_for_storage, _merge_agent_history_summary,
    _mime_from_file_suffix, _mime_from_image_suffix, _normalize_agent_action_footer,
    _normalize_agent_content_blocks, _normalize_agent_history_summary, _normalize_agent_live_activity,
    _normalize_agent_message_rows, _normalize_agent_pending_operation,
    _normalize_agent_pending_question, _normalize_agent_session_row, _normalize_agent_session_step_rows,
    _normalize_agent_stream_block, _persistent_media_data_removed,
    _prepare_agent_sessions_for_project_delete, _project_agent_attachments_dir, _project_agent_logs_dir,
    _project_config_path, _project_dir, _project_file_from_ref, _project_meta_path,
    _recover_stale_running_agent_sessions, _save_agent_attachment_source_file,
    _save_agent_live_snapshot, _save_agent_sessions, _storage_key_token, _thumbnail_ref_for_storage,
    _transient_image_keys_removed, _try_emit_agent_live_activity, append_agent_execution_error,
    clear_agent_error_logs, create_agent_conversation, delete_agent_session, ensure_episode_agent_conversation,
    get_agent_conversation_context, get_agent_session, get_agent_snapshot, list_agent_conversations,
    list_agent_error_logs, list_agent_sessions, save_agent_attachment, set_agent_conversation_context,
)

from .agent_text_planning import (
    _agent_assets_from_model, _agent_episode_script_from_chunk,
    _agent_text_unit_count, _append_generation_instruction, _build_agent_assets, _chunk_sentences,
    _chunk_text_by_units, _join_agent_sentences, _model_episode_chunks, _normalize_agent_asset_rows,
    _split_sentences,
)


from .agent_turn_execution import (
    _agent_turn_background_worker, _run_agent_inline_turn, _start_agent_background_turn,
)

from .agent_turn_routing import (
    _agent_result_used_sdk_stream,
)

from .archive_transfers import (
    HOME_ARCHIVE_FORMAT, HOME_ARCHIVE_MANIFEST, detect_jianying_draft_root, get_jianying_export_info,
    recover_home_archive_imports, start_home_archive_export, start_home_archive_import,
    start_jianying_draft_export, start_video_files_export,
)

from .asset_range_planning import (
    commit_asset_range,
)

from .asset_reference_scope import (
    _ASSET_REF_LABELS, _asset_ref_tokens_by_collection, _asset_refs_from_plan_item,
    _auto_bind_shot_plan_asset_refs, _collect_workflow_asset_refs,
    _filter_asset_refs_to_active_project_assets, _normalize_shot_plan_asset_refs, _project_asset_lookup,
    _project_asset_lookup_with_scope, _validate_asset_refs_for_episode_scope, _validate_plan_asset_refs,
    _validate_workflow_asset_refs, _workflow_asset_ref_panel_rows, bind_storyboard_asset_refs_from_text,
    storyboard_asset_refs_from_current_sources, storyboard_unmatched_asset_mentions,
)

from .asset_text_contract import (
    AGENT_TEXT_RESULT_SOURCES, _agent_text_asset_match_index, _agent_text_asset_summary,
    _agent_text_row_text, _assert_design_asset_complete, _design_asset_completion_issue,
    _normalize_agent_text_asset_row, _normalize_character_voice_style,
)

from .asset_text_ingestion import (
    _save_agent_text_assets, _write_agent_assets, save_asset_batch, upsert_asset,
)

from .assets import (
    _ASSET_CHARACTER_GUARD, _ASSET_CHARACTER_LAYOUT, _ASSET_CHARACTER_PRESENTATION_GUIDE,
    _ASSET_CHARACTER_PROP_RULE, _ASSET_IMAGE_PROMPT_KEYS, _ASSET_NEGATIVE_TAIL,
    _ASSET_NEGATIVE_TAIL_CHARACTER, _ASSET_PROP_GUARD, _ASSET_PROP_LAYOUT, _ASSET_SCENE_GUARD,
    _ASSET_SCENE_LAYOUT, _AssetImageTaskCancelled, _active_asset_image_task,
    _apply_asset_design_prompt_patch, _asset_design_prompt_from_asset, _asset_generation_aspect_ratio,
    _asset_generation_description, _asset_generation_prompt, _asset_generation_resolution,
    _asset_image_cancel_message, _asset_image_task_focus_target, _asset_image_task_message,
    _asset_mapping_text, _asset_media_version, _asset_name_key, _asset_payload_has_design_prompt,
    _asset_project_style, _asset_source_order_for_project, _asset_store_path, _asset_style_prefix,
    _asset_type_label, _asset_version_snapshot, _asset_version_state_changed,
    _build_asset_character_prompt, _build_asset_prop_prompt, _build_asset_scene_prompt,
    _character_visual_prompt_is_complete, _collect_plan_asset_refs, _default_asset_design_prompt,
    _delete_project_asset_media_files, _ensure_asset_design_prompt_for_storage,
    _ensure_asset_media_versions, _find_asset_image_source_row, _find_asset_index_by_name,
    _generate_asset_image_media, _normalize_asset_item_for_storage,
    _normalize_global_asset_item_for_storage, _normalize_media_asset, _project_asset_is_referenced,
    _project_asset_media_paths, _project_storyboard_asset_refs,
    _raise_if_asset_generation_prompt_override, _raise_if_asset_image_cancelled,
    _raise_if_character_visual_prompt_incomplete, _run_asset_media_generation_task,
    _sort_asset_rows_by_source_order, create_asset, delete_all_project_assets, delete_asset,
    delete_asset_media_version, generate_asset_media, list_assets, set_active_asset_media_version,
    start_asset_media_generation, update_asset, update_asset_media_version,
)

from .canvas_store_database import (
    card_dir, card_root, ensure_episode_storage,
)

from .canvas_store_documents import (
    create_custom_canvas_v4, delete_custom_canvas_v4, delete_episode_canvas_v4,
    list_project_custom_canvases_v4, rename_custom_canvas_v4, write_canvas_document_extras_v4,
    write_canvas_production_status_v4, write_canvas_projection_cache_v4, write_canvas_task_record_v4,
    write_canvas_task_records_v4,
)

from .canvas_store_mutations import (
    delete_canvas_records_v4, replace_canvas_records_from_workflow_projection_v4,
    write_canvas_card_records_v4, write_canvas_records_v4,
)

from .canvas_store_queries import (
    episode_canvas_exists, get_canvas_records_v4, get_canvas_scope_records_v4, get_canvas_snapshot_v4,
    list_canvas_changes_v4, read_canvas_card_record_v4,
    read_canvas_cross_episode_visual_handoff_node_v4, read_canvas_node_signatures_v4,
    read_canvas_prompt_storyboard_boundary_node_v4, read_canvas_prompt_storyboard_neighbor_node_v4,
    read_canvas_task_records_v4, read_canvas_visual_handoff_result_node_v4,
    read_canvas_workflow_projection_v4, read_card_results, read_episode_card_results,
    read_workflow_card_neighborhood_v4,
)

from .canvas_store_records import (
    empty_canvas_workflow_projection_v4, normalize_canvas_changed_resource_name,
    normalize_canvas_changed_resources,
)

from .canvas_store_results import (
    commit_canvas_result_v4, delete_card_result_version, set_card_active_version,
)

from .catalogs import (
    ACCENTS, AGENT_ATTACHMENT_MAX_BYTES, AGENT_FILE_EXTENSIONS, AGENT_IMAGE_EXTENSIONS,
    AGENT_MODEL_IMAGE_INPUT_MAX_BYTES, AGENT_OPS_CONSTRAINTS_DIR, AGENT_OPS_DIR,
    AGENT_OPS_PERMISSIONS_DIR, AGENT_OPS_PROMPTS_DIR, AGENT_OPS_SKILLS_DIR,
    ASSET_TYPES, BACKEND_DIR, BUILTIN_PROVIDER_MODELS,
    CUSTOM_STYLE_REQUIRED_MESSAGE, DASHSCOPE_QWEN_IMAGE_DEFAULT_RESOLUTION,
    DASHSCOPE_QWEN_IMAGE_EDIT_DEFAULT_RESOLUTION, DASHSCOPE_QWEN_IMAGE_EDIT_RESOLUTIONS,
    DASHSCOPE_QWEN_IMAGE_RESOLUTIONS, DATA_DIR, DEFAULT_ASSETS, DEFAULT_ASSET_EXTRACTION_TARGET_UNITS,
    DEFAULT_EPISODE_TARGET_UNITS, DEFAULT_GLOBAL_CONFIG, DEFAULT_IMAGE_GENERATION_PARAMETERS,
    DEFAULT_MODEL_CAPABILITIES, DEFAULT_MODEL_CONFIG,
    DEFAULT_OVERVIEW_EXCERPT_CHARS,
    DEFAULT_PROVIDER_PRESETS, DEFAULT_SCRIPT_ADAPTATION_TEMPLATES,
    DEFAULT_STYLE_TEMPLATES,
    DEFAULT_TEXT_REPLACEMENT_RULES, FAVORITE_STYLE_THUMBNAILS_DIR, GENERAL_CHARACTER_STYLE_PROMPT,
    GENERAL_CREATURE_STYLE_PROMPT, GENERAL_GLOBAL_STYLE_PROMPT, GENERAL_STYLE_TEMPLATE_ID,
    GENERAL_VISUAL_TYPE_PROMPTS, GENERAL_VISUAL_TYPE_STYLE_PROMPTS, GENERAL_VISUAL_TYPE_TAGS,
    GENERAL_VISUAL_TYPE_TAG_ALIASES, GLOBAL_ASSETS_PATH, GLOBAL_ASSET_MEDIA_DIR, GLOBAL_CONFIG_PATH,
    GLOBAL_DIR, GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH, GLOBAL_STYLE_REFERENCES_DIR, GLOBAL_STYLE_TEMPLATES_PATH, GLOBAL_TASKS_PATH,
    GLOBAL_TEXT_REPLACEMENT_RULES_PATH, GLOBAL_USAGE_PATH, IMAGE_EXTENSIONS, IMAGE_OUTPUT_FORMATS,
    IMAGE_OUTPUT_FORMAT_VALUES, IMAGE_RESOLUTION_ALIASES, LEGACY_GENERIC_PROVIDER_MODEL_IDS,
    LEGACY_IMAGE_RESOLUTION_TO_TIER, MAX_OVERVIEW_EXCERPT_CHARS, MEDIA_TOOL_DEFAULT_ROOTS,
    MEDIA_TOOL_FILE_EXTENSIONS, MEDIA_TOOL_MAX_ARGS, MEDIA_TOOL_STDIO_LIMIT, MIN_OVERVIEW_EXCERPT_CHARS,
    MODEL_CONFIG_REQUIRED_MESSAGE, OPENAI_GPT_IMAGE_2_DEFAULT_RESOLUTION,
    OPENAI_GPT_IMAGE_2_RESOLUTIONS, PROJECTS_DIR,
    PROJECT_NAME_EXISTS_MESSAGE, PROJECT_OVERVIEW_STRUCTURED_SCHEMA, PROVIDER_ADAPTER_SERVICE_IDS,
    REFERENCE_IMAGE_INPUT_DEFAULT_MAX_BYTES, REFERENCE_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE,
    RETIRED_PROVIDER_PRESET_IDS, SERVICE_PROVIDER_ADAPTER_IDS, SOURCE_LANGUAGE_OPTIONS,
    STANDARD_COMPATIBLE_IMAGE_RESOLUTIONS, STANDARD_COMPATIBLE_VIDEO_RESOLUTIONS,
    STYLE_ACTIVE_PHASE_VISUAL_ID_KEYS, STYLE_ANALYSIS_PROMPT, STYLE_CATEGORY_META,
    STYLE_PHASE_VISUAL_KEYS, STYLE_THUMBNAILS_DIR, VIDEO_EXTENSIONS, _DASHSCOPE_EDIT_MAX_LONG_EDGE,
    _DASHSCOPE_EDIT_MAX_RATIO, _DASHSCOPE_FOURK_PIXEL_BUDGET, _DASHSCOPE_MAX_RATIO,
    _DASHSCOPE_STANDARD_PIXEL_BUDGET, _GPT_IMAGE_MAX_LONG_EDGE, _GPT_IMAGE_MAX_RATIO,
    _GPT_IMAGE_MAX_TOTAL_PIXELS, _REFERENCE_IMAGE_INPUT_EDGE_BY_RESOLUTION, _VIDEO_SIZE_PRESETS,
    _active_style_phase_visual, _append_style_phase_visual_prompt, _catalog_model,
    _compose_image_visual_prompt, _compose_style_visual_prompt,
    _default_model_capabilities_from_catalog,
    _default_provider_rows, _ensure_prompt_sentence_end, _general_visual_type_style_prompt,
    _join_prompt_blocks, _normalize_duration_options, _normalize_provider_model_metadata,
    _normalize_resolution_label, _normalize_resolution_options, _normalize_style_phase_visual_context,
    _normalize_style_phase_visuals, _normalize_style_theme_visual_context, _positive_int_value,
    _prepend_style_theme_visual_prompt, _prompt_labeled_block, _provider_preset,
    _reference_image_input_default_max_long_edge, _strip_style_theme_visual_overlap_text, _style_active_phase_visual_id_from_mapping,
    _style_phase_visual_prompt_block, _style_phase_visual_prompt_from_config,
    _style_phase_visuals_from_mapping, _style_template, _style_theme_visual_prompt_block,
    _style_theme_visual_prompt_from_config, _style_visual_prompt_block,
)

from .director_rules import (
    GLOBAL_DIRECTOR_RULE_OVERRIDES_PATH, get_director_rules, list_director_rules_for_agent,
    normalize_director_rule_identifier, read_director_rule_document, read_director_rule_for_agent,
    reset_director_rule, save_director_rule, search_director_rules_for_agent,
)

from .episode_boundary_planning import _ensure_episode_meta_entry

from .episode_plan_documents import (
    _agent_text_episode_id, _planning_boundary_plan_from_source_coverage, _planning_count,
    _planning_episode_boundary_export, _planning_episode_range_summary, _planning_text,
    _save_agent_text_episodes, _save_episode_production_plan_from_panels, _write_project_document,
    get_project_planning_summary, save_episode_work_chain_plan,
    save_story_world_map,
)

from .exports import (
    _append_node_plan_entry, _collect_asset_definition_exports, _export_episode_rows,
    _first_export_value, _generation_models_from_config, _has_export_value, _jianying_cut_guide,
    _mapping_export_value, _node_export_context, _project_planning_export_bundle,
    _route_comparison_groups, _route_quality_issue, _route_quality_reports, copy_project_tree,
    export_project_assets,
)

from .favorite_styles import (
    _favorite_style_name_key, _find_favorite_style_index_by_name, create_favorite_style_template,
    delete_favorite_style_template, update_favorite_style_template, upload_style_image,
)

from .generation_config import (
    _default_generation_config, _generation_media_type_from_node, _media_generation_config,
    _normalized_model_capabilities, _video_task_card_target_model_context, list_model_capabilities,
    resolve_generation_config,
)

from .generation_input_context import (
    GENERATION_USER_INSTRUCTION_KEYS, _asset_refs_resolved_by_input_links, _first_mapping_text,
    _generation_user_instruction, _truthy_payload_flag, _workflow_node_by_id, _workflow_route_by_id,
)

from .generation_preflight import (
    preflight_workflow_node,
)

from .generation_reference_validation import (
    WORKFLOW_NODE_SLOT_SCHEMA,
)

from .generation_requests import (
    _ensure_generation_workflow_node, _request_generation_version, _submit_real_provider_requested,
    request_route_video_generation,
)

from .media_files import (
    _copy_local_global_asset_image_media_file, _copy_local_project_config_image_file,
    _copy_local_project_image_media_file, _copy_local_project_video_media_file, _data_url,
    _decode_data_url, _decode_image_response_value, _delete_global_asset_media_file,
    _download_image_url, _extract_first_image_bytes, _extract_first_media_url, _extract_video_job_id,
    _file_extension, _global_asset_media_path, _global_file_from_ref, _has_image_file_input,
    _image_media_from_file_info, _local_image_source_from_media, _normalize_global_media_asset,
    _normalized_image_payload, _project_media_relative_path, _project_media_storage_dir,
    _safe_file_stem, _save_favorite_style_thumbnail, _save_global_asset_image_media_file,
    _save_project_config_image_file, _save_project_image_media_file, _save_project_media_file,
    _source_media_data_url, _video_media_from_file_info,
    cleanup_reference_audio, crop_reference_audio, prepare_reference_audio,
)

from .model_generation_contract import (
    _generation_text_value,
)

from .model_provider_config import (
    _agent_model_runtime_options, _api_model_name, _configured_media_model,
    _configured_provider_for_model, _configured_text_model, _openai_compatible_generation_base_url,
    _project_model_config, _provider_base_url,
)

from .model_style_analysis import (
    _call_anthropic_style_analysis, _call_gemini_style_analysis, _call_openai_compatible_style_analysis,
    _call_style_analysis_model, _normalize_style_analysis_output,
)

from .model_text_client import (
    _attached_model_input_images, _call_anthropic_text_model, _call_gemini_text_model,
    _call_openai_compatible_text_model, _call_text_model, _extract_anthropic_response_text,
    _extract_gemini_response_text, _extract_json_payload, _extract_response_text, _model_json_or_none,
    _model_text_or_none, _post_json,
)

from .planning_contract import (
    _asset_ref_tokens, _is_user_locked_item, _item_identity, _panel_generation_strategy,
    _panel_reference_media_ids, _panel_row_text, _payload_document, _preserve_locked_items,
    _preserve_locked_plan_document, _safe_workflow_id, _segment_asset_refs, _strategy_reference_mode,
)

from .planning_workflow_assets import (
    _asset_ref_canvas_materials,
)

from .planning_workflow_builder import (
    _work_chain_plan_to_workflow,
)

from .planning_workflow_inputs import (
    _panel_to_prompts, _panels_to_shot_plan, _shot_plan_generation_config,
)

from .planning_workflow_layout import (
    _layout_workflow_by_work_chain,
)

from .production_status import (
    get_episode_production_status, get_episode_review_results, save_episode_review_results,
    update_episode_production_status, waive_review_issue,
)

from .project_management import (
    _apply_model_config_projection, _apply_global_model_config, _build_project_config,
    _default_workflow, _episode_count_from_payload,
    _normalize_visual_context, apply_phase_visual_context_to_config,
    apply_theme_visual_context_to_config, create_project, delete_project, get_effective_config,
    get_project_settings, import_project, remove_phase_visual_context_from_config,
    save_project_settings,
)

from .project_overview import (
    analyze_project_overview, update_project_overview,
    get_project_narrator_voice_profile, save_project_narrator_reference_audio,
)

from .project_resource_revisions import (
    _append_resource_revision, _apply_json_patch_op, _assert_project_json_resource_is_patchable,
    _assert_resource_write_guard, _container_for_pointer, _json_hash, _json_pointer_tokens,
    _project_json_resource_path, _resource_revision_value, _resource_revisions_path,
    create_resource_revision, patch_project_resource,
)

from .projects import _camel_to_snake
from .projects import _coerce_structured_value
from .store_core import _display_time
from .projects import _duration_to_seconds
from .projects import _favorite_style_thumbnail_fields
from .projects import _favorite_style_thumbnail_path
from .projects import _favorite_style_thumbnail_ref
from .projects import _find_template
from .projects import _first_text
from .projects import _global_relative_path
from .projects import _image_ref_from_value
from .projects import _is_path_within
from .projects import _local_project_image_ref
from .projects import _normalize_project_id
from .projects import _normalize_project_title
from .projects import _normalize_structured_payload
from .projects import _project_asset_counts
from .projects import _project_content_image_refs
from .projects import _project_relative_path
from .projects import _project_row
from .projects import _project_style_reference_ref
from .projects import _project_thumbnail_ref
from .projects import _project_title_exists
from .projects import _provider_native_structured_endpoint
from .projects import _provider_native_structured_status
from .projects import _provider_supports_native_structured_output
from .projects import _provider_with_native_structured_model_result
from .projects import _public_provider
from .projects import _save_global_config
from .projects import _slug_from_title
from .projects import _snake_to_camel
from .projects import _status_label
from .projects import _structured_field_keys
from .projects import _structured_fields
from .projects import _structured_json_schema
from .projects import _structured_model_api_name
from .projects import _structured_prompt
from .projects import _structured_raw_value
from .projects import _structured_repair_prompt
from .projects import _structured_response_format
from .projects import _structured_schema_contract
from .projects import _structured_system_prompt
from .projects import _structured_template_object
from .projects import _structured_template_value
from .projects import _structured_value_missing
from .projects import _style_template_thumbnail_ref
from .projects import _style_thumbnail_ref
from .projects import _text_list
from .projects import _timestamp_rank
from .projects import _touch_project_meta
from .projects import get_creation_options
from .projects import get_dashboard
from .projects import get_global_settings
from .projects import get_project_asset_counts
from .projects import list_projects
from .projects import set_current_project

from .provider_connections import (
    _ANTHROPIC_AUTH_TOKEN_GATEWAY_PATHS,
    _ANTHROPIC_MESSAGES_GATEWAY_PATHS,
    _CLAUDE_AGENT_SDK_PROBE_NAME, _NATIVE_JSON_SCHEMA_PROBE_NAME, _NATIVE_JSON_SCHEMA_PROBE_SCHEMA,
    _anthropic_auth_headers, _anthropic_messages_auth_headers,
    _anthropic_messages_url, _anthropic_models_url, _anthropic_probe_auth_headers,
    _anthropic_sdk_base_url, _anthropic_sdk_env,
    _build_provider_from_add_payload, _candidate_anthropic_agent_base_urls,
    _claude_agent_sdk_probe_from_result, _deepseek_discovery_root, _extract_provider_model_ids,
    _extract_provider_model_rows, _google_discovery_root_url, _http_url_base,
    _looks_like_anthropic_auth_token_gateway, _native_json_schema_probe_from_result, _normalized_url,
    _notify_response_received, _openai_compatible_discovery_base_url, _probe_claude_agent_sdk_runtime,
    _probe_summary_for_result,
    _provider_claude_agent_auth_mode, _provider_claude_agent_base_url, _provider_claude_agent_model,
    _provider_connection_test_fingerprint, _provider_declares_agent_capability,
    _provider_declares_text_capability, _provider_default_base_url, _provider_default_text_model,
    _provider_models_from_payload, _provider_probe_url_and_headers, _provider_supports_claude_agent_sdk,
    _rebase_connection_test_models, _request_json, _response_json_for_log,
    _run_ark_seedance_connection_test, _run_gemini_native_json_schema_probe,
    _run_native_json_schema_probe, _run_openai_native_json_schema_probe, _run_provider_connection_test,
    _run_vidu_connection_test, _validate_native_json_schema_probe_text,
    _validated_payload_connection_test_result, _with_provider_connection_test_context,
    _with_provider_probe_summary, add_provider, delete_provider, list_providers,
    test_provider_connection, update_provider,
)

from .provider_models import (
    _ALIGNED_MODEL_METADATA_KEYS, _REMOTE_MODEL_METADATA_KEYS,
    _adapter_endpoint_format, _align_provider_model_metadata, _aligned_model_catalog_key,
    _available_model_capabilities, _creation_model_config_status, _dashscope_exceeds_standard_budget,
    _dashscope_image_size, _empty_model_capabilities, _empty_model_config, _find_model,
    _generic_image_size, _image_output_size, _image_output_source_mime,
    _image_resolution_options_for_aspect, _is_connected_provider, _is_legacy_generic_model_id,
    _is_user_added_provider_row, _last_test_remote_model_entries, _last_test_remote_model_ids,
    _model_capabilities_with_provider_models, _model_duration_options, _model_generation_endpoint,
    _model_image_output_formats, _model_options_from_capabilities, _model_reference_image_input_limits,
    _model_supports_vision_input, _normalize_aspect_ratio_key, _normalize_image_output_format,
    _normalize_model_config, _normalize_overview_excerpt_chars, _normalize_provider_adapter_id,
    _normalize_provider_capabilities, _normalize_provider_id, _normalize_provider_rows,
    _normalize_remote_model_entries, _normalize_resolution, _provider_adapter_id,
    _provider_available_models_for_test,
    _provider_declared_and_discovered_models, _provider_model_matches_capabilities,
    _provider_models_as_capabilities, _provider_preset_id, _provider_protocol_service_id,
    _provider_service_id, _provider_specific_model_id, _provider_supports_direct_media_generation,
    _provider_text_model_supports_vision, _remote_model_entry_id, _remote_model_row,
    _resolution_matches, _resolution_text_key, _resolve_image_output_format, _standard_video_size,
    _storage_global_config, _storage_provider_row, _sync_defaults_with_model_config,
    _unique_provider_instance_id, _unique_provider_title, _video_output_size,
    _with_model_generation_endpoint, _with_model_resolution_metadata,
)

from .provider_reference_media import _active_asset_media_candidate
from .provider_reference_media import _data_url_base64_payload
from .provider_reference_media import _extract_storyboard_reference_image
from .provider_reference_media import _provider_image_data_url_from_file_info
from .provider_reference_media import _provider_reference_image_by_id
from .provider_reference_media import _provider_reference_image_from_media
from .provider_reference_media import _provider_reference_image_from_storyboard_version
from .provider_reference_media import _provider_reference_images_from_ids
from .provider_reference_media import _provider_reference_images_from_inline_files
from .provider_reference_media import _provider_reference_metadata
from .provider_reference_media import _reference_identity_values
from .media_files import _source_image_data_url
from .media_files import _storage_png_data_url

from .reference_utils import (
    asset_reference_ids_from_generation_sources as _asset_reference_ids_from_generation_sources,
    asset_reference_ids_from_refs as _asset_reference_ids_from_refs, asset_refs_has_value as
    _asset_refs_has_value, dedupe_reference_tokens as _dedupe_reference_tokens, merge_reference_ids as
    _merge_reference_ids,
)

from .runtime_state import (
    AGENT_SESSION_HISTORY_SUMMARY_MESSAGE_LIMIT, AGENT_SESSION_MESSAGE_RETAIN_LIMIT,
    AGENT_STALE_RUNNING_GRACE_SECONDS, AgentTurnCancelled, _AGENT_CANCEL_FLAGS, _AGENT_EVENT_EMITTER,
    _AGENT_SESSION_SERVICE, _AGENT_THREADS, _ASSET_IMAGE_TASK_CANCEL_FLAGS, _ASSET_IMAGE_TASK_THREADS,
    _LOCK, _VIDEO_GENERATION_TASK_TYPES, _VIDEO_TASK_CANCEL_FLAGS, _VIDEO_TASK_POLL_SECONDS,
    _VIDEO_TASK_RESTORE_MESSAGE, _VIDEO_TASK_THREADS, _agent_cancel_requested,
    _raise_if_agent_cancelled,
)

from .settings_loaders import (
    load_global_config, load_script_adaptation_templates, load_style_templates, load_text_replacement_rules,
)

from .shot_prompt_updates import (
    patch_shot_prompt,
)

from .source_asset_batches import (
    get_asset_split_batch_source_text, list_asset_split_batches,
)

from .source_boundary_contract import (
    _asset_range_commit_payload, _commit_next_step, _episode_boundary_commit_payload,
    _natural_boundary_candidates, _next_episode_id, _range_source_excerpt,
    _source_coverage_commit_guard, _unwrap_agent_commit_payload,
)

from .source_coverage import (
    _append_created_asset_ids_to_range, _asset_ids_from_payload, _asset_ranges_for_source_ref,
    _confirmed_asset_range, _coverage_target_units, _default_source_coverage, _load_source_coverage,
    _normalize_coverage_cursor, _normalize_source_coverage, _refresh_created_asset_ids_for_range,
    _reset_source_planning_state, _source_coverage_path, _source_ref_bounds,
    _source_refs_from_asset_row, _stamp_asset_range_id, _sync_source_coverage_targets,
    _validate_asset_batch_refs_in_range, _write_source_coverage, get_source_coverage,
)

from .source_index import (
    _CHAPTER_HEADING_RE, _chapter_id_for_offset, _chapter_rows_for_source, _source_index_path,
    _source_unit_rows_for_source, build_source_index, list_source_index, read_source_window,
)

from .source_reference_scope import (
    _episode_range_for_id, _shot_source_refs, _source_ref_has_valid_unit_ref,
    _source_ref_in_episode_range, _source_ref_unit_ids, _source_units_for_ref,
    _stamp_source_units_on_ref, _stamp_source_units_on_shot_plan, _stamp_source_units_on_source_refs,
    _stamp_source_units_on_workflow, _validate_shot_plan_source_refs,
)

from .source_text_store import (
    SOURCE_GROUP_NOVEL, SOURCE_GROUP_SUPPLEMENTAL, _compact_text, _episode_source_ref_path,
    _episode_source_rows, _episode_source_status, _episode_source_text_path, _is_novel_source,
    _project_source_text, _read_episode_source_text, _read_source_content, _safe_source_content_path,
    _select_project_sources, _sha256_text, _source_collection_text, _source_collection_title,
    _source_content_path, _source_group, _source_refs_for_meta, append_novel_source_files,
    create_source, delete_source_segment, get_episode_source_text, get_source_text, list_sources,
    open_episode_source_file_location, open_source_file_location, replace_sources,
    restore_source_total_snapshot, save_episode_source_text, save_source_text,
)

from .splitting_templates import (
    _string_list, delete_script_adaptation_template, get_model_config,
    get_script_adaptation_templates, get_text_replacement_rules,
    save_model_config, save_script_adaptation_template, save_text_replacement_rules,
)

from .store_core import (
    AGENT_MAX_TOKEN_OPTIONS, AGENT_TEMPERATURE_OPTIONS, AI_VIDEO_AGENT_TASK_MAX_TOKENS,
    AI_VIDEO_AGENT_TASK_TEMPERATURE, ASSET_LIFECYCLE_ACTIVE, ASSET_LIFECYCLE_ALL,
    ASSET_LIFECYCLE_OFFLINE, _JSON_WRITE_LOCK, _assert_explicit_delete_all_confirmed, _asset_is_offline,
    _asset_lifecycle_matches, _asset_lifecycle_patch_value, _asset_lifecycle_status,
    _asset_row_for_response, _deep_merge, _emit_agent_event, _filter_asset_store_by_lifecycle,
    _mask_key, _merge_model_capabilities, _merge_provider_presets,
    _normalize_asset_lifecycle_filter, _normalize_asset_lifecycle_status, _normalize_asset_type_key,
    _normalize_text_replacement_rules, _now, _read_json, _set_asset_lifecycle_status,
    _truthy_confirmation, _write_json, compact_agent_event_payload, ensure_store,
    set_agent_event_emitter,
)

from .storyboard_image_generation import (
    _call_openai_compatible_image_generation, _generate_storyboard_image_media,
)

from .storyboard_prompt_content import (
    _duration_seconds_value, _panel_asset_ref_text, _panel_duration_seconds, _panel_prompt,
    _panel_title, _panel_value, _storyboard_panels_duration_seconds,
    _storyboard_payload_duration_seconds, _workflow_video_task_card_duration_seconds, _xml_text,
)

from .storyboard_task_execution import (
    run_storyboard_generation_task,
)

from .storyboard_templates import (
    GLOBAL_STORYBOARD_TEMPLATES_PATH, STORYBOARD_TEMPLATE_BLOCKING, STORYBOARD_TEMPLATE_DEFAULT,
    STORYBOARD_TEMPLATE_FILMSTRIP, STORYBOARD_TEMPLATE_IMAGE_GRID, STORYBOARD_TEMPLATE_NARRATIVE,
    STORYBOARD_TEMPLATE_NUMBERED_GRID, delete_storyboard_template, get_storyboard_templates,
    load_storyboard_templates, save_storyboard_template, storyboard_template_catalog,
    storyboard_template_from_mapping, storyboard_template_id, storyboard_template_label,
    storyboard_template_layout_spec, storyboard_template_prompt_rules,
    storyboard_template_selection_catalog, storyboard_template_single_panel_prompt_rules,
)

from .storyboard_video_generation import (
    _build_storyboard_video_request, _generate_storyboard_video_media,
    _storyboard_video_debug_block_request_log_input,
)

from .style_analysis import (
    _save_project_cover, _save_style_reference, analyze_style_image,
)

from .task_commands import (
    cancel_agent_session_bound_tasks, cancel_task, clear_task_notifications,
    delete_episode_derived_tasks,
)

from .task_control import (
    _emit_task_update, _get_task, _update_asset_image_task, _update_task_fields, _update_task_if_active,
    _update_video_task, create_task, is_task_cancelled,
)

from .task_events import (
    _emit_generation_task_result,
)

from .task_lifecycle import (
    register_background_task_thread, unregister_background_task_thread,
)

from .task_queries import (
    diagnose_task, get_usage_summary, list_tasks,
)

from .task_storage import (
    _load_task_storage_bucket, _load_tasks, _load_tasks_for_project, _save_task_storage_bucket,
    _save_tasks, _task_storage_key_for_task_id,
)

from .task_workflow_context import (
    _assert_generation_closure_ready,
)

from .video_clips import (
    delete_video_clip_results, ensure_video_thumbnail, extract_video_frame, extract_video_frame_preview,
    get_video_clip_info, list_video_clip_results, save_clipboard_image_media, trim_video_clip,
)

from .video_generation_prompt import (
    _video_prompt_from_generation_payload, _video_source_prompt_from_generation_payload,
)

from .video_provider_references import (
    _video_provider_reference_plan,
)

from .video_task_card_prompts import (
    VIDEO_TASK_CARD_PROMPT_TEMPLATE_VERSION, _director_plan_shot_rows_from_structured,
    _video_task_card_prompt_from_structured_shots,
)

from .video_task_card_references import (
    _ASSET_REF_COLLECTIONS, video_task_card_current_reference_snapshot,
)

from .video_task_cards import (
    sync_work_chain_video_duration,
)

from .video_task_execution import (
    _ensure_storyboard_video_worker, _finish_storyboard_video_task, _resume_storyboard_video_tasks,
    _run_storyboard_video_task,
)

from .video_task_provider import (
    _cancel_message_with_provider_result, _cancel_storyboard_video_provider_job,
    _cancel_storyboard_video_version, _fail_storyboard_video_version, _poll_storyboard_video_job,
    _provider_for_video_job, _response_to_storyboard_video_metadata, _storyboard_video_job_from_request,
)

from .video_task_requests import (
    _update_storyboard_video_processing_version,
)

from .video_task_submission import (
    start_storyboard_video_generation,
)

from .worker_asset_validation import (
    validate_analyze_assets_worker_output,
)

from .worker_contract import (
    worker_work_definition,
)

from .worker_plot_validation import (
    validate_plot_splitting_worker_output,
)

from .worker_task_context import (
    build_worker_task_context,
)

from .workflow_asset_resolution import (
    resolve_canvas_asset_images, resolve_workflow_node_inputs,
)

from .workflow_canvas_asset_copy import (
    paste_workflow_asset_node,
)

from .workflow_canvas_creation import (
    add_workflow_asset_nodes, create_workflow_node, create_workflow_task_card,
)

from .workflow_canvas_deletion import (
    delete_workflow_item, delete_workflow_node,
)

from .workflow_canvas_updates import (
    rename_workflow_asset_node, update_workflow_node_layout, update_workflow_route,
    upsert_workflow_node,
)

from .workflow_contract import (
    _workflow_node, workflow_node_is_default_work_chain_video_task, workflow_video_task_scope,
)

from .workflow_edit_history import (
    delete_node_edit_history, list_node_edit_history, record_node_edit_history,
    record_workflow_node_edit_history,
)
from .workflow_director_rework_records import (
    delete_director_rework_record, list_director_rework_records,
)

from .workflow_media_generation import (
    build_storyboard_generation_metadata,
)
from .workflow_storyboard_prompts import (
    _generated_version_preview,
    _storyboard_prompt_payload,
    _storyboard_svg_preview,
)

from .workflow_generation_config import (
    _clean_runtime_generation_config, _runtime_generation_config_for_execution,
    _runtime_generation_config_from_node,
)

from .workflow_generation_context import (
    _workflow_panels, find_workflow_nodes, validate_workflow_node_inputs_ready,
    workflow_generation_related_node_ids,
)

from .workflow_inline_editing import (
    restore_node_edit_history, save_workflow_node_inline_edit,
)

from .workflow_input_links import (
    link_workflow_input, list_workflow_inputs, unlink_workflow_input,
)

from .workflow_input_resolution import (
    _workflow_node_data, resolve_generation_task_node_id, workflow_current_media_reference,
    workflow_current_media_version_has_media, workflow_storyboard_image_director_node_id,
    workflow_storyboard_reference_node_ids, workflow_video_task_work_chain_storyboard_node_ids,
)

from .workflow_media_batch import (
    import_workflow_media, run_workflow_batch, upload_storyboard_image,
)

from .workflow_planning_lifecycle import (
    delete_project_planning_outputs, delete_source,
)

from .workflow_projection import (
    _append_workflow_version, _workflow_version_label, _workflow_versions_path,
    build_episode_workflow_from_work_chain_plan, empty_episode_workflow, get_canvas_workflow_projection,
    list_workflow_media, relayout_episode_workflow, replace_canvas_workflow_projection,
)

from .workflow_source_split import (
    adjust_source_split_workflow, apply_independent_source_workflow,
    create_independent_source_card, create_manual_workflow_chain,
)

from .storyboard_allocation import apply_storyboard_allocation

from .workflow_storyboard_edits import (
    _update_storyboard_version_metadata, edit_storyboard_image, set_storyboard_result_active_version,
)

from .workflow_storyboard_versions import (
    add_storyboard_version, delete_storyboard_version, list_storyboard_versions,
    select_workflow_variant,
)

from .workflow_task_queries import (
    list_workflow_tasks,
)

from .workflow_variant_quality import (
    auto_review_variant_quality, save_variant_quality_result,
)

from .workflow_visual_handoff import (
    ensure_visual_handoff_result_node, sync_visual_handoff_cross_episode_link,
)

from utils.video_model_capabilities import (
    ARK_SEEDANCE_25_VIDEO_CAPABILITY_METADATA, ARK_SEEDANCE_2_VIDEO_CAPABILITY_METADATA,
    DASHSCOPE_WAN27_VIDEO_CAPABILITY_METADATA, VIDU_Q3_VIDEO_CAPABILITY_METADATA,
)

_EXPORTS: dict[str, Any] = {
    'OPENAI_GPT_IMAGE_2_RESOLUTIONS': OPENAI_GPT_IMAGE_2_RESOLUTIONS,
    'OPENAI_GPT_IMAGE_2_DEFAULT_RESOLUTION': OPENAI_GPT_IMAGE_2_DEFAULT_RESOLUTION,
    'DASHSCOPE_QWEN_IMAGE_RESOLUTIONS': DASHSCOPE_QWEN_IMAGE_RESOLUTIONS,
    'DASHSCOPE_QWEN_IMAGE_DEFAULT_RESOLUTION': DASHSCOPE_QWEN_IMAGE_DEFAULT_RESOLUTION,
    'DASHSCOPE_QWEN_IMAGE_EDIT_RESOLUTIONS': DASHSCOPE_QWEN_IMAGE_EDIT_RESOLUTIONS,
    'DASHSCOPE_QWEN_IMAGE_EDIT_DEFAULT_RESOLUTION': DASHSCOPE_QWEN_IMAGE_EDIT_DEFAULT_RESOLUTION,
    'STANDARD_COMPATIBLE_IMAGE_RESOLUTIONS': STANDARD_COMPATIBLE_IMAGE_RESOLUTIONS,
    'STANDARD_COMPATIBLE_VIDEO_RESOLUTIONS': STANDARD_COMPATIBLE_VIDEO_RESOLUTIONS,
    'ARK_SEEDANCE_2_VIDEO_CAPABILITY_METADATA': ARK_SEEDANCE_2_VIDEO_CAPABILITY_METADATA,
    'ARK_SEEDANCE_25_VIDEO_CAPABILITY_METADATA': ARK_SEEDANCE_25_VIDEO_CAPABILITY_METADATA,
    'DASHSCOPE_WAN27_VIDEO_CAPABILITY_METADATA': DASHSCOPE_WAN27_VIDEO_CAPABILITY_METADATA,
    'VIDU_Q3_VIDEO_CAPABILITY_METADATA': VIDU_Q3_VIDEO_CAPABILITY_METADATA,
    'DEFAULT_IMAGE_GENERATION_PARAMETERS': DEFAULT_IMAGE_GENERATION_PARAMETERS,
    'DEFAULT_OVERVIEW_EXCERPT_CHARS': DEFAULT_OVERVIEW_EXCERPT_CHARS,
    'MIN_OVERVIEW_EXCERPT_CHARS': MIN_OVERVIEW_EXCERPT_CHARS,
    'MAX_OVERVIEW_EXCERPT_CHARS': MAX_OVERVIEW_EXCERPT_CHARS,
    'DEFAULT_EPISODE_TARGET_UNITS': DEFAULT_EPISODE_TARGET_UNITS,
    'DEFAULT_ASSET_EXTRACTION_TARGET_UNITS': DEFAULT_ASSET_EXTRACTION_TARGET_UNITS,
    'IMAGE_RESOLUTION_ALIASES': IMAGE_RESOLUTION_ALIASES,
    'LEGACY_IMAGE_RESOLUTION_TO_TIER': LEGACY_IMAGE_RESOLUTION_TO_TIER,
    '_GPT_IMAGE_MAX_LONG_EDGE': _GPT_IMAGE_MAX_LONG_EDGE,
    '_GPT_IMAGE_MAX_TOTAL_PIXELS': _GPT_IMAGE_MAX_TOTAL_PIXELS,
    '_GPT_IMAGE_MAX_RATIO': _GPT_IMAGE_MAX_RATIO,
    '_DASHSCOPE_STANDARD_PIXEL_BUDGET': _DASHSCOPE_STANDARD_PIXEL_BUDGET,
    '_DASHSCOPE_FOURK_PIXEL_BUDGET': _DASHSCOPE_FOURK_PIXEL_BUDGET,
    '_DASHSCOPE_EDIT_MAX_LONG_EDGE': _DASHSCOPE_EDIT_MAX_LONG_EDGE,
    '_DASHSCOPE_MAX_RATIO': _DASHSCOPE_MAX_RATIO,
    '_DASHSCOPE_EDIT_MAX_RATIO': _DASHSCOPE_EDIT_MAX_RATIO,
    'REFERENCE_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE': REFERENCE_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE,
    'REFERENCE_IMAGE_INPUT_DEFAULT_MAX_BYTES': REFERENCE_IMAGE_INPUT_DEFAULT_MAX_BYTES,
    '_REFERENCE_IMAGE_INPUT_EDGE_BY_RESOLUTION': _REFERENCE_IMAGE_INPUT_EDGE_BY_RESOLUTION,
    '_VIDEO_SIZE_PRESETS': _VIDEO_SIZE_PRESETS,
    'BACKEND_DIR': BACKEND_DIR,
    'DATA_DIR': DATA_DIR,
    'GLOBAL_DIR': GLOBAL_DIR,
    'PROJECTS_DIR': PROJECTS_DIR,
    'AGENT_OPS_DIR': AGENT_OPS_DIR,
    'AGENT_OPS_CONSTRAINTS_DIR': AGENT_OPS_CONSTRAINTS_DIR,
    'AGENT_OPS_PERMISSIONS_DIR': AGENT_OPS_PERMISSIONS_DIR,
    'AGENT_OPS_PROMPTS_DIR': AGENT_OPS_PROMPTS_DIR,
    'AGENT_OPS_SKILLS_DIR': AGENT_OPS_SKILLS_DIR,
    'STYLE_THUMBNAILS_DIR': STYLE_THUMBNAILS_DIR,
    'GLOBAL_STYLE_REFERENCES_DIR': GLOBAL_STYLE_REFERENCES_DIR,
    'FAVORITE_STYLE_THUMBNAILS_DIR': FAVORITE_STYLE_THUMBNAILS_DIR,
    'GLOBAL_ASSET_MEDIA_DIR': GLOBAL_ASSET_MEDIA_DIR,
    'IMAGE_EXTENSIONS': IMAGE_EXTENSIONS,
    'AGENT_IMAGE_EXTENSIONS': AGENT_IMAGE_EXTENSIONS,
    'AGENT_FILE_EXTENSIONS': AGENT_FILE_EXTENSIONS,
    'AGENT_ATTACHMENT_MAX_BYTES': AGENT_ATTACHMENT_MAX_BYTES,
    'AGENT_MODEL_IMAGE_INPUT_MAX_BYTES': AGENT_MODEL_IMAGE_INPUT_MAX_BYTES,
    'VIDEO_EXTENSIONS': VIDEO_EXTENSIONS,
    'MEDIA_TOOL_FILE_EXTENSIONS': MEDIA_TOOL_FILE_EXTENSIONS,
    'MEDIA_TOOL_DEFAULT_ROOTS': MEDIA_TOOL_DEFAULT_ROOTS,
    'MEDIA_TOOL_STDIO_LIMIT': MEDIA_TOOL_STDIO_LIMIT,
    'MEDIA_TOOL_MAX_ARGS': MEDIA_TOOL_MAX_ARGS,
    'STYLE_ANALYSIS_PROMPT': STYLE_ANALYSIS_PROMPT,
    'PROJECT_OVERVIEW_STRUCTURED_SCHEMA': PROJECT_OVERVIEW_STRUCTURED_SCHEMA,
    'PROJECT_NAME_EXISTS_MESSAGE': PROJECT_NAME_EXISTS_MESSAGE,
    'CUSTOM_STYLE_REQUIRED_MESSAGE': CUSTOM_STYLE_REQUIRED_MESSAGE,
    'MODEL_CONFIG_REQUIRED_MESSAGE': MODEL_CONFIG_REQUIRED_MESSAGE,
    'SOURCE_LANGUAGE_OPTIONS': SOURCE_LANGUAGE_OPTIONS,
    'GLOBAL_CONFIG_PATH': GLOBAL_CONFIG_PATH,
    'STYLE_PHASE_VISUAL_KEYS': STYLE_PHASE_VISUAL_KEYS,
    'STYLE_ACTIVE_PHASE_VISUAL_ID_KEYS': STYLE_ACTIVE_PHASE_VISUAL_ID_KEYS,
    '_ensure_prompt_sentence_end': _ensure_prompt_sentence_end,
    '_prompt_labeled_block': _prompt_labeled_block,
    '_join_prompt_blocks': _join_prompt_blocks,
    '_normalize_style_theme_visual_context': _normalize_style_theme_visual_context,
    '_style_theme_visual_prompt_from_config': _style_theme_visual_prompt_from_config,
    '_style_theme_visual_prompt_block': _style_theme_visual_prompt_block,
    '_prepend_style_theme_visual_prompt': _prepend_style_theme_visual_prompt,
    '_strip_style_theme_visual_overlap_text': _strip_style_theme_visual_overlap_text,
    '_normalize_style_phase_visual_context': _normalize_style_phase_visual_context,
    '_normalize_style_phase_visuals': _normalize_style_phase_visuals,
    '_style_phase_visuals_from_mapping': _style_phase_visuals_from_mapping,
    '_style_active_phase_visual_id_from_mapping': _style_active_phase_visual_id_from_mapping,
    '_active_style_phase_visual': _active_style_phase_visual,
    '_style_phase_visual_prompt_from_config': _style_phase_visual_prompt_from_config,
    '_style_phase_visual_prompt_block': _style_phase_visual_prompt_block,
    '_append_style_phase_visual_prompt': _append_style_phase_visual_prompt,
    '_compose_style_visual_prompt': _compose_style_visual_prompt,
    '_style_visual_prompt_block': _style_visual_prompt_block,
    '_compose_image_visual_prompt': _compose_image_visual_prompt,
    'GLOBAL_ASSETS_PATH': GLOBAL_ASSETS_PATH,
    'GLOBAL_STYLE_TEMPLATES_PATH': GLOBAL_STYLE_TEMPLATES_PATH,
    'GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH': GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH,
    'GLOBAL_TEXT_REPLACEMENT_RULES_PATH': GLOBAL_TEXT_REPLACEMENT_RULES_PATH,
    'GLOBAL_TASKS_PATH': GLOBAL_TASKS_PATH,
    'GLOBAL_USAGE_PATH': GLOBAL_USAGE_PATH,
    'ACCENTS': ACCENTS,
    'IMAGE_OUTPUT_FORMATS': IMAGE_OUTPUT_FORMATS,
    'IMAGE_OUTPUT_FORMAT_VALUES': IMAGE_OUTPUT_FORMAT_VALUES,
    'DEFAULT_PROVIDER_PRESETS': DEFAULT_PROVIDER_PRESETS,
    'LEGACY_GENERIC_PROVIDER_MODEL_IDS': LEGACY_GENERIC_PROVIDER_MODEL_IDS,
    'RETIRED_PROVIDER_PRESET_IDS': RETIRED_PROVIDER_PRESET_IDS,
    'PROVIDER_ADAPTER_SERVICE_IDS': PROVIDER_ADAPTER_SERVICE_IDS,
    'SERVICE_PROVIDER_ADAPTER_IDS': SERVICE_PROVIDER_ADAPTER_IDS,
    '_normalize_resolution_label': _normalize_resolution_label,
    '_normalize_resolution_options': _normalize_resolution_options,
    '_normalize_duration_options': _normalize_duration_options,
    '_normalize_provider_model_metadata': _normalize_provider_model_metadata,
    '_catalog_model': _catalog_model,
    'BUILTIN_PROVIDER_MODELS': BUILTIN_PROVIDER_MODELS,
    '_provider_preset': _provider_preset,
    'DEFAULT_MODEL_CAPABILITIES': DEFAULT_MODEL_CAPABILITIES,
    '_default_model_capabilities_from_catalog': _default_model_capabilities_from_catalog,
    'DEFAULT_MODEL_CONFIG': DEFAULT_MODEL_CONFIG,
    '_positive_int_value': _positive_int_value,
    '_reference_image_input_default_max_long_edge': _reference_image_input_default_max_long_edge,
    '_default_provider_rows': _default_provider_rows,
    'DEFAULT_GLOBAL_CONFIG': DEFAULT_GLOBAL_CONFIG,
    'DEFAULT_SCRIPT_ADAPTATION_TEMPLATES': DEFAULT_SCRIPT_ADAPTATION_TEMPLATES,
    'DEFAULT_TEXT_REPLACEMENT_RULES': DEFAULT_TEXT_REPLACEMENT_RULES,
    'GENERAL_STYLE_TEMPLATE_ID': GENERAL_STYLE_TEMPLATE_ID,
    'GENERAL_VISUAL_TYPE_TAGS': GENERAL_VISUAL_TYPE_TAGS,
    'GENERAL_VISUAL_TYPE_PROMPTS': GENERAL_VISUAL_TYPE_PROMPTS,
    'GENERAL_VISUAL_TYPE_STYLE_PROMPTS': GENERAL_VISUAL_TYPE_STYLE_PROMPTS,
    'GENERAL_VISUAL_TYPE_TAG_ALIASES': GENERAL_VISUAL_TYPE_TAG_ALIASES,
    '_general_visual_type_style_prompt': _general_visual_type_style_prompt,
    'GENERAL_GLOBAL_STYLE_PROMPT': GENERAL_GLOBAL_STYLE_PROMPT,
    'GENERAL_CHARACTER_STYLE_PROMPT': GENERAL_CHARACTER_STYLE_PROMPT,
    'GENERAL_CREATURE_STYLE_PROMPT': GENERAL_CREATURE_STYLE_PROMPT,
    'STYLE_CATEGORY_META': STYLE_CATEGORY_META,
    '_style_template': _style_template,
    'DEFAULT_STYLE_TEMPLATES': DEFAULT_STYLE_TEMPLATES,
    'DEFAULT_ASSETS': DEFAULT_ASSETS,
    'ASSET_TYPES': ASSET_TYPES,
    '_LOCK': _LOCK,
    '_AGENT_EVENT_EMITTER': _AGENT_EVENT_EMITTER,
    '_AGENT_SESSION_SERVICE': _AGENT_SESSION_SERVICE,
    '_AGENT_CANCEL_FLAGS': _AGENT_CANCEL_FLAGS,
    '_AGENT_THREADS': _AGENT_THREADS,
    '_ASSET_IMAGE_TASK_THREADS': _ASSET_IMAGE_TASK_THREADS,
    '_ASSET_IMAGE_TASK_CANCEL_FLAGS': _ASSET_IMAGE_TASK_CANCEL_FLAGS,
    '_VIDEO_TASK_THREADS': _VIDEO_TASK_THREADS,
    '_VIDEO_TASK_CANCEL_FLAGS': _VIDEO_TASK_CANCEL_FLAGS,
    '_VIDEO_TASK_POLL_SECONDS': _VIDEO_TASK_POLL_SECONDS,
    '_VIDEO_TASK_RESTORE_MESSAGE': _VIDEO_TASK_RESTORE_MESSAGE,
    '_VIDEO_GENERATION_TASK_TYPES': _VIDEO_GENERATION_TASK_TYPES,
    'AGENT_STALE_RUNNING_GRACE_SECONDS': AGENT_STALE_RUNNING_GRACE_SECONDS,
    'AGENT_SESSION_MESSAGE_RETAIN_LIMIT': AGENT_SESSION_MESSAGE_RETAIN_LIMIT,
    'AGENT_SESSION_HISTORY_SUMMARY_MESSAGE_LIMIT': AGENT_SESSION_HISTORY_SUMMARY_MESSAGE_LIMIT,
    'AgentTurnCancelled': AgentTurnCancelled,
    '_agent_cancel_requested': _agent_cancel_requested,
    '_raise_if_agent_cancelled': _raise_if_agent_cancelled,
    '_normalize_asset_type_key': _normalize_asset_type_key,
    'ASSET_LIFECYCLE_ACTIVE': ASSET_LIFECYCLE_ACTIVE,
    'ASSET_LIFECYCLE_OFFLINE': ASSET_LIFECYCLE_OFFLINE,
    'ASSET_LIFECYCLE_ALL': ASSET_LIFECYCLE_ALL,
    '_normalize_asset_lifecycle_status': _normalize_asset_lifecycle_status,
    '_normalize_asset_lifecycle_filter': _normalize_asset_lifecycle_filter,
    '_asset_lifecycle_status': _asset_lifecycle_status,
    '_asset_is_offline': _asset_is_offline,
    '_asset_lifecycle_matches': _asset_lifecycle_matches,
    '_asset_lifecycle_patch_value': _asset_lifecycle_patch_value,
    '_set_asset_lifecycle_status': _set_asset_lifecycle_status,
    '_asset_row_for_response': _asset_row_for_response,
    '_filter_asset_store_by_lifecycle': _filter_asset_store_by_lifecycle,
    '_now': _now,
    '_read_json': _read_json,
    '_write_json': _write_json,
    '_JSON_WRITE_LOCK': _JSON_WRITE_LOCK,
    '_normalize_text_replacement_rules': _normalize_text_replacement_rules,
    'set_agent_event_emitter': set_agent_event_emitter,
    'compact_agent_event_payload': compact_agent_event_payload,
    '_emit_agent_event': _emit_agent_event,
    '_deep_merge': _deep_merge,
    'ensure_store': ensure_store,
    '_merge_provider_presets': _merge_provider_presets,
    '_merge_model_capabilities': _merge_model_capabilities,
    'AGENT_TEMPERATURE_OPTIONS': AGENT_TEMPERATURE_OPTIONS,
    'AGENT_MAX_TOKEN_OPTIONS': AGENT_MAX_TOKEN_OPTIONS,
    'AI_VIDEO_AGENT_TASK_TEMPERATURE': AI_VIDEO_AGENT_TASK_TEMPERATURE,
    'AI_VIDEO_AGENT_TASK_MAX_TOKENS': AI_VIDEO_AGENT_TASK_MAX_TOKENS,
    '_mask_key': _mask_key,
    '_truthy_confirmation': _truthy_confirmation,
    '_assert_explicit_delete_all_confirmed': _assert_explicit_delete_all_confirmed,
    '_normalize_provider_id': _normalize_provider_id,
    '_normalize_provider_capabilities': _normalize_provider_capabilities,
    '_provider_preset_id': _provider_preset_id,
    '_provider_service_id': _provider_service_id,
    '_normalize_provider_adapter_id': _normalize_provider_adapter_id,
    '_provider_adapter_id': _provider_adapter_id,
    '_provider_protocol_service_id': _provider_protocol_service_id,
    '_adapter_endpoint_format': _adapter_endpoint_format,
    '_unique_provider_instance_id': _unique_provider_instance_id,
    '_unique_provider_title': _unique_provider_title,
    '_storage_provider_row': _storage_provider_row,
    '_storage_global_config': _storage_global_config,
    '_is_user_added_provider_row': _is_user_added_provider_row,
    '_normalize_provider_rows': _normalize_provider_rows,
    '_provider_model_matches_capabilities': _provider_model_matches_capabilities,
    '_model_generation_endpoint': _model_generation_endpoint,
    '_with_model_generation_endpoint': _with_model_generation_endpoint,
    '_provider_supports_direct_media_generation': _provider_supports_direct_media_generation,
    '_provider_specific_model_id': _provider_specific_model_id,
    '_provider_text_model_supports_vision': _provider_text_model_supports_vision,
    '_REMOTE_MODEL_METADATA_KEYS': _REMOTE_MODEL_METADATA_KEYS,
    '_remote_model_entry_id': _remote_model_entry_id,
    '_normalize_remote_model_entries': _normalize_remote_model_entries,
    '_remote_model_row': _remote_model_row,
    '_last_test_remote_model_ids': _last_test_remote_model_ids,
    '_last_test_remote_model_entries': _last_test_remote_model_entries,
    '_is_legacy_generic_model_id': _is_legacy_generic_model_id,
    '_ALIGNED_MODEL_METADATA_KEYS': _ALIGNED_MODEL_METADATA_KEYS,
    '_aligned_model_catalog_key': _aligned_model_catalog_key,
    '_align_provider_model_metadata': _align_provider_model_metadata,
    '_provider_declared_and_discovered_models': _provider_declared_and_discovered_models,
    '_provider_available_models_for_test': _provider_available_models_for_test,
    '_model_capabilities_with_provider_models': _model_capabilities_with_provider_models,
    '_empty_model_capabilities': _empty_model_capabilities,
    '_is_connected_provider': _is_connected_provider,
    '_provider_models_as_capabilities': _provider_models_as_capabilities,
    '_available_model_capabilities': _available_model_capabilities,
    '_model_options_from_capabilities': _model_options_from_capabilities,
    '_find_model': _find_model,
    '_model_supports_vision_input': _model_supports_vision_input,
    '_resolution_text_key': _resolution_text_key,
    '_normalize_aspect_ratio_key': _normalize_aspect_ratio_key,
    '_generic_image_size': _generic_image_size,
    '_image_resolution_options_for_aspect': _image_resolution_options_for_aspect,
    '_dashscope_exceeds_standard_budget': _dashscope_exceeds_standard_budget,
    '_dashscope_image_size': _dashscope_image_size,
    '_standard_video_size': _standard_video_size,
    '_image_output_size': _image_output_size,
    '_with_model_resolution_metadata': _with_model_resolution_metadata,
    '_video_output_size': _video_output_size,
    '_normalize_resolution': _normalize_resolution,
    '_normalize_image_output_format': _normalize_image_output_format,
    '_model_image_output_formats': _model_image_output_formats,
    '_resolve_image_output_format': _resolve_image_output_format,
    '_image_output_source_mime': _image_output_source_mime,
    '_model_reference_image_input_limits': _model_reference_image_input_limits,
    '_resolution_matches': _resolution_matches,
    '_model_duration_options': _model_duration_options,
    '_empty_model_config': _empty_model_config,
    '_normalize_overview_excerpt_chars': _normalize_overview_excerpt_chars,
    '_normalize_model_config': _normalize_model_config,
    '_sync_defaults_with_model_config': _sync_defaults_with_model_config,
    '_creation_model_config_status': _creation_model_config_status,
    'load_global_config': load_global_config,
    'load_script_adaptation_templates': load_script_adaptation_templates,
    'load_text_replacement_rules': load_text_replacement_rules,
    'load_style_templates': load_style_templates,
    '_project_dir': _project_dir,
    '_project_meta_path': _project_meta_path,
    '_project_config_path': _project_config_path,
    '_agent_session_service': _agent_session_service,
    '_agent_sessions_db_path': _agent_sessions_db_path,
    '_agent_session_repo': _agent_session_repo,
    '_agent_session_sql_failure': _agent_session_sql_failure,
    '_project_agent_attachments_dir': _project_agent_attachments_dir,
    '_project_agent_logs_dir': _project_agent_logs_dir,
    '_agent_log_date_key': _agent_log_date_key,
    '_agent_log_sanitize': _agent_log_sanitize,
    'append_agent_execution_error': append_agent_execution_error,
    'list_agent_error_logs': list_agent_error_logs,
    'clear_agent_error_logs': clear_agent_error_logs,
    '_image_suffix_from_mime_or_name': _image_suffix_from_mime_or_name,
    '_mime_from_image_suffix': _mime_from_image_suffix,
    '_file_suffix_from_mime_or_name': _file_suffix_from_mime_or_name,
    '_mime_from_file_suffix': _mime_from_file_suffix,
    '_decode_agent_attachment_data_url': _decode_agent_attachment_data_url,
    '_project_file_from_ref': _project_file_from_ref,
    '_agent_attachment_ref_from_path': _agent_attachment_ref_from_path,
    '_local_agent_attachment_source_from_media': _local_agent_attachment_source_from_media,
    '_save_agent_attachment_source_file': _save_agent_attachment_source_file,
    '_hydrate_agent_attachment_row': _hydrate_agent_attachment_row,
    '_agent_message_attachment_rows': _agent_message_attachment_rows,
    'save_agent_attachment': save_agent_attachment,
    '_PERSISTENT_MEDIA_DATA_KEYS': _PERSISTENT_MEDIA_DATA_KEYS,
    '_storage_key_token': _storage_key_token,
    '_is_inline_media_string': _is_inline_media_string,
    '_looks_like_large_base64': _looks_like_large_base64,
    '_persistent_media_data_removed': _persistent_media_data_removed,
    '_transient_image_keys_removed': _transient_image_keys_removed,
    '_media_ref_for_storage': _media_ref_for_storage,
    '_thumbnail_ref_for_storage': _thumbnail_ref_for_storage,
    '_hydrate_media_asset_for_ui': _hydrate_media_asset_for_ui,
    '_asset_source_metadata_for_ui': _asset_source_metadata_for_ui,
    '_hydrate_asset_row_for_ui': _hydrate_asset_row_for_ui,
    '_hydrate_assets_for_ui': _hydrate_assets_for_ui,
    '_agent_message_row': _agent_message_row,
    '_agent_attachment_input_from_block': _agent_attachment_input_from_block,
    '_agent_image_attachment_input_from_block': _agent_image_attachment_input_from_block,
    '_agent_file_attachment_input_from_block': _agent_file_attachment_input_from_block,
    '_agent_attachment_error_content_block': _agent_attachment_error_content_block,
    '_agent_content_block_log_details': _agent_content_block_log_details,
    '_agent_image_content_block_from_ref': _agent_image_content_block_from_ref,
    '_agent_file_content_block_from_ref': _agent_file_content_block_from_ref,
    '_agent_blocks_from_attachment_fields': _agent_blocks_from_attachment_fields,
    '_AGENT_UI_ONLY_RECOMMENDATION_ACTIONS': _AGENT_UI_ONLY_RECOMMENDATION_ACTIONS,
    '_AGENT_UI_ONLY_RECOMMENDATION_PATTERNS': _AGENT_UI_ONLY_RECOMMENDATION_PATTERNS,
    '_agent_is_ui_only_recommendation': _agent_is_ui_only_recommendation,
    '_normalize_agent_action_footer': _normalize_agent_action_footer,
    '_agent_action_footer_text': _agent_action_footer_text,
    '_agent_merge_action_footer_values': _agent_merge_action_footer_values,
    '_agent_attach_action_footer_to_content_blocks': _agent_attach_action_footer_to_content_blocks,
    '_normalize_agent_content_blocks': _normalize_agent_content_blocks,
    '_agent_text_from_content_blocks': _agent_text_from_content_blocks,
    '_agent_blocks_have_body_text': _agent_blocks_have_body_text,
    '_agent_blocks_have_text': _agent_blocks_have_text,
    '_agent_message_is_control_only': _agent_message_is_control_only,
    '_normalize_agent_message_rows': _normalize_agent_message_rows,
    '_normalize_agent_history_summary': _normalize_agent_history_summary,
    '_agent_message_summary_line': _agent_message_summary_line,
    '_merge_agent_history_summary': _merge_agent_history_summary,
    '_apply_agent_message_retention': _apply_agent_message_retention,
    '_normalize_agent_session_step_rows': _normalize_agent_session_step_rows,
    '_normalize_agent_pending_question': _normalize_agent_pending_question,
    '_normalize_agent_pending_operation': _normalize_agent_pending_operation,
    '_normalize_agent_session_row': _normalize_agent_session_row,
    '_load_agent_session_snapshot': _load_agent_session_snapshot,
    '_load_agent_sessions': _load_agent_sessions,
    '_save_agent_sessions': _save_agent_sessions,
    '_agent_session_updated_age_seconds': _agent_session_updated_age_seconds,
    '_recover_stale_running_agent_sessions': _recover_stale_running_agent_sessions,
    '_agent_session_title_for_message': _agent_session_title_for_message,
    '_agent_session_summary': _agent_session_summary,
    '_agent_session_summaries': _agent_session_summaries,
    '_agent_session_detail': _agent_session_detail,
    '_agent_snapshot_from_session': _agent_snapshot_from_session,
    '_normalize_agent_live_activity': _normalize_agent_live_activity,
    '_agent_stream_tool_name': _agent_stream_tool_name,
    '_normalize_agent_stream_block': _normalize_agent_stream_block,
    '_agent_stream_block_key': _agent_stream_block_key,
    '_agent_live_activity_from_stream_blocks': _agent_live_activity_from_stream_blocks,
    '_agent_draft_turn_from_stream_blocks': _agent_draft_turn_from_stream_blocks,
    '_agent_live_activity_for_turn': _agent_live_activity_for_turn,
    '_save_agent_live_snapshot': _save_agent_live_snapshot,
    '_emit_agent_live_activity': _emit_agent_live_activity,
    '_try_emit_agent_live_activity': _try_emit_agent_live_activity,
    '_hydrate_agent_snapshot_for_ui': _hydrate_agent_snapshot_for_ui,
    'list_agent_sessions': list_agent_sessions,
    'get_agent_conversation_context': get_agent_conversation_context,
    'set_agent_conversation_context': set_agent_conversation_context,
    'list_agent_conversations': list_agent_conversations,
    'create_agent_conversation': create_agent_conversation,
    'ensure_episode_agent_conversation': ensure_episode_agent_conversation,
    'get_agent_session': get_agent_session,
    'get_agent_snapshot': get_agent_snapshot,
    'delete_agent_session': delete_agent_session,
    '_prepare_agent_sessions_for_project_delete': _prepare_agent_sessions_for_project_delete,
    '_ensure_agent_session': _ensure_agent_session,
    'card_dir': card_dir,
    'card_root': card_root,
    'create_custom_canvas_v4': create_custom_canvas_v4,
    'delete_custom_canvas_v4': delete_custom_canvas_v4,
    'delete_episode_canvas_v4': delete_episode_canvas_v4,
    'episode_canvas_exists': episode_canvas_exists,
    'ensure_episode_storage': ensure_episode_storage,
    'empty_canvas_workflow_projection_v4': empty_canvas_workflow_projection_v4,
    'read_canvas_workflow_projection_v4': read_canvas_workflow_projection_v4,
    'read_canvas_card_record_v4': read_canvas_card_record_v4,
    'read_canvas_cross_episode_visual_handoff_node_v4': read_canvas_cross_episode_visual_handoff_node_v4,
    'read_canvas_node_signatures_v4': read_canvas_node_signatures_v4,
    'read_canvas_prompt_storyboard_boundary_node_v4': read_canvas_prompt_storyboard_boundary_node_v4,
    'read_canvas_prompt_storyboard_neighbor_node_v4': read_canvas_prompt_storyboard_neighbor_node_v4,
    'read_canvas_visual_handoff_result_node_v4': read_canvas_visual_handoff_result_node_v4,
    'read_workflow_card_neighborhood_v4': read_workflow_card_neighborhood_v4,
    'replace_canvas_records_from_workflow_projection_v4': replace_canvas_records_from_workflow_projection_v4,
    'write_canvas_records_v4': write_canvas_records_v4,
    'delete_canvas_records_v4': delete_canvas_records_v4,
    'write_canvas_card_records_v4': write_canvas_card_records_v4,
    'list_canvas_changes_v4': list_canvas_changes_v4,
    'get_canvas_snapshot_v4': get_canvas_snapshot_v4,
    'get_canvas_records_v4': get_canvas_records_v4,
    'get_canvas_scope_records_v4': get_canvas_scope_records_v4,
    'list_project_custom_canvases_v4': list_project_custom_canvases_v4,
    'commit_canvas_result_v4': commit_canvas_result_v4,
    'read_canvas_task_records_v4': read_canvas_task_records_v4,
    'write_canvas_task_record_v4': write_canvas_task_record_v4,
    'write_canvas_task_records_v4': write_canvas_task_records_v4,
    'write_canvas_document_extras_v4': write_canvas_document_extras_v4,
    'write_canvas_production_status_v4': write_canvas_production_status_v4,
    'write_canvas_projection_cache_v4': write_canvas_projection_cache_v4,
    'rename_custom_canvas_v4': rename_custom_canvas_v4,
    'normalize_canvas_changed_resource_name': normalize_canvas_changed_resource_name,
    'normalize_canvas_changed_resources': normalize_canvas_changed_resources,
    'read_card_results': read_card_results,
    'read_episode_card_results': read_episode_card_results,
    'set_card_active_version': set_card_active_version,
    'delete_card_result_version': delete_card_result_version,
    '_normalize_project_id': _normalize_project_id,
    '_slug_from_title': _slug_from_title,
    '_find_template': _find_template,
    '_duration_to_seconds': _duration_to_seconds,
    '_status_label': _status_label,
    '_first_text': _first_text,
    '_text_list': _text_list,
    '_structured_fields': _structured_fields,
    '_structured_template_value': _structured_template_value,
    '_structured_template_object': _structured_template_object,
    '_structured_schema_contract': _structured_schema_contract,
    '_structured_prompt': _structured_prompt,
    '_structured_system_prompt': _structured_system_prompt,
    '_structured_json_schema': _structured_json_schema,
    '_structured_response_format': _structured_response_format,
    '_structured_model_api_name': _structured_model_api_name,
    '_provider_native_structured_status': _provider_native_structured_status,
    '_provider_supports_native_structured_output': _provider_supports_native_structured_output,
    '_provider_native_structured_endpoint': _provider_native_structured_endpoint,
    '_provider_with_native_structured_model_result': _provider_with_native_structured_model_result,
    '_structured_repair_prompt': _structured_repair_prompt,
    '_snake_to_camel': _snake_to_camel,
    '_camel_to_snake': _camel_to_snake,
    '_structured_field_keys': _structured_field_keys,
    '_structured_raw_value': _structured_raw_value,
    '_coerce_structured_value': _coerce_structured_value,
    '_structured_value_missing': _structured_value_missing,
    '_normalize_structured_payload': _normalize_structured_payload,
    '_display_time': _display_time,
    '_timestamp_rank': _timestamp_rank,
    '_normalize_project_title': _normalize_project_title,
    '_project_title_exists': _project_title_exists,
    '_project_relative_path': _project_relative_path,
    '_global_relative_path': _global_relative_path,
    '_is_path_within': _is_path_within,
    '_touch_project_meta': _touch_project_meta,
    '_local_project_image_ref': _local_project_image_ref,
    '_image_ref_from_value': _image_ref_from_value,
    '_project_style_reference_ref': _project_style_reference_ref,
    '_style_thumbnail_ref': _style_thumbnail_ref,
    '_favorite_style_thumbnail_path': _favorite_style_thumbnail_path,
    '_favorite_style_thumbnail_fields': _favorite_style_thumbnail_fields,
    '_favorite_style_thumbnail_ref': _favorite_style_thumbnail_ref,
    '_style_template_thumbnail_ref': _style_template_thumbnail_ref,
    '_project_content_image_refs': _project_content_image_refs,
    '_project_thumbnail_ref': _project_thumbnail_ref,
    '_project_asset_counts': _project_asset_counts,
    'get_project_asset_counts': get_project_asset_counts,
    '_project_row': _project_row,
    'list_projects': list_projects,
    'get_dashboard': get_dashboard,
    'set_current_project': set_current_project,
    'get_creation_options': get_creation_options,
    'get_global_settings': get_global_settings,
    '_save_global_config': _save_global_config,
    '_public_provider': _public_provider,
    'list_providers': list_providers,
    '_build_provider_from_add_payload': _build_provider_from_add_payload,
    '_provider_models_from_payload': _provider_models_from_payload,
    '_extract_provider_model_ids': _extract_provider_model_ids,
    '_extract_provider_model_rows': _extract_provider_model_rows,
    '_request_json': _request_json,
    '_response_json_for_log': _response_json_for_log,
    '_notify_response_received': _notify_response_received,
    '_deepseek_discovery_root': _deepseek_discovery_root,
    '_provider_default_base_url': _provider_default_base_url,
    '_provider_default_text_model': _provider_default_text_model,
    '_anthropic_messages_url': _anthropic_messages_url,
    '_anthropic_models_url': _anthropic_models_url,
    '_anthropic_auth_headers': _anthropic_auth_headers,
    '_ANTHROPIC_AUTH_TOKEN_GATEWAY_PATHS': _ANTHROPIC_AUTH_TOKEN_GATEWAY_PATHS,
    '_ANTHROPIC_MESSAGES_GATEWAY_PATHS': _ANTHROPIC_MESSAGES_GATEWAY_PATHS,
    '_looks_like_anthropic_auth_token_gateway': _looks_like_anthropic_auth_token_gateway,
    '_anthropic_sdk_base_url': _anthropic_sdk_base_url,
    '_anthropic_messages_auth_headers': _anthropic_messages_auth_headers,
    '_provider_claude_agent_base_url': _provider_claude_agent_base_url,
    '_provider_claude_agent_model': _provider_claude_agent_model,
    '_provider_claude_agent_auth_mode': _provider_claude_agent_auth_mode,
    '_anthropic_sdk_env': _anthropic_sdk_env,
    '_http_url_base': _http_url_base,
    '_openai_compatible_discovery_base_url': _openai_compatible_discovery_base_url,
    '_google_discovery_root_url': _google_discovery_root_url,
    '_provider_declares_agent_capability': _provider_declares_agent_capability,
    '_provider_declares_text_capability': _provider_declares_text_capability,
    '_normalized_url': _normalized_url,
    '_candidate_anthropic_agent_base_urls': _candidate_anthropic_agent_base_urls,
    '_anthropic_probe_auth_headers': _anthropic_probe_auth_headers,
    '_provider_probe_url_and_headers': _provider_probe_url_and_headers,
    '_CLAUDE_AGENT_SDK_PROBE_NAME': _CLAUDE_AGENT_SDK_PROBE_NAME,
    '_NATIVE_JSON_SCHEMA_PROBE_NAME': _NATIVE_JSON_SCHEMA_PROBE_NAME,
    '_NATIVE_JSON_SCHEMA_PROBE_SCHEMA': _NATIVE_JSON_SCHEMA_PROBE_SCHEMA,
    '_claude_agent_sdk_probe_from_result': _claude_agent_sdk_probe_from_result,
    '_native_json_schema_probe_from_result': _native_json_schema_probe_from_result,
    '_validate_native_json_schema_probe_text': _validate_native_json_schema_probe_text,
    '_run_openai_native_json_schema_probe': _run_openai_native_json_schema_probe,
    '_run_gemini_native_json_schema_probe': _run_gemini_native_json_schema_probe,
    '_run_native_json_schema_probe': _run_native_json_schema_probe,
    '_run_vidu_connection_test': _run_vidu_connection_test,
    '_run_ark_seedance_connection_test': _run_ark_seedance_connection_test,
    '_probe_claude_agent_sdk_runtime': _probe_claude_agent_sdk_runtime,
    '_provider_supports_claude_agent_sdk': _provider_supports_claude_agent_sdk,
    '_probe_summary_for_result': _probe_summary_for_result,
    '_with_provider_probe_summary': _with_provider_probe_summary,
    '_provider_connection_test_fingerprint': _provider_connection_test_fingerprint,
    '_with_provider_connection_test_context': _with_provider_connection_test_context,
    '_rebase_connection_test_models': _rebase_connection_test_models,
    '_validated_payload_connection_test_result': _validated_payload_connection_test_result,
    '_run_provider_connection_test': _run_provider_connection_test,
    'add_provider': add_provider,
    'update_provider': update_provider,
    'delete_provider': delete_provider,
    'test_provider_connection': test_provider_connection,
    'get_model_config': get_model_config,
    'save_model_config': save_model_config,
    'get_script_adaptation_templates': get_script_adaptation_templates,
    'get_text_replacement_rules': get_text_replacement_rules,
    '_string_list': _string_list,
    'save_script_adaptation_template': save_script_adaptation_template,
    'delete_script_adaptation_template': delete_script_adaptation_template,
    'save_text_replacement_rules': save_text_replacement_rules,
    'STORYBOARD_TEMPLATE_NARRATIVE': STORYBOARD_TEMPLATE_NARRATIVE,
    'STORYBOARD_TEMPLATE_BLOCKING': STORYBOARD_TEMPLATE_BLOCKING,
    'STORYBOARD_TEMPLATE_IMAGE_GRID': STORYBOARD_TEMPLATE_IMAGE_GRID,
    'STORYBOARD_TEMPLATE_NUMBERED_GRID': STORYBOARD_TEMPLATE_NUMBERED_GRID,
    'STORYBOARD_TEMPLATE_FILMSTRIP': STORYBOARD_TEMPLATE_FILMSTRIP,
    'STORYBOARD_TEMPLATE_DEFAULT': STORYBOARD_TEMPLATE_DEFAULT,
    'GLOBAL_STORYBOARD_TEMPLATES_PATH': GLOBAL_STORYBOARD_TEMPLATES_PATH,
    'load_storyboard_templates': load_storyboard_templates,
    'get_storyboard_templates': get_storyboard_templates,
    'save_storyboard_template': save_storyboard_template,
    'delete_storyboard_template': delete_storyboard_template,
    'storyboard_template_id': storyboard_template_id,
    'storyboard_template_label': storyboard_template_label,
    'storyboard_template_catalog': storyboard_template_catalog,
    'storyboard_template_selection_catalog': storyboard_template_selection_catalog,
    'storyboard_template_layout_spec': storyboard_template_layout_spec,
    'storyboard_template_from_mapping': storyboard_template_from_mapping,
    'storyboard_template_prompt_rules': storyboard_template_prompt_rules,
    'storyboard_template_single_panel_prompt_rules': storyboard_template_single_panel_prompt_rules,
    'GLOBAL_DIRECTOR_RULE_OVERRIDES_PATH': GLOBAL_DIRECTOR_RULE_OVERRIDES_PATH,
    'normalize_director_rule_identifier': normalize_director_rule_identifier,
    'list_director_rules_for_agent': list_director_rules_for_agent,
    'search_director_rules_for_agent': search_director_rules_for_agent,
    'read_director_rule_for_agent': read_director_rule_for_agent,
    'read_director_rule_document': read_director_rule_document,
    'get_director_rules': get_director_rules,
    'save_director_rule': save_director_rule,
    'reset_director_rule': reset_director_rule,
    '_decode_data_url': _decode_data_url,
    '_data_url': _data_url,
    '_source_media_data_url': _source_media_data_url,
    '_source_image_data_url': _source_image_data_url,
    '_storage_png_data_url': _storage_png_data_url,
    '_normalized_image_payload': _normalized_image_payload,
    '_file_extension': _file_extension,
    '_safe_file_stem': _safe_file_stem,
    '_project_media_relative_path': _project_media_relative_path,
    '_project_media_storage_dir': _project_media_storage_dir,
    '_save_project_media_file': _save_project_media_file,
    '_save_project_image_media_file': _save_project_image_media_file,
    '_copy_local_project_image_media_file': _copy_local_project_image_media_file,
    '_video_media_from_file_info': _video_media_from_file_info,
    '_copy_local_project_video_media_file': _copy_local_project_video_media_file,
    '_save_project_config_image_file': _save_project_config_image_file,
    '_copy_local_project_config_image_file': _copy_local_project_config_image_file,
    '_global_file_from_ref': _global_file_from_ref,
    '_save_global_asset_image_media_file': _save_global_asset_image_media_file,
    '_copy_local_global_asset_image_media_file': _copy_local_global_asset_image_media_file,
    '_local_image_source_from_media': _local_image_source_from_media,
    '_has_image_file_input': _has_image_file_input,
    '_normalize_global_media_asset': _normalize_global_media_asset,
    '_global_asset_media_path': _global_asset_media_path,
    '_delete_global_asset_media_file': _delete_global_asset_media_file,
    '_image_media_from_file_info': _image_media_from_file_info,
    '_download_image_url': _download_image_url,
    '_decode_image_response_value': _decode_image_response_value,
    '_extract_first_image_bytes': _extract_first_image_bytes,
    '_extract_first_media_url': _extract_first_media_url,
    '_extract_video_job_id': _extract_video_job_id,
    '_save_favorite_style_thumbnail': _save_favorite_style_thumbnail,
    'save_clipboard_image_media': save_clipboard_image_media,
    'get_video_clip_info': get_video_clip_info,
    'list_video_clip_results': list_video_clip_results,
    'delete_video_clip_results': delete_video_clip_results,
    'extract_video_frame_preview': extract_video_frame_preview,
    'extract_video_frame': extract_video_frame,
    'ensure_video_thumbnail': ensure_video_thumbnail,
    'trim_video_clip': trim_video_clip,
    '_configured_provider_for_model': _configured_provider_for_model,
    '_api_model_name': _api_model_name,
    '_provider_base_url': _provider_base_url,
    '_extract_response_text': _extract_response_text,
    '_extract_anthropic_response_text': _extract_anthropic_response_text,
    '_extract_gemini_response_text': _extract_gemini_response_text,
    '_post_json': _post_json,
    '_data_url_base64_payload': _data_url_base64_payload,
    '_provider_image_data_url_from_file_info': _provider_image_data_url_from_file_info,
    '_openai_compatible_generation_base_url': _openai_compatible_generation_base_url,
    '_call_openai_compatible_style_analysis': _call_openai_compatible_style_analysis,
    '_call_anthropic_style_analysis': _call_anthropic_style_analysis,
    '_call_gemini_style_analysis': _call_gemini_style_analysis,
    '_normalize_style_analysis_output': _normalize_style_analysis_output,
    '_call_style_analysis_model': _call_style_analysis_model,
    '_project_model_config': _project_model_config,
    '_agent_model_runtime_options': _agent_model_runtime_options,
    '_call_openai_compatible_text_model': _call_openai_compatible_text_model,
    '_call_anthropic_text_model': _call_anthropic_text_model,
    '_call_gemini_text_model': _call_gemini_text_model,
    '_call_text_model': _call_text_model,
    '_configured_media_model': _configured_media_model,
    '_provider_reference_image_from_storyboard_version': _provider_reference_image_from_storyboard_version,
    '_extract_storyboard_reference_image': _extract_storyboard_reference_image,
    '_provider_reference_image_from_media': _provider_reference_image_from_media,
    '_reference_identity_values': _reference_identity_values,
    '_active_asset_media_candidate': _active_asset_media_candidate,
    '_provider_reference_image_by_id': _provider_reference_image_by_id,
    '_provider_reference_images_from_ids': _provider_reference_images_from_ids,
    '_provider_reference_images_from_inline_files': _provider_reference_images_from_inline_files,
    '_call_openai_compatible_image_generation': _call_openai_compatible_image_generation,
    '_generate_storyboard_image_media': _generate_storyboard_image_media,
    '_generation_text_value': _generation_text_value,
    '_provider_reference_metadata': _provider_reference_metadata,
    '_video_provider_reference_plan': _video_provider_reference_plan,
    '_video_source_prompt_from_generation_payload': _video_source_prompt_from_generation_payload,
    '_video_prompt_from_generation_payload': _video_prompt_from_generation_payload,
    '_storyboard_video_debug_block_request_log_input': _storyboard_video_debug_block_request_log_input,
    '_build_storyboard_video_request': _build_storyboard_video_request,
    '_generate_storyboard_video_media': _generate_storyboard_video_media,
    '_configured_text_model': _configured_text_model,
    '_extract_json_payload': _extract_json_payload,
    '_attached_model_input_images': _attached_model_input_images,
    '_model_json_or_none': _model_json_or_none,
    '_model_text_or_none': _model_text_or_none,
    'analyze_style_image': analyze_style_image,
    '_save_project_cover': _save_project_cover,
    '_save_style_reference': _save_style_reference,
    '_build_project_config': _build_project_config,
    '_episode_count_from_payload': _episode_count_from_payload,
    '_default_workflow': _default_workflow,
    'create_project': create_project,
    'import_project': import_project,
    'delete_project': delete_project,
    'get_project_settings': get_project_settings,
    '_apply_model_config_projection': _apply_model_config_projection,
    '_apply_global_model_config': _apply_global_model_config,
    'save_project_settings': save_project_settings,
    'get_effective_config': get_effective_config,
    '_normalize_visual_context': _normalize_visual_context,
    'apply_theme_visual_context_to_config': apply_theme_visual_context_to_config,
    'apply_phase_visual_context_to_config': apply_phase_visual_context_to_config,
    'remove_phase_visual_context_from_config': remove_phase_visual_context_from_config,
    'list_assets': list_assets,
    '_normalize_global_asset_item_for_storage': _normalize_global_asset_item_for_storage,
    '_normalize_media_asset': _normalize_media_asset,
    '_normalize_asset_item_for_storage': _normalize_asset_item_for_storage,
    '_asset_store_path': _asset_store_path,
    '_asset_version_snapshot': _asset_version_snapshot,
    '_asset_version_state_changed': _asset_version_state_changed,
    '_asset_media_version': _asset_media_version,
    '_ensure_asset_media_versions': _ensure_asset_media_versions,
    '_asset_source_order_for_project': _asset_source_order_for_project,
    '_sort_asset_rows_by_source_order': _sort_asset_rows_by_source_order,
    '_asset_payload_has_design_prompt': _asset_payload_has_design_prompt,
    '_asset_name_key': _asset_name_key,
    '_find_asset_index_by_name': _find_asset_index_by_name,
    '_project_asset_media_paths': _project_asset_media_paths,
    '_delete_project_asset_media_files': _delete_project_asset_media_files,
    '_collect_plan_asset_refs': _collect_plan_asset_refs,
    '_project_storyboard_asset_refs': _project_storyboard_asset_refs,
    '_project_asset_is_referenced': _project_asset_is_referenced,
    '_apply_asset_design_prompt_patch': _apply_asset_design_prompt_patch,
    'create_asset': create_asset,
    'update_asset': update_asset,
    'delete_asset': delete_asset,
    'delete_all_project_assets': delete_all_project_assets,
    'set_active_asset_media_version': set_active_asset_media_version,
    'update_asset_media_version': update_asset_media_version,
    'delete_asset_media_version': delete_asset_media_version,
    '_asset_type_label': _asset_type_label,
    '_default_asset_design_prompt': _default_asset_design_prompt,
    '_ensure_asset_design_prompt_for_storage': _ensure_asset_design_prompt_for_storage,
    '_ASSET_IMAGE_PROMPT_KEYS': _ASSET_IMAGE_PROMPT_KEYS,
    '_ASSET_CHARACTER_LAYOUT': _ASSET_CHARACTER_LAYOUT,
    '_ASSET_CHARACTER_PROP_RULE': _ASSET_CHARACTER_PROP_RULE,
    '_ASSET_SCENE_LAYOUT': _ASSET_SCENE_LAYOUT,
    '_ASSET_PROP_LAYOUT': _ASSET_PROP_LAYOUT,
    '_ASSET_CHARACTER_GUARD': _ASSET_CHARACTER_GUARD,
    '_ASSET_CHARACTER_PRESENTATION_GUIDE': _ASSET_CHARACTER_PRESENTATION_GUIDE,
    '_ASSET_SCENE_GUARD': _ASSET_SCENE_GUARD,
    '_ASSET_PROP_GUARD': _ASSET_PROP_GUARD,
    '_ASSET_NEGATIVE_TAIL_CHARACTER': _ASSET_NEGATIVE_TAIL_CHARACTER,
    '_ASSET_NEGATIVE_TAIL': _ASSET_NEGATIVE_TAIL,
    '_asset_mapping_text': _asset_mapping_text,
    '_asset_design_prompt_from_asset': _asset_design_prompt_from_asset,
    '_asset_style_prefix': _asset_style_prefix,
    '_asset_project_style': _asset_project_style,
    '_asset_generation_description': _asset_generation_description,
    '_build_asset_character_prompt': _build_asset_character_prompt,
    '_build_asset_scene_prompt': _build_asset_scene_prompt,
    '_build_asset_prop_prompt': _build_asset_prop_prompt,
    '_asset_generation_aspect_ratio': _asset_generation_aspect_ratio,
    '_asset_generation_resolution': _asset_generation_resolution,
    '_asset_generation_prompt': _asset_generation_prompt,
    '_character_visual_prompt_is_complete': _character_visual_prompt_is_complete,
    '_raise_if_character_visual_prompt_incomplete': _raise_if_character_visual_prompt_incomplete,
    '_raise_if_asset_generation_prompt_override': _raise_if_asset_generation_prompt_override,
    '_generate_asset_image_media': _generate_asset_image_media,
    '_asset_image_task_focus_target': _asset_image_task_focus_target,
    '_asset_image_task_message': _asset_image_task_message,
    '_AssetImageTaskCancelled': _AssetImageTaskCancelled,
    '_asset_image_cancel_message': _asset_image_cancel_message,
    '_raise_if_asset_image_cancelled': _raise_if_asset_image_cancelled,
    '_find_asset_image_source_row': _find_asset_image_source_row,
    '_active_asset_image_task': _active_asset_image_task,
    '_run_asset_media_generation_task': _run_asset_media_generation_task,
    'start_asset_media_generation': start_asset_media_generation,
    'generate_asset_media': generate_asset_media,
    'list_sources': list_sources,
    'get_source_text': get_source_text,
    'save_source_text': save_source_text,
    'append_novel_source_files': append_novel_source_files,
    'delete_source_segment': delete_source_segment,
    'restore_source_total_snapshot': restore_source_total_snapshot,
    'SOURCE_GROUP_NOVEL': SOURCE_GROUP_NOVEL,
    'SOURCE_GROUP_SUPPLEMENTAL': SOURCE_GROUP_SUPPLEMENTAL,
    '_source_group': _source_group,
    '_is_novel_source': _is_novel_source,
    '_source_refs_for_meta': _source_refs_for_meta,
    '_CHAPTER_HEADING_RE': _CHAPTER_HEADING_RE,
    '_source_content_path': _source_content_path,
    '_safe_source_content_path': _safe_source_content_path,
    '_read_source_content': _read_source_content,
    '_source_index_path': _source_index_path,
    '_source_coverage_path': _source_coverage_path,
    '_sha256_text': _sha256_text,
    '_chapter_rows_for_source': _chapter_rows_for_source,
    '_chapter_id_for_offset': _chapter_id_for_offset,
    '_source_unit_rows_for_source': _source_unit_rows_for_source,
    'build_source_index': build_source_index,
    'list_source_index': list_source_index,
    'read_source_window': read_source_window,
    '_coverage_target_units': _coverage_target_units,
    '_default_source_coverage': _default_source_coverage,
    '_normalize_coverage_cursor': _normalize_coverage_cursor,
    '_normalize_source_coverage': _normalize_source_coverage,
    '_load_source_coverage': _load_source_coverage,
    '_write_source_coverage': _write_source_coverage,
    '_sync_source_coverage_targets': _sync_source_coverage_targets,
    '_reset_source_planning_state': _reset_source_planning_state,
    '_episode_source_ref_path': _episode_source_ref_path,
    '_episode_source_text_path': _episode_source_text_path,
    '_read_episode_source_text': _read_episode_source_text,
    '_episode_source_status': _episode_source_status,
    '_episode_source_rows': _episode_source_rows,
    'get_episode_source_text': get_episode_source_text,
    'save_episode_source_text': save_episode_source_text,
    'get_source_coverage': get_source_coverage,
    'list_asset_split_batches': list_asset_split_batches,
    'get_asset_split_batch_source_text': get_asset_split_batch_source_text,
    'open_source_file_location': open_source_file_location,
    'open_episode_source_file_location': open_episode_source_file_location,
    '_next_episode_id': _next_episode_id,
    '_natural_boundary_candidates': _natural_boundary_candidates,
    '_range_source_excerpt': _range_source_excerpt,
    '_source_coverage_commit_guard': _source_coverage_commit_guard,
    '_commit_next_step': _commit_next_step,
    '_episode_boundary_commit_payload': _episode_boundary_commit_payload,
    '_asset_range_commit_payload': _asset_range_commit_payload,
    '_unwrap_agent_commit_payload': _unwrap_agent_commit_payload,
    '_ensure_episode_meta_entry': _ensure_episode_meta_entry,
    'commit_asset_range': commit_asset_range,
    '_confirmed_asset_range': _confirmed_asset_range,
    '_source_refs_from_asset_row': _source_refs_from_asset_row,
    '_source_ref_bounds': _source_ref_bounds,
    '_validate_asset_batch_refs_in_range': _validate_asset_batch_refs_in_range,
    '_stamp_asset_range_id': _stamp_asset_range_id,
    '_asset_ids_from_payload': _asset_ids_from_payload,
    '_append_created_asset_ids_to_range': _append_created_asset_ids_to_range,
    '_refresh_created_asset_ids_for_range': _refresh_created_asset_ids_for_range,
    '_asset_ranges_for_source_ref': _asset_ranges_for_source_ref,
    '_json_hash': _json_hash,
    '_resource_revision_value': _resource_revision_value,
    '_assert_resource_write_guard': _assert_resource_write_guard,
    '_project_json_resource_path': _project_json_resource_path,
    '_assert_project_json_resource_is_patchable': _assert_project_json_resource_is_patchable,
    '_resource_revisions_path': _resource_revisions_path,
    '_append_resource_revision': _append_resource_revision,
    '_json_pointer_tokens': _json_pointer_tokens,
    '_container_for_pointer': _container_for_pointer,
    '_apply_json_patch_op': _apply_json_patch_op,
    'create_resource_revision': create_resource_revision,
    'patch_project_resource': patch_project_resource,
    '_select_project_sources': _select_project_sources,
    '_source_collection_title': _source_collection_title,
    '_source_collection_text': _source_collection_text,
    'create_source': create_source,
    'replace_sources': replace_sources,
    'analyze_project_overview': analyze_project_overview,
    'update_project_overview': update_project_overview,
    'get_project_narrator_voice_profile': get_project_narrator_voice_profile,
    'save_project_narrator_reference_audio': save_project_narrator_reference_audio,
    'prepare_reference_audio': prepare_reference_audio,
    'crop_reference_audio': crop_reference_audio,
    'cleanup_reference_audio': cleanup_reference_audio,
    '_project_source_text': _project_source_text,
    '_compact_text': _compact_text,
    'GENERATION_USER_INSTRUCTION_KEYS': GENERATION_USER_INSTRUCTION_KEYS,
    '_first_mapping_text': _first_mapping_text,
    '_generation_user_instruction': _generation_user_instruction,
    '_append_generation_instruction': _append_generation_instruction,
    '_split_sentences': _split_sentences,
    '_agent_text_unit_count': _agent_text_unit_count,
    '_join_agent_sentences': _join_agent_sentences,
    '_chunk_text_by_units': _chunk_text_by_units,
    '_chunk_sentences': _chunk_sentences,
    '_build_agent_assets': _build_agent_assets,
    '_normalize_agent_asset_rows': _normalize_agent_asset_rows,
    '_agent_assets_from_model': _agent_assets_from_model,
    '_agent_episode_script_from_chunk': _agent_episode_script_from_chunk,
    '_model_episode_chunks': _model_episode_chunks,
    '_write_agent_assets': _write_agent_assets,
    'AGENT_TEXT_RESULT_SOURCES': AGENT_TEXT_RESULT_SOURCES,
    '_agent_text_row_text': _agent_text_row_text,
    '_normalize_character_voice_style': _normalize_character_voice_style,
    '_agent_text_asset_match_index': _agent_text_asset_match_index,
    '_agent_text_asset_summary': _agent_text_asset_summary,
    '_normalize_agent_text_asset_row': _normalize_agent_text_asset_row,
    '_design_asset_completion_issue': _design_asset_completion_issue,
    '_assert_design_asset_complete': _assert_design_asset_complete,
    '_save_agent_text_assets': _save_agent_text_assets,
    '_agent_text_episode_id': _agent_text_episode_id,
    '_panel_row_text': _panel_row_text,
    '_panel_reference_media_ids': _panel_reference_media_ids,
    '_panel_generation_strategy': _panel_generation_strategy,
    '_strategy_reference_mode': _strategy_reference_mode,
    '_segment_asset_refs': _segment_asset_refs,
    '_panel_to_prompts': _panel_to_prompts,
    '_panels_to_shot_plan': _panels_to_shot_plan,
    '_shot_plan_generation_config': _shot_plan_generation_config,
    '_layout_workflow_by_work_chain': _layout_workflow_by_work_chain,
    '_work_chain_plan_to_workflow': _work_chain_plan_to_workflow,
    '_save_episode_production_plan_from_panels': _save_episode_production_plan_from_panels,
    '_save_agent_text_episodes': _save_agent_text_episodes,
    '_payload_document': _payload_document,
    '_is_user_locked_item': _is_user_locked_item,
    '_item_identity': _item_identity,
    '_preserve_locked_items': _preserve_locked_items,
    '_preserve_locked_plan_document': _preserve_locked_plan_document,
    '_write_project_document': _write_project_document,
    'save_story_world_map': save_story_world_map,
    '_asset_refs_from_plan_item': _asset_refs_from_plan_item,
    '_asset_refs_has_value': _asset_refs_has_value,
    '_normalize_shot_plan_asset_refs': _normalize_shot_plan_asset_refs,
    '_asset_ref_tokens': _asset_ref_tokens,
    '_ASSET_REF_COLLECTIONS': _ASSET_REF_COLLECTIONS,
    '_ASSET_REF_LABELS': _ASSET_REF_LABELS,
    '_asset_ref_tokens_by_collection': _asset_ref_tokens_by_collection,
    '_validate_asset_refs_for_episode_scope': _validate_asset_refs_for_episode_scope,
    '_validate_workflow_asset_refs': _validate_workflow_asset_refs,
    '_dedupe_reference_tokens': _dedupe_reference_tokens,
    '_asset_reference_ids_from_refs': _asset_reference_ids_from_refs,
    '_merge_reference_ids': _merge_reference_ids,
    '_asset_reference_ids_from_generation_sources': _asset_reference_ids_from_generation_sources,
    '_asset_refs_resolved_by_input_links': _asset_refs_resolved_by_input_links,
    '_workflow_asset_ref_panel_rows': _workflow_asset_ref_panel_rows,
    '_collect_workflow_asset_refs': _collect_workflow_asset_refs,
    '_filter_asset_refs_to_active_project_assets': _filter_asset_refs_to_active_project_assets,
    '_asset_ref_canvas_materials': _asset_ref_canvas_materials,
    'storyboard_asset_refs_from_current_sources': storyboard_asset_refs_from_current_sources,
    'bind_storyboard_asset_refs_from_text': bind_storyboard_asset_refs_from_text,
    'storyboard_unmatched_asset_mentions': storyboard_unmatched_asset_mentions,
    '_auto_bind_shot_plan_asset_refs': _auto_bind_shot_plan_asset_refs,
    '_project_asset_lookup': _project_asset_lookup,
    '_project_asset_lookup_with_scope': _project_asset_lookup_with_scope,
    '_validate_plan_asset_refs': _validate_plan_asset_refs,
    'save_episode_work_chain_plan': save_episode_work_chain_plan,
    '_planning_count': _planning_count,
    '_planning_text': _planning_text,
    '_planning_episode_range_summary': _planning_episode_range_summary,
    '_planning_boundary_plan_from_source_coverage': _planning_boundary_plan_from_source_coverage,
    '_planning_episode_boundary_export': _planning_episode_boundary_export,
    'get_project_planning_summary': get_project_planning_summary,
    'save_asset_batch': save_asset_batch,
    'upsert_asset': upsert_asset,
    '_episode_range_for_id': _episode_range_for_id,
    '_source_ref_in_episode_range': _source_ref_in_episode_range,
    '_source_ref_unit_ids': _source_ref_unit_ids,
    '_source_units_for_ref': _source_units_for_ref,
    '_stamp_source_units_on_ref': _stamp_source_units_on_ref,
    '_source_ref_has_valid_unit_ref': _source_ref_has_valid_unit_ref,
    '_stamp_source_units_on_source_refs': _stamp_source_units_on_source_refs,
    '_stamp_source_units_on_shot_plan': _stamp_source_units_on_shot_plan,
    '_stamp_source_units_on_workflow': _stamp_source_units_on_workflow,
    '_shot_source_refs': _shot_source_refs,
    '_validate_shot_plan_source_refs': _validate_shot_plan_source_refs,
    'patch_shot_prompt': patch_shot_prompt,
    '_workflow_route_by_id': _workflow_route_by_id,
    '_workflow_node_by_id': _workflow_node_by_id,
    '_media_generation_config': _media_generation_config,
    '_generation_media_type_from_node': _generation_media_type_from_node,
    '_default_generation_config': _default_generation_config,
    '_normalized_model_capabilities': _normalized_model_capabilities,
    'resolve_generation_config': resolve_generation_config,
    'WORKFLOW_NODE_SLOT_SCHEMA': WORKFLOW_NODE_SLOT_SCHEMA,
    'list_model_capabilities': list_model_capabilities,
    'preflight_workflow_node': preflight_workflow_node,
    '_safe_workflow_id': _safe_workflow_id,
    '_ensure_generation_workflow_node': _ensure_generation_workflow_node,
    '_truthy_payload_flag': _truthy_payload_flag,
    '_submit_real_provider_requested': _submit_real_provider_requested,
    '_request_generation_version': _request_generation_version,
    '_director_plan_shot_rows_from_structured': _director_plan_shot_rows_from_structured,
    '_video_task_card_target_model_context': _video_task_card_target_model_context,
    '_video_task_card_prompt_from_structured_shots': _video_task_card_prompt_from_structured_shots,
    'VIDEO_TASK_CARD_PROMPT_TEMPLATE_VERSION': VIDEO_TASK_CARD_PROMPT_TEMPLATE_VERSION,
    'sync_work_chain_video_duration': sync_work_chain_video_duration,
    'video_task_card_current_reference_snapshot': video_task_card_current_reference_snapshot,
    'request_route_video_generation': request_route_video_generation,
    'build_worker_task_context': build_worker_task_context,
    'worker_work_definition': worker_work_definition,
    'validate_analyze_assets_worker_output': validate_analyze_assets_worker_output,
    'validate_plot_splitting_worker_output': validate_plot_splitting_worker_output,
    '_asset_ref_in_confirmed_range': _asset_ref_in_confirmed_range,
    '_quality_node_ids_for_generation_task': _quality_node_ids_for_generation_task,
    'validate_project_quality': validate_project_quality,
    '_update_agent_workflow': _update_agent_workflow,
    '_agent_overview_ready': _agent_overview_ready,
    '_agent_episode_boundary_ready': _agent_episode_boundary_ready,
    '_agent_episode_production_progress': _agent_episode_production_progress,
    '_agent_progress_state': _agent_progress_state,
    '_agent_steps_from_state': _agent_steps_from_state,
    '_agent_task_progress_content_block': _agent_task_progress_content_block,
    '_agent_result_content_blocks': _agent_result_content_blocks,
    '_agent_tool_result_summary': _agent_tool_result_summary,
    '_agent_project_effect_for_action': _agent_project_effect_for_action,
    '_agent_action_label': _agent_action_label,
    '_agent_recommended_action': _agent_recommended_action,
    '_agent_recommendation_item': _agent_recommendation_item,
    '_agent_stage_recommendations': _agent_stage_recommendations,
    '_agent_stage_next_step_label': _agent_stage_next_step_label,
    '_agent_progress_message': _agent_progress_message,
    '_agent_workflow_explainer': _agent_workflow_explainer,
    '_execute_agent_action': _execute_agent_action,
    '_AGENT_BACKGROUND_ACTIONS': _AGENT_BACKGROUND_ACTIONS,
    '_AGENT_ALLOWED_ACTIONS': _AGENT_ALLOWED_ACTIONS,
    '_AGENT_ACTION_ORDER': _AGENT_ACTION_ORDER,
    '_AGENT_PROGRAM_DIRECT_ACTIONS': _AGENT_PROGRAM_DIRECT_ACTIONS,
    '_load_agent_ops_permissions': _load_agent_ops_permissions,
    '_agent_allowed_actions': _agent_allowed_actions,
    '_agent_action_order': _agent_action_order,
    '_agent_program_direct_actions': _agent_program_direct_actions,
    '_agent_program_action_from_message': _agent_program_action_from_message,
    '_agent_is_background_action': _agent_is_background_action,
    '_agent_validate_action': _agent_validate_action,
    '_agent_action_description': _agent_action_description,
    '_agent_action_prompt': _agent_action_prompt,
    '_agent_action_icon': _agent_action_icon,
    '_agent_skill_frontmatter': _agent_skill_frontmatter,
    'list_agent_skills': list_agent_skills,
    '_agent_session_messages_for_prompt': _agent_session_messages_for_prompt,
    '_agent_session_history_summary_for_prompt': _agent_session_history_summary_for_prompt,
    '_agent_sdk_session_id_for_resume': _agent_sdk_session_id_for_resume,
    '_agent_conversation_context_for_prompt': _agent_conversation_context_for_prompt,
    '_agent_source_context_for_prompt': _agent_source_context_for_prompt,
    '_agent_overview_context_for_prompt': _agent_overview_context_for_prompt,
    '_agent_decision_requires_answer': _agent_decision_requires_answer,
    '_agent_sanitize_pending_question': _agent_sanitize_pending_question,
    '_agent_pending_question_from_decision': _agent_pending_question_from_decision,
    '_agent_decision_content_blocks': _agent_decision_content_blocks,
    '_agent_normalize_turn_decision': _agent_normalize_turn_decision,
    '_agent_sdk_runtime_config': _agent_sdk_runtime_config,
    '_truncate_process_text': _truncate_process_text,
    '_agent_media_tool_project_root': _agent_media_tool_project_root,
    '_agent_media_tool_int': _agent_media_tool_int,
    '_agent_media_tool_reject_unsafe_text': _agent_media_tool_reject_unsafe_text,
    '_agent_media_arg_looks_like_path': _agent_media_arg_looks_like_path,
    '_agent_media_tool_resolve_arg': _agent_media_tool_resolve_arg,
    '_agent_media_tool_args': _agent_media_tool_args,
    '_agent_project_file_entry': _agent_project_file_entry,
    'list_project_files_for_agent': list_project_files_for_agent,
    'search_project_files_for_agent': search_project_files_for_agent,
    'read_project_file_for_agent': read_project_file_for_agent,
    'run_project_media_tool': run_project_media_tool,
    '_agent_configured_model_summary': _agent_configured_model_summary,
    '_agent_result_used_sdk_stream': _agent_result_used_sdk_stream,
    '_update_task_fields': _update_task_fields,
    '_agent_session_payload': _agent_session_payload,
    '_emit_agent_session_update': _emit_agent_session_update,
    '_emit_agent_project_effect': _emit_agent_project_effect,
    '_finish_agent_session_result': _finish_agent_session_result,
    'append_agent_generation_task_session_report': append_agent_generation_task_session_report,
    '_interrupt_agent_session_state': _interrupt_agent_session_state,
    'interrupt_agent_session': interrupt_agent_session,
    '_agent_next_running_step_id': _agent_next_running_step_id,
    '_resolve_agent_turn_result': _resolve_agent_turn_result,
    '_start_agent_background_turn': _start_agent_background_turn,
    '_run_agent_inline_turn': _run_agent_inline_turn,
    '_agent_turn_background_worker': _agent_turn_background_worker,
    'run_agent_message': run_agent_message,
    '_agent_answer_candidates': _agent_answer_candidates,
    '_agent_answers_summary': _agent_answers_summary,
    '_agent_pending_option_label': _agent_pending_option_label,
    '_agent_action_from_answers': _agent_action_from_answers,
    'answer_agent_question': answer_agent_question,
    'delete_source': delete_source,
    'delete_project_planning_outputs': delete_project_planning_outputs,
    'empty_episode_workflow': empty_episode_workflow,
    'get_canvas_workflow_projection': get_canvas_workflow_projection,
    'build_episode_workflow_from_work_chain_plan': build_episode_workflow_from_work_chain_plan,
    'adjust_source_split_workflow': adjust_source_split_workflow,
    'apply_storyboard_allocation': apply_storyboard_allocation,
    'create_independent_source_card': create_independent_source_card,
    'apply_independent_source_workflow': apply_independent_source_workflow,
    'create_manual_workflow_chain': create_manual_workflow_chain,
    'relayout_episode_workflow': relayout_episode_workflow,
    '_workflow_versions_path': _workflow_versions_path,
    '_workflow_version_label': _workflow_version_label,
    '_append_workflow_version': _append_workflow_version,
    'replace_canvas_workflow_projection': replace_canvas_workflow_projection,
    'list_workflow_media': list_workflow_media,
    'link_workflow_input': link_workflow_input,
    'unlink_workflow_input': unlink_workflow_input,
    'list_workflow_inputs': list_workflow_inputs,
    'resolve_workflow_node_inputs': resolve_workflow_node_inputs,
    'validate_workflow_node_inputs_ready': validate_workflow_node_inputs_ready,
    'list_workflow_tasks': list_workflow_tasks,
    'run_workflow_batch': run_workflow_batch,
    'save_variant_quality_result': save_variant_quality_result,
    'auto_review_variant_quality': auto_review_variant_quality,
    'import_workflow_media': import_workflow_media,
    'create_workflow_task_card': create_workflow_task_card,
    'add_workflow_asset_nodes': add_workflow_asset_nodes,
    'paste_workflow_asset_node': paste_workflow_asset_node,
    'update_workflow_route': update_workflow_route,
    'create_workflow_node': create_workflow_node,
    'delete_workflow_node': delete_workflow_node,
    'upsert_workflow_node': upsert_workflow_node,
    'rename_workflow_asset_node': rename_workflow_asset_node,
    'update_workflow_node_layout': update_workflow_node_layout,
    'record_node_edit_history': record_node_edit_history,
    'record_workflow_node_edit_history': record_workflow_node_edit_history,
    'list_node_edit_history': list_node_edit_history,
    'delete_node_edit_history': delete_node_edit_history,
    'list_director_rework_records': list_director_rework_records,
    'delete_director_rework_record': delete_director_rework_record,
    'restore_node_edit_history': restore_node_edit_history,
    'save_workflow_node_inline_edit': save_workflow_node_inline_edit,
    'resolve_canvas_asset_images': resolve_canvas_asset_images,
    'delete_workflow_item': delete_workflow_item,
    'list_storyboard_versions': list_storyboard_versions,
    '_xml_text': _xml_text,
    '_panel_value': _panel_value,
    '_workflow_node': _workflow_node,
    '_workflow_node_data': _workflow_node_data,
    'find_workflow_nodes': find_workflow_nodes,
    'resolve_generation_task_node_id': resolve_generation_task_node_id,
    'workflow_storyboard_reference_node_ids': workflow_storyboard_reference_node_ids,
    'workflow_storyboard_image_director_node_id': workflow_storyboard_image_director_node_id,
    'workflow_video_task_scope': workflow_video_task_scope,
    'workflow_node_is_default_work_chain_video_task': workflow_node_is_default_work_chain_video_task,
    'workflow_video_task_work_chain_storyboard_node_ids': workflow_video_task_work_chain_storyboard_node_ids,
    'ensure_visual_handoff_result_node': ensure_visual_handoff_result_node,
    'sync_visual_handoff_cross_episode_link': sync_visual_handoff_cross_episode_link,
    'workflow_current_media_reference': workflow_current_media_reference,
    'workflow_current_media_version_has_media': workflow_current_media_version_has_media,
    'workflow_generation_related_node_ids': workflow_generation_related_node_ids,
    '_workflow_panels': _workflow_panels,
    '_duration_seconds_value': _duration_seconds_value,
    '_panel_duration_seconds': _panel_duration_seconds,
    '_storyboard_panels_duration_seconds': _storyboard_panels_duration_seconds,
    '_storyboard_payload_duration_seconds': _storyboard_payload_duration_seconds,
    '_workflow_video_task_card_duration_seconds': _workflow_video_task_card_duration_seconds,
    '_clean_runtime_generation_config': _clean_runtime_generation_config,
    '_runtime_generation_config_from_node': _runtime_generation_config_from_node,
    '_runtime_generation_config_for_execution': _runtime_generation_config_for_execution,
    '_panel_title': _panel_title,
    '_panel_asset_ref_text': _panel_asset_ref_text,
    '_panel_prompt': _panel_prompt,
    '_storyboard_prompt_payload': _storyboard_prompt_payload,
    '_storyboard_svg_preview': _storyboard_svg_preview,
    '_generated_version_preview': _generated_version_preview,
    'build_storyboard_generation_metadata': build_storyboard_generation_metadata,
    'add_storyboard_version': add_storyboard_version,
    'upload_storyboard_image': upload_storyboard_image,
    'edit_storyboard_image': edit_storyboard_image,
    '_update_storyboard_version_metadata': _update_storyboard_version_metadata,
    'set_storyboard_result_active_version': set_storyboard_result_active_version,
    'select_workflow_variant': select_workflow_variant,
    'delete_storyboard_version': delete_storyboard_version,
    '_load_tasks': _load_tasks,
    '_load_tasks_for_project': _load_tasks_for_project,
    '_load_task_storage_bucket': _load_task_storage_bucket,
    '_save_tasks': _save_tasks,
    '_save_task_storage_bucket': _save_task_storage_bucket,
    '_task_storage_key_for_task_id': _task_storage_key_for_task_id,
    'create_task': create_task,
    'is_task_cancelled': is_task_cancelled,
    'register_background_task_thread': register_background_task_thread,
    'unregister_background_task_thread': unregister_background_task_thread,
    '_get_task': _get_task,
    '_emit_task_update': _emit_task_update,
    '_update_task_if_active': _update_task_if_active,
    '_update_asset_image_task': _update_asset_image_task,
    '_update_video_task': _update_video_task,
    '_provider_for_video_job': _provider_for_video_job,
    '_response_to_storyboard_video_metadata': _response_to_storyboard_video_metadata,
    '_fail_storyboard_video_version': _fail_storyboard_video_version,
    '_cancel_storyboard_video_version': _cancel_storyboard_video_version,
    '_poll_storyboard_video_job': _poll_storyboard_video_job,
    '_cancel_storyboard_video_provider_job': _cancel_storyboard_video_provider_job,
    '_cancel_message_with_provider_result': _cancel_message_with_provider_result,
    '_storyboard_video_job_from_request': _storyboard_video_job_from_request,
    '_update_storyboard_video_processing_version': _update_storyboard_video_processing_version,
    '_finish_storyboard_video_task': _finish_storyboard_video_task,
    '_run_storyboard_video_task': _run_storyboard_video_task,
    '_ensure_storyboard_video_worker': _ensure_storyboard_video_worker,
    '_resume_storyboard_video_tasks': _resume_storyboard_video_tasks,
    'start_storyboard_video_generation': start_storyboard_video_generation,
    '_emit_generation_task_result': _emit_generation_task_result,
    '_assert_generation_closure_ready': _assert_generation_closure_ready,
    'run_storyboard_generation_task': run_storyboard_generation_task,
    'list_tasks': list_tasks,
    'delete_episode_derived_tasks': delete_episode_derived_tasks,
    'clear_task_notifications': clear_task_notifications,
    'cancel_agent_session_bound_tasks': cancel_agent_session_bound_tasks,
    'cancel_task': cancel_task,
    'diagnose_task': diagnose_task,
    'get_usage_summary': get_usage_summary,
    'HOME_ARCHIVE_MANIFEST': HOME_ARCHIVE_MANIFEST,
    'HOME_ARCHIVE_FORMAT': HOME_ARCHIVE_FORMAT,
    'recover_home_archive_imports': recover_home_archive_imports,
    'start_home_archive_export': start_home_archive_export,
    'start_home_archive_import': start_home_archive_import,
    'detect_jianying_draft_root': detect_jianying_draft_root,
    'get_jianying_export_info': get_jianying_export_info,
    'start_jianying_draft_export': start_jianying_draft_export,
    'start_video_files_export': start_video_files_export,
    '_export_episode_rows': _export_episode_rows,
    '_has_export_value': _has_export_value,
    '_first_export_value': _first_export_value,
    '_mapping_export_value': _mapping_export_value,
    '_node_export_context': _node_export_context,
    '_append_node_plan_entry': _append_node_plan_entry,
    '_collect_asset_definition_exports': _collect_asset_definition_exports,
    '_route_quality_issue': _route_quality_issue,
    '_generation_models_from_config': _generation_models_from_config,
    '_route_quality_reports': _route_quality_reports,
    '_route_comparison_groups': _route_comparison_groups,
    '_project_planning_export_bundle': _project_planning_export_bundle,
    '_jianying_cut_guide': _jianying_cut_guide,
    'export_project_assets': export_project_assets,
    'copy_project_tree': copy_project_tree,
    'get_episode_review_results': get_episode_review_results,
    'save_episode_review_results': save_episode_review_results,
    'waive_review_issue': waive_review_issue,
    'get_episode_production_status': get_episode_production_status,
    'update_episode_production_status': update_episode_production_status,
    '_favorite_style_name_key': _favorite_style_name_key,
    '_find_favorite_style_index_by_name': _find_favorite_style_index_by_name,
    'create_favorite_style_template': create_favorite_style_template,
    'delete_favorite_style_template': delete_favorite_style_template,
    'update_favorite_style_template': update_favorite_style_template,
    'upload_style_image': upload_style_image,
}
__all__ = tuple(_EXPORTS)

def export_namespace() -> dict[str, Any]:
    """Return a copy of the explicitly declared public API."""
    return dict(_EXPORTS)
