"""Forensic instrumentation must be bounded, privacy-safe and truthful."""

import json
import os
import sqlite3

import pytest

from ghostframe.benchmark import failure_category
from ghostframe.forensics import Diagnostic, sanitize_stack, supervise
from ghostframe.models import GFError


def test_progress_can_append_while_windows_reader_is_open(tmp_path):
    diag = Diagnostic(tmp_path, True)
    diag.progress("source_recording", "started")
    with (tmp_path / "progress.jsonl").open("r") as reader:
        diag.progress("db_commit", "started")
        assert len(reader.readlines()) == 2


def test_diagnostic_markers_reject_private_labels_and_stacks(tmp_path):
    diag = Diagnostic(tmp_path, True)
    secret = "SYNTHETIC_PRIVATE_LABEL_CANARY_333"
    diag.scope.set(secret)
    with diag.span(secret):
        pass
    artifact = (tmp_path / "progress.jsonl").read_text() + json.dumps(diag.stats)
    assert secret not in artifact
    frames = sanitize_stack(
        "Process: secret-token\nThread: private-name\n    execute (C:\\private-secret\\store.py:99)\n    user_function (C:\\private-secret\\user_document.py:12)"
    )
    assert frames == [{"module": "store.py", "function": "execute", "line": 99}]
    assert "private" not in json.dumps(frames)


def test_diagnostic_cap_does_not_change_caller_outcome(tmp_path):
    diag = Diagnostic(tmp_path, True)
    diag.markers = 20000
    with diag.span("db_commit"):
        value = 42
    assert value == 42 and diag.truncated
    assert not (tmp_path / "progress.jsonl").exists()


@pytest.mark.parametrize(
    "stage,code,expected",
    [
        ("source_recording", "EXECUTION_TIMEOUT", "RECORDING_TIMEOUT"),
        ("deterministic_replay", "EXECUTION_TIMEOUT", "REPLAY_TIMEOUT"),
        ("source_recording", "EXECUTION_CANCELLED", "CANCELLED"),
        ("deterministic_replay", "EVENT_MISMATCH", "REPLAY_DIVERGED"),
        ("deterministic_replay", "CHECKPOINT_CORRUPT", "INTEGRITY_FAILURE"),
    ],
)
def test_failure_taxonomy_keeps_recording_and_replay_distinct(stage, code, expected):
    assert failure_category(stage, GFError(code, "synthetic")) == expected


def test_storage_busy_requires_actual_sqlite_evidence(tmp_path):
    path = tmp_path / "locked.db"
    with sqlite3.connect(path) as a, sqlite3.connect(path, timeout=0.01) as b:
        a.execute("create table x(n)")
        a.commit()
        a.execute("begin immediate")
        with pytest.raises(sqlite3.OperationalError) as caught:
            b.execute("begin immediate")
        assert failure_category("source_recording", caught.value) == "RECORDING_STORAGE_BLOCKED"
        a.rollback()
    assert (
        failure_category("source_recording", sqlite3.OperationalError("synthetic syntax failure"))
        == "RECORDING_FAILED"
    )


def test_supervisor_normal_and_detailed_preserve_semantics(tmp_path):
    for mode in [False, True]:
        result = supervise(tmp_path / str(mode), "F2", 1, mode)
        row = result["rows"][0]
        assert row["record_success"] and row["replay_entered"] and row["replay_success"]
        assert row["attempt_success"] and row["parent_preserved"] and row["integrity_valid"]
        assert row["process_cleanup_success"]
        assert not result["harness_terminated"]
        if os.name == "nt":
            assert result["diagnostic_completeness"]["cpu_available"]
            assert result["diagnostic_completeness"]["memory_available"]


def test_supervisor_termination_is_never_success(tmp_path):
    result = supervise(tmp_path / "terminated", "E2", 2, True, control="terminate", deadline=3)
    assert result["harness_terminated"] and len(result["rows"]) == 2
    assert all(not r["attempt_success"] for r in result["rows"])
    assert all(r["category"] == "BENCHMARK_HARNESS_TIMEOUT" for r in result["rows"])
    assert result["rows"][0]["started"] and not result["rows"][1]["started"]


def test_heartbeat_ring_remains_bounded_and_responsive(tmp_path):
    diag = Diagnostic(tmp_path, True)
    for _ in range(1500):
        diag.progress("db_commit", "started")
    path = tmp_path / "progress.jsonl"
    assert path.stat().st_size < 128 * 1024
    assert diag.rotations > 0 and not diag.truncated
    last = json.loads(path.read_text().splitlines()[-1])
    assert last["sequence"] == diag.markers == 1500
