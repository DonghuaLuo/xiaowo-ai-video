# -*- coding: utf-8 -*-
"""从已提交原文、资产和生产要求构建任务上下文。"""
from __future__ import annotations

import copy
from .agent_sessions import (
    _project_dir,
)
from .assets import (
    list_assets,
)
from .context_resolver import (
    merge_asset_candidates,
    resolve_work_context,
)
from .production_specs import (
    build_project_production_spec,
)
from .source_coverage import _asset_ranges_for_source_ref, _load_source_coverage, _source_ref_bounds
from .source_index import read_source_window
from .source_text_store import _compact_text
from .store_core import (
    _read_json,
)
from .worker_asset_context import (
    _asset_design_catalog_rows,
    _asset_state_versions_for_prompt,
    _asset_tagged_media_versions_for_context,
)
from .worker_asset_contract import (
    _ANALYZE_ASSETS_BOUNDARY_SPEC_VERSION,
    _ASSET_ADJACENT_SOURCE_CHARS,
    _ASSET_TYPES,
    _SCENE_REFERENCE_ROLE_CONTEXT_ONLY,
    _analyze_assets_boundary_spec_text,
    _scene_reference_role,
)
from .worker_asset_materials import (
    _asset_context_file_catalog,
)
from .worker_contract import worker_work_definition
from .worker_text import (
    _compact_source_excerpt,
    _compact_story_text,
)
from typing import (
    Any,
)
from utils.text_metrics import (
    content_char_count,
)




