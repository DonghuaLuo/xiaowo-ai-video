# -*- coding: utf-8 -*-
"""Keep actionable image-provider moderation details without guessing causes."""
from __future__ import annotations

import json
import re
from typing import Any


def image_provider_error_details(error: BaseException | str) -> dict[str, Any]:
    message = str(error or "")
    match = re.search(r"\{\s*\"error\"\s*:", message)
    payload: dict[str, Any] = {}
    if match:
        try:
            parsed, _end = json.JSONDecoder().raw_decode(message[match.start():])
            payload = parsed.get("error") if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict) else {}
        except (ValueError, TypeError):
            pass
    moderation = payload.get("moderation_details") if isinstance(payload.get("moderation_details"), dict) else {}
    stage = str(moderation.get("moderation_stage") or "unknown").strip()
    if stage not in {"input", "output", "unknown"}:
        stage = "unknown"
    categories = moderation.get("categories")
    request_id = str(payload.get("request_id") or "").strip()
    if not request_id:
        id_match = re.search(r"request ID ([0-9a-fA-F-]{32,36})", str(payload.get("message") or ""))
        request_id = id_match.group(1) if id_match else ""
    return {
        "code": str(payload.get("code") or "").strip(),
        "type": str(payload.get("type") or "").strip(),
        "moderationStage": stage,
        "categories": [str(item) for item in categories if isinstance(item, str)] if isinstance(categories, list) else [],
        "requestId": request_id,
    }
