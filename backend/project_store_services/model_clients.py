# -*- coding: utf-8 -*-
"""模型调用 API 的直接导出；实现按协议、参考媒体和生成流程归属。"""
from __future__ import annotations

from .generation_input_context import (
    GENERATION_USER_INSTRUCTION_KEYS,
    _generation_user_instruction,
)
from .model_generation_contract import (
    _IMAGE_REFERENCE_VIDEO_STRATEGIES,
    _LEGACY_STORYBOARD_VIDEO_STRATEGIES,
    _STORYBOARD_REFERENCE_ASSET_TYPE_KEYS,
    _STORYBOARD_REFERENCE_TYPE_VALUES,
    _SUPPLIER_OFFICIAL_FINAL_VIDEO_PROMPT_PROFILES,
    _SUPPORTED_FINAL_VIDEO_PROMPT_PROFILES,
    _generation_text_value,
    _model_capability_sources,
    _model_final_prompt_profile,
    _model_prompt_timing_style,
    _model_supports_storyboard_reference_image,
    _normalize_video_generation_strategy,
    _normalize_video_input_mode,
    _positive_int_config_value,
    _project_ai_content_disclosure_metadata,
    _reference_has_storyboard_asset_type,
    _reference_is_storyboard_sheet,
    _reference_is_visual_handoff,
    _video_input_mode_for_strategy,
    _video_reference_mode_for_input_mode,
    _video_strategy_for_input_mode,
    _visual_style_prompt_for_model,
)
from .model_provider_config import (
    _agent_model_runtime_options,
    _api_model_name,
    _configured_media_model,
    _configured_provider_for_model,
    _configured_text_model,
    _debug_block_builtin_video_provider_and_model,
    _get_effective_config,
    _openai_compatible_generation_base_url,
    _project_model_config,
    _provider_base_url,
    _video_generation_debug_block_enabled,
)
from .model_style_analysis import (
    _STYLE_ANALYSIS_ENGLISH_REPLACEMENTS,
    _STYLE_ANALYSIS_FORBIDDEN_SEGMENT_TERMS,
    _call_anthropic_style_analysis,
    _call_gemini_style_analysis,
    _call_openai_compatible_style_analysis,
    _call_style_analysis_model,
    _drop_forbidden_style_analysis_segments,
    _normalize_style_analysis_output,
    _strip_unapproved_latin_text,
    _style_analysis_output_has_required_fields,
    _style_analysis_text_from_payload,
)
from .model_text_client import (
    _attached_model_input_images,
    _call_anthropic_text_model,
    _call_gemini_text_model,
    _call_openai_compatible_text_model,
    _call_text_model,
    _ensure_native_structured_model_checked,
    _extract_anthropic_response_text,
    _extract_gemini_response_text,
    _extract_json_payload,
    _extract_response_text,
    _is_text_request_timeout,
    _model_json_or_none,
    _model_text_or_none,
    _notify_text_request_prepared,
    _persist_native_structured_model_result,
    _post_json,
)
from .provider_reference_media import _PROVIDER_REFERENCE_FILE_ID_KEYS
from .provider_reference_media import _VIDEO_REFERENCE_FILE_SUFFIXES
from .provider_reference_media import _active_asset_media_candidate
from .provider_reference_media import _asset_refs_resolved_by_input_links_for_provider
from .provider_reference_media import _data_url_base64_payload
from .provider_reference_media import _extract_storyboard_reference_image
from .provider_reference_media import _provider_image_data_url_from_data_url
from .provider_reference_media import _provider_image_data_url_from_file_info
from .provider_reference_media import _provider_media_reference_http_url
from .provider_reference_media import _provider_media_reference_is_video
from .provider_reference_media import _provider_media_reference_suffix
from .provider_reference_media import _provider_model_input_images
from .provider_reference_media import _provider_reference_assets_from_context
from .provider_reference_media import _provider_reference_file_id_from_fields
from .provider_reference_media import _provider_reference_file_id_from_value
from .provider_reference_media import _provider_reference_image_by_id
from .provider_reference_media import _provider_reference_image_from_media
from .provider_reference_media import _provider_reference_image_from_storyboard_version
from .provider_reference_media import _provider_reference_image_metadata_only
from .provider_reference_media import _provider_reference_images_from_ids
from .provider_reference_media import _provider_reference_images_from_inline_files
from .provider_reference_media import _provider_reference_metadata
from .provider_reference_media import _provider_reference_prepare_kwargs
from .provider_reference_media import _provider_reference_resolution_context
from .provider_reference_media import _provider_reference_videos_from_ids
from .provider_reference_media import _reference_identity_values
from .media_files import _source_image_data_url
from .media_files import _storage_png_data_url
from .provider_reference_media import _truthy_reference_flag
from .storyboard_image_generation import (
    _IMAGE_EDIT_BASE_PRESERVATION_INSTRUCTION,
    _IMAGE_EDIT_EXTRA_REFERENCE_ROLE_INSTRUCTION,
    _REFERENCE_REQUEST_KEYS,
    _append_generation_instruction,
    _append_image_edit_base_preservation_instruction,
    _append_image_edit_reference_role_instruction,
    _append_image_request_prompt_instruction,
    _append_storyboard_generation_instruction,
    _append_storyboard_image_phase_visual_prompt,
    _call_openai_compatible_image_generation,
    _debug_image_input_token_count,
    _debug_request_has_reference_image,
    _debug_request_reference_file_id_count,
    _generate_storyboard_image_media,
    _insert_storyboard_actual_output_spec_prompt,
    _insert_storyboard_project_visual_supplement_prompt,
    _insert_storyboard_section_before_prompt_contract,
    _parse_image_size_text,
    _provider_generated_image_file_id_from_debug,
    _storyboard_actual_output_spec_prompt,
    _storyboard_image_generation_error,
    _storyboard_image_reference_consumption_report,
    _storyboard_project_visual_supplement_prompt,
    _storyboard_prompt_is_full_sheet,
    _storyboard_reference_consistency_prompt,
    _storyboard_reference_role_flags,
    _storyboard_transport_reference_image,
    _storyboard_visual_block_content,
)
from .storyboard_video_generation import (
    _build_storyboard_video_request,
    _generate_storyboard_video_media,
    _storyboard_video_debug_block_request_log_input,
    _validate_native_frame_aspect_ratio,
    _video_generate_audio_enabled,
    _video_input_plan_from_payload,
    _video_output_aspect_ratio,
    _video_task_scope_from_payload_or_workflow,
)
from .task_control import (
    _check_generation_task_cancelled,
)
from .video_generation_prompt import (
    _VIDEO_VOICE_STYLE_ASSET_COLLECTIONS,
    _VIDEO_VOICE_STYLE_REFERENCE_SLOTS,
    _apply_final_video_prompt_replacement_rules,
    _current_video_task_prompt_from_payload,
    _dashscope_wan_reference_sentence,
    _seedance_official_reference_sentence,
    _storyboard_reference_instruction,
    _supplier_official_asset_reference_prompt_from_payload,
    _supplier_official_prepared_prompt_reference_meta,
    _supplier_prompt_join,
    _supplier_prompt_one_line,
    _supplier_prompt_reference_binding,
    _supplier_prompt_reference_name,
    _supplier_prompt_role_label,
    _supplier_prompt_sentence,
    _supplier_shot_labels_from_editor_prompt,
    _video_prompt_and_budget_from_generation_payload,
    _video_prompt_from_generation_payload,
    _video_reference_row_looks_like_voice_asset,
    _video_source_prompt_from_generation_payload,
    _video_voice_style_asset_identity_tokens,
    _video_voice_style_candidate_rows_from_payload,
    _video_voice_style_label_from_row,
    _video_voice_style_match_tokens_from_payload,
    _video_voice_style_provider_line,
    _video_voice_style_rows_from_bound_assets,
    _video_voice_style_tokens_from_value,
    _video_voice_style_value_from_row,
    _vidu_q3_reference_sentence,
)
from .video_provider_references import (
    VISUAL_HANDOFF_REFERENCE_BRIEF,
    _video_inline_reference_files_from_payload,
    _video_official_reference_entries,
    _video_provider_reference_plan,
    _video_reference_ids_from_rows,
    _video_reference_inline_text,
    _video_reference_row_dedupe_identity,
    _video_reference_row_identity_values,
    _video_reference_row_is_direct_asset_reference,
    _video_reference_row_is_input_link,
    _video_reference_row_is_video,
    _video_reference_row_label,
    _video_reference_row_media,
    _video_reference_row_name,
    _video_reference_row_reference_id,
    _video_reference_row_slot,
    _video_reference_rows_from_payload,
    _video_safe_reference_label,
    _video_storyboard_interpretation_contract_from_payload,
    _video_storyboard_visual_id_for_reference,
)

