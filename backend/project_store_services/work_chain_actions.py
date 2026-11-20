"""Read-only recommendations for one work chain; never an execution queue."""

from typing import Any

from .work_chain_context import card_text, script_source_text


WORK_CHAIN_ACTIONS = (
    {"id": "generate_current_cinematic_script", "stateId": "cinematic_script.generated", "taskType": "workflow_cinematic_script_generation", "nodeType": "prompt.storyboard", "label": "生成片段剧本（可选）"},
    {"id": "generate_current_director_plan", "stateId": "director_plan.generated", "taskType": "director_plan_generation", "nodeType": "director.board", "label": "生成分镜脚本"},
    {"id": "generate_current_storyboard_image", "stateId": "storyboard.generated", "taskType": "storyboard_image_generation", "nodeType": "storyboard.image", "label": "生成分镜图（可选）"},
    {"id": "generate_current_visual_handoff_image", "stateId": "visual_handoff.generated", "taskType": "visual_handoff_image_generation", "nodeType": "storyboard.card", "label": "生成视觉交接图（可选）"},
    {"id": "generate_current_video_prompt", "stateId": "video_prompt.ready", "taskType": "video_prompt_generation", "nodeType": "video.storyboard", "label": "生成视频提示词"},
    {"id": "generate_current_storyboard_video", "stateId": "video.generated", "taskType": "storyboard_video_generation", "nodeType": "video.storyboard", "label": "生成视频片段"},
)


def recommend_work_chain_actions(
    nodes: list[dict[str, Any]],
    completed_states: list[str],
    *,
    ready_image_ids: set[str] | None = None,
    generated_handoff_card_ids: set[str] | None = None,
    generated_video_ids: set[str] | None = None,
    pending_video_prompt_ids: set[str] | None = None,
    include_visual_handoff: bool = False,
) -> list[dict[str, Any]]:
    completed = set(completed_states)
    ordered_nodes = [
        node for _, node in sorted(
            enumerate(nodes),
            key=lambda row: (
                int(((row[1].get("data") or {}).get("shotGroupOrder") or 0)),
                row[0],
            ),
        )
    ]
    by_type = {node.get("type"): node for node in ordered_nodes if node.get("type") not in {"storyboard.image", "video.storyboard"}}
    images = [node for node in ordered_nodes if node.get("type") == "storyboard.image"]
    videos = [node for node in ordered_nodes if node.get("type") == "video.storyboard"]
    script_data = (by_type.get("prompt.storyboard") or {}).get("data") or {}
    ready_image_ids = ready_image_ids or set()
    generated_handoff_card_ids = generated_handoff_card_ids or set()
    generated_video_ids = generated_video_ids or set()
    ordered_cards = [node for node in ordered_nodes if node.get("type") == "storyboard.card"]
    cards_by_id = {str(node.get("id") or ""): node for node in ordered_cards}
    def image_owner_id(node: dict[str, Any]) -> str:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        return str(data.get("resultOfNodeId") or data.get("sourceNodeId") or "").strip()

    current_images = [
        image for image in images
        if image_owner_id(image) in cards_by_id
        and str((cards_by_id[image_owner_id(image)].get("data") or {}).get("shotGroupId") or "")
        and str((image.get("data") or {}).get("shotGroupId") or "")
        == str((cards_by_id[image_owner_id(image)].get("data") or {}).get("shotGroupId") or "")
    ]
    ready_image_owner_ids = {
        image_owner_id(node) for node in current_images
        if str(node.get("id") or "") in ready_image_ids
    }
    pending_image = next((
        image for card in ordered_cards
        if str(card.get("id") or "") not in ready_image_owner_ids
        for image in current_images if image_owner_id(image) == str(card.get("id") or "")
    ), None)
    def needs_video_prompt(node: dict[str, Any]) -> bool:
        node_id = str(node.get("id") or "")
        if node_id in generated_video_ids:
            return False
        if pending_video_prompt_ids is not None:
            return node_id in pending_video_prompt_ids
        return not card_text((node.get("data") or {}).get("videoTaskCard"), "finalVideoPrompt")

    pending_prompt = next((node for node in videos if needs_video_prompt(node)), None)
    pending_video = next((node for node in videos if str(node.get("id") or "") not in generated_video_ids), None)
    director_shots = ((by_type.get("director.board") or {}).get("data") or {}).get("directorPlanShots") or []
    if pending_prompt and pending_video and videos.index(pending_video) < videos.index(pending_prompt):
        shot_nos = (pending_prompt.get("data") or {}).get("shotNos") or []
        first_shot_no = shot_nos[0] if shot_nos else None
        if (isinstance(first_shot_no, int) and 0 < first_shot_no <= len(director_shots)
                and director_shots[first_shot_no - 1].get("entryBoundaryKind") == "direct_continuation"):
            # Its prompt needs the preceding group's real clip, so finish that clip first.
            pending_prompt = None
    has_storyboard = "storyboard.generated" in completed
    has_director = "director_plan.generated" in completed
    selected_nodes: dict[str, dict[str, Any]] = {}
    if not has_director:
        selected = {"director_plan_generation"} if script_source_text(script_data) else set()
        if not has_storyboard and not card_text(script_data, "cinematicStoryText") and card_text(script_data, "sourceFactText"):
            selected.add("workflow_cinematic_script_generation")
    else:
        selected = set()
        if pending_image and not has_storyboard:
            selected.add("storyboard_image_generation")
            selected_nodes["storyboard_image_generation"] = pending_image
        if include_visual_handoff:
            ready_card = next((
                card for card in ordered_cards
                if str(card.get("id") or "") in ready_image_owner_ids
                and str(card.get("id") or "") not in generated_handoff_card_ids
            ), None)
            if ready_card:
                selected.add("visual_handoff_image_generation")
                selected_nodes["visual_handoff_image_generation"] = ready_card
        if pending_prompt:
            selected.add("video_prompt_generation")
            selected_nodes["video_prompt_generation"] = pending_prompt
        elif pending_video:
            selected.add("storyboard_video_generation")
            selected_nodes["storyboard_video_generation"] = pending_video
    result = []
    for action in WORK_CHAIN_ACTIONS:
        node = selected_nodes.get(action["taskType"]) or by_type.get(action["nodeType"])
        if action["taskType"] not in selected or not node:
            continue
        result.append({
            **action, "nodeId": node["id"], "routeId": node.get("routeId") or "",
            "workChainId": node.get("workChainId") or "",
        })
    result.sort(key=lambda row: row["taskType"] != "visual_handoff_image_generation")
    return result
