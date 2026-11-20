# -*- coding: utf-8 -*-
"""供应商视频提示词、参考素材说明、音色上下文与请求预算。"""
from __future__ import annotations

from .model_generation_contract import _SUPPORTED_FINAL_VIDEO_PROMPT_PROFILES
from .model_generation_contract import _generation_text_value
from .provider_reference_media import _active_asset_media_candidate
from .settings_loaders import load_text_replacement_rules
from .store_core import ASSET_LIFECYCLE_ACTIVE
from .storyboard_templates import storyboard_reference_brief
from .video_provider_references import VISUAL_HANDOFF_REFERENCE_BRIEF
from .video_provider_references import _video_official_reference_entries
from .video_provider_references import _video_reference_row_dedupe_identity
from .video_provider_references import _video_reference_row_is_input_link
from .video_provider_references import _video_reference_row_label
from .video_provider_references import _video_reference_row_slot
from typing import Any, Callable
from utils.frame_references import frame_reference_brief
from utils.video_prompt_mentions import PROMPT_REFERENCE_PATTERN, prompt_reference_label, resolve_prompt_mentions
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_DASHSCOPE_WAN27_R2V_OFFICIAL
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_VIDU_Q3_REFERENCE_OFFICIAL
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_HAPPYHORSE_OFFICIAL
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_GROK_OFFICIAL
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_KLING_OFFICIAL
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_VEO_OFFICIAL
from utils.video_model_capabilities import FINAL_VIDEO_PROMPT_PROFILE_MINIMAX_H3_OFFICIAL
import copy
import re
import traceback

VIDEO_CLEAN_FRAME_INSTRUCTION = "不生成字幕，但剧情内实物或屏幕上的必要文字，仅按镜头正文要求保留。"
VIDEO_REFERENCE_FRAME_INSTRUCTION = (
    "参考图仅用于理解画面，不能将其中的说明文字、编号、箭头、边框、水印或多格排版等辅助标记带入生成画面。"
    + VIDEO_CLEAN_FRAME_INSTRUCTION
)
VIDEO_STORYBOARD_EXECUTION_INSTRUCTION = (
    "分镜图仅提供静态画面参考，剧情、镜头顺序和动作以镜头正文为准。"
)


def _supplier_prompt_one_line(value: Any) -> str:
    return re.sub(r"\s+", " ", _generation_text_value(value, limit=0)).strip()


def _supplier_prompt_sentence(value: Any) -> str:
    text = _generation_text_value(value, limit=0).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    if text.endswith(("。", "！", "？", ".", "!", "?")):
        return text
    return f"{text}。"


def _storyboard_reference_instruction(token: str, entry: dict[str, Any]) -> str:
    subject = f"{token}：<{entry['mentionLabel']}>" if entry.get("mentionLabel") else token
    spec = entry.get("storyboardPromptSpec")
    return f"{subject}，{storyboard_reference_brief(spec if isinstance(spec, dict) else {})}"


def _supplier_prompt_role_label(entry: dict[str, Any]) -> str:
    kind = str(entry.get("kind") or "")
    if bool(entry.get("isVisualHandoff")):
        return "视觉交接图"
    if bool(entry.get("isStoryboard")):
        return "故事板"
    if "角色" in kind:
        return "角色"
    if "生物" in kind:
        return "生物"
    if "场景" in kind:
        return "场景"
    if "道具" in kind:
        return "道具"
    return "参考"


def _supplier_prompt_reference_name(entry: dict[str, Any]) -> str:
    name = _supplier_prompt_one_line(entry.get("mentionLabel") or entry.get("label"))
    if not name:
        return ""
    name = f"<{name}>" if entry.get("mentionLabel") else name
    brief = _supplier_prompt_one_line(entry.get("brief"))
    if brief and brief.casefold() not in name.casefold():
        return f"{name}（{brief}）"
    return name


def _supplier_prompt_reference_binding(token: str, entry: dict[str, Any]) -> str:
    clean_token = _supplier_prompt_one_line(token)
    if not clean_token:
        return ""
    if entry.get("isCustomImage"):
        name = _supplier_prompt_reference_name(entry)
        return f"{clean_token}：{name}" if name else ""
    if entry.get("isFrame"):
        native_role = entry.get("nativeRole")
        name = str(entry.get("mentionLabel") or ("尾帧" if entry.get("frameRole") == "last_frame" else "首帧"))
        if native_role in {"first_frame", "last_frame"}:
            return f"<{name}>指输入的{'尾帧' if native_role == 'last_frame' else '首帧'}画面"
        return f"{clean_token}：<{name}>，{frame_reference_brief(str(entry.get('frameRole') or 'first_frame'))}"
    role = _supplier_prompt_role_label(entry)
    if role == "视觉交接图":
        return f"{clean_token}：<{entry.get('mentionLabel') or '视觉交接图'}>参考，{VISUAL_HANDOFF_REFERENCE_BRIEF}"
    name = _supplier_prompt_reference_name(entry)
    if not name:
        return ""
    if role == "角色":
        label = "角色参考"
    elif role == "生物":
        label = "生物参考"
    elif role == "场景":
        label = "场景参考"
    elif role == "道具":
        label = "道具参考"
    else:
        label = "补充参考"
    return f"{clean_token}：{label}，{name}"


