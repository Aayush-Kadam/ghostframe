"""Opt-in, synthetic-only recording diagnostics with an independent supervisor."""

from __future__ import annotations

import argparse
import contextvars
import ctypes
import faulthandler
import functools
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path
from typing import Any

from .benchmark import failure_category
from .fixtures import flagship, load
from .models import GFError
from .policies import RetentionPolicy
from .runtime import DocumentDriver, Engine
from .sandbox import Sandbox
from .store import Store

MAX_BYTES = 1024 * 1024
STAGES = {
    "worker_start",
    "attempt",
    "environment_preparation",
    "fixture_initialization",
    "source_recording",
    "source_execution",
    "event_recording",
    "recording_finalization",
    "checkpoint_creation",
    "checkpoint_restoration",
    "semantic_comparison",
    "replay_initialization",
    "replay_execution",
    "cleanup",
    "controlled_pause",
    "conditioning",
    "create",
    "verify",
    "db_schema_init",
    "db_sql_read",
    "db_sql_other",
    "db_transaction_begin",
    "db_event_insert",
    "db_checkpoint_insert",
    "db_maintenance_delete",
    "db_connection_acquisition",
    "db_commit",
    "db_rollback",
    "db_close",
    "unrecognized_stage",
}
SCOPES = {
    "environment_preparation",
    "fixture_initialization",
    "source_recording",
    "replay_execution",
    "semantic_comparison",
    "cleanup",
    "maintenance",
    "conditioning",
}


def write_json(path, value):
    data = json.dumps(value, indent=2).encode("utf-8")
    if len(data) > MAX_BYTES:
        raise RuntimeError("Diagnostic output cap reached")
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


