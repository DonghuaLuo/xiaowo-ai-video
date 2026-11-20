# -*- coding: utf-8 -*-
"""原文边界匹配、标题规则、提议确认契约与通用模型输入。"""
from __future__ import annotations

from .catalogs import _normalize_style_phase_visual_context
from .project_resource_revisions import _json_hash
from .project_resource_revisions import _payload_first_int
from .project_resource_revisions import _payload_first_present
from .project_resource_revisions import _payload_first_text
from .project_resource_revisions import _resource_revision_value
from .source_text_store import _compact_text
from .store_core import _read_json
from typing import Any
from utils.text_metrics import content_offset_after_units
from utils.text_metrics import content_units_between
import copy
import re


def _next_episode_id(coverage: dict[str, Any]) -> str:
    ranges = [item for item in coverage.get("episodeRanges", []) if isinstance(item, dict)]
    last_id = str((coverage.get("episodeCursor") or {}).get("lastEpisodeId") or "").strip()
    if last_id:
        match = re.search(r"(\d+)$", last_id)
        if match:
            return f"E{int(match.group(1)) + 1:02d}"
    return f"E{len(ranges) + 1:02d}"


def _natural_boundary_candidates(content: str, start: int, lower: int, upper: int, target_end: int) -> list[dict[str, Any]]:
    total = len(content)
    lower = max(start + 1, min(total, lower))
    upper = max(lower, min(total, upper))
    candidates: dict[int, dict[str, Any]] = {}
    window = content[lower:upper]
    for match in re.finditer(r"\r?\n\s*\r?\n|\r?\n|[。！？!?；;]\s*", window):
        end = lower + int(match.end())
        if end <= start or end > total:
            continue
        marker = match.group(0)
        line_break_count = marker.count("\n")
        if line_break_count >= 2:
            reason = "自然段结束"
            bonus = 80
        elif line_break_count == 1:
            reason = "换行停顿"
            bonus = 45
        else:
            reason = "句意停顿"
            bonus = 30
        candidates[end] = {
            "endOffset": end,
            "actualUnits": content_units_between(content, start, end),
            "reason": reason,
            "score": abs(end - target_end) - bonus,
        }
    if upper > start:
        candidates.setdefault(
            upper,
            {
                "endOffset": upper,
                "actualUnits": content_units_between(content, start, upper),
                "reason": "目标范围内未找到更强自然断点，使用窗口上界",
                "score": abs(upper - target_end) + 120,
            },
        )
    if total > start and total <= upper:
        candidates[total] = {
            "endOffset": total,
            "actualUnits": content_units_between(content, start, total),
            "reason": "已到达源文件末尾",
            "score": 0,
        }
    return sorted(candidates.values(), key=lambda item: (item["score"], abs(int(item["endOffset"]) - target_end)))[:6]


def _locate_source_boundary_text_end(
    content: str,
    start: int,
    planning_end: int,
    boundary_text: str,
    *,
    min_boundary_end: int | None = None,
) -> int | None:
    result = _match_source_boundary_text_end(
        content,
        start,
        planning_end,
        boundary_text,
        min_boundary_end=min_boundary_end,
    )
    if result.get("status") == "unique":
        return int(result["endOffset"])
    return None


_BOUNDARY_NON_WORD_PATTERN = re.compile(r"[\W_]+", re.UNICODE)


BOUNDARY_TEXT_MIN_EFFECTIVE_CHARS = 20


BOUNDARY_TEXT_MAX_EFFECTIVE_CHARS = 60


ASSET_RANGE_BOUNDARY_TEXT_MIN_EFFECTIVE_CHARS = BOUNDARY_TEXT_MIN_EFFECTIVE_CHARS


ASSET_RANGE_BOUNDARY_TEXT_MAX_EFFECTIVE_CHARS = BOUNDARY_TEXT_MAX_EFFECTIVE_CHARS


def _strip_boundary_match_text(value: str) -> str:
    return _BOUNDARY_NON_WORD_PATTERN.sub("", str(value or ""))


def _boundary_text_effective_length(value: str) -> int:
    return len(_strip_boundary_match_text(value))


