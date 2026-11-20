# -*- coding: utf-8 -*-
"""分镜图片生成与编辑：请求准备、模型调用和原图保存。"""
from __future__ import annotations

from .agent_sessions import _persistent_media_data_removed
from .catalogs import _append_style_phase_visual_prompt
from .catalogs import _style_phase_visual_prompt_block
from .catalogs import _style_phase_visual_prompt_from_config
from .catalogs import _style_theme_visual_prompt_block
from .catalogs import _style_theme_visual_prompt_from_config
from .catalogs import _style_visual_prompt_block
from .generation_input_context import _generation_user_instruction
from .image_prompt_guidance import append_image_request_prompt_instruction
from .provider_models import validate_image_model_inputs
from .image_prompt_guidance import image_request_size_label
from .media_files import _decode_data_url
from .media_files import _extract_first_image_bytes
from .media_files import _save_project_image_media_file
from .media_files import _save_project_original_image_media_file
from .model_generation_contract import _project_ai_content_disclosure_metadata
from .model_provider_config import _api_model_name
from .model_provider_config import _configured_provider_for_model
from .model_provider_config import _get_effective_config
from .model_provider_config import _openai_compatible_generation_base_url
from .model_provider_config import _project_model_config
from .model_provider_config import _provider_base_url
from .model_request_logs import STAGE_STORYBOARD_IMAGE_GENERATION_PROMPT
from .model_request_logs import model_request_log_reference
from .model_request_logs import write_model_request_log
from .model_text_client import _post_json
from .production_specs import normalize_production_aspect_ratio, production_orientation
from .provider_models import _find_model
from .provider_models import _image_output_size
from .provider_models import _image_output_source_mime
from .provider_models import _image_resolution_options_for_aspect
from .provider_models import _is_connected_provider
from .provider_models import _model_generation_endpoint
from .provider_models import _model_reference_image_input_limits
from .provider_models import _normalize_resolution
from .provider_models import _provider_adapter_id
from .provider_models import _provider_service_id
from .provider_models import _provider_supports_direct_media_generation
from .provider_models import _resolve_image_output_format
from .provider_models import _storyboard_size_prompt_only_for_gpt_relay
from .provider_reference_media import _asset_refs_resolved_by_input_links_for_provider
from .provider_reference_media import _provider_reference_file_id_from_value
from .provider_reference_media import _provider_reference_image_from_media
from .provider_reference_media import _provider_reference_images_from_ids
from .provider_reference_media import _provider_reference_images_from_inline_files
from .provider_reference_media import _provider_reference_metadata
from .provider_reference_media import _provider_reference_prepare_kwargs
from .reference_utils import asset_reference_ids_from_generation_sources as _asset_reference_ids_from_generation_sources
from .reference_utils import merge_reference_ids as _merge_reference_ids
from .splitting_templates import _string_list
from .task_control import _check_generation_task_cancelled
from typing import Any
from utils.generation_requests import GenerationCancelled
from utils.generation_requests import run_cancellable_model_request
from utils.image_pipeline import prepare_provider_image_data_uri
from utils.image_resolution_schema import image_resolution_actual_report
from utils.image_resolution_schema import image_resolution_request_plan
from utils.image_resolution_schema import image_resolution_schema_for_model
from utils.image_resolution_schema import normalize_image_resolution_for_schema
from utils.image_resolution_schema import resolve_image_aspect_ratio_for_model
from utils.media_backends import generate_image_media
from utils.media_backends import image_prompt_char_limit
from utils.model_timeouts import MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS
import copy
import json
import math
import re
import uuid


def _append_generation_instruction(prompt: str, instruction: str) -> str:
    base = str(prompt or "").strip()
    note = str(instruction or "").strip()
    if not note:
        return base
    if note in base:
        return base
    if not base:
        return note
    return f"{base}\n\n用户本轮优化要求：{note}"


def _append_storyboard_generation_instruction(prompt: str, instruction: str) -> str:
    base = str(prompt or "").strip()
    note = str(instruction or "").strip()
    if not note:
        return base
    if note in base and "仅执行不改变分镜脚本" in base:
        return base
    guarded_note = (
        "【用户本轮优化要求】\n"
        "仅执行不改变分镜脚本的呈现偏好；不得改变镜头数量、顺序、构图、站位、关键动作、结尾画面、资产身份或故事事实。"
        "若该要求会改变上述内容，本次分镜图生成不得执行，应先更新分镜脚本。\n"
        f"{note}"
    )
    if note in base:
        return (
            f"{base}\n\n【用户本轮优化要求边界】\n"
            "仅执行不改变分镜脚本的呈现偏好；不得改变镜头数量、顺序、构图、站位、关键动作、结尾画面、资产身份或故事事实。"
            "若该要求会改变上述内容，本次分镜图生成不得执行，应先更新分镜脚本。"
        )
    if not base:
        return guarded_note
    return f"{base}\n\n{guarded_note}"


def _append_image_request_prompt_instruction(
    prompt: str,
    size: Any,
    orientation: str = "landscape",
) -> str:
    base = str(prompt or "").strip()
    return append_image_request_prompt_instruction(base, size, orientation)


def _append_image_edit_reference_role_instruction(prompt: str, extra_reference_count: int) -> str:
    base = str(prompt or "").strip()
    if extra_reference_count <= 0 or not base or _IMAGE_EDIT_EXTRA_REFERENCE_ROLE_INSTRUCTION in base:
        return base
    return f"{base}\n\n{_IMAGE_EDIT_EXTRA_REFERENCE_ROLE_INSTRUCTION}"


def _append_image_edit_base_preservation_instruction(prompt: str) -> str:
    base = str(prompt or "").strip()
    if not base or _IMAGE_EDIT_BASE_PRESERVATION_INSTRUCTION in base or "【必须保持】" in base:
        return base
    return f"{base}\n\n{_IMAGE_EDIT_BASE_PRESERVATION_INSTRUCTION}"


def _provider_generated_image_file_id_from_debug(debug: dict[str, Any] | None) -> str:
    if not isinstance(debug, dict):
        return ""
    response = debug.get("response")
    if isinstance(response, dict):
        return _provider_reference_file_id_from_value(response)
    return ""


