# -*- coding: utf-8 -*-
"""Lightweight performance logging for canvas task hot paths."""

from __future__ import annotations

import json
import os
import time
from typing import Any

_CANVAS_PERF_PREFIX = "[canvas-perf]"
_CANVAS_PERF_ENV = "XIAOWO_CANVAS_PERF_LOG"
_CANVAS_PERF_THRESHOLD_ENV = "XIAOWO_CANVAS_PERF_LOG_THRESHOLD_MS"
_DEFAULT_SLOW_LOG_THRESHOLD_MS = 100.0
_ERROR_STATUSES = {"error"}


def canvas_perf_start() -> float:
    return time.perf_counter()


def canvas_perf_elapsed_ms(started_at: float) -> float:
    try:
        return round((time.perf_counter() - float(started_at)) * 1000, 3)
    except Exception:
        return 0.0


def _canvas_perf_log_enabled(fields: dict[str, Any]) -> bool:
    mode = str(os.environ.get(_CANVAS_PERF_ENV) or "error").strip().lower()
    if mode in {"0", "false", "no", "off", "disabled"}:
        return False
    status = str(fields.get("status") or "").strip().lower()
    if status in _ERROR_STATUSES:
        return True
    if mode in {"1", "true", "yes", "on", "all", "debug"}:
        return True
    if mode in {"error", "errors"}:
        return False
    if mode not in {"slow", "threshold"}:
        return False
    try:
        threshold_ms = float(os.environ.get(_CANVAS_PERF_THRESHOLD_ENV) or _DEFAULT_SLOW_LOG_THRESHOLD_MS)
    except (TypeError, ValueError):
        threshold_ms = _DEFAULT_SLOW_LOG_THRESHOLD_MS
    try:
        return float(fields.get("durationMs") or 0.0) >= threshold_ms
    except (TypeError, ValueError):
        return False


def canvas_perf_log(stage: str, **fields: Any) -> None:
    try:
        if not _canvas_perf_log_enabled(fields):
            return
        payload = {"stage": str(stage or "").strip() or "unknown", **fields}
        print(f"{_CANVAS_PERF_PREFIX} {json.dumps(payload, ensure_ascii=False, default=str)}", flush=True)
    except Exception:
        return
