# -*- coding: utf-8 -*-
"""当前会话可发起的结构化任务目录。"""
from __future__ import annotations


_TASK_LABELS = {
    "free_chat": "讨论项目内容",
    "project_status": "查看当前进度",
    "overview_request": "生成项目概述",
    "project_cleanup": "清理项目或分集数据",
    "asset_range_delete_latest": "删除最新资产拆分范围",
    "asset_range_propose": "规划资产范围",
    "asset_range_commit": "确认资产范围",
    "asset_extraction": "拆分资产",
    "episode_boundary_propose": "规划下一集",
    "asset_query": "查询资产",
    "asset_content_update": "修改资产设定",
    "asset_update": "更新资产",
    "project_content_update": "修改项目内容",
    "settings_update": "更新项目配置",
    "work_chain_plan_discuss": "讨论当前集创作方案",
    "work_chain_plan_save": "拆分剧情并关联资产",
    "shot_prompt_patch": "修改分镜提示词",
    "workflow_node_content_update": "修改画布任务卡",
    "workflow_node_update": "修改画布节点",
    "workflow_update": "修改画布工作流",
    "workflow_cinematic_script_generation": "创作片段剧本",
    "director_plan_generation": "生成分镜脚本",
    "video_prompt_generation": "生成工作链视频提示词",
    "video_prompt_optimization": "优化独立视频卡提示词",
    "video_prompt_standalone_generation": "生成独立视频卡提示词",
    "asset_image_generation": "生成资产图",
    "storyboard_image_generation": "生成分镜图",
    "visual_handoff_image_generation": "生成视觉交接图",
    "storyboard_video_generation": "生成视频",
    "generation_request": "发起媒体生成",
    "media_file_request": "查询项目媒体文件",
    "quality_review": "检查项目质量",
}

_TASK_NOTES = {
    "overview_request": "生成项目概述的一次性任务。",
    "storyboard_image_generation": "为明确的分镜节点发起一次性图片任务。",
    "visual_handoff_image_generation": "为明确的视觉交接节点发起一次性图片任务。",
    "storyboard_video_generation": "为明确的视频节点发起一次性视频任务。",
    "asset_range_delete_latest": "先展示影响范围，等待用户确认后删除最新资产范围。",
    "project_cleanup": "先展示影响范围，等待用户确认后清理指定数据。",
}


def _agent_known_task_types() -> list[str]:
    return list(_TASK_LABELS)


def _agent_task_catalog() -> list[dict[str, str]]:
    return [{"taskType": task_type, "label": label,
             "note": _TASK_NOTES.get(task_type, "")}
            for task_type, label in _TASK_LABELS.items()]


def _agent_task_label(task_type: str) -> str:
    return _TASK_LABELS.get(str(task_type or "").strip(), "")
