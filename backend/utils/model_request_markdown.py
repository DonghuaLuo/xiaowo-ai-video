"""Readable model-request evidence shared by production logging and CLI exports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model_prompt_log import extract_effective_model_input, fingerprint
from .model_log_readable_values import readable_value


EMPTY_TEXT = "(空)"
REQUEST_DATA_KEYS = ("effectiveModelInput", "requestData", "requestInfo", "request", "providerRequest")
REQUEST_BODY_KEYS = ("requestBody", "body", "payload")
SCHEMA_FIELDS = (
    "structuredSchema",
    "schema",
    "jsonSchema",
    "responseFormat",
    "response_format",
    "outputConfig",
    "output_config",
)
SCHEMA_CONTAINER_FIELDS = (
    *SCHEMA_FIELDS,
    "text",
    "generationConfig",
    "generation_config",
)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _inline(value: Any) -> str:
    text = str(value if value not in (None, "") else EMPTY_TEXT)
    return text.replace("`", "\\`")


def _json_field_path(base: str, key: str) -> str:
    return f"$.{key}" if base == "$" else f"{base}.{key}"


def _request_data_with_path(log: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if isinstance(log.get("effectiveModelInput"), dict):
        return log["effectiveModelInput"], "$.effectiveModelInput"
    for key in REQUEST_DATA_KEYS[1:]:
        item = log.get(key)
        if isinstance(item, dict):
            return item, f"$.{key}"
    return log, "$"


def _request_body_path(log: dict[str, Any]) -> str:
    request_data, request_path = _request_data_with_path(log)
    for key in REQUEST_BODY_KEYS:
        if isinstance(request_data.get(key), dict):
            return _json_field_path(request_path, key)
    return request_path


def _text_from_simple_content_blocks(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    text_parts: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        block_type = str(item.get("type") or "").strip()
        block_text = item.get("text")
        if block_type != "text" or not isinstance(block_text, str):
            return None
        if block_text.strip():
            text_parts.append(block_text)
    return "\n\n".join(text_parts)


def _same_rendered_text(left: Any, right: Any) -> bool:
    return isinstance(left, str) and str(left or "").strip() == str(right or "").strip()


def _message_content_for_render(message: dict[str, Any]) -> tuple[str, set[str]]:
    used_keys = {"content"}
    content = message.get("content")
    if isinstance(content, str):
        used_keys.add("content")
        if _same_rendered_text(message.get("text"), content):
            used_keys.add("text")
        content_blocks_text = _text_from_simple_content_blocks(message.get("contentBlocks"))
        if _same_rendered_text(content_blocks_text, content):
            used_keys.add("contentBlocks")
        return readable_value(content, path="content"), used_keys
    if content is not None:
        used_keys.add("content")
        return readable_value(content, path="content"), used_keys

    content_blocks = message.get("contentBlocks")
    content_blocks_text = _text_from_simple_content_blocks(content_blocks)
    if content_blocks_text is not None:
        used_keys.add("contentBlocks")
        if _same_rendered_text(message.get("text"), content_blocks_text):
            used_keys.add("text")
        return readable_value(content_blocks_text, path="contentBlocks"), used_keys
    if isinstance(content_blocks, (list, dict)):
        used_keys.add("contentBlocks")
        return readable_value(content_blocks, path="contentBlocks"), used_keys

    text = message.get("text")
    if isinstance(text, str):
        used_keys.add("text")
        return readable_value(text, path="text"), used_keys
    return EMPTY_TEXT, used_keys


def _section(lines: list[str], title: str, body: str) -> None:
    lines.extend(["", f"## {title}", "", body])


def _subsection(lines: list[str], title: str, body: str) -> None:
    lines.extend(["", f"### {title}", "", body])


def _render_messages(lines: list[str], path: str, messages: list[Any]) -> None:
    lines.extend(["", "## 发送给模型的 Messages", ""])
    if not messages:
        lines.append(f"`{path}` 为空。")
        return
    for index, message in enumerate(messages):
        message_path = f"{path}[{index}]"
        if not isinstance(message, dict):
            _subsection(lines, message_path, readable_value(message, path=message_path))
            continue
        title_parts = [message_path]
        if message.get("role"):
            title_parts.append(f"role={message.get('role')}")
        if message.get("name"):
            title_parts.append(f"name={message.get('name')}")
        body_lines = []
        rendered_content, content_keys = _message_content_for_render(message)
        metadata = {
            key: value
            for key, value in message.items()
            if key not in {"role", "name", *content_keys}
        }
        if metadata:
            body_lines.extend(["消息元数据：", "", readable_value(metadata, path=message_path), ""])
        aliases = [key for key in content_keys if key != "content" and key in message]
        if "content" in message and message.get("content") is not None and aliases:
            body_lines.extend(["相同正文的重复字段：" + "、".join(f"`{key}`" for key in sorted(aliases)) + "。正文只展开一次，原始字段保留在 JSON。", ""])
        body_lines.append(rendered_content)
        _subsection(lines, " / ".join(str(item) for item in title_parts), "\n".join(body_lines))


def render_prompt_request_log(log: dict[str, Any]) -> str:
    source_log = log if isinstance(log, dict) else {}
    effective_input = extract_effective_model_input(source_log)
    if not effective_input:
        return "\n".join(
            [
                "# Prompt Request Log",
                "",
                "这是 `prompt_request_log.json` 的人类可读版。",
                "",
                "本次没有记录到真实请求数据或提示词快照；可能是 dry-run 之前配置不可用，或真实执行在发起模型请求前失败。",
                "",
            ]
        )
    request_body = _dict(effective_input.get("requestBody"))
    request_body_path = _request_body_path(source_log)
    capture_level = effective_input.get("captureLevel")
    is_sdk = effective_input.get("transport") == "claude_agent_sdk"
    boundary = {
        "application_submission": "应用提交参数：这是交给 SDK/客户端的数据，不代表 SDK 组装后的最终 API 请求。",
        "api_outbound": "API 出站记录：这是应用或 SDK 发送到供应商 API 边界的数据；不代表远端服务内部组装。",
        "local_diagnostic": "本地诊断：以下内容不能视为发送给模型的数据。",
    }.get(str(capture_level), (
        "应用提交参数：旧记录未声明采集层级；SDK 后续自动组装的内容未包含在这份参数快照中。"
        if is_sdk else "采集层级未声明：以下为已记录的 HTTP 请求/提示词快照，不能据此证明网络调用已经执行。"
    ))
    if effective_input.get("dryRun") or effective_input.get("executed") is False:
        boundary += " 本次是请求预览，未发送模型请求。"
    lines = [
        "# Prompt Request Log",
        "",
        "这是提示词日志 JSON 的人类可读版。所有已记录字段按来源展开；媒体以引用或脱敏信息表示。原始 JSON 是逐字核对依据。",
        "",
        "## 记录信息",
        "",
        boundary,
        "",
        f"- 请求指纹: `{_inline(fingerprint(effective_input))}`",
    ]
    envelope = {key: value for key, value in effective_input.items() if key != "requestBody"}
    if envelope:
        _section(lines, "请求来源与传输信息", readable_value(envelope, path="$"))
    for key, value in request_body.items():
        path = _json_field_path(request_body_path, key)
        if key == "messages" and isinstance(value, list):
            _render_messages(lines, path, value)
            continue
        if key == "options" and isinstance(value, dict):
            system = value.get("system_prompt")
            if system is not None:
                notice = ""
                if isinstance(system, dict) and system.get("type") == "preset":
                    notice = "内置 preset 正文由 SDK 提供，本次记录未捕获；以下为 preset 声明和应用追加内容。\n\n"
                _section(lines, f"应用提交的 SDK System Prompt（{path}.system_prompt）",
                         notice + readable_value(system, path=f"{path}.system_prompt"))
            remaining = {name: item for name, item in value.items() if name != "system_prompt"}
            if remaining:
                _section(lines, f"SDK 调用参数（{path}）", readable_value(remaining, path=path))
            continue
        title = (
            "System Prompt" if key in {"system", "systemPrompt", "system_prompt", "instructions", "systemInstruction"}
            else "User Prompt" if key in {"prompt", "userPrompt", "user_prompt"}
            else "Input" if key == "input"
            else "工具定义" if key == "tools"
            else "工具选择" if key == "tool_choice"
            else "结构化输出约束与参数" if key in SCHEMA_CONTAINER_FIELDS
            else "请求字段"
        )
        _section(lines, f"{title}（{path}）", readable_value(value, path=path))
    return "\n".join(lines) + "\n"


def render_prompt_request_log_file(
    path: str | Path,
    out: str | Path | None = None,
) -> Path | str:
    target = Path(path)
    log = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    markdown = render_prompt_request_log(log if isinstance(log, dict) else {})
    markdown += f"\n原始证据：[请求 JSON](<{Path(path).absolute().as_posix()}>)。\n"
    if out:
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8", newline="\n")
        return target
    return markdown
