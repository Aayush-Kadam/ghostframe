"""Independent adverse cases for M8-R, separate from fixture outcome generation."""

import asyncio
import json
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from ghostframe import CapturePolicy, GFError, Limits, Recorder, RetentionPolicy, trace_tool
from ghostframe.api import create_app
from ghostframe.boundary import BudgetBoundary
from ghostframe.fixtures import flagship
from ghostframe.models import canonical
from ghostframe.runtime import Engine, initial_state
from ghostframe.sandbox import Sandbox
from ghostframe.store import Store

CANARIES = [
    "SYNTHETIC_API_CANARY_917",
    "SYNTHETIC_COOKIE_CANARY_918",
    "SYNTHETIC_PASSWORD_CANARY_919",
    "SYNTHETIC_NESTED_CANARY_920",
    "SYNTHETIC_DB_CANARY_921",
    "SYNTHETIC_EXCEPTION_CANARY_922",
]


def target(store, rid):
    return next(
        e for e in store.events(rid) if e["kind"] == "TOOL_CALL_COMPLETED" and e["tool"] == "read_ticket"
    )


def test_metadata_default_all_supported_artifacts(tmp_path):
    db = tmp_path / "private.db"
    r = Recorder(str(db), project=CANARIES[0])
    payload = {
        "api_key": CANARIES[0],
        "cookie": CANARIES[1],
        "password": CANARIES[2],
        "nested": {"value": CANARIES[3]},
        "url": "postgres://user:" + CANARIES[4] + "@localhost/db",
    }

    @trace_tool(recorder=r, name="private_tool")
    def tool(value):
        return value

    with r.run(CANARIES[0], payload) as rid:
        tool(payload)
        r.store.checkpoint(rid, payload)
    bundle = canonical(r.store.export(rid))
    assert not r.store.summary(rid)["replay_eligible"]
    assert all(not e["capture_complete"] for e in r.store.events(rid))
    with pytest.raises(ValueError), r.run("exception"):
        raise ValueError(CANARIES[5])
    app = TestClient(create_app(str(db)))
    api = app.get(f"/api/runs/{rid}/export").text + app.get("/api/runs").text
    raw = b"".join(p.read_bytes() for p in tmp_path.glob("private.db*"))
    for secret in CANARIES:
        assert secret not in bundle + api
        assert secret.encode() not in raw


def test_allowlists_exclude_siblings_nested_lists_and_other_tools(tmp_path):
    policy = CapturePolicy(
        mode="allowlist", allowed_tools=("approved",), allowed_fields=("safe", "nested.value")
    )
    s = Store(tmp_path / "allow.db", policy=policy)
    rid = s.create({"name": CANARIES[0]})
    s.append(rid, "RUN_STARTED")
    ev = s.append(
        rid,
        "AGENT_STEP_COMPLETED",
        {
            "safe": 7,
            "nested": {"value": 8, "extra": CANARIES[1]},
            "list": [CANARIES[2]],
            "other": CANARIES[3],
        },
        tool="approved",
    )
    assert ev["payload"] == {"safe": 7, "nested": {"value": 8}}
    assert not ev["capture_complete"]
    denied = s.append(rid, "AGENT_STEP_COMPLETED", {"safe": CANARIES[4]}, tool="unapproved")
    assert denied["payload"] == {"capture": "EXCLUDED"}
    assert not any(secret in canonical(s.export(rid)) for secret in CANARIES)


def test_pattern_redaction_and_replay_eligibility():
    p = CapturePolicy(mode="synthetic_fixture", redact_values=(CANARIES[3],))
    data, complete = p.capture(
        {
            "message": "Bearer " + CANARIES[0],
            "url": "https://host/?token=" + CANARIES[1],
            "password": CANARIES[2],
            "nested": [CANARIES[3]],
        }
    )
    assert not complete
    assert all(secret not in canonical(data) for secret in CANARIES)


def test_missing_capture_cannot_replay_and_fixture_opt_in(tmp_path):
    s = Store(tmp_path / "r.db")
    e = Engine(s)
    rid = s.create({"driver_version": "document-agent.v1"})
    s.append(rid, "RUN_STARTED", {"secret": CANARIES[0]})
    s.append(rid, "RUN_COMPLETED", {})
    with pytest.raises(GFError, match="incomplete"):
        e.replay(rid)
    f = flagship()
    f.pop("synthetic")
    with pytest.raises(GFError) as exc:
        e.run(f)
    assert exc.value.code == "SYNTHETIC_OPT_IN_REQUIRED"


