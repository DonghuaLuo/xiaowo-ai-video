# -*- coding: utf-8 -*-
"""工作流领域实际实现。"""
from __future__ import annotations
from .canvas_ownership import VIDEO_TASK_NODE_TYPES
from utils.video_prompt_mentions import canonicalize_editor_mentions, prompt_reference_labels, resolve_prompt_mentions

from .canvas_ownership import validate_node_identity_update
from .canvas_store_database import validate_canvas_revision_v4
from .canvas_store_mutations import write_canvas_card_records_v4
from .canvas_store_mutations import write_canvas_records_v4
from .canvas_store_queries import read_canvas_card_record_v4
from .canvas_store_queries import read_workflow_card_neighborhood_v4
from .director_plan_contract import (
    director_plan_bound_asset_ids_for_work_chain,
    director_plan_bound_speaker_asset_ids_for_work_chain,
)
from .director_plan_contract import _director_plan_normalized_content
from .director_plan_contract import _director_plan_reference_duration_sum
from .director_plan_contract import _normalize_multiline_text
from .generation_config import _video_task_card_target_model_context
from .media_files import video_media_metadata
from .planning_contract import _is_user_locked_item
from .asset_reference_scope import _validate_workflow_asset_refs
from .projects import _touch_project_meta
from .source_text_store import _compact_text
from .source_text_store import save_episode_source_text
from .storyboard_timing import validate_shot_timing
from .store_core import _JSON_WRITE_LOCK
from .store_core import _deep_merge
from .store_core import _now
from .video_task_card_references import video_task_card_current_reference_snapshot
from .workflow_canvas_updates import _assert_split_asset_rename_fields_unchanged
from .workflow_contract import _assert_canvas_mutation_does_not_return_workflow
from .workflow_contract import _assert_new_workflow_node_type_allowed
from .workflow_contract import _canonical_workflow_slot
from .workflow_contract import _ensure_saved_workflow_contract
from .workflow_contract import _ensure_saved_workflow_edge_contract
from .workflow_contract import _ensure_saved_workflow_node_contract
from .workflow_contract import _merge_generation_config_patch
from .workflow_contract import _workflow_mutation_event_fields
from .workflow_contract import _workflow_node
from .workflow_contract import _workflow_node_media_kind
from .workflow_contract import _workflow_node_owns_generation_config
from .workflow_contract import _workflow_node_type_value
from .workflow_edit_history import _NODE_EDIT_HISTORY_DURATION_KEYS
from .workflow_edit_history import _node_edit_director_text_content
from .workflow_edit_history import _node_edit_generation_config_content
from .workflow_edit_history import _node_edit_history_save_reason_allowed
from .workflow_edit_history import _node_edit_storyboard_template_content
from .workflow_edit_history import _node_edit_storyboard_text_content
from .workflow_edit_history import _read_node_edit_history
from .workflow_edit_history import _sanitize_node_edit_history_item
from .workflow_edit_history import record_workflow_node_edit_history
from .workflow_edit_history import record_video_prompt_edit_history
from .workflow_edit_history import _node_edit_content_from_node
from .workflow_input_resolution import _resolve_workflow_node_inputs_from_workflow
from .workflow_input_resolution import workflow_reference_video_input_links
from .workflow_projection import _workflow_cards_mutation_write
from .workflow_projection import get_canvas_workflow_projection
from typing import Any
from utils.video_references import VIDEO_REFERENCE_SLOT
from utils.video_references import validate_reference_video_durations
import copy
import math
import traceback


def _inline_edit_requires_workflow_validation(data_patch: dict[str, Any]) -> bool:
    if not isinstance(data_patch, dict) or not data_patch:
        return False
    return any(key in data_patch for key in ("inputLinks", "input_links"))


def _inline_text_value(value: Any) -> str:
    return str(value or "").strip() if value is not None else ""


