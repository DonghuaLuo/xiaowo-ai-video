"""AutoDL's hosted ComfyUI workflows; never submit generation during discovery."""

from __future__ import annotations

import copy
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from utils.temporary_media_storage import ensure_public_url

AUTODL_COMFYUI_BASE_URL = "https://autodl.art/api/v1/comfyui"
AUTODL_H3_WORKFLOWS = {
    "minimax_h3_image_audio_to_video_v2_15s": {
        "title": "H3 多图多音频 · 原版 15秒", "native_frames": False,
        "aspect_ratios": ["16:9", "9:16"], "image_required": False,
    },
    "minimax_h3_lightx2v": {
        "title": "H3 首尾帧", "native_frames": True,
        "aspect_ratios": ["16:9", "9:16", "1:1"], "image_required": True,
    },
    "minimax_h3_zm_u24": {
        "title": "H3 多图多音频 · 升级画质", "native_frames": False,
        "aspect_ratios": ["16:9", "9:16", "1:1"], "image_required": True,
    },
    "minimax_h3_zm_titi": {
        "title": "H3 角色替换 · 单角色", "native_frames": False,
        "aspect_ratios": ["16:9", "9:16"], "image_required": True,
        "character_replace": True, "max_images": 1,
    },
    "minimax_h3_zm_titim": {
        "title": "H3 角色替换 · 多角色", "native_frames": False,
        "aspect_ratios": ["16:9", "9:16"], "image_required": True,
        "character_replace": True, "max_images": 9,
    },
}
_AUTH_PROBE_TASK_ID = "00000000-0000-0000-0000-000000000000"


