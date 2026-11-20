# -*- coding: utf-8 -*-
"""任务类型定义、执行配置和语言、审查策略。"""
from __future__ import annotations

import copy
from .production_specs import (
    project_language_spec,
)
from .worker_asset_contract import (
    _NATURAL_LANGUAGE_FORBIDDEN_LATIN_RE,
    _WORKER_WORK_DEFINITIONS,
)
from typing import (
    Any,
    Callable,
)


WorkerProgressCallback = Callable[[dict[str, Any]], None]




def _worker_language_contract(
    context: dict[str, Any],
    *,
    preserve_source_text: bool = False,
) -> str:
    production_spec = context.get("productionSpec") if isinstance(context.get("productionSpec"), dict) else {}
    language = production_spec.get("language") if isinstance(production_spec.get("language"), dict) else {}
    language = language or project_language_spec("zh-CN")
    code = str(language.get("code") or "zh-CN")
    label = str(language.get("label") or "简体中文")
    instruction = str(language.get("instruction") or project_language_spec(code)["instruction"])
    contract = (
        f"【项目语言硬约束】项目创建时选择的语言为 {label}（{code}）。{instruction}"
        "JSON 字段名保持 schema 规定的英文键名，但所有模型新生成的自然语言字段值必须遵守该语言。"
        "sourceEvidence 可忠实概括原文，name/aliases 可保留原文专名；desc、assetImagePrompt、voiceStyle、designRationale 和审查说明等生成性说明不要夹杂英文单词或中英混写。"
    )
    if preserve_source_text:
        contract += (
            "sourceStartAnchor 和 sourceEndAnchor 必须来自当前分集原文的连续逐字摘录，且有效字符数必须大于 10；"
            "不得概括、压缩、润色、换词、补写、代词消解或插入原文没有的文字。"
        )
    return contract


def _natural_language_forbidden_latin_terms(value: Any) -> list[str]:
    text = str(value or "")
    if not text:
        return []
    terms: list[str] = []
    for match in _NATURAL_LANGUAGE_FORBIDDEN_LATIN_RE.finditer(text):
        term = match.group(0).strip()
        if term and term not in terms:
            terms.append(term)
        if len(terms) >= 6:
            break
    return terms








def worker_work_definition(worker_name: str) -> dict[str, Any]:
    definition = _WORKER_WORK_DEFINITIONS.get(worker_name)
    if not definition:
        raise ValueError(f"未知 worker：{worker_name}")
    return copy.deepcopy(definition)
