"""Task and project reasoning translated only for verified provider/model routes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


_NON_REASONING_TASKS = frozenset({
    "storyboard-image-error-classifier-prompt",
    "structured-probe",
})

_LOW_TASKS = frozenset({
    "agent-intent-probe-prompt",
    "agent-intent",
})

_LOW_AGENT_TASKS = frozenset({
    "project_status", "progress_query", "asset_query", "media_file_request",
    "settings_update", "asset_range_commit",
})

_HIGH_TASKS = frozenset({
    "director-plan-prompt", "plot-split-asset-binding-review-prompt",
    "storyboard-image-readback-prompt", "video-prompt-quality-review",
    "worker-review", "agent:quality_review",
})

_HIGH_ASSET_PHASES = frozenset({
    "candidate-review", "candidate-living-boundary-review",
    "candidate-cross-type-conflict-review", "final-mixed-review",
})

_OUTPUT_TOKEN_BUDGETS = {
    "disabled": 8192,
    "low": 8192,
    "medium": 16384,
    "high": 32768,
    "xhigh": 65536,  # Reserved; no task automatically selects this level.
    "max": 65536,  # Explicit DeepSeek maximum; never selected automatically.
    "adaptive": 16384,
}
_DEEPSEEK_BUDGET_MULTIPLIER = 3
_SDK_ANSWER_TOKEN_RESERVE = 4096

_ADAPTIVE_CONTRACTS = frozenset({"claude-adaptive", "minimax-m2", "minimax-m3"})
_DEFAULT_AGENT_REASONING_MODES = ("low", "medium", "high")
_GPT_AGENT_REASONING_MODES = (*_DEFAULT_AGENT_REASONING_MODES, "xhigh")
_DEEPSEEK_AGENT_REASONING_MODES = ("low", "high", "max")
_DASHSCOPE_DEEPSEEK_PRO_MODES = ("high", "max")
AGENT_REASONING_MODES = frozenset((*_GPT_AGENT_REASONING_MODES, *_DEEPSEEK_AGENT_REASONING_MODES))


def agent_reasoning_modes(base_url: str, model: str) -> tuple[str, ...]:
    """Offer only grades that are sent unchanged on this agent route."""
    contract = _reasoning_contract(base_url, model)
    if contract is None:
        return ()
    name = model.strip().lower().rsplit("/", 1)[-1]
    if contract == "dashscope" and name == "deepseek-v4-pro":
        return _DASHSCOPE_DEEPSEEK_PRO_MODES
    if _is_verified_deepseek_route(base_url, model):
        return _DEEPSEEK_AGENT_REASONING_MODES
    if contract == "dashscope-glm53":
        return ("low", "high", "max")
    if contract == "dashscope" and re.match(r"^qwen3\.8-(?:flash|max)(?:-|$)", name):
        return ("low", "medium", "xhigh")
    if contract in {"minimax-m2", "minimax-m3"}:
        return ()
    candidates = _GPT_AGENT_REASONING_MODES if contract == "gpt" else _DEFAULT_AGENT_REASONING_MODES
    return tuple(
        mode for mode in candidates
        if _provider_effort(base_url, model, mode, manually_selected=True) == mode
    )


def default_agent_reasoning_mode(model: str, base_url: str = "") -> str:
    """A project default independent of the agent task classification."""
    name = str(model or "").strip().lower().split(":", 1)[-1].rsplit("/", 1)[-1]
    if name.startswith("deepseek-"):
        return "low" if "low" in agent_reasoning_modes(base_url, model) else "high"
    contract = _reasoning_contract(base_url, str(model or ""))
    if contract in {
        "ark-glm52", "ark-glm53", "dashscope-glm53", "qiniu-glm53",
        "dashscope-kimi3", "qiniu-kimi3",
    }:
        return "high"
    if contract == "gemini3" and name.startswith("gemini-3-pro"):
        return "high"
    return "medium"


@dataclass(frozen=True)
class ReasoningPolicy:
    """Resolved policy before it is translated into a provider request.

    ``request_token_budget`` is the transport-level completion allowance. On
    providers whose thinking tokens share that allowance, it covers the whole
    completion rather than only the visible answer. ``thinking_token_budget``
    is only for SDKs that expose a separate thinking option. Keeping the two
    values explicit prevents a future provider adapter from silently treating
    one as the other; their values may diverge when a provider contract is
    calibrated without changing the task classification.
    """

    requested_mode: str
    effective_mode: str
    wire_effort: str
    budget_mode: str
    budget_multiplier: int
    request_token_budget: int
    thinking_token_budget: int


def _reasoning_contract(base_url: str, model: str) -> str | None:
    try:
        host = urlsplit(base_url).hostname or ""
    except ValueError:
        return None
    name = str(model).strip().lower()
    if host == "api.deepseek.com":
        return "deepseek" if name.startswith("deepseek-") else None
    deepseek_v4 = re.match(r"^deepseek-v4(?:[.-]|$)", name)
    doubao_seed2 = re.match(r"^doubao-seed-(?:2[.-][01][.-](?:pro|lite|mini|turbo|code)|evolving|character)(?:-|$)", name)
    if host == "ark.cn-beijing.volces.com":
        if re.match(r"^glm-5[.-]3(?:-|$)", name):
            return "ark-glm53"
        if re.match(r"^glm-5[.-]2(?:-|$)", name):
            return "ark-glm52"
        return "ark" if deepseek_v4 or doubao_seed2 else None
    if host == "dashscope.aliyuncs.com" or host.endswith(".cn-beijing.maas.aliyuncs.com"):
        if re.match(r"^(?:zhipu/)?glm-5\.3(?:-|$)", name):
            return "dashscope-glm53"
        if name == "kimi-k3":
            return "dashscope-kimi3"
        if name == "kimi/kimi-k3":
            # This is Moonshot's direct channel, not Bailian's deployment.
            # Its max-only contract is not covered by the low-effort policy.
            return None
        if deepseek_v4 or re.match(r"^qwen3\.8-(?:flash|max)(?:-|$)", name):
            return "dashscope"
        return None
    if host in {"api.minimax.cn", "api.minimax.io"}:
        if re.fullmatch(r"minimax-m2(?:\.[157])?(?:-highspeed)?", name):
            return "minimax-m2"
        return "minimax-m3" if name == "minimax-m3" else None
    if host == "api.qnaigc.com":
        if re.match(r"^z-ai/glm-5\.3(?:-|$)", name):
            return "qiniu-glm53"
        if name == "moonshotai/kimi-k3":
            return "qiniu-kimi3"
        if re.match(r"^qwen/qwen3\.8-(?:flash|max)(?:-|$)", name):
            return "dashscope"
        if re.match(r"^deepseek/deepseek-v4(?:[.-]|$)", name) or re.match(r"^bytedance/doubao-seed-2-1-(?:pro|turbo)(?:-|$)", name):
            return "ark"
        return None
    # Family rules describe wire formats, not the upstream identity of a
    # private alias. Unknown generations and hosted vendor namespaces stay out.
    if host and re.match(r"^gpt-(?:5\.[56]|6(?:\.1)?)(?:-|$)", name):
        return "gpt"
    if host and re.match(r"^claude-(?:sonnet|opus)-(?:4[.-][678]|5(?:[.-]5)?)(?:-|$)", name):
        return "claude-adaptive"
    name = name.removeprefix("models/")
    if host and re.fullmatch(r"gemini-3(?:\.[15678])?-(?:pro|flash|flash-lite)(?:-preview(?:-\d{2}-\d{2})?)?", name):
        return "gemini3"
    if host and re.fullmatch(r"gemini-2\.5-(?:pro|flash|flash-lite)(?:-preview(?:-\d{2}-\d{2})?)?", name):
        return "gemini25"
    return None


def model_reasoning_mode(base_url: str, model: str, task: str, *, mode_override: str | None = None) -> str | None:
    """None leaves unverified routes untouched; tasks are internal IDs."""
    if _reasoning_contract(base_url, model) is None:
        return None
    if mode_override is not None:
        if mode_override not in agent_reasoning_modes(base_url, model):
            raise ValueError("无效的智能体推理能力")
        return mode_override
    return task_reasoning_mode(task)


def task_reasoning_mode(task: str) -> str:
    """Business requirement, independent of transport and provider effort names."""
    if task in _NON_REASONING_TASKS:
        return "disabled"
    if task in _LOW_TASKS or (task.startswith("agent:") and task.removeprefix("agent:") in _LOW_AGENT_TASKS):
        return "low"
    if task in _HIGH_TASKS:
        return "high"
    if task.startswith("asset-phase:"):
        phase = task.removeprefix("asset-phase:")
        if phase in _HIGH_ASSET_PHASES or phase.startswith(("identity-", "semantic-review-", "type-candidate-patch-")):
            return "high"
    # Short answers can still decide creative scope. Free chat may include
    # creative discussion; unknown tasks must not silently lose reasoning.
    return "medium"


def reasoning_policy(base_url: str, model: str, task: str, *, mode_override: str | None = None) -> ReasoningPolicy | None:
    """Resolve business policy without emitting provider-specific fields."""
    requested_mode = model_reasoning_mode(base_url, model, task, mode_override=mode_override)
    if requested_mode is None:
        return None
    contract = _reasoning_contract(base_url, model)
    effective_mode = _effective_mode(contract, model, requested_mode)
    wire_effort = _provider_effort(base_url, model, effective_mode, manually_selected=mode_override is not None)
    budget_mode = effective_mode if mode_override is not None else wire_effort
    multiplier = (
        _DEEPSEEK_BUDGET_MULTIPLIER
        if effective_mode != "disabled" and _is_verified_deepseek_route(base_url, model)
        else 1
    )
    budget = _OUTPUT_TOKEN_BUDGETS[budget_mode] * multiplier
    return ReasoningPolicy(
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        wire_effort=wire_effort,
        budget_mode=budget_mode,
        budget_multiplier=multiplier,
        request_token_budget=budget,
        thinking_token_budget=(
            budget - _SDK_ANSWER_TOKEN_RESERVE
            if effective_mode != "disabled"
            and contract not in _ADAPTIVE_CONTRACTS | {"gemini3", "gemini25"}
            else 0
        ),
    )


def _provider_effort(base_url: str, model: str, mode: str, *, manually_selected: bool = False) -> str:
    contract = _reasoning_contract(base_url, model)
    if mode == "disabled":
        return mode
    qwen38 = contract == "dashscope" and bool(re.match(
        r"^qwen3\.8-(?:flash|max)(?:-|$)", model.strip().lower().rsplit("/", 1)[-1],
    ))
    if manually_selected and mode == "xhigh" and contract != "gpt" and not qwen38:
        mode = "high"
    if contract in {"minimax-m2", "minimax-m3"}:
        return "adaptive"
    if contract == "gemini3" and mode == "medium" and model.lower().removeprefix("models/").startswith("gemini-3-pro"):
        # Gemini 3 Pro does not expose the portable medium level; the native
        # request is promoted to high by apply_model_reasoning().
        return "high"
    if _is_verified_deepseek_route(base_url, model):
        # Business quality is not a native effort name. High exhausted the
        # real episode request; low passed with adequate shared output space.
        if manually_selected:
            return mode
        return default_agent_reasoning_mode(model, base_url)
    if contract in {"ark-glm53", "dashscope-kimi3"}:
        # These routes do not expose a portable medium level in the verified
        # gateway contract. Keep simple probes at low, but do not silently
        # downgrade creative medium/high work; use the next supported level.
        return "low" if mode == "low" else "high"
    if contract == "dashscope-glm53":
        # These channels have low/high/max, not a portable medium level.
        # High completed the fixed creative sample within its output budget.
        return mode if mode in {"low", "high", "max"} else "high"
    if contract == "qiniu-kimi3":
        # The gateway's medium previously selected low. Preserve low only for
        # low-complexity work; creative medium/high work must not be silently
        # downgraded below the application quality floor.
        return "low" if mode == "low" else "high"
    if contract == "ark-glm52":
        # The service maps low and medium to high; name the effective level.
        return "high"
    if contract == "dashscope" and "qwen3.8-" in model.lower() and mode == "high":
        # Bailian's high alias selects xhigh; the same gateway vocabulary is
        # accepted on Qiniu. Keep creative review within the measured ceiling.
        return "medium"
    return mode


def _effective_mode(contract: str, model: str, mode: str) -> str:
    if mode != "disabled":
        return mode
    if contract in {"ark-glm53", "dashscope-glm53", "qiniu-glm53", "qiniu-kimi3", "minimax-m2", "gemini3"}:
        return "low"
    if contract == "gemini25" and "-pro" in model.lower():
        return "low"
    if contract == "gpt" and re.match(r"^gpt-(?:6-astra|6\.1-sol)(?:-|$)", model.lower()):
        return "low"
    return mode


def _is_verified_deepseek_route(base_url: str, model: str) -> bool:
    contract = _reasoning_contract(base_url, model)
    return contract in {"deepseek", "ark", "dashscope"} and model.strip().lower().rsplit("/", 1)[-1].startswith("deepseek-")


def apply_model_reasoning(
    payload: dict[str, Any], *, base_url: str, model: str,
    endpoint: str, task: str, mode_override: str | None = None,
) -> None:
    policy = reasoning_policy(base_url, model, task, mode_override=mode_override)
    if policy is None:
        return
    contract = _reasoning_contract(base_url, model)
    mode = policy.effective_mode
    effort = policy.wire_effort
    if endpoint == "openai-responses":
        if contract not in {"deepseek", "gpt"}:
            return
        payload["reasoning"] = {"effort": "none" if mode == "disabled" else effort}
    elif endpoint == "gemini-generate":
        if contract not in {"gemini3", "gemini25"}:
            return
        generation = payload.setdefault("generationConfig", {})
        if contract == "gemini3":
            generation["thinkingConfig"] = {"thinkingLevel": effort}
        else:
            generation["thinkingConfig"] = {"thinkingBudget": {"disabled": 0, "low": 1024, "medium": 4096, "high": 8192, "xhigh": 8192}[mode]}
        generation["maxOutputTokens"] = policy.request_token_budget
    elif endpoint in {"openai-chat", "anthropic-messages"}:
        if contract in {"gemini3", "gemini25"}:
            return
        if contract in {"minimax-m3", "minimax-m2", "claude-adaptive"}:
            if endpoint != "anthropic-messages":
                return
            payload["thinking"] = {"type": "disabled" if mode == "disabled" else "adaptive"}
            if contract == "claude-adaptive":
                payload.setdefault("output_config", {})["effort"] = "low" if mode == "disabled" else effort
        elif endpoint == "openai-chat" and contract == "gpt":
            payload["reasoning_effort"] = "none" if mode == "disabled" else effort
            if "max_tokens" in payload:
                payload["max_completion_tokens"] = payload.pop("max_tokens")
        else:
            if endpoint == "openai-chat" and contract.startswith("dashscope"):
                payload["enable_thinking"] = mode != "disabled"
            else:
                payload["thinking"] = {"type": "disabled" if mode == "disabled" else "enabled"}
            if mode != "disabled":
                if endpoint == "anthropic-messages":
                    payload.setdefault("output_config", {})["effort"] = effort
                else:
                    payload["reasoning_effort"] = effort
    else:
        return
    host = urlsplit(base_url).hostname or ""
    if endpoint == "openai-chat" and (host in {"ark.cn-beijing.volces.com", "dashscope.aliyuncs.com"} or host.endswith(".cn-beijing.maas.aliyuncs.com")):
        if "max_tokens" in payload:
            payload["max_completion_tokens"] = payload.pop("max_tokens")
    # The centralized policy owns the final cap; call-site defaults apply only
    # to unverified routes. SDK requests install their cap in the runtime.
    for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
        if key in payload:
            payload[key] = policy.request_token_budget
    if mode != "disabled" or contract != "deepseek":
        payload.pop("temperature", None)
        payload.pop("top_p", None)


def model_sdk_reasoning_options(base_url: str, model: str, task: str, *, mode_override: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {}
    apply_model_reasoning(body, base_url=base_url, model=model,
                          endpoint="anthropic-messages", task=task, mode_override=mode_override)
    policy = reasoning_policy(base_url, model, task, mode_override=mode_override)
    thinking = body.get("thinking")
    if not thinking:
        return {}
    # These are CLI options, not the final provider body. The runtime also
    # applies apply_model_reasoning via EXTRA_BODY to preserve provider fields.
    options: dict[str, Any] = {"thinking": dict(thinking)}
    if thinking["type"] == "enabled":
        # The Agent SDK CLI requires budget_tokens for every ``enabled``
        # thinking config, even when the upstream provider must not receive a
        # fixed budget.  The provider request body is carried separately in
        # CLAUDE_CODE_EXTRA_BODY and remains free of this field for routes such
        # as Bailian/Qiniu Qwen.  Keep the SDK ceiling and provider payload
        # deliberately separate.
        sdk_budget = policy.thinking_token_budget if policy else 0
        if sdk_budget:
            options["thinking"]["budget_tokens"] = sdk_budget
    effort = (body.get("output_config") or {}).get("effort")
    if effort:
        options["effort"] = effort
    elif thinking["type"] == "disabled" and _reasoning_contract(base_url, model) != "minimax-m3":
        options["effort"] = "low"
    return options
