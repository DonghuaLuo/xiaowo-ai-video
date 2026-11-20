# -*- coding: utf-8 -*-
"""风格图分析、项目封面和风格参考保存。"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
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
    parse_aspect_ratio,
    resolution_to_short_edge,
)
from utils.image_pipeline import (
    convert_image_bytes_to_png,
    data_url_from_bytes,
    prepare_provider_image_bytes,
    prepare_provider_image_data_uri,
    save_project_image,
    save_provider_output_image,
)
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

from .model_provider_config import (
    _configured_provider_for_model,
    _project_model_config,
)
from .model_style_analysis import (
    _call_style_analysis_model,
)
from .media_files import _source_image_data_url
from .media_files import _storage_png_data_url

from .catalogs import STYLE_ANALYSIS_PROMPT
from .store_core import _now

def analyze_style_image(
    file_info: dict[str, Any] | None,
    project_id: str | None = None,
) -> dict[str, Any]:
    from .provider_models import _find_model
    from .provider_models import _is_connected_provider
    from .media_files import _local_image_source_from_media
    from .provider_models import _model_supports_vision_input
    from .agent_sessions import _project_config_path
    from .agent_sessions import _project_file_from_ref
    if not file_info or not (
        _source_image_data_url(file_info)
        or _project_file_from_ref(project_id, file_info)
        or _local_image_source_from_media(file_info)
    ):
        return {"success": False, "message": "请先上传风格参考图"}
    name = str(file_info.get("name") or "style-reference")
    resolved_project_id = str(project_id or "").strip()
    if resolved_project_id:
        project_config_path = _project_config_path(resolved_project_id)
        if not project_config_path.exists():
            return {"success": False, "message": "项目不存在"}
    try:
        global_config, capabilities, model_config = _project_model_config(
            resolved_project_id or None
        )
    except ValueError as exc:
        return {"success": False, "message": str(exc)}
    config_source = "global"
    text_config = (
        model_config.get("text") if isinstance(model_config.get("text"), dict) else {}
    )
    text_model_id = str(text_config.get("model_id") or "").strip()
    text_model = _find_model(text_model_id, "text", capabilities)
    if not text_model:
        message = "请先在全局设置中选择文本模型"
        return {
            "success": False,
            "message": message,
            "analysis": {
                "fileName": name,
                "prompt": STYLE_ANALYSIS_PROMPT,
                "modelId": text_model_id,
                "projectId": resolved_project_id or None,
                "configSource": config_source,
                "providerConfigured": False,
            },
        }
    if not _model_supports_vision_input(text_model):
        message = "当前文本模型不支持图片输入，请在全局设置中选择支持视觉输入的文本模型"
        return {
            "success": False,
            "message": message,
            "analysis": {
                "fileName": name,
                "prompt": STYLE_ANALYSIS_PROMPT,
                "modelId": text_model_id,
                "modelLabel": text_model.get("label") or text_model.get("id"),
                "providerId": text_model.get("provider_id"),
                "projectId": resolved_project_id or None,
                "configSource": config_source,
                "providerConfigured": False,
            },
        }
    provider = _configured_provider_for_model(text_model, global_config.get("providers", []))
    provider_title = (
        provider.get("title")
        if provider
        else text_model.get("provider_id") or "未配置供应商"
    )
    provider_configured = bool(provider and _is_connected_provider(provider))
    if not provider_configured or not provider:
        return {
            "success": False,
            "message": "请先在全局设置中完成供应商连接测试",
            "analysis": {
                "fileName": name,
                "prompt": STYLE_ANALYSIS_PROMPT,
                "modelId": text_model.get("id"),
                "modelLabel": text_model.get("label") or text_model.get("id"),
                "providerId": text_model.get("provider_id"),
                "providerTitle": provider_title,
                "providerConfigured": False,
                "projectId": resolved_project_id or None,
                "configSource": config_source,
            },
        }
    try:
        description = _call_style_analysis_model(provider, text_model, file_info, resolved_project_id)
    except Exception as exc:
        return {
            "success": False,
            "message": f"风格分析失败：{str(exc)}",
            "analysis": {
                "fileName": name,
                "prompt": STYLE_ANALYSIS_PROMPT,
                "modelId": text_model.get("id"),
                "modelLabel": text_model.get("label") or text_model.get("id"),
                "providerId": text_model.get("provider_id"),
                "providerTitle": provider_title,
                "providerConfigured": True,
                "projectId": resolved_project_id or None,
                "configSource": config_source,
                "error": str(exc),
            },
        }
    return {
        "success": True,
        "style_description": description,
        "analysis": {
            "fileName": name,
            "prompt": STYLE_ANALYSIS_PROMPT,
            "modelId": text_model.get("id"),
            "modelLabel": text_model.get("label") or text_model.get("id"),
            "providerId": text_model.get("provider_id"),
            "providerTitle": provider_title,
            "providerConfigured": provider_configured,
            "projectId": resolved_project_id or None,
            "configSource": config_source,
            "source": "model",
        },
    }


def _save_project_cover(project_id: str, file_info: dict[str, Any]) -> dict[str, Any]:
    from .media_files import _copy_local_project_config_image_file
    from .media_files import _decode_data_url
    from .media_files import _has_image_file_input
    from .media_files import _local_image_source_from_media
    from .media_files import _save_project_config_image_file
    if not isinstance(file_info, dict) or not _has_image_file_input(file_info):
        raise ValueError("请上传项目封面图片")
    data_url = _storage_png_data_url(file_info)
    local_source = _local_image_source_from_media(file_info)
    ref_id = f"cover-{uuid.uuid4().hex[:10]}"
    if not data_url and local_source:
        source_path, source_mime = local_source
        if not source_mime.startswith("image/"):
            raise ValueError("项目封面只支持 png、jpg 或 webp")
        media = _copy_local_project_config_image_file(
            project_id,
            source_path,
            media_id=ref_id,
            subdir="covers",
            original_name=str(file_info.get("name") or source_path.name),
            source_mime=source_mime,
        )
        return {
            "id": ref_id,
            "name": file_info.get("name") or media.get("file") or source_path.name,
            "mimeType": media.get("mimeType") or source_mime,
            "path": media.get("path"),
            "relativePath": media.get("relativePath"),
            "relative_path": media.get("relative_path"),
            "createdAt": _now(),
        }
    if data_url:
        raw, mime = _decode_data_url(data_url)
    else:
        raise ValueError("请上传项目封面图片")
    if not mime.startswith("image/"):
        raise ValueError("项目封面只支持 png、jpg 或 webp")
    media = _save_project_config_image_file(
        project_id,
        raw,
        media_id=ref_id,
        subdir="covers",
        original_name=str(file_info.get("name") or ""),
        source_mime=mime,
    )
    return {
        "id": ref_id,
        "name": file_info.get("name") or media.get("file") or f"{ref_id}.png",
        "mimeType": "image/png",
        "path": media.get("path"),
        "relativePath": media.get("relativePath"),
        "relative_path": media.get("relative_path"),
        "createdAt": _now(),
    }


def _save_style_reference(project_id: str, file_info: dict[str, Any], style_description: str = "") -> dict[str, Any]:
    from .media_files import _image_media_from_file_info
    ref_id = f"style-{uuid.uuid4().hex[:10]}"
    media = _image_media_from_file_info(project_id, file_info, media_id=ref_id, subdir="styles")
    return {
        "id": ref_id,
        "name": file_info.get("name") or media.get("file") or f"{ref_id}.png",
        "mimeType": media.get("mimeType") or "image/png",
        "path": media.get("path"),
        "relativePath": media.get("relativePath"),
        "relative_path": media.get("relative_path"),
        "styleDescription": style_description,
        "createdAt": _now(),
    }

__all__ = ('analyze_style_image', '_save_project_cover', '_save_style_reference',)
