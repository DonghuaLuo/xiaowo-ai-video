# -*- coding: utf-8 -*-
"""工作流领域实际实现。"""
from __future__ import annotations

from .assets import list_assets
from .canvas_ownership import validate_node_identity_update
from .canvas_store_database import retry_canvas_mutation_v4
from .canvas_store_database import validate_canvas_revision_v4
from .canvas_store_mutations import write_canvas_records_v4
from .canvas_store_queries import get_canvas_records_v4
from .canvas_store_queries import read_card_results
from .canvas_store_results import commit_canvas_result_v4
from .catalogs import ASSET_TYPES
from .planning_contract import _is_user_locked_item
from .projects import _touch_project_meta
from .store_core import ASSET_LIFECYCLE_ACTIVE
from .store_core import _deep_merge
from .storyboard_templates import storyboard_template_label
from .workflow_asset_resolution import _workflow_canvas_project_asset_info
from .workflow_contract import _WORKFLOW_CHAIN_MANAGED_NODE_TYPES
from .workflow_contract import _assert_canvas_mutation_does_not_return_workflow
from .workflow_contract import _assert_new_workflow_node_type_allowed
from .workflow_contract import _assert_workflow_node_type_update_allowed
from .workflow_contract import _ensure_saved_workflow_node_contract
from .workflow_contract import _ensure_saved_workflow_route_contract
from .workflow_contract import _workflow_asset_type_from_media_purpose
from .workflow_contract import _workflow_image_node_type
from .workflow_contract import _workflow_layout_position
from .workflow_contract import _workflow_layout_size
from .workflow_contract import _mark_visual_handoff_user_position
from .workflow_contract import _workflow_media_purpose_material_slot
from .workflow_contract import _workflow_media_purpose_target_slot
from .workflow_contract import _workflow_mutation_event_fields
from .workflow_contract import _workflow_node_media_kind
from .workflow_contract import _workflow_node_payload_data
from .workflow_contract import _workflow_node_type_value
from .workflow_projection import _read_canvas_route_v4
from .workflow_input_resolution import workflow_current_media_reference
from .workflow_input_resolution import _workflow_data_active_version_id
from .workflow_projection import _workflow_cards_mutation_write
from typing import Any
from utils.frame_references import FRAME_IMAGE
from utils.frame_references import is_frame_image
import copy
import uuid


def update_workflow_route(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not episode_id:
        raise ValueError("缺少 episodeId")
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "更新画布路线")
    route_id = str(payload.get("routeId") or payload.get("route_id") or payload.get("id") or "").strip()
    if not route_id:
        raise ValueError("缺少 routeId")
    route_patch = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    allowed_fields = {
        "label",
        "title",
        "status",
        "locked",
        "lockedByUser",
        "locked_by_user",
        "preserveOnReplan",
        "preserve_on_replan",
        "lockedReason",
        "locked_reason",
        "quality",
        "storyboardTemplate",
        "storyboard_template",
        "storyboardTemplateLabel",
        "storyboard_template_label",
    }
    patch: dict[str, Any] = {}
    for key in allowed_fields:
        if key in payload:
            patch[key] = payload.get(key)
        if key in route_patch:
            patch[key] = route_patch.get(key)
    if not patch:
        raise ValueError("没有需要更新的路线字段")

    route = _read_canvas_route_v4(project_id, episode_id, route_id)
    if not route:
        raise FileNotFoundError("路线不存在")
    if "locked_by_user" in patch:
        patch["lockedByUser"] = patch.pop("locked_by_user")
    if "preserve_on_replan" in patch:
        patch["preserveOnReplan"] = patch.pop("preserve_on_replan")
    if "locked_reason" in patch:
        patch["lockedReason"] = patch.pop("locked_reason")
    if "storyboard_template" in patch:
        patch["storyboardTemplate"] = patch.pop("storyboard_template")
    if "storyboard_template_label" in patch:
        patch["storyboardTemplateLabel"] = patch.pop("storyboard_template_label")
    if patch.get("locked") is False and "lockedReason" not in patch:
        patch["lockedReason"] = None
    for key, value in patch.items():
        if value is None and key in {"lockedReason", "storyboardTemplateLabel"}:
            route.pop(key, None)
        else:
            route[key] = copy.deepcopy(value)
    if route.get("storyboardTemplate") and not route.get("storyboardTemplateLabel"):
        route["storyboardTemplateLabel"] = storyboard_template_label(str(route.get("storyboardTemplate") or ""))
    route_to_chain_id = {
        route_id: str(route.get("workChainId") or route.get("work_chain_id") or "").strip()
    }
    _ensure_saved_workflow_route_contract(
        {"nodes": []},
        route,
        0,
        route_to_chain_id,
    )
    save_result = write_canvas_records_v4(
        project_id,
        episode_id,
        routes=[route],
        op_type="structure_patch",
        changed_resources=["canvas_route"],
        expected_revision=payload.get("expectedRevision") or payload.get("expected_revision"),
    )
    _touch_project_meta(project_id)

    result = {
        "success": True,
        "episodeId": episode_id,
        "route": copy.deepcopy(route),
        "workflowVersion": save_result.get("workflowVersion"),
        **_workflow_mutation_event_fields(save_result, ["canvas_route"]),
        "focusTarget": {"section": "episode", "episodeId": episode_id, "routeId": route_id},
        "projectChanged": True,
    }
    return result