@pytest.mark.parametrize("phase", ["triggers", "deleted", "logged"])
def test_expiry_dependency_rollback_retry_and_sentinel(tmp_path, phase):
    now = [1000.0]
    s = Store(
        tmp_path / "retention.db",
        clock=lambda: now[0],
        retention=RetentionPolicy(retention_days=1, cleanup_on_startup=False),
    )
    e = Engine(s)
    parent = e.run(flagship())
    now[0] += 80000
    branch = e.fork(
        parent, target(s, parent)["event_id"], {"action": "delete", "target": "/documents/draft_report.txt"}
    )["branch_id"]
    active = s.create({})
    s.append(active, "RUN_STARTED")
    pinned = e.run(flagship())
    s.pin(pinned)
    sentinel = tmp_path / "unrelated.txt"
    sentinel.write_text("must survive")
    now[0] += 10000
    assert parent not in s.cleanup()["expired_runs"]
    now[0] += 90000
    ids = s.cleanup()["expired_runs"]
    assert parent in ids and branch in ids and pinned not in ids and active not in ids

    def interrupt(at):
        if at == phase:
            raise RuntimeError("controlled interruption")

    with pytest.raises(RuntimeError):
        s.cleanup(apply=True, interrupt=interrupt)
    assert s.verify(parent)["complete"] and s.verify(branch)["complete"]
    with s.connect() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM events")
    assert set(s.cleanup(apply=True)["expired_runs"]) == set(ids)
    assert s.verify(pinned)["complete"]
    assert s.metadata(active)
    assert sentinel.read_text() == "must survive"
    assert s.cleanup(apply=True)["expired_runs"] == []


def test_legacy_and_active_operation_protected(tmp_path):
    now = [1.0]
    s = Store(tmp_path / "legacy.db", clock=lambda: now[0], retention=RetentionPolicy(retention_days=1))
    rid = Engine(s).run(flagship())
    with s.connect() as db:
        db.execute("DELETE FROM lifecycle WHERE run_id=?", (rid,))
    now[0] += 200000
    assert rid not in s.cleanup()["expired_runs"]
    protected = Engine(s).run(flagship())
    now[0] += 200000
    with s.operation(protected):
        assert protected not in s.cleanup(apply=True)["expired_runs"]
    assert protected in s.cleanup(apply=True)["expired_runs"]


@pytest.mark.parametrize(
    "payload", [{"x": "x" * 100}, [[[[[[[1]]]]]]], {"x": float("nan")}, {"x": b"binary"}]
)
def test_low_payload_quotas_reject_before_persistence(tmp_path, payload):
    s = Store(tmp_path / "q.db", limits=replace(Limits(), payload_bytes=80, string_bytes=80, depth=5))
    rid = s.create({})
    s.append(rid, "RUN_STARTED")
    with pytest.raises(GFError):
        s.append(rid, "AGENT_STEP_COMPLETED", payload)
    assert len(s.events(rid)) == 1


def test_cyclic_and_exponential_shared_values_bounded():
    cycle = []
    cycle.append(cycle)
    with pytest.raises(GFError):
        Limits().check(cycle)
    tree = []
    for _ in range(22):
        tree = [tree, tree]
    with pytest.raises(GFError):
        Limits(nodes=100).check(tree)


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"events": 2}, "RUN_EVENT_LIMIT_EXCEEDED"),
        ({"checkpoints": 1}, "CHECKPOINT_LIMIT_EXCEEDED"),
        ({"run_bytes": 900}, "STORAGE_QUOTA_EXCEEDED"),
    ],
)
def test_execution_quota_failure_is_terminal(tmp_path, changes, code):
    s = Store(tmp_path / "limits.db", limits=replace(Limits(), **changes))
    with pytest.raises(GFError) as exc:
        Engine(s).run(flagship())
    assert exc.value.code == code
    rows = s.runs()
    if rows:
        assert all(r["status"] != "RUN_COMPLETED" for r in rows)
        assert not any(r["replay_eligible"] for r in rows)


