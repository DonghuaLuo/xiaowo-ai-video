# -*- coding: utf-8 -*-
"""分镜生成上下文、镜头解释契约、图像提示词和预览构建。"""
from __future__ import annotations

from .agent_sessions import _project_dir
from .agent_sessions import _project_meta_path
from .asset_reference_scope import _collect_workflow_asset_refs
from .asset_reference_scope import _project_asset_binding_index
from .asset_reference_scope import _project_asset_lookup_with_scope
from .asset_reference_scope import _validate_asset_refs_for_episode_scope
from .director_plan_contract import _normalize_multiline_text
from .director_rules import _normalize_director_rule_id
from .planning_contract import _workflow_clean_seconds
from .planning_contract import _workflow_shot_timing_plan_duration
from .planning_contract import _workflow_timing_number
from .production_specs import build_project_production_spec
from .production_specs import build_storyboard_render_spec
from .project_management import get_effective_config
from .reference_utils import asset_refs_has_value as _asset_refs_has_value
from .source_text_store import _compact_text
from .source_text_store import _episode_source_ref_path
from .splitting_templates import _string_list
from .store_core import _read_json
from .storyboard_prompt_content import _duration_seconds_value
from .storyboard_prompt_content import _panel_action_text
from .storyboard_prompt_content import _panel_asset_ref_text
from .storyboard_prompt_content import _panel_prompt
from .storyboard_prompt_content import _panel_timing_text
from .storyboard_prompt_content import _panel_title
from .storyboard_prompt_content import _panel_value
from .storyboard_prompt_content import _storyboard_panels_duration_seconds
from .storyboard_prompt_content import _storyboard_panels_shot_timing_plan
from .storyboard_prompt_content import _storyboard_target_frame_composition_note
from .storyboard_prompt_content import _storyboard_template_layout_block
from .storyboard_prompt_content import _xml_text
from .storyboard_templates import storyboard_template_id
from .storyboard_templates import storyboard_template_label
from .storyboard_templates import storyboard_template_layout_spec
from .storyboard_templates import storyboard_template_layout_kind
from .storyboard_templates import storyboard_panel_arrangement_rules
from .storyboard_templates import storyboard_template_prompt_rules
from .storyboard_templates import storyboard_template_single_panel_prompt_rules
from .storyboard_visual_policy import storyboard_presentation_effect_preset
from .storyboard_reference_scope import scope_storyboard_reference_manifest
from .video_reference_metadata import replace_known_local_asset_mentions
from .video_task_card_prompts import _director_plan_shot_rows_from_structured
from .work_chain_context import card_text
from .work_chain_context import script_source_text
from .work_chain_context import work_chain_stage_node
from .canvas_ownership import work_chain_origin
from .workflow_contract import _VISUAL_HANDOFF_SLOT
from .workflow_contract import _workflow_node
from .workflow_contract import _workflow_node_work_chain_id
from .workflow_generation_config import _merge_version_payload_snapshots
from .workflow_generation_config import _reference_manifest_prompt
from .workflow_generation_config import _workflow_version_payload_snapshots
from .workflow_input_resolution import _workflow_director_board_for_context
from typing import Any
import base64
import copy
import hashlib
import re


def _storyboard_story_context_text(
    meta: dict[str, Any],
    story_world: dict[str, Any] | None = None,
) -> str:
    return ""


def _storyboard_visual_style_prompt_text(text: Any) -> str:
    prompt = str(text or "").strip()
    if not prompt:
        return ""
    prompt = re.sub(r"^\s*(?:画风|风格|视觉风格)\s*[:：]\s*", "", prompt)
    if not prompt:
        return ""
    return f"视觉风格：{prompt}"


def _storyboard_visual_style_text(meta: dict[str, Any], config: dict[str, Any]) -> str:
    style_config = config.get("style") if isinstance(config.get("style"), dict) else {}
    style_prompt = _storyboard_visual_style_prompt_text(
        style_config.get("prompt") or meta.get("style_prompt")
    )
    if style_prompt:
        return _compact_text(style_prompt, 1400)
    return "沿用当前项目已配置的视觉风格、画面质感、光影、色彩和统一美术方向。"


def _storyboard_asset_prompt_block(manifest_prompt: str = "") -> str:
    lines = ["【资产引用提示词】"]
    if manifest_prompt:
        lines.append(manifest_prompt)
        lines.append("资产引用只提供已绑定图片和名称关系，不负责改变剧情内容，也不负责决定故事版版式；具体用途以分镜脚本和资产引用清单为准，用户本轮要求只在不改变分镜脚本时作为呈现偏好。")
        lines.append("当前剧情明确的年龄、人生阶段和临时外观状态优先于参考资产的历史外观；参考图只锁定仍需延续的身份特征，不得把当前角色改回其他年龄或阶段。")
        lines.append("已绑定角色、生物、场景、道具参考图只约束对应资产本身；分镜脚本中需要入画但未绑定的对象，按计划已确定的身份、外观与状态呈现，不得套用绑定角色的脸、发型、服装、体态或道具外观。")
        lines.append("当已绑定角色正在观看、谈论、感知或操作某个未绑定的间接对象、媒介对象或异空间对象时，画面必须区分当前角色与被观察/被呈现对象；参考图中的身份只属于绑定对象。")
    else:
        lines.append("本次没有已绑定图片资产时，只依据分镜脚本和项目风格生成；不要臆造资产绑定或把临时对象误当作已有资产。")
    return "\n".join(lines)


def _storyboard_single_panel_template_rules(value: Any) -> str:
    return storyboard_template_single_panel_prompt_rules(value)


def _storyboard_single_panel_layout_block(
    storyboard_render_spec: dict[str, Any] | None = None,
) -> str:
    render_spec = storyboard_render_spec if isinstance(storyboard_render_spec, dict) else {}
    sheet_spec = render_spec.get("sheet") if isinstance(render_spec.get("sheet"), dict) else {}
    target_video_spec = (
        render_spec.get("targetVideo")
        if isinstance(render_spec.get("targetVideo"), dict)
        else {}
    )
    aspect_ratio = str(target_video_spec.get("aspectRatio") or "16:9")
    orientation_label = str(target_video_spec.get("orientationLabel") or "横屏")
    language = target_video_spec.get("language") if isinstance(target_video_spec.get("language"), dict) else {}
    return (
        f"正式镜头画格：{orientation_label} {aspect_ratio}；比例来自项目配置，必须按该完整安全画框构图。"
        f"整张分镜工作页参考比例：{sheet_spec.get('aspectRatio') or aspect_ratio}；辅助区域按所选版式保留。"
        f"{_storyboard_target_frame_composition_note(target_video_spec)}"
        f"项目语言：{language.get('label') or '简体中文'}（{language.get('code') or 'zh-CN'}）；"
        f"{language.get('instruction') or '所有模型生成的画面短标签使用简体中文，禁止无原文依据的中英混写。'}"
        "只生成一个正式镜头画格；整张工作页的辅助区域按所选版式保留。"
    )