class Diagnostic:
    def __init__(self, root, detailed):
        self.root, self.detailed = root, detailed
        self.scope = contextvars.ContextVar("diagnostic_scope", default="environment_preparation")
        self.stack = threading.local()
        self.stats = {}
        self.lock = threading.RLock()
        self.attempt = -1
        self.markers = 0
        self.truncated = False
        self.rotations = 0
        self.progress_errors = 0

    def progress(self, stage, status):
        stage = stage if stage in STAGES else "unrecognized_stage"
        status = status if status in {"started", "completed"} else "unknown"
        if threading.current_thread() is not threading.main_thread():
            return
        if stage in {"db_sql_read", "db_sql_other", "source_execution"}:
            return  # Timed in aggregates; avoid a heartbeat write for every fast read.
        if stage.startswith("db_") and status == "completed":
            return  # Outer stage completion plus timing totals capture the return.
        self.markers += 1
        if self.markers > 20000:
            self.truncated = True
            return
        value = {
            "attempt": self.attempt,
            "scope": self.scope.get() if self.scope.get() in SCOPES else "unrecognized_scope",
            "stage": stage,
            "status": status,
            "monotonic": time.monotonic(),
            "pid": os.getpid(),
            "thread_id": threading.get_ident(),
            "sequence": self.markers,
        }
        path = self.root / "progress.jsonl"
        data = json.dumps(value, separators=(",", ":")) + "\n"
        rotate = path.exists() and path.stat().st_size + len(data.encode()) > 128 * 1024
        # Append instead of replace: Windows readers can hold a sharing lock on
        # the heartbeat. Monitoring must never make a storage call fail.
        try:
            # A bounded heartbeat ring, not a durable per-operation event log.
            # Timings and external samples retain evidence; sequence never resets.
            with path.open("w" if rotate else "a", encoding="utf-8") as output:
                output.write(data)
            if rotate:
                self.rotations += 1
        except OSError:
            self.progress_errors += 1
            self.truncated = True

    @contextmanager
    def span(self, stage):
        stage = stage if stage in STAGES else "unrecognized_stage"
        self.progress(stage, "started")
        stack = getattr(self.stack, "frames", [])
        self.stack.frames = stack
        item = [time.monotonic(), 0.0]
        stack.append(item)
        try:
            yield
        finally:
            elapsed = time.monotonic() - item[0]
            stack.pop()
            if stack:
                stack[-1][1] += elapsed
            scope = self.scope.get() if self.scope.get() in SCOPES else "unrecognized_scope"
            key = scope + "." + stage
            with self.lock:
                stats = self.stats.setdefault(
                    key,
                    {"calls": 0, "inclusive_seconds": 0.0, "exclusive_seconds": 0.0, "maximum_seconds": 0.0},
                )
                stats["calls"] += 1
                stats["inclusive_seconds"] += elapsed
                stats["exclusive_seconds"] += max(0, elapsed - item[1])
                stats["maximum_seconds"] = max(stats["maximum_seconds"], elapsed)
            self.progress(stage, "completed")

    def install(self):
        original_connect = sqlite3.connect
        diag = self

        class TimedConnection(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                text = sql.lstrip().upper()
                category = (
                    "transaction_begin"
                    if text.startswith("BEGIN")
                    else "event_insert"
                    if text.startswith("INSERT INTO EVENTS")
                    else "checkpoint_insert"
                    if text.startswith("INSERT INTO CHECKPOINTS")
                    else "maintenance_delete"
                    if text.startswith("DELETE")
                    else "sql_read"
                    if text.startswith("SELECT")
                    else "sql_other"
                )
                with diag.span("db_" + category):
                    return super().execute(sql, *args, **kwargs)

            def executescript(self, sql, *args, **kwargs):
                with diag.span("db_schema_init"):
                    return super().executescript(sql, *args, **kwargs)

            def __exit__(self, kind, value, tb):
                with diag.span("db_rollback" if kind else "db_commit"):
                    return super().__exit__(kind, value, tb)

            def close(self):
                with diag.span("db_close"):
                    return super().close()

        def connect(*args, **kwargs):
            kwargs["factory"] = TimedConnection
            with diag.span("db_connection_acquisition"):
                return original_connect(*args, **kwargs)

        sqlite3.connect = connect
        for cls, names in [
            (Store, ["create", "append", "checkpoint", "restore", "verify", "cleanup"]),
            (DocumentDriver, ["action", "observe"]),
            (Sandbox, ["call"]),
        ]:
            for name in names:
                original = getattr(cls, name)

                def wrap(function, label):
                    @functools.wraps(function)
                    def timed(*args, **kwargs):
                        category = (
                            "recording_finalization"
                            if label == "append" and len(args) > 2 and args[2] == "RUN_COMPLETED"
                            else "event_recording"
                            if label == "append"
                            else "checkpoint_creation"
                            if label == "checkpoint"
                            else "checkpoint_restoration"
                            if label == "restore"
                            else "source_execution"
                            if label in ["action", "observe", "call"]
                            else label
                        )
                        with diag.span(category):
                            return function(*args, **kwargs)

                    return timed

                setattr(cls, name, wrap(original, name))


def process_sample(pid):
    if os.name != "nt":
        return {"cpu_seconds": None, "working_set_bytes": None, "status": "UNAVAILABLE"}
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x10, False, pid)
    if not handle:
        return {"cpu_seconds": None, "working_set_bytes": None, "status": "ACCESS_UNAVAILABLE"}

    class Memory(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in [
                "peak",
                "working",
                "paged_peak",
                "paged",
                "nonpaged_peak",
                "nonpaged",
                "pagefile",
                "pagefile_peak",
            ]
        ]

    try:
        creation, exit_time, kernel_time, user = [wintypes.FILETIME() for _ in range(4)]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        cpu = None
        if kernel.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user),
        ):
            cpu = (
                (kernel_time.dwHighDateTime << 32)
                + kernel_time.dwLowDateTime
                + (user.dwHighDateTime << 32)
                + user.dwLowDateTime
            ) / 1e7
        memory = Memory()
        memory.cb = ctypes.sizeof(memory)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        available = psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb)
        return {
            "cpu_seconds": cpu,
            "working_set_bytes": memory.working if available else None,
            "status": "CAPTURED" if cpu is not None and available else "PARTIAL",
        }
    finally:
        kernel.CloseHandle(handle)


