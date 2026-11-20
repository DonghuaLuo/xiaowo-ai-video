"""Read live inputs from their owning cards, independent of chain origin."""

from typing import Any

from .canvas_ownership import node_work_chain_id


def card_text(data: dict[str, Any] | None, key: str) -> str:
    value = data.get(key) if isinstance(data, dict) else None
    return value.strip() if isinstance(value, str) else ""


def script_source_text(data: dict[str, Any] | None) -> str:
    return card_text(data, "cinematicStoryText") or card_text(data, "sourceFactText")


def script_narrative_mode(data: dict[str, Any] | None) -> str:
    mode = card_text(data, "narrativeMode") or "drama"
    if mode != "drama":
        raise ValueError("旁白讲述模式尚未开放")
    return mode


def work_chain_stage_node(
    workflow: dict[str, Any], current_node: dict[str, Any] | None, node_type: str,
) -> dict[str, Any] | None:
    if not isinstance(current_node, dict):
        return None
    if current_node.get("type") == node_type:
        return current_node
    chain_id = node_work_chain_id(current_node)
    if not chain_id:
        return None
    route_id = str(current_node.get("routeId") or "").strip()
    matches = [
        node for node in workflow.get("nodes", [])
        if isinstance(node, dict) and node.get("type") == node_type
        and node_work_chain_id(node) == chain_id
        and (not route_id or str(node.get("routeId") or "").strip() == route_id)
    ]
    if len(matches) > 1:
        raise ValueError("工作链包含重复环节，无法确定输入来源")
    return matches[0] if matches else None
