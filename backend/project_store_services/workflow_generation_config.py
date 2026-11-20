# -*- coding: utf-8 -*-
"""生成配置继承、输入快照和素材清单。"""
from __future__ import annotations

import copy
import traceback
from .video_reference_metadata import video_reference_usage
from .model_provider_config import (
    _project_model_config,
)
from .workflow_asset_resolution import (
    resolve_workflow_node_inputs,
)
from .workflow_contract import (
    _VISUAL_HANDOFF_SLOT,
    _WORKFLOW_VIDEO_TASK_NODE_TYPES,
    _node_route_id,
    _node_segment_id,
    _workflow_is_result_node_type,
    _workflow_is_video_task_type,
    _workflow_node,
    _workflow_node_owns_generation_config,
    _workflow_node_payload_data,
    _workflow_node_provenance,
    _workflow_node_type_value,
    _workflow_node_work_chain_id,
)
from .workflow_input_resolution import (
    _link_reference_media_id,
    _link_slot,
    _workflow_director_board_for_context,
)
from typing import (
    Any,
)
from utils.frame_references import (
    frame_options,
    frame_reference_brief,
    is_frame_image,
)
from utils.video_references import reference_rows_in_transport_order


def _workflow_task_config_from_node(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    generation_config = data.get("generationConfig") if isinstance(data.get("generationConfig"), dict) else {}
    return copy.deepcopy(generation_config)


def _clean_runtime_generation_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if item is None:
            continue
        if isinstance(item, str) and not item.strip():
            continue
        if isinstance(item, dict):
            nested = _clean_runtime_generation_config(item)
            if nested:
                cleaned[key] = nested
            continue
        cleaned[key] = copy.deepcopy(item)
    return cleaned


def _runtime_generation_config_from_node(
    node: dict[str, Any],
    generation_config_override: dict[str, Any] | None = None,
    *,
    generation_config_provided: bool = False,
) -> dict[str, Any]:
    if generation_config_provided:
        return _clean_runtime_generation_config(generation_config_override)
    return _clean_runtime_generation_config(_workflow_task_config_from_node(node))


def _append_unique_text(items: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in items:
        items.append(text)


def _workflow_generation_config_source_types(node_type: str) -> set[str]:
    normalized = str(node_type or "").strip()
    if normalized == "video.result":
        return set(_WORKFLOW_VIDEO_TASK_NODE_TYPES)
    if normalized == "storyboard.image":
        return {"storyboard.card"}
    return set()


def _workflow_generation_config_source_ids(node: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    data = _workflow_node_payload_data(node)
    provenance = _workflow_node_provenance(node)
    for source in (data, provenance):
        for key in (
            "resultOfNodeId",
            "result_of_node_id",
            "sourceNodeId",
            "source_node_id",
            "taskNodeId",
            "task_node_id",
            "promptNodeId",
            "prompt_node_id",
        ):
            _append_unique_text(ids, source.get(key))
    input_links = data.get("inputLinks")
    if isinstance(input_links, list):
        for link in input_links:
            if not isinstance(link, dict):
                continue
            for key in ("sourceNodeId", "source_node_id", "source"):
                _append_unique_text(ids, link.get(key))
    return ids


def _workflow_generation_config_source_node(
    workflow: dict[str, Any],
    selected_node: dict[str, Any] | None,
    requested_node: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    selected = selected_node if isinstance(selected_node, dict) else {}
    requested = requested_node if isinstance(requested_node, dict) else {}
    direct_node = requested or selected
    direct_type = _workflow_node_type_value(direct_node)
    if direct_node and not _workflow_is_result_node_type(direct_type):
        if _workflow_node_owns_generation_config(direct_type):
            return direct_node
        director_node = _workflow_director_board_for_context(workflow, direct_node)
        if director_node:
            return director_node
        return direct_node

    result_node = direct_node or selected
    result_type = _workflow_node_type_value(result_node)
    source_types = _workflow_generation_config_source_types(result_type)
    if not result_node or not source_types:
        return None

    result_id = str(result_node.get("id") or "").strip()
    for source_id in _workflow_generation_config_source_ids(result_node):
        candidate = _workflow_node(workflow, source_id)
        if candidate and _workflow_node_type_value(candidate) in source_types:
            return candidate

    edges = workflow.get("edges")
    if isinstance(edges, list) and result_id:
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            if str(edge.get("target") or edge.get("targetNodeId") or "").strip() != result_id:
                continue
            candidate = _workflow_node(workflow, str(edge.get("source") or edge.get("sourceNodeId") or "").strip())
            if candidate and _workflow_node_type_value(candidate) in source_types:
                return candidate

    result_route_id = _node_route_id(result_node)
    result_segment_id = _node_segment_id(result_node)
    result_work_chain_id = _workflow_node_work_chain_id(workflow, result_node)
    scoped_candidates: list[tuple[int, dict[str, Any]]] = []
    for candidate in workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []:
        if not isinstance(candidate, dict) or _workflow_node_type_value(candidate) not in source_types:
            continue
        score = 0
        if result_segment_id and _node_segment_id(candidate) == result_segment_id:
            score += 4
        if result_route_id and _node_route_id(candidate) == result_route_id:
            score += 2
        if result_work_chain_id and _workflow_node_work_chain_id(workflow, candidate) == result_work_chain_id:
            score += 1
        if score > 0:
            scoped_candidates.append((score, candidate))
    if scoped_candidates:
        scoped_candidates.sort(key=lambda item: item[0], reverse=True)
        return scoped_candidates[0][1]
    return None


def _runtime_generation_config_for_execution(
    workflow: dict[str, Any],
    selected_node_id: str,
    requested_node_id: str | None = None,
    *,
    request_generation_config: dict[str, Any] | None = None,
    request_generation_config_provided: bool = False,
) -> dict[str, Any]:
    requested_id = str(requested_node_id or "").strip()
    selected_id = str(selected_node_id or "").strip()
    selected_node = _workflow_node(workflow, selected_id) or {}
    requested_node = _workflow_node(workflow, requested_id) if requested_id else None
    source_node = _workflow_generation_config_source_node(workflow, selected_node, requested_node)
    config = _runtime_generation_config_from_node(source_node or {})
    if not config and request_generation_config_provided and not selected_node and not requested_node:
        return _clean_runtime_generation_config(request_generation_config)
    return config


def _workflow_version_model_section(
    node_type: str,
    *,
    version_type: str = "",
    task_type: str = "",
) -> str:
    if task_type == "storyboard_plan" or version_type == "prompt":
        return "agent"
    if task_type == "storyboard_video" or version_type == "video" or _workflow_is_video_task_type(node_type):
        return "video"
    if (
        task_type in {"storyboard_image", "storyboard_image_edit"}
        or version_type == "image"
        or node_type == "prompt.storyboard"
        or node_type == "storyboard.image"

    ):
        return "image"
    return ""


def _safe_model_selection_config(model_section: dict[str, Any]) -> dict[str, Any]:
    safe_keys = (
        "model_id",
        "provider_id",
        "provider_preset_id",
        "endpoint",
        "resolution",
        "storyboard_resolution",
        "aspect_ratio",
        "duration_seconds",
        "fps",
        "input_mode",
    )
    return {
        key: copy.deepcopy(model_section.get(key))
        for key in safe_keys
        if key in model_section and model_section.get(key) is not None
    }


def _workflow_version_payload_snapshots(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_id: str,
    *,
    version_type: str = "",
    task_type: str = "",
    prompt_payload: dict[str, Any] | None = None,
    input_snapshot: dict[str, Any] | None = None,
    preflight_snapshot: dict[str, Any] | None = None,
    generation_config_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node = _workflow_node(workflow, node_id) or {}
    node_type = str(node.get("type") or "")
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
    capability_check = data.get("capabilityCheck") if isinstance(data.get("capabilityCheck"), dict) else {}
    model_preflight = quality.get("modelPreflight") if isinstance(quality.get("modelPreflight"), dict) else {}
    preflight = preflight_snapshot if isinstance(preflight_snapshot, dict) else {}
    resolved_config = (
        preflight.get("resolvedConfig")
        if isinstance(preflight.get("resolvedConfig"), dict)
        else model_preflight.get("resolvedConfig")
        if isinstance(model_preflight.get("resolvedConfig"), dict)
        else capability_check.get("resolvedConfig")
        if isinstance(capability_check.get("resolvedConfig"), dict)
        else data.get("resolvedConfig")
        if isinstance(data.get("resolvedConfig"), dict)
        else {}
    )

    prompt_snapshot: dict[str, Any] = {}
    node_prompt = data.get("prompt")
    if isinstance(node_prompt, dict):
        prompt_snapshot["nodePrompt"] = copy.deepcopy(node_prompt)
    elif isinstance(node_prompt, str) and node_prompt.strip():
        prompt_snapshot["nodePrompt"] = node_prompt
    if isinstance(prompt_payload, dict):
        for key in (
            "storyboardImagePrompt",
            "videoPrompt",
            "video_prompt",
            "userStoryText",
            "userInstruction",
            "revisionApplied",
            "revisionError",
        ):
            if key in prompt_payload:
                prompt_snapshot[key] = copy.deepcopy(prompt_payload.get(key))
        if isinstance(prompt_payload.get("panels"), list):
            prompt_snapshot["panels"] = copy.deepcopy(prompt_payload.get("panels"))
        if prompt_payload.get("panelCount") is not None:
            prompt_snapshot["panelCount"] = prompt_payload.get("panelCount")

    generation_config_snapshot = {
        "node": copy.deepcopy(data.get("generationConfig") if isinstance(data.get("generationConfig"), dict) else {}),
        "runtimeOverride": copy.deepcopy(generation_config_override or {}),
        "resolved": copy.deepcopy(resolved_config),
        "merged": copy.deepcopy(_workflow_task_config_from_node(node)),
    }
    if generation_config_snapshot["runtimeOverride"]:
        generation_config_snapshot["merged"].update(copy.deepcopy(generation_config_snapshot["runtimeOverride"]))
    if resolved_config:
        generation_config_snapshot["merged"].update(copy.deepcopy(resolved_config))

    model_section_name = _workflow_version_model_section(
        node_type,
        version_type=version_type,
        task_type=task_type,
    )
    model_selection_snapshot = copy.deepcopy(data.get("modelSelection") if isinstance(data.get("modelSelection"), dict) else {})
    if model_section_name:
        model_selection_snapshot.setdefault("section", model_section_name)
        try:
            model_config = _project_model_config(project_id)[2]
        except Exception:
            model_config = {}
        model_section = model_config.get(model_section_name) if isinstance(model_config.get(model_section_name), dict) else {}
        if model_section:
            model_selection_snapshot["effectiveModelConfig"] = _safe_model_selection_config(model_section)
    if isinstance(preflight.get("model"), dict):
        model_selection_snapshot["preflightModel"] = copy.deepcopy(preflight.get("model"))
    elif isinstance(model_preflight.get("model"), dict):
        model_selection_snapshot["preflightModel"] = copy.deepcopy(model_preflight.get("model"))

    context_snapshot = {
        "projectId": project_id,
        "episodeId": episode_id,
        "workflowId": workflow.get("id"),
        "nodeId": node_id,
        "nodeType": node_type,
        "routeId": _node_route_id(node),
        "segmentId": _node_segment_id(node),
        "workChainId": _workflow_node_work_chain_id(workflow, node),
        "strategy": str(data.get("strategy") or node.get("strategy") or ""),
        "title": data.get("title"),
        "summary": data.get("summary"),
        "frameSlot": data.get("frameSlot"),
        "sourceRefs": copy.deepcopy(data.get("sourceRefs") or []),
        "shotIds": copy.deepcopy(data.get("shotIds") or []),
        "assetRefs": copy.deepcopy(data.get("assetRefs") or {}),
    }
    if isinstance(prompt_payload, dict) and prompt_payload.get("panelCount") is not None:
        context_snapshot["panelCount"] = prompt_payload.get("panelCount")

    snapshots: dict[str, Any] = {
        "promptSnapshot": prompt_snapshot,
        "generationConfigSnapshot": generation_config_snapshot,
        "modelSelectionSnapshot": model_selection_snapshot,
        "contextSnapshot": context_snapshot,
    }
    resolved_input_snapshot = input_snapshot
    if resolved_input_snapshot is None and node_id:
        try:
            resolved_input_snapshot = resolve_workflow_node_inputs(project_id, episode_id, {"nodeId": node_id})
        except Exception:
            print(traceback.format_exc(), flush=True)
            resolved_input_snapshot = None
    if isinstance(resolved_input_snapshot, dict):
        snapshots["inputLinksSnapshot"] = copy.deepcopy(resolved_input_snapshot.get("inputLinks") or [])
        snapshots["referenceMediaIdsSnapshot"] = copy.deepcopy(resolved_input_snapshot.get("referenceMediaIds") or [])
        snapshots["assetRefsSnapshot"] = copy.deepcopy(resolved_input_snapshot.get("assetRefs") or [])
        snapshots["assetRefsResolvedByInputLinks"] = bool(
            resolved_input_snapshot.get("assetRefsResolvedByInputLinks")
        )
        reference_manifest = _reference_manifest_from_input_snapshot(resolved_input_snapshot)
        if reference_manifest:
            snapshots["referenceManifestSnapshot"] = reference_manifest
        if resolved_input_snapshot.get("needsRelink"):
            snapshots["needsRelink"] = copy.deepcopy(resolved_input_snapshot.get("needsRelink") or [])
    return snapshots


def _reference_manifest_display_name(link: dict[str, Any]) -> str:
    for key in (
        "displayName",
        "display_name",
        "assetName",
        "asset_name",
        "name",
        "title",
        "label",
    ):
        text = str(link.get(key) or "").strip()
        if text:
            return text
    return ""


def _reference_manifest_from_input_snapshot(input_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(input_snapshot, dict):
        return []
    links = reference_rows_in_transport_order([
        link
        for link in input_snapshot.get("inputLinks", [])
        if isinstance(link, dict)
    ] if isinstance(input_snapshot.get("inputLinks"), list) else [])
    by_media_id: dict[str, dict[str, dict[str, Any]]] = {}
    ordered_media_ids: list[str] = []
    for link in links:
        media_id = _link_reference_media_id(link)
        if not media_id:
            continue
        if media_id not in ordered_media_ids:
            ordered_media_ids.append(media_id)
        by_media_id.setdefault(media_id, {}).setdefault(video_reference_usage(link), link)
    snapshot_media_ids = [
        str(item or "").strip()
        for item in input_snapshot.get("referenceMediaIds", [])
        if str(item or "").strip()
    ] if isinstance(input_snapshot.get("referenceMediaIds"), list) else []
    snapshot_media_id_set = set(snapshot_media_ids)
    media_ids = [media_id for media_id in ordered_media_ids if media_id in snapshot_media_id_set]
    media_ids.extend(media_id for media_id in snapshot_media_ids if media_id not in media_ids)
    if not media_ids:
        media_ids = ordered_media_ids
    manifest: list[dict[str, Any]] = []

    def append_manifest_row(media_id: str, link: dict[str, Any]) -> None:
        index = len(manifest) + 1
        slot = _link_slot(link)
        asset_type = str(link.get("assetType") or link.get("asset_type") or "").strip()
        asset_id = str(link.get("assetId") or link.get("asset_id") or "").strip()
        row = {
            "refId": f"R{index:02d}",
            "mediaId": media_id,
            "slot": slot or "storyboard_image",
            "assetId": asset_id,
            "assetType": asset_type,
            "displayName": _reference_manifest_display_name(link),
            "sourceType": str(link.get("sourceType") or link.get("source_type") or "").strip(),
            "sourceNodeId": str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip(),
            **(frame_options(link) if is_frame_image(link) else {}),
        }
        aliases = link.get("aliases")
        if isinstance(aliases, list):
            row["aliases"] = [str(item).strip() for item in aliases if str(item).strip()]
        role = str(link.get("roleInScene") or link.get("role_in_scene") or link.get("description") or "").strip()
        if role and slot != "custom_image":
            row["roleInScene"] = role
        manifest.append(row)

    for media_id in media_ids:
        for link in by_media_id.get(media_id, {"reference_image": {}}).values():
            append_manifest_row(media_id, link)

    # A semantic asset link resolves to its current active media when the provider
    # request is assembled. Keep the manifest aligned with that real transport
    # order by appending asset refs not already represented above.
    by_asset_id = {
        str(link.get("assetId") or link.get("asset_id") or "").strip(): link
        for link in links
        if str(link.get("assetId") or link.get("asset_id") or "").strip()
    }
    asset_ref_rows: list[dict[str, Any]] = []
    raw_asset_refs = input_snapshot.get("assetRefs") or input_snapshot.get("asset_refs")
    if isinstance(raw_asset_refs, list):
        asset_ref_rows = [copy.deepcopy(row) for row in raw_asset_refs if isinstance(row, dict)]
    elif isinstance(raw_asset_refs, dict):
        collection_slots = {
            "characters": "character_reference",
            "creatures": "creature_reference",
            "scenes": "scene_reference",
            "props": "prop_reference",
        }
        for asset_type, slot in collection_slots.items():
            values = raw_asset_refs.get(asset_type)
            values = values if isinstance(values, list) else [values] if values else []
            for value in values:
                if isinstance(value, dict):
                    asset_ref_rows.append({**copy.deepcopy(value), "assetType": asset_type, "slot": slot})
                elif str(value or "").strip():
                    asset_ref_rows.append(
                        {"assetId": str(value).strip(), "assetType": asset_type, "slot": slot}
                    )
    represented_asset_ids = {
        str(row.get("assetId") or "").strip()
        for row in manifest
        if str(row.get("assetId") or "").strip()
    }
    for asset_ref in asset_ref_rows:
        asset_id = str(asset_ref.get("assetId") or asset_ref.get("asset_id") or "").strip()
        if not asset_id or asset_id in represented_asset_ids:
            continue
        linked = by_asset_id.get(asset_id, {})
        merged_link = {**asset_ref, **linked}
        append_manifest_row(_link_reference_media_id(linked) or asset_id, merged_link)
        represented_asset_ids.add(asset_id)
    visual_prefixes = {
        "character_reference": "R",
        "creature_reference": "B",
        "scene_reference": "S",
        "prop_reference": "P",
        "style_reference": "V",
        _VISUAL_HANDOFF_SLOT: "H",
    }
    visual_counts: dict[str, int] = {}
    for row in manifest:
        prefix = visual_prefixes.get(str(row.get("slot") or "").strip())
        if not prefix:
            continue
        visual_counts[prefix] = visual_counts.get(prefix, 0) + 1
        row["visualId"] = f"{prefix}{visual_counts[prefix]:02d}"
    return manifest


def _reference_manifest_prompt(reference_manifest: list[dict[str, Any]]) -> str:
    rows = [row for row in reference_manifest if isinstance(row, dict)]
    if not rows:
        return ""
    lines = [
        "参考图绑定清单：以下参考图序号与随附图片顺序严格一致；若当前分镜图版式允许资产短编号，画面内只使用清单中对应资产的短编号。视觉交接参考图和风格参考图只按参考图用途理解，不作为镜头内对象标签；不得把参考图序号当成资产短编号。",
        "清单中的资产只约束同名、别名或上下文明确为同一身份、同一空间、同一物件的对象；导演镜头计划中需要入画但未绑定的对象，按计划已确定的身份与状态呈现，不得借用已列资产身份。",
    ]
    slot_labels = {
        "custom_image": "自定义图片",
        "character_reference": "角色",
        "creature_reference": "生物",
        "scene_reference": "场景",
        "prop_reference": "道具",
        "style_reference": "风格",
        _VISUAL_HANDOFF_SLOT: "视觉交接参考图",
        "storyboard_image": "故事版分镜参考图",
    }
    for index, row in enumerate(rows, start=1):
        ref_id = str(row.get("refId") or "").strip()
        if is_frame_image(row):
            lines.append(f"参考图{index:02d}：{frame_reference_brief(frame_options(row)['frameRole'], storyboard=True)}")
            continue
        visual_id = str(row.get("visualId") or "").strip()
        transport_label = f"参考图{index:02d}"
        slot = str(row.get("slot") or "").strip()
        label = slot_labels.get(slot, slot or "参考资产")
        if slot in {_VISUAL_HANDOFF_SLOT, "storyboard_image"}:
            name = label
        else:
            name = str(row.get("displayName") or row.get("assetId") or row.get("mediaId") or "").strip()
        aliases = row.get("aliases") if isinstance(row.get("aliases"), list) else []
        alias_text = f"，别名：{'、'.join(str(item) for item in aliases if str(item).strip())}" if aliases else ""
        role = str(row.get("roleInScene") or "").strip()
        if slot == "custom_image":
            lines.append(f"{transport_label}：{label}“{name or transport_label}”。")
            continue
        role_text = f"，用途：{role}" if role else ""
        visual_id_text = f"（资产短编号 {visual_id}）" if visual_id else ""
        if slot in {_VISUAL_HANDOFF_SLOT, "storyboard_image"}:
            lines.append(
                f"{transport_label}{visual_id_text}：{label}{role_text or '，用于理解连续镜头和空间状态'}。"
            )
            continue
        lines.append(
            f"{transport_label}{visual_id_text}：{label}“{name or ref_id or transport_label}”{alias_text}{role_text}。"
        )
    return "\n".join(lines)


def _merge_version_payload_snapshots(
    payload: dict[str, Any],
    snapshots: dict[str, Any],
    *,
    prefer_existing: bool = True,
) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    refreshed_snapshot_keys = {
        "inputLinksSnapshot",
        "referenceMediaIdsSnapshot",
        "assetRefsSnapshot",
        "assetRefsResolvedByInputLinks",
        "referenceManifestSnapshot",
        "needsRelink",
    }
    for key, value in snapshots.items():
        if key in refreshed_snapshot_keys:
            result[key] = copy.deepcopy(value)
            continue
        if key in result and isinstance(result.get(key), dict) and isinstance(value, dict):
            if prefer_existing:
                merged = copy.deepcopy(value)
                merged.update(copy.deepcopy(result.get(key) or {}))
            else:
                merged = copy.deepcopy(result.get(key) or {})
                merged.update(copy.deepcopy(value))
            result[key] = merged
        elif key not in result:
            result[key] = copy.deepcopy(value)
    return result
