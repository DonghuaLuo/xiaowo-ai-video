#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Claude Agent SDK runtime bridge for ai-video.

This module keeps the SDK-specific imports and message parsing outside
``project_store.py``. The ai-video store passes project-bound callbacks in, so
MCP tools stay tied to the current desktop project instead of accepting arbitrary
project paths from the model.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import dataclasses
import inspect
import json
import os
import re
import subprocess
import sys
import time
import traceback
import uuid
from collections import deque
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from utils.model_reasoning import apply_model_reasoning, model_sdk_reasoning_options, reasoning_policy, task_reasoning_mode

SDK_CONTEXT_VERSION = "business-v7"


# The SDK merges options.env over the parent environment. Empty/off overrides
# are required here; omitting a key would leave the parent's value effective.
_SDK_EXTERNAL_PROVIDER_MODES = (
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_GATEWAY", "CLAUDE_CODE_USE_MANTLE",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS", "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
)
_SDK_EXTERNAL_AUTH_FIELDS = (
    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
    "CLAUDE_CODE_SESSION_ACCESS_TOKEN", "CLAUDE_CODE_GATEWAY_TOKEN",
    "CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR",
)


def _sdk_business_environment(env: dict[str, str]) -> dict[str, str]:
    """Keep the configured Anthropic-compatible route authoritative per turn.

    Do not mutate os.environ: concurrent tasks can use different providers.
    Proxy, CA and ordinary process settings keep their normal inheritance.
    The runtime adds its own reasoning body after external overrides are reset.
    """
    protected = {
        **dict.fromkeys(_SDK_EXTERNAL_PROVIDER_MODES, "0"),
        **dict.fromkeys(_SDK_EXTERNAL_AUTH_FIELDS, ""),
        "CLAUDE_CODE_EXTRA_BODY": "{}",
        "ANTHROPIC_CUSTOM_HEADERS": "",
    }
    # Windows environment names are case-insensitive. Also neutralize differently
    # cased inherited names before the SDK constructs its subprocess environment.
    inherited = {key: protected[key.upper()] for key in os.environ if key.upper() in protected}
    configured = {key: value for key, value in env.items() if key.upper() not in protected}
    return {**inherited, **configured, **protected}


@lru_cache(maxsize=4)
def _checked_cli_version(path: str, modified_ns: int, size: int, expected: str) -> str:
    # File identity participates in the cache so replacing the runtime forces
    # revalidation, without spawning a version process for every model turn.
    result = subprocess.run(
        [path, "--version"], stdin=subprocess.DEVNULL, capture_output=True,
        text=True, encoding="utf-8", timeout=10, check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    actual = result.stdout.strip().split()[0] if result.stdout.strip() else ""
    if actual != expected:
        raise RuntimeError(f"SDK CLI version mismatch: expected {expected}, got {actual}")
    return actual


def _agent_cli_info() -> dict[str, str]:
    import claude_agent_sdk
    from claude_agent_sdk._cli_version import __cli_version__

    cli = Path(claude_agent_sdk.__file__).resolve().parent / "_bundled" / (
        "claude.exe" if sys.platform == "win32" else "claude"
    )
    if not cli.is_file():
        raise RuntimeError(f"SDK bundled CLI missing: {cli}; run scripts/install_agent_cli.py --install using {sys.executable}")
    stat = cli.stat()
    version = _checked_cli_version(str(cli), stat.st_mtime_ns, stat.st_size, __cli_version__)
    return {"path": str(cli), "version": version}

try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
        ToolResultBlock,
        ToolUseBlock,
        create_sdk_mcp_server,
        tool,
    )
except Exception as exc:  # noqa: BLE001 - optional runtime dependency.
    AssistantMessage = None  # type: ignore[assignment]
    ClaudeAgentOptions = None  # type: ignore[assignment]
    ClaudeSDKClient = None  # type: ignore[assignment]
    ResultMessage = None  # type: ignore[assignment]
    TextBlock = None  # type: ignore[assignment]
    ToolResultBlock = None  # type: ignore[assignment]
    ToolUseBlock = None  # type: ignore[assignment]
    create_sdk_mcp_server = None  # type: ignore[assignment]
    tool = None  # type: ignore[assignment]
    SDK_IMPORT_ERROR: BaseException | None = exc
    SDK_AVAILABLE = False
else:
    SDK_IMPORT_ERROR = None
    SDK_AVAILABLE = True


SnapshotProvider = Callable[..., dict[str, Any]]
ActionRequestHandler = Callable[[str, str], dict[str, Any]]
ToolRequestHandler = Callable[[str, dict[str, Any]], dict[str, Any]]
StreamEventHandler = Callable[[dict[str, Any]], None]
RequestPreparedHandler = Callable[[dict[str, Any]], None]
USER_INSTRUCTION_KEYS = (
    "userInstruction",
    "user_instruction",
    "revisionInstruction",
    "revision_instruction",
    "feedback",
)

DEFAULT_ALLOWED_TOOLS = [
    "mcp__ai_video__get_project_snapshot",
    "mcp__ai_video__get_conversation_history",
    "mcp__ai_video__list_workflow_node_versions",
    "mcp__ai_video__read_workflow_node_version",
    "mcp__ai_video__start_business_task",
    "mcp__ai_video__read_source_window",
    "mcp__ai_video__search_source_text",
    "mcp__ai_video__get_source_coverage",
    "mcp__ai_video__get_episode_boundary_context",
    "mcp__ai_video__update_project_settings",
    "mcp__ai_video__submit_episode_boundary_candidate",
    "mcp__ai_video__get_asset_range_context",
    "mcp__ai_video__submit_asset_range_candidate",
    "mcp__ai_video__get_asset_extraction_context",
    "mcp__ai_video__get_asset_extraction_asset_catalog",
    "mcp__ai_video__submit_asset_extraction_result",
    "mcp__ai_video__get_plot_split_context",
    "mcp__ai_video__submit_plot_split_candidate",
    "mcp__ai_video__get_cinematic_script_context",
    "mcp__ai_video__submit_cinematic_script_result",
    "mcp__ai_video__get_director_plan_context",
    "mcp__ai_video__validate_director_plan_draft",
    "mcp__ai_video__submit_director_plan_result",
    "mcp__ai_video__get_video_prompt_context",
    "mcp__ai_video__submit_video_prompt_result",
    "mcp__ai_video__get_video_prompt_optimization_context",
    "mcp__ai_video__submit_video_prompt_optimization_result",
    "mcp__ai_video__get_video_prompt_standalone_context",
    "mcp__ai_video__submit_video_prompt_standalone_result",
    "mcp__ai_video__publish_task_report",
    "mcp__ai_video__list_agent_actions",
    "mcp__ai_video__request_agent_action",
    "mcp__ai_video__request_overview_analysis",
    "mcp__ai_video__request_open_current_episode",
    "mcp__ai_video__save_story_world_map",
    "mcp__ai_video__upsert_asset",
    "mcp__ai_video__delete_asset",
    "mcp__ai_video__save_episode_work_chain_plan",
    "mcp__ai_video__patch_shot_prompt",
    "mcp__ai_video__upsert_workflow_node",
    "mcp__ai_video__delete_workflow_node",
    "mcp__ai_video__save_workflow_node_inline_edit",
    "mcp__ai_video__create_workflow_task_card",
    "mcp__ai_video__add_workflow_asset_nodes",
    "mcp__ai_video__update_workflow_route",
    "mcp__ai_video__link_workflow_input",
    "mcp__ai_video__unlink_workflow_input",
    "mcp__ai_video__list_workflow_inputs",
    "mcp__ai_video__resolve_generation_config",
    "mcp__ai_video__validate_project_quality",
    "mcp__ai_video__request_storyboard_image_generation",
    "mcp__ai_video__request_visual_handoff_image_generation",
    "mcp__ai_video__edit_storyboard_image",
    "mcp__ai_video__request_storyboard_video_generation",
    "mcp__ai_video__request_route_video_generation",
    "mcp__ai_video__request_asset_image_generation",
    "mcp__ai_video__list_generation_tasks",
    "mcp__ai_video__cancel_generation_task",
    "mcp__ai_video__request_project_export",
    "mcp__ai_video__list_director_rules",
    "mcp__ai_video__search_director_rules",
    "mcp__ai_video__read_director_rule",
    "mcp__ai_video__list_project_files",
    "mcp__ai_video__search_project_files",
    "mcp__ai_video__read_project_file",
    "mcp__ai_video__run_ffprobe",
    "mcp__ai_video__run_ffmpeg",
]

