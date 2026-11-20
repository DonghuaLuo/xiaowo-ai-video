# -*- coding: utf-8 -*-
"""视觉风格图片分析的供应商协议与结果规范化。"""
from __future__ import annotations

from utils.model_reasoning import apply_model_reasoning

from .catalogs import STYLE_ANALYSIS_PROMPT
from .model_provider_config import _api_model_name
from .model_provider_config import _openai_compatible_generation_base_url
from .model_provider_config import _provider_base_url
from .model_text_client import _extract_anthropic_response_text
from .model_text_client import _extract_gemini_response_text
from .model_text_client import _extract_response_text
from .model_text_client import _post_json
from .model_text_client import _raise_for_text_output_limit
from .provider_connections import _anthropic_messages_auth_headers
from .provider_connections import _anthropic_messages_url
from .provider_connections import _google_discovery_root_url
from .provider_connections import _provider_default_base_url
from .provider_connections import _request_json
from .provider_models import _text_model_generation_endpoint
from .provider_models import _model_reference_image_input_limits
from .provider_models import _model_supports_vision_input
from .provider_models import _provider_service_id
from .provider_reference_media import _data_url_base64_payload
from .provider_reference_media import _provider_image_data_url_from_data_url
from .provider_reference_media import _provider_image_data_url_from_file_info
from typing import Any, Callable
from utils.media_backends import normalize_media_endpoint
from utils.model_timeouts import MODEL_STYLE_ANALYSIS_TIMEOUT_SECONDS
import json
import re
import urllib.error
import urllib.request

def _style_analysis_text_from_payload(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text[:1] in {"{", "["}:
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            for key in (
                "style_description",
                "styleDescription",
                "stylePrompt",
                "style_prompt",
                "description",
                "prompt",
                "style",
            ):
                item = payload.get(key)
                if isinstance(item, str) and item.strip():
                    return item.strip()
        if isinstance(payload, list):
            rows = [str(item).strip() for item in payload if str(item or "").strip()]
            if rows:
                return "，".join(rows)
    return text


def _strip_unapproved_latin_text(text: str) -> str:
    allowed: dict[str, str] = {}

    def keep(match: re.Match[str]) -> str:
        key = f"§允许{len(allowed)}§"
        allowed[key] = match.group(0).upper()
        return key

    protected = re.sub(r"(?<![A-Za-z0-9])(?:2D|3D|CG|PBR)(?![A-Za-z0-9])", keep, text, flags=re.I)
    protected = re.sub(r"[A-Za-z][A-Za-z0-9+._/-]*", "", protected)
    for key, value in allowed.items():
        protected = protected.replace(key, value)
    return protected


def _drop_forbidden_style_analysis_segments(text: str) -> str:
    def clean_segments(value: str) -> str:
        segments = [segment.strip() for segment in re.split(r"[，；。]+", value) if segment.strip()]
        return "，".join(
            segment for segment in segments
            if not any(term in segment for term in _STYLE_ANALYSIS_FORBIDDEN_SEGMENT_TERMS)
        )

    if "统一美术风格：" not in text:
        return clean_segments(text)

    before_style, style_text = text.split("统一美术风格：", 1)
    before_style = clean_segments(before_style.strip("，；。"))
    style_text = clean_segments(style_text.strip("，；。"))
    if before_style and style_text:
        return f"{before_style}，统一美术风格：{style_text}"
    if style_text:
        return f"统一美术风格：{style_text}"
    return before_style


def _normalize_style_analysis_output(value: Any) -> str:
    text = _style_analysis_text_from_payload(value)
    if not text:
        return ""
    text = text.replace("\r", "\n")
    text = re.sub(r"```(?:[A-Za-z0-9_-]+)?", "", text).replace("```", "")
    rows: list[str] = []
    for line in text.splitlines():
        line = line.strip().strip("`\"'“”‘’")
        line = re.sub(r"^[\s\-*•·\d.、]+", "", line).strip()
        if not line:
            continue
        if re.match(r"^(?:以下|下面|分析结果|输出|result|style analysis)\b", line, re.I):
            continue
        rows.append(line)
    text = "，".join(rows) if rows else text.strip()
    for pattern, replacement in _STYLE_ANALYSIS_ENGLISH_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.I)
    text = re.sub(r"\bvisual\s+style\s*[:：]\s*", "视觉风格：", text, flags=re.I)
    text = re.sub(r"\bstyle\s*[:：]\s*", "风格：", text, flags=re.I)
    text = re.sub(r"^\s*(?:视觉风格|风格|画风)\s*[:：]\s*", "统一美术风格：", text)
    text = re.sub(r"([，,；;。])\s*(?:视觉风格|风格|画风)\s*[:：]\s*", r"\1统一美术风格：", text)
    text = text.translate(str.maketrans({",": "，", ";": "；", ":": "："}))
    text = _strip_unapproved_latin_text(text)
    text = re.sub(r"\s+", "", text)
    text = _drop_forbidden_style_analysis_segments(text)
    text = re.sub(r"[，；。]{2,}", "，", text)
    text = re.sub(r"([：，；。])([，；。])+", r"\1", text)
    text = re.sub(r"：([，；。])", "：", text)
    text = text.strip("，；。 \t\r\n")
    return text


