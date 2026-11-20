# -*- coding: utf-8 -*-
"""扩展资料路由、候选关联片段和资料摘要。"""
from __future__ import annotations

import copy
import json
import re
import unicodedata
from .agent_sessions import (
    _project_dir,
)
from .source_text_store import _compact_text
from .store_core import (
    _filter_asset_store_by_lifecycle,
    _read_json,
)
from .worker_asset_candidates import (
    _analyze_assets_asset_type_key,
    _analyze_assets_candidate_id,
    _analyze_assets_candidate_id_key,
    _analyze_assets_candidate_needs_design,
    _analyze_assets_design_rows_for_type,
)
from .worker_asset_context import (
    _compact_analyze_assets_material_digest_for_prompt,
)
from .worker_asset_contract import (
    _ASSET_CONTEXT_FILE_CATALOG_LIMIT,
    _ASSET_CONTEXT_FILE_READ_MAX_CHARS,
    _ASSET_CONTEXT_SNIPPET_CHARS,
    _ASSET_CONTEXT_SNIPPET_LIMIT,
    _ASSET_CONTEXT_SNIPPET_TOTAL_CHARS,
    _ASSET_CONTEXT_TEXT_SUFFIXES,
    _ASSET_MATERIAL_DIGEST_FILE_CHARS,
    _ASSET_MATERIAL_DIGEST_FILE_LIMIT_PER_TYPE,
    _ASSET_MATERIAL_DIGEST_TOTAL_CHARS,
    _ASSET_MATERIAL_ROUTE_LIMIT_PER_TYPE,
    _ASSET_TYPES,
)
from .worker_text import (
    _compact_analyze_assets_brief_list,
    _compact_text_head_tail,
    _json_chars,
)
from pathlib import (
    Path,
)
from typing import (
    Any,
)


