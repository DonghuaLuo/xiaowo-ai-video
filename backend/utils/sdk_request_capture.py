"""Loopback streaming proxy that archives every actual SDK HTTP request."""
from __future__ import annotations

import asyncio
import codecs
import copy
import json
import threading
import traceback
import os
import ssl
import socket
import sys
import urllib.request
import uuid
from collections.abc import Callable
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qsl, quote, quote_plus, unquote, unquote_plus, urljoin, urlsplit, urlunsplit



_HOP_HEADERS = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
})
_AUTH_HEADERS = frozenset({"authorization", "x-api-key", "x-goog-api-key", "api-key", "api_key"})
_AUTH_QUERY = frozenset({"key", "api_key", "apikey", "api-key", "access_token", "token"})


def _url_secrets(url: str) -> set[str]:
    query = urlsplit(url).query
    values = {value for key, value in parse_qsl(query) if key.casefold() in _AUTH_QUERY and value}
    # Keep the exact encoding too (including lowercase percent escapes).
    values.update(part.partition("=")[2] for part in query.split("&")
                  if unquote_plus(part.partition("=")[0]).casefold() in _AUTH_QUERY and part.partition("=")[2])
    return values


def _origin(url: str) -> tuple[str, str | None, int]:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def _upstream_proxy(url: str, environment: dict[str, str]) -> str | None:
    proxies = {}
    # Lowercase wins, matching the conventional precedence of proxy variables.
    for key, value in sorted(environment.items(), key=lambda item: item[0].islower()):
        if key.casefold().endswith("_proxy"):
            proxies[key[:-6].casefold()] = value
    parsed = urlsplit(url)
    if urllib.request.proxy_bypass_environment(parsed.netloc, proxies):
        return None
    return proxies.get(parsed.scheme) or proxies.get("all") or None


def _upstream_tls_context(environment: dict[str, str]) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=environment.get("SSL_CERT_FILE") or None,
                                         capath=environment.get("SSL_CERT_DIR") or None)
    # The CLI can trust an additional private CA; preserve that explicit choice.
    if environment.get("NODE_EXTRA_CA_CERTS"):
        context.load_verify_locations(cafile=environment["NODE_EXTRA_CA_CERTS"])
    return context


def upstream_request_path(base_url: str, incoming_path: str) -> str:
    """Keep provider prefixes, without doubling a shared /v1 suffix/prefix."""
    base = urlsplit(base_url)
    incoming = urlsplit(incoming_path)
    prefix = [part for part in base.path.split("/") if part]
    suffix = [part for part in incoming.path.split("/") if part]
    overlap = next((size for size in range(min(len(prefix), len(suffix)), 0, -1)
                    if prefix[-size:] == suffix[:size]), 0)
    path = "/" + "/".join(prefix + suffix[overlap:])
    if incoming.path.endswith("/") and not path.endswith("/"):
        path += "/"
    query = "&".join(item for item in (base.query, incoming.query) if item)
    return urlunsplit(("", "", path, query, ""))