def _inline_first_text(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _inline_first_submitted_text(mapping: dict[str, Any], *keys: str) -> tuple[bool, str]:
    found = False
    for key in keys:
        if key not in mapping:
            continue
        found = True
        text = _inline_text_value(mapping.get(key))
        if text:
            return True, text
    return found, ""


def _inline_join_append(base: str, addition: str) -> str:
    base = _inline_text_value(base)
    addition = _inline_text_value(addition)
    if not addition:
        return base
    if not base:
        return addition
    if addition in base:
        return base
    return f"{base}\n\n{addition}"


_DIRECTOR_INLINE_PLAN_TEXT_KEYS = ("directorPlan",)




def _inline_first_present_text(mapping: dict[str, Any], *keys: str) -> tuple[str, bool]:
    if not isinstance(mapping, dict):
        return "", False
    for key in keys:
        if key in mapping:
            return str(mapping.get(key) or "").strip(), True
    return "", False


def _workflow_inline_director_card_dict(mapping: dict[str, Any]) -> dict[str, Any]:
    if isinstance(mapping.get("directorTaskCard"), dict):
        return copy.deepcopy(mapping.get("directorTaskCard"))
    return {}


def _workflow_inline_prompt_dict(mapping: dict[str, Any]) -> dict[str, Any]:
    prompt = mapping.get("prompt")
    return copy.deepcopy(prompt) if isinstance(prompt, dict) else {}


def _workflow_inline_result_card_edit_allowed(
    node_type: str,
    data_patch: dict[str, Any],
    save_reason: str,
) -> bool:
    normalized_node_type = str(node_type or "").strip()
    if normalized_node_type not in {"storyboard.image", "video.result"}:
        return True
    if str(save_reason or "").strip() != "result_frame_slot_set":
        return False
    allowed_keys = {"eyebrow", "nodeType", "node_type", "frameSlot", "frame_slot"}
    return all(str(key or "").strip() in allowed_keys for key in data_patch.keys())


def _workflow_inline_existing_story_text(node_data: dict[str, Any]) -> str:
    prompt = node_data.get("prompt") if isinstance(node_data.get("prompt"), dict) else {}
    return _inline_first_text(
        node_data,
        "cinematicStoryText",
        "cinematic_story_text",
    ) or _inline_first_text(
        prompt,
        "cinematicStoryText",
        "cinematic_story_text",
    )


def _normalize_workflow_inline_data_patch(
    data_patch: dict[str, Any],
    node_data: dict[str, Any],
    node_type: str,
    *,
    project_id: str = "",
    speaker_asset_ids: set[str] | None = None,
    allowed_asset_ids: dict[str, set[str]] | None = None,
    preserve_generated_normal_estimates: bool = False,
) -> dict[str, Any]:
    patch = copy.deepcopy(data_patch)
    prompt_patch = _workflow_inline_prompt_dict(patch)
    normalized_node_type = str(node_type or "").strip()
    if normalized_node_type in VIDEO_TASK_NODE_TYPES:
        card_patch = patch.get("videoTaskCard") if isinstance(patch.get("videoTaskCard"), dict) else {}
        if "soundPrompt" in card_patch and not isinstance(card_patch["soundPrompt"], str):
            raise ValueError("声音提示词必须是文本")
        if "soundPrompt" in card_patch:
            card_patch["soundPrompt"] = canonicalize_editor_mentions(card_patch["soundPrompt"])
        if "voiceOverrides" in card_patch:
            from .video_reference_audio import normalize_video_task_voice_overrides
            card_patch["voiceOverrides"] = normalize_video_task_voice_overrides(project_id, card_patch["voiceOverrides"])
        direct_text_submitted, direct_text = _inline_first_submitted_text(
            card_patch,
            "finalVideoPrompt",
        )
        patch.pop("prompt", None)
        patch.pop("videoPrompt", None)
        patch.pop("videoPromptRaw", None)
        if direct_text_submitted or "soundPrompt" in card_patch:
            existing_card = node_data.get("videoTaskCard")
            next_card = copy.deepcopy(existing_card) if isinstance(existing_card, dict) else {}
            if not direct_text_submitted:
                direct_text = str(next_card.get("finalVideoPrompt") or (node_data.get("prompt") or {}).get("videoPrompt") or "")
            saved_video_prompt = canonicalize_editor_mentions(direct_text)
            previous_video_prompt = next_card.get("finalVideoPrompt")
            next_card.update(copy.deepcopy(card_patch))
            next_card.setdefault("soundPrompt", "")
            if (previous_video_prompt != saved_video_prompt
                    and "shotPromptPlan" not in card_patch):
                # A manual rewrite makes the previous structured shot plan stale.
                # Use an explicit null so the deep merge also clears the stored plan.
                next_card["shotPromptPlan"] = None
            bindings = next_card.get("promptBindings") or {}
            if not isinstance(bindings, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in bindings.items()):
                raise ValueError("视频提示词的资产引用绑定无效")
            next_card["promptBindings"] = {name: bindings.get(name, "") for name in
                                          prompt_reference_labels(saved_video_prompt, next_card["soundPrompt"])}
            generation_config = node_data.get("generationConfig") if isinstance(node_data.get("generationConfig"), dict) else {}
            model_id = str(
                generation_config.get("modelId")
                or next_card.get("modelId")
                or ""
            ).strip()
            next_card.update(
                {
                    "source": "manual_final_provider_prompt",
                    "promptKind": "final_provider_prompt",
                    "videoPromptKind": "final_provider_prompt",
                    "finalVideoPrompt": saved_video_prompt,
                    "manualEdited": True,
                    "dynamicPrompt": False,
                    "updatedAt": _now(),
                }
            )
            if model_id:
                next_card["modelId"] = model_id
            patch["videoTaskCard"] = next_card
            existing_prompt = node_data.get("prompt") if isinstance(node_data.get("prompt"), dict) else {}
            patch["prompt"] = {
                **copy.deepcopy(existing_prompt),
                "videoPrompt": saved_video_prompt,
            }
            patch["summary"] = _compact_text(saved_video_prompt, 180)
    elif normalized_node_type == "prompt.storyboard":
        card_patch = patch.get("storyboardTaskCard") if isinstance(patch.get("storyboardTaskCard"), dict) else {}
        for source in (patch, prompt_patch, card_patch):
            if "narrativeMode" in source and source["narrativeMode"] != "drama":
                raise ValueError("旁白讲述模式尚未开放")
        script_instruction, script_instruction_present = _inline_first_present_text(
            patch,
            *_WORKFLOW_SCRIPT_USER_INSTRUCTION_KEYS,
        )
        if not script_instruction_present:
            script_instruction, script_instruction_present = _inline_first_present_text(
                prompt_patch,
                *_WORKFLOW_SCRIPT_USER_INSTRUCTION_KEYS,
            )
        if not script_instruction_present:
            script_instruction, script_instruction_present = _inline_first_present_text(
                card_patch,
                *_WORKFLOW_SCRIPT_USER_INSTRUCTION_KEYS,
            )
        if script_instruction_present:
            for target in (patch, prompt_patch, card_patch):
                target["scriptUserInstruction"] = script_instruction
                target["script_user_instruction"] = script_instruction
            patch["storyboardTaskCard"] = card_patch
        append_text = _inline_first_text(
            patch,
            "cinematicStoryTextAppend",
            "cinematic_story_text_append",
            "appendCinematicStoryText",
            "append_cinematic_story_text",
        ) or _inline_first_text(prompt_patch, "cinematicStoryTextAppend", "cinematic_story_text_append")
        for key in (
            "cinematicStoryTextAppend",
            "cinematic_story_text_append",
            "appendCinematicStoryText",
            "append_cinematic_story_text",
            "storyTextAppend",
            "story_text_append",
            "appendStoryText",
            "append_story_text",
        ):
            patch.pop(key, None)
        for key in (
            "cinematicStoryTextAppend",
            "cinematic_story_text_append",
            "appendCinematicStoryText",
            "append_cinematic_story_text",
            "storyTextAppend",
            "story_text_append",
            "appendStoryText",
            "append_story_text",
        ):
            prompt_patch.pop(key, None)
        direct_text, direct_text_present = _inline_first_present_text(patch, "cinematicStoryText")
        if not direct_text_present:
            direct_text, direct_text_present = _inline_first_present_text(prompt_patch, "cinematicStoryText")
        for key in ("storyText", "story_text", "content"):
            patch.pop(key, None)
            prompt_patch.pop(key, None)
        if append_text and not direct_text:
            direct_text = _inline_join_append(
                _workflow_inline_existing_story_text(node_data),
                append_text,
            )
        if direct_text_present or direct_text:
            patch["cinematicStoryText"] = direct_text
            prompt_patch["cinematicStoryText"] = direct_text
        if prompt_patch:
            patch["prompt"] = prompt_patch
    elif normalized_node_type == "director.board":
        if "directorRuleSelectionMode" in patch:
            if patch["directorRuleSelectionMode"] not in {"auto", "manual"}:
                raise ValueError("导演规则选择模式无效")
            if (patch["directorRuleSelectionMode"] == "manual"
                    and not str(patch.get("directorRuleId") or node_data.get("directorRuleId") or "").strip()):
                raise ValueError("手动选择导演规则时必须指定规则")
        card_patch = _workflow_inline_director_card_dict(patch)
        sources = (patch, prompt_patch, card_patch)
        direct_text = ""
        direct_text_explicit = False
        for source in sources:
            direct_text, direct_text_explicit = _inline_first_present_text(source, *_DIRECTOR_INLINE_PLAN_TEXT_KEYS)
            if direct_text_explicit:
                break
        structured_shots: Any = None
        structured_shots_explicit = False
        for source in sources:
            if "directorPlanShots" in source:
                structured_shots_explicit = True
                structured_shots = source["directorPlanShots"]
                if not isinstance(structured_shots, list):
                    raise ValueError("分镜脚本的 directorPlanShots 必须是数组")
                break
        speaker_roster_patch: list[dict[str, Any]] = []
        speaker_roster_present = False
        for source in sources:
            if "speakerRoster" in source:
                speaker_roster_present = True
                if not isinstance(source["speakerRoster"], list):
                    raise ValueError("分镜脚本的临时说话者名单必须是数组")
                speaker_roster_patch = copy.deepcopy(source["speakerRoster"])
                break
        if direct_text and not structured_shots_explicit:
            raise ValueError("分镜脚本保存必须包含结构化 directorPlanShots，不能从文本反向解析镜头。")
        if direct_text and structured_shots_explicit and not structured_shots:
            raise ValueError("清空导演镜头时不能同时保存非空分镜脚本正文")
        plan_changed = structured_shots_explicit or direct_text_explicit
        if plan_changed or speaker_roster_present:
            if not structured_shots_explicit:
                structured_shots = [] if direct_text_explicit else node_data.get("directorPlanShots") or []
            if structured_shots_explicit and not preserve_generated_normal_estimates:
                previous_by_number = {
                    shot.get("shotNo"): shot for shot in node_data.get("directorPlanShots") or []
                    if isinstance(shot, dict)
                }
                for shot in structured_shots:
                    if not isinstance(shot, dict) or "normalDurationSec" not in shot:
                        continue
                    previous = previous_by_number.get(shot.get("shotNo"))
                    timing_fields = ("durationSec", "videoExecution", "nonOverlappingBeats", "soundEvents")
                    if (not isinstance(previous, dict)
                            or shot["normalDurationSec"] != previous.get("normalDurationSec")
                            or any(shot.get(field) != previous.get(field) for field in timing_fields)):
                        shot.pop("normalDurationSec", None)
            clearing_plan = plan_changed and not structured_shots
            speaker_roster = (
                speaker_roster_patch if speaker_roster_present
                else [] if clearing_plan
                else copy.deepcopy(node_data.get("speakerRoster") or [])
            )
            normalized_content = _director_plan_normalized_content(
                structured_shots, speaker_roster, speaker_asset_ids=speaker_asset_ids,
                allowed_asset_ids=allowed_asset_ids, allow_empty=True,
            )
            director_plan_shots = normalized_content["directorPlanShots"]
            if plan_changed and director_plan_shots:
                validate_shot_timing(director_plan_shots, 1.0)
                normalized_content["durationSeconds"] = _director_plan_reference_duration_sum(director_plan_shots)
            task_card_patch = copy.deepcopy(node_data.get("directorTaskCard") or {})
            task_card_patch.update(copy.deepcopy(card_patch))
            for target in (patch, prompt_patch, task_card_patch):
                target.update(copy.deepcopy(normalized_content))
            task_card_patch["state"] = "ready" if director_plan_shots else "pending_director_plan"
            patch["directorTaskCard"] = task_card_patch
            patch["prompt"] = prompt_patch
            patch["status"] = "ready" if director_plan_shots else "draft"
            patch["summary"] = _compact_text(normalized_content["directorPlan"], 160)
    return patch


def _cleanup_workflow_inline_existing_prompt_patch_fields(
    node_data: dict[str, Any],
    node_type: str,
) -> None:
    normalized_node_type = str(node_type or "").strip()
    prompt = node_data.get("prompt")
    if not isinstance(prompt, dict):
        return
    if normalized_node_type in VIDEO_TASK_NODE_TYPES:
        return
    elif normalized_node_type in {"prompt.storyboard", "director.board"}:
        if normalized_node_type == "prompt.storyboard":
            for key in (
                "cinematicStoryTextAppend",
                "cinematic_story_text_append",
                "appendCinematicStoryText",
                "append_cinematic_story_text",
                "storyTextAppend",
                "story_text_append",
                "appendStoryText",
                "append_story_text",
            ):
                prompt.pop(key, None)


_WORKFLOW_SCRIPT_OBSOLETE_PLANNING_KEYS = (
    "durationSeconds",
    "duration_seconds",
    "storyboardAnalysis",
    "storyboard_analysis",
    "storyboardAnalysisStoryTextHash",
    "storyboard_analysis_story_text_hash",
    "storyboardPlanHash",
    "storyboard_plan_hash",
    "storyboardPlanState",
    "storyboard_plan_state",
    "storyboardPlanStateReason",
    "storyboard_plan_state_reason",
    "visualBeats",
    "visual_beats",
    "panels",
    "shots",
    "shotIds",
    "shot_ids",
    "shotCount",
    "shot_count",
    "shotTimingPlan",
    "shot_timing_plan",
)


_WORKFLOW_SCRIPT_USER_INSTRUCTION_KEYS = ("scriptUserInstruction", "script_user_instruction")


def _workflow_sync_script_user_instruction_fields(mapping: dict[str, Any] | None) -> None:
    if not isinstance(mapping, dict):
        return
    found = False
    text = ""
    for key in _WORKFLOW_SCRIPT_USER_INSTRUCTION_KEYS:
        if key not in mapping:
            continue
        found = True
        candidate = _normalize_multiline_text(mapping.get(key))
        if candidate:
            text = candidate
            break
    if not found:
        return
    if text:
        mapping["scriptUserInstruction"] = text
        mapping["script_user_instruction"] = text
        return
    for key in _WORKFLOW_SCRIPT_USER_INSTRUCTION_KEYS:
        mapping.pop(key, None)


def _workflow_clean_script_user_instruction_fields(mapping: dict[str, Any] | None) -> None:
    if not isinstance(mapping, dict):
        return
    _workflow_sync_script_user_instruction_fields(mapping)
    for nested_key in ("prompt", "storyboardTaskCard", "storyboard_task_card"):
        nested = mapping.get(nested_key)
        if isinstance(nested, dict):
            _workflow_clean_script_user_instruction_fields(nested)


def _workflow_clear_script_obsolete_planning_fields(mapping: dict[str, Any] | None) -> None:
    if not isinstance(mapping, dict):
        return
    for key in _WORKFLOW_SCRIPT_OBSOLETE_PLANNING_KEYS:
        mapping.pop(key, None)
    for nested_key in ("prompt", "storyboardTaskCard", "storyboard_task_card", "videoTaskCard", "video_task_card"):
        nested = mapping.get(nested_key)
        if isinstance(nested, dict):
            _workflow_clear_script_obsolete_planning_fields(nested)




class _CanvasHistoryRestore:
    """一次操作独立持有业务状态，按验证、准备和提交阶段执行。"""

    def __init__(self, project_id, episode_id, payload):
        self.project_id = project_id
        self.episode_id = episode_id
        self.payload = payload

    def run(self) -> dict[str, Any] | None:
        result = self._load_history_version()
        if result is not None:
            return result
        if self.node_type in VIDEO_TASK_NODE_TYPES:
            return self._restore_video_prompt()
        self._prepare_card()
        self._restore_card_content()
        if self.node_type == "director.board" and getattr(self, "needs_allocation", False):
            return self._commit_director_restore()
        self._validate_and_commit()
        return self._respond()

    def _commit_director_restore(self) -> dict[str, Any]:
        from .storyboard_allocation import apply_storyboard_allocation, default_storyboard_groups

        _ensure_saved_workflow_contract(self.workflow)
        blocking, _warnings = _validate_workflow_asset_refs(self.project_id, self.episode_id, self.workflow)
        if blocking:
            raise ValueError("；".join(blocking))
        groups = default_storyboard_groups(self.data.get("directorPlanShots") or [], self.previous_allocation)
        if not groups:
            shots = self.data.get("directorPlanShots") or []
            if shots and shots[0].get("entryBoundaryKind") == "direct_continuation":
                from .storyboard_allocation import require_direct_continuation_previous_group

                chain_id = str(self.node.get("workChainId") or self.data.get("workChainId") or "")
                require_direct_continuation_previous_group(self.project_id, self.episode_id, chain_id)
            self.data["status"] = "draft"
            self.data.setdefault("directorTaskCard", {})["state"] = (
                "pending_allocation" if shots else "pending_director_plan"
            )
            self._validate_and_commit()
            saved = self._respond()
            saved["allocationNeedsSave"] = bool(shots)
            saved["message"] = ("历史分镜已恢复为草稿，需重新分组后才能制作。"
                                if shots else "历史分镜已恢复为空草稿。")
            return saved
        result = apply_storyboard_allocation(
            self.project_id, self.episode_id,
            {"directorNodeId": self.node_id, "expectedShots": self.previous_director_shots,
             "groups": groups, "invalidateGenerated": True,
             "expectedWorkflowVersion": self.workflow["version"]},
            director_replacement_data=self.data,
        )
        return {
            **result, "nodeId": self.node_id, "nodeType": self.node_type,
            "version": self.item, "structureChanged": result.get("structureChanged", True),
            "focusTarget": {"section": "episode", "episodeId": self.episode_id, "nodeId": self.node_id},
        }

    def _load_history_version(self):
        self.payload = self.payload if isinstance(self.payload, dict) else {}
        version_id = str(self.payload.get("versionId") or self.payload.get("version_id") or self.payload.get("id") or "").strip()
        self.node_id = str(self.payload.get("nodeId") or self.payload.get("node_id") or "").strip()
        if not version_id:
            raise ValueError("缺少 versionId")
        items = _read_node_edit_history(self.project_id, self.episode_id, self.node_id)
        self.item = next(
            (
                row
                for row in items
                if isinstance(row, dict)
                and str(row.get("id") or "") == version_id
                and (not self.node_id or str(row.get("nodeId") or "") == self.node_id)
            ),
            None,
        )
        if not self.item:
            raise FileNotFoundError("修改记录不存在")
        self.item = _sanitize_node_edit_history_item(self.item)
        if self.item is None:
            raise ValueError("修改记录格式不正确")
        self.node_id = str(self.item.get("nodeId") or self.node_id).strip()
        self.node_type = str(self.item.get("nodeType") or "").strip()
        restore_patch = self.item.get("restorePatch") if isinstance(self.item.get("restorePatch"), dict) else {}
        data_patch = restore_patch.get("data") if isinstance(restore_patch.get("data"), dict) else {}
        self.generation_config_content = _node_edit_generation_config_content(
            restore_patch.get("generationConfig")
        )
        if not data_patch and not self.generation_config_content:
            raise ValueError("修改记录缺少恢复补丁")
        self.content = copy.deepcopy(data_patch)
        if self.generation_config_content:
            self.content["generationConfig"] = self.generation_config_content
        if self.node_type == "source.text":
            node = read_canvas_card_record_v4(self.project_id, self.episode_id, self.node_id, detail="full")
            if (node.get("data") or {}).get("sourceMode") == "independent":
                result = save_workflow_node_inline_edit(self.project_id, self.episode_id, {
                    "nodeId": self.node_id,
                    "data": {"sourceText": str(self.content.get("sourceText") or ""), "summary": ""},
                    "expectedRevision": self.payload.get("expectedRevision", self.payload.get("expected_revision")),
                    "reason": "node_edit_history_restored",
                    "source": "restore",
                })
                if result.get("skippedLocked"):
                    raise ValueError("节点已锁定，未恢复独立原文")
                return {**result, "nodeType": self.node_type, "version": self.item}
            detail = save_episode_source_text(
                self.project_id,
                self.episode_id,
                str(self.content.get("sourceText") or ""),
                title=str(self.item.get("title") or ""),
                reason="node_edit_history_restored",
            )
            return {
                "success": True,
                "episodeId": self.episode_id,
                "nodeId": self.node_id,
                "nodeType": self.node_type,
                "version": self.item,
                "sourceText": detail,
                "changedResources": ["episodeSource"],
                "projectChanged": True,
            }

    def _restore_video_prompt(self):
        current = read_canvas_card_record_v4(self.project_id, self.episode_id, self.node_id, detail="full")
        if current.get("type") != self.node_type:
            raise ValueError("修改记录与当前视频卡类型不一致")
        current_card = (current.get("data") or {}).get("videoTaskCard") or {}
        current_overrides = current_card.get("voiceOverrides") or {}
        card_content = {
            "finalVideoPrompt": self.content["finalVideoPrompt"],
            "soundPrompt": self.content["soundPrompt"],
            "promptBindings": copy.deepcopy(self.content["promptBindings"]),
            "durationSeconds": self.content["durationSeconds"],
            "voiceOverrides": {**{key: None for key in current_overrides}, **(self.content.get("voiceOverrides") or {})},
            "usedSpeakerIds": copy.deepcopy(self.content["usedSpeakerIds"]),
            "voiceDesign": copy.deepcopy(self.content["voiceDesign"]),
            "assetNameMap": {**copy.deepcopy(current_card.get("assetNameMap") or {}), **copy.deepcopy(self.content["assetNameMap"])},
        }
        data_patch = {"videoTaskCard": card_content, "durationSeconds": self.content["durationSeconds"]}
        result = save_workflow_node_inline_edit(self.project_id, self.episode_id, {
            "nodeId": self.node_id,
            "data": data_patch,
            "generationConfig": self.generation_config_content,
            "expectedRevision": self.payload.get("expectedRevision", self.payload.get("expected_revision")),
            "source": "restore",
            "reason": "node_edit_history_restored",
        })
        if result.get("skippedLocked"):
            raise ValueError("节点已锁定，未恢复提示词")
        return {**result, "nodeType": self.node_type, "version": self.item}

    def _prepare_card(self):
        self.workflow = get_canvas_workflow_projection(self.project_id, self.episode_id)
        validate_canvas_revision_v4(self.workflow["version"], self.payload.get("expectedRevision", self.payload.get("expected_revision")))
        self.node = _workflow_node(self.workflow, self.node_id)
        if not self.node:
            raise FileNotFoundError("节点不存在")
        self.data = self.node.setdefault("data", {})
        if not isinstance(self.data, dict):
            self.data = {}
            self.node["data"] = self.data
        self.previous_director_shots = copy.deepcopy(self.data.get("directorPlanShots") or [])
        self.previous_speaker_roster = copy.deepcopy(self.data.get("speakerRoster") or [])
        self.previous_allocation = copy.deepcopy(self.data.get("storyboardAllocation")) if isinstance(self.data.get("storyboardAllocation"), dict) else {}
        template_content = _node_edit_storyboard_template_content(self.content)
        if template_content:
            for key, value in template_content.items():
                self.data[key] = copy.deepcopy(value)
            self.card_state = self.data.get("cardState") if isinstance(self.data.get("cardState"), dict) else {}
            if "storyboardTemplate" in template_content:
                self.card_state["template"] = copy.deepcopy(template_content.get("storyboardTemplate"))
            if "storyboardTemplateLabel" in template_content:
                self.card_state["templateLabel"] = copy.deepcopy(template_content.get("storyboardTemplateLabel"))
            self.data["cardState"] = self.card_state
        for key in ("prompt", "prompts"):
            if key in self.content:
                self.data[key] = copy.deepcopy(self.content.get(key))
        for key in _NODE_EDIT_HISTORY_DURATION_KEYS:
            if key in self.content:
                self.data[key] = copy.deepcopy(self.content.get(key))
        self.generation_config_content = _node_edit_generation_config_content(self.content.get("generationConfig"))
        if self.generation_config_content:
            current_config = self.data.get("generationConfig")
            if not isinstance(current_config, dict):
                current_config = {}
            self.data["generationConfig"] = _merge_generation_config_patch(current_config, self.generation_config_content)

    def _restore_card_content(self):
        direct_storyboard_text_content = _node_edit_storyboard_text_content(self.content)
        if direct_storyboard_text_content:
            prompt = self.data.get("prompt") if isinstance(self.data.get("prompt"), dict) else {}
            prompt = copy.deepcopy(prompt)
            task_card = self.data.get("storyboardTaskCard") if isinstance(self.data.get("storyboardTaskCard"), dict) else {}
            task_card = copy.deepcopy(task_card)
            for key, value in direct_storyboard_text_content.items():
                self.data[key] = copy.deepcopy(value)
                if key in {"scriptTemplateId", "scriptTemplateLabel"}:
                    continue
                snake_key = {
                    "sourceFactText": "source_fact_text",
                    "cinematicStoryText": "cinematic_story_text",
                    "scriptUserInstruction": "script_user_instruction",
                }.get(key, "")
                prompt[key] = copy.deepcopy(value)
                task_card[key] = copy.deepcopy(value)
                if snake_key:
                    self.data[snake_key] = copy.deepcopy(value)
                    prompt[snake_key] = copy.deepcopy(value)
                    task_card[snake_key] = copy.deepcopy(value)
            self.data["prompt"] = prompt
            self.data["storyboardTaskCard"] = task_card
        direct_director_text_content = _node_edit_director_text_content(self.content) if self.node_type == "director.board" else {}
        if direct_director_text_content:
            restored_shots = direct_director_text_content["directorPlanShots"]
            # Validate against current asset bindings without rewriting the saved snapshot.
            _director_plan_normalized_content(
                restored_shots,
                direct_director_text_content["speakerRoster"],
                speaker_asset_ids=director_plan_bound_speaker_asset_ids_for_work_chain(
                    self.project_id, self.workflow, self.episode_id, self.node_id,
                ),
                allowed_asset_ids=director_plan_bound_asset_ids_for_work_chain(
                    self.project_id, self.workflow, self.episode_id, self.node_id,
                ),
                allow_empty=True,
            )
            prompt = self.data.get("prompt") if isinstance(self.data.get("prompt"), dict) else {}
            prompt = copy.deepcopy(prompt)
            task_card = self.data.get("directorTaskCard") if isinstance(self.data.get("directorTaskCard"), dict) else {}
            task_card = copy.deepcopy(task_card)
            for key, value in direct_director_text_content.items():
                self.data[key] = copy.deepcopy(value)
                prompt[key] = copy.deepcopy(value)
                task_card[key] = copy.deepcopy(value)
            self.data["prompt"] = prompt
            self.data["directorTaskCard"] = task_card
            shots = restored_shots
            self.data["status"] = "ready" if shots else "draft"
            self.data["summary"] = _compact_text(self.data.get("directorPlan"), 160)
            task_card["state"] = "ready" if shots else "pending_director_plan"
            if "durationSeconds" in direct_director_text_content:
                card_state = copy.deepcopy(self.data.get("cardState")) if isinstance(self.data.get("cardState"), dict) else {}
                card_state["durationSeconds"] = copy.deepcopy(direct_director_text_content["durationSeconds"])
                self.data["cardState"] = card_state
            self.needs_allocation = (
                restored_shots != self.previous_director_shots
                or direct_director_text_content["speakerRoster"] != self.previous_speaker_roster
            )
            if self.needs_allocation:
                self.data["storyboardAllocation"] = {
                    "schemaVersion": 1, "directorPlanHash": "",
                    "groups": copy.deepcopy(self.previous_allocation.get("groups") or []) if restored_shots else [],
                }

    def _validate_and_commit(self):
        _ensure_saved_workflow_contract(self.workflow)
        asset_ref_blocking, self.asset_ref_warnings = _validate_workflow_asset_refs(self.project_id, self.episode_id, self.workflow)
        if asset_ref_blocking:
            raise ValueError("；".join(asset_ref_blocking))
        save_result = _workflow_cards_mutation_write(
            self.project_id, self.episode_id, [copy.deepcopy(self.node)], expected_revision=self.workflow["version"],
        )
        self.workflow["version"] = save_result.get("workflowVersion") or self.workflow.get("version")
        self.mutation_fields = _workflow_mutation_event_fields(
            save_result,
            ["canvas_node", "node_edit_history"],
        )

    def _respond(self):
        result = {
            "success": True,
            "episodeId": self.episode_id,
            "nodeId": self.node_id,
            "nodeType": self.node_type,
            "version": self.item,
            "node": copy.deepcopy(self.node),
            "workflowVersion": self.workflow.get("version"),
            **self.mutation_fields,
            "focusTarget": {"section": "episode", "episodeId": self.episode_id, "nodeId": self.node_id},
            "projectChanged": True,
        }
        if self.asset_ref_warnings:
            result["warnings"] = self.asset_ref_warnings
        if self.node_type in {"prompt.storyboard", "director.board"}:
            from .workflow_production_sync import sync_workflow_production_after_commit

            result = sync_workflow_production_after_commit(self.project_id, self.episode_id, result)
        return result


def restore_node_edit_history(project_id: str, episode_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return _CanvasHistoryRestore(project_id, episode_id, payload).run()


def _validate_video_task_reference_links_for_model(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node: dict[str, Any],
    model_context: dict[str, Any],
) -> None:
    """Validate native input combinations and reference videos before saving.

    Model changes must not leave a task card in a state that the next generation
    request can never submit.  Rejecting the model change keeps the existing
    links intact and gives the UI a precise reason to unlink or edit the video.
    """
    from utils.video_task_types import model_supports_video_task
    if model_context.get("modelId") and not model_supports_video_task(model_context, str(node.get("type") or "")):
        raise ValueError("所选模型不支持此视频任务，请选择匹配的工作流")
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    input_links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
    video_rows: list[dict[str, Any]] = []
    for link in workflow_reference_video_input_links(project_id, episode_id, workflow, input_links):
        source_node_id = str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip()
        if not source_node_id:
            raise ValueError("视频生成存在无法识别来源的参考视频关联，请先解除该关联")
        media = link.get("media")
        if not isinstance(media, dict) or not media:
            raise ValueError("视频生成的参考视频当前没有可用媒体，请先解除该关联")
        video_rows.append(video_media_metadata(project_id, media))
    image_count = _video_task_reference_image_count_for_validation(
        project_id, episode_id, workflow, node, model_context, len(video_rows),
    )
    if not video_rows:
        return
    output_duration: float | None = None
    for candidate in (
        data.get("durationSeconds"),
        data.get("duration_seconds"),
        (data.get("generationConfig") or {}).get("durationSeconds")
        if isinstance(data.get("generationConfig"), dict)
        else None,
        (data.get("generationConfig") or {}).get("duration_seconds")
        if isinstance(data.get("generationConfig"), dict)
        else None,
        model_context.get("preferredDurationSeconds"),
    ):
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            output_duration = value
            break
    # A model change may make only the file representation incompatible.
    # Duration/count/material limits cannot be repaired and remain blocking;
    # size, format, dimensions and FPS are normalized at submission time.
    validate_reference_video_durations(
        video_rows,
        model_context,
        image_count=image_count,
        output_duration=output_duration,
    )


def _video_task_reference_image_count_for_validation(
    project_id: str, episode_id: str,
    workflow: dict[str, Any], node: dict[str, Any], model_context: dict[str, Any], video_count: int,
) -> int | None:
    """Share media counting; native cards additionally enforce exact frame roles."""
    from utils.frame_references import is_frame_image, select_frame_transport
    from utils.video_references import reference_video_capability
    from .video_reference_metadata import video_reference_input_identity
    from .workflow_input_resolution import _workflow_source_node_input_link_fields

    nodes = {str(item.get("id") or "").strip(): item for item in workflow.get("nodes", []) if isinstance(item, dict)}
    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    from .workflow_input_resolution import _resolve_workflow_node_inputs_from_workflow
    active_inputs = _resolve_workflow_node_inputs_from_workflow(project_id, workflow, episode_id, str(node["id"]))
    for link in active_inputs["inputLinks"]:
        if not isinstance(link, dict):
            continue
        if _canonical_workflow_slot(link.get("targetSlot") or link.get("slot"), "") == VIDEO_REFERENCE_SLOT:
            continue
        source_id = str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip()
        source = nodes.get(source_id)
        if source and (source.get("type") == "video.result" or _workflow_node_media_kind(source) == "video"):
            continue
        # Keep every frame association so duplicate roles still fail validation.
        if is_frame_image(link):
            references.append(link)
            continue
        fields = _workflow_source_node_input_link_fields(project_id, episode_id, workflow, source)
        identity = video_reference_input_identity({"sourceNodeId": source_id, **fields})
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        references.append({})
    if node.get("type") != "video.keyframe":
        capability = reference_video_capability(model_context)
        visual = (capability.get("adapter_capabilities") or {}).get("visual_inputs")
        if isinstance(visual, dict) and not visual.get("modes"):
            raise ValueError("当前模型仅支持首尾帧视频生成，请切换模型或任务卡类型")
        if isinstance(visual, dict):
            selection = select_frame_transport(
                references, capability, reference_video_count=video_count, allow_incomplete=True,
            )
            return len(references) - len(selection["nativeRoles"])
        return len(references)
    # Editing may precede adding the first frame; enforce limits without requiring a complete task.
    if not references and not video_count and not (model_context.get("modelId") or model_context.get("id")):
        return None
    select_frame_transport(
        references, reference_video_capability(model_context),
        reference_video_count=video_count, native_required=True, allow_incomplete=True,
    )
    return None


class _CanvasInlineEdit:
    """一次操作独立持有业务状态，按验证、准备和提交阶段执行。"""

    def __init__(self, project_id, episode_id, node_id, data_patch, generation_config, payload, save_reason):
        self.project_id = project_id
        self.episode_id = episode_id
        self.node_id = node_id
        self.data_patch = data_patch
        self.generation_config = generation_config
        self.payload = payload
        self.save_reason = save_reason

    def run(self) -> dict[str, Any] | None:
        with _JSON_WRITE_LOCK:
            result = self._load_and_check_card()
            if result is not None:
                return result
            if (self.effective_node_type == "director.board"
                    and ("directorPlanShots" in self.data_patch
                         or ("speakerRoster" in self.data_patch and self.node_data.get("directorPlanShots")))):
                return self._commit_director_plan()
            self._prepare_type_change()
            result = self._commit_current_card()
            if result is not None:
                return result
            return self._record_history_and_respond()

    def _commit_director_plan(self) -> dict[str, Any]:
        from .storyboard_allocation import apply_storyboard_allocation, default_storyboard_groups

        allowed = {"directorPlanShots", "speakerRoster", "directorRuleId",
                   "directorRuleSelectionMode", "rhythmMultiplier", "speechBudgetNote"}
        if set(self.data_patch) - allowed:
            raise ValueError("分镜内容与其他节点字段不能混合保存；请在分镜工作台保存脚本与分组")
        current_data = self.node.get("data") or {}
        shots = self.data_patch.get("directorPlanShots", current_data.get("directorPlanShots"))
        allocation = current_data.get("storyboardAllocation") or {}
        groups = default_storyboard_groups(shots, allocation) if isinstance(shots, list) else []
        if not groups:
            if (isinstance(shots, list) and shots and isinstance(shots[0], dict)
                    and shots[0].get("entryBoundaryKind") == "direct_continuation"):
                from .storyboard_allocation import require_direct_continuation_previous_group

                chain_id = str(self.node.get("workChainId") or current_data.get("workChainId") or "")
                require_direct_continuation_previous_group(self.project_id, self.episode_id, chain_id)
            self.director_draft_save = True
            self._prepare_type_change()
            self._commit_current_card()
            saved = self._record_history_and_respond()
            saved["allocationNeedsSave"] = bool(shots)
            saved["message"] = ("分镜草稿已保存，需在分镜工作台完成镜头分组后才能制作。"
                                if shots else "分镜已清空并保存为草稿。")
            return saved
        result = apply_storyboard_allocation(
            self.project_id, self.episode_id,
            {"directorNodeId": self.node_id,
             "expectedShots": copy.deepcopy(current_data.get("directorPlanShots")),
             "groups": groups,
             "directorPlanPatch": copy.deepcopy(self.data_patch),
             "invalidateGenerated": True,
             "expectedWorkflowVersion": self.payload.get("expectedRevision", self.payload.get("expected_revision"))},
            generation_config_patch=self.generation_config,
        )
        return {
            **result, "message": "分镜脚本已保存。", "nodeId": self.node_id,
            "structureChanged": result.get("structureChanged", True),
            "focusTarget": {"section": "episode", "episodeId": self.episode_id, "nodeId": self.node_id},
        }

    def _load_and_check_card(self):
        self.requested_node_type = str(
            self.data_patch.get("eyebrow")
            or self.data_patch.get("nodeType")
            or self.data_patch.get("node_type")
            or ""
        ).strip()

        self.node = read_canvas_card_record_v4(self.project_id, self.episode_id, self.node_id, detail="full")
        self.node_type = str(self.node.get("type") or "").strip()
        self.effective_node_type = self.requested_node_type or self.node_type
        if self.data_patch and not _workflow_inline_result_card_edit_allowed(
            self.effective_node_type,
            self.data_patch,
            self.save_reason,
        ):
            raise ValueError("结果卡不能通过通用文本保存修改媒体结果；请修改任务卡提示词后重新生成。")
        if self.generation_config and not _workflow_node_owns_generation_config(self.effective_node_type):
            raise ValueError("生成配置只能保存到分镜脚本、分镜单元或视频生成，不能写入结果卡或其他节点")

        if _is_user_locked_item(self.node):
            return {
                "success": True,
                "message": f"node {self.node_id} 已由用户锁定，未覆盖。",
                "episodeId": self.episode_id,
                "nodeId": self.node_id,
                "skippedLocked": True,
                "changedResources": [],
                "projectChanged": False,
            }

        self.node_data = self.node.setdefault("data", {})
        if not isinstance(self.node_data, dict):
            self.node_data = {}
            self.node["data"] = self.node_data

    def _prepare_type_change(self):
        self.node_type_changed = False
        self.patched_edges: list[dict[str, Any]] = []
        if self.requested_node_type:
            _assert_new_workflow_node_type_allowed(self.requested_node_type, allow_work_chain_managed=True)
            if self.requested_node_type != self.node_type:
                if self.save_reason != "result_frame_slot_set" or self.requested_node_type not in {"storyboard.image"}:
                    raise ValueError("节点类型只能通过受支持的结果图用途切换更新")
                self.neighborhood = read_workflow_card_neighborhood_v4(
                    self.project_id,
                    self.episode_id,
                    self.node_id,
                    detail="full",
                )
                validate_canvas_revision_v4(self.neighborhood["version"], self.payload.get("expectedRevision", self.payload.get("expected_revision")))
                latest_node = _workflow_node(self.neighborhood, self.node_id)
                if not latest_node or latest_node.get("type") != self.node_type:
                    raise ValueError("节点类型已变化，请刷新后重试")
                self.node = copy.deepcopy(latest_node)
                self.node["type"] = self.requested_node_type
                self.node_type = self.requested_node_type
                self.node_type_changed = True
                self.node_data = self.node.setdefault("data", {})
                self.node_data["eyebrow"] = self.requested_node_type
                node_by_id = {
                    str(item.get("id") or "").strip(): item
                    for item in self.neighborhood.get("nodes", [])
                    if isinstance(item, dict) and str(item.get("id") or "").strip()
                }
                node_by_id[self.node_id] = self.node
                for edge in self.neighborhood.get("edges", []):
                    if not isinstance(edge, dict):
                        continue
                    source_id = str(edge.get("source") or "").strip()
                    target_id = str(edge.get("target") or "").strip()
                    if source_id != self.node_id and target_id != self.node_id:
                        continue
                    patched_edge = copy.deepcopy(edge)
                    edge_data = patched_edge.get("data") if isinstance(patched_edge.get("data"), dict) else {}
                    patched_edge["data"] = edge_data
                    if source_id == self.node_id:
                        edge_data["sourceNodeType"] = self.requested_node_type
                    if target_id == self.node_id:
                        edge_data["targetNodeType"] = self.requested_node_type
                    _ensure_saved_workflow_edge_contract(patched_edge, node_by_id, self.neighborhood)
                    self.patched_edges.append(patched_edge)

    def _commit_current_card(self):
        def update_current_data(current_node: dict[str, Any]) -> dict[str, Any]:
            if _is_user_locked_item(current_node):
                raise ValueError("节点已锁定，未保存")
            if str(current_node.get("type") or "") != self.effective_node_type:
                raise ValueError("节点类型已变化，请刷新后重试")
            validate_node_identity_update(current_node, {"data": self.data_patch})
            previous = copy.deepcopy(current_node)
            self.previous_node = previous
            current_data = current_node.setdefault("data", {})
            if self.data_patch:
                speaker_asset_ids = None
                allowed_asset_ids = None
                if self.effective_node_type == "director.board":
                    neighborhood = read_workflow_card_neighborhood_v4(
                        self.project_id, self.episode_id, self.node_id, detail="full",
                    )
                    speaker_asset_ids = director_plan_bound_speaker_asset_ids_for_work_chain(
                        self.project_id, neighborhood, self.episode_id, self.node_id,
                    )
                    allowed_asset_ids = director_plan_bound_asset_ids_for_work_chain(
                        self.project_id, neighborhood, self.episode_id, self.node_id,
                    )
                normalized_patch = _normalize_workflow_inline_data_patch(
                    self.data_patch, current_data, self.effective_node_type,
                    project_id=self.project_id,
                    speaker_asset_ids=speaker_asset_ids, allowed_asset_ids=allowed_asset_ids,
                )
                if "scriptContinuityReview" in normalized_patch:
                    normalized_patch = self._confirm_script_continuity_review(current_node, normalized_patch)
                _cleanup_workflow_inline_existing_prompt_patch_fields(current_data, self.effective_node_type)
                current_data = _deep_merge(current_data, normalized_patch)
                if self.effective_node_type in VIDEO_TASK_NODE_TYPES:
                    card_patch = normalized_patch.get("videoTaskCard")
                    if isinstance(card_patch, dict):
                        for field in ("assetNameMap", "promptBindings", "shotPromptPlan", "voiceDesign"):
                            if field in card_patch:
                                current_data["videoTaskCard"][field] = copy.deepcopy(card_patch[field])
                        if "voiceOverrides" in card_patch:
                            # Each submitted speaker setting is complete; omitted media
                            # means inherit again, rather than retain a previous upload.
                            for speaker_id, override in card_patch["voiceOverrides"].items():
                                current_data["videoTaskCard"]["voiceOverrides"][speaker_id] = copy.deepcopy(override)
                        if any(field in card_patch for field in ("usedSpeakerIds", "voiceDesign", "voiceOverrides")):
                            from .video_reference_audio import validate_video_task_voice_names
                            validate_video_task_voice_names(self.project_id, current_data)
                current_node["data"] = current_data
                if self.effective_node_type == "prompt.storyboard":
                    _workflow_clean_script_user_instruction_fields(current_data)
                    _workflow_clear_script_obsolete_planning_fields(current_data)
                if self.effective_node_type == "director.board" and (
                    current_data.get("directorPlanShots") != (previous.get("data") or {}).get("directorPlanShots")
                    or current_data.get("speakerRoster") != (previous.get("data") or {}).get("speakerRoster")
                ):
                    previous_allocation = (previous.get("data") or {}).get("storyboardAllocation")
                    previous_allocation = previous_allocation if isinstance(previous_allocation, dict) else {}
                    current_data["storyboardAllocation"] = {
                        "schemaVersion": 1,
                        "directorPlanHash": "",
                        "groups": copy.deepcopy(previous_allocation.get("groups") or []) if current_data.get("directorPlanShots") else [],
                    }
                if self.effective_node_type == "director.board" and getattr(self, "director_draft_save", False):
                    current_data["status"] = "draft"
                    current_data.setdefault("directorTaskCard", {})["state"] = (
                        "pending_allocation" if current_data.get("directorPlanShots") else "pending_director_plan"
                    )
            if self.generation_config:
                current_data["generationConfig"] = _merge_generation_config_patch(current_data.get("generationConfig"), self.generation_config)
            if self.effective_node_type in VIDEO_TASK_NODE_TYPES:
                card_patch = self.data_patch.get("videoTaskCard") if isinstance(self.data_patch.get("videoTaskCard"), dict) else {}
                duration = next((value for value in (
                    self.data_patch.get("durationSeconds"),
                    card_patch.get("durationSeconds"),
                    self.generation_config.get("durationSeconds"),
                ) if value is not None), None)
                if duration is not None:
                    current_data["durationSeconds"] = duration
                    current_data.setdefault("videoTaskCard", {})["durationSeconds"] = duration
                    current_data.setdefault("generationConfig", {})["durationSeconds"] = duration
                next_workflow = read_workflow_card_neighborhood_v4(
                    self.project_id,
                    self.episode_id,
                    str(current_node.get("id") or self.node_id),
                    detail="full",
                )
                next_model_context = _video_task_card_target_model_context(
                    self.project_id,
                    current_data,
                    {},
                    include_timing=True,
                )
                if "finalVideoPrompt" in card_patch:
                    card = current_data.setdefault("videoTaskCard", {})
                    card["modelId"] = str(next_model_context.get("modelId") or "")
                    card["finalPromptProfile"] = str(next_model_context.get("finalPromptProfile") or "")
                if self.save_reason == "node_edit_history_restored":
                    card = current_data.get("videoTaskCard") or {}
                    prompt = str(card.get("finalVideoPrompt") or "")
                    sound = str(card.get("soundPrompt") or "")
                    manifest = []
                    if prompt_reference_labels(prompt, sound):
                        # Validate against today's links and the restored parameters before writing.
                        next_workflow["nodes"] = [
                            current_node if item.get("id") == self.node_id else item
                            for item in next_workflow.get("nodes") or []
                        ]
                        inputs = _resolve_workflow_node_inputs_from_workflow(
                            self.project_id, next_workflow, self.episode_id, self.node_id,
                        )
                        manifest = video_task_card_current_reference_snapshot(
                            self.project_id, self.episode_id, next_workflow, self.node_id, inputs,
                        ).get("referenceManifest") or []
                    resolved = {}
                    for field_text in (prompt, sound):
                        resolved.update(resolve_prompt_mentions(field_text, card.get("promptBindings", {}), manifest, require_transport=False))
                    if any(row.get("kind") == "text" and (card.get("promptBindings") or {}).get(label)
                           for label, row in resolved.items()):
                        raise ValueError("历史版本引用的资产已不在当前节点，不能恢复其旧身份绑定")
                _validate_video_task_reference_links_for_model(
                    self.project_id,
                    self.episode_id,
                    next_workflow,
                    current_node,
                    next_model_context,
                )
                if (self.effective_node_type == "video.storyboard"
                        and (current_node.get("workChainId") or current_data.get("workChainId"))
                        and isinstance(card_patch, dict)
                        and "finalVideoPrompt" in card_patch):
                    from .video_boundary_plan import work_chain_video_boundary_plan

                    next_workflow["nodes"] = [
                        current_node if row.get("id") == self.node_id else row
                        for row in next_workflow.get("nodes") or []
                    ]
                    current_data.setdefault("videoTaskCard", {})["boundaryPlan"] = work_chain_video_boundary_plan(
                        next_workflow, current_node,
                        project_id=self.project_id, episode_id=self.episode_id,
                    )
            _assert_split_asset_rename_fields_unchanged(self.project_id, previous, current_node)
            _ensure_saved_workflow_node_contract(current_node)
            return current_node["data"]

        changed_resources = [
            "canvas_node",
            *(["canvas_edge"] if self.patched_edges else []),
        ]
        if self.node_type_changed or self.patched_edges:
            self.node["data"] = update_current_data(self.node)
            self.save_result = write_canvas_records_v4(
                self.project_id,
                self.episode_id,
                nodes=[copy.deepcopy(self.node)],
                edges=self.patched_edges,
                op_type="structure_patch",
                changed_resources=changed_resources,
                expected_revision=self.neighborhood["version"],
            )
            _touch_project_meta(self.project_id)
        else:
            self.save_result = write_canvas_card_records_v4(
                self.project_id, self.episode_id, [{"id": self.node_id}],
                changed_resources=changed_resources,
                expected_revision=self.payload.get("expectedRevision", self.payload.get("expected_revision")),
                data_transform=update_current_data,
            )
            _touch_project_meta(self.project_id)
            self.node = self.save_result["nodes"][0]

    def _confirm_script_continuity_review(self, node, patch):
        from .canvas_store_queries import read_previous_cinematic_script_text_v4
        from .workflow_cinematic_script import cinematic_script_context_hash

        request = patch.pop("scriptContinuityReview")
        chain_id = str(node.get("workChainId") or "")
        metadata = copy.deepcopy((node.get("data") or {}).get("scriptGenerationMeta") or {})
        continuity = metadata.get("continuity") if isinstance(metadata, dict) else None
        if (self.effective_node_type != "prompt.storyboard" or not chain_id or patch
                or not isinstance(request, dict) or not isinstance(continuity, dict)
                or not continuity.get("previousScriptHash") or not continuity.get("generatedScriptHash")):
            raise ValueError("当前卡片不支持确认剧本衔接，请重新打开卡片")
        previous_hash = cinematic_script_context_hash(
            read_previous_cinematic_script_text_v4(self.project_id, self.episode_id, chain_id)
        )
        script_hash = cinematic_script_context_hash(_workflow_inline_existing_story_text(node.get("data") or {}))
        if request.get("previousScriptHash") != previous_hash or request.get("scriptHash") != script_hash:
            raise ValueError("剧本或前一片段已变化，请重新打开卡片复核")
        # Confirmation acknowledges this upstream version without changing the
        # script. Later manual edits retain the dependency; generation replaces it.
        continuity.update(reviewedPreviousScriptHash=previous_hash, reviewedScriptHash=script_hash, reviewedAt=_now())
        return {"scriptGenerationMeta": metadata}

    def _record_history_and_respond(self):
        history_result: dict[str, Any] = {"success": True, "skipped": True, "reason": "non_edit_save_reason"}
        if self.effective_node_type in VIDEO_TASK_NODE_TYPES and self.save_reason != "node_edit_history_restored":
            history_result = record_video_prompt_edit_history(
                self.project_id, self.episode_id, self.node, self.previous_node, self.save_reason,
            )
        elif _node_edit_history_save_reason_allowed(self.save_reason) and (
            self.effective_node_type != "director.board"
            or _node_edit_content_from_node(self.node) != _node_edit_content_from_node(self.previous_node)
        ):
            try:
                history_result = record_workflow_node_edit_history(
                    self.project_id,
                    self.episode_id,
                    self.node,
                    reason=self.save_reason,
                )
            except Exception as exc:
                history_result = {
                    "success": False,
                    "skipped": True,
                    "error": str(exc),
                }

        mutation_fields = _workflow_mutation_event_fields(
            self.save_result,
            [
                "canvas_node",
                *([] if not self.patched_edges else ["canvas_edge"]),
                *([] if history_result.get("skipped") else ["node_edit_history"]),
            ],
        )
        result = {
            "success": True,
            "message": "节点配置已保存。",
            "episodeId": self.episode_id,
            "nodeId": self.node_id,
            "node": copy.deepcopy(self.node),
            "editHistory": history_result.get("item") if isinstance(history_result, dict) else None,
            "editHistoryItems": history_result.get("items") or ([history_result["item"]] if history_result.get("item") else []),
            "editHistoryWarning": history_result.get("error") if isinstance(history_result, dict) else "",
            "workflowVersion": self.save_result.get("workflowVersion"),
            **mutation_fields,
            "focusTarget": {"section": "episode", "episodeId": self.episode_id, "nodeId": self.node_id},
            "projectChanged": True,
        }
        if self.patched_edges:
            result["edges"] = self.patched_edges
        if self.effective_node_type in {"prompt.storyboard", "director.board"}:
            from .workflow_production_sync import sync_workflow_production_after_commit

            result = sync_workflow_production_after_commit(self.project_id, self.episode_id, result)
        return result


def _save_workflow_node_inline_edit_fast_v4(
    project_id: str,
    episode_id: str,
    node_id: str,
    data_patch: dict[str, Any],
    generation_config: dict[str, Any],
    payload: dict[str, Any],
    save_reason: str,
) -> dict[str, Any] | None:
    return _CanvasInlineEdit(project_id, episode_id, node_id, data_patch, generation_config, payload, save_reason).run()


def save_workflow_node_inline_edit(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not episode_id:
        raise ValueError("缺少 episodeId")
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "保存画布节点内容")
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    if not node_id:
        raise ValueError("缺少 nodeId")

    data_patch = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    generation_config = (
        payload.get("generationConfig")
        if isinstance(payload.get("generationConfig"), dict)
        else payload.get("generation_config")
        if isinstance(payload.get("generation_config"), dict)
        else payload.get("config")
        if isinstance(payload.get("config"), dict)
        else {}
    )
    if not data_patch and not generation_config:
        raise ValueError("没有需要保存的节点配置")
    if _inline_edit_requires_workflow_validation(data_patch):
        raise ValueError("画布输入链接必须通过 link_workflow_input/unlink_workflow_input 修改，不能通过节点内容保存写入。")
    save_reason = str(payload.get("reason") or "inline_node_edit_saved")
    result = _save_workflow_node_inline_edit_fast_v4(
        project_id,
        episode_id,
        node_id,
        data_patch,
        generation_config,
        payload,
        save_reason,
    )
    if result is None:
        raise RuntimeError("节点配置保存未产生画布事务")
    return result
