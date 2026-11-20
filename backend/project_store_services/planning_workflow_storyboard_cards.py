# -*- coding: utf-8 -*-
"""Insert an editable storyboard card between the director and each image task."""
from __future__ import annotations

import copy
from typing import Any


def add_storyboard_cards(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    by_id = {str(node.get("id") or ""): node for node in nodes}
    for node in nodes:
        if node.get("type") in {"video.storyboard", "video.keyframe"}:
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            data.pop("assetThumbnails", None)
    for image in list(nodes):
        if image.get("type") != "storyboard.image":
            continue
        image_data = image.get("data") if isinstance(image.get("data"), dict) else {}
        if image_data.get("canvasNodeRole") == "image_asset":
            continue
        director_edge = next((edge for edge in edges if edge.get("target") == image.get("id")
                              and by_id.get(str(edge.get("source") or ""), {}).get("type") == "director.board"
                              and (edge.get("data") or {}).get("role") == "generates"), None)
        if not director_edge:
            continue
        director = by_id[str(director_edge["source"])]
        card_id = f"storyboard_card_{image['id']}"
        card_data = {
            "title": "分镜单元",
            "status": "waiting",
            "summary": "生成分镜脚本后显示对应镜头。",
            "workChainId": image.get("workChainId"),
            "routeId": image.get("routeId"),
            "segmentId": image.get("segmentId"),
            "shotNos": [],
            "directorPlanShots": [],
            "inputLinks": [],
            "generationConfig": copy.deepcopy((director.get("data") or {}).get("generationConfig") or {}),
            "modelSelection": copy.deepcopy((director.get("data") or {}).get("modelSelection") or {}),
        }
        card = {
            "id": card_id, "type": "storyboard.card",
            "position": copy.deepcopy(image.get("position") or {"x": 0, "y": 0}),
            "workChainId": image.get("workChainId"), "routeId": image.get("routeId"),
            "segmentId": image.get("segmentId"), "strategy": image.get("strategy"),
            "data": card_data,
        }
        nodes.append(card)
        by_id[card_id] = card
        director_edge["source"] = card_id
        director_edge["sourceHandle"] = "storyboard"
        director_edge["id"] = f"{card_id}_to_{image['id']}"
        edge_data = director_edge.setdefault("data", {})
        edge_data["sourceNodeType"] = "storyboard.card"
        image_data["sourceNodeId"] = card_id
        image_data["resultOfNodeId"] = card_id
        edges.append({
            "id": f"{director['id']}_to_{card_id}",
            "source": director["id"], "sourceHandle": "plan",
            "target": card_id, "targetHandle": "story",
            "locked": True, "deletable": False, "preserveOnReplan": True,
            "data": {
                "kind": "dependency", "role": "context", "sourceNodeType": "director.board",
                "targetNodeType": "storyboard.card", "targetSlot": "story",
                "workChainId": image.get("workChainId"), "routeId": image.get("routeId"),
                "segmentId": image.get("segmentId"),
            },
        })
