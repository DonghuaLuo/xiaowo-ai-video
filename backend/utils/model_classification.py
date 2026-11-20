"""Pure catalog classification; no discovery, routing or agent verification.

Rules and primary sources: plugins/ai-video/docs/model-classification-sources.md
(in the main repository).
Names provide candidates only. Unknown entries must remain in the catalog.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, TypedDict

__all__ = ["ModelClassification", "classify_model"]


class ModelClassification(TypedDict):
    id: str
    vendor: str
    vendor_source: str
    vendor_rule: str
    kinds: list[str]
    source: str
    rule: str


_KIND_ORDER = ("video", "image", "text", "three_d", "speech", "audio", "embedding", "rerank", "unknown")
_OUTPUT_FIELDS = (
    "output_modalities", "outputModalities", "response_modality",
    "response_modalities", "responseModalities",
)
_KIND_ALIASES = {
    **{kind: kind for kind in _KIND_ORDER},
    "llm": "text", "lrm": "text", "vlm": "text",
    "textgeneration": "text", "imagegeneration": "image",
    "videogeneration": "video", "audiogeneration": "audio",
    "speechgeneration": "speech", "tts": "speech", "asr": "speech",
    "stt": "speech", "texttospeech": "speech", "speechtotext": "speech",
    "embeddings": "embedding", "textembedding": "embedding",
    "multimodalembedding": "embedding", "reranking": "rerank",
    "reranker": "rerank",
    "3d": "three_d", "threed": "three_d", "three-dimensional": "three_d",
}

# These names describe catalog attribution, never verified upstream identity.
# In particular, relay/service names and '*-compatible' are not aliases.
_VENDOR_ALIASES = {
    "openai": ("openai",),
    "anthropic": ("anthropic",),
    "google": ("google", "googleai", "google-deepmind", "gemini"),
    "volcengine": ("volcengine", "bytedance", "doubao", "ark"),
    "alibaba": ("alibaba", "aliyun", "aliyun-bailian", "dashscope", "qwen", "qwenlm", "qwen-domain-model", "wan", "happyhorse"),
    "vidu": ("vidu", "shengshu"),
    "minimax": ("minimax", "mini-max"),
    "deepseek": ("deepseek", "deepseek-ai"),
    "xai": ("xai", "x.ai", "grok"),
    "moonshot": ("moonshot", "moonshotai", "moonshot-ai", "kimi"),
    "zhipu": ("zhipu", "zhipuai", "zhipu-ai", "z.ai", "zai", "zai-org", "thudm"),
    "kling": ("kling", "klingai", "kuaishou"),
    "meta": ("meta", "meta-llama"),
    "mistral": ("mistral", "mistralai"),
    "stepfun": ("stepfun",),
    "meituan": ("meituan", "longcat"),
    "tencent": ("tencent", "hunyuan"),
    "black-forest-labs": ("black-forest-labs", "bfl"),
    "stability": ("stability", "stabilityai"),
    "baai": ("baai",),
    "xiaomi": ("xiaomi", "mimo"),
    "pixverse": ("pixverse",),
    "unisound": ("unisound",),
}
_VENDOR_FAMILIES = {
    "openai": r"^(?:(?:chat)?gpt[-_]|o[1-9][0-9]*(?:$|[-_.])|dall[-_]e(?:$|[-_])|sora(?:$|[-_.0-9])|whisper[-_])",
    "anthropic": r"^(?:(?:[a-z]{2}\.)?anthropic\.)?claude[-_]",
    "google": r"^(?:gemini|gemma|imagen|veo)(?:$|[-_.0-9])",
    "volcengine": r"^(?:doubao[-_]|seedream(?:$|[-_.0-9])|seedance(?:$|[-_.0-9])|ark[-_]code(?:$|[-_])|(?:hyper3d|hitem3d)(?:$|[-_.0-9]))",
    "alibaba": r"^(?:qwen(?:$|[-_.0-9])|qwq[-_]|wanx?(?:$|[-_.0-9])|happyhorse[-_]|cosyvoice(?:$|[-_.0-9]))",
    "vidu": r"^vidu(?:$|[-_.0-9]|q[0-9])",
    "minimax": r"^(?:minimax[-_]|hailuo(?:$|[-_.0-9])|abab[0-9])",
    "deepseek": r"^deepseek[-_]",
    "xai": r"^grok[-_]",
    "moonshot": r"^(?:kimi|moonshot)[-_]",
    "zhipu": r"^(?:glm[-_]|chatglm[0-9-]|cogview(?:$|[-_.0-9])|cogvideo(?:x|$|[-_.0-9]))",
    "kling": r"^kling(?:$|[-_.0-9])",
    "meta": r"^llama[-_.]?[0-9]",
    "mistral": r"^(?:mistral|mixtral|codestral|pixtral|voxtral|devstral|ministral)[-_]",
    "stepfun": r"^step[-_][0-9]",
    "meituan": r"^longcat[-_]",
    "tencent": r"^(?:hy[0-9]|hunyuan[-_])",
    "black-forest-labs": r"^flux(?:$|[-_.0-9])",
    "stability": r"^stable[-_]diffusion(?:$|[-_.0-9])",
    "baai": r"^bge[-_]",
}

# Each vendor owns its media exceptions and language-series boundary.
_VENDOR_MEDIA = {
    "openai": (
        ("image.gpt-dalle", "image", r"^(?:(?:chat)?gpt[-_]image(?:$|[-_.0-9])|dall[-_]e(?:$|[-_.0-9]))"),
        ("video.sora", "video", r"^sora(?:$|[-_.0-9])"),
    ),
    "google": (
        ("image.gemini", "image", r"^gemini[-_].*[-_]image(?:$|[-_])"),
        ("image.imagen", "image", r"^imagen(?:$|[-_.0-9])"),
        ("video.veo", "video", r"^veo(?:$|[-_.0-9])"),
    ),
    "volcengine": (
        ("image.seedream", "image", r"^(?:doubao[-_])?seedream(?:$|[-_.0-9])"),
        ("video.seedance", "video", r"^(?:doubao[-_])?seedance(?:$|[-_.0-9])"),
    ),
    "alibaba": (
        ("video.wan-happyhorse", "video", r"^(?:wanx?|happyhorse)[0-9.]*[-_](?:.*[-_])?(?:t2v|i2v|r2v|s2v|vace|video)(?:$|[-_])"),
        ("image.qwen-wan", "image", r"^(?:qwen|wanx?)[0-9.]*[-_]image(?:$|[-_])"),
        ("image.wanx-legacy", "image", r"^wanx[-_](?:v[0-9]|sketch|style|background)(?:$|[-_.0-9])"),
    ),
    "vidu": (
        ("image.vidu-reference2image", "image", r"^vidu(?:[-_]?q[0-9.]+|[0-9.]+)[-_].*reference2image(?:$|[-_])"),
        ("image.vidu", "image", r"^vidu[-_]?q[0-9.]+[-_]image(?:$|[-_])"),
        ("video.vidu", "video", r"^vidu(?:[-_]?q[0-9.]+|[0-9.]+|[-_]s[0-9.]+[-_](?:avatar|editing))(?:$|[-_])"),
    ),
    "minimax": (
        ("video.minimax", "video", r"^(?:(?:minimax[-_])?hailuo(?:$|[-_.0-9])|minimax[-_]h[0-9]|[ti]2v[-_])"),
        ("image.minimax", "image", r"^(?:minimax[-_])?image[-_][0-9]+(?:$|[-_.])"),
    ),
    "xai": (
        ("video.grok", "video", r"^grok[-_](?:imagine[-_])?video(?:$|[-_.0-9])"),
        ("image.grok", "image", r"^grok[-_](?:imagine[-_]|[0-9.]+[-_])?image(?:$|[-_])"),
    ),
    "kling": (
        ("image.kling-explicit", "image", r"^kling[-_]image(?:$|[-_./0-9])"),
        ("video.kling-explicit", "video", r"^kling[-_]video(?:$|[-_./0-9])"),
    ),
    "zhipu": (
        ("image.cogview", "image", r"^cogview(?:$|[-_.0-9])"),
        ("video.cogvideo", "video", r"^cogvideo(?:x|$|[-_.0-9])"),
    ),
    "black-forest-labs": (("image.flux", "image", r"^flux(?:$|[-_.0-9])"),),
    "stability": (("image.diffusion", "image", r"^stable[-_]diffusion(?:$|[-_.0-9])"),),
    "mistral": (("speech.voxtral", "speech", r"^voxtral[-_]"),),
    "unknown": (("image.generic-series", "image", r"^image[-_][0-9]+(?:$|[-_.])"),),
}
_VENDOR_TEXT = {
    "openai": r"^(?:(?:chat)?gpt[-_](?:[0-9]|latest(?:$|[-_])|oss(?:$|[-_]))|o[1-9][0-9]*(?:$|[-_.])|codex(?:$|[-_.-]))",
    "anthropic": _VENDOR_FAMILIES["anthropic"],
    "google": r"^(?:gemini[-_](?:[0-9]|latest(?:$|[-_]))|gemma[-_][0-9])",
    "volcengine": r"^(?:doubao[-_](?:seed[-_]|[0-9]|pro(?:$|[-_])|lite(?:$|[-_])|vision(?:$|[-_])|thinking(?:$|[-_]))|ark[-_]code(?:$|[-_]))",
    "alibaba": r"^qwen(?:[0-9]+(?:\.[0-9]+)*|[-_](?:plus|max|turbo|long|vl|coder|mt))(?:$|[-_])|^qwq[-_]",
    "minimax": r"^(?:minimax[-_](?:m[0-9]|(?:text|vl)[-_][0-9])|abab[0-9])",
    "deepseek": r"^deepseek[-_](?:v[0-9]|r[0-9]|chat(?:$|[-_])|reasoner(?:$|[-_])|flash(?:$|[-_])|coder(?:$|[-_]))",
    "xai": r"^grok[-_][0-9]",
    "moonshot": _VENDOR_FAMILIES["moonshot"],
    "zhipu": r"^(?:glm[-_][0-9]|chatglm[0-9-])",
    "meta": _VENDOR_FAMILIES["meta"],
    "mistral": r"^(?:mistral|mixtral|codestral|pixtral|devstral|ministral)[-_]",
    "stepfun": _VENDOR_FAMILIES["stepfun"],
    "meituan": r"^longcat[-_](?:flash|think)",
    "tencent": r"^(?:hy[0-9]|hunyuan[-_](?:turbo|large|standard|lite|pro|a13b|t1|turbos)(?:$|[-_]))",
}
_RETRIEVAL_RULES = (
    ("retrieval.rerank", "rerank", r"(?:^|[-_./:])rerank(?:er|ing)?(?:$|[-_./:0-9])"),
    ("retrieval.embedding", "embedding", r"(?:^|[-_./:])(?:embeddings?|embed)(?:$|[-_./:0-9])"),
    ("retrieval.bge-e5", "embedding", r"^(?:bge|e5|multilingual-e5)[-_.]"),
)
_NON_TEXT_RULES = (
    ("speech.dedicated", "speech", r"(?:^|[-_./:])(?:tts|asr|stt|speech|whisper|transcribe|transcription|cosyvoice|voice)(?:$|[-_./:0-9])"),
    ("audio.music", "audio", r"^(?:minimax[-_])?music(?:$|[-_.0-9])|^audio[0-9]+(?:$|[.-])"),
    ("audio.dedicated", "audio", r"(?:^|[-_./:])(?:audio|realtime)(?:$|[-_./:0-9])"),
    ("ambiguous.omni-live", "unknown", r"(?:^|[-_./:])(?:omni|live)(?:$|[-_./:0-9])"),
    ("guard.nontext", "unknown", r"(?:^|[-_./:])(?:image|video|img|visiongen|moderation|safety|ocr|segmentation|detection)(?:$|[-_./:0-9])"),
)


def _vendor_alias(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    return next((vendor for vendor, aliases in _VENDOR_ALIASES.items() if token in aliases), None)


def _vendor(row: Mapping[str, Any], name: str) -> tuple[str, str, str]:
    leaf = name.rsplit("/", 1)[-1]
    named = next((vendor for vendor, pattern in _VENDOR_FAMILIES.items() if re.search(pattern, leaf)), None)
    namespace = _vendor_alias(name.split("/", 1)[0]) if "/" in name else None
    asserted = [(field, _vendor_alias(row.get(field))) for field in (
        "vendor", "model_vendor", "manufacturer", "owned_by",
    )]
    asserted = [(field, vendor) for field, vendor in asserted if vendor is not None]
    hints = [(field, _vendor_alias(row.get(field))) for field in (
        "inference_provider", "provider",
    )]
    hints = [(field, vendor) for field, vendor in hints if vendor is not None]
    if len({vendor for _, vendor in asserted}) > 1:
        return "unknown", "conflict", "vendor.conflicting-metadata"
    if asserted:
        field, vendor = asserted[0]
        return vendor, f"metadata:{field}", "vendor.known-alias"
    # Provider/inference_provider often names the hosting platform. Use it
    # only when the model namespace and series provide no stronger identity.
    if named:
        return named, "series-regex", f"vendor.{named}"
    if namespace:
        return namespace, "name-namespace", "vendor.known-namespace"
    if len({vendor for _, vendor in hints}) == 1 and hints:
        field, vendor = hints[0]
        return vendor, f"metadata:{field}", "vendor.hosting-alias"
    if len({vendor for _, vendor in hints}) > 1:
        return "unknown", "conflict", "vendor.conflicting-hosting-hints"
    return "unknown", "unknown", "vendor.no-evidence"


def _series_kind(vendor: str, name: str) -> tuple[list[str], str, str]:
    names = (name, name.rsplit("/", 1)[-1])
    rules = (*_RETRIEVAL_RULES, *_VENDOR_MEDIA.get(vendor, ()), *_NON_TEXT_RULES)
    for rule, kind, pattern in rules:
        if any(re.search(pattern, value) for value in names):
            return [kind], "series-regex", rule
    pattern = _VENDOR_TEXT.get(vendor)
    if pattern and any(re.search(pattern, value) for value in names):
        return ["text"], "series-regex", f"text.{vendor}"
    return ["unknown"], "unknown", "unknown.no-vendor-series"


def _kind(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    token = re.sub(r"[-_\s]", "", value.strip().lower())
    return _KIND_ALIASES.get(token, "unknown")


def _outputs(value: Any) -> list[str] | None:
    if value is None or value == "" or value == [] or value == ():
        return None
    values = value if isinstance(value, (list, tuple)) else [value]
    kinds = {_kind(item) for item in values}
    return [kind for kind in _KIND_ORDER if kind in kinds]


def _explicit_metadata(row: Mapping[str, Any]) -> tuple[list[str], str, str] | None:
    containers = [("", row)]
    containers.extend(
        (f"{key}.", row[key])
        for key in ("modalities", "architecture", "inference_metadata")
        if isinstance(row.get(key), Mapping)
    )
    for prefix, container in containers:
        fields = (*_OUTPUT_FIELDS, "output") if prefix == "modalities." else _OUTPUT_FIELDS
        for field in fields:
            kinds = _outputs(container.get(field))
            if kinds is not None:
                return kinds, f"metadata:{prefix}{field}", "explicit.output"
    for field in ("media_type", "domain", "type"):
        value = row.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if field == "type" and isinstance(value, str) and value.strip().lower() == "model":
            continue
        return [_kind(value)], f"metadata:{field}", "explicit.kind"
    return None


def classify_model(
    row: Mapping[str, Any] | str,
    *,
    list_kind: str | None = None,
    list_source: str | None = None,
) -> ModelClassification:
    """Classify one original discovery row without changing it or its ID.

    Identify catalog vendor first (not verified upstream identity), then use
    explicit output metadata, named scoped list, or that vendor's series.
    Pass both list_kind and list_source only for a documented kind-specific
    list, never for a generic /models response or a requested UI capability.
    source records the winning field/list; rule records the stable rule ID.
    A text result is a candidate, not a tool-use or agent compatibility claim.
    """
    if (list_kind is None) != (list_source is None):
        raise ValueError("list_kind and list_source must be supplied together")
    if list_kind is not None and (
        list_kind not in _KIND_ORDER or list_kind == "unknown"
        or not isinstance(list_source, str) or not list_source.strip()
    ):
        raise ValueError("a scoped list requires a canonical kind and nonempty source")
    if isinstance(row, str):
        row = {"id": row}
    if not isinstance(row, Mapping):
        raise TypeError("row must be a model ID string or mapping")
    model_id = next(
        (row[key] for key in ("id", "model_id", "api_model_id", "name", "model")
         if isinstance(row.get(key), str) and row[key].strip()),
        "",
    )
    name = model_id.strip().lower()
    vendor, vendor_source, vendor_rule = _vendor(row, name)
    evidence = _explicit_metadata(row)
    if evidence is not None:
        kinds, source, rule = evidence
    elif list_kind is not None:
        kinds, source, rule = [list_kind], f"scoped-list:{list_source}", "scoped.kind"
    else:
        kinds, source, rule = _series_kind(vendor, name)
    return {
        "id": model_id, "vendor": vendor, "vendor_source": vendor_source,
        "vendor_rule": vendor_rule, "kinds": kinds, "source": source, "rule": rule,
    }
