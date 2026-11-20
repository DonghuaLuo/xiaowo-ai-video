# -*- coding: utf-8 -*-
"""Field-only render preflight for frozen storyboard starting frames.

Observed provider terms are kept here rather than in creative prompts. They
trigger a local rewrite of the visible frame; story facts and sound stay intact.
"""
from __future__ import annotations

from typing import Any


_FRAME_REVIEW_RULES = (
    ("visible_start", "只描述当前画格可见的主体、相对位置、构图、姿态和状态；未来动作与终态留在视频字段。"),
    ("story_fidelity", "保留原剧本的人物关系、时间确定程度和关键结果；图像表达可以克制，但不得把已发生的事改成另一件事。"),
    ("sensitive_depiction", "对可能令人不适的事件，优先描述非露骨的可见姿态、距离和人物反应；不要求展示伤口、血腥或刺激性细节，也不靠空泛词隐藏剧情。"),
    ("style_ownership", "按本镜视觉层应用范围保留项目身份、时代和空间事实；静态差异与项目画风不可互相覆盖。"),
    ("text_ownership", "画面字段只写可见场景与构图；保留必要的场景载体信息，不编造编辑层装饰字。"),
    ("request_scope", "只把当前画面、必要资产身份与所选画风投影给图片模型；供应商拒绝须检查实际提示词、参考图和错误阶段。"),
)


def storyboard_frame_review_rules() -> list[dict[str, str]]:
    return [{"id": rule_id, "requirement": requirement} for rule_id, requirement in _FRAME_REVIEW_RULES]


# Extend only after a refusal is reproduced for the named image model.
# This is not a universal safety policy or a text-wide substitution list.
_OBSERVED_FRAME_TERMS_BY_MODEL = {
    "gptimage25flare": {
        "遗体": "用可见的身体姿态和人物关系表达同一状态；可写“身体”，故事事实留在剧本与动作字段",
    },
}


def observed_frame_refusal_risks(image_model: str = "") -> list[dict[str, str]]:
    """Only expose refusal wording reproduced for the selected image model."""
    normalized_model = "".join(char for char in str(image_model).casefold() if char.isalnum())
    return [
        {"term": term, "guidance": guidance}
        for model, terms in _OBSERVED_FRAME_TERMS_BY_MODEL.items()
        if model in normalized_model
        for term, guidance in terms.items()
    ]


def storyboard_frame_readiness_issues(shots: list[dict[str, Any]], image_model: str = "") -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    observed_terms = observed_frame_refusal_risks(image_model)
    for index, shot in enumerate(shots):
        frame = str(shot.get("storyboardFrame") or "")
        for risk in observed_terms:
            term, guidance = risk["term"], risk["guidance"]
            if term not in frame:
                continue
            issues.append({
                "path": f"shots[{index}].storyboardFrame",
                "code": "observed_image_provider_term",
                "message": f"镜头 {index + 1} 的起始画面含已复现拒绝风险的“{term}”。只改 storyboardFrame：{guidance}；不得删除角色、构图或故事事实。",
                "repairAction": "revise_frame_only",
                "shotNo": index + 1,
                "term": term,
            })
    return issues


def storyboard_image_prompt_refusal_risks(prompt: str, image_model: str = "") -> list[str]:
    """Catch reproduced refusal terms in the exact text sent to the image model."""
    text = str(prompt or "")
    return [risk["term"] for risk in observed_frame_refusal_risks(image_model)
            if risk["term"] in text]