_WORKFLOW_RENAME_MEDIA_PURPOSES = {
    "custom_image",
    "character_reference",
    "creature_reference",
    "scene_reference",
    "prop_reference",
    "storyboard_image",
    "visual_handoff",
}


_WORKFLOW_PROTECTED_ASSET_RENAME_DATA_KEYS = {
    "name",
    "title",
    "sourceType",
    "source_type",
    "assetName",
    "asset_name",
    "assetType",
    "asset_type",
    "assetKind",
    "asset_kind",
    "assetId",
    "asset_id",
    "sourceVersionId",
    "source_version_id",
    "assetVersionId",
    "asset_version_id",
    "mediaVersionId",
    "media_version_id",
    "activeMediaVersionId",
    "active_media_version_id",
    "activeVersionId",
    "active_version_id",
    "winnerVersionId",
    "winner_version_id",
    "mediaPurpose",
    "media_purpose",
    "preferredTargetSlot",
    "preferred_target_slot",
    "voiceStyle",
    "voice_style",
}


_WORKFLOW_PROJECT_ASSET_REFERENCE_DATA_KEYS = (
    "assetId",
    "asset_id",
    "sourceVersionId",
    "source_version_id",
    "assetVersionId",
    "asset_version_id",
    "mediaVersionId",
    "media_version_id",
    "activeMediaVersionId",
    "active_media_version_id",
    "activeVersionId",
    "active_version_id",
    "winnerVersionId",
    "winner_version_id",
)


def _workflow_rename_asset_kind(node: dict[str, Any] | None) -> str:
    node_type = _workflow_node_type_value(node)
    if node_type == "video.result":
        return "video"
    if node_type in {"asset.image", "media.external", "storyboard.image"}:
        return "video" if _workflow_node_media_kind(node) == "video" else "image"
    return ""


def _workflow_node_claims_project_asset_reference(node: dict[str, Any] | None) -> bool:
    if not isinstance(node, dict):
        return False
    if _workflow_image_node_type(node) not in {"asset.image", "media.external"}:
        return False
    data = _workflow_node_payload_data(node)
    return str(data.get("sourceType") or data.get("source_type") or "").strip() == "asset"


