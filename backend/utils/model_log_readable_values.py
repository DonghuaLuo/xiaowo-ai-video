"""Lossless business-field presentation shared by request and response reports."""
from __future__ import annotations

import json
import re
from typing import Any

from .model_prompt_log import sanitize_for_prompt_log


def text_block(text: str) -> str:
    fence = "`" * max(3, max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    return f"{fence}text\n{text}\n{fence}"


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value == "":
        return "（空字符串）"
    return str(value).replace("`", "\\`")


def readable_value(value: Any, *, path: str = "$", level: int = 3) -> str:
    """Keep every field, with newlines unescaped and media represented by metadata.

    This is presentation only: never rewrite the captured evidence. Opaque protocol
    signatures are explicitly represented by their length, not copied into prose.
    """
    value = sanitize_for_prompt_log(value)
    if isinstance(value, str):
        if path.rsplit(".", 1)[-1] in {"signature", "encrypted_content"}:
            return f"不透明协议数据，{len(value)} 字符；完整值见原始 JSON。"
        return readable_text(value, path=path, level=level)
    if not isinstance(value, (dict, list)):
        return _scalar(value)
    if not value:
        return "（空对象）" if isinstance(value, dict) else "（空列表）"
    lines: list[str] = []
    entries = value.items() if isinstance(value, dict) else enumerate(value)
    for key, item in entries:
        child_path = f"{path}.{key}" if isinstance(value, dict) else f"{path}[{key}]"
        if not isinstance(item, (dict, list)) and not (isinstance(item, str) and (
            "\n" in item or len(item) > 100 or item.lstrip().startswith(("{", "[", "```"))
        )):
            if isinstance(item, str) and str(key) in {"signature", "encrypted_content"}:
                rendered = f"不透明协议数据，{len(item)} 字符；见原始 JSON"
            else:
                rendered = _scalar(item)
            lines.extend([f"- `{child_path}`: {rendered}", ""])
        else:
            title = f"{'#' * min(level, 6)} {child_path}" if level <= 6 else f"**{child_path}**"
            lines.extend([title, "", readable_value(item, path=child_path, level=level + 1), ""])
    return "\n".join(lines).rstrip()


def readable_text(text: str, *, path: str = "$", level: int = 3) -> str:
    """Decode complete JSON / fenced JSON without duplicating the source string.

    Plain text, including whitespace and malformed or partial JSON, is retained.
    Mixed prose and JSON fences retain all the prose around each decoded block.
    """
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, (dict, list)):
        return "按字段展开（原始文本见 JSON 证据）：\n\n" + readable_value(parsed, path=path, level=level)
    pattern = re.compile(r"(?m)^(`{3,})(?:json)?[ \t]*\r?\n(.*?)^\1[ \t]*(?:\r?\n|$)", re.DOTALL)
    lines: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        try:
            parsed = json.loads(match.group(2))
        except ValueError:
            continue
        if not isinstance(parsed, (dict, list)):
            continue
        if match.start() > cursor:
            lines.append(_embedded_json(text[cursor:match.start()], path=path, level=level))
        lines.append(readable_value(parsed, path=f"{path}.json", level=level))
        cursor = match.end()
    if not lines:
        return _embedded_json(text, path=path, level=level)
    if cursor < len(text):
        lines.append(_embedded_json(text[cursor:], path=path, level=level))
    return "\n\n".join(lines)


def _embedded_json(text: str, *, path: str, level: int) -> str:
    """Unpack labeled JSON context sections while retaining their surrounding text."""
    decoder = json.JSONDecoder()
    cursor = 0
    lines: list[str] = []
    for match in re.finditer(r"[\{\[]", text):
        if match.start() < cursor:
            continue
        prefix = text[text.rfind("\n", 0, match.start()) + 1:match.start()]
        if not re.fullmatch(r"\s*(?:【[^】]+】\s*)?", prefix):
            continue
        try:
            parsed, end = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        if not isinstance(parsed, (dict, list)):
            continue
        if match.start() > cursor:
            lines.append(text_block(text[cursor:match.start()]))
        lines.append(readable_value(parsed, path=f"{path}.json", level=level))
        cursor = match.start() + end
    if not lines:
        return text_block(text)
    if cursor < len(text):
        lines.append(text_block(text[cursor:]))
    return "\n\n".join(lines)