def sanitize_stack(text):
    frames = []
    for line in text.splitlines():
        match = re.match(r"\s+([\w<>]+) \((.*):(\d+)\)$", line)
        fault = re.match(r'\s+File "(.*)", line (\d+) in ([\w<>]+)', line)
        if match:
            function, file, number = match.groups()
        elif fault:
            file, number, function = fault.groups()
        else:
            continue
        base = Path(file).name
        if base in {
            "forensics.py",
            "store.py",
            "runtime.py",
            "policies.py",
            "models.py",
            "sandbox.py",
            "threading.py",
            "contextlib.py",
            "subprocess.py",
            "socket.py",
            "proactor_events.py",
            "windows_events.py",
        }:
            frames.append({"module": base, "function": function, "line": int(number)})
    return frames[:256]


def supervise(
    output,
    fixture="E2",
    repetitions=1,
    detailed=False,
    seed=None,
    activity=False,
    sampler=None,
    control="none",
    deadline=300,
    conditioned=False,
):
    if (
        fixture not in {f["id"] for g in ["development", "regression"] for f in load()[g]}
        or not 1 <= repetitions <= 10
        or not 1 <= deadline <= 300
    ):
        raise ValueError("Invalid bounded synthetic diagnostic configuration")
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    database = root / "synthetic.db"
    if seed:
        with closing(sqlite3.connect(seed)) as source, closing(sqlite3.connect(database)) as target:
            source.backup(target)
    command = [
        getattr(sys, "_base_executable", sys.executable),
        "-m",
        "ghostframe.forensics",
        "--worker",
        "--output",
        str(root),
        "--fixture",
        fixture,
        "--repetitions",
        str(repetitions),
        "--control",
        control,
    ]
    if detailed:
        command.append("--detailed")
    if activity:
        command.append("--activity")
    if conditioned:
        command.append("--conditioned")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)
    start = time.monotonic()
    with (root / "raw-child-stderr.txt").open("w") as err:
        child = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=err,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        write_json(
            root / "manifest.json",
            {
                "worker_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "fixture": fixture,
                "repetitions": repetitions,
                "detailed": detailed,
                "activity": activity,
                "control": control,
                "pid": child.pid,
                "supervisor_pid": os.getpid(),
                "process_deadline_seconds": deadline,
                "product_seconds": 60,
                "busy_timeout_seconds": 20,
                "seeded": bool(seed),
            },
        )
        samples: list[dict[str, Any]] = []
        captures: list[dict[str, Any]] = []
        last_sequence = None
        last_progress = start
        attempt_started = start
        last_attempt = None
        progress = {}
        terminated = False
        while child.poll() is None:
            now = time.monotonic()
            try:
                content = (root / "progress.jsonl").read_text()
                complete = content[: content.rfind("\n")].splitlines()
                if complete:
                    progress = json.loads(complete[-1])
                if progress.get("sequence") != last_sequence:
                    last_sequence = progress.get("sequence")
                    last_progress = now
                if progress.get("attempt") != last_attempt:
                    last_attempt = progress.get("attempt")
                    attempt_started = now
            except (OSError, ValueError):
                pass
            samples.append(
                {
                    "elapsed_seconds": now - start,
                    "no_observed_progress_seconds": now - last_progress,
                    "state": "ALIVE_NO_OBSERVED_PROGRESS"
                    if now - last_progress >= 2
                    else "ALIVE_PROGRESSING",
                    "scope": progress.get("scope"),
                    "stage": progress.get("stage"),
                    "attempt": progress.get("attempt"),
                    **process_sample(child.pid),
                }
            )
            if now - last_progress >= 2 and progress.get("scope") == "source_recording" and len(captures) < 2:
                capture = {"elapsed_seconds": now - start, "status": "TOOL_UNAVAILABLE", "frames": []}
                if sampler:
                    try:
                        sample_result = subprocess.run(
                            [str(sampler), "dump", "--pid", str(child.pid)],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=8,
                        )
                        frames = sanitize_stack(sample_result.stdout)
                        capture.update(
                            status="CAPTURED" if sample_result.returncode == 0 and frames else "FAILED",
                            frames=frames,
                            exit_code=sample_result.returncode,
                        )
                        (root / f"raw-stack-{len(captures)}.txt").write_text(
                            (sample_result.stdout + sample_result.stderr)[:MAX_BYTES], encoding="utf-8"
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        capture["status"] = "FAILED"
                captures.append(capture)
            too_large = any(p.stat().st_size > MAX_BYTES for p in root.glob("raw-*.txt"))
            if now - start > deadline or now - attempt_started > 90 or len(samples) >= 2048 or too_large:
                child.terminate()
                terminated = True
                break
            time.sleep(0.2)
        child.wait(timeout=10)
    try:
        rows = json.loads((root / "attempts.json").read_text())
    except (OSError, ValueError):
        rows = []
    for index in range(len(rows), repetitions):
        rows.append(
            {
                "attempt": index,
                "fixture": fixture,
                "record_success": False,
                "replay_entered": False,
                "replay_success": False,
                "attempt_success": False,
                "category": "BENCHMARK_HARNESS_TIMEOUT" if terminated else "ENVIRONMENT_FAILURE",
                "started": progress.get("attempt") == index,
            }
        )
    try:
        timing_data = json.loads((root / "timings.json").read_text())
    except (OSError, ValueError):
        timing_data = {}
    cleanup_valid = (
        child.returncode == 0
        and not terminated
        and all(timing_data.get(k) for k in ["sqlite_integrity", "foreign_keys", "background_stopped"])
    )
    for row in rows:
        row["process_cleanup_success"] = cleanup_valid
        if row.get("attempt_success") and not cleanup_valid:
            row["attempt_success"] = False
            row["category"] = "BENCHMARK_HARNESS_TIMEOUT" if terminated else "ENVIRONMENT_FAILURE"
    fault_path = root / "raw-faulthandler.txt"
    fault_frames = sanitize_stack(fault_path.read_text(errors="replace")) if fault_path.exists() else []
    result = {
        "rows": rows,
        "exit_code": child.returncode,
        "harness_terminated": terminated,
        "elapsed_seconds": time.monotonic() - start,
        "samples": samples,
        "stack_captures": captures,
        "faulthandler_frames": fault_frames,
        "diagnostic_completeness": {
            "process_samples": bool(samples),
            "progress_complete": not timing_data.get("marker_cap_reached", True),
            "database_timing_captured": bool(timing_data.get("phases")),
            "cpu_available": any(x["cpu_seconds"] is not None for x in samples),
            "memory_available": any(x["working_set_bytes"] is not None for x in samples),
            "external_stack_successes": sum(x["status"] == "CAPTURED" for x in captures),
            "faulthandler_captured": bool(fault_frames),
            "missing_progress_is_not_deadlock_proof": True,
        },
    }
    write_json(root / "supervisor.json", result)
    write_json(root / "attempts-final.json", rows)
    return result


def worker(args):
    root = Path(args.output)
    diag = Diagnostic(root, args.detailed)
    if args.detailed:
        diag.install()
    diag.progress("worker_start", "started")
    fixture = next(f for g in ["development", "regression"] for f in load()[g] if f["id"] == args.fixture)
    with diag.span("environment_preparation"):
        store = Store(root / "synthetic.db")
    engine = Engine(store)
    conditioning = {}
    if args.conditioned:
        diag.scope.set("conditioning")
        with diag.span("conditioning"):
            control_fixture = next(f for f in load()["development"] if f["id"] == "F2")
            original_id = engine.run(control_fixture)
            before = store.export(original_id)["digest"]
            event = next(
                e
                for e in store.events(original_id)
                if e["tool"] == "read_ticket" and e["kind"] == "TOOL_CALL_COMPLETED"
            )
            engine.fork(
                original_id, event["event_id"], {"action": "delete", "target": "/documents/draft_report.txt"}
            )
            old = Store(store.path, clock=lambda: 0, retention=RetentionPolicy(cleanup_on_startup=False))
            expired = old.create({"name": "synthetic expiry control"})
            old.append(expired, "RUN_STARTED", {})
            old.append(expired, "RUN_COMPLETED", {})
            cleanup = store.cleanup(apply=True)
            conditioning = {
                "f2_completed": True,
                "parent_preserved": before == store.export(original_id)["digest"],
                "expired_control_removed": expired in cleanup["expired_runs"],
            }
    background_rows: list[dict[str, Any]] = []
    stop = threading.Event()

    def background():
        diag.scope.set("maintenance")
        for index in range(10):
            if stop.is_set():
                break
            begin = time.monotonic()
            try:
                rid = Engine(store).run(flagship())
                event = next(
                    e
                    for e in store.events(rid)
                    if e["tool"] == "read_ticket" and e["kind"] == "TOOL_CALL_COMPLETED"
                )
                Engine(store).fork(
                    rid, event["event_id"], {"action": "delete", "target": "/documents/draft_report.txt"}
                )
                store.cleanup(apply=True)
                background_rows.append(
                    {"iteration": index, "begin": begin, "end": time.monotonic(), "success": True}
                )
            except Exception as exc:  # noqa: BLE001 - retain every diagnostic failure without raw messages
                background_rows.append(
                    {
                        "iteration": index,
                        "begin": begin,
                        "end": time.monotonic(),
                        "success": False,
                        "error_code": exc.code if isinstance(exc, GFError) else type(exc).__name__,
                    }
                )
            time.sleep(0.01)

    thread = threading.Thread(target=background, daemon=True) if args.activity else None
    if thread:
        thread.start()
    ready = threading.Event()

    def locked_writer():
        with sqlite3.connect(store.path) as db:
            db.execute("BEGIN IMMEDIATE")
            ready.set()
            time.sleep(3.5)

    lock_thread = (
        threading.Thread(target=locked_writer, daemon=True) if args.control == "storage_wait" else None
    )
    if lock_thread:
        lock_thread.start()
        ready.wait(timeout=5)
    if args.control in ["pause", "terminate"]:
        original = store.append
        paused = [False]

        def pause(*a, **k):
            if len(a) > 1 and a[1] == "TOOL_CALL_COMPLETED" and not paused[0]:
                paused[0] = True
                diag.progress("controlled_pause", "started")
                time.sleep(4 if args.control == "pause" else 30)
            return original(*a, **k)

        store.append = pause  # type: ignore[method-assign]
    rows = []
    with (root / "raw-faulthandler.txt").open("w") if args.detailed else nullcontext(None) as stack_file:
        for index in range(args.repetitions):
            diag.attempt = index
            diag.scope.set("fixture_initialization")
            diag.progress("attempt", "started")
            row = {
                "attempt": index,
                "fixture": args.fixture,
                "record_success": False,
                "replay_entered": False,
                "replay_success": False,
                "attempt_success": False,
                "category": "UNKNOWN",
                "started": True,
            }
            if args.detailed:
                assert stack_file is not None
                faulthandler.dump_traceback_later(2, repeat=False, file=stack_file, exit=False)
            started = time.monotonic()
            try:
                diag.scope.set("source_recording")
                begin = time.monotonic()
                with diag.span("source_recording"):
                    rid = engine.run(fixture)
                row["record_ms"] = (time.monotonic() - begin) * 1000
                row["record_success"] = True
                summary = store.summary(rid)["outcome"]
                row["record_oracle_match"] = (
                    summary["final_files"] == fixture["expected_files"]
                    and summary["task_correct"] == fixture["expected_correct"]
                    and summary["result"].get("error") == fixture["expected_error"]
                )
                before = store.export(rid)["digest"]
                row["replay_entered"] = True
                diag.scope.set("replay_execution")
                begin = time.monotonic()
                with diag.span("replay_execution"):
                    replay = engine.replay(rid)
                row["replay_ms"] = (time.monotonic() - begin) * 1000
                row["replay_success"] = replay["status"] == "REPLAY_SUCCESS"
                diag.scope.set("semantic_comparison")
                with diag.span("semantic_comparison"):
                    row["parent_preserved"] = before == store.export(rid)["digest"]
                    row["integrity_valid"] = store.verify(replay["run_id"])["valid"]
                row["attempt_success"] = all(
                    row[k]
                    for k in ["record_oracle_match", "replay_success", "parent_preserved", "integrity_valid"]
                )
                row["category"] = "REPLAY_SUCCESS" if row["attempt_success"] else "INTEGRITY_FAILURE"
            except Exception as exc:  # noqa: BLE001 - retain every diagnostic failure without raw messages
                code = exc.code if isinstance(exc, GFError) else type(exc).__name__
                row["error_code"] = code
                row["category"] = failure_category(
                    "deterministic_replay" if row["replay_entered"] else "source_recording", exc
                )

            finally:
                if args.detailed:
                    faulthandler.cancel_dump_traceback_later()
            row["attempt_ms"] = (time.monotonic() - started) * 1000
            rows.append(row)
            write_json(root / "attempts.json", rows)
            diag.progress("attempt", "completed")
    stop.set()
    if thread:
        thread.join(timeout=20)
    if lock_thread:
        lock_thread.join(timeout=5)
    diag.scope.set("cleanup")
    with diag.span("cleanup"), store.connect() as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        foreign_keys = not db.execute("PRAGMA foreign_key_check").fetchall()
    write_json(
        root / "timings.json",
        {
            "phases": diag.stats,
            "markers": diag.markers,
            "marker_cap_reached": diag.truncated,
            "heartbeat_rotations": diag.rotations,
            "progress_write_errors": diag.progress_errors,
            "sqlite_integrity": integrity,
            "foreign_keys": foreign_keys,
            "background": background_rows,
            "conditioning": conditioning,
            "background_stopped": not thread or not thread.is_alive(),
            "nested_spans": "inclusive overlaps; exclusive subtracts directly nested instrumented spans; scopes/threads must be kept separate",
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fixture", default="E2")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--detailed", action="store_true")
    parser.add_argument("--sampler")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--conditioned", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--activity", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--control",
        choices=["none", "pause", "storage_wait", "terminate"],
        default="none",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 10 or args.fixture not in {
        f["id"] for g in ["development", "regression"] for f in load()[g]
    }:
        parser.error("Only bounded repetitions of bundled synthetic fixtures are supported")
    if args.worker:
        try:
            manifest = json.loads((Path(args.output) / "manifest.json").read_text())
        except (OSError, ValueError):
            parser.error("Worker requires its owning supervisor manifest")
        if manifest.get("pid") != os.getpid():
            parser.error("Worker identity does not match the owning supervisor")

        worker(args)
    else:
        result = supervise(args.output, args.fixture, args.repetitions, args.detailed, sampler=args.sampler)
        print(
            json.dumps(
                {
                    "attempts": len(result["rows"]),
                    "successes": sum(r["attempt_success"] for r in result["rows"]),
                    "harness_terminated": result["harness_terminated"],
                }
            )
        )


if __name__ == "__main__":
    main()
