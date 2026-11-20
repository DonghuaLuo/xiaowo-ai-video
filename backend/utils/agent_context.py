from __future__ import annotations

import re
from typing import Any

AGENT_CONTEXT_RECENT_WINDOW = 12
AGENT_CONTEXT_MESSAGE_TEXT_LIMIT = 800
AGENT_CONTEXT_SUMMARY_MESSAGE_LIMIT = 24
AGENT_CONTEXT_SUMMARY_CHARS = 1600


def _compact_text(value: str, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def _prompt_content_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = message.get("content") if isinstance(message.get("content"), list) else []
    if not blocks:
        text = str(message.get("text") or "").strip()
        return [{"type": "text", "text": _compact_text(text, AGENT_CONTEXT_MESSAGE_TEXT_LIMIT)}] if text else []

    rows: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("contextExcluded") or block.get("context_excluded"):
            continue
        block_type = str(block.get("type") or "text")
        if block_type in {"source_text", "sourceText", "tool_result"}:
            continue
        if block_type == "text":
            text = _compact_text(str(block.get("text") or ""), AGENT_CONTEXT_MESSAGE_TEXT_LIMIT)
            if text:
                rows.append({"type": "text", "text": text})
        elif block_type == "image":
            rows.append({"type": "image", "summary": "用户上传的图片附件"})
        elif block_type in {
            "tool_use",
            "thinking",
            "skill_content",
            "task_progress",
            "interrupt_notice",
            "attachment_error",
        }:
            text = _compact_text(
                str(
                    block.get("text")
                    or block.get("content")
                    or block.get("result")
                    or block.get("title")
                    or block.get("name")
                    or ""
                ),
                360,
            )
            rows.append({"type": block_type, "summary": text})
    return rows


def _text_from_prompt_content_blocks(blocks: list[dict[str, Any]]) -> str:
    text = " ".join(
        str(block.get("text") or "").strip()
        for block in blocks
        if block.get("type") == "text" and str(block.get("text") or "").strip()
    )
    return _compact_text(text, AGENT_CONTEXT_MESSAGE_TEXT_LIMIT)


def _intent_content_hints(message: dict[str, Any], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for block in blocks:
        block_type = str(block.get("type") or "text")
        if block_type == "text":
            continue
        hint: dict[str, Any] = {"type": block_type}
        summary = str(block.get("summary") or "").strip()
        if summary:
            hint["summary"] = summary
        hints.append(hint)
    attachments = message.get("attachments") if isinstance(message.get("attachments"), list) else []
    hints.extend(_intent_attachment_hints(attachments))
    return hints


def _intent_attachment_kind(attachment: dict[str, Any]) -> str:
    mime_type = str(attachment.get("mimeType") or attachment.get("mime_type") or "").strip().lower()
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    raw_kind = str(attachment.get("kind") or attachment.get("type") or "").strip().lower()
    if raw_kind in {"image", "video", "audio", "file"}:
        return raw_kind
    return "file"


def _intent_valid_attachments(attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(attachments, list):
        return []
    return [attachment for attachment in attachments if isinstance(attachment, dict)]


def _intent_attachment_hints(attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    valid_attachments = _intent_valid_attachments(attachments)
    hints: list[dict[str, Any]] = []
    for index, attachment in enumerate(valid_attachments[:5]):
        mime_type = str(attachment.get("mimeType") or attachment.get("mime_type") or "").strip()
        name = _compact_text(
            str(
                attachment.get("name")
                or attachment.get("originalName")
                or attachment.get("fileName")
                or attachment.get("filename")
                or f"附件 {index + 1}"
            ),
            120,
        )
        hint: dict[str, Any] = {"type": _intent_attachment_kind(attachment)}
        if mime_type:
            hint["mimeType"] = mime_type
        if name:
            hint["name"] = name
        hints.append(hint)
    return hints


def _recent_history(messages: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in messages[-limit:]:
        rows.append(
            {
                "role": str(item.get("role") or "user"),
                "text": _compact_text(str(item.get("text") or ""), AGENT_CONTEXT_MESSAGE_TEXT_LIMIT),
                "contentBlocks": _prompt_content_blocks(item),
                "createdAt": str(item.get("createdAt") or ""),
            }
        )
    return rows


def _intent_recent_history(messages: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in messages[-limit:]:
        content_blocks = _prompt_content_blocks(item)
        text = _compact_text(str(item.get("text") or ""), AGENT_CONTEXT_MESSAGE_TEXT_LIMIT)
        if not text:
            text = _text_from_prompt_content_blocks(content_blocks)
        content_hints = _intent_content_hints(item, content_blocks)
        if not text and not content_hints:
            continue
        row: dict[str, Any] = {
            "role": str(item.get("role") or "user"),
            "text": text,
        }
        if content_hints:
            row["contentHints"] = content_hints
        rows.append(row)
    return rows


def _older_summary(messages: list[dict[str, Any]], recent_count: int) -> str:
    older = messages[: max(0, len(messages) - recent_count)]
    if not older:
        return ""
    snippets: list[str] = []
    for item in older[-AGENT_CONTEXT_SUMMARY_MESSAGE_LIMIT:]:
        role = "用户" if str(item.get("role") or "") == "user" else "助手"
        snippets.append(f"{role}: {_compact_text(str(item.get('text') or ''), 180)}")
    return _compact_text("\n".join(snippets), AGENT_CONTEXT_SUMMARY_CHARS)


def build_agent_intent_conversation_context(
    *,
    messages: list[dict[str, Any]],
    limit: int = 2,
) -> dict[str, Any]:
    return {
        "recentMessages": _intent_recent_history(messages, limit),
    }


def build_agent_intent_current_message_hints(
    *,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    valid_attachments = _intent_valid_attachments(attachments)
    content_hints = _intent_attachment_hints(valid_attachments)
    if not valid_attachments:
        return {}
    return {
        "attachmentCount": len(valid_attachments),
        "attachedImageCount": sum(
            1 for item in valid_attachments if _intent_attachment_kind(item) == "image"
        ),
        "contentHints": content_hints,
        "policy": "当前轮附件只提供类型、数量和文件名提示；不包含图片数据、文件内容或本地路径。",
    }


def build_agent_conversation_context(
    *,
    session_id: str | None,
    messages: list[dict[str, Any]],
    history_summary: str = "",
    limit: int = AGENT_CONTEXT_RECENT_WINDOW,
) -> dict[str, Any]:
    recent = _recent_history(messages, limit)
    durable_summary = _compact_text(str(history_summary or ""), AGENT_CONTEXT_SUMMARY_CHARS)
    generated_summary = _older_summary(messages, limit)
    older_summary_parts = [part for part in (durable_summary, generated_summary) if part]
    older_summary = _compact_text("\n".join(older_summary_parts), AGENT_CONTEXT_SUMMARY_CHARS)
    return {
        "sessionId": session_id,
        "storage": "sqlite",
        "historyPolicy": {
            "currentUserMessageIsSeparate": True,
            "recentWindowLimit": limit,
            "messageTextLimit": AGENT_CONTEXT_MESSAGE_TEXT_LIMIT,
            "olderSummaryMaxChars": AGENT_CONTEXT_SUMMARY_CHARS,
            "unboundedFullHistory": False,
            "durableSummaryIncluded": bool(durable_summary),
        },
        "storedMessageCount": len(messages),
        "includedRecentCount": len(recent),
        "olderSummary": older_summary,
        "recentMessages": recent,
    }