class AnthropicEventStream:
    """Incrementally parse SSE, retaining raw events and assembling one message."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.message: dict[str, Any] = {}
        self.errors: list[str] = []
        self.stopped = False
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._pending = ""
        self._fields: list[tuple[str, str]] = []
        self._blocks: dict[int, dict[str, Any]] = {}
        self._tool_json: dict[int, str] = {}

    def feed(self, data: bytes) -> None:
        self._consume(self._decoder.decode(data))

    def _consume(self, text: str) -> None:
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._line(line.removesuffix("\r"))

    def _line(self, line: str) -> None:
        if not line:
            self._emit()
        elif not line.startswith(":"):
            key, separator, value = line.partition(":")
            self._fields.append((key, value.removeprefix(" ") if separator else ""))

    def _emit(self) -> None:
        if not self._fields:
            return
        fields, self._fields = self._fields, []
        text = "\n".join(value for key, value in fields if key == "data")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = text
        event = {"event": next((value for key, value in fields if key == "event"), "message"),
                 "data": data, "rawData": text}
        for key, value in fields:
            if key not in {"event", "data"}:
                event[key] = value
        self.events.append(event)
        if isinstance(data, dict):
            try:
                self._apply(data)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                self.errors.append(f"Cannot aggregate captured SSE event: {type(exc).__name__}: {exc}")

    def _apply(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "message_start":
            self.message = copy.deepcopy(event.get("message") or {})
            self._blocks = {index: copy.deepcopy(block) for index, block in enumerate(self.message.get("content") or [])}
        elif kind == "content_block_start":
            self._blocks[int(event["index"])] = copy.deepcopy(event.get("content_block") or {})
        elif kind == "content_block_delta":
            index = int(event["index"])
            block = self._blocks.setdefault(index, {})
            delta = event.get("delta") or {}
            field = {"text_delta": "text", "thinking_delta": "thinking", "signature_delta": "signature"}.get(delta.get("type"))
            if field:
                block[field] = str(block.get(field) or "") + str(delta.get(field) or "")
            elif delta.get("type") == "input_json_delta":
                self._tool_json[index] = self._tool_json.get(index, "") + str(delta.get("partial_json") or "")
            elif delta.get("type") == "citations_delta":
                block.setdefault("citations", []).append(copy.deepcopy(delta.get("citation")))
        elif kind == "message_delta":
            self.message.update(copy.deepcopy(event.get("delta") or {}))
            if isinstance(event.get("usage"), dict):
                self.message.setdefault("usage", {}).update(event["usage"])
        elif kind == "message_stop":
            self.stopped = True
        elif kind == "error":
            error = event.get("error")
            self.errors.append(str(error.get("message") or error) if isinstance(error, dict) else str(error))

    def finish(self) -> dict[str, Any]:
        self._consume(self._decoder.decode(b"", final=True))
        if self._pending:
            self._line(self._pending.removesuffix("\r"))
            self._pending = ""
        self._emit()
        for index, raw in self._tool_json.items():
            block = self._blocks.setdefault(index, {})
            try:
                block["input"] = json.loads(raw)
            except json.JSONDecodeError:
                block["input_json_partial"] = raw
        if self._blocks:
            self.message["content"] = [self._blocks[index] for index in sorted(self._blocks)]
        return copy.deepcopy(self.message)


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    blocks = message.get("content")
    if not isinstance(blocks, list):
        return ""
    return "".join(block.get("text", "") for block in blocks
                   if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str))


def _redact(value: Any, secrets: set[str]) -> Any:
    if isinstance(value, str):
        variants = {variant for secret in secrets for variant in (secret, quote(secret, safe=""), quote_plus(secret, safe="")) if variant}
        for secret in sorted(variants, key=len, reverse=True):
            if secret:
                value = value.replace(secret, "<redacted>")
        return value
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    return value


class SdkHttpCapture:
    """Forward to one configured upstream and archive all attempts in isolation.

    ``base_url`` is used as the SDK's temporary API base. ``records`` is ordered
    by arrival, including failed/auxiliary requests. Authentication is forwarded
    in memory and excluded from artifacts. No provider configuration is changed.
    """

    def __init__(self, upstream_base_url: str, *,
                 on_exchange: Callable[[dict[str, Any]], Any] | None = None,
                 request_purpose: str = "sdk_generation", parent_request_id: str = "",
                 timeout: float = 300, upstream_environment: dict[str, str] | None = None) -> None:
        upstream = urlsplit(upstream_base_url)
        if upstream.scheme not in {"http", "https"} or not upstream.hostname:
            raise ValueError("upstream_base_url must be an HTTP(S) base URL")
        if upstream.username or upstream.password:
            raise ValueError("Use forwarded authentication headers, not URL credentials")
        self.upstream_base_url = upstream_base_url
        self.on_exchange = on_exchange
        self.request_purpose = request_purpose
        self.parent_request_id = parent_request_id
        self.upstream_environment = {**os.environ, **(upstream_environment or {})}
        self._forward_tasks: dict[asyncio.Task, asyncio.AbstractEventLoop] = {}
        self._downstream_connections: set[socket.socket] = set()
        self._closing = False
        self.timeout = timeout
        self.base_url = ""
        self._lock = threading.Lock()
        self._next_number = 0
        self._active = 0
        self._idle = threading.Condition(self._lock)
        self._records: list[dict[str, Any]] = []
        self._redirects: dict[str, tuple[str, bool]] = {}
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(sorted(self._records, key=lambda item: item["requestNumber"]))

    def __enter__(self) -> "SdkHttpCapture":
        if self._server is not None or self._closing:
            raise RuntimeError("Capture is already running or closed")
        capture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                capture._forward(self)

            do_GET = do_POST
            do_PUT = do_POST
            do_PATCH = do_POST
            do_DELETE = do_POST
            do_OPTIONS = do_POST
            do_HEAD = do_POST

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._server.block_on_close = False
        self.base_url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        with self._lock:
            self._closing = True
            tasks = list(self._forward_tasks.items())
            downstream = list(self._downstream_connections)
        # Closing a synchronous HTTP client cannot interrupt pending DNS/TCP/TLS
        # setup. Cancel the owning coroutine so it cannot later send a request.
        for task, loop in tasks:
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(self._cancel_forward, task)
        for connection in downstream:
            with suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
            with suppress(OSError):
                connection.close()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        with self._idle:
            # Each cancelled request closes its transport and archives its final
            # state before leaving. Do not return a partial diagnostics snapshot.
            self._idle.wait_for(lambda: self._active == 0)
        self._server = None

    def _cancel_forward(self, task: asyncio.Task) -> None:
        # This callback runs on the request's loop. A request already finalizing
        # must finish cleanup/archiving without a second cancellation.
        with self._lock:
            if task in self._forward_tasks:
                task.cancel()

    def _request_bytes(self, handler: BaseHTTPRequestHandler) -> bytes:
        if "chunked" not in handler.headers.get("Transfer-Encoding", "").casefold():
            return handler.rfile.read(int(handler.headers.get("Content-Length", "0")))
        parts = []
        while True:
            size = int(handler.rfile.readline().split(b";", 1)[0], 16)
            if not size:
                while handler.rfile.readline() not in {b"\r\n", b"\n", b""}:
                    pass
                return b"".join(parts)
            parts.append(handler.rfile.read(size))
            handler.rfile.read(2)

    def _redirect_location(self, source: str, location: str, drop_auth: bool) -> str:
        destination = urljoin(source, location)
        parsed = urlsplit(destination)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return location
        if parsed.username or parsed.password:
            raise ValueError("Redirect URL must not contain credentials")
        path = "/_sdk_capture_redirect/" + uuid.uuid4().hex
        with self._lock:
            self._redirects[path] = (destination, drop_auth or _origin(source) != _origin(destination))
        return self.base_url + path

    def _forward(self, handler: BaseHTTPRequestHandler) -> None:
        asyncio.run(self._forward_async(handler))

    async def _forward_async(self, handler: BaseHTTPRequestHandler) -> None:
        task = asyncio.current_task()
        with self._lock:
            if self._closing:
                handler.close_connection = True
                return
            self._next_number += 1
            self._active += 1
            self._forward_tasks[task] = asyncio.get_running_loop()
            self._downstream_connections.add(handler.connection)
            number = self._next_number
        try:
            await self._forward_exchange(handler, number)
        finally:
            with self._lock:
                self._forward_tasks.pop(task, None)
                self._downstream_connections.discard(handler.connection)
                self._active -= 1
                self._idle.notify_all()

    async def _forward_exchange(self, handler: BaseHTTPRequestHandler, number: int) -> None:
        request_id = uuid.uuid4().hex
        incoming_path = urlsplit(handler.path).path
        upstream = urlsplit(self.upstream_base_url)
        target = upstream_request_path(self.upstream_base_url, handler.path)
        with self._lock:
            redirected = self._redirects.get(incoming_path)
        url, drop_auth = redirected or (urlunsplit((upstream.scheme, upstream.netloc, target.partition("?")[0], target.partition("?")[2], "")), False)
        auxiliary = handler.command != "POST" or not urlsplit(url).path.rstrip("/").endswith("/messages")
        secrets = _url_secrets(url)
        for key, value in handler.headers.items():
            if key.casefold() in _AUTH_HEADERS:
                secrets.add(value)
                if key.casefold() == "authorization" and " " in value:
                    secrets.add(value.split(" ", 1)[1])
        request_body: Any = None
        raw_response = bytearray()
        stream: AnthropicEventStream | None = None
        status: int | None = None
        error = ""
        response_started = False
        connection: Any = None
        response: Any = None
        network_streams: dict[int, Any] = {}

        async def track_connection(event: str, info: dict[str, Any]) -> None:
            # A TCP stream awaiting TLS does not yet belong to httpcore's HTTP
            # connection. Retain it through the public trace hook for cleanup.
            if event.endswith((".connect_tcp.complete", ".connect_unix_socket.complete", ".start_tls.complete")):
                network_stream = info.get("return_value")
                if network_stream is not None:
                    network_streams[id(network_stream)] = network_stream

        try:
            raw_request = self._request_bytes(handler)
            if raw_request:
                try:
                    request_body = json.loads(raw_request.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    request_body = {"rawBody": raw_request.decode("utf-8", errors="replace")}
            else:
                request_body = {}
            hop = _HOP_HEADERS | {item.strip().casefold() for item in handler.headers.get("Connection", "").split(",")}
            headers = {key: value for key, value in handler.headers.items()
                       if key.casefold() not in hop | {"host", "content-length", "accept-encoding"}}
            if drop_auth:
                headers = {key: value for key, value in headers.items()
                           if key.casefold() not in _AUTH_HEADERS | {"cookie", "cookie2"}}
            headers["Accept-Encoding"] = "identity"
            if raw_request or handler.command in {"POST", "PUT", "PATCH"}:
                headers["Content-Length"] = str(len(raw_request))
            # Explicit proxy selection uses the original SDK environment, before
            # loopback bypasses are added. No process-global environment mutation.
            import httpx
            proxy = _upstream_proxy(url, self.upstream_environment)
            if proxy:
                credentials = urlsplit(proxy)
                if credentials.password:
                    secrets.update({credentials.password, unquote(credentials.password)})
            tls_context = await asyncio.to_thread(_upstream_tls_context, self.upstream_environment)
            if proxy and urlsplit(proxy).scheme == "https":
                proxy = httpx.Proxy(proxy, ssl_context=tls_context)
            connection = httpx.AsyncClient(proxy=proxy, trust_env=False,
                                           verify=tls_context,
                                           timeout=self.timeout, follow_redirects=False)
            with self._lock:
                if self._closing:
                    raise InterruptedError("SDK request capture has closed")
            request = connection.build_request(handler.command, url, content=raw_request or b"", headers=headers,
                                               extensions={"trace": track_connection})
            response = await connection.send(request, stream=True)
            status = response.status_code
            stream = AnthropicEventStream() if "text/event-stream" in response.headers.get("Content-Type", "").casefold() else None
            response_hop = _HOP_HEADERS | {item.strip().casefold() for item in response.headers.get("Connection", "").split(",")}
            outgoing_headers = []
            for key, value in response.headers.multi_items():
                if key.casefold() not in response_hop:
                    if key.casefold() == "location" and status in {301, 302, 303, 307, 308}:
                        value = self._redirect_location(url, value, drop_auth)
                    outgoing_headers.append((key, value))
            handler.send_response(status, response.reason_phrase)
            for key, value in outgoing_headers:
                handler.send_header(key, value)
            # Dechunked bytes are flushed immediately and terminated by EOF.
            handler.send_header("Connection", "close")
            handler.end_headers()
            response_started = True
            handler.close_connection = True
            async for chunk in response.aiter_raw():
                raw_response.extend(chunk)
                if stream is not None:
                    try:
                        stream.feed(chunk)
                    except (UnicodeError, ValueError, TypeError) as exc:
                        # Inspection must never interrupt otherwise valid transport.
                        error = error or f"Cannot parse captured SSE: {type(exc).__name__}: {exc}"
                        stream = None
                handler.wfile.write(chunk)
                handler.wfile.flush()
        except asyncio.CancelledError:
            error = "SDK request capture has closed"
            handler.close_connection = True
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if not response_started:
                try:
                    payload = json.dumps({"error": {"type": "capture_proxy_error", "message": _redact(error, secrets)}}).encode("utf-8")
                    handler.send_response(502)
                    handler.send_header("Content-Type", "application/json")
                    handler.send_header("Content-Length", str(len(payload)))
                    handler.send_header("Connection", "close")
                    handler.end_headers()
                    handler.wfile.write(payload)
                    handler.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            handler.close_connection = True
        finally:
            with self._lock:
                self._forward_tasks.pop(asyncio.current_task(), None)
            if response is not None:
                with suppress(Exception):
                    await response.aclose()
            if connection is not None:
                with suppress(Exception):
                    await connection.aclose()
            for network_stream in reversed(list(network_streams.values())):
                with suppress(Exception):
                    await network_stream.aclose()
            if stream is not None:
                try:
                    data = stream.finish()
                except UnicodeDecodeError as exc:
                    data = copy.deepcopy(stream.message)
                    error = error or f"Invalid UTF-8 in upstream stream: {exc}"
                http_response: Any = {"events": stream.events,
                                      "rawText": bytes(raw_response).decode("utf-8", errors="replace")}
                if stream.errors:
                    error = error or "; ".join(stream.errors)
                if not auxiliary and not stream.stopped:
                    error = error or "Upstream SSE ended without message_stop"
            else:
                response_text = bytes(raw_response).decode("utf-8", errors="replace")
                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError:
                    data = None
                http_response = data if data is not None else {"rawText": response_text}
            if status is not None and status >= 400 and not error:
                detail = data.get("error") if isinstance(data, dict) else None
                error = str(detail.get("message") or detail) if isinstance(detail, dict) else str(detail or f"HTTP {status}")
            result = _redact({
                "executed": True, "success": status is not None and 200 <= status < 300 and not error,
                "httpStatus": status, "error": error,
                "requestInfo": {"transport": "http", "method": handler.command,
                    "provider": "sdk_upstream_capture", "url": url, "requestBody": request_body,
                    "captureLevel": "api_outbound", "captureSource": "claude_agent_sdk",
                    "requestPurpose": "sdk_auxiliary" if auxiliary else self.request_purpose,
                    "requestId": request_id, "parentRequestId": self.parent_request_id},
                "text": _message_text(data), "rawData": data, "data": data,
                "httpResponse": http_response,
            }, secrets)
            record = {"requestNumber": number, "auxiliary": auxiliary, "method": handler.command,
                      "path": incoming_path, "status": status, "success": result["success"],
                      "error": result["error"], "requestId": request_id}
            try:
                record = self._archive_exchange(result, record)
            except Exception as exc:
                record["artifactError"] = _redact(f"{type(exc).__name__}: {exc}", secrets)
                # Logging failure must not change the bytes or status returned to the SDK.
                print(_redact(traceback.format_exc(), secrets), file=sys.stderr, flush=True)
            with self._lock:
                self._records.append(record)

    def _archive_exchange(self, result: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        if self.on_exchange:
            references = self.on_exchange(result)
            if isinstance(references, dict):
                record["logs"] = references
        return record
