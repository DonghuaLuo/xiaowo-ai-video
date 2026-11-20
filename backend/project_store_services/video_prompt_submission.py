"""The model submits creative video and sound data; the turn owns its destination."""
from typing import Any


VIDEO_PROMPT_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "video": {
            "type": "object",
            "properties": {
                "shots": {"type": "array", "minItems": 1, "items": {
                    "type": "object",
                    "properties": {
                        "shotNo": {"type": "integer", "minimum": 1},
                        "durationSec": {"type": "number", "exclusiveMinimum": 0},
                        "prompt": {"type": "string"},
                    },
                    "required": ["shotNo", "durationSec", "prompt"],
                    "additionalProperties": False,
                }},
            },
            "required": ["shots"],
            "additionalProperties": False,
        },
        "sound": {
            "type": "object",
            "properties": {
                "soundPrompt": {
                    "type": "string",
                    "description": "声音总体要求；无额外要求用空字符串，固定声线由 voiceDesign 及本地声音数据提供",
                },
                "usedSpeakerIds": {"type": "array", "items": {"type": "string"}},
                "voiceDesign": {
                    "type": "object",
                    "properties": {
                        "speakers": {"type": "array", "items": {
                            "type": "object",
                            "properties": {
                                "speakerId": {"type": "string"},
                                "displayName": {"type": "string"},
                                "voiceStyle": {"type": "string"},
                            },
                            "required": ["speakerId", "displayName", "voiceStyle"],
                            "additionalProperties": False,
                        }},
                    },
                    "required": ["speakers"],
                    "additionalProperties": False,
                },
            },
            "required": ["soundPrompt", "usedSpeakerIds", "voiceDesign"],
            "additionalProperties": False,
        },
    },
    "required": ["video", "sound"],
    "additionalProperties": False,
}


def video_prompt_result_fields(args: dict[str, Any]) -> dict[str, Any]:
    """Adapt the model contract to existing independent storage/service fields."""
    if set(args) - {"video", "sound", "episodeId", "nodeId"}:
        raise ValueError("视频提示词结果只包含 video 和 sound 两个内容对象")
    video, sound = args.get("video"), args.get("sound")
    if not isinstance(video, dict) or set(video) != {"shots"}:
        raise ValueError("video 必须包含 shots 镜头数组")
    if not isinstance(sound, dict) or set(sound) != {"soundPrompt", "usedSpeakerIds", "voiceDesign"}:
        raise ValueError("sound 必须包含 soundPrompt、usedSpeakerIds 和 voiceDesign")
    return {"shots": video["shots"], **sound}
