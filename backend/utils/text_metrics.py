# -*- coding: utf-8 -*-
"""Shared text counting helpers."""

from __future__ import annotations

import re


_CONTENT_WHITESPACE_RE = re.compile(r"\s+", re.UNICODE)


def content_char_count(text: object) -> int:
    """Count visible content chars while ignoring whitespace separators."""
    return len(_CONTENT_WHITESPACE_RE.sub("", str("" if text is None else text)))


def content_offset_after_units(text: str, start: int, units: int) -> int:
    """Return the raw string offset reached after reading N content chars."""
    value = str("" if text is None else text)
    total = len(value)
    cursor = max(0, min(total, int(start or 0)))
    target_units = max(0, int(units or 0))
    if target_units <= 0 or cursor >= total:
        return cursor
    seen = 0
    for index in range(cursor, total):
        if value[index].isspace():
            continue
        seen += 1
        if seen >= target_units:
            return index + 1
    return total


def content_units_between(text: str, start: int, end: int) -> int:
    """Count visible content chars inside a raw string offset range."""
    value = str("" if text is None else text)
    total = len(value)
    safe_start = max(0, min(total, int(start or 0)))
    safe_end = max(safe_start, min(total, int(end or 0)))
    return content_char_count(value[safe_start:safe_end])
