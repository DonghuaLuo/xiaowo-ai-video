# -*- coding: utf-8 -*-
"""参考素材身份解析、项目素材读取与供应商传输媒体准备。"""
from __future__ import annotations

from .agent_sessions import _project_file_from_ref
from .catalogs import PROJECTS_DIR
from .canvas_store_queries import (
    read_canvas_reference_versions_by_ids_v4,
)
from .canvas_store_queries import (
    read_card_results,
)
from .canvas_store_queries import (
    read_episode_card_results,
)
from .media_files import _decode_data_url
from .media_files import _local_image_source_from_media
from .media_files import _local_video_source_from_media
from .media_files import video_media_metadata
from .media_files import original_reference_video_media
from .perf_logging import canvas_perf_elapsed_ms
from .perf_logging import canvas_perf_log
from .perf_logging import canvas_perf_start
from .reference_utils import workflow_media_identity_values as _workflow_media_identity_values
from .store_core import ASSET_LIFECYCLE_ACTIVE
from .storyboard_templates import storyboard_image_prompt_spec
from pathlib import Path
from typing import Any
from utils.image_pipeline import PROVIDER_IMAGE_INPUT_DEFAULT_MAX_BYTES
from utils.image_pipeline import PROVIDER_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE
from utils.image_pipeline import prepare_provider_image_data_uri
from utils.temporary_media_storage import ensure_public_url
from utils.video_references import prepare_reference_video
from utils.video_references import reference_video_limits
from utils.video_references import validate_reference_video_durations
from utils.video_references import validate_reference_videos
import base64
import copy
import urllib.error
import urllib.parse
import urllib.request

from .media_files import _source_image_data_url


def _data_url_base64_payload(data_url: str) -> tuple[str, str]:
    raw, mime = _decode_data_url(data_url)
    return base64.b64encode(raw).decode("ascii"), mime






