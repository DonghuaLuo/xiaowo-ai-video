"""Video task purposes shared by canvas contracts and provider adapters."""

CHARACTER_REPLACE_TASK = "video.character_replace"
CHARACTER_REPLACE_STRATEGY = "character_replace_video"
CHARACTER_REPLACE_IMAGE_SLOTS = frozenset({"character_reference", "creature_reference", "custom_image"})
CHARACTER_REPLACE_INPUT_SLOTS = CHARACTER_REPLACE_IMAGE_SLOTS | {"reference_video"}


def standalone_video_input_mode(node_type: str) -> str:
    return {
        "video.keyframe": "native_keyframe",
        CHARACTER_REPLACE_TASK: "character_replace",
    }.get(node_type, "image_reference")


def standalone_video_strategy(node_type: str) -> str:
    return standalone_video_input_mode(node_type) + "_video"


def standalone_video_required_slots(node_type: str) -> list[str]:
    return {
        "video.keyframe": ["frame_reference"],
        CHARACTER_REPLACE_TASK: ["character_reference", "reference_video"],
    }.get(node_type, ["image_reference"])


def model_supports_video_task(model: dict, node_type: str) -> bool:
    from utils.video_model_capabilities import video_model_capability

    adapter = (video_model_capability(model) or model).get("adapter_capabilities") or {}
    task_types = adapter.get("task_types") or []
    if task_types:
        return node_type in task_types
    return node_type != CHARACTER_REPLACE_TASK