def _storyboard_prompt_with_reference_manifest(prompt: str, manifest_prompt: str) -> str:
    if not manifest_prompt:
        return prompt
    asset_block = _storyboard_asset_prompt_block(manifest_prompt)
    asset_marker = "【资产引用提示词】"
    if asset_marker in prompt:
        return re.sub(
            r"【资产引用提示词】.*?(?=\n\n【|\Z)",
            lambda _match: asset_block,
            prompt,
            count=1,
            flags=re.DOTALL,
        )
    if manifest_prompt in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n{asset_block}"


def _storyboard_spatial_reference_prompt(
    reference_manifest: list[dict[str, Any]],
    storyboard_template: str = "",
) -> str:
    rows = [row for row in reference_manifest if isinstance(row, dict)]
    scene_rows = [
        row
        for row in rows
        if str(row.get("slot") or "").strip() == "scene_reference"
    ]
    handoff_rows = [
        row
        for row in rows
        if str(row.get("slot") or "").strip() == _VISUAL_HANDOFF_SLOT
    ]
    if not scene_rows and not handoff_rows:
        return ""

    def display_names(source_rows: list[dict[str, Any]], label: str) -> str:
        return "、".join(
            f"{label}{index}"
            for index, _row in enumerate(source_rows[:3], start=1)
        )

    scene_names = display_names(scene_rows, "场景参考图")
    handoff_names = display_names(handoff_rows, "视觉交接参考图")
    lines = ["【空间参考使用规则】"]
    if scene_rows and handoff_rows:
        lines.append(
            f"本次同时提供当前场景参考图（{scene_names or '场景参考图'}）和视觉交接参考图（{handoff_names or '视觉交接参考图'}）。当前场景参考图是空间骨架主依据，视觉交接参考图只作为前序结尾状态的连续性辅助。"
        )
        lines.append(
            "生成主要镜头画格时，当前空间/场景的整体边界、主要结构、当前场景参考图中已确认的空间开口（如门、通道）、动线、固定地貌或固定陈设、关键空间锚点、尺度比例、相对间距、光源方向和环境材质以当前场景参考图为准；人物/道具在连续时间内的位置、朝向、视线和终态可参考视觉交接图。"
        )
        lines.append(
            "若当前剧情承接同一场景、同一行动线或连续时间，本次第一个有效镜头延续视觉交接参考图中已确定的人物/道具位置、朝向、视线和终态；只能在分镜脚本允许范围内更换机位、景别和构图。"
        )
        lines.append(
            "若当前剧情明确换场、跳时、进入新空间或开启新的叙事段落，不强行延续视觉交接参考图；视觉交接参考图不得新增剧情或改写分镜脚本。"
        )
        lines.append(
            "这些空间关系应按当前分镜图版式规则呈现在主要镜头画格或版式要求的空间表达区域中；空间参考只决定依据来源，不改写版式规则。"
        )
    elif scene_rows:
        lines.append(
            f"本次提供当前场景参考图（{scene_names or '场景参考图'}）。当前空间/场景的整体边界、主要结构、当前场景参考图中已确认的空间开口（如门、通道）、动线、固定地貌或固定陈设、关键空间锚点、尺度比例、相对间距、光源方向和环境材质以当前场景参考图为主。"
        )
        lines.append(
            "这些空间关系应按当前分镜图版式规则呈现在主要镜头画格或版式要求的空间表达区域中；空间参考只决定依据来源，不改写版式规则。"
        )
    else:
        lines.append(
            f"本次没有当前场景参考图，但提供视觉交接参考图（{handoff_names or '视觉交接参考图'}）。只有当前剧情承接同一场景、同一行动线或连续时间时，才使用视觉交接参考图理解当前所在空间、人物/道具位置、朝向和终态。"
        )
        lines.append(
            "若当前剧情承接，本次第一个有效镜头延续视觉交接参考图中已确定的位置、朝向、视线和终态；若剧情明确换场或跳时，则不强行延续。视觉交接参考图不得新增剧情或改写分镜脚本。"
        )
        lines.append(
            "这些连续性关系应按当前分镜图版式规则呈现；空间参考只决定依据来源，不改写版式规则。"
        )
    return "\n".join(lines)


def _storyboard_prompt_with_spatial_reference(prompt: str, spatial_prompt: str) -> str:
    spatial_prompt = str(spatial_prompt or "").strip()
    if not spatial_prompt or spatial_prompt in prompt:
        return prompt
    if "【空间参考使用规则】" in prompt:
        return prompt
    for marker in ("【分镜图版式规则】", "【故事版模板规则】"):
        if marker in prompt:
            return prompt.replace(marker, f"{spatial_prompt}\n\n{marker}", 1)
    return f"{prompt.rstrip()}\n\n{spatial_prompt}"


_STORYBOARD_DIRECTOR_INPUT_RULES = (
    "【分镜脚本使用方式】\n"
    "只绘制每镜 storyboardFrame 指定的起始关键画面，所有画格沿用统一项目视觉；"
    "每个镜头画格保持项目横屏或竖屏方向，具体构图以该镜起始画面为准。"
    "手机拍摄、屏幕播放等素材来源的横竖比例不强制成为整格的画幅或镜头视角；"
    "起始画面写独立场景就绘制该场景，写人物观看设备才绘制人物与设备。"
    "画格的具体排法由图片模型在本次版式规则和禁止条件内决定。"
    "场景内文字仅在起始帧实际可见时绘入载体。"
    "动作终态、声音原话、原文和剧情说明不属于本次图片指令。"
)


