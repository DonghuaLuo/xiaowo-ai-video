# -*- coding: utf-8 -*-
"""画布媒体生成执行：分镜图失败修订重试、视觉交接、视频提交与结果组装。"""
from __future__ import annotations

from .agent_sessions import _persistent_media_data_removed
from .canvas_store_queries import read_canvas_task_context_v4
from .canvas_store_queries import read_workflow_card_neighborhood_v4
from .director_plan_contract import _normalize_multiline_text
from .model_provider_config import _project_model_config
from .source_text_store import _compact_text
from .storyboard_image_generation import _generate_storyboard_image_media
from .storyboard_prompt_content import _panel_value
from .storyboard_prompt_content import _workflow_video_task_card_duration_seconds
from .storyboard_video_generation import _generate_storyboard_video_media
from .task_control import _raise_if_workflow_generation_task_cancelled
from .workflow_asset_resolution import resolve_workflow_node_inputs
from .workflow_contract import _VISUAL_HANDOFF_SOURCE_NODE_TYPES
from .workflow_contract import _WORKFLOW_VIDEO_TASK_SCOPE_STANDALONE
from .workflow_contract import _append_unique_string
from .workflow_contract import _workflow_generated_output_title
from .workflow_contract import _workflow_is_video_task_type
from .workflow_contract import _workflow_meaningful_output_title
from .workflow_contract import _workflow_media_reference_kind
from .workflow_contract import _workflow_node
from .workflow_contract import _workflow_node_meaningful_title
from .workflow_contract import _workflow_node_payload_data
from .workflow_contract import _workflow_node_type
from .workflow_contract import _workflow_node_type_value
from .workflow_contract import _workflow_node_work_chain_id
from .workflow_contract import _workflow_standalone_video_generation_config
from .workflow_contract import _workflow_standalone_video_payload
from .workflow_contract import workflow_video_task_scope
from .workflow_generation_config import _runtime_generation_config_for_execution
from .workflow_generation_config import _workflow_generation_config_source_node
from .workflow_inline_editing import _inline_first_text
from .workflow_input_resolution import _link_reference_media_id
from .workflow_input_resolution import _link_slot
from .workflow_input_resolution import _resolve_workflow_node_inputs_from_workflow
from .workflow_input_resolution import _workflow_active_card_version
from .workflow_input_resolution import _workflow_director_board_for_context
from .workflow_input_resolution import _workflow_media_reference_version_id
from .workflow_input_resolution import _workflow_node_data
from .workflow_input_resolution import workflow_current_media_reference
from .workflow_input_resolution import workflow_current_media_version_has_media
from .workflow_input_resolution import workflow_storyboard_reference_node_ids
from .workflow_storyboard_prompts import _generated_version_preview
from .workflow_storyboard_prompts import _storyboard_prompt_payload
from .workflow_storyboard_prompts import _workflow_director_context_payload
from typing import Any
import copy
import re


def _visual_handoff_source_prompt_node_id(
    workflow: dict[str, Any],
    handoff_node_id: str,
    requested_node_id: str | None = None,
) -> str:
    requested_id = str(requested_node_id or "").strip()
    requested_node = _workflow_node(workflow, requested_id) if requested_id else None
    if requested_node and _workflow_node_type(requested_node) in _VISUAL_HANDOFF_SOURCE_NODE_TYPES:
        return requested_id
    handoff_node = _workflow_node(workflow, handoff_node_id) or {}
    data = handoff_node.get("data") if isinstance(handoff_node.get("data"), dict) else {}
    for value in (data.get("resultOfNodeId"), data.get("sourceNodeId")):
        source_id = str(value or "").strip()
        source_node = _workflow_node(workflow, source_id) if source_id else None
        if source_node and _workflow_node_type(source_node) in _VISUAL_HANDOFF_SOURCE_NODE_TYPES:
            return source_id
    for edge in (workflow.get("edges", []) if isinstance(workflow.get("edges"), list) else []):
        if not isinstance(edge, dict) or str(edge.get("target") or "").strip() != handoff_node_id:
            continue
        source_id = str(edge.get("source") or "").strip()
        source_node = _workflow_node(workflow, source_id) if source_id else None
        if source_node and _workflow_node_type(source_node) in _VISUAL_HANDOFF_SOURCE_NODE_TYPES:
            return source_id
    return ""


def _visual_handoff_storyboard_image_node_id(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    source_card_node_id: str,
) -> str:
    source_card = _workflow_node(workflow, source_card_node_id)
    if not source_card or _workflow_node_type(source_card) != "storyboard.card":
        return ""
    card_data = source_card.get("data") if isinstance(source_card.get("data"), dict) else {}
    group_id = str(card_data.get("shotGroupId") or "").strip()
    if not group_id:
        return ""
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict) or _workflow_node_type(node) != "storyboard.image":
            continue
        node_id = str(node.get("id") or "").strip()
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if (not node_id
                or str(data.get("resultOfNodeId") or data.get("sourceNodeId") or "").strip() != source_card_node_id
                or str(data.get("shotGroupId") or "").strip() != group_id):
            continue
        if workflow_current_media_version_has_media(project_id, episode_id, workflow, node_id):
            return node_id
    return ""


