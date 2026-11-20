# -*- coding: utf-8 -*-
"""任务持久化、运行时字段与持久化摘要；不依赖生成编排。"""
from __future__ import annotations

from .catalogs import (
    GLOBAL_TASKS_PATH,
)
from .store_core import (
    ensure_store,
)
from typing import (
    Any,
)

import copy
import re
import threading
from .agent_sessions import (
    _persistent_media_data_removed,
    _project_dir,
)
from .catalogs import (
    PROJECTS_DIR,
)
from .store_core import (
    _read_json,
    _write_json,
)
from pathlib import (
    Path,
)


_PROJECT_TASKS_DIRNAME = "tasks"


_PROJECT_TASKS_FILENAME = "tasks.json"


_TASK_STORAGE_RETAIN_LIMIT = 200


_TASK_STORAGE_GLOBAL_KEY = "__global__"


_TASK_RUNTIME_ID_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


_TASK_PROJECT_INDEX: dict[str, str] = {}


_TASK_STORAGE_COMPACTION_CHECKED = False


_TASK_STORAGE_LOCK = threading.RLock()


def _task_project_id(task: dict[str, Any] | None) -> str:
    if not isinstance(task, dict):
        return ""
    return str(task.get("projectId") or task.get("project_id") or "").strip()


def _task_storage_key_for_project(project_id: str | None) -> str:
    return str(project_id or "").strip() or _TASK_STORAGE_GLOBAL_KEY


def _project_id_from_task_storage_key(key: str | None) -> str:
    text = str(key or "").strip()
    return "" if not text or text == _TASK_STORAGE_GLOBAL_KEY else text


def _project_tasks_path(project_id: str) -> Path:
    return _project_dir(project_id) / _PROJECT_TASKS_DIRNAME / _PROJECT_TASKS_FILENAME


def _task_storage_path(project_id: str | None = None) -> Path:
    normalized_project_id = str(project_id or "").strip()
    return _project_tasks_path(normalized_project_id) if normalized_project_id else GLOBAL_TASKS_PATH


def _safe_task_runtime_id(value: Any) -> str:
    text = str(value or "").strip()
    text = _TASK_RUNTIME_ID_PATTERN.sub("_", text).strip("._-")
    return text or "task"


def _task_runtime_jobs_dir(project_id: str | None = None) -> Path:
    return _task_storage_path(project_id).parent / "jobs"


def _task_runtime_job_path(project_id: str | None, task_id: str) -> Path:
    return _task_runtime_jobs_dir(project_id) / f"{_safe_task_runtime_id(task_id)}.json"


def _task_runtime_job_ref(task_id: str) -> str:
    return f"jobs/{_safe_task_runtime_id(task_id)}.json"


def _task_video_job_summary(job: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "phase",
        "title",
        "versionId",
        "providerJobId",
        "providerInstanceId",
        "providerId",
        "modelId",
        "modelName",
        "size",
        "aspectRatio",
        "resolution",
        "durationSeconds",
        "endpoint",
        "resumable",
        "providerCancel",
    ):
        if key in job and job.get(key) not in (None, ""):
            summary[key] = _persistent_media_data_removed(job.get(key), key=key)
    return summary


def _write_task_runtime_job(project_id: str | None, task_id: str, job: dict[str, Any]) -> None:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id or not isinstance(job, dict):
        return
    _write_json(
        _task_runtime_job_path(project_id, normalized_task_id),
        _persistent_media_data_removed(job),
    )


def _read_task_runtime_job(task: dict[str, Any]) -> dict[str, Any]:
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        return {}
    project_id = _task_project_id(task)
    job = _read_json(_task_runtime_job_path(project_id, task_id), {})
    return job if isinstance(job, dict) else {}


def _hydrate_task_runtime_fields(task: dict[str, Any]) -> dict[str, Any]:
    row = copy.deepcopy(task)
    if not isinstance(row.get("videoJob"), dict) and row.get("videoJobRef"):
        job = _read_task_runtime_job(row)
        if job:
            row["videoJob"] = job
    return row


