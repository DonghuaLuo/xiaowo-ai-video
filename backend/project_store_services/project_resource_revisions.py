# -*- coding: utf-8 -*-
"""项目 JSON 资源写入保护、修订快照和补丁操作。"""
from __future__ import annotations

from .source_text_store import _sha256_text
from .store_core import _deep_merge
from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json
from pathlib import Path
from typing import Any
import copy
import json
import re
import uuid


def _payload_first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload.get(key)
    return None


def _payload_first_present_from_sources(sources: list[dict[str, Any]], *keys: str) -> Any:
    for source in sources:
        if not isinstance(source, dict):
            continue
        value = _payload_first_present(source, *keys)
        if value is not None:
            return value
    return None


def _payload_first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _payload_first_int(*values: Any) -> int | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _json_hash(value: Any) -> str:
    return _sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _resource_revision_value(document: Any) -> int:
    if isinstance(document, dict):
        for key in ("revision", "version"):
            value = document.get(key)
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue
    return 0


def _assert_resource_write_guard(document: Any, expected_revision: Any = None, base_hash: Any = None) -> None:
    if expected_revision is not None and str(expected_revision).strip():
        current_revision = _resource_revision_value(document)
        try:
            expected = int(expected_revision)
        except (TypeError, ValueError) as exc:
            raise ValueError("expectedRevision 必须是数字") from exc
        if current_revision != expected:
            raise ValueError(f"资源版本已变化，当前 revision={current_revision}，收到 expectedRevision={expected}")
    if base_hash is not None and str(base_hash).strip():
        current_hash = _json_hash(document)
        if str(base_hash).strip() != current_hash:
            raise ValueError("资源内容已变化，baseHash 不匹配")


def _project_json_resource_path(project_id: str, payload: dict[str, Any]) -> tuple[Path, str]:
    from .agent_sessions import _project_dir
    from .projects import _is_path_within
    project_dir = _project_dir(project_id)
    raw_relative = str(payload.get("relativePath") or payload.get("relative_path") or "").strip()
    if raw_relative:
        path = (project_dir / raw_relative).resolve()
        if not _is_path_within(path, project_dir) or path.suffix.lower() != ".json":
            raise ValueError("项目资源路径无效")
        relative = raw_relative.replace("\\", "/").strip("/")
        _assert_project_json_resource_is_patchable(relative)
        return path, relative
    resource = str(payload.get("resource") or payload.get("resourceType") or payload.get("resource_type") or "").strip()
    if resource in {
        "sourceCoverage",
        "coverage",
        "episodeSourceRef",
        "sourceRef",
        "sourceIndex",
        "source_index",
        "boundaryPlan",
        "episodeBoundaryPlan",
    }:
        raise ValueError("原文拆分账本由专用工具维护，请使用 get_source_coverage、propose_* 和 commit_* 流程")
    if resource in {"workChainPlan", "episodeWorkChainPlan"}:
        raise ValueError("工作链计划请使用 save_episode_work_chain_plan 或 patch_shot_prompt，避免绕过 sourceRefs 校验")
    if resource in {"workflow", "canvasWorkflow"}:
        raise ValueError("画布结构请使用 upsert_workflow_node、delete_workflow_node；任务卡字段和生成配置请使用 save_workflow_node_inline_edit")
    if resource in {"assets", "assetStore"}:
        raise ValueError("资产请使用 save_asset_batch、upsert_asset 或 delete_asset，避免绕过资产范围校验")
    if resource in {"config", "projectConfig", "settings"}:
        raise ValueError("项目配置请使用 update_project_settings，避免绕过配置归一化和 source coverage 目标同步")
    mapping = {
        "project": "project.json",
        "projectMeta": "project.json",
        "meta": "project.json",
        "storyWorld": "story_world.json",
    }
    if resource not in mapping:
        raise ValueError("未知项目资源")
    relative = mapping[resource]
    return project_dir / relative, relative


def _assert_project_json_resource_is_patchable(relative: str) -> None:
    normalized = relative.replace("\\", "/").strip("/")
    normalized_key = normalized.casefold()
    if normalized_key == "config.json":
        raise ValueError("项目配置请使用 update_project_settings，避免绕过配置归一化和 source coverage 目标同步")
    protected = {
        "source_coverage.json",
        "source_index.json",
        "sources/sources.json",
        "episode_boundary_plan.json",
        "assets/assets.json",
    }
    protected_episode_json = re.fullmatch(r"episodes/[^/]+/(source_ref|work_chain_plan|workflow)\.json", normalized_key)
    if normalized_key in protected or protected_episode_json:
        raise ValueError("该资源由专用工具维护，请使用分集、资产、分镜或画布专用 MCP 方法")


def _resource_revisions_path(project_id: str) -> Path:
    from .agent_sessions import _project_dir
    return _project_dir(project_id) / "versions" / "resource_revisions.json"


def _append_resource_revision(
    project_id: str,
    *,
    resource: str,
    relative_path: str,
    document: Any,
    reason: str = "",
    user_instruction: str = "",
) -> dict[str, Any]:
    from .agent_sessions import _persistent_media_data_removed
    revisions = _read_json(_resource_revisions_path(project_id), [])
    if not isinstance(revisions, list):
        revisions = []
    revision = {
        "id": f"resource-revision-{uuid.uuid4().hex[:10]}",
        "resource": resource,
        "relativePath": relative_path,
        "documentHash": _json_hash(_persistent_media_data_removed(document)),
        "documentRevision": _resource_revision_value(document),
        "reason": reason,
        "userInstruction": user_instruction,
        "createdAt": _now(),
        "document": _persistent_media_data_removed(document),
    }
    revisions.append(revision)
    _write_json(_resource_revisions_path(project_id), revisions[-120:])
    return revision


