"""Measured trials with authored oracles and no success exclusions."""

from __future__ import annotations

import copy
import csv
import json
import platform
import sqlite3
import statistics
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from .fixtures import load
from .models import GFError
from .runtime import DocumentDriver, Engine, initial_state
from .sandbox import Sandbox
from .store import Store


def baseline(fixture):
    box = Sandbox(initial_state(fixture))
    driver = DocumentDriver()
    for _ in range(64):
        action = driver.action(box.state)
        if action is None:
            return box.state
        tool, args = action
        try:
            result = box.call(tool, args)
        except GFError as exc:
            result = {"error": exc.code}
        driver.observe(box.state, tool, result)
    raise GFError("EXECUTION_TIMEOUT", "Baseline exceeded logical step budget")


def journal_check(store, rid):
    meta = store.metadata(rid)
    events = store.events(rid)
    if meta.get("source_checkpoint"):
        files = copy.deepcopy(store.restore(meta["source_checkpoint"], meta["parent_id"])["files"])
    else:
        files = copy.deepcopy(meta["fixture"]["files"])
    mutations = [e for e in events if e["kind"] == "SIDE_EFFECT_RECORDED"]
    for event in mutations:
        change = event["payload"]
        if files.get(change["path"]) != change["before"]:
            return False, len(mutations)
        if change["operation"] == "delete":
            files.pop(change["path"], None)
        else:
            files[change["path"]] = change["after"]
    return files == store.summary(rid)["outcome"]["final_files"], len(mutations)


def failure_category(stage, exc):
    """Phase-aware report taxonomy; underlying engine error contracts unchanged."""
    code = exc.code if isinstance(exc, GFError) else type(exc).__name__
    if code == "EXECUTION_CANCELLED":
        return "CANCELLED"
    if code == "EXECUTION_TIMEOUT":
        return "REPLAY_TIMEOUT" if stage == "deterministic_replay" else "RECORDING_TIMEOUT"
    if isinstance(exc, sqlite3.OperationalError) and getattr(exc, "sqlite_errorcode", None) in {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
    }:
        return "RECORDING_STORAGE_BLOCKED" if stage == "source_recording" else "STORAGE_WAIT"
    if code in {"INTEGRITY_VIOLATION", "CHECKPOINT_CORRUPT"}:
        return "INTEGRITY_FAILURE"
    return (
        "REPLAY_DIVERGED"
        if stage == "deterministic_replay"
        else "RECORDING_FAILED"
        if stage == "source_recording"
        else "UNKNOWN"
    )