def _style_analysis_output_has_required_fields(text: str) -> bool:
    if not text.startswith("画面类型：") or "统一美术风格：" not in text:
        return False
    visual_type, style_text = text.split("统一美术风格：", 1)
    visual_type = visual_type.removeprefix("画面类型：").strip("，；。 \t\r\n")
    style_text = style_text.strip("，；。 \t\r\n")
    return bool(visual_type and style_text)


def _call_openai_compatible_style_analysis(
    provider: dict[str, Any],
    provider_id: str,
    base_url: str,
    model_name: str,
    data_url: str,
    api_key: str,
    endpoint: str | None = None,
) -> str:
    generation_base_url = _openai_compatible_generation_base_url(
        provider,
        provider_id,
        base_url,
    )
    normalized_endpoint = normalize_media_endpoint(endpoint)
    if normalized_endpoint == "openai-responses":
        use_responses = True
    elif normalized_endpoint == "openai-chat":
        use_responses = False
    else:
        use_responses = provider_id == "openai" and re.search(r"(^|[-_:/])gpt[-_]?5", model_name, re.I)
    if use_responses:
        payload = {
            "model": model_name,
            "max_output_tokens": 4096,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": STYLE_ANALYSIS_PROMPT},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        }
        apply_model_reasoning(
            payload, base_url=generation_base_url, model=model_name,
            endpoint="openai-responses", task="style-analysis",
        )
        data = _post_json(
            f"{generation_base_url}/responses",
            payload,
            api_key,
            timeout=MODEL_STYLE_ANALYSIS_TIMEOUT_SECONDS,
        )
    else:
        payload = {
            "model": model_name,
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": STYLE_ANALYSIS_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        }
        apply_model_reasoning(
            payload, base_url=generation_base_url, model=model_name,
            endpoint="openai-chat", task="style-analysis",
        )
        data = _post_json(
            f"{generation_base_url}/chat/completions",
            payload,
            api_key,
            timeout=MODEL_STYLE_ANALYSIS_TIMEOUT_SECONDS,
        )
    _raise_for_text_output_limit(data)
    return _extract_response_text(data)


def _call_anthropic_style_analysis(
    provider: dict[str, Any],
    base_url: str,
    model_name: str,
    data_url: str,
    api_key: str,
) -> str:
    image_data, mime = _data_url_base64_payload(data_url)
    payload = {
        "model": model_name,
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": STYLE_ANALYSIS_PROMPT},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": image_data,
                        },
                    },
                ],
            }
        ],
    }
    apply_model_reasoning(
        payload, base_url=base_url, model=model_name,
        endpoint="anthropic-messages", task="style-analysis",
    )
    data = _request_json(
        "POST",
        _anthropic_messages_url(base_url),
        headers=_anthropic_messages_auth_headers(provider, api_key, base_url),
        data=payload,
        timeout=MODEL_STYLE_ANALYSIS_TIMEOUT_SECONDS,
    )
    _raise_for_text_output_limit(data)
    return _extract_anthropic_response_text(data)


def _call_gemini_style_analysis(
    base_url: str,
    model_name: str,
    data_url: str,
    api_key: str,
) -> str:
    image_data, mime = _data_url_base64_payload(data_url)
    root = _google_discovery_root_url(base_url or _provider_default_base_url("gemini"))
    model_resource = model_name if model_name.startswith("models/") else f"models/{model_name}"
    url = f"{root}/v1beta/{model_resource}:generateContent"
    payload = {
        "generationConfig": {"maxOutputTokens": 4096},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": STYLE_ANALYSIS_PROMPT},
                    {
                        "inlineData": {
                            "mimeType": mime,
                            "data": image_data,
                        }
                    },
                ],
            }
        ]
    }
    apply_model_reasoning(payload, base_url=root, model=model_name,
                          endpoint="gemini-generate", task="style-analysis")
    data = _request_json(
        "POST",
        url,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        data=payload,
        timeout=MODEL_STYLE_ANALYSIS_TIMEOUT_SECONDS,
    )
    _raise_for_text_output_limit(data)
    return _extract_gemini_response_text(data)