def _json_chars(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        return len(str(value or ""))


def _normalized_allowed_tools(allowed_tools: list[str] | tuple[str, ...] | None = None) -> list[str]:
    if allowed_tools is None:
        return list(DEFAULT_ALLOWED_TOOLS)
    known = set(DEFAULT_ALLOWED_TOOLS)
    rows: list[str] = []
    for item in allowed_tools:
        name = str(item or "").strip()
        if not name or name not in known or name in rows:
            continue
        rows.append(name)
    return rows


def _sdk_request_log_options(options_kwargs: dict[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for key, value in options_kwargs.items():
        if key in {"env", "mcp_servers", "stderr"}:
            continue
        try:
            rows[key] = copy.deepcopy(value)
        except Exception:
            rows[key] = str(value)
    env = options_kwargs.get("env")
    if isinstance(env, dict):
        rows["env"] = {
            str(key): {
                "redacted": True,
                "valueLength": len(str(value)),
            }
            for key, value in sorted(env.items(), key=lambda item: str(item[0]))
        }
    mcp_servers = options_kwargs.get("mcp_servers")
    if isinstance(mcp_servers, dict):
        rows["mcp_servers"] = {
            str(key): {
                "configured": True,
                "type": type(value).__name__,
            }
            for key, value in mcp_servers.items()
        }
    return rows


def is_claude_agent_sdk_available() -> bool:
    return SDK_AVAILABLE


def unavailable_reason() -> str:
    if SDK_AVAILABLE:
        return ""
    return str(SDK_IMPORT_ERROR or "claude_agent_sdk is not installed")


def _cancel_requested(cancel_event: Any | None) -> bool:
    is_set = getattr(cancel_event, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    return False


def _is_sdk_cleanup_coroutine_reuse_error(exc: BaseException) -> bool:
    return isinstance(exc, RuntimeError) and "cannot reuse already awaited coroutine" in str(exc)


async def _disconnect_sdk_client(client: Any) -> None:
    try:
        await client.disconnect()
        return
    except RuntimeError as exc:
        if not _is_sdk_cleanup_coroutine_reuse_error(exc):
            raise

    # claude_agent_sdk 0.2.x can fail while awaiting its private read-task
    # handle during disconnect. Clear that handle and retry so transport.close()
    # still runs instead of leaking the CLI subprocess.
    query = getattr(client, "_query", None)
    if query is not None:
        with contextlib.suppress(Exception):
            setattr(query, "_read_task", None)
    try:
        await client.disconnect()
    except RuntimeError as exc:
        if not _is_sdk_cleanup_coroutine_reuse_error(exc):
            raise
        with contextlib.suppress(Exception):
            if query is not None:
                query.close_receive_stream()
        transport = getattr(query, "transport", None) if query is not None else None
        if transport is not None:
            with contextlib.suppress(Exception):
                await transport.close()
        with contextlib.suppress(Exception):
            setattr(client, "_query", None)
        with contextlib.suppress(Exception):
            setattr(client, "_transport", None)
        materialized = getattr(client, "_materialized", None)
        if materialized is not None:
            with contextlib.suppress(Exception):
                await materialized.cleanup()
            with contextlib.suppress(Exception):
                setattr(client, "_materialized", None)


def _json_text(payload: dict[str, Any], *, label: str = "ai-video 工具输出") -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": f"{label}\n{json.dumps(payload, ensure_ascii=False, indent=2)}",
            }
        ]
    }


def _tool_error(
    name: str,
    exc: BaseException,
    *,
    details: dict[str, Any] | None = None,
    recovery_advice: dict[str, Any] | None = None,
    next_allowed_tools: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": False,
        "error": str(exc),
        "exceptionType": exc.__class__.__name__,
        "traceback": traceback.format_exc(),
    }
    if details:
        payload["details"] = details
    if recovery_advice:
        payload["recoveryAdvice"] = recovery_advice
    if next_allowed_tools:
        payload["nextAllowedTools"] = next_allowed_tools
    result = _json_text(payload, label=f"{name} 错误")
    result["is_error"] = True
    return result


def _backend_tool_recovery_advice(tool_name: str, error: str) -> dict[str, Any] | None:
    if tool_name == "upsert_asset":
        return {
            "reason": "单资产写入失败时，先核对目标资产 ID、名称及必填设计字段。",
            "nextAllowedTools": ["upsert_asset", "get_project_snapshot"],
            "hint": "按错误信息修正单资产输入后重试；整批原文资产拆分使用资产范围流程。",
        }
    if tool_name in {"submit_episode_boundary_candidate", "submit_asset_range_candidate"} and ("末尾" in error or "cursor" in error.lower()):
        return {
            "reason": "当前源文件游标可能已到末尾。",
            "nextAllowedTools": ["get_source_coverage", "validate_project_quality"],
            "hint": "读取 coverage 确认是否还有未覆盖原文。",
        }
    if tool_name == "update_project_settings":
        return {
            "reason": "项目设置更新失败通常是字段非法或 revision/baseHash 已变化。",
            "nextAllowedTools": ["get_project_snapshot", "update_project_settings"],
            "hint": "分集断点字数由项目设置控制；本次资产范围的目标字数可传给 get_asset_range_context.targetUnits。只有用户明确要求修改默认配置时才重试设置更新。",
        }
    return None


async def _call_provider(provider: SnapshotProvider, **projection: Any) -> dict[str, Any]:
    # Small worker snapshots remain parameterless; the main project provider
    # supports explicit field selection. Never retry an internal TypeError.
    if projection:
        try:
            inspect.signature(provider).bind(**projection)
        except (TypeError, ValueError):
            projection = {}
    return await asyncio.to_thread(provider, **projection)


def _arg_text(args: dict[str, Any] | None, *keys: str) -> str:
    source = args if isinstance(args, dict) else {}
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _user_instruction(args: dict[str, Any] | None) -> str:
    return _arg_text(args, *USER_INSTRUCTION_KEYS)


def _rationale_with_user_instruction(args: dict[str, Any] | None, default: str = "") -> str:
    rationale = _arg_text(args, "rationale") or default
    instruction = _user_instruction(args)
    if not instruction:
        return rationale
    if rationale and instruction in rationale:
        return rationale
    if not rationale:
        return f"用户补充要求：{instruction}"
    return f"{rationale}\n用户补充要求：{instruction}"


def build_ai_video_mcp_server(
    *,
    snapshot_provider: SnapshotProvider,
    action_request_handler: ActionRequestHandler,
    tool_request_handler: ToolRequestHandler | None = None,
    allowed_tool_names: list[str] | tuple[str, ...] | None = None,
) -> Any:
    if not SDK_AVAILABLE or create_sdk_mcp_server is None or tool is None:
        raise RuntimeError(unavailable_reason())

    from project_store_services.director_plan_contract import (
        _DIRECTOR_PLAN_SOUND_KINDS,
        _DIRECTOR_PLAN_VOICE_TYPES,
        _PRESENTATION_MODES,
    )

    from project_store_services.video_prompt_submission import VIDEO_PROMPT_RESULT_SCHEMA

    allowed_tool_name_set: set[str] | None = None
    if allowed_tool_names is not None:
        allowed_tool_name_set = {
            str(name or "").strip()
            for name in allowed_tool_names
            if str(name or "").strip()
        }

    def _tool_visible(short_name: str) -> bool:
        if allowed_tool_name_set is None:
            return True
        return short_name in allowed_tool_name_set or f"mcp__ai_video__{short_name}" in allowed_tool_name_set

    @tool(
        "get_project_snapshot",
        "按需读取当前项目的最新业务事实。已提供的事实足够时无需重复读取；定位资产或写后核验时指定对象与字段。返回事实，不重复任务指令和对话。",
        {"type": "object", "properties": {
            "domains": {"type": "array", "items": {"type": "string", "enum": ["project", "overview", "assets", "settings", "workflow", "source", "pending"]}, "description": "只读取需要的业务领域。"},
            "assetIds": {"type": "array", "items": {"type": "string"}, "description": "只读取这些项目资产；与 assets 领域配合。"},
            "fields": {"type": "array", "items": {"type": "string"}, "description": "资产字段使用存储字段名：desc（身份及描述）、voiceStyle、canSpeak、sourceRefs、sourceEvidence、designRationale、tag、prompts.assetImagePrompt。id/assetType/name 始终保留；不指定 fields 时返回所选资产的全部可用业务字段。"},
        }, "additionalProperties": False},
    )
    async def get_project_snapshot(_args: dict[str, Any]) -> dict[str, Any]:
        try:
            projection = {dest: _args[src] for src, dest in (
                ("domains", "domains"), ("assetIds", "asset_ids"), ("fields", "fields")
            ) if src in _args}
            snapshot = await _call_provider(snapshot_provider, **projection)
            return _json_text({"success": True, "snapshot": snapshot})
        except Exception as exc:  # noqa: BLE001
            return _tool_error("get_project_snapshot", exc)

    @tool(
        "get_conversation_history",
        "按需查询当前应用会话的较早对话、用户反馈和已确认约束。会话 ID 由后端绑定，不能跨会话读取。已有 SDK 上下文足够时无需调用。",
        {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "本页消息数，最多 20。"},
            "beforeMessageId": {"type": "string", "description": "可选，读取此消息之前的记录。"},
        }, "additionalProperties": False},
    )
    async def get_conversation_history(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="get_conversation_history", label="ai-video 当前会话历史",
        )

    @tool(
        "list_workflow_node_versions",
        "按需列出当前分集指定片段剧本或分镜脚本节点的修改版本。只返回编号、摘要和标识；用户没有提及旧版时不必调用。编号按现存版本从旧到新排列。",
        {"type": "object", "properties": {
            "episodeId": {"type": "string", "description": "当前分集 ID。"},
            "nodeId": {"type": "string", "description": "明确的片段剧本或分镜脚本节点 ID。"},
            "offset": {"type": "integer", "description": "从最新版本起跳过的条数，默认 0。"},
            "limit": {"type": "integer", "description": "本页版本数，最多 50，默认 20。"},
        }, "required": ["episodeId", "nodeId"], "additionalProperties": False},
    )
    async def list_workflow_node_versions(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="list_workflow_node_versions", label="ai-video 节点修改版本目录",
        )

    @tool(
        "read_workflow_node_version",
        "按需读取指定修改版本的剧本正文或结构化分镜及其返工要求。只用于比较和修订，不会恢复版本或写入节点。versionId 与 versionNumber 二选一，优先使用目录返回的稳定 versionId。",
        {"type": "object", "properties": {
            "episodeId": {"type": "string", "description": "当前分集 ID。"},
            "nodeId": {"type": "string", "description": "明确的片段剧本或分镜脚本节点 ID。"},
            "versionId": {"type": "string", "description": "目录返回的版本 ID；与 versionNumber 二选一。"},
            "versionNumber": {"type": "integer", "description": "用户所说第几版，按现存版本从旧到新编号；与 versionId 二选一。"},
        }, "required": ["episodeId", "nodeId"], "additionalProperties": False},
    )
    async def read_workflow_node_version(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="read_workflow_node_version", label="ai-video 指定节点修改版本",
        )

    @tool(
        "start_business_task",
        "按当前任务目录启动适用的一次性业务操作，包括概述、图片或视频生成及需要用户确认的清理操作。"
        "目标明确后传入对应 taskType；分集断点使用 episode-boundary-agent Skill。"
        "taskType 必须来自本轮提供的任务目录，后端会核验当前会话范围和目标。",
        {"type": "object", "properties": {
            "taskType": {"type": "string", "description": "任务目录中的稳定 taskType。"},
            "userRequirement": {"type": "string", "description": "用户本轮要求和已确认的相关约束；不添加新要求。"},
        }, "required": ["taskType"], "additionalProperties": False},
    )
    async def start_business_task(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="start_business_task", label="ai-video 确定性业务操作",
        )

    @tool(
        "read_source_window",
        (
            "按 sourceId、chapterId、offset、length 读取当前项目内小说正文窗口。"
            "length 按正文内容字数计算，不包含换行、空行、空格或制表符。"
            "offset、absoluteStart、absoluteEnd 按原始正文偏移计算；分页续读必须使用返回的 absoluteEnd。"
            "只读取项目源文件，不访问项目目录外路径；长篇小说应分窗口读取。"
        ),
        {
            "type": "object",
            "properties": {
                "sourceId": {"type": "string", "description": "可选。源文件 ID；为空时读取当前项目第一个源文件。"},
                "chapterId": {"type": "string", "description": "可选。章节 ID；填写后 offset 相对该章节起点。"},
                "offset": {"type": "integer", "description": "窗口起始原文偏移，默认 0；分页续读请传上一轮返回的 absoluteEnd。"},
                "length": {"type": "integer", "description": "读取内容字数，默认 4000，最大 20000；不包含换行、空行、空格或制表符。"},
            },
        },
    )
    async def read_source_window(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="read_source_window",
            label="ai-video 正文窗口读取",
        )

    @tool(
        "search_source_text",
        "在当前项目小说正文中检索明确名称或短语，返回分布于原文各位置的少量命中及偏移；需要完整表现时再按偏移调用 read_source_window。仅用于原文事实定位，不搜索扩展资料。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要定位的资产名称或原文短语，按字面匹配。"},
                "sourceId": {"type": "string", "description": "可选。指定小说源文件 ID。"},
                "maxMatches": {"type": "integer", "description": "可选。返回 1-12 个分布式命中，默认 8。"},
            },
            "required": ["query"],
        },
    )
    async def search_source_text(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="search_source_text",
            label="ai-video 原文定位",
        )

    @tool(
        "get_source_coverage",
        "读取当前项目的分集与资产覆盖进度，以及已提交的分集原文。",
        {
            "type": "object",
            "properties": {
                "sourceId": {"type": "string", "description": "可选。源文件 ID；为空时使用当前 coverage 源。"},
            },
        },
    )
    async def get_source_coverage(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="get_source_coverage",
            label="ai-video 原文覆盖账本读取",
        )

    @tool(
        "get_episode_boundary_context",
        "分项读取分集断点资料。首次规划不传 episodeId；修订已保存分集时每次传其 episodeId。source_text 返回原文，planning_state 返回集号、游标、允许边界及 currentEpisode；两项 contextVersion 须一致。continuation_text 按需补读窗口后文。资产覆盖由后端检查。",
        {"type": "object", "properties": {
            "part": {"type": "string", "enum": ["source_text", "planning_state", "continuation_text"]},
            "episodeId": {"type": "string", "description": "仅修订已保存分集时传入明确目标；下一集规划省略。"},
        }, "required": ["part"], "additionalProperties": False},
    )
    async def get_episode_boundary_context(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="get_episode_boundary_context", label="ai-video 下一集断点专用资料",
        )

    @tool(
        "update_project_settings",
        "更新项目配置，例如 episodeTargetUnits 或 assetExtractionTargetUnits。仅当用户明确要求修改当前项目配置时调用；分集断点使用项目设置的字数，本次资产范围字数可传给 get_asset_range_context.targetUnits。",
        {
            "type": "object",
            "properties": {
                "settings": {"type": "object", "description": "要更新的项目配置字段。"},
                "episodeTargetUnits": {"type": "integer", "description": "每集目标字数。"},
                "assetExtractionTargetUnits": {"type": "integer", "description": "资产范围目标字数。"},
                "expectedRevision": {"type": "integer", "description": "可选。settings 资源 revision 防覆盖。"},
                "baseHash": {"type": "string", "description": "可选。settings 资源 hash 防覆盖。"},
                "reason": {"type": "string", "description": "可选。本次修改原因。"},
                "userInstruction": {"type": "string", "description": "可选。用户本轮原始要求摘要。"},
            },
        },
    )
    async def update_project_settings(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="update_project_settings",
            label="ai-video 项目设置更新",
        )

    @tool(
        "submit_episode_boundary_candidate",
        "提交分集断点或修订明确的已保存分集。contextVersion 来自本轮同目标的正文与规划状态；修改时传 episodeId，不传则规划下一集。只改标题或理由时沿用 currentEpisode 的尾句及其他字段。边界变化受后续分集和下游依赖保护，成功后自动写入核验并报告。",
        {
            "type": "object",
            "properties": {
                "boundaryEndText": {"type": "string", "description": "原文中断点末尾连续 20-60 个有效字，原样复制，不改写。"},
                "episodeTitle": {"type": "string", "description": "概括本集关键戏剧钩子的具体短标题。"},
                "reason": {"type": "string", "description": "说明本集形成的局部结果、集尾压力及断点选择理由。"},
                "riskNotes": {"type": "array", "items": {"type": "string"}},
                "episodeId": {"type": "string", "description": "修订已保存分集的明确 ID；与本轮读取相同，下一集规划省略。"},
                "contextVersion": {"type": "string", "description": "正文和规划状态共同返回的当前版本。"},
            },
            "required": ["boundaryEndText", "episodeTitle", "reason", "contextVersion"],
        },
    )
    async def submit_episode_boundary_candidate(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="submit_episode_boundary_candidate",
            label="ai-video 智能体分集断点校验",
        )

    @tool(
        "get_asset_range_context",
        "按用途读取资产范围规划资料：source_text 为原文，planning_state 为断点位置及当前范围，phase_visuals 为已有整体阶段视觉。三项须为同一 contextVersion。修改已保存范围时，每次传 assetRangeId；仅允许最新且尚未开始拆分的范围。",
        {"type": "object", "properties": {
            "part": {"type": "string", "enum": ["source_text", "planning_state", "phase_visuals"]},
            "assetRangeId": {"type": "string", "description": "仅修订已保存范围时指定；省略表示规划下一段。"},
            "sourceId": {"type": "string"},
            "targetUnits": {"type": "integer", "minimum": 100, "maximum": 50000},
        }, "required": ["part"], "additionalProperties": False},
    )
    async def get_asset_range_context(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="get_asset_range_context", label="ai-video 资产范围规划资料",
        )

    @tool(
        "submit_asset_range_candidate",
        "提交资产范围规划或修订。修订时传 assetRangeId，更新指定范围而非追加下一段。按 asset-range-agent 保留连续的出场、介绍或状态变化，尾句须在允许区间；阶段视觉描述跨场景持续的可见状态。三项资料的 contextVersion 必须一致，校验后自动写入。",
        {"type": "object", "properties": {
            "sourceId": {"type": "string"},
            "absoluteStart": {"type": "integer", "minimum": 0},
            "targetUnits": {"type": "integer", "minimum": 100, "maximum": 50000},
            "coverageHash": {"type": "string"},
            "contextVersion": {"type": "string"},
            "assetRangeId": {"type": "string", "description": "修订专用资料中 currentRange 对应的范围；新规划省略。"},
            "boundaryEndText": {"type": "string"},
            "reason": {"type": "string", "description": "按 asset-range-agent 的同一选点与验收标准，简述断点附近资产已交代的具体事实，以及前后衔接为何没有拆开连续的资产表达。"},
            "summary": {"type": "string"},
            "riskNotes": {"type": "array", "items": {"type": "string"}},
            "assetTypes": {"type": "array", "items": {"type": "string", "enum": ["characters", "creatures", "scenes", "props"]}},
            "stageVisualChanged": {"type": "boolean"},
            "phaseVisualContexts": {"type": "array", "maxItems": 4, "items": {
                "type": "object", "properties": {
                    "name": {"type": "string", "minLength": 6, "maxLength": 16,
                             "description": "概括跨多个场景的整体视觉质感和状态，不写地点类别、行动、剧情或道具。"},
                    "visualPrompt": {"type": "string", "minLength": 12, "maxLength": 41,
                                     "description": "以“整体视觉以……为主。”描述大多数场景共享的环境维护程度、资源层级、色彩材质或公共空间秩序，不列举场景类别、活动或事件。"},
                    "sourceSpan": {"type": "string", "description": "仅定位原文中持续存在的视觉状态，不作为绘图提示词。"},
                    "visualChangeReason": {"type": "string", "minLength": 20, "maxLength": 80,
                                           "description": "说明相对已有阶段的整体视觉状态变化，不复述剧情。"},
                    "transitionType": {"type": "string", "enum": ["initial_or_single_stage", "world_state_shift", "resource_class_shift", "power_system_shift", "combat_or_training_shift"]},
                }, "required": ["name", "visualPrompt", "sourceSpan", "visualChangeReason", "transitionType"], "additionalProperties": False,
            }},
        }, "required": ["absoluteStart", "coverageHash", "contextVersion", "boundaryEndText", "reason",
                         "stageVisualChanged", "phaseVisualContexts"], "additionalProperties": False},
    )
    async def submit_asset_range_candidate(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="submit_asset_range_candidate", label="ai-video 资产范围候选校验",
        )

    @tool(
        "get_asset_extraction_context",
        "按资产拆分阶段读取资料：source_text 返回已确认范围原文；task_state 返回范围、版本及扩展资料目录首页；identity_index 返回已有身份；design_context 返回制作规格与阶段视觉；material_catalog 分页发现资料；material_evidence 按候选名称/别名跨资料检索，或按文件行号补读；adjacent_evidence 补相邻证据。各项 inputDigest 必须一致，变化时重读并核对受影响事实。多个范围时指定 assetRangeId。",
        {"type": "object", "properties": {
            "part": {"type": "string", "enum": ["source_text", "task_state", "identity_index", "design_context", "material_catalog", "material_evidence", "adjacent_evidence"]},
            "assetRangeId": {"type": "string", "description": "可选；不提供时须只有一个待拆分范围。"},
            "offset": {"type": "integer", "minimum": 0, "description": "material_catalog 或 material_evidence 检索有 nextOffset 时读取下一页。"},
            "queries": {"type": "array", "items": {"type": "string"}, "description": "material_evidence 的候选名称及相关别名；字面检索不等于语义排除。"},
            "relativePath": {"type": "string", "description": "目录中的资料路径；指定后可限定检索，或不传 queries 按行读取。"},
            "lineStart": {"type": "integer", "minimum": 1, "description": "按行补读的起始行，默认1。"},
            "lineCount": {"type": "integer", "minimum": 1, "maximum": 120, "description": "按行补读行数，默认80。"},
        }, "required": ["part"], "additionalProperties": False},
    )
    async def get_asset_extraction_context(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="get_asset_extraction_context", label="ai-video 资产拆分资料",
        )

    @tool(
        "get_asset_extraction_asset_catalog",
        "按类型和页码读取项目现有资产的身份与设计摘要，以核对别名、复用关系和视觉连续性。",
        {"type": "object", "properties": {
            "assetType": {"type": "string", "enum": ["characters", "creatures", "scenes", "props"]},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 40},
        }, "required": ["assetType"], "additionalProperties": False},
    )
    async def get_asset_extraction_asset_catalog(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="get_asset_extraction_asset_catalog", label="ai-video 已有资产目录",
        )

    asset_extraction_item_schema = {
        "type": "object", "properties": {
            "candidateId": {"type": "string"},
            "assetId": {"type": "string", "description": "复用已有资产时填写现有 ID；新资产不填写。"},
            "name": {"type": "string"},
            "aliases": {"type": "array", "items": {"type": "string"}},
            "desc": {"type": "string"},
            "assetImagePrompt": {"type": "string"},
            "designRationale": {"type": "string"},
            "sourceEvidence": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "voiceStyle": {"type": "string"},
            "sceneReferenceRole": {"type": "string", "enum": ["work_chain_reference"]},
        },
        "required": ["name", "sourceEvidence"],
        "additionalProperties": False,
    }
    @tool(
        "submit_asset_extraction_result",
        "提交已按 asset-extraction-agent Skill 检查的四类资产与覆盖审计。后端核对原文证据、旧资产身份、用户要求版本和输入摘要，原子写入并回读；成功返回 committed 与 receiptId，随后调用 publish_task_report。",
        {"type": "object", "properties": {
            "assetRangeId": {"type": "string"},
            "inputDigest": {"type": "string"},
            "requirementRevision": {"type": "integer", "minimum": 0},
            "assetBatch": {"type": "object", "properties": {
                "characters": {"type": "array", "items": asset_extraction_item_schema},
                "creatures": {"type": "array", "items": asset_extraction_item_schema},
                "scenes": {"type": "array", "items": asset_extraction_item_schema},
                "props": {"type": "array", "items": asset_extraction_item_schema},
                "coverageAudit": {"type": "object", "properties": {
                    "checked": {"type": "boolean"},
                    "assetBoundaryAudit": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                    "mergeDecisions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                    "skippedMentions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                    "unresolved": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                }, "required": ["checked"], "additionalProperties": False},
                "assetCoverageTable": {"type": "object", "additionalProperties": True},
                "notes": {"type": "array", "items": {"type": "string"}},
            }, "required": ["characters", "creatures", "scenes", "props", "coverageAudit"],
                "additionalProperties": False},
        }, "required": ["assetRangeId", "inputDigest", "requirementRevision", "assetBatch"],
            "additionalProperties": False},
    )
    async def submit_asset_extraction_result(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="submit_asset_extraction_result", label="ai-video 资产拆分写入核验",
        )

    @tool(
        "get_plot_split_context",
        "按用途读取当前分集剧情拆分资料：source_text 只返回本集已提交的纯原文；asset_catalog 只返回可关联的四类资产 ID 与精简身份。两项分开读取。",
        {"type": "object", "properties": {
            "part": {"type": "string", "enum": ["source_text", "asset_catalog"]},
            "episodeId": {"type": "string", "description": "可选。只允许当前会话绑定的分集 ID。"},
        }, "required": ["part"], "additionalProperties": False},
    )
    async def get_plot_split_context(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="get_plot_split_context", label="ai-video 当前分集剧情拆分资料",
        )

    @tool(
        "submit_plot_split_candidate",
        "提交当前分集的完整剧情拆分候选：每段提供有行动意义的标题、边界理由、连续逐字原文、单独清理的非剧情原文片段及可视资产 ID。后端推导来源坐标、校验结构并暂存待确认候选；成功后停止创作，等待用户确认或反馈。失败时根据 errors 的 path 与修复动作调整后重交。",
        {"type": "object", "properties": {
            "episodeId": {"type": "string", "description": "可选。只允许当前会话绑定的分集 ID。"},
            "segments": {"type": "array", "items": {
                "type": "object", "properties": {
                    "text": {"type": "string", "description": "本段连续逐字原文；所有段去除空白后必须完整覆盖当前分集原文。"},
                    "excludedTexts": {"type": "array", "items": {"type": "string"}, "description": "按原文顺序列出本段需清理的章节标题、正文外广告、网址或联系方式的完整逐字原文；剧情中实际出现或使用的同类信息必须保留。无清理内容时填空数组。"},
                    "title": {"type": "string", "description": "概括本段主要行动、冲突或结果的短标题，不用‘剧情1’之类编号代替。"},
                    "splitReason": {"type": "string", "description": "说明本段主问题、行动落点，以及与相邻段为何在此分界。"},
                    "characters": {"type": "array", "items": {"type": "string"}},
                    "creatures": {"type": "array", "items": {"type": "string"}},
                    "scenes": {"type": "array", "items": {"type": "string"}},
                    "props": {"type": "array", "items": {"type": "string"}},
                }, "required": ["text", "excludedTexts", "title", "splitReason", "characters", "creatures", "scenes", "props"],
                "additionalProperties": False,
            }},
        }, "required": ["segments"], "additionalProperties": False},
    )
    async def submit_plot_split_candidate(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="submit_plot_split_candidate", label="ai-video 剧情拆分候选校验",
        )

    @tool(
        "get_cinematic_script_context",
        "优先用 generation_bundle 一次取得同版片段原文、前段承接、当前稿、创作策略、本轮要求及 inputDigest；其余 part 仅供必要补读和旧任务兼容。必须明确 episodeId、nodeId。",
        {"type": "object", "properties": {
            "episodeId": {"type": "string"},
            "nodeId": {"type": "string"},
            "part": {"type": "string", "enum": ["generation_bundle", "source_fragment", "novel_context", "previous_script", "strategies", "current_script", "submission_state"]},
        }, "required": ["episodeId", "nodeId", "part"], "additionalProperties": False},
    )
    async def get_cinematic_script_context(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="get_cinematic_script_context", label="ai-video 片段剧本创作资料",
        )

    @tool(
        "submit_cinematic_script_result",
        "提交当前片段的影视化剧本；校验读取版本并回读成功后返回 receiptId。",
        {"type": "object", "properties": {
            "episodeId": {"type": "string"},
            "nodeId": {"type": "string"},
            "cinematicStoryText": {"type": "string"},
            "scriptTemplateId": {"type": "string"},
            "inputDigest": {"type": "string"},
            "deliveryContract": {"type": "object", "description": "同轮写出的少量关键因果信息交付映射；不另起模型任务。只有观众实际能看到、听到或读清的正文可作 scriptEvidence。", "properties": {
                "items": {"type": "array", "minItems": 1, "maxItems": 12, "items": {"type": "object", "properties": {
                    "sourceKind": {"type": "string", "enum": ["source_fragment", "user_instruction"]},
                    "sourceQuote": {"type": "string"},
                    "audienceInformation": {"type": "string"},
                    "timeAndCertainty": {"type": "string"},
                    "deliveryPaths": {"type": "array", "minItems": 1, "items": {"type": "string", "enum": ["visible_action", "dialogue", "inner_voice", "narration", "screen_text"]}},
                    "scriptEvidence": {"type": "string"},
                }, "required": ["sourceKind", "sourceQuote", "audienceInformation", "timeAndCertainty", "deliveryPaths", "scriptEvidence"], "additionalProperties": False}},
            }, "required": ["items"], "additionalProperties": False},
        }, "required": ["episodeId", "nodeId", "cinematicStoryText", "scriptTemplateId", "inputDigest"],
            "additionalProperties": False},
    )
    async def submit_cinematic_script_result(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="submit_cinematic_script_result", label="ai-video 片段剧本提交校验",
        )

    @tool(
        "get_director_plan_context",
        "首选 planning_bundle 一次取得资料。后端在本轮记录读取版本，补读与预检可省略 inputDigest；若填写，只能用结果最外层 inputDigest，不能使用工具元数据 outputDigest。自动选择后带 selectedDirectorRuleId 读 director_rule 正文。其他 part 只用于必要补读。",
        {"type": "object", "properties": {
            "episodeId": {"type": "string"}, "nodeId": {"type": "string"},
            "part": {"type": "string", "enum": ["planning_bundle", "shootable_content", "episode_continuity", "rule_catalog", "director_rule", "visual_assets", "project_visuals", "speaker_identities", "planning_state", "revision_state"]},
            "inputDigest": {"type": "string", "description": "可省略；后端沿用本轮最近一次 planning_bundle/planning_state 的读取版本，并在提交前重新核对。"},
            "selectedDirectorRuleId": {"type": "string", "description": "自动选择模式读取 director_rule 时传入从 rule_catalog 选出的规则 ID；手动模式不传。"},
        }, "required": ["episodeId", "nodeId", "part"], "additionalProperties": False},
    )
    async def get_director_plan_context(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="get_director_plan_context", label="ai-video 分镜脚本创作资料",
        )

    _director_plan_shot_schema = {
        "type": "object", "properties": {
            "shotNo": {"type": "integer", "minimum": 1},
            "visualPurpose": {"type": "string", "description": "本镜独有的可见画面和戏剧观看任务：揭示、必要反应、关系/视角转换等。长对白可在这些重点处跨镜连续；换人说话或细小动作本身不算。"},
            "normalDurationSec": {"type": "number", "exclusiveMinimum": 0, "maximum": 3600,
                                  "description": "新稿或保留原估时的修订稿填写；按正常语速与正常画面表达预估本镜秒数，不读取项目倍率或视频模型档位。"},
            "durationSec": {"type": "number", "exclusiveMinimum": 0, "maximum": 3600,
                            "description": "仅修订已手工定时的镜头时填写原正式镜长；不得与 normalDurationSec 同时填写。"},
            "nonOverlappingBeats": {"type": "array", "description": "有不能再压缩的实际用时下限时填写，包括独立无声动作以及必须与发声或其他动作错时完成的动作；可同步完成的变化不重复计时。各项秒数须计入正常估时或手工正式镜长。", "items": {"type": "object", "properties": {
                "description": {"type": "string", "description": "本镜 videoExecution 中可核对的独立动作。"},
                "durationSec": {"type": "number", "exclusiveMinimum": 0, "maximum": 3600, "description": "该动作不可再压缩的实际秒数，不随项目画面节奏倍率缩短。"},
            }, "required": ["description", "durationSec"], "additionalProperties": False}},
            "groupBreakBefore": {"type": "boolean", "description": "仅当本镜与前镜确实不能在同一视频段连续执行时填 true；普通切镜或特殊类型入出不是硬边界。"},
            "groupBreakReason": {"type": "string", "description": "仅当 groupBreakBefore=true 时填写具体时空或制作断裂事实；只用于本轮自动分组，不进入正式镜头字段。"},
            "storyboardFrame": {"type": "string", "description": "只写可冻结的起始关键画面；类型效果由图片阶段根据 presentation.modes 自动附加。"},
            "videoExecution": {"type": "string", "description": "只写从起始画面到结束状态的连续镜内表演、动作与运镜，不写类型效果；可含多句对白。若镜长明显超过发声时间，写明不可并行的动作或停顿及其时间依据。"},
            "endState": {"type": "string"},
            "assets": {"type": "object", "properties": {
                kind: {"type": "array", "items": {"type": "string"}}
                for kind in ("characters", "creatures", "scenes", "props")
            }, "required": ["characters", "creatures", "scenes", "props"]},
            "visibleAssets": {"type": "object", "description": "本镜实际可见、可辨的资产 ID，必须是 assets 子集。画外声源和仅被提及的资产不填；首次登场由程序计算。", "properties": {
                kind: {"type": "array", "items": {"type": "string"}}
                for kind in ("characters", "creatures", "scenes", "props")
            }, "required": ["characters", "creatures", "scenes", "props"], "additionalProperties": False},
            "startVisibleAssets": {"type": "object", "description": "起始画格已可见的资产，必须是 visibleAssets 子集；镜内稍后入画者不填。", "properties": {
                kind: {"type": "array", "items": {"type": "string"}}
                for kind in ("characters", "creatures", "scenes", "props")
            }, "required": ["characters", "creatures", "scenes", "props"], "additionalProperties": False},
            "presentation": {"type": "object", "description": "仅特殊段落填写来源、时间、主客观及确定程度；普通现场省略。首次填完整字段，后续连续镜头可只填相同 modes 与 segmentId。", "properties": {
                "modes": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string", "enum": sorted(_PRESENTATION_MODES)}},
                "segmentId": {"type": "string", "description": "特殊段落必填；普通现场省略。"},
                "sourcePerspective": {"type": "string", "description": "现实或主观来源及其知识归属；特殊段落必填。"},
                "certainty": {"type": "string", "description": "事实确定程度；特殊段落必填。"},
                "timeRelation": {"type": "string", "description": "相对当前现场的时间方向或并行关系；特殊段落必填。"},
                "eventLabel": {"type": "object", "description": "仅特殊段落确需有据事件短标识时填写。", "properties": {
                    "content": {"type": "string"}, "sourceQuote": {"type": "string"},
                    "visibleAtStart": {"type": "boolean"},
                }, "required": ["content", "sourceQuote", "visibleAtStart"], "additionalProperties": False},
                "entryCue": {"type": "string"}, "exitCue": {"type": "string"},
            }, "required": ["modes"], "additionalProperties": False},
            "screenTextEvents": {"type": "array", "description": "只列必须读清且有来源的剧情载体文字；普通消息快速变化写进画面执行。", "items": {"type": "object", "properties": {
                "content": {"type": "string"}, "medium": {"type": "string"},
                "authorLabel": {"type": "string"}, "timing": {"type": "string"},
                "visibleAtStart": {"type": "boolean", "description": "文字在 storyboardFrame 起始画格是否已可见；图片阶段只呈现 true。"},
            }, "required": ["content", "medium"]}},
            "soundEvents": {"type": "array", "description": "对白/旁白可以按自然短句跨镜连续；相邻声事件按顺序拼接须保留原句全部原字和标点，同一声源跨镜保留 speakerId。", "items": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": sorted(_DIRECTOR_PLAN_SOUND_KINDS)},
                "voiceType": {"type": "string", "enum": sorted(_DIRECTOR_PLAN_VOICE_TYPES)},
                "speakerId": {"type": "string"}, "sourceName": {"type": "string"},
                "content": {"type": "string"}, "expressionNotes": {"type": "string"},
                "timing": {"type": "string"},
                "durationSec": {"type": "number", "exclusiveMinimum": 0, "maximum": 3600, "description": "仅供非人声事件；人声时长由后端按正常语速估算，voice 不得填写。"},
                "deliveryOverride": {"type": "object", "description": "仅当原文或本轮用户指令明确要求拖长发声时用于 voice；普通对白不得填写，必要停顿写入 videoExecution。", "properties": {
                    "durationSec": {"type": "number", "exclusiveMinimum": 0, "maximum": 3600, "description": "有来源依据的正常语速发声时长，必须长于后端正常语速基准。"},
                    "evidenceSource": {"type": "string", "enum": ["source_text", "user_instruction"]},
                    "evidenceText": {"type": "string", "description": "逐字摘录明确要求慢说或拖长发声的原文/本轮用户指令；只引用对白内容不算依据。"},
                    "reason": {"type": "string", "description": "解释为什么该依据要求本句偏离正常语速。"},
                }, "required": ["durationSec", "evidenceSource", "evidenceText", "reason"], "additionalProperties": False},
            }, "required": ["kind", "content"]}},
        }, "required": ["shotNo", "visualPurpose", "entryBoundaryKind", "audioBoundaryKind", "storyboardFrame",
                         "videoExecution", "endState", "assets", "visibleAssets", "screenTextEvents", "soundEvents"],
           "oneOf": [{"required": ["normalDurationSec"]}, {"required": ["durationSec"]}],
    }
    # New shots use normal estimates; manually timed revisions keep their
    # formal durations. The backend validates and stores both paths.
    _director_plan_shot_schema["properties"]["screenTextEvents"]["description"] = (
        "只列本镜必须读清且有来源的剧情载体文字；快速掠过的消息写入画面执行，不逐条配音。"
        "书面讨论按正式剧本指定的不同声源进入 soundEvents，其他消息只是快速画面信息流。"
    )
    _director_plan_payload_schema = {"type": "object", "properties": {
            "episodeId": {"type": "string"}, "nodeId": {"type": "string"},
            "shots": {"type": "array", "minItems": 1, "items": _director_plan_shot_schema},
            "groups": {"type": "array", "minItems": 1, "description": "仅当硬边界缺少 groupBreakReason 或需要人工调整时，在首轮预检返回正式 durationSec 后填写；其余由后端自动分组。", "items": {"type": "object", "properties": {
                "shotNos": {"type": "array", "minItems": 1, "items": {"type": "integer", "minimum": 1}},
                "reason": {"type": "string", "description": "相邻两组合计仍在时长上限内时，说明新组首镜为何不能与前组连续执行，并在该镜标记 groupBreakBefore。容量超限无需编造原因。"},
            }, "required": ["shotNos"]}},
            "speakerRoster": {"type": "array", "items": {"type": "object", "properties": {
                "speakerId": {"type": "string"}, "displayName": {"type": "string"},
                "identityDescription": {"type": "string", "description": "只写来源已知的身份事实；男／女声等配音选择写在对应 soundEvents.expressionNotes。"},
            }, "required": ["speakerId", "displayName"]}},
            "speechBudgetNote": {"type": "string"},
            "inputDigest": {"type": "string", "description": "可省略；后端使用本轮最近一次读取的版本并在预检时重新核对。"},
            "selectedDirectorRuleId": {"type": "string", "description": "自动选择模式必填，必须与预检时选择的规则 ID 一致；手动模式留空。"},
        }, "required": ["episodeId", "nodeId", "shots", "speakerRoster"],
            "additionalProperties": False}
    _director_plan_commit_schema = copy.deepcopy(_director_plan_payload_schema)
    _director_plan_commit_schema["properties"]["validatedSubmissionDigest"] = {
        "type": "string",
        "description": "预检通过返回的 submissionDigest。只传此摘要和目标即可按本轮原稿提交；不要再重发镜头数组。",
    }
    _director_plan_commit_schema["required"] = ["episodeId", "nodeId"]
    @tool(
        "validate_director_plan_draft",
        "只读预检：不传 groups 时按正式镜长及带 groupBreakReason 的硬边界自动分组并校验，返回 generatedGroups 和 submissionDigest；无法自动分组时返回 shotsForGrouping/groupMaxSeconds，再传同一草稿和语义分组 groups。",
        _director_plan_payload_schema,
    )
    async def validate_director_plan_draft(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="validate_director_plan_draft", label="ai-video 分镜草稿校验",
        )

    @tool(
        "submit_director_plan_result",
        "提交已经通过预检的分镜草稿。只传 episodeId、nodeId 和预检返回的 validatedSubmissionDigest；后端沿用本轮读取版本和完整草稿及分组，重验、写入和回读。草稿改动必须重新预检。",
        _director_plan_commit_schema,
    )
    async def submit_director_plan_result(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="submit_director_plan_result", label="ai-video 分镜脚本提交校验",
        )

    @tool(
        "get_video_prompt_context",
        "首选 generation_bundle 一次读取工作链本卡镜头、来源镜号、锁定时长、声音、素材、衔接和模型。已锁定目标时只传 part；普通聊天未锁定目标时，首次读取用 nodeId 选择用户明确指定的卡片。系统校验并锁定目标与输入版本，其他 part 供缺项补读。",
        {"type": "object", "properties": {
            "nodeId": {"type": "string", "description": "普通聊天首次读取时选择用户指定的卡片；已有锁定目标时省略"},
            "part": {"type": "string", "enum": ["generation_bundle", "assigned_shots", "voice_context", "asset_names", "references", "continuity", "target_model", "current_prompt", "submission_state"]},
        }, "required": ["part"], "additionalProperties": False},
    )
    async def get_video_prompt_context(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="get_video_prompt_context", label="ai-video 视频提示词创作资料",
        )

    @tool(
        "submit_video_prompt_result",
        "只提交 video（shots）和 sound（soundPrompt、usedSpeakerIds、voiceDesign）两个对象，目标卡片和已读取的输入版本由系统携带。校验时间账、镜头顺序、台词及声音身份，保存回读后返回 receiptId，随后调用 publish_task_report。",
        VIDEO_PROMPT_RESULT_SCHEMA,
    )
    async def submit_video_prompt_result(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="submit_video_prompt_result", label="ai-video 视频提示词提交校验",
        )

    @tool(
        "get_video_prompt_optimization_context",
        "先读 draft_text，再按需读取素材、引用、声音、旧稿和 target_model。已锁定目标时只传 part；普通聊天首次读取可用 nodeId 选择用户指定的独立卡，并以其已保存正文和声音作为草稿。目标和版本由系统锁定，submission_state 可刷新输入版本。",
        {"type": "object", "properties": {
            "nodeId": {"type": "string", "description": "普通聊天首次读取时选择用户指定的卡片；已有锁定目标时省略"},
            "part": {"type": "string", "enum": ["draft_text", "asset_names", "references", "voice_context", "target_model", "current_prompt", "submission_state"]},
        }, "required": ["part"], "additionalProperties": False},
    )
    async def get_video_prompt_optimization_context(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="get_video_prompt_optimization_context", label="ai-video 独立视频卡优化资料",
        )

    @tool(
        "submit_video_prompt_optimization_result",
        "只提交 video（shots）和 sound（soundPrompt、usedSpeakerIds、voiceDesign）两个优化结果对象。目标卡片和已读取的输入版本由系统携带；校验时间账、草稿及素材后保存，返回 receiptId，随后调用 publish_task_report。",
        VIDEO_PROMPT_RESULT_SCHEMA,
    )
    async def submit_video_prompt_optimization_result(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="submit_video_prompt_optimization_result", label="ai-video 独立视频卡优化提交校验",
        )

    @tool(
        "get_video_prompt_standalone_context",
        "先读 source_cards 中每张来源卡的权威正文，再按需读取素材、引用、声音及 target_model 中的整卡时长。已锁定目标时只传 part；普通聊天首次读取用 nodeId 选择用户指定的独立卡。目标和输入版本由系统锁定。",
        {"type": "object", "properties": {
            "nodeId": {"type": "string", "description": "普通聊天首次读取时选择用户指定的卡片；已有锁定目标时省略"},
            "part": {"type": "string", "enum": ["source_cards", "asset_names", "references", "voice_context", "target_model", "current_prompt", "submission_state"]},
        }, "required": ["part"], "additionalProperties": False},
    )
    async def get_video_prompt_standalone_context(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="get_video_prompt_standalone_context", label="ai-video 独立视频卡创作资料",
        )

    @tool(
        "submit_video_prompt_standalone_result",
        "只提交 video（shots）和 sound（soundPrompt、usedSpeakerIds、voiceDesign）两个生成结果对象。目标卡片和已读取的输入版本由系统携带；校验时间账及原始输入后保存，返回 receiptId，随后调用 publish_task_report。",
        VIDEO_PROMPT_RESULT_SCHEMA,
    )
    async def submit_video_prompt_standalone_result(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="submit_video_prompt_standalone_result", label="ai-video 独立视频卡生成提交校验",
        )

    @tool(
        "list_agent_actions",
        "列出当前 ai-video 后端允许模型代理流程请求执行的动作。无需参数。",
        {"type": "object", "properties": {}},
    )
    async def list_agent_actions(_args: dict[str, Any]) -> dict[str, Any]:
        try:
            snapshot = await _call_provider(snapshot_provider, domains=["project"])
            return _json_text(
                {
                    "success": True,
                    "availableActions": snapshot.get("availableActions") or [],
                    "recommendedAction": (snapshot.get("projectProgress") or {}).get("nextAction"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            return _tool_error("list_agent_actions", exc)

    @tool(
        "request_agent_action",
        (
            "请求 ai-video 后端执行导航、概述分析等允许动作。不要用于小说拆分、资产提取、"
            "分集剧本或分镜提示词等可变文本任务；这些任务必须使用项目操作目录里的专用 MCP 工具。"
        ),
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "必须是 list_agent_actions 返回的 action。",
                },
                "rationale": {
                    "type": "string",
                    "description": "面向用户解释为什么需要执行该动作。",
                },
                "userInstruction": {
                    "type": "string",
                    "description": "可选。用户本轮对重拆、重生成或优化的具体要求；如果用户提出修改意见，必须原样提炼写入。",
                },
            },
            "required": ["action"],
        },
    )
    async def request_agent_action(args: dict[str, Any]) -> dict[str, Any]:
        try:
            action = str(args.get("action") or "").strip()
            rationale = _rationale_with_user_instruction(args)
            result = await asyncio.to_thread(action_request_handler, action, rationale)
            return _json_text({"success": True, **result}, label="ai-video 动作请求")
        except Exception as exc:  # noqa: BLE001
            return _tool_error("request_agent_action", exc)

    async def _request_predefined_action(
        args: dict[str, Any],
        *,
        action: str,
        default_rationale: str,
        label: str,
    ) -> dict[str, Any]:
        rationale = _rationale_with_user_instruction(args, default_rationale)
        try:
            result = await asyncio.to_thread(action_request_handler, action, rationale)
            return _json_text({"success": True, **result}, label=label)
        except Exception as exc:  # noqa: BLE001
            return _tool_error(label, exc)

    _rationale_schema = {
        "type": "object",
        "properties": {
            "rationale": {
                "type": "string",
                "description": "面向用户解释为什么需要执行这个 ai-video 后端动作。",
            },
            "userInstruction": {
                "type": "string",
                "description": "可选。用户本轮对生成、重做或优化结果的具体反馈；有反馈时必须填写。",
            },
        },
    }

    @tool(
        "request_overview_analysis",
        "请求后端读取小说文本并生成项目概述、题材语境和主题视觉。",
        _rationale_schema,
    )
    async def request_overview_analysis(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_predefined_action(
            args,
            action="analyze_overview",
            default_rationale="用户需要先生成项目概述、题材语境和主题视觉，为展示、图片视觉和后续弱类型约束准备基础数据。",
            label="ai-video 项目概述请求",
        )

    @tool(
        "request_open_current_episode",
        "请求前端定位到当前绘画工作流，便于用户检查分镜和生成进度。",
        _rationale_schema,
    )
    async def request_open_current_episode(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_predefined_action(
            args,
            action="open_current_episode",
            default_rationale="用户需要检查当前绘画工作流。",
            label="ai-video 打开当前绘画请求",
        )

    _episode_schema = {
        "type": "object",
        "properties": {
            "episodeId": {"type": "string", "description": "可选。为空时使用当前选中的画布/分集。"},
        },
    }

    @tool(
        "save_story_world_map",
        "保存 Agent 已经生成的全书理解/故事地图。工具只校验并落库，不替 Agent 创作内容。",
        {
            "type": "object",
            "properties": {
                "storyWorld": {"type": "object", "description": "story_world.json 内容。"},
                "summary": {"type": "string", "description": "可选。本次保存摘要。"},
                "expectedRevision": {"type": "integer", "description": "可选。storyWorld 资源 revision 防覆盖。"},
                "baseHash": {"type": "string", "description": "可选。storyWorld 资源 hash 防覆盖。"},
                "reason": {"type": "string"},
                "userInstruction": {"type": "string"},
            },
            "required": ["storyWorld"],
        },
    )
    async def save_story_world_map(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="save_story_world_map",
            label="ai-video 故事地图保存",
        )

    @tool(
        "upsert_asset",
        "新增或定向更新单个项目资产。只修一名角色、一个生物、一个场景或一个道具时使用；整批拆分使用资产范围流程。先读取已有资产及 revision，再按本轮授权修改。局部替换、纠错、删除旧表述、重写或压缩时，保留未涉及的内容，提交所改字段的完整最终文本并传 replaceExisting=true；否则后端会将新旧文本合并，可能留下冲突或重复。纯追加且旧内容全部仍有效时才可省略该参数。保存后回读所改字段，核对修改与未变约束。",
        {
            "type": "object",
            "properties": {
                "assetType": {"type": "string", "description": "characters、creatures、scenes、props 或 styles。"},
                "asset": {"type": "object", "description": "单个资产对象，支持 id/name/desc/prompts.assetImagePrompt；新建时必须写 name、desc 和已设计的 prompts.assetImagePrompt，且不传旧资产 id；新建角色尽量写本人稳定的语言型 voiceStyle，无法确定可留空；生物仅在明确具有语言型声线时写 voiceStyle，canSpeak 由后端推导。不要通过本工具写 stateTag/stateTags；状态标签仅来自历史版本里用户手动编辑的版本标注。只修改一个已有资产或新增一个明确资产时使用；整批提取使用资产范围流程。稳定资产设定写 desc；资产母版提示词写 prompts.assetImagePrompt。更新已有资产文本时默认提交合并后的完整文本，不要只提交新增片段；不要写 visualSpec、continuity、generation 或临时剧情状态。"},
                "expectedRevision": {"type": "integer", "description": "可选。assets 资源 revision 防覆盖。"},
                "baseHash": {"type": "string", "description": "可选。assets 资源 hash 防覆盖。"},
                "replaceExisting": {"type": "boolean", "description": "文本写入方式，不代表替换整个资产。true 将本次提供的 desc、prompts.assetImagePrompt、voiceStyle 保存为完整最终文本；未提供字段保留。用户要求局部替换或纠错也应在读取当前值后传 true，并完整保留其他有效文字。false 或省略会保留并追加合并旧文本，只用于旧内容全部仍成立的补充；不得用追加表达取代或撤销旧设定。"},
                "reason": {"type": "string"},
                "userInstruction": {"type": "string"},
            },
            "required": ["assetType", "asset"],
        },
    )
    async def upsert_asset(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="upsert_asset",
            label="ai-video 单资产保存",
        )

    @tool(
        "delete_asset",
        "为项目中的单个角色、生物、场景或道具资产提交删除待确认请求；此工具不会立即删除。等待用户在会话中点击确认。",
        {
            "type": "object",
            "properties": {
                "assetType": {"type": "string", "description": "characters、creatures、scenes 或 props。"},
                "assetId": {"type": "string", "description": "要删除的资产 ID。"},
                "scope": {"type": "string", "description": "默认 project。"},
                "expectedRevision": {"type": "integer", "description": "可选。assets 资源 revision 防覆盖。"},
                "baseHash": {"type": "string", "description": "可选。assets 资源 hash 防覆盖。"},
                "reason": {"type": "string"},
                "userInstruction": {"type": "string"},
            },
            "required": ["assetType", "assetId"],
        },
    )
    async def delete_asset(args: dict[str, Any]) -> dict[str, Any]:
        next_args = {"scope": "project", **(args or {})}
        return await _request_backend_tool(
            next_args,
            tool_name="delete_asset",
            label="ai-video 单资产删除",
        )

    @tool(
        "delete_all_project_assets",
        "清空当前项目中拆分得到的角色、生物、场景、道具等资产。只有用户明确要求“清空/删除全部/所有资产”且已二次明确确认时才能调用；禁止用于试探、建议、删除最新一组或含糊请求。",
        {
            "type": "object",
            "properties": {
                "assetTypes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选。默认清空 characters/creatures/scenes/props；传 all 才包含 styles。",
                },
                "resetAssetRanges": {
                    "type": "boolean",
                    "description": "默认 true。同步清除资产提取范围的进度游标。",
                },
                "confirmDeleteAll": {
                    "type": "boolean",
                    "description": "必须为 true，表示已经先向用户报告影响，并收到明确清空全部资产确认。",
                },
                "expectedRevision": {"type": "integer", "description": "可选。assets 资源 revision 防覆盖。"},
                "baseHash": {"type": "string", "description": "可选。assets 资源 hash 防覆盖。"},
                "reason": {"type": "string"},
                "userInstruction": {
                    "type": "string",
                    "description": "必须填写用户原始明确删除指令，例如“清空当前项目所有角色、生物、场景、道具资产”。",
                },
            },
            "required": ["confirmDeleteAll", "userInstruction"],
        },
    )
    async def delete_all_project_assets(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args or {},
            tool_name="delete_all_project_assets",
            label="ai-video 项目资产全部删除",
        )

    @tool(
        "save_episode_work_chain_plan",
        "保存当前集已确认的工作链结构并生成画布工作链；普通对话中的完整工作链生成须先取得原文事实拆分提案并等待用户确认。这里只保存左侧原文事实、sourceRefs 和 assetRefs；右侧影视化剧本、故事版模板、视频片段时长、分镜节拍、视频提示词和视频片段另行生成。sourceRefs 传 sourceId + absoluteStart/absoluteEnd；每个 segment/shot 应带 assetRefs 引用相关角色、生物、场景和道具。同一连续空间内的泛称房间、未命名房间或局部机位，应引用已有父级稳定场景，并把局部位置、机位、站位和临时状态写入镜头字段。",
        {
            "type": "object",
            "properties": {
                **_episode_schema["properties"],
                "workChainPlan": {"type": "object", "description": "当前集工作链计划结构；保存后端会生成画布工作链。"},
                "expectedRevision": {"type": "integer", "description": "可选。工作链计划 revision 防覆盖。"},
                "baseHash": {"type": "string", "description": "可选。工作链计划 hash 防覆盖。"},
                "reason": {"type": "string"},
                "userInstruction": {"type": "string"},
            },
            "required": ["workChainPlan"],
        },
    )
    async def save_episode_work_chain_plan(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="save_episode_work_chain_plan",
            label="ai-video 工作链计划保存",
        )

    @tool(
        "patch_shot_prompt",
        "只修改当前分集某个 segment/shot 或画布片段剧本的提示词、镜头说明、sourceRefs 或 assetRefs，不覆盖整张画布；sourceUnitIds 由后端按 offset 自动补齐。",
        {
            "type": "object",
            "properties": {
                **_episode_schema["properties"],
                "segmentId": {"type": "string", "description": "可选。目标 segments[].id。"},
                "shotId": {"type": "string", "description": "可选。目标 shots[].id。"},
                "index": {"type": "integer", "description": "可选。无 ID 时按 1-based index 定位。"},
                "fields": {"type": "object", "description": "要合并到目标条目的字段，例如 title、sourceRefs、assetRefs、continuityAnchor。"},
                "sourceRefs": {"type": "array", "items": {"type": "object"}, "description": "可选。目标镜头对应原文引用，通常只填 sourceId、absoluteStart、absoluteEnd。"},
                "assetRefs": {"type": "object", "description": "可选。目标镜头引用的角色/生物/场景/道具资产，例如 {characters: [], creatures: [], scenes: [], props: []}。同一连续空间内的泛称房间、未命名房间或局部机位应引用已有父级稳定场景，不要新增场景资产。"},
                "expectedRevision": {"type": "integer", "description": "可选。工作链计划 revision 防覆盖；当前画布任务卡优先走节点级版本保护。"},
                "baseHash": {"type": "string", "description": "可选。工作链计划 hash 防覆盖。"},
                "reason": {"type": "string"},
                "userInstruction": {"type": "string"},
            },
        },
    )
    async def patch_shot_prompt(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="patch_shot_prompt",
            label="ai-video 单镜头提示词 patch",
        )

    @tool(
        "upsert_workflow_node",
        "新增或定向更新工作流中的 node/route，适合局部修普通画布数据，不覆盖整张画布；资产关联统一使用 link_workflow_input，不能直接修改连线；不能用来新建分集原文、片段剧本、分镜脚本、分镜图、工作链视频生成或视频片段；节点 sourceRefs 会按 offset 自动绑定 sourceUnitIds。",
        {
            "type": "object",
            "properties": {
                **_episode_schema["properties"],
                "itemType": {"type": "string", "enum": ["node", "route"], "description": "默认 node。"},
                "item": {"type": "object", "description": "要新增或合并的 node/route。"},
                "id": {"type": "string", "description": "可选。目标 item id。"},
                "expectedRevision": {"type": "integer", "description": "可选。workflow revision 防覆盖。"},
                "reason": {"type": "string"},
                "userInstruction": {"type": "string"},
            },
        },
    )
    async def upsert_workflow_node(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="upsert_workflow_node",
            label="ai-video 工作流局部保存",
        )

    @tool(
        "delete_workflow_node",
        "为工作流中的 node/route/workChain 提交删除待确认请求；此工具不会立即删除。取消资产关联统一使用 unlink_workflow_input；工作链主干不能单独删除。",
        {
            "type": "object",
            "properties": {
                **_episode_schema["properties"],
                "itemType": {"type": "string", "enum": ["node", "route", "workChain"], "description": "默认 node。"},
                "itemId": {"type": "string", "description": "要删除的 item id。"},
                "expectedRevision": {"type": "integer", "description": "可选。workflow revision 防覆盖。"},
                "reason": {"type": "string"},
            },
        },
    )
    async def delete_workflow_node(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="delete_workflow_node",
            label="ai-video 工作流局部删除",
        )

    @tool(
        "delete_project_planning_outputs",
        "删除当前项目可重建的分集/分镜/画布规划派生结果。保留 sources/*.txt 原始导入文本。只有用户明确要求清空全部规划、明确指定 episodeIds 删除某一集，或用户确认重新拆分某集前删除该集原文后的派生工作链时才能调用；targets=[\"storyboards\"] 会保留该集分集原文/分集边界，并清理该集画布、任务卡、结果版本、生产状态和派生任务记录；重新拆分场景删除后还需要再触发原文事实拆分流程。",
        {
            "type": "object",
            "properties": {
                "targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选。默认 all；指定 episodeIds 且不传 targets 时默认 source_splits/storyboards。可传 source_index、source_splits、asset_ranges、storyboards。重新拆分某集时只传 storyboards，以保留分集原文和原文范围，同时清理画布/任务卡/结果版本/生产状态/派生任务。",
                },
                "episodeIds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选。指定要删除的分集；删除分集时会从最早命中的集开始清理后续 coverage 范围。",
                },
                "confirmDeleteAll": {
                    "type": "boolean",
                    "description": "必须为 true，表示智能体已判断用户本轮指令明确要求删除该范围。",
                },
                "reason": {"type": "string"},
                "userInstruction": {
                    "type": "string",
                    "description": "必须填写用户原始明确删除指令，例如“清空所有分集和工作链计划”或“删除 E02 这一集”。",
                },
            },
            "required": ["confirmDeleteAll", "userInstruction"],
        },
    )
    async def delete_project_planning_outputs(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args or {},
            tool_name="delete_project_planning_outputs",
            label="ai-video 项目规划派生结果删除",
        )

    @tool(
        "save_workflow_node_inline_edit",
        "保存任务卡扩展框里的局部字段和生成配置；只修改该任务卡自身配置，不读取或写入结果卡。片段剧本右侧影视化剧本写 data.cinematicStoryText，可同步维护 data.adaptationStyle、data.scriptTemplateId；普通片段剧本编辑不要写 data.prompt。分镜脚本镜头方案写 data.directorPlan、data.directorPlanShots、data.speakerRoster、data.directorRuleId；speakerRoster 仅登记临时说话者的原文已知身份，声音事件 expressionNotes 保留原文明确的音色、语气、语速等表达要求，不自行补充声音设计。视频生成最终提示词使用 data.videoTaskCard.finalVideoPrompt。字段值是保存后的最终值；用户要在已有字段上补充、细化或合并时，结合当前节点或最新 workflow 快照的现有值生成完整最终文本再保存。",
        {
            "type": "object",
            "properties": {
                **_episode_schema["properties"],
                "nodeId": {"type": "string", "description": "必填。要修改的任务卡节点 id。"},
                "data": {
                    "type": "object",
                    "description": "可选。任务卡字段 patch。片段剧本写 data.sourceFactText、data.cinematicStoryText、data.adaptationStyle、data.scriptTemplateId；普通片段剧本文字不要写入内部 data.prompt。分镜脚本写 data.directorPlan、data.directorPlanShots、data.speakerRoster、data.durationSeconds、data.directorRuleId；修改台词归属时同步临时身份名单，已有资产与项目旁白通过事件 speakerId 直接引用，不加入名单。视频生成最终提示词写入 data.videoTaskCard.finalVideoPrompt。字段值是保存后的最终值；用户要求补充、细化或合并时，保留现有内容并提交合并后的完整值。",
                },
                "generationConfig": {"type": "object", "description": "可选。模型、尺寸、时长、故事版相关配置 patch；未设置字段保持未配置，生成时由后端按任务卡 -> 项目 -> 全局读取。"},
                "reason": {"type": "string"},
                "userInstruction": {"type": "string"},
            },
            "required": ["nodeId"],
        },
    )
    async def save_workflow_node_inline_edit(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="save_workflow_node_inline_edit",
            label="ai-video 任务卡局部配置保存",
        )

    _workflow_mutation_common_properties = {
        **_episode_schema["properties"],
        "expectedRevision": {"type": "integer", "description": "可选。workflow revision 防覆盖。"},
        "reason": {"type": "string"},
        "userInstruction": {"type": "string"},
    }

    @tool(
        "create_workflow_task_card",
        "在当前集画布中通过底层数据新建独立视频生成，并自动创建对应视频片段与系统结果边；用于智能体代替用户右键新建独立视频生成。工作链上的视频生成只能由生成工作链流程创建。",
        {
            "type": "object",
            "properties": {
                **_workflow_mutation_common_properties,
                "nodeType": {
                    "type": "string",
                    "description": "必填。只能是独立视频生成类型 video.storyboard。",
                },
                "nodeId": {"type": "string", "description": "可选。指定新任务卡节点 id。"},
                "resultNodeId": {"type": "string", "description": "可选。指定自动结果卡节点 id。"},
                "position": {"type": "object", "description": "可选。画布坐标 {x,y}。"},
                "resultPosition": {"type": "object", "description": "可选。自动结果卡坐标 {x,y}。"},
                "size": {"type": "object", "description": "可选。任务卡尺寸。"},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "status": {"type": "string"},
                "prompt": {"type": "string", "description": "可选。任务卡初始 prompt。"},
                "data": {"type": "object", "description": "可选。任务卡 data patch。"},
                "generationConfig": {"type": "object", "description": "可选。任务卡生成配置。"},
            },
            "required": ["nodeType"],
        },
    )
    async def create_workflow_task_card(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="create_workflow_task_card",
            label="ai-video 画布任务卡创建",
        )

    @tool(
        "add_workflow_asset_nodes",
        "把已有角色、生物、场景、道具、外部媒体或生成结果作为素材节点添加到当前集画布。只负责放入画布，不自动接入任务卡；需要接入时继续调用 link_workflow_input。",
        {
            "type": "object",
            "properties": {
                **_workflow_mutation_common_properties,
                "nodes": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "必填。要添加的后端 workflow node 列表；asset.image 节点必须包含 data.assetType 和 data.assetId。",
                },
            },
            "required": ["nodes"],
        },
    )
    async def add_workflow_asset_nodes(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="add_workflow_asset_nodes",
            label="ai-video 画布素材节点添加",
        )

    @tool(
        "update_workflow_route",
        "局部更新画布线路元数据，例如标题、状态、锁定、分镜模板等。不要用它修改任务卡正文或素材连接。",
        {
            "type": "object",
            "properties": {
                **_workflow_mutation_common_properties,
                "routeId": {"type": "string", "description": "必填。目标线路 id。"},
                "route": {"type": "object", "description": "可选。线路字段 patch。"},
                "label": {"type": "string"},
                "title": {"type": "string"},
                "status": {"type": "string"},
                "locked": {"type": "boolean"},
                "lockedByUser": {"type": "boolean"},
                "preserveOnReplan": {"type": "boolean"},
                "lockedReason": {"type": "string"},
                "quality": {"type": "object"},
                "storyboardTemplate": {"type": "string"},
                "storyboardTemplateLabel": {"type": "string"},
            },
            "required": ["routeId"],
        },
    )
    async def update_workflow_route(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="update_workflow_route",
            label="ai-video 画布线路局部更新",
        )

    @tool(
        "link_workflow_input",
        "把已经在画布上的可见素材节点链接到明确任务卡 slot。已有资产、外部媒体或生成结果必须先用 add_workflow_asset_nodes 放到画布并取得 sourceNodeId；本工具不创建 route/workChain/global 隐藏链接。",
        {
            "type": "object",
            "properties": {
                **_workflow_mutation_common_properties,
                "scope": {"type": "string", "enum": ["node"], "description": "必填，固定为 node。"},
                "nodeId": {"type": "string", "description": "必填。目标任务卡节点 id。"},
                "slot": {"type": "string", "description": "目标输入槽，例如 character/creature/scene/prop/storyboard_image/reference_image。"},
                "sourceType": {"type": "string", "description": "可选。asset、external_media、generated_media、version 等，仅作为输入链接元数据；真实连线来源以 sourceNodeId 为准。"},
                "sourceId": {"type": "string", "description": "可选。输入来源业务 id，仅作为链接元数据；不能替代 sourceNodeId。"},
                "assetId": {"type": "string"},
                "assetType": {"type": "string", "description": "characters、creatures、scenes 或 props。"},
                "mediaId": {"type": "string"},
                "mediaType": {"type": "string"},
                "mediaKind": {"type": "string"},
                "versionId": {"type": "string"},
                "sourceNodeId": {"type": "string", "description": "必填。来源画布素材节点 id，用于生成可见素材线；如果只有资产/媒体/生成结果 id，先调用 add_workflow_asset_nodes。"},
                "label": {"type": "string"},
                "note": {"type": "string"},
                "locked": {"type": "boolean"},
                "lockedByUser": {"type": "boolean"},
            },
            "required": ["scope", "nodeId", "slot", "sourceNodeId"],
        },
    )
    async def link_workflow_input(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="link_workflow_input",
            label="ai-video 任务卡素材输入链接",
        )

    @tool(
        "unlink_workflow_input",
        "为任务卡素材输入链接提交移除待确认请求；此工具不会立即移除。调用前先定位 linkId/sourceId/slot 和目标 nodeId，不能盲删。",
        {
            "type": "object",
            "properties": {
                **_workflow_mutation_common_properties,
                "scope": {"type": "string", "enum": ["node"], "description": "必填，固定为 node。"},
                "nodeId": {"type": "string", "description": "必填。目标任务卡节点 id。"},
                "linkId": {"type": "string", "description": "要取消的输入链接 id。"},
                "sourceId": {"type": "string", "description": "可选。按来源 id 删除。"},
                "slot": {"type": "string", "description": "可选。按目标 slot 删除。"},
            },
            "required": ["scope", "nodeId"],
            "anyOf": [
                {"required": ["linkId"]},
                {"required": ["sourceId"]},
                {"required": ["slot"]},
            ],
        },
    )
    async def unlink_workflow_input(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="unlink_workflow_input",
            label="ai-video 任务卡素材输入取消",
        )

    @tool(
        "list_workflow_inputs",
        "读取指定画布任务卡的输入链接，必须传 nodeId，可按 routeId/scope 过滤。用于修改素材连接前确认现有关联。",
        {
            "type": "object",
            "properties": {
                **_episode_schema["properties"],
                "nodeId": {"type": "string"},
                "routeId": {"type": "string"},
                "scope": {"type": "string"},
            },
            "required": ["nodeId"],
        },
    )
    async def list_workflow_inputs(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="list_workflow_inputs",
            label="ai-video 画布输入链接读取",
        )

    @tool(
        "resolve_generation_config",
        "解析某个任务卡的最终图片/视频生成配置，并返回模型能力、警告与阻塞问题；结果卡只按上游任务卡解析，不读取结果卡配置。",
        {
            "type": "object",
            "properties": {
                **_episode_schema["properties"],
                "routeId": {"type": "string"},
                "nodeId": {"type": "string"},
                "nodeType": {"type": "string"},
                "mediaType": {"type": "string", "description": "image 或 video。"},
                "strategy": {"type": "string"},
                "referenceMediaIds": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
    )
    async def resolve_generation_config(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="resolve_generation_config",
            label="ai-video 生成配置解析",
        )

    @tool(
        "validate_project_quality",
        "校验当前项目拆分、原文文件、sourceRefs、sourceUnitIds、资产范围和工作流基础完整性，返回 blocking/warnings。",
        {
            "type": "object",
            "properties": {
                "episodeId": {"type": "string", "description": "可选。只校验指定分集；为空时校验全部已提交分集。"},
            },
        },
    )
    async def validate_project_quality(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="validate_project_quality",
            label="ai-video 项目质量门禁",
        )

    async def _request_backend_tool(
        args: dict[str, Any],
        *,
        tool_name: str,
        label: str,
    ) -> dict[str, Any]:
        if not callable(tool_request_handler):
            result = _json_text(
                {"success": False, "error": "ai-video 业务工具尚未接入后端执行器"},
                label=f"{label} 错误",
            )
            result["is_error"] = True
            return result
        try:
            result = await asyncio.to_thread(tool_request_handler, tool_name, args or {})
            payload = {"success": True, **result}
            mcp_content = payload.pop("mcpContent", None)
            response = _json_text(payload, label=label)
            if payload.get("status") in {"grouping_required", "frame_review_required", "field_review_required",
                                         "validation_failed", "validated", "rejected", "pending_confirmation",
                                         "committed", "published", "already_published"}:
                response["structuredContent"] = {
                    "status": payload["status"],
                    "success": bool(payload.get("success", True)),
                    **({"groupMaxSeconds": payload["groupMaxSeconds"]} if payload.get("groupMaxSeconds") is not None else {}),
                    **({"durationSeconds": payload["durationSeconds"]} if payload.get("durationSeconds") is not None else {}),
                    **({"shotsForGrouping": payload["shotsForGrouping"]} if isinstance(payload.get("shotsForGrouping"), list) else {}),
                    **({"shotTiming": payload["shotTiming"]} if isinstance(payload.get("shotTiming"), list) else {}),
                    **({"submissionDigest": payload["submissionDigest"]} if payload.get("submissionDigest") else {}),
                    **({"receiptId": payload["receiptId"]} if payload.get("receiptId") else {}),
                    **({"reportText": payload["reportText"]} if payload.get("reportText") else {}),
                    **({"errors": payload["errors"]} if isinstance(payload.get("errors"), list) else {}),
                    **({"proposal": payload["proposal"]} if isinstance(payload.get("proposal"), dict) else {}),
                }
            if isinstance(mcp_content, list):
                for item in mcp_content:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") in {"text", "image"}:
                        response["content"].append(item)
            business_feedback = (
                bool(payload.get("requiresAssetExtraction"))
                and str(payload.get("recommendedAction") or "").strip()
                in {"asset_range_propose", "asset_extraction"}
            )
            if not bool(payload.get("success", True)) and not business_feedback and tool_name not in {
                "validate_project_quality",
            }:
                response["is_error"] = True
            return response
        except Exception as exc:  # noqa: BLE001
            advice = _backend_tool_recovery_advice(tool_name, str(exc))
            next_tools = advice.get("nextAllowedTools") if isinstance(advice, dict) else None
            return _tool_error(
                label,
                exc,
                details={"toolName": tool_name, "args": args or {}},
                recovery_advice=advice,
                next_allowed_tools=next_tools if isinstance(next_tools, list) else None,
            )

    _episode_node_schema = {
        "type": "object",
        "properties": {
            "episodeId": {
                "type": "string",
                "description": "可选。为空时使用当前选中的画布/分集。",
            },
            "nodeId": {
                "type": "string",
                "description": "可选。为空时使用该工具对应的默认工作流节点。",
            },
            "rationale": {
                "type": "string",
                "description": "面向用户解释为什么需要执行这个生成动作。",
            },
            "userInstruction": {
                "type": "string",
                "description": "可选。用户对本次片段剧本快照、分镜图或分镜视频生成的具体要求；例如镜头、风格、角色动作、节奏或需避免的问题。",
            },
        },
    }

    @tool(
        "request_storyboard_image_generation",
        "请求后端为当前绘画生成故事版大图/分镜图版本。若用户提出画面修改意见，必须传 userInstruction。",
        _episode_node_schema,
    )
    async def request_storyboard_image_generation(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="request_storyboard_image_generation",
            label="ai-video 分镜图生成请求",
        )

    @tool(
        "request_visual_handoff_image_generation",
        "请求后端为当前工作链生成视觉交接图版本；这是可选连续性参考图，仅在用户明确询问/确认某集子流程当前环节时使用。若用户提出画面修改意见，必须传 userInstruction。",
        _episode_node_schema,
    )
    async def request_visual_handoff_image_generation(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="request_visual_handoff_image_generation",
            label="ai-video 视觉交接图生成请求",
        )

    _storyboard_image_edit_schema = {
        "type": "object",
        "properties": {
            "episodeId": {
                "type": "string",
                "description": "可选。为空时使用当前选中的画布/分集。",
            },
            "nodeId": {
                "type": "string",
                "description": "必填。要编辑的分镜图节点 ID。",
            },
            "baseVersionId": {
                "type": "string",
                "description": "可选。指定要作为编辑基底的分镜图版本 ID；为空时使用当前节点默认版本。",
            },
            "panelIndex": {
                "type": "integer",
                "description": "可选。按工作页顺序从 1 开始的画格序号；只编辑这一镜，其他画格保持原像素。",
            },
            "prompt": {
                "type": "string",
                "description": "本次编辑修改要求。只描述本轮要怎么改，后端会读取原图、根提示词和历史修改记录。",
            },
            "referenceFiles": {
                "type": "array",
                "items": {"type": "object"},
                "description": "可选。本次编辑的参考图文件列表；参考图只作为参考，不作为被编辑原图。",
            },
            "rationale": {
                "type": "string",
                "description": "面向用户解释为什么需要执行这个编辑动作。",
            },
        },
        "required": ["nodeId", "prompt"],
    }

    @tool(
        "edit_storyboard_image",
        "请求后端基于已有分镜图生成图片编辑新版本。必须传 nodeId 和本次修改 prompt；参考图只传 referenceFiles，不能替代被编辑原图。",
        _storyboard_image_edit_schema,
    )
    async def edit_storyboard_image(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="edit_storyboard_image",
            label="ai-video 分镜图编辑请求",
        )

    @tool(
        "request_storyboard_video_generation",
        "使用视频生成已保存的提示词和当前关联图片生成视频，不自动生成或改写提示词；工作链提示词为空时应先显式生成视频提示词。",
        _episode_node_schema,
    )
    async def request_storyboard_video_generation(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="request_storyboard_video_generation",
            label="ai-video 分镜视频生成请求",
        )

    _route_generation_schema = {
        "type": "object",
        "properties": {
            "episodeId": {
                "type": "string",
                "description": "可选。为空时使用当前选中的画布/分集。",
            },
            "routeId": {
                "type": "string",
                "description": "可选。目标画布线路 ID。",
            },
            "nodeId": {
                "type": "string",
                "description": "可选。目标生成节点 ID。",
            },
            "segmentId": {
                "type": "string",
                "description": "可选。目标 segment ID。",
            },
            "prompt": {
                "type": "string",
                "description": "Agent 已写好的生成提示词；工具不代写提示词。",
            },
            "referenceMediaIds": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选。故事版分镜图或角色、生物、场景、道具参考图媒体 ID。",
            },
            "generationConfig": {
                "type": "object",
                "description": "可选。节点/线路专属生成配置。",
            },
            "userInstruction": {
                "type": "string",
                "description": "可选。用户本轮修改要求。",
            },
        },
    }

    @tool(
        "request_route_video_generation",
        "请求后端按画布 route 的 strategy 创建视频生成任务/版本记录。工具只执行固定生成动作，不规划策略。",
        {
            **_route_generation_schema,
            "properties": {
                **_route_generation_schema["properties"],
                "strategy": {"type": "string", "description": "可选。默认 storyboard_multi_shot；用于故事版分镜图参考生视频。"},
            },
        },
    )
    async def request_route_video_generation(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="request_route_video_generation",
            label="ai-video 线路视频生成请求",
        )

    @tool(
        "request_asset_image_generation",
        "请求后端为项目角色、生物、场景或道具生成设计图；后端基于已保存资产 desc / prompts.assetImagePrompt、项目风格和内置版式拼接提示词。不要给本工具传 prompt、assetImagePrompt 或 designPrompt；若用户要求先修改视觉设定或资产母版提示词，先用 upsert_asset 保存，再在用户明确要求生成/重新生成时调用本工具。userInstruction 只记录本轮用户原话，不替代资产持久字段。",
        {
            "type": "object",
            "properties": {
                "assetType": {
                    "type": "string",
                    "description": "资产类型：characters、creatures、scenes 或 props。",
                },
                "assetId": {
                    "type": "string",
                    "description": "项目资产 ID。",
                },
                "hideTurnaroundHeads": {
                    "type": "boolean",
                    "description": "仅角色设计图：不传则沿用角色卡片设置（未设置时有头）；true 为右侧三视图仅省略头部、完整保留颈部及以下，false 为有头。左侧头肩主图不变；显式选择仅作用于本次生成，不修改卡片设置。",
                },
            },
            "required": ["assetType", "assetId"],
        },
    )
    async def request_asset_image_generation(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="request_asset_image_generation",
            label="ai-video 资产设计图生成请求",
        )

    @tool(
        "list_generation_tasks",
        "列出 ai-video 当前生成任务，包括故事版图片、视频、资产图片和导出任务。无需参数。",
        {"type": "object", "properties": {}},
    )
    async def list_generation_tasks(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="list_generation_tasks",
            label="ai-video 生成任务列表",
        )

    @tool(
        "cancel_generation_task",
        "取消一个 ai-video 生成任务，包括正在运行的资产设计图、故事版图片/视频、线路视频或导出任务。",
        {
            "type": "object",
            "properties": {
                "taskId": {"type": "string", "description": "要取消的任务 ID。"}
            },
            "required": ["taskId"],
        },
    )
    async def cancel_generation_task(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="cancel_generation_task",
            label="ai-video 任务取消请求",
        )

    @tool(
        "request_project_export",
        "请求后端导出当前项目的剪映编辑素材包，包含项目清单、素材、分集、任务索引和剪辑参考说明。注意这不是成片合成。",
        {
            "type": "object",
            "properties": {
                "scopes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选导出范围，例如 sources、characters、creatures、scenes、props、episodes、storyboard、tasks。",
                }
            },
        },
    )
    async def request_project_export(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="request_project_export",
            label="ai-video 项目导出请求",
        )

    @tool(
        "list_director_rules",
        "列出 ai-video 本地导演镜头设计规则索引。只返回规则标识和摘要，适合先判断是否需要读取具体规则。",
        {
            "type": "object",
            "properties": {},
        },
    )
    async def list_director_rules(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="list_director_rules",
            label="ai-video 导演规则索引",
        )

    @tool(
        "search_director_rules",
        "按模型自行提出的检索词或需求描述，在本地导演镜头设计规则索引中定位相关规则。工具不负责剧情分类或语义判断；复杂需求可先 list_director_rules 看索引，再 read_director_rule 读取少量相关规则。",
        {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索目标或需求描述。由模型根据当前任务自行组织；不要把它当作固定剧情分类。",
                },
                "maxMatches": {
                    "type": "integer",
                    "description": "最多返回命中数，默认 30，最大 80。",
                },
            },
            "required": ["query"],
        },
    )
    async def search_director_rules(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="search_director_rules",
            label="ai-video 导演规则搜索",
        )

    @tool(
        "read_director_rule",
        "按规则标识读取一个本地导演镜头设计规则。规则只能作为当前剧情/分镜/视频提示词的表达参考，不能新增剧情事实。",
        {
            "type": "object",
            "properties": {
                "ruleId": {
                    "type": "string",
                    "description": "导演规则标识，例如 action_impact。",
                },
                "maxChars": {
                    "type": "integer",
                    "description": "最多返回字符数，默认 8000，最大 24000。优先只读当前任务最相关的小段规则。",
                },
            },
            "required": ["ruleId"],
        },
    )
    async def read_director_rule(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="read_director_rule",
            label="ai-video 导演规则读取",
        )

    @tool(
        "list_project_files",
        "列出当前 ai-video 项目目录内的素材、生成结果和导出文件，供后续 ffmpeg/ffprobe 命令引用相对路径。",
        {
            "type": "object",
            "properties": {
                "roots": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选。相对项目目录的根路径列表，例如 sources、assets、episodes、exports、generated。为空时扫描常用目录。",
                },
                "extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选。只返回这些后缀，例如 .mp4、.png、.wav。",
                },
                "maxFiles": {
                    "type": "integer",
                    "description": "最多返回文件数，默认 120，最大 300。",
                },
            },
        },
    )
    async def list_project_files(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="list_project_files",
            label="ai-video 项目文件列表",
        )

    @tool(
        "search_project_files",
        "在当前 ai-video 项目允许的创作资料范围内按文件名或文本内容搜索。资产拆分时先看 get_asset_extraction_context 返回的资料目录，确有相关文件再搜索；不写入文件。",
        {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词；为空时按 roots/extensions 列出文件。",
                },
                "roots": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选。相对项目目录的根路径列表；为空时按当前工具允许范围搜索。",
                },
                "extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选。只搜索这些后缀，例如 .txt、.json、.png、.docx。",
                },
                "maxFiles": {
                    "type": "integer",
                    "description": "最多扫描文件数，默认 120，最大 500。",
                },
                "maxMatches": {
                    "type": "integer",
                    "description": "最多返回命中数，默认 80，最大 300。",
                },
            },
        },
    )
    async def search_project_files(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="search_project_files",
            label="ai-video 项目文件搜索",
        )

    @tool(
        "read_project_file",
        "读取当前 ai-video 项目允许范围内的创作资料文件。资产拆分可读已列出的相关扩展资料；PDF/Office/图片/二进制会自动选择合适读取方式；不写入文件。",
        {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "当前项目目录内的相对路径。",
                },
                "maxChars": {
                    "type": "integer",
                    "description": "文本最多返回字符数，默认 60000，最大 200000。",
                },
                "includeImage": {
                    "type": "boolean",
                    "description": "读取图片时是否返回 image 内容块供模型视觉理解，默认 true。",
                },
            },
            "required": ["file"],
        },
    )
    async def read_project_file(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="read_project_file",
            label="ai-video 项目文件读取",
        )

    _media_command_schema = {
        "type": "object",
        "properties": {
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "传给 ffmpeg/ffprobe 的参数列表，不包含可执行文件名。路径应使用当前项目目录内的相对路径。",
            },
            "timeoutSeconds": {
                "type": "integer",
                "description": "可选超时秒数。ffprobe 默认 60 秒，ffmpeg 默认 300 秒。",
            },
            "rationale": {
                "type": "string",
                "description": "面向用户解释为什么需要执行这个媒体命令。",
            },
        },
        "required": ["args"],
    }

    @tool(
        "run_ffprobe",
        "在当前 ai-video 项目目录内运行 ffprobe。Agent 可以自由组合 ffprobe 参数，但不能访问项目目录外路径。",
        _media_command_schema,
    )
    async def run_ffprobe(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="run_ffprobe",
            label="ai-video ffprobe 执行",
        )

    @tool(
        "run_ffmpeg",
        "在当前 ai-video 项目目录内运行 ffmpeg。Agent 可以自由组合 ffmpeg 参数处理视频、音频和图片，但不能访问项目目录外路径。",
        _media_command_schema,
    )
    async def run_ffmpeg(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args,
            tool_name="run_ffmpeg",
            label="ai-video ffmpeg 执行",
        )

    @tool(
        "publish_task_report",
        "仅在本轮提交工具返回 committed 和 receiptId 后，发布简短完成报告。后端会核验回执与当前项目、分集、会话和执行轮次；本工具不会再次写入业务数据。",
        {"type": "object", "properties": {
            "receiptId": {"type": "string", "description": "本轮正式提交结果返回的 receiptId。"},
            "summary": {"type": "string", "description": "可选的一句简短结果说明，最多 180 字；不要复述 Skill、规则或工具细节。"},
        }, "required": ["receiptId"], "additionalProperties": False},
    )
    async def publish_task_report(args: dict[str, Any]) -> dict[str, Any]:
        return await _request_backend_tool(
            args, tool_name="publish_task_report", label="ai-video 完成报告",
        )

    tool_entries = [
        ("get_project_snapshot", get_project_snapshot),
        ("get_conversation_history", get_conversation_history),
        ("list_workflow_node_versions", list_workflow_node_versions),
        ("read_workflow_node_version", read_workflow_node_version),
        ("start_business_task", start_business_task),
        ("read_source_window", read_source_window),
        ("search_source_text", search_source_text),
        ("get_source_coverage", get_source_coverage),
        ("get_episode_boundary_context", get_episode_boundary_context),
        ("update_project_settings", update_project_settings),
        ("submit_episode_boundary_candidate", submit_episode_boundary_candidate),
        ("get_asset_range_context", get_asset_range_context),
        ("submit_asset_range_candidate", submit_asset_range_candidate),
        ("get_asset_extraction_context", get_asset_extraction_context),
        ("get_asset_extraction_asset_catalog", get_asset_extraction_asset_catalog),
        ("submit_asset_extraction_result", submit_asset_extraction_result),
        ("get_plot_split_context", get_plot_split_context),
        ("submit_plot_split_candidate", submit_plot_split_candidate),
        ("get_cinematic_script_context", get_cinematic_script_context),
        ("submit_cinematic_script_result", submit_cinematic_script_result),
        ("get_director_plan_context", get_director_plan_context),
        ("validate_director_plan_draft", validate_director_plan_draft),
        ("submit_director_plan_result", submit_director_plan_result),
        ("get_video_prompt_context", get_video_prompt_context),
        ("submit_video_prompt_result", submit_video_prompt_result),
        ("get_video_prompt_optimization_context", get_video_prompt_optimization_context),
        ("submit_video_prompt_optimization_result", submit_video_prompt_optimization_result),
        ("get_video_prompt_standalone_context", get_video_prompt_standalone_context),
        ("submit_video_prompt_standalone_result", submit_video_prompt_standalone_result),
        ("list_agent_actions", list_agent_actions),
        ("request_agent_action", request_agent_action),
        ("request_overview_analysis", request_overview_analysis),
        ("request_open_current_episode", request_open_current_episode),
        ("save_story_world_map", save_story_world_map),
        ("upsert_asset", upsert_asset),
        ("delete_asset", delete_asset),
        ("delete_all_project_assets", delete_all_project_assets),
        ("save_episode_work_chain_plan", save_episode_work_chain_plan),
        ("patch_shot_prompt", patch_shot_prompt),
        ("upsert_workflow_node", upsert_workflow_node),
        ("delete_workflow_node", delete_workflow_node),
        ("delete_project_planning_outputs", delete_project_planning_outputs),
        ("save_workflow_node_inline_edit", save_workflow_node_inline_edit),
        ("create_workflow_task_card", create_workflow_task_card),
        ("add_workflow_asset_nodes", add_workflow_asset_nodes),
        ("update_workflow_route", update_workflow_route),
        ("link_workflow_input", link_workflow_input),
        ("unlink_workflow_input", unlink_workflow_input),
        ("list_workflow_inputs", list_workflow_inputs),
        ("resolve_generation_config", resolve_generation_config),
        ("validate_project_quality", validate_project_quality),
        ("request_storyboard_image_generation", request_storyboard_image_generation),
        ("request_visual_handoff_image_generation", request_visual_handoff_image_generation),
        ("edit_storyboard_image", edit_storyboard_image),
        ("request_storyboard_video_generation", request_storyboard_video_generation),
        ("request_route_video_generation", request_route_video_generation),
        ("request_asset_image_generation", request_asset_image_generation),
        ("list_generation_tasks", list_generation_tasks),
        ("cancel_generation_task", cancel_generation_task),
        ("request_project_export", request_project_export),
        ("list_director_rules", list_director_rules),
        ("search_director_rules", search_director_rules),
        ("read_director_rule", read_director_rule),
        ("list_project_files", list_project_files),
        ("search_project_files", search_project_files),
        ("read_project_file", read_project_file),
        ("run_ffprobe", run_ffprobe),
        ("run_ffmpeg", run_ffmpeg),
        ("publish_task_report", publish_task_report),
    ]
    visible_tools = [handler for name, handler in tool_entries if _tool_visible(name)]

    return create_sdk_mcp_server(
        name="ai_video",
        version="1.0.0",
        tools=visible_tools,
    )