def _supplier_reference_sentence(
    entries: list[dict[str, Any]], *, image_label: str, index_offset: int = 0,
) -> str:
    storyboard_parts: list[str] = []
    asset_parts: list[str] = []
    for entry in entries:
        index = int(entry.get("index") or 0)
        token = image_label.format(index=index + index_offset) if index > 0 else "参考图"
        if entry.get("isStoryboard"):
            storyboard_parts.append(_storyboard_reference_instruction(token, entry))
        else:
            binding = _supplier_prompt_reference_binding(token, entry)
            if binding:
                asset_parts.append(_supplier_prompt_sentence(binding))
    return "\n".join(storyboard_parts + asset_parts)


def _seedance_official_reference_sentence(entries: list[dict[str, Any]], *, image_label: str = "图片{index}") -> str:
    return _supplier_reference_sentence(entries, image_label=image_label)


def _dashscope_wan_reference_sentence(entries: list[dict[str, Any]], *, image_label: str = "图{index}", index_offset: int = 0) -> str:
    return _supplier_reference_sentence(entries, image_label=image_label, index_offset=index_offset)


def _vidu_q3_reference_sentence(entries: list[dict[str, Any]]) -> str:
    return _supplier_reference_sentence(entries, image_label="图{index}")


def _supplier_official_asset_reference_prompt_from_payload(
    prompt_profile: str,
    payload: dict[str, Any],
    reference_images: list[dict[str, Any]] | None,
    *,
    prepared_entries: list[dict[str, Any]] | None = None,
    seedance_image_label: str = "图片{index}",
) -> str:
    if not reference_images:
        return ""
    entries = prepared_entries if prepared_entries is not None else _video_official_reference_entries(payload, reference_images)
    if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT:
        prompt = _seedance_official_reference_sentence(entries, image_label=seedance_image_label)
    elif prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_DASHSCOPE_WAN27_R2V_OFFICIAL:
        prompt = _dashscope_wan_reference_sentence(entries)
    elif prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_HAPPYHORSE_OFFICIAL:
        prompt = _dashscope_wan_reference_sentence(entries, image_label="[Image {index}]")
    elif prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_GROK_OFFICIAL:
        has_first_frame = any(row.get("transportRole") == "first_frame" for row in reference_images)
        prompt = _dashscope_wan_reference_sentence(entries, image_label="<IMAGE_{index}>", index_offset=0 if has_first_frame else -1)
    elif prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_KLING_OFFICIAL:
        has_first_frame = any(row.get("transportRole") == "first_frame" for row in reference_images)
        prompt = _dashscope_wan_reference_sentence(entries, image_label="<<<image_{index}>>>", index_offset=1 if has_first_frame else 0)
    elif prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_VIDU_Q3_REFERENCE_OFFICIAL:
        prompt = _vidu_q3_reference_sentence(entries)
    elif prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_MINIMAX_H3_OFFICIAL:
        prompt = _dashscope_wan_reference_sentence(entries, image_label="参考图{index}")
    elif prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_VEO_OFFICIAL:
        if any(entry.get("nativeRole") not in {"first_frame", "last_frame"} for entry in entries):
            raise RuntimeError("当前 Veo 中转接口仅支持原生帧输入")
        prompt = "\n".join(_supplier_prompt_reference_binding("帧画面", entry) for entry in entries)
    else:
        raise RuntimeError(f"当前视频模型配置了未接入的视频提示词路线：{prompt_profile}")
    return prompt


