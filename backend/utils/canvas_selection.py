"""Canvas multi-selection commands: validate the complete set before one write."""
from project_store_services.canvas_store_database import retry_canvas_mutation_v4, validate_canvas_revision_v4
from project_store_services.canvas_store_queries import get_canvas_records_v4
from project_store_services.planning_contract import _is_user_locked_item
from project_store_services.workflow_canvas_deletion import _CanvasNodeDeletion
from project_store_services.workflow_contract import _mark_visual_handoff_user_position, _workflow_layout_position, _workflow_mutation_event_fields
from project_store_services.workflow_projection import _workflow_cards_mutation_write


def delete_canvas_selection(project_id, episode_id, payload):
    from project_store_services.task_storage import _TASK_STORAGE_LOCK
    node_ids = payload.get("nodeIds")
    if not isinstance(node_ids, list) or not node_ids or any(not isinstance(value, str) or not value.strip() for value in node_ids):
        raise ValueError("请选择需要删除的卡片")
    node_ids = list(dict.fromkeys(node_ids))
    with _TASK_STORAGE_LOCK:
        return retry_canvas_mutation_v4(
            lambda: _CanvasNodeDeletion(project_id, episode_id, node_ids[0], payload, node_ids=node_ids).run(),
            expected_revision=payload.get("expectedRevision"),
        )


def update_canvas_selection_layout(project_id, episode_id, payload):
    rows = payload.get("positions")
    if not isinstance(rows, list) or not rows:
        raise ValueError("缺少需要移动的卡片")
    positions = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("nodeId"), str) or not row["nodeId"].strip():
            raise ValueError("卡片标识格式不正确")
        position = _workflow_layout_position(row.get("position"))
        if position is None or row["nodeId"] in positions:
            raise ValueError("卡片坐标或标识格式不正确")
        positions[row["nodeId"]] = position

    def mutate():
        snapshot = get_canvas_records_v4(project_id, episode_id, {"ids": {"nodeIds": list(positions)}, "detail": "full"})
        validate_canvas_revision_v4(snapshot["currentRevision"], payload.get("expectedRevision"))
        nodes = snapshot["records"]["nodes"]
        if {node["id"] for node in nodes} != set(positions):
            raise ValueError("移动的卡片已变化，请刷新画布")
        for node in nodes:
            if _is_user_locked_item(node) or node.get("draggable") is False:
                raise ValueError("选中卡片中有禁止移动的卡片")
            if node.get("position") != positions[node["id"]]:
                _mark_visual_handoff_user_position(node)
            node["position"] = positions[node["id"]]
        result = _workflow_cards_mutation_write(
            project_id, episode_id, nodes, op_type="layout_patch",
            changed_resources=["canvas_node"], expected_revision=snapshot["currentRevision"],
        )
        return {
            "success": True, "projectChanged": True, "episodeId": episode_id,
            "nodes": [{"id": node["id"], "type": node["type"], "position": node["position"], "data": {}} for node in nodes],
            "workflowVersion": result.get("workflowVersion"),
            **_workflow_mutation_event_fields(result, ["canvas_node"]),
        }

    return retry_canvas_mutation_v4(mutate, expected_revision=payload.get("expectedRevision"))
