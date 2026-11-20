"""Character replacement uses a short user instruction, without shot/voice prose."""

from utils.video_prompt_mentions import PROMPT_REFERENCE_PATTERN, prompt_reference_label, resolve_prompt_mentions


def character_replacement_prompt(payload: dict, manifest: list[dict]) -> tuple[str, dict]:
    card = payload.get("videoTaskCard") or {}
    text = card.get("finalVideoPrompt", "")
    if not isinstance(text, str):
        raise ValueError("角色替换说明必须是文本")
    text = text.strip()
    resolved = resolve_prompt_mentions(text, card.get("promptBindings") or {}, manifest)

    def render(match):
        row = resolved[prompt_reference_label(match)]
        if row.get("kind") == "text":
            raise ValueError("替换说明引用的素材未参与本次生成，请检查关联与启用状态")
        return "源视频" if row["kind"] == "video" else f"图{row['index']}"

    prompt = PROMPT_REFERENCE_PATTERN.sub(render, text)
    if len(prompt) > 2048:
        raise ValueError("角色替换说明不能超过 2048 字符")
    return prompt, {"finalPromptChars": len(prompt), "source": "character_replace_instruction",
                    "voiceStyleSupplementIncluded": False}