def _boundary_text_length_issue(value: str, *, available_text: str | None = None) -> str:
    effective_length = _boundary_text_effective_length(value)
    min_effective_chars = BOUNDARY_TEXT_MIN_EFFECTIVE_CHARS
    if available_text is not None:
        available_effective_length = _boundary_text_effective_length(available_text)
        if available_effective_length > 0:
            min_effective_chars = min(min_effective_chars, available_effective_length)
    if effective_length < min_effective_chars:
        if min_effective_chars < BOUNDARY_TEXT_MIN_EFFECTIVE_CHARS:
            return (
                f"断点尾句有效长度不足 {min_effective_chars} 字，"
                "请返回覆盖断点前可用正文、且可唯一定位的原文尾句。"
            )
        return (
            f"断点尾句有效长度不足 {BOUNDARY_TEXT_MIN_EFFECTIVE_CHARS} 字，"
            "请向前连带上一句或短句，重新返回 20-60 字且可唯一定位的原文尾句。"
        )
    if effective_length > BOUNDARY_TEXT_MAX_EFFECTIVE_CHARS:
        return (
            f"断点尾句有效长度超过 {BOUNDARY_TEXT_MAX_EFFECTIVE_CHARS} 字，"
            "请缩短为 20-60 字且可唯一定位的原文尾句。"
        )
    return ""


def _asset_range_boundary_text_length_issue(value: str, *, available_text: str | None = None) -> str:
    return _boundary_text_length_issue(value, available_text=available_text)


def _episode_boundary_text_length_issue(value: str, *, available_text: str | None = None) -> str:
    return _boundary_text_length_issue(value, available_text=available_text)


def _source_char_is_boundary_punctuation(char: str) -> bool:
    return bool(char and not char.isspace() and not _strip_boundary_match_text(char))


def _extend_source_boundary_end(content: str, end: int, planning_end: int) -> int:
    extended = max(0, min(len(content), end))
    planning_end = max(0, min(len(content), planning_end))
    while extended < planning_end and _source_char_is_boundary_punctuation(content[extended]):
        extended += 1
    # Consume EOF whitespace without changing interior boundaries or source offsets.
    if planning_end == len(content) and not content[extended:planning_end].strip():
        return planning_end
    return extended


