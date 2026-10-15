"""Bounded ASGI ingress and egress; no unbounded request.body() allocation."""

from __future__ import annotations

import contextvars
import json
import threading
import time

import anyio
from starlette.responses import JSONResponse

from .models import GFError

request_cancelled: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "request_cancelled", default=None
)


class BudgetBoundary:
    def __init__(self, app, limits):
        self.app, self.limits = app, limits
        self.slots = threading.BoundedSemaphore(limits.active_operations * 2)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def reject(code, status=413):
            await JSONResponse(
                {"error": {"code": code, "message": "Configured request or response budget exceeded"}},
                status_code=status,
            )(scope, receive, send)

        if not self.slots.acquire(blocking=False):
            return await reject("CONCURRENCY_LIMIT_EXCEEDED", 429)
        try:
            raw_headers = scope.get("headers", [])
            headers = dict(raw_headers)
            if (
                len(scope.get("path", "")) > 4096
                or len(scope.get("query_string", b"")) > 4096
                or len(raw_headers) > 100
                or sum(len(k) + len(v) for k, v in raw_headers) > 16384
            ):
                return await reject("REQUEST_METADATA_TOO_LARGE")
            if headers.get(b"content-encoding", b"identity") != b"identity":
                return await reject("UNSUPPORTED_CONTENT_ENCODING", 415)
            try:
                declared = int(headers.get(b"content-length", b"0"))
            except ValueError:
                return await reject("INVALID_CONTENT_LENGTH", 400)
            if declared < 0 or declared > self.limits.request_bytes:
                return await reject("PAYLOAD_TOO_LARGE")
            body = bytearray()
            started = time.monotonic()
            while True:
                remaining = self.limits.seconds - (time.monotonic() - started)
                if remaining <= 0:
                    return await reject("REQUEST_TIMEOUT", 408)
                try:
                    with anyio.fail_after(remaining):
                        message = await receive()
                except TimeoutError:
                    return await reject("REQUEST_TIMEOUT", 408)
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > self.limits.request_bytes:
                    return await reject("PAYLOAD_TOO_LARGE")
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            if body and (
                b"json" in headers.get(b"content-type", b"") or scope["method"] in {"POST", "PUT", "PATCH"}
            ):
                try:
                    value = json.loads(body)
                    self.limits.check(value, self.limits.request_bytes)
                except (ValueError, RecursionError, UnicodeError, GFError):
                    return await reject("INVALID_OR_OVERSIZED_JSON", 422)
            delivered = False
            cancelled = threading.Event()
            disconnected = anyio.Event()

            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                await disconnected.wait()
                return {"type": "http.disconnect"}

            async def watch_disconnect():
                message = await receive()
                if message["type"] == "http.disconnect":
                    cancelled.set()
                    disconnected.set()
                else:
                    await anyio.sleep_forever()

            messages = []
            size = 0

            async def bounded_send(message):
                nonlocal size
                size += len(message.get("body", b""))
                if size > self.limits.response_bytes:
                    raise GFError("RESPONSE_LIMIT_EXCEEDED", "Response byte budget exceeded")
                messages.append(message)

            token = request_cancelled.set(cancelled)
            try:
                async with anyio.create_task_group() as group:
                    group.start_soon(watch_disconnect)
                    try:
                        await self.app(scope, bounded_receive, bounded_send)
                    except GFError:
                        messages = []
                    finally:
                        group.cancel_scope.cancel()
            finally:
                request_cancelled.reset(token)
            if not messages:
                return await reject("RESPONSE_LIMIT_EXCEEDED")
            for message in messages:
                await send(message)
        finally:
            self.slots.release()
