from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .boundary import BudgetBoundary
from .fixtures import flagship
from .models import (
    BranchResult,
    ComparisonResult,
    EventPage,
    EvidenceBundle,
    ForkRequest,
    GFError,
    IntegrityResult,
    ReplayResult,
    RunSummary,
    Ticket,
)
from .policies import Limits
from .runtime import Engine
from .store import Store


def _loopback_authority(value: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"(localhost|127\.0\.0\.1|\[::1\])(?::([0-9]{1,5}))?", value, re.IGNORECASE)
    if not match:
        return None
    port = int(match[2]) if match[2] else 80
    return (match[1].lower(), port) if 1 <= port <= 65535 else None


def create_app(
    storage: str | None = None, *, limits: Limits | None = None, allow_dev_origin: bool = False
) -> FastAPI:
    if type(allow_dev_origin) is not bool:
        raise ValueError("Development origin opt-in must be boolean")
    store = Store(storage or os.environ.get("GHOSTFRAME_DB", ".ghostframe/ghostframe.db"), limits=limits)
    engine = Engine(store)
    app = FastAPI(title="GhostFrame", version="0.1.0rc1")
    app.state.store, app.state.engine = store, engine
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        authority = _loopback_authority(request.headers.get("host", ""))
        server = request.scope.get("server")
        # testserver is an in-process ASGI test address, never a network Host exception.
        test_server = request.headers.get("host") == "testserver" and server and server[0] == "testserver"
        if not test_server and (not authority or not server or authority[1] != server[1]):
            return JSONResponse(
                {"error": {"code": "HOST_DENIED", "message": "Expected bound loopback host and port"}},
                status_code=400,
            )
        origin = request.headers.get("origin")
        origin_authority = (
            _loopback_authority(origin[7:]) if origin and origin.startswith("http://") else None
        )
        same_origin = authority is not None and origin_authority == authority
        development = allow_dev_origin and origin in {"http://127.0.0.1:5173", "http://localhost:5173"}
        if origin is not None and not (same_origin or development):
            return JSONResponse(
                {"error": {"code": "ORIGIN_DENIED", "message": "Expected the bound local debugger origin"}},
                status_code=403,
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "VALIDATION_FAILED",
                    "message": "Request does not match the schema",
                    "details": [{"type": e["type"]} for e in exc.errors()],
                }
            },
            status_code=422,
        )

    @app.exception_handler(GFError)
    async def domain_error(request, exc: GFError):
        return JSONResponse(
            {
                "error": {
                    "code": exc.code,
                    "message": "Operation rejected; inspect local policy and capture eligibility",
                }
            },
            status_code=404 if exc.code == "RUN_NOT_FOUND" else 409,
        )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "boundary": "trusted-local", "version": "0.1.0rc1"}

    @app.get("/api/health/dependencies")
    def dependencies():
        from .cli import doctor

        return doctor(store)

    @app.get("/api/schema/ticket")
    def schema():
        return Ticket.model_json_schema()

    @app.get("/api/runs", response_model=list[RunSummary])
    def runs(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        return store.runs(limit, offset)

    @app.get("/api/runs/{rid}", response_model=RunSummary)
    def run(rid: str):
        return store.summary(rid)

    @app.get("/api/runs/{rid}/events", response_model=EventPage)
    def events(rid: str, limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0)):
        return store.event_page(rid, limit, offset)

    @app.get("/api/runs/{rid}/checkpoints")
    def checkpoints(rid: str):
        return store.checkpoints(rid)

    @app.get("/api/runs/{rid}/integrity", response_model=IntegrityResult)
    def integrity(rid: str):
        return store.verify(rid)

    @app.get("/api/runs/{rid}/export", response_model=EvidenceBundle)
    def export(rid: str):
        return store.export(rid)

    @app.post("/api/runs/{rid}/replay", response_model=ReplayResult)
    def replay(rid: str):
        return engine.replay(rid)

    @app.post("/api/runs/{rid}/fork", response_model=BranchResult)
    def fork(rid: str, request: ForkRequest):
        return engine.fork(
            rid, request.event_id, request.replacement.model_dump(), request.label, request.note
        )

    @app.get("/api/branches/{bid}", response_model=RunSummary)
    def branch(bid: str):
        return store.summary(bid)

    @app.get("/api/branches/{bid}/events", response_model=EventPage)
    def branch_events(bid: str, limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0)):
        return events(bid, limit, offset)

    @app.get("/api/branches/{bid}/comparison", response_model=ComparisonResult)
    def comparison(bid: str):
        meta = store.metadata(bid)
        if not meta.get("source_event"):
            raise GFError("NOT_A_BRANCH", "Run is not an intervention branch")
        return engine.compare(meta["parent_id"], bid)

    @app.post("/api/demo/run", response_model=RunSummary)
    def demo():
        return store.summary(engine.run(flagship()))

    @app.post("/api/demo/seed", response_model=RunSummary)
    def seed():
        return demo()

    @app.get("/api/benchmarks/latest")
    def benchmark():
        path = Path("benchmarks/reports/latest.json")
        return (
            json.loads(path.read_text())
            if path.exists()
            else {"status": "NOT_RUN", "message": "Run ghostframe benchmark"}
        )

    static = Path(__file__).parent / "static"
    if static.exists():
        app.mount("/", StaticFiles(directory=static, html=True), name="debugger")
    app.add_middleware(BudgetBoundary, limits=store.limits)
    return app