def _provider_reference_prepare_kwargs(image_input_limits: dict[str, Any] | None) -> dict[str, int]:
    kwargs: dict[str, int] = {
        "max_long_edge": PROVIDER_IMAGE_INPUT_DEFAULT_MAX_LONG_EDGE,
        "max_bytes": PROVIDER_IMAGE_INPUT_DEFAULT_MAX_BYTES,
    }
    if not isinstance(image_input_limits, dict):
        return kwargs
    if image_input_limits.get("defer_video_preparation"):
        return {"defer_video_preparation": True}
    for source_key, target_key in (
        ("max_long_edge", "max_long_edge"),
        ("max_bytes", "max_bytes"),
    ):
        try:
            value = int(image_input_limits.get(source_key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            kwargs[target_key] = value
    return kwargs


def _provider_image_data_url_from_data_url(
    data_url: str,
    *,
    purpose: str,
    image_input_limits: dict[str, Any] | None = None,
) -> str:
    if not str(data_url or "").startswith("data:image/"):
        return ""
    raw, _mime = _decode_data_url(data_url)
    return prepare_provider_image_data_uri(
        raw,
        purpose=purpose,
        preserve_alpha=True,
        **_provider_reference_prepare_kwargs(image_input_limits),
    )


def _provider_image_data_url_from_file_info(
    project_id: str | None,
    file_info: dict[str, Any],
    *,
    purpose: str,
    image_input_limits: dict[str, Any] | None = None,
) -> str:
    if not isinstance(file_info, dict):
        return ""
    prepare_kwargs = _provider_reference_prepare_kwargs(image_input_limits)
    path = _project_file_from_ref(project_id, file_info)
    if path and path.is_file():
        return prepare_provider_image_data_uri(
            path,
            purpose=purpose,
            preserve_alpha=True,
            **prepare_kwargs,
        )
    local_source = _local_image_source_from_media(file_info)
    if local_source:
        source_path, _source_mime = local_source
        return prepare_provider_image_data_uri(
            source_path,
            purpose=purpose,
            preserve_alpha=True,
            **prepare_kwargs,
        )
    data_url = _source_image_data_url(file_info)
    if data_url.startswith("data:image/"):
        return _provider_image_data_url_from_data_url(
            data_url,
            purpose=purpose,
            image_input_limits=image_input_limits,
        )
    return ""


def _provider_model_input_images(
    input_images: list[str] | None,
    *,
    purpose: str,
    image_input_limits: dict[str, Any] | None = None,
) -> list[str]:
    rows: list[str] = []
    for index, data_url in enumerate(input_images or []):
        prepared = _provider_image_data_url_from_data_url(
            str(data_url or "").strip(),
            purpose=f"{purpose}-{index + 1}",
            image_input_limits=image_input_limits,
        )
        if prepared:
            rows.append(prepared)
    return rows


def _provider_reference_file_id_from_fields(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in _PROVIDER_REFERENCE_FILE_ID_KEYS:
        text = str(value.get(key) or "").strip()
        if text:
            return text
    for key in ("fileId", "file_id"):
        text = str(value.get(key) or "").strip()
        if text.startswith("file-"):
            return text
    return ""


def _provider_reference_file_id_from_value(value: Any, *, _depth: int = 0) -> str:
    if _depth > 5:
        return ""
    if isinstance(value, dict):
        direct = _provider_reference_file_id_from_fields(value)
        if direct:
            return direct
        for item in value.values():
            found = _provider_reference_file_id_from_value(item, _depth=_depth + 1)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _provider_reference_file_id_from_value(item, _depth=_depth + 1)
            if found:
                return found
    return ""


def _provider_media_reference_suffix(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    candidate = parsed.path or text
    return Path(candidate).suffix.lower()


def _provider_media_reference_is_video(media: dict[str, Any] | None) -> bool:
    if not isinstance(media, dict):
        return False
    for key in (
        "kind",
        "mediaKind",
        "media_kind",
        "mediaType",
        "media_type",
        "assetKind",
        "asset_kind",
        "assetType",
        "asset_type",
    ):
        text = str(media.get(key) or "").strip().casefold()
        if text in {"video", "generated_video", "video.result", "storyboard_video"}:
            return True
    mime_type = str(media.get("mimeType") or media.get("mime_type") or "").strip().casefold()
    if mime_type.startswith("video/"):
        return True
    data_url = str(media.get("dataUrl") or "").strip().casefold()
    if data_url.startswith("data:video/"):
        return True
    for key in (
        "name",
        "originalName",
        "original_name",
        "fileName",
        "file_name",
        "filePath",
        "file_path",
        "path",
        "relativePath",
        "relative_path",
        "url",
    ):
        text = str(media.get(key) or "").strip()
        if text and _provider_media_reference_suffix(text) in _VIDEO_REFERENCE_FILE_SUFFIXES:
            return True
    return False


def _provider_media_reference_http_url(media: dict[str, Any] | None) -> str:
    if not isinstance(media, dict):
        return ""
    for key in ("url", "videoUrl", "video_url", "downloadUrl", "download_url"):
        text = str(media.get(key) or "").strip()
        if not text:
            continue
        parsed = urllib.parse.urlparse(text)
        if parsed.scheme in {"http", "https"}:
            return text
    return ""


def _provider_reference_image_metadata_only(
    source: dict[str, Any] | None,
    *,
    fallback_source: str = "",
    index: int | None = None,
) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    reference: dict[str, Any] = {
        "providerPrepared": False,
        "metadataOnly": True,
    }
    if fallback_source:
        reference["source"] = fallback_source
    if index is not None:
        reference["index"] = index
    for key in (
        "id",
        "mediaId",
        "media_id",
        "versionId",
        "version_id",
        "assetId",
        "asset_id",
        "assetType",
        "asset_type",
        "source",
        "sourceNodeId",
        "source_node_id",
        "role",
        "referenceRole",
        "reference_role",
        "purpose",
        "slot",
        "sourceType",
        "source_type",
        "label",
        "caption",
        "displayName",
        "display_name",
        "name",
        "title",
        "mimeType",
        "mime_type",
        "storyboardPromptSpec",
        "panelCount",
        "nodeType",
        "sourceNodeType",
    ):
        value = source.get(key)
        if value not in (None, ""):
            reference[key] = copy.deepcopy(value)
    if source.get("id") and "mediaId" not in reference:
        reference["mediaId"] = source.get("id")
    if source.get("media_id") and "mediaId" not in reference:
        reference["mediaId"] = source.get("media_id")
    if source.get("version_id") and "versionId" not in reference:
        reference["versionId"] = source.get("version_id")
    if source.get("asset_id") and "assetId" not in reference:
        reference["assetId"] = source.get("asset_id")
    if source.get("asset_type") and "assetType" not in reference:
        reference["assetType"] = source.get("asset_type")
    if source.get("mime_type") and "mimeType" not in reference:
        reference["mimeType"] = source.get("mime_type")
    provider_file_id = _provider_reference_file_id_from_value(source)
    if provider_file_id:
        reference["providerFileId"] = provider_file_id
    if set(reference.keys()) <= {"providerPrepared", "metadataOnly"}:
        return None
    return reference


def _provider_reference_image_from_storyboard_version(
    project_id: str,
    selected: dict[str, Any],
    *,
    purpose: str,
    image_input_limits: dict[str, Any] | None = None,
    prepare_transport_media: bool = True,
) -> dict[str, Any] | None:
    media = selected.get("media") if isinstance(selected.get("media"), dict) else {}
    if _provider_media_reference_is_video(media):
        return None
    payload = selected.get("payload") if isinstance(selected.get("payload"), dict) else {}
    custom_image_fields = {"assetType": "custom_image", "mediaPurpose": "custom_image", "slot": "custom_image"} if payload.get("assetType") == "custom_image" else {}
    reference = _provider_reference_image_from_media(
        project_id,
        media,
        purpose=purpose,
        image_input_limits=image_input_limits,
        prepare_transport_media=prepare_transport_media,
    )
    if reference:
        reference.update(custom_image_fields)
        reference["versionId"] = selected.get("id")
        reference["nodeId"] = selected.get("nodeId")
        reference["mediaId"] = media.get("id")
        reference["source"] = "storyboard_version"
        provider_file_id = _provider_reference_file_id_from_value(media) or _provider_reference_file_id_from_fields(selected)
        if provider_file_id:
            reference["providerFileId"] = provider_file_id
        if isinstance(payload.get("storyboardPromptSpec"), dict):
            reference["storyboardPromptSpec"] = payload.get("storyboardPromptSpec")
        if payload.get("panelCount") not in (None, ""):
            reference["panelCount"] = payload.get("panelCount")
        return reference
    preview = selected.get("preview")
    if not prepare_transport_media:
        reference = _provider_reference_image_metadata_only(
            {
                **media,
                **custom_image_fields,
                "versionId": selected.get("id"),
                "nodeId": selected.get("nodeId"),
                "source": "storyboard_version",
                "storyboardPromptSpec": payload.get("storyboardPromptSpec")
                if isinstance(payload.get("storyboardPromptSpec"), dict)
                else None,
                "panelCount": payload.get("panelCount"),
            },
            fallback_source="storyboard_version",
        )
        if reference:
            provider_file_id = _provider_reference_file_id_from_fields(selected)
            if provider_file_id:
                reference["providerFileId"] = provider_file_id
            return reference
    if isinstance(preview, str) and preview.startswith("data:image/"):
        raw, _mime = _decode_data_url(preview)
        data_url = prepare_provider_image_data_uri(
            raw,
            purpose=purpose,
            preserve_alpha=True,
            **_provider_reference_prepare_kwargs(image_input_limits),
        )
        _raw, mime = _decode_data_url(data_url)
        reference = {
            **custom_image_fields,
            "versionId": selected.get("id"),
            "nodeId": selected.get("nodeId"),
            "source": "storyboard_version",
            "dataUrl": data_url,
            "mimeType": mime,
            "providerPrepared": True,
            "storyboardPromptSpec": payload.get("storyboardPromptSpec") if isinstance(payload.get("storyboardPromptSpec"), dict) else None,
            "panelCount": payload.get("panelCount"),
        }
        provider_file_id = _provider_reference_file_id_from_fields(selected)
        if provider_file_id:
            reference["providerFileId"] = provider_file_id
        return reference
    provider_file_id = _provider_reference_file_id_from_value(media) or _provider_reference_file_id_from_fields(selected)
    if provider_file_id:
        return {
            **custom_image_fields,
            "versionId": selected.get("id"),
            "nodeId": selected.get("nodeId"),
            "mediaId": media.get("id"),
            "source": "storyboard_version",
            "providerFileId": provider_file_id,
            "providerPrepared": True,
            "mimeType": media.get("mimeType") or media.get("mime_type"),
            "storyboardPromptSpec": copy.deepcopy(payload.get("storyboardPromptSpec") or {}),
        }
    return None


def _extract_storyboard_reference_image(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    *,
    node_id: str | None = None,
    route_id: str | None = None,
    image_input_limits: dict[str, Any] | None = None,
    prepare_transport_media: bool = True,
) -> dict[str, Any] | None:
    from .workflow_input_resolution import _workflow_node_data
    from .workflow_storyboard_versions import list_storyboard_versions
    from .workflow_input_resolution import workflow_current_media_reference
    from .workflow_input_resolution import workflow_storyboard_reference_node_ids

    image_node_ids = workflow_storyboard_reference_node_ids(
        workflow,
        node_id=node_id,
        route_id=route_id,
    )
    for image_node_id in image_node_ids:
        image_node = _workflow_node_data(workflow, image_node_id)
        if image_node.get("mediaPurpose") and image_node["mediaPurpose"] != "storyboard_image":
            continue
        active_id = str(
            image_node.get("activeVersionId")
            or image_node.get("activeMediaVersionId")
            or image_node.get("mediaVersionId")
            or ""
        ).strip()
        versions = list_storyboard_versions(project_id, episode_id, image_node_id).get("versions", [])
        selected = next(
            (item for item in versions if isinstance(item, dict) and str(item.get("id") or "") == active_id),
            None,
        )
        if isinstance(selected, dict):
            reference = _provider_reference_image_from_storyboard_version(
                project_id,
                selected,
                purpose="storyboard-video-reference",
                image_input_limits=image_input_limits,
                prepare_transport_media=prepare_transport_media,
            )
        else:
            current_media = workflow_current_media_reference(
                project_id,
                episode_id,
                workflow,
                image_node_id,
            )
            reference = _provider_reference_image_from_media(
                project_id,
                current_media,
                purpose="storyboard-video-reference",
                image_input_limits=image_input_limits,
                prepare_transport_media=prepare_transport_media,
            )
        if reference:
            reference["storyboardPromptSpec"] = storyboard_image_prompt_spec(
                image_node.get("media") or image_node.get("storage"), selected,
            )
            _apply_canvas_reference_category(reference, {"data": image_node})
            reference["nodeId"] = image_node_id
            reference["sourceNodeId"] = image_node_id
            if active_id:
                reference.setdefault("versionId", active_id)
            return reference
    return None


def _provider_reference_image_from_media(
    project_id: str | None,
    media: dict[str, Any] | None,
    *,
    purpose: str,
    image_input_limits: dict[str, Any] | None = None,
    prepare_transport_media: bool = True,
) -> dict[str, Any] | None:
    if not isinstance(media, dict):
        return None
    if _provider_media_reference_is_video(media):
        return None
    if not prepare_transport_media:
        return _provider_reference_image_metadata_only(media)
    data_url = _provider_image_data_url_from_file_info(
        project_id,
        media,
        purpose=purpose,
        image_input_limits=image_input_limits,
    )
    if data_url:
        _raw, mime = _decode_data_url(data_url)
        reference = {"dataUrl": data_url, "mimeType": mime, "providerPrepared": True}
        spec = storyboard_image_prompt_spec(media)
        if spec:
            reference["storyboardPromptSpec"] = spec
        provider_file_id = _provider_reference_file_id_from_value(media)
        if provider_file_id:
            reference["providerFileId"] = provider_file_id
        return reference
    return None


def _reference_identity_values(value: dict[str, Any] | None) -> set[str]:
    if not isinstance(value, dict):
        return set()
    keys = (
        "id",
        "nodeId",
        "node_id",
        "linkId",
        "link_id",
        "inputLinkId",
        "input_link_id",
        "sourceNodeId",
        "source_node_id",
        "rootAssetId",
        "assetId",
        "mediaVersionId",
        "media_version_id",
        "sourceVersionId",
        "source_version_id",
        "versionId",
        "version_id",
        "mediaId",
        "media_id",
        "relativePath",
        "relative_path",
        "file",
        "filePath",
        "file_path",
        "path",
    )
    return {str(value.get(key) or "").strip() for key in keys if str(value.get(key) or "").strip()}


def _truthy_reference_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _asset_refs_resolved_by_input_links_for_provider(*sources: Any) -> bool:
    for source in sources:
        if not isinstance(source, dict):
            continue
        if _truthy_reference_flag(source.get("assetRefsResolvedByInputLinks")):
            return True
        for key in ("resolvedConfig", "generationConfig", "videoTaskCard", "storyboardTaskCard", "directorTaskCard"):
            nested = source.get(key)
            if isinstance(nested, dict) and _asset_refs_resolved_by_input_links_for_provider(nested):
                return True
    return False


def _active_asset_media_candidate(item: dict[str, Any]) -> dict[str, Any] | None:
    versions = item.get("mediaVersions") if isinstance(item.get("mediaVersions"), list) else []
    active_id = str(item.get("activeMediaVersionId") or "").strip()
    selected = next(
        (
            version
            for version in versions
            if isinstance(version, dict) and active_id and str(version.get("id") or "") == active_id
        ),
        None,
    )
    if isinstance(selected, dict) and isinstance(selected.get("media"), dict):
        return selected["media"]
    return None


def _provider_reference_resolution_context(
    project_id: str,
    episode_id: str,
    *,
    workflow_projection: dict[str, Any] | None = None,
    reference_ids: list[str] | set[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    context_started_at = canvas_perf_start()
    status = "ok"
    workflow_read_ms = 0.0
    card_results_ms = 0.0
    asset_scan_ms = 0.0
    workflow: dict[str, Any] = workflow_projection if isinstance(workflow_projection, dict) else {}
    workflow_reused = isinstance(workflow_projection, dict)
    active_storyboard_version_ids: set[str] = set()
    active_storyboard_card_ids: set[str] = set()
    card_results: list[dict[str, Any]] = []
    seen_card_result_keys: set[tuple[str, str]] = set()
    normalized_reference_ids = {
        str(reference_id or "").strip()
        for reference_id in (reference_ids if isinstance(reference_ids, (list, set, tuple)) else [])
        if str(reference_id or "").strip()
    }
    assets: dict[str, Any] = {}
    asset_count = 0
    try:
        if not workflow_reused:
            from .workflow_projection import get_canvas_workflow_projection

            workflow_started_at = canvas_perf_start()
            workflow = get_canvas_workflow_projection(project_id, episode_id)
            workflow_read_ms = canvas_perf_elapsed_ms(workflow_started_at)
        for node in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or node.get("nodeId") or "").strip()
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            version_id = str(
                data.get("activeVersionId")
                or data.get("activeMediaVersionId")
                or data.get("mediaVersionId")
                or ""
            ).strip()
            if version_id:
                active_storyboard_version_ids.add(version_id)
                if node_id:
                    active_storyboard_card_ids.add(node_id)

        card_results_started_at = canvas_perf_start()
        if active_storyboard_card_ids:
            for card_id in sorted(active_storyboard_card_ids):
                for version in read_card_results(project_id, episode_id, card_id):
                    if not isinstance(version, dict):
                        continue
                    key = (str(version.get("nodeId") or card_id), str(version.get("id") or ""))
                    if key in seen_card_result_keys:
                        continue
                    seen_card_result_keys.add(key)
                    card_results.append(version)
        elif not workflow_reused and not normalized_reference_ids:
            card_results = read_episode_card_results(project_id, episode_id)
            seen_card_result_keys.update(
                (str(version.get("nodeId") or ""), str(version.get("id") or ""))
                for version in card_results
                if isinstance(version, dict)
            )
        if normalized_reference_ids:
            for version in read_canvas_reference_versions_by_ids_v4(project_id, episode_id, normalized_reference_ids):
                if not isinstance(version, dict):
                    continue
                version_id = str(version.get("id") or "").strip()
                key = (str(version.get("nodeId") or ""), version_id)
                if key not in seen_card_result_keys:
                    seen_card_result_keys.add(key)
                    card_results.append(version)
                if version_id:
                    active_storyboard_version_ids.add(version_id)
        card_results_ms = canvas_perf_elapsed_ms(card_results_started_at)

        workflow_node_count = len(workflow.get("nodes")) if isinstance(workflow.get("nodes"), list) else 0
        card_result_count = len(card_results) if isinstance(card_results, list) else 0
        return {
            "workflow": workflow,
            "activeStoryboardVersionIds": active_storyboard_version_ids,
            "cardResults": card_results,
            "assets": assets,
            "assetsLoaded": False,
            "workflowReadMs": workflow_read_ms,
            "workflowNodeCount": workflow_node_count,
            "cardResultsMs": card_results_ms,
            "cardResultCount": card_result_count,
            "assetScanMs": asset_scan_ms,
            "assetCount": asset_count,
            "workflowReused": workflow_reused,
            "activeCardCount": len(active_storyboard_card_ids),
            "referenceIdCount": len(normalized_reference_ids),
        }
    except Exception:
        status = "error"
        raise
    finally:
        workflow_node_count = len(workflow.get("nodes")) if isinstance(workflow.get("nodes"), list) else 0
        card_result_count = len(card_results) if isinstance(card_results, list) else 0
        canvas_perf_log(
            "provider_reference_resolution_context",
            projectId=project_id,
            episodeId=episode_id,
            status=status,
            durationMs=canvas_perf_elapsed_ms(context_started_at),
            workflowReadMs=workflow_read_ms,
            workflowNodeCount=workflow_node_count,
            cardResultsMs=card_results_ms,
            cardResultCount=card_result_count,
            assetScanMs=asset_scan_ms,
            assetCount=asset_count,
            assetsLoaded=False,
            workflowReused=workflow_reused,
            activeCardCount=len(active_storyboard_card_ids),
            referenceIdCount=len(normalized_reference_ids),
        )


def _provider_reference_assets_from_context(
    project_id: str,
    episode_id: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    from .assets import list_assets

    assets = context.get("assets") if isinstance(context.get("assets"), dict) else {}
    if context.get("assetsLoaded") is True:
        return assets
    perf_started_at = canvas_perf_start()
    status = "ok"
    asset_count = 0
    try:
        assets = list_assets("project", project_id, hydrate=False, lifecycle_status=ASSET_LIFECYCLE_ACTIVE)
        if isinstance(assets, dict):
            for asset_type in ("characters", "creatures", "scenes", "props", "styles"):
                rows = assets.get(asset_type)
                if isinstance(rows, list):
                    asset_count += len(rows)
        context["assets"] = assets if isinstance(assets, dict) else {}
        context["assetsLoaded"] = True
        context["assetScanMs"] = canvas_perf_elapsed_ms(perf_started_at)
        context["assetCount"] = asset_count
        return context["assets"]
    except Exception:
        status = "error"
        raise
    finally:
        canvas_perf_log(
            "provider_reference_assets_lazy_load",
            projectId=project_id,
            episodeId=episode_id,
            status=status,
            durationMs=canvas_perf_elapsed_ms(perf_started_at),
            assetCount=asset_count,
        )


def _apply_canvas_reference_category(reference: dict[str, Any], node: dict[str, Any]) -> None:
    """卡片当前用途优先于历史生成版本的资产类别。"""
    data = node.get("data") or {}
    purpose = data.get("mediaPurpose")
    if purpose:
        reference["mediaPurpose"] = purpose
        reference["slot"] = data.get("preferredTargetSlot") or purpose
        reference["assetType"] = data.get("assetType") or purpose


def _provider_reference_image_by_id(
    project_id: str,
    episode_id: str,
    reference_id: str,
    *,
    purpose: str,
    image_input_limits: dict[str, Any] | None = None,
    prepare_transport_media: bool = True,
    resolution_context: dict[str, Any] | None = None,
    allow_asset_library_lookup: bool = True,
) -> dict[str, Any] | None:
    reference_id = str(reference_id or "").strip()
    if not reference_id:
        return None
    perf_started_at = canvas_perf_start()
    status = "not_found"
    source = ""
    workflow_read_ms = 0.0
    card_results_ms = 0.0
    asset_scan_ms = 0.0
    workflow_node_count = 0
    card_result_count = 0
    asset_count = 0
    context_reused = isinstance(resolution_context, dict)

    try:
        context = (
            resolution_context
            if isinstance(resolution_context, dict)
            else _provider_reference_resolution_context(project_id, episode_id)
        )
        workflow = context.get("workflow") if isinstance(context.get("workflow"), dict) else {}
        active_storyboard_version_ids = (
            context.get("activeStoryboardVersionIds")
            if isinstance(context.get("activeStoryboardVersionIds"), set)
            else set()
        )
        card_results = context.get("cardResults") if isinstance(context.get("cardResults"), list) else []
        assets: dict[str, Any] = {}
        workflow_read_ms = float(context.get("workflowReadMs") or 0.0)
        workflow_node_count = int(context.get("workflowNodeCount") or 0)
        card_results_ms = float(context.get("cardResultsMs") or 0.0)
        card_result_count = int(context.get("cardResultCount") or len(card_results))
        asset_scan_ms = float(context.get("assetScanMs") or 0.0)
        asset_count = int(context.get("assetCount") or 0)
        for version in card_results:
            version_id = str(version.get("id") or "").strip()
            if not version_id or version_id not in active_storyboard_version_ids:
                continue
            media = version.get("media") if isinstance(version.get("media"), dict) else {}
            identities = _reference_identity_values(version) | _reference_identity_values(media)
            if reference_id not in identities:
                continue
            reference = _provider_reference_image_from_storyboard_version(
                project_id,
                version,
                purpose=purpose,
                image_input_limits=image_input_limits,
                prepare_transport_media=prepare_transport_media,
            )
            if reference:
                status = "found"
                source = "storyboard_version"
                source_node_id = str(version.get("nodeId") or "").strip()
                if source_node_id:
                    reference["sourceNodeId"] = source_node_id
                    for workflow_node in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
                        if not isinstance(workflow_node, dict):
                            continue
                        if str(workflow_node.get("id") or workflow_node.get("nodeId") or "").strip() != source_node_id:
                            continue
                        node_data = workflow_node.get("data") or {}
                        reference["storyboardPromptSpec"] = storyboard_image_prompt_spec(
                            node_data.get("media") or node_data.get("storage"), version,
                        )
                        source_node_type = str(workflow_node.get("type") or "").strip()
                        if source_node_type:
                            reference["sourceNodeType"] = source_node_type
                            reference["nodeType"] = source_node_type
                        if source_node_type == "storyboard.image":
                            reference.setdefault("assetType", "storyboard")
                            reference.setdefault("sourceType", "storyboard_image")
                            reference.setdefault("slot", "storyboard_image")
                            reference.setdefault("referenceRole", "storyboard_image")
                        _apply_canvas_reference_category(reference, workflow_node)
                        break
                reference["requestedReferenceId"] = reference_id
                return reference

        for node in (workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []):
            if not isinstance(node, dict) or str(node.get("type") or "").strip() != "storyboard.image":
                continue
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            media = data.get("media") if isinstance(data.get("media"), dict) else data.get("storage")
            if not isinstance(media, dict):
                continue
            identities = _workflow_media_identity_values(node, data, media)
            if reference_id not in identities:
                continue
            reference = _provider_reference_image_from_media(
                project_id,
                media,
                purpose=purpose,
                image_input_limits=image_input_limits,
                prepare_transport_media=prepare_transport_media,
            )
            if reference:
                status = "found"
                source = "workflow_storyboard_media"
                reference["requestedReferenceId"] = reference_id
                reference["mediaId"] = media.get("id") or data.get("mediaId") or data.get("media_id")
                reference["source"] = "workflow_storyboard_media"
                reference["sourceNodeId"] = node.get("id") or node.get("nodeId")
                reference["sourceNodeType"] = "storyboard.image"
                reference["nodeType"] = "storyboard.image"
                reference["assetType"] = "storyboard"
                reference["sourceType"] = "storyboard_image"
                reference["slot"] = "storyboard_image"
                reference["referenceRole"] = "storyboard_image"
                _apply_canvas_reference_category(reference, node)
                return reference

        for node in (workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []):
            if not isinstance(node, dict) or str(node.get("type") or "").strip() != "media.external":
                continue
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            media = data.get("media") if isinstance(data.get("media"), dict) else data.get("storage")
            if not isinstance(media, dict):
                continue
            identities = _workflow_media_identity_values(node, data, media)
            if reference_id not in identities:
                continue
            reference = _provider_reference_image_from_media(
                project_id,
                media,
                purpose=purpose,
                image_input_limits=image_input_limits,
                prepare_transport_media=prepare_transport_media,
            )
            if reference:
                status = "found"
                source = "workflow_media"
                reference["requestedReferenceId"] = reference_id
                reference["mediaId"] = media.get("id") or data.get("mediaId")
                reference["source"] = "workflow_media"
                reference["sourceNodeId"] = node.get("id")
                reference["slot"] = data.get("preferredTargetSlot") or data.get("mediaPurpose")
                reference["mediaPurpose"] = data.get("mediaPurpose")
                if data.get("mediaPurpose") == "custom_image":
                    reference["assetType"] = "custom_image"
                return reference

        for node in (workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []):
            if not isinstance(node, dict) or str(node.get("type") or "").strip() != "asset.image":
                continue
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            media = data.get("media") if isinstance(data.get("media"), dict) else data.get("storage")
            if not isinstance(media, dict):
                continue
            identities = _workflow_media_identity_values(node, data, media)
            if reference_id not in identities:
                continue
            reference = _provider_reference_image_from_media(
                project_id,
                media,
                purpose=purpose,
                image_input_limits=image_input_limits,
                prepare_transport_media=prepare_transport_media,
            )
            if reference:
                status = "found"
                source = "workflow_asset_node"
                reference["requestedReferenceId"] = reference_id
                reference["mediaId"] = media.get("id") or data.get("mediaId") or data.get("media_id")
                reference["source"] = "workflow_asset_node"
                reference["sourceNodeId"] = node.get("id") or node.get("nodeId")
                reference["sourceNodeType"] = "asset.image"
                reference["nodeType"] = "asset.image"
                reference["assetId"] = (
                    data.get("rootAssetId")
                    or data.get("assetId")
                )
                reference["assetType"] = (
                    data.get("rootAssetType")
                    or data.get("assetType")
                )
                reference["sourceType"] = data.get("sourceType") or "asset"
                reference["slot"] = data.get("preferredTargetSlot") or data.get("slot")
                _apply_canvas_reference_category(reference, node)
                return reference

        if allow_asset_library_lookup:
            assets = _provider_reference_assets_from_context(project_id, episode_id, context)
            asset_scan_ms = float(context.get("assetScanMs") or 0.0)
            asset_count = int(context.get("assetCount") or 0)
            for asset_type in ("characters", "creatures", "scenes", "props", "styles"):
                rows = assets.get(asset_type) if isinstance(assets, dict) else []
                if not isinstance(rows, list):
                    continue
                for item in rows:
                    if not isinstance(item, dict):
                        continue
                    media_candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
                    active_media = _active_asset_media_candidate(item)
                    if isinstance(active_media, dict):
                        media_candidates.append(
                            (
                                active_media,
                                {
                                    "assetId": item.get("id"),
                                    "assetType": asset_type,
                                    "versionId": item.get("activeMediaVersionId"),
                                },
                            )
                        )
                    item_matches = reference_id in _reference_identity_values(item)
                    for media, metadata in media_candidates:
                        if not item_matches and reference_id not in (_reference_identity_values(media) | _reference_identity_values(metadata)):
                            continue
                        reference = _provider_reference_image_from_media(
                            project_id,
                            media,
                            purpose=purpose,
                            image_input_limits=image_input_limits,
                            prepare_transport_media=prepare_transport_media,
                        )
                        if reference:
                            status = "found"
                            source = "asset"
                            reference.update(metadata)
                            reference["mediaId"] = media.get("id")
                            reference["source"] = "asset"
                            reference["requestedReferenceId"] = reference_id
                            return reference
        return None
    except Exception:
        status = "error"
        raise
    finally:
        canvas_perf_log(
            "provider_reference_image_by_id",
            projectId=project_id,
            episodeId=episode_id,
            referenceId=reference_id,
            purpose=purpose,
            status=status,
            source=source,
            durationMs=canvas_perf_elapsed_ms(perf_started_at),
            workflowReadMs=workflow_read_ms,
            workflowNodeCount=workflow_node_count,
            cardResultsMs=card_results_ms,
            cardResultCount=card_result_count,
            assetScanMs=asset_scan_ms,
            assetCount=asset_count,
            contextReused=context_reused,
            prepareTransportMedia=bool(prepare_transport_media),
            allowAssetLibraryLookup=bool(allow_asset_library_lookup),
        )


def _provider_reference_images_from_ids(
    project_id: str,
    episode_id: str,
    reference_ids: list[str],
    *,
    purpose: str,
    image_input_limits: dict[str, Any] | None = None,
    prepare_transport_media: bool = True,
    require_all: bool = False,
    required_reference_label: str = "参考图",
    resolution_workflow: dict[str, Any] | None = None,
    allow_asset_library_lookup: bool = True,
    deduplicate_media: bool = True,
) -> list[dict[str, Any]]:
    perf_started_at = canvas_perf_start()
    status = "ok"
    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    resolution_context: dict[str, Any] = {}
    normalized_reference_ids: list[str] = []
    seen_requested: set[str] = set()
    missing_reference_ids: list[str] = []
    for reference_id in (reference_ids if isinstance(reference_ids, list) else []):
        normalized_reference_id = str(reference_id or "").strip()
        if not normalized_reference_id or normalized_reference_id in seen_requested:
            continue
        seen_requested.add(normalized_reference_id)
        normalized_reference_ids.append(normalized_reference_id)
    try:
        if not normalized_reference_ids:
            return references
        resolution_context = _provider_reference_resolution_context(
            project_id,
            episode_id,
            workflow_projection=resolution_workflow,
            reference_ids=normalized_reference_ids,
        )
        for reference_id in normalized_reference_ids:
            reference = _provider_reference_image_by_id(
                project_id,
                episode_id,
                reference_id,
                purpose=purpose,
                image_input_limits=image_input_limits,
                prepare_transport_media=prepare_transport_media,
                resolution_context=resolution_context,
                allow_asset_library_lookup=allow_asset_library_lookup,
            )
            if not reference:
                missing_reference_ids.append(reference_id)
                continue
            key = str(reference.get("mediaId") or reference.get("versionId") or reference.get("requestedReferenceId") or "")
            if deduplicate_media and key and key in seen:
                continue
            if key:
                seen.add(key)
            references.append(reference)
        if require_all and missing_reference_ids:
            status = "missing_required_reference"
            visible_missing = "、".join(missing_reference_ids[:8])
            suffix = f" 等 {len(missing_reference_ids)} 个" if len(missing_reference_ids) > 8 else ""
            raise RuntimeError(
                f"任务绑定的{required_reference_label}无法解析：{visible_missing}{suffix}。"
                "请刷新画布或重新生成/绑定这些参考图后再发起生成；不能跳过缺失参考图提交。"
            )
        return references
    except Exception:
        if status == "ok":
            status = "error"
        raise
    finally:
        canvas_perf_log(
            "provider_reference_images_from_ids",
            projectId=project_id,
            episodeId=episode_id,
            purpose=purpose,
            status=status,
            durationMs=canvas_perf_elapsed_ms(perf_started_at),
            referenceIdCount=len(normalized_reference_ids),
            resolvedReferenceCount=len(references),
            missingReferenceCount=len(missing_reference_ids),
            missingReferenceIds=missing_reference_ids[:8],
            requireAllReferences=bool(require_all),
            allowAssetLibraryLookup=bool(allow_asset_library_lookup),
            workflowReadMs=float(resolution_context.get("workflowReadMs") or 0.0) if isinstance(resolution_context, dict) else 0.0,
            workflowNodeCount=int(resolution_context.get("workflowNodeCount") or 0) if isinstance(resolution_context, dict) else 0,
            cardResultsMs=float(resolution_context.get("cardResultsMs") or 0.0) if isinstance(resolution_context, dict) else 0.0,
            cardResultCount=int(resolution_context.get("cardResultCount") or 0) if isinstance(resolution_context, dict) else 0,
            assetScanMs=float(resolution_context.get("assetScanMs") or 0.0) if isinstance(resolution_context, dict) else 0.0,
            assetCount=int(resolution_context.get("assetCount") or 0) if isinstance(resolution_context, dict) else 0,
            workflowReused=bool(resolution_context.get("workflowReused")) if isinstance(resolution_context, dict) else False,
            prepareTransportMedia=bool(prepare_transport_media),
        )


def _provider_reference_images_from_inline_files(
    project_id: str,
    file_infos: list[Any],
    *,
    purpose: str,
    source: str = "uploaded_reference",
    image_input_limits: dict[str, Any] | None = None,
    prepare_transport_media: bool = True,
    require_all: bool = False,
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, file_info in enumerate(file_infos):
        if not isinstance(file_info, dict):
            if require_all:
                raise RuntimeError(f"第 {index + 1} 张参考图数据无效，请重新选择；不会跳过参考图提交。")
            continue
        if not prepare_transport_media:
            reference = _provider_reference_image_metadata_only(
                file_info,
                fallback_source=str(file_info.get("source") or source),
                index=index,
            )
            if not reference:
                if require_all:
                    raise RuntimeError(f"第 {index + 1} 张参考图未能完整读取，请检查图片后重试；不会跳过参考图提交。")
                continue
            key = str(
                file_info.get("id")
                or file_info.get("mediaId")
                or file_info.get("media_id")
                or file_info.get("versionId")
                or file_info.get("version_id")
                or file_info.get("filePath")
                or file_info.get("file_path")
                or file_info.get("path")
                or file_info.get("relativePath")
                or file_info.get("relative_path")
                or reference.get("providerFileId")
                or index
            )
            if key in seen:
                continue
            seen.add(key)
            references.append(reference)
            continue
        data_url = _provider_image_data_url_from_file_info(
            project_id,
            file_info,
            purpose=f"{purpose}-{index + 1}",
            image_input_limits=image_input_limits,
        )
        if not data_url:
            if require_all:
                raise RuntimeError(f"第 {index + 1} 张参考图未能完整读取，请检查图片后重试；不会跳过参考图提交。")
            continue
        _raw, mime = _decode_data_url(data_url)
        provider_file_id = _provider_reference_file_id_from_value(file_info)
        key = str(
            file_info.get("filePath")
            or file_info.get("file_path")
            or file_info.get("path")
            or file_info.get("relativePath")
            or file_info.get("relative_path")
            or provider_file_id
            or data_url
        )
        if key in seen:
            continue
        seen.add(key)
        reference = {
            "dataUrl": data_url,
            "mimeType": mime,
            "providerPrepared": True,
            "source": str(file_info.get("source") or source),
            "name": file_info.get("name") or file_info.get("originalName"),
            "index": index,
        }
        for key in (
            "role",
            "referenceRole",
            "reference_role",
            "purpose",
            "assetId",
            "asset_id",
            "assetType",
            "asset_type",
            "slot",
            "sourceType",
            "source_type",
            "label",
            "caption",
            "displayName",
            "template",
            "id",
            "requestedReferenceId",
        ):
            if file_info.get(key):
                reference[key] = file_info.get(key)
        if provider_file_id:
            reference["providerFileId"] = provider_file_id
        references.append(reference)
    return references


def _provider_reference_metadata(reference: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(reference, dict):
        return {}
    return {
        key: reference.get(key)
        for key in (
            "requestedReferenceId",
            "mediaId",
            "versionId",
            "assetId",
            "assetType",
            "source",
            "sourceType",
            "sourceNodeId",
            "sourceNodeType",
            "nodeType",
            "slot",
            "role",
            "referenceRole",
            "frameRole",
            "useNativeFrame",
            "transportRole",
            "isEditBaseImage",
            "providerPrepared",
            "mimeType",
            "storyboardVideoReferenceCleaned",
            "storyboardLabelMaskCount",
            "storyboardVideoReferenceCleanup",
            "storyboardVideoReferenceCleanupError",
        )
        if reference.get(key) not in (None, "")
    }


def _provider_reference_videos_from_ids(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    reference_ids: list[str],
    *,
    model: dict[str, Any],
    prepare_transport_media: bool = True,
    output_duration: float | None = None,
    require_all: bool = True,
) -> list[dict[str, Any]]:
    """Resolve linked local video media and upload only the exact generation input."""
    if not reference_ids:
        return []
    if not prepare_transport_media:
        return [{"requestedReferenceId": item, "kind": "video"} for item in reference_ids]
    context = _provider_reference_resolution_context(
        project_id,
        episode_id,
        workflow_projection=workflow,
        reference_ids=list(reference_ids),
    )
    candidates: list[tuple[str, dict[str, Any]]] = []
    for version in context.get("cardResults", []) if isinstance(context.get("cardResults"), list) else []:
        media = version.get("media") if isinstance(version.get("media"), dict) else {}
        if str(media.get("kind") or media.get("mediaType") or "").lower() != "video":
            continue
        identities = _reference_identity_values(version) | _reference_identity_values(media)
        candidates.extend((item, media) for item in reference_ids if item in identities)
    workflow_nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    for node in workflow_nodes:
        if not isinstance(node, dict) or str(node.get("type") or "") not in {"media.external", "video.result"}:
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        media = data.get("media") if isinstance(data.get("media"), dict) else data.get("storage")
        if not isinstance(media, dict):
            media = data.get("currentMedia") if isinstance(data.get("currentMedia"), dict) else {}
        if str(media.get("kind") or media.get("mediaType") or "").lower() != "video":
            continue
        identities = _workflow_media_identity_values(node, data, media)
        candidates.extend((item, media) for item in reference_ids if item in identities)
    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    media_by_id: dict[str, dict[str, Any]] = {}
    for requested_id, media in candidates:
        media_by_id.setdefault(requested_id, media)
    # Resolution traversal, upload completion and cache hits must not renumber inputs.
    for requested_id in reference_ids:
        media = media_by_id.get(requested_id)
        if media is None:
            continue
        media = original_reference_video_media(media)
        source = _local_video_source_from_media(media)
        if not source:
            if require_all:
                raise RuntimeError(f"参考视频 {requested_id} 缺少本地文件，无法上传到七牛")
            continue
        path, _mime = source
        metadata = video_media_metadata(project_id, media)
        resolved.append({
            **metadata,
            "media": metadata,
            "requestedReferenceId": requested_id,
            "kind": "video",
            "_localPath": str(path),
        })
        seen.add(requested_id)
    missing = set(reference_ids) - seen
    if require_all and missing:
        raise RuntimeError(f"任务绑定的参考视频无法解析：{'、'.join(sorted(missing))}")
    # A model switch can make the existing file representation too large or
    # use an unsupported container. Those constraints are repairable, so only
    # reject the duration/count/material constraints before normalization.
    validate_reference_video_durations(resolved, model, output_duration=output_duration)
    limits = reference_video_limits(model)
    from .video_clips import _media_tool_executable

    for reference in resolved:
        source_path = Path(reference.pop("_localPath"))
        with prepare_reference_video(
            source_path,
            reference,
            limits,
            ffmpeg=_media_tool_executable("ffmpeg"),
        ) as (prepared_path, processing):
            normalized = dict(reference)
            if processing.get("compressed"):
                measured = video_media_metadata(project_id, {"path": str(prepared_path)})
                normalized.update({
                    **{key: measured[key] for key in ("format", "size", "width", "height", "fps", "duration", "videoCodec", "audioCodecs")},
                    "referenceVideoProcessing": copy.deepcopy(processing),
                })
            validate_reference_videos([normalized], model, output_duration=output_duration)
            reference.clear()
            reference.update(normalized)
            reference["media"] = copy.deepcopy(normalized)
            remote = ensure_public_url(prepared_path, "video")
            from utils.request_media_archive import archive_uploaded_media

            reference["requestLogMedia"] = archive_uploaded_media(
                prepared_path, remote,
                PROJECTS_DIR / project_id / "debug" / "model-request-logs" / "final-video-generation-request" / "_transport",
            )
        reference["url"] = remote["url"]
        reference["videoUrl"] = remote["url"]
        reference["storage"] = remote
    return resolved


_VIDEO_REFERENCE_FILE_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}


_PROVIDER_REFERENCE_FILE_ID_KEYS = {
    "providerFileId",
    "provider_file_id",
    "providerImageId",
    "provider_image_id",
    "providerMediaId",
    "provider_media_id",
    "openaiFileId",
    "openai_file_id",
    "imageFileId",
    "image_file_id",
}
