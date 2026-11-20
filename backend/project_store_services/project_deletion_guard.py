"""Coordinate project deletion with canvas connections and new project access."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager


_CONDITION = threading.Condition(threading.RLock())
_DELETING: dict[str, int] = {}
_ACTIVE_CANVAS: dict[str, int] = {}


def assert_project_available(project_id: str) -> None:
    with _CONDITION:
        owner = _DELETING.get(project_id)
        if owner is not None and owner != threading.get_ident():
            raise FileNotFoundError("项目正在删除")


def is_project_deleting(project_id: str) -> bool:
    with _CONDITION:
        return project_id in _DELETING


@contextmanager
def canvas_project_access(project_id: str):
    with _CONDITION:
        assert_project_available(project_id)
        _ACTIVE_CANVAS[project_id] = _ACTIVE_CANVAS.get(project_id, 0) + 1
    try:
        yield
    finally:
        with _CONDITION:
            remaining = _ACTIVE_CANVAS[project_id] - 1
            if remaining:
                _ACTIVE_CANVAS[project_id] = remaining
            else:
                _ACTIVE_CANVAS.pop(project_id, None)
            _CONDITION.notify_all()


@contextmanager
def deleting_project(project_id: str):
    with _CONDITION:
        if project_id in _DELETING:
            raise RuntimeError("项目正在删除")
        _DELETING[project_id] = threading.get_ident()
    try:
        yield
    finally:
        with _CONDITION:
            _DELETING.pop(project_id, None)
            _CONDITION.notify_all()


def wait_for_canvas_idle(project_id: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    with _CONDITION:
        while _ACTIVE_CANVAS.get(project_id, 0):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _CONDITION.wait(remaining)
    return True
