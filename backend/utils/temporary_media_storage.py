# -*- coding: utf-8 -*-
"""On-demand Qiniu transport; cloud expiry is entirely managed by Qiniu."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse


DELETE_AFTER_DAYS = 3
MIN_REMAINING_SECONDS = 3600
_LOCKS = [threading.Lock() for _ in range(64)]
_CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "temporary-media.sqlite3"


def _configuration() -> dict:
    # PLUGIN_DATA is injected by the host when the backend process starts.
    # Never persist or return this document (it contains storage credentials).
    try:
        document = json.loads(os.environ.get("PLUGIN_DATA") or "{}")
    except (ValueError, TypeError):
        raise ValueError("PLUGIN_DATA 不是有效 JSON，无法读取七牛配置") from None
    configs = document.get("upload_configs") if isinstance(document, dict) else None
    matches = [row.get("config") for row in (configs or [])
               if isinstance(row, dict) and row.get("provider") == "qiniu"]
    if len(matches) != 1 or not isinstance(matches[0], dict):
        raise ValueError("PLUGIN_DATA 需要提供唯一的七牛上传配置")
    config = matches[0]
    for field in ("bucket_name", "access_key", "secret_key", "upload_url", "cdn_url"):
        if not isinstance(config.get(field), str) or not config[field].strip():
            raise ValueError(f"七牛上传配置缺少 {field}")
    result = {key: value.strip() if isinstance(value, str) else value for key, value in config.items()}
    for field in ("upload_url", "cdn_url"):
        parsed = urlparse(result[field])
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError(f"七牛 {field} 必须为有效 HTTPS 地址")
    if urlparse(result["upload_url"]).path.strip("/"):
        raise ValueError("七牛 upload_url 应为上传域名，不应包含路径")
    return result


def _cache_record(namespace: str, digest: str, record: dict | None = None) -> dict | None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(_CACHE_PATH), timeout=30) as db:
        db.execute("CREATE TABLE IF NOT EXISTS uploads (namespace TEXT, digest TEXT, record TEXT NOT NULL, PRIMARY KEY(namespace, digest))")
        if record is not None:
            db.execute("INSERT OR REPLACE INTO uploads VALUES (?, ?, ?)",
                       (namespace, digest, json.dumps(record, ensure_ascii=False)))
            return record
        row = db.execute("SELECT record FROM uploads WHERE namespace=? AND digest=?", (namespace, digest)).fetchone()
        return json.loads(row[0]) if row else None


def ensure_public_url(local_file: str | Path, media_type: str) -> dict:
    """Return URL/key metadata, reusing an existing object with enough lifetime.

    This runs inside the existing generation worker, never during canvas import.
    No local timer, deletion API, or bucket-wide lifecycle mutation is used.
    """
    if media_type not in {"video", "image", "audio"}:
        raise ValueError("不支持的临时素材类型")
    path = Path(local_file).resolve(strict=True)
    suffix = path.suffix.lower()
    mime = mimetypes.guess_type(path.name)[0] or ""
    if not path.is_file() or not mime.startswith(media_type + "/"):
        raise ValueError("临时素材类型与文件格式不一致")
    original_stat = path.stat()
    if original_stat.st_size <= 0:
        raise ValueError("不能上传空文件")
    config = _configuration()
    try:
        from qiniu import Auth, BucketManager, etag, put_file_v2
        from qiniu.http.endpoint import Endpoint
        from qiniu.http.region import Region, ServiceName
    except ImportError:
        raise RuntimeError("当前插件运行时缺少 qiniu 依赖，请安装插件依赖后重启") from None
    digest_builder = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest_builder.update(chunk)
    digest = digest_builder.hexdigest()
    expected_etag = etag(str(path))
    namespace = hashlib.sha256(json.dumps(
        [config["access_key"], config["bucket_name"], config["upload_url"], media_type, suffix],
        ensure_ascii=False).encode("utf-8")).hexdigest()
    auth = Auth(config["access_key"], config["secret_key"])
    manager = BucketManager(auth, preferred_scheme="https")
    bucket = config["bucket_name"]

    def unchanged() -> None:
        current = path.stat()
        if (current.st_size, current.st_mtime_ns) != (original_stat.st_size, original_stat.st_mtime_ns):
            raise ValueError("素材文件已发生变化，请重新生成")

    def stat(key: str) -> dict | None:
        try:
            result, info = manager.stat(bucket, key)
        except Exception:
            raise RuntimeError("七牛素材检查失败，请检查网络和存储配置") from None
        if info.status_code == 612:
            return None
        if info.status_code != 200 or not isinstance(result, dict):
            raise RuntimeError(f"七牛素材检查失败（HTTP {info.status_code}），请检查存储权限")
        if result.get("hash") != expected_etag or result.get("fsize") != original_stat.st_size:
            raise RuntimeError("七牛同名素材校验不一致，已停止上传")
        return result

    def reusable(meta: dict) -> bool:
        uploaded = int(meta.get("putTime") or 0) / 10_000_000
        # Do not hand a model an object about to be removed while it queues.
        return uploaded + DELETE_AFTER_DAYS * 86400 > time.time() + MIN_REMAINING_SECONDS

    def finish(key: str, meta: dict, reused: bool) -> dict:
        unchanged()
        uploaded = int(meta.get("putTime") or 0) / 10_000_000
        result = {"provider": "qiniu", "bucket": bucket, "key": key,
                  "sha256": digest, "size": original_stat.st_size, "contentType": mime,
                  "uploadedAt": uploaded, "reuseUntil": uploaded + DELETE_AFTER_DAYS * 86400 - MIN_REMAINING_SECONDS,
                  "deleteAfterDays": DELETE_AFTER_DAYS}
        _cache_record(namespace, digest, result)
        # Rebuild the URL each time so a configured domain change takes effect.
        url = config["cdn_url"].rstrip("/") + "/" + quote(key, safe="/")
        if config.get("private") is True:
            url = auth.private_download_url(url, expires=MIN_REMAINING_SECONDS)
        return {**result, "url": url, "reused": reused}

    with _LOCKS[int(digest[:8], 16) % len(_LOCKS)]:
        unchanged()
        cached = _cache_record(namespace, digest)
        today = datetime.now(timezone(timedelta(hours=8))).date()
        # Exact-key probes also recover reuse after cache loss or on another PC.
        candidates = ([cached["key"]] if cached else []) + [
            f"ai-video/{media_type}/{(today - timedelta(days=age)):%Y%m%d}/{digest}{suffix}"
            for age in range(DELETE_AFTER_DAYS + 1)
        ]
        seen = set()
        for key in candidates:
            if key in seen:
                continue
            seen.add(key)
            meta = stat(key)
            if meta and reusable(meta):
                return finish(key, meta, True)
        key = f"ai-video/{media_type}/{today:%Y%m%d}/{digest}{suffix}"
        token = auth.upload_token(bucket, key, 3600, policy={
            "insertOnly": 1, "deleteAfterDays": DELETE_AFTER_DAYS,
            "fileType": 0, "fsizeLimit": original_stat.st_size,
        })
        regions = [Region(services={ServiceName.UP: [Endpoint.from_host(config["upload_url"])]})]
        try:
            result, info = put_file_v2(token, key, str(path), mime_type=mime,
                                       check_crc=True, bucket_name=bucket, regions=regions)
        except Exception:
            raise RuntimeError("七牛素材上传失败，请检查网络后重试") from None
        # Another process may have uploaded the same content concurrently.
        if info.status_code not in {200, 614}:
            raise RuntimeError(f"七牛素材上传失败（HTTP {info.status_code}）")
        if info.status_code == 200 and (not isinstance(result, dict) or result.get("key") != key or result.get("hash") != expected_etag):
            raise RuntimeError("七牛上传结果校验失败")
        meta = stat(key)
        if not meta or not reusable(meta):
            raise RuntimeError("七牛上传后未获取到有效素材，请重试")
        return finish(key, meta, info.status_code == 614)