def _object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    return {
        name: getattr(value, name)
        for name in dir(value)
        if not name.startswith("_") and not callable(getattr(value, name, None))
    }


def _extract_sdk_session_id(message: Any, message_dict: dict[str, Any] | None = None) -> str:
    data = message_dict or (message if isinstance(message, dict) else {})
    if isinstance(data, dict):
        sdk_id = data.get("session_id") or data.get("sessionId")
        if sdk_id:
            return str(sdk_id)
    sdk_id = getattr(message, "session_id", None) or getattr(message, "sessionId", None)
    return str(sdk_id or "")


def _block_text(block: Any) -> str:
    if TextBlock is not None and isinstance(block, TextBlock):
        return str(block.text or "")
    if isinstance(block, dict) and str(block.get("type") or "") == "text":
        return str(block.get("text") or "")
    if dataclasses.is_dataclass(block):
        data = dataclasses.asdict(block)
        if "text" in data:
            return str(data.get("text") or "")
    return ""


def _tool_use_from_block(block: Any) -> dict[str, Any] | None:
    if ToolUseBlock is not None and isinstance(block, ToolUseBlock):
        return {"id": block.id, "name": block.name, "input": block.input}
    if isinstance(block, dict) and str(block.get("type") or "") == "tool_use":
        return {
            "id": block.get("id"),
            "name": block.get("name"),
            "input": block.get("input") or {},
        }
    if dataclasses.is_dataclass(block):
        data = dataclasses.asdict(block)
        if data.get("name") and "input" in data:
            return {"id": data.get("id"), "name": data.get("name"), "input": data.get("input") or {}}
    return None