def test_checkpoint_export_run_and_store_quotas(tmp_path):
    s = Store(tmp_path / "cp.db", limits=replace(Limits(), checkpoint_bytes=100))
    rid = s.create({})
    with pytest.raises(GFError):
        s.checkpoint(rid, {"x": "x" * 200})
    s = Store(tmp_path / "exp.db")
    rid = Engine(s).run(flagship())
    s.limits = replace(s.limits, export_bytes=100)
    with pytest.raises(GFError):
        s.export(rid)
    s = Store(tmp_path / "count.db", limits=replace(Limits(), runs=1))
    s.create({})
    with pytest.raises(GFError):
        s.create({})
    s = Store(tmp_path / "bytes.db", limits=replace(Limits(), store_bytes=350))
    s.create({})
    with pytest.raises(GFError):
        s.create({})


def test_step_timeout_cancel_and_original_preservation(tmp_path):
    s = Store(tmp_path / "time.db")
    e = Engine(s)
    rid = e.run(flagship())
    before = s.export(rid)
    s.limits = replace(s.limits, steps=1)
    with pytest.raises(GFError) as exc:
        e.replay(rid)
    assert exc.value.code == "REPLAY_STEP_LIMIT_EXCEEDED"
    assert s.export(rid) == before
    s.limits = replace(s.limits, steps=64, seconds=0.001)
    real = e.driver.action

    def slow(state):
        time.sleep(0.005)
        return real(state)

    e.driver.action = slow
    with pytest.raises(GFError) as exc:
        e.fork(rid, target(s, rid)["event_id"], {"action": "delete", "target": "/documents/draft_report.txt"})
    assert exc.value.code == "BRANCH_TIMEOUT"
    e.cancelled.set()
    with pytest.raises(GFError) as exc:
        e.run(flagship())
    assert exc.value.code == "EXECUTION_CANCELLED"
    assert s.export(rid) == before


def test_virtual_filesystem_quotas_transactional():
    box = Sandbox(initial_state(flagship()), limits=replace(Limits(), file_bytes=100, files=3))
    before = json.loads(canonical(box.state))
    with pytest.raises(GFError):
        box.call("write_file", {"path": "/documents/new.txt", "content": "x" * 101})
    assert box.state == before and box.journal == []


def test_concurrent_branches_count_enforced_and_slots_released(tmp_path):
    s = Store(tmp_path / "concurrent.db", limits=replace(Limits(), branches=2))
    e = Engine(s)
    rid = e.run(flagship())
    event = target(s, rid)["event_id"]
    before = s.export(rid)

    def branch(_):
        try:
            return e.fork(rid, event, {"action": "delete", "target": "/documents/draft_report.txt"})["status"]
        except GFError as exc:
            return exc.code

    with ThreadPoolExecutor(4) as pool:
        statuses = list(pool.map(branch, range(4)))
    assert statuses.count("BRANCH_SUCCESS") == 2
    assert statuses.count("BRANCH_LIMIT_EXCEEDED") == 2
    assert not s._active
    assert s.export(rid) == before
    s.limits = replace(s.limits, active_operations=1)
    with s.operation(rid), pytest.raises(GFError):
        e.replay(rid)
    with s.operation(rid):
        pass


