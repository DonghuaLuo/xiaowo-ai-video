# -*- coding: utf-8 -*-
"""既有 sources API 的直接导出；实现由各业务领域持有。"""
from __future__ import annotations

from .asset_range_planning import commit_asset_range
from .episode_boundary_planning import _ensure_episode_meta_entry
from .project_overview import _PROJECT_OVERVIEW_FIELDS
from .project_overview import _PROJECT_OVERVIEW_TEXT_FIELDS
from .project_overview import _normalize_project_overview_result
from .project_overview import _overview_payload_value
from .project_overview import _project_overview_summary_text
from .project_overview import _sync_project_theme_visual_context
from .project_overview import analyze_project_overview
from .project_overview import update_project_overview
from .project_resource_revisions import _append_resource_revision
from .project_resource_revisions import _apply_json_patch_op
from .project_resource_revisions import _assert_project_json_resource_is_patchable
from .project_resource_revisions import _assert_resource_write_guard
from .project_resource_revisions import _container_for_pointer
from .project_resource_revisions import _json_hash
from .project_resource_revisions import _json_pointer_tokens
from .project_resource_revisions import _payload_first_int
from .project_resource_revisions import _payload_first_present
from .project_resource_revisions import _payload_first_present_from_sources
from .project_resource_revisions import _payload_first_text
from .project_resource_revisions import _project_json_resource_path
from .project_resource_revisions import _resource_revision_value
from .project_resource_revisions import _resource_revisions_path
from .project_resource_revisions import create_resource_revision
from .project_resource_revisions import patch_project_resource
from .source_asset_batches import _ASSET_SPLIT_RECORD_SOURCE_TEXT_LIMIT
from .source_asset_batches import _ASSET_SPLIT_RECORD_SOURCE_TEXT_MAX_LIMIT
from .source_asset_batches import _ASSET_SPLIT_RECORD_TYPES
from .source_asset_batches import _asset_split_append_asset
from .source_asset_batches import _asset_split_asset_id_tokens
from .source_asset_batches import _asset_split_counts
from .source_asset_batches import _asset_split_empty_groups
from .source_asset_batches import _asset_split_int
from .source_asset_batches import _asset_split_merge_asset_groups
from .source_asset_batches import _asset_split_range_ids_for_asset
from .source_asset_batches import _asset_split_record_asset
from .source_asset_batches import _asset_split_source_range_keys_for_asset
from .source_asset_batches import _asset_split_source_rows_by_id
from .source_asset_batches import _asset_split_source_text
from .source_asset_batches import _asset_split_source_text_limit
from .source_asset_batches import get_asset_split_batch_source_text
from .source_asset_batches import list_asset_split_batches
from .source_boundary_contract import ASSET_RANGE_BOUNDARY_STRUCTURED_SCHEMA
from .source_boundary_contract import ASSET_RANGE_BOUNDARY_TEXT_MAX_EFFECTIVE_CHARS
from .source_boundary_contract import ASSET_RANGE_BOUNDARY_TEXT_MIN_EFFECTIVE_CHARS
from .source_boundary_contract import BOUNDARY_TEXT_MAX_EFFECTIVE_CHARS
from .source_boundary_contract import BOUNDARY_TEXT_MIN_EFFECTIVE_CHARS
from .source_boundary_contract import _BOUNDARY_NON_WORD_PATTERN
from .source_boundary_contract import _asset_range_boundary_text_length_issue
from .source_boundary_contract import _asset_range_commit_payload
from .source_boundary_contract import _asset_range_phase_visual_context_items
from .source_boundary_contract import _boundary_match_result
from .source_boundary_contract import _boundary_text_effective_length
from .source_boundary_contract import _boundary_text_length_issue
from .source_boundary_contract import _commit_next_step
from .source_boundary_contract import _compact_text_model_meta
from .source_boundary_contract import _dedupe_boundary_matches
from .source_boundary_contract import _episode_boundary_asset_cursor_end
from .source_boundary_contract import _episode_boundary_commit_payload
from .source_boundary_contract import _episode_boundary_pending_matches_payload
from .source_boundary_contract import _episode_boundary_planning_window_end
from .source_boundary_contract import _episode_boundary_risk_notes
from .source_boundary_contract import _episode_boundary_text_length_issue
from .source_boundary_contract import _episode_boundary_title_context
from .source_boundary_contract import _episode_boundary_title_from_payload
from .source_boundary_contract import _episode_boundary_title_from_text
from .source_boundary_contract import _episode_boundary_tolerance_units
from .source_boundary_contract import _episode_title_from_shot_plan
from .source_boundary_contract import _episode_title_metadata_line
from .source_boundary_contract import _episode_title_rules_payload
from .source_boundary_contract import _find_boundary_text_matches
from .source_boundary_contract import _find_boundary_text_matches_ignoring_punctuation
from .source_boundary_contract import _genre_context_policy_for_stage
from .source_boundary_contract import _locate_source_boundary_text_end
from .source_boundary_contract import _match_source_boundary_text_end
from .source_boundary_contract import _model_request_user_instruction_text
from .source_boundary_contract import _natural_boundary_candidates
from .source_boundary_contract import _next_episode_id
from .source_boundary_contract import _normalize_episode_boundary_title
from .source_boundary_contract import _project_genre_context
from .source_boundary_contract import _range_source_excerpt
from .source_boundary_contract import _source_char_is_boundary_punctuation
from .source_boundary_contract import _source_coverage_commit_guard
from .source_boundary_contract import _strip_boundary_match_text
from .source_boundary_contract import _unwrap_agent_commit_payload
from .source_coverage import _ASSET_RANGE_ANALYSIS_COMPLETED_STATUSES
from .source_coverage import _append_created_asset_ids_to_range
from .source_coverage import _asset_ids_from_payload
from .source_coverage import _asset_range_analysis_completed
from .source_coverage import _asset_range_analysis_state
from .source_coverage import _asset_range_blocked_response
from .source_coverage import _asset_range_bounds
from .source_coverage import _asset_range_created_ids
from .source_coverage import _asset_range_id_tokens
from .source_coverage import _asset_ranges_for_source_ref
from .source_coverage import _blocking_asset_analysis_range
from .source_coverage import _confirmed_asset_range
from .source_coverage import _coverage_target_units
from .source_coverage import _default_source_coverage
from .source_coverage import _episode_asset_coverage_gap
from .source_coverage import _episode_requires_asset_extraction_response
from .source_coverage import _load_source_coverage
from .source_coverage import _normalize_coverage_cursor
from .source_coverage import _normalize_source_coverage
from .source_coverage import _range_cursor_from_rows
from .source_coverage import _refresh_created_asset_ids_for_range
from .source_coverage import _reset_source_planning_state
from .source_coverage import _source_coverage_path
from .source_coverage import _source_ref_bounds
from .source_coverage import _source_refs_from_asset_row
from .source_coverage import _stamp_asset_range_id
from .source_coverage import _sync_source_coverage_targets
from .source_coverage import _validate_asset_batch_refs_in_range
from .source_coverage import _write_source_coverage
from .source_coverage import get_source_coverage
from .source_index import _CHAPTER_HEADING_RE
from .source_index import _SOURCE_INDEX_MAX_UNITS_PER_SOURCE
from .source_index import _SOURCE_INDEX_SCHEMA_VERSION
from .source_index import _SOURCE_INDEX_SENTENCE_MAX_CHARS
from .source_index import _chapter_id_for_offset
from .source_index import _chapter_rows_for_source
from .source_index import _source_index_path
from .source_index import _source_unit_rows_for_source
from .source_index import build_source_index
from .source_index import list_source_index
from .source_index import read_source_window
from .source_text_store import SOURCE_GROUP_NOVEL
from .source_text_store import SOURCE_GROUP_SUPPLEMENTAL
from .source_text_store import _NOVEL_SOURCE_GROUP_ALIASES
from .source_text_store import _SOURCE_TEXT_ENCODINGS
from .source_text_store import _SUPPLEMENTAL_SOURCE_GROUP_ALIASES
from .source_text_store import _assert_segment_text_unchanged
from .source_text_store import _assert_source_text_not_corrupted
from .source_text_store import _compact_text
from .source_text_store import _decode_source_text_bytes
from .source_text_store import _ensure_initial_source_segment
from .source_text_store import _ensure_source_total_text_state
from .source_text_store import _episode_source_display_title
from .source_text_store import _episode_source_ref_path
from .source_text_store import _episode_source_rows
from .source_text_store import _episode_source_status
from .source_text_store import _episode_source_text_path
from .source_text_store import _find_source_record
from .source_text_store import _is_novel_source
from .source_text_store import _latest_source_with_runtime_status
from .source_text_store import _project_source_text
from .source_text_store import _read_episode_source_text
from .source_text_store import _read_source_content
from .source_text_store import _read_source_total_backup
from .source_text_store import _rebaseline_source_segments_for_content
from .source_text_store import _rebaseline_source_total_from_consistent_backup
from .source_text_store import _restore_source_total_text_from_backup
from .source_text_store import _safe_source_content_path
from .source_text_store import _segment_bounds
from .source_text_store import _select_project_sources
from .source_text_store import _sha256_text
from .source_text_store import _source_append_segments
from .source_text_store import _source_collection_text
from .source_text_store import _source_collection_title
from .source_text_store import _source_content_path
from .source_text_store import _source_filename_extension
from .source_text_store import _source_filename_stem
from .source_text_store import _source_group
from .source_text_store import _source_line_count
from .source_text_store import _source_payload_content
from .source_text_store import _source_payload_label
from .source_text_store import _source_recorded_total_hash
from .source_text_store import _source_refs_for_meta
from .source_text_store import _source_segment_from_text
from .source_text_store import _source_segment_line_range
from .source_text_store import _source_storage_path
from .source_text_store import _source_text_corruption_reason
from .source_text_store import _source_text_hash
from .source_text_store import _source_text_result
from .source_text_store import _source_total_backup_path
from .source_text_store import _source_total_hash_status
from .source_text_store import _source_with_runtime_status
from .source_text_store import _write_source_total_backup
from .source_text_store import append_novel_source_files
from .source_text_store import create_source
from .source_text_store import delete_source_segment
from .source_text_store import get_episode_source_text
from .source_text_store import get_source_text
from .source_text_store import list_sources
from .source_text_store import open_episode_source_file_location
from .source_text_store import open_source_file_location
from .source_text_store import replace_sources
from .source_text_store import restore_source_total_snapshot
from .source_text_store import save_episode_source_text
from .source_text_store import save_source_text

