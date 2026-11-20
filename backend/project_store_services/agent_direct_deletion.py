# -*- coding: utf-8 -*-
"""Stage agent-requested local deletions and execute only a confirmed snapshot."""

from __future__ import annotations

import copy
from typing import Any

from .assets import delete_asset, list_assets
from .canvas_store_queries import read_canvas_workflow_projection_v4
from .project_resource_revisions import _json_hash, _resource_revision_value
from .store_core import _emit_agent_event, _now
from .workflow_canvas_deletion import delete_workflow_item
from .workflow_input_links import unlink_workflow_input


DIRECT_DELETE_OPERATIONS = {
    "delete_asset": "confirm_direct_asset_delete",
    "delete_workflow_node": "confirm_direct_workflow_delete",
    "unlink_workflow_input": "confirm_direct_workflow_unlink",
}


def _direct_delete_snapshot(project_id: str, episode_id: str, tool_name: str) -> tuple[int, str]:
    if tool_name == "delete_asset":
        assets = list_assets("project", project_id, hydrate=False)
        return _resource_revision_value(assets), _json_hash(assets)
    workflow = read_canvas_workflow_projection_v4(project_id, episode_id, detail="full")
    return int(workflow.get("version") or 0), ""


def stage_agent_direct_delete(
    project_id: str, episode_id: str, session_id: str | None,
    tool_name: str, args: dict[str, Any],
) -> dict[str, Any]:
    operation_type = DIRECT_DELETE_OPERATIONS.get(tool_name)
    if not operation_type:
        raise ValueError("不支持的删除操作")
    target_args = copy.deepcopy(args)
    if tool_name == "delete_asset":
        if str(target_args.get("scope") or "project").strip() != "project":
            raise ValueError("智能体只能删除当前项目的资产")
        asset_type = str(target_args.get("assetType") or target_args.get("asset_type") or "").strip()
        asset_id = str(target_args.get("assetId") or target_args.get("asset_id") or "").strip()
        assets = list_assets("project", project_id, hydrate=False)
        if not isinstance(assets.get(asset_type), list):
            raise ValueError("资产类型无效")
        asset = next((item for item in assets[asset_type] if isinstance(item, dict) and str(item.get("id") or "") == asset_id), None)
        if not asset:
            raise ValueError("要删除的资产不存在，请重新读取资产列表")
        target = str(asset.get("name") or asset.get("title") or asset_id)
        message = f"待确认删除项目资产：{target}（{asset_type} / {asset_id}）。确认前不会删除。"
    elif tool_name == "delete_workflow_node":
        item_type = str(target_args.get("itemType") or "node").strip()
        item_id = str(target_args.get("itemId") or target_args.get("nodeId") or "").strip()
        if item_type not in {"node", "route", "workChain"} or not item_id:
            raise ValueError("删除画布内容需要明确的类型和 ID")
        if item_type == "route":
            raise ValueError("画布路线由工作链维护，不能单独删除；请明确需要删除的独立工作链")
        workflow = read_canvas_workflow_projection_v4(project_id, episode_id, detail="full")
        collection = {"node": "nodes", "route": "routes", "workChain": "workChains"}[item_type]
        if not any(isinstance(item, dict) and str(item.get("id") or "") == item_id for item in workflow.get(collection) or []):
            raise ValueError("要删除的画布内容不存在，请重新读取画布")
        message = f"待确认删除 {episode_id} 的{item_type}：{item_id}。关联内容也可能一并移除；确认前不会删除。"
    else:
        node_id = str(target_args.get("nodeId") or target_args.get("targetNodeId") or "").strip()
        selectors = [str(target_args.get(key) or "").strip() for key in ("linkId", "sourceId", "slot", "targetSlot")]
        if not node_id or not any(selectors):
            raise ValueError("移除输入关联需要明确任务卡和关联选择条件")
        selector = next(value for value in selectors if value)
        message = f"待确认移除 {episode_id} 任务卡 {node_id} 的输入关联 {selector}。确认前不会修改画布。"
    revision, base_hash = _direct_delete_snapshot(project_id, episode_id, tool_name)
    target_args["expectedRevision"] = revision
    if base_hash:
        target_args["baseHash"] = base_hash
    operation = {
        "type": operation_type, "operationType": operation_type,
        "source": "agent_tool", "sessionId": str(session_id or ""),
        "createdAt": _now(), "requiresUserConfirmation": True,
        "expectedNextTool": tool_name, "nextAllowedTools": [tool_name],
        "proposal": {"episodeId": episode_id, "message": message},
        "commitPayload": {"toolName": tool_name, "episodeId": episode_id,
                          "args": target_args, "expectedRevision": revision,
                          "baseHash": base_hash},
        "message": message,
    }
    return {"success": True, "status": "pending_confirmation",
            "requiresUserConfirmation": True, "projectChanged": False,
            "message": message, "pendingOperation": operation}


def agent_direct_delete_is_current(project_id: str, operation: dict[str, Any]) -> bool:
    payload = operation.get("commitPayload") if isinstance(operation.get("commitPayload"), dict) else {}
    tool_name = str(payload.get("toolName") or "")
    episode_id = str(payload.get("episodeId") or "")
    if tool_name not in DIRECT_DELETE_OPERATIONS or not episode_id:
        return False
    try:
        revision, base_hash = _direct_delete_snapshot(project_id, episode_id, tool_name)
        return (revision == int(payload.get("expectedRevision"))
                and (not payload.get("baseHash") or base_hash == payload["baseHash"]))
    except (TypeError, ValueError, OSError):
        return False


def execute_agent_direct_delete(project_id: str, operation: dict[str, Any]) -> dict[str, Any]:
    payload = operation.get("commitPayload") if isinstance(operation.get("commitPayload"), dict) else {}
    tool_name = str(payload.get("toolName") or "")
    if tool_name not in DIRECT_DELETE_OPERATIONS or operation.get("type") != DIRECT_DELETE_OPERATIONS[tool_name]:
        raise ValueError("待确认删除操作与目标不符")
    if not agent_direct_delete_is_current(project_id, operation):
        raise ValueError("删除目标已变化，请重新提出删除请求并确认")
    episode_id = str(payload["episodeId"])
    args = copy.deepcopy(payload.get("args") if isinstance(payload.get("args"), dict) else {})
    if tool_name == "delete_asset":
        result = delete_asset(
            str(args.get("assetType") or args.get("asset_type") or ""),
            str(args.get("assetId") or args.get("asset_id") or ""),
            "project", project_id,
            expected_revision=payload["expectedRevision"], base_hash=payload.get("baseHash"),
            reason="agent_confirmed_delete_asset",
            user_instruction=str(args.get("userInstruction") or ""),
        )
    elif tool_name == "delete_workflow_node":
        result = delete_workflow_item(project_id, episode_id, args)
    else:
        result = unlink_workflow_input(project_id, episode_id, args)
    if result.get("success") is False or result.get("projectChanged") is False:
        raise ValueError(str(result.get("message") or "目标未发生变更，请重新读取后再操作"))
    _emit_agent_event("project_changed", {
        "action": tool_name, "projectId": project_id, "episodeId": episode_id,
        "changedResources": result.get("changedResources") or [],
    })
    label = {"delete_asset": "资产", "delete_workflow_node": "画布内容",
             "unlink_workflow_input": "画布输入关联"}[tool_name]
    return {"success": True, "message": f"已{('移除' if tool_name == 'unlink_workflow_input' else '删除')}{label}。",
            "projectChanged": bool(result.get("projectChanged", True)),
            "projectEffect": {"action": tool_name, "changedResources": result.get("changedResources") or []},
            "pendingOperation": None}