def _normalize_analyze_assets_material_digest(
    value: dict[str, Any],
    candidates: dict[str, Any],
    *,
    asset_type: str,
    material_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    valid_candidate_ids = {
        str(row.get("candidateId") or "").strip(): str(row.get("name") or "").strip()
        for row in _analyze_assets_material_candidate_refs(
            candidates,
            asset_types=(asset_type,),
            needs_design_only=True,
        ).get(asset_type, [])
        if str(row.get("candidateId") or "").strip()
    }
    valid_paths = {
        str(row.get("relativePath") or "").strip()
        for row in material_entries
        if isinstance(row, dict) and str(row.get("relativePath") or "").strip()
    }
    rows = (value.get("digests") or value.get("items")) if isinstance(value, dict) else []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        candidate_id = str(row.get("candidateId") or row.get("candidate_id") or "").strip()
        if candidate_id not in valid_candidate_ids or candidate_id in seen:
            continue
        if not isinstance(row.get("matched"), bool):
            continue
        seen.add(candidate_id)
        matched = row.get("matched") is True
        digest = _compact_text(row.get("materialDigest") or row.get("summary"), 520)
        identity_facts = _compact_analyze_assets_brief_list(row.get("identityFacts"), limit=6, item_limit=80)
        visual_facts = _compact_analyze_assets_brief_list(row.get("visualFacts"), limit=8, item_limit=90)
        constraints = _compact_analyze_assets_brief_list(row.get("constraints"), limit=6, item_limit=90)
        refs: list[dict[str, str]] = []
        for ref in row.get("sourceMaterialRefs") if isinstance(row.get("sourceMaterialRefs"), list) else []:
            if not isinstance(ref, dict):
                continue
            relative_path = str(ref.get("relativePath") or "").strip()
            if relative_path not in valid_paths:
                continue
            refs.append(
                {
                    "relativePath": relative_path,
                    "matchedText": _compact_text(ref.get("matchedText") or ref.get("text"), 100),
                }
            )
            if len(refs) >= 3:
                break
        item = {
            "candidateId": candidate_id,
            "assetName": valid_candidate_ids.get(candidate_id) or _compact_text(row.get("assetName"), 60),
            "matched": matched,
            "materialDigest": digest,
            "identityFacts": identity_facts,
            "visualFacts": visual_facts,
            "constraints": constraints,
            "sourceMaterialRefs": refs,
        }
        result.append({key: value for key, value in item.items() if value not in (None, "", [], {})})
    missing_ids = [candidate_id for candidate_id in valid_candidate_ids if candidate_id not in seen]
    if missing_ids:
        raise ValueError(f"资料摘要未完整核验候选，缺少有效 matched 状态：{', '.join(missing_ids)}")
    return result


def _analyze_assets_material_digests_for_candidates(
    context: dict[str, Any],
    candidates: dict[str, Any],
    *,
    asset_types: tuple[str, ...] | list[str],
) -> dict[str, list[dict[str, Any]]]:
    raw = context.get("assetMaterialDigests")
    if not isinstance(raw, dict) or not isinstance(candidates, dict):
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for asset_type in asset_types:
        if asset_type not in _ASSET_TYPES:
            continue
        valid_ids = {
            _analyze_assets_candidate_id_key(row.get("candidateId") or row.get("candidate_id"))
            for row in _analyze_assets_design_rows_for_type(candidates, asset_type)
            if isinstance(row, dict)
        }
        rows = raw.get(asset_type)
        selected: list[dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            candidate_key = _analyze_assets_candidate_id_key(row.get("candidateId") or row.get("candidate_id"))
            if valid_ids and candidate_key not in valid_ids:
                continue
            compacted = _compact_analyze_assets_material_digest_for_prompt(row)
            if not compacted:
                continue
            selected.append(compacted)
        if selected:
            result[asset_type] = selected
    return result


def _asset_context_file_catalog(project_id: str, *, limit: int = _ASSET_CONTEXT_FILE_CATALOG_LIMIT) -> dict[str, Any]:
    project_root = _project_dir(project_id)
    candidates: list[tuple[str, str]] = [("assets/assets.json", "existingAssets")]
    materials_root = project_root / "sources" / "materials"
    if materials_root.exists():
        for path in sorted(materials_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if path.is_file():
                try:
                    relative_path = path.resolve().relative_to(project_root).as_posix()
                except ValueError:
                    continue
                candidates.append((relative_path, "extensionMaterial"))
    files: list[dict[str, Any]] = []
    for relative_path, kind in candidates:
        path = project_root / relative_path
        if not path.exists() or not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append(
            {
                "relativePath": relative_path,
                "name": path.name,
                "suffix": path.suffix.lower(),
                "size": stat.st_size,
                "kind": kind,
            }
        )
        if len(files) >= limit:
            break
    return {
        "scope": "asset_context",
        "files": files,
        "truncated": len(candidates) > len(files),
    }


def _asset_context_match_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold()


def _asset_context_candidate_terms(candidates: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def push(value: Any) -> None:
        text = str(value or "").strip()
        if len(text) < 2 or len(text) > 60:
            return
        normalized = _asset_context_match_text(text)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        terms.append(text)

    def walk(value: Any, key: str = "") -> None:
        normalized_key = key.strip()
        if isinstance(value, dict):
            if any(candidate_key in value for candidate_key in ("candidateId", "candidate_id", "name", "assetId", "decision", "needsDesign")):
                if not _analyze_assets_candidate_needs_design(value):
                    return
                for candidate_key in ("name", "originalName", "aliasName", "assetName", "asset_name", "mention"):
                    push(value.get(candidate_key))
                aliases = value.get("aliases")
                if isinstance(aliases, list):
                    for alias in aliases[:4]:
                        push(alias)
                return
            for child_key, child_value in value.items():
                walk(child_value, str(child_key))
            return
        if isinstance(value, list):
            for item in value:
                walk(item, key)
            return
        if isinstance(value, str) and key in _ASSET_TYPES:
            push(value)
            return
        if normalized_key in {"name", "mention", "assetName", "asset_name"}:
            push(value)

    walk(candidates if isinstance(candidates, dict) else {})
    return terms[:24]


def _asset_context_material_paths(project_id: str, catalog: Any) -> list[tuple[str, Path]]:
    project_root = _project_dir(project_id)
    rows: list[str] = []
    if isinstance(catalog, dict) and isinstance(catalog.get("files"), list):
        for row in catalog.get("files") or []:
            if not isinstance(row, dict) or str(row.get("kind") or "") != "extensionMaterial":
                continue
            relative_path = str(row.get("relativePath") or "").strip().replace("\\", "/")
            if relative_path:
                rows.append(relative_path)
    if not rows:
        materials_root = project_root / "sources" / "materials"
        if materials_root.exists():
            for path in sorted(materials_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
                if not path.is_file():
                    continue
                try:
                    rows.append(path.resolve().relative_to(project_root).as_posix())
                except ValueError:
                    continue
    result: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for relative_path in rows:
        normalized = relative_path.strip("/").casefold()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        path = project_root / relative_path
        try:
            resolved = path.resolve()
            resolved.relative_to(project_root.resolve())
        except (OSError, ValueError):
            continue
        if resolved.is_file() and resolved.suffix.lower() in _ASSET_CONTEXT_TEXT_SUFFIXES:
            result.append((relative_path, resolved))
    return result


def _asset_context_read_text(path: Path, *, max_chars: int = 24000) -> str:
    try:
        if path.name == "assets.json" and path.parent.name == "assets":
            data = _read_json(path, {})
            text = json.dumps(
                _filter_asset_store_by_lifecycle(data, "active"),
                ensure_ascii=False,
                indent=2,
            )
        else:
            text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return ""
    return text[:max_chars]


def _asset_context_excerpt(text: str, matched_terms: list[str], *, limit: int = _ASSET_CONTEXT_SNIPPET_CHARS) -> str:
    if not text:
        return ""
    normalized_text = _asset_context_match_text(text)
    positions = [
        normalized_text.find(_asset_context_match_text(term))
        for term in matched_terms
        if _asset_context_match_text(term)
    ]
    positions = [position for position in positions if position >= 0]
    start = max(0, min(positions) - limit // 3) if positions else 0
    excerpt = text[start : start + limit]
    prefix = "..." if start > 0 else ""
    suffix = "..." if start + limit < len(text) else ""
    return _compact_text(f"{prefix}{excerpt}{suffix}", limit + 6)


def _asset_context_snippets_for_candidates(
    project_id: str,
    candidates: dict[str, Any],
    catalog: Any,
) -> list[dict[str, Any]]:
    terms = _asset_context_candidate_terms(candidates)
    if not terms:
        return []
    scored: list[tuple[int, str, list[str], str]] = []
    for relative_path, path in _asset_context_material_paths(project_id, catalog):
        text = _asset_context_read_text(path)
        if not text:
            continue
        file_norm = _asset_context_match_text(relative_path)
        text_norm = _asset_context_match_text(text)
        matched_terms: list[str] = []
        score = 0
        for term in terms:
            term_norm = _asset_context_match_text(term)
            if not term_norm:
                continue
            file_hit = term_norm in file_norm
            text_hit = term_norm in text_norm
            if not file_hit and not text_hit:
                continue
            matched_terms.append(term)
            score += (6 if file_hit else 0) + (3 if text_hit else 0)
        if score:
            scored.append((score, relative_path, matched_terms[:8], text))
    scored.sort(key=lambda row: (-row[0], row[1].casefold()))
    snippets: list[dict[str, Any]] = []
    total_chars = 0
    for score, relative_path, matched_terms, text in scored[:_ASSET_CONTEXT_SNIPPET_LIMIT]:
        excerpt = _asset_context_excerpt(text, matched_terms)
        if not excerpt:
            continue
        if total_chars + len(excerpt) > _ASSET_CONTEXT_SNIPPET_TOTAL_CHARS:
            break
        total_chars += len(excerpt)
        snippets.append(
            {
                "relativePath": relative_path,
                "matchedTerms": matched_terms,
                "excerpt": excerpt,
                "score": score,
            }
        )
    return snippets


def _asset_context_snippets_for_source_mentions(
    project_id: str,
    catalog: Any,
    source_text: str,
    *,
    max_snippets: int = 3,
    excerpt_limit: int = 360,
    total_limit: int = 1400,
    deprioritized_terms: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[dict[str, Any]]:
    source_normalized = _asset_context_match_text(source_text)
    if not source_normalized:
        return []
    deprioritized = {
        _asset_context_match_text(term)
        for term in (deprioritized_terms or [])
        if _asset_context_match_text(term)
    }

    def material_terms_in_source(text: str) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        header_words = {
            "人物",
            "角色",
            "名称",
            "姓名",
            "身份",
            "当前天赋",
            "当前状态",
            "关系",
            "备注",
            "类型",
            "说明",
            "用途",
            "版本",
            "状态",
        }

        def consider(candidate: str) -> None:
            candidate = str(candidate or "").strip("`*_\"'《》| ")
            if not (2 <= len(candidate) <= 24):
                return
            if candidate in header_words:
                return
            if not re.search(r"[\u4e00-\u9fffA-Za-z]", candidate):
                return
            normalized = _asset_context_match_text(candidate)
            if not normalized or normalized in seen or normalized not in source_normalized:
                return
            seen.add(normalized)
            terms.append(candidate)

        for line in str(text or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("|") and stripped.endswith("|"):
                cells = [cell.strip() for cell in stripped.strip("|").split("|")]
                if cells and not set(cells[0]) <= {"-", "—", " "}:
                    consider(cells[0])
            for pattern in (
                r"(?:人物名|角色名|姓名|名称|资产名|规范名)[:：]\s*([^|，,；;\s。]{2,24})",
                r"^[#>\-\*\+\s]*(?:\d+[\.\u3001]\s*)?(?:人物|角色|场景|道具|物件|地点)[:：]\s*([^|，,；;\s。]{2,24})",
            ):
                for match in re.findall(pattern, stripped):
                    consider(match)
            if len(terms) >= 36:
                break
        return sorted(
            terms,
            key=lambda term: (
                1 if _asset_context_match_text(term) in deprioritized else 0,
                source_normalized.find(_asset_context_match_text(term)),
                len(term),
                term,
            ),
        )

    scored: list[tuple[int, str, list[str], str]] = []
    for relative_path, path in _asset_context_material_paths(project_id, catalog):
        text = _asset_context_read_text(path)
        terms = material_terms_in_source(text)
        if not terms:
            continue
        file_norm = _asset_context_match_text(relative_path)
        for index, term in enumerate(terms[:6]):
            term_norm = _asset_context_match_text(term)
            score = (12 if term_norm not in deprioritized else 4) - index
            if term_norm in file_norm:
                score += 3
            scored.append((score, relative_path, [term], text))
    scored.sort(key=lambda row: (-row[0], row[1].casefold()))

    snippets: list[dict[str, Any]] = []
    total_chars = 0
    for score, relative_path, matched_terms, text in scored[:max_snippets]:
        excerpt = _asset_context_excerpt(text, matched_terms, limit=excerpt_limit)
        if not excerpt:
            continue
        if total_chars + len(excerpt) > total_limit:
            break
        total_chars += len(excerpt)
        snippets.append(
            {
                "relativePath": relative_path,
                "matchedTerms": matched_terms[:8],
                "excerpt": excerpt,
                "score": score,
                "source": "sourceTextMention",
            }
        )
    return snippets


def _asset_context_catalog_extension_files(catalog: Any) -> list[dict[str, Any]]:
    if not isinstance(catalog, dict) or not isinstance(catalog.get("files"), list):
        return []
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in catalog.get("files") or []:
        if not isinstance(row, dict) or str(row.get("kind") or "") != "extensionMaterial":
            continue
        relative_path = str(row.get("relativePath") or "").strip().replace("\\", "/")
        if not relative_path or relative_path.casefold() in seen:
            continue
        if row.get("size") == 0:
            continue
        seen.add(relative_path.casefold())
        files.append({"relativePath": relative_path})
    return files


def _analyze_assets_material_candidate_refs(
    candidates: dict[str, Any],
    *,
    asset_types: tuple[str, ...] | list[str] | None = None,
    needs_design_only: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    selected = tuple(asset_type for asset_type in (asset_types or _ASSET_TYPES) if asset_type in _ASSET_TYPES)
    result: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(candidates, dict):
        return result
    for asset_type in selected:
        rows = candidates.get(asset_type)
        refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            if needs_design_only and not _analyze_assets_candidate_needs_design(row):
                continue
            candidate_id = _analyze_assets_candidate_id(row)
            name = str(row.get("name") or row.get("originalName") or "").strip()
            if not candidate_id or not name:
                continue
            key = _analyze_assets_candidate_id_key(candidate_id) or name.casefold()
            if key in seen:
                continue
            seen.add(key)
            aliases = [
                str(alias or "").strip()
                for alias in (row.get("aliases") if isinstance(row.get("aliases"), list) else [])
                if str(alias or "").strip()
            ][:4]
            refs.append(
                {
                    "candidateId": candidate_id,
                    "name": name,
                    **({"originalName": str(row.get("originalName") or "").strip()} if str(row.get("originalName") or "").strip() and str(row.get("originalName") or "").strip() != name else {}),
                    **({"aliases": aliases} if aliases else {}),
                }
            )
        result[asset_type] = refs
    return result


def _normalize_analyze_assets_material_routing(
    value: dict[str, Any],
    candidates: dict[str, Any],
    catalog: Any,
) -> dict[str, Any]:
    extension_files = _asset_context_catalog_extension_files(catalog)
    valid_paths = {str(row.get("relativePath") or "").strip(): row for row in extension_files}
    candidate_refs = _analyze_assets_material_candidate_refs(candidates, needs_design_only=True)
    candidates_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    candidates_by_name: dict[tuple[str, str], dict[str, Any]] = {}
    for asset_type, rows in candidate_refs.items():
        for row in rows:
            candidate_id = str(row.get("candidateId") or "").strip()
            if candidate_id:
                candidates_by_id[_analyze_assets_candidate_id_key(candidate_id)] = (asset_type, row)
            for name in [row.get("name"), row.get("originalName"), *(row.get("aliases") if isinstance(row.get("aliases"), list) else [])]:
                name_key = str(name or "").strip().casefold()
                if name_key:
                    candidates_by_name[(asset_type, name_key)] = row
    routes_by_type: dict[str, list[dict[str, Any]]] = {asset_type: [] for asset_type in _ASSET_TYPES}
    seen: set[tuple[str, str, str]] = set()
    rows = value.get("routes") if isinstance(value, dict) else []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        relative_path = str(row.get("relativePath") or row.get("path") or "").strip().replace("\\", "/")
        if relative_path not in valid_paths:
            continue
        relevance = str(row.get("relevance") or "medium").strip().lower()
        if relevance not in {"high", "medium", "low"}:
            continue
        raw_types: list[Any] = []
        if isinstance(row.get("assetTypes"), list):
            raw_types.extend(row.get("assetTypes") or [])
        raw_types.extend([row.get("assetType"), row.get("type")])
        asset_types = [
            normalized
            for normalized in (_analyze_assets_asset_type_key(item) for item in raw_types)
            if normalized in _ASSET_TYPES
        ]
        candidate_ids: list[str] = []
        asset_names: list[str] = []
        for value_id in row.get("candidateIds") if isinstance(row.get("candidateIds"), list) else []:
            candidate_key = _analyze_assets_candidate_id_key(value_id)
            match = candidates_by_id.get(candidate_key)
            if not match:
                continue
            matched_type, candidate = match
            if matched_type not in asset_types:
                asset_types.append(matched_type)
            candidate_id = str(candidate.get("candidateId") or "").strip()
            if candidate_id and candidate_id not in candidate_ids:
                candidate_ids.append(candidate_id)
            name = str(candidate.get("name") or "").strip()
            if name and name not in asset_names:
                asset_names.append(name)
        for name_value in row.get("assetNames") if isinstance(row.get("assetNames"), list) else []:
            name = str(name_value or "").strip()
            if not name:
                continue
            if name not in asset_names:
                asset_names.append(name)
            for asset_type in asset_types or _ASSET_TYPES:
                candidate = candidates_by_name.get((asset_type, name.casefold()))
                if not candidate:
                    continue
                candidate_id = str(candidate.get("candidateId") or "").strip()
                if candidate_id and candidate_id not in candidate_ids:
                    candidate_ids.append(candidate_id)
        if not asset_types:
            continue
        for asset_type in asset_types:
            key = (asset_type, relative_path, "|".join(sorted(candidate_ids)))
            if key in seen:
                continue
            seen.add(key)
            routes_by_type[asset_type].append(
                {
                    "relativePath": relative_path,
                    "assetType": asset_type,
                    "candidateIds": candidate_ids[:12],
                    "assetNames": asset_names[:12],
                    "relevance": relevance,
                    "reason": _compact_text(row.get("reason"), 90),
                }
            )
    for asset_type in _ASSET_TYPES:
        routes_by_type[asset_type] = routes_by_type[asset_type][:_ASSET_MATERIAL_ROUTE_LIMIT_PER_TYPE]
    return {
        "mode": "model_filename_routing",
        "routesByType": routes_by_type,
        "routeCount": sum(len(rows) for rows in routes_by_type.values()),
        "fileCount": len(extension_files),
        "warnings": [
            _compact_text(item, 120)
            for item in (value.get("warnings") if isinstance(value, dict) and isinstance(value.get("warnings"), list) else [])
            if _compact_text(item, 120)
        ][:8],
    }


def _analyze_assets_material_routes_for_type(context: dict[str, Any], asset_type: str) -> list[dict[str, Any]]:
    routing = context.get("assetMaterialRouting") if isinstance(context.get("assetMaterialRouting"), dict) else {}
    routes_by_type = routing.get("routesByType") if isinstance(routing.get("routesByType"), dict) else {}
    rows = routes_by_type.get(asset_type)
    return [copy.deepcopy(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _asset_material_candidate_terms(
    candidates: dict[str, Any],
    asset_type: str,
    routes: list[dict[str, Any]],
) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def push(value: Any) -> None:
        text = str(value or "").strip()
        if len(text) < 2 or len(text) > 60:
            return
        key = _asset_context_match_text(text)
        if not key or key in seen:
            return
        seen.add(key)
        terms.append(text)

    for row in _analyze_assets_design_rows_for_type(candidates, asset_type):
        push(row.get("name"))
        push(row.get("originalName"))
        for alias in row.get("aliases") if isinstance(row.get("aliases"), list) else []:
            push(alias)
    for route in routes:
        for name in route.get("assetNames") if isinstance(route.get("assetNames"), list) else []:
            push(name)
    return terms[:24]


def _asset_material_excerpt_for_terms(text: str, terms: list[str], *, limit: int) -> str:
    if not text:
        return ""
    lowered = text.casefold()
    windows: list[tuple[int, int]] = []
    window_chars = max(520, min(1200, limit // 3))
    for term in terms:
        needle = str(term or "").strip()
        if not needle:
            continue
        start_at = 0
        needle_lower = needle.casefold()
        while True:
            index = lowered.find(needle_lower, start_at)
            if index < 0:
                break
            start = max(0, index - window_chars // 2)
            end = min(len(text), index + len(needle) + window_chars // 2)
            windows.append((start, end))
            start_at = index + max(1, len(needle))
            if len(windows) >= 8:
                break
        if len(windows) >= 8:
            break
    if not windows:
        return ""
    windows.sort()
    merged: list[tuple[int, int]] = []
    for start, end in windows:
        if not merged or start > merged[-1][1] + 80:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    parts: list[str] = []
    total = 0
    for start, end in merged:
        part = text[start:end].strip()
        if not part:
            continue
        marker_prefix = "..." if start > 0 else ""
        marker_suffix = "..." if end < len(text) else ""
        part = f"{marker_prefix}{part}{marker_suffix}"
        if total + len(part) > limit and parts:
            break
        parts.append(part)
        total += len(part)
    return _compact_text("\n...\n".join(parts), limit)


def _asset_context_material_entries_for_type(
    project_id: str,
    context: dict[str, Any],
    candidates: dict[str, Any],
    asset_type: str,
    routes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not routes:
        return []
    path_map = {
        relative_path: path
        for relative_path, path in _asset_context_material_paths(project_id, context.get("assetContextFileCatalog"))
    }
    terms = _asset_material_candidate_terms(candidates, asset_type, routes)
    selected: list[dict[str, Any]] = []
    total_chars = 0
    seen: set[str] = set()
    relevance_rank = {"high": 0, "medium": 1, "low": 2}
    sorted_routes = sorted(
        routes,
        key=lambda row: (
            relevance_rank.get(str(row.get("relevance") or "").lower(), 1),
            str(row.get("relativePath") or "").casefold(),
        ),
    )
    for route in sorted_routes:
        relative_path = str(route.get("relativePath") or "").strip().replace("\\", "/")
        if not relative_path or relative_path.casefold() in seen:
            continue
        path = path_map.get(relative_path)
        if not path:
            continue
        text = _asset_context_read_text(
            path,
            max_chars=max(_ASSET_MATERIAL_DIGEST_TOTAL_CHARS * 3, _ASSET_CONTEXT_FILE_READ_MAX_CHARS),
        )
        if not text:
            continue
        excerpt = _asset_material_excerpt_for_terms(text, terms, limit=_ASSET_MATERIAL_DIGEST_FILE_CHARS)
        content_match_mode = "candidate_term_window"
        routed_candidate_ids = [
            str(item or "").strip()
            for item in (route.get("candidateIds") if isinstance(route.get("candidateIds"), list) else [])
            if str(item or "").strip()
        ][:12]
        routed_asset_names = [
            str(item or "").strip()
            for item in (route.get("assetNames") if isinstance(route.get("assetNames"), list) else [])
            if str(item or "").strip()
        ][:12]
        if not excerpt:
            relevance = str(route.get("relevance") or "medium").strip().lower()
            if (routed_candidate_ids or routed_asset_names) and relevance in {"high", "medium"}:
                excerpt = _compact_text_head_tail(text, min(_ASSET_MATERIAL_DIGEST_FILE_CHARS, 1400))
                content_match_mode = "explicit_candidate_filename_route_brief"
        if not excerpt:
            continue
        row = {
            "relativePath": relative_path,
            "routedCandidateIds": routed_candidate_ids,
            "routedAssetNames": routed_asset_names,
            "relevance": str(route.get("relevance") or "medium").strip(),
            "contentMatchMode": content_match_mode,
            "contentExcerpt": excerpt,
        }
        row_chars = _json_chars(row)
        if selected and total_chars + row_chars > _ASSET_MATERIAL_DIGEST_TOTAL_CHARS:
            break
        selected.append(row)
        total_chars += row_chars
        seen.add(relative_path.casefold())
        if len(selected) >= _ASSET_MATERIAL_DIGEST_FILE_LIMIT_PER_TYPE:
            break
    return selected
