# -*- coding: utf-8 -*-
"""资产文本批次与单资产入库，保持锁和修订写入顺序。"""
from __future__ import annotations

from .asset_range_bindings import _attach_asset_range_metadata_to_item
from .asset_range_bindings import _attach_reused_asset_ranges_from_coverage
from .asset_range_bindings import _merge_reused_asset_aliases_from_coverage
from .asset_range_bindings import _promote_reused_asset_canonical_names_from_coverage
from .asset_text_contract import AGENT_TEXT_RESULT_SOURCES
from .asset_text_contract import _agent_text_asset_match_index
from .asset_text_contract import _agent_text_row_text
from .asset_text_contract import _agent_text_scene_row_is_context_only
from .asset_text_contract import _assert_design_asset_complete
from .asset_text_contract import _drop_incoming_asset_grouping_metadata
from .asset_text_contract import _normalize_agent_text_asset_row
from .asset_text_contract import _payload_bool
from .catalogs import DEFAULT_ASSETS
from .planning_contract import _is_user_locked_item
from .project_resource_revisions import _append_resource_revision
from .project_resource_revisions import _assert_resource_write_guard
from .project_resource_revisions import _resource_revision_value
from .reference_utils import asset_row_ids as _shared_asset_row_ids
from .reference_utils import next_short_asset_id as _shared_next_short_asset_id
from .source_coverage import _refresh_created_asset_ids_for_range
from .source_coverage import _source_refs_from_asset_row
from .source_coverage import _stamp_asset_range_id
from .source_coverage import _validate_asset_batch_refs_in_range
from .store_core import _JSON_WRITE_LOCK
from .store_core import _asset_is_offline
from .store_core import _deep_merge
from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json
from .video_task_card_references import _ASSET_REF_COLLECTIONS
from typing import Any
import copy