def _supplier_official_prepared_prompt_reference_meta(
    prompt_profile: str,
    entries: list[dict[str, Any]],
    *,
    asset_reference_prompt: str,
) -> dict[str, Any]:
    reference_count = len(entries)
    reference_brief_count = sum(1 for entry in entries if entry.get("brief"))
    storyboard_count = sum(1 for entry in entries if entry.get("isStoryboard"))
    base = {
        "enabled": False,
        "skipped": "already_final_provider_prompt",
        "assetReferencePromptPrepended": bool(asset_reference_prompt),
        "referenceCount": reference_count,
        "referenceBriefCount": reference_brief_count,
        "storyboardReferenceCount": storyboard_count,
    }
    if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT:
        return {
            **base,
            "profile": FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT,
            "officialRenderer": "seedance_official_compact_formula_asset_reference_only",
            "sourceUrls": [
                "https://docs.volcengine.com/docs/82379/2222480",
                "https://docs.volcengine.com/docs/82379/1520757",
            ],
            "referenceLabelStyle": "图片N",
        }
    if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_DASHSCOPE_WAN27_R2V_OFFICIAL:
        return {
            **base,
            "profile": FINAL_VIDEO_PROMPT_PROFILE_DASHSCOPE_WAN27_R2V_OFFICIAL,
            "officialRenderer": "dashscope_wan_formula_asset_reference_only",
            "sourceUrls": [
                "https://help.aliyun.com/zh/model-studio/wan-video-to-video-api-reference",
                "https://help.aliyun.com/zh/model-studio/wan3-video-generation-api-reference",
                "https://help.aliyun.com/zh/model-studio/text-to-video-prompt",
            ],
            "referenceLabelStyle": "图N",
        }
    if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_VIDU_Q3_REFERENCE_OFFICIAL:
        return {
            **base,
            "profile": FINAL_VIDEO_PROMPT_PROFILE_VIDU_Q3_REFERENCE_OFFICIAL,
            "officialRenderer": "vidu_reference2video_images_asset_reference_only",
            "sourceUrls": [
                "https://platform.vidu.com/docs/reference-to-video",
                "https://platform.vidu.com/docs/model-map",
                "https://platform.vidu.com/docs/prompt-rec",
                "https://help.aliyun.com/zh/model-studio/vidu-video-generation-prompt-guide",
            ],
            "referenceLabelStyle": "图N",
            "imageReferenceTransport": "images",
            "subjectSyntaxUsed": False,
            "imageIdSyntaxUsed": False,
            "subjectSyntaxReason": "当前提交层发送 images 数组，不发送 Vidu subjects payload；因此按图片上传顺序用自然语言说明参考图用途。",
        }
    if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_HAPPYHORSE_OFFICIAL:
        return {
            **base, "profile": prompt_profile,
            "officialRenderer": "happyhorse_asset_reference_only",
            "sourceUrls": ["https://help.aliyun.com/zh/model-studio/happyhorse-reference-to-video-api-reference"],
            "referenceLabelStyle": "[Image N]",
        }
    if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_KLING_OFFICIAL:
        return {**base, "profile": prompt_profile, "officialRenderer": "kling_asset_reference_only",
                "sourceUrls": ["https://apidocs.qnaigc.com/420877484e0.md"], "referenceLabelStyle": "<<<image_N>>>"}
    if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_GROK_OFFICIAL:
        return {
            **base, "profile": prompt_profile, "officialRenderer": "grok_asset_reference_only",
            "sourceUrls": ["https://docs.x.ai/developers/model-capabilities/video/reference-to-video"],
            "referenceLabelStyle": "<IMAGE_N>",
        }
    raise RuntimeError(f"当前视频模型配置了未接入的视频提示词路线：{prompt_profile}")


def _supplier_prompt_join(parts: list[str]) -> str:
    rows: list[str] = []
    for item in parts:
        text = _generation_text_value(item, limit=0).replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            continue
        lines = [_supplier_prompt_one_line(line) for line in text.split("\n")]
        block = "\n".join(line for line in lines if line).strip()
        if block:
            rows.append(block)
    unique: list[str] = []
    for row in rows:
        if row not in unique:
            unique.append(row)
    return "\n".join(unique).strip()


