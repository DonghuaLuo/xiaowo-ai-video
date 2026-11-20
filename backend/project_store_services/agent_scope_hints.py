# -*- coding: utf-8 -*-
"""项目会话中按需加载分集进度详情的只读提示。"""
from __future__ import annotations
import re


def _agent_message_requests_episode_detail(message: str) -> bool:
    compact = re.sub(r"\s+", "", str(message or ""))
    if not compact:
        return False
    detail_terms = (
        "分镜图",
        "片段剧本",
        "视频生成",
        "影视化剧本",
        "生成剧本",
        "视觉交接",
        "视频提示词",
        "最终视频",
        "资产图",
        "未完成",
        "完成进度",
        "当前环节",
        "做到哪",
        "还差什么",
    )
    if any(term in compact for term in detail_terms):
        return True
    if re.search(r"(当前|本条|这条|该条|第[一二三四五六七八九十百千万\d]+条)工作链", compact):
        return True
    episode_terms = ("当前集", "本集", "这一集", "该集")
    episode_pattern = r"第[一二三四五六七八九十百千万\d]+集"
    progress_terms = ("进度", "状态", "下一步", "完成", "还差", "未完成")
    mentions_episode = any(term in compact for term in episode_terms) or bool(
        re.search(episode_pattern, compact)
    )
    mentions_progress = any(term in compact for term in progress_terms)
    if mentions_episode and mentions_progress and "下一集" not in compact:
        return True
    return False