def _storyboard_director_panel_details(panel: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    action = _panel_action_text(panel)
    if action:
        lines.append(f"起始画格：{action}")
    presentation = panel.get("presentation") if isinstance(panel.get("presentation"), dict) else {}
    preset = storyboard_presentation_effect_preset(presentation)
    if preset:
        lines.append("仅本画格的类型效果：" + preset + " 不把此效果加到同组其他画格。")
    event_label = presentation.get("eventLabel")
    if isinstance(event_label, dict) and event_label.get("visibleAtStart") is True:
        content = _normalize_multiline_text(event_label.get("content"))
        if content:
            lines.append(f"本镜起点可见的事件短标识：{content}；只放本画格，不添加其他装饰字卡。")
    screen_text_lines: list[str] = []
    for event in panel.get("screenTextEvents") if isinstance(panel.get("screenTextEvents"), list) else []:
        if not isinstance(event, dict):
            continue
        if event.get("visibleAtStart") is not True:
            continue
        medium = _normalize_multiline_text(event.get("medium"))
        content = _normalize_multiline_text(event.get("content"))
        if medium and content:
            screen_text_lines.append(f"- {medium}：{content}")
    if screen_text_lines:
        lines.append("起始可见的场景载体文字（保留来源和相关意思，字形无需逐字准确）：\n" + "\n".join(screen_text_lines))
    return lines


def _storyboard_sheet_prompt(
    episode_title: str,
    panels: list[dict[str, Any]],
    raw_panel_prompts: list[str],
    storyboard_template: str = "",
    *,
    visual_style_text: str = "",
    story_context_text: str = "",
    asset_manifest_prompt: str = "",
    storyboard_render_spec: dict[str, Any] | None = None,
) -> str:
    panel_count = len(panels)
    template_id = storyboard_template_id(storyboard_template)
    if template_id == "narrative_storyboard":
        target_line = (
            f"根据本次提供的分镜脚本和叙事故事版规则生成一张完整的叙事故事版分镜图；"
            f"分镜脚本对应 {panel_count} 个有序主要镜头画格，整张工作页同时包含叙事故事版规则要求的右侧独立辅助视觉窄栏。"
        )
    elif template_id == "blocking_storyboard":
        target_line = (
            f"根据本次提供的分镜脚本和调度故事版规则生成一张完整的调度故事版分镜图；"
            f"分镜脚本对应 {panel_count} 个有序主要镜头画格，整张工作页同时包含调度故事版规则要求的下方独立辅助调度条。"
        )
    elif template_id == "image_grid_storyboard":
        target_line = f"根据本次提供的分镜脚本和镜头画格宫格规则生成一张完整的镜头画格宫格分镜图；画面由 {panel_count} 个有序主要镜头画格组成。"
    elif template_id == "numbered_grid_storyboard":
        target_line = f"根据本次提供的分镜脚本和编号宫格规则生成一张完整的编号宫格分镜图；画面由 {panel_count} 个有序主要镜头画格组成。"
    elif template_id == "filmstrip_storyboard":
        target_line = f"根据本次提供的分镜脚本和胶片条故事版规则生成一张完整的胶片条故事版分镜图；画面由 {panel_count} 个有序主要镜头画格组成。"
    else:
        template_label = storyboard_template_label(template_id)
        target_line = f"根据本次提供的分镜脚本，按照「{template_label}」版式生成一张完整的分镜图；分镜脚本对应 {panel_count} 个有序主要镜头画格，整张工作页的版式组成以当前分镜图版式规则为准。"
    visual_style_text = str(visual_style_text or "").strip()
    story_context_text = str(story_context_text or "").strip()
    target_video = (
        storyboard_render_spec.get("targetVideo")
        if isinstance(storyboard_render_spec, dict)
        and isinstance(storyboard_render_spec.get("targetVideo"), dict)
        else {}
    )
    arrangement_rules = storyboard_panel_arrangement_rules(
        template_id, panel_count, target_video.get("orientation") or "landscape",
    )
    panel_lines: list[str] = []
    for index, panel in enumerate(panels, start=1):
        title = _panel_title(panel, index - 1)
        detail_parts = [f"{index}. {title}"]
        detail_parts.extend(_storyboard_director_panel_details(panel))
        panel_lines.append("\n".join(detail_parts))
    panel_block = "\n\n".join(panel_lines)
    shot_contract = (
        f"分镜脚本共 {panel_count} 个镜头，必须生成且只生成 {panel_count} 个主要镜头画格；"
        "每个镜头对应且只对应一个画格，画格数量和顺序与分镜脚本一致；镜头编号仅用于对应输入，图中是否显示编号由所选版式决定。"
        "该数量只约束主要镜头画格，版式规则要求的其他版面组成属于整张工作页的版式组成。"
        "每格只绘制对应镜头的起始画面，不读取镜内执行和镜长；版式规则只决定画格布局与版式标注。"
    )
    overall_generation_logic = (
        f"本次工作页的核心内容是 {panel_count} 个主要镜头画格；"
        "每个主要镜头画格必须优先准确呈现分镜脚本中的主体、构图、站位、关键动作、情绪落点和画面信息。"
        "完整工作页还必须按当前分镜图版式规则呈现对应的版面组成与版式元素。"
    )
    sections = [
        f"【生成目标与硬性合同】\n{target_line}",
        f"【整体生成逻辑】\n{overall_generation_logic}",
        _STORYBOARD_DIRECTOR_INPUT_RULES,
        f"【分镜脚本（唯一镜头合同）】\n{panel_block}\n\n{shot_contract}",
        _storyboard_asset_prompt_block(asset_manifest_prompt),
        *([f"【项目视觉风格与连续性】\n{visual_style_text}\n该部分只约束画面风格、质感、光影、色彩和跨镜头一致性，不得改变分镜脚本。"] if visual_style_text else []),
        f"【分镜图版式规则】\n{storyboard_template_prompt_rules(template_id)}",
        *([f"【本组镜头排列】\n{arrangement_rules}"] if arrangement_rules else []),
        f"【画布与输出规格】\n{_storyboard_template_layout_block(template_id, storyboard_render_spec)}",
        "【画面标注与清洁约束】\n画内文字仅绘制起始时已可见的场景载体信息和正式分镜确定的特殊事件短标识，字形无需逐字准确；版式编号、箭头和图示仅按所选版式执行，不额外生成人物介绍等通用装饰。主要镜头画格保持足够面积。",
        f"【最终生成指令】\n生成一张完整分镜图，其中分镜脚本对应 {panel_count} 个有序主要镜头画格，每个镜头对应且只对应一个主要画格；当前版式规则要求的其他版面组成也必须作为整张工作页的一部分呈现。分镜脚本的起始画面是各画格唯一剧情画面依据，资产只用于身份和外观参考，分镜图版式规则负责布局和必要版式标注。直接输出最终分镜图，不输出提示词或 JSON。执行优先级：项目画幅/语言/安全合同 > 分镜脚本起始画面 > 如有空间参考使用规则 > 资产身份与参考图外观 > 分镜图版式规则 > 项目视觉风格 > 用户补充中不改变分镜脚本的呈现偏好。若用户补充会改变镜头数量、顺序、构图、站位或起始画面，不得在本环节执行，应先更新分镜脚本。参考资产不得新增剧情。",
    ]
    return "\n\n".join(section for section in sections if section)


def _storyboard_single_panel_prompt(
    episode_title: str,
    panel: dict[str, Any],
    raw_panel_prompt: str,
    panel_index: int,
    storyboard_template: str = "",
    *,
    visual_style_text: str = "",
    story_context_text: str = "",
    asset_manifest_prompt: str = "",
    storyboard_render_spec: dict[str, Any] | None = None,
) -> str:
    # One shot still produces a complete sheet under the selected template.
    return _storyboard_sheet_prompt(
        episode_title, [panel], [raw_panel_prompt], storyboard_template,
        visual_style_text=visual_style_text,
        story_context_text=story_context_text,
        asset_manifest_prompt=asset_manifest_prompt,
        storyboard_render_spec=storyboard_render_spec,
    )


def _humanize_internal_asset_ids(project_id: str, text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    try:
        rows_by_type, _token_to_id = _project_asset_binding_index(project_id, None)
    except Exception:
        return value
    replacements: list[tuple[str, str]] = []
    for rows in rows_by_type.values() if isinstance(rows_by_type, dict) else []:
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            asset_id = str(row.get("assetId") or "").strip()
            display_name = str(row.get("displayName") or "").strip()
            if asset_id and display_name and asset_id != display_name:
                replacements.append((asset_id, display_name))
    for asset_id, display_name in sorted(dict(replacements).items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(asset_id)}(?![A-Za-z0-9_-])")
        value = pattern.sub(display_name, value)
    return value


def _storyboard_local_asset_ref_tokens(source: Any, *, include_plain_strings: bool) -> list[str]:
    tokens: dict[str, str] = {}
    id_keys = {"assetId", "asset_id", "assetID", "id"}

    def add(value: Any) -> None:
        token = str(value or "").strip()
        if token:
            tokens.setdefault(token.casefold(), token)

    stack = [source]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key in id_keys:
                add(current.get(key))
            stack.extend(value for value in current.values() if isinstance(value, (dict, list)))
        elif isinstance(current, list):
            stack.extend(current)
        elif include_plain_strings and isinstance(current, str):
            add(current)
    return list(tokens.values())


def _storyboard_local_asset_mention_labels(project_id: str, payload: dict[str, Any]) -> list[str]:
    labels: dict[str, str] = {}

    def add(value: Any) -> None:
        label = str(value or "").strip()
        if label:
            labels.setdefault(label.casefold(), label)

    label_keys = {"name", "title", "displayName", "display_name", "assetName", "asset_name", "label"}

    def collect_labels(source: Any, *, allow_plain_strings: bool) -> None:
        stack = [source]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                for key in label_keys:
                    add(current.get(key))
                stack.extend(
                    value
                    for key, value in current.items()
                    if key not in label_keys and isinstance(value, (dict, list))
                )
            elif isinstance(current, list):
                stack.extend(current)
            elif allow_plain_strings and isinstance(current, str):
                add(current)

    asset_ref_tokens: dict[str, str] = {}
    for token in (
        *_storyboard_local_asset_ref_tokens(payload.get("assetRefs"), include_plain_strings=True),
        *_storyboard_local_asset_ref_tokens(payload.get("asset_refs"), include_plain_strings=True),
        *_storyboard_local_asset_ref_tokens(payload.get("referenceManifest"), include_plain_strings=False),
        *_storyboard_local_asset_ref_tokens(payload.get("reference_manifest"), include_plain_strings=False),
    ):
        asset_ref_tokens.setdefault(token.casefold(), token)

    collect_labels(payload.get("referenceManifest"), allow_plain_strings=True)
    collect_labels(payload.get("reference_manifest"), allow_plain_strings=True)
    collect_labels(payload.get("assetRefs"), allow_plain_strings=True)
    collect_labels(payload.get("asset_refs"), allow_plain_strings=True)
    try:
        rows_by_type, token_to_id = _project_asset_binding_index(project_id, None)
    except Exception:
        rows_by_type = {}
        token_to_id = {}
    allowed_asset_ids = set(asset_ref_tokens)
    for token_key in list(asset_ref_tokens):
        for collection in token_to_id.values() if isinstance(token_to_id, dict) else []:
            if not isinstance(collection, dict):
                continue
            asset_id = str(collection.get(token_key) or "").strip()
            if asset_id:
                allowed_asset_ids.add(asset_id.casefold())
    for rows in rows_by_type.values() if isinstance(rows_by_type, dict) else []:
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            asset_id = str(row.get("assetId") or "").strip()
            if asset_id.casefold() not in allowed_asset_ids:
                continue
            add(row.get("displayName"))
            for alias in row.get("aliases") or []:
                add(alias)
    return list(labels.values())


def _normalize_storyboard_local_asset_mentions(
    project_id: str,
    prompt: Any,
    payload: dict[str, Any],
    *,
    context_label: str,
) -> tuple[str, dict[str, Any]]:
    labels = _storyboard_local_asset_mention_labels(project_id, payload)
    normalized, meta = replace_known_local_asset_mentions(
        _humanize_internal_asset_ids(project_id, str(prompt or "")),
        labels,
        context_label=context_label,
        error_type=ValueError,
    )
    return _humanize_internal_asset_ids(project_id, normalized), meta


def _selected_storyboard_panel_for_node(
    current_data: dict[str, Any],
    panels: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, int]:
    panel_value = current_data.get("panel")
    if isinstance(panel_value, dict):
        explicit_index = _duration_seconds_value(current_data.get("panelIndex") or current_data.get("shotIndex"))
        return copy.deepcopy(panel_value), max(0, (explicit_index or 1) - 1)
    for key in ("panelIndex", "shotIndex", "panel_index", "shot_index"):
        try:
            index = int(current_data.get(key) or 0)
        except (TypeError, ValueError):
            index = 0
        if index > 0 and index <= len(panels):
            return copy.deepcopy(panels[index - 1]), index - 1
    shot_ids = _string_list(current_data.get("shotIds") or current_data.get("shot_ids"))
    if len(shot_ids) == 1:
        shot_id = shot_ids[0]
        for index, panel in enumerate(panels):
            if str(panel.get("id") or panel.get("shotId") or panel.get("shot_id") or "").strip() == shot_id:
                return copy.deepcopy(panel), index
    if panels:
        return copy.deepcopy(panels[0]), 0
    return None, 0


def _storyboard_layout_content_presence(
    task_card_data: dict[str, Any],
    current_story_text: str,
) -> dict[str, list[str]]:
    """Resolve entities from the current task card without reading stale shot-plan state."""
    data = task_card_data if isinstance(task_card_data, dict) else {}
    presence: dict[str, list[str]] = {"characters": [], "creatures": [], "scenes": [], "props": []}

    def append(collection: str, value: Any) -> None:
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = str(item or "").strip()
            if text and text not in presence[collection]:
                presence[collection].append(text)

    normalized_story_text = re.sub(
        r"\s+",
        " ",
        str(current_story_text or "").replace("@", "").replace("＠", ""),
    ).strip()
    current_hash = hashlib.sha256(normalized_story_text.encode("utf-8")).hexdigest()
    analysis_hash = str(
        data.get("storyboardAnalysisStoryTextHash")
        or data.get("storyboard_analysis_story_text_hash")
        or ""
    ).strip()
    analysis = data.get("storyboardAnalysis") if isinstance(data.get("storyboardAnalysis"), dict) else {}
    if analysis_hash and analysis_hash == current_hash:
        append("characters", analysis.get("characters"))
        append("creatures", analysis.get("creatures"))
        append("scenes", analysis.get("scene") or analysis.get("scenes"))
        append("props", analysis.get("props"))
    missing_rows = data.get("missingAssetRefs") if isinstance(data.get("missingAssetRefs"), list) else []
    for row in missing_rows:
        if not isinstance(row, dict):
            continue
        asset_type = str(row.get("assetType") or row.get("asset_type") or "").strip().lower()
        collection = {
            "character": "characters",
            "characters": "characters",
            "creature": "creatures",
            "creatures": "creatures",
            "monster": "creatures",
            "monsters": "creatures",
            "beast": "creatures",
            "beasts": "creatures",
            "scene": "scenes",
            "scenes": "scenes",
            "prop": "props",
            "props": "props",
        }.get(asset_type)
        if collection:
            append(collection, row.get("token") or row.get("name"))
    return presence


def _workflow_director_context_payload(
    workflow: dict[str, Any],
    current_node: dict[str, Any] | None,
) -> dict[str, Any]:
    director_node = _workflow_director_board_for_context(workflow, current_node)
    if not isinstance(director_node, dict):
        return {}
    data = director_node.get("data") if isinstance(director_node.get("data"), dict) else {}
    card = (
        data.get("directorTaskCard")
        if isinstance(data.get("directorTaskCard"), dict)
        else {}
    )
    analysis = data.get("storyboardAnalysis") if isinstance(data.get("storyboardAnalysis"), dict) else {}
    director_plan = card_text(data, "directorPlan")
    director_plan_shots = copy.deepcopy(
        data.get("directorPlanShots")
        if isinstance(data.get("directorPlanShots"), list)
        else []
    )
    speaker_roster = copy.deepcopy(
        data.get("speakerRoster")
        if isinstance(data.get("speakerRoster"), list)
        else []
    )
    director_rule_id = _normalize_director_rule_id(
        card_text(data, "directorRuleId"),
        source_label="分镜脚本使用的导演规则",
    )
    template_value = data.get("storyboardTemplate")
    template_id = storyboard_template_id(template_value)
    context = {
        "directorBoardNodeId": str(director_node.get("id") or "").strip(),
        "directorPlan": director_plan,
        "directorPlanShots": director_plan_shots,
        "speakerRoster": speaker_roster,
        "directorRuleId": director_rule_id,
        "storyboardTemplate": template_id,
        "storyboardTemplateLabel": storyboard_template_label(template_id),
        "directorTaskCard": copy.deepcopy(card),
        "storyboardAnalysis": copy.deepcopy(analysis),
    }
    duration_seconds = _workflow_timing_number(data.get("durationSeconds"))
    if duration_seconds and duration_seconds > 0:
        context["durationSeconds"] = _workflow_clean_seconds(float(duration_seconds))
    return {key: value for key, value in context.items() if value not in ("", [], {})}


def _storyboard_interpretation_contract_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    panels = payload.get("panels") if isinstance(payload.get("panels"), list) else []
    shot_order: list[dict[str, Any]] = []
    timing_rows: list[dict[str, Any]] = []
    running = 0.0
    for index, panel in enumerate(panels, start=1):
        if not isinstance(panel, dict):
            continue
        shot_label = str(panel.get("shotLabel") or panel.get("shot_label") or f"Shot {index:02d}").strip()
        duration = _workflow_timing_number(
            panel.get("durationSeconds") or panel.get("duration_seconds") or panel.get("duration")
        )
        start_second = _workflow_timing_number(panel.get("startSecond") or panel.get("start_second"))
        end_second = _workflow_timing_number(panel.get("endSecond") or panel.get("end_second"))
        if start_second is None and duration and duration > 0:
            start_second = running
        if end_second is None and start_second is not None and duration and duration > 0:
            end_second = start_second + duration
        row: dict[str, Any] = {
            "shotLabel": shot_label,
            "shotId": str(panel.get("id") or panel.get("shotId") or panel.get("shot_id") or "").strip(),
            "title": _panel_title(panel, index - 1),
            "visibleAction": _panel_action_text(panel),
            "storyboardFrame": _panel_action_text(panel),
        }
        presentation = panel.get("presentation") if isinstance(panel.get("presentation"), dict) else {}
        effect_preset = storyboard_presentation_effect_preset(presentation)
        if effect_preset:
            row["typeEffectPreset"] = effect_preset
        if start_second is not None and end_second is not None and end_second > start_second:
            duration = end_second - start_second
            running = end_second
            timing_row = {
                "shotLabel": shot_label,
                "durationSeconds": _workflow_clean_seconds(float(duration)),
                "startSecond": _workflow_clean_seconds(float(start_second)),
                "endSecond": _workflow_clean_seconds(float(end_second)),
            }
            timing_rows.append(timing_row)
            row.update(copy.deepcopy(timing_row))
        shot_order.append(row)
    panel_count = int(payload.get("panelCount") or len(shot_order) or 0)
    duration_seconds = _workflow_clean_seconds(float(timing_rows[-1].get("endSecond") or 0)) if timing_rows else None
    manifest = payload.get("referenceManifest") if isinstance(payload.get("referenceManifest"), list) else []
    asset_bindings: list[dict[str, Any]] = []
    for item in manifest:
        if not isinstance(item, dict):
            continue
        visual_id = str(item.get("visualId") or item.get("visual_id") or "").strip().upper()
        asset_id = str(item.get("assetId") or item.get("asset_id") or "").strip()
        media_id = str(item.get("mediaId") or item.get("media_id") or "").strip()
        if not visual_id and not asset_id and not media_id:
            continue
        asset_bindings.append(
            {
                "visualId": visual_id,
                "assetType": str(item.get("assetType") or item.get("asset_type") or "").strip(),
                "displayName": str(item.get("displayName") or item.get("label") or "").strip(),
                "assetId": asset_id,
                "mediaId": media_id,
            }
        )
    validation_passed = bool(shot_order) and (not panel_count or panel_count == len(shot_order))
    contract: dict[str, Any] = {
        "schemaVersion": 1,
        "source": "storyboard_generation_payload_binding_validation",
        "visualReadback": False,
        "storyboardVersionId": "",
        "storyboardNodeId": str(payload.get("nodeId") or payload.get("storyboardNodeId") or "").strip(),
        "panelCount": panel_count,
        "shotOrder": shot_order,
        "durationSeconds": duration_seconds,
        "shotTimingPlan": (
            {
                "schemaVersion": 1,
                "durationSeconds": duration_seconds,
                "shotCount": len(timing_rows),
                "shots": copy.deepcopy(timing_rows),
                "source": "storyboard_generation_payload_binding_validation",
                "scope": "work_chain",
            }
            if duration_seconds and len(timing_rows) == len(shot_order)
            else {}
        ),
        "assetBindings": asset_bindings,
        "bindingValidation": {
            "passed": validation_passed,
            "source": "storyboard_generation_payload",
            "message": (
                "镜头顺序与分镜面板数量一致。"
                if validation_passed
                else "分镜图缺少可用镜头顺序或面板数量不一致。"
            ),
        },
    }
    return contract if shot_order else {}


def _storyboard_prompt_payload(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_id: str | None = None,
) -> dict[str, Any]:
    meta = _read_json(_project_meta_path(project_id), {})
    current_node = _workflow_node(workflow, str(node_id or "")) or {}
    work_chain_id = _workflow_node_work_chain_id(workflow, current_node) or None
    chain = next((row for row in workflow.get("workChains", []) if row.get("id") == work_chain_id), None)
    origin = work_chain_origin(chain, workflow) if chain else {}
    is_independent = origin.get("kind") in {"independent", "independent_source"}
    episode = next(
        (
            item
            for item in meta.get("episodes", [])
            if isinstance(item, dict) and str(item.get("id")) == episode_id
        ),
        {},
    )
    episode_title = str((chain or {}).get("label") or "独立工作链") if is_independent else str(episode.get("title") or episode_id)
    config = get_effective_config(project_id)
    visual_style_text = _storyboard_visual_style_text(meta, config)
    story_context_text = ""
    episode_source_ref = {}
    if not is_independent:
        story_world = _read_json(_project_dir(project_id) / "story_world.json", {})
        story_context_text = _storyboard_story_context_text(meta, story_world)
        source_ref_path = _episode_source_ref_path(project_id, episode_id)
        episode_source_ref = _read_json(source_ref_path, {}) if source_ref_path.exists() else {}
    current_data = current_node.get("data") if isinstance(current_node.get("data"), dict) else {}
    director_context = _workflow_director_context_payload(workflow, current_node)
    route_id = str(current_node.get("routeId") or current_data.get("routeId") or "").strip() or None
    context_provenance = (
        workflow.get("contextProvenance")
        if not is_independent and isinstance(workflow.get("contextProvenance"), dict)
        else None
    )
    script_node = work_chain_stage_node(workflow, current_node, "prompt.storyboard")
    prompt_data = script_node.get("data", {}) if script_node else {}
    prompt_card_state = (
        prompt_data.get("cardState")
        if isinstance(prompt_data.get("cardState"), dict)
        else {}
    )
    director_plan_text = _normalize_multiline_text(director_context.get("directorPlan"))
    if not director_plan_text:
        raise ValueError("当前工作链缺少分镜脚本，请先生成或填写后再生成分镜图。")
    director_plan_shots = _director_plan_shot_rows_from_structured(
        director_context.get("directorPlanShots"),
    )
    if not director_plan_shots:
        raise ValueError(
            "当前分镜脚本缺少结构化镜头合同，请重新生成或保存分镜脚本后再生成分镜图。"
        )
    raw_director_shots = director_context.get("directorPlanShots") if isinstance(director_context.get("directorPlanShots"), list) else []
    panels = [
        {**copy.deepcopy(item), "durationSeconds": raw_director_shots[index].get("durationSec")}
        for index, item in enumerate(director_plan_shots)
    ]
    raw_prompts = [_panel_prompt(panel, index) for index, panel in enumerate(panels)]
    user_story_text = script_source_text(prompt_data)
    node_type = str(current_node.get("type") or "").strip()
    assigned_shot_nos = current_data.get("shotNos") if isinstance(current_data.get("shotNos"), list) else []
    if (
        node_type == "storyboard.image"
        and work_chain_id
        and not assigned_shot_nos
    ):
        raise ValueError("当前分镜图尚未分配镜头，请先在分镜脚本中保存修改")
    if assigned_shot_nos and node_type in {"storyboard.image", "video.storyboard", "video.keyframe"}:
        from .storyboard_allocation import director_shots_hash

        director_node = _workflow_director_board_for_context(workflow, current_node)
        director_data = director_node.get("data") if isinstance((director_node or {}).get("data"), dict) else {}
        allocation = director_data.get("storyboardAllocation") if isinstance(director_data.get("storyboardAllocation"), dict) else {}
        live_director_shots = director_data.get("directorPlanShots") if isinstance(director_data.get("directorPlanShots"), list) else []
        if allocation.get("directorPlanHash") != director_shots_hash(live_director_shots):
            raise ValueError("分镜脚本已变化，请先保存修改")
        group_id = str(current_data.get("shotGroupId") or "")
        group = next(
            (row for row in allocation.get("groups") or [] if isinstance(row, dict) and row.get("id") == group_id),
            None,
        )
        if not group_id or not group or group.get("shotNos") != assigned_shot_nos:
            raise ValueError("当前分镜图与分镜脚本的镜头分配不一致，请保存修改")
        if any(not isinstance(value, int) or value < 1 or value > len(panels) for value in assigned_shot_nos):
            raise ValueError("分镜分配包含无效镜头，请重新保存分镜分配")
        panels_for_node = [panels[number - 1] for number in assigned_shot_nos]
        prompts_for_node = [raw_prompts[number - 1] for number in assigned_shot_nos]
    else:
        panels_for_node = panels
        prompts_for_node = raw_prompts
    if assigned_shot_nos and node_type in {"storyboard.image", "video.storyboard", "video.keyframe"} and director_context:
        from .director_plan_contract import speaker_roster_for_shots

        director_context["speakerRoster"] = speaker_roster_for_shots(
            director_context.get("speakerRoster") or [],
            [raw_director_shots[number - 1] for number in assigned_shot_nos],
        )
    current_card_state = current_data.get("cardState") if isinstance(current_data.get("cardState"), dict) else {}
    storyboard_card = _workflow_node(
        workflow,
        str(current_data.get("sourceNodeId") or ""),
    ) if node_type == "storyboard.image" else None
    storyboard_card_data = storyboard_card.get("data") if isinstance(storyboard_card, dict) and storyboard_card.get("type") == "storyboard.card" else {}
    storyboard_card_data = storyboard_card_data if isinstance(storyboard_card_data, dict) else {}
    storyboard_card_state = storyboard_card_data.get("cardState") if isinstance(storyboard_card_data.get("cardState"), dict) else {}
    storyboard_template = storyboard_template_id(
        storyboard_card_data.get("storyboardTemplate")
        or storyboard_card_state.get("template")
        or director_context.get("storyboardTemplate")
        or prompt_data.get("storyboardTemplate")
        or prompt_data.get("storyboard_template")
        or prompt_card_state.get("template")
        or current_data.get("storyboardTemplate")
        or current_data.get("storyboard_template")
        or current_card_state.get("template")
    )
    template_layout_spec = storyboard_template_layout_spec(storyboard_template)
    storyboard_render_spec = build_storyboard_render_spec(
        config,
        template_layout_spec,
        main_panel_count=len(panels_for_node),
        builtin_template=storyboard_template_layout_kind(storyboard_template) != "custom",
        template_id=storyboard_template,
    )
    production_spec = build_project_production_spec(config)
    has_explicit_panel = isinstance(current_data.get("panel"), dict) and bool(current_data.get("panel"))
    has_explicit_panel_index = any(
        str(current_data.get(key) or "").strip()
        for key in ("panelIndex", "shotIndex", "panel_index", "shot_index")
    )
    is_single_panel_image_node = (
        node_type == "storyboard.image"
        and len(assigned_shot_nos) <= 1
        and (has_explicit_panel or has_explicit_panel_index)
    )
    payload_panels = panels_for_node
    payload_raw_prompts = prompts_for_node
    storyboard_format = "storyboard_panel_sequence"
    selected_panel_index: int | None = None
    if is_single_panel_image_node:
        if assigned_shot_nos:
            selected_index = assigned_shot_nos[0] - 1
            selected_panel = copy.deepcopy(panels_for_node[0])
        else:
            selected_panel, selected_index = _selected_storyboard_panel_for_node(current_data, panels)
        if selected_panel:
            selected_panel_index = selected_index
            payload_panels = [selected_panel]
            payload_raw_prompts = [_panel_prompt(selected_panel, selected_index)]
            storyboard_render_spec = build_storyboard_render_spec(
                config, template_layout_spec, main_panel_count=1,
                builtin_template=storyboard_template_layout_kind(storyboard_template) != "custom",
                template_id=storyboard_template,
            )
            storyboard_prompt_raw = _storyboard_single_panel_prompt(
                episode_title,
                selected_panel,
                payload_raw_prompts[0],
                selected_index,
                storyboard_template,
                visual_style_text=visual_style_text,
                story_context_text=story_context_text,
                storyboard_render_spec=storyboard_render_spec,
            )
        else:
            storyboard_prompt_raw = _storyboard_sheet_prompt(
                episode_title,
                panels_for_node,
                prompts_for_node,
                storyboard_template,
                visual_style_text=visual_style_text,
                story_context_text=story_context_text,
                storyboard_render_spec=storyboard_render_spec,
            )
    else:
        storyboard_prompt_raw = _storyboard_sheet_prompt(
            episode_title,
            panels_for_node,
            prompts_for_node,
            storyboard_template,
            visual_style_text=visual_style_text,
            story_context_text=story_context_text,
            storyboard_render_spec=storyboard_render_spec,
        )
    shot_timing_plan = _storyboard_panels_shot_timing_plan(payload_panels)
    duration_seconds = (
        _workflow_shot_timing_plan_duration(shot_timing_plan)
        or _workflow_timing_number(director_context.get("durationSeconds"))
        or _storyboard_panels_duration_seconds(payload_panels)
    )
    storyboard_prompt_raw = _humanize_internal_asset_ids(
        project_id,
        str(storyboard_prompt_raw or "").strip(),
    )
    storyboard_prompt = storyboard_prompt_raw
    payload = {
        "episodeId": episode_id,
        "episodeTitle": episode_title,
        "sourceRef": episode_source_ref if isinstance(episode_source_ref, dict) else {},
        "panelCount": len(payload_panels),
        "routePanelCount": len(panels),
        "panels": payload_panels,
        "durationSeconds": duration_seconds,
        "shotTimingPlan": copy.deepcopy(shot_timing_plan),
        "storyboardImagePrompt": storyboard_prompt,
        "storyboardImagePromptRaw": storyboard_prompt_raw,
        "userStoryText": user_story_text,
        "projectStylePrompt": visual_style_text,
        "storyContextPrompt": story_context_text,
        "panelPromptRows": payload_raw_prompts,
        "storyboardTemplate": storyboard_template,
        "storyboardTemplateLabel": storyboard_template_label(storyboard_template),
        "storyboardTemplateLayoutSpec": template_layout_spec,
        "productionSpec": production_spec,
        "storyboardRenderSpec": storyboard_render_spec,
        "storyboardPromptSpec": {
            "format": storyboard_format,
            "layoutKind": storyboard_template_layout_kind(storyboard_template),
            "template": storyboard_template,
            "templateLabel": storyboard_template_label(storyboard_template),
            "panelCount": len(payload_panels),
            "routePanelCount": len(panels),
            "durationSeconds": duration_seconds,
            "panelIndex": selected_panel_index + 1 if selected_panel_index is not None else None,
            "panelPolicy": "single_panel_per_result_node" if is_single_panel_image_node else "ordered_shot_panel_sequence",
            "fixedGrid": False,
            "targetVideoAspectRatio": production_spec.get("aspectRatio"),
            "shotFrameAspectRatio": production_spec.get("aspectRatio"),
        },
    }
    if director_context:
        payload["directorContext"] = copy.deepcopy(director_context)
        for key in (
            "directorBoardNodeId",
            "directorPlan",
            "directorPlanShots",
            "directorRuleId",
            "directorTaskCard",
            "storyboardAnalysis",
        ):
            if key in director_context:
                payload[key] = copy.deepcopy(director_context.get(key))
    asset_refs = _collect_workflow_asset_refs(
        workflow,
        payload_panels,
        project_id=project_id,
        episode_id=None if is_independent else episode_id,
        context_provenance=context_provenance,
        route_id=route_id,
        work_chain_id=work_chain_id,
    )
    if _asset_refs_has_value(asset_refs):
        payload["assetRefs"] = asset_refs
    if node_id:
        payload = _merge_version_payload_snapshots(
            payload,
            _workflow_version_payload_snapshots(
                project_id,
                episode_id,
                workflow,
                str(node_id),
                prompt_payload=payload,
            ),
        )
        if "referenceMediaIdsSnapshot" in payload:
            payload["referenceMediaIds"] = copy.deepcopy(payload.get("referenceMediaIdsSnapshot") or [])
        if "assetRefsSnapshot" in payload:
            snapshot_asset_refs = copy.deepcopy(payload.get("assetRefsSnapshot") or [])
            if snapshot_asset_refs:
                payload["assetRefs"] = snapshot_asset_refs
            else:
                payload.pop("assetRefs", None)
        if "referenceManifestSnapshot" in payload:
            payload["referenceManifest"] = copy.deepcopy(payload.get("referenceManifestSnapshot") or [])
    manifest = payload.get("referenceManifest") if isinstance(payload.get("referenceManifest"), list) else []
    scoped_manifest, excluded_manifest = scope_storyboard_reference_manifest(payload_panels, manifest)
    payload["referenceManifest"] = scoped_manifest
    kept_tokens = {str(row.get(key) or "").strip() for row in scoped_manifest for key in ("mediaId", "assetId")}
    excluded_tokens = {str(row.get(key) or "").strip() for row in excluded_manifest for key in ("mediaId", "assetId")}
    excluded_tokens.discard("")
    payload["storyboardExcludedReferenceIds"] = sorted(excluded_tokens - kept_tokens)
    if isinstance(payload.get("referenceMediaIds"), list):
        payload["referenceMediaIds"] = [value for value in payload["referenceMediaIds"]
                                        if str(value or "").strip() not in payload["storyboardExcludedReferenceIds"]]
    manifest_prompt = _reference_manifest_prompt(payload.get("referenceManifest") if isinstance(payload.get("referenceManifest"), list) else [])
    if manifest_prompt:
        if manifest_prompt not in payload["storyboardImagePrompt"]:
            payload["storyboardImagePrompt"] = _storyboard_prompt_with_reference_manifest(
                payload["storyboardImagePrompt"],
                manifest_prompt,
            )
        if payload.get("storyboardImagePromptRaw") and manifest_prompt not in str(payload.get("storyboardImagePromptRaw") or ""):
            payload["storyboardImagePromptRaw"] = _storyboard_prompt_with_reference_manifest(
                str(payload.get("storyboardImagePromptRaw") or ""),
                manifest_prompt,
            )
    spatial_reference_prompt = _storyboard_spatial_reference_prompt(
        payload.get("referenceManifest") if isinstance(payload.get("referenceManifest"), list) else [],
        storyboard_template,
    )
    if spatial_reference_prompt:
        if spatial_reference_prompt not in payload["storyboardImagePrompt"]:
            payload["storyboardImagePrompt"] = _storyboard_prompt_with_spatial_reference(
                payload["storyboardImagePrompt"],
                spatial_reference_prompt,
            )
        if payload.get("storyboardImagePromptRaw") and spatial_reference_prompt not in str(payload.get("storyboardImagePromptRaw") or ""):
            payload["storyboardImagePromptRaw"] = _storyboard_prompt_with_spatial_reference(
                str(payload.get("storyboardImagePromptRaw") or ""),
                spatial_reference_prompt,
            )
    payload["storyboardImagePrompt"], local_asset_mention_meta = _normalize_storyboard_local_asset_mentions(
        project_id,
        payload.get("storyboardImagePrompt"),
        payload,
        context_label="分镜图提示词",
    )
    if payload.get("storyboardImagePromptRaw"):
        payload["storyboardImagePromptRaw"], raw_local_asset_mention_meta = _normalize_storyboard_local_asset_mentions(
            project_id,
            payload.get("storyboardImagePromptRaw"),
            payload,
            context_label="分镜图原始提示词",
        )
        local_asset_mention_meta["rawConvertedCount"] = raw_local_asset_mention_meta.get("convertedCount", 0)
    payload["storyboardLocalAssetMentionNormalization"] = local_asset_mention_meta
    payload_asset_refs = payload.get("assetRefs") if "assetRefs" in payload else payload.get("asset_refs")
    # Runtime generation happens after the workflow exists. Manual canvas asset
    # links are project-global at this stage; episode/context asset scope only
    # belongs to planning-agent candidate selection before workflow generation.
    project_asset_lookup, _unused_scoped = _project_asset_lookup_with_scope(project_id)
    asset_ref_blocking, asset_ref_warnings = _validate_asset_refs_for_episode_scope(
        project_id,
        None,
        payload_asset_refs,
        "生成 payload",
        lookup=project_asset_lookup,
        scoped=False,
    )
    if asset_ref_blocking:
        raise ValueError("；".join(asset_ref_blocking))
    if asset_ref_warnings:
        payload["assetRefWarnings"] = asset_ref_warnings
    storyboard_contract = _storyboard_interpretation_contract_from_payload(payload)
    if storyboard_contract:
        payload["storyboardInterpretationContract"] = storyboard_contract
    return payload


def _storyboard_svg_preview(title: str, payload: dict[str, Any]) -> str:
    raw_panels = payload.get("panels") if isinstance(payload.get("panels"), list) else []
    panels = [item for item in raw_panels if isinstance(item, dict)]
    count = max(1, min(6, len(panels) or 6))
    width = 1280
    height = 720
    gap = 18
    margin = 44
    cols = 3 if count > 2 else count
    rows = 2 if count > 3 else 1
    cell_w = (width - margin * 2 - gap * (cols - 1)) / cols
    cell_h = (height - 150 - gap * (rows - 1)) / rows
    colors = [
        ("312e81", "0f172a"),
        ("155e75", "111827"),
        ("7c2d12", "27272a"),
        ("581c87", "020617"),
        ("164e63", "172554"),
        ("1e3a8a", "3b0764"),
    ]
    cells = []
    for index in range(count):
        panel = panels[index] if index < len(panels) else {}
        col = index % cols
        row = index // cols
        x = margin + col * (cell_w + gap)
        y = 116 + row * (cell_h + gap)
        panel_title = _xml_text(_panel_title(panel, index))
        action = _xml_text(_compact_text(_panel_value(panel, "action", "description", "summary", "content"), 48))
        start_color, end_color = colors[index % len(colors)]
        gradient = f"panel{index}"
        cells.append(
            f"<defs><linearGradient id='{gradient}' x1='0' y1='0' x2='1' y2='1'>"
            f"<stop offset='0%' stop-color='#{start_color}'/>"
            f"<stop offset='100%' stop-color='#{end_color}'/>"
            "</linearGradient></defs>"
            f"<rect x='{x:.1f}' y='{y:.1f}' width='{cell_w:.1f}' height='{cell_h:.1f}' rx='18' fill='url(#{gradient})' stroke='rgba(255,255,255,0.34)'/>"
            f"<text x='{x + 22:.1f}' y='{y + 40:.1f}' font-family='Arial, sans-serif' font-size='22' font-weight='700' fill='white'>{index + 1:02d}. {panel_title}</text>"
            f"<text x='{x + 22:.1f}' y='{y + 74:.1f}' font-family='Arial, sans-serif' font-size='15' fill='rgba(255,255,255,0.78)'>{action}</text>"
            f"<circle cx='{x + cell_w - 40:.1f}' cy='{y + cell_h - 38:.1f}' r='18' fill='rgba(255,255,255,0.16)'/>"
        )
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='1280' height='720' viewBox='0 0 1280 720'>"
        "<defs><linearGradient id='bg' x1='0' y1='0' x2='1' y2='1'>"
        "<stop offset='0%' stop-color='#111827'/><stop offset='55%' stop-color='#1e1b4b'/><stop offset='100%' stop-color='#0f766e'/>"
        "</linearGradient></defs>"
        "<rect width='1280' height='720' fill='url(#bg)'/>"
        f"<text x='44' y='58' font-family='Arial, sans-serif' font-size='30' font-weight='700' fill='white'>{_xml_text(title)}</text>"
        f"<text x='44' y='88' font-family='Arial, sans-serif' font-size='15' fill='rgba(255,255,255,0.68)'>分镜图 · {count} panels · ai-video</text>"
        + "".join(cells)
        + "</svg>"
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def _generated_version_preview(version_type: str, title: str, payload: dict[str, Any] | None = None) -> str | None:
    return None
