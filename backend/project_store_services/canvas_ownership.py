"""Canvas identity and work-chain ownership, independent of generation logic."""

from __future__ import annotations

import copy
from typing import Any


VIDEO_TASK_NODE_TYPES = frozenset({"video.storyboard", "video.keyframe", "video.character_replace"})


def is_video_task_type(node_type: Any) -> bool:
    return str(node_type or "").strip() in VIDEO_TASK_NODE_TYPES


def node_work_chain_id(node: dict[str, Any]) -> str:
    return str(node.get("workChainId") or "").strip()


def normalize_node_ownership(node: dict[str, Any]) -> str:
    owner = node_work_chain_id(node)
    data = node.setdefault("data", {})
    if data.get("workChainId") not in (None, "", owner):
        raise ValueError("节点的工作链归属字段冲突")
    # data is a UI projection, never an alternative source of membership.
    node["workChainId"] = data["workChainId"] = owner
    return owner


def validate_node_identity_update(previous: dict[str, Any], patch: dict[str, Any]) -> None:
    """General edits cannot reassign an existing node or its identity projections."""
    owner = node_work_chain_id(previous)
    fields = [("workChainId", "work_chain_id")]
    if owner:
        fields.extend((("routeId", "route_id"), ("segmentId", "segment_id")))
    data = patch.get("data") if isinstance(patch.get("data"), dict) else {}
    for canonical, alias in fields:
        expected = str(previous.get(canonical) or "").strip()
        for source in (patch, data):
            for key in (canonical, alias):
                if key in source and str(source[key] or "").strip() != expected:
                    raise ValueError(f"已有节点的 {canonical} 不能通过通用更新修改")


def work_chain_origin(chain: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    origin = chain.get("origin") if isinstance(chain.get("origin"), dict) else {}
    if origin.get("kind") == "independent" and origin.get("sourceNodeId") is None:
        return {"kind": "independent", "sourceNodeId": None}
    if origin.get("kind") == "source_split" and origin.get("sourceNodeId") and workflow.get("canvasKind") != "custom":
        return {"kind": "source_split", "sourceNodeId": str(origin["sourceNodeId"])}
    if origin.get("kind") == "independent_source" and origin.get("sourceNodeId"):
        return {"kind": "independent_source", "sourceNodeId": str(origin["sourceNodeId"])}
    raise ValueError("工作链缺少有效的来源信息")


def video_task_scope(node: dict[str, Any]) -> str:
    if not is_video_task_type(node.get("type")):
        return ""
    return "work_chain" if node_work_chain_id(node) else "standalone"


def normalize_work_chain_origins(workflow: dict[str, Any]) -> None:
    for chain in workflow.get("workChains", []):
        if isinstance(chain, dict):
            chain["origin"] = work_chain_origin(chain, workflow)


def source_work_chain_ids(workflow: dict[str, Any]) -> set[str]:
    return {
        str(chain["id"])
        for chain in workflow.get("workChains", [])
        if isinstance(chain, dict) and chain.get("id")
        and work_chain_origin(chain, workflow)["kind"] == "source_split"
    }


def work_chain_scope(workflow: dict[str, Any], chain_ids: set[str], *, include_source: bool = False) -> dict[str, Any]:
    scoped = copy.deepcopy(workflow)
    scoped["workChains"] = [chain for chain in scoped.get("workChains", []) if chain.get("id") in chain_ids]
    scoped["routes"] = [route for route in scoped.get("routes", []) if route.get("workChainId") in chain_ids]
    source_ids = {
        work_chain_origin(chain, workflow)["sourceNodeId"] for chain in scoped["workChains"]
    } if include_source else set()
    scoped["nodes"] = [node for node in scoped.get("nodes", []) if node_work_chain_id(node) in chain_ids or node.get("id") in source_ids]
    node_ids = {node["id"] for node in scoped["nodes"]}
    scoped["edges"] = [edge for edge in scoped.get("edges", []) if edge.get("source") in node_ids and edge.get("target") in node_ids]
    return scoped