__all__ = (
    '_configured_provider_for_model', '_api_model_name', '_provider_base_url', '_extract_response_text',
    '_extract_anthropic_response_text', '_extract_gemini_response_text', '_post_json',
    '_data_url_base64_payload', '_storage_png_data_url', '_source_image_data_url',
    '_provider_image_data_url_from_file_info', '_openai_compatible_generation_base_url',
    '_call_openai_compatible_style_analysis', '_call_anthropic_style_analysis', '_call_gemini_style_analysis',
    '_normalize_style_analysis_output', '_call_style_analysis_model', '_project_model_config', '_agent_model_runtime_options',
    '_call_openai_compatible_text_model', '_call_anthropic_text_model', '_call_gemini_text_model',
    '_call_text_model', '_configured_media_model', '_provider_reference_image_from_storyboard_version',
    '_extract_storyboard_reference_image', '_provider_reference_image_from_media', '_reference_identity_values',
    '_active_asset_media_candidate', '_provider_reference_image_by_id', '_provider_reference_images_from_ids',
    '_provider_reference_images_from_inline_files',
    '_call_openai_compatible_image_generation',
    '_generate_storyboard_image_media', '_generation_text_value', '_provider_reference_metadata',
    '_video_provider_reference_plan', '_video_source_prompt_from_generation_payload',
    '_video_prompt_from_generation_payload', '_storyboard_video_debug_block_request_log_input',
    '_build_storyboard_video_request', '_generate_storyboard_video_media', '_configured_text_model',
    '_extract_json_payload', '_attached_model_input_images', '_model_json_or_none', '_model_text_or_none'
)