def _call_openai_compatible_image_generation(
    provider: dict[str, Any],
    provider_id: str,
    base_url: str,
    model_name: str,
    prompt: str,
    *,
    size: str,
    reference_image: dict[str, Any] | None = None,
    output_format: str | None = None,
    image_input_limits: dict[str, Any] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    api_key = str(provider.get("api_key") or provider.get("apiKey") or "").strip()
    generation_base_url = _openai_compatible_generation_base_url(provider, provider_id, base_url)
    payload = {
        "model": model_name,
        "prompt": prompt,
        "n": 1,
        "size": size,
    }
    if output_format:
        payload["output_format"] = "jpeg" if output_format == "jpg" else output_format
    reference_data_url = str((reference_image or {}).get("dataUrl") or "").strip()
    if reference_data_url:
        raw_reference, _reference_mime = _decode_data_url(reference_data_url)
        prepare_kwargs = _provider_reference_prepare_kwargs(image_input_limits)
        prepare_kwargs.setdefault("max_long_edge", 0)
        reference_data_url = prepare_provider_image_data_uri(
            raw_reference,
            purpose="legacy-openai-compatible-image-reference",
            preserve_alpha=True,
            **prepare_kwargs,
        )
        _prepared_raw, prepared_mime = _decode_data_url(reference_data_url)
        payload["input_reference"] = reference_data_url
        payload["input_reference_mime"] = prepared_mime or "image/jpeg"

    legacy_response_format_allowed = provider_id == "dashscope" or (
        _provider_adapter_id(provider) == "openai-compatible"
        and _provider_service_id(provider) != "openai"
    )
    attempt_payloads: list[dict[str, Any]] = [payload]
    legacy_payload: dict[str, Any] | None = None
    if legacy_response_format_allowed:
        legacy_payload = {**payload, "response_format": "b64_json"}
        attempt_payloads.append(legacy_payload)

    unique_attempts: list[dict[str, Any]] = []
    seen_payloads: set[str] = set()
    for item in attempt_payloads:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
        if key not in seen_payloads:
            unique_attempts.append(item)
            seen_payloads.add(key)

    data: Any = None
    raw: bytes | None = None
    used_payload = payload
    fallback_errors: list[str] = []
    endpoint = f"{generation_base_url}/images/generations"
    for index, item in enumerate(unique_attempts):
        try:
            data = _post_json(endpoint, item, api_key, timeout=MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
            raw = _extract_first_image_bytes(data)
            if raw:
                used_payload = item
                break
            fallback_errors.append("图片模型未返回可用图片数据")
        except Exception as exc:
            fallback_errors.append(str(exc))
        if index == len(unique_attempts) - 1:
            break
    if raw is None:
        detail = fallback_errors[-1] if fallback_errors else "图片模型未返回可用图片数据"
        raise RuntimeError(detail)

    debug_request = {**used_payload, "prompt": prompt[:1200]}
    if debug_request.get("input_reference"):
        debug_request["input_reference"] = "data:image/*;base64,<redacted>"
    debug = {"response": data, "request": debug_request}
    if fallback_errors and used_payload is not payload:
        debug["imageGenerationFallbackErrors"] = fallback_errors
    return raw, debug








def _storyboard_image_generation_error(
    message: str,
    payload: dict[str, Any] | None = None,
    debug: dict[str, Any] | None = None,
) -> RuntimeError:
    error = RuntimeError(message)
    if isinstance(payload, dict):
        setattr(error, "payload", copy.deepcopy(payload))
    if isinstance(debug, dict):
        setattr(error, "debug", copy.deepcopy(debug))
    return error


def _append_storyboard_image_phase_visual_prompt(prompt: Any, phase_prompt: Any) -> str:
    text = str(prompt or "").strip()
    phase_block = _append_style_phase_visual_prompt("", phase_prompt)
    if not phase_block:
        return text
    phase = phase_block.split("\n", 1)[1].strip() if "\n" in phase_block else phase_block
    if phase_block in text or (phase and phase in text):
        return text
    visual_marker = "【视觉风格提示词】"
    following_markers = ("【稳定世界观背景】", "【画面标注与清洁约束】", "【画面清洁约束】", "【生成指令】")
    if visual_marker in text:
        start = text.index(visual_marker)
        insert_candidates = [
            text.index(marker, start)
            for marker in following_markers
            if marker in text[start:]
        ]
        if insert_candidates:
            insert_at = min(insert_candidates)
            return f"{text[:insert_at].rstrip()}\n\n{phase_block}\n\n{text[insert_at:].lstrip()}"
    return f"{text}\n\n{phase_block}" if text else phase_block


def _storyboard_visual_block_content(block: Any) -> str:
    text = str(block or "").strip()
    if not text:
        return ""
    if "\n" in text and re.match(r"^\s*【[^】]+】", text):
        return text.split("\n", 1)[1].strip()
    return text


def _storyboard_project_visual_supplement_prompt(
    base_prompt: Any,
    theme_prompt: Any,
    visual_prompt: Any,
    phase_prompt: Any,
    *,
    is_visual_handoff_image: bool = False,
) -> str:
    base = str(base_prompt or "")
    rows: list[str] = []
    for label, block in (
        ("主题视觉", _style_theme_visual_prompt_block(theme_prompt)),
        ("全局视觉", _style_visual_prompt_block(visual_prompt, "全局视觉")),
        ("阶段视觉", _style_phase_visual_prompt_block(phase_prompt)),
    ):
        content = _storyboard_visual_block_content(block)
        if not content or content in base:
            continue
        row = f"{label}：{content}"
        if row not in rows:
            rows.append(row)
    if not rows:
        return ""
    boundary = (
        "不得覆盖本段剧情事实、用户要求、空间连续性交接图任务，或改变已绑定图片资产的身份、外观、材质和空间关系。"
        if is_visual_handoff_image
        else "不得改写分镜脚本、用户要求或分镜图版式规则，或改变已绑定图片资产的身份、外观、材质和空间关系。"
    )
    return (
        "【项目视觉补充】\n"
        "如有已绑定角色、生物、场景、道具图片资产和本次参考图，它们是视觉主依据；以下内容只补足参考图未覆盖的时代地域、统一质感、阶段氛围和环境状态，"
        f"{boundary}\n"
        + "\n".join(rows)
    )


def _insert_storyboard_section_before_prompt_contract(prompt: Any, section: Any) -> str:
    base = str(prompt or "").strip()
    block = str(section or "").strip()
    if not block:
        return base
    marker = block.splitlines()[0].strip() if block.splitlines() else ""
    if marker and marker in base:
        return base
    insert_before_markers = (
        "【项目视觉补充】",
        "【分镜图版式规则】",
        "【故事版模板规则】",
        "【故事版模板延续规则】",
        "【单镜头版式延续规则】",
        "【故事版模板】",
        "【单面板适配】",
        "【画布与输出规格】",
        "【故事版画布与视频画框规格】",
        "【故事版画布规格】",
        "【实际输出规格】",
        "【画面标注与清洁约束】",
        "【画面清洁约束】",
        "【生成指令】",
    )
    indexes = [base.index(item) for item in insert_before_markers if item in base]
    if indexes:
        insert_at = min(indexes)
        return f"{base[:insert_at].rstrip()}\n\n{block}\n\n{base[insert_at:].lstrip()}"
    return f"{base.rstrip()}\n\n{block}" if base else block


def _insert_storyboard_project_visual_supplement_prompt(
    prompt: Any,
    theme_prompt: Any,
    visual_prompt: Any,
    phase_prompt: Any,
    *,
    is_visual_handoff_image: bool = False,
) -> str:
    base = str(prompt or "").strip()
    if "【项目视觉补充】" in base:
        return base
    supplement = _storyboard_project_visual_supplement_prompt(
        base,
        theme_prompt,
        visual_prompt,
        phase_prompt,
        is_visual_handoff_image=is_visual_handoff_image,
    )
    return _insert_storyboard_section_before_prompt_contract(base, supplement)


def _storyboard_actual_output_spec_prompt(
    orientation_label: Any,
    aspect_ratio: Any,
    target_width: Any,
    target_height: Any,
) -> str:
    orientation = str(orientation_label or "").strip()
    ratio = str(aspect_ratio or "").strip()
    try:
        width = int(target_width)
        height = int(target_height)
    except (TypeError, ValueError):
        width = 0
        height = 0
    if not orientation or not ratio or width <= 0 or height <= 0:
        return ""
    if width > height:
        frame_guard = "画面宽度必须大于高度；禁止竖版海报、手机竖屏比例或正方形构图。"
    elif height > width:
        frame_guard = "画面高度必须大于宽度；禁止横向宽幅或正方形构图。"
    else:
        frame_guard = "画布宽高必须近似相等；禁止明显横向或竖向长幅构图。"
    return (
        f"本次实际输出：{orientation} {ratio}，目标尺寸 {width}x{height}；{frame_guard}"
        "若版式参考画布或版式规则中出现其他尺寸，只按比例理解，必须以本次实际输出尺寸为准。"
    )


def _insert_storyboard_actual_output_spec_prompt(prompt: Any, spec_prompt: Any) -> str:
    base = str(prompt or "").strip()
    block = str(spec_prompt or "").strip()
    if not block or block in base or "本次实际输出：" in base:
        return base
    for marker in ("【画布与输出规格】", "【故事版画布与视频画框规格】"):
        if marker in base:
            insert_at = base.index(marker) + len(marker)
            return f"{base[:insert_at]}\n{block}{base[insert_at:]}"
    section = f"【画布与输出规格】\n{block}"
    insert_before_markers = ("【画面标注与清洁约束】", "【画面清洁约束】", "【生成指令】")
    indexes = [base.index(marker) for marker in insert_before_markers if marker in base]
    if indexes:
        insert_at = min(indexes)
        return f"{base[:insert_at].rstrip()}\n\n{section}\n\n{base[insert_at:].lstrip()}"
    return f"{base.rstrip()}\n\n{section}" if base else section


class _StoryboardImageGeneration:
    """一次图片生成持有自己的请求数据；各阶段按准备、执行、保存顺序运行。"""

    def __init__(self, project_id: str, episode_id: str, title: str, payload: dict[str, Any], workflow_projection: dict[str, Any] | None):
        self.project_id = project_id
        self.episode_id = episode_id
        self.title = title
        self.payload = payload
        self.workflow_projection = workflow_projection

    def check_image_task_cancelled(self) -> None:
        _check_generation_task_cancelled(str(self.payload.get("taskId") or "").strip())

    def _prepare_model(self) -> None:
        global_config, capabilities, model_config = _project_model_config(self.project_id)
        self.image_config = model_config.get("image", {}) if isinstance(model_config.get("image"), dict) else {}
        self.resolved_config = self.payload.get("resolvedConfig") if isinstance(self.payload.get("resolvedConfig"), dict) else {}
        model_id = str(
            self.resolved_config.get("modelId")
            or self.resolved_config.get("model_id")
            or self.image_config.get("model_id")
            or ""
        ).strip()
        self.model = _find_model(model_id, "image", capabilities) if model_id else None
        self.provider = _configured_provider_for_model(self.model, global_config.get("providers", []))
        if not self.provider or not self.model or not _is_connected_provider(self.provider):
            raise RuntimeError("图片模型供应商未连接")
        self.base_url = _provider_base_url(self.provider)
        if not self.base_url:
            raise RuntimeError("图片供应商 Base URL 为空")
        self.provider_id = _provider_service_id(self.provider)
        self.model_name = _api_model_name(self.model.get("id"))
        self.project_config = _get_effective_config(self.project_id)
        self.prompt = str(self.payload.get("storyboardImagePrompt") or self.title or "").strip()
        self.theme_visual_prompt = _style_theme_visual_prompt_from_config(self.project_config)
        self.phase_visual_prompt = _style_phase_visual_prompt_from_config(self.project_config)
        requested_image_mode = str(
            self.payload.get("imageGenerationMode") or self.payload.get("image_generation_mode") or ""
        ).strip().lower()
        image_operation = str(self.payload.get("imageOperation") or self.payload.get("image_operation") or "").strip().lower()
        self.requested_image_edit = requested_image_mode == "image_edit" or image_operation == "edit"
        self.is_visual_handoff_image = str(
            self.payload.get("generationStage") or self.payload.get("generation_stage") or ""
        ).strip() == "visual_handoff_image"
        self.is_storyboard_image = not self.is_visual_handoff_image and self.payload.get("assetType") != "custom_image" and str(
            self.payload.get("generationStage") or ""
        ) not in {"canvas_asset_image_generation", "canvas_image_direct"}
        validate_image_model_inputs(self.model, image_edit=self.requested_image_edit)
        storyboard_visual_prompt = (
            self.project_config.get("style", {}).get("prompt")
            if isinstance(self.project_config.get("style"), dict)
            else ""
        )
        # Edits inherit appearance from the original; asset templates already include project style.
        if self.payload.get("assetType") == "custom_image":
            if self.payload.get("useProjectVisual") is True:
                visual_blocks = [
                    _style_theme_visual_prompt_block(self.theme_visual_prompt),
                    _style_visual_prompt_block(storyboard_visual_prompt, "视觉风格"),
                ]
                self.prompt = "\n\n".join([self.prompt, *[block for block in visual_blocks if block]])
            self.theme_visual_prompt = ""
            self.phase_visual_prompt = ""
        elif self.requested_image_edit or self.payload.get("generationStage") in {"canvas_asset_image_generation", "canvas_image_direct"}:
            self.theme_visual_prompt = ""
            self.phase_visual_prompt = ""
        else:
            self.prompt = _insert_storyboard_project_visual_supplement_prompt(
                self.prompt,
                self.theme_visual_prompt,
                storyboard_visual_prompt,
                self.phase_visual_prompt,
                is_visual_handoff_image=self.is_visual_handoff_image,
            )
        self.layout_spec = (
            self.payload.get("storyboardTemplateLayoutSpec")
            if isinstance(self.payload.get("storyboardTemplateLayoutSpec"), dict)
            else {}
        )
        self.storyboard_render_spec = (
            self.payload.get("storyboardRenderSpec")
            if isinstance(self.payload.get("storyboardRenderSpec"), dict)
            else {}
        )
        self.sheet_spec = (
            self.storyboard_render_spec.get("sheet")
            if isinstance(self.storyboard_render_spec.get("sheet"), dict)
            else {}
        )
        self.desired_storyboard_aspect_ratio = str(
            self.sheet_spec.get("aspectRatio")
            or self.layout_spec.get("sheetAspectRatio")
            or self.layout_spec.get("aspectRatio")
            or "16:9"
        ).strip() or "16:9"
        self.storyboard_aspect_ratio = self.desired_storyboard_aspect_ratio
        self.storyboard_resolution = (
            self.resolved_config.get("resolution")
            or self.resolved_config.get("size")
            or self.image_config.get("storyboard_resolution")
            or self.layout_spec.get("defaultResolution")
            or "2K"
        )
        self.storyboard_resolution = _normalize_resolution(
            self.storyboard_resolution,
            _image_resolution_options_for_aspect(
                _string_list(self.model.get("resolutions")),
                self.storyboard_aspect_ratio,
                self.model,
            ),
            str(self.model.get("default_resolution") or self.image_config.get("storyboard_resolution") or "2K"),
        )
        self.endpoint = _model_generation_endpoint(self.provider, self.model)
        if not _provider_supports_direct_media_generation(self.provider, "image", self.model):
            raise RuntimeError(f"当前图片供应商 {self.provider_id or 'unknown'} 暂未接入 ai-video 直接出图适配")
        self.output_format = _resolve_image_output_format(
            {
                **self.image_config,
                "image_output_format": (
                    self.resolved_config.get("outputFormat")
                    or self.resolved_config.get("output_format")
                    or self.image_config.get("image_output_format")
                ),
            },
            self.model,
        )
        self.image_input_limits = _model_reference_image_input_limits(self.model)

    def _prepare_references(self) -> None:
        self.asset_refs_resolved_by_links = _asset_refs_resolved_by_input_links_for_provider(self.payload, self.resolved_config)
        self.base_reference_ids: list[str] = []
        self.reference_ids: list[str] = []
        self.base_reference_images: list[dict[str, Any]] = []
        self.asset_reference_images: list[dict[str, Any]] = []
        if self.requested_image_edit:
            self.base_reference_ids = _merge_reference_ids(
                self.payload.get("baseReferenceMediaIds"),
                self.payload.get("base_reference_media_ids"),
                self.payload.get("baseVersionId"),
                self.payload.get("base_version_id"),
            )
            base_reference_media = (
                self.payload.get("baseReferenceMedia")
                if isinstance(self.payload.get("baseReferenceMedia"), dict)
                else self.payload.get("base_reference_media")
                if isinstance(self.payload.get("base_reference_media"), dict)
                else None
            )
            base_reference_image_payload = (
                self.payload.get("baseReferenceImage")
                if isinstance(self.payload.get("baseReferenceImage"), dict)
                else self.payload.get("base_reference_image")
                if isinstance(self.payload.get("base_reference_image"), dict)
                else None
            )
            if self.base_reference_ids and len(self.base_reference_ids) != 1:
                raise RuntimeError("图片编辑必须明确指定唯一原图")
            if self.base_reference_ids and not isinstance(base_reference_media, dict):
                self.base_reference_images = _provider_reference_images_from_ids(
                    self.project_id,
                    self.episode_id,
                    self.base_reference_ids,
                    purpose="storyboard-image-edit-base",
                    image_input_limits=self.image_input_limits,
                    require_all=True,
                    required_reference_label="图片编辑原图",
                    resolution_workflow=self.workflow_projection,
                )
            elif isinstance(base_reference_media, dict):
                base_reference = _provider_reference_image_from_media(
                    self.project_id,
                    base_reference_media,
                    purpose="storyboard-image-edit-base",
                    image_input_limits=self.image_input_limits,
                )
                if base_reference:
                    base_reference["source"] = "payload_media"
                    base_reference["mediaId"] = base_reference_media.get("id")
                    self.base_reference_images = [base_reference]
            elif isinstance(base_reference_image_payload, dict) and (
                base_reference_image_payload.get("dataUrl")
                or base_reference_image_payload.get("data_url")
                or base_reference_image_payload.get("providerFileId")
                or base_reference_image_payload.get("provider_file_id")
            ):
                self.base_reference_images = [copy.deepcopy(base_reference_image_payload)]
            if not self.base_reference_images:
                raise RuntimeError("未能解析当前图片原图，无法发起图片编辑")
            self.base_reference_images = [copy.deepcopy(self.base_reference_images[0])]
            self.base_reference_images[0]["role"] = "edit_base"
            self.base_reference_images[0]["referenceRole"] = "edit_base"
            self.base_reference_images[0]["isEditBaseImage"] = True
            panel_edit = self.payload.get("storyboardPanelEdit")
            if isinstance(panel_edit, dict):
                panel_index = panel_edit.get("panelIndex")
                if isinstance(panel_index, int) and panel_index > 0:
                    self.prompt = f"{self.prompt}\n\n仅修改第 {panel_index} 个正式镜头画格，保留其他镜头和辅助区域；以提供的整张原始分镜图为编辑基准。"
            self.reference_ids = _merge_reference_ids(
                self.payload.get("referenceMediaIds"),
                self.payload.get("reference_media_ids"),
            )
            self.asset_reference_images = _provider_reference_images_from_ids(
                self.project_id,
                self.episode_id,
                self.reference_ids,
                purpose="storyboard-image-edit-reference",
                image_input_limits=self.image_input_limits,
                require_all=True,
                required_reference_label="图片编辑参考图",
                resolution_workflow=self.workflow_projection,
                allow_asset_library_lookup=not self.asset_refs_resolved_by_links,
            )
            for reference in self.asset_reference_images:
                reference["role"] = "edit_reference"
                reference["referenceRole"] = "edit_reference"
        else:
            reference_sources: list[Any] = [
                self.payload.get("referenceMediaIds"),
                self.payload.get("reference_media_ids"),
            ]
            if not self.asset_refs_resolved_by_links and self.payload.get("generationStage") != "canvas_image_direct":
                reference_sources.extend(
                    [
                        self.resolved_config.get("referenceMediaIds"),
                        _asset_reference_ids_from_generation_sources(self.payload, self.resolved_config),
                    ]
                )
            self.reference_ids = _merge_reference_ids(*reference_sources)
            excluded_ids = set(self.payload.get("storyboardExcludedReferenceIds") or [])
            if excluded_ids and isinstance(self.payload.get("panels"), list):
                self.reference_ids = [value for value in self.reference_ids if value not in excluded_ids]
            self.asset_reference_images = _provider_reference_images_from_ids(
                self.project_id,
                self.episode_id,
                self.reference_ids,
                purpose="storyboard-image-reference",
                image_input_limits=self.image_input_limits,
                require_all=True,
                required_reference_label="图片生成参考图",
                resolution_workflow=self.workflow_projection,
                allow_asset_library_lookup=not self.asset_refs_resolved_by_links,
            )
        inline_reference_files: list[Any] = []
        for key in (
            "referenceFiles",
            "reference_files",
            "inlineReferenceImages",
            "inline_reference_images",
            "editReferenceFiles",
            "edit_reference_files",
        ):
            value = self.payload.get(key)
            if isinstance(value, list):
                inline_reference_files.extend(value)
            elif isinstance(value, dict):
                inline_reference_files.append(value)
        self.inline_reference_images = _provider_reference_images_from_inline_files(
            self.project_id,
            inline_reference_files,
            purpose="storyboard-image-edit-inline-reference" if self.requested_image_edit else "storyboard-image-inline-reference",
            image_input_limits=self.image_input_limits,
            require_all=True,
        )
        if self.requested_image_edit:
            for reference in self.inline_reference_images:
                reference["role"] = "edit_reference"
                reference["referenceRole"] = "edit_reference"
        if self.reference_ids and not self.asset_reference_images:
            raise RuntimeError("分镜图生成任务已链接参考资产，但未能解析为可发送给图片模型的参考图，请检查资产版本。")
        if not self.requested_image_edit and isinstance(self.payload.get("panels"), list):
            from .storyboard_reference_scope import scope_storyboard_reference_images
            manifest = self.payload.get("referenceManifest") if isinstance(self.payload.get("referenceManifest"), list) else []
            excluded = self.payload.get("storyboardExcludedReferenceIds") or []
            self.asset_reference_images = scope_storyboard_reference_images(
                self.payload["panels"], manifest, excluded, self.asset_reference_images,
            )
            self.inline_reference_images = scope_storyboard_reference_images(
                self.payload["panels"], manifest, excluded, self.inline_reference_images,
            )
        self.reference_images = [*self.base_reference_images, *self.asset_reference_images, *self.inline_reference_images]
        self.edit_extra_reference_count = len(self.asset_reference_images) + len(self.inline_reference_images)
        self.suppressed_reference_images: list[dict[str, Any]] = []
        self.max_reference_images = validate_image_model_inputs(
            self.model, image_edit=self.requested_image_edit, reference_count=len(self.reference_images),
        )

    def _prepare_request(self) -> None:
        prompt_only_gpt = self.is_storyboard_image and _storyboard_size_prompt_only_for_gpt_relay(
            self.model,
            provider_id=self.provider_id,
            adapter_id=_provider_adapter_id(self.provider),
        )
        resolution_schema = image_resolution_schema_for_model(self.model)
        allowed_aspects = resolution_schema.get("aspect_ratios")
        if self.is_storyboard_image and isinstance(allowed_aspects, list) and allowed_aspects:
            desired_width, desired_height = (int(part) for part in self.desired_storyboard_aspect_ratio.split(":"))
            desired_ratio = desired_width / desired_height
            candidates: list[tuple[float, str]] = []
            for option in allowed_aspects:
                try:
                    candidate_width, candidate_height = (int(part) for part in str(option).split(":"))
                    if candidate_width > 0 and candidate_height > 0:
                        candidates.append((abs(math.log((candidate_width / candidate_height) / desired_ratio)), str(option)))
                except (TypeError, ValueError):
                    continue
            self.storyboard_aspect_ratio = min(candidates)[1] if candidates else self.desired_storyboard_aspect_ratio
        elif self.is_storyboard_image and resolution_schema.get("size_mode") == "explicit_pixels":
            # Fixed-size catalogs choose their nearest legal preset to the sheet plan.
            self.storyboard_aspect_ratio = self.desired_storyboard_aspect_ratio
        else:
            self.storyboard_aspect_ratio = resolve_image_aspect_ratio_for_model(
                self.model,
                self.desired_storyboard_aspect_ratio,
                fallback_aspect_ratio="16:9",
                options=_string_list(self.model.get("resolutions")),
                has_reference_images=bool(self.reference_images),
            )
        self.storyboard_sheet_orientation, self.storyboard_sheet_orientation_label = production_orientation(
            self.storyboard_aspect_ratio
        )
        self.storyboard_resolution = normalize_image_resolution_for_schema(
            self.storyboard_resolution,
            _string_list(self.model.get("resolutions")),
            str(self.model.get("default_resolution") or self.image_config.get("storyboard_resolution") or "2K"),
            resolution_schema,
            self.storyboard_aspect_ratio,
            has_reference_images=bool(self.reference_images),
        )
        if self.is_storyboard_image and resolution_schema.get("size_mode") == "explicit_pixels":
            manually_selected = str(self.resolved_config.get("size") or self.resolved_config.get("resolution") or "").strip()
            supported_presets = _string_list(self.model.get("resolutions"))
            self.storyboard_resolution = next(
                (preset for preset in supported_presets if preset.casefold() == manually_selected.casefold()),
                self.storyboard_resolution,
            )
        self.size = _image_output_size(
            self.model,
            self.storyboard_resolution,
            self.storyboard_aspect_ratio,
            has_reference_images=bool(self.reference_images),
        )
        self.request_plan = image_resolution_request_plan(
            self.model,
            self.storyboard_resolution,
            self.storyboard_aspect_ratio,
            size=self.size,
            has_reference_images=bool(self.reference_images),
        )
        if self.is_storyboard_image and self.provider_id == "ark-seedance" and "seedream" in self.model_name.lower():
            schema = image_resolution_schema_for_model(self.model)
            tiers = [str(value).upper() for value in schema.get("native_tiers", [])]
            if tiers:
                requested_tier = str(self.storyboard_resolution or "").upper()
                self.storyboard_resolution = requested_tier if requested_tier in tiers else tiers[0]
                self.size = self.storyboard_resolution.lower()
                self.request_plan = image_resolution_request_plan(
                    self.model, self.storyboard_resolution, self.storyboard_aspect_ratio,
                    size=self.size, has_reference_images=bool(self.reference_images),
                )
        if prompt_only_gpt:
            self.storyboard_aspect_ratio = self.desired_storyboard_aspect_ratio
            self.storyboard_sheet_orientation, self.storyboard_sheet_orientation_label = production_orientation(
                self.storyboard_aspect_ratio
            )
            self.storyboard_resolution = ""
            self.size = "auto"
            self.resolved_config = {
                key: value for key, value in self.resolved_config.items()
                if key not in {"resolution", "size", "storyboardResolution", "storyboard_resolution"}
            }
            if "resolvedConfig" in self.payload:
                self.payload = {**self.payload, "resolvedConfig": self.resolved_config}
            if "imageSize" in self.payload:
                self.payload = {**self.payload, "imageSize": ""}
            self.sheet_spec = {
                **self.sheet_spec, "resolution": "model_determined",
                "targetWidth": None, "targetHeight": None,
            }
            self.storyboard_render_spec = {**self.storyboard_render_spec, "sheet": self.sheet_spec}
            self.payload = {**self.payload, "storyboardRenderSpec": self.storyboard_render_spec}
            self.request_plan = {
                "controlMode": "prompt_only", "effectiveSizeControl": False,
                "parameter": "size", "requestValue": "auto", "requestedSize": "auto",
                "requestedWidth": None, "requestedHeight": None, "exactPixelRequest": False,
                "aspectRatio": self.storyboard_aspect_ratio,
                "outputPreservation": "provider_original_bytes",
            }
        elif self.is_storyboard_image:
            self.request_plan["outputPreservation"] = "provider_original_bytes"
            self.sheet_spec = {
                **self.sheet_spec,
                "resolution": str(self.storyboard_resolution or "model_determined"),
            }
            requested_dimensions = _parse_image_size_text(self.size)
            if requested_dimensions:
                requested_aspect_ratio = normalize_production_aspect_ratio(
                    f"{requested_dimensions[0]}:{requested_dimensions[1]}"
                )
                self.storyboard_aspect_ratio = requested_aspect_ratio
                self.storyboard_sheet_orientation, self.storyboard_sheet_orientation_label = production_orientation(
                    requested_aspect_ratio
                )
                self.request_plan["plannedAspectRatio"] = self.desired_storyboard_aspect_ratio
                self.request_plan["aspectRatio"] = requested_aspect_ratio
                self.sheet_spec.update(
                    targetWidth=requested_dimensions[0],
                    targetHeight=requested_dimensions[1],
                    requestedAspectRatio=requested_aspect_ratio,
                    resolvedResolution=str(self.storyboard_resolution or ""),
                    resolvedSize=self.size,
                )
            elif self.request_plan.get("sizeMode") == "native_tier":
                self.sheet_spec.update(targetWidth=None, targetHeight=None)
            self.storyboard_render_spec = {**self.storyboard_render_spec, "sheet": self.sheet_spec}
            self.payload = {**self.payload, "storyboardRenderSpec": self.storyboard_render_spec}
        request_size_label = image_request_size_label(self.request_plan, self.size, self.storyboard_resolution)
        if prompt_only_gpt or (self.is_storyboard_image and request_size_label.casefold() == "auto"):
            request_size_label = ""
        actual_output_spec_prompt = ""
        if not self.requested_image_edit and _storyboard_prompt_is_full_sheet(self.payload):
            parsed_size = _parse_image_size_text(self.size)
            if parsed_size:
                target_width, target_height = parsed_size
                self.storyboard_aspect_ratio = normalize_production_aspect_ratio(
                    f"{target_width}:{target_height}"
                )
                self.storyboard_sheet_orientation, self.storyboard_sheet_orientation_label = production_orientation(
                    self.storyboard_aspect_ratio
                )
                self.request_plan["plannedAspectRatio"] = self.desired_storyboard_aspect_ratio
                self.request_plan["aspectRatio"] = self.storyboard_aspect_ratio
                self.layout_spec = {
                    **self.layout_spec,
                    "targetWidth": target_width,
                    "targetHeight": target_height,
                    "resolvedResolution": str(self.storyboard_resolution or ""),
                    "resolvedSize": self.size,
                }
                self.sheet_spec = {
                    **self.sheet_spec,
                    "targetWidth": target_width,
                    "targetHeight": target_height,
                    "resolvedResolution": str(self.storyboard_resolution or ""),
                    "resolvedSize": self.size,
                }
                self.storyboard_render_spec = {
                    **self.storyboard_render_spec,
                    "sheet": self.sheet_spec,
                }
                self.payload = {
                    **self.payload,
                    "storyboardTemplateLayoutSpec": self.layout_spec,
                    "storyboardRenderSpec": self.storyboard_render_spec,
                }
                actual_output_spec_prompt = _storyboard_actual_output_spec_prompt(
                    self.storyboard_sheet_orientation_label,
                    self.storyboard_aspect_ratio,
                    target_width,
                    target_height,
                )
        if not self.requested_image_edit and self.payload.get("generationStage") not in {
            "canvas_storyboard_generation", "canvas_asset_image_generation", "canvas_image_direct",
        }:
            reference_lock = _storyboard_reference_consistency_prompt(
                self.reference_images,
                is_visual_handoff_image=self.is_visual_handoff_image,
            )
            if reference_lock and reference_lock not in self.prompt:
                self.prompt = _insert_storyboard_section_before_prompt_contract(self.prompt, reference_lock)
            self.prompt = _append_storyboard_generation_instruction(self.prompt, _generation_user_instruction(self.payload))
        self.selected_reference = _storyboard_transport_reference_image(self.reference_images)
        self.image_generation_mode = (
            "image_edit"
            if self.requested_image_edit
            else "image_to_image"
            if self.reference_images
            else "text_to_image"
        )
        if self.requested_image_edit:
            image_safety_flow = {
                "mode": "direct",
                "stage": "image_edit",
                "policy": "direct_image_edit_prompt",
                "reason": "image_edit_uses_current_instruction_and_selected_references",
            }
            current_prompt = self.prompt
            self.prompt = _append_image_request_prompt_instruction(
                self.prompt,
                request_size_label,
                self.storyboard_sheet_orientation,
            )
            self.prompt = _append_image_edit_reference_role_instruction(self.prompt, self.edit_extra_reference_count)
            if self.payload.get("assetType") == "custom_image":
                self.prompt += "\n\n图片编辑任务：只修改输入原图。依据本次要求调整图片，保留未要求改变的内容。"
                if self.payload.get("useProjectVisual") is True:
                    self.prompt += "本次启用了项目视觉，按提供的主题视觉和视觉风格调整原图的视觉表现。"
            else:
                self.prompt = _append_image_edit_base_preservation_instruction(self.prompt)
        else:
            if self.payload.get("generationStage") in {"canvas_storyboard_generation", "canvas_asset_image_generation", "canvas_image_direct"}:
                image_safety_flow = {
                    "mode": "direct",
                    "stage": "preflight",
                    "policy": "canvas_image_direct_prompt",
                    "reason": "canvas_image_uses_current_instruction_and_explicit_references",
                }
            elif self.is_visual_handoff_image:
                image_safety_flow = {
                    "mode": "direct",
                    "stage": "preflight",
                    "policy": "visual_handoff_direct_prompt",
                    "reason": (
                        "visual_handoff_uses_cinematic_script_visual_beats_and_generated_storyboard_reference"
                    ),
                }
            else:
                image_safety_flow = {
                    "mode": "director_plan_first",
                    "stage": "direct_first_attempt",
                    "policy": "director_plan_revision_on_provider_safety_failure",
                    "reason": "storyboard_image_prompt_must_follow_director_plan_without_visual_prompt_rewrite",
                }
            self.prompt = _insert_storyboard_actual_output_spec_prompt(self.prompt, actual_output_spec_prompt)
            current_prompt = self.prompt
            if not actual_output_spec_prompt:
                self.prompt = _append_image_request_prompt_instruction(
                    self.prompt,
                    request_size_label,
                    self.storyboard_sheet_orientation,
                )
        self.image_prompt_limit = image_prompt_char_limit(self.provider_id, self.model_name)
        image_prompt_budget = {
            "limit": self.image_prompt_limit,
            "originalPromptChars": len(self.prompt),
            "finalPromptChars": len(self.prompt),
            "compacted": False,
            "actualOutputSpecIncluded": bool(actual_output_spec_prompt and "本次实际输出：" in self.prompt),
        }
        if self.image_prompt_limit > 0 and len(self.prompt) > self.image_prompt_limit:
            raise RuntimeError(
                f"分镜图提示词超过当前图片模型上限 {self.image_prompt_limit} 字符，已停止生成；"
                "不能在发送前截断剧本事实、故事版合同或资产绑定"
            )
        payload_update = {
            **self.payload,
            "storyboardImagePrompt": self.prompt,
            "providerPromptSent": self.prompt,
            "storyboardImageSafetyFlow": image_safety_flow,
            "promptBudget": image_prompt_budget,
        }
        if self.theme_visual_prompt:
            payload_update["themeVisualPrompt"] = self.theme_visual_prompt
            payload_update["theme_visual_prompt"] = self.theme_visual_prompt
        if self.phase_visual_prompt:
            payload_update["phaseVisualPrompt"] = self.phase_visual_prompt
            payload_update["phase_visual_prompt"] = self.phase_visual_prompt
        if actual_output_spec_prompt:
            payload_update["actualOutputSpecPrompt"] = actual_output_spec_prompt
            payload_update["actual_output_spec_prompt"] = actual_output_spec_prompt
        if self.requested_image_edit:
            payload_update["imageEditPromptAssembly"] = {
                "policy": image_safety_flow.get("policy"),
                "mode": self.payload.get("imageEditMode") or "manual",
                "currentEditPrompt": str(self.payload.get("finalEditPrompt") or self.payload.get("userInstruction") or ""),
                "extraReferenceCount": self.edit_extra_reference_count,
                "baseReferenceMediaIds": self.base_reference_ids,
                "referenceRoleInstructionApplied": self.edit_extra_reference_count > 0,
                "basePreservationInstructionApplied": True,
            }
        else:
            payload_update["currentPrompt"] = current_prompt
            payload_update["currentVisualPrompt"] = current_prompt
        self.payload = payload_update

    def _generate(self) -> None:
        from .source_text_store import _compact_text

        log_node_id = str(
            self.payload.get("nodeId")
            or self.payload.get("node_id")
            or self.payload.get("generationTaskNodeId")
            or self.payload.get("generation_task_node_id")
            or self.payload.get("resultNodeId")
            or self.payload.get("result_node_id")
            or ""
        ).strip()
        log_phase = str(
            self.payload.get("generationStage")
            or self.payload.get("generation_stage")
            or ("storyboard-image-edit" if self.requested_image_edit else "storyboard-image")
        ).strip()
        self.model_request_log_errors: list[dict[str, Any]] = []
        self.model_request_logs: list[dict[str, Any]] = []
        def log_storyboard_image_request(request_info: dict[str, Any]) -> None:
            result = write_model_request_log(
                self.project_id,
                STAGE_STORYBOARD_IMAGE_GENERATION_PROMPT,
                request_info,
                episode_id=self.episode_id,
                node_id=log_node_id,
                task_id=str(self.payload.get("taskId") or ""),
                phase=log_phase,
                provider_id=self.provider_id,
                model_name=self.model_name,
                endpoint=self.endpoint,
                source="_generate_storyboard_image_media",
            )
            if result.get("success"):
                self.model_request_logs.append(model_request_log_reference(result, phase=log_phase))
            else:
                self.model_request_log_errors.append(
                    {
                        "stage": STAGE_STORYBOARD_IMAGE_GENERATION_PROMPT,
                        "phase": log_phase,
                        "error": str(result.get("error") or "日志写入失败"),
                    }
                )
        def send_image_request(prompt_to_send: str) -> Any:
            panel_references = getattr(self, "active_panel_references", self.reference_images)
            return generate_image_media(
                self.provider,
                self.provider_id,
                self.base_url,
                self.model_name,
                prompt_to_send,
                size=self.size,
                aspect_ratio=self.storyboard_aspect_ratio,
                resolution=str(self.storyboard_resolution or ""),
                output_format=self.output_format,
                endpoint=self.endpoint,
                reference_image=_storyboard_transport_reference_image(panel_references),
                reference_images=panel_references,
                max_reference_images=self.max_reference_images,
                image_input_limits=self.image_input_limits,
                on_request_prepared=log_storyboard_image_request,
            )
        def request_image_media(prompt_to_send: str) -> Any:
            return run_cancellable_model_request(
                lambda: send_image_request(prompt_to_send), self.check_image_task_cancelled,
            )
        panels = self.payload.get("panels") if isinstance(self.payload.get("panels"), list) else []
        if panels and not self.requested_image_edit:
            from .storyboard_frame_readiness import (
                storyboard_frame_readiness_issues, storyboard_image_prompt_refusal_risks,
            )

            frame_issues = storyboard_frame_readiness_issues(panels, self.model_name)
            if frame_issues:
                first = frame_issues[0]
                raise ValueError(
                    f"镜头 {first['shotNo']} 的 storyboardFrame 未通过图片前画面专项预检："
                    f"{first['message']}；请修正正式分镜中该镜的画面字段后重试"
                )
            request_risks = storyboard_image_prompt_refusal_risks(self.prompt, self.model_name)
            if request_risks:
                raise ValueError(
                    "本次图片请求仍包含已复现的供应商拒绝风险措辞："
                    + "、".join(request_risks)
                    + "。请按实际请求定位画面、事件标识、资产参考、项目视觉或用户补充的来源，再修对应字段。"
                )
        policy_feedback_errors: list[dict[str, Any]] = []
        try:
            self.response = request_image_media(self.prompt)
        except GenerationCancelled:
            raise
        except Exception as exc:
            if self.image_generation_mode == "image_edit":
                raise
            from .storyboard_provider_feedback import image_provider_error_details
            initial_provider_error = _compact_text(str(exc) or exc.__class__.__name__, 1200)
            policy_feedback_errors.append(
                {
                    "attempt": 0,
                    "providerError": initial_provider_error,
                }
            )
            safety_flow = self.payload.get("storyboardImageSafetyFlow") if isinstance(self.payload.get("storyboardImageSafetyFlow"), dict) else {}
            self.payload = {
                **self.payload,
                "storyboardImageSafetyFlow": {
                    **copy.deepcopy(safety_flow),
                    "providerFailed": True,
                    "providerError": initial_provider_error,
                    "providerErrorDetails": image_provider_error_details(exc),
                },
                "imageGenerationPolicyFeedback": copy.deepcopy(policy_feedback_errors),
            }
            raise _storyboard_image_generation_error(
                initial_provider_error or exc.__class__.__name__,
                self.payload,
            ) from exc
        self.raw = self.response.raw
        if self.raw is None:
            raise RuntimeError("图片模型未返回可用图片数据")

    def _save_result(self) -> dict[str, Any]:
        debug = _persistent_media_data_removed(self.response.debug)
        if isinstance(self.payload.get("storyboardPanelEdit"), dict):
            debug["panelEdit"] = {
                **copy.deepcopy(self.payload.get("storyboardPanelEdit") or {}),
                "mode": "whole_sheet_model_edit",
            }
        reference_consumption = _storyboard_image_reference_consumption_report(
            debug,
            provider_id=self.provider_id,
            model_id=str(self.model.get("id") or ""),
            reference_count=len(self.reference_images),
        )
        if reference_consumption:
            debug = {**debug, "referenceConsumption": reference_consumption}
        if self.model_request_logs:
            debug = {**debug, "modelRequestLogs": copy.deepcopy(self.model_request_logs)}
        if self.model_request_log_errors:
            debug = {**debug, "modelRequestLogErrors": copy.deepcopy(self.model_request_log_errors)}
        debug = {
            **debug,
            "imageGenerationMode": self.image_generation_mode,
            "targetImageParameters": {
                "kind": "visual_handoff" if self.is_visual_handoff_image else "storyboard",
                "desiredAspectRatio": self.desired_storyboard_aspect_ratio,
                "aspectRatio": self.storyboard_aspect_ratio,
                "resolution": str(self.storyboard_resolution or ""),
                "size": self.size,
                "request": self.request_plan,
                "aspectRatioAdaptation": {
                    "desired": self.desired_storyboard_aspect_ratio,
                    "request": self.storyboard_aspect_ratio,
                    "appliedBeforeRequest": self.desired_storyboard_aspect_ratio != self.storyboard_aspect_ratio,
                },
            },
            "imageResolutionRequest": self.request_plan,
            "referenceInputLimits": self.image_input_limits,
            "referenceImageCount": len(self.reference_images),
            "productionTrace": {
                "aiContentDisclosure": _project_ai_content_disclosure_metadata(self.project_config),
                "productionSpec": copy.deepcopy(self.payload.get("productionSpec") or {}),
                "storyboardRenderSpec": copy.deepcopy(self.storyboard_render_spec),
            },
        }
        if self.image_generation_mode == "image_edit":
            provider_file_id_count = _debug_request_reference_file_id_count(debug.get("request"))
            extra_reference_count = len(self.asset_reference_images) + len(self.inline_reference_images)
            debug = {
                **debug,
                "imageEdit": {
                    "baseVersionId": self.payload.get("baseVersionId") or self.payload.get("base_version_id"),
                    "baseMediaId": self.payload.get("baseMediaId") or self.payload.get("base_media_id"),
                    "baseReferenceMediaIds": self.base_reference_ids,
                    "baseReferenceCount": len(self.base_reference_images),
                    "baseReference": _provider_reference_metadata(self.base_reference_images[0]) if self.base_reference_images else None,
                    "editTransport": "provider_file_id" if provider_file_id_count else "image_bytes",
                    "providerImageIdUsed": provider_file_id_count > 0,
                    "providerImageIdCount": provider_file_id_count,
                    "extraReferenceMediaIds": self.reference_ids,
                    "extraReferenceCount": extra_reference_count,
                    "extraInlineReferenceCount": len(self.inline_reference_images),
                    "extraAssetReferenceCount": len(self.asset_reference_images),
                    "referenceRoleInstructionApplied": self.edit_extra_reference_count > 0,
                },
            }
        if self.reference_ids or self.reference_images:
            debug = {
                **debug,
                "referencePlan": {
                    "referenceMediaIds": self.reference_ids,
                    "baseReferenceMediaIds": self.base_reference_ids,
                    "assetReferenceMediaIds": []
                    if self.image_generation_mode == "image_edit" or self.asset_refs_resolved_by_links
                    else _asset_reference_ids_from_generation_sources(self.payload, self.resolved_config),
                    "inlineReferenceCount": len(self.inline_reference_images),
                    "assetReferenceCount": len(self.asset_reference_images),
                    "baseReferenceCount": len(self.base_reference_images),
                    "promptOnlyReferenceCount": len(self.suppressed_reference_images),
                    "resolvedReferenceCount": len(self.reference_images),
                    "transportMode": (
                        "single_reference_image"
                        if self.selected_reference
                        else "multi_reference_images"
                        if self.reference_images
                        else "text_prompt_only"
                    ),
                    "transportReferenceCount": 1 if self.selected_reference else len(self.reference_images),
                    "selectedReference": _provider_reference_metadata(self.selected_reference),
                    "selectedReferences": [_provider_reference_metadata(reference) for reference in self.reference_images],
                },
            }
        media_id = (
            f"visual-handoff-{self.episode_id}-{uuid.uuid4().hex[:8]}"
            if self.is_visual_handoff_image
            else f"storyboard-{self.episode_id}-{uuid.uuid4().hex[:8]}"
        )
        self.check_image_task_cancelled()
        task_id = str(self.payload.get("taskId") or "").strip()
        if task_id:
            from .task_control import _begin_task_result_commit

            if not _begin_task_result_commit(task_id, message="正在保存图片生成结果。"):
                raise RuntimeError("图片生成任务已取消，结果未保存")
        save_image = _save_project_original_image_media_file if self.is_storyboard_image else _save_project_image_media_file
        media = save_image(
            self.project_id,
            self.raw,
            media_id=media_id,
            subdir="visual_handoffs" if self.is_visual_handoff_image else "storyboard_images",
            **({} if self.is_storyboard_image else {"original_name": f"{media_id}.png"}),
            source_mime=str(debug.get("mimeType") or _image_output_source_mime(self.output_format)),
            storage_scope="episode_results",
            episode_id=self.episode_id,
        )
        provider_generated_image_id = _provider_generated_image_file_id_from_debug(debug)
        if provider_generated_image_id:
            media["providerFileId"] = provider_generated_image_id
            media["providerMediaId"] = provider_generated_image_id
        debug["actualImageParameters"] = image_resolution_actual_report(media, self.request_plan)
        if self.is_storyboard_image:
            debug["actualImageParameters"]["savedFormat"] = media.get("mimeType") or ""
            debug["actualImageParameters"]["savedSha256"] = media.get("sha256") or ""
        if provider_generated_image_id:
            debug["providerGeneratedImageIdPersisted"] = True
        return {
            "media": media,
            "source": "model-image-edit" if self.image_generation_mode == "image_edit" else "model-image-generation",
            "model": self.model.get("id"),
            "provider": self.provider_id,
            "payload": self.payload,
            "debug": debug,
        }


def _generate_storyboard_image_media(
    project_id: str,
    episode_id: str,
    title: str,
    payload: dict[str, Any],
    *,
    workflow_projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generation = _StoryboardImageGeneration(project_id, episode_id, title, payload, workflow_projection)
    generation._prepare_model()
    generation._prepare_references()
    generation._prepare_request()
    generation._generate()
    return generation._save_result()


def _debug_image_input_token_count(debug: dict[str, Any]) -> int | None:
    response = debug.get("response") if isinstance(debug.get("response"), dict) else {}
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    raw_value = details.get("image_tokens")
    if raw_value is None:
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _debug_request_has_reference_image(value: Any) -> bool:
    if isinstance(value, dict):
        try:
            reference_count = int(value.get("referenceImageCount") or 0)
        except (TypeError, ValueError):
            reference_count = 0
        if reference_count > 0:
            return True
        if str(value.get("imageField") or "").strip() in {"image", "image[]", "images"}:
            return True
        if str(value.get("reference_transport") or "").strip() in {
            "multipart_form_data",
            "image_url",
            "provider_file_id",
        }:
            return True
        for key, item in value.items():
            if str(key) in _REFERENCE_REQUEST_KEYS and bool(item):
                return True
            if _debug_request_has_reference_image(item):
                return True
    if isinstance(value, list):
        return any(_debug_request_has_reference_image(item) for item in value)
    return False


def _debug_request_reference_file_id_count(value: Any) -> int:
    if isinstance(value, dict):
        count = 1 if str(value.get("file_id") or value.get("fileId") or "").strip() else 0
        return count + sum(_debug_request_reference_file_id_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(_debug_request_reference_file_id_count(item) for item in value)
    return 0


def _storyboard_image_reference_consumption_report(
    debug: dict[str, Any],
    *,
    provider_id: str,
    model_id: str,
    reference_count: int,
) -> dict[str, Any]:
    if reference_count <= 0:
        return {}
    backend = str(debug.get("backend") or "").strip()
    request = debug.get("request") if isinstance(debug.get("request"), dict) else {}
    has_inline_reference = _debug_request_has_reference_image(request)
    image_tokens = _debug_image_input_token_count(debug)
    report: dict[str, Any] = {
        "status": "observed",
        "referenceCount": reference_count,
        "backend": backend,
        "requestHasReferenceImage": has_inline_reference,
    }
    if image_tokens is not None:
        report["imageTokens"] = image_tokens
    warnings: list[str] = []
    if not has_inline_reference:
        warnings.append("分镜图任务已链接参考资产，但调试记录中没有识别到供应商请求携带图片参考。")
    if backend == "openai-compatible" and image_tokens == 0:
        warnings.append(
            f"图片模型 {model_id or provider_id} 没有消费参考图片（image_tokens=0）。"
            "已按模型实际返回保存图片，请人工检查参考图一致性。"
        )
    if warnings:
        report["status"] = "warning"
        report["warnings"] = warnings
    return report


def _storyboard_prompt_is_full_sheet(payload: dict[str, Any]) -> bool:
    spec = payload.get("storyboardPromptSpec") if isinstance(payload.get("storyboardPromptSpec"), dict) else {}
    return str(spec.get("format") or "").strip() == "storyboard_panel_sequence"


def _parse_image_size_text(value: Any) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\s*[xX×*]\s*(\d+)\s*", str(value or ""))
    if not match:
        return None
    width, height = int(match.group(1)), int(match.group(2))
    if width <= 0 or height <= 0:
        return None
    return width, height


def _storyboard_reference_role_flags(reference_images: list[dict[str, Any]]) -> tuple[set[str], bool]:
    flags: set[str] = set()
    has_bound_reference = False
    for item in reference_images:
        if not isinstance(item, dict):
            continue
        if str(item.get("assetId") or item.get("assetType") or item.get("requestedReferenceId") or "").strip():
            has_bound_reference = True
        parts: list[str] = []
        for key in (
            "requestedReferenceId",
            "referenceRole",
            "reference_role",
            "role",
            "purpose",
            "assetType",
            "asset_type",
            "slot",
            "source",
            "sourceType",
            "source_type",
            "label",
            "name",
            "caption",
        ):
            value = item.get(key)
            if value in (None, ""):
                continue
            if isinstance(value, (dict, list)):
                parts.append(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
            else:
                parts.append(str(value))
        text = " ".join(parts).casefold()
        matched = False
        if any(token in text for token in ("layout", "composition", "storyboard_template_layout", "layout_reference", "版式", "构图", "排版")):
            flags.add("layout")
            matched = True
        if any(token in text for token in ("visual_handoff", "handoff", "continuity", "spatial_continuity", "视觉交接", "空间连续", "交接图")):
            flags.add("visual_handoff")
            matched = True
        if any(token in text for token in ("style", "style_reference", "visual_style", "风格", "画风", "美术")):
            flags.add("style")
            matched = True
        if any(token in text for token in ("character", "characters", "person", "角色", "人物")):
            flags.add("character")
            matched = True
        if any(token in text for token in ("creature", "creatures", "monster", "monsters", "beast", "beasts", "生物", "怪物", "妖兽", "魔兽", "异兽")):
            flags.add("creature")
            matched = True
        if any(token in text for token in ("scene", "scenes", "location", "environment", "场景", "环境", "地点")):
            flags.add("scene")
            matched = True
        if any(token in text for token in ("prop", "props", "item", "object", "道具", "物件")):
            flags.add("prop")
            matched = True
        if not matched and str(item.get("assetId") or item.get("assetType") or item.get("requestedReferenceId") or "").strip():
            flags.add("generic")
    return flags, has_bound_reference


def _storyboard_reference_consistency_prompt(
    reference_images: list[dict[str, Any]],
    *,
    is_visual_handoff_image: bool = False,
) -> str:
    reference_images = [
        item for item in reference_images
        if isinstance(item, dict) and not any(item.get(key) == "custom_image" for key in ("assetType", "mediaPurpose", "slot"))
    ]
    if not reference_images:
        return ""
    flags, has_bound_reference = _storyboard_reference_role_flags(reference_images)
    if is_visual_handoff_image:
        lines = [
            "随附参考图必须按视觉交接图生成任务、可拍摄内容、分镜线索和资产引用清单理解，不要只凭文件名猜测。"
        ]
        if flags.intersection({"character", "creature", "scene", "prop"}) or has_bound_reference:
            lines.append("已绑定参考图只约束其绑定对象的身份、外观、材质和连续性，具体对象以资产引用清单为准。")
            lines.append(
                "已绑定资产只约束同名、别名或上下文明确为同一身份、同一空间、同一物件的对象；未绑定且无法证明与已绑定资产同一身份的临时人物、场景或物件，须按可拍摄内容独立呈现，不得套用已绑定资产的外观。"
            )
        if "style" in flags:
            lines.append("风格参考图只用于约束画风、色彩、质感和光影气质，不替代本段剧情事实或空间连续性任务。")
        if "layout" in flags:
            lines.append("版式或构图参考图只用于理解交接图的画面组织方式，不复制其中的剧情内容，不覆盖空间连续性交接图任务。")
        if "visual_handoff" in flags:
            lines.append("视觉交接图参考只用于理解前序剧情结尾的空间状态、位置、朝向和相对关系，不新增剧情。")
        if "generic" in flags or not flags:
            lines.append("未标明用途的用户绑定图片按可拍摄内容、分镜线索和不改变空间连续性的用户补充要求解释，不自动升级为新的剧情资产。")
        lines.append(
            "随附故事版分镜图用于理解本段剧情已建立的镜头、空间关系和最后有效状态；它不是可裁切复刻的输出模板，也不要求保留原故事板版式或镜头画格。"
        )
        lines.append(
            "优先级：视觉交接图生成任务和空间连续性要求 > 可拍摄内容与分镜线索 > 资产身份与参考图外观 > 项目视觉补充 > 用户本轮不改变空间连续性的呈现偏好。"
        )
        return "【视觉参考一致性要求】\n" + "".join(lines)
    lines = [
        "随附参考图必须按分镜脚本、资产引用清单和用户本轮不改变分镜脚本的呈现偏好理解，不要只凭文件名猜测。"
    ]
    if flags.intersection({"character", "creature", "scene", "prop"}):
        lines.append("角色、生物、场景、道具参考图用于锁定对应资产的身份、外观、空间关系、道具形态和连续性。")
    elif has_bound_reference:
        lines.append("已绑定参考图用于约束其绑定对象的外观和连续性，具体对象以资产引用清单为准。")
    if flags.intersection({"character", "creature", "scene", "prop"}) or has_bound_reference:
        lines.append(
            "已绑定资产只约束同名、别名或上下文明确为同一身份、同一空间、同一物件的对象；分镜脚本中需要入画但未绑定的对象，按计划已确定的身份、外观与状态呈现，不得套用绑定角色的脸、发型、服装、体态或道具外观。"
        )
    if "style" in flags:
        lines.append("风格参考图只用于约束画风、色彩、质感和光影气质，不替代当前剧情、角色或场景资产。")
    if "visual_handoff" in flags:
        lines.append("视觉交接图用于约束前序剧情结尾的空间状态、人物/生物/关键道具/陈设位置、朝向和相对关系；只在当前剧情承接同一场景、同一行动线或连续时间时执行，不替代当前分镜脚本。")
    if "layout" in flags:
        lines.append("版式或构图参考图只用于理解故事版工作页结构、辅助区组织和画面构成，不复制其中的剧情内容，不改变分镜脚本。")
    if "generic" in flags or not flags:
        lines.append("未标明用途的用户绑定图片按分镜脚本、资产引用清单和不改变分镜脚本的用户补充要求解释，不自动升级为新的剧情资产。")
    lines.append("优先级：分镜脚本决定镜头数量、顺序、镜头调度和每个镜头必须画出的可见内容；分镜图版式规则只提供版面组织、辅助区和短标签组织方式；参考图只约束其已声明或已绑定的身份、外观、风格、构图用途；用户本轮要求只能作为不改变分镜脚本的呈现偏好。")
    return "【视觉参考一致性要求】\n" + "".join(lines)


def _storyboard_transport_reference_image(reference_images: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows = [
        copy.deepcopy(row)
        for row in reference_images
        if isinstance(row, dict) and str(row.get("dataUrl") or "").strip()
    ]
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    return None


_IMAGE_EDIT_EXTRA_REFERENCE_ROLE_INSTRUCTION = (
    "第一张输入图片是必须被修改的原图；其余输入图片仅作为参考图，"
    "按本次要求参考其对应主体、风格或细节，不把参考图当作被修改对象。"
)


_IMAGE_EDIT_BASE_PRESERVATION_INSTRUCTION = (
    "图片编辑任务：输入原图是唯一被修改对象，只执行本次明确要求的修改。"
    "除本次明确要求调整的部分外，保留原图的分镜结构、镜头数量、镜头顺序、"
    "角色身份、场景关系、主体构图、风格、画幅比例及其他视觉内容。"
)





_REFERENCE_REQUEST_KEYS = {
    "input_reference",
    "image",
    "image[]",
    "images",
    "image_url",
    "image_urls",
    "reference_image",
    "reference_images",
    "inlineData",
    "inline_data",
}