def test_api_limits_validation_and_no_echo(tmp_path):
    c = TestClient(create_app(str(tmp_path / "api.db")))
    rid = c.post("/api/demo/run").json()["id"]
    assert c.get(f"/api/runs/{rid}/events?limit=501").status_code == 422
    assert c.post(f"/api/runs/{rid}/fork", json={CANARIES[0]: CANARIES[1]}).status_code == 422
    assert CANARIES[0] not in c.post(f"/api/runs/{rid}/fork", json={CANARIES[0]: CANARIES[1]}).text
    assert c.post("/api/demo/run", content="x" * 40000).status_code == 413
    assert c.post("/api/demo/run", content="gzip", headers={"content-encoding": "gzip"}).status_code == 415
    assert (
        c.post(
            "/api/demo/run", content="[" * 40 + "0" + "]" * 40, headers={"content-type": "application/json"}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("disconnect", [False, True])
def test_chunked_ingress_and_disconnect_bounded(disconnect):
    called = []
    sent = []

    async def app(scope, receive, send):
        called.append(True)

    boundary = BudgetBoundary(app, replace(Limits(), request_bytes=10))
    chunks = [
        {"type": "http.request", "body": b"123456", "more_body": True},
        {"type": "http.disconnect"}
        if disconnect
        else {"type": "http.request", "body": b"789012", "more_body": False},
    ]

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    asyncio.run(boundary({"type": "http", "method": "POST", "headers": []}, receive, send))
    assert not called
    assert not sent if disconnect else sent[0]["status"] == 413


def test_connections_close_on_rollback_and_windows_unlink(tmp_path):
    path = tmp_path / "sqlite locking ü with spaces.db"
    s = Store(path)
    with pytest.raises(RuntimeError), s.connect() as db:
        db.execute("INSERT INTO cleanup_log VALUES ('test',0,'[]')")
        raise RuntimeError("rollback")
    with s.connect() as db:
        assert not db.execute("SELECT * FROM cleanup_log").fetchall()
    path.unlink()
    assert not path.exists()


def test_cross_process_leases_crash_recovery_and_cleanup(tmp_path):
    now = [1.0]
    s = Store(
        tmp_path / "leases.db",
        clock=lambda: now[0],
        retention=RetentionPolicy(retention_days=1, cleanup_on_startup=False),
        limits=replace(Limits(), active_operations=1),
    )
    rid = Engine(s).run(flagship())
    now[0] += 200000
    script = (
        "import sys,os; from ghostframe.store import Store; "
        "s=Store(sys.argv[1], retention=__import__('ghostframe').RetentionPolicy(cleanup_on_startup=False)); c=s.operation(sys.argv[2]); c.__enter__(); "
        "print('LEASED',flush=True); sys.stdin.readline(); os._exit(17)"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(s.path), rid],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "LEASED"
        assert rid not in s.cleanup(apply=True)["expired_runs"]
        with pytest.raises(GFError), s.operation(rid):
            pass
        child.communicate("exit\n", timeout=20)
        assert child.returncode == 17
        assert rid in s.cleanup(apply=True)["expired_runs"]
        with s.operation():
            pass
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=20)


def test_ancestry_response_depth_and_disk_failure(tmp_path, monkeypatch):
    s = Store(tmp_path / "ancestry.db")
    e = Engine(s)
    rid = e.run(flagship())
    replay = e.replay(rid)["run_id"]
    with pytest.raises(GFError) as exc:
        e.replay(replay)
    assert exc.value.code == "BRANCH_DEPTH_LIMIT_EXCEEDED"
    s.limits = replace(s.limits, response_bytes=10)
    with pytest.raises(GFError):
        s.event_page(rid, 1, 0)
    with pytest.raises(GFError):
        s.runs()
    s.limits = Limits()
    before = s.export(rid)
    real = s._charge

    def full(db, run, size):
        raise sqlite3.OperationalError("controlled disk capacity failure")

    monkeypatch.setattr(s, "_charge", full)
    with pytest.raises(sqlite3.OperationalError):
        e.run(flagship())
    monkeypatch.setattr(s, "_charge", real)
    assert s.export(rid) == before
    assert not s._active
    assert s.runs()[0]["status"] != "RUN_COMPLETED"


def test_sdk_terminal_event_quota_and_sensitive_tool_label(tmp_path):
    r = Recorder(str(tmp_path / "sdk.db"), limits=replace(Limits(), events=1))
    with pytest.raises(GFError), r.run(CANARIES[0]) as rid:
        pass
    assert r.store.events(rid)[-1]["kind"] == "RUN_FAILED"
    assert not r.store.summary(rid)["replay_eligible"]
    r = Recorder(str(tmp_path / "labels.db"))
    with r.run("safe") as rid:
        r.emit("AGENT_STEP_COMPLETED", {}, tool=CANARIES[1])
    assert CANARIES[1] not in canonical(r.store.export(rid))


def test_bounded_response_sends_no_partial_success():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"x" * 20})

    sent = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    asyncio.run(
        BudgetBoundary(app, replace(Limits(), response_bytes=10))(
            {"type": "http", "method": "GET", "headers": []}, receive, send
        )
    )
    assert sent[0]["status"] == 413


