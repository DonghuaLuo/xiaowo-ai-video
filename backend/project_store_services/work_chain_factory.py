"""Pure record construction for a new independent work chain."""

from typing import Any


def build_independent_work_chain(work_chain_id: str, position: dict[str, float]) -> dict[str, Any]:
    route_id, segment_id = f"route_{work_chain_id}", f"segment_{work_chain_id}"
    roles = (
        ("script", "prompt.storyboard", "片段剧本", 340, 280),
        ("director", "director.board", "分镜脚本", 380, 360),
        ("storyboard_card", "storyboard.card", "分镜单元", 380, 300),
        ("storyboard", "storyboard.image", "分镜图", 320, 300),
        ("video", "video.storyboard", "视频生成", 360, 300),
        ("result", "video.result", "视频片段", 360, 260),
    )
    ids = {role: f"{work_chain_id}_{role}" for role, *_ in roles}
    membership = {"workChainId": work_chain_id, "routeId": route_id, "segmentId": segment_id}
    nodes = []
    for index, (role, node_type, title, width, height) in enumerate(roles):
        data: dict[str, Any] = {
            "title": title, "status": "draft", "prompt": {},
            "cardState": {"size": {"width": width, "height": height}},
        }
        if role == "script":
            data.update({"sourceFactText": "", "cinematicStoryText": "", "narrativeMode": "drama"})
        elif role == "storyboard_card":
            data["generationConfig"] = {"purpose": "storyboard_image"}
            data.update({"shotNos": [], "directorPlanShots": [], "inputLinks": []})
        elif role == "video":
            data["generationConfig"] = {"purpose": "storyboard_to_video", "referenceMode": "storyboard_image", "requiresReferenceMedia": True}
            data["videoTaskCard"] = {"finalVideoPrompt": ""}
        if role in {"storyboard", "result"}:
            data["resultOfNodeId"] = ids["storyboard_card" if role == "storyboard" else "video"]
        if role == "storyboard":
            data["sourceNodeId"] = ids["storyboard_card"]
        nodes.append({
            "id": ids[role], "type": node_type, **membership,
            "strategy": "storyboard_multi_shot",
            "position": {"x": position["x"] + index * 613, "y": position["y"]},
            "data": data,
        })
    edges = []
    for index, (source_handle, target_handle, kind, role) in enumerate((
        ("prompt", "story", "dependency", "context"),
        ("plan", "story", "dependency", "context"),
        ("storyboard", "generates", "dependency", "generates"),
        ("image", "video_input", "material", "storyboard_image"),
        ("video", "generates", "dependency", "generates"),
    )):
        source, target = nodes[index], nodes[index + 1]
        edge_id = f"{source['id']}_to_{target['id']}"
        edge_data = {**membership, "kind": kind, "role": role, "sourceNodeType": source["type"], "targetNodeType": target["type"], "locked": True}
        if kind == "material":
            edge_data.update({"inputLinkId": edge_id, "targetSlot": "storyboard_image", "sourceType": "generated_media"})
            target["data"]["inputLinks"] = [{"id": edge_id, "sourceNodeId": source["id"], "targetNodeId": target["id"], **edge_data}]
        edges.append({"id": edge_id, "source": source["id"], "target": target["id"], "sourceHandle": source_handle, "targetHandle": target_handle, "deletable": False, "data": edge_data})
    return {
        "nodes": nodes, "edges": edges,
        "routes": [{"id": route_id, **membership, "strategy": "storyboard_multi_shot", "status": "draft", "shotIds": []}],
        "workChains": [{"id": work_chain_id, "label": "独立工作链", "origin": {"kind": "independent", "sourceNodeId": None}, "routeIds": [route_id], "segmentIds": [segment_id], "shotIds": [], "status": "draft"}],
    }
