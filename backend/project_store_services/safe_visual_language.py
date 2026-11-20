# -*- coding: utf-8 -*-
"""通用的正向画面语言边界。"""

from __future__ import annotations

import re
from typing import Any


_DIRECT_RISK_LANGUAGE_PATTERNS = (
    re.compile(
        r"(?:杀人|杀死|杀害|谋杀|处死|枪杀|刺杀|砍杀|砍死|捅死|勒死|毒死|咬死|撞死|"
        r"烧死|烧伤|活活烧|肢解|割喉|斩首|爆头|虐待|施虐|强暴|强奸|侵犯|伤害|"
        r"殺人|殺死|殺害|謀殺|處死|槍殺|刺殺|砍殺|砍死|捅死|勒死|毒死|咬死|撞死|"
        r"燒死|燒傷|活活燒|肢解|割喉|斬首|爆頭|虐待|施虐|強暴|強姦|侵犯|傷害)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<!燃)(?:烧|燒|焚烧|焚燒|火烧|火燒|放火烧|放火燒|点火烧|點火燒)"
        r"[^，。；;\n]{0,8}"
        r"(?:人|人体|人體|人物|角色|儿童|兒童|孩子|老人|动物|動物|生物|蛇|兽|獸|鸟|鳥|鱼|魚|"
        r"猫|貓|狗|马|馬|牛|羊|龙|龍|妖|怪|精灵|精靈)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:尸体|屍體|遗体|遺體|血肉模糊|血腥|鲜血淋漓|鮮血淋漓|死亡|死者)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:kill(?:ed|ing)?|murder(?:ed|ing)?|burn(?:ed|ing)?\s+alive|corpse|dead\s+body|"
        r"harm(?:ed|ing)?|abuse(?:d|ing)?|assault(?:ed|ing)?|rape(?:d|ing)?|gore|bloodied)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:giết(?:\s+người)?|thiêu\s+sống|xác\s+chết|làm\s+hại|tấn\s+công|cưỡng\s+hiếp|máu\s+me)\b",
        re.IGNORECASE,
    ),
)

_SAFETY_POLICY_LANGUAGE_RE = re.compile(
    r"(?:内容策略|內容策略|安全策略|违规词|違規詞|敏感词|敏感詞|审核|審核|拒绝生成|拒絕生成|"
    r"无法生成|無法生成|不能生成|政策违规|政策違規|content\s+policy|policy\s+violation)",
    re.IGNORECASE,
)


def direct_risk_language_matches(value: Any) -> list[str]:
    """返回仍在直接描述风险行为或结果的片段，不修改原文。"""

    text = str(value or "")
    matches: list[str] = []
    for pattern in _DIRECT_RISK_LANGUAGE_PATTERNS:
        for match in pattern.finditer(text):
            token = match.group(0).strip()
            if token and token not in matches:
                matches.append(token)
    return matches


def uses_safety_policy_language(value: Any) -> bool:
    """识别不应进入媒体模型提示词的审核或策略话术。"""

    return bool(_SAFETY_POLICY_LANGUAGE_RE.search(str(value or "")))