def test_disconnect_during_controlled_execution_is_not_success(tmp_path):
    import anyio

    s = Store(tmp_path / "disconnect.db")
    e = Engine(s)
    real = e.driver.action

    def slow(state):
        time.sleep(0.05)
        return real(state)

    e.driver.action = slow
    outcomes = []

    async def app(scope, receive, send):
        try:
            await anyio.to_thread.run_sync(lambda: e.run(flagship()))
            outcomes.append("SUCCESS")
        except GFError as exc:
            outcomes.append(exc.code)
        await send({"type": "http.response.start", "status": 409, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    calls = 0

    async def receive():
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"type": "http.request", "body": b""}
        await anyio.sleep(0.02)
        return {"type": "http.disconnect"}

    async def send(message):
        pass

    asyncio.run(
        BudgetBoundary(app, Limits())({"type": "http", "method": "POST", "headers": []}, receive, send)
    )
    assert outcomes == ["EXECUTION_CANCELLED"]
    assert s.runs()[0]["status"] == "RUN_FAILED"
    assert not s._active


@pytest.mark.parametrize("phase", ["triggers", "deleted", "logged"])
def test_cleanup_abrupt_process_death_rolls_back(tmp_path, phase):
    s = Store(
        tmp_path / "crash-cleanup.db",
        clock=lambda: 1.0,
        retention=RetentionPolicy(retention_days=1, cleanup_on_startup=False),
    )
    rid = Engine(s).run(flagship())
    script = (
        "import sys,os; from ghostframe import RetentionPolicy; from ghostframe.store import Store; "
        "s=Store(sys.argv[1],clock=lambda:200000,retention=RetentionPolicy(cleanup_on_startup=False)); "
        "s.cleanup(apply=True,interrupt=lambda phase: os._exit(17) if phase==sys.argv[2] else None)"
    )
    child = subprocess.run([sys.executable, "-c", script, str(s.path), phase], timeout=20, check=False)
    assert child.returncode == 17
    assert s.verify(rid)["complete"]
    with s.connect() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM runs")
    s.clock = lambda: 200000
    assert s.cleanup(apply=True)["expired_runs"] == [rid]


@pytest.mark.parametrize(
    "limits",
    [replace(Limits(), files=3), replace(Limits(), file_bytes=10), replace(Limits(), filesystem_bytes=1)],
)
def test_each_virtual_filesystem_quota(limits):
    if limits.file_bytes == 10 or limits.filesystem_bytes == 1:
        with pytest.raises(GFError):
            Sandbox(initial_state(flagship()), limits=limits)
    else:
        box = Sandbox(initial_state(flagship()), limits=limits)
        with pytest.raises(GFError):
            box.call("write_file", {"path": "/documents/fourth.txt", "content": "safe"})


def test_request_timeout_releases_slot():
    import anyio

    sent = []

    async def app(scope, receive, send):
        raise AssertionError("Timed-out request must not execute")

    async def receive():
        await anyio.sleep(0.03)
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    b = BudgetBoundary(app, replace(Limits(), seconds=0.01))
    asyncio.run(b({"type": "http", "method": "POST", "headers": []}, receive, send))
    assert sent[0]["status"] == 408


@pytest.mark.parametrize("kwargs", [{"steps": 0.5}, {"seconds": float("inf")}, {"events": -1}])
def test_invalid_quota_configuration_rejected(kwargs):
    with pytest.raises(ValueError):
        replace(Limits(), **kwargs)


def test_invalid_event_errors_do_not_echo_and_closed_checkpoint_denied(tmp_path):
    s = Store(tmp_path / "errors.db")
    rid = s.create({})
    s.append(rid, "RUN_STARTED")
    for fields in ({"unexpected": CANARIES[0]}, {"step": CANARIES[1]}):
        with pytest.raises(GFError) as exc:
            s.append(rid, "AGENT_STEP_COMPLETED", {}, **fields)
        assert not any(c in str(exc.value) for c in CANARIES)
    s.append(rid, "RUN_COMPLETED")
    with pytest.raises(GFError) as exc:
        s.checkpoint(rid, {})
    assert exc.value.code == "RUN_FINALIZED"


def test_missing_fixture_has_typed_replay_error_and_ineligible_summary(tmp_path):
    s = Store(tmp_path / "missing-fixture.db", policy=CapturePolicy(enabled=True))
    rid = s.create({"name": "synthetic", "driver_version": "document-agent.v1"})
    s.append(rid, "RUN_STARTED", {})
    s.append(rid, "RUN_COMPLETED", {})
    assert not s.summary(rid)["replay_eligible"]
    with pytest.raises(GFError) as exc:
        Engine(s).replay(rid)
    assert exc.value.code == "MISSING_CAPTURE"


def test_byte_counter_matches_independent_sql_and_rollback(tmp_path):
    s = Store(
        tmp_path / "counter.db",
        clock=lambda: 1.0,
        retention=RetentionPolicy(retention_days=1, cleanup_on_startup=False),
    )
    Engine(s).run(flagship())

    def assert_accounting():
        with s.connect() as db:
            actual = sum(
                db.execute(f"SELECT COALESCE(SUM(length(CAST({column} AS BLOB))),0) FROM {table}").fetchone()[
                    0
                ]
                for table, column in (
                    ("runs", "metadata"),
                    ("events", "body"),
                    ("checkpoints", "body"),
                    ("cleanup_log", "removed"),
                )
            )
            assert db.execute("SELECT bytes FROM storage_usage WHERE id=1").fetchone()[0] == actual

    assert_accounting()

    s.clock = lambda: 200000

    def interrupt(phase):
        if phase == "deleted":
            raise RuntimeError("rollback")

    with pytest.raises(RuntimeError):
        s.cleanup(apply=True, interrupt=interrupt)
    assert_accounting()
    s.cleanup(apply=True)
    assert_accounting()


def test_reopening_cannot_escalate_existing_capture_policy(tmp_path):
    path = tmp_path / "resume.db"
    original = Store(path)
    rid = original.create({})
    original.append(rid, "RUN_STARTED")
    reopened = Store(path, policy=CapturePolicy(enabled=True))
    event = reopened.append(rid, "AGENT_STEP_COMPLETED", {"plain": CANARIES[0]})
    assert not event["capture_complete"]
    assert CANARIES[0] not in canonical(reopened.export(rid))


def test_run_retention_opt_out_survives_reopening(tmp_path):
    path = tmp_path / "retention-opt-out.db"
    original = Store(path, retention=RetentionPolicy(enabled=False), clock=lambda: 1.0)
    rid = original.create({})
    original.append(rid, "RUN_STARTED")
    reopened = Store(path, clock=lambda: 1.0)
    reopened.append(rid, "RUN_COMPLETED")
    reopened.clock = lambda: 10000000
    assert rid not in reopened.cleanup(apply=True)["expired_runs"]


@pytest.mark.parametrize(
    "path,allowed",
    [
        ("/documents/CON", True),
        ("/documents/NUL", True),
        ("/documents/报告 ü.txt", True),
        ("/documents/Report With Spaces.txt", True),
        ("C:/documents/file.txt", False),
        ("/documents\\file.txt", False),
        ("/documents/../file.txt", False),
    ],
)
def test_windows_virtual_paths_do_not_resolve_to_host(tmp_path, path, allowed):
    from ghostframe.sandbox import normalize

    sentinel = tmp_path / "host-sentinel.txt"
    sentinel.write_text("untouched")
    if allowed:
        assert normalize(path) == path
        box = Sandbox(initial_state(flagship()))
        assert box.call("write_file", {"path": path, "content": "synthetic ü"})["ok"]
        assert box.state["files"][path] == "synthetic ü"
    else:
        with pytest.raises(GFError):
            normalize(path)
    assert sentinel.read_text() == "untouched"


def test_cli_utf8_intervention_file(tmp_path, monkeypatch, capsys):
    from ghostframe.cli import main

    s = Store(tmp_path / "unicode-cli.db")
    rid = Engine(s).run(flagship())
    replacement = tmp_path / "replacement ü.json"
    replacement.write_text(
        json.dumps(
            {"action": "write", "target": "/documents/报告.txt", "content": "synthetic ü"}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ghostframe",
            "--db",
            str(s.path),
            "fork",
            rid,
            "--event",
            target(s, rid)["event_id"],
            "--replacement",
            str(replacement),
        ],
    )
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["comparison"]["branch_outcome"]["final_files"]["/documents/报告.txt"] == "synthetic ü"


def test_duplicate_headers_do_not_bypass_metadata_budget():
    sent = []

    async def app(scope, receive, send):
        raise AssertionError("Oversized header count must not execute")

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    asyncio.run(
        BudgetBoundary(app, Limits())(
            {"type": "http", "method": "GET", "headers": [(b"x-test", b"a")] * 101}, receive, send
        )
    )
    assert sent[0]["status"] == 413


def test_default_cli_server_does_not_enable_raw_access_logging(tmp_path, monkeypatch):
    from ghostframe.cli import main

    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, **options: calls.append(options))
    monkeypatch.setattr(sys, "argv", ["ghostframe", "--db", str(tmp_path / "serve.db"), "serve"])
    main()
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["access_log"] is False