def _video_boundary_reference_instruction(payload: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    """Explain only boundary inputs that are actually sent to this generation."""
    if payload.get("videoTaskScope") != "work_chain":
        return ""
    plan = payload.get("videoInputPlan") or {}
    kind = plan.get("boundaryKind")
    native_roles = {entry.get("nativeRole") for entry in entries}
    if (kind == "direct_continuation" and plan.get("mode") == "native_keyframe"
            and {"first_frame", "last_frame"}.issubset(native_roles)):
        return (
            "片头从输入首帧接续当前动作，不重演上一段；本镜结束画面趋近输入尾帧。"
            "静态首帧不代表运动速度。"
        )
    if kind == "spatial_cut" and any(entry.get("isVisualHandoff") for entry in entries):
        return (
            "片头按镜头正文切换机位；视觉交接图仅用于维持人物、道具与视线的空间关系。"
        )
    # A time/space jump belongs in the first shot's execution. An independent
    # request without preceding media has no previous picture to continue.
    return ""


def _apply_final_video_prompt_replacement_rules(prompt: str) -> tuple[str, dict[str, Any]]:
    text = str(prompt or "")
    rules = load_text_replacement_rules()
    applied: list[dict[str, Any]] = []
    for row in rules:
        if not isinstance(row, dict):
            continue
        pattern = str(row.get("from") or row.get("pattern") or "").strip()
        replacement = str(row.get("to") or row.get("replacement") or "")
        if not pattern:
            continue
        try:
            next_text, count = re.subn(pattern, replacement, text)
        except re.error as exc:
            applied.append({"from": pattern, "to": replacement, "count": 0, "error": str(exc)})
            continue
        if count:
            applied.append({"from": pattern, "to": replacement, "count": count})
            text = next_text
    total = sum(int(item.get("count") or 0) for item in applied)
    return text, {
        "enabled": bool(rules),
        "applied": total > 0,
        "count": total,
        "rules": applied[:40],
    }


def _video_reference_row_looks_like_voice_asset(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    slot = _video_reference_row_slot(row)
    if slot in _VIDEO_VOICE_STYLE_REFERENCE_SLOTS:
        return True
    asset_type = str(
        row.get("assetType")
        or row.get("asset_type")
        or row.get("assetKind")
        or row.get("asset_kind")
        or row.get("sourceType")
        or row.get("source_type")
        or ""
    ).strip().casefold()
    return "character" in asset_type or "creature" in asset_type


def _video_voice_style_value_from_row(row: dict[str, Any]) -> str:
    if not isinstance(row, dict):
        return ""
    candidates: list[dict[str, Any]] = [row]
    for key in ("asset", "data", "metadata", "provenance"):
        value = row.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    for source in candidates:
        for key in ("voiceStyle", "voice_style"):
            text = _generation_text_value(source.get(key), limit=0)
            if text:
                return text
    return ""


def _video_voice_style_label_from_row(row: dict[str, Any], fallback: str = "") -> str:
    label = _video_reference_row_label(row, fallback)
    if label:
        return re.sub(r"\s+", " ", _generation_text_value(label, limit=0)).strip()
    media = row.get("media") if isinstance(row.get("media"), dict) else {}
    for key in ("label", "displayName", "display_name", "assetName", "asset_name", "name", "title"):
        text = re.sub(r"\s+", " ", _generation_text_value(media.get(key), limit=0)).strip()
        if text:
            return text
    return re.sub(r"\s+", " ", _generation_text_value(fallback, limit=0)).strip()


def _video_voice_style_candidate_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in (
        payload,
        payload.get("videoTaskCard") if isinstance(payload.get("videoTaskCard"), dict) else {},
        payload.get("storyboardTaskCard") if isinstance(payload.get("storyboardTaskCard"), dict) else {},
    ):
        if not isinstance(source, dict):
            continue
        for key in (
            "assetThumbnails",
            "assetThumbnailsSnapshot",
            "referenceThumbnails",
            "referenceThumbnailsSnapshot",
            "inputLinksSnapshot",
            "inputLinks",
        ):
            value = source.get(key)
            if not isinstance(value, list):
                continue
            for row in value:
                if not isinstance(row, dict) or not _video_reference_row_looks_like_voice_asset(row):
                    continue
                identity = _video_reference_row_dedupe_identity(row)
                key_text = f"{_video_reference_row_slot(row)}|{identity}"
                if key_text in seen:
                    continue
                seen.add(key_text)
                rows.append(copy.deepcopy(row))
    return rows


def _video_voice_style_tokens_from_value(value: Any) -> set[str]:
    tokens: set[str] = set()

    def add(item: Any) -> None:
        text = str(item or "").strip()
        if text:
            tokens.add(text.casefold())

    def walk(item: Any) -> None:
        if isinstance(item, str):
            add(item)
            return
        if isinstance(item, list):
            for child in item:
                walk(child)
            return
        if not isinstance(item, dict):
            return
        for key in (
            "id",
            "linkId",
            "link_id",
            "inputLinkId",
            "input_link_id",
            "rootAssetId",
            "assetId",
            "mediaId",
            "media_id",
            "versionId",
            "version_id",
            "mediaVersionId",
            "media_version_id",
            "sourceVersionId",
            "source_version_id",
        ):
            add(item.get(key))
        if _video_reference_row_is_input_link(item):
            for key in ("sourceNodeId", "source_node_id"):
                add(item.get(key))
        for nested_key in ("media", "storage", "asset", "data", "provenance"):
            nested = item.get(nested_key)
            if isinstance(nested, (dict, list)):
                walk(nested)

    walk(value)
    return tokens


def _video_voice_style_match_tokens_from_payload(payload: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for row in _video_voice_style_candidate_rows_from_payload(payload):
        tokens.update(_video_voice_style_tokens_from_value(row))
    for source in (
        payload,
        payload.get("videoTaskCard") if isinstance(payload.get("videoTaskCard"), dict) else {},
        payload.get("storyboardTaskCard") if isinstance(payload.get("storyboardTaskCard"), dict) else {},
    ):
        if not isinstance(source, dict):
            continue
        for key in ("assetRefs", "asset_refs", "assetRefsSnapshot", "asset_refs_snapshot"):
            refs = source.get(key)
            if not isinstance(refs, dict):
                continue
            for collection in _VIDEO_VOICE_STYLE_ASSET_COLLECTIONS:
                tokens.update(_video_voice_style_tokens_from_value(refs.get(collection)))
    return tokens


def _video_voice_style_asset_identity_tokens(asset: dict[str, Any]) -> set[str]:
    tokens = _video_voice_style_tokens_from_value(asset)
    active_media = _active_asset_media_candidate(asset)
    if isinstance(active_media, dict):
        tokens.update(_video_voice_style_tokens_from_value(active_media))
    return tokens


def _video_voice_style_rows_from_bound_assets(
    project_id: str | None,
    payload: dict[str, Any],
    *,
    preserve_complete_text: bool = False,
) -> list[dict[str, str]]:
    from .assets import list_assets

    if not str(project_id or "").strip():
        return []
    match_tokens = _video_voice_style_match_tokens_from_payload(payload)
    if not match_tokens:
        return []
    try:
        assets = list_assets("project", str(project_id), hydrate=False, lifecycle_status=ASSET_LIFECYCLE_ACTIVE)
    except Exception:
        print(traceback.format_exc(), flush=True)
        return []
    rows: list[dict[str, str]] = []
    for collection in _VIDEO_VOICE_STYLE_ASSET_COLLECTIONS:
        asset_rows = assets.get(collection) if isinstance(assets, dict) else []
        if not isinstance(asset_rows, list):
            continue
        for asset in asset_rows:
            if not isinstance(asset, dict):
                continue
            style = _generation_text_value(
                asset.get("voiceStyle") or asset.get("voice_style"),
                limit=0,
            )
            if not style:
                continue
            if not (_video_voice_style_asset_identity_tokens(asset) & match_tokens):
                continue
            label = re.sub(
                r"\s+",
                " ",
                _generation_text_value(
                    asset.get("name") or asset.get("displayName") or asset.get("title"),
                    limit=0,
                ),
            ).strip()
            rows.append({"label": label, "style": style})
    return rows


def _video_voice_style_provider_line(
    project_id: str | None,
    payload: dict[str, Any],
    *,
    limit: int,
    existing_prompt: str = "",
    preserve_complete_text: bool = False,
) -> str:
    rows: list[str] = []
    existing_text = str(existing_prompt or "")

    def add_row(label: Any, style: Any) -> None:
        voice_style = re.sub(
            r"\s+",
            " ",
            _generation_text_value(style, limit=0),
        ).strip()
        if not voice_style or voice_style in existing_text:
            return
        name = re.sub(r"\s+", " ", _generation_text_value(label, limit=0)).strip() or "未命名角色"
        row = f"{name}={voice_style}"
        if row not in rows:
            rows.append(row)

    for row in _video_voice_style_candidate_rows_from_payload(payload):
        add_row(_video_voice_style_label_from_row(row), _video_voice_style_value_from_row(row))
    for row in _video_voice_style_rows_from_bound_assets(
        project_id,
        payload,
        preserve_complete_text=preserve_complete_text,
    ):
        add_row(row.get("label"), row.get("style"))

    if not rows:
        return ""
    return "角色声音设定: " + "；".join(rows)


def _current_video_task_prompt_from_payload(payload: dict[str, Any]) -> str:
    prompt_payload = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else {}
    value = prompt_payload.get("videoPrompt")
    if value is None:
        value = prompt_payload.get("video_prompt")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise RuntimeError(
            "当前视频生成 videoPrompt 类型异常，必须是字符串；"
            "已阻断生成，不能把结构化对象兜底拼接成视频提示词。"
        )
    return value.strip()


def _supplier_shot_labels_from_editor_prompt(prompt: str, prompt_profile: str, timing_style: str = "") -> str:
    """Translate only the reserved line-start 镜头N label, never shot prose."""
    if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT:
        if timing_style == "shot_sequence":
            # Seedance 2.0 follows shot order; subsecond editor bookkeeping is
            # retained on the card but need not become a provider instruction.
            prompt = re.sub(r"(?m)^整片时长：[0-9]+(?:\.[0-9]+)?秒。?\n?", "", prompt)
            prompt = re.sub(
                r"(?m)^(镜头[1-9][0-9]*)｜[0-9]+(?:\.[0-9]+)?[–-][0-9]+(?:\.[0-9]+)?秒"
                r"（[0-9]+(?:\.[0-9]+)?秒）(?=：)",
                r"\1", prompt,
            )
        return prompt

    def replace_label(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_DASHSCOPE_WAN27_R2V_OFFICIAL:
            return f"第{number}个镜头"
        if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_VIDU_Q3_REFERENCE_OFFICIAL:
            return f"Shot {number:02d}"
        return match.group(0)

    # This is the editor's explicit numbering protocol, not intent recognition.
    return re.sub(r"(?m)^镜头([1-9][0-9]*)(?=[：:｜])", replace_label, prompt)


def _render_user_asset_mentions(
    prompt: str,
    prompt_profile: str,
    reference_manifest: list[dict[str, Any]],
    bindings: dict[str, str],
    enabled_manifest: list[dict[str, Any]] | None = None,
    plain_image_asset_labels: bool = False,
) -> str:
    resolved = resolve_prompt_mentions(prompt, bindings, reference_manifest, enabled_manifest=enabled_manifest)

    def replace_token(match: re.Match[str]) -> str:
        row = resolved[prompt_reference_label(match)]
        if row["kind"] == "text":
            return match.group(0)
        if row["kind"] != "video":
            return row["mentionLabel"] if plain_image_asset_labels else f"<{row['mentionLabel']}>"
        if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT:
            return f"@video{row['index']}"
        if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_DASHSCOPE_WAN27_R2V_OFFICIAL:
            return f"视频{row['index']}"
        if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_MINIMAX_H3_OFFICIAL:
            return f"参考视频{row['index']}"
        raise RuntimeError("当前模型不支持参考视频编号，请移除视频引用或切换模型")

    return PROMPT_REFERENCE_PATTERN.sub(replace_token, prompt)


def _video_prompt_and_budget_from_generation_payload(
    title: str,
    payload: dict[str, Any],
    resolved_config: dict[str, Any],
    *,
    project_id: str | None = None,
    generate_audio: bool,
    reference_images: list[dict[str, Any]] | None = None,
    prompt_char_limit: int = 0,
    final_prompt_profile: str = "",
    prompt_timing_style: str = "",
    include_asset_reference_prompt: bool = True,
    reference_manifest: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    prompt = _current_video_task_prompt_from_payload(payload)
    if not prompt:
        raise RuntimeError("当前视频任务缺少视频提示词，无法生成视频。")
    original_core_length = len(prompt)
    prompt_profile = str(final_prompt_profile or "").strip()
    if not prompt_profile:
        raise RuntimeError(
            "当前视频模型未接入专用视频提示词路线，请先按该供应商官方文档接入 final_prompt_profile 后再生成视频。"
        )
    if prompt_profile not in _SUPPORTED_FINAL_VIDEO_PROMPT_PROFILES:
        raise RuntimeError(f"当前视频模型配置了未接入的视频提示词路线：{prompt_profile}")
    reference_entries = (
        _video_official_reference_entries(payload, reference_images)
        if reference_images
        else []
    )
    prepared_reference_entries = reference_entries if include_asset_reference_prompt else []
    manifest = reference_manifest if isinstance(reference_manifest, list) else payload.get("referenceManifest") or []
    image_mentions = [row for row in manifest if row.get("kind") == "image"]
    named_entries = []
    for entry in prepared_reference_entries:
        labels = list(dict.fromkeys(
            row.get("mentionLabel") for row in image_mentions
            if row.get("mentionLabel") and row.get("index") == entry["index"]
            and (entry["index"] > 0 or row.get("transportRole") == entry.get("nativeRole"))
        ))
        # Several enabled cards may refer to one submitted image. Describe each
        # name with that same index without adding another image or rewriting prose.
        named_entries.extend({**entry, "mentionLabel": label} for label in labels)
        if not labels:
            named_entries.append(entry)
    prepared_reference_entries = named_entries
    model_id = str(resolved_config.get("modelId") or (payload.get("videoTaskCard") or {}).get("modelId") or "")
    seedance_25 = (prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT
                   and "seedance-2-5" in model_id.lower())
    if include_asset_reference_prompt:
        asset_reference_prompt = _supplier_official_asset_reference_prompt_from_payload(
            prompt_profile,
            payload,
            reference_images,
            prepared_entries=prepared_reference_entries,
            seedance_image_label="@图片{index}" if seedance_25 else "图片{index}",
        )
    else:
        asset_reference_prompt = ""
    if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT:
        # Keep the card's canonical <asset> bindings. Seedance uses <...> for
        # sound effects, so only unwrap labels that this reference block added.
        reference_labels = {
            _supplier_prompt_one_line(entry.get("mentionLabel") or entry.get("label"))
            for entry in prepared_reference_entries
        } | {"首帧", "尾帧", "视觉交接图"}
        for label in reference_labels:
            if label:
                asset_reference_prompt = asset_reference_prompt.replace(f"<{label}>", label)
    seedance_supplier_meta: dict[str, Any] = {"enabled": False, "skipped": "already_final_provider_prompt"}
    dashscope_meta: dict[str, Any] = {"enabled": False, "skipped": "already_final_provider_prompt"}
    vidu_meta: dict[str, Any] = {"enabled": False, "skipped": "already_final_provider_prompt"}
    grok_meta: dict[str, Any] = {"enabled": False, "skipped": "already_final_provider_prompt"}
    kling_meta: dict[str, Any] = {"enabled": False, "skipped": "already_final_provider_prompt"}
    if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT:
        seedance_supplier_meta = _supplier_official_prepared_prompt_reference_meta(
            prompt_profile,
            prepared_reference_entries,
            asset_reference_prompt=asset_reference_prompt,
        )
        if seedance_25:
            seedance_supplier_meta["referenceLabelStyle"] = "@图片N"
    elif prompt_profile in {FINAL_VIDEO_PROMPT_PROFILE_DASHSCOPE_WAN27_R2V_OFFICIAL, FINAL_VIDEO_PROMPT_PROFILE_HAPPYHORSE_OFFICIAL}:
        dashscope_meta = _supplier_official_prepared_prompt_reference_meta(
            prompt_profile,
            prepared_reference_entries,
            asset_reference_prompt=asset_reference_prompt,
        )
    elif prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_VIDU_Q3_REFERENCE_OFFICIAL:
        vidu_meta = _supplier_official_prepared_prompt_reference_meta(
            prompt_profile,
            prepared_reference_entries,
            asset_reference_prompt=asset_reference_prompt,
        )
    elif prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_GROK_OFFICIAL:
        grok_meta = _supplier_official_prepared_prompt_reference_meta(
            prompt_profile, prepared_reference_entries, asset_reference_prompt=asset_reference_prompt,
        )
    elif prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_KLING_OFFICIAL:
        kling_meta = _supplier_official_prepared_prompt_reference_meta(
            prompt_profile, prepared_reference_entries, asset_reference_prompt=asset_reference_prompt,
        )
    card_prompt = _supplier_shot_labels_from_editor_prompt(
        prompt.strip(), prompt_profile, prompt_timing_style,
    )
    card = payload.get("videoTaskCard") or {}
    sound_prompt = str(card.get("soundPrompt") or "")
    enabled_manifest = payload.get("referenceManifest") or []
    if (payload.get("videoTaskScope") == "work_chain"
            and (payload.get("videoInputPlan") or {}).get("mode") == "native_keyframe"):
        # H3 native frames cannot carry the storyboard/identity image set. Keep
        # validated identity names as text, while rejecting visual-card mentions.
        current_mentions = {}
        for field_text in (card_prompt, sound_prompt):
            current_mentions.update(resolve_prompt_mentions(
                field_text, card.get("promptBindings") or {}, enabled_manifest,
                enabled_manifest=enabled_manifest,
            ))

        def native_identity_name(match: re.Match[str]) -> str:
            row = current_mentions[prompt_reference_label(match)]
            if row.get("kind") != "image":
                return match.group(0)
            slot = str(row.get("slot") or row.get("targetSlot") or "")
            if (slot in {"storyboard_image", "visual_handoff_reference", "frame_reference"}
                    or row.get("mentionKind") in {"storyboard", "visual_handoff", "frame"}):
                raise ValueError("原生首尾帧视频提示词不能引用未传输的分镜图或视觉交接图")
            return str(row.get("mentionLabel") or prompt_reference_label(match))

        card_prompt = PROMPT_REFERENCE_PATTERN.sub(native_identity_name, card_prompt)
        sound_prompt = PROMPT_REFERENCE_PATTERN.sub(native_identity_name, sound_prompt)
    card_prompt = _render_user_asset_mentions(
        card_prompt,
        prompt_profile,
        manifest if isinstance(manifest, list) else [],
        card.get("promptBindings") or {},
        enabled_manifest,
        plain_image_asset_labels=prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT,
    )
    sound_prompt = _render_user_asset_mentions(
        sound_prompt, prompt_profile,
        manifest if isinstance(manifest, list) else [], card.get("promptBindings") or {},
        enabled_manifest,
        plain_image_asset_labels=prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT,
    )
    shot_labels_adapted = card_prompt != prompt.strip()
    if prompt_profile == FINAL_VIDEO_PROMPT_PROFILE_SEEDANCE_OFFICIAL_COMPACT:
        seedance_supplier_meta = {
            **seedance_supplier_meta,
            "visiblePromptPreserved": not shot_labels_adapted,
            "hiddenPromptNormalization": False,
            "taskCardPromptTransformedBeforeSubmit": shot_labels_adapted,
        }
    clean_frame_instruction = VIDEO_REFERENCE_FRAME_INSTRUCTION if reference_images else VIDEO_CLEAN_FRAME_INSTRUCTION
    if any(entry.get("isStoryboard") for entry in prepared_reference_entries):
        clean_frame_instruction = VIDEO_STORYBOARD_EXECUTION_INSTRUCTION + clean_frame_instruction
    boundary_instruction = _video_boundary_reference_instruction(payload, reference_entries)
    final_prompt = _supplier_prompt_join(
        [asset_reference_prompt, clean_frame_instruction, boundary_instruction, sound_prompt, card_prompt]
    )
    final_prompt_chars = len(final_prompt)
    prompt_hard_limit_exceeded = prompt_char_limit > 0 and final_prompt_chars > prompt_char_limit
    if prompt_hard_limit_exceeded:
        raise RuntimeError(
            f"视频生成总提示词当前 {final_prompt_chars} 字符（来自视频生成），"
            f"超过模型上限 {prompt_char_limit} 字符，已阻断。"
        )
    return final_prompt, {
        "limit": prompt_char_limit,
        "finalPromptProfile": prompt_profile,
        "grok": grok_meta,
        "kling": kling_meta,
        "promptTimingStyle": prompt_timing_style,
        "originalCoreChars": original_core_length,
        "finalCoreChars": len(card_prompt),
        "originalFinalPromptChars": final_prompt_chars,
        "finalPromptChars": final_prompt_chars,
        "promptHardLimitChars": prompt_char_limit,
        "promptHardLimitExceeded": prompt_hard_limit_exceeded,
        "finalPromptAlreadyPrepared": True,
        "finalPromptSource": "video_task_card_with_current_asset_references"
        if include_asset_reference_prompt
        else "video_task_card",
        "assetBindingIncluded": bool(asset_reference_prompt),
        "assetReferencePromptChars": len(asset_reference_prompt),
        "assetReferencePromptPrepended": bool(asset_reference_prompt),
        "cleanFrameInstructionPrepended": True,
        "cleanFrameInstructionChars": len(clean_frame_instruction),
        **({"boundaryClauseChars": len(boundary_instruction) + 1} if boundary_instruction else {}),
        "storyboardInterpretationIncluded": False,
        "visualContinuitySupplementIncluded": False,
        "voiceStyleSupplementIncluded": False,
        "editReferenceIncluded": False,
        "productionConstraintIncluded": False,
        "currentEditPrioritized": False,
        "finalPromptReplacement": {"enabled": False, "skipped": "already_final_provider_prompt"},
        "localAssetMentionNormalization": {"enabled": False, "skipped": "already_final_provider_prompt"},
        "seedanceSupplierPromptNormalization": seedance_supplier_meta,
        "dashscopeWanPromptNormalization": dashscope_meta,
        "viduQ3PromptNormalization": vidu_meta,
    }


def _video_prompt_from_generation_payload(
    title: str,
    payload: dict[str, Any],
    resolved_config: dict[str, Any],
    *,
    project_id: str | None = None,
    generate_audio: bool,
    reference_images: list[dict[str, Any]] | None = None,
    prompt_char_limit: int = 0,
    final_prompt_profile: str = "",
    prompt_timing_style: str = "",
    include_asset_reference_prompt: bool = True,
) -> str:
    prompt, _budget = _video_prompt_and_budget_from_generation_payload(
        title,
        payload,
        resolved_config,
        project_id=project_id,
        generate_audio=generate_audio,
        reference_images=reference_images,
        prompt_char_limit=prompt_char_limit,
        final_prompt_profile=final_prompt_profile,
        prompt_timing_style=prompt_timing_style,
        include_asset_reference_prompt=include_asset_reference_prompt,
    )
    return prompt


def _video_source_prompt_from_generation_payload(
    title: str,
    payload: dict[str, Any],
    resolved_config: dict[str, Any],
    *,
    project_id: str | None = None,
    generate_audio: bool,
    reference_images: list[dict[str, Any]] | None = None,
    prompt_char_limit: int = 0,
    final_prompt_profile: str = "",
    prompt_timing_style: str = "",
    include_asset_reference_prompt: bool = True,
) -> str:
    return _video_prompt_from_generation_payload(
        title,
        payload,
        resolved_config,
        project_id=project_id,
        generate_audio=generate_audio,
        reference_images=reference_images,
        prompt_char_limit=prompt_char_limit,
        final_prompt_profile=final_prompt_profile,
        prompt_timing_style=prompt_timing_style,
        include_asset_reference_prompt=include_asset_reference_prompt,
    )


_VIDEO_VOICE_STYLE_REFERENCE_SLOTS = {"character_reference", "creature_reference"}


_VIDEO_VOICE_STYLE_ASSET_COLLECTIONS = ("characters", "creatures")