def _visual_handoff_prompt_text_key(value: Any) -> str:
    return re.sub(r"[\s:：;；,，.。、\-—_]+", "", str(value or "")).lower()


def _visual_handoff_prompt_title(value: Any) -> str:
    text = _workflow_meaningful_output_title(value)
    if not text:
        return ""
    text = re.sub(r"^\s*分镜脚本\s*[:：]\s*", "", text).strip()
    text = re.sub(r"\s*视觉交接图\s*$", "", text).strip()
    return _workflow_meaningful_output_title(text)


def _visual_handoff_scene_reference_name(link: dict[str, Any], source_node: dict[str, Any]) -> str:
    source_data = source_node.get("data") if isinstance(source_node.get("data"), dict) else {}
    return str(
        link.get("displayName")
        or link.get("display_name")
        or link.get("assetName")
        or link.get("asset_name")
        or link.get("label")
        or source_data.get("assetName")
        or source_data.get("asset_name")
        or source_data.get("title")
        or source_data.get("name")
        or link.get("assetId")
        or link.get("rootAssetId")
        or source_node.get("id")
        or ""
    ).strip()


def _visual_handoff_scene_reference_rows(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    director_node_id: str,
) -> list[dict[str, Any]]:
    director_node = _workflow_node(workflow, str(director_node_id or "").strip())
    if not isinstance(director_node, dict):
        return []
    try:
        input_result = _resolve_workflow_node_inputs_from_workflow(
            project_id,
            workflow,
            episode_id,
            str(director_node_id or "").strip(),
        )
    except Exception:
        return []
    links = input_result.get("inputLinks") if isinstance(input_result, dict) else []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in links if isinstance(links, list) else []:
        if not isinstance(link, dict) or _link_slot(link) != "scene_reference":
            continue
        source_node_id = str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip()
        if not source_node_id:
            continue
        source_node = _workflow_node(workflow, source_node_id)
        if not isinstance(source_node, dict) or _workflow_node_type_value(source_node) != "asset.image":
            continue
        current_media = workflow_current_media_reference(project_id, episode_id, workflow, source_node_id)
        if not isinstance(current_media, dict):
            continue
        source_data = source_node.get("data") if isinstance(source_node.get("data"), dict) else {}
        if _workflow_media_reference_kind(link, source_data, current_media) == "video":
            continue
        reference_id = (
            _link_reference_media_id(link)
            or _workflow_media_reference_version_id(current_media)
            or str(current_media.get("id") or current_media.get("mediaId") or current_media.get("media_id") or "").strip()
            or source_node_id
        )
        if not reference_id:
            continue
        asset_id = str(link.get("rootAssetId") or link.get("assetId") or source_data.get("assetId") or source_data.get("asset_id") or "").strip()
        dedupe_key = str(reference_id or source_node_id).casefold()
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        display_name = _visual_handoff_scene_reference_name(link, source_node) or asset_id or "场景图"
        result.append(
            {
                "mediaId": reference_id,
                "assetId": asset_id,
                "assetType": "scenes",
                "slot": "scene_reference",
                "displayName": display_name,
                "sourceType": "direct_director_input",
                "sourceNodeId": source_node_id,
                "sourceNodeType": "asset.image",
                "mediaVersionId": _workflow_media_reference_version_id(current_media),
                "sourceMediaId": str(current_media.get("id") or current_media.get("mediaId") or current_media.get("media_id") or "").strip(),
                "roleInScene": "场景图用于提供主场景外观、主要结构、入口出口、通道或动线、固定地貌或固定陈设、关键空间锚点、光源和环境材质；若图中存在俯视或调度示意，可用于辅助表达人物、道具、机位和动线的方位关系。"
            }
        )
    return result


