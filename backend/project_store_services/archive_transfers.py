# -*- coding: utf-8 -*-
"""Homepage ZIP backup/restore and Jianying draft background exports."""

from __future__ import annotations
from .canvas_ownership import VIDEO_TASK_NODE_TYPES

import configparser
import copy
import json
import math
import os
import platform
import re
import shutil
import sqlite3
import tempfile
import threading
import traceback
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .catalogs import (
    DEFAULT_ASSETS,
    DEFAULT_MODEL_CAPABILITIES,
    DEFAULT_TEXT_REPLACEMENT_RULES,
    GLOBAL_ASSET_MEDIA_DIR,
    GLOBAL_ASSETS_PATH,
    DATA_DIR,
    GLOBAL_CONFIG_PATH,
    GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH,
    GLOBAL_STYLE_REFERENCES_DIR,
    GLOBAL_STYLE_TEMPLATES_PATH,
    GLOBAL_TEXT_REPLACEMENT_RULES_PATH,
    PROJECTS_DIR,
)
from .projects import _save_global_config, list_projects
from .settings_loaders import (
    load_global_config,
    load_script_adaptation_templates,
    load_style_templates,
    load_text_replacement_rules,
)
from .director_rules import (
    GLOBAL_DIRECTOR_RULE_OVERRIDES_PATH,
    _load_director_rule_overrides,
    _save_director_rule_overrides,
    normalize_director_rule_identifier,
)
from .provider_models import (
    _find_model,
    _model_capabilities_with_provider_models,
    _normalize_provider_id,
    _provider_service_id,
)
from .storyboard_templates import (
    GLOBAL_STORYBOARD_TEMPLATES_PATH,
    load_storyboard_templates,
)
from .store_core import (
    _GLOBAL_CONFIG_UPDATE_LOCK,
    _JSON_WRITE_LOCK,
    _deep_merge,
    _emit_agent_event,
    _read_json,
    _serialized_global_config_write,
    _write_json,
    ensure_store,
)
from .canvas_store_queries import episode_canvas_exists, read_canvas_workflow_projection_v4
from .canvas_store_documents import list_project_custom_canvases_v4
from .task_contract import _task_failure_fields
from .task_control import _emit_task_update
from .task_control import _get_task
from .task_control import _update_task_fields
from .task_control import _update_task_if_active
from .task_control import create_task
from .task_lifecycle import register_background_task_thread
from .task_lifecycle import unregister_background_task_thread
from .task_storage import _load_tasks_for_project