def _dedupe_boundary_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[int, int]] = set()
    unique: list[dict[str, Any]] = []
    for item in matches:
        key = (int(item.get("startOffset") or 0), int(item.get("endOffset") or 0))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _boundary_match_result(
    status: str,
    *,
    match_mode: str,
    boundary_text: str,
    matches: list[dict[str, Any]] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    matches = _dedupe_boundary_matches(matches or [])
    result: dict[str, Any] = {
        "status": status,
        "matchMode": match_mode,
        "matchCount": len(matches),
        "matches": matches[:5],
        "boundaryText": boundary_text,
    }
    if len(matches) == 1:
        result["startOffset"] = matches[0]["startOffset"]
        result["endOffset"] = matches[0]["endOffset"]
    if reason:
        result["reason"] = reason
    return result


def _find_boundary_text_matches(
    content: str,
    start: int,
    planning_end: int,
    boundary_text: str,
    *,
    min_boundary_end: int,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    search_start = start
    while True:
        index = content.find(boundary_text, search_start, planning_end)
        if index < 0:
            break
        end = index + len(boundary_text)
        end = _extend_source_boundary_end(content, end, planning_end)
        if end >= min_boundary_end:
            matches.append({"startOffset": index, "endOffset": end})
        search_start = index + 1
    return _dedupe_boundary_matches(matches)


def _find_boundary_text_matches_ignoring_punctuation(
    content: str,
    start: int,
    planning_end: int,
    boundary_text: str,
    *,
    min_boundary_end: int,
) -> list[dict[str, Any]]:
    normalized_text = _strip_boundary_match_text(boundary_text)
    if not normalized_text:
        return []
    segment = content[start:planning_end]
    normalized_chars: list[str] = []
    original_start_offsets: list[int] = []
    original_end_offsets: list[int] = []
    for index, char in enumerate(segment):
        stripped = _strip_boundary_match_text(char)
        if not stripped:
            continue
        for stripped_char in stripped:
            normalized_chars.append(stripped_char)
            original_start_offsets.append(start + index)
            original_end_offsets.append(start + index + 1)
    normalized_segment = "".join(normalized_chars)
    if not normalized_segment:
        return []
    matches: list[dict[str, Any]] = []
    search_start = 0
    while True:
        normalized_index = normalized_segment.find(normalized_text, search_start)
        if normalized_index < 0:
            break
        end_index = normalized_index + len(normalized_text) - 1
        end = _extend_source_boundary_end(content, original_end_offsets[end_index], planning_end)
        if end >= min_boundary_end:
            matches.append(
                {
                    "startOffset": original_start_offsets[normalized_index],
                    "endOffset": end,
                }
            )
        search_start = normalized_index + 1
    return _dedupe_boundary_matches(matches)


def _match_source_boundary_text_end(
    content: str,
    start: int,
    planning_end: int,
    boundary_text: str,
    *,
    min_boundary_end: int | None = None,
) -> dict[str, Any]:
    text = str(boundary_text or "").strip()
    if not text:
        return _boundary_match_result(
            "no_match",
            match_mode="exact",
            boundary_text="",
            reason="模型返回的断点尾句为空，请重新返回正确尾句。",
        )
    if not _strip_boundary_match_text(text):
        return _boundary_match_result(
            "no_match",
            match_mode="exact",
            boundary_text=text,
            reason="模型返回的断点尾句缺少可匹配正文内容，请重新返回包含正文文字的正确尾句。",
        )
    planning_end = max(start, min(len(content), planning_end))
    min_end = start + 1
    if min_boundary_end is not None:
        min_end = max(start + 1, min(planning_end, int(min_boundary_end)))
    exact_matches = _find_boundary_text_matches(
        content,
        start,
        planning_end,
        text,
        min_boundary_end=min_end,
    )
    exact_matches = _dedupe_boundary_matches(exact_matches)
    if len(exact_matches) == 1:
        return _boundary_match_result("unique", match_mode="exact", boundary_text=text, matches=exact_matches)
    if len(exact_matches) > 1:
        return _boundary_match_result(
            "multiple",
            match_mode="exact",
            boundary_text=text,
            matches=exact_matches,
            reason="尾句匹配到多个位置，请重新返回更完整、可唯一定位的尾句。",
        )
    fallback_matches = _find_boundary_text_matches_ignoring_punctuation(
        content,
        start,
        planning_end,
        text,
        min_boundary_end=min_end,
    )
    if len(fallback_matches) == 1:
        return _boundary_match_result(
            "unique",
            match_mode="punctuation_stripped",
            boundary_text=text,
            matches=fallback_matches,
        )
    if len(fallback_matches) > 1:
        return _boundary_match_result(
            "multiple",
            match_mode="punctuation_stripped",
            boundary_text=text,
            matches=fallback_matches,
            reason="尾句匹配到多个位置，请重新返回更完整、可唯一定位的尾句。",
        )
    return _boundary_match_result(
        "no_match",
        match_mode="punctuation_stripped",
        boundary_text=text,
        reason="尾句无法匹配到正文，请重新返回正确尾句。",
    )






ASSET_RANGE_BOUNDARY_STRUCTURED_SCHEMA: dict[str, Any] = {
    "name": "asset_range_boundary",
    "description": "资产提取范围的原文断点选择，以及当前范围内新增阶段视觉判断。",
    "allow_extras": False,
    "fields": [
        {
            "name": "boundaryEndText",
            "type": "string",
            "required": True,
            "description": "断点末尾的原文片段，必须从当前待判断正文中原样摘录连续文本，并以断点末尾结尾；有效长度控制在 20-60 字，有效长度按去掉标点和空白后的文字计算。若最后一句太短，应向前连带上一句或短句补足；不要超过 60 字，不要改写、概括或补标点。",
        },
        {
            "name": "stageVisualChanged",
            "type": "boolean",
            "required": True,
            "description": "当前范围是否出现已有阶段视觉列表无法覆盖的新整体视觉阶段。",
        },
        {
            "name": "phaseVisualContexts",
            "type": "array",
            "required": False,
            "items": {
                "type": "object",
                "fields": [
                    {
                        "name": "name",
                        "type": "string",
                        "required": True,
                        "description": "阶段视觉名称，6-16字，只概括当前阶段的整体视觉状态；不要写具体事件、地点或道具。",
                    },
                    {
                        "name": "visualPrompt",
                        "type": "string",
                        "required": True,
                        "description": "阶段视觉描述，12-40字；必须使用“整体视觉以……为主。”句式。“……”只写当前阶段大多数剧情共同所在的时代、世界、场景、环境或生活质感。世界观、能力体系或重大事件如果只是通过传闻、公告、网络讨论、对话或信息被提到，不能写进 visualPrompt；只有它已经成为可见场景、环境设施、服饰物件或公共空间的主导视觉时，才写入。不要写剧情、原因、社会分析、局部家庭状态、房间、道具、单场事件、人物关系、后续阶段或“避免什么”。",
                    },
                    {
                        "name": "sourceSpan",
                        "type": "string",
                        "required": True,
                        "description": "该新阶段视觉覆盖的原文区间描述；只用于定位，不作为设计图提示词。",
                    },
                    {
                        "name": "visualChangeReason",
                        "type": "string",
                        "required": True,
                        "description": "为什么需要追加为新阶段视觉，20-80字；只说明整体视觉状态变化，如资源层级、世界体系、生活质感、训练/战斗状态发生变化，不写具体剧情。",
                    },
                    {
                        "name": "transitionType",
                        "type": "string",
                        "required": True,
                        "enum": ["initial_or_single_stage", "world_state_shift", "resource_class_shift", "power_system_shift", "combat_or_training_shift"],
                        "default": "initial_or_single_stage",
                        "description": "阶段变化类型。若这是项目没有阶段视觉时的起始视觉，使用 initial_or_single_stage；相对已有阶段或上一项发生变化时，选择 world_state_shift、resource_class_shift、power_system_shift 或 combat_or_training_shift。",
                    },
                ],
            },
            "default": [],
            "description": "只输出需要追加到项目设置的新阶段视觉，按原文顺序 0-4 个。若当前范围仍可沿用已有阶段视觉，输出空数组。",
        },
    ],
}


def _asset_range_phase_visual_context_items(value: Any) -> list[dict[str, str]]:
    items = value
    if isinstance(value, dict):
        items = value.get("phaseVisualContexts")
    if not isinstance(items, list):
        items = []
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        visual_prompt = _normalize_style_phase_visual_context(
            item.get("visualPrompt")
            or ""
        )
        if not visual_prompt:
            continue
        name = _compact_text(
            str(item.get("name") or item.get("title") or f"自动阶段视觉{index}"),
            40,
        )
        normalized.append(
            {
                "name": name or f"自动阶段视觉{index}",
                "visualPrompt": visual_prompt,
                "sourceSpan": _compact_text(str(item.get("sourceSpan") or ""), 80),
                "visualChangeReason": _compact_text(
                    str(item.get("visualChangeReason") or ""),
                    140,
                ),
                "transitionType": _compact_text(
                    str(item.get("transitionType") or ""),
                    40,
                ),
            }
        )
    return normalized[:4]


def _range_source_excerpt(content: str, start: int, end: int, limit: int = 240) -> str:
    excerpt = re.sub(r"\s+", " ", content[start:end]).strip()
    return excerpt[:limit]


def _episode_title_rules_payload() -> dict[str, Any]:
    return {
        "goal": "分集标题不完整总结整集，只抓本集最容易让读者记住的一个关键点。",
        "prefer": [
            "本集最核心的场景",
            "本集最关键的事件",
            "本集最重要的认知变化",
            "本集最有辨识度的危机或异常",
            "本集关系或局势的关键落点",
        ],
        "avoid": [
            "不要写成整集剧情梗概",
            "不要使用读者第一眼看不懂的内部术语",
            "不要把多个事件拼接成标题",
            "不要用生硬口语或临时吐槽，除非它就是本集最强钩子",
            "已确认标题后，后续流程不得二次发挥覆盖",
        ],
        "checks": [
            "读者没看正文前能大概知道这一集看点",
            "读者看完正文后会觉得标题抓住了本集最重要的钩子",
            "标题比完整剧情总结更短、更准、更有记忆点",
        ],
    }




def _episode_title_metadata_line(line: str) -> bool:
    normalized = re.sub(r"\s+", "", str(line or "").strip())
    if not normalized:
        return True
    if re.match(r"^《[^》]{1,80}》作者[:：]", normalized):
        return True
    if re.match(r"^(作者|分类|标签|字数|状态|简介|文案|书名|作品名|小说名)[:：]", normalized):
        return True
    if normalized in {"简介", "内容简介", "作品简介", "标签", "分类"}:
        return True
    return False


def _episode_boundary_title_context(content: str, start: int, end: int) -> dict[str, Any]:
    text = str(content or "")[max(0, start):max(start, end)]
    if not text:
        return {"rules": _episode_title_rules_payload(), "headExcerpt": "", "middleExcerpt": "", "tailExcerpt": ""}
    size = len(text)
    middle_start = max(0, (size // 2) - 450)
    return {
        "rules": _episode_title_rules_payload(),
        "instruction": "先按规则从本集原文提炼 episodeTitle/title；不要提交 E01/第1集/分集原文这类假标题。",
        "headExcerpt": _compact_text(text[:1000], 1000),
        "middleExcerpt": _compact_text(text[middle_start:middle_start + 900], 900) if size > 1600 else "",
        "tailExcerpt": _compact_text(text[max(0, size - 1000):], 1000) if size > 1000 else "",
    }


def _normalize_episode_boundary_title(value: Any, episode_id: str = "") -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n\"'“”‘’《》")
    text = re.sub(r"^(?:分集|本集|剧集|episode)\s*标题\s*[：:]\s*", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return ""
    episode_number = None
    matches = re.findall(r"\d+", str(episode_id or ""))
    if matches:
        try:
            episode_number = int(matches[-1])
        except (TypeError, ValueError):
            episode_number = None
    generic_labels = {
        str(episode_id or "").strip().casefold(),
        str(episode_id or "").strip().replace("0", "").casefold(),
    }
    if episode_number:
        generic_labels.update(
            {
                f"第{episode_number}集".casefold(),
                f"第{episode_number:02d}集".casefold(),
                f"episode{episode_number}".casefold(),
                f"ep{episode_number}".casefold(),
                f"e{episode_number}".casefold(),
                f"e{episode_number:02d}".casefold(),
            }
        )
    normalized = re.sub(r"\s+", "", text).casefold()
    if normalized in {"分集原文", "本集原文", "原文"}:
        return ""
    if normalized in {item for item in generic_labels if item}:
        return ""
    if re.fullmatch(
        r"(?:第[一二三四五六七八九十百千万\d]+[章节回卷集部]|chapter\s+\d+|episode\s+\d+|ep\s*\d+|e\s*\d+)",
        text,
        re.IGNORECASE,
    ):
        return ""
    chapter_match = re.match(
        r"^(?:第[一二三四五六七八九十百千万\d]+[章节回卷集部]|chapter\s+\d+|episode\s+\d+|ep\s*\d+|e\s*\d+)\s*[：:、,.，。.\-—_ ]+(.+)$",
        text,
        re.IGNORECASE,
    )
    if chapter_match:
        suffix = chapter_match.group(1).strip(" \t\r\n\"'“”‘’《》")
        if suffix and re.sub(r"\s+", "", suffix).casefold() not in {item for item in generic_labels if item}:
            text = suffix
    return _compact_text(text, 40)


def _episode_boundary_title_from_text(text: str, episode_id: str) -> str:
    head = str(text or "")[:1600]
    lines = [raw_line.strip() for raw_line in head.splitlines()]
    for line in lines:
        if not line:
            continue
        explicit = re.match(r"^(?:分集|本集|剧集|episode)\s*标题\s*[：:]\s*(.+)$", line, re.IGNORECASE)
        if explicit:
            title = _normalize_episode_boundary_title(explicit.group(1), episode_id)
            if title:
                return title
    for line in lines:
        if not line or _episode_title_metadata_line(line):
            continue
        heading = re.match(
            r"^(第[一二三四五六七八九十百千万\d]+[章节回卷集部][^\n]{0,48}|chapter\s+\d+[^\n]{0,60}|episode\s+\d+[^\n]{0,60})$",
            line,
            re.IGNORECASE,
        )
        if heading:
            title = _normalize_episode_boundary_title(heading.group(1), episode_id)
            if title:
                return title
    for line in lines:
        if not line or _episode_title_metadata_line(line):
            continue
        if len(line) <= 28 and not re.search(r"[。！？!?；;]$", line):
            title = _normalize_episode_boundary_title(line, episode_id)
            if title:
                return title
    return ""


def _episode_title_from_shot_plan(project_id: str, episode_id: str) -> str:
    from .agent_sessions import _project_dir
    path = _project_dir(project_id) / "episodes" / episode_id / "work_chain_plan.json"
    if not path.exists() or not path.is_file():
        return ""
    document = _read_json(path, {})
    if not isinstance(document, dict):
        return ""
    proposal = document.get("plotSplitProposal") if isinstance(document.get("plotSplitProposal"), dict) else {}
    for value in (
        document.get("episodeTitle"),
        document.get("episode_title"),
        proposal.get("episodeTitle"),
        proposal.get("episode_title"),
        proposal.get("title"),
    ):
        title = _normalize_episode_boundary_title(value, episode_id)
        if title:
            return title
    return ""


def _episode_boundary_title_from_payload(payload: dict[str, Any], episode_id: str, text: str = "") -> str:
    for key in ("episodeTitle", "episode_title", "title"):
        title = _normalize_episode_boundary_title(payload.get(key), episode_id)
        if title:
            return title
    return _episode_boundary_title_from_text(text, episode_id) if text else ""


def _episode_boundary_tolerance_units(payload: dict[str, Any], target_units: int) -> int:
    raw_value = _payload_first_present(payload, "boundaryToleranceUnits", "boundary_tolerance_units")
    if raw_value is None:
        if target_units < 500:
            raw_value = max(1, int(target_units * 0.2))
        else:
            raw_value = max(80, min(200, int(target_units * 0.2)))
    try:
        tolerance = int(raw_value)
    except (TypeError, ValueError):
        tolerance = 0
    return max(0, min(max(0, target_units - 1), tolerance))


def _episode_boundary_planning_window_end(
    content: str,
    start: int,
    target_units: int,
    boundary_tolerance_units: int,
    upper_limit: int,
) -> int:
    total = len(content)
    upper_limit = max(start, min(total, upper_limit))
    # Expose the full allowed window so the agent can choose the scene ending.
    return min(
        upper_limit,
        content_offset_after_units(content, start, target_units + boundary_tolerance_units),
    )


def _episode_boundary_asset_cursor_end(coverage: dict[str, Any], total_chars: int) -> int:
    asset_cursor = coverage.get("assetCursor") if isinstance(coverage.get("assetCursor"), dict) else {}
    try:
        offset = int(asset_cursor.get("nextOffset") or 0)
    except (TypeError, ValueError):
        offset = 0
    return max(0, min(total_chars, offset))




def _model_request_user_instruction_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text).casefold().strip("。！？!?，,；;：:.")
    exact_control_terms = {
        "继续",
        "继续执行",
        "继续下一步",
        "下一步继续",
        "确认",
        "确认提交",
        "提交",
        "保存",
        "可以",
        "好的",
        "好",
        "ok",
        "yes",
        "同意",
        "就这样",
        "按这个",
        "接着做",
        "接着来",
        "确认继续",
        "继续确认",
        "确认继续执行",
        "确认继续提交",
        "确认继续保存",
        "好的继续",
        "可以继续",
        "同意继续",
        "好继续",
    }
    if compact in exact_control_terms:
        return ""
    control_prefixes = ("确认", "继续", "同意", "可以", "好的", "ok", "yes", "好")
    control_suffixes = {
        "执行",
        "提交",
        "保存",
        "处理",
        "开始",
        "下一步",
        "继续下一步",
        "提交当前结果",
        "提交当前方案",
        "保存当前结果",
        "保存当前方案",
        "执行当前结果",
        "执行当前方案",
        "吧",
        "了",
        "这版",
        "这个",
        "当前结果",
        "当前方案",
    }
    for prefix in control_prefixes:
        if compact.startswith(prefix) and compact[len(prefix):] in control_suffixes:
            return ""
    return text


def _episode_boundary_risk_notes(value: Any) -> list[str]:
    from .projects import _text_list
    rows = value if isinstance(value, list) else _text_list(value, limit=3)
    return [_compact_text(str(item or ""), 120) for item in rows[:3] if str(item or "").strip()]


def _compact_text_model_meta(model_meta: dict[str, Any] | None) -> dict[str, Any]:
    meta = model_meta if isinstance(model_meta, dict) else {}
    result: dict[str, Any] = {}
    for key in (
        "source",
        "modelId",
        "modelLabel",
        "providerId",
        "providerInstanceId",
        "structuredSchema",
        "structuredMode",
        "nativeStructuredCapability",
        "error",
    ):
        if meta.get(key) not in (None, "", [], {}):
            result[key] = copy.deepcopy(meta.get(key))
    for key in ("validationErrors", "repairErrors", "modelRequestLogs", "modelResponseLogs", "modelRequestLogErrors"):
        if isinstance(meta.get(key), list) and meta.get(key):
            result[key] = copy.deepcopy(meta.get(key))
    return result


def _source_coverage_commit_guard(coverage: dict[str, Any]) -> dict[str, Any]:
    return {
        "expectedRevision": _resource_revision_value(coverage),
        "baseHash": _json_hash(coverage),
    }


def _commit_next_step(commit_tool: str) -> dict[str, Any]:
    return {
        "requiresUserConfirmation": True,
        "message": "先向用户汇报本次提案；分集断点必须同时报告标题。用户明确继续或接受后，直接调用对应 commit 工具并传入 commitPayload。",
        "commitTool": commit_tool,
        "nextAllowedTools": [commit_tool],
    }


def _episode_boundary_commit_payload(proposal: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    proposal_copy = copy.deepcopy(proposal)
    end_offset = int(proposal_copy.get("recommendedEndOffset") or proposal_copy.get("endOffset") or 0)
    episode_id = str(proposal_copy.get("episodeId") or proposal_copy.get("episode_id") or "").strip()
    title = _episode_boundary_title_from_payload(proposal_copy, episode_id)
    payload = {
        "proposalId": str(proposal_copy.get("proposalId") or proposal_copy.get("proposal_id") or "").strip(),
        "sourceId": proposal_copy.get("sourceId"),
        "episodeId": episode_id,
        "title": title,
        "episodeTitle": title,
        "startOffset": int(proposal_copy.get("startOffset") or 0),
        "endOffset": end_offset,
        "recommendedEndOffset": end_offset,
        "targetUnits": int(proposal_copy.get("targetUnits") or 0),
        "reason": str(proposal_copy.get("reason") or ""),
        "committedBy": "agent",
    }
    for key in (
        "boundaryReason",
        "boundaryEndText",
        "boundaryToleranceUnits",
        "planningLookaheadUnits",
        "planningWindowEnd",
        "planningMethod",
        "riskNotes",
    ):
        if proposal_copy.get(key) not in (None, "", [], {}):
            payload[key] = copy.deepcopy(proposal_copy.get(key))
    payload.update(_source_coverage_commit_guard(coverage))
    return payload


def _episode_boundary_pending_matches_payload(
    pending: dict[str, Any],
    payload: dict[str, Any],
    proposal: dict[str, Any],
) -> bool:
    if not isinstance(pending, dict) or not pending:
        return False
    pending_proposal_id = _payload_first_text(pending.get("proposalId"), pending.get("proposal_id"))
    proposal_id = _payload_first_text(
        payload.get("proposalId"),
        payload.get("proposal_id"),
        proposal.get("proposalId"),
        proposal.get("proposal_id"),
    )
    if not pending_proposal_id or proposal_id != pending_proposal_id:
        return False
    pending_source_id = _payload_first_text(pending.get("sourceId"), pending.get("source_id"))
    source_id = _payload_first_text(
        payload.get("sourceId"),
        payload.get("source_id"),
        proposal.get("sourceId"),
        proposal.get("source_id"),
    )
    if not source_id or source_id != pending_source_id:
        return False
    pending_episode_id = _payload_first_text(pending.get("episodeId"), pending.get("episode_id"))
    episode_id = _payload_first_text(
        payload.get("episodeId"),
        payload.get("episode_id"),
        proposal.get("episodeId"),
        proposal.get("episode_id"),
    )
    if not episode_id or episode_id != pending_episode_id:
        return False
    pending_start = _payload_first_int(pending.get("startOffset"), pending.get("start_offset"))
    start = _payload_first_int(
        payload.get("startOffset"),
        payload.get("start_offset"),
        proposal.get("startOffset"),
        proposal.get("start_offset"),
    )
    if start is None or pending_start is None or start != pending_start:
        return False
    pending_end = _payload_first_int(pending.get("recommendedEndOffset"), pending.get("endOffset"))
    end = _payload_first_int(
        payload.get("endOffset"),
        payload.get("absoluteEnd"),
        payload.get("recommendedEndOffset"),
        proposal.get("recommendedEndOffset"),
        proposal.get("endOffset"),
    )
    if end is None or pending_end is None or end != pending_end:
        return False
    pending_method = _payload_first_text(pending.get("planningMethod"))
    planning_method = _payload_first_text(payload.get("planningMethod"), proposal.get("planningMethod"))
    if pending_method != "agent_episode_boundary" or planning_method != pending_method:
        return False
    pending_boundary_text = _payload_first_text(pending.get("boundaryEndText"))
    boundary_text = _payload_first_text(payload.get("boundaryEndText"), proposal.get("boundaryEndText"))
    return bool(pending_boundary_text and boundary_text == pending_boundary_text)


def _asset_range_commit_payload(proposal: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    proposal_copy = copy.deepcopy(proposal)
    start_offset = int(proposal_copy.get("absoluteStart") or proposal_copy.get("startOffset") or 0)
    end_offset = int(proposal_copy.get("absoluteEnd") or proposal_copy.get("endOffset") or 0)
    phase_visual_contexts = _asset_range_phase_visual_context_items(proposal_copy)
    payload = {
        "sourceId": proposal_copy.get("sourceId"),
        "rangeId": proposal_copy.get("rangeId"),
        "startOffset": start_offset,
        "absoluteStart": start_offset,
        "endOffset": end_offset,
        "absoluteEnd": end_offset,
        "targetUnits": int(proposal_copy.get("targetUnits") or 0),
        "assetTypes": proposal_copy.get("assetTypes") if isinstance(proposal_copy.get("assetTypes"), list) else [],
        "summary": str(proposal_copy.get("summary") or ""),
        "reason": str(proposal_copy.get("reason") or ""),
        "boundaryReason": str(proposal_copy.get("boundaryReason") or ""),
        "boundaryToleranceUnits": int(proposal_copy.get("boundaryToleranceUnits") or 0),
        "planningLookaheadUnits": int(proposal_copy.get("planningLookaheadUnits") or 0),
        "planningWindowEnd": int(proposal_copy.get("planningWindowEnd") or end_offset),
        "planningMethod": str(proposal_copy.get("planningMethod") or ""),
        "boundaryEndText": str(proposal_copy.get("boundaryEndText") or ""),
        "phaseVisualContext": str(proposal_copy.get("phaseVisualContext") or ""),
        "phaseVisualContexts": phase_visual_contexts,
        "stageVisualChanged": bool(phase_visual_contexts),
        "riskNotes": proposal_copy.get("riskNotes") if isinstance(proposal_copy.get("riskNotes"), list) else [],
    }
    payload.update(_source_coverage_commit_guard(coverage))
    return payload


def _project_genre_context(project_id: str, limit: int = 160) -> str:
    from .agent_sessions import _project_meta_path
    meta = _read_json(_project_meta_path(project_id), {})
    if not isinstance(meta, dict):
        return ""
    overview_analysis = (
        meta.get("overview_analysis")
        if isinstance(meta.get("overview_analysis"), dict)
        else {}
    )
    overview_result = (
        overview_analysis.get("result")
        if isinstance(overview_analysis.get("result"), dict)
        else {}
    )
    return _compact_text(
        str(
            overview_result.get("genre_context")
            or overview_result.get("genreContext")
            or ""
        ),
        limit,
    )


def _genre_context_policy_for_stage(stage: str) -> str:
    if stage == "episode_boundary":
        return (
            "题材语境只用于辅助判断本次分集断点汇报的叙事口味、节奏预期和钩子表达；"
            "自然断点仍以当前原文和资产覆盖为准，不得补写角色、地点、事件、设定规则或当前范围没有的剧情事实。"
        )
    return (
        "题材语境只作为类型和叙事口味弱约束；不得新增剧情事实、角色、地点、世界规则或阶段设定。"
    )


def _unwrap_agent_commit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    commit_payload = payload.get("commitPayload")
    if not isinstance(commit_payload, dict):
        return payload
    merged = copy.deepcopy(commit_payload)
    for key in (
        "reason",
        "boundaryReason",
        "riskNotes",
        "userInstruction",
        "committedBy",
        "title",
        "episodeTitle",
    ):
        value = payload.get(key)
        if value is not None:
            merged[key] = value
    return merged