def test_checkpoint_identifier_cannot_be_a_capture_bypass(tmp_path):
    s = Store(tmp_path / "id-capture.db")
    rid = s.create({})
    s.append(rid, "RUN_STARTED")
    with pytest.raises(GFError):
        s.append(rid, "AGENT_STEP_COMPLETED", {}, checkpoint=CANARIES[0])
    assert CANARIES[0] not in canonical(s.export(rid))


def test_ancestry_identifiers_must_be_owned_evidence(tmp_path):
    s = Store(tmp_path / "ancestry-ids.db")
    parent = s.create({})
    for key in ("source_event", "source_checkpoint"):
        with pytest.raises(GFError):
            s.create({"parent_id": parent, key: "deadbeef" * 4})
    assert len(s.runs()) == 1


@pytest.mark.parametrize(
    "factory",
    [
        lambda: CapturePolicy(enabled="false"),
        lambda: CapturePolicy(enabled=None),
        lambda: RetentionPolicy(enabled="false"),
        lambda: RetentionPolicy(cleanup_on_startup="false"),
        lambda: RetentionPolicy(retention_days=True),
        lambda: Limits(seconds=True),
    ],
)
def test_configuration_strings_cannot_silently_enable_capture_or_expiry(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_branch_virtual_quota_cannot_report_success(tmp_path):
    s = Store(tmp_path / "branch-file-quota.db", limits=replace(Limits(), files=3))
    e = Engine(s)
    rid = e.run(flagship())
    before = s.export(rid)
    with pytest.raises(GFError) as exc:
        e.fork(
            rid,
            target(s, rid)["event_id"],
            {"action": "write", "target": "/documents/fourth.txt", "content": "safe"},
        )
    assert exc.value.code == "FILESYSTEM_QUOTA_EXCEEDED"
    failed = exc.value.details["failed_run_id"]
    assert s.events(failed)[-1]["payload"]["code"] == "FILESYSTEM_QUOTA_EXCEEDED"
    assert s.summary(failed)["status"] == "RUN_FAILED"
    assert s.summary(failed)["outcome"] is None
    with pytest.raises(GFError) as comparison:
        e.compare(rid, failed)
    assert comparison.value.code == "INCOMPLETE_CAPTURE"
    assert s.export(rid) == before


def test_replay_virtual_quota_cannot_report_success(tmp_path):
    s = Store(tmp_path / "replay-file-quota.db")
    e = Engine(s)
    f = flagship()
    f["ticket"] = {"action": "write", "target": "/documents/fourth.txt", "content": "safe"}
    rid = e.run(f)
    before = s.export(rid)
    s.limits = replace(s.limits, files=3)
    with pytest.raises(GFError) as exc:
        e.replay(rid)
    assert exc.value.code == "FILESYSTEM_QUOTA_EXCEEDED"
    assert s.summary(exc.value.details["failed_run_id"])["status"] == "RUN_FAILED"
    assert s.export(rid) == before


@pytest.mark.parametrize("key", ["policy", "limits", "retention"])
def test_false_policy_objects_do_not_fall_back_to_permissive_defaults(tmp_path, key):
    path = tmp_path / "invalid-config.db"
    with pytest.raises(TypeError):
        Store(path, **{key: False})
    assert not path.exists()