def _write_agent_assets_unlocked(project_id: str, generated: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    from .assets import _asset_source_order_for_project
    from .assets import _normalize_asset_item_for_storage
    from .assets import _sort_asset_rows_by_source_order
    from .assets import list_assets
    assets = list_assets("project", project_id, hydrate=False)
    source_order = _asset_source_order_for_project(project_id)
    for asset_type in ("characters", "creatures", "scenes", "props"):
        if asset_type not in generated:
            continue
        existing = [
            item for item in assets.get(asset_type, [])
            if not (
                isinstance(item, dict)
                and item.get("source") in {"agent", "agent-model"}
                and not _asset_is_offline(item)
            )
        ]
        used_asset_ids = set(_shared_asset_row_ids(existing))
        normalized_rows: list[dict[str, Any]] = []
        for index, row in enumerate(generated.get(asset_type, [])):
            item = _normalize_agent_text_asset_row(asset_type, row, index=index, used_ids=used_asset_ids)
            if not item:
                continue
            _assert_design_asset_complete(asset_type, item)
            _normalize_asset_item_for_storage(project_id, item)
            normalized_rows.append(item)
        next_rows = existing + normalized_rows
        _sort_asset_rows_by_source_order(next_rows, source_order)
        assets[asset_type] = next_rows
    path = _project_dir(project_id) / "assets" / "assets.json"
    _write_json(path, assets)
    return assets


def _write_agent_assets(project_id: str, generated: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    with _JSON_WRITE_LOCK:
        return _write_agent_assets_unlocked(project_id, generated)


def _save_agent_text_assets(project_id: str, payload: dict[str, Any], *, persist: bool = True,
                            asset_document: dict[str, Any] | None = None) -> dict[str, Any]:
    from .assets import _asset_source_order_for_project
    from .assets import _asset_store_path
    from .assets import _normalize_asset_item_for_storage
    from .assets import _sort_asset_rows_by_source_order
    from .assets import list_assets
    from .projects import _touch_project_meta
    assets = copy.deepcopy(asset_document) if asset_document is not None else list_assets("project", project_id, hydrate=False)
    mode = str(payload.get("assetMode") or payload.get("asset_mode") or payload.get("mode") or "upsert").strip()
    replace_agent = mode in {"replace", "replace_agent", "replace-agent", "replace_agent_assets"}
    changed_types: list[str] = []
    counts: dict[str, int] = {}
    skipped_locked_counts: dict[str, int] = {}
    skipped_context_scene_counts: dict[str, int] = {}
    reused_existing_counts: dict[str, int] = {}
    for asset_type in ("characters", "creatures", "scenes", "props"):
        rows = payload.get(asset_type)
        if not isinstance(rows, list):
            continue
        existing_rows = [copy.deepcopy(item) for item in assets.get(asset_type, []) if isinstance(item, dict)]
        written = 0
        skipped_locked = 0
        if replace_agent:
            next_rows = [
                item
                for item in existing_rows
                if _asset_is_offline(item)
                or str(item.get("source") or "") not in AGENT_TEXT_RESULT_SOURCES
                or _is_user_locked_item(item)
            ]
            used_asset_ids = set(_shared_asset_row_ids(next_rows))
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                if asset_type == "scenes" and _agent_text_scene_row_is_context_only(row):
                    skipped_context_scene_counts[asset_type] = skipped_context_scene_counts.get(asset_type, 0) + 1
                    continue
                match_index = _agent_text_asset_match_index(next_rows, row)
                incoming_asset_id = _agent_text_row_text(row, "assetId", "asset_id", "id")
                if incoming_asset_id and match_index < 0:
                    raise ValueError(f"{asset_type} 复用已有资产失败，assetId 不存在：{incoming_asset_id}")
                if incoming_asset_id and match_index >= 0:
                    if _is_user_locked_item(next_rows[match_index]):
                        skipped_locked += 1
                        continue
                    asset_range_id = str(payload.get("assetRangeId") or payload.get("asset_range_id") or "").strip()
                    source_refs = _source_refs_from_asset_row(row)
                    if _attach_asset_range_metadata_to_item(
                        next_rows[match_index],
                        asset_range_id,
                        source_refs=source_refs,
                    ):
                        _normalize_asset_item_for_storage(project_id, next_rows[match_index])
                        written += 1
                    reused_existing_counts[asset_type] = reused_existing_counts.get(asset_type, 0) + 1
                    continue
                incoming_name = _agent_text_row_text(row, "name", "title")
                if incoming_name:
                    duplicated_name = any(
                        isinstance(item, dict)
                        and not _asset_is_offline(item)
                        and str(item.get("name") or item.get("title") or "").strip().casefold() == incoming_name.casefold()
                        for item in next_rows
                    )
                    if duplicated_name:
                        raise ValueError(f"{asset_type} 新资产名称与已有资产重复；复用已有资产必须传 assetId：{incoming_name}")
                item = _normalize_agent_text_asset_row(asset_type, row, index=index, used_ids=used_asset_ids)
                if not item:
                    continue
                _assert_design_asset_complete(asset_type, item)
                _normalize_asset_item_for_storage(project_id, item)
                next_rows.append(item)
                written += 1
        else:
            next_rows = existing_rows
            used_asset_ids = set(_shared_asset_row_ids(next_rows))
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                if asset_type == "scenes" and _agent_text_scene_row_is_context_only(row):
                    skipped_context_scene_counts[asset_type] = skipped_context_scene_counts.get(asset_type, 0) + 1
                    continue
                match_index = _agent_text_asset_match_index(next_rows, row)
                incoming_asset_id = _agent_text_row_text(row, "assetId", "asset_id", "id")
                if incoming_asset_id and match_index < 0:
                    raise ValueError(f"{asset_type} 复用已有资产失败，assetId 不存在：{incoming_asset_id}")
                if incoming_asset_id and match_index >= 0:
                    asset_range_id = str(payload.get("assetRangeId") or payload.get("asset_range_id") or "").strip()
                    source_refs = _source_refs_from_asset_row(row)
                    if _attach_asset_range_metadata_to_item(
                        next_rows[match_index],
                        asset_range_id,
                        source_refs=source_refs,
                    ):
                        _normalize_asset_item_for_storage(project_id, next_rows[match_index])
                        written += 1
                    reused_existing_counts[asset_type] = reused_existing_counts.get(asset_type, 0) + 1
                    continue
                incoming_name = _agent_text_row_text(row, "name", "title")
                if not incoming_asset_id and incoming_name:
                    duplicated_name = any(
                        isinstance(item, dict)
                        and not _asset_is_offline(item)
                        and str(item.get("name") or item.get("title") or "").strip().casefold() == incoming_name.casefold()
                        for item in next_rows
                    )
                    if duplicated_name:
                        raise ValueError(f"{asset_type} 新资产名称与已有资产重复；复用已有资产必须传 assetId：{incoming_name}")
                existing = next_rows[match_index] if match_index >= 0 else None
                if _is_user_locked_item(existing):
                    skipped_locked += 1
                    continue
                item = _normalize_agent_text_asset_row(asset_type, row, existing=existing, index=index, used_ids=used_asset_ids)
                if not item:
                    continue
                _assert_design_asset_complete(asset_type, item)
                _normalize_asset_item_for_storage(project_id, item)
                if match_index >= 0:
                    next_rows[match_index] = item
                else:
                    next_rows.append(item)
                written += 1
        if written:
            assets[asset_type] = next_rows
            counts[asset_type] = written
            changed_types.append(asset_type)
        if skipped_locked:
            skipped_locked_counts[asset_type] = skipped_locked
    range_binding_counts = _attach_reused_asset_ranges_from_coverage(project_id, assets, payload)
    canonical_name_update_counts = _promote_reused_asset_canonical_names_from_coverage(assets, payload)
    alias_update_counts = _merge_reused_asset_aliases_from_coverage(assets, payload)
    source_order = _asset_source_order_for_project(project_id)
    for asset_type in _ASSET_REF_COLLECTIONS:
        rows = assets.get(asset_type)
        if (
            isinstance(rows, list)
            and _sort_asset_rows_by_source_order(rows, source_order)
            and asset_type not in changed_types
        ):
            changed_types.append(asset_type)
    for asset_type in range_binding_counts:
        if asset_type not in changed_types:
            changed_types.append(asset_type)
    for asset_type in canonical_name_update_counts:
        if asset_type not in changed_types:
            changed_types.append(asset_type)
    for asset_type in alias_update_counts:
        if asset_type not in changed_types:
            changed_types.append(asset_type)
    if changed_types and persist:
        _write_json(_asset_store_path("project", project_id), assets)
        _touch_project_meta(project_id)
    return {
        "changedTypes": changed_types,
        "counts": counts,
        "skippedLockedCounts": skipped_locked_counts,
        "skippedContextSceneCounts": skipped_context_scene_counts,
        "reusedExistingCounts": reused_existing_counts,
        "rangeBindingCounts": range_binding_counts,
        "canonicalNameUpdateCounts": canonical_name_update_counts,
        "aliasUpdateCounts": alias_update_counts,
        **({"document": assets} if not persist else {}),
    }


def _save_asset_batch_unlocked(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from .assets import _asset_store_path
    asset_store_path = _asset_store_path("project", project_id)
    asset_store_before = _read_json(asset_store_path, DEFAULT_ASSETS)
    _assert_resource_write_guard(
        asset_store_before,
        payload.get("expectedRevision") or payload.get("expected_revision"),
        payload.get("baseHash") or payload.get("base_hash"),
    )
    asset_range_id = str(payload.get("assetRangeId") or payload.get("asset_range_id") or "").strip()
    has_scoped_assets = any(
        isinstance(payload.get(asset_type), list) and payload.get(asset_type)
        for asset_type in _ASSET_REF_COLLECTIONS
    )
    if has_scoped_assets and not asset_range_id:
        raise ValueError("保存角色、生物、场景或道具资产前必须先 commit_asset_range，并传入 assetRangeId")
    if asset_range_id:
        _validate_asset_batch_refs_in_range(project_id, payload, asset_range_id)
        payload = _stamp_asset_range_id(payload, asset_range_id)
    result = _save_agent_text_assets(project_id, payload)
    changed_resources = list(result.get("changedTypes") or [])
    skipped_locked_counts = result.get("skippedLockedCounts") if isinstance(result.get("skippedLockedCounts"), dict) else {}
    skipped_context_scene_counts = (
        result.get("skippedContextSceneCounts") if isinstance(result.get("skippedContextSceneCounts"), dict) else {}
    )
    reused_existing_counts = result.get("reusedExistingCounts") if isinstance(result.get("reusedExistingCounts"), dict) else {}
    range_binding_counts = result.get("rangeBindingCounts") if isinstance(result.get("rangeBindingCounts"), dict) else {}
    canonical_name_update_counts = (
        result.get("canonicalNameUpdateCounts") if isinstance(result.get("canonicalNameUpdateCounts"), dict) else {}
    )
    alias_update_counts = result.get("aliasUpdateCounts") if isinstance(result.get("aliasUpdateCounts"), dict) else {}
    asset_coverage_table = payload.get("assetCoverageTable") if isinstance(payload.get("assetCoverageTable"), dict) else {}
    if (
        not changed_resources
        and not skipped_locked_counts
        and not skipped_context_scene_counts
        and not reused_existing_counts
        and not range_binding_counts
        and not canonical_name_update_counts
        and not alias_update_counts
        and not asset_coverage_table
    ):
        raise ValueError("没有可保存的角色、生物、场景或道具资产")
    if asset_range_id:
        _refresh_created_asset_ids_for_range(project_id, asset_range_id)
    if changed_resources:
        next_assets = _read_json(asset_store_path, DEFAULT_ASSETS)
        if isinstance(next_assets, dict):
            next_assets["revision"] = _resource_revision_value(asset_store_before) + 1
            next_assets["updatedAt"] = _now()
            _write_json(asset_store_path, next_assets)
        _append_resource_revision(
            project_id,
            resource="assets",
            relative_path="assets/assets.json",
            document=asset_store_before,
            reason=str(payload.get("reason") or "save_asset_batch"),
            user_instruction=str(payload.get("userInstruction") or payload.get("user_instruction") or ""),
        )
    response = {
        "success": True,
        "message": (
            "智能体已保存设计资产。"
            if result.get("counts")
            else "本段资产均已存在，已记录复用关系。"
            if (range_binding_counts or reused_existing_counts)
            else "智能体已保存设计资产。"
            if changed_resources
            else "本段仅包含背景语境场景，未保存为可引用场景资产。"
            if skipped_context_scene_counts
            else "本段资产均已存在，已记录复用关系。"
        ),
        "changedResources": changed_resources,
        "focusTarget": {"section": changed_resources[0], "assetTab": changed_resources[0]} if changed_resources else {"section": "assets"},
        "projectChanged": bool(changed_resources),
        "assetCounts": result.get("counts") or {},
        "skippedLockedCounts": skipped_locked_counts,
        "skippedContextSceneCounts": skipped_context_scene_counts,
        "reusedExistingCounts": reused_existing_counts,
        "rangeBindingCounts": range_binding_counts,
        "canonicalNameUpdateCounts": canonical_name_update_counts,
        "aliasUpdateCounts": alias_update_counts,
        "assetRangeId": asset_range_id or None,
    }
    if asset_coverage_table:
        response["assetCoverageTable"] = copy.deepcopy(asset_coverage_table)
        response["assetCoverage"] = copy.deepcopy(asset_coverage_table)
    return response


def save_asset_batch(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _JSON_WRITE_LOCK:
        return _save_asset_batch_unlocked(project_id, payload)


def _upsert_asset_unlocked(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from .agent_sessions import _hydrate_asset_row_for_ui
    from .assets import _asset_source_order_for_project
    from .assets import _asset_store_path
    from .assets import _normalize_asset_item_for_storage
    from .assets import _sort_asset_rows_by_source_order
    from .projects import _touch_project_meta
    asset_type = str(payload.get("assetType") or payload.get("asset_type") or "").strip()
    if asset_type not in set(_ASSET_REF_COLLECTIONS):
        raise ValueError("资产类型必须是 characters、creatures、scenes 或 props")
    asset_store_path = _asset_store_path("project", project_id)
    asset_store_before = _read_json(asset_store_path, DEFAULT_ASSETS)
    _assert_resource_write_guard(
        asset_store_before,
        payload.get("expectedRevision") or payload.get("expected_revision"),
        payload.get("baseHash") or payload.get("base_hash"),
    )
    asset = copy.deepcopy(payload.get("asset")) if isinstance(payload.get("asset"), dict) else copy.deepcopy(payload)
    # 单资产新建不属于资产拆分范围；编辑时只沿用已保存资产的分组。
    asset = _drop_incoming_asset_grouping_metadata(asset)
    # 单资产编辑只归一化目标行，不能借读取改写其他资产。
    assets = copy.deepcopy(asset_store_before)
    rows = assets.setdefault(asset_type, [])
    asset_id = str(asset.get("id") or "").strip()
    asset_name = str(asset.get("name") or asset.get("title") or "").strip()
    match_index = -1
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        if _asset_is_offline(item):
            continue
        if asset_id and str(item.get("id") or "") == asset_id:
            match_index = index
            break
    if match_index < 0 and asset_name:
        has_same_name = any(
            isinstance(item, dict)
            and not _asset_is_offline(item)
            and str(item.get("name") or "").strip().casefold() == asset_name.casefold()
            for item in rows
        )
        if has_same_name:
            raise ValueError("已有同名资产；编辑已有资产必须传 asset.id，新增资产请使用不重复名称")
    existing = copy.deepcopy(rows[match_index]) if match_index >= 0 and isinstance(rows[match_index], dict) else {}
    if asset_type in set(_ASSET_REF_COLLECTIONS):
        replace_existing_text = _payload_bool(payload, "replaceExisting", "replace_existing")
        merge_existing_text = (
            not replace_existing_text
            if match_index >= 0
            else _payload_bool(payload, "mergeExisting", "merge_existing")
        )
        used_asset_ids = set(_shared_asset_row_ids(rows))
        next_item = _normalize_agent_text_asset_row(
            asset_type,
            asset,
            existing=existing,
            index=match_index if match_index >= 0 else len(rows),
            merge_existing_text=match_index >= 0 and merge_existing_text,
            replace_existing=replace_existing_text,
            used_ids=used_asset_ids,
        )
        if not next_item:
            raise ValueError("资产缺少名称")
        _assert_design_asset_complete(asset_type, next_item)
    else:
        next_item = _deep_merge(existing, copy.deepcopy(asset))
        if not str(next_item.get("id") or "").strip():
            next_item["id"] = _shared_next_short_asset_id(
                asset_type,
                _shared_asset_row_ids(rows),
            )
        if asset_name:
            next_item["name"] = asset_name
        next_item.setdefault("source", "agent-sdk")
        _normalize_asset_item_for_storage(project_id, next_item)
    if match_index >= 0:
        rows[match_index] = next_item
    else:
        rows.append(next_item)
    if asset_type in set(_ASSET_REF_COLLECTIONS):
        _sort_asset_rows_by_source_order(rows, _asset_source_order_for_project(project_id))
    assets["revision"] = _resource_revision_value(asset_store_before) + 1
    assets["updatedAt"] = _now()
    _write_json(_asset_store_path("project", project_id), assets)
    _append_resource_revision(
        project_id,
        resource="assets",
        relative_path="assets/assets.json",
        document=asset_store_before,
        reason=str(payload.get("reason") or "upsert_asset"),
        user_instruction=str(payload.get("userInstruction") or payload.get("user_instruction") or ""),
    )
    _touch_project_meta(project_id)
    response = {
        "success": True,
        "asset": _hydrate_asset_row_for_ui(project_id, next_item),
        "changedResources": [asset_type],
        "focusTarget": {"section": asset_type, "assetTab": asset_type, "assetId": next_item.get("id")},
        "projectChanged": True,
    }
    return response


def upsert_asset(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _JSON_WRITE_LOCK:
        return _upsert_asset_unlocked(project_id, payload)
