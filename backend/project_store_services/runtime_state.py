# -*- coding: utf-8 -*-
"""跨请求共享的锁、线程、取消标记和智能体取消异常。"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import random
import re
import shutil
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.agent_context import (
    AGENT_CONTEXT_MESSAGE_TEXT_LIMIT,
    AGENT_CONTEXT_RECENT_WINDOW,
    AGENT_CONTEXT_SUMMARY_CHARS,
    build_agent_conversation_context,
)
from utils import agent_sdk_runtime
from utils.agent_session_service import AgentSessionService
from utils.aspect_size import (
    IMAGE_TIER_SHORT_EDGE,
    VIDEO_TIER_SHORT_EDGE,
    aspect_size,
    parse_aspect_ratio,
    resolution_to_short_edge,
)
from utils.image_pipeline import (
    convert_image_bytes_to_png,
    data_url_from_bytes,
    prepare_provider_image_bytes,
    prepare_provider_image_data_uri,
    save_project_image,
    save_provider_output_image,
)
from utils.media_backends import (
    cancel_video_media_job,
    endpoint_supports_media_generation,
    infer_model_endpoint,
    media_endpoint_type,
    normalize_media_endpoint,
    generate_image_media,
    generate_video_media,
    poll_video_media_job,
    provider_supports_media_generation,
    submit_video_media_job,
)


_LOCK = threading.RLock()
_AGENT_EVENT_EMITTER: Any | None = None
_AGENT_SESSION_SERVICE: AgentSessionService | None = None
_AGENT_CANCEL_FLAGS: dict[str, threading.Event] = {}
_AGENT_THREADS: dict[str, threading.Thread] = {}
_AGENT_BACKEND_INSTANCE_ID = uuid.uuid4().hex
_ASSET_IMAGE_TASK_THREADS: dict[str, threading.Thread] = {}
_ASSET_IMAGE_TASK_CANCEL_FLAGS: dict[str, threading.Event] = {}
_VIDEO_TASK_THREADS: dict[str, threading.Thread] = {}
_VIDEO_TASK_CANCEL_FLAGS: dict[str, threading.Event] = {}
_VIDEO_TASK_POLL_SECONDS = 5.0
_VIDEO_TASK_RESTORE_MESSAGE = "插件已重启，正在恢复供应商视频任务状态。"
_VIDEO_GENERATION_TASK_TYPES = {"storyboard_video", "route_video"}
AGENT_STALE_RUNNING_GRACE_SECONDS = 30
AGENT_SESSION_MESSAGE_RETAIN_LIMIT = 120
AGENT_SESSION_HISTORY_SUMMARY_MESSAGE_LIMIT = 48


class AgentTurnCancelled(RuntimeError):
    pass


def _agent_thread_is_alive(key: str) -> bool:
    thread = _AGENT_THREADS.get(key)
    return bool(thread and thread.is_alive())


def _agent_cancel_requested(session_id: str | None) -> bool:
    from utils.agent_execution_state import current_execution_id
    identity = current_execution_id(session_id)
    if identity:
        flag = _AGENT_CANCEL_FLAGS.get(identity)
        return bool(flag and flag.is_set())
    if not session_id:
        return False
    cancel_flag = _AGENT_CANCEL_FLAGS.get(str(session_id))
    return bool(cancel_flag and cancel_flag.is_set())


def _raise_if_agent_cancelled(session_id: str | None) -> None:
    if _agent_cancel_requested(session_id):
        raise AgentTurnCancelled("智能体执行已停止")

__all__ = (
    '_LOCK', '_AGENT_EVENT_EMITTER', '_AGENT_SESSION_SERVICE', '_AGENT_CANCEL_FLAGS', '_AGENT_THREADS',
    '_ASSET_IMAGE_TASK_THREADS', '_ASSET_IMAGE_TASK_CANCEL_FLAGS', '_VIDEO_TASK_THREADS',
    '_VIDEO_TASK_CANCEL_FLAGS', '_VIDEO_TASK_POLL_SECONDS', '_VIDEO_TASK_RESTORE_MESSAGE',
    '_VIDEO_GENERATION_TASK_TYPES', 'AGENT_STALE_RUNNING_GRACE_SECONDS', 'AGENT_SESSION_MESSAGE_RETAIN_LIMIT',
    'AGENT_SESSION_HISTORY_SUMMARY_MESSAGE_LIMIT', 'AgentTurnCancelled', '_agent_cancel_requested',
    '_raise_if_agent_cancelled'
)