HOME_ARCHIVE_MANIFEST = "ai-video-export.json"
HOME_ARCHIVE_FORMAT = "ai-video-home-archive"
HOME_ARCHIVE_VERSION = 1
HOME_ARCHIVE_MANIFEST_MAX_BYTES = 16 * 1024 * 1024
HOME_ARCHIVE_MAX_MEMBERS = 200_000
HOME_ARCHIVE_MAX_TOTAL_BYTES = 100 * 1024 * 1024 * 1024
HOME_ARCHIVE_MAX_NON_MEDIA_MEMBER_BYTES = 512 * 1024 * 1024
HOME_ARCHIVE_MAX_MEDIA_MEMBER_BYTES = 32 * 1024 * 1024 * 1024
HOME_ARCHIVE_GLOBAL_SCOPES = {
    "providers",
    "models",
    "scriptAdaptationTemplates",
    "directorRules",
    "textReplacementRules",
    "storyboardTemplates",
}
HOME_ARCHIVE_ASSET_SCOPES = {"characters", "creatures", "scenes", "props", "styles"}
HOME_ARCHIVE_GLOBAL_FILE_PREFIXES = ("asset_media/", "style_references/")
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
STORED_MEDIA_SUFFIXES = VIDEO_SUFFIXES | {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SQLITE_SUFFIXES = {".sqlite", ".sqlite3"}
ACTIVE_TASK_STATUSES = {
    "created",
    "queued",
    "waiting",
    "waiting_upstream",
    "ready",
    "running",
    "processing",
    "paused",
}
IMPORTED_TASK_RESET_MESSAGE = "项目导入后，原未完成任务已停止，不会自动恢复。"
_HOME_ARCHIVE_IMPORT_LOCK = threading.RLock()
_JIANYING_DRAFT_LOCK = threading.RLock()


def _now_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


def _normalized_zip_export_path(value: Any) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ValueError("缺少导出路径")
    path = Path(text).expanduser()
    while path.name.lower().endswith(".zip.zip"):
        path = path.with_name(path.name[:-4])
    if path.suffix.lower() != ".zip":
        path = Path(f"{path}.zip")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _archive_import_path(value: Any) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ValueError("缺少压缩包路径")
    path = Path(text).expanduser()
    if not path.is_file():
        raise FileNotFoundError("导入压缩包不存在")
    if path.suffix.lower() != ".zip":
        raise ValueError("请选择 ZIP 压缩包")
    return path


def _task_cancelled(task_id: str) -> bool:
    task = _get_task(task_id)
    return not task or str(task.get("status") or "") == "cancelled"


def _update_transfer_task(task_id: str, event: str = "task_progress", **fields: Any) -> dict[str, Any] | None:
    fields["updatedAt"] = _now_ms()
    task = _update_task_if_active(task_id, **fields)
    if task:
        _emit_task_update(task, event)
    return task


def _start_background_task(task: dict[str, Any], target: Any, *args: Any) -> None:
    thread = threading.Thread(
        target=target,
        args=(str(task["id"]), *args),
        name=f"ai-video-{task['type']}-{task['id']}",
    )
    register_background_task_thread(str(task["id"]), thread)
    try:
        thread.start()
    except Exception as exc:
        unregister_background_task_thread(str(task["id"]))
        now_ms = _now_ms()
        failed = _update_task_if_active(
            str(task["id"]),
            status="failed",
            progress=0,
            failedAt=now_ms,
            updatedAt=now_ms,
            **_task_failure_fields(str(exc), prefix="启动后台任务失败"),
        )
        _emit_task_update(failed, "task_failed")
        raise


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def _zip_write_file(archive: zipfile.ZipFile, source: Path, arcname: str) -> None:
    compression = zipfile.ZIP_STORED if source.suffix.lower() in STORED_MEDIA_SUFFIXES else zipfile.ZIP_DEFLATED
    archive.write(source, arcname=arcname, compress_type=compression)


def _is_sqlite_database_path(path: Path) -> bool:
    return path.suffix.lower() in SQLITE_SUFFIXES


def _sqlite_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(str(source), timeout=30)
    destination_connection = sqlite3.connect(str(destination), timeout=30)
    try:
        source_connection.execute("PRAGMA busy_timeout = 30000")
        source_connection.backup(destination_connection)
        result = destination_connection.execute("PRAGMA quick_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            raise sqlite3.DatabaseError("SQLite 快照完整性检查失败")
    finally:
        destination_connection.close()
        source_connection.close()


def _project_archive_files(project_id: str, snapshot_root: Path) -> list[tuple[Path, str]]:
    _load_tasks_for_project(project_id)
    root = (PROJECTS_DIR / project_id).resolve()
    if not root.is_dir():
        return []
    files: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        resolved = path.resolve()
        if root != resolved and root not in resolved.parents:
            continue
        relative = path.relative_to(root)
        lower_name = path.name.lower()
        if lower_name.endswith("-wal") or lower_name.endswith("-shm"):
            continue
        source = path
        if _is_sqlite_database_path(path):
            source = snapshot_root / project_id / relative
            _sqlite_backup(path, source)
        elif path.suffix.lower() not in STORED_MEDIA_SUFFIXES:
            source = snapshot_root / project_id / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, source)
        files.append((source, f"projects/{project_id}/{relative.as_posix()}"))
    return files


def _custom_templates(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [
        copy.deepcopy(row)
        for row in rows
        if isinstance(row, dict) and str(row.get("source") or "") != "builtin"
    ]


def _custom_text_replacement_rules(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    default_by_from = {
        str(row.get("from") or ""): str(row.get("to") or "")
        for row in DEFAULT_TEXT_REPLACEMENT_RULES
        if isinstance(row, dict) and str(row.get("from") or "")
    }
    custom_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = str(row.get("from") or "").strip()
        target = str(row.get("to") or "").strip()
        if not source:
            continue
        if source in default_by_from and default_by_from[source] == target:
            continue
        custom_rows.append(copy.deepcopy(row))
    return custom_rows


def _director_rule_overrides_archive_payload() -> list[dict[str, Any]]:
    return [
        copy.deepcopy(row)
        for row in _load_director_rule_overrides().values()
        if isinstance(row, dict)
        and str(row.get("id") or "").strip()
        and (
            str(row.get("description") or "").strip()
            or str(row.get("content") or "").strip()
        )
    ]


def _global_archive_payload(scopes: set[str]) -> dict[str, Any]:
    config = load_global_config()
    payload: dict[str, Any] = {}
    if "providers" in scopes:
        payload["providers"] = copy.deepcopy(config.get("providers") or [])
    if "models" in scopes:
        payload["models"] = {
            "modelConfig": copy.deepcopy(config.get("model_config") or {}),
            "defaults": {
                key: copy.deepcopy((config.get("defaults") or {}).get(key))
                for key in ("models", "storyboard", "video")
                if isinstance(config.get("defaults"), dict) and key in config["defaults"]
            },
        }
    if "scriptAdaptationTemplates" in scopes:
        payload["scriptAdaptationTemplates"] = _custom_templates(
            load_script_adaptation_templates()
        )
    if "directorRules" in scopes:
        payload["directorRules"] = _director_rule_overrides_archive_payload()
    if "textReplacementRules" in scopes:
        payload["textReplacementRules"] = _custom_text_replacement_rules(
            load_text_replacement_rules()
        )
    if "storyboardTemplates" in scopes:
        payload["storyboardTemplates"] = _custom_templates(load_storyboard_templates())
    return payload


def _global_assets_archive_payload(asset_scopes: set[str]) -> dict[str, Any]:
    selected = {scope for scope in asset_scopes if scope in HOME_ARCHIVE_ASSET_SCOPES}
    if not selected:
        return {}
    assets = _read_json(GLOBAL_ASSETS_PATH, copy.deepcopy(DEFAULT_ASSETS))
    if not isinstance(assets, dict):
        assets = copy.deepcopy(DEFAULT_ASSETS)
    exported_assets: dict[str, list[dict[str, Any]]] = {}
    for asset_type in sorted(selected):
        rows = assets.get(asset_type)
        exported_assets[asset_type] = [
            copy.deepcopy(row) for row in rows if isinstance(row, dict)
        ] if isinstance(rows, list) else []
    payload: dict[str, Any] = {
        "assetTypes": sorted(selected),
        "assets": exported_assets,
    }
    if "styles" in selected:
        payload["favoriteStyles"] = [
            copy.deepcopy(row)
            for row in load_style_templates()
            if isinstance(row, dict)
            and (
                str(row.get("category") or "") == "favorite"
                or str(row.get("source") or "") == "favorite"
            )
        ]
    return payload


def _global_archive_files(asset_scopes: set[str]) -> list[tuple[Path, str]]:
    selected = {scope for scope in asset_scopes if scope in HOME_ARCHIVE_ASSET_SCOPES}
    if not selected:
        return []
    roots: list[Path] = []
    for asset_type in sorted(selected):
        roots.append(GLOBAL_ASSET_MEDIA_DIR / asset_type)
    if "styles" in selected:
        roots.append(GLOBAL_STYLE_REFERENCES_DIR)
    files: list[tuple[Path, str]] = []
    global_root = GLOBAL_ASSET_MEDIA_DIR.parent.resolve()
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        resolved_root = root.resolve()
        if global_root != resolved_root and global_root not in resolved_root.parents:
            continue
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            if global_root != resolved and global_root not in resolved.parents:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            relative = resolved.relative_to(global_root).as_posix()
            files.append((path, f"global/{relative}"))
    return files


def _run_home_archive_export(
    task_id: str,
    project_ids: list[str],
    scopes: set[str],
    export_path: Path,
    asset_scopes: set[str] | None = None,
) -> None:
    temp_path = export_path.with_name(f".{export_path.name}.{task_id}.tmp")
    backup_path = export_path.with_name(f".{export_path.name}.{task_id}.backup")
    installed = False
    backup_created = False
    snapshot_root: Path | None = None

    def restore_previous_export() -> None:
        nonlocal installed, backup_created
        if installed and export_path.exists():
            export_path.unlink()
        if backup_created and backup_path.exists():
            os.replace(backup_path, export_path)
        installed = False
        backup_created = False

    try:
        ensure_store()
        asset_scopes = {
            str(item).strip()
            for item in (asset_scopes or set())
            if str(item).strip() in HOME_ARCHIVE_ASSET_SCOPES
        }
        _update_transfer_task(task_id, status="running", progress=3, message="正在准备导出内容。")
        available = {str(row.get("id") or "") for row in list_projects()}
        selected = [project_id for project_id in project_ids if project_id in available]
        global_assets = _global_assets_archive_payload(asset_scopes)
        manifest = {
            "format": HOME_ARCHIVE_FORMAT,
            "version": HOME_ARCHIVE_VERSION,
            "createdAt": datetime.now().astimezone().isoformat(),
            "projectIds": selected,
            "globalScopes": sorted(scopes),
            "globalSettings": _global_archive_payload(scopes),
            "assetScopes": sorted(asset_scopes),
            "globalAssets": global_assets,
        }
        if not selected and not manifest["globalSettings"] and not global_assets:
            raise ValueError("所选项目已不存在，且没有可导出的全局设置或资产库")
        snapshot_root = Path(tempfile.mkdtemp(prefix="ai-video-export-", dir=str(DATA_DIR)))
        files: list[tuple[Path, str]] = []
        with _JSON_WRITE_LOCK:
            for project_id in selected:
                files.extend(_project_archive_files(project_id, snapshot_root))
            files.extend(_global_archive_files(asset_scopes))
        total = max(1, len(files))
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.writestr(HOME_ARCHIVE_MANIFEST, _json_bytes(manifest))
            for index, (source, arcname) in enumerate(files, start=1):
                if _task_cancelled(task_id):
                    return
                _zip_write_file(archive, source, arcname)
                if _task_cancelled(task_id):
                    return
                if index == total or index % 20 == 0:
                    _update_transfer_task(
                        task_id,
                        status="running",
                        progress=min(95, 5 + round(index / total * 90)),
                        message=f"正在打包项目文件 {index}/{total}。",
                    )
        if _task_cancelled(task_id):
            return
        if export_path.exists():
            if not export_path.is_file():
                raise IsADirectoryError(f"导出目标不是文件：{export_path}")
            os.replace(export_path, backup_path)
            backup_created = True
        os.replace(temp_path, export_path)
        installed = True
        completed = _update_transfer_task(
            task_id,
            "task_completed",
            status="completed",
            progress=100,
            message=f"首页导出完成：{export_path}",
            notice="首页项目与全局设置 ZIP 已导出。",
            completedAt=_now_ms(),
            exportPath=str(export_path),
            result={
                "projectIds": selected,
                "globalScopes": sorted(scopes),
                "assetScopes": sorted(asset_scopes),
            },
        )
        if not completed:
            raise _TransferCancelled()
        if backup_created and backup_path.exists():
            try:
                backup_path.unlink()
                backup_created = False
            except OSError:
                print(traceback.format_exc(), flush=True)
        _emit_agent_event("home_archive_completed", completed)
    except _TransferCancelled:
        restore_previous_export()
        return
    except Exception as exc:
        try:
            restore_previous_export()
        except Exception:
            print(traceback.format_exc(), flush=True)
        debug = traceback.format_exc()
        print(debug, flush=True)
        failed = _update_transfer_task(
            task_id,
            "task_failed",
            status="failed",
            progress=0,
            failedAt=_now_ms(),
            **_task_failure_fields(str(exc), prefix="首页导出失败", traceback_text=debug),
        )
        if failed:
            _emit_agent_event("home_archive_failed", failed)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if snapshot_root and snapshot_root.exists():
            shutil.rmtree(snapshot_root, ignore_errors=True)
        unregister_background_task_thread(task_id)


def start_home_archive_export(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    project_ids = list(
        dict.fromkeys(
            str(item).strip()
            for item in payload.get("projectIds") or []
            if str(item).strip()
        )
    )
    scopes = {
        str(item).strip()
        for item in payload.get("globalScopes") or []
        if str(item).strip() in HOME_ARCHIVE_GLOBAL_SCOPES
    }
    asset_scopes = {
        str(item).strip()
        for item in payload.get("assetScopes") or payload.get("globalAssetScopes") or []
        if str(item).strip() in HOME_ARCHIVE_ASSET_SCOPES
    }
    if not project_ids and not scopes and not asset_scopes:
        raise ValueError("请至少选择一个项目、一项全局设置或一项资产库内容")
    export_path = _normalized_zip_export_path(payload.get("exportPath") or payload.get("path"))
    task = create_task(
        "home_archive_export",
        message="首页导出任务已创建。",
        status="created",
        progress=0,
    )
    task = _update_task_fields(task["id"], exportPath=str(export_path)) or task
    _emit_task_update(task, "task_created")
    _start_background_task(task, _run_home_archive_export, project_ids, scopes, export_path, asset_scopes)
    return {"success": True, "task": task, "exportPath": str(export_path)}


def _validate_archive_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > HOME_ARCHIVE_MAX_MEMBERS:
        raise ValueError("压缩包文件数量过多")
    members: list[zipfile.ZipInfo] = []
    total_size = 0
    seen_names: set[str] = set()
    for info in infos:
        filename = str(info.filename or "")
        path = PurePosixPath(filename)
        if (
            not filename
            or "\0" in filename
            or "\\" in filename
            or path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or any(":" in part for part in path.parts)
        ):
            raise ValueError(f"压缩包包含非法路径：{info.filename}")
        normalized_name = path.as_posix().rstrip("/").casefold()
        if normalized_name in seen_names:
            raise ValueError(f"压缩包包含重复路径：{info.filename}")
        seen_names.add(normalized_name)
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError(f"压缩包包含符号链接：{info.filename}")
        if info.flag_bits & 0x1:
            raise ValueError(f"压缩包包含加密成员，无法安全导入：{info.filename}")
        file_size = max(0, int(info.file_size or 0))
        suffix = Path(path.name).suffix.lower()
        lower_name = path.name.lower()
        if lower_name.endswith("-wal") or lower_name.endswith("-shm"):
            raise ValueError(f"压缩包包含不完整的 SQLite 临时文件：{info.filename}")
        if not info.is_dir():
            if suffix in STORED_MEDIA_SUFFIXES:
                if file_size > HOME_ARCHIVE_MAX_MEDIA_MEMBER_BYTES:
                    raise ValueError(f"压缩包中的单个媒体文件过大：{info.filename}")
                if info.compress_type != zipfile.ZIP_STORED:
                    raise ValueError(f"压缩包中的媒体文件必须使用不压缩存储：{info.filename}")
            elif file_size > HOME_ARCHIVE_MAX_NON_MEDIA_MEMBER_BYTES:
                raise ValueError(f"压缩包中的单个非媒体文件过大：{info.filename}")
            compressed_size = max(1, int(info.compress_size or 0))
            if file_size >= 8 * 1024 * 1024 and file_size / compressed_size > 200:
                raise ValueError(f"压缩包中的文件压缩比异常：{info.filename}")
        total_size += file_size
        if total_size > HOME_ARCHIVE_MAX_TOTAL_BYTES:
            raise ValueError("压缩包解压后体积过大")
        members.append(info)
    free_bytes = shutil.disk_usage(DATA_DIR).free
    if total_size + 512 * 1024 * 1024 > free_bytes:
        raise ValueError("磁盘剩余空间不足，无法安全解压该压缩包")
    return members


def _unique_import_project_id(project_id: str, reserved: set[str] | None = None) -> str:
    reserved = reserved or set()
    if project_id not in reserved and not (PROJECTS_DIR / project_id).exists():
        return project_id
    for index in range(1, 10000):
        candidate = f"{project_id}-imported-{index}"
        if candidate not in reserved and not (PROJECTS_DIR / candidate).exists():
            return candidate
    raise FileExistsError("无法为导入项目生成唯一目录")


def _replace_project_path_segment(value: str, old_id: str, new_id: str) -> str:
    pattern = re.compile(rf"(^|[/\\]){re.escape(old_id)}(?=([/\\]|$))")
    return pattern.sub(lambda match: f"{match.group(1)}{new_id}", value)


def _replace_project_id(value: Any, old_id: str, new_id: str, field_name: str = "") -> Any:
    if isinstance(value, dict):
        return {
            key: _replace_project_id(item, old_id, new_id, str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_project_id(item, old_id, new_id, field_name) for item in value]
    if isinstance(value, str):
        field_token = re.sub(r"[^a-z0-9]", "", field_name.lower())
        if field_token in {"project", "projectid"} and value == old_id:
            return new_id
        if "/" in value or "\\" in value:
            return _replace_project_path_segment(value, old_id, new_id)
        return value
    return value


def _sqlite_identifier(value: str) -> str:
    return f'"{str(value).replace(chr(34), chr(34) * 2)}"'


def _rewrite_imported_sqlite_project_id(path: Path, old_id: str, new_id: str) -> None:
    try:
        connection = sqlite3.connect(str(path), timeout=30)
        try:
            connection.execute("PRAGMA busy_timeout = 30000")
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if not quick_check or str(quick_check[0]).lower() != "ok":
                raise sqlite3.DatabaseError("SQLite 完整性检查失败")
            if old_id == new_id:
                return
            tables = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            with connection:
                for table_name in tables:
                    table_sql = _sqlite_identifier(table_name)
                    columns = [
                        str(row[1])
                        for row in connection.execute(f"PRAGMA table_info({table_sql})").fetchall()
                    ]
                    if "project_id" in columns:
                        connection.execute(
                            f"UPDATE {table_sql} SET project_id = ? WHERE project_id = ?",
                            (new_id, old_id),
                        )
                    for column_name in (name for name in columns if name.lower().endswith("_json")):
                        column_sql = _sqlite_identifier(column_name)
                        rows = connection.execute(
                            f"SELECT rowid, {column_sql} FROM {table_sql} WHERE {column_sql} IS NOT NULL"
                        ).fetchall()
                        for row_id, raw_value in rows:
                            if not isinstance(raw_value, str) or not raw_value.strip():
                                continue
                            try:
                                payload = json.loads(raw_value)
                            except json.JSONDecodeError as exc:
                                raise ValueError(
                                    f"SQLite JSON 字段无效：{path.name}/{table_name}.{column_name}"
                                ) from exc
                            rewritten = _replace_project_id(payload, old_id, new_id, column_name)
                            if rewritten != payload:
                                connection.execute(
                                    f"UPDATE {table_sql} SET {column_sql} = ? WHERE rowid = ?",
                                    (json.dumps(rewritten, ensure_ascii=False), row_id),
                                )
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
    except (OSError, sqlite3.DatabaseError) as exc:
        raise ValueError(f"项目 SQLite 文件无效：{path.name}") from exc


def _assert_project_overwrite_idle(project_id: str, import_task_id: str) -> None:
    active = [
        task
        for task in _load_tasks_for_project(project_id)
        if isinstance(task, dict)
        and str(task.get("id") or "") != import_task_id
        and str(task.get("projectId") or task.get("project_id") or "") == project_id
        and str(task.get("status") or "").strip().lower() in ACTIVE_TASK_STATUSES
    ]
    if not active:
        return
    labels = ", ".join(str(task.get("id") or task.get("type") or "任务") for task in active[:3])
    raise RuntimeError(f"项目 {project_id} 仍有进行中的任务（{labels}），请等待或取消后再覆盖导入")


def _sanitize_imported_project_tasks(root: Path, project_id: str) -> None:
    now_ms = _now_ms()
    for path in (root / "tasks" / "tasks.json", root / "tasks.json"):
        if not path.is_file():
            continue
        data = _read_json(path, [])
        if not isinstance(data, list):
            continue
        changed = False
        for task in data:
            if not isinstance(task, dict):
                continue
            original_task_id = str(task.get("id") or "").strip()
            task["id"] = f"task-imported-{uuid.uuid4().hex[:10]}"
            if original_task_id:
                task["importedFromTaskId"] = original_task_id
            changed = True
            if str(task.get("projectId") or task.get("project_id") or "").strip() != project_id:
                task["projectId"] = project_id
                changed = True
            status = str(task.get("status") or "").strip().lower()
            if status in ACTIVE_TASK_STATUSES:
                task["status"] = "cancelled"
                task["progress"] = 0
                task["message"] = IMPORTED_TASK_RESET_MESSAGE
                task["notice"] = IMPORTED_TASK_RESET_MESSAGE
                task["cancelledAt"] = now_ms
                task["updatedAt"] = now_ms
                changed = True
            if not task.get("notificationClearedAt"):
                task["notificationClearedAt"] = now_ms
                changed = True
        if changed:
            _write_json(path, data)


def _rewrite_imported_project_id(root: Path, old_id: str, new_id: str) -> None:
    for path in root.rglob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            relative = path.relative_to(root).as_posix()
            raise ValueError(f"项目 JSON 文件无效：{relative}") from exc
        if old_id != new_id:
            path.write_text(
                json.dumps(_replace_project_id(payload, old_id, new_id), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    meta_path = root / "project.json"
    meta = _read_json(meta_path, {})
    if not isinstance(meta, dict):
        raise ValueError("项目 project.json 格式无效")
    for path in root.rglob("*"):
        if path.is_file() and _is_sqlite_database_path(path):
            _rewrite_imported_sqlite_project_id(path, old_id, new_id)
    _sanitize_imported_project_tasks(root, new_id)
    if old_id != new_id:
        if "id" in meta:
            meta["id"] = new_id
        title = str(meta.get("title") or meta.get("name") or "导入项目").strip()
        renamed_title = f"{title}（导入）"
        if "title" in meta or "name" not in meta:
            meta["title"] = renamed_title
        if "name" in meta:
            meta["name"] = renamed_title
        meta["updated_at"] = datetime.now().astimezone().isoformat()
        _write_json(meta_path, meta)


def _asset_import_merge_key(row: dict[str, Any]) -> str:
    asset_id = str(row.get("id") or "").strip()
    if asset_id:
        return f"id:{asset_id}"
    name = re.sub(r"\s+", " ", str(row.get("name") or row.get("title") or "").strip()).casefold()
    return f"name:{name}" if name else ""


def _selected_global_asset_scopes(global_assets: dict[str, Any]) -> set[str]:
    if not isinstance(global_assets, dict):
        return set()
    selected = {
        str(item).strip()
        for item in global_assets.get("assetTypes") or global_assets.get("assetScopes") or []
        if str(item).strip() in HOME_ARCHIVE_ASSET_SCOPES
    }
    assets_payload = (
        global_assets.get("assets")
        if isinstance(global_assets.get("assets"), dict)
        else {}
    )
    if not selected and isinstance(assets_payload, dict):
        selected = {
            key for key in assets_payload.keys() if key in HOME_ARCHIVE_ASSET_SCOPES
        }
    if not selected and isinstance(global_assets.get("favoriteStyles"), list):
        selected.add("styles")
    return selected


def _merge_rows_by_id_or_name(
    current_rows: Any,
    incoming_rows: Any,
) -> list[dict[str, Any]]:
    result = [
        copy.deepcopy(row)
        for row in current_rows
        if isinstance(row, dict)
    ] if isinstance(current_rows, list) else []
    key_to_index: dict[str, int] = {}
    for index, row in enumerate(result):
        key = _asset_import_merge_key(row)
        if key:
            key_to_index[key] = index
    source_rows = incoming_rows if isinstance(incoming_rows, list) else []
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        item = copy.deepcopy(row)
        key = _asset_import_merge_key(item)
        if key and key in key_to_index:
            result[key_to_index[key]] = item
        else:
            if key:
                key_to_index[key] = len(result)
            result.append(item)
    return result


def _merge_imported_favorite_styles(rows: Any) -> bool:
    if not isinstance(rows, list):
        return False
    imported_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and (
            str(row.get("category") or "") == "favorite"
            or str(row.get("source") or "") == "favorite"
        )
    ]
    if not imported_rows:
        return False
    current = load_style_templates()
    builtin_or_other = [
        copy.deepcopy(row)
        for row in current
        if isinstance(row, dict)
        and str(row.get("category") or "") != "favorite"
        and str(row.get("source") or "") != "favorite"
    ]
    current_favorites = [
        copy.deepcopy(row)
        for row in current
        if isinstance(row, dict)
        and (
            str(row.get("category") or "") == "favorite"
            or str(row.get("source") or "") == "favorite"
        )
    ]
    merged = _merge_rows_by_id_or_name(current_favorites, imported_rows)
    _write_json(GLOBAL_STYLE_TEMPLATES_PATH, builtin_or_other + merged)
    load_style_templates()
    return True


def _merge_imported_global_assets(global_assets: dict[str, Any]) -> list[str]:
    imported: list[str] = []
    if not isinstance(global_assets, dict):
        return imported
    selected = _selected_global_asset_scopes(global_assets)
    assets_payload = (
        global_assets.get("assets")
        if isinstance(global_assets.get("assets"), dict)
        else {}
    )
    if not selected:
        return imported
    current = _read_json(GLOBAL_ASSETS_PATH, copy.deepcopy(DEFAULT_ASSETS))
    if not isinstance(current, dict):
        current = copy.deepcopy(DEFAULT_ASSETS)
    for asset_type in DEFAULT_ASSETS:
        if not isinstance(current.get(asset_type), list):
            current[asset_type] = []
    changed_assets = False
    for asset_type in sorted(selected):
        rows = assets_payload.get(asset_type) if isinstance(assets_payload, dict) else None
        if isinstance(rows, list):
            current[asset_type] = _merge_rows_by_id_or_name(current.get(asset_type), rows)
            imported.append(f"assets.{asset_type}")
            changed_assets = True
    if changed_assets:
        _write_json(GLOBAL_ASSETS_PATH, current)
    if "styles" in selected and _merge_imported_favorite_styles(global_assets.get("favoriteStyles")):
        imported.append("favoriteStyles")
    return imported


def _merge_imported_custom_templates(
    rows: Any,
    *,
    path: Path,
    loader: Any,
) -> bool:
    if not isinstance(rows, list):
        return False
    incoming = {
        str(row.get("id") or ""): copy.deepcopy(row)
        for row in rows
        if isinstance(row, dict)
        and row.get("id")
        and row.get("source") != "builtin"
    }
    if not incoming:
        return False
    current = loader()
    builtin = [
        copy.deepcopy(row)
        for row in current
        if isinstance(row, dict) and row.get("source") == "builtin"
    ]
    custom = {
        str(row.get("id") or ""): copy.deepcopy(row)
        for row in current
        if isinstance(row, dict)
        and row.get("source") != "builtin"
        and row.get("id")
    }
    custom.update(incoming)
    _write_json(path, builtin + list(custom.values()))
    loader()
    return True


def _merge_imported_text_replacement_rules(rows: Any) -> bool:
    imported_rows = _custom_text_replacement_rules(rows)
    if not imported_rows:
        return False
    current = load_text_replacement_rules()
    merged = {
        str(row.get("from") or ""): copy.deepcopy(row)
        for row in current
        if isinstance(row, dict) and str(row.get("from") or "").strip()
    }
    for row in imported_rows:
        source = str(row.get("from") or "").strip()
        if source:
            merged[source] = copy.deepcopy(row)
    _write_json(GLOBAL_TEXT_REPLACEMENT_RULES_PATH, list(merged.values()))
    load_text_replacement_rules()
    return True


def _merge_imported_director_rules(rows: Any) -> bool:
    if not isinstance(rows, list):
        return False
    overrides = _load_director_rule_overrides()
    changed = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        rule_id = normalize_director_rule_identifier(
            row.get("id") or row.get("ruleId")
        )
        if not rule_id:
            continue
        description = str(row.get("description") or "").strip()
        content = str(row.get("content") or "").strip()
        if not description and not content:
            continue
        overrides[rule_id] = {
            "id": rule_id,
            "description": description,
            "content": content,
            "updatedAt": str(row.get("updatedAt") or "").strip(),
        }
        changed = True
    if not changed:
        return False
    _save_director_rule_overrides(overrides)
    return True


def _model_import_provider_keys(providers: Any) -> set[str]:
    if not isinstance(providers, list):
        return set()
    keys: set[str] = set()
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        for value in (
            provider.get("id"),
            provider.get("preset_id"),
            provider.get("presetId"),
            _provider_service_id(provider),
        ):
            key = _normalize_provider_id(value)
            if key:
                keys.add(key)
    return keys


def _model_import_provider_id(model: dict[str, Any], requested_model_id: str) -> str:
    provider_id = _normalize_provider_id(
        model.get("provider_id") or model.get("providerId")
    )
    if provider_id:
        return provider_id
    model_id = str(model.get("id") or requested_model_id or "").strip()
    if ":" in model_id:
        return _normalize_provider_id(model_id.split(":", 1)[0])
    return ""


def _import_model_exists(
    model_id: Any,
    model_type: str,
    capabilities: dict[str, Any],
    provider_keys: set[str],
) -> bool:
    requested_model_id = str(model_id or "").strip()
    if not requested_model_id or not provider_keys:
        return False
    model = _find_model(requested_model_id, model_type, capabilities)
    if not isinstance(model, dict):
        return False
    provider_id = _model_import_provider_id(model, requested_model_id)
    return bool(provider_id and provider_id in provider_keys)


def _merge_imported_model_settings(
    config: dict[str, Any],
    models: Any,
) -> bool:
    if not isinstance(models, dict):
        return False
    incoming = models.get("modelConfig")
    if not isinstance(incoming, dict):
        return False
    providers = config.get("providers") if isinstance(config.get("providers"), list) else []
    provider_keys = _model_import_provider_keys(providers)
    if not provider_keys:
        return False
    capabilities = _model_capabilities_with_provider_models(
        DEFAULT_MODEL_CAPABILITIES,
        providers,
    )
    next_config = copy.deepcopy(
        config.get("model_config") if isinstance(config.get("model_config"), dict) else {}
    )
    changed = False

    def merge_section(section: str, model_key: str, model_type: str) -> None:
        nonlocal changed
        row = incoming.get(section)
        if not isinstance(row, dict):
            return
        model_id = row.get(model_key)
        if not _import_model_exists(model_id, model_type, capabilities, provider_keys):
            return
        current_section = (
            next_config.get(section)
            if isinstance(next_config.get(section), dict)
            else {}
        )
        next_config[section] = _deep_merge(current_section, row)
        changed = True

    merge_section("image", "model_id", "image")
    merge_section("video", "model_id", "video")
    merge_section("agent", "model_id", "agent")

    text = incoming.get("text")
    if isinstance(text, dict):
        text_patch: dict[str, Any] = {}
        if _import_model_exists(text.get("model_id"), "text", capabilities, provider_keys):
            text_patch["model_id"] = copy.deepcopy(text["model_id"])
        if text_patch:
            if "overview_excerpt_chars" in text:
                text_patch["overview_excerpt_chars"] = copy.deepcopy(
                    text["overview_excerpt_chars"]
                )
            current_text = (
                next_config.get("text")
                if isinstance(next_config.get("text"), dict)
                else {}
            )
            next_config["text"] = _deep_merge(current_text, text_patch)
            changed = True

    if not changed:
        return False
    config["model_config"] = next_config
    if isinstance(models.get("defaults"), dict):
        config["defaults"] = _deep_merge(config.get("defaults") or {}, models["defaults"])
    return True


@_serialized_global_config_write
def _merge_imported_global_settings(settings: dict[str, Any]) -> list[str]:
    imported: list[str] = []
    config = load_global_config()
    providers = settings.get("providers")
    if isinstance(providers, list):
        config["providers"] = copy.deepcopy(providers)
        imported.append("providers")
    models = settings.get("models")
    if _merge_imported_model_settings(config, models):
        imported.append("models")
    if imported:
        _save_global_config(config)

    script_templates = settings.get("scriptAdaptationTemplates")
    if _merge_imported_custom_templates(
        script_templates,
        path=GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH,
        loader=load_script_adaptation_templates,
    ):
        imported.append("scriptAdaptationTemplates")

    director_rules = settings.get("directorRules")
    if _merge_imported_director_rules(director_rules):
        imported.append("directorRules")

    text_replacement_rules = settings.get("textReplacementRules")
    if _merge_imported_text_replacement_rules(text_replacement_rules):
        imported.append("textReplacementRules")

    storyboards = settings.get("storyboardTemplates")
    if _merge_imported_custom_templates(
        storyboards,
        path=GLOBAL_STORYBOARD_TEMPLATES_PATH,
        loader=load_storyboard_templates,
    ):
        imported.append("storyboardTemplates")
    return imported


class _TransferCancelled(RuntimeError):
    pass


def _import_global_file_snapshot() -> dict[Path, bytes | None]:
    return {
        path: path.read_bytes() if path.is_file() else None
        for path in (
            GLOBAL_CONFIG_PATH,
            GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH,
            GLOBAL_DIRECTOR_RULE_OVERRIDES_PATH,
            GLOBAL_TEXT_REPLACEMENT_RULES_PATH,
            GLOBAL_STORYBOARD_TEMPLATES_PATH,
            GLOBAL_ASSETS_PATH,
            GLOBAL_STYLE_TEMPLATES_PATH,
        )
    }


def _restore_import_global_file_snapshot(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            path.unlink(missing_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _is_global_archive_media_target(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    global_root = GLOBAL_ASSET_MEDIA_DIR.parent.resolve()
    if resolved == global_root or global_root not in resolved.parents:
        return False
    try:
        relative = resolved.relative_to(global_root).as_posix()
    except ValueError:
        return False
    return any(relative == prefix.rstrip("/") or relative.startswith(prefix) for prefix in HOME_ARCHIVE_GLOBAL_FILE_PREFIXES)


def _home_import_journal_path() -> Path:
    return DATA_DIR / "home_archive_import_recovery.json"


def _write_home_import_journal(payload: dict[str, Any]) -> None:
    _write_json(_home_import_journal_path(), payload)


def _delete_home_import_journal() -> None:
    _home_import_journal_path().unlink(missing_ok=True)


def _remove_import_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


@contextmanager
def _home_import_staging_directory():
    stage_root = Path(tempfile.mkdtemp(prefix="ai-video-import-", dir=str(DATA_DIR)))
    try:
        yield stage_root
    finally:
        if not _home_import_journal_path().is_file() and stage_root.exists():
            shutil.rmtree(stage_root, ignore_errors=True)


def _create_home_import_journal(
    task_id: str,
    stage_root: Path,
    plans: list[dict[str, Any]],
    global_snapshot: dict[Path, bytes | None],
    global_file_targets: list[Path] | None = None,
) -> dict[str, Any]:
    backup_root = stage_root / "backups"
    global_backup_root = backup_root / "global"
    global_entries: list[dict[str, Any]] = []
    for index, (target, content) in enumerate(global_snapshot.items(), start=1):
        backup = global_backup_root / f"{index:02d}-{target.name}"
        if content is not None:
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(content)
        global_entries.append(
            {
                "target": str(target.resolve()),
                "backup": str(backup.resolve()),
                "existed": content is not None,
            }
        )
    next_index = len(global_entries) + 1
    for target in global_file_targets or []:
        resolved_target = Path(target).resolve()
        if resolved_target in {Path(path).resolve() for path in global_snapshot}:
            continue
        if not _is_global_archive_media_target(resolved_target):
            raise RuntimeError(f"全局资产文件目标非法：{resolved_target}")
        suffix = resolved_target.suffix or ".bin"
        backup = global_backup_root / f"{next_index:02d}-{uuid.uuid4().hex}{suffix}"
        existed = resolved_target.is_file()
        if existed:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved_target, backup)
        global_entries.append(
            {
                "target": str(resolved_target),
                "backup": str(backup.resolve()),
                "existed": existed,
            }
        )
        next_index += 1
    project_entries = [
        {
            "target": str(Path(plan["target"]).resolve()),
            "backup": str((backup_root / Path(plan["target"]).name).resolve()),
            "originalExisted": Path(plan["target"]).exists(),
            "phase": "planned",
        }
        for plan in plans
    ]
    journal = {
        "version": 1,
        "taskId": task_id,
        "stageRoot": str(stage_root.resolve()),
        "committed": False,
        "projects": project_entries,
        "globalFiles": global_entries,
    }
    _write_home_import_journal(journal)
    return journal


def recover_home_archive_imports() -> dict[str, Any]:
    with _HOME_ARCHIVE_IMPORT_LOCK:
        with _GLOBAL_CONFIG_UPDATE_LOCK:
            journal_path = _home_import_journal_path()
            if not journal_path.is_file():
                return {"success": True, "recovered": False}
            journal = _read_json(journal_path, {})
            if not isinstance(journal, dict) or journal.get("version") != 1:
                raise RuntimeError("首页导入恢复日志格式无效，请先备份并人工检查数据目录")
            data_root = DATA_DIR.resolve()
            projects_root = PROJECTS_DIR.resolve()
            stage_root = Path(str(journal.get("stageRoot") or "")).resolve()
            if data_root not in stage_root.parents or not stage_root.name.startswith("ai-video-import-"):
                raise RuntimeError("首页导入恢复日志包含非法暂存目录")
            if not bool(journal.get("committed")):
                for entry in reversed(journal.get("projects") or []):
                    if not isinstance(entry, dict):
                        continue
                    target = Path(str(entry.get("target") or "")).resolve()
                    backup = Path(str(entry.get("backup") or "")).resolve()
                    if target.parent != projects_root or stage_root not in backup.parents:
                        raise RuntimeError("首页导入恢复日志包含非法项目路径")
                    if backup.exists():
                        if target.exists() or target.is_symlink():
                            _remove_import_path(target)
                        os.replace(backup, target)
                    elif (
                        entry.get("originalExisted")
                        and entry.get("phase") in {"backed_up", "installed"}
                    ):
                        raise RuntimeError(f"首页导入恢复备份缺失：{target.name}")
                    elif entry.get("phase") == "installed" and not entry.get("originalExisted"):
                        if target.exists() or target.is_symlink():
                            _remove_import_path(target)
                allowed_global_paths = {
                    path.resolve()
                    for path in (
                        GLOBAL_CONFIG_PATH,
                        GLOBAL_SCRIPT_ADAPTATION_TEMPLATES_PATH,
                        GLOBAL_DIRECTOR_RULE_OVERRIDES_PATH,
                        GLOBAL_TEXT_REPLACEMENT_RULES_PATH,
                        GLOBAL_STORYBOARD_TEMPLATES_PATH,
                        GLOBAL_ASSETS_PATH,
                        GLOBAL_STYLE_TEMPLATES_PATH,
                    )
                }
                for entry in journal.get("globalFiles") or []:
                    if not isinstance(entry, dict):
                        continue
                    target = Path(str(entry.get("target") or "")).resolve()
                    backup = Path(str(entry.get("backup") or "")).resolve()
                    target_allowed = (
                        target in allowed_global_paths
                        or _is_global_archive_media_target(target)
                    )
                    if not target_allowed or stage_root not in backup.parents:
                        raise RuntimeError("首页导入恢复日志包含非法全局设置路径")
                    if entry.get("existed"):
                        if not backup.is_file():
                            raise RuntimeError(f"首页导入恢复文件缺失：{backup.name}")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup, target)
                    else:
                        target.unlink(missing_ok=True)
            if stage_root.exists():
                shutil.rmtree(stage_root, ignore_errors=True)
            _delete_home_import_journal()
            return {"success": True, "recovered": True, "committed": bool(journal.get("committed"))}


def _copy_archive_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path,
    task_id: str,
) -> None:
    written = 0
    expected = max(0, int(info.file_size or 0))
    with archive.open(info) as source, destination.open("wb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            if _task_cancelled(task_id):
                raise _TransferCancelled()
            written += len(chunk)
            if written > expected:
                raise ValueError(f"压缩包成员实际体积异常：{info.filename}")
            output.write(chunk)
    if written != expected:
        raise ValueError(f"压缩包成员体积校验失败：{info.filename}")


def _archive_global_relative_path(filename: str) -> PurePosixPath | None:
    if not filename.startswith("global/"):
        return None
    relative = PurePosixPath(filename[len("global/") :])
    if not relative.parts:
        return None
    normalized = relative.as_posix()
    if not any(normalized.startswith(prefix) for prefix in HOME_ARCHIVE_GLOBAL_FILE_PREFIXES):
        return None
    if relative.parts[0] == "asset_media" and len(relative.parts) < 3:
        return None
    return relative


def _copy_archive_global_asset_files(
    archive: zipfile.ZipFile,
    members: list[zipfile.ZipInfo],
    stage_root: Path,
    task_id: str,
    asset_scopes: set[str],
) -> list[dict[str, Path]]:
    staged_global_root = stage_root / "global"
    global_root = GLOBAL_ASSET_MEDIA_DIR.parent.resolve()
    plans: list[dict[str, Path]] = []
    for info in members:
        if info.is_dir():
            continue
        relative = _archive_global_relative_path(str(info.filename or ""))
        if relative is None:
            continue
        if relative.parts[0] == "asset_media":
            if len(relative.parts) < 3 or relative.parts[1] not in asset_scopes:
                continue
        elif relative.parts[0] == "style_references" and "styles" not in asset_scopes:
            continue
        staged = staged_global_root.joinpath(*relative.parts)
        target = global_root.joinpath(*relative.parts)
        resolved_staged_root = staged_global_root.resolve()
        resolved_staged = staged.resolve()
        resolved_target = target.resolve()
        if (
            resolved_staged != resolved_staged_root
            and resolved_staged_root not in resolved_staged.parents
        ):
            raise ValueError(f"压缩包包含越界全局资产路径：{info.filename}")
        if not _is_global_archive_media_target(resolved_target):
            raise ValueError(f"压缩包包含非法全局资产路径：{info.filename}")
        if resolved_target.exists() and resolved_target.is_dir():
            raise ValueError(f"压缩包全局资产目标是目录：{info.filename}")
        staged.parent.mkdir(parents=True, exist_ok=True)
        _copy_archive_member(archive, info, staged, task_id)
        plans.append({"staged": staged, "target": resolved_target})
    return plans


def _install_imported_global_asset_files(plans: list[dict[str, Path]]) -> None:
    for plan in plans:
        staged = Path(plan["staged"])
        target = Path(plan["target"])
        if not staged.is_file():
            raise FileNotFoundError(f"全局资产文件缺失：{staged.name}")
        if not _is_global_archive_media_target(target):
            raise ValueError(f"全局资产目标路径非法：{target}")
        if target.exists() and target.is_dir():
            raise ValueError(f"全局资产目标是目录：{target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged, target)


def _restore_import_global_file_entries(entries: list[Any]) -> None:
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        target = Path(str(entry.get("target") or "")).resolve()
        backup = Path(str(entry.get("backup") or "")).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry.get("existed"):
            if not backup.is_file():
                raise RuntimeError(f"首页导入恢复文件缺失：{backup.name}")
            shutil.copy2(backup, target)
        else:
            target.unlink(missing_ok=True)


def _run_home_archive_import(task_id: str, archive_path: Path, conflict_policy: str) -> None:
    try:
        with _HOME_ARCHIVE_IMPORT_LOCK:
            ensure_store()
            recover_home_archive_imports()
            if _task_cancelled(task_id):
                return
            _update_transfer_task(task_id, status="running", progress=5, message="正在校验导入压缩包。")
            with zipfile.ZipFile(archive_path) as archive:
                members = _validate_archive_members(archive)
                manifest_info = next(
                    (info for info in members if info.filename == HOME_ARCHIVE_MANIFEST),
                    None,
                )
                if not manifest_info:
                    raise ValueError("不是有效的 ai-video 首页导出包")
                if int(manifest_info.file_size or 0) > HOME_ARCHIVE_MANIFEST_MAX_BYTES:
                    raise ValueError("导入包清单文件过大")
                with archive.open(manifest_info) as source:
                    manifest_bytes = source.read(HOME_ARCHIVE_MANIFEST_MAX_BYTES + 1)
                if len(manifest_bytes) > HOME_ARCHIVE_MANIFEST_MAX_BYTES:
                    raise ValueError("导入包清单文件过大")
                manifest = json.loads(manifest_bytes.decode("utf-8"))
                if not isinstance(manifest, dict) or manifest.get("format") != HOME_ARCHIVE_FORMAT:
                    raise ValueError("压缩包格式不受支持")
                if manifest.get("version") != HOME_ARCHIVE_VERSION:
                    raise ValueError("压缩包版本不受支持")
                raw_project_ids = [
                    str(item).strip()
                    for item in manifest.get("projectIds") or []
                    if str(item).strip()
                ]
                if len(raw_project_ids) != len(set(raw_project_ids)):
                    raise ValueError("压缩包清单包含重复项目 ID")
                project_ids = raw_project_ids
                global_settings = (
                    manifest.get("globalSettings")
                    if isinstance(manifest.get("globalSettings"), dict)
                    else {}
                )
                global_assets = (
                    manifest.get("globalAssets")
                    if isinstance(manifest.get("globalAssets"), dict)
                    else {}
                )
                if not project_ids and not global_settings and not global_assets:
                    raise ValueError("压缩包没有可导入的项目、全局设置或资产库")

                imported_projects: list[str] = []
                skipped_projects: list[str] = []
                imported_settings: list[str] = []
                with _home_import_staging_directory() as stage_root:
                    staged_root = stage_root / "projects"
                    backup_root = stage_root / "backups"
                    plans: list[dict[str, Any]] = []
                    global_asset_file_plans: list[dict[str, Path]] = []
                    reserved_target_ids: set[str] = set()
                    try:
                        for index, project_id in enumerate(project_ids, start=1):
                            if _task_cancelled(task_id):
                                raise _TransferCancelled()
                            if project_id in {".", ".."} or not re.fullmatch(
                                r"[A-Za-z0-9._-]+", project_id
                            ):
                                raise ValueError(f"项目 ID 无效：{project_id}")
                            target_id = project_id
                            target = PROJECTS_DIR / target_id
                            overwrite_existing = False
                            if target.exists():
                                if conflict_policy == "skip":
                                    skipped_projects.append(project_id)
                                    continue
                                if conflict_policy == "overwrite":
                                    _assert_project_overwrite_idle(project_id, task_id)
                                    overwrite_existing = True
                                else:
                                    target_id = _unique_import_project_id(
                                        project_id,
                                        reserved_target_ids,
                                    )
                                    target = PROJECTS_DIR / target_id
                            elif target_id in reserved_target_ids:
                                target_id = _unique_import_project_id(
                                    project_id,
                                    reserved_target_ids,
                                )
                                target = PROJECTS_DIR / target_id
                            reserved_target_ids.add(target_id)
                            staged = staged_root / target_id
                            prefix = f"projects/{project_id}/"
                            matched_files = 0
                            for info in members:
                                if info.is_dir() or not info.filename.startswith(prefix):
                                    continue
                                relative = PurePosixPath(info.filename[len(prefix) :])
                                if not relative.parts:
                                    continue
                                destination = staged.joinpath(*relative.parts)
                                resolved_staged = staged.resolve()
                                resolved_destination = destination.resolve()
                                if (
                                    resolved_destination != resolved_staged
                                    and resolved_staged not in resolved_destination.parents
                                ):
                                    raise ValueError(f"压缩包包含越界路径：{info.filename}")
                                destination.parent.mkdir(parents=True, exist_ok=True)
                                _copy_archive_member(archive, info, destination, task_id)
                                matched_files += 1
                            if not matched_files or not (staged / "project.json").is_file():
                                raise ValueError(f"项目 {project_id} 缺少 project.json")
                            _rewrite_imported_project_id(staged, project_id, target_id)
                            plans.append(
                                {
                                    "targetId": target_id,
                                    "target": target,
                                    "staged": staged,
                                    "overwrite": overwrite_existing,
                                }
                            )
                            _update_transfer_task(
                                task_id,
                                status="running",
                                progress=min(70, 10 + round(index / max(1, len(project_ids)) * 55)),
                                message=f"正在校验项目 {index}/{len(project_ids)}。",
                            )

                        global_asset_file_plans = (
                            _copy_archive_global_asset_files(
                                archive,
                                members,
                                stage_root,
                                task_id,
                                _selected_global_asset_scopes(global_assets),
                            )
                            if global_assets
                            else []
                        )
                        with _GLOBAL_CONFIG_UPDATE_LOCK:
                            global_snapshot = _import_global_file_snapshot()
                            recovery_journal = _create_home_import_journal(
                                task_id,
                                stage_root,
                                plans,
                                global_snapshot,
                                [Path(plan["target"]) for plan in global_asset_file_plans],
                            )
                            committed: list[tuple[Path, Path | None]] = []
                            try:
                                for index, plan in enumerate(plans, start=1):
                                    if _task_cancelled(task_id):
                                        raise _TransferCancelled()
                                    target = Path(plan["target"])
                                    backup: Path | None = None
                                    if target.exists():
                                        if not plan["overwrite"]:
                                            raise FileExistsError(f"导入目标已存在：{target.name}")
                                        _assert_project_overwrite_idle(target.name, task_id)
                                        backup_root.mkdir(parents=True, exist_ok=True)
                                        backup = backup_root / target.name
                                        os.replace(target, backup)
                                        recovery_journal["projects"][index - 1]["phase"] = "backed_up"
                                        _write_home_import_journal(recovery_journal)
                                    try:
                                        shutil.move(str(plan["staged"]), str(target))
                                    except Exception:
                                        if backup and backup.exists() and not target.exists():
                                            os.replace(backup, target)
                                        raise
                                    recovery_journal["projects"][index - 1]["phase"] = "installed"
                                    _write_home_import_journal(recovery_journal)
                                    committed.append((target, backup))
                                    imported_projects.append(str(plan["targetId"]))
                                    _update_transfer_task(
                                        task_id,
                                        status="running",
                                        progress=min(90, 72 + round(index / max(1, len(plans)) * 15)),
                                        message=f"正在恢复项目 {index}/{len(plans)}。",
                                    )
                                if _task_cancelled(task_id):
                                    raise _TransferCancelled()
                                _install_imported_global_asset_files(global_asset_file_plans)
                                if _task_cancelled(task_id):
                                    raise _TransferCancelled()
                                imported_settings = _merge_imported_global_settings(global_settings)
                                imported_settings.extend(_merge_imported_global_assets(global_assets))
                                if _task_cancelled(task_id):
                                    raise _TransferCancelled()
                                recovery_journal["committed"] = True
                                _write_home_import_journal(recovery_journal)
                                completed = _update_transfer_task(
                                    task_id,
                                    "task_completed",
                                    status="completed",
                                    progress=100,
                                    message=f"导入完成：{len(imported_projects)} 个项目。",
                                    notice="首页 ZIP 已导入。",
                                    completedAt=_now_ms(),
                                    result={
                                        "importedProjectIds": imported_projects,
                                        "skippedProjectIds": skipped_projects,
                                        "globalScopes": imported_settings,
                                    },
                                )
                                if not completed:
                                    raise _TransferCancelled()
                                _delete_home_import_journal()
                            except Exception as transaction_error:
                                recovery_journal["committed"] = False
                                _write_home_import_journal(recovery_journal)
                                rollback_errors: list[str] = []
                                try:
                                    _restore_import_global_file_entries(
                                        recovery_journal.get("globalFiles") or []
                                    )
                                except Exception as rollback_error:
                                    rollback_errors.append(f"全局设置回滚失败：{rollback_error}")
                                for target, backup in reversed(committed):
                                    try:
                                        if target.exists():
                                            shutil.rmtree(target)
                                        if backup and backup.exists():
                                            os.replace(backup, target)
                                    except Exception as rollback_error:
                                        rollback_errors.append(
                                            f"项目 {target.name} 回滚失败：{rollback_error}"
                                        )
                                imported_projects.clear()
                                if rollback_errors:
                                    raise RuntimeError("；".join(rollback_errors)) from transaction_error
                                _delete_home_import_journal()
                                raise
                    except _TransferCancelled:
                        return
        changed_resources = ["projects"]
        if any(scope in HOME_ARCHIVE_GLOBAL_SCOPES for scope in imported_settings):
            changed_resources.append("global_settings")
        if any(
            str(scope).startswith("assets.") or scope == "favoriteStyles"
            for scope in imported_settings
        ):
            changed_resources.append("global_assets")

        _emit_agent_event(
            "project_changed",
            {
                "action": "home_archive_imported",
                "projectIds": imported_projects,
                "changedResources": changed_resources,
            },
        )
        _emit_agent_event("home_archive_completed", completed)
    except Exception as exc:
        debug = traceback.format_exc()
        print(debug, flush=True)
        failed = _update_transfer_task(
            task_id,
            "task_failed",
            status="failed",
            progress=0,
            failedAt=_now_ms(),
            **_task_failure_fields(str(exc), prefix="首页导入失败", traceback_text=debug),
        )
        if failed:
            _emit_agent_event("home_archive_failed", failed)
    finally:
        unregister_background_task_thread(task_id)


def start_home_archive_import(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    archive_path = _archive_import_path(payload.get("archivePath") or payload.get("path"))
    conflict_policy = str(payload.get("conflictPolicy") or "rename").strip()
    if conflict_policy not in {"rename", "skip", "overwrite"}:
        conflict_policy = "rename"
    task = create_task(
        "home_archive_import",
        message="首页导入任务已创建。",
        status="created",
        progress=0,
    )
    task = _update_task_fields(task["id"], archivePath=str(archive_path)) or task
    _emit_task_update(task, "task_created")
    _start_background_task(task, _run_home_archive_import, archive_path, conflict_policy)
    return {"success": True, "task": task, "archivePath": str(archive_path)}


def _detect_jianying_custom_paths(user_data_dir: Path) -> list[Path]:
    config_path = user_data_dir / "Config" / "globalSetting"
    if not config_path.is_file():
        return []
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(config_path, encoding="utf-8")
    except configparser.Error:
        return []
    raw = parser.get("General", "currentCustomDraftPath", fallback="").strip().strip("\"'")
    if not raw:
        return []
    return [Path(os.path.expandvars(raw.replace("\\\\", "\\"))).expanduser()]


def detect_jianying_draft_root() -> dict[str, Any]:
    candidates: list[Path] = []
    home = Path.home()
    if platform.system() == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        user_data = local / "JianyingPro" / "User Data"
        candidates.extend(_detect_jianying_custom_paths(user_data))
        candidates.append(user_data / "Projects" / "com.lveditor.draft")
    elif platform.system() == "Darwin":
        candidates.append(home / "Movies" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft")
    else:
        candidates.append(home / ".config" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft")
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_dir():
            return {"success": True, "path": key}
    return {"success": True, "path": ""}


def _episode_workflow_paths(project_id: str, episode_id: str) -> list[Path]:
    episode_dir = PROJECTS_DIR / project_id / "episodes" / episode_id
    candidates = [episode_dir / "canvas" / "canvas.json"]
    seen: set[str] = set()
    result: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _media_path_from_node(project_id: str, node: dict[str, Any]) -> Path | None:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    project_root = (PROJECTS_DIR / project_id).resolve()
    for media in (data.get("media"), data.get("storage")):
        if not isinstance(media, dict):
            continue
        values = [
            media.get("relativePath"),
            media.get("relative_path"),
            media.get("file"),
            media.get("path"),
            media.get("filePath"),
        ]
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            path = Path(text)
            if not path.is_absolute():
                path = project_root / path
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved != project_root and project_root not in resolved.parents:
                continue
            if resolved.is_file() and resolved.suffix.lower() in VIDEO_SUFFIXES:
                return resolved
    return None


def _node_data(node: dict[str, Any] | None) -> dict[str, Any]:
    return node.get("data") if isinstance(node, dict) and isinstance(node.get("data"), dict) else {}


def _node_type(node: dict[str, Any] | None) -> str:
    data = _node_data(node)
    return str((node or {}).get("type") or data.get("eyebrow") or "").strip()


def _node_current_version_id(node: dict[str, Any] | None) -> str:
    data = _node_data(node)
    for key in ("activeVersionId", "activeMediaVersionId", "mediaVersionId"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return ""


def _node_work_chain_id(node: dict[str, Any] | None) -> str:
    return str((node or {}).get("workChainId") or "").strip()


def _is_history_video_result(data: dict[str, Any]) -> bool:
    provenance = data.get("provenance") if isinstance(data.get("provenance"), dict) else {}
    return (
        str(data.get("sourceType") or "").strip() == "version"
        or bool(data.get("copiedFromNodeId"))
        or bool(provenance.get("copiedFromNodeId"))
        or "created_from_video_version" in str(provenance.get("action") or "")
    )


def _node_position_tuple(node: dict[str, Any]) -> tuple[float, float]:
    position = node.get("position") if isinstance(node.get("position"), dict) else {}
    return (float(position.get("y") or 0), float(position.get("x") or 0))


def _canvas_video_clip_plan(
    project_id: str,
    canvas_key: str,
    *,
    item_order: int = 0,
    use_work_chain_order: bool = True,
) -> dict[str, Any]:
    if not canvas_key or not episode_canvas_exists(project_id, canvas_key):
        return {
            "clips": [],
            "totalChains": 0,
            "canvasCount": 0,
            "workChainVideoCount": 0,
            "otherVideoCount": 0,
        }
    workflow = read_canvas_workflow_projection_v4(project_id, canvas_key, detail="full")
    if not isinstance(workflow, dict):
        return {
            "clips": [],
            "totalChains": 0,
            "canvasCount": 0,
            "workChainVideoCount": 0,
            "otherVideoCount": 0,
        }
    chains = [row for row in workflow.get("workChains") or [] if isinstance(row, dict)]
    chain_order = {
        str(row.get("id") or ""): int(row.get("order") or index + 1)
        for index, row in enumerate(chains)
        if row.get("id")
    }
    nodes = [row for row in workflow.get("nodes") or [] if isinstance(row, dict)]
    node_by_id = {str(row.get("id") or ""): row for row in nodes if row.get("id")}
    node_index_by_id = {
        str(row.get("id") or ""): index
        for index, row in enumerate(nodes)
        if row.get("id")
    }
    from .storyboard_allocation import director_shots_hash

    allocation_by_chain: dict[str, dict[str, Any]] = {}
    for director in nodes:
        if _node_type(director) != "director.board":
            continue
        director_data = _node_data(director)
        allocation = director_data.get("storyboardAllocation")
        if isinstance(allocation, dict):
            allocation_by_chain[_node_work_chain_id(director)] = {
                "valid": allocation.get("directorPlanHash") == director_shots_hash(director_data.get("directorPlanShots") or []),
                "groups": {str(group.get("id") or ""): group.get("shotNos") for group in allocation.get("groups") or [] if isinstance(group, dict)},
                "shots": director_data.get("directorPlanShots") or [],
            }
    inferred_chains = {
        _node_work_chain_id(row)
        for row in nodes
        if _node_work_chain_id(row)
    }
    total_chains = len(chains) if chains else len(inferred_chains)
    clips: list[dict[str, Any]] = []
    stale_allocation_count = 0
    seen_active_results: set[tuple[str, str]] = set()
    for node_index, node in enumerate(nodes):
        if _node_type(node) != "video.result":
            continue
        data = _node_data(node)
        if _is_history_video_result(data):
            continue
        result_version_id = _node_current_version_id(node)
        if not result_version_id:
            continue
        source_node_id = str(data.get("resultOfNodeId") or data.get("sourceNodeId") or "").strip()
        source_node = node_by_id.get(source_node_id)
        if _node_type(source_node) not in VIDEO_TASK_NODE_TYPES:
            continue
        source_version_id = _node_current_version_id(source_node)
        if source_version_id and source_version_id != result_version_id:
            continue
        media_path = _media_path_from_node(project_id, node)
        if not media_path:
            continue
        work_chain_id = _node_work_chain_id(node) or _node_work_chain_id(source_node)
        group_id = str(data.get("shotGroupId") or _node_data(source_node).get("shotGroupId") or "")
        allocation_state = allocation_by_chain.get(work_chain_id)
        if group_id and (
            not allocation_state
            or not allocation_state["valid"]
            or allocation_state["groups"].get(group_id) != (data.get("shotNos") or _node_data(source_node).get("shotNos"))
        ):
            stale_allocation_count += 1
            continue
        clip_kind = "work_chain" if work_chain_id else "other"
        unique_key = (source_node_id, result_version_id)
        if unique_key in seen_active_results:
            continue
        seen_active_results.add(unique_key)
        source_index = node_index_by_id.get(source_node_id, node_index)
        y, x = _node_position_tuple(node)
        chain_rank = chain_order.get(work_chain_id, 999999) if work_chain_id else 999999
        shot_group_order = int(data.get("shotGroupOrder") or _node_data(source_node).get("shotGroupOrder") or 0)
        group_shot_nos = (allocation_state or {}).get("groups", {}).get(group_id) or []
        director_shots = (allocation_state or {}).get("shots") or []
        first_shot = (
            director_shots[group_shot_nos[0] - 1]
            if group_shot_nos and isinstance(group_shot_nos[0], int)
            and 0 < group_shot_nos[0] <= len(director_shots) else {}
        )
        order = (
            (item_order, chain_rank, shot_group_order, source_index, node_index, y, x)
            if use_work_chain_order
            else (item_order, shot_group_order, source_index, node_index, y, x)
        )
        clips.append(
            {
                "id": str(node.get("id") or media_path.stem),
                "sourceNodeId": source_node_id,
                "versionId": result_version_id,
                "kind": clip_kind,
                "workChainId": work_chain_id,
                "shotGroupId": group_id,
                "routeId": str(node.get("routeId") or data.get("routeId") or ""),
                "path": media_path,
                "boundaryKind": str(first_shot.get("entryBoundaryKind") or "ordinary_cut"),
                "audioBoundaryKind": str(first_shot.get("audioBoundaryKind") or "hard_cut"),
                "order": order,
            }
        )
    clips.sort(key=lambda row: row["order"])
    generated_groups = {
        (str(clip.get("workChainId") or ""), str(clip.get("shotGroupId") or ""))
        for clip in clips if clip.get("shotGroupId")
    }
    missing_allocation_count = sum(
        1
        for chain_id, allocation in allocation_by_chain.items()
        for group_id in allocation["groups"]
        if (chain_id, group_id) not in generated_groups
    )
    work_chain_count = sum(1 for clip in clips if clip.get("kind") == "work_chain")
    other_count = len(clips) - work_chain_count
    return {
        "clips": clips,
        "totalChains": total_chains,
        "canvasCount": 1,
        "workChainVideoCount": work_chain_count,
        "otherVideoCount": other_count,
        "staleAllocationCount": stale_allocation_count,
        "missingAllocationCount": missing_allocation_count,
    }


def _episode_video_plan(project_id: str, episode_id: str, *, item_order: int = 0) -> dict[str, Any]:
    return _canvas_video_clip_plan(project_id, episode_id, item_order=item_order)


def _episode_clip_plan(project_id: str, episode_id: str) -> dict[str, Any]:
    plan = _episode_video_plan(project_id, episode_id)
    if plan.get("staleAllocationCount"):
        raise ValueError("分镜脚本已变化，部分视频对应旧分镜分配；请重新分配并生成受影响的视频后再导出")
    if plan.get("missingAllocationCount"):
        raise ValueError("还有分配的分镜视频未生成，完成所有视频任务后再导出本集成片")
    clips = [clip for clip in plan["clips"] if clip.get("kind") == "work_chain"]
    return {**plan, "clips": clips}


def _custom_canvas_video_plan(project_id: str, canvas: dict[str, Any], *, item_order: int = 0) -> dict[str, Any]:
    storage_key = str(canvas.get("storageKey") or canvas.get("canvasId") or "").strip()
    return _canvas_video_clip_plan(
        project_id,
        storage_key,
        item_order=item_order,
        use_work_chain_order=False,
    )


def _custom_canvas_rows(project_id: str) -> list[dict[str, Any]]:
    payload = list_project_custom_canvases_v4(project_id)
    rows = payload.get("customCanvases") if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def get_jianying_export_info(project_id: str) -> dict[str, Any]:
    from pyJianYingDraft import VideoMaterial

    def clip_choices(clips: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        rows = []
        unreadable = 0
        for index, clip in enumerate(clips):
            try:
                duration = VideoMaterial(str(clip["path"])).duration / 1_000_000
                if not math.isfinite(duration) or duration < 0.1:
                    raise ValueError("视频时长无效")
            except (OSError, ValueError, RuntimeError, KeyError):
                unreadable += 1
                continue
            rows.append({
                "nodeId": clip["id"], "versionId": clip["versionId"],
                "workChainId": clip.get("workChainId") or "",
                "shotGroupId": clip.get("shotGroupId") or "",
                "durationSec": round(duration, 3),
                "boundaryKind": clip.get("boundaryKind") or "ordinary_cut",
                "audioBoundaryKind": clip.get("audioBoundaryKind") or "hard_cut",
                "mustKeepTail": (index + 1 < len(clips)
                                 and clips[index + 1].get("boundaryKind") == "direct_continuation"),
            })
        return rows, unreadable

    project_dir = PROJECTS_DIR / str(project_id or "")
    meta = _read_json(project_dir / "project.json", {})
    if not isinstance(meta, dict) or not project_dir.is_dir():
        raise FileNotFoundError("项目不存在")
    episodes = [row for row in meta.get("episodes") or [] if isinstance(row, dict)]
    episode_rows: list[dict[str, Any]] = []
    for index, episode in enumerate(episodes):
        episode_id = str(episode.get("id") or f"E{index + 1:02d}")
        plan = _episode_video_plan(project_id, episode_id, item_order=index)
        generated = len(plan["clips"])
        stale = int(plan.get("staleAllocationCount") or 0)
        missing = int(plan.get("missingAllocationCount") or 0)
        if generated <= 0 and stale <= 0 and missing <= 0:
            continue
        choices, unreadable = clip_choices([clip for clip in plan["clips"] if clip.get("kind") == "work_chain"])
        episode_rows.append(
            {
                "id": episode_id,
                "title": str(episode.get("title") or f"第 {index + 1} 集"),
                "order": index + 1,
                "canvasCount": plan["canvasCount"],
                "workChainCount": plan["totalChains"],
                "workChainVideoCount": plan["workChainVideoCount"],
                "otherVideoCount": plan["otherVideoCount"],
                "generatedVideoCount": generated,
                "staleAllocationCount": stale,
                "missingAllocationCount": missing,
                "unreadableVideoCount": unreadable,
                "eligible": generated > 0 and stale == 0 and missing == 0 and unreadable == 0,
                "clips": choices,
            }
        )
    custom_rows: list[dict[str, Any]] = []
    for index, canvas in enumerate(_custom_canvas_rows(project_id)):
        canvas_id = str(canvas.get("canvasId") or "").strip()
        if not canvas_id:
            continue
        plan = _custom_canvas_video_plan(project_id, canvas, item_order=index)
        generated = len(plan["clips"])
        if generated <= 0:
            continue
        choices, unreadable = clip_choices(plan["clips"])
        custom_rows.append(
            {
                "id": canvas_id,
                "canvasId": canvas_id,
                "storageKey": str(canvas.get("storageKey") or canvas_id),
                "title": str(canvas.get("title") or "自定义画布"),
                "order": index + 1,
                "canvasCount": plan["canvasCount"],
                "workChainCount": plan["totalChains"],
                "workChainVideoCount": plan["workChainVideoCount"],
                "otherVideoCount": plan["otherVideoCount"],
                "generatedVideoCount": generated,
                "unreadableVideoCount": unreadable,
                "eligible": generated > 0 and unreadable == 0,
                "clips": choices,
            }
        )
    return {
        "success": True,
        "projectId": project_id,
        "episodes": episode_rows,
        "sources": {
            "workChain": {"entries": episode_rows},
            "custom": {"entries": custom_rows},
        },
    }


def _safe_draft_name(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" .")
    return name[:100] or "ai-video_剪映草稿"


def _unique_draft_name(root: Path, base: str) -> str:
    if not (root / base).exists():
        return base
    for index in range(2, 10000):
        candidate = f"{base}_{index}"
        if not (root / candidate).exists():
            return candidate
    raise FileExistsError("无法创建唯一的剪映草稿目录")


def _project_draft_size(project_id: str) -> tuple[int, int]:
    config = _read_json(PROJECTS_DIR / project_id / "config.json", {})
    aspect = str((config or {}).get("aspect_ratio") or "16:9")
    return (1080, 1920) if aspect == "9:16" else (1920, 1080)


def _create_jianying_episode_draft_unlocked(
    project_id: str,
    project_title: str,
    episode: dict[str, Any],
    draft_root: Path,
    jianying_version: str,
    cancellation_check: Any = None,
    draft_name: str | None = None,
    clips_override: list[dict[str, Any]] | None = None,
    source_mode: str = "work_chain",
) -> dict[str, Any]:
    import pyJianYingDraft as draft
    from pyJianYingDraft import TrackSpec, TrackType, VideoMaterial, VideoSegment, trange

    episode_id = str(episode.get("id") or "")
    clips = list(clips_override) if clips_override is not None else _episode_clip_plan(project_id, episode_id)["clips"]
    if not clips:
        raise ValueError(f"{episode.get('title') or episode_id} 没有可导出视频")
    if callable(cancellation_check) and cancellation_check():
        raise _TransferCancelled()
    draft_root.mkdir(parents=True, exist_ok=True)
    base = _safe_draft_name(f"{project_title}_{episode.get('title') or episode_id}")
    draft_name = draft_name or _unique_draft_name(draft_root, base)
    width, height = _project_draft_size(project_id)
    draft_dir = draft_root / draft_name
    try:
        folder = draft.DraftFolder(str(draft_root))
        script_file = folder.create_draft(draft_name, width=width, height=height, allow_replace=False)
        assets_dir = draft_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        video_track = script_file.append_track(TrackSpec(TrackType.video))
        offset = 0
        manifest_clips: list[dict[str, Any]] = []
        for index, clip in enumerate(clips, start=1):
            if callable(cancellation_check) and cancellation_check():
                raise _TransferCancelled()
            source = Path(clip["path"])
            filename = f"{index:03d}_{_safe_draft_name(str(clip.get('workChainId') or clip.get('id')))}{source.suffix.lower()}"
            target = assets_dir / filename
            shutil.copy2(source, target)
            if callable(cancellation_check) and cancellation_check():
                raise _TransferCancelled()
            material = VideoMaterial(str(target))
            edit = clip.get("editPlan") if isinstance(clip.get("editPlan"), dict) else {}
            source_start = round(float(edit.get("inSec") or 0) * 1_000_000)
            source_end = (round(float(edit["outSec"]) * 1_000_000)
                          if edit.get("outSec") is not None else material.duration)
            if source_start < 0 or source_end > material.duration + 10_000 or source_end - source_start < 100_000:
                raise ValueError(f"片段 {clip.get('id')} 的入出点超出素材范围或不足 0.1 秒")
            source_end = min(source_end, material.duration)
            if (index < len(clips) and clips[index].get("boundaryKind") == "direct_continuation"
                    and source_end < material.duration - 10_000):
                raise ValueError("下一段采用无切镜直续，当前片段须保留用于生成下一段首帧的实际末帧")
            duration = source_end - source_start
            script_file.add_segment(
                VideoSegment(material, trange(offset, duration),
                             source_timerange=trange(source_start, duration)),
                track=video_track,
            )
            offset += duration
            manifest_clips.append(
                {
                    "nodeId": clip.get("id"),
                    "sourceNodeId": clip.get("sourceNodeId"),
                    "versionId": clip.get("versionId"),
                    "workChainId": clip.get("workChainId"),
                    "routeId": clip.get("routeId"),
                    "file": f"assets/{filename}",
                    "inSec": round(source_start / 1_000_000, 3),
                    "outSec": round(source_end / 1_000_000, 3),
                    "boundaryKind": clip.get("boundaryKind") or "ordinary_cut",
                    "audioBoundaryKind": clip.get("audioBoundaryKind") or "hard_cut",
                }
            )
        if callable(cancellation_check) and cancellation_check():
            raise _TransferCancelled()
        script_file.save()
        content_path = draft_dir / "draft_content.json"
        if jianying_version != "5" and content_path.is_file():
            content_path.replace(draft_dir / "draft_info.json")
        _write_json(
            draft_dir / "ai-video-export.json",
            {
                "kind": "ai-video-jianying-draft",
                "projectId": project_id,
                "sourceMode": source_mode,
                "episodeId": episode_id if source_mode == "work_chain" else "",
                "canvasId": episode_id if source_mode == "custom" else "",
                "clips": manifest_clips,
            },
        )
        return {"episodeId": episode_id, "draftDir": str(draft_dir), "exportedVideoCount": len(clips)}
    except Exception:
        if draft_dir.exists():
            shutil.rmtree(draft_dir, ignore_errors=True)
        raise


def _replace_jianying_draft_path(value: Any, old_root: Path, new_root: Path) -> Any:
    if isinstance(value, dict):
        return {key: _replace_jianying_draft_path(item, old_root, new_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_jianying_draft_path(item, old_root, new_root) for item in value]
    if isinstance(value, str):
        return value.replace(str(old_root), str(new_root)).replace(old_root.as_posix(), new_root.as_posix())
    return value


def _rewrite_jianying_draft_paths(draft_dir: Path, final_dir: Path) -> None:
    for path in draft_dir.rglob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rewritten = _replace_jianying_draft_path(payload, draft_dir, final_dir)
        if rewritten != payload:
            path.write_text(json.dumps(rewritten, ensure_ascii=False, indent=2), encoding="utf-8")


def _create_jianying_episode_draft(
    project_id: str,
    project_title: str,
    episode: dict[str, Any],
    draft_root: Path,
    jianying_version: str,
    cancellation_check: Any = None,
    clips_override: list[dict[str, Any]] | None = None,
    source_mode: str = "work_chain",
) -> dict[str, Any]:
    with _JIANYING_DRAFT_LOCK:
        draft_root.mkdir(parents=True, exist_ok=True)
        episode_id = str(episode.get("id") or "")
        base = _safe_draft_name(f"{project_title}_{episode.get('title') or episode_id}")
        draft_name = _unique_draft_name(draft_root, base)
        final_dir = draft_root / draft_name
        staging_root = draft_root.parent / f".{draft_root.name}-ai-video-jianying-{uuid.uuid4().hex}"
        try:
            result = _create_jianying_episode_draft_unlocked(
                project_id,
                project_title,
                episode,
                staging_root,
                jianying_version,
                cancellation_check,
                draft_name,
                clips_override,
                source_mode,
            )
            staged_dir = Path(str(result.get("draftDir") or ""))
            _rewrite_jianying_draft_paths(staged_dir, final_dir)
            if callable(cancellation_check) and cancellation_check():
                raise _TransferCancelled()
            if final_dir.exists():
                raise FileExistsError("剪映草稿目录已被其他程序占用，请重试导出")
            os.rename(staged_dir, final_dir)
            return {**result, "draftDir": str(final_dir)}
        finally:
            if staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)


def _project_export_meta(project_id: str) -> dict[str, Any]:
    meta = _read_json(PROJECTS_DIR / project_id / "project.json", {})
    if not isinstance(meta, dict):
        raise FileNotFoundError("项目不存在")
    return meta


def _selected_work_chain_export_items(
    project_id: str,
    selected_ids: list[str],
    *,
    jianying_only: bool,
) -> list[dict[str, Any]]:
    meta = _project_export_meta(project_id)
    episodes = [row for row in meta.get("episodes") or [] if isinstance(row, dict)]
    requested = set(dict.fromkeys(selected_ids))
    episode_ids = {
        str(row.get("id") or f"E{index + 1:02d}")
        for index, row in enumerate(episodes)
    }
    missing_ids = [episode_id for episode_id in selected_ids if episode_id not in episode_ids]
    if missing_ids:
        raise ValueError(f"所选分集不存在：{', '.join(missing_ids)}")
    items: list[dict[str, Any]] = []
    for index, episode in enumerate(episodes):
        episode_id = str(episode.get("id") or f"E{index + 1:02d}")
        if episode_id not in requested:
            continue
        plan = _episode_video_plan(project_id, episode_id, item_order=index)
        if plan.get("staleAllocationCount"):
            raise ValueError(f"{episode_id} 的分镜脚本已变化，请重新分配并生成受影响的视频后再导出")
        if plan.get("missingAllocationCount"):
            raise ValueError(f"{episode_id} 还有分配的分镜视频未生成，完成全部视频任务后再导出")
        clips = (
            [clip for clip in plan["clips"] if clip.get("kind") == "work_chain"]
            if jianying_only
            else list(plan["clips"])
        )
        items.append(
            {
                "id": episode_id,
                "title": str(episode.get("title") or f"第 {index + 1} 集"),
                "order": index,
                "clips": clips,
            }
        )
    return items


def _selected_custom_canvas_export_items(
    project_id: str,
    selected_ids: list[str],
) -> list[dict[str, Any]]:
    requested = set(dict.fromkeys(selected_ids))
    rows = _custom_canvas_rows(project_id)
    canvas_ids = {str(row.get("canvasId") or "") for row in rows if row.get("canvasId")}
    missing_ids = [canvas_id for canvas_id in selected_ids if canvas_id not in canvas_ids]
    if missing_ids:
        raise ValueError(f"所选自定义画布不存在：{', '.join(missing_ids)}")
    items: list[dict[str, Any]] = []
    for index, canvas in enumerate(rows):
        canvas_id = str(canvas.get("canvasId") or "").strip()
        if not canvas_id or canvas_id not in requested:
            continue
        plan = _custom_canvas_video_plan(project_id, canvas, item_order=index)
        items.append(
            {
                "id": canvas_id,
                "title": str(canvas.get("title") or "自定义画布"),
                "order": index,
                "clips": list(plan["clips"]),
            }
        )
    return items


def _run_jianying_draft_export(
    task_id: str,
    project_id: str,
    source_mode: str,
    selected_ids: list[str],
    draft_root: Path,
    jianying_version: str,
    clip_edits: list[dict[str, Any]] | None = None,
) -> None:
    results: list[dict[str, Any]] = []

    def cleanup_created_drafts() -> None:
        resolved_root = draft_root.resolve()
        for result in reversed(results):
            draft_text = str(result.get("draftDir") or "").strip()
            if not draft_text:
                continue
            try:
                draft_dir = Path(draft_text).resolve()
            except OSError:
                continue
            if draft_dir == resolved_root or resolved_root not in draft_dir.parents:
                continue
            if draft_dir.is_dir():
                shutil.rmtree(draft_dir, ignore_errors=True)

    try:
        meta = _project_export_meta(project_id)
        project_title = str(meta.get("title") or meta.get("name") or project_id)
        selected = (
            _selected_custom_canvas_export_items(project_id, selected_ids)
            if source_mode == "custom"
            else _selected_work_chain_export_items(project_id, selected_ids, jianying_only=True)
        )
        ineligible = [str(item.get("title") or item.get("id") or "未命名") for item in selected if not item["clips"]]
        if ineligible:
            label = "自定义画布" if source_mode == "custom" else "分集"
            raise ValueError(f"以下{label}没有可导出视频：{', '.join(ineligible)}")
        edit_map = {
            (str(row["canvasId"]), str(row["nodeId"])): row
            for row in clip_edits or []
        }
        available_edit_keys = {
            (str(item["id"]), str(clip["id"]))
            for item in selected for clip in item["clips"]
        }
        if set(edit_map) - available_edit_keys:
            raise ValueError("剪辑片段已变化或不属于本次导出，请刷新列表")
        for index, item in enumerate(selected, start=1):
            if _task_cancelled(task_id):
                raise _TransferCancelled()
            _update_transfer_task(
                task_id,
                status="running",
                progress=max(5, round((index - 1) / len(selected) * 90)),
                message=f"正在生成剪映草稿 {index}/{len(selected)}。",
            )
            selected_clips = []
            for clip in item["clips"]:
                edit = edit_map.get((str(item["id"]), str(clip["id"])))
                if edit and str(edit["versionId"]) != str(clip.get("versionId") or ""):
                    raise ValueError("剪辑片段版本已变化，请刷新列表重新设置入出点")
                selected_clips.append({**clip, **({"editPlan": edit} if edit else {})})
            results.append(
                _create_jianying_episode_draft(
                    project_id,
                    project_title,
                    {"id": item["id"], "title": item["title"]},
                    draft_root,
                    jianying_version,
                    lambda: _task_cancelled(task_id),
                    selected_clips,
                    source_mode,
                )
            )
        if _task_cancelled(task_id):
            raise _TransferCancelled()
        completed = _update_transfer_task(
            task_id,
            "task_completed",
            status="completed",
            progress=100,
            message=f"已生成 {len(results)} 个剪映草稿。",
            notice="剪映草稿导出完成。",
            completedAt=_now_ms(),
            draftPath=str(draft_root),
            result={"drafts": results},
        )
        if not completed:
            raise _TransferCancelled()
        _emit_agent_event("jianying_export_completed", completed)
    except _TransferCancelled:
        cleanup_created_drafts()
        return
    except Exception as exc:
        cleanup_created_drafts()
        debug = traceback.format_exc()
        print(debug, flush=True)
        failed = _update_transfer_task(
            task_id,
            "task_failed",
            status="failed",
            progress=0,
            failedAt=_now_ms(),
            **_task_failure_fields(str(exc), prefix="剪映草稿导出失败", traceback_text=debug),
        )
        if failed:
            _emit_agent_event("jianying_export_failed", failed)
    finally:
        unregister_background_task_thread(task_id)


def start_jianying_draft_export(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    project_id = str(payload.get("projectId") or payload.get("project_id") or "").strip()
    if not project_id or not (PROJECTS_DIR / project_id / "project.json").is_file():
        raise FileNotFoundError("项目不存在")
    source_mode = str(payload.get("sourceMode") or payload.get("source_mode") or "work_chain").strip()
    if source_mode not in {"work_chain", "custom"}:
        source_mode = "work_chain"
    if source_mode == "custom":
        raw_ids = payload.get("customCanvasIds") or payload.get("custom_canvas_ids") or []
    else:
        raw_ids = payload.get("episodeIds") or payload.get("episode_ids") or []
    selected_ids = [
        str(item).strip()
        for item in raw_ids
        if str(item).strip()
    ]
    if not selected_ids:
        raise ValueError("请至少选择一个自定义画布" if source_mode == "custom" else "请至少选择一集")
    draft_text = str(payload.get("draftPath") or payload.get("draft_path") or "").strip()
    if not draft_text:
        raise ValueError("请选择剪映草稿目录")
    draft_root = Path(draft_text).expanduser()
    draft_root.mkdir(parents=True, exist_ok=True)
    version = str(payload.get("jianyingVersion") or "6")
    if version not in {"5", "6"}:
        raise ValueError("剪映版本仅支持 5 或 6")
    raw_clip_edits = payload.get("clipEdits") or []
    if not isinstance(raw_clip_edits, list):
        raise ValueError("剪辑入出点必须是片段列表")
    clip_edits: list[dict[str, Any]] = []
    seen_edit_keys: set[tuple[str, str]] = set()
    for raw in raw_clip_edits:
        if not isinstance(raw, dict):
            raise ValueError("剪辑片段参数无效")
        canvas_id = str(raw.get("canvasId") or "").strip()
        node_id = str(raw.get("nodeId") or "").strip()
        version_id = str(raw.get("versionId") or "").strip()
        if not canvas_id or not node_id or not version_id or canvas_id not in selected_ids:
            raise ValueError("剪辑片段缺少当前画布、节点或版本")
        key = (canvas_id, node_id)
        if key in seen_edit_keys:
            raise ValueError("同一剪辑片段重复设置入出点")
        seen_edit_keys.add(key)
        try:
            in_sec = float(raw.get("inSec", 0))
            out_sec = float(raw["outSec"])
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("剪辑入出点必须是秒数") from exc
        if not math.isfinite(in_sec) or not math.isfinite(out_sec) or in_sec < 0 or out_sec - in_sec < 0.1:
            raise ValueError("剪辑入出点无效或片段不足 0.1 秒")
        clip_edits.append({"canvasId": canvas_id, "nodeId": node_id,
                           "versionId": version_id, "inSec": in_sec, "outSec": out_sec})
    task = create_task(
        "jianying_draft_export",
        project_id=project_id,
        message="剪映草稿导出任务已创建。",
        status="created",
        progress=0,
    )
    task = _update_task_fields(
        task["id"],
        draftPath=str(draft_root),
        sourceMode=source_mode,
        episodeIds=selected_ids if source_mode == "work_chain" else [],
        customCanvasIds=selected_ids if source_mode == "custom" else [],
    ) or task
    _emit_task_update(task, "task_created")
    _start_background_task(
        task,
        _run_jianying_draft_export,
        project_id,
        source_mode,
        selected_ids,
        draft_root,
        version,
        clip_edits,
    )
    return {"success": True, "task": task, "draftPath": str(draft_root)}


def _unique_video_export_path(root: Path, filename: str, source: Path) -> Path:
    candidate = root / filename
    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(1, 10000):
        try:
            if candidate.resolve() != source.resolve() and not candidate.exists():
                return candidate
        except OSError:
            if not candidate.exists():
                return candidate
        candidate = root / f"{stem}_{index}{suffix}"
    raise FileExistsError("无法创建唯一的视频导出文件名")


def _run_video_files_export(
    task_id: str,
    project_id: str,
    source_mode: str,
    selected_ids: list[str],
    destination: Path,
) -> None:
    copied: list[Path] = []

    def cleanup_copied_files() -> None:
        for path in reversed(copied):
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                continue

    try:
        items = (
            _selected_custom_canvas_export_items(project_id, selected_ids)
            if source_mode == "custom"
            else _selected_work_chain_export_items(project_id, selected_ids, jianying_only=False)
        )
        clips: list[dict[str, Any]] = []
        for item in items:
            for clip in item["clips"]:
                clips.append({**clip, "sourceTitle": item["title"], "sourceId": item["id"]})
        if not clips:
            raise ValueError("没有可导出的视频")
        destination.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        for index, clip in enumerate(clips, start=1):
            if _task_cancelled(task_id):
                raise _TransferCancelled()
            source = Path(clip["path"])
            filename = (
                f"{index:03d}_"
                f"{_safe_draft_name(str(clip.get('sourceTitle') or clip.get('sourceId') or '视频'))}_"
                f"{_safe_draft_name(str(clip.get('sourceNodeId') or clip.get('id') or 'clip'))}"
                f"{source.suffix.lower()}"
            )
            target = _unique_video_export_path(destination, filename, source)
            _update_transfer_task(
                task_id,
                status="running",
                progress=max(5, round((index - 1) / len(clips) * 90)),
                message=f"正在导出视频 {index}/{len(clips)}。",
            )
            shutil.copy2(source, target)
            copied.append(target)
            results.append(
                {
                    "nodeId": clip.get("id"),
                    "sourceNodeId": clip.get("sourceNodeId"),
                    "versionId": clip.get("versionId"),
                    "sourceId": clip.get("sourceId"),
                    "sourceTitle": clip.get("sourceTitle"),
                    "file": str(target),
                }
            )
        if _task_cancelled(task_id):
            raise _TransferCancelled()
        completed = _update_transfer_task(
            task_id,
            "task_completed",
            status="completed",
            progress=100,
            message=f"已导出 {len(results)} 个视频。",
            notice="视频文件导出完成。",
            completedAt=_now_ms(),
            destinationPath=str(destination),
            result={"files": results},
        )
        if not completed:
            raise _TransferCancelled()
    except _TransferCancelled:
        cleanup_copied_files()
        return
    except Exception as exc:
        cleanup_copied_files()
        debug = traceback.format_exc()
        print(debug, flush=True)
        _update_transfer_task(
            task_id,
            "task_failed",
            status="failed",
            progress=0,
            failedAt=_now_ms(),
            **_task_failure_fields(str(exc), prefix="视频文件导出失败", traceback_text=debug),
        )
    finally:
        unregister_background_task_thread(task_id)


def start_video_files_export(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    project_id = str(payload.get("projectId") or payload.get("project_id") or "").strip()
    if not project_id or not (PROJECTS_DIR / project_id / "project.json").is_file():
        raise FileNotFoundError("项目不存在")
    source_mode = str(payload.get("sourceMode") or payload.get("source_mode") or "work_chain").strip()
    if source_mode not in {"work_chain", "custom"}:
        source_mode = "work_chain"
    if source_mode == "custom":
        raw_ids = payload.get("customCanvasIds") or payload.get("custom_canvas_ids") or []
    else:
        raw_ids = payload.get("episodeIds") or payload.get("episode_ids") or []
    selected_ids = [str(item).strip() for item in raw_ids if str(item).strip()]
    if not selected_ids:
        raise ValueError("请至少选择一个自定义画布" if source_mode == "custom" else "请至少选择一集")
    destination_text = str(
        payload.get("destinationPath")
        or payload.get("destination_path")
        or payload.get("exportPath")
        or ""
    ).strip()
    if not destination_text:
        raise ValueError("请选择视频导出目录")
    destination = Path(destination_text).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    task = create_task(
        "video_files_export",
        project_id=project_id,
        message="视频文件导出任务已创建。",
        status="created",
        progress=0,
    )
    task = _update_task_fields(
        task["id"],
        destinationPath=str(destination),
        sourceMode=source_mode,
        episodeIds=selected_ids if source_mode == "work_chain" else [],
        customCanvasIds=selected_ids if source_mode == "custom" else [],
    ) or task
    _emit_task_update(task, "task_created")
    _start_background_task(
        task,
        _run_video_files_export,
        project_id,
        source_mode,
        selected_ids,
        destination,
    )
    return {"success": True, "task": task, "destinationPath": str(destination)}


__all__ = (
    "HOME_ARCHIVE_MANIFEST",
    "HOME_ARCHIVE_FORMAT",
    "recover_home_archive_imports",
    "start_home_archive_export",
    "start_home_archive_import",
    "detect_jianying_draft_root",
    "get_jianying_export_info",
    "start_jianying_draft_export",
    "start_video_files_export",
)