def benchmark(output="benchmarks/reports", repetitions=3):
    fixture_started = time.perf_counter()
    suite = load()
    fixture_loading_ms = (time.perf_counter() - fixture_started) * 1000
    rows = []
    environment_started = time.perf_counter()
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "bench.db")
        engine = Engine(store)
        environment_ms = (time.perf_counter() - environment_started) * 1000
        engine.run(suite["development"][0])  # one warm-up, excluded by declared protocol
        for group in ["development", "regression"]:
            for fixture in suite[group]:
                for trial in range(repetitions):
                    row = {
                        "set": group,
                        "fixture": fixture["id"],
                        "trial": trial,
                        "record_entered": False,
                        "record_success": False,
                        "replay_entered": False,
                        "attempt_success": False,
                        "category": "UNKNOWN",
                        "replay_success": False,
                        "oracle_match": False,
                        "branch_attempted": False,
                        "branch_valid": False,
                        "error": "",
                        "attempt_id": f"{group}/{fixture['id']}/{trial}",
                        "expected_outcome": "successful_deterministic_replay",
                        "deadline_seconds": store.limits.seconds,
                    }
                    attempt_started = time.perf_counter()
                    stage = "unrecorded_baseline"
                    start = time.perf_counter()
                    try:
                        start = time.perf_counter()
                        base = baseline(fixture)
                        row["unrecorded_ms"] = (time.perf_counter() - start) * 1000
                        stage = "source_recording"
                        start = time.perf_counter()
                        row["record_entered"] = True
                        rid = engine.run(fixture)
                        row["record_success"] = True
                        row["source_run_id"] = rid
                        row["record_ms"] = (time.perf_counter() - start) * 1000
                        outcome = store.summary(rid)["outcome"]
                        row["oracle_match"] = (
                            outcome["final_files"] == fixture["expected_files"]
                            and outcome["task_correct"] == fixture["expected_correct"]
                            and outcome["result"].get("error") == fixture["expected_error"]
                            and base["files"] == outcome["final_files"]
                        )
                        stage = "playback"
                        start = time.perf_counter()
                        playback = store.events(rid)
                        row["playback_ms"] = (time.perf_counter() - start) * 1000
                        row["event_count"] = len(playback)
                        row["event_bytes"] = len(json.dumps(playback).encode())
                        row["checkpoint_bytes"] = len(json.dumps(store.checkpoints(rid)).encode())
                        stage = "deterministic_replay"
                        start = time.perf_counter()
                        row["replay_entered"] = True
                        replay = engine.replay(rid)
                        row["replay_run_id"] = replay["run_id"]
                        row["replay_ms"] = (time.perf_counter() - start) * 1000
                        row["replay_success"] = replay["status"] == "REPLAY_SUCCESS"
                        stage = "checkpoint_and_journal_validation"
                        checkpoints = store.checkpoints(rid)
                        row["checkpoint_count"] = len(checkpoints)
                        row["restored_count"] = 0
                        row["checkpoint_restore_samples_ms"] = []
                        for cp in checkpoints:
                            restore_started = time.perf_counter()
                            restored = store.restore(cp["id"], rid)
                            row["checkpoint_restore_samples_ms"].append(
                                (time.perf_counter() - restore_started) * 1000
                            )
                            row["restored_count"] += restored == cp["body"]["state"]
                        row["checkpoint_restore_ms"] = sum(row["checkpoint_restore_samples_ms"])
                        accounted, mutations = journal_check(store, rid)
                        row["mutations"] = mutations
                        row["accounted_mutations"] = mutations if accounted else 0
                        if fixture.get("intervention"):
                            stage = "branch_continuation"
                            row["branch_attempted"] = True
                            target = next(
                                e
                                for e in playback
                                if e["tool"] == "read_ticket" and e["kind"] == "TOOL_CALL_COMPLETED"
                            )
                            before = store.export(rid)["digest"]
                            start = time.perf_counter()
                            branch = engine.fork(
                                rid, target["event_id"], fixture["intervention"]["replacement"]
                            )
                            row["branch_ms"] = (time.perf_counter() - start) * 1000
                            bo = branch["comparison"]["branch_outcome"]
                            row["branch_valid"] = (
                                bo["final_files"] == fixture["intervention"]["expected_files"]
                                and bo["task_correct"] == fixture["intervention"]["expected_correct"]
                                and before == store.export(rid)["digest"]
                                and journal_check(store, branch["branch_id"])[0]
                            )
                        row["attempt_success"] = (
                            row["oracle_match"]
                            and row["replay_success"]
                            and row["restored_count"] == row["checkpoint_count"]
                            and row["accounted_mutations"] == row["mutations"]
                            and (not row["branch_attempted"] or row["branch_valid"])
                        )
                        row["category"] = "REPLAY_SUCCESS" if row["attempt_success"] else "INTEGRITY_FAILURE"
                    except Exception as exc:  # noqa: BLE001 — include failures in denominator
                        row["category"] = failure_category(stage, exc)
                        row["error"] = str(exc)
                        row["failure_stage"] = stage
                        row["failed_stage_ms"] = (time.perf_counter() - start) * 1000
                        row["error_code"] = exc.code if isinstance(exc, GFError) else type(exc).__name__
                        if isinstance(exc, GFError) and isinstance(exc.details, dict):
                            row["failed_run_id"] = exc.details.get("failed_run_id")
                    row["attempt_ms"] = (time.perf_counter() - attempt_started) * 1000
                    rows.append(row)
        cleanup_started = time.perf_counter()
        db_bytes = sum(p.stat().st_size for p in Path(directory).glob("bench.db*"))
    cleanup_ms = (time.perf_counter() - cleanup_started) * 1000
    timings = {}
    for key in [
        "record_ms",
        "unrecorded_ms",
        "playback_ms",
        "replay_ms",
        "branch_ms",
        "attempt_ms",
        "checkpoint_restore_ms",
    ]:
        values = sorted(r[key] for r in rows if key in r)
        if values:
            timings[key] = {
                "samples": len(values),
                "median": statistics.median(values),
                "p95": values[max(0, int(len(values) * 0.95) - 1)],
                "maximum": max(values),
            }
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "uncommitted"
    report = {
        "date": datetime.now(UTC).isoformat(),
        "git_commit": commit,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "fixture_version": suite["version"],
        "command": "python -m ghostframe.cli benchmark",
        "repetitions": repetitions,
        "warmup": "one development incident; excluded",
        "phases": {
            "recording": {
                "entered": sum(r["record_entered"] for r in rows),
                "completed": sum(r["record_success"] for r in rows),
            },
            "replay": {
                "entered": sum(r["replay_entered"] for r in rows),
                "successful": sum(r["replay_success"] for r in rows),
            },
            "end_to_end": {"attempts": len(rows), "successful": sum(r["attempt_success"] for r in rows)},
            "categories": {
                category: sum(r["category"] == category for r in rows)
                for category in sorted({r["category"] for r in rows})
            },
            "environment_preparation_ms": environment_ms,
            "fixture_loading_ms": fixture_loading_ms,
            "cleanup_ms": cleanup_ms,
            "nesting": "Source/replay engine calls include event, checkpoint, persistence and operation cleanup. Restore samples below are a separate post-replay validation phase; do not add overlapping diagnostic spans.",
            "checkpoint_restore_samples_ms": [
                v for r in rows for v in r.get("checkpoint_restore_samples_ms", [])
            ],
        },
        "sets": {
            group: {
                "unique_fixtures": len(suite[group]),
                "attempts": sum(r["set"] == group for r in rows),
                "eligible": sum(r["set"] == group for r in rows),
                "replay_success": sum(r["set"] == group and r["replay_success"] for r in rows),
                "oracle_match": sum(r["set"] == group and r["oracle_match"] for r in rows),
            }
            for group in ["development", "regression"]
        },
        "branches": {
            "attempted": sum(r["branch_attempted"] for r in rows),
            "valid": sum(r["branch_valid"] for r in rows),
        },
        "checkpoints": {
            "attempted": sum(r.get("checkpoint_count", 0) for r in rows),
            "restored": sum(r.get("restored_count", 0) for r in rows),
        },
        "side_effects": {
            "observed": sum(r.get("mutations", 0) for r in rows),
            "accounted": sum(r.get("accounted_mutations", 0) for r in rows),
        },
        "timings": timings,
        "database_bytes": db_bytes,
        "failures": [r for r in rows if r["error"] or not r["oracle_match"] or not r["replay_success"]],
        "baselines": {
            "unrecorded": "Same driver and virtual tools, no ledger",
            "playback": "SQLite event retrieval only; cannot validate computational fidelity or branch",
        },
        "limitations": [
            "Regression set was authored separately but is not externally blinded.",
            "Small synthetic workload; recording includes durable SQLite transactions and full snapshots.",
            "No live model, human debugging-time study, or competitor performance claim.",
            "Integrity fault tests and API/browser timings are reported separately in test/audit reports.",
        ],
    }
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "latest.json").write_text(json.dumps(report, indent=2))
    (destination / "latest.md").write_text(
        "# Measured benchmark\n\n```json\n" + json.dumps(report, indent=2) + "\n```\n"
    )
    keys = sorted(set().union(*(r.keys() for r in rows)))
    with (destination / "raw_results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    return report
