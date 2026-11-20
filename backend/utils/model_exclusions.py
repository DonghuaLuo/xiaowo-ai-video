"""Local model exclusion policy.

This is deliberately a product-side rule set. It does not call a provider,
read provider lifecycle metadata, or infer anything from a user's balance or
permissions. Discovery still comes from the provider; this module limits
official-service families and hides generations the product no longer offers.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


LOCAL_EXCLUSION_SOURCE = "local-model-policy"

_MODEL_FIELDS = ("api_model_id", "model_id", "model", "id", "name")

# Local selection boundaries, independent of aliases offered by a particular Key.
# Match upstream IDs after stripping a carrier namespace; never rewrite request IDs.
_RETIRED_SERIES = (
    (r"doubao-(?:pro|lite|vision-pro|vision-lite)-(?:4k|32k|128k|256k)(?:-(?:pretrain-character|character|functioncall|browsing))?(?:-\d{6}|-preview)?",
     "旧 Doubao Pro/Lite 系列不再作为本地可选模型。", "Doubao Seed 2.1 / Seed Character"),
    (r"doubao-1[.-]5(?:-[a-z0-9]+)*", "Doubao 1.5 系列不再作为本地可选模型。", "Doubao Seed 2.1"),
    (r"doubao-seed-1[.-](?:6|8)(?:-[a-z0-9]+)*", "Doubao Seed 1.x 系列不再作为本地可选模型。", "Doubao Seed 2.1"),
    (r"gemini-2\.0-flash(?:-lite)?(?:-001|-exp|-preview-02-05)?|gemini-3-pro-preview",
     "该 Gemini 旧系列已下线，不再作为本地可选模型。", "当前 Gemini 系列"),
    (r"claude-3-5-sonnet-(?:20240620|20241022)|claude-opus-4-1-20250805",
     "该 Claude 旧版本已下线，不再作为本地可选模型。", "当前 Claude 系列"),
    (r"grok-imagine-image-(?:quality|pro)", "该 Grok 图片系列已由 Image 2.0 替代。", "grok-imagine-image-2.0"),
)
_RETIRED_SERIES_RULES = tuple((re.compile(pattern), reason, replacement)
                              for pattern, reason, replacement in _RETIRED_SERIES)

# Verified on 2026-10-04. Exact IDs avoid treating every preview or Claude 4.x
# model as retired. These are product exclusions, not relay availability claims.
# Sources: official OpenAI, Claude and Gemini API deprecation tables.
_RETIRED_IDS = {
    "chatgpt-4o-latest": "GPT 5.5 或更高版本",
    "o1-preview": "GPT 5.5 或更高版本",
    "o1-mini": "GPT 5.5 或更高版本",
    **dict.fromkeys((
        "claude-sonnet-4-20250514", "claude-opus-4-20250514",
        "claude-3-7-sonnet-20250219", "claude-3-5-haiku-20241022",
        "claude-3-haiku-20240307", "claude-3-opus-20240229",
        "claude-2.0", "claude-2.1", "claude-3-sonnet-20240229",
    ), "当前 Claude 系列"),
    **dict.fromkeys((
        "gemini-3.1-flash-image-preview", "gemini-3-pro-image-preview",
        "gemini-2.5-flash-image", "gemini-2.5-flash-image-preview",
    ), "gemini-3.1-flash-image / gemini-3-pro-image"),
    **dict.fromkeys((
        "gemini-2.5-pro-preview-03-25", "gemini-2.5-pro-preview-05-06",
        "gemini-2.5-pro-preview-06-05", "gemini-2.5-flash-lite-preview-09-2025",
        "gemini-2.5-flash-preview-05-20", "gemini-2.5-flash-preview-09-25",
        "gemini-3.1-flash-lite-preview",
    ), "当前 Gemini 正式系列"),
}

# Ark EOS is scoped to the ordinary Ark service, not Agent Plan or relays
# hosting the same model. Source: docs.volcengine.com/docs/ark/model-deprecation-notice
_ARK_RETIRED_IDS = frozenset((
    "mistral-7b-instruct-v0.2",
    "deepseek-r1-distill-qwen-7b-250120", "deepseek-r1-distill-qwen-32b-250120",
    "deepseek-r1-250120", "deepseek-v3-241226", "kimi-k2-250711",
    "deepseek-v3-1-250821", "kimi-k2-250905", "kimi-k2-thinking-251104",
    "deepseek-v3-250324", "deepseek-r1-250528", "deepseek-v3-1-terminus",
    "deepseek-v3-2-251201", "deepseek-v4-flash-260425", "glm-4-7-251222",
    "doubao-seed-code-preview-251028",
))

# A model can be available from a vendor but unavailable for a specific
# product route. Keep this scoped to the route instead of excluding the model
# from relays or other official services.
_ROUTE_UNSUPPORTED_IDS = {
    ("ark-agent-plan", "kimi-k3"): (
        "该模型不支持火山方舟 Agent Plan 接口，不能作为此套餐的智能体模型。",
        "Agent Plan 支持的模型",
    ),
}

# Text/agent selection is intentionally narrower than discovery. Discovery
# may return every upstream model exposed by a relay, but only these families
# have a local request contract and a useful creative-task verification. The
# rule is scoped by preset; a relay can still expose different upstream
# families than another relay. Image/video projections do not use this list.
_ADAPTED_TEXT_AGENT_RULES = {
    "deepseek": (
        r"deepseek-v4(?:[.-].*)?", r"deepseek-flash(?:[.-].*)?",
    ),
    "openai": (r"gpt-(?:5[.]5|5[.]6|6(?:[.]1)?)(?:[-.].*)?",),
    "anthropic": (
        r"claude-(?:sonnet|opus)-(?:4[.-]6|4[.-]7|4[.-]8|5(?:[.-]5)?)(?:[-.].*)?",
    ),
    "gemini": (
        r"gemini-(?:3(?:[.]1|[.]6|[.]7|[.]8)?|2[.]5)-(?:pro|flash|flash-lite)(?:[-.].*)?",
    ),
    "ark-seedance": (
        r"doubao-seed-2(?:[.-][01])?(?:[.-](?:pro|lite|mini|turbo|code|character|evolving))(?:[-.].*)?",
        r"deepseek-v4(?:[.-].*)?", r"glm-5[.-]2(?:[-.].*)?",
    ),
    "ark-agent-plan": (
        r"ark-code-latest", r"doubao-seed-2(?:[.-][01])?(?:[.-](?:pro|lite|mini|turbo|code|character|evolving))(?:[-.].*)?",
        r"deepseek-v4(?:[.-].*)?", r"glm-5[.-]3(?:[-.].*)?",
    ),
    "dashscope": (
        r"qwen3[.]8-(?:flash|max)(?:[-.].*)?", r"deepseek-v4(?:[.-].*)?",
        r"glm-5[.]3(?:[-.].*)?", r"kimi-k3",
    ),
    "minimax": (r"minimax-m3",),
    "qiniu": (
        r"(?:[^/]+/)?deepseek-v4(?:[.-].*)?", r"(?:[^/]+/)?qwen3[.]8-(?:flash|max)(?:[-.].*)?",
        r"(?:z-ai/)?glm-5[.]3(?:[-.].*)?", r"bytedance/doubao-seed-2-1-(?:pro|turbo)(?:[-.].*)?",
        r"(?:moonshotai/)?kimi-k3",
    ),
    # Both custom relay records use this preset. The relay-specific model
    # inventory decides which of these families is actually available.
    "custom-provider": (
        r"(?:[^/]+/)?deepseek-v4(?:[.-].*)?", r"(?:[^/]+/)?doubao-seed-2(?:[.-][01])?(?:[.-].*)(?:[-.].*)?",
        r"(?:[^/]+/)?qwen3[.]8-(?:flash|max)(?:[-.].*)?", r"(?:[^/]+/)?glm-5[.]3(?:[-.].*)?",
        r"(?:[^/]+/)?kimi-k3", r"(?:[^/]+/)?minimax-m3",
        r"gpt-(?:5[.]5|5[.]6|6(?:[.]1)?)(?:[-.].*)?",
        r"claude-(?:sonnet|opus)-(?:4[.-]6|4[.-]7|4[.-]8|5(?:[.-]5)?)(?:[-.].*)?",
    ),
}
_ADAPTED_TEXT_AGENT_RULES = {
    preset: tuple(re.compile(pattern) for pattern in patterns)
    for preset, patterns in _ADAPTED_TEXT_AGENT_RULES.items()
}


def _raw_model_id(row: Mapping[str, Any] | str) -> str:
    source = row if isinstance(row, Mapping) else {"id": row}
    for field in _MODEL_FIELDS:
        value = source.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip().lower().removeprefix("models/")
    return ""

# Official-service selection boundaries, reviewed 2026-10-04. See
# plugins/ai-video/docs/model-exclusion-policy.md (main repo). A match is not an adapter or
# entitlement assertion. Never apply these scopes to Qiniu or custom relays,
# or infer a service from an instance ID, adapter protocol or model vendor.
_OFFICIAL_SERVICE_SERIES = {
    "ark-seedance": r"(?:doubao|deepseek|glm)-.+",
    "ark-agent-plan": r"(?:doubao-seed|ark-code|deepseek|glm|kimi)-.+|minimax-m[0-9].*",
    "deepseek": r"deepseek-.+",
    "dashscope": (
        r"(?:qwen|qwq|qvq|wanx?|happyhorse)(?:[-_.0-9].*)?"
        r"|(?:deepseek|glm|kimi|moonshot|minimax|mimo|step|unisound)-.+"
        r"|(?:kling|vidu|pixverse|tripo)(?:[-_.0-9].*|q[0-9].*)?"
        r"|(?:tongyi|farui|decision)-.+"
        r"|(?:z-image|aitryon|facechain|shoemodel|virtualmodel|wordart)(?:[-_.].+)?"
        r"|image-(?:erase-completion|instance-segmentation|out-painting)(?:[-_.].+)?"
        r"|(?:animate-anyone|emo|emoji|liveportrait|videoretalk|video-style-transform)(?:[-_.].+)?"
    ),
    "gemini": r"(?:gemini|gemma|imagen|veo)(?:[-_.0-9].*)?",
    "minimax": r"minimax-(?:m|h)[0-9].*|(?:minimax-)?hailuo[-_.0-9].*|image-[0-9].*|[ti]2v-.+",
    "vidu": r"vidu(?:[-_.0-9].*|q[0-9].*)",
    "grok": r"grok-.+",
}
_OFFICIAL_SERVICE_SERIES_RULES = {
    service: re.compile(pattern) for service, pattern in _OFFICIAL_SERVICE_SERIES.items()
}


def normalized_model_id(row: Mapping[str, Any] | str) -> str:
    source = row if isinstance(row, Mapping) else {"id": row}
    for field in _MODEL_FIELDS:
        value = source.get(field)
        if isinstance(value, str) and value.strip():
            value = value.strip().lower().removeprefix("models/")
            if ":" in value and not value.startswith("http"):
                value = value.split(":", 1)[1]
            return value.rsplit("/", 1)[-1]
    return ""


def _numbered_version(model: str, pattern: str) -> tuple[int, int] | None:
    match = re.search(pattern, model)
    if not match:
        return None
    minor = int(match.group(2) or 0) if match.lastindex and match.lastindex >= 2 else 0
    return int(match.group(1)), minor


def model_exclusion(row: Mapping[str, Any] | str, *, output_kind: str | None = None) -> dict[str, Any]:
    """Exclude a classified capability view, or preserve any allowed output.

    Callers projecting multi-output rows pass their already classified kind.
    Without a view, explicit output metadata wins over legacy type/name hints.
    """

    model = normalized_model_id(row)
    preset = str(row.get("provider_preset_id") or "") if isinstance(row, Mapping) else ""
    route_issue = _ROUTE_UNSUPPORTED_IDS.get((preset, model))
    if route_issue:
        reason, replacement = route_issue
        return {"excluded": True, "status": "当前接口不支持",
                "reason": reason, "replacement": replacement,
                "source": LOCAL_EXCLUSION_SOURCE}
    if preset == "ark-seedance" and model in _ARK_RETIRED_IDS:
        return {"excluded": True, "status": "旧/过期排除",
                "reason": "该型号已在普通火山方舟下线，不再作为本地可选模型。",
                "replacement": "当前方舟同用途型号", "source": LOCAL_EXCLUSION_SOURCE}
    series = _OFFICIAL_SERVICE_SERIES_RULES.get(preset)
    if series is not None and not series.fullmatch(model):
        return {"excluded": True, "status": "系列范围排除",
                "reason": "该模型系列未纳入此官方服务的本地支持范围。",
                "replacement": "", "source": LOCAL_EXCLUSION_SOURCE}
    if model in _RETIRED_IDS:
        return {"excluded": True, "status": "旧/过期排除",
                "reason": "该旧型号不再作为本地可选模型。",
                "replacement": _RETIRED_IDS[model], "source": LOCAL_EXCLUSION_SOURCE}
    if re.fullmatch(r"(?:farui-plus|qwen-math-(?:plus|turbo))(?:-latest|-\d{4}(?:-\d{2}-\d{2})?)?", model):
        return {"excluded": True, "status": "用途不适用",
                "reason": "法律或数学专用模型，不用于本插件的通用创作任务。",
                "replacement": "通用文本模型", "source": LOCAL_EXCLUSION_SOURCE}
    for pattern, reason, replacement in _RETIRED_SERIES_RULES:
        if pattern.fullmatch(model):
            return {"excluded": True, "status": "旧/过期排除", "reason": reason,
                    "replacement": replacement, "source": LOCAL_EXCLUSION_SOURCE}

    # Current local custom-relay adapters target GPT-5.5+ text and GPT Image
    # 2+. This applies equally to a direct model ID and a relay ID.
    version = _numbered_version(model, r"^gpt[-_]?([0-9]+)(?:\.([0-9]+))?(?:$|[-_.])")
    if version and version < (5, 5):
        return {
            "excluded": True,
            "status": "旧/过期排除",
            "reason": "GPT 5.5 以下模型不再作为本地默认可选模型。",
            "replacement": "gpt-5.5 或更高版本",
            "source": LOCAL_EXCLUSION_SOURCE,
        }

    # GPT-4o / GPT-5o style IDs do not put a separator between the numeric
    # generation and the `o` suffix, but they are still covered by the same
    # local GPT generation boundary.
    omni_version = _numbered_version(model, r"^gpt[-_]?([0-9]+)o(?:$|[-_.])")
    if omni_version and omni_version < (5, 5):
        return {
            "excluded": True,
            "status": "旧/过期排除",
            "reason": "GPT 5.5 以下模型不再作为本地默认可选模型。",
            "replacement": "gpt-5.5 或更高版本",
            "source": LOCAL_EXCLUSION_SOURCE,
        }

    image_version = _numbered_version(model, r"^gpt[-_]?image[-_]?([0-9]+)(?:\.([0-9]+))?(?:$|[-_.])")
    if image_version and image_version < (2, 0):
        return {
            "excluded": True,
            "status": "旧/过期排除",
            "reason": "GPT Image 2 以下图片模型不再作为本地默认可选模型。",
            "replacement": "gpt-image-2",
            "source": LOCAL_EXCLUSION_SOURCE,
        }

    if model.startswith("dall-e"):
        return {
            "excluded": True,
            "status": "旧/过期排除",
            "reason": "DALL-E 系列不属于当前本地图片适配范围。",
            "replacement": "gpt-image-2",
            "source": LOCAL_EXCLUSION_SOURCE,
        }

    # The current local video contract is the Seedance 2.x/2.5 family.
    if re.search(r"(?:^|[-_/])(?:doubao[-_])?seedance[-_]1(?:[._-]0)?(?:[-_.]|$)", model):
        return {
            "excluded": True,
            "status": "旧/过期排除",
            "reason": "Seedance 1.x 视频系列不在当前本地视频适配范围。",
            "replacement": "Seedance 2.0 或 Seedance 2.5",
            "source": LOCAL_EXCLUSION_SOURCE,
        }

    # Only generations that the current local catalogs intentionally support
    # are excluded here. Unknown future models remain discoverable and are
    # handled by the separate “未适配” state.
    if re.search(r"(?:^|[-_/])(?:doubao[-_])?seedream[-_]([1-4])(?:[._-]0)?(?:[-_.]|$)", model):
        return {
            "excluded": True,
            "status": "旧/过期排除",
            "reason": "Seedream 4.0 以下图片系列不在当前本地适配范围。",
            "replacement": "Seedream 5.0",
            "source": LOCAL_EXCLUSION_SOURCE,
        }

    # Q2 shares its API ID across image and video operations. Keep the raw
    # multi-output record when it has an image view; exclude its video view.
    from utils.model_classification import classify_model

    kinds = [output_kind] if output_kind is not None else classify_model(
        {**(dict(row) if isinstance(row, Mapping) else {}), "id": model}
    )["kinds"]
    is_image = "image" in kinds
    if not is_image and re.fullmatch(r"viduq(?:1|2)(?:[-_.].*)?", model):
        return {
            "excluded": True,
            "status": "旧/过期排除",
            "reason": "Vidu Q1/Q2 系列不在当前本地视频适配范围。",
            "replacement": "Vidu Q3 系列",
            "source": LOCAL_EXCLUSION_SOURCE,
        }

    return {
        "excluded": False,
        "status": "",
        "reason": "",
        "replacement": "",
        "source": "",
    }


def adapted_model_exclusion(row: Mapping[str, Any] | str, *, output_kind: str | None = None) -> dict[str, Any]:
    """Return the local allowlist result for selectable text/agent models.

    Discovery keeps unadapted rows available for the provider test report. The
    production capability projection uses this separate check to hide them
    from model selection without losing the provider's raw directory.
    """
    if output_kind not in {"text", "agent"}:
        return {"excluded": False, "status": "", "reason": "", "replacement": "", "source": ""}
    source = row if isinstance(row, Mapping) else {"id": row}
    preset = str(source.get("provider_preset_id") or "")
    rules = _ADAPTED_TEXT_AGENT_RULES.get(preset)
    if not rules:
        return {"excluded": False, "status": "", "reason": "", "replacement": "", "source": ""}
    model = normalized_model_id(source)
    raw_model = _raw_model_id(source)
    if any(rule.fullmatch(candidate) for rule in rules for candidate in (model, raw_model)):
        return {"excluded": False, "status": "", "reason": "", "replacement": "", "source": ""}
    return {"excluded": True, "status": "未适配",
            "reason": "该文本/智能体模型系列尚未纳入本地请求适配范围。",
            "replacement": "已适配的主力模型系列", "source": LOCAL_EXCLUSION_SOURCE}


def adapted_model_is_excluded(row: Mapping[str, Any] | str, *, output_kind: str | None = None) -> bool:
    return bool(adapted_model_exclusion(row, output_kind=output_kind)["excluded"])


def model_is_excluded(row: Mapping[str, Any] | str, *, output_kind: str | None = None) -> bool:
    return bool(model_exclusion(row, output_kind=output_kind)["excluded"])


def annotate_model_exclusion(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result.update({
        "model_exclusion_status": info["status"],
        "model_exclusion_reason": info["reason"],
        "model_exclusion_replacement": info["replacement"],
        "model_exclusion_source": info["source"],
    } if (info := model_exclusion(row))["excluded"] else {})
    return result


# (provider presets, old API name, replacement API names in priority order).
# These are local selection decisions, not claims that old endpoints stopped
# working. Never broaden a dated/specialist pattern to an entire brand.
_REPLACEMENTS = (
    (("ark-seedance",), r"doubao-seed-2-0-pro(?:-\d{6})?|doubao-seed-2-1-pro-260628",
     ("doubao-seed-2-1-pro-260915",)),
    (("ark-seedance",), r"doubao-seed-2-0-lite(?:-\d{6})?",
     ("doubao-seed-2-1-lite-260915",)),
    (("ark-seedance",), r"doubao-seed-2-0-mini-260215",
     ("doubao-seed-2-0-mini-260428",)),
    (("dashscope", "qiniu", "custom-provider"), r"qwen3\.7-max(?:-preview|-\d{4}(?:-\d{2}-\d{2})?)?",
     ("qwen3.8-max", "qwen3.8-max-0902")),
    (("dashscope", "qiniu", "custom-provider"), r"qwen(?:3(?:\.[56])?-max|-max)(?:-latest|-preview|-\d{4}(?:-\d{2}-\d{2})?)?",
     ("qwen3.8-max",)),
    (("dashscope", "qiniu", "custom-provider"), r"qwen(?:3\.[56]-plus|-plus)(?:-latest|-\d{4}(?:-\d{2}-\d{2})?)?",
     ("qwen3.7-plus",)),
    (("dashscope", "qiniu", "custom-provider"), r"qwen(?:3\.[567]-flash|-flash)(?:-latest|-\d{4}(?:-\d{2}-\d{2})?)?",
     ("qwen3.8-flash", "qwen3.7-flash")),
    (("qiniu",), r"glm-5\.2", ("glm-5.3",)),
    (("minimax", "qiniu"), r"minimax-m(?:2|2\.1|2\.5)", ("minimax-m3",)),
    (("deepseek",), r"deepseek-v4-flash(?:-vision-exp)?", ("deepseek-flash",)),
    (("dashscope",), r"qwen3\.8-max-0902", ("qwen3.8-max",)),
    (("dashscope",), r"qwen3\.7-plus-2026-05-26", ("qwen3.7-plus",)),
    (("dashscope",), r"qwen3-coder-plus-\d{4}-\d{2}-\d{2}", ("qwen3-coder-plus",)),
    (("dashscope",), r"qwen3-coder-flash-\d{4}-\d{2}-\d{2}", ("qwen3-coder-flash",)),
)
_REPLACEMENT_RULES = tuple(
    (presets, re.compile(pattern), replacements)
    for presets, pattern, replacements in _REPLACEMENTS
)


def _selection_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    value = next((str(row[key]).strip() for key in _MODEL_FIELDS
                  if isinstance(row.get(key), str) and str(row[key]).strip()), "")
    # Strip only our instance prefix. Keep the full carrier namespace so two
    # deployments of the same upstream model are never treated as one route.
    prefix = str(row.get("provider_id") or "").strip().lower() + ":"
    if prefix != ":" and value.lower().startswith(prefix):
        value = value[len(prefix):]
    namespace, _, model = value.rpartition("/")
    return namespace, model.lower()


def _declared_inputs(row: Mapping[str, Any]) -> set[str]:
    inputs: set[str] = set()
    for container in (row, row.get("architecture"), row.get("modalities"), row.get("inference_metadata")):
        if not isinstance(container, Mapping):
            continue
        values = container.get("input_modalities") or container.get("input_modality")
        if container is row.get("modalities"):
            values = values or container.get("input")
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            inputs.update(str(value).lower() for value in values)
    supports = {str(value).lower() for value in row.get("supports", [])} if isinstance(row.get("supports"), list) else set()
    if {"vision", "image_input"} & supports:
        inputs.add("image")
    return inputs - {"text"}


def annotate_model_replacements(
    rows: list[dict[str, Any]], *, output_kind: str,
) -> list[dict[str, Any]]:
    """Annotate selection exclusions without removing executable saved models.

    Run after capability projection: a text replacement cannot imply an agent
    replacement. No discovery, persisted metadata or generation payload changes.
    """
    if output_kind not in {"text", "agent"}:
        return rows
    result = [dict(row) for row in rows]
    fields = ("model_exclusion_status", "model_exclusion_reason",
              "model_exclusion_replacement", "model_exclusion_source")
    for row in result:
        # Recompute selection annotations from this directory, not saved hints.
        for field in fields:
            if row.get("model_exclusion_status") != "未适配":
                row.pop(field, None)

    def route_key(row: Mapping[str, Any]) -> tuple[str, ...]:
        route = (row.get("agent_route") or {}) if output_kind == "agent" else {}
        return (str(row.get("provider_id") or ""), str(row.get("provider_preset_id") or ""),
                _selection_identity(row)[0],
                str(route.get("baseUrl") or "") if output_kind == "agent" else str(row.get("endpoint") or ""),
                str(route.get("authMode") or "") if output_kind == "agent" else "")

    indexed = {(route_key(row), _selection_identity(row)[1]): row for row in result
               if row.get("available") is True and row.get("provider_id")}
    proposed: dict[str, dict[str, Any]] = {}
    for row in result:
        preset = str(row.get("provider_preset_id") or "")
        name = _selection_identity(row)[1]
        for presets, pattern, targets in _REPLACEMENT_RULES:
            if preset not in presets or not pattern.fullmatch(name):
                continue
            replacement = next((candidate for target in targets
                                if (candidate := indexed.get((route_key(row), target))) is not None
                                and _declared_inputs(row) <= _declared_inputs(candidate)), None)
            if replacement is not None and replacement.get("id") != row.get("id"):
                proposed[str(row["id"])] = replacement
            break
    # Resolve chains (old generation -> dated version -> current alias) to a
    # visible terminal. A malformed cycle must never empty a provider's list.
    for row in result:
        replacement = proposed.get(str(row.get("id")))
        visited = {str(row.get("id"))}
        while replacement is not None and str(replacement.get("id")) in proposed:
            key = str(replacement["id"])
            if key in visited:
                replacement = None
                break
            visited.add(key)
            replacement = proposed[key]
        if replacement is None:
            continue
        replacement_name = str(replacement.get("label") or replacement["id"])
        row.update({
            "model_exclusion_status": "已替代",
            "model_exclusion_reason": f"已有同用途替代模型：{replacement_name}",
            "model_exclusion_replacement": str(replacement["id"]),
            "model_exclusion_source": LOCAL_EXCLUSION_SOURCE,
        })
    return result
