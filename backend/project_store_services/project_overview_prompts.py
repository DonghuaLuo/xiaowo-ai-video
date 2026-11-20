# -*- coding: utf-8 -*-
"""项目概述分析提示词组件与组装器。"""

from __future__ import annotations


PROJECT_OVERVIEW_SYSTEM_PROMPT = """你是专业的小说影视化项目概述分析师。

你只做一件事：阅读当前提供的小说原文内容，完成项目概述分析。"""

PROJECT_OVERVIEW_TASK_PROMPT = (
    "你只能基于下面提供的小说原文内容做项目概述分析，并设计可贯穿项目的旁白声音。"
)

PROJECT_OVERVIEW_READING_BOUNDARY_PROMPT = (
    "注意：当前读取内容不一定覆盖完整小说，"
    "不要把只属于局部阶段、局部地点、局部贫富状态或局部事件的内容误当成贯穿全书设定。"
)

PROJECT_OVERVIEW_FIELD_RELATION_PROMPT = (
    "genre_context 与 theme_visual_context 允许相近，但职责必须不同："
    "前者突出题材类型和叙事推进，后者突出时代地域文化和视觉世界；"
    "narrator_voice_design 分别写长期复用的基础声线和默认讲述方式，不写单句表演。"
)

PROJECT_OVERVIEW_USER_PROMPT_TEMPLATE = """【概述分析任务】
{taskPrompt}

【阅读边界】
{readingBoundary}

【字段关系】
{fieldRelation}

【小说原文】
{sourceBlock}"""


# 这些变量按 PROJECT_OVERVIEW_USER_PROMPT_TEMPLATE 中出现的顺序排列，方便人工确认最终提示词组装顺序。
PROJECT_OVERVIEW_PROMPT_VARIABLES_IN_ORDER = (
    ("{taskPrompt}", "具体执行任务提示词，即本文件中的 PROJECT_OVERVIEW_TASK_PROMPT。"),
    ("{readingBoundary}", "阅读范围和不可外推约束，即本文件中的 PROJECT_OVERVIEW_READING_BOUNDARY_PROMPT。"),
    ("{fieldRelation}", "跨字段关系约束，即本文件中的 PROJECT_OVERVIEW_FIELD_RELATION_PROMPT。"),
    ("{sourceBlock}", "小说原文区块，由 build_project_overview_source_block(source_text) 生成。"),
)


def build_project_overview_source_block(source_text: str) -> str:
    return str(source_text or "").strip()


def build_project_overview_prompt(
    *,
    source_text: str,
) -> str:
    return PROJECT_OVERVIEW_USER_PROMPT_TEMPLATE.format(
        taskPrompt=PROJECT_OVERVIEW_TASK_PROMPT,
        readingBoundary=PROJECT_OVERVIEW_READING_BOUNDARY_PROMPT,
        fieldRelation=PROJECT_OVERVIEW_FIELD_RELATION_PROMPT,
        sourceBlock=build_project_overview_source_block(source_text),
    ).strip()


__all__ = (
    "PROJECT_OVERVIEW_SYSTEM_PROMPT",
    "PROJECT_OVERVIEW_TASK_PROMPT",
    "PROJECT_OVERVIEW_READING_BOUNDARY_PROMPT",
    "PROJECT_OVERVIEW_FIELD_RELATION_PROMPT",
    "PROJECT_OVERVIEW_USER_PROMPT_TEMPLATE",
    "PROJECT_OVERVIEW_PROMPT_VARIABLES_IN_ORDER",
    "build_project_overview_source_block",
    "build_project_overview_prompt",
)