__all__ = (
    'list_sources', 'get_source_text', 'save_source_text',
    'append_novel_source_files', 'delete_source_segment',
    'restore_source_total_snapshot', 'SOURCE_GROUP_NOVEL',
    'SOURCE_GROUP_SUPPLEMENTAL', '_source_group', '_is_novel_source',
    '_source_refs_for_meta', '_CHAPTER_HEADING_RE',
    '_source_content_path', '_safe_source_content_path', '_read_source_content',
    '_source_index_path', '_source_coverage_path', '_sha256_text',
    '_chapter_rows_for_source', '_chapter_id_for_offset', '_source_unit_rows_for_source', 'build_source_index',
    'list_source_index', 'read_source_window', '_coverage_target_units', '_default_source_coverage',
    '_normalize_coverage_cursor', '_normalize_source_coverage', '_load_source_coverage',
    '_write_source_coverage', '_sync_source_coverage_targets', '_reset_source_planning_state',
    '_episode_source_ref_path', '_episode_source_text_path', '_read_episode_source_text',
    '_episode_source_status', '_episode_source_rows', 'get_episode_source_text',
    'save_episode_source_text', 'get_source_coverage', 'list_asset_split_batches',
    'get_asset_split_batch_source_text', 'open_source_file_location',
    'open_episode_source_file_location',
    '_next_episode_id', '_natural_boundary_candidates', '_range_source_excerpt',
    '_source_coverage_commit_guard', '_commit_next_step', '_episode_boundary_commit_payload',
    '_asset_range_commit_payload', '_unwrap_agent_commit_payload',
    '_ensure_episode_meta_entry', 'commit_asset_range',
    '_confirmed_asset_range', '_source_refs_from_asset_row', '_source_ref_bounds',
    '_validate_asset_batch_refs_in_range', '_stamp_asset_range_id', '_asset_ids_from_payload',
    '_append_created_asset_ids_to_range', '_refresh_created_asset_ids_for_range', '_asset_ranges_for_source_ref', '_json_hash', '_resource_revision_value',
    '_assert_resource_write_guard', '_project_json_resource_path', '_assert_project_json_resource_is_patchable',
    '_resource_revisions_path', '_append_resource_revision', '_json_pointer_tokens', '_container_for_pointer',
    '_apply_json_patch_op', 'create_resource_revision', 'patch_project_resource', '_select_project_sources',
    '_source_collection_title', '_source_collection_text', 'create_source', 'replace_sources',
    'analyze_project_overview', 'update_project_overview', '_project_source_text', '_compact_text'
)