def _visual_handoff_reference_materials(
    *,
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    director_node_id: str,
    source_storyboard_version_id: str,
    source_storyboard_title: str,
    storyboard_image_node_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    storyboard_display_name = _visual_handoff_prompt_title(source_storyboard_title) or "当前分镜图"
    manifest: list[dict[str, Any]] = [
        {
            "visualId": "H00",
            "mediaId": source_storyboard_version_id,
            "slot": "storyboard_image",
            "displayName": storyboard_display_name,
            "sourceType": "storyboard_version",
            "sourceNodeId": storyboard_image_node_id,
            "roleInScene": "本段剧情已生成的故事版分镜图，用于确认连续镜头、最后有效镜头和结尾状态。",
        }
    ]
    manifest.extend(
        _visual_handoff_scene_reference_rows(
            project_id,
            episode_id,
            workflow,
            director_node_id,
        )
    )
    reference_media_ids: list[str] = []
    scene_index = 0
    for index, row in enumerate(manifest, start=1):
        row["refId"] = f"R{index:02d}"
        if str(row.get("slot") or "").strip() == "scene_reference":
            scene_index += 1
            row["visualId"] = f"S{scene_index:02d}"
        reference_media_ids = _append_unique_string(reference_media_ids, str(row.get("mediaId") or ""))
    return {
        "referenceMediaIds": reference_media_ids,
        "referenceManifest": manifest,
    }


def _visual_handoff_reference_manifest_prompt(reference_manifest: list[dict[str, Any]]) -> str:
    rows = [row for row in reference_manifest if isinstance(row, dict)]
    scene_rows = [
        row
        for row in rows
        if str(row.get("slot") or "").strip() == "scene_reference"
    ]
    if not scene_rows:
        return ""
    lines = [
        "【图片资产引用提示词】",
        "以下参考图序号与实际随附图片顺序严格一致。",
    ]
    for index, row in enumerate(rows, start=1):
        slot = str(row.get("slot") or "").strip()
        display_name = str(row.get("displayName") or row.get("assetId") or row.get("mediaId") or "").strip()
        role_text = str(row.get("roleInScene") or "").strip()
        if slot == "storyboard_image":
            lines.append(
                f"参考图{index:02d}（故事版分镜图）：{display_name or '当前分镜图'}。"
                "用途：作为最主要依据，理解本段剧情的连续镜头、最后有效镜头、人物/道具终态和局部事件状态。"
            )
        elif slot == "scene_reference":
            visual_id = str(row.get("visualId") or f"S{len(lines):02d}").strip()
            lines.append(
                f"参考图{index:02d}（场景图 {visual_id}）：{display_name or '场景图'}。"
                f"用途：{role_text or '提供完整空间骨架和稳定环境关系。'}"
            )
    lines.extend(
        [
            "多图理解方式：参考图01决定本段剧情的结尾状态；场景图决定稳定空间结构、固定陈设、环境外观、材质和光源。若场景图包含俯视或调度示意，可用于辅助表达人物、道具、机位和动线的方位关系。",
            "当故事版只展示局部空间时，用场景图补足当前场景的整体边界、主要结构、入口出口、通道或动线、固定地貌或固定陈设、关键空间锚点、光源和比例关系；只有两类参考图都未覆盖的位置，才做克制补全。",
            "若故事版结尾状态与场景图静态状态存在差异，人物/道具的终态以故事版最后有效镜头为准，稳定空间骨架以场景图为准。",
        ]
    )
    return "\n".join(lines)


def _visual_handoff_generation_prompt(
    *,
    title: str,
    source_storyboard_title: str,
    payload: dict[str, Any],
) -> str:
    panels = payload.get("panels") if isinstance(payload.get("panels"), list) else []
    visual_beat_rows: list[str] = []
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            continue
        shot_label = str(
            panel.get("shotLabel")
            or panel.get("shot_label")
            or panel.get("id")
            or f"Shot {index + 1:02d}"
        ).strip()
        row_parts: list[str] = []
        row_part_keys: set[str] = set()
        shot_label_key = _visual_handoff_prompt_text_key(shot_label)
        for value in (
            _panel_value(panel, "title", "name"),
            _panel_value(panel, "storyboardFrame", "storyboard_frame"),
            _panel_value(panel, "camera", "cameraInstruction", "camera_instruction"),
        ):
            text = str(value or "").strip()
            text_key = _visual_handoff_prompt_text_key(text)
            if text and text_key and text_key != shot_label_key and text_key not in row_part_keys:
                row_parts.append(text)
                row_part_keys.add(text_key)
        if row_parts:
            visual_beat_rows.append(f"{shot_label}：{'；'.join(row_parts)}")
    last_panel = panels[-1] if panels and isinstance(panels[-1], dict) else {}
    last_action_parts: list[str] = []
    for value in (
        _panel_value(last_panel, "storyboardFrame", "storyboard_frame"),
        _panel_value(last_panel, "camera", "cameraInstruction", "camera_instruction"),
    ):
        text = str(value or "").strip()
        if text and text not in last_action_parts:
            last_action_parts.append(text)
    last_action = _compact_text(
        "；".join(last_action_parts),
        700,
    )
    visual_beats_text = "\n".join(visual_beat_rows).strip()
    if len(visual_beats_text) > 1400:
        visual_beats_text = visual_beats_text[:1397].rstrip() + "..."
    story_text = _compact_text(str(payload.get("userStoryText") or ""), 2000)
    reference_title = _visual_handoff_prompt_title(source_storyboard_title) or _visual_handoff_prompt_title(title)
    reference_line = "随附参考图为本段剧情已生成的故事版分镜图。"
    if reference_title:
        reference_line = f"{reference_line}\n片段标题：{reference_title}"
    return (
        "【视觉交接图生成任务】\n"
        "请根据随附故事版分镜图、可拍摄内容和分镜线索，生成一张空间连续性交接图。"
        "随附参考图只用于理解本段剧情已有镜头和空间状态；请重新整理为连续性状态板，不裁切、复刻或拼贴原故事板。\n\n"
        "【核心目的】\n"
        "交接图用于让后续剧情片段理解本段剧情结尾时同一空间内人物、生物、关键道具、固定地貌或固定陈设、入口出口、通道或动线、光源和环境变化的位置、朝向、相对距离和状态。"
        "它只记录空间连续性和终态，不替后续剧情片段设计机位、景别、镜头运动或构图。\n\n"
        "【必须呈现】\n"
        "1. 主区域：俯视空间调度图/简化平面示意，固定清楚的前后左右或方位标记；标出场景边界、入口出口、主要通道或行动路径、固定地貌或固定陈设、关键空间锚点和道具。\n"
        "2. 人物/生物/关键道具：用清晰标记呈现位置，给人物和生物加朝向箭头、视线方向或移动方向；保持相对距离、阵营关系、位置/调度关系和随附故事板最后有效镜头中已确定的终态姿态。若最后有效镜头未完整展示身体姿态，应结合随附故事板中本段剧情的前后镜头和镜头内调度示意理解，不自行改变已建立的人物位置、姿态和朝向。\n"
        "3. 辅助区域：本段剧情最后有效镜头的结束状态参考，包括关键人物姿态、手持/掉落/损坏道具、服装和道具成色、光照、烟尘/破坏/水火等状态。\n"
        "4. 标签：使用简体中文短标签，标签服务于空间理解，不遮挡主体；不要输出大段说明文字。\n\n"
        "【禁止】\n"
        "不要生成新的剧情分镜，不要生成宣传海报，不要只画最后一帧特写，不要省略俯视调度关系，不要让人物或关键道具的位置与故事板末尾状态冲突。\n\n"
        f"【随附故事版参考】\n{reference_line}\n"
        f"【可拍摄内容】\n{story_text or '以随附故事板和任务上下文为准。'}\n"
        f"【分镜线索】\n{visual_beats_text or '以可拍摄内容和随附故事板的连续镜头为准。'}\n"
        f"【最后有效镜头状态线索】\n{last_action or '从随附故事板的最后有效镜头中理解人物位置、朝向、道具和环境状态。'}"
    )


class _WorkflowMediaGeneration:
    """每次请求独立持有业务状态，显式执行准备、请求与结果处理阶段。"""

    def __init__(self, project_id, episode_id, node_id, version_type, task_type, user_instruction, revision_result, requested_node_id, generation_config_override, generation_config_provided, task_id):
        self.project_id = project_id
        self.episode_id = episode_id
        self.node_id = node_id
        self.version_type = version_type
        self.task_type = task_type
        self.user_instruction = user_instruction
        self.revision_result = revision_result
        self.requested_node_id = requested_node_id
        self.generation_config_override = generation_config_override
        self.generation_config_provided = generation_config_provided
        self.task_id = task_id

    def run(self) -> dict[str, Any]:
        self._load_context()
        self._prepare_request()
        if self.task_type == "storyboard_plan":
            self._describe_director_plan()
        elif self.task_type == "storyboard_image":
            self._generate_storyboard_image()
        elif self.task_type == "visual_handoff_image":
            self._prepare_visual_handoff()
            self._request_visual_handoff()
        elif self.task_type == "storyboard_video":
            self._prepare_video_references()
            self._prepare_video_config()
            self._submit_video()
        else:
            self.summary = str(self.node_data.get("summary") or "工作流节点已运行。")
        return self._build_result()

    def _load_context(self):
        self.workflow = read_workflow_card_neighborhood_v4(self.project_id, self.episode_id, self.node_id, detail="full")
        resolve_workflow_node_inputs(self.project_id, self.episode_id, {"nodeId": self.node_id}, workflow=self.workflow)
        self.node_data = _workflow_node_data(self.workflow, self.node_id)
        self.current_node = _workflow_node(self.workflow, self.node_id) or {}
        route_id = str(self.current_node.get("routeId") or self.node_data.get("routeId") or "").strip() or None
        work_chain_id = _workflow_node_work_chain_id(self.workflow, self.current_node) or None
        self.payload_node_id = self.node_id
        self.visual_handoff_source_prompt_node_id = ""
        if self.task_type == "visual_handoff_image":
            self.visual_handoff_source_prompt_node_id = _visual_handoff_source_prompt_node_id(
                self.workflow,
                self.node_id,
                self.requested_node_id,
            )
            if not self.visual_handoff_source_prompt_node_id:
                raise ValueError("视觉交接图缺少来源分镜单元")
            self.workflow = read_canvas_task_context_v4(
                self.project_id,
                self.episode_id,
                self.visual_handoff_source_prompt_node_id,
                detail="full",
                extra_node_ids=[self.node_id],
            )
            self.current_node = _workflow_node(self.workflow, self.node_id) or self.current_node
            self.node_data = _workflow_node_data(self.workflow, self.node_id) or self.node_data
            storyboard_image_id = _visual_handoff_storyboard_image_node_id(
                self.project_id, self.episode_id, self.workflow,
                self.visual_handoff_source_prompt_node_id,
            )
            storyboard_image_node = _workflow_node(self.workflow, storyboard_image_id)
            if not storyboard_image_node or _workflow_node_type(storyboard_image_node) != "storyboard.image":
                raise ValueError("请先生成当前分镜单元的分镜图，再生成视觉交接图")
            self.payload_node_id = storyboard_image_id
            route_id = str(self.current_node.get("routeId") or self.node_data.get("routeId") or "").strip() or None
            work_chain_id = _workflow_node_work_chain_id(self.workflow, self.current_node) or None
        current_video_task_scope = (
            workflow_video_task_scope(self.workflow, self.current_node)
            if self.task_type == "storyboard_video"
            else ""
        )
        self.payload = (
            _workflow_standalone_video_payload(
                self.episode_id,
                str(self.node_data.get("title") or "视频生成").strip(),
            )
            if self.task_type == "storyboard_video" and current_video_task_scope == _WORKFLOW_VIDEO_TASK_SCOPE_STANDALONE
            else _storyboard_prompt_payload(self.project_id, self.episode_id, self.workflow, node_id=self.payload_node_id)
        )

    def _prepare_request(self):
        self.instruction = str(self.user_instruction or "").strip()
        revision = self.revision_result if isinstance(self.revision_result, dict) else {}
        if self.instruction:
            self.payload["userInstruction"] = self.instruction
        self.normalized_task_id = str(self.task_id or "").strip()
        if self.normalized_task_id:
            self.payload["taskId"] = self.normalized_task_id
        if revision:
            self.payload["revisionApplied"] = bool(revision.get("applied"))
            if revision.get("error"):
                self.payload["revisionError"] = str(revision.get("error") or "")
            model_meta = revision.get("modelMeta") if isinstance(revision.get("modelMeta"), dict) else {}
            if model_meta:
                self.payload["revisionModel"] = {
                    "source": model_meta.get("source"),
                    "modelId": model_meta.get("modelId"),
                    "modelLabel": model_meta.get("modelLabel"),
                    "providerId": model_meta.get("providerId"),
                    "error": model_meta.get("error"),
                }
        _raise_if_workflow_generation_task_cancelled(self.payload)
        self.panel_count = int(self.payload.get("panelCount") or 0)
        raw_title = str(self.node_data.get("title") or "生成版本").strip()
        self.title = (
            _workflow_generated_output_title(
                self.workflow,
                self.node_id,
                self.task_type,
                fallback=raw_title,
            )
            if self.task_type in {"storyboard_image", "storyboard_video", "visual_handoff_image"}
            else _workflow_meaningful_output_title(raw_title)
        ) or raw_title
        self.source = "workflow-run"
        self.media_result: dict[str, Any] = {}
        self.generation_error = ""

    def _describe_director_plan(self):
        count_label = f"{self.panel_count} 个连续镜头面板" if self.panel_count else "当前"
        director_context = _workflow_director_context_payload(self.workflow, self.current_node)
        self.director_plan_text = _normalize_multiline_text(
            director_context.get("directorPlan")
            or self.node_data.get("directorPlan")
        )
        self.summary = f"已生成{count_label}分镜脚本。"
        if self.instruction:
            self.summary += " 本轮补充要求已纳入分镜脚本生成。"
        self.source = "model-director-plan"
        self.payload["generationStage"] = "director_plan"
        self.payload["planGenerationMode"] = "model"
        if self.director_plan_text:
            self.payload["directorPlan"] = self.director_plan_text
        if isinstance(director_context, dict) and director_context:
            self.payload["directorContext"] = copy.deepcopy(director_context)

    def _generate_storyboard_image(self):
        director_context_payload = (
            self.payload.get("directorContext")
            if isinstance(self.payload.get("directorContext"), dict)
            else {}
        )
        self.director_plan_text = _normalize_multiline_text(
            self.payload.get("directorPlan")
            or director_context_payload.get("directorPlan")
        )
        if not self.director_plan_text:
            raise ValueError("请先填写或生成分镜脚本，再生成分镜图。")
        prompt_spec = self.payload.get("storyboardPromptSpec") if isinstance(self.payload.get("storyboardPromptSpec"), dict) else {}
        self.is_single_panel = str(prompt_spec.get("format") or "") == "single_storyboard_panel"
        self.summary = (
            "已根据分镜脚本生成单个故事版镜头面板。"
            if self.is_single_panel
            else f"已根据分镜脚本生成故事版镜头图，包含 {self.panel_count or 0} 个连续镜头面板。"
        )

        self.payload = self._prepare_storyboard_image_payload(self.payload, self.workflow)
        try:
            self.media_result = _generate_storyboard_image_media(
                self.project_id,
                self.episode_id,
                self.title,
                self.payload,
                workflow_projection=self.workflow,
            )
            if isinstance(self.media_result.get("payload"), dict):
                self.payload = copy.deepcopy(self.media_result["payload"])
            self.summary = (
                "已调用图片模型生成单个故事版镜头面板。"
                if self.is_single_panel
                else f"已调用图片模型生成分镜图，包含 {self.panel_count or 0} 个连续镜头面板。"
            )
            self.source = str(self.media_result.get("source") or "model-image-generation")
        except Exception as exc:
            self._handle_storyboard_image_failure(exc)

    def _handle_storyboard_image_failure(self, exc: Exception):
        _raise_if_workflow_generation_task_cancelled(self.payload)
        self.exc_payload = getattr(exc, "payload", None)
        if isinstance(self.exc_payload, dict):
            self.payload = copy.deepcopy(self.exc_payload)
        self.exc_debug = getattr(exc, "debug", None)
        if isinstance(self.exc_debug, dict):
            self.media_result["debug"] = copy.deepcopy(self.exc_debug)
        self.generation_error = str(exc)
        self.source = "model-image-generation-failed"
        self.summary = self.generation_error or "图片模型未完成直接出图"


    def _prepare_visual_handoff(self):
        source_prompt_node_id = self.visual_handoff_source_prompt_node_id or _visual_handoff_source_prompt_node_id(
            self.workflow,
            self.node_id,
            self.requested_node_id,
        )
        if not source_prompt_node_id:
            raise ValueError("视觉交接图缺少来源分镜单元")
        storyboard_image_node_id = _visual_handoff_storyboard_image_node_id(
            self.project_id, self.episode_id, self.workflow, source_prompt_node_id,
        )
        storyboard_image_node = _workflow_node(self.workflow, storyboard_image_node_id)
        if not storyboard_image_node:
            raise ValueError("请先生成当前工作链的分镜图，再生成视觉交接图")
        source_storyboard_version = _workflow_active_card_version(
            self.project_id,
            self.episode_id,
            storyboard_image_node_id,
            storyboard_image_node,
        )
        source_storyboard_version_id = str(source_storyboard_version.get("id") or "").strip()
        source_storyboard_media = (
            source_storyboard_version.get("media")
            if isinstance(source_storyboard_version.get("media"), dict)
            else {}
        )
        if not source_storyboard_version_id or not source_storyboard_media:
            raise ValueError("请先生成当前工作链的分镜图，再生成视觉交接图")
        source_storyboard_title = _workflow_node_meaningful_title(self.workflow, storyboard_image_node_id)
        source_prompt_node = _workflow_node(self.workflow, source_prompt_node_id)
        director_node = _workflow_director_board_for_context(self.workflow, source_prompt_node)
        reference_materials = _visual_handoff_reference_materials(
            project_id=self.project_id,
            episode_id=self.episode_id,
            workflow=self.workflow,
            director_node_id=str((director_node or {}).get("id") or ""),
            source_storyboard_version_id=source_storyboard_version_id,
            source_storyboard_title=source_storyboard_title,
            storyboard_image_node_id=storyboard_image_node_id,
            payload=self.payload,
        )
        handoff_prompt = _visual_handoff_generation_prompt(
            title=self.title,
            source_storyboard_title=source_storyboard_title,
            payload=self.payload,
        )
        reference_manifest_prompt = _visual_handoff_reference_manifest_prompt(
            reference_materials.get("referenceManifest")
            if isinstance(reference_materials.get("referenceManifest"), list)
            else []
        )
        if reference_manifest_prompt and reference_manifest_prompt not in handoff_prompt:
            handoff_prompt = f"{handoff_prompt.rstrip()}\n\n{reference_manifest_prompt}"
        self.payload["generationStage"] = "visual_handoff_image"
        self.payload["storyboardImageSource"] = "visual_handoff_generation"
        self.payload["visualHandoffImagePrompt"] = handoff_prompt
        self.payload["storyboardImagePrompt"] = handoff_prompt
        self.payload["storyboardImagePromptRaw"] = handoff_prompt
        if reference_manifest_prompt:
            self.payload["visualHandoffReferencePrompt"] = reference_manifest_prompt
        self.payload["referenceMediaIds"] = copy.deepcopy(reference_materials.get("referenceMediaIds") or [source_storyboard_version_id])
        self.payload["referenceManifest"] = copy.deepcopy(
            reference_materials.get("referenceManifest")
            if isinstance(reference_materials.get("referenceManifest"), list)
            else []
        )
        self.payload["sourcePromptNodeId"] = source_prompt_node_id
        self.payload["sourceStoryboardImageNodeId"] = storyboard_image_node_id
        self.payload["sourceStoryboardImageVersionId"] = source_storyboard_version_id
        self.payload["sourceStoryboardImageMedia"] = _persistent_media_data_removed(source_storyboard_media)
        self.payload["storyboardPromptSpec"] = {
            "format": "visual_handoff_board",
            "source": "storyboard_image",
            "sourceStoryboardImageNodeId": storyboard_image_node_id,
            "sourceStoryboardImageVersionId": source_storyboard_version_id,
            "purpose": "spatial_continuity_handoff",
        }
        self.image_section = _project_model_config(self.project_id)[2].get("image", {})
        self.generation_config = _runtime_generation_config_for_execution(
            self.workflow,
            self.node_id,
            self.requested_node_id,
            request_generation_config=self.generation_config_override,
            request_generation_config_provided=self.generation_config_provided,
        )
        self.payload["imageModel"] = (
            self.generation_config.get("modelId")
            or self.generation_config.get("model_id")
            or (self.image_section.get("model_id") if isinstance(self.image_section, dict) else "")
        )
        self.payload["imageSize"] = (
            self.generation_config.get("resolution")
            or self.generation_config.get("size")
            or (self.image_section.get("storyboard_resolution") if isinstance(self.image_section, dict) else "")
        )
        if self.generation_config:
            self.payload["resolvedConfig"] = copy.deepcopy(self.generation_config)
        self.summary = "正在根据当前分镜图生成视觉交接图。"

    def _request_visual_handoff(self):
        try:
            self.media_result = _generate_storyboard_image_media(
                self.project_id,
                self.episode_id,
                self.title,
                self.payload,
                workflow_projection=self.workflow,
            )
            if isinstance(self.media_result.get("payload"), dict):
                self.payload = copy.deepcopy(self.media_result["payload"])
            self.summary = "已调用图片模型生成视觉交接图。"
            self.source = str(self.media_result.get("source") or "model-visual-handoff-generation")
        except Exception as exc:
            self.exc_payload = getattr(exc, "payload", None)
            if isinstance(self.exc_payload, dict):
                self.payload = copy.deepcopy(self.exc_payload)
            self.exc_debug = getattr(exc, "debug", None)
            if isinstance(self.exc_debug, dict):
                self.media_result["debug"] = copy.deepcopy(self.exc_debug)
            self.generation_error = str(exc)
            self.source = "model-visual-handoff-generation-failed"
            self.summary = self.generation_error or "视觉交接图未完成直接出图"

    def _prepare_video_references(self):
        video_task_scope = workflow_video_task_scope(self.workflow, self.current_node)
        self.is_standalone_video_task = video_task_scope == _WORKFLOW_VIDEO_TASK_SCOPE_STANDALONE
        image_nodes = (
            []
            if self.is_standalone_video_task
            else [
                _workflow_node(self.workflow, image_node_id)
                for image_node_id in workflow_storyboard_reference_node_ids(
                    self.workflow,
                    node_id=self.node_id,
                )
            ]
        )
        image_version_ids = []
        for item in image_nodes:
            if not isinstance(item, dict):
                continue
            item_data = item.get("data") if isinstance(item.get("data"), dict) else {}
            image_version_id = str(
                item_data.get("activeVersionId")
                or item_data.get("activeMediaVersionId")
                or item_data.get("mediaVersionId")
                or ""
            ).strip()
            if image_version_id:
                image_version_ids.append(image_version_id)
        self.payload["generationStage"] = "storyboard_video"
        if video_task_scope:
            self.payload["videoTaskScope"] = video_task_scope
        self.payload["imageVersionId"] = image_version_ids[0] if image_version_ids else None
        self.payload["imageVersionIds"] = image_version_ids

    def _prepare_video_config(self):
        model_config = _project_model_config(self.project_id)[2]
        video_section = model_config.get("video", {}) if isinstance(model_config.get("video"), dict) else {}
        self.generation_config = _runtime_generation_config_for_execution(
            self.workflow,
            self.node_id,
            self.requested_node_id,
            request_generation_config=self.generation_config_override,
            request_generation_config_provided=self.generation_config_provided,
        )
        requested_node = _workflow_node(self.workflow, str(self.requested_node_id or "").strip()) if self.requested_node_id else None
        generation_source_node = _workflow_generation_config_source_node(self.workflow, self.current_node, requested_node)
        generation_source_data = (
            _workflow_node_payload_data(generation_source_node)
            if isinstance(generation_source_node, dict)
            else {}
        )
        generation_source_is_video_task = bool(
            generation_source_node
            and _workflow_is_video_task_type(_workflow_node_type_value(generation_source_node))
        )
        if generation_source_is_video_task:
            source_video_task_card = generation_source_data.get("videoTaskCard")
            if not isinstance(source_video_task_card, dict):
                source_video_task_card = {}
            source_video_task_card = copy.deepcopy(source_video_task_card)
            final_video_prompt = _inline_first_text(
                source_video_task_card,
                "finalVideoPrompt",
            )
            if not final_video_prompt:
                raise ValueError("当前视频生成缺少视频提示词，无法生成视频。")
            payload_prompt = self.payload.get("prompt") if isinstance(self.payload.get("prompt"), dict) else {}
            self.payload["prompt"] = {
                **copy.deepcopy(payload_prompt),
                "videoPrompt": final_video_prompt,
                "videoPromptRaw": final_video_prompt,
            }
            self.payload["videoPrompt"] = final_video_prompt
            self.payload["videoPromptRaw"] = final_video_prompt
            self.payload["videoTaskCard"] = source_video_task_card
        if self.is_standalone_video_task:
            self.payload["strategy"] = "image_reference_video"
            self.payload["videoInputMode"] = "image_reference"
            self.payload["referenceMode"] = "image_reference"
            self.payload["videoInputPlan"] = {
                "mode": "image_reference",
                "referenceMode": "image_reference",
                "requiredSlots": ["image_reference"],
            }
        task_duration_seconds = (
            _workflow_video_task_card_duration_seconds(generation_source_data)
            if generation_source_node
            and _workflow_is_video_task_type(_workflow_node_type_value(generation_source_node))
            else None
        )
        self.payload["videoModel"] = (
            self.generation_config.get("modelId")
            or self.generation_config.get("model_id")
            or video_section.get("model_id")
        )
        duration_seconds = task_duration_seconds
        if duration_seconds:
            self.payload["durationSeconds"] = duration_seconds
            if self.generation_config:
                self.generation_config.pop("duration_seconds", None)
                self.generation_config.pop("duration", None)
                self.generation_config["durationSeconds"] = duration_seconds
        if self.is_standalone_video_task:
            self.generation_config = _workflow_standalone_video_generation_config(self.generation_config)
        self.payload["resolution"] = (
            self.generation_config.get("resolution")
            or self.generation_config.get("size")
            or video_section.get("resolution")
        )
        if self.generation_config:
            self.payload["resolvedConfig"] = copy.deepcopy(self.generation_config)
        duration_label = f"{self.payload.get('durationSeconds')}s" if self.payload.get("durationSeconds") else "按分镜时长"
        self.summary = (
            f"已生成故事版视频版本参数：{duration_label} · {self.payload.get('resolution')}，"
            f"输入分镜图版本 {self.payload.get('imageVersionId') or '待绑定'}。"
        )

    def _submit_video(self):
        try:
            self.media_result = _generate_storyboard_video_media(self.project_id, self.episode_id, self.title, self.payload, self.workflow)
            self.source = str(self.media_result.get("source") or "model-video-generation")
            if self.media_result.get("status") == "processing":
                self.summary = "视频任务已提交，供应商仍在处理；版本中保留任务 ID 与生成参数。"
            elif self.media_result.get("status") == "blocked":
                self.summary = str(
                    self.media_result.get("summary")
                    or "视频阻断已开启：已写入最终提示词，未请求供应商 API。"
                )
            else:
                self.summary = f"{self.title}已生成成功。"
        except Exception as exc:
            self.generation_error = str(exc)
            self.source = "model-video-generation-failed"
            self.summary = f"视频模型未完成直接生成：{self.generation_error}"

    def _build_result(self):
        has_media_result = bool(self.media_result.get("media"))
        media_status = str(self.media_result.get("status") or "")
        preview = self.media_result.get("preview")
        if not self.generation_error and media_status != "processing" and not preview and not has_media_result:
            preview = _generated_version_preview(self.version_type, self.title, self.payload)
        result = {
            "title": self.title,
            "summary": self.summary,
            "source": self.source,
            "payload": self.payload,
        }
        node_data_patch: dict[str, Any] = {}
        if self.task_type == "storyboard_image":
            storyboard_contract = (
                self.payload.get("storyboardInterpretationContract")
                if isinstance(self.payload.get("storyboardInterpretationContract"), dict)
                else {}
            )
            if storyboard_contract:
                node_data_patch["storyboardInterpretationContract"] = copy.deepcopy(storyboard_contract)
                shot_timing_plan = (
                    storyboard_contract.get("shotTimingPlan")
                    if isinstance(storyboard_contract.get("shotTimingPlan"), dict)
                    else self.payload.get("shotTimingPlan")
                    if isinstance(self.payload.get("shotTimingPlan"), dict)
                    else {}
                )
                if shot_timing_plan:
                    node_data_patch["shotTimingPlan"] = copy.deepcopy(shot_timing_plan)
        if node_data_patch:
            result["nodeDataPatch"] = node_data_patch
        if preview:
            result["preview"] = preview
        if self.media_result.get("media"):
            result["media"] = self.media_result.get("media")
        if self.task_type == "storyboard_image" and self.media_result.get("workpageMedia"):
            result["workpageMedia"] = self.media_result["workpageMedia"]
            result.setdefault("nodeDataPatch", {})["workpageMedia"] = self.media_result["workpageMedia"]
        if self.media_result.get("model"):
            result["model"] = self.media_result.get("model")
        if self.media_result.get("provider"):
            result["provider"] = self.media_result.get("provider")
        if self.media_result.get("debug"):
            result["generationDebug"] = _persistent_media_data_removed(self.media_result.get("debug"))
        if self.generation_error:
            result["generationError"] = self.generation_error
            result["status"] = "failed"
        if self.media_result.get("status"):
            result["status"] = self.media_result.get("status")
        return result

    def _prepare_storyboard_image_payload(
        self,
        base_payload: dict[str, Any],
        active_workflow: dict[str, Any],
    ) -> dict[str, Any]:
        next_payload = copy.deepcopy(base_payload)
        if self.normalized_task_id:
            next_payload["taskId"] = self.normalized_task_id
        next_payload["generationStage"] = "storyboard_image"
        next_payload["storyboardImageSource"] = "task_generation"
        image_section = _project_model_config(self.project_id)[2].get("image", {})
        generation_config = _runtime_generation_config_for_execution(
            active_workflow,
            self.node_id,
            self.requested_node_id,
            request_generation_config=self.generation_config_override,
            request_generation_config_provided=self.generation_config_provided,
        )
        next_payload["imageModel"] = (
            generation_config.get("modelId")
            or generation_config.get("model_id")
            or (image_section.get("model_id") if isinstance(image_section, dict) else "")
        )
        next_payload["imageSize"] = (
            generation_config.get("resolution")
            or generation_config.get("size")
            or (image_section.get("storyboard_resolution") if isinstance(image_section, dict) else "")
        )
        if generation_config:
            next_payload["resolvedConfig"] = copy.deepcopy(generation_config)
        return next_payload


def build_storyboard_generation_metadata(
    project_id: str,
    episode_id: str,
    node_id: str,
    version_type: str,
    task_type: str,
    *,
    user_instruction: str = "",
    revision_result: dict[str, Any] | None = None,
    requested_node_id: str | None = None,
    generation_config_override: dict[str, Any] | None = None,
    generation_config_provided: bool = False,
    task_id: str | None = None,
) -> dict[str, Any]:
    return _WorkflowMediaGeneration(project_id, episode_id, node_id, version_type, task_type, user_instruction, revision_result, requested_node_id, generation_config_override, generation_config_provided, task_id).run()