def _workflow_direct_project_asset_info(node: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(node, dict):
        return None
    data = _workflow_node_payload_data(node)
    if str(data.get("sourceType") or data.get("source_type") or "").strip() != "asset":
        return None
    return _workflow_canvas_project_asset_info(node)


def _workflow_detach_project_asset_reference(data: dict[str, Any]) -> None:
    data["sourceType"] = "asset_copy"
    data.pop("source_type", None)
    for key in _WORKFLOW_PROJECT_ASSET_REFERENCE_DATA_KEYS:
        data.pop(key, None)
    data["mediaBindingMode"] = "pinned"


def _workflow_split_range_binding_exists(value: Any, *, source_ref: bool = False) -> bool:
    if isinstance(value, list):
        return any(_workflow_split_range_binding_exists(item, source_ref=source_ref) for item in value)
    if isinstance(value, dict):
        if source_ref:
            keys = ("assetRangeId", "asset_range_id", "rangeId", "range_id")
        else:
            keys = ("id", "assetRangeId", "asset_range_id", "rangeId", "range_id")
        return any(str(value.get(key) or "").strip() for key in keys)
    return bool(str(value or "").strip()) if not source_ref else False


def _workflow_asset_row_has_split_range_binding(row: dict[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    return any(
        _workflow_split_range_binding_exists(row.get(key))
        for key in ("assetRangeId", "asset_range_id", "assetRangeIds", "asset_range_ids")
    ) or any(
        _workflow_split_range_binding_exists(row.get(key), source_ref=True)
        for key in ("sourceRefs", "source_refs")
    )


def _workflow_project_asset_row_by_id(
    project_id: str,
    asset_type: str,
    asset_id: str,
) -> dict[str, Any] | None:
    if not project_id or asset_type not in ASSET_TYPES or not asset_id:
        return None
    assets = list_assets(
        "project",
        project_id,
        hydrate=True,
        include_source_metadata=True,
        asset_type=asset_type,
        lifecycle_status=ASSET_LIFECYCLE_ACTIVE,
    )
    rows = assets.get(asset_type) if isinstance(assets, dict) else []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and str(row.get("id") or "").strip() == asset_id:
            return row
    return None


def _workflow_canvas_node_references_split_asset(project_id: str, node: dict[str, Any] | None) -> bool:
    asset_info = _workflow_direct_project_asset_info(node)
    if not asset_info:
        return False
    row = _workflow_project_asset_row_by_id(
        project_id,
        asset_info.get("assetType") or "",
        asset_info.get("assetId") or "",
    )
    return _workflow_asset_row_has_split_range_binding(row)


def _workflow_asset_rename_field_changed(previous_node: dict[str, Any], next_node: dict[str, Any]) -> bool:
    previous_data = _workflow_node_payload_data(previous_node)
    next_data = _workflow_node_payload_data(next_node)
    for key in _WORKFLOW_PROTECTED_ASSET_RENAME_DATA_KEYS:
        if str(previous_data.get(key) or "").strip() != str(next_data.get(key) or "").strip():
            return True
    return False


def _assert_split_asset_rename_fields_unchanged(
    project_id: str,
    previous_node: dict[str, Any] | None,
    next_node: dict[str, Any] | None,
) -> None:
    if not isinstance(previous_node, dict) or not isinstance(next_node, dict):
        return
    if (
        _workflow_node_claims_project_asset_reference(previous_node)
        and not _workflow_direct_project_asset_info(previous_node)
        and _workflow_asset_rename_field_changed(previous_node, next_node)
    ):
        raise ValueError("资产来源信息不完整，不能重命名")
    if not _workflow_canvas_node_references_split_asset(project_id, previous_node):
        return
    if _workflow_asset_rename_field_changed(previous_node, next_node):
        raise ValueError("拆分资产参与自动关联，不能重命名")


def rename_workflow_asset_node(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    params = payload if isinstance(payload, dict) else {}
    return retry_canvas_mutation_v4(
        lambda: _rename_workflow_asset_node_once(project_id, episode_id, params),
        expected_revision=params.get("expectedRevision", params.get("expected_revision")),
    )


def _rename_workflow_asset_node_once(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not episode_id:
        raise ValueError("缺少 episodeId")
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "重命名画布资产节点")
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    if not node_id:
        raise ValueError("缺少 nodeId")
    title = str(payload.get("title") or payload.get("name") or "").strip()
    if not title:
        raise ValueError("请输入名称")

    snapshot = get_canvas_records_v4(project_id, episode_id, {"ids": {"nodeIds": [node_id]}, "detail": "full"})
    validate_canvas_revision_v4(snapshot["currentRevision"], payload.get("expectedRevision", payload.get("expected_revision")))
    node = next((item for item in snapshot["records"]["nodes"] if item.get("id") == node_id), None)
    if node is None:
        raise ValueError("节点不存在")
    if _is_user_locked_item(node):
        return {
            "success": True,
            "message": f"node {node_id} 已由用户锁定，未覆盖。",
            "episodeId": episode_id,
            "nodeId": node_id,
            "node": copy.deepcopy(node),
            "skippedLocked": True,
            "changedResources": [],
            "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id},
            "projectChanged": False,
        }

    kind = _workflow_rename_asset_kind(node)
    if not kind:
        return {"success": False, "message": "当前节点不支持重命名"}
    direct_asset_info = (
        _workflow_direct_project_asset_info(node)
        if _workflow_node_claims_project_asset_reference(node)
        else None
    )
    if _workflow_node_claims_project_asset_reference(node) and not direct_asset_info:
        return {"success": False, "message": "资产来源信息不完整，不能重命名"}
    if _workflow_canvas_node_references_split_asset(project_id, node):
        return {"success": False, "message": "拆分资产参与自动关联，不能重命名", "protected": True}

    next_node = copy.deepcopy(node)
    data = next_node.setdefault("data", {})
    if not isinstance(data, dict):
        data = {}
        next_node["data"] = data
    data["title"] = title
    data["assetName"] = title
    updated_versions = None
    active_version_id = _workflow_data_active_version_id(data)
    if kind == "video":
        data["assetKind"] = "video"
        data["assetType"] = "video"
        data["mediaPurpose"] = "video_result"
        data["preferredTargetSlot"] = "video_result"
        data["voiceStyle"] = ""
        if direct_asset_info:
            _workflow_detach_project_asset_reference(data)
    else:
        media_purpose = str(payload.get("mediaPurpose") or payload.get("media_purpose") or "").strip()
        if media_purpose == "visual_handoff_reference":
            media_purpose = "visual_handoff"
        if is_frame_image(node.get("data")):
            media_purpose = FRAME_IMAGE
        elif media_purpose not in _WORKFLOW_RENAME_MEDIA_PURPOSES:
            return {"success": False, "message": "图片类别无效"}
        asset_type = _workflow_asset_type_from_media_purpose(media_purpose)
        if not asset_type:
            return {"success": False, "message": "图片类别无效"}
        previous_purpose = (
            data.get("mediaPurpose") or data.get("preferredTargetSlot")
            or data.get("assetKind") or data.get("assetType")
        )
        if media_purpose == "storyboard_image" and previous_purpose not in {"storyboard", "storyboard_image"}:
            media = workflow_current_media_reference(project_id, episode_id, {"nodes": [node]}, node_id)
            if media:
                if active_version_id:
                    updated_versions = read_card_results(project_id, episode_id, node_id)
                    selected = next((v for v in updated_versions if v.get("id") == active_version_id), None)
                    if selected is None:
                        raise ValueError("当前图片版本不存在，无法修改分类")
                    selected.setdefault("payload", {})["storyboardPromptSpec"] = {"layoutKind": "custom"}
                    media.pop("storyboardPromptSpec", None)
                else:
                    media["storyboardPromptSpec"] = {"layoutKind": "custom"}
                data["media"] = copy.deepcopy(media)
                data["storage"] = copy.deepcopy(media)
        data["mediaPurpose"] = media_purpose
        data["preferredTargetSlot"] = (
            _workflow_media_purpose_material_slot(media_purpose)
            or _workflow_media_purpose_target_slot(media_purpose)
        )
        data["assetKind"] = asset_type
        data["assetType"] = asset_type
        if direct_asset_info and asset_type != direct_asset_info.get("assetType"):
            _workflow_detach_project_asset_reference(data)
        data["voiceStyle"] = (
            str(payload.get("voiceStyle") or payload.get("voice_style") or "").strip()
            if media_purpose in {"character_reference", "creature_reference"}
            else ""
        )

    _ensure_saved_workflow_node_contract(next_node)
    if updated_versions is not None:
        save_result = commit_canvas_result_v4(
            project_id, episode_id, node_id=node_id, versions=updated_versions,
            active_version_id=active_version_id, nodes=[next_node],
            changed_resources=["canvas_node", "canvas_version"],
            expected_revision=snapshot["currentRevision"],
        )
    else:
        save_result = write_canvas_records_v4(
            project_id, episode_id, nodes=[next_node], op_type="structure_patch",
            changed_resources=["canvas_node"], expected_revision=snapshot["currentRevision"],
        )
    _touch_project_meta(project_id)
    mutation_fields = _workflow_mutation_event_fields(save_result, ["canvas_node"])
    return {
        "success": True,
        "episodeId": episode_id,
        "nodeId": node_id,
        "itemType": "node",
        "item": copy.deepcopy(next_node),
        "node": copy.deepcopy(next_node),
        "workflowVersion": save_result.get("workflowVersion"),
        **mutation_fields,
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id},
        "projectChanged": True,
    }


def upsert_workflow_node(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not episode_id:
        raise ValueError("缺少 episodeId")
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "保存画布节点")
    item_type = str(payload.get("itemType") or payload.get("item_type") or payload.get("kind") or "node").strip()
    if item_type not in {"node", "route"}:
        raise ValueError("itemType 必须是 node 或 route；资产关联请使用 link_workflow_input")
    item = payload.get(item_type) if isinstance(payload.get(item_type), dict) else payload.get("item")
    if not isinstance(item, dict):
        item = payload.get("node") if isinstance(payload.get("node"), dict) else {}
    item = copy.deepcopy(item)
    if item_type == "node":
        incoming_node_type = str(item.get("type") or payload.get("nodeType") or payload.get("node_type") or "").strip()
        if incoming_node_type:
            _assert_new_workflow_node_type_allowed(incoming_node_type, allow_work_chain_managed=True)
    fallback_prefix = {"node": "node", "route": "route"}[item_type]
    item_id = str(item.get("id") or payload.get("id") or payload.get("itemId") or payload.get("item_id") or f"{fallback_prefix}_{uuid.uuid4().hex[:8]}")
    item["id"] = item_id

    record_key = "nodes" if item_type == "node" else "routes"
    read_params = {"ids": {"nodeIds" if item_type == "node" else "routeIds": [item_id]}, "detail": "full"}
    first_snapshot = get_canvas_records_v4(project_id, episode_id, read_params)
    originally_present = any(row.get("id") == item_id for row in first_snapshot["records"][record_key])

    def save_current() -> dict[str, Any]:
        nonlocal first_snapshot
        snapshot = first_snapshot if first_snapshot is not None else get_canvas_records_v4(project_id, episode_id, read_params)
        first_snapshot = None
        validate_canvas_revision_v4(snapshot["currentRevision"], payload.get("expectedRevision", payload.get("expected_revision")))
        return _upsert_workflow_item_from_snapshot(
            project_id, episode_id, payload, item_type, item, snapshot, originally_present,
        )

    return retry_canvas_mutation_v4(
        save_current, expected_revision=payload.get("expectedRevision", payload.get("expected_revision")),
    )


def _upsert_workflow_item_from_snapshot(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
    item_type: str,
    item: dict[str, Any],
    snapshot: dict[str, Any],
    originally_present: bool,
) -> dict[str, Any]:
    item = copy.deepcopy(item)
    item_id = item["id"]
    record_key = "nodes" if item_type == "node" else "routes"
    existing_item = next((row for row in snapshot["records"][record_key] if row.get("id") == item_id), None)
    if originally_present and existing_item is None:
        raise FileNotFoundError("画布记录已删除，更新未保存")
    if not originally_present and existing_item is not None:
        raise ValueError("画布记录已存在，创建操作不能覆盖已有记录")

    if existing_item is not None:
        if _is_user_locked_item(existing_item):
            result = {
                "success": True,
                "message": f"{item_type} {item_id} 已由用户锁定，未覆盖。",
                "episodeId": episode_id,
                "itemType": item_type,
                "item": copy.deepcopy(existing_item),
                "skippedLocked": True,
                "changedResources": [],
                "focusTarget": {"section": "episode", "episodeId": episode_id, "itemId": item_id},
                "projectChanged": False,
            }
            return result
        if item_type == "node":
            _assert_workflow_node_type_update_allowed(existing_item, item)
        validate_node_identity_update(existing_item, item)
        saved_item = _deep_merge(existing_item, item)
        if item_type == "node":
            _assert_split_asset_rename_fields_unchanged(project_id, existing_item, saved_item)
    else:
        if item_type == "node":
            new_node_type = str(
                item.get("type")
                or payload.get("nodeType")
                or payload.get("node_type")
                or "custom"
            ).strip()
            if new_node_type in _WORKFLOW_CHAIN_MANAGED_NODE_TYPES:
                raise ValueError("分集原文、片段剧本、分镜脚本、分镜单元、分镜图、工作链视频生成和视频片段只能由生成工作链流程创建")
            item.setdefault("type", new_node_type)
            item.setdefault("position", {"x": 120, "y": 120})
            item.setdefault("data", {"title": item.get("type") or "节点", "status": "draft"})
        saved_item = item

    if item_type == "node":
        _ensure_saved_workflow_node_contract(saved_item)
        save_result = write_canvas_records_v4(
            project_id,
            episode_id,
            nodes=[saved_item],
            op_type="structure_patch",
            changed_resources=["canvas_node"],
            expected_revision=snapshot["currentRevision"],
            create_only=not originally_present,
        )
        changed_resources = ["canvas_node"]
    else:
        route_to_chain_id = {
            item_id: str(saved_item.get("workChainId") or saved_item.get("work_chain_id") or "").strip()
        }
        _ensure_saved_workflow_route_contract({"nodes": []}, saved_item, 0, route_to_chain_id)
        save_result = write_canvas_records_v4(
            project_id,
            episode_id,
            routes=[saved_item],
            op_type="structure_patch",
            changed_resources=["canvas_route"],
            expected_revision=snapshot["currentRevision"],
            create_only=not originally_present,
        )
        changed_resources = ["canvas_route"]
    _touch_project_meta(project_id)
    mutation_fields = _workflow_mutation_event_fields(save_result, changed_resources)
    result_payload = {
        "success": True,
        "episodeId": episode_id,
        "itemType": item_type,
        "item": copy.deepcopy(saved_item),
        "workflowVersion": save_result.get("workflowVersion"),
        **mutation_fields,
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": item_id if item_type == "node" else ""},
        "projectChanged": True,
    }
    if item_type == "node":
        result_payload["node"] = copy.deepcopy(saved_item)
    elif item_type == "route":
        result_payload["route"] = copy.deepcopy(saved_item)
    return result_payload


def update_workflow_node_layout(project_id: str, episode_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    params = payload if isinstance(payload, dict) else {}
    return retry_canvas_mutation_v4(
        lambda: _update_workflow_node_layout_once(project_id, episode_id, params),
        expected_revision=params.get("expectedRevision", params.get("expected_revision")),
    )


def _update_workflow_node_layout_once(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not episode_id:
        raise ValueError("缺少 episodeId")
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "更新画布节点布局")
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    if not node_id:
        raise ValueError("缺少 nodeId")

    has_position_payload = isinstance(payload.get("position"), dict)
    next_position = _workflow_layout_position(payload.get("position"))
    size_payload = (
        payload.get("size")
        if isinstance(payload.get("size"), dict)
        else payload.get("cardSize")
        if isinstance(payload.get("cardSize"), dict)
        else payload.get("card_size")
        if isinstance(payload.get("card_size"), dict)
        else None
    )
    if has_position_payload and next_position is None:
        raise ValueError("节点坐标格式不正确")
    if next_position is None and size_payload is None:
        raise ValueError("没有需要保存的节点布局")

    snapshot = get_canvas_records_v4(project_id, episode_id, {"ids": {"nodeIds": [node_id]}, "detail": "full"})
    validate_canvas_revision_v4(snapshot["currentRevision"], payload.get("expectedRevision", payload.get("expected_revision")))
    node = next((item for item in snapshot["records"]["nodes"] if item.get("id") == node_id), None)
    if node is None:
        raise FileNotFoundError("节点不存在")
    if _is_user_locked_item(node):
        return {
            "success": True,
            "message": f"node {node_id} 已由用户锁定，未覆盖。",
            "episodeId": episode_id,
            "nodeId": node_id,
            "node": {
                "id": node_id,
                "type": str(node.get("type") or ""),
                "position": copy.deepcopy(node.get("position") or {}),
                "data": {},
            },
            "skippedLocked": True,
            "changedResources": [],
            "projectChanged": False,
        }

    changed = False
    node_type = str(node.get("type") or "")
    if next_position is not None and node.get("position") != next_position:
        node["position"] = next_position
        _mark_visual_handoff_user_position(node)
        changed = True

    size_changed = False
    if size_payload is not None:
        next_size = _workflow_layout_size(node_type, size_payload)
        if next_size is None:
            raise ValueError("卡片尺寸格式不正确")
        data = node.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            node["data"] = data
        card_state = data.get("cardState") if isinstance(data.get("cardState"), dict) else {}
        current_size = card_state.get("size") if isinstance(card_state.get("size"), dict) else {}
        if current_size != next_size:
            card_state["size"] = next_size
            data["cardState"] = card_state
            size_changed = True
            changed = True

    if not changed:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        return {
            "success": True,
            "episodeId": episode_id,
            "nodeId": node_id,
            "node": {
                "id": node_id,
                "type": node_type,
                "position": copy.deepcopy(node.get("position") or {}),
                "data": {"cardState": copy.deepcopy(data.get("cardState"))} if size_payload is not None else {},
            },
            "changedResources": [],
            "projectChanged": False,
        }

    _ensure_saved_workflow_node_contract(node)
    save_result = _workflow_cards_mutation_write(
        project_id,
        episode_id,
        [copy.deepcopy(node)],
        op_type="layout_patch",
        changed_resources=["canvas_node"],
        expected_revision=snapshot["currentRevision"],
    )

    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    mutation_fields = _workflow_mutation_event_fields(save_result, ["canvas_node"])
    return {
        "success": True,
        "message": "节点布局已保存。",
        "episodeId": episode_id,
        "nodeId": node_id,
        "node": {
            "id": node_id,
            "type": node_type,
            "position": copy.deepcopy(node.get("position") or {}),
            "data": {"cardState": copy.deepcopy(data.get("cardState"))} if size_changed else {},
        },
        "workflowVersion": save_result.get("workflowVersion"),
        **mutation_fields,
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": node_id},
        "projectChanged": True,
    }