def _call_style_analysis_model(
    provider: dict[str, Any],
    model: dict[str, Any],
    file_info: dict[str, Any],
    project_id: str | None = None,
) -> str:
    if not _model_supports_vision_input(model):
        raise RuntimeError("当前文本模型不支持图片输入，请选择支持视觉输入的文本模型")
    api_key = str(provider.get("api_key") or provider.get("apiKey") or "").strip()
    if not api_key:
        raise RuntimeError(f"{provider.get('key_label') or provider.get('keyLabel') or 'API_KEY'} 为空")
    base_url = _provider_base_url(provider)
    if not base_url:
        raise RuntimeError("供应商 Base URL 为空")
    data_url = _provider_image_data_url_from_file_info(
        project_id,
        file_info,
        purpose="style-analysis",
        image_input_limits=_model_reference_image_input_limits(model),
    )
    if not data_url:
        raise RuntimeError("请先上传风格参考图")
    data_url = _provider_image_data_url_from_data_url(
        data_url,
        purpose="style-analysis-request",
        image_input_limits=_model_reference_image_input_limits(model),
    )
    model_name = _api_model_name(model.get("id"))
    provider_id = _provider_service_id(provider)
    endpoint = _text_model_generation_endpoint(provider, model)
    if endpoint == "gemini-generate":
        text = _call_gemini_style_analysis(
            base_url,
            model_name,
            data_url,
            api_key,
        )
    elif endpoint == "anthropic-messages":
        text = _call_anthropic_style_analysis(
            provider,
            base_url,
            model_name,
            data_url,
            api_key,
        )
    else:
        text = _call_openai_compatible_style_analysis(
            provider,
            provider_id,
            base_url,
            model_name,
            data_url,
            api_key,
            endpoint=endpoint,
        )
    text = _normalize_style_analysis_output(text)
    if not _style_analysis_output_has_required_fields(text):
        raise RuntimeError("模型未返回结构化全局视觉风格描述")
    return text


_STYLE_ANALYSIS_ENGLISH_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\blive[-\s]?action\b", "真人影视"),
    (r"\bhyper[-\s]?realistic\b", "超写实"),
    (r"\bphoto[-\s]?realistic\b", "照片级写实"),
    (r"\bpbr\b", "PBR写实"),
    (r"\bstylized\s+realism\b", "风格化写实"),
    (r"\bstylized\s+realistic\b", "风格化写实"),
    (r"\bpixar\b", "美式3D卡通"),
    (r"\bdisney\b", "美式3D卡通"),
    (r"\blow\s+poly\b", "低多边形"),
    (r"\bnpr\b", "非真实感渲染"),
    (r"\btoon\s+shad(?:ed|ing)\b", "卡通渲染"),
    (r"\brealistic\b", "写实"),
    (r"\banime\b", "动漫"),
    (r"\bmanga\b", "漫画"),
    (r"\bcartoon\b", "卡通动画"),
    (r"\bcel[-\s]?shad(?:ed|ing)\b", "赛璐璐渲染"),
    (r"\billustration\b", "插画"),
    (r"\bconcept\s+art\b", "概念美术"),
    (r"\bdigital\s+painting\b", "数字绘画"),
)


_STYLE_ANALYSIS_FORBIDDEN_SEGMENT_TERMS: tuple[str, ...] = (
    "环境",
    "场景",
    "背景",
    "建筑",
    "室内",
    "室外",
    "陈设",
    "天气",
    "雾",
    "云",
    "烟尘",
    "烟雾",
    "光线",
    "布光",
    "打光",
    "逆光",
    "强光",
    "柔光",
    "硬光",
    "灰光",
    "辉光",
    "光影",
    "阴影",
    "高光",
    "光晕",
    "明亮",
    "昏暗",
    "暗调",
    "色彩",
    "色调",
    "调色",
    "配色",
    "冷色",
    "暖色",
    "冷暖",
    "冷紫",
    "紫蓝",
    "蓝调",
    "暖金",
    "饱和",
    "材质",
    "纹理",
    "肌理",
    "质感",
    "金属",
    "织物",
    "皮肤",
    "反光",
    "湿润",
    "粗粝",
    "旧化",
    "颗粒",
    "胶片",
    "粒子",
    "特效",
    "镜头",
    "构图",
    "视角",
    "景别",
    "景深",
    "虚化",
    "近景",
    "远景",
    "特写",
    "横屏",
    "竖屏",
    "分辨率",
    "画幅",
    "道具",
    "服装",
    "服饰",
    "妆发",
    "物体",
    "品牌",
    "文字",
    "电影",
    "摄影",
    "拍摄",
    "实拍",
    "影像",
    "影视级",
    "影视化",
    "机械",
    "机甲",
    "硬表面",
    "偶像剧",
    "剧集",
    "电视剧",
    "电影级",
    "电影感",
    "历史",
    "史诗",
    "古典",
    "宫廷",
    "民国",
    "都市",
    "时代",
    "世界观",
    "剧情",
    "人物",
    "人像",
    "角色",
    "生物",
    "比例",
    "面部",
    "五官",
    "脸型",
    "年龄",
    "体型",
    "清秀",
    "俊美",
    "硬朗",
    "成熟",
    "成人",
    "少年",
    "少女",
    "美型",
)
