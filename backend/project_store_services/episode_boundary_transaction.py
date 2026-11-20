"""Recoverable filesystem transaction for an episode-boundary commit."""
from __future__ import annotations

import re
import shutil
import traceback
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Iterator

from .store_core import _read_json, _write_json


EPISODE_COMMIT_LOCK = RLock()
_JOURNAL_DIR = ".episode-boundary-commit"
_FILES = ("source_coverage.json", "project.json", "versions/resource_revisions.json")


def _transaction_dir(project_id: str) -> Path:
    from .agent_sessions import _project_dir

    return _project_dir(project_id) / _JOURNAL_DIR


def _safe_episode_id(value: str) -> str:
    episode_id = str(value or "").strip()
    if episode_id in {"", ".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]+", episode_id):
        raise ValueError("分集 ID 无效")
    return episode_id


def _restore_file(backup: Path, target: Path, existed: bool) -> None:
    if not existed:
        target.unlink(missing_ok=True)
        return
    if not backup.is_file():
        raise RuntimeError(f"分集提交回滚缺少备份：{target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.episode-restore.tmp")
    shutil.copy2(backup, temporary)
    temporary.replace(target)


def recover_episode_boundary_commit(project_id: str) -> None:
    """Roll back an interrupted commit, or remove a completed commit's journal."""
    from .agent_sessions import _project_dir

    with EPISODE_COMMIT_LOCK:
        transaction_dir = _transaction_dir(project_id)
        if not transaction_dir.exists():
            return
        journal_path = transaction_dir / "journal.json"
        if not journal_path.is_file():
            # No business file is changed before the journal is durable.
            shutil.rmtree(transaction_dir)
            return
        journal = _read_json(journal_path, {})
        if not isinstance(journal, dict) or journal.get("version") != 1:
            raise RuntimeError("分集提交恢复记录无效，请核查项目状态")
        if journal.get("phase") != "committed":
            project_root = _project_dir(project_id)
            for row in journal.get("files") or []:
                relative = str(row.get("path") or "")
                if relative not in _FILES:
                    raise RuntimeError("分集提交恢复记录包含无效路径")
                _restore_file(transaction_dir / "backup" / relative,
                              project_root / relative, bool(row.get("existed")))
            for row in journal.get("episodes") or []:
                episode_id = _safe_episode_id(row.get("id"))
                target = project_root / "episodes" / episode_id
                backup = transaction_dir / "backup" / "episodes" / episode_id
                if target.exists():
                    shutil.rmtree(target)
                if row.get("existed"):
                    if not backup.is_dir():
                        raise RuntimeError(f"分集提交回滚缺少备份：{episode_id}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(backup, target)
        shutil.rmtree(transaction_dir)


@contextmanager
def episode_boundary_transaction(project_id: str, episode_ids: list[str]) -> Iterator[None]:
    from .agent_sessions import _project_dir

    # The caller holds EPISODE_COMMIT_LOCK across validation and mutation.
    recover_episode_boundary_commit(project_id)
    project_root = _project_dir(project_id)
    transaction_dir = _transaction_dir(project_id)
    backup_dir = transaction_dir / "backup"
    file_rows: list[dict[str, object]] = []
    episode_rows: list[dict[str, object]] = []
    try:
        for relative in _FILES:
            source = project_root / relative
            existed = source.is_file()
            file_rows.append({"path": relative, "existed": existed})
            if existed:
                target = backup_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        for episode_id in dict.fromkeys(_safe_episode_id(item) for item in episode_ids):
            source = project_root / "episodes" / episode_id
            existed = source.is_dir()
            episode_rows.append({"id": episode_id, "existed": existed})
            if existed:
                target = backup_dir / "episodes" / episode_id
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, target)
        journal = {"version": 1, "phase": "prepared", "files": file_rows, "episodes": episode_rows}
        _write_json(transaction_dir / "journal.json", journal)
    except Exception:
        # Preparation did not touch project data.
        shutil.rmtree(transaction_dir, ignore_errors=True)
        raise
    try:
        yield
    except BaseException:
        recover_episode_boundary_commit(project_id)
        raise
    else:
        try:
            _write_json(transaction_dir / "journal.json", {**journal, "phase": "committed"})
        except Exception:
            recover_episode_boundary_commit(project_id)
            raise
        try:
            shutil.rmtree(transaction_dir)
        except Exception:
            # The committed marker makes later cleanup safe and idempotent.
            print(traceback.format_exc(), flush=True)
