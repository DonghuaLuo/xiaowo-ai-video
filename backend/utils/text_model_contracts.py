"""Operation constraints shared by discovery, selection and text requests."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from utils.model_exclusions import normalized_model_id


def general_text_pending_reason(model: Mapping[str, Any] | str) -> str:
    name = normalized_model_id(model)
    # Translation endpoints do not implement our system-prompt / general-task contract.
    if re.fullmatch(r"(?:qwen-mt-(?:plus|turbo|flash|lite)|doubao-seed-translation)(?:-latest|-\d{4}(?:-\d{2}-\d{2})?|-\d{6})?", name):
        return "专用翻译模型，通用文本与智能体调用待适配"
    # The research workflow requires its own adapter, not a generic chat call.
    # https://help.aliyun.com/zh/model-studio/qwen-deep-research-api
    if re.fullmatch(r"qwen-deep-research(?:-\d{4}-\d{2}-\d{2})?", name):
        return "专用研究流程，通用文本与智能体调用待适配"
    return ""


def anthropic_sampling_parameters(model: Mapping[str, Any] | str, temperature: float) -> dict[str, float]:
    # https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide
    # https://platform.claude.com/docs/en/models/opus-5-5/migration-guide
    name = normalized_model_id(model)
    version = re.fullmatch(
        r"claude-(opus|sonnet)-(\d+)(?:[.-](\d{1,2}))?(?:-(?:latest|\d{8}))?", name,
    )
    if version:
        family, major, minor = version.groups()
        boundary = (4, 7) if family == "opus" else (5, 0)
        if (int(major), int(minor or 0)) >= boundary:
            return {}
    return {"temperature": temperature}