def _tool_result_from_block(block: Any) -> dict[str, Any] | None:
    if ToolResultBlock is not None and isinstance(block, ToolResultBlock):
        return {"toolUseId": block.tool_use_id, "content": block.content, "isError": block.is_error}
    if isinstance(block, dict) and str(block.get("type") or "") == "tool_result":
        return {
            "toolUseId": block.get("tool_use_id"),
            "content": block.get("content"),
            "isError": bool(block.get("is_error")),
        }
    return None


def _compact_event_text(value: Any, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if len(text) <= limit else f"{text[: max(0, limit - 3)]}..."


def _tool_result_outcome(content: Any) -> str:
    """Classify revisable business feedback separately from a broken tool call."""
    def parse_json_text(value: str) -> Any:
        start = value.find("{")
        if start < 0:
            return None
        try:
            return json.JSONDecoder().raw_decode(value[start:])[0]
        except ValueError:
            return None

    fragments = content if isinstance(content, list) else [content]
    for fragment in fragments:
        if not isinstance(fragment, (dict, str)):
            fragment = fragment.model_dump() if callable(getattr(fragment, "model_dump", None)) else {
                "text": getattr(fragment, "text", None),
            }
        if isinstance(fragment, dict):
            structured = fragment.get("structuredContent")
            if isinstance(structured, dict):
                payload = structured
            elif fragment.get("success") is False:
                payload = fragment
            else:
                text = fragment.get("text")
                payload = parse_json_text(text) if isinstance(text, str) else None
        elif isinstance(fragment, str):
            payload = parse_json_text(fragment)
        else:
            payload = None
        if not isinstance(payload, dict) or payload.get("success") is not False:
            continue
        errors = payload.get("errors")
        if (payload.get("status") in {"validation_failed", "rejected"}
                and isinstance(errors, list) and errors
                and all(isinstance(error, dict) and error.get("repairAction") in
                        {"revise_and_resubmit", "reread_context"} for error in errors)):
            return "revision_required"
    return ""


def _stream_blocks_from_message(message: Any) -> list[dict[str, Any]]:
    is_assistant = bool(
        (AssistantMessage is not None and isinstance(message, AssistantMessage))
        or (isinstance(message, dict) and str(message.get("type") or "") == "assistant")
        or str(getattr(message, "type", "") or "") == "assistant"
    )
    if AssistantMessage is not None and isinstance(message, AssistantMessage):
        content = message.content
    elif isinstance(message, dict):
        content = message.get("content") or (message.get("message") or {}).get("content") or []
    else:
        content = getattr(message, "content", [])

    if isinstance(content, str):
        text = _compact_event_text(content)
        return [{"type": "text", "text": text}] if is_assistant and text else []
    if not isinstance(content, list):
        return []

    blocks: list[dict[str, Any]] = []
    for block in content:
        text = _block_text(block).strip()
        if text and is_assistant:
            blocks.append({"type": "text", "text": _compact_event_text(text)})
            continue
        tool_use = _tool_use_from_block(block)
        if tool_use:
            blocks.append(
                {
                    "type": "tool_use",
                    "id": str(tool_use.get("id") or ""),
                    "name": str(tool_use.get("name") or "Tool"),
                    "input": tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {},
                }
            )
            continue
        tool_result = _tool_result_from_block(block)
        if tool_result:
            outcome = _tool_result_outcome(tool_result.get("content"))
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": str(tool_result.get("toolUseId") or tool_result.get("tool_use_id") or ""),
                    "content": _compact_event_text(tool_result.get("content")),
                    "is_error": bool(tool_result.get("isError") or tool_result.get("is_error")),
                    **({"outcome": outcome} if outcome else {}),
                }
            )
    return blocks


