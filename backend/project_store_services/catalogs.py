# -*- coding: utf-8 -*-
"""常量目录、结构化 schema、模型目录、默认模板和默认资产。"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.cinematic_script_templates import script_adaptation_templates

from utils.agent_context import (
    AGENT_CONTEXT_MESSAGE_TEXT_LIMIT,
    AGENT_CONTEXT_RECENT_WINDOW,
    AGENT_CONTEXT_SUMMARY_CHARS,
    build_agent_conversation_context,
)
from utils import agent_sdk_runtime
from utils.agent_session_service import AgentSessionService
from utils.aspect_size import (
    IMAGE_TIER_SHORT_EDGE,
    VIDEO_TIER_SHORT_EDGE,
    aspect_size,
    image_generation_preset,
    image_size_for_preset,
    parse_aspect_ratio,
    resolution_to_short_edge,
)
from utils.image_pipeline import (
    PROVIDER_IMAGE_INPUT_DEFAULT_MAX_BYTES,
    PROVIDER_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE,
    convert_image_bytes_to_png,
    data_url_from_bytes,
    prepare_provider_image_bytes,
    prepare_provider_image_data_uri,
    save_project_image,
    save_provider_output_image,
)
from utils.image_resolution_schema import image_resolution_schema_for_model
from utils.media_backends import (
    cancel_video_media_job,
    endpoint_supports_media_generation,
    infer_model_endpoint,
    media_endpoint_type,
    normalize_media_endpoint,
    generate_image_media,
    generate_video_media,
    poll_video_media_job,
    provider_supports_media_generation,
    submit_video_media_job,
)
from utils.video_model_capabilities import (
    ARK_SEEDANCE_2_VIDEO_CAPABILITY_METADATA,
    ARK_SEEDANCE_25_VIDEO_CAPABILITY_METADATA,
    DASHSCOPE_WAN27_VIDEO_CAPABILITY_METADATA,
    STORYBOARD_VIDEO_MODEL_CAPABILITIES,
    VIDU_Q3_VIDEO_CAPABILITY_METADATA,
)

OPENAI_GPT_IMAGE_2_RESOLUTIONS = ["1K", "2K", "3K", "4K"]
OPENAI_GPT_IMAGE_2_DEFAULT_RESOLUTION = "2K"
OPENAI_GPT_IMAGE_REFERENCE_LIMIT_METADATA = {
    "reference_image_limit_source": "official",
    "reference_image_limit_source_url": "https://developers.openai.com/api/reference/resources/images/methods/edit/",
    "reference_image_limit_note": "OpenAI Images edit API: GPT image models accept up to 16 input images.",
}
ARK_SEEDREAM_5_REFERENCE_LIMIT_METADATA = {
    "reference_image_limit_source": "official",
    "reference_image_limit_source_url": "https://www.volcengine.com/docs/82379/1541523",
    "reference_image_limit_note": "Seedream 5.0 API supports multi-reference image input with 2-14 reference images.",
}
DASHSCOPE_QWEN_IMAGE_REFERENCE_LIMIT_METADATA = {
    "reference_image_limit_source": "official",
    "reference_image_limit_source_url": "https://help.aliyun.com/zh/model-studio/qwen-image-edit-api",
    "reference_image_limit_note": "Qwen Image Edit API content supports 1-3 input images.",
}
DASHSCOPE_WAN27_IMAGE_REFERENCE_LIMIT_METADATA = {
    "reference_image_limit_source": "official",
    "reference_image_limit_source_url": "https://help.aliyun.com/en/model-studio/wan-image-generation-and-editing-api-reference",
    "reference_image_limit_note": "Wan2.7 image generation and editing API accepts 0-9 input images.",
}
DASHSCOPE_QWEN_IMAGE_RESOLUTIONS = [
    "2048*2048",
    "2688*1536",
    "1536*2688",
    "2368*1728",
    "1728*2368",
]
DASHSCOPE_QWEN_IMAGE_DEFAULT_RESOLUTION = "2048*2048"
DASHSCOPE_QWEN_IMAGE_EDIT_RESOLUTIONS = [
    "2048*2048",
    "2048*1152",
    "1152*2048",
    "2048*1536",
    "1536*2048",
]
DASHSCOPE_QWEN_IMAGE_EDIT_DEFAULT_RESOLUTION = "2048*2048"
GEMINI_IMAGE_REFERENCE_LIMIT_METADATA = {
    "reference_image_limit_source": "official",
    "reference_image_limit_source_url": "https://ai.google.dev/gemini-api/docs/image-generation",
    "reference_image_limit_note": "Gemini 3 image models can mix up to 14 reference images.",
}
VIDU_Q2_IMAGE_REFERENCE_LIMIT_METADATA = {
    "reference_image_limit_source": "official",
    "reference_image_limit_source_url": "https://platform.vidu.com/docs/model-map",
    "reference_image_limit_note": "Vidu model map lists viduq2 image generation supported image count as 0-7 images.",
}
GROK_IMAGE_REFERENCE_LIMIT_METADATA = {
    "reference_image_limit_source": "official",
    "reference_image_limit_source_url": "https://docs.x.ai/developers/migration/imagine-image-quality-nov-2",
    "reference_image_limit_note": "Grok Imagine Image 2.0 supports up to 5 reference images per request.",
}
STANDARD_COMPATIBLE_IMAGE_RESOLUTIONS = ["1K", "2K", "3K", "4K"]
STANDARD_COMPATIBLE_VIDEO_RESOLUTIONS = ["480p", "720p", "1080p", "4K"]


def _default_image_generation_parameter(kind: str) -> dict[str, str]:
    preset = image_generation_preset(kind)
    width, height = image_size_for_preset(kind)
    return {
        "label": preset["label"],
        "aspect_ratio": preset["aspect_ratio"],
        "default_resolution": preset["default_resolution"],
        "default_size": f"{width}x{height}",
    }


DEFAULT_IMAGE_GENERATION_PARAMETERS = {
    kind: _default_image_generation_parameter(kind)
    for kind in ("character", "scene", "prop", "storyboard", "asset")
}
DEFAULT_OVERVIEW_EXCERPT_CHARS = 10000
MIN_OVERVIEW_EXCERPT_CHARS = 1000
MAX_OVERVIEW_EXCERPT_CHARS = 50000
DEFAULT_EPISODE_TARGET_UNITS = 1000
DEFAULT_ASSET_EXTRACTION_TARGET_UNITS = 5000
IMAGE_RESOLUTION_ALIASES = {
    "512px": "512px",
    "1k": "1K",
    "2k": "2K",
    "3k": "3K",
    "4k": "4K",
}
LEGACY_IMAGE_RESOLUTION_TO_TIER = {
    "1024x1024": "1K",
    "1536x1024": "1K",
    "1024x1536": "1K",
    "1280x720": "1K",
    "720x1280": "1K",
    "2048x2048": "2K",
    "2048x1152": "2K",
    "1152x2048": "2K",
    "2048x1536": "2K",
    "1536x2048": "2K",
    "2560x1440": "2K",
    "1440x2560": "2K",
    "3072x1728": "3K",
    "1728x3072": "3K",
    "3840x2160": "4K",
    "2160x3840": "4K",
    "1024x576": "1K",
    "576x1024": "1K",
    "768x1024": "1K",
    "1024x768": "1K",
    "3072x3072": "3K",
    "2304x3072": "3K",
    "3072x2304": "3K",
    "4096x4096": "4K",
    "4096x2304": "4K",
    "2304x4096": "4K",
    "3072x4096": "4K",
    "4096x3072": "4K",
}
_GPT_IMAGE_MAX_LONG_EDGE = 3840
_GPT_IMAGE_MAX_TOTAL_PIXELS = 8_294_400
_GPT_IMAGE_MAX_RATIO = 3.0
_DASHSCOPE_STANDARD_PIXEL_BUDGET = 2048 * 2048
_DASHSCOPE_FOURK_PIXEL_BUDGET = 4096 * 4096
_DASHSCOPE_EDIT_MAX_LONG_EDGE = 2048
_DASHSCOPE_MAX_RATIO = 8.0
_DASHSCOPE_EDIT_MAX_RATIO = 4.0
REFERENCE_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE = PROVIDER_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE
REFERENCE_IMAGE_INPUT_DEFAULT_MAX_BYTES = PROVIDER_IMAGE_INPUT_DEFAULT_MAX_BYTES
_REFERENCE_IMAGE_INPUT_EDGE_BY_RESOLUTION = {
    "512px": 512,
    "1K": 1024,
    "2K": 2048,
    "3K": 3072,
    "4K": 4096,
}
_VIDEO_SIZE_PRESETS: dict[str, dict[str, str]] = {
    "16:9": {
        "360p": "640x360",
        "480p": "848x480",
        "540p": "960x540",
        "720p": "1280x720",
        "1024p": "1792x1024",
        "1080p": "1920x1080",
        "4K": "3840x2160",
    },
    "9:16": {
        "360p": "360x640",
        "480p": "480x848",
        "540p": "540x960",
        "720p": "720x1280",
        "1024p": "1024x1792",
        "1080p": "1080x1920",
        "4K": "2160x3840",
    },
}
BACKEND_DIR = Path(os.getcwd()).resolve()
DATA_DIR = BACKEND_DIR / "data"
GLOBAL_DIR = DATA_DIR / "global"
PROJECTS_DIR = DATA_DIR / "projects"
AGENT_OPS_DIR = BACKEND_DIR / "agent_ops"
AGENT_OPS_CONSTRAINTS_DIR = AGENT_OPS_DIR / "constraints"
AGENT_OPS_PERMISSIONS_DIR = AGENT_OPS_DIR / "permissions"
AGENT_OPS_PROMPTS_DIR = AGENT_OPS_DIR / "prompts"
AGENT_OPS_SKILLS_DIR = AGENT_OPS_DIR / "skills"
STYLE_THUMBNAILS_DIR = BACKEND_DIR / "public" / "style-imgs"
GLOBAL_STYLE_REFERENCES_DIR = GLOBAL_DIR / "style_references"
FAVORITE_STYLE_THUMBNAILS_DIR = GLOBAL_STYLE_REFERENCES_DIR / "favorites"
GLOBAL_ASSET_MEDIA_DIR = GLOBAL_DIR / "asset_media"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".jp", ".webp"}
AGENT_IMAGE_EXTENSIONS = IMAGE_EXTENSIONS | {".gif"}
AGENT_FILE_EXTENSIONS = AGENT_IMAGE_EXTENSIONS | {".txt", ".md", ".json", ".csv", ".pdf", ".bin"}
AGENT_ATTACHMENT_MAX_BYTES = 8 * 1024 * 1024
AGENT_MODEL_IMAGE_INPUT_MAX_BYTES = 12 * 1024 * 1024
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}
MEDIA_TOOL_FILE_EXTENSIONS = (
    AGENT_FILE_EXTENSIONS
    | VIDEO_EXTENSIONS
    | {".mkv", ".avi", ".m4v", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".srt", ".ass", ".vtt"}
)
MEDIA_TOOL_DEFAULT_ROOTS = ("sources", "assets", "episodes", "exports", "generated", "media", "temp")
MEDIA_TOOL_STDIO_LIMIT = 12000
MEDIA_TOOL_MAX_ARGS = 160

STYLE_ANALYSIS_PROMPT = (
    "你是影视美术风格分析师。准确识别参考图中可复用的视觉表达。"
    "本任务只提取两类信息：1. 画面类型；2. 可跨角色、生物、场景、道具复用的统一美术风格。"
    "画面类型写媒介和呈现方式，例如真人写实、2D国漫、3D国漫、日式动画、厚涂插画或3D写实CG。"
    "统一美术风格概括渲染与造型路线，例如风格化写实、PBR写实、赛璐璐三渲二、"
    "低多边形几何化、手绘笔触或块面化造型；可补充一项具有跨画面复用价值的美术取向。"
    "从参考图提炼共同画风，不把具体主体、场景、服装、光照、色调、镜头或画幅写成全局风格。"
    "只依据可见内容判断，使用简体中文；媒介缩写可用 2D、3D、CG、PBR。"
    "只输出一行，格式为“画面类型：……，统一美术风格：……”，控制在 40 到 120 个汉字。"
)
PROJECT_OVERVIEW_STRUCTURED_SCHEMA: dict[str, Any] = {
    "name": "project_overview",
    "description": "项目概述结果：故事简介、题材语境、主题视觉和旁白声线。",
    "fields": [
        {
            "name": "excerpt_summary",
            "type": "string",
            "required": True,
            "description": "根据已读取的小说内容，用 120–220 字直接概括主角处境、关键冲突、行动目标和当前阶段结果。写成自然的故事简介，以完整句子收尾；内容只覆盖已读取范围。",
            "aliases": ["excerptSummary"],
        },
        {
            "name": "genre_context",
            "type": "string",
            "required": True,
            "description": "用 8–24 字概括故事类型与叙事推进方式，可包含宽泛的时代或世界类型。表达为可贯穿项目的题材短语，例如“东方玄幻修仙升级流”；不写具体剧情、角色或地点。",
            "aliases": ["genreContext"],
        },
        {
            "name": "theme_visual_context",
            "type": "string",
            "required": True,
            "description": "用一句简短语境确定贯穿项目的时代、地域文化或世界视觉体系，例如“唐代宫廷礼制文化语境”。它用于定位视觉世界，不承担题材叙事、阶段环境状态或具体场景设计。",
            "aliases": ["themeVisualContext"],
        },
        {
            "name": "narrator_voice_design",
            "type": "object",
            "required": True,
            "allow_missing_in_response": True,
            "description": "项目旁白的长期声音。原文明示的声音优先；角色自述遵从角色已知声音，性别未明时暂定中性听感，不凭姓名或听众身份猜测；独立旁白自行选定男声或女声。不得写角色姓名或选声理由。",
            "fields": [
                {
                    "name": "voice_base",
                    "type": "string",
                    "required": True,
                    "allow_missing_in_response": True,
                    "description": "只写可听见的基础声线：具体听觉年龄、符合叙述者身份的声音性别感、常态音区、一项辨识音色及原文明示口音。直接描述声音，不写身份标签或录音质量。",
                },
                {
                    "name": "narration_relation",
                    "type": "string",
                    "required": True,
                    "allow_missing_in_response": True,
                    "description": "根据叙述者与故事的长期关系选一项，不依据开篇情绪选，不添加剧情主题或当句表演。",
                    "enum": [
                        "贴近人物讲述剧情",
                        "从全局视角讲述剧情",
                        "以亲历者视角追述经历",
                        "以亲历者视角讲述经历",
                        "以讲述者视角铺陈传奇",
                    ],
                },
            ],
        },
    ],
}
PROJECT_NAME_EXISTS_MESSAGE = "当前项目名称已经存在，请修改其他名字"
CUSTOM_STYLE_REQUIRED_MESSAGE = "请上传风格参考图和风格描述"
MODEL_CONFIG_REQUIRED_MESSAGE = "请先在全局设置中添加供应商并配置模型"
SOURCE_LANGUAGE_OPTIONS = {"zh-CN", "zh-TW", "en-US", "vi-VN"}

STYLE_PHASE_VISUAL_KEYS = ("phaseVisuals", "phase_visuals", "stylePhaseVisuals", "style_phase_visuals")
STYLE_ACTIVE_PHASE_VISUAL_ID_KEYS = (
    "activePhaseVisualId",
    "active_phase_visual_id",
    "activeStylePhaseVisualId",
    "active_style_phase_visual_id",
)


_STYLE_THEME_VISUAL_LABEL_RE = re.compile(
    r"^\s*(?:【(?:主题视觉|视觉主题|时代地域|视觉语境)】\s*)?"
    r"(?:(?:主题视觉|视觉主题|时代地域|视觉语境)\s*[:：]\s*)?",
    re.IGNORECASE,
)
_STYLE_THEME_VISUAL_NOISE_RE = re.compile(
    r"(?:"
    r"画面类型|画风|风格|美术|设定图|分镜|镜头|构图|光影|色彩|调色|滤镜|材质|纹理|高清|高质量|"
    r"2D|3D|CG|真人|国风|国漫|日漫|美漫|美型|高颜值|帅气|漂亮|精致|华丽|"
    r"角色|人物|主角|男女|女性|男性|生物|灵兽|妖兽|怪物|"
    r"服装|服饰|穿搭|衣装|妆容|脸型|发型|家具|道具|场景|"
    r"贫民窟|贫穷|贫困|富裕|贫富|阶层|底层|上流|破败|破旧|破损|脏乱差|脏乱|"
    r"战场|破碎|打斗|受伤|成长阶段|阶段"
    r")",
    re.IGNORECASE,
)
_STYLE_THEME_VISUAL_STAGE_DETAIL_RE = re.compile(
    r"(?:"
    r"贫民窟|贫穷|贫困|富裕|贫富差距|贫富|阶层|底层|上流|破败|破旧|破损|脏乱差|脏乱|"
    r"战场|破碎|打斗|受伤|成长阶段|阶段|"
    r"角色|人物|主角|男女|女性|男性|生物|灵兽|妖兽|怪物|"
    r"服装|服饰|穿搭|衣装|妆容|脸型|发型|家具|道具|场景|"
    r"画面类型|画风|风格|美术|设定图|分镜|镜头|构图|光影|色彩|调色|滤镜|材质|纹理|高清|高质量|"
    r"2D|3D|CG|真人|国风|国漫|日漫|美漫|美型|高颜值|帅气|漂亮|精致|华丽"
    r")",
    re.IGNORECASE,
)
_STYLE_THEME_VISUAL_ANCHOR_RE = re.compile(
    r"(?:"
    r"公元|世纪|年代|古代|上古|中古|近代|近现代|现代|当代|未来|近未来|末世|后末世|"
    r"秦|汉|魏晋|隋|唐|宋|元|明|清|民国|王朝|架空|异世|异世界|"
    r"东北|西北|西南|江南|岭南|西域|草原|海岛|中原|边塞|都市|城市|乡村|山村|小镇|"
    r"东方|中式|民俗|民间|宫廷|宫斗|江湖|武侠|修仙|仙侠|玄幻|宗门|神话|山海|"
    r"赛博|废土|科幻|机甲|校园|商战|悬疑|志怪|权谋"
    r")"
)
_STYLE_THEME_VISUAL_TOO_GENERIC = {
    "国风",
    "东方",
    "中式",
    "民俗",
    "民间",
    "古风",
    "现代",
    "古代",
    "未来",
    "架空",
    "玄幻",
    "科幻",
    "悬疑",
}
_STYLE_THEME_VISUAL_MAX_CHARS = 24
_BUILTIN_STYLE_THEME_VISUAL_PREFIX_RE = re.compile(
    r"^[^，,。；;]*(?:时代背景|时代设定|世界观背景)[，,]\s*"
)
_BUILTIN_STYLE_THEME_VISUAL_TAIL_RE = re.compile(
    r"[，,。；;]?\s*(?:整体时代设定保持|整体世界观保持)[^，,。；;]*语境[。；;，,]?\s*"
)
_PROMPT_SENTENCE_END_RE = re.compile(r"[。！？.!?…][\"'”’）)\]】》]*$")


def _ensure_prompt_sentence_end(value: Any, punctuation: str = "。") -> str:
    text = str(value or "").strip()
    if not text or _PROMPT_SENTENCE_END_RE.search(text):
        return text
    return f"{text}{punctuation or '。'}"


def _prompt_labeled_block(
    label: Any,
    content: Any,
    *,
    ensure_sentence_end: bool = False,
) -> str:
    name = str(label or "").strip().strip("【】")
    body = str(content or "").strip()
    if ensure_sentence_end:
        body = _ensure_prompt_sentence_end(body)
    if not name or not body:
        return body
    return f"【{name}】\n{body}"


def _join_prompt_blocks(parts: Any) -> str:
    rows = [str(part or "").strip() for part in parts if str(part or "").strip()]
    return "\n\n".join(rows)


def _strip_builtin_style_theme_visual_text(value: Any, category: Any) -> str:
    text = str(value or "").strip()
    if not text or str(category or "").strip() in {"general", "favorite"}:
        return text
    return _strip_style_theme_visual_overlap_text(text)


def _strip_style_theme_visual_overlap_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = _BUILTIN_STYLE_THEME_VISUAL_PREFIX_RE.sub("", text)
    text = _BUILTIN_STYLE_THEME_VISUAL_TAIL_RE.sub("，", text)
    return text.strip(" \t\r\n，,；;。")


def _style_theme_visual_candidate_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.strip(" \t\r\n\"'`“”‘’[]{}")
    text = _STYLE_THEME_VISUAL_LABEL_RE.sub("", text).strip()
    text = re.sub(r"\s+", "", text)
    return text


def _style_theme_visual_has_anchor(text: str) -> bool:
    return bool(_STYLE_THEME_VISUAL_ANCHOR_RE.search(text or ""))


def _style_theme_visual_is_specific(text: str) -> bool:
    core = re.sub(r"语境$", "", str(text or "").strip())
    core = re.sub(r"(?:时代背景|时代设定|背景|题材)$", "", core).strip()
    if not core or core in _STYLE_THEME_VISUAL_TOO_GENERIC:
        return False
    if len(core) > _STYLE_THEME_VISUAL_MAX_CHARS:
        return False
    return len(core) >= 4 or bool(re.search(r"\d", core))


def _normalize_style_theme_visual_context(value: Any) -> str:
    text = _style_theme_visual_candidate_text(value)
    if not text:
        return ""
    best = ""
    for sentence in re.split(r"[\r\n。；;]+", text):
        sentence = _STYLE_THEME_VISUAL_LABEL_RE.sub("", sentence).strip(" ，,、")
        if not sentence:
            continue
        kept_parts: list[str] = []
        for part in re.split(r"[，,、]+", sentence):
            part = _STYLE_THEME_VISUAL_LABEL_RE.sub("", part).strip(" ：:，,、")
            if not part:
                continue
            cleaned = _STYLE_THEME_VISUAL_STAGE_DETAIL_RE.sub("", part)
            cleaned = re.sub(
                r"^(?:故事发生在|故事设定在|设定在|背景为|时代背景为|整体设定为|世界观为|主要为|主要是|以)",
                "",
                cleaned,
            )
            cleaned = re.sub(r"(?:只写|不要写).*$", "", cleaned).strip(" ：:，,、")
            if not cleaned:
                continue
            if _STYLE_THEME_VISUAL_NOISE_RE.search(cleaned):
                continue
            kept_parts.append(cleaned)
            if "语境" in cleaned:
                break
        candidate = "".join(kept_parts).strip()
        candidate = re.sub(r"语境$", "", candidate).strip()
        candidate = re.sub(r"(?:时代背景|时代设定|背景|题材)$", "", candidate).strip()
        if (
            candidate
            and _style_theme_visual_has_anchor(candidate)
            and _style_theme_visual_is_specific(candidate)
        ):
            best = candidate
            break
    if not best:
        return ""
    return f"{best}语境"


def _style_theme_visual_prompt_from_config(config: Any) -> str:
    if not isinstance(config, dict):
        return ""
    return _normalize_style_theme_visual_context(config.get("theme_visual_context") or "")


def _style_theme_visual_prompt_block(theme_prompt: Any) -> str:
    theme = _normalize_style_theme_visual_context(theme_prompt)
    if not theme:
        return ""
    return _prompt_labeled_block("主题视觉", theme)


def _prepend_style_theme_visual_prompt(base_prompt: Any, theme_prompt: Any) -> str:
    base = str(base_prompt or "").strip()
    theme_block = _style_theme_visual_prompt_block(theme_prompt)
    if not theme_block:
        return base
    theme = theme_block.split("\n", 1)[1].strip() if "\n" in theme_block else theme_block
    if theme_block in base or theme in base:
        return base
    if not base:
        return theme_block
    return f"{theme_block}\n\n{base}"


def _normalize_style_phase_visual_context(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^\s*【(?:阶段视觉语境|阶段视觉提示词|阶段视觉)】\s*", "", text).strip()
    text = re.sub(r"^\s*(?:阶段视觉语境|阶段视觉提示词|阶段视觉|状态视觉|阶段视觉补充)\s*[:：]\s*", "", text).strip()
    return re.sub(r"[。；;，,\s]+$", "", text).strip()


def _normalize_style_phase_visuals(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if isinstance(item, str):
            raw: dict[str, Any] = {"prompt": item}
        elif isinstance(item, dict):
            raw = item
        else:
            continue
        prompt = str(
            raw.get("prompt")
            or raw.get("phasePrompt")
            or raw.get("phase_prompt")
            or ""
        )
        prompt = _normalize_style_phase_visual_context(prompt)
        if not prompt:
            continue
        raw_id = str(raw.get("id") or f"phase-visual-{index + 1}").strip()
        item_id = raw_id or f"phase-visual-{index + 1}"
        if item_id in seen_ids:
            item_id = f"{item_id}-{index + 1}"
        seen_ids.add(item_id)
        name = str(
            raw.get("name")
            or raw.get("title")
            or raw.get("label")
            or ""
        ).strip() or f"第{len(rows) + 1}阶段"
        rows.append({"id": item_id, "name": name, "prompt": prompt})
    return rows


def _style_phase_visuals_from_mapping(source: Any, fallback: Any = None) -> list[dict[str, str]]:
    if isinstance(source, dict):
        for key in STYLE_PHASE_VISUAL_KEYS:
            if key in source:
                return _normalize_style_phase_visuals(source.get(key))
    return _normalize_style_phase_visuals(fallback)


def _style_active_phase_visual_id_from_mapping(
    source: Any,
    phase_visuals: list[dict[str, str]],
    fallback: Any = None,
) -> str | None:
    value = None
    has_value = False
    if isinstance(source, dict):
        for key in STYLE_ACTIVE_PHASE_VISUAL_ID_KEYS:
            if key in source:
                value = source.get(key)
                has_value = True
                break
    if not has_value:
        value = fallback
    item_id = str(value or "").strip()
    if not item_id:
        return None
    return item_id if any(str(item.get("id") or "") == item_id for item in phase_visuals) else None


def _active_style_phase_visual(source: Any) -> dict[str, str] | None:
    if not isinstance(source, dict):
        return None
    phase_visuals = _style_phase_visuals_from_mapping(source)
    active_id = _style_active_phase_visual_id_from_mapping(
        source,
        phase_visuals,
    )
    if not active_id:
        return None
    for item in phase_visuals:
        if str(item.get("id") or "") == active_id and str(item.get("prompt") or "").strip():
            return item
    return None


def _style_phase_visual_prompt_from_config(config: Any) -> str:
    if not isinstance(config, dict):
        return ""
    style_config = config.get("style") if isinstance(config.get("style"), dict) else {}
    active = _active_style_phase_visual(style_config)
    # 阶段名称只用于 UI 管理，模型提示词只读取用户填写的 prompt 内容。
    return str((active or {}).get("prompt") or "").strip()


def _style_phase_visual_prompt_block(phase_prompt: Any) -> str:
    phase = _normalize_style_phase_visual_context(phase_prompt)
    if not phase:
        return ""
    return _prompt_labeled_block("阶段视觉", phase)


def _append_style_phase_visual_prompt(base_prompt: Any, phase_prompt: Any) -> str:
    base = str(base_prompt or "").strip()
    phase_block = _style_phase_visual_prompt_block(phase_prompt)
    if not phase_block:
        return base
    phase = phase_block.split("\n", 1)[1].strip() if "\n" in phase_block else phase_block
    if phase_block in base or phase in base:
        return base
    if not base:
        return phase_block
    return f"{base}\n\n{phase_block}"


def _compose_style_visual_prompt(
    base_prompt: Any,
    theme_prompt: Any,
    phase_prompt: Any,
) -> str:
    base = str(base_prompt or "").strip()
    parts: list[str] = []
    for block in (
        _style_theme_visual_prompt_block(theme_prompt),
        _style_phase_visual_prompt_block(phase_prompt),
    ):
        if not block:
            continue
        content = block.split("\n", 1)[1].strip() if "\n" in block else block
        if block in base or (content and content in base):
            continue
        if block not in parts:
            parts.append(block)
    if base:
        parts.append(base)
    return _join_prompt_blocks(parts)


def _style_visual_prompt_block(visual_prompt: Any, label: str = "全局视觉") -> str:
    visual = str(visual_prompt or "").strip()
    if not visual:
        return ""
    if re.match(r"^\s*【[^】]+】", visual):
        stripped = re.sub(
            r"^\s*【(?:画风|风格|视觉风格|视觉风格提示词|全局视觉|角色视觉|生物视觉)】\s*",
            "",
            visual,
        ).strip()
        if stripped != visual:
            visual = stripped
        else:
            return visual
    visual = re.sub(r"^\s*(?:画风|风格|视觉风格|视觉风格提示词)\s*[:：]\s*", "", visual).strip()
    visual = _strip_style_theme_visual_overlap_text(visual)
    if not visual:
        return ""
    if re.match(r"^\s*【[^】]+】", visual):
        stripped = re.sub(
            r"^\s*【(?:画风|风格|视觉风格|视觉风格提示词|全局视觉|角色视觉|生物视觉)】\s*",
            "",
            visual,
        ).strip()
        if stripped != visual:
            visual = stripped
        else:
            return visual
    if not visual:
        return ""
    return _prompt_labeled_block(label or "全局视觉", visual)


def _compose_image_visual_prompt(
    base_prompt: Any,
    theme_prompt: Any,
    visual_prompt: Any,
    phase_prompt: Any,
    visual_label: str = "全局视觉",
) -> str:
    base = str(base_prompt or "").strip()
    parts: list[str] = []
    for block in (
        _style_theme_visual_prompt_block(theme_prompt),
        _style_visual_prompt_block(visual_prompt, visual_label),
        _style_phase_visual_prompt_block(phase_prompt),
    ):
        if not block:
            continue
        content = block.split("\n", 1)[1].strip() if "\n" in block else block
        if block in base or (content and content in base):
            continue
        if block not in parts:
            parts.append(block)
    if base:
        parts.append(base)
    return _join_prompt_blocks(parts)

GLOBAL_CONFIG_PATH = GLOBAL_DIR / "config.json"
GLOBAL_ASSETS_PATH = GLOBAL_DIR / "assets.json"
GLOBAL_STYLE_TEMPLATES_PATH = GLOBAL_DIR / "style_templates.json"
GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH = GLOBAL_DIR / "script_adaptation_templates.json"
GLOBAL_TEXT_REPLACEMENT_RULES_PATH = GLOBAL_DIR / "text_replacement_rules.json"
GLOBAL_TASKS_PATH = GLOBAL_DIR / "tasks.json"
GLOBAL_USAGE_PATH = GLOBAL_DIR / "usage.json"
ACCENTS = [
    "from-indigo-500 via-sky-500 to-emerald-400",
    "from-rose-500 via-orange-400 to-amber-300",
    "from-violet-500 via-fuchsia-500 to-pink-400",
    "from-slate-600 via-sky-500 to-cyan-300",
]
IMAGE_OUTPUT_FORMATS = ("png", "jpg", "webp")
IMAGE_OUTPUT_FORMAT_VALUES = {"auto", *IMAGE_OUTPUT_FORMATS}

DEFAULT_PROVIDER_PRESETS: list[dict[str, Any]] = [
    {
        "id": "custom-provider",
        "adapter_id": "openai-compatible",
        "title": "自定义供应商",
        "logo": "API",
        "description": "用于 sub2api、new-api 等中转平台，可接入其中的多个官方模型。",
        "base_url": "",
        "docs_url": "",
        "key_label": "API_KEY",
        "capabilities": ["storyboard_image", "asset_image", "agent", "text_generation", "storyboard_video"],
        "models": [],
    },
    {
        "id": "ark-seedance",
        "adapter_id": "ark-seedance",
        "title": "火山方舟",
        "logo": "SD",
        "icon_key": "Volcengine",
        "description": "火山方舟：图片、智能体、文本和视频模型。",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "docs_url": "https://www.volcengine.com/docs/82379/1520757",
        "key_label": "ARK_API_KEY",
        "capabilities": [
            "storyboard_image",
            "asset_image",
            "storyboard_video",
            "text_generation",
            "agent",
        ],
        "models": [],
    },
    {
        "id": "ark-agent-plan",
        "adapter_id": "anthropic-compatible",
        "title": "火山方舟 Agent Plan",
        "logo": "ARK",
        "icon_key": "Volcengine",
        "description": "火山方舟智能体接口。",
        "base_url": "https://ark.cn-beijing.volces.com/api/plan",
        "docs_url": "https://www.volcengine.com/docs/82379/2375486",
        "key_label": "ARK_API_KEY",
        "capabilities": ["agent"],
        "supports_discovery": False,
        "models": [],
    },
    {
        "id": "deepseek",
        "adapter_id": "anthropic-compatible",
        "title": "DeepSeek",
        "logo": "DS",
        "icon_key": "DeepSeek",
        "description": "DeepSeek 文本与智能体接口。",
        "base_url": "https://api.deepseek.com/anthropic",
        "docs_url": "https://api-docs.deepseek.com",
        "key_label": "DEEPSEEK_API_KEY",
        "capabilities": ["text_generation", "agent"],
        "models": [],
    },
    {
        "id": "minimax",
        "adapter_id": "anthropic-compatible",
        "title": "MiniMax",
        "logo": "MM",
        "icon_key": "MiniMax",
        "description": "MiniMax：图片、智能体、文本和视频生成。",
        "base_url": "https://api.minimax.cn/anthropic",
        "docs_url": "https://platform.minimax.cn/docs/api-reference/text-anthropic-api",
        "key_label": "MINIMAX_API_KEY",
        "capabilities": ["storyboard_image", "asset_image", "agent", "text_generation", "storyboard_video"],
        "models": [],
    },
    {
        "id": "metaso",
        "adapter_id": "minimax-compatible",
        "title": "秘塔（Metaso）",
        "logo": "秘塔",
        "icon_key": "Metaso",
        "description": "秘塔部署的 MiniMax H3，支持参考图/视频和原生首尾帧视频生成。",
        "base_url": "https://metaso.cn/api/minimax",
        "docs_url": "https://metaso.cn/minimax-h3",
        "key_label": "METASO_API_KEY",
        "capabilities": ["storyboard_video"],
        "models": [],
    },
    {
        "id": "autodl-comfyui",
        "adapter_id": "autodl-comfyui",
        "title": "autodl ComfyUI",
        "logo": "AD",
        "description": "AutoDL ComfyUI：MiniMax H3 多参考图、升级画质和首尾帧视频生成。",
        "base_url": "https://autodl.art/api/v1/comfyui",
        "docs_url": "https://autodl.art/docs/comfyui_api/",
        "key_label": "AUTODL_API_KEY",
        "capabilities": ["storyboard_video"],
        "models": [],
    },
    {
        # Legacy persisted records may still reference this adapter. It is
        # intentionally hidden from the provider picker; custom relays are
        # identified by their public platform contract during probing.
        "id": "newapi",
        "adapter_id": "newapi-video",
        "title": "New API（官方视频协议）",
        "logo": "NA",
        "description": "兼容旧配置的内部协议预设，不作为独立供应商展示。",
        "base_url": "",
        "docs_url": "https://github.com/QuantumNous/new-api-docs/blob/main/docs/api/openai-video.md",
        "key_label": "NEW_API_KEY",
        "capabilities": ["storyboard_video"],
        "models": [],
        "hidden": True,
    },
    {
        "id": "dashscope",
        "adapter_id": "dashscope",
        "title": "阿里百炼",
        "logo": "ALI",
        "icon_key": "Bailian",
        "description": "阿里百炼：图片、智能体、文本和视频生成。",
        "base_url": "https://dashscope.aliyuncs.com",
        "base_url_options": [
            {
                "label": "Workspace China Beijing",
                "base_url_template": "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com",
                "source_url": "https://help.aliyun.com/en/model-studio/what-is-model-studio",
            },
            {
                "label": "Legacy public native API",
                "base_url": "https://dashscope.aliyuncs.com",
                "source_url": "https://help.aliyun.com/zh/model-studio/wan-video-to-video-api-reference",
            },
        ],
        "base_url_note": (
            "DashScope 文本兼容接口优先使用官方 workspace 专属域名；Wan 原生视频接口仍按 /api/v1/services/aigc/"
            "video-generation/video-synthesis 组装，旧公共域名保持兼容。"
        ),
        "docs_url": "https://help.aliyun.com/zh/model-studio/",
        "key_label": "DASHSCOPE_API_KEY",
        "capabilities": ["storyboard_image", "asset_image", "storyboard_video", "text_generation", "agent"],
        "models": [],
    },
    {
        "id": "anthropic",
        "adapter_id": "anthropic-compatible",
        "title": "Anthropic 兼容",
        "logo": "AN",
        "icon_key": "Anthropic",
        "description": "Anthropic/Claude 兼容文本接口。",
        "base_url": "https://api.anthropic.com",
        "docs_url": "https://docs.anthropic.com",
        "key_label": "ANTHROPIC_API_KEY",
        "capabilities": ["agent", "text_generation"],
        "models": [],
    },
    {
        "id": "gemini",
        "adapter_id": "gemini-compatible",
        "title": "Gemini",
        "logo": "G",
        "icon_key": "Gemini",
        "description": "Gemini：图片和文本模型。",
        "base_url": "https://generativelanguage.googleapis.com",
        "docs_url": "https://ai.google.dev",
        "key_label": "GEMINI_API_KEY",
        "capabilities": ["storyboard_image", "asset_image", "text_generation"],
        "models": [],
    },
    {
        "id": "vidu",
        "adapter_id": "vidu",
        "title": "Vidu",
        "logo": "VD",
        "icon_key": "Vidu",
        "description": "Vidu 图片与视频生成。",
        "base_url": "https://api.vidu.com/ent/v2",
        "base_url_options": [
            {
                "label": "Global official",
                "base_url": "https://api.vidu.com/ent/v2",
                "source_url": "https://platform.vidu.com/docs/reference-to-video",
            },
            {
                "label": "China official",
                "base_url": "https://api.vidu.cn/ent/v2",
                "source_url": "https://platform.vidu.cn/docs/reference-to-video",
            },
        ],
        "base_url_note": "Vidu Reference-to-Video 英文官方示例使用 api.vidu.com；已按中国区域配置的账号可继续使用 api.vidu.cn。",
        "docs_url": "https://platform.vidu.com",
        "key_label": "VIDU_API_KEY",
        "capabilities": ["storyboard_image", "asset_image", "storyboard_video"],
        "models": [],
    },
    {
        "id": "grok",
        "adapter_id": "grok",
        "title": "xAI Grok",
        "logo": "XAI",
        "icon_key": "Grok",
        "description": "xAI 图片生成。Grok 视频当前本地适配仍是单静图首帧路线，不作为故事版分镜图视频模型预设。",
        "base_url": "https://api.x.ai/v1",
        "docs_url": "https://docs.x.ai/developers/model-capabilities/imagine",
        "key_label": "XAI_API_KEY",
        "capabilities": ["storyboard_image", "asset_image"],
        "models": [],
    },
    {
        "id": "qiniu",
        "adapter_id": "openai-compatible",
        "title": "七牛云",
        "logo": "七牛",
        "description": "七牛云：图片、智能体、文本和视频模型。",
        "base_url": "https://api.qnaigc.com/v1",
        "docs_url": "https://developer.qiniu.com/aitokenapi",
        "key_label": "QINIU_API_KEY",
        "capabilities": ["storyboard_image", "asset_image", "agent", "text_generation", "storyboard_video"],
        "models": [],
    },
]

LEGACY_GENERIC_PROVIDER_MODEL_IDS = {
    "custom:image-model",
    "custom:video-model",
    "custom:text-model",
}
RETIRED_PROVIDER_PRESET_IDS = {"openai", "custom-openai-compatible", "custom-ark-seedance"}
PROVIDER_ADAPTER_SERVICE_IDS = {
    "autodl-comfyui": "autodl-comfyui",
    "minimax-compatible": "minimax",
    "openai-compatible": "openai",
    "anthropic-compatible": "anthropic",
    "gemini-compatible": "gemini",
    "ark-seedance": "ark-seedance",
    "dashscope": "dashscope",
    "vidu": "vidu",
    "grok": "grok",
    "newapi-video": "newapi",
}
SERVICE_PROVIDER_ADAPTER_IDS = {
    "autodl-comfyui": "autodl-comfyui",
    "metaso": "minimax-compatible",
    "custom-provider": "openai-compatible",
    "newapi": "newapi-video",
    "qiniu": "openai-compatible",
    "openai": "openai-compatible",
    "anthropic": "anthropic-compatible",
    "deepseek": "anthropic-compatible",
    "minimax": "anthropic-compatible",
    "ark-agent-plan": "anthropic-compatible",
    "gemini": "gemini-compatible",
    "ark-seedance": "ark-seedance",
    "dashscope": "dashscope",
    "vidu": "vidu",
    "grok": "grok",
}


def _normalize_resolution_label(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return IMAGE_RESOLUTION_ALIASES.get(raw.lower(), raw)


def _normalize_resolution_options(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    options: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_resolution_label(value)
        key = normalized.lower()
        if normalized and key not in seen:
            options.append(normalized)
            seen.add(key)
    return options


def _normalize_duration_options(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    def parse_value(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    durations = sorted(
        {
            parsed
            for value in values
            for parsed in [parse_value(value)]
            if parsed is not None
        }
    )
    return durations


def _normalize_provider_model_metadata(model: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(model)
    aliases = {
        "referenceImageInputMaxLongEdge": "reference_image_input_max_long_edge",
        "referenceImageInputMaxBytes": "reference_image_input_max_bytes",
        "referenceImageInputSource": "reference_image_input_source",
        "referenceImageInputSourceUrl": "reference_image_input_source_url",
        "referenceImageInputNote": "reference_image_input_note",
        "imageResolutionSchema": "image_resolution_schema",
        "allowedDurations": "durations",
        "durationResolutionConstraints": "duration_resolution_constraints",
        "supportsStoryboardReferenceImage": "supports_storyboard_reference_image",
        "supportsMultiReferenceImages": "supports_multi_reference_images",
        "supportsNativeAudio": "supports_native_audio",
        "promptHardLimitChars": "prompt_hard_limit_chars",
        "officialPromptLimitChars": "official_prompt_limit_chars",
        "finalPromptProfile": "final_prompt_profile",
        "promptTimingStyle": "prompt_timing_style",
        "capabilitySource": "capability_source",
        "capabilitySourceUrl": "capability_source_url",
        "capabilityNote": "capability_note",
        "officialCapabilities": "official_capabilities",
        "adapterCapabilities": "adapter_capabilities",
    }
    for alias, key in aliases.items():
        if alias in normalized and key not in normalized:
            normalized[key] = normalized[alias]
    if "resolutions" in normalized:
        normalized["resolutions"] = _normalize_resolution_options(normalized.get("resolutions"))
    if "default_resolution" in normalized:
        default_resolution = _normalize_resolution_label(normalized.get("default_resolution"))
        if default_resolution:
            normalized["default_resolution"] = default_resolution
    if "durations" in normalized:
        durations = _normalize_duration_options(normalized.get("durations"))
        if durations:
            normalized["durations"] = durations
            normalized["allowedDurations"] = durations
    constraints = normalized.get("duration_resolution_constraints")
    if isinstance(constraints, dict):
        normalized_constraints: dict[str, list[int]] = {}
        for key, value in constraints.items():
            resolution = _normalize_resolution_label(key)
            durations = _normalize_duration_options(value)
            if resolution and durations:
                normalized_constraints[resolution] = durations
        normalized["duration_resolution_constraints"] = normalized_constraints
    model_type = str(normalized.get("type") or "").strip().lower()
    if model_type == "video":
        durations = _normalize_duration_options(normalized.get("durations"))
        if durations:
            normalized["durations"] = durations
            normalized["allowedDurations"] = durations
        else:
            normalized.pop("durations", None)
            normalized.pop("allowedDurations", None)
        supports = {
            str(item).strip().lower()
            for item in normalized.get("supports", [])
            if str(item).strip()
        } if isinstance(normalized.get("supports"), list) else set()
        if "supports_storyboard_reference_image" not in normalized:
            normalized["supports_storyboard_reference_image"] = "storyboard_reference_image" in supports
        if "supports_multi_reference_images" not in normalized:
            normalized["supports_multi_reference_images"] = "multi_reference_video" in supports
        if "supports_native_audio" not in normalized:
            normalized["supports_native_audio"] = bool(normalized.get("audio") is True or "native_audio" in supports)
    if model_type == "image":
        schema = image_resolution_schema_for_model(normalized)
        if schema:
            normalized["image_resolution_schema"] = schema
            normalized["imageResolutionSchema"] = copy.deepcopy(schema)
    if model_type in {"image", "video"}:
        edge = _positive_int_value(normalized.get("reference_image_input_max_long_edge"))
        if edge is None:
            edge = _reference_image_input_default_max_long_edge(normalized)
        if edge is not None:
            normalized["reference_image_input_max_long_edge"] = edge
        max_bytes = _positive_int_value(normalized.get("reference_image_input_max_bytes"))
        if max_bytes is None:
            max_bytes = REFERENCE_IMAGE_INPUT_DEFAULT_MAX_BYTES
        normalized["reference_image_input_max_bytes"] = max_bytes
        normalized.setdefault("reference_image_input_source", "application")
        normalized.setdefault(
            "reference_image_input_note",
            "Reference images are prepared at the provider-input valve only: transparent PNG stays PNG; all other images are sent as JPEG and compressed within this byte/edge budget.",
        )
    return normalized


def _positive_int_value(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _reference_image_input_default_max_long_edge(model: dict[str, Any]) -> int | None:
    model_type = str(model.get("type") or "").strip().lower()
    if model_type not in {"image", "video"}:
        return None
    edges: list[int] = []
    for resolution in model.get("resolutions") if isinstance(model.get("resolutions"), list) else []:
        label = _normalize_resolution_label(resolution)
        edge = _REFERENCE_IMAGE_INPUT_EDGE_BY_RESOLUTION.get(label)
        if edge:
            edges.append(edge)
    edge = max(edges) if edges else REFERENCE_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE
    model_id = str(model.get("id") or "").strip().lower()
    if model_id.endswith(":gpt-image-2") or model_id == "gpt-image-2":
        edge = min(edge, _GPT_IMAGE_MAX_LONG_EDGE)
    return edge


def _catalog_model(
    provider_prefix: str,
    model_id: str,
    label: str,
    model_type: str,
    *,
    resolutions: list[str] | None = None,
    default_resolution: str | None = None,
    durations: list[int] | None = None,
    duration_resolution_constraints: dict[str, list[int]] | None = None,
    image_output_formats: list[str] | None = None,
    audio: bool = False,
    max_reference_images: int | None = None,
    reference_image_limit_source: str | None = None,
    reference_image_limit_source_url: str | None = None,
    reference_image_limit_note: str | None = None,
    reference_image_input_max_long_edge: int | None = None,
    reference_image_input_max_bytes: int | None = None,
    reference_image_input_source: str | None = None,
    reference_image_input_source_url: str | None = None,
    reference_image_input_note: str | None = None,
    reference_image_transport_verified: bool | None = None,
    reference_image_transport_unverified: bool | None = None,
    supports: list[str] | None = None,
    supports_storyboard_reference_image: bool | None = None,
    supports_multi_reference_images: bool | None = None,
    supports_native_audio: bool | None = None,
    prompt_hard_limit_chars: int | None = None,
    official_prompt_limit_chars: int | None = None,
    final_prompt_profile: str | None = None,
    capability_source: str | None = None,
    capability_source_url: str | None = None,
    capability_note: str | None = None,
    official_capabilities: dict[str, Any] | None = None,
    adapter_capabilities: dict[str, Any] | None = None,
    usage: str = "",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": f"{provider_prefix}:{model_id}",
        "label": label,
        "type": model_type,
        "resolutions": list(resolutions or []),
    }
    if model_type == "image":
        schema = image_resolution_schema_for_model(row, provider_prefix)
        if schema:
            row["image_resolution_schema"] = schema
            row["imageResolutionSchema"] = copy.deepcopy(schema)
    if default_resolution:
        row["default_resolution"] = default_resolution
    if model_type == "video":
        video_durations = _normalize_duration_options(durations)
        if not video_durations:
            raise ValueError(f"视频模型 {provider_prefix}:{model_id} 缺少 durations/allowedDurations")
        row["durations"] = video_durations
        row["allowedDurations"] = video_durations
    elif durations:
        row["durations"] = _normalize_duration_options(durations)
    if duration_resolution_constraints:
        row["duration_resolution_constraints"] = {
            str(resolution): [int(duration) for duration in values]
            for resolution, values in duration_resolution_constraints.items()
            if isinstance(values, list)
        }
    if image_output_formats:
        row["image_output_formats"] = list(image_output_formats)
    if audio:
        row["audio"] = True
    if max_reference_images is not None:
        row["max_reference_images"] = max_reference_images
    if reference_image_limit_source:
        row["reference_image_limit_source"] = str(reference_image_limit_source)
    if reference_image_limit_source_url:
        row["reference_image_limit_source_url"] = str(reference_image_limit_source_url)
    if reference_image_limit_note:
        row["reference_image_limit_note"] = str(reference_image_limit_note)
    if model_type in {"image", "video"}:
        if reference_image_input_max_long_edge is not None:
            row["reference_image_input_max_long_edge"] = int(reference_image_input_max_long_edge)
        if reference_image_input_max_bytes is not None:
            row["reference_image_input_max_bytes"] = int(reference_image_input_max_bytes)
        if reference_image_input_source:
            row["reference_image_input_source"] = str(reference_image_input_source)
        if reference_image_input_source_url:
            row["reference_image_input_source_url"] = str(reference_image_input_source_url)
        if reference_image_input_note:
            row["reference_image_input_note"] = str(reference_image_input_note)
    if reference_image_transport_verified is not None:
        row["reference_image_transport_verified"] = reference_image_transport_verified
    if reference_image_transport_unverified is not None:
        row["reference_image_transport_unverified"] = reference_image_transport_unverified
    if supports:
        row["supports"] = list(supports)
    support_set = {str(item).strip().lower() for item in row.get("supports", []) if str(item).strip()} if isinstance(row.get("supports"), list) else set()
    if model_type == "video":
        row["supports_storyboard_reference_image"] = (
            bool(supports_storyboard_reference_image)
            if supports_storyboard_reference_image is not None
            else "storyboard_reference_image" in support_set
        )
        row["supports_multi_reference_images"] = (
            bool(supports_multi_reference_images)
            if supports_multi_reference_images is not None
            else "multi_reference_video" in support_set
        )
        row["supports_native_audio"] = (
            bool(supports_native_audio)
            if supports_native_audio is not None
            else bool(audio or "native_audio" in support_set)
        )
        if prompt_hard_limit_chars is not None:
            row["prompt_hard_limit_chars"] = int(prompt_hard_limit_chars)
        if official_prompt_limit_chars is not None:
            row["official_prompt_limit_chars"] = int(official_prompt_limit_chars)
        if final_prompt_profile:
            row["final_prompt_profile"] = str(final_prompt_profile)
        if capability_source:
            row["capability_source"] = str(capability_source)
        if capability_source_url:
            row["capability_source_url"] = str(capability_source_url)
        if capability_note:
            row["capability_note"] = str(capability_note)
        if isinstance(official_capabilities, dict):
            row["official_capabilities"] = copy.deepcopy(official_capabilities)
        if isinstance(adapter_capabilities, dict):
            row["adapter_capabilities"] = copy.deepcopy(adapter_capabilities)
    if usage:
        row["usage"] = usage
    return _normalize_provider_model_metadata(row)


def _storyboard_video_catalog_model(model_id: str, *, provider_id: str = "") -> dict[str, Any]:
    from utils.video_model_capabilities import video_model_capability

    spec = (
        video_model_capability({"api_model_id": model_id, "provider_preset_id": provider_id})
        if provider_id else STORYBOARD_VIDEO_MODEL_CAPABILITIES[model_id]
    )
    if spec is None:
        raise ValueError(f"视频模型 {provider_id}:{model_id} 尚未适配")
    metadata = spec.get("metadata") if isinstance(spec.get("metadata"), dict) else {}
    return _catalog_model(
        str(spec["provider_prefix"]),
        model_id,
        str(spec["title"]),
        "video",
        resolutions=list(spec.get("resolutions") or []),
        default_resolution=str(spec.get("default_resolution") or ""),
        durations=list(spec.get("durations") or []),
        audio=bool(spec.get("audio") is True),
        max_reference_images=int(spec.get("max_reference_images") or 0),
        **metadata,
        supports=list(spec.get("supports") or []),
        official_capabilities=spec.get("official_capabilities") if isinstance(spec.get("official_capabilities"), dict) else None,
        adapter_capabilities=spec.get("adapter_capabilities") if isinstance(spec.get("adapter_capabilities"), dict) else None,
        usage=str(spec.get("usage") or ""),
    )


BUILTIN_PROVIDER_MODELS: dict[str, list[dict[str, Any]]] = {
    "ark-seedance": [
        _catalog_model("ark", "doubao-seed-2-0-pro-260215", "豆包 Seed 2.0 Pro", "text", supports=["vision"], usage="文本处理 / 视觉输入"),
        _catalog_model("ark", "doubao-seed-2-0-lite-260215", "豆包 Seed 2.0 Lite", "text", supports=["vision"], usage="文本处理 / 视觉输入"),
        _catalog_model("ark", "doubao-seed-2-0-mini-260215", "豆包 Seed 2.0 Mini", "text", supports=["vision"], usage="文本处理 / 视觉输入"),
        _catalog_model("ark", "doubao-seed-1-8-251228", "豆包 Seed 1.8", "text", supports=["vision"], usage="文本处理 / 视觉输入"),
        _catalog_model(
            "ark",
            "doubao-seedream-5-0-lite-260128",
            "Seedream 5.0 Lite",
            "image",
            resolutions=["2K", "3K", "4K"],
            default_resolution="2K",
            max_reference_images=14,
            **ARK_SEEDREAM_5_REFERENCE_LIMIT_METADATA,
            supports=[
                "storyboard_image",
                "storyboard_panel",
                "storyboard_sheet",
                "asset_image",
                "reference_image",
                "image_edit",
                "multi_reference_image",
            ],
            usage="故事版分镜图 / 资产图",
        ),
        _catalog_model(
            "ark",
            "doubao-seedream-5-0-pro-260628",
            "Seedream 5.0 Pro",
            "image",
            resolutions=["1K", "2K"],
            default_resolution="2K",
            max_reference_images=14,
            **ARK_SEEDREAM_5_REFERENCE_LIMIT_METADATA,
            supports=[
                "storyboard_image",
                "storyboard_panel",
                "storyboard_sheet",
                "asset_image",
                "reference_image",
                "image_edit",
                "multi_reference_image",
            ],
            usage="故事版分镜图 / 资产图",
        ),
        _storyboard_video_catalog_model("doubao-seedance-2-0-260128"),
        _storyboard_video_catalog_model("doubao-seedance-2-0-fast-260128"),
        _storyboard_video_catalog_model("doubao-seedance-2-0-mini-260615"),
        _storyboard_video_catalog_model("doubao-seedance-2-5-260628"),
    ],
    "ark-agent-plan": [
        _catalog_model("ark-agent-plan", "ark-code-latest", "ark-code-latest", "text", usage="智能体"),
    ],
    "deepseek": [
        _catalog_model(
            "deepseek",
            "deepseek-flash",
            "DeepSeek V4.1 Flash",
            "text",
            supports=["vision"],
            usage="智能体 / 文本处理 / 图片理解",
        ),
        _catalog_model(
            "deepseek",
            "deepseek-v4-pro",
            "DeepSeek V4 Pro",
            "text",
            usage="智能体 / 文本处理",
        ),
    ],
    "minimax": [
        _catalog_model(
            "minimax", "image-01", "MiniMax Image 01", "image",
            resolutions=["1K", "2K"], default_resolution="2K",
            max_reference_images=1,
            reference_image_input_max_long_edge=2048,
            reference_image_input_max_bytes=30 * 1024 * 1024,
            reference_image_input_source="official",
            reference_image_input_source_url="https://platform.minimax.cn/docs/api-reference/image-generation-i2i",
            reference_image_input_note="官方图生图通过 subject_reference 传递人物主体参考图。",
            supports=["storyboard_image", "asset_image", "reference_image", "image_edit"],
            capability_source="official",
            capability_source_url="https://platform.minimax.cn/docs/api-reference/image-generation-t2i",
            capability_note="MiniMax 官方图片生成模型，支持文生图和人物主体参考图。",
            usage="故事版分镜图 / 资产图",
        ),
        _catalog_model(
            "minimax", "image-01-live", "MiniMax Image 01 Live", "image",
            resolutions=["auto"], default_resolution="auto",
            max_reference_images=1,
            reference_image_input_max_long_edge=2048,
            reference_image_input_max_bytes=30 * 1024 * 1024,
            reference_image_input_source="official",
            reference_image_input_source_url="https://platform.minimax.cn/docs/api-reference/image-generation-i2i",
            reference_image_input_note="官方图生图通过 subject_reference 传递人物主体参考图。",
            supports=["storyboard_image", "asset_image", "reference_image", "image_edit"],
            capability_source="official",
            capability_source_url="https://platform.minimax.cn/docs/api-reference/image-generation-t2i",
            capability_note="MiniMax 官方图片生成模型，支持文生图和人物主体参考图。",
            usage="故事版分镜图 / 资产图",
        ),
        _storyboard_video_catalog_model("MiniMax-H3"),
        _storyboard_video_catalog_model("MiniMax-H3-Max"),
        _catalog_model(
            "minimax",
            "MiniMax-M3.1-Flash-Preview",
            "MiniMax M3.1 Flash Preview",
            "text",
            supports=["vision"],
            usage="智能体 / 文本处理 / 视觉输入",
        ),
        _catalog_model(
            "minimax",
            "MiniMax-M3",
            "MiniMax M3",
            "text",
            supports=["vision"],
            usage="智能体 / 文本处理 / 视觉输入",
        ),
        _catalog_model("minimax", "MiniMax-M2.7", "MiniMax M2.7", "text", usage="智能体 / 文本处理"),
        _catalog_model("minimax", "MiniMax-M2.7-highspeed", "MiniMax M2.7 Highspeed", "text", usage="智能体 / 文本处理"),
        _catalog_model("minimax", "MiniMax-M2.5", "MiniMax M2.5", "text", usage="智能体 / 文本处理"),
        _catalog_model("minimax", "MiniMax-M2.5-highspeed", "MiniMax M2.5 Highspeed", "text", usage="智能体 / 文本处理"),
        _catalog_model("minimax", "MiniMax-M2.1", "MiniMax M2.1", "text", usage="智能体 / 文本处理"),
        _catalog_model("minimax", "MiniMax-M2.1-highspeed", "MiniMax M2.1 Highspeed", "text", usage="智能体 / 文本处理"),
        _catalog_model("minimax", "MiniMax-M2", "MiniMax M2", "text", usage="智能体 / 文本处理"),
    ],
    "autodl-comfyui": [
        {
            **_storyboard_video_catalog_model(workflow_id, provider_id="autodl-comfyui"),
            "api_model_id": workflow_id, "provider_preset_id": "autodl-comfyui",
            "model_vendor": "minimax", "endpoint": "autodl-comfyui-video",
        }
        for workflow_id in (
            "minimax_h3_image_audio_to_video_v2_15s", "minimax_h3_lightx2v", "minimax_h3_zm_u24",
            "minimax_h3_zm_titi", "minimax_h3_zm_titim",
        )
    ],
    "metaso": [
        {
            **_storyboard_video_catalog_model("MiniMax-H3", provider_id="metaso"),
            "api_model_id": "MiniMax-H3",
            "provider_preset_id": "metaso",
            "model_vendor": "minimax",
            "endpoint": "metaso-video",
        },
    ],
    "anthropic": [
        _catalog_model(
            "anthropic",
            "claude-opus-5",
            "Claude Opus 5",
            "text",
            supports=["vision"],
            usage="智能体 / 文本处理",
        ),
    ],
    "dashscope": [
        _catalog_model("dashscope", "qwen-plus", "Qwen Plus", "text", usage="文本处理"),
        _catalog_model("dashscope", "qwen3.6-plus", "Qwen3.6 Plus", "text", usage="文本处理"),
        _catalog_model("dashscope", "qwen3-max", "Qwen3 Max", "text", usage="文本处理"),
        _catalog_model("dashscope", "qwen3.7-max", "Qwen3.7 Max", "text", usage="文本处理"),
        _catalog_model("dashscope", "qwen3.6-flash", "Qwen3.6 Flash", "text", usage="文本处理"),
        _catalog_model("dashscope", "qwen-long", "Qwen Long", "text", usage="文本处理"),
        _catalog_model(
            "dashscope",
            "qwen-image-2.0",
            "Qwen Image 2.0",
            "image",
            resolutions=DASHSCOPE_QWEN_IMAGE_RESOLUTIONS,
            default_resolution=DASHSCOPE_QWEN_IMAGE_DEFAULT_RESOLUTION,
            max_reference_images=3,
            **DASHSCOPE_QWEN_IMAGE_REFERENCE_LIMIT_METADATA,
            supports=["storyboard_image", "storyboard_panel", "asset_image", "reference_image", "image_edit", "multi_reference_image"],
            usage="故事版分镜图 / 图片融合",
        ),
        _catalog_model(
            "dashscope",
            "qwen-image-2.0-pro",
            "Qwen Image 2.0 Pro",
            "image",
            resolutions=DASHSCOPE_QWEN_IMAGE_RESOLUTIONS,
            default_resolution=DASHSCOPE_QWEN_IMAGE_DEFAULT_RESOLUTION,
            max_reference_images=3,
            **DASHSCOPE_QWEN_IMAGE_REFERENCE_LIMIT_METADATA,
            supports=["storyboard_image", "storyboard_panel", "asset_image", "reference_image", "image_edit", "multi_reference_image"],
            usage="故事版分镜图 / 图片融合",
        ),
        _catalog_model(
            "dashscope",
            "qwen-image-edit-plus",
            "Qwen Image Edit Plus",
            "image",
            resolutions=DASHSCOPE_QWEN_IMAGE_EDIT_RESOLUTIONS,
            default_resolution=DASHSCOPE_QWEN_IMAGE_EDIT_DEFAULT_RESOLUTION,
            max_reference_images=3,
            **DASHSCOPE_QWEN_IMAGE_REFERENCE_LIMIT_METADATA,
            supports=["asset_image", "reference_image", "image_edit", "multi_reference_image"],
            usage="资产图 / 图片编辑",
        ),
        _catalog_model(
            "dashscope",
            "qwen-image-edit-max",
            "Qwen Image Edit Max",
            "image",
            resolutions=DASHSCOPE_QWEN_IMAGE_EDIT_RESOLUTIONS,
            default_resolution=DASHSCOPE_QWEN_IMAGE_EDIT_DEFAULT_RESOLUTION,
            max_reference_images=3,
            **DASHSCOPE_QWEN_IMAGE_REFERENCE_LIMIT_METADATA,
            supports=["asset_image", "reference_image", "image_edit", "multi_reference_image"],
            usage="资产图 / 图片编辑",
        ),
        _catalog_model(
            "dashscope",
            "wan2.7-image",
            "万相 2.7 图像",
            "image",
            resolutions=["1K", "2K"],
            default_resolution="2K",
            max_reference_images=9,
            **DASHSCOPE_WAN27_IMAGE_REFERENCE_LIMIT_METADATA,
            supports=[
                "storyboard_image",
                "storyboard_panel",
                "storyboard_sheet",
                "asset_image",
                "reference_image",
                "image_edit",
                "multi_reference_image",
            ],
            usage="故事版分镜图 / 资产图",
        ),
        _catalog_model(
            "dashscope",
            "wan2.7-image-pro",
            "万相 2.7 图像 Pro",
            "image",
            resolutions=["1K", "2K", "4K"],
            default_resolution="2K",
            max_reference_images=9,
            **DASHSCOPE_WAN27_IMAGE_REFERENCE_LIMIT_METADATA,
            supports=[
                "storyboard_image",
                "storyboard_panel",
                "storyboard_sheet",
                "asset_image",
                "reference_image",
                "image_edit",
                "multi_reference_image",
            ],
            usage="故事版分镜图 / 资产图",
        ),
        _storyboard_video_catalog_model("wan2.7-r2v-2026-06-12"),
        _storyboard_video_catalog_model("wan3.0-video"),
        _storyboard_video_catalog_model("wan3.0-video-prime"),
        _storyboard_video_catalog_model("happyhorse-1.1-r2v"),
        _storyboard_video_catalog_model("happyhorse-1.1-i2v"),
    ],
    "gemini": [
        _catalog_model("gemini", "gemini-3.1-pro-preview", "Gemini 3.1 Pro", "text", supports=["vision"], usage="文本处理 / 视觉输入 / 智能体"),
        _catalog_model("gemini", "gemini-3-flash-preview", "Gemini 3 Flash", "text", supports=["vision"], usage="文本处理 / 视觉输入 / 智能体"),
        _catalog_model("gemini", "gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite", "text", usage="文本处理 / 智能体"),
        _catalog_model(
            "gemini",
            "gemini-3-pro-image",
            "Gemini 3 Pro Image",
            "image",
            resolutions=["1K", "2K", "4K"],
            default_resolution="2K",
            max_reference_images=14,
            **GEMINI_IMAGE_REFERENCE_LIMIT_METADATA,
            supports=["storyboard_image", "storyboard_panel", "asset_image", "reference_image", "image_edit", "multi_reference_image"],
            usage="故事版分镜图 / 资产图",
        ),
        _catalog_model(
            "gemini",
            "gemini-3.1-flash-image",
            "Gemini 3.1 Flash Image",
            "image",
            resolutions=["1K", "2K", "4K"],
            default_resolution="2K",
            max_reference_images=14,
            **GEMINI_IMAGE_REFERENCE_LIMIT_METADATA,
            supports=["storyboard_image", "storyboard_panel", "asset_image", "reference_image", "image_edit", "multi_reference_image"],
            usage="故事版分镜图 / 资产图",
        ),
    ],
    "vidu": [
        _catalog_model(
            "vidu",
            "viduq2",
            "Vidu Q2 Image",
            "image",
            resolutions=["1K", "2K", "4K"],
            default_resolution="2K",
            max_reference_images=7,
            **VIDU_Q2_IMAGE_REFERENCE_LIMIT_METADATA,
            supports=["storyboard_image", "storyboard_panel", "asset_image", "reference_image", "image_edit", "multi_reference_image"],
            usage="故事版分镜图 / 参考生图",
        ),
        _storyboard_video_catalog_model("viduq3-turbo"),
        _storyboard_video_catalog_model("viduq3-pro"),
        _storyboard_video_catalog_model("viduq3-pro-fast"),
        _storyboard_video_catalog_model("viduq3"),
        _storyboard_video_catalog_model("viduq3-mix"),
    ],
    "grok": [
        _catalog_model(
            "grok",
            "grok-imagine-image-2.0",
            "Grok Imagine Image 2.0",
            "image",
            resolutions=["1K", "2K"],
            default_resolution="2K",
            max_reference_images=5,
            **GROK_IMAGE_REFERENCE_LIMIT_METADATA,
            supports=["storyboard_image", "storyboard_panel", "asset_image", "reference_image", "image_edit", "multi_reference_image"],
            usage="故事版分镜图 / 图片编辑",
        ),
    ],
}

for _provider_preset in DEFAULT_PROVIDER_PRESETS:
    _aligned_models = BUILTIN_PROVIDER_MODELS.get(str(_provider_preset.get("id")))
    if _aligned_models is not None:
        # Provider presets keep UI/provider metadata; model rows are maintained only in BUILTIN_PROVIDER_MODELS.
        _provider_preset["models"] = copy.deepcopy(_aligned_models)

def _default_capability_label(provider_title: str, model: dict[str, Any]) -> str:
    label = str(model.get("label") or model.get("id") or "").strip()
    return f"{provider_title} / {label}" if provider_title else label


def _default_model_capability_row(
    provider_id: str,
    provider_title: str,
    model: dict[str, Any],
) -> dict[str, Any]:
    row = copy.deepcopy(model)
    row["provider_id"] = provider_id
    row["provider_preset_id"] = provider_id
    row["label"] = _default_capability_label(provider_title, model)
    return _normalize_provider_model_metadata(row)


def _default_model_capabilities_from_catalog() -> dict[str, list[dict[str, Any]]]:
    provider_titles = {
        str(row.get("id") or ""): str(row.get("title") or row.get("name") or "").strip()
        for row in DEFAULT_PROVIDER_PRESETS
        if isinstance(row, dict)
    }
    capabilities: dict[str, list[dict[str, Any]]] = {
        "image": [],
        "video": [],
        "agent": [],
        "text": [],
    }
    seen: dict[str, set[str]] = {key: set() for key in capabilities}

    def add(target: str, provider_id: str, model: dict[str, Any]) -> None:
        model_id = str(model.get("id") or "").strip()
        if not model_id or model_id in seen[target]:
            return
        capabilities[target].append(
            _default_model_capability_row(
                provider_id,
                provider_titles.get(provider_id, provider_id),
                model,
            )
        )
        seen[target].add(model_id)

    def storyboard_video_supported(model: dict[str, Any]) -> bool:
        native_modes = ((model.get("adapter_capabilities") or {}).get("keyframe_visual_inputs") or {}).get("modes")
        if native_modes and _normalize_duration_options(model.get("durations")):
            return True
        supports = {
            str(item).strip().lower()
            for item in model.get("supports", [])
            if str(item).strip()
        } if isinstance(model.get("supports"), list) else set()
        try:
            reference_limit = int(model.get("max_reference_images") or model.get("maxReferenceImages") or 0)
        except (TypeError, ValueError):
            reference_limit = 0
        return bool(
            _normalize_duration_options(model.get("durations") or model.get("allowedDurations"))
            and reference_limit >= 2
            and (
                model.get("supports_storyboard_reference_image") is True
                or model.get("supportsStoryboardReferenceImage") is True
                or "storyboard_reference_image" in supports
            )
            and (
                model.get("supports_multi_reference_images") is True
                or model.get("supportsMultiReferenceImages") is True
                or "multi_reference_video" in supports
            )
            and (
                model.get("supports_native_audio") is True
                or model.get("supportsNativeAudio") is True
                or model.get("audio") is True
                or "native_audio" in supports
            )
        )

    for provider_id, models in BUILTIN_PROVIDER_MODELS.items():
        for model in models:
            if not isinstance(model, dict):
                continue
            model_type = str(model.get("type") or "").strip().lower()
            if model_type == "image":
                add("image", provider_id, model)
                continue
            if model_type == "video":
                if storyboard_video_supported(model):
                    add("video", provider_id, model)
                continue
            if model_type != "text":
                continue
            supports = {
                str(item).strip().lower()
                for item in model.get("supports", [])
                if str(item).strip()
            } if isinstance(model.get("supports"), list) else set()
            usage = str(model.get("usage") or "").casefold()
            if provider_id in {"anthropic", "deepseek", "minimax", "ark-agent-plan", "gemini"} or "智能体" in usage:
                add("agent", provider_id, model)
            if provider_id != "ark-agent-plan" and (
                "text_generation" in supports
                or "vision" in supports
                or "文本处理" in usage
                or provider_id in {"anthropic", "deepseek", "minimax", "ark-seedance", "dashscope", "gemini"}
            ):
                add("text", provider_id, model)
    return capabilities


DEFAULT_MODEL_CAPABILITIES: dict[str, list[dict[str, Any]]] = _default_model_capabilities_from_catalog()

for _image_capability in DEFAULT_MODEL_CAPABILITIES.get("image", []):
    _schema = image_resolution_schema_for_model(_image_capability)
    if _schema:
        _image_capability["image_resolution_schema"] = copy.deepcopy(_schema)
        _image_capability["imageResolutionSchema"] = copy.deepcopy(_schema)


DEFAULT_MODEL_CONFIG: dict[str, Any] = {
    "image": {
        "model_id": "",
        "character_resolution": DEFAULT_IMAGE_GENERATION_PARAMETERS["character"]["default_resolution"],
        "scene_resolution": DEFAULT_IMAGE_GENERATION_PARAMETERS["scene"]["default_resolution"],
        "prop_resolution": DEFAULT_IMAGE_GENERATION_PARAMETERS["prop"]["default_resolution"],
        "asset_resolution": DEFAULT_IMAGE_GENERATION_PARAMETERS["asset"]["default_resolution"],
        "storyboard_resolution": DEFAULT_IMAGE_GENERATION_PARAMETERS["storyboard"]["default_resolution"],
        "image_output_format": "auto",
    },
    "video": {
        "model_id": "ark:doubao-seedance-2-0-260128",
        "resolution": "720p",
        "duration_seconds": 8,
        "generate_audio": True,
    },
    "agent": {
        "model_id": "",
        "temperature": 0.4,
        "max_tokens": 8192,
    },
    "text": {
        "model_id": "",
        "overview_excerpt_chars": DEFAULT_OVERVIEW_EXCERPT_CHARS,
    },
}


def _default_provider_rows() -> list[dict[str, Any]]:
    return []


DEFAULT_GLOBAL_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "content_modes": [
        {
            "id": "drama",
            "name": "故事版视频",
            "description": "按分集原文创建剧情片段、分镜脚本、分镜和视频。",
        },
    ],
    "aspect_ratios": ["16:9", "9:16"],
    "provider_presets": DEFAULT_PROVIDER_PRESETS,
    "providers": _default_provider_rows(),
    "model_capabilities": DEFAULT_MODEL_CAPABILITIES,
    "model_config": DEFAULT_MODEL_CONFIG,
    "defaults": {
        "pipeline_mode": "storyboard_video",
        "content_mode": "drama",
        "aspect_ratio": "16:9",
        "source_language": "zh-CN",
        "episode_target_units": DEFAULT_EPISODE_TARGET_UNITS,
        "asset_extraction_target_units": DEFAULT_ASSET_EXTRACTION_TARGET_UNITS,
        "style_template_id": "urban_boss_romance_drama",
        "models": {
            "text": "",
            "agent": "",
            "image": "",
            "video": "火山方舟 / doubao-seedance-2-0-260128",
        },
        "storyboard": {
            "panel_count": 3,
            "layout": "auto",
            "reading_order": "left_to_right",
            "image_model": "",
            "image_size": OPENAI_GPT_IMAGE_2_DEFAULT_RESOLUTION,
            "image_output_format": "auto",
            "allow_manual_storyboard": True,
        },
        "video": {
            "provider": "ark-seedance",
            "model": "火山方舟 / doubao-seedance-2-0-260128",
            "duration_seconds": 8,
            "resolution": "720p",
            "generate_audio": True,
            "seed": None,
        },
        "project_feature_overrides": {
            "storyboard_generation": {
                "use_project_style": True,
                "use_project_assets": True,
            }
        },
    },
}

DEFAULT_SCRIPT_ADAPTATION_TEMPLATES: list[dict[str, Any]] = script_adaptation_templates()

DEFAULT_TEXT_REPLACEMENT_RULES: list[dict[str, str]] = [
    {"from": "找死", "to": "找嘎"},
    {"from": "人头", "to": "西瓜"},
]

GENERAL_STYLE_TEMPLATE_ID = "general_universal_high_art"
GENERAL_VISUAL_TYPE_TAGS = [
    "真人写实 · 现实主义影视",
    "真人写实 · 商业精修影像",
    "真人写实 · 照片级CG",
    "3D动漫 · 风格化写实",
    "3D动漫 · 美式电影卡通",
    "3D动漫 · 萌系圆润卡通",
    "3D动漫 · 低多边形几何",
    "3D国漫 · 精致美型CG",
    "3D国漫 · 写实PBR CG",
    "3D国漫 · 三渲二赛璐璐",
    "三渲二 · 日式赛璐璐",
    "三渲二 · 美式图形小说",
    "三渲二 · 国风水墨",
    "2D动漫 · 日式赛璐璐",
    "2D动漫 · 国漫赛璐璐",
    "2D动漫 · 国风水墨",
    "2D插画 · 半写实国漫",
    "2D插画 · 厚涂概念",
    "2D漫画 · 韩漫精修条漫",
    "2D漫画 · 美漫图形漫画",
    "混合媒介 · 实验动画",
]
GENERAL_VISUAL_TYPE_STYLE_PROMPTS: dict[str, dict[str, str]] = {
    "真人写实 · 现实主义影视": {
        "asset_prompt": "画面类型：真人写实 · 现实主义影视，统一美术风格：现实主义真人影像路线，以真实比例、自然造型、可信细节和克制美术处理为核心，整体可信、朴素、可表演",
        "character_asset_prompt": "画面类型：真人写实 · 现实主义影视，角色视觉：人物以真实影视角色审美为核心，外貌自然可信，五官、发型、妆容和服装贴合身份与生活质感；避免过度偶像化和夸张造型，重点突出人物气质、年龄感和可表演性",
        "creature_asset_prompt": "画面类型：真人写实 · 现实主义影视，生物视觉：生物以真实动物或可信特殊生物审美为核心，身体结构自然合理，头部、四肢、爪牙、尾、翼或毛发等特征控制在真实镜头可成立的范围内",
    },
    "真人写实 · 商业精修影像": {
        "asset_prompt": "画面类型：真人写实 · 商业精修影像，统一美术风格：真人影像与商业美术审美结合，真实结构适度美化，整体造型更干净、精致、明确，比现实更漂亮但仍保持可信",
        "character_asset_prompt": "画面类型：真人写实 · 商业精修影像，角色视觉：人物以商业真人主角审美为核心，外貌漂亮或有强辨识度，五官干净，妆容精修，发型利落，服装突出身份和气质；避免假脸感和过度网红化",
        "creature_asset_prompt": "画面类型：真人写实 · 商业精修影像，生物视觉：生物以真人影像可呈现的特殊生物审美为核心，轮廓清楚，头部、爪、尾、翼、鳞或毛发等特征集中好读；避免复杂怪物结构和廉价道具感",
    },
    "真人写实 · 照片级CG": {
        "asset_prompt": "画面类型：真人写实 · 照片级CG，统一美术风格：照片级写实CG路线，以真实比例、真实形体和高拟真细节为核心，整体接近真实影像，避免卡通化、漫画化和过度美化",
        "character_asset_prompt": "画面类型：真人写实 · 照片级CG，角色视觉：人物以真实演员级外貌为核心，五官结构自然，脸型、眼神、发型、妆容、服装都保持可信；可以精致好看，但避免假脸、网红滤镜和塑料感",
        "creature_asset_prompt": "画面类型：真人写实 · 照片级CG，生物视觉：生物以真实生态可信度为核心，骨骼、肌肉、头部、肢体、爪牙、翼膜、鳞片或毛发符合自然逻辑；特异化设计像真实物种演化而来",
    },
    "3D动漫 · 风格化写实": {
        "asset_prompt": "画面类型：3D动漫 · 风格化写实，统一美术风格：stylized realistic 3D路线，写实结构与动画概括平衡，造型饱满、轮廓清楚，整体成熟精致但不过分拟真",
        "character_asset_prompt": "画面类型：3D动漫 · 风格化写实，角色视觉：人物以风格化写实动画审美为核心，五官立体但更有设计感，眼神和表情清楚；发型、服装、身形比例形成漂亮剪影，整体有主角辨识度",
        "creature_asset_prompt": "画面类型：3D动漫 · 风格化写实，生物视觉：生物以风格化写实动画生物审美为核心，体块清楚，头部、四肢、翼、尾、角、爪或毛发形成强识别轮廓；可威严或可亲，但设计重点必须集中",
    },
    "3D动漫 · 美式电影卡通": {
        "asset_prompt": "画面类型：3D动漫 · 美式电影卡通，统一美术风格：圆润几何化3D卡通路线，真实结构适度简化，体块饱满，表情夸张传神，整体亲和、明快、有电影动画质感",
        "character_asset_prompt": "画面类型：3D动漫 · 美式电影卡通，角色视觉：人物以美式动画角色审美为核心，头身比例适度夸张，脸部形状圆润，眼睛和表情有强表现力；服装剪影简洁，整体讨喜、有喜剧感和角色魅力",
        "creature_asset_prompt": "画面类型：3D动漫 · 美式电影卡通，生物视觉：生物以卡通化动物或虚构小兽审美为核心，轮廓圆润、体块清楚、表情可读；突出大耳、短爪、尾巴、绒毛、翅膀或嘴鼻形状等亲和识别点",
    },
    "3D动漫 · 萌系圆润卡通": {
        "asset_prompt": "画面类型：3D动漫 · 萌系圆润卡通，统一美术风格：柔软圆润的可爱3D动画路线，体块饱满，边缘柔和，造型简洁，整体轻快、治愈、低攻击性",
        "character_asset_prompt": "画面类型：3D动漫 · 萌系圆润卡通，角色视觉：人物以萌系治愈角色审美为核心，头身比例可爱，脸部圆润，眼睛大而清澈，表情轻松讨喜；服装轮廓柔软，配饰少而精，整体干净亲近",
        "creature_asset_prompt": "画面类型：3D动漫 · 萌系圆润卡通，生物视觉：生物以软萌宠物和虚构小兽审美为核心，身体圆润，耳朵、尾巴、翅膀、爪垫或毛团形成可爱识别点；避免尖锐恐怖和过度复杂",
    },
    "3D动漫 · 低多边形几何": {
        "asset_prompt": "画面类型：3D动漫 · 低多边形几何，统一美术风格：Low Poly 极简几何路线，低面数块面、抽象体块和清晰剪影为主，整体简洁、抽象、图形化",
        "character_asset_prompt": "画面类型：3D动漫 · 低多边形几何，角色视觉：人物以极简几何角色审美为核心，用头身比例、发型大块面、服装外轮廓和少量标志色建立识别度；五官可以高度概括，但姿态必须清楚",
        "creature_asset_prompt": "画面类型：3D动漫 · 低多边形几何，生物视觉：生物以几何化图标式异兽审美为核心，用大体块、尖角、尾巴、翅膀、爪或背脊形成清晰剪影；形态要有趣、稀有、易读",
    },
    "3D国漫 · 精致美型CG": {
        "asset_prompt": "画面类型：3D国漫 · 精致美型CG，统一美术风格：国漫风格化3D CG路线，写实结构与动画概括结合，造型精致、轮廓修长、整体干净华丽但不浮夸",
        "character_asset_prompt": "画面类型：3D国漫 · 精致美型CG，角色视觉：人物以高颜值国漫角色审美为核心，五官精修，眼神清亮，脸型干净耐看；发型有层次，服装突出肩颈、腰线、长摆和配饰节奏，整体漂亮、有主角感",
        "creature_asset_prompt": "画面类型：3D国漫 · 精致美型CG，生物视觉：生物以精致国漫异兽审美为核心，轮廓优美神秘，头部、角、爪、翼、尾、鳞片或鬃毛形成清晰标志；身体兼具力量感和流线感",
    },
    "3D国漫 · 写实PBR CG": {
        "asset_prompt": "画面类型：3D国漫 · 写实PBR CG，统一美术风格：PBR写实CG与国漫审美融合，真实体积、精细造型和动画化审美并重，整体真实可信但保留国漫审美特征",
        "character_asset_prompt": "画面类型：3D国漫 · 写实PBR CG，角色视觉：人物以写实国漫CG角色审美为核心，五官立体自然但更精修，眼神、发型、妆容和服装结构完整；比例稳重，整体像高规格角色设定",
        "creature_asset_prompt": "画面类型：3D国漫 · 写实PBR CG，生物视觉：生物以写实国漫CG生物设定审美为核心，身体结构可信，头部、角、爪、翼、尾、鳞片、毛发等特征有清晰主次；整体稀有、有体量感",
    },
    "3D国漫 · 三渲二赛璐璐": {
        "asset_prompt": "画面类型：3D国漫 · 三渲二赛璐璐，统一美术风格：3D建模结合国漫赛璐璐渲染，硬边块面、明确描边和动画化形体并重，整体像高完成度国漫番剧画面",
        "character_asset_prompt": "画面类型：3D国漫 · 三渲二赛璐璐，角色视觉：人物以国漫三渲二角色审美为核心，眉眼清晰，脸部简洁漂亮，发型轮廓强；服装靠剪影、腰线、肩颈、长摆和少量标志符号建立身份",
        "creature_asset_prompt": "画面类型：3D国漫 · 三渲二赛璐璐，生物视觉：生物以国漫三渲二异兽审美为核心，大轮廓清楚，再强化角、耳、翼、尾、爪、鳞或毛团等识别点；结构简洁，适合多角度复现",
    },
    "三渲二 · 日式赛璐璐": {
        "asset_prompt": "画面类型：三渲二 · 日式赛璐璐，统一美术风格：3D建模结合日式动画赛璐璐渲染，硬边块面、明确描边、平面化上色，整体像可动画化的高完成度番剧画面",
        "character_asset_prompt": "画面类型：三渲二 · 日式赛璐璐，角色视觉：人物以日式三渲二角色审美为核心，脸部简洁漂亮，眼睛形状有强记忆点，发型用大块面组织；服装靠清晰剪影、色块节奏和少量标志符号建立身份",
        "creature_asset_prompt": "画面类型：三渲二 · 日式赛璐璐，生物视觉：生物以日式三渲二虚构生物设定为核心，优先保证大轮廓好看，再强化角、耳、翼、尾、爪、鳞或毛团等识别点；结构简洁，适合多角度复现",
    },
    "三渲二 · 美式图形小说": {
        "asset_prompt": "画面类型：三渲二 · 美式图形小说，统一美术风格：三维结构结合图形小说式块面、粗轮廓和笔触感，画面有强烈设计感、节奏感和漫画张力",
        "character_asset_prompt": "画面类型：三渲二 · 美式图形小说，角色视觉：人物以强剪影和图形化表演为核心，脸部轮廓、眉眼形状、发型块面和服装外轮廓要一眼可识别；服饰用大色块、局部图案、夸张肩线或外套形体建立个性",
        "creature_asset_prompt": "画面类型：三渲二 · 美式图形小说，生物视觉：生物以图形化怪物和漫画异兽审美为核心，突出夸张大轮廓、强节奏肢体、标志性头部和爪牙翼尾；细节以块面和符号组织，避免写实脏乱",
    },
    "三渲二 · 国风水墨": {
        "asset_prompt": "画面类型：三渲二 · 国风水墨，统一美术风格：3D结构结合水墨非真实感渲染，造型写意、线面留白、轮廓含蓄，整体有东方气韵和动画感",
        "character_asset_prompt": "画面类型：三渲二 · 国风水墨，角色视觉：人物以东方写意人物审美为核心，五官简练但神韵清楚，眉眼、发髻、衣袍轮廓形成主要美感；服装强调长线条、宽袖、衣摆、束带和疏密节奏",
        "creature_asset_prompt": "画面类型：三渲二 · 国风水墨，生物视觉：生物以东方异兽和灵物审美为核心，轮廓写意且有神性，突出角、羽、鳞、尾、须、爪等具备笔墨表现力的特征；结构可概括但必须优美灵动",
    },
    "2D动漫 · 日式赛璐璐": {
        "asset_prompt": "画面类型：2D动漫 · 日式赛璐璐，统一美术风格：日式二维动画路线，清晰线稿、硬边块面上色、平面化处理，整体轻盈、稳定、番剧感明确",
        "character_asset_prompt": "画面类型：2D动漫 · 日式赛璐璐，角色视觉：人物以日式动画角色审美为核心，眼型、发型和服装剪影是主要记忆点；五官简洁漂亮，表情清晰，服装层次适中，色块干净，适合多镜头复现",
        "creature_asset_prompt": "画面类型：2D动漫 · 日式赛璐璐，生物视觉：生物以动画化非人类生物或宠物审美为核心，轮廓简洁，特征明确，角、耳、尾、翼、爪或毛团要一眼可读；避免写实复杂",
    },
    "2D动漫 · 国漫赛璐璐": {
        "asset_prompt": "画面类型：2D动漫 · 国漫赛璐璐，统一美术风格：二维国漫赛璐璐路线，线条利落，块面清楚，造型更修长精致，整体偏商业动画和漫画改编审美",
        "character_asset_prompt": "画面类型：2D动漫 · 国漫赛璐璐，角色视觉：人物以国漫动画角色审美为核心，眉眼清晰，发型外轮廓强，服装强调剪影、腰线、肩颈、长摆和动作姿态；角色要有明显身份感和登场气势",
        "creature_asset_prompt": "画面类型：2D动漫 · 国漫赛璐璐，生物视觉：生物以动画化异兽或虚构宠物审美为核心，轮廓锐利清楚，突出角、爪、牙、翼、尾、背刺等识别特征；结构清楚，适合分镜中快速识别",
    },
    "2D动漫 · 国风水墨": {
        "asset_prompt": "画面类型：2D动漫 · 国风水墨，统一美术风格：二维国风水墨动画路线，写意线条、留白、笔墨概括和古典色彩并重，整体清雅、灵动、有东方意境",
        "character_asset_prompt": "画面类型：2D动漫 · 国风水墨，角色视觉：人物以古典写意审美为核心，眉眼、发髻、衣袍和身姿形成主要气韵；服装强调长线条、宽袖、衣摆、束带和疏密留白，少用碎装饰",
        "creature_asset_prompt": "画面类型：2D动漫 · 国风水墨，生物视觉：生物以水墨灵物和东方异兽审美为核心，轮廓要优雅、有神性，突出角、羽、鳞、尾、须、爪等适合笔墨表现的特征；形态可写意变形",
    },
    "2D插画 · 半写实国漫": {
        "asset_prompt": "画面类型：2D插画 · 半写实国漫，统一美术风格：国漫半写实插画路线，精细线稿与绘画概括结合，人物漂亮，造型规整，整体偏商业漫画和封面立绘审美",
        "character_asset_prompt": "画面类型：2D插画 · 半写实国漫，角色视觉：人物以高颜值半写实国漫审美为核心，五官精修，眼型、眉形、唇形要有记忆点；妆容干净有气质，发型层次清楚，服装强调剪裁、腰线、肩颈、袖摆和饰品节奏",
        "creature_asset_prompt": "画面类型：2D插画 · 半写实国漫，生物视觉：生物以半写实插画化异兽审美为核心，强调优雅轮廓和标志性部位，角、羽、鳞、尾、爪、鬃毛等元素组织成清晰设计语言；避免细节平均铺满",
    },
    "2D插画 · 厚涂概念": {
        "asset_prompt": "画面类型：2D插画 · 厚涂概念，统一美术风格：数字厚涂概念插画路线，写实结构与绘画概括结合，笔触感明确，整体有设定集和概念设计质感",
        "character_asset_prompt": "画面类型：2D插画 · 厚涂概念，角色视觉：人物以概念设计级角色审美为核心，面部结构有立体感，眼神、发型、服装外轮廓和局部装饰要有设计重点；服饰强调造型节奏、层次分区、身份符号和绘画感",
        "creature_asset_prompt": "画面类型：2D插画 · 厚涂概念，生物视觉：生物以概念设计级异兽审美为核心，先建立独特大轮廓，再组织角、骨刺、鳞甲、羽翼、爪牙、毛发或能量器官等特征；结构可信且有想象力",
    },
    "2D漫画 · 韩漫精修条漫": {
        "asset_prompt": "画面类型：2D漫画 · 韩漫精修条漫，统一美术风格：半写实韩式网络漫画路线，线条清爽，薄涂与赛璐璐融合，人物精致，整体干净、商业感强",
        "character_asset_prompt": "画面类型：2D漫画 · 韩漫精修条漫，角色视觉：人物以韩漫高颜值审美为核心，脸型修长，五官精修，眼神、睫毛、唇形和发丝层次要漂亮；服装强调干净剪裁、身形优势和精致配饰",
        "creature_asset_prompt": "画面类型：2D漫画 · 韩漫精修条漫，生物视觉：生物以精致条漫非人类生物审美为核心，轮廓优雅、线条干净，特征集中在头部、翼、尾、角、毛发或宝石状装饰；避免粗糙怪物感",
    },
    "2D漫画 · 美漫图形漫画": {
        "asset_prompt": "画面类型：2D漫画 · 美漫图形漫画，统一美术风格：美式漫画图形化路线，线条力度强，块面造型明确，符号化表达突出，整体有漫画海报张力",
        "character_asset_prompt": "画面类型：2D漫画 · 美漫图形漫画，角色视觉：人物以美式漫画角色审美为核心，强壮或夸张的身体比例、明确下颌和眉眼、强剪影服装是重点；服饰用大块面分区、外轮廓、图案符号和结构节奏突出身份",
        "creature_asset_prompt": "画面类型：2D漫画 · 美漫图形漫画，生物视觉：生物以漫画化怪物、宠兽或异种审美为核心，夸张体型、巨爪、獠牙、触手、翼尾或甲壳形成强烈剪影；特征要大胆明确，避免普通动物化",
    },
    "混合媒介 · 实验动画": {
        "asset_prompt": "画面类型：混合媒介 · 实验动画，统一美术风格：3D、2D手绘、拼贴或定格质感混合的实验路线，媒介边界清晰，造型大胆，整体有作者动画和先锋视觉气质",
        "character_asset_prompt": "画面类型：混合媒介 · 实验动画，角色视觉：人物以强概念角色设计为核心，外貌不追求常规漂亮，而追求独特剪影、反常比例、标志性发型、服装结构和符号化妆容；整体怪诞但有审美秩序",
        "creature_asset_prompt": "画面类型：混合媒介 · 实验动画，生物视觉：生物以混合媒介奇异生命体审美为核心，形态可以拼贴、变形、抽象或半机械化，但必须有清晰大轮廓和核心特征；避免无序堆砌",
    },
}
GENERAL_VISUAL_TYPE_TAG_ALIASES = {
    "真人": "真人写实 · 现实主义影视",
    "真人风格": "真人写实 · 现实主义影视",
    "真人影视": "真人写实 · 现实主义影视",
    "真人写实": "真人写实 · 现实主义影视",
    "真人半写实": "真人写实 · 商业精修影像",
    "现实主义真人影视": "真人写实 · 现实主义影视",
    "风格化真人影像": "真人写实 · 商业精修影像",
    "超写实真人CG": "真人写实 · 照片级CG",
    "超写实照片级CG": "真人写实 · 照片级CG",
    "风格化真人短剧": "真人写实 · 商业精修影像",
    "商业化真人短剧": "真人写实 · 商业精修影像",
    "2D": "2D动漫 · 国漫赛璐璐",
    "2D动漫": "2D动漫 · 国漫赛璐璐",
    "2D 动漫": "2D动漫 · 国漫赛璐璐",
    "2D国漫": "2D动漫 · 国漫赛璐璐",
    "2D日漫": "2D动漫 · 日式赛璐璐",
    "2D韩漫": "2D漫画 · 韩漫精修条漫",
    "2D美漫": "2D漫画 · 美漫图形漫画",
    "2D半写实": "2D插画 · 半写实国漫",
    "2D赛璐璐动画": "2D动漫 · 日式赛璐璐",
    "日式赛璐璐2D动画": "2D动漫 · 日式赛璐璐",
    "国漫赛璐璐2D动画": "2D动漫 · 国漫赛璐璐",
    "半写实国漫插画": "2D插画 · 半写实国漫",
    "东方水墨2D动画": "2D动漫 · 国风水墨",
    "3D": "3D动漫 · 风格化写实",
    "3D动漫": "3D动漫 · 风格化写实",
    "3D 动漫": "3D动漫 · 风格化写实",
    "3D国漫": "3D国漫 · 精致美型CG",
    "3D美式卡通": "3D动漫 · 美式电影卡通",
    "3D欧美动画": "3D动漫 · 美式电影卡通",
    "3D日漫": "三渲二 · 日式赛璐璐",
    "3D日式三渲二": "三渲二 · 日式赛璐璐",
    "3D半写实": "3D动漫 · 风格化写实",
    "3D写实CG": "3D国漫 · 写实PBR CG",
    "风格化写实3D动画": "3D动漫 · 风格化写实",
    "美式电影级3D卡通": "3D动漫 · 美式电影卡通",
    "美式卡通3D动画": "3D动漫 · 美式电影卡通",
    "萌系圆润3D动画": "3D动漫 · 萌系圆润卡通",
    "萌系软糖3D动画": "3D动漫 · 萌系圆润卡通",
    "低多边形几何3D": "3D动漫 · 低多边形几何",
    "低多边形": "3D动漫 · 低多边形几何",
    "低多边形3D": "3D动漫 · 低多边形几何",
    "Low Poly": "3D动漫 · 低多边形几何",
    "low poly": "3D动漫 · 低多边形几何",
    "半写实": "2D插画 · 半写实国漫",
    "写实": "真人写实 · 现实主义影视",
    "国漫": "2D动漫 · 国漫赛璐璐",
    "日漫": "2D动漫 · 日式赛璐璐",
    "韩漫": "2D漫画 · 韩漫精修条漫",
    "美漫": "2D漫画 · 美漫图形漫画",
    "厚涂": "2D插画 · 厚涂概念",
    "厚涂插画": "2D插画 · 厚涂概念",
    "2D厚涂插画": "2D插画 · 厚涂概念",
    "三渲二": "三渲二 · 日式赛璐璐",
    "三渲二动画": "三渲二 · 日式赛璐璐",
    "日式赛璐璐三渲二": "三渲二 · 日式赛璐璐",
    "国风水墨三渲二": "三渲二 · 国风水墨",
    "美式图形小说三渲二": "三渲二 · 美式图形小说",
    "美式图形小说": "三渲二 · 美式图形小说",
    "国风水墨动画": "2D动漫 · 国风水墨",
    "实验混合媒介动画": "混合媒介 · 实验动画",
    "混合媒介实验动画": "混合媒介 · 实验动画",
    "东方仙侠3D国漫": "3D国漫 · 精致美型CG",
    "热血战斗3D国漫": "3D国漫 · 精致美型CG",
    "暗黑科幻3D国漫": "3D动漫 · 风格化写实",
    "东方玄幻写实CG": "3D国漫 · 写实PBR CG",
}
GENERAL_VISUAL_TYPE_PROMPTS = {
    visual_type_tag: f"画面类型：{visual_type_tag}。"
    for visual_type_tag in GENERAL_VISUAL_TYPE_TAGS
}


def _general_visual_type_style_prompt(
    visual_type_tag: Any,
    field: str = "asset_prompt",
    fallback: Any = "",
) -> str:
    tag = str(visual_type_tag or "").strip()
    tag = GENERAL_VISUAL_TYPE_TAG_ALIASES.get(tag, tag)
    prompts = GENERAL_VISUAL_TYPE_STYLE_PROMPTS.get(tag) or {}
    normalized_field = str(field or "asset_prompt").strip()
    value = str(prompts.get(normalized_field) or "").strip()
    if not value and normalized_field == "prompt":
        value = str(prompts.get("asset_prompt") or "").strip()
    if not value:
        value = str(prompts.get("asset_prompt") or "").strip()
    return value or str(fallback or "").strip()


GENERAL_GLOBAL_STYLE_PROMPT = _general_visual_type_style_prompt("3D国漫 · 精致美型CG", "asset_prompt")
GENERAL_CHARACTER_STYLE_PROMPT = _general_visual_type_style_prompt("3D国漫 · 精致美型CG", "character_asset_prompt")
GENERAL_CREATURE_STYLE_PROMPT = _general_visual_type_style_prompt("3D国漫 · 精致美型CG", "creature_asset_prompt")

STYLE_CATEGORY_META: dict[str, dict[str, str]] = {
    "general": {
        "label": "通用风格",
        "accent": "from-sky-500 via-fuchsia-500 to-amber-300",
    },
    "live_action": {
        "label": "真人短剧",
        "accent": "from-rose-500 via-orange-400 to-amber-300",
    },
    "two_d": {
        "label": "2D动漫",
        "accent": "from-amber-400 via-rose-500 to-pink-500",
    },
    "three_d": {
        "label": "3D动漫",
        "accent": "from-violet-500 via-indigo-500 to-sky-400",
    },
}


def _style_template(
    template_id: str,
    name: str,
    desc: str,
    category: str,
    prompt: str,
    asset_prompt: str = "",
    character_asset_prompt: str = "",
    creature_asset_prompt: str = "",
    visual_type_tags: list[str] | None = None,
    visual_type_style_prompts: dict[str, dict[str, str]] | None = None,
    default_visual_type_tag: str = "",
    thumbnail_file: str | None = None,
) -> dict[str, Any]:
    meta = STYLE_CATEGORY_META.get(category, STYLE_CATEGORY_META["live_action"])
    thumbnail_file = thumbnail_file or f"{template_id}.jpg"
    prompt = _strip_builtin_style_theme_visual_text(prompt, category)
    asset_prompt = _strip_builtin_style_theme_visual_text(asset_prompt, category)
    visual_type_style_prompts = copy.deepcopy(visual_type_style_prompts or {})
    template = {
        "id": template_id,
        "name": name,
        "desc": desc,
        "category": category,
        "categoryLabel": meta["label"],
        "accent": meta["accent"],
        "thumbnailFile": thumbnail_file,
        "thumbnail_file": thumbnail_file,
        "prompt": prompt,
        "asset_prompt": asset_prompt,
        "character_asset_prompt": character_asset_prompt,
        "creature_asset_prompt": creature_asset_prompt,
        "visual_type_tags": list(visual_type_tags or []),
        "default_visual_type_tag": default_visual_type_tag,
        "source": "preset",
    }
    if visual_type_style_prompts:
        template["visual_type_style_prompts"] = visual_type_style_prompts
        template["visualTypeStylePrompts"] = copy.deepcopy(visual_type_style_prompts)
    return template


DEFAULT_STYLE_TEMPLATES: list[dict[str, Any]] = [
    _style_template(
        "urban_boss_romance_drama",
        "现代都市 · 柔光真人",
        "真人 / 现代都市 / 商业短剧质感",
        "live_action",
        "画面类型：真人写实，统一美术风格：超写实写实路线，精致商业视觉取向，真实结构与自然写实造型语言",
        asset_prompt="画面类型：真人写实，统一美术风格：超写实写实路线，精致商业视觉取向，真实结构与自然写实造型语言",
        thumbnail_file="1.jpg",
    ),
    _style_template(
        "urban_workplace_comeback_drama",
        "现代都市 · 商务真人",
        "真人 / 现代都市 / 明亮现实质感",
        "live_action",
        "画面类型：真人写实，统一美术风格：写实主义美术路线，精致商业写实取向，造型规整克制，真实结构与自然细节表达",
        asset_prompt="画面类型：真人写实，统一美术风格：写实主义美术路线，精致商业写实取向，造型规整克制，真实结构与自然细节表达",
        thumbnail_file="2.jpg",
    ),
    _style_template(
        "urban_marriage_reality_drama",
        "现代都市 · 生活真人",
        "真人 / 现代生活 / 自然电视剧质感",
        "live_action",
        "画面类型：真人影视，统一美术风格：现实主义写实美术路线，生活化造型，结构真实自然，细节处理克制细腻",
        asset_prompt="画面类型：真人影视，统一美术风格：现实主义写实美术路线，生活化造型，结构真实自然，细节处理克制细腻",
        thumbnail_file="3.jpg",
    ),
    _style_template(
        "costume_palace_power_drama",
        "古代宫廷 · 厚重真人",
        "真人 / 架空古代 / 古典电影质感",
        "live_action",
        "画面类型：真人写实，统一美术风格：超写实PBR写实，东方华丽写实美术路线，写实结构与高度精细化造型结合",
        asset_prompt="画面类型：真人写实，统一美术风格：超写实PBR写实，东方华丽写实美术路线，写实结构与高度精细化造型结合",
        thumbnail_file="4.jpg",
    ),
    _style_template(
        "costume_general_revenge_epic",
        "古代边塞 · 冷色真人",
        "真人 / 架空古代 / 精致冷色影视感",
        "live_action",
        "画面类型：真人写实，统一美术风格：超写实PBR写实，东方写实美术路线，写实结构与高密度精细造型结合",
        asset_prompt="画面类型：真人写实，统一美术风格：超写实PBR写实，东方写实美术路线，写实结构与高密度精细造型结合",
        thumbnail_file="5.jpg",
    ),
    _style_template(
        "costume_wuxia_heroine",
        "古代江湖 · 暗调真人",
        "真人 / 古代江湖 / 港式武侠感",
        "live_action",
        "画面类型：真人写实，统一美术风格：超写实PBR写实，东方暗黑奇幻美术路线，写实结构与高度细节化造型语言",
        asset_prompt="画面类型：真人写实，统一美术风格：超写实PBR写实，东方暗黑奇幻美术路线，写实结构与高度细节化造型语言",
        thumbnail_file="6.jpg",
    ),
    _style_template(
        "xianxia_cultivation_sect",
        "古装玄幻 · 清亮2D",
        "2D / 古代修仙 / 国风幻想插画",
        "two_d",
        "画面类型：厚涂插画，统一美术风格：半写实数字厚涂，东方写意幻想美术路线，写实结构与精细化动画概括结合",
        asset_prompt="画面类型：厚涂插画，统一美术风格：半写实数字厚涂，东方写意幻想美术路线，写实结构与精细化动画概括结合",
        thumbnail_file="7.jpg",
    ),
    _style_template(
        "xianxia_gods_demons_epic",
        "古装玄幻 · 厚涂2D",
        "2D / 东方玄幻 / 史诗概念插画",
        "two_d",
        "画面类型：厚涂插画，统一美术风格：风格化写实厚涂，东方玄幻美术路线，写实结构与夸张概括结合，繁复装饰化造型",
        asset_prompt="画面类型：厚涂插画，统一美术风格：风格化写实厚涂，东方玄幻美术路线，写实结构与夸张概括结合，繁复装饰化造型",
        thumbnail_file="8.jpg",
    ),
    _style_template(
        "xianxia_spirit_beast_shanhai",
        "上古山海 · 水墨2D",
        "2D / 上古神话 / 水墨重彩国风",
        "two_d",
        "画面类型：厚涂插画，统一美术风格：东方玄幻风格化写实厚涂路线，写实结构与写意概括结合，细密装饰化造型语言",
        asset_prompt="画面类型：厚涂插画，统一美术风格：东方玄幻风格化写实厚涂路线，写实结构与写意概括结合，细密装饰化造型语言",
        thumbnail_file="9.jpg",
    ),
    _style_template(
        "folk_strange_village",
        "近现代乡村 · 民俗真人",
        "真人 / 近现代乡村 / 自然民俗影视质感",
        "live_action",
        "画面类型：真人影视，统一美术风格：PBR写实美术路线，东方暗黑奇幻取向，写实结构与现实细节高度还原结合",
        asset_prompt="画面类型：真人影视，统一美术风格：PBR写实美术路线，东方暗黑奇幻取向，写实结构与现实细节高度还原结合",
        thumbnail_file="10.jpg",
    ),
    _style_template(
        "folk_ghost_marriage_paper",
        "近现代民俗 · 低照度真人",
        "真人 / 中式民俗 / 精致民俗影视质感",
        "live_action",
        "画面类型：真人写实，统一美术风格：超写实PBR写实，东方民俗暗黑奇幻美术路线，写实结构与高细节造型语言结合",
        asset_prompt="画面类型：真人写实，统一美术风格：超写实PBR写实，东方民俗暗黑奇幻美术路线，写实结构与高细节造型语言结合",
        thumbnail_file="11.jpg",
    ),
    _style_template(
        "folk_detective_revenge",
        "民国小镇 · 冷青真人",
        "真人 / 民国近现代 / 冷青电影质感",
        "live_action",
        "画面类型：真人影视，统一美术风格：超写实自然主义路线，写实结构与克制细节还原，暗黑现实主义视觉取向",
        asset_prompt="画面类型：真人影视，统一美术风格：超写实自然主义路线，写实结构与克制细节还原，暗黑现实主义视觉取向",
        thumbnail_file="12.jpg",
    ),
    _style_template(
        "scifi_apocalypse_wasteland",
        "末世废土 · 真人电影",
        "真人 / 末世废土 / 精致工业科幻感",
        "live_action",
        "画面类型：3D写实CG，统一美术风格：超写实PBR写实，高拟真概念美术路线，写实结构与高密度细节刻画结合",
        asset_prompt="画面类型：3D写实CG，统一美术风格：超写实PBR写实，高拟真概念美术路线，写实结构与高密度细节刻画结合",
        thumbnail_file="13.jpg",
    ),
    _style_template(
        "scifi_mecha_future_war",
        "末世机甲 · 3D电影",
        "3D / 末世机甲 / 硬表面CG",
        "three_d",
        "画面类型：3D写实CG，统一美术风格：超写实PBR写实渲染，暗黑科幻视觉取向，写实结构与高密度工业化细节结合",
        asset_prompt="画面类型：3D写实CG，统一美术风格：超写实PBR写实渲染，暗黑科幻视觉取向，写实结构与高密度工业化细节结合",
        thumbnail_file="14.jpg",
    ),
    _style_template(
        "scifi_power_wasteland_future",
        "末世高武 · 科幻3D",
        "3D / 末世高武 / 科幻CG质感",
        "three_d",
        "画面类型：3D写实CG，统一美术风格：超写实PBR写实渲染，暗黑科幻奇幻美术路线，写实结构与高概念视觉设计结合",
        asset_prompt="画面类型：3D写实CG，统一美术风格：超写实PBR写实渲染，暗黑科幻奇幻美术路线，写实结构与高概念视觉设计结合",
        thumbnail_file="15.jpg",
    ),
    _style_template(
        "cyber_neon_city",
        "未来赛博 · 霓虹真人",
        "真人 / 未来都市 / 赛博霓虹光色",
        "live_action",
        "画面类型：厚涂插画，统一美术风格：风格化写实概念美术，赛博朋克科幻视觉取向，写实结构与高密度细节概括结合",
        asset_prompt="画面类型：厚涂插画，统一美术风格：风格化写实概念美术，赛博朋克科幻视觉取向，写实结构与高密度细节概括结合",
        thumbnail_file="16.jpg",
    ),
    _style_template(
        "cyber_underworld_night_city",
        "未来赛博 · 黑色真人",
        "真人 / 未来都市 / 金属冷光电影",
        "live_action",
        "画面类型：3D写实CG，统一美术风格：超写实PBR写实渲染，赛博朋克科幻美术路线，写实结构与高密度细节建模结合",
        asset_prompt="画面类型：3D写实CG，统一美术风格：超写实PBR写实渲染，赛博朋克科幻美术路线，写实结构与高密度细节建模结合",
        thumbnail_file="17.jpg",
    ),
    _style_template(
        "cyber_tech_suspense",
        "近未来科技 · 冷光真人",
        "真人 / 近未来科技 / 蓝绿冷光质感",
        "live_action",
        "画面类型：真人影视，统一美术风格：超写实写实美术路线，赛博朋克科幻视觉取向，现实结构与高概念科技感造型结合",
        asset_prompt="画面类型：真人影视，统一美术风格：超写实写实美术路线，赛博朋克科幻视觉取向，现实结构与高概念科技感造型结合",
        thumbnail_file="18.jpg",
    ),
    _style_template(
        "comic_korean_romance_webtoon",
        "现代都市 · 韩漫2D",
        "2D / 现代都市 / 半写实条漫",
        "two_d",
        "画面类型：2D半写实，统一美术风格：精致半写实漫画插画，赛璐璐与薄涂融合，写实结构与动画概括结合，细腻线稿",
        asset_prompt="画面类型：2D半写实，统一美术风格：精致半写实漫画插画，赛璐璐与薄涂融合，写实结构与动画概括结合，细腻线稿",
        thumbnail_file="19.jpg",
    ),
    _style_template(
        "comic_jp_campus_youth",
        "现代校园 · 日系2D",
        "2D / 现代校园 / 柔光赛璐珞",
        "two_d",
        "画面类型：2D日漫，统一美术风格：日式赛璐璐动画，偏风格化写实，写实结构与动画概括结合，线条精细，块面化平面渲染",
        asset_prompt="画面类型：2D日漫，统一美术风格：日式赛璐璐动画，偏风格化写实，写实结构与动画概括结合，线条精细，块面化平面渲染",
        thumbnail_file="20.jpg",
    ),
    _style_template(
        "comic_cn_storyboard_webtoon",
        "古代江湖 · 国漫2D",
        "2D / 古代江湖 / 条漫视觉质感",
        "two_d",
        "画面类型：2D国漫，统一美术风格：精细厚涂感赛璐璐动画，风格化写实三渲二，写实结构与动画概括结合，热血国漫美术路线",
        asset_prompt="画面类型：2D国漫，统一美术风格：精细厚涂感赛璐璐动画，风格化写实三渲二，写实结构与动画概括结合，热血国漫美术路线",
        thumbnail_file="21.jpg",
    ),
    _style_template(
        "guoman_3d_xuanhuan",
        "古装玄幻 · 国风3D",
        "3D / 古装玄幻 / 精致国漫质感",
        "three_d",
        "画面类型：3D国漫，统一美术风格：风格化写实CG，东方仙侠美术路线，写实结构与动画概括结合，精细化造型语言",
        asset_prompt="画面类型：3D国漫，统一美术风格：风格化写实CG，东方仙侠美术路线，写实结构与动画概括结合，精细化造型语言",
        thumbnail_file="22.jpg",
    ),
    _style_template(
        "guoman_cel_shaded_battle",
        "现代高武 · 三渲二3D",
        "3D / 现代高武 / 高饱和CG",
        "three_d",
        "画面类型：2D日漫，统一美术风格：日式赛璐璐半写实插画，热血奇幻动画美术路线，清晰描边，写实结构与动画概括结合",
        asset_prompt="画面类型：2D日漫，统一美术风格：日式赛璐璐半写实插画，热血奇幻动画美术路线，清晰描边，写实结构与动画概括结合",
        thumbnail_file="23.jpg",
    ),
    _style_template(
        "guoman_unreal_game_cg",
        "古装玄幻 · 写实3D",
        "3D / 古装玄幻 / 虚幻引擎CG",
        "three_d",
        "画面类型：3D写实CG，统一美术风格：PBR写实渲染，东方玄幻暗黑奇幻美术路线，高细节写实结构与装饰化造型结合",
        asset_prompt="画面类型：3D写实CG，统一美术风格：PBR写实渲染，东方玄幻暗黑奇幻美术路线，高细节写实结构与装饰化造型结合",
        thumbnail_file="24.jpg",
    ),
    _style_template(
        GENERAL_STYLE_TEMPLATE_ID,
        "通用风格",
        "选择风格分类，主题视觉由小说概述自动分析",
        "general",
        GENERAL_GLOBAL_STYLE_PROMPT,
        asset_prompt=GENERAL_GLOBAL_STYLE_PROMPT,
        character_asset_prompt=GENERAL_CHARACTER_STYLE_PROMPT,
        creature_asset_prompt=GENERAL_CREATURE_STYLE_PROMPT,
        visual_type_tags=GENERAL_VISUAL_TYPE_TAGS,
        visual_type_style_prompts=GENERAL_VISUAL_TYPE_STYLE_PROMPTS,
        default_visual_type_tag="3D国漫 · 精致美型CG",
        thumbnail_file="25.jpg",
    ),
]

DEFAULT_ASSETS: dict[str, list[dict[str, Any]]] = {
    "characters": [],
    "creatures": [],
    "scenes": [],
    "props": [],
    "styles": [],
}
ASSET_TYPES = tuple(DEFAULT_ASSETS.keys())

__all__ = (
    'OPENAI_GPT_IMAGE_2_RESOLUTIONS', 'OPENAI_GPT_IMAGE_2_DEFAULT_RESOLUTION',
    'DASHSCOPE_QWEN_IMAGE_RESOLUTIONS', 'DASHSCOPE_QWEN_IMAGE_DEFAULT_RESOLUTION',
    'DASHSCOPE_QWEN_IMAGE_EDIT_RESOLUTIONS', 'DASHSCOPE_QWEN_IMAGE_EDIT_DEFAULT_RESOLUTION',
    'STANDARD_COMPATIBLE_IMAGE_RESOLUTIONS', 'STANDARD_COMPATIBLE_VIDEO_RESOLUTIONS',
    'ARK_SEEDANCE_2_VIDEO_CAPABILITY_METADATA', 'ARK_SEEDANCE_25_VIDEO_CAPABILITY_METADATA',
    'DASHSCOPE_WAN27_VIDEO_CAPABILITY_METADATA', 'VIDU_Q3_VIDEO_CAPABILITY_METADATA',
    'DEFAULT_IMAGE_GENERATION_PARAMETERS',
    'DEFAULT_OVERVIEW_EXCERPT_CHARS', 'MIN_OVERVIEW_EXCERPT_CHARS', 'MAX_OVERVIEW_EXCERPT_CHARS',
    'DEFAULT_EPISODE_TARGET_UNITS', 'DEFAULT_ASSET_EXTRACTION_TARGET_UNITS', 'IMAGE_RESOLUTION_ALIASES',
    'LEGACY_IMAGE_RESOLUTION_TO_TIER', '_GPT_IMAGE_MAX_LONG_EDGE', '_GPT_IMAGE_MAX_TOTAL_PIXELS',
    '_GPT_IMAGE_MAX_RATIO', '_DASHSCOPE_STANDARD_PIXEL_BUDGET', '_DASHSCOPE_FOURK_PIXEL_BUDGET',
    '_DASHSCOPE_EDIT_MAX_LONG_EDGE', '_DASHSCOPE_MAX_RATIO', '_DASHSCOPE_EDIT_MAX_RATIO',
    'REFERENCE_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE', 'REFERENCE_IMAGE_INPUT_DEFAULT_MAX_BYTES',
    '_REFERENCE_IMAGE_INPUT_EDGE_BY_RESOLUTION', '_VIDEO_SIZE_PRESETS',
    'BACKEND_DIR', 'DATA_DIR', 'GLOBAL_DIR',
    'PROJECTS_DIR', 'AGENT_OPS_DIR', 'AGENT_OPS_CONSTRAINTS_DIR', 'AGENT_OPS_PERMISSIONS_DIR',
    'AGENT_OPS_PROMPTS_DIR', 'AGENT_OPS_SKILLS_DIR', 'STYLE_THUMBNAILS_DIR', 'GLOBAL_STYLE_REFERENCES_DIR',
    'FAVORITE_STYLE_THUMBNAILS_DIR', 'GLOBAL_ASSET_MEDIA_DIR', 'IMAGE_EXTENSIONS', 'AGENT_IMAGE_EXTENSIONS',
    'AGENT_FILE_EXTENSIONS', 'AGENT_ATTACHMENT_MAX_BYTES', 'AGENT_MODEL_IMAGE_INPUT_MAX_BYTES',
    'VIDEO_EXTENSIONS', 'MEDIA_TOOL_FILE_EXTENSIONS', 'MEDIA_TOOL_DEFAULT_ROOTS', 'MEDIA_TOOL_STDIO_LIMIT',
    'MEDIA_TOOL_MAX_ARGS', 'STYLE_ANALYSIS_PROMPT',
    'PROJECT_OVERVIEW_STRUCTURED_SCHEMA',
    'PROJECT_NAME_EXISTS_MESSAGE', 'CUSTOM_STYLE_REQUIRED_MESSAGE',
    'MODEL_CONFIG_REQUIRED_MESSAGE', 'SOURCE_LANGUAGE_OPTIONS', 'GLOBAL_CONFIG_PATH',
    'STYLE_PHASE_VISUAL_KEYS', 'STYLE_ACTIVE_PHASE_VISUAL_ID_KEYS',
    '_ensure_prompt_sentence_end', '_prompt_labeled_block', '_join_prompt_blocks',
    '_normalize_style_theme_visual_context', '_style_theme_visual_prompt_from_config',
    '_style_theme_visual_prompt_block', '_prepend_style_theme_visual_prompt',
    '_strip_style_theme_visual_overlap_text',
    '_normalize_style_phase_visual_context', '_normalize_style_phase_visuals', '_style_phase_visuals_from_mapping',
    '_style_active_phase_visual_id_from_mapping', '_active_style_phase_visual',
    '_style_phase_visual_prompt_from_config', '_style_phase_visual_prompt_block', '_append_style_phase_visual_prompt',
    '_compose_style_visual_prompt', '_style_visual_prompt_block', '_compose_image_visual_prompt',
    'GLOBAL_ASSETS_PATH', 'GLOBAL_STYLE_TEMPLATES_PATH',
    'GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH', 'GLOBAL_TEXT_REPLACEMENT_RULES_PATH',
    'GLOBAL_TASKS_PATH', 'GLOBAL_USAGE_PATH', 'ACCENTS', 'IMAGE_OUTPUT_FORMATS', 'IMAGE_OUTPUT_FORMAT_VALUES',
    'DEFAULT_PROVIDER_PRESETS', 'LEGACY_GENERIC_PROVIDER_MODEL_IDS', 'RETIRED_PROVIDER_PRESET_IDS',
    'PROVIDER_ADAPTER_SERVICE_IDS', 'SERVICE_PROVIDER_ADAPTER_IDS', '_normalize_resolution_label',
    '_normalize_resolution_options', '_normalize_duration_options', '_normalize_provider_model_metadata',
    '_catalog_model', 'BUILTIN_PROVIDER_MODELS', '_provider_preset', 'DEFAULT_MODEL_CAPABILITIES',
    '_default_model_capabilities_from_catalog', 'DEFAULT_MODEL_CONFIG',
    '_positive_int_value', '_reference_image_input_default_max_long_edge',
    '_default_provider_rows', 'DEFAULT_GLOBAL_CONFIG',
    'DEFAULT_SCRIPT_ADAPTATION_TEMPLATES',
    'DEFAULT_TEXT_REPLACEMENT_RULES', 'GENERAL_STYLE_TEMPLATE_ID', 'GENERAL_VISUAL_TYPE_TAGS',
    'GENERAL_VISUAL_TYPE_PROMPTS', 'GENERAL_VISUAL_TYPE_STYLE_PROMPTS', 'GENERAL_VISUAL_TYPE_TAG_ALIASES',
    '_general_visual_type_style_prompt',
    'GENERAL_GLOBAL_STYLE_PROMPT', 'GENERAL_CHARACTER_STYLE_PROMPT',
    'GENERAL_CREATURE_STYLE_PROMPT',
    'STYLE_CATEGORY_META', '_style_template', 'DEFAULT_STYLE_TEMPLATES',
    'DEFAULT_ASSETS', 'ASSET_TYPES'
)