def _task_storage_row_for_write(task: dict[str, Any], project_id: str | None = None) -> dict[str, Any]:
    row = copy.deepcopy(task)
    task_id = str(row.get("id") or "").strip()
    runtime_project_id = str(
        project_id if project_id is not None else _task_project_id(row) or ""
    ).strip()
    video_job = row.get("videoJob")
    if task_id and isinstance(video_job, dict):
        _write_task_runtime_job(runtime_project_id, task_id, video_job)
        row["videoJobRef"] = _task_runtime_job_ref(task_id)
        video_job_summary = _task_video_job_summary(video_job)
        if video_job_summary:
            row["videoJobSummary"] = video_job_summary
        row.pop("videoJob", None)
    worker_run = row.get("workerRun")
    if isinstance(worker_run, dict):
        worker_summary = _task_list_worker_run_summary(worker_run)
        if worker_summary:
            row["workerRun"] = worker_summary
        else:
            row.pop("workerRun", None)
    return _persistent_media_data_removed(row)


def _read_task_file(path: Path) -> list[dict[str, Any]]:
    data = _read_json(path, [])
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _write_task_file(path: Path, tasks: list[dict[str, Any]], project_id: str | None = None) -> list[dict[str, Any]]:
    rows = [
        _task_storage_row_for_write(task, project_id)
        for task in tasks[-_TASK_STORAGE_RETAIN_LIMIT:]
        if isinstance(task, dict)
    ]
    _write_json(path, rows)
    return rows


def _task_storage_row_needs_compaction(task: dict[str, Any]) -> bool:
    return (
        isinstance(task.get("videoJob"), dict)
        or isinstance(task.get("workerRun"), dict)
    )


def _project_task_paths() -> list[Path]:
    if not PROJECTS_DIR.exists() or not PROJECTS_DIR.is_dir():
        return []
    return sorted(PROJECTS_DIR.glob(f"*/{_PROJECT_TASKS_DIRNAME}/{_PROJECT_TASKS_FILENAME}"))


def _project_id_from_task_path(path: Path) -> str:
    try:
        return path.parents[1].name
    except IndexError:
        return ""


def _remember_task_storage(task: dict[str, Any], project_id: str | None = None) -> None:
    task_id = str(task.get("id") or "").strip() if isinstance(task, dict) else ""
    if not task_id:
        return
    normalized_project_id = _task_project_id(task) if project_id is None else str(project_id or "").strip()
    _TASK_PROJECT_INDEX[task_id] = _task_storage_key_for_project(normalized_project_id)


def _remember_task_storage_rows(tasks: list[dict[str, Any]], project_id: str | None = None) -> None:
    for task in tasks:
        _remember_task_storage(task, project_id)


def _project_exists_for_task_storage(project_id: str) -> bool:
    if not project_id:
        return False
    try:
        return _project_dir(project_id).is_dir()
    except Exception:
        return False


def _compact_task_storage_files_unlocked() -> None:
    global _TASK_STORAGE_COMPACTION_CHECKED
    if _TASK_STORAGE_COMPACTION_CHECKED:
        return
    _TASK_STORAGE_COMPACTION_CHECKED = True
    for path in [GLOBAL_TASKS_PATH, *_project_task_paths()]:
        rows = _read_task_file(path)
        if not rows or not any(_task_storage_row_needs_compaction(row) for row in rows):
            continue
        project_id = "" if path == GLOBAL_TASKS_PATH else _project_id_from_task_path(path)
        _write_task_file(path, rows, project_id)


def _ensure_task_storage_ready() -> None:
    ensure_store()
    with _TASK_STORAGE_LOCK:
        _compact_task_storage_files_unlocked()


def _load_tasks_for_project(project_id: str | None) -> list[dict[str, Any]]:
    normalized_project_id = str(project_id or "").strip()
    _ensure_task_storage_ready()
    if not normalized_project_id:
        rows = _read_task_file(GLOBAL_TASKS_PATH)
        _remember_task_storage_rows(rows, "")
        return rows
    rows = _read_task_file(_project_tasks_path(normalized_project_id))
    _remember_task_storage_rows(rows, normalized_project_id)
    return rows