def _collect_message(
    message: Any,
    *,
    text_parts: list[str],
    tool_uses: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
) -> tuple[list[str], bool]:
    is_assistant = bool(
        (AssistantMessage is not None and isinstance(message, AssistantMessage))
        or (isinstance(message, dict) and str(message.get("type") or "") == "assistant")
    )
    if AssistantMessage is not None and isinstance(message, AssistantMessage):
        content = message.content
    elif isinstance(message, dict):
        content = message.get("content") or (message.get("message") or {}).get("content") or []
    else:
        content = getattr(message, "content", [])

    if isinstance(content, str):
        if content.strip():
            text_parts.append(content.strip())
        return ([content.strip()] if is_assistant and content.strip() else [], False)
    if not isinstance(content, list):
        return [], False
    assistant_parts: list[str] = []
    used_tool = False
    for block in content:
        text = _block_text(block).strip()
        if text:
            text_parts.append(text)
            if is_assistant:
                assistant_parts.append(text)
            continue
        tool_use = _tool_use_from_block(block)
        if tool_use:
            tool_uses.append(tool_use)
            used_tool = True
            continue
        tool_result = _tool_result_from_block(block)
        if tool_result:
            tool_results.append(tool_result)
    return assistant_parts, used_tool


async def _run_sdk_turn_async(
    *,
    prompt: str,
    system_prompt: str,
    cwd: Path,
    env: dict[str, str],
    model: str,
    snapshot_provider: SnapshotProvider,
    action_request_handler: ActionRequestHandler,
    tool_request_handler: ToolRequestHandler | None = None,
    stream_event_handler: StreamEventHandler | None = None,
    resume_id: str | None = None,
    allowed_tools: list[str] | tuple[str, ...] | None = None,
    max_turns: int | None = None,
    cancel_event: Any | None = None,
    handoff_event: Any | None = None,
    timeout_seconds: float | int | None = None,
    include_partial_messages: bool = True,
    on_request_prepared: RequestPreparedHandler | None = None,
    on_api_exchange: Callable[[dict[str, Any]], Any] | None = None,
    reasoning_task: str = "",
    reasoning_mode: str | None = None,
    sdk_skills: list[str] | None = None,
    image_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if _cancel_requested(cancel_event):
        return {"success": False, "cancelled": True, "error": "智能体执行已停止", "events": []}
    if not SDK_AVAILABLE or ClaudeAgentOptions is None or ClaudeSDKClient is None:
        return {"success": False, "error": unavailable_reason(), "events": []}
    try:
        cli_info = _agent_cli_info()
    except Exception as exc:
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        return {"success": False, "error": "智能体运行时缺失或版本不匹配，请修复插件运行环境", "events": [],
                "diagnostics": {"failureKind": "sdk_runtime", "python": sys.executable, "detail": str(exc)}}

    requested_action: dict[str, Any] = {}
    parent_request_id = uuid.uuid4().hex
    capture = None
    sdk_allowed_tools = _normalized_allowed_tools(allowed_tools)
    # A bare Skill permission would allow every installed project Skill.
    sdk_permission_tools = [
        *sdk_allowed_tools,
        *(f"Skill({name})" for name in sdk_skills or []),
    ]
    query_session_id = str(resume_id or "").strip() or f"ai-video-{uuid.uuid4().hex}"
    started_at = time.monotonic()
    first_event_ms: int | None = None
    timeout_value = float(timeout_seconds or 0)
    execution_stage = "connect"
    stderr_tail: deque[str] = deque(maxlen=12)
    assistant_errors: list[str] = []
    failure_details: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    reasoning_override = {"mode_override": reasoning_mode} if reasoning_mode else {}
    reasoning_options = model_sdk_reasoning_options(
        env.get("ANTHROPIC_BASE_URL", ""), model, reasoning_task, **reasoning_override,
    )
    reasoning_policy_value = reasoning_policy(
        env.get("ANTHROPIC_BASE_URL", ""), model, reasoning_task, **reasoning_override,
    )
    reasoning_body: dict[str, Any] = {}
    apply_model_reasoning(
        reasoning_body, base_url=env.get("ANTHROPIC_BASE_URL", ""), model=model,
        endpoint="anthropic-messages", task=reasoning_task, **reasoning_override,
    )
    # Claude omits disabled thinking on third-party routes. Use its supported
    # body override so the provider cannot silently enable its own default.
    env = {**_sdk_business_environment(env), "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1",
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    if reasoning_body:
        # Only override effort for graded protocols. On/off-only models must
        # not receive a fabricated task-level effort from this fallback.
        if reasoning_options.get("effort"):
            reasoning_body.setdefault("output_config", {}).setdefault(
                "effort", reasoning_options["effort"],
            )
        if reasoning_policy_value and reasoning_policy_value.request_token_budget:
            # Total completion cap, not a guarantee of answer space on
            # effort-only upstreams. The SDK thinking ceiling is separate.
            reasoning_body["max_tokens"] = reasoning_policy_value.request_token_budget
        env["CLAUDE_CODE_EXTRA_BODY"] = json.dumps(reasoning_body)

    def safe_diagnostic(value: Any) -> str:
        text = str(value or "")
        for key, secret in env.items():
            if secret and any(part in key.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
                text = text.replace(str(secret), "<redacted>")
        text = re.sub(r"(?i)(bearer\s+)[^\s,\"']+", r"\1<redacted>", text)
        text = re.sub(r"(?i)((?:api[_-]?key|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s,}\"']+", r"\1<redacted>", text)
        return text[:1200]

    def capture_stderr(line: str) -> None:
        stderr_tail.append(safe_diagnostic(line))

    def _remaining_timeout() -> float | None:
        if timeout_value <= 0:
            return None
        return max(0.1, timeout_value - (time.monotonic() - started_at))

    def _timeout_result() -> dict[str, Any]:
        failure_details["failureKind"] = "local_timeout"
        return {
            "success": False,
            "error": f"智能体执行超时（{int(timeout_value)} 秒）",
            "sdkSessionId": sdk_session_id or query_session_id,
            "diagnostics": diagnostics,
            "events": {
                "toolUses": tool_uses,
                "toolResults": tool_results,
                "result": result_message,
            },
        }

    def _capture_action(action: str, rationale: str) -> dict[str, Any]:
        result = action_request_handler(action, rationale)
        requested_action.update(result)
        return result

    def _diagnostics() -> dict[str, Any]:
        return {
            "sdkContextVersion": SDK_CONTEXT_VERSION,
            "apiExchanges": capture.records if capture is not None else [],
            "apiCaptureEnabled": capture is not None,
            "allowedToolCount": len(sdk_allowed_tools),
            "allowedTools": sdk_allowed_tools,
            "builtinTools": [],
            "querySessionId": query_session_id,
            "resumeId": resume_id or "",
            "promptChars": len(prompt or ""),
            "systemPromptChars": len(system_prompt or ""),
            "totalMs": int((time.monotonic() - started_at) * 1000),
            "firstEventMs": first_event_ms,
            "toolUseCount": len(tool_uses),
            "toolResultCount": len(tool_results),
            "toolInputChars": sum(_json_chars(item.get("input")) for item in tool_uses if isinstance(item, dict)),
            "toolResultChars": sum(_json_chars(item.get("content")) for item in tool_results if isinstance(item, dict)),
            "replyChars": sum(len(part) for part in text_parts),
            "includePartialMessages": bool(include_partial_messages),
            "resultSubtype": str(result_message.get("subtype") or ""),
            "executionStage": execution_stage,
            "cli": cli_info,
            "timeoutSeconds": timeout_value,
            "stderrTail": list(stderr_tail),
            "assistantErrors": list(assistant_errors),
            **({"reasoningTask": reasoning_task,
                "requestedReasoning": reasoning_mode or task_reasoning_mode(reasoning_task),
                "effectiveReasoning": reasoning_policy_value.effective_mode,
                "wireEffort": reasoning_policy_value.wire_effort,
                "budgetMode": reasoning_policy_value.budget_mode,
                "budgetMultiplier": reasoning_policy_value.budget_multiplier,
                "requestTokenBudget": reasoning_policy_value.request_token_budget,
                "thinkingTokenBudget": reasoning_policy_value.thinking_token_budget,
                "reasoningOptions": reasoning_options,
                "reasoningRequestBody": reasoning_body} if reasoning_options and reasoning_policy_value else {}),
            **failure_details,
        }

    mcp_server = build_ai_video_mcp_server(
        snapshot_provider=snapshot_provider,
        action_request_handler=_capture_action,
        tool_request_handler=tool_request_handler,
        allowed_tool_names=sdk_allowed_tools,
    )
    options_kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "cli_path": cli_info["path"],
        # Only our scoped MCP tools are exposed; allowed_tools is a permission
        # list, not a way to remove Claude Code's built-in tools (e.g. TodoWrite).
        "tools": ["Skill"] if sdk_skills else [],
        "allowed_tools": sdk_permission_tools,
        "max_buffer_size": max(
            8 * 1024 * 1024,
            sum(len(str(block.get("source", {}).get("data") or "")) for block in image_blocks or []) + 1024 * 1024,
        ),
        "system_prompt": system_prompt,
        "setting_sources": ["project"] if sdk_skills else [],
        "skills": list(sdk_skills or []),
        "strict_mcp_config": True,
        "include_partial_messages": bool(include_partial_messages),
        "resume": resume_id,
        "mcp_servers": {"ai_video": mcp_server},
        "env": env,
        "model": model or None,
        "stderr": capture_stderr,
        **reasoning_options,
    }
    if max_turns is not None:
        options_kwargs["max_turns"] = max_turns
    # Configuration inspection stays read-only. Create directories only when
    # this turn really starts, after lab runners have substituted their cwd/env.
    cwd.mkdir(parents=True, exist_ok=True)
    if env.get("CLAUDE_CONFIG_DIR"):
        Path(env["CLAUDE_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
    prepared_request = {
        "transport": "claude_agent_sdk",
        "method": "ClaudeSDKClient.query",
        "captureLevel": "application_submission",
        "captureSource": "ai_video",
        "requestPurpose": reasoning_task or "sdk_generation",
        "requestId": parent_request_id,
        "querySessionId": query_session_id,
        "prompt": prompt or "",
        "imageCount": len(image_blocks or []),
        "options": _sdk_request_log_options(options_kwargs),
        "reasoningRequestBody": reasoning_body,
    }
    try:
        if on_request_prepared:
            on_request_prepared(prepared_request)
        elif on_api_exchange:
            on_api_exchange({"applicationOnly": True, "requestInfo": prepared_request})
    except Exception as exc:  # logging must not silently abort the business operation
        if getattr(exc, "allow_request_prepared_abort", False):
            raise
        print(traceback.format_exc(), file=sys.stderr, flush=True)
    options = ClaudeAgentOptions(**options_kwargs)

    text_parts: list[str] = []
    final_assistant_parts: list[str] = []
    tool_uses: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    result_message: dict[str, Any] = {}
    sdk_session_id = ""
    client = ClaudeSDKClient(options=options)
    try:
        if on_api_exchange:
            from utils.sdk_request_capture import SdkHttpCapture

            capture = SdkHttpCapture(
                env.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com",
                on_exchange=on_api_exchange,
                request_purpose=reasoning_task or "sdk_generation",
                parent_request_id=parent_request_id,
                timeout=timeout_value if timeout_value > 0 else 300,
                upstream_environment=env,
            )
            capture.__enter__()
            # Compute reasoning against the real provider above, and route only
            # the SDK transport through a transparent per-turn loopback capture.
            no_proxy = env.get("no_proxy", env.get("NO_PROXY", os.environ.get("no_proxy", os.environ.get("NO_PROXY", ""))))
            loopback_bypass = ",".join(part for part in (no_proxy, "127.0.0.1", "localhost") if part)
            options.env = {**env, "ANTHROPIC_BASE_URL": capture.base_url,
                           "NO_PROXY": loopback_bypass, "no_proxy": loopback_bypass}
        remaining = _remaining_timeout()
        try:
            if remaining is None:
                await client.connect()
            else:
                await asyncio.wait_for(client.connect(), timeout=remaining)
        except asyncio.TimeoutError:
            return _timeout_result()
        if _cancel_requested(cancel_event):
            failure_details["failureKind"] = "cancelled"
            return {"success": False, "cancelled": True, "error": "智能体执行已停止", "events": [],
                    "diagnostics": diagnostics}
        execution_stage = "query"
        try:
            remaining = _remaining_timeout()
            query_input: Any = prompt
            if image_blocks:
                async def multimodal_message():
                    yield {
                        "type": "user",
                        "message": {"role": "user", "content": [
                            {"type": "text", "text": prompt},
                            *image_blocks,
                        ]},
                        "parent_tool_use_id": None,
                    }
                query_input = multimodal_message()
            if remaining is not None:
                await asyncio.wait_for(client.query(query_input, session_id=query_session_id), timeout=remaining)
            else:
                await client.query(query_input, session_id=query_session_id)
        except asyncio.TimeoutError:
            with contextlib.suppress(Exception):
                await client.interrupt()
            return _timeout_result()
        response_iter = client.receive_response().__aiter__()
        execution_stage = "receive"
        message_task = asyncio.create_task(response_iter.__anext__())
        try:
            while True:
                if _cancel_requested(handoff_event):
                    # A validated candidate is already durable. Its next turn belongs
                    # to the user, so there is no model completion to wait for.
                    with contextlib.suppress(Exception):
                        await client.interrupt()
                    return {
                        "success": True,
                        "handoff": True,
                        "sdkSessionId": sdk_session_id or query_session_id,
                        "diagnostics": diagnostics,
                        "events": {
                            "toolUses": tool_uses,
                            "toolResults": tool_results,
                            "result": result_message,
                        },
                    }
                if timeout_value > 0 and (time.monotonic() - started_at) >= timeout_value:
                    with contextlib.suppress(Exception):
                        await client.interrupt()
                    return _timeout_result()
                if _cancel_requested(cancel_event):
                    failure_details["failureKind"] = "cancelled"
                    with contextlib.suppress(Exception):
                        await client.interrupt()
                    return {
                        "success": False,
                        "cancelled": True,
                        "error": "智能体执行已停止",
                        "sdkSessionId": sdk_session_id or query_session_id,
                        "diagnostics": diagnostics,
                        "events": {
                            "toolUses": tool_uses,
                            "toolResults": tool_results,
                            "result": result_message,
                        },
                    }
                done, _pending = await asyncio.wait({message_task}, timeout=0.25)
                if message_task not in done:
                    continue
                try:
                    message = message_task.result()
                except StopAsyncIteration:
                    break
                if first_event_ms is None:
                    first_event_ms = int((time.monotonic() - started_at) * 1000)
                message_dict = _object_to_dict(message) if dataclasses.is_dataclass(message) else (message if isinstance(message, dict) else {})
                if message_dict.get("error") and len(assistant_errors) < 8:
                    assistant_errors.append(safe_diagnostic(message_dict["error"]))
                sdk_session_id = sdk_session_id or _extract_sdk_session_id(message, message_dict)
                assistant_parts, used_tool = _collect_message(
                    message,
                    text_parts=text_parts,
                    tool_uses=tool_uses,
                    tool_results=tool_results,
                )
                if used_tool:
                    final_assistant_parts.clear()
                elif assistant_parts:
                    final_assistant_parts.extend(assistant_parts)
                if stream_event_handler:
                    stream_blocks = _stream_blocks_from_message(message)
                    if stream_blocks:
                        with contextlib.suppress(Exception):
                            stream_event_handler(
                                {
                                    "type": "message",
                                    "sdkSessionId": sdk_session_id or query_session_id,
                                    "messageType": str(message_dict.get("type") or ""),
                                    "blocks": stream_blocks,
                                }
                            )
                if ResultMessage is not None and isinstance(message, ResultMessage):
                    result_message = message_dict
                    break
                elif isinstance(message, dict) and str(message.get("type") or "") == "result":
                    result_message = message
                    break
                message_task = asyncio.create_task(response_iter.__anext__())
        finally:
            if not message_task.done():
                message_task.cancel()
                with contextlib.suppress(BaseException):
                    await message_task
    except Exception as exc:
        failure_details.update({"failureKind": "sdk_exception", "exceptionType": type(exc).__name__,
                                "exceptionMessage": safe_diagnostic(exc)})
        if getattr(exc, "exit_code", None) is not None:
            failure_details["exitCode"] = exc.exit_code
        exc.sdk_diagnostics = diagnostics
        raise
    finally:
        try:
            await _disconnect_sdk_client(client)
        finally:
            if capture is not None:
                await asyncio.to_thread(capture.__exit__, None, None, None)
            # Early returns and exceptions retain this dict. Populate it only
            # after shutdown has archived the final in-flight exchanges.
            diagnostics.update(_diagnostics())

    reply = str(result_message.get("result") or "").strip()
    if not reply:
        reply = "\n\n".join(final_assistant_parts).strip()
    failed = not result_message or bool(result_message.get("is_error")) or str(result_message.get("subtype") or "").startswith("error_")
    errors = result_message.get("errors") or []
    error = ("；".join(str(item) for item in errors) if isinstance(errors, list) else str(errors)) if failed else ""
    if failed and not error:
        subtype = str(result_message.get("subtype") or "")
        error = str(result_message.get("result") or (
            "智能体达到执行轮数上限，尚未完成输出" if subtype == "error_max_turns"
            else f"智能体会话未正常完成（{subtype}）" if subtype
            else "智能体会话未正常完成，请检查供应商响应后重试"
        ))
    if failed:
        failure_details.update({
            "failureKind": "sdk_result_error" if result_message else "missing_terminal_result",
            "resultErrors": [safe_diagnostic(item) for item in errors[:8]] if isinstance(errors, list) else [safe_diagnostic(errors)],
            "terminalReason": safe_diagnostic(result_message.get("terminal_reason")),
            "apiErrorStatus": result_message.get("api_error_status"),
        })
        if result_message.get("subtype") == "error_during_execution":
            error = "智能体请求执行失败，请查看诊断记录后重试"
    diagnostics.update(failure_details)
    return {
        "success": not failed,
        **({"error": error} if failed else {}),
        "reply": reply,
        "sdkSessionId": sdk_session_id or _extract_sdk_session_id(result_message, result_message) or query_session_id,
        "requestedAction": requested_action,
        "diagnostics": diagnostics,
        "events": {
            "toolUses": tool_uses,
            "toolResults": tool_results,
            "result": result_message,
        },
    }


def run_sdk_turn(
    *,
    prompt: str,
    system_prompt: str,
    cwd: Path,
    env: dict[str, str],
    model: str,
    snapshot_provider: SnapshotProvider,
    action_request_handler: ActionRequestHandler,
    tool_request_handler: ToolRequestHandler | None = None,
    stream_event_handler: StreamEventHandler | None = None,
    resume_id: str | None = None,
    allowed_tools: list[str] | tuple[str, ...] | None = None,
    max_turns: int | None = None,
    cancel_event: Any | None = None,
    handoff_event: Any | None = None,
    timeout_seconds: float | int | None = None,
    include_partial_messages: bool = True,
    on_request_prepared: RequestPreparedHandler | None = None,
    on_api_exchange: Callable[[dict[str, Any]], Any] | None = None,
    reasoning_task: str = "",
    reasoning_mode: str | None = None,
    sdk_skills: list[str] | None = None,
    image_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if _cancel_requested(cancel_event):
        return {"success": False, "cancelled": True, "error": "智能体执行已停止", "events": []}
    try:
        return asyncio.run(
            _run_sdk_turn_async(
                prompt=prompt,
                system_prompt=system_prompt,
                cwd=cwd,
                env=env,
                model=model,
                snapshot_provider=snapshot_provider,
                action_request_handler=action_request_handler,
                tool_request_handler=tool_request_handler,
                stream_event_handler=stream_event_handler,
                resume_id=resume_id,
                allowed_tools=allowed_tools,
                max_turns=max_turns,
                cancel_event=cancel_event,
                handoff_event=handoff_event,
                timeout_seconds=timeout_seconds,
                include_partial_messages=include_partial_messages,
                on_request_prepared=on_request_prepared,
                on_api_exchange=on_api_exchange,
                reasoning_task=reasoning_task,
                reasoning_mode=reasoning_mode,
                sdk_skills=sdk_skills,
                image_blocks=image_blocks,
            )
        )
    except RuntimeError as exc:
        if "asyncio.run() cannot be called from a running event loop" not in str(exc):
            raise
        result: dict[str, Any] = {}
        error: list[BaseException] = []

        def _runner() -> None:
            try:
                result.update(
                    asyncio.run(
                        _run_sdk_turn_async(
                            prompt=prompt,
                            system_prompt=system_prompt,
                            cwd=cwd,
                            env=env,
                            model=model,
                            snapshot_provider=snapshot_provider,
                            action_request_handler=action_request_handler,
                            tool_request_handler=tool_request_handler,
                            stream_event_handler=stream_event_handler,
                            resume_id=resume_id,
                            allowed_tools=allowed_tools,
                            max_turns=max_turns,
                            cancel_event=cancel_event,
                            handoff_event=handoff_event,
                            timeout_seconds=timeout_seconds,
                            include_partial_messages=include_partial_messages,
                            on_request_prepared=on_request_prepared,
                            on_api_exchange=on_api_exchange,
                            reasoning_task=reasoning_task,
                            reasoning_mode=reasoning_mode,
                            sdk_skills=sdk_skills,
                            image_blocks=image_blocks,
                        )
                    )
                )
            except BaseException as thread_exc:  # noqa: BLE001
                error.append(thread_exc)

        import threading

        from contextvars import copy_context
        execution_context = copy_context()
        thread = threading.Thread(target=lambda: execution_context.run(_runner), name="ai-video-sdk-turn", daemon=True)
        thread.start()
        thread.join()
        if error:
            raise error[0]
        return result