def autodl_base_url(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    if (parsed.scheme != "https" or parsed.netloc.lower() not in {"autodl.art", "www.autodl.art"}
            or parsed.path.rstrip("/") != "/api/v1/comfyui" or parsed.query or parsed.fragment):
        raise ValueError(f"autodl ComfyUI 请求地址应为 {AUTODL_COMFYUI_BASE_URL}")
    return str(value).strip().rstrip("/")


def _request(provider: dict[str, Any], method: str, url: str, *, data=None, timeout=30):
    from utils.media_backends import _api_key, _request_json
    from utils.preset_provider_probes import _redact_probe

    key = _api_key(provider)
    if not key:
        raise ValueError("请填写 AutoDL API 密钥")
    try:
        # This API takes the token itself, without the Bearer prefix.
        response = _request_json(method, url, headers={"Authorization": key}, data=data, timeout=timeout)
        return _redact_probe(response, key)
    except Exception as exc:
        raise RuntimeError(str(exc).replace(key, "[redacted]")) from None


def _success_data(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict) or response.get("code") != "Success":
        message = str(response.get("msg") or response.get("code") or "返回格式无效") if isinstance(response, dict) else "返回格式无效"
        raise RuntimeError(f"AutoDL：{message.replace(chr(10), ' ')[:200]}")
    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("AutoDL 返回的数据格式无效")
    return data


def probe_autodl_provider(provider: dict[str, Any], *, on_progress=None) -> dict[str, Any]:
    from project_store_services.catalogs import BUILTIN_PROVIDER_MODELS
    from project_store_services.provider_connections import _finalize_provider_capability_result
    from utils.preset_provider_probes import _error_message

    started = time.perf_counter()
    models, probes = [], []
    if on_progress:
        on_progress({"group": "video", "status": "testing", "modelCount": 0})
    try:
        base = autodl_base_url(provider.get("base_url", ""))
        # A nonexistent task gives this known negative response after authentication.
        # Live checked 2026-11-17: an invalid token gives HTTP 401 instead.
        auth = _request(provider, "GET", f"{base}/comfyui_workflow/result/{_AUTH_PROBE_TASK_ID}", timeout=8)
        if not isinstance(auth, dict) or auth.get("code") != "InternalError" or auth.get("msg") != "工作流不可用":
            raise ValueError("AutoDL 只读鉴权响应发生变化，请核对 API 密钥与接口状态")
        probes.append({"name": "auth.read", "status": "ok", "authChecked": True,
                       "entitlementChecked": False, "generationVerified": False})
        catalog = {row["api_model_id"]: row for row in BUILTIN_PROVIDER_MODELS["autodl-comfyui"]}
        for workflow_id, workflow in AUTODL_H3_WORKFLOWS.items():
            detail = _success_data(_request(provider, "GET", f"{base}/workflows/{workflow_id}", timeout=8))
            rules = detail.get("input_rules") or {}
            duration = rules.get("duration") or {}
            prompt = rules.get("prompt") or {}
            options = {row.get("label") for row in (rules.get("resolution") or {}).get("options", [])}
            replace = workflow.get("character_replace", False)
            expected = {f"{resolution}{suffix}" for resolution in (("768p",) if replace else ("480p", "768p"))
                        for ratio, suffix in (("16:9", "横"), ("9:16", "竖"), ("1:1", "(1:1)"))
                        if ratio in workflow["aspect_ratios"]}
            image_fields = (("ref_image",) if workflow.get("max_images") == 1 else tuple(f"ref_image_{i}" for i in range(9))) if replace else (
                ("first_frame", "last_frame") if workflow["native_frames"] else tuple(f"ref_image_{i}" for i in range(9)))
            if (detail.get("uuid") != workflow_id or duration.get("min") != (5 if replace else 1) or duration.get("max") != (25 if replace else 15)
                    or prompt.get("max_length") != (2048 if replace else 20000) or not expected.issubset(options)
                    or any((rules.get(field) or {}).get("type") != "image" for field in image_fields)
                    or (workflow["native_frames"] and not all(rules[field].get("required") for field in image_fields))
                    or (not workflow["native_frames"] and bool(rules[image_fields[0]].get("required")) != workflow["image_required"])
                    or (replace and ((rules.get("ref_video") or {}).get("type") != "video" or not rules["ref_video"].get("required")))):
                raise ValueError(f"AutoDL 工作流 {workflow_id} 的输入契约发生变化，请更新适配")
            models.append({**copy.deepcopy(catalog[workflow_id]), "id": workflow_id,
                           "discovery_source": "official-catalog", "catalog_only": True,
                           "auth_checked": True, "entitlement_checked": False, "generation_verified": False})
        probes.append({"name": "models.list", "status": "ok", "source": "official-catalog",
                       "catalogOnly": True, "authChecked": False, "generationVerified": False})
        result = {"status": "ok", "message": f"已验证密钥并载入 {len(models)} 个工作流，未提交生成",
                  "modelCount": len(models), "modelSource": "preset", "authChecked": True,
                  "entitlementChecked": False, "generationVerified": False}
    except Exception as exc:
        models = []
        message = _error_message(exc, str(provider.get("api_key") or ""))
        probes.append({"name": "models.list", "status": "failed", "error": message})
        result = {"status": "failed", "message": message, "modelCount": 0}
    if on_progress:
        on_progress({"group": "video", "status": result["status"], "modelCount": len(models)})
    return _finalize_provider_capability_result(
        provider, started=started, results={"video": result}, models=models,
        capability_models={"video": [row["api_model_id"] for row in models]}, probes=probes,
        pending_models=[], discovered_models=models,
    )


def _public_image_url(data_url: str) -> str:
    from utils.media_backends import _decode_data_url

    raw, mime = _decode_data_url(data_url)
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(mime)
    if not suffix or not raw:
        raise ValueError("AutoDL 输入图片必须为 JPG、PNG 或 WebP")
    with tempfile.TemporaryDirectory(prefix="ai-video-autodl-") as directory:
        path = Path(directory) / ("reference" + suffix)
        path.write_bytes(raw)
        remote = ensure_public_url(path, "image")
    url = str(remote.get("url") or "")
    if urlsplit(url).scheme not in {"http", "https"}:
        raise RuntimeError("AutoDL 参考图片上传未返回可访问地址")
    return url


def submit_autodl_video(provider, base_url, model_name, prompt, reference_image, *,
                        reference_images=None, reference_videos=None, strategy="", aspect_ratio,
                        resolution, duration_seconds, generate_audio=True, replacement_subject="person", on_request_prepared=None):
    from utils import media_backends as media
    from utils.frame_references import select_frame_transport, is_frame_image
    from utils.video_model_capabilities import video_model_capability

    base = autodl_base_url(base_url)
    workflow = AUTODL_H3_WORKFLOWS.get(model_name)
    if not workflow:
        raise ValueError("当前 AutoDL 工作流尚未适配")
    spec = video_model_capability(model_name)
    replace = workflow.get("character_replace", False)
    if replace != (strategy == "character_replace_video"):
        raise ValueError("角色替换工作流仅用于角色替换视频任务，请选择匹配的工作流和任务卡")
    resolution = str(resolution).lower()
    if resolution not in spec["resolutions"] or duration_seconds not in spec["durations"]:
        raise ValueError("角色替换仅支持 768p、5–25 秒" if replace else "AutoDL H3 仅支持 480p/768p、1–15 秒")
    if aspect_ratio not in spec["aspect_ratios"]:
        raise ValueError("当前 AutoDL 工作流不支持所选画幅")
    if replace and len(prompt) > 2048:
        raise ValueError("角色替换说明不能超过 2048 字符")
    if not replace and (not prompt.strip() or len(prompt) > 20000):
        raise ValueError("AutoDL H3 提示词不能为空且不能超过 20000 字符")
    if reference_videos and not replace:
        raise ValueError("当前 AutoDL 工作流不支持参考视频")
    if replace:
        rows = reference_images or ([reference_image] if reference_image else [])
        if not 1 <= len(rows) <= workflow["max_images"]:
            raise ValueError(f"当前角色替换模式需要 1–{workflow['max_images']} 张角色图")
        if any(is_frame_image(row) for row in rows):
            raise ValueError("角色替换不能使用首尾帧输入")
        if len(reference_videos or []) != 1:
            raise ValueError("角色替换必须关联且只能关联一段源视频")
        from utils.video_references import validate_reference_videos
        validate_reference_videos(reference_videos, model_name, image_count=len(rows), output_duration=duration_seconds)
        video_url = str(reference_videos[0].get("videoUrl") or reference_videos[0].get("url") or "")
        if urlsplit(video_url).scheme not in {"http", "https"}:
            raise ValueError("角色替换源视频缺少可访问地址")
        replacement_subject = str(replacement_subject or "person").strip()
        if len(replacement_subject) > 100:
            raise ValueError("替换对象不能超过 100 字符")
    native = strategy == "native_keyframe_video"
    if native != workflow["native_frames"]:
        raise ValueError("请为首尾帧任务选择 AutoDL H3 首尾帧工作流，为多图任务选择多图工作流")
    rows = reference_images or ([reference_image] if reference_image else [])
    if rows or native or workflow["image_required"]:
        select_frame_transport(rows, spec, native_required=native, reference_video_count=len(reference_videos or []))
    roles = media._video_image_role_urls(reference_image, reference_images, model_name,
                                        native_required=native, capability=spec)
    images = {"content": [{"type": "image_url", "image_url": {"url": url}, "role": role} for role, url in roles]}
    preparation = media.prepare_video_request_images(images, model_name, capability=spec)
    suffix = {"16:9": "横", "9:16": "竖", "1:1": "(1:1)"}[aspect_ratio]
    body = {"prompt": (prompt.strip() or " ") if replace else prompt, "duration": duration_seconds, "resolution": resolution + suffix}
    if replace:
        body["ref_video"] = video_url
        if workflow["max_images"] > 1:
            body["video_subject_to_replace"] = replacement_subject
    else:
        body["seed"] = secrets.randbelow(999999999999999) + 1
    for index, image in enumerate(images["content"]):
        field = image["role"] if native else "ref_image" if replace and workflow["max_images"] == 1 else f"ref_image_{index}"
        body[field] = _public_image_url(image["image_url"]["url"])
    url = f"{base}/comfyui_workflow/{model_name}"
    media._notify_request_prepared(on_request_prepared, {
        "provider": "autodl-comfyui", "transport": "http", "method": "POST", "url": url,
        "requestBody": body, "imagePreparation": preparation,
        "mediaReferences": media._reference_media_log_rows(reference_image, reference_images, media_type="image"),
    })
    try:
        created = _request(provider, "POST", url, data=body, timeout=media.MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    except Exception as exc:
        if str(exc).startswith("HTTP 4"):
            raise
        raise RuntimeError("AutoDL 视频提交结果未确认，请核对供应商任务记录，勿直接重试") from exc
    data = _success_data(created)
    task_id = str(data.get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError("AutoDL 视频提交未返回任务 ID，请核对供应商任务记录，勿重复提交")
    return media.MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug={
        "backend": "autodl-comfyui", "workflowId": model_name, "taskId": task_id,
        "request": body, "imagePreparation": preparation,
    })


def poll_autodl_video(provider, base_url, task_id):
    from utils import media_backends as media

    base = autodl_base_url(base_url)
    response = _request(provider, "GET", f"{base}/comfyui_workflow/result/{quote(task_id, safe='')}",
                        timeout=media.MODEL_MEDIA_REQUEST_TIMEOUT_SECONDS)
    data = _success_data(response)
    status = str(data.get("status") or "").lower()
    debug = {"backend": "autodl-comfyui", "taskId": task_id, "response": response}
    if status in {"queued", "pending", "running", "processing"}:
        return media.MediaGenerationResponse(raw=None, status="processing", job_id=task_id, debug=debug)
    if status in {"failed", "cancelled", "canceled", "expired"}:
        raise RuntimeError("AutoDL 视频生成失败：" + str(data.get("message") or data.get("error") or status)[:200])
    if status not in {"success", "completed"}:
        raise RuntimeError("AutoDL 视频查询返回了无法识别的任务状态")
    results = data.get("results") or []
    url = next((str(row.get("url") or "") for row in results
                if isinstance(row, dict) and row.get("type") == "video"), "")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError("AutoDL 视频任务已完成，但未返回有效的视频地址")
    # Result URLs expire after 24 hours; persist bytes through the normal job lifecycle.
    raw = media._download_url(url, timeout=media.MODEL_MEDIA_DOWNLOAD_TIMEOUT_SECONDS)
    if not raw:
        raise RuntimeError("AutoDL 视频下载结果为空")
    return media.MediaGenerationResponse(raw=raw, status="completed", job_id=task_id, debug=debug)