def _resolved_plot_context_assets(
    project_id: str,
    episode_id: str,
    source: dict[str, Any],
    *,
    production_memory: dict[str, Any] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    source_ref = source.get("sourceRef") if isinstance(source.get("sourceRef"), dict) else {}
    source_text = str(source.get("text") or "")
    current_assets = _asset_name_rows(
        project_id,
        include_desc=True,
        source_ref=source_ref,
    )
    context_envelope = resolve_work_context(
        project_id,
        "plot_splitting",
        episode_id=episode_id,
        current_source=source,
        production_memory=production_memory or {},
    )
    continuity = (
        context_envelope.get("continuity") if isinstance(context_envelope.get("continuity"), dict) else {}
    )
    previous_episode = (
        continuity.get("previousEpisode") if isinstance(continuity.get("previousEpisode"), dict) else {}
    )
    previous_source_ref = (
        previous_episode.get("sourceRef") if isinstance(previous_episode.get("sourceRef"), dict) else {}
    )
    carryover_assets = (
        _asset_name_rows(
            project_id,
            include_desc=True,
            source_ref=previous_source_ref,
        )
        if previous_source_ref
        else {}
    )
    merged_assets, merged_envelope = merge_asset_candidates(
        current_assets,
        carryover_assets,
        current_text=source_text,
        context_envelope=context_envelope,
    )
    return _filter_plot_splitting_candidate_assets(merged_assets), merged_envelope


def build_worker_task_context(
    project_id: str,
    worker_name: str,
    task_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = task_payload if isinstance(task_payload, dict) else {}
    production_spec = build_project_production_spec(
        _read_json(_project_dir(project_id) / "config.json", {})
    )
    if worker_name == "analyze-assets":
        work_definition = worker_work_definition(worker_name)
        range_row = payload.get("range") if isinstance(payload.get("range"), dict) else payload
        source_id = str(range_row.get("sourceId") or "").strip()
        asset_range_id = str(
            range_row.get("assetRangeId")
            or range_row.get("rangeId")
            or ""
        ).strip()
        absolute_start = int(range_row.get("absoluteStart") or range_row.get("startOffset") or 0)
        absolute_end = int(range_row.get("absoluteEnd") or range_row.get("endOffset") or 0)
        if not source_id:
            raise ValueError("analyze-assets worker 缺少 sourceId")
        if not asset_range_id:
            raise ValueError("analyze-assets worker 缺少 assetRangeId/rangeId")
        if absolute_end <= absolute_start:
            raise ValueError("analyze-assets worker 收到无效资产范围")
        source_window = _source_window_for_range(project_id, source_id, absolute_start, absolute_end)
        adjacent_context = _asset_adjacent_source_context(
            project_id,
            source_id,
            absolute_start,
            absolute_end,
            window_chars=_ASSET_ADJACENT_SOURCE_CHARS,
            include_after=bool(source_window.get("hasAfter")),
        )
        existing_assets, asset_catalog_meta = _asset_design_catalog_rows(project_id)
        context_envelope = {
            "schemaVersion": 1,
            "workType": "asset_extraction",
            "target": {
                "assetRangeId": asset_range_id,
                "sourceId": source_id,
                "absoluteStart": absolute_start,
                "absoluteEnd": absolute_end,
            },
            "factPriority": [
                "committed_asset_range_explicit_text",
                "confirmed_existing_asset_identity",
                "adjacent_source_identity_evidence",
                "genre_context",
                "minimal_model_inference",
            ],
            "adjacentEvidence": adjacent_context,
            "retrievalPolicy": {
                "mode": "controller_prefetched_short_context",
                "rule": "先从 sourceText 建立候选，再结合 assets 判断复用关系；设计与审查只使用本轮提供的相关扩展资料摘要，不调用工具或扫描资料库。",
                "assetCreationBoundary": "新资产必须在当前已提交 sourceText 中有清楚对象证据；对象证据可以来自现场出场，也可以来自剧情内媒介、口述、档案、肖像或资料展示；相邻原文、题材语境和项目资料只能辅助理解与合并。",
                "extensionMaterialBoundary": "扩展资料仅用于 analyze-assets 的角色、生物、场景、道具拆分与设计；源文件列表和临时源文件不属于扩展资料，小说正文只使用当前 sourceText。",
            },
        }
        return {
            "workerName": worker_name,
            "projectId": project_id,
            "assetRangeId": asset_range_id,
            "sourceId": source_id,
            "absoluteStart": absolute_start,
            "absoluteEnd": absolute_end,
            "sourceText": str(source_window.get("text") or ""),
            "sourceWindow": {
                key: source_window.get(key)
                for key in ("sourceId", "chapterId", "absoluteStart", "absoluteEnd", "length", "hasAfter", "chunks")
                if key in source_window
            },
            "sourceRef": {
                "sourceId": source_id,
                "absoluteStart": absolute_start,
                "absoluteEnd": absolute_end,
                "assetRangeId": asset_range_id,
            },
            "productionSpec": production_spec,
            "assets": existing_assets,
            "assetCatalogMeta": asset_catalog_meta,
            "assetContextFileCatalog": _asset_context_file_catalog(project_id),
            "contextEnvelope": context_envelope,
            "genreContext": _project_genre_context(project_id),
            "genreContextPolicy": (
                "题材语境只用于辅助判断当前资产范围的类型口味、资产重要性和设计取向；"
                "sourceText 仍是新增资产事实来源；不得据此新增当前范围没有清楚对象证据的角色、地点、事件、设定规则或资产。"
            ),
            "extractedRequirements": _normalize_extracted_requirements(
                payload.get("extractedRequirements")
                or payload.get("requirements")
                or payload.get("assetExtractionRequirements")
                or payload.get("assetRequirements"),
                str(work_definition.get("workType") or "asset_extraction"),
            ),
            "assetRules": {
                "assetContract": f"详细拆分、设计和审查规则以 analyze-assets 任务提示词和 {_ANALYZE_ASSETS_BOUNDARY_SPEC_VERSION} 为准。",
                "sourcePolicy": "sourceText 是新增资产的事实来源；当前正文中的现场出场、剧情内媒介、口述、档案、肖像或资料展示都可以构成对象证据。genreContext 只提供题材语境弱约束，contextEnvelope、已有资产索引和提供的扩展资料摘要只辅助理解类型、身份、世界观和连续性，不能凭空新增当前正文未出现的资产。",
                "existingAssetPolicy": "assets 是已有资产紧凑索引，用于识别同一资产、别名和既有视觉连续性；命中已有资产时复用其 id 与规范名称，并按复用资产的输出字段要求提交。",
                "extensionMaterialPolicy": "扩展资料板块只在资产拆分与设计时可用，用于补足角色、生物、场景、道具设定理解；设计前先按文件名/路径路由，再只使用候选名命中或明确候选文件路由后的短摘要；不要读取源文件列表或把源文件正文当扩展资料。",
                "boundaryPolicy": _analyze_assets_boundary_spec_text(stage="context-asset-rules"),
                "baselineDesignPolicy": "角色、生物、场景、道具都只设计稳定资产母版；不同服装、形态、损毁或阶段变化只用于判断是否复用同一资产，不输出版本标注字段，也不拆成另一份资产。",
                "outputPolicy": "新资产输出 name/aliases/desc/assetImagePrompt/sourceEvidence/designRationale；characters 额外输出 voiceStyle；creatures 仅在有稳定语言型声线时输出 voiceStyle。资产 name 只写规范名；aliases 只收录原文明确指向同一资产的真实姓名、正式专名、稳定专有别名或疑似笔误异名，不收录普通称谓、关系称呼、泛称、状态称呼或括号说明。若同一资产出现多个精确名称，优先用已有规范名；新资产优先用自我介绍、旁白确认或更权威的正式名称作为 name，其他精确名称写入 aliases。复用已有资产时只输出 assetId/name/sourceEvidence/designRationale，不重复改写已有 desc、assetImagePrompt 或 voiceStyle。拆分资产阶段不输出版本标注字段。voiceStyle 是声线设计，只写音色、年龄感、声区/音高、气息、语速、咬字、力度、口音倾向和少量可听见的声音气质，禁止写台词、常用短句、口头禅、语气词、示例对白、性格判断、情绪底色或当场态度。",
            },
            "userInstruction": _compact_text(
                payload.get("userInstruction"),
                500,
            ),
        }
    raise ValueError(f"未知 worker：{worker_name}")






def _normalize_extracted_requirements(value: Any, work_type: str) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    raw_constraints = source.get("constraints") if isinstance(source.get("constraints"), list) else []
    constraints: list[str] = []
    seen: set[str] = set()
    for item in raw_constraints:
        text = _compact_text(item, 260)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        constraints.append(text)
        if len(constraints) >= 12:
            break
    summary = _compact_text(source.get("summary"), 500) if constraints else ""
    constraint_map = {constraint.casefold(): constraint for constraint in constraints}
    raw_evidence = source.get("evidence") if isinstance(source.get("evidence"), list) else []
    evidence: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
    for item in raw_evidence:
        if not isinstance(item, dict):
            continue
        constraint_text = _compact_text(
            item.get("constraint") or item.get("text") or item.get("requirement"),
            260,
        )
        constraint = constraint_map.get(constraint_text.casefold())
        if not constraint:
            continue
        raw_indexes = (
            item.get("messageIndexes")
            if isinstance(item.get("messageIndexes"), list)
            else item.get("message_indices")
        )
        if not isinstance(raw_indexes, list):
            raw_indexes = [raw_indexes]
        indexes: list[int] = []
        for raw_index in raw_indexes:
            try:
                message_index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if message_index <= 0 or message_index in indexes:
                continue
            indexes.append(message_index)
            if len(indexes) >= 8:
                break
        if not indexes:
            continue
        evidence_key = f"{constraint.casefold()}:{','.join(str(index) for index in indexes)}"
        if evidence_key in seen_evidence:
            continue
        seen_evidence.add(evidence_key)
        evidence.append({"constraint": constraint, "messageIndexes": indexes})
        if len(evidence) >= 12:
            break
    return {
        "workType": str(source.get("workType") or source.get("work_type") or work_type),
        "constraints": constraints,
        "summary": summary,
        "evidence": evidence if constraints else [],
        "source": str(source.get("source") or "requirement_extractor"),
    }


def _project_genre_context(project_id: str, limit: int = 160) -> str:
    meta = _read_json(_project_dir(project_id) / "project.json", {})
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


def _asset_range_scope_for_source_ref(
    project_id: str,
    source_ref: dict[str, Any] | None,
) -> tuple[set[str], set[str], bool]:
    ref = source_ref if isinstance(source_ref, dict) else {}
    source_id = str(ref.get("sourceId") or "").strip()
    start, end = _source_ref_bounds(ref)
    if not source_id or start is None or end is None or end <= start:
        return set(), set(), False
    ranges = _asset_ranges_for_source_ref(project_id, source_ref)
    range_ids: set[str] = set()
    asset_tokens: set[str] = set()
    for range_row in ranges:
        range_id = str(range_row.get("rangeId") or "").strip()
        if range_id:
            range_ids.add(range_id.casefold())
        created_ids = range_row.get("createdAssetIds") if isinstance(range_row.get("createdAssetIds"), list) else []
        for value in created_ids:
            token = str(value or "").strip()
            if token:
                asset_tokens.add(token.casefold())
    if ranges:
        return range_ids, asset_tokens, True
    try:
        coverage = _load_source_coverage(project_id, source_id or None)
    except Exception:
        return set(), set(), False
    has_ranges_for_source = any(
        isinstance(item, dict)
        and (
            not source_id
            or str(item.get("sourceId") or "").strip() == source_id
        )
        for item in (coverage.get("assetRanges") if isinstance(coverage.get("assetRanges"), list) else [])
    )
    return set(), set(), bool(has_ranges_for_source)


def _asset_row_matches_range_scope(
    row: dict[str, Any],
    range_ids: set[str],
    asset_tokens: set[str],
) -> bool:
    for row_range_id in _asset_row_range_ids(row):
        if row_range_id.casefold() in range_ids:
            return True
    token = str(row.get("id") or "").strip()
    if token and token.casefold() in asset_tokens:
        return True
    return False


def _asset_row_range_ids(row: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("assetRangeIds",):
        raw = row.get(key)
        if isinstance(raw, (list, tuple, set)):
            values.extend(raw)
        else:
            values.append(raw)
    values.append(row.get("assetRangeId"))
    result: list[str] = []
    for value in values:
        token = str(value or "").strip()
        if token and token not in result:
            result.append(token)
    return result


def _asset_name_rows(
    project_id: str,
    *,
    include_desc: bool = True,
    source_ref: dict[str, Any] | None = None,
    include_state_versions: bool = True,
    desc_limit: int = 120,
) -> dict[str, list[dict[str, Any]]]:
    assets = list_assets("project", project_id, hydrate=False, lifecycle_status="active", persist_normalization=False)
    range_ids, asset_tokens, scoped = _asset_range_scope_for_source_ref(project_id, source_ref)
    result: dict[str, list[dict[str, Any]]] = {}
    for asset_type in _ASSET_TYPES:
        rows = assets.get(asset_type) if isinstance(assets, dict) else []
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            if scoped and not _asset_row_matches_range_scope(row, range_ids, asset_tokens):
                continue
            name = str(row.get("name") or row.get("title") or "").strip()
            row_id = str(row.get("id") or "").strip()
            if not row_id or not name:
                continue
            row_key = row_id.casefold()
            if row_key in seen:
                continue
            seen.add(row_key)
            item = {
                "id": row_id,
                "name": name,
            }
            aliases = [
                _compact_text(alias, 40)
                for alias in (row.get("aliases") if isinstance(row.get("aliases"), list) else [])
                if str(alias or "").strip()
            ][:8]
            if aliases:
                item["aliases"] = aliases
            if include_desc:
                item["desc"] = _compact_text(row.get("desc") or row.get("description") or "", desc_limit)
            if asset_type == "scenes":
                scene_reference_role = _scene_reference_role(row)
                if scene_reference_role:
                    item["sceneReferenceRole"] = scene_reference_role
            if include_state_versions:
                tagged_versions = _asset_tagged_media_versions_for_context(row)
                prompt_versions = _asset_state_versions_for_prompt(tagged_versions)
                if prompt_versions:
                    item["stateVersions"] = prompt_versions
            normalized.append(item)
        result[asset_type] = normalized
    return result


def _asset_hint_tokens(value: Any) -> set[str]:
    tokens: set[str] = set()
    rows = value if isinstance(value, list) else []
    for row in rows:
        if isinstance(row, dict):
            candidates = (row.get("id"),)
        else:
            candidates = (row,)
        for candidate in candidates:
            token = str(candidate or "").strip()
            if token:
                tokens.add(token)
    return tokens


def _plot_asset_hint_key(value: Any) -> str:
    if isinstance(value, dict):
        raw = value.get("id") or ""
    else:
        raw = value
    return str(raw or "").strip()


def _scene_lookup_for_plot_assets(assets: dict[str, list[dict[str, Any]]] | None) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    rows = assets.get("scenes") if isinstance(assets, dict) and isinstance(assets.get("scenes"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        keys = [
            str(row.get("id") or "").strip(),
        ]
        for key in keys:
            if key:
                lookup.setdefault(key.casefold(), row)
    return lookup


def _filter_plot_scene_asset_hints(
    asset_hints: dict[str, list[Any]],
    assets: dict[str, list[dict[str, Any]]] | None,
    *,
    item_label: str = "",
    warnings: list[str] | None = None,
) -> dict[str, list[Any]]:
    if not isinstance(asset_hints, dict):
        return asset_hints
    scenes = asset_hints.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return asset_hints
    lookup = _scene_lookup_for_plot_assets(assets)
    if not lookup:
        if warnings is not None:
            label = item_label or "当前原文拆分内容"
            warnings.append(f"{label} 移除了未在候选资产中的场景引用。")
        asset_hints["scenes"] = []
        return asset_hints
    kept: list[Any] = []
    dropped_names: list[str] = []
    for hint in scenes:
        hint_key = _plot_asset_hint_key(hint)
        row = lookup.get(hint_key.casefold()) if hint_key else None
        if not row:
            if hint_key:
                dropped_names.append(hint_key)
            continue
        if _scene_reference_role(row) == _SCENE_REFERENCE_ROLE_CONTEXT_ONLY:
            dropped_names.append(str(row.get("name") or hint_key).strip() or hint_key)
            continue
        kept.append(hint)
    if dropped_names and warnings is not None:
        label = item_label or "当前原文拆分内容"
        warnings.append(
            f"{label} 移除了只可作为语境资料的场景引用：{', '.join(dropped_names)}。"
        )
    asset_hints["scenes"] = kept
    return asset_hints


def _filter_plot_splitting_candidate_assets(
    assets: dict[str, list[dict[str, Any]]] | None,
) -> dict[str, list[dict[str, Any]]]:
    source = assets if isinstance(assets, dict) else {}
    filtered: dict[str, list[dict[str, Any]]] = {}
    for asset_type in _ASSET_TYPES:
        rows = source.get(asset_type) if isinstance(source.get(asset_type), list) else []
        selected: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if asset_type == "scenes" and _scene_reference_role(row) == _SCENE_REFERENCE_ROLE_CONTEXT_ONLY:
                continue
            selected.append(copy.deepcopy(row))
        filtered[asset_type] = selected
    return filtered


def _filter_assets_for_plot_proposal(
    assets: dict[str, list[dict[str, Any]]],
    plot_split_proposal: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    assets = _filter_plot_splitting_candidate_assets(assets)
    items = plot_split_proposal.get("items") if isinstance(plot_split_proposal.get("items"), list) else []
    hints: dict[str, set[str]] = {asset_type: set() for asset_type in _ASSET_TYPES}
    for item in items:
        if not isinstance(item, dict):
            continue
        asset_hints = item.get("assetHints") or item.get("asset_refs") or item.get("assetRefs")
        if not isinstance(asset_hints, dict):
            continue
        for asset_type in _ASSET_TYPES:
            hints[asset_type].update(_asset_hint_tokens(asset_hints.get(asset_type)))
    if not any(hints.values()):
        return {asset_type: [] for asset_type in _ASSET_TYPES}
    filtered: dict[str, list[dict[str, Any]]] = {}
    for asset_type in _ASSET_TYPES:
        rows = assets.get(asset_type) if isinstance(assets.get(asset_type), list) else []
        wanted = hints.get(asset_type) or set()
        if not wanted:
            filtered[asset_type] = []
            continue
        selected = [
            row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("id") or "").strip() in wanted
        ]
        filtered[asset_type] = selected
    return filtered


def _source_preview_from_refs(
    refs: Any,
    *,
    episode_text: str,
    episode_source_ref: dict[str, Any],
    limit: int = 2400,
) -> str:
    if not episode_text:
        return ""
    rows = refs if isinstance(refs, list) else [refs] if isinstance(refs, dict) else []
    episode_start, _episode_end = _source_ref_bounds(episode_source_ref)
    if episode_start is None:
        episode_start = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        start, end = _source_ref_bounds(row)
        if start is None or end is None or end <= start:
            continue
        local_start = max(0, start - episode_start)
        local_end = min(len(episode_text), end - episode_start)
        if local_end <= local_start:
            continue
        preview = episode_text[local_start:local_end].strip()
        if limit > 0 and len(preview) > limit:
            preview = preview[:limit].rstrip()
        if preview:
            return preview
    return ""


def _enrich_plot_split_source_previews_for_context(
    plot_split_proposal: dict[str, Any],
    *,
    episode_text: str,
    episode_source_ref: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(plot_split_proposal, dict):
        return {}
    items = plot_split_proposal.get("items") if isinstance(plot_split_proposal.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict) or item.get("sourcePreview"):
            continue
        preview = _source_preview_from_refs(
            item.get("sourceRefs") or item.get("source_refs"),
            episode_text=episode_text,
            episode_source_ref=episode_source_ref,
        )
        if preview:
            item["sourcePreview"] = preview
    return plot_split_proposal


def _compact_plot_split_proposal_for_context(
    value: Any,
    *,
    include_asset_hints: bool = True,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    items = value.get("items") if isinstance(value.get("items"), list) else []
    compact_items: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        compact_item = {
            "index": item.get("index") or index,
            "id": str(item.get("id") or f"plot_{index:03d}"),
            "title": _compact_text(item.get("title") or item.get("name"), 80),
            "sourceStartAnchor": _compact_source_excerpt(item.get("sourceStartAnchor") or item.get("source_start_anchor"), 160),
            "sourceEndAnchor": _compact_source_excerpt(item.get("sourceEndAnchor") or item.get("source_end_anchor"), 160, keep_tail=True),
            "sourceFactText": _compact_story_text(
                item.get("sourceFactText")
                or item.get("source_fact_text")
                or item.get("originalFactText")
                or item.get("original_fact_text"),
                420,
            ),
            "sourceRefs": copy.deepcopy(item.get("sourceRefs") or item.get("source_refs") or []),
            "reason": _compact_text(item.get("reason") or item.get("splitReason") or item.get("split_reason"), 220),
            "splitReason": _compact_text(item.get("splitReason") or item.get("split_reason") or item.get("reason"), 220),
        }
        if include_asset_hints:
            compact_item["assetHints"] = copy.deepcopy(item.get("assetHints") or item.get("asset_hints") or {})
            asset_bindings = item.get("assetBindings") or item.get("asset_bindings")
            if isinstance(asset_bindings, list):
                compact_item["assetBindings"] = copy.deepcopy(asset_bindings[:24])
        compact_items.append({key: value for key, value in compact_item.items() if value not in (None, "", [], {})})
    return {
        "episodeId": str(value.get("episodeId") or value.get("episode_id") or "").strip(),
        "episodeTitle": _compact_text(value.get("episodeTitle") or value.get("episode_title") or value.get("title"), 80),
        "count": int(value.get("count") or len(items) or 0),
        "contextProvenance": copy.deepcopy(
            value.get("contextProvenance") or value.get("context_provenance") or {}
        ),
        "items": compact_items,
    }


def _source_window_for_range(
    project_id: str,
    source_id: str,
    absolute_start: int,
    absolute_end: int,
) -> dict[str, Any]:
    requested_end = max(absolute_start, absolute_end)
    cursor = absolute_start
    parts: list[str] = []
    chunks: list[dict[str, Any]] = []
    last_window: dict[str, Any] | None = None
    while cursor < requested_end:
        length = min(20000, requested_end - cursor)
        window = read_source_window(project_id, source_id, None, cursor, length)
        last_window = window
        window_start = int(window.get("absoluteStart") or cursor)
        window_end = int(window.get("absoluteEnd") or window_start)
        text = str(window.get("text") or "")
        if window_end <= cursor:
            raise ValueError("读取资产原文范围失败，窗口没有前进")
        if window_end > requested_end:
            text = text[: max(0, requested_end - window_start)]
            window_end = requested_end
        parts.append(text)
        chunks.append(
            {
                "sourceId": window.get("sourceId"),
                "absoluteStart": window_start,
                "absoluteEnd": window_end,
                "length": content_char_count(text),
            }
        )
        cursor = window_end
    if cursor < requested_end:
        raise ValueError("读取资产原文范围失败，未覆盖完整范围")
    return {
        **(last_window or {}),
        "sourceId": source_id,
        "absoluteStart": absolute_start,
        "absoluteEnd": requested_end,
        "length": content_char_count("".join(parts)),
        "hasAfter": bool((last_window or {}).get("hasAfter")),
        "text": "".join(parts),
        "chunks": chunks,
    }


def _asset_adjacent_source_context(
    project_id: str,
    source_id: str,
    absolute_start: int,
    absolute_end: int,
    *,
    window_chars: int = 1000,
    include_after: bool = True,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if absolute_start > 0:
        before_start = max(0, absolute_start - window_chars)
        try:
            before = read_source_window(
                project_id,
                source_id,
                None,
                before_start,
                absolute_start - before_start,
            )
        except (FileNotFoundError, ValueError):
            before = {}
        before_text = str(before.get("text") or "")
        if before_text:
            result["before"] = {
                "sourceId": source_id,
                "absoluteStart": int(before.get("absoluteStart") or before_start),
                "absoluteEnd": int(before.get("absoluteEnd") or absolute_start),
                "text": before_text,
                "purpose": "只用于消解当前范围开头的身份、别名、地点和连续物件，不得从这里新增本范围未出现的资产。",
            }
    after: dict[str, Any] = {}
    if include_after:
        try:
            after = read_source_window(project_id, source_id, None, absolute_end, window_chars)
        except (FileNotFoundError, ValueError):
            after = {}
    after_text = str(after.get("text") or "")
    if after_text:
        result["after"] = {
            "sourceId": source_id,
            "absoluteStart": int(after.get("absoluteStart") or absolute_end),
            "absoluteEnd": int(after.get("absoluteEnd") or absolute_end + len(after_text)),
            "text": after_text,
            "purpose": "只用于确认当前范围资产的身份延续、后续用途和命名，不得提前抽取仅在后文出现的资产。",
        }
    return result
