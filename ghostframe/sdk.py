"""Opt-in payload capture; context propagation for synchronous and asynchronous tools."""

from __future__ import annotations

import contextvars
import functools
import inspect
from contextlib import contextmanager
from typing import Any

from .models import GFError
from .policies import CapturePolicy, Limits, RetentionPolicy
from .store import Store

_context: contextvars.ContextVar[tuple[str, str | None] | None] = contextvars.ContextVar(
    "ghostframe_context", default=None
)


class Recorder:
    def __init__(
        self,
        storage: str = ".ghostframe/ghostframe.db",
        project: str = "agent",
        policy: CapturePolicy | None = None,
        limits: Limits | None = None,
        retention: RetentionPolicy | None = None,
    ):
        self.store = Store(
            storage.removeprefix("sqlite:///"), policy=policy, limits=limits, retention=retention
        )
        self.project = project
        self.policy = policy or CapturePolicy()

    def emit(self, kind: str, payload: Any = None, **fields):
        ctx = _context.get()
        if not ctx:
            raise GFError("MISSING_RUN_CONTEXT", "Use 'with recorder.run(...)' first")
        return self.store.append(
            ctx[0],
            kind,
            payload,
            parent=fields.pop("parent", ctx[1]),
            actor=self.project,
            **fields,
        )

    @contextmanager
    def run(self, name: str, metadata: dict | None = None):
        rid = self.store.create(
            {
                "name": name,
                "project": self.project,
                "driver_version": None,
                "provenance": "RECORDED",
                "custom_metadata": metadata,
            }
        )
        token = _context.set((rid, None))
        try:
            self.emit("RUN_STARTED", {"name": name})
            yield rid
        except BaseException as exc:
            self.store.fail(rid, exc.code if isinstance(exc, GFError) else "EXECUTION_FAILED")
            raise
        else:
            try:
                self.emit("RUN_COMPLETED", {"status": "completed"})
            except GFError as exc:
                self.store.fail(rid, exc.code)
                raise
        finally:
            _context.reset(token)


def trace_tool(*, recorder: Recorder, name: str | None = None):
    def decorate(fn):
        tool = name or fn.__name__

        def start(args, kwargs):
            ctx = _context.get()
            event = recorder.emit("TOOL_CALL_REQUESTED", {"args": args, "kwargs": kwargs}, tool=tool)
            assert ctx is not None
            token = _context.set((ctx[0], event["event_id"]))
            return event, token

        def finish(event, result):
            recorder.emit("TOOL_CALL_COMPLETED", result, parent=event["event_id"], tool=tool)

        def failed(event, exc):
            try:
                recorder.emit(
                    "TOOL_CALL_FAILED",
                    {"exception": type(exc).__name__, "message": str(exc)},
                    parent=event["event_id"],
                    tool=tool,
                    status="ERROR",
                )
            except GFError:
                recorder.store.fail(
                    event["run_id"], exc.code if isinstance(exc, GFError) else "EXECUTION_FAILED"
                )

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapped(*args, **kwargs):
                event, token = start(args, kwargs)
                try:
                    result = await fn(*args, **kwargs)
                    finish(event, result)
                    return result
                except BaseException as exc:
                    failed(event, exc)
                    raise
                finally:
                    _context.reset(token)

            return async_wrapped

        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            event, token = start(args, kwargs)
            try:
                result = fn(*args, **kwargs)
                finish(event, result)
                return result
            except BaseException as exc:
                failed(event, exc)
                raise
            finally:
                _context.reset(token)

        return wrapped

    return decorate
