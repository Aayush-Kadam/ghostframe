import asyncio
import json
import sqlite3
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from ghostframe import CapturePolicy, GFError, Recorder, trace_tool
from ghostframe.api import create_app


def test_sdk_sync_nested_exception(tmp_path):
    r = Recorder(str(tmp_path / "sdk.db"), policy=CapturePolicy(enabled=True))

    @trace_tool(recorder=r)
    def inner(value):
        if value == 0:
            raise ValueError("failure")
        return value + 1

    @trace_tool(recorder=r)
    def outer(value):
        return inner(value)

    with r.run("success") as rid:
        assert outer(1) == 2
    assert r.store.verify(rid)["complete"]
    events = r.store.events(rid)
    requests = [e for e in events if e["kind"] == "TOOL_CALL_REQUESTED"]
    assert requests[1]["parent"] == requests[0]["event_id"]
    with pytest.raises(ValueError), r.run("failure") as bad:
        inner(0)
    assert r.store.events(bad)[-1]["kind"] == "RUN_FAILED"
    assert any(e["kind"] == "TOOL_CALL_FAILED" for e in r.store.events(bad))
    with pytest.raises(GFError):
        inner(1)


def test_sdk_concurrent_contexts(tmp_path):
    r = Recorder(str(tmp_path / "async.db"), policy=CapturePolicy(enabled=True))

    @trace_tool(recorder=r)
    async def work(value):
        await asyncio.sleep(0)
        return value

    async def run(name):
        with r.run(name) as rid:
            assert await asyncio.gather(work(1), work(2)) == [1, 2]
        return rid

    async def both():
        return await asyncio.gather(run("one"), run("two"))

    ids = asyncio.run(both())
    assert len(set(ids)) == 2
    for rid in ids:
        assert r.store.verify(rid)["complete"]
        assert len(r.store.events(rid)) == 6


@pytest.mark.parametrize(
    "policy,payload,expected",
    [
        (CapturePolicy(), {"secret": "NEVER_SAVE"}, "DISABLED"),
        (CapturePolicy(enabled=True), {"password": "NEVER_SAVE"}, "REDACTED"),
        (CapturePolicy(enabled=True, redact_values=("NEVER_SAVE",)), {"message": "NEVER_SAVE"}, "REDACTED"),
        (CapturePolicy(enabled=True, max_bytes=10), {"message": "x" * 100}, "OVERSIZED"),
    ],
)
def test_capture_before_persistence(tmp_path, policy, payload, expected):
    r = Recorder(str(tmp_path / "capture.db"), policy=policy)

    @trace_tool(recorder=r)
    def tool():
        return payload

    with r.run("test") as rid:
        tool()
    bundle = json.dumps(r.store.export(rid))
    assert "NEVER_SAVE" not in bundle
    assert expected in bundle
    assert not all(e["capture_complete"] for e in r.store.events(rid))


def test_unsupported_serialization(tmp_path):
    r = Recorder(str(tmp_path / "serialize.db"), policy=CapturePolicy(enabled=True))

    @trace_tool(recorder=r)
    def tool():
        return object()

    with pytest.raises(GFError), r.run("test") as rid:
        tool()
    assert r.store.events(rid)[-1]["kind"] == "RUN_FAILED"


def test_sdk_process_death(tmp_path):
    path = tmp_path / "crash.db"
    script = f"from ghostframe import Recorder; import os; r=Recorder({str(path)!r}); c=r.run('crash'); c.__enter__(); os._exit(17)"
    result = subprocess.run([sys.executable, "-c", script], check=False)
    assert result.returncode == 17
    from ghostframe.store import Store

    s = Store(path)
    assert s.runs()[0]["integrity"]["status"] == "INCOMPLETE_CAPTURE"


def test_storage_failure(tmp_path):
    r = Recorder(str(tmp_path / "fail.db"), policy=CapturePolicy(enabled=True))

    def broken(*args, **kw):
        raise sqlite3.OperationalError("disk full")

    r.store.append = broken
    with pytest.raises(sqlite3.OperationalError), r.run("test"):
        pass


def test_api_end_to_end(tmp_path):
    c = TestClient(create_app(str(tmp_path / "api.db")))
    assert c.get("/api/health").json()["status"] == "ok"
    rid = c.post("/api/demo/run").json()["id"]
    events = c.get(f"/api/runs/{rid}/events").json()["events"]
    target = next(e for e in events if e["kind"] == "TOOL_CALL_COMPLETED" and e["tool"] == "read_ticket")
    assert c.post(f"/api/runs/{rid}/replay").json()["status"] == "REPLAY_SUCCESS"
    body = {
        "event_id": target["event_id"],
        "replacement": {"action": "delete", "target": "/documents/draft_report.txt"},
    }
    b = c.post(f"/api/runs/{rid}/fork", json=body)
    assert b.status_code == 200
    bid = b.json()["branch_id"]
    assert c.get(f"/api/branches/{bid}/comparison").json()["branch_outcome"]["task_correct"]
    assert c.get(f"/api/runs/{rid}/integrity").json()["valid"]
    assert c.get(f"/api/runs/{rid}/events?limit=2&offset=1").json()["events"] == events[1:3]
    assert c.get(f"/api/runs/{rid}/checkpoints").json()
    assert c.get(f"/api/runs/{rid}/export").json()["bundle"]["events"] == events
    assert c.get("/api/runs/missing").status_code == 404
    assert c.get("/api/runs?limit=1000").status_code == 422
    assert c.post(f"/api/runs/{rid}/fork", json={}).status_code == 422
    body["replacement"]["target"] = "/etc/passwd"
    assert c.post(f"/api/runs/{rid}/fork", json=body).status_code == 409
    assert c.post("/api/demo/run", headers={"origin": "https://evil.example"}).status_code == 403
    assert c.get("/api/health", headers={"host": "evil.example"}).status_code == 400
    assert c.post("/api/demo/run", content="x" * 40000).status_code == 413
    assert c.get("/api/schema/ticket").json()["additionalProperties"] is False