def _json_pointer_tokens(path: Any) -> list[str]:
    text = str(path or "")
    if not text:
        return []
    if text.startswith("/"):
        return [item.replace("~1", "/").replace("~0", "~") for item in text.split("/")[1:]]
    return [item for item in text.split(".") if item]


def _container_for_pointer(document: Any, tokens: list[str], *, create: bool = False) -> tuple[Any, str | None]:
    if not tokens:
        return None, None
    current = document
    for token in tokens[:-1]:
        if isinstance(current, list):
            index = len(current) if token == "-" else int(token)
            if index >= len(current):
                if not create:
                    raise KeyError(token)
                current.extend({} for _ in range(index - len(current) + 1))
            current = current[index]
        elif isinstance(current, dict):
            if token not in current:
                if not create:
                    raise KeyError(token)
                current[token] = {}
            current = current[token]
        else:
            raise ValueError("patch 路径无法定位")
    return current, tokens[-1]


def _apply_json_patch_op(document: Any, op: dict[str, Any]) -> Any:
    action = str(op.get("op") or op.get("type") or "merge").strip()
    if action == "set":
        action = "replace"
    tokens = _json_pointer_tokens(op.get("path") or op.get("pointer") or "")
    value = copy.deepcopy(op.get("value"))
    if not tokens:
        if action in {"replace", "add"}:
            return value
        if action == "append":
            if not isinstance(document, list):
                raise ValueError("根节点 append 需要数组")
            document.append(value)
            return document
        if action == "merge":
            if not isinstance(document, dict) or not isinstance(value, dict):
                raise ValueError("根节点 merge 需要对象")
            return _deep_merge(document, value)
        if action == "remove":
            return {}
        raise ValueError("不支持的 patch 操作")
    parent, key = _container_for_pointer(document, tokens, create=action in {"add", "append", "merge"})
    if key is None:
        return document
    if isinstance(parent, list):
        index = len(parent) if key == "-" else int(key)
        if action in {"add", "append"}:
            if index > len(parent):
                raise IndexError(key)
            if action == "append":
                parent.append(value)
            else:
                parent.insert(index, value)
        elif action == "replace":
            parent[index] = value
        elif action == "merge":
            if not isinstance(parent[index], dict) or not isinstance(value, dict):
                raise ValueError("数组项 merge 需要对象")
            parent[index] = _deep_merge(parent[index], value)
        elif action == "remove":
            parent.pop(index)
        else:
            raise ValueError("不支持的 patch 操作")
        return document
    if not isinstance(parent, dict):
        raise ValueError("patch 路径无法定位")
    if action in {"add", "replace"}:
        parent[key] = value
    elif action == "append":
        current = parent.setdefault(key, [])
        if not isinstance(current, list):
            raise ValueError("append 目标需要数组")
        current.append(value)
    elif action == "merge":
        current = parent.get(key)
        parent[key] = _deep_merge(current if isinstance(current, dict) else {}, value if isinstance(value, dict) else {})
    elif action == "remove":
        parent.pop(key, None)
    else:
        raise ValueError("不支持的 patch 操作")
    return document


def create_resource_revision(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    path, relative = _project_json_resource_path(project_id, payload)
    document = _read_json(path, {})
    revision = _append_resource_revision(
        project_id,
        resource=str(payload.get("resource") or payload.get("resourceType") or relative),
        relative_path=relative,
        document=document,
        reason=str(payload.get("reason") or ""),
        user_instruction=str(payload.get("userInstruction") or payload.get("user_instruction") or ""),
    )
    return {"success": True, "revision": revision}


def patch_project_resource(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from .projects import _touch_project_meta
    path, relative = _project_json_resource_path(project_id, payload)
    document = _read_json(path, {})
    _assert_resource_write_guard(
        document,
        _payload_first_present(payload, "expectedRevision", "expected_revision"),
        _payload_first_present(payload, "baseHash", "base_hash"),
    )
    before = copy.deepcopy(document)
    operations = payload.get("operations") or payload.get("ops")
    if not isinstance(operations, list):
        operations = [
            {
                "op": payload.get("op") or payload.get("operation") or "merge",
                "path": payload.get("path") or "",
                "value": payload.get("value") if "value" in payload else payload.get("patch") or {},
            }
        ]
    next_document = copy.deepcopy(document)
    for op in operations:
        if not isinstance(op, dict):
            raise ValueError("patch operation 必须是对象")
        next_document = _apply_json_patch_op(next_document, op)
    if isinstance(next_document, dict):
        next_document["revision"] = _resource_revision_value(before) + 1
        next_document["updatedAt"] = _now()
    revision = _append_resource_revision(
        project_id,
        resource=str(payload.get("resource") or payload.get("resourceType") or relative),
        relative_path=relative,
        document=before,
        reason=str(payload.get("reason") or ""),
        user_instruction=str(payload.get("userInstruction") or payload.get("user_instruction") or ""),
    )
    _write_json(path, next_document)
    _touch_project_meta(project_id)
    return {
        "success": True,
        "document": next_document,
        "revision": revision,
        "resourceHash": _json_hash(next_document),
        "resourceRevision": _resource_revision_value(next_document),
        "changedResources": [str(payload.get("resource") or relative)],
        "projectChanged": True,
    }