def _load_task_storage_bucket(storage_key: str | None) -> list[dict[str, Any]]:
    project_id = _project_id_from_task_storage_key(storage_key)
    return _load_tasks_for_project(project_id)


def _save_task_storage_bucket(storage_key: str | None, tasks: list[dict[str, Any]]) -> None:
    project_id = _project_id_from_task_storage_key(storage_key)
    stored_tasks = _write_task_file(_task_storage_path(project_id), tasks, project_id)
    _remember_task_storage_rows(stored_tasks, project_id)


def _task_storage_key_for_task_id(task_id: str | None) -> str | None:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return None
    cached = _TASK_PROJECT_INDEX.get(normalized_task_id)
    if cached:
        return cached
    _ensure_task_storage_ready()
    global_rows = _read_task_file(GLOBAL_TASKS_PATH)
    for task in global_rows:
        if str(task.get("id") or "").strip() == normalized_task_id:
            _remember_task_storage(task, "")
            return _TASK_STORAGE_GLOBAL_KEY
    for path in _project_task_paths():
        project_id = _project_id_from_task_path(path)
        for task in _read_task_file(path):
            if str(task.get("id") or "").strip() == normalized_task_id:
                _remember_task_storage(task, project_id)
                return _task_storage_key_for_project(project_id)
    return None


def _normalized_task_status(task: dict[str, Any]) -> str:
    return str(task.get("status") or "").strip().lower()


_TASK_LIST_SUMMARY_TEXT_LIMIT = 1200


def _task_list_summary_text(value: Any, limit: int = _TASK_LIST_SUMMARY_TEXT_LIMIT) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}...（已截断）"


def _task_list_summary_values(value: Any, *, item_limit: int = 8, text_limit: int = 600) -> list[Any]:
    if not isinstance(value, list):
        return []
    rows: list[Any] = []
    for item in value[:item_limit]:
        if isinstance(item, str):
            rows.append(_task_list_summary_text(item, text_limit))
        elif isinstance(item, dict):
            rows.append(_persistent_media_data_removed(item))
        else:
            rows.append(item)
    return rows


def _task_list_model_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    summary: dict[str, Any] = {}
    for key in (
        "modelId",
        "modelLabel",
        "providerId",
        "source",
        "structuredSchema",
        "structuredMode",
        "promptChars",
        "systemPromptChars",
        "totalMs",
        "error",
    ):
        if key in value and value.get(key) not in (None, "", [], {}):
            next_value = value.get(key)
            if isinstance(next_value, str):
                next_value = _task_list_summary_text(next_value, 600)
            summary[key] = _persistent_media_data_removed(next_value, key=key)
    return summary or None


def _task_list_validation_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    summary: dict[str, Any] = {}
    for key in ("status", "pass", "success", "saveAllowed", "nonBlocking", "error"):
        if key in value and value.get(key) not in (None, "", [], {}):
            next_value = value.get(key)
            if isinstance(next_value, str):
                next_value = _task_list_summary_text(next_value, 600)
            summary[key] = _persistent_media_data_removed(next_value, key=key)
    for key in ("blockingIssues", "warnings", "reviewIssues"):
        rows = _task_list_summary_values(value.get(key), item_limit=10, text_limit=600)
        if rows:
            summary[key] = rows
    revision = value.get("revisionInstruction")
    if isinstance(revision, str) and revision.strip():
        summary["revisionInstruction"] = _task_list_summary_text(revision, 900)
    model = _task_list_model_summary(value.get("model"))
    if model:
        summary["model"] = model
    return summary or None


