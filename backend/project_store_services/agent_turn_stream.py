# -*- coding: utf-8 -*-
"""Per-turn stream buffer, duplicate suppression and live-event throttling."""
from __future__ import annotations

import time
from typing import Any
from utils.agent_execution_state import current_execution_id

from .agent_sessions import (
    _agent_draft_turn_from_stream_blocks,
    _agent_live_activity_from_stream_blocks,
    _agent_stream_block_key,
    _normalize_agent_stream_block,
    _try_emit_agent_live_activity,
)


class AgentTurnStream:
    def __init__(self, project_id: str, episode_id: str | None, session_id: str | None):
        self.project_id = project_id
        self.episode_id = episode_id
        self.session_id = session_id
        self.execution_id = current_execution_id(session_id)
        self.blocks: list[dict[str, Any]] = []
        self._keys: set[str] = set()
        self._last_emit_at = 0.0

    def emit(self, *, force: bool = False) -> None:
        if not self.session_id:
            return
        now = time.monotonic()
        if not force and now - self._last_emit_at < 0.45:
            return
        self._last_emit_at = now
        draft_turn = _agent_draft_turn_from_stream_blocks(self.project_id, str(self.session_id), self.blocks)
        _try_emit_agent_live_activity(
            self.project_id,
            self.episode_id,
            str(self.session_id),
            _agent_live_activity_from_stream_blocks(self.blocks),
            draft_turn=draft_turn,
            expected_execution_id=self.execution_id,
        )

    def append(self, blocks: Any, *, force: bool = False) -> None:
        if not isinstance(blocks, list):
            return
        added = False
        for block in blocks:
            normalized = _normalize_agent_stream_block(block)
            if not normalized:
                continue
            key = _agent_stream_block_key(normalized)
            if key in self._keys:
                continue
            self._keys.add(key)
            self.blocks.append(normalized)
            added = True
        if not added:
            return
        if len(self.blocks) > 40:
            del self.blocks[:-40]
        self.emit(force=force)

    def handle_event(self, event: dict[str, Any]) -> None:
        self.append(event.get("blocks"), force=False)
