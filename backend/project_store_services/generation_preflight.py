# -*- coding: utf-8 -*-
"""画布节点生成预检及可选校验结果写回。"""
from __future__ import annotations

import copy
import traceback
from .canvas_store_queries import read_canvas_task_context_v4
from .canvas_store_mutations import write_canvas_card_records_v4
from .generation_config import (
    resolve_generation_config,
)
from .generation_input_context import (
    _workflow_node_by_id,
    _workflow_generation_config_source_node,
    _workflow_resolved_prompt_text,
    _workflow_route_by_id,
)
from .generation_reference_validation import (
    WORKFLOW_NODE_SLOT_SCHEMA,
    _video_required_slot_status,
    _video_storyboard_sheet_transport_blocker,
)
from .projects import (
    _touch_project_meta,
)
from .reference_utils import (
    merge_reference_ids as _merge_reference_ids,
)
from .splitting_templates import (
    _string_list,
)
from .store_core import (
    _JSON_WRITE_LOCK,
    _now,
)
from typing import (
    Any,
)


def _canvas_mutation_returns_workflow(payload: dict[str, Any]) -> bool:
    # Local canvas mutations return ACK/version by default; full workflow payloads must be explicit.
    for key in ("returnWorkflow", "return_workflow", "includeWorkflow", "include_workflow"):
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() not in {"0", "false", "no", "off"}
    return False


def _assert_canvas_mutation_does_not_return_workflow(
    payload: dict[str, Any],
    operation_label: str = "画布操作",
) -> None:
    if _canvas_mutation_returns_workflow(payload):
        raise ValueError(f"{operation_label}不再返回完整 workflow；需要完整状态时请单独调用 get_canvas_snapshot。")
    if payload.get("baseHash") or payload.get("base_hash"):
        raise ValueError(f"{operation_label}不再支持 baseHash 全量写入；请使用 expectedRevision。")


def _canvas_mutation_returns_production_status(payload: dict[str, Any]) -> bool:
    for key in (
        "returnProductionStatus",
        "return_production_status",
        "includeProductionStatus",
        "include_production_status",
    ):
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() not in {"0", "false", "no", "off"}
    return _canvas_mutation_returns_workflow(payload)


def _preflight_write_back_enabled(payload: dict[str, Any]) -> bool:
    for key in (
        "writeBack",
        "write_back",
        "commitPreflight",
        "commit_preflight",
        "persistPreflight",
        "persist_preflight",
    ):
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() not in {"0", "false", "no", "off"}
    return False