def _task_list_worker_attempt_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    summary: dict[str, Any] = {}
    for key in ("attempt", "status", "isRetry", "outputChars", "error", "reviewWarning", "completedAt"):
        if key in value and value.get(key) not in (None, "", [], {}):
            next_value = value.get(key)
            if isinstance(next_value, str):
                next_value = _task_list_summary_text(next_value, 600)
            summary[key] = _persistent_media_data_removed(next_value, key=key)
    model = _task_list_model_summary(value.get("modelDiagnostics") or value.get("model"))
    if model:
        summary["modelDiagnostics"] = model
    controller_validation = _task_list_validation_summary(value.get("controllerValidation"))
    if controller_validation:
        summary["controllerValidation"] = controller_validation
    semantic_review = _task_list_validation_summary(value.get("semanticReview"))
    if semantic_review:
        summary["semanticReview"] = semantic_review
    return summary or None


def _task_list_worker_run_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    summary: dict[str, Any] = {}
    for key in (
        "id",
        "workerRunId",
        "worker_run_id",
        "workerName",
        "worker_name",
        "status",
        "progress",
        "stage",
        "cyclePhase",
        "message",
        "notice",
        "typeProgress",
        "parallelTypeCycles",
        "sessionId",
    ):
        if key in value:
            summary[key] = _persistent_media_data_removed(value.get(key))
    model = _task_list_model_summary(value.get("model") or value.get("modelDiagnostics"))
    if model:
        summary["model"] = model
    controller_validation = _task_list_validation_summary(value.get("controllerValidation"))
    if controller_validation:
        summary["controllerValidation"] = controller_validation
    semantic_review = _task_list_validation_summary(value.get("semanticReview"))
    if semantic_review:
        summary["semanticReview"] = semantic_review
    for key in ("reviewRetryLimit", "reviewRerunCount", "attemptCount"):
        if key in value and value.get(key) not in (None, "", [], {}):
            summary[key] = value.get(key)
    warnings = _task_list_summary_values(value.get("warnings"), item_limit=10, text_limit=600)
    if warnings:
        summary["warnings"] = warnings
    attempts = value.get("attempts") if isinstance(value.get("attempts"), list) else []
    if attempts:
        compact_attempts = [
            attempt_summary
            for attempt_summary in (
                _task_list_worker_attempt_summary(row) for row in attempts[-3:]
            )
            if attempt_summary
        ]
        if compact_attempts:
            summary["attempts"] = compact_attempts
    return summary or None


def _delete_task_runtime_job(project_id: str | None, task_id: str) -> bool:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return False
    path = _task_runtime_job_path(project_id, normalized_task_id)
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def _load_tasks() -> list[dict[str, Any]]:
    _ensure_task_storage_ready()
    tasks = _read_task_file(GLOBAL_TASKS_PATH)
    _remember_task_storage_rows(tasks, "")
    for path in _project_task_paths():
        project_id = _project_id_from_task_path(path)
        rows = _read_task_file(path)
        _remember_task_storage_rows(rows, project_id)
        tasks.extend(rows)
    return tasks


def _load_task_listing_snapshot(project_id: str | None = None, *, global_only: bool = False) -> list[dict[str, Any]]:
    normalized_project_id = str(project_id or "").strip()
    if not _TASK_STORAGE_COMPACTION_CHECKED:
        _ensure_task_storage_ready()
    else:
        ensure_store()
    if normalized_project_id:
        rows = _read_task_file(_project_tasks_path(normalized_project_id))
        _remember_task_storage_rows(rows, normalized_project_id)
        return rows
    if global_only:
        rows = _read_task_file(GLOBAL_TASKS_PATH)
        _remember_task_storage_rows(rows, "")
        return rows
    return _load_tasks()


def _save_tasks(tasks: list[dict[str, Any]]) -> None:
    _ensure_task_storage_ready()
    global_tasks: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        project_id = _task_project_id(task)
        if project_id and _project_exists_for_task_storage(project_id):
            grouped.setdefault(project_id, []).append(task)
        else:
            global_tasks.append(task)
    stored_global_tasks = _write_task_file(GLOBAL_TASKS_PATH, global_tasks, "")
    _remember_task_storage_rows(stored_global_tasks, "")
    for project_id, rows in grouped.items():
        stored_project_tasks = _write_task_file(_project_tasks_path(project_id), rows, project_id)
        _remember_task_storage_rows(stored_project_tasks, project_id)
