"""Load the current and preceding episode as one finite novel excerpt."""
from __future__ import annotations

import json


def merge_episode_context(episode_ids, episode_id, read_source, fragment):
    """Use explicit project ordering; never truncate or append an unmatched fragment."""
    from project_store_services.director_plan_contract import _normalize_multiline_text

    if episode_ids.count(episode_id) != 1:
        raise ValueError("当前集在项目顺序中不存在或不唯一")
    index = episode_ids.index(episode_id)
    selected = episode_ids[max(0, index - 1):index + 1]
    sources = []
    for item in selected:
        source = _normalize_multiline_text(read_source(item))
        if not source:
            raise ValueError(f"缺少集原文：{item}")
        sources.append(source)
    fragment = _normalize_multiline_text(fragment)
    if not fragment or sources[-1].count(fragment) != 1:
        raise ValueError("待改编片段必须唯一对应当前集原文；请检查原文或卡片是否已更新")
    novel = "\n\n".join(sources)
    if novel.count(fragment) != 1:
        raise ValueError("待改编片段在合并上下文中重复，无法唯一定位")
    return novel, fragment, selected


def load_episode_sample(project_id, episode_id, fragment, user_instruction="", *, script_template_id="faithful_cinematic"):
    from project_store_services.agent_sessions import _project_meta_path
    from project_store_services.source_text_store import _read_episode_source_text

    meta = json.loads(_project_meta_path(project_id).read_text(encoding="utf-8"))
    episode_ids = [str(item.get("id") or "") for item in meta.get("episodes", []) if isinstance(item, dict)]
    novel, target, selected = merge_episode_context(
        episode_ids, episode_id,
        lambda item: _read_episode_source_text(project_id, item), fragment,
    )
    return {
        "novelExcerpt": novel,
        "fragmentText": target,
        "scriptTemplateId": script_template_id,
        "userInstruction": user_instruction,
    }, selected