def preflight_workflow_node(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
    *,
    workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .production_status import update_episode_production_status
    from .workflow_asset_resolution import resolve_workflow_node_inputs
    from .workflow_projection import get_canvas_workflow_projection
    if not episode_id:
        raise ValueError("缺少 episodeId")
    payload = copy.deepcopy(payload) if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "预检画布节点")
    write_back = _preflight_write_back_enabled(payload)
    node_id_hint = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    provided_workflow = isinstance(workflow, dict)
    workflow = workflow if isinstance(workflow, dict) else (
        read_canvas_task_context_v4(project_id, episode_id, node_id_hint, detail="full")
        if node_id_hint
        else get_canvas_workflow_projection(project_id, episode_id)
    )
    input_snapshot: dict[str, Any] = {}
    input_snapshot_error = ""
    input_node_id = node_id_hint
    requested_node = _workflow_node_by_id(workflow, node_id_hint)
    if requested_node.get("type") == "video.result":
        owner = _workflow_generation_config_source_node(workflow, requested_node, "video")
        input_node_id = str(owner.get("id") or node_id_hint)
        if input_node_id != node_id_hint and not provided_workflow:
            # Result neighborhoods may omit the task's own material inputs.
            workflow = read_canvas_task_context_v4(project_id, episode_id, input_node_id, detail="full")
            if not _workflow_node_by_id(workflow, node_id_hint):
                workflow.setdefault("nodes", []).append(requested_node)
    if node_id_hint:
        try:
            input_snapshot = resolve_workflow_node_inputs(
                project_id,
                episode_id,
                {"nodeId": input_node_id},
                workflow=workflow,
            )
        except Exception:
            print(traceback.format_exc(), flush=True)
            input_snapshot_error = "未能解析节点输入链接，请检查 slot 链接状态"
        else:
            input_reference_ids = _string_list(input_snapshot.get("referenceMediaIds"))
            if input_snapshot.get("assetRefsResolvedByInputLinks"):
                payload["assetRefsResolvedByInputLinks"] = True
                payload["referenceMediaIds"] = input_reference_ids
                payload.pop("reference_media_ids", None)
                payload.pop("explicitReferenceMediaIds", None)
                payload.pop("explicit_reference_media_ids", None)
                payload.pop("assetReferenceMediaIds", None)
                payload.pop("asset_reference_media_ids", None)
            elif input_reference_ids:
                payload["referenceMediaIds"] = _merge_reference_ids(
                    payload.get("referenceMediaIds"),
                    payload.get("reference_media_ids"),
                    input_reference_ids,
                )
    check = resolve_generation_config(project_id, episode_id, payload, workflow=workflow)
    node_id = str(check.get("nodeId") or payload.get("nodeId") or payload.get("node_id") or "").strip()
    if not node_id:
        raise ValueError("缺少 nodeId")
    if node_id != node_id_hint and not _workflow_node_by_id(workflow, node_id):
        workflow = read_canvas_task_context_v4(project_id, episode_id, node_id, detail="full")
        check = resolve_generation_config(project_id, episode_id, payload, workflow=workflow)
    node = _workflow_node_by_id(workflow, node_id)
    if not node:
        raise FileNotFoundError("未找到要预检的工作流节点")
    data = node.setdefault("data", {})
    if not isinstance(data, dict):
        data = {}
        node["data"] = data

    media_type = str(check.get("mediaType") or "video")
    strategy = str(check.get("strategy") or "")
    resolved_config = check.get("resolvedConfig") if isinstance(check.get("resolvedConfig"), dict) else {}
    blocking = list(check.get("blockingIssues") or [])
    warnings = list(check.get("warnings") or [])
    if input_snapshot_error and input_snapshot_error not in blocking:
        blocking.append(input_snapshot_error)
    task_node = _workflow_node_by_id(workflow, input_node_id or node_id)
    is_character_replace = media_type == "video" and task_node.get("type") == "video.character_replace"
    prompt_text, prompt_source_node_id = _workflow_resolved_prompt_text(workflow, node, media_type)
    if prompt_text:
        resolved_config["promptText"] = prompt_text
        if prompt_source_node_id:
            resolved_config["promptSourceNodeId"] = prompt_source_node_id
    elif not is_character_replace:
        if media_type == "image" and node.get("workChainId"):
            blocking.append("请先生成或填写分镜脚本")
        else:
            blocking.append("缺少可用于生成的提示词")

    if is_character_replace and len(prompt_text) > 2048:
        blocking.append("角色替换说明不能超过 2048 字符")

    if not input_snapshot and not input_snapshot_error:
        try:
            input_snapshot = resolve_workflow_node_inputs(
                project_id,
                episode_id,
                {"nodeId": input_node_id or node_id},
                workflow=workflow,
            )
        except Exception:
            print(traceback.format_exc(), flush=True)
            input_snapshot_error = "未能解析节点输入链接，请检查 slot 链接状态"
    if input_snapshot_error and input_snapshot_error not in blocking:
        blocking.append(input_snapshot_error)

    if media_type == "video" and input_snapshot:
        from .video_task_card_references import video_task_card_current_reference_snapshot
        references = video_task_card_current_reference_snapshot(
            project_id, episode_id, workflow, input_node_id or node_id, input_snapshot,
            for_generation=True,
        )
        if references:
            input_snapshot = references["inputSnapshot"]

    if input_snapshot.get("assetRefsResolvedByInputLinks"):
        resolved_config["assetRefsResolvedByInputLinks"] = True
        resolved_config.pop("referenceMediaIds", None)
        resolved_config.pop("reference_media_ids", None)
        resolved_config.pop("explicitReferenceMediaIds", None)
        resolved_config.pop("explicit_reference_media_ids", None)
        resolved_config.pop("assetReferenceMediaIds", None)
        resolved_config.pop("asset_reference_media_ids", None)
    input_reference_ids = _string_list(input_snapshot.get("referenceMediaIds"))
    if input_reference_ids:
        if resolved_config.get("assetRefsResolvedByInputLinks"):
            resolved_config["referenceMediaIds"] = input_reference_ids
            resolved_config["explicitReferenceMediaIds"] = input_reference_ids
        else:
            resolved_config["referenceMediaIds"] = _merge_reference_ids(
                resolved_config.get("referenceMediaIds"),
                input_reference_ids,
            )

    required_slots: list[dict[str, Any]] = []
    needs_relink = input_snapshot.get("needsRelink") if isinstance(input_snapshot.get("needsRelink"), list) else []
    if needs_relink:
        blocking.append(f"有 {len(needs_relink)} 个输入链接缺少明确 slot，请重新链接后再运行")

    if media_type == "video":
        if task_node.get("type") == "video.storyboard" and (
            task_node.get("workChainId") or (task_node.get("data") or {}).get("workChainId")
        ):
            from .video_boundary_plan import work_chain_video_boundary_plan
            try:
                boundary_plan = work_chain_video_boundary_plan(
                    workflow, task_node, project_id=project_id, episode_id=episode_id,
                )
            except ValueError as exc:
                blocking.append(str(exc))
                boundary_plan = {}
            if boundary_plan:
                resolved_config["videoInputPlan"] = copy.deepcopy(boundary_plan)
                if boundary_plan["mode"] == "native_keyframe":
                    from .video_boundary_plan import validate_direct_continuation_first_frame
                    try:
                        validate_direct_continuation_first_frame(
                            project_id, episode_id, workflow, task_node, boundary_plan,
                            input_snapshot.get("inputLinks") or [],
                        )
                    except ValueError as exc:
                        blocking.append(str(exc))
                    strategy = "native_keyframe_video"
                    resolved_config.update({"strategy": strategy, "inputMode": "native_keyframe",
                                            "referenceMode": "native_keyframe", "videoInputMode": "native_keyframe"})
                    from .generation_reference_validation import _snapshot_row_has_media_reference
                    frame_rows = (input_snapshot.get("groupedBySlot") or {}).get("frame_reference") or []
                    has_last = any(
                        row.get("frameRole") == "last_frame" and row.get("useNativeFrame") is not False
                        and _snapshot_row_has_media_reference(row)
                        for row in frame_rows if isinstance(row, dict)
                    )
                    required_slots.append({"slot": "last_frame", "label": "目标原生尾帧",
                                           "required": True, "satisfied": bool(has_last),
                                           "reason": "" if has_last else "缺少本镜终态目标尾帧"})
                    if not has_last:
                        blocking.append("缺少本镜终态目标尾帧")
                elif boundary_plan["boundaryKind"] == "time_space_jump":
                    if (input_snapshot.get("groupedBySlot") or {}).get("visual_handoff_reference"):
                        blocking.append("时空跳转不能沿用上一段视觉交接图")
        slot_requirements, slot_blocking, slot_warnings = _video_required_slot_status(
            project_id,
            episode_id,
            workflow,
            node_id,
            strategy,
            resolved_config,
            input_snapshot,
        )
        required_slots.extend(slot_requirements)
        blocking.extend(slot_blocking)
        warnings.extend(slot_warnings)
        storyboard_transport_blocker = _video_storyboard_sheet_transport_blocker(
            strategy,
            resolved_config,
            input_snapshot,
        )
        if storyboard_transport_blocker and storyboard_transport_blocker not in blocking:
            blocking.append(storyboard_transport_blocker)

    capability_check = {
        "success": not blocking,
        "checkedAt": _now(),
        "mediaType": media_type,
        "strategy": strategy,
        "modelId": resolved_config.get("modelId") or resolved_config.get("model_id") or "",
        "resolvedConfig": copy.deepcopy(resolved_config),
        "warnings": warnings,
        "blockingIssues": blocking,
        "slotSchema": copy.deepcopy(WORKFLOW_NODE_SLOT_SCHEMA.get(media_type) or []),
        "requiredSlots": required_slots,
        "inputSnapshot": {
            "inputLinks": copy.deepcopy(input_snapshot.get("inputLinks") or []),
            "groupedBySlot": copy.deepcopy(input_snapshot.get("groupedBySlot") or {}),
            "referenceMediaIds": copy.deepcopy(input_snapshot.get("referenceMediaIds") or []),
            "needsRelink": copy.deepcopy(needs_relink),
        },
        "qualityGates": {
            "blockingIssueCount": len(blocking),
            "warningCount": len(warnings),
        },
    }
    data["capabilityCheck"] = capability_check
    quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
    generation_config = data.get("generationConfig") if isinstance(data.get("generationConfig"), dict) else {}
    quality["modelPreflight"] = copy.deepcopy(capability_check)
    if not blocking and isinstance(generation_config, dict):
        data["generationConfig"] = generation_config
    data["quality"] = quality
    data["status"] = "preflight_failed" if blocking else "ready"

    saved_result: dict[str, Any] = {
        "workflowVersion": workflow.get("version"),
        "changedResources": [],
    }
    if write_back:
        with _JSON_WRITE_LOCK:
            saved_result = write_canvas_card_records_v4(project_id, episode_id, [copy.deepcopy(node)])
            _touch_project_meta(project_id)
            workflow["version"] = saved_result.get("workflowVersion") or workflow.get("version")
    saved_workflow = workflow
    return_production_status = write_back and _canvas_mutation_returns_production_status(payload)
    production_status = None
    if return_production_status:
        try:
            status_result = update_episode_production_status(project_id, episode_id)
            production_status = status_result.get("status")
        except Exception:
            print(traceback.format_exc(), flush=True)
    saved_node = _workflow_node_by_id(saved_workflow, node_id)
    route_id = str(check.get("routeId") or payload.get("routeId") or payload.get("route_id") or "").strip()
    saved_route = _workflow_route_by_id(saved_workflow, route_id) if route_id else {}
    check_route = check.get("route") if isinstance(check.get("route"), dict) else {}
    mutation_fields = {
        key: copy.deepcopy(saved_result.get(key))
        for key in ("txId", "seq", "revision", "baseRevision", "opType", "records", "changedResources")
        if saved_result.get(key) is not None
    }
    changed_resources = list(mutation_fields.get("changedResources") or (["canvas_node"] if write_back else []))
    if production_status and "episode_production_status" not in changed_resources:
        changed_resources.append("episode_production_status")
    mutation_fields["changedResources"] = changed_resources
    result = {
        **check,
        "success": not blocking,
        "route": copy.deepcopy(saved_route or check_route),
        "node": copy.deepcopy(saved_node or node),
        "warnings": warnings,
        "blockingIssues": blocking,
        "qualityGates": capability_check["qualityGates"],
        "preflight": capability_check,
        "workflowVersion": saved_result.get("workflowVersion"),
        **mutation_fields,
        "writeBack": write_back,
        "projectChanged": write_back,
    }
    if return_production_status:
        result["productionStatus"] = production_status
    return result
