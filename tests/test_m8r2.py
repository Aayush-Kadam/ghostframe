"""M8-R2: adversarial redaction complexity and replay lifecycle regression checks."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from ghostframe import CapturePolicy, GFError, RetentionPolicy
from ghostframe.fixtures import flagship, load
from ghostframe.runtime import Engine
from ghostframe.store import Store


def test_maximum_plain_text_redaction_has_bounded_work():
    # A process watchdog isolates a potentially non-cooperative regex; it is not
    # the product's 60-second execution deadline. Three legal 32KiB strings used
    # to exceed this 5-second guard through repeated unsuccessful scheme scans.
    code = """
from ghostframe import CapturePolicy
p=CapturePolicy(mode='synthetic_fixture')
s='x'*32768
for _ in range(3):
    result,complete=p.capture({'text':s})
    assert result['text']==s and complete
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=5)


@pytest.mark.parametrize("prefix", ["https", "postgresql+tcp", "X.Y-1", "123", ""])
def test_credentials_after_long_prefix_never_reach_storage(tmp_path, prefix):
    secret = "SYNTHETIC_R2_CREDENTIAL_CANARY"
    value = "x" * 16000 + " " + prefix + "://user:" + secret + "@host/db token=" + secret
    s = Store(tmp_path / "credentials.db", policy=CapturePolicy(enabled=True))
    rid = s.create({"name": "redaction"})
    event = s.append(rid, "AGENT_STEP_COMPLETED", {"text": value})
    assert secret not in json.dumps(event)
    assert not event["capture_complete"]
    assert secret.encode() not in b"".join(p.read_bytes() for p in tmp_path.glob("credentials.db*"))


@pytest.mark.parametrize("fid", ["E2", "F1", "F2"])
def test_affected_cases_reexecute_and_preserve_parent(tmp_path, fid):
    fixture = next(f for f in load()["development"] if f["id"] == fid)
    s = Store(tmp_path / "replay.db")
    e = Engine(s)
    parent = e.run(fixture)
    before = s.export(parent)["digest"]
    result = e.replay(parent)
    assert result["status"] == "REPLAY_SUCCESS"
    assert s.export(parent)["digest"] == before
    assert s.verify(result["run_id"])["valid"]
    assert s.summary(result["run_id"])["outcome"] == s.summary(parent)["outcome"]


def test_deadline_and_cancel_release_leases_without_success(tmp_path, monkeypatch):
    s = Store(tmp_path / "deadline.db")
    e = Engine(s)
    parent = e.run(flagship())
    before = s.export(parent)["digest"]
    real_clock = __import__("time").monotonic
    ticks = iter([0, 61])
    monkeypatch.setattr("ghostframe.runtime.time.monotonic", lambda: next(ticks, 61))
    with pytest.raises(GFError) as caught:
        e.replay(parent)
    assert caught.value.code == "EXECUTION_TIMEOUT"
    failed = caught.value.details["failed_run_id"]
    assert s.events(failed)[-1]["kind"] == "RUN_FAILED"
    assert not any(v["kind"] == "RUN_COMPLETED" for v in s.events(failed))
    monkeypatch.setattr("ghostframe.runtime.time.monotonic", real_clock)
    e.cancelled.set()
    with pytest.raises(GFError) as cancelled:
        e.replay(parent)
    assert cancelled.value.code == "EXECUTION_CANCELLED"
    assert s.export(parent)["digest"] == before
    with s.connect() as db:
        assert db.execute("select count(*) from operations").fetchone()[0] == 0
        assert db.execute("pragma integrity_check").fetchone()[0] == "ok"
    e.cancelled.clear()
    assert e.replay(parent)["status"] == "REPLAY_SUCCESS"


def test_replay_with_overlapping_retention_preserves_dependencies(tmp_path):
    now = [1.0]
    s = Store(
        tmp_path / "lifecycle.db",
        clock=lambda: now[0],
        retention=RetentionPolicy(retention_days=1, cleanup_on_startup=False),
    )
    parent = Engine(s).run(flagship())
    before = s.export(parent)["digest"]
    now[0] = 90000
    # Hold a real operation lease across concurrent cleanup/replay. No security
    # policy is disabled; expired ancestry must stay protected while active.
    with s.operation(parent):
        with ThreadPoolExecutor(max_workers=2) as pool:
            replay = pool.submit(Engine(s).replay, parent)
            cleanup = pool.submit(s.cleanup, apply=True)
            assert replay.result(timeout=20)["status"] == "REPLAY_SUCCESS"
            assert parent not in cleanup.result(timeout=20)["expired_runs"]
        assert s.export(parent)["digest"] == before
    with s.connect() as db:
        assert db.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert db.execute("select count(*) from operations").fetchone()[0] == 0


def test_benchmark_reports_recording_failure_without_losing_denominator(tmp_path, monkeypatch):
    import ghostframe.benchmark as module

    suite = load()
    cases = [next(f for f in suite["development"] if f["id"] == fid) for fid in ["E2", "F1"]]
    # A controlled reporting test, separate from the sealed 40-fixture protocol.
    monkeypatch.setattr(module, "load", lambda: {"version": 1, "development": cases, "regression": []})
    original = Engine.run
    calls = [0]

    def injected(self, fixture):
        calls[0] += 1
        if fixture["id"] == "E2" and calls[0] > 1:  # retain the ordinary warm-up
            raise GFError("EXECUTION_TIMEOUT", "Synthetic reporting fault")
        return original(self, fixture)

    monkeypatch.setattr(Engine, "run", injected)
    result = module.benchmark(str(tmp_path / "reports"), repetitions=2)
    assert result["sets"]["development"]["attempts"] == 4
    assert result["sets"]["development"]["eligible"] == 4
    assert len(result["failures"]) == 2
    for row in result["failures"]:
        assert row["failure_stage"] == "source_recording"
        assert row["error_code"] == "EXECUTION_TIMEOUT"
        assert row["failed_stage_ms"] >= 0
        assert not row["replay_success"]
        assert "replay_ms" not in row
